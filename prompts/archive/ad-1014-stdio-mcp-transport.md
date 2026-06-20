# AD-1014 — stdio/subprocess MCP transport (marketplace launch parity)

**Track:** GitHub #954. **Highest AD at authoring: AD-1013 → this is AD-1014.**
**Repo:** OSS (`d:\ProbOS`). **Default-OFF mechanism slice. No pack wiring (that is AD-1015).**

> **Architect:** verify every reference below against the live codebase before approving (AD-566a discipline). Assign/confirm the AD number by re-grepping the ceiling. Decompose only if a single commit is genuinely too large; prefer one AD = one testable change.

---

## 1. The gap (verified 2026-06-15)

ProbOS speaks MCP over **HTTP only**. To install the MCP marketplace (15k+ servers, overwhelmingly stdio) it needs a **stdio/subprocess transport** — spawn `command + args`, talk JSON-RPC over stdin/stdout. The MCP spec: *"Clients SHOULD support stdio whenever possible."*

Current state (read these first):
- `MCPClient` — [client.py](src/probos/integrations/mcp_bridge/client.py): JSON-RPC 2.0 **hardcoded to `httpx.AsyncClient`**. `initialize()` / `list_tools()` / `call_tool()` / `read_resource()` all funnel through `_call(method, params)` which does `http.post(self._session.server_url, …)`. The egress policy gates every call. `_last_response_headers` captures `Mcp-Session-Id`.
- `MCPSession` — [session.py](src/probos/integrations/mcp_bridge/session.py): frozen dataclass, `server_url` / `session_id` / `headers` / `capabilities`.
- `MCPBridge` — [bridge.py](src/probos/integrations/mcp_bridge/bridge.py): `register_server(url, headers)` → builds `MCPSession` + `MCPClient`, keyed by URL in `self._clients`. `invoke` / `list_servers` / `get_client` / `close_all`.
- `MCPServerConfig` / `MCPConfig` — [config.py](src/probos/config.py) (~L3519): `MCPServerConfig{url, headers}`; `MCPConfig{enabled=True, request_timeout_seconds, servers}`. `system.yaml` has `mcp: {enabled: true, request_timeout_seconds: 30.0, servers: []}`.
- Startup wiring — [finalize.py](src/probos/startup/finalize.py) **L3269–3284**, inside `async def finalize_startup` (L2422 — no top-level `def` between it and the block, so an `await` here is valid): `if config.mcp.enabled: runtime.mcp_bridge = MCPBridge(egress_policy=getattr(runtime,"egress_policy",None), emit_event=runtime.emit_event, request_timeout=config.mcp.request_timeout_seconds)` then `for srv in config.mcp.servers: runtime.mcp_bridge.register_server(srv.url, headers=dict(srv.headers))`. `register_server` is **sync** (returns `bool`); `runtime.emit_event` is **sync** (`def emit_event(self, event, data=None) -> None` — runtime.py L1312).
- `external_discovery.discover_external_apps(registry, mcp_bridge)` — [external_discovery.py](src/probos/mcp_apps/external_discovery.py): **transport-agnostic** — iterates connected clients, registers their tools as mesh capabilities. Works the moment a stdio client is connected; do not change it.
- Consent substrate (already shipped): `HookBus` (AD-1004) — [bus.py](src/probos/hooks/bus.py). The consent seam is **`async def fire(event, context=None) -> AggregateDecision`** with `.allowed`/`.asked`/`.denied` properties (most-restrictive-wins: `deny` > `ask` > `allow`; an **unwired bus returns `ALLOW`**, so firing with no handlers never blocks). `HookEvent.PRE_TOOL_USE` is a gate event. `runtime.hook_bus` exists when `config.hooks.enabled`. ⚠️ `make_capability_gate_handler` (AD-1012, [handlers.py](src/probos/hooks/handlers.py)) is the **precedent** for adapting a policy store into the bus — but it builds a **`PreDispatch`** *agent-intent* handler keyed on `agent_id`/`intent_name`, so it is **NOT** the handler the MCP-spawn gate uses. The MCP gate just **fires `PRE_TOOL_USE` and reads `.denied`/`.allowed`**.
- Egress — [egress.py](src/probos/security/egress.py): `EgressPolicy.is_allowed(url) -> bool` parses the host from a URL — **HTTP-only**; stdio has no URL and is correctly NOT egress-gated. The egress gate currently lives **inside `MCPClient._call`**; this AD moves it into `HttpTransport` (HTTP-only) so stdio never consults it.

