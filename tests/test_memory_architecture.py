"""Tests for Memory Architecture Extensions (AD-462c/d/e)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.config import SystemConfig, MemoryConfig
from probos.crew_profile import Rank
from probos.earned_agency import RecallTier, recall_tier_from_rank
from probos.cognitive.episodic import resolve_recall_tier_params


# ===========================================================================
# Phase 1: AD-462c — Variable Recall Tiers
# ===========================================================================


class TestRecallTiers:
    """Test RecallTier enum and rank-to-tier mapping."""

    def test_recall_tier_from_rank_ensign(self):
        assert recall_tier_from_rank(Rank.ENSIGN) == RecallTier.BASIC

    def test_recall_tier_from_rank_lieutenant(self):
        assert recall_tier_from_rank(Rank.LIEUTENANT) == RecallTier.ENHANCED

    def test_recall_tier_from_rank_commander(self):
        assert recall_tier_from_rank(Rank.COMMANDER) == RecallTier.FULL

    def test_recall_tier_from_rank_senior(self):
        assert recall_tier_from_rank(Rank.SENIOR) == RecallTier.ORACLE

    def test_resolve_recall_tier_params_basic(self):
        params = resolve_recall_tier_params("basic")
        assert params["k"] == 3
        assert params["context_budget"] == 1500
        assert params["use_salience_weights"] is False
        assert params["cross_department_anchors"] is False

    def test_resolve_recall_tier_params_oracle(self):
        params = resolve_recall_tier_params("oracle")
        assert params["k"] == 10
        assert params["context_budget"] == 8000
        assert params["use_salience_weights"] is True
        assert params["cross_department_anchors"] is True

    def test_resolve_recall_tier_params_unknown_falls_back(self):
        params = resolve_recall_tier_params("nonexistent_tier")
        # Should fall back to enhanced defaults
        assert params["k"] == 5
        assert params["context_budget"] == 4000
        assert params["use_salience_weights"] is True

    def test_resolve_recall_tier_params_custom_config(self):
        custom = {
            "basic": {"k": 1, "context_budget": 500, "use_salience_weights": False,
                      "cross_department_anchors": False, "anchor_confidence_gate": 0.0},
            "enhanced": {"k": 3, "context_budget": 2000, "use_salience_weights": True,
                         "cross_department_anchors": False, "anchor_confidence_gate": 0.5},
        }
        params = resolve_recall_tier_params("basic", custom)
        assert params["k"] == 1
        assert params["context_budget"] == 500

    def test_recall_tiers_on_memory_config(self):
        cfg = SystemConfig()
        tiers = cfg.memory.recall_tiers
        assert "basic" in tiers
        assert "enhanced" in tiers
        assert "full" in tiers
        assert "oracle" in tiers
        assert tiers["basic"]["k"] == 3
        assert tiers["oracle"]["k"] == 10


# ===========================================================================
# Phase 2: AD-462e — Oracle Service
# ===========================================================================

from probos.cognitive.oracle_service import OracleService, OracleResult


@pytest.fixture
def mock_episodic():
    em = AsyncMock()
    ep = MagicMock(
        id="ep1", user_input="test memory about trust", timestamp=time.time() - 3600,
        agent_ids=["agent-001"], source="direct",
    )
    em.recall_weighted = AsyncMock(return_value=[
        MagicMock(episode=ep, composite_score=0.85),
    ])
    em.recall = AsyncMock(return_value=[ep])
    return em


@pytest.fixture
def mock_records():
    rs = AsyncMock()
    rs.search = AsyncMock(return_value=[
        {"snippet": "Trust threshold discussion", "score": 7, "path": "notebooks/Lynx/trust.md",
         "frontmatter": {"author": "Lynx"}},
    ])
    return rs


@pytest.fixture
def mock_knowledge():
    ks = AsyncMock()
    ep = MagicMock(user_input="trust calibration data", reflection="important finding", timestamp=time.time() - 7200)
    ks.load_episodes = AsyncMock(return_value=[ep])
    return ks


class TestOracleService:
    """Test OracleService cross-tier query aggregation."""

    @pytest.mark.asyncio
    async def test_oracle_query_episodic_only(self, mock_episodic):
        oracle = OracleService(episodic_memory=mock_episodic)
        results = await oracle.query("trust", agent_id="agent-001", tiers=["episodic"])
        assert len(results) == 1
        assert results[0].source_tier == "episodic"
        assert results[0].score == 0.85
        mock_episodic.recall_weighted.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_oracle_query_records_only(self, mock_records):
        oracle = OracleService(records_store=mock_records)
        results = await oracle.query("trust", tiers=["records"])
        assert len(results) == 1
        assert results[0].source_tier == "records"
        assert results[0].provenance == "[ship's records]"
        mock_records.search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_oracle_query_all_tiers(self, mock_episodic, mock_records, mock_knowledge):
        oracle = OracleService(
            episodic_memory=mock_episodic,
            records_store=mock_records,
            knowledge_store=mock_knowledge,
        )
        results = await oracle.query("trust", agent_id="agent-001")
        assert len(results) >= 2  # At least episodic + records
        tiers_found = {r.source_tier for r in results}
        assert "episodic" in tiers_found
        assert "records" in tiers_found

    @pytest.mark.asyncio
    async def test_oracle_query_tier_filter(self, mock_episodic, mock_records):
        oracle = OracleService(episodic_memory=mock_episodic, records_store=mock_records)
        results = await oracle.query("trust", tiers=["records"])
        assert all(r.source_tier == "records" for r in results)
        mock_episodic.recall_weighted.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_oracle_query_empty_query(self, mock_episodic):
        oracle = OracleService(episodic_memory=mock_episodic)
        results = await oracle.query("")
        assert results == []

    @pytest.mark.asyncio
    async def test_oracle_query_tier_failure_graceful(self, mock_records):
        bad_episodic = AsyncMock()
        bad_episodic.recall_weighted = AsyncMock(side_effect=RuntimeError("boom"))
        oracle = OracleService(episodic_memory=bad_episodic, records_store=mock_records)
        results = await oracle.query("trust", agent_id="a1")
        # Records should still return results despite episodic failure
        assert len(results) >= 1
        assert results[0].source_tier == "records"

    @pytest.mark.asyncio
    async def test_oracle_result_provenance_tags(self, mock_episodic, mock_records):
        oracle = OracleService(episodic_memory=mock_episodic, records_store=mock_records)
        results = await oracle.query("trust", agent_id="a1")
        provenance_set = {r.provenance for r in results}
        assert "[episodic memory]" in provenance_set
        assert "[ship's records]" in provenance_set

    @pytest.mark.asyncio
    async def test_oracle_query_formatted_budget(self, mock_episodic):
        oracle = OracleService(episodic_memory=mock_episodic)
        formatted = await oracle.query_formatted("trust", agent_id="a1", max_chars=100)
        assert len(formatted) <= 200  # header + footer + some content

    @pytest.mark.asyncio
    async def test_oracle_query_formatted_content(self, mock_episodic):
        oracle = OracleService(episodic_memory=mock_episodic)
        formatted = await oracle.query_formatted("trust", agent_id="a1")
        assert "=== ORACLE QUERY RESULTS ===" in formatted
        assert "=== END ORACLE RESULTS ===" in formatted

    @pytest.mark.asyncio
    async def test_oracle_no_stores(self):
        oracle = OracleService()
        results = await oracle.query("trust")
        assert results == []


# ===========================================================================
# Phase 3: AD-462d — Social Memory
# ===========================================================================

from probos.cognitive.social_memory import SocialMemoryService


@pytest.fixture
def mock_ward_room():
    wr = AsyncMock()
    thread = MagicMock(id="thread-001")
    wr.create_thread = AsyncMock(return_value=thread)
    wr.browse_threads = AsyncMock(return_value=[
        MagicMock(
            id="thread-001", author_id="agent-requester",
            title="[Memory Query] trust thresholds",
            body="Does anyone remember: trust thresholds",
            thread_mode="memory_query",
        ),
    ])
    wr.get_thread = AsyncMock(return_value={
        "thread": {"author_id": "agent-requester"},
        "posts": [
            {"author_id": "agent-requester", "body": "Does anyone remember: trust thresholds", "created_at": time.time()},
        ],
    })
    wr.create_post = AsyncMock(return_value=MagicMock(id="post-001"))
    return wr


@pytest.fixture
def mock_em_for_social():
    em = AsyncMock()
    ep = MagicMock(
        user_input="Trust threshold calibration at 0.85 for commander promotion path analysis",
        source="ward_room",
        timestamp=time.time() - 1800,
    )
    em.recall_for_agent = AsyncMock(return_value=[ep])
    return em


class TestSocialMemory:
    """Test SocialMemoryService query/response protocol."""

    @pytest.mark.asyncio
    async def test_post_memory_query_creates_thread(self, mock_ward_room):
        svc = SocialMemoryService(ward_room=mock_ward_room)
        thread_id = await svc.post_memory_query(
            "agent-001", "Echo", "trust thresholds", department_channel_id="ch-science",
        )
        assert thread_id == "thread-001"
        mock_ward_room.create_thread.assert_awaited_once()
        call_kwargs = mock_ward_room.create_thread.call_args
        assert call_kwargs.kwargs.get("thread_mode") == "memory_query"

    @pytest.mark.asyncio
    async def test_post_memory_query_no_ward_room(self):
        svc = SocialMemoryService(ward_room=None)
        result = await svc.post_memory_query("agent-001", "Echo", "trust thresholds")
        assert result is None

    @pytest.mark.asyncio
    async def test_check_queries_finds_open_query(self, mock_ward_room, mock_em_for_social):
        svc = SocialMemoryService(ward_room=mock_ward_room, episodic_memory=mock_em_for_social)
        results = await svc.check_and_respond_to_queries(
            agent_id="agent-responder", agent_callsign="Lynx",
        )
        assert len(results) == 1
        assert results[0]["responded"] is True
        mock_ward_room.create_post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_queries_skips_own_query(self, mock_ward_room, mock_em_for_social):
        svc = SocialMemoryService(ward_room=mock_ward_room, episodic_memory=mock_em_for_social)
        results = await svc.check_and_respond_to_queries(
            agent_id="agent-requester", agent_callsign="Echo",
        )
        assert len(results) == 1
        assert results[0]["responded"] is False
        mock_ward_room.create_post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_check_queries_skips_already_responded(self, mock_ward_room, mock_em_for_social):
        # Add a post from agent-responder in the thread data
        mock_ward_room.get_thread = AsyncMock(return_value={
            "thread": {"author_id": "agent-requester"},
            "posts": [
                {"author_id": "agent-requester", "body": "Does anyone remember: trust thresholds", "created_at": time.time()},
                {"author_id": "agent-responder", "body": "I recall: ...", "created_at": time.time()},
            ],
        })
        svc = SocialMemoryService(ward_room=mock_ward_room, episodic_memory=mock_em_for_social)
        results = await svc.check_and_respond_to_queries(
            agent_id="agent-responder", agent_callsign="Lynx",
        )
        assert len(results) == 1
        assert results[0]["responded"] is False
        mock_ward_room.create_post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_check_queries_skips_no_relevant_memory(self, mock_ward_room):
        em = AsyncMock()
        em.recall_for_agent = AsyncMock(return_value=[])
        svc = SocialMemoryService(ward_room=mock_ward_room, episodic_memory=em)
        results = await svc.check_and_respond_to_queries(
            agent_id="agent-responder", agent_callsign="Lynx",
        )
        assert len(results) == 1
        assert results[0]["responded"] is False
        mock_ward_room.create_post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_check_queries_responds_with_memory_content(self, mock_ward_room, mock_em_for_social):
        svc = SocialMemoryService(ward_room=mock_ward_room, episodic_memory=mock_em_for_social)
        await svc.check_and_respond_to_queries(
            agent_id="agent-responder", agent_callsign="Lynx",
        )
        post_call = mock_ward_room.create_post.call_args
        body = post_call.kwargs.get("body", "")
        assert "I recall:" in body
        assert "Trust threshold" in body

    @pytest.mark.asyncio
    async def test_get_query_responses_returns_replies(self, mock_ward_room):
        mock_ward_room.get_thread = AsyncMock(return_value={
            "thread": {"author_id": "agent-requester"},
            "posts": [
                {"author_id": "agent-requester", "body": "query", "created_at": time.time()},
                {"author_id": "agent-responder", "body": "I recall: something", "created_at": time.time()},
            ],
        })
        svc = SocialMemoryService(ward_room=mock_ward_room)
        responses = await svc.get_query_responses("thread-001")
        assert len(responses) == 1
        assert responses[0]["responder_id"] == "agent-responder"
        assert "I recall:" in responses[0]["content"]

    @pytest.mark.asyncio
    async def test_get_query_responses_excludes_original_post(self, mock_ward_room):
        mock_ward_room.get_thread = AsyncMock(return_value={
            "thread": {"author_id": "agent-requester"},
            "posts": [
                {"author_id": "agent-requester", "body": "query", "created_at": time.time()},
                {"author_id": "agent-responder-1", "body": "response 1", "created_at": time.time()},
                {"author_id": "agent-responder-2", "body": "response 2", "created_at": time.time()},
            ],
        })
        svc = SocialMemoryService(ward_room=mock_ward_room)
        responses = await svc.get_query_responses("thread-001")
        assert len(responses) == 2
        assert all(r["responder_id"] != "agent-requester" for r in responses)

    @pytest.mark.asyncio
    async def test_social_memory_no_episodic_memory(self, mock_ward_room):
        svc = SocialMemoryService(ward_room=mock_ward_room, episodic_memory=None)
        results = await svc.check_and_respond_to_queries(
            agent_id="agent-responder", agent_callsign="Lynx",
        )
        assert results == []
