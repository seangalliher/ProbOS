# AD-501 Build Report

**Prompt:** `prompts/ad-501-tasktracker-deprecation.md`
**Builder:** GitHub Copilot (Claude Opus 4.7)
**Date:** 2026-05-03
**Status:** ✅ CLOSED

## Files Changed

- `src/probos/notifications.py` — **NEW** (NotificationQueue + AgentNotification, move-only)
- `src/probos/task_tracker.py` — **DELETED** (orphaned)
- `src/probos/runtime.py` — removed import, dataclass field, init, snapshot key, restore line
- `src/probos/startup/structural_services.py` — removed TaskTracker construction + struct field
- `src/probos/startup/results.py` — removed TaskTracker import + dataclass field
- `src/probos/startup/shutdown.py` — removed task_tracker stop block
- `tests/conftest.py` — import updated (`probos.task_tracker` → `probos.notifications`)
- `tests/test_notifications.py` — import updated + 8 new TestAD501Migration tests
- `tests/test_task_tracker.py` — **DELETED** (30 orphan-class tests)
- `PROGRESS.md`, `DECISIONS.md`, `docs/development/roadmap.md` — tracker updates

## Sections Implemented

1. ✅ Section 1 — Created `src/probos/notifications.py` (NotificationQueue + AgentNotification)
2. ✅ Section 2 — Updated all imports (`runtime.py:69`, `conftest.py:158`, `test_notifications.py:7`, plus 3 startup files identified beyond prompt footer)
3. ✅ Section 3 — Removed TaskTracker from runtime.py (lines 69, 234, 543, 1058, 1526)
4. ✅ Section 4 — Deleted `src/probos/task_tracker.py`
5. ✅ Section 5 — Test triage: deleted `test_task_tracker.py` (30 tests), added 8 migration-invariance tests
6. ✅ Section 6 — Verified routers/ untouched (`get_task_tracker` FastAPI dep is unrelated naming overlap)

## Post-Build Section Audit

Every `###` section in the prompt has corresponding implementation. Section 6 is verify-only and was confirmed by leaving routers/ untouched.

## Beyond-Prompt Repairs

The verify-first footer missed 3 startup-wiring touchpoints that became dead references after the field removal:
- `src/probos/startup/structural_services.py:122-124,183` (TaskTracker import + construction + struct field)
- `src/probos/startup/results.py:52,142` (TaskTracker import + `StructuralServicesResult.task_tracker` field)
- `src/probos/startup/shutdown.py:207-208` (task_tracker stop block)

All three are logically required by Section 3 (remove field) + Section 4 (no remaining importers). Treated as routine spec extension within stated scope per Wave 9 verify-first culture.

## Test Results

```
$ pytest tests/test_notifications.py -v -n 0
============================= 20 passed in 0.43s ==============================

$ pytest tests/ -q -n 8 --dist=loadfile
10626 passed, 15 skipped, 155 warnings in 413.60s
```

**Baseline:** 10648 passed, 15 skipped
**After AD-501:** 10626 passed, 15 skipped
**Delta:** −22 (= +8 new TestAD501Migration tests − 30 deleted orphan tests). Exactly matches spec.

## Pre-Commit Sanity Check

`git diff --cached --stat` showed `task_tracker.py` deletion of ~283 lines + `test_task_tracker.py` deletion of ~530 lines. Both file deletes are intentional and approved by Section 4 + Section 5 of the prompt. No other file shows >200 deletions.

## Hard-Stops Triggered

None.
