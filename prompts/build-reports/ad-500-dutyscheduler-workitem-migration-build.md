# AD-500 Build Report

**Prompt:** `prompts/ad-500-dutyscheduler-workitem-migration.md`
**Builder:** GitHub Copilot (Claude Opus 4.7)
**Date:** 2026-05-03
**Status:** ✅ CLOSED (v1 producer-only; consumer migration → AD-500a-1)

## Files Changed

- `src/probos/duty_schedule.py` — added `emit_due_duties_as_work_items` async method + `TYPE_CHECKING` guard for `WorkItemStore`
- `src/probos/config.py` — added `DutyScheduleConfig.use_work_items: bool = False`
- `tests/test_ad500_duty_workitem_producer.py` — **NEW** (9 tests)
- `PROGRESS.md`, `DECISIONS.md`, `docs/development/roadmap.md` — tracker updates

## Sections Implemented

1. ✅ Section 1 — Verify-only: `duty` work type pre-registered at `workforce.py:206` (covered by test)
2. ✅ Section 2 — Added `emit_due_duties_as_work_items(agent_type, work_item_store) -> list[str]` producer method on `DutyScheduleTracker`. Uses real API `await work_item_store.create_work_item(work_type="duty", assigned_to=..., title=..., metadata={...})`. `metadata=` is the verified field name at `workforce.py:583` (NOT phantom `payload=`). TYPE_CHECKING guard added per architect's beyond-review repair to prevent circular import.
3. ✅ Section 3 — Added `DutyScheduleConfig.use_work_items: bool = False` opt-in flag (default False per convention #14)
4. ✅ Section 4 — Verify-only: producer reuses existing `EventType.WORK_ITEM_CREATED` (no new EventType)

## Post-Build Section Audit

All 4 `###` sections in the prompt have corresponding implementation. Sections 1 and 4 are verify-only and confirmed by tests.

## Acceptance Criteria

- ✅ `DutyScheduleTracker.emit_due_duties_as_work_items(agent_type, work_item_store)` exists; produces WorkItems via `WorkItemStore.create_work_item(work_type="duty", ...)`.
- ✅ `DutyScheduleConfig.use_work_items: bool = False` (opt-in default).
- ✅ `src/probos/proactive.py` UNTOUCHED (`git diff --stat src/probos/proactive.py` returned empty).
- ✅ `DutyScheduleTracker.__init__` signature unchanged.
- ✅ No new EventType added.
- ✅ 9 focused tests pass (target was 6; added 3 boundary tests: `use_work_items=True` round-trip, no-record_execution invariant, description-fallback).
- ✅ Existing duty/proactive/notification/runtime tests green (only environmental flake on `test_trust_dampening` under -n 8; passes serially per standing rule).

## Test Results

```
$ pytest tests/test_ad500_duty_workitem_producer.py -v -n 0
============================== 9 passed in 0.25s ==============================

$ pytest tests/ -q -n 8 --dist=loadfile
1 failed, 10634 passed, 15 skipped

$ pytest tests/test_trust_dampening.py::TestDampeningIntegration::test_full_cascade_scenario -v -n 0
============================== 1 passed in 0.24s ==============================  # environmental flake; accepted
```

## Pre-Commit Sanity Check

`git diff --cached --stat` showed no deletions >200 lines. Only additions (config.py +1, duty_schedule.py +30, test_ad500 new file).

## Hard-Stops Triggered

None. Specifically did NOT touch `proactive.py` (deferred temptation check passed).
