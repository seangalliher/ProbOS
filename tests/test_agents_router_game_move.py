"""AD-572: Tests for agents router [MOVE] parsing in DM path."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.routers.agents import agent_chat


def _make_runtime(
    response_text: str = "I'll play center [MOVE 4]",
    has_game: bool = True,
    callsign: str = "Lynx",
):
    """Build a mock runtime for agent_chat() tests."""
    runtime = MagicMock()

    # Registry
    agent = MagicMock()
    agent.id = "test-id"
    agent.agent_type = "science_officer"
    agent.confidence = 0.7
    runtime.registry.get.return_value = agent

    # Callsign
    runtime.callsign_registry.get_callsign.return_value = callsign

    # Intent bus
    intent_result = MagicMock()
    intent_result.result = response_text
    intent_result.error = None
    runtime.intent_bus.send = AsyncMock(return_value=intent_result)

    # Recreation service
    if has_game:
        game = {
            "game_id": "g-123",
            "challenger": "Captain",
            "opponent": callsign,
            "state": {"board": ["X", "", "", "", "", "", "", "", ""], "current_player": callsign, "status": "in_progress"},
            "thread_id": "t-456",
        }
        runtime.recreation_service = MagicMock()
        runtime.recreation_service.get_game_by_player.return_value = game
        runtime.recreation_service.make_move = AsyncMock(return_value={
            "state": {"board": ["X", "", "", "", "O", "", "", "", ""], "current_player": "Captain", "status": "in_progress"},
        })
        runtime.recreation_service.render_board.return_value = "board"
    else:
        runtime.recreation_service = None

    # Ward Room — None so board posting is skipped
    runtime.ward_room = None

    # Episodic memory — disable
    runtime.episodic_memory = None

    return runtime


# Patch is_crew_agent to always return True for these tests
_CREW_PATCH = patch("probos.routers.agents.is_crew_agent", return_value=True)


class TestMoveParsing:
    """DM response [MOVE] tag parsing and execution."""

    @pytest.mark.asyncio
    async def test_move_tag_executes_game_move(self):
        """[MOVE 4] in response triggers make_move()."""
        runtime = _make_runtime(response_text="Let me play center [MOVE 4]")
        req = MagicMock()
        req.message = "Make your move"
        req.history = []

        with _CREW_PATCH:
            result = await agent_chat("test-id", req, runtime)

        runtime.recreation_service.make_move.assert_called_once()
        call_kwargs = runtime.recreation_service.make_move.call_args[1]
        assert call_kwargs["move"] == "4"
        assert result["gameMoveExecuted"] is True

    @pytest.mark.asyncio
    async def test_move_tag_stripped_from_response(self):
        """[MOVE] tag is removed from the response text shown to Captain."""
        runtime = _make_runtime(response_text="I'll play here [MOVE 4] for strategy")
        req = MagicMock()
        req.message = "Your move"
        req.history = []

        with _CREW_PATCH:
            result = await agent_chat("test-id", req, runtime)

        assert "[MOVE" not in result["response"]
        assert "I'll play here" in result["response"]
        assert "for strategy" in result["response"]

    @pytest.mark.asyncio
    async def test_no_move_tag_no_game_action(self):
        """Response without [MOVE] does not trigger game action."""
        runtime = _make_runtime(response_text="Just chatting, no moves here")
        req = MagicMock()
        req.message = "Hello"
        req.history = []

        with _CREW_PATCH:
            result = await agent_chat("test-id", req, runtime)

        runtime.recreation_service.make_move.assert_not_called()
        assert "gameMoveExecuted" not in result

    @pytest.mark.asyncio
    async def test_move_tag_no_recreation_service(self):
        """[MOVE] tag with no recreation service is gracefully ignored."""
        runtime = _make_runtime(response_text="[MOVE 4]", has_game=False)
        req = MagicMock()
        req.message = "Move"
        req.history = []

        with _CREW_PATCH:
            result = await agent_chat("test-id", req, runtime)

        assert "gameMoveExecuted" not in result

    @pytest.mark.asyncio
    async def test_move_tag_no_active_game(self):
        """[MOVE] tag when player has no active game is ignored."""
        runtime = _make_runtime(response_text="[MOVE 4]")
        runtime.recreation_service.get_game_by_player.return_value = None
        req = MagicMock()
        req.message = "Move"
        req.history = []

        with _CREW_PATCH:
            result = await agent_chat("test-id", req, runtime)

        runtime.recreation_service.make_move.assert_not_called()

    @pytest.mark.asyncio
    async def test_move_failure_logged_not_raised(self):
        """make_move() failure is logged, not raised to caller."""
        runtime = _make_runtime(response_text="[MOVE 4]")
        runtime.recreation_service.make_move = AsyncMock(side_effect=ValueError("Invalid move"))
        req = MagicMock()
        req.message = "Move"
        req.history = []

        with _CREW_PATCH:
            # Should not raise
            result = await agent_chat("test-id", req, runtime)
        assert "gameMoveExecuted" not in result
