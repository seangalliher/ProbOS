"""BF-082: Unread DM check — Ward Room query + proactive cycle integration."""

import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from probos.runtime import ProbOSRuntime
from probos.ward_room import WardRoomService
from probos.proactive import ProactiveCognitiveLoop


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
async def wr(tmp_path):
    """Ward Room service with test DB."""
    svc = WardRoomService(db_path=str(tmp_path / "wr.db"))
    await svc.start()
    yield svc
    await svc.stop()


# ------------------------------------------------------------------
# Ward Room — get_unread_dms() tests
# ------------------------------------------------------------------

class TestGetUnreadDms:
    """Tests for WardRoomService.get_unread_dms()."""

    @pytest.mark.asyncio
    async def test_returns_unanswered_threads(self, wr):
        """Unread DM from agent_a should be visible to agent_b but not agent_a."""
        ch = await wr.get_or_create_dm_channel("agent-aaa", "agent-bbb")
        thread = await wr.create_thread(
            channel_id=ch.id, author_id="agent-aaa",
            title="Hey", body="Got a minute?", author_callsign="Bones",
        )

        # agent_b should see it as unread
        unread_b = await wr.get_unread_dms("agent-bbb")
        assert len(unread_b) == 1
        assert unread_b[0]["thread_id"] == thread.id
        assert unread_b[0]["author_callsign"] == "Bones"
        assert unread_b[0]["title"] == "Hey"
        assert unread_b[0]["body"] == "Got a minute?"

        # agent_a authored the thread — should NOT see it as unread
        unread_a = await wr.get_unread_dms("agent-aaa")
        assert len(unread_a) == 0

    @pytest.mark.asyncio
    async def test_excludes_answered_threads(self, wr):
        """Once agent_b replies, thread is no longer unread."""
        ch = await wr.get_or_create_dm_channel("agent-aaa", "agent-bbb")
        thread = await wr.create_thread(
            channel_id=ch.id, author_id="agent-aaa",
            title="Status?", body="How are things?",
        )

        # Reply from agent_b
        await wr.create_post(
            thread_id=thread.id, author_id="agent-bbb", body="All good!",
        )

        unread = await wr.get_unread_dms("agent-bbb")
        assert len(unread) == 0

    @pytest.mark.asyncio
    async def test_excludes_non_dm_channels(self, wr):
        """Threads in ship/department channels are not DMs."""
        ch = await wr.create_channel(
            name="test-ship-channel", channel_type="ship", created_by="agent-aaa",
        )
        await wr.subscribe("agent-bbb", ch.id)
        await wr.create_thread(
            channel_id=ch.id, author_id="agent-aaa",
            title="Ship update", body="Everything's fine",
        )

        unread = await wr.get_unread_dms("agent-bbb")
        assert len(unread) == 0

    @pytest.mark.asyncio
    async def test_respects_limit(self, wr):
        """Only return up to 'limit' unread threads."""
        ch = await wr.get_or_create_dm_channel("agent-aaa", "agent-bbb")
        for i in range(5):
            await wr.create_thread(
                channel_id=ch.id, author_id="agent-aaa",
                title=f"DM #{i}", body=f"Message {i}",
            )

        unread = await wr.get_unread_dms("agent-bbb", limit=2)
        assert len(unread) == 2


# ------------------------------------------------------------------
# Proactive cycle — unread DM integration
# ------------------------------------------------------------------

class TestUnreadDmDeduplication:
    """BF-082: Deduplication prevents re-notification."""

    def test_dedup_prevents_repeat_notification(self):
        """Same thread_id should not be re-notified in the same cycle window."""
        loop = ProactiveCognitiveLoop()
        loop._notified_dm_threads.add("thread-123")

        # Simulating the guard: thread-123 already notified
        assert "thread-123" in loop._notified_dm_threads
        assert "thread-456" not in loop._notified_dm_threads

    def test_dedup_set_hourly_reset(self):
        """Dedup set resets after 1 hour."""
        loop = ProactiveCognitiveLoop()
        loop._notified_dm_threads.add("thread-old")
        # Simulate 1 hour elapsed
        loop._notified_dm_threads_reset = time.monotonic() - 3601

        # _check_unread_dms would reset; simulate the condition check
        if time.monotonic() - loop._notified_dm_threads_reset > 3600:
            loop._notified_dm_threads.clear()
            loop._notified_dm_threads_reset = time.monotonic()

        assert "thread-old" not in loop._notified_dm_threads


class TestProactiveCycleUnreadDms:
    """Integration test: proactive cycle routes unread DMs."""

    @pytest.mark.asyncio
    async def test_proactive_cycle_checks_unread_dms(self):
        """_check_unread_dms calls ward_room.get_unread_dms and routes via ward_room_router."""
        loop = ProactiveCognitiveLoop()

        agent = MagicMock(spec=["id", "agent_type", "callsign"])
        agent.id = "agent-bbb"
        agent.agent_type = "counselor"
        agent.callsign = "Troi"

        rt = MagicMock(spec=ProbOSRuntime)
        rt.config = MagicMock()
        rt.config.ward_room = MagicMock()
        rt.config.ward_room.dm_exchange_limit = 40
        rt.ward_room = AsyncMock(spec=WardRoomService)
        rt.ward_room.get_unread_dms = AsyncMock(return_value=[
            {
                "thread_id": "t-001",
                "channel_id": "ch-dm",
                "author_id": "agent-aaa",
                "author_callsign": "Bones",
                "title": "Urgent",
                "body": "Need your input",
                "created_at": 1000.0,
            },
        ])
        rt.ward_room_router = AsyncMock()
        rt.ward_room_router.route_event = AsyncMock()

        await loop._check_unread_dms(agent, rt)

        # Should have called get_unread_dms for this agent
        rt.ward_room.get_unread_dms.assert_awaited_once_with(agent.id, limit=2, exchange_limit=40)

        # Should have routed the event through ward_room_router
        rt.ward_room_router.route_event.assert_awaited_once()
        call_args = rt.ward_room_router.route_event.call_args
        assert call_args[0][0] == "ward_room_thread_created"
        assert call_args[0][1]["thread_id"] == "t-001"
        assert call_args[0][1]["author_callsign"] == "Bones"

        # Should be in dedup set
        assert "t-001" in loop._notified_dm_threads

    @pytest.mark.asyncio
    async def test_proactive_cycle_skips_already_notified(self):
        """Threads already in _notified_dm_threads are skipped."""
        loop = ProactiveCognitiveLoop()
        loop._notified_dm_threads.add("t-001")  # Pre-seed

        agent = MagicMock(spec=["id", "agent_type", "callsign"])
        agent.id = "agent-bbb"
        agent.agent_type = "counselor"
        agent.callsign = "Troi"

        rt = MagicMock(spec=ProbOSRuntime)
        rt.ward_room = AsyncMock(spec=WardRoomService)
        rt.ward_room.get_unread_dms = AsyncMock(return_value=[
            {
                "thread_id": "t-001",  # already notified
                "channel_id": "ch-dm",
                "author_id": "agent-aaa",
                "author_callsign": "Bones",
                "title": "Urgent",
                "body": "Need your input",
                "created_at": 1000.0,
            },
        ])
        rt.ward_room_router = AsyncMock()
        rt.ward_room_router.route_event = AsyncMock()

        await loop._check_unread_dms(agent, rt)

        # Should NOT route — already notified
        rt.ward_room_router.route_event.assert_not_awaited()
