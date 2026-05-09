# Review: AD-706 v1 — BrowserTool (Computer Use via Playwright)

**Verdict:** ⚠️ Conditional
**Pass:** 1
**Date:** 2026-05-08
**Required: 1 / Recommended: 3 / Nits: 2**

The prompt absorbed all six dispatch contradictions surfaced during drafting and the Verified-Against block grounds every concrete claim at HEAD. One Required gap remains: a config field referenced in D6 (`tier_3_domain_patterns`) is not declared in the D4 `BrowserToolConfig` model. Because the prompt is medium-risk and is the sole prompt in the wave, it falls within the relaxed "1 ⚠️ on highest-risk-in-wave" tolerance per Wave 10 convention #15. One revision cycle resolves; deeper rework is not warranted.

## Required (must fix before building)

1. **D4/D6 field-name contradiction — `BrowserToolConfig.tier_3_domain_patterns` is referenced but never declared.**
   D6 says: *"URL host matches `BrowserToolConfig.tier_3_domain_patterns` (financial: `*bank*`, `*paypal*`, `*stripe*`, `*chase*`, `*coinbase*`, `*checkout*`)."* But the `BrowserToolConfig` model in D4 has no `tier_3_domain_patterns` field. Either:
   - **(a)** Add the field to D4: `tier_3_domain_patterns: list[str] = Field(default_factory=lambda: ["*bank*", "*paypal*", "*stripe*", "*chase*", "*coinbase*", "*checkout*"])`, OR
   - **(b)** Inline the list as a module-level constant in `tool.py`/`actions.py` and remove the config reference from D6.
   Without one of these, Builder will hit a `AttributeError: 'BrowserToolConfig' object has no attribute 'tier_3_domain_patterns'` on first tier-3 invocation.

## Recommended

1. **Tier-3 confirmation token flow is under-specified.**
   D6 says the agent "receives `ToolResult(output={"intervention_required": True, "tier": 3, "session_id": ...})`" and the Captain reissues with `params["confirmation_token"]` set to "the token returned in the intervention event payload." But the prompt does not state:
   - Where the token is generated (presumably `uuid4()` inside `_emit_intervention_required`).
   - That the token surfaces in the `TOOL_INTERVENTION_REQUIRED` event payload only (Captain-visible bus subscriber), not in the agent-visible `ToolResult.output`.
   - Whether the agent itself can autonomously retry, or whether re-issue is strictly a human-in-loop operator action.
   Add a one-paragraph "Confirmation token flow" subsection to D6 stating: token = uuid4 generated when tier-3 short-circuits; surfaces only in the event payload; consumed exactly once from `_pending_confirmations`; expires after `confirmation_timeout_seconds`. v1 = human-in-loop reissue (no autonomous agent retry).

2. **Action boundary-test gap — 6 of 10 actions have no dedicated test.**
   Per the standing rule "each public action has happy + error + edge case test", D9 covers `goto` (#3, #4, #5), `state` (#6), `click` (#7, #8, #9), `screenshot` (#10). Missing dedicated tests for: `type`, `scroll`, `wait`, `back`, `forward`, `extract_text`. Add at least one happy-path test per action (six new tests, light fakes — not blocking but meaningful coverage drift). Total target: ~20 tests rather than 14.

3. **Possible DRY violation — local `_DomainRateState` redefines `agents/http_fetch.py:23 DomainRateState`.**
   The prompt's `_DomainRateState` dataclass duplicates `DomainRateState` (already public in `agents/http_fetch.py`). Either import the existing class (`from probos.agents.http_fetch import DomainRateState`) or strengthen the docstring justification ("different semantics" — name them: e.g., default min interval differs, no 429 backoff because Playwright doesn't surface response headers uniformly). The redefinition is not wrong, but Builder will likely flag it during self-review.

## Nits

- **D7 wirer call-site line number drift.** "before the AD-697 extension dispatcher block (line ~3828)" — the existing `_wire_mcp_app_host` call site is at finalize.py:3214 in HEAD. Restate as "immediately after the existing `_wire_mcp_app_host(runtime=runtime, config=config)` call (line ~3214)" for precision.
- **D5 audit detail field allowlist.** D5 says "do not log `params.text` or `params.url` query strings verbatim" but the audit-detail JSON schema is informally listed (`session_id, action, agent_id, success, error?, tier`). Promote the redaction rule to an explicit allowlist (whitelist exactly those six keys + a sanitized `url`) so Builder can implement defense-in-depth without ambiguity.

## Verified Improvements (vs draft / dispatch)

Phantom-API sweep at HEAD — all cited symbols confirmed present:

