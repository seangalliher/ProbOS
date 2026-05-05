"""AD-690: Dream Step 7i — Relationship inference from co-occurring episode agents.

Pure service. Given a list of recent episodes, finds AGENT→AGENT pairs that
co-participated, skips pairs already linked in the knowledge edge store or
previously rejected, asks an LLM to classify the relationship from a small
whitelist (`reports_to` | `depends_on`), and emits new ``KnowledgeEdge``
rows tagged ``source_agent="dream_step10"`` /
``source_duty="relationship_inference"``.

Anti-contamination guards (all mandatory in v1):

* per-entity edge cap (``max_inferences_per_entity``)
* per-run pair cap (``max_pairs_per_run``)
* min-confidence floor (``min_confidence``) — sub-threshold pairs cached
* rejection cache (LLM null / parse-failure / off-whitelist all cached)
* relation whitelist (``REPORTS_TO``, ``DEPENDS_ON`` only in v1)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEdgeStorage,
    KnowledgeEntityType,
    KnowledgeRelationType,
)
from probos.knowledge.rejection_cache import RejectionCacheStorage
from probos.types import Episode, LLMRequest
from probos.utils.json_extract import extract_json

logger = logging.getLogger(__name__)


_AGENT_AGENT_RELATION_WHITELIST: tuple[KnowledgeRelationType, ...] = (
    KnowledgeRelationType.REPORTS_TO,
    KnowledgeRelationType.DEPENDS_ON,
)

_RESPONSE_MAX_TOKENS = 200

_LLM_PROMPT_TEMPLATE = """\
You are classifying the working relationship between two ProbOS agents that
co-occurred in recent episodes. Choose ONE relation, or return null if no
clear relationship exists. Reply with ONLY a JSON object.

Allowed relations:
- "reports_to"  — A reports to B in the org chain of command.
- "depends_on"  — A's work depends on outputs/decisions from B.
- null          — no clear working relationship between A and B.

Agent A: {a}
Agent B: {b}

