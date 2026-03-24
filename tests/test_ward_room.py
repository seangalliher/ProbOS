"""Tests for WardRoomService (AD-407a)."""

import pytest
import pytest_asyncio

from probos.ward_room import (
    WardRoomService, WardRoomChannel, WardRoomThread,
    WardRoomPost, WardRoomEndorsement, WardRoomCredibility,
)


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
    svc._captured_events = events  # For test assertions
    yield svc
    await svc.stop()


# ---------------------------------------------------------------------------
# Channel tests
# ---------------------------------------------------------------------------

class TestChannels:
    async def test_default_channels_created(self, ward_room):
        """After start(), ship channel 'All Hands' + department channels exist."""
        channels = await ward_room.list_channels()
        names = {c.name for c in channels}
        assert "All Hands" in names
        assert "Engineering" in names
        assert "Science" in names
        assert "Medical" in names
        assert "Security" in names
        assert "Bridge" in names

    async def test_create_custom_channel(self, ward_room):
        """Create a custom channel and verify it appears in list."""
        ch = await ward_room.create_channel(
            name="Off Duty", channel_type="custom",
            created_by="agent-1", description="Casual chat",
        )
        assert ch.name == "Off Duty"
        assert ch.channel_type == "custom"
        channels = await ward_room.list_channels()
        names = {c.name for c in channels}
        assert "Off Duty" in names

    async def test_duplicate_channel_name_rejected(self, ward_room):
        """Creating channel with same name raises ValueError."""
        await ward_room.create_channel(
            name="Unique", channel_type="custom", created_by="agent-1",
        )
        with pytest.raises(ValueError, match="already exists"):
            await ward_room.create_channel(
                name="Unique", channel_type="custom", created_by="agent-1",
            )

    async def test_list_channels(self, ward_room):
        """Returns all channels including defaults."""
        channels = await ward_room.list_channels()
        assert len(channels) >= 6  # All Hands + 5 departments


# ---------------------------------------------------------------------------
# Thread tests
# ---------------------------------------------------------------------------

class TestThreads:
    async def test_create_thread(self, ward_room):
        """Create thread, verify fields populated."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(
            channel_id=ch.id, author_id="agent-1",
            title="Status Report", body="All systems nominal.",
            author_callsign="Wesley",
        )
        assert thread.title == "Status Report"
        assert thread.body == "All systems nominal."
        assert thread.author_callsign == "Wesley"
        assert thread.channel_name == ch.name

    async def test_list_threads_sorted_by_recent(self, ward_room):
        """Create 3 threads, verify sorted by last_activity desc."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        t1 = await ward_room.create_thread(ch.id, "a1", "First", "body")
        t2 = await ward_room.create_thread(ch.id, "a1", "Second", "body")
        t3 = await ward_room.create_thread(ch.id, "a1", "Third", "body")
        threads = await ward_room.list_threads(ch.id, sort="recent")
        assert threads[0].title == "Third"
        assert threads[2].title == "First"

    async def test_list_threads_pinned_first(self, ward_room):
        """Pinned thread appears first regardless of sort."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        t1 = await ward_room.create_thread(ch.id, "a1", "Normal", "body")
        t2 = await ward_room.create_thread(ch.id, "a1", "Pinned", "body")
        # Pin t2 manually
        await ward_room._db.execute(
            "UPDATE threads SET pinned = 1 WHERE id = ?", (t2.id,)
        )
        await ward_room._db.commit()
        threads = await ward_room.list_threads(ch.id)
        assert threads[0].title == "Pinned"
        assert threads[0].pinned is True

    async def test_get_thread_with_posts(self, ward_room):
        """Create thread + replies, verify nested structure."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "a1", "Discussion", "body")
        p1 = await ward_room.create_post(thread.id, "a2", "Reply 1")
        p2 = await ward_room.create_post(thread.id, "a3", "Nested", parent_id=p1.id)
        result = await ward_room.get_thread(thread.id)
        assert result is not None
        assert result["thread"]["title"] == "Discussion"
        assert len(result["posts"]) == 1  # Only root-level posts
        assert result["posts"][0]["body"] == "Reply 1"
        assert len(result["posts"][0]["children"]) == 1
        assert result["posts"][0]["children"][0]["body"] == "Nested"


# ---------------------------------------------------------------------------
# Post tests
# ---------------------------------------------------------------------------

