"""AD-1198 slice 2c (#1135): the operator-only audited reset of one configured peer's held key history.

``POST /api/identity/peers/{node_id}/reset`` (crew scope; 503 while peer admission is unarmed, then 403
``identity_keys_require_token`` while no crew-scope token is configured, before any hold, store or registry is read; the
confirm literal ``forget-held-key-history``; audited as ``identity_peer_reset``) asks the armed identity exchange to
forget the peer's held key history: identity.db's chain for the held DID first (``AgentIdentityRegistry
.forget_foreign_chain``), under identity.db's lock until the hold's write has ended, then -- in one envelope-store
transaction -- the hold, every key id recorded for it and its replay windows (``EnvelopeStore.forget`` through
``EnvelopeGuard.forget``, settled as every store write of the guard is). The peer's next envelope is a first contact under
its current pin; foreign birth and transfer certificates are kept.

M0 pins today's premise on the unmodified base: a held peer that re-incepts is refused by the envelope hold and by
identity.db, and a restart forgets neither. M1 tests the store, the registry and the guard; M2 the exchange, its ordering
against chain imports and resyncs, and the route over ASGI in the test's own loop (never ``TestClient``); M3 each residual
a reset closes. Every test runs in process over real AD-1196 keys (the duck keyring), real envelope stores and
registries and the mock bus. No test reaches the real OS keyring (AD-1196's autouse guard is imported, H5) or opens a
socket.

Amendment A-1 (review round 1) adds the a1 group: identity.db's deletion in a transaction of its own, which waits for a
local key event's commit and never commits or rolls back any of it, even when it fails or is cancelled; a chain judged
before a reset refused once a first contact holds another branch; no chain imported while a reset's write is unsettled,
and a retry that converges; and the audit run inside the reset's write once it has committed -- once, with its note,
for a cancelled request and a commit after the bound -- whose failure leaves the reset standing.

Amendment A-2 (review round 2) holds the module's concurrent tests to one discipline: a test that creates a task, or
holds a gate, a lock, a transaction or a paused import, releases what it holds in ``finally``, ends each task it created
before its resources are torn down -- cancelling one that does not end once let go -- reads each task's outcome, so
that an exception it raised fails the test, and asserts that each bounded wait completed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest

from probos.types import IntentMessage
from tests.test_ad1196_did_key_binding import _armed, _birth, _DuckKeyring
from tests.test_ad1196_did_key_binding import _no_real_os_keyring  # noqa: F401 -- the autouse guard (H5)
from tests.test_ad1197_signed_envelopes import _ENVELOPE_LOGGER, _active_key, _node, _rejections, _unsigned, _Wire
from tests.test_ad1198_fork_resolution import _store_rows
from tests.test_ad1198_identity_continuity import _GAP, _exchange, _pinned_pair
from tests.test_ad1198_peer_admission import _admit


# --------------------------------------------------------------------------- #
# M0 -- today's code (passes on the unmodified base)
# --------------------------------------------------------------------------- #


async def test_s2c_m0_a_held_peer_that_re_incepts_is_refused_by_both_holds_and_a_restart_forgets_neither(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, _ = await _pinned_pair(stack, wire, tmp_path)
        exchange = _exchange(b, {"node-a": pin_a})
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))  # node-b holds node-a's inception
        a_did = (await a.binding.status())["did"]
        stored_before = await a.registry.export_chain()
        assert (await exchange.import_chain_from("node-a", stored_before))[0] is True  # and identity.db its chain
        await a.binding.reincept(reason="lost", compromised_after_index=None)
        reincepted = await a.registry.export_chain()

        await a.transport.send_to_peer("node-b", _unsigned("node-a"))
        imported = await b.registry.import_chain(reincepted)
        await _admit(stack, b, pins={"node-a": pin_a})  # node-b's seam restarts on the same stores
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))
        held = b.transport.chain_seam.held("node-a")

    assert [reason for _, source, reason in _rejections(caplog) if source == "node-a"] == ["held history"] * 2
    assert imported[0] is False and imported[1].startswith("Key history check failed: ")
    assert b.registry.get_foreign_chain(a_did) == stored_before
    assert held is not None and held.state.seq == 0


# --------------------------------------------------------------------------- #
# slice 2c names (M1 onward; omit this block and everything after it for the M0 run on the unmodified base)
# --------------------------------------------------------------------------- #

import json  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402

import probos.federation.envelope as envelope_module  # noqa: E402
from probos.config import AuthConfig, SystemConfig  # noqa: E402
from probos.federation.continuity import IdentityExchange, PeerReset, chain_key_history  # noqa: E402
from probos.federation_envelope_store import ENVELOPE_DB_NAME, EnvelopeStore, StoredSender, StoredWindow  # noqa: E402
from probos.identity import AgentIdentityRegistry  # noqa: E402
from probos.identity_keys import recovery_precedence  # noqa: E402
from probos.routers import identity as identity_routes  # noqa: E402
from probos.routers.deps import get_runtime  # noqa: E402
from probos.security.audit import AuditLog  # noqa: E402
from probos.storage.sqlite_factory import default_factory  # noqa: E402
from probos.types import FederationMessage  # noqa: E402
from tests.test_ad1197_signed_envelopes import _seal, _StartFailingFactory  # noqa: E402
from tests.test_ad1198_fork_resolution import _copy, _guard, _history, _scene  # noqa: E402
from tests.test_ad1198_identity_continuity import (  # noqa: E402
    _CONTINUITY_LOGGER,
    _diverged,
    _exchange_bridge,
    _messages,
    _RecordingIntentBus,
    _resync_refusals,
    _until,
)

_TOKEN = "ad1198-s2c-crew-scope-token"
_CONFIRM = "forget-held-key-history"
_AUDIT_CATEGORY = "identity_peer_reset"
_ROUTER_LOGGER = "probos.routers.identity"
_BOUND_S = 0.3  # a short store-write bound: these tests exercise the settlement, not its value (2b-i A-2 pins that)
_RESET = "/api/identity/peers/{}/reset"


def _holding(
    seen: list[str | None], *, entered: asyncio.Event | None = None, gate: asyncio.Event | None = None,
) -> Callable[[str | None], contextlib.AbstractAsyncContextManager[object]]:
    """The guard's ``holding`` argument as the exchange passes it: records the DID it is entered with; may pause there."""

    @contextlib.asynccontextmanager
    async def holding(did: str | None) -> AsyncIterator[None]:
        seen.append(did)
        if entered is not None:
            entered.set()
        if gate is not None:
            await gate.wait()
        yield

    return holding


async def _joined(*tasks: asyncio.Task[Any] | None) -> None:
    """A-2 (G5): ends every task a test created before the test's resources are torn down, and retrieves each outcome, so
    that none is left running and no exception is left unread. Each is given 5 s to end once what it waited on has been
    let go, and one still running is then cancelled and given 5 s more. On a test's normal path every task has ended,
    its result read by the test itself, and this only retrieves; ``None`` stands for a task the test had not created."""
    created = [task for task in tasks if task is not None]
    if not created:
        return
    await asyncio.wait(created, timeout=5)  # joined first: a task let go ends on its own, its work not cut short
    for task in created:
        if not task.done():
            task.cancel()
    await asyncio.wait(created, timeout=5)
    for task in created:
        assert task.done(), f"{task.get_coro()!r} has not ended 5 s after its cancellation"
        if not task.cancelled():
            task.exception()  # retrieved, so that its outcome is never left unread


