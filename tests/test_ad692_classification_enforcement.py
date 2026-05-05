"""AD-692 v1: Classification Enforcement on Knowledge Graph Edges."""

from __future__ import annotations

import pytest

from probos.knowledge.edge_classification import (
    ClassificationGatedKnowledgeEdgeStore,
    ClassificationLevel,
    KnowledgeEdgeClassificationGate,
    edge_visible_to,
)
from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEntityType,
    KnowledgeRelationType,
    SQLiteKnowledgeEdgeStore,
)


def _make_edge(
    *,
    source_id: str = "alice",
    target_id: str = "engineering",
    relation: KnowledgeRelationType = KnowledgeRelationType.MEMBER_OF,
    classification: str | None = None,
    source_agent: str | None = None,
) -> KnowledgeEdge:
    return KnowledgeEdge(
        source_type=KnowledgeEntityType.AGENT,
        source_id=source_id,
        relation=relation,
        target_type=KnowledgeEntityType.DEPARTMENT,
        target_id=target_id,
        classification=classification,
        source_agent=source_agent,
    )


# ── 1. Enum ────────────────────────────────────────────────────


def test_classification_level_enum_ordering() -> None:
    assert ClassificationLevel.PRIVATE < ClassificationLevel.DEPARTMENT
    assert ClassificationLevel.DEPARTMENT < ClassificationLevel.SHIP
    assert ClassificationLevel.SHIP < ClassificationLevel.FLEET
    assert int(ClassificationLevel.PRIVATE) == 0
    assert int(ClassificationLevel.FLEET) == 3
    assert ClassificationLevel.from_label("private") == ClassificationLevel.PRIVATE
    assert ClassificationLevel.from_label("FLEET") == ClassificationLevel.FLEET
    assert ClassificationLevel.from_label(None) == ClassificationLevel.PRIVATE
    assert ClassificationLevel.from_label("") == ClassificationLevel.PRIVATE
    assert ClassificationLevel.from_label("UNKNOWN") == ClassificationLevel.PRIVATE


# ── 2. edge_visible_to matrix ──────────────────────────────────


@pytest.mark.parametrize(
    "tier,classification,owner,requester,expected",
    [
        ("basic", "private", "alice", "alice", True),
        ("basic", "private", "alice", "bob", False),
        ("basic", "department", None, "bob", False),
        ("enhanced", "department", None, "bob", True),
        ("enhanced", "ship", None, "bob", False),
        ("full", "ship", None, "bob", True),
        ("full", "fleet", None, "bob", False),
        ("oracle", "fleet", None, "bob", True),
    ],
)
def test_edge_visible_to_matrix(
    tier: str, classification: str, owner: str | None, requester: str, expected: bool,
) -> None:
    edge = _make_edge(classification=classification, source_agent=owner)
    assert edge_visible_to(edge, requester_tier=tier, requester_agent_id=requester) is expected


# ── 3. gate.filter_edges full clearance ────────────────────────


@pytest.mark.asyncio
async def test_gate_filter_edges_full_clearance_returns_mixed() -> None:
    gate = KnowledgeEdgeClassificationGate()
    gate.set_clearance_resolver(lambda _aid: "oracle")
    edges = [
        _make_edge(classification="private", source_agent="alice"),
        _make_edge(classification="department"),
        _make_edge(classification="ship"),
        _make_edge(classification="fleet"),
    ]
    out = await gate.filter_edges(edges, requester_agent_id="alice")
    assert len(out) == 4


# ── 4. drops fleet for FULL ────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_filter_edges_drops_fleet_for_full() -> None:
    gate = KnowledgeEdgeClassificationGate()
    gate.set_clearance_resolver(lambda _aid: "full")
    edges = [
        _make_edge(classification="private", source_agent="alice"),
        _make_edge(classification="department"),
        _make_edge(classification="ship"),
        _make_edge(classification="fleet"),
    ]
    out = await gate.filter_edges(edges, requester_agent_id="alice")
    assert len(out) == 3
    assert all(e.classification != "fleet" for e in out)


# ── 5. authorize_write blocks low_tier high classification ─────


@pytest.mark.asyncio
async def test_gate_authorize_write_blocks_low_tier_high_classification() -> None:
    gate = KnowledgeEdgeClassificationGate()
    gate.set_clearance_resolver(lambda _aid: "enhanced")
    edge = _make_edge(classification="fleet", source_agent="alice")
    assert await gate.authorize_write(edge, writer_agent_id="alice") is False


