"""Tests for WardRoomService (AD-407a)."""

import json
import time

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


class TestWardRoomRecentActivity:
    """AD-413: Recent activity for proactive loop context."""

    @pytest.fixture
    async def wr(self, tmp_path):
        svc = WardRoomService(db_path=str(tmp_path / "wr.db"))
        await svc.start()
        yield svc
        await svc.stop()

    @pytest.mark.asyncio
    async def test_get_recent_activity_returns_threads(self, wr):
        channels = await wr.list_channels()
        ch = channels[0]  # All Hands
        await wr.create_thread(ch.id, "agent1", "Test Thread", "Body text", author_callsign="LaForge")
        activity = await wr.get_recent_activity(ch.id, since=0.0, limit=10)
        assert len(activity) >= 1
        assert activity[0]["type"] == "thread"
        assert activity[0]["author"] == "LaForge"

    @pytest.mark.asyncio
    async def test_get_recent_activity_respects_since(self, wr):
        channels = await wr.list_channels()
        ch = channels[0]
        await wr.create_thread(ch.id, "agent1", "Old Thread", "old", author_callsign="Worf")
        import time
        cutoff = time.time() + 1  # Future cutoff
        activity = await wr.get_recent_activity(ch.id, since=cutoff, limit=10)
        assert len(activity) == 0

    @pytest.mark.asyncio
    async def test_get_recent_activity_includes_replies(self, wr):
        channels = await wr.list_channels()
        ch = channels[0]
        thread = await wr.create_thread(ch.id, "agent1", "Thread", "body", author_callsign="Number One")
        await wr.create_post(thread.id, "agent2", "I agree", author_callsign="Wesley")
        activity = await wr.get_recent_activity(ch.id, since=0.0, limit=10)
        types = {a["type"] for a in activity}
        assert "thread" in types
        assert "reply" in types

    @pytest.mark.asyncio
    async def test_get_recent_activity_limits_results(self, wr):
        channels = await wr.list_channels()
        ch = channels[0]
        for i in range(10):
            await wr.create_thread(ch.id, "agent1", f"Thread {i}", "body", author_callsign="LaForge")
        activity = await wr.get_recent_activity(ch.id, since=0.0, limit=3)
        assert len(activity) == 3

    @pytest.mark.asyncio
    async def test_get_recent_activity_no_db(self):
        svc = WardRoomService(db_path=None)
        await svc.start()
        result = await svc.get_recent_activity("fake", since=0.0)
        assert result == []
        await svc.stop()

    @pytest.mark.asyncio
    async def test_recent_activity_includes_thread_mode(self, wr):
        """AD-425: get_recent_activity() includes thread_mode for threads."""
        channels = await wr.list_channels()
        ch = channels[0]
        await wr.create_thread(ch.id, "agent1", "Discuss Thread", "body",
                               author_callsign="LaForge", thread_mode="discuss")
        activity = await wr.get_recent_activity(ch.id, since=0.0, limit=10)
        thread_items = [a for a in activity if a["type"] == "thread"]
        assert len(thread_items) >= 1
        assert thread_items[0]["thread_mode"] == "discuss"


# ---------------------------------------------------------------------------
# Browse Threads tests (AD-425)
# ---------------------------------------------------------------------------

