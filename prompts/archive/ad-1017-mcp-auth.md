# AD-1017 — MCP server authentication: static tokens + OAuth

**Track:** GitHub #958 (epic #955). **Highest AD at authoring: AD-1016 → this is AD-1017.**
**Repo:** OSS (`d:\ProbOS`). Endpoints + credential-resolution wiring only — no HXI (AD-1018, consumes these endpoints), no per-agent grants (AD-1019), no device-code (deferred AD-1017a).

> **Architect:** verify every reference; re-grep the ceiling; resolve the per-server OAuth-client-config home (§2) and the stdio-auth shape (§1). Confirm the cloud-picker refresh helper is reusable without modifying AD-720c code.

---

## 1. Goal + injection point (VERIFIED)

Authenticated MCP servers must work: resolve a server's stored credential and inject it at register time. AD-1015 reserved `McpServerRecord.auth_kind` (none|static|oauth) + `credential_ref`. This AD makes them live, with **secrets only in the credential vault/keychain (AD-706f/AD-1016), never in the store row or any API response.**

**The injection seam (verified):** [routers/mcp_servers.py](src/probos/routers/mcp_servers.py) `_register(bridge, record)` (L116) does `bridge.register_server(record.url, headers=dict(record.headers))` (http) / `register_stdio_server(..., env=dict(record.env), ...)` (stdio). AD-1017 adds `_resolve_auth_headers(record, runtime) -> dict` and merges: http → `headers={**record.headers, **auth}`. **stdio static-auth shape (RESOLVED):** add a non-secret `auth_env_var: str = ""` field on the record; when set and `auth_kind != "none"`, inject the resolved token into `env` under that var name (`env={**record.env, auth_env_var: <resolved value>}`) — the operator names the var their server expects (e.g. `API_KEY`). When `auth_env_var` is empty, stdio registers unauthenticated (http is the primary auth path this slice). The base-headers reach the wire at [transport.py](src/probos/integrations/mcp_bridge/transport.py) L108 (`**self._base_headers`).

Read first: `MCPSession.headers` (session.py:22); the AD-1015 router register/update/enable paths (L149/L198/L181); `runtime.credential_vault` Protocol (`store(*,ref,value,scope)`/`read(*,ref,requesting_agent_id)`/`delete(*,ref)`); `CredentialScope` (captain-only = empty allowed_agent_ids).

## 2. Static auth

Operator supplies the token via a **dedicated endpoint** (never the registration body — keeps secrets out of the row):
- `POST /api/mcp/servers/{id}/credential` body `{value: str, header_name: str = "Authorization", scheme: str = "Bearer"}` → `credential_vault.store(ref=f"mcp:{id}", value=value, scope=<captain-only>)`; set `record.auth_kind="static"`, `record.credential_ref=f"mcp:{id}"`, and persist the **non-secret** `header_name`/`scheme` on the record (new fields `auth_header_name`/`auth_scheme`, default "Authorization"/"Bearer"). 503 if no vault. Re-register if enabled.
- `DELETE /api/mcp/servers/{id}/credential` → `credential_vault.delete(ref)`, clear `credential_ref`, `auth_kind="none"`. Re-register.
- `_resolve_auth_headers`: `auth_kind=="static"` → `v = await credential_vault.read(ref, "captain")`; `{header_name: f"{scheme} {v}".strip()}` (or bare `v` if scheme==""). Vault miss → `{}` + warning (honest-degrade; server registers unauthenticated).

## 3. OAuth auth (authorization-code popup — reuse AD-720c)

Per-server OAuth client config: add a **non-secret** `oauth_json` field on the record (client_id, authorize_url, token_url, scopes, redirect_uri) — the **client_secret is stored in the vault by ref** (`mcp:{id}:oauth_secret`), never in `oauth_json` or responses. (RESOLVED: per-server `oauth_json` is the right granularity, not the global `OAuthClientCredentialsConfig`.)
- `McpOAuthProvider` modeled on `CloudPickerProvider` ([provider.py](src/probos/cloud_pickers/provider.py): `start_authorization(*, state) -> url`, `async handle_callback(*, code) -> OAuthTokenBundle`). VERIFIED there is no separately-importable refresh helper — **replicate a minimal httpx token POST** (`grant_type=authorization_code` for exchange, `grant_type=refresh_token` for refresh) in the MCP provider using the resident `httpx` dep; do NOT modify the cloud-picker code.
- `POST /api/mcp/servers/{id}/auth/start` → mint CSRF state. **CSRF store (RESOLVED):** mirror cloud_pickers' lazy `_get_state_store(runtime)` (cloud_pickers.py:59 — a module-level per-runtime `CsrfStateStore(ttl_seconds=...)` with a `_clear_state_stores()` test hook); add the equivalent in `routers/mcp_servers.py`. Return `{auth_url, state}`.
- `GET /api/mcp/servers/{id}/auth/callback?code=&state=` → consume state (403 on invalid) → `handle_callback(code)` → `OAuthTokenBundle` → `credential_vault.store(ref=f"mcp:{id}:oauth", value=bundle.model_dump_json(), scope=<captain>)`; set `auth_kind="oauth"`, `credential_ref=f"mcp:{id}:oauth"`; return the **same popup-close HTML** as [cloud_pickers.py](src/probos/routers/cloud_pickers.py) callback (`postMessage` + `window.close()`).
- `_resolve_auth_headers`: `auth_kind=="oauth"` → read bundle JSON from vault → `OAuthTokenBundle.model_validate_json(...)` → `{"Authorization": f"Bearer {bundle.access_token}"}`.
- **Refresh on 401 (RESOLVED):** a reactive `POST /api/mcp/servers/{id}/auth/refresh` (the HXI/registration calls it when a `test`/request 401s) — read the stored bundle, POST `grant_type=refresh_token` to `token_url`, re-store the new bundle, re-register. A reactive endpoint avoids threading refresh through the transport this slice. Unit-test the refresh exchange (monkeypatch the httpx POST).

