"""AD-1299 S1b (#1352) M2: the first-trusted-digest ledger and its in-slice consumer.

``RepairEvidenceLinkStore`` keeps the FIRST digest of each ``(candidate digest, evidence kind,
evidence ref)`` and reports a later, different digest as ``changed`` (sticky, never replaced).
``assess_candidate_evidence`` derives both links with the real verifier and binder, records each
``present`` one, and evaluates C9 completion. These tests pin:

* the ledger contract (first / unchanged / changed, ABA stickiness, restart, independence);
* its refusals and failure tiers: bad input before any write, an integrity error for a stored row
  that no longer validates, a write that fails, or is cancelled before its COMMIT is queued, commits
  nothing (one cancelled after may record), a clock that is not
  a finite real, a connection that fails to close;
* the database's own immutability (triggers abort UPDATE, DELETE and INSERT OR REPLACE);
* the producer -> ledger -> completion seam, crossed once with a receipt written by the REAL gate
  producer and across a store restart; the store declaration; and the D5 pin that nothing in
  ``src/`` constructs the store yet.

Direct ``sqlite3`` is used here only to read and to attack the file (the ``db-connect`` gate covers
``src/``). The fault proxy runs the statement on the real connection and THEN raises, so a failure
arrives with its row pending in an open transaction and only closing the connection can discard it.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import hashlib
import itertools
import logging
import queue
import sqlite3
import threading
import weakref
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from probos.cognitive.repair_candidate import (
    EvidenceLink,
    RepairCandidate,
    is_evidence_ref,
    is_sha256_hex,
    verify_gate_receipt,
)
from probos.cognitive.repair_evidence_store import (
    EvidenceAssessment,
    RepairEvidenceIntegrityError,
    RepairEvidenceLinkStore,
    RepairEvidenceStoreUnavailable,
    TrustedDigestCheck,
    assess_candidate_evidence,
)
from probos.storage.registry import load_default_store_registry
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from tests.test_ad1299_s1a_repair_candidate import (  # noqa: F401 -- gate and repo are fixtures; they register by import
    _candidate,
    _mutate,
    _real_receipt,
    _Review,
    gate,
    repo,
)

STORE_LOGGER = "probos.cognitive.repair_evidence_store"
SRC_PROBOS = Path(__file__).resolve().parent.parent / "src" / "probos"
FIRST_TABLE = "repair_evidence_first_digests"
CHANGES_TABLE = "repair_evidence_digest_changes"
FIRST_INSERT = "INSERT INTO repair_evidence_first_digests"

CANDIDATE = "0" * 64
ANOTHER_CANDIDATE = "f" * 64
FIRST = "1" * 64
OTHER = "2" * 64
THIRD = "3" * 64
REF = "receipt-1"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "repair_evidence.db"


def _gate_link(digest: str = FIRST, *, candidate: str = CANDIDATE) -> EvidenceLink:
    return EvidenceLink("gate_receipt", "present", "gate_receipt_bound", candidate, digest)


def _review_link(digest: str = FIRST, *, candidate: str = CANDIDATE) -> EvidenceLink:
    return EvidenceLink("review_set", "present", "review_set_bound", candidate, digest)


class _NotALink:
    """Carries every attribute ``check_and_record`` reads, but is not an ``EvidenceLink``."""

    kind = "gate_receipt"
    current = True
    candidate_digest = CANDIDATE
    evidence_sha256 = FIRST


class _LinkSubclass(EvidenceLink):
    """An ``EvidenceLink`` by ``isinstance`` only: the ledger records exact ``EvidenceLink`` instances."""


def _ticking_clock() -> Callable[[], float]:
    """1.0, 2.0, 3.0, ...: each ``check_and_record`` reads the clock exactly once."""
    ticks = itertools.count(1)
    return lambda: float(next(ticks))


def _rows(db_path: Path, table: str) -> list[tuple[Any, ...]]:
    """Read ``table`` straight from the file, bypassing the store (tests only)."""
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        return conn.execute(  # noqa: S608 -- ``table`` is one of this module's two literals
            f"SELECT * FROM {table} ORDER BY candidate_digest, evidence_kind, evidence_ref"
        ).fetchall()


def _counts(db_path: Path) -> tuple[int, int]:
    """(first-digest rows, digest-change rows)."""
    return len(_rows(db_path, FIRST_TABLE)), len(_rows(db_path, CHANGES_TABLE))


def _recorded_refs(db_path: Path) -> set[tuple[str, str]]:
    """``(kind, ref)`` of every first-digest row."""
    return {(row[1], row[2]) for row in _rows(db_path, FIRST_TABLE)}


async def _started(db_path: Path, **kwargs: Any) -> RepairEvidenceLinkStore:
    store = RepairEvidenceLinkStore(str(db_path), **kwargs)
    await store.start()
    return store


class _QueueSpy:
    """Stands in for an aiosqlite ``Connection._tx`` (R3-1): records ``(label, weakref.ref(future))`` for every item
    the connection queues for its worker thread, then forwards the item unchanged to the original queue (the worker
    thread keeps the original in aiosqlite 0.22.1). ``put_nowait`` is the only method that version's ``Connection``
    calls on it; the worker of 0.19 to 0.21 also calls ``get()`` on the attribute, so every other attribute reads
    through to the original queue (R4-1), and an item that is not a ``(future, function)`` pair (those versions queue
    a bare stop sentinel) is forwarded unrecorded. The future is held WEAKLY: an ``execute`` future carries its
    ``sqlite3.Cursor`` as its result, and a strong reference would keep that cursor's statement unfinalised and lock
    the database."""

    def __init__(self, original: queue.SimpleQueue[Any], factory: _FaultyFactory) -> None:
        self._original = original
        self._factory = factory

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)

    def put_nowait(self, item: Any) -> None:
        if isinstance(item, tuple) and len(item) == 2:
            future, function = item
            reference = None if future is None else weakref.ref(future)
            self._factory.queued.append((self._factory.label(function), reference))
        self._original.put_nowait(item)


class _FaultyConnection:
    """Delegates ``execute`` / ``executescript`` / ``commit`` / ``close`` to a real connection and
    raises when its factory is armed. An armed statement is executed first, so the failure arrives
    with that row pending in an open transaction."""

    def __init__(self, inner: Any, factory: _FaultyFactory) -> None:
        self._inner = inner
        self._factory = factory

    async def execute(self, sql: str, parameters: Sequence[Any] = ()) -> Any:
        cursor = await self._inner.execute(sql, parameters)
        fault = self._factory.fault
        if fault is not None and sql.startswith(fault[0]):
            self._factory.fired += 1
            raise fault[1]
        park = self._factory.park_after
        if park is not None and sql.startswith(park):
            # Park mode: the real statement has run; hold the call here until the test cancels it.
            self._factory.parked.set()
            await self._factory.never.wait()
        return cursor

    async def executescript(self, script: str) -> Any:
        return await self._inner.executescript(script)

    async def commit(self) -> None:
        factory = self._factory
        if not factory.park_at_commit:
            await self._inner.commit()
            return
        # Park mode at the commit point (R2-3): hold the connection's worker thread with a queued
        # blocker, queue the real COMMIT behind it, and make production await exactly that COMMIT.
        factory.blocker = asyncio.ensure_future(self._inner._execute(factory.block_worker))
        await asyncio.sleep(0)
        factory.commit_future = asyncio.ensure_future(self._inner.commit())
        await asyncio.sleep(0)
        factory.parked.set()
        await factory.commit_future  # production awaits exactly this COMMIT

    async def close(self) -> None:
        await self._inner.close()
        if self._factory.fail_close:
            raise RuntimeError("injected close failure")


async def _close_unless_stuck(inner: Any) -> None:
    """Close a raw connection through a BOUNDED wait (R5-2): ``Connection.close()`` awaits the worker's shutdown in a
    ``finally``, so a stuck worker keeps it pending; the cleanup is never awaited unless it finished, and an
    exception it raised is retrieved and swallowed."""
    cleanup = asyncio.ensure_future(inner.close())
    await asyncio.wait({cleanup}, timeout=2)
    if cleanup.done() and not cleanup.cancelled():
        cleanup.exception()


class _FaultyFactory:
    """Wraps ``SQLiteConnectionFactory``: records every connection it hands out, and can raise on an
    armed statement or after closing the real connection."""

    def __init__(self) -> None:
        self._real = SQLiteConnectionFactory()
        self.connect_paths: list[str] = []
        self.fault: tuple[str, BaseException] | None = None
        self.fired = 0
        self.fail_close = False
        self.park_after: str | None = None  # park mode: hold the caller after this statement has run
        self.park_at_commit = False  # park mode: hold the worker, queue the COMMIT behind it, await it
        self.parked = asyncio.Event()  # set when a connection has parked
        self.never = asyncio.Event()  # never set: a parked call leaves only by being cancelled
        self.release = threading.Event()  # set by the test to let the held worker thread go on
        self.worker_parked = threading.Event()  # set from the worker thread once the blocker holds it
        self.blocker: asyncio.Future[Any] | None = None  # the blocker queued ahead of the COMMIT
        self.commit_future: asyncio.Future[None] | None = None  # the real COMMIT production awaits
        self.queued: list[tuple[str, weakref.ReferenceType[asyncio.Future[Any]] | None]] = []  # worker-queue spy (R3-1), in order

    def block_worker(self) -> bool:
        # Runs ON the connection's worker thread: announce the hold, then hold it until released.
        self.worker_parked.set()
        return self.release.wait(10)

    @staticmethod
    def label(function: Any) -> str:
        """The spy's label for one queued callable (every aiosqlite ``_execute`` call is a ``functools.partial``)."""
        target = getattr(function, "func", function)
        if getattr(target, "__func__", None) is _FaultyFactory.block_worker:
            return "blocker"
        if isinstance(getattr(target, "__self__", None), sqlite3.Connection):
            return str(target.__name__)  # "execute", "commit", "close", ...
        return str(getattr(target, "__name__", type(target).__name__))

    def queued_labels(self) -> list[str]:
        """Every label the spy saw, in queue order."""
        return [label for label, _reference in self.queued]

    def queued_tail(self) -> list[str]:
        """The labels from the last ``"blocker"`` on; ``[]`` if no blocker was queued."""
        labels = self.queued_labels()
        if "blocker" not in labels:
            return []
        return labels[len(labels) - 1 - labels[::-1].index("blocker"):]

    def arm(self, statement_prefix: str, error: BaseException) -> None:
        self.fault = (statement_prefix, error)

    def disarm(self) -> None:
        self.fault = None

    def park_after_statement(self, statement_prefix: str) -> None:
        self.park_after = statement_prefix

    def park_commit(self) -> None:
        self.park_at_commit = True

    def unpark(self) -> None:
        self.park_after = None
        self.park_at_commit = False

    async def connect(self, db_path: str) -> _FaultyConnection:
        self.connect_paths.append(db_path)
        inner = await self._real.connect(db_path)
        # premise: the aiosqlite internal the spy relies on (``core.py:88`` in 0.22.1); a different shape fails here
        if not isinstance(inner._tx, queue.SimpleQueue):
            await _close_unless_stuck(inner)
            pytest.fail("the queue spy broke the aiosqlite worker: its internals differ from the versions this test was written for")
        inner._tx = _QueueSpy(inner._tx, self)
        try:
            # R4-1, R5-1: prove the worker still answers through the spy with TWO timed round trips (no-op COMMITs,
            # recorded as two more ``commit`` labels); the worker of 0.19 to 0.21 re-reads its queue between items,
            # so a spy it cannot read through shows on the second one
            await asyncio.wait_for(inner.commit(), 5)
            await asyncio.wait_for(inner.commit(), 5)
        except Exception:  # noqa: BLE001 -- a timeout or any worker failure; ``pytest.fail`` raises its own exception
            await _close_unless_stuck(inner)
            pytest.fail("the queue spy broke the aiosqlite worker: its internals differ from the versions this test was written for")
        return _FaultyConnection(inner, self)