class _GatedStore(EnvelopeStore):
    """An envelope store whose ``record`` or ``forget`` waits on a gate while one is set, as a stalled write does."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.gates: dict[str, asyncio.Event] = {}
        self.running = 0

    async def _through(self, name: str) -> None:
        gate = self.gates.get(name)
        if gate is not None:
            await gate.wait()

    async def record(self, *args: Any, **kwargs: Any) -> None:
        self.running += 1
        try:
            await self._through("record")
            await super().record(*args, **kwargs)
        finally:
            self.running -= 1

    async def forget(self, source: str) -> None:
        self.running += 1
        try:
            await self._through("forget")
            await super().forget(source)
        finally:
            self.running -= 1


class _CommitFailing:
    """Delegates to an aiosqlite connection; its next ``commit`` raises once ``fail_commit`` is set."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.fail_commit = False

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        return self._inner.execute(sql, parameters)

    async def commit(self) -> None:
        if self.fail_commit:
            self.fail_commit = False
            raise sqlite3.OperationalError("AD-1198 slice 2c test: injected commit failure")
        await self._inner.commit()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _CommitFailingFactory:
    def __init__(self) -> None:
        self.connection: _CommitFailing | None = None
        self.fail_next = False  # A-1: the next connection it opens fails its first commit

    async def connect(self, db_path: str) -> Any:
        self.connection = _CommitFailing(await default_factory.connect(db_path))
        self.connection.fail_commit, self.fail_next = self.fail_next, False
        return self.connection


def _identity_rows(db_path: Path) -> dict[str, list[tuple[Any, ...]]]:
    with contextlib.closing(sqlite3.connect(db_path)) as db:
        return {
            "chains": db.execute("SELECT origin_ship_did FROM foreign_chains ORDER BY origin_ship_did").fetchall(),
            "births": db.execute("SELECT did, origin_ship_did FROM foreign_birth_certificates ORDER BY did").fetchall(),
            "transfers": db.execute("SELECT did, direction FROM transfer_certificates ORDER BY did").fetchall(),
        }


async def _held_pair(
    stack: contextlib.AsyncExitStack, wire: _Wire, tmp: Path, *, extra_pins: dict[str, str] | None = None,
) -> tuple[Any, Any, str, IdentityExchange, str]:
    """Node-a and node-b pinned to each other, node-b holding node-a's inception and identity.db holding node-a's chain;
    node-b's identity exchange (pins ``node-a`` and ``extra_pins``) and node-a's DID."""
    a, b, pin_a, _ = await _pinned_pair(stack, wire, tmp)
    exchange = _exchange(b, {"node-a": pin_a, **(extra_pins or {})})
    stack.push_async_callback(exchange.stop)
    await a.transport.send_to_peer("node-b", _unsigned("node-a"))
    assert b.transport.chain_seam.held("node-a") is not None  # premise: node-b holds node-a
    assert (await exchange.import_chain_from("node-a", await a.registry.export_chain()))[0] is True  # and its chain
    return a, b, pin_a, exchange, (await a.binding.status())["did"]


async def _chain_answer(node: Any, chain: list[dict[str, Any]]) -> FederationMessage:
    """``node``'s chain answer to node-b, sealed by its armed seam's guard."""
    message = FederationMessage(
        type="chain_response", source_node=node.name, message_id="r1", payload={"blocks": chain}, timestamp=2.0,
    )
    sealed = await vars(node.transport)["_guard"].seal(message, "node-b")
    assert sealed is not None and sealed.auth is not None, "premise: the ship key signs"
    return sealed


# --------------------------------------------------------------------------- #
# M1 -- the envelope store, identity.db and the guard
# --------------------------------------------------------------------------- #


async def test_s2c_m1_store_forget_deletes_one_sources_hold_key_ids_and_windows_in_one_transaction(tmp_path: Path) -> None:
    path = tmp_path / ENVELOPE_DB_NAME
    store = EnvelopeStore(path)
    await store.start()
    try:
        epoch = await store.next_send_epoch()
        for source in ("node-a", "node-c"):
            sender = StoredSender(f"did:probos:{source}", 1, "a" * 64, "[]")
            await store.record(source, "direct", sender, StoredWindow(1, 1, 3, 0b101), frozenset({f"{source}#k0", f"{source}#k1"}))
            await store.record(source, "broadcast", None, StoredWindow(1, 1, 1, 1))
        before = _store_rows(path)
        await store.forget("node-a")
        await store.forget("node-z")  # nothing is held for it: nothing changes
        after = _store_rows(path)
        forgotten_ids = await store.key_ids("node-a")
        await store.record(  # a first hold again: back at key seq 0, with fewer key ids than were recorded
            "node-a", "direct", StoredSender("did:probos:node-a", 0, "b" * 64, "[]"), StoredWindow(0, 1, 1, 1),
            frozenset({"node-a#k9"}),
        )
        again = _store_rows(path)
        next_epoch = await store.next_send_epoch()
    finally:
        await store.stop()
    assert [row[0] for row in before[0]] == ["node-a", "node-c"] and len(before[1]) == 4  # premise
    assert after == ([row for row in before[0] if row[0] == "node-c"], [row for row in before[1] if row[0] == "node-c"])
    assert forgotten_ids == frozenset()
    assert again[0] == [("node-a", "did:probos:node-a", 0, "b" * 64, ["node-a#k9"]), before[0][1]]
    assert next_epoch == epoch + 1  # the send epoch is never forgotten


async def test_s2c_m1_store_forget_that_fails_rolls_back_and_keeps_the_hold(tmp_path: Path) -> None:
    path = tmp_path / ENVELOPE_DB_NAME
    store = EnvelopeStore(path, connection_factory=_StartFailingFactory("DELETE FROM envelope_windows"))
    await store.start()
    try:
        await store.next_send_epoch()
        await store.record(
            "node-a", "direct", StoredSender("did:probos:node-a", 1, "a" * 64, "[]"), StoredWindow(1, 1, 1, 1),
            frozenset({"k0"}),
        )
        before = _store_rows(path)
        with pytest.raises(sqlite3.OperationalError):
            await store.forget("node-a")  # its second statement fails: the first is rolled back with it
        await store.record(  # the next write commits, and nothing of the failed one with it
            "node-c", "direct", StoredSender("did:probos:node-c", 0, "c" * 64, "[]"), StoredWindow(0, 1, 1, 1),
            frozenset({"kc"}),
        )
        after = _store_rows(path)
    finally:
        await store.stop()
    assert [row for row in after[0] if row[0] == "node-a"] == before[0]
    assert [row for row in after[1] if row[0] == "node-a"] == before[1]