class TestBrowseThreads:

    @pytest.mark.asyncio
    async def test_browse_all_subscribed_channels(self, ward_room):
        """Agent subscribed to 2 channels, browse with channels=None returns threads from both."""
        channels = await ward_room.list_channels()
        # Find All Hands (ship) and first department channel
        all_hands = next(c for c in channels if c.channel_type == "ship")
        dept = next(c for c in channels if c.channel_type == "department")

        # Subscribe agent to both
        await ward_room.subscribe("agent-1", all_hands.id)
        await ward_room.subscribe("agent-1", dept.id)

        # Create threads in both channels
        await ward_room.create_thread(all_hands.id, "captain", "All Hands Thread", "body")
        await ward_room.create_thread(dept.id, "captain", "Dept Thread", "body")

        threads = await ward_room.browse_threads("agent-1")
        assert len(threads) == 2
        titles = {t.title for t in threads}
        assert "All Hands Thread" in titles
        assert "Dept Thread" in titles

    @pytest.mark.asyncio
    async def test_browse_specific_channel(self, ward_room):
        """Pass explicit channels list, only get threads from specified channel."""
        channels = await ward_room.list_channels()
        all_hands = next(c for c in channels if c.channel_type == "ship")
        dept = next(c for c in channels if c.channel_type == "department")

        await ward_room.create_thread(all_hands.id, "captain", "AH Thread", "body")
        await ward_room.create_thread(dept.id, "captain", "Dept Thread", "body")

        threads = await ward_room.browse_threads("agent-1", channels=[dept.id])
        assert len(threads) == 1
        assert threads[0].title == "Dept Thread"

    @pytest.mark.asyncio
    async def test_browse_thread_mode_filter(self, ward_room):
        """Filter by thread_mode returns only matching threads."""
        channels = await ward_room.list_channels()
        ch = next(c for c in channels if c.channel_type == "ship")
        await ward_room.subscribe("agent-1", ch.id)

        await ward_room.create_thread(ch.id, "captain", "Info", "status",
                                      thread_mode="inform")
        await ward_room.create_thread(ch.id, "captain", "Talk", "discuss",
                                      thread_mode="discuss")

        threads = await ward_room.browse_threads(
            "agent-1", thread_mode="discuss",
        )
        assert len(threads) == 1
        assert threads[0].title == "Talk"

    @pytest.mark.asyncio
    async def test_browse_since_filter(self, ward_room):
        """since parameter filters correctly."""
        import time
        channels = await ward_room.list_channels()
        ch = next(c for c in channels if c.channel_type == "ship")
        await ward_room.subscribe("agent-1", ch.id)

        await ward_room.create_thread(ch.id, "captain", "Old", "body")
        future = time.time() + 100
        threads = await ward_room.browse_threads("agent-1", since=future)
        assert len(threads) == 0

    @pytest.mark.asyncio
    async def test_browse_limit(self, ward_room):
        """limit caps the number of returned threads."""
        channels = await ward_room.list_channels()
        ch = next(c for c in channels if c.channel_type == "ship")
        await ward_room.subscribe("agent-1", ch.id)

        for i in range(5):
            await ward_room.create_thread(ch.id, "captain", f"Thread {i}", "body")

        threads = await ward_room.browse_threads("agent-1", limit=3)
        assert len(threads) == 3

    @pytest.mark.asyncio
    async def test_browse_empty_result(self, ward_room):
        """No matching threads returns empty list."""
        # Agent not subscribed to anything
        threads = await ward_room.browse_threads("nobody")
        assert threads == []


# ---------------------------------------------------------------------------
# Thread Classification tests (AD-424)
# ---------------------------------------------------------------------------

