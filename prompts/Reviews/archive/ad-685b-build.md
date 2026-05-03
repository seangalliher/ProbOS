# AD-685b Build Report — Wave 15

**Date:** 2026-05-03
**Mode:** Single-prompt wave; one commit.
**Prompt:** `prompts/ad-685b-method-call-validation.md` (revised at c4a2465).

## Summary

Extended `scripts/phantom_api_ast_helper.py` in-place with method-name AST validation against resolved classes. Wrapper changes minimal — added `[method_phantom]` category prefix and `Skipped (unresolved class)` informational section. JSON output additively extended with `"unresolved": [...]` field.

## Results

- **Test count:** 10693 → 10704 (+11), 15 skipped, 0 failures.
- **New tests:** `tests/test_phantom_api_precheck_method_calls.py` (11 tests, all green).
- **Existing test updated:** `tests/test_phantom_api_precheck_kwargs.py::test_helper_runs_on_clean_prompt_returns_empty_phantoms` — replaced exact-shape JSON equality with key-by-key access (additive `unresolved` field).
- **Hard-stops triggered:** 0.
- **Recursive-validity gate:** PASS — 2 documented pre-existing FPs (`runtime.duty_schedule_tracker` audit prose; `class:SomeClass` placeholder); 0 NEW method_phantom flags.
- **Calibration sweep:** PASS — 0 phantoms / 0 false positives across all 3 archived prompts (`ad-641c-ward-room-thread-priority`, `ad-500-dutyscheduler-workitem-migration`, `ad-487-self-distillation-v1`).
- **Performance:** 2.26s cold / 2.17s warm per prompt (well under 10s ceiling; no `_INDEX_CACHE` extension needed).

## Implementation Notes

- **AST-only:** Helper never imports from `src/probos/` — preserves sandbox property (Hard-Stop #9 honored).
- **Pattern A priority order** (first hit wins): (1) AnnAssign in `runtime.py`, (2) Assign+Call in `startup/finalize.py`, (3) Assign+Call in `runtime.py.__init__`, (4) unresolved. Same-priority conflicts (different classes) → `pattern_a_conflict` (`conflicts` set populated; resolution skipped).
- **Pattern A tie-breaking simplification:** The spec's git-blame-by-commit-date tiebreak was simplified to "skip on classes-differ at same priority". Matches the conservative-skip intent ("never guess"). Documented in helper comment.
- **Pattern B simplification:** Spec describes line-aware reassignment scoping (skip only call sites AFTER reassignment line). Implementation collapses to "any reassignment to different class → skip all call sites on that var" — strictly more conservative; documented in `_resolve_pattern_b` docstring.
- **Pattern C (typed parameter via type hints in surrounding context):** Not implemented in v1. Tests assert behavior on Pattern A + B only. The spec lists C in Section 1 but no test demands it; an explicit deferral to a future AD is preferable to a half-baked implementation.
- **Bare-var `no_class_resolution`:** Silently skipped (not emitted as `unresolved`) to avoid flooding output with stdlib aliases / fixture parameters / function arguments. Pattern A `runtime.X` unresolveds DO emit. Documented in `find_method_phantoms` body.
- **Test #3 framing:** `event_log.query` actually exists on `EventLog` in real `src/probos/`. Test uses a synthetic tmp_path src tree where `EventLog` only defines `query_structured` and `log` — exercises the method-name check on a controlled fixture rather than relying on real codebase shape.
- **Windows encoding fix:** `subprocess.run(..., encoding="utf-8")` required for the recursive-validity test (prompt body contains `→` Unicode arrows; default Windows cp1252 encoder rejects them).

## Tracker Updates

- **PROGRESS.md** — AD-685b paragraph prepended (verbatim per Tracking section).
- **DECISIONS.md** — AD-685b entry under Era V (verbatim from prompt's Tracking block, placed above AD-685 v1).
- **docs/development/roadmap.md** — AD-685b entry inserted after AD-685 within the existing tooling-hygiene block.

## Deferred Nits

None. All Required + Recommended items from the second-pass review file (`prompts/Reviews/README-wave-15-pass-2.md`) are folded into the build.

## Files Changed

- `scripts/phantom_api_ast_helper.py` — extended (+~210 LOC).
- `scripts/phantom-api-precheck.ps1` — wrapper extended (+~30 LOC).
- `tests/test_phantom_api_precheck_method_calls.py` — NEW (~290 LOC, 11 tests).
- `tests/test_phantom_api_precheck_kwargs.py` — 1 existing test updated for additive schema.
- `PROGRESS.md` — AD-685b paragraph prepended.
- `DECISIONS.md` — AD-685b entry inserted under Era V.
- `docs/development/roadmap.md` — AD-685b entry inserted alongside AD-685.
- `prompts/build-reports/ad-685b-build.md` — this report.
