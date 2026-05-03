"""AD-449: MCPBridge -- coordinator over MCPClient instances."""

from __future__ import annotations

import logging
from typing import Any

from probos.integrations.mcp_bridge.client import MCPClient, MCPProtocolError
from probos.integrations.mcp_bridge.session import MCPSession

logger = logging.getLogger(__name__)


class MCPBridge:
    """Coordinator over MCPClient instances.

    v1 surface:
      - register_server(url, headers=None) -> bool
      - list_servers() -> list[str]
      - get_client(server_url) -> MCPClient | None
      - invoke(server_url, tool_name, arguments) -> dict
      - close_all()

    Each registered server gets its own MCPClient with its own MCPSession.
    Session lifecycle is per-server (one session per registered URL in v1;
    multi-session-per-server is deferred to AD-449e).
    """

    def __init__(
        self,
        *,
        egress_policy: Any | None = None,
        emit_event: Any | None = None,
        request_timeout: float = 30.0,
    ) -> None:
        self._egress_policy = egress_policy
        self._emit_event = emit_event
        self._request_timeout = request_timeout
        self._clients: dict[str, MCPClient] = {}

    def register_server(
        self, url: str, headers: dict[str, str] | None = None,
    ) -> bool:
        if not url:
            return False
        if url in self._clients:
            return False
        session = MCPSession(server_url=url, headers=dict(headers or {}))
        client = MCPClient(
            session=session,
            egress_policy=self._egress_policy,
            emit_event=self._emit_event,
            timeout=self._request_timeout,
        )
        self._clients[url] = client
        return True

    def list_servers(self) -> list[str]:
        return list(self._clients.keys())

    def get_client(self, server_url: str) -> MCPClient | None:
        return self._clients.get(server_url)

    async def invoke(
        self, server_url: str, tool_name: str, arguments: dict[str, Any],
    ) -> dict:
        client = self._clients.get(server_url)
        if client is None:
            raise MCPProtocolError(f"unknown server: {server_url}")
        return await client.call_tool(tool_name, arguments)

    async def close_all(self) -> None:
        for client in list(self._clients.values()):
            try:
                await client.close()
            except Exception:
                logger.warning(
                    "AD-449: MCPClient close failed", exc_info=True,
                )
        self._clients.clear()