def _reviews(candidate: RepairCandidate) -> list[_Review]:
    """Two independent, accepted reviews of this candidate's tree, both naming the campaign builder."""
    return [
        _Review(review_attempt_id="attempt-1", reviewer_id="red_team", reviewed_tree=candidate.tree),
        _Review(review_attempt_id="attempt-2", reviewer_id="system_qa", reviewed_tree=candidate.tree),
    ]


async def _assess(
    store: RepairEvidenceLinkStore,
    candidate: RepairCandidate,
    receipt: bytes | None,
    reviews: Sequence[_Review] | None,
    **overrides: Any,
) -> EvidenceAssessment:
    """``assess_candidate_evidence`` with the campaign defaults; ``overrides`` replace any argument."""
    authority_class = overrides.pop("authority_class", "repair")
    arguments: dict[str, Any] = {
        "receipt_ref": "gate-run-1",
        "receipt_bytes": receipt,
        "review_ref": "review-round-1",
        "reviews": reviews,
        "expected_assignee": "builder",
        "required_reviewers": 2,
    }
    arguments.update(overrides)
    return await assess_candidate_evidence(store, candidate, authority_class, **arguments)


async def _assert_unavailable(store: RepairEvidenceLinkStore, link: EvidenceLink) -> None:
    with pytest.raises(RepairEvidenceStoreUnavailable) as excinfo:
        await store.check_and_record(REF, link)
    assert excinfo.value.args == ("repair_evidence_store_unavailable",)


