"""Tests for IntentBus."""

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import probos.mesh.intent as intent_module
from probos.mesh.intent import IntentBus
from probos.mesh.nats_bus import MockNATSBus
from probos.mesh.signal import SignalManager
from probos.types import HandlerLatencyClass, IntentMessage, IntentResult


class _MonotonicClock:
    def __init__(self, ticks: list[float]) -> None:
        self._ticks = deque(ticks)

    def monotonic(self) -> float:
        if not self._ticks:
            raise AssertionError("monotonic clock exhausted")
        return self._ticks.popleft()


def _install_clock(monkeypatch, *ticks: float) -> _MonotonicClock:
    clock = _MonotonicClock(list(ticks))
    monkeypatch.setattr(
        intent_module,
        "time",
        SimpleNamespace(monotonic=clock.monotonic),
    )
    return clock


@pytest.fixture
def signal_manager():
    return SignalManager()


@pytest.fixture
def intent_bus(signal_manager):
    return IntentBus(signal_manager)


class TestIntentBus:
    @pytest.mark.asyncio
    async def test_broadcast_no_subscribers(self, intent_bus):
        intent = IntentMessage(intent="test", ttl_seconds=5.0)
        results = await intent_bus.broadcast(intent, timeout=1.0)
        assert results == []

    @pytest.mark.asyncio
    async def test_broadcast_single_subscriber(self, intent_bus):
        async def handler(intent: IntentMessage) -> IntentResult | None:
            return IntentResult(
                intent_id=intent.id,
                agent_id="agent-1",
                success=True,
                result="handled",
                confidence=0.9,
            )

        intent_bus.subscribe("agent-1", handler)
        intent = IntentMessage(intent="test")
        results = await intent_bus.broadcast(intent, timeout=2.0)

        assert len(results) == 1
        assert results[0].success
        assert results[0].result == "handled"
        assert results[0].agent_id == "agent-1"

    @pytest.mark.asyncio
    async def test_broadcast_multiple_subscribers(self, intent_bus):
        async def make_handler(agent_id: str):
            async def handler(intent: IntentMessage) -> IntentResult | None:
                return IntentResult(
                    intent_id=intent.id,
                    agent_id=agent_id,
                    success=True,
                    result=f"from-{agent_id}",
                    confidence=0.8,
                )
            return handler

        for i in range(3):
            aid = f"agent-{i}"
            intent_bus.subscribe(aid, await make_handler(aid))

        intent = IntentMessage(intent="test")
        results = await intent_bus.broadcast(intent, timeout=2.0)

        assert len(results) == 3
        agent_ids = {r.agent_id for r in results}
        assert agent_ids == {"agent-0", "agent-1", "agent-2"}

    @pytest.mark.asyncio
    async def test_subscriber_can_decline(self, intent_bus):
        """A subscriber returning None means it declined the intent."""

        async def declines(intent: IntentMessage) -> IntentResult | None:
            return None

        async def accepts(intent: IntentMessage) -> IntentResult | None:
            return IntentResult(
                intent_id=intent.id,
                agent_id="acceptor",
                success=True,
                result="accepted",
            )

        intent_bus.subscribe("decliner", declines)
        intent_bus.subscribe("acceptor", accepts)

        results = await intent_bus.broadcast(IntentMessage(intent="test"), timeout=2.0)
        assert len(results) == 1
        assert results[0].agent_id == "acceptor"

    @pytest.mark.asyncio
    async def test_subscriber_error_recorded(self, intent_bus):
        async def fails(intent: IntentMessage) -> IntentResult | None:
            raise RuntimeError("boom")

        intent_bus.subscribe("failing", fails)
        results = await intent_bus.broadcast(IntentMessage(intent="test"), timeout=2.0)

        assert len(results) == 1
        assert not results[0].success
        assert "boom" in results[0].error

    @pytest.mark.asyncio
    async def test_unsubscribe(self, intent_bus):
        async def handler(intent: IntentMessage) -> IntentResult | None:
            return IntentResult(
                intent_id=intent.id, agent_id="a", success=True
            )

        intent_bus.subscribe("a", handler)
        assert intent_bus.subscriber_count == 1
        intent_bus.unsubscribe("a")
        assert intent_bus.subscriber_count == 0

        results = await intent_bus.broadcast(IntentMessage(intent="test"), timeout=1.0)
        assert results == []

    def test_subscribe_explicit_latency_class_preserves_callable(self, intent_bus):
        async def handler(intent: IntentMessage) -> IntentResult | None:
            return None

        intent_bus.subscribe(
            "cognitive-agent",
            handler,
            latency_class=HandlerLatencyClass.COGNITIVE,
        )

        assert intent_bus._subscribers["cognitive-agent"] is handler
        assert (
            intent_bus._subscriber_latency_classes["cognitive-agent"]
            == HandlerLatencyClass.COGNITIVE
        )

    def test_legacy_subscribe_defaults_deterministic(self, intent_bus):
        async def handler(intent: IntentMessage) -> IntentResult | None:
            return None

        intent_bus.subscribe("two-arg", handler)
        intent_bus.subscribe("three-arg", handler, ["test"])

        assert intent_bus._subscriber_latency_classes == {
            "two-arg": HandlerLatencyClass.DETERMINISTIC,
            "three-arg": HandlerLatencyClass.DETERMINISTIC,
        }

    @pytest.mark.parametrize("invalid", ["cognitive", 1, None])
    def test_subscribe_rejects_non_enum_before_mutation(self, intent_bus, invalid):
        async def handler(intent: IntentMessage) -> IntentResult | None:
            return None

        with pytest.raises(TypeError, match="HandlerLatencyClass"):
            intent_bus.subscribe(
                "invalid",
                handler,
                latency_class=invalid,
            )

        assert "invalid" not in intent_bus._subscribers
        assert "invalid" not in intent_bus._subscriber_latency_classes

    def test_resubscribe_replaces_handler_and_latency_class(self, intent_bus):
        async def old_handler(intent: IntentMessage) -> IntentResult | None:
            return None

        async def new_handler(intent: IntentMessage) -> IntentResult | None:
            return None

        intent_bus.subscribe(
            "agent",
            old_handler,
            latency_class=HandlerLatencyClass.COGNITIVE,
        )
        intent_bus.subscribe(
            "agent",
            new_handler,
            latency_class=HandlerLatencyClass.NETWORK,
        )

        assert intent_bus._subscribers["agent"] is new_handler
        assert (
            intent_bus._subscriber_latency_classes["agent"]
            == HandlerLatencyClass.NETWORK
        )

    def test_unsubscribe_removes_handler_class_queue_and_index(self, intent_bus):
        async def handler(intent: IntentMessage) -> IntentResult | None:
            return None

        queue = object()
        intent_bus.subscribe(
            "agent",
            handler,
            ["test"],
            latency_class=HandlerLatencyClass.COGNITIVE,
        )
        intent_bus.register_queue("agent", queue)

        intent_bus.unsubscribe("agent")

        assert "agent" not in intent_bus._subscribers
        assert "agent" not in intent_bus._subscriber_latency_classes
        assert intent_bus._get_agent_queue("agent") is None
        assert "agent" not in intent_bus._intent_index["test"]

    @pytest.mark.asyncio
    async def test_direct_subscriber_injection_defaults_deterministic(self, intent_bus):
        async def handler(intent: IntentMessage) -> IntentResult:
            return IntentResult(intent_id=intent.id, agent_id="legacy", success=True)

        intent_bus._subscribers["legacy"] = handler

        results = await intent_bus.broadcast(
            IntentMessage(intent="test"),
            federated=False,
        )

        assert [result.agent_id for result in results] == ["legacy"]
        assert intent_bus.get_metrics()["handlers"][0]["latency_class"] == "deterministic"

    @pytest.mark.asyncio
    async def test_broadcast_snapshots_handler_and_latency_class_together(self, intent_bus):
        started = asyncio.Event()
        release = asyncio.Event()
        calls: list[str] = []

        async def old_handler(intent: IntentMessage) -> IntentResult:
            calls.append("old")
            started.set()
            await release.wait()
            return IntentResult(intent_id=intent.id, agent_id="agent", success=True)

        async def new_handler(intent: IntentMessage) -> IntentResult:
            calls.append("new")
            return IntentResult(intent_id=intent.id, agent_id="agent", success=True)

        intent_bus.subscribe(
            "agent",
            old_handler,
            ["test"],
            latency_class=HandlerLatencyClass.COGNITIVE,
        )
        first = asyncio.create_task(
            intent_bus.broadcast(IntentMessage(intent="test"), federated=False)
        )
        await started.wait()
        intent_bus.subscribe(
            "agent",
            new_handler,
            ["test"],
            latency_class=HandlerLatencyClass.DETERMINISTIC,
        )
        release.set()
        await first

        old_key = (
            "agent",
            "test",
            HandlerLatencyClass.COGNITIVE.value,
        )
        first_rows = {
            (row["agent_id"], row["intent"], row["latency_class"]): row
            for row in intent_bus.get_metrics()["handlers"]
        }
        assert calls == ["old"]
        assert set(first_rows) == {old_key}
        assert first_rows[old_key]["responded_count"] == 1

        await intent_bus.broadcast(IntentMessage(intent="test"), federated=False)

        assert calls == ["old", "new"]
        new_key = (
            "agent",
            "test",
            HandlerLatencyClass.DETERMINISTIC.value,
        )
        final_rows = {
            (row["agent_id"], row["intent"], row["latency_class"]): row
            for row in intent_bus.get_metrics()["handlers"]
        }
        assert set(final_rows) == {old_key, new_key}
        assert final_rows[old_key]["responded_count"] == 1
        assert final_rows[new_key]["responded_count"] == 1

    @pytest.mark.asyncio
    async def test_cognitive_completion_within_budget_records_without_warning(
        self,
        intent_bus,
        caplog,
        monkeypatch,
    ):
        async def handler(intent: IntentMessage) -> IntentResult:
            return IntentResult(
                intent_id=intent.id,
                agent_id="cognitive-agent-full-id",
                success=True,
            )

        _install_clock(monkeypatch, 0.0, 0.0, 0.0, 8.0, 8.0)
        intent_bus.subscribe(
            "cognitive-agent-full-id",
            handler,
            intent_names=["reason"],
            latency_class=HandlerLatencyClass.COGNITIVE,
        )

        with caplog.at_level(logging.WARNING, logger="probos.mesh.intent"):
            results = await intent_bus.broadcast(
                IntentMessage(intent="reason"),
                federated=False,
            )

        assert len(results) == 1
        assert caplog.records == []
        assert intent_bus.get_metrics()["handlers"] == [
            {
                "agent_id": "cognitive-agent-full-id",
                "intent": "reason",
                "latency_class": "cognitive",
                "count": 1,
                "mean_ms": 8000.0,
                "p95_ms": 8000.0,
                "max_ms": 8000.0,
                "responded_count": 1,
                "declined_count": 0,
                "error_count": 0,
            }
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("latency_class", "elapsed_ms", "threshold_ms", "warns"),
        [
            (HandlerLatencyClass.DETERMINISTIC, 100.0, 100.0, False),
            (HandlerLatencyClass.DETERMINISTIC, 101.0, 100.0, True),
            (HandlerLatencyClass.NETWORK, 8000.0, 10_000.0, False),
            (HandlerLatencyClass.NETWORK, 10_001.0, 10_000.0, True),
            (HandlerLatencyClass.COGNITIVE, 30_001.0, 30_000.0, True),
        ],
    )
    async def test_completed_response_uses_strict_class_budget(
        self,
        intent_bus,
        caplog,
        monkeypatch,
        latency_class,
        elapsed_ms,
        threshold_ms,
        warns,
    ):
        agent_id = "agent-full-identifier-0123456789"
        intent_name = "intent.full.identifier"

        async def handler(intent: IntentMessage) -> IntentResult:
            return IntentResult(intent_id=intent.id, agent_id=agent_id, success=True)

        _install_clock(monkeypatch, 0.0, 0.0, 0.0, elapsed_ms / 1000.0, elapsed_ms / 1000.0)
        intent_bus.subscribe(
            agent_id,
            handler,
            [intent_name],
            latency_class=latency_class,
        )

        with caplog.at_level(logging.WARNING, logger="probos.mesh.intent"):
            await intent_bus.broadcast(IntentMessage(intent=intent_name), federated=False)

        warning_records = [
            record for record in caplog.records
            if "latency budget" in record.message
        ]
        assert len(warning_records) == int(warns)
        if warns:
            message = warning_records[0].message
            assert f"agent_id={agent_id}" in message
            assert f"intent={intent_name}" in message
            assert f"latency_class={latency_class.value}" in message
            assert f"threshold_ms={threshold_ms:.0f}" in message
            assert f"elapsed_ms={elapsed_ms:.0f}" in message
            assert "outcome=responded" in message
            assert "dispatch=completed" in message
        row = intent_bus.get_metrics()["handlers"][0]
        assert row["agent_id"] == agent_id
        assert row["intent"] == intent_name
        assert row["latency_class"] == latency_class.value
        assert row["responded_count"] == 1
        assert row["mean_ms"] == elapsed_ms

    @pytest.mark.asyncio
    async def test_unclassified_101ms_warns_as_deterministic(
        self,
        intent_bus,
        caplog,
        monkeypatch,
    ):
        async def handler(intent: IntentMessage) -> IntentResult:
            return IntentResult(intent_id=intent.id, agent_id="legacy", success=True)

        _install_clock(monkeypatch, 0.0, 0.0, 0.0, 0.101, 0.101)
        intent_bus._subscribers["legacy"] = handler

        with caplog.at_level(logging.WARNING, logger="probos.mesh.intent"):
            await intent_bus.broadcast(IntentMessage(intent="legacy.intent"), federated=False)

        assert len(caplog.records) == 1
        assert "latency_class=deterministic" in caplog.records[0].message

    @pytest.mark.asyncio
    async def test_above_budget_decline_records_and_warns(
        self,
        intent_bus,
        caplog,
        monkeypatch,
    ):
        async def handler(intent: IntentMessage) -> IntentResult | None:
            return None

        _install_clock(monkeypatch, 0.0, 0.0, 0.0, 0.101, 0.101)
        intent_bus.subscribe("decliner", handler)

        with caplog.at_level(logging.WARNING, logger="probos.mesh.intent"):
            results = await intent_bus.broadcast(
                IntentMessage(intent="decline"), federated=False
            )

        assert results == []
        assert len(caplog.records) == 1
        assert "outcome=declined" in caplog.records[0].message
        row = intent_bus.get_metrics()["handlers"][0]
        assert row["declined_count"] == 1
        assert row["responded_count"] == 0

    @pytest.mark.asyncio
    async def test_error_records_once_and_never_latency_warns(
        self,
        intent_bus,
        caplog,
        monkeypatch,
    ):
        agent_id = "error-agent-full-identifier"
        intent_name = "error.intent.full"

        async def handler(intent: IntentMessage) -> IntentResult | None:
            raise RuntimeError("boom-reason")

        _install_clock(monkeypatch, 0.0, 0.0, 0.0, 31.0, 31.0)
        intent_bus.subscribe(
            agent_id,
            handler,
            latency_class=HandlerLatencyClass.COGNITIVE,
        )

        with caplog.at_level(logging.WARNING, logger="probos.mesh.intent"):
            results = await intent_bus.broadcast(
                IntentMessage(intent=intent_name), federated=False
            )

        assert len(results) == 1
        assert results[0].agent_id == agent_id
        assert results[0].success is False
        assert results[0].error == "boom-reason"
        assert len(caplog.records) == 1
        message = caplog.records[0].message
        assert "Handler error" in message
        assert f"agent_id={agent_id}" in message
        assert f"intent={intent_name}" in message
        assert "reason=boom-reason" in message
        assert "latency budget" not in message
        row = intent_bus.get_metrics()["handlers"][0]
        assert row["error_count"] == 1
        assert row["count"] == 1

    @pytest.mark.asyncio
    async def test_cancelled_invoke_propagates_without_sample_warning_or_result(
        self,
        intent_bus,
        caplog,
    ):
        started = asyncio.Event()

        async def handler(intent: IntentMessage) -> IntentResult:
            started.set()
            await asyncio.Event().wait()
            return IntentResult(intent_id=intent.id, agent_id="cancelled", success=True)

        intent = IntentMessage(intent="cancelled.intent")
        intent_bus._pending_results[intent.id] = []
        task = asyncio.create_task(
            intent_bus._invoke_handler(
                intent,
                "cancelled-agent",
                handler,
                HandlerLatencyClass.COGNITIVE,
            )
        )
        await started.wait()

        with caplog.at_level(logging.WARNING, logger="probos.mesh.intent"):
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert intent_bus._pending_results[intent.id] == []
        assert intent_bus.get_metrics()["handlers"] == []
        assert caplog.records == []

    @pytest.mark.asyncio
    async def test_broadcast_starts_handlers_concurrently_and_uses_one_task_each(
        self,
        intent_bus,
        monkeypatch,
    ):
        started: set[str] = set()
        all_started = asyncio.Event()
        release = asyncio.Event()
        created_coroutines = []
        original_create_task = intent_module.asyncio.create_task

        def tracking_create_task(coro, *args, **kwargs):
            created_coroutines.append(coro)
            return original_create_task(coro, *args, **kwargs)

        monkeypatch.setattr(intent_module.asyncio, "create_task", tracking_create_task)

        def make_handler(agent_id: str):
            async def handler(intent: IntentMessage) -> IntentResult:
                started.add(agent_id)
                if len(started) == 3:
                    all_started.set()
                await release.wait()
                return IntentResult(intent_id=intent.id, agent_id=agent_id, success=True)
            return handler

        for index in range(3):
            agent_id = f"agent-{index}"
            intent_bus.subscribe(agent_id, make_handler(agent_id), ["barrier"])

        broadcast_task = original_create_task(
            intent_bus.broadcast(IntentMessage(intent="barrier"), federated=False)
        )
        await asyncio.wait_for(all_started.wait(), timeout=1.0)
        assert started == {"agent-0", "agent-1", "agent-2"}
        assert len(created_coroutines) == 3
        release.set()
        results = await broadcast_task
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_broadcast_results_remain_completion_ordered(self, intent_bus):
        releases = {name: asyncio.Event() for name in ("first", "second", "third")}
        started = asyncio.Event()
        started_count = 0

        def make_handler(agent_id: str):
            async def handler(intent: IntentMessage) -> IntentResult:
                nonlocal started_count
                started_count += 1
                if started_count == 3:
                    started.set()
                await releases[agent_id].wait()
                return IntentResult(intent_id=intent.id, agent_id=agent_id, success=True)
            return handler

        for name in ("first", "second", "third"):
            intent_bus.subscribe(name, make_handler(name), ["ordered"])
        broadcast_task = asyncio.create_task(
            intent_bus.broadcast(IntentMessage(intent="ordered"), federated=False)
        )
        await started.wait()
        for name in ("third", "first", "second"):
            releases[name].set()
            await asyncio.sleep(0)

        results = await broadcast_task
        assert [result.agent_id for result in results] == ["third", "first", "second"]

    @pytest.mark.asyncio
    async def test_broadcast_timeout_cancels_pending_without_handler_sample(
        self,
        intent_bus,
    ):
        cancelled = asyncio.Event()

        async def fast_handler(intent: IntentMessage) -> IntentResult:
            return IntentResult(intent_id=intent.id, agent_id="fast", success=True)

        async def slow_handler(intent: IntentMessage) -> IntentResult:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return IntentResult(intent_id=intent.id, agent_id="slow", success=True)

        intent_bus.subscribe("fast", fast_handler, ["timeout"])
        intent_bus.subscribe(
            "slow",
            slow_handler,
            ["timeout"],
            latency_class=HandlerLatencyClass.COGNITIVE,
        )

        results = await intent_bus.broadcast(
            IntentMessage(intent="timeout"), timeout=0.01, federated=False
        )
        await asyncio.wait_for(cancelled.wait(), timeout=1.0)

        assert [result.agent_id for result in results] == ["fast"]
        assert [row["agent_id"] for row in intent_bus.get_metrics()["handlers"]] == [
            "fast"
        ]