async def test_s2c_m1_registry_forgets_one_ships_chain_and_keeps_its_birth_and_transfer_certificates(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        c = await _node(stack, wire, tmp_path, "node-c")
        holder, _ = await stack.enter_async_context(_armed(tmp_path / "holder", _DuckKeyring(), instance_id="ship-b"))
        ship = holder.get_ship_certificate()
        assert ship is not None
        troi = await _birth(a.registry, "Troi", instance_id="ship-a")
        xfer = await a.registry.issue_transfer_certificate(troi.agent_uuid, ship.ship_did)
        a_chain, c_chain = await a.registry.export_chain(), await c.registry.export_chain()
        a_did, c_did = a_chain[0]["agent_did"], c_chain[0]["agent_did"]
        assert (await holder.import_chain(a_chain))[0] and (await holder.import_transfer_certificate(xfer))[0]
        assert (await holder.import_chain(c_chain))[0]
        before = _identity_rows(tmp_path / "holder" / "identity.db")

        lock = vars(holder)["_foreign_chain_lock"]  # an import holding identity.db's chain lock
        forgetting: asyncio.Task[int] | None = None
        try:
            async with lock:  # A-2: let go whatever happens while it is held
                forgetting = asyncio.create_task(holder.forget_foreign_chain(a_did))
                early, _ = await asyncio.wait({forgetting}, timeout=0.5)  # far longer than one DELETE and COMMIT take (milliseconds)
                ordered = not early and _identity_rows(tmp_path / "holder" / "identity.db")["chains"] == before["chains"]
            forgotten = await asyncio.wait_for(forgetting, 5)
        finally:
            await _joined(forgetting)
        again = await holder.forget_foreign_chain(a_did)
        after = _identity_rows(tmp_path / "holder" / "identity.db")
        kept = holder.get_by_uuid(troi.agent_uuid)
        transfers = await holder.get_transfer_certificates_for(troi.did)
        reimported = await holder.import_chain(a_chain)  # the next chain of that ship is imported as a first one

    assert ordered and (forgotten, again) == (len(a_chain), 0)
    assert holder.get_foreign_chain(c_did) == c_chain and before["chains"] == sorted([(a_did,), (c_did,)])
    assert after == {**before, "chains": [(c_did,)]}  # only that ship's chain; its birth and transfer rows are kept
    assert kept is not None and kept.did == troi.did and [row["direction"] for row in transfers] == ["incoming"]
    assert reimported == (True, f"Chain imported: {len(a_chain)} blocks from {a_did}")
    with pytest.raises(RuntimeError, match="not started"):
        await AgentIdentityRegistry(tmp_path / "cold").forget_foreign_chain(a_did)


async def test_s2c_m1_a_registry_deletion_that_fails_keeps_the_chain(tmp_path: Path) -> None:
    wire = _Wire()
    factory = _CommitFailingFactory()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        holder, _ = await stack.enter_async_context(
            _armed(tmp_path / "holder", _DuckKeyring(), instance_id="ship-b", connection_factory=factory),
        )
        chain = await a.registry.export_chain()
        a_did = chain[0]["agent_did"]
        assert (await holder.import_chain(chain))[0]
        factory.fail_next = True  # the deletion's own connection (A-1) fails its commit
        with pytest.raises(sqlite3.OperationalError):
            await holder.forget_foreign_chain(a_did)
        await _birth(holder, "Data", instance_id="ship-b")  # an unrelated write that commits, on the shared connection
        cached = holder.get_foreign_chain(a_did)
        rows = _identity_rows(tmp_path / "holder" / "identity.db")
    assert cached == chain  # the in-memory copy follows only a committed deletion
    assert rows["chains"] == [(a_did,)]  # the failed deletion was discarded with its connection, not left for a commit


async def test_s2c_m1_guard_forgets_a_held_source_in_memory_and_the_store_and_its_next_envelope_is_a_first_contact(
    tmp_path: Path,
) -> None:
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, _Wire(), tmp_path, "node-a")
        c = await _node(stack, _Wire(), tmp_path, "node-c")
        _, pin_a = await _active_key(a.binding)
        _, pin_c = await _active_key(c.binding)
        pins = {"node-a": pin_a, "node-c": pin_c, "node-q": ""}
        guard, path = await _guard(stack, tmp_path, pins)
        first = await _seal(a, "node-b")
        assert await guard.admit(first) and await guard.admit(await _seal(c, "node-b"))
        held_a, held_c = guard.held("node-a"), guard.held("node-c")
        assert held_a is not None and held_c is not None
        before = _store_rows(path)
        seen: list[str | None] = []

        forgotten = await guard.forget("node-a", _holding(seen))
        nothing = await guard.forget("node-q", _holding(seen))  # configured, never held
        between = (_store_rows(path), guard.held("node-a"))
        replayed = await guard.admit(first)  # its replay windows are forgotten too: an old envelope is a first contact (R-27)
        duplicate = await guard.admit(first)
        await a.binding.rotate()
        grown = await guard.admit(await _seal(a, "node-b"))
        await guard.stop()
        restarted, _ = await _guard(stack, tmp_path, pins, label="restarted", path=path)  # a restart after the reset

    assert (forgotten, nothing) == (None, None) and seen == [held_a.did, None]
    assert between[0] == ([row for row in before[0] if row[0] == "node-c"], [row for row in before[1] if row[0] == "node-c"])
    assert between[1] is None and guard.held("node-c") == held_c
    assert (replayed, duplicate, grown) == (True, False, True)
    held = restarted.held("node-a")
    assert held is not None and (held.did, held.state.seq) == (held_a.did, 1)
    assert restarted.held("node-c") is not None and restarted.held("node-q") is None


async def test_s2c_m1_guard_forgets_a_hold_refused_at_start_with_the_did_it_names(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, _Wire(), tmp_path, "node-a")
        c = await _node(stack, _Wire(), tmp_path, "node-c")
        _, pin_a = await _active_key(a.binding)
        _, pin_c = await _active_key(c.binding)
        guard, path = await _guard(stack, tmp_path, {"node-a": pin_a, "node-c": pin_c})
        assert await guard.admit(await _seal(a, "node-b")) and await guard.admit(await _seal(c, "node-b"))
        a_did, c_did = guard.held("node-a").did, guard.held("node-c").did  # type: ignore[union-attr]
        await guard.stop()
        await a.binding.rotate()
        _, pin_a1 = await _active_key(a.binding)  # node-a is re-pinned to its new key: its held run lacks it
        with contextlib.closing(sqlite3.connect(path)) as db, db:  # node-c's stored hold no longer replays
            db.execute("UPDATE envelope_senders SET key_head = ? WHERE source_node = 'node-c'", ("0" * 64,))
        restarted, _ = await _guard(stack, tmp_path, {"node-a": pin_a1, "node-c": pin_c}, label="repinned", path=path)
        refused = [await restarted.admit(await _seal(a, "node-b")), await restarted.admit(await _seal(c, "node-b"))]
        seen: list[str | None] = []

        forgotten = [await restarted.forget("node-a", _holding(seen)), await restarted.forget("node-c", _holding(seen))]
        admitted = [await restarted.admit(await _seal(a, "node-b")), await restarted.admit(await _seal(c, "node-b"))]
        held_a = restarted.held("node-a")

    assert refused == [False, False] and [reason for *_, reason in _rejections(caplog)][-2:] == ["held history"] * 2
    assert forgotten == [None, None] and seen == [a_did, c_did]  # each refused hold's own DID
    assert admitted == [True, True] and held_a is not None and held_a.state.seq == 1


async def test_s2c_m1_guard_forgets_nothing_without_peer_admission_or_once_stopped(tmp_path: Path) -> None:
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, _Wire(), tmp_path, "node-a")
        _, pin_a = await _active_key(a.binding)
        guard, path = await _guard(stack, tmp_path, {"node-a": pin_a})
        assert await guard.admit(await _seal(a, "node-b"))
        before = _store_rows(path)
        seen: list[str | None] = []

        unadmitted = await a.guard.forget("node-b", _holding(seen))  # an AD-1197 guard without peer admission
        await guard.stop()
        stopped = await guard.forget("node-a", _holding(seen))
        after = _store_rows(path)

    assert (unadmitted, stopped) == ("not armed", "not armed") and seen == []
    assert after == before


