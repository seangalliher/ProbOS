"""Tests for AD-687 Knowledge Edge Store."""

from __future__ import annotations

import time
import pytest

from probos.knowledge.edges import (
    MAX_HOPS_CEILING,
    KnowledgeEdge,
    KnowledgeEdgeStorage,
    KnowledgeEntityType,
    KnowledgeRelationType,
    SQLiteKnowledgeEdgeStore,
)


@pytest.fixture
async def store(tmp_path):
    s = SQLiteKnowledgeEdgeStore(db_path=str(tmp_path / "edges.sqlite"))
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


def _edge(src, rel, tgt, **kw):
    return KnowledgeEdge(
        source_type=KnowledgeEntityType.AGENT,
        source_id=src,
        relation=rel,
        target_type=KnowledgeEntityType.AGENT,
        target_id=tgt,
        **kw,
    )


# 1. Schema/migration creates table + indexes
@pytest.mark.asyncio
async def test_schema_creates_table_and_indexes(tmp_path):
    s = SQLiteKnowledgeEdgeStore(db_path=str(tmp_path / "x.sqlite"))
    await s.start()
    try:
        cur = await s._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_edges'"
        )
        assert (await cur.fetchone())["name"] == "knowledge_edges"
        cur = await s._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_ke_%'"
        )
        idxs = {r["name"] for r in await cur.fetchall()}
        assert {"idx_ke_source", "idx_ke_target", "idx_ke_relation", "idx_ke_classification"} <= idxs
    finally:
        await s.stop()


# 2. add_edge happy path returns id and persists
@pytest.mark.asyncio
async def test_add_edge_returns_id_and_persists(store):
    e = _edge("a1", KnowledgeRelationType.REPORTS_TO, "a2", classification="ship")
    returned_id = await store.add_edge(e)
    assert returned_id == e.id
    fetched = await store.get_edge(e.id)
    assert fetched is not None
    assert fetched.source_id == "a1" and fetched.target_id == "a2"
    assert fetched.relation == KnowledgeRelationType.REPORTS_TO
    assert fetched.classification == "ship"


# 3. get_edge by id round-trips ALL 13 fields
@pytest.mark.asyncio
async def test_get_edge_round_trip_all_fields(store):
    now = time.time()
    e = KnowledgeEdge(
        id="custom-id-1",
        source_type=KnowledgeEntityType.DEPARTMENT,
        source_id="engineering",
        relation=KnowledgeRelationType.MEMBER_OF,
        target_type=KnowledgeEntityType.AGENT,
        target_id="ag-7",
        confidence=0.8,
        weight=0.6,
        classification="department",
        source_agent="agent-x",
        source_duty="duty-42",
        created_at=now,
        updated_at=now,
    )
    await store.add_edge(e)
    got = await store.get_edge("custom-id-1")
    assert got is not None
    assert got.to_dict() == e.to_dict()


# 4. find_edges filter by source_type + source_id
@pytest.mark.asyncio
async def test_find_edges_by_source(store):
    await store.add_edge(_edge("a1", KnowledgeRelationType.REPORTS_TO, "a2"))
    await store.add_edge(_edge("a1", KnowledgeRelationType.MEMBER_OF, "a3"))
    await store.add_edge(_edge("a9", KnowledgeRelationType.REPORTS_TO, "a2"))
    found = await store.find_edges(
        source_type=KnowledgeEntityType.AGENT, source_id="a1"
    )
    assert len(found) == 2
    assert {e.target_id for e in found} == {"a2", "a3"}


# 5. find_edges filter by relation
@pytest.mark.asyncio
async def test_find_edges_by_relation(store):
    await store.add_edge(_edge("a1", KnowledgeRelationType.REPORTS_TO, "a2"))
    await store.add_edge(_edge("a3", KnowledgeRelationType.REPORTS_TO, "a4"))
    await store.add_edge(_edge("a5", KnowledgeRelationType.MEMBER_OF, "a6"))
    found = await store.find_edges(relation=KnowledgeRelationType.REPORTS_TO)
    assert len(found) == 2
    assert all(e.relation == KnowledgeRelationType.REPORTS_TO for e in found)


# 6. update_edge changes confidence + weight + advances updated_at
@pytest.mark.asyncio
async def test_update_edge_advances_updated_at(store):
    e = _edge("a1", KnowledgeRelationType.COMPETENT_IN, "skill-x",
              confidence=0.5, weight=0.5)
    await store.add_edge(e)
    original_updated = (await store.get_edge(e.id)).updated_at
    time.sleep(0.01)  # ensure clock tick
    ok = await store.update_edge(e.id, confidence=0.9, weight=0.7)
    assert ok is True
    after = await store.get_edge(e.id)
    assert after.confidence == 0.9 and after.weight == 0.7
    assert after.updated_at > original_updated


