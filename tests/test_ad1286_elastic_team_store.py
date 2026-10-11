"""AD-1286 (#1333): ElasticTeamStore -- insert-only persistence, admission rules and SQLite-boundary immutability.

Real SQLite under ``tmp_path`` only (never the live vessel data directory). The store is exercised
through its public API; the immutability tests then open a RAW ``sqlite3`` connection with default
pragmas (no ``recursive_triggers``, no ``foreign_keys``) to prove the database itself refuses every
UPDATE, DELETE and replacing INSERT, and still accepts a genuinely new row.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from probos.cognitive import elastic_team_store as store_module
from probos.cognitive.elastic_team import (
    TeamSpecLookup,
    WorkerAttempt,
    WorkerAttemptOutcome,
    derive_worker_attempt_id,
)
from probos.cognitive.elastic_team_store import (
    ElasticTeamConflict,
    ElasticTeamIntegrityError,
    ElasticTeamStore,
    ElasticTeamStoreUnavailable,
)
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from tests.test_ad1286_elastic_team_contract import _PROFILE_A, _review_slot, _slot, _spec

_PROFILE_B = "b" * 64
_NEW_REF = "9" * 64
_NEW_ID = "wa-" + "9" * 64
_DIGEST = "d" * 64
_TABLES = ("elastic_team_specs", "elastic_worker_slots", "elastic_worker_attempts", "elastic_attempt_outcomes")
# The tables are WITHOUT ROWID (F1), so a snapshot is ordered by each table's primary key.
_PRIMARY_KEYS = {
    "elastic_team_specs": "spec_ref",
    "elastic_worker_slots": "spec_ref, slot_id",
    "elastic_worker_attempts": "worker_attempt_id",
    "elastic_attempt_outcomes": "worker_attempt_id",
}
_SPEC = _spec()
_SPEC_REF = _SPEC.content_ref()
# a spec whose ``analyse`` slot pins two execution profiles, so attempts can differ in profile
_TWO_PROFILE_SPEC = _spec(
    slots=[
        _slot(qualification={"qualification_ids": ["evidence_analysis"], "pinned_profile_refs": [_PROFILE_A, _PROFILE_B]}),
        _review_slot(),
    ]
)
_TWO_PROFILE_REF = _TWO_PROFILE_SPEC.content_ref()
# a spec whose ``review`` slot has max_attempts equal to its capacity (1)
_TIGHT_BUDGET_SPEC = _spec(
    slots=[_slot(), _review_slot(budget={"max_tokens": 100000, "max_wall_ms": 600000, "max_attempts": 1})]
)


class _Clock:
    def __init__(self, t: Any) -> None:
        self.t = t

    def __call__(self) -> Any:
        return self.t


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "elastic_teams.db"


def _new_store(tmp_path: Path, clock: Callable[[], Any] | None = None) -> ElasticTeamStore:
    return ElasticTeamStore(
        db_path=str(_db_path(tmp_path)),
        connection_factory=SQLiteConnectionFactory(),
        clock=clock or _Clock(1000.0),
    )


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[ElasticTeamStore]:
    opened = _new_store(tmp_path)
    await opened.start()
    try:
        yield opened
    finally:
        await opened.stop()


def _attempt(
    spec_ref: str,
    *,
    session_id: str = "session-parent",
    slot_id: str = "analyse",
    ordinal: int = 1,
    profile: str = _PROFILE_A,
    supersedes: str | None = None,
) -> WorkerAttempt:
    return WorkerAttempt(
        schema_version=1,
        worker_attempt_id=derive_worker_attempt_id(
            team_spec_ref=spec_ref, session_id=session_id, slot_id=slot_id, ordinal=ordinal
        ),
        team_spec_ref=spec_ref,
        session_id=session_id,
        slot_id=slot_id,
        ordinal=ordinal,
        execution_profile_ref=profile,
        supersedes_attempt_id=supersedes,
    )


def _failed(attempt: WorkerAttempt, *, at: float = 2000.0, code: str = "model_timeout") -> WorkerAttemptOutcome:
    return WorkerAttemptOutcome(
        worker_attempt_id=attempt.worker_attempt_id, terminal_status="failed", error_code=code, recorded_at=at
    )


def _cancelled(attempt: WorkerAttempt, *, at: float = 3000.0) -> WorkerAttemptOutcome:
    return WorkerAttemptOutcome(
        worker_attempt_id=attempt.worker_attempt_id,
        terminal_status="cancelled",
        error_code="operator_cancelled",
        recorded_at=at,
    )


def _succeeded(attempt: WorkerAttempt, *, at: float = 2000.0) -> WorkerAttemptOutcome:
    return WorkerAttemptOutcome(
        worker_attempt_id=attempt.worker_attempt_id, terminal_status="succeeded", error_code=None, recorded_at=at
    )


def _read_tables(raw: sqlite3.Connection, *tables: str) -> dict[str, list[tuple[Any, ...]]]:
    # Formerly ``ORDER BY rowid``: the tables are WITHOUT ROWID now (F1), so no rowid exists to order by.
    return {
        name: raw.execute(f"SELECT * FROM {name} ORDER BY {_PRIMARY_KEYS[name]}").fetchall()
        for name in (tables or _TABLES)
    }


def _snapshot(path: Path, *tables: str) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of the named tables (default: all four) read through a separate raw connection."""
    raw = sqlite3.connect(path)
    try:
        return _read_tables(raw, *tables)
    finally:
        raw.close()


def _tamper(path: Path, drop_trigger: str, statement: str, params: tuple[Any, ...]) -> None:
    """Defeat one guard trigger and rewrite a row, as a file-level attacker could (test 5 pattern)."""
    raw = sqlite3.connect(path)
    try:
        raw.execute(f"DROP TRIGGER {drop_trigger}")
        raw.execute(statement, params)
        raw.commit()
    finally:
        raw.close()


async def _populated_db(tmp_path: Path) -> Path:
    """Populate through the store: one spec; attempt 1 (failed); attempt 2 replaces it (cancelled)."""
    populating = _new_store(tmp_path)
    await populating.start()
    try:
        spec_ref = await populating.put_team_spec(_SPEC)
        first = await populating.record_attempt(_attempt(spec_ref, ordinal=1))
        await populating.record_attempt_outcome(_failed(first))
        second = await populating.record_attempt(
            _attempt(spec_ref, ordinal=2, supersedes=first.worker_attempt_id)
        )
        await populating.record_attempt_outcome(_cancelled(second))
    finally:
        await populating.stop()
    return _db_path(tmp_path)


_A1 = derive_worker_attempt_id(team_spec_ref=_SPEC_REF, session_id="session-parent", slot_id="analyse", ordinal=1)
_A2 = derive_worker_attempt_id(team_spec_ref=_SPEC_REF, session_id="session-parent", slot_id="analyse", ordinal=2)
_A3 = derive_worker_attempt_id(team_spec_ref=_SPEC_REF, session_id="session-parent", slot_id="analyse", ordinal=3)
_OTHER_SESSION_A1 = derive_worker_attempt_id(
    team_spec_ref=_SPEC_REF, session_id="session-other", slot_id="analyse", ordinal=1
)


# --------------------------------------------------------------------------------------
# 1. Lifecycle
# --------------------------------------------------------------------------------------

_OPERATIONS: list[Any] = [
    pytest.param(lambda s: s.put_team_spec(_SPEC), id="put_team_spec"),
    pytest.param(lambda s: s.get_team_spec(_SPEC_REF), id="get_team_spec"),
    pytest.param(lambda s: s.record_attempt(_attempt(_SPEC_REF)), id="record_attempt"),
    pytest.param(lambda s: s.get_attempt(_A1), id="get_attempt"),
    pytest.param(
        lambda s: s.list_slot_attempts(session_id="session-parent", team_spec_ref=_SPEC_REF, slot_id="analyse"),
        id="list_slot_attempts",
    ),
    pytest.param(lambda s: s.record_attempt_outcome(_failed(_attempt(_SPEC_REF))), id="record_attempt_outcome"),
    pytest.param(lambda s: s.get_attempt_outcome(_A1), id="get_attempt_outcome"),
]


@pytest.mark.parametrize("operation", _OPERATIONS)
async def test_operations_before_start_raise_unavailable(
    tmp_path: Path, operation: Callable[[ElasticTeamStore], Awaitable[Any]]
) -> None:
    never_started = _new_store(tmp_path)

    with pytest.raises(ElasticTeamStoreUnavailable, match="elastic_team_store_unavailable"):
        await operation(never_started)

    assert not _db_path(tmp_path).exists()


@pytest.mark.parametrize("operation", _OPERATIONS)
async def test_operations_after_stop_raise_unavailable(
    tmp_path: Path, operation: Callable[[ElasticTeamStore], Awaitable[Any]]
) -> None:
    stopped = _new_store(tmp_path)
    await stopped.start()
    await stopped.stop()

    with pytest.raises(ElasticTeamStoreUnavailable, match="elastic_team_store_unavailable"):
        await operation(stopped)


async def test_stop_is_idempotent(tmp_path: Path) -> None:
    never_started = _new_store(tmp_path)
    await never_started.stop()  # stopping a store that never started is a no-op
    reopened = _new_store(tmp_path)
    await reopened.start()
    try:
        await reopened.start()  # an idempotent start opens nothing more and keeps the data
        ref = await reopened.put_team_spec(_SPEC)
        assert await reopened.get_team_spec(ref) == _SPEC

        await reopened.stop()
        await reopened.stop()  # a second stop is a no-op

        with pytest.raises(ElasticTeamStoreUnavailable):
            await reopened.get_team_spec(ref)
        await reopened.start()  # restartable; the data survived the stop
        assert await reopened.get_team_spec(ref) == _SPEC
    finally:
        await reopened.stop()


@pytest.mark.parametrize("path", ["", None, 5, b"elastic.db"], ids=["empty", "none", "int", "bytes"])
def test_constructor_refuses_a_blank_or_non_string_path(path: Any) -> None:
    with pytest.raises(ValueError, match="elastic_team_store_path_invalid"):
        ElasticTeamStore(db_path=path)


def test_constructor_refuses_the_private_in_memory_database_name() -> None:
    """R3-3: every operation opens its own connection, so ``:memory:`` would be a different, empty database each time."""
    with pytest.raises(ValueError, match="elastic_team_store_path_invalid"):
        ElasticTeamStore(db_path=":memory:")


@pytest.mark.parametrize(
    "path",
    [
        "memory.db",
        "mode=memory-data/elastic_teams.db",
        "data/mode=memory/elastic_teams.db",
        "data/:memory:/elastic_teams.db",
    ],
    ids=["basename", "directory-with-equals", "nested-directory", "name-inside-a-longer-path"],
)
def test_constructor_accepts_an_ordinary_path_that_mentions_memory(path: str) -> None:
    """R4-1: only the exact name ``:memory:`` is special; a data directory called ``mode=memory-data`` is a file path."""
    assert ElasticTeamStore(db_path=path) is not None


async def test_default_connection_factory_opens_a_working_store(tmp_path: Path) -> None:
    defaulted = ElasticTeamStore(db_path=str(_db_path(tmp_path)))  # no factory, no clock: the defaults
    await defaulted.start()
    try:
        ref = await defaulted.put_team_spec(_SPEC)
        assert await defaulted.get_team_spec(ref) == _SPEC
    finally:
        await defaulted.stop()


class _NoCursor:
    async def fetchall(self) -> list[Any]:
        return []


class _FailingConnection:
    """A fake connection that fails while the store is applying its pragmas or schema."""

    def __init__(self, failure: BaseException) -> None:
        self.failure = failure
        self.closed = False

    async def execute(self, sql: str, parameters: Any = ()) -> _NoCursor:
        if "foreign_keys" in sql:
            raise self.failure
        return _NoCursor()

    async def executescript(self, sql_script: str) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


class _FakeFactory:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    async def connect(self, db_path: str) -> Any:
        return self.connection


