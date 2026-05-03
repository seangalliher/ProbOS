# AD-477 Build Report — Naval Organization v1

**Wave:** 12
**Date:** 2026-05-03
**Mode:** Single commit, AD-477 only.
**Test baseline:** 10644 passed, 15 skipped (post-Wave-11 state).
**Test target:** +14 (10658).
**Test result:** 10658 passed, 15 skipped — **exact target hit, +14**.

## Sections Implemented

| # | Section | Result |
|---|---|---|
| 0 | EventTypes (`CAPTAINS_LOG_GENERATED`, `PLAN_OF_DAY_GENERATED`) — `events.py` | ✓ collision-free, added under "Naval Organization (AD-477)" group |
| 1 | `src/probos/naval/__init__.py` package re-exports | ✓ |
| 2 | `CaptainsLogService` (`src/probos/naval/captains_log.py`) | ✓ 3 source aggregations (episodic + Ward Room + work items) |
| 3 | `PlanOfDayService` (`src/probos/naval/plan_of_day.py`) | ✓ 3 source aggregations (work items + Ward Room queue + alerts) |
| 4 | `NavalOrganizationConfig` + nested configs (`config.py`) | ✓ `Field(default_factory=...)` for nested-BaseModel defaults |
| 5 | Runtime wiring in `startup/finalize.py` | ✓ public attrs (no underscore); `None` when disabled |
| Tests | `tests/test_ad477_naval.py` | ✓ 14 tests |

## Section Audit

Every `###` section header in the prompt maps to implemented code:
- **Section 0** → `events.py:CAPTAINS_LOG_GENERATED`/`PLAN_OF_DAY_GENERATED`.
- **Section 1** → `src/probos/naval/__init__.py`.
- **Section 2** → `CaptainsLogService` with `generate_for_date`/`write_to_disk`/`start`/`stop`.
- **Section 3** → `PlanOfDayService` with `generate_for_date`/`write_to_disk`/`start`/`stop`.
- **Section 4** → `CaptainsLogConfig`/`PlanOfDayConfig`/`NavalOrganizationConfig` and `SystemConfig.naval_organization`.
- **Section 5** → `finalize.py` runtime wiring with all four public attributes.

No omissions.

## Verify-First Pre-Flight Results

| API | Verified location | Status |
|---|---|---|
| `EpisodicMemory.recent(k=10)` | `cognitive/episodic.py:1832` | ✓ matches prompt |
| `WorkItemStore.list_work_items(status=...)` | `workforce.py:1066` | ✓ matches prompt |
| `WorkItemStatus.OPEN = "open"` | `workforce.py:44` | ✓ canonical (NOT `"pending"`) |
| `WardRoomService.list_threads(channel_id, ...)` | `ward_room/service.py:289`, threads.py:232 | ✓ — `channel_id` is required `str`; passing `None` produces empty result-set in production (graceful degradation) |
| `BridgeAlertService.get_recent_alerts(limit)` | `bridge_alerts.py:822` | ✓ |
| `runtime.dreaming_engine` | (not present) | confirmed phantom — dream-consolidation deferred to AD-477g |
| `runtime.duty_schedule_tracker` | (not present) | confirmed phantom — scheduled-duties deferred to AD-477f |
| `EventType.CAPTAINS_LOG_GENERATED`/`PLAN_OF_DAY_GENERATED` | (not present pre-build) | ✓ collision-free |

## Hard-Stops Triggered

**Zero.** All 7 hard-stops in the prompt evaluated:
1. Phantom API — none discovered (the two known absent attrs were already deferred).
2. Architectural change beyond scope — none required.
3. Persistent serial test failure on unchanged file — none.
4. Existing test breaks unanticipated by "What This Does NOT Change" — none (10644 → 10658, all green).
5. >5 sweep-introduced quarantines — none.
6. `runtime.episodic_memory.recent` signature drift — signature matches verified `episodic.py:1832`.
7. `runtime.ward_room` thread query API requires writes — read-only confirmed.

## Confirmations

