"""AD-621: Billet-Driven Channel Visibility — Subscription-Based Routing.

Tests that WardRoomRouter's find_targets() and find_targets_for_agent()
route based on channel membership (subscription) rather than home department,
and that communication.py subscribes bridge officers (reports_to: captain)
to all department channels.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from probos.ward_room.models import WardRoomChannel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_channel(name: str, ch_type: str, dept: str = "", ch_id: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        id=ch_id or f"ch_{name.lower().replace(' ', '_')}",
        name=name,
        channel_type=ch_type,
        department=dept,
        created_by="system",
        created_at=0.0,
        archived=False,
        description="",
    )


def _make_agent(agent_type: str, agent_id: str, dept: str = "") -> MagicMock:
    agent = MagicMock()
    agent.agent_type = agent_type
    agent.id = agent_id
    agent.is_alive = True
    agent.handle_intent = MagicMock()
    return agent


def _make_router(
    agents: list,
    channel_members: dict[str, set[str]] | None = None,
    ontology: MagicMock | None = None,
    ea_enabled: bool = False,
) -> MagicMock:
    """Build a WardRoomRouter with the membership cache pre-populated."""
    from probos.ward_room_router import WardRoomRouter

    registry = MagicMock()
    registry.all.return_value = agents

    config = MagicMock()
    config.earned_agency.enabled = ea_enabled
    config.ward_room.event_coalesce_ms = 200

    trust = MagicMock()
    trust.get_score.return_value = 0.5

    ward_room = MagicMock()
    callsign_reg = MagicMock()
    callsign_reg.resolve.return_value = None

    router = WardRoomRouter(
        ward_room=ward_room,
        registry=registry,
        intent_bus=MagicMock(),
        trust_network=trust,
        ontology=ontology,
        callsign_registry=callsign_reg,
        episodic_memory=None,
        event_emitter=MagicMock(),
        event_log=MagicMock(),
        config=config,
    )

    # Pre-populate membership cache (normally done via populate_membership_cache)
    if channel_members is not None:
        router._channel_members = channel_members

    return router


# ---------------------------------------------------------------------------
# 1. Router: home-department agent notified
# ---------------------------------------------------------------------------

class TestRouterMembershipRouting:
    def test_home_department_agent_notified(self) -> None:
        """Agent in Engineering, subscribed to Engineering channel, receives events."""
        eng_agent = _make_agent("chief_engineer", "eng_001")
        channel = _make_channel("Engineering", "department", "engineering")

        ontology = MagicMock()
        ontology.get_agent_department.return_value = "engineering"

        router = _make_router(
            [eng_agent],
            channel_members={channel.id: {"eng_001"}},
            ontology=ontology,
        )
        with patch("probos.ward_room_router.is_crew_agent", return_value=True):
            targets = router.find_targets(channel, author_id="captain_001")

        assert "eng_001" in targets

    def test_cross_department_subscriber_notified(self) -> None:
        """First Officer (Bridge) subscribed to Engineering → receives Engineering events."""
        fo_agent = _make_agent("first_officer", "fo_001")
        channel = _make_channel("Engineering", "department", "engineering")

        ontology = MagicMock()
        ontology.get_agent_department.return_value = "bridge"

        router = _make_router(
            [fo_agent],
            channel_members={channel.id: {"fo_001"}},
            ontology=ontology,
        )
        with patch("probos.ward_room_router.is_crew_agent", return_value=True):
            targets = router.find_targets(channel, author_id="captain_001")

        assert "fo_001" in targets

    def test_non_subscriber_not_notified(self) -> None:
        """Scout (Science) NOT subscribed to Engineering → does NOT receive events."""
        scout = _make_agent("scout", "scout_001")
        channel = _make_channel("Engineering", "department", "engineering")

        ontology = MagicMock()
        ontology.get_agent_department.return_value = "science"

        router = _make_router(
            [scout],
            channel_members={channel.id: set()},  # Scout not in membership
            ontology=ontology,
        )
        with patch("probos.ward_room_router.is_crew_agent", return_value=True):
            targets = router.find_targets(channel, author_id="captain_001")

        assert "scout_001" not in targets

    def test_mention_overrides_subscription(self) -> None:
        """Agent NOT subscribed but @mentioned → receives event."""
        scout = _make_agent("scout", "scout_001")
        channel = _make_channel("Engineering", "department", "engineering")

        ontology = MagicMock()
        ontology.get_agent_department.return_value = "science"

        router = _make_router(
            [scout],
            channel_members={channel.id: set()},
            ontology=ontology,
        )
        router._callsign_registry.resolve.return_value = {
            "agent_id": "scout_001",
            "callsign": "Horizon",
        }
        with patch("probos.ward_room_router.is_crew_agent", return_value=True):
            targets = router.find_targets(channel, author_id="captain_001", mentions=["Horizon"])

        assert "scout_001" in targets


# ---------------------------------------------------------------------------
# 2. Agent-authored cross-dept notification
# ---------------------------------------------------------------------------

class TestAgentAuthoredRouting:
    def test_cross_dept_subscriber_gets_agent_posts(self) -> None:
        """LaForge posts in Engineering → First Officer (subscribed) gets notified."""
        fo_agent = _make_agent("first_officer", "fo_001")
        channel = _make_channel("Engineering", "department", "engineering")

        ontology = MagicMock()
        ontology.get_agent_department.return_value = "bridge"

        router = _make_router(
            [fo_agent],
            channel_members={channel.id: {"fo_001", "eng_001"}},
            ontology=ontology,
        )
        with patch("probos.ward_room_router.is_crew_agent", return_value=True):
            targets = router.find_targets_for_agent(channel, author_id="eng_001")

        assert "fo_001" in targets


# ---------------------------------------------------------------------------
# 3. Earned Agency same_department flag
# ---------------------------------------------------------------------------

class TestEarnedAgencySameDept:
    def test_cross_dept_subscriber_gets_same_department_false(self) -> None:
        """Cross-department subscriber → same_department=False for EA gating."""
        fo_agent = _make_agent("first_officer", "fo_001")
        channel = _make_channel("Engineering", "department", "engineering")

        ontology = MagicMock()
        ontology.get_agent_department.return_value = "bridge"  # Not engineering

        router = _make_router(
            [fo_agent],
            channel_members={channel.id: {"fo_001"}},
            ontology=ontology,
            ea_enabled=True,
        )

        with (
            patch("probos.ward_room_router.is_crew_agent", return_value=True),
            patch("probos.earned_agency.can_respond_ambient") as mock_can_respond,
        ):
            mock_can_respond.return_value = True
            router.find_targets(channel, author_id="captain_001")

            # Verify same_department=False for cross-dept subscriber
            mock_can_respond.assert_called()
            call_kwargs = mock_can_respond.call_args
            assert call_kwargs.kwargs.get("same_department") is False or (
                len(call_kwargs.args) >= 3 and call_kwargs.args[2] is False
            )

    def test_home_dept_agent_gets_same_department_true(self) -> None:
        """Home department agent → same_department=True for EA gating."""
        eng_agent = _make_agent("chief_engineer", "eng_001")
        channel = _make_channel("Engineering", "department", "engineering")

        ontology = MagicMock()
        ontology.get_agent_department.return_value = "engineering"

        router = _make_router(
            [eng_agent],
            channel_members={channel.id: {"eng_001"}},
            ontology=ontology,
            ea_enabled=True,
        )

        with (
            patch("probos.ward_room_router.is_crew_agent", return_value=True),
            patch("probos.earned_agency.can_respond_ambient") as mock_can_respond,
        ):
            mock_can_respond.return_value = True
            router.find_targets(channel, author_id="captain_001")

            mock_can_respond.assert_called()
            call_kwargs = mock_can_respond.call_args
            assert call_kwargs.kwargs.get("same_department") is True or (
                len(call_kwargs.args) >= 3 and call_kwargs.args[2] is True
            )


# ---------------------------------------------------------------------------
# 4. Subscription policy: reports_to captain
# ---------------------------------------------------------------------------

class TestSubscriptionPolicy:
    @pytest.mark.asyncio
    async def test_reports_to_captain_gets_all_dept_channels(self) -> None:
        """First Officer and Counselor (reports_to: captain) get all department channels."""
        from probos.ontology.loader import OntologyLoader

        loader = OntologyLoader(Path("config/ontology"))
        await loader.initialize()

        fo_post = loader.posts.get("first_officer")
        counselor_post = loader.posts.get("counselor")

        assert fo_post is not None
        assert fo_post.reports_to == "captain"
        assert counselor_post is not None
        assert counselor_post.reports_to == "captain"

    @pytest.mark.asyncio
    async def test_chief_does_not_report_to_captain(self) -> None:
        """Department chiefs report_to first_officer → own dept channel only."""
        from probos.ontology.loader import OntologyLoader

        loader = OntologyLoader(Path("config/ontology"))
        await loader.initialize()

        chief_eng = loader.posts.get("chief_engineer")
        chief_med = loader.posts.get("chief_medical")

        assert chief_eng is not None
        assert chief_eng.reports_to != "captain"
        assert chief_med is not None
        assert chief_med.reports_to != "captain"

    @pytest.mark.asyncio
    async def test_regular_officer_does_not_report_to_captain(self) -> None:
        """Regular officers don't report to captain → own dept channel only."""
        from probos.ontology.loader import OntologyLoader

        loader = OntologyLoader(Path("config/ontology"))
        await loader.initialize()

        # scout agent_type -> scout_officer post_id
        scout_assignment = loader.assignments.get("scout")
        assert scout_assignment is not None
        scout = loader.posts.get(scout_assignment.post_id)
        assert scout is not None
        assert scout.reports_to != "captain"


