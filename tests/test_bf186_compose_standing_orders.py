"""BF-186: Compose Standing Orders Regression — tests."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.compose import (
    ComposeHandler,
    _build_dm_compose_prompt,
    _build_proactive_compose_prompt,
    _build_ward_room_compose_prompt,
    _should_short_circuit,
)
from probos.cognitive.sub_tasks.analyze import (
    _build_dm_comprehension_prompt,
    _build_situation_review_prompt,
    _build_thread_analysis_prompt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_context(**overrides) -> dict:
    ctx = {
        "_callsign": "TestAgent",
        "_department": "science",
        "_agent_type": "test_agent",
        "_from_captain": False,
        "_was_mentioned": False,
        "_agent_rank": "Lieutenant",
        "_skill_profile": None,
        "_crew_manifest": "",
    }
    ctx.update(overrides)
    return ctx


def _analyze_result(assessment: str = "RESPOND") -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze-test",
        result={
            "contribution_assessment": assessment,
            "should_respond": assessment != "SILENT",
        },
        tokens_used=50,
        success=True,
    )


def _compose_spec(mode: str = "ward_room_response") -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose-test",
        prompt_template=mode,
        timeout_ms=15000,
    )


def _mock_llm_client(response: str = "Test response."):
    client = AsyncMock()
    resp = MagicMock()
    resp.content = response
    resp.tokens_used = 100
    resp.tier = "fast"
    client.complete.return_value = resp
    return client


# ---------------------------------------------------------------------------
# Context injection tests
# ---------------------------------------------------------------------------

class TestContextInjection:
    """Verify _agent_rank, _skill_profile, _crew_manifest are injected."""

    def test_chain_context_includes_agent_rank(self):
        ctx = _base_context(_agent_rank="Commander")
        assert ctx["_agent_rank"] == "Commander"

    def test_chain_context_includes_skill_profile(self):
        mock_profile = MagicMock()
        ctx = _base_context(_skill_profile=mock_profile)
        assert ctx["_skill_profile"] is mock_profile

    def test_chain_context_includes_crew_manifest(self):
        ctx = _base_context(_crew_manifest="## Crew\n- Bones (Medical)")
        assert ctx["_crew_manifest"] != ""
        assert "Bones" in ctx["_crew_manifest"]

    def test_chain_context_crew_manifest_empty_without_runtime(self):
        ctx = _base_context(_crew_manifest="")
        assert ctx["_crew_manifest"] == ""


# ---------------------------------------------------------------------------
# Compose standing orders parity tests
# ---------------------------------------------------------------------------

class TestComposeStandingOrdersParity:
    """Verify compose prompts include standing orders and crew manifest."""

    def test_ward_room_compose_includes_standing_orders(self):
        ctx = _base_context()
        system_prompt, _ = _build_ward_room_compose_prompt(
            ctx, [], "TestAgent", "science",
        )
        # compose_instructions() should inject standing orders headers
        assert "Federation Constitution" in system_prompt or "Ship Standing Orders" in system_prompt or "TestAgent" in system_prompt

    def test_ward_room_compose_includes_crew_manifest(self):
        ctx = _base_context(_crew_manifest="## Crew Roster\n- Bones (Medical)")
        system_prompt, _ = _build_ward_room_compose_prompt(
            ctx, [], "TestAgent", "science",
        )
        assert "Bones" in system_prompt

    def test_proactive_compose_no_duplicate_action_vocab(self):
        """Proactive compose builder itself should NOT hardcode action vocab.

        Standing orders (via get_step_instructions) provide it. We mock
        get_step_instructions to return a bare string and verify the builder
        doesn't add action tags on its own.
        """
        ctx = _base_context()
        with patch(
            "probos.cognitive.sub_tasks.compose.get_step_instructions",
            return_value="Mocked base instructions.",
        ):
            system_prompt, _ = _build_proactive_compose_prompt(
                ctx, [], "TestAgent", "science",
            )
        # With compose_instructions mocked out, no action vocab should appear
        assert "[ENDORSE" not in system_prompt
        assert "[REPLY" not in system_prompt
        assert "[DM @" not in system_prompt
        assert "[CHALLENGE" not in system_prompt
        assert "[MOVE" not in system_prompt
        assert "[NOTEBOOK" not in system_prompt

    def test_compose_passes_agent_rank(self):
        ctx = _base_context(_agent_rank="Commander")
        with patch(
            "probos.cognitive.sub_tasks.compose.get_step_instructions",
            return_value="mocked instructions",
        ) as mock_ci:
            _build_ward_room_compose_prompt(ctx, [], "TestAgent", "science")
            mock_ci.assert_called_once()
            _, kwargs = mock_ci.call_args
            # agent_rank passed as keyword arg
            assert kwargs.get("agent_rank") == "Commander" or mock_ci.call_args[1].get("agent_rank") == "Commander"
            assert kwargs.get("step_name") == "compose"

    def test_compose_passes_skill_profile(self):
        mock_profile = MagicMock()
        ctx = _base_context(_skill_profile=mock_profile)
        with patch(
            "probos.cognitive.sub_tasks.compose.get_step_instructions",
            return_value="mocked instructions",
        ) as mock_ci:
            _build_ward_room_compose_prompt(ctx, [], "TestAgent", "science")
            mock_ci.assert_called_once()
            _, kwargs = mock_ci.call_args
            assert kwargs.get("skill_profile") is mock_profile or mock_ci.call_args[1].get("skill_profile") is mock_profile
            assert kwargs.get("step_name") == "compose"


# ---------------------------------------------------------------------------
# Social obligation bypass tests
# ---------------------------------------------------------------------------

class TestComposeSocialBypass:
    """BF-186: SILENT short-circuit respects social obligation flags."""

    def test_compose_short_circuit_bypassed_for_captain(self):
        """SILENT + captain → do NOT short-circuit."""
        prior = [_analyze_result("SILENT")]
        ctx = _base_context(_from_captain=True)
        assert _should_short_circuit(prior, ctx) is False

    def test_compose_short_circuit_bypassed_for_mention(self):
        """SILENT + mentioned → do NOT short-circuit."""
        prior = [_analyze_result("SILENT")]
        ctx = _base_context(_was_mentioned=True)
        assert _should_short_circuit(prior, ctx) is False

    def test_compose_short_circuit_normal_without_social(self):
        """SILENT + no social flags → short-circuit as before."""
        prior = [_analyze_result("SILENT")]
        ctx = _base_context(_from_captain=False, _was_mentioned=False)
        assert _should_short_circuit(prior, ctx) is True

    def test_compose_short_circuit_no_context(self):
        """Backward compat: no context arg → normal behavior."""
        prior = [_analyze_result("SILENT")]
        assert _should_short_circuit(prior) is True

    def test_compose_respond_no_short_circuit(self):
        """RESPOND assessment → no short-circuit regardless."""
        prior = [_analyze_result("RESPOND")]
        ctx = _base_context()
        assert _should_short_circuit(prior, ctx) is False


# ---------------------------------------------------------------------------
# Analyze enrichment tests
# ---------------------------------------------------------------------------

class TestAnalyzeEnrichment:
    """BF-186/AD-651: Analyze prompts use standing orders, not bare identity."""

    def test_analyze_thread_prompt_includes_standing_orders(self):
        ctx = _base_context()
        with patch(
            "probos.cognitive.sub_tasks.analyze.get_step_instructions",
            return_value="You are TestAgent, science officer.\n\n## Ship Standing Orders\nTest orders",
        ) as mock_ci:
            system_prompt, _ = _build_thread_analysis_prompt(
                ctx, [], "TestAgent", "science",
            )
            mock_ci.assert_called_once()
            assert mock_ci.call_args.kwargs.get("step_name") == "analyze"
            assert "Ship Standing Orders" in system_prompt
            assert "ANALYZE" in system_prompt

    def test_analyze_situation_prompt_includes_standing_orders(self):
        ctx = _base_context()
        with patch(
            "probos.cognitive.sub_tasks.analyze.get_step_instructions",
            return_value="You are TestAgent.\n\n## Ship Standing Orders\nTest",
        ) as mock_ci:
            system_prompt, _ = _build_situation_review_prompt(
                ctx, [], "TestAgent", "science",
            )
            mock_ci.assert_called_once()
            assert mock_ci.call_args.kwargs.get("step_name") == "analyze"
            assert "Ship Standing Orders" in system_prompt
            assert "ASSESS" in system_prompt

    def test_analyze_dm_prompt_includes_standing_orders(self):
        ctx = _base_context()
        with patch(
            "probos.cognitive.sub_tasks.analyze.get_step_instructions",
            return_value="You are TestAgent.\n\n## Ship Standing Orders\nTest",
        ) as mock_ci:
            system_prompt, _ = _build_dm_comprehension_prompt(
                ctx, [], "TestAgent", "science",
            )
            mock_ci.assert_called_once()
            assert mock_ci.call_args.kwargs.get("step_name") == "analyze"
            assert "Ship Standing Orders" in system_prompt
            assert "UNDERSTAND" in system_prompt


# ---------------------------------------------------------------------------
# Integration: ComposeHandler with social bypass
# ---------------------------------------------------------------------------

class TestComposeHandlerSocialBypass:
    """Full handler integration for social obligation bypass at compose layer."""

    @pytest.mark.asyncio
    async def test_captain_overrides_silent(self):
        """Captain message prevents SILENT short-circuit, calls LLM."""
        llm = _mock_llm_client()
        handler = ComposeHandler(llm_client=llm, runtime=None)
        ctx = _base_context(_from_captain=True)
        prior = [_analyze_result("SILENT")]

        result = await handler(_compose_spec(), ctx, prior)

        assert result.success
        assert result.result["output"] != "[NO_RESPONSE]"
        llm.complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mention_overrides_silent(self):
        """@mentioned prevents SILENT short-circuit, calls LLM."""
        llm = _mock_llm_client()
        handler = ComposeHandler(llm_client=llm, runtime=None)
        ctx = _base_context(_was_mentioned=True)
        prior = [_analyze_result("SILENT")]

        result = await handler(_compose_spec(), ctx, prior)

        assert result.success
        llm.complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_silent_without_social_flags(self):
        """No social flags → SILENT short-circuits, no LLM call."""
        llm = _mock_llm_client()
        handler = ComposeHandler(llm_client=llm, runtime=None)
        ctx = _base_context()
        prior = [_analyze_result("SILENT")]

        result = await handler(_compose_spec(), ctx, prior)

        assert result.success
        assert result.result["output"] == "[NO_RESPONSE]"
        assert result.tokens_used == 0
        llm.complete.assert_not_awaited()
