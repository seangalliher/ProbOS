"""AD-534c: Multi-agent replay dispatch tests.

Tests cover:
- ProcedureStep.resolved_agent_type (Test Class 1: 8 tests)
- Compound detection in _check_procedural_memory (Test Class 2: 5 tests)
- _resolve_step_agent (Test Class 3: 7 tests)
- _execute_compound_replay (Test Class 4: 10 tests)
- compound_step_replay handler (Test Class 5: 5 tests)
- handle_intent compound branch (Test Class 6: 8 tests)
- _format_single_step (Test Class 7: 4 tests)
- _format_procedure_replay DRY (Test Class 8: 3 tests)
- End-to-end compound replay (Test Class 9: 4 tests)

Total: 54 tests.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.procedures import (
    Procedure,
    ProcedureStep,
    _build_steps_from_data,
    _resolve_agent_roles,
)
from probos.types import IntentMessage, IntentResult


# ------------------------------------------------------------------ helpers

def _make_cognitive_agent(**overrides):
    """Build a minimal CognitiveAgent for testing."""
    from probos.cognitive.cognitive_agent import CognitiveAgent, _DECISION_CACHES
    from probos.types import AgentMeta, AgentState

    defaults = {
        "agent_id": "test-agent-001",
        "agent_type": "science_officer",
        "instructions": "Test instructions.",
        "llm_client": AsyncMock(),
    }
    defaults.update(overrides)

    _DECISION_CACHES.pop(defaults["agent_type"], None)

    class TestCognitiveAgent(CognitiveAgent):
        _handled_intents = {"test_intent", "security_review"}

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
    # _procedure_store and _cognitive_journal are @property accessors via _runtime
    proc_store = defaults.get("procedure_store")
    if proc_store is not None:
        if agent._runtime is None:
            agent._runtime = MagicMock()
        agent._runtime.procedure_store = proc_store
    return agent


def _make_procedure(**overrides):
    """Build a minimal Procedure for testing."""
    defaults = {
        "id": "proc-42",
        "name": "Test Procedure",
        "description": "A test procedure",
        "steps": [ProcedureStep(step_number=1, action="Do something")],
        "intent_types": ["test_intent"],
        "is_active": True,
        "generation": 0,
    }
    defaults.update(overrides)
    return Procedure(**defaults)


def _make_compound_procedure(**overrides):
    """Build a compound procedure with agent_role on steps."""
    steps = overrides.pop("steps", [
        ProcedureStep(
            step_number=1,
            action="Analyze code for vulnerability",
            agent_role="security_analysis",
            resolved_agent_type="security_officer",
            expected_output="vulnerability report",
        ),
        ProcedureStep(
            step_number=2,
            action="Implement patch",
            agent_role="engineering_fix",
            resolved_agent_type="engineering_officer",
            expected_output="patch applied",
        ),
    ])
    defaults = {
        "id": "proc-compound",
        "name": "Security Review + Patch",
        "description": "Multi-agent security review",
        "steps": steps,
        "intent_types": ["security_review"],
        "is_active": True,
        "generation": 0,
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
    return store


def _make_intent(intent_type="test_intent", **overrides):
    """Build a minimal IntentMessage."""
    defaults = {
        "intent": intent_type,
        "params": {"message": "test query"},
        "context": "",
        "target_agent_id": "test-agent-001",
    }
    defaults.update(overrides)
    return IntentMessage(**defaults)


def _make_mock_runtime(intent_bus=None, registry=None, procedure_store=None):
    """Build a mock runtime with intent_bus and registry."""
    rt = MagicMock()
    rt.intent_bus = intent_bus or AsyncMock()
    rt.registry = registry or MagicMock()
    rt._emit_event = MagicMock()
    rt.procedure_store = procedure_store
    return rt


def _make_mock_agent_entry(agent_id: str, is_alive: bool = True):
    """Build a mock agent registry entry."""
    entry = MagicMock()
    entry.id = agent_id
    entry.is_alive = is_alive
    return entry


# ===================================================================
# Test Class 1: TestResolvedAgentType (8 tests)
# ===================================================================


class TestResolvedAgentType:
    """Tests for ProcedureStep.resolved_agent_type field."""

    def test_procedure_step_resolved_agent_type_default(self):
        step = ProcedureStep(step_number=1, action="do stuff")
        assert step.resolved_agent_type == ""

    def test_procedure_step_resolved_agent_type_set(self):
        step = ProcedureStep(
            step_number=1, action="do stuff", resolved_agent_type="security_officer"
        )
        assert step.resolved_agent_type == "security_officer"

    def test_procedure_step_to_dict_includes_resolved_agent_type(self):
        step = ProcedureStep(
            step_number=1, action="do stuff", resolved_agent_type="eng_officer"
        )
        d = step.to_dict()
        assert "resolved_agent_type" in d
        assert d["resolved_agent_type"] == "eng_officer"

    def test_build_steps_from_data_parses_resolved_agent_type(self):
        data = {
            "steps": [
                {
                    "step_number": 1,
                    "action": "act",
                    "resolved_agent_type": "science_officer",
                }
            ]
        }
        steps = _build_steps_from_data(data)
        assert steps[0].resolved_agent_type == "science_officer"

    def test_build_steps_from_data_missing_resolved_agent_type(self):
        data = {"steps": [{"step_number": 1, "action": "act"}]}
        steps = _build_steps_from_data(data)
        assert steps[0].resolved_agent_type == ""

    def test_procedure_round_trip_with_resolved_agent_type(self):
        proc = _make_procedure(
            steps=[
                ProcedureStep(
                    step_number=1,
                    action="analyze",
                    agent_role="security_analysis",
                    resolved_agent_type="security_officer",
                )
            ]
        )
        d = proc.to_dict()
        restored = Procedure.from_dict(d)
        assert restored.steps[0].resolved_agent_type == "security_officer"
        assert restored.steps[0].agent_role == "security_analysis"

    def test_resolve_agent_roles_basic(self):
        steps = [
            ProcedureStep(step_number=1, action="analyze", agent_role="security_analysis"),
            ProcedureStep(step_number=2, action="fix", agent_role="engineering_fix"),
        ]
        _resolve_agent_roles(steps, ["security_officer-abc123", "engineering_officer-def456"])
        assert steps[0].resolved_agent_type == "security_officer"
        assert steps[1].resolved_agent_type == "engineering_officer"

    def test_resolve_agent_roles_no_match(self):
        steps = [
            ProcedureStep(step_number=1, action="cast spell", agent_role="wizardry_magic"),
        ]
        _resolve_agent_roles(steps, ["security_officer-abc123", "engineering_officer-def456"])
        # No token overlap → empty
        assert steps[0].resolved_agent_type == ""


# ===================================================================
# Test Class 2: TestCompoundDetection (5 tests)
# ===================================================================


class TestCompoundDetection:
    """Tests for compound detection in _check_procedural_memory()."""

    @pytest.mark.asyncio
    async def test_compound_detected_when_steps_have_roles(self):
        proc = _make_compound_procedure()
        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[{"id": proc.id, "score": 0.9}])
        store.get = AsyncMock(return_value=proc)

        agent = _make_cognitive_agent(procedure_store=store)
        observation = {"intent": "security_review", "params": {"message": "review code"}}

        result = await agent._check_procedural_memory(observation)
        assert result is not None
        assert result.get("compound") is True
        assert result.get("procedure") is proc

    @pytest.mark.asyncio
    async def test_not_compound_when_no_roles(self):
        proc = _make_procedure()  # No agent_role on steps
        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[{"id": proc.id, "score": 0.9}])
        store.get = AsyncMock(return_value=proc)

        agent = _make_cognitive_agent(procedure_store=store)
        observation = {"intent": "test_intent", "params": {"message": "test"}}

        result = await agent._check_procedural_memory(observation)
        assert result is not None
        assert "compound" not in result

    @pytest.mark.asyncio
    async def test_compound_not_detected_empty_roles(self):
        steps = [
            ProcedureStep(step_number=1, action="do x", agent_role=""),
            ProcedureStep(step_number=2, action="do y", agent_role=""),
        ]
        proc = _make_procedure(steps=steps)
        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[{"id": proc.id, "score": 0.9}])
        store.get = AsyncMock(return_value=proc)

        agent = _make_cognitive_agent(procedure_store=store)
        observation = {"intent": "test_intent", "params": {"message": "test"}}

        result = await agent._check_procedural_memory(observation)
        assert result is not None
        assert "compound" not in result

    @pytest.mark.asyncio
    async def test_mixed_roles_still_compound(self):
        steps = [
            ProcedureStep(step_number=1, action="do x", agent_role=""),
            ProcedureStep(step_number=2, action="do y", agent_role="analysis"),
        ]
        proc = _make_procedure(steps=steps)
        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[{"id": proc.id, "score": 0.9}])
        store.get = AsyncMock(return_value=proc)

        agent = _make_cognitive_agent(procedure_store=store)
        observation = {"intent": "test_intent", "params": {"message": "test"}}

        result = await agent._check_procedural_memory(observation)
        assert result is not None
        assert result.get("compound") is True

    @pytest.mark.asyncio
    async def test_compound_decision_includes_procedure_object(self):
        proc = _make_compound_procedure()
        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[{"id": proc.id, "score": 0.9}])
        store.get = AsyncMock(return_value=proc)

        agent = _make_cognitive_agent(procedure_store=store)
        observation = {"intent": "security_review", "params": {"message": "review"}}

        result = await agent._check_procedural_memory(observation)
        assert result["procedure"] is proc
        assert isinstance(result["procedure"], Procedure)


# ===================================================================
# Test Class 3: TestResolveStepAgent (7 tests)
# ===================================================================


class TestResolveStepAgent:
    """Tests for _resolve_step_agent()."""

    def test_resolve_by_resolved_agent_type(self):
        target = _make_mock_agent_entry("sec-agent-001")
        registry = MagicMock()
        registry.get_by_pool = MagicMock(return_value=[target])
        rt = _make_mock_runtime(registry=registry)

        agent = _make_cognitive_agent(runtime=rt)
        step = ProcedureStep(
            step_number=1, action="scan", resolved_agent_type="security_officer"
        )

        result = agent._resolve_step_agent(step)
        assert result == "sec-agent-001"
        registry.get_by_pool.assert_called_once_with("security_officer")

    def test_resolve_by_capability_fallback(self):
        cap_agent = _make_mock_agent_entry("cap-agent-001")
        registry = MagicMock()
        registry.get_by_pool = MagicMock(return_value=[])
        registry.get_by_capability = MagicMock(return_value=[cap_agent])
        rt = _make_mock_runtime(registry=registry)

        agent = _make_cognitive_agent(runtime=rt)
        step = ProcedureStep(
            step_number=1, action="scan", agent_role="security_analysis"
        )

        result = agent._resolve_step_agent(step)
        assert result == "cap-agent-001"
        registry.get_by_capability.assert_called_once_with("security_analysis")

    def test_resolve_returns_none_on_failure(self):
        registry = MagicMock()
        registry.get_by_pool = MagicMock(return_value=[])
        registry.get_by_capability = MagicMock(return_value=[])
        rt = _make_mock_runtime(registry=registry)

        agent = _make_cognitive_agent(runtime=rt)
        step = ProcedureStep(
            step_number=1, action="scan", agent_role="unknown_role"
        )

        result = agent._resolve_step_agent(step)
        assert result is None

    def test_resolve_skips_self(self):
        self_entry = _make_mock_agent_entry("test-agent-001")  # same as agent.id
        registry = MagicMock()
        registry.get_by_pool = MagicMock(return_value=[self_entry])
        registry.get_by_capability = MagicMock(return_value=[])
        rt = _make_mock_runtime(registry=registry)

        agent = _make_cognitive_agent(runtime=rt)
        step = ProcedureStep(
            step_number=1, action="scan", resolved_agent_type="science_officer"
        )

        result = agent._resolve_step_agent(step)
        assert result is None

    def test_resolve_picks_live_agent(self):
        dead = _make_mock_agent_entry("dead-agent", is_alive=False)
        alive = _make_mock_agent_entry("alive-agent", is_alive=True)
        registry = MagicMock()
        registry.get_by_pool = MagicMock(return_value=[dead, alive])
        rt = _make_mock_runtime(registry=registry)

        agent = _make_cognitive_agent(runtime=rt)
        step = ProcedureStep(
            step_number=1, action="scan", resolved_agent_type="security_officer"
        )

        result = agent._resolve_step_agent(step)
        assert result == "alive-agent"

    def test_resolve_no_registry_returns_none(self):
        agent = _make_cognitive_agent(runtime=None)
        step = ProcedureStep(
            step_number=1, action="scan", resolved_agent_type="security_officer"
        )

        result = agent._resolve_step_agent(step)
        assert result is None

    def test_resolve_empty_pool_returns_none(self):
        registry = MagicMock()
        registry.get_by_pool = MagicMock(return_value=[])
        registry.get_by_capability = MagicMock(return_value=[])
        rt = _make_mock_runtime(registry=registry)

        agent = _make_cognitive_agent(runtime=rt)
        step = ProcedureStep(
            step_number=1,
            action="scan",
            resolved_agent_type="empty_pool",
            agent_role="also_empty",
        )

        result = agent._resolve_step_agent(step)
        assert result is None


# ===================================================================
# Test Class 4: TestExecuteCompoundReplay (10 tests)
# ===================================================================


class TestExecuteCompoundReplay:
    """Tests for _execute_compound_replay()."""

    @pytest.mark.asyncio
    async def test_compound_replay_dispatches_steps(self):
        sec_agent = _make_mock_agent_entry("sec-001")
        eng_agent = _make_mock_agent_entry("eng-001")
        registry = MagicMock()
        # Step 1 resolves to sec-001, step 2 to eng-001
        registry.get_by_pool = MagicMock(
            side_effect=lambda pool: [sec_agent] if "security" in pool else [eng_agent]
        )

        bus = AsyncMock()
        bus.send = AsyncMock(
            side_effect=[
                IntentResult(intent_id="i1", agent_id="sec-001", success=True, result="sec result"),
                IntentResult(intent_id="i2", agent_id="eng-001", success=True, result="eng result"),
            ]
        )
        rt = _make_mock_runtime(intent_bus=bus, registry=registry)
        agent = _make_cognitive_agent(runtime=rt)
        proc = _make_compound_procedure()

        result = await agent._execute_compound_replay(proc, "fallback text")
        assert result["compound_dispatched"] is True
        assert result["steps_dispatched"] == 2
        assert "sec result" in result["result"]
        assert "eng result" in result["result"]

    @pytest.mark.asyncio
    async def test_compound_replay_local_steps(self):
        bus = AsyncMock()
        registry = MagicMock()
        rt = _make_mock_runtime(intent_bus=bus, registry=registry)
        agent = _make_cognitive_agent(runtime=rt)

        # Steps without agent_role = local
        steps = [
            ProcedureStep(step_number=1, action="Local step 1"),
            ProcedureStep(step_number=2, action="Local step 2"),
        ]
        proc = _make_procedure(steps=steps)

        result = await agent._execute_compound_replay(proc, "fallback")
        assert result["compound_dispatched"] is True
        assert result["steps_dispatched"] == 0
        bus.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_compound_replay_mixed_local_and_remote(self):
        sec_agent = _make_mock_agent_entry("sec-001")
        registry = MagicMock()
        registry.get_by_pool = MagicMock(return_value=[sec_agent])

        bus = AsyncMock()
        bus.send = AsyncMock(
            return_value=IntentResult(
                intent_id="i1", agent_id="sec-001", success=True, result="remote result"
            )
        )
        rt = _make_mock_runtime(intent_bus=bus, registry=registry)
        agent = _make_cognitive_agent(runtime=rt)

        steps = [
            ProcedureStep(step_number=1, action="Local step"),
            ProcedureStep(
                step_number=2,
                action="Remote step",
                agent_role="security",
                resolved_agent_type="security_officer",
            ),
        ]
        proc = _make_procedure(steps=steps)

        result = await agent._execute_compound_replay(proc, "fallback")
        assert result["compound_dispatched"] is True
        assert result["steps_dispatched"] == 1
        assert bus.send.await_count == 1

    @pytest.mark.asyncio
    async def test_compound_replay_degradation_on_unavailable_agent(self):
        registry = MagicMock()
        registry.get_by_pool = MagicMock(return_value=[])
        registry.get_by_capability = MagicMock(return_value=[])
        bus = AsyncMock()
        rt = _make_mock_runtime(intent_bus=bus, registry=registry)
        agent = _make_cognitive_agent(runtime=rt)
        proc = _make_compound_procedure()

        result = await agent._execute_compound_replay(proc, "fallback text")
        assert result["compound_dispatched"] is False
        assert result["result"] == "fallback text"
        assert agent._last_fallback_info is not None
        assert agent._last_fallback_info["type"] == "compound_agent_unavailable"

    @pytest.mark.asyncio
    async def test_compound_replay_step_dispatch_failure(self):
        sec_agent = _make_mock_agent_entry("sec-001")
        eng_agent = _make_mock_agent_entry("eng-001")
        registry = MagicMock()
        registry.get_by_pool = MagicMock(
            side_effect=lambda pool: [sec_agent] if "security" in pool else [eng_agent]
        )

        bus = AsyncMock()
        # First step succeeds, second fails
        bus.send = AsyncMock(
            side_effect=[
                IntentResult(intent_id="i1", agent_id="sec-001", success=True, result="sec ok"),
                IntentResult(intent_id="i2", agent_id="eng-001", success=False, result="failed"),
            ]
        )
        rt = _make_mock_runtime(intent_bus=bus, registry=registry)
        agent = _make_cognitive_agent(runtime=rt)
        proc = _make_compound_procedure()

        result = await agent._execute_compound_replay(proc, "fallback")
        # Does NOT abort — uses step text for failed step
        assert result["compound_dispatched"] is True
        assert result["steps_dispatched"] == 2
        assert "sec ok" in result["result"]

    @pytest.mark.asyncio
    async def test_compound_replay_no_intent_bus(self):
        rt = MagicMock(spec=[])  # No attributes at all
        agent = _make_cognitive_agent(runtime=rt)
        proc = _make_compound_procedure()

        result = await agent._execute_compound_replay(proc, "fallback text")
        assert result["compound_dispatched"] is False
        assert result["result"] == "fallback text"

    @pytest.mark.asyncio
    async def test_compound_replay_no_registry(self):
        rt = MagicMock(spec=[])  # No intent_bus or registry
        agent = _make_cognitive_agent(runtime=rt)
        proc = _make_compound_procedure()

        result = await agent._execute_compound_replay(proc, "fallback text")
        assert result["compound_dispatched"] is False
        assert result["result"] == "fallback text"

    @pytest.mark.asyncio
    async def test_compound_replay_zero_tokens(self):
        sec_agent = _make_mock_agent_entry("sec-001")
        registry = MagicMock()
        registry.get_by_pool = MagicMock(return_value=[sec_agent])

        bus = AsyncMock()
        bus.send = AsyncMock(
            return_value=IntentResult(
                intent_id="i1", agent_id="sec-001", success=True, result="step text"
            )
        )
        rt = _make_mock_runtime(intent_bus=bus, registry=registry)

        llm_mock = AsyncMock()
        agent = _make_cognitive_agent(runtime=rt, llm_client=llm_mock)

        steps = [
            ProcedureStep(
                step_number=1,
                action="scan",
                agent_role="security",
                resolved_agent_type="security_officer",
            ),
        ]
        proc = _make_procedure(steps=steps)

        await agent._execute_compound_replay(proc, "fallback")
        # No LLM calls should have happened
        llm_mock.complete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_compound_replay_result_assembly(self):
        sec_agent = _make_mock_agent_entry("sec-001")
        eng_agent = _make_mock_agent_entry("eng-001")
        registry = MagicMock()
        registry.get_by_pool = MagicMock(
            side_effect=lambda pool: [sec_agent] if "security" in pool else [eng_agent]
        )

        bus = AsyncMock()
        bus.send = AsyncMock(
            side_effect=[
                IntentResult(intent_id="i1", agent_id="sec-001", success=True, result="AAA"),
                IntentResult(intent_id="i2", agent_id="eng-001", success=True, result="BBB"),
            ]
        )
        rt = _make_mock_runtime(intent_bus=bus, registry=registry)
        agent = _make_cognitive_agent(runtime=rt)
        proc = _make_compound_procedure()

        result = await agent._execute_compound_replay(proc, "fallback")
        assert result["result"] == "AAA\n\nBBB"

    @pytest.mark.asyncio
    async def test_compound_replay_steps_dispatched_count(self):
        sec_agent = _make_mock_agent_entry("sec-001")
        registry = MagicMock()
        registry.get_by_pool = MagicMock(return_value=[sec_agent])

        bus = AsyncMock()
        bus.send = AsyncMock(
            return_value=IntentResult(
                intent_id="i1", agent_id="sec-001", success=True, result="ok"
            )
        )
        rt = _make_mock_runtime(intent_bus=bus, registry=registry)
        agent = _make_cognitive_agent(runtime=rt)

        steps = [
            ProcedureStep(step_number=1, action="local step"),  # no role = local
            ProcedureStep(
                step_number=2,
                action="remote step",
                agent_role="security",
                resolved_agent_type="security_officer",
            ),
        ]
        proc = _make_procedure(steps=steps)

        result = await agent._execute_compound_replay(proc, "fallback")
        assert result["steps_dispatched"] == 1


# ===================================================================
# Test Class 5: TestCompoundStepReplayHandler (5 tests)
# ===================================================================


class TestCompoundStepReplayHandler:
    """Tests for _handle_compound_step_replay()."""

    @pytest.mark.asyncio
    async def test_handler_returns_step_text(self):
        agent = _make_cognitive_agent()
        intent = _make_intent(
            intent_type="compound_step_replay",
            params={"step_text": "**Step 1:** Analyze code", "procedure_id": "p1", "step_number": 1},
        )

        result = await agent._handle_compound_step_replay(intent)
        assert result.result == "**Step 1:** Analyze code"

    @pytest.mark.asyncio
    async def test_handler_success_true(self):
        agent = _make_cognitive_agent()
        intent = _make_intent(
            intent_type="compound_step_replay",
            params={"step_text": "text", "procedure_id": "p1", "step_number": 1},
        )

        result = await agent._handle_compound_step_replay(intent)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_handler_confidence_one(self):
        agent = _make_cognitive_agent()
        intent = _make_intent(
            intent_type="compound_step_replay",
            params={"step_text": "text", "procedure_id": "p1", "step_number": 1},
        )

        result = await agent._handle_compound_step_replay(intent)
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_handler_preserves_procedure_id(self):
        agent = _make_cognitive_agent()
        intent = _make_intent(
            intent_type="compound_step_replay",
            params={"step_text": "text", "procedure_id": "proc-789", "step_number": 3},
        )

        # Handler reads procedure_id from params (debug logging)
        result = await agent._handle_compound_step_replay(intent)
        assert result.success is True
        # The handler doesn't expose procedure_id on the result, but it shouldn't crash
        assert result.result == "text"

    @pytest.mark.asyncio
    async def test_handler_no_llm_invocation(self):
        llm_mock = AsyncMock()
        agent = _make_cognitive_agent(llm_client=llm_mock)
        intent = _make_intent(
            intent_type="compound_step_replay",
            params={"step_text": "text", "procedure_id": "p1", "step_number": 1},
        )

        await agent._handle_compound_step_replay(intent)
        llm_mock.complete.assert_not_awaited()


# ===================================================================
# Test Class 6: TestHandleIntentCompound (8 tests)
# ===================================================================


class TestHandleIntentCompound:
    """Tests for compound branch in handle_intent()."""

    @pytest.mark.asyncio
    async def test_handle_intent_compound_dispatch_success(self):
        proc = _make_compound_procedure()
        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[{"id": proc.id, "score": 0.9}])
        store.get = AsyncMock(return_value=proc)

        sec_agent = _make_mock_agent_entry("sec-001")
        eng_agent = _make_mock_agent_entry("eng-001")
        registry = MagicMock()
        registry.get_by_pool = MagicMock(
            side_effect=lambda pool: [sec_agent] if "security" in pool else [eng_agent]
        )

        bus = AsyncMock()
        bus.send = AsyncMock(
            side_effect=[
                IntentResult(intent_id="i1", agent_id="sec-001", success=True, result="sec done"),
                IntentResult(intent_id="i2", agent_id="eng-001", success=True, result="eng done"),
            ]
        )
        rt = _make_mock_runtime(intent_bus=bus, registry=registry)
        agent = _make_cognitive_agent(runtime=rt, procedure_store=store)
        intent = _make_intent(intent_type="security_review")

        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success is True
        assert "sec done" in result.result
        assert "eng done" in result.result

    @pytest.mark.asyncio
    async def test_handle_intent_compound_records_completion(self):
        proc = _make_compound_procedure()
        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[{"id": proc.id, "score": 0.9}])
        store.get = AsyncMock(return_value=proc)

        sec_agent = _make_mock_agent_entry("sec-001")
        eng_agent = _make_mock_agent_entry("eng-001")
        registry = MagicMock()
        registry.get_by_pool = MagicMock(
            side_effect=lambda pool: [sec_agent] if "security" in pool else [eng_agent]
        )

        bus = AsyncMock()
        bus.send = AsyncMock(
            side_effect=[
                IntentResult(intent_id="i1", agent_id="sec-001", success=True, result="ok"),
                IntentResult(intent_id="i2", agent_id="eng-001", success=True, result="ok"),
            ]
        )
        rt = _make_mock_runtime(intent_bus=bus, registry=registry)
        agent = _make_cognitive_agent(runtime=rt, procedure_store=store)
        intent = _make_intent(intent_type="security_review")

        await agent.handle_intent(intent)
        store.record_completion.assert_awaited_once_with(proc.id)

    @pytest.mark.asyncio
    async def test_handle_intent_compound_emits_task_event(self):
        proc = _make_compound_procedure()
        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[{"id": proc.id, "score": 0.9}])
        store.get = AsyncMock(return_value=proc)

        sec_agent = _make_mock_agent_entry("sec-001")
        eng_agent = _make_mock_agent_entry("eng-001")
        registry = MagicMock()
        registry.get_by_pool = MagicMock(
            side_effect=lambda pool: [sec_agent] if "security" in pool else [eng_agent]
        )

        bus = AsyncMock()
        bus.send = AsyncMock(
            side_effect=[
                IntentResult(intent_id="i1", agent_id="sec-001", success=True, result="ok"),
                IntentResult(intent_id="i2", agent_id="eng-001", success=True, result="ok"),
            ]
        )
        rt = _make_mock_runtime(intent_bus=bus, registry=registry)
        agent = _make_cognitive_agent(runtime=rt, procedure_store=store)
        intent = _make_intent(intent_type="security_review")

        await agent.handle_intent(intent)
        rt._emit_event.assert_called_once()
        call_args = rt._emit_event.call_args
        event_data = call_args[0][1]
        assert event_data["compound_dispatched"] is True
        assert event_data["used_procedure"] is True

    @pytest.mark.asyncio
    async def test_handle_intent_compound_degradation_falls_through(self):
        proc = _make_compound_procedure()
        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[{"id": proc.id, "score": 0.9}])
        store.get = AsyncMock(return_value=proc)

        registry = MagicMock()
        registry.get_by_pool = MagicMock(return_value=[])
        registry.get_by_capability = MagicMock(return_value=[])
        bus = AsyncMock()
        rt = _make_mock_runtime(intent_bus=bus, registry=registry)
        agent = _make_cognitive_agent(runtime=rt, procedure_store=store)
        intent = _make_intent(intent_type="security_review")

        result = await agent.handle_intent(intent)
        # Degradation falls through to act() — still succeeds with text fallback
        assert result is not None
        assert result.success is True

    @pytest.mark.asyncio
    async def test_handle_intent_compound_degradation_records_fallback(self):
        proc = _make_compound_procedure()
        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[{"id": proc.id, "score": 0.9}])
        store.get = AsyncMock(return_value=proc)

        registry = MagicMock()
        registry.get_by_pool = MagicMock(return_value=[])
        registry.get_by_capability = MagicMock(return_value=[])
        bus = AsyncMock()
        rt = _make_mock_runtime(intent_bus=bus, registry=registry, procedure_store=store)
        agent = _make_cognitive_agent(runtime=rt)
        intent = _make_intent(intent_type="security_review")

        await agent.handle_intent(intent)
        # _last_fallback_info is consumed by the event emission, so check the event
        # Find the PROCEDURE_FALLBACK_LEARNING event call
        fallback_calls = [
            c for c in rt._emit_event.call_args_list
            if len(c[0]) >= 2 and "compound_agent_unavailable" in str(c[0][1].get("fallback_type", ""))
        ]
        assert len(fallback_calls) == 1

    @pytest.mark.asyncio
    async def test_handle_intent_non_compound_unchanged(self):
        proc = _make_procedure()  # No agent_role
        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[{"id": proc.id, "score": 0.9}])
        store.get = AsyncMock(return_value=proc)

        rt = _make_mock_runtime()
        agent = _make_cognitive_agent(runtime=rt, procedure_store=store)
        intent = _make_intent(intent_type="test_intent")

        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success is True
        # Non-compound path — act() called normally

    @pytest.mark.asyncio
    async def test_handle_intent_compound_step_replay_intent(self):
        agent = _make_cognitive_agent()
        intent = IntentMessage(
            intent="compound_step_replay",
            params={"step_text": "**Step 1:** Do stuff", "procedure_id": "p1", "step_number": 1},
            target_agent_id="test-agent-001",
        )

        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success is True
        assert result.result == "**Step 1:** Do stuff"

    @pytest.mark.asyncio
    async def test_handle_intent_compound_step_replay_early_return(self):
        llm_mock = AsyncMock()
        agent = _make_cognitive_agent(llm_client=llm_mock)
        intent = IntentMessage(
            intent="compound_step_replay",
            params={"step_text": "step text", "procedure_id": "p1", "step_number": 1},
            target_agent_id="test-agent-001",
        )

        result = await agent.handle_intent(intent)
        # Should NOT have called decide()/act() — early return
        llm_mock.complete.assert_not_awaited()
        assert result.success is True


# ===================================================================
# Test Class 7: TestFormatSingleStep (4 tests)
# ===================================================================


class TestFormatSingleStep:
    """Tests for _format_single_step()."""

    def test_format_with_role(self):
        agent = _make_cognitive_agent()
        step = ProcedureStep(step_number=1, action="Analyze code", agent_role="security_analysis")

        result = agent._format_single_step(step)
        assert "[security_analysis]" in result
        assert "**Step 1" in result
        assert "Analyze code" in result

    def test_format_without_role(self):
        agent = _make_cognitive_agent()
        step = ProcedureStep(step_number=1, action="Analyze code")

        result = agent._format_single_step(step)
        assert "[" not in result
        assert "**Step 1:**" in result

    def test_format_with_expected_output(self):
        agent = _make_cognitive_agent()
        step = ProcedureStep(
            step_number=1, action="Scan", expected_output="vulnerability report"
        )

        result = agent._format_single_step(step)
        assert "\u2192 Expected:" in result
        assert "vulnerability report" in result

    def test_format_without_expected_output(self):
        agent = _make_cognitive_agent()
        step = ProcedureStep(step_number=1, action="Do stuff")

        result = agent._format_single_step(step)
        assert "Expected:" not in result


# ===================================================================
# Test Class 8: TestFormatProcedureReplayDRY (3 tests)
# ===================================================================


class TestFormatProcedureReplayDRY:
    """Tests for _format_procedure_replay() DRY refactor."""

    def test_format_replay_uses_format_single_step(self):
        agent = _make_cognitive_agent()
        proc = _make_procedure(
            steps=[ProcedureStep(step_number=1, action="Do x")]
        )

        with patch.object(agent, "_format_single_step", wraps=agent._format_single_step) as spy:
            agent._format_procedure_replay(proc, 0.95)
            spy.assert_called_once()

    def test_format_replay_compound_output_unchanged(self):
        agent = _make_cognitive_agent()
        steps = [
            ProcedureStep(step_number=1, action="Analyze", agent_role="security"),
            ProcedureStep(step_number=2, action="Fix", agent_role="engineering"),
        ]
        proc = _make_procedure(steps=steps, name="CompoundProc", description="Desc")

        output = agent._format_procedure_replay(proc, 0.9)
        assert "[Procedure Replay: CompoundProc]" in output
        assert "**Step 1 [security]:** Analyze" in output
        assert "**Step 2 [engineering]:** Fix" in output

    def test_format_replay_non_compound_output_unchanged(self):
        agent = _make_cognitive_agent()
        steps = [
            ProcedureStep(
                step_number=1,
                action="Do thing",
                expected_output="thing done",
                fallback_action="try again",
            )
        ]
        proc = _make_procedure(steps=steps, name="SimpleProc", description="Simple")

        output = agent._format_procedure_replay(proc, 0.8)
        assert "[Procedure Replay: SimpleProc]" in output
        assert "**Step 1:** Do thing" in output
        assert "\u2192 Expected: thing done" in output
        assert "\u26a0 Fallback: try again" in output


# ===================================================================
# Test Class 9: TestCompoundReplayEndToEnd (4 tests)
# ===================================================================


class TestCompoundReplayEndToEnd:
    """End-to-end compound replay tests."""

    @pytest.mark.asyncio
    async def test_end_to_end_extract_store_replay_dispatch(self):
        """Extract → store → match → detect compound → dispatch → assembled."""
        proc = _make_compound_procedure()
        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[{"id": proc.id, "score": 0.95}])
        store.get = AsyncMock(return_value=proc)

        sec_agent = _make_mock_agent_entry("sec-001")
        eng_agent = _make_mock_agent_entry("eng-001")
        registry = MagicMock()
        registry.get_by_pool = MagicMock(
            side_effect=lambda pool: [sec_agent] if "security" in pool else [eng_agent]
        )

        bus = AsyncMock()
        bus.send = AsyncMock(
            side_effect=[
                IntentResult(intent_id="i1", agent_id="sec-001", success=True, result="scan done"),
                IntentResult(intent_id="i2", agent_id="eng-001", success=True, result="fix done"),
            ]
        )
        rt = _make_mock_runtime(intent_bus=bus, registry=registry)
        agent = _make_cognitive_agent(runtime=rt, procedure_store=store)
        intent = _make_intent(intent_type="security_review")

        result = await agent.handle_intent(intent)
        assert result.success is True
        assert "scan done" in result.result
        assert "fix done" in result.result
        assert bus.send.await_count == 2

    @pytest.mark.asyncio
    async def test_end_to_end_degradation_to_single_agent(self):
        """Target agent unavailable → single-agent text replay."""
        proc = _make_compound_procedure()
        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[{"id": proc.id, "score": 0.9}])
        store.get = AsyncMock(return_value=proc)

        registry = MagicMock()
        registry.get_by_pool = MagicMock(return_value=[])
        registry.get_by_capability = MagicMock(return_value=[])
        bus = AsyncMock()
        rt = _make_mock_runtime(intent_bus=bus, registry=registry)
        agent = _make_cognitive_agent(runtime=rt, procedure_store=store)
        intent = _make_intent(intent_type="security_review")

        result = await agent.handle_intent(intent)
        assert result.success is True
        # Degraded path — text fallback via act()
        bus.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_end_to_end_near_miss_capture_on_degradation(self):
        proc = _make_compound_procedure()
        store = _make_store_mock()
        store.find_matching = AsyncMock(return_value=[{"id": proc.id, "score": 0.9}])
        store.get = AsyncMock(return_value=proc)

        registry = MagicMock()
        registry.get_by_pool = MagicMock(return_value=[])
        registry.get_by_capability = MagicMock(return_value=[])
        bus = AsyncMock()
        rt = _make_mock_runtime(intent_bus=bus, registry=registry, procedure_store=store)
        agent = _make_cognitive_agent(runtime=rt)
        intent = _make_intent(intent_type="security_review")

        await agent.handle_intent(intent)
        # _last_fallback_info consumed by event emission — verify via emitted event
        fallback_calls = [
            c for c in rt._emit_event.call_args_list
            if len(c[0]) >= 2 and isinstance(c[0][1], dict) and c[0][1].get("fallback_type") == "compound_agent_unavailable"
        ]
        assert len(fallback_calls) == 1
        assert "procedure_id" in fallback_calls[0][0][1]

    @pytest.mark.asyncio
    async def test_end_to_end_config_timeout(self):
        """Dispatched intents use COMPOUND_STEP_TIMEOUT_SECONDS from config."""
        from probos.config import COMPOUND_STEP_TIMEOUT_SECONDS

        sec_agent = _make_mock_agent_entry("sec-001")
        eng_agent = _make_mock_agent_entry("eng-001")
        registry = MagicMock()
        registry.get_by_pool = MagicMock(
            side_effect=lambda pool: [sec_agent] if "security" in pool else [eng_agent]
        )

        bus = AsyncMock()
        bus.send = AsyncMock(
            side_effect=[
                IntentResult(intent_id="i1", agent_id="sec-001", success=True, result="ok"),
                IntentResult(intent_id="i2", agent_id="eng-001", success=True, result="ok"),
            ]
        )
        rt = _make_mock_runtime(intent_bus=bus, registry=registry)
        agent = _make_cognitive_agent(runtime=rt)
        proc = _make_compound_procedure()

        await agent._execute_compound_replay(proc, "fallback")

        # Verify dispatched IntentMessages used the config timeout
        for call in bus.send.call_args_list:
            sent_intent = call[0][0]
            assert sent_intent.ttl_seconds == COMPOUND_STEP_TIMEOUT_SECONDS
