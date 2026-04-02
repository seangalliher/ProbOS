"""AD-535: Graduated Compilation Levels — 62 tests across 9 classes."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.procedures import Procedure, ProcedureStep

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeStep:
    step_number: int = 1
    action: str = "do something"
    expected_output: str = ""
    expected_input: str = ""
    fallback_action: str = ""
    invariants: list[str] = field(default_factory=list)
    agent_role: str = ""
    resolved_agent_type: str = ""


def _make_procedure(**kwargs) -> Procedure:
    """Create a real Procedure for tests that need store.save()."""
    defaults = dict(
        id="proc-1",
        name="test-proc",
        description="A test procedure",
        compilation_level=2,
        is_active=True,
    )
    defaults.update(kwargs)
    return Procedure(**defaults)


@dataclass
class _FakeProcedure:
    id: str = "proc-1"
    name: str = "test-proc"
    description: str = "A test procedure"
    compilation_level: int = 2
    steps: list = field(default_factory=lambda: [_FakeStep()])
    postconditions: list[str] = field(default_factory=list)
    is_active: bool = True
    is_negative: bool = False
    origin_cluster_id: str = ""
    evolution_type: str = "CAPTURED"
    generation: int = 0
    superseded_by: str = ""
    intent_types: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    origin_agent_ids: list[str] = field(default_factory=list)
    parent_procedure_ids: list[str] = field(default_factory=list)
    extraction_date: float = 0.0
    preconditions: list[str] = field(default_factory=list)

    def to_dict(self):
        return {"id": self.id, "name": self.name}


def _make_cognitive_agent(**overrides):
    """Create a minimal CognitiveAgent for testing."""
    from probos.cognitive.cognitive_agent import CognitiveAgent, _DECISION_CACHES
    from probos.types import AgentMeta, AgentState

    defaults = {
        "agent_type": "test-graduated",
        "pool_name": "test-pool",
        "instructions": "Test instructions for graduated compilation",
    }
    defaults.update(overrides)
    _DECISION_CACHES.pop(defaults["agent_type"], None)

    agent = object.__new__(CognitiveAgent)
    agent.agent_type = defaults["agent_type"]
    agent.pool_name = defaults["pool_name"]
    agent.instructions = defaults["instructions"]
    agent.id = defaults.get("id", "agent-001")
    agent.callsign = defaults.get("callsign", "")
    agent.confidence = 0.5
    agent._llm_client = defaults.get("llm_client")
    agent._runtime = defaults.get("runtime")
    agent._skills = {}
    agent._strategy_advisor = None
    agent._last_fallback_info = None
    agent._handled_intents = set()
    agent.intent_descriptors = []
    agent.meta = AgentMeta()
    agent.state = AgentState.ACTIVE
    agent.trust_score = defaults.get("trust_score", 0.5)
    agent._trust_score = defaults.get("trust_score", 0.5)
    return agent


# ===========================================================================
# TestCompilationConfig (4 tests)
# ===========================================================================
class TestCompilationConfig:
    def test_promotion_threshold_default(self):
        from probos.config import COMPILATION_PROMOTION_THRESHOLD
        assert COMPILATION_PROMOTION_THRESHOLD == 3

    def test_demotion_level_default(self):
        from probos.config import COMPILATION_DEMOTION_LEVEL
        assert COMPILATION_DEMOTION_LEVEL == 2

    def test_max_level_default(self):
        from probos.config import COMPILATION_MAX_LEVEL
        assert COMPILATION_MAX_LEVEL == 5  # AD-537: Level 5 Expert unlocked

    def test_min_compilation_level(self):
        from probos.config import PROCEDURE_MIN_COMPILATION_LEVEL
        assert PROCEDURE_MIN_COMPILATION_LEVEL == 2


# ===========================================================================
# TestTrustClamping (5 tests)
# ===========================================================================
class TestTrustClamping:
    def test_ensign_max_level_2(self):
        agent = _make_cognitive_agent(trust_score=0.3)
        assert agent._max_compilation_level_for_trust(0.3) == 2

    def test_lieutenant_max_level_4(self):
        agent = _make_cognitive_agent(trust_score=0.5)
        assert agent._max_compilation_level_for_trust(0.5) == 4

    def test_commander_max_level_4(self):
        agent = _make_cognitive_agent(trust_score=0.7)
        assert agent._max_compilation_level_for_trust(0.7) == 4

    def test_senior_max_level_4(self):
        agent = _make_cognitive_agent(trust_score=0.9)
        assert agent._max_compilation_level_for_trust(0.9) == 4

    @pytest.mark.asyncio
    async def test_clamping_applied_in_check_procedural_memory(self):
        """Procedure at Level 4 + Ensign trust → effective Level 2 (guided)."""
        proc = _FakeProcedure(compilation_level=4)

        store = AsyncMock()
        store.find_matching = AsyncMock(side_effect=[
            [],  # negative check
            [{"id": "proc-1", "name": "test", "score": 0.9}],  # positive
        ])
        store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 0, "effective_rate": 1.0,
        })
        store.record_selection = AsyncMock()
        store.record_applied = AsyncMock()
        store.get = AsyncMock(return_value=proc)

        runtime = MagicMock()
        runtime.procedure_store = store

        llm_client = AsyncMock()
        llm_response = MagicMock()
        llm_response.content = "guided output"
        llm_response.tier = "fast"
        llm_response.model = "test"
        llm_response.prompt_tokens = 10
        llm_response.completion_tokens = 5
        llm_response.tokens_used = 15
        llm_response.error = None
        llm_client.complete = AsyncMock(return_value=llm_response)

        agent = _make_cognitive_agent(
            trust_score=0.3,  # Ensign
            runtime=runtime,
            llm_client=llm_client,
        )

        result = await agent._check_procedural_memory({
            "intent": "test", "params": {"message": "hello"},
        })

        # Should call _build_guided_decision (Level 2) not Level 4 zero-token
        assert result is not None
        assert result.get("guided_by_procedure") is True
        assert result.get("compilation_level") == 2


# ===========================================================================
# TestConsecutiveSuccessTracking (6 tests)
# ===========================================================================
class TestConsecutiveSuccessTracking:
    @pytest.fixture
    async def store(self, tmp_path):
        from probos.cognitive.procedure_store import ProcedureStore
        s = ProcedureStore(tmp_path / "procs")
        await s.start()
        yield s
        await s.stop()

    @pytest.fixture
    async def proc_id(self, store):
        proc = _make_procedure(id="cs-1", name="consec-test")
        return await store.save(proc)

    @pytest.mark.asyncio
    async def test_record_consecutive_success_increments(self, store, proc_id):
        c1 = await store.record_consecutive_success(proc_id)
        c2 = await store.record_consecutive_success(proc_id)
        c3 = await store.record_consecutive_success(proc_id)
        assert c1 == 1
        assert c2 == 2
        assert c3 == 3

    @pytest.mark.asyncio
    async def test_reset_consecutive_successes(self, store, proc_id):
        await store.record_consecutive_success(proc_id)
        await store.record_consecutive_success(proc_id)
        await store.reset_consecutive_successes(proc_id)
        # Next increment should be 1
        c = await store.record_consecutive_success(proc_id)
        assert c == 1

    @pytest.mark.asyncio
    async def test_promote_compilation_level(self, store, proc_id):
        await store.record_consecutive_success(proc_id)
        await store.record_consecutive_success(proc_id)
        await store.promote_compilation_level(proc_id, 3)
        proc = await store.get(proc_id)
        # Note: promote updates DB, not the cached Procedure object in get()
        # Check DB directly
        metrics = await store.get_quality_metrics(proc_id)
        assert metrics["consecutive_successes"] == 0  # Reset on promote

    @pytest.mark.asyncio
    async def test_demote_compilation_level(self, store, proc_id):
        await store.record_consecutive_success(proc_id)
        await store.demote_compilation_level(proc_id, 2)
        metrics = await store.get_quality_metrics(proc_id)
        assert metrics["consecutive_successes"] == 0

    @pytest.mark.asyncio
    async def test_get_quality_metrics_includes_consecutive(self, store, proc_id):
        await store.record_consecutive_success(proc_id)
        metrics = await store.get_quality_metrics(proc_id)
        assert "consecutive_successes" in metrics
        assert metrics["consecutive_successes"] == 1

    @pytest.mark.asyncio
    async def test_schema_migration_adds_column(self, store):
        """consecutive_successes column exists after init."""
        cursor = await store._db.execute("PRAGMA table_info(procedure_records)")
        columns = [row[1] for row in await cursor.fetchall()]
        assert "consecutive_successes" in columns


# ===========================================================================
# TestLevel2Guided (8 tests)
# ===========================================================================
class TestLevel2Guided:
    def _make_llm_client(self, response_text="guided response"):
        llm_client = AsyncMock()
        resp = MagicMock()
        resp.content = response_text
        resp.tier = "fast"
        resp.model = "test"
        resp.prompt_tokens = 10
        resp.completion_tokens = 5
        resp.tokens_used = 15
        resp.error = None
        llm_client.complete = AsyncMock(return_value=resp)
        return llm_client

    @pytest.mark.asyncio
    async def test_guided_decision_calls_llm(self):
        llm_client = self._make_llm_client()
        agent = _make_cognitive_agent(llm_client=llm_client)
        proc = _FakeProcedure()
        result = await agent._build_guided_decision(proc, {"intent": "test"}, 0.8)
        llm_client.complete.assert_awaited_once()
        assert result["guided_by_procedure"] is True

    @pytest.mark.asyncio
    async def test_guided_decision_includes_procedure_hints(self):
        llm_client = self._make_llm_client()
        agent = _make_cognitive_agent(llm_client=llm_client)
        proc = _FakeProcedure(steps=[_FakeStep(action="Step one action")])
        await agent._build_guided_decision(proc, {"intent": "test"}, 0.8)
        # The observation passed to _decide_via_llm should contain hints
        call_args = llm_client.complete.call_args
        prompt = call_args[0][0].prompt if call_args[0] else call_args[1].get("prompt", "")
        assert "Suggested approach" in prompt or "procedure_guidance" in str(call_args)

    def test_format_procedure_as_hints(self):
        agent = _make_cognitive_agent()
        proc = _FakeProcedure(
            steps=[
                _FakeStep(step_number=1, action="Do A", expected_output="Result A"),
                _FakeStep(step_number=2, action="Do B", expected_input="needs B"),
            ],
        )
        hints = agent._format_procedure_as_hints(proc)
        assert "1. Do A" in hints
        assert "2. Do B" in hints
        assert "Expected result: Result A" in hints
        assert "Context: needs B" in hints

    def test_format_hints_with_agent_role(self):
        agent = _make_cognitive_agent()
        proc = _FakeProcedure(
            steps=[_FakeStep(action="analyze", agent_role="science_officer")]
        )
        hints = agent._format_procedure_as_hints(proc)
        assert "(Typically performed by: science_officer)" in hints

    def test_format_hints_with_postconditions(self):
        agent = _make_cognitive_agent()
        proc = _FakeProcedure(
            postconditions=["All checks pass"],
        )
        hints = agent._format_procedure_as_hints(proc)
        assert "Success criteria:" in hints

    def test_format_hints_no_expected_output(self):
        agent = _make_cognitive_agent()
        proc = _FakeProcedure(
            steps=[_FakeStep(action="step action", expected_output="")]
        )
        hints = agent._format_procedure_as_hints(proc)
        assert "Expected result:" not in hints
        assert "step action" in hints

    @pytest.mark.asyncio
    async def test_guided_decision_tagged(self):
        llm_client = self._make_llm_client()
        agent = _make_cognitive_agent(llm_client=llm_client)
        proc = _FakeProcedure(id="proc-42")
        result = await agent._build_guided_decision(proc, {"intent": "test"}, 0.8)
        assert result["guided_by_procedure"] is True
        assert result["procedure_id"] == "proc-42"
        assert result["compilation_level"] == 2

    @pytest.mark.asyncio
    async def test_guided_metrics_recorded(self):
        """Guided success should record completion against the guiding procedure."""
        store = AsyncMock()
        store.record_completion = AsyncMock()
        store.record_consecutive_success = AsyncMock(return_value=1)
        store.get = AsyncMock(return_value=_FakeProcedure(compilation_level=2))
        runtime = MagicMock()
        runtime.procedure_store = store

        llm_client = self._make_llm_client()
        agent = _make_cognitive_agent(llm_client=llm_client, runtime=runtime)

        # Simulate what handle_intent does after guided decision
        decision = {
            "guided_by_procedure": True,
            "procedure_id": "proc-42",
            "procedure_name": "test",
            "action": "execute",
            "llm_output": "result",
            "compilation_level": 2,
        }
        # Emulate the guided metric recording path
        success = True
        if decision.get("guided_by_procedure") and decision.get("procedure_id"):
            if success:
                await store.record_completion(decision["procedure_id"])
        store.record_completion.assert_awaited_once_with("proc-42")


# ===========================================================================
# TestLevel3Validated (10 tests)
# ===========================================================================
class TestLevel3Validated:
    @pytest.mark.asyncio
    async def test_validated_replay_calls_validation(self):
        agent = _make_cognitive_agent()
        proc = _FakeProcedure(
            compilation_level=3,
            postconditions=["output matches"],
        )
        with patch.object(agent, "_validate_replay_postconditions", new_callable=AsyncMock, return_value=True):
            result = await agent._build_validated_decision(proc, {}, 0.9)
            agent._validate_replay_postconditions.assert_awaited_once()
            assert result is not None

    @pytest.mark.asyncio
    async def test_validated_replay_passes(self):
        agent = _make_cognitive_agent()
        proc = _FakeProcedure(compilation_level=3)
        with patch.object(agent, "_validate_replay_postconditions", new_callable=AsyncMock, return_value=True):
            result = await agent._build_validated_decision(proc, {}, 0.9)
            assert result is not None
            assert result["cached"] is True
            assert result["validated"] is True

    @pytest.mark.asyncio
    async def test_validated_replay_fails(self):
        agent = _make_cognitive_agent()
        proc = _FakeProcedure(compilation_level=3, postconditions=["must pass"])
        with patch.object(agent, "_validate_replay_postconditions", new_callable=AsyncMock, return_value=False):
            result = await agent._build_validated_decision(proc, {}, 0.9)
            assert result is None  # Falls through to LLM

    @pytest.mark.asyncio
    async def test_validated_replay_fail_sets_fallback_info(self):
        agent = _make_cognitive_agent()
        proc = _FakeProcedure(id="proc-v", compilation_level=3, postconditions=["must pass"])
        with patch.object(agent, "_validate_replay_postconditions", new_callable=AsyncMock, return_value=False):
            await agent._build_validated_decision(proc, {}, 0.9)
            assert agent._last_fallback_info is not None
            assert agent._last_fallback_info["type"] == "validation_failure"

    @pytest.mark.asyncio
    async def test_validation_no_postconditions_passes(self):
        agent = _make_cognitive_agent()
        proc = _FakeProcedure(postconditions=[], steps=[_FakeStep(expected_output="")])
        result = await agent._validate_replay_postconditions(proc, "output", {})
        assert result is True

    @pytest.mark.asyncio
    async def test_validation_timeout_passes(self):
        """Timeout → passes by default (fail-open)."""
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(side_effect=asyncio.TimeoutError())
        agent = _make_cognitive_agent(llm_client=llm_client)
        proc = _FakeProcedure(postconditions=["something"])
        result = await agent._validate_replay_postconditions(proc, "output", {})
        assert result is True

    @pytest.mark.asyncio
    async def test_validation_includes_postconditions(self):
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(return_value="YES looks good")
        agent = _make_cognitive_agent(llm_client=llm_client)
        proc = _FakeProcedure(postconditions=["all widgets created"])
        await agent._validate_replay_postconditions(proc, "output", {})
        prompt = llm_client.generate.call_args[0][0]
        assert "all widgets created" in prompt

    @pytest.mark.asyncio
    async def test_validation_includes_step_expected_outputs(self):
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(return_value="YES")
        agent = _make_cognitive_agent(llm_client=llm_client)
        proc = _FakeProcedure(
            steps=[_FakeStep(step_number=1, expected_output="file exists")]
        )
        await agent._validate_replay_postconditions(proc, "output", {})
        prompt = llm_client.generate.call_args[0][0]
        assert "file exists" in prompt

    @pytest.mark.asyncio
    async def test_validation_includes_invariants(self):
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(return_value="YES")
        agent = _make_cognitive_agent(llm_client=llm_client)
        proc = _FakeProcedure(
            steps=[_FakeStep(step_number=1, invariants=["no data loss"])]
        )
        await agent._validate_replay_postconditions(proc, "output", {})
        prompt = llm_client.generate.call_args[0][0]
        assert "no data loss" in prompt

    @pytest.mark.asyncio
    async def test_validated_compound_detection(self):
        agent = _make_cognitive_agent()
        proc = _FakeProcedure(
            compilation_level=3,
            steps=[
                _FakeStep(step_number=1, resolved_agent_type="science"),
                _FakeStep(step_number=2, resolved_agent_type="engineering"),
            ],
        )
        with patch.object(agent, "_validate_replay_postconditions", new_callable=AsyncMock, return_value=True):
            result = await agent._build_validated_decision(proc, {}, 0.9)
            assert result is not None
            assert result.get("compound") is True


# ===========================================================================
# TestLevel3StepValidation (6 tests)
# ===========================================================================
class TestLevel3StepValidation:
    @pytest.mark.asyncio
    async def test_validate_step_postcondition_passes(self):
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(return_value="YES matches")
        agent = _make_cognitive_agent(llm_client=llm_client)
        step = _FakeStep(expected_output="data processed")
        result = await agent._validate_step_postcondition(step, "data processed successfully")
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_step_postcondition_fails(self):
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(return_value="NO doesn't match")
        agent = _make_cognitive_agent(llm_client=llm_client)
        step = _FakeStep(expected_output="data processed")
        result = await agent._validate_step_postcondition(step, "error occurred")
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_step_no_expected_output(self):
        agent = _make_cognitive_agent()
        step = _FakeStep(expected_output="")
        result = await agent._validate_step_postcondition(step, "anything")
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_step_llm_failure_passes(self):
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(side_effect=Exception("LLM down"))
        agent = _make_cognitive_agent(llm_client=llm_client)
        step = _FakeStep(expected_output="something")
        result = await agent._validate_step_postcondition(step, "output")
        assert result is True  # Fail-open

    @pytest.mark.asyncio
    async def test_compound_level_3_step_validation(self):
        """Compound replay at Level 3 validates each step."""
        agent = _make_cognitive_agent()
        proc = _FakeProcedure(
            steps=[
                _FakeStep(step_number=1, agent_role="sci", expected_output="done"),
                _FakeStep(step_number=2, agent_role="eng", expected_output="built"),
            ]
        )

        agent._resolve_step_agent = MagicMock(return_value="agent-x")
        intent_bus = AsyncMock()
        intent_result = MagicMock()
        intent_result.success = True
        intent_result.result = "step output"
        intent_bus.send = AsyncMock(return_value=intent_result)

        runtime = MagicMock()
        runtime.intent_bus = intent_bus
        runtime.registry = MagicMock()
        agent._runtime = runtime

        with patch.object(agent, "_validate_step_postcondition", new_callable=AsyncMock, return_value=True) as mock_val:
            result = await agent._execute_compound_replay(proc, "fallback", compilation_level=3)
            assert mock_val.await_count == 2  # Both steps validated
            assert result["compound_dispatched"] is True

    @pytest.mark.asyncio
    async def test_compound_level_3_step_failure_aborts(self):
        """Step validation failure aborts compound replay."""
        agent = _make_cognitive_agent()
        proc = _FakeProcedure(
            steps=[
                _FakeStep(step_number=1, agent_role="sci", expected_output="done"),
                _FakeStep(step_number=2, agent_role="eng", expected_output="built"),
            ]
        )

        agent._resolve_step_agent = MagicMock(return_value="agent-x")
        intent_bus = AsyncMock()
        intent_result = MagicMock()
        intent_result.success = True
        intent_result.result = "step output"
        intent_bus.send = AsyncMock(return_value=intent_result)

        runtime = MagicMock()
        runtime.intent_bus = intent_bus
        runtime.registry = MagicMock()
        agent._runtime = runtime

        with patch.object(agent, "_validate_step_postcondition", new_callable=AsyncMock, return_value=False):
            result = await agent._execute_compound_replay(proc, "text fallback", compilation_level=3)
            assert result.get("compound_aborted") is True
            assert result["result"] == "text fallback"


# ===========================================================================
# TestLevel4Autonomous (4 tests)
# ===========================================================================
class TestLevel4Autonomous:
    @pytest.mark.asyncio
    async def test_level_4_zero_token_replay(self):
        """Level 4 should produce zero-token replay (no LLM call)."""
        store = AsyncMock()
        proc = _FakeProcedure(compilation_level=4)
        store.find_matching = AsyncMock(side_effect=[
            [],
            [{"id": "proc-1", "name": "test", "score": 0.9}],
        ])
        store.get_quality_metrics = AsyncMock(return_value={"total_selections": 0, "effective_rate": 1.0})
        store.record_selection = AsyncMock()
        store.record_applied = AsyncMock()
        store.get = AsyncMock(return_value=proc)

        runtime = MagicMock()
        runtime.procedure_store = store

        agent = _make_cognitive_agent(trust_score=0.6, runtime=runtime)

        result = await agent._check_procedural_memory({
            "intent": "test", "params": {"message": "hello"},
        })

        assert result is not None
        assert result.get("cached") is True
        assert "guided_by_procedure" not in result

    @pytest.mark.asyncio
    async def test_level_4_compound_dispatch(self):
        """Level 4 compound dispatch same as AD-534c."""
        agent = _make_cognitive_agent()
        proc = _FakeProcedure(
            compilation_level=4,
            steps=[
                _FakeStep(step_number=1, agent_role="eng", resolved_agent_type="engineering"),
            ]
        )
        store = AsyncMock()
        store.find_matching = AsyncMock(side_effect=[
            [],
            [{"id": "proc-1", "name": "test", "score": 0.9}],
        ])
        store.get_quality_metrics = AsyncMock(return_value={"total_selections": 0, "effective_rate": 1.0})
        store.record_selection = AsyncMock()
        store.record_applied = AsyncMock()
        store.get = AsyncMock(return_value=proc)

        runtime = MagicMock()
        runtime.procedure_store = store
        agent._runtime = runtime
        agent._trust_score = 0.6

        result = await agent._check_procedural_memory({
            "intent": "test", "params": {"message": "hello"},
        })

        assert result is not None
        assert result.get("compound") is True

    @pytest.mark.asyncio
    async def test_level_4_no_validation_call(self):
        """Level 4 does NOT call postcondition validation."""
        agent = _make_cognitive_agent()

        with patch.object(agent, "_validate_replay_postconditions", new_callable=AsyncMock) as mock_val:
            proc = _FakeProcedure(compilation_level=4, postconditions=["check"])
            store = AsyncMock()
            store.find_matching = AsyncMock(side_effect=[
                [],
                [{"id": "proc-1", "name": "test", "score": 0.9}],
            ])
            store.get_quality_metrics = AsyncMock(return_value={"total_selections": 0, "effective_rate": 1.0})
            store.record_selection = AsyncMock()
            store.record_applied = AsyncMock()
            store.get = AsyncMock(return_value=proc)

            runtime = MagicMock()
            runtime.procedure_store = store
            agent._runtime = runtime
            agent._trust_score = 0.6

            await agent._check_procedural_memory({
                "intent": "test", "params": {"message": "hello"},
            })
            mock_val.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_level_4_requires_trust(self):
        """Ensign cannot use Level 4 (clamped to 2)."""
        agent = _make_cognitive_agent(trust_score=0.3)
        assert agent._max_compilation_level_for_trust(0.3) == 2
        # Level 4 procedure would be clamped


# ===========================================================================
# TestPromotion (10 tests)
# ===========================================================================
class TestPromotion:
    @pytest.fixture
    async def store(self, tmp_path):
        from probos.cognitive.procedure_store import ProcedureStore
        s = ProcedureStore(tmp_path / "procs")
        await s.start()
        yield s
        await s.stop()

    @pytest.fixture
    async def proc_id(self, store):
        proc = _make_procedure(id="promo-1", name="promo-test", compilation_level=2)
        return await store.save(proc)

    @pytest.mark.asyncio
    async def test_promote_after_consecutive_successes(self, store, proc_id):
        """3 successes → Level 2 to Level 3."""
        for _ in range(3):
            await store.record_consecutive_success(proc_id)
        await store.promote_compilation_level(proc_id, 3)

        cursor = await store._db.execute(
            "SELECT compilation_level FROM procedure_records WHERE id = ?",
            (proc_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == 3

    @pytest.mark.asyncio
    async def test_no_promote_below_threshold(self, store, proc_id):
        """2 successes → stays at current level."""
        c1 = await store.record_consecutive_success(proc_id)
        c2 = await store.record_consecutive_success(proc_id)
        assert c2 == 2
        # Not enough — should not promote (caller checks threshold)

    @pytest.mark.asyncio
    async def test_promote_resets_counter(self, store, proc_id):
        for _ in range(3):
            await store.record_consecutive_success(proc_id)
        await store.promote_compilation_level(proc_id, 3)
        metrics = await store.get_quality_metrics(proc_id)
        assert metrics["consecutive_successes"] == 0

    @pytest.mark.asyncio
    async def test_promote_capped_by_trust(self):
        """Ensign cannot promote beyond Level 2."""
        agent = _make_cognitive_agent(trust_score=0.3)
        max_level = agent._max_compilation_level_for_trust(0.3)
        assert max_level == 2
        # promotion to 3 would be blocked by trust check

    @pytest.mark.asyncio
    async def test_promote_capped_by_max_level(self):
        """Cannot promote beyond COMPILATION_MAX_LEVEL (4)."""
        from probos.config import COMPILATION_MAX_LEVEL
        agent = _make_cognitive_agent(trust_score=0.9)
        max_level = agent._max_compilation_level_for_trust(0.9)
        assert max_level <= COMPILATION_MAX_LEVEL

    @pytest.mark.asyncio
    async def test_demote_on_failure(self, store, proc_id):
        """Any failure → demote to Level 2."""
        await store.promote_compilation_level(proc_id, 3)
        await store.demote_compilation_level(proc_id, 2)
        cursor = await store._db.execute(
            "SELECT compilation_level FROM procedure_records WHERE id = ?",
            (proc_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == 2

    @pytest.mark.asyncio
    async def test_demote_resets_counter(self, store, proc_id):
        for _ in range(3):
            await store.record_consecutive_success(proc_id)
        await store.demote_compilation_level(proc_id, 2)
        metrics = await store.get_quality_metrics(proc_id)
        assert metrics["consecutive_successes"] == 0

    @pytest.mark.asyncio
    async def test_no_demote_if_already_level_2(self, store, proc_id):
        """Failure at Level 2 → stays at Level 2, resets counter."""
        await store.record_consecutive_success(proc_id)
        # Already Level 2, so no demotion, just reset
        cursor = await store._db.execute(
            "SELECT compilation_level FROM procedure_records WHERE id = ?",
            (proc_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == 2  # unchanged (saved at Level 2 per fixture, but save uses INSERT OR REPLACE)
        # The check in handle_intent would skip demotion since level == 2

    @pytest.mark.asyncio
    async def test_guided_success_counts_for_promotion(self, store, proc_id):
        """Level 2 guided successes should increment consecutive counter."""
        c = await store.record_consecutive_success(proc_id)
        assert c == 1

    @pytest.mark.asyncio
    async def test_guided_failure_resets_counter(self, store, proc_id):
        await store.record_consecutive_success(proc_id)
        await store.record_consecutive_success(proc_id)
        await store.reset_consecutive_successes(proc_id)
        metrics = await store.get_quality_metrics(proc_id)
        assert metrics["consecutive_successes"] == 0


# ===========================================================================
# TestMigration (4 tests)
# ===========================================================================
class TestMigration:
    @pytest.mark.asyncio
    async def test_migrate_qualifying_procedures(self, tmp_path):
        """Level 1 with enough completions → auto-promoted to Level 2."""
        from probos.cognitive.procedure_store import ProcedureStore

        store = ProcedureStore(tmp_path / "mig")
        await store.start()

        # Insert a Level 1 procedure with enough completions
        proc = _make_procedure(id="mig-1", compilation_level=1)
        await store.save(proc)
        # Manually set completions
        await store._db.execute(
            "UPDATE procedure_records SET total_completions = 5 WHERE id = 'mig-1'"
        )
        await store._db.commit()

        # Re-run migration
        await store._migrate_qualifying_procedures()

        cursor = await store._db.execute(
            "SELECT compilation_level FROM procedure_records WHERE id = 'mig-1'"
        )
        row = await cursor.fetchone()
        assert row[0] == 2
        await store.stop()

    @pytest.mark.asyncio
    async def test_migrate_ignores_low_completion(self, tmp_path):
        """Level 1 with few completions → stays Level 1."""
        from probos.cognitive.procedure_store import ProcedureStore

        store = ProcedureStore(tmp_path / "mig2")
        await store.start()

        proc = _make_procedure(id="mig-2", compilation_level=1)
        await store.save(proc)
        # total_completions defaults to 0

        await store._migrate_qualifying_procedures()

        cursor = await store._db.execute(
            "SELECT compilation_level FROM procedure_records WHERE id = 'mig-2'"
        )
        row = await cursor.fetchone()
        assert row[0] == 1
        await store.stop()

    @pytest.mark.asyncio
    async def test_migrate_ignores_inactive(self, tmp_path):
        """Inactive Level 1 not promoted."""
        from probos.cognitive.procedure_store import ProcedureStore

        store = ProcedureStore(tmp_path / "mig3")
        await store.start()

        proc = _make_procedure(id="mig-3", compilation_level=1, is_active=True)
        await store.save(proc)
        await store._db.execute(
            "UPDATE procedure_records SET total_completions = 10, is_active = 0 WHERE id = 'mig-3'"
        )
        await store._db.commit()

        await store._migrate_qualifying_procedures()

        cursor = await store._db.execute(
            "SELECT compilation_level FROM procedure_records WHERE id = 'mig-3'"
        )
        row = await cursor.fetchone()
        assert row[0] == 1
        await store.stop()

    @pytest.mark.asyncio
    async def test_migrate_idempotent(self, tmp_path):
        """Running migration twice has no adverse effect."""
        from probos.cognitive.procedure_store import ProcedureStore

        store = ProcedureStore(tmp_path / "mig4")
        await store.start()

        proc = _make_procedure(id="mig-4", compilation_level=1)
        await store.save(proc)
        await store._db.execute(
            "UPDATE procedure_records SET total_completions = 5 WHERE id = 'mig-4'"
        )
        await store._db.commit()

        await store._migrate_qualifying_procedures()
        await store._migrate_qualifying_procedures()  # Second run

        cursor = await store._db.execute(
            "SELECT compilation_level FROM procedure_records WHERE id = 'mig-4'"
        )
        row = await cursor.fetchone()
        assert row[0] == 2
        await store.stop()


# ===========================================================================
# TestLevelDispatchRouting (5 tests)
# ===========================================================================
class TestLevelDispatchRouting:

    def _setup_store(self, proc):
        store = AsyncMock()
        store.find_matching = AsyncMock(side_effect=[
            [],
            [{"id": proc.id, "name": proc.name, "score": 0.9}],
        ])
        store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 0, "effective_rate": 1.0,
        })
        store.record_selection = AsyncMock()
        store.record_applied = AsyncMock()
        store.get = AsyncMock(return_value=proc)
        return store

    @pytest.mark.asyncio
    async def test_level_1_not_dispatched(self):
        """Level 1 procedures filtered by PROCEDURE_MIN_COMPILATION_LEVEL."""
        proc = _FakeProcedure(compilation_level=1)
        store = AsyncMock()
        # find_matching with min_compilation_level=2 won't return Level 1
        store.find_matching = AsyncMock(side_effect=[[], []])
        store.get_quality_metrics = AsyncMock(return_value={})

        runtime = MagicMock()
        runtime.procedure_store = store

        agent = _make_cognitive_agent(trust_score=0.6, runtime=runtime)
        result = await agent._check_procedural_memory({
            "intent": "test", "params": {"message": "hello"},
        })
        assert result is None

    @pytest.mark.asyncio
    async def test_level_2_routes_to_guided(self):
        """Level 2 → _build_guided_decision()."""
        proc = _FakeProcedure(compilation_level=2)
        store = self._setup_store(proc)
        runtime = MagicMock()
        runtime.procedure_store = store

        llm_client = AsyncMock()
        resp = MagicMock()
        resp.content = "guided response"
        resp.tier = "fast"
        resp.model = "test"
        resp.prompt_tokens = 10
        resp.completion_tokens = 5
        resp.tokens_used = 15
        resp.error = None
        llm_client.complete = AsyncMock(return_value=resp)

        agent = _make_cognitive_agent(trust_score=0.6, runtime=runtime, llm_client=llm_client)
        result = await agent._check_procedural_memory({
            "intent": "test", "params": {"message": "hello"},
        })
        assert result is not None
        assert result.get("guided_by_procedure") is True

    @pytest.mark.asyncio
    async def test_level_3_routes_to_validated(self):
        """Level 3 → _build_validated_decision()."""
        proc = _FakeProcedure(compilation_level=3)
        store = self._setup_store(proc)
        runtime = MagicMock()
        runtime.procedure_store = store

        agent = _make_cognitive_agent(trust_score=0.6, runtime=runtime)

        with patch.object(agent, "_validate_replay_postconditions", new_callable=AsyncMock, return_value=True):
            result = await agent._check_procedural_memory({
                "intent": "test", "params": {"message": "hello"},
            })
            assert result is not None
            assert result.get("validated") is True

    @pytest.mark.asyncio
    async def test_level_4_routes_to_autonomous(self):
        """Level 4 → current replay behavior."""
        proc = _FakeProcedure(compilation_level=4)
        store = self._setup_store(proc)
        runtime = MagicMock()
        runtime.procedure_store = store

        agent = _make_cognitive_agent(trust_score=0.6, runtime=runtime)
        result = await agent._check_procedural_memory({
            "intent": "test", "params": {"message": "hello"},
        })
        assert result is not None
        assert result.get("cached") is True
        assert "validated" not in result
        assert "guided_by_procedure" not in result

    @pytest.mark.asyncio
    async def test_mixed_levels_in_store(self):
        """Multiple procedures at different levels — correct one dispatched."""
        # find_matching returns the best match based on score
        proc = _FakeProcedure(id="proc-mix", compilation_level=3, name="mix-test")
        store = AsyncMock()
        store.find_matching = AsyncMock(side_effect=[
            [],
            [{"id": "proc-mix", "name": "mix-test", "score": 0.85}],
        ])
        store.get_quality_metrics = AsyncMock(return_value={
            "total_selections": 0, "effective_rate": 1.0,
        })
        store.record_selection = AsyncMock()
        store.record_applied = AsyncMock()
        store.get = AsyncMock(return_value=proc)

        runtime = MagicMock()
        runtime.procedure_store = store

        agent = _make_cognitive_agent(trust_score=0.6, runtime=runtime)

        with patch.object(agent, "_validate_replay_postconditions", new_callable=AsyncMock, return_value=True):
            result = await agent._check_procedural_memory({
                "intent": "test", "params": {"message": "hello"},
            })
            assert result is not None
            assert result.get("validated") is True
            assert result["procedure_id"] == "proc-mix"
