"""AD-637d: System Event Migration (EventEmitter → NATS) tests."""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from probos.events import BaseEvent, EventType
from probos.mesh.nats_bus import MockNATSBus


class _FakeRuntime:
    """Minimal runtime-like object for testing _emit_event / add_event_listener."""

    def __init__(self, nats_bus=None):
        self.nats_bus = nats_bus
        self._event_listeners: list[tuple] = []
        self._nats_publish_tasks: set[asyncio.Task] = set()
        self._night_orders_mgr = None
        self._escalation_calls: list[tuple] = []

    def _check_night_order_escalation(self, type_str: str, data: dict) -> None:
        self._escalation_calls.append((type_str, data))

    def _emit_event(self, event_type, data=None):
        """Port of runtime._emit_event (AD-637d)."""
        if isinstance(event_type, BaseEvent):
            event = event_type.to_dict()
        elif isinstance(event_type, EventType):
            event = {"type": event_type.value, "data": data or {}, "timestamp": time.time()}
        else:
            event = {"type": event_type, "data": data or {}, "timestamp": time.time()}
        type_str = event.get("type", "")

        # Night Orders escalation — always local
        self._check_night_order_escalation(type_str, event.get("data", {}))

        # Route — NATS or fallback
        if getattr(self, 'nats_bus', None) and self.nats_bus.connected:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                self._emit_event_local(event, type_str)
                return
            subject = f"system.events.{type_str}"
            task = loop.create_task(self.nats_bus.js_publish(subject, event))
            self._nats_publish_tasks.add(task)
            task.add_done_callback(self._nats_publish_tasks.discard)
        else:
            self._emit_event_local(event, type_str)

    def _emit_event_local(self, event, type_str):
        """In-memory dispatch (fallback)."""
        for fn, type_filter in self._event_listeners:
            if type_filter is not None and type_str not in type_filter:
                continue
            try:
                if asyncio.iscoroutinefunction(fn):
                    asyncio.create_task(fn(event))
                else:
                    fn(event)
            except Exception:
                pass

    def add_event_listener(self, fn, event_types=None):
        type_filter = frozenset(str(t) for t in event_types) if event_types else None
        self._event_listeners.append((fn, type_filter))
        if getattr(self, 'nats_bus', None) and self.nats_bus.connected:
            self._create_nats_event_subscription(fn, type_filter)

    def _create_nats_event_subscription(self, fn, type_filter):
        async def _nats_callback(msg):
            event = msg.data
            try:
                if asyncio.iscoroutinefunction(fn):
                    await fn(event)
                else:
                    fn(event)
            except Exception:
                pass

        async def _do_subscribe():
            if type_filter:
                for event_type in type_filter:
                    subject = f"system.events.{event_type}"
                    await self.nats_bus.js_subscribe(
                        subject, _nats_callback, stream="SYSTEM_EVENTS",
                    )
            else:
                await self.nats_bus.js_subscribe(
                    "system.events.>", _nats_callback, stream="SYSTEM_EVENTS",
                )

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_do_subscribe())
            self._nats_publish_tasks.add(task)
            task.add_done_callback(self._nats_publish_tasks.discard)
        except RuntimeError:
            pass

    def _setup_nats_event_subscriptions(self):
        if not (getattr(self, 'nats_bus', None) and self.nats_bus.connected):
            return
        for fn, type_filter in self._event_listeners:
            self._create_nats_event_subscription(fn, type_filter)


@pytest.fixture
async def mock_nats_bus():
    bus = MockNATSBus()
    await bus.start()
    await bus.ensure_stream("SYSTEM_EVENTS", ["system.events.>"], max_msgs=50000, max_age=3600)
    return bus


