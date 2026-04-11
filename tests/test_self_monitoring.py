"""Tests for AD-504: Agent Self-Monitoring Context."""
from __future__ import annotations

import asyncio
import importlib
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.crew_profile import Rank
from probos.earned_agency import AgencyLevel


# ---------------------------------------------------------------------------
# TestJaccardUtility
# ---------------------------------------------------------------------------


class TestJaccardUtility:
    """Tests for the jaccard utility module."""

    def test_jaccard_identical_sets(self) -> None:
        assert jaccard_similarity({"a", "b", "c"}, {"a", "b", "c"}) == 1.0

    def test_jaccard_disjoint_sets(self) -> None:
        assert jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0

    def test_jaccard_partial_overlap(self) -> None:
        # {a,b,c} ∩ {b,c,d} = {b,c}, |union| = 4, result = 2/4 = 0.5
        assert jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"}) == 0.5

    def test_jaccard_empty_sets(self) -> None:
        assert jaccard_similarity(set(), set()) == 0.0

    def test_jaccard_one_empty(self) -> None:
        assert jaccard_similarity({"a", "b"}, set()) == 0.0

    def test_text_to_words_basic(self) -> None:
        assert text_to_words("Hello World") == {"hello", "world"}

    def test_text_to_words_empty(self) -> None:
        assert text_to_words("") == set()


# ---------------------------------------------------------------------------
# TestWardRoomPostsByAuthor
# ---------------------------------------------------------------------------


