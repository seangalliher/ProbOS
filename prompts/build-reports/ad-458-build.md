# AD-458 Build Report

**Date:** 2026-05-01
**Builder:** Wave 6 continuous-build

## Sections Implemented

| Section | File | Status |
|---|---|---|
| Section 0: EventType | `src/probos/events.py` | ✅ Added `PREFLIGHT_FAILED` |
| Section 1-3: Pre-Flight module | `src/probos/cognitive/pre_flight.py` (new) | ✅ Protocol, dataclasses, 2 checks, Runner |
| Section 4: Builder integration | `src/probos/cognitive/builder.py` | ✅ SEARCH/REPLACE at lines 2515-2517 (after dirty-tree, before branch creation) |
| Section 5: PreFlightConfig | `src/probos/config.py` | ✅ Added Pydantic class + `pre_flight: PreFlightConfig` field after `validation_framework` (AD-457 anchor not yet landed; used AD-451 fallback per anchor chain) |
| Section 6: finalize.py wiring | `src/probos/startup/finalize.py` | ✅ `runtime.pre_flight_runner` (public) after AD-451 ReconciliationEscalator |
| Tests | `tests/test_ad458_pre_flight.py` (new) | ✅ 10/10 pass at `-n 0` |
| Tracking | `PROGRESS.md`, `docs/development/roadmap.md:4150` | ✅ Updated |

## Test Results

- Focused gate: `pytest tests/test_ad458_pre_flight.py -v -n 0` → **10/10 passed in 0.27s**
- Full parallel gate (initial): 4 failures — 1 false-positive Unicode encoding incompatibility in 3 source-reading tests (cp1252 read of `←` arrow character I added per prompt verbatim).
- **Source-fix applied:** Replaced UTF-8 `←` (0x90 in cp1252) with ASCII `<-` in the `parents[3] = repo root` comment in `finalize.py`. Tests under `tests/test_counselor_therapeutic.py` and `tests/test_ad637z_nats_cleanup.py` use `Path(...).read_text()` which defaults to cp1252 on Windows. ASCII conversion preserves prompt intent without semantic change. Per standing rule: minor source fix to maintain test compatibility.
- Full parallel gate (after fix): **10,365 passed (+10 vs AD-451 baseline 10,355), 14 skipped**.

## Notes / Decisions

- Used standard `@runtime_checkable` decorator form (above class definition) instead of the prompt's post-assignment `PreFlightCheck = runtime_checkable(PreFlightCheck)` form. The second-pass review flagged this as Builder-discretion Nit; standard form is cleaner and matches `protocols.py` precedent.
- Section 5 anchor: AD-457 `engineering: EngineeringConfig` hasn't landed yet, used the next fallback `validation_framework: ValidationFrameworkConfig` (AD-451 just landed in commit `4ed9ab2`).
- v1 no-theater discipline honored: only 2 real-work filesystem checks ship. LLMTier and TokenBudget deferred to AD-458b.
- Builder integration uses `BuildResult` create-then-mutate pattern (`result.error = ...; return result`), NOT direct construct (which would TypeError because `spec` is required).

## Pre-Commit Sanity Check

10 files changed, 305 insertions, 4 deletions. Max per-file deletion: 4 lines (the original ASCII rewrite + tracker append). Well under 200-line threshold.

## Acceptance Criteria

- [x] All 10 tests pass under `pytest tests/test_ad458_pre_flight.py -v -n 0`
- [x] Full parallel gate non-decreasing (+10 tests)
- [x] 1 new EventType in `events.py`
- [x] `runtime.pre_flight_runner` published as public attribute
- [x] `execute_approved_build()` invokes runner after dirty-tree, before branch
- [x] v1 ships only `TargetFilesExistCheck` + `TargetFilesWritableCheck`
- [x] `PreFlightCheck` Protocol decorated `@runtime_checkable`
