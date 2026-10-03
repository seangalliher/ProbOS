"""AD-1197: federation envelope statements, signature blocks, replay windows and the guard.

What is signed. Every federation message a node sends is sealed with a detached
RFC 7515 JWS (``typ`` ``probos-envelope+jws``) by the ship's active AD-1196 key over
the RFC 8785 form of a twelve-member statement: the topic, source, target, message
id and timestamp, the SHA-256 of the body's RFC 8785 form, the send epoch and
sequence, and the signing key's history length and head digest. The signature block
(``FederationMessage.auth``) carries the target, the counters, that key state, the
JWS and the newest key events of the sender's history (all of them while there are
at most 32).

What is verified. A receiver recomputes the statement from the message it holds,
replays the events it does not hold from the history it holds for that source -- at
first contact from the oldest event carried -- and keeps the newest 32, never
changing an event it holds. It records the id of every key it verifies for a source
and refuses an event that reintroduces one, as AD-1196's full replay does. It
verifies the JWS under the active key of the held history and admits the envelope
through a durable 64-wide replay window per source and channel, ordered by key
history, epoch and sequence, recorded before the message is delivered. Timestamps
are signed and never judged: nothing here reads a clock.

This module's logger records no signature, key-event history, epoch or sequence.
The store's SQL parameters -- public key events and window counters, never a private
key -- reach the third-party ``aiosqlite`` logger at DEBUG; ProbOS runs that logger
at WARNING (``__main__.py:175``).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from probos.federation.ard.jcs import canonicalize
from probos.federation.ard.jws import parse_detached
from probos.federation_envelope_store import StoredSender, StoredWindow
from probos.identity_keys import (
    ENVELOPE_JWS_TYP,
    STATUS_ACTIVE,
    EnvelopeSignature,
    KeyEvent,
    KeyEventInvalid,
    KeyState,
    canonical_bytes,
    derive_key_state,
    event_digest,
    keeps_held_key_events,
    replay_key_events,
    verify_signature_for,
)
from probos.types import FederationMessage

logger = logging.getLogger(__name__)

STATEMENT_TYPE = "probos.federation.envelope"
ENVELOPE_VERSION = 1
BROADCAST = "*"
CHANNEL_DIRECT = "direct"
CHANNEL_BROADCAST = "broadcast"
BROADCAST_TOPICS = frozenset({"gossip_self_model"})
RESPONSE_TOPICS = frozenset({"intent_response", "chain_response", "transfer_response"})  # bridge.py:1500-1520 only queues these
ATTACHMENT_REQUEST = "attachment_request"  # AD-1198 slice 3a: a peer's signed attachment fetch
A2A_REQUEST = "a2a_request"  # AD-1198 slice 3b: a peer's signed A2A JSON-RPC request
PEER_REQUEST_TOPICS = frozenset({ATTACHMENT_REQUEST, A2A_REQUEST})  # AD-1198 accepted only over HTTP (peer_requests.py), never over the bridge
POLICY_SIGN = "sign"
POLICY_REQUIRE = "require"
REPLAY_WINDOW = 64
MAX_KEY_EVENTS = 32  # the newest key events an envelope carries and a receiver holds per sender (AD-1197 A-1)
MAX_HELD_SENDERS = 256
MAX_HELD_KEY_IDS = 4_096  # the most key ids a receiver records per sender; past it the sender is refused, never forgotten (AD-1197 A-2)
MAX_SEQUENCE = 2**53 - 1
MAX_AUTH_BYTES = 65_536
MAX_NODE_ID_CHARS = 256  # the longest node id a signed envelope may name as its source or target (AD-1197 A-2b)
_MASK = (1 << REPLAY_WINDOW) - 1
_AUTH_MEMBERS = frozenset({"v", "target", "epoch", "seq", "key_seq", "key_head", "jws", "key_events"})
_EVENT_MEMBERS = frozenset({"index", "event", "signatures"})
_HEADER_MEMBERS = frozenset({"alg", "kid", "typ"})
_MAX_JWS_CHARS = 4_096
_HEX_DIGITS = frozenset("0123456789abcdef")

_MODE_NEW = "new"
_MODE_ARMED = "armed"
_MODE_UNGUARDED = "unguarded"
_MODE_CLOSED = "closed"
_MODE_STOPPED = "stopped"


class EnvelopeError(Exception):
    """Base class for AD-1197 envelope failures. Messages never carry a signature or key material."""


class EnvelopeRejected(EnvelopeError):
    """An envelope failed verification and was not delivered."""


class EnvelopeNotSent(EnvelopeError):
    """An envelope could not be signed, and nothing unsigned is sent."""


class EnvelopeSigner(Protocol):
    """What the guard needs from the ship's key binding; ``IdentityKeyBinding`` satisfies it."""

    @property
    def key_status(self) -> str: ...

    async def sign_envelope(
        self, statement_for: Callable[[KeyState], Mapping[str, Any]],
    ) -> EnvelopeSignature | None: ...