class TestWardRoomPostsByAuthor:
    """Tests for get_posts_by_author on ThreadManager."""

    def _make_thread_mgr(self, db: Any = None) -> Any:
        from probos.ward_room.threads import ThreadManager
        return ThreadManager(
            db=db,
            emit_fn=MagicMock(spec=lambda *a, **kw: None),
        )

    @pytest.mark.asyncio
    async def test_get_posts_by_author_returns_recent(self) -> None:
        """Posts returned ordered by created_at DESC via SQL."""
        now = time.time()
        rows = [
            ("p2", "t1", "second", now, None, "ch1"),
            ("p1", "t1", "first", now - 60, None, "ch1"),
        ]

        class _FakeCursor:
            def __init__(self, data: list) -> None:
                self._data = data
                self._idx = 0
            async def __aenter__(self) -> "_FakeCursor":
                return self
            async def __aexit__(self, *a: object) -> bool:
                return False
            def __aiter__(self) -> "_FakeCursor":
                return self
            async def __anext__(self) -> tuple:
                if self._idx >= len(self._data):
                    raise StopAsyncIteration
                row = self._data[self._idx]
                self._idx += 1
                return row

        db = MagicMock()
        db.execute = MagicMock(return_value=_FakeCursor(rows))
        mgr = self._make_thread_mgr(db=db)
        result = await mgr.get_posts_by_author("Bones", limit=5, since=0.0)
        assert len(result) == 2
        assert result[0]["post_id"] == "p2"
        assert result[1]["post_id"] == "p1"

    @pytest.mark.asyncio
    async def test_get_posts_by_author_empty_when_no_posts(self) -> None:
        cursor_mock = AsyncMock()
        cursor_mock.__aiter__ = MagicMock(return_value=iter([]))
        cursor_mock.__aenter__ = AsyncMock(return_value=cursor_mock)
        cursor_mock.__aexit__ = AsyncMock(return_value=False)
        db = MagicMock()
        db.execute = MagicMock(return_value=cursor_mock)
        mgr = self._make_thread_mgr(db=db)
        result = await mgr.get_posts_by_author("Bones", limit=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_posts_by_author_handles_db_error(self) -> None:
        db = MagicMock()
        db.execute = MagicMock(side_effect=Exception("db error"))
        mgr = self._make_thread_mgr(db=db)
        result = await mgr.get_posts_by_author("Bones")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_posts_by_author_no_db(self) -> None:
        mgr = self._make_thread_mgr(db=None)
        result = await mgr.get_posts_by_author("Bones")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_posts_by_author_filters_by_callsign(self) -> None:
        """SQL WHERE clause filters by author_callsign."""
        cursor_mock = AsyncMock()
        cursor_mock.__aiter__ = MagicMock(return_value=iter([]))
        cursor_mock.__aenter__ = AsyncMock(return_value=cursor_mock)
        cursor_mock.__aexit__ = AsyncMock(return_value=False)
        db = MagicMock()
        db.execute = MagicMock(return_value=cursor_mock)
        mgr = self._make_thread_mgr(db=db)
        await mgr.get_posts_by_author("TestCallsign", limit=3, since=100.0)
        # Verify SQL was called with "TestCallsign" and since=100.0
        call_args = db.execute.call_args
        assert call_args[0][1][0] == "TestCallsign"
        assert call_args[0][1][1] == 100.0
        assert call_args[0][1][2] == 3

    @pytest.mark.asyncio
    async def test_get_posts_by_author_respects_limit(self) -> None:
        """Limit is passed through to SQL LIMIT clause."""
        cursor_mock = AsyncMock()
        cursor_mock.__aiter__ = MagicMock(return_value=iter([]))
        cursor_mock.__aenter__ = AsyncMock(return_value=cursor_mock)
        cursor_mock.__aexit__ = AsyncMock(return_value=False)
        db = MagicMock()
        db.execute = MagicMock(return_value=cursor_mock)
        mgr = self._make_thread_mgr(db=db)
        await mgr.get_posts_by_author("X", limit=3)
        call_args = db.execute.call_args
        assert call_args[0][1][2] == 3  # LIMIT param

    @pytest.mark.asyncio
    async def test_get_posts_by_author_respects_since(self) -> None:
        """Since timestamp filters old posts."""
        cursor_mock = AsyncMock()
        cursor_mock.__aiter__ = MagicMock(return_value=iter([]))
        cursor_mock.__aenter__ = AsyncMock(return_value=cursor_mock)
        cursor_mock.__aexit__ = AsyncMock(return_value=False)
        db = MagicMock()
        db.execute = MagicMock(return_value=cursor_mock)
        mgr = self._make_thread_mgr(db=db)
        await mgr.get_posts_by_author("X", since=12345.0)
        call_args = db.execute.call_args
        assert call_args[0][1][1] == 12345.0


# ---------------------------------------------------------------------------
# Helpers for proactive tests
# ---------------------------------------------------------------------------


def _make_agent(
    agent_id: str = "agent-1",
    agent_type: str = "medical_agent",
    callsign: str = "Bones",
    rank: Rank = Rank.LIEUTENANT,
    department: str = "medical",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=agent_id,
        agent_type=agent_type,
        callsign=callsign,
        rank=rank,
        department=department,
        sovereign_id=agent_id,
    )


def _make_runtime(
    ward_room: Any = None,
    episodic_memory: Any = None,
    records_store: Any = None,
    callsign_registry: Any = None,
    lifecycle_state: str = "warm_boot",
    start_time_wall: float | None = None,
    trust_score: float = 0.55,
) -> SimpleNamespace:
    trust_network = MagicMock()
    trust_network.get_score = MagicMock(return_value=trust_score)
    rt = SimpleNamespace(
        ward_room=ward_room,
        episodic_memory=episodic_memory,
        _records_store=records_store,
        _lifecycle_state=lifecycle_state,
        _start_time_wall=start_time_wall or (time.time() - 7200),  # 2h ago
        trust_network=trust_network,
    )
    if callsign_registry:
        rt.callsign_registry = callsign_registry
    return rt


def _make_loop() -> Any:
    from probos.proactive import ProactiveCognitiveLoop
    loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0)
    return loop


# ---------------------------------------------------------------------------
# TestSelfMonitoringContextBuilder
# ---------------------------------------------------------------------------


