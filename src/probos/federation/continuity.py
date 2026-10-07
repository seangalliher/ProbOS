"""AD-1198 slice 2a: identity continuity -- the armed identity exchange, and the resync that heals a key-history gap.

While ``federation.peer_admission_enabled`` is armed, the bridge's two identity requests (AD-443e) are answered here,
bound to the authenticated peer that sent them (``FederationBridge`` asks :meth:`IdentityExchange.for_sender`):

- a **chain request** is served only to a pinned peer, and only a chain of at most ``MAX_CHAIN_BLOCKS`` blocks and
  ``MAX_CHAIN_BYTES`` bytes of JSON;
- a **chain import** (a transfer carries its origin's chain) takes only the sender's own chain: bounded before it is
  verified; every block hash, link, key event and birth-certificate signature verified (a transfer's signature is
  verified when its certificate is imported, AD-1196); the DID of the key history held for the sender; that DID's full
  key state satisfying the sender's pin; and keeping the held history -- so identity.db only ever follows the envelope
  hold, never another branch (AD-1197 R-15);
- a **transfer certificate** is taken only from the sender's own ship, only when it names this ship, and only while
  identity.db stores a chain of that ship which verifies in full (Amendment A-2).

A key-history gap (AD-1197 R-21: a holder that missed more of a sender's key events than its envelopes carry refuses
every envelope from it, the chain answer that would heal it included) asks for a **resync**: one chain request to that
pinned peer, single-flight and at most once per ``RESYNC_INTERVAL_S`` for each peer, because the gap is found before
any signature can be checked. The guard admits the answer with the full key history its chain carries
(``EnvelopeGuard.resync``) -- the chain is fetched; a hold is never read as a full key state (AD-1197 R-25) -- and
identity.db imports the same chain first: the hold is recorded only once identity.db holds it, so a resynchronised
hold always has its chain there, where the guard's next start judges its pin (Amendment A-1). The exchange relies on a
chain -- one a peer sends, or one identity.db already stores -- only when it verifies in full (``verified_chain_state``:
the bounds, every block hash and link, every signature, with key events; Amendment A-2). Every armed import only
extends a verified stored chain of that DID: an older snapshot changes nothing, and any other chain is refused. A
stored chain that does not verify is replaced by a judged chain that begins with every one of its block hashes, and is
otherwise kept and the import refused. A late or repeated answer to an ended resync is dropped before it can reach an
intent while it is among the newest ``MAX_ENDED_RESYNCS`` ended requests (``signed_transport``). A sender past 4,096 key
ids (AD-1197 R-24) is not healed by a resync. An unarmed node builds no exchange, and its bridge answers exactly as
before.

Slice 2b: a held peer's envelope refused for a held history or a stale key also asks for a resync, and the fetched chain
may take the place of the held events where it parts from them, by recovery-key precedence
(``probos.identity_keys.recovery_precedence``): only where the two part inside the held run, and only when the chain's
event there is a ``recovery`` that replays from the state they share. identity.db first replaces a verified stored chain
the fetched chain takes precedence over -- the one exception to extending it, which the registry judges again
(``import_chain(..., supersede=True)``) -- and then the guard re-anchors the hold on the chain's branch in one logged
write (``EnvelopeGuard.resync``). A transfer's chain never moves either hold.

Slice 2c: an operator's reset (``IdentityExchange.reset``, behind ``POST /api/identity/peers/{node_id}/reset``) forgets
one configured peer's held key history -- identity.db's stored chain for the held DID first, in a transaction of its own,
then the hold, every key id recorded for it and its replay windows in one envelope-store transaction -- holding the
exchange's ledger lock from before the first until the second has ended or the guard's bound has passed, so no chain
import interleaves. Every import judges its chain again under that lock against the hold as it is then -- a reset may
have forgotten it since the chain was judged (``not held``), or a first contact after it may hold another branch -- and
none is imported while a store write of the guard is unsettled (``store write unsettled``): a reset's may have
forgotten a hold the guard still shows (Amendment A-1). Foreign birth and transfer certificates are kept. The peer's
next envelope is a first contact under its current pin, and the operator's audit runs once the hold's write has
committed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

from probos.federation.envelope import CHAIN_REQUEST, DIVERGENCE_REFUSALS, HeldSender
from probos.identity import chain_block_hashes, verify_chain_structure
from probos.identity_keys import (
    KeyEvent,
    chain_key_events,
    keeps_held_key_events,
    recovery_precedence,
    verify_chain_signatures,
)
from probos.types import FederationMessage

if TYPE_CHECKING:
    from probos.federation.admission import PeerAdmission
    from probos.identity import ShipBirthCertificate
    from probos.identity_keys import KeyState
    from probos.mobility import TransferCertificate

logger = logging.getLogger(__name__)

MAX_CHAIN_BLOCKS = 1_024  # the most ledger blocks a chain may carry to or from a peer
MAX_CHAIN_BYTES = 917_504  # 896 KiB of JSON: with the largest signature block a receiver accepts (65,536) a chain answer stays under NATS's default 1 MiB payload
RESYNC_INTERVAL_S = 60.0  # the least time between two resyncs of one peer: a gap is found before any signature is checked


class StoredChains(Protocol):
    """The chains identity.db stores for peer ships, by DID; ``AgentIdentityRegistry`` satisfies it (AD-1198 A-1)."""

    def get_foreign_chain(self, origin_ship_did: str) -> list[dict[str, Any]] | None: ...


class IdentityLedger(StoredChains, Protocol):
    """What the exchange needs from the identity registry; ``AgentIdentityRegistry`` satisfies it."""

    def get_ship_certificate(self) -> ShipBirthCertificate | None: ...

    async def export_chain(self) -> list[dict[str, Any]]: ...

    async def import_chain(
        self, blocks: list[dict[str, Any]], *, supersede: bool = False, if_stored: tuple[Any, ...] | None = None,
    ) -> tuple[bool, str]: ...

    async def import_transfer_certificate(self, cert: TransferCertificate) -> tuple[bool, str]: ...

    async def forget_foreign_chain(self, origin_ship_did: str) -> int: ...


class ChainSeam(Protocol):
    """What the exchange needs from the armed federation seam; ``SignedChainSeam`` satisfies it."""

    def held(self, source: str) -> HeldSender | None: ...

    def on_history_gap(self, listener: Callable[[str], None] | None) -> None: ...

    async def request_resync(
        self,
        peer_node_id: str,
        request: FederationMessage,
        timeout_ms: int,
        history_of: Callable[[FederationMessage], Awaitable[tuple[KeyEvent, ...] | None]],
        before_record: Callable[[FederationMessage], Awaitable[str | None]] | None = None,
    ) -> FederationMessage | None: ...

    async def forget(
        self, source: str, holding: Callable[[str | None], contextlib.AbstractAsyncContextManager[object]],
        committed: Callable[[], None] | None = None,
    ) -> str | None: ...

    def settled(self) -> bool: ...


@dataclass(frozen=True)
class PeerReset:
    """AD-1198 slice 2c: what an operator's reset of one configured peer forgot -- public data only, never key material."""

    node_id: str
    forgotten: bool  # whether a key history was held for the peer, and so forgotten
    did: str | None  # the DID of that key history
    key_seq: int | None  # its held key seq; None when nothing was held, or when the hold had been refused at start
    refused_at_start: bool  # whether that hold had been refused at start
    identity_chain_blocks: int  # the blocks of identity.db's chain for that DID that were forgotten (0 when none was stored)


