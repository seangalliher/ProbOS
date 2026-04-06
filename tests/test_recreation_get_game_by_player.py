"""AD-572: Tests for RecreationService.get_game_by_player() DRY method."""

from __future__ import annotations

import pytest

from probos.recreation.service import RecreationService


@pytest.fixture
def service():
    """RecreationService with no dependencies."""
    return RecreationService()


class TestGetGameByPlayer:
    """RecreationService.get_game_by_player() DRY method."""

    @pytest.mark.asyncio
    async def test_finds_challenger(self, service: RecreationService):
        """get_game_by_player() finds game where callsign is challenger."""
        game = await service.create_game("tictactoe", "Captain", "Lynx")
        result = service.get_game_by_player("Captain")
        assert result is not None
        assert result["game_id"] == game["game_id"]

    @pytest.mark.asyncio
    async def test_finds_opponent(self, service: RecreationService):
        """get_game_by_player() finds game where callsign is opponent."""
        game = await service.create_game("tictactoe", "Captain", "Lynx")
        result = service.get_game_by_player("Lynx")
        assert result is not None
        assert result["game_id"] == game["game_id"]

    @pytest.mark.asyncio
    async def test_returns_none_when_not_playing(self, service: RecreationService):
        """get_game_by_player() returns None for non-participant."""
        await service.create_game("tictactoe", "Captain", "Lynx")
        assert service.get_game_by_player("Atlas") is None

    def test_returns_none_when_no_games(self, service: RecreationService):
        """get_game_by_player() returns None when no active games."""
        assert service.get_game_by_player("Captain") is None
