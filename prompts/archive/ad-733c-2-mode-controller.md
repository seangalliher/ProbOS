# AD-733c-2 — PerceptionModeController

**Status:** Drafted 2026-05-18, awaiting GATE 1.
**Closes (part of):** #675.
**Estimated tests:** +12 pytest, +4 vitest.
**Depends on:** AD-733c-1 (force-describe path), BF-308 (hot-reload setters on `PerceptualHashStrategy`), AD-733a `VisionConsumer`.

## Problem

Today the supervisor's tuning knobs (`min_interval_seconds`, `novelty_threshold`, `baseline_max_age_seconds`) are set once at consumer construction and only changed via operator hand-tuning. The Captain's three-mode metaphor (dormant / ambient / engaged) needs those knobs to swing automatically based on engagement signals.

**Solution:** new `PerceptionModeController` holds `current_mode`, exposes `transition_to(mode)` which pushes a preset bundle's values into the live strategy via the BF-308 setters. Two API endpoints (`GET` for status, `POST` for manual override). Surfaced in the CameraLiveIndicator + PerceptionLivePanel.

## Solution overview

1. **New module** `src/probos/perception/mode_controller.py` with `Mode` Enum, `ModePreset` dataclass, `PerceptionModeController` class. Three baked-in presets (DORMANT/AMBIENT/ENGAGED).
2. **`transition_to(mode)`** pushes the preset's values to the consumer's supervisor via the BF-308 setters. Idempotent: same-mode call logs DEBUG and returns. Cooldown of 1s on programmatic transitions.
3. **`note_dm_activity()`** — public hook called by `routers/agents.py:agent_chat`. Updates `last_dm_activity_at`. AMBIENT → ENGAGED on first activity after AMBIENT-entry. (DORMANT does NOT auto-engage on DM — only manual override or wake-word; rationale below.)
4. **`note_high_novelty_event()`** — hook called by `ProactiveVisionObserver` when high-novelty fires. AMBIENT → ENGAGED (the "you sat down" trigger).
5. **API endpoints** on the existing `routers/perception.py` router:
    - `GET /api/perception/mode` → `{mode, since, last_dm_activity, presets, transitions: [last 3]}`
    - `POST /api/perception/mode {mode: "engaged"}` → manual operator override.
6. **finalize.py wiring** constructs the controller next to `VisionConsumer`, sets `runtime.perception_mode_controller`, calls `controller.start()` for the background timer task (AD-733c-4 fills in the timer body; this prompt ships start/stop scaffolding with a no-op loop).
7. **shutdown.py wiring** awaits `controller.stop()` mirroring the `recording_reaper` pattern.
8. **UI:** `CameraLiveIndicator` gains a small text-mode badge. `PerceptionLivePanel` gains a "Mode" section showing current state + last 3 transitions + manual override buttons.

### Why DORMANT does not auto-engage on DM

A DM arriving while in DORMANT means the Captain explicitly typed something, but DORMANT semantically means "the agent is in another room" — getting a DM should ramp up gradually (DORMANT → AMBIENT first, then on subsequent activity AMBIENT → ENGAGED). Rationale: prevents a single keystroke after a long idle from spending an immediate vision LLM call before the operator has actually started conversing. The wake-word path (AD-733c-3) is the explicit "engage now" channel.

Decision: `note_dm_activity()` transitions DORMANT → AMBIENT, AMBIENT → ENGAGED (one-step at a time), ENGAGED → ENGAGED (refresh `last_dm_activity_at` only).

### Section 1: new module `src/probos/perception/mode_controller.py`

