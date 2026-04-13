"""BF-164: Stale unread DM notification loop.

AD-614's exchange limit blocks agents from responding to old flood threads,
but get_unread_dms() kept returning those threads — causing infinite
BF-082 notification cycles.  Fix: get_unread_dms() excludes threads where
the agent already has >= exchange_limit posts.
"""

from __future__ import annotations

import ast
import asyncio
import textwrap
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"


# ---------------------------------------------------------------------------
# Structural tests — verify fix is present in source
# ---------------------------------------------------------------------------


class TestGetUnreadDmsExchangeLimit:
    """Structural: get_unread_dms() accepts and uses exchange_limit param."""

    def test_exchange_limit_param_exists_on_message_store(self):
        """MessageStore.get_unread_dms should accept exchange_limit parameter."""
        source = (SRC / "probos" / "ward_room" / "messages.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "get_unread_dms":
                    arg_names = [a.arg for a in node.args.args]
                    assert "exchange_limit" in arg_names, (
                        "get_unread_dms() must accept exchange_limit parameter"
                    )
                    return
        pytest.fail("get_unread_dms not found in messages.py")

    def test_exchange_limit_param_exists_on_service(self):
        """WardRoomService.get_unread_dms should accept exchange_limit parameter."""
        source = (SRC / "probos" / "ward_room" / "service.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "get_unread_dms":
                    arg_names = [a.arg for a in node.args.args]
                    assert "exchange_limit" in arg_names, (
                        "WardRoomService.get_unread_dms() must accept exchange_limit"
                    )
                    return
        pytest.fail("get_unread_dms not found in service.py")

    def test_exchange_filter_sql_in_source(self):
        """get_unread_dms should contain exchange-limit SQL filter."""
        source = (SRC / "probos" / "ward_room" / "messages.py").read_text()
        assert "exchange_filter" in source or "exchange_limit" in source
        # The SQL should count agent posts per thread
        assert "COUNT(*)" in source or "count(*)" in source.lower()


class TestCheckUnreadDmsPassesLimit:
    """Structural: _check_unread_dms passes exchange_limit from config."""

    def test_exchange_limit_passed_to_get_unread_dms(self):
        """Proactive _check_unread_dms should pass dm_exchange_limit to query."""
        source = (SRC / "probos" / "proactive.py").read_text()
        assert "exchange_limit" in source, (
            "_check_unread_dms must pass exchange_limit to get_unread_dms"
        )
        assert "dm_exchange_limit" in source, (
            "_check_unread_dms must read dm_exchange_limit from config"
        )


class TestLogAccuracy:
    """Structural: BF-082 log should report routed count, not query count."""

    def test_log_uses_routed_count(self):
        """BF-082 log should use count of actually-routed DMs, not len(unread_dms)."""
        source = (SRC / "probos" / "proactive.py").read_text()
        # Should NOT have len(unread_dms) in the BF-082 log line
        # Should have a routed counter
        assert "routed" in source, (
            "_check_unread_dms should track routed count"
        )


# ---------------------------------------------------------------------------
# Behavioral tests — verify exchange_limit filtering works
# ---------------------------------------------------------------------------


class TestExchangeLimitFiltering:
    """Behavioral: get_unread_dms excludes threads at exchange limit."""

    @pytest.fixture
    def _setup_db(self, tmp_path):
        """Create a minimal Ward Room DB with DM threads."""
        import aiosqlite

        db_path = str(tmp_path / "ward_room.db")

        async def setup():
            db = await aiosqlite.connect(db_path)
            await db.execute("PRAGMA foreign_keys = ON")
            # Minimal schema
            await db.executescript(textwrap.dedent("""\
                CREATE TABLE IF NOT EXISTS channels (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    channel_type TEXT NOT NULL DEFAULT 'department',
                    department TEXT,
                    created_by TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    archived INTEGER NOT NULL DEFAULT 0,
                    description TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    author_id TEXT NOT NULL,
                    author_callsign TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    reply_count INTEGER NOT NULL DEFAULT 0,
                    last_activity TEXT DEFAULT (datetime('now')),
                    pinned INTEGER NOT NULL DEFAULT 0,
                    archived INTEGER NOT NULL DEFAULT 0,
                    thread_mode TEXT NOT NULL DEFAULT 'discuss',
                    max_responders INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (channel_id) REFERENCES channels(id)
                );
                CREATE TABLE IF NOT EXISTS posts (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    author_id TEXT NOT NULL,
                    author_callsign TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL,
                    parent_id TEXT,
                    depth INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    deleted INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (thread_id) REFERENCES threads(id)
                );
                CREATE TABLE IF NOT EXISTS credibility (
                    agent_id TEXT PRIMARY KEY,
                    post_count INTEGER NOT NULL DEFAULT 0,
                    endorsement_count INTEGER NOT NULL DEFAULT 0,
                    restriction TEXT
                );
            """))
            await db.commit()

            # Create DM channel — name must contain agent_aa's 8-char prefix
            # so the LIKE '%agent_aa%' filter in get_unread_dms() matches.
            await db.execute(
                "INSERT INTO channels (id, name, channel_type) VALUES (?, ?, ?)",
                ("ch-dm-1", "dm-agent_aa-agent_bb", "dm"),
            )

            # Thread where agent_aa has 7 posts (over the limit of 6)
            # Thread authored by agent_bb so it shows as "unread" for agent_aa
            await db.execute(
                "INSERT INTO threads (id, channel_id, author_id, author_callsign, title, body) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("t-capped", "ch-dm-1", "agent_bb", "AgentB", "old flood", "hello"),
            )
            for i in range(7):
                await db.execute(
                    "INSERT INTO posts (id, thread_id, author_id, author_callsign, body) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (f"p-capped-{i}", "t-capped", "agent_aa", "AgentA", f"reply {i}"),
                )
            # Last post by agent_bb so it shows as "unread" for agent_aa
            await db.execute(
                "INSERT INTO posts (id, thread_id, author_id, author_callsign, body, created_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now', '+1 minute'))",
                ("p-capped-last", "t-capped", "agent_bb", "AgentB", "are you there?"),
            )

            # Thread where agent_aa has 2 posts (under the limit)
            await db.execute(
                "INSERT INTO threads (id, channel_id, author_id, author_callsign, title, body) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("t-ok", "ch-dm-1", "agent_bb", "AgentB", "new convo", "hey"),
            )
            for i in range(2):
                await db.execute(
                    "INSERT INTO posts (id, thread_id, author_id, author_callsign, body) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (f"p-ok-{i}", "t-ok", "agent_aa", "AgentA", f"reply {i}"),
                )
            # Last post by agent_bb
            await db.execute(
                "INSERT INTO posts (id, thread_id, author_id, author_callsign, body, created_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now', '+2 minutes'))",
                ("p-ok-last", "t-ok", "agent_bb", "AgentB", "what do you think?"),
            )

            await db.commit()
            return db

        return db_path, setup

    @pytest.mark.asyncio
    async def test_without_exchange_limit_returns_both(self, _setup_db):
        """Without exchange_limit, both threads are returned as unread."""
        db_path, setup = _setup_db
        db = await setup()
        try:
            from probos.ward_room.messages import MessageStore

            store = MessageStore(db=db, emit_fn=lambda *a: None)
            results = await store.get_unread_dms("agent_aa", limit=10, exchange_limit=0)
            thread_ids = {r["thread_id"] for r in results}
            assert "t-capped" in thread_ids, "Capped thread should appear without limit"
            assert "t-ok" in thread_ids, "Under-limit thread should appear"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_with_exchange_limit_excludes_capped(self, _setup_db):
        """With exchange_limit=6, threads where agent has >=6 posts are excluded."""
        db_path, setup = _setup_db
        db = await setup()
        try:
            from probos.ward_room.messages import MessageStore

            store = MessageStore(db=db, emit_fn=lambda *a: None)
            results = await store.get_unread_dms("agent_aa", limit=10, exchange_limit=6)
            thread_ids = {r["thread_id"] for r in results}
            assert "t-capped" not in thread_ids, (
                "Thread where agent has 7 posts should be excluded with limit=6"
            )
            assert "t-ok" in thread_ids, "Under-limit thread should still appear"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_exchange_limit_exact_boundary(self, _setup_db):
        """Thread with exactly exchange_limit posts should be excluded (>= check)."""
        db_path, setup = _setup_db
        db = await setup()
        try:
            from probos.ward_room.messages import MessageStore

            store = MessageStore(db=db, emit_fn=lambda *a: None)
            # agent_aa has 7 posts in t-capped, limit=7 should exclude it
            results = await store.get_unread_dms("agent_aa", limit=10, exchange_limit=7)
            thread_ids = {r["thread_id"] for r in results}
            assert "t-capped" not in thread_ids, (
                "Thread with exactly exchange_limit posts should be excluded"
            )
        finally:
            await db.close()
