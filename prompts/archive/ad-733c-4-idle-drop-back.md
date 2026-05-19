# AD-733c-4 — Idle drop-back timers

**Status:** Drafted 2026-05-18, awaiting GATE 1.
**Closes:** #675 (umbrella — final sub-AD).
**Estimated tests:** +5 pytest.
**Depends on:** AD-733c-2 (controller + `_run()` watchdog scaffolding), AD-733c-3 (wake-word cooldown tracking).

## Problem

The controller's watchdog task (`_run()`) currently no-ops. Without idle drop-back, the system stays in ENGAGED forever after the first DM, paying engaged-cadence vision LLM costs for an absent operator.

**Solution:** every 30s the watchdog computes the seconds since `last_dm_activity_at`. If ENGAGED and `> engaged_idle_seconds` (default 300s = 5 min), drop to AMBIENT. If AMBIENT and `> ambient_idle_seconds` (default 1800s = 30 min), drop to DORMANT. DORMANT stays put — only manual override / wake-word / DM activity moves it out.

## Solution overview

1. **PerceptionConfig** gains `engaged_idle_seconds` and `ambient_idle_seconds` fields with sensible defaults.
2. **Controller** stores those thresholds (passed via constructor from finalize.py) and consults them in `_run()`.
3. **`_run()` body** replaces the stub with the drop-back check. Trigger label `"idle_timer"`. Logged at INFO so the operator can correlate the drop in CameraLiveIndicator with the log entry.
4. **AMBIENT-entry timestamp.** To compute "30 min of ambient idle", we use `mode_since` (already tracked) — the ambient drop-back compares `now - mode_since` since DM activity in AMBIENT wouldn't have transitioned (DM activity in AMBIENT goes to ENGAGED per AD-733c-2). So `mode_since` IS the AMBIENT-entry time for any session that reached AMBIENT.

### Section 1: PerceptionConfig fields

`src/probos/config.py` — add to `PerceptionConfig` next to the AD-733c-1 field.

SEARCH:
```python
    # AD-733c-1 (Wave 172): DM-receive force-describe of the latest cached frame
    # before the agent's reply is composed. 4s wall-clock timeout enforced by
    # VisionConsumer.force_describe_current_frame. Default True so the
    # subsystem benefits from fresh-frame grounding out of the box; operator
    # can disable for cost-discipline experiments.
    dm_force_describe_enabled: bool = Field(default=True,
        description="On every DM, synchronously describe the latest captured frame before composing the reply (4s timeout floor).",
    )
```
REPLACE WITH:
```python
    # AD-733c-1 (Wave 172): DM-receive force-describe of the latest cached frame
    # before the agent's reply is composed. 4s wall-clock timeout enforced by
    # VisionConsumer.force_describe_current_frame. Default True so the
    # subsystem benefits from fresh-frame grounding out of the box; operator
    # can disable for cost-discipline experiments.
    dm_force_describe_enabled: bool = Field(default=True,
        description="On every DM, synchronously describe the latest captured frame before composing the reply (4s timeout floor).",
    )

    # AD-733c-4 (Wave 172): idle drop-back thresholds. ENGAGED -> AMBIENT
    # after engaged_idle_seconds of no DM activity. AMBIENT -> DORMANT
    # after ambient_idle_seconds since entering AMBIENT (AMBIENT-entry is
    # tracked via the controller's mode_since timestamp).
    engaged_idle_seconds: float = Field(default=300.0, ge=30.0, le=3600.0,
        description="ENGAGED -> AMBIENT after this many seconds of no DM activity. Default 5 min.",
    )
    ambient_idle_seconds: float = Field(default=1800.0, ge=60.0, le=86400.0,
        description="AMBIENT -> DORMANT after this many seconds in AMBIENT with no engagement signal. Default 30 min.",
    )
    idle_watchdog_tick_seconds: float = Field(default=30.0, ge=5.0, le=300.0,
        description="How often the controller's idle watchdog polls. Default 30s.",
    )
```

### Section 2: controller constructor accepts thresholds

`src/probos/perception/mode_controller.py` — extend `__init__` to accept idle thresholds.

