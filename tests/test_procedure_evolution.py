"""AD-532b: Procedure evolution tests (FIX / DERIVED).

Tests cover:
- _format_episode_blocks() helper (5a)
- evolve_fix_procedure() (5b)
- evolve_derived_procedure() (5c)
- diagnose_procedure_health() shared function (5d)
- Anti-loop guard (5e)
- _evolve_degraded_procedures() integration (5f)
- DreamReport procedures_evolved field (5g)
- ProcedureStore.save() with evolution metadata (5h)
- Refactored extract_procedure_from_cluster() (5i)
- CognitiveAgent._diagnose_procedure_health() refactor (5j)
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.procedures import (
    Procedure,
    ProcedureStep,
    EvolutionResult,
    _format_episode_blocks,
    diagnose_procedure_health,
    evolve_fix_procedure,
    evolve_derived_procedure,
    extract_procedure_from_cluster,
)
from probos.types import DreamReport, Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(
    episode_id: str,
    user_input: str = "test",
    outcomes: list[dict] | None = None,
    agent_ids: list[str] | None = None,
    timestamp: float = 0.0,
    reflection: str = "",
    dag_summary: dict | None = None,
) -> Episode:
    return Episode(
        id=episode_id,
        user_input=user_input,
        outcomes=outcomes or [],
        agent_ids=agent_ids or [],
        timestamp=timestamp,
        reflection=reflection,
        dag_summary=dag_summary or {},
    )


def _make_procedure(
    proc_id: str = "proc-1",
    name: str = "Test Procedure",
    intent_types: list[str] | None = None,
    generation: int = 0,
    compilation_level: int = 2,
    tags: list[str] | None = None,
    origin_cluster_id: str = "cluster-1",
    origin_agent_ids: list[str] | None = None,
) -> Procedure:
    return Procedure(
        id=proc_id,
        name=name,
        description="A test procedure",
        steps=[
            ProcedureStep(step_number=1, action="Do thing"),
            ProcedureStep(step_number=2, action="Do other thing"),
        ],
        preconditions=["logged in"],
        postconditions=["task done"],
        intent_types=intent_types or ["read"],
        origin_cluster_id=origin_cluster_id,
        origin_agent_ids=origin_agent_ids or ["agent-a"],
        generation=generation,
        compilation_level=compilation_level,
        tags=tags or ["domain:test"],
    )


_FIX_LLM_JSON = json.dumps({
    "name": "Repaired read handler",
    "description": "Fixed version of read request handler",
    "steps": [
        {
            "step_number": 1,
            "action": "Validate input format",
            "expected_input": "raw text",
            "expected_output": "validated input",
            "fallback_action": "reject with error",
            "invariants": ["input is non-empty"],
        },
        {
            "step_number": 2,
            "action": "Execute read",
            "expected_input": "validated input",
            "expected_output": "data",
            "fallback_action": "retry",
            "invariants": [],
        },
    ],
    "preconditions": ["authenticated"],
    "postconditions": ["data returned"],
    "change_summary": "Added input validation step to reduce fallback rate",
})

_DERIVED_LLM_JSON = json.dumps({
    "name": "Specialized read for large files",
    "description": "Handles large file reads with streaming",
    "steps": [
        {
            "step_number": 1,
            "action": "Check file size",
            "expected_input": "file path",
            "expected_output": "size classification",
            "fallback_action": "assume large",
            "invariants": [],
        },
        {
            "step_number": 2,
            "action": "Stream read",
            "expected_input": "large file path",
            "expected_output": "streamed data",
            "fallback_action": "chunk read",
            "invariants": ["memory < threshold"],
        },
    ],
    "preconditions": ["file exists", "file size > 1MB"],
    "postconditions": ["data streamed"],
    "change_summary": "Specialized for large file reads that parent fails on",
})


def _mock_llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    return resp


def _make_llm_client(response_content: str) -> AsyncMock:
    client = AsyncMock()
    client.complete = AsyncMock(return_value=_mock_llm_response(response_content))
    return client


# ===========================================================================
# 5a: _format_episode_blocks() helper
# ===========================================================================

class TestFormatEpisodeBlocks:
    def test_formats_with_readonly_framing(self):
        eps = [_make_episode("ep-1", user_input="hello", reflection="good")]
        result = _format_episode_blocks(eps)
        assert "=== READ-ONLY EPISODE" in result
        assert "=== END READ-ONLY EPISODE ===" in result
        assert "Episode ID: ep-1" in result
        assert "User Input: hello" in result
        assert "Reflection: good" in result

    def test_empty_episodes(self):
        result = _format_episode_blocks([])
        assert result == ""

    def test_none_reflection(self):
        eps = [_make_episode("ep-2", reflection="")]
        result = _format_episode_blocks(eps)
        assert "Reflection: none" in result

    def test_multiple_episodes(self):
        eps = [_make_episode(f"ep-{i}") for i in range(3)]
        result = _format_episode_blocks(eps)
        assert result.count("=== READ-ONLY EPISODE") == 3
        assert result.count("=== END READ-ONLY EPISODE ===") == 3


# ===========================================================================
# 5b: evolve_fix_procedure()
# ===========================================================================

class TestEvolveFixProcedure:
    @pytest.mark.asyncio
    async def test_returns_evolution_result(self):
        parent = _make_procedure()
        client = _make_llm_client(_FIX_LLM_JSON)
        episodes = [_make_episode("ep-1")]
        metrics = {"total_selections": 10, "fallback_rate": 0.5}

        result = await evolve_fix_procedure(
            parent, "FIX:high_fallback_rate", metrics, episodes, client,
        )

        assert result is not None
        assert isinstance(result, EvolutionResult)
        assert result.procedure.name == "Repaired read handler"

    @pytest.mark.asyncio
    async def test_fix_fields(self):
        parent = _make_procedure(generation=2, compilation_level=3)
        client = _make_llm_client(_FIX_LLM_JSON)
        result = await evolve_fix_procedure(
            parent, "FIX:high_fallback_rate", {}, [_make_episode("e1")], client,
        )
        assert result is not None
        p = result.procedure
        assert p.evolution_type == "FIX"
        assert p.generation == 3  # parent + 1
        assert p.parent_procedure_ids == [parent.id]
        assert p.compilation_level == 3  # preserved from parent

    @pytest.mark.asyncio
    async def test_preserves_parent_fields(self):
        parent = _make_procedure(
            intent_types=["read", "write"],
            tags=["domain:test", "priority:high"],
            origin_cluster_id="cluster-99",
            origin_agent_ids=["a1", "a2"],
        )
        client = _make_llm_client(_FIX_LLM_JSON)
        result = await evolve_fix_procedure(
            parent, "FIX:low_completion", {}, [_make_episode("e1")], client,
        )
        assert result is not None
        p = result.procedure
        assert p.intent_types == ["read", "write"]
        assert p.tags == ["domain:test", "priority:high"]
        assert p.origin_cluster_id == "cluster-99"
        assert p.origin_agent_ids == ["a1", "a2"]

    @pytest.mark.asyncio
    async def test_generates_content_diff(self):
        parent = _make_procedure()
        client = _make_llm_client(_FIX_LLM_JSON)
        result = await evolve_fix_procedure(
            parent, "FIX:high_fallback_rate", {}, [_make_episode("e1")], client,
        )
        assert result is not None
        assert len(result.content_diff) > 0
        assert "parent:" in result.content_diff or "---" in result.content_diff

    @pytest.mark.asyncio
    async def test_extracts_change_summary(self):
        parent = _make_procedure()
        client = _make_llm_client(_FIX_LLM_JSON)
        result = await evolve_fix_procedure(
            parent, "FIX:high_fallback_rate", {}, [_make_episode("e1")], client,
        )
        assert result is not None
        assert "validation" in result.change_summary.lower()

    @pytest.mark.asyncio
    async def test_returns_none_on_error_response(self):
        parent = _make_procedure()
        client = _make_llm_client(json.dumps({"error": "no_repair_possible"}))
        result = await evolve_fix_procedure(
            parent, "FIX:high_fallback_rate", {}, [_make_episode("e1")], client,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        parent = _make_procedure()
        client = AsyncMock()
        client.complete = AsyncMock(side_effect=RuntimeError("boom"))
        result = await evolve_fix_procedure(
            parent, "FIX:high_fallback_rate", {}, [_make_episode("e1")], client,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_malformed_json(self):
        parent = _make_procedure()
        client = _make_llm_client("not json at all")
        result = await evolve_fix_procedure(
            parent, "FIX:high_fallback_rate", {}, [_make_episode("e1")], client,
        )
        assert result is None


# ===========================================================================
# 5c: evolve_derived_procedure()
# ===========================================================================

class TestEvolveDerivedProcedure:
    @pytest.mark.asyncio
    async def test_returns_evolution_result(self):
        parent = _make_procedure()
        client = _make_llm_client(_DERIVED_LLM_JSON)
        result = await evolve_derived_procedure(
            [parent], [_make_episode("e1")], client,
        )
        assert result is not None
        assert isinstance(result, EvolutionResult)
        assert result.procedure.name == "Specialized read for large files"

    @pytest.mark.asyncio
    async def test_derived_fields(self):
        parent = _make_procedure(generation=1, compilation_level=3)
        client = _make_llm_client(_DERIVED_LLM_JSON)
        result = await evolve_derived_procedure(
            [parent], [_make_episode("e1")], client,
        )
        assert result is not None
        p = result.procedure
        assert p.evolution_type == "DERIVED"
        assert p.generation == 2  # max(parents) + 1
        assert p.parent_procedure_ids == [parent.id]
        assert p.compilation_level == 2  # max(parents) - 1

    @pytest.mark.asyncio
    async def test_compilation_level_minimum_1(self):
        parent = _make_procedure(compilation_level=1)
        client = _make_llm_client(_DERIVED_LLM_JSON)
        result = await evolve_derived_procedure(
            [parent], [_make_episode("e1")], client,
        )
        assert result is not None
        assert result.procedure.compilation_level == 1  # max(1-1, 1) = 1

    @pytest.mark.asyncio
    async def test_multi_parent_derived(self):
        p1 = _make_procedure(proc_id="p1", intent_types=["read"], tags=["a"], generation=1, compilation_level=2)
        p2 = _make_procedure(proc_id="p2", intent_types=["write"], tags=["b"], generation=3, compilation_level=4)
        client = _make_llm_client(_DERIVED_LLM_JSON)
        result = await evolve_derived_procedure(
            [p1, p2], [_make_episode("e1")], client,
        )
        assert result is not None
        p = result.procedure
        assert p.generation == 4  # max(1,3) + 1
        assert p.compilation_level == 3  # max(2,4) - 1
        assert set(p.parent_procedure_ids) == {"p1", "p2"}
        assert "read" in p.intent_types
        assert "write" in p.intent_types

    @pytest.mark.asyncio
    async def test_intent_types_union(self):
        p1 = _make_procedure(proc_id="p1", intent_types=["read", "list"])
        p2 = _make_procedure(proc_id="p2", intent_types=["read", "write"])
        client = _make_llm_client(_DERIVED_LLM_JSON)
        result = await evolve_derived_procedure(
            [p1, p2], [_make_episode("e1")], client,
        )
        assert result is not None
        assert set(result.procedure.intent_types) == {"read", "list", "write"}

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self):
        parent = _make_procedure()
        client = _make_llm_client(json.dumps({"error": "no_specialization_possible"}))
        result = await evolve_derived_procedure(
            [parent], [_make_episode("e1")], client,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        parent = _make_procedure()
        client = AsyncMock()
        client.complete = AsyncMock(side_effect=RuntimeError("boom"))
        result = await evolve_derived_procedure(
            [parent], [_make_episode("e1")], client,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_origin_cluster_empty(self):
        """DERIVED has no single origin cluster."""
        parent = _make_procedure(origin_cluster_id="cluster-1")
        client = _make_llm_client(_DERIVED_LLM_JSON)
        result = await evolve_derived_procedure(
            [parent], [_make_episode("e1")], client,
        )
        assert result is not None
        assert result.procedure.origin_cluster_id == ""


# ===========================================================================
# 5d: diagnose_procedure_health() shared function
# ===========================================================================

class TestDiagnoseProcedureHealth:
    def test_fix_high_fallback_rate(self):
        metrics = {"total_selections": 10, "fallback_rate": 0.5, "applied_rate": 0.0,
                    "completion_rate": 0.0, "effective_rate": 0.0}
        assert diagnose_procedure_health(metrics) == "FIX:high_fallback_rate"

    def test_fix_low_completion(self):
        metrics = {"total_selections": 10, "fallback_rate": 0.1, "applied_rate": 0.6,
                    "completion_rate": 0.2, "effective_rate": 0.8}
        assert diagnose_procedure_health(metrics) == "FIX:low_completion"

    def test_derived_low_effective(self):
        metrics = {"total_selections": 10, "fallback_rate": 0.1, "applied_rate": 0.5,
                    "completion_rate": 0.9, "effective_rate": 0.3}
        assert diagnose_procedure_health(metrics) == "DERIVED:low_effective_rate"

    def test_returns_none_when_healthy(self):
        metrics = {"total_selections": 10, "fallback_rate": 0.1, "applied_rate": 0.3,
                    "completion_rate": 0.9, "effective_rate": 0.8}
        assert diagnose_procedure_health(metrics) is None

    def test_returns_none_below_min_selections(self):
        metrics = {"total_selections": 3, "fallback_rate": 0.9}
        assert diagnose_procedure_health(metrics) is None

    def test_first_match_wins_priority(self):
        """FIX:high_fallback_rate takes priority over FIX:low_completion."""
        metrics = {"total_selections": 10, "fallback_rate": 0.6, "applied_rate": 0.6,
                    "completion_rate": 0.2, "effective_rate": 0.3}
        result = diagnose_procedure_health(metrics)
        assert result == "FIX:high_fallback_rate"

    def test_custom_min_selections(self):
        metrics = {"total_selections": 3, "fallback_rate": 0.9, "applied_rate": 0.0,
                    "completion_rate": 0.0, "effective_rate": 0.0}
        assert diagnose_procedure_health(metrics, min_selections=3) == "FIX:high_fallback_rate"
        assert diagnose_procedure_health(metrics, min_selections=5) is None


# ===========================================================================
# 5e: Anti-loop guard
# ===========================================================================

class TestAntiLoopGuard:
    @pytest.mark.asyncio
    async def test_skips_within_cooldown(self):
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        engine = DreamingEngine(
            router=MagicMock(), trust_network=MagicMock(),
            episodic_memory=MagicMock(), config=DreamingConfig(),
            llm_client=_make_llm_client(_FIX_LLM_JSON),
            procedure_store=MagicMock(),
        )

        # Pre-set cooldown for proc-1
        engine._addressed_degradations["proc-1"] = time.time()

        # Mock store to return a degraded procedure
        store = engine._procedure_store
        store.list_active = AsyncMock(return_value=[{
            "id": "proc-1", "name": "test", "intent_types": ["read"],
            "total_selections": 10, "total_applied": 5,
            "total_completions": 2, "total_fallbacks": 6,
        }])
        store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10, "fallback_rate": 0.6,
            "applied_rate": 0.5, "completion_rate": 0.4, "effective_rate": 0.2,
        })

        result = await engine._evolve_degraded_procedures([], [])
        assert result == 0  # Skipped due to cooldown

    @pytest.mark.asyncio
    async def test_processes_after_cooldown(self):
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        parent = _make_procedure(proc_id="proc-1")
        engine = DreamingEngine(
            router=MagicMock(), trust_network=MagicMock(),
            episodic_memory=MagicMock(), config=DreamingConfig(),
            llm_client=_make_llm_client(_FIX_LLM_JSON),
            procedure_store=MagicMock(),
        )

        # Set cooldown to far past
        engine._addressed_degradations["proc-1"] = time.time() - 300000

        store = engine._procedure_store
        store.list_active = AsyncMock(return_value=[{
            "id": "proc-1", "name": "test", "intent_types": ["read"],
        }])
        store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10, "fallback_rate": 0.6,
            "applied_rate": 0.5, "completion_rate": 0.4, "effective_rate": 0.2,
        })
        store.get = AsyncMock(return_value=parent)
        store.save = AsyncMock()
        store.deactivate = AsyncMock()

        engine.episodic_memory.recall_by_intent = AsyncMock(
            return_value=[_make_episode("e1")]
        )

        result = await engine._evolve_degraded_procedures([], [])
        assert result == 1  # Processed

    @pytest.mark.asyncio
    async def test_records_timestamp_after_attempt(self):
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        parent = _make_procedure(proc_id="proc-1")
        engine = DreamingEngine(
            router=MagicMock(), trust_network=MagicMock(),
            episodic_memory=MagicMock(), config=DreamingConfig(),
            llm_client=_make_llm_client(json.dumps({"error": "no_repair_possible"})),
            procedure_store=MagicMock(),
        )

        store = engine._procedure_store
        store.list_active = AsyncMock(return_value=[{"id": "proc-1", "name": "test", "intent_types": ["read"]}])
        store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10, "fallback_rate": 0.6,
            "applied_rate": 0.5, "completion_rate": 0.4, "effective_rate": 0.2,
        })
        store.get = AsyncMock(return_value=parent)
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[_make_episode("e1")])

        before = time.time()
        await engine._evolve_degraded_procedures([], [])
        assert "proc-1" in engine._addressed_degradations
        assert engine._addressed_degradations["proc-1"] >= before


# ===========================================================================
# 5f: _evolve_degraded_procedures() integration
# ===========================================================================

class TestEvolveDegradedProcedures:
    @pytest.mark.asyncio
    async def test_triggers_fix_for_high_fallback(self):
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        parent = _make_procedure(proc_id="proc-1")
        engine = DreamingEngine(
            router=MagicMock(), trust_network=MagicMock(),
            episodic_memory=MagicMock(), config=DreamingConfig(),
            llm_client=_make_llm_client(_FIX_LLM_JSON),
            procedure_store=MagicMock(),
        )

        store = engine._procedure_store
        store.list_active = AsyncMock(return_value=[{"id": "proc-1", "name": "test", "intent_types": ["read"]}])
        store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10, "fallback_rate": 0.6,
            "applied_rate": 0.5, "completion_rate": 0.4, "effective_rate": 0.2,
        })
        store.get = AsyncMock(return_value=parent)
        store.save = AsyncMock()
        store.deactivate = AsyncMock()
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[_make_episode("e1")])

        procedures: list = []
        result = await engine._evolve_degraded_procedures([], procedures)
        assert result == 1
        store.save.assert_awaited_once()
        store.deactivate.assert_awaited_once()
        # FIX deactivates parent
        call_kwargs = store.deactivate.call_args
        assert call_kwargs[0][0] == "proc-1"

    @pytest.mark.asyncio
    async def test_triggers_derived_keeps_parent_active(self):
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        parent = _make_procedure(proc_id="proc-1")
        engine = DreamingEngine(
            router=MagicMock(), trust_network=MagicMock(),
            episodic_memory=MagicMock(), config=DreamingConfig(),
            llm_client=_make_llm_client(_DERIVED_LLM_JSON),
            procedure_store=MagicMock(),
        )

        store = engine._procedure_store
        store.list_active = AsyncMock(return_value=[{"id": "proc-1", "name": "test", "intent_types": ["read"]}])
        store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10, "fallback_rate": 0.1,
            "applied_rate": 0.5, "completion_rate": 0.9, "effective_rate": 0.3,
        })
        store.get = AsyncMock(return_value=parent)
        store.save = AsyncMock()
        store.deactivate = AsyncMock()
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[_make_episode("e1")])

        result = await engine._evolve_degraded_procedures([], [])
        assert result == 1
        store.save.assert_awaited_once()
        store.deactivate.assert_not_awaited()  # DERIVED keeps parent active

    @pytest.mark.asyncio
    async def test_saves_with_content_diff_and_summary(self):
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        parent = _make_procedure(proc_id="proc-1")
        engine = DreamingEngine(
            router=MagicMock(), trust_network=MagicMock(),
            episodic_memory=MagicMock(), config=DreamingConfig(),
            llm_client=_make_llm_client(_FIX_LLM_JSON),
            procedure_store=MagicMock(),
        )

        store = engine._procedure_store
        store.list_active = AsyncMock(return_value=[{"id": "proc-1", "name": "test", "intent_types": ["read"]}])
        store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10, "fallback_rate": 0.6,
            "applied_rate": 0.5, "completion_rate": 0.4, "effective_rate": 0.2,
        })
        store.get = AsyncMock(return_value=parent)
        store.save = AsyncMock()
        store.deactivate = AsyncMock()
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[_make_episode("e1")])

        await engine._evolve_degraded_procedures([], [])
        save_kwargs = store.save.call_args
        assert "content_diff" in save_kwargs.kwargs
        assert "change_summary" in save_kwargs.kwargs
        assert len(save_kwargs.kwargs["content_diff"]) > 0

    @pytest.mark.asyncio
    async def test_skips_insufficient_selections(self):
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        engine = DreamingEngine(
            router=MagicMock(), trust_network=MagicMock(),
            episodic_memory=MagicMock(), config=DreamingConfig(),
            llm_client=_make_llm_client(_FIX_LLM_JSON),
            procedure_store=MagicMock(),
        )

        store = engine._procedure_store
        store.list_active = AsyncMock(return_value=[{"id": "proc-1", "name": "test", "intent_types": ["read"]}])
        store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 2, "fallback_rate": 0.0,
            "applied_rate": 0.0, "completion_rate": 0.0, "effective_rate": 0.0,
        })

        result = await engine._evolve_degraded_procedures([], [])
        assert result == 0

    @pytest.mark.asyncio
    async def test_handles_empty_procedure_list(self):
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        engine = DreamingEngine(
            router=MagicMock(), trust_network=MagicMock(),
            episodic_memory=MagicMock(), config=DreamingConfig(),
            llm_client=_make_llm_client(""),
            procedure_store=MagicMock(),
        )
        engine._procedure_store.list_active = AsyncMock(return_value=[])
        result = await engine._evolve_degraded_procedures([], [])
        assert result == 0

    @pytest.mark.asyncio
    async def test_handles_evolution_returning_none(self):
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        parent = _make_procedure(proc_id="proc-1")
        engine = DreamingEngine(
            router=MagicMock(), trust_network=MagicMock(),
            episodic_memory=MagicMock(), config=DreamingConfig(),
            llm_client=_make_llm_client(json.dumps({"error": "no_repair_possible"})),
            procedure_store=MagicMock(),
        )

        store = engine._procedure_store
        store.list_active = AsyncMock(return_value=[{"id": "proc-1", "name": "test", "intent_types": ["read"]}])
        store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10, "fallback_rate": 0.6,
            "applied_rate": 0.5, "completion_rate": 0.4, "effective_rate": 0.2,
        })
        store.get = AsyncMock(return_value=parent)
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[_make_episode("e1")])

        result = await engine._evolve_degraded_procedures([], [])
        assert result == 0
        store.save = AsyncMock()
        store.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_no_fresh_episodes(self):
        from probos.cognitive.dreaming import DreamingEngine
        from probos.config import DreamingConfig

        parent = _make_procedure(proc_id="proc-1")
        engine = DreamingEngine(
            router=MagicMock(), trust_network=MagicMock(),
            episodic_memory=MagicMock(), config=DreamingConfig(),
            llm_client=_make_llm_client(_FIX_LLM_JSON),
            procedure_store=MagicMock(),
        )

        store = engine._procedure_store
        store.list_active = AsyncMock(return_value=[{"id": "proc-1", "name": "test", "intent_types": ["read"]}])
        store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 10, "fallback_rate": 0.6,
            "applied_rate": 0.5, "completion_rate": 0.4, "effective_rate": 0.2,
        })
        store.get = AsyncMock(return_value=parent)
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[])

        result = await engine._evolve_degraded_procedures([], [])
        assert result == 0


# ===========================================================================
# 5g: DreamReport procedures_evolved
# ===========================================================================

class TestDreamReportEvolved:
    def test_defaults_to_zero(self):
        report = DreamReport()
        assert report.procedures_evolved == 0

    def test_field_can_be_set(self):
        report = DreamReport(procedures_evolved=3)
        assert report.procedures_evolved == 3


# ===========================================================================
# 5h: ProcedureStore.save() with evolution metadata
# ===========================================================================

class TestProcedureStoreSaveEvolution:
    @pytest.mark.asyncio
    async def test_save_with_content_diff(self):
        from probos.cognitive.procedure_store import ProcedureStore

        mock_db = AsyncMock()
        mock_db.executescript = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        factory = AsyncMock()
        factory.connect = AsyncMock(return_value=mock_db)

        store = ProcedureStore(data_dir="/tmp/test_store", connection_factory=factory)
        store._db = mock_db
        store._chroma_collection = None

        proc = _make_procedure()
        await store.save(proc, content_diff="--- a\n+++ b\n", change_summary="Fixed step 1")

        # Verify the INSERT call includes content_diff and change_summary
        call_args = mock_db.execute.call_args_list
        insert_call = [c for c in call_args if "INSERT OR REPLACE" in str(c)]
        assert len(insert_call) > 0
        # The params tuple should contain the diff and summary
        params = insert_call[0][0][1]
        assert "--- a\n+++ b\n" in params
        assert "Fixed step 1" in params

    @pytest.mark.asyncio
    async def test_save_without_kwargs_still_works(self):
        """Existing save() calls (AD-533) still work without kwargs."""
        from probos.cognitive.procedure_store import ProcedureStore

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        store = ProcedureStore(data_dir="/tmp/test_store")
        store._db = mock_db
        store._chroma_collection = None

        proc = _make_procedure()
        await store.save(proc)  # No kwargs — should not raise

    @pytest.mark.asyncio
    async def test_get_evolution_metadata(self):
        from probos.cognitive.procedure_store import ProcedureStore

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=("some diff", "some summary"))
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        store = ProcedureStore(data_dir="/tmp/test_store")
        store._db = mock_db

        result = await store.get_evolution_metadata("proc-1")
        assert result["content_diff"] == "some diff"
        assert result["change_summary"] == "some summary"

    @pytest.mark.asyncio
    async def test_get_evolution_metadata_empty(self):
        from probos.cognitive.procedure_store import ProcedureStore

        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=None)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        store = ProcedureStore(data_dir="/tmp/test_store")
        store._db = mock_db

        result = await store.get_evolution_metadata("nonexistent")
        assert result["content_diff"] == ""
        assert result["change_summary"] == ""


# ===========================================================================
# 5i: Refactored extract_procedure_from_cluster()
# ===========================================================================

class TestExtractProcedureRefactored:
    """Verify extract_procedure_from_cluster() still works after _format_episode_blocks() refactor."""

    @pytest.mark.asyncio
    async def test_still_extracts_successfully(self):
        valid_json = json.dumps({
            "name": "Test procedure",
            "description": "A test",
            "steps": [
                {"step_number": 1, "action": "Do it", "expected_input": "",
                 "expected_output": "", "fallback_action": "", "invariants": []},
            ],
            "preconditions": ["ready"],
            "postconditions": ["done"],
        })
        client = _make_llm_client(valid_json)
        cluster = MagicMock()
        cluster.cluster_id = "c1"
        cluster.success_rate = 0.9
        cluster.intent_types = ["test"]
        cluster.participating_agents = ["agent-1"]
        cluster.episode_ids = ["e1"]

        episodes = [_make_episode("e1")]
        result = await extract_procedure_from_cluster(cluster, episodes, client)
        assert result is not None
        assert result.name == "Test procedure"
        assert result.evolution_type == "CAPTURED"
        assert len(result.steps) == 1

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self):
        client = _make_llm_client(json.dumps({"error": "no_common_pattern"}))
        cluster = MagicMock()
        cluster.cluster_id = "c1"
        cluster.success_rate = 0.9
        cluster.intent_types = ["test"]
        cluster.participating_agents = ["agent-1"]
        cluster.episode_ids = ["e1"]

        result = await extract_procedure_from_cluster(cluster, [_make_episode("e1")], client)
        assert result is None


# ===========================================================================
# 5j: CognitiveAgent._diagnose_procedure_health() refactor
# ===========================================================================

class TestCognitiveAgentDiagnoseRefactor:
    """Verify the refactored CognitiveAgent method still produces correct diagnoses."""

    def test_fix_high_fallback_logs_warning(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = object.__new__(CognitiveAgent)
        metrics = {"total_selections": 10, "fallback_rate": 0.6,
                    "applied_rate": 0.0, "completion_rate": 0.0, "effective_rate": 0.0}
        # Should not raise — just logs
        agent._diagnose_procedure_health("proc-1", "Test Proc", metrics)

    def test_healthy_metrics_no_warning(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = object.__new__(CognitiveAgent)
        metrics = {"total_selections": 10, "fallback_rate": 0.1,
                    "applied_rate": 0.3, "completion_rate": 0.9, "effective_rate": 0.8}
        agent._diagnose_procedure_health("proc-1", "Test Proc", metrics)

    def test_below_min_selections_no_warning(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = object.__new__(CognitiveAgent)
        metrics = {"total_selections": 2, "fallback_rate": 0.9}
        agent._diagnose_procedure_health("proc-1", "Test Proc", metrics)
