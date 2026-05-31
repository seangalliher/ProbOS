# BF-291: AD-825 shutdown field access raises AttributeError on transitional restart

**Closes:** #764
**Type:** Bug fix — defensive coding
**Estimated diff:** ~30 LOC source + ~100 LOC test
**Estimated tests added:** 5

## Problem

`src/probos/startup/shutdown.py` reads two `MemoryConfig` fields
(`shutdown_consolidation_timeout_s`, `shutdown_drain_timeout_s`) via direct
attribute access guarded only by truthiness checks on the parent objects:

```python
float(
    getattr(getattr(runtime, "config", None), "memory", None).shutdown_consolidation_timeout_s
    if (getattr(runtime, "config", None) and getattr(runtime.config, "memory", None))
    else 30.0
)
```

The guard checks that `runtime.config.memory` *exists*. It does NOT check that
the *named field* exists on it. When a long-running runtime started with an
older `MemoryConfig` (pre-AD-820 / pre-AD-825) shuts down with the new
`shutdown.py` code on disk, the direct `.shutdown_consolidation_timeout_s`
access raises `AttributeError`, the exception propagates out of `shutdown()`,
the AD-825 drain phase never runs, and AD-820's `shutdown_status.json`
integrity marker is never written. The next boot has no signal that
consolidation was skipped.

This defeats the entire intent of AD-825 (graceful drain before cancel) for
any process spanning a config schema change — the exact scenario AD-825 was
designed to survive.

## Affected Sites

Three direct-attribute reads in `src/probos/startup/shutdown.py`:

| Line | Field |
|---|---|
| 110 | `shutdown_consolidation_timeout_s` |
| 127 | `shutdown_drain_timeout_s` (AD-825 quiesce of DreamScheduler) |
| 216 | `shutdown_drain_timeout_s` (AD-825 drain phase) |

Sites 127 and 216 read the same field; site 110 reads a different one. All
three share the same fragile pattern.

## Fix Design

Introduce a single module-private helper near the top of `shutdown.py`
(after the `logger = ...` line, before `async def shutdown(...)`):

```python
def _memory_field(runtime: Any, name: str, default: float) -> float:
    """BF-291: defensively read a MemoryConfig field with a fallback.

    Direct attribute access raises ``AttributeError`` on Pydantic v2 models
    when the field is absent — which happens transitionally when a process
    started before a new field was added is shutting down with newer
    ``shutdown.py`` code on disk. The ``getattr``-with-default form skips
    Pydantic's strict ``__getattr__`` path entirely.
    """
    cfg = getattr(getattr(runtime, "config", None), "memory", None)
    if cfg is None:
        return default
    return float(getattr(cfg, name, default))
```

Replace all three call sites with:

- Line 110: `_shutdown_consolidation_timeout = _memory_field(runtime, "shutdown_consolidation_timeout_s", 30.0)`
- Line 122-131 (`_drain_budget = float(...)` block): `_drain_budget = _memory_field(runtime, "shutdown_drain_timeout_s", 30.0)`
- Line 213-222 (`_drain_budget = float(...)` block): same replacement

## Section 1: Add the helper

In `src/probos/startup/shutdown.py`, after the `logger = logging.getLogger(__name__)` line and before `async def shutdown(...)`:

```search
logger = logging.getLogger(__name__)


async def shutdown(runtime: ProbOSRuntime, reason: str = "") -> None:
```

```replace
logger = logging.getLogger(__name__)


def _memory_field(runtime: Any, name: str, default: float) -> float:
    """BF-291: defensively read a MemoryConfig field with a fallback.

    Direct attribute access raises ``AttributeError`` on Pydantic v2 models
    when the field is absent — which happens transitionally when a process
    started before a new field was added is shutting down with newer
    ``shutdown.py`` code on disk. The ``getattr``-with-default form skips
    Pydantic's strict ``__getattr__`` path entirely.
    """
    cfg = getattr(getattr(runtime, "config", None), "memory", None)
    if cfg is None:
        return default
    return float(getattr(cfg, name, default))


async def shutdown(runtime: ProbOSRuntime, reason: str = "") -> None:
```

## Section 2: Replace the consolidation-timeout read (~line 110)

```search
    _shutdown_consolidation_timeout = float(
        getattr(getattr(runtime, "config", None), "memory", None).shutdown_consolidation_timeout_s
        if (getattr(runtime, "config", None) and getattr(runtime.config, "memory", None))
        else 30.0
    )
```

```replace
    _shutdown_consolidation_timeout = _memory_field(
        runtime, "shutdown_consolidation_timeout_s", 30.0,
    )
```

## Section 3: Replace the DreamScheduler-quiesce drain read (~line 122)

```search
    if runtime.dream_scheduler:
        try:
            _drain_budget = float(
                getattr(
                    getattr(runtime, "config", None), "memory", None,
                ).shutdown_drain_timeout_s
                if (
                    getattr(runtime, "config", None)
                    and getattr(runtime.config, "memory", None)
                )
                else 30.0
            )
            _ok = await runtime.dream_scheduler.stop_gracefully(
                timeout=_drain_budget,
            )
```

```replace
    if runtime.dream_scheduler:
        try:
            _drain_budget = _memory_field(
                runtime, "shutdown_drain_timeout_s", 30.0,
            )
            _ok = await runtime.dream_scheduler.stop_gracefully(
                timeout=_drain_budget,
            )
```

## Section 4: Replace the AD-825 drain-phase read (~line 213)