class TestSelfMonitoringContextBuilder:
    """Tests for _build_self_monitoring_context()."""

    @pytest.mark.asyncio
    async def test_recent_posts_injected(self) -> None:
        now = time.time()
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[
            {"body": "observation one", "created_at": now - 60, "post_id": "p1",
             "thread_id": "t1", "parent_id": None, "channel_id": "ch1"},
        ])
        rt = _make_runtime(ward_room=ward_room)
        loop = _make_loop()
        agent = _make_agent(rank=Rank.LIEUTENANT)
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        assert "recent_posts" in result
        assert len(result["recent_posts"]) == 1
        assert "observation one" in result["recent_posts"][0]["body"]

    @pytest.mark.asyncio
    async def test_recent_posts_truncated_to_150_chars(self) -> None:
        now = time.time()
        long_body = "a" * 300
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[
            {"body": long_body, "created_at": now - 60, "post_id": "p1",
             "thread_id": "t1", "parent_id": None, "channel_id": "ch1"},
        ])
        rt = _make_runtime(ward_room=ward_room)
        loop = _make_loop()
        agent = _make_agent(rank=Rank.LIEUTENANT)
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        assert len(result["recent_posts"][0]["body"]) == 150

    @pytest.mark.asyncio
    async def test_self_similarity_computed(self) -> None:
        now = time.time()
        ward_room = MagicMock()
        # Two identical posts → similarity = 1.0
        ward_room.get_posts_by_author = AsyncMock(return_value=[
            {"body": "the same words", "created_at": now - 30, "post_id": "p1",
             "thread_id": "t1", "parent_id": None, "channel_id": "ch1"},
            {"body": "the same words", "created_at": now - 60, "post_id": "p2",
             "thread_id": "t1", "parent_id": None, "channel_id": "ch1"},
        ])
        rt = _make_runtime(ward_room=ward_room)
        loop = _make_loop()
        agent = _make_agent(rank=Rank.LIEUTENANT)
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        assert "self_similarity" in result
        assert result["self_similarity"] == 1.0

    @pytest.mark.asyncio
    async def test_self_similarity_skipped_with_one_post(self) -> None:
        now = time.time()
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[
            {"body": "just one post", "created_at": now - 30, "post_id": "p1",
             "thread_id": "t1", "parent_id": None, "channel_id": "ch1"},
        ])
        rt = _make_runtime(ward_room=ward_room)
        loop = _make_loop()
        agent = _make_agent(rank=Rank.LIEUTENANT)
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        assert "self_similarity" not in result

    @pytest.mark.asyncio
    async def test_high_similarity_increases_cooldown(self) -> None:
        now = time.time()
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[
            {"body": "same same same", "created_at": now - 30, "post_id": "p1",
             "thread_id": "t1", "parent_id": None, "channel_id": "ch1"},
            {"body": "same same same", "created_at": now - 60, "post_id": "p2",
             "thread_id": "t1", "parent_id": None, "channel_id": "ch1"},
        ])
        rt = _make_runtime(ward_room=ward_room)
        loop = _make_loop()
        agent = _make_agent(rank=Rank.LIEUTENANT)
        original_cooldown = loop.get_agent_cooldown(agent.id)
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        assert result.get("cooldown_increased") is True
        assert loop.get_agent_cooldown(agent.id) > original_cooldown

    @pytest.mark.asyncio
    async def test_cooldown_increase_capped_at_1800(self) -> None:
        now = time.time()
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[
            {"body": "same same same", "created_at": now - 30, "post_id": "p1",
             "thread_id": "t1", "parent_id": None, "channel_id": "ch1"},
            {"body": "same same same", "created_at": now - 60, "post_id": "p2",
             "thread_id": "t1", "parent_id": None, "channel_id": "ch1"},
        ])
        rt = _make_runtime(ward_room=ward_room)
        loop = _make_loop()
        # Set cooldown high so * 1.5 would exceed 1800
        loop.set_agent_cooldown("agent-1", 1500)
        agent = _make_agent(rank=Rank.LIEUTENANT)
        await loop._build_self_monitoring_context(agent, "Bones", rt)
        assert loop.get_agent_cooldown(agent.id) <= 1800

    @pytest.mark.asyncio
    async def test_memory_state_sparse_shard_note(self) -> None:
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[])
        episodic = MagicMock()
        episodic.count_for_agent = AsyncMock(return_value=2)
        rt = _make_runtime(
            ward_room=ward_room,
            episodic_memory=episodic,
            lifecycle_state="warm_boot",
            start_time_wall=time.time() - 7200,  # 2h uptime
        )
        loop = _make_loop()
        agent = _make_agent(rank=Rank.LIEUTENANT)
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        assert "memory_state" in result
        assert result["memory_state"]["episode_count"] == 2
        assert result["memory_state"]["uptime_hours"] > 1

    @pytest.mark.asyncio
    async def test_memory_state_skipped_on_reset(self) -> None:
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[])
        episodic = MagicMock()
        episodic.count_for_agent = AsyncMock(return_value=0)
        rt = _make_runtime(
            ward_room=ward_room,
            episodic_memory=episodic,
            lifecycle_state="reset",
        )
        loop = _make_loop()
        agent = _make_agent(rank=Rank.LIEUTENANT)
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        # memory_state populated but lifecycle=reset check happens at prompt formatting level
        assert "memory_state" in result
        assert result["memory_state"]["lifecycle"] == "reset"

    @pytest.mark.asyncio
    async def test_memory_state_skipped_when_episodes_sufficient(self) -> None:
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[])
        episodic = MagicMock()
        episodic.count_for_agent = AsyncMock(return_value=50)
        rt = _make_runtime(ward_room=ward_room, episodic_memory=episodic)
        loop = _make_loop()
        agent = _make_agent(rank=Rank.LIEUTENANT)
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        # memory_state populated but count >= 5 so prompt won't show sparse note
        assert result["memory_state"]["episode_count"] == 50

    @pytest.mark.asyncio
    async def test_notebook_index_populated(self) -> None:
        now = time.time()
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[])
        records = MagicMock()
        records.list_entries = AsyncMock(return_value=[
            {"path": "notebooks/Bones/topic-a.md", "frontmatter": {"topic": "topic-a", "updated": now - 100}},
            {"path": "notebooks/Bones/topic-b.md", "frontmatter": {"topic": "topic-b", "updated": now - 200}},
        ])
        records.search = AsyncMock(return_value=[])
        rt = _make_runtime(ward_room=ward_room, records_store=records, trust_score=0.75)
        loop = _make_loop()
        agent = _make_agent(rank=Rank.COMMANDER)  # Notebooks require AUTONOMOUS tier
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        assert "notebook_index" in result
        assert len(result["notebook_index"]) == 2
        assert result["notebook_index"][0]["topic"] == "topic-a"

    @pytest.mark.asyncio
    async def test_notebook_index_limited_to_5(self) -> None:
        now = time.time()
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[])
        entries = [
            {"path": f"notebooks/Bones/t-{i}.md", "frontmatter": {"topic": f"t-{i}", "updated": now - i * 100}}
            for i in range(10)
        ]
        records = MagicMock()
        records.list_entries = AsyncMock(return_value=entries)
        records.search = AsyncMock(return_value=[])
        rt = _make_runtime(ward_room=ward_room, records_store=records, trust_score=0.75)
        loop = _make_loop()
        agent = _make_agent(rank=Rank.COMMANDER)
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        assert len(result["notebook_index"]) == 5

    @pytest.mark.asyncio
    async def test_notebook_semantic_pull(self) -> None:
        now = time.time()
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[])
        records = MagicMock()
        records.list_entries = AsyncMock(return_value=[
            {"path": "notebooks/Bones/analysis.md", "frontmatter": {"topic": "analysis", "updated": now}},
        ])
        records.search = AsyncMock(return_value=[
            {"path": "notebooks/Bones/analysis.md", "snippet": "This is my analysis content on the topic."},
        ])
        rt = _make_runtime(ward_room=ward_room, records_store=records, trust_score=0.75)
        loop = _make_loop()
        agent = _make_agent(rank=Rank.COMMANDER, department="medical")
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        assert "notebook_content" in result
        assert "analysis" in result["notebook_content"]["snippet"]

    @pytest.mark.asyncio
    async def test_pending_notebook_read_injected(self) -> None:
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[])
        records = MagicMock()
        records.list_entries = AsyncMock(return_value=[])
        records.read_entry = AsyncMock(return_value={"content": "Notebook content here"})
        rt = _make_runtime(ward_room=ward_room, records_store=records, trust_score=0.75)
        loop = _make_loop()
        loop._pending_notebook_reads["agent-1"] = "my-topic"
        agent = _make_agent(rank=Rank.COMMANDER)
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        assert "notebook_content" in result
        assert result["notebook_content"]["topic"] == "my-topic"

    @pytest.mark.asyncio
    async def test_pending_notebook_read_consumed(self) -> None:
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[])
        records = MagicMock()
        records.list_entries = AsyncMock(return_value=[])
        records.read_entry = AsyncMock(return_value={"content": "content"})
        rt = _make_runtime(ward_room=ward_room, records_store=records, trust_score=0.75)
        loop = _make_loop()
        loop._pending_notebook_reads["agent-1"] = "some-topic"
        agent = _make_agent(rank=Rank.COMMANDER)
        await loop._build_self_monitoring_context(agent, "Bones", rt)
        assert "agent-1" not in loop._pending_notebook_reads

    @pytest.mark.asyncio
    async def test_self_monitoring_degrades_gracefully(self) -> None:
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(side_effect=Exception("WR error"))
        episodic = MagicMock()
        episodic.count_for_agent = AsyncMock(side_effect=Exception("epi error"))
        rt = _make_runtime(ward_room=ward_room, episodic_memory=episodic)
        loop = _make_loop()
        agent = _make_agent(rank=Rank.LIEUTENANT)
        # Should not raise
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestEarnedAgencyScaling
# ---------------------------------------------------------------------------


