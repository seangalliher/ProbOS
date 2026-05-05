# AD-691 v1 — NL-to-Graph Query Service (Ship's Computer Structural Routing)

**Status:** Draft (Wave 41) · **Phase:** Unified Knowledge Graph — Phase B (Intelligence)
**Depends on:** AD-687 (KnowledgeEdgeStore, Wave 37), AD-688 (Oracle Tier 6 graph, Wave 38)
**Closes:** GH issue #385
**Estimated tests:** 14 (≥12 floor)

## Problem

The knowledge graph (AD-687) is now populated (AD-689) and queryable through the
Oracle's Tier 6 substring-match heuristic (AD-688). But there is **no LLM-driven
NL-to-graph entry point** — a human asking "who reports to the chief engineer?"
or "what duties depend on the medical bay?" has no path that uses the graph
relations as first-class structure. AD-688 falls back to bag-of-tokens against
`source_id`/`target_id` strings, which only fires when the query happens to
contain the literal IDs.

AD-691 closes the **read seam** by adding a 2-phase LLM-driven service that
(1) extracts entity references and a relation filter from natural language, then
(2) traverses the graph and synthesises a natural-language answer with explicit
graph-edge provenance citations.

## Note on Commercial Tag

GH issue #385 is tagged `Layer:Commercial`. The OSS extension point — the
`nl_graph_query` capability surface (LLM-driven NL→graph traversal returning
structured results with provenance) — **belongs in OSS** as the public
mechanism. Commercial overlays (RBAC-aware routing, audit pipelines, multi-tenant
scoping) layer on top of `runtime.nl_graph_query` without modifying it. This
prompt ships the OSS extension point fully and includes no pricing,
positioning, or enterprise-feature language.

## Solution

New `NLGraphQueryService` in `src/probos/cognitive/nl_graph_query.py`:

1. **Phase 1 (extraction)** — `tier="standard"` LLM call returns strict JSON
   `{"entities": [{"id": "...", "type": "agent|department|..."}],
   "relation_filter": ["reports_to", ...], "intent": "find|traverse|count"}`.
2. **Graph step** — for each extracted entity, invoke
   `runtime.knowledge_edges.find_edges(...)` (direct hits) and
   `traverse(..., max_hops=N, relation_filter=...)` (multi-hop paths), with
   `max_hops` and `limit` clamped to config defaults.
3. **Scoring** — mirror AD-688: `score = edge.weight × edge.confidence ×
   hop_proximity` where direct=1.0, hop-2=0.6, hop-3=0.36 (0.6²). Sort
   descending, truncate to `limit`.
4. **Phase 2 (synthesis)** — `tier="standard"` LLM call inlines the structured
   graph results and returns a natural-language answer that **must** cite
   edges as `[graph: edge_id]` for every fact derived from a graph hit.
5. Returns `NLGraphQueryResult` frozen dataclass:
   `query`, `extracted_entities`, `edges_traversed`, `paths`, `answer`,
   `provenance`.