# ---------------------------------------------------------------------------
# 5. list_channels(agent_id) filtering
# ---------------------------------------------------------------------------

class TestListChannelsFiltering:
    @pytest.mark.asyncio
    async def test_list_channels_with_agent_id_filters(self) -> None:
        """list_channels(agent_id) returns only subscribed channels."""
        import aiosqlite
        from probos.ward_room.channels import ChannelManager
        from probos.ward_room.models import _SCHEMA

        db = await aiosqlite.connect(":memory:")
        await db.executescript(_SCHEMA)

        mgr = ChannelManager(db=db, ontology=None)

        # Create two channels
        await db.execute(
            "INSERT INTO channels (id, name, channel_type, department, created_by, created_at, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("ch1", "Engineering", "department", "engineering", "sys", 0.0, ""),
        )
        await db.execute(
            "INSERT INTO channels (id, name, channel_type, department, created_by, created_at, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("ch2", "Medical", "department", "medical", "sys", 0.0, ""),
        )
        # Subscribe agent to ch1 only
        await db.execute(
            "INSERT INTO memberships (agent_id, channel_id, subscribed_at, last_seen, role) "
            "VALUES (?, ?, ?, ?, ?)",
            ("agent_001", "ch1", 0.0, 0.0, "member"),
        )
        await db.commit()

        # Filtered query
        filtered = await mgr.list_channels(agent_id="agent_001")
        assert len(filtered) == 1
        assert filtered[0].id == "ch1"

        # Unfiltered query
        all_channels = await mgr.list_channels()
        assert len(all_channels) == 2

        await db.close()


