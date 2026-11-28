"""BF-1006 (#1870): test-run SQLite connections start without commit flushes; ``os.fsync`` does nothing.

At 16 xdist workers the test volume completed about 600 synchronous writes per second however
many workers asked (#1870, runs A and B, 2026-11-28). A worker's boot-heavy first test spent
about half of its 80-180 s inside SQLite commits at about 130 ms each, and pytest-timeout
(180 s) killed seven workers. With the flushes off the same tests took 28-36 s and no worker
was lost.

What the hook does, from ``pytest_configure`` to ``pytest_unconfigure`` (``tests/conftest.py``):

* ``sqlite3.connect`` is wrapped. Every argument passes through unchanged. On the new
  connection the wrapper runs ``PRAGMA synchronous=OFF`` once, with the connection's busy
  timeout at 0 for that one statement and then put back to what it was, even when the
  statement fails. ``PRAGMA synchronous`` reads the schema, so on a database another
  connection holds it would otherwise wait the whole timeout before the caller could set a
  shorter one of its own; with the bracket it fails at once. The three statements that set the
  timeout and the level go through ``sqlite3.Connection.execute`` itself; the timeout is read
  on a cursor the wrapper makes with ``sqlite3.Connection.cursor`` and whose row factory it sets
  to ``None``. So a connection subclass's own ``execute`` or ``cursor`` neither sees nor changes
  any of the four, and the connection's row factory is neither called nor changed (A2).
  aiosqlite opens its connection through ``sqlite3.connect`` in its worker thread, so aiosqlite
  connections are covered too.
* ``os.fsync`` does nothing.

What it changes, and what it does not. It changes the level a connection starts with, not
every commit. A store that sets its own level after connecting keeps it: the AD-1315 authority
sets FULL on purpose and still flushes. A store that sets no level (``ProfileStore`` among
them) runs at OFF. So no test may assert a connection's default: a test reads a store's level
on the store's own connection, never on one it opened itself. A connection that finds its
database locked when it opens keeps SQLite's default (FULL). A write still reaches the
operating system's cache before the call returns, so every reader in the run sees it, and a
process that is killed keeps its data; only an operating-system crash or a power loss could
lose it, and no test simulates either. Connections that do not go through Python's ``sqlite3``
(ChromaDB's own SQLite) and child processes a test starts still flush.

A failing PRAGMA (a locked database, a file that is not a database, a connection opened inside
a transaction) logs a warning and the connection is returned as it is; when delivering that
warning fails, the connection is still returned. The hook never fails a connection.
``PROBOS_TEST_DURABLE_WRITES=1``, read once when pytest configures, leaves both functions as
they are.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable, Mapping
from typing import Any

OPT_OUT_ENV = "PROBOS_TEST_DURABLE_WRITES"
PRAGMA = "PRAGMA synchronous=OFF"

_LOG = logging.getLogger(__name__)
_originals: dict[str, Callable[..., Any]] = {}


def no_fsync(fd: Any) -> None:
    """``os.fsync`` for a test run: the bytes stay in the operating system's cache."""
    return None


def _turn_off_commit_flush(connection: sqlite3.Connection) -> None:
    """``PRAGMA synchronous=OFF`` on ``connection``, failing at once on a lock, through the base class."""
    # A2: the timeout is read on a cursor of the hook's own with no row factory, so the connection's row
    # factory (a caller's dict rows, a counter) is neither called nor changed; the base class's ``cursor``
    # keeps a subclass's override out of it. The other statements' rows are never fetched.
    reader = sqlite3.Connection.cursor(connection)
    reader.row_factory = None
    try:
        prior = int(reader.execute("PRAGMA busy_timeout").fetchone()[0])
    finally:
        reader.close()
    sqlite3.Connection.execute(connection, "PRAGMA busy_timeout=0")
    try:
        sqlite3.Connection.execute(connection, PRAGMA)
    finally:
        sqlite3.Connection.execute(connection, f"PRAGMA busy_timeout={prior}")


def _warn_default_kept() -> None:
    # Called from the ``except`` in ``connect``, so ``exc_info`` names the refusal.
    try:
        _LOG.warning(
            "BF-1006: %s failed on a new connection; it keeps SQLite's default",
            PRAGMA,
            exc_info=True,
        )
    except Exception:
        # Swallow: the warning is this path's only report and delivering it failed (a handler that
        # raises). The hook never fails a connection (D4), so the connection is returned without it.
        pass


def _without_flush(
    real_connect: Callable[..., sqlite3.Connection],
) -> Callable[..., sqlite3.Connection]:
    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        try:
            _turn_off_commit_flush(connection)
        except Exception:
            _warn_default_kept()
        return connection

    connect.__wrapped__ = real_connect  # type: ignore[attr-defined]
    return connect


def installed() -> bool:
    """Whether the hook is installed in this process."""
    return bool(_originals)


def install_no_commit_flush(environ: Mapping[str, str] | None = None) -> bool:
    """Install the hook unless ``PROBOS_TEST_DURABLE_WRITES=1``; return whether it is installed.

    ``environ`` defaults to ``os.environ``. A second call while it is installed changes nothing.
    """
    if _originals:
        return True
    source = os.environ if environ is None else environ
    if source.get(OPT_OUT_ENV) == "1":
        return False
    _originals["connect"] = sqlite3.connect
    _originals["fsync"] = os.fsync
    sqlite3.connect = _without_flush(sqlite3.connect)  # type: ignore[assignment]
    os.fsync = no_fsync
    return True


def uninstall_no_commit_flush() -> None:
    """Put back the two functions the hook replaced; nothing to do when it is not installed."""
    if not _originals:
        return
    sqlite3.connect = _originals.pop("connect")  # type: ignore[assignment]
    os.fsync = _originals.pop("fsync")
