# AD-1019 — per-agent + per-tool MCP enablement (backend substrate)

**Track:** GitHub #960 (epic #955). **Highest AD: AD-1018 → this is AD-1019.** Backend + API only — HXI is AD-1019a; MCP-tool invocation wiring is AD-1019b.

## Goal
Agents can be **enabled to use** an MCP server, with **per-tool** granularity (enable/disable individual tools the server exposes). Reuse the audited `ToolPermissionStore` with composite ids — no new grant store. This is the authorization + enumeration substrate (MCP tools aren't agent-callable yet; like `IntentGrantStore` was built before enforcement).

## Verified references
- `ToolPermissionStore` ([permissions.py](src/probos/tools/permissions.py)): `async issue_grant(agent_id, tool_id, permission: ToolPermission, *, is_restriction=False, reason="", issued_by="captain") -> ToolAccessGrant`; `async revoke_grant(grant_id) -> bool`; `get_active_grants_sync(agent_id, tool_id=None) -> list[ToolAccessGrant]` (grant has `.id`/`.tool_id`/`.permission`/`.is_restriction`). `runtime.tool_permission_store`.
- `ToolPermission` ([protocol.py:29](src/probos/tools/protocol.py#L29)): `NONE/OBSERVE/READ/WRITE/FULL`.
- Per-agent grant API to mirror: `/api/crew/{agent_id}/tools` GET/POST ([crew.py:367](src/probos/routers/crew.py#L367)).
- `MCPClient.list_tools()` (AD-1014) via `runtime.mcp_bridge.get_client(key)`; `_bridge_key(record)` = url(http)/name(stdio) ([mcp_servers.py:104](src/probos/routers/mcp_servers.py#L104)).
- AD-1015 `McpServerStore` (`runtime.mcp_server_store`), `routers/mcp_servers.py` (gated on `config.mcp.management_enabled`).

## Build (all in `routers/mcp_servers.py` + a small pure helper)

### Composite-id scheme + resolution
- Server-level: `tool_id = f"mcp:{server_name}"` (all tools).
- Tool-level: `tool_id = f"mcp:{server_name}:{tool_name}"`.
- Pure helper `resolve_mcp_access(grants: list[ToolAccessGrant], server_name: str, tool_name: str) -> tuple[bool, str]` returning `(enabled, source)` where source ∈ `{"tool","server","default"}`:
  - active **tool-level restriction** (is_restriction, id `mcp:{s}:{t}`) → `(False, "tool")`.
  - active **tool-level grant** → `(True, "tool")`.
  - active **server-level restriction** → `(False, "server")`.
  - active **server-level grant** → `(True, "server")`.
  - else → `(False, "default")` (MCP is opt-in per agent).
  (Tool-level overrides server-level; restriction beats grant at the same level.) Pure, no I/O — unit-testable. Place it in `mcp_bridge/store.py` (next to `validate_record`) or a small `mcp_bridge/access.py` — Builder's call.

### Endpoints (gated `management_enabled` → 404 when off; honest-degrade → 503/empty)
- `GET /api/mcp/servers/{id}/tools` → resolve record → `bridge.get_client(_bridge_key(record))` → `await client.list_tools()` → `{tools: [{name, description}], count}`. Not registered/connected → `{tools: [], count: 0, error: "..."}` (never 500).
- `GET /api/mcp/servers/{id}/agents/{agent_id}/access` → enumerate the server's tools (as above) + `grants = perms.get_active_grants_sync(agent_id)` → `{server_enabled: bool (resolve at server scope), tools: [{name, enabled, source}]}` via `resolve_mcp_access` per tool.
- `POST /api/mcp/servers/{id}/agents/{agent_id}` body `{enabled: bool, tool?: str}` → `tool_id = f"mcp:{name}"` (no tool) or `f"mcp:{name}:{tool}"` → `perms.issue_grant(agent_id, tool_id, permission=ToolPermission.WRITE if enabled else ToolPermission.NONE, is_restriction=not enabled, reason="mcp enablement")`. 503 if no perm store. Returns the grant id.
- `DELETE /api/mcp/servers/{id}/agents/{agent_id}?tool=` → find the active grant for the composite id (`get_active_grants_sync(agent_id, tool_id)`), `revoke_grant(grant.id)` for each; returns `{revoked: n}`.

## Tests — `tests/test_ad1019_mcp_enablement.py`
BF-287: real `McpServerStore` + real `ToolPermissionStore` (db_path="") + real `MCPBridge` + the AD-1014 echo fixture + real `TestClient`.
- `resolve_mcp_access` pure: tool-restriction beats server-grant; tool-grant enables; server-grant enables all; server-restriction disables; default disabled; tool-level overrides server-level (all 6+ branches).
- `GET /tools` enumerates the echo fixture's tools; honest-degrade when not connected (`{tools:[], error}`).
- `POST` server-level → `GET /access` shows all tools enabled (source "server"); `POST` tool-level disable → that tool `enabled:false` source "tool", others still enabled; `DELETE` reverts to default.
- Grants recorded in the real `ToolPermissionStore` (assert via `get_active_grants_sync`).
- `management_enabled=False` ⇒ the new endpoints 404.
- Parity: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "mcp or ad1015 or ad1017 or permission or ad894" -q -n 0 -p no:cacheprovider` green (AD-894 + AD-1015/1017 unchanged).

## Do NOT build
❌ HXI (AD-1019a). ❌ MCP-tool invocation wiring (AD-1019b). ❌ a new grant store (reuse `ToolPermissionStore`). ❌ secrets. ❌ change AD-894/AD-1015/AD-1017 behavior.

## Acceptance
All tests green; AD-894 + AD-1015/1017 unchanged; composite-id grants recorded in `ToolPermissionStore`; resolution correct (tool>server>default, restriction>grant); `management_enabled=False` ⇒ 404; full type annotations; async hygiene; **comply with `.github/copilot-instructions.md`.**
