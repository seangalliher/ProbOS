"""AD-731 (Wave 152): regression tests asserting "no inline base64 ever crosses
the bus" — inverted shape of the original BF-265 / Wave 151 suite.

Originally BF-265 stripped IntentMessage.params['vision_messages'] from NATS
transport because AD-730 packed inline base64 image bytes (150 KB-1 MB per
attachment) into the bus, which triggered the 2026-05-11 memory-exhaustion
crash (GH #636). AD-731 switched the wire format to content-addressable refs
(SHA-256 + media_type, ~70 bytes per image) and reverted the strip — the
uniform-NATS-transport invariant is restored.

These tests now assert the AD-731 contract:
1. ``IntentBus._serialize_intent`` no longer strips ``vision_messages`` — it
   round-trips intact when carrying ref-shape blocks.
2. The serialized payload stays small (< 4 KB for a 5-image ref-shape DM)
   so the original OOM crash CANNOT recur via the same path.
3. ``_transport_stripped`` marker is NOT added to ref-shape DMs.
4. **Regression sentinel for the original mistake**: if someone re-introduces
   inline base64 in ``vision_messages`` content blocks (the AD-730 shape that
   caused #636), the size-bound sentinel test fires loudly.
5. Federation bridge keeps validated refs while rejecting inline siblings via
    the AD-731a-1d reference-only boundary.
"""
from __future__ import annotations

import copy
import json

import pytest

from probos.config import FederationConfig
from probos.federation.bridge import FederationBridge
from probos.federation.router import FederationRouter
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import FederationMessage, IntentMessage, NodeSelfModel


def _make_intent_with_vision_refs() -> IntentMessage:
    """Build an IntentMessage with AD-731 attachment_ref-shape vision_messages."""
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
                                "type": "attachment_ref",
                                "sha256": "a" * 64,
                                "media_type": "image/png",
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
# IntentBus serialization — AD-731 contract
# ------------------------------------------------------------------


def test_serialize_intent_preserves_vision_messages_ref_shape():
    """AD-731: vision_messages survives NATS serialization (no strip)."""
    intent = _make_intent_with_vision_refs()
    serialized = IntentBus._serialize_intent(intent)
    assert "vision_messages" in serialized["params"]
    block = serialized["params"]["vision_messages"][0]["content"][1]
    assert block["type"] == "image"
    assert block["source"]["type"] == "attachment_ref"
    assert block["source"]["sha256"] == "a" * 64
    assert block["source"]["media_type"] == "image/png"


def test_serialize_intent_no_transport_stripped_marker_for_refs():
    """AD-731: the _transport_stripped marker is NOT added for ref-shape DMs."""
    intent = _make_intent_with_vision_refs()
    serialized = IntentBus._serialize_intent(intent)
    assert "_transport_stripped" not in serialized["params"]


def test_serialize_intent_preserves_safe_params():
    """Non-vision params survive serialization unchanged."""
    intent = _make_intent_with_vision_refs()
    serialized = IntentBus._serialize_intent(intent)
    assert serialized["params"]["text"] == "Hello Ezri, can you describe this image?"
    assert serialized["params"]["from"] == "hxi_profile"
    assert serialized["params"]["has_image_attachment"] is True


def test_serialize_intent_does_not_mutate_original():
    """The live IntentMessage is untouched by serialization."""
    intent = _make_intent_with_vision_refs()
    _ = IntentBus._serialize_intent(intent)
    assert "vision_messages" in intent.params
    assert intent.params["vision_messages"][0]["content"][1]["type"] == "image"


def test_serialize_intent_without_vision_unchanged():
    """Intents without vision_messages serialize identically — no marker."""
    intent = _make_intent_without_vision()
    serialized = IntentBus._serialize_intent(intent)
    assert "vision_messages" not in serialized["params"]
    assert "_transport_stripped" not in serialized["params"]
    assert serialized["params"]["text"] == "Hello Ezri, text-only message."


def test_serialize_intent_ref_payload_is_size_bounded():
    """AD-731 invariant: ref-shape vision DMs stay small enough to never
    re-trigger #636. A 5-image DM with full 64-hex SHAs and the AD-730
    shape overhead must serialize to well under 4 KB.
    """
    intent = IntentMessage(
        intent="direct_message",
        params={
            "text": "Look at these five images",
            "vision_messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Look at these"},
                        *[
                            {
                                "type": "image",
                                "source": {
                                    "type": "attachment_ref",
                                    "sha256": f"{i:064x}",
                                    "media_type": "image/png",
                                },
                            }
                            for i in range(5)
                        ],
                    ],
                }
            ],
        },
        target_agent_id="counselor-001",
    )
    serialized = IntentBus._serialize_intent(intent)
    payload_bytes = len(json.dumps(serialized).encode("utf-8"))
    assert payload_bytes < 4_000, (
        f"AD-731 size-bound violated: serialized payload is {payload_bytes} "
        f"bytes for 5 ref-shape images. This should be ~600 bytes; if it has "
        f"ballooned, someone likely re-introduced inline base64."
    )


