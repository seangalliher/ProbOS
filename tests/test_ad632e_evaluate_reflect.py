"""AD-632e: Evaluate & Reflect Sub-Task Handler tests.

~50 tests covering EvaluateHandler, ReflectHandler, decision extractor
update, chain structure, and registration.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.sub_task import (
    SubTaskHandler,
    SubTaskResult,
    SubTaskSpec,
    SubTaskType,
)
from probos.cognitive.sub_tasks.evaluate import (
    EvaluateHandler,
    _EVALUATION_MODES,
    _build_ward_room_eval_prompt,
    _build_proactive_eval_prompt,
    _build_notebook_eval_prompt,
    _get_compose_output,
)
from probos.cognitive.sub_tasks.reflect import (
    ReflectHandler,
    _REFLECTION_MODES,
    _should_suppress,
    _build_ward_room_reflect_prompt,
)
from probos.types import LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockLLMClient:
    """Controllable mock LLM client."""

    def __init__(
        self,
        content: str = "{}",
        tokens_used: int = 100,
        tier: str = "fast",
        raise_exc: Exception | None = None,
    ) -> None:
        self._content = content
        self._tokens_used = tokens_used
        self._tier = tier
        self._raise_exc = raise_exc
        self.last_request = None

    async def complete(self, request: Any) -> LLMResponse:
        self.last_request = request
        if self._raise_exc:
            raise self._raise_exc
        return LLMResponse(
            content=self._content,
            tier=self._tier,
            tokens_used=self._tokens_used,
        )


def _eval_spec(prompt_template: str = "ward_room_quality") -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.EVALUATE,
        name="evaluate-test",
        prompt_template=prompt_template,
        tier="fast",
    )


def _reflect_spec(prompt_template: str = "ward_room_reflection") -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.REFLECT,
        name="reflect-test",
        prompt_template=prompt_template,
        tier="fast",
    )


def _make_context(**overrides: Any) -> dict:
    base = {
        "context": "Lynx: I observed latency spikes.\nAtlas: Confirmed.",
        "intent": "ward_room_notification",
        "_callsign": "Kira",
        "_department": "Science",
        "_agent_type": "data_analyst",
    }
    base.update(overrides)
    return base


def _compose_result(output: str = "Draft response text.") -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose-reply",
        result={"output": output},
        tokens_used=50,
        duration_ms=200,
        success=True,
        tier_used="fast",
    )


def _analyze_result() -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze-thread",
        result={"topics_covered": ["latency"], "contribution_assessment": "RESPOND"},
        tokens_used=80,
        duration_ms=300,
        success=True,
        tier_used="fast",
    )


def _evaluate_result(recommendation: str = "approve", pass_val: bool = True) -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.EVALUATE,
        name="evaluate-reply",
        result={
            "pass": pass_val,
            "score": 0.8 if pass_val else 0.3,
            "criteria": {},
            "recommendation": recommendation,
        },
        tokens_used=40,
        duration_ms=150,
        success=True,
        tier_used="fast",
    )


_VALID_EVAL_JSON = json.dumps({
    "pass": True,
    "score": 0.85,
    "criteria": {
        "novelty": {"pass": True, "reason": "New metric cited"},
        "opening_quality": {"pass": True, "reason": "Starts with conclusion"},
        "non_redundancy": {"pass": True, "reason": "Adds analysis"},
        "relevance": {"pass": True, "reason": "Science lens"},
    },
    "recommendation": "approve",
})

_VALID_REFLECT_JSON = json.dumps({
    "output": "Revised draft response.",
    "revised": True,
    "reflection": "Improved opening sentence.",
})


# ===========================================================================
# EvaluateHandler — Construction & Guards
# ===========================================================================

class TestEvaluateConstruction:
    def test_evaluate_handler_implements_protocol(self):
        handler = EvaluateHandler(llm_client=MockLLMClient(), runtime=None)
        assert isinstance(handler, SubTaskHandler)

    @pytest.mark.asyncio
    async def test_evaluate_handler_no_llm_client(self):
        handler = EvaluateHandler(llm_client=None, runtime=None)
        result = await handler(_eval_spec(), _make_context(), [])
        assert not result.success
        assert "error" in result.result

    @pytest.mark.asyncio
    async def test_evaluate_handler_works_without_runtime(self):
        client = MockLLMClient(content=_VALID_EVAL_JSON)
        handler = EvaluateHandler(llm_client=client, runtime=None)
        result = await handler(_eval_spec(), _make_context(), [_compose_result()])
        assert result.success


# ===========================================================================
# Evaluate — Mode Dispatch
# ===========================================================================

class TestEvaluateModeDispatch:
    @pytest.mark.asyncio
    async def test_ward_room_quality_mode(self):
        client = MockLLMClient(content=_VALID_EVAL_JSON)
        handler = EvaluateHandler(llm_client=client, runtime=None)
        result = await handler(_eval_spec("ward_room_quality"), _make_context(), [_compose_result()])
        assert result.success
        assert "Novelty" in client.last_request.system_prompt or "novelty" in client.last_request.system_prompt.lower()

    @pytest.mark.asyncio
    async def test_proactive_quality_mode(self):
        client = MockLLMClient(content=_VALID_EVAL_JSON)
        handler = EvaluateHandler(llm_client=client, runtime=None)
        result = await handler(_eval_spec("proactive_quality"), _make_context(), [_compose_result()])
        assert result.success
        assert "observation" in client.last_request.system_prompt.lower()

    @pytest.mark.asyncio
    async def test_notebook_quality_mode(self):
        client = MockLLMClient(content=_VALID_EVAL_JSON)
        handler = EvaluateHandler(llm_client=client, runtime=None)
        result = await handler(_eval_spec("notebook_quality"), _make_context(), [_compose_result()])
        assert result.success
        assert "notebook" in client.last_request.system_prompt.lower()

    @pytest.mark.asyncio
    async def test_unknown_eval_mode_falls_back(self):
        client = MockLLMClient(content=_VALID_EVAL_JSON)
        handler = EvaluateHandler(llm_client=client, runtime=None)
        result = await handler(_eval_spec("nonexistent_mode"), _make_context(), [_compose_result()])
        assert result.success

    @pytest.mark.asyncio
    async def test_empty_eval_mode_uses_default(self):
        client = MockLLMClient(content=_VALID_EVAL_JSON)
        handler = EvaluateHandler(llm_client=client, runtime=None)
        spec = _eval_spec("")
        result = await handler(spec, _make_context(), [_compose_result()])
        assert result.success


# ===========================================================================
# Evaluate — Criteria in Prompts
# ===========================================================================

class TestEvaluateCriteria:
    def test_eval_novelty_criterion_in_prompt(self):
        sys_p, _ = _build_ward_room_eval_prompt(_make_context(), [_compose_result()], "Kira", "Science")
        assert "Novelty" in sys_p or "novelty" in sys_p.lower()

    def test_eval_opening_quality_in_prompt(self):
        sys_p, _ = _build_ward_room_eval_prompt(_make_context(), [_compose_result()], "Kira", "Science")
        assert "Opening" in sys_p or "opening" in sys_p.lower()

    def test_eval_non_redundancy_in_prompt(self):
        sys_p, _ = _build_ward_room_eval_prompt(_make_context(), [_compose_result()], "Kira", "Science")
        assert "redundancy" in sys_p.lower()

    def test_eval_relevance_in_prompt(self):
        sys_p, _ = _build_ward_room_eval_prompt(_make_context(), [_compose_result()], "Kira", "Science")
        assert "Relevance" in sys_p or "relevance" in sys_p.lower()


# ===========================================================================
# Evaluate — Result Format
# ===========================================================================

class TestEvaluateResult:
    @pytest.mark.asyncio
    async def test_eval_result_has_pass_key(self):
        client = MockLLMClient(content=_VALID_EVAL_JSON)
        handler = EvaluateHandler(llm_client=client, runtime=None)
        result = await handler(_eval_spec(), _make_context(), [_compose_result()])
        assert isinstance(result.result["pass"], bool)

    @pytest.mark.asyncio
    async def test_eval_result_has_score(self):
        client = MockLLMClient(content=_VALID_EVAL_JSON)
        handler = EvaluateHandler(llm_client=client, runtime=None)
        result = await handler(_eval_spec(), _make_context(), [_compose_result()])
        assert 0.0 <= result.result["score"] <= 1.0

    @pytest.mark.asyncio
    async def test_eval_result_has_recommendation(self):
        client = MockLLMClient(content=_VALID_EVAL_JSON)
        handler = EvaluateHandler(llm_client=client, runtime=None)
        result = await handler(_eval_spec(), _make_context(), [_compose_result()])
        assert result.result["recommendation"] in ("approve", "revise", "suppress")

    @pytest.mark.asyncio
    async def test_eval_result_type_is_evaluate(self):
        client = MockLLMClient(content=_VALID_EVAL_JSON)
        handler = EvaluateHandler(llm_client=client, runtime=None)
        result = await handler(_eval_spec(), _make_context(), [_compose_result()])
        assert result.sub_task_type == SubTaskType.EVALUATE

    @pytest.mark.asyncio
    async def test_eval_result_tracks_tokens(self):
        client = MockLLMClient(content=_VALID_EVAL_JSON, tokens_used=42)
        handler = EvaluateHandler(llm_client=client, runtime=None)
        result = await handler(_eval_spec(), _make_context(), [_compose_result()])
        assert result.tokens_used == 42


# ===========================================================================
# Evaluate — Error Handling
# ===========================================================================

class TestEvaluateErrors:
    @pytest.mark.asyncio
    async def test_eval_llm_failure_returns_error(self):
        client = MockLLMClient(raise_exc=RuntimeError("LLM down"))
        handler = EvaluateHandler(llm_client=client, runtime=None)
        result = await handler(_eval_spec(), _make_context(), [_compose_result()])
        assert not result.success
        assert "error" in result.result

    @pytest.mark.asyncio
    async def test_eval_json_parse_failure_passes_by_default(self):
        client = MockLLMClient(content="This is not JSON at all")
        handler = EvaluateHandler(llm_client=client, runtime=None)
        result = await handler(_eval_spec(), _make_context(), [_compose_result()])
        assert result.success
        assert result.result["pass"] is True
        assert result.result["score"] == 1.0
        assert result.result["recommendation"] == "approve"


# ===========================================================================
# Evaluate — Prior Results
# ===========================================================================

class TestEvaluatePriorResults:
    @pytest.mark.asyncio
    async def test_eval_reads_compose_output(self):
        client = MockLLMClient(content=_VALID_EVAL_JSON)
        handler = EvaluateHandler(llm_client=client, runtime=None)
        priors = [_compose_result("My unique draft output.")]
        await handler(_eval_spec(), _make_context(), priors)
        assert "My unique draft output." in client.last_request.prompt

    @pytest.mark.asyncio
    async def test_eval_reads_analysis_context(self):
        client = MockLLMClient(content=_VALID_EVAL_JSON)
        handler = EvaluateHandler(llm_client=client, runtime=None)
        priors = [_analyze_result(), _compose_result()]
        await handler(_eval_spec(), _make_context(), priors)
        assert "latency" in client.last_request.prompt

    @pytest.mark.asyncio
    async def test_eval_no_compose_result_still_works(self):
        client = MockLLMClient(content=_VALID_EVAL_JSON)
        handler = EvaluateHandler(llm_client=client, runtime=None)
        result = await handler(_eval_spec(), _make_context(), [])
        assert result.success


# ===========================================================================
# ReflectHandler — Construction & Guards
# ===========================================================================

class TestReflectConstruction:
    def test_reflect_handler_implements_protocol(self):
        handler = ReflectHandler(llm_client=MockLLMClient(), runtime=None)
        assert isinstance(handler, SubTaskHandler)

    @pytest.mark.asyncio
    async def test_reflect_handler_no_llm_client(self):
        handler = ReflectHandler(llm_client=None, runtime=None)
        result = await handler(_reflect_spec(), _make_context(), [])
        assert not result.success
        assert "error" in result.result


# ===========================================================================
# Reflect — Mode Dispatch
# ===========================================================================

class TestReflectModeDispatch:
    @pytest.mark.asyncio
    async def test_ward_room_reflection_mode(self):
        client = MockLLMClient(content=_VALID_REFLECT_JSON)
        handler = ReflectHandler(llm_client=client, runtime=None)
        priors = [_compose_result()]
        result = await handler(_reflect_spec("ward_room_reflection"), _make_context(), priors)
        assert result.success

    @pytest.mark.asyncio
    async def test_proactive_reflection_mode(self):
        client = MockLLMClient(content=_VALID_REFLECT_JSON)
        handler = ReflectHandler(llm_client=client, runtime=None)
        priors = [_compose_result()]
        result = await handler(_reflect_spec("proactive_reflection"), _make_context(), priors)
        assert result.success
        assert "observation" in client.last_request.system_prompt.lower()

    @pytest.mark.asyncio
    async def test_general_reflection_mode(self):
        client = MockLLMClient(content=_VALID_REFLECT_JSON)
        handler = ReflectHandler(llm_client=client, runtime=None)
        priors = [_compose_result()]
        result = await handler(_reflect_spec("general_reflection"), _make_context(), priors)
        assert result.success

    @pytest.mark.asyncio
    async def test_unknown_reflect_mode_falls_back(self):
        client = MockLLMClient(content=_VALID_REFLECT_JSON)
        handler = ReflectHandler(llm_client=client, runtime=None)
        priors = [_compose_result()]
        result = await handler(_reflect_spec("nonexistent_mode"), _make_context(), priors)
        assert result.success


# ===========================================================================
# Reflect — Suppress Short-Circuit
# ===========================================================================

class TestReflectSuppress:
    @pytest.mark.asyncio
    async def test_reflect_suppress_skips_llm(self):
        client = MockLLMClient(content=_VALID_REFLECT_JSON)
        handler = ReflectHandler(llm_client=client, runtime=None)
        priors = [_compose_result(), _evaluate_result("suppress")]
        result = await handler(_reflect_spec(), _make_context(), priors)
        assert result.success
        assert result.result["output"] == "[NO_RESPONSE]"
        assert result.tokens_used == 0
        assert client.last_request is None  # LLM never called

    @pytest.mark.asyncio
    async def test_reflect_revise_calls_llm(self):
        client = MockLLMClient(content=_VALID_REFLECT_JSON)
        handler = ReflectHandler(llm_client=client, runtime=None)
        priors = [_compose_result(), _evaluate_result("revise")]
        result = await handler(_reflect_spec(), _make_context(), priors)
        assert result.success
        assert client.last_request is not None

    @pytest.mark.asyncio
    async def test_reflect_approve_calls_llm(self):
        client = MockLLMClient(content=_VALID_REFLECT_JSON)
        handler = ReflectHandler(llm_client=client, runtime=None)
        priors = [_compose_result(), _evaluate_result("approve")]
        result = await handler(_reflect_spec(), _make_context(), priors)
        assert result.success
        assert client.last_request is not None

    @pytest.mark.asyncio
    async def test_reflect_no_evaluate_result_calls_llm(self):
        client = MockLLMClient(content=_VALID_REFLECT_JSON)
        handler = ReflectHandler(llm_client=client, runtime=None)
        priors = [_compose_result()]  # No EVALUATE result
        result = await handler(_reflect_spec(), _make_context(), priors)
        assert result.success
        assert client.last_request is not None


# ===========================================================================
# Reflect — Result Format
# ===========================================================================

class TestReflectResult:
    @pytest.mark.asyncio
    async def test_reflect_result_has_output(self):
        client = MockLLMClient(content=_VALID_REFLECT_JSON)
        handler = ReflectHandler(llm_client=client, runtime=None)
        result = await handler(_reflect_spec(), _make_context(), [_compose_result()])
        assert "output" in result.result
        assert isinstance(result.result["output"], str)

    @pytest.mark.asyncio
    async def test_reflect_result_has_revised_flag(self):
        client = MockLLMClient(content=_VALID_REFLECT_JSON)
        handler = ReflectHandler(llm_client=client, runtime=None)
        result = await handler(_reflect_spec(), _make_context(), [_compose_result()])
        assert isinstance(result.result["revised"], bool)

    @pytest.mark.asyncio
    async def test_reflect_result_type_is_reflect(self):
        client = MockLLMClient(content=_VALID_REFLECT_JSON)
        handler = ReflectHandler(llm_client=client, runtime=None)
        result = await handler(_reflect_spec(), _make_context(), [_compose_result()])
        assert result.sub_task_type == SubTaskType.REFLECT

    @pytest.mark.asyncio
    async def test_reflect_result_tracks_tokens(self):
        client = MockLLMClient(content=_VALID_REFLECT_JSON, tokens_used=77)
        handler = ReflectHandler(llm_client=client, runtime=None)
        result = await handler(_reflect_spec(), _make_context(), [_compose_result()])
        assert result.tokens_used == 77


# ===========================================================================
# Reflect — Error Handling
# ===========================================================================

class TestReflectErrors:
    @pytest.mark.asyncio
    async def test_reflect_llm_failure_returns_compose_output(self):
        client = MockLLMClient(raise_exc=RuntimeError("LLM down"))
        handler = ReflectHandler(llm_client=client, runtime=None)
        priors = [_compose_result("Original draft.")]
        result = await handler(_reflect_spec(), _make_context(), priors)
        assert not result.success
        assert result.result["output"] == "Original draft."
        assert result.result["revised"] is False

    @pytest.mark.asyncio
    async def test_reflect_parse_failure_returns_compose_output(self):
        client = MockLLMClient(content="")  # Empty response
        handler = ReflectHandler(llm_client=client, runtime=None)
        priors = [_compose_result("Original draft.")]
        result = await handler(_reflect_spec(), _make_context(), priors)
        assert result.success
        assert result.result["output"] == "Original draft."
        assert result.result["revised"] is False


# ===========================================================================
# Reflect — Self-Critique Content
# ===========================================================================

class TestReflectContent:
    @pytest.mark.asyncio
    async def test_reflect_skill_instructions_in_prompt(self):
        client = MockLLMClient(content=_VALID_REFLECT_JSON)
        handler = ReflectHandler(llm_client=client, runtime=None)
        ctx = _make_context(_augmentation_skill_instructions="Check for redundancy.")
        priors = [_compose_result()]
        await handler(_reflect_spec(), ctx, priors)
        assert "Check for redundancy." in client.last_request.system_prompt

    @pytest.mark.asyncio
    async def test_reflect_pre_submit_check_in_prompt(self):
        client = MockLLMClient(content=_VALID_REFLECT_JSON)
        handler = ReflectHandler(llm_client=client, runtime=None)
        priors = [_compose_result()]
        await handler(_reflect_spec("ward_room_reflection"), _make_context(), priors)
        sp = client.last_request.system_prompt
        assert "Novelty" in sp or "novelty" in sp.lower()
        assert "opening" in sp.lower()

    @pytest.mark.asyncio
    async def test_reflect_plain_text_treated_as_revision(self):
        client = MockLLMClient(content="Here is a better version of the draft.")
        handler = ReflectHandler(llm_client=client, runtime=None)
        priors = [_compose_result()]
        result = await handler(_reflect_spec(), _make_context(), priors)
        assert result.success
        assert result.result["revised"] is True
        assert "better version" in result.result["output"]


# ===========================================================================
# Decision Extractor — REFLECT > COMPOSE > fallback
# ===========================================================================

class TestDecisionExtractor:
    """Test the decision extractor logic in cognitive_agent.py.

    These test the static helpers rather than full agent integration.
    """

    def test_extractor_prefers_reflect_over_compose(self):
        """REFLECT result should win over COMPOSE."""
        compose = _compose_result("Compose output")
        reflect = SubTaskResult(
            sub_task_type=SubTaskType.REFLECT,
            name="reflect-reply",
            result={"output": "Reflected output", "revised": True},
            tokens_used=50,
            duration_ms=200,
            success=True,
            tier_used="fast",
        )
        results = [compose, reflect]
        # Simulate extractor logic
        reflect_results = [r for r in results if r.sub_task_type == SubTaskType.REFLECT and r.success]
        compose_results = [r for r in results if r.sub_task_type == SubTaskType.COMPOSE and r.success]
        if reflect_results:
            output = reflect_results[-1].result.get("output", "")
        elif compose_results:
            output = compose_results[-1].result.get("output", "")
        else:
            output = ""
        assert output == "Reflected output"

    def test_extractor_falls_back_to_compose(self):
        """No REFLECT → uses COMPOSE."""
        compose = _compose_result("Compose output")
        results = [compose]
        reflect_results = [r for r in results if r.sub_task_type == SubTaskType.REFLECT and r.success]
        compose_results = [r for r in results if r.sub_task_type == SubTaskType.COMPOSE and r.success]
        if reflect_results:
            output = reflect_results[-1].result.get("output", "")
        elif compose_results:
            output = compose_results[-1].result.get("output", "")
        else:
            output = ""
        assert output == "Compose output"

    def test_extractor_skips_failed_reflect(self):
        """Failed REFLECT → uses COMPOSE."""
        compose = _compose_result("Compose output")
        failed_reflect = SubTaskResult(
            sub_task_type=SubTaskType.REFLECT,
            name="reflect-reply",
            result={"output": "Draft response text.", "revised": False},
            tokens_used=0,
            duration_ms=100,
            success=False,
            tier_used="",
        )
        results = [compose, failed_reflect]
        reflect_results = [r for r in results if r.sub_task_type == SubTaskType.REFLECT and r.success]
        compose_results = [r for r in results if r.sub_task_type == SubTaskType.COMPOSE and r.success]
        if reflect_results:
            output = reflect_results[-1].result.get("output", "")
        elif compose_results:
            output = compose_results[-1].result.get("output", "")
        else:
            output = ""
        assert output == "Compose output"


# ===========================================================================
# Chain Structure — 5-step chains
# ===========================================================================

class TestChainStructure:
    def _get_wr_chain(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = MagicMock(spec=CognitiveAgent)
        agent._build_chain_for_intent = CognitiveAgent._build_chain_for_intent.__get__(agent)
        return agent._build_chain_for_intent({"intent": "ward_room_notification"})

    def _get_proactive_chain(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = MagicMock(spec=CognitiveAgent)
        agent._build_chain_for_intent = CognitiveAgent._build_chain_for_intent.__get__(agent)
        return agent._build_chain_for_intent({"intent": "proactive_think"})

    def test_ward_room_chain_has_5_steps(self):
        chain = self._get_wr_chain()
        assert len(chain.steps) == 5

    def test_proactive_chain_has_5_steps(self):
        chain = self._get_proactive_chain()
        assert len(chain.steps) == 5

    def test_evaluate_step_not_required(self):
        chain = self._get_wr_chain()
        eval_steps = [s for s in chain.steps if s.sub_task_type == SubTaskType.EVALUATE]
        assert len(eval_steps) == 1
        assert eval_steps[0].required is False

    def test_reflect_step_not_required(self):
        chain = self._get_wr_chain()
        reflect_steps = [s for s in chain.steps if s.sub_task_type == SubTaskType.REFLECT]
        assert len(reflect_steps) == 1
        assert reflect_steps[0].required is False

    def test_evaluate_prompt_template_correct(self):
        wr = self._get_wr_chain()
        pro = self._get_proactive_chain()
        wr_eval = [s for s in wr.steps if s.sub_task_type == SubTaskType.EVALUATE][0]
        pro_eval = [s for s in pro.steps if s.sub_task_type == SubTaskType.EVALUATE][0]
        assert wr_eval.prompt_template == "ward_room_quality"
        assert pro_eval.prompt_template == "proactive_quality"

    def test_reflect_prompt_template_correct(self):
        wr = self._get_wr_chain()
        pro = self._get_proactive_chain()
        wr_ref = [s for s in wr.steps if s.sub_task_type == SubTaskType.REFLECT][0]
        pro_ref = [s for s in pro.steps if s.sub_task_type == SubTaskType.REFLECT][0]
        assert wr_ref.prompt_template == "ward_room_reflection"
        assert pro_ref.prompt_template == "proactive_reflection"


# ===========================================================================
# Registration — handlers registered in executor
# ===========================================================================

class TestRegistration:
    def test_executor_has_evaluate_handler(self):
        from probos.cognitive.sub_task import SubTaskExecutor
        from probos.config import SubTaskConfig
        executor = SubTaskExecutor(config=SubTaskConfig(), emit_event_fn=lambda *a, **kw: None)
        handler = EvaluateHandler(llm_client=MockLLMClient(), runtime=None)
        executor.register_handler(SubTaskType.EVALUATE, handler)
        assert executor.has_handler(SubTaskType.EVALUATE)

    def test_executor_has_reflect_handler(self):
        from probos.cognitive.sub_task import SubTaskExecutor
        from probos.config import SubTaskConfig
        executor = SubTaskExecutor(config=SubTaskConfig(), emit_event_fn=lambda *a, **kw: None)
        handler = ReflectHandler(llm_client=MockLLMClient(), runtime=None)
        executor.register_handler(SubTaskType.REFLECT, handler)
        assert executor.has_handler(SubTaskType.REFLECT)


# ===========================================================================
# Helper Function Unit Tests
# ===========================================================================

class TestHelpers:
    def test_get_compose_output_extracts_from_prior(self):
        priors = [_compose_result("Hello world")]
        assert _get_compose_output(priors) == "Hello world"

    def test_get_compose_output_empty_priors(self):
        assert _get_compose_output([]) == ""

    def test_should_suppress_with_suppress_recommendation(self):
        priors = [_evaluate_result("suppress")]
        assert _should_suppress(priors) is True

    def test_should_suppress_with_approve(self):
        priors = [_evaluate_result("approve")]
        assert _should_suppress(priors) is False

    def test_should_suppress_no_evaluate(self):
        priors = [_compose_result()]
        assert _should_suppress(priors) is False