class _BrokenBeginConnection:
    """A fake connection whose BEGIN fails and whose ROLLBACK then finds no open transaction."""

    def __init__(self, failure: BaseException) -> None:
        self.failure = failure
        self.statements: list[str] = []

    async def execute(self, sql: str, parameters: Any = ()) -> _NoCursor:
        self.statements.append(sql)
        if sql == "BEGIN IMMEDIATE":
            raise self.failure
        if sql == "ROLLBACK":
            raise sqlite3.OperationalError("cannot rollback - no transaction is active")
        return _NoCursor()

    async def executescript(self, sql_script: str) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.mark.parametrize(
    "failure", [RuntimeError("injected begin failure"), asyncio.CancelledError()], ids=["error", "cancellation"]
)
async def test_failed_write_propagates_the_original_error_when_rollback_has_nothing_to_undo(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, failure: BaseException
) -> None:
    connection = _BrokenBeginConnection(failure)
    fragile = ElasticTeamStore(db_path=str(_db_path(tmp_path)), connection_factory=_FakeFactory(connection))
    await fragile.start()

    with caplog.at_level(logging.DEBUG, logger="probos.cognitive.elastic_team_store"):
        with pytest.raises(type(failure)):
            await fragile.put_team_spec(_SPEC)

    assert "ROLLBACK" in connection.statements  # the store tried to undo the write ...
    assert [record for record in caplog.records if "found no open transaction" in record.getMessage()]
    with pytest.raises(type(failure)):  # ... and neither the swallowed rollback error nor the lock leaked
        await fragile.record_attempt(_attempt(_SPEC_REF))


