"""AD-526a: Recreation channel + proactive integration tests."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.events import EventType
from probos.recreation.service import RecreationService


class TestEventType:
    """Verify GAME_COMPLETED event type exists."""

    def test_game_completed_event(self):
        assert hasattr(EventType, "GAME_COMPLETED")
        assert EventType.GAME_COMPLETED.value == "game_completed"


class TestChallengePattern:
    """Verify CHALLENGE regex extraction."""

    def test_challenge_pattern_match(self):
        pattern = r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]'
        text = "I challenge you! [CHALLENGE @bones tictactoe]"
        match = re.search(pattern, text)
        assert match
        assert match.group(1) == "bones"
        assert match.group(2) == "tictactoe"

    def test_challenge_pattern_strip(self):
        pattern = r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]'
        text = "I challenge you! [CHALLENGE @bones tictactoe] Let's go!"
        cleaned = re.sub(pattern, '', text).strip()
        assert "[CHALLENGE" not in cleaned
        assert "I challenge you!" in cleaned

    def test_multiple_challenges(self):
        pattern = r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]'
        text = "[CHALLENGE @bones tictactoe] [CHALLENGE @worf tictactoe]"
        matches = list(re.finditer(pattern, text))
        assert len(matches) == 2


class TestMovePattern:
    """Verify MOVE regex extraction."""

    def test_move_pattern_match(self):
        pattern = r'\[MOVE\s+(\S+)\]'
        text = "My turn! [MOVE 4]"
        match = re.search(pattern, text)
        assert match
        assert match.group(1) == "4"

    def test_move_pattern_strip(self):
        pattern = r'\[MOVE\s+(\S+)\]'
        text = "Playing center. [MOVE 4] Good game so far."
        cleaned = re.sub(pattern, '', text).strip()
        assert "[MOVE" not in cleaned


class TestRecreationServiceIntegration:
    """Integration tests for RecreationService game flow."""

    @pytest.mark.asyncio
    async def test_full_game_flow(self):
        """Play a complete game and verify lifecycle."""
        svc = RecreationService()
        game = await svc.create_game("tictactoe", "echo", "bones")
        gid = game["game_id"]

        # echo (X) plays 0, 1, 2 — bones (O) plays 3, 4
        await svc.make_move(gid, "echo", "0")
        board = svc.render_board(gid)
        assert "X" in board

        await svc.make_move(gid, "bones", "3")
        await svc.make_move(gid, "echo", "1")
        await svc.make_move(gid, "bones", "4")

        # Valid moves should be 5,6,7,8 before final move
        moves = svc.get_valid_moves(gid)
        assert "2" in moves

        result = await svc.make_move(gid, "echo", "2")
        assert result["result"]["status"] == "won"
        assert result["result"]["winner"] == "echo"
        assert len(svc.get_active_games()) == 0

    @pytest.mark.asyncio
    async def test_draw_game(self):
        """Play to a draw."""
        svc = RecreationService()
        game = await svc.create_game("tictactoe", "a", "b")
        gid = game["game_id"]
        # Board: X O X / X O O / O X X — no winner, alternating a,b
        for pos, player in [(0, "a"), (4, "b"), (2, "a"),
                             (1, "b"), (3, "a"), (6, "b"),
                             (8, "a"), (5, "b"), (7, "a")]:
            await svc.make_move(gid, player, str(pos))
        assert len(svc.get_active_games()) == 0
