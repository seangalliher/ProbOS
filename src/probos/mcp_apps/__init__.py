"""AD-597: MCP App Host package — registry, game-app glue, external discovery."""

from __future__ import annotations

from probos.mcp_apps.registry import (
    AppResourceRegistration,
    AppToolRegistration,
    MCPAppRegistry,
)
from probos.mcp_apps.game_app import register_game_resources, register_game_tools
from probos.mcp_apps.external_discovery import discover_external_apps

__all__ = [
    "AppResourceRegistration",
    "AppToolRegistration",
    "MCPAppRegistry",
    "discover_external_apps",
    "register_game_resources",
    "register_game_tools",
]
