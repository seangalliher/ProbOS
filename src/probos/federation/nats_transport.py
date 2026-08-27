"""NATS federation transport — replaces ZeroMQ DEALER-ROUTER (AD-637e).

Uses NATS pub/sub for inter-instance communication via unprefixed
(raw) subjects, bypassing per-ship subject_prefix isolation.
Requires NATSBus (AD-637a) to be started before federation.

Topology prerequisite: federated ProbOS instances must share a NATS
namespace (same server, cluster, or leaf-node mesh). Without shared
NATS infrastructure, messages cannot reach remote ships. ZeroMQ
fallback remains available for direct TCP peer connections.

When using NATS transport, PeerConfig.address is ignored. Peer
reachability depends on NATS cluster topology, not explicit TCP addresses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Callable, Awaitable
from typing import Any

from probos.types import FederationMessage

logger = logging.getLogger(__name__)

_DIRECTED_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_DIRECTED_CORRELATION_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
)


def _is_safe_node_id(value: Any) -> bool:
    return type(value) is str and _DIRECTED_NODE_ID_RE.fullmatch(value) is not None


def _is_safe_correlation_id(value: Any) -> bool:
    return (
        type(value) is str
        and _DIRECTED_CORRELATION_ID_RE.fullmatch(value) is not None
    )


def _is_targeted_directed_response(payload: Any) -> bool:
    if type(payload) is not dict:
        return False
    for key, value in dict.items(payload):
        if type(key) is not str or key != "delivery_mode":
            continue
        return type(value) is str and value == "targeted_dm"
    return False


class NATSFederationTransport:
    """NATS-based federation transport.

    Provides the same interface as FederationTransport / MockFederationTransport
    so FederationBridge can use any interchangeably.

    Design:
    - send_to_peer() publishes to ``federation.intent.{peer_node_id}``
    - send_to_all_peers() publishes to ``federation.gossip``
    - Each node subscribes to its own ``federation.intent.{node_id}`` + ``federation.gossip``
    - All subjects are unprefixed (publish_raw/subscribe_raw) because federation
      crosses ship boundaries with different subject_prefix values.

    connected_peers semantic note: Returns configured peer IDs when NATS is
    connected. NATS pub/sub has no per-peer connection state — an unreachable
    peer is invisible. Gossip-based liveness is a future enhancement.

    Note: _inbound_handler is set directly by FederationBridge.start().
    This is a known interface contract shared with FederationTransport
    and MockFederationTransport (bridge.py:59).
    """

    def __init__(
        self,
        node_id: str,
        nats_bus: Any,
        peer_node_ids: list[str],
    ) -> None:
        self._node_id = node_id
        self._nats_bus = nats_bus
        self._peer_node_ids = peer_node_ids
        self._running = False
        self._inbound_handler: (
            Callable[[FederationMessage], Awaitable[None]] | None
        ) = None
        self._response_queues: dict[str, asyncio.Queue[FederationMessage]] = {}
        self._pending_requests: dict[
            tuple[str, str], asyncio.Future[FederationMessage]
        ] = {}
        self._request_admission_open = True
        self._subscriptions: list[Any] = []

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def connected_peers(self) -> list[str]:
        """Return configured peer node IDs when NATS is connected.

        Note: This does NOT verify per-peer reachability. NATS pub/sub
        has no per-peer connection state. Unreachable peers are invisible.
        Gossip-based liveness tracking is a future enhancement.
        """
        if not self._nats_bus.connected:
            return []
        return list(self._peer_node_ids)

    async def start(self) -> None:
        """Subscribe to gossip and intent subjects for this node."""
        self._request_admission_open = False
        try:
            # Subscribe to gossip from all peers
            gossip_sub = await self._nats_bus.subscribe_raw(
                "federation.gossip", self._on_gossip_message
            )
            if gossip_sub is None:
                logger.warning("AD-637e: Failed to subscribe to federation.gossip — NATS may have disconnected")
            else:
                self._subscriptions.append(gossip_sub)

            # Subscribe to intents/responses addressed to this node
            intent_sub = await self._nats_bus.subscribe_raw(
                f"federation.intent.{self._node_id}", self._on_intent_message
            )
            if intent_sub is None:
                logger.warning("AD-637e: Failed to subscribe to federation.intent.%s", self._node_id)
            else:
                self._subscriptions.append(intent_sub)

            self._running = True
        except BaseException:
            self._running = False
            raise
        self._request_admission_open = True
        logger.info("AD-637e: NATS federation transport started (node=%s, peers=%s)",
                     self._node_id, self._peer_node_ids)

    async def stop(self) -> None:
        """Stop federation transport."""
        self._request_admission_open = False
        self._running = False
        pending_requests = tuple(self._pending_requests.values())
        self._pending_requests.clear()
        for pending in pending_requests:
            if not pending.done():
                pending.cancel()
        self._subscriptions.clear()
        logger.info("AD-637e: NATS federation transport stopped")

    async def send_to_peer(self, peer_node_id: str, message: FederationMessage) -> None:
        """Send a message to a specific peer via NATS."""
        data = self._serialize(message)
        try:
            await self._nats_bus.publish_raw(
                f"federation.intent.{peer_node_id}", data
            )
        except Exception as e:
            logger.debug("AD-637e: Failed to send to peer %s: %s", peer_node_id, e)

    async def send_to_all_peers(self, message: FederationMessage) -> list[str]:
        """Send a message to all peers via gossip subject."""
        data = self._serialize(message)
        try:
            await self._nats_bus.publish_raw("federation.gossip", data)
        except Exception as e:
            logger.debug("AD-637e: Failed to publish gossip: %s", e)
        return list(self._peer_node_ids)

    async def receive_with_timeout(
        self, peer_node_id: str, timeout_ms: int
    ) -> FederationMessage | None:
        """Wait for a response from a specific peer."""
        queue = self._response_queues.get(peer_node_id)
        if queue is None:
            queue = asyncio.Queue()
            self._response_queues[peer_node_id] = queue

        try:
            return await asyncio.wait_for(
                queue.get(), timeout=timeout_ms / 1000.0
            )
        except asyncio.TimeoutError:
            return None

    async def request_peer(
        self,
        peer_node_id: str,
        message: FederationMessage,
        timeout_ms: int,
    ) -> FederationMessage | None:
        """Send one message and wait for its exact peer/message response."""
        if (
            not isinstance(message, FederationMessage)
            or not _is_safe_node_id(peer_node_id)
            or not _is_safe_correlation_id(message.message_id)
        ):
            raise ValueError("federation_correlation_id_invalid")
        if not self._request_admission_open:
            raise RuntimeError("federation_transport_closed")
        key = (peer_node_id, message.message_id)
        if key in self._pending_requests:
            raise RuntimeError("federation_request_key_in_use")
        pending = asyncio.get_running_loop().create_future()
        self._pending_requests[key] = pending
        try:
            await self.send_to_peer(peer_node_id, message)
            return await asyncio.wait_for(
                asyncio.shield(pending), timeout=timeout_ms / 1000.0
            )
        except asyncio.TimeoutError:
            return None
        except asyncio.CancelledError:
            raise
        finally:
            if self._pending_requests.get(key) is pending:
                self._pending_requests.pop(key, None)
            if not pending.done():
                pending.cancel()

    async def deliver_response(self, from_node_id: str, message: FederationMessage) -> None:
        """Deliver a response message to the appropriate response queue."""
        directed = _is_targeted_directed_response(message.payload)
        pending = None
        if _is_safe_node_id(from_node_id) and _is_safe_correlation_id(
            message.message_id
        ):
            pending = self._pending_requests.get(
                (from_node_id, message.message_id)
            )
        if pending is not None:
            if not pending.done():
                pending.set_result(message)
            return
        if directed:
            return
        queue = self._response_queues.get(from_node_id)
        if queue is None:
            queue = asyncio.Queue()
            self._response_queues[from_node_id] = queue
        await queue.put(message)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _on_intent_message(self, nats_msg: Any) -> None:
        """Handle inbound intent/response/ping/pong messages."""
        message = self._deserialize(nats_msg.data)

        if message.type == "intent_response":
            # Route to pending request's response queue
            await self.deliver_response(message.source_node, message)
        elif self._inbound_handler:
            # AD-1276: bounded. Anything raising out of
            # ``FederationBridge.handle_inbound`` used to escape into the NATS
            # subscription wrapper, no ``intent_response`` was ever sent, and
            # the peer waited out its own timeout with no local record of why.
            # A handler that fails is reported here as a failure; whether a
            # reply is owed is the bridge's question, not the transport's, and
            # the bridge answers it on the paths that have one.
            try:
                await self._inbound_handler(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error(
                    "Federation inbound handler failed for %s from %s "
                    "(message_id=%s); the peer will not receive a response to "
                    "this message and will time out",
                    message.type, message.source_node, message.message_id,
                    exc_info=True,
                )

    async def _on_gossip_message(self, nats_msg: Any) -> None:
        """Handle inbound gossip messages. Filters self-gossip."""
        message = self._deserialize(nats_msg.data)
        # Don't process our own gossip
        if message.source_node == self._node_id:
            return
        if self._inbound_handler:
            await self._inbound_handler(message)

    def _serialize(self, message: FederationMessage) -> dict[str, Any]:
        """Serialize a FederationMessage to a dict (NATSBus handles JSON encoding)."""
        return {
            "type": message.type,
            "source_node": message.source_node,
            "message_id": message.message_id,
            "payload": message.payload,
            "timestamp": message.timestamp,
        }

    def _deserialize(self, data: dict[str, Any]) -> FederationMessage:
        """Deserialize a dict to a FederationMessage."""
        return FederationMessage(
            type=data["type"],
            source_node=data["source_node"],
            message_id=data.get("message_id", uuid.uuid4().hex),
            payload=data.get("payload", {}),
            timestamp=data.get("timestamp", 0.0),
        )
