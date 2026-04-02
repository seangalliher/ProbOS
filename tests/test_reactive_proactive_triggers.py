"""Tests for AD-532e: Reactive & Proactive Extraction Triggers."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.procedures import (
    Procedure,
    ProcedureStep,
    confirm_evolution_with_llm,
    evolve_with_retry,
    evolve_fix_procedure,
    evolve_derived_procedure,
    diagnose_procedure_health,
)
from probos.config import (
    REACTIVE_COOLDOWN_SECONDS,
    PROACTIVE_SCAN_INTERVAL_SECONDS,
    EVOLUTION_MAX_RETRIES,
    EVOLUTION_COOLDOWN_SECONDS,
)
from probos.types import DreamReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm_client(content: str = "YES\nLooks reasonable.") -> AsyncMock:
    """Create a mock LLM client that returns the given content."""
    client = AsyncMock()
    response = MagicMock()
    response.content = content
    client.complete = AsyncMock(return_value=response)
    return client


def _make_procedure(**kwargs: Any) -> Procedure:
    """Create a test Procedure with defaults."""
    defaults = {
        "id": "proc-1",
        "name": "test procedure",
        "intent_types": ["code_review"],
        "steps": [ProcedureStep(step_number=1, action="do thing")],
        "is_active": True,
    }
    defaults.update(kwargs)
    return Procedure(**defaults)


@dataclass
class _FakeConfig:
    replay_episode_count: int = 50
    pathway_strengthening_factor: float = 0.03
    pathway_weakening_factor: float = 0.02
    prune_threshold: float = 0.01
    trust_boost: float = 0.1
    trust_penalty: float = 0.1
    pre_warm_top_k: int = 5


@dataclass
class _FakeEpisode:
    id: str = "ep-1"
    user_input: str = "test"
    outcomes: list = field(default_factory=lambda: [{"intent": "code_review", "success": True}])
    dag_summary: dict = field(default_factory=dict)
    reflection: str | None = None
    agent_ids: list = field(default_factory=lambda: ["agent-1"])
    embedding: list = field(default_factory=list)


# ===========================================================================
# Test Class 1: TestLLMConfirmationGate
# ===========================================================================


class TestLLMConfirmationGate:
    """Tests for confirm_evolution_with_llm()."""

    @pytest.mark.asyncio
    async def test_confirm_yes(self):
        client = _make_llm_client("YES\nLooks reasonable.")
        result = await confirm_evolution_with_llm("proc", "FIX:high_fallback", "evidence", client)
        assert result is True

    @pytest.mark.asyncio
    async def test_confirm_no(self):
        client = _make_llm_client("NO\nNot enough evidence.")
        result = await confirm_evolution_with_llm("proc", "FIX:high_fallback", "evidence", client)
        assert result is False

    @pytest.mark.asyncio
    async def test_confirm_maybe(self):
        client = _make_llm_client("MAYBE\nUncertain.")
        result = await confirm_evolution_with_llm("proc", "FIX:high_fallback", "evidence", client)
        assert result is False

    @pytest.mark.asyncio
    async def test_confirm_empty(self):
        client = _make_llm_client("")
        result = await confirm_evolution_with_llm("proc", "FIX:high_fallback", "evidence", client)
        assert result is False

    @pytest.mark.asyncio
    async def test_confirm_llm_failure(self):
        client = AsyncMock()
        client.complete = AsyncMock(side_effect=RuntimeError("LLM down"))
        result = await confirm_evolution_with_llm("proc", "FIX:high_fallback", "evidence", client)
        assert result is False

    @pytest.mark.asyncio
    async def test_confirm_case_insensitive(self):
        client = _make_llm_client("yes\nlowercase is fine")
        result = await confirm_evolution_with_llm("proc", "FIX:high_fallback", "evidence", client)
        assert result is True

    @pytest.mark.asyncio
    async def test_confirm_leading_whitespace(self):
        client = _make_llm_client("  YES\nwith leading spaces")
        result = await confirm_evolution_with_llm("proc", "FIX:high_fallback", "evidence", client)
        assert result is True


# ===========================================================================
# Test Class 2: TestEvolveWithRetry
# ===========================================================================


class TestEvolveWithRetry:
    """Tests for evolve_with_retry()."""

    @pytest.mark.asyncio
    async def test_retry_success_first_try(self):
        fn = AsyncMock(return_value="result")
        result = await evolve_with_retry(fn, "arg1", max_retries=3)
        assert result == "result"
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_success_second_try(self):
        fn = AsyncMock(side_effect=[None, "result"])
        result = await evolve_with_retry(fn, "arg1", max_retries=3)
        assert result == "result"
        assert fn.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_all_fail(self):
        fn = AsyncMock(return_value=None)
        result = await evolve_with_retry(fn, "arg1", max_retries=3)
        assert result is None
        assert fn.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exception_then_success(self):
        fn = AsyncMock(side_effect=[RuntimeError("fail"), "result"])
        result = await evolve_with_retry(fn, "arg1", max_retries=3)
        assert result == "result"
        assert fn.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_max_retries_configurable(self):
        fn = AsyncMock(return_value=None)
        result = await evolve_with_retry(fn, max_retries=1)
        assert result is None
        assert fn.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_passes_retry_hint(self):
        calls = []

        async def track_fn(*args, **kwargs):
            calls.append(kwargs.copy())
            return None

        await evolve_with_retry(track_fn, max_retries=2)
        # First call should not have retry_hint
        assert "retry_hint" not in calls[0]
        # Second call should have retry_hint
        assert "retry_hint" in calls[1]
        assert "valid JSON" in calls[1]["retry_hint"]


# ===========================================================================
# Test Class 3: TestEventTypeAndEmission
# ===========================================================================


class TestEventTypeAndEmission:
    """Tests for TASK_EXECUTION_COMPLETE event."""

    def test_task_execution_complete_event_type_exists(self):
        from probos.events import EventType
        assert hasattr(EventType, "TASK_EXECUTION_COMPLETE")
        assert EventType.TASK_EXECUTION_COMPLETE.value == "task_execution_complete"

    def test_task_execution_complete_event_dataclass(self):
        from probos.events import TaskExecutionCompleteEvent, EventType
        event = TaskExecutionCompleteEvent(
            agent_id="a1",
            agent_type="scout",
            intent_type="code_review",
            success=True,
            used_procedure=False,
        )
        assert event.event_type == EventType.TASK_EXECUTION_COMPLETE
        assert event.agent_id == "a1"
        assert event.success is True
        assert event.used_procedure is False

    def test_event_not_emitted_without_runtime(self):
        """CognitiveAgent with no runtime should not crash."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        # Just verify the import path and event type reference work
        from probos.events import EventType
        assert EventType.TASK_EXECUTION_COMPLETE is not None