# ---------------------------------------------------------------------------
# Construction and lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_path", ["", ":memory:", None, 5], ids=["empty", "memory", "none", "int"])
def test_constructor_refuses_bad_paths(tmp_path: Path, bad_path: object) -> None:
    good = tmp_path / "repair_evidence.db"
    RepairEvidenceLinkStore(str(good))  # premise: a real path constructs...
    assert not good.exists()  # ...and opens nothing until start()

    with pytest.raises(ValueError) as excinfo:
        RepairEvidenceLinkStore(bad_path)  # type: ignore[arg-type]

    assert excinfo.value.args == ("repair_evidence_store_path_invalid",)


async def test_unstarted_and_stopped_store_raise_unavailable(db_path: Path) -> None:
    store = RepairEvidenceLinkStore(str(db_path), clock=lambda: 1.0)
    link = _gate_link()

    await _assert_unavailable(store, link)  # before start()
    await store.stop()  # stop before start is a no-op
    await _assert_unavailable(store, link)
    assert not db_path.exists()  # nothing was ever opened

    await store.start()
    await store.start()  # idempotent
    assert (await store.check_and_record(REF, link)).status == "first_recorded"  # premise: started works

    await store.stop()
    await store.stop()  # idempotent
    await _assert_unavailable(store, link)  # after stop()

    await store.start()  # start after stop works, on the same file
    assert (await store.check_and_record(REF, link)).status == "unchanged"
    await store.stop()


# ---------------------------------------------------------------------------
# The ledger contract
# ---------------------------------------------------------------------------


async def test_first_observation_recorded_then_unchanged(db_path: Path) -> None:
    store = await _started(db_path, clock=_ticking_clock())
    link = _gate_link()

    first = await store.check_and_record(REF, link)
    again = await store.check_and_record(REF, link)

    assert isinstance(first, TrustedDigestCheck)
    assert (first.status, first.candidate_digest, first.kind, first.evidence_ref) == (
        "first_recorded", CANDIDATE, "gate_receipt", REF,
    )
    assert (first.first_sha256, first.observed_sha256, first.changed) == (FIRST, FIRST, False)
    assert (again.status, again.first_sha256, again.observed_sha256, again.changed) == (
        "unchanged", FIRST, FIRST, False,
    )
    # one row, written by the first observation only
    assert _rows(db_path, FIRST_TABLE) == [(CANDIDATE, "gate_receipt", REF, FIRST, 1, 1.0)]
    assert _rows(db_path, CHANGES_TABLE) == []
    await store.stop()


async def test_different_digest_is_changed_first_kept_and_sticky(db_path: Path) -> None:
    store = await _started(db_path, clock=_ticking_clock())

    a = await store.check_and_record(REF, _gate_link(FIRST))
    b = await store.check_and_record(REF, _gate_link(OTHER))
    a_again = await store.check_and_record(REF, _gate_link(FIRST))  # ABA: back to the first bytes
    c = await store.check_and_record(REF, _gate_link(THIRD))

    assert (a.status, a.first_sha256, a.observed_sha256) == ("first_recorded", FIRST, FIRST)
    assert (b.status, b.first_sha256, b.observed_sha256, b.changed) == ("changed", FIRST, OTHER, True)
    assert (a_again.status, a_again.first_sha256, a_again.observed_sha256) == ("changed", FIRST, FIRST)
    assert (c.status, c.first_sha256, c.observed_sha256) == ("changed", FIRST, THIRD)
    # the file holds one first row (A, at its own tick) and one change row (B, at ITS tick): never replaced
    assert _rows(db_path, FIRST_TABLE) == [(CANDIDATE, "gate_receipt", REF, FIRST, 1, 1.0)]
    assert _rows(db_path, CHANGES_TABLE) == [(CANDIDATE, "gate_receipt", REF, OTHER, 1, 2.0)]
    await store.stop()


async def test_first_digest_survives_restart(db_path: Path) -> None:
    store = await _started(db_path)
    assert (await store.check_and_record(REF, _gate_link(FIRST))).status == "first_recorded"
    await store.stop()

    restarted = await _started(db_path)  # a NEW instance on the same file
    changed = await restarted.check_and_record(REF, _gate_link(OTHER))

    assert (changed.status, changed.first_sha256, changed.observed_sha256) == ("changed", FIRST, OTHER)
    await restarted.stop()


async def test_references_are_independent(db_path: Path) -> None:
    store = await _started(db_path)
    base = await store.check_and_record(REF, _gate_link(FIRST))
    assert base.status == "first_recorded"  # premise: the base reference holds FIRST

    other_ref = await store.check_and_record("receipt-2", _gate_link(OTHER))
    other_kind = await store.check_and_record(REF, _review_link(OTHER))
    other_candidate = await store.check_and_record(REF, _gate_link(OTHER, candidate=ANOTHER_CANDIDATE))

    # each differs from the base only in one key part, and each is its own first digest, never a change
    assert [check.status for check in (other_ref, other_kind, other_candidate)] == ["first_recorded"] * 3
    assert [check.first_sha256 for check in (other_ref, other_kind, other_candidate)] == [OTHER] * 3
    # and none of them touched the base reference
    again = await store.check_and_record(REF, _gate_link(FIRST))
    assert (again.status, again.first_sha256) == ("unchanged", FIRST)
    assert _counts(db_path) == (4, 0)
    await store.stop()


# ---------------------------------------------------------------------------
# Refusals and failure tiers
# ---------------------------------------------------------------------------


async def test_untrusted_or_malformed_input_is_refused_before_any_write(db_path: Path) -> None:
    store = await _started(db_path, clock=lambda: 1.0)

    # a link that is not ``present`` with a digest is not trusted, even when it carries one
    refused_with_digest = EvidenceLink("gate_receipt", "refused", "gate_receipt_tree_mismatch", CANDIDATE, THIRD)
    malformed_with_digest = EvidenceLink("gate_receipt", "unavailable", "gate_receipt_malformed", CANDIDATE, THIRD)
    present_without_digest = EvidenceLink("gate_receipt", "present", "gate_receipt_bound", CANDIDATE, "")
    for untrusted in (refused_with_digest, malformed_with_digest, present_without_digest):
        with pytest.raises(ValueError) as excinfo:
            await store.check_and_record(REF, untrusted)
        assert excinfo.value.args == ("repair_evidence_link_untrusted",), untrusted

    # anything that is not exactly an EvidenceLink is refused, however link-shaped
    for not_a_link in (
        None,
        {"kind": "gate_receipt"},
        _NotALink(),
        _LinkSubclass("gate_receipt", "present", "gate_receipt_bound", CANDIDATE, FIRST),
    ):
        with pytest.raises(TypeError) as type_error:
            await store.check_and_record(REF, not_a_link)  # type: ignore[arg-type]
        assert type_error.value.args == ("repair_evidence_link_required",), not_a_link

    # a reference must be an owned id
    for bad_ref in ("", "-x", "a/b", "a b", "a" * 129, "a\n", None, 5, b"receipt-1"):
        with pytest.raises(ValueError) as ref_error:
            await store.check_and_record(bad_ref, _gate_link())  # type: ignore[arg-type]
        assert ref_error.value.args == ("repair_evidence_ref_invalid",), bad_ref

    assert _counts(db_path) == (0, 0)
    # premise: the store, the reference and the link are fine; only the refused inputs above were at fault
    assert (await store.check_and_record(REF, _gate_link())).status == "first_recorded"
    await store.stop()


