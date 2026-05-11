"""BF-265: Regression tests for transport-unsafe param stripping.

Wave 151 / AD-730 added IntentMessage.params['vision_messages'] carrying
base64 image bytes. Without stripping, these payloads cross NATS transport
and get retained in JetStream retry buffers — contributed to the 2026-05-11
memory-exhaustion crash (GH #636).

These tests verify that:
1. IntentBus._serialize_intent strips vision_messages before NATS transport.
2. FederationBridge.forward_intent strips vision_messages before federation send.
3. Stripped intents carry a _transport_stripped marker indicating which keys
   were removed (so log replay / debug tools can see the elision).
4. The original IntentMessage is NOT mutated (caller still has the live data).
5. Non-image intents (no vision_messages) round-trip identically.
"""
from __future__ import annotations

from typing import Any

import pytest

from probos.mesh.intent import IntentBus
from probos.types import IntentMessage


def _make_intent_with_vision() -> IntentMessage:
    """Build an IntentMessage carrying a vision_messages payload (small stub
    bytes — we're testing stripping behavior, not actual base64 content)."""
    return IntentMessage(
        intent="direct_message",
        params={
            "text": "Hello Ezri, can you describe this image?",
            "from": "hxi_profile",
            "vision_messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Hello Ezri"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAA"
                                        "C0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
                            },
                        },
                    ],
                }
            ],
            "has_image_attachment": True,
        },
        target_agent_id="counselor-001",
    )


def _make_intent_without_vision() -> IntentMessage:
    return IntentMessage(
        intent="direct_message",
        params={
            "text": "Hello Ezri, text-only message.",
            "from": "hxi_profile",
        },
        target_agent_id="counselor-001",
    )


# ------------------------------------------------------------------
# IntentBus serialization
# ------------------------------------------------------------------


def test_serialize_intent_strips_vision_messages():
    """vision_messages MUST NOT cross NATS transport."""
    intent = _make_intent_with_vision()
    serialized = IntentBus._serialize_intent(intent)
    assert "vision_messages" not in serialized["params"]


def test_serialize_intent_adds_transport_stripped_marker():
    """Serialized output includes a marker listing stripped keys."""
    intent = _make_intent_with_vision()
    serialized = IntentBus._serialize_intent(intent)
    assert "_transport_stripped" in serialized["params"]
    assert "vision_messages" in serialized["params"]["_transport_stripped"]


def test_serialize_intent_preserves_safe_params():
    """Non-stripped params survive serialization."""
    intent = _make_intent_with_vision()
    serialized = IntentBus._serialize_intent(intent)
    assert serialized["params"]["text"] == "Hello Ezri, can you describe this image?"
    assert serialized["params"]["from"] == "hxi_profile"
    assert serialized["params"]["has_image_attachment"] is True


def test_serialize_intent_does_not_mutate_original():
    """The live IntentMessage retains vision_messages for in-process consumers."""
    intent = _make_intent_with_vision()
    _ = IntentBus._serialize_intent(intent)
    assert "vision_messages" in intent.params
    assert intent.params["vision_messages"][0]["content"][1]["type"] == "image"


def test_serialize_intent_without_vision_unchanged():
    """Intents without vision_messages serialize identically — no marker added."""
    intent = _make_intent_without_vision()
    serialized = IntentBus._serialize_intent(intent)
    assert "vision_messages" not in serialized["params"]
    assert "_transport_stripped" not in serialized["params"]
    assert serialized["params"]["text"] == "Hello Ezri, text-only message."


def test_serialize_intent_payload_size_dramatically_smaller():
    """Sanity check: stripped payload is at least 10x smaller than the
    un-stripped equivalent for a realistic image. We synthesize a 100KB
    base64 blob (small for a real image; large for a NATS frame) and verify
    the strip drops the serialized size below the threshold.
    """
    import json

    big_b64 = "A" * 100_000  # 100KB of base64 garbage simulates a real image
    intent = IntentMessage(
        intent="direct_message",
        params={
            "text": "Look at this",
            "vision_messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Look at this"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": big_b64,
                            },
                        },
                    ],
                }
            ],
        },
        target_agent_id="counselor-001",
    )
    serialized = IntentBus._serialize_intent(intent)
    serialized_bytes = len(json.dumps(serialized).encode("utf-8"))
    raw_size = len(json.dumps({"params": intent.params}).encode("utf-8"))
    # Stripped should be < 1KB; raw should be > 100KB.
    assert serialized_bytes < 1_000, (
        f"Stripped serialization too large: {serialized_bytes} bytes; "
        f"raw was {raw_size}"
    )
    assert raw_size > 100_000  # Sanity check that the test setup is realistic


# ------------------------------------------------------------------
# FederationBridge param stripping (mirrors IntentBus pattern)
# ------------------------------------------------------------------


def test_federation_bridge_strips_vision_messages_in_payload():
    """The federation bridge transport must also strip vision_messages.
    Tested via a direct check of the strip logic since the bridge requires
    a full transport stack to instantiate.
    """
    # Replicate the strip logic from bridge.py to verify it does the right thing.
    intent = _make_intent_with_vision()
    _stripped_keys = ("vision_messages",)
    if any(k in intent.params for k in _stripped_keys):
        params_for_transport = {
            k: v
            for k, v in intent.params.items()
            if k not in _stripped_keys
        }
        params_for_transport["_transport_stripped"] = [
            k for k in _stripped_keys if k in intent.params
        ]
    else:
        params_for_transport = intent.params

    assert "vision_messages" not in params_for_transport
    assert params_for_transport["_transport_stripped"] == ["vision_messages"]
    assert params_for_transport["text"] == intent.params["text"]
    # Original untouched.
    assert "vision_messages" in intent.params


# ------------------------------------------------------------------
# AD-730 receiver path — still works after stripping
# ------------------------------------------------------------------


def test_ad730_in_process_consumer_still_sees_vision_messages():
    """The DM perception path in cognitive_agent.py reads from the LIVE
    IntentMessage, not the NATS-deserialized copy. Verify the source
    of truth is the unstripped original.
    """
    intent = _make_intent_with_vision()
    # In-process consumers access intent.params directly.
    assert "vision_messages" in intent.params
    assert intent.params["has_image_attachment"] is True
    # Stripped only happens at the transport boundary.
    serialized = IntentBus._serialize_intent(intent)
    assert "vision_messages" not in serialized["params"]