class _FaultyConnection:
    """Delegates to a real connection and injects the faults a test asks for; the real one stays at ``inner``.

    ``fail_slot_insert``: the second ``elastic_worker_slots`` INSERT raises, so a spec write dies after BEGIN, the
    spec row and the first slot row. ``rollback``: ``"ok"``, ``"fails"``, or ``"gated"`` (sets ``entered``, then
    waits for ``release``). ``close``: ``"ok"``; ``"fails-after-release"`` (the real connection is closed first);
    ``"fails-holding"`` (raises and leaves the real connection OPEN, so the test must close ``inner`` itself);
    or ``"gated"`` (sets ``entered``, waits for ``release``, then closes).
    """

    def __init__(
        self,
        inner: Any,
        *,
        fail_slot_insert: bool = False,
        rollback: str = "ok",
        close: str = "ok",
        entered: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        self.inner = inner
        self.entered = entered if entered is not None else asyncio.Event()
        self.release = release if release is not None else asyncio.Event()
        self.close_calls = 0
        self._fail_slot_insert = fail_slot_insert
        self._rollback = rollback
        self._close = close
        self._slot_inserts = 0

    async def execute(self, sql: str, parameters: Any = ()) -> Any:
        if sql == "ROLLBACK":
            if self._rollback == "fails":
                raise RuntimeError("injected rollback failure")
            if self._rollback == "gated":
                self.entered.set()
                await self.release.wait()
        if self._fail_slot_insert and sql.startswith("INSERT INTO elastic_worker_slots"):
            self._slot_inserts += 1
            if self._slot_inserts == 2:
                raise RuntimeError("injected slot failure")
        return await self.inner.execute(sql, parameters)

    async def executescript(self, sql_script: str) -> None:
        await self.inner.executescript(sql_script)

    async def commit(self) -> None:
        await self.inner.commit()

    async def close(self) -> None:
        self.close_calls += 1
        if self._close == "gated":
            self.entered.set()
            await self.release.wait()
        elif self._close == "fails-holding":
            raise RuntimeError("injected close failure")
        await self.inner.close()
        if self._close == "fails-after-release":
            raise RuntimeError("injected close failure")


class _FaultyFactory:
    """Real connections wrapped in ``_FaultyConnection``; ``arm`` queues the faults of the NEXT connection opened.

    The connection ``start()`` opens is therefore a plain pass-through unless a test armed the factory first.
    """

    def __init__(self) -> None:
        self._queued: list[dict[str, Any]] = []
        self.connections: list[_FaultyConnection] = []

    def arm(self, **faults: Any) -> None:
        self._queued.append(faults)

    async def connect(self, db_path: str) -> _FaultyConnection:
        connection = _FaultyConnection(
            await SQLiteConnectionFactory().connect(db_path), **(self._queued.pop(0) if self._queued else {})
        )
        self.connections.append(connection)
        return connection


async def _drain_closes(target: ElasticTeamStore) -> None:
    """Wait for every tracked connection close to finish, so no test ends with a pending close or an open connection."""
    if target._closing:
        await asyncio.wait_for(asyncio.wait(set(target._closing)), timeout=10)


@pytest.mark.parametrize("close_fails", [False, True], ids=["rollback-fails", "rollback-and-close-fail"])
async def test_failed_rollback_leaves_no_partial_rows_and_the_store_usable(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, close_fails: bool
) -> None:
    """A failed ROLLBACK cannot expose uncommitted rows, and it no longer takes the store out of service.

    This replaces ``test_failed_rollback_closes_the_connection_and_leaves_no_partial_rows`` (F5), which pinned the
    shared-connection design: a failed rollback closed THE connection and made the store unavailable. Every
    operation has its own connection now (R4), so the connection that failed is simply discarded and the next
    operation succeeds on a fresh one. The write dies on the second slot INSERT (after the spec and the first slot
    were inserted), then the ROLLBACK itself fails: the ORIGINAL error must still propagate and nothing may be
    readable. In the second case the close also fails, after releasing the real connection.
    """
    factory = _FaultyFactory()
    faulty = ElasticTeamStore(db_path=str(_db_path(tmp_path)), connection_factory=factory, clock=_Clock(1000.0))
    await faulty.start()
    factory.arm(fail_slot_insert=True, rollback="fails", close="fails-after-release" if close_fails else "ok")
    try:
        with caplog.at_level(logging.WARNING, logger="probos.cognitive.elastic_team_store"):
            with pytest.raises(RuntimeError, match="^injected slot failure$"):  # the original error, not the rollback's
                await faulty.put_team_spec(_SPEC)

        assert factory.connections[-1].close_calls == 1  # the failed connection was discarded
        assert await faulty.get_team_spec(_SPEC_REF) is None  # a fresh connection sees none of its rows
        snapshot = _snapshot(_db_path(tmp_path))
        assert snapshot["elastic_team_specs"] == [] and snapshot["elastic_worker_slots"] == []
        messages = [record.getMessage() for record in caplog.records]
        assert [m for m in messages if "rollback after a failed elastic team write also failed" in m]
        assert bool([m for m in messages if "closing an elastic team connection failed" in m]) is close_fails
        assert not [m for m in messages if "was closed" in m]

        assert await faulty.put_team_spec(_SPEC) == _SPEC_REF  # the store is still in service ...
        assert await faulty.get_team_spec(_SPEC_REF) == _SPEC  # ... and the retried write is stored
    finally:
        await faulty.stop()


async def test_cancellation_during_rollback_never_exposes_uncommitted_rows(tmp_path: Path) -> None:
    """R2-1: a CancelledError delivered while ROLLBACK is awaited must not leave the uncommitted spec readable.

    Before R4 the cancellation escaped ``_abandon_transaction`` with the one shared connection still published
    and its transaction open, so the next read on that connection returned a spec the write never committed.
    Every operation has its own connection now: the cancelled write's connection is closed, which discards its
    transaction, and the next operation opens a fresh one.
    """
    factory = _FaultyFactory()
    gated = ElasticTeamStore(db_path=str(_db_path(tmp_path)), connection_factory=factory, clock=_Clock(1000.0))
    await gated.start()
    entered, release = asyncio.Event(), asyncio.Event()
    try:
        factory.arm(fail_slot_insert=True, rollback="gated", entered=entered, release=release)
        write = asyncio.create_task(gated.put_team_spec(_SPEC))
        await asyncio.wait_for(entered.wait(), timeout=10)  # the write failed on its second slot and is in ROLLBACK
        write.cancel()
        with pytest.raises(asyncio.CancelledError):
            await write

        assert factory.connections[-1].close_calls == 1  # the cancelled write's connection was still closed
        assert await gated.get_team_spec(_SPEC_REF) is None  # a fresh connection sees none of its rows ...
        snapshot = _snapshot(_db_path(tmp_path))
        assert snapshot["elastic_team_specs"] == [] and snapshot["elastic_worker_slots"] == []
        release.set()
        await _drain_closes(gated)
        assert await gated.put_team_spec(_SPEC) == _SPEC_REF  # ... and the store is still in service
    finally:
        release.set()
        await gated.stop()


async def test_close_failure_is_reported_and_never_exposes_uncommitted_rows(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """R2-2: a close that raises WITHOUT releasing the connection is reported truthfully and exposes nothing.

    The write fails after BEGIN and a slot insert, its ROLLBACK fails too, and the proxy's ``close`` raises while
    the real connection stays open (the test releases it). Before R4 the store logged "the connection was closed"
    after a swallowed close failure and discarded the handle. Now the original error propagates, an ERROR says the
    close failed, no record claims it succeeded, and no other connection sees the leaked transaction's rows: it
    only keeps the write lock until it is released, so a writer elsewhere fails closed ("database is locked").
    """
    factory = _FaultyFactory()
    leaky = ElasticTeamStore(db_path=str(_db_path(tmp_path)), connection_factory=factory, clock=_Clock(1000.0))
    await leaky.start()
    factory.arm(fail_slot_insert=True, rollback="fails", close="fails-holding")
    leaked: _FaultyConnection | None = None
    try:
        with caplog.at_level(logging.INFO, logger="probos.cognitive.elastic_team_store"):
            with pytest.raises(RuntimeError, match="^injected slot failure$"):
                await leaky.put_team_spec(_SPEC)
        leaked = factory.connections[-1]  # the write's connection: its close raised, so it is still open

        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert [m for m in errors if "closing an elastic team connection failed" in m]
        assert not [r for r in caplog.records if "was closed" in r.getMessage()]
        assert await leaky.get_team_spec(_SPEC_REF) is None  # a fresh connection ...
        snapshot = _snapshot(_db_path(tmp_path))  # ... and a raw one see no partial rows
        assert snapshot["elastic_team_specs"] == [] and snapshot["elastic_worker_slots"] == []
        competitor = sqlite3.connect(_db_path(tmp_path), timeout=0.1)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):  # the residue: the leaked write lock
                competitor.execute("BEGIN IMMEDIATE")
        finally:
            competitor.close()

        await leaked.inner.close()  # release what the store could not
        assert await leaky.put_team_spec(_SPEC) == _SPEC_REF  # the lock is gone: the store writes again
    finally:
        if leaked is not None:
            await leaked.inner.close()  # idempotent: nothing may outlive the test
        await leaky.stop()


async def test_start_reports_a_failed_probe_close_but_still_starts(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """R4-3: only a failure to open, probe or initialise stops ``start()``; a failed probe close is reported.

    The probe committed the schema before its close was requested, so the store is usable. The close callback is
    the only place that sees the failure, and it logs it.
    """
    factory = _FaultyFactory()
    probed = ElasticTeamStore(db_path=str(_db_path(tmp_path)), connection_factory=factory, clock=_Clock(1000.0))
    factory.arm(close="fails-after-release")  # the probe's real connection closes, then its close raises
    try:
        with caplog.at_level(logging.ERROR, logger="probos.cognitive.elastic_team_store"):
            await probed.start()
            await _drain_closes(probed)

        assert [r for r in caplog.records if "closing an elastic team connection failed" in r.getMessage()]
        assert factory.connections[0].close_calls == 1
        ref = await probed.put_team_spec(_SPEC)
        assert await probed.get_team_spec(ref) == _SPEC
    finally:
        await probed.stop()


class _WaitObserver:
    """Stands in for ``asyncio`` inside the store module: everything delegates to the real module except ``wait``.

    ``wait`` records the timeout the production code asked for, then waits at most ``cap`` seconds. The shipped
    bounds stay untouched, so a test reads the bound the module really uses while a stalled close costs only
    milliseconds. A missing bound (``None``) is recorded and capped like any other, so removing one fails an
    assertion instead of hanging the run.
    """

    def __init__(self, cap: float) -> None:
        self._cap = cap
        self.timeouts: list[float | None] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)

    async def wait(self, fs: Any, *, timeout: float | None = None, **kwargs: Any) -> Any:
        self.timeouts.append(timeout)
        return await asyncio.wait(fs, timeout=self._cap if timeout is None else min(timeout, self._cap), **kwargs)


# The longest a stalled close may hold an operation or ``stop()``; the shipped bounds are 5 s each.
_CLOSE_BOUND_CEILING_SECONDS = 10.0


def _assert_bounded(timeout: float | None) -> None:
    assert timeout is not None and 0 < timeout <= _CLOSE_BOUND_CEILING_SECONDS, timeout


async def test_stalled_close_bounds_the_operation_and_stop(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2-2: a close that never finishes delays neither the operation nor ``stop()`` beyond their bounds.

    No elapsed time is asserted, so a loaded machine cannot fail it. Ordering is proved with events: the operation
    and ``stop()`` both return while the close is still gated, and the gate opens only afterwards. The bounds are
    read from the waits the store makes (``_WaitObserver``): each must be finite and within the ceiling, so a
    removed or lengthened bound fails here. The stalled close stays tracked and reported, and finishes in the
    background once it is released.
    """
    factory = _FaultyFactory()
    stalled = ElasticTeamStore(db_path=str(_db_path(tmp_path)), connection_factory=factory, clock=_Clock(1000.0))
    await stalled.start()
    observer = _WaitObserver(cap=0.05)
    monkeypatch.setattr(store_module, "asyncio", observer)
    entered, release = asyncio.Event(), asyncio.Event()
    factory.arm(close="gated", entered=entered, release=release)
    operation: asyncio.Task[str] | None = None
    try:
        with caplog.at_level(logging.ERROR, logger="probos.cognitive.elastic_team_store"):
            operation = asyncio.create_task(stalled.put_team_spec(_SPEC))  # the write commits; only its close stalls
            await asyncio.wait_for(entered.wait(), timeout=30)  # the timeouts here are watchdogs, not bounds under test
            ref = await asyncio.wait_for(operation, timeout=30)
            assert not release.is_set()  # the operation returned while its close was still gated
            assert ref == _SPEC_REF
            assert len(observer.timeouts) == 1  # the operation's own close wait
            _assert_bounded(observer.timeouts[0])
            messages = [record.getMessage() for record in caplog.records]
            assert [m for m in messages if "did not finish within" in m and "stays tracked" in m]
            assert len(stalled._closing) == 1

            await asyncio.wait_for(stalled.stop(), timeout=30)
            assert not release.is_set()  # stop() returned while that close was still gated
            assert len(observer.timeouts) == 2  # ... after its own bounded wait
            _assert_bounded(observer.timeouts[1])
            messages = [record.getMessage() for record in caplog.records]
            assert [m for m in messages if "1 elastic team connection(s) did not finish closing" in m]
            assert len(stalled._closing) == 1  # it has not finished, so it is still tracked

        tracked = set(stalled._closing)
        release.set()
        await asyncio.wait_for(asyncio.wait(tracked), timeout=10)
        assert all(task.done() and task.exception() is None for task in tracked)
        assert not stalled._closing
    finally:
        release.set()
        if operation is not None and not operation.done():
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
        await _drain_closes(stalled)


class _BlockingCommitConnection:
    """Delegates to a real connection; once armed, ``commit`` signals it was entered and waits to be released."""

    def __init__(self, inner: Any, entered: asyncio.Event, release: asyncio.Event) -> None:
        self._inner = inner
        self._entered = entered
        self._release = release
        self.armed = False
        self.closed = False

    async def execute(self, sql: str, parameters: Any = ()) -> Any:
        return await self._inner.execute(sql, parameters)

    async def executescript(self, sql_script: str) -> None:
        await self._inner.executescript(sql_script)

    async def commit(self) -> None:
        if self.armed:
            self._entered.set()
            await self._release.wait()
        await self._inner.commit()

    async def close(self) -> None:
        self.closed = True
        await self._inner.close()


class _BlockingCommitFactory:
    """Real connections; once ``armed``, every connection it opens blocks in ``commit`` until released.

    ``connection`` is the most recently opened one. (Before R4 the store held ONE connection, which the F8 test
    armed right after ``start()``; each operation opens its own now, so arming is a factory-wide switch.)
    """

    def __init__(self, entered: asyncio.Event, release: asyncio.Event) -> None:
        self._entered = entered
        self._release = release
        self.armed = False
        self.connection: _BlockingCommitConnection | None = None

    async def connect(self, db_path: str) -> _BlockingCommitConnection:
        self.connection = _BlockingCommitConnection(
            await SQLiteConnectionFactory().connect(db_path), self._entered, self._release
        )
        self.connection.armed = self.armed
        return self.connection


async def test_stop_waits_for_an_in_flight_write(tmp_path: Path) -> None:
    """F8: ``stop()`` takes the lock, so it cannot report the store stopped while a write is mid-commit."""
    entered, release = asyncio.Event(), asyncio.Event()
    factory = _BlockingCommitFactory(entered, release)
    blocked = ElasticTeamStore(db_path=str(_db_path(tmp_path)), connection_factory=factory, clock=_Clock(1000.0))
    await blocked.start()
    factory.armed = True  # the connection the write opens blocks in its commit (this used to arm the one shared one)
    write = asyncio.create_task(blocked.put_team_spec(_SPEC))
    await asyncio.wait_for(entered.wait(), timeout=10)  # the write is now inside its commit
    assert factory.connection is not None

    stopping = asyncio.create_task(blocked.stop())
    await asyncio.sleep(0.05)  # ample time for an unlocked stop() to have returned

    assert not stopping.done() and not factory.connection.closed
    release.set()
    ref = await asyncio.wait_for(write, timeout=10)
    await asyncio.wait_for(stopping, timeout=10)

    assert ref == _SPEC_REF and factory.connection.closed
    reopened = _new_store(tmp_path)
    await reopened.start()
    try:
        assert await reopened.get_team_spec(ref) == _SPEC  # the write completed before the connection closed
    finally:
        await reopened.stop()


@pytest.mark.parametrize(
    "failure", [RuntimeError("injected pragma failure"), asyncio.CancelledError()], ids=["error", "cancellation"]
)
async def test_start_failure_after_connect_closes_the_connection(tmp_path: Path, failure: BaseException) -> None:
    connection = _FailingConnection(failure)
    failing = ElasticTeamStore(db_path=str(_db_path(tmp_path)), connection_factory=_FakeFactory(connection))

    with pytest.raises(type(failure)):
        await failing.start()

    assert connection.closed
    with pytest.raises(ElasticTeamStoreUnavailable, match="elastic_team_store_unavailable"):
        await failing.get_team_spec(_SPEC_REF)


async def test_start_failure_closes_and_leaves_store_stopped(tmp_path: Path) -> None:
    (_db_path(tmp_path)).mkdir()  # a directory where the database file should be
    failing = _new_store(tmp_path)

    with pytest.raises(sqlite3.OperationalError):
        await failing.start()

    with pytest.raises(ElasticTeamStoreUnavailable, match="elastic_team_store_unavailable"):
        await failing.put_team_spec(_SPEC)
    await failing.stop()  # still idempotent after a failed start


_PROBED_PRAGMAS = ("foreign_keys", "journal_mode", "busy_timeout", "synchronous", "recursive_triggers")


async def _pragma(connection: Any, name: str) -> Any:
    cursor = await connection.execute(f"PRAGMA {name}")
    return (await cursor.fetchone())[0]


class _ProbeConnection:
    """Delegates to a real connection, records what it executed, and reads its effective pragmas just before it closes."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.statements: list[str] = []
        self.pragmas: dict[str, Any] = {}

    async def execute(self, sql: str, parameters: Any = ()) -> Any:
        self.statements.append(sql)
        return await self._inner.execute(sql, parameters)

    async def executescript(self, sql_script: str) -> None:
        self.statements.append("<executescript>")
        await self._inner.executescript(sql_script)

    async def commit(self) -> None:
        await self._inner.commit()

    async def close(self) -> None:
        for name in _PROBED_PRAGMAS:
            self.pragmas[name] = await _pragma(self._inner, name)
        await self._inner.close()


class _ProbeFactory:
    """Keeps every connection the store opens, so a test can ask what each executed and was configured as."""

    def __init__(self) -> None:
        self.connections: list[_ProbeConnection] = []

    async def connect(self, db_path: str) -> _ProbeConnection:
        connection = _ProbeConnection(await SQLiteConnectionFactory().connect(db_path))
        self.connections.append(connection)
        return connection


async def test_start_probes_once_applies_wal_and_creates_the_schema(tmp_path: Path) -> None:
    """Formerly ``test_start_applies_the_connection_pragmas_once_and_creates_the_schema``.

    The pragmas are per connection now (R4): ``start()`` opens one probe connection, sets the persistent
    ``journal_mode=WAL`` and the schema on it and closes it; what that connection was configured as is read just
    before it closed. The per-connection pragmas of the OPERATION connections are pinned by
    ``test_every_connection_gets_the_per_connection_pragmas``.
    """
    factory = _ProbeFactory()
    probed = ElasticTeamStore(db_path=str(_db_path(tmp_path)), connection_factory=factory, clock=_Clock(1000.0))
    await probed.start()
    try:
        await probed.start()  # idempotent: no second connection

        assert len(factory.connections) == 1
        pragmas = factory.connections[0].pragmas
        assert pragmas["foreign_keys"] == 1  # per-connection, so set on every connection
        assert pragmas["journal_mode"] == "wal"
        assert pragmas["busy_timeout"] == 5000
        assert pragmas["synchronous"] == 1  # NORMAL
        assert pragmas["recursive_triggers"] == 0  # nothing relies on it
    finally:
        await probed.stop()
    raw = sqlite3.connect(_db_path(tmp_path))
    try:
        objects = raw.execute("SELECT type, name FROM sqlite_master").fetchall()
    finally:
        raw.close()
    assert {name for kind, name in objects if kind == "table"} >= set(_TABLES)
    triggers = {name for kind, name in objects if kind == "trigger"}
    assert len(triggers) == 12
    for table in _TABLES:
        assert {f"{table}_no_update", f"{table}_no_delete", f"{table}_no_replace"} <= triggers


async def test_every_connection_gets_the_per_connection_pragmas(tmp_path: Path) -> None:
    """R4: SQLite keeps ``busy_timeout``, ``synchronous`` and ``foreign_keys`` per connection, so each one sets them.

    Every connection the store opens -- a write's, a read's, and the probe at ``start()`` -- executed the three
    pragmas before any other statement (the probe sets ``journal_mode=WAL`` first; that one is persistent for the
    file) and ended up configured as asserted. Only ``start()`` applies the schema.
    """
    factory = _ProbeFactory()
    probed = ElasticTeamStore(db_path=str(_db_path(tmp_path)), connection_factory=factory, clock=_Clock(1000.0))
    await probed.start()
    try:
        ref = await probed.put_team_spec(_SPEC)  # a write
        await probed.get_team_spec(ref)  # a read
        await probed.list_slot_attempts(session_id="session-parent", team_spec_ref=ref, slot_id="analyse")  # a read
    finally:
        await probed.stop()

    probe, *operations = factory.connections
    per_connection = ["PRAGMA busy_timeout=5000", "PRAGMA synchronous=NORMAL", "PRAGMA foreign_keys=ON"]
    assert probe.statements[:4] == ["PRAGMA journal_mode=WAL", *per_connection]
    assert probe.statements[4] == "<executescript>"  # the schema, applied once, at start()
    assert len(operations) == 3
    for operation in operations:
        assert operation.statements[:3] == per_connection
        assert not [statement for statement in operation.statements if "journal_mode" in statement]
        assert "<executescript>" not in operation.statements
        assert operation.pragmas == {
            "foreign_keys": 1,
            "journal_mode": "wal",
            "busy_timeout": 5000,
            "synchronous": 1,
            "recursive_triggers": 0,
        }


# --------------------------------------------------------------------------------------
# 2-5. Specs: idempotent put, one digest per (team_id, revision), reads verify identity
# --------------------------------------------------------------------------------------


async def test_put_team_spec_is_idempotent_and_survives_reopen(tmp_path: Path) -> None:
    first_open = _new_store(tmp_path)
    await first_open.start()
    try:
        first = await first_open.put_team_spec(_SPEC)
        written = _snapshot(_db_path(tmp_path))

        second = await first_open.put_team_spec(_SPEC)

        assert first == second == _SPEC.content_ref()
        assert _snapshot(_db_path(tmp_path)) == written  # the repeat wrote nothing
    finally:
        await first_open.stop()

    second_open = _new_store(tmp_path)
    await second_open.start()
    try:
        assert await second_open.get_team_spec(first) == _SPEC
    finally:
        await second_open.stop()


async def test_put_team_spec_persists_one_slot_row_per_slot(store: ElasticTeamStore, tmp_path: Path) -> None:
    ref = await store.put_team_spec(_TWO_PROFILE_SPEC)

    rows = _snapshot(_db_path(tmp_path))
    assert [row[0] for row in rows["elastic_team_specs"]] == [ref]
    spec_row = rows["elastic_team_specs"][0]
    assert spec_row[1:4] == ("review-team", 1, 1)
    assert spec_row[4] == _TWO_PROFILE_SPEC.canonical_bytes().decode("utf-8")
    assert spec_row[5] == 1000.0
    slots = {row[1]: row for row in rows["elastic_worker_slots"]}
    assert set(slots) == {"analyse", "review"}
    for slot in _TWO_PROFILE_SPEC.slots:
        row = slots[slot.slot_id]
        assert row[0] == ref
        assert row[2] == slot.content_ref()
        assert row[3] == slot.budget.max_attempts
        assert json.loads(row[4]) == list(slot.qualification.pinned_profile_refs)
    assert rows["elastic_worker_attempts"] == [] and rows["elastic_attempt_outcomes"] == []


async def test_same_revision_with_different_content_conflicts(store: ElasticTeamStore, tmp_path: Path) -> None:
    ref = await store.put_team_spec(_SPEC)
    changed = _spec(slots=[_slot(budget={"max_tokens": 200001, "max_wall_ms": 900000, "max_attempts": 6}), _review_slot()])
    assert changed.content_ref() != ref and (changed.team_id, changed.revision) == (_SPEC.team_id, _SPEC.revision)
    written = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamConflict) as conflict:
        await store.put_team_spec(changed)

    assert str(conflict.value) == "elastic_team_revision_conflict"
    assert await store.get_team_spec(ref) == _SPEC
    assert await store.get_team_spec(changed.content_ref()) is None
    assert _snapshot(_db_path(tmp_path)) == written
    next_revision = _spec(revision=2)  # control: a change under a NEW revision is accepted
    assert await store.put_team_spec(next_revision) == next_revision.content_ref()
    assert await store.get_team_spec(ref) == _SPEC


async def test_concurrent_specs_for_one_revision_admit_exactly_one(
    store: ElasticTeamStore, tmp_path: Path
) -> None:
    changed = _spec(slots=[_slot(role_id="senior_analyst"), _review_slot()])

    results = await asyncio.gather(store.put_team_spec(_SPEC), store.put_team_spec(changed), return_exceptions=True)

    winners = [result for result in results if isinstance(result, str)]
    losers = [result for result in results if isinstance(result, ElasticTeamConflict)]
    assert len(winners) == 1 and len(losers) == 1
    assert str(losers[0]) == "elastic_team_revision_conflict"
    assert [row[0] for row in _snapshot(_db_path(tmp_path), "elastic_team_specs")["elastic_team_specs"]] == winners


@pytest.mark.parametrize("bad_ref", ["", "A" * 64, "a" * 63, "a" * 65, "a" * 64 + "\n", None, 5, b"a" * 64])
async def test_get_team_spec_rejects_bad_ref_and_returns_none_when_absent(
    store: ElasticTeamStore, bad_ref: Any
) -> None:
    with pytest.raises(ValueError, match="elastic_team_spec_ref_invalid"):
        await store.get_team_spec(bad_ref)

    assert await store.get_team_spec(_NEW_REF) is None  # a well-formed but unknown reference is absent, not an error
    await store.put_team_spec(_SPEC)
    assert await store.get_team_spec(_NEW_REF) is None


async def test_writers_refuse_the_wrong_type(store: ElasticTeamStore, tmp_path: Path) -> None:
    ref = await store.put_team_spec(_SPEC)
    attempt = _attempt(ref)
    written = _snapshot(_db_path(tmp_path))

    with pytest.raises(TypeError, match="elastic_team_spec_type_invalid"):
        await store.put_team_spec(_SPEC.model_dump(mode="json"))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="elastic_attempt_type_invalid"):
        await store.record_attempt(attempt.model_dump(mode="json"))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="elastic_attempt_outcome_type_invalid"):
        await store.record_attempt_outcome(_failed(attempt).model_dump(mode="json"))  # type: ignore[arg-type]

    assert _snapshot(_db_path(tmp_path)) == written


