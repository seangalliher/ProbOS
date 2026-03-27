"""AD-453: Ward Room DM tests — channel creation, action tag, API endpoints."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from probos.ward_room import WardRoomService


@pytest.fixture
async def wr(tmp_path):
    """Ward Room service with test DB."""
    svc = WardRoomService(db_path=str(tmp_path / "wr.db"))
    await svc.start()
    yield svc
    await svc.stop()


class TestDmChannelCreation:
    @pytest.mark.asyncio
    async def test_get_or_create_dm_channel_creates_new(self, wr):
        """First call creates a DM channel."""
        ch = await wr.get_or_create_dm_channel("agent-aaa", "agent-bbb", "Bones", "Troi")
        assert ch.channel_type == "dm"
        assert ch.name.startswith("dm-")

    @pytest.mark.asyncio
    async def test_get_or_create_dm_channel_returns_existing(self, wr):
        """Second call returns the same channel (idempotent)."""
        ch1 = await wr.get_or_create_dm_channel("agent-aaa", "agent-bbb")
        ch2 = await wr.get_or_create_dm_channel("agent-aaa", "agent-bbb")
        assert ch1.id == ch2.id

    @pytest.mark.asyncio
    async def test_dm_channel_name_deterministic(self, wr):
        """A→B and B→A produce the same channel."""
        ch1 = await wr.get_or_create_dm_channel("agent-aaa", "agent-bbb")
        ch2 = await wr.get_or_create_dm_channel("agent-bbb", "agent-aaa")
        assert ch1.id == ch2.id

    @pytest.mark.asyncio
    async def test_dm_channel_type_is_dm(self, wr):
        ch = await wr.get_or_create_dm_channel("agent-aaa", "agent-bbb")
        assert ch.channel_type == "dm"

    @pytest.mark.asyncio
    async def test_dm_channel_subscribes_both_agents(self, wr):
        ch = await wr.get_or_create_dm_channel("agent-aaa", "agent-bbb")
        # Query memberships table directly
        async with wr._db.execute(
            "SELECT agent_id FROM memberships WHERE channel_id = ?", (ch.id,)
        ) as cursor:
            rows = await cursor.fetchall()
        sub_ids = {r[0] for r in rows}
        assert "agent-aaa" in sub_ids
        assert "agent-bbb" in sub_ids


class TestDmActionTag:
    @pytest.mark.asyncio
    async def test_dm_action_tag_sends_message(self, wr):
        """[DM @bones]...[/DM] creates thread in DM channel."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = ProactiveCognitiveLoop(interval=60)
        rt = MagicMock()
        rt.ward_room = wr
        rt.trust_network = MagicMock()
        rt.trust_network.get_score = MagicMock(return_value=0.9)

        # Set up callsign registry
        rt.callsign_registry = MagicMock()
        rt.callsign_registry.get_agent_type = MagicMock(return_value="diagnostician")
        rt.callsign_registry.get_callsign = MagicMock(return_value="Bones")

        # Set up agents list
        target_agent = MagicMock()
        target_agent.agent_type = "diagnostician"
        target_agent.id = "diag-001"
        rt._agents = [target_agent]

        rt.hebbian_router = None  # skip Hebbian for this test

        loop._runtime = rt

        agent = MagicMock()
        agent.agent_type = "counselor"
        agent.id = "couns-001"
        agent.callsign = "Troi"

        text = "[DM @Bones]\nHave you checked the crew health reports today?\n[/DM]"
        cleaned, actions = await loop._extract_and_execute_dms(agent, text)

        assert len(actions) == 1
        assert actions[0]["type"] == "dm"
        assert actions[0]["target_callsign"] == "Bones"
        assert cleaned == ""

    @pytest.mark.asyncio
    async def test_dm_action_tag_unknown_callsign_skipped(self):
        """Unknown @nobody doesn't crash."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = ProactiveCognitiveLoop(interval=60)
        rt = MagicMock()
        rt.callsign_registry = MagicMock()
        rt.callsign_registry.get_agent_type = MagicMock(return_value=None)
        loop._runtime = rt

        agent = MagicMock()
        agent.agent_type = "counselor"
        agent.id = "couns-001"

        text = "[DM @nobody]\nHello?\n[/DM]"
        cleaned, actions = await loop._extract_and_execute_dms(agent, text)
        assert len(actions) == 0

    @pytest.mark.asyncio
    async def test_dm_action_tag_self_dm_skipped(self):
        """Agent can't DM themselves."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = ProactiveCognitiveLoop(interval=60)
        rt = MagicMock()
        rt.callsign_registry = MagicMock()
        rt.callsign_registry.get_agent_type = MagicMock(return_value="counselor")
        loop._runtime = rt

        agent = MagicMock()
        agent.agent_type = "counselor"
        agent.id = "couns-001"

        text = "[DM @Troi]\nNote to self.\n[/DM]"
        cleaned, actions = await loop._extract_and_execute_dms(agent, text)
        assert len(actions) == 0

    @pytest.mark.asyncio
    async def test_dm_action_requires_commander_rank(self):
        """Lieutenant can't send DMs (earned agency gate)."""
        from probos.earned_agency import can_perform_action, Rank
        assert not can_perform_action(Rank.LIEUTENANT, "dm")

    @pytest.mark.asyncio
    async def test_dm_action_commander_can_send(self):
        """Commander rank allows DMs."""
        from probos.earned_agency import can_perform_action, Rank
        assert can_perform_action(Rank.COMMANDER, "dm")


class TestDmApi:
    @pytest.mark.asyncio
    async def test_dm_api_list_dm_channels(self, wr):
        """GET /api/wardroom/dms returns only DM channels."""
        # Create a DM channel
        await wr.get_or_create_dm_channel("a-001", "b-002", "Bones", "Troi")

        channels = await wr.list_channels()
        dm_channels = [c for c in channels if c.channel_type == "dm"]
        non_dm = [c for c in channels if c.channel_type != "dm"]
        assert len(dm_channels) == 1
        assert len(non_dm) > 0  # Default channels exist

    @pytest.mark.asyncio
    async def test_dm_api_list_dm_threads(self, wr):
        """DM channel threads can be listed."""
        ch = await wr.get_or_create_dm_channel("a-001", "b-002")
        await wr.create_thread(
            channel_id=ch.id, author_id="a-001",
            title="Test DM", body="Hello from A to B",
        )
        threads = await wr.list_threads(ch.id)
        assert len(threads) == 1

    @pytest.mark.asyncio
    async def test_dm_api_non_dm_channel_404(self, wr):
        """Non-DM channel should not appear in DM listing."""
        channels = await wr.list_channels()
        non_dm_ch = next(c for c in channels if c.channel_type != "dm")
        dm_channels = [c for c in channels if c.channel_type == "dm"]
        assert non_dm_ch.id not in {c.id for c in dm_channels}
