# BF-114b: Remove Dead `proactive_extends_idle` Code Path

**Type:** Bug fix cleanup (dead code removal)
**Priority:** Medium
**Prerequisite:** BF-114 (config toggle set to `false`) — already applied

## Context

AD-417 added `proactive_extends_idle` to prevent full dream cycles from firing while the proactive loop is active. BF-114 discovered that this creates an impossible condition: proactive fires every ~120s, `truly_idle = min(idle_time, proactive_idle)` caps idle at ~120s, but `idle_threshold_seconds = 300` — so full dreams can **never** fire. The toggle was set to `false` in BF-114. With `false`, the entire feature is dead code:

- `record_proactive_activity()` updates `_last_proactive_time` which nothing reads
- `is_proactively_busy` always returns `False`
- The `truly_idle = min(...)` branch is never entered
- `DreamAdapter.on_post_micro_dream()` has a dead guard on `is_proactively_busy`

The feature cannot work correctly in any realistic configuration (proactive interval would need to exceed `idle_threshold_seconds`, i.e., agents think less than once every 5 minutes). Remove the entire code path.

## What This Removes

1. `proactive_extends_idle` field from `DreamingConfig`
2. `proactive_extends_idle` line from `config/system.yaml`
3. `proactive_extends_idle` constructor parameter from `DreamScheduler.__init__()`
4. `self.proactive_extends_idle` instance attribute
5. `self._last_proactive_time` instance attribute
6. `record_proactive_activity()` method on `DreamScheduler`
7. `is_proactively_busy` property on `DreamScheduler`
8. The `truly_idle = min(idle_time, proactive_idle)` branch — simplify to `truly_idle = idle_time`
9. The `record_proactive_activity()` call in `proactive.py`
10. The `proactive_extends_idle` wiring in `startup/dreaming.py`
11. The `is_proactively_busy` guard in `DreamAdapter.on_post_micro_dream()`
12. The entire `TestDreamSchedulerProactiveAwareness` test class (9 tests)

## What This Does NOT Touch

- `_last_proactive_scan_time` — this is AD-532e (Cognitive JIT proactive procedure scanning), completely separate from AD-417. Do NOT remove.
- `record_activity()` — this is the user-activity idle timer, unrelated. Do NOT remove.
- `micro_dream_interval_seconds` — unrelated. Do NOT touch.
- Micro-dream logic — fires unconditionally on its own interval. Do NOT touch.
- Full dream idle gate logic — the `truly_idle >= self.idle_threshold_seconds` check stays, just simplified to use `idle_time` directly.

## Files Modified

| File | Change |
|------|--------|
| `src/probos/config.py` | Remove `proactive_extends_idle` field from `DreamingConfig` (line 289) |
| `config/system.yaml` | Remove `proactive_extends_idle` line (line 89) |
| `src/probos/cognitive/dreaming.py` | Remove constructor param, `_last_proactive_time`, `record_proactive_activity()`, `is_proactively_busy`, simplify `_monitor_loop()` idle calculation |
| `src/probos/proactive.py` | Remove `record_proactive_activity()` call (lines 419-421) |
| `src/probos/startup/dreaming.py` | Remove `proactive_extends_idle=` kwarg from `DreamScheduler()` constructor call (line 117) |
| `src/probos/dream_adapter.py` | Remove `is_proactively_busy` guard in `on_post_micro_dream()` (lines 249-251) |
| `tests/test_dreaming.py` | Remove entire `TestDreamSchedulerProactiveAwareness` class (lines 896-1077) |

## Files NOT Modified / Created

No new files. No docs changes required beyond what BF-114 already recorded.

## Design Details

### 1. `DreamScheduler.__init__()` — Remove parameter and attributes

**Before:**
```python
def __init__(
    self,
    engine: DreamingEngine,
    idle_threshold_seconds: float = 300.0,
    dream_interval_seconds: float = 600.0,
    micro_dream_interval_seconds: float = 10.0,
    proactive_extends_idle: bool = True,  # AD-417
) -> None:
    ...
    self.proactive_extends_idle = proactive_extends_idle
    ...
    self._last_proactive_time: float = 0.0  # AD-417
```

**After:**
```python
def __init__(
    self,
    engine: DreamingEngine,
    idle_threshold_seconds: float = 300.0,
    dream_interval_seconds: float = 600.0,
    micro_dream_interval_seconds: float = 10.0,
) -> None:
    ...
    # Remove: self.proactive_extends_idle
    # Remove: self._last_proactive_time
```

### 2. Remove `record_proactive_activity()` and `is_proactively_busy`

Delete these entirely from `DreamScheduler`:

```python
# DELETE:
def record_proactive_activity(self) -> None:
    """Record that the proactive loop just completed a think cycle."""
    self._last_proactive_time = time.monotonic()

# DELETE:
@property
def is_proactively_busy(self) -> bool:
    """True if proactive loop activity was recent (within idle threshold)."""
    if not self.proactive_extends_idle or self._last_proactive_time == 0.0:
        return False
    return (time.monotonic() - self._last_proactive_time) < self.idle_threshold_seconds
```

### 3. Simplify `_monitor_loop()` idle calculation

**Before:**
```python
# Tier 2: Full dream when idle long enough
idle_time = now - self._last_activity_time
time_since_last_dream = now - self._last_dream_time

# AD-417: Proactive activity extends the idle threshold
proactive_idle = now - self._last_proactive_time
if self.proactive_extends_idle and self._last_proactive_time > 0:
    truly_idle = min(idle_time, proactive_idle)
else:
    truly_idle = idle_time

if (
    truly_idle >= self.idle_threshold_seconds
    and time_since_last_dream >= self.dream_interval_seconds
):
```

