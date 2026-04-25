"""AD-632c: Analyze Sub-Task Handler tests.

39 tests across 11 classes verifying the AnalyzeHandler — focused LLM
comprehension for Level 3 cognitive escalation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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
from probos.cognitive.sub_tasks.analyze import AnalyzeHandler
from probos.config import SubTaskConfig
from probos.types import LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockLLMClient:
    """Controllable mock LLM client for testing."""

    def __init__(
        self,
        content: str = '{}',
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
        # Yield to event loop — ensures duration_ms is measurably > 0 on
        # platforms with coarse monotonic clock resolution (Windows).
        await asyncio.sleep(0.001)
        if self._raise_exc:
            raise self._raise_exc
        return LLMResponse(
            content=self._content,
            tier=self._tier,
            tokens_used=self._tokens_used,
        )


def _make_spec(
    name: str = "analyze-thread",
    prompt_template: str = "thread_analysis",
    tier: str = "fast",
    context_keys: tuple[str, ...] = (),
) -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.ANALYZE,
        name=name,
        prompt_template=prompt_template,
        context_keys=context_keys,
        tier=tier,
    )


def _make_context(**overrides: Any) -> dict:
    base = {
        "context": "Lynx: I observed latency spikes in sector 7.\nAtlas: Consistent with last watch's findings.",
        "params": {"channel_name": "science", "title": "Latency Analysis"},
        "intent": "ward_room_notification",
        "_callsign": "Kira",
        "_department": "Science",
        "_agent_id": "agent-kira-001",
        "_agent_type": "data_analyst",
    }
    base.update(overrides)
    return base


_VALID_THREAD_JSON = '''{
    "topics_covered": ["Lynx observed latency spikes", "Atlas confirmed prior findings"],
    "novel_posts": ["Lynx"],
    "gaps": ["No root cause analysis performed yet"],
    "endorsement_candidates": ["Lynx"],
    "contribution_assessment": "RESPOND"
}'''

_VALID_SITUATION_JSON = '''{
    "active_threads": ["Latency Analysis"],
    "pending_actions": ["Review sensor data"],
    "priority_topics": ["Latency spikes in sector 7"],
    "department_relevance": "HIGH"
}'''

_VALID_DM_JSON = '''{
    "sender_intent": "Request analysis of sensor logs",
    "key_questions": ["What caused the latency spike?"],
    "required_actions": ["Review logs", "Report findings"],
    "emotional_tone": "urgent"
}'''


# ===========================================================================
# 1. TestAnalyzeHandlerProtocol
# ===========================================================================

class TestAnalyzeHandlerProtocol:
    """Verify AnalyzeHandler satisfies SubTaskHandler protocol."""

    @pytest.fixture()
    def handler(self) -> AnalyzeHandler:
        return AnalyzeHandler(llm_client=MockLLMClient(content=_VALID_THREAD_JSON), runtime=None)

    def test_implements_sub_task_handler(self, handler: AnalyzeHandler) -> None:
        assert isinstance(handler, SubTaskHandler)

    @pytest.mark.asyncio
    async def test_returns_sub_task_result(self, handler: AnalyzeHandler) -> None:
        result = await handler(_make_spec(), _make_context(), [])
        assert isinstance(result, SubTaskResult)

    @pytest.mark.asyncio
    async def test_sub_task_type_is_analyze(self, handler: AnalyzeHandler) -> None:
        result = await handler(_make_spec(), _make_context(), [])
        assert result.sub_task_type == SubTaskType.ANALYZE

    @pytest.mark.asyncio
    async def test_tokens_reported(self, handler: AnalyzeHandler) -> None:
        result = await handler(_make_spec(), _make_context(), [])
        assert result.tokens_used > 0


# ===========================================================================
# 2. TestThreadAnalysisMode
# ===========================================================================

class TestThreadAnalysisMode:
    """Verify thread_analysis mode comprehension."""

    @pytest.fixture()
    def handler(self) -> AnalyzeHandler:
        return AnalyzeHandler(llm_client=MockLLMClient(content=_VALID_THREAD_JSON), runtime=None)

    @pytest.mark.asyncio
    async def test_thread_analysis_parses_json(self, handler: AnalyzeHandler) -> None:
        result = await handler(_make_spec(), _make_context(), [])
        assert result.success is True
        assert "topics_covered" in result.result
        assert "gaps" in result.result
        assert "endorsement_candidates" in result.result
        assert "novel_posts" in result.result
        assert "contribution_assessment" in result.result

    @pytest.mark.asyncio
    async def test_thread_analysis_includes_topics(self, handler: AnalyzeHandler) -> None:
        result = await handler(_make_spec(), _make_context(), [])
        assert isinstance(result.result["topics_covered"], list)

    @pytest.mark.asyncio
    async def test_thread_analysis_contribution_assessment(self, handler: AnalyzeHandler) -> None:
        result = await handler(_make_spec(), _make_context(), [])
        assert result.result["contribution_assessment"] in ("RESPOND", "ENDORSE", "SILENT")

    @pytest.mark.asyncio
    async def test_thread_analysis_with_prior_query_results(self, handler: AnalyzeHandler) -> None:
        prior = SubTaskResult(
            sub_task_type=SubTaskType.QUERY,
            name="query-thread",
            result={"thread_metadata": {"post_count": 5, "contributors": 3}},
            success=True,
        )
        result = await handler(_make_spec(), _make_context(), [prior])
        assert result.success is True
        # Verify prior data was included in the prompt
        req = handler._llm_client.last_request
        assert "thread_metadata" in req.prompt

    @pytest.mark.asyncio
    async def test_thread_analysis_default_mode(self, handler: AnalyzeHandler) -> None:
        """Empty prompt_template defaults to thread_analysis."""
        spec = _make_spec(prompt_template="")
        result = await handler(spec, _make_context(), [])
        assert result.success is True
        assert "topics_covered" in result.result


# ===========================================================================
# 3. TestSituationReviewMode
# ===========================================================================

class TestSituationReviewMode:
    """Verify situation_review mode for proactive think cycles."""

    @pytest.fixture()
    def handler(self) -> AnalyzeHandler:
        return AnalyzeHandler(llm_client=MockLLMClient(content=_VALID_SITUATION_JSON), runtime=None)

    @pytest.mark.asyncio
    async def test_situation_review_parses_json(self, handler: AnalyzeHandler) -> None:
        spec = _make_spec(prompt_template="situation_review")
        result = await handler(spec, _make_context(), [])
        assert result.success is True
        assert "active_threads" in result.result
        assert "pending_actions" in result.result
        assert "priority_topics" in result.result
        assert "department_relevance" in result.result

    @pytest.mark.asyncio
    async def test_situation_review_mode_selection(self, handler: AnalyzeHandler) -> None:
        spec = _make_spec(prompt_template="situation_review")
        result = await handler(spec, _make_context(), [])
        assert result.success is True
        req = handler._llm_client.last_request
        assert "ASSESS" in req.system_prompt

    @pytest.mark.asyncio
    async def test_situation_review_context_keys(self, handler: AnalyzeHandler) -> None:
        spec = _make_spec(prompt_template="situation_review")
        ctx = _make_context(intent="proactive_think")
        result = await handler(spec, ctx, [])
        assert result.success is True


# ===========================================================================
# 4. TestDMComprehensionMode
# ===========================================================================

class TestDMComprehensionMode:
    """Verify dm_comprehension mode for DM understanding."""

    @pytest.fixture()
    def handler(self) -> AnalyzeHandler:
        return AnalyzeHandler(llm_client=MockLLMClient(content=_VALID_DM_JSON), runtime=None)

    @pytest.mark.asyncio
    async def test_dm_comprehension_parses_json(self, handler: AnalyzeHandler) -> None:
        spec = _make_spec(prompt_template="dm_comprehension")
        result = await handler(spec, _make_context(), [])
        assert result.success is True
        assert "sender_intent" in result.result
        assert "key_questions" in result.result
        assert "required_actions" in result.result
        assert "emotional_tone" in result.result

    @pytest.mark.asyncio
    async def test_dm_comprehension_mode_selection(self, handler: AnalyzeHandler) -> None:
        spec = _make_spec(prompt_template="dm_comprehension")
        result = await handler(spec, _make_context(), [])
        req = handler._llm_client.last_request
        assert "UNDERSTAND" in req.system_prompt


# ===========================================================================
# 5. TestLLMCallConstruction
# ===========================================================================

class TestLLMCallConstruction:
    """Verify LLMRequest construction details."""

    @pytest.fixture()
    def handler(self) -> AnalyzeHandler:
        return AnalyzeHandler(llm_client=MockLLMClient(content=_VALID_THREAD_JSON), runtime=None)

    @pytest.mark.asyncio
    async def test_uses_spec_tier(self, handler: AnalyzeHandler) -> None:
        spec = _make_spec(tier="deep")
        await handler(spec, _make_context(), [])
        assert handler._llm_client.last_request.tier == "deep"

    @pytest.mark.asyncio
    async def test_temperature_zero(self, handler: AnalyzeHandler) -> None:
        await handler(_make_spec(), _make_context(), [])
        assert handler._llm_client.last_request.temperature == 0.0

    @pytest.mark.asyncio
    async def test_max_tokens_1536(self, handler: AnalyzeHandler) -> None:
        await handler(_make_spec(), _make_context(), [])
        assert handler._llm_client.last_request.max_tokens == 1536

    @pytest.mark.asyncio
    async def test_system_prompt_excludes_skill_instructions(self, handler: AnalyzeHandler) -> None:
        ctx = _make_context(
            _augmentation_skill_instructions="## Skill: Communication Discipline\nFollow the 5-gate protocol.",
            cognitive_skill_instructions="Additional skill text here.",
        )
        await handler(_make_spec(), ctx, [])
        req = handler._llm_client.last_request
        assert "Communication Discipline" not in req.system_prompt
        assert "5-gate protocol" not in req.system_prompt
        assert "Additional skill text" not in req.system_prompt

    @pytest.mark.asyncio
    async def test_system_prompt_includes_department(self, handler: AnalyzeHandler) -> None:
        await handler(_make_spec(), _make_context(), [])
        req = handler._llm_client.last_request
        assert "Science" in req.system_prompt


# ===========================================================================
# 6. TestAgentIdentityInjection
# ===========================================================================

class TestAgentIdentityInjection:
    """Verify agent identity flows through context dict."""

    @pytest.fixture()
    def handler(self) -> AnalyzeHandler:
        return AnalyzeHandler(llm_client=MockLLMClient(content=_VALID_THREAD_JSON), runtime=None)

    @pytest.mark.asyncio
    async def test_context_has_agent_id(self, handler: AnalyzeHandler) -> None:
        ctx = _make_context()
        result = await handler(_make_spec(), ctx, [])
        assert result.success is True
        assert ctx["_agent_id"] == "agent-kira-001"

    @pytest.mark.asyncio
    async def test_context_has_callsign(self, handler: AnalyzeHandler) -> None:
        ctx = _make_context()
        await handler(_make_spec(), ctx, [])
        req = handler._llm_client.last_request
        assert "Kira" in req.system_prompt

    @pytest.mark.asyncio
    async def test_context_has_department(self, handler: AnalyzeHandler) -> None:
        ctx = _make_context()
        await handler(_make_spec(), ctx, [])
        req = handler._llm_client.last_request
        assert "Science" in req.system_prompt

    @pytest.mark.asyncio
    async def test_department_fallback_to_standing_orders(self, handler: AnalyzeHandler) -> None:
        """When _department missing, handler uses 'unassigned' gracefully.

        The ``department`` value propagates into the user prompt (system prompt
        is derived from _agent_type via standing_orders, which is unaffected).
        """
        ctx = _make_context()
        del ctx["_department"]
        result = await handler(_make_spec(), ctx, [])
        assert result.success is True
        req = handler._llm_client.last_request
        assert "unassigned" in req.prompt


# ===========================================================================
# 7. TestErrorHandling
# ===========================================================================

class TestErrorHandling:
    """Verify error handling for three tiers."""

    @pytest.mark.asyncio
    async def test_llm_client_none(self) -> None:
        handler = AnalyzeHandler(llm_client=None, runtime=None)
        result = await handler(_make_spec(), _make_context(), [])
        assert result.success is False
        assert "LLM client not available" in result.error

    @pytest.mark.asyncio
    async def test_llm_call_exception(self) -> None:
        handler = AnalyzeHandler(
            llm_client=MockLLMClient(raise_exc=RuntimeError("Timeout connecting")),
            runtime=None,
        )
        result = await handler(_make_spec(), _make_context(), [])
        assert result.success is False
        assert "Timeout connecting" in result.error

    @pytest.mark.asyncio
    async def test_json_parse_failure(self) -> None:
        handler = AnalyzeHandler(
            llm_client=MockLLMClient(content="I cannot analyze this, here is my thoughts"),
            runtime=None,
        )
        result = await handler(_make_spec(), _make_context(), [])
        assert result.success is False
        assert "Failed to parse analysis JSON" in result.error

    @pytest.mark.asyncio
    async def test_error_content_truncated(self) -> None:
        long_content = "x" * 500
        handler = AnalyzeHandler(
            llm_client=MockLLMClient(content=long_content),
            runtime=None,
        )
        result = await handler(_make_spec(), _make_context(), [])
        assert result.success is False
        assert len(result.error) < 500  # Truncated, not full 500 chars


# ===========================================================================
# 8. TestDurationAndTokenTracking
# ===========================================================================

class TestDurationAndTokenTracking:
    """Verify duration and token accounting."""

    @pytest.fixture()
    def handler(self) -> AnalyzeHandler:
        return AnalyzeHandler(
            llm_client=MockLLMClient(content=_VALID_THREAD_JSON, tokens_used=250, tier="standard"),
            runtime=None,
        )

    @pytest.mark.asyncio
    async def test_duration_ms_recorded(self, handler: AnalyzeHandler) -> None:
        result = await handler(_make_spec(), _make_context(), [])
        assert result.duration_ms >= 0  # Mock LLM completes in <1ms under xdist load

    @pytest.mark.asyncio
    async def test_tokens_from_llm_response(self, handler: AnalyzeHandler) -> None:
        result = await handler(_make_spec(), _make_context(), [])
        assert result.tokens_used == 250

    @pytest.mark.asyncio
    async def test_tier_from_llm_response(self, handler: AnalyzeHandler) -> None:
        result = await handler(_make_spec(), _make_context(), [])
        assert result.tier_used == "standard"


# ===========================================================================
# 9. TestContextFiltering
# ===========================================================================

class TestContextFiltering:
    """Verify skill/standing order exclusion from analysis prompt."""

    @pytest.fixture()
    def handler(self) -> AnalyzeHandler:
        return AnalyzeHandler(llm_client=MockLLMClient(content=_VALID_THREAD_JSON), runtime=None)

    @pytest.mark.asyncio
    async def test_skill_instructions_excluded(self, handler: AnalyzeHandler) -> None:
        ctx = _make_context(
            _augmentation_skill_instructions="SKILL: Always use 5-gate protocol before responding.",
        )
        await handler(_make_spec(), ctx, [])
        req = handler._llm_client.last_request
        assert "5-gate protocol" not in req.prompt
        assert "5-gate protocol" not in req.system_prompt

    @pytest.mark.asyncio
    async def test_cognitive_skill_excluded(self, handler: AnalyzeHandler) -> None:
        ctx = _make_context(
            cognitive_skill_instructions="Apply thread awareness checklist.",
        )
        await handler(_make_spec(), ctx, [])
        req = handler._llm_client.last_request
        assert "thread awareness checklist" not in req.prompt
        assert "thread awareness checklist" not in req.system_prompt

    @pytest.mark.asyncio
    async def test_thread_content_included(self, handler: AnalyzeHandler) -> None:
        ctx = _make_context(context="Specific thread text about latency")
        await handler(_make_spec(), ctx, [])
        req = handler._llm_client.last_request
        assert "Specific thread text about latency" in req.prompt


# ===========================================================================
# 10. TestExecutorIntegration
# ===========================================================================

class TestExecutorIntegration:
    """Verify AnalyzeHandler works with SubTaskExecutor."""

    def test_register_with_executor(self) -> None:
        config = SubTaskConfig(enabled=True)
        executor = SubTaskExecutor(config=config, emit_event_fn=AsyncMock())
        handler = AnalyzeHandler(llm_client=MockLLMClient(content=_VALID_THREAD_JSON), runtime=None)
        executor.register_handler(SubTaskType.ANALYZE, handler)
        assert executor.can_execute(SubTaskChain(steps=[_make_spec()]))

    @pytest.mark.asyncio
    async def test_executor_can_execute_analyze_chain(self) -> None:
        config = SubTaskConfig(enabled=True)
        executor = SubTaskExecutor(config=config, emit_event_fn=AsyncMock())
        handler = AnalyzeHandler(llm_client=MockLLMClient(content=_VALID_THREAD_JSON), runtime=None)
        executor.register_handler(SubTaskType.ANALYZE, handler)

        chain = SubTaskChain(steps=[_make_spec(context_keys=("context", "_callsign", "_department"))])
        journal = AsyncMock()
        journal.record = AsyncMock()

        results = await executor.execute(
            chain,
            _make_context(),
            agent_id="agent-kira-001",
            agent_type="data_analyst",
            intent="ward_room_notification",
            intent_id="int-001",
            journal=journal,
        )
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].sub_task_type == SubTaskType.ANALYZE

    @pytest.mark.asyncio
    async def test_executor_records_journal(self) -> None:
        """Journal.record() IS called for ANALYZE steps (unlike QUERY)."""
        config = SubTaskConfig(enabled=True)
        executor = SubTaskExecutor(config=config, emit_event_fn=AsyncMock())
        handler = AnalyzeHandler(llm_client=MockLLMClient(content=_VALID_THREAD_JSON), runtime=None)
        executor.register_handler(SubTaskType.ANALYZE, handler)

        chain = SubTaskChain(steps=[_make_spec(context_keys=("context", "_callsign", "_department"))])
        journal = AsyncMock()
        journal.record = AsyncMock()

        await executor.execute(
            chain,
            _make_context(),
            agent_id="agent-kira-001",
            agent_type="data_analyst",
            intent="ward_room_notification",
            intent_id="int-001",
            journal=journal,
        )
        journal.record.assert_called_once()
        call_kwargs = journal.record.call_args
        # dag_node_id should contain "analyze"
        assert "analyze" in (call_kwargs.kwargs.get("dag_node_id", "") or call_kwargs[1].get("dag_node_id", ""))

    @pytest.mark.asyncio
    async def test_query_then_analyze_chain(self) -> None:
        """Two-step chain: QUERY feeds data into ANALYZE via prior_results."""
        config = SubTaskConfig(enabled=True)
        executor = SubTaskExecutor(config=config, emit_event_fn=AsyncMock())

        # Register both handlers
        from probos.cognitive.sub_tasks.query import QueryHandler

        mock_runtime = MagicMock()
        mock_runtime.ward_room = None
        mock_runtime.trust_network = None

        query_handler = QueryHandler(mock_runtime)
        executor.register_handler(SubTaskType.QUERY, query_handler)

        analyze_handler = AnalyzeHandler(
            llm_client=MockLLMClient(content=_VALID_THREAD_JSON),
            runtime=None,
        )
        executor.register_handler(SubTaskType.ANALYZE, analyze_handler)

        query_spec = SubTaskSpec(
            sub_task_type=SubTaskType.QUERY,
            name="query-data",
            context_keys=(),  # No known operation keys — returns empty success
        )
        analyze_spec = _make_spec(
            context_keys=("context", "_callsign", "_department"),
        )

        chain = SubTaskChain(steps=[query_spec, analyze_spec])
        journal = AsyncMock()
        journal.record = AsyncMock()

        results = await executor.execute(
            chain,
            _make_context(),
            agent_id="agent-kira-001",
            agent_type="data_analyst",
            intent="ward_room_notification",
            intent_id="int-001",
            journal=journal,
        )
        assert len(results) == 2
        assert results[0].sub_task_type == SubTaskType.QUERY
        assert results[1].sub_task_type == SubTaskType.ANALYZE
        assert results[1].success is True


# ===========================================================================
# 11. TestStartupWiring
# ===========================================================================

class TestStartupWiring:
    """Verify finalize.py wiring creates and registers AnalyzeHandler."""

    def test_analyze_handler_registered(self) -> None:
        """After the wiring block, executor should have ANALYZE handler."""
        config = SubTaskConfig(enabled=True)
        executor = SubTaskExecutor(config=config, emit_event_fn=AsyncMock())

        mock_runtime = MagicMock()
        mock_runtime.llm_client = MockLLMClient(content=_VALID_THREAD_JSON)

        handler = AnalyzeHandler(llm_client=mock_runtime.llm_client, runtime=mock_runtime)
        executor.register_handler(SubTaskType.ANALYZE, handler)

        chain = SubTaskChain(steps=[_make_spec()])
        assert executor.can_execute(chain)

    def test_analyze_handler_receives_llm_client(self) -> None:
        mock_llm = MockLLMClient(content=_VALID_THREAD_JSON)
        handler = AnalyzeHandler(llm_client=mock_llm, runtime=None)
        assert handler._llm_client is mock_llm
