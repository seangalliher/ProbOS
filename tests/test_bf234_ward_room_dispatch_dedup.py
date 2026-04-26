"""BF-234: Consumer-side dedup gate for ward_room_notification dispatch."""

import logging
import time

import pytest
from unittest.mock import AsyncMock, MagicMock

from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage


@pytest.fixture
def bus():
    """Create an IntentBus with a real SignalManager."""
    return IntentBus(SignalManager())


def _make_intent(intent_type: str = "ward_room_notification", **kwargs):
    """Helper to create an IntentMessage with defaults."""
    return IntentMessage(
        intent=intent_type,
        params=kwargs.pop("params", {"thread_id": "t1"}),
        target_agent_id=kwargs.pop("target_agent_id", "agent-1"),
        **kwargs,
    )


def _make_mock_msg(bus_instance, intent_msg):
    """Create a mock NATS JetStream message from an IntentMessage."""
    msg = MagicMock()
    msg.data = bus_instance._serialize_intent(intent_msg)
    msg.ack = AsyncMock()
    msg.term = AsyncMock()
    msg.nak = AsyncMock()
    return msg


async def _get_dispatch_callback(bus_instance, agent_id="agent-1"):
    """Subscribe an agent via _js_subscribe_agent_dispatch and capture the callback."""
    handler = AsyncMock()
    bus_instance._nats_bus = MagicMock()
    bus_instance._nats_bus.js_subscribe = AsyncMock(return_value=MagicMock())
    await bus_instance._js_subscribe_agent_dispatch(agent_id, handler)
    callback = bus_instance._nats_bus.js_subscribe.call_args.args[1]
    return callback, handler


# ── Test 1 ────────────────────────────────────────────────────────────

def test_dedup_blocks_second_intent(bus):
    """First-seen intent passes; second is flagged as duplicate."""
    bus._record_seen_intent("intent-1")
    assert bus._is_duplicate_intent("intent-1") is True
    assert bus._is_duplicate_intent("intent-2") is False


# ── Test 2 ────────────────────────────────────────────────────────────

def test_dedup_expires_after_window(bus):
    """Intent seen beyond the dedup window is not a duplicate."""
    bus._record_seen_intent("intent-1")
    # Force timestamp to be beyond the 300s window
    bus._seen_intents["intent-1"] = time.monotonic() - 301.0
    assert bus._is_duplicate_intent("intent-1") is False


# ── Test 3 ────────────────────────────────────────────────────────────

def test_eviction_removes_stale_entries(bus):
    """Eviction removes entries older than max_age, keeps recent ones."""
    now = time.monotonic()
    # 3 stale entries
    for i in range(3):
        bus._seen_intents[f"stale-{i}"] = now - 15.0
    # 2 fresh entries
    for i in range(2):
        bus._seen_intents[f"fresh-{i}"] = now

    bus._evict_stale_seen_intents(max_age=10.0)
    assert len(bus._seen_intents) == 2
    assert all(k.startswith("fresh-") for k in bus._seen_intents)


# ── Test 4 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_on_dispatch_suppresses_duplicate_ward_room_notification(bus):
    """Duplicate ward_room_notification is ack'd and dropped — handler never runs."""
    callback, handler = await _get_dispatch_callback(bus)
    bus._record_response = MagicMock()

    intent_msg = _make_intent()
    bus._record_seen_intent(intent_msg.id)  # pre-record → duplicate

    msg = _make_mock_msg(bus, intent_msg)
    await callback(msg)

    msg.ack.assert_awaited_once()
    msg.term.assert_not_awaited()
    bus._record_response.assert_not_called()
    handler.assert_not_awaited()
    assert bus._duplicate_suppressed_count == 1