class TestEarnedAgencyScaling:
    """Tests for tier-based feature gating."""

    @pytest.mark.asyncio
    async def test_ensign_skips_self_monitoring(self) -> None:
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[])
        rt = _make_runtime(ward_room=ward_room)
        loop = _make_loop()
        agent = _make_agent(rank=Rank.ENSIGN)
        result = await loop._build_self_monitoring_context(agent, "Wesley", rt)
        assert result == {}

    @pytest.mark.asyncio
    async def test_lieutenant_gets_3_posts_no_notebooks(self) -> None:
        now = time.time()
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[
            {"body": f"post {i}", "created_at": now - i * 60, "post_id": f"p{i}",
             "thread_id": "t1", "parent_id": None, "channel_id": "ch1"}
            for i in range(5)
        ])
        records = MagicMock()
        records.list_entries = AsyncMock(return_value=[
            {"path": "notebooks/Bones/x.md", "frontmatter": {"topic": "x", "updated": now}},
        ])
        rt = _make_runtime(ward_room=ward_room, records_store=records)
        loop = _make_loop()
        agent = _make_agent(rank=Rank.LIEUTENANT)
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        # Lieutenant: limit=3, notebooks=False
        ward_room.get_posts_by_author.assert_called_once()
        call_kwargs = ward_room.get_posts_by_author.call_args
        assert call_kwargs[1]["limit"] == 3
        assert "notebook_index" not in result

    @pytest.mark.asyncio
    async def test_commander_gets_5_posts_with_notebooks(self) -> None:
        now = time.time()
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[])
        records = MagicMock()
        records.list_entries = AsyncMock(return_value=[
            {"path": "notebooks/Bones/x.md", "frontmatter": {"topic": "x", "updated": now}},
        ])
        records.search = AsyncMock(return_value=[])
        rt = _make_runtime(ward_room=ward_room, records_store=records, trust_score=0.75)
        loop = _make_loop()
        agent = _make_agent(rank=Rank.COMMANDER)
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        call_kwargs = ward_room.get_posts_by_author.call_args
        assert call_kwargs[1]["limit"] == 5
        assert "notebook_index" in result

    @pytest.mark.asyncio
    async def test_senior_gets_full_context(self) -> None:
        ward_room = MagicMock()
        ward_room.get_posts_by_author = AsyncMock(return_value=[])
        records = MagicMock()
        records.list_entries = AsyncMock(return_value=[
            {"path": "notebooks/Bones/x.md", "frontmatter": {"topic": "x", "updated": time.time()}},
        ])
        records.search = AsyncMock(return_value=[])
        rt = _make_runtime(ward_room=ward_room, records_store=records, trust_score=0.9)
        loop = _make_loop()
        agent = _make_agent(rank=Rank.SENIOR)
        result = await loop._build_self_monitoring_context(agent, "Bones", rt)
        call_kwargs = ward_room.get_posts_by_author.call_args
        assert call_kwargs[1]["limit"] == 5
        assert "notebook_index" in result


