# AD-417: Dream Scheduler Proactive-Loop Awareness — Build Prompt

## Context

The dream scheduler (`DreamScheduler` in `cognitive/dreaming.py`) distinguishes between idle and active via a single `_last_activity_time` field, reset only by `record_activity()`. Currently only `process_natural_language()` and `propose()` (user-initiated work) call `record_activity()`. The proactive cognitive loop does NOT reset the idle timer — so from the dream scheduler's perspective, the system is "idle" 300 seconds after the last user command, even when agents are actively running proactive thinks every 2 minutes.

**Consequences:**
1. **Full dreams fire during proactive activity.** The idle threshold (300s) is met quickly when there's no user input, so full dream cycles fire every `dream_interval_seconds` (600s = 10 minutes) continuously — even while agents are proactively busy. Full dreams run heavy maintenance (pruning, trust consolidation, strategy extraction, contradiction detection) plus EmergentDetector analysis plus Bridge Alert checks. This is unnecessary when the system is actually doing work — dreams are meant for truly idle periods.
2. **Micro-dreams fire every 10 seconds unconditionally.** Each micro-dream replays new episodes and triggers `EmergentDetector.analyze()` via the `_post_micro_dream_fn` callback. Post-reset, with proactive thinks generating new episodes every couple minutes, micro-dreams replay them quickly and EmergentDetector detects "anomalies" in the fresh-from-zero trust/routing data — producing the trust anomaly cascade the crew observed (O'Brien and Bones flagged these as real issues when they were just calibration noise).

**Goal:** Make the dream scheduler aware of proactive loop activity. When agents are proactively busy, the system is not truly idle — so full dreams should wait for genuine idle periods. Also reduce micro-dream frequency during proactive activity to prevent EmergentDetector noise.

## Part 1: Add `record_proactive_activity()` to DreamScheduler

**File:** `src/probos/cognitive/dreaming.py`

Add a new method to DreamScheduler (after `record_activity()` at line ~362) and a new tracking field:

```python
class DreamScheduler:
    def __init__(self, ...):
        # ... existing fields ...
        self._last_proactive_time: float = 0.0  # AD-417: Track proactive loop activity

    def record_activity(self) -> None:
        """Record that user activity occurred (resets idle timer)."""
        self._last_activity_time = time.monotonic()

    def record_proactive_activity(self) -> None:
        """Record that proactive loop activity occurred (AD-417).

        Proactive activity extends the idle timer but with a weaker effect
        than user activity — the system is "busy but not user-driven".
        """
        self._last_proactive_time = time.monotonic()
```

**No changes to `record_activity()`** — it stays as-is for user-driven work.

## Part 2: Gate full dreams on proactive activity

**File:** `src/probos/cognitive/dreaming.py`

In `_monitor_loop()`, modify the Tier 2 full dream gate (line ~434) to also check proactive activity:

```python
# Tier 2: Full dream when idle long enough
idle_time = now - self._last_activity_time
time_since_last_dream = now - self._last_dream_time

# AD-417: Proactive activity extends the idle threshold.
# If agents are proactively busy, the system isn't truly idle.
proactive_idle = now - self._last_proactive_time
truly_idle = min(idle_time, proactive_idle)

if (
    truly_idle >= self.idle_threshold_seconds
    and time_since_last_dream >= self.dream_interval_seconds
):
```

**Effect:** `truly_idle` is the minimum of time since last user activity AND time since last proactive activity. If either is recent, the system isn't idle enough for a full dream. The 300s threshold now applies to BOTH — no full dream fires until 300s after the last proactive think OR user command, whichever is more recent.

**Note:** `_last_proactive_time` starts at 0.0 in `__init__`, so before any proactive activity occurs, `proactive_idle` will be very large (hours since epoch), and `truly_idle` will correctly fall back to `idle_time`. Only once the proactive loop has started will it begin gating dreams.

## Part 3: Throttle micro-dream EmergentDetector during proactive activity

**File:** `src/probos/cognitive/dreaming.py`

Micro-dreams themselves are lightweight (no LLM calls, just Hebbian updates) — they should keep running. But the `_post_micro_dream_fn` callback triggers `EmergentDetector.analyze()` which produces noisy trust anomaly reports post-reset.

Add a property to expose the proactive-busy state:

```python
@property
def is_proactively_busy(self) -> bool:
    """True if proactive loop activity was recent (within idle threshold)."""
    if self._last_proactive_time == 0.0:
        return False
    return (time.monotonic() - self._last_proactive_time) < self.idle_threshold_seconds
```

**File:** `src/probos/runtime.py`

In `_on_post_micro_dream()` (line ~3280), skip EmergentDetector analysis during proactive-busy periods:

```python
def _on_post_micro_dream(self, micro_report: dict) -> None:
    """Post-micro-dream callback: update emergent detector (AD-288)."""
    if not self._emergent_detector:
        return
    # AD-417: Skip analysis during proactive-busy periods to reduce noise.
    # Micro-dreams keep running (Hebbian updates), but EmergentDetector
    # analysis waits for true idle when data is more stable.
    if self.dream_scheduler and self.dream_scheduler.is_proactively_busy:
        return
    try:
        self._emergent_detector.analyze(dream_report=micro_report)
    except Exception as e:
        logger.debug("Post-micro-dream analysis failed: %s", e)
```

**Effect:** During proactive-busy periods, micro-dreams still replay episodes and update Hebbian weights (useful), but EmergentDetector is not called (was producing noise). EmergentDetector will still run during full dream cycles (which now only fire during true idle).

## Part 4: Wire DreamScheduler to ProactiveCognitiveLoop

**File:** `src/probos/proactive.py`

In `_think_for_agent()`, after the proactive think executes (regardless of outcome — successful post, `[NO_RESPONSE]`, or failure), record proactive activity:

Find the method `_think_for_agent()` and add near the top, before any early returns that indicate actual work was attempted (but AFTER the duty check early-return at line ~156, since skipping an agent due to no duty doesn't count as activity):

The cleanest insertion point is right after the duty check block, before the LLM call. This way, any time the proactive loop actually engages an agent's LLM, it counts as activity — even if the agent returns `[NO_RESPONSE]`.

```python
# AD-417: Record proactive activity for dream scheduler awareness
if hasattr(self._runtime, 'dream_scheduler') and self._runtime.dream_scheduler:
    self._runtime.dream_scheduler.record_proactive_activity()
```

Insert this AFTER the duty schedule check (which may `return` early if no duty is due — skipping is not activity) and BEFORE the `handle_intent()` call.

## Part 5: Add DreamingConfig field for proactive awareness toggle

**File:** `src/probos/config.py`

Add one new field to `DreamingConfig` (currently at line ~161):

```python
class DreamingConfig(BaseModel):
    """Dreaming / offline consolidation configuration."""

    idle_threshold_seconds: float = 120.0  # Tier 2: full dream after idle (AD-288)
    dream_interval_seconds: float = 600.0
    proactive_extends_idle: bool = True     # AD-417: Proactive activity extends idle timer
    replay_episode_count: int = 50
    # ... rest unchanged
```

**File:** `src/probos/cognitive/dreaming.py`

Add constructor parameter and use it:

```python
class DreamScheduler:
    def __init__(
        self,
        engine: DreamingEngine,
        idle_threshold_seconds: float = 300.0,
        dream_interval_seconds: float = 600.0,
        micro_dream_interval_seconds: float = 10.0,
        proactive_extends_idle: bool = True,  # AD-417
    ) -> None:
        # ... existing fields ...
        self.proactive_extends_idle = proactive_extends_idle
        self._last_proactive_time: float = 0.0
```

Then guard the idle calculation:

```python
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

And update `is_proactively_busy`:

```python
@property
def is_proactively_busy(self) -> bool:
    """True if proactive loop activity was recent (within idle threshold)."""
    if not self.proactive_extends_idle or self._last_proactive_time == 0.0:
        return False
    return (time.monotonic() - self._last_proactive_time) < self.idle_threshold_seconds
```

**File:** `src/probos/runtime.py`

Pass the new config field when constructing DreamScheduler (line ~1055):

```python
self.dream_scheduler = DreamScheduler(
    engine=engine,
    idle_threshold_seconds=dream_cfg.idle_threshold_seconds,
    dream_interval_seconds=dream_cfg.dream_interval_seconds,
    proactive_extends_idle=dream_cfg.proactive_extends_idle,
)
```

## Part 6: Update system.yaml

**File:** `config/system.yaml`

Add the new field under the `dreaming:` section, after `dream_interval_seconds`:

```yaml
dreaming:
  idle_threshold_seconds: 300
  dream_interval_seconds: 600
  proactive_extends_idle: true    # AD-417: Proactive thinks extend idle timer
```

## Part 7: Tests

**File:** `tests/test_dreaming.py` (add to existing file)

Add a new test class `TestDreamSchedulerProactiveAwareness` with these tests:

### Test 1: `test_record_proactive_activity_updates_timestamp`
- Create a DreamScheduler
- Assert `_last_proactive_time` is 0.0 initially
- Call `record_proactive_activity()`
- Assert `_last_proactive_time` is now > 0

### Test 2: `test_proactive_activity_prevents_full_dream`
- Create DreamScheduler with `idle_threshold_seconds=1.0, dream_interval_seconds=0.1`
- Start the scheduler
- Run a tight loop where you call `record_proactive_activity()` every 0.3s for 3s
- Assert no full dream fired (check `last_dream_report is None` or mock the engine's `dream_cycle`)
- Stop calling `record_proactive_activity()`
- Wait for idle threshold + dream interval (e.g., 2s)
- Assert full dream fires

### Test 3: `test_proactive_activity_does_not_affect_micro_dreams`
- Create DreamScheduler with `micro_dream_interval_seconds=0.1`
- Call `record_proactive_activity()`
- Start scheduler, wait briefly
- Assert micro-dreams still fire (check `_micro_dream_count > 0` or mock `engine.micro_dream`)

### Test 4: `test_is_proactively_busy_property`
- Create DreamScheduler with `idle_threshold_seconds=2.0`
- Assert `is_proactively_busy` is False (no proactive activity yet)
- Call `record_proactive_activity()`
- Assert `is_proactively_busy` is True
- Wait 2.5 seconds
- Assert `is_proactively_busy` is False (proactive activity expired)

### Test 5: `test_proactive_extends_idle_disabled`
- Create DreamScheduler with `proactive_extends_idle=False, idle_threshold_seconds=1.0, dream_interval_seconds=0.1`
- Call `record_proactive_activity()` repeatedly
- Assert full dream still fires (proactive activity ignored when disabled)
- Assert `is_proactively_busy` is False (disabled)

### Test 6: `test_user_activity_still_overrides_proactive`
- Create DreamScheduler with `idle_threshold_seconds=2.0`
- Call `record_proactive_activity()` — system is proactively busy
- Call `record_activity()` — user activity resets idle timer too
- Wait 2.5 seconds without either activity
- Assert full dream fires (both timers expired)

### Test 7: `test_config_field_exists`
- Create `DreamingConfig()` with defaults
- Assert `proactive_extends_idle` is True
- Create `DreamingConfig(proactive_extends_idle=False)`
- Assert it's False

### Test 8: `test_skip_emergent_during_proactive_busy`
- This tests the runtime-level behavior from Part 3
- Create a mock runtime with dream_scheduler where `is_proactively_busy = True`
- Call `_on_post_micro_dream({"episodes_replayed": 5})`
- Assert `_emergent_detector.analyze()` was NOT called
- Set `is_proactively_busy = False`
- Call `_on_post_micro_dream({"episodes_replayed": 5})`
- Assert `_emergent_detector.analyze()` WAS called

## Verification

After implementation:
1. Run `uv run pytest tests/test_dreaming.py -x -v` — all tests pass (existing + 8 new)
2. Run `uv run pytest tests/test_proactive.py -x -v` — no regressions
3. Run `uv run pytest tests/test_duty_schedule.py -x -v` — no regressions
4. Run `uv run pytest tests/ -x -q` — full suite clean

## Summary

| Part | File | Change |
|------|------|--------|
| 1 | dreaming.py | `record_proactive_activity()` method + `_last_proactive_time` field |
| 2 | dreaming.py | Full dream gate uses `truly_idle = min(idle_time, proactive_idle)` |
| 3 | dreaming.py + runtime.py | `is_proactively_busy` property; skip EmergentDetector in micro-dream callback |
| 4 | proactive.py | Call `record_proactive_activity()` before agent think |
| 5 | config.py + dreaming.py + runtime.py | `proactive_extends_idle` config toggle |
| 6 | system.yaml | Default value in config |
| 7 | test_dreaming.py | 8 new tests in TestDreamSchedulerProactiveAwareness |

**After this AD:** Full dreams will only fire during genuine idle periods — when neither user commands nor proactive thinks have occurred for 300 seconds. Post-reset trust anomaly cascading will be reduced because EmergentDetector won't run during proactive-busy micro-dreams. The proactive loop and dream scheduler will finally be aware of each other, creating a proper active/idle lifecycle: user activity → active; proactive loop → busy; neither for 5 min → idle → dream.
