"""Recreation service — game lifecycle management (AD-526a)."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from probos.recreation.engine import GameEngine, TicTacToeEngine

logger = logging.getLogger(__name__)


class RecreationService:
    """Manages active games, validates moves, and records results.

    Games flow through Ward Room threads:
    1. Challenger posts [CHALLENGE @target game_type] -> RecreationService creates game
    2. Target sees challenge in Recreation channel -> accepts by replying
    3. Each move is a reply in the game thread with [MOVE position]
    4. RecreationService validates moves, posts updated board
    5. On game end, posts result and writes to Ship's Records
    """

    def __init__(
        self,
        ward_room: Any = None,
        records_store: Any = None,
        emit_event_fn: Any = None,
    ):
        self._ward_room = ward_room
        self._records_store = records_store
        self._emit = emit_event_fn
        # Registered game engines by type
        self._engines: dict[str, GameEngine] = {}
        # Active games by game_id
        self._active_games: dict[str, dict[str, Any]] = {}
        # Map thread_id -> game_id for move routing
        self._thread_games: dict[str, str] = {}

        # Register default engines
        self.register_engine(TicTacToeEngine())

    def register_engine(self, engine: GameEngine) -> None:
        """Register a game engine by its game_type."""
        self._engines[engine.game_type] = engine

    def get_available_games(self) -> list[str]:
        """Return list of registered game type names."""
        return list(self._engines.keys())

    async def create_game(
        self,
        game_type: str,
        challenger: str,
        opponent: str,
        thread_id: str = "",
    ) -> dict[str, Any]:
        """Create a new game. Returns game info dict.

        Args:
            game_type: Type of game (must be registered).
            challenger: Callsign of the challenging player.
            opponent: Callsign of the opponent.
            thread_id: Ward Room thread ID where the game lives.

        Returns:
            Dict with game_id, game_type, state, thread_id.

        Raises:
            ValueError: If game_type is not registered.
        """
        engine = self._engines.get(game_type)
        if not engine:
            raise ValueError(
                f"Unknown game type '{game_type}'. "
                f"Available: {', '.join(self._engines.keys())}"
            )

        game_id = f"game-{uuid.uuid4().hex[:12]}"
        state = engine.new_game(challenger, opponent)

        game_info = {
            "game_id": game_id,
            "game_type": game_type,
            "state": state,
            "thread_id": thread_id,
            "challenger": challenger,
            "opponent": opponent,
            "created_at": time.time(),
            "moves_count": 0,
        }

        self._active_games[game_id] = game_info
        if thread_id:
            self._thread_games[thread_id] = game_id

        return game_info

    async def make_move(
        self, game_id: str, player: str, move: str,
    ) -> dict[str, Any]:
        """Apply a move to an active game.

        Args:
            game_id: The game to play in.
            player: Callsign of the player making the move.
            move: The move string (game-type specific).

        Returns:
            Updated game info dict.

        Raises:
            ValueError: If game not found, invalid move, or wrong player.
        """
        game_info = self._active_games.get(game_id)
        if not game_info:
            raise ValueError(f"Game {game_id} not found")

        engine = self._engines[game_info["game_type"]]
        new_state = engine.make_move(game_info["state"], player, move)

        game_info["state"] = new_state
        game_info["moves_count"] += 1

        # AD-526b: Emit game state update for HXI WebSocket
        if self._emit:
            try:
                from probos.events import EventType
                self._emit(EventType.GAME_UPDATE, {
                    "game_id": game_id,
                    "board": new_state["board"],
                    "current_player": new_state.get("current_player", ""),
                    "status": new_state["status"],
                    "winner": new_state.get("winner", ""),
                    "valid_moves": engine.get_valid_moves(new_state) if new_state["status"] == "in_progress" else [],
                    "moves_count": game_info["moves_count"],
                    "last_move": {"player": player, "position": move},
                    "thread_id": game_info.get("thread_id", ""),
                })
            except Exception:
                pass

        # Check if game is finished
        if engine.is_finished(new_state):
            result = engine.get_result(new_state)
            game_info["result"] = result
            game_info["finished_at"] = time.time()

            # Write game record to Ship's Records
            await self._record_game(game_info, engine)

            # Emit event for Hebbian bond strengthening
            if self._emit:
                try:
                    from probos.events import EventType
                    self._emit(EventType.GAME_COMPLETED, {
                        "game_id": game_id,
                        "game_type": game_info["game_type"],
                        "players": [game_info["challenger"], game_info["opponent"]],
                        "result": result,
                        "moves_count": game_info["moves_count"],
                    })
                except Exception:
                    logger.debug("AD-526a: GAME_COMPLETED event emission failed", exc_info=True)

            # Clean up
            thread_id = game_info.get("thread_id")
            if thread_id and thread_id in self._thread_games:
                del self._thread_games[thread_id]
            del self._active_games[game_id]

        return game_info

    def get_game_by_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Look up active game by Ward Room thread ID."""
        game_id = self._thread_games.get(thread_id)
        if game_id:
            return self._active_games.get(game_id)
        return None

    def get_active_games(self) -> list[dict[str, Any]]:
        """Return all active games."""
        return list(self._active_games.values())

    def render_board(self, game_id: str) -> str:
        """Render the current board for a game."""
        game_info = self._active_games.get(game_id)
        if not game_info:
            return ""
        engine = self._engines[game_info["game_type"]]
        return engine.render_board(game_info["state"])

    def get_valid_moves(self, game_id: str) -> list[str]:
        """Get valid moves for the current player."""
        game_info = self._active_games.get(game_id)
        if not game_info:
            return []
        engine = self._engines[game_info["game_type"]]
        return engine.get_valid_moves(game_info["state"])

    async def forfeit_game(self, game_id: str, player: str) -> None:
        """Forfeit/abandon an active game."""
        game_info = self._active_games.get(game_id)
        if not game_info:
            return

        thread_id = game_info.get("thread_id", "")
        if thread_id and thread_id in self._thread_games:
            del self._thread_games[thread_id]
        del self._active_games[game_id]

        if self._emit:
            try:
                from probos.events import EventType
                self._emit(EventType.GAME_UPDATE, {
                    "game_id": game_id,
                    "status": "forfeited",
                    "board": [],
                    "current_player": "",
                    "winner": "",
                    "valid_moves": [],
                    "moves_count": 0,
                })
            except Exception:
                pass

    async def _record_game(
        self, game_info: dict[str, Any], engine: GameEngine,
    ) -> None:
        """Write completed game record to Ship's Records."""
        if not self._records_store:
            return

        result = game_info.get("result", {})
        board_final = engine.render_board(game_info["state"])
        duration = game_info.get("finished_at", 0) - game_info.get("created_at", 0)

        content = (
            f"# Game Record: {game_info['game_type'].title()}\n\n"
            f"**Players:** {game_info['challenger']} (X) vs {game_info['opponent']} (O)\n"
            f"**Result:** {result.get('status', 'unknown')}"
        )
        if result.get("winner"):
            content += f" — **{result['winner']}** wins!\n"
        else:
            content += "\n"
        content += (
            f"**Moves:** {game_info['moves_count']}\n"
            f"**Duration:** {duration:.0f}s\n\n"
            f"## Final Board\n\n```\n{board_final}\n```\n\n"
            f"## Move History\n\n"
        )
        for i, (player, pos) in enumerate(game_info["state"].get("moves", []), 1):
            content += f"{i}. {player} -> {pos}\n"

        try:
            path = f"recreation/games/{game_info['game_type']}/{game_info['game_id']}.md"
            await self._records_store.write_entry(
                author="system",
                path=path,
                content=content,
                message=f"AD-526a: Game record {game_info['game_id']}",
                classification="ship",
                tags=["game", game_info["game_type"]],
            )
        except Exception:
            logger.debug("AD-526a: Failed to record game to Ship's Records", exc_info=True)
