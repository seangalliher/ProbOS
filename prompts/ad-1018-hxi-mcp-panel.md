# AD-1018 — HXI MCP Servers management panel

**Track:** GitHub #959 (epic #955). **Highest AD: AD-1017 → this is AD-1018.** UI only — consume AD-1015/AD-1017 endpoints as-is.

## Verified integration facts (mirror ShipsLockerPanel + RolePicker)
- **Panel open pattern:** zustand `useStore` boolean flag (e.g. `shipsLockerOpen`); `const open = useStore((s) => s.mcpServersOpen)`; `close = () => useStore.setState({ mcpServersOpen: false })`. Panel rendered **unconditionally** in `ui/src/App.tsx` (alongside `<ShipsLockerPanel />` at ~L113) and returns `null` when `!open`. Add the `mcpServersOpen` flag to the store (find it: `git grep -n "shipsLockerOpen" -- ui/src`) + an Engineering-station action or a launcher to open it.
- **Deps-injectable fetch:** `function McpServersPanel({ deps }: { deps?: Partial<McpDeps> })`; each call defaults to a real `fetch` (mirror `ShipsLockerPanel`'s `_fetch = deps?.fetchCatalog ?? fetchCatalog`). This is what the Vitest tests inject.
- **HXI compliance (HARD):** inline SVG stroke icons (`strokeWidth:1.5`, `strokeLinecap:'round'`), amber active (`#f0b060`) / dim inactive (`#666680`), **NO emoji**, `data-testid` on every interactive element, Escape-to-close.
- **Tests:** Vitest, `vi.fn()`-injected deps, `@testing-library/react`. Run: `cd ui; npx vitest run src/components/mcp/McpServersPanel.test.tsx`. Build: `cd ui; npm run build`.

## Backend endpoints to consume (all under `/api/mcp/servers`, gated `management_enabled`)
- `GET ""` → `{servers:[{id,name,type,url,command,args,env,cwd,enabled,auth_kind,auth_header_name,auth_scheme,auth_env_var,oauth_json,timeout_seconds,...}], count}` (to_public_dict — NO secrets).
- `POST ""` (create) / `PUT /{id}` (edit) / `DELETE /{id}` (hard delete) / `POST /{id}/enable` / `POST /{id}/disable` / `POST /{id}/test` → `{ok,tool_count}|{ok:false,error}`.
- `POST /{id}/credential` `{value,header_name?,scheme?,env_var?}` (static) / `DELETE /{id}/credential`.
- `POST /{id}/auth/start` → `{auth_url,state}` / `GET /{id}/auth/callback` (popup hits this; returns postMessage close HTML) / `POST /{id}/auth/refresh`.

## Build — `ui/src/components/mcp/McpServersPanel.tsx`
1. **List**: a row per server — name, type badge (http/stdio), url/command summary, `enabled` toggle (→ enable/disable), `auth_kind` badge (none/static/oauth), a Test button (→ test, render `✓ N tools` in text/SVG, not emoji — use "OK · N tools" / "FAILED"). Empty state + feature-disabled state (honest-degrade: if `GET` 404s, show "MCP management is disabled" — mirror ShipsLockerPanel's degrade).
2. **Create/Edit form**: `type` selector → http (url + headers key/val rows) | stdio (command + args + env key/val + cwd); name; timeout. Client validation mirrors backend (kebab name; http⇒url; stdio⇒command). **No secret inputs here.**
3. **Credential modal** (opened from a row's "Auth" button): radio static|oauth.
   - static → token value (type=password, write-only) + header_name (default Authorization) + scheme (default Bearer) [+ env_var for stdio] → `putCredential`. After save, the token is NOT shown again (only "configured ✓" as text).
   - oauth → client_id/authorize_url/token_url/scopes/redirect_uri + client_secret (password) → save (PUT updates `oauth_json` + posts the secret), then a **"Connect" button** → `startOAuth` → `window.open(auth_url)` + `window.addEventListener('message', ...)` waiting for `{type:'oauth_complete'}` then refresh the list. A "Refresh token" affordance → `refreshOAuth`.
4. **Delete**: confirm prompt → `deleteServer`.
5. **Trust note**: for `type==='stdio'`, render a clear inline note "Runs a local command on this machine" before/near the enable toggle (Copilot trust-dialog ethos; backend HookBus is the enforcement).

## Tests — `ui/src/components/mcp/McpServersPanel.test.tsx`
- list renders from injected `fetchServers`; empty + disabled states.
- create http + stdio → `createServer` called with the right shape; bad input blocked client-side.
- edit + delete(confirm) + enable/disable toggle call the right deps.
- test-connection renders ok/tool_count + error.
- credential modal static → `putCredential` called with the token; **after save the token value is absent from the DOM** (assert `queryByDisplayValue(token)` is null in the list/detail). oauth → `startOAuth` called + `window.open` invoked (mock it).
- **no secret in a list/detail render** (only auth_kind badge + non-secret config).

## Do NOT
❌ backend changes. ❌ per-agent/per-tool (AD-1019). ❌ device-code UI. ❌ emoji. ❌ render any token/secret value back.

## Acceptance
Panel mounts (Engineering station / App.tsx) + opens via store flag; full CRUD + credential prompt-and-save + test + enable/disable + delete; no secret rendered back; Vitest green; `npm run build` clean; HXI principles honored; **comply with `.github/copilot-instructions.md`.**