- **Dream-consolidation NOT built** — confirmed. `CaptainsLogService` aggregates exactly 3 sources (episodic memory, Ward Room, work items). No `runtime.dreaming_engine` / `runtime.dream_scheduler` reads. Per AD-477g defer.
- **Scheduled-duties NOT built** — confirmed. `PlanOfDayService` aggregates exactly 3 sources (work items, Ward Room queue, alerts). No `runtime.duty_schedule_tracker` reads. Per AD-477f defer.
- **v1 ships ONLY 2 capabilities × 3 source aggregations each** — confirmed.

## Test Plan Coverage

All 14 named tests implemented and passing (`pytest tests/test_ad477_naval.py -q -n 0` → `14 passed in 0.27s`):

1. `test_event_type_captains_log_generated_exists`
2. `test_event_type_plan_of_day_generated_exists`
3. `test_naval_organization_config_defaults`
4. `test_captains_log_generate_with_no_episodes_returns_empty_template`
5. `test_captains_log_aggregates_top_episodes_by_importance` (asserts over-fetch `k=8` and importance-sort + date+threshold filter)
6. `test_captains_log_includes_ward_room_summary` (asserts `list_threads(channel_id=None, limit=50, sort="recent")`)
7. `test_captains_log_write_to_disk_emits_event`
8. `test_plan_of_day_aggregates_open_work_items` (asserts `status="open"` canonical)
9. `test_plan_of_day_includes_alert_conditions_when_enabled`
10. `test_plan_of_day_write_to_disk_emits_event`
11. `test_start_creates_named_task` (idempotent re-start; cleans up via `stop()`)
12. `test_stop_surfaces_cancellederror_to_caller_after_cleanup` (`pytest.raises(asyncio.CancelledError)` — non-swallow per Recommended #3)
13. `test_runtime_attribute_set_when_enabled`
14. `test_runtime_attribute_none_when_disabled`

## Conventions Compliance Spot-Check

- **Convention #1 (public attributes):** all 4 runtime attrs are no-underscore (`captains_log_service`, `plan_of_day_service`, `captains_log_start_task`, `plan_of_day_start_task`).
- **Convention #14 (aggressive pre-deferral):** v1 ships 2 of 6 — Qualification/3M/Damage Control/SORM/scheduled-duties/dream-consolidation deferred with explicit forcing functions.
- **Convention #16 (verified-against-codebase audit trail):** all 8 APIs grep-verified before implementation.
- **Recommended #1 (Pydantic factory defaults):** `Field(default_factory=CaptainsLogConfig)` and `Field(default_factory=PlanOfDayConfig)` used in `NavalOrganizationConfig`.
- **Recommended #3 (CancelledError non-swallow):** `_run_loop` re-raises `CancelledError` after cleanup; `stop()` does NOT catch — caller observes via `pytest.raises`.
- **Engineering principles:** Defense-in-depth `try/except` around every collaborator call (log-and-degrade tier per the three-tier model). `getattr(runtime, "X", None)` for optional accessors.

## Full Gate

```
pytest tests/ -q -n 8 --dist=loadfile  →  10658 passed, 15 skipped, 156 warnings in 398.47s (0:06:38)
```

Exit 0. Test count non-decreasing.

## Flakes Observed

None. The `test_browse_threads_sort_recent` flake noted in Wave 11 PROGRESS.md notes did not surface this run.

## Files Touched

- `src/probos/events.py` (+4 lines)
- `src/probos/config.py` (+24 lines: 3 BaseModel classes + 1 SystemConfig field)
- `src/probos/naval/__init__.py` (new, 32 lines)
- `src/probos/naval/captains_log.py` (new, 192 lines)
- `src/probos/naval/plan_of_day.py` (new, 167 lines)
- `src/probos/startup/finalize.py` (+27 lines wiring block)
- `tests/test_ad477_naval.py` (new, 282 lines)
- `PROGRESS.md` (prepended AD-477 entry)
- `DECISIONS.md` (added AD-477 entry under Era V)
- `docs/development/roadmap.md` (flipped AD-477 status to `partial`)
