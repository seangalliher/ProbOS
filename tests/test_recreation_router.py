"""Tests for AD-526b: Recreation API router + GAME_UPDATE + forfeit."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.events import EventType
from probos.recreation.service import RecreationService


# ── EventType ────────────────────────────────────────────────────────

class TestGameUpdateEventType:
    """Verify GAME_UPDATE event type exists."""

    def test_game_update_event(self):
        assert hasattr(EventType, "GAME_UPDATE")
        assert EventType.GAME_UPDATE.value == "game_update"


# ── RecreationService.forfeit_game() ─────────────────────────────────

class TestForfeitMethod:
    """RecreationService.forfeit_game()"""

    @pytest.mark.asyncio
    async def test_forfeit_removes_from_active(self):
        """forfeit_game() removes game from active games."""
        svc = RecreationService()
        game = await svc.create_game("tictactoe", "Captain", "Lynx")
        game_id = game["game_id"]

        assert len(svc.get_active_games()) == 1
        await svc.forfeit_game(game_id, "Captain")
        assert len(svc.get_active_games()) == 0

    @pytest.mark.asyncio
    async def test_forfeit_cleans_thread_mapping(self):
        """forfeit_game() removes thread -> game mapping."""
        svc = RecreationService()
        game = await svc.create_game("tictactoe", "Captain", "Lynx", thread_id="t-123")
        game_id = game["game_id"]

        assert svc.get_game_by_thread("t-123") is not None
        await svc.forfeit_game(game_id, "Captain")
        assert svc.get_game_by_thread("t-123") is None

    @pytest.mark.asyncio
    async def test_forfeit_nonexistent_is_noop(self):
        """forfeit_game() does nothing for unknown game IDs."""
        svc = RecreationService()
        await svc.forfeit_game("nonexistent", "Captain")  # should not raise

    @pytest.mark.asyncio
    async def test_forfeit_emits_game_update(self):
        """forfeit_game() emits GAME_UPDATE event."""
        emit_fn = MagicMock()
        svc = RecreationService(emit_event_fn=emit_fn)
        game = await svc.create_game("tictactoe", "Captain", "Lynx")
        game_id = game["game_id"]

        await svc.forfeit_game(game_id, "Captain")
        assert emit_fn.called
        call_args = emit_fn.call_args[0]
        assert call_args[0] == EventType.GAME_UPDATE
        assert call_args[1]["status"] == "forfeited"
        assert call_args[1]["game_id"] == game_id


# ── GAME_UPDATE emission on moves ───────────────────────────────────

class TestGameUpdateEmission:
    """RecreationService emits GAME_UPDATE on moves."""

    @pytest.mark.asyncio
    async def test_move_emits_game_update(self):
        """make_move() emits GAME_UPDATE event with correct board state."""
        emit_fn = MagicMock()
        svc = RecreationService(emit_event_fn=emit_fn)
        game = await svc.create_game("tictactoe", "Captain", "Lynx")
        game_id = game["game_id"]

        await svc.make_move(game_id, "Captain", "4")

        assert emit_fn.called
        call_args = emit_fn.call_args[0]
        assert call_args[0] == EventType.GAME_UPDATE
        event_data = call_args[1]
        assert event_data["game_id"] == game_id
        assert event_data["board"][4] == "X"
        assert event_data["current_player"] == "Lynx"
        assert event_data["status"] == "in_progress"
        assert event_data["last_move"]["player"] == "Captain"
        assert event_data["last_move"]["position"] == "4"

    @pytest.mark.asyncio
    async def test_winning_move_emits_game_update_and_completed(self):
        """Winning move emits both GAME_UPDATE and GAME_COMPLETED."""
        emit_fn = MagicMock()
        svc = RecreationService(emit_event_fn=emit_fn)
        game = await svc.create_game("tictactoe", "Captain", "Lynx")
        gid = game["game_id"]

        # X plays 0,1,2 with O at 3,4
        await svc.make_move(gid, "Captain", "0")
        await svc.make_move(gid, "Lynx", "3")
        await svc.make_move(gid, "Captain", "1")
        await svc.make_move(gid, "Lynx", "4")
        await svc.make_move(gid, "Captain", "2")  # wins top row

        # Should have emitted GAME_UPDATE for each move + GAME_COMPLETED at end
        event_types = [call[0][0] for call in emit_fn.call_args_list]
        assert EventType.GAME_UPDATE in event_types
        assert EventType.GAME_COMPLETED in event_types


# ── Router endpoint validation ──────────────────────────────────────

class TestRecreationRouter:
    """Test recreation router endpoint logic via direct function calls."""

    @pytest.mark.asyncio
    async def test_challenge_endpoint_creates_game(self):
        """challenge_agent() creates game and returns state."""
        from probos.routers.recreation import challenge_agent

        runtime = MagicMock()
        agent = MagicMock()
        agent.id = "test-id"
        agent.agent_type = "science_officer"
        runtime.registry.all.return_value = [agent]
        runtime.callsign_registry.get_callsign.return_value = "Lynx"
        runtime.ward_room = AsyncMock()
        runtime.ward_room.list_channels.return_value = []
        runtime.recreation_service = MagicMock()
        runtime.recreation_service.create_game = AsyncMock(return_value={
            "game_id": "game-1",
            "state": {"board": [""] * 9, "current_player": "Captain", "status": "in_progress"},
        })
        runtime.recreation_service.get_valid_moves.return_value = [str(i) for i in range(9)]

        broadcast = MagicMock()
        body = {"opponent_agent_id": "test-id", "game_type": "tictactoe"}

        result = await challenge_agent(body, runtime, broadcast)
        assert result["game_id"] == "game-1"
        assert result["board"] == [""] * 9
        assert result["opponent"] == "Lynx"
        assert broadcast.called

    @pytest.mark.asyncio
    async def test_challenge_rejects_unknown_agent(self):
        """challenge_agent() returns 404 for unknown agent."""
        from fastapi import HTTPException
        from probos.routers.recreation import challenge_agent

        runtime = MagicMock()
        runtime.registry.all.return_value = []
        runtime.recreation_service = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await challenge_agent({"opponent_agent_id": "nope"}, runtime, MagicMock())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_challenge_rejects_non_crew(self):
        """challenge_agent() returns 400 for non-crew agents."""
        from fastapi import HTTPException
        from probos.routers.recreation import challenge_agent

        runtime = MagicMock()
        agent = MagicMock()
        agent.id = "infra-id"
        agent.agent_type = "vitals_monitor"
        runtime.registry.all.return_value = [agent]
        runtime.callsign_registry.get_callsign.return_value = ""
        runtime.recreation_service = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await challenge_agent({"opponent_agent_id": "infra-id"}, runtime, MagicMock())
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_challenge_no_service(self):
        """challenge_agent() returns 503 when service not available."""
        from fastapi import HTTPException
        from probos.routers.recreation import challenge_agent

        runtime = MagicMock(spec=[])

        with pytest.raises(HTTPException) as exc_info:
            await challenge_agent({"opponent_agent_id": "x"}, runtime, MagicMock())
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_move_endpoint_success(self):
        """make_move() returns updated board state."""
        from probos.routers.recreation import make_move

        runtime = MagicMock()
        runtime.recreation_service = MagicMock()
        runtime.recreation_service.make_move = AsyncMock(return_value={
            "state": {"board": ["X", "", "", "", "", "", "", "", ""],
                      "current_player": "Lynx", "status": "in_progress"},
            "thread_id": "",
            "moves_count": 1,
        })
        runtime.recreation_service.get_valid_moves.return_value = [str(i) for i in range(1, 9)]
        runtime.ward_room = None

        result = await make_move({"game_id": "g-1", "position": "0"}, runtime, MagicMock())
        assert result["board"][0] == "X"
        assert result["current_player"] == "Lynx"
        assert result["moves_count"] == 1

    @pytest.mark.asyncio
    async def test_move_rejects_invalid(self):
        """make_move() returns 400 for invalid moves."""
        from fastapi import HTTPException
        from probos.routers.recreation import make_move

        runtime = MagicMock()
        runtime.recreation_service = MagicMock()
        runtime.recreation_service.make_move = AsyncMock(side_effect=ValueError("Not your turn"))

        with pytest.raises(HTTPException) as exc_info:
            await make_move({"game_id": "g-1", "position": "0"}, runtime, MagicMock())
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_active_returns_captain_game(self):
        """get_active_game() returns Captain's active game."""
        from probos.routers.recreation import get_active_game

        runtime = MagicMock()
        runtime.recreation_service = MagicMock()
        runtime.recreation_service.get_active_games.return_value = [{
            "game_id": "g-1",
            "challenger": "Captain",
            "opponent": "Lynx",
            "state": {"board": ["X", "O", "", "", "", "", "", "", ""],
                      "current_player": "Captain", "status": "in_progress"},
            "game_type": "tictactoe",
            "moves_count": 2,
        }]
        runtime.recreation_service.get_valid_moves.return_value = [str(i) for i in range(2, 9)]

        result = await get_active_game(runtime)
        assert result["game"] is not None
        assert result["game"]["game_id"] == "g-1"
        assert result["game"]["opponent"] == "Lynx"

    @pytest.mark.asyncio
    async def test_active_returns_null_when_no_game(self):
        """get_active_game() returns null when no active game."""
        from probos.routers.recreation import get_active_game

        runtime = MagicMock()
        runtime.recreation_service = MagicMock()
        runtime.recreation_service.get_active_games.return_value = []

        result = await get_active_game(runtime)
        assert result["game"] is None

    @pytest.mark.asyncio
    async def test_forfeit_endpoint(self):
        """forfeit_game() calls service and broadcasts event."""
        from probos.routers.recreation import forfeit_game

        runtime = MagicMock()
        runtime.recreation_service = MagicMock()
        runtime.recreation_service.forfeit_game = AsyncMock()
        broadcast = MagicMock()

        result = await forfeit_game({"game_id": "g-1"}, runtime, broadcast)
        assert result["status"] == "forfeited"
        runtime.recreation_service.forfeit_game.assert_called_once_with("g-1", "Captain")
        assert broadcast.called
