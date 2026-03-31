"""AD-542: Tests for abstract database connection interface."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.protocols import ConnectionFactory, DatabaseConnection
from probos.storage.sqlite_factory import SQLiteConnectionFactory, default_factory


# ---------------------------------------------------------------------------
# 1. SQLiteConnectionFactory returns a DatabaseConnection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sqlite_factory_returns_connection() -> None:
    """SQLiteConnectionFactory.connect() returns object satisfying DatabaseConnection protocol."""
    factory = SQLiteConnectionFactory()
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        conn = await factory.connect(db_path)
        try:
            # aiosqlite.Connection structurally satisfies DatabaseConnection.
            # Verify by checking all required methods exist and are callable.
            for method in ("execute", "executemany", "executescript", "commit", "close"):
                assert hasattr(conn, method), f"Missing method: {method}"
                assert callable(getattr(conn, method)), f"Not callable: {method}"
        finally:
            await conn.close()


# ---------------------------------------------------------------------------
# 2. Connection execute and commit roundtrip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_execute_and_commit() -> None:
    """Create table, insert, select — verify data roundtrips."""
    factory = SQLiteConnectionFactory()
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        conn = await factory.connect(db_path)
        try:
            await conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")
            await conn.execute("INSERT INTO test (id, val) VALUES (?, ?)", (1, "hello"))
            await conn.commit()
            async with conn.execute("SELECT val FROM test WHERE id = ?", (1,)) as cursor:
                row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "hello"
        finally:
            await conn.close()


# ---------------------------------------------------------------------------
# 3. Connection executescript
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_executescript() -> None:
    """Verify executescript() works with multi-statement SQL."""
    factory = SQLiteConnectionFactory()
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        conn = await factory.connect(db_path)
        try:
            await conn.executescript("""
                CREATE TABLE a (id INTEGER PRIMARY KEY);
                CREATE TABLE b (id INTEGER PRIMARY KEY);
                INSERT INTO a VALUES (1);
                INSERT INTO b VALUES (2);
            """)
            await conn.commit()
            async with conn.execute("SELECT COUNT(*) FROM a") as cursor:
                row = await cursor.fetchone()
            assert row[0] == 1
            async with conn.execute("SELECT COUNT(*) FROM b") as cursor:
                row = await cursor.fetchone()
            assert row[0] == 1
        finally:
            await conn.close()


# ---------------------------------------------------------------------------
# 4. Connection close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_close() -> None:
    """Verify close() completes without error."""
    factory = SQLiteConnectionFactory()
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        conn = await factory.connect(db_path)
        await conn.close()  # Should not raise


# ---------------------------------------------------------------------------
# 5. Default factory singleton
# ---------------------------------------------------------------------------


def test_default_factory_singleton() -> None:
    """default_factory is importable and is a SQLiteConnectionFactory instance."""
    assert isinstance(default_factory, SQLiteConnectionFactory)


# ---------------------------------------------------------------------------
# 6. Custom factory injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_factory_injected() -> None:
    """Mock ConnectionFactory injected into EventLog — start() uses it."""
    from probos.substrate.event_log import EventLog

    mock_conn = AsyncMock()
    mock_factory = AsyncMock(spec=ConnectionFactory)
    mock_factory.connect.return_value = mock_conn

    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "events.db")
        log = EventLog(db_path=db_path, connection_factory=mock_factory)
        await log.start()
        mock_factory.connect.assert_called_once_with(db_path)
        await log.stop()


# ---------------------------------------------------------------------------
# 7. None factory defaults to SQLite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_none_factory_defaults_to_sqlite() -> None:
    """When connection_factory=None, module uses SQLiteConnectionFactory internally."""
    from probos.substrate.event_log import EventLog

    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "events.db")
        log = EventLog(db_path=db_path)
        assert isinstance(log._connection_factory, SQLiteConnectionFactory)
        await log.start()
        assert log._db is not None
        await log.stop()


# ---------------------------------------------------------------------------
# 8. ACM uses factory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acm_uses_factory() -> None:
    """AgentCapitalService(data_dir, connection_factory=mock) calls mock.connect() in start()."""
    from probos.acm import AgentCapitalService

    mock_conn = AsyncMock()
    mock_factory = AsyncMock(spec=ConnectionFactory)
    mock_factory.connect.return_value = mock_conn

    with tempfile.TemporaryDirectory() as td:
        svc = AgentCapitalService(data_dir=td, connection_factory=mock_factory)
        await svc.start()
        mock_factory.connect.assert_called_once()
        await svc.stop()


# ---------------------------------------------------------------------------
# 9. EventLog uses factory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_log_uses_factory() -> None:
    """EventLog(db_path, connection_factory=mock) calls mock.connect() in start()."""
    from probos.substrate.event_log import EventLog

    mock_conn = AsyncMock()
    mock_factory = AsyncMock(spec=ConnectionFactory)
    mock_factory.connect.return_value = mock_conn

    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "events.db")
        log = EventLog(db_path=db_path, connection_factory=mock_factory)
        await log.start()
        mock_factory.connect.assert_called_once_with(db_path)
        await log.stop()


# ---------------------------------------------------------------------------
# 10. WardRoomService uses factory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ward_room_uses_factory() -> None:
    """WardRoomService uses injected connection_factory in start()."""
    from probos.ward_room import WardRoomService

    # Use a real SQLite connection through the factory, just verify it was injected.
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "ward_room.db")
        factory = SQLiteConnectionFactory()
        svc = WardRoomService(db_path=db_path, connection_factory=factory)
        assert svc._connection_factory is factory
        await svc.start()
        assert svc._db is not None
        await svc.stop()
