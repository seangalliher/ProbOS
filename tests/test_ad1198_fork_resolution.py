"""AD-1198 slice 2b-i (#1135): key-history continuity across a recovery event.

Tests are named by subject. m0 pins today's code: ordinary admission refuses a branch that parts from the held events,
identity.db keeps a stored key history, and the envelope store never moves a hold back. m1 covers the judgement
(``recovery_precedence``) over real key histories and the store's one write that may move a hold back
(``EnvelopeStore.reanchor``); m2 the guard's resync that re-anchors a hold, its refusals, its trigger and its restart;
m3 identity.db's branch change, the exchange, and the automatic path from a refused envelope to a served one; a1
(Amendment A-1) a cancellation while a store write commits, a history that does not replay after its recovery, the
listener without peer admission, and the in-memory store double's re-anchor; a2 (Amendment A-2) a store write still
running at ``STORE_WRITE_SETTLE_S``: its caller stops waiting there, nothing is admitted until the write ends and then
what it committed is held, and shutdown's stops stay within the bound, each timed from the moment its write began
(Amendment A-3); a3 (Amendment A-3) a close of the store that the guard's stop leaves running, read once it ends and
reported once if it failed. A branch
is made by a second ship over a copy of a node's ledger and keys, which seals as that node. Nodes are real AD-1196 keys
over the in-memory duck keyring with real envelope stores on the mock bus, rebuilt with peer admission through the
production ``build_signed_transport``. No test opens a socket, reaches the real OS keyring (AD-1196's autouse guard is
imported) or a live service.

M0 runs on the unmodified base: write this module up to the ``M1`` marker without the slice-2b import block.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import functools
import json
import logging
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from probos.federation.admission import PeerAdmission
from probos.federation.bridge import FederationBridge
from probos.federation.continuity import IdentityExchange, chain_key_history, stored_key_history
from probos.federation.envelope import BROADCAST, MAX_KEY_EVENTS, POLICY_REQUIRE, EnvelopeGuard
from probos.federation_envelope_store import (
    ENVELOPE_DB_NAME,
    EnvelopeStateConflict,
    EnvelopeStore,
    StoredSender,
    StoredWindow,
)
from probos.identity import AgentIdentityRegistry
from probos.identity_keys import KeyEvent, generate_recovery_keypair, sign_recovery_authorization
from probos.types import FederationMessage, IntentMessage
from tests.test_ad1196_did_key_binding import _armed, _DuckKeyring
from tests.test_ad1196_did_key_binding import _no_real_os_keyring  # noqa: F401 -- the autouse guard (H5)
from tests.test_ad1197_signed_envelopes import (
    _ENVELOPE_LOGGER,
    _active_key,
    _node,
    _Node,
    _RecordingIntentBus,
    _rejections,
    _seal,
    _Wire,
)
from tests.test_ad1198_identity_continuity import (
    _CONTINUITY_LOGGER,
    _answer,
    _exchange,
    _exchange_bridge,
    _messages,
    _rearmed,
    _until,
)
from tests.test_ad1198_peer_admission import _admit

_IDENTITY_LOGGER = "probos.identity"
_GOSSIP = {"node_id": "node-a", "capabilities": [], "pool_sizes": {}, "agent_count": 0, "health": 1.0, "uptime_seconds": 0.0, "timestamp": 0.0}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


@dataclasses.dataclass
class _Copy:
    """A ship over a copy of another node's ledger and keys, sealing envelopes as that node."""

    name: str
    registry: AgentIdentityRegistry
    binding: Any
    guard: EnvelopeGuard


async def _owner(stack: contextlib.AsyncExitStack, wire: _Wire, tmp: Path, name: str = "node-a") -> tuple[_Node, str, str]:
    """``name``, whose inception commits a recovery key; that key's private and public halves."""
    private, public = generate_recovery_keypair()
    node = await _node(stack, wire, tmp, name, recovery_public_key=public)
    return node, private, public


async def _copy(stack: contextlib.AsyncExitStack, node: Any, tmp: Path, recovery_public_key: str, label: str) -> _Copy:
    """A second ship over a copy of ``node``'s ledger and keys as they are now; its next key event parts from ``node``'s."""
    directory = tmp / f"{node.name}-{label}-identity"
    directory.mkdir()
    source = tmp / f"{node.name}-identity" / "identity.db"
    with contextlib.closing(sqlite3.connect(source)) as given, contextlib.closing(sqlite3.connect(directory / "identity.db")) as made:
        given.backup(made)
    duck = _DuckKeyring()
    duck.entries.update(node.duck.entries)
    registry, binding = await stack.enter_async_context(_armed(
        directory, duck, recovery_public_key=recovery_public_key, instance_id=node.name.replace("node", "ship"),
    ))
    store = tmp / f"{node.name}-{label}-data"
    store.mkdir()
    guard = EnvelopeGuard(
        signer=binding, store=EnvelopeStore(store / ENVELOPE_DB_NAME), local_node_id=node.name, policy=POLICY_REQUIRE,
    )
    stack.push_async_callback(guard.stop)
    await guard.start()
    return _Copy(node.name, registry, binding, guard)


async def _resealed(stack: contextlib.AsyncExitStack, ship: _Copy, path: Path, *, times: int) -> EnvelopeGuard:
    """``ship``'s sealer restarted ``times`` times on its store at ``path``: each start commits a later send epoch."""
    guard = ship.guard
    for _ in range(times):
        await guard.stop()
        guard = EnvelopeGuard(signer=ship.binding, store=EnvelopeStore(path), local_node_id=ship.name, policy=POLICY_REQUIRE)
        stack.push_async_callback(guard.stop)
        await guard.start()
    return guard


async def _recover(binding: Any, private: str, *, reason: str = "compromised") -> None:
    """A recovery signed by the committed recovery key; for ``compromised``, from the active key's activation."""
    status = await binding.status()
    active = next(key for key in status["keys"] if key["kid"] == status["active_kid"])
    after = active["activated_at"] if reason == "compromised" else None
    prepared = await binding.prepare_recovery(reason=reason, compromised_after_index=after, next_recovery_public_key="")
    await binding.apply_recovery(
        authorization=sign_recovery_authorization(private, prepared["signing_payload"]),
        reason=reason, compromised_after_index=after, next_recovery_public_key="",
    )


async def _history(ship: Any) -> tuple[KeyEvent, ...]:
    return chain_key_history(await ship.registry.export_chain())


async def _deliver(guard: EnvelopeGuard, ship: Any, rotations: int) -> None:
    """``ship`` rotates ``rotations`` times; ``guard`` admits one of its envelopes after every 31, so it holds them all."""
    for done in range(1, rotations + 1):
        await ship.binding.rotate()
        if done % 31 == 0 or done == rotations:
            assert await guard.admit(await _seal(ship, "node-b")), "premise: the guard holds this branch"


async def _guard(
    stack: contextlib.AsyncExitStack, tmp: Path, pins: dict[str, str], *, label: str = "holder",
    store: Callable[[Path], EnvelopeStore] = EnvelopeStore, path: Path | None = None,
) -> tuple[EnvelopeGuard, Path]:
    """Node-b's armed guard with peer admission over ``store`` at ``path`` (a fresh one by default); and that path."""
    _, signer = await stack.enter_async_context(_armed(tmp / f"{label}-identity", _DuckKeyring(), instance_id="ship-b"))
    if path is None:
        (tmp / f"{label}-data").mkdir()
        path = tmp / f"{label}-data" / ENVELOPE_DB_NAME
    guard = EnvelopeGuard(
        signer=signer, store=store(path), local_node_id="node-b", policy=POLICY_REQUIRE,
        identity_policy=PeerAdmission(local_node_id="node-b", pins=pins),
    )
    stack.push_async_callback(guard.stop)
    await guard.start()
    return guard, path


async def _scene(stack: contextlib.AsyncExitStack, tmp: Path, *, pins: dict[str, str] | None = None) -> tuple[_Node, str, _Copy, EnvelopeGuard, Path]:
    """Node-a (a recovery key committed at its inception), a copy of it, and node-b's guard pinned to node-a's inception
    key (or ``pins``) and holding node-a's inception; node-a's recovery private key and the guard's store path."""
    a, private, public = await _owner(stack, _Wire(), tmp)
    _, pin = await _active_key(a.binding)
    guard, path = await _guard(stack, tmp, {"node-a": pin} if pins is None else pins)
    assert await guard.admit(await _seal(a, "node-b")), "premise: node-b holds node-a's inception"
    return a, private, await _copy(stack, a, tmp, public, "x"), guard, path


def _store_rows(path: Path) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    """The held senders ``(source, did, key_seq, key_head, key ids)`` and the replay windows, as committed."""
    with contextlib.closing(sqlite3.connect(path)) as db:
        senders = [
            (source, did, seq, head, sorted(json.loads(ids)))
            for source, did, seq, head, ids in db.execute(
                "SELECT source_node, did, key_seq, key_head, key_ids_json FROM envelope_senders ORDER BY source_node",
            )
        ]
        windows = db.execute(
            "SELECT source_node, channel, key_seq, epoch, hwm, mask FROM envelope_windows ORDER BY source_node, channel",
        ).fetchall()
    return senders, windows


async def _kids(ship: Any) -> set[str]:
    return {key["kid"] for key in (await ship.binding.status())["keys"]}


