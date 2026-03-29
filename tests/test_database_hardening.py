"""Tests for BF-073: Database indexes and foreign key enforcement."""

import pytest
import pytest_asyncio
import aiosqlite

from probos.ward_room import WardRoomService
from probos.persistent_tasks import PersistentTaskStore
from probos.assignment import AssignmentService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def ward_room(tmp_path):
    svc = WardRoomService(db_path=str(tmp_path / "ward_room.db"), emit_event=lambda *a: None)
    await svc.start()
    yield svc
    await svc.stop()


@pytest_asyncio.fixture
async def task_store(tmp_path):
    s = PersistentTaskStore(db_path=str(tmp_path / "tasks.db"), emit_event=lambda *a: None, tick_interval=100)
    await s.start()
    yield s
    await s.stop()


@pytest_asyncio.fixture
async def assignment_svc(tmp_path):
    svc = AssignmentService(db_path=str(tmp_path / "assignments.db"), emit_event=lambda *a: None)
    await svc.start()
    yield svc
    await svc.stop()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _index_names(db: aiosqlite.Connection) -> set[str]:
    """Return all user-created index names from sqlite_master."""
    async with db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'") as cur:
        return {row[0] async for row in cur}


async def _pragma_fk(db: aiosqlite.Connection) -> int:
    """Return the current foreign_keys pragma value."""
    async with db.execute("PRAGMA foreign_keys") as cur:
        row = await cur.fetchone()
        return row[0]


# ===========================================================================
# Index verification
# ===========================================================================

class TestIndexes:
    """Verify indexes exist after schema creation."""

    @pytest.mark.asyncio
    async def test_ward_room_indexes(self, ward_room):
        names = await _index_names(ward_room._db)
        assert "idx_threads_channel" in names
        assert "idx_posts_thread" in names
        assert "idx_posts_author" in names
        assert "idx_mod_actions_channel" in names

    @pytest.mark.asyncio
    async def test_persistent_tasks_indexes(self, task_store):
        names = await _index_names(task_store._db)
        assert "idx_tasks_status" in names
        assert "idx_tasks_webhook" in names

    @pytest.mark.asyncio
    async def test_assignment_indexes(self, assignment_svc):
        names = await _index_names(assignment_svc._db)
        assert "idx_assignments_status" in names


# ===========================================================================
# Foreign key enforcement
# ===========================================================================

class TestForeignKeys:
    """Verify PRAGMA foreign_keys = ON is applied and enforced."""

    @pytest.mark.asyncio
    async def test_ward_room_fk_pragma(self, ward_room):
        assert await _pragma_fk(ward_room._db) == 1

    @pytest.mark.asyncio
    async def test_task_store_fk_pragma(self, task_store):
        assert await _pragma_fk(task_store._db) == 1

    @pytest.mark.asyncio
    async def test_assignment_fk_pragma(self, assignment_svc):
        assert await _pragma_fk(assignment_svc._db) == 1

    @pytest.mark.asyncio
    async def test_ward_room_fk_enforced_rejects_bad_channel(self, ward_room):
        """Inserting a thread with a nonexistent channel_id should raise IntegrityError."""
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            await ward_room._db.execute(
                "INSERT INTO threads (id, channel_id, author_id, title, body, author_callsign, created_at, last_activity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("t-bad", "nonexistent-channel", "captain", "Test", "body", "Captain", 1.0, 1.0),
            )

    @pytest.mark.asyncio
    async def test_ward_room_fk_enforced_accepts_good_channel(self, ward_room):
        """Inserting a thread into an existing channel should succeed."""
        # Default channels are created by start(), grab the first one
        channels = await ward_room.list_channels()
        ch = channels[0]
        import time
        await ward_room._db.execute(
            "INSERT INTO threads (id, channel_id, author_id, title, body, author_callsign, created_at, last_activity) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("t-good", ch.id, "captain", "Test", "body", "Captain", 1.0, time.time()),
        )
        await ward_room._db.commit()
        # Verify it exists
        async with ward_room._db.execute("SELECT id FROM threads WHERE id = ?", ("t-good",)) as cur:
            row = await cur.fetchone()
        assert row is not None

    @pytest.mark.asyncio
    async def test_assignment_fk_enforced_rejects_bad_assignment(self, assignment_svc):
        """Inserting a member for a nonexistent assignment should raise IntegrityError."""
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            await assignment_svc._db.execute(
                "INSERT INTO assignment_members (assignment_id, agent_id, joined_at) VALUES (?, ?, ?)",
                ("nonexistent", "agent-1", 1.0),
            )


# ===========================================================================
# Regression — existing operations unaffected
# ===========================================================================

class TestRegression:
    """Ensure existing CRUD operations still work with indexes + FK enforcement."""

    @pytest.mark.asyncio
    async def test_ward_room_full_flow(self, ward_room):
        """Create channel → thread → post → all succeed."""
        ch = await ward_room.create_channel(
            name="test-channel", channel_type="department",
            created_by="captain", description="Test",
        )
        thread = await ward_room.create_thread(
            channel_id=ch.id,
            author_id="captain",
            title="Test Thread",
            body="Hello",
            author_callsign="Captain",
        )
        post = await ward_room.create_post(
            thread_id=thread.id,
            author_id="numberone",
            body="Acknowledged.",
            author_callsign="Number One",
        )
        detail = await ward_room.get_thread(thread.id)
        assert detail["thread"]["reply_count"] == 1

    @pytest.mark.asyncio
    async def test_assignment_creation(self, assignment_svc):
        """Basic assignment creation still works."""
        result = await assignment_svc.create_assignment(
            name="Alpha Team",
            assignment_type="away_team",
            members=["agent-1", "agent-2"],
            created_by="captain",
            mission="Test mission",
        )
        assert result.name == "Alpha Team"
        assert result.status == "active"
