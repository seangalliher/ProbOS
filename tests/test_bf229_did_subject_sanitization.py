"""BF-229: NATS subject prefix rejects colons from Ship DID.

Tests that NATSBus sanitizes DID colons to underscores for NATS-safe subjects.
"""

from __future__ import annotations

import pytest

from probos.mesh.nats_bus import MockNATSBus


@pytest.mark.asyncio
async def test_did_colons_sanitized_in_subject_prefix():
    """BF-229: Ship DID colons replaced with underscores for NATS subjects."""
    bus = MockNATSBus(subject_prefix="probos.local")
    await bus.start()

    # NATSBus sanitizes internally — caller passes raw DID
    await bus.set_subject_prefix("probos.did:probos:d9832d8c-9059-4532-8fb2-c30c0678f672")

    assert bus.subject_prefix == "probos.did_probos_d9832d8c-9059-4532-8fb2-c30c0678f672"
    assert ":" not in bus.subject_prefix


@pytest.mark.asyncio
async def test_subscriptions_follow_sanitized_prefix():
    """BF-229: Subscriptions re-created with sanitized prefix deliver messages."""
    bus = MockNATSBus(subject_prefix="probos.local")
    await bus.start()

    received = []

    async def _on_msg(msg):
        received.append(msg.data)

    await bus.subscribe("system.events.test", _on_msg)

    # Change to DID prefix — NATSBus sanitizes colons to underscores
    await bus.set_subject_prefix("probos.did:probos:abc123")

    # Publish on new (sanitized) prefix — should reach subscriber
    await bus.publish("system.events.test", {"ok": True})
    assert len(received) == 1
    assert received[0]["ok"] is True


@pytest.mark.asyncio
async def test_js_publish_succeeds_after_sanitized_prefix():
    """BF-229: JetStream publishes use sanitized prefix, not raw DID."""
    bus = MockNATSBus(subject_prefix="probos.local")
    await bus.start()

    # Create stream with initial prefix
    await bus.ensure_stream("SYSTEM_EVENTS", ["system.events.>"])

    # Change to DID prefix — NATSBus sanitizes internally
    await bus.set_subject_prefix("probos.did:probos:abc123")

    # JS publish should succeed (stream filter matches sanitized prefix)
    await bus.js_publish("system.events.test_event", {"data": "value"})

    # Verify the published subject uses sanitized prefix (underscores, not colons)
    assert len(bus.published) > 0
    last_subject = bus.published[-1][0]
    assert ":" not in last_subject
    assert last_subject == "probos.did_probos_abc123.system.events.test_event"


@pytest.mark.asyncio
async def test_safe_prefix_unchanged():
    """BF-229: Prefixes without unsafe chars pass through without modification."""
    bus = MockNATSBus(subject_prefix="probos.local")
    await bus.start()

    await bus.set_subject_prefix("probos.ship-abc-123")
    assert bus.subject_prefix == "probos.ship-abc-123"


@pytest.mark.asyncio
async def test_sanitization_preserves_namespace_depth():
    """BF-229: Colons become underscores (one token), not dots (multiple tokens).

    This preserves the probos.{ship}.* namespace hierarchy — the DID stays
    as a single NATS token, keeping subject depth consistent with probos.local.*.
    """
    bus = MockNATSBus(subject_prefix="probos.local")
    await bus.start()

    await bus.set_subject_prefix("probos.did:probos:abc-123")

    # Should be 2 prefix tokens (probos + did_probos_abc-123), not 4
    prefix_tokens = bus.subject_prefix.split(".")
    assert len(prefix_tokens) == 2
    assert prefix_tokens[0] == "probos"
    assert prefix_tokens[1] == "did_probos_abc-123"