# ---------------------------------------------------------------------------
# AD-637b: NATS migration tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def mock_nats_bus():
    bus = MockNATSBus()
    await bus.start()
    return bus


def _make_handler(agent_id: str, counter: dict | None = None):
    """Create a handler that returns success and optionally increments a counter."""
    async def handler(intent: IntentMessage) -> IntentResult | None:
        if counter is not None:
            counter["count"] = counter.get("count", 0) + 1
        return IntentResult(
            intent_id=intent.id,
            agent_id=agent_id,
            success=True,
            result="handled",
            confidence=0.9,
        )
    return handler


class TestIntentBusNATS:
    """AD-637b: NATS transport for send()."""

    @pytest.mark.asyncio
    async def test_send_via_nats_request_reply(self, signal_manager, mock_nats_bus):
        """Test 7: send() uses NATS request/reply when connected."""
        bus = IntentBus(signal_manager)
        bus.set_nats_bus(mock_nats_bus)

        counter: dict = {}
        bus.subscribe("agent-1", _make_handler("agent-1", counter))
        await asyncio.sleep(0)  # let ensure_future complete

        intent = IntentMessage(
            intent="test", target_agent_id="agent-1", ttl_seconds=5.0
        )
        result = await bus.send(intent)

        assert result is not None
        assert result.success
        assert result.result == "handled"
        assert result.agent_id == "agent-1"
        assert counter["count"] == 1

    @pytest.mark.asyncio
    async def test_send_fallback_when_nats_disconnected(self, signal_manager):
        """Test 8: send() falls back to direct-call when NATS not started."""
        mock_bus = MockNATSBus()  # NOT started — connected=False
        bus = IntentBus(signal_manager)
        bus.set_nats_bus(mock_bus)

        counter: dict = {}
        bus.subscribe("agent-1", _make_handler("agent-1", counter))

        intent = IntentMessage(
            intent="test", target_agent_id="agent-1", ttl_seconds=5.0
        )
        result = await bus.send(intent)

        assert result is not None
        assert result.success
        assert counter["count"] == 1

    @pytest.mark.asyncio
    async def test_send_fallback_when_no_nats(self, intent_bus):
        """Test 9: send() uses direct-call when no NATS bus wired."""
        counter: dict = {}
        intent_bus.subscribe("agent-1", _make_handler("agent-1", counter))

        intent = IntentMessage(
            intent="test", target_agent_id="agent-1", ttl_seconds=5.0
        )
        result = await intent_bus.send(intent)

        assert result is not None
        assert result.success
        assert counter["count"] == 1

    @pytest.mark.asyncio
    async def test_send_no_dual_delivery(self, signal_manager, mock_nats_bus):
        """Test 10: send() invokes handler exactly once (no dual-delivery)."""
        bus = IntentBus(signal_manager)
        bus.set_nats_bus(mock_nats_bus)

        counter: dict = {}
        bus.subscribe("agent-1", _make_handler("agent-1", counter))
        await asyncio.sleep(0)

        intent = IntentMessage(
            intent="test", target_agent_id="agent-1", ttl_seconds=5.0
        )
        await bus.send(intent)

        assert counter["count"] == 1  # exactly once, not twice

    @pytest.mark.asyncio
    async def test_nats_subscribe_creates_subscription(self, signal_manager, mock_nats_bus):
        """Test 11: subscribe() creates NATS subscription when NATS is available."""
        bus = IntentBus(signal_manager)
        bus.set_nats_bus(mock_nats_bus)

        bus.subscribe("agent-1", _make_handler("agent-1"))
        # AD-637z: tasks are tracked in _pending_sub_tasks, drain them
        if bus._pending_sub_tasks:
            await asyncio.gather(*bus._pending_sub_tasks, return_exceptions=True)

        # AD-637z: NATSBus now owns subscription tracking via _active_subs
        assert any(e["subject"] == "intent.agent-1" for e in mock_nats_bus._active_subs)

    @pytest.mark.asyncio
    async def test_unsubscribe_cleans_nats_subscription(self, signal_manager, mock_nats_bus):
        """Test 12: unsubscribe() removes NATS subscription."""
        bus = IntentBus(signal_manager)
        bus.set_nats_bus(mock_nats_bus)

        bus.subscribe("agent-1", _make_handler("agent-1"))
        if bus._pending_sub_tasks:
            await asyncio.gather(*bus._pending_sub_tasks, return_exceptions=True)

        # AD-637z: NATSBus tracks the subscription
        assert any(e["subject"] == "intent.agent-1" for e in mock_nats_bus._active_subs)
        bus.unsubscribe("agent-1")
        # Drain unsub task
        if bus._pending_sub_tasks:
            await asyncio.gather(*bus._pending_sub_tasks, return_exceptions=True)
        assert not any(e["subject"] == "intent.agent-1" for e in mock_nats_bus._active_subs)

    @pytest.mark.asyncio
    async def test_publish_alias_calls_broadcast(self, intent_bus):
        """Test 13: publish() delegates to broadcast()."""
        counter: dict = {}
        intent_bus.subscribe("agent-1", _make_handler("agent-1", counter))

        intent = IntentMessage(intent="test", ttl_seconds=5.0)
        results = await intent_bus.publish(intent)

        assert len(results) == 1
        assert results[0].success
        assert counter["count"] == 1

    @pytest.mark.asyncio
    async def test_publish_targeted_delegates_to_send(self, intent_bus):
        """Test 14: publish() with target_agent_id delegates through broadcast→send."""
        counter: dict = {}
        intent_bus.subscribe("agent-1", _make_handler("agent-1", counter))

        intent = IntentMessage(
            intent="test", target_agent_id="agent-1", ttl_seconds=5.0
        )
        results = await intent_bus.publish(intent)

        assert len(results) == 1
        assert results[0].success
        assert counter["count"] == 1

    @pytest.mark.asyncio
    async def test_intent_serialization_roundtrip(self):
        """Test 15: IntentMessage serialization round-trip."""
        original = IntentMessage(
            intent="analyze",
            params={"key": "value", "count": 42},
            urgency=0.8,
            context="test context",
            ttl_seconds=30.0,
            target_agent_id="agent-x",
        )
        serialized = IntentBus._serialize_intent(original)
        restored = IntentBus._deserialize_intent(serialized)

        assert restored.intent == original.intent
        assert restored.params == original.params
        assert restored.urgency == original.urgency
        assert restored.context == original.context
        assert restored.ttl_seconds == original.ttl_seconds
        assert restored.id == original.id
        assert restored.target_agent_id == original.target_agent_id
        assert restored.created_at.isoformat() == original.created_at.isoformat()

    @pytest.mark.asyncio
    async def test_result_serialization_roundtrip(self):
        """Test 16: IntentResult serialization round-trip."""
        original = IntentResult(
            intent_id="abc123",
            agent_id="agent-1",
            success=True,
            result="analysis complete",
            error=None,
            confidence=0.95,
        )
        serialized = IntentBus._serialize_result(original)
        restored = IntentBus._deserialize_result(serialized)

        assert restored.intent_id == original.intent_id
        assert restored.agent_id == original.agent_id
        assert restored.success == original.success
        assert restored.result == original.result
        assert restored.error == original.error
        assert restored.confidence == original.confidence
        assert restored.timestamp.isoformat() == original.timestamp.isoformat()

    @pytest.mark.asyncio
    async def test_broadcast_still_uses_direct_call(self, signal_manager, mock_nats_bus):
        """Test 17: broadcast() still uses direct-call even with NATS connected."""
        bus = IntentBus(signal_manager)
        bus.set_nats_bus(mock_nats_bus)

        counter: dict = {}
        bus.subscribe("agent-1", _make_handler("agent-1", counter))
        await asyncio.sleep(0)

        intent = IntentMessage(intent="test", ttl_seconds=5.0)
        results = await bus.broadcast(intent, timeout=2.0)

        assert len(results) == 1
        assert results[0].success
        assert counter["count"] == 1

    @pytest.mark.asyncio
    async def test_set_nats_bus_wires_reference(self, signal_manager):
        """Test 18: set_nats_bus() wires the reference."""
        bus = IntentBus(signal_manager)
        assert bus._nats_bus is None

        mock = MockNATSBus()
        bus.set_nats_bus(mock)
        assert bus._nats_bus is mock

    @pytest.mark.asyncio
    async def test_set_federation_handler(self, signal_manager):
        """Test 19: set_federation_handler() sets _federation_fn and it's called on federated broadcast."""
        bus = IntentBus(signal_manager)
        fed_calls: list = []

        async def mock_federation(intent: IntentMessage) -> list[IntentResult]:
            fed_calls.append(intent)
            return [
                IntentResult(
                    intent_id=intent.id,
                    agent_id="remote-agent",
                    success=True,
                    result="from-federation",
                    confidence=0.7,
                )
            ]

        bus.set_federation_handler(mock_federation)
        assert bus._federation_fn is mock_federation

        intent = IntentMessage(intent="test", ttl_seconds=5.0)
        results = await bus.broadcast(intent, timeout=2.0, federated=True)

        assert len(fed_calls) == 1
        assert any(r.agent_id == "remote-agent" for r in results)
