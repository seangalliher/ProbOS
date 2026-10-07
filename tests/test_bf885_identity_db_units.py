"""BF-885 (#1468): identity.db's writers -- each write one unit of work, one unit at a time.

H1-H3 are #1468's three reproductions, each with a restart and each asserting its own premise. O, I and K are one writer
class each -- onboarding, imports, key events -- and show that a failure or a cancellation inside one unit leaves every
other writer's unit intact and memory equal to what committed. T, C, F and R are the issued transfer, the ship's
commissioning, slice 2c's deletion and the registry's stop; W is the writer's own contract. Real registries and key
bindings over the duck keyring in a temp directory; faults enter through the registry's connection factory. A is
Amendment A-1 (review round 1): while a unit whose caller stopped waiting has not ended nothing is admitted, every value a
unit's statements depend on -- a signature's anchor, a key event's block, the chain an import is judged against -- is
derived inside the unit from what committed, and an export reads what committed only.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import probos.identity as identity_module
import probos.identity_writer as identity_writer
from probos.federation.envelope import STORE_WRITE_SETTLE_S
from probos.identity import AgentIdentityRegistry
from probos.identity_key_store import KeyringKeyStore
from probos.identity_keys import chain_key_events, verify_chain_signatures
from probos.identity_writer import IdentityUnitUnsettled, IdentityWriter
from probos.storage.sqlite_factory import default_factory
from tests.test_ad1196_did_key_binding import _armed, _birth, _DuckKeyring
from tests.test_ad1196_did_key_binding import _no_real_os_keyring  # noqa: F401 -- the autouse guard against the OS keyring
from tests.test_ad1197_signed_envelopes import _unsigned, _Wire
from tests.test_ad1198_identity_continuity import _exchange, _pinned_pair, _resync_pair
from tests.test_ad1198_peer_reset import _joined

_WRITER_LOGGER = "probos.identity_writer"
_BOUND_S = 0.2  # a short bound for the writer's own tests: they exercise the bound, not its value (W2 pins that)


class _Shared:
    """A connection to identity.db under test. Every statement is logged; one statement prefix can be made to fail once;
    the next commit can be held before SQLite sees it (``hold``), held while SQLite runs it (``hold_inflight``: the COMMIT
    is queued first, as aiosqlite queues one whose caller is then cancelled), or made to fail once before SQLite sees it
    (``fail_commit``: the transaction stays open, as ``SQLITE_BUSY`` at ``COMMIT`` leaves it) -- or, held, fail once it
    is released (``fail_held``, A-1)."""

    def __init__(self, inner: Any, held: asyncio.Event) -> None:
        self._inner = inner
        self.held = held
        self.statements: list[str] = []
        self.fail_prefix = ""
        self.fail_commit = False
        self.fail_held = False
        self.hold: asyncio.Event | None = None
        self.hold_inflight: asyncio.Event | None = None
        self.inflight: asyncio.Task[None] | None = None

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        self.statements.append(sql)
        if self.fail_prefix and sql.lstrip().startswith(self.fail_prefix):
            self.fail_prefix = ""
            raise sqlite3.OperationalError("BF-885 test: injected statement failure")
        return self._inner.execute(sql, parameters)

    async def commit(self) -> None:
        if self.fail_commit:
            self.fail_commit = False
            raise sqlite3.OperationalError("BF-885 test: COMMIT not completed")
        gate, self.hold = self.hold, None
        if gate is not None:
            self.held.set()
            await gate.wait()
            if self.fail_held:  # A-1 the held COMMIT fails once released, its transaction left open
                self.fail_held = False
                raise sqlite3.OperationalError("BF-885 test: COMMIT failed once it was released")
        late, self.hold_inflight = self.hold_inflight, None
        if late is None:
            await self._inner.commit()
            return
        self.inflight = asyncio.create_task(self._inner.commit())
        await asyncio.sleep(0)  # the COMMIT is queued on aiosqlite's worker thread
        self.held.set()
        await late.wait()
        await self.inflight

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _SharedFactory:
    """Wraps every connection the registry opens: the first is its shared connection, a later one slice 2c's own.
    ``next_hold_inflight`` holds the commit of the next connection opened, while SQLite runs it."""

    def __init__(self) -> None:
        self.held = asyncio.Event()
        self.opened: list[_Shared] = []
        self.next_hold_inflight: asyncio.Event | None = None

    async def connect(self, db_path: str) -> Any:
        connection = _Shared(await default_factory.connect(db_path), self.held)
        connection.hold_inflight, self.next_hold_inflight = self.next_hold_inflight, None
        self.opened.append(connection)
        return connection

    @property
    def shared(self) -> _Shared:
        return self.opened[0]


class _Fake:
    """A connection double for the writer's own contract: it records every call; its next commit can be held on a gate,
    and its rollback can be made to fail."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.hold: asyncio.Event | None = None
        self.held = asyncio.Event()
        self.fail_rollback = False

    async def execute(self, sql: str, parameters: Any = ()) -> None:
        self.calls.append(sql)

    async def commit(self) -> None:
        gate, self.hold = self.hold, None
        if gate is not None:
            self.held.set()
            await gate.wait()
        self.calls.append("COMMIT")

    async def rollback(self) -> None:
        self.calls.append("ROLLBACK")
        if self.fail_rollback:
            raise sqlite3.OperationalError("BF-885 test: injected rollback failure")


class _FixedTime:
    """``probos.identity``'s clock, fixed, so that two transfers of one agent share a timestamp."""

    @staticmethod
    def time() -> float:
        return 1790000000.5


def _rows(db_path: Path, sql: str) -> list[tuple[Any, ...]]:
    """Committed rows only: a connection of the test's own sees no other connection's pending statements."""
    with contextlib.closing(sqlite3.connect(db_path)) as db:
        return db.execute(sql).fetchall()


def _key_seq(db_path: Path) -> int | None:
    return _rows(db_path, "SELECT MAX(seq) FROM identity_key_events")[0][0]


async def _foreign_chain(
    stack: contextlib.AsyncExitStack, tmp: Path, instance_id: str, *, births: int,
) -> list[dict[str, Any]]:
    """Another ship's signed chain: its genesis, its inception and ``births`` birth certificates."""
    other, _ = await stack.enter_async_context(_armed(tmp / instance_id, _DuckKeyring(), instance_id=instance_id))
    for index in range(births):
        await _birth(other, f"Crew{index}", instance_id=instance_id)
    return await other.export_chain()


async def _write(writer: IdentityWriter, sql: str, committed: list[str] | None = None) -> None:
    async with writer.unit(None if committed is None else lambda: committed.append(sql)) as db:
        await db.execute(sql)