SEARCH:
```python
    def __init__(self, runtime: Any, *, initial_mode: Mode = Mode.AMBIENT) -> None:
        self._runtime = runtime
        self._mode: Mode = initial_mode
        self._mode_since: float = time.monotonic()
        self._last_dm_activity_at: float = 0.0
        self._last_transition_at: float = self._mode_since
        # AD-733c-3: wake-word cooldown tracker. Separate from
        # _last_transition_at so a stream of wake-word events is throttled
        # independently of DM-activity / novelty transitions.
        self._last_wake_word_at: float = 0.0
```
REPLACE WITH:
```python
    def __init__(
        self,
        runtime: Any,
        *,
        initial_mode: Mode = Mode.AMBIENT,
        engaged_idle_seconds: float = 300.0,
        ambient_idle_seconds: float = 1800.0,
        idle_tick_seconds: float = 30.0,
    ) -> None:
        self._runtime = runtime
        self._mode: Mode = initial_mode
        self._mode_since: float = time.monotonic()
        self._last_dm_activity_at: float = 0.0
        self._last_transition_at: float = self._mode_since
        # AD-733c-3: wake-word cooldown tracker. Separate from
        # _last_transition_at so a stream of wake-word events is throttled
        # independently of DM-activity / novelty transitions.
        self._last_wake_word_at: float = 0.0
        # AD-733c-4: idle drop-back thresholds.
        self._engaged_idle_s: float = float(engaged_idle_seconds)
        self._ambient_idle_s: float = float(ambient_idle_seconds)
        self._idle_tick_s: float = max(1.0, float(idle_tick_seconds))
```

### Section 3: replace `_run()` stub with drop-back logic

`src/probos/perception/mode_controller.py` — replace the stub watchdog body.

SEARCH:
```python
    async def _run(self) -> None:
        """Idle-watchdog body. AD-733c-2 ships a 30s tick that does nothing
        (the AD-733c-4 prompt extends this method with the drop-back logic).

        Async-discipline: catch CancelledError, perform cleanup, re-raise.
        """
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    # AD-733c-4 inserts the drop-back logic here.
                    pass
        except asyncio.CancelledError:
            logger.debug("AD-733c-2: idle watchdog cancelled")
            raise
        except Exception:
            logger.warning("AD-733c-2: idle watchdog crashed", exc_info=True)
            raise
```
REPLACE WITH:
```python
    async def _run(self) -> None:
        """AD-733c-4: idle-watchdog body. Every ``_idle_tick_s`` seconds,
        check whether the current mode has been idle long enough to drop
        one level (ENGAGED -> AMBIENT, AMBIENT -> DORMANT). DORMANT stays
        put — only manual override / wake-word / DM activity moves it out.

        Async-discipline: catch CancelledError, perform cleanup, re-raise.
        """
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._idle_tick_s,
                    )
                except asyncio.TimeoutError:
                    try:
                        self._check_idle_drop_back()
                    except Exception:
                        logger.warning(
                            "AD-733c-4: idle drop-back check raised",
                            exc_info=True,
                        )
        except asyncio.CancelledError:
            logger.debug("AD-733c-2: idle watchdog cancelled")
            raise
        except Exception:
            logger.warning("AD-733c-2: idle watchdog crashed", exc_info=True)
            raise

    def _check_idle_drop_back(self) -> None:
        """Synchronous helper — called by ``_run`` once per tick.

        Public-ish: exposed for tests via the bare name (no underscore-only
        guard at the test boundary; this is the unit-testable seam).
        """
        now = time.time()
        if self._mode is Mode.ENGAGED:
            # DM-activity tracks engagement; if no DM in engaged_idle_s,
            # drop to AMBIENT.
            idle = now - (self._last_dm_activity_at or self._mode_since)
            if idle >= self._engaged_idle_s:
                self.transition_to(Mode.AMBIENT, trigger="idle_timer")
        elif self._mode is Mode.AMBIENT:
            # Time in AMBIENT counted from mode_since; no DM activity will
            # have moved us out (DM in AMBIENT -> ENGAGED per AD-733c-2).
            idle = now - self._mode_since
            if idle >= self._ambient_idle_s:
                self.transition_to(Mode.DORMANT, trigger="idle_timer")
        # DORMANT: do nothing — operator action required to leave.
```

### Section 4: finalize.py passes config thresholds

`src/probos/startup/finalize.py` — extend the controller construction with the new config fields.