@pytest.mark.parametrize(
    ("table", "sql", "params"),
    [
        pytest.param(
            FIRST_TABLE, f"UPDATE {FIRST_TABLE} SET first_sha256 = ?", ("9" * 64,), id="update-first",
        ),
        pytest.param(FIRST_TABLE, f"DELETE FROM {FIRST_TABLE}", (), id="delete-first"),
        pytest.param(
            FIRST_TABLE,
            f"INSERT OR REPLACE INTO {FIRST_TABLE} (candidate_digest, evidence_kind, evidence_ref, "
            "first_sha256, schema_version, recorded_at) VALUES (?, ?, ?, ?, 1, 99.0)",
            (CANDIDATE, "gate_receipt", REF, "9" * 64),
            id="replace-first",
        ),
        pytest.param(
            CHANGES_TABLE, f"UPDATE {CHANGES_TABLE} SET first_changed_sha256 = ?", ("9" * 64,), id="update-change",
        ),
        pytest.param(CHANGES_TABLE, f"DELETE FROM {CHANGES_TABLE}", (), id="delete-change"),
        pytest.param(
            CHANGES_TABLE,
            f"INSERT OR REPLACE INTO {CHANGES_TABLE} (candidate_digest, evidence_kind, evidence_ref, "
            "first_changed_sha256, schema_version, observed_at) VALUES (?, ?, ?, ?, 1, 99.0)",
            (CANDIDATE, "gate_receipt", REF, "9" * 64),
            id="replace-change",
        ),
    ],
)
async def test_database_refuses_update_delete_and_replace(
    db_path: Path, table: str, sql: str, params: tuple[Any, ...],
) -> None:
    store = await _started(db_path, clock=_ticking_clock())
    await store.check_and_record(REF, _gate_link(FIRST))
    await store.check_and_record(REF, _gate_link(OTHER))
    await store.stop()
    before = _rows(db_path, table)
    assert len(before) == 1  # premise: the row exists in BOTH tables, so the statement has something to hit

    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="repair_evidence_immutable"):
            conn.execute(sql, params)

    assert _rows(db_path, table) == before  # the row is unchanged


_PERMISSIVE_SCHEMA = """
CREATE TABLE repair_evidence_first_digests (
    candidate_digest TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    first_sha256 TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    recorded_at REAL NOT NULL,
    PRIMARY KEY (candidate_digest, evidence_kind, evidence_ref)
) WITHOUT ROWID;
CREATE TABLE repair_evidence_digest_changes (
    candidate_digest TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    first_changed_sha256 TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    observed_at REAL NOT NULL,
    PRIMARY KEY (candidate_digest, evidence_kind, evidence_ref),
    FOREIGN KEY (candidate_digest, evidence_kind, evidence_ref)
        REFERENCES repair_evidence_first_digests (candidate_digest, evidence_kind, evidence_ref)
) WITHOUT ROWID;
"""
_FIRST_ROW = f"INSERT INTO {FIRST_TABLE} VALUES (?, 'gate_receipt', ?, ?, ?, 1.0)"
_CHANGE_ROW = f"INSERT INTO {CHANGES_TABLE} VALUES (?, 'gate_receipt', ?, ?, ?, 2.0)"


@pytest.mark.parametrize(
    "stored_rows",
    [
        pytest.param([(_FIRST_ROW, (CANDIDATE, REF, FIRST, 2))], id="first-row-schema-version-2"),
        pytest.param([(_FIRST_ROW, (CANDIDATE, REF, "Z" * 64, 1))], id="first-row-digest-not-hex"),
        pytest.param(
            [(_FIRST_ROW, (CANDIDATE, REF, FIRST, 1)), (_CHANGE_ROW, (CANDIDATE, REF, FIRST, 1))],
            id="change-row-equal-to-first",
        ),
    ],
)
async def test_unvalidated_stored_row_is_an_integrity_error(
    db_path: Path, stored_rows: list[tuple[str, tuple[Any, ...]]], caplog: pytest.LogCaptureFixture,
) -> None:
    # A file this module's own schema could never have produced: same names, columns and primary keys,
    # WITHOUT ROWID, but no CHECKs (the foreign key still has its parent key). The store's
    # ``CREATE TABLE IF NOT EXISTS`` leaves it alone, so only the read-side validation can refuse it.
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(_PERMISSIVE_SCHEMA)
        for statement, values in stored_rows:
            conn.execute(statement, values)
        conn.commit()
    before = _counts(db_path)
    store = await _started(db_path, clock=lambda: 3.0)

    with caplog.at_level(logging.ERROR, logger=STORE_LOGGER):
        with pytest.raises(RepairEvidenceIntegrityError) as excinfo:
            await store.check_and_record(REF, _gate_link(OTHER))

    assert excinfo.value.args == ("repair_evidence_integrity",)
    assert isinstance(excinfo.value, ValueError)
    errors = [r for r in caplog.records if r.name == STORE_LOGGER and r.levelno == logging.ERROR]
    assert len(errors) == 1 and "no longer validates" in errors[0].getMessage()
    assert _counts(db_path) == before  # the observation was refused and nothing was recorded
    await store.stop()


async def test_failed_write_commits_nothing(db_path: Path) -> None:
    factory = _FaultyFactory()
    store = await _started(db_path, connection_factory=factory, clock=lambda: 1.0)
    factory.arm(FIRST_INSERT, sqlite3.OperationalError("injected write failure"))

    with pytest.raises(sqlite3.OperationalError, match="injected write failure"):
        await store.check_and_record(REF, _gate_link())

    assert factory.fired == 1  # premise: the failure arrived AFTER the INSERT ran on the real connection
    assert _counts(db_path) == (0, 0)  # its uncommitted row died with the connection
    factory.disarm()
    retried = await store.check_and_record(REF, _gate_link())  # and the file is not left locked
    assert retried.status == "first_recorded"
    assert _counts(db_path) == (1, 0)
    await store.stop()


async def test_cancelled_write_commits_nothing(db_path: Path) -> None:
    # A REAL task.cancel() while the call is parked after the real INSERT has run, before any COMMIT.
    factory = _FaultyFactory()
    store = await _started(db_path, connection_factory=factory, clock=lambda: 1.0)
    factory.park_after_statement(FIRST_INSERT)
    task = asyncio.create_task(store.check_and_record(REF, _gate_link()))

    await asyncio.wait_for(factory.parked.wait(), 5)
    assert factory.parked.is_set()  # premise: the INSERT ran on the real connection and the call parked
    assert not task.done()  # premise: the call is still in flight, not failed
    assert factory.commit_future is None  # premise: no COMMIT was ever started
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.cancelled()
    assert _counts(db_path) == (0, 0)  # its uncommitted row died with the connection
    factory.unpark()
    retried = await asyncio.wait_for(store.check_and_record(REF, _gate_link()), 5)  # the lock is free again
    assert retried.status == "first_recorded"
    assert _counts(db_path) == (1, 0)
    await store.stop()