_SKIPPED_VALIDATION: list[Any] = [
    pytest.param(
        lambda s, ref: s.put_team_spec(_SPEC.model_copy(update={"revision": 0})),
        "elastic_team_revision_invalid",
        id="spec",
    ),
    pytest.param(
        lambda s, ref: s.record_attempt(_attempt(ref).model_copy(update={"ordinal": 0})),
        "elastic_attempt_ordinal_invalid",
        id="attempt",
    ),
    pytest.param(
        lambda s, ref: s.record_attempt_outcome(_failed(_attempt(ref)).model_copy(update={"error_code": None})),
        "elastic_attempt_outcome_invalid",
        id="outcome",
    ),
]


@pytest.mark.parametrize(("write", "code"), _SKIPPED_VALIDATION)
async def test_store_revalidates_a_top_level_copy_that_skipped_validation(
    store: ElasticTeamStore,
    tmp_path: Path,
    write: Callable[[ElasticTeamStore, str], Awaitable[Any]],
    code: str,
) -> None:
    """F4: ``model_copy(update=...)`` passes the ``type(...) is`` check but skips validation (and hashing it
    would persist an identity no constructor could have produced), so every writer revalidates first."""
    ref = await store.put_team_spec(_SPEC)
    written = _snapshot(_db_path(tmp_path))

    with pytest.raises(ValidationError, match=code):
        await write(store, ref)

    assert _snapshot(_db_path(tmp_path)) == written


def _reindented(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2)


def _with_larger_budget(data: dict[str, Any]) -> str:
    data["slots"][0]["budget"]["max_tokens"] += 1
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


@pytest.mark.parametrize(
    "rewrite",
    [
        pytest.param(_with_larger_budget, id="budget-changed"),
        pytest.param(_reindented, id="same-content-not-canonical"),
        pytest.param(lambda data: "{not json", id="not-json"),
        pytest.param(lambda data: json.dumps({"schema_version": 1}), id="not-a-spec"),
    ],
)
async def test_tampered_spec_row_is_refused(
    store: ElasticTeamStore, tmp_path: Path, caplog: pytest.LogCaptureFixture, rewrite: Callable[[dict[str, Any]], str]
) -> None:
    ref = await store.put_team_spec(_SPEC)
    tampered = rewrite(json.loads(_SPEC.canonical_bytes()))
    _tamper(
        _db_path(tmp_path),
        "elastic_team_specs_no_update",
        "UPDATE elastic_team_specs SET canonical_json = ? WHERE spec_ref = ?",
        (tampered, ref),
    )

    with caplog.at_level(logging.ERROR, logger="probos.cognitive.elastic_team_store"):
        with pytest.raises(ElasticTeamIntegrityError) as refused:
            await store.get_team_spec(ref)

    assert str(refused.value) == "elastic_team_spec_integrity"
    assert [record for record in caplog.records if ref in record.getMessage() and "refusing to return it" in record.getMessage()]


async def test_store_satisfies_the_team_spec_lookup_port(store: ElasticTeamStore) -> None:
    lookup: TeamSpecLookup = store  # the narrow read port CrewSessionService will depend on
    ref = await store.put_team_spec(_SPEC)

    assert await lookup.get_team_spec(ref) == _SPEC
    assert await lookup.get_team_spec(_NEW_REF) is None


# --------------------------------------------------------------------------------------
# 6. The database itself refuses every mutation and replacement (R1)
# --------------------------------------------------------------------------------------

_SPEC_COLUMNS = "(spec_ref, team_id, revision, schema_version, canonical_json, created_at)"
_SLOT_COLUMNS = "(spec_ref, slot_id, slot_digest, max_attempts, pinned_profile_refs)"
_ATTEMPT_COLUMNS = (
    "(worker_attempt_id, spec_ref, session_id, slot_id, ordinal, execution_profile_ref, "
    "supersedes_attempt_id, attempt_digest, created_at)"
)
_OUTCOME_COLUMNS = "(worker_attempt_id, terminal_status, error_code, recorded_at)"
_SPEC_VALUES = "VALUES (?, ?, ?, ?, ?, ?)"
_SLOT_VALUES = "VALUES (?, ?, ?, ?, ?)"
_ATTEMPT_VALUES = "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
_OUTCOME_VALUES = "VALUES (?, ?, ?, ?)"


def _spec_row(spec_ref: str = _SPEC_REF, team_id: str = "review-team", revision: int = 1) -> tuple[Any, ...]:
    return (spec_ref, team_id, revision, 1, "{}", 0.0)


def _slot_row(spec_ref: str = _SPEC_REF, slot_id: str = "analyse") -> tuple[Any, ...]:
    return (spec_ref, slot_id, _DIGEST, 1, "[]")


def _attempt_row(
    attempt_id: str = _A1,
    session_id: str = "session-parent",
    ordinal: int = 1,
    supersedes: str | None = None,
) -> tuple[Any, ...]:
    return (attempt_id, _SPEC_REF, session_id, "analyse", ordinal, _PROFILE_A, supersedes, _DIGEST, 0.0)


def _outcome_row(attempt_id: str = _A1) -> tuple[Any, ...]:
    return (attempt_id, "succeeded", None, 0.0)


