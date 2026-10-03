"""AD-1198 slice 3a: signed peer HTTP requests -- a federation envelope carried in an HTTP body.

A peer request is an AD-1197 envelope that the sending ship seals for one pinned peer: its topic names
the operation and its payload binds the operation's arguments. The serving ship authenticates it as an
inbound envelope -- peer admission (a pinned peer, signed) and the envelope guard (the signature under the
held key history, the pin rule and the durable replay window) -- so no bearer secret is shared with a peer
and each request is accepted once. Peer requests exist only while ``federation.peer_admission_enabled`` is
armed, and a peer-request topic is never accepted over the bridge. The body is the envelope's wire form
(``type``, ``source_node``, ``message_id``, ``payload``, ``timestamp``, ``auth``): a header cannot carry it,
because a 32-event key history makes it about 30 KB. Nothing here reads a clock -- freshness is the replay
window's (AD-1197).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol

from probos.federation.envelope import ATTACHMENT_REQUEST, MAX_AUTH_BYTES, PEER_REQUEST_TOPICS
from probos.federation.mcp_server import strict_json_loads
from probos.types import FederationMessage

__all__ = [
    "ATTACHMENT_REQUEST",
    "MAX_PEER_REQUEST_BYTES",
    "PEER_REQUEST_TOPICS",
    "PeerRequestSeam",
    "PeerRequests",
    "decode_peer_request",
    "encode_peer_request",
]

logger = logging.getLogger(__name__)

MAX_PEER_REQUEST_BYTES = MAX_AUTH_BYTES + 4_096  # the signature block's bound plus a small payload (3a: one hash)
_WIRE_MEMBERS = frozenset({"type", "source_node", "message_id", "payload", "timestamp", "auth"})


class PeerRequestSeam(Protocol):
    """What peer requests need from the armed federation seam; ``SignedPeerRequestSeam`` satisfies it."""

    @property
    def node_id(self) -> str: ...

    async def seal_request(self, peer_node_id: str, message: FederationMessage) -> FederationMessage | None: ...

    async def admit_request(self, message: object) -> bool: ...


def encode_peer_request(message: FederationMessage) -> bytes:
    """The HTTP body carrying a sealed peer request; raises ``ValueError`` for an unsigned one."""
    if message.auth is None:
        raise ValueError("a peer request is never unsigned")
    return json.dumps({
        "type": message.type, "source_node": message.source_node, "message_id": message.message_id,
        "payload": message.payload, "timestamp": message.timestamp, "auth": message.auth,
    }).encode()


def decode_peer_request(body: object) -> FederationMessage | None:
    """The sealed peer request ``body`` carries, or ``None`` for any body this server does not accept.

    Never raises: a bounded size, strict JSON (no NaN, Infinity or overflowing number), exactly the six wire
    members, string identifiers, a numeric timestamp, an object payload and an object signature block.
    """
    if type(body) is not bytes or len(body) > MAX_PEER_REQUEST_BYTES:  # AD-1198 a bounded body
        return None
    try:
        data = strict_json_loads(body)
    except (ValueError, RecursionError):
        return None
    if type(data) is not dict or frozenset(data) != _WIRE_MEMBERS:  # AD-1198 exactly the envelope's wire members
        return None
    kind, source, message_id = data["type"], data["source_node"], data["message_id"]
    payload, timestamp, auth = data["payload"], data["timestamp"], data["auth"]
    if type(kind) is not str or type(source) is not str or type(message_id) is not str:
        return None
    if type(payload) is not dict or type(auth) is not dict or type(timestamp) not in (int, float):
        return None
    return FederationMessage(
        type=kind, source_node=source, message_id=message_id, payload=payload, timestamp=timestamp, auth=auth,
    )


class PeerRequests:
    """Signs this ship's peer requests and authenticates its peers' (AD-1198 slice 3a)."""

    def __init__(self, seam: PeerRequestSeam) -> None:
        self._seam = seam
        self._refusals: dict[str, int] = {}

    @property
    def refusal_counts(self) -> dict[str, int]:
        """How many peer requests were refused here, by reason (a copy); the seam and the guard count their own."""
        return dict(self._refusals)

    async def sign(self, peer_node_id: str, topic: str, payload: Mapping[str, Any]) -> bytes | None:
        """The body of a peer request for ``peer_node_id``, or ``None`` when it cannot be signed -- never unsigned."""
        if topic not in PEER_REQUEST_TOPICS:
            raise ValueError(f"{topic!r} is not a peer request topic")
        message = FederationMessage(type=topic, source_node=self._seam.node_id, payload=dict(payload))
        sealed = await self._seam.seal_request(peer_node_id, message)
        if sealed is None:
            return None
        body = encode_peer_request(sealed)
        if decode_peer_request(body) is None:  # AD-1198 never send a body the server's own parser refuses
            return None
        return body

    async def authenticate(self, body: bytes, *, topic: str, payload: Mapping[str, Any]) -> str | None:
        """The pinned peer that sent ``body`` for ``topic`` with exactly ``payload``, or ``None`` when refused.

        The topic and the payload are checked before any envelope state is read or written; the seam then
        admits the request exactly as an inbound envelope (peer admission, then the guard's verification,
        replay window and record). Refusals here are counted and logged, sampled per reason; the seam and the
        guard log theirs.
        """
        message = decode_peer_request(body)
        if message is None:
            return self._refused(topic, None, "malformed")
        if message.type != topic or topic not in PEER_REQUEST_TOPICS:  # AD-1198 a request authenticates only its own operation
            return self._refused(topic, message.source_node, "topic")
        if message.payload != dict(payload):  # AD-1198 the signed payload binds the operation's arguments
            return self._refused(topic, message.source_node, "arguments")
        if not await self._seam.admit_request(message):  # AD-1198 verified and recorded as an inbound envelope
            return self._refused(topic, message.source_node, "not admitted")
        return message.source_node

    def _refused(self, topic: str, source: str | None, reason: str) -> None:
        count = self._refusals.get(reason, 0) + 1
        self._refusals[reason] = count
        if count & (count - 1) == 0:  # AD-1198 sampled: the 1st, 2nd, 4th, 8th ... refusal of a reason
            logger.warning(
                "AD-1198: peer request %r from %r refused (%s); %d refused for that reason so far",
                topic[:64], "?" if source is None else source[:64], reason, count,
            )
        return None
