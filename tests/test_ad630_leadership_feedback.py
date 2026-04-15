"""AD-630: Leadership Developmental Feedback -- tests."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_db():
    """Create an in-memory aiosqlite database with Ward Room schema."""
    import aiosqlite
    db = await aiosqlite.connect(":memory:")
    await db.execute(
        "CREATE TABLE IF NOT EXISTS threads ("
        "  id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, title TEXT,"
        "  author_id TEXT, created_at REAL, last_activity REAL,"
        "  pinned INTEGER DEFAULT 0, archived INTEGER DEFAULT 0,"
        "  depth INTEGER DEFAULT 0, parent_id TEXT,"
        "  total_post_count INTEGER DEFAULT 0,"
        "  thread_mode TEXT DEFAULT NULL"
        ")"
    )
    await db.execute(
        "CREATE TABLE IF NOT EXISTS posts ("
        "  id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, author_id TEXT NOT NULL,"
        "  body TEXT, created_at REAL, parent_id TEXT, deleted INTEGER DEFAULT 0"
        ")"
    )
    await db.execute(
        "CREATE TABLE IF NOT EXISTS endorsements ("
        "  id TEXT PRIMARY KEY, target_id TEXT NOT NULL, target_type TEXT NOT NULL,"
        "  voter_id TEXT NOT NULL, direction TEXT NOT NULL, created_at REAL NOT NULL"
        ")"
    )
    await db.execute(
        "CREATE TABLE IF NOT EXISTS credibility ("
        "  agent_id TEXT PRIMARY KEY, total_posts INTEGER DEFAULT 0,"
        "  total_endorsements INTEGER DEFAULT 0, credibility_score REAL DEFAULT 0.5,"
        "  restrictions TEXT DEFAULT NULL"
        ")"
    )
    await db.commit()
    return db


def _noop_emit(*a, **kw):
    """No-op event emit function for ThreadManager/MessageStore init."""
    pass


# ---------------------------------------------------------------------------
# 1. TestCrossThreadPostCounts
# ---------------------------------------------------------------------------

class TestCrossThreadPostCounts:
    """Tests for ThreadManager.count_all_posts_by_author()."""

    @pytest.mark.asyncio
    async def test_count_all_posts_by_author(self):
        from probos.ward_room.threads import ThreadManager
        db = await _make_db()
        try:
            tm = ThreadManager(db, _noop_emit)
            now = time.time()
            # Insert posts across two threads
            await db.execute(
                "INSERT INTO posts (id, thread_id, author_id, body, created_at, deleted) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("p1", "t1", "agent-a", "hello", now, 0),
            )
            await db.execute(
                "INSERT INTO posts (id, thread_id, author_id, body, created_at, deleted) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("p2", "t2", "agent-a", "world", now, 0),
            )
            await db.execute(
                "INSERT INTO posts (id, thread_id, author_id, body, created_at, deleted) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("p3", "t1", "agent-b", "other", now, 0),
            )
            await db.commit()

            count = await tm.count_all_posts_by_author("agent-a")
            assert count == 2
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_count_all_posts_by_author_with_since(self):
        from probos.ward_room.threads import ThreadManager
        db = await _make_db()
        try:
            tm = ThreadManager(db, _noop_emit)
            old_time = 1000.0
            new_time = 2000.0
            await db.execute(
                "INSERT INTO posts (id, thread_id, author_id, body, created_at, deleted) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("p1", "t1", "agent-a", "old", old_time, 0),
            )
            await db.execute(
                "INSERT INTO posts (id, thread_id, author_id, body, created_at, deleted) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("p2", "t1", "agent-a", "new", new_time, 0),
            )
            await db.commit()

            count = await tm.count_all_posts_by_author("agent-a", since=1500.0)
            assert count == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_count_all_posts_by_author_excludes_deleted(self):
        from probos.ward_room.threads import ThreadManager
        db = await _make_db()
        try:
            tm = ThreadManager(db, _noop_emit)
            now = time.time()
            await db.execute(
                "INSERT INTO posts (id, thread_id, author_id, body, created_at, deleted) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("p1", "t1", "agent-a", "live", now, 0),
            )
            await db.execute(
                "INSERT INTO posts (id, thread_id, author_id, body, created_at, deleted) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("p2", "t1", "agent-a", "deleted", now, 1),
            )
            await db.commit()

            count = await tm.count_all_posts_by_author("agent-a")
            assert count == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_count_all_posts_by_author_unknown_agent(self):
        from probos.ward_room.threads import ThreadManager
        db = await _make_db()
        try:
            tm = ThreadManager(db, _noop_emit)
            count = await tm.count_all_posts_by_author("unknown-agent")
            assert count == 0
        finally:
            await db.close()


# ---------------------------------------------------------------------------
# 2. TestEndorsementCounts
# ---------------------------------------------------------------------------

class TestEndorsementCounts:
    """Tests for MessageStore endorsement count methods."""

    @pytest.mark.asyncio
    async def test_count_endorsements_by_voter(self):
        from probos.ward_room.messages import MessageStore
        db = await _make_db()
        try:
            ms = MessageStore(db, _noop_emit)
            now = time.time()
            await db.execute(
                "INSERT INTO endorsements (id, target_id, target_type, voter_id, direction, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("e1", "p1", "post", "agent-a", "UP", now),
            )
            await db.execute(
                "INSERT INTO endorsements (id, target_id, target_type, voter_id, direction, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("e2", "p2", "post", "agent-a", "UP", now),
            )
            await db.execute(
                "INSERT INTO endorsements (id, target_id, target_type, voter_id, direction, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("e3", "p3", "post", "agent-b", "UP", now),
            )
            await db.commit()

            count = await ms.count_endorsements_by_voter("agent-a")
            assert count == 2
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_count_endorsements_by_voter_with_since(self):
        from probos.ward_room.messages import MessageStore
        db = await _make_db()
        try:
            ms = MessageStore(db, _noop_emit)
            await db.execute(
                "INSERT INTO endorsements (id, target_id, target_type, voter_id, direction, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("e1", "p1", "post", "agent-a", "UP", 1000.0),
            )
            await db.execute(
                "INSERT INTO endorsements (id, target_id, target_type, voter_id, direction, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("e2", "p2", "post", "agent-a", "UP", 2000.0),
            )
            await db.commit()

            count = await ms.count_endorsements_by_voter("agent-a", since=1500.0)
            assert count == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_count_endorsements_for_author(self):
        from probos.ward_room.messages import MessageStore
        db = await _make_db()
        try:
            ms = MessageStore(db, _noop_emit)
            now = time.time()
            # Create thread and post authored by agent-a
            await db.execute(
                "INSERT INTO threads (id, channel_id, title, author_id, created_at, last_activity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("t1", "ch1", "Thread 1", "agent-a", now, now),
            )
            await db.execute(
                "INSERT INTO posts (id, thread_id, author_id, body, created_at, deleted) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("p1", "t1", "agent-a", "hello", now, 0),
            )
            # Endorse the post
            await db.execute(
                "INSERT INTO endorsements (id, target_id, target_type, voter_id, direction, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("e1", "p1", "post", "agent-b", "UP", now),
            )
            await db.commit()

            count = await ms.count_endorsements_for_author("agent-a")
            assert count == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_count_endorsements_for_author_with_since(self):
        from probos.ward_room.messages import MessageStore
        db = await _make_db()
        try:
            ms = MessageStore(db, _noop_emit)
            # Create post authored by agent-a
            await db.execute(
                "INSERT INTO posts (id, thread_id, author_id, body, created_at, deleted) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("p1", "t1", "agent-a", "hello", 1000.0, 0),
            )
            # Old endorsement
            await db.execute(
                "INSERT INTO endorsements (id, target_id, target_type, voter_id, direction, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("e1", "p1", "post", "agent-b", "UP", 1000.0),
            )
            # New endorsement
            await db.execute(
                "INSERT INTO endorsements (id, target_id, target_type, voter_id, direction, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("e2", "p1", "post", "agent-c", "UP", 2000.0),
            )
            await db.commit()

            count = await ms.count_endorsements_for_author("agent-a", since=1500.0)
            assert count == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_count_endorsements_unknown_agent(self):
        from probos.ward_room.messages import MessageStore
        db = await _make_db()
        try:
            ms = MessageStore(db, _noop_emit)
            given = await ms.count_endorsements_by_voter("unknown")
            received = await ms.count_endorsements_for_author("unknown")
            assert given == 0
            assert received == 0
        finally:
            await db.close()


# ---------------------------------------------------------------------------
# 3. TestAgentCommStats
# ---------------------------------------------------------------------------

class TestAgentCommStats:
    """Tests for WardRoomService.get_agent_comm_stats() facade."""

    @pytest.mark.asyncio
    async def test_get_agent_comm_stats_all_fields(self):
        from probos.ward_room.service import WardRoomService
        svc = WardRoomService.__new__(WardRoomService)
        svc._threads = AsyncMock()
        svc._messages = AsyncMock()
        svc._threads.count_all_posts_by_author = AsyncMock(return_value=5)
        svc._messages.count_endorsements_by_voter = AsyncMock(return_value=2)
        svc._messages.count_endorsements_for_author = AsyncMock(return_value=3)
        cred_mock = MagicMock()
        cred_mock.credibility_score = 0.75
        svc._messages.get_credibility = AsyncMock(return_value=cred_mock)

        stats = await svc.get_agent_comm_stats("agent-a")
        assert stats["posts_total"] == 5
        assert stats["endorsements_given"] == 2
        assert stats["endorsements_received"] == 3
        assert stats["credibility_score"] == 0.75

    @pytest.mark.asyncio
    async def test_get_agent_comm_stats_with_since(self):
        from probos.ward_room.service import WardRoomService
        svc = WardRoomService.__new__(WardRoomService)
        svc._threads = AsyncMock()
        svc._messages = AsyncMock()
        svc._threads.count_all_posts_by_author = AsyncMock(return_value=1)
        svc._messages.count_endorsements_by_voter = AsyncMock(return_value=0)
        svc._messages.count_endorsements_for_author = AsyncMock(return_value=0)
        cred_mock = MagicMock()
        cred_mock.credibility_score = 0.5
        svc._messages.get_credibility = AsyncMock(return_value=cred_mock)

        stats = await svc.get_agent_comm_stats("agent-a", since=1000.0)
        svc._threads.count_all_posts_by_author.assert_called_once_with("agent-a", 1000.0)
        svc._messages.count_endorsements_by_voter.assert_called_once_with("agent-a", 1000.0)
        assert stats["posts_total"] == 1

    @pytest.mark.asyncio
    async def test_get_agent_comm_stats_no_activity(self):
        from probos.ward_room.service import WardRoomService
        svc = WardRoomService.__new__(WardRoomService)
        svc._threads = AsyncMock()
        svc._messages = AsyncMock()
        svc._threads.count_all_posts_by_author = AsyncMock(return_value=0)
        svc._messages.count_endorsements_by_voter = AsyncMock(return_value=0)
        svc._messages.count_endorsements_for_author = AsyncMock(return_value=0)
        cred_mock = MagicMock()
        cred_mock.credibility_score = 0.5
        svc._messages.get_credibility = AsyncMock(return_value=cred_mock)

        stats = await svc.get_agent_comm_stats("nobody")
        assert stats["posts_total"] == 0
        assert stats["endorsements_given"] == 0
        assert stats["endorsements_received"] == 0
        assert stats["credibility_score"] == 0.5


# ---------------------------------------------------------------------------
# 4. TestOntologyReverseLookup
# ---------------------------------------------------------------------------

class TestOntologyReverseLookup:
    """Tests for ontology reverse lookup methods."""

    def _make_dept_service(self):
        from probos.ontology.departments import DepartmentService
        from probos.ontology.models import Assignment, Department, Post

        posts = {
            "chief_eng": Post(
                id="chief_eng", title="Chief Engineer", department_id="engineering",
                reports_to="captain",
                authority_over=["eng_officer_1", "eng_officer_2"],
            ),
            "eng_officer_1": Post(
                id="eng_officer_1", title="Engineer 1", department_id="engineering",
                reports_to="chief_eng",
            ),
            "eng_officer_2": Post(
                id="eng_officer_2", title="Engineer 2", department_id="engineering",
                reports_to="chief_eng",
            ),
            "sci_officer": Post(
                id="sci_officer", title="Science Officer", department_id="science",
                reports_to="chief_sci",
            ),
        }
        departments = {
            "engineering": Department(id="engineering", name="Engineering", description=""),
            "science": Department(id="science", name="Science", description=""),
        }
        assignments = {
            "engineering_officer": Assignment(
                agent_type="engineering_officer", post_id="chief_eng", callsign="LaForge",
            ),
            "damage_control_officer": Assignment(
                agent_type="damage_control_officer", post_id="eng_officer_1", callsign="Forge",
            ),
            "systems_engineer": Assignment(
                agent_type="systems_engineer", post_id="eng_officer_2", callsign="Reyes",
            ),
            "science_analyst": Assignment(
                agent_type="science_analyst", post_id="sci_officer", callsign="Kira",
            ),
        }
        return DepartmentService(departments, posts, assignments)

    def test_get_agents_for_post(self):
        ds = self._make_dept_service()
        result = ds.get_agents_for_post("eng_officer_1")
        assert len(result) == 1
        assert result[0].agent_type == "damage_control_officer"

    def test_get_agents_for_post_unknown(self):
        ds = self._make_dept_service()
        result = ds.get_agents_for_post("nonexistent_post")
        assert result == []

    def test_get_subordinate_agent_types_chief(self):
        from probos.ontology.service import VesselOntologyService
        ds = self._make_dept_service()
        svc = VesselOntologyService.__new__(VesselOntologyService)
        svc._dept = ds
        svc._loader = MagicMock()

        result = svc.get_subordinate_agent_types("engineering_officer")
        assert set(result) == {"damage_control_officer", "systems_engineer"}

    def test_get_subordinate_agent_types_non_chief(self):
        from probos.ontology.service import VesselOntologyService
        ds = self._make_dept_service()
        svc = VesselOntologyService.__new__(VesselOntologyService)
        svc._dept = ds
        svc._loader = MagicMock()

        result = svc.get_subordinate_agent_types("science_analyst")
        assert result == []


# ---------------------------------------------------------------------------
# 5. TestChiefContextInjection
# ---------------------------------------------------------------------------

class TestChiefContextInjection:
    """Tests for subordinate stats injection in _gather_context()."""

    def _make_loop_and_rt(self, *, subordinate_types, sub_agents=None,
                          comm_stats=None):
        """Build a ProactiveCognitiveLoop with mocked runtime for context tests."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0)

        rt = MagicMock()
        rt.ontology = MagicMock()
        rt.ontology.get_subordinate_agent_types = MagicMock(
            return_value=subordinate_types
        )
        rt.ontology.get_crew_context = MagicMock(return_value=None)
        rt.ward_room_service = AsyncMock()
        if comm_stats is not None:
            rt.ward_room_service.get_agent_comm_stats = AsyncMock(
                return_value=comm_stats
            )
        rt.agent_pool = sub_agents or {}
        rt._start_time_wall = 1000.0
        rt.trust_network = AsyncMock()
        rt.trust_network.get_trust = AsyncMock(return_value=0.5)
        rt.skill_service = None
        rt._introspective_telemetry = None
        rt.conn_manager = None
        rt.cognitive_skill_catalog = None

        loop.set_runtime(rt)
        loop._build_self_monitoring_context = AsyncMock(return_value=None)

        return loop, rt

    @pytest.mark.asyncio
    async def test_chief_gets_subordinate_stats(self):
        """Chief agents receive subordinate_stats in context."""
        agent = MagicMock()
        agent.agent_type = "engineering_officer"
        agent.id = "chief-id"
        agent.sovereign_id = "chief-sov"
        agent.callsign = "LaForge"

        sub_agent = MagicMock()
        sub_agent.id = "sub-id"
        sub_agent.sovereign_id = "sub-sov"
        sub_agent.callsign = "Forge"

        loop, rt = self._make_loop_and_rt(
            subordinate_types=["damage_control_officer"],
            sub_agents={"damage_control_officer": sub_agent},
            comm_stats={
                "posts_total": 5,
                "endorsements_given": 1,
                "endorsements_received": 2,
                "credibility_score": 0.6,
            },
        )

        context = await loop._gather_context(agent, 0.5)

        assert "subordinate_stats" in context
        assert "Forge" in context["subordinate_stats"]
        stats = context["subordinate_stats"]["Forge"]
        assert stats["posts_total"] == 5

    @pytest.mark.asyncio
    async def test_non_chief_no_subordinate_stats(self):
        """Regular crew agents do not receive subordinate_stats."""
        agent = MagicMock()
        agent.agent_type = "science_analyst"
        agent.id = "analyst-id"

        loop, rt = self._make_loop_and_rt(subordinate_types=[])

        context = await loop._gather_context(agent, 0.5)

        assert "subordinate_stats" not in context

    @pytest.mark.asyncio
    async def test_minimum_post_threshold(self):
        """Subordinates with < 3 posts are excluded from stats."""
        agent = MagicMock()
        agent.agent_type = "engineering_officer"
        agent.id = "chief-id"

        sub_agent = MagicMock()
        sub_agent.id = "sub-id"
        sub_agent.sovereign_id = "sub-sov"
        sub_agent.callsign = "Forge"

        loop, rt = self._make_loop_and_rt(
            subordinate_types=["damage_control_officer"],
            sub_agents={"damage_control_officer": sub_agent},
            comm_stats={
                "posts_total": 2,  # Below threshold
                "endorsements_given": 0,
                "endorsements_received": 0,
                "credibility_score": 0.5,
            },
        )

        context = await loop._gather_context(agent, 0.5)

        assert "subordinate_stats" not in context


