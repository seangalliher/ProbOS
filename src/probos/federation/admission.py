"""AD-1198: peer admission -- which nodes may federate with this one, and who they must be.

Armed by ``federation.peer_admission_enabled`` (it needs envelope signing). Only the
configured peers may then be held or delivered. A peer configured with
``pinned_public_key`` must sign every envelope, and the key history it presents must
introduce that key with no re-inception after the key's activation. The rule reads
only the keys a history introduced and its re-inception indices after the pinned
key's activation -- exactly what a carried or held run of the newest key events
contains (AD-1197 R-25) -- so a pin older than the run is refused, never guessed.
A broadcast speaks only for its sender. The seam (``SignedFederationTransport``)
asks :meth:`PeerAdmission.admits_message` before anything else; the envelope guard
asks :meth:`PeerAdmission.admits_source` and :meth:`PeerAdmission.identity_refusal`.
The HTTP seam (slice 3a) asks :meth:`PeerAdmission.admits_request` and
:meth:`PeerAdmission.pinned`: only a pinned peer is served over HTTP or sent a peer
request. Nothing here reads a clock.
"""

from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

from probos.federation.envelope import BROADCAST_TOPICS
from probos.types import FederationMessage

if TYPE_CHECKING:
    from probos.config import FederationConfig
    from probos.identity_keys import KeyState

logger = logging.getLogger(__name__)

_RAW_PUBLIC_KEY_BYTES = 32


def _raw_key(text: object) -> bytes | None:
    if type(text) is not str:
        return None
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None


def _label(value: object) -> str:
    return value[:64] if type(value) is str else type(value).__name__


class PeerAdmission:
    """The configured peers of one node and their pinned ship keys (AD-1198)."""

    def __init__(self, *, local_node_id: str, pins: Mapping[str, str]) -> None:
        if not local_node_id:
            raise ValueError("peer admission needs this node's id")
        if local_node_id in pins:
            raise ValueError("a node is not its own peer")
        decoded: dict[str, bytes] = {}
        for node_id, pin in pins.items():
            raw = _raw_key(pin) if pin else b""
            if raw is None or (pin and len(raw) != _RAW_PUBLIC_KEY_BYTES):
                raise ValueError(f"the pin for peer {_label(node_id)!r} is not a base64 raw Ed25519 public key")
            decoded[node_id] = raw
        self._local_node_id = local_node_id
        self._pins = decoded
        self._refusals: dict[str, int] = {}

    @classmethod
    def from_config(cls, federation: FederationConfig) -> PeerAdmission:
        """The admission a validated ``FederationConfig`` describes."""
        return cls(
            local_node_id=federation.node_id,
            pins={peer.node_id: peer.pinned_public_key for peer in federation.peers},
        )

    @property
    def refusal_counts(self) -> dict[str, int]:
        """How many messages the seam refused, by reason (a copy)."""
        return dict(self._refusals)

    def admits_source(self, source: str) -> bool:
        """Whether ``source`` is a configured peer: the only nodes that may be held or delivered."""
        return source in self._pins  # AD-1198 configured peers are the only sources

    def pinned(self, node_id: str) -> bool:
        """Whether ``node_id`` is a configured peer with a pinned key: the only peers a peer request goes to (AD-1198)."""
        return bool(self._pins.get(node_id))

    def identity_refusal(self, source: str, state: KeyState) -> str | None:
        """Why ``state`` does not satisfy ``source``'s pin, or ``None``; an unpinned peer is not judged here."""
        pinned = self._pins.get(source, b"")
        if not pinned:
            return None
        record = next((key for key in state.keys if _raw_key(key.public_key) == pinned), None)
        if record is None:  # AD-1198 the pinned key must be in the carried history
            return "pin (key)"
        if any(index > record.activated_at for index in state.broken_at):  # AD-1198 no re-inception after the pinned key
            return "pin (continuity)"
        return None

    def admits_message(self, message: object) -> bool:
        """Whether ``message`` may pass the seam; each refusal is counted and logged, sampled per reason."""
        if type(message) is not FederationMessage:
            return self._refused(message, "malformed")
        source = message.source_node
        if type(source) is not str or source not in self._pins:  # AD-1198 configured peers only
            return self._refused(message, "unconfigured source")
        if message.auth is None and self._pins[source]:  # AD-1198 a pinned peer always signs
            return self._refused(message, "unsigned from a pinned peer")
        payload = message.payload
        if message.type in BROADCAST_TOPICS and type(payload) is dict and payload.get("node_id", source) != source:  # AD-1198 a broadcast speaks for its sender
            return self._refused(message, "gossip names another node")
        return True

    def admits_request(self, message: object) -> bool:
        """Whether ``message`` may be served as a peer request (AD-1198 slice 3a): it passes
        :meth:`admits_message` and comes from a pinned peer -- an unpinned peer is never served over HTTP."""
        if not self.admits_message(message):
            return False
        if not self._pins[cast(FederationMessage, message).source_node]:  # AD-1198 peer requests only from pinned peers
            return self._refused(message, "request from an unpinned peer")
        return True

    def _refused(self, message: object, reason: str) -> bool:
        count = self._refusals.get(reason, 0) + 1
        self._refusals[reason] = count
        if count & (count - 1) == 0:  # AD-1198 sampled: the 1st, 2nd, 4th, 8th ... refusal of a reason
            logger.warning(
                "AD-1198: envelope %r from %r refused (%s); %d refused for that reason so far, not delivered",
                _label(getattr(message, "type", None)), _label(getattr(message, "source_node", None)), reason, count,
            )
        return False
