"""Recreation service — game lifecycle management (AD-526a)."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from probos.recreation.engine import GameEngine, TicTacToeEngine
from probos.recreation.chess_engine import ChessEngine
from probos.recreation.turns import (
    UNVERSIONED,
    RecreationConflict,
    RecreationTurns,
    RecreationTurnSupport,
    RecreationTurnSupportFactory,
    canonical_text,
)

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
        dispatcher: Any | None = None,            # AD-654d
        callsign_registry: Any | None = None,     # AD-654d: for callsign → agent_id
        *,
        default_game: str = "tictactoe",          # AD-526c: Captain default
        clock: Callable[[], float] = time.monotonic,
        actor_exists: Callable[[str], bool] | None = None,
        turns_factory: RecreationTurnSupportFactory | None = None,
    ) -> None:
        self._ward_room = ward_room
        self._records_store = records_store
        self._emit = emit_event_fn
        self._dispatcher = dispatcher
        self._callsign_registry = callsign_registry
        # Registered game engines by type
        self._engines: dict[str, GameEngine] = {}
        # AD-526c: optional per-game metadata layered on top of _engines
        from probos.recreation.metadata import GameMetadata as _GameMetadata
        self._metadata: dict[str, _GameMetadata] = {}
        self._default_game: str = default_game
        # Active games by game_id
        self._active_games: dict[str, dict[str, Any]] = {}
        # Map thread_id -> game_id for move routing
        self._thread_games: dict[str, str] = {}
        factory = turns_factory if turns_factory is not None else RecreationTurnSupport
        self.turns: RecreationTurns = factory(
            self,
            dispatcher=dispatcher,
            emit_event_fn=emit_event_fn,
            clock=clock,
            actor_exists=actor_exists,
        )

        # Register default engines
        self.register_engine(TicTacToeEngine())
        self.register_engine(ChessEngine())

    @property
    def default_game(self) -> str:
        """AD-526c: Captain-default game preference."""
        return self._default_game

    def get_metadata(self, game_type: str) -> Any:
        """AD-526c: return GameMetadata for a registered game (or None)."""
        return self._metadata.get(game_type)

    def _resolve_callsign(self, callsign: str) -> str | None:
        """AD-654d: Resolve a callsign to agent_id via CallsignRegistry."""
        if not self._callsign_registry:
            return None
        resolved = self._callsign_registry.resolve(callsign)
        return resolved.get("agent_id") if resolved else None

    def register_engine(self, engine: GameEngine, metadata: Any = None) -> None:
        """Register a game engine by its game_type.

        AD-526c: optional ``metadata: GameMetadata`` supplements the engine
        with description / agent-count constraints / registration timestamp.
        Defaults to a ``GameMetadata(description="", agent_count_min=2,
        agent_count_max=2, registered_at=time.time())`` when None.
        """
        import time as _time
        from probos.events import EventType
        from probos.recreation.metadata import GameMetadata

        self._engines[engine.game_type] = engine
        meta = metadata if metadata is not None else GameMetadata(
            registered_at=_time.time(),
        )
        self._metadata[engine.game_type] = meta

        if self._emit is not None:
            try:
                self._emit(
                    EventType.RECREATION_GAME_REGISTERED,
                    {
                        "game_type": engine.game_type,
                        "description": meta.description,
                        "agent_count_min": meta.agent_count_min,
                        "agent_count_max": meta.agent_count_max,
                    },
                )
            except Exception:
                # AD-526c: emit is best-effort; never block registration
                pass

    def get_available_games(self) -> list[str]:
        """Return list of registered game type names."""
        return list(self._engines.keys())

    async def create_game(
        self,
        game_type: str,
        challenger: str,
        opponent: str,
        thread_id: str = "",
        *,
        opponent_agent_id: str | None = None,
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
        if self.turns.stopped:
            raise ValueError("Recreation service is stopped")
        for name, value in (("Game type", game_type), ("Challenger", challenger), ("Opponent", opponent)):
            canonical_text(value, name)
        canonical_text(thread_id, "Thread ID", allow_empty=True)
        if opponent_agent_id is not None:
            canonical_text(opponent_agent_id, "Opponent agent ID")
        if challenger == opponent:
            raise ValueError("Players must be distinct")
        if "Captain" in (challenger, opponent) and self.get_game_by_player("Captain") is not None:
            raise RecreationConflict("Captain already has an active game")
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
            "revision": 0,
            "opponent_agent_id": opponent_agent_id or self._resolve_callsign(opponent) or "",
            "challenger_agent_id": self._resolve_callsign(challenger) or "",
            "opponent_turn_status": "idle",
            "opponent_turn_reason": "",
        }

        self._active_games[game_id] = game_info
        if thread_id:
            self._thread_games[thread_id] = game_id

        self.turns.publish_snapshot(game_info)
        if not thread_id and challenger == "Captain" and self._ward_room is not None:
            try:
                channels = await self._ward_room.list_channels()
                channel = next((channel for channel in channels if channel.name == "Recreation"), None)
                if channel is not None and game_id in self._active_games and not self.turns.stopped:
                    thread = await self._ward_room.create_thread(
                        channel_id=channel.id, author_id="captain",
                        title=f"[Challenge] Captain challenges {opponent} to {game_type}!",
                        body=f"The Captain has challenged {opponent} to a game of {game_type}.",
                        author_callsign="Captain",
                    )
                    if game_id in self._active_games and not self.turns.stopped:
                        game_info["thread_id"] = thread.id
                        self._thread_games[thread.id] = game_id
                        game_info["revision"] += 1
                        self.turns.publish_snapshot(game_info)
            except Exception:
                logger.warning(
                    "Recreation thread creation failed for %s; admitted game remains available",
                    game_id, exc_info=True,
                )
        return game_info

    async def make_move(
        self, game_id: str, player: str, move: str,
        *, expected_revision: Any = UNVERSIONED,
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
        canonical_text(move, "Move")
        game_info = self.turns.validate_request(game_id, player, expected_revision=expected_revision)
        if not game_info:
            raise ValueError(f"Game {game_id} not found")

        engine = self._engines[game_info["game_type"]]
        if move not in engine.get_valid_moves(game_info["state"]):
            raise ValueError(f"Invalid move '{move}': not a canonical legal move")
        new_state = engine.make_move(game_info["state"], player, move)

        self.turns.invalidate_turn(game_id)
        game_info["state"] = new_state
        game_info["moves_count"] += 1
        game_info["revision"] += 1
        game_info["opponent_turn_status"] = "idle"
        game_info["opponent_turn_reason"] = ""
        game_info["last_move"] = {"player": player, "position": move}
        finished = engine.is_finished(new_state)
        event = self.turns.prepare_turn(game_info, finished=finished)
        if finished:
            game_info["result"] = engine.get_result(new_state)
            game_info["finished_at"] = time.time()
            game_info["board_text"] = engine.render_board(new_state)
            thread_id = game_info.get("thread_id", "")
            if self._thread_games.get(thread_id) == game_id:
                del self._thread_games[thread_id]
            del self._active_games[game_id]

        self.turns.publish_snapshot(game_info, completed=finished)

        if event is not None:
            try:
                admission = await self._dispatcher.dispatch(event)
                if not admission.accepted:
                    self.turns.fail_queued_turn(game_id, event.id, "dispatch_rejected")
            except Exception:
                logger.warning(
                    "Recreation dispatch failed for %s; the accepted move remains and the turn is recoverable",
                    game_id, exc_info=True,
                )
                self.turns.fail_queued_turn(game_id, event.id, "dispatch_failed")

        if finished:
            await self._record_game(game_info, engine)

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

    def get_game_by_player(self, callsign: str) -> dict[str, Any] | None:
        """Find an active game where the given callsign is a player.

        Returns the game info dict, or None if no active game found.
        AD-572: DRY extraction — this pattern was duplicated in proactive.py.
        """
        for game in self._active_games.values():
            players = [game.get("challenger", ""), game.get("opponent", "")]
            if callsign in players:
                return game
        return None

    async def forfeit_game(
        self, game_id: str, player: str, *, expected_revision: Any = UNVERSIONED,
    ) -> None:
        """Forfeit/abandon an active game."""
        game_info = self.turns.validate_request(game_id, player, expected_revision=expected_revision)
        if not game_info:
            return

        self.turns.invalidate_turn(game_id)
        game_info["board_text"] = self._engines[game_info["game_type"]].render_board(game_info["state"])
        game_info["state"] = {
            **game_info["state"], "status": "forfeited", "current_player": "", "winner": "",
        }
        game_info["result"] = {"status": "forfeited", "winner": "", "forfeited_by": player}
        game_info["finished_at"] = time.time()
        game_info["revision"] += 1
        game_info["opponent_turn_status"] = "idle"
        game_info["opponent_turn_reason"] = ""
        thread_id = game_info.get("thread_id", "")
        if self._thread_games.get(thread_id) == game_id:
            del self._thread_games[thread_id]
        del self._active_games[game_id]

        self.turns.publish_snapshot(game_info, completed=True)

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
