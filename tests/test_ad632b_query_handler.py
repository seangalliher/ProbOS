"""Tests for AD-632b: Query Sub-Task Handler (Deterministic Data Retrieval).

41 tests across 10 test classes verifying QueryHandler protocol compliance,
query operation dispatch, error handling, and executor integration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.sub_task import (
    SubTaskChain,
    SubTaskExecutor,
    SubTaskHandler,
    SubTaskResult,
    SubTaskSpec,
    SubTaskType,
)
from probos.cognitive.sub_tasks.query import QueryHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class _MockCredibility:
    """Mimics WardRoomCredibility dataclass for testing asdict() conversion."""
    agent_id: str = "agent-1"
    total_posts: int = 10
    total_endorsements: int = 5
    credibility_score: float = 0.75
    restrictions: list = None

    def __post_init__(self):
        if self.restrictions is None:
            self.restrictions = []


def _make_runtime(
    *,
    ward_room: Any = "auto",
    trust_network: Any = "auto",
) -> MagicMock:
    """Create a mock runtime with configurable service availability."""
    rt = MagicMock()

    if ward_room == "auto":
        wr = AsyncMock()
        wr.get_thread = AsyncMock(return_value={
            "id": "t-1", "reply_count": 3, "contributors": ["a", "b"],
            "post_ids": ["p1", "p2", "p3"], "department": "science",
        })
        wr.get_recent_activity = AsyncMock(return_value=[
            {"id": "p1", "author": "atlas", "timestamp": 1.0, "type": "reply"},
        ])
        wr.get_agent_comm_stats = AsyncMock(return_value={
            "posts_total": 10, "endorsements_given": 3,
            "endorsements_received": 5, "credibility_score": 0.75,
        })
        wr.get_credibility = AsyncMock(return_value=_MockCredibility())
        wr.get_unread_counts = AsyncMock(return_value={"ch-sci": 2, "ch-eng": 0})
        wr.get_unread_dms = AsyncMock(return_value=[
            {"from": "lynx", "text": "Analysis ready", "timestamp": 100.0},
        ])
        wr.get_posts_by_author = AsyncMock(return_value=[
            {"id": "p1", "text": "hello", "timestamp": 1.0, "thread_id": "t-1"},
        ])
        rt.ward_room = wr
    elif ward_room is None:
        rt.ward_room = None
    else:
        rt.ward_room = ward_room

    if trust_network == "auto":
        tn = MagicMock()
        tn.get_score = MagicMock(return_value=0.82)
        tn.summary = MagicMock(return_value=[
            {"agent_id": "a1", "score": "0.82", "observations": 15.0},
        ])
        rt.trust_network = tn
    elif trust_network is None:
        rt.trust_network = None
    else:
        rt.trust_network = trust_network

    return rt


def _make_spec(
    *,
    context_keys: tuple[str, ...] = ("thread_metadata",),
    name: str = "query-test",
) -> SubTaskSpec:
    """Create a QUERY SubTaskSpec with the given context_keys."""
    return SubTaskSpec(
        sub_task_type=SubTaskType.QUERY,
        name=name,
        context_keys=context_keys,
    )


# ---------------------------------------------------------------------------
# 1. TestQueryHandlerProtocol
# ---------------------------------------------------------------------------


class TestQueryHandlerProtocol:
    """Verify QueryHandler satisfies SubTaskHandler protocol."""

    def test_implements_sub_task_handler(self):
        handler = QueryHandler(_make_runtime())
        assert isinstance(handler, SubTaskHandler)

    @pytest.mark.asyncio
    async def test_returns_sub_task_result(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("thread_metadata",))
        result = await handler(spec, {"thread_id": "t-1"}, [])
        assert isinstance(result, SubTaskResult)

    @pytest.mark.asyncio
    async def test_tokens_always_zero(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("thread_metadata", "comm_stats"))
        result = await handler(spec, {"thread_id": "t-1", "agent_id": "a1"}, [])
        assert result.tokens_used == 0

    @pytest.mark.asyncio
    async def test_tier_always_empty(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("trust_score",))
        result = await handler(spec, {"agent_id": "a1"}, [])
        assert result.tier_used == ""

    @pytest.mark.asyncio
    async def test_sub_task_type_is_query(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec()
        result = await handler(spec, {"thread_id": "t-1"}, [])
        assert result.sub_task_type == SubTaskType.QUERY


# ---------------------------------------------------------------------------
# 2. TestThreadMetadata
# ---------------------------------------------------------------------------


class TestThreadMetadata:
    """Test thread_metadata query operation."""

    @pytest.mark.asyncio
    async def test_thread_metadata_returns_structured_data(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("thread_metadata",))
        result = await handler(spec, {"thread_id": "t-1"}, [])
        assert result.success is True
        assert "thread_metadata" in result.result
        data = result.result["thread_metadata"]
        assert "reply_count" in data

    @pytest.mark.asyncio
    async def test_thread_metadata_missing_thread_id(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("thread_metadata",))
        result = await handler(spec, {}, [])
        assert result.success is False
        assert "thread_id required" in result.error

    @pytest.mark.asyncio
    async def test_thread_metadata_thread_not_found(self):
        rt = _make_runtime()
        rt.ward_room.get_thread = AsyncMock(return_value=None)
        handler = QueryHandler(rt)
        spec = _make_spec(context_keys=("thread_metadata",))
        result = await handler(spec, {"thread_id": "missing"}, [])
        assert result.success is False
        assert "not found" in result.error.lower()


# ---------------------------------------------------------------------------
# 3. TestCommStats
# ---------------------------------------------------------------------------


class TestCommStats:
    """Test comm_stats query operation."""

    @pytest.mark.asyncio
    async def test_comm_stats_returns_agent_data(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("comm_stats",))
        result = await handler(spec, {"agent_id": "a1"}, [])
        assert result.success is True
        assert "comm_stats" in result.result
        assert "posts_total" in result.result["comm_stats"]

    @pytest.mark.asyncio
    async def test_comm_stats_missing_agent_id(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("comm_stats",))
        result = await handler(spec, {}, [])
        assert result.success is False
        assert "agent_id required" in result.error

    @pytest.mark.asyncio
    async def test_comm_stats_with_since_parameter(self):
        rt = _make_runtime()
        handler = QueryHandler(rt)
        spec = _make_spec(context_keys=("comm_stats",))
        await handler(spec, {"agent_id": "a1", "since": 1000.0}, [])
        rt.ward_room.get_agent_comm_stats.assert_called_once_with(
            "a1", since=1000.0,
        )


# ---------------------------------------------------------------------------
# 4. TestTrustQueries
# ---------------------------------------------------------------------------


class TestTrustQueries:
    """Test trust_score and trust_summary query operations."""

    @pytest.mark.asyncio
    async def test_trust_score_returns_float(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("trust_score",))
        result = await handler(spec, {"agent_id": "a1"}, [])
        assert result.success is True
        assert isinstance(result.result["trust_score"]["score"], float)

    @pytest.mark.asyncio
    async def test_trust_summary_returns_list(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("trust_summary",))
        result = await handler(spec, {}, [])
        assert result.success is True
        assert isinstance(result.result["trust_summary"], list)

    @pytest.mark.asyncio
    async def test_trust_network_unavailable(self):
        rt = _make_runtime(trust_network=None)
        handler = QueryHandler(rt)
        spec = _make_spec(context_keys=("trust_score",))
        result = await handler(spec, {"agent_id": "a1"}, [])
        assert result.success is False
        assert "TrustNetwork" in result.error


# ---------------------------------------------------------------------------
# 5. TestCredibilityAndUnread
# ---------------------------------------------------------------------------


class TestCredibilityAndUnread:
    """Test credibility, unread_counts, and unread_dms operations."""

    @pytest.mark.asyncio
    async def test_credibility_returns_data(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("credibility",))
        result = await handler(spec, {"agent_id": "a1"}, [])
        assert result.success is True
        cred = result.result["credibility"]
        assert "credibility_score" in cred
        assert isinstance(cred["credibility_score"], float)

    @pytest.mark.asyncio
    async def test_unread_counts_returns_dict(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("unread_counts",))
        result = await handler(spec, {"agent_id": "a1"}, [])
        assert result.success is True
        counts = result.result["unread_counts"]
        assert isinstance(counts, dict)
        assert "ch-sci" in counts

    @pytest.mark.asyncio
    async def test_unread_dms_returns_list(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("unread_dms",))
        result = await handler(spec, {"agent_id": "a1"}, [])
        assert result.success is True
        assert isinstance(result.result["unread_dms"], list)


# ---------------------------------------------------------------------------
# 6. TestMultipleOperations
# ---------------------------------------------------------------------------


class TestMultipleOperations:
    """Test dispatching multiple context_keys in a single call."""

    @pytest.mark.asyncio
    async def test_multiple_context_keys(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("thread_metadata", "comm_stats"))
        result = await handler(
            spec, {"thread_id": "t-1", "agent_id": "a1"}, [],
        )
        assert result.success is True
        assert "thread_metadata" in result.result
        assert "comm_stats" in result.result

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        """Some keys succeed, some fail — result has both."""
        rt = _make_runtime()
        rt.ward_room.get_agent_comm_stats = AsyncMock(
            side_effect=Exception("DB timeout"),
        )
        handler = QueryHandler(rt)
        spec = _make_spec(context_keys=("thread_metadata", "comm_stats"))
        result = await handler(
            spec, {"thread_id": "t-1", "agent_id": "a1"}, [],
        )
        # Partial failure: thread_metadata succeeded, comm_stats failed
        assert result.success is False
        assert "thread_metadata" in result.result
        assert "comm_stats" not in result.result
        assert "DB timeout" in result.error

    @pytest.mark.asyncio
    async def test_unknown_operation_key(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("nonexistent_key",))
        result = await handler(spec, {}, [])
        assert result.success is False
        assert "Unknown operation key" in result.error


# ---------------------------------------------------------------------------
# 7. TestServiceUnavailable
# ---------------------------------------------------------------------------


class TestServiceUnavailable:
    """Test behavior when runtime services are unavailable."""

    @pytest.mark.asyncio
    async def test_ward_room_none(self):
        rt = _make_runtime(ward_room=None)
        handler = QueryHandler(rt)
        spec = _make_spec(context_keys=("thread_metadata",))
        result = await handler(spec, {"thread_id": "t-1"}, [])
        assert result.success is False
        assert "WardRoomService" in result.error

    @pytest.mark.asyncio
    async def test_trust_network_none(self):
        rt = _make_runtime(trust_network=None)
        handler = QueryHandler(rt)
        spec = _make_spec(context_keys=("trust_score",))
        result = await handler(spec, {"agent_id": "a1"}, [])
        assert result.success is False
        assert "TrustNetwork" in result.error

    @pytest.mark.asyncio
    async def test_runtime_none(self):
        handler = QueryHandler(None)
        spec = _make_spec(context_keys=("thread_metadata",))
        result = await handler(spec, {"thread_id": "t-1"}, [])
        assert result.success is False
        assert "Runtime not available" in result.error


# ---------------------------------------------------------------------------
# 8. TestContextKeyFiltering
# ---------------------------------------------------------------------------


class TestContextKeyFiltering:
    """Test that only requested operations are dispatched."""

    @pytest.mark.asyncio
    async def test_empty_context_keys_runs_nothing(self):
        rt = _make_runtime()
        handler = QueryHandler(rt)
        spec = _make_spec(context_keys=())
        result = await handler(spec, {}, [])
        assert result.success is True
        assert result.result == {}
        # No service methods should have been called
        rt.ward_room.get_thread.assert_not_called()
        rt.trust_network.get_score.assert_not_called()

    @pytest.mark.asyncio
    async def test_context_keys_filter_operations(self):
        """Only thread_metadata is requested — comm_stats should not be called."""
        rt = _make_runtime()
        handler = QueryHandler(rt)
        spec = _make_spec(context_keys=("thread_metadata",))
        await handler(spec, {"thread_id": "t-1"}, [])
        rt.ward_room.get_thread.assert_called_once()
        rt.ward_room.get_agent_comm_stats.assert_not_called()


# ---------------------------------------------------------------------------
# 9. TestDurationTracking
# ---------------------------------------------------------------------------


class TestDurationTracking:
    """Test that wall clock time is recorded."""

    @pytest.mark.asyncio
    async def test_duration_ms_recorded(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("thread_metadata",))
        result = await handler(spec, {"thread_id": "t-1"}, [])
        assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# 10. TestExecutorIntegration
# ---------------------------------------------------------------------------


class TestExecutorIntegration:
    """Test QueryHandler integration with SubTaskExecutor."""

    def test_register_with_executor(self):
        executor = SubTaskExecutor(config=MagicMock(max_chain_steps=6))
        handler = QueryHandler(_make_runtime())
        executor.register_handler(SubTaskType.QUERY, handler)
        assert executor.has_handler(SubTaskType.QUERY)

    @pytest.mark.asyncio
    async def test_executor_can_execute_query_chain(self):
        executor = SubTaskExecutor(config=MagicMock(max_chain_steps=6))
        handler = QueryHandler(_make_runtime())
        executor.register_handler(SubTaskType.QUERY, handler)

        # context_keys includes both the operation key AND the data keys
        # so the executor's context filtering preserves them for the handler
        chain = SubTaskChain(steps=[
            SubTaskSpec(
                sub_task_type=SubTaskType.QUERY,
                name="query-thread",
                context_keys=("thread_metadata", "thread_id"),
            ),
        ])

        results = await executor.execute(
            chain, {"thread_id": "t-1"},
            agent_id="agent-1", agent_type="test",
        )
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].tokens_used == 0

    @pytest.mark.asyncio
    async def test_executor_query_skips_journal(self):
        """QUERY steps must NOT create journal entries (0 LLM calls)."""
        executor = SubTaskExecutor(config=MagicMock(max_chain_steps=6))
        handler = QueryHandler(_make_runtime())
        executor.register_handler(SubTaskType.QUERY, handler)

        mock_journal = AsyncMock()

        chain = SubTaskChain(steps=[
            SubTaskSpec(
                sub_task_type=SubTaskType.QUERY,
                name="query-thread",
                context_keys=("thread_metadata", "thread_id"),
            ),
        ])

        await executor.execute(
            chain, {"thread_id": "t-1"},
            agent_id="agent-1", agent_type="test",
            journal=mock_journal,
        )
        mock_journal.record.assert_not_called()


# ---------------------------------------------------------------------------
# 11. TestPostsByAuthor
# ---------------------------------------------------------------------------


class TestPostsByAuthor:
    """Test posts_by_author query operation."""

    @pytest.mark.asyncio
    async def test_posts_by_author_returns_list(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("posts_by_author",))
        result = await handler(spec, {"author_callsign": "Atlas"}, [])
        assert result.success is True
        assert isinstance(result.result["posts_by_author"], list)

    @pytest.mark.asyncio
    async def test_posts_by_author_missing_callsign(self):
        handler = QueryHandler(_make_runtime())
        spec = _make_spec(context_keys=("posts_by_author",))
        result = await handler(spec, {}, [])
        assert result.success is False
        assert "author_callsign required" in result.error
