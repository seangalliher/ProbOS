"""ZeroMQ federation transport — real network communication between ProbOS nodes.

NOT tested in the test suite — all federation tests use MockFederationTransport.
This module requires ``pyzmq`` (``pip install pyzmq``).

Uses ZeroMQ DEALER-ROUTER sockets:
- This node binds a ROUTER socket on ``bind_address``.
- For each peer, a DEALER socket connects to the peer's ROUTER address.
- Messages are JSON-serialized FederationMessage payloads.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Callable, Awaitable
from typing import Any

from probos.config import PeerConfig
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

try:
    import zmq
    import zmq.asyncio
    _HAS_ZMQ = True
except ImportError:
    _HAS_ZMQ = False


class FederationTransport:
    """ZeroMQ-based federation transport.

    Provides the same interface as MockFederationTransport so FederationBridge
    can use either interchangeably.
    """

    def __init__(
        self,
        node_id: str,
        bind_address: str,
        peers: list[PeerConfig],
    ) -> None:
        if not _HAS_ZMQ:
            raise ImportError("pyzmq is required for FederationTransport")

        self._node_id = node_id
        self._bind_address = bind_address
        self._peers_config = peers
        self._running = False
        self._inbound_handler: Callable[[FederationMessage], Awaitable[None]] | None = None
        self._response_queues: dict[str, asyncio.Queue[FederationMessage]] = {}
        self._pending_requests: dict[
            tuple[str, str], asyncio.Future[FederationMessage]
        ] = {}
        self._request_admission_open = True

        self._ctx: zmq.asyncio.Context | None = None
        self._router_socket: zmq.asyncio.Socket | None = None
        self._dealer_sockets: dict[str, zmq.asyncio.Socket] = {}
        self._recv_task: asyncio.Task | None = None

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def connected_peers(self) -> list[str]:
        """Return list of configured peer node IDs."""
        return list(self._dealer_sockets.keys())

    async def start(self) -> None:
        """Bind ROUTER socket and connect DEALER sockets to all peers."""
        self._request_admission_open = False
        try:
            self._ctx = zmq.asyncio.Context()

            # ROUTER: accepts incoming connections from other nodes' DEALER sockets
            self._router_socket = self._ctx.socket(zmq.ROUTER)
            self._router_socket.bind(self._bind_address)
            logger.info("Federation ROUTER bound: %s", self._bind_address)

            # DEALER: one per peer, connects to peer's ROUTER
            for peer in self._peers_config:
                dealer = self._ctx.socket(zmq.DEALER)
                dealer.setsockopt(zmq.IDENTITY, self._node_id.encode())
                dealer.connect(peer.address)
                self._dealer_sockets[peer.node_id] = dealer
                logger.info("Federation DEALER connected to %s at %s", peer.node_id, peer.address)

            self._running = True
            self._recv_task = asyncio.create_task(
                self._recv_loop(), name="federation-recv"
            )
        except BaseException:
            self._running = False
            for dealer in self._dealer_sockets.values():
                dealer.close(linger=0)
            self._dealer_sockets.clear()
            if self._router_socket:
                self._router_socket.close(linger=0)
                self._router_socket = None
            if self._ctx:
                self._ctx.term()
                self._ctx = None
            raise
        self._request_admission_open = True

    async def stop(self) -> None:
        """Close all sockets and the context."""
        self._request_admission_open = False
        self._running = False
        pending_requests = tuple(self._pending_requests.values())
        self._pending_requests.clear()
        for pending in pending_requests:
            if not pending.done():
                pending.cancel()
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass

        for dealer in self._dealer_sockets.values():
            dealer.close(linger=0)
        self._dealer_sockets.clear()

        if self._router_socket:
            self._router_socket.close(linger=0)
        if self._ctx:
            self._ctx.term()
        logger.info("Federation transport stopped")

    async def send_to_peer(self, peer_node_id: str, message: FederationMessage) -> None:
        """Send a message to a specific peer via its DEALER socket."""
        dealer = self._dealer_sockets.get(peer_node_id)
        if dealer is None:
            logger.debug("No DEALER for peer %s", peer_node_id)
            return
        payload = self._serialize(message)
        await dealer.send(payload)

    async def send_to_all_peers(self, message: FederationMessage) -> list[str]:
        """Send a message to all connected peers."""
        payload = self._serialize(message)
        sent: list[str] = []
        for peer_id, dealer in self._dealer_sockets.items():
            try:
                await dealer.send(payload)
                sent.append(peer_id)
            except Exception as e:
                logger.debug("Failed to send to %s: %s", peer_id, e)
        return sent

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
        if not getattr(self, "_request_admission_open", True):
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

    async def _recv_loop(self) -> None:
        """Listen for incoming messages on the ROUTER socket."""
        while self._running:
            try:
                # ROUTER receives [identity, payload]
                frames = await self._router_socket.recv_multipart()
                if len(frames) < 2:
                    continue

                identity = frames[0].decode()
                payload = frames[-1]
                message = self._deserialize(payload)

                if message.type == "intent_response":
                    # Route to the pending request's response queue
                    await self.deliver_response(message.source_node, message)
                elif self._inbound_handler:
                    await self._inbound_handler(message)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Recv loop error: %s", e)

    def _serialize(self, message: FederationMessage) -> bytes:
        """Serialize a FederationMessage to JSON bytes."""
        data = {
            "type": message.type,
            "source_node": message.source_node,
            "message_id": message.message_id,
            "payload": message.payload,
            "timestamp": message.timestamp,
        }
        return json.dumps(data).encode()

    def _deserialize(self, data: bytes) -> FederationMessage:
        """Deserialize JSON bytes to a FederationMessage."""
        obj = json.loads(data.decode())
        return FederationMessage(
            type=obj["type"],
            source_node=obj["source_node"],
            message_id=obj.get("message_id", uuid.uuid4().hex),
            payload=obj.get("payload", {}),
            timestamp=obj.get("timestamp", 0.0),
        )
