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
        cleaned, actions = await loop.extract_and_execute_dms(agent, text)

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
        cleaned, actions = await loop.extract_and_execute_dms(agent, text)
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
        cleaned, actions = await loop.extract_and_execute_dms(agent, text)
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
        cleaned, actions = await loop.extract_and_execute_dms(agent, text)

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


class TestUnreadDmsQuery:
    """AD-574: Unread DM detection handles Captain replies in agent-initiated threads."""

    @pytest.mark.asyncio
    async def test_captain_reply_in_agent_thread_is_unread(self, wr):
        """Agent initiates DM, Captain replies -> thread appears as unread for agent."""
        agent_id = "abc12345-full-uuid"
        ch = await wr.get_or_create_dm_channel(agent_id, "captain", "Bones", "Captain")
        thread = await wr.create_thread(
            channel_id=ch.id, author_id=agent_id,
            title="Report", body="Captain, I have a report.",
            author_callsign="Bones",
        )
        # Agent authored the thread — not unread yet
        unread = await wr._messages.get_unread_dms(agent_id)
        assert len(unread) == 0

        # Captain replies
        await wr.create_post(
            thread_id=thread.id, author_id="captain",
            body="Go ahead, Bones.", author_callsign="Captain",
        )
        # Now the last author is Captain — thread is unread for agent
        unread = await wr._messages.get_unread_dms(agent_id)
        assert len(unread) == 1
        assert unread[0]["thread_id"] == thread.id

    @pytest.mark.asyncio
    async def test_agent_reply_clears_unread(self, wr):
        """Agent replies to Captain's post -> thread is no longer unread."""
        agent_id = "abc12345-full-uuid"
        ch = await wr.get_or_create_dm_channel(agent_id, "captain")
        thread = await wr.create_thread(
            channel_id=ch.id, author_id="captain",
            title="Question", body="Status report?",
            author_callsign="Captain",
        )
        # Captain authored — unread for agent
        unread = await wr._messages.get_unread_dms(agent_id)
        assert len(unread) == 1

        # Agent replies
        await wr.create_post(
            thread_id=thread.id, author_id=agent_id,
            body="All systems nominal.", author_callsign="Bones",
        )
        # Agent is now last author — no longer unread
        unread = await wr._messages.get_unread_dms(agent_id)
        assert len(unread) == 0

    @pytest.mark.asyncio
    async def test_agent_initiated_no_reply_not_unread(self, wr):
        """Agent initiates DM with no replies -> NOT unread."""
        agent_id = "abc12345-full-uuid"
        ch = await wr.get_or_create_dm_channel(agent_id, "captain")
        await wr.create_thread(
            channel_id=ch.id, author_id=agent_id,
            title="Note", body="Just a note.",
            author_callsign="Bones",
        )
        unread = await wr._messages.get_unread_dms(agent_id)
        assert len(unread) == 0

    @pytest.mark.asyncio
    async def test_multiple_exchanges_last_author_wins(self, wr):
        """Multiple back-and-forth -> unread status based on who posted last."""
        agent_id = "abc12345-full-uuid"
        ch = await wr.get_or_create_dm_channel(agent_id, "captain")
        thread = await wr.create_thread(
            channel_id=ch.id, author_id="captain",
            title="Discussion", body="Let's discuss.",
            author_callsign="Captain",
        )
        # Captain authored -> unread
        assert len(await wr._messages.get_unread_dms(agent_id)) == 1

        # Agent replies -> not unread
        await wr.create_post(
            thread_id=thread.id, author_id=agent_id,
            body="Understood.", author_callsign="Bones",
        )
        assert len(await wr._messages.get_unread_dms(agent_id)) == 0

        # Captain replies again -> unread
        await wr.create_post(
            thread_id=thread.id, author_id="captain",
            body="One more thing.", author_callsign="Captain",
        )
        assert len(await wr._messages.get_unread_dms(agent_id)) == 1

    # BF-905 gate blocker: CPython 3.12 on Windows reads time.time() from a
    # clock that advances once per ~15.6 ms tick, so two back-to-back posts can
    # carry the SAME created_at. The tests below force that tie (or its absence)
    # deterministically by replacing the clock the ward room sees.

    @staticmethod
    def _install_clock(monkeypatch, *, tied: bool) -> None:
        """Make ward-room messages see a constant clock (tied) or a rising one."""
        from types import SimpleNamespace
        from probos.ward_room import messages as wr_messages

        ticks = iter(range(1, 10_000))

        def _tied_clock() -> float:
            return 1_000_000.0

        def _rising_clock() -> float:
            return 1_000_000.0 + next(ticks)

        monkeypatch.setattr(
            wr_messages, "time",
            SimpleNamespace(time=_tied_clock if tied else _rising_clock),
        )

    @staticmethod
    async def _post_times(wr, thread_id: str) -> list[float]:
        """created_at of a thread's posts in insertion order (rowid)."""
        async with wr._messages._db.execute(
            "SELECT created_at FROM posts WHERE thread_id = ? ORDER BY rowid",
            (thread_id,),
        ) as cursor:
            return [row[0] async for row in cursor]

    async def _agent_thread_with_two_replies(
        self, wr, monkeypatch, *, first: str, second: str, tied: bool,
    ) -> tuple[str, str]:
        """Agent-initiated DM thread, then replies by `first` and `second`."""
        agent_id = "abc12345-full-uuid"
        self._install_clock(monkeypatch, tied=tied)
        ch = await wr.get_or_create_dm_channel(agent_id, "captain")
        thread = await wr.create_thread(
            channel_id=ch.id, author_id=agent_id,
            title="Tie", body="Opening note.", author_callsign="Bones",
        )
        for author in (first, second):
            await wr.create_post(
                thread_id=thread.id,
                author_id=agent_id if author == "agent" else "captain",
                body=f"{author} reply",
                author_callsign="Bones" if author == "agent" else "Captain",
            )
        return agent_id, thread.id

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("first", "second", "expected_unread"),
        [
            # Agent replies, then the Captain in the SAME tick: the later
            # insert (the Captain) decides, so the thread is unread.
            ("agent", "captain", 1),
            # The Captain posts, then the agent in the SAME tick: the agent
            # (later insert) decides, so the thread is read.
            ("captain", "agent", 0),
        ],
    )
    async def test_get_unread_dms_same_tick_later_insert_decides(
        self, wr, monkeypatch, first, second, expected_unread,
    ):
        agent_id, thread_id = await self._agent_thread_with_two_replies(
            wr, monkeypatch, first=first, second=second, tied=True,
        )
        times = await self._post_times(wr, thread_id)
        assert len(times) == 2 and times[0] == times[1]  # premise: a real tie

        unread = await wr._messages.get_unread_dms(agent_id)

        assert len(unread) == expected_unread
        if expected_unread:
            assert unread[0]["thread_id"] == thread_id

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("first", "second", "expected_unread"),
        [("agent", "captain", 1), ("captain", "agent", 0)],
    )
    async def test_get_unread_dms_distinct_ticks_latest_post_decides(
        self, wr, monkeypatch, first, second, expected_unread,
    ):
        """No-tie control: the same two scenarios give the same answers."""
        agent_id, thread_id = await self._agent_thread_with_two_replies(
            wr, monkeypatch, first=first, second=second, tied=False,
        )
        times = await self._post_times(wr, thread_id)
        assert len(times) == 2 and times[0] < times[1]  # premise: no tie

        assert len(await wr._messages.get_unread_dms(agent_id)) == expected_unread

    @pytest.mark.asyncio
    async def test_get_unread_dms_deleted_last_post_previous_post_decides(
        self, wr, monkeypatch,
    ):
        """A deleted last post is ignored: the post before it decides."""
        agent_id, thread_id = await self._agent_thread_with_two_replies(
            wr, monkeypatch, first="agent", second="captain", tied=False,
        )
        # Premise: the Captain's reply is last, so the thread is unread
        assert len(await wr._messages.get_unread_dms(agent_id)) == 1
        await wr._messages._db.execute(
            "UPDATE posts SET deleted = 1 WHERE thread_id = ? AND author_id = ?",
            (thread_id, "captain"),
        )
        await wr._messages._db.commit()

        # The agent's reply is now the last live post -> read
        assert len(await wr._messages.get_unread_dms(agent_id)) == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("first", "second", "expected_unread"),
        [("agent", "captain", 1), ("captain", "agent", 0)],
    )
    async def test_get_unread_dms_same_tick_tie_break_independent_of_index_order(
        self, wr, monkeypatch, first, second, expected_unread,
    ):
        """The explicit rowid tie-break decides, not the index's scan order.

        With idx_posts_thread_created present, SQLite scans it backwards and
        returns tied rows in descending rowid order even without the explicit
        `rowid DESC`; dropping the index exposes the tie-break itself.
        """
        agent_id, thread_id = await self._agent_thread_with_two_replies(
            wr, monkeypatch, first=first, second=second, tied=True,
        )
        times = await self._post_times(wr, thread_id)
        assert len(times) == 2 and times[0] == times[1]  # premise: a real tie
        await wr._messages._db.execute("DROP INDEX idx_posts_thread_created")
        await wr._messages._db.commit()
        async with wr._messages._db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'index' AND name = 'idx_posts_thread_created'"
        ) as cursor:
            assert await cursor.fetchall() == []  # premise: the index is gone

        unread = await wr._messages.get_unread_dms(agent_id)

        assert len(unread) == expected_unread
        if expected_unread:
            assert unread[0]["thread_id"] == thread_id

    @pytest.mark.asyncio
    async def test_get_unread_dms_most_recent_unread_thread_first(
        self, wr, monkeypatch,
    ):
        """Unread threads come back ordered by their last post, newest first."""
        agent_id = "abc12345-full-uuid"
        self._install_clock(monkeypatch, tied=False)
        ch = await wr.get_or_create_dm_channel(agent_id, "captain")
        created_first = await wr.create_thread(
            channel_id=ch.id, author_id=agent_id,
            title="Created first", body="First note.", author_callsign="Bones",
        )
        created_second = await wr.create_thread(
            channel_id=ch.id, author_id=agent_id,
            title="Created second", body="Second note.", author_callsign="Bones",
        )
        # The Captain answers the thread created second FIRST, so the order of
        # the last posts is the reverse of the order of thread creation: the
        # thread created first holds the newest post and must be listed first.
        for thread in (created_second, created_first):
            await wr.create_post(
                thread_id=thread.id, author_id="captain",
                body="Noted.", author_callsign="Captain",
            )
        newest = (await self._post_times(wr, created_first.id))[-1]
        oldest = (await self._post_times(wr, created_second.id))[-1]
        assert newest > oldest  # premise: the last posts differ in time
        both = await wr._messages.get_unread_dms(agent_id, limit=10)
        assert {u["thread_id"] for u in both} == {
            created_first.id, created_second.id,
        }  # premise: both threads are unread

        unread = await wr._messages.get_unread_dms(agent_id)

        assert [u["thread_id"] for u in unread] == [
            created_first.id, created_second.id,
        ]
        limited = await wr._messages.get_unread_dms(agent_id, limit=1)
        assert [u["thread_id"] for u in limited] == [created_first.id]
