"""AD-597f: External MCP App discovery via existing AD-449 MCPBridge."""

from __future__ import annotations

import logging
from typing import Any

from probos.mcp_apps.registry import MCPAppRegistry

logger = logging.getLogger(__name__)


async def discover_external_apps(
    registry: MCPAppRegistry,
    mcp_bridge: Any,
) -> int:
    """Iterate connected MCP servers, discover app tools, register them.

    Returns count of external app tools registered. Tier-2 log-and-degrade:
    per-server failure logs WARNING and skips that server.
    """
    if mcp_bridge is None:
        return 0
    count = 0
    try:
        # AD-449 MCPBridge.list_servers() returns list[str] of server URLs;
        # use get_client(server_url) to resolve to MCPClient.
        server_urls = mcp_bridge.list_servers()
    except Exception as exc:
        logger.warning("AD-597f: list_servers failed: %s", exc)
        return 0
    for server_url in server_urls:
        client = mcp_bridge.get_client(server_url)
        if client is None:
            continue
        try:
            tools = await client.list_tools()
        except Exception as exc:
            logger.warning(
                "AD-597f: list_tools failed for %s: %s", server_url, exc
            )
            continue
        for tool in tools:
            ui = tool.get("_meta", {}).get("ui", {})
            if not ui.get("resourceUri"):
                continue
            csp = ui.get("csp", "")
            try:
                registry.register_external_app(
                    server_id=server_url,
                    tool_dict=tool,
                    csp=csp,
                    mcp_client=client,
                )
                count += 1
            except ValueError as exc:
                logger.warning(
                    "AD-597f: skipping %s/%s: %s",
                    server_url, tool.get("name", "?"), exc,
                )
    return count