def within_chain_bounds(blocks: object) -> bool:
    """Whether ``blocks`` is a list of 1 to ``MAX_CHAIN_BLOCKS`` items whose JSON has at most ``MAX_CHAIN_BYTES``.

    Checked before anything is verified; never raises.
    """
    if type(blocks) is not list or not 1 <= len(blocks) <= MAX_CHAIN_BLOCKS:  # AD-1198 a chain's block bound
        return False
    try:
        size = len(json.dumps(blocks))
    except (TypeError, ValueError, RecursionError):
        return False
    return size <= MAX_CHAIN_BYTES  # AD-1198 a chain's byte bound, before it is verified


def chain_key_history(blocks: list[dict[str, Any]]) -> tuple[KeyEvent, ...]:
    """The key events ``blocks`` anchors, in ledger order; for a chain whose signatures have verified. The same reading
    as identity.db's (``probos.identity_keys.chain_key_events``; AD-1198 slice 2b)."""
    return chain_key_events(blocks)


def verified_chain_state(blocks: object, did: str | None = None) -> KeyState | None:
    """AD-1198 A-2: the key state ``blocks`` verifies to, or ``None``: the one judgement of a chain the exchange relies on.

    Within the bounds; every block hash and link, as AD-443b checks them (``probos.identity.verify_chain_structure``);
    every key event and certificate signature, with key events (``verify_chain_signatures``); and, when ``did`` is given,
    that DID's. Applied to a chain a peer sends (``IdentityExchange._judged``), to the chain identity.db stores before
    the exchange relies on it, and to the guard's start-up proof (``stored_key_history``). Never raises.
    """
    if not within_chain_bounds(blocks):  # AD-1198 A-1 within the bounds before anything is verified
        return None
    chain = cast("list[dict[str, Any]]", blocks)
    try:
        linked, _ = verify_chain_structure(chain)  # AD-1198 A-2 every block hash and link, as AD-443b checks them
    except Exception:  # noqa: BLE001 -- trust boundary: a malformed chain verifies nothing
        linked = False
    report = verify_chain_signatures(chain) if linked else None  # AD-1198 a chain whose blocks do not link is not verified further
    if report is None or not report.ok or report.state is None:  # AD-1198 every hash, link and signature verifies, and the chain carries its key history
        return None
    if did is not None and report.state.did != did:  # AD-1198 A-1 only a verified chain of this DID
        return None
    return report.state


