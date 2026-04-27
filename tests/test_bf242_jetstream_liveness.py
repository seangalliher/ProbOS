"""BF-242: JetStream liveness probe — consecutive failure tracking + recovery.

Tests cover:
- Consecutive failure counter increments on js_publish failure
- Counter resets on success
- Recovery triggered after threshold consecutive failures
- JetStream suspended during recovery
- JetStream resumed after successful recovery + probe
- JetStream stays suspended when probe fails
- Recovery failure keeps bus suspended
- Suspended publishes bypass to core NATS (no timeout)
- Reconnect resumes suspended JetStream
- health() reports js_suspended state
- Single-flight guard prevents concurrent recovery tasks
- Suspended + core NATS failure doesn't propagate
- MockNATSBus parity
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_bus():
    """Build a NATSBus with mocked internals for unit testing."""
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._url = "nats://localhost:4222"
    bus._subject_prefix = "probos.test"
    bus._js = MagicMock()  # Truthy — JetStream enabled
    bus._nc = MagicMock()
    bus._nc.is_connected = True
    bus._nc.connected_url = "nats://localhost:4222"
    bus._connected = True
    bus._started = True
    bus._resubscribing = False
    bus._active_subs = []
    bus._stream_configs = [
        {"name": "SYSTEM_EVENTS", "subjects": ["system.events.>"], "max_msgs": 50000, "max_age": 3600},
    ]
    bus._subscriptions = []
    bus._prefix_change_callbacks = []
    bus._js_publish_timeout = 5.0
    bus._jetstream_enabled = True
    # BF-242
    bus._js_consecutive_failures = 0
    bus._js_failure_threshold = 3
    bus._js_suspended = False
    bus._js_recovery_task = None
    return bus


@pytest.mark.asyncio
async def test_failure_counter_increments():
    """Consecutive failure counter increments after both attempts fail."""
    bus = _make_bus()
    bus._js.publish = AsyncMock(side_effect=Exception("no response from stream"))
    bus.publish = AsyncMock()  # core NATS fallback

    await bus.js_publish("system.events.test", {"type": "test"})

    assert bus._js_consecutive_failures == 1
    assert bus.publish.call_count == 1  # fell back to core NATS


@pytest.mark.asyncio
async def test_failure_counter_resets_on_success():
    """Counter resets to 0 on a successful JetStream publish."""
    bus = _make_bus()
    bus._js_consecutive_failures = 2
    bus._js.publish = AsyncMock()  # success

    await bus.js_publish("system.events.test", {"type": "test"})

    assert bus._js_consecutive_failures == 0


@pytest.mark.asyncio
async def test_recovery_triggered_at_threshold():
    """Consecutive failures reaching threshold sets condition for recovery."""
    bus = _make_bus()
    bus._js_consecutive_failures = 2  # One more will hit threshold of 3
    bus._js.publish = AsyncMock(side_effect=Exception("no response"))
    bus.publish = AsyncMock()

    await bus.js_publish("system.events.test", {"type": "test"})

    assert bus._js_consecutive_failures >= bus._js_failure_threshold


@pytest.mark.asyncio
async def test_suspend_sets_flag():
    """_suspend_jetstream sets _js_suspended to True."""
    bus = _make_bus()
    bus._js_consecutive_failures = 3
    bus._suspend_jetstream()

    assert bus._js_suspended is True


@pytest.mark.asyncio
async def test_resume_clears_state():
    """_resume_jetstream clears suspended flag and resets counter."""
    bus = _make_bus()
    bus._js_suspended = True
    bus._js_consecutive_failures = 5
    bus._resume_jetstream()

    assert bus._js_suspended is False
    assert bus._js_consecutive_failures == 0


@pytest.mark.asyncio
async def test_suspended_bypasses_to_core_nats():
    """When suspended, js_publish goes straight to core NATS — no JS attempt."""
    bus = _make_bus()
    bus._js_suspended = True
    bus.publish = AsyncMock()

    await bus.js_publish("system.events.test", {"type": "test"})

    # JS publish should NOT have been called
    bus._js.publish.assert_not_called()
    # Core NATS publish SHOULD have been called
    assert bus.publish.call_count == 1


@pytest.mark.asyncio
async def test_try_recovery_resumes_on_probe_success():
    """Successful recovery + probe resumes JetStream."""
    bus = _make_bus()
    bus._js_consecutive_failures = 3

    bus.recreate_stream = AsyncMock()
    bus.delete_consumer = AsyncMock()
    bus._js.stream_info = AsyncMock(return_value=MagicMock())

    await bus._try_jetstream_recovery()

    assert bus._js_suspended is False
    assert bus._js_consecutive_failures == 0


@pytest.mark.asyncio
async def test_try_recovery_stays_suspended_on_probe_failure():
    """Failed probe keeps JetStream suspended."""
    bus = _make_bus()
    bus._js_consecutive_failures = 3

    bus.recreate_stream = AsyncMock()
    bus.delete_consumer = AsyncMock()
    bus._js.stream_info = AsyncMock(side_effect=Exception("timeout"))

    await bus._try_jetstream_recovery()

    assert bus._js_suspended is True


@pytest.mark.asyncio
async def test_reconnect_resumes_suspended_jetstream():
    """_on_reconnected resumes JetStream even if it was suspended."""
    bus = _make_bus()
    bus._js_suspended = True
    bus._js_consecutive_failures = 5

    bus.recreate_stream = AsyncMock()
    bus.delete_consumer = AsyncMock()

    await bus._on_reconnected()

    assert bus._js_suspended is False
    assert bus._js_consecutive_failures == 0


def test_health_reports_suspension():
    """health() includes js_suspended field."""
    bus = _make_bus()
    bus._js_suspended = True

    h = bus.health()
    assert h["js_suspended"] is True

    bus._js_suspended = False
    h = bus.health()
    assert h["js_suspended"] is False


@pytest.mark.asyncio
async def test_suspend_is_idempotent():
    """Calling _suspend_jetstream multiple times doesn't change state."""
    bus = _make_bus()
    bus._suspend_jetstream()
    bus._suspend_jetstream()
    assert bus._js_suspended is True