| Claim | HEAD evidence |
|---|---|
| `ToolType.BROWSER`, `ToolType.COMPUTER_USE` | `protocol.py:21–22` |
| `ToolResult(output, error, duration_ms, metadata)` | `protocol.py:69–80` |
| `Tool` Protocol with 7 members (`runtime_checkable`) | `protocol.py:84` |
| `ToolPermission.{NONE,OBSERVE,READ,WRITE,FULL}` | `protocol.py:29–43` |
| `ToolRegistry.register(*, domain, department, tags, provider, enabled, default_permissions, restricted_to, concurrency, lock_timeout_seconds)` | `registry.py:92–122` |
| `ToolRegistry.get_tool(tool_id)` | `registry.py:142` |
| `ToolRegistry.check_and_invoke()` | `registry.py:269` |
| `ToolContext.invoke()` | `context.py:107` |
| `ToolExecutor.invoke()` calls `registry.check_and_invoke()` | `executor.py:69, 123` |
| `make_audit_hook` emits `EventType.TOOL_INVOKED` | `executor.py:148, 158` |
| `AuditLog.append(*, category, detail)` | `security/audit.py:67` |
| `runtime.audit_log = AuditLog(emit_event=runtime.emit_event)` | `finalize.py:2296` |
| `runtime.tool_registry = comm.tool_registry` | `runtime.py:1747` |
| `HttpFetchAgent._domain_state: ClassVar[dict[str, DomainRateState]]` | `http_fetch.py:80` (note: `DomainRateState`, not `_DomainRateState`) |
| `EventType.TOOL_INVOKED`, `TOOL_PERMISSION_DENIED` | `events.py:196–197` |
| No `TOOL_INTERVENTION_REQUIRED` or `BROWSER_*` (correctly introduced new) | `events.py` |
| `validation_framework: ValidationFrameworkConfig` | `config.py:3000` |
| `mcp_app_host: MCPAppHostConfig` | `config.py:3014` |
| `_wire_creative_expression`, `_wire_classification_gate`, `_wire_mcp_app_host` | `finalize.py:80, 105, 963` |
| `class InterventionType(str, Enum)` (Counselor-only) | `cognitive/counselor.py:123` |
| `playwright` not in `pyproject.toml` (correctly added new optional group) | `pyproject.toml:47` |

Six dispatch contradictions absorbed into the prompt body:

| # | Dispatch claim | Prompt resolution |
|---|---|---|
| 1 | `ToolResult.data` | D2 dispatch sketch + table use `ToolResult.output` consistently; documented in top Verified block |
| 2 | "AD-451 SafetyClassifier" | Verify block + D6 verify-first note: AD-451 is `ValidationFrameworkConfig`; rule-based classifier ships self-contained in D6 |
| 3 | "AD-561 Intervention Classification" | Verify block + D6 verify-first note: `InterventionType` is Counselor-only (`counselor.py:123`); same rule-based classifier ships in D6 |
| 4 | `tool_intervention_required` event | Verify block: not in HEAD; D7 introduces `TOOL_INTERVENTION_REQUIRED` + `BROWSER_*` |
| 5 | `McpAppFrame` class | Verify block + Non-Goals: not a real class; v1 stubs `BrowserSession.get_streaming_url() -> None`; v2 (AD-706a forward marker) populates it |
| 6 | `HttpFetchAgent._domain_state` reuse | D1 mirrors with new local `_DomainRateState` ClassVar; documented as "different semantics" (see Recommended #3) |

Other standing-checklist confirmations:

- ✅ 10-action vocabulary stable; `state()` indexed-element absorption from browser-use is the cornerstone (D2 table, `input_schema` enum, description property).
- ✅ XGA 1024×768 in D2 `screenshot` row AND `BrowserToolConfig.screenshot_max_{width,height}` defaults (D4).
- ✅ 4-point Anthropic safety block verbatim with `Source: anthropics/claude-quickstarts/computer-use-demo, MIT-licensed.` attribution; mapped to v1 implementation.
- ✅ Lazy Playwright import in two places: `BrowserSession.start()` body (D1) and `_wire_browser_tool` body (D7). Module-level imports in D1 file headers do not pull `playwright`.
- ✅ `enabled: bool = False` default per Wave 10 convention #14.
- ✅ Pre-flight working-tree integrity check is the first Acceptance bullet (`git diff --numstat | sort -k2nr | Select-Object -First 5`; >200 deletions on any tracked file = STOP).
- ✅ AD-numbering re-verification at commit time per `.github/copilot-instructions.md` is in Acceptance.
- ✅ `domain_denylist: list[str] = Field(default_factory=list)` — no bare mutable default.
- ✅ AD-448 audit hook attribution: `BrowserTool` does NOT double-emit `TOOL_INVOKED`; D5 explicitly states this and adds a single per-invoke `audit_log.append(category="browser_tool", ...)` row instead.
- ✅ AD-456 hash chain: `runtime.audit_log` available; D5 wires through it.
- ✅ Default install (`pip install -e .[dev]`) does not pull `playwright`; new `[browser]` extras group added separately (D8).
- ✅ Permission registration uses lowercase string values matching `ToolPermission` enum string values (`"none"`, `"read"`, `"write"`, `"full"`).
- ✅ Tier-3 short-circuit and confirmation hook are protocol-stable: a future LLM-driven classifier (AD-706d marker) replaces internals without changing call sites.
- ✅ v2 forward marker for Captain-watch streaming surface (AD-706a) preserved via `BrowserSession.get_streaming_url() -> None` stub.
- ✅ Test isolation: each test builds its own `BrowserToolConfig` and `BrowserTool`; integration test gated on env var.
- ✅ Async discipline: `BrowserTool._reaper_task` reference held; cancellation handled in `BrowserTool.stop()`.

## Pass 2 Review

**Verdict:** ✅ Approved
**Pass:** 2 (post-revision)
**Date:** 2026-05-08
**Required: 0 / Recommended: 0 / Nits: 0**

All five Pass-1 issues resolved. Grep self-checks and HEAD phantom-API spot-checks pass cleanly. Wave 132 cleared for Builder dispatch.

### Required (Pass 1) — resolution

1. ✅ **	ier_3_domain_patterns declared in D4 + referenced in D6.** Field declared at lines 396–406 with the 6-entry default factory; D6 reference at line 475 now resolves. No orphan references.

### Recommended (Pass 1) — resolution

1. ✅ **Tier-3 confirmation token flow specified.** D6 lines 481–489: 5-point subsection covering Generation (uuid4.hex), Surface boundary (event payload only, not ToolResult.output), Reissue (strictly human-in-loop in v1), Consumption (single-use pop with session/action validation), Expiry (opportunistic reaper prune).
2. ✅ **Action boundary tests added.** D9 now lists 20 tests (#15–#20: type, scroll, wait, back, forward, extract_text). Standing rule "one boundary test per public action" satisfied.
3. ✅ **_DomainRateState justification strengthened.** D1 lines 185–207: docstring names three concrete divergences from gents/http_fetch.py:DomainRateState (default min_interval, no 429 backoff because Playwright doesn't surface Retry-After uniformly, BrowserSession-scoped not class-shared).

### Nits (Pass 1) — resolution

1. ✅ **D7 line drift.** "line ~3214" replaces "~3828" with explicit advisory note that ordering (after _wire_mcp_app_host) is the invariant. Grep `3828` returns 0 hits in normative content.
2. ✅ **D5 audit allowlist formalized.** D5 lines 487–497: 7-key table (session_id, action, agent_id, success, error?, tier, url_sanitized?) with explicit forbidden-keys list (params.text, params.url verbatim, POST bodies, cookies, state() text).

### Grep self-check results

| Pattern | Expected | Actual | Result |
|---|---|---|---|
| `tier_3_domain_patterns` | hits in D4 + D6 | line 396 (D4 decl), line 475 (D6 ref), lines 720+731 (audit narration) | ✅ |
| `3828` | 0 in normative | 0 normative; 2 audit-narration hits at lines 724, 732 | ✅ |
| `confirmation_token` | hit in D6 body | lines 139, 324, 479, 483–486, 586 | ✅ |

### Phantom-API spot-check at HEAD

| Symbol | HEAD evidence |
|---|---|
| `ToolResult.output` | 	ools/protocol.py:72 `output: Any = None` |
| `ToolType.BROWSER` | 	ools/protocol.py:23 `BROWSER = "browser"` |
| `_wire_mcp_app_host` call site | startup/finalize.py:3214 (matches D7 advisory line ~3214) |
| `AuditLog.append(*, category, detail)` | security/audit.py:67 `def append(self, *, category: str, detail: str) -> AuditEntry` |

All four symbols confirmed at HEAD. No phantom APIs.

### Wave APPROVED for Builder dispatch (gate-1): **YES**

### Recommended Builder pre-flight

1. **Working-tree integrity check** (per architect learnings 2026-05-08): run `git diff --numstat | sort -k2nr | head -5` and verify no unexpected tracked-file deletions before starting.
2. **Confirm _wire_mcp_app_host line number at dispatch time.** D7 cites line ~3214 (verified 2026-05-08); if HEAD has drifted, preserve relative ordering (after _wire_mcp_app_host, before AD-697 extension dispatcher) rather than the literal line number.
3. **Lazy Playwright import.** D1 explicitly requires rom playwright.async_api import async_playwright inside BrowserSession.start(), NOT at module level. The default install (no [browser] extra) must not crash on import.
4. **Optional-dep test gating.** Tests #1–#13, #15–#20 must run without Playwright installed (use _FakePage/_FakeContext/_FakeBrowser stubs). Only test #14 may require PROBOS_PLAYWRIGHT_REAL=1.
5. **Default-disabled invariant.** BrowserToolConfig.enabled defaults False; `_wire_browser_tool` returns False when disabled. Verify no test enables it globally via fixture leak.

