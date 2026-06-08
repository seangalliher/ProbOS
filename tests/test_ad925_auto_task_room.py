"""AD-925: auto-create the task-linked workspace room.

When :class:`CrewTaskExecutor` fans a parent work item out to **>=2 distinct
crew** agents (and the ``group_chat.auto_task_room_enabled`` flag is ON), it
opens exactly **one** task-linked group chat via the existing AD-918
``AgentGroupChatService.create_group_chat`` path so the collaborators share a
room while they execute.

BF-287 discipline (MagicMock-at-substrate-boundary trap): every substrate piece
is **real** — a real :class:`WorkItemStore`, a real :class:`ChatThreadStore`,
and a real :class:`AgentGroupChatService`. Critically, the ``ChatThreadStore``
passed to the service and the one on the runtime stub are the **SAME instance**
(the idempotency check must read what the service wrote). The registry /
agentic-executor / callsign / clock are ``_Fake*`` duck stubs (the AD-859 /
AD-918 precedent), never ``MagicMock``.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome
from probos.cognitive.crew_executor import CrewTaskExecutor
from probos.config import GroupChatConfig
from probos.threads import ChatThreadStore
from probos.threads.agent_group_chat import AgentGroupChatService
from probos.workforce import WorkItemStore


# ---------------------------------------------------------------------------
# BF-287 real-but-fake substrate stubs
# ---------------------------------------------------------------------------


@dataclass
class _FakeAgent:
    """Combined crew-identity + execution fields.

    ``agent_type`` is a legacy crew type (``crew_utils._WARD_ROOM_CREW``) so
    ``is_crew_agent(agent, None)`` resolves True; ``instructions`` / ``department``
    / ``rank`` are read by ``CrewTaskExecutor._run_child``.
    """

    id: str
    agent_type: str
    is_alive: bool = True
    instructions: str = "do the thing"
    department: str = "engineering"
    rank: str = "ensign"


class _FakeRegistry:
    """Duck-typed AgentRegistry: only ``get`` is exercised (AD-918 shape)."""

    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._agents = agents

    def get(self, agent_id: str | None) -> _FakeAgent | None:
        if agent_id is None:
            return None
        return self._agents.get(agent_id)


class _FakeAgenticExecutor:
    """Records every ``run`` and reports each child ``complete`` (AD-859 shape)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(
        self,
        *,
        agent_id: str,
        instructions: str,
        task_text: str,
        runtime: Any,
        department: str = "",
        rank: str = "ensign",
    ) -> WorkItemAgenticOutcome:
        self.calls.append(agent_id)
        return WorkItemAgenticOutcome(
            final_text=f"done: {task_text}",
            stopped_reason="complete",
            tool_trace_ref=None,
        )


class _NoCallsigns:
    """Callsign registry stub whose resolve always misses (agent_id-only path)."""

    def resolve(self, callsign: str) -> None:
        return None


