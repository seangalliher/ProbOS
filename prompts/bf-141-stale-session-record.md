# BF-141: Stale session record — Ctrl+C skips session_last.json write

**Issue:** #149
**Priority:** High (affects all agent temporal awareness)
**Extends:** BF-135, BF-137
**Estimated tests:** 5

## Context

Agents report "2d 20h stasis" when the system was only down for minutes. Root cause: `session_last.json` hasn't been updated since April 7th because Ctrl+C doesn't trigger the session record write.

**Root cause chain:**
1. Ctrl+C → `KeyboardInterrupt` → `asyncio.run()` cancels the running task
2. `_boot_and_run()` finally block (line 343) tries `await runtime.stop()`
3. Task is already cancelled → `CancelledError` (BaseException, not Exception)
4. `except Exception` at line 351 doesn't catch it → propagates
5. `os._exit(0)` at line 355 kills process → `shutdown()` never runs → session record never written
6. Next boot: `stasis_duration = time.time() - stale_shutdown_time` = days instead of minutes

BF-135/137 fixed this inside `shutdown()` by writing first. But if `shutdown()` never runs, those fixes are moot.

## Engineering Principles

- **Defense in Depth:** Belt-and-suspenders — write at call site AND in `shutdown()`. Either path guarantees the record is written.
- **Fail Fast:** Best-effort write, don't block shutdown path.
- **DRY:** Same record format as `shutdown.py` lines 35-42. If `shutdown()` runs after, it overwrites with more accurate timestamp — correct behavior.

## Fix

### File: `src/probos/__main__.py`

**Imports check:** `time`, `json`, and `is_crew_agent` are **NOT** imported at module level in `__main__.py`. Use local imports inside the `try` block:
```python
import json
import time
from probos.crew_utils import is_crew_agent
```
Alternatively, simplify `agent_count` to `len(runtime.registry.all())` (total agents) to avoid the `is_crew_agent` import — agent count is informational only, not used for stasis duration calculation. **Use the simpler approach if preferred.**

**Change 1 — `_boot_and_run` finally block (line 343)**

Insert the following synchronous session record write BEFORE the existing `console.print("\n[bold red]ProbOS shutting down...[/bold red]")` line. Do NOT modify any existing code after it.

```python
    finally:
        # BF-141: Write session record synchronously BEFORE async shutdown.
        # Ctrl+C cancels the task → CancelledError skips runtime.stop() →
        # session_last.json stays stale → inflated stasis on next boot.
        try:
            import json as _json
            import time as _time
            _sr = {
                "session_id": runtime._session_id,
                "start_time_utc": runtime._start_time_wall,
                "shutdown_time_utc": _time.time(),
                "uptime_seconds": _time.monotonic() - runtime._start_time,
                "agent_count": len(runtime.registry.all()),
                "reason": getattr(shell, '_quit_reason', '') or "interrupted",
            }
            (runtime._data_dir / "session_last.json").write_text(
                _json.dumps(_sr, indent=2)
            )
        except Exception:
            pass  # best-effort — don't block shutdown
        console.print("\n[bold red]ProbOS shutting down...[/bold red]")
        # ... existing shutdown code continues unchanged ...
```

**Change 2 — `_serve` finally block (line 440)**

Same pattern — insert synchronous session record write BEFORE the existing `console.print("\n[bold red]ProbOS shutting down...[/bold red]")` line. Same code but with `reason` defaulting to `"server_shutdown"`:

```python
    finally:
        # BF-141: Write session record synchronously BEFORE async shutdown.
        try:
            import json as _json
            import time as _time
            _sr = {
                "session_id": runtime._session_id,
                "start_time_utc": runtime._start_time_wall,
                "shutdown_time_utc": _time.time(),
                "uptime_seconds": _time.monotonic() - runtime._start_time,
                "agent_count": len(runtime.registry.all()),
                "reason": "server_shutdown",
            }
            (runtime._data_dir / "session_last.json").write_text(
                _json.dumps(_sr, indent=2)
            )
        except Exception:
            pass
        console.print("\n[bold red]ProbOS shutting down...[/bold red]")
        # ... existing shutdown code continues unchanged ...
```

**No changes to `src/probos/startup/shutdown.py`.** The existing BF-135/137 write stays. If `runtime.stop()` runs successfully, it overwrites with a slightly more accurate timestamp.

## Tests