# ── 6. authorize_write permits owner private ──────────────────


@pytest.mark.asyncio
async def test_gate_authorize_write_permits_owner_private() -> None:
    gate = KnowledgeEdgeClassificationGate()
    gate.set_clearance_resolver(lambda _aid: "basic")
    edge = _make_edge(classification="private", source_agent="alice")
    assert await gate.authorize_write(edge, writer_agent_id="alice") is True


# ── 7. filter_for_export default excludes fleet ────────────────


def test_gate_filter_for_export_default_excludes_fleet() -> None:
    gate = KnowledgeEdgeClassificationGate()
    edges = [
        _make_edge(classification="private", source_agent="alice"),
        _make_edge(classification="department"),
        _make_edge(classification="ship"),
        _make_edge(classification="fleet"),
    ]
    default_out = gate.filter_for_export(edges)
    assert len(default_out) == 3
    assert all(e.classification != "fleet" for e in default_out)
    explicit_out = gate.filter_for_export(edges, target_classification=ClassificationLevel.FLEET)
    assert len(explicit_out) == 4


# ── 8. wrapper.find_edges with requester filters ───────────────


@pytest.mark.asyncio
async def test_wrapper_find_edges_with_requester_filters(tmp_path) -> None:
    inner = SQLiteKnowledgeEdgeStore(db_path=str(tmp_path / "edges.db"))
    await inner.start()
    try:
        await inner.add_edge(_make_edge(classification="private", source_agent="alice"))
        await inner.add_edge(_make_edge(classification="department"))
        await inner.add_edge(_make_edge(classification="ship"))

        gate = KnowledgeEdgeClassificationGate()
        gate.set_clearance_resolver(lambda _aid: "enhanced")
        wrapper = ClassificationGatedKnowledgeEdgeStore(inner, gate)

        out = await wrapper.find_edges(requester_agent_id="alice")
        # alice (ENHANCED): owns private, sees department, blocked from ship
        kinds = {e.classification for e in out}
        assert kinds == {"private", "department"}
    finally:
        await inner.stop()


# ── 9. no requester passes through ─────────────────────────────


@pytest.mark.asyncio
async def test_wrapper_find_edges_no_requester_passes_through(tmp_path) -> None:
    inner = SQLiteKnowledgeEdgeStore(db_path=str(tmp_path / "edges.db"))
    await inner.start()
    try:
        await inner.add_edge(_make_edge(classification="private", source_agent="alice"))
        await inner.add_edge(_make_edge(classification="department"))
        await inner.add_edge(_make_edge(classification="ship"))

        gate = KnowledgeEdgeClassificationGate()
        gate.set_clearance_resolver(lambda _aid: "basic")
        wrapper = ClassificationGatedKnowledgeEdgeStore(inner, gate)

        out = await wrapper.find_edges()
        assert len(out) == 3
    finally:
        await inner.stop()


# ── 10. traverse drops blocked path ────────────────────────────


@pytest.mark.asyncio
async def test_wrapper_traverse_filters_per_path_drops_blocked(tmp_path) -> None:
    inner = SQLiteKnowledgeEdgeStore(db_path=str(tmp_path / "edges.db"))
    await inner.start()
    try:
        # A (agent) -> B (department) ship-classified
        edge_ab = KnowledgeEdge(
            source_type=KnowledgeEntityType.AGENT,
            source_id="A",
            relation=KnowledgeRelationType.MEMBER_OF,
            target_type=KnowledgeEntityType.DEPARTMENT,
            target_id="B",
            classification="ship",
        )
        # B (department) -> C (department) fleet-classified
        edge_bc = KnowledgeEdge(
            source_type=KnowledgeEntityType.DEPARTMENT,
            source_id="B",
            relation=KnowledgeRelationType.REPORTS_TO,
            target_type=KnowledgeEntityType.DEPARTMENT,
            target_id="C",
            classification="fleet",
        )
        await inner.add_edge(edge_ab)
        await inner.add_edge(edge_bc)

        gate = KnowledgeEdgeClassificationGate()
        gate.set_clearance_resolver(lambda _aid: "full")  # sees ship, NOT fleet
        wrapper = ClassificationGatedKnowledgeEdgeStore(inner, gate)

        paths = await wrapper.traverse(
            source_type=KnowledgeEntityType.AGENT,
            source_id="A",
            max_hops=2,
            requester_agent_id="alice",
        )
        # Any path containing the FLEET edge must be dropped entirely.
        for path in paths:
            assert all(e.classification != "fleet" for e in path)
    finally:
        await inner.stop()


