"""AD-573: Tests for WorkingMemoryStore — SQLite persistence layer."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.working_memory_store import WorkingMemoryStore


def _mock_factory():
    """Build a mock ConnectionFactory + connection."""
    conn = AsyncMock()
    conn.executescript = AsyncMock()
    conn.execute = AsyncMock()
    conn.commit = AsyncMock()
    conn.rollback = AsyncMock()
    conn.close = AsyncMock()

    factory = MagicMock()
    factory.connect = AsyncMock(return_value=conn)
    return factory, conn


class TestWorkingMemoryStore:
    """WorkingMemoryStore lifecycle and CRUD operations."""

    @pytest.mark.asyncio
    async def test_start_creates_schema(self):
        factory, conn = _mock_factory()
        store = WorkingMemoryStore(connection_factory=factory, db_path="test.db")
        await store.start()
        conn.executescript.assert_called_once()
        conn.commit.assert_called()

    @pytest.mark.asyncio
    async def test_stop_closes_connection(self):
        factory, conn = _mock_factory()
        store = WorkingMemoryStore(connection_factory=factory, db_path="test.db")
        await store.start()
        await store.stop()
        conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_inserts_state(self):
        factory, conn = _mock_factory()
        store = WorkingMemoryStore(connection_factory=factory, db_path="test.db")
        await store.start()
        await store.save("agent-1", {"key": "value"})
        # Should have BEGIN IMMEDIATE + INSERT
        calls = [c[0][0] for c in conn.execute.call_args_list]
        assert any("BEGIN" in c for c in calls)
        assert any("INSERT" in c for c in calls)

    @pytest.mark.asyncio
    async def test_save_all_batch(self):
        factory, conn = _mock_factory()
        store = WorkingMemoryStore(connection_factory=factory, db_path="test.db")
        await store.start()
        states = {"a1": {"x": 1}, "a2": {"y": 2}}
        await store.save_all(states)
        # 1 BEGIN + 2 INSERTs
        insert_calls = [c for c in conn.execute.call_args_list if "INSERT" in str(c)]
        assert len(insert_calls) == 2

    @pytest.mark.asyncio
    async def test_load_returns_none_when_empty(self):
        factory, conn = _mock_factory()
        cursor = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=None)
        conn.execute = AsyncMock(return_value=cursor)
        store = WorkingMemoryStore(connection_factory=factory, db_path="test.db")
        await store.start()
        result = await store.load("agent-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_op_without_connection(self):
        """Operations are no-ops when store has no connection."""
        store = WorkingMemoryStore()
        await store.save("a1", {"x": 1})
        await store.save_all({"a1": {"x": 1}})
        result = await store.load("a1")
        assert result is None
        all_result = await store.load_all()
        assert all_result == {}

    @pytest.mark.asyncio
    async def test_clear(self):
        factory, conn = _mock_factory()
        store = WorkingMemoryStore(connection_factory=factory, db_path="test.db")
        await store.start()
        await store.clear()
        delete_calls = [c for c in conn.execute.call_args_list if "DELETE" in str(c)]
        assert len(delete_calls) == 1