class EnvelopeStateStore(Protocol):
    """What the guard needs from its replay store; ``EnvelopeStore`` satisfies it."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def next_send_epoch(self) -> int: ...

    async def load(self) -> tuple[dict[str, StoredSender], dict[tuple[str, str], StoredWindow]]: ...

    async def key_ids(self, source: str) -> frozenset[str]: ...

    async def record(
        self, source: str, channel: str, sender: StoredSender | None, window: StoredWindow,
        key_ids: frozenset[str] = frozenset(),
    ) -> None: ...


class PeerIdentityPolicy(Protocol):
    """AD-1198: which sources the guard may hold, and whether a key history satisfies a source's pin.

    ``PeerAdmission`` satisfies it. Without one the guard behaves exactly as AD-1197 shipped it.
    """

    def admits_source(self, source: str) -> bool: ...

    def identity_refusal(self, source: str, state: KeyState) -> str | None: ...


@dataclass(frozen=True)
class EnvelopeAuth:
    """A signature block (``FederationMessage.auth``) that passed :func:`parse_auth`."""

    target: str
    epoch: int
    seq: int
    key_seq: int
    key_head: str
    jws: str
    key_events: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class HeldSender:
    """The newest key events held for one source node (at most ``MAX_KEY_EVENTS``, ending at
    its head) and the key state they replay to.
    """

    did: str
    events: tuple[KeyEvent, ...]
    state: KeyState


def body_digest(payload: object) -> str:
    """The SHA-256 hex digest of ``payload``'s RFC 8785 form.

    Raises ``ValueError`` when it has none, and ``RecursionError`` when it is nested
    too deep to canonicalise (plain JSON may still carry it).
    """
    return hashlib.sha256(canonicalize(payload)).hexdigest()


def envelope_statement(
    message: FederationMessage,
    *,
    target: str,
    epoch: int,
    seq: int,
    key_seq: int,
    key_head: str,
    body_sha256: str,
) -> dict[str, Any]:
    """The twelve-member statement an envelope signature covers; the sender and the receiver both build it here."""
    return {
        "type": STATEMENT_TYPE,
        "v": ENVELOPE_VERSION,
        "topic": message.type,
        "source": message.source_node,
        "target": target,
        "message_id": message.message_id,
        "timestamp": message.timestamp,
        "body_sha256": body_sha256,
        "epoch": epoch,
        "seq": seq,
        "key_seq": key_seq,
        "key_head": key_head,
    }


def key_events_to_wire(events: Sequence[KeyEvent]) -> list[dict[str, Any]]:
    """A detached JSON copy of ``events`` in their wire form ``{index, event, signatures}``."""
    return json.loads(json.dumps([
        {"index": event.index, "event": event.payload, "signatures": event.signatures} for event in events
    ]))


def key_events_from_wire(items: Sequence[Mapping[str, Any]]) -> tuple[KeyEvent, ...]:
    """Key events from their wire form, detached from the caller's objects, each digest recomputed."""
    detached = json.loads(json.dumps([dict(item) for item in items]))
    return tuple(
        KeyEvent(
            index=item["index"], payload=item["event"], signatures=item["signatures"],
            digest=event_digest(item["event"]),
        )
        for item in detached
    )


