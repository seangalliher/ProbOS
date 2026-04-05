"""Tests for AD-540: Memory Provenance Boundary — Knowledge Source Attribution."""

from __future__ import annotations

from pathlib import Path

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.standing_orders import compose_instructions, clear_cache
from probos.types import IntentDescriptor


# ---------------------------------------------------------------------------
# Concrete subclass for testing
# ---------------------------------------------------------------------------

class ProvenanceTestAgent(CognitiveAgent):
    """Minimal CognitiveAgent for provenance boundary tests."""

    agent_type = "provenance_test"
    _handled_intents = {"direct_message", "ward_room_notification", "proactive_think"}
    instructions = "You are a test agent."
    intent_descriptors = [
        IntentDescriptor(
            name="direct_message",
            params={"text": "input"},
            description="DM",
            tier="domain",
        )
    ]


# ---------------------------------------------------------------------------
# Test data (AD-541: includes source and verified keys)
# ---------------------------------------------------------------------------

SAMPLE_MEMORIES = [
    {"age": "3m", "input": "Captain asked about trust scores", "reflection": "Trust query",
     "source": "direct", "verified": False},
    {"age": "1h", "input": "Ward Room thread about routing", "reflection": "Routing discussion",
     "source": "direct", "verified": True},
]

MEMORY_NO_AGE = [
    {"input": "Observed latency spike in medical pool", "source": "direct", "verified": False},
]

MEMORY_REFLECTION_ONLY = [
    {"age": "5m", "reflection": "Analyzed codebase index performance",
     "source": "direct", "verified": False},
]


# ---------------------------------------------------------------------------
# Helper method tests
# ---------------------------------------------------------------------------

class TestFormatMemorySection:
    """Test _format_memory_section helper directly."""

    def setup_method(self):
        self.agent = ProvenanceTestAgent.__new__(ProvenanceTestAgent)

    def test_boundary_markers_present(self):
        lines = self.agent._format_memory_section(SAMPLE_MEMORIES)
        text = "\n".join(lines)
        assert "=== SHIP MEMORY (your experiences aboard this vessel) ===" in text
        assert "=== END SHIP MEMORY ===" in text
        assert "Do NOT confuse" in text

    def test_memories_between_markers(self):
        lines = self.agent._format_memory_section(SAMPLE_MEMORIES)
        text = "\n".join(lines)
        start = text.index("=== SHIP MEMORY")
        end = text.index("=== END SHIP MEMORY ===")
        between = text[start:end]
        assert "Captain asked about trust scores" in between
        assert "Ward Room thread about routing" in between

    def test_age_prefix_included(self):
        lines = self.agent._format_memory_section(SAMPLE_MEMORIES)
        text = "\n".join(lines)
        assert "[3m ago]" in text
        assert "[1h ago]" in text

    def test_no_age_prefix_when_missing(self):
        lines = self.agent._format_memory_section(MEMORY_NO_AGE)
        text = "\n".join(lines)
        assert "ago]" not in text
        assert "Observed latency spike" in text

    def test_reflection_fallback(self):
        lines = self.agent._format_memory_section(MEMORY_REFLECTION_ONLY)
        text = "\n".join(lines)
        assert "Analyzed codebase index performance" in text

    def test_structure_order(self):
        lines = self.agent._format_memory_section(SAMPLE_MEMORIES)
        # Opening marker is first
        assert "SHIP MEMORY" in lines[0]
        # Instruction lines (AD-541: 3 instruction lines + blank = 4 header lines)
        assert "YOUR experiences" in lines[1]
        assert "[direct]" in lines[2]
        assert "[verified]" in lines[3]
        # Blank line separator
        assert lines[4] == ""
        # AD-567b: Memory entries now have header + content lines
        assert "[direct | unverified]" in lines[5]
        assert "Captain asked about trust scores" in lines[6]
        assert "[direct | verified]" in lines[7]
        assert "Ward Room thread about routing" in lines[8]
        # Blank line before closing
        assert lines[9] == ""
        # Closing marker is last
        assert "END SHIP MEMORY" in lines[10]

    def test_empty_memories(self):
        lines = self.agent._format_memory_section([])
        text = "\n".join(lines)
        # Markers still present even with empty list (helper always wraps)
        assert "=== SHIP MEMORY" in text
        assert "=== END SHIP MEMORY ===" in text


# ---------------------------------------------------------------------------
# _build_user_message path tests
# ---------------------------------------------------------------------------

