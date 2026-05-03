"""AD-449: MCPClient -- JSON-RPC 2.0 over Streamable HTTP."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import replace
from typing import Any

import httpx

from probos.events import EventType
from probos.integrations.mcp_bridge.session import MCPSession

logger = logging.getLogger(__name__)


# JSON-RPC 2.0 protocol version we negotiate. MCP also has a protocol-version
# string distinct from JSON-RPC; we send the MCP-protocol-version constant in
# the initialize payload.
JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2025-03-26"


class MCPProtocolError(Exception):
    """Raised when the server returns a JSON-RPC error or malformed payload."""


class MCPClient:
    """JSON-RPC 2.0 client over Streamable HTTP.

    Public methods:
      - initialize() -> MCPSession
      - list_tools() -> list[dict]
      - call_tool(name, arguments) -> dict
      - close()

    Every outbound request is consulted through the egress policy
    (when wired). When the policy denies a URL, the call is rejected
    with MCPProtocolError and an MCP_BRIDGE_FAILED event with
    reason="egress_blocked" is emitted.
    """

    def __init__(
        self,
        *,
        session: MCPSession,
        egress_policy: Any | None = None,
        emit_event: Any | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._session = session
        self._egress_policy = egress_policy
        self._emit_event = emit_event
        self._timeout = timeout
        # AD-449: defensive getattr for __new__-bypass tests (convention #11)
        self._http: httpx.AsyncClient | None = httpx.AsyncClient(timeout=timeout)
        # AD-449 rev: instance-level header capture (was class attribute --
        # shared mutable state across MCPClient instances; race risk)
        self._last_response_headers: dict[str, str] = {}

    @property
    def session(self) -> MCPSession:
        return self._session

    async def initialize(self) -> MCPSession:
        result = await self._call(
            method="initialize",
            params={
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "probos", "version": "0.1.0"},
            },
        )
        capabilities = result.get("capabilities") or {}
        if not isinstance(capabilities, dict):
            capabilities = {}
        # Streamable HTTP servers may set a Mcp-Session-Id header on the
        # initialize response; capture it via the http response headers
        # surfaced through self._last_response_headers.
        sid = self._last_response_headers.get("mcp-session-id", "") or ""
        self._session = replace(
            self._session,
            session_id=sid,
            capabilities=capabilities,
        )
        return self._session

    async def list_tools(self) -> list[dict]:
        result = await self._call(method="tools/list", params={})
        tools = result.get("tools") or []
        return list(tools) if isinstance(tools, list) else []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict:
        result = await self._call(
            method="tools/call",
            params={"name": name, "arguments": arguments},
        )
        return result if isinstance(result, dict) else {}

    async def close(self) -> None:
        http = getattr(self, "_http", None)
        if http is not None:
            await http.aclose()
        self._http = None

    async def _call(self, *, method: str, params: dict[str, Any]) -> dict:
        url = self._session.server_url
        # Egress policy gate (AD-456 integration; convention #3)
        policy = self._egress_policy
        if policy is not None and not policy.is_allowed(url):
            self._emit_failed(method, reason="egress_blocked", url=url)
            raise MCPProtocolError(f"egress denied for {url}")

        request_id = uuid.uuid4().hex
        payload = {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "method": method,
            "params": params,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self._session.headers,
        }
        if self._session.session_id:
            headers["Mcp-Session-Id"] = self._session.session_id

        http = getattr(self, "_http", None)
        if http is None:
            self._emit_failed(method, reason="client_closed", url=url)
            raise MCPProtocolError("client closed")

        try:
            response = await http.post(url, content=json.dumps(payload), headers=headers)
        except httpx.HTTPError as exc:
            self._emit_failed(method, reason="transport_error", url=url, detail=str(exc))
            raise MCPProtocolError(f"transport error: {exc}") from exc

        # Capture headers for initialize() to extract Mcp-Session-Id
        self._last_response_headers = {
            k.lower(): v for k, v in response.headers.items()
        }

        if response.status_code >= 400:
            self._emit_failed(
                method, reason="http_error", url=url, detail=str(response.status_code),
            )
            raise MCPProtocolError(
                f"HTTP {response.status_code} from {url}"
            )

        try:
            envelope = response.json()
        except json.JSONDecodeError as exc:
            self._emit_failed(method, reason="bad_json", url=url, detail=str(exc))
            raise MCPProtocolError(f"bad JSON from {url}") from exc

        if not isinstance(envelope, dict):
            self._emit_failed(method, reason="bad_envelope", url=url)
            raise MCPProtocolError(f"bad envelope from {url}")

        if "error" in envelope:
            err = envelope.get("error") or {}
            msg = err.get("message", "unknown") if isinstance(err, dict) else "unknown"
            code = err.get("code", 0) if isinstance(err, dict) else 0
            self._emit_failed(method, reason="rpc_error", url=url, detail=f"{code}:{msg}")
            raise MCPProtocolError(f"rpc error {code}: {msg}")

        result = envelope.get("result")
        if not isinstance(result, dict):
            self._emit_failed(method, reason="bad_result", url=url)
            raise MCPProtocolError(f"bad result from {url}")

        self._emit_invoke(method, url=url)
        return result

    def _emit_invoke(self, method: str, *, url: str) -> None:
        if self._emit_event is None:
            return
        try:
            self._emit_event(
                EventType.MCP_BRIDGE_INVOKE,
                {
                    "server_url": url,
                    "method": method,
                    "session_id": self._session.session_id,
                },
            )
        except Exception:
            logger.warning(
                "AD-449: MCP_BRIDGE_INVOKE emit failed (method=%s)", method, exc_info=True,
            )

    def _emit_failed(
        self, method: str, *, reason: str, url: str, detail: str = "",
    ) -> None:
        if self._emit_event is None:
            return
        try:
            self._emit_event(
                EventType.MCP_BRIDGE_FAILED,
                {
                    "server_url": url,
                    "method": method,
                    "reason": reason,
                    "detail": detail[:200] if detail else "",
                },
            )
        except Exception:
            logger.warning(
                "AD-449: MCP_BRIDGE_FAILED emit failed (method=%s)", method, exc_info=True,
            )