def parse_auth(auth: object) -> EnvelopeAuth | None:
    """The signature block ``auth`` parsed, or ``None`` for any block this verifier does not accept.

    Never raises. Exact member sets, a bounded size, a bounded run of key events no
    longer than the history ``key_seq`` names, bounded strings, and integers that are
    never ``bool``.
    """
    if type(auth) is not dict or frozenset(auth) != _AUTH_MEMBERS:
        return None
    try:
        size = len(json.dumps(auth))
    except (TypeError, ValueError, RecursionError):
        return None
    if size > MAX_AUTH_BYTES:
        return None
    version, target, epoch, seq = auth["v"], auth["target"], auth["epoch"], auth["seq"]
    key_seq, key_head, jws, items = auth["key_seq"], auth["key_head"], auth["jws"], auth["key_events"]
    if type(version) is not int or version != ENVELOPE_VERSION:
        return None
    if not _is_node_id(target):
        return None
    if type(epoch) is not int or type(seq) is not int:
        return None
    if not 1 <= epoch <= MAX_SEQUENCE or not 1 <= seq <= MAX_SEQUENCE:
        return None
    if type(key_seq) is not int or not 0 <= key_seq <= MAX_SEQUENCE:  # AD-1197 A-1 the count no longer bounds it
        return None
    if type(key_head) is not str or len(key_head) != 64 or not _HEX_DIGITS.issuperset(key_head):
        return None
    if type(jws) is not str or len(jws) > _MAX_JWS_CHARS:
        return None
    if type(items) is not list:
        return None
    if not 1 <= len(items) <= MAX_KEY_EVENTS:  # AD-1197 bounded key history
        return None
    if len(items) > key_seq + 1:  # AD-1197 A-1 a suffix of the history
        return None
    for item in items:
        if type(item) is not dict or frozenset(item) != _EVENT_MEMBERS:
            return None
        if type(item["index"]) is not int or item["index"] < 1:
            return None
        if type(item["event"]) is not dict or type(item["signatures"]) is not dict:
            return None
    return EnvelopeAuth(target, epoch, seq, key_seq, key_head, jws, tuple(items))


def advance_window(
    window: StoredWindow | None, key_seq: int, epoch: int, seq: int,
) -> tuple[StoredWindow | None, str]:
    """The replay window after admitting ``(key_seq, epoch, seq)``, or ``None`` and the reason it is refused."""
    if window is None or key_seq > window.key_seq or (key_seq == window.key_seq and epoch > window.epoch):
        return StoredWindow(key_seq, epoch, seq, 1), "fresh"
    if key_seq < window.key_seq:  # AD-1197 replay state belongs to the newest key
        return None, "stale key"
    if epoch < window.epoch:  # AD-1197 stale epoch
        return None, "stale epoch"
    if seq > window.hwm:
        shift = seq - window.hwm
        mask = 1 if shift >= REPLAY_WINDOW else ((window.mask << shift) | 1) & _MASK
        return StoredWindow(key_seq, epoch, seq, mask), "advanced"
    if seq <= window.hwm - REPLAY_WINDOW:  # AD-1197 too old
        return None, "too old"
    bit = 1 << (window.hwm - seq)
    if window.mask & bit:  # AD-1197 duplicate
        return None, "duplicate"
    return StoredWindow(key_seq, epoch, window.hwm, window.mask | bit), "filled"


def _label(value: object) -> str:
    return value[:64] if type(value) is str else type(value).__name__


