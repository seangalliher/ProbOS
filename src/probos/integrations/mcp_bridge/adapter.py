"""AD-449: MCPToolAdapter -- expose remote MCP tools as ProbOS Tools."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class MCPToolAdapter:
    """Wraps a remote MCP tool descriptor as a ProbOS Tool.

    v1 surface:
      - name -- ProbOS-side tool name (typically prefixed: ``mcp.<server>.<tool>``)
      - server_url -- the registered MCPBridge server
      - tool_name -- the remote tool name
      - description -- forwarded from the MCP server's ``tools/list`` response
      - input_schema -- forwarded from the MCP server (JSON Schema)
      - invoke(arguments) -> dict -- routes through ``MCPBridge.invoke``
    """

    def __init__(
        self,
        *,
        bridge: Any,
        server_url: str,
        tool_name: str,
        description: str = "",
        input_schema: dict | None = None,
        prefix: str = "mcp",
    ) -> None:
        self._bridge = bridge
        self.server_url = server_url
        self.tool_name = tool_name
        self.description = description
        self.input_schema = dict(input_schema or {})
        # Public name: mcp.<server-host>.<tool>
        self.name = f"{prefix}.{self._safe_host(server_url)}.{tool_name}"

    async def invoke(self, arguments: dict[str, Any]) -> dict:
        return await self._bridge.invoke(self.server_url, self.tool_name, arguments)

    @staticmethod
    def _safe_host(url: str) -> str:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").replace(".", "_")
        return host or "unknown"
