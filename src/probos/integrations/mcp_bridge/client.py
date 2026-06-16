"""AD-449: MCPClient -- JSON-RPC 2.0 over a pluggable transport.

AD-1014: the wire I/O is delegated to a ``Transport`` (HTTP or stdio). The
client owns payload construction, envelope validation, and the single
``MCP_BRIDGE_*`` emission site; the transport owns the bytes. When no transport
is supplied the client builds an ``HttpTransport`` from the session — a public
back-compat default that keeps ``register_server`` and the existing AD-449 /
AD-597f tests byte-identical.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from probos.events import EventType
from probos.integrations.mcp_bridge.session import MCPSession

if TYPE_CHECKING:
    from probos.integrations.mcp_bridge.transport import Transport

logger = logging.getLogger(__name__)


# JSON-RPC 2.0 protocol version we negotiate. MCP also has a protocol-version
# string distinct from JSON-RPC; we send the MCP-protocol-version constant in
# the initialize payload.
JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2025-03-26"


class MCPProtocolError(Exception):
    """Raised when the server returns a JSON-RPC error or malformed payload.

    AD-1014: carries an optional ``reason`` so an (event-free) transport can name
    the wire failure (e.g. ``spawn_failed`` / ``timeout`` / ``egress_blocked``)
    without importing ``EventType``; the owning layer maps it onto the
    ``MCP_BRIDGE_FAILED`` event reason. Bare ``raise MCPProtocolError("msg")``
    still works (``reason`` defaults to ``""``).
    """

    def __init__(self, *args: Any, reason: str = "") -> None:
        super().__init__(*args)
        self.reason = reason


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
        transport: "Transport | None" = None,
        egress_policy: Any | None = None,
        emit_event: Any | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._session = session
        self._egress_policy = egress_policy
        self._emit_event = emit_event
        self._timeout = timeout
        # AD-1014: pluggable transport. When none is supplied, build the
        # byte-identical HTTP transport from the session (lazy import to avoid a
        # client<->transport import cycle). This default keeps register_server
        # and the existing direct-construction tests unchanged.
        if transport is None:
            from probos.integrations.mcp_bridge.transport import HttpTransport

            transport = HttpTransport(
                server_url=session.server_url,
                base_headers=session.headers,
                egress_policy=egress_policy,
                timeout=timeout,
                initial_session_id=session.session_id,
            )
        self._transport: Transport = transport

    @property
    def session(self) -> MCPSession:
        return self._session

    @property
    def _http(self) -> Any:
        """AD-1014 back-compat shim: the pre-AD-1014 HTTP body lived on
        ``client._http``; the existing AD-449 tests still set it to a mock. Proxy
        get/set to the (HTTP) transport's client so those tests stay byte-identical.
        Returns ``None`` for non-HTTP transports (nothing reads it for those)."""
        transport = getattr(self, "_transport", None)
        return getattr(transport, "_http", None)

    @_http.setter
    def _http(self, value: Any) -> None:
        transport = getattr(self, "_transport", None)
        if transport is not None:
            transport._http = value

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
        # initialize response; capture it via the transport's response-direction
        # metadata (lower-cased). stdio transports expose {} here (no headers).
        sid = self._transport.last_metadata.get("mcp-session-id", "") or ""
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

    async def read_resource(self, uri: str) -> dict:
        """AD-597f: Issue resources/read JSON-RPC call. Returns the result envelope."""
        result = await self._call(
            method="resources/read",
            params={"uri": uri},
        )
        return result if isinstance(result, dict) else {}

    async def close(self) -> None:
        # AD-1014: delegate teardown to the transport (HTTP closes the httpx
        # client; stdio closes stdin, terminates the subprocess, cancels the
        # stderr drain). Defensive getattr for __new__-bypass tests (convention #11).
        transport = getattr(self, "_transport", None)
        if transport is not None:
            await transport.close()

    async def _call(self, *, method: str, params: dict[str, Any]) -> dict:
        url = self._session.server_url
        request_id = uuid.uuid4().hex
        payload = {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "method": method,
            "params": params,
        }

        # AD-1014: the transport owns the wire (egress gate, headers, bytes) and
        # raises MCPProtocolError(reason=…) on any wire failure. The client is the
        # single MCP_BRIDGE_FAILED emission site for request-time failures.
        try:
            envelope = await self._transport.request(payload)
        except MCPProtocolError as exc:
            self._emit_failed(
                method,
                reason=exc.reason or "transport_error",
                url=url,
                detail=str(exc),
            )
            raise

        if not isinstance(envelope, dict):
            self._emit_failed(method, reason="bad_envelope", url=url)
            raise MCPProtocolError(f"bad envelope from {url}", reason="bad_envelope")

        if "error" in envelope:
            err = envelope.get("error") or {}
            msg = err.get("message", "unknown") if isinstance(err, dict) else "unknown"
            code = err.get("code", 0) if isinstance(err, dict) else 0
            self._emit_failed(method, reason="rpc_error", url=url, detail=f"{code}:{msg}")
            raise MCPProtocolError(f"rpc error {code}: {msg}", reason="rpc_error")

        result = envelope.get("result")
        if not isinstance(result, dict):
            self._emit_failed(method, reason="bad_result", url=url)
            raise MCPProtocolError(f"bad result from {url}", reason="bad_result")

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