# ---------------------------------------------------------------------------
# 6. TestSubordinateRendering
# ---------------------------------------------------------------------------

class TestSubordinateRendering:
    """Tests for <subordinate_activity> XML rendering in _build_user_message()."""

    def _make_agent(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = MagicMock(spec=CognitiveAgent)
        agent.callsign = "LaForge"
        agent.agent_type = "engineering_officer"
        agent._augmentation_skills_used = []
        agent._runtime = None
        agent._working_memory = None
        agent._build_temporal_context = MagicMock(return_value="")
        return agent

    @pytest.mark.asyncio
    async def test_subordinate_stats_xml_tags(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = self._make_agent()
        observation = {
            "intent": "proactive_think",
            "params": {
                "context_parts": {
                    "subordinate_stats": {
                        "Forge": {
                            "posts_total": 5,
                            "endorsements_given": 1,
                            "endorsements_received": 2,
                            "credibility_score": 0.65,
                        },
                    },
                },
                "trust_score": 0.8,
                "agency_level": "suggestive",
            },
        }
        result = await CognitiveAgent._build_user_message(agent, observation)
        assert "<subordinate_activity>" in result
        assert "</subordinate_activity>" in result

    @pytest.mark.asyncio
    async def test_subordinate_stats_shows_metrics(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = self._make_agent()
        observation = {
            "intent": "proactive_think",
            "params": {
                "context_parts": {
                    "subordinate_stats": {
                        "Forge": {
                            "posts_total": 5,
                            "endorsements_given": 1,
                            "endorsements_received": 2,
                            "credibility_score": 0.65,
                        },
                    },
                },
                "trust_score": 0.8,
                "agency_level": "suggestive",
            },
        }
        result = await CognitiveAgent._build_user_message(agent, observation)
        assert "5 posts" in result
        assert "1 endorsements given" in result
        assert "2 endorsements received" in result
        assert "0.65" in result

    @pytest.mark.asyncio
    async def test_no_subordinate_stats_no_tags(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = self._make_agent()
        observation = {
            "intent": "proactive_think",
            "params": {
                "context_parts": {},
                "trust_score": 0.8,
                "agency_level": "suggestive",
            },
        }
        result = await CognitiveAgent._build_user_message(agent, observation)
        assert "<subordinate_activity>" not in result


# ---------------------------------------------------------------------------
# 7. TestSkillContent
# ---------------------------------------------------------------------------

class TestSkillContent:
    """Tests for leadership-feedback SKILL.md."""

    _SKILL_PATH = Path(__file__).resolve().parent.parent / "config" / "skills" / "leadership-feedback" / "SKILL.md"

    def test_skill_loads_for_chief_rank(self):
        from probos.cognitive.skill_catalog import parse_skill_file
        entry = parse_skill_file(self._SKILL_PATH)
        assert entry is not None
        assert entry.min_rank == "lieutenant_commander"

    def test_skill_not_loaded_for_ensign(self):
        """Ensign rank is below lieutenant_commander -- skill should be filtered."""
        from probos.cognitive.skill_catalog import parse_skill_file
        entry = parse_skill_file(self._SKILL_PATH)
        rank_order = ["ensign", "lieutenant_junior", "lieutenant", "lieutenant_commander", "commander", "captain"]
        min_rank = entry.min_rank
        min_idx = rank_order.index(min_rank) if min_rank in rank_order else 0
        ensign_idx = rank_order.index("ensign")
        assert ensign_idx < min_idx, "Ensign should be below lieutenant_commander"

    def test_skill_validates(self):
        """SKILL.md passes basic structural validation."""
        from probos.cognitive.skill_catalog import parse_skill_file
        entry = parse_skill_file(self._SKILL_PATH)
        assert entry is not None
        assert entry.name == "leadership-feedback"
        assert entry.activation == "augmentation"
        assert "proactive_think" in entry.intents

    def test_skill_has_proficiency_progression(self):
        content = self._SKILL_PATH.read_text(encoding="utf-8")
        for level in ["FOLLOW", "ASSIST", "APPLY", "ENABLE", "ADVISE", "LEAD", "SHAPE"]:
            assert level in content, f"Missing proficiency level: {level}"


# ---------------------------------------------------------------------------
# 8. TestFederationUpdate
# ---------------------------------------------------------------------------

class TestFederationUpdate:
    """Tests for federation.md Leadership and Mentorship section."""

    _FED_PATH = Path(__file__).resolve().parent.parent / "config" / "standing_orders" / "federation.md"

    def test_federation_has_leadership_section(self):
        content = self._FED_PATH.read_text(encoding="utf-8")
        assert "### Leadership and Mentorship" in content

    def test_federation_leadership_mentions_dm(self):
        content = self._FED_PATH.read_text(encoding="utf-8")
        # Find the Leadership section and check it mentions DM
        idx = content.index("### Leadership and Mentorship")
        section = content[idx:idx + 800]
        assert "DM" in section
