# BF-074: Code Hygiene — Deduplication, Encoding, Async Modernization

## Problem

Three categories of code hygiene issues flagged in the code review:

### 1. `_format_duration()` duplicated in 3 files (HIGH)

Identical 15-line function copy-pasted in:
- `runtime.py:110` — module-level function
- `proactive.py:58` — static method on `ProactiveEngine`
- `cognitive/cognitive_agent.py:487` — static method on `CognitiveAgent`

All three are called from multiple locations within their respective files.

### 2. `open()` without `encoding` (MEDIUM — Windows breakage)

Three locations use `open(path, "r")` without specifying `encoding="utf-8"`, which fails on non-ASCII content on Windows (defaults to system locale encoding):

| File | Line | Code |
|------|------|------|
| `crew_profile.py` | 328 | `with open(yaml_file, "r") as f:` |
| `crew_profile.py` | 409 | `with open(target, "r") as f:` |
| `config.py` | 464 | `with open(path) as f:` |

### 3. `asyncio.ensure_future()` deprecated (MEDIUM)

9 occurrences of `asyncio.ensure_future()` should use `asyncio.create_task()` (the modern replacement since Python 3.7, recommended since 3.10):

| File | Lines | Context |
|------|-------|---------|
| `cognitive/builder.py` | 635, 656, 667, 710, 737 | Fire-and-forget `on_event()` callbacks during transporter decomposition |
| `cognitive/builder.py` | 1350 | Generic event callback |
| `knowledge/store.py` | 444 | Lambda scheduling `_flush_pending()` |
| `cognitive/dreaming.py` | 388 | Starting `_monitor_loop()` background task |
| `cognitive/task_scheduler.py` | 111 | Starting `_tick_loop()` background task |

### 4. Bonus: `import time as _time` workaround (9 locations)

Nine occurrences of `import time as _time` scattered across 5 files — a workaround for local variables shadowing the `time` module. Not critical, but worth noting for future cleanup — too many files to safely touch in this BF.

### 5. Bonus: `asyncio.get_event_loop()` deprecated (2 locations)

| File | Line | Context |
|------|------|---------|
| `runtime.py` | 1583 | `_aio_dm.get_event_loop().create_task(...)` |
| `knowledge/records_store.py` | 403 | `asyncio.get_event_loop()` in `_git()` helper |

The `records_store.py` one should use `asyncio.get_running_loop()` (the non-deprecated equivalent). The `runtime.py` one uses a discord.py module pattern — leave it unless you can verify the discord adapter uses a running loop.

## Solution

### Part A: Extract `_format_duration()` to shared utility

Move the function to `src/probos/utils/__init__.py` (or a new `src/probos/utils/formatting.py` — check if `__init__.py` already has content and decide). Replace all three copies with imports.

### Part B: Add `encoding="utf-8"` to `open()` calls

### Part C: Replace `asyncio.ensure_future()` with `asyncio.create_task()`

### Part D: Replace `asyncio.get_event_loop()` in `records_store.py`

## Files to Modify

### 1. `src/probos/utils/__init__.py` (or `src/probos/utils/formatting.py`)

Check if `__init__.py` has existing content. If it's empty or minimal, add `format_duration` there. If it has substantial content, create a new `formatting.py` file.

Add the canonical implementation:

```python
def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration string.

    Examples: "45s", "3m 12s", "2h 15m", "3d 5h"
    """
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    elif seconds < 86400:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"
    else:
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        return f"{days}d {hours}h"
```

**Note:** The function is named `format_duration` (no leading underscore) since it's now a public utility.

### 2. `src/probos/runtime.py`

- **Delete** the module-level `_format_duration()` function (lines 110-123)
- **Add import**: `from probos.utils import format_duration` (or from `probos.utils.formatting`)
- **Replace all calls** to `_format_duration(` with `format_duration(` — there are 2 call sites (lines 1252 and 1746)

### 3. `src/probos/proactive.py`

- **Delete** the static method `_format_duration()` (lines 58-71)
- **Add import**: `from probos.utils import format_duration`
- **Replace** `self._format_duration(` with `format_duration(` — 1 call site (line 507)

### 4. `src/probos/cognitive/cognitive_agent.py`