**After:**
```python
# Tier 2: Full dream when idle long enough
idle_time = now - self._last_activity_time
time_since_last_dream = now - self._last_dream_time

if (
    idle_time >= self.idle_threshold_seconds
    and time_since_last_dream >= self.dream_interval_seconds
):
```

### 4. Remove caller in `proactive.py`

**Delete lines 419-421:**
```python
# AD-417: Record proactive activity for dream scheduler awareness
if hasattr(self._runtime, 'dream_scheduler') and self._runtime.dream_scheduler:
    self._runtime.dream_scheduler.record_proactive_activity()
```

### 5. Remove wiring in `startup/dreaming.py`

**Before (line 113-118):**
```python
dream_scheduler = DreamScheduler(
    engine=dreaming_engine,
    idle_threshold_seconds=dream_cfg.idle_threshold_seconds,
    dream_interval_seconds=dream_cfg.dream_interval_seconds,
    proactive_extends_idle=dream_cfg.proactive_extends_idle,
)
```

**After:**
```python
dream_scheduler = DreamScheduler(
    engine=dreaming_engine,
    idle_threshold_seconds=dream_cfg.idle_threshold_seconds,
    dream_interval_seconds=dream_cfg.dream_interval_seconds,
)
```

### 6. Remove guard in `dream_adapter.py`

**Before (lines 245-255):**
```python
def on_post_micro_dream(self, micro_report: dict[str, Any]) -> None:
    """Post-micro-dream callback: update emergent detector (AD-288)."""
    if not self._emergent_detector:
        return
    # AD-417: Skip analysis during proactive-busy periods to reduce noise.
    if self._dream_scheduler and self._dream_scheduler.is_proactively_busy:
        return
    try:
        self._emergent_detector.analyze(dream_report=micro_report, duty_completions=[])
    except Exception as e:
        logger.debug("Post-micro-dream analysis failed: %s", e)
```

**After:**
```python
def on_post_micro_dream(self, micro_report: dict[str, Any]) -> None:
    """Post-micro-dream callback: update emergent detector (AD-288)."""
    if not self._emergent_detector:
        return
    try:
        self._emergent_detector.analyze(dream_report=micro_report, duty_completions=[])
    except Exception as e:
        logger.debug("Post-micro-dream analysis failed: %s", e)
```

### 7. Remove `DreamingConfig.proactive_extends_idle`

**Before (`config.py` line 289):**
```python
proactive_extends_idle: bool = True     # AD-417: Proactive activity extends idle timer
```

**After:** Delete the line entirely.

### 8. Remove `system.yaml` line

**Before (`config/system.yaml` line 89):**
```yaml
proactive_extends_idle: false   # BF-114: true blocked all full dream cycles
```

**After:** Delete the line entirely.

### 9. Remove test class

Delete the entire `TestDreamSchedulerProactiveAwareness` class from `tests/test_dreaming.py` (lines 896-1077, 9 tests). All 9 tests exclusively test the removed feature. General dream behavior (idle timers, micro-dreams, full dreams) is already covered by `TestDreamScheduler` and other test classes in the same file.

**Verify** that `on_post_micro_dream` calling `EmergentDetector.analyze()` is tested elsewhere. If not, add one focused test:

```python
def test_post_micro_dream_calls_emergent_detector():
    """on_post_micro_dream triggers EmergentDetector analysis."""
    from unittest.mock import MagicMock
    from probos.dream_adapter import DreamAdapter
    from probos.runtime import ProbOSRuntime

    rt = ProbOSRuntime.__new__(ProbOSRuntime)
    rt._emergent_detector = MagicMock()
    rt.dream_adapter = DreamAdapter(rt)

    rt.dream_adapter.on_post_micro_dream({"episodes_replayed": 5})
    rt._emergent_detector.analyze.assert_called_once()
```

Place this in an appropriate existing test class or as a standalone function in `test_dreaming.py`.

## Engineering Principles Compliance

- **DRY:** Removing dead code — no duplication introduced.
- **SOLID (I — Interface Segregation):** `DreamScheduler`'s public API becomes narrower. Consumers no longer see `record_proactive_activity()` or `is_proactively_busy` that serve no purpose.
- **Fail Fast:** No error handling changes. `on_post_micro_dream` retains its `try/except` with `logger.debug()` — appropriate for non-critical callback.
- **Law of Demeter:** No reaching through objects. `dream_adapter.py` no longer reaches into `dream_scheduler.is_proactively_busy`.
- **Cloud-Ready Storage:** No storage changes.

## Verification

1. Run dream scheduler tests: `pytest tests/test_dreaming.py -v`
2. Run dream adapter tests: `pytest tests/ -k "dream_adapter" -v`
3. Run proactive tests: `pytest tests/test_proactive*.py -v`
4. Run full test suite: `pytest --tb=short`
5. Verify no remaining references: `grep -r "proactive_extends_idle\|record_proactive_activity\|is_proactively_busy\|_last_proactive_time" src/ config/ tests/ --include="*.py" --include="*.yaml"` — should return zero results (docs/prompts/decisions may still reference historically, that's fine)
6. Verify `_last_proactive_scan_time` is NOT removed: `grep -r "_last_proactive_scan_time" src/` — should still show hits in `dreaming.py`

## Test Impact

- **Removed:** 9 tests (entire `TestDreamSchedulerProactiveAwareness` class)
- **Added:** 1 test (`test_post_micro_dream_calls_emergent_detector`) — preserves the salvageable half of `test_skip_emergent_during_proactive_busy`
- **Net:** -8 tests

This is correct — we are removing a feature, not adding one. The removed tests tested behavior that no longer exists.
