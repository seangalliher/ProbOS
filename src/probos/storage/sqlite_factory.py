"""Default SQLite connection factory using aiosqlite."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from probos.protocols import ConnectionFactory, DatabaseConnection


class SQLiteConnectionFactory:
    """Default ConnectionFactory implementation wrapping aiosqlite.

    This is the out-of-the-box backend for all ProbOS DB modules.
    """

    async def connect(self, db_path: str, *, read_only: bool = False) -> DatabaseConnection:
        """Open an aiosqlite connection.

        The returned connection satisfies DatabaseConnection protocol.
        aiosqlite.Connection already implements execute/executemany/
        executescript/commit/close — no wrapper needed.

        BF-906: ``read_only=True`` opens an existing database through SQLite's
        ``mode=ro`` URI. It never creates the database file (a missing one raises
        ``sqlite3.OperationalError``), never changes its contents, and every write
        raises. One side effect remains: opening a WAL-mode database may create
        its ``-wal`` and ``-shm`` files, as any reader of a WAL database does when
        the directory is writable (SQLite wal.html section 5; measured on 3.50.4
        after a clean close). ``immutable=1`` would avoid them but is unsafe while
        the vessel writes. It is SQLite-specific and deliberately not part of the
        ``ConnectionFactory`` protocol. The default path is unchanged: ``uri=False``
        is sqlite3's own default.
        """
        target = f"{Path(db_path).resolve().as_uri()}?mode=ro" if read_only else db_path
        conn = await aiosqlite.connect(target, uri=read_only)
        return conn  # type: ignore[return-value]  # aiosqlite.Connection satisfies protocol


# Module-level singleton for convenience
default_factory = SQLiteConnectionFactory()