- **Delete** the static method `_format_duration()` (lines 487-500)
- **Add import**: `from probos.utils import format_duration`
- **Replace** `self._format_duration(` with `format_duration(` — 4 call sites (lines 523, 530, 536, 823)

### 5. `src/probos/crew_profile.py`

- **Line 328**: Change `with open(yaml_file, "r") as f:` to `with open(yaml_file, "r", encoding="utf-8") as f:`
- **Line 409**: Change `with open(target, "r") as f:` to `with open(target, "r", encoding="utf-8") as f:`

### 6. `src/probos/config.py`

- **Line 464**: Change `with open(path) as f:` to `with open(path, encoding="utf-8") as f:`

### 7. `src/probos/cognitive/builder.py`

Replace all 6 `asyncio.ensure_future(` calls with `asyncio.create_task(`:
- Lines 635, 656, 667, 710, 737, 1350

The code assigns the return value in zero of these cases — they're all fire-and-forget. `create_task()` has the same API for this pattern.

### 8. `src/probos/knowledge/store.py`

- **Line 444**: Replace `asyncio.ensure_future(self._flush_pending())` with `asyncio.create_task(self._flush_pending())`

### 9. `src/probos/cognitive/dreaming.py`

- **Line 388**: Replace `asyncio.ensure_future(self._monitor_loop())` with `asyncio.create_task(self._monitor_loop())`

### 10. `src/probos/cognitive/task_scheduler.py`

- **Line 111**: Replace `asyncio.ensure_future(self._tick_loop())` with `asyncio.create_task(self._tick_loop())`

### 11. `src/probos/knowledge/records_store.py`

- **Line 403**: Replace `loop = asyncio.get_event_loop()` with `loop = asyncio.get_running_loop()`

### 12. Tests

Add or extend tests in `tests/test_format_duration.py`:

```python
"""Tests for BF-074: Shared format_duration utility."""
```

Test cases:

1. **Sub-minute**: `format_duration(45)` → `"45s"`
2. **Minutes+seconds**: `format_duration(195)` → `"3m 15s"`
3. **Hours+minutes**: `format_duration(7500)` → `"2h 5m"`
4. **Days+hours**: `format_duration(90000)` → `"1d 1h"`
5. **Zero**: `format_duration(0)` → `"0s"`
6. **Negative clamped**: `format_duration(-5)` → `"0s"`
7. **Exact minute boundary**: `format_duration(60)` → `"1m 0s"`
8. **Exact hour boundary**: `format_duration(3600)` → `"1h 0m"`
9. **Import works from utils**: `from probos.utils import format_duration` succeeds

**No separate tests needed for encoding/async changes** — existing tests will validate the behavior is unchanged.

## Implementation Notes

- The `proactive.py` and `cognitive_agent.py` copies are `@staticmethod` — the shared function is module-level, so call sites change from `self._format_duration(x)` to `format_duration(x)`.
- `asyncio.create_task()` requires a running event loop. All 9 call sites are inside `async` methods that are only called from within the event loop, so this is safe.
- `asyncio.create_task()` keeps a strong reference to the task (prevents GC), which is actually *better* behavior than `ensure_future()` for these fire-and-forget patterns.
- The `store.py` lambda at line 444 may need slight restructuring: `lambda: asyncio.create_task(self._flush_pending())`. Verify the lambda is called from within the event loop context.
- **Do NOT touch** the 9 `import time as _time` patterns — they work correctly and fixing them would require renaming local variables across many functions. That's a separate cleanup if ever needed.
- **Do NOT touch** `runtime.py:1583` (`_aio_dm.get_event_loop()`) — this is a discord.py internal pattern running in a separate thread.

## Acceptance Criteria

- [ ] `format_duration()` exists in `probos.utils` (single canonical copy)
- [ ] Zero copies of `_format_duration()` remain in runtime.py, proactive.py, cognitive_agent.py
- [ ] All 3 `open()` calls have `encoding="utf-8"`
- [ ] All 9 `asyncio.ensure_future()` calls replaced with `asyncio.create_task()`
- [ ] `records_store.py` uses `asyncio.get_running_loop()` instead of `get_event_loop()`
- [ ] All new tests pass
- [ ] Existing tests unaffected
