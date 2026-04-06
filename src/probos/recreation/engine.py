"""Game engine protocol and implementations (AD-526a)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class GameEngine(Protocol):
    """Protocol that all game implementations must satisfy.

    Game state is opaque to the recreation service — only the engine
    knows how to interpret it. State must be serializable to dict for
    persistence in active game tracking.
    """

    @property
    def game_type(self) -> str:
        """Unique identifier for this game type (e.g., 'tictactoe', 'chess')."""
        ...

    def new_game(self, player_a: str, player_b: str) -> dict[str, Any]:
        """Create a new game. Returns initial game state dict.

        player_a goes first. State must include at minimum:
        - 'board': the board representation
        - 'current_player': callsign of whose turn it is
        - 'player_a': first player callsign
        - 'player_b': second player callsign
        - 'status': 'in_progress' | 'won' | 'draw'
        - 'winner': callsign of winner or '' if no winner yet
        """
        ...

    def make_move(self, state: dict[str, Any], player: str, move: str) -> dict[str, Any]:
        """Apply a move. Returns updated state. Raises ValueError if move is invalid."""
        ...

    def get_valid_moves(self, state: dict[str, Any]) -> list[str]:
        """Return list of valid move strings for the current player."""
        ...

    def render_board(self, state: dict[str, Any]) -> str:
        """Render the board as ASCII art for display in Ward Room posts."""
        ...

    def is_finished(self, state: dict[str, Any]) -> bool:
        """Check if the game is over (win or draw)."""
        ...

    def get_result(self, state: dict[str, Any]) -> dict[str, str]:
        """Return game result. Keys: 'status' ('won'|'draw'), 'winner' (callsign or '')."""
        ...


class TicTacToeEngine:
    """Tic-tac-toe — minimal game for framework validation (AD-526a)."""

    @property
    def game_type(self) -> str:
        return "tictactoe"

    def new_game(self, player_a: str, player_b: str) -> dict[str, Any]:
        return {
            "board": [""] * 9,  # 0-8, top-left to bottom-right
            "current_player": player_a,
            "player_a": player_a,
            "player_b": player_b,
            "symbols": {player_a: "X", player_b: "O"},
            "status": "in_progress",
            "winner": "",
            "moves": [],  # list of (player, position) tuples
        }

    def make_move(self, state: dict[str, Any], player: str, move: str) -> dict[str, Any]:
        if state["status"] != "in_progress":
            raise ValueError("Game is already finished")
        if player != state["current_player"]:
            raise ValueError(f"Not {player}'s turn")
        try:
            pos = int(move)
        except ValueError:
            raise ValueError(f"Invalid move '{move}' — must be 0-8")
        if pos < 0 or pos > 8:
            raise ValueError(f"Position {pos} out of range (0-8)")
        if state["board"][pos] != "":
            raise ValueError(f"Position {pos} is already occupied")

        # Apply move
        new_state = {**state, "board": list(state["board"])}
        new_state["board"][pos] = state["symbols"][player]
        new_state["moves"] = list(state["moves"]) + [(player, pos)]

        # Check win
        wins = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
        for a, b, c in wins:
            if (new_state["board"][a] == new_state["board"][b] == new_state["board"][c]
                    and new_state["board"][a] != ""):
                new_state["status"] = "won"
                new_state["winner"] = player
                return new_state

        # Check draw
        if "" not in new_state["board"]:
            new_state["status"] = "draw"
            new_state["winner"] = ""
            return new_state

        # Switch turn
        new_state["current_player"] = (
            state["player_b"] if player == state["player_a"] else state["player_a"]
        )
        return new_state

    def get_valid_moves(self, state: dict[str, Any]) -> list[str]:
        return [str(i) for i, cell in enumerate(state["board"]) if cell == ""]

    def render_board(self, state: dict[str, Any]) -> str:
        b = state["board"]

        def cell(i: int) -> str:
            return b[i] if b[i] else str(i)

        return (
            f" {cell(0)} | {cell(1)} | {cell(2)} \n"
            f"---+---+---\n"
            f" {cell(3)} | {cell(4)} | {cell(5)} \n"
            f"---+---+---\n"
            f" {cell(6)} | {cell(7)} | {cell(8)} "
        )

    def is_finished(self, state: dict[str, Any]) -> bool:
        return state["status"] != "in_progress"

    def get_result(self, state: dict[str, Any]) -> dict[str, str]:
        return {"status": state["status"], "winner": state["winner"]}
