"""BF-1006 (#1870): the test suite's no-flush hook (``tests/fixtures/no_commit_flush.py``).

``tests/conftest.py`` installs the hook for the whole session, and these tests read what it changed on real
connections; every refusal they provoke is SQLite's own (A1). The opt-out test takes the hook down and puts it back in a
``finally``. SQLite's own connection default
is FULL (2) here and in CI: ``tests/test_ad1315_protected_execution_authority.py`` read 2 on a fresh connection on
both before this change.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from probos.storage.sqlite_factory import default_factory
from tests.fixtures import no_commit_flush as ncf

pytestmark = pytest.mark.skipif(
    os.environ.get(ncf.OPT_OUT_ENV) == "1", reason="BF-1006: this run opted out of the no-flush hook"
)

_OFF, _NORMAL, _FULL = 0, 1, 2
_DEFAULT_BUSY_TIMEOUT_MS = 5000  # sqlite3.connect's default timeout of 5.0 s


def _level(connection: sqlite3.Connection) -> int:
    return connection.execute("PRAGMA synchronous").fetchone()[0]


def _busy_timeout(connection: sqlite3.Connection) -> int:
    return connection.execute("PRAGMA busy_timeout").fetchone()[0]


def _assert_one_warning(caplog: pytest.LogCaptureFixture) -> None:
    records = [record for record in caplog.records if record.name == ncf.__name__]
    assert len(records) == 1 and records[0].levelno == logging.WARNING, records
    assert "BF-1006" in records[0].getMessage()


def test_a_bare_connection_reads_synchronous_off(tmp_path: Path) -> None:
    assert ncf.installed(), "premise: tests/conftest.py installed the hook for this session"
    connection = sqlite3.connect(tmp_path / "bare.db")
    try:
        assert _level(connection) == _OFF
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("statement", "level"),
    [("PRAGMA synchronous=NORMAL", _NORMAL), ("PRAGMA synchronous=FULL", _FULL)],
    ids=["normal", "full"],
)
def test_a_stores_own_level_after_connect_wins(tmp_path: Path, statement: str, level: int) -> None:
    connection = sqlite3.connect(tmp_path / "store.db")
    try:
        assert _level(connection) == _OFF, "premise: the hook set OFF at connect"
        connection.execute(statement)
        assert _level(connection) == level
    finally:
        connection.close()


async def test_aiosqlite_and_the_store_factory_connect_through_the_hook(tmp_path: Path) -> None:
    async with aiosqlite.connect(str(tmp_path / "raw.db")) as raw:
        cursor = await raw.execute("PRAGMA synchronous")
        assert (await cursor.fetchone())[0] == _OFF
    store = await default_factory.connect(str(tmp_path / "store.db"))
    try:
        cursor = await store.execute("PRAGMA synchronous")
        assert (await cursor.fetchone())[0] == _OFF
    finally:
        await store.close()


def test_os_fsync_does_nothing_during_the_run() -> None:
    assert os.fsync is ncf.no_fsync
    assert os.fsync(-1) is None  # the real call raises OSError for a descriptor that is not open


def test_every_connect_argument_passes_through(tmp_path: Path) -> None:
    class Recording(sqlite3.Connection):
        pass

    by_keyword = sqlite3.connect(
        str(tmp_path / "keyword.db"),
        timeout=1.5,
        detect_types=sqlite3.PARSE_DECLTYPES,
        isolation_level=None,
        check_same_thread=False,
        factory=Recording,
        cached_statements=7,
        uri=False,
        autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,
    )
    by_uri = sqlite3.connect((tmp_path / "uri.db").as_uri() + "?mode=rwc", uri=True)
    try:
        assert type(by_keyword) is Recording
        assert by_keyword.isolation_level is None
        assert by_keyword.autocommit == sqlite3.LEGACY_TRANSACTION_CONTROL
        assert _level(by_keyword) == _OFF
        assert _busy_timeout(by_keyword) == 1500, "the hook put the caller's timeout back"
        assert (tmp_path / "uri.db").is_file(), "the uri flag reached SQLite"
        assert _level(by_uri) == _OFF
    finally:
        by_keyword.close()
        by_uri.close()


@pytest.mark.parametrize("refusal", ["not-a-database", "inside-a-transaction"])
def test_a_genuine_refusal_logs_one_warning_and_returns_the_connection(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, refusal: str
) -> None:
    """SQLite itself refuses the PRAGMA: the file is not a database, or Python opened a transaction at connect
    (``autocommit=False``) and SQLite does not change the safety level inside one."""
    path = tmp_path / "refused.db"
    if refusal == "not-a-database":
        path.write_bytes(b"this is not an SQLite database file. " * 64)
    with caplog.at_level(logging.WARNING, logger=ncf.__name__):
        if refusal == "not-a-database":
            connection = sqlite3.connect(path)
        else:
            connection = sqlite3.connect(path, autocommit=False)
    try:
        _assert_one_warning(caplog)
        if refusal == "inside-a-transaction":
            assert _level(connection) == _FULL, "the refused PRAGMA left SQLite's default"
            assert _busy_timeout(connection) == _DEFAULT_BUSY_TIMEOUT_MS, "the timeout is back after the refusal"
    finally:
        connection.close()


def test_a_locked_database_fails_the_pragma_at_once_and_keeps_the_callers_timeout(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """``PRAGMA synchronous`` reads the schema. Run plainly on a database another connection holds, it waited longer
    than the caller's whole timeout (round 1: 7.84 s for the doctor check's read, whose own 0.1 s busy timeout comes
    only after the connect). With the busy timeout at 0 for that statement it fails at once."""
    path = tmp_path / "locked.db"
    holder = sqlite3.connect(path, isolation_level=None)
    try:
        holder.execute("CREATE TABLE t (x)")  # rollback-journal mode, SQLite's default
        holder.execute("BEGIN EXCLUSIVE")
        with caplog.at_level(logging.WARNING, logger=ncf.__name__):
            started = time.monotonic()
            connection = sqlite3.connect(path, timeout=2.0)
            elapsed = time.monotonic() - started
    finally:
        holder.close()  # closing the connection rolls the open transaction back
    try:
        assert elapsed < 1.0, f"the connect waited {elapsed:.2f}s on the lock"
        assert _busy_timeout(connection) == 2000, "the caller's timeout is back"
        assert _level(connection) == _FULL, "a connection that found the database locked keeps SQLite's default"
        _assert_one_warning(caplog)
    finally:
        connection.close()


def test_the_hook_runs_its_statements_on_the_base_class(tmp_path: Path) -> None:
    """A subclass that records and intercepts ``execute`` neither sees the hook's statements nor stops them."""

    class Intercepting(sqlite3.Connection):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]
            self.seen: list[str] = []

        def execute(self, sql: str, *args: object) -> sqlite3.Cursor:  # type: ignore[override]
            self.seen.append(sql)
            if sql.upper().startswith("PRAGMA"):
                return super().execute("SELECT 0")  # swallows every PRAGMA it is handed
            return super().execute(sql, *args)

    connection = sqlite3.connect(str(tmp_path / "subclass.db"), factory=Intercepting, timeout=1.5)
    try:
        assert type(connection) is Intercepting
        assert connection.seen == [], "the hook's statements bypass the subclass"
        level = sqlite3.Connection.execute(connection, "PRAGMA synchronous").fetchone()[0]
        timeout = sqlite3.Connection.execute(connection, "PRAGMA busy_timeout").fetchone()[0]
        assert (level, timeout) == (_OFF, 1500)
    finally:
        connection.close()


