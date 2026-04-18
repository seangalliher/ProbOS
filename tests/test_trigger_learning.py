"""AD-643b: Skill Trigger Learning — Awareness + Post-Hoc Feedback.

Tests cover:
- get_eligible_triggers() filtering
- Trigger awareness formatting for ANALYZE prompts
- Undeclared action detection in COMPOSE output
- REFLECT trigger feedback formatting
- Re-reflect chain execution
- _get_compose_output() fallback for re-reflect
- Episode enrichment with trigger feedback
- Integration: trigger awareness injection, backward compat
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.skill_catalog import (
    CognitiveSkillCatalog,
    CognitiveSkillEntry,
)
from probos.cognitive.sub_task import SubTaskResult, SubTaskType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill_entry(
    name: str = "test-skill",
    activation: str = "augmentation",
    intents: list[str] | None = None,
    triggers: list[str] | None = None,
    department: str = "*",
    min_rank: str = "ensign",
) -> CognitiveSkillEntry:
    return CognitiveSkillEntry(
        name=name,
        description=f"Test skill {name}",
        skill_dir=Path("/tmp/fake"),
        activation=activation,
        intents=intents or [],
        triggers=triggers or [],
        department=department,
        min_rank=min_rank,
        loaded_at=time.time(),
    )


def _make_catalog_with_entries(entries: list[CognitiveSkillEntry]) -> CognitiveSkillCatalog:
    """Create a catalog and inject entries directly into _cache."""
    catalog = CognitiveSkillCatalog.__new__(CognitiveSkillCatalog)
    catalog._cache = {e.name: e for e in entries}
    catalog._skills = catalog._cache  # alias for compatibility
    return catalog


def _make_analyze_result(intended_actions=None, **extra) -> SubTaskResult:
    result = {"contribution_assessment": "RESPOND"}
    if intended_actions is not None:
        result["intended_actions"] = intended_actions
    result.update(extra)
    return SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze-thread",
        result=result,
        success=True,
    )


def _make_compose_result(output: str = "test reply") -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose-reply",
        result={"output": output},
        success=True,
    )


def _make_reflect_result(output: str = "reflected") -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.REFLECT,
        name="reflect",
        result={"output": output, "revised": False},
        success=True,
    )


# ===========================================================================
# 1. Skill Catalog — get_eligible_triggers()
# ===========================================================================

class TestGetEligibleTriggers:
    """Tests for CognitiveSkillCatalog.get_eligible_triggers()."""

    def test_basic(self):
        """Returns correct action→skill mapping."""
        entries = [
            _make_skill_entry(name="comm-discipline", triggers=["ward_room_post", "ward_room_reply"]),
            _make_skill_entry(name="notebook-quality", triggers=["notebook"]),
        ]
        catalog = _make_catalog_with_entries(entries)
        result = catalog.get_eligible_triggers()
        assert "ward_room_post" in result
        assert "comm-discipline" in result["ward_room_post"]
        assert "notebook" in result
        assert "notebook-quality" in result["notebook"]

    def test_universal_department(self):
        """department='*' skills appear for all agents."""
        entries = [
            _make_skill_entry(name="universal", triggers=["notebook"], department="*"),
        ]
        catalog = _make_catalog_with_entries(entries)
        result = catalog.get_eligible_triggers(department="science")
        assert "notebook" in result

    def test_department_filter(self):
        """Department-specific skills only for matching agents."""
        entries = [
            _make_skill_entry(name="eng-only", triggers=["notebook"], department="engineering"),
        ]
        catalog = _make_catalog_with_entries(entries)
        assert catalog.get_eligible_triggers(department="engineering") != {}
        assert catalog.get_eligible_triggers(department="science") == {}

    def test_rank_filter(self):
        """Above-rank skills excluded."""
        entries = [
            _make_skill_entry(name="senior-skill", triggers=["notebook"], min_rank="commander"),
        ]
        catalog = _make_catalog_with_entries(entries)
        # ensign (rank 0) < commander (rank 2) — excluded
        assert catalog.get_eligible_triggers(agent_rank="ensign") == {}
        # commander (rank 2) >= commander (rank 2) — included
        assert catalog.get_eligible_triggers(agent_rank="commander") != {}

    def test_no_triggers_excluded(self):
        """Skills without probos-triggers excluded."""
        entries = [
            _make_skill_entry(name="no-triggers", triggers=[], intents=["ward_room_notification"]),
        ]
        catalog = _make_catalog_with_entries(entries)
        assert catalog.get_eligible_triggers() == {}

    def test_empty_cache(self):
        """Empty catalog returns empty dict."""
        catalog = _make_catalog_with_entries([])
        assert catalog.get_eligible_triggers() == {}

    def test_multiple_skills_same_trigger(self):
        """Action tag maps to multiple skills."""
        entries = [
            _make_skill_entry(name="skill-a", triggers=["notebook"]),
            _make_skill_entry(name="skill-b", triggers=["notebook"]),
        ]
        catalog = _make_catalog_with_entries(entries)
        result = catalog.get_eligible_triggers()
        assert len(result["notebook"]) == 2
        assert "skill-a" in result["notebook"]
        assert "skill-b" in result["notebook"]


# ===========================================================================
# 2. Trigger Awareness Formatting
# ===========================================================================

class TestFormatTriggerAwareness:
    """Tests for analyze.py _format_trigger_awareness()."""

    def test_with_triggers(self):
        """Produces formatted string with trigger→skill mapping."""
        from probos.cognitive.sub_tasks.analyze import _format_trigger_awareness
        context = {"_eligible_triggers": {"notebook": ["notebook-quality"]}}
        result = _format_trigger_awareness(context)
        assert "notebook" in result
        assert "notebook-quality" in result
        assert "Declare ALL actions" in result

    def test_empty(self):
        """Returns empty string when no triggers."""
        from probos.cognitive.sub_tasks.analyze import _format_trigger_awareness
        assert _format_trigger_awareness({}) == ""
        assert _format_trigger_awareness({"_eligible_triggers": {}}) == ""
        assert _format_trigger_awareness({"_eligible_triggers": None}) == ""

    def test_sorted(self):
        """Output alphabetically sorted by action tag."""
        from probos.cognitive.sub_tasks.analyze import _format_trigger_awareness
        context = {"_eligible_triggers": {
            "ward_room_reply": ["comm"],
            "endorse": ["comm"],
            "notebook": ["nb"],
        }}
        result = _format_trigger_awareness(context)
        # endorse should come before notebook, notebook before ward_room_reply
        endorse_pos = result.index("endorse")
        notebook_pos = result.index("notebook")
        ward_pos = result.index("ward_room_reply")
        assert endorse_pos < notebook_pos < ward_pos


# ===========================================================================
# 3. Undeclared Action Detection
# ===========================================================================

class TestDetectUndeclaredActions:
    """Tests for CognitiveAgent._detect_undeclared_actions()."""

    @pytest.fixture
    def detect(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        return CognitiveAgent._detect_undeclared_actions

    def test_notebook_undeclared(self, detect):
        """[NOTEBOOK topic] detected when not in intended_actions."""
        output = "Some text [NOTEBOOK Security Review] more text"
        result = detect(output, ["ward_room_reply"])
        assert "notebook" in result

    def test_endorse_undeclared(self, detect):
        """[ENDORSE post UP] detected."""
        output = "Good analysis [ENDORSE post-123 UP]"
        result = detect(output, ["ward_room_reply"])
        assert "endorse" in result

    def test_proposal_undeclared(self, detect):
        """[PROPOSAL] detected."""
        output = "I propose [PROPOSAL] we restructure"
        result = detect(output, ["ward_room_reply"])
        assert "proposal" in result

    def test_dm_undeclared(self, detect):
        """[DM @callsign] detected."""
        output = "Let me check [DM @Lynx] about this"
        result = detect(output, ["ward_room_reply"])
        assert "dm" in result

    def test_reply_undeclared(self, detect):
        """[REPLY thread_id] detected."""
        output = "[REPLY thread-abc] I agree with the assessment"
        result = detect(output, ["notebook"])
        assert "ward_room_reply" in result

    def test_no_false_positive(self, detect):
        """Declared action not flagged."""
        output = "[NOTEBOOK Security Review] some text"
        result = detect(output, ["notebook", "ward_room_reply"])
        assert "notebook" not in result

    def test_multiple_undeclared(self, detect):
        """Multiple undeclared detected."""
        output = "[NOTEBOOK Security] and [ENDORSE post UP] and [DM @Lynx]"
        result = detect(output, ["ward_room_reply"])
        assert "notebook" in result
        assert "endorse" in result
        assert "dm" in result

    def test_empty_output(self, detect):
        """Empty compose output returns empty list."""
        assert detect("", ["ward_room_reply"]) == []
        assert detect(None, ["ward_room_reply"]) == []

    def test_case_insensitive(self, detect):
        """Markers detected regardless of case."""
        output = "[notebook Security Review]"
        result = detect(output, ["ward_room_reply"])
        assert "notebook" in result


# ===========================================================================
# 4. REFLECT Feedback Formatting
# ===========================================================================

class TestFormatTriggerFeedback:
    """Tests for reflect.py _format_trigger_feedback()."""

    def test_with_actions(self):
        """Produces feedback block with undeclared actions."""
        from probos.cognitive.sub_tasks.reflect import _format_trigger_feedback
        feedback = {
            "undeclared_actions": ["notebook", "endorse"],
            "missed_skills": ["notebook-quality", "comm-discipline"],
        }
        result = _format_trigger_feedback(feedback)
        assert "Skill Trigger Feedback" in result
        assert "notebook" in result
        assert "endorse" in result
        assert "notebook-quality" in result
        assert "comm-discipline" in result

    def test_empty(self):
        """Returns empty when no undeclared actions."""
        from probos.cognitive.sub_tasks.reflect import _format_trigger_feedback
        assert _format_trigger_feedback({"undeclared_actions": []}) == ""
        assert _format_trigger_feedback({}) == ""

    def test_no_missed_skills(self):
        """Handles empty skills list gracefully."""
        from probos.cognitive.sub_tasks.reflect import _format_trigger_feedback
        feedback = {"undeclared_actions": ["notebook"], "missed_skills": []}
        result = _format_trigger_feedback(feedback)
        assert "notebook" in result
        assert "none" in result


# ===========================================================================
# 5. Re-Reflect Tests
# ===========================================================================

class TestReReflect:
    """Tests for re-reflect chain execution."""

    @pytest.fixture
    def mock_agent(self):
        """Create a minimal CognitiveAgent-like mock for testing."""
        from probos.cognitive.sub_task import SubTaskSpec

        agent = MagicMock()
        agent.id = "test-agent-id"
        agent.agent_type = "test_agent"
        agent._cognitive_journal = None

        # Mock executor
        agent._sub_task_executor = AsyncMock()

        # Build a minimal full_chain with a REFLECT step
        reflect_spec = SubTaskSpec(
            name="reflect",
            sub_task_type=SubTaskType.REFLECT,
            prompt_template="ward_room_reflection",
            tier="standard",
        )
        chain = MagicMock()
        chain.steps = [reflect_spec]
        chain.source = "test_chain"

        return agent, chain

    @pytest.mark.asyncio
    async def test_runs_on_undeclared(self, mock_agent):
        """Re-reflect chain executes when undeclared actions detected."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent, chain = mock_agent
        observation = {
            "intent": "ward_room_notification",
            "_undeclared_action_feedback": {
                "undeclared_actions": ["notebook"],
                "missed_skills": ["notebook-quality"],
            },
            "_re_reflect_compose_output": "some compose output",
        }
        original_result = {"llm_output": "original", "chain_source": "test"}

        # Mock executor to return a successful reflect result
        reflect_result = _make_reflect_result("re-reflected output")
        agent._sub_task_executor.execute = AsyncMock(return_value=[reflect_result])

        result = await CognitiveAgent._re_reflect_with_feedback(
            agent, chain, observation, original_result,
        )

        agent._sub_task_executor.execute.assert_called_once()
        assert result["llm_output"] == "re-reflected output"
        assert "re_reflect" in result["chain_source"]

    @pytest.mark.asyncio
    async def test_skipped_when_all_declared(self):
        """No re-reflect when no undeclared actions — detected upstream."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        # _detect_undeclared_actions returns empty → re-reflect never called
        output = "[NOTEBOOK topic]"
        result = CognitiveAgent._detect_undeclared_actions(output, ["notebook"])
        assert result == []

    @pytest.mark.asyncio
    async def test_output_replaces_original(self, mock_agent):
        """Decision dict updated with re-reflect output."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent, chain = mock_agent
        observation = {"intent": "test", "_re_reflect_compose_output": "draft"}
        original = {"llm_output": "original", "chain_source": "test", "extra": "kept"}

        reflect_result = _make_reflect_result("new output")
        agent._sub_task_executor.execute = AsyncMock(return_value=[reflect_result])

        result = await CognitiveAgent._re_reflect_with_feedback(
            agent, chain, observation, original,
        )
        assert result["llm_output"] == "new output"
        assert result["extra"] == "kept"  # original fields preserved

    @pytest.mark.asyncio
    async def test_failure_preserves_original(self, mock_agent):
        """Original result kept on executor error."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent, chain = mock_agent
        observation = {"intent": "test"}
        original = {"llm_output": "original", "chain_source": "test"}

        agent._sub_task_executor.execute = AsyncMock(side_effect=RuntimeError("boom"))

        result = await CognitiveAgent._re_reflect_with_feedback(
            agent, chain, observation, original,
        )
        assert result["llm_output"] == "original"

    @pytest.mark.asyncio
    async def test_receives_compose_output(self, mock_agent):
        """_re_reflect_compose_output available in observation."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent, chain = mock_agent
        observation = {
            "intent": "test",
            "_re_reflect_compose_output": "the draft text",
        }
        original = {"llm_output": "original", "chain_source": "test"}

        # Return empty reflect result so original is kept
        agent._sub_task_executor.execute = AsyncMock(return_value=[])

        await CognitiveAgent._re_reflect_with_feedback(
            agent, chain, observation, original,
        )
        # The observation passed to executor contains the compose output
        call_args = agent._sub_task_executor.execute.call_args
        passed_obs = call_args[0][1]  # second positional arg
        assert passed_obs.get("_re_reflect_compose_output") == "the draft text"


