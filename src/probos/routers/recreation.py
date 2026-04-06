"""ProbOS API — Recreation routes (AD-526b)."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.routers.deps import get_runtime, get_ws_broadcast

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recreation", tags=["recreation"])


@router.post("/challenge")
async def challenge_agent(
    body: dict,
    runtime: Any = Depends(get_runtime),
    broadcast: Any = Depends(get_ws_broadcast),
):
    """Captain challenges a crew agent to a game."""
    opponent_id = body.get("opponent_agent_id", "")
    game_type = body.get("game_type", "tictactoe")

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

    # Create Ward Room thread in Recreation channel
    thread_id = ""
    try:
        channels = await runtime.ward_room.list_channels()
        rec_ch = next((c for c in channels if c.name == "Recreation"), None)
        if rec_ch:
            thread = await runtime.ward_room.create_thread(
                channel_id=rec_ch.id,
                author_id="captain",
                title=f"[Challenge] Captain challenges {callsign} to {game_type}!",
                body=f"The Captain has challenged {callsign} to a game of {game_type}.",
                author_callsign="Captain",
            )
            thread_id = thread.id
    except Exception:
        logger.debug("Ward Room thread creation failed for Captain challenge", exc_info=True)

    # Create game via service
    game = await rec_svc.create_game(game_type, "Captain", callsign, thread_id)
    state = game.get("state", {})
    board = state.get("board", [""] * 9)
    valid_moves = rec_svc.get_valid_moves(game["game_id"])

    result = {
        "game_id": game["game_id"],
        "game_type": game_type,
        "board": board,
        "current_player": state.get("current_player", "Captain"),
        "status": state.get("status", "in_progress"),
        "winner": "",
        "valid_moves": valid_moves,
        "moves_count": 0,
        "opponent": callsign,
        "opponent_agent_id": opponent_id,
        "thread_id": thread_id,
    }

    broadcast({"type": "game_update", "data": result, "timestamp": time.time()})
    return result


@router.post("/move")
async def make_move(
    body: dict,
    runtime: Any = Depends(get_runtime),
    broadcast: Any = Depends(get_ws_broadcast),
):
    """Captain makes a move in an active game."""
    game_id = body.get("game_id", "")
    position = body.get("position", "")

    rec_svc = getattr(runtime, "recreation_service", None)
    if not rec_svc:
        raise HTTPException(status_code=503, detail="Recreation service not available")

    try:
        game_info = await rec_svc.make_move(game_id, "Captain", position)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    state = game_info.get("state", {})
    board = state.get("board", [""] * 9)

    # Post board update to Ward Room thread
    thread_id = game_info.get("thread_id", "")
    if thread_id and runtime.ward_room:
        try:
            board_text = rec_svc.render_board(game_id)
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

    valid_moves = rec_svc.get_valid_moves(game_id) if state.get("status") == "in_progress" else []

    return {
        "board": board,
        "current_player": state.get("current_player", ""),
        "status": state.get("status", "in_progress"),
        "winner": state.get("winner", ""),
        "valid_moves": valid_moves,
        "moves_count": game_info.get("moves_count", 0),
    }


@router.get("/active")
async def get_active_game(runtime: Any = Depends(get_runtime)):
    """Return the Captain's active game, if any."""
    rec_svc = getattr(runtime, "recreation_service", None)
    if not rec_svc:
        return {"game": None}

    for game in rec_svc.get_active_games():
        if "Captain" in [game.get("challenger"), game.get("opponent")]:
            state = game.get("state", {})
            board = state.get("board", [""] * 9)
            valid_moves = rec_svc.get_valid_moves(game["game_id"])
            opponent = game.get("opponent") if game.get("challenger") == "Captain" else game.get("challenger")
            return {
                "game": {
                    "game_id": game["game_id"],
                    "game_type": game.get("game_type", "tictactoe"),
                    "board": board,
                    "current_player": state.get("current_player", ""),
                    "status": state.get("status", "in_progress"),
                    "winner": state.get("winner", ""),
                    "valid_moves": valid_moves,
                    "moves_count": game.get("moves_count", 0),
                    "opponent": opponent,
                    "opponent_agent_id": "",
                    "thread_id": game.get("thread_id", ""),
                }
            }
    return {"game": None}


@router.post("/forfeit")
async def forfeit_game(
    body: dict,
    runtime: Any = Depends(get_runtime),
    broadcast: Any = Depends(get_ws_broadcast),
):
    """Captain forfeits the active game."""
    game_id = body.get("game_id", "")

    rec_svc = getattr(runtime, "recreation_service", None)
    if not rec_svc:
        raise HTTPException(status_code=503, detail="Recreation service not available")

    await rec_svc.forfeit_game(game_id, "Captain")

    broadcast({"type": "game_update", "data": {
        "game_id": game_id,
        "status": "forfeited",
        "board": [""] * 9,
        "current_player": "",
        "winner": "",
        "valid_moves": [],
        "moves_count": 0,
    }, "timestamp": time.time()})

    return {"status": "forfeited"}