@pytest.mark.parametrize("mode", ["first", "change"])
async def test_cancel_after_commit_queued_waits_for_cleanup_and_may_record(db_path: Path, mode: str) -> None:
    # B1, R2-1, R2-3, R3-1: a REAL task.cancel() with the COMMIT queued behind a held worker thread,
    # observed on the connection's real worker queue (the spy), not only on the proxy. The cancel
    # reaches the COMMIT future production awaits (no shield). The close is queued behind the COMMIT,
    # and a call that is cancelled once stays pending until the worker is released and that cleanup
    # has run. That pending-until-cleanup behaviour is single-cancel behaviour (an implementation
    # note of ``check_and_record``, observed with aiosqlite 0.22.1), NOT the contract: the contract
    # only promises that CancelledError propagates and the outcome is unknown. This test does not
    # cancel repeatedly. The outcome (recorded) proves the COMMIT queued before the cancel is the
    # one that ran.
    factory = _FaultyFactory()
    store = await _started(db_path, connection_factory=factory, clock=lambda: 1.0)
    if mode == "change":
        assert (await store.check_and_record(REF, _gate_link(FIRST))).status == "first_recorded"
    before = _counts(db_path)
    assert before == ((0, 0) if mode == "first" else (1, 0))  # premise: the starting rows
    observed = FIRST if mode == "first" else OTHER
    factory.park_commit()
    task = asyncio.create_task(store.check_and_record(REF, _gate_link(observed)))

    try:
        await asyncio.wait_for(factory.parked.wait(), 5)
        assert await asyncio.to_thread(factory.worker_parked.wait, 5)  # premise: the worker is held
        assert factory.commit_future is not None  # premise: the COMMIT was queued
        assert not factory.commit_future.done()  # premise: ...and is pending behind the blocker
        assert not task.done()  # premise: the call is still in flight
        assert _counts(db_path) == before  # premise: the COMMIT has not run
        labels = factory.queued_labels()
        last_blocker = len(labels) - 1 - labels[::-1].index("blocker")
        assert "execute" in labels[:last_blocker]  # premise: the spy sees this connection's statements
        # the real sqlite3 COMMIT was queued after the blocker and BEFORE the cancel; no close yet
        assert factory.queued_tail() == ["blocker", "commit"]
        task.cancel()
        _, pending = await asyncio.wait({task}, timeout=0.2)
        assert task in pending  # single cancel: the close is queued behind the COMMIT
        assert factory.commit_future.cancelled()  # the awaited COMMIT future got the cancel: no shield
        tail_items = factory.queued[len(factory.queued) - len(factory.queued_tail()):]
        commit_references = [reference for label, reference in tail_items if label == "commit"]
        assert len(commit_references) == 1 and commit_references[0] is not None
        queued_commit = commit_references[0]()  # weak: the spy must not keep the future (and its cursor) alive
        assert queued_commit is not None  # still referenced by the cancelled call's pending cleanup, so it resolves
        # The referent is the future aiosqlite's ``_execute`` queued for that COMMIT, not ``factory.commit_future``
        # (the Task wrapping ``Connection.commit()``); cancelling that Task cancels the future it waits on.
        assert queued_commit.cancelled()  # the cancel reached the real queued COMMIT's future
        assert factory.queued_tail() == ["blocker", "commit", "close"]
        assert _counts(db_path) == before  # the COMMIT still has not run
    finally:
        factory.release.set()

    done, _ = await asyncio.wait({task}, timeout=5)
    assert task in done
    assert task.cancelled()  # propagated, not swallowed
    with pytest.raises(asyncio.CancelledError):
        await task
    # no COMMIT was queued after the cancel (``stop()`` queues its own item after the close)
    assert factory.queued_tail()[:3] == ["blocker", "commit", "close"]
    assert factory.queued_tail().count("commit") == 1
    factory.unpark()
    if mode == "first":
        assert _rows(db_path, FIRST_TABLE) == [(CANDIDATE, "gate_receipt", REF, FIRST, 1, 1.0)]
        assert _rows(db_path, CHANGES_TABLE) == []
        retry_a = await asyncio.wait_for(store.check_and_record(REF, _gate_link(FIRST)), 5)
        assert (retry_a.status, retry_a.first_sha256) == ("unchanged", FIRST)
        retry_b = await asyncio.wait_for(store.check_and_record(REF, _gate_link(OTHER)), 5)
        assert (retry_b.status, retry_b.first_sha256, retry_b.observed_sha256) == ("changed", FIRST, OTHER)
    else:
        assert _rows(db_path, FIRST_TABLE) == [(CANDIDATE, "gate_receipt", REF, FIRST, 1, 1.0)]
        assert _rows(db_path, CHANGES_TABLE) == [(CANDIDATE, "gate_receipt", REF, OTHER, 1, 1.0)]
        retry_b = await asyncio.wait_for(store.check_and_record(REF, _gate_link(OTHER)), 5)
        assert (retry_b.status, retry_b.first_sha256) == ("changed", FIRST)
        retry_a = await asyncio.wait_for(store.check_and_record(REF, _gate_link(FIRST)), 5)
        assert (retry_a.status, retry_a.first_sha256) == ("changed", FIRST)
    await store.stop()


_VALID_COLUMNS: dict[str, Any] = {
    "candidate_digest": CANDIDATE,
    "evidence_kind": "gate_receipt",
    "evidence_ref": REF,
    "first_sha256": FIRST,
    "first_changed_sha256": FIRST,
}
_DIGEST_VALUES = ["0" * 64 + "\x00x", "0" * 32 + "\x00" + "0" * 31, b"0" * 64, "A" * 64]
_REF_VALUES = ["-x", ".x", ":x", "a\x00b", "", "a" * 129, "é", b"abc"]
_KIND_VALUES = ["gate_receipt\x00x", b"gate_receipt"]
# R2-2: numbers a TEXT-affinity column would have converted to text before its CHECK ran
# (value, its string twin or None).
_NUMERIC_VALUES: list[tuple[object, str | None]] = [
    (9, "9"),
    (9.0, "9.0"),
    (True, "1"),
    (2**63 - 1, "9223372036854775807"),
    (-1.7976931348623157e308, None),
    (float("inf"), None),
]
_NUMERIC_TWINS: dict[tuple[type, object], str | None] = {(type(v), v): twin for v, twin in _NUMERIC_VALUES}
_COLUMN_SHAPES = {
    "candidate_digest": "candidate",
    "first_sha256": "sha256",
    "first_changed_sha256": "sha256",
    "evidence_ref": "ref",
    "evidence_kind": "kind",
}


