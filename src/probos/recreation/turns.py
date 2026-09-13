"""Service-owned identities for a single recreation turn attempt."""

from __future__ import annotations

import asyncio
import logging
import math
import uuid
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, Literal, Protocol

from probos.types import IntentMessage

if TYPE_CHECKING:
    from probos.activation.task_event import TaskEvent


logger = logging.getLogger(__name__)


TURN_ATTEMPT_TIMEOUT_SECONDS = 120.0
UNVERSIONED = object()


class RecreationConflict(ValueError):
    """A request refers to an obsolete game projection."""


def canonical_text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if type(allow_empty) is not bool:
        raise ValueError("Allow empty must be a boolean")
    if type(value) is not str or value != value.strip() or (not value and not allow_empty):
        raise ValueError(f"{name}: values must be non-empty strings in canonical form")
    return value


def validate_revision(value: Any) -> None:
    if value is not UNVERSIONED and (type(value) is not int or value < 0):
        raise ValueError("Revision must be a non-negative integer")


def validate_game_record(game: Any) -> None:
    if type(game) is not dict or type(game.get("state")) is not dict:
        raise ValueError("Expected a game record with state")
    for key in ("game_id", "game_type", "challenger", "opponent"):
        canonical_text(game.get(key), key)
    for key in ("opponent_agent_id", "challenger_agent_id", "opponent_turn_status", "opponent_turn_reason"):
        canonical_text(game.get(key), key, allow_empty=True)
    for key in ("revision", "moves_count"):
        validate_revision(game.get(key))
    if type(game["state"].get("board")) is not list:
        raise ValueError("Game record requires a board")
    canonical_text(game["state"].get("status"), "Status")


class RecreationTimerHandle(Protocol):
    def cancel(self) -> None: ...


class RecreationTimerScheduler(Protocol):
    def __call__(
        self, delay: float, callback: Callable[[], None],
    ) -> RecreationTimerHandle: ...


def _schedule_turn_timer(delay: float, callback: Callable[[], None]) -> RecreationTimerHandle:
    return asyncio.get_running_loop().call_later(delay, callback)


@dataclass(frozen=True)
class RecreationTurnClaim:
    game_id: str
    turn_id: str
    attempt_id: str
    event_id: str
    agent_id: str
    player: str
    moves_count: int
    deadline: float
    game_type: str
    board: str
    valid_moves: tuple[str, ...]
    symbol: str


@dataclass
class RecreationTurnAttempt:
    claim: RecreationTurnClaim
    status: Literal["queued", "thinking", "recoverable"] = "queued"
    reason: str = ""
    retry_revision: int | None = None


class RecreationGameAccess(Protocol):
    def get_active_games(self) -> list[dict[str, Any]]: ...

    async def make_move(
        self, game_id: str, player: str, move: str,
        *, expected_revision: Any = UNVERSIONED,
    ) -> dict[str, Any]: ...

    def render_board(self, game_id: str) -> str: ...

    def get_valid_moves(self, game_id: str) -> list[str]: ...


class RecreationTurnOperations(Protocol):
    def claim_turn(self, intent: IntentMessage, agent_id: str) -> RecreationTurnClaim | None: ...

    async def complete_turn(
        self, claim: RecreationTurnClaim, move: str | None, *, reason: str = "",
    ) -> dict[str, Any]: ...


class RecreationTurns(RecreationTurnOperations, Protocol):
    stopped: bool

    async def stop(self) -> None: ...

    def validate_request(
        self, game_id: str, player: str, *, expected_revision: Any = UNVERSIONED,
    ) -> dict[str, Any] | None: ...

    async def retry(
        self, game_id: str, player: str, *, expected_revision: int,
    ) -> dict[str, Any]: ...

    def prepare_turn(self, game_info: dict[str, Any], *, finished: bool) -> TaskEvent | None: ...

    def turn_projection(self, game_info: dict[str, Any]) -> dict[str, Any]: ...

    def snapshot(self, game_info: dict[str, Any]) -> dict[str, Any]: ...

    def publish_snapshot(self, game_info: dict[str, Any], *, completed: bool = False) -> None: ...

    def invalidate_turn(self, game_id: str) -> None: ...

    def fail_queued_turn(self, game_id: str, event_id: str, reason: str) -> None: ...


