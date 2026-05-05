"""NL-to-Graph Query Service — Ship's Computer structural routing (AD-691).

Phase B (Intelligence) of the Unified Knowledge Graph stack. v1 ships an
LLM-driven 2-phase service that translates natural-language queries into
typed graph traversals over the AD-687 KnowledgeEdgeStore and synthesizes
an answer with explicit graph-edge provenance citations.

Phase 1 (extraction): LLM returns strict JSON identifying entities + a
relation filter + a query intent label. Phase 2 (synthesis): LLM is given
the structured graph results inline and asked to compose an answer that
cites every graph-derived fact as ``[graph: <edge.id>]``.

Hop-proximity scoring uses ``0.6 ** (hop - 1)`` — direct=1.0, hop-2=0.6,
hop-3=0.36 — extending the AD-688 formula to the AD-687 ceiling of 3.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEntityType,
    KnowledgeRelationType,
    MAX_HOPS_CEILING,
)
from probos.types import LLMRequest, LLMResponse
from probos.utils.json_extract import extract_json

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────

_GRAPH_HOP_PROXIMITY_BASE = 0.6  # hop-N proximity = base ** (N - 1)
_CITATION_RE = re.compile(r"\[graph:\s*([0-9a-fA-F]{16,})\s*\]")
_RELATION_VALUES = frozenset(rt.value for rt in KnowledgeRelationType)
_ENTITY_TYPE_VALUES = frozenset(et.value for et in KnowledgeEntityType)


_PHASE1_SYSTEM_PROMPT = """\
You extract structured graph queries from natural language.

The knowledge graph contains typed entities (agent, department, incident,
decision, duty, finding, capability, standing_order) connected by typed
relations (reports_to, member_of, competent_in, resolved_by, involved_in,
informed_by, depends_on, produced_by, classified_as, originated_on).

Return ONLY a JSON object of the form:
{
  "entities": [{"id": "<entity-id>", "type": "<entity-type>"}, ...],
  "relation_filter": ["<relation>", ...],
  "intent": "find|traverse|count"
}

Rules:
- "entities" lists the subjects mentioned by the user. Use the most
  specific identifier you can extract verbatim from the query (e.g. an
  agent name, a department code).
- If the user does not mention any entity, return entities: [].
- "relation_filter" lists the relations the user is interested in. If
  the query is not relation-specific, return an empty list (means "any").
- "intent" is one of "find" (locate matching entities), "traverse"
  (walk relationships from a starting entity), or "count" (how many).
- Return JSON only — no commentary, no markdown fences."""


_PHASE2_SYSTEM_PROMPT = """\
You answer questions from structured graph results.

You will receive (a) the user's question, (b) a JSON list of typed graph
edges retrieved by the system. Each edge has an id, a source, a relation,
and a target.

Compose a concise natural-language answer. EVERY factual claim that comes
from a graph edge MUST be followed by a citation in the form
``[graph: <edge.id>]``. If multiple edges support the same claim, cite
each: ``[graph: id1] [graph: id2]``.

