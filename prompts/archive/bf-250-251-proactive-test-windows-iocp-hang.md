# BF-250 + BF-251: Proactive Loop Test Hangs on Windows ProactorEventLoop

**Status:** Ready for builder
**Bug numbers closed:** BF-250, BF-251
**Dependencies:** None — AD-682 fixture isolation already landed; this is the residual hang that AD-682 did NOT fix
**Estimated tests:** Existing tests unquarantined; no new tests
**Risk:** Low — mock-only refactor of one helper function; no production source changes

---

## Problem

Two tests in `tests/test_proactive.py` hang indefinitely under pytest-timeout on Windows:

- `TestPerAgentCooldown::test_per_agent_cooldown_used_in_cycle` (BF-250)
- `TestProactiveExceptionConfidence::test_exception_does_not_crash_loop` (BF-251)

Both have been quarantined since the AD-680/BF-246 sweep. AD-682 fixture isolation did NOT resolve them — the hang reproduces post-AD-682.

### Symptom (reproduced 2026-04-30 with skip markers temporarily removed)

```
+++++++++++++++++++++++++++++++++++ Timeout +++++++++++++++++++++++++++++++++++
asyncio/windows_events.py:445: select
asyncio/windows_events.py:774: _poll
status = _overlapped.GetQueuedCompletionStatus(self._iocp, ms)
```

The asyncio event loop blocks on Windows IOCP polling. pytest-timeout fires (thread method) but cannot interrupt the IOCP wait cleanly, leaving the test hung until the OS kills the process.

### Diagnosis

The proactive loop's `_run_cycle` calls multiple async methods on the runtime mock:

- `rt.ward_room.get_unread_dms(...)` — used by `_check_unread_dms` (line 596 in proactive.py)
- `rt.episodic_memory.recall_for_agent(...)`, `count_for_agent(...)`, `recall_weighted(...)` — used by `_gather_context`
- `rt.event_log.query(...)`
- `rt.ward_room_router.process_endorsements(...)`

`tests/test_proactive.py:_make_mock_runtime` sets up SOME of these as `AsyncMock` (`recall_for_agent`, `count_for_agent`, `recall_weighted`, `event_log.query`, `process_endorsements`, `list_channels`, `create_thread`) but **NOT** `get_unread_dms`. When `_run_cycle` calls `rt.ward_room.get_unread_dms(...)`, the spec'd `WardRoomService` MagicMock returns a regular MagicMock (not an AsyncMock — `MagicMock(spec=...)` does not auto-wrap async methods, only `create_autospec` does).

`await MagicMock()` does not raise immediately on Windows — instead the coroutine state machine yields control to the event loop, which schedules an IOCP wait that never resolves because no real I/O is pending. The test hangs.

The other quarantined tests in the same module (`TestProactiveLLMHealth`, `TestProactiveTrustOutcomes`, etc.) work because they don't hit `_check_unread_dms`'s code path — they exit early via cooldown checks before that line.

### Why BF-250 hits this

```python
# test_per_agent_cooldown_used_in_cycle:
loop._started_at = time.monotonic() - 1200  # past cold-start window
loop._last_proactive["fast"] = time.monotonic() - 100
loop.set_agent_cooldown("fast", 60.0)
await loop._run_cycle()
```

The fast agent's 100s elapsed > 60s cooldown, so `_run_cycle` proceeds past the cooldown check and into `_think_for_agent`. The slow agent's 100s elapsed < 300s cooldown, so it's skipped. But BOTH agents pass through `_check_unread_dms` BEFORE the cooldown check (line 502 in proactive.py is `await self._check_unread_dms(agent, rt)` — first thing in the loop body). So the very first `await rt.ward_room.get_unread_dms(...)` hangs.

### Why BF-251 hits this

Same root cause. `test_exception_does_not_crash_loop` iterates two agents through `_run_cycle`; both hit `_check_unread_dms` before the BF-023 try/except around `_think_for_agent`. The hang occurs before the RuntimeError side_effect is even reached.

## What This Does NOT Change

- No changes to `src/probos/proactive.py` — the production code is correct.
- No changes to `tests/test_proactive.py` test bodies — the test logic is correct.
- No changes to other test helpers (`conftest.py`, AD-682 fixtures).
- No new pytest plugins, no event-loop policy switches, no `-p no:asyncio`.
- Does NOT attempt to fix the underlying Windows ProactorEventLoop + AsyncMock interaction at the asyncio level — that is upstream Python and pytest-asyncio territory. We work around it by ensuring no MagicMock ever appears in an awaited position.

## Verified Against Codebase (2026-04-30)