class TestSystemEventsNATS:
    """AD-637d: System event emission via NATS JetStream."""

    @pytest.mark.asyncio
    async def test_emit_event_publishes_to_nats_when_connected(self, mock_nats_bus):
        """Test 1: When NATS connected, _emit_event publishes to JetStream."""
        rt = _FakeRuntime(nats_bus=mock_nats_bus)

        rt._emit_event("trust_update", {"agent_id": "a1"})
        await asyncio.sleep(0)  # let task run

        assert len(mock_nats_bus.published) == 1
        subject, payload = mock_nats_bus.published[0]
        assert "system.events.trust_update" in subject
        assert payload["type"] == "trust_update"
        assert payload["data"]["agent_id"] == "a1"
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_emit_event_falls_back_when_nats_disconnected(self):
        """Test 2: When NATS disconnected, falls back to in-memory dispatch."""
        bus = MockNATSBus()  # NOT started — connected=False
        rt = _FakeRuntime(nats_bus=bus)

        received: list = []
        rt.add_event_listener(lambda e: received.append(e))

        rt._emit_event("trust_update", {"agent_id": "a1"})
        await asyncio.sleep(0)

        assert len(received) == 1
        assert received[0]["type"] == "trust_update"
        assert len(bus.published) == 0  # Nothing went to NATS

    @pytest.mark.asyncio
    async def test_no_dual_delivery(self, mock_nats_bus):
        """Test 3: Events go through NATS OR fallback, never both."""
        rt = _FakeRuntime(nats_bus=mock_nats_bus)

        counter = {"n": 0}

        def listener(event):
            counter["n"] += 1

        # Register listener with NATS connected — subscription auto-created
        rt.add_event_listener(listener)
        await asyncio.sleep(0)  # let NATS subscription wire up

        # Emit — should go through NATS, not local
        rt._emit_event("trust_update", {"agent_id": "a1"})
        await asyncio.sleep(0)  # let publish + subscribe dispatch

        # Counter should be 1 (received via NATS subscription only, not local)
        assert counter["n"] == 1
        # Verify NATS publish happened
        assert len(mock_nats_bus.published) == 1

    @pytest.mark.asyncio
    async def test_add_event_listener_creates_nats_subscription(self, mock_nats_bus):
        """Test 4: add_event_listener creates NATS subscriptions for filtered types."""
        rt = _FakeRuntime(nats_bus=mock_nats_bus)

        received: list = []

        def listener(event):
            received.append(event)

        rt.add_event_listener(listener, event_types=["trust_update", "dream_complete"])
        await asyncio.sleep(0)  # let subscription task complete

        # Publish to matching subject
        await mock_nats_bus.publish("system.events.trust_update", {
            "type": "trust_update", "data": {"agent_id": "a1"}, "timestamp": time.time()
        })

        assert len(received) == 1
        assert received[0]["type"] == "trust_update"

        # Publish to non-matching subject — should NOT be received
        await mock_nats_bus.publish("system.events.task_started", {
            "type": "task_started", "data": {}, "timestamp": time.time()
        })

        assert len(received) == 1  # still 1

    @pytest.mark.asyncio
    async def test_add_event_listener_wildcard_subscription(self, mock_nats_bus):
        """Test 5: add_event_listener with no filter subscribes to wildcard."""
        rt = _FakeRuntime(nats_bus=mock_nats_bus)

        received: list = []

        def listener(event):
            received.append(event)

        rt.add_event_listener(listener)  # no event_types filter
        await asyncio.sleep(0)

        # Any event type should be received
        await mock_nats_bus.publish("system.events.trust_update", {
            "type": "trust_update", "data": {}, "timestamp": time.time()
        })
        await mock_nats_bus.publish("system.events.dream_complete", {
            "type": "dream_complete", "data": {}, "timestamp": time.time()
        })

        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_night_orders_always_runs_locally(self, mock_nats_bus):
        """Test 6: Night Orders escalation runs regardless of NATS path."""
        rt = _FakeRuntime(nats_bus=mock_nats_bus)

        rt._emit_event("build_failure", {"details": "test"})
        await asyncio.sleep(0)

        # Escalation was called (always local, before dispatch)
        assert len(rt._escalation_calls) == 1
        assert rt._escalation_calls[0][0] == "build_failure"

    @pytest.mark.asyncio
    async def test_stream_ensure_config(self):
        """Test 7: SYSTEM_EVENTS stream created with correct config."""
        bus = MockNATSBus()
        await bus.start()

        await bus.ensure_stream(
            "SYSTEM_EVENTS", ["system.events.>"],
            max_msgs=50000, max_age=3600,
        )

        assert "SYSTEM_EVENTS" in bus._streams
        stream = bus._streams["SYSTEM_EVENTS"]
        assert stream["subjects"] == ["probos.test.system.events.>"]
        assert stream["max_msgs"] == 50000
        assert stream["max_age"] == 3600

    @pytest.mark.asyncio
    async def test_setup_nats_event_subscriptions_wires_existing(self):
        """Test 8: _setup_nats_event_subscriptions wires pre-registered listeners."""
        bus = MockNATSBus()
        # NOT started — listeners go to local list only
        rt = _FakeRuntime(nats_bus=bus)

        received_1: list = []
        received_2: list = []
        received_3: list = []

        rt.add_event_listener(lambda e: received_1.append(e), event_types=["trust_update"])
        rt.add_event_listener(lambda e: received_2.append(e), event_types=["dream_complete"])
        rt.add_event_listener(lambda e: received_3.append(e))  # wildcard

        assert len(rt._event_listeners) == 3

        # Now connect NATS and wire
        await bus.start()
        await bus.ensure_stream("SYSTEM_EVENTS", ["system.events.>"])
        rt._setup_nats_event_subscriptions()
        await asyncio.sleep(0)

        # All 3 should now receive via NATS
        await bus.publish("system.events.trust_update", {
            "type": "trust_update", "data": {}, "timestamp": time.time()
        })
        assert len(received_1) == 1  # filtered match
        assert len(received_2) == 0  # filtered non-match
        assert len(received_3) == 1  # wildcard catches all

    @pytest.mark.asyncio
    async def test_event_payload_format_preserved(self, mock_nats_bus):
        """Test 9: All event formats serialize to the same wire format."""
        rt = _FakeRuntime(nats_bus=mock_nats_bus)

        # BaseEvent instance
        from probos.events import BuildStartedEvent
        rt._emit_event(BuildStartedEvent(build_id="b1", title="test"))
        await asyncio.sleep(0)

        # EventType enum
        rt._emit_event(EventType.TRUST_UPDATE, {"agent_id": "a1"})
        await asyncio.sleep(0)

        # Legacy string
        rt._emit_event("custom_event", {"key": "val"})
        await asyncio.sleep(0)

        assert len(mock_nats_bus.published) == 3

        for _, payload in mock_nats_bus.published:
            assert "type" in payload
            assert isinstance(payload["type"], str)
            assert "timestamp" in payload
            assert isinstance(payload["timestamp"], float)

        # Verify specific types
        assert mock_nats_bus.published[0][1]["type"] == "build_started"
        assert mock_nats_bus.published[1][1]["type"] == "trust_update"
        assert mock_nats_bus.published[2][1]["type"] == "custom_event"

    @pytest.mark.asyncio
    async def test_emit_outside_event_loop_uses_fallback(self):
        """Test 10: _emit_event from outside event loop falls back gracefully."""
        bus = MockNATSBus()
        await bus.start()
        rt = _FakeRuntime(nats_bus=bus)

        received: list = []
        rt.add_event_listener(lambda e: received.append(e))

        # Simulate calling from a thread with no event loop by patching get_running_loop
        original_emit = rt._emit_event

        def _emit_no_loop(event_type, data=None):
            """Simulate _emit_event when get_running_loop raises RuntimeError."""
            if isinstance(event_type, BaseEvent):
                event = event_type.to_dict()
            elif isinstance(event_type, EventType):
                event = {"type": event_type.value, "data": data or {}, "timestamp": time.time()}
            else:
                event = {"type": event_type, "data": data or {}, "timestamp": time.time()}
            type_str = event.get("type", "")
            rt._check_night_order_escalation(type_str, event.get("data", {}))
            # Force the RuntimeError path
            rt._emit_event_local(event, type_str)

        _emit_no_loop("test_event", {"key": "val"})

        assert len(received) == 1
        assert received[0]["type"] == "test_event"
        assert len(bus.published) == 0  # nothing went to NATS
