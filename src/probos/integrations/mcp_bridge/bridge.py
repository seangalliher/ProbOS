"""AD-449: MCPBridge -- coordinator over MCPClient instances."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from probos.events import EventType
from probos.integrations.mcp_bridge.client import MCPClient, MCPProtocolError
from probos.integrations.mcp_bridge.session import MCPSession
from probos.integrations.mcp_bridge.transport import StdioTransport

logger = logging.getLogger(__name__)


class MCPBridge:
    """Coordinator over MCPClient instances.

    v1 surface:
      - register_server(url, headers=None) -> bool
      - register_stdio_server(name, command, args, env, cwd, *, timeout) -> bool
      - list_servers() -> list[str]
      - get_client(server_url) -> MCPClient | None
      - invoke(server_url, tool_name, arguments) -> dict
      - close_all()

    Each registered server gets its own MCPClient with its own MCPSession.
    Session lifecycle is per-server (one session per registered URL in v1;
    multi-session-per-server is deferred to AD-449e).

    AD-1014: stdio/subprocess servers are launched via ``register_stdio_server``
    behind a default-OFF ``stdio_enabled`` gate, a ``command_allowlist`` (the
    primary guard — bounds *what* may be spawned), and an optional ``consent_fn``
    (a narrow ``async (ctx) -> bool``; startup adapts the HookBus to it so the
    bridge stays decoupled from HookBus/HookEvent/AggregateDecision).
    """

    def __init__(
        self,
        *,
        egress_policy: Any | None = None,
        emit_event: Any | None = None,
        request_timeout: float = 30.0,
        stdio_enabled: bool = False,
        command_allowlist: list[str] | None = None,
        consent_fn: Callable[[dict[str, Any]], Awaitable[bool]] | None = None,
    ) -> None:
        self._egress_policy = egress_policy
        self._emit_event = emit_event
        self._request_timeout = request_timeout
        self._stdio_enabled = stdio_enabled
        self._command_allowlist = list(command_allowlist or [])
        self._consent_fn = consent_fn
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

    async def register_stdio_server(
        self,
        name: str,
        command: str,
        args: list[str],
        env: dict[str, str],
        cwd: str,
        *,
        timeout: float | None = None,
    ) -> bool:
        """AD-1014: launch a stdio/subprocess MCP server (default-OFF, gated).

        Guards run in order, all BEFORE any subprocess is created:
          1. stdio disabled  -> return False (config state; no event).
          2. duplicate name  -> return False.
          3. command allowlist (primary guard) -> emit MCP_BRIDGE_FAILED
             reason="command_not_allowed"; return False; no spawn.
          4. consent_fn (second layer)         -> emit MCP_BRIDGE_FAILED
             reason="consent_denied"; return False; no spawn.
          5. spawn the StdioTransport; on MCPProtocolError the bridge emits
             MCP_BRIDGE_FAILED reason=<exc.reason or "spawn_failed">; honest-degrade.
        On success the client is keyed by ``name``; returns True.
        """
        source = f"stdio:{name}"
        if not self._stdio_enabled:
            return False
        if name in self._clients:
            return False
        if command not in self._command_allowlist:
            self._emit_failed(
                source, method="start", reason="command_not_allowed",
                detail=command[:200],
            )
            return False
        if self._consent_fn is not None:
            allowed = await self._consent_fn(
                {
                    "tool_name": "mcp_stdio_spawn",
                    "server": name,
                    "command": command,
                    "args": list(args or []),
                }
            )
            if not allowed:
                self._emit_failed(
                    source, method="start", reason="consent_denied",
                    detail=command[:200],
                )
                return False

        transport = StdioTransport(
            command=command,
            args=list(args or []),
            env=dict(env or {}),
            cwd=cwd,
            timeout=timeout or self._request_timeout,
            name=name,
        )
        client = MCPClient(
            session=MCPSession(server_url=source),
            transport=transport,
            emit_event=self._emit_event,
            timeout=timeout or self._request_timeout,
        )
        try:
            await transport.start()
        except MCPProtocolError as exc:
            # The start() path is NOT inside MCPClient._call, so the client's
            # emission wrapper never sees it — the bridge emits here.
            self._emit_failed(
                source, method="start", reason=exc.reason or "spawn_failed",
                detail=str(exc)[:200],
            )
            return False
        self._clients[name] = client
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

    def _emit_failed(
        self, source: str, *, method: str, reason: str, detail: str = "",
    ) -> None:
        """AD-1014: emit a registration-time MCP_BRIDGE_FAILED (allowlist /
        consent / spawn). Request-time failures are emitted by MCPClient._call —
        no path is emitted by both."""
        if self._emit_event is None:
            return
        try:
            self._emit_event(
                EventType.MCP_BRIDGE_FAILED,
                {
                    "server_url": source,
                    "method": method,
                    "reason": reason,
                    "detail": detail[:200] if detail else "",
                },
            )
        except Exception:
            logger.warning(
                "AD-1014: MCP_BRIDGE_FAILED emit failed (source=%s reason=%s)",
                source, reason, exc_info=True,
            )

