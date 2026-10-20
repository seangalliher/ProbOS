"""A fake monotonic clock for ``probos.proactive``, shared by the tests that need a machine of a chosen uptime.

``time.monotonic()`` counts from machine boot, so the proactive loop's behaviour depends on how old the machine is (BF-909).
These helpers let a test pick that uptime without sleeping and without depending on the machine the suite runs on.

Only the module's own ``time`` name is replaced (``probos.proactive.time``). Patching ``time.monotonic`` itself would
freeze the event loop's clock too (``BaseEventLoop.time()`` calls it), and any ``asyncio.sleep`` in a test would never wake.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

import probos.proactive as proactive_module


class FakeClock:
    """The clock the loop reads: it starts at ``start`` seconds of machine uptime and moves only when a test advances it."""

    def __init__(self, start: float) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class LoopTime:
    """``probos.proactive.time`` as the loop reads it: ``monotonic`` is the fake clock, every other name is the real module's."""

    def __init__(self, clock: FakeClock) -> None:
        self.monotonic = clock

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)


def install_loop_clock(monkeypatch: pytest.MonkeyPatch, start: float) -> FakeClock:
    """Install a fake monotonic clock, ``start`` seconds after boot, as the one ``probos.proactive`` reads.

    Build the loop AFTER installing the clock, so the loop's cold-start reference (``_started_at``) reads the fake clock
    too. The patch is undone by ``monkeypatch`` when the test ends.
    """
    clock = FakeClock(start)
    monkeypatch.setattr(proactive_module, "time", LoopTime(clock))
    return clock
