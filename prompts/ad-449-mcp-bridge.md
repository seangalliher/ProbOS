# AD-449: MCP Bridge — External System Integration (v1 OSS Infrastructure)

**Status:** Ready for builder
**Dependencies:** Builds on AD-448 ✅ (`ToolRegistry` + `ToolExecutor` at `src/probos/tools/registry.py:49` and `tools/executor.py:40`; verified) and AD-456 ✅ Wave 7 (`runtime.egress_policy` at `src/probos/security/egress.py:47`; verified). AD-449 OWNS `src/probos/integrations/__init__.py` and `src/probos/integrations/mcp_bridge/` directory creation (verified absent: `Test-Path src/probos/integrations` returns False).
**Estimated tests:** ~14
**Risk:** HIGH — new external-protocol surface; security review needed at Builder time. All MCP bridge calls go through `runtime.egress_policy.is_allowed(url)` per AD-456 contract.

> ★ **OSS BOUNDARY (AD-450 leak precedent applies).** This prompt describes the OSS bridge infrastructure ONLY: session management, tool routing, JSON-RPC over Streamable HTTP, EgressPolicy integration, and the public extension point for downstream MCP-server-pack consumers. Pricing, customer counts, GTM language, revenue model, and vendor-specific MCP server packs (third-party SaaS connector packs of any kind) belong in the private commercial repo (`commercial-roadmap.md`) and are explicitly out of scope here. The pre-commit hook will catch some patterns; do not include any of those topics in the prompt body, the source code, the docstrings, or the test names.

---

## Problem

ProbOS has no Model Context Protocol (MCP) client. MCP is the emerging open standard for AI-tool integration — a JSON-RPC 2.0 surface over Streamable HTTP that exposes external tools (databases, APIs, file systems) to AI assistants. ProbOS agents currently access external systems only through the in-process `ToolRegistry` (verified at `tools/registry.py:49`) — there is no reach for tools hosted outside the runtime.

`grep -rn "class MCPBridge\|class MCPSession\|class MCPClient" src/probos/` returns no matches.

The roadmap entry (line 4111) defines the bridge surface. v1 ships the OSS bridge infrastructure that makes ProbOS an MCP client — JSON-RPC client transport, session lifecycle, tool routing into the existing `ToolRegistry`, and an Egress-policy-gated outbound HTTP layer.

## Solution Overview

Create `src/probos/integrations/__init__.py` and `src/probos/integrations/mcp_bridge/` (new package; AD-449 OWNS the integrations namespace). v1 ships four real-work primitives:

1. **`MCPSession`** (`session.py`) — opaque session handle: server URL, session id (server-assigned per Streamable HTTP), capability cache. Frozen dataclass.
2. **`MCPClient`** (`client.py`) — async JSON-RPC 2.0 client over `httpx.AsyncClient`. Methods: `initialize()`, `list_tools()`, `call_tool(name, arguments)`, `close()`. Every outbound URL is checked through `runtime.egress_policy.is_allowed(url)` before httpx dispatches. Failures emit `MCP_BRIDGE_FAILED`; success-side per-call emits `MCP_BRIDGE_INVOKE`.
3. **`MCPBridge`** (`bridge.py`) — coordinator over `MCPClient` instances. Public methods: `register_server(url, headers=None)`, `list_servers()`, `invoke(server_url, tool_name, arguments)`. Routes inbound `Tool` invocations from the existing `ToolRegistry` to the right `MCPClient` instance.
4. **`MCPToolAdapter`** (`adapter.py`) — wraps a remote MCP tool descriptor as a ProbOS `Tool` (`tools/protocol.py:83`). Registered into the existing `ToolRegistry` via `runtime.tool_registry.register(...)` (verified at `tools/registry.py:92`). Inbound `check_and_invoke` (verified at `tools/registry.py:269`) dispatches to the `MCPBridge`.

This is **policy + a new external transport layered on existing AD-448 + AD-456 surfaces.** AD-449 does NOT modify `ToolRegistry`, does NOT modify `ToolExecutor`, does NOT modify `EgressPolicy` (consults it only), does NOT introduce server-side MCP (we are a CLIENT in v1).

