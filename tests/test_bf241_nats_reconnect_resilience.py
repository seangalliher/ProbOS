"""BF-241: NATS JetStream reconnect resilience.

Tests cover:
- _recover_jetstream recreates tracked streams
- _recover_jetstream re-subscribes JetStream consumers (not core)
- _recover_jetstream skips when JetStream disabled (_js=None)
- _on_reconnected triggers _recover_jetstream
- Partial failure (stream fails, consumers still re-subscribe)
- _resubscribing flag set during consumer re-subscription
- MockNATSBus interface parity
- set_subject_prefix delegates to _recover_jetstream (DRY)
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_recover_jetstream_recreates_streams():
    """Verify _recover_jetstream calls recreate_stream for each tracked config."""
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._subject_prefix = "probos.test"
    bus._js = True  # Truthy — not None
    bus._connected = True
    bus._resubscribing = False
    bus._active_subs = []
    bus._stream_configs = [
        {"name": "SYSTEM_EVENTS", "subjects": ["system.events.>"], "max_msgs": 50000, "max_age": 3600},
        {"name": "WARDROOM", "subjects": ["wardroom.events.>"], "max_msgs": 10000, "max_age": 3600},
    ]

    recreated = []
    async def mock_recreate(name, subjects, max_msgs=-1, max_age=0):
        recreated.append({"name": name, "subjects": subjects, "max_msgs": max_msgs, "max_age": max_age})

    bus.recreate_stream = mock_recreate
    await bus._recover_jetstream(reason="test")

    assert len(recreated) == 2
    assert recreated[0]["name"] == "SYSTEM_EVENTS"
    assert recreated[1]["name"] == "WARDROOM"


@pytest.mark.asyncio
async def test_recover_jetstream_resubscribes_consumers():
    """Verify JS consumer entries in _active_subs are re-subscribed."""
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._subject_prefix = "probos.test"
    bus._js = True
    bus._connected = True
    bus._resubscribing = False
    bus._stream_configs = []

    callback = lambda msg: None
    bus._active_subs = [
        {
            "kind": "js",
            "subject": "wardroom.events.>",
            "callback": callback,
            "kwargs": {"durable": "wardroom-router", "stream": "WARDROOM"},
            "sub": None,
        },
        {
            "kind": "core",  # Should NOT be re-subscribed by _recover_jetstream
            "subject": "system.ping",
            "callback": callback,
            "kwargs": {},
            "sub": None,
        },
    ]

    js_resubscribed = []
    async def mock_js_subscribe(subject, cb, **kwargs):
        js_resubscribed.append(subject)
        return "mock_sub"

    deleted_consumers = []
    async def mock_delete_consumer(stream, durable):
        deleted_consumers.append((stream, durable))

    bus.js_subscribe = mock_js_subscribe
    bus.delete_consumer = mock_delete_consumer
    await bus._recover_jetstream(reason="test")

    # Only JS entry re-subscribed, not core
    assert len(js_resubscribed) == 1
    assert js_resubscribed[0] == "wardroom.events.>"
    # Stale consumer deleted before re-subscribe (BF-223 pattern)
    assert ("WARDROOM", "wardroom-router") in deleted_consumers
    # Sub reference updated (critical — stale ref breaks next recovery cycle)
    assert bus._active_subs[0]["sub"] == "mock_sub"


@pytest.mark.asyncio
async def test_recover_jetstream_skips_without_js():
    """Verify _recover_jetstream returns early when _js is None (JetStream disabled)."""
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._subject_prefix = "probos.test"
    bus._js = None  # JetStream not initialized
    bus._connected = True
    bus._resubscribing = False
    bus._stream_configs = [
        {"name": "SYSTEM_EVENTS", "subjects": ["system.events.>"], "max_msgs": 50000, "max_age": 3600},
    ]
    bus._active_subs = []

    recreated = []
    async def mock_recreate(name, subjects, max_msgs=-1, max_age=0):
        recreated.append(name)

    bus.recreate_stream = mock_recreate
    await bus._recover_jetstream(reason="test")

    # Early return guard means mock was never called
    assert len(recreated) == 0


@pytest.mark.asyncio
async def test_on_reconnected_triggers_recovery():
    """Verify the _on_reconnected instance method invokes JetStream recovery."""
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._subject_prefix = "probos.test"
    bus._js = True
    bus._connected = False
    bus._resubscribing = False
    bus._stream_configs = []
    bus._active_subs = []
    bus._nc = MagicMock()
    bus._nc.connected_url = "nats://localhost:4222"

    recovery_calls = []
    async def mock_recover(*, reason="reconnect"):
        recovery_calls.append(reason)
    bus._recover_jetstream = mock_recover

    await bus._on_reconnected()

    assert bus._connected is True
    assert "reconnect" in recovery_calls


@pytest.mark.asyncio
async def test_recover_jetstream_partial_failure(caplog):
    """Stream failure must not prevent consumer re-subscription (fail-fast: log-and-degrade)."""
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._subject_prefix = "probos.test"
    bus._js = True
    bus._connected = True
    bus._resubscribing = False
    bus._stream_configs = [
        {"name": "BROKEN_STREAM", "subjects": ["broken.>"], "max_msgs": 100, "max_age": 60},
    ]

    callback = lambda msg: None
    bus._active_subs = [
        {
            "kind": "js",
            "subject": "wardroom.events.>",
            "callback": callback,
            "kwargs": {"durable": "test-consumer", "stream": "WARDROOM"},
            "sub": None,
        },
    ]

    async def mock_recreate_fails(name, subjects, max_msgs=-1, max_age=0):
        raise Exception("Server unavailable")

    js_resubscribed = []
    async def mock_js_subscribe(subject, cb, **kwargs):
        js_resubscribed.append(subject)
        return "mock_sub"

    async def mock_delete_consumer(stream, durable):
        pass

    bus.recreate_stream = mock_recreate_fails
    bus.js_subscribe = mock_js_subscribe
    bus.delete_consumer = mock_delete_consumer

    # Should not raise despite stream failure
    with caplog.at_level(logging.ERROR):
        await bus._recover_jetstream(reason="test")

    # Consumer re-subscription still happened
    assert len(js_resubscribed) == 1
    # Stream failure was logged at ERROR (log-and-degrade contract)
    assert any("BF-241: Stream recreate failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_recover_jetstream_resubscribing_flag():
    """Verify _resubscribing is True during consumer re-subscription and reset after."""
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._subject_prefix = "probos.test"
    bus._js = True
    bus._connected = True
    bus._resubscribing = False
    bus._stream_configs = []

    flag_during_subscribe = []
    callback = lambda msg: None
    bus._active_subs = [
        {
            "kind": "js",
            "subject": "test.>",
            "callback": callback,
            "kwargs": {"durable": "test-dur", "stream": "TEST"},
            "sub": None,
        },
    ]

    async def mock_js_subscribe(subject, cb, **kwargs):
        flag_during_subscribe.append(bus._resubscribing)
        return "mock_sub"

    async def mock_delete_consumer(stream, durable):
        pass

    bus.js_subscribe = mock_js_subscribe
    bus.delete_consumer = mock_delete_consumer
    await bus._recover_jetstream(reason="test")

    # Flag was True during subscribe call
    assert flag_during_subscribe == [True]
    # Flag reset after
    assert bus._resubscribing is False


@pytest.mark.asyncio
async def test_mock_bus_has_recover_jetstream():
    """MockNATSBus must have _recover_jetstream for interface parity."""
    from probos.mesh.nats_bus import MockNATSBus

    bus = MockNATSBus()
    # Should not raise
    await bus._recover_jetstream(reason="test")


@pytest.mark.asyncio
async def test_set_subject_prefix_calls_recover_jetstream():
    """Verify set_subject_prefix delegates to _recover_jetstream (DRY: BF-241)."""
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._subject_prefix = "probos.old"
    bus._js = True
    bus._connected = True
    bus._resubscribing = False
    bus._stream_configs = []
    bus._active_subs = []
    bus._subscriptions = []
    bus._prefix_change_callbacks = []
    bus._nc = MagicMock()
    bus._nc.is_connected = True

    recovery_calls = []
    async def mock_recover(*, reason="reconnect"):
        recovery_calls.append(reason)
    bus._recover_jetstream = mock_recover

    await bus.set_subject_prefix("probos.new")

    assert "prefix_change" in recovery_calls
    assert bus._subject_prefix == "probos.new"