class TestPosts:
    async def test_create_post_reply(self, ward_room):
        """Reply to thread, parent_id is None."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "a1", "Title", "body")
        post = await ward_room.create_post(thread.id, "a2", "My reply")
        assert post.parent_id is None
        assert post.body == "My reply"

    async def test_create_nested_reply(self, ward_room):
        """Reply to a post, parent_id set."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "a1", "Title", "body")
        p1 = await ward_room.create_post(thread.id, "a2", "Top level")
        p2 = await ward_room.create_post(thread.id, "a3", "Nested", parent_id=p1.id)
        assert p2.parent_id == p1.id

    async def test_create_post_increments_reply_count(self, ward_room):
        """Thread reply_count increases."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "a1", "Title", "body")
        await ward_room.create_post(thread.id, "a2", "Reply 1")
        await ward_room.create_post(thread.id, "a3", "Reply 2")
        result = await ward_room.get_thread(thread.id)
        assert result["thread"]["reply_count"] == 2

    async def test_create_post_updates_last_activity(self, ward_room):
        """Thread last_activity updated after post."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "a1", "Title", "body")
        original_activity = thread.last_activity
        import time
        time.sleep(0.01)  # Small delay to ensure timestamp difference
        await ward_room.create_post(thread.id, "a2", "Reply")
        result = await ward_room.get_thread(thread.id)
        assert result["thread"]["last_activity"] >= original_activity

    async def test_edit_own_post(self, ward_room):
        """Author can edit, edited_at set."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "a1", "Title", "body")
        post = await ward_room.create_post(thread.id, "a2", "Original")
        edited = await ward_room.edit_post(post.id, "a2", "Updated")
        assert edited.body == "Updated"
        assert edited.edited_at is not None

    async def test_edit_others_post_rejected(self, ward_room):
        """Non-author edit raises ValueError."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "a1", "Title", "body")
        post = await ward_room.create_post(thread.id, "a2", "Original")
        with pytest.raises(ValueError, match="original author"):
            await ward_room.edit_post(post.id, "a3", "Hacked")


# ---------------------------------------------------------------------------
# Endorsement tests
# ---------------------------------------------------------------------------

class TestEndorsements:
    async def test_endorse_up(self, ward_room):
        """Upvote a post, net_score = 1."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "a1", "Title", "body")
        post = await ward_room.create_post(thread.id, "a2", "Good post")
        result = await ward_room.endorse(post.id, "post", "a1", "up")
        assert result["net_score"] == 1
        assert result["voter_direction"] == "up"

    async def test_endorse_down(self, ward_room):
        """Downvote, net_score = -1."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "a1", "Title", "body")
        post = await ward_room.create_post(thread.id, "a2", "Bad post")
        result = await ward_room.endorse(post.id, "post", "a1", "down")
        assert result["net_score"] == -1
        assert result["voter_direction"] == "down"

    async def test_endorse_unvote(self, ward_room):
        """Unvote removes endorsement, net_score back to 0."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "a1", "Title", "body")
        post = await ward_room.create_post(thread.id, "a2", "Post")
        await ward_room.endorse(post.id, "post", "a1", "up")
        result = await ward_room.endorse(post.id, "post", "a1", "unvote")
        assert result["net_score"] == 0
        assert result["voter_direction"] == "none"

    async def test_self_endorse_rejected(self, ward_room):
        """Endorsing own post raises ValueError."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "a1", "Title", "body")
        post = await ward_room.create_post(thread.id, "a1", "My post")
        with pytest.raises(ValueError, match="own content"):
            await ward_room.endorse(post.id, "post", "a1", "up")

    async def test_vote_change_delta(self, ward_room):
        """Up then down = net_score -1 (delta of -2, not -1)."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "a1", "Title", "body")
        post = await ward_room.create_post(thread.id, "a2", "Post")
        await ward_room.endorse(post.id, "post", "a1", "up")
        result = await ward_room.endorse(post.id, "post", "a1", "down")
        assert result["net_score"] == -1
        assert result["voter_direction"] == "down"

    async def test_endorsement_updates_credibility(self, ward_room):
        """Receiving upvote increases author's credibility_score."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "a1", "Title", "body")
        post = await ward_room.create_post(thread.id, "a2", "Post")
        cred_before = await ward_room.get_credibility("a2")
        await ward_room.endorse(post.id, "post", "a1", "up")
        cred_after = await ward_room.get_credibility("a2")
        assert cred_after.credibility_score > cred_before.credibility_score


