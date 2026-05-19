"""AD-733c-4 (Wave 172): idle drop-back tests.

5 tests covering the ``_check_idle_drop_back`` synchronous helper plus
one watchdog integration test that exercises the actual asyncio loop.

BF-287: real ``PerceptionModeController`` with a ``_FakeRuntime`` data
class (``vision_consumer = None`` so transition_to exercises the
no-consumer branch cleanly). No MagicMock at the substrate boundary.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import pytest

from probos.perception.mode_controller import (
    Mode,
    PerceptionModeController,
)


@dataclass
class _FakeRuntime:
    vision_consumer: object | None = None


def _build(
    initial_mode: Mode = Mode.AMBIENT,
    *,
    engaged_idle_seconds: float = 300.0,
    ambient_idle_seconds: float = 1800.0,
    idle_tick_seconds: float = 30.0,
) -> PerceptionModeController:
    return PerceptionModeController(
        _FakeRuntime(),
        initial_mode=initial_mode,
        engaged_idle_seconds=engaged_idle_seconds,
        ambient_idle_seconds=ambient_idle_seconds,
        idle_tick_seconds=idle_tick_seconds,
    )


def test_engaged_drops_to_ambient_after_idle_threshold() -> None:
    c = _build(initial_mode=Mode.ENGAGED, engaged_idle_seconds=0.1)
    # Simulate 1s since last DM activity.
    c._last_dm_activity_at = time.time() - 1.0
    c._check_idle_drop_back()
    assert c.current_mode is Mode.AMBIENT


def test_ambient_drops_to_dormant_after_idle_threshold() -> None:
    c = _build(initial_mode=Mode.AMBIENT, ambient_idle_seconds=0.1)
    # Simulate 1s in AMBIENT.
    c._mode_since = time.time() - 1.0
    c._check_idle_drop_back()
    assert c.current_mode is Mode.DORMANT


def test_engaged_does_not_drop_when_under_threshold() -> None:
    c = _build(initial_mode=Mode.ENGAGED, engaged_idle_seconds=10.0)
    c._last_dm_activity_at = time.time() - 1.0  # well under 10s
    c._check_idle_drop_back()
    assert c.current_mode is Mode.ENGAGED


def test_dormant_stays_put_under_idle_check() -> None:
    c = _build(initial_mode=Mode.DORMANT)
    for _ in range(100):
        c._check_idle_drop_back()
    assert c.current_mode is Mode.DORMANT


@pytest.mark.asyncio
async def test_watchdog_runs_check_on_tick() -> None:
    c = _build(
        initial_mode=Mode.AMBIENT,
        engaged_idle_seconds=0.01,
        idle_tick_seconds=0.05,
    )
    # Manually flip to ENGAGED (manual trigger bypasses cooldown) and back-
    # date last_dm_activity_at so the tick sees an idle ENGAGED.
    c.transition_to(Mode.ENGAGED, trigger="manual")
    c._last_dm_activity_at = time.time() - 1.0
    # Back-date the programmatic-cooldown floor too so the idle_timer
    # transition isn't blocked by the 1s PROGRAMMATIC_COOLDOWN_S that the
    # manual flip above just set.
    c._last_transition_at = 0.0
    await c.start()
    try:
        # Wait long enough for at least one tick (>0.05s) + the drop_back
        # to take effect.
        await asyncio.sleep(0.2)
        assert c.current_mode is Mode.AMBIENT
    finally:
        await c.stop()