class TestDirectMessagePath:
    """Boundary markers in direct_message path."""

    def setup_method(self):
        self.agent = ProvenanceTestAgent.__new__(ProvenanceTestAgent)

    def test_markers_present_with_memories(self):
        observation = {
            "intent": "direct_message",
            "params": {"text": "What do you know?"},
            "recent_memories": SAMPLE_MEMORIES,
        }
        result = self.agent._build_user_message(observation)
        assert "=== SHIP MEMORY" in result
        assert "=== END SHIP MEMORY ===" in result
        assert "Do NOT confuse" in result

    def test_no_markers_without_memories(self):
        observation = {
            "intent": "direct_message",
            "params": {"text": "Hello"},
        }
        result = self.agent._build_user_message(observation)
        assert "SHIP MEMORY" not in result

    def test_no_markers_with_empty_memories(self):
        observation = {
            "intent": "direct_message",
            "params": {"text": "Hello"},
            "recent_memories": [],
        }
        result = self.agent._build_user_message(observation)
        assert "SHIP MEMORY" not in result


class TestWardRoomPath:
    """Boundary markers in ward_room_notification path."""

    def setup_method(self):
        self.agent = ProvenanceTestAgent.__new__(ProvenanceTestAgent)

    def test_markers_present_with_memories(self):
        observation = {
            "intent": "ward_room_notification",
            "params": {
                "channel_name": "bridge",
                "author_callsign": "LaForge",
                "title": "Routing Update",
                "author_id": "test-agent",
            },
            "recent_memories": SAMPLE_MEMORIES,
            "context": "",
        }
        result = self.agent._build_user_message(observation)
        assert "=== SHIP MEMORY" in result
        assert "=== END SHIP MEMORY ===" in result
        assert "Do NOT confuse" in result

    def test_no_markers_without_memories(self):
        observation = {
            "intent": "ward_room_notification",
            "params": {
                "channel_name": "bridge",
                "author_callsign": "LaForge",
                "title": "Test",
                "author_id": "test-agent",
            },
            "context": "",
        }
        result = self.agent._build_user_message(observation)
        assert "SHIP MEMORY" not in result


class TestProactiveThinkPath:
    """Boundary markers in proactive_think path."""

    def setup_method(self):
        self.agent = ProvenanceTestAgent.__new__(ProvenanceTestAgent)

    def test_markers_present_with_memories(self):
        observation = {
            "intent": "proactive_think",
            "params": {
                "trust_score": 0.7,
                "agency_level": "suggestive",
                "rank": "ensign",
                "context_parts": {"recent_memories": SAMPLE_MEMORIES},
            },
        }
        result = self.agent._build_user_message(observation)
        assert "=== SHIP MEMORY" in result
        assert "=== END SHIP MEMORY ===" in result
        assert "Do NOT confuse" in result

    def test_no_memories_fallback(self):
        observation = {
            "intent": "proactive_think",
            "params": {
                "trust_score": 0.5,
                "agency_level": "suggestive",
                "rank": "ensign",
                "context_parts": {},
            },
        }
        result = self.agent._build_user_message(observation)
        assert "no stored episodic memories" in result
        assert "SHIP MEMORY" not in result


# ---------------------------------------------------------------------------
# Old header removal verification
# ---------------------------------------------------------------------------

class TestOldHeadersRemoved:
    """Ensure old untagged memory headers no longer appear."""

    def setup_method(self):
        self.agent = ProvenanceTestAgent.__new__(ProvenanceTestAgent)

    def test_dm_no_old_header(self):
        observation = {
            "intent": "direct_message",
            "params": {"text": "test"},
            "recent_memories": SAMPLE_MEMORIES,
        }
        result = self.agent._build_user_message(observation)
        assert "Your recent memories" not in result

    def test_wr_no_old_header(self):
        observation = {
            "intent": "ward_room_notification",
            "params": {
                "channel_name": "bridge",
                "author_callsign": "LaForge",
                "title": "Test",
                "author_id": "test-agent",
            },
            "recent_memories": SAMPLE_MEMORIES,
            "context": "",
        }
        result = self.agent._build_user_message(observation)
        assert "Your relevant memories" not in result

    def test_proactive_no_old_header(self):
        observation = {
            "intent": "proactive_think",
            "params": {
                "trust_score": 0.7,
                "agency_level": "suggestive",
                "rank": "ensign",
                "context_parts": {"recent_memories": SAMPLE_MEMORIES},
            },
        }
        result = self.agent._build_user_message(observation)
        assert "Recent memories (your experiences)" not in result


# ---------------------------------------------------------------------------
# Standing order content test
# ---------------------------------------------------------------------------

class TestStandingOrderAttribution:
    """Verify Knowledge Source Attribution in federation standing orders."""

    def test_attribution_section_present(self):
        clear_cache()
        result = compose_instructions(
            "provenance_test",
            "Test instructions.",
        )
        assert "Knowledge Source Attribution" in result
        assert "[observed]" in result
        assert "[training]" in result
        assert "[inferred]" in result

    def test_attribution_mentions_ship_memory_markers(self):
        clear_cache()
        result = compose_instructions(
            "provenance_test",
            "Test instructions.",
        )
        assert "SHIP MEMORY" in result
        assert "Training Knowledge" in result