SEARCH:
```python
            from probos.perception.mode_controller import (
                PerceptionModeController,
                Mode as _PerceptionMode,
            )
            _controller = PerceptionModeController(
                runtime, initial_mode=_PerceptionMode.AMBIENT
            )
```
REPLACE WITH:
```python
            from probos.perception.mode_controller import (
                PerceptionModeController,
                Mode as _PerceptionMode,
            )
            _controller = PerceptionModeController(
                runtime,
                initial_mode=_PerceptionMode.AMBIENT,
                engaged_idle_seconds=_perception_cfg.engaged_idle_seconds,
                ambient_idle_seconds=_perception_cfg.ambient_idle_seconds,
                idle_tick_seconds=_perception_cfg.idle_watchdog_tick_seconds,
            )
```

### Tests

**pytest (+5)** in `tests/test_ad733c4_idle_drop_back.py`:

1. `test_engaged_drops_to_ambient_after_idle_threshold` — construct controller with `engaged_idle_seconds=0.1`; manually set `_mode = ENGAGED`, `_last_dm_activity_at = time.time() - 1.0`; call `_check_idle_drop_back()`; assert mode is now AMBIENT.
2. `test_ambient_drops_to_dormant_after_idle_threshold` — construct with `ambient_idle_seconds=0.1`; manually set `_mode = AMBIENT`, `_mode_since = time.time() - 1.0`; call `_check_idle_drop_back()`; assert DORMANT.
3. `test_engaged_does_not_drop_when_under_threshold` — `engaged_idle_seconds=10.0`, `last_dm_activity = time.time() - 1.0`; check; assert still ENGAGED.
4. `test_dormant_stays_put_under_idle_check` — `_mode = DORMANT`; check 100 times; assert still DORMANT.
5. `test_watchdog_runs_check_on_tick` — construct with `idle_tick_seconds=0.05`, `engaged_idle_seconds=0.01`; `await controller.start()`; manually set engaged + stale `last_dm_activity_at`; `await asyncio.sleep(0.15)`; `await controller.stop()`; assert mode flipped to AMBIENT during the sleep.

All 5 tests use real `PerceptionModeController` instances; no MagicMock at the substrate boundary (BF-287). Wrap controller construction in a small `_FakeRuntime` data class with `vision_consumer = None` so `transition_to` exercises the no-consumer branch cleanly.

### What this does NOT change

- `note_dm_activity` / `note_wake_word` / `note_high_novelty_event` — untouched. They are the engagement signals; drop-back is the inverse.
- BF-308 setters — pushed via `transition_to` as always. Drop-back uses the same path.
- AD-541b episodes — preserved (no new code in the frame path).
- Multi-Captain handling — out of scope (single-Captain v1).

### Tracking

- **PROGRESS.md:** AD-733c-4 entry under Wave 172. Tracker += 5.
- **DECISIONS.md:** append AD-733c-4 paragraph. Close-out paragraph for the AD-733c umbrella.
- **roadmap.md:** close #675 with the four sub-ADs cited. File AD-733c-5/6/7 as new forward-marker issues at GATE 1 BEFORE Builder dispatch.

### Acceptance criteria

- All 5 new pytest pass under `pytest -n 4 --dist=loadfile`.
- Existing AD-733c-2 / AD-733c-3 tests still pass.
- Wave acceptance smoke (per WAVE-172-DISPATCH § Acceptance test for the wave):
  - Boot in AMBIENT → wait 5 min → still AMBIENT (drop-back NOT triggered yet, since `ambient_idle_seconds` default is 30 min).
  - Manual `POST /api/perception/mode {mode: "engaged"}` → wait > 5 min → drop to AMBIENT via idle_timer trigger (log line).
  - Manual ENGAGED → wait > 35 min → drop AMBIENT then DORMANT.
- Verify all changes comply with Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-18)

```
grep -n "engaged_idle_seconds" src/probos/config.py
  (NEW — introduced by this prompt)

grep -n "_check_idle_drop_back" src/probos/perception/mode_controller.py
  (NEW — introduced by this prompt)

grep -n "ambient_idle_seconds" src/probos/config.py
  (NEW — introduced by this prompt)
```

All anchors in SEARCH blocks point at code introduced by AD-733c-2 (mode_controller.py `_run`, finalize.py controller construction) and AD-733c-1 (`dm_force_describe_enabled` config field). Build order enforces those land first.