## 4. Wire into register
`_resolve_auth_headers(record, runtime)` is called inside `_register` (and the update/enable re-register). `auth_kind=="none"` → `{}` (byte-identical to AD-1015). No secret enters the `McpServerStore` row (only `credential_ref`/`auth_kind`/`auth_header_name`/`auth_scheme`/`oauth_json` — all non-secret). `to_public_dict` continues to never emit a secret (the new fields are non-secret; the vault holds values).

## 5. Tests — `tests/test_ad1017_mcp_auth.py`
BF-287: real `McpServerStore` + a real in-memory credential vault (construct `EncryptedFileCredentialVault` on `tmp_path` with a test crew token, OR a small real fake implementing the Protocol — NOT MagicMock) + real `TestClient` + the AD-1014 echo fixture for register.
- Static: `POST /credential` stores in vault; `_resolve_auth_headers` returns `Authorization: Bearer <v>`; register injects it (assert the bridge client's session headers carry it); `DELETE /credential` removes it + clears the ref; **token is in the vault, NOT in the store row or ANY API response body** (assert).
- OAuth: `auth/start` → `{auth_url, state}` (state minted in the CSRF store); `auth/callback` with a **mocked token exchange** (monkeypatch the httpx token POST) persists an `OAuthTokenBundle` in the vault + returns popup-close HTML; invalid state → 403; `_resolve_auth_headers` → `Bearer <access>`; refresh exchange re-stores a new bundle (unit-tested).
- `auth_kind=="none"` registers byte-identical to AD-1015.
- `management_enabled=False` ⇒ all new endpoints 404.
- No token value persisted to the store / returned / logged.
- Parity: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "mcp or ad449 or ad597 or ad1015 or credential or cloud_picker" -q -n 0 -p no:cacheprovider` green (AD-720c + AD-1015 unchanged).

## 6. Do NOT change / build
- ❌ device-code (AD-1017a). ❌ HXI (AD-1018). ❌ per-agent grants (AD-1019). ❌ the credential Protocol, the AD-720c cloud-picker code, or the AD-1015 store schema beyond ADDING the non-secret auth fields (`auth_header_name`, `auth_scheme`, `oauth_json`). ❌ any secret in the store/responses/logs.

## 7. Acceptance
All §5 green; AD-720c + AD-1015 suites unchanged; secrets only in the vault (asserted); `auth_kind=="none"` byte-identical; `management_enabled=False` ⇒ 404; CSRF on OAuth; full type annotations; Pydantic v2; async hygiene; **verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## 8. Files the Builder will touch
**Create:** `src/probos/integrations/mcp_bridge/mcp_oauth.py` (`McpOAuthProvider` — authcode exchange + refresh via httpx), `tests/test_ad1017_mcp_auth.py`.
**Modify:** `src/probos/integrations/mcp_bridge/store.py` (ADD non-secret fields `auth_header_name`/`auth_scheme`/`auth_env_var`/`oauth_json` to `McpServerRecord` + schema + `to_public_dict`; `validate_record` unchanged secret-guard still applies), `src/probos/routers/mcp_servers.py` (add `_resolve_auth_headers` + merge in `_register`; `/credential` POST+DELETE; `/auth/start` + `/auth/callback` + `/auth/refresh`; lazy `_get_state_store`), `DECISIONS.md` + `PROGRESS.md`.
**Device-code (AD-749 style) DEFERRED to AD-1017a** — named, not built.
**Do NOT touch:** `cloud_pickers/*` (reuse `OAuthTokenBundle`/`CsrfStateStore` by import only), `tools/browser/credentials.py`, `security/keyring_backend.py`, the credential Protocol.

## 9. Verified-against-codebase (2026-06-16)
- Inject seam `_register` at routers/mcp_servers.py:116 (`headers=dict(record.headers)` http / `env=dict(record.env)` stdio). ✅
- `McpServerRecord.auth_kind`/`credential_ref` exist (store.py:123-124); schema `mcp_servers` at :36; `to_public_dict` is the serialization seam. ✅
- `credential_vault` Protocol async `store`/`read`/`delete`, captain-only scope. ✅
- AD-720c reuse: `OAuthTokenBundle` (tokens.py:17, `model_dump_json`/`model_validate_json`), `CsrfStateStore` + `_get_state_store(runtime)` lazy pattern (cloud_pickers.py:59), callback popup-close HTML (cloud_pickers.py callback). `CloudPickerProvider.handle_callback` (provider.py:70) — no importable refresh helper, MCP provider replicates minimal httpx token POST. ✅
- `MCPSession.headers` → transport.py:108 `**self._base_headers`. ✅