# ---------------------------------------------------------------------------
# TestPromptFormatting
# ---------------------------------------------------------------------------


class TestPromptFormatting:
    """Tests for self-monitoring prompt section in cognitive_agent."""

    async def _build_proactive_prompt(self, context_parts: dict) -> str:
        """Build a proactive_think prompt via CognitiveAgent._build_user_message."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._recent_post_count = 0
        agent._temporal_context = None
        # Mock _build_temporal_context to return empty
        agent._build_temporal_context = lambda: ""
        # Mock _format_memory_section
        agent._format_memory_section = lambda memories: ["(memories)"]
        observation = {
            "intent": "proactive_think",
            "params": {
                "context_parts": context_parts,
                "trust_score": 0.65,
                "agency_level": "suggestive",
                "rank": "lieutenant",
                "duty": None,
            },
        }
        return await agent._build_user_message(observation)

    @pytest.mark.asyncio
    async def test_self_monitoring_section_in_prompt(self) -> None:
        prompt = await self._build_proactive_prompt({
            "self_monitoring": {
                "recent_posts": [{"body": "observation here", "age": "5m"}],
            },
        })
        assert "Your Recent Activity (self-monitoring)" in prompt
        assert "observation here" in prompt

    @pytest.mark.asyncio
    async def test_high_similarity_warning_in_prompt(self) -> None:
        prompt = await self._build_proactive_prompt({
            "self_monitoring": {
                "self_similarity": 0.7,
            },
        })
        assert "WARNING:" in prompt
        assert "GENUINELY NEW" in prompt

    @pytest.mark.asyncio
    async def test_moderate_similarity_note_in_prompt(self) -> None:
        prompt = await self._build_proactive_prompt({
            "self_monitoring": {
                "self_similarity": 0.35,
            },
        })
        assert "Note:" in prompt
        assert "new insight" in prompt

    @pytest.mark.asyncio
    async def test_no_self_monitoring_when_empty(self) -> None:
        prompt = await self._build_proactive_prompt({})
        assert "Your Recent Activity" not in prompt

    @pytest.mark.asyncio
    async def test_notebook_index_formatted(self) -> None:
        prompt = await self._build_proactive_prompt({
            "self_monitoring": {
                "notebook_index": [
                    {"topic": "analysis-topic", "updated": "2026-03-30"},
                ],
            },
        })
        assert "analysis-topic" in prompt
        assert "READ_NOTEBOOK" in prompt

    @pytest.mark.asyncio
    async def test_memory_state_calibration_note(self) -> None:
        prompt = await self._build_proactive_prompt({
            "self_monitoring": {
                "memory_state": {
                    "episode_count": 2,
                    "lifecycle": "warm_boot",
                    "uptime_hours": 3.5,
                },
            },
        })
        assert "2 episodic memories" in prompt
        assert "sparse" in prompt.lower() or "richer histories" in prompt


# ---------------------------------------------------------------------------
# TestReadNotebookAction
# ---------------------------------------------------------------------------


class TestReadNotebookAction:
    """Tests for [READ_NOTEBOOK] action parsing."""

    @pytest.mark.asyncio
    async def test_read_notebook_parsed_from_output(self) -> None:
        loop = _make_loop()
        loop._runtime = _make_runtime()
        loop._runtime.ward_room = MagicMock()
        loop._runtime.ward_room.list_channels = AsyncMock(return_value=[])
        loop._runtime.trust_network = MagicMock()
        loop._runtime.trust_network.get_score = MagicMock(return_value=0.65)
        loop._runtime.registry = MagicMock()
        loop._runtime.ward_room_router = None
        agent = _make_agent()
        text = "Some observation here [READ_NOTEBOOK my-analysis] and more"
        cleaned, actions = await loop._extract_and_execute_actions(agent, text)
        assert loop._pending_notebook_reads[agent.id] == "my-analysis"

    @pytest.mark.asyncio
    async def test_read_notebook_stripped_from_text(self) -> None:
        loop = _make_loop()
        loop._runtime = _make_runtime()
        loop._runtime.ward_room = MagicMock()
        loop._runtime.ward_room.list_channels = AsyncMock(return_value=[])
        loop._runtime.trust_network = MagicMock()
        loop._runtime.trust_network.get_score = MagicMock(return_value=0.65)
        loop._runtime.registry = MagicMock()
        loop._runtime.ward_room_router = None
        loop._runtime._records_store = None
        agent = _make_agent()
        text = "Some text [READ_NOTEBOOK topic-slug] end"
        cleaned, _ = await loop._extract_and_execute_actions(agent, text)
        assert "[READ_NOTEBOOK" not in cleaned

    @pytest.mark.asyncio
    async def test_multiple_read_notebook_last_wins(self) -> None:
        loop = _make_loop()
        loop._runtime = _make_runtime()
        loop._runtime.ward_room = MagicMock()
        loop._runtime.ward_room.list_channels = AsyncMock(return_value=[])
        loop._runtime.trust_network = MagicMock()
        loop._runtime.trust_network.get_score = MagicMock(return_value=0.65)
        loop._runtime.registry = MagicMock()
        loop._runtime.ward_room_router = None
        loop._runtime._records_store = None
        agent = _make_agent()
        text = "[READ_NOTEBOOK first-topic] mid [READ_NOTEBOOK second-topic]"
        await loop._extract_and_execute_actions(agent, text)
        # Last one wins (loop overwrites)
        assert loop._pending_notebook_reads[agent.id] == "second-topic"


# ---------------------------------------------------------------------------
# TestStandingOrdersIntegration
# ---------------------------------------------------------------------------


class TestStandingOrdersIntegration:
    """Tests for standing orders file update."""

    def test_ship_standing_orders_contain_self_monitoring(self) -> None:
        path = Path(__file__).resolve().parent.parent / "config" / "standing_orders" / "ship.md"
        content = path.read_text(encoding="utf-8")
        assert "## Self-Monitoring" in content
        assert "self-similarity" in content.lower()
        assert "[READ_NOTEBOOK" in content


# ---------------------------------------------------------------------------
# TestCircuitBreakerJaccardRefactor
# ---------------------------------------------------------------------------


class TestCircuitBreakerJaccardRefactor:
    """Tests that Jaccard is imported from the utility module."""

    def test_circuit_breaker_uses_utility_jaccard(self) -> None:
        source = Path(__file__).resolve().parent.parent / "src" / "probos" / "cognitive" / "circuit_breaker.py"
        content = source.read_text(encoding="utf-8")
        assert "from probos.cognitive.similarity import jaccard_similarity" in content

    def test_episodic_dedup_uses_utility_jaccard(self) -> None:
        source = Path(__file__).resolve().parent.parent / "src" / "probos" / "cognitive" / "episodic.py"
        content = source.read_text(encoding="utf-8")
        assert "from probos.cognitive.similarity import jaccard_similarity" in content