```python
"""AD-733c-2: PerceptionModeController — drives the supervisor's tuning knobs
based on engagement state.

Three modes, each a preset bundle (Captain's framing):
- DORMANT  ("in another room"): camera effectively off — very long
  min_interval, never admits new frames except baseline refresh.
- AMBIENT  ("same room, reading a book"): low cadence, high novelty
  threshold — only flags BIG scene changes.
- ENGAGED  ("looking at you while we talk"): high cadence, low threshold,
  short baseline_max_age — body language + per-DM force-describe.

The controller drives ``consumer._supervisor._strategy`` via the BF-308
setters (``set_min_interval_seconds``, ``set_novelty_threshold``,
``set_baseline_max_age_seconds``). It does NOT reach into private state
beyond the setters — those are the public surface of BF-308.

Lifecycle: ``start()`` schedules the idle-watchdog background task (AD-733c-4
fills in the loop body). ``stop()`` cancels the task, awaits cleanup, and
re-raises CancelledError per ProbOS async-discipline rule.

State persistence: NONE. On boot, mode initializes to AMBIENT if
``perception.enabled`` else DORMANT. Restart-clean per design Q11.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Mode(str, Enum):
    DORMANT = "dormant"
    AMBIENT = "ambient"
    ENGAGED = "engaged"


@dataclass(frozen=True)
class ModePreset:
    min_interval_seconds: float
    novelty_threshold: float
    baseline_max_age_seconds: float


# Baked-in presets — Captain authorized. Editable presets is forward marker.
DORMANT_PRESET = ModePreset(
    min_interval_seconds=60.0,
    novelty_threshold=1.0,        # 1.0 means "never admits on novelty alone"
    baseline_max_age_seconds=0.0, # 0 disables baseline refresh
)
AMBIENT_PRESET = ModePreset(
    min_interval_seconds=10.0,
    novelty_threshold=0.25,
    baseline_max_age_seconds=120.0,
)
ENGAGED_PRESET = ModePreset(
    min_interval_seconds=2.0,
    novelty_threshold=0.06,
    baseline_max_age_seconds=15.0,
)

# Public mapping so routers/UI can fetch the preset table without
# reaching into private module state.
PRESETS: dict[Mode, ModePreset] = {
    Mode.DORMANT: DORMANT_PRESET,
    Mode.AMBIENT: AMBIENT_PRESET,
    Mode.ENGAGED: ENGAGED_PRESET,
}


@dataclass
class Transition:
    """One row in the transition history ring buffer."""
    at: float
    from_mode: Mode
    to_mode: Mode
    trigger: str  # "init" | "dm_activity" | "wake_word" | "novelty" | "idle_timer" | "manual"


class PerceptionModeController:
    """Owns ``current_mode``, pushes preset values to the supervisor via BF-308."""

    # Cooldown between programmatic transitions (manual override exempt).
    PROGRAMMATIC_COOLDOWN_S = 1.0
    HISTORY_CAP = 16

    def __init__(self, runtime: Any, *, initial_mode: Mode = Mode.AMBIENT) -> None:
        self._runtime = runtime
        self._mode: Mode = initial_mode
        # Wall-clock timestamps for operator-facing API + idle math.
        # NTP drift over the 30s watchdog tick is negligible for the
        # minutes-scale idle thresholds; using time.time() throughout
        # keeps the /api/perception/mode response meaningful to humans.
        self._mode_since: float = time.time()
        self._last_dm_activity_at: float = 0.0
        self._last_transition_at: float = self._mode_since
        self._history: deque[Transition] = deque(maxlen=self.HISTORY_CAP)
        self._history.append(
            Transition(at=self._mode_since, from_mode=initial_mode, to_mode=initial_mode, trigger="init")
        )
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event = asyncio.Event()

    # ── Public read API ────────────────────────────────────────────

    @property
    def current_mode(self) -> Mode:
        return self._mode

    @property
    def mode_since(self) -> float:
        return self._mode_since

    @property
    def last_dm_activity_at(self) -> float:
        return self._last_dm_activity_at

    def recent_transitions(self, limit: int = 3) -> list[Transition]:
        """Newest-first list of the last N transitions."""
        items = list(self._history)
        items.reverse()
        return items[: max(1, min(limit, self.HISTORY_CAP))]

    def get_preset(self, mode: Mode) -> ModePreset:
        return PRESETS[mode]

    # ── Public write API ───────────────────────────────────────────

    def transition_to(self, mode: Mode, *, trigger: str = "manual") -> bool:
        """Push the preset for ``mode`` to the supervisor. Idempotent.

        Returns True when a real transition happened, False when no-op
        (same mode, or programmatic cooldown active).
        """
        now = time.time()
        if mode == self._mode:
            logger.debug("AD-733c-2: transition_to(%s) is no-op (already current)", mode.value)
            return False
        if trigger != "manual":
            since_last = now - self._last_transition_at
            if since_last < self.PROGRAMMATIC_COOLDOWN_S:
                logger.debug(
                    "AD-733c-2: programmatic transition %s -> %s blocked by cooldown (%.2fs)",
                    self._mode.value, mode.value, since_last,
                )
                return False
        preset = PRESETS[mode]
        prev_mode = self._mode
        # BF-308 setters — public surface. Honest-degrade: if the consumer
        # is absent (subsystem disabled mid-run), the controller still
        # tracks the mode value so the operator UI stays coherent.
        consumer = getattr(self._runtime, "vision_consumer", None)
        if consumer is not None:
            strategy = getattr(getattr(consumer, "_supervisor", None), "_strategy", None)
            if strategy is not None:
                try:
                    strategy.set_min_interval_seconds(preset.min_interval_seconds)
                    strategy.set_novelty_threshold(preset.novelty_threshold)
                    strategy.set_baseline_max_age_seconds(preset.baseline_max_age_seconds)
                except Exception:
                    logger.warning(
                        "AD-733c-2: BF-308 setter failed during %s -> %s",
                        prev_mode.value, mode.value, exc_info=True,
                    )
        self._mode = mode
        self._mode_since = now
        self._last_transition_at = now
        self._history.append(
            Transition(at=now, from_mode=prev_mode, to_mode=mode, trigger=trigger)
        )
        logger.info(
            "AD-733c-2: mode %s -> %s (trigger=%s)",
            prev_mode.value, mode.value, trigger,
        )
        return True

    def note_dm_activity(self) -> None:
        """Hook for ``routers/agents.py:agent_chat``. Step-wise ramp:
        DORMANT -> AMBIENT, AMBIENT -> ENGAGED, ENGAGED -> ENGAGED (refresh).
        """
        self._last_dm_activity_at = time.time()
        if self._mode is Mode.DORMANT:
            self.transition_to(Mode.AMBIENT, trigger="dm_activity")
        elif self._mode is Mode.AMBIENT:
            self.transition_to(Mode.ENGAGED, trigger="dm_activity")

    def note_high_novelty_event(self) -> None:
        """Hook called by ProactiveVisionObserver on a high-novelty emission.
        AMBIENT -> ENGAGED; DORMANT and ENGAGED unchanged.
        """
        if self._mode is Mode.AMBIENT:
            self.transition_to(Mode.ENGAGED, trigger="novelty")

    def note_wake_word(self) -> None:
        """Hook called by the AD-733c-3 engage endpoint. Forces ENGAGED."""
        if self._mode is not Mode.ENGAGED:
            self.transition_to(Mode.ENGAGED, trigger="wake_word")
        else:
            # Already engaged — refresh activity so idle timer resets.
            self._last_dm_activity_at = time.monotonic()

    # ── Background task lifecycle ─────────────────────────────────

    async def start(self) -> None:
        """Schedule the idle-watchdog task. AD-733c-4 fills the loop body.

        Idempotent: a second call while a task is running is a no-op.
        """
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run(), name="perception_mode_controller_idle_watch"
        )

    async def stop(self) -> None:
        """Cancel the background task and await cleanup."""
        self._stop_event.set()
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("AD-733c-2: stop() background task raised", exc_info=True)
        finally:
            self._task = None

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

### Section 2: finalize.py wiring

`src/probos/startup/finalize.py` — insert AFTER the existing VisionConsumer wire-up (immediately after `runtime.vision_consumer = consumer`).

SEARCH (anchor on the post-consumer log):
```python
            consumer.subscribe()
            runtime.vision_consumer = consumer
            logger.info(
                "AD-733a: VisionConsumer wired with %d observers",
                len(consumer.observer_agent_ids),
            )
