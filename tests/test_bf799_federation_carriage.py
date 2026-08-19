"""BF-799 (#1263): the AD-1248 disclosure must survive the federation hop.

Directed federation is a TRANSPORT HOP, not a sink -- the origin reconstructs
an ``IntentResult`` and a LOCAL sink renders it -- so the disclosure has to
ride ACROSS rather than be rendered remotely. ``_serialize_directed_result``
emitted six keys and dropped it, so a tool failure on a remote node was
invisible to the Captain.

The tests that matter here run through TWO REAL BRIDGES. Adversarial review of
the plan proved why: a helper-chain test that calls the serializer and the
detacher by hand still passes if ``forward_direct_message`` forgets to put the
payload back on ``metadata``. The consumer that matters is whatever receives
the return value of ``forward_direct_message``.
"""

from __future__ import annotations

import copy
import json

import pytest

from probos.config import FederationConfig, PeerConfig
from probos.dm_reply import (
    DM_REPLY_METADATA_KEY,
    DmReply,
    ToolFailures,
    call_signature,
    failure_key,
    mint_scope,
)
from probos.federation.bridge import FederationBridge
from probos.federation.mock_transport import (
    MockFederationTransport,
    MockTransportBus,
)
from probos.federation.router import FederationRouter
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage, IntentResult, NodeSelfModel


def _failures(*names: str) -> ToolFailures:
    root, scope = mint_scope(), mint_scope()
    return ToolFailures.from_mapping(
        {failure_key(root, scope, call_signature(n, {})): n for n in names}
    )


def _bridge(node_id: str, peer_node_id: str, transport, intent_bus):  # noqa: ANN001
    return FederationBridge(
        node_id=node_id,
        transport=transport,
        router=FederationRouter(),
        intent_bus=intent_bus,
        config=FederationConfig(
            enabled=True,
            node_id=node_id,
            peers=[PeerConfig(node_id=peer_node_id, address="tcp://127.0.0.1:65530")],
            forward_timeout_ms=2_000,
            gossip_interval_seconds=100.0,
        ),
        self_model_fn=lambda: NodeSelfModel(node_id=node_id),
    )


def _dm_intent() -> IntentMessage:
    return IntentMessage(
        intent="direct_message",
        params={"text": "status?"},
        target_agent_id="target_agent_001",
    )


async def _cross(remote_result_factory):
    """Drive a real origin -> remote -> origin directed hop through two bridges."""
    bus = MockTransportBus()
    origin_bus = IntentBus(SignalManager())
    receiver_bus = IntentBus(SignalManager())

    async def _target(inbound: IntentMessage) -> IntentResult:
        return remote_result_factory(inbound)

    receiver_bus.subscribe("target_agent_001", _target, ["direct_message"])

    origin_bridge = _bridge(
        "node-a", "node-b", MockFederationTransport("node-a", bus), origin_bus
    )
    receiver_bridge = _bridge(
        "node-b", "node-a", MockFederationTransport("node-b", bus), receiver_bus
    )
    await origin_bridge.start()
    await receiver_bridge.start()
    try:
        return await origin_bridge.forward_direct_message("node-b", _dm_intent())
    finally:
        await receiver_bridge.stop()
        await origin_bridge.stop()


# ---------------------------------------------------------------------------
# The crossing that BF-799 is about
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_disclosure_survives_the_whole_directed_hop() -> None:
    """The one test that spans it: remote produces -> wire -> origin sink reads.

    Reverting ANY of the four transforms (serializer, key set, detacher,
    reconstruction) must make this fail.
    """
    def _remote(inbound: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=inbound.id,
            agent_id="target_agent_001",
            success=True,
            result="here is the answer",
            metadata={DM_REPLY_METADATA_KEY: _failures("web_search").to_wire()},
        )

    result = await _cross(_remote)

    assert result.success is True
    assert result.result == "here is the answer"

    # The LOCAL sink's view -- the consumer that actually matters.
    reply = DmReply.from_intent_result(result)
    assert reply.tool_failures.names() == ("web_search",), (
        "the disclosure must be readable by the local sink after the hop"
    )
    assert "web_search" in str(reply.render())


@pytest.mark.asyncio
async def test_a_clean_turn_crosses_with_no_disclosure_and_no_error() -> None:
    """The common case must be untouched."""
    def _remote(inbound: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=inbound.id,
            agent_id="target_agent_001",
            success=True,
            result="clean answer",
        )

    result = await _cross(_remote)

    assert result.success is True
    assert result.result == "clean answer"
    assert DmReply.from_intent_result(result).tool_failures.is_empty