def _caller_rows(shape: str) -> tuple[type[sqlite3.Connection], Callable[..., Any], list[str]]:
    """A connection subclass whose ``__init__`` sets a row factory, as a caller's may. ``made`` records each row the
    factory builds and each call of the subclass's ``cursor``. ``dict-rows`` builds dicts keyed by column name (so
    ``row[0]`` raises ``KeyError``); ``tuple-rows`` returns the plain tuple."""
    made: list[str] = []

    def make_row(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> Any:
        made.append("row")
        if shape == "dict-rows":
            return {column[0]: value for column, value in zip(cursor.description, row, strict=True)}
        return row

    class Rows(sqlite3.Connection):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.row_factory = make_row

        def cursor(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:  # type: ignore[override]
            made.append("cursor")
            return super().cursor(*args, **kwargs)

    return Rows, make_row, made


def _only_value(row: Any) -> Any:
    values = list(row.values()) if isinstance(row, dict) else list(row)
    assert len(values) == 1, row
    return values[0]


def _hook_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == ncf.__name__]


@pytest.mark.parametrize("shape", ["dict-rows", "tuple-rows"])
def test_the_callers_row_factory_is_neither_called_nor_changed_by_the_hook(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, shape: str
) -> None:
    """A2 (Diff Reviewer round 2): the A1 hook read the busy timeout through the connection's row factory, so a
    caller's dict rows made ``[0]`` raise ``KeyError`` (the connection stayed at FULL, with a warning) and a counting
    factory was called during connect. The hook now reads it on a cursor of its own with no row factory."""
    rows, make_row, made = _caller_rows(shape)
    with caplog.at_level(logging.WARNING, logger=ncf.__name__):
        connection = sqlite3.connect(str(tmp_path / "rows.db"), factory=rows, timeout=1.5)
    try:
        assert made == [], "the hook built no row through the caller's factory and called no override of cursor"
        assert _hook_records(caplog) == []
        assert connection.row_factory is make_row, "the caller's row factory is still the connection's"
        assert _only_value(connection.execute("PRAGMA synchronous").fetchone()) == _OFF
        assert _only_value(connection.execute("PRAGMA busy_timeout").fetchone()) == 1500
    finally:
        connection.close()


async def test_aiosqlite_hands_the_callers_factory_to_the_hook_and_its_rows_are_left_alone(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The same through ``aiosqlite.connect``, which passes ``factory`` to ``sqlite3.connect`` in its own thread. The
    store factory (``default_factory.connect``) takes no factory, so this is how a caller's row factory reaches it."""
    rows, make_row, made = _caller_rows("dict-rows")
    with caplog.at_level(logging.WARNING, logger=ncf.__name__):
        async with aiosqlite.connect(str(tmp_path / "rows.db"), factory=rows, timeout=1.5) as connection:
            assert made == [], "the hook built no row through the caller's factory"
            assert connection.row_factory is make_row
            cursor = await connection.execute("PRAGMA synchronous")
            assert _only_value(await cursor.fetchone()) == _OFF
            cursor = await connection.execute("PRAGMA busy_timeout")
            assert _only_value(await cursor.fetchone()) == 1500
    assert _hook_records(caplog) == []


def test_a_failing_log_handler_does_not_fail_the_connection(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    called: list[str] = []

    class Fails(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            called.append(record.getMessage())
            raise RuntimeError("the handler fails")

    caplog.set_level(logging.WARNING, logger=ncf.__name__)
    handler = Fails(logging.WARNING)
    logger = logging.getLogger(ncf.__name__)
    logger.addHandler(handler)
    try:
        connection = sqlite3.connect(str(tmp_path / "refused.db"), autocommit=False)  # refused inside a transaction
    finally:
        logger.removeHandler(handler)
    try:
        assert len(called) == 1, "premise: the warning reached the failing handler"
        assert _level(connection) == _FULL
    finally:
        connection.close()


def test_a_file_that_is_not_a_database_still_opens_and_fails_at_first_use(tmp_path: Path) -> None:
    path = tmp_path / "not-a-database.db"
    path.write_bytes(b"this is not an SQLite database file. " * 64)
    connection = sqlite3.connect(path)  # the hook never fails a connection
    try:
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("SELECT name FROM sqlite_master").fetchall()
    finally:
        connection.close()


def test_the_opt_out_leaves_sqlites_default_and_the_real_fsync(tmp_path: Path) -> None:
    assert ncf.installed(), "premise: the session hook is on"
    ncf.uninstall_no_commit_flush()
    try:
        assert getattr(sqlite3.connect, "__wrapped__", None) is None, "uninstall put the real connect back"
        assert ncf.install_no_commit_flush({ncf.OPT_OUT_ENV: "1"}) is False
        assert not ncf.installed()
        assert os.fsync is not ncf.no_fsync
        connection = sqlite3.connect(tmp_path / "durable.db")
        try:
            assert _level(connection) == _FULL
        finally:
            connection.close()
        assert ncf.install_no_commit_flush({ncf.OPT_OUT_ENV: "0"}) is True, "only the value 1 opts out"
        wrapped = sqlite3.connect
        assert ncf.install_no_commit_flush({}) is True
        assert sqlite3.connect is wrapped, "a second install does not wrap twice"
    finally:
        ncf.uninstall_no_commit_flush()
        ncf.install_no_commit_flush({})
    assert ncf.installed() and os.fsync is ncf.no_fsync