async def test_s2c_m1_guard_forget_is_refused_while_a_write_is_unsettled_and_its_own_write_keeps_the_bound(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    monkeypatch.setattr(envelope_module, "STORE_WRITE_SETTLE_S", _BOUND_S)
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, _Wire(), tmp_path, "node-a")
        c = await _node(stack, _Wire(), tmp_path, "node-c")
        _, pin_a = await _active_key(a.binding)
        _, pin_c = await _active_key(c.binding)
        guard, path = await _guard(stack, tmp_path, {"node-a": pin_a, "node-c": pin_c}, store=_GatedStore)
        store = vars(guard)["_store"]
        assert await guard.admit(await _seal(a, "node-b")) and await guard.admit(await _seal(c, "node-b"))
        a_did, c_did = guard.held("node-a").did, guard.held("node-c").did  # type: ignore[union-attr]
        seen: list[str | None] = []

        try:
            store.gates["record"] = asyncio.Event()
            stalled_admission = await guard.admit(await _seal(c, "node-b"))  # its write outlasts the bound: unsettled
            while_unsettled = await guard.forget("node-a", _holding(seen))
            store.gates.pop("record").set()
            await _until(lambda: store.running == 0, what="the stalled admission's write to end")
            after_it = await guard.forget("node-a", _holding(seen))  # the late write settles first, then the reset runs

            store.gates["forget"] = asyncio.Event()
            stalled_reset = await guard.forget("node-c", _holding(seen))  # its own write outlasts the bound
            held_meanwhile = guard.held("node-c")
            refused_meanwhile = await guard.admit(await _seal(a, "node-b"))
            store.gates.pop("forget").set()
            await _until(lambda: store.running == 0, what="the reset's write to end")
        finally:
            for gate in store.gates.values():  # A-2: a write stalled on a gate is never left stalled
                gate.set()
        admitted_after = await guard.admit(await _seal(a, "node-b"))  # settles the reset first: node-c is forgotten
        rows = _store_rows(path)

    assert (stalled_admission, while_unsettled, after_it) == (False, "store write unsettled", None)
    assert (stalled_reset, refused_meanwhile, admitted_after) == ("store write unsettled", False, True)
    assert seen == [a_did, c_did]  # identity.db is entered only by a reset that writes, and before its write
    assert held_meanwhile is not None and guard.held("node-c") is None and guard.held("node-a") is not None
    assert [row[0] for row in rows[0]] == ["node-a"]
    late = [line for line in _messages(caplog, _ENVELOPE_LOGGER, logging.WARNING) if "after the guard stopped waiting" in line]
    assert len(late) == 2  # the stalled admission's write and the reset's, each held once it ended


async def test_s2c_m1_a_cancelled_forget_holds_what_committed_and_one_cancelled_before_its_write_forgets_nothing(
    tmp_path: Path,
) -> None:
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, _Wire(), tmp_path, "node-a")
        _, pin_a = await _active_key(a.binding)
        guard, path = await _guard(stack, tmp_path, {"node-a": pin_a}, store=_GatedStore)
        store = vars(guard)["_store"]
        assert await guard.admit(await _seal(a, "node-b"))
        before = _store_rows(path)

        entered, never = asyncio.Event(), asyncio.Event()
        early = asyncio.create_task(guard.forget("node-a", _holding([], entered=entered, gate=never)))
        late: asyncio.Task[str | None] | None = None
        try:
            await asyncio.wait_for(entered.wait(), 5)  # inside identity.db's step, before the store's write
            early.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(early, 5)
            kept = (guard.held("node-a"), _store_rows(path))

            store.gates["forget"] = asyncio.Event()
            late = asyncio.create_task(guard.forget("node-a", _holding([])))
            await _until(lambda: store.running == 1, what="the reset's write to begin")
            late.cancel()
            for _ in range(5):
                await asyncio.sleep(0)
            waiting = not late.done()  # the cancellation is kept while the write runs
            store.gates.pop("forget").set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(late, 5)
            after = (guard.held("node-a"), _store_rows(path))
        finally:
            never.set()  # A-2: nothing is left paused or stalled, and both resets end here
            for gate in store.gates.values():
                gate.set()
            await _joined(early, late)

    assert kept[0] is not None and kept[1] == before
    assert waiting and after == (None, ([], []))  # what committed is held before the cancellation is raised


# --------------------------------------------------------------------------- #
# M2 -- the identity exchange and its ordering
# --------------------------------------------------------------------------- #


async def test_s2c_m2_reset_forgets_identity_dbs_chain_and_the_hold_and_keeps_the_certificates(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_CONTINUITY_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, _, exchange, a_did = await _held_pair(stack, wire, tmp_path)
        ship = b.registry.get_ship_certificate()
        assert ship is not None
        troi = await _birth(a.registry, "Troi", instance_id="ship-a")
        xfer = await a.registry.issue_transfer_certificate(troi.agent_uuid, ship.ship_did)
        chain = await a.registry.export_chain()
        assert (await exchange.import_chain_from("node-a", chain))[0] and (await exchange.import_transfer_from("node-a", xfer))[0]
        identity_db = tmp_path / "node-b-identity" / "identity.db"
        before = _identity_rows(identity_db)

        outcome = await exchange.reset("node-a")
        after = (_store_rows(b.store_path), _identity_rows(identity_db), b.registry.get_foreign_chain(a_did))
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))  # its next envelope: a first contact
        held = b.transport.chain_seam.held("node-a")
        reimported = await exchange.import_chain_from("node-a", await a.registry.export_chain())

    assert outcome == (None, PeerReset("node-a", True, a_did, 0, False, len(chain)))
    assert after[0] == ([], []) and after[1] == {**before, "chains": []} and after[2] is None  # births and transfers kept
    assert before["births"] == [(troi.did, a_did)] and before["transfers"] == [(troi.did, "incoming")]
    assert held is not None and held.state.seq == 0
    assert reimported == (True, f"Chain imported: {len(chain)} blocks from {a_did}")
    assert _messages(caplog, _CONTINUITY_LOGGER, logging.WARNING) == [
        f"AD-1198: reset the key history held for 'node-a' on the operator's request (DID {a_did}, key seq 0): its hold, "
        f"every key id recorded for it and its replay windows are forgotten, with identity.db's {len(chain)}-block chain "
        "for that DID; its next envelope is a first contact under its current pin",
    ]