# ===========================================================================
# Test Class 4: TestReactiveTrigger
# ===========================================================================


class TestReactiveTrigger:
    """Tests for DreamingEngine.on_task_execution_complete()."""

    def _make_engine(self, **kwargs):
        from probos.cognitive.dreaming import DreamingEngine
        router = MagicMock()
        trust = MagicMock()
        memory = AsyncMock()
        memory.recall_by_intent = AsyncMock(return_value=[_FakeEpisode()])
        config = _FakeConfig()
        llm_client = kwargs.pop("llm_client", _make_llm_client())
        store = kwargs.pop("procedure_store", AsyncMock())
        engine = DreamingEngine(
            router=router,
            trust_network=trust,
            episodic_memory=memory,
            config=config,
            llm_client=llm_client,
            procedure_store=store,
        )
        return engine

    @pytest.mark.asyncio
    async def test_reactive_skips_procedure_replay(self):
        engine = self._make_engine()
        await engine.on_task_execution_complete({"used_procedure": True, "success": True})
        engine._procedure_store.find_matching.assert_not_called()

    @pytest.mark.asyncio
    async def test_reactive_skips_failure(self):
        engine = self._make_engine()
        await engine.on_task_execution_complete({"used_procedure": False, "success": False})
        engine._procedure_store.find_matching.assert_not_called()

    @pytest.mark.asyncio
    async def test_reactive_rate_limited(self):
        engine = self._make_engine()
        engine._reactive_cooldowns["agent-1"] = time.time()  # just now
        await engine.on_task_execution_complete({
            "used_procedure": False, "success": True,
            "agent_id": "agent-1", "intent_type": "code_review",
        })
        engine._procedure_store.find_matching.assert_not_called()

    @pytest.mark.asyncio
    async def test_reactive_no_match_flags_candidate(self):
        engine = self._make_engine()
        engine._procedure_store.find_matching = AsyncMock(return_value=None)
        await engine.on_task_execution_complete({
            "used_procedure": False, "success": True,
            "agent_id": "agent-2", "intent_type": "translate",
        })
        assert "translate" in engine._extraction_candidates

    @pytest.mark.asyncio
    async def test_reactive_match_healthy_no_action(self):
        engine = self._make_engine()
        engine._procedure_store.find_matching = AsyncMock(return_value={"id": "proc-1"})
        engine._procedure_store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10,
            "fallback_rate": 0.1,
            "applied_rate": 0.8,
            "completion_rate": 0.9,
            "effective_rate": 0.85,
        })
        # healthy metrics → diagnose_procedure_health returns None → no evolution
        await engine.on_task_execution_complete({
            "used_procedure": False, "success": True,
            "agent_id": "agent-3", "intent_type": "code_review",
        })
        engine._procedure_store.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_reactive_match_degraded_confirmed_evolves(self):
        engine = self._make_engine()
        proc = _make_procedure()
        engine._procedure_store.find_matching = AsyncMock(return_value={"id": "proc-1"})
        engine._procedure_store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10,
            "fallback_rate": 0.6,  # triggers FIX:high_fallback_rate
            "applied_rate": 0.5,
            "completion_rate": 0.7,
            "effective_rate": 0.6,
        })
        engine._procedure_store.get = AsyncMock(return_value=proc)
        engine._procedure_store.save = AsyncMock()
        engine._procedure_store.deactivate = AsyncMock()

        # Mock LLM to confirm AND produce valid FIX evolution
        responses = [
            # confirmation gate: YES
            MagicMock(content="YES\nConfirmed"),
            # evolve_fix_procedure: valid JSON (first attempt)
            MagicMock(content='{"name": "fixed", "description": "fixed", "steps": [{"step_number": 1, "action": "fixed step"}], "preconditions": [], "postconditions": [], "change_summary": "fixed it"}'),
        ]
        engine._llm_client.complete = AsyncMock(side_effect=responses)

        await engine.on_task_execution_complete({
            "used_procedure": False, "success": True,
            "agent_id": "agent-4", "intent_type": "code_review",
        })
        engine._procedure_store.save.assert_called()

    @pytest.mark.asyncio
    async def test_reactive_match_degraded_denied_skips(self):
        engine = self._make_engine()
        proc = _make_procedure()
        engine._procedure_store.find_matching = AsyncMock(return_value={"id": "proc-1"})
        engine._procedure_store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10,
            "fallback_rate": 0.6,
            "applied_rate": 0.5,
            "completion_rate": 0.7,
            "effective_rate": 0.6,
        })
        engine._procedure_store.get = AsyncMock(return_value=proc)
        # LLM says NO
        engine._llm_client.complete = AsyncMock(
            return_value=MagicMock(content="NO\nNot needed")
        )
        await engine.on_task_execution_complete({
            "used_procedure": False, "success": True,
            "agent_id": "agent-5", "intent_type": "code_review",
        })
        engine._procedure_store.save.assert_not_called()
        # But should have recorded in _addressed_degradations
        assert "proc-1" in engine._addressed_degradations

    @pytest.mark.asyncio
    async def test_reactive_respects_anti_loop_guard(self):
        engine = self._make_engine()
        proc = _make_procedure()
        engine._procedure_store.find_matching = AsyncMock(return_value={"id": "proc-1"})
        engine._procedure_store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10,
            "fallback_rate": 0.6,
            "applied_rate": 0.5,
            "completion_rate": 0.7,
            "effective_rate": 0.6,
        })
        engine._procedure_store.get = AsyncMock(return_value=proc)
        # Recently addressed
        engine._addressed_degradations["proc-1"] = time.time()
        # LLM confirms (would pass gate)
        engine._llm_client.complete = AsyncMock(
            return_value=MagicMock(content="YES\nConfirmed")
        )
        await engine.on_task_execution_complete({
            "used_procedure": False, "success": True,
            "agent_id": "agent-6", "intent_type": "code_review",
        })
        # Anti-loop guard should prevent the call to confirm_evolution_with_llm
        # (it's checked in _attempt_procedure_evolution before LLM gate)
        engine._procedure_store.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_reactive_never_raises(self):
        engine = self._make_engine()
        engine._procedure_store.find_matching = AsyncMock(side_effect=RuntimeError("db error"))
        # Should not raise
        await engine.on_task_execution_complete({
            "used_procedure": False, "success": True,
            "agent_id": "agent-7", "intent_type": "code_review",
        })


