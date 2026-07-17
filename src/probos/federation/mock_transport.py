"""In-memory federation transport for testing.

Simulates multi-node communication without ZeroMQ.
Messages are routed through an in-memory message bus.
Multiple MockFederationTransport instances can be wired together
via a shared MockTransportBus.
"""

from __future__ import annotations

import asyncio
import logging
import re
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


class MockTransportBus:
    """Shared message bus connecting multiple MockFederationTransport instances.

    Instantiate one bus, pass it to each MockFederationTransport.
    Messages sent to a peer are delivered to that peer's inbound queue.
    """

    def __init__(self) -> None:
        self._transports: dict[str, MockFederationTransport] = {}
        self._queues: dict[str, asyncio.Queue[FederationMessage]] = {}

    def register(self, transport: MockFederationTransport) -> None:
        """Register a transport so it can receive messages."""
        self._transports[transport.node_id] = transport
        self._queues[transport.node_id] = asyncio.Queue()

    async def deliver(self, target_node_id: str, message: FederationMessage) -> None:
        """Deliver a message to a target node's inbound queue."""
        queue = self._queues.get(target_node_id)
        if queue is None:
            logger.debug("Cannot deliver to unregistered node: %s", target_node_id)
            return
        await queue.put(message)

        # If the target transport has an inbound handler, call it
        transport = self._transports.get(target_node_id)
        if transport and transport._inbound_handler:
            try:
                await transport._inbound_handler(message)
            except Exception as e:
                logger.debug("Inbound handler error on %s: %s", target_node_id, e)


class MockFederationTransport:
    """In-memory federation transport for testing.

    Simulates multi-node communication without ZeroMQ.
    """

    def __init__(self, node_id: str, bus: MockTransportBus) -> None:
        self._node_id = node_id
        self._bus = bus
        self._running = False
        self._inbound_handler: Callable[[FederationMessage], Awaitable[None]] | None = None
        self._response_queues: dict[str, asyncio.Queue[FederationMessage]] = {}
        self._pending_requests: dict[
            tuple[str, str], asyncio.Future[FederationMessage]
        ] = {}
        self._request_admission_open = True

        # Register with bus
        bus.register(self)

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def connected_peers(self) -> list[str]:
        """Return list of peer node IDs registered on the bus (excluding self)."""
        return [nid for nid in self._bus._transports if nid != self._node_id]

    async def start(self) -> None:
        """Start the mock transport."""
        self._running = True
        self._request_admission_open = True

    async def stop(self) -> None:
        """Stop the mock transport."""
        self._request_admission_open = False
        self._running = False
        pending_requests = tuple(self._pending_requests.values())
        self._pending_requests.clear()
        for pending in pending_requests:
            if not pending.done():
                pending.cancel()

    async def add_peer(self, peer_config: Any) -> bool:
        """AD-479h: idempotent peer add hook for runtime discovery.

        Mock returns True for any new peer registration; the actual transport
        bus does its own peer tracking via ``register()``. Returns False when
        the peer is already known.
        """
        node_id = getattr(peer_config, "node_id", None)
        if node_id is None and isinstance(peer_config, dict):
            node_id = peer_config.get("node_id")
        if node_id is None:
            return False
        if node_id in self.connected_peers or node_id == self._node_id:
            return False
        return True

    async def send_to_peer(self, peer_node_id: str, message: FederationMessage) -> None:
        """Send a message to a specific peer via the bus."""
        await self._bus.deliver(peer_node_id, message)

    async def send_to_all_peers(self, message: FederationMessage) -> list[str]:
        """Send a message to all connected peers. Returns list of peer IDs sent to."""
        peers = self.connected_peers
        for peer_id in peers:
            await self._bus.deliver(peer_id, message)
        return peers

    async def receive_with_timeout(
        self, peer_node_id: str, timeout_ms: int
    ) -> FederationMessage | None:
        """Wait for a response from a specific peer. Returns None on timeout."""
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
        """Deliver a response message to the appropriate response queue.

        Used by the bridge when handling inbound responses.
        """
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
