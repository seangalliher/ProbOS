"""AD-613: Ward Room performance — query batching, post pagination, indexes."""

import pytest
import pytest_asyncio

from probos.ward_room.service import WardRoomService


@pytest_asyncio.fixture
async def ward_room(tmp_path):
    """Create a WardRoomService with temp SQLite DB."""
    events = []
    def capture_event(event_type, data):
        events.append({"type": event_type, "data": data})

    svc = WardRoomService(
        db_path=str(tmp_path / "ward_room.db"),
        emit_event=capture_event,
    )
    await svc.start()
    yield svc
    await svc.stop()


class TestCountThreads:
    """AD-613 Change 2a: count_threads() uses COUNT(*) not len(list_threads())."""

    @pytest.mark.asyncio
    async def test_count_threads_returns_int(self, ward_room):
        """count_threads() returns an integer, not a list."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        count = await ward_room.count_threads(ch.id)
        assert isinstance(count, int)
        assert count == 0

    @pytest.mark.asyncio
    async def test_count_threads_matches_list_length(self, ward_room):
        """count_threads() agrees with len(list_threads())."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        for i in range(5):
            await ward_room.create_thread(ch.id, f"agent-{i}", f"Thread {i}", f"Body {i}")
        count = await ward_room.count_threads(ch.id)
        threads = await ward_room.list_threads(ch.id, limit=100)
        assert count == len(threads)
        assert count == 5

    @pytest.mark.asyncio
    async def test_count_threads_excludes_archived(self, ward_room):
        """Archived threads are not counted."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        await ward_room.create_thread(ch.id, "agent-1", "Active", "body")
        t2 = await ward_room.create_thread(ch.id, "agent-2", "Archived", "body")
        # Directly archive via SQL since no archive_thread() method exists
        async with ward_room._threads._db.execute(
            "UPDATE threads SET archived = 1 WHERE id = ?", (t2.id,)
        ):
            pass
        await ward_room._threads._db.commit()
        count = await ward_room.count_threads(ch.id)
        assert count == 1


class TestPostPagination:
    """AD-613 Change 4: get_thread() respects post_limit."""

    @pytest.mark.asyncio
    async def test_default_limit(self, ward_room):
        """Default post_limit is 100 — all posts returned when under limit."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Thread", "body")
        for i in range(5):
            await ward_room.create_post(thread.id, "agent-1", f"Post {i}")
        result = await ward_room.get_thread(thread.id)
        assert result["total_post_count"] == 5

    @pytest.mark.asyncio
    async def test_post_limit_caps_results(self, ward_room):
        """post_limit=3 returns only 3 most recent posts."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Thread", "body")
        for i in range(10):
            await ward_room.create_post(thread.id, "agent-1", f"Post {i}")
        result = await ward_room.get_thread(thread.id, post_limit=3)

        def count_posts(posts):
            total = 0
            for p in posts:
                total += 1
                total += count_posts(p.get("children", []))
            return total

        assert count_posts(result["posts"]) <= 3
        assert result["total_post_count"] == 10

    @pytest.mark.asyncio
    async def test_total_post_count_present(self, ward_room):
        """Response includes total_post_count regardless of limit."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Thread", "body")
        result = await ward_room.get_thread(thread.id)
        assert "total_post_count" in result

    @pytest.mark.asyncio
    async def test_chronological_order_preserved(self, ward_room):
        """Posts are returned in chronological order even after DESC LIMIT reversal."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Thread", "body")
        for i in range(5):
            await ward_room.create_post(thread.id, "agent-1", f"Post {i}")
        result = await ward_room.get_thread(thread.id, post_limit=3)
        posts = result["posts"]
        for j in range(len(posts) - 1):
            assert posts[j]["created_at"] <= posts[j + 1]["created_at"]


class TestCompositeIndexes:
    """AD-613 Change 6: Verify composite indexes are created."""

    @pytest.mark.asyncio
    async def test_thread_activity_index_exists(self, ward_room):
        """idx_threads_channel_activity index is present after schema init."""
        async with ward_room._threads._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_threads_channel_activity'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None, "idx_threads_channel_activity index missing"

    @pytest.mark.asyncio
    async def test_thread_archived_index_exists(self, ward_room):
        """idx_threads_channel_archived index is present after schema init."""
        async with ward_room._threads._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_threads_channel_archived'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None, "idx_threads_channel_archived index missing"

    @pytest.mark.asyncio
    async def test_posts_created_index_exists(self, ward_room):
        """idx_posts_thread_created index is present after schema init."""
        async with ward_room._threads._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_posts_thread_created'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None, "idx_posts_thread_created index missing"