def _refused_by_python(column: str, value: object) -> bool:
    """True when the Python validators refuse ``value`` for ``column`` (the rule the CHECK must mirror)."""
    if column == "evidence_ref":
        return not is_evidence_ref(value)
    if column == "evidence_kind":
        return value not in {"gate_receipt", "review_set"}  # production's kind rule: membership only (R5-3)
    return not is_sha256_hex(value)


def _accepted_by_python(column: str, value: object) -> bool:
    if column == "evidence_ref":
        return is_evidence_ref(value)
    if column == "evidence_kind":
        return value in {"gate_receipt", "review_set"}  # production's kind rule: membership only (R5-3)
    return is_sha256_hex(value)


def _validator_cases() -> list[Any]:
    cases: list[Any] = []
    for table, prefix, digest_columns in (
        (FIRST_TABLE, "repair_evidence_first", ("candidate_digest", "first_sha256")),
        (CHANGES_TABLE, "repair_evidence_change", ("candidate_digest", "first_changed_sha256")),
    ):
        for column in digest_columns:
            shape = "candidate" if column == "candidate_digest" else "sha256"
            for index, value in enumerate(_DIGEST_VALUES):
                cases.append(pytest.param(
                    table, column, value, f"{prefix}_{shape}_shape", "off", id=f"{prefix}-{column}-{index}",
                ))
        for index, value in enumerate(_REF_VALUES):
            cases.append(pytest.param(
                table, "evidence_ref", value, f"{prefix}_ref_shape", "off", id=f"{prefix}-ref-{index}",
            ))
        for index, value in enumerate(_KIND_VALUES):
            cases.append(pytest.param(
                table, "evidence_kind", value, f"{prefix}_kind_shape", "off", id=f"{prefix}-kind-{index}",
            ))
        for column in (*digest_columns, "evidence_ref", "evidence_kind"):
            for index, (number, _twin) in enumerate(_NUMERIC_VALUES):
                for foreign_keys in ("off", "on"):
                    cases.append(pytest.param(
                        table, column, number, f"{prefix}_{_COLUMN_SHAPES[column]}_shape", foreign_keys,
                        id=f"{prefix}-{column}-num{index}-fk{foreign_keys}",
                    ))
        for column in (*digest_columns, "evidence_ref", "evidence_kind"):
            # R3-3: SQLite binds NaN as NULL, so no CHECK is named; the NOT NULL constraint refuses it
            cases.append(pytest.param(
                table, column, float("nan"), f"NOT NULL constraint failed: {table}.{column}", "off",
                id=f"{prefix}-{column}-nan-fkoff",
            ))
    return cases


def _insert_sql(table: str) -> tuple[str, tuple[str, ...]]:
    sha_column = "first_sha256" if table == FIRST_TABLE else "first_changed_sha256"
    time_column = "recorded_at" if table == FIRST_TABLE else "observed_at"
    columns = ("candidate_digest", "evidence_kind", "evidence_ref", sha_column)
    sql = (  # noqa: S608 -- ``table`` and the columns are this module's own literals
        f"INSERT INTO {table} ({', '.join(columns)}, schema_version, {time_column}) VALUES (?, ?, ?, ?, 1, 1.0)"
    )
    return sql, columns


@pytest.mark.parametrize(("table", "column", "value", "constraint", "foreign_keys"), _validator_cases())
async def test_database_refuses_values_the_validators_refuse(
    db_path: Path, table: str, column: str, value: object, constraint: str, foreign_keys: str,
) -> None:
    """Only the 20 numeric ``evidence_ref`` cases that TEXT affinity would coerce to a valid reference
    (``9``, ``9.0``, ``True``, ``2**63 - 1``, ``inf`` as ``"Inf"``; both tables; foreign keys off and on)
    discriminate the round-2 change; the other 76 numeric cases also passed before it and stay as regression pins."""
    store = await _started(db_path)
    await store.stop()
    sql, columns = _insert_sql(table)
    valid = {name: _VALID_COLUMNS[name] for name in columns}
    assert column in valid  # premise: the case attacks a column of this table
    assert _refused_by_python(column, value)  # premise: the Python rule refuses this value
    assert _accepted_by_python(column, valid[column])  # premise: and accepts the valid one
    attack = {**valid, column: value}

    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        if foreign_keys == "on":
            conn.execute("PRAGMA foreign_keys=ON")  # first statement: a no-op inside a transaction
            assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
            if table == CHANGES_TABLE:
                # parents for every key this case inserts, so only the mirrored CHECK can refuse the attack
                twin = _NUMERIC_TWINS.get((type(value), value)) if column == "evidence_ref" else None
                parent_sql, parent_columns = _insert_sql(FIRST_TABLE)
                parent_refs = [REF, *([twin] if twin is not None else []), "9", "a" * 128]
                for parent_ref in dict.fromkeys(parent_refs):
                    parent = {**_VALID_COLUMNS, "evidence_ref": parent_ref}
                    conn.execute(parent_sql, tuple(parent[name] for name in parent_columns))
        else:
            # the change table's foreign key is off here, so only its mirrored CHECK can refuse
            assert conn.execute("PRAGMA foreign_keys").fetchone() == (0,)
        before = conn.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608
        with pytest.raises(sqlite3.IntegrityError) as excinfo:
            conn.execute(sql, tuple(attack[name] for name in columns))
        assert constraint in str(excinfo.value)
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == before  # noqa: S608

        # premise: the same INSERT with the valid value succeeds, and so do the reference boundaries
        conn.execute(sql, tuple(valid[name] for name in columns))
        if column == "evidence_ref":
            for boundary in ("9", "a" * 128):
                assert _accepted_by_python("evidence_ref", boundary)
                conn.execute(sql, tuple({**valid, "evidence_ref": boundary}[name] for name in columns))
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (3,)  # noqa: S608
        else:
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (1,)  # noqa: S608


class _Text(str):
    """A ``str`` subclass: SQLite binds it as the plain text it contains (R4-2)."""


