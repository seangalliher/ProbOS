# AD-449 Build Report — MCP Bridge v1 OSS Infrastructure

**Status:** CLOSED  
**Commit:** (pending; this report finalized pre-commit)  
**Wave:** 8 (final prompt; commercial-boundary discipline)

## Summary

Shipped the OSS MCP (Model Context Protocol) bridge infrastructure as a new top-level package `probos.integrations.mcp_bridge`. Provides session-managed JSON-RPC 2.0 over Streamable HTTP for ProbOS agents to invoke external MCP servers. Egress is gated by `runtime.egress_policy` before any network issuance.

## What Shipped (v1)

- `MCPSession` — frozen dataclass (`server_url`/`session_id`/`headers`/`capabilities`); immutable via `dataclasses.replace`.
- `MCPClient` — `httpx.AsyncClient`-based JSON-RPC 2.0 client. Public API: `initialize()`, `list_tools()`, `call_tool(name, args)`. Captures `Mcp-Session-Id` from response headers via instance-level `self._last_response_headers` (NOT class-level — race fix per Wave 8 review).
- `MCPBridge` — multi-server registry. `register_server(url)` rejects empty/duplicate URLs; `invoke(server_url, tool, args)` routes to per-server `MCPClient`; raises `MCPProtocolError` on unknown server.
- `MCPToolAdapter` — `mcp.<sanitized_host>.<tool>` name format via `urllib.parse.urlparse`; `__call__` proxies to bridge.
- 2 new EventTypes: `MCP_BRIDGE_INVOKE`, `MCP_BRIDGE_FAILED` (with `reason ∈ {egress_blocked, http_error, rpc_error}`).
- `MCPConfig` + `MCPServerConfig` (Pydantic) on `SystemConfig.mcp`.
- Public attribute `runtime.mcp_bridge` wired in `startup/finalize.py` after `runtime.eps_coordinator`.

## Commercial Boundary

OSS bridge infrastructure only. Vendor-specific MCP server packs live in the private commercial repo entirely. Source + tests scrubbed for vendor names and pricing patterns — zero hits.

## Deferred (per Solution Overview)

- AD-449b: ProbOS-as-MCP-server (Tool Registry registration via SkillCatalog).
- AD-449c: MCP `sampling/createMessage` callback.
- AD-449d: OAuth 2.1 + Dynamic Client Registration + dynamic scope.
- AD-449e: Multi-tenant audit + observability extensions.

## Verify-First Anchors

- `events.py` after `EPS_REALLOCATION` (line ~end of EventType enum) — anchor stable from AD-469.
- `config.py` `MCPConfig` placed AFTER `EPSConfig` block; `SystemConfig.mcp` field added.
- `startup/finalize.py` mcp wiring added after `runtime.eps_coordinator` else branch.
- Real method `runtime.egress_policy.is_allowed(url)` verified at `security/egress.py` (AD-456).

## Tests

`tests/test_ad449_mcp_bridge.py`: 14 tests, all pass at `-n 0`. Coverage:

- 2 EventType existence + value asserts.
- 1 `MCPConfig` defaults.
- 1 `MCPSession` immutability via `dataclasses.replace`.
- 6 `MCPClient`: initialize-with-capabilities (mocks both body + headers per Wave 8 review Required #3), list_tools, call_tool, egress-blocked emit+raise, http-error emit+raise, rpc-error emit+raise.
- 3 `MCPBridge`: register_server reject-empty/duplicate, invoke unknown raises, invoke routes to correct client.
- 1 `MCPToolAdapter` name format `mcp.api_example_com.search`.

## Gates

- Focused (`-n 0`): 14/14 pass in 0.48s.
- Full parallel (`-n 8 --dist=loadfile`): **10,551 passed**, 15 skipped, 405.85s. Delta vs pre-AD-449 (10,537): **+14**.

## Convention adherence

- Convention #6 (verify-first): All claims in prompt body grepped before write.
- Convention #7 (no theater): ToolRegistry registration genuinely deferred — `MCPToolAdapter.__call__` works real today.
- Convention #9 (ASCII-only source comments): all source files use ASCII comments.
- Convention #11 (`getattr(self, "_runtime", None)` for __new__-bypass tests): not applicable (no runtime indirection in client/bridge — they accept dependencies as constructor kwargs).
- Convention #13 (kw-only optional injection): `MCPClient(*, session, http_client=None, egress_policy=None, emit_event=None)` and `MCPBridge(*, http_client=None, egress_policy=None, emit_event=None)`.
- Wave 8 second-pass Required #3: `_last_response_headers` is instance attribute, initialized in `__init__`.
- Wave 8 second-pass Required (commercial): zero vendor names in shipping content.

## Files

**New:**
- `src/probos/integrations/__init__.py`
- `src/probos/integrations/mcp_bridge/__init__.py`
- `src/probos/integrations/mcp_bridge/session.py`
- `src/probos/integrations/mcp_bridge/client.py`
- `src/probos/integrations/mcp_bridge/bridge.py`
- `src/probos/integrations/mcp_bridge/adapter.py`
- `tests/test_ad449_mcp_bridge.py`

**Modified:**
- `src/probos/events.py` (+2 EventTypes)
- `src/probos/config.py` (+MCPConfig +MCPServerConfig +SystemConfig.mcp)
- `src/probos/startup/finalize.py` (+mcp wiring block)
- `PROGRESS.md` (CLOSED entry prepended)
- `docs/development/roadmap.md` (line 4111 status flip)

## Hard-stop check

No hard-stops triggered. No tracked working-tree changes outside the prompt's stated scope. Pre-commit deletion sanity check pending in next step.