async def test_s2c_m2_reset_refuses_an_unconfigured_peer_and_a_stopped_exchange_and_reports_a_peer_with_nothing_held(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_CONTINUITY_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        _, b, _, exchange, a_did = await _held_pair(stack, wire, tmp_path, extra_pins={"node-c": ""})
        before = (_store_rows(b.store_path), b.registry.get_foreign_chain(a_did))

        unconfigured = await exchange.reset("node-z")
        nothing = await exchange.reset("node-c")  # configured and unpinned, never held
        middle = (_store_rows(b.store_path), b.registry.get_foreign_chain(a_did))
        await exchange.stop()
        stopped = await exchange.reset("node-a")
        after = (_store_rows(b.store_path), b.registry.get_foreign_chain(a_did))

    assert unconfigured == ("unconfigured peer", None) and stopped == ("stopped", None)
    assert nothing == (None, PeerReset("node-c", False, None, None, False, 0))
    assert middle == before and after == before
    assert _messages(caplog, _CONTINUITY_LOGGER, logging.WARNING) == [
        "AD-1198: the reset of 'node-z' was refused (unconfigured peer); nothing was forgotten",
        "AD-1198: the reset of 'node-a' was refused (stopped); nothing was forgotten",
    ]
    assert "AD-1198: reset of 'node-c' on the operator's request: no key history was held for it" in _messages(
        caplog, _CONTINUITY_LOGGER, logging.INFO,
    )


async def test_s2c_m2_a_reset_whose_identity_db_or_envelope_store_fails_says_what_it_forgot_and_a_retry_converges(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_CONTINUITY_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        _, b, _, exchange, a_did = await _held_pair(stack, wire, tmp_path)
        chain = b.registry.get_foreign_chain(a_did)
        assert chain is not None
        store = vars(vars(b.transport)["_guard"])["_store"]
        before = _store_rows(b.store_path)

        async def failing(*_args: Any) -> Any:
            raise sqlite3.OperationalError("AD-1198 slice 2c test: injected failure")

        monkeypatch.setattr(b.registry, "forget_foreign_chain", failing)
        ledger_failed = await exchange.reset("node-a")
        kept = (_store_rows(b.store_path), b.registry.get_foreign_chain(a_did))
        monkeypatch.undo()
        monkeypatch.setattr(store, "forget", failing)
        store_failed = await exchange.reset("node-a")
        partial = (_store_rows(b.store_path), b.registry.get_foreign_chain(a_did), b.transport.chain_seam.held("node-a"))
        monkeypatch.undo()
        retried = await exchange.reset("node-a")
        after = _store_rows(b.store_path)

    assert ledger_failed == ("identity.db: OperationalError", None) and kept == (before, chain)
    assert store_failed == ("not recorded (OperationalError)", None)
    assert partial[0] == before and partial[1] is None and partial[2] is not None  # identity.db first; the hold is kept
    assert retried == (None, PeerReset("node-a", True, a_did, 0, False, 0)) and after == ([], [])
    assert _messages(caplog, _CONTINUITY_LOGGER, logging.WARNING)[:2] == [
        "AD-1198: the reset of 'node-a' was refused (identity.db: OperationalError); nothing was forgotten",
        f"AD-1198: the reset of 'node-a' was refused (not recorded (OperationalError)); identity.db forgot its "
        f"{len(chain)}-block chain for that DID, but the hold's write did not complete, and a reset that completes "
        "forgets both",
    ]


async def test_s2c_m2_no_chain_import_interleaves_a_reset_and_one_judged_before_it_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        _, b, _, exchange, a_did = await _held_pair(stack, wire, tmp_path)
        chain = b.registry.get_foreign_chain(a_did)
        entered, release = asyncio.Event(), asyncio.Event()
        real = b.registry.forget_foreign_chain

        async def gated(did: str) -> int:
            entered.set()
            await release.wait()
            return await real(did)

        monkeypatch.setattr(b.registry, "forget_foreign_chain", gated)
        resetting = asyncio.create_task(exchange.reset("node-a"))
        importing: asyncio.Task[tuple[bool, str]] | None = None
        try:
            await asyncio.wait_for(entered.wait(), 5)  # the reset holds identity.db's lock, the hold not yet forgotten
            importing = asyncio.create_task(exchange.import_chain_from("node-a", chain))  # judged against that hold
            for _ in range(5):
                await asyncio.sleep(0)
            release.set()
            reset, imported = await asyncio.wait_for(resetting, 5), await asyncio.wait_for(importing, 5)
        finally:
            release.set()  # A-2: the reset paused in identity.db's step is never left paused
            await _joined(resetting, importing)
        stored = b.registry.get_foreign_chain(a_did)

    assert reset[1] is not None and reset[1].forgotten
    assert imported == (False, "identity exchange refused (not held)")
    assert stored is None  # no chain stays in identity.db without the hold that vouched for it
    assert exchange.refusal_counts == {"not held": 1}


async def test_s2c_m2_a_resync_answered_after_a_reset_is_refused_and_one_already_recording_completes_first(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, _, exchange, a_did = await _held_pair(stack, wire, tmp_path)
        guard = vars(b.transport)["_guard"]
        stored = b.registry.get_foreign_chain(a_did)
        assert stored is not None
        for _ in range(_GAP):
            await a.binding.rotate()
        chain = await a.registry.export_chain()
        history = chain_key_history(chain)
        recording, release = asyncio.Event(), asyncio.Event()

        async def before_record() -> str | None:
            recording.set()
            await release.wait()
            return None

        resyncing = asyncio.create_task(guard.resync(await _chain_answer(a, chain), history, before_record))
        resetting: asyncio.Task[tuple[str | None, PeerReset | None]] | None = None
        try:
            await asyncio.wait_for(recording.wait(), 5)  # the resync holds the guard's accept lock and records next
            resetting = asyncio.create_task(exchange.reset("node-a"))
            early, _ = await asyncio.wait({resetting}, timeout=0.5)  # far longer than a reset of an unlocked guard takes
            waited = not early and guard.held("node-a") is not None
            release.set()
            resynced, reset = await asyncio.wait_for(resyncing, 5), await asyncio.wait_for(resetting, 5)
        finally:
            release.set()  # A-2: the resync paused before it records is never left paused
            await _joined(resyncing, resetting)
        late = await guard.resync(await _chain_answer(a, chain), history)  # an answer that arrives after the reset

    assert waited and resynced is True
    assert reset == (None, PeerReset("node-a", True, a_did, _GAP, False, len(stored)))  # what the resync recorded
    assert late is False and _resync_refusals(caplog)[-1] == "not held"
    assert guard.held("node-a") is None and _store_rows(b.store_path) == ([], [])


# --------------------------------------------------------------------------- #
# M2 -- the route
# --------------------------------------------------------------------------- #


class _SpyExchange:
    """The route's identity exchange as a double: records each reset, answers ``outcome`` and, as the exchange does once a
    reset's write has committed (A-1), calls the route's audit with what it forgot."""

    def __init__(self, outcome: tuple[str | None, PeerReset | None] | None = None) -> None:
        self.calls: list[str] = []
        self.outcome = outcome

    async def reset(
        self, node_id: str, audit: Callable[[PeerReset], None] | None = None,
    ) -> tuple[str | None, PeerReset | None]:
        self.calls.append(node_id)
        reason, reset = self.outcome if self.outcome is not None else (None, PeerReset(node_id, False, None, None, False, 0))
        if reset is not None and audit is not None:
            audit(reset)
        return reason, reset


class _FailingAudit:
    def append(self, **_kwargs: Any) -> Any:
        raise RuntimeError("AD-1198 slice 2c test: the audit log refused the entry")


def _runtime(exchange: Any, *, token: str = _TOKEN, audit_log: Any = None, unaudited: bool = False) -> Any:
    return SimpleNamespace(
        config=SystemConfig(auth=AuthConfig(crew_scope_token=token)), federation_identity_exchange=exchange,
        audit_log=None if unaudited else (audit_log if audit_log is not None else AuditLog()),
    )


@contextlib.asynccontextmanager
async def _client(runtime: Any) -> AsyncIterator[httpx.AsyncClient]:
    """The real identity router over ``runtime`` on a bare app, in the test's own loop."""
    app = FastAPI()
    app.include_router(identity_routes.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _bearer(token: str = _TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _audited(runtime: Any) -> list[dict[str, Any]]:
    return [json.loads(entry.detail) for entry in runtime.audit_log.entries if entry.category == _AUDIT_CATEGORY]


async def test_s2c_api_reset_forgets_the_peers_hold_and_chain_audits_it_and_answers_what_it_forgot(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, exchange, a_did = await _held_pair(stack, wire, tmp_path)
        blocks = len(b.registry.get_foreign_chain(a_did) or [])
        runtime = _runtime(exchange)
        async with _client(runtime) as client:
            response = await client.post(
                _RESET.format("node-a"), json={"confirm": _CONFIRM, "note": "re-pinned after a lost key"}, headers=_bearer(),
            )
        between = (_store_rows(b.store_path), b.registry.get_foreign_chain(a_did))
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))  # a first contact again
        held = b.transport.chain_seam.held("node-a")

    expected = {"node_id": "node-a", "forgotten": True, "did": a_did, "key_seq": 0, "refused_at_start": False, "identity_chain_blocks": blocks}
    assert response.status_code == 200, response.text
    assert response.json() == expected
    assert _audited(runtime) == [{"v": 1, "action": "reset", **expected, "note": "re-pinned after a lost key"}]
    assert pin_a not in response.text and all(pin_a not in entry.detail for entry in runtime.audit_log.entries)
    assert between == (([], []), None) and held is not None and held.state.seq == 0


async def test_s2c_api_reset_answers_503_while_unarmed_then_403_without_a_token_and_401_without_its_bearer_first() -> None:
    spy = _SpyExchange()
    body = {"confirm": _CONFIRM}
    path = _RESET.format("node-a")
    runtimes = [_runtime(None, token=""), _runtime(None), _runtime(spy, token=""), _runtime(spy), _runtime(spy)]
    headers = [{}, _bearer(), {}, {}, _bearer("not-the-token")]
    answers = []
    for runtime, given in zip(runtimes, headers, strict=True):
        async with _client(runtime) as client:
            response = await client.post(path, json=body, headers=given)
        answers.append((response.status_code, response.json().get("detail")))

    assert answers == [
        (503, "peer admission is not armed"), (503, "peer admission is not armed"), (403, "identity_keys_require_token"),
        (401, "missing_or_malformed_authorization"), (401, "invalid_token"),
    ]
    assert spy.calls == [] and all(_audited(runtime) == [] for runtime in runtimes)  # no state was read, nothing audited


async def test_s2c_api_reset_validates_its_confirm_note_and_node_id_before_the_exchange_is_asked() -> None:
    spy = _SpyExchange()
    runtime = _runtime(spy)
    statuses = []
    async with _client(runtime) as client:
        for node, body in (
            ("node-a", {"confirm": "yes"}),
            ("node-a", {}),
            ("node-a", {"confirm": _CONFIRM, "force": True}),
            ("node-a", {"confirm": _CONFIRM, "note": "n" * 501}),
            ("n" * 257, {"confirm": _CONFIRM}),
            ("", {"confirm": _CONFIRM}),
            ("node-a", {"confirm": _CONFIRM, "note": "n" * 500}),
            ("n" * 256, {"confirm": _CONFIRM}),
            ("x", {"confirm": _CONFIRM}),
        ):
            statuses.append((await client.post(_RESET.format(node), json=body, headers=_bearer())).status_code)

    assert statuses == [422] * 6 + [200] * 3
    assert spy.calls == ["node-a", "n" * 256, "x"]
    assert [entry["node_id"] for entry in _audited(runtime)] == ["node-a", "n" * 256, "x"]


async def test_s2c_api_reset_maps_refusals_reaches_a_node_id_with_a_slash_and_its_audit_degrades(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_ROUTER_LOGGER)
    body = {"confirm": _CONFIRM}
    answers = []
    for reason in ("unconfigured peer", "not armed", "store write unsettled", "identity.db: OperationalError"):
        runtime = _runtime(_SpyExchange((reason, None)))
        async with _client(runtime) as client:
            response = await client.post(_RESET.format("node-a"), json=body, headers=_bearer())
        answers.append((response.status_code, response.json()["detail"], _audited(runtime)))
    slash = _SpyExchange()
    async with _client(_runtime(slash)) as client:
        reached = await client.post(_RESET.format("rack%2Fnode-a"), json=body, headers=_bearer())
    unaudited = []
    for runtime in (_runtime(_SpyExchange(), unaudited=True), _runtime(_SpyExchange(), audit_log=_FailingAudit())):
        async with _client(runtime) as client:
            unaudited.append((await client.post(_RESET.format("node-a"), json=body, headers=_bearer())).status_code)

    assert answers == [
        (404, "unconfigured peer", []), (503, "not armed", []), (503, "store write unsettled", []),
        (503, "identity.db: OperationalError", []),
    ]
    assert reached.status_code == 200 and slash.calls == ["rack/node-a"]
    assert unaudited == [200, 200]  # the reset stands; its audit is log-and-degrade
    assert _messages(caplog, _ROUTER_LOGGER, logging.WARNING) == [
        "AD-1198: the reset of 'node-a' took effect but is not audited: no audit log is wired",
        "AD-1198: auditing the reset of 'node-a' failed; the reset itself stands",
    ]


# --------------------------------------------------------------------------- #
# M3 -- what a reset heals
# --------------------------------------------------------------------------- #


async def test_s2c_m3_a_re_incepted_peer_is_held_again_after_a_reset_once_its_pin_names_its_new_key(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, _, exchange, a_did = await _held_pair(stack, wire, tmp_path)
        await a.binding.reincept(reason="lost", compromised_after_index=None)
        _, new_pin = await _active_key(a.binding)
        reincepted = await a.registry.export_chain()
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))  # the hold refuses it (AD-1197 R-3)
        first = await exchange.reset("node-a")
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))  # a first contact, under the old pin
        await exchange.stop()
        await _admit(stack, b, pins={"node-a": new_pin})  # the operator re-pins node-a to its new key
        repinned = _exchange(b, {"node-a": new_pin})
        stack.push_async_callback(repinned.stop)
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))  # a first contact, under the new pin
        held = b.transport.chain_seam.held("node-a")
        imported = await repinned.import_chain_from("node-a", reincepted)  # identity.db takes it as a first chain (AD-1196 R-3)

    assert [reason for _, source, reason in _rejections(caplog) if source == "node-a"] == ["held history", "pin (continuity)"]
    assert first[1] is not None and first[1].forgotten and first[1].identity_chain_blocks > 0  # a reset never moves a pin
    assert held is not None and (held.did, held.state.seq) == (a_did, 1)
    assert imported == (True, f"Chain imported: {len(reincepted)} blocks from {a_did}")


