# Review: AD-449 — MCP Bridge (v1 OSS Infrastructure)

**Verdict:** ⚠️ Conditional — boundary-language tightening needed (specific commercial connector names appear in shipping prompt body; mechanical reframing) + class-attribute mutable-default bug. The v1 OSS infrastructure design itself is sound.

**Date:** 2026-05-02

**Headline:** Lines 8 and 40 of the prompt body name "Salesforce, ServiceNow" by name — even in negative ("not in scope") framing. Per dispatch verification point #1 strict reading, any mention of those names in shipping content surfaces. Recommend reframing to generic categories. Also: Section 3's `_last_response_headers` is a class attribute mutable default (race risk).

---

## Required (must fix before building)

1. **Commercial-connector names in shipping content (lines 8, 40).** Dispatch verification point #1 grep:

   - Line 8: *"pre-built MCP server packs (Salesforce, ServiceNow, ERP-specific implementations, etc.)"*
   - Line 40: *"Pre-built MCP server packs (Salesforce, ServiceNow, ERP, CRM connectors)"*

   Per dispatch's hard-stop interpretation: *"If any hit appears in shipping content, Required finding — surface immediately."*

   Architect interpretation: both mentions are in **negative framing** — the boundary alert (line 8) and the deferral list (line 40) explicitly mark those names as NOT shipping. The intent is correct (commercial-boundary preservation). But the strict pre-commit-hook regex would still flag them.

   **Fix (mechanical):** rewrite both lines to use generic categories without specific connector names. Example replacement:

   - Line 8 → "pre-built MCP server packs (commercial server-pack catalog) — out of scope here"
   - Line 40 → "Pre-built MCP server packs (commercial connector catalog) — out of scope; live in the private commercial repo"

   The intent (clarifying what's deferred) is preserved; the specific connector names are removed.

   This is the AD-450 leak precedent: even negative framing in shipping content creates a name-association in the OSS repo. Strict reading wins.

2. **`_last_response_headers: dict[str, str] = {}` is a class-attribute mutable default.** Section 3 line 307:

   ```python
       _last_response_headers: dict[str, str] = {}
   ```

   This is a Python anti-pattern. All `MCPClient` instances share the same dict. `initialize()` writes to it from one client; another concurrent client's read returns the wrong session header. **Fix:** initialize as an instance attribute in `__init__`:

   ```python
   def __init__(self, *, session, ...):
       ...
       self._last_response_headers: dict[str, str] = {}
   ```

   Drop the class-level declaration.

3. **Test #5 (`test_mcp_client_initialize_returns_session_with_capabilities`)** asserts the returned session has the capabilities — but the implementation captures `session_id` from response headers via `self._last_response_headers.get("mcp-session-id", "")`. The headers are set inside `_call()` BEFORE the response is parsed (line 261-263). If the test mocks only the response body, the headers will be empty and `session_id` will be `""`. The test must mock both the JSON body AND the response headers to validate `session_id` capture. **Fix:** spec the test to mock `httpx.Response.headers` explicitly, OR add a separate test for header-driven session_id capture.

---

## Recommended

1. **Section 5 `MCPToolAdapter` is documented as "v1 ships the adapter class with `name`/`server_url`/`tool_name`/`description`/`input_schema`/`invoke()` surface. The actual `tool_registry.register(...)` call site is wired by AD-449b."**

   This is honest deferral, but the v1 deliverable list says "MCPToolAdapter — real ToolRegistry integration; remote tools become first-class ProbOS tools." The reality is that AD-449 v1 ships a class that COULD become a first-class tool but isn't actually registered. The Solution Overview should match the deferral note. **Fix:** update line 35 of the v1 scope bullet to: "MCPToolAdapter — real wrapper class; ToolRegistry registration loop deferred to AD-449b."

2. **`MCPClient._http` — `httpx.AsyncClient` constructed in `__init__`.** Synchronous instantiation in `__init__` is fine. But the class doesn't use an async context manager (`async with`). In `close()` the client is closed manually — Builder's tests must call `close()` explicitly or `httpx` will warn about unclosed clients at gc time. Recommend either using a lazy-init pattern (construct on first `_call`) OR documenting that consumers must call `close()` (which the prompt does for `MCPBridge.close_all()`).

3. **Section 7 `MCPConfig.servers: list[MCPServerConfig]` — operator-supplied URLs.** No EgressPolicy preflight on these URLs at startup. If `MCPConfig.servers = [MCPServerConfig(url="https://evil.com/mcp")]` and the EgressPolicy denies `evil.com`, the registration succeeds but every call fails. Recommend an explicit `register_server(...)` log line at startup-wiring time stating which servers were registered, so operators can spot-check.

4. **`MCPClient._call` rejects on egress policy block but doesn't differentiate "would-have-blocked" from "did-block".** The `EGRESS_BLOCKED` event from AD-456 already fires when the policy decides; AD-449's `MCP_BRIDGE_FAILED reason="egress_blocked"` is a second signal for the same denial. Recommend a comment noting the dual emission is intentional (two perspectives on the same decision), OR consolidate to one event.

5. **MCP-protocol-version constant `"2025-03-26"`** matches a real MCP spec version. ✅. But MCP servers commonly negotiate down — the prompt doesn't handle the case where the server responds with a different `protocolVersion`. Recommend: if `result["protocolVersion"]` differs from the request, log + accept (assume server-side is authoritative). Defer "version mismatch handling" to AD-449e if scope blows up.

6. **JSON-RPC `id` is generated as `uuid.uuid4().hex`.** The MCP spec allows int or string IDs. Hex string is fine but slightly heavier. Trivial — not a fix request.

---

## Nits

- `JSONRPC_VERSION = "2.0"` is a module-level constant ✅
- `MCPProtocolError` extends `Exception` — fine; could be more specific (e.g., `MCPTransportError`, `MCPRPCError`) but not required.
- `Mcp-Session-Id` header normalization (lower-case lookup) is correct for httpx response headers (case-insensitive).
- Section 0 `MCP_BRIDGE_INVOKE` and `MCP_BRIDGE_FAILED` are free in `events.py`. ✅
- Section 7's `MCPConfig.request_timeout_seconds: float = Field(default=30.0, ge=1.0)` matches the existing config patterns. ✅
- `register_server` returns False on duplicate URL or empty URL — clean idempotency contract. ✅
- `close_all()` swallows exceptions per Wave 5 tier-2 log-and-degrade. ✅

---

## Verified (looks good)

- `Test-Path src/probos/integrations` returns False — AD-449 owns directory creation. ✅
- `class ToolRegistry` at `tools/registry.py:49`. ✅
- `class Tool(Protocol)` at `tools/protocol.py:83`. ✅
- `class ToolExecutor` at `tools/executor.py:40`. ✅
- `def register(` at `tools/registry.py:92`. ✅
- `async def check_and_invoke(` at `tools/registry.py:269`. ✅
- `class EgressPolicy` at `security/egress.py:47`; `def is_allowed(self, url: str) -> bool:` at `security/egress.py:66`. ✅
- `runtime.tool_registry = comm.tool_registry` at `runtime.py:1591`. ✅
- `runtime.egress_policy` is the AD-456 Wave 7 public attribute (verified). ✅
- 5 of 9 capabilities wholesale-deferred at draft time per convention #14. ✅
- No new HARD pyproject deps (httpx is pre-existing). ✅
- `Streamable HTTP` + `Mcp-Session-Id` header threading match current MCP spec. ✅
- v1 is client-only; ProbOS-as-server deferred to AD-449b — no theater. ✅

---

## Conventions audit

| # | Rule | Status |
|---|---|---|
| 1 | Public-attribute wiring | ✅ `runtime.mcp_bridge` public |
| 2 | stdlib-only | ✅ httpx pre-existing |
| 3 | Coordinator-then-dispatch | ✅ tool_registry registration deferred |
| 4 | Superset-filter | ✅ ToolRegistry/Executor unchanged |
| 5 | init_<phase> | ✅ Section 8 wires from finalize.py |
| 6 | Verify-first | ✅ |
| 7 | No-theater | ⚠️ Recommended #1 (Solution Overview overstates `MCPToolAdapter` integration) |
| 8 | TYPE_CHECKING + ALLOWED_EXCEPTIONS | N/A |
| 9 | ASCII-only comments | ✅ |
| 10 | work_item_store vs workforce | N/A |
| 11 | __new__-bypass defensive-getattr | ✅ `MCPClient.close` uses `getattr(self, "_http", None)` |
| 12 | Solution Overview drift | ⚠️ Recommended #1 |
| 13 | Pool template name collision | N/A |
| 14 | Aggressive pre-deferral | ✅ 5 of 9 |
| 15 | Tolerance: relaxed | ⚠️ accepted (HIGH-risk slot per dispatch) |
| Commercial boundary | OSS-only shipping content | ❌ Required #1 (specific connector names in shipping content; reframe to generic) |

---

## Bottom Line

The MCP Bridge design is solid. v1 ships a real JSON-RPC client with EgressPolicy gating; deferrals are explicit and honest. The Required findings are: (1) tighten boundary language to drop specific connector names, (2) fix the class-attribute mutable-default race, (3) tighten Test #5 to mock both body and headers. After revision, this prompt should converge to ✅ Approved.

Per convention #15 (relaxed tolerance), this is the wave's HIGH-risk slot where ⚠️ is acceptable. The boundary-language Required is mechanical and doesn't expand scope. Revisable in one pass.

---

## Second-Pass Review (2026-05-02)

**Verdict:** ✅ Approved

**Headline:** All 3 Required findings genuinely resolved; commercial-boundary scrub passes; class-attribute race eliminated; test #5 mocks both body and headers. AD-449 clears second-pass without needing the convention #15 ⚠️ tolerance reservation.

### Resolution Audit

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| R#1: Vendor names in shipping content | ✅ Resolved | Lines 8 + 40 reframed: line 8 "vendor-specific MCP server packs (third-party SaaS connector packs of any kind)"; line 40 "vendor-specific third-party connector catalog". **Post-revision grep on the entire prompt body for `Salesforce\|ServiceNow\|D365\|Workday\|SAP\|HubSpot\|Marketo\|Oracle` returns zero hits in shipping content.** Remaining mentions of "Salesforce/ServiceNow" appear ONLY in the Revision section's audit-trail documenting what was removed (meta-content). |
| R#2: `_last_response_headers` class-attribute mutable default | ✅ Resolved | Line 191: `self._last_response_headers: dict[str, str] = {}` — instance attribute in `__init__`. The class-level declaration `_last_response_headers: dict[str, str] = {}` is gone (was at line 307 in pass-1; verified absent post-revision). Race risk across MCPClient instances eliminated. |
| R#3: Test #5 mock both body + headers | ✅ Resolved | Test plan #5 rewritten: "mocked httpx returns body `{...,"result":{"capabilities":{...}}}` AND headers `{"mcp-session-id": "s-123"}`. The session has the capabilities AND `session_id == "s-123"`. The test must mock both `Response.json()` AND `Response.headers` to validate the header-driven session_id capture." |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| rec#1: MCPToolAdapter Solution Overview language | ✅ Applied | Line 35: "MCPToolAdapter — real wrapper class; ToolRegistry registration loop deferred to AD-449b." Convention #12 honored. |
| rec#2: httpx async-context-manager | 📦 Deferred | `MCPClient.close()` + `MCPBridge.close_all()` cascade is sufficient; deferring to AD-449b. |
| rec#3: log registered servers at startup | 📦 Deferred | Existing `logger.info("AD-449: MCPBridge wired ...")` is sufficient. |
| rec#4: dual-emission comment | 📦 Deferred | Architect judgment: dual emission intentional (event-bus + MCP-specific subscribers). |
| rec#5: protocol-version mismatch handling | 📦 Deferred | AD-449e scope. v1 uses fixed `MCP_PROTOCOL_VERSION = "2025-03-26"`. |
| rec#6: JSON-RPC `id` format | 📦 Deferred | Hex string is fine; no change. |

### New Findings (introduced during revision)

None. The revision touched only the four locations called out by R#1 (lines 8 + 40 reframing), R#2 (`_last_response_headers` instance attribute), R#3 (test #5 spec), and rec#1 (Solution Overview line 35). All targeted; no collateral drift.

### Verified Against Revised Codebase Claims (commercial boundary)

```
grep -in "salesforce\|servicenow\|d365\|workday\|sap \|hubspot\|marketo\|oracle\b" prompts/ad-449-mcp-bridge.md
  (zero hits in shipping content; only historical mentions in the Revision section
   audit trail at line 733 -- meta-content explaining what was removed)

grep -in "\$\d\|revenue\|subscription\|license fee\|customer count\|pilot\b\|reference engagement\|gtm" prompts/ad-449-mcp-bridge.md
  (only matches in negative-framing boundary alerts: "do not include",
   "no source/test/doc string mentions", and Revision-section audit trail.
   No positive shipping claims about pricing or commercial topics.)
```

### Verified Against Revised Codebase Claims (technical)

- `Test-Path src/probos/integrations` returns False — AD-449 owns directory creation ✅
- `class ToolRegistry` at `tools/registry.py:49`, `class Tool(Protocol)` at `tools/protocol.py:83`, `class ToolExecutor` at `tools/executor.py:40` ✅
- `class EgressPolicy` at `security/egress.py:47`; `def is_allowed` at `security/egress.py:66` ✅
- `runtime.tool_registry` wired at `runtime.py:1591` ✅
- `runtime.egress_policy` wired in `startup/finalize.py` per AD-456 Wave 7 ✅

### Tolerance Assessment (convention #15: relaxed)

AD-449 was the wave's HIGH-risk + commercial-boundary slot — the convention #15 ⚠️ tolerance was reserved for it. The revision pass cleared all 3 Requireds mechanically; ⚠️ tolerance is **not consumed**. Verdict ✅ Approved without needing the slack.

**Build-time reminder for Builder:** the test #5 mock spec requires both `Response.json()` and `Response.headers` to be mocked. Builder should use `MagicMock(spec=httpx.Response)` with both attributes set explicitly, rather than the simpler `AsyncMock(return_value={"result": ...})` pattern.