class _GatedSignStore:
    """A real key store whose next signature waits on a gate, as a keyring that answers late does (A-1)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.hold: asyncio.Event | None = None
        self.held = asyncio.Event()

    async def describe(self) -> Any:
        return await self.inner.describe()

    async def create(self, did: str) -> tuple[str, str]:
        return await self.inner.create(did)

    async def public_key(self, kid: str) -> str | None:
        return await self.inner.public_key(kid)

    async def sign(self, kid: str, message: str) -> str:
        gate, self.hold = self.hold, None
        if gate is not None:
            self.held.set()
            await gate.wait()
        return await self.inner.sign(kid, message)


def _anchor(jws: str) -> int:
    """The ``anchor_index`` a certificate signature names in its protected header (AD-1196 A-1)."""
    header = jws.split(".")[0]
    return json.loads(base64.urlsafe_b64decode(header + "=" * (-len(header) % 4)))["anchor_index"]


def _ending(registry: AgentIdentityRegistry) -> Any:
    """The newest unit end of the registry's writer, found through ``vars`` as the loop's teardown would find it."""
    return vars(vars(registry)["_writer"])["_ending"]


def _seqs(chain: list[dict[str, Any]] | None) -> list[int]:
    return [event.payload["seq"] for event in chain_key_events(chain or [])]


# --------------------------------------------------------------------------- #
# H1-H3: #1468's reproductions, each with a restart
# --------------------------------------------------------------------------- #


async def test_bf885_h1_a_full_disk_in_another_writers_unit_keeps_a_rotation_reported_done(tmp_path: Path) -> None:
    duck, data_dir, factory = _DuckKeyring(), tmp_path / "ship-a", _SharedFactory()
    db_path = data_dir / "identity.db"
    rotating: asyncio.Task[dict[str, Any]] | None = None
    importing: asyncio.Task[tuple[bool, str]] | None = None
    async with contextlib.AsyncExitStack() as stack:
        c_chain = await _foreign_chain(stack, tmp_path, "ship-c", births=8)  # ten blocks: importing it needs new pages
        registry, binding = await stack.enter_async_context(_armed(data_dir, duck, connection_factory=factory))
        shared = factory.shared
        gate = shared.hold = asyncio.Event()
        try:
            rotating = asyncio.create_task(binding.rotate())
            await asyncio.wait_for(factory.held.wait(), 5)  # the rotation's ledger block and key event are pending
            pending = (_key_seq(db_path), rotating.done())
            async with shared.execute("PRAGMA page_count") as cursor:
                pages = (await cursor.fetchone())[0]
            await shared.execute(f"PRAGMA max_page_count = {pages}")  # identity.db's disk is full
            importing = asyncio.create_task(registry.import_chain(c_chain))  # another writer, under another lock
            await asyncio.wait({importing}, timeout=0.5)
            waited = not importing.done()
            gate.set()
            await asyncio.wait({rotating, importing}, timeout=10)
        finally:
            gate.set()
            await _joined(rotating, importing)
        await shared.execute("PRAGMA max_page_count = 1073741823")
        failure = importing.exception()
        rotated = rotating.result()  # the rotation reported success; an exception it raised fails the test here
        memory = (await binding.status())["seq"]
        durable = _key_seq(db_path)
        _, restarted = await stack.enter_async_context(_armed(data_dir, duck))
        after = (await restarted.status())["seq"]
    assert pending == (0, False), "premise: the rotation's rows were pending when the import began"
    assert isinstance(failure, sqlite3.OperationalError), "premise: the import's statement failed"
    assert str(failure) == "database or disk is full", "premise: the import's statement failed SQLITE_FULL"
    assert "block_index" in rotated, "premise: the rotation reported success"
    assert waited  # the import waited for the rotation's unit to end
    assert (memory, durable, after) == (1, 1, 1)  # the rotation reported done is durable, and after a restart too


async def test_bf885_h2_a_birth_waiting_for_the_ledger_lock_has_nothing_pending_for_another_writers_commit(
    tmp_path: Path,
) -> None:
    duck, data_dir = _DuckKeyring(), tmp_path / "ship-a"
    db_path = data_dir / "identity.db"
    issuing: asyncio.Task[Any] | None = None
    async with contextlib.AsyncExitStack() as stack:
        c_chain = await _foreign_chain(stack, tmp_path, "ship-c", births=0)
        registry, _ = await stack.enter_async_context(_armed(data_dir, duck))
        lock = vars(registry)["_ledger_lock"]  # a key event under way holds the registry's ledger lock
        await lock.acquire()
        try:
            issuing = asyncio.create_task(_birth(registry, "Troi"))
            for _ in range(20):
                await asyncio.sleep(0.01)  # the issuance runs until it waits for the ledger lock
            pending = (_rows(db_path, "SELECT callsign FROM birth_certificates"), issuing.done())
            imported = await registry.import_chain(c_chain)  # another writer commits meanwhile
            split = _rows(
                db_path,
                "SELECT b.callsign FROM birth_certificates b LEFT JOIN identity_ledger l ON l.agent_did = b.did "
                "WHERE l.block_index IS NULL",
            )
            issuing.cancel()  # the issuance ends before its ledger block (a cancellation; a crash leaves the same rows)
            await asyncio.wait({issuing}, timeout=5)
        finally:
            lock.release()
            await _joined(issuing)
        restarted, _ = await stack.enter_async_context(_armed(data_dir, duck))
        after = [cert.callsign for cert in restarted.get_all()]
        slot = restarted.get_by_slot("slot-Troi")
    assert pending == ([], False), "premise: nothing of the birth was durable, and it was still issuing"
    assert imported[0] is True and issuing.cancelled(), "premise: another writer committed; the issuance was cancelled"
    assert split == []  # nothing of the waiting birth was pending for that commit
    assert "Troi" not in after and slot is None  # after a restart: no agent identity the ledger never recorded


async def test_bf885_h3_a_rotation_whose_commit_failed_is_rolled_back_and_never_made_durable(tmp_path: Path) -> None:
    duck, data_dir, factory = _DuckKeyring(), tmp_path / "ship-a", _SharedFactory()
    db_path = data_dir / "identity.db"
    async with contextlib.AsyncExitStack() as stack:
        c_chain = await _foreign_chain(stack, tmp_path, "ship-c", births=0)
        registry, binding = await stack.enter_async_context(_armed(data_dir, duck, connection_factory=factory))
        blocks = _rows(db_path, "SELECT COUNT(*) FROM identity_ledger")
        factory.shared.fail_commit = True
        rotation = None
        try:
            await binding.rotate()
        except sqlite3.OperationalError as exc:
            rotation = str(exc)
        status = (await binding.status())["status"]
        before = _key_seq(db_path)
        imported = await registry.import_chain(c_chain)  # an unrelated writer commits
        durable = (_key_seq(db_path), _rows(db_path, "SELECT COUNT(*) FROM identity_ledger"))
        _, restarted = await stack.enter_async_context(_armed(data_dir, duck))
        after = (await restarted.status())["seq"]
    assert rotation == "BF-885 test: COMMIT not completed", "premise: the rotation's commit failed"
    assert status == "needs_restart" and before == 0 and imported[0] is True, "premise: AD-1196's latch, nothing durable"
    assert durable == (0, blocks)  # the failed rotation's event and ledger block are rolled back, not committed later
    assert after == 0  # the rotation reported failed is not the ship's key after a restart


# --------------------------------------------------------------------------- #
# O, I, K: a failure or a cancellation inside one writer class leaves the others intact
# --------------------------------------------------------------------------- #


async def test_bf885_o1_a_birth_whose_ledger_block_fails_rolls_back_its_rows_and_the_next_unit_commits_alone(
    tmp_path: Path,
) -> None:
    duck, data_dir, factory = _DuckKeyring(), tmp_path / "ship-a", _SharedFactory()
    db_path = data_dir / "identity.db"
    async with contextlib.AsyncExitStack() as stack:
        registry, _ = await stack.enter_async_context(_armed(data_dir, duck, connection_factory=factory))
        mark = len(factory.shared.statements)
        factory.shared.fail_prefix = "INSERT INTO identity_ledger"  # the birth's ledger block fails
        failed = None
        try:
            await _birth(registry, "Troi")
        except sqlite3.OperationalError as exc:
            failed = str(exc)
        ran = [sql.split("(")[0].strip() for sql in factory.shared.statements[mark:] if sql.startswith("INSERT")]
        tag = await registry.issue_asset_tag("probe", "slot-asset", "system")  # the next unit, another writer's
        memory = (registry.get_by_slot("slot-Troi"), registry.get_asset_by_slot("slot-asset"))
        rows = (
            _rows(db_path, "SELECT callsign FROM birth_certificates"),
            _rows(db_path, "SELECT slot_id FROM slot_mappings"),
            _rows(db_path, "SELECT slot_id FROM asset_tags"),
        )
        restarted, _ = await stack.enter_async_context(_armed(data_dir, duck))
        after = (restarted.get_by_slot("slot-Troi"), restarted.get_asset_by_slot("slot-asset"))
    assert failed == "BF-885 test: injected statement failure", "premise: the birth's ledger block failed"
    assert ran == [
        "INSERT INTO birth_certificates", "INSERT OR REPLACE INTO slot_mappings", "INSERT INTO identity_ledger",
    ], "premise: its birth row and slot mapping ran before its ledger block failed"
    assert memory == (None, tag)
    assert rows == ([], [], [("slot-asset",)])  # the failed birth left nothing for the asset tag's commit
    assert after[0] is None and after[1] is not None and after[1].asset_uuid == tag.asset_uuid


async def test_bf885_o2_a_birth_cancelled_while_it_commits_is_committed_held_in_memory_and_on_the_ledger(
    tmp_path: Path,
) -> None:
    duck, data_dir, factory = _DuckKeyring(), tmp_path / "ship-a", _SharedFactory()
    db_path = data_dir / "identity.db"
    issuing: asyncio.Task[Any] | None = None
    async with contextlib.AsyncExitStack() as stack:
        registry, _ = await stack.enter_async_context(_armed(data_dir, duck, connection_factory=factory))
        shared = factory.shared
        gate = shared.hold_inflight = asyncio.Event()
        try:
            issuing = asyncio.create_task(_birth(registry, "Troi"))
            await asyncio.wait_for(factory.held.wait(), 5)  # its COMMIT is queued and running
            issuing.cancel()
            await asyncio.wait({issuing}, timeout=0.5)
            kept = not issuing.done()
            gate.set()
            await asyncio.wait({issuing}, timeout=10)
        finally:
            gate.set()
            await _joined(issuing, shared.inflight)
        durable = _rows(db_path, "SELECT callsign FROM birth_certificates")
        cached = registry.get_by_slot("slot-Troi")
        by_uuid = registry.get_by_uuid(cached.agent_uuid) if cached is not None else None
        on_ledger = cached is not None and cached.did in {block["agent_did"] for block in await registry.export_chain()}
        restarted, _ = await stack.enter_async_context(_armed(data_dir, duck))
        after = restarted.get_by_slot("slot-Troi")
    assert durable == [("Troi",)], "premise: the queued COMMIT completed after its caller was cancelled"
    assert issuing.cancelled() and kept  # the cancellation is raised, once the unit has ended
    assert cached is not None and by_uuid is cached and on_ledger  # memory holds what committed
    assert after is not None and after.did == cached.did


async def test_bf885_i1_a_transfer_import_whose_second_row_fails_leaves_neither_row_and_a_rotation_commits_alone(
    tmp_path: Path,
) -> None:
    duck, data_dir, factory = _DuckKeyring(), tmp_path / "ship-b", _SharedFactory()
    db_path = data_dir / "identity.db"
    async with contextlib.AsyncExitStack() as stack:
        origin, _ = await stack.enter_async_context(_armed(tmp_path / "ship-a", _DuckKeyring(), instance_id="ship-a"))
        holder, binding = await stack.enter_async_context(
            _armed(data_dir, duck, instance_id="ship-b", connection_factory=factory),
        )
        ship = holder.get_ship_certificate()
        assert ship is not None
        troi = await _birth(origin, "Troi", instance_id="ship-a")
        xfer = await origin.issue_transfer_certificate(troi.agent_uuid, ship.ship_did)
        assert (await holder.import_chain(await origin.export_chain()))[0]
        factory.shared.fail_prefix = "INSERT OR REPLACE INTO transfer_certificates"  # its second row fails
        failed = None
        try:
            await holder.import_transfer_certificate(xfer)
        except sqlite3.OperationalError as exc:
            failed = str(exc)
        ran = [sql.split("(")[0].strip() for sql in factory.shared.statements if "INTO foreign_birth" in sql]
        await binding.rotate()  # another writer's unit commits
        rows = (
            _rows(db_path, "SELECT did FROM foreign_birth_certificates"),
            _rows(db_path, "SELECT did FROM transfer_certificates"),
            _key_seq(db_path),
        )
        memory = holder.get_by_uuid(troi.agent_uuid)
        retried = await holder.import_transfer_certificate(xfer)  # nothing of the failed import blocks a retry
        held = holder.get_by_uuid(troi.agent_uuid)
        restarted, _ = await stack.enter_async_context(_armed(data_dir, duck, instance_id="ship-b"))
        after = restarted.get_by_uuid(troi.agent_uuid)
    assert failed == "BF-885 test: injected statement failure", "premise: its second row failed"
    assert ran == ["INSERT OR REPLACE INTO foreign_birth_certificates"], "premise: its first row ran before the failure"
    assert rows == ([], [], 1)  # neither row is durable; the rotation committed only its own
    assert memory is None
    assert retried[0] is True and held is not None and after is not None and after.did == troi.did


async def test_bf885_i2_a_chain_import_cancelled_while_it_commits_is_committed_and_held_in_memory(
    tmp_path: Path,
) -> None:
    duck, data_dir, factory = _DuckKeyring(), tmp_path / "ship-a", _SharedFactory()
    db_path = data_dir / "identity.db"
    importing: asyncio.Task[tuple[bool, str]] | None = None
    async with contextlib.AsyncExitStack() as stack:
        c_chain = await _foreign_chain(stack, tmp_path, "ship-c", births=0)
        c_did = c_chain[0]["agent_did"]
        registry, _ = await stack.enter_async_context(_armed(data_dir, duck, connection_factory=factory))
        shared = factory.shared
        gate = shared.hold_inflight = asyncio.Event()
        try:
            importing = asyncio.create_task(registry.import_chain(c_chain))
            await asyncio.wait_for(factory.held.wait(), 5)  # its COMMIT is queued and running
            importing.cancel()
            await asyncio.wait({importing}, timeout=0.5)
            kept = not importing.done()
            gate.set()
            await asyncio.wait({importing}, timeout=10)
        finally:
            gate.set()
            await _joined(importing, shared.inflight)
        durable = _rows(db_path, "SELECT origin_ship_did FROM foreign_chains")
        cached = registry.get_foreign_chain(c_did)
        tag = await registry.issue_asset_tag("probe", "slot-asset", "system")  # the next unit commits alone
        tags = _rows(db_path, "SELECT asset_uuid FROM asset_tags")
        restarted, _ = await stack.enter_async_context(_armed(data_dir, duck))
        after = restarted.get_foreign_chain(c_did)
    assert durable == [(c_did,)], "premise: the queued COMMIT completed after its caller was cancelled"
    assert importing.cancelled() and kept  # the cancellation is raised, once the unit has ended
    assert cached == c_chain and after == c_chain  # memory holds what committed, and so does a restart
    assert tags == [(tag.asset_uuid,)]


async def test_bf885_k1_a_rotation_cancelled_while_it_commits_ends_before_a_waiting_birth_commits_its_own(
    tmp_path: Path,
) -> None:
    duck, data_dir, factory = _DuckKeyring(), tmp_path / "ship-a", _SharedFactory()
    db_path = data_dir / "identity.db"
    rotating: asyncio.Task[dict[str, Any]] | None = None
    issuing: asyncio.Task[Any] | None = None
    async with contextlib.AsyncExitStack() as stack:
        registry, binding = await stack.enter_async_context(_armed(data_dir, duck, connection_factory=factory))
        shared = factory.shared
        first = shared.hold = asyncio.Event()
        second: asyncio.Event | None = None
        try:
            rotating = asyncio.create_task(binding.rotate())
            await asyncio.wait_for(factory.held.wait(), 5)  # the rotation's block and event are pending, its commit held
            factory.held.clear()
            issuing = asyncio.create_task(_birth(registry, "Troi"))  # waits for the ledger lock the rotation holds
            second = shared.hold = asyncio.Event()  # the next commit after the rotation's -- the birth's -- is held too
            await asyncio.sleep(0.05)
            rotating.cancel()
            await asyncio.wait({rotating}, timeout=0.5)
            kept = not rotating.done()
            first.set()
            await asyncio.wait({rotating}, timeout=10)
            await asyncio.wait_for(factory.held.wait(), 5)  # the birth has reached its commit
            durable = (_key_seq(db_path), _rows(db_path, "SELECT callsign FROM birth_certificates"))
            second.set()
            await asyncio.wait({issuing}, timeout=10)
        finally:
            first.set()
            if second is not None:
                second.set()
            await _joined(rotating, issuing)
        status = (await binding.status())["status"]
        troi = issuing.result()
        restarted_registry, restarted_binding = await stack.enter_async_context(_armed(data_dir, duck))
        restarted = (await restarted_binding.status())["seq"]
        exported = {block["agent_did"] for block in await restarted_registry.export_chain()}
    assert rotating.cancelled() and kept  # the cancellation is raised, once the rotation's unit has ended
    assert durable == (1, [])  # the rotation committed itself before the birth committed anything
    assert status == "needs_restart"  # AD-1196: memory claims nothing until a restart derives it from what committed
    assert restarted == 1 and troi.did in exported


# --------------------------------------------------------------------------- #
# T, C, F, R: the issued transfer, the commissioning, slice 2c's deletion, the registry's stop
# --------------------------------------------------------------------------- #


async def test_bf885_t1_an_issued_transfer_whose_row_fails_leaves_no_ledger_block_or_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    duck, data_dir = _DuckKeyring(), tmp_path / "ship-a"
    db_path = data_dir / "identity.db"
    async with contextlib.AsyncExitStack() as stack:
        registry, _ = await stack.enter_async_context(_armed(data_dir, duck))
        troi = await _birth(registry, "Troi")
        monkeypatch.setattr(identity_module, "time", _FixedTime)  # both transfers of Troi at one timestamp
        await registry.issue_transfer_certificate(troi.agent_uuid, "did:probos:ship-b")
        counted = (
            _rows(db_path, "SELECT COUNT(*) FROM identity_ledger")[0][0],
            _rows(db_path, "SELECT COUNT(*) FROM identity_signatures")[0][0],
        )
        raised = None
        try:
            await registry.issue_transfer_certificate(troi.agent_uuid, "did:probos:ship-b")
        except sqlite3.IntegrityError as exc:
            raised = exc
        monkeypatch.undo()
        await _birth(registry, "Data")  # another writer's unit commits
        after = (
            _rows(db_path, "SELECT COUNT(*) FROM identity_ledger")[0][0],
            _rows(db_path, "SELECT COUNT(*) FROM identity_signatures")[0][0],
        )
        valid, message = await registry.verify_chain()
        restarted, _ = await stack.enter_async_context(_armed(data_dir, duck))
        on_ledger = [block for block in await restarted.export_chain() if block["agent_did"] == troi.did]
    assert raised is not None, "premise: the second transfer's row failed on its key"
    assert after == (counted[0] + 1, counted[1] + 1)  # Data's block and signature only: nothing of the failed transfer
    assert valid, message
    assert len(on_ledger) == 2  # Troi's birth and its one transfer


async def test_bf885_c1_a_commission_that_fails_holds_no_ship_certificate_and_a_retry_commissions_the_ship(
    tmp_path: Path,
) -> None:
    factory = _SharedFactory()
    registry = AgentIdentityRegistry(data_dir=tmp_path / "ship-a", connection_factory=factory)
    try:
        await registry.start()
        factory.shared.fail_prefix = "INSERT OR IGNORE INTO identity_ledger"  # its genesis block fails
        failed = None
        try:
            await registry.start(instance_id="ship-a", vessel_name="Ship-A", version="1")
        except sqlite3.OperationalError as exc:
            failed = str(exc)
        ran = "INSERT INTO ship_birth_certificate" in " ".join(factory.shared.statements)
        memory = registry.get_ship_certificate()
        rows = _rows(tmp_path / "ship-a" / "identity.db", "SELECT ship_did FROM ship_birth_certificate")
        await registry.start(instance_id="ship-a", vessel_name="Ship-A", version="1")  # a retry
        ship = registry.get_ship_certificate()
        chain = await registry.export_chain()
    finally:
        await registry.stop()
    assert failed == "BF-885 test: injected statement failure", "premise: its genesis block failed"
    assert ran, "premise: its certificate row ran before its genesis block failed"
    assert memory is None and rows == []  # memory holds no certificate that did not commit
    assert ship is not None and chain and chain[0]["certificate_hash"] == ship.certificate_hash


async def test_bf885_c2_a_commission_cancelled_while_it_commits_holds_the_committed_ship_certificate(
    tmp_path: Path,
) -> None:
    factory = _SharedFactory()
    registry = AgentIdentityRegistry(data_dir=tmp_path / "ship-a", connection_factory=factory)
    starting: asyncio.Task[None] | None = None
    try:
        await registry.start()
        shared = factory.shared
        gate = shared.hold_inflight = asyncio.Event()
        try:
            starting = asyncio.create_task(registry.start(instance_id="ship-a", vessel_name="Ship-A", version="1"))
            await asyncio.wait_for(factory.held.wait(), 5)  # the commissioning's COMMIT is queued and running
            starting.cancel()
            await asyncio.wait({starting}, timeout=0.5)
            kept = not starting.done()
            gate.set()
            await asyncio.wait({starting}, timeout=10)
        finally:
            gate.set()
            await _joined(starting, shared.inflight)
        rows = _rows(tmp_path / "ship-a" / "identity.db", "SELECT ship_did FROM ship_birth_certificate")
        memory = registry.get_ship_certificate()
    finally:
        await registry.stop()
    assert rows == [("did:probos:ship-a",)], "premise: the queued COMMIT completed after its caller was cancelled"
    assert starting.cancelled() and kept  # the cancellation is raised, once the unit has ended
    assert memory is not None and memory.ship_did == "did:probos:ship-a"  # memory holds what committed


async def test_bf885_f1_a_reset_deletion_cancelled_while_it_commits_is_forgotten_in_memory_too(tmp_path: Path) -> None:
    duck, data_dir, factory = _DuckKeyring(), tmp_path / "ship-b", _SharedFactory()
    db_path = data_dir / "identity.db"
    forgetting: asyncio.Task[int] | None = None
    async with contextlib.AsyncExitStack() as stack:
        a_chain = await _foreign_chain(stack, tmp_path, "ship-a", births=1)
        a_did = a_chain[0]["agent_did"]
        holder, _ = await stack.enter_async_context(
            _armed(data_dir, duck, instance_id="ship-b", connection_factory=factory),
        )
        assert (await holder.import_chain(a_chain))[0]
        gate = factory.next_hold_inflight = asyncio.Event()  # the deletion's own connection (slice 2c A-1)
        try:
            forgetting = asyncio.create_task(holder.forget_foreign_chain(a_did))
            await asyncio.wait_for(factory.held.wait(), 5)  # its COMMIT is queued and running
            forgetting.cancel()
            await asyncio.wait({forgetting}, timeout=0.5)
            kept = not forgetting.done()
            gate.set()
            await asyncio.wait({forgetting}, timeout=10)
        finally:
            gate.set()
            await _joined(forgetting, *(connection.inflight for connection in factory.opened))
        durable = _rows(db_path, "SELECT origin_ship_did FROM foreign_chains")
        cached = holder.get_foreign_chain(a_did)
        restarted, _ = await stack.enter_async_context(_armed(data_dir, duck, instance_id="ship-b"))
        after = restarted.get_foreign_chain(a_did)
    assert len(factory.opened) == 2 and durable == [], "premise: its own connection's queued COMMIT completed"
    assert forgetting.cancelled() and kept  # the cancellation is raised, once the unit has ended
    assert cached is None and after is None  # memory follows the committed deletion


async def test_bf885_r1_a_registry_stopped_while_a_unit_ends_closes_its_connection_only_after_that_unit(
    tmp_path: Path,
) -> None:
    factory = _SharedFactory()
    data_dir = tmp_path / "ship-a"
    registry = AgentIdentityRegistry(data_dir=data_dir, connection_factory=factory)
    tagging: asyncio.Task[Any] | None = None
    stopping: asyncio.Task[None] | None = None
    await registry.start()
    gate = factory.shared.hold = asyncio.Event()
    try:
        tagging = asyncio.create_task(registry.issue_asset_tag("probe", "slot-asset", "system"))
        await asyncio.wait_for(factory.held.wait(), 5)  # the tag's commit is held: its unit is still ending
        stopping = asyncio.create_task(registry.stop())
        await asyncio.wait({stopping}, timeout=0.1)
        waited = not stopping.done()
        gate.set()
        await asyncio.wait({tagging, stopping}, timeout=10)
    finally:
        gate.set()
        await _joined(tagging, stopping)
        await registry.stop()
    outcome = tagging.exception()  # None once the unit committed
    rows = _rows(data_dir / "identity.db", "SELECT asset_uuid FROM asset_tags")
    assert waited  # the stop waited for the unit still ending
    assert outcome is None and rows == [(tagging.result().asset_uuid,)]


# --------------------------------------------------------------------------- #
# W: the writer's own contract
# --------------------------------------------------------------------------- #


async def test_bf885_w1_a_unit_whose_caller_is_cancelled_ends_first_runs_committed_once_and_raises_the_cancellation() -> None:
    fake = _Fake()
    writer = IdentityWriter(lambda: fake)
    committed: list[str] = []
    gate = fake.hold = asyncio.Event()
    ending: asyncio.Task[None] | None = None
    waiting: asyncio.Task[None] | None = None
    body_gate = asyncio.Event()

    async def held_in_body() -> None:
        async with writer.unit(lambda: committed.append("body")) as db:
            await db.execute("INSERT 2")
            await body_gate.wait()  # cancelled here, before its end

    try:
        ending = asyncio.create_task(_write(writer, "INSERT 1", committed))
        await asyncio.wait_for(fake.held.wait(), 5)
        ending.cancel()
        await asyncio.wait({ending}, timeout=0.2)
        kept = not ending.done()
        gate.set()
        await asyncio.wait({ending}, timeout=5)
        waiting = asyncio.create_task(held_in_body())
        await asyncio.sleep(0.05)
        waiting.cancel()
        await asyncio.wait({waiting}, timeout=5)
    finally:
        gate.set()
        body_gate.set()
        await _joined(ending, waiting)
    assert kept and ending.cancelled() and waiting.cancelled()
    assert committed == ["INSERT 1"]  # once, for the unit that committed; never for the one rolled back
    assert fake.calls == ["INSERT 1", "COMMIT", "INSERT 2", "ROLLBACK"]


async def test_bf885_w2_a_unit_outlasting_the_bound_is_refused_and_memory_follows_it_when_it_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_WRITER_LOGGER)
    probe = await default_factory.connect(str(tmp_path / "busy.db"))  # the factory the registry's connection comes from
    try:
        async with probe.execute("PRAGMA busy_timeout") as cursor:
            busy_timeout_ms = (await cursor.fetchone())[0]
    finally:
        await probe.close()
    bound = identity_writer.IDENTITY_UNIT_SETTLE_S
    monkeypatch.setattr(identity_writer, "IDENTITY_UNIT_SETTLE_S", _BOUND_S)
    fake = _Fake()
    writer = IdentityWriter(lambda: fake)
    committed: list[str] = []
    gate = fake.hold = asyncio.Event()
    first: asyncio.Task[None] | None = None
    second: asyncio.Task[None] | None = None
    loop = asyncio.get_running_loop()
    ended: dict[str, float] = {}
    try:
        began = loop.time()
        first = asyncio.create_task(_write(writer, "INSERT 1", committed))
        first.add_done_callback(lambda _task: ended.setdefault("first", loop.time() - began))
        await asyncio.wait_for(fake.held.wait(), 5)
        second_began = loop.time()
        second = asyncio.create_task(_write(writer, "INSERT 2", committed))  # waits for the lock while the first caller waits
        second.add_done_callback(lambda _task: ended.setdefault("second", loop.time() - second_began))
        await asyncio.wait({first, second}, timeout=5)
        first_s, second_s = ended["first"], ended["second"]  # each measured from its own start, when it ended
        began = loop.time()
        with pytest.raises(IdentityUnitUnsettled, match="nothing is admitted until it has"):  # A-1 at once, while unsettled
            await asyncio.wait_for(_write(writer, "INSERT 3", committed), 5)
        third_s = loop.time() - began
        refused = (list(fake.calls), list(committed))
        gate.set()
        await writer.stop()
        await _write(writer, "INSERT 4", committed)  # admitted again once the unit has ended
    finally:
        gate.set()
        await _joined(first, second)
    assert bound == STORE_WRITE_SETTLE_S and bound * 1000 > busy_timeout_ms  # the envelope store's bound: SQLite's ends first
    assert isinstance(first.exception(), IdentityUnitUnsettled)
    assert "the unit has not ended within 0.2 s" in str(first.exception())  # the bound on the unit's end
    assert isinstance(second.exception(), IdentityUnitUnsettled)
    assert "an earlier unit has not ended within 0.2 s" in str(second.exception())  # the bound on the lock
    assert 0.75 * _BOUND_S <= first_s < 5 * _BOUND_S and 0.75 * _BOUND_S <= second_s < 5 * _BOUND_S  # each wait, the bound
    assert third_s < 0.5 * _BOUND_S  # refused at once, never after a wait
    assert refused == (["INSERT 1"], [])  # the second and the third ran nothing; nothing was committed yet
    assert committed == ["INSERT 1", "INSERT 4"] and fake.calls == ["INSERT 1", "COMMIT", "INSERT 4", "COMMIT"]
    assert "whose caller stopped waiting for it has ended: it committed" in caplog.text


async def test_bf885_w3_a_rollback_that_fails_refuses_every_later_unit_until_a_restart(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger=_WRITER_LOGGER)
    monkeypatch.setattr(identity_writer, "IDENTITY_UNIT_SETTLE_S", _BOUND_S)
    fake = _Fake()
    fake.fail_rollback = True
    writer = IdentityWriter(lambda: fake)
    with pytest.raises(sqlite3.OperationalError, match="injected rollback failure"):
        async with writer.unit() as db:
            await db.execute("INSERT 1")
            raise ValueError("the body failed")
    for attempt in (2, 3):  # refused at once, every time: the lock is released after each refusal
        with pytest.raises(IdentityUnitUnsettled, match="refuses every write until a restart"):
            await asyncio.wait_for(_write(writer, f"INSERT {attempt}"), _BOUND_S / 2)
    fake.fail_rollback = False
    await _write(IdentityWriter(lambda: fake), "INSERT 4")  # a restart builds a new writer
    assert fake.calls == ["INSERT 1", "ROLLBACK", "INSERT 4", "COMMIT"]
    assert "could not be rolled back" in caplog.text


async def test_bf885_w4_stop_waits_for_a_unit_still_ending_at_most_the_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(identity_writer, "IDENTITY_UNIT_SETTLE_S", _BOUND_S)
    fake = _Fake()
    writer = IdentityWriter(lambda: fake)
    first_gate = fake.hold = asyncio.Event()
    second_gate: asyncio.Event | None = None
    writing: asyncio.Task[None] | None = None
    stalled: asyncio.Task[None] | None = None
    stopping: asyncio.Task[None] | None = None
    loop = asyncio.get_running_loop()
    try:
        writing = asyncio.create_task(_write(writer, "INSERT 1"))
        await asyncio.wait_for(fake.held.wait(), 5)
        stopping = asyncio.create_task(writer.stop())
        await asyncio.wait({stopping}, timeout=0.05)
        waited = not stopping.done()
        first_gate.set()
        await asyncio.wait({stopping, writing}, timeout=5)
        ended = list(fake.calls)
        fake.held.clear()
        second_gate = fake.hold = asyncio.Event()
        stalled = asyncio.create_task(_write(writer, "INSERT 2"))
        await asyncio.wait_for(fake.held.wait(), 5)
        began = loop.time()
        await asyncio.wait_for(writer.stop(), 5)  # this unit never ends while stop waits
        elapsed = loop.time() - began
    finally:
        first_gate.set()
        if second_gate is not None:
            second_gate.set()
        await _joined(writing, stalled, stopping)
    assert waited and ended == ["INSERT 1", "COMMIT"]
    assert _BOUND_S * 0.75 <= elapsed < _BOUND_S * 10


async def test_bf885_w5_a_unit_without_an_open_connection_writes_nothing() -> None:
    writer = IdentityWriter(lambda: None)
    ran: list[str] = []
    with pytest.raises(RuntimeError, match="not started"):
        async with writer.unit(lambda: ran.append("committed")):
            ran.append("body")
    assert ran == []


async def test_bf885_w6_a_caller_cancelled_while_its_unit_outlasts_the_bound_gets_its_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(identity_writer, "IDENTITY_UNIT_SETTLE_S", _BOUND_S)
    fake = _Fake()
    writer = IdentityWriter(lambda: fake)
    committed: list[str] = []
    gate = fake.hold = asyncio.Event()
    writing: asyncio.Task[None] | None = None
    try:
        writing = asyncio.create_task(_write(writer, "INSERT 1", committed))
        await asyncio.wait_for(fake.held.wait(), 5)
        writing.cancel()
        await asyncio.wait({writing}, timeout=5)  # the caller stops waiting at the bound
        before_end = (writing.done(), list(committed))
        gate.set()
        await writer.stop()
    finally:
        gate.set()
        await _joined(writing)
    assert before_end == (True, [])  # premise: the caller ended before the unit did
    assert writing.cancelled()  # its cancellation, never a refusal in its place
    assert committed == ["INSERT 1"]  # memory followed the unit once it ended


async def test_bf885_w7_an_end_cancelled_before_its_outcome_is_known_refuses_every_later_unit_until_a_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_WRITER_LOGGER)
    monkeypatch.setattr(identity_writer, "IDENTITY_UNIT_SETTLE_S", _BOUND_S)
    db_path = tmp_path / "w7.db"
    with contextlib.closing(sqlite3.connect(db_path)) as setup:
        setup.execute("CREATE TABLE t (n INTEGER)")
        setup.commit()
    shared = _Shared(await default_factory.connect(str(db_path)), asyncio.Event())  # real SQLite: a real transaction
    writer = IdentityWriter(lambda: shared)
    committed: list[str] = []
    gate = shared.hold = asyncio.Event()
    writing: asyncio.Task[None] | None = None
    try:
        writing = asyncio.create_task(_write(writer, "INSERT INTO t VALUES (1)", committed))
        await asyncio.wait({writing}, timeout=5)  # its caller is refused at the bound; its COMMIT is held before SQLite
        ending = vars(writer)["_ending"]  # the end task, cancelled here as the event loop's teardown cancels it
        ending.cancel()
        await asyncio.wait({ending}, timeout=5)
        pending = shared.in_transaction
        for statement in ("INSERT INTO t VALUES (2)", "INSERT INTO t VALUES (3)"):  # refused at once, every time
            with pytest.raises(IdentityUnitUnsettled, match="refuses every write until a restart"):
                await asyncio.wait_for(_write(writer, statement, committed), _BOUND_S / 2)
        with pytest.raises(IdentityUnitUnsettled, match="refuses every write until a restart"):
            async with writer.read():
                pass
    finally:
        gate.set()
        await _joined(writing)
        await shared.close()  # as a restart does: the connection's pending transaction is discarded with it
    durable = _rows(db_path, "SELECT n FROM t")
    assert isinstance(writing.exception(), IdentityUnitUnsettled), "premise: the caller stopped waiting at the bound"
    assert ending.cancelled() and pending, "premise: the end was cancelled while the unit's statement was pending"
    assert durable == [] and committed == []  # no later unit committed it, and memory holds nothing of it
    assert "was cancelled while it ended" in caplog.text
    assert "whose caller stopped waiting for it has ended: its end was cancelled" in caplog.text


async def test_bf885_w8_a_read_sees_only_what_committed_and_is_admitted_as_a_unit_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(identity_writer, "IDENTITY_UNIT_SETTLE_S", _BOUND_S)
    db_path = tmp_path / "w8.db"
    with contextlib.closing(sqlite3.connect(db_path)) as setup:
        setup.execute("CREATE TABLE t (n INTEGER)")
        setup.commit()
    shared = _Shared(await default_factory.connect(str(db_path)), asyncio.Event())
    writer = IdentityWriter(lambda: shared)
    seen: list[list[int]] = []

    async def read() -> None:
        async with writer.read():
            async with shared.execute("SELECT n FROM t ORDER BY n") as cursor:
                seen.append([row[0] for row in await cursor.fetchall()])

    gate: asyncio.Event | None = None
    writing: asyncio.Task[None] | None = None
    reading: asyncio.Task[None] | None = None
    late: asyncio.Task[None] | None = None
    loop = asyncio.get_running_loop()
    try:
        await _write(writer, "INSERT INTO t VALUES (1)")
        gate = shared.hold = asyncio.Event()
        shared.fail_held = True  # this unit's COMMIT, once released, fails: its statement is rolled back
        writing = asyncio.create_task(_write(writer, "INSERT INTO t VALUES (2)"))
        await asyncio.wait_for(shared.held.wait(), 5)
        reading = asyncio.create_task(read())
        await asyncio.sleep(0.05)
        waited = not reading.done()
        gate.set()
        await asyncio.wait({writing, reading}, timeout=5)
        shared.held.clear()
        gate = shared.hold = asyncio.Event()
        late = asyncio.create_task(_write(writer, "INSERT INTO t VALUES (3)"))
        await asyncio.wait({late}, timeout=5)  # its caller is refused at the bound; the unit is still ending
        began = loop.time()
        with pytest.raises(IdentityUnitUnsettled, match="nothing is admitted until it has"):
            async with writer.read():
                pass
        refused_s = loop.time() - began
        gate.set()
        await writer.stop()
        with pytest.raises(ValueError, match="the read failed"):
            async with writer.read():
                raise ValueError("the read failed")
        await asyncio.wait_for(read(), _BOUND_S / 2)  # the failed read released the lock
    finally:
        if gate is not None:
            gate.set()
        await _joined(writing, reading, late)
        await shared.close()
    assert isinstance(writing.exception(), sqlite3.OperationalError), "premise: the pending unit's COMMIT failed"
    assert isinstance(late.exception(), IdentityUnitUnsettled), "premise: the late caller stopped waiting at the bound"
    assert waited  # the read waited for the unit whose statement was pending
    assert seen == [[1], [1, 3]]  # it saw what committed only, never the statement that was rolled back
    assert refused_s < 0.5 * _BOUND_S  # refused at once while a unit's outcome was unknown


# --------------------------------------------------------------------------- #
# A: Amendment A-1 -- a unit whose caller stopped waiting, and what is derived, judged and read inside a unit
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("follower", ["birth", "transfer"])
async def test_bf885_a1_a_follower_of_a_unit_that_failed_late_is_anchored_where_it_lands_and_verifies_remotely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, follower: str,
) -> None:
    monkeypatch.setattr(identity_writer, "IDENTITY_UNIT_SETTLE_S", _BOUND_S)
    duck, data_dir, factory = _DuckKeyring(), tmp_path / "ship-a", _SharedFactory()
    db_path = data_dir / "identity.db"
    store = _GatedSignStore(KeyringKeyStore(backend=duck))
    late: asyncio.Task[Any] | None = None
    following: asyncio.Task[Any] | None = None
    signing = asyncio.Event()
    worf = "SELECT callsign FROM birth_certificates WHERE callsign = 'Worf'"
    async with contextlib.AsyncExitStack() as stack:
        registry, _ = await stack.enter_async_context(_armed(data_dir, duck, store=store, connection_factory=factory))
        receiver, _ = await stack.enter_async_context(_armed(tmp_path / "ship-b", _DuckKeyring(), instance_id="ship-b"))
        troi = await _birth(registry, "Troi")

        def follow() -> Any:  # the next issuance: a birth, or a signed transfer of Troi
            if follower == "birth":
                return _birth(registry, "Data")
            return registry.issue_transfer_certificate(troi.agent_uuid, "did:probos:ship-b")

        shared = factory.shared
        gate = shared.hold = asyncio.Event()
        shared.fail_held = True  # the late unit's COMMIT, once released, fails: its unit is rolled back
        try:
            late = asyncio.create_task(_birth(registry, "Worf"))
            await asyncio.wait({late}, timeout=5)  # its caller is refused at the bound; its unit is still ending
            async with shared.execute(worf) as cursor:
                pending = (list(await cursor.fetchall()), _rows(db_path, worf))
            store.hold = signing
            following = asyncio.create_task(follow())
            for _ in range(200):  # until the follower is refused, or signs while the late unit is pending
                if following.done() or store.held.is_set():
                    break
                await asyncio.sleep(0.005)
            gate.set()
            await asyncio.wait({_ending(registry)}, timeout=5)  # the late unit's COMMIT failed; it was rolled back
            signing.set()
            await asyncio.wait({following}, timeout=5)
        finally:
            gate.set()
            signing.set()
            await _joined(late, following)
        store.hold = None
        rolled_back = _rows(db_path, worf)
        refused = following.exception()
        issued = following.result() if refused is None else await follow()  # refused while unsettled: issued again
        chain = await registry.export_chain()
        block = next(b for b in chain if b["certificate_hash"] == issued.certificate_hash)
        report = verify_chain_signatures(chain)
        received = await receiver.import_chain(chain)
        transfer = await receiver.import_transfer_certificate(issued) if follower == "transfer" else (True, "")
        restarted, _ = await stack.enter_async_context(_armed(data_dir, duck))
        after = verify_chain_signatures(await restarted.export_chain())
    assert isinstance(late.exception(), IdentityUnitUnsettled), "premise: the late caller was refused at the bound"
    assert pending == ([("Worf",)], []), "premise: the late unit's rows were pending, not durable"
    assert rolled_back == [], "premise: the late unit's COMMIT failed and nothing of it is durable"
    assert refused is None or isinstance(refused, IdentityUnitUnsettled), refused
    assert _anchor(block["attestation"]["jws"]) == block["index"]  # signed for the block it landed at
    assert report.ok and after.ok, (report.reason, after.reason)  # every signature verifies, and after a restart
    assert received[0] is True and transfer[0] is True, (received, transfer)  # a peer verifies and accepts it


async def test_bf885_a2_an_older_snapshot_judged_before_a_late_import_committed_never_shrinks_the_stored_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(identity_writer, "IDENTITY_UNIT_SETTLE_S", _BOUND_S)
    wire = _Wire()
    late: asyncio.Task[Any] | None = None
    older: asyncio.Task[Any] | None = None
    b_db = tmp_path / "node-b-identity" / "identity.db"
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, _ = await _pinned_pair(stack, wire, tmp_path)
        exchange = _exchange(b, {"node-a": pin_a})
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))  # node-b holds node-a's key history
        a_did = (await a.binding.status())["did"]
        chains = []
        for callsign in ("Troi", "Worf", "Data"):
            await _birth(a.registry, callsign, instance_id="ship-a")
            chains.append(await a.registry.export_chain())
        three, four, five = chains
        stored = await exchange.import_chain_from("node-a", three)
        shared = _Shared(vars(b.registry)["_db"], asyncio.Event())  # one wrapper after start, as slice 2c's tests swap it
        vars(b.registry)["_db"] = vars(b.binding)["_db"] = shared
        gate = shared.hold = asyncio.Event()
        lock = vars(b.registry)["_foreign_chain_lock"]
        try:
            late = asyncio.create_task(exchange.import_chain_from("node-a", five))
            await asyncio.wait({late}, timeout=5)  # its caller is refused at the bound; its unit is still ending
            await lock.acquire()  # held as a transfer import holds it: the next import is judged, then waits for it
            try:
                older = asyncio.create_task(exchange.import_chain_from("node-a", four))
                for _ in range(20):
                    await asyncio.sleep(0.01)
                judged = (older.done(), len(b.registry.get_foreign_chain(a_did) or []))
                gate.set()  # the late import commits now
                await asyncio.wait({_ending(b.registry)}, timeout=5)
                committed_late = len(b.registry.get_foreign_chain(a_did) or [])
            finally:
                lock.release()
            await asyncio.wait({older}, timeout=5)
        finally:
            gate.set()
            await _joined(late, older)
        memory = len(b.registry.get_foreign_chain(a_did) or [])
        durable = [len(json.loads(chain)) for (chain,) in _rows(b_db, "SELECT chain_json FROM foreign_chains")]
        again = await exchange.import_chain_from("node-a", four)  # judged against what committed: changes nothing
        restarted, _ = await stack.enter_async_context(_armed(b_db.parent, b.duck, instance_id="ship-b"))
        after = len(restarted.get_foreign_chain(a_did) or [])
    assert stored[0] is True, "premise: node-b stored node-a's three-block chain"
    assert isinstance(late.exception(), IdentityUnitUnsettled), "premise: the late import's caller was refused at the bound"
    assert judged == (False, 3), "premise: the older snapshot was judged against the three stored blocks, then waited"
    assert committed_late == 5, "premise: the late import committed its five blocks"
    assert older.result()[0] is False and "Stored chain changed" in older.result()[1], older.result()
    assert (memory, durable, after) == (5, [5], 5)  # nothing shrinks, before or after a restart
    assert again == (True, f"Chain kept: the 5 blocks stored for {a_did} already hold these 4")


async def test_bf885_a3_an_import_while_a_late_one_is_unsettled_is_refused_at_once_and_key_history_never_regresses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(identity_writer, "IDENTITY_UNIT_SETTLE_S", _BOUND_S)
    duck, data_dir, factory = _DuckKeyring(), tmp_path / "ship-b", _SharedFactory()
    late: asyncio.Task[Any] | None = None
    async with contextlib.AsyncExitStack() as stack:
        origin, origin_binding = await stack.enter_async_context(
            _armed(tmp_path / "ship-x", _DuckKeyring(), instance_id="ship-x"),
        )
        seq0 = await origin.export_chain()
        await origin_binding.rotate()
        seq1 = await origin.export_chain()
        x_did = seq0[0]["agent_did"]
        registry, _ = await stack.enter_async_context(
            _armed(data_dir, duck, instance_id="ship-b", connection_factory=factory),
        )
        stored = await registry.import_chain(seq0)
        gate = factory.shared.hold = asyncio.Event()
        loop = asyncio.get_running_loop()
        refusal = ""
        try:
            late = asyncio.create_task(registry.import_chain(seq1))
            await asyncio.wait({late}, timeout=5)  # its caller is refused at the bound; its unit is still ending
            began = loop.time()
            try:
                await asyncio.wait_for(registry.import_chain(seq0), 5)  # the older key history, meanwhile
            except IdentityUnitUnsettled as exc:
                refusal = str(exc)
            refused_s = loop.time() - began
            gate.set()
            await asyncio.wait({_ending(registry)}, timeout=5)
            stale = await registry.import_chain(seq0)  # judged against what committed
        finally:
            gate.set()
            await _joined(late)
        memory = _seqs(registry.get_foreign_chain(x_did))
        restarted, _ = await stack.enter_async_context(_armed(data_dir, duck, instance_id="ship-b"))
        after = _seqs(restarted.get_foreign_chain(x_did))
    assert stored[0] is True and _seqs(seq1) == [0, 1], "premise: seq 0 stored; the late chain carries seq 1"
    assert isinstance(late.exception(), IdentityUnitUnsettled), "premise: the late import's caller was refused at the bound"
    assert "nothing is admitted until it has" in refusal and refused_s < 0.5 * _BOUND_S, (refusal, refused_s)  # at once
    assert stale[0] is False and stale[1].startswith("Key history check failed"), stale
    assert memory == after == [0, 1]  # the key history the late import committed never regresses


async def test_bf885_a4_a_chain_served_over_signed_federation_carries_only_committed_key_events(tmp_path: Path) -> None:
    wire = _Wire()
    rotating: asyncio.Task[Any] | None = None
    asking: asyncio.Task[Any] | None = None
    a_dir, b_dir = tmp_path / "node-a-identity", tmp_path / "node-b-identity"
    async with contextlib.AsyncExitStack() as stack:
        a, b, _, exchange_b, bridge_b = await _resync_pair(stack, wire, tmp_path)
        a_did = (await a.binding.status())["did"]
        shared = _Shared(vars(a.registry)["_db"], asyncio.Event())  # one wrapper after start, as slice 2c's tests swap it
        vars(a.registry)["_db"] = vars(a.binding)["_db"] = shared
        gate = shared.hold = asyncio.Event()
        shared.fail_held = True  # the rotation's COMMIT, once released, fails: its key event is rolled back
        try:
            rotating = asyncio.create_task(a.binding.rotate())
            await asyncio.wait_for(shared.held.wait(), 5)  # its key event and ledger block are pending
            async with shared.execute("SELECT seq FROM identity_key_events ORDER BY seq") as cursor:
                pending = ([row[0] for row in await cursor.fetchall()], [row[0] for row in _rows(
                    a_dir / "identity.db", "SELECT seq FROM identity_key_events ORDER BY seq",
                )])
            asking = asyncio.create_task(bridge_b.request_chain("node-a"))  # signed, answered by node-a's exchange
            await asyncio.wait({asking}, timeout=0.3)
            gate.set()
            await asyncio.wait({rotating}, timeout=5)
            await asyncio.wait({asking}, timeout=10)
        finally:
            gate.set()
            await _joined(rotating, asking)
        served = asking.result()
        received = await exchange_b.import_chain_from("node-a", served) if served else None
        restarted_a, binding_a = await stack.enter_async_context(_armed(a_dir, a.duck, instance_id="ship-a"))
        source_seq = (await binding_a.status())["seq"]
        await binding_a.rotate()  # node-a's next legitimate rotation, after its restart
        source = await restarted_a.export_chain()
        legitimate = await exchange_b.import_chain_from("node-a", source)
        restarted_b, _ = await stack.enter_async_context(_armed(b_dir, b.duck, instance_id="ship-b"))
        receiver = restarted_b.get_foreign_chain(a_did)
    assert isinstance(rotating.exception(), sqlite3.OperationalError), "premise: the rotation's COMMIT failed"
    assert pending == ([0, 1], [0]), "premise: key seq 1 was pending, not durable, when node-b asked"
    assert source_seq == 0, "premise: node-a's committed key history ends at seq 0"
    assert _seqs(served) in ([], [0]), _seqs(served)  # never the key event that rolled back
    assert received is None or received[0] is True, received
    assert legitimate[0] is True, legitimate  # node-a's next rotation extends what node-b stores
    assert [event.digest for event in chain_key_events(receiver or [])] == [
        event.digest for event in chain_key_events(source)
    ]  # node-b holds node-a's committed key history, after a restart too


async def test_bf885_a5_a_transfer_refused_inside_its_unit_writes_nothing_and_says_why(tmp_path: Path) -> None:
    duck, data_dir = _DuckKeyring(), tmp_path / "ship-b"
    db_path = data_dir / "identity.db"
    async with contextlib.AsyncExitStack() as stack:
        origin, _ = await stack.enter_async_context(_armed(tmp_path / "ship-a", _DuckKeyring(), instance_id="ship-a"))
        await _birth(origin, "Troi", instance_id="ship-a")
        chain = await origin.export_chain()  # Troi's birth is on it
        worf = await _birth(origin, "Worf", instance_id="ship-a")  # Worf's is not
        xfer = await origin.issue_transfer_certificate(worf.agent_uuid, "did:probos:ship-b")
        registry, _ = await stack.enter_async_context(_armed(data_dir, duck, instance_id="ship-b"))
        stored = await registry.import_chain(chain)
        refused = await registry.import_transfer_certificate(xfer)  # judged inside its unit: its subject is not on the chain
        rows = (
            _rows(db_path, "SELECT did FROM foreign_birth_certificates"),
            _rows(db_path, "SELECT did FROM transfer_certificates"),
        )
        memory = registry.get_by_uuid(worf.agent_uuid)
        tag = await registry.issue_asset_tag("probe", "slot-asset", "system")  # the next unit is admitted and commits
        tags = _rows(db_path, "SELECT asset_uuid FROM asset_tags")
    assert stored[0] is True, "premise: the origin chain is stored, without Worf's birth"
    assert refused == (False, f"Certificate subject {worf.did} not found in origin chain")
    assert rows == ([], []) and memory is None  # nothing of the refused transfer is written or held
    assert tags == [(tag.asset_uuid,)]