async def test_s2c_m3_key_history_too_long_is_healed_by_a_reset_of_an_unpinned_peer(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    monkeypatch.setattr(envelope_module, "MAX_HELD_KEY_IDS", _GAP)  # past 33 recorded key ids a sender is refused
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, _Wire(), tmp_path, "node-a")
        guard, path = await _guard(stack, tmp_path, {"node-a": ""})  # configured, unpinned: trust on first use
        assert await guard.admit(await _seal(a, "node-b"))
        admitted = []
        for done in range(1, _GAP + 1):
            await a.binding.rotate()
            if done in (31, _GAP):
                admitted.append(await guard.admit(await _seal(a, "node-b")))
        forgotten = await guard.forget("node-a", _holding([]))
        again = await guard.admit(await _seal(a, "node-b"))
        ((_, _, key_seq, _, key_ids),) = _store_rows(path)[0]

    assert admitted == [True, False] and _rejections(caplog)[-1][2] == "key history too long"
    assert forgotten is None and again is True
    assert key_seq == _GAP and len(key_ids) <= _GAP  # a first contact records only the keys its run introduced


async def test_s2c_m3_a_mutual_gap_heals_by_one_reset_and_the_other_sides_resync(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, _, pin_b = await _pinned_pair(stack, wire, tmp_path)
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))
        await b.transport.send_to_peer("node-a", _unsigned("node-b"))  # each holds the other's inception
        for node in (a, b):
            for _ in range(_GAP):
                await node.binding.rotate()  # each misses 33 of the other's key events
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))
        await b.transport.send_to_peer("node-a", _unsigned("node-b"))
        gaps = [(source, reason) for _, source, reason in _rejections(caplog)]
        _, pin_a_now = await _active_key(a.binding)
        await _admit(stack, b, pins={"node-a": pin_a_now})  # node-b re-pins node-a: its pinned key left the newest 32
        exchange_a = _exchange(a, {"node-b": pin_b})
        exchange_b = _exchange(b, {"node-a": pin_a_now})
        stack.push_async_callback(exchange_a.stop)
        stack.push_async_callback(exchange_b.stop)
        a.transport.chain_seam.on_history_gap(exchange_a.history_gap)
        b.transport.chain_seam.on_history_gap(exchange_b.history_gap)
        bridge_a = await _exchange_bridge(stack, a, exchange_a, _RecordingIntentBus("node-a"), peer="node-b")
        bridge_b = await _exchange_bridge(stack, b, exchange_b, _RecordingIntentBus("node-b"), peer="node-a")

        reset = await exchange_b.reset("node-a")  # node-b forgets the hold it refused at start
        await bridge_a.forward_intent(IntentMessage(intent="read_file", params={"path": "/a"}))  # node-b: a first contact
        await _until(
            lambda: (held := a.transport.chain_seam.held("node-b")) is not None and held.state.seq == _GAP,
            what="node-a's resync of node-b",
        )
        a_to_b = await bridge_a.forward_intent(IntentMessage(intent="read_file", params={"path": "/a"}))
        b_to_a = await bridge_b.forward_intent(IntentMessage(intent="read_file", params={"path": "/b"}))

    assert gaps == [("node-a", "key history gap"), ("node-b", "key history gap")]
    assert reset[1] is not None and reset[1].refused_at_start
    assert [result.result for result in a_to_b] == ["done by node-b"]
    assert [result.result for result in b_to_a] == ["done by node-a"]


