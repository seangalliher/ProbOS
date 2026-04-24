"""AD-654c: TaskEvent protocol & Dispatcher tests.

Tests cover:
- TaskEvent & AgentTarget dataclass validation
- Factory functions
- Target resolution (agent, capability, department, broadcast)
- Dispatch routing (queue, fallback, overflow, unroutable)
- IntentMessage conversion
- Event emission
- DispatcherProtocol compliance
- End-to-end dispatch path
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.activation.task_event import (
    AgentTarget,
    TaskEvent,
    task_event_broadcast,
    task_event_for_agent,
    task_event_for_department,
)
from probos.activation.dispatcher import Dispatcher, DispatchResult
from probos.protocols import DispatcherProtocol
from probos.types import Priority


# ── Test helpers ─────────────────────────────────────────────────


def _make_agent(agent_id: str, agent_type: str = "scout", capabilities: list[str] | None = None):
    """Create a mock agent with registry-compatible interface."""
    agent = MagicMock()
    agent.id = agent_id
    agent.agent_type = agent_type
    agent.capabilities = capabilities or []
    agent.handle_intent = AsyncMock()
    return agent


def _make_registry(*agents):
    """Create a mock registry with get/all/get_by_capability."""
    agent_map = {a.id: a for a in agents}

    reg = MagicMock()
    reg.get = MagicMock(side_effect=lambda aid: agent_map.get(aid))
    reg.all = MagicMock(return_value=list(agents))
    reg.get_by_capability = MagicMock(
        side_effect=lambda cap: [a for a in agents if cap in a.capabilities]
    )
    return reg


def _make_ontology(dept_map: dict[str, str] | None = None):
    """Create a mock ontology with get_agent_department and get_crew_agent_types."""
    dept_map = dept_map or {}
    ont = MagicMock()
    ont.get_agent_department = MagicMock(side_effect=lambda at: dept_map.get(at))
    ont.get_crew_agent_types = MagicMock(return_value=set(dept_map.keys()))
    return ont


def _make_event(
    target: AgentTarget,
    event_type: str = "test_event",
    priority: Priority = Priority.NORMAL,
    **kwargs,
) -> TaskEvent:
    """Create a TaskEvent with sensible defaults."""
    return TaskEvent(
        source_type=kwargs.get("source_type", "test"),
        source_id=kwargs.get("source_id", "test-src-1"),
        event_type=event_type,
        priority=priority,
        target=target,
        payload=kwargs.get("payload", {"key": "value"}),
        thread_id=kwargs.get("thread_id"),
        deadline=kwargs.get("deadline"),
    )


def _make_queue(accept: bool = True):
    """Create a mock cognitive queue."""
    q = MagicMock()
    q.enqueue = MagicMock(return_value=accept)
    return q


# ── TaskEvent & AgentTarget (7 tests) ───────────────────────────


class TestTaskEventAgentTarget:
    """TaskEvent and AgentTarget dataclass validation."""

    def test_task_event_frozen(self):
        """TaskEvent is immutable (frozen=True)."""
        ev = _make_event(AgentTarget(agent_id="a1"))
        with pytest.raises(AttributeError):
            ev.event_type = "modified"  # type: ignore[misc]

    def test_agent_target_exactly_one_mode(self):
        """ValueError if 0 or 2+ modes set."""
        with pytest.raises(ValueError, match="exactly one"):
            AgentTarget()  # 0 modes
        with pytest.raises(ValueError, match="exactly one"):
            AgentTarget(agent_id="a1", capability="x")  # 2 modes
        with pytest.raises(ValueError, match="exactly one"):
            AgentTarget(agent_id="a1", broadcast=True)  # 2 modes

    def test_agent_target_agent_id(self):
        t = AgentTarget(agent_id="a1")
        assert t.agent_id == "a1"
        assert t.capability is None
        assert t.department_id is None
        assert t.broadcast is False

    def test_agent_target_capability(self):
        t = AgentTarget(capability="game_play")
        assert t.capability == "game_play"

    def test_agent_target_department(self):
        t = AgentTarget(department_id="science")
        assert t.department_id == "science"

    def test_agent_target_broadcast(self):
        t = AgentTarget(broadcast=True)
        assert t.broadcast is True

    def test_factory_functions(self):
        """Factory functions create valid TaskEvents with correct targets."""
        ev1 = task_event_for_agent(
            agent_id="a1",
            source_type="test",
            source_id="src-1",
            event_type="test_event",
            priority=Priority.NORMAL,
            payload={"k": "v"},
        )
        assert ev1.target.agent_id == "a1"

        ev2 = task_event_for_department(
            department_id="science",
            source_type="test",
            source_id="src-1",
            event_type="dept_event",
            priority=Priority.LOW,
            payload={},
        )
        assert ev2.target.department_id == "science"

        ev3 = task_event_broadcast(
            source_type="system",
            source_id="sys-1",
            event_type="broadcast",
            priority=Priority.CRITICAL,
            payload={"msg": "hello"},
        )
        assert ev3.target.broadcast is True


# ── Target Resolution (5 tests) ─────────────────────────────────


class TestTargetResolution:
    """Dispatcher._resolve_target correctly resolves abstract targets."""

    def _make_dispatcher(self, registry, ontology=None):
        return Dispatcher(
            registry=registry,
            ontology=ontology,
            get_queue=lambda aid: None,
        )

    def test_resolve_agent_id_found(self):
        a1 = _make_agent("a1")
        d = self._make_dispatcher(_make_registry(a1))
        assert d._resolve_target(AgentTarget(agent_id="a1")) == ["a1"]

    def test_resolve_agent_id_not_found(self):
        d = self._make_dispatcher(_make_registry())
        assert d._resolve_target(AgentTarget(agent_id="missing")) == []

    def test_resolve_capability(self):
        a1 = _make_agent("a1", capabilities=["game_play"])
        a2 = _make_agent("a2", capabilities=["analysis"])
        a3 = _make_agent("a3", capabilities=["game_play"])
        d = self._make_dispatcher(_make_registry(a1, a2, a3))
        result = d._resolve_target(AgentTarget(capability="game_play"))
        assert set(result) == {"a1", "a3"}

    def test_resolve_department(self):
        a1 = _make_agent("a1", agent_type="scout")
        a2 = _make_agent("a2", agent_type="data_analyst")
        a3 = _make_agent("a3", agent_type="counselor")
        dept_map = {"scout": "science", "data_analyst": "science", "counselor": "medical"}
        ont = _make_ontology(dept_map)
        d = self._make_dispatcher(_make_registry(a1, a2, a3), ontology=ont)
        result = d._resolve_target(AgentTarget(department_id="science"))
        assert set(result) == {"a1", "a2"}

    def test_resolve_broadcast(self):
        a1 = _make_agent("a1", agent_type="scout")
        a2 = _make_agent("a2", agent_type="data_analyst")
        infra = _make_agent("infra-1", agent_type="vitals_monitor")
        dept_map = {"scout": "science", "data_analyst": "science"}
        ont = _make_ontology(dept_map)
        d = self._make_dispatcher(_make_registry(a1, a2, infra), ontology=ont)
        result = d._resolve_target(AgentTarget(broadcast=True))
        # Only crew agents, not infrastructure
        assert set(result) == {"a1", "a2"}


# ── Dispatch (8 tests) ──────────────────────────────────────────


class TestDispatch:
    """Dispatcher.dispatch routing logic."""

    @pytest.mark.asyncio
    async def test_dispatch_to_agent_enqueues(self):
        """TaskEvent with agent_id target enqueues into cognitive queue."""
        a1 = _make_agent("a1")
        queue = _make_queue(accept=True)
        d = Dispatcher(
            registry=_make_registry(a1),
            ontology=None,
            get_queue=lambda aid: queue if aid == "a1" else None,
        )
        ev = _make_event(AgentTarget(agent_id="a1"))
        result = await d.dispatch(ev)
        assert result.accepted == 1
        assert result.rejected == 0
        assert "a1" in result.agent_ids
        queue.enqueue.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_to_capability_enqueues_all(self):
        a1 = _make_agent("a1", capabilities=["game_play"])
        a2 = _make_agent("a2", capabilities=["game_play"])
        queues = {"a1": _make_queue(), "a2": _make_queue()}
        d = Dispatcher(
            registry=_make_registry(a1, a2),
            ontology=None,
            get_queue=lambda aid: queues.get(aid),
        )
        ev = _make_event(AgentTarget(capability="game_play"))
        result = await d.dispatch(ev)
        assert result.accepted == 2
        assert set(result.agent_ids) == {"a1", "a2"}

    @pytest.mark.asyncio
    async def test_dispatch_to_department_enqueues_dept(self):
        a1 = _make_agent("a1", agent_type="scout")
        a2 = _make_agent("a2", agent_type="counselor")
        dept_map = {"scout": "science", "counselor": "medical"}
        ont = _make_ontology(dept_map)
        queues = {"a1": _make_queue(), "a2": _make_queue()}
        d = Dispatcher(
            registry=_make_registry(a1, a2),
            ontology=ont,
            get_queue=lambda aid: queues.get(aid),
        )
        ev = _make_event(AgentTarget(department_id="science"))
        result = await d.dispatch(ev)
        assert result.accepted == 1
        assert result.agent_ids == ["a1"]

    @pytest.mark.asyncio
    async def test_dispatch_broadcast_enqueues_all_crew(self):
        a1 = _make_agent("a1", agent_type="scout")
        a2 = _make_agent("a2", agent_type="data_analyst")
        dept_map = {"scout": "science", "data_analyst": "science"}
        ont = _make_ontology(dept_map)
        queues = {"a1": _make_queue(), "a2": _make_queue()}
        d = Dispatcher(
            registry=_make_registry(a1, a2),
            ontology=ont,
            get_queue=lambda aid: queues.get(aid),
        )
        ev = _make_event(AgentTarget(broadcast=True))
        result = await d.dispatch(ev)
        assert result.accepted == 2

    @pytest.mark.asyncio
    async def test_dispatch_result_counts(self):
        a1 = _make_agent("a1")
        a2 = _make_agent("a2")
        q1 = _make_queue(accept=True)
        q2 = _make_queue(accept=False)  # overflow
        d = Dispatcher(
            registry=_make_registry(a1, a2),
            ontology=None,
            get_queue=lambda aid: {"a1": q1, "a2": q2}.get(aid),
        )
        ev = _make_event(AgentTarget(capability="x"))
        # Both agents have capability "x"
        a1.capabilities = ["x"]
        a2.capabilities = ["x"]
        result = await d.dispatch(ev)
        assert result.accepted == 1
        assert result.rejected == 1

    @pytest.mark.asyncio
    async def test_dispatch_unroutable_emits_event(self):
        emitted = []
        d = Dispatcher(
            registry=_make_registry(),
            ontology=None,
            get_queue=lambda aid: None,
            emit_event=lambda et, data: emitted.append((et, data)),
        )
        ev = _make_event(AgentTarget(agent_id="missing"))
        result = await d.dispatch(ev)
        assert result.unroutable == 1
        assert result.target_count == 0
        assert len(emitted) == 1
        assert emitted[0][0] == "task_event_unroutable"

    @pytest.mark.asyncio
    async def test_dispatch_no_queue_fallback(self):
        a1 = _make_agent("a1")
        dispatch_fn = AsyncMock()
        d = Dispatcher(
            registry=_make_registry(a1),
            ontology=None,
            get_queue=lambda aid: None,  # No queue
            dispatch_async_fn=dispatch_fn,
        )
        ev = _make_event(AgentTarget(agent_id="a1"))
        result = await d.dispatch(ev)
        assert result.accepted == 1
        dispatch_fn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_queue_overflow_counted(self):
        a1 = _make_agent("a1")
        q = _make_queue(accept=False)
        d = Dispatcher(
            registry=_make_registry(a1),
            ontology=None,
            get_queue=lambda aid: q,
        )
        ev = _make_event(AgentTarget(agent_id="a1"))
        result = await d.dispatch(ev)
        assert result.rejected == 1
        assert result.accepted == 0


# ── Integration (6 tests) ───────────────────────────────────────


class TestIntegration:
    """End-to-end integration tests."""

    def test_taskevent_to_intent_message_conversion(self):
        """Payload preserved, _task_event_id injected."""
        d = Dispatcher(
            registry=_make_registry(),
            ontology=None,
            get_queue=lambda aid: None,
        )
        ev = _make_event(
            AgentTarget(agent_id="a1"),
            payload={"thread_id": "t1", "body": "hello"},
            source_type="ward_room",
            source_id="ch-123",
        )
        intent = d._to_intent_message(ev, "a1")
        assert intent.intent == "test_event"
        assert intent.params["thread_id"] == "t1"
        assert intent.params["body"] == "hello"
        assert intent.params["_task_event_id"] == ev.id
        assert intent.params["_source_type"] == "ward_room"
        assert intent.params["_source_id"] == "ch-123"
        assert intent.target_agent_id == "a1"

    @pytest.mark.asyncio
    async def test_dispatched_event_emitted(self):
        """TASK_EVENT_DISPATCHED event with correct data."""
        a1 = _make_agent("a1")
        emitted = []
        d = Dispatcher(
            registry=_make_registry(a1),
            ontology=None,
            get_queue=lambda aid: _make_queue(),
            emit_event=lambda et, data: emitted.append((et, data)),
        )
        ev = _make_event(AgentTarget(agent_id="a1"))
        await d.dispatch(ev)
        dispatched = [e for e in emitted if e[0] == "task_event_dispatched"]
        assert len(dispatched) == 1
        data = dispatched[0][1]
        assert data["event_id"] == ev.id
        assert data["accepted"] == 1
        assert data["agent_count"] == 1

    @pytest.mark.asyncio
    async def test_priority_preserved_through_dispatch(self):
        """CRITICAL TaskEvent → CRITICAL queue item."""
        a1 = _make_agent("a1")
        q = _make_queue()
        d = Dispatcher(
            registry=_make_registry(a1),
            ontology=None,
            get_queue=lambda aid: q,
        )
        ev = _make_event(AgentTarget(agent_id="a1"), priority=Priority.CRITICAL)
        await d.dispatch(ev)
        call_args = q.enqueue.call_args
        assert call_args[0][1] == Priority.CRITICAL  # second positional arg = priority

    def test_dispatcher_protocol_compliance(self):
        """Dispatcher satisfies DispatcherProtocol."""
        d = Dispatcher(
            registry=_make_registry(),
            ontology=None,
            get_queue=lambda aid: None,
        )
        assert isinstance(d, DispatcherProtocol)

    @pytest.mark.asyncio
    async def test_end_to_end_dispatch_to_handler(self):
        """TaskEvent → Dispatcher → queue → verify intent reaches queue."""
        a1 = _make_agent("a1")
        enqueued_items = []

        class FakeQueue:
            def enqueue(self, intent, priority):
                enqueued_items.append((intent, priority))
                return True

        d = Dispatcher(
            registry=_make_registry(a1),
            ontology=None,
            get_queue=lambda aid: FakeQueue() if aid == "a1" else None,
        )
        ev = _make_event(
            AgentTarget(agent_id="a1"),
            event_type="move_required",
            priority=Priority.NORMAL,
            payload={"game_id": "g1", "move": "e4"},
        )
        result = await d.dispatch(ev)
        assert result.accepted == 1
        assert len(enqueued_items) == 1
        intent, prio = enqueued_items[0]
        assert intent.intent == "move_required"
        assert intent.params["game_id"] == "g1"
        assert intent.params["_task_event_id"] == ev.id
        assert prio == Priority.NORMAL

    @pytest.mark.asyncio
    async def test_broadcast_mixed_queues(self):
        """Broadcast: 2 with queues (enqueued), 1 without (dispatch_async fallback)."""
        a1 = _make_agent("a1", agent_type="scout")
        a2 = _make_agent("a2", agent_type="data_analyst")
        a3 = _make_agent("a3", agent_type="counselor")
        dept_map = {"scout": "science", "data_analyst": "science", "counselor": "medical"}
        ont = _make_ontology(dept_map)

        q1 = _make_queue()
        q2 = _make_queue()
        dispatch_fn = AsyncMock()

        d = Dispatcher(
            registry=_make_registry(a1, a2, a3),
            ontology=ont,
            get_queue=lambda aid: {"a1": q1, "a2": q2}.get(aid),  # a3 has no queue
            dispatch_async_fn=dispatch_fn,
        )
        ev = _make_event(AgentTarget(broadcast=True))
        result = await d.dispatch(ev)
        assert result.accepted == 3
        assert len(result.agent_ids) == 3
        q1.enqueue.assert_called_once()
        q2.enqueue.assert_called_once()
        dispatch_fn.assert_awaited_once()
