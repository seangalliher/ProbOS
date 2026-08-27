"""AD-1276 Section 2 (BF-789, #1253): an inbound federation denial reaches the peer.

Two silences on the inbound path. A policy refusal returned an empty
``results`` list -- byte-identical to "no agent answered", so the peer could
not tell which it had. And anything raising out of ``handle_inbound`` escaped
into the NATS subscription wrapper with no ``intent_response`` ever sent, so
the peer waited out its own timeout with a local fault as the cause.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from probos.config import FederationConfig, PeerConfig
from probos.extensions import overlay
from probos.federation.bridge import FederationBridge
from probos.federation.nats_transport import NATSFederationTransport
from probos.federation.router import FederationRouter
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import (
    FederationMessage,
    IntentMessage,
    IntentResult,
    NodeSelfModel,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _clean_hooks():
    """AD-698's registry is module-level; leaking a hook would poison the suite."""
    before = list(overlay._PRE_INTENT_AUTH_HOOKS)
    overlay._PRE_INTENT_AUTH_HOOKS.clear()
    yield
    overlay._PRE_INTENT_AUTH_HOOKS.clear()
    overlay._PRE_INTENT_AUTH_HOOKS.extend(before)


class _CaptureTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[str, FederationMessage]] = []

    @property
    def connected_peers(self) -> list[str]:
        return ["node-b"]

    async def send_to_peer(self, peer_node_id: str, message: FederationMessage) -> None:
        self.sent.append((peer_node_id, message))

    async def send_to_all_peers(self, message: FederationMessage) -> list[str]:
        return ["node-b"]

    async def deliver_response(
        self, source_node: str, message: FederationMessage
    ) -> None:
        self.sent.append((source_node, message))

    async def request_peer(self, *_a: Any, **_k: Any) -> FederationMessage | None:
        return None

    async def receive_with_timeout(
        self, *_a: Any, **_k: Any
    ) -> FederationMessage | None:
        return None


def _make_bridge(intent_bus: Any) -> tuple[FederationBridge, _CaptureTransport]:
    transport = _CaptureTransport()
    bridge = FederationBridge(
        node_id="node-a",
        transport=transport,
        router=FederationRouter(),
        intent_bus=intent_bus,
        config=FederationConfig(
            enabled=True,
            node_id="node-a",
            peers=[PeerConfig(node_id="node-b", address="tcp://127.0.0.1:65000")],
            forward_timeout_ms=100,
            gossip_interval_seconds=1_000.0,
            validate_remote_results=False,
        ),
        self_model_fn=lambda: NodeSelfModel(node_id="node-a"),
    )
    return bridge, transport


def _inbound_request(intent_name: str = "probe") -> FederationMessage:
    return FederationMessage(
        type="intent_request",
        source_node="node-b",
        message_id="msg-1",
        payload={"intent": intent_name, "params": {}, "id": "fed-1"},
        timestamp=0.0,
    )


def _deny(_intent: Any) -> bool:
    return False


def _allow(_intent: Any) -> bool:
    return True


class _RaisingBus(IntentBus):
    async def broadcast(self, intent, timeout=None, *, federated=True, raise_on_denial=False):
        raise RuntimeError("local fan-out exploded")


class TestADenialIsDistinguishableFromSilence:
    async def test_an_inbound_intent_denied_by_policy_returns_a_denial_not_an_empty_result_set(
        self,
    ):
        bus = IntentBus(SignalManager())
        bridge, transport = _make_bridge(bus)
        overlay.register_pre_intent_authorization_hook("deny_all", _deny)

        await bridge.handle_inbound(_inbound_request())

        assert len(transport.sent) == 1, "the peer received nothing and will time out"
        _, response = transport.sent[0]
        assert response.type == "intent_response"
        assert response.payload.get("denied") is True
        assert response.payload.get("reason") == "deny_all"

    async def test_an_empty_result_set_from_no_subscriber_is_still_reported_as_empty(
        self,
    ):
        """The control. Without it, a fix that labels every empty response a
        denial passes the test above and lies to every peer."""
        bus = IntentBus(SignalManager())
        bridge, transport = _make_bridge(bus)
        overlay.register_pre_intent_authorization_hook("allow_all", _allow)

        await bridge.handle_inbound(_inbound_request())

        _, response = transport.sent[0]
        assert response.payload.get("results") == []
        assert "denied" not in response.payload, (
            "an ordinary empty result set was relabelled as a policy denial"
        )
        assert "error" not in response.payload

    async def test_the_peer_can_tell_a_denial_from_a_transport_failure(self):
        denied_bus = IntentBus(SignalManager())
        denied_bridge, denied_transport = _make_bridge(denied_bus)
        overlay.register_pre_intent_authorization_hook("deny_all", _deny)
        await denied_bridge.handle_inbound(_inbound_request())

        overlay._PRE_INTENT_AUTH_HOOKS.clear()
        failing_bridge, failing_transport = _make_bridge(_RaisingBus(SignalManager()))
        await failing_bridge.handle_inbound(_inbound_request())

        _, denial = denied_transport.sent[0]
        _, failure = failing_transport.sent[0]

        assert denial.payload.get("denied") is True
        assert "error" not in denial.payload
        assert failure.payload.get("error") == "RuntimeError"
        assert "denied" not in failure.payload, (
            "a local fault was reported to the peer as a policy refusal"
        )