```
REPLACE WITH:
```python
            consumer.subscribe()
            runtime.vision_consumer = consumer
            logger.info(
                "AD-733a: VisionConsumer wired with %d observers",
                len(consumer.observer_agent_ids),
            )

            # AD-733c-2 (Wave 172): PerceptionModeController — drives the
            # BF-308 setters based on engagement state. Default: AMBIENT
            # when perception enabled; the idle watchdog (AD-733c-4) will
            # eventually drop to DORMANT after extended idle.
            from probos.perception.mode_controller import (
                PerceptionModeController,
                Mode as _PerceptionMode,
            )
            _controller = PerceptionModeController(
                runtime, initial_mode=_PerceptionMode.AMBIENT
            )
            # Apply the AMBIENT preset to the live supervisor so the
            # default boot state matches the mode.
            _controller.transition_to(_PerceptionMode.AMBIENT, trigger="init")
            await _controller.start()
            runtime.perception_mode_controller = _controller
            logger.info("AD-733c-2: PerceptionModeController wired (initial=ambient)")
```

### Section 3: shutdown.py wiring

`src/probos/startup/shutdown.py` — add a stop hook mirroring `recording_reaper` (line 203 region).

SEARCH:
```python
    if hasattr(runtime, 'recording_reaper') and runtime.recording_reaper is not None:
```
REPLACE WITH:
```python
    # AD-733c-2: stop the perception mode controller's idle watchdog.
    if (
        hasattr(runtime, 'perception_mode_controller')
        and runtime.perception_mode_controller is not None
    ):
        try:
            await runtime.perception_mode_controller.stop()
        except Exception:
            logger.warning("AD-733c-2: mode_controller.stop() failed", exc_info=True)
        runtime.perception_mode_controller = None

    if hasattr(runtime, 'recording_reaper') and runtime.recording_reaper is not None:
```

### Section 4: API endpoints in routers/perception.py

Append at the end of `src/probos/routers/perception.py`:

```python


# AD-733c-2 (Wave 172) — Mode status + manual override.

@router.get("/mode", dependencies=[Depends(require_crew_scope)])
async def get_perception_mode(runtime: Any = Depends(get_runtime)) -> Any:
    """Return the current PerceptionMode, when it transitioned, the last DM
    activity, the three preset bundles, and the most recent transitions.
    """
    controller = getattr(runtime, "perception_mode_controller", None)
    if controller is None:
        return JSONResponse(
            status_code=503,
            content={"error": "perception_mode_controller_unavailable"},
        )
    from probos.perception.mode_controller import PRESETS, Mode

    presets = {
        m.value: {
            "min_interval_seconds": p.min_interval_seconds,
            "novelty_threshold": p.novelty_threshold,
            "baseline_max_age_seconds": p.baseline_max_age_seconds,
        }
        for m, p in PRESETS.items()
    }
    transitions = [
        {
            "at": t.at,
            "from_mode": t.from_mode.value,
            "to_mode": t.to_mode.value,
            "trigger": t.trigger,
        }
        for t in controller.recent_transitions(limit=3)
    ]
    return {
        "mode": controller.current_mode.value,
        "since": controller.mode_since,
        "last_dm_activity": controller.last_dm_activity_at,
        "presets": presets,
        "transitions": transitions,
    }


class _PerceptionModeRequest(BaseModel):
    mode: str