# ---------------------------------------------------------------------------
# The extension must never destroy the answer (the BF-802 lesson, one layer down)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_malformed_disclosure_costs_the_disclosure_not_the_answer() -> None:
    """A disclosure that cannot be carried must drop ITSELF.

    Rejecting the record would mean the disclosure destroys the reply it was
    attached to -- which is precisely BF-802, one layer down.
    """
    def _remote(inbound: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=inbound.id,
            agent_id="target_agent_001",
            success=True,
            result="the answer survives",
            metadata={DM_REPLY_METADATA_KEY: "not-a-dict"},
        )

    result = await _cross(_remote)

    assert result.success is True, "the answer must still arrive"
    assert result.result == "the answer survives"
    assert DmReply.from_intent_result(result).tool_failures.is_empty


@pytest.mark.asyncio
async def test_an_oversized_disclosure_costs_the_disclosure_not_the_answer() -> None:
    """A disclosure that will not fit must drop ITSELF, not the reply.

    The body is a list of legal-sized strings -- a single string is capped at
    ``_DIRECTED_RESULT_MAX_STRING_CHARS`` (65,536), so a 200,000-char body
    would be rejected on its own merits and would prove nothing about the
    disclosure. Sized to nearly fill the shared UTF-8 budget so the disclosure
    is what pushes it over.
    """
    body = ["y" * 60_000 for _ in range(4)]  # 240,000 bytes, each string legal

    def _remote(inbound: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=inbound.id,
            agent_id="target_agent_001",
            success=True,
            result=list(body),
            metadata={
                DM_REPLY_METADATA_KEY: {
                    "v": 1,
                    "entries": [["k" * 30_000, "n" * 30_000]],
                }
            },
        )

    result = await _cross(_remote)

    assert result.success is True, (
        "an oversized disclosure must not discard the answer"
    )
    assert result.result == body
    assert DmReply.from_intent_result(result).tool_failures.is_empty


def test_the_envelope_drops_the_disclosure_before_the_answer() -> None:
    """The second place the answer could be lost: the response envelope.

    Measured by review -- a body compacting to the cap went over once a small
    disclosure was attached, and returning ``None`` there discards the
    Captain's whole answer.

    The body is a LIST of legal-sized strings. An earlier version used one
    ~262,000-character string, which `_detach_directed_result_value` rejects
    outright above ``_DIRECTED_RESULT_MAX_STRING_CHARS`` (65,536) -- so the
    compactor was being handed something the responder could never produce,
    and the test proved nothing about a reachable path.
    """
    from probos.federation.bridge import (
        _DIRECTED_RESPONSE_MAX_JSON_BYTES,
        _DIRECTED_RESULT_MAX_STRING_CHARS,
        _compact_detach_directed_response,
        _encode_directed_response,
    )

    chunk = "z" * _DIRECTED_RESULT_MAX_STRING_CHARS
    base = {
        "intent_id": "i", "agent_id": "ezri", "success": True,
        "result": [chunk, chunk, chunk], "error": None, "confidence": 0.5,
    }
    encoded = _encode_directed_response(base)
    assert encoded is not None, "precondition: a legal body fits alone"

    # Pad with legal-sized strings until one more disclosure tips the envelope.
    headroom = _DIRECTED_RESPONSE_MAX_JSON_BYTES - len(encoded)
    base["result"] = [chunk, chunk, chunk, "p" * max(headroom - 20, 0)]
    assert _encode_directed_response(base) is not None, "precondition: still fits"

    with_disclosure = dict(base)
    with_disclosure[DM_REPLY_METADATA_KEY] = {"v": 1, "entries": [["k", "web_search"]]}
    assert _encode_directed_response(with_disclosure) is None, (
        "precondition: the disclosure must be what tips it"
    )

    out = _compact_detach_directed_response(with_disclosure)

    assert out is not None, "the answer must survive the envelope cap"
    carried = out["results"][0]
    assert carried["result"] == base["result"]
    assert DM_REPLY_METADATA_KEY not in carried

    out = _compact_detach_directed_response(with_disclosure)

    assert out is not None, "the answer must survive the envelope cap"
    carried = out["results"][0]
    assert carried["result"] == base["result"]
    assert DM_REPLY_METADATA_KEY not in carried


# ---------------------------------------------------------------------------
# Wire compatibility
# ---------------------------------------------------------------------------