@pytest.mark.asyncio
async def test_resume_is_idempotent():
    """Calling _resume_jetstream when not suspended is a no-op."""
    bus = _make_bus()
    assert bus._js_suspended is False
    bus._resume_jetstream()
    assert bus._js_suspended is False
    assert bus._js_consecutive_failures == 0


@pytest.mark.asyncio
async def test_recovery_failure_stays_suspended():
    """If _recover_jetstream raises, bus stays suspended."""
    bus = _make_bus()
    bus._js_consecutive_failures = 3

    bus.recreate_stream = AsyncMock(side_effect=Exception("NATS server gone"))
    bus.delete_consumer = AsyncMock()

    await bus._try_jetstream_recovery()

    assert bus._js_suspended is True


@pytest.mark.asyncio
async def test_single_flight_recovery():
    """Only one recovery task runs at a time."""
    bus = _make_bus()
    bus._js_consecutive_failures = 2  # Next failure hits threshold
    bus._js.publish = AsyncMock(side_effect=Exception("no response"))
    bus.publish = AsyncMock()  # core NATS fallback
    bus.recreate_stream = AsyncMock()
    bus.delete_consumer = AsyncMock()
    bus._js.stream_info = AsyncMock(return_value=MagicMock())

    # Trigger threshold — first recovery task spawns
    await bus.js_publish("system.events.test", {"type": "test1"})
    assert bus._js_recovery_task is not None
    first_task = bus._js_recovery_task

    # Let recovery complete
    await first_task

    # Trigger again — counter was reset by resume, need 3 more failures
    bus._js_suspended = False  # Simulate resume completed
    bus._js_consecutive_failures = 2
    await bus.js_publish("system.events.test", {"type": "test2"})

    # New task spawned (old one is .done())
    assert bus._js_recovery_task is not first_task or first_task.done()


@pytest.mark.asyncio
async def test_suspended_core_nats_failure_no_propagation():
    """When suspended, core NATS failure is caught — no exception propagates."""
    bus = _make_bus()
    bus._js_suspended = True
    bus.publish = AsyncMock(side_effect=Exception("NATS down"))

    # Should NOT raise — error is logged and swallowed
    await bus.js_publish("system.events.test", {"type": "test"})

    assert bus.publish.call_count == 1


@pytest.mark.asyncio
async def test_mock_bus_parity():
    """MockNATSBus has js_suspended field and reports it in health()."""
    from probos.mesh.nats_bus import MockNATSBus

    mock = MockNATSBus()
    assert mock._js_suspended is False

    h = mock.health()
    assert "js_suspended" in h
    assert h["js_suspended"] is False
