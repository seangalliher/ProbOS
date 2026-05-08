# AD-700a /diagnostic Slash Command Build Report

**Title:** `/diagnostic` slash command in the HXI shell
**Prompt:** `prompts/ad-700a-diagnostic-slash-command-v1.md`
**Builder:** Builder agent (continuous-build, Wave 129)
**Date:** 2026-05-08
**Status:** SHIPPED

## Files Changed

- `src/probos/experience/commands/commands_diagnostic.py` — new (`_USAGE` constant + `cmd_diagnostic()` handler).
- `src/probos/experience/panels.py` — additive `render_diagnostic_result()` adjacent to `render_dag_result`.
- `src/probos/experience/shell.py` — 3 hooks: import `commands_diagnostic`, `COMMANDS` entry near `/clinical`, `_dispatch_slash` handler entry.
- `tests/test_layer_boundaries.py` — one new `ALLOWED_EXCEPTIONS` entry for the canonical-precedented experience→agents enum import.
- `tests/test_ad700a_diagnostic_slash_command.py` — new (9 tests).

## Sections Implemented

- **D1** New `commands_diagnostic.py` module with `_USAGE`, `cmd_diagnostic(runtime, console, args)`. Pool lookup + `agent.handle_intent` follows the scout precedent (`commands_knowledge.py:130-148`). Exception handler logs warning and prints `[red]` one-liner; never propagates. ✅
- **D2** `render_diagnostic_result(result, *, level)` in panels.py: header line shows level name + `depth_rank`/5 + `expected_duration_label`; severity-tinted (low=green, medium=yellow, high=orange1, critical=red); two-column Table; missing keys render as `--` placeholders. ✅
- **D3** `shell.py` wired: import alongside other `commands_*`, `COMMANDS` registry entry near `/clinical`, `_dispatch_slash` handler entry near `/clinical`. ✅
- **D4** 9 tests: empty-args usage, level token parse, numeric token parse, unknown token L3 fallback, no-focus passes empty, panel renders on success, runtime failure prints red and no traceback, dispatch routes to handler, registry entry exists. ✅

## Post-Build Section Audit

Every D# section maps to implemented code. Test #9 is an additional registry-existence assertion (above the 8-test minimum). No omissions.

## Test Results

- Focused: `pytest tests/test_ad700a_diagnostic_slash_command.py -v -n 0` → **9/9 pass** in 0.57s.
- Adjacent regression: `pytest tests/test_ad635e_clinical_shell_command.py -q -n 0` → **18/18 pass** in 0.52s.
- Layer-boundary: `pytest tests/test_layer_boundaries.py -q -n 0` → **2/2 pass** (after ALLOWED_EXCEPTIONS update).
- Full gate: `pytest tests/ -q -n 8 --dist=loadfile` → **12771 passed, 16 skipped, 175 warnings** in 8m01s. Test count up by 9 from AD-700c baseline (12762 → 12771).

## Deviations

- One additional file beyond the prompt's listed set: `tests/test_layer_boundaries.py`. This is not a deviation in spirit — the prompt requires the import that triggers the boundary check; adding the precedented `ALLOWED_EXCEPTIONS` entry is the standard pattern for net-new experience→agents imports (see `experience/qa_panel.py` precedent already in the file). Justified inline with an "AD-700a:" comment block.
- Wrote 9 tests instead of the 8 the prompt requested; the 9th is a small assertion that `/diagnostic` is registered in `ProbOSShell.COMMANDS` with the AD-700a marker. Marginal cost, useful regression guard.
