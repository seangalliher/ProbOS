# AD-706 Build Report

**Wave:** 132 (single-prompt)
**Date:** 2026-05-08
**Builder mode:** continuous, single-AD
**Status:** SHIPPED

## Summary

Shipped `BrowserTool` (the AD-423a Tool Layer implementation), `BrowserSession`
(one Playwright `BrowserContext` per session, 30-min TTL), and a 10-action
vocabulary (`goto`, `state`, `click`, `type`, `scroll`, `screenshot`, `wait`,
`back`, `forward`, `extract_text`). Default-disabled per Wave 10 convention
\#14. Closes [#482](https://github.com/seangalliher/ProbOS/issues/482).

## Section audit

| Spec section | Implemented in |
|---|---|
| D1 — `BrowserTool` + `BrowserSession` + `_DomainRateState` | `src/probos/tools/browser/tool.py`, `session.py`, `actions.py`, `__init__.py` |
| D2 — 10-action vocabulary + XGA scaling | `actions.py:_HANDLERS` + `_action_screenshot` |
| D3 — Session lifecycle, default 30 min, reaper task ref held | `tool.py:BrowserTool.stop`, `reap_expired`; `session.py:is_expired` |
| D4 — `BrowserToolConfig` + `tier_3_domain_patterns` declared + SystemConfig field | `config.py:BrowserToolConfig`, `config.py:SystemConfig.browser_tool` |
| D5 — Audit allowlist (7 keys, strict) | `tool.py:_AUDIT_DETAIL_ALLOWLIST` + `_audit` + `_sanitize_url` |
| D6 — Domain allow/denylist + tier classifier + 5-point token flow | `tool.py:_check_domain`, `actions.py:classify_action`, `tool.py:_generate_confirmation_token` / `_consume_confirmation_token` |
| D7 — `_wire_browser_tool` + new EventType values | `events.py` (4 new EventTypes), `startup/finalize.py:_wire_browser_tool` (def near `_wire_classification_gate`; call after `_wire_mcp_app_host`) |
| D8 — `[browser]` optional dep | `pyproject.toml:[project.optional-dependencies] browser` |
| D9 — \u2265 20 tests | `tests/test_ad706_browser_tool.py` (23 tests; one gated on `PROBOS_PLAYWRIGHT_REAL=1`) |

## Pre-flight checks (per `.github/copilot-instructions.md` + Wave 132 dispatch)

- **Working-tree integrity (numstat sort):** clean. Only `prompts/wave-plan.yaml` showed prior diff (expected).
- **AD-numbering re-verification:** `Get-ChildItem -Recurse -File -Include "*.md" | Select-String "AD-706"` returned only roadmap reservation rows + Wave 132 review/prompt docs. No live `### AD-706` entry in `DECISIONS.md` or any `decisions-era-*.md`. Safe to author.
- **Lazy Playwright import:** `from playwright.async_api import async_playwright` lives inside `BrowserSession.start()` and inside the wirer's import-probe try/except. Module-level imports in `session.py` and `tool.py` do not reference Playwright. Default install does not crash.
- **Default-disabled invariant:** `BrowserToolConfig.enabled = False` (Field default). Test `test_default_disabled_invariant` asserts.
- **Optional-dep test gating:** all 22 mocked tests pass without Playwright; the single `test_real_chromium_goto_about_blank` is `@pytest.mark.skipif(env != "1")` and SKIPPED in the gate run.
- **`_wire_mcp_app_host` line at dispatch time:** confirmed at `finalize.py:3214`. New AD-706 wire call inserted at `finalize.py:3220` (immediately after `_wire_mcp_app_host` block, before `_wire_spatial_explorer`). Relative ordering invariant preserved.
- **Pre-commit deletion check:** `git diff --cached --numstat | Sort -Desc` showed max 2 deletions (the AD-706 backlog row in `roadmap.md` reflowed to "Built" in the upper Federation table). Well under 200-line threshold.

## Test results

| Stage | Command | Result |
|---|---|---|
| Baseline | `pytest tests/ -q -n 8 --dist=loadfile` | 12873 passed, 18 skipped |
| Focused | `pytest tests/test_ad706_browser_tool.py -v -n 0` | 22 passed, 1 skipped (gated real Playwright) |
| Full gate | `pytest tests/ -q -n 8 --dist=loadfile` | 12895 passed, 19 skipped (+22 / +1) |

Net delta vs baseline: **+22 passing, +1 skipped**, fully matching the prompt's "expect ~+20" target. All other test files unaffected.

## Hidden gotchas worth flagging

1. **`.gitignore` rule `tools/` matched the new `src/probos/tools/browser/` package** \u2014 the four package files were initially excluded by `git add -A`. Resolved with `git add -f src/probos/tools/browser/{__init__.py,tool.py,session.py,actions.py}`. Pre-existing `src/probos/tools/*.py` are tracked because they pre-date the rule. Worth a follow-up nit to scope the rule to root `^tools/` only (out of scope for this AD per Non-Goals).
2. **`BrowserSession._domain_state` is a `ClassVar` shared across all session instances** \u2014 mirrors `HttpFetchAgent._domain_state` discipline. Tests using `headless=False` and `enabled=True` configs do not pollute each other because the keys are real hostnames; no test in this AD intentionally exercises cross-test rate-state leak.
3. **Tier-3 short-circuit returns `ToolResult` with `error=None`, `output={"intervention_required": True, ...}`** \u2014 not an error result. The Captain-watch surface (v2) and the agent-side handler must check `output.intervention_required` rather than `result.error`. The strict-audit row records `success=False, error="intervention_required"` so the audit trail is unambiguous even though the agent-side `ToolResult.success` is True.

## Forward markers (out of scope for v1)

- **AD-706a** \u2014 Captain-watch CDP/WebSocket bridge populating `BrowserSession.get_streaming_url()`.
- **AD-706b** \u2014 Session video recording (`record_video_dir`).
- **AD-706c** \u2014 OmniParser-style vision-based extraction (architecture-only absorption due to AGPL on `icon_detect`).
- **AD-706d** \u2014 LLM-driven tier classifier replacing the rule-based one in `actions.py:classify_action`.
- **AD-706e** \u2014 Action vocabulary v2 (`drag`, `key_combo`, `mouse_move`, `mouse_button`, `upload_file`, `download`, `eval_js`).
- **AD-706f** \u2014 Credential vault integration.

## McpAppFrame integration status

Confirmed deferred to v2 per prompt Non-Goals. `BrowserSession.get_streaming_url()` returns `None` in v1; `test_get_streaming_url_returns_none_in_v1` asserts the contract. The dispatch's `McpAppFrame` reference does not match a real class in HEAD; v1 ships the stub only.

## Quarantines

None.
