"""ProbOS API — Recreation routes (AD-526b)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.recreation.turns import RecreationConflict, RecreationTurns, canonical_text, validate_revision
from probos.routers.deps import (
    WebSocketBroadcast,
    get_runtime,
    get_ws_broadcast,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recreation", tags=["recreation"])


def _validate_body(body: dict[str, Any], *fields: str, revision_required: bool = False) -> dict[str, Any]:
    try:
        if type(body) is not dict:
            raise ValueError("Request body must be an object")
        for field in fields:
            canonical_text(body.get(field), field)
        if "revision" in body or revision_required:
            validate_revision(body.get("revision"))
            return {"expected_revision": body["revision"]}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {}


@router.post("/challenge")
async def challenge_agent(
    body: dict[str, Any],
    runtime: Any = Depends(get_runtime),
    broadcast: WebSocketBroadcast | None = Depends(get_ws_broadcast),
) -> dict[str, Any]:
    """Captain challenges a crew agent to a game."""
    _validate_body(body, "opponent_agent_id")
    opponent_id = body.get("opponent_agent_id", "")
    game_type = body.get("game_type", "tictactoe")
    try:
        canonical_text(game_type, "Game type")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    rec_svc = getattr(runtime, "recreation_service", None)
    if not rec_svc:
        raise HTTPException(status_code=503, detail="Recreation service not available")

    # Validate: agent exists
    target_agent = None
    for agent in runtime.registry.all():
        if agent.id == opponent_id:
            target_agent = agent
            break
    if not target_agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Validate: agent is crew (has callsign)
    callsign = ""
    if hasattr(runtime, "callsign_registry"):
        callsign = runtime.callsign_registry.get_callsign(target_agent.agent_type)
    if not callsign:
        raise HTTPException(
            status_code=400,
            detail="Agent has no callsign — only crew agents can be challenged",
        )

    try:
        game = await rec_svc.create_game(
            game_type, "Captain", callsign, "", opponent_agent_id=opponent_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409 if isinstance(exc, RecreationConflict) else 400, detail=str(exc),
        ) from exc
    turns: RecreationTurns = rec_svc.turns
    return turns.snapshot(game)


@router.post("/move")
async def make_move(
    body: dict[str, Any],
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Captain makes a move in an active game."""
    precondition = _validate_body(body, "game_id", "position")
    game_id = body.get("game_id", "")
    position = body.get("position", "")

    rec_svc = getattr(runtime, "recreation_service", None)
    if not rec_svc:
        raise HTTPException(status_code=503, detail="Recreation service not available")

    try:
        game_info = await rec_svc.make_move(game_id, "Captain", position, **precondition)
    except ValueError as e:
        raise HTTPException(status_code=409 if isinstance(e, RecreationConflict) else 400, detail=str(e)) from e

    state = game_info.get("state", {})
    # Post board update to Ward Room thread
    thread_id = game_info.get("thread_id", "")
    if thread_id and runtime.ward_room:
        try:
            board_text = game_info.get("board_text") or rec_svc.render_board(game_id)
            status_text = state.get("status", "in_progress")
            if status_text == "won":
                msg = f"Game over! Winner: {state.get('winner', '?')}\n```\n{board_text}\n```"
            elif status_text == "draw":
                msg = f"Game over! Draw!\n```\n{board_text}\n```"
            else:
                msg = f"Captain played position {position}.\n```\n{board_text}\n```\nNext: {state.get('current_player', '?')}"
            await runtime.ward_room.create_post(
                thread_id=thread_id,
                author_id="captain",
                body=msg,
                author_callsign="Captain",
            )
        except Exception:
            logger.debug("Ward Room post failed for Captain move", exc_info=True)

    turns: RecreationTurns = rec_svc.turns
    return turns.snapshot(game_info)


@router.get("/active")
async def get_active_game(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Return the Captain's active game, if any."""
    rec_svc = getattr(runtime, "recreation_service", None)
    if not rec_svc:
        return {"game": None}

    for game in rec_svc.get_active_games():
        if "Captain" in [game.get("challenger"), game.get("opponent")]:
            turns: RecreationTurns = rec_svc.turns
            return {"game": turns.snapshot(game)}
    return {"game": None}


@router.post("/forfeit")
async def forfeit_game(
    body: dict[str, Any],
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Captain forfeits the active game."""
    precondition = _validate_body(body, "game_id")
    game_id = body.get("game_id", "")

    rec_svc = getattr(runtime, "recreation_service", None)
    if not rec_svc:
        raise HTTPException(status_code=503, detail="Recreation service not available")

    try:
        game = next((game for game in rec_svc.get_active_games() if game["game_id"] == game_id), None)
        await rec_svc.forfeit_game(game_id, "Captain", **precondition)
    except ValueError as exc:
        raise HTTPException(status_code=409 if isinstance(exc, RecreationConflict) else 400, detail=str(exc)) from exc

    turns: RecreationTurns = rec_svc.turns
    return turns.snapshot(game) if game is not None and precondition else {"status": "forfeited"}


@router.post("/retry")
async def retry_turn(
    body: dict[str, Any], runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Captain explicitly retries a recoverable opponent turn."""
    precondition = _validate_body(body, "game_id", revision_required=True)
    rec_svc = getattr(runtime, "recreation_service", None)
    if not rec_svc:
        raise HTTPException(status_code=503, detail="Recreation service not available")
    turns: RecreationTurns = rec_svc.turns
    try:
        return await turns.retry(body["game_id"], "Captain", **precondition)
    except ValueError as exc:
        raise HTTPException(status_code=409 if isinstance(exc, RecreationConflict) else 400, detail=str(exc)) from exc
