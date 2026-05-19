"""AD-733c-2: PerceptionModeController -- drives the supervisor's tuning knobs
based on engagement state.

Three modes, each a preset bundle (Captain's framing):
- DORMANT  ("in another room"): camera effectively off -- very long
  min_interval, never admits new frames except baseline refresh.
- AMBIENT  ("same room, reading a book"): low cadence, high novelty
  threshold -- only flags BIG scene changes.
- ENGAGED  ("looking at you while we talk"): high cadence, low threshold,
  short baseline_max_age -- body language + per-DM force-describe.

The controller drives ``consumer._supervisor._strategy`` via the BF-308
setters (``set_min_interval_seconds``, ``set_novelty_threshold``,
``set_baseline_max_age_seconds``). It does NOT reach into private state
beyond the setters -- those are the public surface of BF-308.

Lifecycle: ``start()`` schedules the idle-watchdog background task (AD-733c-4
fills in the loop body). ``stop()`` cancels the task, awaits cleanup, and
re-raises CancelledError per ProbOS async-discipline rule.

State persistence: NONE. On boot, mode initializes to AMBIENT if
``perception.enabled`` else DORMANT. Restart-clean per design Q11.

Timestamps: ``time.time()`` (wall-clock) is used throughout because the
controller's state is surfaced to the operator via the /api/perception/mode
GET endpoint -- monotonic values would be meaningless in the UI. NTP drift
over the 30s watchdog tick is negligible for minutes-scale idle thresholds.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
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


# Baked-in presets -- Captain authorized. Editable presets is forward marker.
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
    trigger: str  # "init" | "dm_activity" | "wake_word" | "novelty" |
                  # "idle_timer" | "manual" | "budget_exhausted" (AD-733c-6) |
                  # "voice_activity" (AD-733c-7)


class PerceptionModeController:
    """Owns ``current_mode``, pushes preset values to the supervisor via BF-308."""

    # Cooldown between programmatic transitions (manual override exempt).
    PROGRAMMATIC_COOLDOWN_S = 1.0
    # AD-733c-3: separate floor for wake-word events to prevent UI flap when
    # the detector fires multiple times during the same utterance.
    WAKE_WORD_COOLDOWN_S = 5.0
    # AD-733c-7: Silero VAD secondary trigger. Cooldown sits between
    # PROGRAMMATIC (1s) and WAKE_WORD (5s): speech is more frequent than
    # explicit wake-words but still needs throttling to prevent flap on
    # continuous talk.
    VOICE_ACTIVITY_COOLDOWN_S = 3.0
    HISTORY_CAP = 16

    def __init__(
        self,
        runtime: Any,
        *,
        initial_mode: Mode = Mode.AMBIENT,
        engaged_idle_seconds: float = 300.0,
        ambient_idle_seconds: float = 1800.0,
        idle_tick_seconds: float = 30.0,
        agent_id: str = "",
    ) -> None:
        self._runtime = runtime
        self._agent_id = agent_id  # AD-733c-5: per-agent label for logs
        self._mode: Mode = initial_mode
        # Wall-clock timestamps for operator-facing API + idle math.
        # NTP drift over the 30s watchdog tick is negligible for the
        # minutes-scale idle thresholds; using time.time() throughout
        # keeps the /api/perception/mode response meaningful to humans.
        self._mode_since: float = time.time()
        self._last_dm_activity_at: float = 0.0
        # Initialize to 0 so the FIRST programmatic transition after boot
        # is not falsely blocked by the cooldown floor (the cooldown is for
        # back-to-back transitions, not for the boot->first-engagement path).
        self._last_transition_at: float = 0.0
        # AD-733c-3: wake-word cooldown tracker. Separate from
        # _last_transition_at so a stream of wake-word events is throttled
        # independently of DM-activity / novelty transitions.
        self._last_wake_word_at: float = 0.0
        # AD-733c-7: Silero VAD speech-activity cooldown tracker.
        self._last_voice_activity_at: float = 0.0
        # AD-733c-4: idle drop-back thresholds.
        self._engaged_idle_s: float = float(engaged_idle_seconds)
        self._ambient_idle_s: float = float(ambient_idle_seconds)
        # Floor at 1ms only as a divide-by-zero / negative-timeout guard;
        # the config-level Pydantic validator clamps production values to
        # >= 5.0s. The lower floor here lets unit tests drive sub-second
        # ticks without paying the production cadence.
        self._idle_tick_s: float = max(0.001, float(idle_tick_seconds))
        self._history: deque[Transition] = deque(maxlen=self.HISTORY_CAP)
        self._history.append(
            Transition(at=self._mode_since, from_mode=initial_mode, to_mode=initial_mode, trigger="init")
        )
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event = asyncio.Event()

    # -- Public read API -----------------------------------------------

    @property
    def current_mode(self) -> Mode:
        return self._mode

    @property
    def agent_id(self) -> str:
        """AD-733c-5: ``""`` for the legacy singleton, agent_id otherwise."""
        return self._agent_id

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

    # -- Public write API ----------------------------------------------

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
        # BF-308 setters -- public surface. Honest-degrade: if the consumer
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

    def note_voice_activity(self) -> tuple[bool, str]:
        """AD-733c-7: Silero VAD secondary engagement trigger.

        Step-wise ramp like ``note_dm_activity`` (one mode per call —
        DORMANT -> AMBIENT, AMBIENT -> ENGAGED), but throttled by the
        per-trigger ``VOICE_ACTIVITY_COOLDOWN_S`` (3s) to prevent flap
        on continuous speech. ENGAGED refreshes ``_last_voice_activity_at``
        without re-triggering.

        Returns ``(transitioned, reason)`` mirroring ``note_wake_word``
        so the endpoint can echo the result to the UI:
        ``"transitioned"`` / ``"refreshed"`` / ``"cooldown"`` /
        ``"blocked"``.
        """
        now = time.time()
        if now - self._last_voice_activity_at < self.VOICE_ACTIVITY_COOLDOWN_S:
            logger.debug(
                "AD-733c-7: voice activity ignored (cooldown %.2fs remaining)",
                self.VOICE_ACTIVITY_COOLDOWN_S - (now - self._last_voice_activity_at),
            )
            return (False, "cooldown")
        self._last_voice_activity_at = now
        if self._mode is Mode.ENGAGED:
            return (False, "refreshed")
        target = Mode.AMBIENT if self._mode is Mode.DORMANT else Mode.ENGAGED
        ok = self.transition_to(target, trigger="voice_activity")
        return (ok, "transitioned" if ok else "blocked")

    def note_wake_word(self) -> tuple[bool, str]:
        """Hook called by the AD-733c-3 engage endpoint. Forces ENGAGED.

        Returns ``(transitioned, reason)`` where ``reason`` is one of
        ``"transitioned"`` / ``"refreshed"`` / ``"cooldown"`` / ``"blocked"``.
        The endpoint uses this to populate its response body so the UI
        can surface cooldown rejections to the operator (Captain may want
        to know why a repeated "Hello Ezri" did nothing).
        """
        now = time.time()
        if now - self._last_wake_word_at < self.WAKE_WORD_COOLDOWN_S:
            logger.debug(
                "AD-733c-3: wake-word ignored (cooldown %.2fs remaining)",
                self.WAKE_WORD_COOLDOWN_S - (now - self._last_wake_word_at),
            )
            return (False, "cooldown")
        self._last_wake_word_at = now
        self._last_dm_activity_at = now
        if self._mode is Mode.ENGAGED:
            return (False, "refreshed")
        ok = self.transition_to(Mode.ENGAGED, trigger="wake_word")
        return (ok, "transitioned" if ok else "blocked")

    # -- Background task lifecycle -------------------------------------

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
        """AD-733c-4: idle-watchdog body. Every ``_idle_tick_s`` seconds,
        check whether the current mode has been idle long enough to drop
        one level (ENGAGED -> AMBIENT, AMBIENT -> DORMANT). DORMANT stays
        put -- only manual override / wake-word / DM activity moves it out.

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
        """AD-733c-4: synchronous helper -- called by ``_run`` once per tick.

        Exposed (single-leading-underscore is convention, not capability) so
        unit tests can drive the drop-back logic without spinning the
        watchdog event loop.
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
        # DORMANT: do nothing -- operator action required to leave.