# ── Test 5 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_on_dispatch_allows_first_ward_room_notification(bus):
    """First ward_room_notification is enqueued normally."""
    callback, handler = await _get_dispatch_callback(bus)
    bus._record_response = MagicMock()

    mock_queue = MagicMock()
    mock_queue.enqueue = MagicMock(return_value=True)
    bus.register_queue("agent-1", mock_queue)

    intent_msg = _make_intent()
    msg = _make_mock_msg(bus, intent_msg)
    await callback(msg)

    mock_queue.enqueue.assert_called_once()
    bus._record_response.assert_called_once()
    assert bus._duplicate_suppressed_count == 0
    assert intent_msg.id in bus._seen_intents


# ── Test 6 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_on_dispatch_skips_dedup_for_non_ward_room_intent(bus):
    """Non-ward_room intents bypass the dedup gate even if intent ID was seen."""
    callback, handler = await _get_dispatch_callback(bus)
    bus._record_response = MagicMock()

    intent_msg = _make_intent(intent_type="some_other_intent")
    bus._record_seen_intent(intent_msg.id)  # pre-record — should be ignored

    # No queue → falls through to direct handler dispatch
    msg = _make_mock_msg(bus, intent_msg)
    await callback(msg)

    handler.assert_awaited_once()
    msg.ack.assert_awaited_once()
    assert bus._duplicate_suppressed_count == 0


# ── Test 7 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dedup_emits_event_on_hit(bus):
    """Duplicate suppression emits a telemetry event."""
    callback, _ = await _get_dispatch_callback(bus)
    bus._record_response = MagicMock()
    bus._emit_event_fn = MagicMock()

    intent_msg = _make_intent()
    bus._record_seen_intent(intent_msg.id)

    msg = _make_mock_msg(bus, intent_msg)
    await callback(msg)

    bus._emit_event_fn.assert_called_once()
    event_name, event_data = bus._emit_event_fn.call_args.args
    assert event_name == "wardroom.dispatch.duplicate_suppressed"
    assert "agent_id" in event_data
    assert "thread_id" in event_data
    assert "intent_id" in event_data
    assert "age_ms" in event_data


# ── Test 8 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dedup_logs_warning_on_hit(bus, caplog):
    """Duplicate suppression logs a BF-234 warning."""
    callback, _ = await _get_dispatch_callback(bus)
    bus._record_response = MagicMock()

    intent_msg = _make_intent()
    bus._record_seen_intent(intent_msg.id)

    msg = _make_mock_msg(bus, intent_msg)
    with caplog.at_level(logging.WARNING):
        await callback(msg)

    assert "BF-234" in caplog.text
    assert "Suppressed duplicate" in caplog.text


# ── Test 9 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_suppressed_counter(bus):
    """Counter increments for each duplicate suppression."""
    callback, _ = await _get_dispatch_callback(bus)
    bus._record_response = MagicMock()

    intent_msg = _make_intent()
    bus._record_seen_intent(intent_msg.id)

    msg = _make_mock_msg(bus, intent_msg)
    for _ in range(3):
        await callback(msg)

    assert bus.get_duplicate_suppressed_count() == 3


# ── Test 10 ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_path_latency(bus):
    """Duplicate suppression path completes in < 1ms."""
    callback, _ = await _get_dispatch_callback(bus)
    bus._record_response = MagicMock()

    intent_msg = _make_intent()
    bus._record_seen_intent(intent_msg.id)

    msg = _make_mock_msg(bus, intent_msg)
    t0 = time.monotonic()
    await callback(msg)
    elapsed = time.monotonic() - t0

    assert elapsed < 0.001, f"Duplicate path took {elapsed*1000:.1f}ms, expected <1ms"


# ── Test 11 ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_msg_nak_not_called_on_duplicate(bus):
    """Duplicate messages are ack'd, never nak'd (would cause redelivery loop)."""
    callback, _ = await _get_dispatch_callback(bus)
    bus._record_response = MagicMock()

    intent_msg = _make_intent()
    bus._record_seen_intent(intent_msg.id)

    msg = _make_mock_msg(bus, intent_msg)
    await callback(msg)

    msg.nak.assert_not_awaited()
    msg.ack.assert_awaited_once()