class TestThreadClassification:

    @pytest.mark.asyncio
    async def test_create_thread_default_mode(self, ward_room):
        """Thread defaults to discuss mode with no responder cap."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(
            channel_id=ch.id, author_id="captain",
            title="Default", body="Testing defaults",
        )
        assert thread.thread_mode == "discuss"
        assert thread.max_responders == 0

    @pytest.mark.asyncio
    async def test_create_thread_inform_mode(self, ward_room):
        """Thread can be created with inform mode and persists."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(
            channel_id=ch.id, author_id="captain",
            title="Advisory", body="Status update",
            thread_mode="inform",
        )
        assert thread.thread_mode == "inform"
        # Persist through get_thread
        detail = await ward_room.get_thread(thread.id)
        assert detail["thread"]["thread_mode"] == "inform"

    @pytest.mark.asyncio
    async def test_create_thread_action_mode(self, ward_room):
        """Thread can be created with action mode."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(
            channel_id=ch.id, author_id="captain",
            title="Order", body="Do the thing",
            thread_mode="action",
        )
        assert thread.thread_mode == "action"

    @pytest.mark.asyncio
    async def test_create_thread_with_responder_cap(self, ward_room):
        """Thread can specify max_responders."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(
            channel_id=ch.id, author_id="captain",
            title="Discussion", body="Topic",
            thread_mode="discuss", max_responders=3,
        )
        assert thread.max_responders == 3

    @pytest.mark.asyncio
    async def test_update_thread_lock(self, ward_room):
        """update_thread can lock a thread."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(
            channel_id=ch.id, author_id="captain",
            title="Lock Test", body="body",
        )
        updated = await ward_room.update_thread(thread.id, locked=True)
        assert updated is not None
        assert updated.locked is True
        # Verify persists
        detail = await ward_room.get_thread(thread.id)
        assert detail["thread"]["locked"] is True

    @pytest.mark.asyncio
    async def test_update_thread_reclassify(self, ward_room):
        """update_thread can reclassify inform → discuss."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(
            channel_id=ch.id, author_id="captain",
            title="Advisory", body="status",
            thread_mode="inform",
        )
        updated = await ward_room.update_thread(thread.id, thread_mode="discuss")
        assert updated is not None
        assert updated.thread_mode == "discuss"

    @pytest.mark.asyncio
    async def test_update_thread_responder_cap(self, ward_room):
        """update_thread can adjust max_responders."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(
            channel_id=ch.id, author_id="captain",
            title="Cap Test", body="body",
        )
        updated = await ward_room.update_thread(thread.id, max_responders=5)
        assert updated is not None
        assert updated.max_responders == 5

    @pytest.mark.asyncio
    async def test_update_thread_emits_event(self, ward_room):
        """update_thread emits ward_room_thread_updated event."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(
            channel_id=ch.id, author_id="captain",
            title="Event Test", body="body",
        )
        ward_room._captured_events.clear()
        await ward_room.update_thread(thread.id, locked=True)
        evt = next(
            (e for e in ward_room._captured_events
             if e["type"] == "ward_room_thread_updated"),
            None,
        )
        assert evt is not None
        assert evt["data"]["thread_id"] == thread.id
        assert evt["data"]["updates"]["locked"] is True

    @pytest.mark.asyncio
    async def test_thread_mode_in_event(self, ward_room):
        """Thread created event includes thread_mode."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        ward_room._captured_events.clear()
        await ward_room.create_thread(
            channel_id=ch.id, author_id="captain",
            title="Mode Event", body="body",
            thread_mode="inform",
        )
        evt = next(
            (e for e in ward_room._captured_events
             if e["type"] == "ward_room_thread_created"),
            None,
        )
        assert evt is not None
        assert evt["data"]["thread_mode"] == "inform"

    @pytest.mark.asyncio
    async def test_schema_migration(self, tmp_path):
        """Existing DB without new columns gets migrated on start()."""
        import aiosqlite
        db_path = str(tmp_path / "old.db")
        # Create old schema WITHOUT thread_mode/max_responders columns
        # but with all other tables matching current _SCHEMA
        old_schema = """
CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, channel_type TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL,
    created_at REAL NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, author_id TEXT NOT NULL,
    title TEXT NOT NULL, body TEXT NOT NULL, created_at REAL NOT NULL,
    last_activity REAL NOT NULL, pinned INTEGER NOT NULL DEFAULT 0,
    locked INTEGER NOT NULL DEFAULT 0,
    reply_count INTEGER NOT NULL DEFAULT 0, net_score INTEGER NOT NULL DEFAULT 0,
    author_callsign TEXT NOT NULL DEFAULT '', channel_name TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, parent_id TEXT,
    author_id TEXT NOT NULL, body TEXT NOT NULL, created_at REAL NOT NULL,
    edited_at REAL, deleted INTEGER NOT NULL DEFAULT 0,
    delete_reason TEXT NOT NULL DEFAULT '', deleted_by TEXT NOT NULL DEFAULT '',
    net_score INTEGER NOT NULL DEFAULT 0, author_callsign TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS endorsements (
    id TEXT PRIMARY KEY, target_id TEXT NOT NULL, target_type TEXT NOT NULL,
    voter_id TEXT NOT NULL, direction TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_endorsement_unique
    ON endorsements(target_id, voter_id);
CREATE TABLE IF NOT EXISTS memberships (
    agent_id TEXT NOT NULL, channel_id TEXT NOT NULL,
    subscribed_at REAL NOT NULL, last_seen REAL NOT NULL DEFAULT 0.0,
    notify INTEGER NOT NULL DEFAULT 1, role TEXT NOT NULL DEFAULT 'member',
    PRIMARY KEY (agent_id, channel_id)
);
CREATE TABLE IF NOT EXISTS credibility (
    agent_id TEXT PRIMARY KEY, total_posts INTEGER NOT NULL DEFAULT 0,
    total_endorsements INTEGER NOT NULL DEFAULT 0,
    credibility_score REAL NOT NULL DEFAULT 0.5,
    restrictions TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS mod_actions (
    id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, target_id TEXT NOT NULL,
    target_type TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,
    moderator_id TEXT NOT NULL, created_at REAL NOT NULL
);
"""
        async with aiosqlite.connect(db_path) as db:
            await db.executescript(old_schema)

        # Start service on old DB — migration should add columns
        svc = WardRoomService(db_path=db_path)
        await svc.start()
        channels = await svc.list_channels()
        ch = channels[0]
        thread = await svc.create_thread(
            channel_id=ch.id, author_id="captain",
            title="Post-migration", body="works",
        )
        assert thread.thread_mode == "discuss"
        assert thread.max_responders == 0
        await svc.stop()


# ---------------------------------------------------------------------------
# Ward Room Pruning tests (AD-416)
# ---------------------------------------------------------------------------

class TestWardRoomPruning:

    async def _age_thread(self, wr, thread_id: str, days_old: float):
        """Set a thread's timestamps to be N days old."""
        old_ts = time.time() - (days_old * 86400)
        await wr._db.execute(
            "UPDATE threads SET created_at = ?, last_activity = ? WHERE id = ?",
            (old_ts, old_ts, thread_id),
        )
        await wr._db.commit()

    @pytest.mark.asyncio
    async def test_prune_old_thread(self, ward_room):
        """Thread older than retention_days is deleted."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Old Thread", "body")
        await self._age_thread(ward_room, thread.id, days_old=10)

        result = await ward_room.prune_old_threads(retention_days=7)
        assert result["threads_pruned"] == 1

        # Thread is gone
        detail = await ward_room.get_thread(thread.id)
        assert detail is None

    @pytest.mark.asyncio
    async def test_prune_preserves_recent(self, ward_room):
        """Thread within retention_days survives."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Recent", "body")
        # Default timestamps are now — well within 7 days

        result = await ward_room.prune_old_threads(retention_days=7)
        assert result["threads_pruned"] == 0

        detail = await ward_room.get_thread(thread.id)
        assert detail is not None

    @pytest.mark.asyncio
    async def test_prune_preserves_endorsed(self, ward_room):
        """Thread with net_score > 0 uses endorsed retention window."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Good Thread", "body")
        await self._age_thread(ward_room, thread.id, days_old=10)

        # Upvote the thread (sets net_score > 0)
        await ward_room._db.execute(
            "UPDATE threads SET net_score = 3 WHERE id = ?", (thread.id,),
        )
        await ward_room._db.commit()

        # 10 days old, but net_score > 0 and endorsed retention = 30 days → survives
        result = await ward_room.prune_old_threads(
            retention_days=7, retention_days_endorsed=30,
        )
        assert result["threads_pruned"] == 0

    @pytest.mark.asyncio
    async def test_prune_preserves_pinned(self, ward_room):
        """Pinned threads are never pruned."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Pinned", "body")
        await self._age_thread(ward_room, thread.id, days_old=100)

        # Pin the thread
        await ward_room.update_thread(thread.id, pinned=True)

        result = await ward_room.prune_old_threads(retention_days=7)
        assert result["threads_pruned"] == 0

    @pytest.mark.asyncio
    async def test_prune_preserves_captain(self, ward_room):
        """Captain-authored threads survive with retention_days_captain=0."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "captain", "Captain Post", "body")
        await self._age_thread(ward_room, thread.id, days_old=100)

        result = await ward_room.prune_old_threads(
            retention_days=7, retention_days_captain=0,
        )
        assert result["threads_pruned"] == 0

    @pytest.mark.asyncio
    async def test_prune_cascades_posts(self, ward_room):
        """Posts belonging to pruned threads are deleted."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Old", "body")
        await ward_room.create_post(thread.id, "agent-2", "Reply 1")
        await ward_room.create_post(thread.id, "agent-3", "Reply 2")
        await self._age_thread(ward_room, thread.id, days_old=10)

        result = await ward_room.prune_old_threads(retention_days=7)
        assert result["threads_pruned"] == 1
        assert result["posts_pruned"] == 2

    @pytest.mark.asyncio
    async def test_prune_cascades_endorsements(self, ward_room):
        """Endorsements on pruned threads/posts are deleted."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Old", "body")
        post = await ward_room.create_post(thread.id, "agent-2", "Reply")
        # Add endorsements
        await ward_room.endorse(post.id, "post", "agent-3", "up")
        await self._age_thread(ward_room, thread.id, days_old=10)

        result = await ward_room.prune_old_threads(retention_days=7)
        assert result["endorsements_pruned"] >= 1

    @pytest.mark.asyncio
    async def test_prune_archives_to_jsonl(self, ward_room, tmp_path):
        """Pruned threads are written to JSONL file with correct format."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(
            ch.id, "agent-1", "Archive Me", "body text",
            author_callsign="LaForge",
        )
        await ward_room.create_post(thread.id, "agent-2", "Reply",
                                    author_callsign="Worf")
        await self._age_thread(ward_room, thread.id, days_old=10)

        archive_path = str(tmp_path / "archive.jsonl")
        await ward_room.prune_old_threads(retention_days=7, archive_path=archive_path)

        with open(archive_path) as f:
            lines = f.readlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["thread_id"] == thread.id
        assert record["title"] == "Archive Me"
        assert record["author_callsign"] == "LaForge"
        assert len(record["posts"]) == 1
        assert record["posts"][0]["author_callsign"] == "Worf"
        assert "pruned_at" in record

    @pytest.mark.asyncio
    async def test_prune_archive_appends(self, ward_room, tmp_path):
        """Multiple prune runs append to same file."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        archive_path = str(tmp_path / "archive.jsonl")

        # First prune run
        t1 = await ward_room.create_thread(ch.id, "agent-1", "Thread 1", "body")
        await self._age_thread(ward_room, t1.id, days_old=10)
        await ward_room.prune_old_threads(retention_days=7, archive_path=archive_path)

        # Second prune run
        t2 = await ward_room.create_thread(ch.id, "agent-1", "Thread 2", "body")
        await self._age_thread(ward_room, t2.id, days_old=10)
        await ward_room.prune_old_threads(retention_days=7, archive_path=archive_path)

        with open(archive_path) as f:
            lines = f.readlines()
        assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_prune_no_archive(self, ward_room):
        """When archive_path is None, no file is written."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "No Archive", "body")
        await self._age_thread(ward_room, thread.id, days_old=10)

        result = await ward_room.prune_old_threads(
            retention_days=7, archive_path=None,
        )
        assert result["threads_pruned"] == 1
        assert result["archived_to"] is None

    @pytest.mark.asyncio
    async def test_count_pruneable(self, ward_room):
        """Dry-run count matches actual prune count."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        # Create 3 old threads + 1 recent
        for i in range(3):
            t = await ward_room.create_thread(ch.id, "agent-1", f"Old {i}", "body")
            await self._age_thread(ward_room, t.id, days_old=10)
        await ward_room.create_thread(ch.id, "agent-1", "Recent", "body")

        count = await ward_room.count_pruneable(retention_days=7)
        assert count == 3

        result = await ward_room.prune_old_threads(retention_days=7)
        assert result["threads_pruned"] == count

    @pytest.mark.asyncio
    async def test_get_stats(self, ward_room):
        """Returns correct counts and oldest_thread_at."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        t1 = await ward_room.create_thread(ch.id, "agent-1", "First", "body")
        await ward_room.create_thread(ch.id, "agent-1", "Second", "body")
        await ward_room.create_post(t1.id, "agent-2", "Reply")

        stats = await ward_room.get_stats()
        assert stats["total_threads"] == 2
        assert stats["total_posts"] == 1
        assert stats["oldest_thread_at"] is not None
        assert stats["db_size_bytes"] > 0

    @pytest.mark.asyncio
    async def test_prune_returns_summary(self, ward_room):
        """Return dict has correct keys and counts."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Summary", "body")
        await ward_room.create_post(thread.id, "agent-2", "Reply")
        await self._age_thread(ward_room, thread.id, days_old=10)

        result = await ward_room.prune_old_threads(retention_days=7)
        assert "threads_pruned" in result
        assert "posts_pruned" in result
        assert "endorsements_pruned" in result
        assert "archived_to" in result
        assert result["threads_pruned"] == 1
        assert result["posts_pruned"] == 1

    @pytest.mark.asyncio
    async def test_prune_emits_event(self, ward_room):
        """ward_room_pruned event emitted with summary."""
        channels = await ward_room.list_channels()
        ch = channels[0]
        thread = await ward_room.create_thread(ch.id, "agent-1", "Event", "body")
        await self._age_thread(ward_room, thread.id, days_old=10)

        ward_room._captured_events.clear()
        await ward_room.prune_old_threads(retention_days=7)

        evt = next(
            (e for e in ward_room._captured_events
             if e["type"] == "ward_room_pruned"),
            None,
        )
        assert evt is not None
        assert evt["data"]["threads_pruned"] == 1


# ---------------------------------------------------------------------------
# AD-430a: Ward Room → episodic memory
# ---------------------------------------------------------------------------


class TestWardRoomEpisodicMemory:
    """AD-430a: Ward Room posts stored as episodic memory."""

    @pytest.mark.asyncio
    async def test_thread_creation_stores_episode(self, tmp_path):
        """Thread creation stores an episode for the authoring agent."""
        from unittest.mock import AsyncMock

        mock_mem = AsyncMock()

        svc = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            episodic_memory=mock_mem,
        )
        await svc.start()

        channels = await svc.list_channels()
        ch = channels[0]
        thread = await svc.create_thread(
            ch.id, "agent-1", "Test observation", "Body text",
            author_callsign="Number One",
        )

        mock_mem.store.assert_called_once()
        episode = mock_mem.store.call_args[0][0]
        assert "[Ward Room]" in episode.user_input
        assert episode.agent_ids == ["agent-1"]
        assert episode.outcomes[0]["intent"] == "ward_room_post"
        assert episode.outcomes[0]["is_reply"] is False
        assert episode.outcomes[0]["thread_id"] == thread.id

        await svc.stop()

    @pytest.mark.asyncio
    async def test_post_reply_stores_episode(self, tmp_path):
        """Reply post stores an episode for the replying agent."""
        from unittest.mock import AsyncMock

        mock_mem = AsyncMock()

        svc = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            episodic_memory=mock_mem,
        )
        await svc.start()

        channels = await svc.list_channels()
        ch = channels[0]
        thread = await svc.create_thread(
            ch.id, "agent-1", "Discussion topic", "Let's discuss",
            author_callsign="Number One",
        )
        mock_mem.store.reset_mock()

        post = await svc.create_post(
            thread.id, "agent-2", "I agree with the assessment.",
            author_callsign="LaForge",
        )

        mock_mem.store.assert_called_once()
        episode = mock_mem.store.call_args[0][0]
        assert "[Ward Room reply]" in episode.user_input
        assert episode.outcomes[0]["is_reply"] is True

        await svc.stop()

    @pytest.mark.asyncio
    async def test_reply_reflection_includes_body_excerpt(self, tmp_path):
        """BF-029 Test 6: Reply reflection contains body excerpt, not just thread title."""
        from unittest.mock import AsyncMock

        mock_mem = AsyncMock()

        svc = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            episodic_memory=mock_mem,
        )
        await svc.start()

        channels = await svc.list_channels()
        ch = channels[0]
        thread = await svc.create_thread(
            ch.id, "agent-1", "Trust Review", "Opening topic",
            author_callsign="Number One",
        )
        mock_mem.store.reset_mock()

        await svc.create_post(
            thread.id, "agent-2",
            "I've noticed increased trust variance across departments",
            author_callsign="Counselor",
        )

        mock_mem.store.assert_called_once()
        episode = mock_mem.store.call_args[0][0]
        assert "trust variance" in episode.reflection
        # Should not be just "replied in thread 'Trust Review'." — must have body content
        assert ":" in episode.reflection  # colon separates thread title from body

        await svc.stop()

    @pytest.mark.asyncio
    async def test_reply_episode_includes_channel_name(self, tmp_path):
        """BF-029 Test 7: Reply episode user_input includes channel name."""
        from unittest.mock import AsyncMock

        mock_mem = AsyncMock()

        svc = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            episodic_memory=mock_mem,
        )
        await svc.start()

        channels = await svc.list_channels()
        ch = channels[0]  # "All Hands" default
        thread = await svc.create_thread(
            ch.id, "agent-1", "Topic", "Content",
            author_callsign="Number One",
        )
        mock_mem.store.reset_mock()

        await svc.create_post(
            thread.id, "agent-2", "My reply content",
            author_callsign="LaForge",
        )

        episode = mock_mem.store.call_args[0][0]
        assert episode.user_input.startswith("[Ward Room reply] All Hands")
        assert "LaForge" in episode.user_input

        await svc.stop()

    @pytest.mark.asyncio
    async def test_reply_episode_outcomes_include_channel(self, tmp_path):
        """BF-029 Test 8: Reply episode outcomes dict has 'channel' key."""
        from unittest.mock import AsyncMock

        mock_mem = AsyncMock()

        svc = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            episodic_memory=mock_mem,
        )
        await svc.start()

        channels = await svc.list_channels()
        ch = channels[0]
        thread = await svc.create_thread(
            ch.id, "agent-1", "Topic", "Content",
            author_callsign="Number One",
        )
        mock_mem.store.reset_mock()

        await svc.create_post(
            thread.id, "agent-2", "Reply text",
            author_callsign="Bones",
        )

        episode = mock_mem.store.call_args[0][0]
        assert "channel" in episode.outcomes[0]
        assert episode.outcomes[0]["channel"]  # non-empty

        await svc.stop()

    @pytest.mark.asyncio
    async def test_no_episodic_memory_no_crash(self, tmp_path):
        """Without episodic_memory, thread/post creation works fine."""
        svc = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            episodic_memory=None,
        )
        await svc.start()

        channels = await svc.list_channels()
        ch = channels[0]
        thread = await svc.create_thread(
            ch.id, "agent-1", "Test", "Body",
        )
        assert thread is not None
        post = await svc.create_post(
            thread.id, "agent-2", "Reply body",
        )
        assert post is not None

        await svc.stop()

    @pytest.mark.asyncio
    async def test_episode_store_failure_does_not_block_thread(self, tmp_path):
        """Episodic memory failure doesn't block thread creation."""
        from unittest.mock import AsyncMock

        mock_mem = AsyncMock()
        mock_mem.store = AsyncMock(side_effect=RuntimeError("ChromaDB down"))

        svc = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            episodic_memory=mock_mem,
        )
        await svc.start()

        channels = await svc.list_channels()
        ch = channels[0]
        thread = await svc.create_thread(
            ch.id, "agent-1", "Test observation", "Important body",
            author_callsign="Number One",
        )
        # Thread still created despite episode store failure
        assert thread is not None
        assert thread.title == "Test observation"

        await svc.stop()
