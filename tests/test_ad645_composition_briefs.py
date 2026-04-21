"""AD-645 Phase 1+2: Composition Briefs + COMPOSE Context Enrichment — Tests.

Verifies that ANALYZE prompts request composition_brief, that COMPOSE renders
the brief (and falls back gracefully), and that SA keys flow to COMPOSE.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from probos.cognitive.sub_tasks.analyze import (
    _build_situation_review_prompt,
    _build_thread_analysis_prompt,
    _build_dm_comprehension_prompt,
    AnalyzeHandler,
)
from probos.cognitive.sub_tasks.compose import (
    _build_user_prompt,
    _should_short_circuit,
)
from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_context(**overrides) -> dict:
    ctx = {
        "context": "",
        "_agent_type": "agent",
        "_agent_rank": None,
        "_skill_profile": None,
        "_formatted_memories": "",
    }
    ctx.update(overrides)
    return ctx


def _make_analyze_result(result_dict: dict) -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze",
        result=result_dict,
        duration_ms=10.0,
        success=True,
    )


# ---------------------------------------------------------------------------
# ANALYZE Tests (1-4)
# ---------------------------------------------------------------------------

class TestAnalyzePromptCompositionBrief:

    def test_situation_review_prompt_requests_composition_brief(self):
        ctx = _base_context()
        _sys, user = _build_situation_review_prompt(ctx, [], "Echo", "Medical")

        assert "composition_brief" in user
        assert "situation" in user
        assert "key_evidence" in user
        assert "response_should_cover" in user
        assert "tone" in user
        assert "sources_to_draw_on" in user
        assert "6 keys" in user

    def test_thread_analysis_prompt_requests_composition_brief(self):
        ctx = _base_context(context="Thread content here")
        _sys, user = _build_thread_analysis_prompt(ctx, [], "Bones", "Medical")

        assert "composition_brief" in user
        assert "situation" in user
        assert "key_evidence" in user
        assert "response_should_cover" in user
        assert "tone" in user
        assert "sources_to_draw_on" in user
        assert "7 keys" in user

    def test_dm_comprehension_prompt_requests_composition_brief(self):
        ctx = _base_context(context="Hey, how is the crew?")
        _sys, user = _build_dm_comprehension_prompt(ctx, [], "Echo", "Medical")

        assert "composition_brief" in user
        assert "situation" in user
        assert "key_evidence" in user
        assert "response_should_cover" in user
        assert "tone" in user
        assert "sources_to_draw_on" in user
        assert "5 keys" in user


class TestAnalyzeMaxTokens:

    @pytest.mark.asyncio
    async def test_analyze_max_tokens_increased(self):
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = '{"topics_covered": [], "novel_posts": []}'
        mock_response.tokens_used = 100
        mock_response.tier = "t2"
        mock_llm.complete.return_value = mock_response

        handler = AnalyzeHandler(llm_client=mock_llm, runtime=None)
        spec = SubTaskSpec(
            sub_task_type=SubTaskType.ANALYZE,
            name="analyze",
            prompt_template="thread_analysis",
        )
        ctx = _base_context(context="Some thread")
        await handler(spec, ctx, [])

        call_args = mock_llm.complete.call_args
        request = call_args[0][0]
        assert request.max_tokens == 1536


# ---------------------------------------------------------------------------
# COMPOSE Tests (5-13)
# ---------------------------------------------------------------------------

class TestComposeRendersCompositionBrief:

    def test_compose_renders_composition_brief(self):
        analysis = _make_analyze_result({
            "contribution_assessment": "RESPOND",
            "composition_brief": {
                "situation": "The crew is discussing latency patterns.",
                "key_evidence": ["VitalsMonitor flagged 200ms spikes", "3 departments affected"],
                "response_should_cover": ["Root cause analysis", "Recommended next steps"],
                "tone": "Professional, analytical, confident",
                "sources_to_draw_on": "episodic memories, Ward Room observations",
            },
        })
        result = _build_user_prompt({}, [analysis])

        assert "## Composition Brief" in result
        assert "**Situation:**" in result
        assert "latency patterns" in result
        assert "**Key Evidence:**" in result
        assert "VitalsMonitor" in result
        assert "**Your response should cover:**" in result
        assert "Root cause analysis" in result
        assert "**Tone:**" in result
        assert "**Sources to draw on:**" in result

    def test_compose_falls_back_without_brief(self):
        analysis = _make_analyze_result({
            "contribution_assessment": "RESPOND",
            "topics_covered": ["latency"],
        })
        result = _build_user_prompt({}, [analysis])

        assert "## Analysis" in result
        assert "latency" in result
        # Should NOT have brief heading
        assert "## Composition Brief" not in result

    def test_compose_handles_null_brief(self):
        analysis = _make_analyze_result({
            "contribution_assessment": "SILENT",
            "composition_brief": None,
        })
        result = _build_user_prompt({}, [analysis])

        # Null brief → fallback to JSON dump
        assert "## Analysis" in result
        assert "## Composition Brief" not in result

    def test_compose_renders_partial_brief(self):
        analysis = _make_analyze_result({
            "composition_brief": {
                "situation": "Quick status check",
                "tone": "Casual",
            },
        })
        result = _build_user_prompt({}, [analysis])

        assert "## Composition Brief" in result
        assert "**Situation:**" in result
        assert "Quick status check" in result
        assert "**Tone:**" in result
        assert "Casual" in result
        # Missing fields should not appear
        assert "**Key Evidence:**" not in result
        assert "**Your response should cover:**" not in result


class TestComposeSAKeys:

    def test_compose_includes_ward_room_activity(self):
        ctx = {"_ward_room_activity": "Recent Ward Room discussion:\n  - [thread] Bones: Update"}
        result = _build_user_prompt(ctx, [])
        assert "## Recent Ward Room Activity" in result

    def test_compose_includes_recent_alerts(self):
        ctx = {"_recent_alerts": "Recent bridge alerts:\n  - [WARNING] High latency"}
        result = _build_user_prompt(ctx, [])
        assert "## Recent Alerts" in result

    def test_compose_includes_subordinate_stats(self):
        ctx = {"_subordinate_stats": "<subordinate_activity>\n  Kira: 5 posts\n</subordinate_activity>"}
        result = _build_user_prompt(ctx, [])
        assert "## Subordinate Activity" in result

    def test_compose_includes_infrastructure_status(self):
        ctx = {"_infrastructure_status": "[INFRASTRUCTURE NOTE: Communications array degraded]"}
        result = _build_user_prompt(ctx, [])
        assert "## Infrastructure Status" in result

    def test_compose_sa_keys_not_rendered_when_empty(self):
        result = _build_user_prompt({}, [])
        assert "## Recent Ward Room Activity" not in result
        assert "## Recent Alerts" not in result
        assert "## Recent Events" not in result
        assert "## Infrastructure Status" not in result
        assert "## Subordinate Activity" not in result
        assert "## Active Game" not in result


# ---------------------------------------------------------------------------
# Integration Tests (14-15)
# ---------------------------------------------------------------------------

class TestComposeBriefIntegration:

    def test_compose_brief_plus_sa_keys_together(self):
        analysis = _make_analyze_result({
            "composition_brief": {
                "situation": "Latency spike detected",
                "key_evidence": ["200ms p99"],
                "response_should_cover": ["Root cause"],
                "tone": "Analytical",
                "sources_to_draw_on": "Ward Room, duty data",
            },
        })
        ctx = {
            "_ward_room_activity": "Recent Ward Room discussion:\n  - [thread] Bones: Latency issue",
            "_recent_alerts": "Recent bridge alerts:\n  - [WARNING] High latency",
        }
        result = _build_user_prompt(ctx, [analysis])

        assert "## Composition Brief" in result
        assert "## Recent Ward Room Activity" in result
        assert "## Recent Alerts" in result

        # Brief should appear before SA context
        brief_pos = result.index("## Composition Brief")
        wr_pos = result.index("## Recent Ward Room Activity")
        assert brief_pos < wr_pos

    def test_silent_intended_action_null_brief(self):
        analysis = _make_analyze_result({
            "contribution_assessment": "SILENT",
            "intended_actions": ["silent"],
            "composition_brief": None,
        })
        assert _should_short_circuit([analysis]) is True