async def test_s2c_m3_a_stored_chain_on_another_branch_that_refuses_the_peers_chain_is_forgotten_by_a_reset(
    tmp_path: Path,
) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, _ = await _pinned_pair(stack, wire, tmp_path)
        exchange = _exchange(b, {"node-a": pin_a})
        stack.push_async_callback(exchange.stop)
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))
        a_did = (await a.binding.status())["did"]
        await _birth(a.registry, "Troi", instance_id="ship-a")
        chain = await a.registry.export_chain()
        other = _diverged(chain, len(chain) - 1, "imported before arming")  # another branch from its last block
        assert (await b.registry.import_chain(other))[0] is True  # premise: identity.db stores it, as before arming

        refused = await exchange.import_chain_from("node-a", chain)
        reset = await exchange.reset("node-a")
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))  # a first contact
        imported = await exchange.import_chain_from("node-a", chain)
        stored = b.registry.get_foreign_chain(a_did)

    assert refused == (False, "identity exchange refused (does not extend the stored chain)")
    assert reset[1] is not None and reset[1].identity_chain_blocks == len(other)
    assert imported == (True, f"Chain imported: {len(chain)} blocks from {a_did}") and stored == chain


async def test_s2c_m3_a_divergence_slice_2b_refuses_is_forgotten_by_a_reset_and_the_peers_branch_held_next(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        a, _, copy, guard, _ = await _scene(stack, tmp_path)  # the guard holds node-a's inception; a copy of node-a
        await copy.binding.rotate()
        assert await guard.admit(await _seal(copy, "node-b"))  # premise: the guard holds the copy's branch
        await a.binding.rotate()  # node-a's own branch parts from it by a rotation, not a recovery
        refused = await guard.admit(await _seal(a, "node-b"))
        held = guard.held("node-a")
        assert held is not None
        judged = recovery_precedence(held.events, await _history(a))
        forgotten = await guard.forget("node-a", _holding([]))
        admitted = await guard.admit(await _seal(a, "node-b"))
        now = guard.held("node-a")
        history = await _history(a)

    assert refused is False and _rejections(caplog)[-1][2] in ("held history", "stale key")
    assert judged == (None, "the first divergent event is not a recovery")
    assert forgotten is None and admitted is True
    assert now is not None and now.events[-1].digest == history[-1].digest  # node-a's own branch is held now


# --------------------------------------------------------------------------- #
# A-1 -- review round 1: identity.db's isolation, the hold judged again, the guard's settlement, the audit on commit
# --------------------------------------------------------------------------- #


class _Faults:
    """Faults shared by identity.db's connections in one test (A-1): the next commit may wait on a gate, and the next
    commit of a transaction that deleted a stored chain may fail."""

    def __init__(self) -> None:
        self.hold: asyncio.Event | None = None
        self.holding = asyncio.Event()
        self.fail_deletion = False
        self.connections = 0  # the connections the registry opened of its own


class _Faulty:
    """An aiosqlite connection to identity.db under ``_Faults``."""

    def __init__(self, inner: Any, faults: _Faults) -> None:
        self._inner = inner
        self._faults = faults
        self._deleted = False

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        self._deleted = self._deleted or sql.startswith("DELETE FROM foreign_chains")
        return self._inner.execute(sql, parameters)

    async def commit(self) -> None:
        deleted, self._deleted = self._deleted, False
        if deleted and self._faults.fail_deletion:
            self._faults.fail_deletion = False
            raise sqlite3.OperationalError("AD-1198 slice 2c A-1 test: the deletion's commit failed")
        gate, self._faults.hold = self._faults.hold, None
        if gate is not None:
            self._faults.holding.set()
            await gate.wait()
        await self._inner.commit()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _FaultyFactory:
    def __init__(self, faults: _Faults) -> None:
        self._faults = faults

    async def connect(self, db_path: str) -> Any:
        self._faults.connections += 1
        return _Faulty(await default_factory.connect(db_path), self._faults)


def _key_seq(db_path: Path) -> int | None:
    """This ship's newest committed key event, read through a connection of the test's own."""
    with contextlib.closing(sqlite3.connect(db_path)) as db:
        return db.execute("SELECT MAX(seq) FROM identity_key_events").fetchone()[0]


@pytest.mark.parametrize("ending", ["fails", "is-cancelled"])
async def test_s2c_a1_a_reset_waits_for_a_local_key_events_commit_and_never_commits_or_rolls_back_any_of_it(
    tmp_path: Path, ending: str,
) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        _, b, _, exchange, a_did = await _held_pair(stack, wire, tmp_path)
        chain = b.registry.get_foreign_chain(a_did)
        identity_db = tmp_path / "node-b-identity" / "identity.db"
        faults = _Faults()
        shared = _Faulty(vars(b.registry)["_db"], faults)
        vars(b.registry)["_db"] = shared  # the registry's shared connection, which its key binding writes through too
        vars(b.binding)["_db"] = shared
        vars(b.registry)["_connection_factory"] = _FaultyFactory(faults)  # and any connection it opens of its own
        gate = faults.hold = asyncio.Event()
        rotating = asyncio.create_task(b.binding.rotate())
        resetting: asyncio.Task[tuple[str | None, PeerReset | None]] | None = None
        try:
            await asyncio.wait_for(faults.holding.wait(), 5)  # this ship's ledger block and key event are pending, uncommitted
            faults.fail_deletion = ending == "fails"
            resetting = asyncio.create_task(exchange.reset("node-a"))
            early, _ = await asyncio.wait({resetting}, timeout=0.5)  # far longer than one deletion takes (milliseconds)
            waited = (not early, _key_seq(identity_db), faults.connections)
            if ending == "is-cancelled":
                resetting.cancel()  # cancelled while it waits
            gate.set()
            ended, _ = await asyncio.wait({rotating, resetting}, timeout=10)
            assert ended == {rotating, resetting}, "the rotation and the reset end once the rotation may commit"
            outcome = "cancelled" if resetting.cancelled() else resetting.result()
        finally:
            gate.set()  # A-2: this ship's rotation is never left holding its transaction open
            await _joined(rotating, resetting)
        after = (
            _key_seq(identity_db), (await b.binding.status())["seq"], b.registry.get_foreign_chain(a_did),
            _identity_rows(identity_db)["chains"], b.transport.chain_seam.held("node-a") is not None,
        )
        _, restarted = await stack.enter_async_context(_armed(tmp_path / "node-b-identity", b.duck, instance_id="ship-b"))
        restart_seq = (await restarted.status())["seq"]

    assert waited == (True, 0, 1)  # on a connection of its own, it waits for the local commit and committed none of it
    assert "block_index" in rotating.result()  # A-2: the rotation returned; an exception it raised fails the test here
    assert outcome == {"fails": ("identity.db: OperationalError", None), "is-cancelled": "cancelled"}[ending]
    assert after == (1, 1, chain, [(a_did,)], True)  # the key event is durable; the chain and the hold are kept
    assert restart_seq == 1


async def test_s2c_a1_a_chain_judged_before_a_reset_is_refused_once_a_first_contact_holds_another_branch(
    tmp_path: Path,
) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, _, exchange, a_did = await _held_pair(stack, wire, tmp_path)
        copy = await _copy(stack, a, tmp_path, "", "x")  # node-a's identity and keys as they are now: one branch more
        guard = vars(b.transport)["_guard"]
        await a.binding.rotate()
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))  # node-b holds node-a's branch
        assert (await exchange.import_chain_from("node-a", await a.registry.export_chain()))[0]
        await _birth(a.registry, "Troi", instance_id="ship-a")
        old = await a.registry.export_chain()  # extends that branch: judged against the hold, it keeps it
        await copy.binding.rotate()  # another branch from the same inception key, so under the same pin
        other = await copy.registry.export_chain()
        judged, release = asyncio.Event(), asyncio.Event()
        real = vars(IdentityExchange)["_judged"]

        async def paused(sender: str, blocks: object, *, supersede: bool = False) -> tuple[str | None, Any]:
            verdict = await real(exchange, sender, blocks, supersede=supersede)
            judged.set()
            await release.wait()
            return verdict

        vars(exchange)["_judged"] = paused  # an import paused after its judgement
        importing = asyncio.create_task(exchange.import_chain_from("node-a", old))
        try:
            await asyncio.wait_for(judged.wait(), 5)
            reset = await exchange.reset("node-a")
            first_contact = await guard.admit(await _seal(copy, "node-b"))  # a first contact on the other branch
            held = guard.held("node-a")
            release.set()
            delayed = await asyncio.wait_for(importing, 5)
        finally:
            release.set()  # A-2: the paused import is never left paused
            await _joined(importing)
            vars(exchange).pop("_judged")
        imported = await exchange.import_chain_from("node-a", other)
        stored = b.registry.get_foreign_chain(a_did)

    assert reset[1] is not None and reset[1].forgotten and first_contact is True  # premises
    assert held is not None and held.events[-1].digest == chain_key_history(other)[-1].digest
    assert delayed == (False, "identity exchange refused (held history)")  # refused: it does not keep the current hold
    assert imported == (True, f"Chain imported: {len(other)} blocks from {a_did}") and stored == other