```search
            pending_snapshot = list(drain_tasks)
            if pending_snapshot:
                _drain_budget = float(
                    getattr(
                        getattr(runtime, "config", None), "memory", None,
                    ).shutdown_drain_timeout_s
                    if (
                        getattr(runtime, "config", None)
                        and getattr(runtime.config, "memory", None)
                    )
                    else 30.0
                )
                logger.info(
                    "AD-825: draining %d write-holding task(s) (budget=%.1fs)",
                    len(pending_snapshot), _drain_budget,
                )
```

```replace
            pending_snapshot = list(drain_tasks)
            if pending_snapshot:
                _drain_budget = _memory_field(
                    runtime, "shutdown_drain_timeout_s", 30.0,
                )
                logger.info(
                    "AD-825: draining %d write-holding task(s) (budget=%.1fs)",
                    len(pending_snapshot), _drain_budget,
                )
```

## Section 5: Tests

Create `tests/test_bf291_shutdown_field_absence.py`. Tests should mirror the
`_MiniRuntime` style used in `tests/test_ad825_drain_shutdown.py` (no full
runtime boot).

Required test cases:

1. **`test_memory_field_returns_default_when_field_absent`** — construct a
   Pydantic v2 `BaseModel` with NO `shutdown_consolidation_timeout_s` field;
   build a stub runtime with `config.memory = that_model`; assert
   `_memory_field(runtime, "shutdown_consolidation_timeout_s", 30.0) == 30.0`
   and does NOT raise. This is the core regression test.

2. **`test_memory_field_returns_value_when_field_present`** — use a
   `MemoryConfig`-shaped model where the field IS present with a non-default
   value (e.g. 45.0); assert the helper returns 45.0.

3. **`test_memory_field_returns_default_when_config_is_none`** — stub runtime
   with `config = None`; assert helper returns the default without raising.

4. **`test_memory_field_returns_default_when_memory_is_none`** — stub runtime
   with `config.memory = None`; assert helper returns the default without
   raising.

5. **`test_shutdown_completes_when_memory_config_lacks_both_fields`** —
   integration-style: build a `_MiniRuntime`-shaped stub whose `config.memory`
   is a Pydantic model lacking BOTH `shutdown_consolidation_timeout_s` AND
   `shutdown_drain_timeout_s`. Call `await shutdown(runtime, reason="test")`.
   Assert no `AttributeError` is raised. (Stub out
   `runtime.event_log.log`, `runtime.ward_room`, `runtime.dream_scheduler`,
   `runtime.episodic_memory`, etc. with simple async stubs / `None` as
   needed — follow the pattern in `test_ad825_drain_shutdown.py` for what
   surface to provide.)

   Note: this test exercises only the early phases of `shutdown()`. It does
   NOT need to drive the full shutdown to completion — the goal is to prove
   the field-access lines don't raise. If reaching the AD-825 drain phase
   requires too much stub surface, you may early-return the shutdown by
   leaving `runtime._started = False` AFTER asserting the helper calls
   succeed via direct unit tests (1-4); test 5 is then optional/bonus.

Use `pytest.mark.asyncio` for any async tests.

## What This Does NOT Change

- `MemoryConfig` schema in `config.py` (the fields stay where they are)
- Default values (still 30.0 for both fields)
- AD-825 drain semantics (drain order, cancel-sweep fallthrough, integrity marker)
- Any other startup/shutdown module
- The live runtime — operator's `probos.pid` is already absent (shut down)

## Tracking

- `PROGRESS.md` — append OPEN→CLOSED row for BF-291
- `docs/development/roadmap.md` Bug Tracker — add BF-291 row
- DECISIONS.md — **no entry** (defensive bug fix, no architectural choice)

## Acceptance Criteria

1. Run `D:\ProbOS\.venv\Scripts\pytest.exe -n 0 --timeout=60 tests/test_bf291_shutdown_field_absence.py` — all new tests pass.
2. Run `D:\ProbOS\.venv\Scripts\pytest.exe -n 0 --timeout=60 tests/test_ad820_consolidation_timeout.py tests/test_ad821_*.py tests/test_ad822_*.py tests/test_ad823_*.py tests/test_ad824_*.py tests/test_ad825_drain_shutdown.py` — all AD-820..825 regression tests still green.
3. Run the full parallel gate `D:\ProbOS\.venv\Scripts\pytest.exe tests/ -q -n 4 --dist=loadfile` — no new failures vs HEAD baseline.
4. Single commit with message `BF-291: defensive MemoryConfig field access in shutdown.py (closes #764)`.
5. Push to `origin/main` after gates green.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Standing Constraints

- DO NOT touch the live runtime (pidfile at `C:\Users\seang\AppData\Local\ProbOS\data\probos.pid` — already absent, but the directory is off-limits).
- DO NOT touch anything under `C:\Users\seang\AppData\Local\ProbOS\`.
- Single commit. Source diff ~30 LOC; test file ~100 LOC.
- If any AD-820..825 test fails after this change, STOP and surface — it
  means the helper changed observable behaviour, which it should not.

## Verified Against Codebase (2026-05-22)

```
grep -n "shutdown_consolidation_timeout_s\|shutdown_drain_timeout_s" src/probos/startup/shutdown.py
  110:        getattr(getattr(runtime, "config", None), "memory", None).shutdown_consolidation_timeout_s
  127:                ).shutdown_drain_timeout_s
  216:                ).shutdown_drain_timeout_s
```

Three call sites confirmed (BF body mentions two; the third at line 216 in
the AD-825 drain phase has the same bug and is included in this fix).

```
grep -n "^logger = " src/probos/startup/shutdown.py
  20:logger = logging.getLogger(__name__)
```

Module-scope helper insertion point confirmed between line 20 and the
`async def shutdown(...)` signature at line 23.

```
file_exists tests/test_ad825_drain_shutdown.py → yes
```

Confirmed; `_MiniRuntime` fixture pattern at lines 19-50 is the template
for the new test module.