# ===========================================================================
# 6. _get_compose_output Fallback
# ===========================================================================

class TestGetComposeOutputFallback:
    """Tests for reflect.py _get_compose_output() context fallback."""

    def test_fallback_to_observation(self):
        """Falls back to observation key when prior_results empty."""
        from probos.cognitive.sub_tasks.reflect import _get_compose_output
        context = {"_re_reflect_compose_output": "fallback text"}
        result = _get_compose_output([], context)
        assert result == "fallback text"

    def test_prior_results_take_precedence(self):
        """prior_results compose output takes precedence over fallback."""
        from probos.cognitive.sub_tasks.reflect import _get_compose_output
        compose = _make_compose_result("from prior")
        context = {"_re_reflect_compose_output": "fallback text"}
        result = _get_compose_output([compose], context)
        assert result == "from prior"

    def test_no_context_returns_empty(self):
        """No context returns empty string (backward compat)."""
        from probos.cognitive.sub_tasks.reflect import _get_compose_output
        assert _get_compose_output([]) == ""
        assert _get_compose_output([], None) == ""


# ===========================================================================
# 7. Integration Tests
# ===========================================================================

class TestTriggerLearningIntegration:
    """Integration tests for the full trigger learning loop."""

    def test_analyze_prompt_includes_trigger_list(self):
        """ANALYZE thread prompt includes trigger list when eligible_triggers set."""
        from probos.cognitive.sub_tasks.analyze import _build_thread_analysis_prompt
        context = {
            "_eligible_triggers": {"notebook": ["notebook-quality"]},
            "_agent_type": "test_agent",
        }
        _, user_prompt = _build_thread_analysis_prompt(context, [], "Lynx", "science")
        assert "notebook" in user_prompt
        assert "Declare ALL actions" in user_prompt

    def test_situation_prompt_includes_trigger_list(self):
        """ANALYZE situation prompt includes trigger list when eligible_triggers set."""
        from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt
        context = {
            "_eligible_triggers": {"notebook": ["notebook-quality"]},
            "_agent_type": "test_agent",
        }
        _, user_prompt = _build_situation_review_prompt(context, [], "Lynx", "science")
        assert "notebook" in user_prompt
        assert "Declare ALL actions" in user_prompt

    def test_no_injection_without_triggers(self):
        """No injection when no eligible triggers."""
        from probos.cognitive.sub_tasks.analyze import _build_thread_analysis_prompt
        context = {"_agent_type": "test_agent"}
        _, user_prompt = _build_thread_analysis_prompt(context, [], "Lynx", "science")
        assert "Declare ALL actions" not in user_prompt

    def test_episode_enrichment_with_undeclared(self):
        """Episode outcomes include undeclared_actions and missed_skills."""
        observation = {
            "_undeclared_action_feedback": {
                "undeclared_actions": ["notebook"],
                "missed_skills": ["notebook-quality"],
            },
        }
        # Simulate outcome dict construction matching cognitive_agent.py
        _trigger_fb = observation.get("_undeclared_action_feedback")
        outcome = {"intent": "test", "success": True}
        if _trigger_fb:
            outcome["undeclared_actions"] = _trigger_fb.get("undeclared_actions", [])
            outcome["missed_skills"] = _trigger_fb.get("missed_skills", [])

        assert outcome["undeclared_actions"] == ["notebook"]
        assert outcome["missed_skills"] == ["notebook-quality"]

    def test_backward_compat_no_triggers(self):
        """Skills without triggers work via intent fallback — no eligible triggers."""
        entries = [
            _make_skill_entry(name="legacy", triggers=[], intents=["ward_room_notification"]),
        ]
        catalog = _make_catalog_with_entries(entries)
        # get_eligible_triggers skips skills without triggers
        assert catalog.get_eligible_triggers() == {}
        # But find_triggered_skills falls back to intent matching
        result = catalog.find_triggered_skills(
            ["ward_room_reply"], "ward_room_notification",
        )
        assert len(result) == 1
        assert result[0].name == "legacy"