def _reanchored(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [line for line in _messages(caplog, _ENVELOPE_LOGGER, logging.WARNING) if line.startswith("AD-1198: re-anchored")]


async def _fork_pair(
    stack: contextlib.AsyncExitStack, wire: _Wire, tmp: Path,
) -> tuple[_Node, str, str, _Node, str, IdentityExchange, FederationBridge, _RecordingIntentBus]:
    """Node-a (a recovery key committed at its inception) and node-b, pinned to each other, each with an exchange behind
    an armed bridge and each holding the other; node-a's recovery key halves and pin, node-b's exchange, node-a's bridge
    and node-b's intent bus."""
    a, private, public = await _owner(stack, wire, tmp)
    b = await _node(stack, wire, tmp, "node-b")
    _, pin_a = await _active_key(a.binding)
    _, pin_b = await _active_key(b.binding)
    await _admit(stack, a, pins={"node-b": pin_b})
    await _admit(stack, b, pins={"node-a": pin_a})
    exchange_a = _exchange(a, {"node-b": pin_b})
    exchange_b = _exchange(b, {"node-a": pin_a})
    stack.push_async_callback(exchange_a.stop)
    stack.push_async_callback(exchange_b.stop)
    bridge_a = await _exchange_bridge(stack, a, exchange_a, _RecordingIntentBus("node-a"), peer="node-b")
    bus_b = _RecordingIntentBus("node-b")
    bridge_b = await _exchange_bridge(stack, b, exchange_b, bus_b, peer="node-a")
    assert await bridge_b.request_chain("node-a") == await a.registry.export_chain()  # premise: each holds the other
    return a, private, public, b, pin_a, exchange_b, bridge_a, bus_b


async def _held_on_copy(wire: _Wire, a: _Node, b: _Node, exchange_b: IdentityExchange, tmp: Path, public: str, stack: contextlib.AsyncExitStack) -> _Copy:
    """A copy of node-a rotates once and node-b's armed transport admits its gossip, so node-b holds the copy's branch;
    identity.db then stores the copy's chain through the exchange, as a transfer from it would."""
    x = await _copy(stack, a, tmp, public, "x")
    await x.binding.rotate()
    await wire.inject("node-b", await _seal(x, BROADCAST, kind="gossip_self_model", payload=dict(_GOSSIP)))
    held = b.transport.chain_seam.held("node-a")
    assert held is not None and held.events == await _history(x), "premise: node-b holds the copy's branch"
    assert await exchange_b.import_chain_from("node-a", await x.registry.export_chain()) == (
        True, f"Chain imported: {len(await x.registry.export_chain())} blocks from {held.did}",
    ), "premise: identity.db stores the copy's chain"
    return x


# --------------------------------------------------------------------------- #
# M0 -- today's code (passes on the unmodified base)
# --------------------------------------------------------------------------- #


async def test_s2b_m0_ordinary_admission_identity_db_and_the_store_keep_the_held_branch(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        a, private, x, guard, _ = await _scene(stack, tmp_path)
        await _deliver(guard, x, 3)  # the held events follow the copy, three past the inception
        await _recover(a.binding, private)
        held = guard.held("node-a")
        behind = await guard.admit(await _seal(a, "node-b"))  # its head (1) is behind the held head (3)
        await a.binding.rotate()
        await a.binding.rotate()
        level = await guard.admit(await _seal(a, "node-b"))  # its head (3) is the held head; its event at 1 differs
        x_chain, a_chain = await x.registry.export_chain(), await a.registry.export_chain()
        registry, _ = await stack.enter_async_context(_armed(tmp_path / "r-identity", _DuckKeyring(), instance_id="ship-r"))
        stored = await registry.import_chain(x_chain)
        replaced = await registry.import_chain(a_chain)
        store = EnvelopeStore(tmp_path / "m0-store.db")
        await store.start()
        stack.push_async_callback(store.stop)
        await store.record("node-a", "direct", StoredSender(held.did, 3, "a" * 64, "[]"), StoredWindow(3, 1, 1, 1), frozenset({"k"}))
        with pytest.raises(EnvelopeStateConflict, match="cannot move backwards"):
            await store.record("node-a", "direct", StoredSender(held.did, 1, "b" * 64, "[]"), StoredWindow(3, 1, 2, 1), frozenset({"k"}))

    assert behind is False and level is False and guard.held("node-a") == held
    assert [reason for *_, reason in _rejections(caplog)[-2:]] == ["stale key", "held history"]
    assert stored[0] is True and replaced[0] is False and replaced[1].startswith("Key history check failed: ")
    assert registry.get_foreign_chain(held.did) == x_chain


# M1 marker
# --------------------------------------------------------------------------- #
# slice 2b names (M1 onward; omit this block for the M0 run on the unmodified base)
# --------------------------------------------------------------------------- #

from probos.federation.envelope import DIVERGENCE_REFUSALS  # noqa: E402
from probos.identity_keys import EVENT_RECOVERY, chain_key_events, recovery_precedence  # noqa: E402


# --------------------------------------------------------------------------- #
# M1 -- the judgement and the store's re-anchor
# --------------------------------------------------------------------------- #


@dataclasses.dataclass
class _Shapes:
    """Real key histories that part after a state the branches share at key seq 1."""

    owner: _Node
    held: dict[str, tuple[KeyEvent, ...]]  # each copy's newest 32 events, as a guard holds them
    history: dict[str, tuple[KeyEvent, ...]]  # node-a's own full histories, and two copies' as other owners' histories


async def _shapes(stack: contextlib.AsyncExitStack, tmp: Path) -> _Shapes:
    a, private, public = await _owner(stack, _Wire(), tmp)
    await a.binding.rotate()  # the shared state is key seq 1, so a held run can start after the inception
    copies = {label: await _copy(stack, a, tmp, public, label) for label in ("x1", "x3", "x32", "x33", "xr", "y", "z")}
    before = await _history(a)
    for label, rotations in (("x1", 1), ("x3", 3), ("x32", 32), ("x33", 33), ("y", 1)):
        for _ in range(rotations):
            await copies[label].binding.rotate()
    await _recover(copies["xr"].binding, private, reason="lost")
    await _recover(copies["z"].binding, private, reason="lost")
    await _recover(a.binding, private)
    recovered = await _history(a)
    await a.binding.rotate()
    await a.binding.rotate()
    held = {label: (await _history(ship))[-MAX_KEY_EVENTS:] for label, ship in copies.items()}
    histories = {
        "before": before, "recovered": recovered, "ahead": await _history(a),
        "rotated": await _history(copies["y"]), "lost": await _history(copies["z"]),
    }
    return _Shapes(a, held, histories)


def _tampered(events: tuple[KeyEvent, ...]) -> tuple[KeyEvent, ...]:
    """``events`` with the recovery signature of its last event replaced by that event's own key's signature."""
    last = events[-1]
    assert last.payload["event"] == EVENT_RECOVERY, "premise: the last event is a recovery"
    return (*events[:-1], dataclasses.replace(last, signatures={**last.signatures, "recovery": last.signatures["new"]}))


async def test_s2b_m1_a_recovery_from_the_shared_state_takes_precedence_over_the_held_events(tmp_path: Path) -> None:
    async with contextlib.AsyncExitStack() as stack:
        s = await _shapes(stack, tmp_path)
        chain = await s.owner.registry.export_chain()
    cases = {
        "equal heads": (s.held["x1"], s.history["recovered"]),
        "the held branch is longer": (s.held["x3"], s.history["recovered"]),
        "the owner is ahead": (s.held["x1"], s.history["ahead"]),
        "a recovery for a lost key": (s.held["x1"], s.history["lost"]),
        "the held run starts at the divergence": (s.held["x32"], s.history["recovered"]),
        "the held run starts after the inception": (s.held["x3"][1:], s.history["recovered"]),
        "the held recovery does not replay": (_tampered(s.held["xr"]), s.history["recovered"]),
    }

    assert s.held["x32"][0].payload["seq"] == 2 and s.held["x3"][1:][0].payload["seq"] == 1  # premise: where the runs start
    assert {name: recovery_precedence(*pair) for name, pair in cases.items()} == {
        name: (2, "a recovery at key seq 2 supersedes the held events from there") for name in cases
    }
    assert chain_key_events(chain) == chain_key_history(chain) == s.history["ahead"]  # one reading of a chain's key events
    assert len(chain) == len(s.history["ahead"]) + 1  # every block but the genesis is a key event here


async def test_s2b_m1_a_branch_whose_first_divergent_event_is_not_such_a_recovery_is_refused(tmp_path: Path) -> None:
    async with contextlib.AsyncExitStack() as stack:
        s = await _shapes(stack, tmp_path)
    cases = {
        "the first divergent event is a rotation": ((s.held["x1"], s.history["rotated"]), "the first divergent event is not a recovery"),
        "both branches recover from the shared state": ((s.held["xr"], s.history["recovered"]), "both branches recover there"),
        "the held run starts past the divergence": ((s.held["x33"], s.history["recovered"]), "the held events do not follow this history"),
        "the history ends before the held run": ((s.held["x33"], s.history["before"]), "the held events do not follow this history"),
        "the held run follows the history's end": ((s.held["x3"][2:], s.history["before"]), "no divergent event"),
        "the history is a prefix of the held run": ((s.held["x3"], s.history["before"]), "no divergent event"),
        "the held run is a prefix of the history": ((s.history["before"], s.history["recovered"]), "no divergent event"),
        "the recovery does not replay from the shared state": ((s.held["x1"], _tampered(s.history["recovered"])), "the recovery does not replay from the shared state"),
    }

    assert {name: recovery_precedence(*pair) for name, (pair, _) in cases.items()} == {name: (None, why) for name, (_, why) in cases.items()}


async def test_s2b_m1_precedence_judges_only_a_full_history_and_a_contiguous_held_run_and_never_raises(tmp_path: Path) -> None:
    async with contextlib.AsyncExitStack() as stack:
        s = await _shapes(stack, tmp_path)
    held, history = s.held["x1"], s.history["recovered"]
    cases = {
        "no held events": (((), history), "not a full key history"),
        "no history": ((held, ()), "not a full key history"),
        "a history without its inception": ((held, history[1:]), "not a full key history"),
        "a held run with a gap": ((held[:1] + held[2:], history), "not a contiguous held run"),
        "a held event without a sequence number": (((dataclasses.replace(held[0], payload={}), *held[1:]), history), "the history does not replay"),
    }

    assert {name: recovery_precedence(*pair) for name, (pair, _) in cases.items()} == {name: (None, why) for name, (_, why) in cases.items()}


async def test_s2b_m1_reanchor_moves_a_hold_back_and_clears_its_windows_in_one_transaction(tmp_path: Path) -> None:
    store = EnvelopeStore(tmp_path / ENVELOPE_DB_NAME)
    await store.start()
    try:
        await store.record("node-a", "direct", StoredSender("did:probos:ship-a", 4, "a" * 64, "[]"), StoredWindow(4, 1, 9, 1), frozenset({"k0", "k4"}))
        await store.record("node-a", "broadcast", None, StoredWindow(4, 1, 3, 1))
        await store.record("node-c", "direct", StoredSender("did:probos:ship-c", 0, "c" * 64, "[]"), StoredWindow(0, 1, 1, 1), frozenset({"c0"}))
        moved = StoredSender("did:probos:ship-a", 2, "b" * 64, '[{"seq": 2}]')
        await store.reanchor("node-a", "direct", moved, StoredWindow(2, 7, 1, 1), frozenset({"k0", "k4", "r2"}))
        senders, windows = await store.load()
        recorded = await store.key_ids("node-a")
    finally:
        await store.stop()

    assert senders["node-a"] == moved and senders["node-c"].key_seq == 0  # moved back; another source untouched
    assert windows == {("node-a", "direct"): StoredWindow(2, 7, 1, 1), ("node-c", "direct"): StoredWindow(0, 1, 1, 1)}
    assert recorded == {"k0", "k4", "r2"}


async def test_s2b_m1_reanchor_refuses_an_unheld_source_a_forgotten_key_id_or_another_did_and_writes_nothing(tmp_path: Path) -> None:
    store = EnvelopeStore(tmp_path / ENVELOPE_DB_NAME)
    await store.start()
    try:
        await store.record("node-a", "direct", StoredSender("did:probos:ship-a", 4, "a" * 64, "[]"), StoredWindow(4, 1, 9, 1), frozenset({"k0", "k4"}))
        await store.record("node-a", "broadcast", None, StoredWindow(4, 1, 3, 1))
        before = await store.load()
        moved = StoredSender("did:probos:ship-a", 2, "b" * 64, "[]")
        ids = frozenset({"k0", "k4", "r2"})
        with pytest.raises(EnvelopeStateConflict, match="no key history is held for 'node-z'"):
            await store.reanchor("node-z", "direct", moved, StoredWindow(2, 7, 1, 1), ids)
        with pytest.raises(EnvelopeStateConflict, match="cannot be forgotten"):
            await store.reanchor("node-a", "direct", moved, StoredWindow(2, 7, 1, 1), frozenset({"k0", "r2"}))
        with pytest.raises(EnvelopeStateConflict, match="names another DID"):
            await store.reanchor("node-a", "direct", dataclasses.replace(moved, did="did:probos:ship-x"), StoredWindow(2, 7, 1, 1), ids)
        with pytest.raises(sqlite3.IntegrityError):  # a mask too wide for its column fails after the windows were cleared
            await store.reanchor("node-a", "direct", moved, StoredWindow(2, 7, 1, 1 << 64), ids)
        after = await store.load()
        recorded = await store.key_ids("node-a")
    finally:
        await store.stop()

    assert after == before  # every refusal and the failure rolled the whole transaction back
    assert recorded == {"k0", "k4"}

# --------------------------------------------------------------------------- #
# M2 -- the guard's resync re-anchors a hold
# --------------------------------------------------------------------------- #


class _Store(EnvelopeStore):
    """An envelope store that can report one more recorded key id than it holds, and fail its re-anchor or end it
    cancelled."""

    extra: frozenset[str] = frozenset()
    fail_reanchor = False
    cancel_reanchor = False

    async def key_ids(self, source: str) -> frozenset[str]:
        return await super().key_ids(source) | self.extra

    async def reanchor(self, *args: Any, **kwargs: Any) -> None:
        if self.fail_reanchor:
            raise RuntimeError("the store is not writable")
        if self.cancel_reanchor:
            raise asyncio.CancelledError
        await super().reanchor(*args, **kwargs)


async def test_s2b_m2_a_resync_whose_chain_takes_precedence_re_anchors_the_hold(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        a, private, x, guard, path = await _scene(stack, tmp_path)
        x.guard = await _resealed(stack, x, tmp_path / "node-a-x-data" / ENVELOPE_DB_NAME, times=2)  # a later send epoch than node-a's
        await _deliver(guard, x, 1)
        assert await guard.admit(await _seal(x, BROADCAST, kind="gossip_self_model", payload=dict(_GOSSIP)))  # a broadcast window too
        branch_kids = await _kids(x)
        await _recover(a.binding, private)
        refused = await guard.admit(await _seal(a, "node-b"))
        answer = await _answer(a, "node-b")
        history = chain_key_history(answer.payload["blocks"])
        resynced = await guard.resync(answer, history)
        held = guard.held("node-a")
        senders, windows = _store_rows(path)
        served = await guard.admit(await _seal(a, "node-b"))
        broadcast = await guard.admit(await _seal(a, BROADCAST, kind="gossip_self_model", payload=dict(_GOSSIP)))
        await x.binding.rotate()
        copied = await guard.admit(await _seal(x, "node-b"))
        recovery_kids = await _kids(a)

    assert refused is False and resynced is True and served is True and broadcast is True and copied is False
    assert held is not None and held.events == history and held.state.seq == 1 and held.events[-1].payload["event"] == EVENT_RECOVERY
    assert senders == [("node-a", held.did, 1, held.state.head_digest, sorted(branch_kids | recovery_kids))]  # both branches' keys stay recorded
    assert windows == [("node-a", "direct", 1, answer.auth["epoch"], answer.auth["seq"], "0000000000000001")]  # the windows start again
    assert [reason for *_, reason in _rejections(caplog)] == ["held history", "held history"]
    assert _reanchored(caplog) == [
        "AD-1198: re-anchored the key history held for 'node-a' on the branch its chain carries: the recovery at key seq 1 "
        "takes precedence over the held events from there (key seq 1 -> 1); its replay windows start again, and the 3 key "
        "ids recorded for it, of both branches, stay recorded",
    ]


async def test_s2b_m2_a_re_anchor_may_move_the_hold_back(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        a, private, x, guard, path = await _scene(stack, tmp_path)
        await _deliver(guard, x, 3)
        await _recover(a.binding, private)
        refused = await guard.admit(await _seal(a, "node-b"))
        answer = await _answer(a, "node-b")
        resynced = await guard.resync(answer, chain_key_history(answer.payload["blocks"]))
        senders, _ = _store_rows(path)
        served = await guard.admit(await _seal(a, "node-b"))
        held = guard.held("node-a")

    assert refused is False and resynced is True and served is True
    assert held is not None and held.state.seq == 1 and senders[0][2] == 1  # the hold moved back from key seq 3
    assert [reason for *_, reason in _rejections(caplog)] == ["stale key"]
    assert "(key seq 3 -> 1)" in _reanchored(caplog)[0] and "the 5 key ids recorded" in _reanchored(caplog)[0]


async def test_s2b_m2_a_resync_whose_chain_does_not_take_precedence_changes_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    outcomes: list[tuple[bool, bool, bool]] = []
    async with contextlib.AsyncExitStack() as stack:
        for label, held_branch, owner in (("rotation", "rotate", "rotate"), ("recoveries", "recover", "recover"), ("deep", "deep", "recover")):
            (tmp_path / label).mkdir()
            a, private, x, guard, path = await _scene(stack, tmp_path / label)
            if held_branch == "recover":  # the held branch begins with a recovery from the same state
                await _recover(x.binding, private, reason="lost")
                assert await guard.admit(await _seal(x, "node-b")), "premise: the guard holds the copy's recovery"
            else:
                await _deliver(guard, x, 1 if held_branch == "rotate" else MAX_KEY_EVENTS + 1)
            if owner == "rotate":
                await a.binding.rotate()
            else:
                await _recover(a.binding, private)
            held, rows = guard.held("node-a"), _store_rows(path)
            answer = await _answer(a, "node-b")
            resynced = await guard.resync(answer, chain_key_history(answer.payload["blocks"]))
            outcomes.append((resynced, guard.held("node-a") == held, _store_rows(path) == rows))

    assert outcomes == [(False, True, True)] * 3
    assert [args[1] for args in (record.args for record in caplog.records if record.name == _ENVELOPE_LOGGER and "not admitted for a resync" in str(record.msg))] == [
        "held history", "held history", "stale key",
    ]
    assert _reanchored(caplog) == []


async def test_s2b_m2_a_re_anchor_satisfies_the_pin_on_the_full_key_state(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        a, private, public = await _owner(stack, _Wire(), tmp_path)
        x = await _copy(stack, a, tmp_path, public, "x")
        await x.binding.rotate()
        _, pin = await _active_key(x.binding)  # a key only the copy's branch introduces
        guard, path = await _guard(stack, tmp_path, {"node-a": pin})
        assert await guard.admit(await _seal(x, "node-b")), "premise: the copy's branch satisfies that pin"
        await _recover(a.binding, private)
        held, rows = guard.held("node-a"), _store_rows(path)
        answer = await _answer(a, "node-b")
        resynced = await guard.resync(answer, chain_key_history(answer.payload["blocks"]))

    assert resynced is False and guard.held("node-a") == held and _store_rows(path) == rows
    assert [record.args[1] for record in caplog.records if "not admitted for a resync" in str(record.msg)] == ["pin (key)"]


async def test_s2b_m2_a_re_anchor_reintroduces_no_key_recorded_for_the_sender(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        a, private, public = await _owner(stack, _Wire(), tmp_path)
        _, pin = await _active_key(a.binding)
        guard, path = await _guard(stack, tmp_path, {"node-a": pin}, store=_Store)
        assert await guard.admit(await _seal(a, "node-b"))
        x = await _copy(stack, a, tmp_path, public, "x")
        await _deliver(guard, x, 1)
        await _recover(a.binding, private)
        store = vars(guard)["_store"]
        store.extra = frozenset({(await a.binding.status())["active_kid"]})  # as if the recovery's key were recorded already
        held, rows = guard.held("node-a"), _store_rows(path)
        answer = await _answer(a, "node-b")
        resynced = await guard.resync(answer, chain_key_history(answer.payload["blocks"]))

    assert resynced is False and guard.held("node-a") == held and _store_rows(path) == rows
    assert [record.args[1] for record in caplog.records if "not admitted for a resync" in str(record.msg)] == ["key history does not replay"]


async def test_s2b_m2_a_held_sources_divergence_tells_the_listener_and_nothing_else_does(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, private, public = await _owner(stack, wire, tmp_path)
        c = await _node(stack, wire, tmp_path, "node-c")
        _, pin = await _active_key(a.binding)
        guard, _ = await _guard(stack, tmp_path, {"node-a": pin, "node-c": ""})
        told: list[str] = []
        guard.on_history_gap(told.append)
        first = await _seal(a, "node-b")
        assert await guard.admit(first)
        unheld = await _seal(c, "node-b")
        assert await guard.admit(dataclasses.replace(unheld, auth={**unheld.auth, "key_head": "0" * 64})) is False  # stale key, never held
        assert await guard.admit(first) is False  # a duplicate
        x = await _copy(stack, a, tmp_path, public, "x")
        await _deliver(guard, x, 1)
        await _recover(a.binding, private)
        assert await guard.admit(await _seal(a, "node-b")) is False  # held history
        await _deliver(guard, x, 2)
        assert await guard.admit(await _seal(a, "node-b")) is False  # stale key
        guard.on_history_gap(None)
        assert await guard.admit(await _seal(a, "node-b")) is False

    assert told == ["node-a", "node-a"]
    assert [reason for *_, reason in _rejections(caplog)] == ["stale key", "duplicate", "held history", "stale key", "stale key"]
    assert DIVERGENCE_REFUSALS == frozenset({"held history", "stale key"})


async def test_s2b_m2_a_re_anchor_identity_db_refuses_or_the_store_cannot_write_changes_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        a, private, public = await _owner(stack, _Wire(), tmp_path)
        _, pin = await _active_key(a.binding)
        guard, path = await _guard(stack, tmp_path, {"node-a": pin}, store=_Store)
        assert await guard.admit(await _seal(a, "node-b"))
        x = await _copy(stack, a, tmp_path, public, "x")
        await _deliver(guard, x, 1)
        await _recover(a.binding, private)
        held, rows = guard.held("node-a"), _store_rows(path)
        answer = await _answer(a, "node-b")
        history = chain_key_history(answer.payload["blocks"])

        async def refuse() -> str | None:
            return "identity.db: refused"

        refused = await guard.resync(answer, history, refuse)
        vars(guard)["_store"].fail_reanchor = True
        unwritten = await guard.resync(answer, history)
        unchanged = guard.held("node-a") == held and _store_rows(path) == rows
        vars(guard)["_store"].fail_reanchor = False
        written = await guard.resync(answer, history)

    assert (refused, unwritten, unchanged, written) == (False, False, True, True)
    assert [record.args[1] for record in caplog.records if "not admitted for a resync" in str(record.msg)] == [
        "identity.db: refused", "not recorded (RuntimeError)",
    ]
    assert len(_reanchored(caplog)) == 1


async def test_s2b_m2_a_re_anchored_hold_survives_a_restart(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        a, private, x, guard, path = await _scene(stack, tmp_path)
        _, pin = await _active_key(a.binding)
        await _deliver(guard, x, 2)
        await _recover(a.binding, private)
        answer = await _answer(a, "node-b")
        assert await guard.resync(answer, chain_key_history(answer.payload["blocks"]))
        held = guard.held("node-a")
        await guard.stop()
        restarted, _ = await _guard(stack, tmp_path, {"node-a": pin}, label="restarted", path=path)
        kept = restarted.held("node-a")
        served = await restarted.admit(await _seal(a, "node-b"))
        await x.binding.rotate()
        copied = await restarted.admit(await _seal(x, "node-b"))

    assert held is not None and kept == held and kept.state.seq == 1
    assert served is True and copied is False and _rejections(caplog)[-1][-1] == "held history"

# --------------------------------------------------------------------------- #
# M3 -- identity.db, the exchange, and the automatic path
# --------------------------------------------------------------------------- #


def _replacements(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [line for line in _messages(caplog, _IDENTITY_LOGGER, logging.WARNING) if line.startswith("AD-1198: the chain stored")]


async def test_s2b_m3_identity_db_replaces_a_stored_branch_only_when_asked_and_a_recovery_takes_precedence(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_IDENTITY_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        a, private, public = await _owner(stack, _Wire(), tmp_path)
        x = await _copy(stack, a, tmp_path, public, "x")
        y = await _copy(stack, a, tmp_path, public, "y")
        await x.binding.rotate()
        await y.binding.rotate()
        await _recover(a.binding, private)
        registry, _ = await stack.enter_async_context(_armed(tmp_path / "r-identity", _DuckKeyring(), instance_id="ship-r"))
        x_chain, y_chain, a_chain = await x.registry.export_chain(), await y.registry.export_chain(), await a.registry.export_chain()
        did = (await a.binding.status())["did"]
        outcomes = [
            await registry.import_chain(x_chain),
            await registry.import_chain(a_chain),  # not asked
            await registry.import_chain(y_chain, supersede=True),  # asked; its first divergent event is a rotation
        ]
        kept = registry.get_foreign_chain(did)
        outcomes.append(await registry.import_chain(a_chain, supersede=True))
        replaced = registry.get_foreign_chain(did)
        await a.binding.rotate()
        longer = await a.registry.export_chain()
        outcomes.append(await registry.import_chain(longer, supersede=True))  # an extension supersedes nothing
        extended = registry.get_foreign_chain(did)

    held_at = len(x_chain) - 1  # the copy's rotation is the last block of its chain
    assert [ok for ok, _ in outcomes] == [True, False, False, True, True]
    assert outcomes[1][1] == outcomes[2][1] == f"Key history check failed: the key event held at block {held_at} is missing or changed"
    assert kept == x_chain and replaced == a_chain and extended == longer
    assert _replacements(caplog) == [
        f"AD-1198: the chain stored for {did} is replaced by one whose recovery at key seq 1 takes precedence over it "
        f"(the key event held at block {held_at} is missing or changed); the replaced branch is no longer stored here",
    ]


async def test_s2b_m3_a_transfer_chain_never_moves_either_hold_and_a_resync_moves_both(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_IDENTITY_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, private, public, b, _, exchange_b, _, _ = await _fork_pair(stack, wire, tmp_path)
        x = await _held_on_copy(wire, a, b, exchange_b, tmp_path, public, stack)
        x_chain = await x.registry.export_chain()
        await _recover(a.binding, private)
        a_chain = await a.registry.export_chain()
        did = (await a.binding.status())["did"]
        transferred = await exchange_b.import_chain_from("node-a", a_chain)  # the chain a transfer carries
        after_transfer = (b.registry.get_foreign_chain(did), b.transport.chain_seam.held("node-a"))

        async def full(answer: FederationMessage) -> tuple[KeyEvent, ...] | None:
            return chain_key_history(answer.payload["blocks"])

        request = FederationMessage(type="chain_request", source_node="node-b", payload={})
        moved = await b.transport.chain_seam.request_resync("node-a", request, 2_000, full)  # the hold alone moves
        hold_only = (b.registry.get_foreign_chain(did), b.transport.chain_seam.held("node-a"))
        transferred_again = await exchange_b.import_chain_from("node-a", a_chain)
        resynced = await exchange_b.resync("node-a")
        both = (b.registry.get_foreign_chain(did), b.transport.chain_seam.held("node-a"))

    assert transferred == (False, "identity exchange refused (held history)")
    assert after_transfer[0] == x_chain and after_transfer[1] is not None and after_transfer[1].events == chain_key_history(x_chain)
    assert moved is not None and hold_only[0] == x_chain and hold_only[1] is not None and hold_only[1].events == chain_key_history(a_chain)
    assert transferred_again == (False, "identity exchange refused (does not extend the stored chain)")  # never through a transfer
    assert resynced is True and both[0] == a_chain and both[1] is not None and both[1].events == chain_key_history(a_chain)
    assert len(_replacements(caplog)) == 1


async def test_s2b_m3_a_resync_whose_chain_parts_by_a_rotation_changes_neither_hold(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, _, public, b, _, exchange_b, _, _ = await _fork_pair(stack, wire, tmp_path)
        x = await _held_on_copy(wire, a, b, exchange_b, tmp_path, public, stack)
        x_chain = await x.registry.export_chain()
        await a.binding.rotate()  # node-a's own next event is a rotation, not a recovery
        did = (await a.binding.status())["did"]
        held = b.transport.chain_seam.held("node-a")
        resynced = await exchange_b.resync("node-a")

    assert resynced is False and b.transport.chain_seam.held("node-a") == held and b.registry.get_foreign_chain(did) == x_chain
    assert exchange_b.refusal_counts == {"held history: the first divergent event is not a recovery": 1}


async def test_s2b_m3_a_divergent_held_history_heals_through_one_automatic_resync(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    for name in (_ENVELOPE_LOGGER, _CONTINUITY_LOGGER, _IDENTITY_LOGGER):
        caplog.set_level(logging.INFO, logger=name)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, private, public, b, _, exchange_b, bridge_a, bus_b = await _fork_pair(stack, wire, tmp_path)
        b.transport.chain_seam.on_history_gap(exchange_b.history_gap)
        x = await _held_on_copy(wire, a, b, exchange_b, tmp_path, public, stack)
        await _recover(a.binding, private)
        a_chain = await a.registry.export_chain()
        did = (await a.binding.status())["did"]

        missed = await bridge_a.forward_intent(IntentMessage(intent="read_file", params={"path": "/a"}))
        await _until(lambda: (held := b.transport.chain_seam.held("node-a")) is not None and held.events == chain_key_history(a_chain), what="the re-anchor")
        await _until(lambda: b.registry.get_foreign_chain(did) == a_chain, what="identity.db to follow the recovery")
        answered = await bridge_a.forward_intent(IntentMessage(intent="read_file", params={"path": "/a"}))
        await x.binding.rotate()
        await wire.inject("node-b", await _seal(x, BROADCAST, kind="gossip_self_model", payload=dict(_GOSSIP)))

    assert list(missed) == [] and [result.result for result in answered] == ["done by node-b"] and len(bus_b.broadcasts) == 1
    assert _rejections(caplog)[0] == ("intent_request", "node-a", "held history")
    assert _rejections(caplog)[-1] == ("gossip_self_model", "node-a", "held history")  # the replaced branch is refused
    assert len(_reanchored(caplog)) == 1 and len(_replacements(caplog)) == 1
    assert _messages(caplog, _CONTINUITY_LOGGER, logging.INFO) == [
        "AD-1198: resynchronised the key history held for 'node-a' from its chain (key seq 1)",
    ]


async def test_s2b_m3_a_recovery_past_a_key_history_gap_re_anchors_and_keeps_its_pin_across_a_restart(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, private, public, b, pin_a, exchange_b, _, _ = await _fork_pair(stack, wire, tmp_path)
        await _held_on_copy(wire, a, b, exchange_b, tmp_path, public, stack)
        await _recover(a.binding, private)
        for _ in range(MAX_KEY_EVENTS + 1):
            await a.binding.rotate()  # node-a's next envelope cannot reach the held head
        await a.transport.send_to_peer("node-b", FederationMessage(type="ping", source_node="node-a", payload={}, timestamp=1.0))
        resynced = await exchange_b.resync("node-a")
        held = b.transport.chain_seam.held("node-a")
        await exchange_b.stop()
        pins = {"node-a": pin_a}
        await _rearmed(stack, b, pins, None)  # premise: the newest 32 events no longer introduce the pinned key
        unproved = b.transport.chain_seam.held("node-a")
        await _rearmed(stack, b, pins, functools.partial(stored_key_history, b.registry))
        joined = b.transport.chain_seam.held("node-a")
        sent = FederationMessage(type="ping", source_node="node-a", payload={}, timestamp=2.0)
        await a.transport.send_to_peer("node-b", sent)

    head = 1 + MAX_KEY_EVENTS + 1
    assert ("ping", "node-a", "key history gap") in _rejections(caplog)
    assert resynced is True and held is not None and held.state.seq == head and held.events[0].payload["seq"] == head - MAX_KEY_EVENTS + 1
    assert unproved is None and joined == held
    assert b.dispatched[-1].message_id == sent.message_id


async def test_s2b_m3_after_identity_db_moved_and_the_hold_did_not_the_next_resync_converges(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_IDENTITY_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, private, public, b, _, exchange_b, _, _ = await _fork_pair(stack, wire, tmp_path)
        x = await _held_on_copy(wire, a, b, exchange_b, tmp_path, public, stack)
        x_events = await _history(x)
        await _recover(a.binding, private)
        a_chain = await a.registry.export_chain()
        did = (await a.binding.status())["did"]
        moved = await b.registry.import_chain(a_chain, supersede=True)  # identity.db first, as a stop after its commit leaves it
        held = b.transport.chain_seam.held("node-a")
        resynced = await exchange_b.resync("node-a")
        after = b.transport.chain_seam.held("node-a")

    assert moved[0] is True and held is not None and held.events == x_events  # the hold had not moved
    assert resynced is True and after is not None and after.events == chain_key_history(a_chain)
    assert b.registry.get_foreign_chain(did) == a_chain and len(_replacements(caplog)) == 1  # identity.db kept what it held


# --------------------------------------------------------------------------- #
# a1 -- Amendment A-1 (review round 1)
# --------------------------------------------------------------------------- #

from probos.identity_keys import EVENT_ROTATION, KeyEventInvalid, derive_key_state  # noqa: E402
from tests.test_ad1197_signed_envelopes import _MemoryStore  # noqa: E402

_TURNS = 5  # turns of the event loop that deliver a requested cancellation to its task


class _CommitGate:
    """A sqlite3 trace callback that holds the next ``COMMIT`` of its connection where the statement begins.

    aiosqlite runs every statement on its worker thread, and the trace callback runs there as the statement begins, so
    blocking in it holds the real COMMIT before SQLite performs it; ``release`` lets it commit.
    """

    def __init__(self) -> None:
        self.armed = False
        self.inside = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, statement: str) -> None:
        if self.armed and statement.strip().upper() == "COMMIT":
            self.armed = False
            self.inside = True
            self.entered.set()
            try:
                self.release.wait(30)
            finally:
                self.inside = False


class _Connections:
    """A connection factory over the default one that keeps the connection it opened for each path."""

    def __init__(self) -> None:
        self.opened: dict[str, Any] = {}

    async def connect(self, db_path: str) -> Any:
        from probos.storage.sqlite_factory import default_factory

        connection = await default_factory.connect(db_path)
        self.opened[str(db_path)] = connection
        return connection


async def _gated(connections: _Connections, path: Path) -> _CommitGate:
    gate = _CommitGate()
    await connections.opened[str(path)].set_trace_callback(gate)
    gate.armed = True
    return gate


async def _cancel_at_commit(gate: _CommitGate, pending: asyncio.Task[Any]) -> bool:
    """Cancel ``pending`` while ``gate`` holds its write's COMMIT, let the COMMIT run, and wait for ``pending`` to end.

    Returns whether ``pending`` was still waiting once the cancellation had reached it, the COMMIT still held.
    """
    try:
        await _until(gate.entered.is_set, what="the write's COMMIT")
        assert gate.inside and not pending.done() and pending.cancel(), "premise: cancelled once its COMMIT has begun"
        for _ in range(_TURNS):
            await asyncio.sleep(0)
        assert gate.inside, "premise: the cancellation was delivered while the COMMIT was held"
        waiting = not pending.done()
    finally:
        gate.release.set()
    await asyncio.wait({pending})
    return waiting


async def test_s2b_a1_a_cancellation_while_the_re_anchor_commits_holds_what_committed_and_propagates(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    connections = _Connections()
    async with contextlib.AsyncExitStack() as stack:
        a, private, public = await _owner(stack, _Wire(), tmp_path)
        _, pin = await _active_key(a.binding)
        store = functools.partial(EnvelopeStore, connection_factory=connections)
        guard, path = await _guard(stack, tmp_path, {"node-a": pin}, store=store)
        assert await guard.admit(await _seal(a, "node-b"))
        x = await _copy(stack, a, tmp_path, public, "x")
        x.guard = await _resealed(stack, x, tmp_path / "node-a-x-data" / ENVELOPE_DB_NAME, times=2)  # a later send epoch than node-a's
        await _deliver(guard, x, 1)
        assert await guard.admit(await _seal(x, BROADCAST, kind="gossip_self_model", payload=dict(_GOSSIP)))  # a broadcast window too
        await _recover(a.binding, private)
        answer = await _answer(a, "node-b")
        history = chain_key_history(answer.payload["blocks"])
        gate = await _gated(connections, path)
        pending = asyncio.create_task(guard.resync(answer, history))
        waited = await _cancel_at_commit(gate, pending)
        senders, windows = _store_rows(path)
        held = guard.held("node-a")
        served = await guard.admit(await _seal(a, "node-b"))
        broadcast = await guard.admit(await _seal(a, BROADCAST, kind="gossip_self_model", payload=dict(_GOSSIP)))
        await x.binding.rotate()
        copied = await guard.admit(await _seal(x, "node-b"))
        await guard.stop()
        restarted, _ = await _guard(stack, tmp_path, {"node-a": pin}, label="restarted", path=path)
        kept = restarted.held("node-a")

    assert senders[0][2:4] == (1, history[-1].digest)  # premise: the COMMIT ran -- the store holds the recovery branch
    assert waited and pending.cancelled()  # the resync waited for its write, then the cancellation propagated
    assert held is not None and held.events == history and held.state.seq == 1  # the guard holds what committed
    assert windows == [("node-a", "direct", 1, answer.auth["epoch"], answer.auth["seq"], "0000000000000001")]
    assert (served, broadcast, copied) == (True, True, False)  # the replaced branch is refused, its windows forgotten
    assert kept == held  # a restart holds the recovery branch, as the guard did
    assert len(_reanchored(caplog)) == 1


@pytest.mark.parametrize("grows", [True, False], ids=["the-hold-grows", "the-window-only"])
async def test_s2b_a1_a_cancellation_while_an_admission_commits_holds_what_committed_and_propagates(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, grows: bool,
) -> None:
    """The forward path (AD-1197): an ordinary admission cancelled while its record commits."""
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    connections = _Connections()
    async with contextlib.AsyncExitStack() as stack:
        a, _, _ = await _owner(stack, _Wire(), tmp_path)
        _, pin = await _active_key(a.binding)
        guard, path = await _guard(stack, tmp_path, {"node-a": pin}, store=functools.partial(EnvelopeStore, connection_factory=connections))
        assert await guard.admit(await _seal(a, "node-b"))
        if grows:
            await a.binding.rotate()
        envelope = await _seal(a, "node-b")
        gate = await _gated(connections, path)
        pending = asyncio.create_task(guard.admit(envelope))
        waited = await _cancel_at_commit(gate, pending)
        senders, windows = _store_rows(path)
        held = guard.held("node-a")
        replayed = await guard.admit(envelope)
        following = await guard.admit(await _seal(a, "node-b"))

    seq = 1 if grows else 0
    assert senders[0][2] == seq and windows[0][:5] == ("node-a", "direct", seq, envelope.auth["epoch"], envelope.auth["seq"])  # premise: the COMMIT ran
    assert waited and pending.cancelled()  # the admission waited for its write, then the cancellation propagated
    assert held is not None and (held.state.seq, held.state.head_digest) == (seq, senders[0][3])  # the guard holds what committed
    assert replayed is False and _rejections(caplog)[-1][-1] == "duplicate"  # an envelope is never delivered twice
    assert following is True


async def test_s2b_a1_a_cancellation_in_before_record_leaves_identity_db_ahead_and_the_next_resync_converges(
    tmp_path: Path,
) -> None:
    async with contextlib.AsyncExitStack() as stack:
        a, private, x, guard, path = await _scene(stack, tmp_path)
        await _deliver(guard, x, 1)
        registry, _ = await stack.enter_async_context(_armed(tmp_path / "r-identity", _DuckKeyring(), instance_id="ship-r"))
        assert (await registry.import_chain(await x.registry.export_chain()))[0], "premise: identity.db stores the held branch"
        await _recover(a.binding, private)
        answer = await _answer(a, "node-b")
        a_chain = answer.payload["blocks"]
        history = chain_key_history(a_chain)
        did = (await a.binding.status())["did"]
        held, rows = guard.held("node-a"), _store_rows(path)
        imported = asyncio.Event()

        async def identity_db_first() -> str | None:
            ok, why = await registry.import_chain(a_chain, supersede=True)
            imported.set()
            await asyncio.Event().wait()  # the cancellation lands here: identity.db has committed, the hold has not
            return None if ok else why

        async def identity_db() -> str | None:
            ok, why = await registry.import_chain(a_chain, supersede=True)
            return None if ok else why

        pending = asyncio.create_task(guard.resync(answer, history, identity_db_first))
        await _until(imported.is_set, what="identity.db's import")
        pending.cancel()
        await asyncio.wait({pending})
        ahead = registry.get_foreign_chain(did) == a_chain
        unchanged = guard.held("node-a") == held and _store_rows(path) == rows
        converged = await guard.resync(answer, history, identity_db)
        after = guard.held("node-a")

    assert pending.cancelled() and ahead and unchanged  # identity.db first, the permitted direction; the hold untouched
    assert converged is True and after is not None and after.events == history  # the next resync converges
    assert registry.get_foreign_chain(did) == a_chain


async def test_s2b_a1_a_store_write_that_ends_cancelled_itself_holds_nothing_and_propagates(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        a, private, public = await _owner(stack, _Wire(), tmp_path)
        _, pin = await _active_key(a.binding)
        guard, path = await _guard(stack, tmp_path, {"node-a": pin}, store=_Store)
        assert await guard.admit(await _seal(a, "node-b"))
        x = await _copy(stack, a, tmp_path, public, "x")
        await _deliver(guard, x, 1)
        await _recover(a.binding, private)
        held, rows = guard.held("node-a"), _store_rows(path)
        answer = await _answer(a, "node-b")
        vars(guard)["_store"].cancel_reanchor = True  # the write's own task ends cancelled, as the event loop's shutdown ends it
        with pytest.raises(asyncio.CancelledError):
            await guard.resync(answer, chain_key_history(answer.payload["blocks"]))
        unchanged = guard.held("node-a") == held and _store_rows(path) == rows

    assert unchanged  # nothing is held
    assert not [record for record in caplog.records if "not admitted for a resync" in str(record.msg)]  # never read as a refusal


async def test_s2b_a1_precedence_needs_the_whole_history_to_replay_from_the_shared_state(tmp_path: Path) -> None:
    async with contextlib.AsyncExitStack() as stack:
        s = await _shapes(stack, tmp_path)
    ahead = s.history["ahead"]  # the recovery at key seq 2, then two rotations

    def broken(seq: int) -> tuple[KeyEvent, ...]:
        """``ahead`` with the prior-key signature of its event at ``seq`` replaced by that event's own key's signature."""
        event = ahead[seq]
        return (*ahead[:seq], dataclasses.replace(event, signatures={**event.signatures, "prior": event.signatures["new"]}), *ahead[seq + 1:])

    assert [event.payload["event"] for event in ahead[2:]] == [EVENT_RECOVERY, EVENT_ROTATION, EVENT_ROTATION]  # premise
    assert recovery_precedence(s.held["x1"], ahead)[0] == 2  # premise: the untouched history takes precedence
    for seq in (3, 4):
        with pytest.raises(KeyEventInvalid):
            derive_key_state(broken(seq))  # premise: the history does not replay
    assert {seq: recovery_precedence(s.held["x1"], broken(seq)) for seq in (3, 4)} == {
        seq: (None, "the history does not replay") for seq in (3, 4)
    }


async def test_s2b_a1_without_peer_admission_only_a_key_history_gap_tells_the_listener_as_before_slice_2b(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        a, private, public = await _owner(stack, _Wire(), tmp_path)
        _, signer = await stack.enter_async_context(_armed(tmp_path / "holder-identity", _DuckKeyring(), instance_id="ship-b"))
        (tmp_path / "holder-data").mkdir()
        guard = EnvelopeGuard(  # no peer admission
            signer=signer, store=EnvelopeStore(tmp_path / "holder-data" / ENVELOPE_DB_NAME), local_node_id="node-b", policy=POLICY_REQUIRE,
        )
        stack.push_async_callback(guard.stop)
        await guard.start()
        told: list[str] = []
        guard.on_history_gap(told.append)
        assert await guard.admit(await _seal(a, "node-b"))
        x = await _copy(stack, a, tmp_path, public, "x")
        await _deliver(guard, x, 1)
        await _recover(a.binding, private)
        diverged = await guard.admit(await _seal(a, "node-b"))
        await _deliver(guard, x, 2)
        stale = await guard.admit(await _seal(a, "node-b"))
        told_on_divergence = list(told)
        for _ in range(MAX_KEY_EVENTS + 3):
            await a.binding.rotate()
        gapped = await guard.admit(await _seal(a, "node-b"))

    assert (diverged, stale, gapped) == (False, False, False)
    assert [reason for *_, reason in _rejections(caplog)] == ["held history", "stale key", "key history gap"]
    assert told_on_divergence == [] and told == ["node-a"]  # as before slice 2b: the gap tells it, the divergence does not


async def test_s2b_a1_the_in_memory_store_double_refuses_a_re_anchor_as_an_empty_envelope_store_does(tmp_path: Path) -> None:
    moved, window, ids = StoredSender("did:probos:ship-a", 2, "b" * 64, "[]"), StoredWindow(2, 7, 1, 1), frozenset({"k0"})
    store = EnvelopeStore(tmp_path / ENVELOPE_DB_NAME)
    await store.start()
    try:
        with pytest.raises(EnvelopeStateConflict) as real:
            await store.reanchor("node-a", "direct", moved, window, ids)
    finally:
        await store.stop()
    with pytest.raises(EnvelopeStateConflict) as double:
        await _MemoryStore().reanchor("node-a", "direct", moved, window, ids)

    assert str(double.value) == str(real.value) == "no key history is held for 'node-a'"


# --------------------------------------------------------------------------- #
# a2 -- Amendment A-2 (review round 2)
# --------------------------------------------------------------------------- #

import probos.federation.envelope as envelope_module  # noqa: E402
from probos.federation.envelope import STORE_WRITE_SETTLE_S  # noqa: E402
from probos.startup.shutdown import shutdown  # noqa: E402
from tests.fixtures.runtime_lifecycle import BareRuntime  # noqa: E402

_UNSETTLED = "store write unsettled"
_A_SECOND_S = 1.0  # contract A-2's decision: a store write may wait out the store's whole busy timeout, and one second more
# Contract A-3: a timing test measures from the moment its write began (``_Begun``), which is where the guard's bound
# starts, and allows for a loaded host. A COMMIT meant to end inside the bound is released well inside it; a wait meant to
# end at the bound may end a clock tick before it, and as late after it as a busy event loop or worker thread can delay
# it. Each stall a test makes outlasts that slack, so code without the bound still fails, and the decision test pins the
# bound's value exactly.
_HEADROOM_S = 0.75  # how far inside the bound a test lets a held COMMIT end: 0.25 s after the store's busy timeout
_EARLY_S = 0.1  # how early a wait at the bound may end: the loop may run a timer up to one clock tick (15.6 ms on Windows) early
_LATE_S = 2.0  # how late a wait at the bound may end on a loaded host
_SAFETY_S = 5.0  # a stall a test makes in Python ends by itself then, so that code without the bound fails rather than hangs


async def _bound_s(connection: Any) -> float:
    """The bound contract A-2 decided, read off the store's own connection: its busy timeout and one second more."""
    async with connection.execute("PRAGMA busy_timeout") as cursor:
        (busy_ms,) = await cursor.fetchone()
    assert busy_ms == 5_000, "premise: the store waits at most 5 s for a lock another connection holds"
    return busy_ms / 1_000 + _A_SECOND_S


def _unknown(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [line for line in _messages(caplog, _ENVELOPE_LOGGER, logging.ERROR) if "whether it committed is unknown" in line]


def _late(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [line for line in _messages(caplog, _ENVELOPE_LOGGER, logging.WARNING) if "after the guard stopped waiting for it" in line]


class _StallingStore(EnvelopeStore):
    """An envelope store whose next ``record`` waits for ``release`` and then fails, and whose ``stop`` waits for
    ``closing`` and, once closed, raises ``close_failure`` (Amendment A-3): a stall in Python rather than in SQLite, for
    what follows the bound."""

    release: asyncio.Event | None = None
    closing: asyncio.Event | None = None
    close_failure: Exception | None = None

    async def record(self, *args: Any, **kwargs: Any) -> None:
        release, self.release = self.release, None
        if release is not None:
            await release.wait()
            raise RuntimeError("the store is not writable")
        await super().record(*args, **kwargs)

    async def stop(self) -> None:
        closing, self.closing = self.closing, None
        failure, self.close_failure = self.close_failure, None
        if closing is not None:
            await closing.wait()
        await super().stop()
        if failure is not None:
            raise failure


class _Timed:
    """A runtime service whose ``stop`` is the wrapped one's, its end noted on the loop's clock under ``name``."""

    def __init__(self, inner: Any, ended: dict[str, float], name: str) -> None:
        self.inner, self.ended, self.name = inner, ended, name

    async def stop(self) -> None:
        await self.inner.stop()
        self.ended[self.name] = asyncio.get_running_loop().time()


class _Begun:
    """When each call of a store's write method ``method`` began, on the loop's clock (contract A-3). The guard runs the
    write in a task of its own and starts its bound in the next task, in the same turn of the event loop, so the moment
    a write begins is where its bound starts, never after it."""

    def __init__(self, store: Any, method: str) -> None:
        self.at: list[float] = []
        write = getattr(store, method)

        async def begun(*args: Any, **kwargs: Any) -> None:
            self.at.append(asyncio.get_running_loop().time())
            await write(*args, **kwargs)

        setattr(store, method, begun)


async def test_s2b_a2_the_bound_lets_a_store_write_wait_out_the_busy_timeout_and_one_second_more(tmp_path: Path) -> None:
    connections = _Connections()
    store = EnvelopeStore(tmp_path / ENVELOPE_DB_NAME, connection_factory=connections)
    await store.start()
    try:
        bound = await _bound_s(connections.opened[str(tmp_path / ENVELOPE_DB_NAME)])
    finally:
        await store.stop()

    assert STORE_WRITE_SETTLE_S == bound  # the decision, stated against the store's own busy timeout


async def test_s2b_a2_a_write_that_ends_just_inside_the_bound_is_held_and_its_cancellation_raised(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    connections = _Connections()
    loop = asyncio.get_running_loop()
    async with contextlib.AsyncExitStack() as stack:
        a, _, _ = await _owner(stack, _Wire(), tmp_path)
        _, pin = await _active_key(a.binding)
        guard, path = await _guard(stack, tmp_path, {"node-a": pin}, store=functools.partial(EnvelopeStore, connection_factory=connections))
        assert await guard.admit(await _seal(a, "node-b"))
        bound = await _bound_s(connections.opened[str(path)])
        await a.binding.rotate()
        grown = await _seal(a, "node-b")
        gate = await _gated(connections, path)
        begun = _Begun(vars(guard)["_store"], "record")
        pending = asyncio.create_task(guard.admit(grown))
        try:
            await _until(gate.entered.is_set, what="the write's COMMIT")
            (began,) = begun.at  # premise: one write began, and with it the bound
            assert pending.cancel(), "premise: cancelled once its COMMIT has begun"
            await asyncio.sleep(began + bound - _HEADROOM_S - loop.time())
            released = loop.time() - began
            held_to_the_end = gate.inside  # premise: the COMMIT was held until then
            waiting = not pending.done()
        finally:
            gate.release.set()
        await asyncio.wait({pending})
        ended = loop.time() - began
        senders, _ = _store_rows(path)
        held = guard.held("node-a")
        following = await guard.admit(await _seal(a, "node-b"))

    assert held_to_the_end and released >= bound - _A_SECOND_S and senders[0][2] == 1  # premise: the COMMIT outlasted the busy timeout, then ran
    assert waiting and pending.cancelled() and ended < bound  # the caller waited for its write, then its cancellation propagated inside the bound: the headroom is the slack
    assert held is not None and (held.state.seq, held.state.head_digest) == (senders[0][2], senders[0][3])  # what committed is held
    assert following is True and _unknown(caplog) == []  # nothing was left unsettled


async def test_s2b_a2_a_cancelled_admission_stops_waiting_at_the_bound_and_nothing_is_admitted_until_its_write_ends(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    connections = _Connections()
    loop = asyncio.get_running_loop()
    async with contextlib.AsyncExitStack() as stack:
        a, _, _ = await _owner(stack, _Wire(), tmp_path)
        c, _, _ = await _owner(stack, _Wire(), tmp_path, "node-c")
        _, pin_a = await _active_key(a.binding)
        _, pin_c = await _active_key(c.binding)
        guard, path = await _guard(
            stack, tmp_path, {"node-a": pin_a, "node-c": pin_c}, store=functools.partial(EnvelopeStore, connection_factory=connections),
        )
        assert await guard.admit(await _seal(a, "node-b")) and await guard.admit(await _seal(c, "node-b"))
        bound = await _bound_s(connections.opened[str(path)])
        await a.binding.rotate()
        grown, other = await _seal(a, "node-b"), await _seal(c, "node-b")
        answer = await _answer(a, "node-b")
        asked: list[str] = []

        async def identity_db() -> str | None:
            asked.append("identity.db")
            return None

        gate = await _gated(connections, path)
        begun = _Begun(vars(guard)["_store"], "record")
        pending = asyncio.create_task(guard.admit(grown))
        try:
            await _until(gate.entered.is_set, what="the write's COMMIT")
            (began,) = begun.at  # premise: one write began, and with it the bound
            assert pending.cancel(), "premise: cancelled once its COMMIT has begun"
            await asyncio.wait({pending}, timeout=began + bound + _LATE_S - loop.time())
            stopped, ended = pending.done(), loop.time() - began
            refused = await asyncio.wait_for(guard.admit(other), _LATE_S)  # never queued behind the write: answered while its COMMIT is held
            resynced = await asyncio.wait_for(guard.resync(answer, chain_key_history(answer.payload["blocks"]), identity_db), _LATE_S)
            unknown = gate.inside  # premise: the COMMIT is still held, so the write's outcome is unknown
        finally:
            gate.release.set()
        await _until(lambda: _store_rows(path)[0][0][2] == 1, what="the held COMMIT to land")
        following = await guard.admit(await _seal(a, "node-b"))
        senders, _ = _store_rows(path)
        held = guard.held("node-a")
        replayed = await guard.admit(grown)

    assert unknown  # premise
    assert stopped and pending.cancelled() and ended >= bound - _EARLY_S  # the cancelled caller stops waiting at the bound: not before it, nor _LATE_S after it
    assert (refused, resynced, asked) == (False, False, [])  # nothing is admitted meanwhile, and identity.db is not asked
    assert [reason for *_, reason in _rejections(caplog)] == [_UNSETTLED, "duplicate"]
    assert len(_unknown(caplog)) == 1 and len(_late(caplog)) == 1  # logged once at the bound, and once when the write ended
    assert following is True  # once the write has ended admission resumes
    assert held is not None and (held.state.seq, held.state.head_digest) == (senders[0][2], senders[0][3])  # with what committed held
    assert replayed is False  # the envelope whose write committed late was not delivered, and is not delivered now


async def test_s2b_a2_shutdown_stops_the_exchange_and_the_guard_within_the_bound_while_a_re_anchor_commits(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    for name in (_ENVELOPE_LOGGER, _CONTINUITY_LOGGER, _IDENTITY_LOGGER):
        caplog.set_level(logging.INFO, logger=name)
    wire = _Wire()
    loop = asyncio.get_running_loop()
    ended: dict[str, float] = {}
    async with contextlib.AsyncExitStack() as stack:
        a, private, public, b, pin_a, exchange_b, _, _ = await _fork_pair(stack, wire, tmp_path)
        await _held_on_copy(wire, a, b, exchange_b, tmp_path, public, stack)
        await _recover(a.binding, private)
        a_chain = await a.registry.export_chain()
        did = (await a.binding.status())["did"]
        store = vars(vars(b.transport)["_guard"])["_store"]
        connection = vars(store)["_db"]
        bound = await _bound_s(connection)
        gate = _CommitGate()
        await connection.set_trace_callback(gate)
        gate.armed = True
        begun = _Begun(store, "reanchor")
        runtime = BareRuntime(tmp_path / "runtime-data")
        runtime.federation_identity_exchange = _Timed(exchange_b, ended, "exchange")
        runtime._federation_transport = _Timed(b.transport, ended, "transport")
        exchange_b.history_gap("node-a")  # slice 2b's automatic resync: identity.db first, then the re-anchor
        try:
            await _until(gate.entered.is_set, what="the re-anchor's COMMIT")
            (began,) = begun.at  # premise: one re-anchor began, and with it the bound
            stopping = asyncio.create_task(shutdown(runtime, reason="test"))  # type: ignore[arg-type]
            await asyncio.wait({stopping}, timeout=began + bound + _LATE_S - loop.time())
            in_time = stopping.done()
            unknown = gate.inside  # premise: the COMMIT is still held, so the re-anchor's outcome is unknown
        finally:
            gate.release.set()
        await asyncio.wait({stopping})
        await _rearmed(stack, b, {"node-a": pin_a}, functools.partial(stored_key_history, b.registry))
        restarted = b.transport.chain_seam.held("node-a")

    assert unknown  # premise
    assert in_time and stopping.exception() is None  # shutdown completes while the COMMIT is still held, within _LATE_S of the bound:
    assert ended["exchange"] - began >= bound - _EARLY_S  # IdentityExchange.stop() returns at the bound, not before it,
    assert ended["transport"] - began <= bound + _LATE_S  # and the guard's stop does not wait behind the write
    assert len(_unknown(caplog)) == 1
    assert restarted is not None and restarted.events == chain_key_history(a_chain)  # a restart holds what committed
    assert b.registry.get_foreign_chain(did) == a_chain  # identity.db first, as Amendment A-1 orders it


async def test_s2b_a2_after_a_store_write_that_ended_cancelled_nothing_is_admitted_until_a_restart(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        a, private, public = await _owner(stack, _Wire(), tmp_path)
        _, pin = await _active_key(a.binding)
        guard, path = await _guard(stack, tmp_path, {"node-a": pin}, store=_Store)
        assert await guard.admit(await _seal(a, "node-b"))
        x = await _copy(stack, a, tmp_path, public, "x")
        await _deliver(guard, x, 1)
        await _recover(a.binding, private)
        answer = await _answer(a, "node-b")
        history = chain_key_history(answer.payload["blocks"])
        vars(guard)["_store"].cancel_reanchor = True  # the write's own task ends cancelled: whether it committed is unknown to the guard
        with pytest.raises(asyncio.CancelledError):
            await guard.resync(answer, history)
        vars(guard)["_store"].cancel_reanchor = False
        refused = await guard.admit(await _seal(x, "node-b"))
        retried = await guard.resync(answer, history)
        await guard.stop()
        restarted, _ = await _guard(stack, tmp_path, {"node-a": pin}, label="restarted", path=path)
        readmitted = await restarted.admit(await _seal(x, "node-b"))

    assert (refused, retried, readmitted) == (False, False, True)  # nothing is admitted until a restart reads the store
    assert [reason for *_, reason in _rejections(caplog)] == [_UNSETTLED]
    assert _unknown(caplog) == [
        "AD-1198: the envelope store's write for 'node-a' ended cancelled; whether it committed is unknown, so no "
        "envelope is admitted until a restart reads the store",
    ]


async def test_s2b_a2_an_admission_whose_write_outlasts_the_bound_is_refused_and_a_write_that_then_fails_holds_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    monkeypatch.setattr(envelope_module, "STORE_WRITE_SETTLE_S", 0.2)  # the bound's value is proven above; this is what follows it
    async with contextlib.AsyncExitStack() as stack:
        a, _, _ = await _owner(stack, _Wire(), tmp_path)
        _, pin = await _active_key(a.binding)
        guard, path = await _guard(stack, tmp_path, {"node-a": pin}, store=_StallingStore)
        assert await guard.admit(await _seal(a, "node-b"))
        held, (senders, _) = guard.held("node-a"), _store_rows(path)
        release = vars(guard)["_store"].release = asyncio.Event()
        safety = asyncio.get_running_loop().call_later(_SAFETY_S, release.set)  # without the bound this fails, never hangs
        try:
            stalled = await guard.admit(await _seal(a, "node-b"))  # not cancelled: refused once the bound has passed
            meanwhile = await guard.admit(await _seal(a, "node-b"))
        finally:
            release.set()
            safety.cancel()
        for _ in range(_TURNS):
            await asyncio.sleep(0)  # the released write fails
        following = await guard.admit(await _seal(a, "node-b"))
        after, (senders_after, _) = guard.held("node-a"), _store_rows(path)

    assert (stalled, meanwhile, following) == (False, False, True)
    assert [reason for *_, reason in _rejections(caplog)] == [_UNSETTLED, _UNSETTLED]
    assert _late(caplog) == [
        "AD-1198: the envelope store's write for 'node-a' has ended (not recorded: RuntimeError) after the guard stopped "
        "waiting for it; nothing of it is held, and envelopes are admitted again",
    ]
    assert after == held and senders_after == senders  # the failed write recorded nothing, and nothing of it is held


async def test_s2b_a2_the_guard_waits_for_its_stores_close_at_most_the_bound(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    monkeypatch.setattr(envelope_module, "STORE_WRITE_SETTLE_S", 0.2)  # the bound's value is proven above; this is what follows it
    loop = asyncio.get_running_loop()
    async with contextlib.AsyncExitStack() as stack:
        a, _, _ = await _owner(stack, _Wire(), tmp_path)
        _, pin = await _active_key(a.binding)
        guard, _ = await _guard(stack, tmp_path, {"node-a": pin}, store=_StallingStore)
        closing = vars(guard)["_store"].closing = asyncio.Event()
        safety = loop.call_later(_SAFETY_S, closing.set)  # without the bound this fails, never hangs
        began = loop.time()
        try:
            await asyncio.wait_for(guard.stop(), 0.2 + _LATE_S)
            stopped = loop.time() - began
            (closed,) = vars(guard)["_closing"]  # premise: the close had not ended when the guard stopped, and the guard owns it
        finally:
            closing.set()
            safety.cancel()
        await asyncio.wait({closed})
        admitted = await guard.admit(await _seal(a, "node-b"))

    assert stopped <= 0.2 + _LATE_S  # the guard stopped without waiting past the bound for its store's close
    assert closed.exception() is None and vars(guard)["_closing"] == set()  # the close it owned ended once its store let it
    assert admitted is False and guard.accepts_traffic is False
    assert (
        "AD-1198: the federation envelope store has not closed within 0.2 s; the guard is stopped, and the store closes "
        "once the statement ahead of its close ends"
    ) in _messages(caplog, _ENVELOPE_LOGGER, logging.WARNING)


# --------------------------------------------------------------------------- #
# a3 -- Amendment A-3 (review round 3)
# --------------------------------------------------------------------------- #

import gc  # noqa: E402

_LOOP_LOGGER = "asyncio"
_NOT_CLOSED = (
    "AD-1198: the federation envelope store has not closed within 0.2 s; the guard is stopped, and the store closes "
    "once the statement ahead of its close ends"
)
_LEFT_FAILED = (
    "AD-1198: the federation envelope store's close, left running when the guard's stop ended, failed (RuntimeError); "
    "the store may not have closed cleanly, nothing retries the close, and the next start opens the store as it stands"
)


def _loop_errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    """What asyncio itself reported: a task exception never retrieved, or an exception raised in a callback."""
    return [record.getMessage() for record in caplog.records if record.name == _LOOP_LOGGER and record.levelno >= logging.ERROR]


@pytest.mark.parametrize(("ending", "reported"), [("fails", [_LEFT_FAILED]), ("is-cancelled", [])], ids=["fails", "is-cancelled"])
async def test_s2b_a3_a_close_left_running_at_the_bound_is_read_once_it_ends_and_reported_once_if_it_failed(
    ending: str, reported: list[str], tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.ERROR, logger=_LOOP_LOGGER)  # first: the capture handler keeps the level set last
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    gc.collect()  # what an earlier test left for the collector is reported now, before this test's window opens
    caplog.clear()
    monkeypatch.setattr(envelope_module, "STORE_WRITE_SETTLE_S", 0.2)  # the bound's value is proven above; this is what follows it
    loop = asyncio.get_running_loop()
    async with contextlib.AsyncExitStack() as stack:
        guard, _ = await _guard(stack, tmp_path, {}, store=_StallingStore)
        store = vars(guard)["_store"]
        closing = store.closing = asyncio.Event()
        store.close_failure = RuntimeError("the store did not close")
        safety = loop.call_later(_SAFETY_S, closing.set)  # without the bound this fails, never hangs
        try:
            await asyncio.wait_for(guard.stop(), 0.2 + _LATE_S)
            (closed,) = vars(guard)["_closing"]
            left = not closed.done()  # premise: the stop ended with its store's close still running, owned by the guard
            if ending == "fails":
                closing.set()  # the store closes, then raises
            else:
                closed.cancel()
            await asyncio.wait({closed})  # waits for the close without reading its outcome
        finally:
            closing.set()
            safety.cancel()
        for _ in range(_TURNS):
            await asyncio.sleep(0)  # the close's done callbacks run
        ended_as = "is-cancelled" if closed.cancelled() else "fails"
        owned = set(vars(guard)["_closing"])
        del closed
        gc.collect()  # asyncio reports a task exception nobody read once the task is collected
        warnings, errors = _messages(caplog, _ENVELOPE_LOGGER, logging.WARNING), _loop_errors(caplog)

    assert left and ended_as == ending  # premise
    assert owned == set()  # the guard let the close go once it had ended
    assert warnings == [_NOT_CLOSED, *reported]  # a failure is reported once, a cancelled close not at all, and the warning of a close that fails at once is not added
    assert errors == []  # the close's outcome was read: nothing is left for asyncio to report


async def test_s2b_a3_a_close_left_running_by_a_cancelled_stop_is_read_once_it_ends_and_its_failure_reported_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger=_LOOP_LOGGER)  # first: the capture handler keeps the level set last
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    gc.collect()  # what an earlier test left for the collector is reported now, before this test's window opens
    caplog.clear()
    loop = asyncio.get_running_loop()
    async with contextlib.AsyncExitStack() as stack:
        guard, _ = await _guard(stack, tmp_path, {}, store=_StallingStore)
        store = vars(guard)["_store"]
        closing = store.closing = asyncio.Event()
        store.close_failure = RuntimeError("the store did not close")
        safety = loop.call_later(_SAFETY_S, closing.set)  # a stall the test makes ends by itself, never hangs
        stopping = asyncio.create_task(guard.stop())
        try:
            await _until(lambda: bool(vars(guard)["_closing"]), what="the guard's close of its store")
            (closed,) = vars(guard)["_closing"]
            for _ in range(_TURNS):
                await asyncio.sleep(0)  # the stop is waiting for the close
            assert stopping.cancel(), "premise: the stop is still waiting for its store's close"
            await asyncio.wait({stopping})
            left = not closed.done()  # premise: the cancelled stop left its store's close running
            closing.set()  # the store closes, then raises
            await asyncio.wait({closed})  # waits for the close without reading its outcome
        finally:
            closing.set()
            safety.cancel()
        for _ in range(_TURNS):
            await asyncio.sleep(0)  # the close's done callbacks run
        propagated = stopping.cancelled()
        owned = set(vars(guard)["_closing"])
        del closed, stopping  # the stop's cancellation holds the frame that held the close; neither is referenced now
        gc.collect()  # asyncio reports a task exception nobody read once the task is collected
        warnings, errors = _messages(caplog, _ENVELOPE_LOGGER, logging.WARNING), _loop_errors(caplog)

    assert left  # premise
    assert propagated  # the stop's cancellation is raised, never swallowed
    assert warnings == [_LEFT_FAILED] and errors == []  # the failure is reported once, and nothing is left for asyncio to report
    assert owned == set()  # the guard let the close go once it had ended