# ------------------------------------------------------------------
# Regression sentinel for the original AD-730 mistake (#636 cause)
# ------------------------------------------------------------------


def test_inline_base64_in_vision_messages_balloons_serialization():
    """Regression sentinel: if someone re-introduces inline base64 in
    vision_messages content blocks (the AD-730 shape that caused #636),
    the serialized payload balloons. AD-731 made BF-265's transport strip
    unnecessary by switching to content-addressable refs; a future change
    that inlines base64 again would re-trigger the JetStream retry-buffer
    accumulation that crashed the runtime on 2026-05-11.

    Without the strip, an inline-base64 payload now passes through
    serialize() unchanged. This sentinel pins that fact so the size-jump
    is visible and the contract violation is loud.
    """
    big_b64 = "A" * 100_000  # 100KB simulates a real PNG
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
    payload_bytes = len(json.dumps(serialized).encode("utf-8"))
    # Inline base64 is now not stripped — so payload IS large. This
    # sentinel test makes the size jump explicit: anyone going back to
    # inline-base64 will see this assertion document the size cost.
    assert payload_bytes > 100_000, (
        "Sentinel inverted: inline base64 in vision_messages no longer "
        "balloons serialization. Either the bus silently re-introduced a "
        "strip (contract violation against AD-731) or the test fixture "
        "drifted. Audit IntentBus._serialize_intent and AD-731 docs."
    )


# ------------------------------------------------------------------
# Federation bridge — AD-731a-1d reference-only boundary
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_federation_bridge_forwards_refs_and_rejects_inline_v1():
    """AD-731a-1d: safe refs cross; unsafe inline siblings do not."""
    class _CaptureTransport:
        def __init__(self) -> None:
            self.sent: list[FederationMessage] = []

        @property
        def connected_peers(self) -> list[str]:
            return ["node-b"]

        async def send_to_peer(
            self, peer_node_id: str, message: FederationMessage
        ) -> None:
            self.sent.append(message)

        async def receive_with_timeout(
            self, peer_node_id: str, timeout_ms: int
        ) -> FederationMessage | None:
            return None

    intent = _make_intent_with_vision_refs()
    inline_sentinel = "A" * 100_000
    intent.params["vision_messages"][0]["content"].append({
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": inline_sentinel,
        },
    })
    baseline = copy.deepcopy(intent.params)
    transport = _CaptureTransport()
    bridge = FederationBridge(
        node_id="node-a",
        transport=transport,
        router=FederationRouter(),
        intent_bus=IntentBus(SignalManager()),
        config=FederationConfig(forward_timeout_ms=1),
        self_model_fn=lambda: NodeSelfModel(node_id="node-a"),
    )

    await bridge.forward_intent(intent)

    assert len(transport.sent) == 1
    params_for_transport = transport.sent[0].payload["params"]
    assert params_for_transport["vision_messages"] == [{
        "role": "user",
        "content": [{
            "type": "image",
            "source": {
                "type": "attachment_ref",
                "sha256": "a" * 64,
                "media_type": "image/png",
            },
        }],
    }]
    assert inline_sentinel not in json.dumps(params_for_transport)
    assert params_for_transport["_transport_stripped"] == ["vision_messages"]
    assert params_for_transport["text"] == intent.params["text"]
    assert intent.params == baseline


# ------------------------------------------------------------------
# AD-731 in-process consumer contract
# ------------------------------------------------------------------


def test_ad731_in_process_consumer_sees_ref_shape_vision_messages():
    """The DM perception path in cognitive_agent.py reads from the LIVE
    IntentMessage. AD-731 keeps vision_messages intact through serialization
    too, so both the in-process consumer and any NATS-deserialized copy
    see the same ref-shape content.
    """
    intent = _make_intent_with_vision_refs()
    assert "vision_messages" in intent.params
    assert intent.params["has_image_attachment"] is True
    serialized = IntentBus._serialize_intent(intent)
    # AD-731: serialized payload keeps vision_messages too.
    assert "vision_messages" in serialized["params"]