_REFUSED: list[Any] = [
    # every table x UPDATE (one column of an existing row)
    pytest.param("UPDATE elastic_team_specs SET created_at = 0.5 WHERE spec_ref = ?", (_SPEC_REF,), id="update-specs"),
    pytest.param(
        "UPDATE elastic_worker_slots SET max_attempts = 7 WHERE spec_ref = ? AND slot_id = ?",
        (_SPEC_REF, "analyse"),
        id="update-slots",
    ),
    pytest.param(
        "UPDATE elastic_worker_attempts SET created_at = 0.5 WHERE worker_attempt_id = ?", (_A1,), id="update-attempts"
    ),
    pytest.param(
        "UPDATE elastic_attempt_outcomes SET terminal_status = 'succeeded', error_code = NULL "
        "WHERE worker_attempt_id = ?",
        (_A1,),
        id="update-outcomes",
    ),
    pytest.param(
        "UPDATE OR REPLACE elastic_team_specs SET created_at = 0.5 WHERE spec_ref = ?",
        (_SPEC_REF,),
        id="update-or-replace-specs",
    ),
    # every table x DELETE of an existing row
    pytest.param("DELETE FROM elastic_team_specs WHERE spec_ref = ?", (_SPEC_REF,), id="delete-specs"),
    pytest.param(
        "DELETE FROM elastic_worker_slots WHERE spec_ref = ? AND slot_id = ?", (_SPEC_REF, "analyse"), id="delete-slots"
    ),
    pytest.param("DELETE FROM elastic_worker_attempts WHERE worker_attempt_id = ?", (_A2,), id="delete-attempts"),
    pytest.param("DELETE FROM elastic_attempt_outcomes WHERE worker_attempt_id = ?", (_A1,), id="delete-outcomes"),
    # every table x INSERT OR REPLACE reusing an existing primary key
    pytest.param(
        f"INSERT OR REPLACE INTO elastic_team_specs {_SPEC_COLUMNS} {_SPEC_VALUES}",
        _spec_row(team_id="other-team", revision=7),
        id="replace-primary-key-specs",
    ),
    pytest.param(
        f"INSERT OR REPLACE INTO elastic_worker_slots {_SLOT_COLUMNS} {_SLOT_VALUES}",
        _slot_row(),
        id="replace-primary-key-slots",
    ),
    pytest.param(
        f"INSERT OR REPLACE INTO elastic_worker_attempts {_ATTEMPT_COLUMNS} {_ATTEMPT_VALUES}",
        _attempt_row(session_id="session-other"),
        id="replace-primary-key-attempts",
    ),
    pytest.param(
        f"INSERT OR REPLACE INTO elastic_attempt_outcomes {_OUTCOME_COLUMNS} {_OUTCOME_VALUES}",
        _outcome_row(),
        id="replace-primary-key-outcomes",
    ),
    # REPLACE through a SECONDARY unique key (the bypass the *_no_replace guards close)
    pytest.param(
        f"REPLACE INTO elastic_team_specs {_SPEC_COLUMNS} {_SPEC_VALUES}",
        _spec_row(spec_ref=_NEW_REF),
        id="replace-secondary-key-spec-team-revision",
    ),
    pytest.param(
        f"REPLACE INTO elastic_worker_attempts {_ATTEMPT_COLUMNS} {_ATTEMPT_VALUES}",
        _attempt_row(attempt_id=_NEW_ID),
        id="replace-secondary-key-attempt-ordinal",
    ),
    pytest.param(
        f"REPLACE INTO elastic_worker_attempts {_ATTEMPT_COLUMNS} {_ATTEMPT_VALUES}",
        _attempt_row(attempt_id=_NEW_ID, ordinal=3, supersedes=_A1),
        id="replace-secondary-key-attempt-supersedes",
    ),
    # every table x INSERT ... ON CONFLICT DO UPDATE on its primary key
    pytest.param(
        f"INSERT INTO elastic_team_specs {_SPEC_COLUMNS} {_SPEC_VALUES} "
        "ON CONFLICT (spec_ref) DO UPDATE SET created_at = excluded.created_at",
        _spec_row(team_id="other-team", revision=7),
        id="upsert-specs",
    ),
    pytest.param(
        f"INSERT INTO elastic_worker_slots {_SLOT_COLUMNS} {_SLOT_VALUES} "
        "ON CONFLICT (spec_ref, slot_id) DO UPDATE SET max_attempts = excluded.max_attempts",
        _slot_row(),
        id="upsert-slots",
    ),
    pytest.param(
        f"INSERT INTO elastic_worker_attempts {_ATTEMPT_COLUMNS} {_ATTEMPT_VALUES} "
        "ON CONFLICT (worker_attempt_id) DO UPDATE SET created_at = excluded.created_at",
        _attempt_row(session_id="session-other"),
        id="upsert-attempts",
    ),
    pytest.param(
        f"INSERT INTO elastic_attempt_outcomes {_OUTCOME_COLUMNS} {_OUTCOME_VALUES} "
        "ON CONFLICT (worker_attempt_id) DO UPDATE SET terminal_status = excluded.terminal_status",
        _outcome_row(),
        id="upsert-outcomes",
    ),
    # INSERT OR IGNORE: also aborted (it would otherwise be a silent no-op), on every table
    pytest.param(
        f"INSERT OR IGNORE INTO elastic_team_specs {_SPEC_COLUMNS} {_SPEC_VALUES}",
        _spec_row(team_id="other-team", revision=7),
        id="ignore-specs",
    ),
    pytest.param(
        f"INSERT OR IGNORE INTO elastic_worker_slots {_SLOT_COLUMNS} {_SLOT_VALUES}", _slot_row(), id="ignore-slots"
    ),
    pytest.param(
        f"INSERT OR IGNORE INTO elastic_worker_attempts {_ATTEMPT_COLUMNS} {_ATTEMPT_VALUES}",
        _attempt_row(session_id="session-other"),
        id="ignore-attempts",
    ),
    pytest.param(
        f"INSERT OR IGNORE INTO elastic_attempt_outcomes {_OUTCOME_COLUMNS} {_OUTCOME_VALUES}",
        _outcome_row(),
        id="ignore-outcomes",
    ),
    # F1 / R4 test isolation: the implicit-rowid replacement bypass. The tables are WITHOUT ROWID, so SQLite itself
    # refuses to name ``rowid`` at all (the error is "no column named rowid", not the trigger's code). Every case
    # carries an explicit ``rowid`` of 1 -- the first stored row -- and a primary key AND every secondary unique key
    # that collide with NOTHING stored, so no guard trigger and no unique key could be what refuses it: on a rowid
    # table each statement would simply REPLACE that first row. (These cases used to reuse an existing primary key,
    # so a guard trigger alone was enough to refuse them. The raw connection runs with foreign keys OFF, so the
    # outcome case need not name an existing attempt.)
    pytest.param(
        "INSERT OR REPLACE INTO elastic_team_specs "
        "(rowid, spec_ref, team_id, revision, schema_version, canonical_json, created_at) "
        "VALUES (1, ?, ?, ?, ?, ?, ?)",
        _spec_row(spec_ref=_NEW_REF, team_id="fresh-team", revision=99),
        id="rowid-replace-specs",
    ),
    pytest.param(
        "INSERT OR REPLACE INTO elastic_worker_slots "
        "(rowid, spec_ref, slot_id, slot_digest, max_attempts, pinned_profile_refs) VALUES (1, ?, ?, ?, ?, ?)",
        _slot_row(slot_id="fresh-slot"),
        id="rowid-replace-slots",
    ),
    pytest.param(
        "INSERT OR REPLACE INTO elastic_worker_attempts "
        "(rowid, worker_attempt_id, spec_ref, session_id, slot_id, ordinal, execution_profile_ref, "
        "supersedes_attempt_id, attempt_digest, created_at) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        _attempt_row(attempt_id=_NEW_ID, session_id="session-rowid", ordinal=9),
        id="rowid-replace-attempts",
    ),
    pytest.param(
        "INSERT OR REPLACE INTO elastic_attempt_outcomes "
        "(rowid, worker_attempt_id, terminal_status, error_code, recorded_at) VALUES (1, ?, ?, ?, ?)",
        _outcome_row(_NEW_ID),
        id="rowid-replace-outcomes",
    ),
]


def _refusal_message(statement: str) -> str:
    """What a refused statement raises: the trigger's code, or SQLite's own refusal of a ``rowid`` column."""
    return "rowid" if "(rowid," in statement else "elastic_team_immutable"


@pytest.mark.parametrize(("statement", "params"), _REFUSED)
async def test_triggers_refuse_every_mutation_and_replacement_on_every_table(
    tmp_path: Path, statement: str, params: tuple[Any, ...]
) -> None:
    path = await _populated_db(tmp_path)
    raw = sqlite3.connect(path)  # DEFAULT pragmas: nothing here relies on recursive_triggers or foreign keys
    try:
        assert raw.execute("PRAGMA foreign_keys").fetchone() == (0,)
        assert raw.execute("PRAGMA recursive_triggers").fetchone() == (0,)
        before = _read_tables(raw)
        assert all(before.values())  # every table holds a row, so "unchanged" is not vacuous

        with pytest.raises(sqlite3.DatabaseError, match=_refusal_message(statement)):
            raw.execute(statement, params)
        raw.rollback()

        assert _read_tables(raw) == before
    finally:
        raw.close()


async def test_every_table_is_without_rowid(tmp_path: Path) -> None:
    """F1: with no implicit rowid there is no hidden mutable key a REPLACE could match instead of the guards'."""
    path = await _populated_db(tmp_path)
    raw = sqlite3.connect(path)
    try:
        definitions = dict(
            raw.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name LIKE 'elastic_%'")
        )
    finally:
        raw.close()

    assert set(definitions) == set(_TABLES)
    for table, definition in definitions.items():
        assert definition.rstrip().upper().endswith("WITHOUT ROWID"), table


async def test_triggers_still_accept_genuinely_new_rows(tmp_path: Path) -> None:
    """Negative control for the refusals above, on the same kind of raw default-pragma connection.

    A guard that refused everything would pass every refusal case; this proves the guards fire only
    for an existing row: a new spec with its slot, a new attempt at the next free ordinal that
    replaces an unreplaced cancelled attempt, an attempt with no predecessor beside one that also
    has none (NULL never collides), and new outcomes.
    """
    path = await _populated_db(tmp_path)
    new_spec_ref = "8" * 64
    raw = sqlite3.connect(path)
    try:
        before = _read_tables(raw)

        raw.execute(
            f"INSERT INTO elastic_team_specs {_SPEC_COLUMNS} {_SPEC_VALUES}",
            _spec_row(spec_ref=new_spec_ref, revision=2),
        )
        raw.execute(f"INSERT INTO elastic_worker_slots {_SLOT_COLUMNS} {_SLOT_VALUES}", _slot_row(spec_ref=new_spec_ref))
        raw.execute(
            f"INSERT INTO elastic_worker_attempts {_ATTEMPT_COLUMNS} {_ATTEMPT_VALUES}",
            _attempt_row(attempt_id=_A3, ordinal=3, supersedes=_A2),
        )
        raw.execute(
            f"INSERT INTO elastic_worker_attempts {_ATTEMPT_COLUMNS} {_ATTEMPT_VALUES}",
            _attempt_row(attempt_id=_OTHER_SESSION_A1, session_id="session-other", ordinal=1),
        )
        raw.execute(f"INSERT INTO elastic_attempt_outcomes {_OUTCOME_COLUMNS} {_OUTCOME_VALUES}", _outcome_row(_A3))
        raw.execute(
            f"INSERT INTO elastic_attempt_outcomes {_OUTCOME_COLUMNS} {_OUTCOME_VALUES}",
            _outcome_row(_OTHER_SESSION_A1),
        )
        raw.commit()

        after = _read_tables(raw)
    finally:
        raw.close()
    assert len(after["elastic_team_specs"]) == len(before["elastic_team_specs"]) + 1
    assert len(after["elastic_worker_slots"]) == len(before["elastic_worker_slots"]) + 1
    assert len(after["elastic_worker_attempts"]) == len(before["elastic_worker_attempts"]) + 2
    assert len(after["elastic_attempt_outcomes"]) == len(before["elastic_attempt_outcomes"]) + 2
    for table in _TABLES:
        # Nothing that existed before was touched. The tables are WITHOUT ROWID (F1), so rows sort by
        # primary key rather than insertion order: this used to pin ``after[table][:len(before)] == before``.
        assert set(before[table]) <= set(after[table])


# --------------------------------------------------------------------------------------
# 7-11. Attempts: durable slot, no overwrite, admission, write-once outcomes, concurrency
# --------------------------------------------------------------------------------------


async def test_slot_survives_failed_and_replaced_attempts(store: ElasticTeamStore) -> None:
    ref = await store.put_team_spec(_TWO_PROFILE_SPEC)
    first = await store.record_attempt(_attempt(ref, ordinal=1, profile=_PROFILE_A))
    await store.record_attempt_outcome(_failed(first))
    second = await store.record_attempt(
        _attempt(ref, ordinal=2, profile=_PROFILE_B, supersedes=first.worker_attempt_id)
    )
    await store.record_attempt_outcome(_cancelled(second))
    third = await store.record_attempt(
        _attempt(ref, ordinal=3, profile=_PROFILE_A, supersedes=second.worker_attempt_id)
    )

    attempts = await store.list_slot_attempts(session_id="session-parent", team_spec_ref=ref, slot_id="analyse")

    assert attempts == (first, second, third)
    assert [attempt.ordinal for attempt in attempts] == [1, 2, 3]
    assert len({attempt.worker_attempt_id for attempt in attempts}) == 3
    assert len({attempt.content_ref() for attempt in attempts}) == 3
    assert (await store.get_attempt_outcome(first.worker_attempt_id)).terminal_status == "failed"
    assert (await store.get_attempt_outcome(second.worker_attempt_id)).terminal_status == "cancelled"
    assert await store.get_attempt_outcome(third.worker_attempt_id) is None  # still running
    assert [await store.get_attempt(attempt.worker_attempt_id) for attempt in attempts] == [first, second, third]
    assert await store.get_team_spec(ref) == _TWO_PROFILE_SPEC  # the durable slot never changed


async def test_ordinals_are_counted_per_session_and_slot(store: ElasticTeamStore) -> None:
    ref = await store.put_team_spec(_SPEC)
    mine = await store.record_attempt(_attempt(ref, session_id="session-parent"))
    theirs = await store.record_attempt(_attempt(ref, session_id="session-other"))
    reviewer = await store.record_attempt(_attempt(ref, slot_id="review"))

    assert mine.worker_attempt_id != theirs.worker_attempt_id != reviewer.worker_attempt_id
    assert await store.list_slot_attempts(session_id="session-parent", team_spec_ref=ref, slot_id="analyse") == (mine,)
    assert await store.list_slot_attempts(session_id="session-other", team_spec_ref=ref, slot_id="analyse") == (theirs,)
    assert await store.list_slot_attempts(session_id="session-parent", team_spec_ref=ref, slot_id="review") == (reviewer,)
    assert await store.list_slot_attempts(session_id="session-none", team_spec_ref=ref, slot_id="analyse") == ()