@router.post("/mode", dependencies=[Depends(require_crew_scope)])
async def post_perception_mode(
    body: _PerceptionModeRequest,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """Manual operator override. Trigger='manual' bypasses the programmatic cooldown."""
    controller = getattr(runtime, "perception_mode_controller", None)
    if controller is None:
        return JSONResponse(
            status_code=503,
            content={"error": "perception_mode_controller_unavailable"},
        )
    from probos.perception.mode_controller import Mode
    try:
        target = Mode(body.mode.strip().lower())
    except ValueError:
        return JSONResponse(
            status_code=400, content={"error": "invalid_mode", "value": body.mode},
        )
    changed = controller.transition_to(target, trigger="manual")
    return {"ok": True, "mode": controller.current_mode.value, "changed": changed}
```

Add the `BaseModel` import near the top of the file:
SEARCH:
```python
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
```
REPLACE WITH:
```python
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
```

### Section 5: hook into agent_chat DM-activity

`src/probos/routers/agents.py` — extend the force-describe block from AD-733c-1 to also call `note_dm_activity()`.

SEARCH:
```python
            _consumer = getattr(runtime, "vision_consumer", None)
            if _consumer is not None and getattr(
                _perception_cfg, "dm_force_describe_enabled", True,
            ):
                try:
                    await _consumer.force_describe_current_frame(timeout_s=4.0)
                except Exception:
                    logger.debug(
                        "AD-733c-1: force_describe raised for %s",
                        agent_id, exc_info=True,
                    )
```
REPLACE WITH:
```python
            _consumer = getattr(runtime, "vision_consumer", None)
            if _consumer is not None and getattr(
                _perception_cfg, "dm_force_describe_enabled", True,
            ):
                try:
                    await _consumer.force_describe_current_frame(timeout_s=4.0)
                except Exception:
                    logger.debug(
                        "AD-733c-1: force_describe raised for %s",
                        agent_id, exc_info=True,
                    )
            # AD-733c-2: notify the mode controller of DM activity so the
            # AMBIENT -> ENGAGED transition (and ENGAGED freshness) tracks
            # the real conversational tempo.
            _mode_ctrl = getattr(runtime, "perception_mode_controller", None)
            if _mode_ctrl is not None:
                try:
                    _mode_ctrl.note_dm_activity()
                except Exception:
                    logger.debug(
                        "AD-733c-2: note_dm_activity raised", exc_info=True,
                    )
```

### Section 6: ProactiveVisionObserver hook

`src/probos/perception/observer.py` — call `note_high_novelty_event()` when a high-novelty emission lands. Locate `_decide_and_emit` (line ~85) and add the hook after a successful dispatch.

(Builder: grep `_dispatch_proactive_dm` and insert the controller call AFTER the dispatch succeeds. Pattern: `getattr(self._runtime, "perception_mode_controller", None)` then try/except note_high_novelty_event. Single new block, ~6 lines.)

### Section 7: UI surfaces

**`ui/src/components/perception/CameraLiveIndicator.tsx`** — add a Mode badge after the existing "CAMERA LIVE" span. New stroke-SVG amber-tinted label `DORMANT | AMBIENT | ENGAGED`. Read mode from new Zustand store slice.

**New file `ui/src/store/usePerceptionModeStore.ts`** — Zustand slice with `mode: 'dormant' | 'ambient' | 'engaged'`, `transitions: Transition[]`, `refresh()` action that fetches `GET /api/perception/mode` every 5s when perception is active.

**`ui/src/components/settings/sections/PerceptionLivePanel.tsx`** — append a "Mode" section showing current state + the last 3 transitions + three buttons (DORMANT / AMBIENT / ENGAGED) wired to `POST /api/perception/mode`.

All glyphs: inline stroke SVG `strokeWidth: 1.5`. Active mode amber `#f0b060`, inactive dim `#666680`. No emoji (HXI #3).

### Tests

**pytest (+12)** in new `tests/test_ad733c2_mode_controller.py`:

1. `test_initial_state_ambient` — controller boots in AMBIENT; transition history has one `init` entry.
2. `test_transition_to_engaged_pushes_preset` — uses a real `PerceptualHashStrategy` + a `_FakeConsumer` wrapping it; assert all three setters fired with ENGAGED_PRESET values.
3. `test_same_mode_transition_is_noop` — `transition_to(AMBIENT)` while AMBIENT → returns False, history unchanged.
4. `test_programmatic_cooldown_blocks_rapid_transitions` — two consecutive non-manual transitions within 1s → second returns False.
5. `test_manual_override_bypasses_cooldown` — manual trigger ignores cooldown.
6. `test_note_dm_activity_ambient_to_engaged` — AMBIENT + DM → ENGAGED.
7. `test_note_dm_activity_dormant_to_ambient` — DORMANT + DM → AMBIENT (one step only).
8. `test_note_dm_activity_engaged_only_refreshes` — ENGAGED + DM → still ENGAGED; `last_dm_activity_at` updated.
9. `test_note_high_novelty_event_ambient_to_engaged` — AMBIENT + novelty → ENGAGED.
10. `test_start_stop_idle_watchdog_clean` — start, stop, assert task is None and no CancelledError leaked into the test.
11. `test_get_mode_endpoint_returns_status` — async TestClient GET; assert 200, mode/since/presets/transitions all present.
12. `test_post_mode_endpoint_manual_override` — POST {mode: "engaged"}; assert mode flipped; subsequent GET reflects.

Plus extend `test_ad731_invariant_no_inline_base64_in_perception_modules` to cover `mode_controller.py`.

**vitest (+4)** in `ui/src/components/perception/__tests__/CameraLiveIndicator.modeBadge.test.tsx` and `ui/src/components/settings/sections/__tests__/PerceptionLivePanel.modeSection.test.tsx`:

1. CameraLiveIndicator renders amber badge when `mode === 'engaged'`.
2. CameraLiveIndicator renders dim badge when `mode === 'dormant'`.
3. PerceptionLivePanel shows last 3 transitions newest-first.
4. PerceptionLivePanel ENGAGED button calls `POST /api/perception/mode` with body `{mode: 'engaged'}`.

### What this does NOT change

- `VisionConsumer.force_describe_current_frame` — untouched (introduced in AD-733c-1).
- BF-308 setters on `PerceptualHashStrategy` — untouched. We CONSUME them, not modify.
- AD-731 invariant — preserved (no new frame-handling code in the controller).
- AD-541b anchored episodes — preserved (controller doesn't touch the episode path).
- The idle drop-back logic — STUBBED in `_run()` with a 30s sleep loop. AD-733c-4 fills the body.

### Tracking

- **PROGRESS.md:** AD-733c-2 entry under Wave 172. Tracker += 16 (12 pytest + 4 vitest).
- **DECISIONS.md:** append AD-733c-2 paragraph.
- **roadmap.md:** no change — #675 stays open until AD-733c-4.

### Acceptance criteria

- All 12 new pytest pass under `pytest -n 4 --dist=loadfile`.
- All 4 new vitest pass under `cd ui; npx vitest run`.
- `cd ui; npm run build` succeeds (Wave 155 stale-bundle lesson — `vitest run` is NOT a build gate).
- Existing 20 AD-733a/733b tests still pass.
- `runtime.perception_mode_controller` available after boot when `perception.enabled` is True.
- `stop()` cleanly cancels the watchdog task (no `unawaited task` warnings in pytest output).
- Verify all changes comply with Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-18)

```
grep -n "set_min_interval_seconds" src/probos/perception/supervisor.py
  57: def set_min_interval_seconds(self, value: float) -> None:

grep -n "set_novelty_threshold" src/probos/perception/supervisor.py
  61: def set_novelty_threshold(self, value: float) -> None:

grep -n "set_baseline_max_age_seconds" src/probos/perception/supervisor.py
  65: def set_baseline_max_age_seconds(self, value: float) -> None:

grep -n "AD-733a: VisionConsumer wired with" src/probos/startup/finalize.py
  3981: logger.info("AD-733a: VisionConsumer wired with %d observers",

grep -n "recording_reaper is not None" src/probos/startup/shutdown.py
  203: if hasattr(runtime, 'recording_reaper') and runtime.recording_reaper is not None:

grep -n "from fastapi.responses import JSONResponse" src/probos/routers/perception.py
  20: from fastapi.responses import JSONResponse

grep -n "_dispatch_proactive_dm" src/probos/perception/observer.py
  132: async def _dispatch_proactive_dm(

grep -n "AD-733c-1: force_describe raised" src/probos/routers/agents.py
  (NEW in AD-733c-1; verify after AD-733c-1 merges)
```

The `mode_controller.py` module is introduced by this prompt — absence at HEAD is expected. The `AD-733c-1: force_describe raised` anchor is introduced by AD-733c-1 and must be present at the time this prompt runs (build order enforces this).
