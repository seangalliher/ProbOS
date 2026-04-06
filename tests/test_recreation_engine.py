"""AD-526a: TicTacToeEngine tests — game logic, win/draw detection, move validation."""

from __future__ import annotations

import pytest

from probos.recreation.engine import GameEngine, TicTacToeEngine


class TestTicTacToeEngineProtocol:
    """Verify TicTacToeEngine satisfies GameEngine protocol."""

    def test_implements_protocol(self):
        engine = TicTacToeEngine()
        assert isinstance(engine, GameEngine)

    def test_game_type(self):
        engine = TicTacToeEngine()
        assert engine.game_type == "tictactoe"


class TestNewGame:
    """Verify initial game state."""

    def test_new_game_state(self):
        engine = TicTacToeEngine()
        state = engine.new_game("alice", "bob")
        assert state["board"] == [""] * 9
        assert state["current_player"] == "alice"
        assert state["player_a"] == "alice"
        assert state["player_b"] == "bob"
        assert state["symbols"] == {"alice": "X", "bob": "O"}
        assert state["status"] == "in_progress"
        assert state["winner"] == ""
        assert state["moves"] == []

    def test_new_game_not_finished(self):
        engine = TicTacToeEngine()
        state = engine.new_game("alice", "bob")
        assert not engine.is_finished(state)

    def test_valid_moves_all_positions(self):
        engine = TicTacToeEngine()
        state = engine.new_game("alice", "bob")
        assert engine.get_valid_moves(state) == [str(i) for i in range(9)]


class TestMakeMoves:
    """Verify move application and turn switching."""

    def test_valid_move(self):
        engine = TicTacToeEngine()
        state = engine.new_game("alice", "bob")
        state = engine.make_move(state, "alice", "4")
        assert state["board"][4] == "X"
        assert state["current_player"] == "bob"
        assert state["moves"] == [("alice", 4)]

    def test_turn_alternation(self):
        engine = TicTacToeEngine()
        state = engine.new_game("alice", "bob")
        state = engine.make_move(state, "alice", "0")
        state = engine.make_move(state, "bob", "4")
        assert state["board"][0] == "X"
        assert state["board"][4] == "O"
        assert state["current_player"] == "alice"

    def test_wrong_player_rejected(self):
        engine = TicTacToeEngine()
        state = engine.new_game("alice", "bob")
        with pytest.raises(ValueError, match="Not bob's turn"):
            engine.make_move(state, "bob", "0")

    def test_occupied_position_rejected(self):
        engine = TicTacToeEngine()
        state = engine.new_game("alice", "bob")
        state = engine.make_move(state, "alice", "4")
        with pytest.raises(ValueError, match="already occupied"):
            engine.make_move(state, "bob", "4")

    def test_invalid_move_string(self):
        engine = TicTacToeEngine()
        state = engine.new_game("alice", "bob")
        with pytest.raises(ValueError, match="Invalid move"):
            engine.make_move(state, "alice", "xyz")

    def test_out_of_range_move(self):
        engine = TicTacToeEngine()
        state = engine.new_game("alice", "bob")
        with pytest.raises(ValueError, match="out of range"):
            engine.make_move(state, "alice", "9")

    def test_move_after_game_over(self):
        engine = TicTacToeEngine()
        state = engine.new_game("alice", "bob")
        # alice wins: 0,1,2
        state = engine.make_move(state, "alice", "0")
        state = engine.make_move(state, "bob", "3")
        state = engine.make_move(state, "alice", "1")
        state = engine.make_move(state, "bob", "4")
        state = engine.make_move(state, "alice", "2")  # win
        with pytest.raises(ValueError, match="already finished"):
            engine.make_move(state, "bob", "5")


class TestWinDetection:
    """Verify all win conditions."""

    @pytest.mark.parametrize("moves,winner", [
        # Rows
        ([(0, "a"), (3, "b"), (1, "a"), (4, "b"), (2, "a")], "a"),
        ([(0, "a"), (3, "b"), (1, "a"), (4, "b"), (8, "a"), (5, "b")], "b"),
        # Column
        ([(0, "a"), (1, "b"), (3, "a"), (4, "b"), (6, "a")], "a"),
        # Diagonals
        ([(0, "a"), (1, "b"), (4, "a"), (2, "b"), (8, "a")], "a"),
        ([(2, "a"), (0, "b"), (4, "a"), (1, "b"), (6, "a")], "a"),
    ])
    def test_win_conditions(self, moves, winner):
        engine = TicTacToeEngine()
        state = engine.new_game("a", "b")
        for pos, player in moves:
            state = engine.make_move(state, player, str(pos))
        assert engine.is_finished(state)
        result = engine.get_result(state)
        assert result["status"] == "won"
        assert result["winner"] == winner

    def test_draw(self):
        engine = TicTacToeEngine()
        state = engine.new_game("a", "b")
        # a=X, b=O. Alternating: a,b,a,b,a,b,a,b,a (9 moves)
        # Board: X O X / X O O / O X X — no winner
        for pos, player in [(0, "a"), (4, "b"), (2, "a"),
                             (1, "b"), (3, "a"), (6, "b"),
                             (8, "a"), (5, "b"), (7, "a")]:
            state = engine.make_move(state, player, str(pos))
        assert engine.is_finished(state)
        result = engine.get_result(state)
        assert result["status"] == "draw"
        assert result["winner"] == ""


class TestRenderBoard:
    """Verify board rendering."""

    def test_empty_board(self):
        engine = TicTacToeEngine()
        state = engine.new_game("a", "b")
        rendered = engine.render_board(state)
        assert "0" in rendered
        assert "8" in rendered
        assert "---+---+---" in rendered

    def test_partial_board(self):
        engine = TicTacToeEngine()
        state = engine.new_game("a", "b")
        state = engine.make_move(state, "a", "4")
        rendered = engine.render_board(state)
        assert "X" in rendered
        assert "4" not in rendered  # Position 4 now occupied
