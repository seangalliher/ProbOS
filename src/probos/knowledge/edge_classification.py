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