class RecreationTurnSupportFactory(Protocol):
    def __call__(
        self,
        games: RecreationGameAccess,
        *,
        dispatcher: Any,
        emit_event_fn: Callable[[Any, dict[str, Any]], None] | None,
        clock: Callable[[], float],
        actor_exists: Callable[[str], bool] | None,
    ) -> RecreationTurns: ...


class RecreationTurnSupport:
    """Own attempt delivery state while the game service owns legal mutation."""

    def __init__(
        self,
        games: RecreationGameAccess,
        *,
        dispatcher: Any,
        emit_event_fn: Callable[[Any, dict[str, Any]], None] | None,
        clock: Callable[[], float],
        actor_exists: Callable[[str], bool] | None,
        schedule_timer: RecreationTimerScheduler = _schedule_turn_timer,
    ) -> None:
        self._games = games
        self._dispatcher = dispatcher
        self._emit = emit_event_fn
        self._clock = clock
        self._actor_exists = actor_exists
        self._turn_attempts: dict[str, RecreationTurnAttempt] = {}
        self._schedule_timer = schedule_timer
        self._timers: dict[str, RecreationTimerHandle] = {}
        self.stopped: bool = False

    def validate_request(
        self, game_id: str, player: str, *, expected_revision: Any = UNVERSIONED,
    ) -> dict[str, Any] | None:
        """Validate participation and an optional compare-and-set precondition."""
        canonical_text(game_id, "Game ID")
        canonical_text(player, "Player")
        validate_revision(expected_revision)
        if self.stopped:
            raise ValueError("Recreation service is stopped")
        game = next((game for game in self._games.get_active_games() if game["game_id"] == game_id), None)
        if game is None:
            return None
        if player not in (game["challenger"], game["opponent"]):
            raise ValueError("Player is not a participant")
        if expected_revision is not UNVERSIONED and expected_revision != game["revision"]:
            raise RecreationConflict("Stale game revision")
        return game

    def prepare_turn(self, game_info: dict[str, Any], *, finished: bool) -> TaskEvent | None:
        from probos.activation import task_event_for_agent
        from probos.types import Priority

        validate_game_record(game_info)
        if type(finished) is not bool:
            raise ValueError("Finished must be a boolean")
        state = game_info["state"]
        player = state.get("current_player", "")
        canonical_text(player, "Current player", allow_empty=finished)
        if self.stopped or finished or player == "Captain":
            return None
        if player not in (game_info["challenger"], game_info["opponent"]):
            raise ValueError("Current player is not a participant")
        if not any(game is game_info for game in self._games.get_active_games()):
            raise ValueError("Turn preparation requires the authoritative active record")
        agent_id = game_info[
            "opponent_agent_id" if player == game_info["opponent"] else "challenger_agent_id"
        ]
        reason = ""
        if not self._dispatcher:
            reason = "dispatcher_unavailable"
        elif not agent_id or (self._actor_exists is not None and not self._actor_exists(agent_id)):
            reason = "actor_unavailable"
        if reason:
            game_info["opponent_turn_status"] = "recoverable"
            game_info["opponent_turn_reason"] = reason
            logger.warning(
                "Recreation turn for %s cannot be queued (%s); board retained for recovery",
                game_info["game_id"], reason,
            )
            return None

        game_id = game_info["game_id"]
        turn_id = f"{game_id}:{game_info['moves_count']}:{agent_id}"
        attempt_id = uuid.uuid4().hex
        deadline = self._clock() + TURN_ATTEMPT_TIMEOUT_SECONDS
        event = task_event_for_agent(
            agent_id=agent_id,
            source_type="recreation",
            source_id=game_id,
            event_type="move_required",
            priority=Priority.NORMAL,
            payload={
                "game_id": game_id,
                "game_type": game_info["game_type"],
                "turn_id": turn_id,
                "attempt_id": attempt_id,
                "board": self._games.render_board(game_id),
                "valid_moves": self._games.get_valid_moves(game_id),
                "opponent": next(
                    participant for participant in (game_info["challenger"], game_info["opponent"])
                    if participant != player
                ),
                "your_symbol": state.get("symbols", {}).get(player, ""),
                "thread_id": game_info.get("thread_id", ""),
            },
            thread_id=game_info.get("thread_id"),
            deadline=deadline,
        )
        claim = RecreationTurnClaim(
            game_id=game_id, turn_id=turn_id, attempt_id=attempt_id,
            event_id=event.id, agent_id=agent_id, player=player,
            moves_count=game_info["moves_count"], deadline=deadline,
            game_type=game_info["game_type"], board=self._games.render_board(game_id),
            valid_moves=tuple(self._games.get_valid_moves(game_id)),
            symbol=state.get("symbols", {}).get(player, ""),
        )
        self.invalidate_turn(game_id)
        self._turn_attempts[game_id] = RecreationTurnAttempt(claim)
        self._timers[game_id] = self._schedule_timer(
            TURN_ATTEMPT_TIMEOUT_SECONDS, partial(self._expire_turn, claim),
        )
        game_info["opponent_turn_status"] = "queued"
        game_info["opponent_turn_reason"] = ""
        return event

    def _expire_turn(self, claim: RecreationTurnClaim) -> None:
        attempt = self._turn_attempts.get(claim.game_id)
        if self.stopped or attempt is None or attempt.claim is not claim:
            return
        timer = self._timers.pop(claim.game_id, None)
        if timer is not None:
            timer.cancel()
        if self._current_turn(claim) is not None:
            self._timers[claim.game_id] = self._schedule_timer(
                max(0.0, claim.deadline - self._clock()), partial(self._expire_turn, claim),
            )

    async def stop(self) -> None:
        """Close admission and cancel synchronous timer handles without spawning tasks."""
        if self.stopped:
            return
        self.stopped = True
        attempts = tuple(self._turn_attempts.values())
        for attempt in attempts:
            self.invalidate_turn(attempt.claim.game_id)
            self._set_turn_status(attempt, "recoverable", "service_stopped")

    def turn_projection(self, game_info: dict[str, Any]) -> dict[str, Any]:
        validate_game_record(game_info)
        attempt = self._turn_attempts.get(game_info["game_id"])
        return {
            "revision": game_info["revision"],
            "opponent_agent_id": game_info[
                "challenger_agent_id" if game_info["opponent"] == "Captain" else "opponent_agent_id"
            ],
            "opponent_turn_status": game_info["opponent_turn_status"],
            "opponent_turn_reason": game_info["opponent_turn_reason"],
            "turn_id": attempt.claim.turn_id if attempt else "",
            "attempt_id": attempt.claim.attempt_id if attempt else "",
            "event_id": attempt.claim.event_id if attempt else "",
        }

    def invalidate_turn(self, game_id: str) -> None:
        canonical_text(game_id, "Game ID")
        self._turn_attempts.pop(game_id, None)
        timer = self._timers.pop(game_id, None)
        if timer is not None:
            timer.cancel()

    def snapshot(self, game_info: dict[str, Any]) -> dict[str, Any]:
        """Serialize an authoritative active or retained terminal game record."""
        try:
            validate_game_record(game_info)
        except ValueError as exc:
            raise ValueError(f"Snapshot requires a valid game record: {exc}") from exc
        state = game_info["state"]
        snapshot = {
            "game_id": game_info["game_id"],
            "game_type": game_info["game_type"],
            "board": deepcopy(state["board"]),
            "current_player": state.get("current_player", ""),
            "status": state["status"],
            "winner": state.get("winner", ""),
            "valid_moves": (
                self._games.get_valid_moves(game_info["game_id"])
                if state["status"] == "in_progress" else []
            ),
            "moves_count": game_info["moves_count"],
            "participants": [game_info["challenger"], game_info["opponent"]],
            "opponent": (
                game_info["challenger"] if game_info["opponent"] == "Captain"
                else game_info["opponent"]
            ),
            "thread_id": game_info.get("thread_id", ""),
            **self.turn_projection(game_info),
        }
        for key in ("result", "last_move", "board_text"):
            if key in game_info:
                snapshot[key] = deepcopy(game_info[key])
        return snapshot

    def publish_snapshot(self, game_info: dict[str, Any], *, completed: bool = False) -> None:
        """Publish game state, independently attempting terminal engagement cleanup."""
        from probos.events import EventType

        if type(completed) is not bool:
            raise ValueError("Completed must be a boolean")
        snapshot = self.snapshot(game_info)
        if completed and (snapshot["status"] == "in_progress" or "result" not in snapshot):
            raise ValueError("Completion requires a terminal game result")
        if not self._emit:
            return
        try:
            self._emit(EventType.GAME_UPDATE, snapshot)
        except Exception:
            logger.warning(
                "Recreation snapshot publication failed for %s; authoritative state retained",
                game_info["game_id"], exc_info=True,
            )
        if completed and not game_info.get("completion_published", False):
            game_info["completion_published"] = True
            try:
                self._emit(EventType.GAME_COMPLETED, {
                    "game_id": game_info["game_id"],
                    "game_type": game_info["game_type"],
                    "players": [game_info["challenger"], game_info["opponent"]],
                    "result": deepcopy(game_info["result"]),
                    "moves_count": game_info["moves_count"],
                })
            except Exception:
                logger.warning(
                    "Recreation completion publication failed for %s; game retired but engagement cleanup may lag",
                    game_info["game_id"], exc_info=True,
                )

    def _set_turn_status(
        self, attempt: RecreationTurnAttempt,
        status: Literal["queued", "thinking", "recoverable"], reason: str = "",
    ) -> None:
        game_info = next(
            game for game in self._games.get_active_games()
            if game["game_id"] == attempt.claim.game_id
        )
        attempt.status = status
        attempt.reason = reason
        if status == "recoverable":
            timer = self._timers.pop(attempt.claim.game_id, None)
            if timer is not None:
                timer.cancel()
        game_info["revision"] += 1
        game_info["opponent_turn_status"] = status
        game_info["opponent_turn_reason"] = reason
        if reason:
            message = (
                "Recreation move_required attempt %s reached no agent (%s); board retained for recovery"
                if reason == "dispatch_rejected"
                else "Recreation attempt %s stopped (%s); board retained for recovery"
            )
            logger.warning(
                message,
                attempt.claim.attempt_id, reason,
            )
        self.publish_snapshot(game_info)

    def fail_queued_turn(self, game_id: str, event_id: str, reason: str) -> None:
        canonical_text(game_id, "Game ID")
        canonical_text(event_id, "Event ID")
        canonical_text(reason, "Reason")
        attempt = self._turn_attempts.get(game_id)
        if attempt and attempt.claim.event_id == event_id and attempt.status == "queued":
            self._set_turn_status(attempt, "recoverable", reason)

    def _current_turn(self, claim: RecreationTurnClaim) -> RecreationTurnAttempt | None:
        if self.stopped:
            return None
        attempt = self._turn_attempts.get(claim.game_id)
        game_info = next(
            (game for game in self._games.get_active_games() if game["game_id"] == claim.game_id),
            None,
        )
        if attempt is None or attempt.claim is not claim or game_info is None:
            return None
        if attempt.status == "recoverable":
            return None
        state = game_info["state"]
        if (
            state["status"] != "in_progress"
            or game_info["moves_count"] != claim.moves_count
            or state.get("current_player") != claim.player
        ):
            return None
        if self._clock() >= claim.deadline:
            self._set_turn_status(attempt, "recoverable", "deadline_expired")
            return None
        if self._actor_exists is not None and not self._actor_exists(claim.agent_id):
            self._set_turn_status(attempt, "recoverable", "actor_unavailable")
            return None
        return attempt

    def claim_turn(self, intent: IntentMessage, agent_id: str) -> RecreationTurnClaim | None:
        """Claim only the exact current service-issued event, once, before cognition."""
        if (
            type(intent) is not IntentMessage or type(agent_id) is not str or not agent_id.strip()
            or agent_id != agent_id.strip() or type(intent.intent) is not str
            or intent.intent != "move_required" or type(intent.target_agent_id) is not str
            or intent.target_agent_id != agent_id
            or type(intent.params) is not dict
        ):
            return None
        params = intent.params
        if any(
            type(params.get(key)) is not str or not params[key] or params[key] != params[key].strip()
            for key in ("game_id", "_source_type", "_source_id", "_task_event_id", "turn_id", "attempt_id")
        ):
            return None
        game_id = params.get("game_id")
        if type(game_id) is not str or not game_id:
            return None
        game_info = next(
            (game for game in self._games.get_active_games() if game["game_id"] == game_id), None,
        )
        if game_info is None or "Captain" not in (game_info["challenger"], game_info["opponent"]):
            return None
        attempt = self._turn_attempts.get(game_id)
        if attempt is None:
            return None
        claim = attempt.claim
        if (
            params.get("_source_type") != "recreation"
            or params.get("_source_id") != game_id
            or params.get("_task_event_id") != claim.event_id
            or params.get("turn_id") != claim.turn_id
            or params.get("attempt_id") != claim.attempt_id
            or agent_id != claim.agent_id
            or attempt.status != "queued"
            or self._current_turn(claim) is None
        ):
            return None
        self._set_turn_status(attempt, "thinking")
        return claim

    async def complete_turn(
        self, claim: RecreationTurnClaim, move: str | None, *, reason: str = "",
    ) -> dict[str, Any]:
        """Apply one parsed move only while the claimed attempt is still current."""
        if type(claim) is not RecreationTurnClaim:
            return {"applied": False, "reason": "invalid_claim"}
        if (
            any(type(value) is not str or not value or value != value.strip() for value in (
                claim.game_id, claim.turn_id, claim.attempt_id, claim.event_id, claim.agent_id, claim.player,
            ))
            or type(claim.moves_count) is not int or claim.moves_count < 0
            or type(claim.deadline) not in (int, float) or not math.isfinite(claim.deadline)
        ):
            return {"applied": False, "reason": "invalid_claim"}
        if type(reason) is not str or reason != reason.strip():
            return {"applied": False, "reason": "invalid_reason"}
        outcome = {
            "game_id": claim.game_id, "turn_id": claim.turn_id,
            "attempt_id": claim.attempt_id, "event_id": claim.event_id,
            "applied": False, "reason": "stale_attempt",
        }
        attempt = self._current_turn(claim)
        if attempt is None or attempt.status != "thinking":
            return outcome
        if type(move) is not str or not move.strip():
            outcome["reason"] = reason or "no_usable_move"
            self._set_turn_status(attempt, "recoverable", outcome["reason"])
            return outcome
        try:
            game_info = await self._games.make_move(claim.game_id, claim.player, move)
        except ValueError:
            outcome["reason"] = "invalid_move"
            self._set_turn_status(attempt, "recoverable", "invalid_move")
            return outcome
        outcome.update(applied=True, reason="", revision=game_info["revision"], move=move)
        return outcome

    async def retry(
        self, game_id: str, player: str, *, expected_revision: int,
    ) -> dict[str, Any]:
        """Replace a recoverable attempt once per projection revision."""
        validate_revision(expected_revision)
        if expected_revision is UNVERSIONED:
            raise ValueError("Retry requires a revision")
        game = self.validate_request(game_id, player)
        if game is None:
            raise ValueError("Game not found")
        attempt = self._turn_attempts.get(game_id)
        if attempt is not None and attempt.status in ("queued", "thinking"):
            if attempt.retry_revision == expected_revision and self._current_turn(attempt.claim) is not None:
                return self.snapshot(game)
        self.validate_request(game_id, player, expected_revision=expected_revision)
        if game["state"]["status"] != "in_progress" or game["state"].get("current_player") == player:
            raise ValueError("No opponent turn to retry")
        if game["opponent_turn_status"] != "recoverable":
            raise RecreationConflict("Opponent turn is already pending")
        self.invalidate_turn(game_id)
        game["revision"] += 1
        event = self.prepare_turn(game, finished=False)
        if event is not None:
            self._turn_attempts[game_id].retry_revision = expected_revision
        self.publish_snapshot(game)
        if event is not None:
            try:
                admission = await self._dispatcher.dispatch(event)
                if not admission.accepted:
                    self.fail_queued_turn(game_id, event.id, "dispatch_rejected")
            except Exception:
                logger.warning(
                    "Recreation retry dispatch failed for %s; board retained for recovery",
                    game_id, exc_info=True,
                )
                self.fail_queued_turn(game_id, event.id, "dispatch_failed")
        return self.snapshot(game)