# 7. delete_edge — verify gone
@pytest.mark.asyncio
async def test_delete_edge(store):
    e = _edge("a1", KnowledgeRelationType.REPORTS_TO, "a2")
    await store.add_edge(e)
    ok = await store.delete_edge(e.id)
    assert ok is True
    assert await store.get_edge(e.id) is None
    # Idempotent — second delete returns False
    assert await store.delete_edge(e.id) is False


# 8. traverse 1-hop returns single-edge paths
@pytest.mark.asyncio
async def test_traverse_one_hop(store):
    await store.add_edge(_edge("a1", KnowledgeRelationType.REPORTS_TO, "a2"))
    await store.add_edge(_edge("a1", KnowledgeRelationType.REPORTS_TO, "a3"))
    paths = await store.traverse(
        source_type=KnowledgeEntityType.AGENT,
        source_id="a1",
        max_hops=1,
    )
    assert len(paths) == 2
    assert all(len(p) == 1 for p in paths)
    assert {p[0].target_id for p in paths} == {"a2", "a3"}


# 9. traverse 2-hop with relation_filter
@pytest.mark.asyncio
async def test_traverse_two_hop_with_relation_filter(store):
    # Chain a1 -reports_to-> a2 -reports_to-> a3, and noise edge a2 -member_of-> dept
    await store.add_edge(_edge("a1", KnowledgeRelationType.REPORTS_TO, "a2"))
    await store.add_edge(_edge("a2", KnowledgeRelationType.REPORTS_TO, "a3"))
    await store.add_edge(_edge("a2", KnowledgeRelationType.MEMBER_OF, "dept-x"))
    paths = await store.traverse(
        source_type=KnowledgeEntityType.AGENT,
        source_id="a1",
        max_hops=2,
        relation_filter=[KnowledgeRelationType.REPORTS_TO],
    )
    # Expect: 1-hop a1->a2, 2-hop a1->a2->a3. NO member_of branch.
    assert len(paths) == 2
    by_len = {len(p): p for p in paths}
    assert by_len[1][0].target_id == "a2"
    assert by_len[2][1].target_id == "a3"
    # Confirm no member_of in any returned edge
    for p in paths:
        for edge in p:
            assert edge.relation == KnowledgeRelationType.REPORTS_TO


# 10. traverse caps at MAX_HOPS_CEILING when caller passes higher value
@pytest.mark.asyncio
async def test_traverse_caps_at_max_hops_ceiling(store):
    # 5-link chain a1 -> a2 -> a3 -> a4 -> a5 -> a6
    for i in range(1, 6):
        await store.add_edge(_edge(f"a{i}", KnowledgeRelationType.REPORTS_TO, f"a{i+1}"))
    paths = await store.traverse(
        source_type=KnowledgeEntityType.AGENT,
        source_id="a1",
        max_hops=5,  # exceeds ceiling
    )
    # Deepest path is bounded by MAX_HOPS_CEILING
    assert paths
    assert max(len(p) for p in paths) <= MAX_HOPS_CEILING == 3


# 11. cycle detection — A→B→A→B does NOT infinite-loop
@pytest.mark.asyncio
async def test_traverse_cycle_terminates(store):
    await store.add_edge(_edge("a1", KnowledgeRelationType.DEPENDS_ON, "a2"))
    await store.add_edge(_edge("a2", KnowledgeRelationType.DEPENDS_ON, "a1"))
    paths = await store.traverse(
        source_type=KnowledgeEntityType.AGENT,
        source_id="a1",
        max_hops=3,
    )
    # Walk: a1->a2 (depth 1); a2->a1 would re-add a1 to path → blocked.
    # Expect exactly one path of length 1.
    assert len(paths) == 1
    assert len(paths[0]) == 1
    assert paths[0][0].source_id == "a1" and paths[0][0].target_id == "a2"


# 12. confidence/weight bounds validation in dataclass
def test_edge_validation_rejects_out_of_bounds():
    with pytest.raises(ValueError, match="confidence"):
        KnowledgeEdge(
            source_type=KnowledgeEntityType.AGENT, source_id="a", relation=KnowledgeRelationType.REPORTS_TO,
            target_type=KnowledgeEntityType.AGENT, target_id="b", confidence=1.5,
        )
    with pytest.raises(ValueError, match="weight"):
        KnowledgeEdge(
            source_type=KnowledgeEntityType.AGENT, source_id="a", relation=KnowledgeRelationType.REPORTS_TO,
            target_type=KnowledgeEntityType.AGENT, target_id="b", weight=-0.1,
        )
    with pytest.raises(ValueError, match="classification"):
        KnowledgeEdge(
            source_type=KnowledgeEntityType.AGENT, source_id="a", relation=KnowledgeRelationType.REPORTS_TO,
            target_type=KnowledgeEntityType.AGENT, target_id="b", classification="top_secret",
        )
    # KnowledgeEdgeStorage Protocol acceptance smoke (runtime_checkable)
    s = SQLiteKnowledgeEdgeStore(db_path=None)
    assert isinstance(s, KnowledgeEdgeStorage)
