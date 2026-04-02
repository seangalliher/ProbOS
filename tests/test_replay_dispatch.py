"""AD-534: Replay-First Dispatch tests.

Tests cover:
- Part 0: Infrastructure wiring (runtime property, config constants, journal migration)
- Part 1: Procedural memory check (_check_procedural_memory)
- Part 2: Replay formatting & health diagnosis
- Part 3: decide() integration
- Part 4: Negative procedure integration
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import IntentDescriptor, IntentMessage


# ─── Test agent subclass ──────────────────────────────────────────

class ReplayTestAgent(CognitiveAgent):
    agent_type = "test_replay"
    _handled_intents = {"test_intent"}
    instructions = "You are a test agent."
    intent_descriptors = [
        IntentDescriptor(
            name="test_intent", params={"text": "input"},
            description="Test intent", tier="domain",
        )
    ]


# ─── Minimal procedure mock ──────────────────────────────────────

@dataclass
class _MockStep:
    step_number: int = 1
    action: str = "Do the thing"
    expected_input: str = ""
    expected_output: str = "Thing done"
    fallback_action: str = "Try again"
    invariants: list[str] = field(default_factory=list)


@dataclass
class _MockProcedure:
    id: str = "proc-001"
    name: str = "Handle test task"
    description: str = "A test procedure"
    steps: list[_MockStep] = field(default_factory=lambda: [_MockStep()])
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=lambda: ["Task completed"])
    compilation_level: int = 4  # AD-535: Level 4 (Autonomous) for zero-token replay tests


def _make_store_mock(
    *,
    find_result=None,
    neg_result=None,
    get_result=None,
    quality_metrics=None,
):
    """Build a MagicMock ProcedureStore with common defaults."""
    store = MagicMock()
    store.find_matching = AsyncMock(return_value=find_result or [])
    store.get = AsyncMock(return_value=get_result)
    store.get_quality_metrics = AsyncMock(return_value=quality_metrics or {})
    store.record_selection = AsyncMock()
    store.record_applied = AsyncMock()
    store.record_completion = AsyncMock()
    store.record_fallback = AsyncMock()
    # AD-535: Graduated compilation methods
    store.record_consecutive_success = AsyncMock(return_value=1)
    store.reset_consecutive_successes = AsyncMock()
    store.promote_compilation_level = AsyncMock()
    store.demote_compilation_level = AsyncMock()
    return store


def _make_runtime_with_store(store):
    """Build a mock runtime that exposes procedure_store."""
    rt = MagicMock()
    rt.procedure_store = store
    rt.cognitive_journal = None
    rt.episodic_memory = None
    return rt


# ─── Clear cache fixture ─────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_caches():
    from probos.cognitive.cognitive_agent import (
        _DECISION_CACHES,
        _CACHE_HITS,
        _CACHE_MISSES,
    )
    _DECISION_CACHES.clear()
    _CACHE_HITS.clear()
    _CACHE_MISSES.clear()


# ==================================================================
# Part 0: Infrastructure Wiring
# ==================================================================

class TestInfrastructureWiring:
    """Part 0 tests: runtime property, config constants, journal migration."""

    def test_config_procedure_constants_exist(self):
        from probos.config import (
            PROCEDURE_MATCH_THRESHOLD,
            PROCEDURE_MIN_COMPILATION_LEVEL,
            PROCEDURE_MIN_SELECTIONS,
            PROCEDURE_HEALTH_FALLBACK_RATE,
            PROCEDURE_HEALTH_COMPLETION_RATE,
            PROCEDURE_HEALTH_APPLIED_RATE,
            PROCEDURE_HEALTH_EFFECTIVE_RATE,
            PROCEDURE_HEALTH_DERIVED_APPLIED,
        )
        assert PROCEDURE_MATCH_THRESHOLD == 0.6
        assert PROCEDURE_MIN_COMPILATION_LEVEL == 2  # AD-535: Level 2 minimum for replay
        assert PROCEDURE_MIN_SELECTIONS == 5
        assert PROCEDURE_HEALTH_FALLBACK_RATE == 0.4
        assert PROCEDURE_HEALTH_COMPLETION_RATE == 0.35
        assert PROCEDURE_HEALTH_APPLIED_RATE == 0.4
        assert PROCEDURE_HEALTH_EFFECTIVE_RATE == 0.55
        assert PROCEDURE_HEALTH_DERIVED_APPLIED == 0.25

    def test_runtime_exposes_procedure_store_property(self):
        from probos.runtime import ProbOSRuntime
        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt._procedure_store = MagicMock()
        assert rt.procedure_store is rt._procedure_store

    def test_runtime_procedure_store_none_when_not_initialized(self):
        from probos.runtime import ProbOSRuntime
        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt._procedure_store = None
        assert rt.procedure_store is None

    @pytest.mark.asyncio
    async def test_journal_schema_has_procedure_id_column(self, tmp_path):
        from probos.cognitive.journal import CognitiveJournal
        from probos.storage.sqlite_factory import default_factory
        j = CognitiveJournal(
            db_path=str(tmp_path / "j.db"),
            connection_factory=default_factory,
        )
        await j.start()
        try:
            cursor = await j._db.execute("PRAGMA table_info(journal)")
            cols = [row[1] for row in await cursor.fetchall()]
            assert "procedure_id" in cols
        finally:
            await j.stop()

    @pytest.mark.asyncio
    async def test_journal_record_accepts_procedure_id(self, tmp_path):
        from probos.cognitive.journal import CognitiveJournal
        from probos.storage.sqlite_factory import default_factory
        j = CognitiveJournal(
            db_path=str(tmp_path / "j.db"),
            connection_factory=default_factory,
        )
        await j.start()
        try:
            await j.record(
                entry_id="test-123",
                timestamp=time.time(),
                agent_id="agent-1",
                agent_type="test",
                procedure_id="proc-abc",
            )
            cursor = await j._db.execute(
                "SELECT procedure_id FROM journal WHERE id = ?", ("test-123",)
            )
            row = await cursor.fetchone()
            assert row[0] == "proc-abc"
        finally:
            await j.stop()


# ==================================================================
# Part 1: Procedural Memory Check
# ==================================================================

class TestProceduralMemoryCheck:
    """Part 1 tests: _check_procedural_memory method."""

    @pytest.mark.asyncio
    async def test_returns_none_without_store(self):
        agent = ReplayTestAgent()
        result = await agent._check_procedural_memory({"intent": "test"})
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_empty_query(self):
        store = _make_store_mock()
        rt = _make_runtime_with_store(store)
        agent = ReplayTestAgent(runtime=rt)
        result = await agent._check_procedural_memory({"intent": "", "params": {}})
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_no_matches(self):
        store = _make_store_mock(find_result=[])
        rt = _make_runtime_with_store(store)
        agent = ReplayTestAgent(runtime=rt)
        result = await agent._check_procedural_memory(
            {"intent": "test_intent", "params": {"message": "hello"}}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_below_threshold(self):
        store = _make_store_mock(
            find_result=[{"id": "p1", "name": "P1", "score": 0.3}],
        )
        rt = _make_runtime_with_store(store)
        agent = ReplayTestAgent(runtime=rt)
        result = await agent._check_procedural_memory(
            {"intent": "test_intent", "params": {"message": "hello"}}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_poor_effective_rate(self):
        store = _make_store_mock(
            find_result=[{"id": "p1", "name": "P1", "score": 0.8}],
            get_result=_MockProcedure(),
            quality_metrics={
                "total_selections": 10,
                "effective_rate": 0.1,
            },
        )
        rt = _make_runtime_with_store(store)
        agent = ReplayTestAgent(runtime=rt)
        result = await agent._check_procedural_memory(
            {"intent": "test_intent", "params": {"message": "hello"}}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_decision_on_match(self):
        proc = _MockProcedure(id="proc-42", name="Do X")
        store = _make_store_mock(
            find_result=[{"id": "proc-42", "name": "Do X", "score": 0.85}],
            get_result=proc,
            quality_metrics={},
        )
        rt = _make_runtime_with_store(store)
        agent = ReplayTestAgent(runtime=rt)
        result = await agent._check_procedural_memory(
            {"intent": "test_intent", "params": {"message": "do X please"}}
        )
        assert result is not None
        assert result["action"] == "execute"
        assert "Procedure Replay" in result["llm_output"]

    @pytest.mark.asyncio
    async def test_decision_has_cached_true(self):
        proc = _MockProcedure(id="proc-42")
        store = _make_store_mock(
            find_result=[{"id": "proc-42", "name": "P", "score": 0.85}],
            get_result=proc,
        )
        rt = _make_runtime_with_store(store)
        agent = ReplayTestAgent(runtime=rt)
        result = await agent._check_procedural_memory(
            {"intent": "test_intent", "params": {"message": "hello"}}
        )
        assert result["cached"] is True

    @pytest.mark.asyncio
    async def test_decision_has_procedure_id(self):
        proc = _MockProcedure(id="proc-42", name="Test Proc")
        store = _make_store_mock(
            find_result=[{"id": "proc-42", "name": "Test Proc", "score": 0.85}],
            get_result=proc,
        )
        rt = _make_runtime_with_store(store)
        agent = ReplayTestAgent(runtime=rt)
        result = await agent._check_procedural_memory(
            {"intent": "test_intent", "params": {"message": "hello"}}
        )
        assert result["procedure_id"] == "proc-42"
        assert result["procedure_name"] == "Test Proc"

    @pytest.mark.asyncio
    async def test_records_selection_and_applied(self):
        proc = _MockProcedure(id="proc-42")
        store = _make_store_mock(
            find_result=[{"id": "proc-42", "name": "P", "score": 0.85}],
            get_result=proc,
        )
        rt = _make_runtime_with_store(store)
        agent = ReplayTestAgent(runtime=rt)
        await agent._check_procedural_memory(
            {"intent": "test_intent", "params": {"message": "hello"}}
        )
        store.record_selection.assert_awaited_once_with("proc-42")
        store.record_applied.assert_awaited_once_with("proc-42")
        # AD-534b: record_completion moved to handle_intent() (post-execution)
        store.record_completion.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_records_fallback_on_error(self):
        proc = _MockProcedure(id="proc-42", name="Bad Proc")
        # Make steps property raise during formatting
        proc.steps = None  # will cause iteration error in _format_procedure_replay
        store = _make_store_mock(
            find_result=[{"id": "proc-42", "name": "Bad Proc", "score": 0.85}],
            get_result=proc,
        )
        rt = _make_runtime_with_store(store)
        agent = ReplayTestAgent(runtime=rt)
        result = await agent._check_procedural_memory(
            {"intent": "test_intent", "params": {"message": "hello"}}
        )
        assert result is None  # fell through to LLM
        # AD-534b: record_fallback moved to handle_intent() (post-execution)
        store.record_fallback.assert_not_awaited()


# ==================================================================
# Part 2: Replay Formatting & Health Diagnosis
# ==================================================================

class TestReplayFormatting:
    """Part 2 tests: _format_procedure_replay."""

    def test_includes_name(self):
        agent = ReplayTestAgent()
        proc = _MockProcedure(name="My Procedure")
        output = agent._format_procedure_replay(proc, 0.9)
        assert "My Procedure" in output

    def test_includes_steps(self):
        agent = ReplayTestAgent()
        proc = _MockProcedure(steps=[
            _MockStep(step_number=1, action="First"),
            _MockStep(step_number=2, action="Second"),
        ])
        output = agent._format_procedure_replay(proc, 0.8)
        assert "**Step 1:** First" in output
        assert "**Step 2:** Second" in output

    def test_includes_postconditions(self):
        agent = ReplayTestAgent()
        proc = _MockProcedure(postconditions=["All done", "No errors"])
        output = agent._format_procedure_replay(proc, 0.8)
        assert "**Postconditions:**" in output
        assert "All done" in output
        assert "No errors" in output

    def test_empty_steps(self):
        agent = ReplayTestAgent()
        proc = _MockProcedure(steps=[], postconditions=[])
        output = agent._format_procedure_replay(proc, 0.7)
        assert "Steps: 0" in output
        assert "**Postconditions:**" not in output


class TestHealthDiagnosis:
    """Part 2 tests: _diagnose_procedure_health."""

    def test_skips_below_min_selections(self, caplog):
        agent = ReplayTestAgent()
        with caplog.at_level(logging.WARNING):
            agent._diagnose_procedure_health("p1", "Proc", {
                "total_selections": 3,
                "fallback_rate": 0.9,
            })
        assert "health diagnosis" not in caplog.text.lower()

    def test_fix_high_fallback(self, caplog):
        agent = ReplayTestAgent()
        with caplog.at_level(logging.WARNING):
            agent._diagnose_procedure_health("p1", "Proc", {
                "total_selections": 10,
                "fallback_rate": 0.5,
                "applied_rate": 0.3,
                "completion_rate": 0.5,
                "effective_rate": 0.6,
            })
        assert "FIX:high_fallback_rate" in caplog.text

    def test_fix_low_completion(self, caplog):
        agent = ReplayTestAgent()
        with caplog.at_level(logging.WARNING):
            agent._diagnose_procedure_health("p1", "Proc", {
                "total_selections": 10,
                "fallback_rate": 0.2,
                "applied_rate": 0.5,
                "completion_rate": 0.2,
                "effective_rate": 0.6,
            })
        assert "FIX:low_completion" in caplog.text

    def test_derived_low_effective(self, caplog):
        agent = ReplayTestAgent()
        with caplog.at_level(logging.WARNING):
            agent._diagnose_procedure_health("p1", "Proc", {
                "total_selections": 10,
                "fallback_rate": 0.2,
                "applied_rate": 0.3,
                "completion_rate": 0.5,
                "effective_rate": 0.4,
            })
        assert "DERIVED:low_effective_rate" in caplog.text


# ==================================================================
# Part 3: decide() Integration
# ==================================================================

class TestDecideIntegration:
    """Part 3 tests: procedural memory check wired into decide()."""

    def _make_llm(self):
        from probos.cognitive.llm_client import MockLLMClient
        return MockLLMClient()

    @pytest.mark.asyncio
    async def test_decide_returns_procedural_result_when_matched(self):
        proc = _MockProcedure(id="proc-99", name="Auto-reply")
        store = _make_store_mock(
            find_result=[{"id": "proc-99", "name": "Auto-reply", "score": 0.9}],
            get_result=proc,
        )
        rt = _make_runtime_with_store(store)
        llm = self._make_llm()
        agent = ReplayTestAgent(llm_client=llm, runtime=rt)
        obs = {"intent": "test_intent", "params": {"message": "do it"}}
        result = await agent.decide(obs)
        assert result.get("cached") is True
        assert result.get("procedure_id") == "proc-99"

    @pytest.mark.asyncio
    async def test_decide_skips_llm_on_procedural_hit(self):
        proc = _MockProcedure(id="proc-99")
        store = _make_store_mock(
            find_result=[{"id": "proc-99", "name": "P", "score": 0.9}],
            get_result=proc,
        )
        rt = _make_runtime_with_store(store)
        llm = self._make_llm()
        agent = ReplayTestAgent(llm_client=llm, runtime=rt)
        obs = {"intent": "test_intent", "params": {"message": "do it"}}
        await agent.decide(obs)
        assert llm.call_count == 0

    @pytest.mark.asyncio
    async def test_decide_falls_through_to_llm_on_no_match(self):
        store = _make_store_mock(find_result=[])
        rt = _make_runtime_with_store(store)
        llm = self._make_llm()
        agent = ReplayTestAgent(llm_client=llm, runtime=rt)
        obs = {"intent": "test_intent", "params": {"message": "do it"}}
        await agent.decide(obs)
        assert llm.call_count == 1

    @pytest.mark.asyncio
    async def test_decide_procedural_replay_journal_entry(self):
        proc = _MockProcedure(id="proc-99")
        store = _make_store_mock(
            find_result=[{"id": "proc-99", "name": "P", "score": 0.9}],
            get_result=proc,
        )
        mock_journal = MagicMock()
        mock_journal.record = AsyncMock()
        rt = _make_runtime_with_store(store)
        rt.cognitive_journal = mock_journal
        llm = self._make_llm()
        agent = ReplayTestAgent(llm_client=llm, runtime=rt)
        obs = {"intent": "test_intent", "params": {"message": "do it"}}
        await agent.decide(obs)
        mock_journal.record.assert_awaited_once()
        call_kwargs = mock_journal.record.call_args.kwargs
        assert call_kwargs["cached"] is True
        assert call_kwargs["procedure_id"] == "proc-99"

    @pytest.mark.asyncio
    async def test_decide_procedural_replay_zero_tokens(self):
        proc = _MockProcedure(id="proc-99")
        store = _make_store_mock(
            find_result=[{"id": "proc-99", "name": "P", "score": 0.9}],
            get_result=proc,
        )
        mock_journal = MagicMock()
        mock_journal.record = AsyncMock()
        rt = _make_runtime_with_store(store)
        rt.cognitive_journal = mock_journal
        llm = self._make_llm()
        agent = ReplayTestAgent(llm_client=llm, runtime=rt)
        obs = {"intent": "test_intent", "params": {"message": "do it"}}
        await agent.decide(obs)
        call_kwargs = mock_journal.record.call_args.kwargs
        assert call_kwargs["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_decide_decision_cache_takes_priority(self):
        """Decision cache hit (from LLM path) → procedural memory NOT checked."""
        store = _make_store_mock(find_result=[])  # No procedural matches
        rt = _make_runtime_with_store(store)
        llm = self._make_llm()
        agent = ReplayTestAgent(llm_client=llm, runtime=rt, pool="test")
        obs = {"intent": "test_intent", "params": {"message": "do it"}}
        # First call: cache miss → no proc match → LLM call → cached in decision cache
        result1 = await agent.decide(obs)
        assert llm.call_count == 1
        call_count_after_first = store.find_matching.await_count
        # Second call: decision cache hit → procedural check never runs
        result2 = await agent.decide(obs)
        assert result2.get("cached") is True
        assert llm.call_count == 1  # LLM not called again
        # Store.find_matching should NOT have been called again
        assert store.find_matching.await_count == call_count_after_first

    @pytest.mark.asyncio
    async def test_decide_procedural_failure_falls_through_to_llm(self):
        store = _make_store_mock()
        store.find_matching = AsyncMock(side_effect=RuntimeError("DB error"))
        rt = _make_runtime_with_store(store)
        llm = self._make_llm()
        agent = ReplayTestAgent(llm_client=llm, runtime=rt)
        obs = {"intent": "test_intent", "params": {"message": "do it"}}
        result = await agent.decide(obs)
        # Should have fallen through to LLM
        assert llm.call_count == 1

    @pytest.mark.asyncio
    async def test_decide_checks_procedural_memory_after_cache_miss(self):
        """Verify dispatch order: cache miss → procedural check → (LLM if needed)."""
        proc = _MockProcedure(id="proc-99")
        store = _make_store_mock(
            find_result=[{"id": "proc-99", "name": "P", "score": 0.9}],
            get_result=proc,
        )
        rt = _make_runtime_with_store(store)
        llm = self._make_llm()
        agent = ReplayTestAgent(llm_client=llm, runtime=rt)
        obs = {"intent": "test_intent", "params": {"message": "do it"}}
        result = await agent.decide(obs)
        # Procedural match returned → LLM never called
        assert result.get("cached") is True
        assert llm.call_count == 0
        # Store was queried
        assert store.find_matching.await_count > 0


# ==================================================================
# Part 4: Negative Procedure Integration
# ==================================================================

class TestNegativeProcedures:
    """Part 4 tests: anti-pattern detection flow."""

    @pytest.mark.asyncio
    async def test_negative_procedure_blocks_replay(self):
        store = _make_store_mock()
        # find_matching returns negative match above threshold
        store.find_matching = AsyncMock(return_value=[
            {"id": "neg-1", "name": "Bad Pattern", "score": 0.8, "is_negative": True},
        ])
        rt = _make_runtime_with_store(store)
        agent = ReplayTestAgent(runtime=rt)
        result = await agent._check_procedural_memory(
            {"intent": "test_intent", "params": {"message": "hello"}}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_negative_procedure_logs_warning(self, caplog):
        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[
            {"id": "neg-1", "name": "Bad Pattern", "score": 0.8, "is_negative": True},
        ])
        rt = _make_runtime_with_store(store)
        agent = ReplayTestAgent(runtime=rt)
        with caplog.at_level(logging.WARNING):
            await agent._check_procedural_memory(
                {"intent": "test_intent", "params": {"message": "hello"}}
            )
        assert "Negative procedure match" in caplog.text
        assert "Bad Pattern" in caplog.text

    @pytest.mark.asyncio
    async def test_negative_check_failure_noncritical(self):
        """Store error on negative check → continues to positive search."""
        store = _make_store_mock()
        call_count = 0

        async def _find_matching_side_effect(query, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call (negative check) fails
                raise RuntimeError("DB error")
            # Second call (positive check) returns no matches
            return []

        store.find_matching = AsyncMock(side_effect=_find_matching_side_effect)
        rt = _make_runtime_with_store(store)
        agent = ReplayTestAgent(runtime=rt)
        result = await agent._check_procedural_memory(
            {"intent": "test_intent", "params": {"message": "hello"}}
        )
        # Should have continued past the negative check failure
        assert result is None
        assert call_count == 2  # both calls made

    @pytest.mark.asyncio
    async def test_positive_match_not_blocked_by_low_score_negative(self):
        """Negative below threshold doesn't block positive replay."""
        proc = _MockProcedure(id="proc-42", name="Good Proc")
        store = _make_store_mock(get_result=proc)
        call_count = 0

        async def _find_matching_side_effect(query, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Negative check: returns match below threshold
                return [{"id": "neg-1", "name": "Bad", "score": 0.3, "is_negative": True}]
            # Positive check: returns good match
            return [{"id": "proc-42", "name": "Good Proc", "score": 0.85}]

        store.find_matching = AsyncMock(side_effect=_find_matching_side_effect)
        rt = _make_runtime_with_store(store)
        agent = ReplayTestAgent(runtime=rt)
        result = await agent._check_procedural_memory(
            {"intent": "test_intent", "params": {"message": "hello"}}
        )
        assert result is not None
        assert result["procedure_id"] == "proc-42"
