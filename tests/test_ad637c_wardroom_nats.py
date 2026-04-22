"""AD-637c: Ward Room Event Emission → NATS JetStream tests."""

import asyncio
import time

import pytest

from probos.mesh.nats_bus import MockNATSBus


@pytest.fixture
async def mock_nats_bus():
    bus = MockNATSBus()
    await bus.start()
    return bus


def _build_ward_room_emit(emit_event_fn, nats_bus, router_ref, semaphore):
    """Build the _ward_room_emit callback as production communication.py does."""
    _wardroom_publish_tasks: set[asyncio.Task] = set()

    def _ward_room_emit(event_type: str, data: dict) -> None:
        emit_event_fn(event_type, data)

        if nats_bus and nats_bus.connected:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            payload = {"event_type": event_type, **data}
            subject = f"wardroom.events.{event_type}"
            task = loop.create_task(nats_bus.js_publish(subject, payload))
            _wardroom_publish_tasks.add(task)
            task.add_done_callback(_wardroom_publish_tasks.discard)
        else:
            router = router_ref[0]
            if router:
                async def _bounded_route() -> None:
                    async with semaphore:
                        await router.route_event_coalesced(event_type, data)
                asyncio.create_task(_bounded_route())

    return _ward_room_emit


class _MockRouter:
    """Mock WardRoomRouter for testing."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def route_event_coalesced(self, event_type: str, data: dict) -> None:
        self.calls.append((event_type, data))


class TestWardRoomNATSEmission:
    """AD-637c: Ward Room event emission via NATS JetStream."""

    @pytest.mark.asyncio
    async def test_wardroom_event_publishes_to_jetstream(self, mock_nats_bus):
        """Test 1: When NATS is connected, ward room emit publishes to JetStream."""
        ws_events: list = []
        emit = _build_ward_room_emit(
            lambda et, d: ws_events.append((et, d)),
            mock_nats_bus,
            [None],
            asyncio.Semaphore(10),
        )

        emit("ward_room_post_created", {"thread_id": "t1", "post_id": "p1"})
        await asyncio.sleep(0)  # let task run

        # WebSocket event emitted
        assert len(ws_events) == 1

        # JetStream published
        assert len(mock_nats_bus.published) == 1
        subject, payload = mock_nats_bus.published[0]
        assert "wardroom.events.ward_room_post_created" in subject
        assert payload["event_type"] == "ward_room_post_created"
        assert payload["thread_id"] == "t1"

    @pytest.mark.asyncio
    async def test_wardroom_fallback_when_nats_disconnected(self):
        """Test 2: When NATS is not connected, falls back to create_task dispatch."""
        mock_bus = MockNATSBus()  # NOT started — connected=False
        mock_router = _MockRouter()
        router_ref: list = [mock_router]

        ws_events: list = []
        emit = _build_ward_room_emit(
            lambda et, d: ws_events.append((et, d)),
            mock_bus,
            router_ref,
            asyncio.Semaphore(10),
        )

        emit("ward_room_post_created", {"thread_id": "t1"})
        await asyncio.sleep(0)  # let create_task run

        assert len(ws_events) == 1
        assert len(mock_bus.published) == 0
        assert len(mock_router.calls) == 1
        assert mock_router.calls[0] == ("ward_room_post_created", {"thread_id": "t1"})

    @pytest.mark.asyncio
    async def test_no_dual_delivery_with_counter(self, mock_nats_bus):
        """Test 3: Events go through JetStream OR fallback, never both."""
        mock_router = _MockRouter()
        # Even if router_ref is set, NATS path should be used exclusively
        router_ref: list = [mock_router]

        ws_events: list = []
        emit = _build_ward_room_emit(
            lambda et, d: ws_events.append((et, d)),
            mock_nats_bus,
            router_ref,
            asyncio.Semaphore(10),
        )

        for i in range(5):
            emit("ward_room_post_created", {"n": i})
        await asyncio.sleep(0)

        assert len(mock_nats_bus.published) == 5  # all via NATS
        assert len(mock_router.calls) == 0  # none via fallback

    @pytest.mark.asyncio
    async def test_router_receives_via_jetstream_consumer(self, mock_nats_bus):
        """Test 4: Router receives events through JetStream subscription."""
        await mock_nats_bus.ensure_stream(
            "WARDROOM", ["wardroom.events.>"], max_msgs=10000, max_age=3600
        )

        received: list = []

        async def on_event(msg):
            event_type = msg.data.get("event_type", "")
            data = {k: v for k, v in msg.data.items() if k != "event_type"}
            received.append((event_type, data))

        await mock_nats_bus.js_subscribe(
            "wardroom.events.>", on_event,
            durable="wardroom-router", stream="WARDROOM",
            max_ack_pending=10, ack_wait=120,
        )

        await mock_nats_bus.publish(
            "wardroom.events.ward_room_post_created",
            {"event_type": "ward_room_post_created", "thread_id": "t1", "content": "hello"},
        )

        assert len(received) == 1
        assert received[0][0] == "ward_room_post_created"
        assert received[0][1] == {"thread_id": "t1", "content": "hello"}

    @pytest.mark.asyncio
    async def test_js_subscribe_consumer_config_parameters(self):
        """Test 5: js_subscribe accepts max_ack_pending and ack_wait without error."""
        bus = MockNATSBus()
        await bus.start()

        received: list = []

        async def handler(msg):
            received.append(msg)

        sub = await bus.js_subscribe(
            "test.>", handler, durable="test-consumer",
            max_ack_pending=10, ack_wait=120,
        )
        assert sub is not None

    @pytest.mark.asyncio
    async def test_wardroom_stream_ensure_config(self, mock_nats_bus):
        """Test 6: WARDROOM stream is created with correct config."""
        await mock_nats_bus.ensure_stream(
            "WARDROOM", ["wardroom.events.>"], max_msgs=10000, max_age=3600
        )

        assert "WARDROOM" in mock_nats_bus._streams
        stream = mock_nats_bus._streams["WARDROOM"]
        assert stream["subjects"] == ["probos.test.wardroom.events.>"]
        assert stream["max_msgs"] == 10000
        assert stream["max_age"] == 3600

    @pytest.mark.asyncio
    async def test_wardroom_event_payload_includes_event_type(self, mock_nats_bus):
        """Test 7: JetStream payload includes event_type field."""
        ws_events: list = []
        emit = _build_ward_room_emit(
            lambda et, d: ws_events.append((et, d)),
            mock_nats_bus,
            [None],
            asyncio.Semaphore(10),
        )

        emit("ward_room_thread_created", {"thread_id": "t2", "channel_id": "c1"})
        await asyncio.sleep(0)

        assert len(mock_nats_bus.published) == 1
        _, payload = mock_nats_bus.published[0]
        assert payload["event_type"] == "ward_room_thread_created"
        assert payload["thread_id"] == "t2"
        assert payload["channel_id"] == "c1"

    @pytest.mark.asyncio
    async def test_end_to_end_post_to_consumer_callback(self, mock_nats_bus):
        """Test 8: End-to-end: event published → consumer callback receives with correct extraction."""
        await mock_nats_bus.ensure_stream(
            "WARDROOM", ["wardroom.events.>"], max_msgs=10000, max_age=3600
        )

        received: list = []

        async def on_event(msg):
            event_type = msg.data.get("event_type", "")
            data = {k: v for k, v in msg.data.items() if k != "event_type"}
            received.append((event_type, data))

        await mock_nats_bus.js_subscribe(
            "wardroom.events.>", on_event,
            durable="wardroom-router", stream="WARDROOM",
        )

        # Publish as the emit callback would
        await mock_nats_bus.js_publish(
            "wardroom.events.ward_room_post_created",
            {"event_type": "ward_room_post_created", "thread_id": "t1", "content": "hello"},
        )

        assert len(received) == 1
        event_type, data = received[0]
        assert event_type == "ward_room_post_created"
        assert "thread_id" in data
        assert "content" in data
        assert "event_type" not in data

    @pytest.mark.asyncio
    async def test_router_ref_not_wired_when_nats_connected(self):
        """Test 9: When NATS is connected, _ward_room_router_ref[0] stays None (structural no-dual-delivery)."""
        # Simulate finalize wiring logic
        nats_bus = MockNATSBus()
        await nats_bus.start()  # connected=True

        router_ref: list = [None]
        mock_router = _MockRouter()

        # AD-637c logic: only wire when NATS is NOT connected
        if not (nats_bus and nats_bus.connected):
            router_ref[0] = mock_router

        assert router_ref[0] is None  # Not wired — structural enforcement

        # Now test with NATS disconnected
        nats_bus_off = MockNATSBus()  # NOT started

        router_ref_2: list = [None]
        if not (nats_bus_off and nats_bus_off.connected):
            router_ref_2[0] = mock_router

        assert router_ref_2[0] is mock_router  # Wired — fallback active

    @pytest.mark.asyncio
    async def test_redelivery_handled_gracefully(self, mock_nats_bus):
        """Test 10: Duplicate events (at-least-once redelivery) don't crash the consumer."""
        mock_router = _MockRouter()

        async def on_event(msg):
            event_type = msg.data.get("event_type", "")
            data = {k: v for k, v in msg.data.items() if k != "event_type"}
            await mock_router.route_event_coalesced(event_type, data)

        await mock_nats_bus.js_subscribe("wardroom.events.>", on_event)

        # Simulate redelivery — same event twice
        event = {"event_type": "ward_room_post_created", "thread_id": "t1", "post_id": "p1"}
        await mock_nats_bus.publish("wardroom.events.ward_room_post_created", event)
        await mock_nats_bus.publish("wardroom.events.ward_room_post_created", event)

        # Router receives both — its own deduplication handles it
        assert len(mock_router.calls) == 2
        assert mock_router.calls[0] == mock_router.calls[1]

    @pytest.mark.asyncio
    async def test_emit_returns_immediately(self, mock_nats_bus):
        """Test 11: Emit is non-blocking — core user-facing benefit of JetStream."""
        # Subscribe a slow consumer
        async def slow_handler(msg):
            await asyncio.sleep(2.0)

        await mock_nats_bus.js_subscribe("wardroom.events.>", slow_handler)

        ws_events: list = []
        emit = _build_ward_room_emit(
            lambda et, d: ws_events.append((et, d)),
            mock_nats_bus,
            [None],
            asyncio.Semaphore(10),
        )

        t0 = time.monotonic()
        for i in range(10):
            emit("ward_room_post_created", {"n": i})
        elapsed = time.monotonic() - t0

        # All 10 emits should complete in well under 200ms
        # (they just create tasks, don't await slow handler)
        assert elapsed < 0.2
        assert len(ws_events) == 10