def stored_key_history(chains: StoredChains, did: str) -> tuple[tuple[KeyEvent, ...], KeyState] | None:
    """AD-1198 A-1: the key history of the chain identity.db stores for ``did`` and the full key state it verifies to.

    ``None`` unless that chain verifies in full as ``did``'s (``verified_chain_state``, checked again because it may
    have been stored before arming, or changed since). The envelope guard's start judges a held history's pin on it
    (``EnvelopeGuard``'s ``ledger``).
    """
    blocks = chains.get_foreign_chain(did)
    state = verified_chain_state(blocks, did)  # AD-1198 A-2 the start-up proof is a chain that verifies in full
    if state is None:
        return None
    return chain_key_history(cast("list[dict[str, Any]]", blocks)), state


def _keeps_hold(held: HeldSender | None, history: tuple[KeyEvent, ...], *, supersede: bool) -> str | None:
    """AD-1198 slice 2c A-1: why ``history`` -- the key history of a verified chain, never empty, ending at its head --
    does not keep ``held``, the key history held for its sender, or ``None``. ``IdentityExchange._judged`` judges a chain
    so, and ``_into_ledger`` judges it again under the exchange's ledger lock against the hold as it is then: a reset may
    have forgotten the hold since, or a first contact after it may hold another branch. With ``supersede`` (a resync;
    slice 2b) a history that does not keep the held events keeps them where it takes recovery-key precedence over them.
    """
    if held is None:  # AD-1198 slice 2c a chain is imported only while its sender is held: a reset may have forgotten it since the chain was judged
        return "not held"
    keeps, why = keeps_held_key_events(held.events, history, carried_head=history[-1].payload["seq"])  # AD-1198 slice 2c A-1 the held events as they are now, kept by the chain
    if not keeps and supersede and why in DIVERGENCE_REFUSALS:  # AD-1198 slice 2b a resync's chain may take precedence over the held events
        divergent, precedence = recovery_precedence(held.events, history)
        keeps, why = divergent is not None, f"{why}: {precedence}"  # AD-1198 slice 2b the refusal names the judgement
    return None if keeps else why


class _PeerIdentity:
    """The identity exchange as one authenticated peer reaches it: what the bridge's identity handlers call (AD-1198)."""

    def __init__(self, exchange: IdentityExchange, sender: str) -> None:
        self._exchange = exchange
        self._sender = sender

    async def export_chain(self) -> list[dict[str, Any]]:
        """This ship's chain for the sender; empty unless the sender is pinned and the chain is within the bounds."""
        return await self._exchange.chain_for(self._sender)

    async def import_chain(self, blocks: list[dict[str, Any]]) -> tuple[bool, str]:
        """Import the chain a transfer carries: only the sender's own."""
        return await self._exchange.import_chain_from(self._sender, blocks)

    async def import_transfer_certificate(self, cert: TransferCertificate) -> tuple[bool, str]:
        """Import a transfer certificate: only from the sender's own ship, only for this ship, and only against a verified
        chain of that ship (A-2)."""
        return await self._exchange.import_transfer_from(self._sender, cert)