class TestAFailureStillProducesAResponse:
    async def test_an_exception_from_handle_inbound_still_produces_a_response(self):
        bridge, transport = _make_bridge(_RaisingBus(SignalManager()))
        overlay.register_pre_intent_authorization_hook("allow_all", _allow)

        await bridge.handle_inbound(_inbound_request())

        assert len(transport.sent) == 1, (
            "the exception escaped and no intent_response was sent; the peer "
            "waits out its timeout with a local fault as the cause"
        )
        _, response = transport.sent[0]
        assert response.type == "intent_response"
        assert response.payload.get("error") == "RuntimeError"
        assert response.payload.get("results") == []

    async def test_a_cancelled_inbound_broadcast_still_propagates(self):
        """Cancellation is lifecycle control, not a peer-reportable failure."""

        class _CancelledBus(IntentBus):
            async def broadcast(
                self, intent, timeout=None, *, federated=True, raise_on_denial=False
            ):
                raise asyncio.CancelledError()

        bridge, transport = _make_bridge(_CancelledBus(SignalManager()))
        overlay.register_pre_intent_authorization_hook("allow_all", _allow)

        with pytest.raises(asyncio.CancelledError):
            await bridge.handle_inbound(_inbound_request())

        assert transport.sent == []

    async def test_the_transport_does_not_let_a_handler_exception_escape(self):
        """The last-resort net: nothing may reach the NATS subscription wrapper."""
        transport = NATSFederationTransport.__new__(NATSFederationTransport)
        transport._node_id = "node-a"
        transport._response_queues = {}

        async def _boom(_message: FederationMessage) -> None:
            raise RuntimeError("handler exploded")

        transport._inbound_handler = _boom

        class _Msg:
            data = {
                "type": "intent_request",
                "source_node": "node-b",
                "message_id": "m-1",
                "payload": {},
                "timestamp": 0.0,
            }

        await transport._on_intent_message(_Msg())  # must not raise

    async def test_the_transport_still_propagates_cancellation(self):
        transport = NATSFederationTransport.__new__(NATSFederationTransport)
        transport._node_id = "node-a"
        transport._response_queues = {}

        async def _cancel(_message: FederationMessage) -> None:
            raise asyncio.CancelledError()

        transport._inbound_handler = _cancel

        class _Msg:
            data = {
                "type": "intent_request",
                "source_node": "node-b",
                "message_id": "m-1",
                "payload": {},
                "timestamp": 0.0,
            }

        with pytest.raises(asyncio.CancelledError):
            await transport._on_intent_message(_Msg())


class TestTheAllowedAndDirectedPathsAreUnchanged:
    async def test_an_allowed_inbound_intent_is_unchanged_byte_for_byte(self):
        async def _handler(intent: IntentMessage) -> IntentResult:
            return IntentResult(
                intent_id=intent.id,
                agent_id="agent-1",
                success=True,
                result="answered",
                confidence=0.9,
            )

        bus = IntentBus(SignalManager())
        bus.subscribe("agent-1", _handler)
        bridge, transport = _make_bridge(bus)
        overlay.register_pre_intent_authorization_hook("allow_all", _allow)

        await bridge.handle_inbound(_inbound_request())

        _, response = transport.sent[0]
        assert response.payload == {
            "results": [
                {
                    "intent_id": "fed-1",
                    "agent_id": "agent-1",
                    "success": True,
                    "result": "answered",
                    "error": None,
                    "confidence": 0.9,
                }
            ]
        }, "the allowed payload gained or lost a key"

    async def test_the_directed_federation_path_is_not_altered(self):
        """``_directed_error`` already degrades honestly; AD-1276 does not
        touch it, and this pins that."""
        bus = IntentBus(SignalManager())
        bridge, _ = _make_bridge(bus)
        intent = IntentMessage(
            intent="direct_message",
            params={},
            id="d-1",
            target_agent_id="agent-1",
        )

        error = bridge._directed_error(intent, "federation_peer_timeout")

        assert error.success is False
        assert error.error == "federation_peer_timeout"
        assert error.intent_id == "d-1"
        assert error.agent_id == "agent-1"
