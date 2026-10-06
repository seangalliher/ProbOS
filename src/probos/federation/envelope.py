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
are signed and never judged: nothing here reads a clock. The one timer here bounds how
long the guard waits for its own store (AD-1198 A-2); it never judges an envelope.

This module's logger records no signature, key-event history, epoch or sequence.
The store's SQL parameters -- public key events and window counters, never a private
key -- reach the third-party ``aiosqlite`` logger at DEBUG; ProbOS runs that logger
at WARNING (``__main__.py:175``).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import functools
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

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
    recovery_precedence,
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
CHAIN_REQUEST = "chain_request"  # AD-1198 slice 2a: a request for a ship's identity-ledger chain (bridge.py answers it)
CHAIN_RESPONSE = "chain_response"  # AD-1198 slice 2a: the one topic a resync admits with the key history its chain carries
DIVERGENCE_REFUSALS = frozenset({"held history", "stale key"})  # AD-1198 slice 2b: the refusals of a held source whose history parts from the held events
POLICY_SIGN = "sign"
POLICY_REQUIRE = "require"
REPLAY_WINDOW = 64
MAX_KEY_EVENTS = 32  # the newest key events an envelope carries and a receiver holds per sender (AD-1197 A-1)
MAX_HELD_SENDERS = 256
MAX_HELD_KEY_IDS = 4_096  # the most key ids a receiver records per sender; past it the sender is refused, never forgotten (AD-1197 A-2)
MAX_SEQUENCE = 2**53 - 1
MAX_AUTH_BYTES = 65_536
MAX_NODE_ID_CHARS = 256  # the longest node id a signed envelope may name as its source or target (AD-1197 A-2b)
# AD-1198 A-2: the longest the guard waits for one write, or the close, of its envelope store. The one wait a healthy
# write has is for a lock another connection holds, and the store's SQLite busy timeout (5 s) bounds it; the bound
# allows that wait in full and one second more, so a write still running then is stalled, not contended. Past it the
# write's outcome is unknown: nothing is admitted until the write ends, and then exactly what it committed is held.
STORE_WRITE_SETTLE_S = 6.0  # AD-1198 A-2 the bound on one store write or close
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

    async def reanchor(
        self, source: str, channel: str, sender: StoredSender, window: StoredWindow, key_ids: frozenset[str],
    ) -> None: ...


class PeerIdentityPolicy(Protocol):
    """AD-1198: which sources the guard may hold, and whether a key history satisfies a source's pin.

    ``PeerAdmission`` satisfies it. Without one the guard behaves exactly as AD-1197 shipped it.
    """

    def admits_source(self, source: str) -> bool: ...

    def identity_refusal(self, source: str, state: KeyState) -> str | None: ...


LedgerHistory = Callable[[str], tuple[tuple[KeyEvent, ...], KeyState] | None]  # AD-1198 A-1 a DID's key history as identity.db stores it, re-verified, and its key state


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


_STORE_WRITE_TASK_NAME = "ad1198-envelope-store-write"
_STORE_SETTLE_TASK_NAME = "ad1198-envelope-store-settle"
_STORE_CLOSE_TASK_NAME = "ad1198-envelope-store-close"
_UNSETTLED = "store write unsettled"


async def _ended(write: Callable[[], Awaitable[None]]) -> BaseException | None:
    """How the store write ``write`` starts ended: ``None`` once it committed, else the exception it raised."""
    try:
        await write()
    except Exception as exc:  # noqa: BLE001 -- not recorded means not delivered, in both policies
        return exc  # AD-1198 A-1 a failed write is an outcome, read by its caller
    return None