class IdentityExchange:
    """Identity continuity for armed peers (AD-1198 slice 2a): chain serving, sender-bound imports and resync."""

    def __init__(
        self,
        *,
        node_id: str,
        registry: IdentityLedger,
        seam: ChainSeam,
        admission: PeerAdmission,
        timeout_ms: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._node_id = node_id
        self._registry = registry
        self._seam = seam
        self._admission = admission
        self._timeout_ms = timeout_ms
        self._clock = clock
        self._resyncs: dict[str, asyncio.Task[None]] = {}
        self._attempts: dict[str, float] = {}
        self._refusals: dict[str, int] = {}
        self._stopped = False
        self._ledger_lock = asyncio.Lock()  # AD-1198 A-1 one armed identity.db chain import at a time

    @property
    def refusal_counts(self) -> dict[str, int]:
        """How many identity requests and resync answers were refused here, by reason (a copy)."""
        return dict(self._refusals)

    def for_sender(self, sender: str) -> _PeerIdentity:
        """The exchange bound to ``sender``: the authenticated peer whose request the bridge is answering."""
        return _PeerIdentity(self, sender)

    async def chain_for(self, sender: str) -> list[dict[str, Any]]:
        """This ship's chain, for a pinned peer only; ``[]`` for any other sender or when it is over the bounds."""
        if not self._admission.pinned(sender):  # AD-1198 a chain is served only to a pinned peer
            self._note_refusal(sender, "chain request", "unpinned peer")
            return []
        blocks = await self._registry.export_chain()
        if not within_chain_bounds(blocks):  # AD-1198 never serve a chain a peer must refuse
            logger.warning(
                "AD-1198: this ship's chain (%d blocks) is not served to %r: it is over the %d-block or %d-byte bound a "
                "peer accepts, so no peer can resynchronise from it or accept its transfers",
                len(blocks), sender[:64], MAX_CHAIN_BLOCKS, MAX_CHAIN_BYTES,
            )
            return []
        return blocks

    async def import_chain_from(self, sender: str, blocks: object) -> tuple[bool, str]:
        """Import ``blocks`` only when it is ``sender``'s own chain, and only as an extension of the chain identity.db
        stores for it (A-1); identity.db's own checks (AD-1196) then run."""
        reason, _ = await self._judged(sender, blocks)
        if reason is not None:
            self._note_refusal(sender, "chain", reason)
            return False, f"identity exchange refused ({reason})"
        return await self._into_ledger(sender, cast("list[dict[str, Any]]", blocks))

    async def import_transfer_from(self, sender: str, cert: TransferCertificate) -> tuple[bool, str]:
        """Import ``cert`` only when it comes from ``sender``'s own ship and names this ship, and only while identity.db
        holds a verified chain of that ship (A-2): against a chain with no key events the registry accepts it unsigned."""
        held = self._seam.held(sender)
        ship = self._registry.get_ship_certificate()
        if not self._admission.pinned(sender):  # AD-1198 a transfer is taken only from a pinned peer
            reason: str | None = "unpinned peer"
        elif held is None or cert.origin_ship_did != held.did:  # AD-1198 a transfer comes from the sender's own ship
            reason = "not the sender's ship"
        elif ship is None or cert.target_instance_did != ship.ship_did:  # AD-1198 a transfer is accepted only for this ship
            reason = "not for this ship"
        elif verified_chain_state(self._registry.get_foreign_chain(held.did), held.did) is None:  # AD-1198 A-2 a certificate is judged only against a verified chain of its ship
            reason = "no verified chain of the sender's ship"
        else:
            reason = None
        if reason is not None:
            self._note_refusal(sender, "transfer", reason)
            return False, f"identity exchange refused ({reason})"
        return await self._registry.import_transfer_certificate(cert)

    def history_gap(self, source: str) -> None:
        """The guard's listener for a key history gap -- and (slice 2b) for a held source's held history or stale key,
        where a recovery in its chain may take precedence over the held events: begin one resync of ``source``, unless it
        is not a pinned peer, one is running, the exchange has stopped, or the last began less than ``RESYNC_INTERVAL_S``
        ago. Returns at once.
        """
        if self._stopped or source in self._resyncs or not self._admission.pinned(source):  # AD-1198 one resync at a time, pinned peers only
            return
        now = self._clock()
        last = self._attempts.get(source)
        if last is not None and now - last < RESYNC_INTERVAL_S:  # AD-1198 at most one resync per peer per interval
            return
        self._attempts[source] = now
        task = asyncio.get_running_loop().create_task(self._resync_logged(source), name=f"ad1198-resync-{source[:64]}")
        self._resyncs[source] = task
        task.add_done_callback(lambda _done: self._resyncs.pop(source, None))

    async def resync(self, source: str) -> bool:
        """Fetch ``source``'s chain and resynchronise the key history held for it (``EnvelopeGuard.resync``). identity.db
        imports the chain first, immediately before the hold is recorded, so a resynchronised hold always has its chain
        in identity.db and a chain identity.db refuses resynchronises nothing (A-1). Returns whether the hold was
        resynchronised.
        """
        request = FederationMessage(type=CHAIN_REQUEST, source_node=self._node_id, payload={}, timestamp=time.monotonic())

        async def ledger_first(answer: FederationMessage) -> str | None:
            try:
                imported, why = await self._into_ledger(source, answer.payload["blocks"], supersede=True)  # AD-1198 A-1 identity.db holds the chain first
            except Exception as exc:  # noqa: BLE001 -- identity.db could not import: the hold is not recorded
                return f"identity.db: {type(exc).__name__}"
            return None if imported else f"identity.db: {why}"  # AD-1198 A-1 a chain identity.db refuses resynchronises nothing

        response = await self._seam.request_resync(
            source, request, self._timeout_ms, lambda answer: self._history(source, answer), before_record=ledger_first,
        )
        if response is None:
            logger.warning(
                "AD-1198: no resync of %r: no admitted chain answer; its envelopes stay refused until a later attempt",
                source[:64],
            )
            return False
        held = self._seam.held(source)
        logger.info(
            "AD-1198: resynchronised the key history held for %r from its chain (key seq %s)",
            source[:64], None if held is None else held.state.seq,
        )
        return True

    async def reset(
        self, source: str, audit: Callable[[PeerReset], None] | None = None,
    ) -> tuple[str | None, PeerReset | None]:
        """AD-1198 slice 2c: on an operator's request, forget the key history held for the configured peer ``source``:
        identity.db's stored chain for the held DID first, then -- in one envelope-store transaction -- the hold, every key
        id recorded for it and its replay windows (``ChainSeam.forget``). The exchange's ledger lock is taken before
        identity.db's chain is forgotten and kept until the hold's write has ended or the guard's bound has passed, so no
        chain import interleaves. Foreign birth and transfer certificates are kept. ``audit`` is called with the
        ``PeerReset`` once the hold's write has committed: inside the write and once, also for a cancelled caller and a
        write that commits after the guard's bound (Amendment A-1). ``(None, PeerReset)`` once done -- also when nothing
        was held -- else ``(reason, None)``: an unconfigured peer, a stopped exchange, a guard not armed or with a store
        write unsettled, or a store that failed. The peer's next envelope is a first contact under its current pin.
        """
        if self._stopped or not self._admission.admits_source(source):  # AD-1198 slice 2c only a configured peer, and only while the exchange runs
            reason = "stopped" if self._stopped else "unconfigured peer"
            logger.warning("AD-1198: the reset of %r was refused (%s); nothing was forgotten", source[:64], reason)
            return reason, None
        found: dict[str, Any] = {}

        def report() -> PeerReset:  # AD-1198 slice 2c A-1 what was forgotten, as identity.db's step read it
            return PeerReset(
                node_id=source, forgotten=found["did"] is not None, did=found["did"], key_seq=found["key_seq"],  # AD-1198 slice 2c forgotten when a history was held
                refused_at_start=found["refused"], identity_chain_blocks=found["blocks"],
            )

        def committed() -> None:
            if audit is not None:  # AD-1198 slice 2c A-1 the operator's audit, once the hold's write has committed
                audit(report())

        @contextlib.asynccontextmanager
        async def ledger_first(did: str | None) -> AsyncIterator[None]:
            async with self._ledger_lock:  # AD-1198 slice 2c no chain import interleaves until the hold's write has ended
                held = self._seam.held(source)
                found.update(did=did, key_seq=None if held is None else held.state.seq, refused=held is None and did is not None)  # AD-1198 slice 2c what is forgotten, read under the accept lock
                found["blocks"] = 0 if did is None else await self._registry.forget_foreign_chain(did)  # AD-1198 slice 2c identity.db forgets the held DID's chain first
                yield

        try:
            reason = await self._seam.forget(source, ledger_first, committed)  # AD-1198 slice 2c the guard forgets the hold inside identity.db's step
        except Exception as exc:  # noqa: BLE001 -- identity.db could not forget its chain: the hold is not forgotten either
            reason = f"identity.db: {type(exc).__name__}"  # AD-1198 slice 2c a failure of identity.db refuses the reset
        if reason is not None:
            logger.warning(
                "AD-1198: the reset of %r was refused (%s); %s", source[:64], reason,
                f"identity.db forgot its {found['blocks']}-block chain for that DID, but the hold's write did not complete, "
                "and a reset that completes forgets both" if "blocks" in found else "nothing was forgotten",
            )
            return reason, None
        reset = report()
        if reset.forgotten:
            logger.warning(
                "AD-1198: reset the key history held for %r on the operator's request (DID %s, %s): its hold, every key id "
                "recorded for it and its replay windows are forgotten, with identity.db's %d-block chain for that DID; its "
                "next envelope is a first contact under its current pin",
                source[:64], reset.did, "refused at start" if reset.refused_at_start else f"key seq {reset.key_seq}",
                reset.identity_chain_blocks,
            )
        else:
            logger.info("AD-1198: reset of %r on the operator's request: no key history was held for it", source[:64])
        return None, reset

    async def stop(self) -> None:
        """Begin no more resyncs, cancel those running and wait for them: a hold write under way is waited for, at most the
        guard's ``STORE_WRITE_SETTLE_S`` (A-1, A-2); shutdown calls this before the bridge and the transport stop."""
        self._stopped = True
        self._seam.on_history_gap(None)
        running = list(self._resyncs.values())
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)

    async def _history(self, source: str, answer: FederationMessage) -> tuple[KeyEvent, ...] | None:
        """The key history of the chain in ``answer`` when it is ``source``'s own; ``None`` otherwise."""
        blocks = answer.payload.get("blocks") if type(answer.payload) is dict else None
        reason, history = await self._judged(source, blocks, supersede=True)  # AD-1198 slice 2b only a resync may move the hold to another branch
        if reason is not None:
            self._note_refusal(source, "resync answer", reason)
            return None
        return history

    async def _into_ledger(
        self, sender: str, blocks: list[dict[str, Any]], *, supersede: bool = False,
    ) -> tuple[bool, str]:
        """identity.db imports ``blocks`` -- ``sender``'s own chain, judged -- only as an extension of the chain it
        stores for that DID (A-1), and that stored chain counts only when it verifies in full (A-2). Against a verified
        stored chain an older snapshot changes nothing and counts as imported, so a transfer it carries is judged against
        the longer stored chain, and a chain that does not extend it is refused -- unless ``supersede`` (a resync; slice
        2b) and ``blocks`` takes recovery-key precedence over it: then it replaces it, the one exception, which the
        registry judges again. A stored chain that does not verify -- unsigned, or failing its hashes, links or
        signatures -- is replaced when ``blocks`` begins with every one of its block hashes, and is otherwise kept and
        ``blocks`` refused. One import at a time, judged again against the hold as it is then, and none while a store write
        of the guard is unsettled (slice 2c, Amendment A-1: a reset may have forgotten the hold since the chain was judged,
        or a first contact after it may hold another branch, and a reset's write may have forgotten a hold the guard still
        shows). identity.db then imports it only while it still stores exactly the chain judged here (``if_stored``;
        BF-885 A-1): an identity.db import whose caller stopped waiting may have committed another since.
        """
        async with self._ledger_lock:  # AD-1198 A-1 compare and import as one step
            did = blocks[0]["agent_did"]
            if not self._seam.settled():  # AD-1198 slice 2c A-1 no import while a store write is unsettled: a reset's may have forgotten a hold the guard still shows
                why: str | None = "store write unsettled"
            else:
                why = _keeps_hold(self._seam.held(sender), chain_key_history(blocks), supersede=supersede)  # AD-1198 slice 2c A-1 the chain judged again against the hold as it is now
            if why is not None:
                self._note_refusal(sender, "chain", why)
                return False, f"identity exchange refused ({why})"
            stored = self._registry.get_foreign_chain(did)
            judged = chain_block_hashes(stored)  # BF-885 A-1 identity.db imports only while it still stores this chain
            superseding = False
            if stored:
                verified = verified_chain_state(stored, did) is not None  # AD-1198 A-2 only a stored chain that verifies is relied on
                kept = list(judged)
                given = [block.get("block_hash") for block in blocks]
                if verified and given == kept[: len(given)]:  # AD-1198 A-1 an older snapshot of the stored chain changes nothing
                    return True, f"Chain kept: the {len(stored)} blocks stored for {did} already hold these {len(blocks)}"
                if given[: len(kept)] != kept:  # AD-1198 A-1 an armed import only extends the stored chain
                    superseding = supersede and verified and recovery_precedence(chain_key_history(stored), chain_key_history(blocks))[0] is not None  # AD-1198 slice 2b a resync's branch replaces a stored branch it takes precedence over
                    if not superseding:
                        reason = "does not extend the stored chain" if verified else "the stored chain does not verify and this one does not contain it"  # AD-1198 A-2 an unverified stored chain is kept, not extended
                        self._note_refusal(sender, "chain", reason)
                        return False, f"identity exchange refused ({reason})"
            return await self._registry.import_chain(blocks, supersede=superseding, if_stored=judged)  # AD-1198 slice 2b the registry judges a branch change again; BF-885 A-1 only while it stores the chain judged here

    async def _judged(
        self, sender: str, blocks: object, *, supersede: bool = False,
    ) -> tuple[str | None, tuple[KeyEvent, ...]]:
        """Why ``blocks`` is not ``sender``'s own chain, or ``None`` and the key history it carries. With ``supersede`` (a
        resync; slice 2b) a chain that does not keep the held events is the sender's own when it takes recovery-key
        precedence over them."""
        if not self._admission.pinned(sender):  # AD-1198 identity is exchanged only with a pinned peer
            return "unpinned peer", ()
        held = self._seam.held(sender)
        if held is None:  # AD-1198 a chain is judged against the history held for its sender
            return "not held", ()
        if not within_chain_bounds(blocks):
            return "over the bounds", ()
        chain = cast("list[dict[str, Any]]", blocks)
        state = verified_chain_state(chain)  # AD-1198 A-2 the same judgement as every chain the exchange relies on
        if state is None:  # AD-1198 an unverified chain is refused
            return "unverified chain", ()
        if state.did != held.did:  # AD-1198 only the sender's own chain
            return "not the sender's chain", ()
        pin = self._admission.identity_refusal(sender, state)  # AD-1198 the pin is judged on the full key state, never a hold
        if pin is not None:
            return pin, ()
        history = chain_key_history(chain)
        why = _keeps_hold(held, history, supersede=supersede)  # AD-1198 slice 2c A-1 one judgement against the hold, made again by the import under the ledger lock
        if why is not None:  # AD-1198 identity.db follows the envelope hold, never another branch
            return why, ()
        return None, history

    async def _resync_logged(self, source: str) -> None:
        try:
            await self.resync(source)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- a resync is an attempt: its failure leaves the hold as it was
            logger.warning(
                "AD-1198: the resync of %r failed (%s); its envelopes stay refused until a later attempt",
                source[:64], type(exc).__name__,
            )

    def _note_refusal(self, sender: str, what: str, reason: str) -> None:
        count = self._refusals.get(reason, 0) + 1
        self._refusals[reason] = count
        if count & (count - 1) == 0:  # AD-1198 sampled: the 1st, 2nd, 4th, 8th ... refusal of a reason
            logger.warning(
                "AD-1198: identity %s from %r refused (%s); %d refused for that reason so far",
                what, sender[:64], reason, count,
            )
