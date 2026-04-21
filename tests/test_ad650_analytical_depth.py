"""AD-650: Analytical Depth Enhancement tests."""

import pytest

from probos.cognitive.sub_tasks.analyze import (
    _build_thread_analysis_prompt,
    _build_situation_review_prompt,
    _build_dm_comprehension_prompt,
)
from probos.cognitive.sub_tasks.compose import (
    _build_ward_room_compose_prompt,
    _build_dm_compose_prompt,
    _build_proactive_compose_prompt,
    _build_user_prompt,
)
from probos.cognitive.sub_task import SubTaskResult, SubTaskType


# --- Part A: ANALYZE produces analytical_reasoning ---


class TestAnalyzeNarrativeReasoning:
    """Verify ANALYZE prompts include analytical_reasoning field."""

    def test_thread_analysis_prompt_includes_analytical_reasoning(self):
        """Thread analysis composition_brief prompt mentions analytical_reasoning."""
        ctx = {"mode": "thread_analysis", "context": "test", "channel_name": "engineering"}
        _sys, _user = _build_thread_analysis_prompt(ctx, [], "TestAgent", "engineering")
        prompt = _sys + _user
        assert "analytical_reasoning" in prompt
        assert "narrative prose" in prompt.lower() or "not bullets" in prompt.lower()

    def test_situation_review_prompt_includes_analytical_reasoning(self):
        """Situation review composition_brief prompt mentions analytical_reasoning."""
        ctx = {"mode": "situation_review", "context": "test"}
        _sys, _user = _build_situation_review_prompt(ctx, [], "TestAgent", "engineering")
        prompt = _sys + _user
        assert "analytical_reasoning" in prompt
        assert "narrative prose" in prompt.lower() or "not bullets" in prompt.lower()

    def test_dm_comprehension_prompt_includes_analytical_reasoning(self):
        """DM comprehension composition_brief prompt mentions analytical_reasoning."""
        ctx = {"mode": "dm_comprehension", "context": "test", "channel_name": "dm-captain"}
        _sys, _user = _build_dm_comprehension_prompt(ctx, [], "TestAgent", "medical")
        prompt = _sys + _user
        assert "analytical_reasoning" in prompt
        assert "narrative prose" in prompt.lower() or "not bullets" in prompt.lower()

    def test_brief_description_reframed(self):
        """Composition brief is described as 'analytical reasoning and composition plan'."""
        ctx = {"mode": "thread_analysis", "context": "test", "channel_name": "engineering"}
        _sys, _user = _build_thread_analysis_prompt(ctx, [], "TestAgent", "engineering")
        prompt = _sys + _user
        assert "analytical reasoning and composition plan" in prompt.lower()


# --- Part B: COMPOSE renders and uses analytical_reasoning ---


class TestComposeAnalyticalReasoning:
    """Verify COMPOSE renders analytical_reasoning and has depth instructions."""

    def test_compose_renders_analytical_reasoning_section(self):
        """COMPOSE user prompt includes Analytical Reasoning section when present in brief."""
        ctx = {
            "context": "test thread content",
            "mode": "ward_room_response",
            "channel_name": "engineering",
        }
        prior_analysis = {
            "composition_brief": {
                "situation": "Test situation",
                "key_evidence": "Test evidence",
                "response_should_cover": "Test coverage",
                "tone": "professional",
                "sources_to_draw_on": "episodic memory",
                "analytical_reasoning": "This reveals a deeper pattern of collaborative drift."
            },
            "contribution_assessment": "RESPOND"
        }
        prior_results = [SubTaskResult(
            sub_task_type=SubTaskType.ANALYZE,
            name="analyze-test",
            success=True,
            result=prior_analysis
        )]
        prompt = _build_user_prompt(ctx, prior_results)
        assert "Analytical Reasoning" in prompt
        assert "collaborative drift" in prompt

    def test_compose_graceful_without_analytical_reasoning(self):
        """COMPOSE handles briefs without analytical_reasoning (backward compat)."""
        ctx = {
            "context": "test thread content",
            "mode": "ward_room_response",
            "channel_name": "engineering",
        }
        prior_analysis = {
            "composition_brief": {
                "situation": "Test situation",
                "key_evidence": "Test evidence",
                "response_should_cover": "Test coverage",
                "tone": "professional",
                "sources_to_draw_on": "episodic memory"
                # No analytical_reasoning field
            },
            "contribution_assessment": "RESPOND"
        }
        prior_results = [SubTaskResult(
            sub_task_type=SubTaskType.ANALYZE,
            name="analyze-test",
            success=True,
            result=prior_analysis
        )]
        prompt = _build_user_prompt(ctx, prior_results)
        # Should not crash, should not show empty section
        assert "## Content" in prompt
        assert "Analytical Reasoning" not in prompt

    def test_bold_header_suppression_all_ward_room_branches(self):
        """Bold-header guidance present in ALL Ward Room branches, not just private."""
        for comm_ctx in ["department_discussion", "bridge_briefing", "casual_social", "ship_wide"]:
            ctx = {
                "context": "test",
                "mode": "ward_room_response",
                "channel_name": "engineering",
                "_communication_context": comm_ctx,
            }
            system, _ = _build_ward_room_compose_prompt(ctx, [], "TestAgent", "engineering")
            assert "bold" in system.lower() or "markdown" in system.lower(), \
                f"No bold-header guidance in {comm_ctx} branch"

    def test_depth_instruction_in_ward_room_compose(self):
        """Ward Room compose prompt includes depth instruction."""
        ctx = {
            "context": "test",
            "mode": "ward_room_response",
            "channel_name": "engineering",
            "_communication_context": "department_discussion",
        }
        system, _ = _build_ward_room_compose_prompt(ctx, [], "TestAgent", "engineering")
        assert "interpret" in system.lower() or "another way to see" in system.lower()

    def test_depth_instruction_in_dm_compose(self):
        """DM compose prompt includes depth instruction."""
        ctx = {
            "context": "test",
            "mode": "dm_response",
            "_dm_recipient": "Captain",
            "_communication_context": "private_conversation",
        }
        system, _ = _build_dm_compose_prompt(ctx, [], "TestAgent", "engineering")
        assert "interpret" in system.lower() or "another way to see" in system.lower()

    def test_depth_instruction_in_proactive_compose(self):
        """Proactive compose prompt includes depth instruction."""
        ctx = {
            "context": "test",
            "mode": "proactive_observation",
        }
        system, _ = _build_proactive_compose_prompt(ctx, [], "TestAgent", "engineering")
        assert "interpret" in system.lower() or "another way to see" in system.lower()


# --- Regression ---


class TestRegressionAD650:
    """Ensure AD-650 doesn't break existing behavior."""

    def test_private_conversation_still_has_anti_format(self):
        """private_conversation branch retains its stronger anti-format instruction."""
        ctx = {
            "context": "test",
            "mode": "ward_room_response",
            "channel_name": "dm-captain",
            "_communication_context": "private_conversation",
        }
        system, _ = _build_ward_room_compose_prompt(ctx, [], "TestAgent", "engineering")
        assert "Do NOT use structured formats" in system

    def test_dm_mode_still_has_anti_format(self):
        """DM compose mode retains its anti-format instruction."""
        ctx = {
            "context": "test",
            "mode": "dm_response",
            "_dm_recipient": "Captain",
            "_communication_context": "private_conversation",
        }
        system, _ = _build_dm_compose_prompt(ctx, [], "TestAgent", "engineering")
        assert "Do NOT use any structured output" in system
