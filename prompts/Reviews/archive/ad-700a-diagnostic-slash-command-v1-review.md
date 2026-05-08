# Review: AD-700a v1 — `/diagnostic` slash command in the HXI shell
**Verdict:** ⚠️ Conditional
**The `/diagnostic` surface is well-designed, but D1 step 4 defers the canonical Captain intent dispatch path to Builder ("Builder verifies the live shape — likely `await runtime.process_nl_intent(...)` or `runtime.intent_bus.broadcast(...)`"). That's an architect responsibility, not a Builder one — phantom-API risk.**

## Required (must fix before building)
1. **Spec the exact intent dispatch shape.** D1 step 4 lists *two* candidate paths (`runtime.process_nl_intent` vs. `runtime.intent_bus.broadcast`) and tells the Builder to verify. Architect must grep `experience/commands/commands_alert.py` (or whichever sibling slash issues an intent today) and write the exact call into the prompt. Three failure modes if left unspecified: (a) Builder picks the wrong path → DiagnosticianAgent never receives the intent → tests pass against a stub but ship behavior is broken; (b) Builder invents a synthesis like `runtime.process_nl(f"diagnose level={level.value}")` which bypasses the canonical Captain dispatch; (c) the test's "fake intent bus / runtime stub" (test #2) papers over the real failure. Pick one path; document the kwargs; cite the file:line.

## Recommended
1. **Test #8 patches `commands_diagnostic.cmd_diagnostic` and expects `_dispatch_slash` to invoke it** — but `_dispatch_slash` resolves the module attribute at call time (`commands_diagnostic.cmd_diagnostic`), so monkeypatch on the module attribute should work. Worth one line in the prompt confirming this: "monkeypatch `probos.experience.commands.commands_diagnostic.cmd_diagnostic` (module-level attribute, not the import in shell.py)." Otherwise Builder may patch the wrong path and the test silently passes against the un-patched original.
2. **`self.COMMANDS` registry update is hand-waved** ("Builder verifies its location by grepping the existing `cmd_help` consumer"). Cite the exact file/line of the `COMMANDS` dict at draft time — same architect-responsibility argument as Required #1.

## Nits
1. The dispatch's "DiagnosticLevel.parse_level()" mistake is correctly called out in verify-first — good. Consider promoting the correction into the Goal section so anyone reading top-down sees the right symbol shape immediately.
2. D2 panel renderer signature uses a forward-string type `"DiagnosticLevel"` — correct under `from __future__ import annotations`; the panels module needs to ensure that import is present.
3. The `_USAGE` constant pattern is sound but not specified — add it to D1's bullet list explicitly so the Builder doesn't omit it.

## Verified
- ✅ `parse_level` is module-level at `diagnostic_levels.py:69` (NOT `DiagnosticLevel.parse_level()`) — the prompt correctly catches the dispatch's mistake.
- ✅ `DiagnosticLevel` enum + `depth_rank`, `llm_tier`, `expected_duration_label` properties verified.
- ✅ `_dispatch_slash` at `shell.py:229` and `commands_clinical` import at `:25` — sibling pattern matches.
- ✅ DiagnosticianAgent `IntentDescriptor(name="diagnose_system", params={"focus", "level"})` accepts the kwargs the prompt issues.
- ✅ Scope discipline (no agent changes, no new EventType, no UI work).

## Risk
MEDIUM. The Required gap is a real phantom-API hazard. Once the intent path is pinned, the rest of the prompt is straightforward.

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved (was ⚠️ Pass-1) — Required finding closed; dispatch path pinned to scout precedent.

### Required / Recommended / Nits
None.

### Verified
- **Required #1 landed**: D1 step 4 uses canonical pool-lookup → `agent.handle_intent(IntentMessage(...))` shape, mirroring scout precedent at `commands_knowledge.py:130-148`. Verified at HEAD (lines 126-150 show exactly this dispatch shape). The "Builder picks one" deferral is gone.
- Pool name `medical_diagnostician` verified at `startup/fleet_organization.py:66`.
- **Recommended #1 landed**: Test #8 patches `probos.experience.commands.commands_diagnostic.cmd_diagnostic` (module-level attribute).
- **Recommended #2 landed**: D3 cites `self.COMMANDS` dict-literal at `shell.py:54-110` with exact entry to add.
- **Nit #1 landed**: Goal section uses module-level `parse_level()` shape correctly.
- **Nit #3 landed**: `_USAGE` constant explicitly listed.
- Phantom-API sweep: `parse_level` (module-level, `diagnostic_levels.py:69`), `DiagnosticLevel` (`:28`), pool name confirmed.
- 8 tests cover usage, parse, numeric, fallback, no-focus, panel render, error path, dispatch routing.
