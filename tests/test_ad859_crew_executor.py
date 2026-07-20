"""AD-859: tests for :class:`CrewTaskExecutor`.

Uses a REAL :class:`WorkItemStore` (not a MagicMock — BF-287 phantom-attribute
trap) plus a FAKE :class:`WorkItemAgenticExecutor` that records its calls,
tracks concurrency, and can be told to "fail" specific children.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome
from probos.cognitive.crew_executor import CrewTaskExecutor, SubtaskResult
from probos.events import EventType
from probos.workforce import WorkItemStore


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeAgent:
    id: str
    instructions: str = "do the thing"
    department: str = "engineering"
    rank: str = "ensign"


class _FakeRegistry:
    """Duck-typed AgentRegistry: only ``get`` is exercised by the executor."""

    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._agents = agents

    def get(self, agent_id: str | None) -> _FakeAgent | None:
        if agent_id is None:
            return None
        return self._agents.get(agent_id)


@dataclass
class _Call:
    agent_id: str
    task_text: str
    started_at: float
    finished_at: float


class _FakeAgenticExecutor:
    """Records every ``run`` call, tracks concurrency, can fail by agent id."""

    def __init__(
        self,
        *,
        fail_agents: set[str] | None = None,
        delay: float = 0.0,
        trace_ref: str | None = "d" * 64,
    ) -> None:
        self._fail_agents = fail_agents or set()
        self._delay = delay
        self._trace_ref = trace_ref
        self.calls: list[_Call] = []
        self.active = 0
        self.max_active = 0

    async def run(
        self,
        *,
        agent_id: str,
        instructions: str,
        task_text: str,
        runtime: Any,
        department: str = "",
        rank: str = "ensign",
        thread_id: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> WorkItemAgenticOutcome:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        started = time.time()
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            else:
                await asyncio.sleep(0)
        finally:
            self.active -= 1
        self.calls.append(
            _Call(
                agent_id=agent_id,
                task_text=task_text,
                started_at=started,
                finished_at=time.time(),
            )
        )
        if agent_id in self._fail_agents:
            return WorkItemAgenticOutcome(
                final_text="partial",
                stopped_reason="error",
                tool_trace_ref=None,
            )
        return WorkItemAgenticOutcome(
            final_text=f"done: {task_text}",
            stopped_reason="complete",
            tool_trace_ref=self._trace_ref,
        )


@dataclass
class _EventSink:
    events: list[tuple[EventType, dict[str, Any]]] = field(default_factory=list)

    def __call__(self, event_type: EventType, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


@pytest.fixture
async def store(tmp_path):
    s = WorkItemStore(
        db_path=str(tmp_path / "crew.db"),
        emit_event=MagicMock(),
        tick_interval=1000,
    )
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


async def _make_child(
    store: WorkItemStore,
    *,
    parent_id: str,
    title: str,
    assigned_to: str,
    spec_id: str,
    depends_on: list[str] | None = None,
):
    return await store.create_work_item(
        title=title,
        description=f"please do {title}",
        work_type="task",
        parent_id=parent_id,
        assigned_to=assigned_to,
        depends_on=depends_on or [],
        metadata={"spec_id": spec_id},
    )


def _make_executor(
    store: WorkItemStore,
    registry: _FakeRegistry,
    agentic: _FakeAgenticExecutor,
    *,
    max_parallel: int = 3,
    emit_fn: Any = None,
) -> CrewTaskExecutor:
    return CrewTaskExecutor(
        work_item_store=store,
        agent_registry=registry,
        agentic_executor=agentic,  # type: ignore[arg-type]
        runtime=object(),
        max_parallel_subtasks=max_parallel,
        emit_fn=emit_fn,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_independent_children_all_run_and_complete(store):
    parent = await store.create_work_item(title="parent", work_type="work_order")
    registry = _FakeRegistry({"a1": _FakeAgent("a1"), "a2": _FakeAgent("a2")})
    agentic = _FakeAgenticExecutor()
    await _make_child(store, parent_id=parent.id, title="c1", assigned_to="a1", spec_id="s1")
    await _make_child(store, parent_id=parent.id, title="c2", assigned_to="a2", spec_id="s2")

    executor = _make_executor(store, registry, agentic)
    results = await executor.run(parent.id)

    assert len(results) == 2
    assert all(isinstance(r, SubtaskResult) for r in results)
    assert {r.status for r in results} == {"done"}
    assert {r.spec_id for r in results} == {"s1", "s2"}


@pytest.mark.asyncio
async def test_child_waits_for_depends_on_to_complete_first(store):
    parent = await store.create_work_item(title="parent", work_type="work_order")
    registry = _FakeRegistry({"a1": _FakeAgent("a1"), "a2": _FakeAgent("a2")})
    agentic = _FakeAgenticExecutor(delay=0.05)
    a = await _make_child(store, parent_id=parent.id, title="A", assigned_to="a1", spec_id="sA")
    await _make_child(
        store, parent_id=parent.id, title="B", assigned_to="a2", spec_id="sB",
        depends_on=[a.id],
    )

    executor = _make_executor(store, registry, agentic)
    results = await executor.run(parent.id)

    assert len(results) == 2
    # B (agent a2) must not start until A (agent a1) has finished.
    call_a = next(c for c in agentic.calls if c.agent_id == "a1")
    call_b = next(c for c in agentic.calls if c.agent_id == "a2")
    assert call_b.started_at >= call_a.finished_at


@pytest.mark.asyncio
async def test_subtask_result_carries_persistent_agent_id_and_trace_ref(store):
    parent = await store.create_work_item(title="parent", work_type="work_order")
    registry = _FakeRegistry({"persistent-agent": _FakeAgent("persistent-agent")})
    agentic = _FakeAgenticExecutor(trace_ref="c" * 64)
    await _make_child(
        store, parent_id=parent.id, title="c1",
        assigned_to="persistent-agent", spec_id="s1",
    )

    executor = _make_executor(store, registry, agentic)
    results = await executor.run(parent.id)

    assert len(results) == 1
    r = results[0]
    assert r.agent_id == "persistent-agent"  # durable provenance
    assert r.tool_trace_ref == "c" * 64  # a ref...
    assert isinstance(r.tool_trace_ref, str)  # ...not inline bytes
    assert r.output == "done: please do c1"


@pytest.mark.asyncio
async def test_failed_child_surfaces_status_without_unblocking_dependents(store):
    parent = await store.create_work_item(title="parent", work_type="work_order")
    registry = _FakeRegistry(
        {"fail": _FakeAgent("fail"), "dep": _FakeAgent("dep"), "sib": _FakeAgent("sib")}
    )
    agentic = _FakeAgenticExecutor(fail_agents={"fail"})
    a = await _make_child(store, parent_id=parent.id, title="A", assigned_to="fail", spec_id="sA")
    await _make_child(
        store, parent_id=parent.id, title="B", assigned_to="dep", spec_id="sB",
        depends_on=[a.id],
    )
    await _make_child(store, parent_id=parent.id, title="C", assigned_to="sib", spec_id="sC")

    executor = _make_executor(store, registry, agentic)
    results = await executor.run(parent.id)

    by_spec = {r.spec_id: r for r in results}
    # A failed; dependent B is durably blocked; sibling C still ran.
    assert by_spec["sA"].status != "done"
    assert by_spec["sB"].status == "blocked"
    assert by_spec["sC"].status == "done"
    # The failed child was NOT silently marked done in the store.
    stored_a = await store.get_work_item(a.id)
    assert stored_a is not None
    assert stored_a.status != "done"


@pytest.mark.asyncio
async def test_concurrency_cap_respected(store):
    parent = await store.create_work_item(title="parent", work_type="work_order")
    registry = _FakeRegistry({f"a{i}": _FakeAgent(f"a{i}") for i in range(5)})
    agentic = _FakeAgenticExecutor(delay=0.03)
    for i in range(5):
        await _make_child(
            store, parent_id=parent.id, title=f"c{i}",
            assigned_to=f"a{i}", spec_id=f"s{i}",
        )

    executor = _make_executor(store, registry, agentic, max_parallel=2)
    results = await executor.run(parent.id)

    assert len(results) == 5
    assert agentic.max_active <= 2  # cap honored
    assert agentic.max_active == 2  # cap actually reached (real parallelism)


@pytest.mark.asyncio
async def test_lifecycle_events_emitted(store):
    parent = await store.create_work_item(title="parent", work_type="work_order")
    registry = _FakeRegistry({"a1": _FakeAgent("a1"), "a2": _FakeAgent("a2")})
    agentic = _FakeAgenticExecutor()
    sink = _EventSink()
    await _make_child(store, parent_id=parent.id, title="c1", assigned_to="a1", spec_id="s1")
    await _make_child(store, parent_id=parent.id, title="c2", assigned_to="a2", spec_id="s2")

    executor = _make_executor(store, registry, agentic, emit_fn=sink)
    await executor.run(parent.id)

    started = [e for e in sink.events if e[0] == EventType.CREW_TASK_STARTED]
    completed = [e for e in sink.events if e[0] == EventType.SUBTASK_COMPLETED]
    assert len(started) == 1
    assert len(completed) == 2


@pytest.mark.asyncio
async def test_no_children_returns_empty_and_still_emits_start(store):
    parent = await store.create_work_item(title="lonely-parent", work_type="work_order")
    registry = _FakeRegistry({})
    agentic = _FakeAgenticExecutor()
    sink = _EventSink()

    executor = _make_executor(store, registry, agentic, emit_fn=sink)
    results = await executor.run(parent.id)

    assert results == []
    assert [e[0] for e in sink.events] == [EventType.CREW_TASK_STARTED]


@pytest.mark.asyncio
async def test_unresolvable_agent_marks_child_failed(store):
    parent = await store.create_work_item(title="parent", work_type="work_order")
    registry = _FakeRegistry({})  # no agents registered
    agentic = _FakeAgenticExecutor()
    await _make_child(store, parent_id=parent.id, title="c1", assigned_to="ghost", spec_id="s1")

    executor = _make_executor(store, registry, agentic)
    results = await executor.run(parent.id)

    assert len(results) == 1
    assert results[0].status == "blocked"
    assert results[0].agent_id == "ghost"
    assert agentic.calls == []  # executor never ran for an unresolved agent
