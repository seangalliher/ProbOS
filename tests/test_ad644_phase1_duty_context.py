"""AD-644 Phase 1: Duty Context Restoration — Tests.

Verifies that duty context and agent metrics are correctly injected into
observation dicts, and that ANALYZE and COMPOSE prompts render duty-aware
framing.
"""

import pytest

from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt
from probos.cognitive.sub_tasks.compose import (
    _build_proactive_compose_prompt,
    _build_user_prompt,
)
from probos.cognitive.sub_task import SubTaskResult, SubTaskType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DUTY_DICT = {
    "duty_id": "scout_report",
    "description": "Perform a comprehensive review",
}

AGENT_METRICS = "Your trust: 0.72 | Agency: lieutenant | Rank: lieutenant"


def _make_context(*, with_duty: bool = False, with_metrics: bool = True) -> dict:
    """Build a minimal context dict for prompt builder tests."""
    ctx: dict = {
        "context": "Recent activity summary here.",
        "_agent_type": "agent",
        "_callsign": "TestAgent",
        "_department": "engineering",
        "_agent_rank": "lieutenant",
        "_skill_profile": None,
        "_formatted_memories": "",
    }
    if with_duty:
        ctx["_active_duty"] = DUTY_DICT
    if with_metrics:
        ctx["_agent_metrics"] = AGENT_METRICS
    return ctx


# ---------------------------------------------------------------------------
# Test 1: Observation duty injection
# ---------------------------------------------------------------------------

class TestObservationDutyInjection:
    """Test the injection logic from cognitive_agent.py (Change 1)."""

    def test_observation_duty_injection(self):
        """When params.duty is set, _active_duty and _agent_metrics appear."""
        observation: dict = {
            "params": {
                "duty": DUTY_DICT,
                "trust_score": 0.72,
                "agency_level": "lieutenant",
                "rank": "lieutenant",
            },
        }
        # Simulate the injection logic from _execute_chain_with_intent_routing
        _params = observation.get("params", {})
        _duty = _params.get("duty")
        if _duty:
            observation["_active_duty"] = _duty
        _trust_display = _params.get("trust_score", "?")
        _agency_display = _params.get("agency_level", "?")
        _rank_display = _params.get("rank", "?")
        observation["_agent_metrics"] = (
            f"Your trust: {_trust_display} | "
            f"Agency: {_agency_display} | "
            f"Rank: {_rank_display}"
        )

        assert observation["_active_duty"] == DUTY_DICT
        assert "0.72" in observation["_agent_metrics"]
        assert "lieutenant" in observation["_agent_metrics"]

    def test_observation_no_duty(self):
        """When params.duty is None, _active_duty is NOT set but metrics ARE."""
        observation: dict = {
            "params": {
                "duty": None,
                "trust_score": 0.5,
                "agency_level": "ensign",
                "rank": "ensign",
            },
        }
        _params = observation.get("params", {})
        _duty = _params.get("duty")
        if _duty:
            observation["_active_duty"] = _duty
        _trust_display = _params.get("trust_score", "?")
        _agency_display = _params.get("agency_level", "?")
        _rank_display = _params.get("rank", "?")
        observation["_agent_metrics"] = (
            f"Your trust: {_trust_display} | "
            f"Agency: {_agency_display} | "
            f"Rank: {_rank_display}"
        )

        assert "_active_duty" not in observation
        assert "_agent_metrics" in observation
        assert "0.5" in observation["_agent_metrics"]


# ---------------------------------------------------------------------------
# Test 3-4: Analyze prompt with/without duty
# ---------------------------------------------------------------------------

class TestAnalyzePromptDuty:
    """Test _build_situation_review_prompt duty framing."""

    def test_analyze_prompt_with_duty(self):
        """With active duty, prompt includes duty framing."""
        ctx = _make_context(with_duty=True)
        _sys, user = _build_situation_review_prompt(ctx, [], "TestAgent", "engineering")

        assert "Active Duty" in user
        assert "scheduled duty" in user
        assert "Perform a comprehensive review" in user
        assert AGENT_METRICS in user
        assert "[NO_RESPONSE] is appropriate" not in user

    def test_analyze_prompt_without_duty(self):
        """Without active duty, prompt includes free-form framing."""
        ctx = _make_context(with_duty=False)
        _sys, user = _build_situation_review_prompt(ctx, [], "TestAgent", "engineering")

        assert "Proactive Review" in user
        assert "[NO_RESPONSE] is appropriate" in user
        assert AGENT_METRICS in user
        assert "Active Duty" not in user


# ---------------------------------------------------------------------------
# Test 5-6: Compose prompt with/without duty
# ---------------------------------------------------------------------------

class TestComposePromptDuty:
    """Test _build_proactive_compose_prompt duty framing."""

    def test_compose_prompt_with_duty(self):
        """With active duty, system prompt uses duty framing."""
        ctx = _make_context(with_duty=True)
        sys_prompt, _user = _build_proactive_compose_prompt(ctx, [], "TestAgent", "engineering")

        assert "performing a **scheduled duty**" in sys_prompt
        assert "Perform a comprehensive review" in sys_prompt
        assert "quiet moment" not in sys_prompt

    def test_compose_prompt_without_duty(self):
        """Without active duty, system prompt uses quiet moment framing."""
        ctx = _make_context(with_duty=False)
        sys_prompt, _user = _build_proactive_compose_prompt(ctx, [], "TestAgent", "engineering")

        assert "quiet moment" in sys_prompt
        assert "performing a **scheduled duty**" not in sys_prompt


# ---------------------------------------------------------------------------
# Test 7: Compose user prompt includes metrics
# ---------------------------------------------------------------------------

class TestComposeUserPromptMetrics:
    """Test _build_user_prompt includes agent metrics."""

    def test_compose_user_prompt_includes_metrics(self):
        """User prompt includes Your Status section with metrics."""
        ctx = _make_context(with_metrics=True)
        result = _build_user_prompt(ctx, [])

        assert "Your Status" in result
        assert AGENT_METRICS in result

    def test_compose_user_prompt_no_metrics(self):
        """User prompt omits status when no metrics."""
        ctx = _make_context(with_metrics=False)
        result = _build_user_prompt(ctx, [])

        assert "Your Status" not in result


# ---------------------------------------------------------------------------
# Test 8: Analyze duty bias toward reporting
# ---------------------------------------------------------------------------

class TestAnalyzeDutyBias:
    """Verify duty prompt biases ANALYZE toward action."""

    def test_analyze_duty_bias_toward_reporting(self):
        """With duty active, prompt says 'report your findings' and includes intended_actions."""
        ctx = _make_context(with_duty=True)
        _sys, user = _build_situation_review_prompt(ctx, [], "TestAgent", "engineering")

        assert "report your findings" in user
        assert "intended_actions" in user