async def _written(
    write: Callable[[], Awaitable[None]],
) -> tuple[asyncio.Task[BaseException | None], asyncio.CancelledError | None]:
    """AD-1198 A-1, A-2: run one store write in a task of its own and wait for it, whatever happens to its caller -- the
    shield-and-wait pattern of ``startup/fleet_organization.py`` -- for at most ``STORE_WRITE_SETTLE_S`` from its start.
    aiosqlite completes a COMMIT it has begun even when its caller is cancelled, so a write its caller stopped waiting
    for may still commit; and nothing bounds how long a COMMIT takes -- SQLite's busy timeout bounds only a wait for a
    lock another connection holds. Returns the write's task, ended or still running at the bound, and the caller's
    cancellation if one arrived meanwhile, which the caller raises once it has settled what the write lets it hold. The
    write is never cancelled here: one still running at the bound has an unknown outcome, not a rolled-back one.
    """
    writing = asyncio.create_task(_ended(write), name=_STORE_WRITE_TASK_NAME)
    settling = asyncio.create_task(asyncio.wait({writing}, timeout=STORE_WRITE_SETTLE_S), name=_STORE_SETTLE_TASK_NAME)  # AD-1198 A-2 the wait ends when the write has, or at the bound
    cancelled: asyncio.CancelledError | None = None
    while not settling.done():  # AD-1198 A-1 the wait ends only when the write has, or the bound has passed
        try:
            await asyncio.shield(settling)  # AD-1198 A-1 a cancellation of the caller does not interrupt the store's write
        except asyncio.CancelledError as exc:
            cancelled = cancelled or exc  # AD-1198 A-1 the caller's cancellation is kept, and raised once what committed is held
    return writing, cancelled


class _StoreWrite:
    """AD-1198 A-2: one store write the guard started -- its source, its task, and what the guard holds once it has
    committed -- owned by the guard until its outcome is known."""

    def __init__(self, source: str, task: asyncio.Task[BaseException | None], publish: Callable[[], None]) -> None:
        self.source = source
        self.task = task
        self.publish = publish

    def outcome(self, *, late: bool) -> str | None:
        """``None`` once the write committed, and what it committed is then held; ``"not recorded (...)"`` once it
        failed, and nothing of it is held; ``"store write unsettled"`` while it runs, or once it ended cancelled --
        whether it committed is then unknown, and stays so. ``late`` settles a write the guard stopped waiting for."""
        if not self.task.done() or self.task.cancelled():  # AD-1198 A-2 a write still running, or one that ended cancelled, may or may not have committed
            if not late:
                logger.error(
                    "AD-1198: the envelope store's write for %r %s; whether it committed is unknown, so no envelope is "
                    "admitted until %s",
                    self.source[:64],
                    "ended cancelled" if self.task.done() else f"has not ended within {STORE_WRITE_SETTLE_S:g} s",
                    "a restart reads the store" if self.task.done() else "it ends, and then what it committed is held",
                )
            return _UNSETTLED
        failure = self.task.result()
        if failure is None:  # AD-1198 A-1 exactly what committed is held
            self.publish()
        if late:
            logger.warning(
                "AD-1198: the envelope store's write for %r has ended (%s) after the guard stopped waiting for it; %s, "
                "and envelopes are admitted again",
                self.source[:64], "committed" if failure is None else f"not recorded: {type(failure).__name__}",
                "what it committed is held" if failure is None else "nothing of it is held",
            )
        return None if failure is None else f"not recorded ({type(failure).__name__})"  # AD-1197 not recorded, not delivered


def _close_ended(closing: asyncio.Task[None]) -> None:
    """AD-1198 A-3: once a close of the store that the guard's stop did not wait out has ended, read its outcome -- so
    that no exception of it is left unretrieved -- and report one that failed, once. A cancelled close has no exception
    to read, and one that completed has nothing to report."""
    failure = None if closing.cancelled() else closing.exception()  # AD-1198 A-3 the outcome of a close left running is read once it ends
    if failure is not None:  # AD-1198 A-3 and a close that failed is reported, once
        logger.warning(
            "AD-1198: the federation envelope store's close, left running when the guard's stop ended, failed (%s); the "
            "store may not have closed cleanly, nothing retries the close, and the next start opens the store as it stands",
            type(failure).__name__,
        )