def test_a_clean_turn_serialises_to_the_same_wire_value_it_always_did() -> None:
    """CANONICAL value equality, not key-set equality.

    The previous guard compared ``set(...)`` against the key frozenset, which
    would pass even if a VALUE changed. This compares the whole payload.

    It uses ``sort_keys=True`` deliberately and therefore does NOT assert
    insertion order -- an older peer parses the JSON and validates the
    resulting dict, so canonical value equality is the contract that actually
    binds, and claiming byte identity would overstate it.
    """
    from probos.federation.bridge import _serialize_directed_result

    result = IntentResult(
        intent_id="i", agent_id="ezri", success=True, result="text",
        confidence=0.5,
    )
    baseline = {
        "intent_id": "i",
        "agent_id": "ezri",
        "success": True,
        "result": "text",
        "error": None,
        "confidence": 0.5,
    }
    assert json.dumps(
        _serialize_directed_result(result), sort_keys=True, separators=(",", ":")
    ) == json.dumps(baseline, sort_keys=True, separators=(",", ":"))


def test_an_empty_metadata_dict_does_not_add_the_key() -> None:
    """Only a non-None payload widens the wire shape."""
    from probos.federation.bridge import _DIRECTED_RESULT_KEYS, _serialize_directed_result

    for metadata in ({}, {DM_REPLY_METADATA_KEY: None}, {"tool_trace_ref": "abc"}):
        wire = _serialize_directed_result(
            IntentResult(
                intent_id="i", agent_id="ezri", success=True, result="t",
                metadata=dict(metadata),
            )
        )
        assert set(wire) == set(_DIRECTED_RESULT_KEYS), (
            f"{metadata!r} must not widen the wire shape"
        )


def test_only_the_disclosure_rides_not_the_rest_of_metadata() -> None:
    """`metadata` also carries internal identifiers such as ``tool_trace_ref``.

    Shipping it wholesale to a remote peer would widen the blast radius, so the
    bridge carries exactly one named key.
    """
    from probos.federation.bridge import _serialize_directed_result

    wire = _serialize_directed_result(
        IntentResult(
            intent_id="i", agent_id="ezri", success=True, result="t",
            metadata={
                DM_REPLY_METADATA_KEY: _failures("web_search").to_wire(),
                "tool_trace_ref": "SECRET-INTERNAL-REF",
            },
        )
    )
    assert DM_REPLY_METADATA_KEY in wire
    assert "tool_trace_ref" not in wire
    assert "SECRET-INTERNAL-REF" not in json.dumps(wire)


def test_a_six_key_payload_from_an_older_peer_is_still_accepted() -> None:
    """Old -> new must keep working."""
    from probos.federation.bridge import _detach_serialized_directed_result

    detached, error = _detach_serialized_directed_result(
        {
            "intent_id": "i", "agent_id": "ezri", "success": True,
            "result": "text", "error": None, "confidence": 0.5,
        },
        malformed_error="bad",
    )
    assert error is None and detached is not None
    assert DM_REPLY_METADATA_KEY not in detached


def test_an_unknown_seventh_key_is_still_fatal() -> None:
    """Widening to one documented shape must not become 'ignore unknown keys'.

    The exact-key check is a relay control against key smuggling.
    """
    from probos.federation.bridge import _detach_serialized_directed_result

    detached, error = _detach_serialized_directed_result(
        {
            "intent_id": "i", "agent_id": "ezri", "success": True,
            "result": "text", "error": None, "confidence": 0.5,
            "smuggled": {"anything": "at all"},
        },
        malformed_error="bad",
    )
    assert detached is None and error == "bad"


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def test_the_disclosure_shares_the_node_budget_with_the_body() -> None:
    """Left local, the node counter would grant each field its own full
    allowance, so carrying a second field silently doubled the bound."""
    from probos.federation.bridge import (
        _DIRECTED_RESULT_MAX_NODES,
        _detach_serialized_directed_result,
    )

    # Each dict entry costs TWO nodes (the key in dict_next, the value in the
    # following visit), so halve the allowance to size a body that sits just
    # under it on its own.
    big = {str(i): i for i in range((_DIRECTED_RESULT_MAX_NODES // 2) - 20)}
    detached, error = _detach_serialized_directed_result(
        {
            "intent_id": "i", "agent_id": "ezri", "success": True,
            "result": big, "error": None, "confidence": 0.5,
            DM_REPLY_METADATA_KEY: {str(i): i for i in range(500)},
        },
        malformed_error="bad",
    )

    assert error is None and detached is not None, (
        "the body must still be delivered"
    )
    assert detached["result"] == big
    assert DM_REPLY_METADATA_KEY not in detached, (
        "the disclosure must be dropped once the SHARED node budget is spent, "
        "not granted a second full allowance"
    )
