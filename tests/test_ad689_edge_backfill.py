"""AD-689 v1: Edge population from existing data — Wave 39."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.knowledge.backfill import (
    EdgeBackfillResult,
    EdgeBackfillService,
    _deterministic_edge_id,
)
from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEntityType,
    KnowledgeRelationType,
    SQLiteKnowledgeEdgeStore,
)
from probos.mesh.routing import REL_AGENT, REL_INTENT
from probos.types import Episode


# ── Fixtures ─────────────────────────────────────────────────────


def _stub_ontology(
    *,
    assignments: list[SimpleNamespace],
    posts: list[SimpleNamespace],
) -> MagicMock:
    ont = MagicMock()
    ont.get_all_assignments.return_value = assignments
    ont.get_posts.return_value = posts
    by_id = {p.id: p for p in posts}
    ont.get_post.side_effect = lambda pid: by_id.get(pid)
    return ont


@pytest.fixture
async def edge_store(tmp_path: Path):
    store = SQLiteKnowledgeEdgeStore(db_path=str(tmp_path / "edges.sqlite"))
    await store.start()
    yield store
    await store.stop()


# ── Test 1: Service shape ────────────────────────────────────────


def test_service_shape_and_result_dataclass():
    res = EdgeBackfillResult(ontology=1, hebbian=2, episodes=3, decisions=4)
    assert res.total == 10
    d = res.to_dict()
    assert d["total"] == 10 and d["ontology"] == 1
    with pytest.raises(Exception):
        res.ontology = 99  # type: ignore[misc]
    svc = EdgeBackfillService(
        knowledge_edges=MagicMock(),
        ontology=None,
        hebbian_router=None,
        episodic_memory=None,
        decisions_paths=[],
        hebbian_threshold=0.7,
    )
    assert svc._hebbian_threshold == 0.7


# ── Test 2: backfill_ontology ────────────────────────────────────


@pytest.mark.asyncio
async def test_backfill_ontology_emits_reports_to_and_member_of(edge_store):
    captain_post = SimpleNamespace(
        id="captain", department_id="bridge", reports_to=None,
    )
    chief_eng_post = SimpleNamespace(
        id="chief_engineer", department_id="engineering", reports_to="captain",
    )
    captain_assign = SimpleNamespace(agent_type="captain", post_id="captain")
    chief_assign = SimpleNamespace(agent_type="engineering_officer", post_id="chief_engineer")
    ont = _stub_ontology(
        assignments=[captain_assign, chief_assign],
        posts=[captain_post, chief_eng_post],
    )
    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=ont,
        hebbian_router=None,
        episodic_memory=None,
        decisions_paths=[],
    )
    n = await svc.backfill_ontology()
    assert n == 3
    edges = await edge_store.find_edges(limit=100)
    relations = sorted(e.relation.value for e in edges)
    assert relations == ["member_of", "member_of", "reports_to"]
    rep = next(e for e in edges if e.relation == KnowledgeRelationType.REPORTS_TO)
    assert rep.source_id == "engineering_officer" and rep.target_id == "captain"
    assert rep.source_agent == "edge_backfill" and rep.source_duty == "ontology"


# ── Test 3: backfill_hebbian respects threshold ──────────────────


@pytest.mark.asyncio
async def test_backfill_hebbian_filters_below_threshold(edge_store):
    router = MagicMock()
    router.all_weights_typed.return_value = {
        ("ship.scan", "agent_alpha", REL_INTENT): 0.7,
        ("ship.scan", "agent_beta", REL_INTENT): 0.3,
        ("ship.report", "agent_alpha", REL_INTENT): 0.6,
        ("agent_alpha", "agent_beta", REL_AGENT): 0.9,
    }
    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=None,
        hebbian_router=router,
        episodic_memory=None,
        decisions_paths=[],
    )
    n = await svc.backfill_hebbian()
    assert n == 2
    edges = await edge_store.find_edges(limit=100)
    assert all(e.relation == KnowledgeRelationType.COMPETENT_IN for e in edges)
    capabilities = sorted(e.target_id for e in edges)
    assert capabilities == ["ship.report", "ship.scan"]


# ── Test 4: backfill_hebbian custom threshold ────────────────────


@pytest.mark.asyncio
async def test_backfill_hebbian_custom_threshold(edge_store):
    router = MagicMock()
    router.all_weights_typed.return_value = {
        ("a", "x", REL_INTENT): 0.4,
        ("b", "x", REL_INTENT): 0.6,
    }
    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=None,
        hebbian_router=router,
        episodic_memory=None,
        decisions_paths=[],
        hebbian_threshold=0.5,
    )
    n = await svc.backfill_hebbian(threshold=0.7)
    assert n == 0
    n = await svc.backfill_hebbian(threshold=0.1)
    assert n == 2


# ── Test 5: backfill_episodes ────────────────────────────────────


@pytest.mark.asyncio
async def test_backfill_episodes_emits_involved_in_per_agent(edge_store):
    ep1 = Episode(id="ep-1", timestamp=time.time(), user_input="x", agent_ids=["alpha"])
    ep2 = Episode(id="ep-2", timestamp=time.time(), user_input="y", agent_ids=["alpha", "beta"])
    ep3 = Episode(id="ep-3", timestamp=time.time(), user_input="z", agent_ids=[])
    em = MagicMock()
    em.list_episodes = AsyncMock(return_value=[ep1, ep2, ep3])
    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=None,
        hebbian_router=None,
        episodic_memory=em,
        decisions_paths=[],
    )
    n = await svc.backfill_episodes()
    assert n == 3
    edges = await edge_store.find_edges(limit=100)
    assert all(e.relation == KnowledgeRelationType.INVOLVED_IN for e in edges)
    incidents = sorted(e.target_id for e in edges)
    assert incidents == ["ep-1", "ep-2", "ep-2"]


# ── Test 6: backfill_decisions — Related: ────────────────────────


@pytest.mark.asyncio
async def test_backfill_decisions_parses_related_lines(tmp_path, edge_store):
    md = tmp_path / "decisions.md"
    md.write_text(
        "# Header\n\n"
        "### AD-688 v1: Oracle Graph Integration (2026-05-04)\n\n"
        "Some prose.\n\n"
        "**Related:** AD-686 (Tier 5), AD-687 (Edge Store), BF-100 (noise)\n\n"
        "More prose.\n\n"
        "### AD-687 v1: Knowledge Edge Store (2026-05-04)\n\n"
        "**Related:** AD-688\n",
        encoding="utf-8",
    )
    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=None,
        hebbian_router=None,
        episodic_memory=None,
        decisions_paths=[md],
    )
    n = await svc.backfill_decisions()
    assert n == 3
    edges = await edge_store.find_edges(
        relation=KnowledgeRelationType.INFORMED_BY, limit=100,
    )
    pairs = sorted((e.source_id, e.target_id) for e in edges)
    assert pairs == [("AD-687", "AD-688"), ("AD-688", "AD-686"), ("AD-688", "AD-687")]


# ── Test 7: backfill_decisions — Closes #N ───────────────────────


@pytest.mark.asyncio
async def test_backfill_decisions_parses_closes_markers(tmp_path, edge_store):
    md = tmp_path / "decisions.md"
    md.write_text(
        "### AD-688 v1: Oracle Graph (2026-05-04)\n\n"
        "Some prose. Closes GH issue #382.\n\n"
        "### AD-689 v1: Edge Population (2026-05-04)\n\n"
        "Closes #383.\n",
        encoding="utf-8",
    )
    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=None,
        hebbian_router=None,
        episodic_memory=None,
        decisions_paths=[md],
    )
    n = await svc.backfill_decisions()
    assert n == 2
    edges = await edge_store.find_edges(
        relation=KnowledgeRelationType.RESOLVED_BY, limit=100,
    )
    pairs = sorted((e.source_id, e.target_id) for e in edges)
    assert pairs == [("AD-688", "gh-382"), ("AD-689", "gh-383")]


# ── Test 8: backfill_all aggregates ──────────────────────────────


@pytest.mark.asyncio
async def test_backfill_all_aggregates_counts(tmp_path, edge_store):
    md = tmp_path / "d.md"
    md.write_text(
        "### AD-1 v1: x\n\n**Related:** AD-2\n\n### AD-2 v1: y\n\nCloses #99\n",
        encoding="utf-8",
    )
    captain = SimpleNamespace(id="captain", department_id="bridge", reports_to=None)
    eng = SimpleNamespace(id="eng", department_id="engineering", reports_to="captain")
    a1 = SimpleNamespace(agent_type="captain", post_id="captain")
    a2 = SimpleNamespace(agent_type="engineer", post_id="eng")
    ont = _stub_ontology(assignments=[a1, a2], posts=[captain, eng])

    router = MagicMock()
    router.all_weights_typed.return_value = {("intent.a", "engineer", REL_INTENT): 0.8}

    em = MagicMock()
    em.list_episodes = AsyncMock(return_value=[
        Episode(id="ep-1", timestamp=1.0, user_input="q", agent_ids=["captain"])
    ])

    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=ont,
        hebbian_router=router,
        episodic_memory=em,
        decisions_paths=[md],
    )
    res = await svc.backfill_all()
    assert res.ontology == 3
    assert res.hebbian == 1
    assert res.episodes == 1
    assert res.decisions == 2
    assert res.total == 7
    assert res.duration_ms >= 0.0


# ── Test 9: idempotency ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_backfill_all_is_idempotent(tmp_path, edge_store):
    md = tmp_path / "d.md"
    md.write_text("### AD-1 v1: x\n\n**Related:** AD-2\n", encoding="utf-8")
    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=None,
        hebbian_router=None,
        episodic_memory=None,
        decisions_paths=[md],
    )
    res1 = await svc.backfill_all()
    edges_after_first = await edge_store.find_edges(limit=1000)
    res2 = await svc.backfill_all()
    edges_after_second = await edge_store.find_edges(limit=1000)
    assert res1.total == res2.total == 1
    assert len(edges_after_first) == len(edges_after_second) == 1
    assert edges_after_first[0].id == edges_after_second[0].id
    expected = _deterministic_edge_id(
        KnowledgeEntityType.DECISION, "AD-1",
        KnowledgeRelationType.INFORMED_BY,
        KnowledgeEntityType.DECISION, "AD-2",
    )
    assert edges_after_first[0].id == expected


# ── Test 10: warm-boot wirer skips on populated store ────────────


@pytest.mark.asyncio
async def test_wirer_skips_when_rows_exist(edge_store):
    pre = KnowledgeEdge(
        source_type=KnowledgeEntityType.AGENT,
        source_id="x",
        relation=KnowledgeRelationType.MEMBER_OF,
        target_type=KnowledgeEntityType.DEPARTMENT,
        target_id="y",
    )
    await edge_store.add_edge(pre)
    from probos.config import EdgeBackfillConfig
    from probos.startup.finalize import _wire_edge_backfill

    cfg = EdgeBackfillConfig(
        enabled=True, run_on_warm_boot=True, force=False, decisions_paths=[],
    )
    sys_cfg = SimpleNamespace(edge_backfill=cfg)
    rt = SimpleNamespace(
        knowledge_edges=edge_store,
        ontology=None,
        hebbian_router=None,
        episodic_memory=None,
        edge_backfill=None,
    )
    ok = await _wire_edge_backfill(runtime=rt, config=sys_cfg)
    assert ok is True
    assert rt.edge_backfill is not None
    edges = await edge_store.find_edges(limit=100)
    assert len(edges) == 1


# ── Test 11: warm-boot wirer runs on empty store ─────────────────


@pytest.mark.asyncio
async def test_wirer_runs_when_empty(edge_store):
    captain = SimpleNamespace(id="captain", department_id="bridge", reports_to=None)
    a = SimpleNamespace(agent_type="captain", post_id="captain")
    ont = _stub_ontology(assignments=[a], posts=[captain])
    from probos.config import EdgeBackfillConfig
    from probos.startup.finalize import _wire_edge_backfill

    cfg = EdgeBackfillConfig(
        enabled=True, run_on_warm_boot=True, force=False, decisions_paths=[],
    )
    sys_cfg = SimpleNamespace(edge_backfill=cfg)
    rt = SimpleNamespace(
        knowledge_edges=edge_store,
        ontology=ont,
        hebbian_router=None,
        episodic_memory=None,
        edge_backfill=None,
    )
    ok = await _wire_edge_backfill(runtime=rt, config=sys_cfg)
    assert ok is True
    edges = await edge_store.find_edges(limit=100)
    assert len(edges) == 1
    assert edges[0].relation == KnowledgeRelationType.MEMBER_OF


# ── Test 12: force=True overrides skip ───────────────────────────


@pytest.mark.asyncio
async def test_wirer_force_overrides_populated_skip(edge_store):
    pre = KnowledgeEdge(
        source_type=KnowledgeEntityType.AGENT,
        source_id="x",
        relation=KnowledgeRelationType.MEMBER_OF,
        target_type=KnowledgeEntityType.DEPARTMENT,
        target_id="y",
    )
    await edge_store.add_edge(pre)
    captain = SimpleNamespace(id="captain", department_id="bridge", reports_to=None)
    a = SimpleNamespace(agent_type="captain", post_id="captain")
    ont = _stub_ontology(assignments=[a], posts=[captain])
    from probos.config import EdgeBackfillConfig
    from probos.startup.finalize import _wire_edge_backfill

    cfg = EdgeBackfillConfig(
        enabled=True, run_on_warm_boot=True, force=True, decisions_paths=[],
    )
    sys_cfg = SimpleNamespace(edge_backfill=cfg)
    rt = SimpleNamespace(
        knowledge_edges=edge_store,
        ontology=ont,
        hebbian_router=None,
        episodic_memory=None,
        edge_backfill=None,
    )
    ok = await _wire_edge_backfill(runtime=rt, config=sys_cfg)
    assert ok is True
    edges = await edge_store.find_edges(limit=100)
    assert len(edges) == 2