Plus:
- `runtime.nl_graph_query` public attribute (Wave 5 conv #1).
- `GET /api/nl-graph-query?q=...&max_hops=N&limit=N` returning
  `NLGraphQueryResult.to_dict()`.
- `NLGraphQueryConfig` Pydantic model on `SystemConfig`.

## Architect Calls

### DLog #1 — Decomposer integration shipped via NLGraphQueryAgent (Section 5b)

The decomposer (`cognitive/decomposer.py`) discovers intents dynamically from
`IntentDescriptor` metadata declared by registered agents (intent dispatch
happens via the mesh, not via hardcoded routes in `decompose()`). The natural
fix is therefore **not** a decomposer-side edit but a small agent that wraps
`NLGraphQueryService` and self-registers an IntentDescriptor — exactly the
pattern `IntrospectionAgent` uses (`agents/introspect.py:18`, single-agent
utility pool, `_runtime`-backed delegation, no consensus).

**Decision:** v1 ships **both** the pure callable surface
(`runtime.nl_graph_query.query(...)`) **and** an `NLGraphQueryAgent`
(Section 5b) registered into a single-agent utility pool (Section 5c). The
agent declares `IntentDescriptor(name="nl_graph_query", tier="utility",
requires_consensus=False, requires_reflect=True)` so the decomposer routes
structural-query NL to it. No decomposer-side modification.

### DLog #2 — Provenance citation format

Every fact in the synthesized answer that derives from a graph hit MUST cite
the supporting edge as `[graph: <edge.id>]`. The Phase 2 system prompt
enforces this. The `provenance` field on `NLGraphQueryResult` is the
deduped list of `edge.id` values **actually cited** (extracted via regex
from `answer`) — distinct from `edges_traversed` which lists every edge the
graph step retrieved (whether or not the LLM cited it). This lets downstream
consumers distinguish "what the graph returned" from "what the answer claims".

### DLog #3 — Empty-extraction short-circuit avoids second LLM call

If Phase 1 returns `entities: []`, the service returns immediately with
`answer="No graph entities identified in query."` and `provenance=[]`. No
Phase 2 call. This bounds cost on irrelevant queries (greetings, system
chatter) and gives a deterministic test surface (Test #4).

### DLog #4 — Phase 1 parse-failure fallback

If Phase 1 LLM output cannot be `extract_json()`'d into a dict, or the dict
doesn't have `entities` as a list, the service returns
`answer="Could not parse query."`, `extracted_entities=[]`,
`edges_traversed=[]`, `paths=[]`, `provenance=[]`. Tier-2 log-and-degrade —
never raises into the caller.

### DLog #5 — Hop-proximity formula extended for hop=3

AD-688 used 1.0 / 0.6 for direct / two-hop. AD-691 traversal can go up to
`MAX_HOPS_CEILING=3` (the AD-687 limit). Formula extended: hop-N proximity =
`0.6 ** (N - 1)` → direct=1.0, hop-2=0.6, hop-3=0.36. Documented in
module docstring; computed inline (not config — escalate only on adoption
signal).

### DLog #6 — `relation_filter` whitelist enforcement

The Phase 1 LLM may return relation strings that aren't in
`KnowledgeRelationType`. Coerce by filtering against the enum's `.value` set;
unknown strings are silently dropped (logged at `debug`). If the filter
becomes empty after coercion, pass `relation_filter=None` to `traverse()` so
the call doesn't trivially return `[]`.

## Verify-First (HEAD `bea66c5`)

| Symbol | Path | Notes |
|---|---|---|
| `KnowledgeEdge` 13-field frozen dc | `src/probos/knowledge/edges.py:73` | source/target type+id, relation, id, confidence, weight, classification, source_agent, source_duty, created_at, updated_at |
| `KnowledgeEntityType` 8-value Enum | `:41` | agent/department/incident/decision/duty/finding/capability/standing_order |
| `KnowledgeRelationType` 10-value Enum | `:54` | reports_to/member_of/competent_in/resolved_by/involved_in/informed_by/depends_on/produced_by/classified_as/originated_on |
| `KnowledgeEdgeStorage.find_edges` | `:150` | kw-only `(source_type, source_id, target_type, target_id, relation, limit=100)` |
| `KnowledgeEdgeStorage.traverse` | `:159` | kw-only `(source_type, source_id, max_hops=3, relation_filter=None)` returns `list[list[KnowledgeEdge]]` |
| `MAX_HOPS_CEILING = 3` | `:31` | hard upper bound |
| `runtime.knowledge_edges` | `runtime.py:428` (slot) `:1616` (adoption) | public, may be None |
| `OracleService` Tier 6 graph (AD-688) | `cognitive/oracle_service.py:344` (`_query_semantic`), `_query_graph`/`_expand_via_graph` appended after | sibling pattern reference for graph-driven scoring |
| `_GRAPH_HOP_PROXIMITY_DIRECT/TWO_HOP` | `cognitive/oracle_service.py:42` | mirror these values; AD-691 extends to hop-3 |
| `LLMRequest` dataclass | `types.py:227` | `prompt`, `system_prompt`, `tier="standard"`, `temperature=0.0`, `max_tokens=2048`, `id` |
| `LLMResponse.content` | `types.py:241` | `content` field is the raw text |
| `BaseLLMClient.complete` | `cognitive/llm_client.py:26,420,1060` | async, `(request, *, priority=Priority.NORMAL) -> LLMResponse` |
| `extract_json` | `utils/json_extract.py:17` | `(content) -> dict[str, Any]`, raises `ValueError` on failure |
| `_StubLLM` test pattern | `tests/test_ad690_relationship_inference.py:28` | sequential `responses` list, async `complete(req)` returning `LLMResponse` |
| `DiagnosticContextConfig` Pydantic | `config.py:352` | sibling shape for `NLGraphQueryConfig` (default-True precedent + `field_validator`) |
| `SystemConfig.diagnostic_context` field site | `config.py:2145` | new `nl_graph_query` field inserted right after this |
| `_wire_diagnostic_context` sync wirer | `startup/finalize.py:370` | sibling shape for `_wire_nl_graph_query` |
| `_wire_diagnostic_context` invocation | `startup/finalize.py:703` | new wirer call inserted on the next line |
| Routers tuple in `api.py` | `:192–208` | twin-block: import + for-loop tuples both must include `nl_graph_query` |
| `routers/diagnostic_context.py` | full file (47 lines) | sibling shape for `routers/nl_graph_query.py` |
| Decomposer dynamic intent discovery | `cognitive/decomposer.py:280` (`decompose`) — no hardcoded `ask` route | confirms DLog #1 architectural call |

## Section 0 — Naming Collision Check

`grep -rn "nl_graph_query\|NLGraphQuery\|NL2Graph\|graph_nl" src/ tests/` →
**0 hits**. Fully greenfield.

`grep -rn "runtime\.nl_graph_query" src/` → 0 hits. Public attribute is
collision-free.

## Section 1 — `NLGraphQueryConfig` (NEW Pydantic model in `src/probos/config.py`)

Insert immediately AFTER `CausalReasoningConfig` (which ends at line 401):

```python
class NLGraphQueryConfig(BaseModel):
    """AD-691 v1: NL-to-Graph Query Service.

    Default-enabled (deviation from Wave-10 transitional-flag convention)
    because the service is a callable read-only aggregator with no automatic
    invocation; it is invisible at runtime until a caller invokes
    `runtime.nl_graph_query.query()`. Same precedent as
    `DiagnosticContextConfig` and `KnowledgeEdgesConfig`.
    """

    enabled: bool = True
    default_max_hops: int = 2
    default_limit: int = 10
    llm_tier: str = "standard"
    extraction_max_tokens: int = 600
    synthesis_max_tokens: int = 800

    @field_validator("default_max_hops")
    @classmethod
    def _hops_in_range(cls, v: int) -> int:
        if not 1 <= v <= 3:
            raise ValueError("default_max_hops must be in [1, 3]")
        return v

    @field_validator("default_limit")
    @classmethod
    def _limit_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("default_limit must be >= 1")
        return v
```

Then add the field to `SystemConfig` immediately after the
`diagnostic_context: DiagnosticContextConfig = Field(...)  # AD-661` block at
`config.py:2145`:

```python
    diagnostic_context: DiagnosticContextConfig = Field(
        default_factory=DiagnosticContextConfig
    )  # AD-661
    nl_graph_query: NLGraphQueryConfig = Field(
        default_factory=NLGraphQueryConfig
    )  # AD-691
    clinical_telemetry: ClinicalTelemetryConfig = Field(
        default_factory=ClinicalTelemetryConfig
    )  # AD-635
```

## Section 2 — `NLGraphQueryService` (NEW `src/probos/cognitive/nl_graph_query.py`)

Full file (greenfield). Public surface: `NLGraphQueryResult`,
`EntityExtraction`, `NLGraphQueryService`.

```python
"""NL-to-Graph Query Service — Ship's Computer structural routing (AD-691).

Phase B (Intelligence) of the Unified Knowledge Graph stack. v1 ships an
LLM-driven 2-phase service that translates natural-language queries into
typed graph traversals over the AD-687 KnowledgeEdgeStore and synthesizes
an answer with explicit graph-edge provenance citations.

Phase 1 (extraction): LLM returns strict JSON identifying entities + a
relation filter + a query intent label. Phase 2 (synthesis): LLM is given
the structured graph results inline and asked to compose an answer that
cites every graph-derived fact as ``[graph: <edge.id>]``.

NO decomposer integration v1 — pure callable surface on
``runtime.nl_graph_query``. Intent-route registration deferred to AD-691b.
NO embedding-based fuzzy entity match (deferred AD-691c). NO write/mutation
queries (graph is read-only here). NO classification-aware filtering
(AD-692 commercial owns).
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
```

## Section 3 — Wirer in `src/probos/startup/finalize.py`

Insert new wirer immediately AFTER `_wire_diagnostic_context` (which ends at
`finalize.py:393`):

```python
def _wire_nl_graph_query(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-691 v1: Wire NLGraphQueryService LLM-driven NL→graph router."""
    cfg = getattr(config, "nl_graph_query", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.nl_graph_query import NLGraphQueryService

    runtime.nl_graph_query = NLGraphQueryService(
        runtime,
        default_max_hops=cfg.default_max_hops,
        default_limit=cfg.default_limit,
        llm_tier=cfg.llm_tier,
        extraction_max_tokens=cfg.extraction_max_tokens,
        synthesis_max_tokens=cfg.synthesis_max_tokens,
    )
    logger.info(
        "AD-691: NLGraphQueryService v1 initialized "
        "(default_max_hops=%d, default_limit=%d, llm_tier=%s)",
        cfg.default_max_hops, cfg.default_limit, cfg.llm_tier,
    )
    return True
```

Then add the invocation in `finalize_startup` immediately after the
`_wire_diagnostic_context` invocation (`finalize.py:703`):

```python
    if _wire_diagnostic_context(runtime=runtime, config=config):
        logger.info("AD-661: DiagnosticContextService v1 wired during finalization")

    if _wire_nl_graph_query(runtime=runtime, config=config):
        logger.info("AD-691: NLGraphQueryService v1 wired during finalization")
```

## Section 4 — API router (NEW `src/probos/routers/nl_graph_query.py`)

```python
"""ProbOS API — NL-to-Graph Query routes (AD-691 v1)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/nl-graph-query", tags=["nl-graph-query"])


@router.get("")
async def nl_graph_query(
    q: str = "",
    max_hops: int = 2,
    limit: int = 10,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-691 v1: NL-to-graph query.

    Args:
        q: Natural-language query.
        max_hops: Traversal depth (clamped to [1, 3]).
        limit: Max edges returned (clamped to >= 1, hard cap 100).
    """
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="q must be non-empty")
    service = getattr(runtime, "nl_graph_query", None)
    if service is None:
        raise HTTPException(status_code=503, detail="nl_graph_query disabled")
    result = await service.query(
        q,
        max_hops=min(max(max_hops, 1), 3),
        limit=min(max(limit, 1), 100),
    )
    return result.to_dict()
```

## Section 5 — Register router in `src/probos/api.py`

Twin-block SEARCH/REPLACE — insert `nl_graph_query` alphabetically into BOTH
the import tuple AND the for-loop tuple. Combine into a single multi-replace
call (Wave 31/33 pattern).

Block A (line 192–200, imports):

```python
    from probos.routers import (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic, diagnostic_context, nl_graph_query,
    )
```

Block B (line 202–208, for-loop):

```python
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic, diagnostic_context, nl_graph_query,
    ):
        app.include_router(r.router)
```

(The two tuples differ in their leading line — `from probos.routers import (`
vs `for r in (` — which provides unique anchoring per block.)

## Section 5b — `NLGraphQueryAgent` (NEW `src/probos/agents/utility/nl_graph_query_agent.py`)

Single-agent utility pool that wraps `NLGraphQueryService` and self-registers
an IntentDescriptor so the decomposer routes structural-query NL to it.
Pattern mirror: `src/probos/agents/introspect.py:18` (`IntrospectionAgent` —
`tier = "utility"`, `_runtime`-backed delegation, `requires_reflect=True`,
no consensus, full `perceive→decide→act→report` lifecycle).

Full file (greenfield):

```python
"""NL-to-Graph Query agent (AD-691) — wraps NLGraphQueryService.

Declares an ``nl_graph_query`` IntentDescriptor so the decomposer
(`cognitive/decomposer.py`) — which discovers intents dynamically from
registered agents — routes structural-query natural language
("who reports to chief_engineer?", "what depends on the dream pipeline?",
"how is medbay connected to security?") to this agent.

The agent is purely a thin dispatcher onto ``runtime.nl_graph_query`` and
holds no state of its own. NEVER raises into the caller — every failure
path returns a well-formed degraded ``IntentResult``.
"""

from __future__ import annotations

import logging
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

logger = logging.getLogger(__name__)


class NLGraphQueryAgent(BaseAgent):
    """Decomposer-routable surface for ``runtime.nl_graph_query``.

    Examples of routed natural-language queries:
      - "who reports to chief_engineer?"
      - "what depends on the dream pipeline?"
      - "how is medbay connected to security?"
    """

    agent_type: str = "nl_graph_query"
    tier = "utility"
    default_capabilities = [
        CapabilityDescriptor(
            can="nl_graph_query",
            detail="Translate natural-language structural questions into typed graph traversals over the knowledge edge store and return a synthesized answer with explicit graph-edge provenance.",
        ),
    ]
    initial_confidence: float = 0.85
    intent_descriptors = [
        IntentDescriptor(
            name="nl_graph_query",
            params={
                "query": "natural-language question about relationships between entities (agents, departments, duties, incidents, decisions, findings, capabilities, standing_orders)",
                "max_hops": "optional traversal depth (1-3, default 2)",
                "limit": "optional max edges returned (default 10)",
            },
            description=(
                "Answer structural / relationship questions over the knowledge graph. "
                "Use for queries about who reports to whom, what depends on what, how "
                "two entities are connected, or which entities share a relation. "
                "Returns a natural-language answer with [graph: <edge.id>] provenance."
            ),
            requires_consensus=False,
            requires_reflect=True,
            tier="utility",
        ),
    ]

    _handled_intents = {"nl_graph_query"}

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive → decide → act → report."""
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None

        plan = await self.decide(observation)
        if plan is None:
            return None

        result = await self.act(plan)
        report = await self.report(result)

        success = bool(report.get("success", False))
        self.update_confidence(success)

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("data"),
            error=report.get("error"),
            confidence=self.confidence,
        )

    async def perceive(self, intent: dict[str, Any]) -> Any:
        if intent.get("intent") not in self._handled_intents:
            return None
        return {"params": intent.get("params", {}) or {}}

    async def decide(self, observation: Any) -> Any:
        params = observation["params"]
        nl = params.get("query") or params.get("q") or params.get("text") or ""
        if not isinstance(nl, str) or not nl.strip():
            return None
        return {
            "query": nl.strip(),
            "max_hops": params.get("max_hops"),
            "limit": params.get("limit"),
        }

    async def act(self, plan: Any) -> Any:
        rt = self._runtime
        if rt is None:
            return {"success": False, "error": "No runtime reference available"}
        service = getattr(rt, "nl_graph_query", None)
        if service is None:
            return {"success": False, "error": "nl_graph_query service unavailable"}
        try:
            result = await service.query(
                plan["query"],
                max_hops=plan.get("max_hops"),
                limit=plan.get("limit"),
            )
        except Exception as e:  # Tier-2: log-and-degrade
            logger.warning("AD-691: NLGraphQueryAgent.act delegation failed", exc_info=True)
            return {"success": False, "error": f"nl_graph_query failed: {e}"}
        return {
            "success": True,
            "data": {
                "query": result.query,
                "answer": result.answer,
                "provenance": list(result.provenance),
                "extracted_entities": [e.to_dict() for e in result.extracted_entities],
                "edge_count": len(result.edges_traversed),
                "path_count": len(result.paths),
            },
        }
```

Also export from `src/probos/agents/utility/__init__.py` (append to whatever
existing `__all__` / re-export list is there; if the file is empty, add
`from probos.agents.utility.nl_graph_query_agent import NLGraphQueryAgent`).
Verify the file's existing shape before SEARCH/REPLACE — if it already
imports siblings (`language_agents`, `organizer_agents`, etc.), follow that
convention; otherwise add a single-line import.

## Section 5c — Pool registration in `src/probos/runtime.py` and `src/probos/startup/agent_fleet.py`

Two edits, both grep-anchored.

**5c.1 — Template registration (`runtime.py:598`)**

SEARCH/REPLACE: insert the new template registration immediately after the
introspect template registration (`runtime.py:598`). Also add the import at
the top alongside `IntrospectionAgent` (`runtime.py:25`).

Import block addition (anchor: `from probos.agents.introspect import IntrospectionAgent`):

```python
from probos.agents.introspect import IntrospectionAgent
from probos.agents.utility.nl_graph_query_agent import NLGraphQueryAgent  # AD-691
```

Template registration (anchor: `self.spawner.register_template("introspect", IntrospectionAgent)`):

```python
        self.spawner.register_template("introspect", IntrospectionAgent)
        self.spawner.register_template("nl_graph_query", NLGraphQueryAgent)  # AD-691
        self.spawner.register_template("skill_agent", SkillBasedAgent)
```

**5c.2 — Pool creation (`startup/agent_fleet.py:60`)**

Gate on `config.nl_graph_query.enabled` (the field added in Section 1) AND
on runtime having the service wired (`getattr(runtime, "nl_graph_query", None)
is not None`). Single-agent pool (`target_size=1`) — this is a thin
dispatcher; no parallelism benefit.

SEARCH/REPLACE anchor — the introspect pool block (`agent_fleet.py:58-60`):

```python
    # Introspect pool (needs runtime kwarg)
    ids = generate_pool_ids("introspect", "introspect", 2)
    await create_pool_fn("introspect", "introspect", target_size=2, agent_ids=ids, runtime=runtime)

    # NL-to-Graph Query pool (AD-691) — single-agent dispatcher onto runtime.nl_graph_query
    if (
        getattr(config, "nl_graph_query", None)
        and config.nl_graph_query.enabled
        and getattr(runtime, "nl_graph_query", None) is not None
    ):
        ids = generate_pool_ids("nl_graph_query", "nl_graph_query", 1)
        await create_pool_fn(
            "nl_graph_query", "nl_graph_query",
            target_size=1, agent_ids=ids, runtime=runtime,
        )
```

Note: this phase runs AFTER `finalize_startup` wires `runtime.nl_graph_query`
(verify the ordering at HEAD — `start()` invokes `_wire_*` finalizers before
`create_agent_fleet`). If the ordering is reversed, the gate's third clause
(`runtime.nl_graph_query is not None`) will skip pool creation cleanly
rather than crashing — explicit log emit for that case is in Section 7's
"What this does NOT change" boundary (no startup-ordering refactor).

## Section 6 — Tests (NEW `tests/test_ad691_nl_graph_query.py`)

14 focused tests (≥12 floor — bumped from 10 to accommodate agent +
pool tests). Pattern modelled on
`tests/test_ad690_relationship_inference.py`.

### Stubs (top of file)

```python
class _StubLLM:
    """Sequential responses; tracks calls + last requests."""
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0
        self.requests: list[Any] = []

    async def complete(self, req):
        self.calls += 1
        self.requests.append(req)
        content = self._responses.pop(0) if self._responses else ""
        return LLMResponse(content=content)


class _StubEdgeStore:
    def __init__(self, edges: list[KnowledgeEdge] | None = None):
        self.edges = list(edges or [])
        self.find_calls: list[dict] = []
        self.traverse_calls: list[dict] = []

    async def find_edges(self, **kw):
        self.find_calls.append(kw)
        out = []
        for e in self.edges:
            if "source_id" in kw and kw["source_id"] is not None:
                if e.source_id == kw["source_id"] and (
                    "source_type" not in kw or kw["source_type"] is None
                    or e.source_type == kw["source_type"]
                ):
                    out.append(e)
            if "target_id" in kw and kw["target_id"] is not None:
                if e.target_id == kw["target_id"] and (
                    "target_type" not in kw or kw["target_type"] is None
                    or e.target_type == kw["target_type"]
                ):
                    out.append(e)
        return out

    async def traverse(self, **kw):
        self.traverse_calls.append(kw)
        out: list[list[KnowledgeEdge]] = []
        for e in self.edges:
            if e.source_id == kw["source_id"] and e.source_type == kw["source_type"]:
                rf = kw.get("relation_filter")
                if rf is None or e.relation in rf:
                    out.append([e])
        return out
```

### Test list

1. `test_result_dataclass_frozen_and_to_dict` — `NLGraphQueryResult` is
   frozen (mutating raises) + `to_dict()` round-trip preserves all fields.
2. `test_service_shape_default_kwargs` — ctor accepts the 6 kw-only params,
   defaults match the config defaults (max_hops=2, limit=10, etc.).
3. `test_query_happy_path_with_stub_llm` — Phase-1 returns 1 entity, edge
   store returns 1 direct edge, Phase-2 returns answer with `[graph: <id>]`
   citation. Assert `edges_traversed` len 1, `provenance == [edge.id]`,
   answer non-empty.
4. `test_phase1_parse_failure_returns_degraded_result` — LLM Phase-1 returns
   `"not json at all"`; result has `answer="Could not parse query."`,
   `provenance=[]`, no Phase-2 call (assert `llm.calls == 1`).
5. `test_empty_extraction_short_circuits_phase2` — Phase-1 returns
   `'{"entities": [], "relation_filter": [], "intent": "find"}'`; result
   has `answer="No graph entities identified in query."`, `llm.calls == 1`,
   `edge_store.find_calls == []`.
6. `test_relation_filter_passes_through_to_traverse` — Phase-1 returns
   `relation_filter=["reports_to"]`; assert
   `edge_store.traverse_calls[0]["relation_filter"] ==
   [KnowledgeRelationType.REPORTS_TO]`.
7. `test_unknown_relation_in_filter_dropped_silently` — Phase-1 returns
   `relation_filter=["reports_to", "fictional_relation"]`; only
   `REPORTS_TO` reaches `traverse()`.
8. `test_max_hops_clamped_to_ceiling` — call with `max_hops=99`; assert
   `edge_store.traverse_calls[0]["max_hops"] == 3`.
9. `test_limit_truncates_results` — Phase-1 returns 1 entity; edge store
   has 25 edges all matching; assert `len(result.edges_traversed) == 5`
   when called with `limit=5`.
10. `test_scoring_orders_by_weight_confidence_and_proximity` — 3 edges
    with different weight/confidence; assert returned order matches
    `weight × confidence × 1.0` descending.
11. `test_provenance_drops_hallucinated_citations` — Phase-2 answer cites
    a `[graph: deadbeefdeadbeef0000000000000000]` (not in `edges`); assert
    that ID is NOT in `provenance` (hallucinated cite filter).
12. `test_no_edges_returns_no_evidence_without_phase2_call` — Phase-1
    returns 1 entity; edge store returns 0 edges; assert
    `answer == "No relevant graph evidence."`, `provenance == []`,
    `llm.calls == 1` (no synthesis).

Plus the 2 API tests below — testing API hits floor of 12 even if list
above is reduced.

13. `test_api_endpoint_400_on_empty_query` — TestClient + dependency
    override; `GET /api/nl-graph-query?q=` → 400.
14. `test_api_endpoint_happy_path` — TestClient + dependency override with
    a runtime stub holding a service that returns a fixed
    `NLGraphQueryResult`; assert 200 + body matches `to_dict()`.

### Agent tests (Section 5b/5c coverage)

15. `test_agent_act_happy_path_delegates_to_runtime_service` — Construct
    `NLGraphQueryAgent` with a runtime stub whose `nl_graph_query` is a
    `_FakeService` returning a fixed `NLGraphQueryResult` (1 entity,
    1 edge, answer + provenance). Call `await agent.handle_intent(...)`
    with `IntentMessage(intent="nl_graph_query", params={"query":
    "who reports to chief_engineer?"})`. Assert `result.success is True`,
    `result.result["answer"]` matches the stub answer,
    `result.result["provenance"]` matches the stub provenance, and that
    `_FakeService.calls == 1` with the natural-language query passed
    through verbatim.
16. `test_agent_pool_registered_when_feature_enabled` — Smoke test using
    the standard runtime-bootstrap fixture (mirror the fixture pattern
    used by `test_ad690_*` or any prior `test_ad6xx_*` runtime smoke
    test). Boot a runtime with `nl_graph_query.enabled=True`; assert
    `"nl_graph_query" in runtime.spawner._templates`,
    `"nl_graph_query" in runtime.pools`, and the pool's agent declares
    an `IntentDescriptor(name="nl_graph_query", tier="utility")`. If
    a full runtime boot is too heavy for unit-tier (Wave 8/10 cost
    lesson), substitute with a focused test: directly invoke
    `create_agent_fleet` against a minimal runtime stub with
    `_templates`/`pools` dicts pre-populated and assert the gate
    triggers pool creation.

(Architect call: ship 14. If test count must drop by 2, drop tests 7 and
11 — both are convergent with tests 6 and 10 respectively. NEVER drop
13/14 (API surface) or 15/16 (agent + pool surface — the new core scope).)

## Section 7 — What This Does NOT Change

- **No decomposer-side modification.** v1 ships an `NLGraphQueryAgent`
  (Section 5b) + single-agent pool (Section 5c) so the decomposer's
  existing dynamic IntentDescriptor discovery picks up the route
  automatically. The decomposer source is not touched.
- **No embedding-based fuzzy entity match** (deferred AD-691c if surfaced).
  v1 uses verbatim entity IDs as extracted by the LLM.
- **No write/mutation queries.** Graph is read-only here. Mutation
  (`add_edge`/`update_edge`/`delete_edge`) belongs to the storage owner.
- **No classification-aware filtering** (AD-692 commercial owns).
- **No Fabric IQ NL2GQL parity claims.** v1 is simple typed-triple
  traversal, not full graph-query-language coverage.
- **No HXI surface** (deferred until consumer signal).
- **No new EventType** (keep telemetry to logger.info / logger.debug v1).
- **No Pydantic config for hop-proximity formula** (inline; escalate only
  on adoption signal).
- **No persistence of query history** (each call is stateless).
- **No streaming response** (v1 returns the full result; WS streaming
  deferred).

## Section 8 — Tracker Updates

- `PROGRESS.md` — prepend AD-691 v1 CLOSED entry at top of file (Wave 41).
  Note: ships both callable surface AND decomposer-routable
  `NLGraphQueryAgent`.
- `docs/development/roadmap.md` — flip AD-691 status from **Scoped** to
  **Complete**. Description should mention OSS extension point shipped
  (callable + agent + pool); do NOT mention commercial pricing/positioning.
- `DECISIONS.md` — prepend AD-691 entry at top of Era V section (date
  2026-05-04). Reference: GH issue #385, Wave 41. Note that decomposer
  integration ships in v1 via `NLGraphQueryAgent` (no decomposer-side
  modification — leverages existing dynamic `IntentDescriptor`
  discovery).

## Section 9 — Cloud-Ready Storage

NOT applicable — this AD adds NO new storage. It consumes existing
`runtime.knowledge_edges` (AD-687 SQLiteKnowledgeEdgeStore behind the
`KnowledgeEdgeStorage` Protocol — already Cloud-Ready via `ConnectionFactory`).

## Section 10 — Phantom-API Pre-check Result

Run at draft time:

```
pwsh ./scripts/phantom-api-precheck.ps1 prompts/ad-691-nl-to-graph-query-v1.md
```

Expected candidates (all FPs):
- `class:HTTPException` / `class:APIRouter` — FastAPI stdlib aliases used in
  the API router. Same FP class as Waves 28/31/33.
- `runtime.nl_graph_query` — introduced by Section 3 wirer; not yet in class
  index. Same intro-not-in-index FP class as prior waves.
- `service.query(...)` kwarg shapes — service introduced by Section 2; not
  in index yet.
- `NLGraphQueryAgent` / `agent.handle_intent` / `agent.perceive` /
  `agent.decide` / `agent.act` — agent introduced by Section 5b; methods
  override `BaseAgent` lifecycle hooks (verified shape against
  `agents/introspect.py:54-86`). Same intro-not-in-index FP class.
- `runtime.spawner._templates` / `runtime.pools` (test 16) — internal
  attributes used in pool-registration smoke test; same private-attr
  test-fixture FP class as prior waves' template-registration tests.
- `_StubLLM.__new__` / `_StubEdgeStore.__new__` — stdlib object protocol
  used in test fixtures.
- `_GRAPH_HOP_PROXIMITY_BASE` / `_CITATION_RE` / `_RELATION_VALUES` /
  `_ENTITY_TYPE_VALUES` — module-level constants introduced by Section 2.
- `runtime.knowledge_edges.find_edges(target_id=..., target_type=...)` —
  `find_edges` accepts these kwargs (verified `edges.py:150–158`); should
  resolve cleanly. If pre-check flags as kwarg_mismatch it's a script
  limitation (pre-check does NOT validate kwargs against live signatures —
  Wave 10 lesson, still open as tooling-hygiene-AD candidate).

Architect target: 0 NEW phantoms.

## Section 11 — Standing Conventions

- Wave 5 conv #1 — public `runtime.nl_graph_query` attribute (no underscore).
- Wave 5 conv #3 — every claim in this prompt grep-verified at HEAD `bea66c5`.
- Wave 10 transitional-flag default-False convention — DEVIATED here
  (`enabled=True`); rationale documented in `NLGraphQueryConfig` docstring
  (callable read-only aggregator with no automatic invocation; same precedent
  as `DiagnosticContextConfig`/`KnowledgeEdgesConfig`).
- AD-660 retrospective: `_cognitive_journal` collision trap N/A — this
  service does NOT subclass `CognitiveAgent`.
- Cloud-Ready: N/A (no new storage).
- Property-collision warning: `runtime.nl_graph_query` 0 hits at HEAD.

## Section 12 — Acceptance Criteria

- 14 new tests pass at `tests/test_ad691_nl_graph_query.py` (12 service +
  API tests + 2 agent / pool tests).
- Full gate (`pytest tests/ -q -n 8 --dist=loadfile`) passes; test count
  delta = +14 vs Wave 40 baseline 11028 → expected 11042 (±1 for known
  xdist flakes — see Wave 23/27/30/31/32/33 baselines).
- No new phantoms beyond the FP classes documented in Section 10.
- `NLGraphQueryAgent` registered as a spawner template AND created into
  the `nl_graph_query` pool when `config.nl_graph_query.enabled=True`.
- Decomposer's dynamic intent registry exposes `nl_graph_query` after
  startup (verify via `runtime._collect_intent_descriptors()` — the
  live entry point at `runtime.py:3048`; called by
  `decomposer.refresh_descriptors(...)` at `runtime.py:671`).
- Pre-commit deletion sanity: max single-file deletion < 200 lines.
- Trackers updated per Section 8.
- **Verify all changes comply with the Engineering Principles in
  `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-04, HEAD `bea66c5`)

```
src/probos/knowledge/edges.py:31    MAX_HOPS_CEILING = 3
src/probos/knowledge/edges.py:41    KnowledgeEntityType (8 values)
src/probos/knowledge/edges.py:54    KnowledgeRelationType (10 values)
src/probos/knowledge/edges.py:73    @dataclass(frozen=True) class KnowledgeEdge (13 fields)
src/probos/knowledge/edges.py:139   class KnowledgeEdgeStorage(Protocol)
src/probos/knowledge/edges.py:150       async def find_edges(*, source_type=None, source_id=None,
                                          target_type=None, target_id=None, relation=None, limit=100)
src/probos/knowledge/edges.py:159       async def traverse(*, source_type, source_id,
                                          max_hops=MAX_HOPS_CEILING, relation_filter=None)
                                          -> list[list[KnowledgeEdge]]
src/probos/cognitive/oracle_service.py:30   _GRAPH_DIRECT_LIMIT = 10
src/probos/cognitive/oracle_service.py:42   _GRAPH_HOP_PROXIMITY_DIRECT = 1.0
src/probos/cognitive/oracle_service.py:43   _GRAPH_HOP_PROXIMITY_TWO_HOP = 0.6
src/probos/types.py:227            @dataclass class LLMRequest (prompt, system_prompt,
                                     tier="standard", temperature=0.0, max_tokens=2048, id)
src/probos/types.py:241            @dataclass class LLMResponse (content, model, tier, ...)
src/probos/cognitive/llm_client.py:26   abstractmethod async def complete(self, request, *,
                                          priority=Priority.NORMAL) -> LLMResponse
src/probos/utils/json_extract.py:17   def extract_json(content: str) -> dict[str, Any]
src/probos/runtime.py:428          self.knowledge_edges: Any = None  # AD-687
src/probos/runtime.py:1616         self.knowledge_edges = comm.knowledge_edges  # AD-687
src/probos/config.py:352           class DiagnosticContextConfig(BaseModel)  # sibling shape
src/probos/config.py:385           class CausalReasoningConfig(BaseModel)  # insertion anchor
src/probos/config.py:2145          diagnostic_context: DiagnosticContextConfig = Field(
                                     default_factory=DiagnosticContextConfig
                                   )  # AD-661 — new nl_graph_query field inserted right after
src/probos/startup/finalize.py:370 def _wire_diagnostic_context(...)  # sibling shape
src/probos/startup/finalize.py:703 if _wire_diagnostic_context(...): logger.info("AD-661: ...
src/probos/routers/diagnostic_context.py:1-47   sibling shape for routers/nl_graph_query.py
src/probos/api.py:192-208          twin-block routers tuple (import + for-loop)
tests/test_ad690_relationship_inference.py:28   class _StubLLM (sequential-response pattern)
src/probos/cognitive/decomposer.py:280   async def decompose(...)  # confirms NO hardcoded
                                          "ask" intent; routing is dynamic — supports DLog #1
src/probos/agents/introspect.py:18       class IntrospectionAgent(BaseAgent)
                                           tier="utility", _runtime-backed delegation,
                                           full perceive→decide→act→report lifecycle —
                                           pattern reference for NLGraphQueryAgent (Section 5b)
src/probos/runtime.py:25                from probos.agents.introspect import IntrospectionAgent
                                           — anchor for the new NLGraphQueryAgent import
src/probos/runtime.py:598               self.spawner.register_template("introspect", IntrospectionAgent)
                                           — anchor for new template registration
src/probos/startup/agent_fleet.py:58-60 # Introspect pool block (single-agent utility,
                                           runtime kwarg) — anchor for new
                                           nl_graph_query pool block (Section 5c.2)
src/probos/types.py:64                  @dataclass class IntentResult (intent_id, agent_id,
                                           success, result, error, confidence, timestamp)
src/probos/types.py:581                 @dataclass class IntentDescriptor (name, params,
                                           description, requires_consensus=False,
                                           requires_reflect=False, tier="domain")
```
