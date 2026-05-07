"""AD-597b: ProbOS Game MCP Server — wraps RecreationService as MCP App tools."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from probos.mcp_apps.registry import MCPAppRegistry

logger = logging.getLogger(__name__)


def register_game_tools(
    registry: MCPAppRegistry,
    recreation_service: Any,
) -> None:
    """Register 5 game tools backed by RecreationService."""

    available = recreation_service.get_available_games()

    async def _challenge(args: dict[str, Any]) -> dict[str, Any]:
        game_type = args.get("game_type", recreation_service.default_game)
        challenger = args.get("challenger", "")
        opponent = args.get("opponent", "")
        thread_id = args.get("thread_id", "")
        info = await recreation_service.create_game(
            game_type, challenger, opponent, thread_id
        )
        return {
            "isError": False,
            "content": [
                {"type": "text", "text": json.dumps(info, default=str)}
            ],
        }

    async def _move(args: dict[str, Any]) -> dict[str, Any]:
        info = await recreation_service.make_move(
            args.get("game_id", ""),
            args.get("player", ""),
            args.get("move", ""),
        )
        return {
            "isError": False,
            "content": [
                {"type": "text", "text": json.dumps(info, default=str)}
            ],
        }

    async def _state(args: dict[str, Any]) -> dict[str, Any]:
        game_id = args.get("game_id", "")
        info = recreation_service._active_games.get(game_id)
        if info is None:
            return {
                "isError": True,
                "content": [
                    {"type": "text", "text": f"unknown game_id {game_id}"}
                ],
            }
        return {
            "isError": False,
            "content": [
                {"type": "text", "text": json.dumps(info, default=str)}
            ],
        }

    async def _forfeit(args: dict[str, Any]) -> dict[str, Any]:
        await recreation_service.forfeit_game(
            args.get("game_id", ""), args.get("player", "")
        )
        return {"isError": False, "content": [{"type": "text", "text": "ok"}]}

    async def _valid_moves(args: dict[str, Any]) -> dict[str, Any]:
        moves = recreation_service.get_valid_moves(args.get("game_id", ""))
        return {
            "isError": False,
            "content": [{"type": "text", "text": json.dumps(moves)}],
        }

    # Per-game-type challenge tool registration.
    for game_type in available:
        ui_uri = f"ui://probos/games/{game_type}/index.html"
        registry.register_app_tool(
            name=f"game-{game_type}-challenge",
            description=f"Challenge to a {game_type} game",
            input_schema={
                "type": "object",
                "properties": {
                    "challenger": {"type": "string"},
                    "opponent": {"type": "string"},
                    "thread_id": {"type": "string"},
                },
                "required": ["challenger", "opponent"],
            },
            ui_resource_uri=ui_uri,
            handler=_challenge,
        )

    # Generic game-* tools (game_id-driven; no game_type-specific UI URI)
    registry.register_app_tool(
        name="game-move",
        description="Make a move in an active game",
        input_schema={
            "type": "object",
            "properties": {
                "game_id": {"type": "string"},
                "player": {"type": "string"},
                "move": {"type": "string"},
            },
            "required": ["game_id", "player", "move"],
        },
        ui_resource_uri="",
        handler=_move,
    )
    registry.register_app_tool(
        name="game-state",
        description="Get current state of a game",
        input_schema={
            "type": "object",
            "properties": {"game_id": {"type": "string"}},
            "required": ["game_id"],
        },
        ui_resource_uri="",
        handler=_state,
    )
    registry.register_app_tool(
        name="game-forfeit",
        description="Forfeit an active game",
        input_schema={
            "type": "object",
            "properties": {
                "game_id": {"type": "string"},
                "player": {"type": "string"},
            },
            "required": ["game_id", "player"],
        },
        ui_resource_uri="",
        handler=_forfeit,
    )
    registry.register_app_tool(
        name="game-valid-moves",
        description="List valid moves for the current player",
        input_schema={
            "type": "object",
            "properties": {"game_id": {"type": "string"}},
            "required": ["game_id"],
        },
        ui_resource_uri="",
        handler=_valid_moves,
    )


def register_game_resources(
    registry: MCPAppRegistry,
    bundles_dir: Path,
) -> None:
    """Register HTML bundles under bundles_dir/<game_type>/index.html as ui:// resources."""
    if not bundles_dir.is_dir():
        logger.warning(
            "AD-597b: bundles dir missing: %s — skipping resource registration",
            bundles_dir,
        )
        return
    for game_dir in sorted(bundles_dir.iterdir()):
        if not game_dir.is_dir():
            continue
        index_path = game_dir / "index.html"
        if not index_path.is_file():
            logger.warning(
                "AD-597b: bundle missing index.html: %s", game_dir.name
            )
            continue
        try:
            content = index_path.read_bytes()
        except OSError as exc:
            logger.warning(
                "AD-597b: failed to read %s: %s", index_path, exc
            )
            continue
        uri = f"ui://probos/games/{game_dir.name}/index.html"
        registry.register_app_resource(
            uri=uri, mime_type="text/html", content=content
        )