class _Clock:
    """Deterministic injectable monotonic clock (real fixture, not MagicMock)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


# ---------------------------------------------------------------------------
# Fixtures / assembly helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def wi_store(tmp_path):
    """Real WorkItemStore (BF-287 — MagicMock only for the emit hook)."""
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


def _assemble(
    tmp_path,
    wi_store: WorkItemStore,
    *,
    agents: dict[str, _FakeAgent],
    config: GroupChatConfig,
) -> tuple[CrewTaskExecutor, ChatThreadStore]:
    """Wire a real ChatThreadStore + AgentGroupChatService onto a runtime stub.

    The same ``chat_store`` instance is shared by the service and the runtime
    stub so the AD-925 idempotency lookup reads what the service persisted.
    """
    registry = _FakeRegistry(agents)
    chat_store = ChatThreadStore(tmp_path / "chat_threads.db")
    service = AgentGroupChatService(
        store=chat_store,
        registry=registry,
        callsign_registry=_NoCallsigns(),
        config=config,
        ontology_provider=None,
        clock=_Clock(),
    )
    runtime = SimpleNamespace(
        config=SimpleNamespace(group_chat=config),
        agent_group_chat=service,
        chat_thread_store=chat_store,
    )
    executor = CrewTaskExecutor(
        work_item_store=wi_store,
        agent_registry=registry,
        agentic_executor=_FakeAgenticExecutor(),  # type: ignore[arg-type]
        runtime=runtime,
        max_parallel_subtasks=3,
    )
    return executor, chat_store


async def _make_parent_with_children(
    wi_store: WorkItemStore, *, title: str, assignees: list[str]
):
    """Create a real parent + one child per assignee (the AD-859 _make_child shape)."""
    parent = await wi_store.create_work_item(
        title=title, description="parent task", work_type="task"
    )
    for i, assignee in enumerate(assignees):
        await wi_store.create_work_item(
            title=f"child-{i}",
            description=f"do child-{i}",
            work_type="task",
            parent_id=parent.id,
            assigned_to=assignee,
            metadata={"spec_id": f"spec-{i}"},
        )
    return parent


def _two_crew() -> dict[str, _FakeAgent]:
    return {
        "bones-1": _FakeAgent("bones-1", "diagnostician"),
        "forge-1": _FakeAgent("forge-1", "builder"),
    }


# ---------------------------------------------------------------------------
# 1. happy path — >=2 crew fan-out opens exactly one task-linked room
# ---------------------------------------------------------------------------


async def test_two_crew_fanout_opens_one_task_room(tmp_path, wi_store):
    agents = _two_crew()
    config = GroupChatConfig(auto_task_room_enabled=True)
    executor, chat_store = _assemble(tmp_path, wi_store, agents=agents, config=config)
    parent = await _make_parent_with_children(
        wi_store, title="Build the dashboard", assignees=["forge-1", "bones-1"]
    )

    await executor.run(parent.id)

    rooms = chat_store.list_threads(task_id=parent.id, include_archived=True)
    assert len(rooms) == 1
    room = rooms[0]
    assert room.title == "Task: Build the dashboard"
    assert room.task_id == parent.id
    # creator = first stable-sorted crew assignee.
    assert room.metadata["created_by_agent"] == "bones-1"
    # final participants == exactly the crew child-assignees.
    assert set(room.participants) == {"forge-1", "bones-1"}


# ---------------------------------------------------------------------------
# 2. a single distinct crew assignee opens no room
# ---------------------------------------------------------------------------


async def test_single_crew_parent_opens_no_room(tmp_path, wi_store):
    agents = {"forge-1": _FakeAgent("forge-1", "builder")}
    config = GroupChatConfig(auto_task_room_enabled=True)
    executor, chat_store = _assemble(tmp_path, wi_store, agents=agents, config=config)
    # Two children, BOTH assigned to the same single agent -> 1 distinct crew.
    parent = await _make_parent_with_children(
        wi_store, title="Solo work", assignees=["forge-1", "forge-1"]
    )

    await executor.run(parent.id)

    assert chat_store.list_threads(task_id=parent.id, include_archived=True) == []


# ---------------------------------------------------------------------------
# 3. idempotency — a second run / retry does not duplicate the room
# ---------------------------------------------------------------------------


async def test_idempotent_second_run_no_duplicate(tmp_path, wi_store):
    agents = _two_crew()
    config = GroupChatConfig(auto_task_room_enabled=True)
    executor, chat_store = _assemble(tmp_path, wi_store, agents=agents, config=config)
    parent = await _make_parent_with_children(
        wi_store, title="Build the dashboard", assignees=["forge-1", "bones-1"]
    )

    await executor.run(parent.id)
    await executor.run(parent.id)  # retry / re-run

    assert len(chat_store.list_threads(task_id=parent.id, include_archived=True)) == 1


# ---------------------------------------------------------------------------
# 4. config flag OFF -> no room (zero-config default behaviour)
# ---------------------------------------------------------------------------


async def test_config_off_opens_no_room(tmp_path, wi_store):
    agents = _two_crew()
    config = GroupChatConfig(auto_task_room_enabled=False)
    executor, chat_store = _assemble(tmp_path, wi_store, agents=agents, config=config)
    parent = await _make_parent_with_children(
        wi_store, title="Build the dashboard", assignees=["forge-1", "bones-1"]
    )

    await executor.run(parent.id)

    assert chat_store.list_threads(task_id=parent.id, include_archived=True) == []


# ---------------------------------------------------------------------------
# 5. non-crew assignees -> crew gate holds -> no room
# ---------------------------------------------------------------------------


async def test_noncrew_assignees_open_no_room(tmp_path, wi_store):
    # "captain" is NOT in crew_utils._WARD_ROOM_CREW.
    agents = {
        "cap-1": _FakeAgent("cap-1", "captain"),
        "cap-2": _FakeAgent("cap-2", "captain"),
    }
    config = GroupChatConfig(auto_task_room_enabled=True)
    executor, chat_store = _assemble(tmp_path, wi_store, agents=agents, config=config)
    parent = await _make_parent_with_children(
        wi_store, title="Non-crew work", assignees=["cap-1", "cap-2"]
    )

    await executor.run(parent.id)

    assert chat_store.list_threads(task_id=parent.id, include_archived=True) == []


# ---------------------------------------------------------------------------
# 6. AD-918 rate guard holds — rate-limited creator -> no room, fan-out survives
# ---------------------------------------------------------------------------


async def test_rate_limited_creator_degrades_no_room(tmp_path, wi_store):
    agents = _two_crew()
    # max_per_window=0 -> _rate_ok always denies -> create returns rate_limited.
    config = GroupChatConfig(
        auto_task_room_enabled=True, agent_create_max_per_window=0
    )
    executor, chat_store = _assemble(tmp_path, wi_store, agents=agents, config=config)
    parent = await _make_parent_with_children(
        wi_store, title="Build the dashboard", assignees=["forge-1", "bones-1"]
    )

    results = await executor.run(parent.id)

    # No room (rate guard denied the create) ...
    assert chat_store.list_threads(task_id=parent.id, include_archived=True) == []
    # ... but the fan-out is NOT aborted: both children still produced results.
    assert len(results) == 2
    assert all(r.status == "done" for r in results)


# ---------------------------------------------------------------------------
# 7. honest-degrade — group-chat substrate not wired on the runtime
# ---------------------------------------------------------------------------


async def test_missing_substrate_degrades_no_crash(tmp_path, wi_store):
    agents = _two_crew()
    config = GroupChatConfig(auto_task_room_enabled=True)
    registry = _FakeRegistry(agents)
    # Runtime exposes the flag ON but NO agent_group_chat / chat_thread_store.
    runtime = SimpleNamespace(config=SimpleNamespace(group_chat=config))
    executor = CrewTaskExecutor(
        work_item_store=wi_store,
        agent_registry=registry,
        agentic_executor=_FakeAgenticExecutor(),  # type: ignore[arg-type]
        runtime=runtime,
        max_parallel_subtasks=3,
    )
    parent = await _make_parent_with_children(
        wi_store, title="Build the dashboard", assignees=["forge-1", "bones-1"]
    )

    # Must not raise; the fan-out still returns its results.
    results = await executor.run(parent.id)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# 8. Section-2 primitive — list_threads(task_id=) filters correctly
# ---------------------------------------------------------------------------


def test_list_threads_filters_by_task_id(tmp_path):
    store = ChatThreadStore(tmp_path / "chat_threads.db")
    t_a = store.create_thread(title="A", participants=["x"], task_id="task-A")
    store.create_thread(title="B", participants=["x"], task_id="task-B")
    store.create_thread(title="C", participants=["x"])  # no task_id

    got = store.list_threads(task_id="task-A")

    assert [t.id for t in got] == [t_a.id]