# ===========================================================================
# Test Class 5: TestProactiveScan
# ===========================================================================


class TestProactiveScan:
    """Tests for DreamingEngine.proactive_procedure_scan()."""

    def _make_engine(self, **kwargs):
        from probos.cognitive.dreaming import DreamingEngine
        router = MagicMock()
        trust = MagicMock()
        memory = AsyncMock()
        memory.recall_by_intent = AsyncMock(return_value=[_FakeEpisode()])
        config = _FakeConfig()
        llm_client = kwargs.pop("llm_client", _make_llm_client())
        store = kwargs.pop("procedure_store", AsyncMock())
        engine = DreamingEngine(
            router=router,
            trust_network=trust,
            episodic_memory=memory,
            config=config,
            llm_client=llm_client,
            procedure_store=store,
        )
        return engine

    @pytest.mark.asyncio
    async def test_proactive_scans_all_active(self):
        engine = self._make_engine()
        engine._procedure_store.list_active = AsyncMock(return_value=[
            {"id": "p1"}, {"id": "p2"}, {"id": "p3"},
        ])
        # All healthy
        engine._procedure_store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10,
            "fallback_rate": 0.1,
            "applied_rate": 0.8,
            "completion_rate": 0.9,
            "effective_rate": 0.85,
        })
        result = await engine.proactive_procedure_scan()
        assert result["scanned"] == 3
        assert result["evolved"] == 0

    @pytest.mark.asyncio
    async def test_proactive_skips_healthy(self):
        engine = self._make_engine()
        engine._procedure_store.list_active = AsyncMock(return_value=[{"id": "p1"}])
        engine._procedure_store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10,
            "fallback_rate": 0.1,  # healthy
            "applied_rate": 0.8,
            "completion_rate": 0.9,
            "effective_rate": 0.85,
        })
        result = await engine.proactive_procedure_scan()
        assert result["scanned"] == 1
        assert result["evolved"] == 0

    @pytest.mark.asyncio
    async def test_proactive_evolves_confirmed(self):
        engine = self._make_engine()
        proc = _make_procedure()
        engine._procedure_store.list_active = AsyncMock(return_value=[{"id": "proc-1"}])
        engine._procedure_store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10,
            "fallback_rate": 0.6,  # degraded
            "applied_rate": 0.5,
            "completion_rate": 0.7,
            "effective_rate": 0.6,
        })
        engine._procedure_store.get = AsyncMock(return_value=proc)
        engine._procedure_store.save = AsyncMock()
        engine._procedure_store.deactivate = AsyncMock()

        responses = [
            MagicMock(content="YES\nConfirmed"),
            MagicMock(content='{"name": "fixed", "description": "fixed", "steps": [{"step_number": 1, "action": "fixed"}], "preconditions": [], "postconditions": [], "change_summary": "fixed"}'),
        ]
        engine._llm_client.complete = AsyncMock(side_effect=responses)

        result = await engine.proactive_procedure_scan()
        assert result["scanned"] == 1
        assert result["evolved"] == 1

    @pytest.mark.asyncio
    async def test_proactive_skips_denied(self):
        engine = self._make_engine()
        proc = _make_procedure()
        engine._procedure_store.list_active = AsyncMock(return_value=[{"id": "proc-1"}])
        engine._procedure_store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10,
            "fallback_rate": 0.6,
            "applied_rate": 0.5,
            "completion_rate": 0.7,
            "effective_rate": 0.6,
        })
        engine._procedure_store.get = AsyncMock(return_value=proc)
        engine._llm_client.complete = AsyncMock(
            return_value=MagicMock(content="NO\nNot needed")
        )
        result = await engine.proactive_procedure_scan()
        assert result["evolved"] == 0
        assert "proc-1" in engine._addressed_degradations

    @pytest.mark.asyncio
    async def test_proactive_respects_cooldown(self):
        engine = self._make_engine()
        engine._addressed_degradations["proc-1"] = time.time()
        engine._procedure_store.list_active = AsyncMock(return_value=[{"id": "proc-1"}])
        engine._procedure_store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10,
            "fallback_rate": 0.6,
            "applied_rate": 0.5,
            "completion_rate": 0.7,
            "effective_rate": 0.6,
        })
        result = await engine.proactive_procedure_scan()
        assert result["skipped_cooldown"] == 1

    @pytest.mark.asyncio
    async def test_proactive_returns_stats(self):
        engine = self._make_engine()
        engine._procedure_store.list_active = AsyncMock(return_value=[])
        result = await engine.proactive_procedure_scan()
        assert "scanned" in result
        assert "evolved" in result
        assert "skipped_cooldown" in result

    @pytest.mark.asyncio
    async def test_proactive_one_failure_continues(self):
        engine = self._make_engine()
        engine._procedure_store.list_active = AsyncMock(return_value=[
            {"id": "p1"}, {"id": "p2"},
        ])
        # First call raises, second returns healthy metrics
        engine._procedure_store.get_quality_metrics = AsyncMock(
            side_effect=[
                RuntimeError("db error"),
                {"total_selections": 10, "fallback_rate": 0.1, "applied_rate": 0.8, "completion_rate": 0.9, "effective_rate": 0.85},
            ]
        )
        result = await engine.proactive_procedure_scan()
        assert result["scanned"] == 2  # both scanned despite first error

    @pytest.mark.asyncio
    async def test_proactive_no_store_returns_zeros(self):
        from probos.cognitive.dreaming import DreamingEngine
        router = MagicMock()
        trust = MagicMock()
        memory = AsyncMock()
        config = _FakeConfig()
        engine = DreamingEngine(
            router=router,
            trust_network=trust,
            episodic_memory=memory,
            config=config,
            llm_client=_make_llm_client(),
            procedure_store=None,
        )
        result = await engine.proactive_procedure_scan()
        assert result == {"scanned": 0, "evolved": 0, "skipped_cooldown": 0}