If the graph has no relevant edges, say "No relevant graph evidence" and
cite nothing. Do not invent edges. Do not invent ids."""


# ── Result dataclasses ────────────────────────────────────────────


@dataclass(frozen=True)
class EntityExtraction:
    """Phase-1 output: a single entity reference."""

    id: str
    type: str  # KnowledgeEntityType.value or unknown string

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type}


@dataclass(frozen=True)
class NLGraphQueryResult:
    """The full result of an NL-to-graph query."""

    query: str
    extracted_entities: list[EntityExtraction] = field(default_factory=list)
    edges_traversed: list[KnowledgeEdge] = field(default_factory=list)
    paths: list[list[KnowledgeEdge]] = field(default_factory=list)
    answer: str = ""
    provenance: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "extracted_entities": [e.to_dict() for e in self.extracted_entities],
            "edges_traversed": [e.to_dict() for e in self.edges_traversed],
            "paths": [[e.to_dict() for e in path] for path in self.paths],
            "answer": self.answer,
            "provenance": list(self.provenance),
        }


# ── Service ───────────────────────────────────────────────────────


class NLGraphQueryService:
    """LLM-driven NL→graph query and answer synthesis.

    Constructor takes the runtime so it can locate ``knowledge_edges`` and
    ``llm_client`` lazily (mirrors AD-661 ``DiagnosticContextService``). The
    service NEVER raises into the caller — every failure path returns a
    well-formed ``NLGraphQueryResult`` with a degraded answer.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        default_max_hops: int = 2,
        default_limit: int = 10,
        llm_tier: str = "standard",
        extraction_max_tokens: int = 600,
        synthesis_max_tokens: int = 800,
    ) -> None:
        self._runtime = runtime
        self._default_max_hops = default_max_hops
        self._default_limit = default_limit
        self._llm_tier = llm_tier
        self._extraction_max_tokens = extraction_max_tokens
        self._synthesis_max_tokens = synthesis_max_tokens

    async def query(
        self,
        natural_language: str,
        *,
        max_hops: int | None = None,
        limit: int | None = None,
    ) -> NLGraphQueryResult:
        """Translate ``natural_language`` to a graph traversal and synthesize
        an answer."""
        max_hops_eff = min(int(max_hops or self._default_max_hops), MAX_HOPS_CEILING)
        limit_eff = max(int(limit or self._default_limit), 1)

        edge_store = getattr(self._runtime, "knowledge_edges", None)
        llm = getattr(self._runtime, "llm_client", None)
        if edge_store is None or llm is None:
            logger.debug("AD-691: edge_store or llm_client missing; degrading")
            return NLGraphQueryResult(
                query=natural_language,
                answer="Knowledge graph or LLM unavailable.",
            )

        # Phase 1: entity extraction
        extraction = await self._phase1_extract(llm, natural_language)
        if extraction is None:
            return NLGraphQueryResult(
                query=natural_language,
                answer="Could not parse query.",
            )
        entities, relation_filter = extraction
        if not entities:
            return NLGraphQueryResult(
                query=natural_language,
                answer="No graph entities identified in query.",
            )

        # Graph step
        edges, paths = await self._gather_edges(
            edge_store=edge_store,
            entities=entities,
            relation_filter=relation_filter,
            max_hops=max_hops_eff,
            limit=limit_eff,
        )

        if not edges:
            return NLGraphQueryResult(
                query=natural_language,
                extracted_entities=entities,
                edges_traversed=[],
                paths=[],
                answer="No relevant graph evidence.",
                provenance=[],
            )

        # Phase 2: synthesis
        answer = await self._phase2_synthesize(llm, natural_language, edges)
        provenance = self._extract_citations(answer, allowed_ids={e.id for e in edges})

        return NLGraphQueryResult(
            query=natural_language,
            extracted_entities=entities,
            edges_traversed=edges,
            paths=paths,
            answer=answer,
            provenance=provenance,
        )

    # ── Phase 1 ───────────────────────────────────────────────

    async def _phase1_extract(
        self, llm: Any, nl_query: str,
    ) -> tuple[list[EntityExtraction], list[KnowledgeRelationType]] | None:
        request = LLMRequest(
            prompt=nl_query,
            system_prompt=_PHASE1_SYSTEM_PROMPT,
            tier=self._llm_tier,
            temperature=0.0,
            max_tokens=self._extraction_max_tokens,
        )
        try:
            response: LLMResponse = await llm.complete(request)
        except Exception:
            logger.warning("AD-691: phase-1 LLM call failed", exc_info=True)
            return None
        try:
            payload = extract_json(response.content or "")
        except ValueError:
            logger.warning("AD-691: phase-1 JSON parse failed; raw=%r",
                           (response.content or "")[:200])
            return None
        raw_entities = payload.get("entities")
        if not isinstance(raw_entities, list):
            return None
        entities: list[EntityExtraction] = []
        for item in raw_entities:
            if not isinstance(item, dict):
                continue
            eid = item.get("id")
            etype = item.get("type", "agent")
            if not isinstance(eid, str) or not eid.strip():
                continue
            entities.append(EntityExtraction(id=eid.strip(), type=str(etype)))
        raw_rels = payload.get("relation_filter") or []
        relation_filter: list[KnowledgeRelationType] = []
        if isinstance(raw_rels, list):
            for r in raw_rels:
                if isinstance(r, str) and r in _RELATION_VALUES:
                    relation_filter.append(KnowledgeRelationType(r))
                else:
                    logger.debug("AD-691: dropping unknown relation %r", r)
        return entities, relation_filter

    # ── Graph step ────────────────────────────────────────────

    async def _gather_edges(
        self,
        *,
        edge_store: Any,
        entities: list[EntityExtraction],
        relation_filter: list[KnowledgeRelationType],
        max_hops: int,
        limit: int,
    ) -> tuple[list[KnowledgeEdge], list[list[KnowledgeEdge]]]:
        scored: dict[str, tuple[float, KnowledgeEdge]] = {}
        all_paths: list[list[KnowledgeEdge]] = []
        # Coerce filter — empty list means "any"
        rel_filter_eff = relation_filter or None
        for ent in entities:
            ent_type = self._coerce_entity_type(ent.type)
            # Direct hits — both as source and as target
            direct: list[KnowledgeEdge] = []
            try:
                direct.extend(await edge_store.find_edges(
                    source_type=ent_type, source_id=ent.id, limit=limit,
                ))
                direct.extend(await edge_store.find_edges(
                    target_type=ent_type, target_id=ent.id, limit=limit,
                ))
            except Exception:
                logger.warning("AD-691: find_edges failed for %r", ent, exc_info=True)
            for e in direct:
                if rel_filter_eff is not None and e.relation not in rel_filter_eff:
                    continue
                _record_edge(scored, e, hop_proximity=1.0)
            # Multi-hop traversal — only when ent_type resolved
            if ent_type is None or max_hops < 2:
                continue
            try:
                paths = await edge_store.traverse(
                    source_type=ent_type,
                    source_id=ent.id,
                    max_hops=max_hops,
                    relation_filter=rel_filter_eff,
                )
            except Exception:
                logger.warning("AD-691: traverse failed for %r", ent, exc_info=True)
                continue
            for path in paths:
                if not path:
                    continue
                all_paths.append(list(path))
                hop = max(1, len(path))
                proximity = _GRAPH_HOP_PROXIMITY_BASE ** (hop - 1)
                for e in path:
                    if rel_filter_eff is not None and e.relation not in rel_filter_eff:
                        continue
                    _record_edge(scored, e, hop_proximity=proximity)
        # Rank, truncate
        ordered = sorted(scored.values(), key=lambda t: t[0], reverse=True)
        edges = [t[1] for t in ordered[:limit]]
        return edges, all_paths

    @staticmethod
    def _coerce_entity_type(raw: str) -> KnowledgeEntityType | None:
        if not raw:
            return None
        if raw not in _ENTITY_TYPE_VALUES:
            return None
        return KnowledgeEntityType(raw)

    # ── Phase 2 ───────────────────────────────────────────────

    async def _phase2_synthesize(
        self, llm: Any, nl_query: str, edges: list[KnowledgeEdge],
    ) -> str:
        edge_payload = [e.to_dict() for e in edges]
        prompt = (
            f"Question: {nl_query}\n\n"
            f"Graph edges (JSON):\n{json.dumps(edge_payload, indent=2)}\n\n"
            f"Compose the answer with [graph: <edge.id>] citations."
        )
        request = LLMRequest(
            prompt=prompt,
            system_prompt=_PHASE2_SYSTEM_PROMPT,
            tier=self._llm_tier,
            temperature=0.0,
            max_tokens=self._synthesis_max_tokens,
        )
        try:
            response: LLMResponse = await llm.complete(request)
        except Exception:
            logger.warning("AD-691: phase-2 LLM call failed", exc_info=True)
            return "Synthesis failed."
        return (response.content or "").strip()

    @staticmethod
    def _extract_citations(answer: str, *, allowed_ids: set[str]) -> list[str]:
        """Return deduped, in-order edge IDs cited in ``answer`` that match
        the allowed set. Hallucinated IDs are silently dropped."""
        out: list[str] = []
        seen: set[str] = set()
        for m in _CITATION_RE.finditer(answer or ""):
            eid = m.group(1)
            if eid in allowed_ids and eid not in seen:
                seen.add(eid)
                out.append(eid)
        return out


def _record_edge(
    scored: dict[str, tuple[float, KnowledgeEdge]],
    edge: KnowledgeEdge,
    *,
    hop_proximity: float,
) -> None:
    """Insert-or-replace by edge.id, keeping the highest-scoring instance."""
    score = float(edge.weight) * float(edge.confidence) * hop_proximity
    existing = scored.get(edge.id)
    if existing is None or score > existing[0]:
        scored[edge.id] = (score, edge)
