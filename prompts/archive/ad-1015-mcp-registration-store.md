# AD-1015 — MCP registration store + CRUD API (foundation)

**Track:** GitHub #956 (epic #955). **Highest formal AD: AD-1014 (`### AD-1014`, DECISIONS.md). No `### AD-1015` heading exists → this is AD-1015.**
**Repo:** OSS (`d:\ProbOS`). **Default-OFF (`config.mcp.management_enabled=False`). Backend + API only — no HXI, no credentials, no OAuth, no per-agent wiring.**

> **AD-number note (Architect-resolved 2026-06-16):** AD-1014's *shipped* DECISIONS.md body and PROGRESS.md L3 twice forward-reference "AD-1015" as a placeholder for **pack `mcpServers` auto-launch / pack wiring** (#954) — that slice was never built and has no `### AD-1015` ledger entry. This AD (the MCP registration store) is the stronger, foundational claim on the number. **Resolution:** AD-1015 = this registration store; the pack-wiring forward-references are re-pointed to **AD-1020** (next free after the epic 1015–1019). The Builder updates those two strings in a doc-only pass (see §5 / "Files the Builder will touch"). No code depends on the old reference.

> **Architect (verify-first, done 2026-06-16):** every reference in §1 has been opened against HEAD and corrected in place. Decisions on store placement (§1), the secret-guard (§2), and config/store dedup (§4–§5) are resolved below.

---

## 1. The gap (verified 2026-06-16)