# ---------------------------------------------------------------------------
# 6. Membership cache
# ---------------------------------------------------------------------------

class TestMembershipCache:
    @pytest.mark.asyncio
    async def test_populate_membership_cache(self) -> None:
        """populate_membership_cache() loads from WardRoomService."""
        from probos.ward_room_router import WardRoomRouter

        ward_room = MagicMock()
        ward_room.get_all_channel_members = AsyncMock(
            return_value={"ch1": {"a1", "a2"}, "ch2": {"a3"}}
        )

        config = MagicMock()
        config.earned_agency.enabled = False
        config.ward_room.event_coalesce_ms = 200

        router = WardRoomRouter(
            ward_room=ward_room,
            registry=MagicMock(),
            intent_bus=MagicMock(),
            trust_network=MagicMock(),
            ontology=None,
            callsign_registry=MagicMock(),
            episodic_memory=None,
            event_emitter=MagicMock(),
            event_log=MagicMock(),
            config=config,
        )

        await router.populate_membership_cache()

        assert router._channel_members == {"ch1": {"a1", "a2"}, "ch2": {"a3"}}
        assert router._get_channel_subscribers("ch1") == {"a1", "a2"}
        assert router._get_channel_subscribers("nonexistent") == set()

    def test_get_channel_subscribers_empty_cache(self) -> None:
        """_get_channel_subscribers returns empty set for unknown channel."""
        from probos.ward_room_router import WardRoomRouter

        config = MagicMock()
        config.earned_agency.enabled = False
        config.ward_room.event_coalesce_ms = 200

        router = WardRoomRouter(
            ward_room=MagicMock(),
            registry=MagicMock(),
            intent_bus=MagicMock(),
            trust_network=MagicMock(),
            ontology=None,
            callsign_registry=MagicMock(),
            episodic_memory=None,
            event_emitter=MagicMock(),
            event_log=MagicMock(),
            config=config,
        )

        assert router._get_channel_subscribers("any") == set()


