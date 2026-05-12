"""BF-267: Regression test for local IntentBus dispatch preserving vision_messages.

BF-265 strips ``vision_messages`` from ``IntentMessage.params`` in
``_serialize_intent`` to prevent base64 image bytes from crossing NATS
transport (which contributed to crash #636 by accumulating in JetStream
retry buffers). That fix was correct for cross-mesh delivery.

But ``IntentBus.send()`` was using NATS request/reply for ALL targeted
dispatch — including local same-process agents. The local round-trip
through NATS serialization stripped vision_messages, then the local agent
received an IntentMessage with vision_messages=None and routed through
the text-only branch.

User-facing symptom: image DMs to Ezri (Counselor) caused her to honestly
report "I don't see an image attached to this message — only the text
came through on my end" even though the frontend confirmed
``attachment_ids`` was in the chat POST payload.

BF-267 prefers direct-call dispatch when the target agent is registered
in ``self._subscribers`` (i.e. lives in this process). NATS is reserved
for cross-mesh delivery where the strip is genuinely needed.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage, IntentResult


@pytest.mark.asyncio
async def test_local_send_preserves_vision_messages_when_nats_connected():
    """Even with NATS bus 'connected', a local subscriber receives the
    intent via direct-call — vision_messages survive the dispatch."""
    bus = IntentBus(signal_manager=SignalManager())

    # Simulate NATS bus being "connected" — without BF-267 this would have
    # caused IntentBus to take the NATS-serialize path even for local agents.
    mock_nats = MagicMock()
    mock_nats.connected = True
    bus._nats_bus = mock_nats

    received_intents: list[IntentMessage] = []

    async def local_handler(intent: IntentMessage) -> IntentResult:
        received_intents.append(intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id=intent.target_agent_id or "",
            success=True,
            result={"ok": True},
            confidence=1.0,
        )

    target = "counselor-local"
    bus._subscribers[target] = local_handler

    vision_payload = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "Describe this"},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "FAKE_BASE64_BLOB",
                },
            },
        ],
    }]

    intent = IntentMessage(
        intent="direct_message",
        params={
            "text": "Describe this",
            "vision_messages": vision_payload,
            "has_image_attachment": True,
        },
        target_agent_id=target,
        ttl_seconds=10.0,
    )

    result = await bus.send(intent)

    # Result came back from the local handler.
    assert result is not None
    assert result.success is True

    # CRITICAL: the local handler received vision_messages intact.
    assert len(received_intents) == 1
    received = received_intents[0]
    assert "vision_messages" in received.params, (
        "BF-267: local dispatch must NOT strip vision_messages. "
        "If this fails, image DMs to local crew are broken again."
    )
    assert received.params["vision_messages"] == vision_payload

    # NATS request was NOT called for local dispatch.
    mock_nats.request.assert_not_called() if hasattr(mock_nats, 'request') else None


@pytest.mark.asyncio
async def test_remote_send_still_uses_nats_with_stripping():
    """When the target agent is NOT in local subscribers, NATS is used
    and the BF-265 transport-strip still applies (correct for federation)."""
    bus = IntentBus(signal_manager=SignalManager())

    # NATS bus configured and "connected"
    nats_send_log: list[dict] = []

    async def fake_request(subject: str, payload: dict, timeout: float = 10.0):
        nats_send_log.append({"subject": subject, "payload": payload})
        # Reply shape that _deserialize_result accepts
        return {
            "intent_id": payload.get("id", ""),
            "agent_id": "remote-agent",
            "success": True,
            "data": {},
            "confidence": 1.0,
        }

    mock_nats = MagicMock()
    mock_nats.connected = True
    mock_nats.request = fake_request
    bus._nats_bus = mock_nats

    intent = IntentMessage(
        intent="direct_message",
        params={
            "text": "Describe this",
            "vision_messages": [{"role": "user", "content": [{"type": "image"}]}],
        },
        target_agent_id="remote-agent-not-local",
        ttl_seconds=10.0,
    )

    # No subscriber registered → falls through to NATS path
    await bus.send(intent)

    # NATS request was made
    assert len(nats_send_log) == 1
    # The serialized payload had vision_messages stripped (BF-265 behavior preserved)
    sent_params = nats_send_log[0]["payload"]["params"]
    assert "vision_messages" not in sent_params, (
        "BF-265: remote NATS dispatch must still strip vision_messages "
        "to prevent retry-buffer accumulation."
    )
    # The strip marker is present so log readers know data was elided
    assert "_transport_stripped" in sent_params
    assert "vision_messages" in sent_params["_transport_stripped"]


@pytest.mark.asyncio
async def test_local_send_without_vision_messages_unchanged():
    """Non-vision intents to local agents still work normally."""
    bus = IntentBus(signal_manager=SignalManager())
    mock_nats = MagicMock()
    mock_nats.connected = True
    bus._nats_bus = mock_nats

    async def handler(intent: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=intent.id,
            agent_id=intent.target_agent_id or "",
            success=True,
            confidence=1.0,
        )

    target = "text-only-agent"
    bus._subscribers[target] = handler

    intent = IntentMessage(
        intent="direct_message",
        params={"text": "Hello, no image here."},
        target_agent_id=target,
        ttl_seconds=10.0,
    )

    result = await bus.send(intent)
    assert result is not None
    assert result.success is True


@pytest.mark.asyncio
async def test_local_send_with_no_nats_still_works():
    """The original 'NATS disconnected → direct-call fallback' path is
    preserved as a special case of the local-first dispatch."""
    bus = IntentBus(signal_manager=SignalManager())
    # No NATS bus at all
    bus._nats_bus = None

    async def handler(intent: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=intent.id,
            agent_id=intent.target_agent_id or "",
            success=True,
            confidence=1.0,
        )

    target = "local-only"
    bus._subscribers[target] = handler

    intent = IntentMessage(
        intent="direct_message",
        params={"text": "hi"},
        target_agent_id=target,
        ttl_seconds=10.0,
    )

    result = await bus.send(intent)
    assert result is not None
    assert result.success is True


@pytest.mark.asyncio
async def test_send_with_no_subscriber_and_no_nats_returns_none():
    """Edge case: unreachable target → None, no exception."""
    bus = IntentBus(signal_manager=SignalManager())
    bus._nats_bus = None  # No NATS

    intent = IntentMessage(
        intent="direct_message",
        params={"text": "hi"},
        target_agent_id="nobody-home",
        ttl_seconds=10.0,
    )

    result = await bus.send(intent)
    assert result is None


@pytest.mark.asyncio
async def test_local_send_timeout_preserves_existing_behavior():
    """Handler that hangs longer than TTL returns a timeout result."""
    bus = IntentBus(signal_manager=SignalManager())
    mock_nats = MagicMock()
    mock_nats.connected = True
    bus._nats_bus = mock_nats

    async def slow_handler(intent: IntentMessage) -> IntentResult:
        await asyncio.sleep(5)  # Longer than ttl_seconds below
        return IntentResult(
            intent_id=intent.id,
            agent_id=intent.target_agent_id or "",
            success=True,
            confidence=1.0,
        )

    target = "slow-agent"
    bus._subscribers[target] = slow_handler

    intent = IntentMessage(
        intent="direct_message",
        params={"text": "hi"},
        target_agent_id=target,
        ttl_seconds=0.1,
    )

    result = await bus.send(intent)
    assert result is not None
    assert result.success is False
    assert "did not respond" in (result.error or "")