async def test_attempts_cannot_overwrite_one_another(store: ElasticTeamStore, tmp_path: Path) -> None:
    ref = await store.put_team_spec(_TWO_PROFILE_SPEC)
    original = _attempt(ref, profile=_PROFILE_A)
    rival = _attempt(ref, profile=_PROFILE_B)  # the same derived id, a different execution profile
    assert rival.worker_attempt_id == original.worker_attempt_id and rival.content_ref() != original.content_ref()
    await store.record_attempt(original)
    written = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamConflict) as conflict:
        await store.record_attempt(rival)

    assert str(conflict.value) == "elastic_attempt_conflict"
    assert _snapshot(_db_path(tmp_path)) == written
    assert await store.get_attempt(original.worker_attempt_id) == original
    assert await store.record_attempt(original) == original  # an identical re-record is idempotent
    assert _snapshot(_db_path(tmp_path)) == written  # ... and writes nothing


async def _prepare_unknown_slot(store: ElasticTeamStore, ref: str) -> WorkerAttempt:
    return _attempt(ref, slot_id="ghost")


async def _prepare_unknown_spec(store: ElasticTeamStore, ref: str) -> WorkerAttempt:
    return _attempt(_NEW_REF)


async def _prepare_ordinal_gap(store: ElasticTeamStore, ref: str) -> WorkerAttempt:
    return _attempt(ref, ordinal=2)


async def _prepare_budget_exhausted(store: ElasticTeamStore, ref: str) -> WorkerAttempt:
    await store.record_attempt(_attempt(ref, slot_id="review"))
    return _attempt(ref, slot_id="review", ordinal=2)  # the review slot allows one attempt


async def _prepare_unpinned_profile(store: ElasticTeamStore, ref: str) -> WorkerAttempt:
    return _attempt(ref, profile=_PROFILE_B)  # the analyse slot pins only profile A


async def _prepare_predecessor_without_outcome(store: ElasticTeamStore, ref: str) -> WorkerAttempt:
    first = await store.record_attempt(_attempt(ref))
    return _attempt(ref, ordinal=2, supersedes=first.worker_attempt_id)


async def _prepare_predecessor_succeeded(store: ElasticTeamStore, ref: str) -> WorkerAttempt:
    first = await store.record_attempt(_attempt(ref))
    await store.record_attempt_outcome(_succeeded(first))
    return _attempt(ref, ordinal=2, supersedes=first.worker_attempt_id)


async def _prepare_predecessor_of_another_slot(store: ElasticTeamStore, ref: str) -> WorkerAttempt:
    await store.record_attempt(_attempt(ref))
    other = await store.record_attempt(_attempt(ref, slot_id="review"))
    await store.record_attempt_outcome(_failed(other))
    return _attempt(ref, ordinal=2, supersedes=other.worker_attempt_id)


async def _prepare_predecessor_of_another_session(store: ElasticTeamStore, ref: str) -> WorkerAttempt:
    other = await store.record_attempt(_attempt(ref, session_id="session-other"))
    await store.record_attempt_outcome(_failed(other))
    await store.record_attempt(_attempt(ref))
    return _attempt(ref, ordinal=2, supersedes=other.worker_attempt_id)


async def _prepare_predecessor_that_does_not_exist(store: ElasticTeamStore, ref: str) -> WorkerAttempt:
    await store.record_attempt(_attempt(ref))
    return _attempt(ref, ordinal=2, supersedes="wa-" + "e" * 64)


async def _prepare_predecessor_of_another_spec(store: ElasticTeamStore, ref: str) -> WorkerAttempt:
    await store.record_attempt(_attempt(ref))
    other_ref = await store.put_team_spec(_spec(revision=2))  # same session and slot id, a different spec
    other = await store.record_attempt(_attempt(other_ref))
    await store.record_attempt_outcome(_failed(other))
    return _attempt(ref, ordinal=2, supersedes=other.worker_attempt_id)


async def _prepare_second_successor(store: ElasticTeamStore, ref: str) -> WorkerAttempt:
    first = await store.record_attempt(_attempt(ref))
    await store.record_attempt_outcome(_failed(first))
    await store.record_attempt(_attempt(ref, ordinal=2, supersedes=first.worker_attempt_id))
    return _attempt(ref, ordinal=3, supersedes=first.worker_attempt_id)


_ADMISSION_REFUSALS: list[Any] = [
    pytest.param(_prepare_unknown_slot, "elastic_attempt_slot_unknown", id="unknown-slot"),
    pytest.param(_prepare_unknown_spec, "elastic_attempt_slot_unknown", id="unknown-spec"),
    pytest.param(_prepare_ordinal_gap, "elastic_attempt_ordinal_invalid", id="ordinal-gap"),
    pytest.param(_prepare_budget_exhausted, "elastic_attempt_budget_exhausted", id="beyond-max-attempts"),
    pytest.param(_prepare_unpinned_profile, "elastic_attempt_profile_not_pinned", id="unpinned-profile"),
    pytest.param(
        _prepare_predecessor_without_outcome, "elastic_attempt_supersedes_invalid", id="predecessor-has-no-outcome"
    ),
    pytest.param(
        _prepare_predecessor_succeeded, "elastic_attempt_supersedes_invalid", id="predecessor-succeeded"
    ),
    pytest.param(
        _prepare_predecessor_of_another_slot, "elastic_attempt_supersedes_invalid", id="predecessor-of-another-slot"
    ),
    pytest.param(
        _prepare_predecessor_of_another_session,
        "elastic_attempt_supersedes_invalid",
        id="predecessor-of-another-session",
    ),
    pytest.param(
        _prepare_predecessor_of_another_spec, "elastic_attempt_supersedes_invalid", id="predecessor-of-another-spec"
    ),
    pytest.param(
        _prepare_predecessor_that_does_not_exist, "elastic_attempt_supersedes_invalid", id="predecessor-missing"
    ),
    pytest.param(_prepare_second_successor, "elastic_attempt_already_replaced", id="second-successor"),
]


@pytest.mark.parametrize(("prepare", "code"), _ADMISSION_REFUSALS)
async def test_attempt_admission_refusals(
    store: ElasticTeamStore,
    tmp_path: Path,
    prepare: Callable[[ElasticTeamStore, str], Awaitable[WorkerAttempt]],
    code: str,
) -> None:
    ref = await store.put_team_spec(_TIGHT_BUDGET_SPEC)
    refused = await prepare(store, ref)
    written = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamConflict) as conflict:
        await store.record_attempt(refused)

    assert str(conflict.value) == code
    assert _snapshot(_db_path(tmp_path)) == written  # a refusal writes nothing, in any table
    assert await store.get_attempt(refused.worker_attempt_id) is None


async def test_admission_refuses_a_noncontiguous_history_as_an_integrity_failure(
    store: ElasticTeamStore, tmp_path: Path
) -> None:
    """F6: a gapped history (only possible by writing the file) is an integrity failure, not an admission.

    This replaces ``test_admission_refuses_a_predecessor_that_is_not_older``. That test planted a raw ordinal-3
    row with no ordinals 1..2, saw the replacement of ordinal 3 refused as "not older", and then pinned that an
    ordinal-2 attempt was ACCEPTED beside the gap. Admission used ``COUNT(*)+1``, so it trusted a history it had
    not verified; it now requires the recorded ordinals to be exactly 1..n and refuses both attempts.
    """
    ref = await store.put_team_spec(_SPEC)
    raw = sqlite3.connect(_db_path(tmp_path))
    try:
        raw.execute(f"INSERT INTO elastic_worker_attempts {_ATTEMPT_COLUMNS} {_ATTEMPT_VALUES}", _attempt_row(_A3, ordinal=3))
        raw.execute(
            f"INSERT INTO elastic_attempt_outcomes {_OUTCOME_COLUMNS} {_OUTCOME_VALUES}",
            (_A3, "failed", "model_timeout", 0.0),
        )
        raw.commit()
    finally:
        raw.close()
    tampered = _snapshot(_db_path(tmp_path))

    # the replacement of the recorded ordinal 3, and the former "control" (a plain ordinal 2 beside the gap)
    for refused in (_attempt(ref, ordinal=2, supersedes=_A3), _attempt(ref, ordinal=2)):
        with pytest.raises(ElasticTeamIntegrityError) as integrity:
            await store.record_attempt(refused)

        assert str(integrity.value) == "elastic_attempt_integrity"
        assert _snapshot(_db_path(tmp_path)) == tampered


async def test_admission_refuses_an_orphan_slot(store: ElasticTeamStore, tmp_path: Path) -> None:
    """F6: a slot row whose spec row is missing (possible only with foreign keys off) admits nothing."""
    raw = sqlite3.connect(_db_path(tmp_path))  # default pragmas: foreign keys are OFF, so the orphan inserts
    try:
        raw.execute(f"INSERT INTO elastic_worker_slots {_SLOT_COLUMNS} {_SLOT_VALUES}", _slot_row(spec_ref=_NEW_REF))
        raw.commit()
    finally:
        raw.close()
    tampered = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamIntegrityError) as refused:
        await store.record_attempt(_attempt(_NEW_REF))

    assert str(refused.value) == "elastic_team_spec_integrity"
    assert _snapshot(_db_path(tmp_path)) == tampered


@pytest.mark.parametrize(
    ("column", "value"),
    [
        pytest.param("max_attempts", 7, id="max-attempts"),
        pytest.param("pinned_profile_refs", json.dumps([_PROFILE_B]), id="pinned-profile-refs"),
        pytest.param("slot_digest", "c" * 64, id="slot-digest"),
    ],
)
async def test_admission_refuses_a_slot_cache_that_disagrees_with_the_spec(
    store: ElasticTeamStore, tmp_path: Path, column: str, value: Any
) -> None:
    """F6: the slot row's cached columns are a projection of the verified spec; drift is an integrity failure.

    Each column is rewritten the way the existing tamper tests do it (drop the slot UPDATE guard, then UPDATE).
    """
    ref = await store.put_team_spec(_SPEC)
    _tamper(
        _db_path(tmp_path),
        "elastic_worker_slots_no_update",
        f"UPDATE elastic_worker_slots SET {column} = ? WHERE spec_ref = ? AND slot_id = 'analyse'",
        (value, ref),
    )
    tampered = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamIntegrityError) as refused:
        await store.record_attempt(_attempt(ref))

    assert str(refused.value) == "elastic_team_spec_integrity"
    assert _snapshot(_db_path(tmp_path)) == tampered


async def test_admission_refuses_a_tampered_predecessor(store: ElasticTeamStore, tmp_path: Path) -> None:
    """F6: the predecessor is rebuilt from its row and checked against its digest before it is trusted."""
    ref = await store.put_team_spec(_SPEC)
    first = await store.record_attempt(_attempt(ref))
    await store.record_attempt_outcome(_failed(first))
    _tamper(
        _db_path(tmp_path),
        "elastic_worker_attempts_no_update",
        "UPDATE elastic_worker_attempts SET execution_profile_ref = ? WHERE worker_attempt_id = ?",
        (_PROFILE_B, first.worker_attempt_id),
    )
    tampered = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamIntegrityError) as refused:
        await store.record_attempt(_attempt(ref, ordinal=2, supersedes=first.worker_attempt_id))

    assert str(refused.value) == "elastic_attempt_integrity"
    assert _snapshot(_db_path(tmp_path)) == tampered


async def test_admission_accepts_an_unpinned_slot_with_any_profile_and_in_budget_replacements(
    store: ElasticTeamStore,
) -> None:
    ref = await store.put_team_spec(_SPEC)
    first = await store.record_attempt(_attempt(ref, slot_id="review", profile=_PROFILE_B))  # review pins nothing
    await store.record_attempt_outcome(_failed(first))

    second = await store.record_attempt(
        _attempt(ref, slot_id="review", ordinal=2, profile=_PROFILE_A, supersedes=first.worker_attempt_id)
    )

    assert second.ordinal == 2  # review allows two attempts and the second replaces a failed first