## 2. MCP stdio transport spec (normative — implement exactly)

- Client launches the server as a **subprocess**.
- Server reads JSON-RPC from **stdin**, writes to **stdout**.
- **Messages are delimited by newlines and MUST NOT contain embedded newlines** (NDJSON — `json.dumps(...)` has no newlines by default; append `\n`).
- Server MAY write logs to **stderr** — capture to the logger, never parse as protocol.
- Client MUST NOT write non-MCP to stdin; server MUST NOT write non-MCP to stdout.
- Shutdown: **close stdin, then terminate** the subprocess (kill fallback on timeout).
- `initialize` payload uses the existing `MCP_PROTOCOL_VERSION` / `clientInfo` constants from [client.py](src/probos/integrations/mcp_bridge/client.py).

## 3. Best practices absorbed (MCP spec · Copilot · Claude Code · Hermes)

1. **Config shape `type` + `command`/`args`/`env`** — universal across Copilot `mcp.json`, Claude `.mcp.json`, Hermes `mcp_servers`. Mirror it.
2. **Trust gate before first launch** — all three warn "local MCP servers run arbitrary code." Route the spawn through HookBus `PreToolUse`; `deny` blocks it.
3. **Command allowlist** — bound *what* may be spawned (`uvx`, `npx`, `python`, `node`, `docker`; configurable). Non-allowlisted `command` is refused, no spawn, `MCP_BRIDGE_FAILED` event. This is the primary guard.
4. **Per-server timeout + output cap** — a runaway server must not hang/flood. (Claude `timeout`, Hermes timeout overrides.)
5. **stderr → logs, never stdout.**
6. **No auto-restart of stdio servers** (Claude: stdio not auto-reconnected) — mark failed, honest-degrade.
7. **Namespacing** — keep server identity on the client key so tool names can be namespaced by server (collision avoidance; full namespacing can be AD-1015).
8. **Install-into-isolation, never host** — the subprocess *is* the isolation. Never route marketplace code through the runtime-venv `DependencyResolver`. Kernel sandbox = #936 Tier-2 (future; name it, don't build it).

## 4. Implementation

### 4a. Transport seam — `transport.py` (new). **HTTP path stays byte-identical.**

The seam is introduced **inside `MCPClient`** (not at the bridge) so `register_server` and every existing AD-449 / AD-597f test stay **unchanged**. The `Transport` is **event-free and narrow** — no `EventType`/`emit_event`, no egress in the *interface*, no request headers in the *interface*.

- **`Transport` Protocol** (`typing.Protocol`):
  - `async def start() -> None`
  - `async def request(payload: dict) -> dict` — send one JSON-RPC request, return the parsed **envelope** (`{jsonrpc,id,result|error}`). Raise `MCPProtocolError(reason=…)` on any **wire** failure; the client emits.
  - `async def close() -> None`
  - `last_metadata: dict[str,str]` — **response-direction metadata only** (HTTP exposes the lower-cased response headers so `initialize()` can read `mcp-session-id`). The **request-direction** session header is transport-internal (below) and MUST NOT appear here (stdio has no headers — keeping it out is what stops the interface leaking HTTP concerns).
