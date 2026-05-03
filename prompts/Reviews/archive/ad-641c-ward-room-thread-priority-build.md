# AD-641c Build Report

**Date:** 2026-05-02
**Wave:** 9B (slot 2 of 2)
**Baseline (post-641e):** 10617 passed, 15 skipped (10603 + 14 from AD-641e)

## Summary

Shipped `ThreadPriorityScorer` (pure value-class) + `ThreadPriorityService` (runtime adapter) under new `src/probos/cognitive/thread_priority/` package. 5-factor scoring (captain / unresolved / cross-department / recency / endorsement). Wave 9A pattern compliance verified at every call site (query_structured/event=, async _count_endorsements, entry["data"], recursive _extract_posts, resolve_author_department helper).

## Files

- **New:** 3 files in `src/probos/cognitive/thread_priority/` (`__init__.py`, `scorer.py`, `service.py`)
- **New:** `tests/test_ad641c_thread_priority.py` (16 tests)
- **Modified:** `src/probos/events.py` (+1 EventType), `src/probos/config.py` (+1 Pydantic model + SystemConfig field), `src/probos/startup/finalize.py` (wiring block after AD-641e), `PROGRESS.md`, `docs/development/roadmap.md`

## Tests

- Focused: 16/16 pass at `-n 0`
- Regression: `tests/test_ward_room.py` + `tests/test_ward_room_dms.py` — 113/113 pass + 1 pre-existing time-based flake in `test_browse_threads_sort_recent` that passes in isolation. Not related to this AD; tagged as environmental in PROGRESS.md entry per standing rule.

## Hard-stops triggered

None. The Wave 9A pattern verifications all matched live source:
- `query_structured(event=...)` is the live signature (verified `event_log.py:170`)
- `_count_endorsements` is `async def` and awaited (cascade through `_build_input`)
- `entry["data"]` matches `_row_to_dict` shape (verified `event_log.py:249`)
- `_extract_posts` recursive walker matches `get_thread` tree shape (verified `threads.py:716-748`)
- `resolve_author_department` exists at `_helpers.py:11` (verified)

## Deferred nits

None.

## Convention compliance

- Convention #7 (no theater): All 5 advertised factors fire against live data.
- Convention #11 (real adopters in tests): Service tests use `AsyncMock` ward_room/event_log returning post-R3 row shape; `_extract_posts` regression uses real tree fixture.
- Convention #14 (aggressive pre-deferral): 3 grandchildren tagged (`AD-641c-i`/`-ii`/`-iii`).
- Convention #18 (private-attr discipline): `_extract_posts` is exercised via direct call in regression test (single test only); no other private-attr reach.
- Open/Closed: `AttentionManager` + `ThreadManager` unchanged.

## Listener defer confirmation

AD-641b's `WardRoomEndorsementListener` was NOT built (per Wave 9A defer to AD-641b-iv). v1 reads endorsements via `event_log.query_structured` poll, not via subscription.