async def test_outcome_is_write_once(store: ElasticTeamStore, tmp_path: Path) -> None:
    ref = await store.put_team_spec(_SPEC)
    attempt = await store.record_attempt(_attempt(ref))
    stored = await store.record_attempt_outcome(_failed(attempt, at=2000.0))
    written = _snapshot(_db_path(tmp_path))

    repeated = await store.record_attempt_outcome(_failed(attempt, at=9999.0))

    assert repeated == stored and repeated.recorded_at == 2000.0  # the first write's timestamp wins
    assert _snapshot(_db_path(tmp_path)) == written
    for different in (_succeeded(attempt), _cancelled(attempt), _failed(attempt, code="other_error")):
        with pytest.raises(ElasticTeamConflict) as conflict:
            await store.record_attempt_outcome(different)
        assert str(conflict.value) == "elastic_attempt_outcome_conflict"
    assert await store.get_attempt_outcome(attempt.worker_attempt_id) == stored
    assert _snapshot(_db_path(tmp_path)) == written
    with pytest.raises(ElasticTeamConflict) as unknown:
        await store.record_attempt_outcome(_failed(_attempt(ref, ordinal=1, session_id="session-ghost")))
    assert str(unknown.value) == "elastic_attempt_unknown"
    assert _snapshot(_db_path(tmp_path)) == written


async def test_concurrent_admission_of_one_ordinal_admits_exactly_one(
    store: ElasticTeamStore, tmp_path: Path
) -> None:
    ref = await store.put_team_spec(_TWO_PROFILE_SPEC)
    with_a = _attempt(ref, profile=_PROFILE_A)
    with_b = _attempt(ref, profile=_PROFILE_B)

    results = await asyncio.gather(store.record_attempt(with_a), store.record_attempt(with_b), return_exceptions=True)

    winners = [result for result in results if isinstance(result, WorkerAttempt)]
    losers = [result for result in results if isinstance(result, ElasticTeamConflict)]
    assert len(winners) == 1 and len(losers) == 1
    assert str(losers[0]) == "elastic_attempt_conflict"
    assert len(_snapshot(_db_path(tmp_path), "elastic_worker_attempts")["elastic_worker_attempts"]) == 1
    assert await store.list_slot_attempts(
        session_id="session-parent", team_spec_ref=ref, slot_id="analyse"
    ) == (winners[0],)


# --------------------------------------------------------------------------------------
# Reads: argument validation, integrity verification, clock, write discipline
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad_id", ["", None, 5, "x" * 129, b"wa-"], ids=["empty", "none", "int", "too-long", "bytes"])
async def test_reads_refuse_a_malformed_id(store: ElasticTeamStore, bad_id: Any) -> None:
    with pytest.raises(ValueError, match="elastic_attempt_query_invalid"):
        await store.get_attempt(bad_id)
    with pytest.raises(ValueError, match="elastic_attempt_query_invalid"):
        await store.get_attempt_outcome(bad_id)
    with pytest.raises(ValueError, match="elastic_attempt_query_invalid"):
        await store.list_slot_attempts(session_id=bad_id, team_spec_ref=_SPEC_REF, slot_id="analyse")
    with pytest.raises(ValueError, match="elastic_attempt_query_invalid"):
        await store.list_slot_attempts(session_id="session-parent", team_spec_ref=_SPEC_REF, slot_id=bad_id)


@pytest.mark.parametrize("bad_ref", ["", "A" * 64, "a" * 63, None, 5])
async def test_list_slot_attempts_refuses_a_malformed_spec_ref(store: ElasticTeamStore, bad_ref: Any) -> None:
    with pytest.raises(ValueError, match="elastic_attempt_query_invalid"):
        await store.list_slot_attempts(session_id="session-parent", team_spec_ref=bad_ref, slot_id="analyse")


async def test_reads_return_nothing_for_an_unknown_attempt(store: ElasticTeamStore) -> None:
    assert await store.get_attempt(_NEW_ID) is None
    assert await store.get_attempt_outcome(_NEW_ID) is None
    assert await store.list_slot_attempts(session_id="session-parent", team_spec_ref=_NEW_REF, slot_id="analyse") == ()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        pytest.param("execution_profile_ref", _PROFILE_B, id="valid-row-with-a-different-digest"),
        pytest.param("ordinal", 2, id="row-no-longer-validates-as-an-attempt"),
    ],
)
async def test_tampered_attempt_row_is_refused(
    store: ElasticTeamStore, tmp_path: Path, caplog: pytest.LogCaptureFixture, column: str, value: Any
) -> None:
    ref = await store.put_team_spec(_TWO_PROFILE_SPEC)
    attempt = await store.record_attempt(_attempt(ref, profile=_PROFILE_A))
    _tamper(
        _db_path(tmp_path),
        "elastic_worker_attempts_no_update",
        f"UPDATE elastic_worker_attempts SET {column} = ? WHERE worker_attempt_id = ?",
        (value, attempt.worker_attempt_id),
    )

    with caplog.at_level(logging.ERROR, logger="probos.cognitive.elastic_team_store"):
        with pytest.raises(ElasticTeamIntegrityError) as by_id:
            await store.get_attempt(attempt.worker_attempt_id)
        with pytest.raises(ElasticTeamIntegrityError) as by_slot:
            await store.list_slot_attempts(session_id="session-parent", team_spec_ref=ref, slot_id="analyse")

    assert str(by_id.value) == str(by_slot.value) == "elastic_attempt_integrity"
    assert [record for record in caplog.records if "refusing to return it" in record.getMessage()]


async def test_tampered_slot_pin_list_refuses_admission_and_writes_nothing(
    store: ElasticTeamStore, tmp_path: Path
) -> None:
    ref = await store.put_team_spec(_SPEC)
    _tamper(
        _db_path(tmp_path),
        "elastic_worker_slots_no_update",
        "UPDATE elastic_worker_slots SET pinned_profile_refs = ? WHERE spec_ref = ? AND slot_id = 'analyse'",
        ("not json", ref),
    )
    tampered = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamIntegrityError) as refused:
        await store.record_attempt(_attempt(ref))

    assert str(refused.value) == "elastic_team_spec_integrity"
    assert _snapshot(_db_path(tmp_path)) == tampered


# --------------------------------------------------------------------------------------
# R4: the store never admits, acknowledges or returns from a row it cannot verify (the seven closed paths)
# --------------------------------------------------------------------------------------


def _tamper_ignoring_checks(path: Path, drop_trigger: str, statement: str, params: tuple[Any, ...]) -> None:
    """``_tamper`` with CHECK constraints off, for a rewrite no CHECK would let through (``schema_version = 2``)."""
    raw = sqlite3.connect(path)
    try:
        raw.execute("PRAGMA ignore_check_constraints = ON")
        raw.execute(f"DROP TRIGGER {drop_trigger}")
        raw.execute(statement, params)
        raw.commit()
    finally:
        raw.close()


_TAMPERED_SPEC_TEXT = _with_larger_budget(json.loads(_SPEC.canonical_bytes()))  # parses, but hashes to another ref
_RIVAL_SPEC = _spec(slots=[_slot(role_id="senior_analyst"), _review_slot()])  # the same team and revision, other content
# Each rewrite passes every SQL CHECK of ``elastic_attempt_outcomes`` yet no ``WorkerAttemptOutcome`` could be built from it.
_MALFORMED_OUTCOME_UPDATES: list[Any] = [
    pytest.param("UPDATE elastic_attempt_outcomes SET recorded_at = 'later' WHERE worker_attempt_id = ?", id="recorded-at-is-text"),
    pytest.param("UPDATE elastic_attempt_outcomes SET error_code = NULL WHERE worker_attempt_id = ?", id="failed-without-a-code"),
    pytest.param(
        "UPDATE elastic_attempt_outcomes SET error_code = 'NOT A CODE' WHERE worker_attempt_id = ?",
        id="code-breaks-the-pattern",
    ),
]


@pytest.mark.parametrize(
    ("column", "value"),
    [
        pytest.param("team_id", "other-team", id="team-id"),
        pytest.param("revision", 7, id="revision"),
        pytest.param("schema_version", 2, id="schema-version"),
    ],
)
async def test_catalog_columns_must_match_the_canonical_spec(
    store: ElasticTeamStore, tmp_path: Path, column: str, value: Any
) -> None:
    """R2-3: the catalog columns cached beside ``canonical_json`` are verified against it, not trusted.

    Each column of a stored spec is rewritten (the UPDATE guard dropped, CHECKs ignored) so that it disagrees with
    the canonical text, which still hashes to its reference. Reading the row, and an identical put that would
    otherwise acknowledge it, must both be refused.
    """
    ref = await store.put_team_spec(_SPEC)
    _tamper_ignoring_checks(
        _db_path(tmp_path),
        "elastic_team_specs_no_update",
        f"UPDATE elastic_team_specs SET {column} = ? WHERE spec_ref = ?",
        (value, ref),
    )
    tampered = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamIntegrityError) as read:
        await store.get_team_spec(ref)
    with pytest.raises(ElasticTeamIntegrityError) as repeated:
        await store.put_team_spec(_SPEC)

    assert str(read.value) == str(repeated.value) == "elastic_team_spec_integrity"
    assert _snapshot(_db_path(tmp_path)) == tampered


async def test_a_second_row_cannot_hide_the_team_and_revision_its_content_names(
    store: ElasticTeamStore, tmp_path: Path
) -> None:
    """R2-3 reproduction: a row whose canonical model names the first spec's ``(team_id, revision)`` while its
    catalog says otherwise (so no unique key and no guard trigger sees the clash) is refused when it is read."""
    first_ref = await store.put_team_spec(_SPEC)
    assert (_RIVAL_SPEC.team_id, _RIVAL_SPEC.revision) == (_SPEC.team_id, _SPEC.revision)
    assert _RIVAL_SPEC.content_ref() != first_ref
    raw = sqlite3.connect(_db_path(tmp_path))
    try:
        raw.execute(
            f"INSERT INTO elastic_team_specs {_SPEC_COLUMNS} {_SPEC_VALUES}",
            (_RIVAL_SPEC.content_ref(), "other-team", 9, 1, _RIVAL_SPEC.canonical_bytes().decode("utf-8"), 0.0),
        )
        raw.commit()
    finally:
        raw.close()
    tampered = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamIntegrityError) as read:
        await store.get_team_spec(_RIVAL_SPEC.content_ref())
    with pytest.raises(ElasticTeamIntegrityError) as put:
        await store.put_team_spec(_RIVAL_SPEC)

    assert str(read.value) == str(put.value) == "elastic_team_spec_integrity"
    assert await store.get_team_spec(first_ref) == _SPEC  # the first spec is untouched
    assert _snapshot(_db_path(tmp_path)) == tampered


async def test_identical_put_on_a_corrupt_spec_row_is_refused(store: ElasticTeamStore, tmp_path: Path) -> None:
    """R2-4 path 1: ``put_team_spec`` reads the rows that decide it through the verifier.

    The stored text parses but no longer hashes to its reference. An identical put used to see "the row exists"
    and acknowledge it, although ``get_team_spec`` refuses to return it.
    """
    ref = await store.put_team_spec(_SPEC)
    _tamper(
        _db_path(tmp_path),
        "elastic_team_specs_no_update",
        "UPDATE elastic_team_specs SET canonical_json = ? WHERE spec_ref = ?",
        (_TAMPERED_SPEC_TEXT, ref),
    )
    tampered = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamIntegrityError) as refused:
        await store.put_team_spec(_SPEC)

    assert str(refused.value) == "elastic_team_spec_integrity"
    assert _snapshot(_db_path(tmp_path)) == tampered


async def test_conflicting_put_beside_a_corrupt_spec_row_is_an_integrity_failure(
    store: ElasticTeamStore, tmp_path: Path
) -> None:
    """R2-4 path 1, the revision-conflict read: a row the store cannot verify cannot decide a conflict either."""
    ref = await store.put_team_spec(_SPEC)
    _tamper(
        _db_path(tmp_path),
        "elastic_team_specs_no_update",
        "UPDATE elastic_team_specs SET canonical_json = ? WHERE spec_ref = ?",
        (_TAMPERED_SPEC_TEXT, ref),
    )
    tampered = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamIntegrityError) as refused:
        await store.put_team_spec(_RIVAL_SPEC)  # the same (team_id, revision), other content

    assert str(refused.value) == "elastic_team_spec_integrity"
    assert _snapshot(_db_path(tmp_path)) == tampered


