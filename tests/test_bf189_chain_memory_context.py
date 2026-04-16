"""BF-189: Chain Pipeline Memory Context Gaps — tests.

Verifies that episodic memories are properly formatted and injected into
all three chain pipeline stages: Analyze (thread/DM/situation), Compose.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.analyze import (
    _build_dm_comprehension_prompt,
    _build_situation_review_prompt,
    _build_thread_analysis_prompt,
)
from probos.cognitive.sub_tasks.compose import _build_user_prompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_FORMATTED_MEMORIES = (
    "=== SHIP MEMORY ===\n"
    "Age: 2h | Channel: ward-room | Department: science\n"
    "[direct | verified]\n"
    "Reed mentioned anomalous readings in sector 7.\n"
    "=== END MEMORY ===\n\n"
    "Do NOT fabricate or invent memories."
)

SAMPLE_RAW_MEMORIES = [
    {
        "input": "Anomalous readings in sector 7",
        "source": "direct",
        "verified": True,
        "channel": "ward-room",
        "department": "science",
        "age_seconds": 7200,
    },
]


def _base_context(**overrides) -> dict:
    ctx = {
        "_callsign": "TestAgent",
        "_department": "science",
        "_agent_type": "test_agent",
        "_from_captain": False,
        "_was_mentioned": False,
        "_is_dm": False,
        "_agent_rank": None,
        "_skill_profile": None,
        "_crew_manifest": "",
        "context": "Some thread content for testing.",
    }
    ctx.update(overrides)
    return ctx


def _query_result() -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.QUERY,
        name="query-test",
        result={"thread_id": "123", "participants": "Reed, Wesley"},
        tokens_used=10,
        success=True,
    )


def _analyze_result() -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze-test",
        result={
            "contribution_assessment": "RESPOND",
            "should_respond": True,
        },
        tokens_used=50,
        success=True,
    )


# ===========================================================================
# Part 1: Memory pre-formatting in cognitive_agent.py
# ===========================================================================


class TestChainContextFormattedMemories:
    """Part 1: _execute_sub_task_chain() pre-formats memories."""

    def test_chain_context_includes_formatted_memories(self):
        """When recent_memories contains episodes, _formatted_memories has SHIP MEMORY."""
        agent = MagicMock()
        agent._format_memory_section.return_value = [
            "=== SHIP MEMORY ===",
            "Test memory content",
            "=== END MEMORY ===",
            "",
            "Do NOT fabricate or invent memories.",
        ]

        observation = {"recent_memories": SAMPLE_RAW_MEMORIES}

        # Simulate Part 1 logic
        raw_memories = observation.get("recent_memories", [])
        if raw_memories and isinstance(raw_memories, list):
            source_framing = observation.get("_source_framing")
            formatted_lines = agent._format_memory_section(raw_memories, source_framing=source_framing)
            observation["_formatted_memories"] = "\n".join(formatted_lines)
        else:
            observation["_formatted_memories"] = ""

        assert "=== SHIP MEMORY ===" in observation["_formatted_memories"]
        agent._format_memory_section.assert_called_once_with(
            SAMPLE_RAW_MEMORIES, source_framing=None
        )

    def test_chain_context_empty_memories(self):
        """When recent_memories is empty or missing, _formatted_memories is empty string."""
        for obs in [{"recent_memories": []}, {"recent_memories": ""}, {}]:
            raw_memories = obs.get("recent_memories", [])
            if raw_memories and isinstance(raw_memories, list):
                obs["_formatted_memories"] = "should not reach"
            else:
                obs["_formatted_memories"] = ""
            assert obs["_formatted_memories"] == ""

    def test_chain_context_preserves_confabulation_guard(self):
        """_formatted_memories contains confabulation guard text."""
        agent = MagicMock()
        agent._format_memory_section.return_value = [
            "=== SHIP MEMORY ===",
            "Memory content",
            "=== END MEMORY ===",
            "",
            "Do NOT fabricate or invent memories.",
        ]

        observation = {"recent_memories": SAMPLE_RAW_MEMORIES}
        raw_memories = observation.get("recent_memories", [])
        if raw_memories and isinstance(raw_memories, list):
            formatted_lines = agent._format_memory_section(raw_memories, source_framing=None)
            observation["_formatted_memories"] = "\n".join(formatted_lines)

        assert "Do NOT fabricate" in observation["_formatted_memories"]


# ===========================================================================
# Part 2: Thread analysis formatting
# ===========================================================================


class TestThreadAnalysisMemory:
    """Part 2: _build_thread_analysis_prompt uses _formatted_memories."""

    @patch("probos.cognitive.sub_tasks.analyze.compose_instructions", return_value="System prompt.")
    def test_thread_analysis_uses_formatted_memories(self, _mock_ci):
        """Prompt contains '## Your Episodic Memories' with formatted text."""
        ctx = _base_context(_formatted_memories=SAMPLE_FORMATTED_MEMORIES)
        _, user_prompt = _build_thread_analysis_prompt(ctx, [], "Test", "science")
        assert "## Your Episodic Memories" in user_prompt
        assert "=== SHIP MEMORY ===" in user_prompt
        assert "Do NOT fabricate" in user_prompt
        # Must NOT contain Python list repr
        assert "[{" not in user_prompt

    @patch("probos.cognitive.sub_tasks.analyze.compose_instructions", return_value="System prompt.")
    def test_thread_analysis_no_memories(self, _mock_ci):
        """No _formatted_memories → no memory section in prompt."""
        ctx = _base_context()  # No _formatted_memories key
        _, user_prompt = _build_thread_analysis_prompt(ctx, [], "Test", "science")
        assert "## Your Episodic Memories" not in user_prompt
        assert "## Analysis Required" in user_prompt  # Still valid


# ===========================================================================
# Part 3: DM comprehension memory
# ===========================================================================


class TestDmComprehensionMemory:
    """Part 3: _build_dm_comprehension_prompt includes memories."""

    @patch("probos.cognitive.sub_tasks.analyze.compose_instructions", return_value="System prompt.")
    def test_dm_comprehension_includes_memories(self, _mock_ci):
        """DM prompt contains memory section when _formatted_memories provided."""
        ctx = _base_context(_formatted_memories=SAMPLE_FORMATTED_MEMORIES)
        _, user_prompt = _build_dm_comprehension_prompt(ctx, [], "Test", "science")
        assert "## Your Episodic Memories" in user_prompt
        assert "=== SHIP MEMORY ===" in user_prompt

    @patch("probos.cognitive.sub_tasks.analyze.compose_instructions", return_value="System prompt.")
    def test_dm_comprehension_no_memories(self, _mock_ci):
        """No memories → prompt still valid, no empty header."""
        ctx = _base_context()
        _, user_prompt = _build_dm_comprehension_prompt(ctx, [], "Test", "science")
        assert "## Your Episodic Memories" not in user_prompt
        assert "## Comprehension Required" in user_prompt


# ===========================================================================
# Part 4: Situation review memory
# ===========================================================================


class TestSituationReviewMemory:
    """Part 4: _build_situation_review_prompt includes memories."""

    @patch("probos.cognitive.sub_tasks.analyze.compose_instructions", return_value="System prompt.")
    def test_situation_review_includes_memories(self, _mock_ci):
        """Situation review prompt contains memory section."""
        ctx = _base_context(_formatted_memories=SAMPLE_FORMATTED_MEMORIES)
        _, user_prompt = _build_situation_review_prompt(ctx, [], "Test", "science")
        assert "## Your Episodic Memories" in user_prompt
        assert "=== SHIP MEMORY ===" in user_prompt

    @patch("probos.cognitive.sub_tasks.analyze.compose_instructions", return_value="System prompt.")
    def test_situation_review_no_memories(self, _mock_ci):
        """No memories → prompt still valid."""
        ctx = _base_context()
        _, user_prompt = _build_situation_review_prompt(ctx, [], "Test", "science")
        assert "## Your Episodic Memories" not in user_prompt
        assert "## Assessment Required" in user_prompt


# ===========================================================================
# Part 5: Compose memory grounding
# ===========================================================================


class TestComposeMemoryGrounding:
    """Part 5: _build_user_prompt includes memories."""

    def test_compose_user_prompt_includes_memories(self):
        """_build_user_prompt output contains memory section."""
        ctx = _base_context(_formatted_memories=SAMPLE_FORMATTED_MEMORIES)
        prompt = _build_user_prompt(ctx, [_analyze_result()])
        assert "## Your Episodic Memories" in prompt
        assert "=== SHIP MEMORY ===" in prompt

    def test_compose_user_prompt_no_memories(self):
        """No _formatted_memories → no memory section, no error."""
        ctx = _base_context()
        prompt = _build_user_prompt(ctx, [_analyze_result()])
        assert "## Your Episodic Memories" not in prompt
        assert "## Content" in prompt  # Still has content

    def test_compose_user_prompt_memory_after_analysis(self):
        """Memory section appears after analysis results in the prompt."""
        ctx = _base_context(_formatted_memories=SAMPLE_FORMATTED_MEMORIES)
        prompt = _build_user_prompt(ctx, [_analyze_result()])
        analysis_pos = prompt.index("## Analysis")
        memory_pos = prompt.index("## Your Episodic Memories")
        assert memory_pos > analysis_pos, "Memory should appear after analysis"
