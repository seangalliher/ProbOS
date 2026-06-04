"""AD-594c v1: Parallel execution dispatch tests."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from probos.config import ConsultationDispatchConfig, SystemConfig
from probos.consultation import (
    ConflictDetector,
    ConflictPair,
    DispatchReceipt,
    MarkdownPlanDecomposer,
    ParallelDispatcher,
    ProgressSnapshot,
    WorkItemSpec,
    WorkspaceLifecycleState,
    WorkspaceRegistry,
)
from probos.events import EventType
from probos.knowledge.records_store import RecordsStore
from probos.startup.finalize import _wire_consultation_dispatch
from probos.workforce import WorkItemStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_records_store(tmp_path: Path) -> RecordsStore:
    cfg = SimpleNamespace(repo_path=str(tmp_path / "records"), auto_commit=False)
    return RecordsStore(cfg)


@pytest_asyncio.fixture
async def records(tmp_path: Path) -> RecordsStore:
    rs = _make_records_store(tmp_path)
    await rs.initialize()
    return rs


@pytest.fixture
def clock():
    state = {"t": 1700000000.0}

    def _tick() -> float:
        state["t"] += 1.0
        return state["t"]

    return _tick


@pytest_asyncio.fixture
async def registry(records: RecordsStore, clock) -> WorkspaceRegistry:
    return WorkspaceRegistry(records, clock=clock)


@pytest_asyncio.fixture
async def workspace(registry: WorkspaceRegistry):
    ws = await registry.create(
        title="Wave-80 dispatch test",
        owner_agent_id="captain",
        participants=["captain"],
    )
    # Move APPROVED so dispatch's transition_to(EXECUTING) is valid.
    # Lifecycle: INITIATED -> CONSULTING -> PLAN_REVIEW -> APPROVED -> EXECUTING.
    for state in (
        WorkspaceLifecycleState.CONSULTING,
        WorkspaceLifecycleState.PLAN_REVIEW,
        WorkspaceLifecycleState.APPROVED,
    ):
        await ws.transition_to(state, agent_id="captain")
    return ws


@pytest_asyncio.fixture
async def store(tmp_path: Path):
    s = WorkItemStore(db_path=str(tmp_path / "wis.db"))
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


@pytest.fixture
def dispatch_config():
    return ConsultationDispatchConfig()


@pytest_asyncio.fixture
async def dispatcher(
    registry: WorkspaceRegistry,
    store: WorkItemStore,
    records: RecordsStore,
    dispatch_config: ConsultationDispatchConfig,
    clock,
):
    events: list[tuple[EventType, dict]] = []

    def _emit(et, payload):
        events.append((et, payload))

    d = ParallelDispatcher(
        workspace_registry=registry,
        work_item_store=store,
        records_store=records,
        config=dispatch_config,
        emit_event=_emit,
        clock=clock,
    )
    d._test_events = events  # type: ignore[attr-defined]
    return d


async def _make_plan(workspace, body: str) -> int:
    """Write next plan_v{N}.md via add_plan_iteration; return its version."""
    path = await workspace.add_plan_iteration(body, agent_id="captain")
    # path ends in plan_v{N}.md
    version = int(path.split("plan_v")[-1].split(".md")[0])
    return version


# ---------------------------------------------------------------------------
# Module-level (5)
# ---------------------------------------------------------------------------


def test_event_types_present_and_collision_free():
    assert EventType.PARALLEL_DISPATCH_STARTED.value == "parallel_dispatch_started"
    assert EventType.PARALLEL_DISPATCH_PROGRESS.value == "parallel_dispatch_progress"
    assert EventType.PARALLEL_DISPATCH_BLOCKED.value == "parallel_dispatch_blocked"


def test_consultation_dispatch_config_defaults():
    c = ConsultationDispatchConfig()
    assert c.enabled is True
    assert c.default_work_type == "duty"
    assert c.default_tags == ["consultation"]
    assert c.blocker_threshold_seconds == 600.0
    assert c.progress_subscription_enabled is True
    # SystemConfig wires the field
    sc = SystemConfig()
    assert isinstance(sc.consultation_dispatch, ConsultationDispatchConfig)


def test_workitem_spec_to_dict_roundtrip():
    s = WorkItemSpec(
        spec_id="a", title="A", description="d", work_type="duty",
        agent="agent-1", priority=2, depends_on=("x",), resources=("r1", "r2"),
        metadata={"k": "v"},
    )
    d = s.to_dict()
    assert d == {
        "spec_id": "a", "title": "A", "description": "d", "work_type": "duty",
        "agent": "agent-1", "priority": 2, "depends_on": ["x"],
        "resources": ["r1", "r2"], "metadata": {"k": "v"},
        "expected_output": None,
        "capability": None, "department": None,
    }
    # Mutate the dict; original tuples preserved
    d["depends_on"].append("mut")
    assert s.depends_on == ("x",)


def test_conflict_pair_to_dict():
    cp = ConflictPair(a_spec_id="a", b_spec_id="b", shared_resources=("r",))
    d = cp.to_dict()
    assert d == {"a_spec_id": "a", "b_spec_id": "b", "shared_resources": ["r"]}


def test_dispatch_receipt_to_dict_deep_copies():
    cp = ConflictPair("a", "b", ("r",))
    r = DispatchReceipt(
        workspace_id="w", plan_version=1,
        dispatched_spec_ids=("a", "b"), work_item_ids=("wid-a", "wid-b"),
        spec_id_to_work_item_id={"a": "wid-a", "b": "wid-b"},
        serialization_edges_added=(cp,), conflicts=(cp,),
        started_at=1.0,
    )
    d = r.to_dict()
    d["dispatched_spec_ids"].append("mut")
    d["spec_id_to_work_item_id"]["c"] = "wid-c"
    assert r.dispatched_spec_ids == ("a", "b")
    assert r.spec_id_to_work_item_id == {"a": "wid-a", "b": "wid-b"}


# ---------------------------------------------------------------------------
# MarkdownPlanDecomposer (5)
# ---------------------------------------------------------------------------


def test_decomposer_empty_text_returns_empty_list():
    assert MarkdownPlanDecomposer().decompose("") == []


def test_decomposer_single_task_with_all_keys():
    body = (
        "## Build Foo\n"
        "- id: build-foo\n"
        "- description: builds the foo subsystem\n"
        "- work_type: duty\n"
        "- agent: engineering\n"
        "- priority: 2\n"
        "- depends_on: [a, b]\n"
        "- resources: [src/foo.py, src/bar.py]\n"
    )
    specs = MarkdownPlanDecomposer().decompose(body)
    assert len(specs) == 1
    s = specs[0]
    assert s.spec_id == "build-foo"
    assert s.title == "Build Foo"
    assert s.description == "builds the foo subsystem"
    assert s.work_type == "duty"
    assert s.agent == "engineering"
    assert s.priority == 2
    assert s.depends_on == ("a", "b")
    assert s.resources == ("src/foo.py", "src/bar.py")
    assert s.metadata == {}


def test_decomposer_id_fallback_to_slug_when_missing():
    specs = MarkdownPlanDecomposer().decompose("## Build Foo Bar\n")
    assert len(specs) == 1
    assert specs[0].spec_id == "build-foo-bar"


def test_decomposer_unknown_keys_routed_to_metadata():
    body = (
        "## Task A\n"
        "- id: a\n"
        "- some_extra: hello\n"
        "- another_one: world\n"
    )
    specs = MarkdownPlanDecomposer().decompose(body)
    assert len(specs) == 1
    assert specs[0].metadata == {"some_extra": "hello", "another_one": "world"}


def test_decomposer_multiple_tasks_preserve_order():
    body = "## First\n- id: f\n## Second\n- id: s\n## Third\n- id: t\n"
    specs = MarkdownPlanDecomposer().decompose(body)
    assert [s.spec_id for s in specs] == ["f", "s", "t"]


# ---------------------------------------------------------------------------
# ConflictDetector (3)
# ---------------------------------------------------------------------------


def test_detector_no_resources_returns_empty():
    specs = [
        WorkItemSpec(spec_id="a", title="A"),
        WorkItemSpec(spec_id="b", title="B"),
    ]
    assert ConflictDetector().detect(specs) == []


def test_detector_overlap_emits_pair_with_sorted_shared():
    specs = [
        WorkItemSpec(spec_id="a", title="A", resources=("z", "x")),
        WorkItemSpec(spec_id="b", title="B", resources=("x", "z")),
    ]
    pairs = ConflictDetector().detect(specs)
    assert len(pairs) == 1
    p = pairs[0]
    assert p.a_spec_id == "a"
    assert p.b_spec_id == "b"
    assert p.shared_resources == ("x", "z")  # sorted


def test_detector_three_specs_three_pairwise_overlaps():
    specs = [
        WorkItemSpec(spec_id="a", title="A", resources=("r",)),
        WorkItemSpec(spec_id="b", title="B", resources=("r",)),
        WorkItemSpec(spec_id="c", title="C", resources=("r",)),
    ]
    pairs = ConflictDetector().detect(specs)
    assert len(pairs) == 3
    ids = {(p.a_spec_id, p.b_spec_id) for p in pairs}
    assert ids == {("a", "b"), ("a", "c"), ("b", "c")}


# ---------------------------------------------------------------------------
# Conflict serialization (2)
# ---------------------------------------------------------------------------


def test_serialize_conflicts_injects_depends_on_in_original_order():
    specs = [
        WorkItemSpec(spec_id="a", title="A", resources=("r",)),
        WorkItemSpec(spec_id="b", title="B", resources=("r",)),
    ]
    # Pair given in reversed order — serializer must still anchor on
    # original spec list order (a precedes b).
    conflicts = [ConflictPair(a_spec_id="b", b_spec_id="a", shared_resources=("r",))]
    rewritten, edges = ParallelDispatcher._serialize_conflicts(specs, conflicts)
    assert len(rewritten) == 2
    assert rewritten[0].depends_on == ()
    assert rewritten[1].depends_on == ("a",)
    assert len(edges) == 1
    assert edges[0].a_spec_id == "a" and edges[0].b_spec_id == "b"


def test_serialize_conflicts_no_duplicate_when_dep_already_exists():
    specs = [
        WorkItemSpec(spec_id="a", title="A", resources=("r",)),
        WorkItemSpec(spec_id="b", title="B", resources=("r",), depends_on=("a",)),
    ]
    conflicts = [ConflictPair("a", "b", ("r",))]
    rewritten, edges = ParallelDispatcher._serialize_conflicts(specs, conflicts)
    # depends_on unchanged; no duplicate edge
    assert rewritten[1].depends_on == ("a",)
    assert edges == []


# ---------------------------------------------------------------------------
# Dispatcher core (8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_unknown_workspace_raises_value_error(dispatcher):
    with pytest.raises(ValueError, match="unknown workspace"):
        await dispatcher.dispatch("does-not-exist")


@pytest.mark.asyncio
async def test_dispatch_no_plan_files_raises_value_error(dispatcher, workspace):
    with pytest.raises(ValueError, match="no plan files"):
        await dispatcher.dispatch(workspace.id)


@pytest.mark.asyncio
async def test_dispatch_zero_specs_raises_value_error(dispatcher, workspace):
    await _make_plan(workspace, "# preamble\n")
    with pytest.raises(ValueError, match="zero specs"):
        await dispatcher.dispatch(workspace.id)


@pytest.mark.asyncio
async def test_dispatch_happy_path_creates_workitems_and_mirrors(
    dispatcher, workspace, store, records,
):
    await _make_plan(
        workspace,
        "## Task A\n- id: a\n## Task B\n- id: b\n## Task C\n- id: c\n",
    )
    receipt = await dispatcher.dispatch(workspace.id)
    assert receipt.plan_version == 1
    assert len(receipt.work_item_ids) == 3
    items = await store.list_work_items(tags=[f"workspace:{workspace.id}"], limit=100)
    assert len(items) == 3
    # Workspace state EXECUTING
    ws_after = await dispatcher._registry.get(workspace.id)
    assert ws_after.lifecycle_state == WorkspaceLifecycleState.EXECUTING
    # Mirror yaml files written into workitems/
    wi_dir = records.repo_path / "consultations" / workspace.id / "workitems"
    yaml_count = sum(1 for p in wi_dir.iterdir() if p.suffix == ".yaml")
    assert yaml_count == 3
    # PARALLEL_DISPATCH_STARTED emitted once with work_item_count=3
    started = [
        p for et, p in dispatcher._test_events  # type: ignore[attr-defined]
        if et == EventType.PARALLEL_DISPATCH_STARTED
    ]
    assert len(started) == 1
    assert started[0]["work_item_count"] == 3


@pytest.mark.asyncio
async def test_dispatch_translates_spec_depends_on_to_work_item_ids(
    dispatcher, workspace, store,
):
    await _make_plan(
        workspace,
        "## Task A\n- id: a\n## Task B\n- id: b\n- depends_on: [a]\n",
    )
    receipt = await dispatcher.dispatch(workspace.id)
    wid_a = receipt.spec_id_to_work_item_id["a"]
    wid_b = receipt.spec_id_to_work_item_id["b"]
    item_b = await store.get_work_item(wid_b)
    assert item_b is not None
    assert wid_a in item_b.depends_on
    assert "a" not in item_b.depends_on  # spec_id should NOT leak through


@pytest.mark.asyncio
async def test_dispatch_with_conflict_serializes_via_synthetic_edge(
    dispatcher, workspace, store,
):
    await _make_plan(
        workspace,
        "## Task A\n- id: a\n- resources: [src/foo.py]\n"
        "## Task B\n- id: b\n- resources: [src/foo.py]\n",
    )
    receipt = await dispatcher.dispatch(workspace.id)
    assert len(receipt.conflicts) == 1
    assert len(receipt.serialization_edges_added) == 1
    wid_a = receipt.spec_id_to_work_item_id["a"]
    wid_b = receipt.spec_id_to_work_item_id["b"]
    item_b = await store.get_work_item(wid_b)
    assert item_b is not None
    assert wid_a in item_b.depends_on


@pytest.mark.asyncio
async def test_dispatch_uses_explicit_plan_version_when_passed(
    dispatcher, workspace,
):
    await _make_plan(workspace, "## v1\n- id: v1\n")
    await _make_plan(workspace, "## v2\n- id: v2\n")
    receipt = await dispatcher.dispatch(workspace.id, plan_version=1)
    assert receipt.plan_version == 1
    assert receipt.spec_id_to_work_item_id.keys() == {"v1"}


@pytest.mark.asyncio
async def test_dispatch_explicit_plan_version_unknown_raises_value_error(
    dispatcher, workspace,
):
    await _make_plan(workspace, "## v1\n- id: v1\n")
    with pytest.raises(ValueError, match="plan_v99.md not found"):
        await dispatcher.dispatch(workspace.id, plan_version=99)


# ---------------------------------------------------------------------------
# Progress (3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_progress_returns_zero_for_unknown_workspace(dispatcher):
    snap = await dispatcher.get_progress("nope")
    assert isinstance(snap, ProgressSnapshot)
    assert snap.total == 0
    assert snap.by_status == {}


@pytest.mark.asyncio
async def test_get_progress_aggregates_by_status(dispatcher, workspace, store):
    await _make_plan(
        workspace,
        "## A\n- id: a\n## B\n- id: b\n## C\n- id: c\n",
    )
    receipt = await dispatcher.dispatch(workspace.id)
    wid_a = receipt.spec_id_to_work_item_id["a"]
    wid_b = receipt.spec_id_to_work_item_id["b"]
    await store.update_work_item(wid_a, status="completed")
    await store.update_work_item(wid_b, status="in_progress")
    snap = await dispatcher.get_progress(workspace.id)
    assert snap.total == 3
    assert snap.completed == 1
    assert snap.in_progress == 1
    assert snap.open == 1
    assert snap.by_status.get("completed") == 1
    assert snap.by_status.get("in_progress") == 1


@pytest.mark.asyncio
async def test_get_progress_emits_event_when_subscription_enabled(
    dispatcher, workspace,
):
    await _make_plan(workspace, "## A\n- id: a\n")
    await dispatcher.dispatch(workspace.id)
    # Reset event log to isolate get_progress emission.
    dispatcher._test_events.clear()  # type: ignore[attr-defined]
    await dispatcher.get_progress(workspace.id)
    progress_events = [
        p for et, p in dispatcher._test_events  # type: ignore[attr-defined]
        if et == EventType.PARALLEL_DISPATCH_PROGRESS
    ]
    assert len(progress_events) == 1

    # Disable subscription -> no progress event.
    dispatcher._config.progress_subscription_enabled = False
    dispatcher._test_events.clear()  # type: ignore[attr-defined]
    await dispatcher.get_progress(workspace.id)
    progress_events = [
        p for et, p in dispatcher._test_events  # type: ignore[attr-defined]
        if et == EventType.PARALLEL_DISPATCH_PROGRESS
    ]
    assert progress_events == []


# ---------------------------------------------------------------------------
# Completion (3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_completion_returns_false_when_some_items_open(
    dispatcher, workspace, store,
):
    await _make_plan(workspace, "## A\n- id: a\n## B\n- id: b\n")
    receipt = await dispatcher.dispatch(workspace.id)
    await store.update_work_item(receipt.spec_id_to_work_item_id["a"], status="completed")
    assert await dispatcher.check_completion(workspace.id) is False


@pytest.mark.asyncio
async def test_check_completion_transitions_to_completed_and_journals_when_all_terminal(
    dispatcher, workspace, store, records,
):
    await _make_plan(workspace, "## A\n- id: a\n## B\n- id: b\n")
    receipt = await dispatcher.dispatch(workspace.id)
    for wid in receipt.work_item_ids:
        await store.update_work_item(wid, status="completed")
    assert await dispatcher.check_completion(workspace.id) is True
    ws_after = await dispatcher._registry.get(workspace.id)
    assert ws_after.lifecycle_state == WorkspaceLifecycleState.COMPLETED
    journal = await records.read_workspace_file(
        f"consultations/{workspace.id}/journal.md"
    )
    assert journal is not None
    assert "dispatch completed" in journal


@pytest.mark.asyncio
async def test_check_completion_idempotent(dispatcher, workspace, store):
    await _make_plan(workspace, "## A\n- id: a\n")
    receipt = await dispatcher.dispatch(workspace.id)
    await store.update_work_item(receipt.work_item_ids[0], status="completed")
    assert await dispatcher.check_completion(workspace.id) is True
    # Second call: workspace already COMPLETED, returns False without retransition.
    assert await dispatcher.check_completion(workspace.id) is False


# ---------------------------------------------------------------------------
# Blockers (3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_blockers_below_threshold_returns_empty(
    dispatcher, workspace,
):
    await _make_plan(
        workspace,
        "## A\n- id: a\n## B\n- id: b\n- depends_on: [a]\n",
    )
    receipt = await dispatcher.dispatch(workspace.id)
    # `now` < started_at + threshold (default 600s) -> empty
    reports = await dispatcher.detect_blockers(workspace.id, now=receipt.started_at + 1.0)
    assert reports == []


@pytest.mark.asyncio
async def test_detect_blockers_emits_blocked_event_with_dedup(
    dispatcher, workspace, store,
):
    await _make_plan(
        workspace,
        "## A\n- id: a\n## B\n- id: b\n- depends_on: [a]\n",
    )
    receipt = await dispatcher.dispatch(workspace.id)
    future = receipt.started_at + 700.0
    reports1 = await dispatcher.detect_blockers(workspace.id, now=future)
    assert len(reports1) == 1
    assert reports1[0].spec_id == "b"
    assert "a" in reports1[0].unmet_dependencies
    blocked_events1 = [
        p for et, p in dispatcher._test_events  # type: ignore[attr-defined]
        if et == EventType.PARALLEL_DISPATCH_BLOCKED
    ]
    assert len(blocked_events1) == 1
    # Second call with same state must NOT re-emit (dedup ring).
    reports2 = await dispatcher.detect_blockers(workspace.id, now=future + 1.0)
    assert len(reports2) == 1
    blocked_events2 = [
        p for et, p in dispatcher._test_events  # type: ignore[attr-defined]
        if et == EventType.PARALLEL_DISPATCH_BLOCKED
    ]
    assert len(blocked_events2) == 1  # unchanged


@pytest.mark.asyncio
async def test_detect_blockers_clears_when_dependency_completes(
    dispatcher, workspace, store,
):
    await _make_plan(
        workspace,
        "## A\n- id: a\n## B\n- id: b\n- depends_on: [a]\n",
    )
    receipt = await dispatcher.dispatch(workspace.id)
    future = receipt.started_at + 700.0
    # Mark A complete -> B's dependency is satisfied.
    await store.update_work_item(receipt.spec_id_to_work_item_id["a"], status="completed")
    reports = await dispatcher.detect_blockers(workspace.id, now=future)
    assert reports == []


# ---------------------------------------------------------------------------
# Wirer (4)
# ---------------------------------------------------------------------------


def test_wirer_constructs_dispatcher_when_dependencies_present():
    cfg = SystemConfig()
    runtime = SimpleNamespace(
        consultation_workspaces=MagicMock(),
        work_item_store=MagicMock(),
        records_store=MagicMock(),
        emit_event=lambda *a, **k: None,
    )
    ok = _wire_consultation_dispatch(runtime=runtime, config=cfg)
    assert ok is True
    assert isinstance(runtime.consultation_dispatcher, ParallelDispatcher)


def test_wirer_skips_when_disabled_config():
    cfg = SystemConfig()
    cfg.consultation_dispatch.enabled = False
    runtime = SimpleNamespace(
        consultation_workspaces=MagicMock(),
        work_item_store=MagicMock(),
        records_store=MagicMock(),
    )
    ok = _wire_consultation_dispatch(runtime=runtime, config=cfg)
    assert ok is False
    assert not hasattr(runtime, "consultation_dispatcher")


def test_wirer_skips_when_work_item_store_missing(caplog):
    cfg = SystemConfig()
    runtime = SimpleNamespace(
        consultation_workspaces=MagicMock(),
        work_item_store=None,
        records_store=MagicMock(),
    )
    with caplog.at_level("INFO"):
        ok = _wire_consultation_dispatch(runtime=runtime, config=cfg)
    assert ok is False
    assert not hasattr(runtime, "consultation_dispatcher")
    assert any("work_item_store unavailable" in r.message for r in caplog.records)


def test_wirer_skips_when_records_store_missing(caplog):
    cfg = SystemConfig()
    runtime = SimpleNamespace(
        consultation_workspaces=MagicMock(),
        work_item_store=MagicMock(),
        records_store=None,
    )
    with caplog.at_level("INFO"):
        ok = _wire_consultation_dispatch(runtime=runtime, config=cfg)
    assert ok is False
    assert not hasattr(runtime, "consultation_dispatcher")
    assert any("records_store unavailable" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Revoke (1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_cancels_non_terminal_work_items_only(
    dispatcher, workspace, store,
):
    await _make_plan(
        workspace, "## A\n- id: a\n## B\n- id: b\n## C\n- id: c\n",
    )
    receipt = await dispatcher.dispatch(workspace.id)
    # Mark one terminal so revoke skips it.
    await store.update_work_item(
        receipt.spec_id_to_work_item_id["a"], status="completed",
    )
    cancelled = await dispatcher.revoke(workspace.id)
    assert cancelled == 2
    # b and c are now cancelled.
    item_b = await store.get_work_item(receipt.spec_id_to_work_item_id["b"])
    item_c = await store.get_work_item(receipt.spec_id_to_work_item_id["c"])
    assert item_b is not None and item_b.status == "cancelled"
    assert item_c is not None and item_c.status == "cancelled"