@pytest.mark.parametrize("ending", ["commits-late", "fails-late"])
async def test_s2c_a1_no_chain_is_imported_while_a_resets_write_is_unsettled_and_a_retry_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: str,
) -> None:
    monkeypatch.setattr(envelope_module, "STORE_WRITE_SETTLE_S", _BOUND_S)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, _, exchange, a_did = await _held_pair(stack, wire, tmp_path)
        guard = vars(b.transport)["_guard"]
        store = vars(guard)["_store"]
        identity_db = tmp_path / "node-b-identity" / "identity.db"
        chain = await a.registry.export_chain()
        gate, stalls = asyncio.Event(), [True]
        real = store.forget

        async def stalled(source: str) -> None:
            if stalls:  # only the reset's first write stalls past the bound
                stalls.pop()
                await gate.wait()
                if ending == "fails-late":
                    raise sqlite3.OperationalError("AD-1198 slice 2c A-1 test: the reset's write failed after the bound")
            await real(source)

        monkeypatch.setattr(store, "forget", stalled)
        try:
            first = await exchange.reset("node-a")  # its write outlasts the bound
            pending = (guard.held("node-a") is not None, b.registry.get_foreign_chain(a_did), _identity_rows(identity_db)["chains"])
            during = await exchange.import_chain_from("node-a", chain)  # judged against the hold the guard still shows
            gate.set()
            await _until(lambda: vars(guard)["_unsettled"].task.done(), what="the reset's write to end")
        finally:
            gate.set()  # A-2: the reset's stalled write is never left stalled
        retried = await exchange.reset("node-a")
        after = (
            guard.held("node-a"), _store_rows(b.store_path), b.registry.get_foreign_chain(a_did),
            _identity_rows(identity_db)["chains"],
        )

    late = ending == "fails-late"
    assert first == ("store write unsettled", None)
    assert pending == (True, None, [])  # premise: the guard still shows the hold; identity.db forgot its chain first
    assert during == (False, "identity exchange refused (store write unsettled)")
    assert retried == (None, PeerReset("node-a", late, a_did if late else None, 0 if late else None, False, 0))
    assert after == (None, ([], []), None, [])  # converged: nothing held, and identity.db stores nothing for the peer


@pytest.mark.parametrize("caller", ["cancelled", "answered-503"])
async def test_s2c_a1_api_a_reset_is_audited_once_with_its_note_when_its_caller_is_cancelled_or_it_commits_after_the_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caller: str,
) -> None:
    if caller == "answered-503":
        monkeypatch.setattr(envelope_module, "STORE_WRITE_SETTLE_S", _BOUND_S)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, _, exchange, a_did = await _held_pair(stack, wire, tmp_path)
        blocks = len(b.registry.get_foreign_chain(a_did) or [])
        store = vars(vars(b.transport)["_guard"])["_store"]
        began, gate = asyncio.Event(), asyncio.Event()
        real = store.forget

        async def stalled(source: str) -> None:
            began.set()
            await gate.wait()
            await real(source)

        monkeypatch.setattr(store, "forget", stalled)
        runtime = _runtime(exchange)
        answer: Any = None
        async with _client(runtime) as client:
            posting = asyncio.create_task(
                client.post(_RESET.format("node-a"), json={"confirm": _CONFIRM, "note": "lost key"}, headers=_bearer()),
            )
            try:
                await asyncio.wait_for(began.wait(), 5)  # the reset's write has begun
                if caller == "cancelled":
                    posting.cancel()  # the operator's request is cancelled while the write runs
                else:
                    answer = await asyncio.wait_for(posting, 5)  # 503 at the bound, the write still running
                before = _audited(runtime)
                gate.set()
                if caller == "cancelled":
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(posting, 5)
                await _until(lambda: len(_audited(runtime)) == 1, what="the committed reset's audit")
                await a.transport.send_to_peer("node-b", _unsigned("node-a"))  # the next envelope settles the write: a first contact
            finally:
                gate.set()  # A-2: the reset's stalled write is never left stalled
                await _joined(posting)
        entries = _audited(runtime)
        rows = (_store_rows(b.store_path)[0], b.registry.get_foreign_chain(a_did))

    expected = {
        "v": 1, "action": "reset", "node_id": "node-a", "forgotten": True, "did": a_did, "key_seq": 0,
        "refused_at_start": False, "identity_chain_blocks": blocks, "note": "lost key",
    }
    assert before == [] and entries == [expected]  # once, with its own metadata and note
    assert answer is None or (answer.status_code, answer.json()["detail"]) == (503, "store write unsettled")
    assert rows[1] is None and [row[0] for row in rows[0]] == ["node-a"]  # the reset committed; its first contact is held


async def test_s2c_a1_guard_runs_what_follows_a_committed_reset_once_and_never_for_one_that_failed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, _Wire(), tmp_path, "node-a")
        c = await _node(stack, _Wire(), tmp_path, "node-c")
        _, pin_a = await _active_key(a.binding)
        _, pin_c = await _active_key(c.binding)
        guard, path = await _guard(stack, tmp_path, {"node-a": pin_a, "node-c": pin_c, "node-q": ""})
        assert await guard.admit(await _seal(a, "node-b")) and await guard.admit(await _seal(c, "node-b"))
        followed: list[str] = []

        def failing() -> None:
            followed.append("node-a")
            raise RuntimeError("AD-1198 slice 2c A-1 test: the step after the commit failed")

        failed_step = await guard.forget("node-a", _holding([]), failing)  # committed; what follows it fails
        held_a = guard.held("node-a")
        plain = await guard.forget("node-q", _holding([]))  # nothing follows: nothing more is done or logged

        async def broken(source: str) -> None:
            raise sqlite3.OperationalError("AD-1198 slice 2c A-1 test: the reset's write failed")

        monkeypatch.setattr(vars(guard)["_store"], "forget", broken)
        failed_write = await guard.forget("node-c", _holding([]), lambda: followed.append("node-c"))
        held_c = guard.held("node-c")

    assert (failed_step, plain, failed_write) == (None, None, "not recorded (OperationalError)")
    assert followed == ["node-a"] and held_a is None and held_c is not None  # once for a committed write, never a failed one
    assert [row[0] for row in _store_rows(path)[0]] == ["node-c"]
    assert _messages(caplog, _ENVELOPE_LOGGER, logging.WARNING) == [
        "AD-1198: the reset of 'node-a' has committed, but what follows its commit failed (RuntimeError); the reset "
        "stands, and that step is not retried",
    ]
