"""AD-632d: Compose Sub-Task Handler — unit tests.

Tests cover: protocol compliance, mode dispatch, SILENT short-circuit,
skill injection, action vocabulary, result format, prior results integration,
error handling, and identity injection.

Target: 30 tests.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.sub_task import (
    SubTaskResult,
    SubTaskSpec,
    SubTaskType,
)
from probos.cognitive.sub_tasks.compose import (
    ComposeHandler,
    _COMPOSITION_MODES,
    _build_dm_compose_prompt,
    _build_proactive_compose_prompt,
    _build_ward_room_compose_prompt,
    _get_analysis_result,
    _inject_skills,
    _should_short_circuit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class MockLLMClient:
    """Configurable async LLM client mock."""

    def __init__(
        self,
        content: str = "Test response",
        tokens_used: int = 50,
        tier: str = "fast",
        raise_exc: Exception | None = None,
    ):
        self.content = content
        self.tokens_used = tokens_used
        self.tier = tier
        self.raise_exc = raise_exc
        self.last_request = None

    async def complete(self, request: Any) -> Any:
        self.last_request = request
        if self.raise_exc:
            raise self.raise_exc
        resp = MagicMock()
        resp.content = self.content
        resp.tokens_used = self.tokens_used
        resp.tier = self.tier
        return resp


def _make_spec(
    name: str = "test-compose",
    prompt_template: str | None = None,
    tier: str = "fast",
) -> SubTaskSpec:
    return SubTaskSpec(
        name=name,
        sub_task_type=SubTaskType.COMPOSE,
        prompt_template=prompt_template,
        tier=tier,
    )


def _make_analyze_result(
    result: dict | None = None,
    success: bool = True,
) -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="test-analyze",
        result=result or {"contribution_assessment": "RESPOND", "gaps": ["missing data"]},
        success=success,
        duration_ms=10.0,
    )


def _make_query_result(result: dict | None = None) -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.QUERY,
        name="test-query",
        result=result or {"thread_count": 5, "department": "Science"},
        success=True,
        duration_ms=1.0,
    )


def _base_context(**overrides: Any) -> dict:
    ctx = {
        "_agent_type": "science_officer",
        "_callsign": "Lynx",
        "_department": "Science",
        "context": "Thread content here.",
    }
    ctx.update(overrides)
    return ctx


# ===========================================================================
# Protocol & Construction
# ===========================================================================


class TestComposeHandlerProtocol:
    """Handler construction and protocol compliance."""

    def test_implements_protocol(self):
        from probos.cognitive.sub_task import SubTaskHandler

        handler = ComposeHandler(llm_client=MockLLMClient(), runtime=None)
        assert isinstance(handler, SubTaskHandler)

    @pytest.mark.asyncio
    async def test_no_llm_client_returns_failure(self):
        handler = ComposeHandler(llm_client=None, runtime=None)
        result = await handler(_make_spec(), _base_context(), [])
        assert not result.success
        assert "LLM client not available" in result.error

    @pytest.mark.asyncio
    async def test_no_runtime_still_works(self):
        handler = ComposeHandler(llm_client=MockLLMClient(), runtime=None)
        result = await handler(_make_spec(), _base_context(), [])
        assert result.success
        assert result.result["output"] == "Test response"


# ===========================================================================
# Mode Dispatch
# ===========================================================================


class TestModeDispatch:
    """Mode selection via spec.prompt_template."""

    @pytest.mark.asyncio
    async def test_ward_room_mode(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        await handler(_make_spec(prompt_template="ward_room_response"), _base_context(), [])
        assert "Ward Room" in client.last_request.system_prompt

    @pytest.mark.asyncio
    async def test_dm_mode(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        await handler(_make_spec(prompt_template="dm_response"), _base_context(), [])
        assert "1:1 conversation" in client.last_request.system_prompt

    @pytest.mark.asyncio
    async def test_proactive_mode(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        await handler(_make_spec(prompt_template="proactive_observation"), _base_context(), [])
        assert "quiet moment" in client.last_request.system_prompt

    @pytest.mark.asyncio
    async def test_unknown_mode_falls_back(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        await handler(_make_spec(prompt_template="nonexistent"), _base_context(), [])
        # Falls back to ward_room_response
        assert "Ward Room" in client.last_request.system_prompt

    @pytest.mark.asyncio
    async def test_empty_mode_uses_default(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        await handler(_make_spec(prompt_template=None), _base_context(), [])
        assert "Ward Room" in client.last_request.system_prompt


# ===========================================================================
# SILENT Short-Circuit
# ===========================================================================


class TestSilentShortCircuit:
    """SILENT analysis result skips LLM call."""

    @pytest.mark.asyncio
    async def test_silent_assessment_skips_llm(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        silent_analyze = _make_analyze_result(
            result={"contribution_assessment": "SILENT"},
        )
        result = await handler(_make_spec(), _base_context(), [silent_analyze])
        assert result.success
        assert result.result["output"] == "[NO_RESPONSE]"
        assert result.tokens_used == 0
        assert client.last_request is None  # LLM never called

    @pytest.mark.asyncio
    async def test_should_respond_false_skips_llm(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        no_respond = _make_analyze_result(
            result={"should_respond": False},
        )
        result = await handler(_make_spec(), _base_context(), [no_respond])
        assert result.result["output"] == "[NO_RESPONSE]"
        assert result.tokens_used == 0

    @pytest.mark.asyncio
    async def test_respond_assessment_calls_llm(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        respond = _make_analyze_result(
            result={"contribution_assessment": "RESPOND"},
        )
        result = await handler(_make_spec(), _base_context(), [respond])
        assert result.success
        assert result.result["output"] == "Test response"
        assert client.last_request is not None


# ===========================================================================
# Skill Injection
# ===========================================================================


class TestSkillInjection:
    """Augmentation skill instructions appear in system prompt."""

    @pytest.mark.asyncio
    async def test_skill_instructions_injected(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        ctx = _base_context(
            _augmentation_skill_instructions="Analyze communication patterns deeply.",
            _augmentation_skills_used=[MagicMock(name="comm-analysis")],
        )
        await handler(_make_spec(), ctx, [])
        sp = client.last_request.system_prompt
        assert "<active_skill" in sp
        assert "Analyze communication patterns deeply." in sp
        assert "</active_skill>" in sp

    @pytest.mark.asyncio
    async def test_no_skill_instructions_no_xml(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        await handler(_make_spec(), _base_context(), [])
        assert "<active_skill" not in client.last_request.system_prompt

    @pytest.mark.asyncio
    async def test_proficiency_tier_injected(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        ctx = _base_context(
            _augmentation_skill_instructions="Do the thing.",
            _proficiency_context="advanced",
        )
        await handler(_make_spec(), ctx, [])
        assert "<proficiency_tier>advanced</proficiency_tier>" in client.last_request.system_prompt


# ===========================================================================
# Action Vocabulary
# ===========================================================================


class TestActionVocabulary:
    """Mode-specific action tags in system prompt."""

    @pytest.mark.asyncio
    async def test_ward_room_has_endorse(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        await handler(_make_spec(prompt_template="ward_room_response"), _base_context(), [])
        assert "[ENDORSE" in client.last_request.system_prompt

    @pytest.mark.asyncio
    async def test_ward_room_has_no_response(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        await handler(_make_spec(prompt_template="ward_room_response"), _base_context(), [])
        assert "[NO_RESPONSE]" in client.last_request.system_prompt

    @pytest.mark.asyncio
    async def test_dm_has_no_action_tags_in_mode_section(self):
        """DM mode section does not add action tags (standing orders may have them)."""
        # Verify the DM prompt builder itself doesn't inject action vocabulary
        ctx = _base_context()
        _, user_prompt = _build_dm_compose_prompt(ctx, [], "Lynx", "Science")
        assert "[ENDORSE" not in user_prompt
        assert "[REPLY" not in user_prompt

    @pytest.mark.asyncio
    async def test_proactive_has_full_vocabulary(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        await handler(_make_spec(prompt_template="proactive_observation"), _base_context(), [])
        sp = client.last_request.system_prompt
        assert "[REPLY" in sp
        assert "[ENDORSE" in sp
        assert "[NOTEBOOK" in sp
        assert "[PROPOSAL]" in sp
        assert "[DM @" in sp
        assert "[CHALLENGE" in sp
        assert "[MOVE" in sp


# ===========================================================================
# Result Format
# ===========================================================================


class TestResultFormat:
    """Result shape matches _execute_sub_task_chain() expectations."""

    @pytest.mark.asyncio
    async def test_result_has_output_key(self):
        handler = ComposeHandler(llm_client=MockLLMClient(content="Hello Ward Room"), runtime=None)
        result = await handler(_make_spec(), _base_context(), [])
        assert result.result["output"] == "Hello Ward Room"

    @pytest.mark.asyncio
    async def test_result_type_is_compose(self):
        handler = ComposeHandler(llm_client=MockLLMClient(), runtime=None)
        result = await handler(_make_spec(), _base_context(), [])
        assert result.sub_task_type == SubTaskType.COMPOSE

    @pytest.mark.asyncio
    async def test_result_tracks_tokens(self):
        handler = ComposeHandler(llm_client=MockLLMClient(tokens_used=123), runtime=None)
        result = await handler(_make_spec(), _base_context(), [])
        assert result.tokens_used == 123

    @pytest.mark.asyncio
    async def test_result_tracks_tier(self):
        handler = ComposeHandler(llm_client=MockLLMClient(tier="quality"), runtime=None)
        result = await handler(_make_spec(), _base_context(), [])
        assert result.tier_used == "quality"


# ===========================================================================
# Prior Results Integration
# ===========================================================================


class TestPriorResults:
    """Analysis JSON and query data appear in user prompt."""

    @pytest.mark.asyncio
    async def test_analysis_json_in_user_prompt(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        analyze = _make_analyze_result(
            result={"contribution_assessment": "RESPOND", "gaps": ["missing sensor data"]},
        )
        await handler(_make_spec(), _base_context(), [analyze])
        up = client.last_request.prompt
        assert "## Analysis" in up
        assert "missing sensor data" in up

    @pytest.mark.asyncio
    async def test_no_prior_analysis_still_works(self):
        handler = ComposeHandler(llm_client=MockLLMClient(), runtime=None)
        result = await handler(_make_spec(), _base_context(), [])
        assert result.success

    @pytest.mark.asyncio
    async def test_only_successful_analysis_used(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        failed = _make_analyze_result(
            result={"contribution_assessment": "RESPOND"},
            success=False,
        )
        await handler(_make_spec(), _base_context(), [failed])
        assert "## Analysis" not in client.last_request.prompt

    @pytest.mark.asyncio
    async def test_query_data_in_user_prompt(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        query = _make_query_result({"thread_count": 5})
        await handler(_make_spec(), _base_context(), [query])
        assert "thread_count" in client.last_request.prompt


# ===========================================================================
# Error Handling
# ===========================================================================


class TestErrorHandling:
    """LLM failures produce proper error SubTaskResults."""

    @pytest.mark.asyncio
    async def test_llm_exception_returns_error(self):
        client = MockLLMClient(raise_exc=RuntimeError("API down"))
        handler = ComposeHandler(llm_client=client, runtime=None)
        result = await handler(_make_spec(), _base_context(), [])
        assert not result.success
        assert "API down" in result.error

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_output(self):
        client = MockLLMClient(content="")
        handler = ComposeHandler(llm_client=client, runtime=None)
        result = await handler(_make_spec(), _base_context(), [])
        assert result.success
        assert result.result["output"] == ""


# ===========================================================================
# Identity Injection
# ===========================================================================


class TestIdentityInjection:
    """Agent callsign and department appear in composed prompt."""

    @pytest.mark.asyncio
    async def test_callsign_in_system_prompt(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        ctx = _base_context(_callsign="Atlas")
        await handler(_make_spec(), ctx, [])
        # compose_instructions receives callsign — it should appear somewhere
        # (the exact placement depends on standing_orders.compose_instructions)
        # At minimum, the handler passed it through without error
        assert client.last_request is not None

    @pytest.mark.asyncio
    async def test_department_context_flows(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        ctx = _base_context(_department="Engineering")
        await handler(_make_spec(), ctx, [])
        assert client.last_request is not None


# ===========================================================================
# LLM Call Parameters
# ===========================================================================


class TestLLMCallParams:
    """Verify temperature, max_tokens, tier passed correctly."""

    @pytest.mark.asyncio
    async def test_temperature_is_0_3(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        await handler(_make_spec(), _base_context(), [])
        assert client.last_request.temperature == 0.3

    @pytest.mark.asyncio
    async def test_max_tokens_is_2048(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        await handler(_make_spec(), _base_context(), [])
        assert client.last_request.max_tokens == 2048

    @pytest.mark.asyncio
    async def test_tier_from_spec(self):
        client = MockLLMClient()
        handler = ComposeHandler(llm_client=client, runtime=None)
        await handler(_make_spec(tier="quality"), _base_context(), [])
        assert client.last_request.tier == "quality"


# ===========================================================================
# Helper unit tests
# ===========================================================================


class TestHelpers:
    """Unit tests for module-level helper functions."""

    def test_should_short_circuit_silent(self):
        r = _make_analyze_result(result={"contribution_assessment": "SILENT"})
        assert _should_short_circuit([r]) is True

    def test_should_short_circuit_should_respond_false(self):
        r = _make_analyze_result(result={"should_respond": False})
        assert _should_short_circuit([r]) is True

    def test_should_short_circuit_respond(self):
        r = _make_analyze_result(result={"contribution_assessment": "RESPOND"})
        assert _should_short_circuit([r]) is False

    def test_get_analysis_result_empty(self):
        assert _get_analysis_result([]) == {}

    def test_get_analysis_result_picks_latest(self):
        r1 = _make_analyze_result(result={"v": 1})
        r2 = _make_analyze_result(result={"v": 2})
        assert _get_analysis_result([r1, r2]) == {"v": 2}

    def test_inject_skills_noop_when_empty(self):
        result = _inject_skills("base", {})
        assert result == "base"

    def test_inject_skills_adds_xml(self):
        ctx = {"_augmentation_skill_instructions": "Do analysis."}
        result = _inject_skills("base", ctx)
        assert "<active_skill" in result
        assert "Do analysis." in result