# ── 11. None classification treated as PRIVATE ─────────────────


@pytest.mark.asyncio
async def test_wrapper_default_classification_when_none(tmp_path) -> None:
    inner = SQLiteKnowledgeEdgeStore(db_path=str(tmp_path / "edges.db"))
    await inner.start()
    try:
        await inner.add_edge(_make_edge(classification=None, source_agent="alice"))

        gate = KnowledgeEdgeClassificationGate()
        gate.set_clearance_resolver(lambda _aid: "oracle")
        wrapper = ClassificationGatedKnowledgeEdgeStore(inner, gate)

        # Bob is not the owner; None coerces to PRIVATE → owner-only.
        out = await wrapper.find_edges(requester_agent_id="bob")
        assert out == []
        # Alice IS the owner.
        out_owner = await wrapper.find_edges(requester_agent_id="alice")
        assert len(out_owner) == 1
    finally:
        await inner.stop()


# ── 12. add_edge blocks unauthorized write ─────────────────────


@pytest.mark.asyncio
async def test_wrapper_add_edge_blocks_unauthorized_write(tmp_path) -> None:
    inner = SQLiteKnowledgeEdgeStore(db_path=str(tmp_path / "edges.db"))
    await inner.start()
    try:
        gate = KnowledgeEdgeClassificationGate()
        gate.set_clearance_resolver(lambda _aid: "basic")  # cannot write SHIP
        wrapper = ClassificationGatedKnowledgeEdgeStore(inner, gate)

        edge = _make_edge(classification="ship", source_agent="alice")
        returned_id = await wrapper.add_edge(edge)
        # Returns the id (idempotent surface) but did NOT persist.
        assert returned_id == edge.id
        persisted = await inner.find_edges(limit=100)
        assert len(persisted) == 0
    finally:
        await inner.stop()


# ── 13. Oracle Tier 6 integration with requester ──────────────


@pytest.mark.asyncio
async def test_oracle_tier6_with_requester_agent_id_reduces_results(tmp_path) -> None:
    from probos.cognitive.oracle_service import OracleService

    inner = SQLiteKnowledgeEdgeStore(db_path=str(tmp_path / "edges.db"))
    await inner.start()
    try:
        # 4 edges, all on token 'alice' so the Oracle entity-extractor matches.
        for cls in ("private", "department", "ship", "fleet"):
            await inner.add_edge(
                _make_edge(
                    source_id="alice",
                    classification=cls,
                    source_agent="alice" if cls == "private" else None,
                )
            )

        gate = KnowledgeEdgeClassificationGate()
        gate.set_clearance_resolver(lambda _aid: "enhanced")
        wrapper = ClassificationGatedKnowledgeEdgeStore(inner, gate)

        oracle = OracleService()
        oracle.attach_knowledge_graph(wrapper)

        unfiltered = await oracle._query_graph("alice", k=10)
        filtered = await oracle._query_graph("alice", k=10, requester_agent_id="alice")
        assert len(filtered) < len(unfiltered)
    finally:
        await inner.stop()


# ── 14. Backward-compat smoke ──────────────────────────────────


@pytest.mark.asyncio
async def test_backward_compat_existing_ad687_smoke(tmp_path) -> None:
    inner = SQLiteKnowledgeEdgeStore(db_path=str(tmp_path / "edges.db"))
    await inner.start()
    try:
        for cls in ("private", "department", "ship", "fleet", None):
            await inner.add_edge(
                _make_edge(
                    classification=cls,
                    source_agent="sys" if cls == "private" else None,
                )
            )

        pre_find = await inner.find_edges(limit=100)
        pre_traverse = await inner.traverse(
            source_type=KnowledgeEntityType.AGENT,
            source_id="alice",
            max_hops=1,
        )

        gate = KnowledgeEdgeClassificationGate()
        gate.set_clearance_resolver(lambda _aid: "basic")
        wrapper = ClassificationGatedKnowledgeEdgeStore(inner, gate)

        post_find = await wrapper.find_edges(limit=100)
        post_traverse = await wrapper.traverse(
            source_type=KnowledgeEntityType.AGENT,
            source_id="alice",
            max_hops=1,
        )
        assert len(post_find) == len(pre_find) == 5
        assert len(post_traverse) == len(pre_traverse)
    finally:
        await inner.stop()
