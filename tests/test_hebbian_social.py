"""AD-453: Hebbian social recording tests — Ward Room replies/mentions/DMs create connections."""

import pytest
from unittest.mock import MagicMock

from probos.mesh.routing import HebbianRouter, REL_SOCIAL
from probos.runtime import ProbOSRuntime
from probos.substrate.agent import BaseAgent
from probos.ward_room import WardRoomService


@pytest.fixture
async def wr_with_hebbian(tmp_path):
    """Ward Room service with Hebbian router attached."""
    router = HebbianRouter()
    svc = WardRoomService(
        db_path=str(tmp_path / "wr.db"),
        hebbian_router=router,
    )
    await svc.start()
    yield svc, router
    await svc.stop()


class TestHebbianSocial:
    @pytest.mark.asyncio
    async def test_reply_creates_hebbian_connection(self, wr_with_hebbian):
        """Replying to a thread records author→thread_author with REL_SOCIAL."""
        wr, router = wr_with_hebbian

        channels = await wr.list_channels()
        ch = channels[0]

        # Agent A creates thread
        thread = await wr.create_thread(
            channel_id=ch.id, author_id="agent-aaa",
            title="Test thread", body="Initial post",
        )

        # Agent B replies
        await wr.create_post(
            thread_id=thread.id, author_id="agent-bbb",
            body="I have thoughts on this.",
        )

        # Hebbian weight should exist B→A
        weight = router.get_weight("agent-bbb", "agent-aaa", rel_type=REL_SOCIAL)
        assert weight > 0.0, "Reply should create Hebbian social connection"

    @pytest.mark.asyncio
    async def test_social_connections_reinforce(self, wr_with_hebbian):
        """Multiple replies to same author increase weight."""
        wr, router = wr_with_hebbian

        channels = await wr.list_channels()
        ch = channels[0]

        thread = await wr.create_thread(
            channel_id=ch.id, author_id="agent-aaa",
            title="Test", body="Post",
        )

        # First reply
        await wr.create_post(
            thread_id=thread.id, author_id="agent-bbb",
            body="Reply 1",
        )
        w1 = router.get_weight("agent-bbb", "agent-aaa", rel_type=REL_SOCIAL)

        # Second reply
        await wr.create_post(
            thread_id=thread.id, author_id="agent-bbb",
            body="Reply 2",
        )
        w2 = router.get_weight("agent-bbb", "agent-aaa", rel_type=REL_SOCIAL)

        assert w2 != w1, f"Weight should change after second reply (w1={w1}, w2={w2})"

    @pytest.mark.asyncio
    async def test_social_rel_type_is_social(self, wr_with_hebbian):
        """Ward Room connections use rel_type='social', not 'intent'."""
        wr, router = wr_with_hebbian

        channels = await wr.list_channels()
        ch = channels[0]

        thread = await wr.create_thread(
            channel_id=ch.id, author_id="agent-aaa",
            title="Test", body="Post",
        )
        await wr.create_post(
            thread_id=thread.id, author_id="agent-bbb",
            body="Reply",
        )

        # Social weight should exist
        social_w = router.get_weight("agent-bbb", "agent-aaa", rel_type=REL_SOCIAL)
        assert social_w > 0.0

        # Intent weight should NOT exist
        intent_w = router.get_weight("agent-bbb", "agent-aaa", rel_type="intent")
        assert intent_w == 0.0

    @pytest.mark.asyncio
    async def test_hebbian_event_emitted_on_reply(self, tmp_path):
        """WebSocket hebbian_update event emitted with rel_type: social."""
        router = HebbianRouter()
        events = []

        def capture_emit(event_type, data):
            events.append((event_type, data))

        svc = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            emit_event=capture_emit,
            hebbian_router=router,
        )
        await svc.start()

        channels = await svc.list_channels()
        ch = channels[0]

        thread = await svc.create_thread(
            channel_id=ch.id, author_id="agent-aaa",
            title="Test", body="Post",
        )
        await svc.create_post(
            thread_id=thread.id, author_id="agent-bbb",
            body="Reply triggers event",
        )

        hebbian_events = [(t, d) for t, d in events if t == "hebbian_update"]
        assert len(hebbian_events) > 0, "Should emit hebbian_update event"
        assert hebbian_events[0][1]["rel_type"] == "social"
        assert hebbian_events[0][1]["source"] == "agent-bbb"
        assert hebbian_events[0][1]["target"] == "agent-aaa"

        await svc.stop()

    @pytest.mark.asyncio
    async def test_dm_creates_hebbian_connection(self, wr_with_hebbian):
        """DM records sender→receiver with REL_SOCIAL (via proactive handler)."""
        from probos.proactive import ProactiveCognitiveLoop

        wr, router = wr_with_hebbian
        loop = ProactiveCognitiveLoop(interval=60)

        rt = MagicMock(spec=ProbOSRuntime)
        rt.ward_room = wr
        rt.hebbian_router = router
        rt._emit_event = MagicMock()

        rt.callsign_registry = MagicMock()
        rt.callsign_registry.resolve = MagicMock(return_value={"agent_type": "diagnostician"})
        rt.callsign_registry.get_callsign = MagicMock(return_value="Bones")

        target = MagicMock(spec=BaseAgent)
        target.agent_type = "diagnostician"
        target.id = "diag-001"
        rt.registry = MagicMock()
        rt.registry.all.return_value = [target]

        loop._runtime = rt

        agent = MagicMock(spec=BaseAgent)
        agent.agent_type = "counselor"
        agent.id = "couns-001"
        agent.callsign = "Troi"

        text = "[DM @Bones]\nCrew wellness check needed.\n[/DM]"
        await loop._extract_and_execute_dms(agent, text)

        weight = router.get_weight("couns-001", "diag-001", rel_type=REL_SOCIAL)
        assert weight > 0.0, "DM should create Hebbian social connection"

    @pytest.mark.asyncio
    async def test_self_reply_no_hebbian(self, wr_with_hebbian):
        """Replying to your own thread does NOT create a self-connection."""
        wr, router = wr_with_hebbian

        channels = await wr.list_channels()
        ch = channels[0]

        thread = await wr.create_thread(
            channel_id=ch.id, author_id="agent-aaa",
            title="Test", body="Post",
        )
        await wr.create_post(
            thread_id=thread.id, author_id="agent-aaa",
            body="Self-reply",
        )

        weight = router.get_weight("agent-aaa", "agent-aaa", rel_type=REL_SOCIAL)
        assert weight == 0.0, "Self-connection should not be recorded"
