# AD-469 Build Report

**Date:** 2026-05-02
**Builder:** Wave 8 continuous-build (5 of 6)

## Sections Implemented

| Section | File | Status |
|---|---|---|
| Section 0+5: EventTypes | `src/probos/events.py` | ✅ Added `EPS_BUDGET_EXCEEDED`, `EPS_REALLOCATION` after AD-656 anchor |
| Section 1: Package init | `src/probos/cognitive/eps/__init__.py` (new) | ✅ Owns directory creation |
| Section 2: CapacityTracker | `src/probos/cognitive/eps/capacity.py` (new) | ✅ Real-API integration with `journal.get_token_usage_by(group_by=...)` |
| Section 3: DepartmentBudget + DepartmentBudgetTable | `src/probos/cognitive/eps/budgets.py` (new) | ✅ Proportional renormalization on override |
| Section 4: EPSCoordinator | `src/probos/cognitive/eps/coordinator.py` (new) | ✅ Composes tracker + budgets; `check_budgets` v1=[] (honest deferral per convention #7) |
| Section 6: EPSConfig | `src/probos/config.py` | ✅ Added `EPSConfig` + `EPSDepartmentConfig` after `DepartmentProfilesConfig`; `eps: EPSConfig` field on `SystemConfig` |
| Section 7: finalize.py wiring | `src/probos/startup/finalize.py` | ✅ Wires `runtime.eps_coordinator` after AD-572b CaptainEngagementProvider; always-wired with `else: None` |
| Tests | `tests/test_ad469_eps.py` (new) | ✅ 13/13 pass at `-n 0` |
| Tracking | `PROGRESS.md`, `docs/development/roadmap.md:4185` | ✅ Updated |

## Test Results

- Focused gate: `pytest tests/test_ad469_eps.py -v -n 0` → **13/13 passed in 0.26s**
- Full parallel gate: **10,537 passed (+13 vs Combo A baseline 10,524), 15 skipped**

## Notes / Decisions

- Phantom-API correction propagated correctly: implementation uses `get_token_usage_by(group_by=...)` (real method at `journal.py:299`); test mocks the real shape (`row["total_tokens"]`, `row["total_calls"]`, group-key matching `group_by` argument).
- Section 5 anchor terminated on `MODEL_FALLBACK = "model_fallback"  # AD-463` per fallback chain (AD-655 had laid down `DEPT_PROFILE_APPLIED` first; my events block landed after that).
- Section 7 wiring landed AFTER the AD-572b CaptainEngagementProvider block (introduced in Combo A). Pre-flight grep confirmed the Wave-8-stable position.
- Wholesale-deferred (convention #14): alert-aware reallocation → AD-469b, back-pressure → AD-469c, atomic enforcement → AD-469d, prompt caching → AD-469e.
- `check_budgets()` v1 contract: returns `[]` without emit. The agent->department resolver lands in AD-469b. Honest deferral per convention #7 — the empty-list contract is documented, the method is real, but it does no theater.

## Pre-Commit Sanity Check

10 files changed, ~510 insertions, 1 deletion (roadmap status flip). Max per-file deletion: 1 line. Well under 200-line threshold.