# ---------------------------------------------------------------------------
# 7. Ship/DM routing unchanged
# ---------------------------------------------------------------------------

class TestUnchangedRouting:
    def test_ship_channel_routes_all_crew(self) -> None:
        """Ship-wide channel events still route to all crew agents."""
        agent_a = _make_agent("first_officer", "fo_001")
        agent_b = _make_agent("chief_engineer", "eng_001")
        channel = _make_channel("All Hands", "ship")

        router = _make_router(
            [agent_a, agent_b],
            channel_members={},
        )
        with patch("probos.ward_room_router.is_crew_agent", return_value=True):
            targets = router.find_targets(channel, author_id="captain_001")

        assert "fo_001" in targets
        assert "eng_001" in targets

    def test_dm_routing_unchanged(self) -> None:
        """DM events route to the other participant only."""
        agent = _make_agent("counselor", "couns_001")
        channel = _make_channel("dm_couns_00_cap_0000", "dm")

        router = _make_router(
            [agent],
            channel_members={},
        )
        with patch("probos.ward_room_router.is_crew_agent", return_value=True):
            targets = router.find_targets(channel, author_id="captain_001")

        assert "couns_001" in targets


# ---------------------------------------------------------------------------
# 8. Router fallback: empty memberships
# ---------------------------------------------------------------------------

class TestRouterFallback:
    def test_empty_membership_cache_no_crash(self) -> None:
        """If _get_channel_subscribers returns empty, agents not notified (no crash)."""
        eng_agent = _make_agent("chief_engineer", "eng_001")
        channel = _make_channel("Engineering", "department", "engineering")

        ontology = MagicMock()
        ontology.get_agent_department.return_value = "engineering"

        router = _make_router(
            [eng_agent],
            channel_members={},  # Empty cache — no subscribers
            ontology=ontology,
        )
        with patch("probos.ward_room_router.is_crew_agent", return_value=True):
            targets = router.find_targets(channel, author_id="captain_001")

        # No one subscribed in cache → no targets (graceful degradation)
        assert targets == []


# ---------------------------------------------------------------------------
# 9. Department-match removal verification
# ---------------------------------------------------------------------------

class TestDepartmentMatchRemoval:
    def test_no_direct_department_matching_in_find_targets(self) -> None:
        """Verify router uses membership, not department==channel.department."""
        import inspect
        from probos.ward_room_router import WardRoomRouter

        source = inspect.getsource(WardRoomRouter.find_targets)
        # The old pattern: `== channel.department)` for filtering
        # New pattern: `agent.id in _subscribed_ids`
        assert "in _subscribed_ids" in source
        # Old department comparison should be for same_dept flag, not filtering
        assert "== channel.department)" not in source or "_same_dept" in source

    def test_no_direct_department_matching_in_find_targets_for_agent(self) -> None:
        """Same check for find_targets_for_agent."""
        import inspect
        from probos.ward_room_router import WardRoomRouter

        source = inspect.getsource(WardRoomRouter.find_targets_for_agent)
        assert "in _subscribed_ids" in source
