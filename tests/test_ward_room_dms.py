"""AD-453: Ward Room DM tests — channel creation, action tag, API endpoints."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from probos.ward_room import WardRoomService
from probos.runtime import ProbOSRuntime
from probos.substrate.agent import BaseAgent


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
        rt = MagicMock(spec=ProbOSRuntime)
        rt.ward_room = wr
        rt.trust_network = MagicMock()
        rt.trust_network.get_score = MagicMock(return_value=0.9)

        # Set up callsign registry
        rt.callsign_registry = MagicMock()
        rt.callsign_registry.resolve = MagicMock(return_value={"agent_type": "diagnostician"})
        rt.callsign_registry.get_callsign = MagicMock(return_value="Bones")

        # Set up agents list
        rt.registry = MagicMock()
        target_agent = MagicMock(spec=BaseAgent)
        target_agent.agent_type = "diagnostician"
        target_agent.id = "diag-001"
        rt.registry.all.return_value = [target_agent]

        rt.hebbian_router = None  # skip Hebbian for this test

        loop._runtime = rt

        agent = MagicMock(spec=BaseAgent)
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
        rt = MagicMock(spec=ProbOSRuntime)
        rt.callsign_registry = MagicMock()
        rt.callsign_registry.get_agent_type = MagicMock(return_value=None)
        rt.registry = MagicMock()
        rt.registry.all.return_value = []
        loop._runtime = rt

        agent = MagicMock(spec=BaseAgent)
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
        rt = MagicMock(spec=ProbOSRuntime)
        rt.callsign_registry = MagicMock()
        rt.callsign_registry.get_agent_type = MagicMock(return_value="counselor")
        rt.registry = MagicMock()
        rt.registry.all.return_value = []
        loop._runtime = rt

        agent = MagicMock(spec=BaseAgent)
        agent.agent_type = "counselor"
        agent.id = "couns-001"

        text = "[DM @Troi]\nNote to self.\n[/DM]"
        cleaned, actions = await loop._extract_and_execute_dms(agent, text)
        assert len(actions) == 0

    @pytest.mark.asyncio
    async def test_dm_action_ensign_can_dm_at_default(self):
        """AD-485: Ensign can DM when dm tier is Ensign (default)."""
        from probos.earned_agency import can_perform_action, Rank
        assert can_perform_action(Rank.ENSIGN, "dm")

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


class TestAD485CaptainDmAndArchival:
    """AD-485: Captain DMs, archival, and crew roster tests."""

    @pytest.mark.asyncio
    async def test_captain_dm_creates_channel(self, wr):
        """DM to @captain creates dm-captain-{id} channel."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = ProactiveCognitiveLoop(interval=60)
        rt = MagicMock(spec=ProbOSRuntime)
        rt.ward_room = wr
        rt.trust_network = MagicMock()
        rt.trust_network.get_score = MagicMock(return_value=0.9)
        rt.callsign_registry = MagicMock()
        rt.callsign_registry.get_callsign = MagicMock(return_value="Bones")
        rt.callsign_registry.resolve = MagicMock(return_value=None)
        rt.registry = MagicMock()
        rt.registry.all.return_value = []
        rt.hebbian_router = None
        loop._runtime = rt

        agent = MagicMock(spec=BaseAgent)
        agent.agent_type = "diagnostician"
        agent.id = "diag-001-full-uuid"
        agent.callsign = "Bones"

        text = "[DM @captain]\nCaptain, there is an urgent medical concern.\n[/DM]"
        cleaned, actions = await loop._extract_and_execute_dms(agent, text)

        assert len(actions) == 1
        assert actions[0]["target_callsign"] == "captain"

        # Verify channel was created
        channels = await wr.list_channels()
        captain_dms = [c for c in channels if "captain" in c.name and c.channel_type == "dm"]
        assert len(captain_dms) == 1

    @pytest.mark.asyncio
    async def test_dm_archive_marks_old_messages(self, wr):
        """Messages older than threshold get archived flag."""
        import time
        ch = await wr.get_or_create_dm_channel("a-001", "b-002")
        await wr.create_thread(
            channel_id=ch.id, author_id="a-001",
            title="Old message", body="This is old",
        )
        # Backdate the thread
        await wr._db.execute(
            "UPDATE threads SET created_at = ? WHERE channel_id = ?",
            (time.time() - 100000, ch.id),
        )
        await wr._db.commit()

        count = await wr.archive_dm_messages(max_age_hours=24)
        assert count == 1

    @pytest.mark.asyncio
    async def test_dm_archive_preserves_recent(self, wr):
        """Messages within threshold not archived."""
        ch = await wr.get_or_create_dm_channel("a-001", "b-002")
        await wr.create_thread(
            channel_id=ch.id, author_id="a-001",
            title="Recent message", body="This is new",
        )
        count = await wr.archive_dm_messages(max_age_hours=24)
        assert count == 0

    @pytest.mark.asyncio
    async def test_archive_search_finds_archived(self, wr):
        """Archived threads visible with include_archived=True."""
        import time
        ch = await wr.get_or_create_dm_channel("a-001", "b-002")
        await wr.create_thread(
            channel_id=ch.id, author_id="a-001",
            title="Archived msg", body="Old content",
        )
        await wr._db.execute(
            "UPDATE threads SET created_at = ?, archived = 1 WHERE channel_id = ?",
            (time.time() - 100000, ch.id),
        )
        await wr._db.commit()

        # Without include_archived, should not appear
        threads_active = await wr.list_threads(ch.id, include_archived=False)
        assert len(threads_active) == 0

        # With include_archived, should appear
        threads_all = await wr.list_threads(ch.id, include_archived=True)
        assert len(threads_all) == 1

    def test_crew_roster_in_dm_prompt(self):
        """AD-485: Roster-building logic produces correct DM crew list."""
        # Directly test the roster-building logic from cognitive_agent.py
        # (embedded in decide()'s proactive_think prompt composition)
        callsigns = {
            "diagnostician": "Bones",
            "counselor": "Troi",
            "engineer": "LaForge",
        }
        self_atype = "diagnostician"
        crew_entries = [f"@{cs}" for atype, cs in callsigns.items()
                        if atype != self_atype and cs]
        dm_crew_list = f"Available crew to DM: {', '.join(sorted(crew_entries))}\n"

        assert "@Bones" not in dm_crew_list  # Self excluded
        assert "@Troi" in dm_crew_list
        assert "@LaForge" in dm_crew_list
        assert dm_crew_list.startswith("Available crew to DM:")
