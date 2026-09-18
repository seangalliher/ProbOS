"""AD-449: MCPBridge -- coordinator over MCPClient instances."""

from __future__ import annotations

import asyncio
import logging
import os
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
        self._registration_config: dict[str, tuple[object, ...]] = {}

    def register_server(
        self, url: str, headers: dict[str, str] | None = None,
        *, reuse_if_matching: bool = False,
    ) -> bool:
        """Register locally, or opt into exact reuse; no remote handshake occurs."""
        if not url:
            return False
        if url in self._clients and not reuse_if_matching:
            return False
        copied_headers = dict(headers or {})
        configuration = (
            "http", url, frozenset(copied_headers.items()), self._request_timeout,
        )
        if url in self._clients:
            return reuse_if_matching and self._registration_config.get(url) == configuration
        session = MCPSession(server_url=url, headers=copied_headers)
        client = MCPClient(
            session=session,
            egress_policy=self._egress_policy,
            emit_event=self._emit_event,
            timeout=self._request_timeout,
        )
        self._clients[url] = client
        self._registration_config[url] = configuration
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
        reuse_if_matching: bool = False,
    ) -> bool:
        """AD-1014: launch a stdio/subprocess MCP server (default-OFF, gated).

        Guards run in order, all BEFORE any subprocess is created:
          1. stdio disabled  -> return False (config state; no event).
          2. duplicate name  -> return False unless exact reuse is requested.
          3. command allowlist (primary guard) -> emit MCP_BRIDGE_FAILED
             reason="command_not_allowed"; return False; no spawn.
          4. consent_fn (second layer)         -> emit MCP_BRIDGE_FAILED
             reason="consent_denied"; return False; no spawn.
          5. spawn the StdioTransport; on MCPProtocolError the bridge emits
             MCP_BRIDGE_FAILED reason=<exc.reason or "spawn_failed">; honest-degrade.
        Exact reuse requires the gates, matching configuration and positive
        liveness. A matching dead client is detached before cleanup; unknown
        liveness and mismatches leave it untouched. Configuration is copied before
        awaits and ownership rechecked after cleanup/preparation. A losing
        unpublished candidate is closed without disturbing the current winner.
        On success the client is keyed by ``name``; returns True.
        """
        source = f"stdio:{name}"
        if not self._stdio_enabled:
            return False
        if name in self._clients and not reuse_if_matching:
            return False
        if reuse_if_matching and (not name or not command):
            return False
        if command not in self._command_allowlist:
            self._emit_failed(
                source, method="start", reason="command_not_allowed",
                detail=command[:200],
            )
            return False
        copied_args = list(args or [])
        copied_env = {**os.environ, **dict(env or {})}
        effective_cwd = os.path.abspath(cwd or os.getcwd())
        effective_timeout = timeout or self._request_timeout
        configuration = (
            "stdio", name, command, tuple(copied_args),
            frozenset(copied_env.items()), effective_cwd, effective_timeout,
        )
        if self._consent_fn is not None:
            allowed = await self._consent_fn(
                {
                    "tool_name": "mcp_stdio_spawn",
                    "server": name,
                    "command": command,
                    "args": list(copied_args),
                }
            )
            if not allowed:
                self._emit_failed(
                    source, method="start", reason="consent_denied",
                    detail=command[:200],
                )
                return False
        existing = self._clients.get(name)
        if existing is not None:
            if not reuse_if_matching or self._registration_config.get(name) != configuration:
                return False
            alive = existing.is_alive
            if alive is not False:
                return alive is True
            # Detach the captured identity and configuration together, before yielding.
            del self._clients[name]
            del self._registration_config[name]
            await existing.close()
            if name in self._clients:
                return self._matching_live_stdio_client(name, configuration)

        transport = StdioTransport(
            command=command,
            args=copied_args,
            env=copied_env,
            cwd=effective_cwd,
            timeout=effective_timeout,
            name=name,
        )
        client = MCPClient(
            session=MCPSession(server_url=source),
            transport=transport,
            emit_event=self._emit_event,
            timeout=effective_timeout,
        )
        try:
            await transport.start()
            if name not in self._clients:
                if reuse_if_matching and client.is_alive is not True:
                    raise MCPProtocolError(
                        "stdio candidate has no confirmed live process", reason="spawn_failed",
                    )
                self._clients[name] = client
                self._registration_config[name] = configuration
                return True
        except asyncio.CancelledError:
            try:
                await self._close_candidate(client)
            except asyncio.CancelledError:
                logger.warning(
                    "Unpublished MCP candidate cleanup was cancelled; "
                    "preserving existing clients and propagating cancellation"
                )
            raise
        except MCPProtocolError as exc:
            await self._close_candidate(client)
            # The start() path is NOT inside MCPClient._call, so the client's
            # emission wrapper never sees it — the bridge emits here.
            self._emit_failed(
                source, method="start",
                reason="spawn_failed" if reuse_if_matching else exc.reason or "spawn_failed",
                detail="MCP candidate preparation failed" if reuse_if_matching else str(exc)[:200],
            )
            return False
        except Exception:
            await self._close_candidate(client)
            raise
        if not await self._close_candidate(client):
            return False
        return reuse_if_matching and self._matching_live_stdio_client(name, configuration)

    def _matching_live_stdio_client(self, name: str, configuration: tuple[object, ...]) -> bool:
        client = self._clients.get(name)
        return (
            client is not None
            and self._registration_config.get(name) == configuration
            and client.is_alive is True
        )

    async def _close_candidate(self, client: MCPClient) -> bool:
        try:
            await client.close()
        except Exception:
            logger.warning(
                "Unpublished MCP candidate cleanup failed; existing clients "
                "remain owned and registration does not publish the candidate "
                "(no exception payload logged)"
            )
            return False
        return True

    def list_servers(self) -> list[str]:
        return list(self._clients.keys())

    def get_client(self, server_url: str) -> MCPClient | None:
        return self._clients.get(server_url)

    async def unregister_server(self, key: str) -> bool:
        """AD-1015: tear down one registered client (the inverse of register).

        ``key`` is the value ``_clients`` is keyed by — ``url`` for http,
        ``name`` for stdio (the AD-1015 router derives it as
        ``record.url if record.type == "http" else record.name``). Returns
        ``True`` when a client was removed, ``False`` when the key was unknown.
        Mirrors ``close_all``'s ``await client.close()`` teardown.
        """
        client = self._clients.pop(key, None)
        self._registration_config.pop(key, None)
        if client is None:
            return False
        await client.close()
        return True

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
        self._registration_config.clear()

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
