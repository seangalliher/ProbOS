"""BF-930 / BF-932: timing lines for the spoken-reply path and the Captain-DM reply path (log-only).

These lines say where the time of one call went. They change no result, order, status or timeout of
what they measure. Durations are milliseconds between two readings of one monotonic clock
(``time.perf_counter``), never wall time. A failure while writing a line is dropped at DEBUG (Tier 1,
swallow: a measurement is never a reason for a reply to fail), and when the DEBUG note fails too (the
logger is what failed) that is dropped without a trace; ``asyncio.CancelledError`` is not an
``Exception`` and passes through.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable


def ms_between(start: float, end: float) -> float:
    """Milliseconds from ``start`` to ``end``, two readings of the same monotonic clock; never negative."""
    return max(0.0, (end - start) * 1000.0)


def _note_dropped(logger: logging.Logger, message: str, *args: object) -> None:
    """The DEBUG note that a line was dropped, with the exception being handled.

    The logger is what failed, so it may fail here too. That is dropped without a trace (Tier 1, swallow):
    nothing is left to write to, and a note must never fail the reply it is about.
    """
    try:
        logger.debug(message, *args, exc_info=True)
    except Exception:
        pass


def emit_line(logger: logging.Logger, message: str, *args: object) -> bool:
    """Write ``message % args`` at INFO. Never raises; True when the line was written."""
    try:
        logger.info(message, *args)
        return True
    except Exception:
        _note_dropped(logger, "BF-930: a timing line failed and was dropped: %s", message)
        return False


class TimingLines:
    """The INFO timing lines of one component instance: at most ``max_lines`` per ``window_s``.

    A line the budget declines is counted, and the next line written ends with ``suppressed=N``, so a
    reader knows the log is not the whole story. ``max_lines`` of 0 or less sets no bound. Make one per
    owner (a store, a service), never a module-level one: its budget is state.
    """

    def __init__(
        self,
        logger: logging.Logger,
        *,
        max_lines: int = 12,
        window_s: float = 60.0,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._logger = logger
        self._max_lines = max_lines
        self._window_s = window_s
        self._clock = clock
        self._written: deque[float] = deque()
        self._suppressed = 0

    def emit(self, message: str, *args: object) -> bool:
        """Write the line unless this window's budget is spent; True when it was written."""
        try:
            if self._max_lines > 0:
                now = self._clock()
                while self._written and now - self._written[0] >= self._window_s:
                    self._written.popleft()
                if len(self._written) >= self._max_lines:
                    self._suppressed += 1
                    return False
                self._written.append(now)
            if self._suppressed:
                message, args = message + " suppressed=%d", (*args, self._suppressed)
                self._suppressed = 0
        except Exception:
            _note_dropped(self._logger, "BF-930: a timing budget failed; the line was dropped: %s", message)
            return False
        return emit_line(self._logger, message, *args)
