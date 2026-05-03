# AD-685 Build Report — Wave 11

**Date:** 2026-05-03
**Mode:** Single commit (Wave 11; tooling hygiene)
**Risk:** low
**Builder verdict:** ✅ Shipped clean

## Summary

Extended `scripts/phantom-api-precheck.ps1` with a Python AST helper that validates method-kwarg shapes in prompt bodies against live signatures from `src/probos/`. Added a shared heuristic pre-filter applied uniformly to BOTH the existing symbol-existence check AND the new kwarg check (resolves Wave 11 pass-1 Required #1 recursive-validity gap).

## Sections

### Section 1 — `scripts/phantom_api_ast_helper.py` ✅
- Python AST helper (`scripts/phantom_api_ast_helper.py`).
- Module-level `_INDEX_CACHE` dict (per Recommended #1 promotion).
- Cold AST index build: ~1.0 s indexing 2810 method names across 403 Python files.
- Warm cached call: ~0.25 ms.
- Receives pre-filtered body on stdin; emits JSON to stdout (UTF-8 — Nit #4).
- Helper-internal heuristics: skip noisy method names (`format`/`info`/`execute`/etc.) and noisy receivers (`self`/`asyncio`/`logger`/etc.); accept kwarg if any same-named definition matches OR any candidate accepts `**kwargs`.

### Section 2 — Wrapper integration with shared pre-filter ✅
- Added `Get-FilteredPromptBody` function in `scripts/phantom-api-precheck.ps1`.
- Pre-filter steps (mask via whitespace-of-equal-length to preserve line numbers):
  1. Non-Python fenced code blocks (pwsh/bash/sh/text/json/bare). Only ` ```python ` / ` ```py ` blocks scanned.
  2. `## Revision` audit-trail sections through next `## ` heading or EOF.
  3. Markdown table-row backticked call-shapes (`Class.method`, `Class(args)`, `obj.method(args)`).
  4. Inline-prose backticked call-shapes (broadens #3 to bullet lists and paragraphs — recursive-validity tuning per Hard-Stop).
- Existing symbol-check logic preserved verbatim (regex patterns, tunings); only INPUT changed from `$body` to `$filteredBody`.
- AST helper invoked AFTER symbol check on the same `$filteredBody`; results merged into `$phantomsHere` with `Category = 'kwarg_mismatch'`.
- Display now shows category prefix: `[<Class>.<method>]`, `[runtime.X]`, `[<Class>(...)]`, `[kwarg_mismatch]`.

### Section 3 — Calibration sweep ✅

**Corpus (named in prompt + 3 others):**
- `prompts/archive/ad-641c-ward-room-thread-priority.md`
- `prompts/archive/ad-500-dutyscheduler-workitem-migration.md`
- `prompts/archive/ad-501-tasktracker-deprecation.md`
- `prompts/archive/ad-641d-crew-deliberation-protocol.md`
- `prompts/archive/ad-469-eps-compute-token-distribution.md`

**Result:** 0 phantoms, 0 false positives across all 5.

**Note on named ad-641c/ad-500 corpus:** the archived prompt bodies tag their own phantom fixes with "Applied" / "replaced everywhere" markers (e.g., ad-641c L617: "phantom kwarg `event_type=` on `EventLog.query` — Applied"; ad-500 L260: "Phantom `runtime.work_item_store.add(work_item)` — replaced everywhere"). They represent the post-repair state, not the pre-repair state. The catch behavior is verified instead by the synthetic test cases #2 and #3 in `tests/test_phantom_api_precheck_kwargs.py`, which feed the original phantom shapes through the helper directly and confirm flagging.

**Performance:**
- Cold AST index build (single Python process): ~1.0 s indexing 2810 method names across 403 Python files.
- Warm cached call (within same process): ~0.25 ms.
- 5-prompt sweep wall time: ~6.0–6.2 s total → ~1.2 s/prompt avg. Each prompt invocation is its own Python process under the current wrapper-spawns-helper-once-per-prompt design, so each pays the cold-build cost. Well under the 5s target on a per-process basis; well under the 30s cold-build Hard-Stop.

## Recursive-Validity Gate ✅

```
$ ./scripts/phantom-api-precheck.ps1 prompts/ad-685-phantom-precheck-kwarg-validation.md
=== prompts/ad-685-phantom-precheck-kwarg-validation.md ===
  Clean — no phantom symbols detected.
=== Summary ===
Prompts scanned: 1
Total phantom candidates: 0
```

Before: 1 phantom (`WorkItemStore.get_pending` self-reference + 2 kwarg cites in prose tables).
After: 0 phantoms. Pre-filter suppression worked end-to-end.

No allowlist short-circuit. No AD-685-filename special-casing.

## Test Results

```
tests/test_phantom_api_precheck_kwargs.py::test_helper_runs_on_clean_prompt_returns_empty_phantoms PASSED
tests/test_phantom_api_precheck_kwargs.py::test_helper_catches_event_log_query_event_type_kwarg_mismatch PASSED
tests/test_phantom_api_precheck_kwargs.py::test_helper_catches_work_item_store_get_pending PASSED
tests/test_phantom_api_precheck_kwargs.py::test_helper_skips_kwargs_in_non_python_fenced_blocks PASSED
tests/test_phantom_api_precheck_kwargs.py::test_helper_skips_kwargs_in_revision_section PASSED
tests/test_phantom_api_precheck_kwargs.py::test_helper_accepts_kwarg_matching_any_definition PASSED
tests/test_phantom_api_precheck_kwargs.py::test_powershell_wrapper_merges_kwarg_mismatches_with_symbol_phantoms PASSED
tests/test_phantom_api_precheck_kwargs.py::test_powershell_wrapper_exit_code_1_when_kwarg_phantom PASSED
tests/test_phantom_api_precheck_kwargs.py::test_powershell_wrapper_shared_prefilter_suppresses_prose_table_phantom PASSED
============================= 9 passed in 19.04s ==============================
```

**Full gate:** 10643 passed + 1 environmental flake (`test_browse_threads_sort_recent` passes serially — pre-existing flake, unrelated to this AD; documented in PROGRESS.md AD-641c entry as "1 pre-existing time-based flake in `test_browse_threads_sort_recent` that passes in isolation"), 15 skipped. **Delta: +9** vs Wave 10 baseline of 10635 — exact target hit.

## Hard-Stops

| # | Hard-Stop | Triggered? |
|---|---|---|
| 1 | AST parse takes >30s on cold first build | No (~1s) |
| 2 | Heuristics produce >5 false positives per archived prompt | No (0 across 5 prompts) |
| 3 | Helper conflicts with existing pre-check semantics | No (additive; exit codes preserved) |
| 4 | Recursive-validity gate fails after pre-filter tuning | No (passes after step-4 broadening) |
| 5 | Shared pre-filter regresses existing symbol check | No (only suppresses; no new symbol-check phantoms surfaced) |

## Pre-Commit Deletion Sanity Check

```
git diff --cached --stat
```

Auditing prior to commit. PROGRESS.md / DECISIONS.md / roadmap.md changes are all additive (entries prepended/inserted; no large deletions).

## Convention Compliance

- **Convention #14 (aggressive pre-deferral):** v1 ships 2 of 4 capabilities (kwarg validation + shared pre-filter). AD-685b/c/d deferred.
- **Convention #16 (phantom-api pre-check mandatory):** This AD strengthens the convention.
- **Convention #19 (verify-first):** AST helper queries live `src/probos/` signatures.
- **Engineering Principles** (`.github/copilot-instructions.md`): All public functions in helper have full type annotations; UTF-8 stdout; module-level cache properly initialized; no fire-and-forget tasks; no wildcard imports; PowerShell wrapper preserves existing exit semantics.

## Deferred to Sub-ADs

- **AD-685b:** Field-name validation for dataclass/Pydantic constructors (`WorkItem(payload=...)` field-shape).
- **AD-685c:** Type-shape validation (kwarg expects `dict` but prompt passes `list`).
- **AD-685d:** Receiver-class resolution. Current v1 limitation: `runtime.work_item_store.add(work_item=...)` passes if any class with an `add` method has a `work_item` param.

## Files Changed

- **Added:** `scripts/phantom_api_ast_helper.py`
- **Added:** `tests/test_phantom_api_precheck_kwargs.py`
- **Added:** `prompts/build-reports/ad-685-build.md` (this report)
- **Modified:** `scripts/phantom-api-precheck.ps1` (added `Get-FilteredPromptBody`; switched 3 regex inputs from `$body` to `$filteredBody`; added kwarg-helper invocation block; categorized phantom display)
- **Modified:** `PROGRESS.md` (prepended AD-685 entry)
- **Modified:** `DECISIONS.md` (added Era V entry verbatim from prompt)
- **Modified:** `docs/development/roadmap.md` (inserted AD-685 entry after AD-680)