- **`MCPProtocolError`** gains an optional `reason: str = ""` (`__init__(self, *args, reason="")`; bare raises still work). This lets the transport name the failure without importing `EventType`. Reasons preserved verbatim: HTTP → `egress_blocked`/`client_closed`/`transport_error`/`http_error`/`bad_json`; stdio → `spawn_failed`/`closed_pipe`/`bad_json`/`timeout`.
- **`HttpTransport`** — lift the **wire** body of the current `_call` verbatim: egress gate on `server_url`, header build (`Content-Type`, `Accept`, base headers, `Mcp-Session-Id`), `httpx.post(url, content=json.dumps(payload), headers=headers)`, response-header capture, status-≥400, `response.json()`. On each wire failure `raise MCPProtocolError(<same msg>, reason=<same reason as today>)`. On success **return the envelope dict** (do NOT unwrap `result` — the client does). `__init__(*, server_url, base_headers, egress_policy=None, timeout=30.0, initial_session_id="")`; `start()` is a **no-op** (httpx client created in `__init__`, exactly as today).
  - **Request-direction `Mcp-Session-Id` — byte-identical, do not drop (this is the #1 regression risk):** today `_call` sends `Mcp-Session-Id` on every post once `session.session_id` is set. `HttpTransport` self-manages it: seed `self._session_id = initial_session_id`; after each response, update from `mcp-session-id` if present; inject as a request header when non-empty. `last_metadata` still exposes the raw response headers so `initialize()` can mirror the id into `MCPSession.session_id` (the `session_id` event field). A Builder who wires only `last_metadata` would silently stop sending the session id on calls 2..N — **not byte-identical.**
- **`MCPClient`** stays the **single event-emission site** (preserves today's exactly-one `MCP_BRIDGE_FAILED`/`MCP_BRIDGE_INVOKE` per call, same reasons):
  - `__init__(*, session, transport: Transport | None = None, egress_policy=None, emit_event=None, timeout=30.0)`. When `transport is None`, build `HttpTransport(server_url=session.server_url, base_headers=session.headers, egress_policy=egress_policy, timeout=timeout, initial_session_id=session.session_id)`. **This default keeps `register_server` and the existing direct-construction tests byte-identical** (a public back-compat default, not a test-only branch).
  - `_call(method, params)`: build the payload (`uuid` id, `JSONRPC_VERSION`, method, params); `try: envelope = await self._transport.request(payload) except MCPProtocolError as exc: self._emit_failed(method, reason=exc.reason or "transport_error", url=self._session.server_url, detail=str(exc)); raise`. Then keep the existing `bad_envelope`/`rpc_error`/`bad_result` checks + `self._emit_invoke(...)` exactly as today. `initialize()` reads `self._transport.last_metadata.get("mcp-session-id","")`.
  - Keep `JSONRPC_VERSION` / `MCP_PROTOCOL_VERSION` / `clientInfo {name:"probos",version:"0.1.0"}` constants. stdio reuses `MCPClient.initialize()` unchanged → identical handshake payload.

### 4b. `StdioTransport` — in `transport.py` (event-free; the client/bridge own emission)
- `__init__(*, command, args, env, cwd, timeout, name="")`. **No `emit_event`** — it raises `MCPProtocolError(reason=…)`; `request`-time failures are emitted by `MCPClient._call`, registration-time failures by the bridge (§4d). The allowlist is the **bridge's** guard (§4d), enforced before construction — not a transport concern.
- `start()`: `proc = await asyncio.create_subprocess_exec(command, *args, stdin=PIPE, stdout=PIPE, stderr=PIPE, env={**os.environ, **env} or None, cwd=cwd or None)`. Hold the `proc` ref. Spawn a stderr-drain task with **`asyncio.create_task`** (NOT `ensure_future`); **hold the task ref**; the drain coroutine reads lines → `logger.debug` and ends with `except asyncio.CancelledError: raise` after cleanup. `OSError`/`FileNotFoundError` → `raise MCPProtocolError(f"spawn failed: {command}", reason="spawn_failed")`.
- `request(payload)`: `self._proc.stdin.write(json.dumps(payload).encode()+b"\n"); await self._proc.stdin.drain()`. Read under one overall `asyncio.wait_for(_read_matching(payload["id"]), timeout)`: loop `line = await stdout.readline()` — `b""` (closed pipe) → `MCPProtocolError(reason="closed_pipe")`; `json.loads` (bad → `reason="bad_json"`); **skip lines whose `id` ≠ our id** (spec-legal `notifications/*` may appear on stdout) and keep reading until the matching envelope; return it. **Single-flight** (one outstanding request per client; the bridge awaits `invoke` serially) is acceptable for v1 — **documented limitation; a concurrent read-loop with id-keyed futures + server→client request handling is deferred to AD-1015.** `asyncio.TimeoutError` → `MCPProtocolError(reason="timeout")`. All failure paths leave the subprocess alive (honest-degrade; bridge stays usable).
- `close()`: if stdin open, `stdin.close()`; `proc.terminate()`; `try: await asyncio.wait_for(proc.wait(), timeout=<short>) except asyncio.TimeoutError: proc.kill(); await proc.wait()`. Cancel + await the stderr-drain task (swallow its `CancelledError`).
- `last_metadata` → `{}`. The stdio-backed `MCPSession` uses `server_url=f"stdio:{name}"` (a non-URL identifier so `MCP_BRIDGE_*` events carry a meaningful source; egress is never consulted for stdio) and `session_id=""`.

### 4c. Config — [config.py](src/probos/config.py) (`MCPServerConfig` **L3519**, `MCPConfig` **L3526**; both Pydantic **v2** `BaseModel`)
- `MCPServerConfig` gains (all defaulted; list/dict via `Field(default_factory=...)` — **never bare mutable defaults**): `type: Literal["http","stdio"] = "http"` (back-compat — existing `{url, headers}` entries default to `http` and are unaffected), `command: str = ""`, `args: list[str] = Field(default_factory=list)`, `env: dict[str,str] = Field(default_factory=dict)`, `cwd: str = ""`, `timeout_seconds: float | None = None`. Change `url: str` → `url: str = ""` (now optional). Add `@model_validator(mode="after")`: `type=="http"` requires non-empty `url`; `type=="stdio"` requires non-empty `command`; else `raise ValueError(...)` (fails at parse time).
- `MCPConfig` gains: `stdio_enabled: bool = False` (the default-OFF gate for the whole subprocess-launch capability) and `command_allowlist: list[str] = Field(default_factory=lambda: ["uvx","npx","python","node","docker"])`.
- `system.yaml` (L987 `mcp:` block, currently `{enabled: true, request_timeout_seconds: 30.0, servers: []}`): leave it as-is — `stdio_enabled` absent ⇒ `False`. Do **not** add a live stdio server. Default-OFF ⇒ byte-identical boot.

### 4d. Bridge — [bridge.py](src/probos/integrations/mcp_bridge/bridge.py)
- `register_server(url, headers=None)` — **unchanged** (constructs `MCPClient(session=, egress_policy=, emit_event=, timeout=)`; the `transport=None` default builds `HttpTransport`). HTTP path byte-identical.
- `MCPBridge.__init__` gains: `stdio_enabled: bool = False`, `command_allowlist: list[str] | None = None`, `consent_fn: Callable[[dict[str, Any]], Awaitable[bool]] | None = None`. **Keep the bridge decoupled from `HookBus`**: `consent_fn` is a narrow `async (ctx) -> bool` (True = allowed); startup adapts `hook_bus.fire(...)` to it (§4e). Do **not** import `HookBus`/`HookEvent`/`AggregateDecision` into the bridge.
- New `async def register_stdio_server(name, command, args, env, cwd, *, timeout=None) -> bool`, with guards **in this order, all BEFORE any spawn**:
  1. `if not self._stdio_enabled:` → return `False` (config state, not a failure; no event).
  2. `if name in self._clients:` → return `False`.
  3. **command allowlist (primary guard):** `if command not in (self._command_allowlist or []):` → emit `MCP_BRIDGE_FAILED {"server_url": f"stdio:{name}", "method": "start", "reason": "command_not_allowed", "detail": command[:200]}`; return `False`. **No subprocess created.**
  4. **consent (second layer):** `if self._consent_fn is not None and not await self._consent_fn({"tool_name":"mcp_stdio_spawn","server":name,"command":command,"args":list(args)}):` → emit `MCP_BRIDGE_FAILED` reason=`consent_denied`; return `False`. **No subprocess created.**
  5. build `StdioTransport(command=…, args=…, env=…, cwd=…, timeout=timeout or self._request_timeout, name=name)` + `MCPClient(session=MCPSession(server_url=f"stdio:{name}"), transport=transport, emit_event=self._emit_event)`; `try: await transport.start() except MCPProtocolError as exc:` → **the bridge emits** `MCP_BRIDGE_FAILED {"server_url": f"stdio:{name}", "method":"start", "reason": exc.reason or "spawn_failed", "detail": str(exc)[:200]}` (the `start()` path is NOT inside `_call`, so the client wrapper never sees it); honest-degrade → return `False`. On success, key the client by `name` in `self._clients`; return `True`.
- **Emission split (no gaps, no double-emit):** registration-time failures (`command_not_allowed`, `consent_denied`, `spawn_failed`) are emitted by the **bridge**; request-time failures (`timeout`, `closed_pipe`, `bad_json`, `rpc_error`, …) and `MCP_BRIDGE_INVOKE` are emitted by **`MCPClient._call`**. No path is emitted by both.
- `invoke` / `get_client` / `list_servers` / `close_all` are key-agnostic (string keys) — they already work for `name`-keyed stdio clients; `close_all` awaits `client.close()` which now also tears down the subprocess. **No change needed.**

### 4e. Startup — [finalize.py](src/probos/startup/finalize.py) L3269–3284 (inside `async def finalize_startup`)
- Construct the bridge with the new args: `MCPBridge(egress_policy=…, emit_event=runtime.emit_event, request_timeout=config.mcp.request_timeout_seconds, stdio_enabled=config.mcp.stdio_enabled, command_allowlist=config.mcp.command_allowlist, consent_fn=_mcp_consent)`.
- Define the consent adapter here (keeps the bridge decoupled; `HookEvent` is imported in finalize, **not** the bridge):
  ```python
  from probos.hooks.bus import HookEvent  # local import
  async def _mcp_consent(ctx: dict[str, Any]) -> bool:
      hb = getattr(runtime, "hook_bus", None)
      if hb is None:
          return True  # no bus → allowlist is the guard (stdio already opt-in)
      decision = await hb.fire(HookEvent.PRE_TOOL_USE, ctx)
      return decision.allowed  # fail-safe: refuse on ASK or DENY (no approval loop yet)
  ```
- Keep the existing **sync** HTTP `register_server` loop unchanged. After it, add the stdio loop (enclosing fn is async ⇒ `await` valid):
  ```python
  if config.mcp.stdio_enabled:
      for srv in config.mcp.servers:
          if srv.type == "stdio":
              await runtime.mcp_bridge.register_stdio_server(
                  name=srv.command, command=srv.command, args=srv.args,
                  env=srv.env, cwd=srv.cwd, timeout=srv.timeout_seconds,
              )
  ```
  With `stdio_enabled=False` (default) the loop never runs; with the default empty `servers` list it is inert — either way **byte-identical to today**. (v1 keys by `command`; a dedicated `name`/`mcpServers` field + collision-safe namespacing is AD-1015.)

## 5. Tests — `tests/test_ad1014_stdio_mcp_transport.py` + a fixture server

- **Fixture**: a tiny in-repo NDJSON echo MCP server script (e.g. `tests/fixtures/echo_mcp_server.py`) that reads a line, responds to `initialize` / `tools/list` / `tools/call` with valid JSON-RPC envelopes over stdout (echoing the request `id`), and may emit a spec-legal `notifications/*` line (no `id`) to exercise the skip-until-id read. Launch it with `sys.executable`.
- **BF-287** — real `MCPBridge` + real subprocess; **no MagicMock at the transport boundary.** (A `_FakeTransport` implementing the `Transport` Protocol is fine for a focused client-unwrap unit test, but the stdio path must use the real fixture subprocess.)
- Cases: (1) **HTTP parity** — existing AD-449/AD-597f suites stay green **unchanged** (run them; do not edit them); (2) stdio `initialize` handshake succeeds; (3) `tools/list` returns the fixture's tools; (4) `tools/call` round-trips; (5) `close()` terminates the subprocess (assert `proc.returncode is not None`); (6) command **not** on allowlist → `register_stdio_server` returns `False`, **no subprocess spawned**, `MCP_BRIDGE_FAILED` reason=`command_not_allowed`; (7) `consent_fn` returns `False` → returns `False`, no spawn, reason=`consent_denied`; (8) `stdio_enabled=False` → returns `False`, no spawn, **no event**; (9) bad-JSON / timeout from the server → `MCPProtocolError` (reason `bad_json`/`timeout`), honest-degrade, **bridge still usable** for the next call; (10) a leading `notifications/*` line is skipped and the matching `id` envelope is returned; (11) config validator: `stdio` without `command` rejected, `http` without `url` rejected, default `type=="http"`, existing `{url, headers}` still parse.
- Run the **existing** MCP suites to prove HTTP byte-identical (**serial — `-n auto` is forbidden until AD-682**): `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "mcp or ad449 or ad597" -q -n 0 -p no:cacheprovider`. They already exercise `Mcp-Session-Id` capture + the request-direction header; they MUST pass **unchanged** (proof the `HttpTransport` extraction is byte-identical). New AD-1014 tests run `-n 0`; the full gate is `-n 4 --dist=loadfile`.

## 6. Do NOT change

- ❌ HTTP transport wire behavior (parity is a hard gate).
- ❌ `external_discovery` (already transport-agnostic).
- ❌ No pack `mcpServers` wiring (AD-1015), no OS sandbox (#936 Tier-2), no marketplace UI, no runtime-venv installs.
- Default-OFF: with `stdio_enabled=False` and an empty `servers` list, behavior is byte-identical to today.

## 7. Acceptance

All of §5 green; existing MCP suites green unchanged; `stdio_enabled=False` ⇒ no behavior change; command allowlist + consent gate enforced before any spawn; honest-degrade on spawn/crash/timeout; full type annotations on new public APIs; async hygiene (hold task refs, handle cancellation, `create_task` not `ensure_future`); **verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 8. Files the Builder will create / modify

**Create**
- `src/probos/integrations/mcp_bridge/transport.py` — `Transport` Protocol, `HttpTransport`, `StdioTransport`.
- `tests/test_ad1014_stdio_mcp_transport.py` — the AD-1014 suite.
- `tests/fixtures/echo_mcp_server.py` — NDJSON echo MCP fixture server.

**Modify**
- `src/probos/integrations/mcp_bridge/client.py` — `MCPProtocolError(reason=…)`; `MCPClient.__init__(transport=None …)` default → `HttpTransport`; `_call` wraps `transport.request` (single emit site); `initialize()` reads `transport.last_metadata`. **No HTTP wire-behavior change.**
- `src/probos/integrations/mcp_bridge/bridge.py` — `__init__(stdio_enabled, command_allowlist, consent_fn)`; new `async register_stdio_server(...)`. `register_server` unchanged.
- `src/probos/integrations/mcp_bridge/__init__.py` — re-export `Transport`/`HttpTransport`/`StdioTransport` **only if** the package `__init__` already re-exports symbols (verify and mirror; do not invent an export style).
- `src/probos/config.py` — `MCPServerConfig` (+`type`/`command`/`args`/`env`/`cwd`/`timeout_seconds`, optional `url`, `model_validator`); `MCPConfig` (+`stdio_enabled`/`command_allowlist`).
- `src/probos/startup/finalize.py` L3269–3284 — pass new bridge args + `_mcp_consent`; add the inert-by-default stdio registration loop.

**Do NOT touch:** `external_discovery.py`, `egress.py`, `hooks/*`, the `system.yaml` server list, any pack/`mcpServers` wiring.

---

## 9. Verified against codebase (2026-06-15)

```
AD ceiling : git grep "### AD-1NNN" DECISIONS.md → highest AD-1013  (AD-1014 correct, no collision)
client.py        : _call HTTP body; _last_response_headers["mcp-session-id"]; request-header Mcp-Session-Id inject; JSONRPC_VERSION="2.0"; MCP_PROTOCOL_VERSION="2025-03-26"; clientInfo{probos,0.1.0}; MCP_BRIDGE_FAILED/_INVOKE; MCPProtocolError(bare Exception)
session.py       : frozen MCPSession{server_url, session_id="", headers, capabilities}
bridge.py        : MCPBridge.__init__(*, egress_policy=None, emit_event=None, request_timeout=30.0); register_server(url, headers)->bool (sync); invoke/get_client/list_servers/close_all; self._clients: dict[str, MCPClient]
config.py L3519  : MCPServerConfig{url: str (required), headers}  |  L3526 MCPConfig{enabled, request_timeout_seconds, servers}
finalize.py L3269: MCP block inside `async def finalize_startup` (L2422; no top-level def between) — register_server(srv.url, headers=dict(srv.headers)) sync, no await
hooks/bus.py     : async fire(event, ctx)->AggregateDecision; .allowed/.asked/.denied; PRE_TOOL_USE gate; unwired bus → ALLOW
hooks/handlers.py: make_capability_gate_handler(intent_grant_store)->HookHandler — PreDispatch agent-intent gate (precedent only; NOT the MCP gate)
egress.py        : EgressPolicy.is_allowed(url)->bool (URL host parse; HTTP-only)
runtime.py L1312 : def emit_event(self, event, data=None) -> None  (sync)
system.yaml L987 : mcp: {enabled: true, request_timeout_seconds: 30.0, servers: []}
```
