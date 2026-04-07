"""AD-575: Unified Self-Awareness — Cross-Context Identity Recognition tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_agent(runtime=None, callsign="Echo"):
    """Create a CognitiveAgent with minimal runtime for self-awareness tests."""
    from probos.cognitive.cognitive_agent import CognitiveAgent

    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent._runtime = runtime
    agent.agent_type = "counselor"
    agent.id = "test-agent"
    agent._model_id = "test"
    agent._system_prompt_base = ""
    agent._max_tokens = 1000
    agent._callsign = callsign
    agent.callsign = callsign
    return agent


class TestDetectSelfInContent:
    """CognitiveAgent._detect_self_in_content() self-recognition."""

    def test_detect_self_callsign_found(self):
        agent = _make_agent(callsign="Echo")
        result = agent._detect_self_in_content(
            "Captain challenges Echo to tictactoe"
        )
        assert result != ""
        assert "Echo" in result
        assert "participant" in result

    def test_detect_self_callsign_not_found(self):
        agent = _make_agent(callsign="Echo")
        result = agent._detect_self_in_content("Captain played position 0")
        assert result == ""

    def test_detect_self_callsign_in_title_area(self):
        agent = _make_agent(callsign="Echo")
        content = (
            "Thread: [Challenge] Captain challenges Echo\n"
            "Captain: I challenge you!\nEcho: Game on!"
        )
        result = agent._detect_self_in_content(content)
        assert result != ""

    def test_detect_self_case_insensitive(self):
        agent = _make_agent(callsign="Echo")
        result = agent._detect_self_in_content("ECHO is playing well today")
        assert result != ""
        assert "participant" in result

    def test_detect_self_word_boundary(self):
        agent = _make_agent(callsign="Echo")
        result = agent._detect_self_in_content(
            "Echoing the sentiment, she echoed the captain's words"
        )
        assert result == ""

    def test_detect_self_no_callsign(self):
        agent = _make_agent(callsign="")
        result = agent._detect_self_in_content("Echo is mentioned here")
        assert result == ""

    def test_detect_self_with_game_engagement(self):
        from probos.cognitive.agent_working_memory import (
            ActiveEngagement,
            AgentWorkingMemory,
        )

        agent = _make_agent(callsign="Echo")
        wm = AgentWorkingMemory()
        wm.add_engagement(ActiveEngagement(
            engagement_type="game",
            engagement_id="g-123",
            summary="Playing tictactoe against Captain",
            state={"game_type": "tictactoe", "opponent": "Captain"},
        ))
        agent._working_memory = wm

        result = agent._detect_self_in_content(
            "Echo is playing against the Captain"
        )
        assert "game" in result.lower() or "game" in result
        assert "player" in result
        assert "Spectators" in result

    def test_detect_self_without_game_engagement(self):
        from probos.cognitive.agent_working_memory import AgentWorkingMemory

        agent = _make_agent(callsign="Echo")
        agent._working_memory = AgentWorkingMemory()

        result = agent._detect_self_in_content(
            "Echo shared a great insight earlier"
        )
        assert "participant" in result
        assert "game" not in result.lower()
        assert "Spectators" not in result


class TestWardRoomSelfCueIntegration:
    """Integration: _build_user_message() injects self-cue in WR path."""

    def _build_wr_observation(self, context_text: str) -> dict:
        """Build a minimal ward_room_notification observation."""
        return {
            "type": "intent",
            "intent": "ward_room_notification",
            "params": {
                "channel_name": "recreation",
                "author_callsign": "Lynx",
                "title": "Game Discussion",
                "author_id": "science_officer",
            },
            "context": context_text,
        }

    def test_ward_room_message_includes_self_cue(self):
        agent = _make_agent(callsign="Echo")
        # Stub temporal context and memory formatting
        agent._build_temporal_context = lambda: ""
        agent._format_memory_section = lambda x: []
        agent._orientation_rendered = ""

        obs = self._build_wr_observation(
            "Lynx: Great game! Echo is really thinking strategically."
        )
        result = agent._build_user_message(obs)
        assert "Your callsign is Echo" in result
        assert "participant" in result

    def test_ward_room_message_excludes_self_cue_when_not_mentioned(self):
        agent = _make_agent(callsign="Echo")
        agent._build_temporal_context = lambda: ""
        agent._format_memory_section = lambda x: []
        agent._orientation_rendered = ""

        obs = self._build_wr_observation(
            "Lynx: The Captain just made a bold move!"
        )
        result = agent._build_user_message(obs)
        assert "Your callsign is" not in result
