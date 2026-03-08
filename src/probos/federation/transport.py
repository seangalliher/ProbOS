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
import uuid
from collections.abc import Callable, Awaitable
from typing import Any

from probos.config import PeerConfig
from probos.types import FederationMessage

logger = logging.getLogger(__name__)

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
        self._recv_task = asyncio.create_task(self._recv_loop(), name="federation-recv")

    async def stop(self) -> None:
        """Close all sockets and the context."""
        self._running = False
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

    async def deliver_response(self, from_node_id: str, message: FederationMessage) -> None:
        """Deliver a response message to the appropriate response queue."""
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
