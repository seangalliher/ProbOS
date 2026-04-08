"""AD-534b: Fallback learning tests.

Tests for the complete fallback learning pipeline:
- Metric semantics fix (Part 0)
- Near-miss capture (Part 1)
- Service recovery (Part 2)
- Fallback event emission (Part 2c/3)
- Event & queue infrastructure (Part 3)
- Targeted FIX evolution (Part 4)
- Dream Step 7d (Part 5)
- DreamReport enhancement (Part 6)
- End-to-end integration (Part 7)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ------------------------------------------------------------------ helpers
def _make_cognitive_agent(**overrides):
    """Build a minimal CognitiveAgent for testing."""
    from probos.cognitive.cognitive_agent import CognitiveAgent, _DECISION_CACHES
    from probos.types import AgentMeta, AgentState

    defaults = {
        "agent_id": "test-agent",
        "agent_type": "test",
        "instructions": "Test instructions.",
        "llm_client": AsyncMock(),
    }
    defaults.update(overrides)

    # Clear decision cache to prevent cross-test contamination
    _DECISION_CACHES.pop(defaults["agent_type"], None)

    class TestCognitiveAgent(CognitiveAgent):
        _handled_intents = {"test_intent"}

    agent = object.__new__(TestCognitiveAgent)
    agent.instructions = defaults["instructions"]
    agent.agent_type = defaults["agent_type"]
    agent.id = defaults["agent_id"]
    agent.callsign = "test"
    agent.confidence = 0.5
    agent.meta = AgentMeta()
    agent.state = AgentState.ACTIVE
    agent.trust_score = 0.5
    agent._llm_client = defaults["llm_client"]
    agent._runtime = defaults.get("runtime")
    agent._skills = {}
    agent._strategy_advisor = None
    agent._last_fallback_info = None
    return agent


def _make_procedure(**overrides):
    """Build a minimal Procedure for testing."""
    from probos.cognitive.procedures import Procedure, ProcedureStep

    defaults = {
        "id": "proc-001",
        "name": "Test Procedure",
        "description": "A test procedure",
        "steps": [ProcedureStep(step_number=1, action="Do something")],
        "intent_types": ["test_intent"],
        "is_active": True,
        "generation": 0,
        "compilation_level": 4,  # AD-535: Level 4 (Autonomous) for zero-token replay tests
    }
    defaults.update(overrides)
    return Procedure(**defaults)


def _make_store_mock():
    """Build a mock procedure store."""
    store = AsyncMock()
    store.find_matching = AsyncMock(return_value=[])
    store.get = AsyncMock(return_value=None)
    store.get_quality_metrics = AsyncMock(return_value={})
    store.record_selection = AsyncMock()
    store.record_applied = AsyncMock()
    store.record_completion = AsyncMock()
    store.record_fallback = AsyncMock()
    store.save = AsyncMock()
    store.deactivate = AsyncMock()
    store.list_active = AsyncMock(return_value=[])
    store.has_cluster = AsyncMock(return_value=False)
    # AD-535: Graduated compilation methods
    store.record_consecutive_success = AsyncMock(return_value=1)
    store.reset_consecutive_successes = AsyncMock()
    store.promote_compilation_level = AsyncMock()
    store.demote_compilation_level = AsyncMock()
    return store


def _make_intent(intent_type="test_intent", **overrides):
    """Build a minimal IntentMessage."""
    from probos.types import IntentMessage
    defaults = {
        "intent": intent_type,
        "params": {"message": "test query"},
        "context": "",
        "target_agent_id": "test-agent",
    }
    defaults.update(overrides)
    return IntentMessage(**defaults)


def _make_dreaming_engine(**overrides):
    """Build a minimal DreamingEngine for testing."""
    from probos.cognitive.dreaming import DreamingEngine
    from probos.config import DreamingConfig

    engine = object.__new__(DreamingEngine)
    engine.router = MagicMock()
    engine.trust_network = MagicMock()
    engine.episodic_memory = overrides.get("episodic_memory", AsyncMock())
    engine.config = DreamingConfig()
    engine.pre_warm_intents = []
    engine._idle_scale_down_fn = None
    engine._gap_prediction_fn = None
    engine._last_clusters = []
    engine._contradiction_resolve_fn = None
    engine._last_consolidated_count = 0
    engine._llm_client = overrides.get("llm_client", AsyncMock())
    engine._procedure_store = overrides.get("procedure_store", _make_store_mock())
    engine._last_procedures = []
    engine._extracted_cluster_ids = set()
    engine._addressed_degradations = {}
    engine._extraction_candidates = {}
    engine._reactive_cooldowns = {}
    engine._fallback_learning_queue = []
    # AD-537 fields
    engine._ward_room = None
    engine._agent_id = ""
    engine._trust_network_lookup = None
    engine._observed_threads = set()
    # AD-557 fields
    engine._emergence_metrics_engine = None
    engine._get_department = None
    # AD-551 fields
    engine._records_store = None
    # AD-555 fields
    engine._notebook_quality_engine = None
    # AD-541c fields
    engine._retrieval_practice_engine = None
    engine._retrieval_llm_client = None
    # AD-567d fields
    engine._activation_tracker = None
    engine._behavioral_metrics_engine = None  # AD-569
    return engine


# ==================================================================
# Test Class 1: TestMetricSemanticsFix
# ==================================================================


class TestMetricSemanticsFix:
    """Part 0: Verify record_completion/record_fallback moved to handle_intent."""

    @pytest.mark.asyncio
    async def test_completion_not_recorded_in_check_procedural(self):
        """_check_procedural_memory() no longer calls record_completion()."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        proc = _make_procedure()
        store.find_matching.return_value = [
            {"id": proc.id, "name": proc.name, "score": 0.9}
        ]
        store.get.return_value = proc
        store.get_quality_metrics.return_value = {}
        agent._runtime = MagicMock()
        agent._runtime.procedure_store = store

        observation = {"intent": "test_intent", "params": {"message": "test query"}}
        result = await agent._check_procedural_memory(observation)

        assert result is not None
        assert result["cached"] is True
        store.record_completion.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_not_recorded_in_check_procedural(self):
        """_check_procedural_memory() no longer calls record_fallback()."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        proc = _make_procedure()
        store.find_matching.return_value = [
            {"id": proc.id, "name": proc.name, "score": 0.9}
        ]
        store.get.return_value = proc
        store.get_quality_metrics.return_value = {}
        agent._runtime = MagicMock()
        agent._runtime.procedure_store = store

        # Make _format_procedure_replay raise to trigger the except block
        with patch.object(agent, '_format_procedure_replay', side_effect=Exception("boom")):
            observation = {"intent": "test_intent", "params": {"message": "test query"}}
            result = await agent._check_procedural_memory(observation)

        assert result is None
        store.record_fallback.assert_not_called()

    @pytest.mark.asyncio
    async def test_completion_recorded_after_successful_act(self):
        """Cached decision + act() success → record_completion() in handle_intent()."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        proc = _make_procedure()
        store.find_matching.side_effect = [
            # First call: negative check (empty)
            [],
            # Second call: positive match
            [{"id": proc.id, "name": proc.name, "score": 0.9}],
        ]
        store.get.return_value = proc
        store.get_quality_metrics.return_value = {}

        runtime = MagicMock()
        runtime.procedure_store = store
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock, return_value={"intent": "test_intent", "params": {"message": "test query"}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                result = await agent.handle_intent(intent)

        assert result is not None
        assert result.success is True
        store.record_completion.assert_called_once_with(proc.id)

    @pytest.mark.asyncio
    async def test_fallback_recorded_after_failed_act(self):
        """Cached decision + act() failure → record_fallback() in handle_intent()."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        proc = _make_procedure()
        store.find_matching.side_effect = [[], [{"id": proc.id, "name": proc.name, "score": 0.9}]]
        store.get.return_value = proc
        store.get_quality_metrics.return_value = {}

        runtime = MagicMock()
        runtime.procedure_store = store
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        # Make act() return failure
        async def _failing_act(decision):
            return {"success": False, "error": "test error"}

        agent.act = _failing_act

        # Also make _run_llm_fallback return None so service recovery doesn't mask
        agent._run_llm_fallback = AsyncMock(return_value=None)

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock, return_value={"intent": "test_intent", "params": {"message": "test query"}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                result = await agent.handle_intent(intent)

        store.record_fallback.assert_called_once_with(proc.id)

    @pytest.mark.asyncio
    async def test_metrics_not_recorded_for_non_cached(self):
        """Non-cached decision → no completion/fallback recording."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()

        runtime = MagicMock()
        runtime.procedure_store = store
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        # Mock decide to return non-cached decision
        agent.decide = AsyncMock(return_value={"action": "execute", "llm_output": "test"})

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock, return_value={"intent": "test_intent", "params": {}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                await agent.handle_intent(intent)

        store.record_completion.assert_not_called()
        store.record_fallback.assert_not_called()

    @pytest.mark.asyncio
    async def test_procedure_id_in_decision_dict(self):
        """Cached decision dict contains 'procedure_id'."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        proc = _make_procedure()
        store.find_matching.return_value = [{"id": proc.id, "name": proc.name, "score": 0.9}]
        store.get.return_value = proc
        store.get_quality_metrics.return_value = {}

        runtime = MagicMock()
        runtime.procedure_store = store
        agent._runtime = runtime

        observation = {"intent": "test_intent", "params": {"message": "test"}}
        result = await agent._check_procedural_memory(observation)

        assert result is not None
        assert "procedure_id" in result
        assert result["procedure_id"] == proc.id


# ==================================================================
# Test Class 2: TestNearMissCapture
# ==================================================================


class TestNearMissCapture:
    """Part 1: Verify _last_fallback_info is set correctly at rejection points."""

    @pytest.mark.asyncio
    async def test_score_threshold_sets_fallback_info(self):
        """Best match below threshold → _last_fallback_info with type='score_threshold'."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        store.find_matching.return_value = [{"id": "p1", "name": "Test", "score": 0.1}]

        runtime = MagicMock()
        runtime.procedure_store = store
        agent._runtime = runtime

        observation = {"intent": "test_intent", "params": {"message": "test"}}
        result = await agent._check_procedural_memory(observation)

        assert result is None
        assert agent._last_fallback_info is not None
        assert agent._last_fallback_info["type"] == "score_threshold"
        assert agent._last_fallback_info["procedure_id"] == "p1"

    @pytest.mark.asyncio
    async def test_quality_gate_sets_fallback_info(self):
        """Effective rate < 0.3 → _last_fallback_info with type='quality_gate'."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        store.find_matching.return_value = [{"id": "p1", "name": "Test", "score": 0.9}]
        store.get_quality_metrics.return_value = {
            "total_selections": 10,
            "effective_rate": 0.2,
        }

        runtime = MagicMock()
        runtime.procedure_store = store
        agent._runtime = runtime

        observation = {"intent": "test_intent", "params": {"message": "test"}}
        result = await agent._check_procedural_memory(observation)

        assert result is None
        assert agent._last_fallback_info is not None
        assert agent._last_fallback_info["type"] == "quality_gate"

    @pytest.mark.asyncio
    async def test_negative_veto_sets_fallback_info(self):
        """Negative procedure blocks match → _last_fallback_info with type='negative_veto'."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        store.find_matching.return_value = [
            {"id": "neg-1", "name": "Bad Pattern", "score": 0.9, "is_negative": True}
        ]

        runtime = MagicMock()
        runtime.procedure_store = store
        agent._runtime = runtime

        observation = {"intent": "test_intent", "params": {"message": "test"}}
        result = await agent._check_procedural_memory(observation)

        assert result is None
        assert agent._last_fallback_info is not None
        assert agent._last_fallback_info["type"] == "negative_veto"
        assert agent._last_fallback_info["procedure_id"] == "neg-1"

    @pytest.mark.asyncio
    async def test_format_exception_sets_fallback_info(self):
        """Replay formatting raises → _last_fallback_info with type='format_exception'."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        proc = _make_procedure()
        store.find_matching.return_value = [{"id": proc.id, "name": proc.name, "score": 0.9}]
        store.get.return_value = proc
        store.get_quality_metrics.return_value = {}

        runtime = MagicMock()
        runtime.procedure_store = store
        agent._runtime = runtime

        with patch.object(agent, '_format_procedure_replay', side_effect=Exception("format error")):
            observation = {"intent": "test_intent", "params": {"message": "test"}}
            result = await agent._check_procedural_memory(observation)

        assert result is None
        assert agent._last_fallback_info is not None
        assert agent._last_fallback_info["type"] == "format_exception"

    @pytest.mark.asyncio
    async def test_no_match_does_not_set_fallback_info(self):
        """Empty results from find_matching → _last_fallback_info remains None."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        store.find_matching.return_value = []

        runtime = MagicMock()
        runtime.procedure_store = store
        agent._runtime = runtime

        observation = {"intent": "test_intent", "params": {"message": "test"}}
        result = await agent._check_procedural_memory(observation)

        assert result is None
        assert agent._last_fallback_info is None

    @pytest.mark.asyncio
    async def test_fallback_info_cleared_on_entry(self):
        """Each call to _check_procedural_memory() resets _last_fallback_info."""
        agent = _make_cognitive_agent()
        agent._last_fallback_info = {"type": "old_stale_info"}
        store = _make_store_mock()
        store.find_matching.return_value = []

        runtime = MagicMock()
        runtime.procedure_store = store
        agent._runtime = runtime

        observation = {"intent": "test_intent", "params": {"message": "test"}}
        await agent._check_procedural_memory(observation)

        assert agent._last_fallback_info is None

    @pytest.mark.asyncio
    async def test_fallback_info_includes_procedure_id(self):
        """All near-miss types include procedure_id."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        store.find_matching.return_value = [{"id": "p99", "name": "X", "score": 0.1}]

        runtime = MagicMock()
        runtime.procedure_store = store
        agent._runtime = runtime

        observation = {"intent": "test_intent", "params": {"message": "test"}}
        await agent._check_procedural_memory(observation)

        assert agent._last_fallback_info is not None
        assert "procedure_id" in agent._last_fallback_info

    @pytest.mark.asyncio
    async def test_fallback_info_includes_reason(self):
        """All near-miss types include human-readable reason string."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        store.find_matching.return_value = [{"id": "p1", "name": "X", "score": 0.1}]

        runtime = MagicMock()
        runtime.procedure_store = store
        agent._runtime = runtime

        observation = {"intent": "test_intent", "params": {"message": "test"}}
        await agent._check_procedural_memory(observation)

        assert agent._last_fallback_info is not None
        assert "reason" in agent._last_fallback_info
        assert len(agent._last_fallback_info["reason"]) > 0


# ==================================================================
# Test Class 3: TestServiceRecovery
# ==================================================================


class TestServiceRecovery:
    """Part 2: Verify service recovery on cached execution failure."""

    @pytest.mark.asyncio
    async def test_cached_failure_triggers_llm_rerun(self):
        """Cached decision + act fails → _run_llm_fallback() called."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        proc = _make_procedure()
        store.find_matching.side_effect = [[], [{"id": proc.id, "name": proc.name, "score": 0.9}]]
        store.get.return_value = proc
        store.get_quality_metrics.return_value = {}

        runtime = MagicMock()
        runtime.procedure_store = store
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        call_count = [0]
        original_act = agent.act

        async def _act_that_fails_once(decision):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"success": False, "error": "replay failed"}
            return {"success": True, "result": "recovered"}

        agent.act = _act_that_fails_once
        agent._run_llm_fallback = AsyncMock(return_value={"action": "execute", "llm_output": "llm fixed it"})

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock, return_value={"intent": "test_intent", "params": {"message": "test"}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                result = await agent.handle_intent(intent)

        agent._run_llm_fallback.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_rerun_success_replaces_result(self):
        """LLM re-run succeeds → result/report/success updated."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        proc = _make_procedure()
        store.find_matching.side_effect = [[], [{"id": proc.id, "name": proc.name, "score": 0.9}]]
        store.get.return_value = proc
        store.get_quality_metrics.return_value = {}

        runtime = MagicMock()
        runtime.procedure_store = store
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        call_count = [0]

        async def _act_that_fails_first(decision):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"success": False, "error": "replay failed"}
            return {"success": True, "result": "recovered via LLM"}

        agent.act = _act_that_fails_first
        agent._run_llm_fallback = AsyncMock(return_value={"action": "execute", "llm_output": "llm says do this"})

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock, return_value={"intent": "test_intent", "params": {"message": "test"}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                result = await agent.handle_intent(intent)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_llm_rerun_failure_keeps_original(self):
        """LLM re-run also fails → original failure stands."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        proc = _make_procedure()
        store.find_matching.side_effect = [[], [{"id": proc.id, "name": proc.name, "score": 0.9}]]
        store.get.return_value = proc
        store.get_quality_metrics.return_value = {}

        runtime = MagicMock()
        runtime.procedure_store = store
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        async def _always_fail(decision):
            return {"success": False, "error": "still broken"}

        agent.act = _always_fail
        agent._run_llm_fallback = AsyncMock(return_value={"action": "execute", "llm_output": "llm attempt"})

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock, return_value={"intent": "test_intent", "params": {"message": "test"}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                result = await agent.handle_intent(intent)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_llm_rerun_exception_nonfatal(self):
        """_run_llm_fallback() raises → original failure stands, no crash."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        proc = _make_procedure()
        store.find_matching.side_effect = [[], [{"id": proc.id, "name": proc.name, "score": 0.9}]]
        store.get.return_value = proc
        store.get_quality_metrics.return_value = {}

        runtime = MagicMock()
        runtime.procedure_store = store
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        async def _fail_act(decision):
            return {"success": False, "error": "broken"}

        agent.act = _fail_act
        agent._run_llm_fallback = AsyncMock(side_effect=Exception("LLM exploded"))

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock, return_value={"intent": "test_intent", "params": {"message": "test"}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                result = await agent.handle_intent(intent)

        assert result.success is False  # No crash

    @pytest.mark.asyncio
    async def test_confidence_updated_with_recovered_success(self):
        """After service recovery, update_confidence() receives True."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()
        proc = _make_procedure()
        store.find_matching.side_effect = [[], [{"id": proc.id, "name": proc.name, "score": 0.9}]]
        store.get.return_value = proc
        store.get_quality_metrics.return_value = {}

        runtime = MagicMock()
        runtime.procedure_store = store
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        call_count = [0]

        async def _act_fails_first(decision):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"success": False}
            return {"success": True, "result": "ok"}

        agent.act = _act_fails_first
        agent._run_llm_fallback = AsyncMock(return_value={"action": "execute", "llm_output": "fix"})
        old_confidence = agent.confidence

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock, return_value={"intent": "test_intent", "params": {"message": "test"}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                result = await agent.handle_intent(intent)

        assert result.success is True
        # Confidence should have gone up (from update_confidence(True))
        assert agent.confidence >= old_confidence

    @pytest.mark.asyncio
    async def test_non_cached_failure_no_rerun(self):
        """Non-cached decision fails → no LLM re-run."""
        agent = _make_cognitive_agent()
        store = _make_store_mock()

        runtime = MagicMock()
        runtime.procedure_store = store
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        agent.decide = AsyncMock(return_value={"action": "execute", "llm_output": "test"})

        async def _fail_act(decision):
            return {"success": False, "error": "broken"}

        agent.act = _fail_act
        agent._run_llm_fallback = AsyncMock()

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock, return_value={"intent": "test_intent", "params": {}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                await agent.handle_intent(intent)

        agent._run_llm_fallback.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_llm_fallback_skips_procedure_memory(self):
        """_run_llm_fallback() does not call _check_procedural_memory()."""
        agent = _make_cognitive_agent()
        agent._llm_client = AsyncMock()
        agent._llm_client.complete = AsyncMock(
            return_value=MagicMock(content="result", tier="standard", model="test", error=None,
                                  prompt_tokens=10, completion_tokens=20, tokens_used=30)
        )
        runtime = MagicMock()
        runtime.cognitive_journal = None
        agent._runtime = runtime

        with patch.object(agent, '_check_procedural_memory', new_callable=AsyncMock) as mock_check:
            result = await agent._run_llm_fallback({"intent": "test", "params": {}})

        mock_check.assert_not_called()
        assert result is not None

    @pytest.mark.asyncio
    async def test_run_llm_fallback_skips_decision_cache(self):
        """_run_llm_fallback() does not check decision cache."""
        from probos.cognitive.cognitive_agent import _DECISION_CACHES

        agent = _make_cognitive_agent()
        agent._llm_client = AsyncMock()
        agent._llm_client.complete = AsyncMock(
            return_value=MagicMock(content="result", tier="standard", model="test", error=None,
                                  prompt_tokens=10, completion_tokens=20, tokens_used=30)
        )
        runtime = MagicMock()
        runtime.cognitive_journal = None
        agent._runtime = runtime

        # Pre-populate cache
        _DECISION_CACHES[agent.agent_type] = {
            "test-key": ({"cached_result": True}, time.monotonic(), 9999)
        }

        result = await agent._run_llm_fallback({"intent": "test", "params": {}})

        # Should have called LLM, not returned cache
        assert result is not None
        assert "cached_result" not in result
        agent._llm_client.complete.assert_called_once()

        # Cleanup
        _DECISION_CACHES.pop(agent.agent_type, None)


# ==================================================================
# Test Class 4: TestFallbackEventEmission
# ==================================================================


class TestFallbackEventEmission:
    """Part 2c/3: Verify PROCEDURE_FALLBACK_LEARNING event emission."""

    @pytest.mark.asyncio
    async def test_event_emitted_on_near_miss_with_llm_success(self):
        """Near-miss + LLM succeeds → PROCEDURE_FALLBACK_LEARNING event emitted."""
        from probos.events import EventType

        agent = _make_cognitive_agent()
        runtime = MagicMock()
        runtime.procedure_store = None  # No store → skip procedural memory
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        # Simulate: near-miss was captured, LLM succeeded
        agent._last_fallback_info = {
            "type": "score_threshold",
            "procedure_id": "p1",
            "procedure_name": "Test",
            "score": 0.3,
            "reason": "Score too low",
        }
        agent.decide = AsyncMock(return_value={"action": "execute", "llm_output": "LLM did it"})

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock, return_value={"intent": "test_intent", "params": {}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                await agent.handle_intent(intent)

        # Check that PROCEDURE_FALLBACK_LEARNING was emitted
        calls = runtime._emit_event.call_args_list
        fallback_calls = [c for c in calls if c[0][0] == EventType.PROCEDURE_FALLBACK_LEARNING]
        assert len(fallback_calls) == 1

    @pytest.mark.asyncio
    async def test_event_not_emitted_on_near_miss_with_llm_failure(self):
        """Near-miss + LLM fails → no event."""
        from probos.events import EventType

        agent = _make_cognitive_agent()
        runtime = MagicMock()
        runtime.procedure_store = None
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        agent._last_fallback_info = {
            "type": "score_threshold",
            "procedure_id": "p1",
            "score": 0.3,
            "reason": "Score too low",
        }

        async def _fail_act(d):
            return {"success": False}

        agent.decide = AsyncMock(return_value={"action": "execute", "llm_output": "test"})
        agent.act = _fail_act

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock, return_value={"intent": "test_intent", "params": {}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                await agent.handle_intent(intent)

        calls = runtime._emit_event.call_args_list
        fallback_calls = [c for c in calls if c[0][0] == EventType.PROCEDURE_FALLBACK_LEARNING]
        assert len(fallback_calls) == 0

    @pytest.mark.asyncio
    async def test_event_not_emitted_without_fallback_info(self):
        """No near-miss, normal LLM path → no fallback event."""
        from probos.events import EventType

        agent = _make_cognitive_agent()
        runtime = MagicMock()
        runtime.procedure_store = None
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        agent.decide = AsyncMock(return_value={"action": "execute", "llm_output": "test"})

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock, return_value={"intent": "test_intent", "params": {}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                await agent.handle_intent(intent)

        calls = runtime._emit_event.call_args_list
        fallback_calls = [c for c in calls if c[0][0] == EventType.PROCEDURE_FALLBACK_LEARNING]
        assert len(fallback_calls) == 0

    @pytest.mark.asyncio
    async def test_event_emitted_on_execution_failure_recovery(self):
        """Cached failure + LLM recovery → event with type='execution_failure'."""
        from probos.events import EventType

        agent = _make_cognitive_agent()
        store = _make_store_mock()
        proc = _make_procedure()
        store.find_matching.side_effect = [[], [{"id": proc.id, "name": proc.name, "score": 0.9}]]
        store.get.return_value = proc
        store.get_quality_metrics.return_value = {}

        runtime = MagicMock()
        runtime.procedure_store = store
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        call_count = [0]

        async def _act_fails_first(decision):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"success": False}
            return {"success": True, "result": "recovered"}

        agent.act = _act_fails_first
        agent._run_llm_fallback = AsyncMock(return_value={"action": "execute", "llm_output": "fixed"})

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock, return_value={"intent": "test_intent", "params": {"message": "test"}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                result = await agent.handle_intent(intent)

        calls = runtime._emit_event.call_args_list
        fallback_calls = [c for c in calls if c[0][0] == EventType.PROCEDURE_FALLBACK_LEARNING]
        assert len(fallback_calls) == 1
        data = fallback_calls[0][0][1]
        assert data["fallback_type"] == "execution_failure"

    def test_event_contains_llm_response_truncated(self):
        """Event llm_response truncated to MAX_FALLBACK_RESPONSE_CHARS."""
        from probos.config import MAX_FALLBACK_RESPONSE_CHARS
        assert MAX_FALLBACK_RESPONSE_CHARS == 4000

    def test_event_contains_procedure_id_and_name(self):
        """Event data includes procedure identifying info — verified via structure."""
        from probos.events import ProcedureFallbackLearningEvent
        e = ProcedureFallbackLearningEvent()
        assert hasattr(e, "procedure_id")
        assert hasattr(e, "procedure_name")

    def test_event_contains_rejection_reason(self):
        """Event data includes human-readable reason."""
        from probos.events import ProcedureFallbackLearningEvent
        e = ProcedureFallbackLearningEvent()
        assert hasattr(e, "rejection_reason")

    @pytest.mark.asyncio
    async def test_event_emission_failure_nonfatal(self):
        """Event emission raises → no crash."""
        from probos.events import EventType

        agent = _make_cognitive_agent()
        runtime = MagicMock()
        runtime.procedure_store = None
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock(side_effect=Exception("event broken"))
        agent._runtime = runtime

        agent._last_fallback_info = {"type": "score_threshold", "procedure_id": "p1", "score": 0.3, "reason": "low"}
        agent.decide = AsyncMock(return_value={"action": "execute", "llm_output": "test"})

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock, return_value={"intent": "test_intent", "params": {}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                result = await agent.handle_intent(intent)

        assert result is not None  # No crash

    @pytest.mark.asyncio
    async def test_fallback_info_cleared_after_event(self):
        """_last_fallback_info set to None after event emission."""
        agent = _make_cognitive_agent()
        runtime = MagicMock()
        runtime.procedure_store = None
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        agent._last_fallback_info = {"type": "score_threshold", "procedure_id": "p1", "score": 0.3, "reason": "low"}
        agent.decide = AsyncMock(return_value={"action": "execute", "llm_output": "test"})

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock, return_value={"intent": "test_intent", "params": {}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                await agent.handle_intent(intent)

        assert agent._last_fallback_info is None


# ==================================================================
# Test Class 5: TestEventAndQueue
# ==================================================================


class TestEventAndQueue:
    """Part 3: Event type, dataclass, and DreamingEngine queue."""

    def test_procedure_fallback_learning_event_type_exists(self):
        """EventType.PROCEDURE_FALLBACK_LEARNING exists."""
        from probos.events import EventType
        assert hasattr(EventType, "PROCEDURE_FALLBACK_LEARNING")
        assert EventType.PROCEDURE_FALLBACK_LEARNING == "procedure_fallback_learning"

    def test_procedure_fallback_learning_event_dataclass(self):
        """ProcedureFallbackLearningEvent has all required fields."""
        from probos.events import ProcedureFallbackLearningEvent
        e = ProcedureFallbackLearningEvent()
        assert hasattr(e, "agent_id")
        assert hasattr(e, "intent_type")
        assert hasattr(e, "fallback_type")
        assert hasattr(e, "procedure_id")
        assert hasattr(e, "procedure_name")
        assert hasattr(e, "near_miss_score")
        assert hasattr(e, "rejection_reason")
        assert hasattr(e, "llm_response")
        assert hasattr(e, "timestamp")

    @pytest.mark.asyncio
    async def test_dreaming_engine_queues_event(self):
        """on_procedure_fallback_learning() appends to _fallback_learning_queue."""
        engine = _make_dreaming_engine()
        event = {"fallback_type": "score_threshold", "procedure_id": "p1", "procedure_name": "Test"}

        await engine.on_procedure_fallback_learning(event)

        assert len(engine._fallback_learning_queue) == 1
        assert engine._fallback_learning_queue[0] == event

    @pytest.mark.asyncio
    async def test_queue_cap_evicts_oldest(self):
        """Queue at MAX_FALLBACK_QUEUE_SIZE → oldest entry dropped."""
        from probos.config import MAX_FALLBACK_QUEUE_SIZE

        engine = _make_dreaming_engine()
        # Fill queue to capacity
        for i in range(MAX_FALLBACK_QUEUE_SIZE):
            engine._fallback_learning_queue.append({"id": f"event-{i}"})

        # Add one more
        await engine.on_procedure_fallback_learning({"id": "newest"})

        assert len(engine._fallback_learning_queue) == MAX_FALLBACK_QUEUE_SIZE
        assert engine._fallback_learning_queue[0]["id"] == "event-1"  # oldest evicted
        assert engine._fallback_learning_queue[-1]["id"] == "newest"

    @pytest.mark.asyncio
    async def test_queue_guard_no_store(self):
        """procedure_store is None → event not queued."""
        engine = _make_dreaming_engine(procedure_store=None)
        engine._procedure_store = None

        await engine.on_procedure_fallback_learning({"fallback_type": "test"})

        assert len(engine._fallback_learning_queue) == 0

    @pytest.mark.asyncio
    async def test_queue_handler_never_raises(self):
        """Handler exception → caught, no propagation."""
        engine = _make_dreaming_engine()
        # Force an error by making the method's internals fail
        with patch("probos.config.MAX_FALLBACK_QUEUE_SIZE", side_effect=Exception("config broken")):
            # Should not raise
            await engine.on_procedure_fallback_learning({"fallback_type": "test"})


# ==================================================================
# Test Class 6: TestFallbackFIXPromptAndEvolution
# ==================================================================


class TestFallbackFIXPromptAndEvolution:
    """Part 4: _FALLBACK_FIX_SYSTEM_PROMPT and evolve_fix_from_fallback()."""

    def test_fallback_fix_prompt_exists(self):
        """_FALLBACK_FIX_SYSTEM_PROMPT is a non-empty string."""
        from probos.cognitive.procedures import _FALLBACK_FIX_SYSTEM_PROMPT
        assert isinstance(_FALLBACK_FIX_SYSTEM_PROMPT, str)
        assert len(_FALLBACK_FIX_SYSTEM_PROMPT) > 100

    def test_fallback_fix_prompt_mentions_comparison(self):
        """Prompt contains 'compare' or 'diverge' language."""
        from probos.cognitive.procedures import _FALLBACK_FIX_SYSTEM_PROMPT
        text = _FALLBACK_FIX_SYSTEM_PROMPT.lower()
        assert "compare" in text or "diverge" in text

    def test_fallback_fix_prompt_mentions_llm_response(self):
        """Prompt references 'LLM' or 'successful'."""
        from probos.cognitive.procedures import _FALLBACK_FIX_SYSTEM_PROMPT
        text = _FALLBACK_FIX_SYSTEM_PROMPT.lower()
        assert "llm" in text or "successful" in text

    @pytest.mark.asyncio
    async def test_evolve_fix_from_fallback_basic(self):
        """Mock LLM returns valid JSON → EvolutionResult with FIX procedure."""
        import json
        from probos.cognitive.procedures import evolve_fix_from_fallback, EvolutionResult

        parent = _make_procedure()
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content=json.dumps({
                "name": "Fixed Procedure",
                "description": "Repaired version",
                "steps": [{"step_number": 1, "action": "Do it right"}],
                "preconditions": [],
                "postconditions": [],
                "change_summary": "Fixed step 1",
                "divergence_point": 1,
            })
        ))

        result = await evolve_fix_from_fallback(
            parent, "execution_failure", "LLM response text",
            "Replay failed", [], mock_llm,
        )

        assert result is not None
        assert isinstance(result, EvolutionResult)
        assert result.procedure.evolution_type == "FIX"

    @pytest.mark.asyncio
    async def test_evolve_fix_from_fallback_includes_divergence_point(self):
        """Response JSON with divergence_point → captured in change_summary."""
        import json
        from probos.cognitive.procedures import evolve_fix_from_fallback

        parent = _make_procedure()
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content=json.dumps({
                "name": "Fixed",
                "description": "test",
                "steps": [{"step_number": 1, "action": "fixed action"}],
                "preconditions": [],
                "postconditions": [],
                "change_summary": "Diverged at step 2",
                "divergence_point": 2,
            })
        ))

        result = await evolve_fix_from_fallback(
            parent, "quality_gate", "LLM did it right",
            "Effective rate too low", [], mock_llm,
        )

        assert result is not None
        assert result.change_summary == "Diverged at step 2"

    @pytest.mark.asyncio
    async def test_evolve_fix_from_fallback_generation_incremented(self):
        """New procedure has generation = parent.generation + 1."""
        import json
        from probos.cognitive.procedures import evolve_fix_from_fallback

        parent = _make_procedure(generation=3)
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content=json.dumps({
                "name": "Gen4", "description": "test",
                "steps": [{"step_number": 1, "action": "step"}],
                "preconditions": [], "postconditions": [],
                "change_summary": "test",
            })
        ))

        result = await evolve_fix_from_fallback(
            parent, "execution_failure", "resp", "reason", [], mock_llm,
        )

        assert result is not None
        assert result.procedure.generation == 4

    @pytest.mark.asyncio
    async def test_evolve_fix_from_fallback_parent_linked(self):
        """New procedure has parent_procedure_ids = [parent.id]."""
        import json
        from probos.cognitive.procedures import evolve_fix_from_fallback

        parent = _make_procedure(id="parent-xyz")
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content=json.dumps({
                "name": "Child", "description": "test",
                "steps": [{"step_number": 1, "action": "step"}],
                "preconditions": [], "postconditions": [],
                "change_summary": "test",
            })
        ))

        result = await evolve_fix_from_fallback(
            parent, "execution_failure", "resp", "reason", [], mock_llm,
        )

        assert result is not None
        assert result.procedure.parent_procedure_ids == ["parent-xyz"]

    @pytest.mark.asyncio
    async def test_evolve_fix_from_fallback_llm_decline(self):
        """LLM returns error JSON → returns None."""
        import json
        from probos.cognitive.procedures import evolve_fix_from_fallback

        parent = _make_procedure()
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content=json.dumps({"error": "no_repair_possible"})
        ))

        result = await evolve_fix_from_fallback(
            parent, "execution_failure", "resp", "reason", [], mock_llm,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_evolve_fix_from_fallback_llm_failure(self):
        """LLM raises → returns None."""
        from probos.cognitive.procedures import evolve_fix_from_fallback

        parent = _make_procedure()
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=Exception("LLM down"))

        result = await evolve_fix_from_fallback(
            parent, "execution_failure", "resp", "reason", [], mock_llm,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_evolve_fix_from_fallback_uses_episode_blocks(self):
        """Function calls _format_episode_blocks (DRY)."""
        import json
        from probos.cognitive.procedures import evolve_fix_from_fallback

        parent = _make_procedure()
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content=json.dumps({
                "name": "Fixed", "description": "test",
                "steps": [{"step_number": 1, "action": "step"}],
                "preconditions": [], "postconditions": [],
                "change_summary": "test",
            })
        ))

        # Create a fake episode
        episode = MagicMock()
        episode.id = "ep-1"
        episode.user_input = "test"
        episode.outcomes = {"success": True}
        episode.dag_summary = {}
        episode.reflection = None
        episode.agent_ids = ["agent-1"]

        with patch("probos.cognitive.procedures._format_episode_blocks", return_value="formatted") as mock_fmt:
            result = await evolve_fix_from_fallback(
                parent, "execution_failure", "resp", "reason", [episode], mock_llm,
            )

        mock_fmt.assert_called_once()

    @pytest.mark.asyncio
    async def test_evolve_fix_from_fallback_content_diff_generated(self):
        """EvolutionResult includes non-empty content_diff."""
        import json
        from probos.cognitive.procedures import evolve_fix_from_fallback

        parent = _make_procedure()
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content=json.dumps({
                "name": "Different Name", "description": "different desc",
                "steps": [{"step_number": 1, "action": "different action"}],
                "preconditions": [], "postconditions": [],
                "change_summary": "changed everything",
            })
        ))

        result = await evolve_fix_from_fallback(
            parent, "execution_failure", "resp", "reason", [], mock_llm,
        )

        assert result is not None
        assert len(result.content_diff) > 0

    @pytest.mark.asyncio
    async def test_evolve_fix_from_fallback_accepts_retry_hint(self):
        """Function accepts retry_hint kwarg."""
        import json
        from probos.cognitive.procedures import evolve_fix_from_fallback

        parent = _make_procedure()
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content=json.dumps({
                "name": "Fixed", "description": "test",
                "steps": [{"step_number": 1, "action": "step"}],
                "preconditions": [], "postconditions": [],
                "change_summary": "test",
            })
        ))

        result = await evolve_fix_from_fallback(
            parent, "execution_failure", "resp", "reason", [], mock_llm,
            retry_hint="Please output valid JSON",
        )

        assert result is not None
        # Verify retry_hint was included in prompt
        call_args = mock_llm.complete.call_args
        assert "RETRY HINT" in call_args[0][0].prompt


# ==================================================================
# Test Class 7: TestDreamStep7d
# ==================================================================


class TestDreamStep7d:
    """Part 5: _process_fallback_learning() behavior."""

    @pytest.mark.asyncio
    async def test_step7d_processes_queue(self):
        """Non-empty queue → processes entries."""
        import json

        engine = _make_dreaming_engine()
        proc = _make_procedure()
        engine._procedure_store.get.return_value = proc
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[])

        engine._fallback_learning_queue = [
            {"procedure_id": proc.id, "fallback_type": "quality_gate",
             "llm_response": "test", "rejection_reason": "low rate", "intent_type": "test"}
        ]

        with patch("probos.cognitive.dreaming.evolve_with_retry", new_callable=AsyncMock, return_value=None):
            stats = await engine._process_fallback_learning()

        assert stats["processed"] == 1

    @pytest.mark.asyncio
    async def test_step7d_empty_queue_returns_zero(self):
        """Empty queue → returns zeros."""
        engine = _make_dreaming_engine()
        stats = await engine._process_fallback_learning()
        assert stats["evolved"] == 0
        assert stats["processed"] == 0

    @pytest.mark.asyncio
    async def test_step7d_groups_by_procedure_id(self):
        """Multiple events for same procedure → processed once."""
        engine = _make_dreaming_engine()
        proc = _make_procedure()
        engine._procedure_store.get.return_value = proc
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[])

        engine._fallback_learning_queue = [
            {"procedure_id": proc.id, "fallback_type": "quality_gate", "llm_response": "old", "rejection_reason": "x", "intent_type": "t"},
            {"procedure_id": proc.id, "fallback_type": "quality_gate", "llm_response": "newest", "rejection_reason": "y", "intent_type": "t"},
        ]

        calls = []

        async def _track_retry(fn, *args, **kwargs):
            calls.append(args)
            return None

        with patch("probos.cognitive.dreaming.evolve_with_retry", side_effect=_track_retry):
            stats = await engine._process_fallback_learning()

        assert stats["processed"] == 2
        assert len(calls) == 1  # Grouped — only one evolution call

    @pytest.mark.asyncio
    async def test_step7d_respects_anti_loop_guard(self):
        """Procedure in _addressed_degradations within cooldown → skipped."""
        engine = _make_dreaming_engine()
        proc = _make_procedure()
        engine._addressed_degradations[proc.id] = time.time()  # Just now

        engine._fallback_learning_queue = [
            {"procedure_id": proc.id, "fallback_type": "quality_gate", "llm_response": "test", "rejection_reason": "x", "intent_type": "t"}
        ]

        stats = await engine._process_fallback_learning()

        assert stats["skipped_cooldown"] == 1
        assert stats["evolved"] == 0

    @pytest.mark.asyncio
    async def test_step7d_execution_failure_deactivates_parent(self):
        """fallback_type='execution_failure' + evolution succeeds → parent deactivated."""
        from probos.cognitive.procedures import EvolutionResult

        engine = _make_dreaming_engine()
        proc = _make_procedure()
        engine._procedure_store.get.return_value = proc
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[])

        evolved = _make_procedure(id="evolved-1", name="Fixed")
        evo_result = EvolutionResult(procedure=evolved, content_diff="diff", change_summary="fixed")

        engine._fallback_learning_queue = [
            {"procedure_id": proc.id, "fallback_type": "execution_failure",
             "llm_response": "test", "rejection_reason": "failed", "intent_type": "t"}
        ]

        with patch("probos.cognitive.dreaming.evolve_with_retry", new_callable=AsyncMock, return_value=evo_result):
            stats = await engine._process_fallback_learning()

        engine._procedure_store.deactivate.assert_called_once()
        assert stats["evolved"] == 1

    @pytest.mark.asyncio
    async def test_step7d_near_miss_keeps_parent_active(self):
        """fallback_type='quality_gate' + evolution succeeds → parent stays active."""
        from probos.cognitive.procedures import EvolutionResult

        engine = _make_dreaming_engine()
        proc = _make_procedure()
        engine._procedure_store.get.return_value = proc
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[])

        evolved = _make_procedure(id="evolved-2", name="Variant")
        evo_result = EvolutionResult(procedure=evolved, content_diff="diff", change_summary="improved")

        engine._fallback_learning_queue = [
            {"procedure_id": proc.id, "fallback_type": "quality_gate",
             "llm_response": "test", "rejection_reason": "low rate", "intent_type": "t"}
        ]

        with patch("probos.cognitive.dreaming.evolve_with_retry", new_callable=AsyncMock, return_value=evo_result):
            stats = await engine._process_fallback_learning()

        engine._procedure_store.deactivate.assert_not_called()
        assert stats["evolved"] == 1

    @pytest.mark.asyncio
    async def test_step7d_negative_veto_flags_candidate(self):
        """fallback_type='negative_veto' → added to _extraction_candidates, no evolution."""
        engine = _make_dreaming_engine()

        engine._fallback_learning_queue = [
            {"procedure_id": "neg-1", "fallback_type": "negative_veto",
             "llm_response": "test", "rejection_reason": "blocked", "intent_type": "test_intent"}
        ]

        stats = await engine._process_fallback_learning()

        assert stats["negative_veto_flagged"] == 1
        assert "test_intent" in engine._extraction_candidates

    @pytest.mark.asyncio
    async def test_step7d_saves_evolved_procedure(self):
        """Evolution succeeds → saved to procedure_store with content_diff."""
        from probos.cognitive.procedures import EvolutionResult

        engine = _make_dreaming_engine()
        proc = _make_procedure()
        engine._procedure_store.get.return_value = proc
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[])

        evolved = _make_procedure(id="evolved-3")
        evo_result = EvolutionResult(procedure=evolved, content_diff="test diff", change_summary="test summary")

        engine._fallback_learning_queue = [
            {"procedure_id": proc.id, "fallback_type": "quality_gate",
             "llm_response": "test", "rejection_reason": "low", "intent_type": "t"}
        ]

        with patch("probos.cognitive.dreaming.evolve_with_retry", new_callable=AsyncMock, return_value=evo_result):
            await engine._process_fallback_learning()

        engine._procedure_store.save.assert_called_once()
        call_kwargs = engine._procedure_store.save.call_args
        assert call_kwargs[1].get("content_diff") == "test diff" or call_kwargs[0][0] == evolved

    @pytest.mark.asyncio
    async def test_step7d_one_failure_continues(self):
        """First procedure raises → second still processed."""
        engine = _make_dreaming_engine()
        proc1 = _make_procedure(id="p1")
        proc2 = _make_procedure(id="p2")

        call_count = [0]

        async def _get_proc(pid):
            if pid == "p1":
                raise Exception("load failed")
            return proc2

        engine._procedure_store.get = AsyncMock(side_effect=_get_proc)
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[])

        engine._fallback_learning_queue = [
            {"procedure_id": "p1", "fallback_type": "quality_gate", "llm_response": "t", "rejection_reason": "x", "intent_type": "t"},
            {"procedure_id": "p2", "fallback_type": "quality_gate", "llm_response": "t", "rejection_reason": "x", "intent_type": "t"},
        ]

        with patch("probos.cognitive.dreaming.evolve_with_retry", new_callable=AsyncMock, return_value=None):
            stats = await engine._process_fallback_learning()

        # Should have processed both (p1 failed, p2 continued)
        assert stats["processed"] == 2

    @pytest.mark.asyncio
    async def test_step7d_clears_queue_after_processing(self):
        """After processing, _fallback_learning_queue is empty."""
        engine = _make_dreaming_engine()
        engine._fallback_learning_queue = [
            {"procedure_id": "p1", "fallback_type": "quality_gate", "llm_response": "t", "rejection_reason": "x", "intent_type": "t"}
        ]

        engine._procedure_store.get.return_value = _make_procedure()
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[])

        with patch("probos.cognitive.dreaming.evolve_with_retry", new_callable=AsyncMock, return_value=None):
            await engine._process_fallback_learning()

        assert len(engine._fallback_learning_queue) == 0

    @pytest.mark.asyncio
    async def test_step7d_uses_evolve_with_retry(self):
        """Evolution called via evolve_with_retry() wrapper."""
        engine = _make_dreaming_engine()
        proc = _make_procedure()
        engine._procedure_store.get.return_value = proc
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[])

        engine._fallback_learning_queue = [
            {"procedure_id": proc.id, "fallback_type": "quality_gate",
             "llm_response": "t", "rejection_reason": "x", "intent_type": "t"}
        ]

        with patch("probos.cognitive.dreaming.evolve_with_retry", new_callable=AsyncMock, return_value=None) as mock_retry:
            await engine._process_fallback_learning()

        mock_retry.assert_called_once()

    @pytest.mark.asyncio
    async def test_step7d_no_store_returns_zeros(self):
        """procedure_store is None → returns zeros dict."""
        engine = _make_dreaming_engine(procedure_store=None)
        engine._procedure_store = None
        engine._fallback_learning_queue = [{"procedure_id": "p1"}]

        stats = await engine._process_fallback_learning()
        assert stats["evolved"] == 0
        assert stats["processed"] == 0


# ==================================================================
# Test Class 8: TestDreamCycleIntegration
# ==================================================================


class TestDreamCycleIntegration:
    """Part 5b/6: Dream cycle wiring and DreamReport fields."""

    @pytest.mark.asyncio
    async def test_step7d_runs_after_step7c(self):
        """dream_cycle() calls _process_fallback_learning()."""
        engine = _make_dreaming_engine()
        engine.episodic_memory.recall = AsyncMock(return_value=[])
        engine.episodic_memory.get_stats = AsyncMock(return_value={"total": 0})

        with patch.object(engine, 'micro_dream', new_callable=AsyncMock, return_value={
            "episodes_replayed": 0, "weights_strengthened": 0, "weights_weakened": 0,
        }):
            with patch.object(engine, '_process_fallback_learning', new_callable=AsyncMock, return_value={"evolved": 0, "processed": 0}) as mock_step7d:
                report = await engine.dream_cycle()

        mock_step7d.assert_called_once()

    @pytest.mark.asyncio
    async def test_step7d_failure_nonfatal_in_dream_cycle(self):
        """Step 7d raises → dream cycle continues."""
        engine = _make_dreaming_engine()
        engine.episodic_memory.recall = AsyncMock(return_value=[])
        engine.episodic_memory.get_stats = AsyncMock(return_value={"total": 0})

        with patch.object(engine, 'micro_dream', new_callable=AsyncMock, return_value={
            "episodes_replayed": 0, "weights_strengthened": 0, "weights_weakened": 0,
        }):
            with patch.object(engine, '_process_fallback_learning', new_callable=AsyncMock, side_effect=Exception("7d boom")):
                report = await engine.dream_cycle()

        # Should complete without crash
        assert report is not None

    def test_dreamreport_fallback_fields(self):
        """DreamReport has fallback_evolutions and fallback_events_processed with default 0."""
        from probos.types import DreamReport
        report = DreamReport()
        assert report.fallback_evolutions == 0
        assert report.fallback_events_processed == 0

    @pytest.mark.asyncio
    async def test_dreamreport_populated_from_step7d(self):
        """Step 7d results flow into DreamReport fields."""
        engine = _make_dreaming_engine()
        engine.episodic_memory.recall = AsyncMock(return_value=[])
        engine.episodic_memory.get_stats = AsyncMock(return_value={"total": 0})

        with patch.object(engine, 'micro_dream', new_callable=AsyncMock, return_value={
            "episodes_replayed": 0, "weights_strengthened": 0, "weights_weakened": 0,
        }):
            with patch.object(engine, '_process_fallback_learning', new_callable=AsyncMock,
                              return_value={"evolved": 2, "processed": 5, "skipped_cooldown": 1, "negative_veto_flagged": 0}):
                report = await engine.dream_cycle()

        assert report.fallback_evolutions == 2
        assert report.fallback_events_processed == 5


# ==================================================================
# Test Class 9: TestEndToEnd
# ==================================================================


class TestEndToEnd:
    """Integration tests for the full fallback learning pipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline_execution_failure(self):
        """Full pipeline: procedure matched → replay → act fails → LLM recovery → event."""
        from probos.events import EventType

        agent = _make_cognitive_agent()
        store = _make_store_mock()
        proc = _make_procedure()
        store.find_matching.side_effect = [[], [{"id": proc.id, "name": proc.name, "score": 0.9}]]
        store.get.return_value = proc
        store.get_quality_metrics.return_value = {}

        runtime = MagicMock()
        runtime.procedure_store = store
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        call_count = [0]

        async def _act_fails_first(decision):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"success": False, "error": "replay failed"}
            return {"success": True, "result": "recovered"}

        agent.act = _act_fails_first
        agent._run_llm_fallback = AsyncMock(return_value={"action": "execute", "llm_output": "LLM fixed it"})

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock,
                          return_value={"intent": "test_intent", "params": {"message": "test"}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                result = await agent.handle_intent(intent)

        assert result.success is True
        # Verify fallback learning event was emitted
        calls = runtime._emit_event.call_args_list
        fallback_calls = [c for c in calls if c[0][0] == EventType.PROCEDURE_FALLBACK_LEARNING]
        assert len(fallback_calls) == 1
        assert fallback_calls[0][0][1]["fallback_type"] == "execution_failure"

    @pytest.mark.asyncio
    async def test_full_pipeline_quality_gate_near_miss(self):
        """Full pipeline: quality gate rejects → LLM succeeds → event emitted."""
        from probos.events import EventType

        agent = _make_cognitive_agent()
        store = _make_store_mock()
        # Return match with poor quality
        store.find_matching.return_value = [{"id": "p1", "name": "BadProc", "score": 0.9}]
        store.get_quality_metrics.return_value = {"total_selections": 10, "effective_rate": 0.1}

        runtime = MagicMock()
        runtime.procedure_store = store
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        # Mock LLM call path
        agent._llm_client.complete = AsyncMock(return_value=MagicMock(
            content="LLM response", tier="standard", model="test", error=None,
            prompt_tokens=10, completion_tokens=20, tokens_used=30,
        ))

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock,
                          return_value={"intent": "test_intent", "params": {"message": "test"}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                result = await agent.handle_intent(intent)

        assert result.success is True
        calls = runtime._emit_event.call_args_list
        fallback_calls = [c for c in calls if c[0][0] == EventType.PROCEDURE_FALLBACK_LEARNING]
        assert len(fallback_calls) == 1
        assert fallback_calls[0][0][1]["fallback_type"] == "quality_gate"

    @pytest.mark.asyncio
    async def test_full_pipeline_score_threshold_near_miss(self):
        """Full pipeline: score below threshold → LLM succeeds → event with comparison."""
        from probos.events import EventType

        agent = _make_cognitive_agent()
        store = _make_store_mock()
        # Return match with low score
        store.find_matching.return_value = [{"id": "p2", "name": "LowScore", "score": 0.1}]

        runtime = MagicMock()
        runtime.procedure_store = store
        runtime.cognitive_journal = None
        runtime._emit_event = MagicMock()
        agent._runtime = runtime

        agent._llm_client.complete = AsyncMock(return_value=MagicMock(
            content="LLM response", tier="standard", model="test", error=None,
            prompt_tokens=10, completion_tokens=20, tokens_used=30,
        ))

        intent = _make_intent()
        with patch.object(agent, '_recall_relevant_memories', new_callable=AsyncMock,
                          return_value={"intent": "test_intent", "params": {"message": "test"}}):
            with patch.object(agent, '_store_action_episode', new_callable=AsyncMock):
                result = await agent.handle_intent(intent)

        assert result.success is True
        calls = runtime._emit_event.call_args_list
        fallback_calls = [c for c in calls if c[0][0] == EventType.PROCEDURE_FALLBACK_LEARNING]
        assert len(fallback_calls) == 1
        assert fallback_calls[0][0][1]["fallback_type"] == "score_threshold"