@pytest.mark.parametrize(
    ("table", "column"),
    [
        pytest.param(table, column, id=f"{table}-{column}")
        for table, columns in (
            (FIRST_TABLE, ("candidate_digest", "evidence_kind", "evidence_ref", "first_sha256")),
            (CHANGES_TABLE, ("candidate_digest", "evidence_kind", "evidence_ref", "first_changed_sha256")),
        )
        for column in columns
    ],
)
async def test_a_str_subclass_is_stored_as_plain_text_and_passes_the_stored_text_rules(
    db_path: Path, table: str, column: str,
) -> None:
    """R4-2, R5-3: SQLite cannot see the Python object type, so the engine admits a ``str`` subclass as the plain
    text it contains. The exact-``str`` rule is for references and digests (``check_and_record``'s, #9, not the
    engine's); production's kind rule is membership of the two literals, which a subclass equal to one satisfies."""
    store = await _started(db_path)
    await store.stop()
    sql, columns = _insert_sql(table)
    valid = {name: _VALID_COLUMNS[name] for name in columns}
    assert column in valid  # premise: the case binds a column of this table
    subclass = _Text(valid[column])
    if column == "evidence_kind":
        # premise (the opposite one): the kind rule is membership, so the real constructor accepts the subclass
        assert not _refused_by_python(column, subclass)
        for kind in ("gate_receipt", "review_set"):
            link = EvidenceLink(_Text(kind), "present", f"{kind}_bound", "0" * 64, "1" * 64)
            assert link.kind == kind
    else:
        assert _refused_by_python(column, subclass)  # premise: the exact-``str`` rule refuses the subclass
    assert _accepted_by_python(column, valid[column])  # premise: and accepts the plain text

    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        # the change table's foreign key is off here, so only the mirrored CHECKs act
        assert conn.execute("PRAGMA foreign_keys").fetchone() == (0,)
        conn.execute(sql, tuple({**valid, column: subclass}[name] for name in columns))
        stored_type, stored = conn.execute(f"SELECT typeof({column}), {column} FROM {table}").fetchone()  # noqa: S608

    assert stored_type == "text"
    assert type(stored) is str
    assert stored == str(subclass) == valid[column]
    assert _accepted_by_python(column, stored)  # the stored text passes the Python rule for its column


@pytest.mark.parametrize("bad_now", [float("nan"), float("inf"), "1"], ids=["nan", "inf", "str"])
async def test_invalid_clock_refuses_the_write(db_path: Path, bad_now: object) -> None:
    store = await _started(db_path, clock=lambda: bad_now)  # type: ignore[arg-type,return-value]

    with pytest.raises(RepairEvidenceStoreUnavailable) as excinfo:
        await store.check_and_record(REF, _gate_link())

    assert excinfo.value.args == ("repair_evidence_clock_invalid",)
    assert _counts(db_path) == (0, 0)
    # premise: the same observation is recorded by a store with a sane clock, so the refusal was the clock's
    sane = await _started(db_path, clock=lambda: 1.0)
    assert (await sane.check_and_record(REF, _gate_link())).status == "first_recorded"
    await sane.stop()
    await store.stop()


