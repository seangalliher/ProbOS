"""AD-649: Communication Context Awareness — Tests.

Verifies communication context derivation, ANALYZE tone field injection,
and COMPOSE voice/register adaptation across channel types.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.sub_tasks.analyze import (
    _build_dm_comprehension_prompt,
    _build_situation_review_prompt,
    _build_thread_analysis_prompt,
)
from probos.cognitive.sub_tasks.compose import (
    _build_dm_compose_prompt,
    _build_proactive_compose_prompt,
    _build_ward_room_compose_prompt,
)
from probos.cognitive.cognitive_agent import CognitiveAgent, derive_communication_context


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(**kwargs) -> CognitiveAgent:
    agent = CognitiveAgent(agent_id="test-agent", instructions="Test agent.")
    agent.callsign = "Nova"
    agent.agent_type = "operations_officer"
    agent._runtime = kwargs.get("runtime", None)
    return agent


def _make_observation(channel_name: str = "", is_dm_channel: bool = False) -> dict:
    """Build minimal observation dict matching chain entry point expectations."""
    return {
        "params": {
            "channel_name": channel_name,
            "is_dm_channel": is_dm_channel,
        },
    }


# ---------------------------------------------------------------------------
# Tests 1-5: Communication context derivation
# ---------------------------------------------------------------------------

class TestCommunicationContextDerivation:

    def test_dm_channel(self):
        """Test 1: DM channel → private_conversation."""
        assert derive_communication_context("dm-captain-nova", is_dm_channel=True) == "private_conversation"

    def test_bridge_channel(self):
        """Test 2: bridge channel → bridge_briefing."""
        assert derive_communication_context("bridge") == "bridge_briefing"

    def test_recreation_channel(self):
        """Test 3: recreation channel → casual_social."""
        assert derive_communication_context("recreation") == "casual_social"

    def test_department_channel(self):
        """Test 4: department channel → department_discussion."""
        assert derive_communication_context("science") == "department_discussion"

    def test_ship_wide_channel(self):
        """Test 5: general channel → ship_wide."""
        assert derive_communication_context("general") == "ship_wide"


# ---------------------------------------------------------------------------
# Tests 6-9: Ward Room compose voice and register
# ---------------------------------------------------------------------------

class TestWardRoomCompose:

    def test_includes_voice_instruction(self):
        """Test 6: Ward Room compose includes voice instruction."""
        context = {
            "_agent_type": "operations_officer",
            "_communication_context": "department_discussion",
        }
        system_prompt, _ = _build_ward_room_compose_prompt(
            context, [], "Nova", "Operations"
        )
        assert "Speak in your natural voice" in system_prompt
        assert "Show your reasoning" in system_prompt

    def test_recreation_register(self):
        """Test 7: recreation register adds casual guidance."""
        context = {
            "_agent_type": "operations_officer",
            "_communication_context": "casual_social",
        }
        system_prompt, _ = _build_ward_room_compose_prompt(
            context, [], "Nova", "Operations"
        )
        assert "relaxed, playful, and social" in system_prompt

    def test_bridge_register(self):
        """Test 8: bridge register adds strategic guidance."""
        context = {
            "_agent_type": "operations_officer",
            "_communication_context": "bridge_briefing",
        }
        system_prompt, _ = _build_ward_room_compose_prompt(
            context, [], "Nova", "Operations"
        )
        assert "concise, strategic, and command-focused" in system_prompt

    def test_ship_wide_register(self):
        """Test 9: ship-wide register adds measured guidance."""
        context = {
            "_agent_type": "operations_officer",
            "_communication_context": "ship_wide",
        }
        system_prompt, _ = _build_ward_room_compose_prompt(
            context, [], "Nova", "Operations"
        )
        assert "observation versus recommendation" in system_prompt


# ---------------------------------------------------------------------------
# Test 10: ANALYZE thread analysis includes communication context
# ---------------------------------------------------------------------------

class TestAnalyzeThreadContext:

    def test_thread_analysis_includes_context(self):
        """Test 10: thread analysis tone field includes communication context."""
        context = {
            "_agent_type": "operations_officer",
            "_communication_context": "casual_social",
            "context": "Some thread content",
        }
        _, user_prompt = _build_thread_analysis_prompt(
            context, [], "Nova", "Operations"
        )
        assert "casual_social" in user_prompt
        assert "Private conversations are warm" in user_prompt


# ---------------------------------------------------------------------------
# Test 11: Proactive duty compose includes voice guidance
# ---------------------------------------------------------------------------

class TestProactiveDutyCompose:

    def test_duty_compose_includes_voice(self):
        """Test 11: proactive duty compose includes voice guidance."""
        context = {
            "_agent_type": "operations_officer",
            "_active_duty": {
                "duty_id": "scout_report",
                "description": "External research scan",
            },
        }
        system_prompt, _ = _build_proactive_compose_prompt(
            context, [], "Nova", "Operations"
        )
        assert "Speak in your natural voice" in system_prompt
        assert "Show your reasoning" in system_prompt


# ---------------------------------------------------------------------------
# Tests 12-13: DM compose dynamic recipient
# ---------------------------------------------------------------------------

class TestDMCompose:

    def test_dynamic_recipient(self):
        """Test 12: DM compose uses dynamic recipient."""
        context = {
            "_agent_type": "operations_officer",
            "_dm_recipient": "Lieutenant Sage",
        }
        system_prompt, _ = _build_dm_compose_prompt(
            context, [], "Nova", "Operations"
        )
        assert "private conversation with Lieutenant Sage" in system_prompt
        # The mode framing should not reference "the Captain" — but standing
        # orders / personality preamble may mention the Captain generically.
        # Verify the mode-specific sentence uses the dynamic recipient.
        assert "1:1 private conversation with Lieutenant Sage" in system_prompt

    def test_defaults_to_captain(self):
        """Test 13: DM compose defaults to Captain when no recipient."""
        context = {
            "_agent_type": "operations_officer",
        }
        system_prompt, _ = _build_dm_compose_prompt(
            context, [], "Nova", "Operations"
        )
        assert "private conversation with a crew member" in system_prompt


# ---------------------------------------------------------------------------
# Test 14: Communication context defaults to department_discussion
# ---------------------------------------------------------------------------

class TestContextDefault:

    def test_defaults_to_department(self):
        """Test 14: unknown channel defaults to department_discussion."""
        assert derive_communication_context("custom-channel-xyz") == "department_discussion"
