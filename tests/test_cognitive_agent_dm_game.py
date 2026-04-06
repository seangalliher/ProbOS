"""AD-572: Tests for CognitiveAgent DM game context injection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_agent(runtime=None, callsign="Lynx"):
    """Create a CognitiveAgent with minimal runtime for game context tests."""
    from probos.cognitive.cognitive_agent import CognitiveAgent

    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent._runtime = runtime
    agent.agent_type = "science_officer"
    agent.id = "test-agent"
    agent._model_id = "test"
    agent._system_prompt_base = ""
    agent._max_tokens = 1000
    agent._callsign = callsign
    # _resolve_callsign() checks self.callsign first
    agent.callsign = callsign
    return agent


class TestHasActiveGame:
    """CognitiveAgent._has_active_game() lightweight check."""

    def test_false_when_no_runtime(self):
        agent = _make_agent(runtime=None)
        assert agent._has_active_game() is False

    def test_false_when_no_recreation_service(self):
        rt = MagicMock(spec=[])
        agent = _make_agent(runtime=rt)
        assert agent._has_active_game() is False

    def test_false_when_no_game(self):
        rt = MagicMock()
        rt.recreation_service = MagicMock()
        rt.recreation_service.get_game_by_player.return_value = None
        rt.callsign_registry.get_callsign.return_value = "Lynx"
        agent = _make_agent(runtime=rt)
        assert agent._has_active_game() is False

    def test_true_when_game_exists(self):
        rt = MagicMock()
        rt.recreation_service = MagicMock()
        rt.recreation_service.get_game_by_player.return_value = {"game_id": "g-1"}
        rt.callsign_registry.get_callsign.return_value = "Lynx"
        agent = _make_agent(runtime=rt)
        assert agent._has_active_game() is True

    def test_false_when_no_callsign(self):
        rt = MagicMock(spec=['recreation_service'])
        rt.recreation_service = MagicMock()
        agent = _make_agent(runtime=rt, callsign="")
        assert agent._has_active_game() is False


class TestBuildActiveGameContext:
    """CognitiveAgent._build_active_game_context() board formatting."""

    def test_returns_none_when_no_game(self):
        rt = MagicMock()
        rt.recreation_service = MagicMock()
        rt.recreation_service.get_game_by_player.return_value = None
        rt.callsign_registry.get_callsign.return_value = "Lynx"
        agent = _make_agent(runtime=rt)
        assert agent._build_active_game_context() is None

    def test_returns_formatted_context(self):
        game = {
            "game_id": "g-123",
            "game_type": "tictactoe",
            "challenger": "Captain",
            "opponent": "Lynx",
            "state": {
                "board": ["X", "", "", "", "O", "", "", "", ""],
                "current_player": "Lynx",
                "status": "in_progress",
            },
            "moves_count": 2,
        }
        rt = MagicMock()
        rt.recreation_service = MagicMock()
        rt.recreation_service.get_game_by_player.return_value = game
        rt.recreation_service.render_board.return_value = " X |   |  \n---+---+---\n   | O |  \n---+---+---\n   |   |  "
        rt.recreation_service.get_valid_moves.return_value = ["1", "2", "3", "5", "6", "7", "8"]
        rt.callsign_registry.get_callsign.return_value = "Lynx"
        agent = _make_agent(runtime=rt)

        ctx = agent._build_active_game_context()
        assert ctx is not None
        assert "YOUR turn" in ctx
        assert "tictactoe" in ctx
        assert "Captain" in ctx  # opponent from Lynx's perspective

    def test_returns_none_when_no_runtime(self):
        agent = _make_agent(runtime=None)
        assert agent._build_active_game_context() is None
