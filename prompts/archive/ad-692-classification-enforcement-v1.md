# AD-692 v1: Classification Enforcement on Knowledge Graph Edges

**Status:** Ready for build
**Phase:** Unified Knowledge Graph + Oracle Unification — Phase B (Intelligence)
**Layer:** OSS extension point (commercial overlay can layer enterprise audit/RBAC on top)
**GH Issue:** #386
**Depends on:** AD-687 (Knowledge Edge Store, shipped Wave 37). AD-679 (Selective Disclosure Routing, shipped #367) referenced as **orthogonal**.
**Estimated tests:** ≥12

---

## Problem

`KnowledgeEdge.classification` field exists (Wave 37, AD-687) but is **not enforced** on read or write. Any caller can:

- Read every edge regardless of classification.
- Write edges at any classification level without authority check.
- Future federation export (planned, not yet implemented) would forward all edges including `fleet`-classified.

OSS extension point: classification labels enforced at the storage boundary so future commercial overlays (audit, RBAC, multi-tenant) can layer on top of a stable seam.

---

## Solution

Add a **decorator-pattern wrapper** (`ClassificationGatedKnowledgeEdgeStore`) around the existing `SQLiteKnowledgeEdgeStore`. Wrapper implements `KnowledgeEdgeStorage` Protocol and delegates all calls; reads accept an optional `requester_agent_id` kwarg and filter edges by clearance when present. Writes route through `KnowledgeEdgeClassificationGate.authorize_write()` which checks the writer's clearance against the edge's classification. A pure `filter_for_export(edges, *, target_classification)` helper provides the federation extension seam.

Backward compatible: when `requester_agent_id=None` (system/internal callers, all Wave 37/38/39/40 tests), no filtering is applied — the wrapper is a no-op pass-through. Oracle Tier 6 plumbs `requester_agent_id` from `OracleService.query()`'s existing `agent_id` parameter.

Late-bind clearance resolver (callable injected via setter) so the wrapper does NOT import substrate (`earned_agency`, `ontology`) directly — preserves layer discipline.

---

## Section 0: ClassificationLevel Taxonomy

Reuse `_CLASSIFICATION_LEVELS = {"private":0, "department":1, "ship":2, "fleet":3}` from `records_store.py:27`. Promote to a typed `IntEnum` whose **integer value matches the existing dict** (so the records_store ordering and the new enum agree byte-for-byte).

| Label | IntEnum value | Audience | Required clearance |
|---|---|---|---|
| `PRIVATE` | 0 | Owner only (`edge.source_agent == requester_agent_id`) | any tier (gated on ownership, not tier) |
| `DEPARTMENT` | 1 | Department members | `ENHANCED`+ |
| `SHIP` | 2 | All crew | `FULL`+ |
| `FLEET` | 3 | Federation peers | `ORACLE` |

**Per-department matching is OUT OF SCOPE for v1.** `KnowledgeEdge` does not carry a department field today; adding one is out of scope. v1's `DEPARTMENT` gate is tier-based (any ENHANCED+ requester sees all department-classified edges). Per-dept refinement deferred to AD-692b if adoption signals justify.

**Default-when-None:** edges with `classification is None` are read as `PRIVATE` (most restrictive) on the gate side. Pre-existing edges from Wave 37/38/39/40 that omitted classification stay restricted unless an explicit owner-equality match passes.

---

## Section 1: Verified Against Codebase (2026-05-04, HEAD `fdb71b5`)

```
grep -n "_CLASSIFICATION_LEVELS = {" src/probos/knowledge/records_store.py
  27: _CLASSIFICATION_LEVELS = {

grep -n "_CLASSIFICATION_LABELS = " src/probos/knowledge/edges.py
  34: _CLASSIFICATION_LABELS = {"private", "department", "ship", "fleet"}

grep -n "classification: str | None = None" src/probos/knowledge/edges.py
  91:    classification: str | None = None      # KnowledgeEdge field (frozen dc)

grep -n "class KnowledgeEdgeStorage" src/probos/knowledge/edges.py
  133: class KnowledgeEdgeStorage(Protocol):

grep -n "async def find_edges\|async def traverse\|async def add_edge" src/probos/knowledge/edges.py
  138:    async def add_edge(self, edge: KnowledgeEdge) -> str: ...
  149:    async def find_edges(...
  159:    async def traverse(...

grep -n "class RecallTier\|def effective_recall_tier\|def resolve_billet_clearance\|def resolve_active_grants" src/probos/earned_agency.py
  53:  class RecallTier(str, Enum):
  100: def effective_recall_tier(rank, billet_clearance="", grants=()) -> RecallTier:
  131: def resolve_billet_clearance(agent_type, ontology) -> str:
  149: def resolve_active_grants(agent_id, grant_store) -> list[ClearanceGrant]:

grep -n "self.knowledge_edges\|attach_knowledge_graph" src/probos/runtime.py
  429:  self.knowledge_edges: Any = None
  1618: self.knowledge_edges = comm.knowledge_edges  # AD-687
  1620: if self._oracle_service is not None and self.knowledge_edges is not None:
  1622:     self._oracle_service.attach_knowledge_graph(self.knowledge_edges)

grep -n "self.ontology = comm\|self.clearance_grant_store = comm" src/probos/runtime.py
  1614: self.clearance_grant_store = comm.clearance_grant_store
  1651: self.ontology = comm.ontology

grep -n "async def _query_graph\|agent_id: str = " src/probos/cognitive/oracle_service.py
  167: agent_id: str = "",       # OracleService.query()
  279: agent_id: str = "",       # OracleService.query_formatted()
  480: async def _query_graph(self, query_text: str, *, k: int) -> list[OracleResult]:

grep -n "_wire_diagnostic_context\|_wire_nl_graph_query" src/probos/startup/finalize.py
  370: def _wire_diagnostic_context(*, runtime, config) -> bool:
  394: def _wire_nl_graph_query(*, runtime, config) -> bool:
  727: if _wire_diagnostic_context(runtime=runtime, config=config):
  730: if _wire_nl_graph_query(runtime=runtime, config=config):

grep -rn "knowledge_edge\|KnowledgeEdge\|edge_export" src/probos/federation/
  (no matches — federation does not export edges in HEAD)

grep -n "class DisclosureLevel\|class DisclosureRouter" src/probos/mesh/disclosure.py
  15:  class DisclosureLevel(IntEnum):       # PUBLIC=0..CLASSIFIED=4 (5-tier)
  48:  class DisclosureRouter:
```

**Phase ordering CRITICAL** — `runtime.ontology` is adopted at `runtime.py:1651`, AFTER `runtime.knowledge_edges` at `:1618`. Wirer MUST run in finalize phase (which is after both are adopted) and MUST re-call `attach_knowledge_graph` after wrapping so Oracle Tier 6 holds a reference to the wrapper, not the bare store.

---

## Section 2: New file `src/probos/knowledge/edge_classification.py`

Create with the following content (full):

```python
"""Classification Enforcement on Knowledge Graph Edges (AD-692).

OSS extension point. Captures classification gating at the storage boundary
so future commercial overlays (audit, RBAC, multi-tenant) layer on top of a
stable seam without modifying the underlying SQLiteKnowledgeEdgeStore.

Design:
- ``ClassificationLevel`` — typed 4-tier IntEnum mirroring records_store
  ``_CLASSIFICATION_LEVELS`` ordering (private=0..fleet=3).
- ``KnowledgeEdgeClassificationGate`` — pure decision service. Resolves
  requester clearance via an injected callable (kept abstract so this
  module does NOT import ``earned_agency`` / ``ontology`` directly).
- ``ClassificationGatedKnowledgeEdgeStore`` — decorator wrapper around any
  ``KnowledgeEdgeStorage`` implementation. Adds ``requester_agent_id``
  kwarg to read methods; ``None`` preserves backward-compatible
  pass-through (Wave 37/38/39/40 tests unaffected).
- ``filter_for_export(edges, *, target_classification)`` — pure helper for
  future federation export filtering. NOT consumed in v1; no federation
  edge-export pathway exists at HEAD.

Orthogonal to AD-679 ``DisclosureRouter`` (mesh/disclosure.py). AD-679
narrows IntentMessage recipients via a 5-tier IntEnum
(PUBLIC..CLASSIFIED). AD-692 gates KnowledgeEdge reads/writes via a 4-tier
IntEnum (PRIVATE..FLEET). Bridging between the two is intentionally NOT
provided in v1 — the taxonomies are different by design (recipient
clearance vs. data scope of audience).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import IntEnum
from typing import Any

from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEdgeStorage,
    KnowledgeEntityType,
    KnowledgeRelationType,
)

logger = logging.getLogger(__name__)


class ClassificationLevel(IntEnum):
    """AD-692: 4-tier audience-scope classification.

    Integer values intentionally match ``records_store._CLASSIFICATION_LEVELS``
    so the two ordering schemes agree byte-for-byte. ``PRIVATE`` is the
    most restrictive (owner-only); ``FLEET`` is federation-shareable
    (requires highest clearance to read).
    """

    PRIVATE = 0
    DEPARTMENT = 1
    SHIP = 2
    FLEET = 3

    @classmethod
    def from_label(cls, label: str | None) -> "ClassificationLevel":
        """Coerce a records_store-style string label (or ``None``) to the
        enum. Unknown / ``None`` defaults to ``PRIVATE`` (most restrictive).
        """
        if not label:
            return cls.PRIVATE
        try:
            return cls[label.upper()]
        except KeyError:
            logger.debug(
                "AD-692: unknown classification label %r; defaulting to PRIVATE",
                label,
            )
            return cls.PRIVATE


# Tier names mirror earned_agency.RecallTier values without importing it
# (layer discipline — knowledge/ must not import substrate). Resolver
# callable returns the string form; we map locally.
_TIER_MAX_VISIBLE: dict[str, ClassificationLevel] = {
    "basic": ClassificationLevel.PRIVATE,
    "enhanced": ClassificationLevel.DEPARTMENT,
    "full": ClassificationLevel.SHIP,
    "oracle": ClassificationLevel.FLEET,
}

# Default tier when resolver yields nothing (defensive — most restrictive).
_DEFAULT_TIER: str = "basic"


def edge_visible_to(
    edge: KnowledgeEdge,
    *,
    requester_tier: str,
    requester_agent_id: str | None,
) -> bool:
    """AD-692: Pure visibility check.

    - PRIVATE edges: visible only when ``edge.source_agent`` equals
      ``requester_agent_id``. Tier irrelevant (ownership gate).
    - DEPARTMENT/SHIP/FLEET edges: visible when the requester's tier
      grants visibility for the edge's classification per ``_TIER_MAX_VISIBLE``.

    None / unknown classifications coerce to PRIVATE (most restrictive).
    """
    edge_level = ClassificationLevel.from_label(edge.classification)
    if edge_level == ClassificationLevel.PRIVATE:
        return bool(requester_agent_id) and edge.source_agent == requester_agent_id
    max_visible = _TIER_MAX_VISIBLE.get(requester_tier.lower(), ClassificationLevel.PRIVATE)
    return edge_level <= max_visible


# Resolver callable signature: (requester_agent_id) -> tier_name (str).
# Returning unknown/None coerces to _DEFAULT_TIER.
ClearanceResolver = Callable[[str], str]


class KnowledgeEdgeClassificationGate:
    """AD-692: Decision service for edge read/write authorization.

    Stateless except for the late-bound clearance resolver. Never raises
    into callers — denied operations log at debug and return ``False`` /
    filtered list. Audit persistence is OUT OF SCOPE for v1 (deferred to
    AD-692b if adoption signals justify).
    """

    def __init__(self, *, default_classification: str = "private") -> None:
        self._default_classification = default_classification
        self._resolver: ClearanceResolver | None = None

    # ── Late-bind setter (avoids substrate import) ────────────────

    def set_clearance_resolver(self, resolver: ClearanceResolver) -> None:
        """Inject the (agent_id) -> tier_name callable. Called by the
        finalize-time wirer after ``runtime.ontology`` and
        ``runtime.clearance_grant_store`` are adopted.
        """
        self._resolver = resolver

    # ── Read filter ───────────────────────────────────────────────

    async def filter_edges(
        self,
        edges: list[KnowledgeEdge],
        *,
        requester_agent_id: str,
    ) -> list[KnowledgeEdge]:
        """Return only the edges the requester is cleared to see."""
        tier = self._resolve_tier(requester_agent_id)
        return [
            e for e in edges
            if edge_visible_to(
                e, requester_tier=tier, requester_agent_id=requester_agent_id,
            )
        ]

    # ── Write authorization ───────────────────────────────────────

    async def authorize_write(
        self,
        edge: KnowledgeEdge,
        *,
        writer_agent_id: str,
    ) -> bool:
        """Return True iff the writer is cleared to add an edge at this
        classification. Writers may always create PRIVATE edges they own.
        DEPARTMENT/SHIP/FLEET writes require the writer to have read access
        at that tier (a writer cannot label content above their clearance).
        """
        edge_level = ClassificationLevel.from_label(edge.classification)
        if edge_level == ClassificationLevel.PRIVATE:
            return edge.source_agent == writer_agent_id or not edge.source_agent
        tier = self._resolve_tier(writer_agent_id)
        max_visible = _TIER_MAX_VISIBLE.get(tier.lower(), ClassificationLevel.PRIVATE)
        permitted = edge_level <= max_visible
        if not permitted:
            logger.debug(
                "AD-692: write blocked — agent=%s tier=%s edge_level=%s",
                writer_agent_id, tier, edge_level.name,
            )
        return permitted

    # ── Federation export filter (extension hook) ─────────────────

    def filter_for_export(
        self,
        edges: list[KnowledgeEdge],
        *,
        target_classification: ClassificationLevel = ClassificationLevel.SHIP,
    ) -> list[KnowledgeEdge]:
        """AD-692: Federation extension hook. Returns edges whose
        classification level is ``<= target_classification``. Default
        ``SHIP`` excludes ``FLEET``-tagged edges from cross-mesh export
        unless the caller explicitly opts in.

        Pure / synchronous — no resolver needed; classification is on the
        edge itself. NOT consumed in v1 (no federation edge-export
        pathway exists at HEAD); ships as a stable seam for future
        federation work and AD-679 disclosure-routing integration.
        """
        return [
            e for e in edges
            if ClassificationLevel.from_label(e.classification) <= target_classification
        ]

    # ── Internal ──────────────────────────────────────────────────

    def _resolve_tier(self, requester_agent_id: str) -> str:
        if not self._resolver or not requester_agent_id:
            return _DEFAULT_TIER
        try:
            tier = self._resolver(requester_agent_id) or _DEFAULT_TIER
        except Exception:
            logger.debug(
                "AD-692: clearance resolver raised for agent=%s; defaulting to %s",
                requester_agent_id, _DEFAULT_TIER, exc_info=True,
            )
            return _DEFAULT_TIER
        return tier


class ClassificationGatedKnowledgeEdgeStore:
    """AD-692: Decorator wrapper around a ``KnowledgeEdgeStorage``.

    Implements ``KnowledgeEdgeStorage`` Protocol so it is a drop-in
    replacement for ``SQLiteKnowledgeEdgeStore``. Read methods
    (``find_edges``, ``traverse``, ``get_edge``) accept an optional
    ``requester_agent_id`` kwarg; when ``None`` (the default and the case
    for all Wave 37/38/39/40 tests), the wrapper passes through
    unmodified. When set, results are filtered through the gate.

    Write methods (``add_edge``) authorize through the gate when a writer
    identity is supplied; system writers (no ``edge.source_agent``) are
    always permitted.
    """

    def __init__(
        self,
        inner: KnowledgeEdgeStorage,
        gate: KnowledgeEdgeClassificationGate,
    ) -> None:
        self._inner = inner
        self._gate = gate

    # ── Lifecycle delegation ──────────────────────────────────────

    async def start(self) -> None:
        start = getattr(self._inner, "start", None)
        if start is not None:
            await start()

    async def stop(self) -> None:
        stop = getattr(self._inner, "stop", None)
        if stop is not None:
            await stop()

    # ── Writes ────────────────────────────────────────────────────

    async def add_edge(self, edge: KnowledgeEdge) -> str:
        # System writes (no source_agent) are always permitted; otherwise
        # check authorization before delegation.
        if edge.source_agent:
            permitted = await self._gate.authorize_write(
                edge, writer_agent_id=edge.source_agent,
            )
            if not permitted:
                logger.warning(
                    "AD-692: add_edge blocked — agent=%s classification=%s",
                    edge.source_agent, edge.classification,
                )
                return edge.id  # idempotent no-op; caller cannot distinguish from a stored edge
        return await self._inner.add_edge(edge)

    async def update_edge(
        self,
        edge_id: str,
        *,
        confidence: float | None = None,
        weight: float | None = None,
        classification: str | None = None,
    ) -> bool:
        return await self._inner.update_edge(
            edge_id,
            confidence=confidence,
            weight=weight,
            classification=classification,
        )

    async def delete_edge(self, edge_id: str) -> bool:
        return await self._inner.delete_edge(edge_id)

    # ── Reads ─────────────────────────────────────────────────────

    async def get_edge(
        self,
        edge_id: str,
        *,
        requester_agent_id: str | None = None,
    ) -> KnowledgeEdge | None:
        edge = await self._inner.get_edge(edge_id)
        if edge is None or requester_agent_id is None:
            return edge
        filtered = await self._gate.filter_edges(
            [edge], requester_agent_id=requester_agent_id,
        )
        return filtered[0] if filtered else None

    async def find_edges(
        self,
        *,
        source_type: KnowledgeEntityType | None = None,
        source_id: str | None = None,
        target_type: KnowledgeEntityType | None = None,
        target_id: str | None = None,
        relation: KnowledgeRelationType | None = None,
        limit: int = 100,
        requester_agent_id: str | None = None,
    ) -> list[KnowledgeEdge]:
        edges = await self._inner.find_edges(
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            relation=relation,
            limit=limit,
        )
        if requester_agent_id is None:
            return edges
        return await self._gate.filter_edges(
            edges, requester_agent_id=requester_agent_id,
        )

    async def traverse(
        self,
        *,
        source_type: KnowledgeEntityType,
        source_id: str,
        max_hops: int = 3,
        relation_filter: list[KnowledgeRelationType] | None = None,
        requester_agent_id: str | None = None,
    ) -> list[list[KnowledgeEdge]]:
        paths = await self._inner.traverse(
            source_type=source_type,
            source_id=source_id,
            max_hops=max_hops,
            relation_filter=relation_filter,
        )
        if requester_agent_id is None:
            return paths
        # Per-hop filter — drop entire path if ANY hop edge is restricted.
        # Conservative: tests assert this behavior to prevent leakage of
        # partial-path inferences.
        out: list[list[KnowledgeEdge]] = []
        for path in paths:
            filtered = await self._gate.filter_edges(
                list(path), requester_agent_id=requester_agent_id,
            )
            if len(filtered) == len(path):
                out.append(path)
        return out
```

---

## Section 3: Pydantic config — append to `src/probos/config.py`

Insert the new config class adjacent to `EdgeBackfillConfig` (`config.py:1806`). SEARCH/REPLACE:

```
===SEARCH===
class EdgeBackfillConfig(BaseModel):
===REPLACE===
class KnowledgeEdgeClassificationConfig(BaseModel):
    """AD-692: Classification enforcement on knowledge graph edges.

    OSS extension point. Default ``enabled=True`` follows the same precedent
    as ``KnowledgeEdgesConfig`` — the wrapper is a transparent pass-through
    when ``requester_agent_id`` is ``None`` (system/internal callers,
    backward-compatible with Wave 37/38/39/40). Filtering only applies once
    consumers (Oracle Tier 6 via AD-688 plumbing) supply a requester id.
    """
    enabled: bool = True
    default_classification: str = "private"

    @field_validator("default_classification")
    @classmethod
    def _validate_default(cls, v: str) -> str:
        allowed = {"private", "department", "ship", "fleet"}
        if v.lower() not in allowed:
            raise ValueError(
                f"knowledge_edge_classification.default_classification "
                f"must be one of {sorted(allowed)}, got {v!r}"
            )
        return v.lower()


class EdgeBackfillConfig(BaseModel):
===END REPLACE===
```

Then add the field to `SystemConfig` adjacent to `edge_backfill` (`config.py:2147`). SEARCH/REPLACE:

```
===SEARCH===
    knowledge_edges: KnowledgeEdgesConfig = Field(default_factory=KnowledgeEdgesConfig)  # AD-687
    edge_backfill: EdgeBackfillConfig = Field(default_factory=EdgeBackfillConfig)  # AD-689
===REPLACE===
    knowledge_edges: KnowledgeEdgesConfig = Field(default_factory=KnowledgeEdgesConfig)  # AD-687
    knowledge_edge_classification: KnowledgeEdgeClassificationConfig = Field(
        default_factory=KnowledgeEdgeClassificationConfig
    )  # AD-692
    edge_backfill: EdgeBackfillConfig = Field(default_factory=EdgeBackfillConfig)  # AD-689
===END REPLACE===
```

---

## Section 4: Wirer — `src/probos/startup/finalize.py`

Add the wirer immediately after `_wire_nl_graph_query`. SEARCH/REPLACE:

```
===SEARCH===
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


def _wire_clinical_telemetry(*, runtime: Any, config: "SystemConfig") -> bool:
===REPLACE===
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


def _wire_edge_classification(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-692 v1: Wrap ``runtime.knowledge_edges`` with the classification
    gate. Re-stitches Oracle Tier 6 so the wrapper (not the bare store) is
    consulted on graph queries.

    Resolver maps ``requester_agent_id`` -> RecallTier name via the AD-635
    helpers (``effective_recall_tier`` + ``resolve_billet_clearance`` +
    ``resolve_active_grants``). All three pieces of substrate are public on
    runtime (``ontology`` at runtime.py:1651, ``clearance_grant_store`` at
    :1614, registry for rank lookup) and adopted by the time finalize runs.
    """
    cfg = getattr(config, "knowledge_edge_classification", None)
    if not cfg or not cfg.enabled:
        return False
    if getattr(runtime, "knowledge_edges", None) is None:
        # Underlying store disabled (knowledge_edges.enabled=False); no-op.
        return False

    from probos.knowledge.edge_classification import (
        ClassificationGatedKnowledgeEdgeStore,
        KnowledgeEdgeClassificationGate,
    )
    from probos.earned_agency import (
        effective_recall_tier,
        resolve_active_grants,
        resolve_billet_clearance,
    )

    gate = KnowledgeEdgeClassificationGate(
        default_classification=cfg.default_classification,
    )

    def _resolve_tier(agent_id: str) -> str:
        try:
            registry = getattr(runtime, "registry", None)
            agent = registry.get(agent_id) if registry else None
            agent_type = getattr(agent, "agent_type", agent_id) if agent else agent_id
            rank_holder = getattr(agent, "rank", None) if agent else None
            billet = resolve_billet_clearance(
                agent_type, getattr(runtime, "ontology", None),
            )
            grants = resolve_active_grants(
                agent_id, getattr(runtime, "clearance_grant_store", None),
            )
            tier = effective_recall_tier(rank_holder, billet, grants)
            return tier.value  # RecallTier is a str Enum
        except Exception:
            logger.debug(
                "AD-692: resolver failed for agent=%s; defaulting to basic",
                agent_id, exc_info=True,
            )
            return "basic"

    gate.set_clearance_resolver(_resolve_tier)
    wrapper = ClassificationGatedKnowledgeEdgeStore(runtime.knowledge_edges, gate)
    runtime.knowledge_edges = wrapper
    runtime.edge_classification_gate = gate

    # Re-stitch Oracle Tier 6 so it sees the wrapper, not the bare store.
    oracle = getattr(runtime, "_oracle_service", None)
    if oracle is not None:
        try:
            oracle.attach_knowledge_graph(wrapper)
        except Exception:
            logger.warning(
                "AD-692: failed to re-attach wrapped knowledge graph to Oracle; "
                "Tier 6 graph queries continue against the bare store",
                exc_info=True,
            )

    logger.info(
        "AD-692: KnowledgeEdgeClassificationGate v1 initialized "
        "(default_classification=%s; Oracle Tier 6 re-stitched)",
        cfg.default_classification,
    )
    return True


def _wire_clinical_telemetry(*, runtime: Any, config: "SystemConfig") -> bool:
===END REPLACE===
```

Then invoke the new wirer in the finalize cascade IMMEDIATELY after `_wire_nl_graph_query`. SEARCH/REPLACE:

```
===SEARCH===
    if _wire_nl_graph_query(runtime=runtime, config=config):
        logger.info("AD-691: NLGraphQueryService v1 wired during finalization")

    if _wire_clinical_telemetry(runtime=runtime, config=config):
===REPLACE===
    if _wire_nl_graph_query(runtime=runtime, config=config):
        logger.info("AD-691: NLGraphQueryService v1 wired during finalization")

    if _wire_edge_classification(runtime=runtime, config=config):
        logger.info("AD-692: KnowledgeEdgeClassificationGate v1 wired during finalization")

    if _wire_clinical_telemetry(runtime=runtime, config=config):
===END REPLACE===
```

---

## Section 5: Public re-exports — `src/probos/knowledge/__init__.py`

SEARCH/REPLACE to add the new names:

```
===SEARCH===
from probos.knowledge.backfill import EdgeBackfillResult, EdgeBackfillService
from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEdgeStorage,
    KnowledgeEdgeStore,
    KnowledgeEntityType,
    KnowledgeRelationType,
    SQLiteKnowledgeEdgeStore,
)
from probos.knowledge.rejection_cache import (
    RejectionCacheStorage,
    SQLiteRejectionCache,
)
from probos.knowledge.store import KnowledgeStore
===REPLACE===
from probos.knowledge.backfill import EdgeBackfillResult, EdgeBackfillService
from probos.knowledge.edge_classification import (
    ClassificationGatedKnowledgeEdgeStore,
    ClassificationLevel,
    KnowledgeEdgeClassificationGate,
    edge_visible_to,
)
from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEdgeStorage,
    KnowledgeEdgeStore,
    KnowledgeEntityType,
    KnowledgeRelationType,
    SQLiteKnowledgeEdgeStore,
)
from probos.knowledge.rejection_cache import (
    RejectionCacheStorage,
    SQLiteRejectionCache,
)
from probos.knowledge.store import KnowledgeStore
===END REPLACE===
```

Then extend `__all__` (the closing list). Read the current closing bracket region first to find the exact insertion anchor; add `"ClassificationGatedKnowledgeEdgeStore"`, `"ClassificationLevel"`, `"KnowledgeEdgeClassificationGate"`, `"edge_visible_to"` in alphabetical order with the existing names.

---

## Section 6: Oracle Tier 6 plumb — `src/probos/cognitive/oracle_service.py`

Thread `requester_agent_id` from `OracleService.query()`'s existing `agent_id` parameter through to `_query_graph` and the underlying `find_edges` / `traverse` calls.

SEARCH/REPLACE 6a — pass through to `_query_graph` from `query()`:

```
===SEARCH===
        # Tier 6: Knowledge Graph (AD-688) — typed-triple traversal
        if "graph" in active_tiers:
            try:
                tier_results = await self._query_graph(query_text, k=k_per_tier)
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 6 (graph) query failed", exc_info=True)
===REPLACE===
        # Tier 6: Knowledge Graph (AD-688/692) — typed-triple traversal,
        # classification-gated when ``agent_id`` is supplied.
        if "graph" in active_tiers:
            try:
                tier_results = await self._query_graph(
                    query_text, k=k_per_tier, requester_agent_id=agent_id,
                )
                all_results.extend(tier_results)
            except Exception:
                logger.debug("Oracle: Tier 6 (graph) query failed", exc_info=True)
===END REPLACE===
```

SEARCH/REPLACE 6b — extend `_query_graph` signature + plumb to find_edges/traverse:

```
===SEARCH===
    async def _query_graph(
        self,
        query_text: str,
        *,
        k: int,
    ) -> list[OracleResult]:
        """AD-688: Query KnowledgeEdgeStorage (Tier 6).
===REPLACE===
    async def _query_graph(
        self,
        query_text: str,
        *,
        k: int,
        requester_agent_id: str = "",
    ) -> list[OracleResult]:
        """AD-688: Query KnowledgeEdgeStorage (Tier 6).

        AD-692: When ``requester_agent_id`` is non-empty, the wrapper
        (``ClassificationGatedKnowledgeEdgeStore``) filters edges by
        clearance. Empty string preserves the Wave 38 behavior (no
        filtering) so legacy callers and tests stay green.
===END REPLACE===
```

SEARCH/REPLACE 6c — direct `find_edges(source_id=token)` call:

```
===SEARCH===
            # Direct: source_id matches
            try:
                src_hits = await graph.find_edges(
                    source_id=token, limit=_GRAPH_DIRECT_LIMIT,
                )
            except Exception:
                logger.debug("Oracle Tier 6: find_edges(source_id=%r) failed", token, exc_info=True)
                src_hits = []
===REPLACE===
            # Direct: source_id matches
            try:
                src_hits = await self._graph_find_edges(
                    graph, source_id=token, limit=_GRAPH_DIRECT_LIMIT,
                    requester_agent_id=requester_agent_id,
                )
            except Exception:
                logger.debug("Oracle Tier 6: find_edges(source_id=%r) failed", token, exc_info=True)
                src_hits = []
===END REPLACE===
```

SEARCH/REPLACE 6d — direct `find_edges(target_id=token)` call:

```
===SEARCH===
            # Direct: target_id matches
            try:
                tgt_hits = await graph.find_edges(
                    target_id=token, limit=_GRAPH_DIRECT_LIMIT,
                )
            except Exception:
                logger.debug("Oracle Tier 6: find_edges(target_id=%r) failed", token, exc_info=True)
                tgt_hits = []
===REPLACE===
            # Direct: target_id matches
            try:
                tgt_hits = await self._graph_find_edges(
                    graph, target_id=token, limit=_GRAPH_DIRECT_LIMIT,
                    requester_agent_id=requester_agent_id,
                )
            except Exception:
                logger.debug("Oracle Tier 6: find_edges(target_id=%r) failed", token, exc_info=True)
                tgt_hits = []
===END REPLACE===
```

SEARCH/REPLACE 6e — `traverse` 2-hop call:

```
===SEARCH===
            # 2-hop: traverse one extra step from each direct match's target
            for edge in (*src_hits, *tgt_hits):
                try:
                    paths = await graph.traverse(
                        source_type=edge.target_type,
                        source_id=edge.target_id,
                        max_hops=1,
                    )
                except Exception:
                    logger.debug(
                        "Oracle Tier 6: traverse(source_id=%r) failed",
                        edge.target_id, exc_info=True,
                    )
                    continue
===REPLACE===
            # 2-hop: traverse one extra step from each direct match's target
            for edge in (*src_hits, *tgt_hits):
                try:
                    paths = await self._graph_traverse(
                        graph,
                        source_type=edge.target_type,
                        source_id=edge.target_id,
                        max_hops=1,
                        requester_agent_id=requester_agent_id,
                    )
                except Exception:
                    logger.debug(
                        "Oracle Tier 6: traverse(source_id=%r) failed",
                        edge.target_id, exc_info=True,
                    )
                    continue
===END REPLACE===
```

SEARCH/REPLACE 6f — add the two helper methods at the end of the class. Anchor on the closing of `_query_graph` / start of `_expand_via_graph` (verify line via grep at build time):

```
===SEARCH===
    async def _expand_via_graph(
        self,
        merged_results: list[OracleResult],
        *,
        top_k: int = 5,
    ) -> list[OracleResult]:
===REPLACE===
    async def _graph_find_edges(
        self,
        graph: Any,
        *,
        source_id: str | None = None,
        target_id: str | None = None,
        limit: int,
        requester_agent_id: str,
    ) -> list[Any]:
        """AD-692: Pass ``requester_agent_id`` only when the underlying
        store accepts it (the AD-692 wrapper does; the bare AD-687 store
        does not). Keeps Tier 6 compatible with both."""
        kwargs: dict[str, Any] = {"limit": limit}
        if source_id is not None:
            kwargs["source_id"] = source_id
        if target_id is not None:
            kwargs["target_id"] = target_id
        if requester_agent_id:
            kwargs["requester_agent_id"] = requester_agent_id
            try:
                return await graph.find_edges(**kwargs)
            except TypeError:
                kwargs.pop("requester_agent_id", None)
        return await graph.find_edges(**kwargs)

    async def _graph_traverse(
        self,
        graph: Any,
        *,
        source_type: Any,
        source_id: str,
        max_hops: int,
        requester_agent_id: str,
    ) -> list[list[Any]]:
        """AD-692: Mirror of ``_graph_find_edges`` for ``traverse``."""
        kwargs: dict[str, Any] = {
            "source_type": source_type,
            "source_id": source_id,
            "max_hops": max_hops,
        }
        if requester_agent_id:
            kwargs["requester_agent_id"] = requester_agent_id
            try:
                return await graph.traverse(**kwargs)
            except TypeError:
                kwargs.pop("requester_agent_id", None)
        return await graph.traverse(**kwargs)

    async def _expand_via_graph(
        self,
        merged_results: list[OracleResult],
        *,
        top_k: int = 5,
    ) -> list[OracleResult]:
===END REPLACE===
```

The `TypeError` fallback is the safety net for MagicMock-based tests in Wave 38 / pre-existing callers that bind `find_edges` / `traverse` without the new kwarg. Production wraps go through the wrapper which accepts the kwarg.

---

## Section 7: Tests — `tests/test_ad692_classification_enforcement.py` (new file)

≥12 tests required. Use `pytest.mark.asyncio` per the conftest pattern. Real `SQLiteKnowledgeEdgeStore` with `tmp_path` for round-trips; lightweight fakes for the resolver.

### Test plan (12 minimum, target 14):

1. **`test_classification_level_enum_ordering`** — assert `PRIVATE(0) < DEPARTMENT(1) < SHIP(2) < FLEET(3)`; assert `from_label("private") == PRIVATE`; assert `from_label(None) == PRIVATE`; assert `from_label("UNKNOWN") == PRIVATE` (defensive default).

2. **`test_edge_visible_to_matrix`** — parametrized matrix of (tier × edge classification × ownership) → expected visibility:
   - `basic` + `private` + owner=requester → True
   - `basic` + `private` + owner=other → False
   - `basic` + `department` + any → False
   - `enhanced` + `department` + any → True
   - `enhanced` + `ship` + any → False
   - `full` + `ship` + any → True
   - `full` + `fleet` + any → False
   - `oracle` + `fleet` + any → True

3. **`test_gate_filter_edges_full_clearance_returns_mixed`** — 4 edges with each classification; ORACLE-clearance requester → all 4 returned.

4. **`test_gate_filter_edges_drops_fleet_for_full`** — 4 edges with each classification; FULL-clearance requester → only PRIVATE(owned)+DEPARTMENT+SHIP = 3 edges (not FLEET).

5. **`test_gate_authorize_write_blocks_low_tier_high_classification`** — ENHANCED writer attempting to add a FLEET edge → `authorize_write` returns False.

6. **`test_gate_authorize_write_permits_owner_private`** — any-tier writer adding own PRIVATE edge → True.

7. **`test_gate_filter_for_export_default_excludes_fleet`** — list of 4 classifications; default `target=SHIP` → 3 returned (no FLEET); explicit `target=FLEET` → all 4.

8. **`test_wrapper_find_edges_with_requester_filters`** — real `SQLiteKnowledgeEdgeStore` populated with 3 edges (private/department/ship), wrapped with gate + ENHANCED resolver → `find_edges(requester_agent_id="alice")` returns DEPARTMENT + (PRIVATE if owned). Owner of PRIVATE edge is "alice"; requester is "alice" → all 2 returned (private+department).

9. **`test_wrapper_find_edges_no_requester_passes_through`** — same fixture as #8; `find_edges()` with no `requester_agent_id` → all 3 edges returned (Wave 37 backward-compat).

10. **`test_wrapper_traverse_filters_per_path_drops_blocked`** — populate a 2-hop chain `A -> B (ship) -> C (fleet)`; wrapper.traverse with FULL-clearance requester → path containing FLEET hop dropped entirely. Single-hop `A -> B` path retained.

11. **`test_wrapper_default_classification_when_none`** — edge stored with `classification=None`; wrapped read with non-owner requester → not returned (treated as PRIVATE, owner-only).

12. **`test_wrapper_add_edge_blocks_unauthorized_write`** — gate with stub resolver always returning `"basic"`; attempt to wrapper.add_edge(edge with `classification="ship"`, `source_agent="alice"`) → returns the edge id but `inner.find_edges(limit=100)` shows the edge was NOT persisted.

13. **`test_oracle_tier6_with_requester_agent_id_reduces_results`** (integration) — stub graph store returns 4 edges of mixed classifications via `find_edges`; `OracleService._query_graph(query_text="alice", k=10, requester_agent_id="alice")` calls wrapper which filters; assert returned `OracleResult` count < unfiltered count. Use a real `ClassificationGatedKnowledgeEdgeStore` wrapped over a fake inner-store fixture; resolver returns `"enhanced"`.

14. **`test_backward_compat_existing_ad687_smoke`** — wrap a real `SQLiteKnowledgeEdgeStore` populated with 5 edges of varying classifications. Call `find_edges()` and `traverse()` without `requester_agent_id`. Counts MUST match the pre-wrap counts (the wrapper is a no-op pass-through for legacy callers).

Drop targets if drift: tests #6 (overlaps #2) and #14 (covered by #9 mechanically), landing at 12.

---

## What This Does NOT Change

- **No new EventType.** Audit-event emission for denied accesses is OUT OF SCOPE for v1; if needed, add as AD-692b.
- **No persistence of denied-access audit log.** In-memory-only ring buffer also OUT for v1 (would couple gate to event bus). AD-692b can layer this.
- **No federation export of edges.** `filter_for_export` ships as a pure helper / extension hook. Federation today (`federation/bridge.py`) does not export `KnowledgeEdge` objects; that work is a future AD.
- **No bridging to AD-679 `DisclosureLevel`.** The two taxonomies are intentionally orthogonal (recipient routing vs. data-scope-of-audience). Bridging is an AD-692c if commercial overlay needs unified policy.
- **No per-department classification matching.** `KnowledgeEdge` has no `dept` field; v1's `DEPARTMENT` gate is tier-based only.
- **No encryption-at-rest** for edge fields.
- **No fine-grained per-edge ACLs** beyond level-based gating.
- **No agent / pool / intent.** This is a guard layer. Existing callers (Oracle Tier 6) consume it transparently. The decomposer is unchanged.
- **No HXI surface.** Captain-facing visibility deferred to AD-692d if requested.

---

## Standing Conventions

- Engineering Principles in `.github/copilot-instructions.md` apply.
- No private-attribute access across module boundaries (`runtime.ontology` and `runtime.clearance_grant_store` are public; `runtime.registry` is public).
- Layer discipline: `knowledge/edge_classification.py` does NOT import `earned_agency` or `ontology`; the wirer in `startup/finalize.py` does the bridging via the late-bind setter. (Same pattern as AD-660 CausalReasoner.)
- Default `enabled=True` deviation from Wave-10 transitional-flag convention: documented inline in config docstring with the same rationale as `KnowledgeEdgesConfig` / `EdgeBackfillConfig`. Reviewer should NOT flag.
- **Property collision warning:** `runtime.edge_classification_gate` is a NEW attribute. Verified collision-free against `_classification_gate` (AD-530, used in `security/classification.py`), `classification_gate` config field, and `_disclosure_router`.
- Frozen dataclass / IntEnum field ordering: `ClassificationLevel` values are explicit ints matching `_CLASSIFICATION_LEVELS` — do NOT renumber.
- Test isolation: each test creates its own `tmp_path`-backed store; no shared mutable state.

---

## Phantom-API Pre-Check

Run before final commit:

```pwsh
./scripts/phantom-api-precheck.ps1 prompts/ad-692-classification-enforcement-v1.md
```

Expected FPs (document in build report):

- `runtime.edge_classification_gate` — introduced by this prompt.
- `runtime.knowledge_edges` — already public (AD-687, runtime.py:429).
- `ClassificationGatedKnowledgeEdgeStore.X`, `KnowledgeEdgeClassificationGate.X` — symbols introduced by this prompt; not yet in class index.
- `RecallTier.value` — `RecallTier` is a `str, Enum` (verified at earned_agency.py:53); `.value` is the string form (e.g., `"basic"`).
- Any `class:TypeError` reference — Python builtin (used in fallback in Section 6f).

0 NEW phantoms expected. If new phantoms appear, halt and surface to architect.

---

## Acceptance Criteria

1. `tests/test_ad692_classification_enforcement.py` contains ≥12 tests, all passing.
2. Full parallel gate (`pytest tests/ -q -n 8 --dist=loadfile`) passes; net delta ≥ +12 vs Wave 41 baseline (11042). Target: 11054.
3. All Wave 37/38/39/40/41 tests continue to pass — wrapper is a no-op when `requester_agent_id` is None.
4. `runtime.knowledge_edges` is the wrapper post-finalize (assert via integration smoke or runtime-shape test if convenient).
5. `runtime.edge_classification_gate` is a public attribute pointing at the gate.
6. Oracle Tier 6 (`_query_graph`) accepts and threads `requester_agent_id`; calls fall back gracefully (TypeError catch) for non-wrapper graph instances.
7. `filter_for_export` is a pure synchronous helper (no async, no resolver dependency).
8. No `print()`; structured logger calls only; messages tagged `AD-692:`.
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Tracking

Update on commit:

- **PROGRESS.md** — prepend "AD-692 v1 CLOSED. Classification Enforcement on Knowledge Graph..." entry. Update test count to new baseline.
- **docs/development/roadmap.md** — flip AD-692 status from `Future, Commercial` to `Complete, OSS extension point` (commercial overlay separate). Wording: keep `Layer:Commercial` per GH issue; clarify "OSS extension point shipped, commercial overlay layers on top."
- **DECISIONS.md** — prepend AD-692 entry to the Era V section. Single paragraph: scope, taxonomy decision, orthogonality with AD-679, OSS-vs-commercial boundary.

---

## Commit message

```
AD-692: Classification Enforcement on Knowledge Graph (Wave 42, closes #386)
```
