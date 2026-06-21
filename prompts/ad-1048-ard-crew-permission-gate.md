# AD-1048 — Crew-agent permission gate for ARD resources ("if permitted")

**Epic:** ARD Integration (`docs/development/ard-integration.md`) · **Phase 3, Step 3**
**Issue:** #998 · **Epic:** #989 · **Target repo:** OSS (`d:\ProbOS`)
**Depends on:** AD-1046 (client) · **Blocks:** AD-1049 (adoption)
**Verification status:** ⚠ DRAFT — re-verify file refs against HEAD at build time. Reuses the **AD-1019** pattern — confirm `resolve_mcp_access` ([integrations/mcp_bridge/access.py](src/probos/integrations/mcp_bridge/access.py)) + `ToolPermissionStore` (AD-423b/894) signatures at build time.

## Objective

The literal **"if permitted"** requirement: gate *which crew agents* may use *which ARD-discovered resources/tools*, reusing the audited `ToolPermissionStore` — **no new grant store** — via composite ids. ARD resources are **opt-in per agent**: unusable by a crew agent until explicitly permitted.

## Why

The user's directive: "allow crew agents *if permitted* to use tools and skills from ARD catalogs." ProbOS already solved exactly this shape for MCP in AD-1019 (`resolve_mcp_access`, server-level `mcp:{name}` + tool-level `mcp:{name}:{tool}`, precedence tool>server, restriction>grant, opt-in). This AD mirrors it for ARD so the governance model is identical and the operator UI pattern (AD-1019a) transfers.

## Build

1. **Composite-id scheme** (mirror AD-1019):
   - Catalog-level: `ard:{catalog}` (all resources from a registered catalog).
   - Resource-level: `ard:{catalog}:{resource}` (one discovered resource).
   - Tool-level: `ard:{catalog}:{resource}:{tool}` (one tool on a discovered MCP server).
2. **New pure `federation/ard/access.py`** — `resolve_ard_access(grants, catalog, resource, tool=None) -> (enabled, source)` mirroring `resolve_mcp_access`:
   - Precedence: tool-restriction → tool-grant → resource-restriction → resource-grant → catalog-restriction → catalog-grant → `(False, "default")`.
   - **Opt-in per agent** (default `False`); restriction beats grant; tool overrides resource overrides catalog.
3. **Reuse `ToolPermissionStore`** for the grants (the audited trail) — no new store. Grants issued with the `ard:` composite id.
4. **Endpoints** mirroring AD-1019's `routers/mcp_servers.py` access surface, gated on `federation.ard.enabled`:
   - `GET /api/ard/{catalog}/agents/{agent_id}` — per-resource resolved enablement for an agent.
   - `POST/DELETE` per-(agent, resource|tool|catalog) grant/restriction via `ToolPermissionStore`.
5. **Enforcement is wired in AD-1049** (origination point); this AD ships the resolver + grant surface + tests. (Same split as AD-1019 substrate vs AD-1019b enforcement.)

## Acceptance criteria

- `resolve_ard_access` exhaustive precedence: tool>resource>catalog; restriction>grant; default `(False,"default")`.
- A resource-grant enables all its tools unless a tool-restriction overrides; a catalog-restriction caps everything under it unless a narrower grant overrides.
- Grants persist via `ToolPermissionStore` (audited); `GET …/agents/{id}` reflects resolved state + `source`.
- Disabled → 404.
- Tests `tests/test_ad1048_ard_access.py` (BF-287: **real `ToolPermissionStore`**, real resolver — no MagicMock at the store boundary): every precedence branch + opt-in default + endpoint shapes.
- Verify compliance with `.github/copilot-instructions.md`.

## Do NOT build

- No new grant store — reuse `ToolPermissionStore`.
- No adoption/connect (AD-1049) — this is the resolver + grant surface only.
- No HXI panel yet (a later UI AD, mirroring AD-1019a — named, not built).
- Default opt-in-off; `config/system.yaml` untouched.
