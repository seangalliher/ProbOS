"""Default SQLite connection factory using aiosqlite."""

from __future__ import annotations

import aiosqlite

from probos.protocols import ConnectionFactory, DatabaseConnection


class SQLiteConnectionFactory:
    """Default ConnectionFactory implementation wrapping aiosqlite.

    This is the out-of-the-box backend for all ProbOS DB modules.
    """

    async def connect(self, db_path: str) -> DatabaseConnection:
        """Open an aiosqlite connection.

        The returned connection satisfies DatabaseConnection protocol.
        aiosqlite.Connection already implements execute/executemany/
        executescript/commit/close — no wrapper needed.
        """
        conn = await aiosqlite.connect(db_path)
        return conn  # type: ignore[return-value]  # aiosqlite.Connection satisfies protocol


# Module-level singleton for convenience
default_factory = SQLiteConnectionFactory()
