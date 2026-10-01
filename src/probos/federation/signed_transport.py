"""AD-1197: the signed federation transport -- the seam where envelopes are sealed and admitted.

Wraps a ZeroMQ, NATS or mock federation transport. Every outbound envelope is
sealed by the node's :class:`~probos.federation.envelope.EnvelopeGuard`; every
inbound request and one-way message is admitted by it before the bridge sees it;
the response topics the bridge only queues are admitted once, where they are
consumed. Policy lives in the guard; this module only routes.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

from probos.federation.envelope import (
    BROADCAST,
    RESPONSE_TOPICS,
    EnvelopeGuard,
    EnvelopeNotSent,
    EnvelopeRejected,
    EnvelopeSigner,
)
from probos.federation_envelope_store import ENVELOPE_DB_NAME, EnvelopeStore
from probos.types import FederationMessage

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory


class SignedFederationTransport:
    """A federation transport that seals every outbound envelope and admits every inbound one (AD-1197).

    Wraps ZeroMQ, NATS or the mock transport and offers the bridge exactly the
    members it uses (bridge.py: _inbound_handler, connected_peers, send_to_peer,
    send_to_all_peers, receive_with_timeout, request_peer, deliver_response, and
    add_peer by getattr). Requests and one-way messages are verified before
    dispatch; the response topics the bridge only queues are verified once, where
    they are consumed. Policy lives in the guard.
    """

    def __init__(self, inner: Any, guard: EnvelopeGuard) -> None:
        self._inner = inner
        self._guard = guard
        self._handler: Any = None
        self._inner_started = False

    @property
    def node_id(self) -> str:
        """The wrapped transport's node id."""
        return self._inner.node_id

    @property
    def connected_peers(self) -> list[str]:
        """The wrapped transport's peers, or none while the guard accepts no traffic."""
        return self._inner.connected_peers if self._guard.accepts_traffic else []

    @property
    def _inbound_handler(self) -> Any:
        return self._handler

    @_inbound_handler.setter
    def _inbound_handler(self, handler: Any) -> None:
        self._handler = handler
        self._inner._inbound_handler = self._on_inbound if handler is not None else None

    async def start(self) -> None:
        """Start the guard, then the wrapped transport -- unless the guard keeps federation closed."""
        await self._guard.start()
        if not self._guard.accepts_traffic:  # AD-1197 a closed guard starts no transport
            return
        try:
            await self._inner.start()
        except BaseException:
            await self._guard.stop()
            raise
        self._inner_started = True

    async def stop(self) -> None:
        """Stop the wrapped transport (when this started it), then the guard."""
        try:
            if self._inner_started:
                await self._inner.stop()
        finally:
            self._inner_started = False
            await self._guard.stop()

    async def send_to_peer(self, peer_node_id: str, message: FederationMessage) -> None:
        """Seal ``message`` for ``peer_node_id`` and send it; a message the guard refuses is not sent."""
        sealed = await self._guard.seal(message, peer_node_id)
        if sealed is None:
            return
        await self._inner.send_to_peer(peer_node_id, sealed)

    async def send_to_all_peers(self, message: FederationMessage) -> list[str]:
        """Seal ``message`` for every peer and broadcast it; returns the peers sent to (none when refused)."""
        sealed = await self._guard.seal(message, BROADCAST)
        if sealed is None:
            return []
        return await self._inner.send_to_all_peers(sealed)

    async def receive_with_timeout(self, peer_node_id: str, timeout_ms: int) -> FederationMessage | None:
        """The next admitted message from ``peer_node_id`` within ``timeout_ms``, or ``None``.

        Messages from any other peer, replays and forgeries are discarded while the
        genuine message may still arrive. The deadline is a local timeout, never a
        judgement of an envelope.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_ms / 1000.0
        while True:
            remaining_ms = math.ceil((deadline - loop.time()) * 1000.0)
            if remaining_ms <= 0:
                return None
            message = await self._inner.receive_with_timeout(peer_node_id, remaining_ms)
            if message is None:
                return None
            if type(message) is not FederationMessage or message.source_node != peer_node_id:  # AD-1197 only the peer asked
                continue
            if await self._guard.admit(message):  # AD-1197 a response is verified where it is consumed
                return message

    async def request_peer(
        self, peer_node_id: str, message: FederationMessage, timeout_ms: int,
    ) -> FederationMessage | None:
        """Seal and send a request, then admit the directed response.

        Raises :class:`EnvelopeNotSent` when the request cannot be signed under a
        policy that sends nothing unsigned, and :class:`EnvelopeRejected` when the
        response fails verification.
        """
        sealed = await self._guard.seal(message, peer_node_id)
        if sealed is None:
            raise EnvelopeNotSent("the envelope could not be signed, and nothing unsigned is sent")
        response = await self._inner.request_peer(peer_node_id, sealed, timeout_ms)
        if response is not None and not await self._guard.admit(response):  # AD-1197 directed response
            raise EnvelopeRejected("the directed response failed envelope verification")
        return response

    async def deliver_response(self, from_node_id: str, message: FederationMessage) -> None:
        """Queue a response for consumption; it is verified where it is consumed."""
        await self._inner.deliver_response(from_node_id, message)

    def __getattr__(self, name: str) -> Any:
        if name == "add_peer":
            return getattr(self._inner, name)
        raise AttributeError(name)

    async def _on_inbound(self, message: Any) -> None:
        handler = self._handler
        if handler is None:
            return
        if type(message) is FederationMessage and type(message.type) is str and message.type in RESPONSE_TOPICS:
            await handler(message)  # queued by the bridge; verified where it is consumed
            return
        if not await self._guard.admit(message):  # AD-1197 verify before dispatch
            return
        await handler(message)


def build_signed_transport(
    inner: Any,
    *,
    policy: str,
    key_binding: EnvelopeSigner | None,
    data_dir: Path,
    connection_factory: ConnectionFactory | None = None,
) -> SignedFederationTransport:
    """The armed transport: ``inner`` wrapped, with a guard over the ship key and the node's replay store."""
    if key_binding is None:
        raise ValueError("federation envelope signing needs the ship key binding (federation.identity_keys_enabled)")
    store = EnvelopeStore(Path(data_dir) / ENVELOPE_DB_NAME, connection_factory=connection_factory)
    guard = EnvelopeGuard(signer=key_binding, store=store, local_node_id=inner.node_id, policy=policy)
    return SignedFederationTransport(inner, guard)
