# AD-1019a — HXI per-agent / per-tool MCP enablement surface

**Track:** GitHub #961 (epic #955). **Highest AD: AD-1019 → this is AD-1019a. UI ONLY — no backend changes.**

> Builder: implement against the verified endpoints below. The AD-1019 backend is shipped and these endpoints are live. Mirror the existing `McpServersPanel.tsx` + `ToolCertifications.tsx` patterns exactly.

## Endpoints (live, AD-1019 — verified)
- `GET /api/crew/roster` → crew agents (read `.agents`/list; each has `id` + display name — inspect the response shape in `crew.py:crew_roster` and mirror what `CrewPersonnelConsole`/`ServiceRecord` already consume).
- `GET /api/mcp/servers/{id}/tools` → `{tools:[{name,description}], count, error?}`.
- `GET /api/mcp/servers/{id}/agents/{aid}/access` → `{server_enabled:bool, tools:[{name,enabled,source}], error?}`, `source ∈ {tool,server,default}`.
- `POST /api/mcp/servers/{id}/agents/{aid}` body `{enabled:bool, tool?:string}` (omit `tool` = server-wide).
- `DELETE /api/mcp/servers/{id}/agents/{aid}?tool={name}` → `{revoked:N}` (omit `tool` = server-level).

## Build
1. **New `ui/src/components/mcp/McpAgentAccess.tsx`** — props `{ serverId: string; serverName: string; deps?: Partial<McpAgentAccessDeps> }`. `McpAgentAccessDeps`: `fetchRoster`, `fetchTools`, `fetchAgentAccess(agentId)`, `setAccess(agentId, {enabled, tool?})`, `clearAccess(agentId, tool?)` — each `_fn = deps?.x ?? apiX`, every `apiX` a real `fetch` (Vitest injects `vi.fn()`). On mount: fetch roster + tools. Per agent row: a **server-level tri-state** (enabled / disabled / default) toggle + an expander showing **per-tool** toggles (each tool's resolved `{enabled, source}` from `fetchAgentAccess`). Toggle → `setAccess` (enable `{enabled:true,tool?}` / disable `{enabled:false,tool?}`); **Reset to default** → `clearAccess(tool?)`. A small `source` badge per tool (`tool`/`server`/`default`) makes precedence legible. Re-fetch that agent's access after a mutate.
2. **Wire into `McpServersPanel.tsx`** — an expandable **"Agent access"** section per server row (a button that toggles a `<McpAgentAccess serverId=… serverName=… />` block). Keep `McpAgentAccess` self-contained so the panel diff is small.

## HXI discipline (HARD — these are review blockers)
- **No emoji.** Inline stroke-only SVG (`strokeWidth:1.5`, `strokeLinecap:"round"`), amber `#f0b060` active / dim `#666680` inactive. A test asserts no emoji (the repo has an `Extended_Pictographic` guard pattern — reuse it).
- Deps-injectable everywhere (no bare `fetch` in the component body that a test can't intercept).
- `data-testid`: `mcp-access-{serverName}-{agentId}` (server toggle), `mcp-access-expand-{serverName}-{agentId}`, `mcp-access-tool-{serverName}-{agentId}-{toolName}` (tool toggle), `mcp-access-reset-…`.
- Honest-degrade: any fetch failure → inline error text, never blank/crash; a 404 (management disabled) → "MCP management is disabled".

## Tests — `ui/src/components/mcp/McpAgentAccess.test.tsx` (Vitest, deps-injected)
Renders roster; server enable→`POST {enabled:true}`; server disable→`POST {enabled:false}`; tool enable→`POST {enabled:true,tool}`; tool disable→`POST {enabled:false,tool}`; reset→`DELETE ?tool=`; `source` badge reflects tool/server/default; fetch-failure honest-degrade; **no-emoji** assertion; management-disabled state. Plus a `McpServersPanel.test.tsx` case asserting the "Agent access" section mounts for an expanded server.

## Gates
- `cd ui; npx vitest run src/components/mcp` green.
- `cd ui; npm run build` clean.
- No backend file touched. Bridge+personnel+mcp UI regression unchanged.

## Do NOT
- ❌ Any backend/Python change. ❌ AD-1019b invocation enforcement. ❌ device-code UI. ❌ a Personnel-Console MCP tab (server-centric surface only this slice).

## Acceptance
All tests + build green; HXI no-emoji/SVG/deps-injectable/honest-degrade satisfied; section wired into the panel; **verify compliance with the Engineering Principles + HXI Design Principles in `.github/copilot-instructions.md`.**