# ---------------------------------------------------------------------------
# Membership tests
# ---------------------------------------------------------------------------

class TestMembership:
    async def test_subscribe_and_unsubscribe(self, ward_room):
        """Subscribe, verify membership, unsubscribe, verify removed."""
        channels = await ward_room.list_channels()
        # Find a custom/ship channel (not department)
        ship_ch = [c for c in channels if c.channel_type == "ship"][0]
        await ward_room.subscribe("a1", ship_ch.id)
        counts = await ward_room.get_unread_counts("a1")
        assert ship_ch.id in counts
        await ward_room.unsubscribe("a1", ship_ch.id)
        counts = await ward_room.get_unread_counts("a1")
        assert ship_ch.id not in counts

    async def test_update_last_seen(self, ward_room):
        """Update last_seen, verify updated."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        await ward_room.subscribe("a1", ch.id)
        await ward_room.update_last_seen("a1", ch.id)
        # Verify via unread counts (should be 0 if last_seen is current)
        counts = await ward_room.get_unread_counts("a1")
        assert counts.get(ch.id, 0) == 0

    async def test_unread_counts(self, ward_room):
        """Subscribe, create threads, verify unread count. Update last_seen, verify 0."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        await ward_room.subscribe("a1", ch.id)
        # Mark as seen now
        await ward_room.update_last_seen("a1", ch.id)
        # Create a thread (will have last_activity > last_seen)
        import time
        time.sleep(0.01)
        await ward_room.create_thread(ch.id, "a2", "New thread", "body")
        counts = await ward_room.get_unread_counts("a1")
        assert counts.get(ch.id, 0) >= 1
        # Mark as read
        await ward_room.update_last_seen("a1", ch.id)
        counts = await ward_room.get_unread_counts("a1")
        assert counts.get(ch.id, 0) == 0


# ---------------------------------------------------------------------------
# Credibility tests
# ---------------------------------------------------------------------------

class TestCredibility:
    async def test_default_credibility(self, ward_room):
        """New agent gets score 0.5."""
        cred = await ward_room.get_credibility("new-agent")
        assert cred.credibility_score == 0.5
        assert cred.total_posts == 0

    async def test_credibility_increases_with_upvotes(self, ward_room):
        """Multiple upvotes raise score above 0.5."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "author", "T", "b")
        post = await ward_room.create_post(thread.id, "author", "Good post")
        for voter in ["v1", "v2", "v3", "v4", "v5"]:
            await ward_room.endorse(post.id, "post", voter, "up")
        cred = await ward_room.get_credibility("author")
        assert cred.credibility_score > 0.5

    async def test_credibility_decreases_with_downvotes(self, ward_room):
        """Multiple downvotes lower score below 0.5."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "author", "T", "b")
        post = await ward_room.create_post(thread.id, "author", "Bad post")
        for voter in ["v1", "v2", "v3", "v4", "v5"]:
            await ward_room.endorse(post.id, "post", voter, "down")
        cred = await ward_room.get_credibility("author")
        assert cred.credibility_score < 0.5


# ---------------------------------------------------------------------------
# Event emission tests
# ---------------------------------------------------------------------------

class TestEvents:
    async def test_thread_created_emits_event(self, ward_room):
        """Creating thread emits ward_room_thread_created."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        ward_room._captured_events.clear()
        await ward_room.create_thread(ch.id, "a1", "Title", "body")
        types = [e["type"] for e in ward_room._captured_events]
        assert "ward_room_thread_created" in types

    async def test_post_created_emits_event(self, ward_room):
        """Creating post emits ward_room_post_created."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "a1", "Title", "body")
        ward_room._captured_events.clear()
        await ward_room.create_post(thread.id, "a2", "Reply")
        types = [e["type"] for e in ward_room._captured_events]
        assert "ward_room_post_created" in types

    async def test_endorsement_emits_event(self, ward_room):
        """Endorsing emits ward_room_endorsement."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "a1", "Title", "body")
        post = await ward_room.create_post(thread.id, "a2", "Post")
        ward_room._captured_events.clear()
        await ward_room.endorse(post.id, "post", "a1", "up")
        types = [e["type"] for e in ward_room._captured_events]
        assert "ward_room_endorsement" in types
