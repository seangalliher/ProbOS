"""AD-526a: RecreationService tests — game lifecycle, thread routing, event emission."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from probos.recreation.engine import TicTacToeEngine
from probos.recreation.service import RecreationService


@pytest.fixture
def service():
    """RecreationService with mocked dependencies."""
    return RecreationService(
        ward_room=MagicMock(),
        records_store=AsyncMock(),
        emit_event_fn=MagicMock(),
    )


@pytest.fixture
def bare_service():
    """RecreationService with no dependencies."""
    return RecreationService()


class TestGameRegistration:
    """Verify engine registration."""

    def test_default_engine_registered(self, service):
        assert "tictactoe" in service.get_available_games()

    def test_register_custom_engine(self, service):
        mock_engine = MagicMock()
        mock_engine.game_type = "chess"
        service.register_engine(mock_engine)
        assert "chess" in service.get_available_games()


class TestCreateGame:
    """Verify game creation."""

    @pytest.mark.asyncio
    async def test_create_game_basic(self, service):
        game = await service.create_game("tictactoe", "alice", "bob")
        assert game["game_id"].startswith("game-")
        assert game["game_type"] == "tictactoe"
        assert game["challenger"] == "alice"
        assert game["opponent"] == "bob"
        assert game["moves_count"] == 0

    @pytest.mark.asyncio
    async def test_create_game_with_thread(self, service):
        game = await service.create_game("tictactoe", "alice", "bob", thread_id="th-123")
        assert game["thread_id"] == "th-123"
        assert service.get_game_by_thread("th-123") is not None

    @pytest.mark.asyncio
    async def test_create_game_unknown_type(self, service):
        with pytest.raises(ValueError, match="Unknown game type"):
            await service.create_game("chess", "alice", "bob")

    @pytest.mark.asyncio
    async def test_active_games_tracked(self, service):
        await service.create_game("tictactoe", "alice", "bob")
        assert len(service.get_active_games()) == 1


class TestMakeMove:
    """Verify move execution and game completion."""

    @pytest.mark.asyncio
    async def test_make_move(self, service):
        game = await service.create_game("tictactoe", "alice", "bob")
        updated = await service.make_move(game["game_id"], "alice", "4")
        assert updated["moves_count"] == 1
        assert updated["state"]["board"][4] == "X"

    @pytest.mark.asyncio
    async def test_game_not_found(self, service):
        with pytest.raises(ValueError, match="not found"):
            await service.make_move("nonexistent", "alice", "0")

    @pytest.mark.asyncio
    async def test_game_completion_cleanup(self, service):
        game = await service.create_game("tictactoe", "a", "b")
        gid = game["game_id"]
        # Play to win: a=0,1,2  b=3,4
        await service.make_move(gid, "a", "0")
        await service.make_move(gid, "b", "3")
        await service.make_move(gid, "a", "1")
        await service.make_move(gid, "b", "4")
        result = await service.make_move(gid, "a", "2")
        assert result["result"]["status"] == "won"
        assert result["result"]["winner"] == "a"
        # Game removed from active
        assert len(service.get_active_games()) == 0

    @pytest.mark.asyncio
    async def test_game_completion_emits_event(self, service):
        game = await service.create_game("tictactoe", "a", "b")
        gid = game["game_id"]
        await service.make_move(gid, "a", "0")
        await service.make_move(gid, "b", "3")
        await service.make_move(gid, "a", "1")
        await service.make_move(gid, "b", "4")
        await service.make_move(gid, "a", "2")
        # AD-526b: now emits GAME_UPDATE per move + GAME_COMPLETED at end
        from probos.events import EventType
        completed_calls = [c for c in service._emit.call_args_list
                           if len(c[0]) >= 1 and c[0][0] == EventType.GAME_COMPLETED]
        assert len(completed_calls) == 1
        assert completed_calls[0][0][1]["game_type"] == "tictactoe"
        assert completed_calls[0][0][1]["result"]["winner"] == "a"

    @pytest.mark.asyncio
    async def test_game_completion_records(self, service):
        game = await service.create_game("tictactoe", "a", "b")
        gid = game["game_id"]
        await service.make_move(gid, "a", "0")
        await service.make_move(gid, "b", "3")
        await service.make_move(gid, "a", "1")
        await service.make_move(gid, "b", "4")
        await service.make_move(gid, "a", "2")
        service._records_store.write_entry.assert_awaited_once()
        call_kwargs = service._records_store.write_entry.call_args[1]
        assert "recreation/games/tictactoe/" in call_kwargs["path"]
        assert "Game Record" in call_kwargs["content"]


class TestThreadRouting:
    """Verify thread-to-game mapping."""

    @pytest.mark.asyncio
    async def test_get_game_by_thread(self, service):
        game = await service.create_game("tictactoe", "a", "b", thread_id="th-1")
        found = service.get_game_by_thread("th-1")
        assert found["game_id"] == game["game_id"]

    @pytest.mark.asyncio
    async def test_get_game_by_unknown_thread(self, service):
        assert service.get_game_by_thread("unknown") is None


class TestBoardRendering:
    """Verify board and valid moves access."""

    @pytest.mark.asyncio
    async def test_render_board(self, service):
        game = await service.create_game("tictactoe", "a", "b")
        board = service.render_board(game["game_id"])
        assert "---+---+---" in board

    def test_render_board_unknown_game(self, service):
        assert service.render_board("nonexistent") == ""

    @pytest.mark.asyncio
    async def test_get_valid_moves(self, service):
        game = await service.create_game("tictactoe", "a", "b")
        moves = service.get_valid_moves(game["game_id"])
        assert len(moves) == 9

    def test_get_valid_moves_unknown_game(self, service):
        assert service.get_valid_moves("nonexistent") == []


class TestNoDependencies:
    """Verify service works without optional dependencies."""

    @pytest.mark.asyncio
    async def test_no_emit_fn(self, bare_service):
        game = await bare_service.create_game("tictactoe", "a", "b")
        gid = game["game_id"]
        await bare_service.make_move(gid, "a", "0")
        await bare_service.make_move(gid, "b", "3")
        await bare_service.make_move(gid, "a", "1")
        await bare_service.make_move(gid, "b", "4")
        result = await bare_service.make_move(gid, "a", "2")
        assert result["result"]["status"] == "won"

    @pytest.mark.asyncio
    async def test_no_records_store(self, bare_service):
        game = await bare_service.create_game("tictactoe", "a", "b")
        gid = game["game_id"]
        await bare_service.make_move(gid, "a", "0")
        await bare_service.make_move(gid, "b", "3")
        await bare_service.make_move(gid, "a", "1")
        await bare_service.make_move(gid, "b", "4")
        # Should not raise even without records store
        await bare_service.make_move(gid, "a", "2")