```
grep -n "_make_mock_runtime\|_make_mock_agent\|get_unread_dms" tests/test_proactive.py
  81: def _make_mock_agent(...)
  95: def _make_mock_runtime(...)
  (no get_unread_dms)

grep -n "rt.ward_room\.\|rt\.episodic_memory\.\|rt\.event_log\.\|rt\.ward_room_router\." src/probos/proactive.py
  ward_room.get_unread_dms (line 596)
  ward_room.list_channels
  ward_room.create_thread
  ward_room.post_to_channel
  episodic_memory.recall_for_agent
  episodic_memory.count_for_agent
  episodic_memory.recall_weighted
  event_log.query
  ward_room_router.process_endorsements
  ward_room_router.extract_endorsements (sync)
  bridge_alerts.get_recent_alerts (sync)

grep -n "@pytest.mark.skip.*BF-25" tests/test_proactive.py
  501: BF-250 skip marker
  1030: BF-251 skip marker
```

## Implementation

### Section 1: Harden `_make_mock_runtime` to cover all async runtime methods

**File:** `tests/test_proactive.py`

Find `_make_mock_runtime` (around line 95) and add the missing async stubs. Specifically the WardRoomService block needs `get_unread_dms`, `post_to_channel`, and `archive_thread` as AsyncMock. The current block:

```python
    if ward_room:
        rt.ward_room = MagicMock(spec=WardRoomService)
        rt.ward_room.list_channels = AsyncMock(return_value=[
            MagicMock(id="ch1", channel_type="department", department="science", name="Science"),
            MagicMock(id="ch2", channel_type="ship", department="", name="All Hands"),
        ])
        rt.ward_room.create_thread = AsyncMock()
    else:
        rt.ward_room = None
```

Replace with:

```python
    if ward_room:
        rt.ward_room = MagicMock(spec=WardRoomService)
        rt.ward_room.list_channels = AsyncMock(return_value=[
            MagicMock(id="ch1", channel_type="department", department="science", name="Science"),
            MagicMock(id="ch2", channel_type="ship", department="", name="All Hands"),
        ])
        rt.ward_room.create_thread = AsyncMock()
        # BF-250/251: prevent Windows IOCP hang when _run_cycle awaits these
        # methods. MagicMock(spec=...) does NOT auto-wrap async methods as
        # AsyncMock; the unwrapped MagicMock yields to the event loop on await
        # and never resolves on Windows ProactorEventLoop. Defaulting to empty
        # collections keeps the test surface minimal — individual tests can
        # override return_value as needed.
        rt.ward_room.get_unread_dms = AsyncMock(return_value=[])
        rt.ward_room.post_to_channel = AsyncMock()
        rt.ward_room.archive_thread = AsyncMock()
        rt.ward_room.get_or_create_dm_channel = AsyncMock()
        rt.ward_room.create_post = AsyncMock()
    else:
        rt.ward_room = None
```

### Section 2: Add a Windows-defensive sanity check fixture (optional belt-and-suspenders)

**File:** `tests/test_proactive.py`

After the `_make_mock_runtime` definition, add a small sanity helper used by the tests that exercise `_run_cycle`:

```python
def _assert_no_unawaitable_async_paths(rt) -> None:
    """BF-250/251: Sanity check that all async runtime entry points are AsyncMock.

    On Windows ProactorEventLoop, awaiting a regular MagicMock blocks IOCP
    polling indefinitely. This helper enforces the invariant for tests that
    drive _run_cycle through ward_room and episodic_memory paths.
    """
    from unittest.mock import AsyncMock
    if rt.ward_room is None:
        return
    for name in (
        "get_unread_dms", "list_channels", "create_thread",
        "post_to_channel", "archive_thread",
    ):
        attr = getattr(rt.ward_room, name, None)
        assert isinstance(attr, AsyncMock), (
            f"BF-250/251: rt.ward_room.{name} must be AsyncMock to avoid "
            f"Windows IOCP hang; got {type(attr).__name__}"
        )
```

Builder note: this helper is OPTIONAL — only add it if Section 1 alone doesn't make the tests green. If the unquarantined tests pass after Section 1, skip Section 2.

### Section 3: Unquarantine the two tests

**File:** `tests/test_proactive.py`

Remove the `@pytest.mark.skip` decorators on:

- `test_per_agent_cooldown_used_in_cycle` (around line 501-502 — remove just the `@pytest.mark.skip(reason="BF-250: ...")` line; keep `@pytest.mark.asyncio`)
- `test_exception_does_not_crash_loop` (around line 1030-1031 — same pattern; remove BF-251 skip)

### Section 4: Update trackers

**File:** `PROGRESS.md`

Find the existing `BF-250 OPEN` and `BF-251 OPEN` entries and replace with CLOSED entries:

```markdown
BF-250 CLOSED. Resolved by `_make_mock_runtime` AsyncMock hardening for ward_room methods. Root cause: `MagicMock(spec=WardRoomService)` does not auto-wrap async methods as AsyncMock; `rt.ward_room.get_unread_dms()` was awaited as a regular MagicMock, which on Windows ProactorEventLoop yields to the event loop and blocks indefinitely on `_overlapped.GetQueuedCompletionStatus`. Test now passes under `-n 16 --dist=loadfile` and `-n 0`.

BF-251 CLOSED. Same root cause as BF-250 — `_run_cycle` calls `_check_unread_dms` BEFORE the BF-023 try/except around `_think_for_agent`, so the unawaitable MagicMock hung before the RuntimeError side_effect was reached. Resolved by the same mock hardening.
```

**File:** `docs/development/roadmap.md`

Find the BF-250 and BF-251 rows in the Bug Tracker table and update Status from **Open** to **Closed** with a one-line root cause:

```markdown
| BF-250 | `TestPerAgentCooldown::test_per_agent_cooldown_used_in_cycle` hung under pytest-timeout on Windows. **Root cause:** `MagicMock(spec=WardRoomService)` does not auto-wrap async methods as AsyncMock; `await rt.ward_room.get_unread_dms()` blocked on Windows IOCP. **Fix:** `_make_mock_runtime` now sets `get_unread_dms` and related ward_room methods as AsyncMock. | Medium | **Closed** |
| BF-251 | `TestProactiveExceptionConfidence::test_exception_does_not_crash_loop` hung under pytest-timeout on Windows. Same root cause as BF-250 (hang occurred in `_check_unread_dms` before the BF-023 exception path). **Fix:** Same as BF-250. | Medium | **Closed** |
```

### Section 5: Verify

```pwsh
# Focused — both unquarantined tests must pass
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_proactive.py::TestPerAgentCooldown::test_per_agent_cooldown_used_in_cycle tests/test_proactive.py::TestProactiveExceptionConfidence::test_exception_does_not_crash_loop -v -n 0 --timeout=10

# Whole proactive test file (regression check on the rest of TestPerAgentCooldown and TestProactiveExceptionConfidence)
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_proactive.py -v -n 0

# Full parallel gate
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile
```

Expected:
- Focused: 2 passed in <5s.
- Whole file: all tests pass (no regressions).
- Full gate: 10254 passed (or +0/+1 vs prior baseline; we're unquarantining 2 tests, so skipped count drops from 16 to 14).

## Pre-Commit Sanity Check (per BUILDER-EXECUTION-PLAN)

Before `git commit`, run `git diff --cached --stat`. Expected delta:

- `tests/test_proactive.py`: ~10-15 insertions (mock hardening + skip marker removals), ~2-4 deletions.
- `PROGRESS.md`: 2 lines changed (BF-250 and BF-251 entries).
- `docs/development/roadmap.md`: 2 rows updated.

If any file shows >200 deletions, STOP and investigate. The tracker files are append-mostly; large deletions are wrong.

## Tracking

- `PROGRESS.md`: BF-250 and BF-251 marked CLOSED.
- `docs/development/roadmap.md`: same updates in Bug Tracker table.
- `DECISIONS.md`: no entry needed (this is a test-helper bug fix, not an architectural decision).

## Acceptance Criteria

- Both quarantined tests now pass at `-n 0` and under `-n 16 --dist=loadfile`.
- The rest of `tests/test_proactive.py` still passes (no regressions in the helper change).
- BF-250 and BF-251 closed in trackers.
- Pre-commit `git diff --cached --stat` audit performed.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Engineering Principles Applied

- **Fail Fast (modified for tests):** the helper now ensures every awaitable runtime mock IS awaitable. The previous behavior silently hung; the new behavior either succeeds or surfaces a clear assertion if Section 2's optional sanity helper is added.
- **DRY:** all proactive tests use one helper (`_make_mock_runtime`); fixing it once benefits every future test.
- **Defense in Depth:** Section 2's optional sanity helper enforces the AsyncMock invariant at test boundary so future regressions surface immediately rather than via a 30-second hang.
- **Test isolation:** AD-682 fixture isolation handles cross-test state; this BF handles within-test mock correctness. Complementary fixes.

## Future Work (out of scope)

- A repository-wide audit of `MagicMock(spec=...)` usage where the spec'd class has async methods. There may be other latent hangs of this shape elsewhere. File as AD-683 if AD-682 follow-up shows they're real.
- Switching pytest-timeout from `method=thread` to a Windows-compatible approach for asyncio tests. Currently no good solution; `method=signal` doesn't work on Windows. Document as a known limitation.
- Migrating `MagicMock(spec=...)` to `create_autospec(spec=..., instance=True)` codebase-wide — autospec auto-wraps async methods as AsyncMock since Python 3.8. Larger refactor; track separately.