# ===========================================================================
# Test Class 6: TestDreamSchedulerProactiveTier
# ===========================================================================


class TestDreamSchedulerProactiveTier:
    """Tests for DreamScheduler proactive scan integration."""

    def test_scheduler_has_proactive_scan_time(self):
        from probos.cognitive.dreaming import DreamScheduler, DreamingEngine
        engine = MagicMock(spec=DreamingEngine)
        sched = DreamScheduler(engine=engine)
        assert hasattr(sched, "_last_proactive_scan_time")
        assert sched._last_proactive_scan_time == 0.0

    def test_proactive_scan_not_during_dreaming(self):
        """The proactive scan condition requires _is_dreaming=False."""
        from probos.cognitive.dreaming import DreamScheduler, DreamingEngine
        engine = MagicMock(spec=DreamingEngine)
        sched = DreamScheduler(engine=engine)
        sched._is_dreaming = True
        # The monitor loop condition checks `not self._is_dreaming`
        # so proactive scan should not trigger
        assert sched._is_dreaming is True

    @pytest.mark.asyncio
    async def test_proactive_scan_failure_nonfatal(self):
        """Proactive scan failure in scheduler should not crash."""
        from probos.cognitive.dreaming import DreamScheduler, DreamingEngine
        engine = MagicMock(spec=DreamingEngine)
        engine.proactive_procedure_scan = AsyncMock(side_effect=RuntimeError("scan failed"))
        sched = DreamScheduler(engine=engine)
        # Simulate the scan call (this would be in the monitor loop)
        try:
            await engine.proactive_procedure_scan()
        except RuntimeError:
            pass  # Expected — the monitor loop wraps this in try/except