async def _closed(closing: asyncio.Task[None], behind: _StoreWrite | None) -> None:
    """AD-1198 A-2: wait for the store's close ``closing`` at most ``STORE_WRITE_SETTLE_S`` -- not at all behind a store
    write still running, whose statements it is queued behind -- and raise what it raised once it has ended. A close
    that has not ended by the bound is logged and left to end on aiosqlite's worker thread, owned by the guard. A close
    this wait leaves running -- at the bound, or because the wait itself was cancelled -- is read once it ends (A-3)."""
    blocked = behind is not None and not behind.task.done()  # AD-1198 A-2 a close queued behind an unsettled write cannot end before it
    try:
        await asyncio.wait({closing}, timeout=0 if blocked else STORE_WRITE_SETTLE_S)  # AD-1198 A-2 the guard's stop waits for its store at most the bound
    except asyncio.CancelledError:
        closing.add_done_callback(_close_ended)  # AD-1198 A-3 a close whose wait was cancelled is read once it ends
        raise  # AD-1198 A-3 and the cancellation of the guard's stop is raised, never swallowed
    if closing.done():
        closing.result()
        return
    closing.add_done_callback(_close_ended)  # AD-1198 A-3 a close left running at the bound is read once it ends
    logger.warning(
        "AD-1198: the federation envelope store has not closed %s; the guard is stopped, and the store closes once the "
        "statement ahead of its close ends",
        "behind its unsettled write" if blocked else f"within {STORE_WRITE_SETTLE_S:g} s",
    )


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
        identity_policy: PeerIdentityPolicy | None = None, ledger: LedgerHistory | None = None,
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
        self._gap_listener: Callable[[str], None] | None = None  # AD-1198 slice 2a: told of each key history gap
        self._ledger = ledger  # AD-1198 A-1: at start, a held history's pin may be judged on the chain identity.db stores
        self._unsettled: _StoreWrite | None = None  # AD-1198 A-2 a store write whose outcome is not known yet, owned until it is
        self._closing: set[asyncio.Task[None]] = set()  # AD-1198 A-2 each close of the store, owned until it ends

    @property
    def accepts_traffic(self) -> bool:
        """Whether this node sends and accepts federation traffic at all."""
        return self._mode in (_MODE_ARMED, _MODE_UNGUARDED)

    def held(self, source: str) -> HeldSender | None:
        """AD-1198: the key history held for ``source`` -- its newest events and the state they replay to -- or ``None``.
        While a store write is unsettled (A-2) it may lag the store by that write, and nothing is admitted."""
        return self._holds.get(source)

    def on_history_gap(self, listener: Callable[[str], None] | None) -> None:
        """AD-1198: call ``listener`` with the source of each envelope refused for a key history gap, which a resync from
        that source's chain can heal, and (slice 2b), while peer admission is armed, of each envelope from a held source
        refused for a held history or a stale key, where a recovery in that chain may take precedence over the held
        events; ``None`` removes it. The listener must return at once and must not raise.
        """
        self._gap_listener = listener

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
            if why == "pin (key)" and self._ledger is not None:  # AD-1198 A-1 newest events without the pinned key: judged on the full history
                why = self._pin_on_ledger(source, events, state)
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

    def _pin_on_ledger(self, source: str, events: tuple[KeyEvent, ...], state: KeyState) -> str | None:
        """AD-1198 A-1: a held history refused at start for ``pin (key)`` -- its newest events no longer introduce the
        pinned key, as after a resync -- judged again on the full key history: the chain identity.db stores for the held
        DID (re-verified, ``ledger``), joined to the held events. The stored chain must reach the held head keeping the
        held events unchanged, or the held events must continue it from its head, replayed from its state under every
        AD-1196 rule; the pin and its continuity are then judged on that full state. ``pin (key)`` again when nothing is
        stored, the chain does not verify or the two do not join. Never raises.
        """
        found = None
        with contextlib.suppress(Exception):  # an unread chain proves nothing: the hold is refused as before
            found = None if self._ledger is None else self._ledger(state.did)
        if found is None or self._identity is None:
            return "pin (key)"
        history, full = found
        try:
            if full.seq < state.seq:  # AD-1198 A-1 the held events continue the stored chain from its head
                keeps, _ = keeps_held_key_events(history, events, carried_head=state.seq)
                if keeps:
                    full = derive_key_state(events[len(events) - (state.seq - full.seq):], after=full) or full
            else:
                keeps, _ = keeps_held_key_events(events, history, carried_head=full.seq)
        except (KeyEventInvalid, ValueError, TypeError, KeyError):  # AD-1198 A-1 a history that does not replay proves nothing
            keeps = False
        if not keeps:  # AD-1198 A-1 the stored chain and the held events must be one history
            return "pin (key)"
        why = self._identity.identity_refusal(source, full)  # AD-1198 A-1 the pin and its continuity on the full history
        if why is None:
            logger.info(
                "AD-1198: on the chain identity.db stores for %r, the key history held for it satisfies its identity "
                "pin (key seq %d); it is held",
                source[:64], state.seq,
            )
        return why

    async def stop(self) -> None:
        """Close the store; afterwards nothing is sent or accepted. The close is waited for at most ``STORE_WRITE_SETTLE_S``,
        and not at all behind a store write left unsettled; one that has not ended is left to end, owned by the guard (A-2).
        """
        async with self._accept_lock:
            closing = asyncio.create_task(self._store.stop(), name=_STORE_CLOSE_TASK_NAME)
            self._closing.add(closing)  # AD-1198 A-2 the guard owns each close of its store until it ends
            closing.add_done_callback(self._closing.discard)  # AD-1198 A-2 and lets it go once it has ended
            try:
                await _closed(closing, self._unsettled)
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
        written (AD-1197 A-2b). A cancellation that arrives while the envelope is being recorded is
        raised once the store's write has ended, with what it committed held (AD-1198 A-1), or once
        ``STORE_WRITE_SETTLE_S`` has passed: an envelope whose write has not ended by then is not
        delivered, and nothing is admitted until that write ends (A-2).
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
        diverged = reason in DIVERGENCE_REFUSALS and self._identity is not None and cast(FederationMessage, message).source_node in self._holds  # AD-1198 A-1 a held source's divergence asks for a resync only while peer admission is armed
        if (reason == "key history gap" or diverged) and self._gap_listener is not None:  # AD-1198 a gap, or (slice 2b) a held source's divergence, asks for a resync
            self._gap_listener(cast(FederationMessage, message).source_node)
        return False

    async def resync(
        self, message: object, history: Sequence[KeyEvent], before_record: Callable[[], Awaitable[str | None]] | None = None,
    ) -> bool:
        """AD-1198: admit a pinned peer's directed ``chain_response`` with ``history``, the key events of the chain it
        carries, in place of the run its signature block carries -- so a hold refused for a key history gap is resynchronised.

        Only while armed with peer admission, only a ``chain_response`` and only for a source already held. ``history``
        is judged exactly as a carried run: it must end at the head the envelope was signed under, keep the held events
        unchanged and re-incept nothing after them; the events past the held head replay from the held state under every
        AD-1196 rule and may not reintroduce a recorded key; the newest 32 become the hold, every key the new events
        introduced is recorded, and the envelope is verified under the new head's key and recorded in its replay window.
        ``before_record`` (A-1) runs once every check has passed, immediately before anything is recorded: a reason it
        returns refuses the resync. A refusal is never raised: it is logged with its reason and changes nothing. A
        cancellation propagates: before the store write begins nothing is recorded, though ``before_record`` may already
        have written identity.db, which is then ahead of the hold until the next resync; once the write has begun it is
        waited for, at most ``STORE_WRITE_SETTLE_S``, and what it committed is held before the cancellation is raised
        (A-1). A write still running then has an unknown outcome: the resync ends at the bound -- cancelled, or else
        refused -- and nothing is admitted until the write ends (A-2).

        Slice 2b: a ``history`` that does not keep the held events is admitted only when it takes recovery-key precedence
        over them (``recovery_precedence``). Its events from the recovery on replay from the state the two branches share
        under every AD-1196 rule and may not reintroduce a recorded key; its full key state must satisfy the source's
        pin; its newest 32 events become the hold, even when that moves the hold back; the key ids of both branches stay
        recorded; the source's replay windows start again with this envelope's; and the store writes all of it in one
        transaction (``reanchor``), which is logged.
        """
        if self._mode != _MODE_ARMED or self._identity is None:  # AD-1198 a resync only with peer admission armed
            reason: str | None = "not armed"
        elif type(message) is not FederationMessage or message.type != CHAIN_RESPONSE:  # AD-1198 only a chain response carries a history
            reason = "topic"
        else:
            try:
                async with self._accept_lock:
                    reason = await self._admit_locked(message, tuple(history), before_record)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- trust boundary: anything malformed is a refusal
                reason = f"malformed ({type(exc).__name__})"
        if reason is None:
            return True
        logger.warning(
            "AD-1198: chain response from %r not admitted for a resync (%s); the key history held for it is unchanged",
            _label(getattr(message, "source_node", None)), reason,
        )
        return False

    async def _admit_locked(
        self, message: object, history: tuple[KeyEvent, ...] | None = None,
        before_record: Callable[[], Awaitable[str | None]] | None = None,
    ) -> str | None:
        if self._unsettled is not None and self._unsettled.outcome(late=True) == _UNSETTLED:  # AD-1198 A-2 nothing is admitted while the store may hold what memory does not
            return _UNSETTLED
        self._unsettled = None  # AD-1198 A-2 a write left unsettled is let go once what it committed is held
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
        if history is not None and held is None:  # AD-1198 a resync re-anchors a hold; a first contact carries its own run
            return "not held"
        if held is None and len(self._holds) + len(self._invalid) >= MAX_HELD_SENDERS:  # AD-1197 bounded first contact
            return "first contact refused"
        carried = key_events_from_wire(parsed.key_events) if history is None else history  # AD-1198 a resync carries its chain's history
        if history is not None and (not carried or carried[-1].payload.get("seq") != parsed.key_seq):  # AD-1198 the history ends at the signing head
            return "stale key"
        keeps, why = keeps_held_key_events(held.events if held else (), carried, carried_head=parsed.key_seq)
        divergent = None
        if not keeps and history is not None and held is not None and why in DIVERGENCE_REFUSALS:  # AD-1198 slice 2b a resync's chain may take precedence over the hold
            divergent, _ = recovery_precedence(held.events, carried)
        if not keeps and divergent is None:  # AD-1197 held history
            return why
        used: frozenset[str] = frozenset()
        if held is not None and (parsed.key_seq > held.state.seq or divergent is not None):  # AD-1198 slice 2b a re-anchor reads the recorded key ids too
            try:
                used = await self._store.key_ids(source)  # AD-1197 A-2 every key this receiver verified for the sender
            except Exception as exc:  # noqa: BLE001 -- an unread record is an unchecked rule: not delivered
                return f"not recorded ({type(exc).__name__})"  # AD-1197 A-2 an unread record refuses the growth
        tail = None
        derived: KeyState | None = None
        try:
            if divergent is not None:  # AD-1198 slice 2b the branch replays from the state the two branches share
                derived = derive_key_state(carried[divergent:], after=derive_key_state(carried[:divergent]), used_key_ids=used)  # AD-1198 slice 2b from the shared state, never reintroducing a recorded key
                tail = carried[-MAX_KEY_EVENTS:]  # AD-1198 slice 2b the branch's newest events become the hold
            elif held is None:
                tail = carried
            elif parsed.key_seq > held.state.seq:
                new = carried[len(carried) - (parsed.key_seq - held.state.seq):]
                derived = derive_key_state(new, after=held.state, used_key_ids=used)  # AD-1197 A-1 new events replay from the held state
                tail = (*held.events, *new)[-MAX_KEY_EVENTS:]  # AD-1197 A-1 a hold keeps the newest events
            state = held.state if tail is None else replay_key_events(tail)  # AD-1197 A-1 held from the oldest kept event
        except (KeyEventInvalid, ValueError, TypeError, KeyError):
            return "key history does not replay"
        if state is None:
            return "malformed"
        why = None if held is not None or self._identity is None else self._identity.identity_refusal(source, state)  # AD-1198 a first contact must satisfy its pin
        if divergent is not None and self._identity is not None:  # AD-1198 slice 2b a re-anchor satisfies the pin
            why = self._identity.identity_refusal(source, cast(KeyState, derived))  # AD-1198 slice 2b the pin on the full key state, not the kept run
        if why is not None:
            return why
        grows = tail is not None
        recorded = state if derived is None else derived  # AD-1198 every key the new events introduced, also those older than the kept run
        key_ids = used.union(kept.kid for kept in recorded.keys) if grows else frozenset()  # AD-1197 A-2 the kept run's keys join every key verified before
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
        window, why = advance_window(None if divergent is not None else self._windows.get((source, channel)), parsed.key_seq, parsed.epoch, parsed.seq)  # AD-1198 slice 2b a re-anchored source's windows start again
        if window is None:
            return why
        if before_record is not None:  # AD-1198 A-1 a resync's chain is in identity.db before its hold is recorded
            refused = await before_record()
            if refused is not None:
                return refused
        sender = (
            StoredSender(state.did, state.seq, state.head_digest, json.dumps(key_events_to_wire(tail)))
            if grows else None
        )
        if divergent is None:
            write = functools.partial(self._store.record, source, channel, sender, window, key_ids)
        else:
            write = functools.partial(self._store.reanchor, source, channel, cast(StoredSender, sender), window, key_ids)  # AD-1198 slice 2b the one write that may move a hold back

        def publish() -> None:  # AD-1198 A-2 what the write committed, held at once or once a write left unsettled ends
            if divergent is not None:
                self._windows = {key: kept for key, kept in self._windows.items() if key[0] != source}  # AD-1198 slice 2b the guard forgets the source's windows in memory too
                logger.warning(
                    "AD-1198: re-anchored the key history held for %r on the branch its chain carries: the recovery at key "
                    "seq %d takes precedence over the held events from there (key seq %d -> %d); its replay windows start "
                    "again, and the %d key ids recorded for it, of both branches, stay recorded",
                    source[:64], divergent, cast(HeldSender, held).state.seq, state.seq, len(key_ids),
                )
            self._windows[(source, channel)] = window
            if grows:
                self._holds[source] = HeldSender(state.did, tail, state)

        writing, cancelled = await _written(write)  # AD-1198 A-1 the write and what it holds complete as one, whatever happens to the caller -- within the bound (A-2)
        written = _StoreWrite(source, writing, publish)
        reason = written.outcome(late=False)
        if reason == _UNSETTLED:  # AD-1198 A-2 an unknown outcome: the guard owns the write until it is known, and admits nothing meanwhile
            self._unsettled = written
        if cancelled is not None:  # AD-1198 A-1 a cancellation that arrived during the write is raised once what committed is held
            raise cancelled
        if writing.cancelled():  # AD-1198 A-1 a write that ended cancelled raises its cancellation, never a refusal (AD-1197)
            raise asyncio.CancelledError
        return reason

    def _unsigned(self, source: str) -> str | None:
        if self._policy == POLICY_REQUIRE:  # AD-1197 require: nothing unsigned enters
            return "unsigned"
        if source in self._holds or source in self._invalid:  # AD-1197 no downgrade
            return "downgrade"
        return None