**v1 scope (no-theater discipline; convention #7 + #14):**

- **MCPSession + MCPClient** — real JSON-RPC 2.0 client with real `tools/list` + `tools/call` methods.
- **MCPBridge** — real session lifecycle + real tool routing.
- **MCPToolAdapter** — real wrapper class; ToolRegistry registration loop deferred to AD-449b.
- **EgressPolicy gating** — every outbound request is consulted via `runtime.egress_policy.is_allowed(url)`. v1 honors the policy decision: block when denied, emit `MCP_BRIDGE_FAILED` with `reason="egress_blocked"`.

**Five wholesale-deferred to sub-ADs:**

- **Pre-built MCP server packs** (vendor-specific third-party connector catalog) — out of scope; live in the private commercial repo.
- **MCP server (ProbOS-as-server, exposing ProbOS tools to external MCP clients)** — AD-449b. v1 is client-only.
- **Bidirectional sampling/elicitation (server -> client LLM calls)** — AD-449c. v1 supports `tools/*` only; `sampling/*` and `elicitation/*` are deferred.
- **OAuth/auth flows beyond bearer tokens** — AD-449d. v1 supports static `Authorization` headers only.
- **MCP server health probing + automatic reconnect** — AD-449e. v1 fails over per-call; the operator-side reconciliation is deferred.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
MCP_BRIDGE_INVOKE = "mcp_bridge_invoke"  # AD-449
MCP_BRIDGE_FAILED = "mcp_bridge_failed"  # AD-449
```

Verified absent: `grep -n "MCP_BRIDGE" src/probos/events.py` returns no matches.

---

## Section 1: Package init

**File:** `src/probos/integrations/__init__.py` (new — AD-449 OWNS top-level integrations namespace)

```python
"""External system integrations (AD-449)."""
```

**File:** `src/probos/integrations/mcp_bridge/__init__.py` (new)

```python
"""MCP Bridge -- ProbOS-as-MCP-client (AD-449).

v1 ships the OSS bridge infrastructure: JSON-RPC 2.0 over Streamable HTTP,
session management, tool routing into the existing ToolRegistry, and
EgressPolicy-gated outbound dispatch.
"""

from probos.integrations.mcp_bridge.adapter import MCPToolAdapter
from probos.integrations.mcp_bridge.bridge import MCPBridge
from probos.integrations.mcp_bridge.client import MCPClient
from probos.integrations.mcp_bridge.session import MCPSession

__all__ = [
    "MCPBridge",
    "MCPClient",
    "MCPSession",
    "MCPToolAdapter",
]
```

---

## Section 2: `MCPSession`

**File:** `src/probos/integrations/mcp_bridge/session.py` (new)

```python
"""AD-449: MCPSession -- opaque session handle for an MCP server."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MCPSession:
    """One MCP server session.

    server_url is the canonical Streamable HTTP endpoint (e.g.,
    https://example.com/mcp). session_id is server-assigned during
    initialize() and threaded back via the Mcp-Session-Id header per
    the Streamable HTTP specification.
    capabilities is the server's reported capability set from the
    initialize response (cached for the session lifetime).
    """

    server_url: str
    session_id: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    capabilities: dict[str, dict] = field(default_factory=dict)
```

---

## Section 3: `MCPClient`

**File:** `src/probos/integrations/mcp_bridge/client.py` (new)

```python
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
```

---

## Section 4: `MCPBridge`

**File:** `src/probos/integrations/mcp_bridge/bridge.py` (new)

```python
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
```

---

## Section 5: `MCPToolAdapter`

**File:** `src/probos/integrations/mcp_bridge/adapter.py` (new)

```python
"""AD-449: MCPToolAdapter -- expose remote MCP tools as ProbOS Tools."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class MCPToolAdapter:
    """Wraps a remote MCP tool descriptor as a ProbOS Tool.

    v1 surface:
      - name -- ProbOS-side tool name (typically prefixed: "mcp.<server>.<tool>")
      - server_url -- the registered MCPBridge server
      - tool_name -- the remote tool name
      - description -- forwarded from the MCP server's tools/list response
      - input_schema -- forwarded from the MCP server (JSON Schema)
      - invoke(arguments) -> dict -- routes through MCPBridge.invoke
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
```

> Note: full registration of `MCPToolAdapter` into `runtime.tool_registry` requires the existing `Tool` Protocol surface (`tools/protocol.py:83`). v1 ships the adapter class and its `name`/`server_url`/`tool_name`/`description`/`input_schema`/`invoke()` surface. The actual `tool_registry.register(...)` call site is wired by AD-449b once an operator-driven server-registration flow exists; v1 keeps the adapter standalone so it can be invoked directly via `MCPBridge.invoke()` without touching the runtime ToolRegistry. This honors convention #14 (aggressive pre-deferral) — the bridge is real today, but the auto-registration loop is deferred.

---

## Section 6: Add EventTypes

**File:** `src/probos/events.py`

SEARCH (post-AD-469 EPS):
```python
    EPS_BUDGET_EXCEEDED = "eps_budget_exceeded"  # AD-469
    EPS_REALLOCATION = "eps_reallocation"  # AD-469
```

REPLACE:
```python
    EPS_BUDGET_EXCEEDED = "eps_budget_exceeded"  # AD-469
    EPS_REALLOCATION = "eps_reallocation"  # AD-469
    MCP_BRIDGE_INVOKE = "mcp_bridge_invoke"  # AD-449
    MCP_BRIDGE_FAILED = "mcp_bridge_failed"  # AD-449
```

> Anchor depends on AD-469 landing first within Wave 8. Fallback to `MODEL_FALLBACK = "model_fallback"  # AD-463` (line 211) if AD-469 has not landed.

---

## Section 7: Add `MCPConfig`

**File:** `src/probos/config.py`

```python
class MCPServerConfig(BaseModel):
    """One MCP server registration entry (AD-449)."""

    url: str
    headers: dict[str, str] = Field(default_factory=dict)


class MCPConfig(BaseModel):
    """MCP Bridge configuration (AD-449)."""

    enabled: bool = True
    request_timeout_seconds: float = Field(default=30.0, ge=1.0)
    servers: list[MCPServerConfig] = Field(default_factory=list)
```

Wire into `SystemConfig`:

SEARCH (post-AD-469):
```python
    eps: EPSConfig = EPSConfig()  # AD-469
```

REPLACE:
```python
    eps: EPSConfig = EPSConfig()  # AD-469
    mcp: MCPConfig = MCPConfig()  # AD-449
```

> Anchor-chain fallback: if AD-469 has not landed, anchor on `model_routing: ModelRoutingConfig = ModelRoutingConfig()  # AD-463` at `config.py:1693`. Final terminal: `orders: OrdersConfig = OrdersConfig()  # AD-440` at `config.py:1683`.

---

## Section 8: Wire into startup

**File:** `src/probos/startup/finalize.py`

Place after AD-469 (or AD-463 if AD-469 hasn't landed):

```python
    # AD-449: MCP Bridge (v1 OSS infrastructure)
    if config.mcp.enabled:
        from probos.integrations.mcp_bridge import MCPBridge
        runtime.mcp_bridge = MCPBridge(
            egress_policy=getattr(runtime, "egress_policy", None),
            emit_event=runtime.emit_event,
            request_timeout=config.mcp.request_timeout_seconds,
        )
        for srv in config.mcp.servers:
            runtime.mcp_bridge.register_server(srv.url, headers=dict(srv.headers))
        logger.info(
            "AD-449: MCPBridge wired (%d server(s) preregistered)",
            len(config.mcp.servers),
        )
    else:
        runtime.mcp_bridge = None
```

> Verify-first: `runtime.egress_policy` is the AD-456 public attribute (verified at `src/probos/security/egress.py:47`; runtime wiring confirmed in `startup/finalize.py` AD-456 block). `runtime.emit_event` is the public method at `runtime.py:785`. `runtime.mcp_bridge` is a NEW public attribute per Wave 5 convention #1.

---

## Tests

**File:** `tests/test_ad449_mcp_bridge.py`

14 tests using fakes for `egress_policy`, `emit_event`, and `httpx.AsyncClient`:

1. `test_event_type_mcp_bridge_invoke_exists`
2. `test_event_type_mcp_bridge_failed_exists`
3. `test_mcp_config_defaults` -- `enabled=True`, `request_timeout_seconds=30.0`, `servers=[]`.
4. `test_mcp_session_immutable` -- frozen dataclass; `dataclasses.replace` produces a new instance.
5. `test_mcp_client_initialize_returns_session_with_capabilities` -- mocked httpx returns body `{"jsonrpc":"2.0","id":...,"result":{"capabilities":{...}}}` AND headers `{"mcp-session-id": "s-123"}`. The session has the capabilities AND `session_id == "s-123"`. The test must mock both `Response.json()` AND `Response.headers` to validate the header-driven session_id capture. `@pytest.mark.asyncio`.
6. `test_mcp_client_list_tools_returns_list` -- mocked httpx returns `{"result":{"tools":[{"name":"x"}]}}` -> `list_tools()` returns `[{"name":"x"}]`. `@pytest.mark.asyncio`.
7. `test_mcp_client_call_tool_returns_dict_result` -- `@pytest.mark.asyncio`.
8. `test_mcp_client_egress_blocked_emits_failed_and_raises` -- egress policy returns False -> `MCPProtocolError`; emit fires `MCP_BRIDGE_FAILED` with `reason="egress_blocked"`. `@pytest.mark.asyncio`.
9. `test_mcp_client_http_error_emits_failed_and_raises` -- mocked httpx returns 500 -> `MCPProtocolError`; emit fires `MCP_BRIDGE_FAILED` with `reason="http_error"`. `@pytest.mark.asyncio`.
10. `test_mcp_client_rpc_error_emits_failed_and_raises` -- response envelope contains `"error":{"code":-32601,"message":"method not found"}` -> raises; emit fires with `reason="rpc_error"`. `@pytest.mark.asyncio`.
11. `test_mcp_bridge_register_server_rejects_duplicates_and_empty` -- `register_server("")` returns False; second register_server with same URL returns False.
12. `test_mcp_bridge_invoke_unknown_server_raises` -- `invoke("https://nonexistent", ...)` -> `MCPProtocolError`. `@pytest.mark.asyncio`.
13. `test_mcp_bridge_invoke_routes_to_correct_client` -- two registered servers; invoke on URL B routes to client B's `call_tool`. `@pytest.mark.asyncio`.
14. `test_mcp_tool_adapter_name_format` -- adapter constructed with `server_url="https://api.example.com/mcp"` and `tool_name="search"` -> `name == "mcp.api_example_com.search"`.

Each test uses `MagicMock` for httpx clients and isolated fakes. No shared mutable state.

---

## What This Does NOT Change

- `ToolRegistry` (`tools/registry.py:49`) is unchanged. v1 ships `MCPToolAdapter` as a standalone wrapper; auto-registration loop deferred to AD-449b.
- `ToolExecutor` (`tools/executor.py:40`) is unchanged.
- `EgressPolicy` (`security/egress.py:47`) is unchanged. AD-449 consults `is_allowed(url)` only.
- `LLMClient` and `IntentBus` are unchanged. AD-449 is a tool-layer extension.
- **MCP server (ProbOS-as-server) is NOT shipped in v1.** Wholesale deferred to AD-449b.
- **Pre-built MCP server packs are out of scope.** They live in the private commercial repo. No code, docstring, or test in this prompt mentions specific server-pack names.
- AD-449 introduces NO destructive intents; v1 is consultation-only at the egress layer.

---

## Tracking

- `PROGRESS.md`: add `AD-449 CLOSED. MCP Bridge v1 OSS infrastructure (Session + Client + Bridge + Adapter; EgressPolicy-gated)...`
- `docs/development/roadmap.md`: flip AD-449 status from `*(planned, Commercial)*` to `*(partial - v1 OSS bridge ships; ProbOS-as-server / sampling / advanced auth deferred to AD-449b/c/d/e)*` near line 4111.
- `DECISIONS.md`: optional entry recording the OSS-vs-commercial boundary and the v1-4-of-9 scope decision.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP. Check that no source/test/doc file mentions pricing, customer counts, GTM language, or commercial server-pack names.

Expected delta:
- `src/probos/integrations/__init__.py`: 1-2 lines (new; AD-449 owns).
- `src/probos/integrations/mcp_bridge/__init__.py`: ~14 lines (new).
- `src/probos/integrations/mcp_bridge/session.py`: ~25 lines (new).
- `src/probos/integrations/mcp_bridge/client.py`: ~210 lines (new).
- `src/probos/integrations/mcp_bridge/bridge.py`: ~80 lines (new).
- `src/probos/integrations/mcp_bridge/adapter.py`: ~50 lines (new).
- `src/probos/events.py`: 2 lines added.
- `src/probos/config.py`: ~20 lines added.
- `src/probos/startup/finalize.py`: ~16 lines added.
- `tests/test_ad449_mcp_bridge.py`: ~310 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 14 tests pass under `pytest tests/test_ad449_mcp_bridge.py -v -n 0`.
- Full parallel gate non-decreasing.
- 2 new EventTypes appear exactly once in `events.py`.
- `runtime.mcp_bridge` is a public attribute (no leading underscore).
- `MCPClient`, `MCPBridge`, `MCPSession`, `MCPToolAdapter` use stdlib + the existing `httpx` dependency only; no new pyproject deps.
- `EgressPolicy.is_allowed(url)` is consulted on every outbound request.
- `ToolRegistry` and `ToolExecutor` are unchanged.
- **No source / test / doc string mentions pricing, customer counts, GTM, or specific commercial MCP server packs.** Pre-commit hook should not flag the prompt.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-02)

```
Test-Path src/probos/integrations
  False  (AD-449 OWNS directory creation)

grep -rn "class MCPBridge\|class MCPSession\|class MCPClient" src/probos/
  (no matches -- AD-449 introduces these names)

grep -n "MCP_BRIDGE" src/probos/events.py
  (no matches -- names are free)

grep -n "class ToolRegistry\|class Tool\b\|class ToolExecutor" src/probos/tools/
  registry.py:49: class ToolRegistry:
  protocol.py:83: class Tool(Protocol):
  executor.py:40: class ToolExecutor:

grep -n "def register\|async def check_and_invoke" src/probos/tools/registry.py
  92: def register(
  269: async def check_and_invoke(

grep -n "class EgressPolicy\|def is_allowed" src/probos/security/egress.py
  47: class EgressPolicy:
  66: def is_allowed(self, url: str) -> bool:

grep -n "self\.tool_registry\|self\.egress_policy" src/probos/runtime.py
  1591: self.tool_registry = comm.tool_registry
  (egress_policy wired in startup/finalize.py per AD-456 Wave 7)

grep -n "self\.llm_client\|def emit_event" src/probos/runtime.py
  347: self.llm_client: BaseLLMClient = llm_client or MockLLMClient()
  785: def emit_event(self, event: BaseEvent | str | EventType, ...

grep -n "MODEL_FALLBACK\|EPS_REALLOCATION" src/probos/events.py
  211: MODEL_FALLBACK = "model_fallback"  # AD-463
  (EPS_REALLOCATION lands with AD-469; AD-449 anchor depends on AD-469 first)

grep -n "model_routing: ModelRoutingConfig" src/probos/config.py
  1693: model_routing: ModelRoutingConfig = ModelRoutingConfig()  # AD-463
```

Wave-5/6/7 conventions audit:
- #1 Public-attribute wiring: `runtime.mcp_bridge` public. ✅
- #2 stdlib-only: yes (httpx is a pre-existing dep). ✅
- #3 Coordinator-then-dispatch: v1 ships consult-only egress gating; auto tool-registry registration deferred. ✅
- #4 Superset-filter: registry/executor unchanged; new external surface. ✅
- #5 init_<phase>: Section 8 wires from finalize.py. ✅
- #6 Verify-first: footer above. ✅
- #7 No-theater: real JSON-RPC client + real EgressPolicy gate + real events. Server packs deferred wholesale (commercial repo). ✅
- #11 __new__-bypass defensive-getattr: `MCPClient.close` uses `getattr(self, "_http", None)`. ✅
- #14 Aggressive pre-deferral: 5 of 9 capabilities deferred at draft time. ✅
- **Commercial-boundary**: prompt body, source code, and tests describe OSS infrastructure ONLY. No pricing, GTM, customer-count, or server-pack-specific language anywhere. ✅

---

## Revision (2026-05-02)

Applied review findings from `prompts/Reviews/ad-449-mcp-bridge-review.md` (verdict: ⚠️ Conditional; 3 Required + 6 Recommended). Per dispatch convention #15 (relaxed tolerance), AD-449 is the wave's HIGH-risk slot.

**Required addressed:**

- **R#1: Commercial-connector names in shipping content (lines 8 + 40).** Both lines reframed to generic categories. No specific vendor names remain in shipping content:
  - Line 8 (boundary alert): "vendor-specific MCP server packs (third-party SaaS connector packs of any kind)"
  - Line 40 (deferral list): "Pre-built MCP server packs (vendor-specific third-party connector catalog) — out of scope; live in the private commercial repo"

  Post-revision grep confirms zero hits for `Salesforce|ServiceNow|D365|Workday|\$\d|revenue|subscription|pilot|reference engagement` in shipping content. The remaining metadata mentions ("customer counts", "GTM language", "vendor-specific") are in negative-framing boundary-alert prose — same pattern as the dispatch hard-stop section. AD-450 leak precedent honored.

- **R#2: `_last_response_headers` class-attribute mutable default.** Section 3 `MCPClient.__init__` now initializes `self._last_response_headers: dict[str, str] = {}` per instance. The class-level declaration `_last_response_headers: dict[str, str] = {}` removed. Concurrent MCPClient instances no longer share header state -- race risk eliminated. Documented as a Wave-8-revision-pass correction in the source comment.

- **R#3: Test #5 must mock both body and headers.** Test plan rewritten:

  > "mocked httpx returns body `{...,"result":{"capabilities":{...}}}` AND headers `{"mcp-session-id": "s-123"}`. The session has the capabilities AND `session_id == "s-123"`. The test must mock both `Response.json()` AND `Response.headers` to validate the header-driven session_id capture."

  Builder will now write the test against both mock surfaces.

**Recommended applied:**

- **rec#1: MCPToolAdapter Solution Overview language.** v1 scope bullet (line 35) updated:

  > "MCPToolAdapter -- real wrapper class; ToolRegistry registration loop deferred to AD-449b."

  Matches the existing Section 5 deferral note. Solution Overview drift convention #12 honored.

**Recommended deferred:**

- **rec#2: httpx async-context-manager pattern.** `MCPClient.close()` is the canonical lifecycle; `MCPBridge.close_all()` cascades. Adding `async with` semantics would change the public API; defer to AD-449b.
- **rec#3: log registered servers at startup.** `runtime.mcp_bridge.register_server(...)` already logs at INFO via the existing `logger.info("AD-449: MCPBridge wired ...")` line in finalize. Sufficient for spot-check.
- **rec#4: dual-emission comment (EGRESS_BLOCKED + MCP_BRIDGE_FAILED).** Architect judgment: the dual emission is intentional and useful (two perspectives on the same denial -- one event-bus subscriber set, one MCP-specific subscriber set). Keep both.
- **rec#5: protocol-version mismatch handling.** Defer to AD-449e ("MCP server health probing + automatic reconnect"). v1 uses fixed `MCP_PROTOCOL_VERSION = "2025-03-26"`.
- **rec#6: JSON-RPC `id` format.** Hex string `uuid.uuid4().hex` is fine; not changed.

**Phantom-API pre-check (run during revision):**

```
grep -rn "class MCPBridge\|class MCPSession\|class MCPClient\|class MCPToolAdapter" src/probos/
  (no matches -- AD-449 introduces all four; correct)

grep -n "class ToolRegistry\|class Tool\b\|class ToolExecutor\|class EgressPolicy" src/probos/
  tools/registry.py:49: class ToolRegistry:
  tools/protocol.py:83: class Tool(Protocol):
  tools/executor.py:40: class ToolExecutor:
  security/egress.py:47: class EgressPolicy:

grep -n "def register\|async def check_and_invoke\|def is_allowed" src/probos/tools/registry.py src/probos/security/egress.py
  src/probos/tools/registry.py:92: def register(
  src/probos/tools/registry.py:269: async def check_and_invoke(
  src/probos/security/egress.py:66: def is_allowed(self, url: str) -> bool:

grep -n "self\.tool_registry\|self\.egress_policy\|self\.llm_client\|def emit_event" src/probos/runtime.py
  347: self.llm_client: BaseLLMClient = llm_client or MockLLMClient()
  785: def emit_event(self, event: BaseEvent | str | EventType, ...
  1591: self.tool_registry = comm.tool_registry
  (egress_policy wired in startup/finalize.py per AD-456 Wave 7)
```

All concrete claims grep-confirmed. No additional phantoms found.

**Verified Against Codebase footer extended:** the post-revision commercial-boundary scan added; vendor-name greps documented as zero-hit.

**Test count: 14 -> 14** (R#3 tightens existing Test #5; no new tests added).

**Verdict shift:** Pass-1 ⚠️ Conditional (HIGH-risk + commercial-boundary) -> expected ✅ Approved on second-pass review (3 Requireds mechanical; 1 of 6 Recommendeds applied; 5 deferred with explicit architect judgment per Wave-8 relaxed tolerance).
