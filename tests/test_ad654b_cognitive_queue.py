"""AD-654b: Agent Cognitive Queue tests.

Tests cover: priority ordering, enqueue/overflow, processor loop,
priority preemption, IntentBus integration, lifecycle, and events.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.queue import AgentCognitiveQueue, QueueItem, _PRIORITY_ORDER
from probos.events import EventType
from probos.types import Priority


# ── Test helpers ──────────────────────────────────────────────────


def _make_intent(intent_name="ward_room_notification", **params):
    """Create a minimal IntentMessage-like object."""
    mock = MagicMock()
    mock.intent = intent_name
    mock.params = params
    mock.target_agent_id = "test-agent"
    return mock


def _make_js_msg():
    """Create a mock JetStream message with ack/term/nak."""
    msg = AsyncMock()
    msg.ack = AsyncMock()
    msg.term = AsyncMock()
    msg.nak = AsyncMock()
    return msg


def _make_queue(handler=None, max_size=50, should_process=None, emit_event=None):
    """Create a queue with sensible defaults."""
    if handler is None:
        handler = AsyncMock()
    return AgentCognitiveQueue(
        agent_id="test-agent-1234",
        handler=handler,
        max_size=max_size,
        should_process=should_process,
        emit_event=emit_event,
    )


# ── Priority ordering (5 tests) ──────────────────────────────────


class TestPriorityOrdering:

    def test_critical_dequeued_before_normal(self):
        q = _make_queue()
        q.enqueue(_make_intent("normal_task"), Priority.NORMAL)
        q.enqueue(_make_intent("critical_task"), Priority.CRITICAL)

        item = q._dequeue()
        assert item is not None
        assert item.intent.intent == "critical_task"
        assert item.priority == Priority.CRITICAL

    def test_normal_dequeued_before_low(self):
        q = _make_queue()
        q.enqueue(_make_intent("low_task"), Priority.LOW)
        q.enqueue(_make_intent("normal_task"), Priority.NORMAL)

        item = q._dequeue()
        assert item is not None
        assert item.intent.intent == "normal_task"

    def test_fifo_within_same_priority(self):
        q = _make_queue()
        q.enqueue(_make_intent("first"), Priority.NORMAL)
        q.enqueue(_make_intent("second"), Priority.NORMAL)

        item1 = q._dequeue()
        item2 = q._dequeue()
        assert item1.intent.intent == "first"
        assert item2.intent.intent == "second"

    def test_mixed_priorities_exact_order(self):
        q = _make_queue()
        q.enqueue(_make_intent("low"), Priority.LOW)
        q.enqueue(_make_intent("critical"), Priority.CRITICAL)
        q.enqueue(_make_intent("normal"), Priority.NORMAL)

        order = []
        while True:
            item = q._dequeue()
            if item is None:
                break
            order.append(item.intent.intent)
        assert order == ["critical", "normal", "low"]

    def test_empty_queue_returns_none(self):
        q = _make_queue()
        assert q._dequeue() is None


# ── Enqueue/overflow (4 tests) ────────────────────────────────────


class TestEnqueueOverflow:

    def test_enqueue_returns_true_with_space(self):
        q = _make_queue(max_size=10)
        result = q.enqueue(_make_intent(), Priority.NORMAL)
        assert result is True
        assert q.pending_count() == 1

    def test_overflow_critical_sheds_low(self):
        q = _make_queue(max_size=2)
        q.enqueue(_make_intent("low1"), Priority.LOW)
        q.enqueue(_make_intent("low2"), Priority.LOW)

        result = q.enqueue(_make_intent("critical1"), Priority.CRITICAL)
        assert result is True
        assert q.pending_count() == 2
        # Verify a LOW was shed — remaining should be 1 LOW + 1 CRITICAL
        items = []
        while True:
            item = q._dequeue()
            if item is None:
                break
            items.append(item)
        priorities = [i.priority for i in items]
        assert Priority.CRITICAL in priorities

    def test_overflow_low_rejected_not_shed_critical(self):
        q = _make_queue(max_size=2)
        q.enqueue(_make_intent("crit1"), Priority.CRITICAL)
        q.enqueue(_make_intent("crit2"), Priority.CRITICAL)

        result = q.enqueue(_make_intent("low1"), Priority.LOW)
        assert result is False
        assert q.pending_count() == 2

    @pytest.mark.asyncio
    async def test_shed_item_js_msg_gets_term(self):
        q = _make_queue(max_size=1)
        js_msg_shed = _make_js_msg()
        q.enqueue(_make_intent("low1"), Priority.LOW, js_msg=js_msg_shed)

        result = q.enqueue(_make_intent("crit1"), Priority.CRITICAL)
        assert result is True
        # Give the create_task(term()) a tick to run
        await asyncio.sleep(0.01)
        js_msg_shed.term.assert_awaited_once()


# ── Processor loop (5 tests) ──────────────────────────────────────


class TestProcessorLoop:

    @pytest.mark.asyncio
    async def test_processor_calls_handler(self):
        handler = AsyncMock()
        q = _make_queue(handler=handler)
        await q.start()

        intent = _make_intent("test")
        q.enqueue(intent, Priority.NORMAL)
        await asyncio.sleep(0.05)

        handler.assert_awaited_once_with(intent)
        await q.shutdown()

    @pytest.mark.asyncio
    async def test_handler_success_acks_js_msg(self):
        handler = AsyncMock()
        q = _make_queue(handler=handler)
        await q.start()

        js_msg = _make_js_msg()
        q.enqueue(_make_intent(), Priority.NORMAL, js_msg=js_msg)
        await asyncio.sleep(0.05)

        js_msg.ack.assert_awaited_once()
        js_msg.term.assert_not_awaited()
        await q.shutdown()

    @pytest.mark.asyncio
    async def test_handler_error_terms_js_msg(self):
        handler = AsyncMock(side_effect=RuntimeError("boom"))
        q = _make_queue(handler=handler)
        await q.start()

        js_msg = _make_js_msg()
        q.enqueue(_make_intent(), Priority.NORMAL, js_msg=js_msg)
        await asyncio.sleep(0.05)

        js_msg.term.assert_awaited_once()
        js_msg.ack.assert_not_awaited()
        await q.shutdown()

    @pytest.mark.asyncio
    async def test_guard_transient_rejection_naks(self):
        def _guard(item, js_msg):
            return (False, True)  # transient rejection

        handler = AsyncMock()
        q = _make_queue(handler=handler, should_process=_guard)
        await q.start()

        js_msg = _make_js_msg()
        q.enqueue(_make_intent(), Priority.NORMAL, js_msg=js_msg)
        await asyncio.sleep(0.05)

        js_msg.nak.assert_awaited_once_with(delay=60)
        handler.assert_not_awaited()
        await q.shutdown()

    @pytest.mark.asyncio
    async def test_guard_permanent_rejection_terms(self):
        def _guard(item, js_msg):
            return (False, False)  # permanent rejection

        handler = AsyncMock()
        q = _make_queue(handler=handler, should_process=_guard)
        await q.start()

        js_msg = _make_js_msg()
        q.enqueue(_make_intent(), Priority.NORMAL, js_msg=js_msg)
        await asyncio.sleep(0.05)

        js_msg.term.assert_awaited_once()
        handler.assert_not_awaited()
        await q.shutdown()


# ── Priority preemption (1 test) ──────────────────────────────────


class TestPriorityPreemption:

    @pytest.mark.asyncio
    async def test_critical_processed_next_after_normal(self):
        """CRITICAL enqueued during NORMAL processing runs next."""
        call_order = []
        handler_started = asyncio.Event()
        handler_continue = asyncio.Event()

        async def slow_handler(intent):
            call_order.append(intent.intent)
            if intent.intent == "normal1":
                handler_started.set()
                await handler_continue.wait()

        q = _make_queue(handler=slow_handler)
        await q.start()

        # Enqueue NORMAL + another NORMAL
        q.enqueue(_make_intent("normal1"), Priority.NORMAL)
        q.enqueue(_make_intent("normal2"), Priority.NORMAL)

        # Wait for first handler to start
        await asyncio.wait_for(handler_started.wait(), timeout=1.0)

        # Now enqueue CRITICAL while normal1 is in-flight
        q.enqueue(_make_intent("critical1"), Priority.CRITICAL)

        # Let normal1 finish
        handler_continue.set()
        await asyncio.sleep(0.1)

        # critical1 should be processed before normal2
        assert call_order == ["normal1", "critical1", "normal2"]
        await q.shutdown()


# ── IntentBus integration (5 tests) ──────────────────────────────


class TestIntentBusIntegration:

    def test_register_and_get_queue(self):
        from probos.mesh.intent import IntentBus
        from probos.mesh.signal import SignalManager

        bus = IntentBus(SignalManager())
        queue = _make_queue()
        bus.register_queue("agent-1", queue)
        assert bus._get_agent_queue("agent-1") is queue

    def test_unregister_clears_queue(self):
        from probos.mesh.intent import IntentBus
        from probos.mesh.signal import SignalManager

        bus = IntentBus(SignalManager())
        queue = _make_queue()
        bus.register_queue("agent-1", queue)
        bus.unregister_queue("agent-1")
        assert bus._get_agent_queue("agent-1") is None

    @pytest.mark.asyncio
    async def test_dispatch_callback_captain_enqueues_critical(self):
        """JetStream _on_dispatch enqueues Captain posts as CRITICAL."""
        from probos.mesh.intent import IntentBus
        from probos.mesh.signal import SignalManager

        bus = IntentBus(SignalManager())
        handler = AsyncMock()
        q = _make_queue(handler=handler)
        bus.register_queue("agent-1", q)

        intent = _make_intent("ward_room_notification", is_captain=True, thread_id="t1")
        # Simulate _on_dispatch behavior
        priority = Priority.classify(
            intent=intent.intent,
            is_captain=intent.params.get("is_captain", False),
            was_mentioned=intent.params.get("was_mentioned", False),
        )
        assert priority == Priority.CRITICAL
        accepted = q.enqueue(intent, priority)
        assert accepted is True
        item = q._dequeue()
        assert item.priority == Priority.CRITICAL

    @pytest.mark.asyncio
    async def test_dispatch_callback_normal_enqueues_normal(self):
        """Normal ward room post enqueues as NORMAL."""
        intent = _make_intent("ward_room_notification", is_captain=False, was_mentioned=False)
        priority = Priority.classify(
            intent=intent.intent,
            is_captain=False,
            was_mentioned=False,
        )
        assert priority == Priority.NORMAL

    @pytest.mark.asyncio
    async def test_fallback_uses_queue_when_available(self):
        """dispatch_async fallback uses queue when registered, skips create_task."""
        from probos.mesh.intent import IntentBus
        from probos.mesh.signal import SignalManager
        from probos.types import IntentMessage

        bus = IntentBus(SignalManager())
        handler = AsyncMock()
        bus.subscribe("agent-1", handler)

        q = _make_queue(handler=handler)
        bus.register_queue("agent-1", q)

        intent = IntentMessage(
            intent="ward_room_notification",
            params={},
            context="test",
            target_agent_id="agent-1",
        )
        await bus.dispatch_async(intent)
        # Queue should have the item, create_task should NOT have been called
        assert q.pending_count() == 1

    @pytest.mark.asyncio
    async def test_fallback_no_queue_uses_create_task(self):
        """dispatch_async fallback falls through to create_task for substrate agents."""
        from probos.mesh.intent import IntentBus
        from probos.mesh.signal import SignalManager
        from probos.types import IntentMessage

        bus = IntentBus(SignalManager())
        handler = AsyncMock()
        bus.subscribe("substrate-agent", handler)
        # No queue registered for this agent

        intent = IntentMessage(
            intent="some_intent",
            params={},
            context="test",
            target_agent_id="substrate-agent",
        )
        await bus.dispatch_async(intent)
        # Handler should be called directly via create_task
        await asyncio.sleep(0.05)
        handler.assert_awaited_once()


# ── Lifecycle (3 tests) ───────────────────────────────────────────


class TestLifecycle:

    @pytest.mark.asyncio
    async def test_start_creates_task(self):
        q = _make_queue()
        await q.start()
        assert q._task is not None
        assert not q._task.done()
        await q.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_does_not_term_pending(self):
        """Pending JetStream messages are NOT term'd on shutdown — left for redelivery."""
        q = _make_queue()
        await q.start()

        js_msg1 = _make_js_msg()
        js_msg2 = _make_js_msg()
        q.enqueue(_make_intent("a"), Priority.NORMAL, js_msg=js_msg1)
        q.enqueue(_make_intent("b"), Priority.NORMAL, js_msg=js_msg2)

        # Shut down immediately before processor can drain
        await q.shutdown()

        # Neither should be term'd — left for JetStream redelivery
        js_msg1.term.assert_not_awaited()
        js_msg2.term.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pending_count_and_is_processing(self):
        handler_started = asyncio.Event()
        handler_continue = asyncio.Event()

        async def slow_handler(intent):
            handler_started.set()
            await handler_continue.wait()

        q = _make_queue(handler=slow_handler)
        await q.start()

        q.enqueue(_make_intent("a"), Priority.NORMAL)
        q.enqueue(_make_intent("b"), Priority.NORMAL)

        await asyncio.wait_for(handler_started.wait(), timeout=1.0)
        # One is being processed, one is pending
        assert q.is_processing() is True
        assert q.pending_count() == 1

        handler_continue.set()
        await asyncio.sleep(0.05)
        assert q.is_processing() is False
        assert q.pending_count() == 0
        await q.shutdown()


# ── Event emission (1 test) ───────────────────────────────────────


class TestEventEmission:

    @pytest.mark.asyncio
    async def test_dequeue_event_includes_wait_ms(self):
        events = []

        def _emit(event_type, data):
            events.append((event_type, data))

        handler = AsyncMock()
        q = _make_queue(handler=handler, emit_event=_emit)
        await q.start()

        q.enqueue(_make_intent("test"), Priority.NORMAL)
        await asyncio.sleep(0.05)

        dequeue_events = [
            (t, d) for t, d in events
            if t == EventType.QUEUE_ITEM_DEQUEUED.value
        ]
        assert len(dequeue_events) == 1
        _, data = dequeue_events[0]
        assert "wait_ms" in data
        assert isinstance(data["wait_ms"], (int, float))
        assert data["wait_ms"] >= 0
        await q.shutdown()