MCP servers are **static config + read-only**. To get a CRUD management UX (epic #955) we first need a **persisted, runtime-mutable registration store** + an HTTP CRUD surface. This AD is that foundation — everything else in the epic (credentials AD-1016, OAuth AD-1017, HXI AD-1018, per-agent AD-1019) builds on it.

Read these first:
- `MCPBridge` — [bridge.py](src/probos/integrations/mcp_bridge/bridge.py): `__init__(*, egress_policy, emit_event, request_timeout, stdio_enabled=False, command_allowlist=None, consent_fn=None)` (L38); `register_server(url, headers=None) -> bool` (**sync**, L56 — returns `False` on empty url or duplicate key, never raises); `async register_stdio_server(name, command, args, env, cwd, *, timeout=None) -> bool` (L73); `list_servers()` (L150); `get_client(key)` (L153); `close_all()` (L164, awaits `client.close()`). **`_clients: dict[str, MCPClient]` is keyed by `url` for http and by `name` for stdio** (L145 `self._clients[name] = client` — *not* by command). **Verified: no public `unregister_server` exists → add one (§3).** `MCPClient.close()` is `async` (client.py L155).
- `MCPServerConfig` / `MCPConfig` — [config.py](src/probos/config.py#L3519): `MCPServerConfig` (L3519) `{type: Literal["http","stdio"]="http", url="", headers={}, command="", args=[], env={}, cwd="", timeout_seconds: float|None=None}` + a `model_validator(mode="after")` (http⇒url, stdio⇒command). `MCPConfig` (L3547) `{enabled=True, request_timeout_seconds, servers, stdio_enabled=False, command_allowlist=[uvx,npx,python,node,docker]}`. Adding `management_enabled: bool = False` is clean (Pydantic v2 BaseModel, all-defaulted).
- Startup wiring — [finalize.py](src/probos/startup/finalize.py#L3274): `if config.mcp.enabled:` (L3274) → `runtime.mcp_bridge = MCPBridge(...)` (L3285, **direct-assign convention**) → http sync loop (`register_server(srv.url, headers=...)`) → AD-1014 inert stdio loop (`await register_stdio_server(name=srv.command, ...)`); `else: runtime.mcp_bridge = None` (L3313). `runtime.data_dir` is the public data-dir property (used L2795/L2876/L2945).
- Read-only catalog — [tools.py](src/probos/routers/tools.py#L44) `list_capability_catalog` (the `@router.get("/catalog")` at L44) reads `config.mcp.servers` at L141 (`for srv in getattr(mcp_cfg, "servers", []) ...`, gated on `mcp_cfg.enabled`). **AD-1015 leaves this config-only — do NOT touch tools.py here; unioning store rows into the catalog is an AD-1018 concern (note left in §5).**
- **Store pattern to mirror exactly** — `IntentGrantStore` [intent_grants.py](src/probos/cognitive/intent_grants.py): `from probos.protocols import ConnectionFactory` (L37, the correct type import); lazy `from probos.storage.sqlite_factory import default_factory` inside `__init__` (L98); `start()` = `PRAGMA journal_mode=WAL` + `busy_timeout=5000` + `synchronous=NORMAL` + `executescript(_SCHEMA)` + `commit` + `_load_cache` (L100); `stop()` closes + None; `db_path=""` ⇒ cache-only (tests skip DB I/O); in-memory `_cache` for sync reads. **Resolved placement: `src/probos/integrations/mcp_bridge/store.py`** (co-located with the bridge — the store is MCP *integration/registration* state tightly coupled to `MCPBridge`, and the router reads both `runtime.mcp_bridge` and `runtime.mcp_server_store`; a top-level `mcp_servers/` package would scatter MCP concerns. `IntentGrantStore` lives in `cognitive/` only because it is a *cognitive-authorization* substrate.) Import the new store via the direct module path `from probos.integrations.mcp_bridge.store import McpServerStore` — **no `__init__.py` change**.
- Router DI — routers use `runtime: Any = Depends(get_runtime)` ([deps.py](src/probos/routers/deps.py#L13) → `request.app.state.runtime`); register the new router in [api.py](src/probos/api.py) (add to **both** the `from probos.routers import (...)` block at L192 and the `for r in (...)` include tuple at L235 — the include loop is flat/unconditional).

## 2. `McpServerStore` (new) — `store.py`

Mirror `IntentGrantStore` (ConnectionFactory + WAL + sync cache + `db_path=""` cache-only). Schema `mcp_servers`:

| col | type | notes |
|---|---|---|
| `id` | TEXT PK | uuid4 hex |
| `name` | TEXT UNIQUE NOT NULL | kebab-case, validated |
| `type` | TEXT NOT NULL | `http` \| `stdio` |
| `url` | TEXT DEFAULT '' | http |
| `headers_json` | TEXT DEFAULT '{}' | **non-secret only (§2a guard)** |
| `command` | TEXT DEFAULT '' | stdio |
| `args_json` | TEXT DEFAULT '[]' | stdio |
| `env_json` | TEXT DEFAULT '{}' | **non-secret only (§2a guard)** |
| `cwd` | TEXT DEFAULT '' | stdio |
| `timeout_seconds` | REAL | nullable |
| `enabled` | INTEGER NOT NULL DEFAULT 1 | soft-disable axis |
| `auth_kind` | TEXT NOT NULL DEFAULT 'none' | `none`\|`static`\|`oauth` (AD-1017 consumes) |
| `credential_ref` | TEXT NOT NULL DEFAULT '' | AD-1016 consumes |
| `created_at` | REAL NOT NULL | |
| `updated_at` | REAL NOT NULL | |

Frozen `McpServerRecord` dataclass + `to_public_dict()` (NEVER emit secret values — there are none here, but the method is the single serialization seam). Async API: `create(record)→McpServerRecord` (uuid + timestamps), `get(id)`, `list()`, `update(id, **fields)` (bump `updated_at`), `delete(id)→bool`, `set_enabled(id, bool)`. Sync: `list_sync()` (cache). `start()`/`stop()`/`_load_cache()` mirror IntentGrantStore. Name-uniqueness enforced (raise `ValueError` on dup, like `import_skill`).

### 2a. `validate_record(record, *, command_allowlist)` — pure helper (resolved secret-guard)

Pure function (no I/O), called by the router before `create`/`update` so failures map to a clean `400`. Defense-in-depth: the bridge re-checks the allowlist at spawn (`register_stdio_server` already refuses non-allowlisted commands), so this is the *first* gate, not the only one.

- `type=="http"` ⇒ non-empty `url` required (else 400).
- `type=="stdio"` ⇒ non-empty `command` required AND `command ∈ command_allowlist` (else 400; the router passes `runtime.config.mcp.command_allowlist`).
- `name` must match `^[a-z0-9][a-z0-9-]*$` (kebab) — else 400.
- **Secret-guard — structural denylist (NOT a `${ref}` rule).** The earlier `${ref}` idea is rejected: it over-constrains (it would reject legitimate non-secret pairs like `Content-Type`/`NODE_ENV`) and pre-commits AD-1016's credential-ref syntax before AD-1016 designs it. Instead, refuse the **known credential-bearing channels** when they carry a non-empty literal value, and point the operator at the AD-1016 seam:
  - **Header keys** (case-insensitive) in `{authorization, proxy-authorization, x-api-key, api-key, apikey, cookie, x-auth-token, x-amz-security-token}` with a **non-empty** value → reject with `secret_value_not_allowed`: *"secret-bearing header values are not stored in AD-1015; set `auth_kind`+`credential_ref` (AD-1016 resolves credentials at registration)."*
  - **Env keys** (case-insensitive) that `endswith` one of `{_token, _key, _secret, _password, _apikey, _api_key}` **or** exactly match `{token, secret, password, apikey, api_key}` with a **non-empty** value → same rejection.
  - **Empty** values for those keys are allowed (the operator may declare the channel exists; AD-1016 fills it via `credential_ref`). All other (non-secret) header/env pairs pass through and are persisted verbatim.
  - This is leak-proof for every known secret channel, needs no unbuilt `${ref}` contract, and keeps non-secret metadata usable. Implement the key sets as module-level frozensets/tuples (single source of truth, type-annotated).

## 3. Bridge — add `unregister_server` (verified absent)

**Verified: `MCPBridge` has no public unregister** (grep of `bridge.py` shows only `register_server`/`register_stdio_server`/`list_servers`/`get_client`/`close_all`). Add an async method mirroring `close_all`'s `await client.close()`:
```
async def unregister_server(self, key: str) -> bool:
    client = self._clients.pop(key, None)
    if client is None:
        return False
    await client.close()
    return True
```
`key` is the same value `_clients` is keyed by: **`url` for http, `name` for stdio** (the router derives `key = record.url if record.type == "http" else record.name`). Keep `register_server` (sync http) + `register_stdio_server` (async) unchanged; do not touch `__init__`/transport. This is the only change to `bridge.py`.

## 4. Router — `routers/mcp_servers.py`, prefix `/api/mcp/servers`

Gate the whole router on `runtime.config.mcp.management_enabled` (new field, §5). The router is included **unconditionally** in `api.py` (matching the flat include loop); each endpoint checks the gate first and returns **404** (`feature_disabled`) when off — so existing paths are byte-identical and the new paths simply 404 when disabled. DI `runtime` + read `runtime.mcp_server_store` / `runtime.mcp_bridge` via `getattr(..., None)` (honest-degrade → **503** when absent).

**Bridge key derivation (single rule, used by register/unregister/re-register):** `key = record.url if record.type == "http" else record.name`. **Await discipline:** the http path is **sync** (`bridge.register_server(url, headers)` — no `await`); the stdio path is **async** (`await bridge.register_stdio_server(name=..., command=..., args=..., env=..., cwd=..., timeout=...)`). Never `await` the http register; always `await` the stdio register/unregister.

- `GET ""` → `{servers: [rec.to_public_dict()...], count}`.
- `POST ""` body→`validate_record(rec, command_allowlist=runtime.config.mcp.command_allowlist)`→`store.create`; if `enabled`, live-register via the key rule (http sync / stdio await). Return **201** + the record. Validation failure → **400**; command-not-allowlisted / secret-value → **400**; dup name (store `ValueError`) → **409**.
- `GET "/{id}"` → record | **404**.
- `PUT "/{id}"` → `store.update`; if a connection-affecting field changed and the row is enabled, `await bridge.unregister_server(old_key)` then re-register with the new key. → record | **404**.
- `DELETE "/{id}"` → `await bridge.unregister_server(key)` (best-effort; ignore `False`) + `store.delete`. Return `{deleted: true}`. (Credential cleanup via `credential_ref` is an AD-1016 seam — leave a `# AD-1016:` TODO; do not implement secret deletion here.)
- `POST "/{id}/enable"` / `POST "/{id}/disable"` → `store.set_enabled` + register/unregister via the bridge (keep the row).
- `POST "/{id}/test"` → build a **transient** client (do NOT persist, do NOT touch `_clients`): http = `MCPClient(session=MCPSession(url, headers))`; stdio = a `StdioTransport`+`MCPClient` you `await transport.start()`. Call `initialize()` + `list_tools()`, then **`await client.close()` in a `finally`** (never leak a subprocess). Return `{ok: true, tool_count}` or `{ok: false, error}` with **HTTP 200** — wrap in `try/except Exception` and never raise 500 for a server-side/connection failure (honest-degrade).

## 5. Config + startup

- `config.py` `MCPConfig` (L3547): add `management_enabled: bool = False` (default-OFF gate). `system.yaml`: leave absent → False (no behavior change).
- `finalize.py`: **inside the existing `if config.mcp.enabled:` block** (L3274), **after** the http/stdio registration loops and before the `logger.info(...)` / `else:` (L3313): `if config.mcp.management_enabled:` → construct `McpServerStore(db_path=str(runtime.data_dir / "mcp_servers.db"))`, `await store.start()`, **direct-assign `runtime.mcp_server_store = store`** (mirror the adjacent `runtime.mcp_bridge = ...`), then seed — for each `enabled` stored row, live-register via the §4 key rule (http sync / stdio await). In the `else` (gate off, or `config.mcp.enabled` False) set `runtime.mcp_server_store = None`.
- **Do NOT add a `results.py` field.** The store is built in `finalize.py` adjacent to `mcp_bridge`, whose convention is **direct-assign on `runtime`** (not results-threading — that pattern is only used for `intent_grant_store`, built in `communication.py`). One fewer file touched, and it matches the local idiom.
- **Config/store dedup + precedence (resolved):** config-defined `config.mcp.servers` register **first** (existing loop), stored rows register **second**. `MCPBridge.register_server`/`register_stdio_server` already return `False` on a duplicate key, so **double-registration is impossible** — no pre-scan needed. **Config wins**: a stored row whose bridge key (`url` for http / `name` for stdio) collides with a config row persists in the store but is a bridge no-op (its `register_*` returns `False`; the seed loop ignores the return). The store still enforces its own `name` UNIQUE constraint (dup → `ValueError` → 409 at the API).
- `shutdown.py`: add teardown after the `intent_grant_store` block (L685–687): `if getattr(runtime, "mcp_server_store", None): await runtime.mcp_server_store.stop(); runtime.mcp_server_store = None`.
- Register the router in `api.py` (import block L192 + include tuple L235).
- **AD-1020 doc-only re-point:** update the two strings that forward-reference "AD-1015" for pack wiring — in `DECISIONS.md` (the AD-1014 body: `no pack mcpServers auto-launch (AD-1015)`) and `PROGRESS.md` L3 (`no pack wiring (AD-1015)`) — to read **AD-1020**. Text-only; no code impact.
- **Do NOT touch `routers/tools.py`** — the capability catalog stays config-only this AD; unioning store rows into `/api/tools/catalog` is an AD-1018 (HXI) concern. Leave a one-line `# AD-1018:` note there only if trivially adjacent; otherwise omit.

## 6. Tests — `tests/test_ad1015_mcp_server_store.py` + `tests/test_ad1015_mcp_servers_api.py`

BF-287 — real `McpServerStore` (`db_path=""` cache-only) + real `MCPBridge` + real `TestClient`, no MagicMock at the store/bridge boundary. Full type annotations on every new public method; `validate_record` is a pure function and gets its own unit tests.
- Store: create (uuid+timestamps), get, list, list_sync (cache), update (bumps updated_at), delete, set_enabled, dup-name→ValueError.
- `validate_record`: http-needs-url (400), stdio-needs-command (400), stdio command-not-allowlisted (400), non-kebab name (400), **secret-guard** — `Authorization`/`X-Api-Key`/`Cookie` header with a non-empty value rejected, `*_TOKEN`/`*_SECRET`/`*_API_KEY` env with a non-empty value rejected, **and** an empty-valued secret key + a non-secret header (`Content-Type`) / non-secret env (`NODE_ENV`) *accepted* (proves the guard isn't over-constraining).
- API (`management_enabled=True` runtime): GET empty + populated; POST http + stdio (+ validation rejects 400/409 incl. a secret-value 400); GET/{id} + 404; PUT re-registers (assert the bridge key flips when url/name changes); DELETE unregisters; enable/disable toggles registration but keeps the row; test-connection ok (against a real fixture server — reuse the AD-1014 stdio echo fixture or a minimal http one) + honest-degrade returns `{ok:false}` **HTTP 200** on a bad target (assert no 500).
- Config/store dedup: a stored row whose key matches a config-registered server is a bridge no-op (seed ignores the `False`); assert no double client and config's client wins.
- Gate: `management_enabled=False` ⇒ every endpoint 404, `runtime.mcp_server_store is None`, no DB created (byte-identical).
- Run config + MCP regression: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "config or mcp" -q -n 0 -p no:cacheprovider`.

## 7. Do NOT build / change
- ❌ Any HXI (AD-1018). ❌ Credential vault/keychain storage or reads (AD-1016) — `credential_ref`/`auth_kind` are **inert stored strings** this AD. ❌ OAuth (AD-1017). ❌ per-agent grants (AD-1019). ❌ secret values in the store or API responses. ❌ `MCPBridge.__init__` / `transport.py` / `client.py` wire behavior (AD-449/AD-1014) — the only `bridge.py` change is the new `unregister_server`. ❌ `routers/tools.py` (catalog stays config-only; AD-1018 unions). ❌ `results.py` (direct-assign on `runtime`, no dataclass field). Default-OFF ⇒ byte-identical.

## 8. Acceptance
All §6 green; `management_enabled=False` ⇒ byte-identical (existing `-k "mcp or ad449 or ad597"` suites pass unchanged — if a route-count/OpenAPI-schema assertion exists, confirm it tolerates the unconditionally-included router); CRUD + enable/disable + test-connection work against a real bridge; no secret persisted/returned (secret-guard denylist enforced + tested); the http register path is **not** awaited and the stdio path **is**; transient test-connection client is closed in `finally` (no leaked subprocess); full type annotations on new public APIs; Pydantic v2 hygiene (`Field(default_factory=...)`, validator); async hygiene; **verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## 9. Files the Builder will touch

**CREATE (4):**
- `src/probos/integrations/mcp_bridge/store.py` — `McpServerStore` + `McpServerRecord` + `validate_record` (+ secret-key denylist constants).
- `src/probos/routers/mcp_servers.py` — CRUD/enable/disable/test router, prefix `/api/mcp/servers`, gated on `management_enabled`.
- `tests/test_ad1015_mcp_server_store.py` — store + `validate_record` unit tests (BF-287 real store).
- `tests/test_ad1015_mcp_servers_api.py` — API tests (BF-287 real store + real `MCPBridge` + real `TestClient`).

**MODIFY (5):**
- `src/probos/integrations/mcp_bridge/bridge.py` — add `async unregister_server` only.
- `src/probos/config.py` — `MCPConfig.management_enabled: bool = False` (after L3559).
- `src/probos/startup/finalize.py` — store build + seed inside the `if config.mcp.enabled:` block (after the server loops, ~L3309); `else` → `runtime.mcp_server_store = None`.
- `src/probos/startup/shutdown.py` — teardown after the `intent_grant_store` block (L685–687).
- `src/probos/api.py` — import (L192) + include tuple (L235).

**DOC-ONLY (2, AD-1020 re-point):** `DECISIONS.md` (AD-1014 body) + `PROGRESS.md` (L3) — change the pack-wiring `(AD-1015)` → `(AD-1020)`.

**MUST NOT touch:** `routers/tools.py`, `startup/results.py`, `startup/communication.py`, `integrations/mcp_bridge/transport.py`, `integrations/mcp_bridge/client.py`, `MCPBridge.__init__`.

## 10. Verified against codebase (2026-06-16)

```
git grep -ohE "### AD-1[0-9]{3}" DECISIONS.md | sort -u | tail -1
  ### AD-1014                       # ceiling; no ### AD-1015 → free

bridge.py
  L38  def __init__( *, egress_policy, emit_event, request_timeout=30.0, stdio_enabled=False, command_allowlist=None, consent_fn=None )
  L56  def register_server(self, url, headers=None) -> bool        # SYNC; False on dup/empty
  L73  async def register_stdio_server(self, name, command, args, env, cwd, *, timeout=None) -> bool
  L145 self._clients[name] = client                                # stdio keyed by NAME (not command)
  L150 def list_servers / L153 get_client / L164 async close_all (awaits client.close())
  (no unregister_server)                                           # → §3 adds it
client.py  L155 async def close(self) -> None                      # §3 await is correct
config.py  L3519 class MCPServerConfig / L3547 class MCPConfig (model_validator http⇒url, stdio⇒command)
intent_grants.py L37 from probos.protocols import ConnectionFactory ; L98 from probos.storage.sqlite_factory import default_factory ; L100 start() WAL+busy_timeout+synchronous+executescript+_load_cache ; db_path="" cache-only
finalize.py L3274 if config.mcp.enabled: / L3285 runtime.mcp_bridge = MCPBridge( / L3313 else runtime.mcp_bridge = None ; runtime.data_dir public
communication.py L379 IntentGrantStore(db_path=str(data_dir/"intent_grants.db")) → results-threaded (NOT the mcp_bridge convention)
shutdown.py L685-687 getattr(runtime,'intent_grant_store',None)→stop()→None   # mirror target
deps.py L13 get_runtime → request.app.state.runtime
api.py L192 from probos.routers import (...) / L235 for r in (...) / L256 app.include_router(r.router)   # flat, unconditional
tools.py L44 @router.get("/catalog") list_capability_catalog / L141 for srv in getattr(mcp_cfg,"servers",[]) (gated on mcp_cfg.enabled)   # config-only; leave untouched
```