async def test_injected_factory_is_used_and_close_failure_is_logged(
    db_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    factory = _FaultyFactory()
    store = await _started(db_path, connection_factory=factory, clock=lambda: 1.0)
    assert factory.connect_paths == [str(db_path)]  # start() connected through the injected factory
    factory.fail_close = True  # the real connection is closed, THEN close raises

    with caplog.at_level(logging.WARNING, logger=STORE_LOGGER):
        check = await store.check_and_record(REF, _gate_link())

    assert check.status == "first_recorded"  # the operation's own result stands
    assert factory.connect_paths == [str(db_path)] * 2  # one connection per operation, every one injected
    assert _counts(db_path) == (1, 0)  # and its work was committed before the close failed
    warnings = [r for r in caplog.records if r.name == STORE_LOGGER and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "closing a repair evidence connection failed" in warnings[0].getMessage()
    assert warnings[0].exc_info is not None
    await store.stop()


# ---------------------------------------------------------------------------
# assess_candidate_evidence: the producer -> ledger -> completion seam
# ---------------------------------------------------------------------------


async def test_assess_crosses_verifier_ledger_and_completion_across_restart(
    gate: ModuleType, repo: Path, db_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    candidate = _candidate(repo)
    receipt = _real_receipt(gate, repo)  # written by the REAL gate producer
    reviews = _reviews(candidate)
    receipt_digest = hashlib.sha256(receipt).hexdigest()

    store = await _started(db_path)
    first = await _assess(store, candidate, receipt, reviews)
    assert (first.completeness.complete, first.completeness.reason) == (True, "evidence_complete")
    assert [(c.kind, c.status) for c in first.checks] == [("gate_receipt", "first_recorded"), ("review_set", "first_recorded")]
    # what the ledger holds is exactly what the verifier derived from the real bytes
    assert first.checks[0].first_sha256 == first.links[0].evidence_sha256 == receipt_digest
    assert first.checks[1].first_sha256 == first.links[1].evidence_sha256
    await store.stop()

    restarted = await _started(db_path)  # a NEW instance on the same file
    again = await _assess(restarted, candidate, receipt, reviews)
    assert (again.completeness.complete, again.completeness.reason) == (True, "evidence_complete")
    assert [check.status for check in again.checks] == ["unchanged", "unchanged"]

    # ``finished_at`` is not read by the binder, so the edited receipt still binds (S1a precedent)...
    edited = _mutate(receipt, "finished_at", "2026-10-11T23:59:59Z")
    bound = verify_gate_receipt(candidate, edited)
    assert (bound.status, bound.reason) == ("present", "gate_receipt_bound")
    assert bound.evidence_sha256 != receipt_digest
    # ...so the ledger is what catches it, under the SAME reference
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=STORE_LOGGER):
        changed = await _assess(restarted, candidate, edited, reviews)
    assert changed.completeness.complete is False
    assert changed.completeness.reason == "evidence_changed"
    assert [check.status for check in changed.checks] == ["changed", "unchanged"]
    assert changed.checks[0].first_sha256 == receipt_digest
    assert changed.checks[0].observed_sha256 == hashlib.sha256(edited).hexdigest()
    warnings = [r.getMessage() for r in caplog.records if r.name == STORE_LOGGER and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "gate_receipt evidence gate-run-1" in warnings[0]
    assert "has a recorded digest change" in warnings[0]

    # the same edited receipt under a NEW reference is new evidence: complete
    fresh = await _assess(restarted, candidate, edited, reviews, receipt_ref="gate-run-2")
    assert (fresh.completeness.complete, fresh.completeness.reason) == (True, "evidence_complete")
    assert [check.status for check in fresh.checks] == ["first_recorded", "unchanged"]
    assert _recorded_refs(db_path) == {
        ("gate_receipt", "gate-run-1"), ("gate_receipt", "gate-run-2"), ("review_set", "review-round-1"),
    }
    assert _counts(db_path) == (3, 1)
    await restarted.stop()


async def test_assess_does_not_record_non_present_links(repo: Path, db_path: Path) -> None:
    candidate = _candidate(repo)
    store = await _started(db_path)

    assessment = await _assess(store, candidate, None, _reviews(candidate))  # no receipt at all

    assert [(link.kind, link.status, link.reason) for link in assessment.links] == [
        ("gate_receipt", "unavailable", "gate_receipt_absent"),
        ("review_set", "present", "review_set_bound"),
    ]
    assert [(check.kind, check.status) for check in assessment.checks] == [("review_set", "first_recorded")]
    assert (assessment.completeness.complete, assessment.completeness.reason) == (False, "evidence_not_present")
    assert assessment.completeness.missing_kinds == ("gate_receipt",)
    assert _recorded_refs(db_path) == {("review_set", "review-round-1")}  # the absent receipt left no row
    await store.stop()


async def test_assess_refuses_relabelled_self_review(
    gate: ModuleType, repo: Path, db_path: Path,
) -> None:
    candidate = _candidate(repo)
    receipt = _real_receipt(gate, repo)
    store = await _started(db_path)
    # premise: the honest, independent review set completes and is recorded under its own reference
    honest = await _assess(store, candidate, receipt, _reviews(candidate))
    assert honest.completeness.complete is True

    # the builder reviews its own work but labels it ``decoy``, to slip past the independence check
    decoy = [_Review(review_attempt_id="attempt-9", reviewer_id="builder", assignee_id="decoy", reviewed_tree=candidate.tree)]
    relabelled = await _assess(
        store, candidate, receipt, decoy, review_ref="review-round-2", required_reviewers=1,
    )

    assert [(link.kind, link.status, link.reason) for link in relabelled.links][1] == (
        "review_set", "refused", "review_assignee_mismatch",
    )
    assert (relabelled.completeness.complete, relabelled.completeness.reason) == (False, "evidence_not_present")
    assert [(check.kind, check.evidence_ref) for check in relabelled.checks] == [("gate_receipt", "gate-run-1")]
    assert ("review_set", "review-round-2") not in _recorded_refs(db_path)  # nothing recorded for it
    await store.stop()


async def test_assess_argument_errors_raise_before_recording(
    gate: ModuleType, repo: Path, db_path: Path,
) -> None:
    candidate = _candidate(repo)
    receipt = _real_receipt(gate, repo)  # present evidence, so a write WOULD happen if an argument were not checked first
    store = await _started(db_path)

    for override, message in (
        ({"receipt_ref": ""}, "repair_evidence_ref_invalid"),
        ({"receipt_ref": "a b"}, "repair_evidence_ref_invalid"),
        ({"review_ref": "-x"}, "repair_evidence_ref_invalid"),
        ({"review_ref": None}, "repair_evidence_ref_invalid"),
        ({"authority_class": "other"}, "authority_class_invalid"),
        ({"expected_assignee": ""}, "review_expected_assignee_invalid"),
    ):
        with pytest.raises(ValueError) as excinfo:
            await _assess(store, candidate, receipt, _reviews(candidate), **override)
        assert excinfo.value.args == (message,), override
        assert _counts(db_path) == (0, 0), override

    # premise: the unmodified call completes and records both references
    complete = await _assess(store, candidate, receipt, _reviews(candidate))
    assert complete.completeness.complete is True
    assert _counts(db_path) == (2, 0)
    await store.stop()


# ---------------------------------------------------------------------------
# Declaration and wiring
# ---------------------------------------------------------------------------


def test_store_is_declared() -> None:
    declaration = load_default_store_registry().get("cognitive.repair-evidence")

    assert declaration is not None
    assert declaration.owner_symbol == "RepairEvidenceLinkStore"
    assert declaration.canonical_path == "repair_evidence.db"
    assert declaration.lifecycle_owner == "unowned"
    # the declaration names this very class
    assert (RepairEvidenceLinkStore.__module__, RepairEvidenceLinkStore.__name__) == (
        declaration.owner_module, declaration.owner_symbol,
    )


_STORE_MODULE = "repair_evidence_store"
_STORE_CLASS = "RepairEvidenceLinkStore"


def _store_references(tree: ast.AST) -> list[str]:
    """Every construction of the store class and every import of its module found in ``tree``."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name == _STORE_CLASS:
                found.append(f"call at line {node.lineno}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[-1] == _STORE_MODULE or any(a.name == _STORE_MODULE for a in node.names):
                found.append(f"import-from at line {node.lineno}")
        elif isinstance(node, ast.Import):
            if any(a.name.split(".")[-1] == _STORE_MODULE for a in node.names):
                found.append(f"import at line {node.lineno}")
    return found


def test_nothing_in_src_constructs_the_store() -> None:
    """Pins D5: this slice adds the store and its consumer, but nothing constructs or starts it.

    AD-1299 S2 (admission) constructs and starts ``RepairEvidenceLinkStore`` and changes this test
    deliberately. The scan is AST-based: a string that merely names the class (as the store
    declaration does) is not a reference.
    """
    own = SRC_PROBOS / "cognitive" / "repair_evidence_store.py"
    assert own.is_file()  # premise: the module the scan excludes is where the exclusion expects it

    # the scanner is not vacuous: it flags each shape it exists to forbid, and not a bare string
    assert _store_references(ast.parse("RepairEvidenceLinkStore('x.db')"))
    assert _store_references(ast.parse("registry.RepairEvidenceLinkStore('x.db')"))
    assert _store_references(ast.parse("from probos.cognitive.repair_evidence_store import X"))
    assert _store_references(ast.parse("from probos.cognitive import repair_evidence_store"))
    assert _store_references(ast.parse("import probos.cognitive.repair_evidence_store as store"))
    assert _store_references(ast.parse("owner_symbol = 'RepairEvidenceLinkStore'")) == []

    others = [path for path in SRC_PROBOS.rglob("*.py") if path != own]
    assert len(others) > 1  # premise: the glob reached the tree
    offenders: dict[str, list[str]] = {}
    for path in others:
        raw = path.read_bytes()
        if _STORE_CLASS.encode() not in raw and _STORE_MODULE.encode() not in raw:
            continue  # a file that never names either cannot call or import it: not worth a parse
        references = _store_references(ast.parse(raw, filename=str(path)))
        if references:
            offenders[path.relative_to(SRC_PROBOS).as_posix()] = references
    assert offenders == {}


# ---------------------------------------------------------------------------
# TrustedDigestCheck construction (Amendment A2)
# ---------------------------------------------------------------------------


def _check(status: object) -> TrustedDigestCheck:
    return TrustedDigestCheck(
        status=status,  # type: ignore[arg-type]
        candidate_digest=CANDIDATE,
        kind="gate_receipt",
        evidence_ref="ref",
        first_sha256=FIRST,
        observed_sha256=FIRST,
    )


@pytest.mark.parametrize(
    ("status", "changed"),
    [("first_recorded", False), ("unchanged", False), ("changed", True)],
)
def test_trusted_digest_check_valid_status_constructs_and_changed_only_for_changed(
    status: str, changed: bool,
) -> None:
    check = _check(status)

    assert check.status == status
    assert check.changed is changed


@pytest.mark.parametrize("bad_status", ["bogus", [], None])
def test_trusted_digest_check_invalid_status_raises_stable_value_error(bad_status: object) -> None:
    # An unhashable status ([]) used to reach `in _STATUSES` and raise a raw TypeError.
    with pytest.raises(ValueError, match="trusted_digest_check_invalid"):
        _check(bad_status)