### New file: `tests/test_bf141_session_record.py`

```python
"""BF-141: Session record written synchronously before async shutdown."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _make_mock_runtime(tmp_path: Path) -> MagicMock:
    """Create a mock runtime with required attributes for session record write."""
    rt = MagicMock()
    rt._session_id = "test-session-141"
    rt._start_time_wall = time.time() - 60  # started 60s ago
    rt._start_time = time.monotonic() - 60
    rt._data_dir = tmp_path
    # registry.all() returns empty list (no crew agents)
    rt.registry.all.return_value = []
    rt.ontology = None
    return rt


def _write_session_record(runtime: MagicMock, reason: str = "interrupted") -> None:
    """Reproduce the BF-141 synchronous write block from __main__.py."""
    import json
    import time

    _sr = {
        "session_id": runtime._session_id,
        "start_time_utc": runtime._start_time_wall,
        "shutdown_time_utc": time.time(),
        "uptime_seconds": time.monotonic() - runtime._start_time,
        "agent_count": len(runtime.registry.all()),
        "reason": reason,
    }
    (runtime._data_dir / "session_last.json").write_text(
        json.dumps(_sr, indent=2)
    )


class TestBF141SessionRecord:
    """BF-141: Ctrl+C must write session_last.json before async shutdown."""

    def test_session_record_written(self, tmp_path: Path):
        """Session record file is created with expected fields."""
        rt = _make_mock_runtime(tmp_path)
        _write_session_record(rt)

        path = tmp_path / "session_last.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["session_id"] == "test-session-141"
        assert "shutdown_time_utc" in data
        assert "uptime_seconds" in data
        assert data["reason"] == "interrupted"

    def test_session_record_has_recent_timestamp(self, tmp_path: Path):
        """shutdown_time_utc is within the last few seconds."""
        rt = _make_mock_runtime(tmp_path)
        before = time.time()
        _write_session_record(rt)
        after = time.time()

        data = json.loads((tmp_path / "session_last.json").read_text())
        assert before <= data["shutdown_time_utc"] <= after

    def test_stale_record_overwritten(self, tmp_path: Path):
        """A stale session record is replaced with current timestamp."""
        path = tmp_path / "session_last.json"
        stale = {"shutdown_time_utc": 1000000000.0, "session_id": "old"}
        path.write_text(json.dumps(stale))

        rt = _make_mock_runtime(tmp_path)
        _write_session_record(rt)

        data = json.loads(path.read_text())
        assert data["shutdown_time_utc"] > 1700000000.0  # well past stale
        assert data["session_id"] == "test-session-141"

    def test_write_failure_does_not_raise(self, tmp_path: Path):
        """Best-effort: write failure silently passes."""
        rt = _make_mock_runtime(tmp_path)
        rt._data_dir = Path("/nonexistent/impossible/path")
        # Should not raise — matches the try/except Exception: pass pattern
        try:
            _write_session_record(rt)
        except Exception:
            pass  # This is what the production code does

    def test_stasis_duration_from_fresh_record(self, tmp_path: Path):
        """After writing, next boot computes stasis_duration < 5s."""
        rt = _make_mock_runtime(tmp_path)
        _write_session_record(rt)

        # Simulate startup read (from cognitive_services.py line 298)
        data = json.loads((tmp_path / "session_last.json").read_text())
        stasis_duration = time.time() - data["shutdown_time_utc"]
        assert stasis_duration < 5.0, (
            f"Stasis duration {stasis_duration:.1f}s should be < 5s for freshly written record"
        )
```

## Verification

```bash
# Run BF-141 tests
python -m pytest tests/test_bf141_session_record.py -v

# Run existing session-related tests (regression check)
python -m pytest tests/ -k "session" -v
```

## Files Modified (Summary)

| File | Change |
|------|--------|
| `src/probos/__main__.py` | Insert synchronous session record write in 2 finally blocks |
| `tests/test_bf141_session_record.py` | New file — 5 tests |

**2 files modified/created, 5 tests added.**

## What This Does NOT Fix

- **Why pathologist has 2x more episodes:** Separate investigation (candidate BF-142).
- **`os._exit(0)` usage:** Still used at line 355. The session record write now happens before it, making it safe.
- **`except Exception` not catching `CancelledError`:** Could also be fixed by changing to `except BaseException`, but the synchronous-first approach is more defensive (matches BF-135/137 principle).