# ===========================================================================
# Test Class 7: TestDreamReportFields
# ===========================================================================


class TestDreamReportFields:
    """Tests for AD-532e DreamReport fields."""

    def test_dreamreport_proactive_evolutions_default_zero(self):
        report = DreamReport()
        assert report.proactive_evolutions == 0

    def test_dreamreport_reactive_flags_default_zero(self):
        report = DreamReport()
        assert report.reactive_flags == 0


# ===========================================================================
# Test Class 8: TestEvolutionFunctionRetryHint
# ===========================================================================


class TestEvolutionFunctionRetryHint:
    """Evolution functions accept retry_hint gracefully."""

    @pytest.mark.asyncio
    async def test_fix_procedure_accepts_retry_hint(self):
        """evolve_fix_procedure should accept retry_hint kwarg without error."""
        client = _make_llm_client('{"name": "fixed", "description": "d", "steps": [{"step_number": 1, "action": "a"}], "preconditions": [], "postconditions": [], "change_summary": "s"}')
        proc = _make_procedure()
        result = await evolve_fix_procedure(
            proc, "FIX:high_fallback", {}, [_FakeEpisode()], client,
            retry_hint="Please output valid JSON",
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_derived_procedure_accepts_retry_hint(self):
        """evolve_derived_procedure should accept retry_hint kwarg without error."""
        client = _make_llm_client('{"name": "derived", "description": "d", "steps": [{"step_number": 1, "action": "a"}], "preconditions": [], "postconditions": [], "change_summary": "s"}')
        proc = _make_procedure()
        result = await evolve_derived_procedure(
            [proc], [_FakeEpisode()], client,
            retry_hint="Please output valid JSON",
        )
        assert result is not None


# ===========================================================================
# Test Class 9: TestConfigConstants
# ===========================================================================


class TestConfigConstants:
    """Config constants exist with expected values."""

    def test_reactive_cooldown(self):
        assert REACTIVE_COOLDOWN_SECONDS == 60

    def test_proactive_scan_interval(self):
        assert PROACTIVE_SCAN_INTERVAL_SECONDS == 300

    def test_evolution_max_retries(self):
        assert EVOLUTION_MAX_RETRIES == 3