Respond with EXACTLY this JSON shape:
{{"relation": "<relation_or_null>", "confidence": <0.0-1.0>, "rationale": "<one sentence>"}}
"""


@dataclass(frozen=True)
class RelationshipInferenceResult:
    """Counters returned by :func:`infer_relationships_from_episodes`."""

    candidate_pairs: int = 0
    inferred_edges: int = 0
    relationship_pairs_rejected: int = 0
    relationship_pairs_capped: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "candidate_pairs": self.candidate_pairs,
            "inferred_edges": self.inferred_edges,
            "relationship_pairs_rejected": self.relationship_pairs_rejected,
            "relationship_pairs_capped": self.relationship_pairs_capped,
        }


def _extract_agent_pairs(episodes: list[Episode]) -> list[tuple[str, str]]:
    """Build deduped ``(min, max)`` agent pair list from episodes.

    Episodes with fewer than 2 ``agent_ids`` are skipped. Pairs are sorted so
    ``(a, b)`` and ``(b, a)`` collapse. Insertion order preserved via
    ``dict.fromkeys``.
    """
    seen: dict[tuple[str, str], None] = {}
    for episode in episodes:
        agent_ids = list(getattr(episode, "agent_ids", []) or [])
        if len(agent_ids) < 2:
            continue
        # Dedupe agents within the episode first to avoid (a,a)
        unique = list(dict.fromkeys(agent_ids))
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                a, b = unique[i], unique[j]
                pair = (a, b) if a <= b else (b, a)
                if pair[0] == pair[1]:
                    continue
                seen.setdefault(pair, None)
    return list(seen.keys())


async def _classify_pair_with_llm(
    agent_a: str,
    agent_b: str,
    *,
    llm_client: Any,
) -> tuple[KnowledgeRelationType | None, float, str]:
    """Ask the LLM to classify the (a, b) relationship.

    Returns ``(relation, confidence, rationale_or_reason)``. On any rejection
    path, ``relation`` is ``None`` and the third element is a stable reason
    string suitable for the rejection cache.
    """
    req = LLMRequest(
        prompt=_LLM_PROMPT_TEMPLATE.format(a=agent_a, b=agent_b),
        tier="standard",
        temperature=0.0,
        max_tokens=_RESPONSE_MAX_TOKENS,
    )
    try:
        resp = await llm_client.complete(req)
    except Exception:
        logger.debug(
            "AD-690: LLM call failed for pair (%s,%s)", agent_a, agent_b, exc_info=True
        )
        return (None, 0.0, "llm_call_failure")

    content = getattr(resp, "content", "") or ""
    try:
        parsed = extract_json(content)
    except Exception:
        return (None, 0.0, "llm_parse_failure")

    relation_raw = parsed.get("relation")
    if relation_raw is None:
        return (None, 0.0, "llm_returned_null")

    if not isinstance(relation_raw, str):
        return (None, 0.0, "llm_parse_failure")

    try:
        relation = KnowledgeRelationType(relation_raw)
    except ValueError:
        return (None, 0.0, "relation_not_in_whitelist")

    if relation not in _AGENT_AGENT_RELATION_WHITELIST:
        return (None, 0.0, "relation_not_in_whitelist")

    try:
        conf = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))

    rationale = parsed.get("rationale", "")
    if not isinstance(rationale, str):
        rationale = ""
    return (relation, conf, rationale)


async def infer_relationships_from_episodes(
    *,
    episodes: list[Episode],
    knowledge_edges: KnowledgeEdgeStorage,
    llm_client: Any,
    rejection_cache: RejectionCacheStorage,
    max_pairs_per_run: int = 50,
    max_inferences_per_entity: int = 5,
    min_confidence: float = 0.6,
) -> RelationshipInferenceResult:
    """Infer AGENT→AGENT relationships from co-occurring episode agents.

    See module docstring for the v1 contract and anti-contamination guards.
    """
    pairs = _extract_agent_pairs(episodes)
    candidate_pairs = len(pairs)
    inferred_edges = 0
    pairs_rejected = 0
    pairs_capped = 0

    per_entity_counter: dict[str, int] = {}
    processed = 0

    for a, b in pairs:
        if processed >= max_pairs_per_run:
            break

        # Replay-skip: silently drop pairs we've already classified-and-rejected.
        try:
            already_rejected = await rejection_cache.was_rejected(a, b)
        except Exception:
            logger.debug(
                "AD-690: rejection cache lookup failed for (%s,%s); treating as not-rejected",
                a, b, exc_info=True,
            )
            already_rejected = False
        if already_rejected:
            continue

        # Existing edge (either direction) → skip without LLM call.
        try:
            forward = await knowledge_edges.find_edges(
                source_id=a, target_id=b, limit=1
            )
            reverse = await knowledge_edges.find_edges(
                source_id=b, target_id=a, limit=1
            )
        except Exception:
            logger.debug(
                "AD-690: find_edges failed for (%s,%s); skipping pair",
                a, b, exc_info=True,
            )
            continue
        if forward or reverse:
            continue

        if (
            per_entity_counter.get(a, 0) >= max_inferences_per_entity
            or per_entity_counter.get(b, 0) >= max_inferences_per_entity
        ):
            pairs_capped += 1
            processed += 1
            continue

        relation, conf, reason = await _classify_pair_with_llm(
            a, b, llm_client=llm_client
        )
        processed += 1

        if relation is None:
            try:
                await rejection_cache.record_rejection(
                    source_id=a, target_id=b, relation=None, reason=reason,
                )
            except Exception:
                logger.debug(
                    "AD-690: rejection cache write failed for (%s,%s)",
                    a, b, exc_info=True,
                )
            pairs_rejected += 1
            continue

        if conf < min_confidence:
            try:
                await rejection_cache.record_rejection(
                    source_id=a,
                    target_id=b,
                    relation=relation.value,
                    reason=f"below_threshold_{conf:.2f}",
                )
            except Exception:
                logger.debug(
                    "AD-690: rejection cache write failed for (%s,%s)",
                    a, b, exc_info=True,
                )
            pairs_rejected += 1
            continue

        edge = KnowledgeEdge(
            source_type=KnowledgeEntityType.AGENT,
            source_id=a,
            relation=relation,
            target_type=KnowledgeEntityType.AGENT,
            target_id=b,
            confidence=conf,
            weight=0.5,
            source_agent="dream_step10",
            source_duty="relationship_inference",
        )
        try:
            await knowledge_edges.add_edge(edge)
        except Exception as e:
            logger.warning(
                "AD-690: add_edge failed for (%s,%s): %s; pair will retry next cycle",
                a, b, e,
            )
            continue

        inferred_edges += 1
        per_entity_counter[a] = per_entity_counter.get(a, 0) + 1
        per_entity_counter[b] = per_entity_counter.get(b, 0) + 1

    return RelationshipInferenceResult(
        candidate_pairs=candidate_pairs,
        inferred_edges=inferred_edges,
        relationship_pairs_rejected=pairs_rejected,
        relationship_pairs_capped=pairs_capped,
    )