def _is_node_id(value: object) -> bool:
    """Whether ``value`` can name a node in a signed envelope: a ``str`` of 1 to ``MAX_NODE_ID_CHARS`` characters."""
    return type(value) is str and 1 <= len(value) <= MAX_NODE_ID_CHARS


class EnvelopeGuard:
    """Seals outbound envelopes and admits inbound ones for one node (AD-1197).

    Owns the replay store's lifecycle and every policy decision: ``require`` sends and
    accepts nothing unsigned and keeps federation closed when its store cannot open;
    ``sign`` sends unsigned while the key cannot sign, accepts unsigned envelopes
    only from senders never seen signing, and runs plain federation when its store
    cannot open. A malformed signature block is never read as unsigned. With an
    ``identity_policy`` (AD-1198) it holds only the sources the policy admits, a first
    contact or a stored hold must satisfy the source's pin, and a store that cannot open
    keeps federation closed under either policy.
    """

    def __init__(
        self, *, signer: EnvelopeSigner, store: EnvelopeStateStore, local_node_id: str, policy: str,
        identity_policy: PeerIdentityPolicy | None = None,
    ) -> None:
        if policy not in (POLICY_SIGN, POLICY_REQUIRE):
            raise ValueError(f"the envelope policy must be {POLICY_SIGN!r} or {POLICY_REQUIRE!r}")
        if not local_node_id:
            raise ValueError("an envelope guard needs its node id")
        self._signer = signer
        self._store = store
        self._local_node_id = local_node_id
        self._policy = policy
        self._identity = identity_policy
        self._mode = _MODE_NEW
        self._epoch = 0
        self._seq = 0
        self._sign_lock = asyncio.Lock()
        self._accept_lock = asyncio.Lock()
        self._holds: dict[str, HeldSender] = {}
        self._invalid: set[str] = set()
        self._windows: dict[tuple[str, str], StoredWindow] = {}
        self._unsigned_reason: str | None = None

    @property
    def accepts_traffic(self) -> bool:
        """Whether this node sends and accepts federation traffic at all."""
        return self._mode in (_MODE_ARMED, _MODE_UNGUARDED)

    async def start(self) -> None:
        """Open the store, commit a new send epoch and load the holds; never raises for a store failure.

        A store that cannot open keeps federation closed under ``require`` or with peer
        admission armed (AD-1198), and otherwise runs it unsigned and unverified under
        ``sign`` -- logged either way.
        """
        try:
            await self._store.start()
            epoch = await self._store.next_send_epoch()
            senders, windows = await self._store.load()
        except BaseException as exc:
            with contextlib.suppress(Exception):
                await self._store.stop()
            if not isinstance(exc, Exception):
                raise
            if self._policy == POLICY_REQUIRE or self._identity is not None:  # AD-1198 armed admission never degrades to unverified
                self._mode = _MODE_CLOSED
                if self._identity is not None:
                    logger.error(
                        "AD-1198: the federation envelope store could not be opened (%s); peer admission is armed, so "
                        "federation stays closed -- nothing is sent or accepted -- until it opens on a restart",
                        type(exc).__name__,
                    )
                else:
                    logger.error(
                        "AD-1197: the federation envelope store could not be opened (%s); policy 'require' keeps "
                        "federation closed -- nothing is sent or accepted -- until it opens on a restart",
                        type(exc).__name__,
                    )
            else:
                self._mode = _MODE_UNGUARDED
                logger.warning(
                    "AD-1197: the federation envelope store could not be opened (%s); policy 'sign' runs "
                    "federation unsigned and unverified until it opens on a restart",
                    type(exc).__name__,
                )
            return
        holds: dict[str, HeldSender] = {}
        invalid: set[str] = set()
        for source, stored in senders.items():
            if self._identity is not None and not self._identity.admits_source(source):  # AD-1198 only configured peers are held
                continue
            events: tuple[KeyEvent, ...] = ()
            try:
                events = key_events_from_wire(json.loads(stored.key_events_json))
                state = replay_key_events(events)  # AD-1197 A-1 a hold is what its stored tail replays to
            except (KeyEventInvalid, ValueError, TypeError, KeyError):
                state = None
            if state is None or state.did != stored.did or state.seq != stored.key_seq or state.head_digest != stored.key_head:  # AD-1197 a stored history must replay
                invalid.add(source)
                logger.error(
                    "AD-1197: the key history held for %r does not replay; its envelopes are refused until an "
                    "operator resolves it",
                    source[:64],
                )
                continue
            why = None if self._identity is None else self._identity.identity_refusal(source, state)  # AD-1198 a held history must satisfy its pin
            if why is not None:
                invalid.add(source)
                logger.error(
                    "AD-1198: the key history held for %r does not satisfy its identity pin (%s); its envelopes are "
                    "refused until its pin or its hold is corrected",
                    source[:64], why,
                )
                continue
            holds[source] = HeldSender(state.did, events, state)
        self._holds, self._invalid, self._windows = holds, invalid, dict(windows)
        self._epoch, self._seq = epoch, 0
        self._mode = _MODE_ARMED
        logger.info(
            "AD-1197: federation envelope signing armed (policy %s, %d senders held)", self._policy, len(holds),
        )

    async def stop(self) -> None:
        """Close the store; afterwards nothing is sent or accepted."""
        async with self._accept_lock:
            try:
                await self._store.stop()
            except Exception as exc:  # noqa: BLE001 -- shutdown degrades: the guard is stopped either way
                logger.warning(
                    "AD-1197: the federation envelope store did not close cleanly (%s); the guard is stopped",
                    type(exc).__name__,
                )
            self._mode = _MODE_STOPPED

    async def seal(self, message: FederationMessage, target: str) -> FederationMessage | None:
        """``message`` signed for ``target`` (a node id, or ``BROADCAST``).

        Returns the signed copy, the message itself when it may go unsigned, or
        ``None`` when it must not be sent.
        """
        if self._mode == _MODE_UNGUARDED:
            return message
        if self._mode != _MODE_ARMED:
            logger.debug("AD-1197: envelope %r not sent: federation is not open", _label(message.type))
            return None
        try:
            body_sha256 = body_digest(message.payload)
        except (ValueError, RecursionError):  # AD-1197 A-0 outbound: a body too deep has no RFC 8785 form either
            signed, reason = None, "the body has no RFC 8785 form"
        else:
            async with self._sign_lock:
                signed, reason = await self._sign_locked(message, target, body_sha256)
        self._note_signing(reason if signed is None else None)
        if signed is not None:
            return signed
        if self._policy == POLICY_REQUIRE:
            logger.debug("AD-1197: envelope %r not sent unsigned", _label(message.type))
            return None  # AD-1197 require: nothing unsigned leaves
        return message

    async def _sign_locked(
        self, message: FederationMessage, target: str, body_sha256: str,
    ) -> tuple[FederationMessage | None, str]:
        if not _is_node_id(message.source_node):  # AD-1197 A-2b a local node id beyond the bound is never signed
            return None, f"the source node id is not 1 to {MAX_NODE_ID_CHARS} characters"
        seq = self._seq + 1
        epoch = self._epoch

        def statement_for(state: KeyState) -> dict[str, Any]:
            return envelope_statement(
                message, target=target, epoch=epoch, seq=seq, key_seq=state.seq, key_head=state.head_digest,
                body_sha256=body_sha256,
            )

        for _attempt in range(2):
            try:
                signature = await self._signer.sign_envelope(statement_for)
            except ValueError:
                return None, "the envelope has no RFC 8785 form"
            if signature is not None:
                events = signature.key_events
                for start in range(max(0, len(events) - MAX_KEY_EVENTS), len(events)):
                    auth = {
                        "v": ENVELOPE_VERSION,
                        "target": target,
                        "epoch": epoch,
                        "seq": seq,
                        "key_seq": signature.state.seq,
                        "key_head": signature.state.head_digest,
                        "jws": signature.jws,
                        "key_events": key_events_to_wire(events[start:]),
                    }
                    if parse_auth(auth) is not None:  # AD-1197 A-1 never send a block a receiver's parser refuses
                        self._seq = seq
                        return dataclasses.replace(message, auth=auth), ""
                return None, "the signature block exceeds the envelope bounds"
            if self._signer.key_status != STATUS_ACTIVE:
                return None, f"the ship key is {self._signer.key_status}"
        return None, "the ship key changed during both signing attempts"  # AD-1197 A-0 the race, not the key state

    def _note_signing(self, reason: str | None) -> None:
        if reason == self._unsigned_reason:
            return
        self._unsigned_reason = reason
        if reason is None:
            logger.info("AD-1197: federation envelopes are signed again")
        elif self._policy == POLICY_REQUIRE:
            logger.warning(
                "AD-1197: federation envelopes cannot be signed (%s); under policy 'require' they are not sent",
                reason,
            )
        else:
            logger.warning(
                "AD-1197: federation envelopes cannot be signed (%s); under policy 'sign' they are sent unsigned",
                reason,
            )

    async def admit(self, message: object) -> bool:
        """Whether ``message`` may be delivered: verified, admitted through its replay window and recorded.

        Total: anything malformed is a rejection, logged once with its topic, source and reason.
        Unguarded (policy ``sign`` without peer admission, whose store could not open), unsigned and well-formed signed
        envelopes are admitted without verification -- the designed degrade -- and a malformed
        block is refused, as in every mode. A signed envelope whose source node id is not 1 to
        ``MAX_NODE_ID_CHARS`` characters is refused in every mode, before the store is read or
        written (AD-1197 A-2b).
        """
        if self._mode not in (_MODE_ARMED, _MODE_UNGUARDED):
            return False
        auth = message.auth if type(message) is FederationMessage else None
        if auth is not None and not _is_node_id(getattr(message, "source_node", None)):  # AD-1197 A-2b a source node is bounded
            reason: str | None = "malformed (source)"
        elif self._mode == _MODE_UNGUARDED:
            reason = "malformed" if auth is not None and parse_auth(auth) is None else None  # AD-1197 A-1 a malformed block is refused in every mode
        else:
            try:
                async with self._accept_lock:
                    reason = await self._admit_locked(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- trust boundary: anything malformed is a rejection
                reason = f"malformed ({type(exc).__name__})"
        if reason is None:
            return True
        logger.warning(
            "AD-1197: envelope %r from %r rejected (%s); not delivered",
            _label(getattr(message, "type", None)), _label(getattr(message, "source_node", None)), reason,
        )
        return False

    async def _admit_locked(self, message: object) -> str | None:
        if type(message) is not FederationMessage:
            return "malformed"
        source = message.source_node
        if type(source) is not str or type(message.type) is not str or type(message.message_id) is not str:
            return "malformed"
        if source == self._local_node_id:  # AD-1197 reflection
            return "reflected"
        if self._identity is not None and not self._identity.admits_source(source):  # AD-1198 an unconfigured source is refused
            return "unconfigured source"
        if message.auth is None:
            return self._unsigned(source)
        parsed = parse_auth(message.auth)
        if parsed is None:  # AD-1197 a malformed signature block is never unsigned
            return "malformed"
        if not (parsed.target == self._local_node_id or (parsed.target == BROADCAST and message.type in BROADCAST_TOPICS)):  # AD-1197 target
            return "target"
        if source in self._invalid:
            return "held history"
        held = self._holds.get(source)
        if held is None and len(self._holds) + len(self._invalid) >= MAX_HELD_SENDERS:  # AD-1197 bounded first contact
            return "first contact refused"
        carried = key_events_from_wire(parsed.key_events)
        keeps, why = keeps_held_key_events(held.events if held else (), carried, carried_head=parsed.key_seq)
        if not keeps:  # AD-1197 held history
            return why
        used: frozenset[str] = frozenset()
        if held is not None and parsed.key_seq > held.state.seq:
            try:
                used = await self._store.key_ids(source)  # AD-1197 A-2 every key this receiver verified for the sender
            except Exception as exc:  # noqa: BLE001 -- an unread record is an unchecked rule: not delivered
                return f"not recorded ({type(exc).__name__})"  # AD-1197 A-2 an unread record refuses the growth
        tail = None
        try:
            if held is None:
                tail = carried
            elif parsed.key_seq > held.state.seq:
                new = carried[len(carried) - (parsed.key_seq - held.state.seq):]
                derive_key_state(new, after=held.state, used_key_ids=used)  # AD-1197 A-1 new events replay from the held state
                tail = (*held.events, *new)[-MAX_KEY_EVENTS:]  # AD-1197 A-1 a hold keeps the newest events
            state = held.state if tail is None else replay_key_events(tail)  # AD-1197 A-1 held from the oldest kept event
        except (KeyEventInvalid, ValueError, TypeError, KeyError):
            return "key history does not replay"
        if state is None:
            return "malformed"
        why = None if held is not None or self._identity is None else self._identity.identity_refusal(source, state)  # AD-1198 a first contact must satisfy its pin
        if why is not None:
            return why
        grows = tail is not None
        key_ids = used.union(kept.kid for kept in state.keys) if grows else frozenset()  # AD-1197 A-2 the kept run's keys join every key verified before
        if len(key_ids) > MAX_HELD_KEY_IDS:  # AD-1197 A-2 a sender past the bound is refused, never forgotten
            return "key history too long"
        if parsed.key_seq != state.seq or parsed.key_head != state.head_digest:  # AD-1197 stale key
            return "stale key"
        try:
            header = parse_detached(parsed.jws, expected_typ=ENVELOPE_JWS_TYP)
        except (ValueError, RecursionError):
            header = None
        if header is None or frozenset(header.header) != _HEADER_MEMBERS:  # AD-1197 exact protected header
            return "header"
        try:
            payload = canonical_bytes(envelope_statement(message, target=parsed.target, epoch=parsed.epoch, seq=parsed.seq, key_seq=parsed.key_seq, key_head=parsed.key_head, body_sha256=body_digest(message.payload)))
        except (ValueError, RecursionError):  # AD-1197 A-0 inbound: a body too deep has no RFC 8785 form either
            return "no canonical form"
        if not verify_signature_for(parsed.jws, payload, public_key_b64=state.active.public_key, kid=state.active_kid, typ=ENVELOPE_JWS_TYP):  # AD-1197 signature
            return "signature"
        channel = CHANNEL_BROADCAST if parsed.target == BROADCAST else CHANNEL_DIRECT
        window, why = advance_window(self._windows.get((source, channel)), parsed.key_seq, parsed.epoch, parsed.seq)
        if window is None:
            return why
        sender = (
            StoredSender(state.did, state.seq, state.head_digest, json.dumps(key_events_to_wire(tail)))
            if grows else None
        )
        try:
            await self._store.record(source, channel, sender, window, key_ids)
        except Exception as exc:  # noqa: BLE001 -- not recorded means not delivered, in both policies
            return f"not recorded ({type(exc).__name__})"  # AD-1197 not recorded, not delivered
        self._windows[(source, channel)] = window
        if grows:
            self._holds[source] = HeldSender(state.did, tail, state)
        return None

    def _unsigned(self, source: str) -> str | None:
        if self._policy == POLICY_REQUIRE:  # AD-1197 require: nothing unsigned enters
            return "unsigned"
        if source in self._holds or source in self._invalid:  # AD-1197 no downgrade
            return "downgrade"
        return None
