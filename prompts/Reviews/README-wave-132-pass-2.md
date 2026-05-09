# Wave 132 — Pass 2 Review Summary

**Date:** 2026-05-08
**Wave:** 132 (single-prompt: AD-706 BrowserTool v1)
**Verdict:** ✅ **APPROVED for Builder dispatch (gate-1)**

## Pass-2 Tally

| Tier | Pass 1 | Pass 2 | Status |
|---|---|---|---|
| Required | 1 | 0 | ✅ All resolved |
| Recommended | 3 | 0 | ✅ All resolved |
| Nits | 2 | 0 | ✅ All resolved |

No Pass-1 issue flagged a second time. Pass-2 bar (any Required = ❌; any Recommended re-flagged = ⚠️) cleared.

## Resolutions

| # | Tier | Pass-1 issue | Pass-2 resolution |
|---|---|---|---|
| 1 | Required | `tier_3_domain_patterns` referenced in D6 but undeclared in D4 | Field declared in D4 (lines 396–406) with 6-entry default factory; D6 reference (line 475) resolves |
| 2 | Recommended | Tier-3 confirmation token flow under-specified | D6 lines 481–489: 5-point subsection (Generation/Surface boundary/Reissue/Consumption/Expiry); v1 strictly human-in-loop |
| 3 | Recommended | 6 of 10 actions had no dedicated test | D9 expanded to 20 tests; #15–#20 cover type, scroll, wait, back, forward, extract_text |
| 4 | Recommended | `_DomainRateState` redefinition vs `agents/http_fetch.py:DomainRateState` | D1 docstring (lines 185–207) names 3 concrete divergences (default interval, no 429 backoff, session-scoped) |
| 5 | Nit | D7 cited finalize.py line ~3828 (HEAD is 3214) | D7 line 551: "~3214" with advisory note; relative ordering after `_wire_mcp_app_host` is the invariant |
| 6 | Nit | D5 audit detail informally listed | D5 lines 487–497: 7-key allowlist table + explicit forbidden-keys list |

## Grep self-checks

| Pattern | Required | Result |
|---|---|---|
| `tier_3_domain_patterns` | Hits in BOTH D4 + D6 | ✅ Line 396 (D4 declaration), line 475 (D6 reference) |
| `3828` | 0 hits in normative content | ✅ 0 normative; 2 hits confined to Revision audit (lines 724, 732) |
| `confirmation_token` | Hits in D6 body | ✅ Lines 139, 324, 479, 483–486, 586 |

## Phantom-API spot-check at HEAD

| Symbol | HEAD evidence | Status |
|---|---|---|
| `ToolResult.output` | `tools/protocol.py:72` | ✅ |
| `ToolType.BROWSER` | `tools/protocol.py:23` | ✅ |
| `_wire_mcp_app_host` call site | `startup/finalize.py:3214` | ✅ matches advisory `~3214` |
| `AuditLog.append(*, category, detail)` | `security/audit.py:67` | ✅ |

No phantom APIs. All four symbols confirmed.

## Builder pre-flight checklist

Before starting AD-706:

1. **Working-tree integrity.** Run `git diff --numstat | sort -k2nr | head -5`. Any tracked-file deletion >200 lines that the Builder did not author is a hard stop.
2. **Confirm `_wire_mcp_app_host` line at dispatch time.** D7 cites `~3214` (verified 2026-05-08). If HEAD has drifted, preserve relative ordering (after `_wire_mcp_app_host`, before AD-697 extension dispatcher) — line numbers are advisory.
3. **Lazy Playwright import.** D1 requires `from playwright.async_api import async_playwright` inside `BrowserSession.start()`, NOT at module level. Default install (no `[browser]` extra) must not crash on import.
4. **Optional-dep test gating.** Tests #1–#13, #15–#20 must run without Playwright via `_FakePage`/`_FakeContext`/`_FakeBrowser` stubs. Only test #14 may require `PROBOS_PLAYWRIGHT_REAL=1`.
5. **Default-disabled invariant.** `BrowserToolConfig.enabled` defaults False; `_wire_browser_tool` returns False when disabled. Verify no fixture leak globally enables it.

## Wave 132 dispatch

- **Single prompt:** `prompts/ad-706-browser-tool-v1.md`
- **Estimated tests:** ≥20 (D9 explicit list)
- **Risk tier:** Medium (new external dependency, security-sensitive surface)
- **Builder mode:** continuous (single AD = single commit)
- **Test gate:** `pytest tests/test_ad706_browser_tool.py -v -n 0` for focused; full parallel `-n 4 --dist=loadfile` post-commit