async def test_identical_record_on_a_corrupt_attempt_row_is_refused(store: ElasticTeamStore, tmp_path: Path) -> None:
    """R2-4 path 3: re-recording an attempt compared the stored DIGEST COLUMN with the new digest, so a row whose
    content no longer matches that column was acknowledged as an idempotent repeat."""
    ref = await store.put_team_spec(_SPEC)
    attempt = await store.record_attempt(_attempt(ref))
    _tamper(
        _db_path(tmp_path),
        "elastic_worker_attempts_no_update",
        "UPDATE elastic_worker_attempts SET execution_profile_ref = ? WHERE worker_attempt_id = ?",
        (_PROFILE_B, attempt.worker_attempt_id),
    )
    tampered = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamIntegrityError) as refused:
        await store.record_attempt(_attempt(ref))  # the identical attempt

    assert str(refused.value) == "elastic_attempt_integrity"
    assert _snapshot(_db_path(tmp_path)) == tampered


async def test_admission_refuses_a_history_row_with_a_bad_digest(store: ElasticTeamStore, tmp_path: Path) -> None:
    """R2-4 path 4: every row of the slot's history is digest-verified before it is counted.

    The ordinals are contiguous (1, 2) and the predecessor is intact; only attempt 1's digest column was altered.
    Admission used to read just the ordinals and admit attempt 3.
    """
    ref = await store.put_team_spec(_SPEC)
    first = await store.record_attempt(_attempt(ref))
    await store.record_attempt_outcome(_failed(first))
    second = await store.record_attempt(_attempt(ref, ordinal=2, supersedes=first.worker_attempt_id))
    await store.record_attempt_outcome(_failed(second))
    _tamper(
        _db_path(tmp_path),
        "elastic_worker_attempts_no_update",
        "UPDATE elastic_worker_attempts SET attempt_digest = ? WHERE worker_attempt_id = ?",
        ("c" * 64, first.worker_attempt_id),
    )
    tampered = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamIntegrityError) as refused:
        await store.record_attempt(_attempt(ref, ordinal=3, supersedes=second.worker_attempt_id))

    assert str(refused.value) == "elastic_attempt_integrity"
    assert _snapshot(_db_path(tmp_path)) == tampered


async def test_admission_refuses_a_gapped_history_whose_rows_all_verify(
    store: ElasticTeamStore, tmp_path: Path
) -> None:
    """The gap check on its own. ``test_admission_refuses_a_noncontiguous_history_as_an_integrity_failure`` plants its
    ordinal-3 row with a placeholder digest, so since R4 that row is refused by the digest check before the gap is
    ever reached. Here the planted row is genuine (its digest verifies), so only the missing ordinals 1..2 can refuse."""
    ref = await store.put_team_spec(_SPEC)
    genuine = _attempt(ref, ordinal=3)
    raw = sqlite3.connect(_db_path(tmp_path))
    try:
        raw.execute(
            f"INSERT INTO elastic_worker_attempts {_ATTEMPT_COLUMNS} {_ATTEMPT_VALUES}",
            (genuine.worker_attempt_id, ref, "session-parent", "analyse", 3, _PROFILE_A, None, genuine.content_ref(), 0.0),
        )
        raw.commit()
    finally:
        raw.close()
    tampered = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamIntegrityError) as refused:
        await store.record_attempt(_attempt(ref, ordinal=2))

    assert str(refused.value) == "elastic_attempt_integrity"
    assert _snapshot(_db_path(tmp_path)) == tampered


@pytest.mark.parametrize("statement", _MALFORMED_OUTCOME_UPDATES)
async def test_admission_refuses_a_malformed_predecessor_outcome(
    store: ElasticTeamStore, tmp_path: Path, statement: str
) -> None:
    """R2-4 path 5: the predecessor's outcome is shape-verified, not just read for its status.

    The tampered outcome still says ``failed`` (the old check read only the status), but it can no longer have
    been recorded by this store, so the replacement is refused with the outcome integrity code.
    """
    ref = await store.put_team_spec(_SPEC)
    first = await store.record_attempt(_attempt(ref))
    await store.record_attempt_outcome(_failed(first))
    _tamper(_db_path(tmp_path), "elastic_attempt_outcomes_no_update", statement, (first.worker_attempt_id,))
    tampered = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamIntegrityError) as refused:
        await store.record_attempt(_attempt(ref, ordinal=2, supersedes=first.worker_attempt_id))

    assert str(refused.value) == "elastic_attempt_outcome_integrity"
    assert _snapshot(_db_path(tmp_path)) == tampered


async def test_outcome_for_a_corrupt_attempt_is_refused(store: ElasticTeamStore, tmp_path: Path) -> None:
    """R2-4 path 6, the "known attempt" read: an outcome is not recorded against an attempt row the store cannot
    verify (it used to read ``SELECT 1`` and record it)."""
    ref = await store.put_team_spec(_SPEC)
    attempt = await store.record_attempt(_attempt(ref))
    _tamper(
        _db_path(tmp_path),
        "elastic_worker_attempts_no_update",
        "UPDATE elastic_worker_attempts SET execution_profile_ref = ? WHERE worker_attempt_id = ?",
        (_PROFILE_B, attempt.worker_attempt_id),
    )
    tampered = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamIntegrityError) as refused:
        await store.record_attempt_outcome(_failed(attempt))

    assert str(refused.value) == "elastic_attempt_integrity"
    assert _snapshot(_db_path(tmp_path)) == tampered


@pytest.mark.parametrize("statement", _MALFORMED_OUTCOME_UPDATES)
async def test_identical_outcome_on_a_malformed_row_is_refused(
    store: ElasticTeamStore, tmp_path: Path, statement: str
) -> None:
    """R2-4 path 6, the existing-outcome read: an identical repeat is not acknowledged from a row that no longer
    validates (it used to rebuild it unchecked and return it)."""
    ref = await store.put_team_spec(_SPEC)
    attempt = await store.record_attempt(_attempt(ref))
    await store.record_attempt_outcome(_failed(attempt))
    _tamper(_db_path(tmp_path), "elastic_attempt_outcomes_no_update", statement, (attempt.worker_attempt_id,))
    tampered = _snapshot(_db_path(tmp_path))

    with pytest.raises(ElasticTeamIntegrityError) as refused:
        await store.record_attempt_outcome(_failed(attempt))

    assert str(refused.value) == "elastic_attempt_outcome_integrity"
    assert _snapshot(_db_path(tmp_path)) == tampered


@pytest.mark.parametrize("statement", _MALFORMED_OUTCOME_UPDATES)
async def test_get_attempt_outcome_refuses_a_malformed_row(
    store: ElasticTeamStore, tmp_path: Path, caplog: pytest.LogCaptureFixture, statement: str
) -> None:
    """R2-4 path 7: a malformed outcome row is an integrity failure, not a raw ``ValidationError`` or a value."""
    ref = await store.put_team_spec(_SPEC)
    attempt = await store.record_attempt(_attempt(ref))
    await store.record_attempt_outcome(_failed(attempt))
    _tamper(_db_path(tmp_path), "elastic_attempt_outcomes_no_update", statement, (attempt.worker_attempt_id,))
    tampered = _snapshot(_db_path(tmp_path))

    with caplog.at_level(logging.ERROR, logger="probos.cognitive.elastic_team_store"):
        with pytest.raises(ElasticTeamIntegrityError) as refused:
            await store.get_attempt_outcome(attempt.worker_attempt_id)

    assert str(refused.value) == "elastic_attempt_outcome_integrity"
    assert [r for r in caplog.records if "no longer validates as an outcome" in r.getMessage()]
    assert _snapshot(_db_path(tmp_path)) == tampered


@pytest.mark.parametrize("bad_clock", [float("nan"), float("inf"), True, "now", None], ids=repr)
async def test_a_clock_that_is_not_a_finite_real_refuses_writes_and_writes_nothing(
    tmp_path: Path, bad_clock: Any
) -> None:
    clock = _Clock(1000.0)
    timed = _new_store(tmp_path, clock=clock)
    await timed.start()
    try:
        ref = await timed.put_team_spec(_SPEC)
        written = _snapshot(_db_path(tmp_path))
        clock.t = bad_clock

        with pytest.raises(ElasticTeamStoreUnavailable, match="elastic_team_clock_invalid"):
            await timed.put_team_spec(_spec(revision=2))
        with pytest.raises(ElasticTeamStoreUnavailable, match="elastic_team_clock_invalid"):
            await timed.record_attempt(_attempt(ref))

        assert _snapshot(_db_path(tmp_path)) == written
        clock.t = 1000.0  # the store recovers as soon as the clock does
        assert (await timed.record_attempt(_attempt(ref))).ordinal == 1
    finally:
        await timed.stop()


async def test_integer_clock_is_accepted_and_stored_as_a_float(tmp_path: Path) -> None:
    timed = _new_store(tmp_path, clock=_Clock(1000))
    await timed.start()
    try:
        await timed.put_team_spec(_SPEC)
    finally:
        await timed.stop()

    created = _snapshot(_db_path(tmp_path), "elastic_team_specs")["elastic_team_specs"][0][5]
    assert created == 1000.0 and type(created) is float


class _RecordingConnection:
    """Delegates to the real connection and records every ``execute`` statement."""

    def __init__(self, inner: Any, statements: list[str]) -> None:
        self._inner = inner
        self._statements = statements

    async def execute(self, sql: str, parameters: Any = ()) -> Any:
        self._statements.append(sql)
        return await self._inner.execute(sql, parameters)

    async def executescript(self, sql_script: str) -> None:
        await self._inner.executescript(sql_script)

    async def commit(self) -> None:
        await self._inner.commit()

    async def close(self) -> None:
        await self._inner.close()


class _RecordingFactory:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def connect(self, db_path: str) -> _RecordingConnection:
        return _RecordingConnection(await SQLiteConnectionFactory().connect(db_path), self.statements)


_CONFLICT_CLAUSE = re.compile(r"\bOR\s+(REPLACE|IGNORE|ABORT|FAIL|ROLLBACK)\b|\bREPLACE\s+INTO\b|\bON\s+CONFLICT\b", re.I)


async def test_store_issues_plain_inserts_only_and_idempotent_repeats_write_nothing(tmp_path: Path) -> None:
    factory = _RecordingFactory()
    recording = ElasticTeamStore(db_path=str(_db_path(tmp_path)), connection_factory=factory, clock=_Clock(1000.0))
    await recording.start()
    try:
        ref = await recording.put_team_spec(_SPEC)
        await recording.put_team_spec(_SPEC)  # idempotent repeat
        first = await recording.record_attempt(_attempt(ref))
        await recording.record_attempt(_attempt(ref))  # idempotent repeat
        await recording.record_attempt_outcome(_failed(first))
        await recording.record_attempt_outcome(_failed(first, at=9999.0))  # idempotent repeat
        await recording.record_attempt(_attempt(ref, ordinal=2, supersedes=first.worker_attempt_id))
        await recording.get_team_spec(ref)
        await recording.get_attempt(first.worker_attempt_id)
        await recording.list_slot_attempts(session_id="session-parent", team_spec_ref=ref, slot_id="analyse")
        await recording.get_attempt_outcome(first.worker_attempt_id)
    finally:
        await recording.stop()

    inserts = [statement for statement in factory.statements if "INSERT" in statement.upper()]
    assert not [statement for statement in factory.statements if _CONFLICT_CLAUSE.search(statement)]
    assert all(statement.startswith("INSERT INTO ") for statement in inserts)
    for table, expected in (
        ("elastic_team_specs", 1),
        ("elastic_worker_slots", 2),  # one per slot, written with the spec only
        ("elastic_worker_attempts", 2),
        ("elastic_attempt_outcomes", 1),
    ):
        assert len([statement for statement in inserts if f"INSERT INTO {table} " in statement]) == expected, table


async def test_put_team_spec_logs_only_when_a_new_spec_is_inserted(
    store: ElasticTeamStore, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="probos.cognitive.elastic_team_store"):
        ref = await store.put_team_spec(_SPEC)
        await store.put_team_spec(_SPEC)

    stored = [record for record in caplog.records if "stored team spec" in record.getMessage()]
    assert len(stored) == 1
    assert ref in stored[0].getMessage() and "AD-1286" in stored[0].getMessage()
