"""BF-932 (#1670): the loop-stall sampler names the code that holds the event loop (log-only).

A heartbeat coroutine on the event loop stamps a monotonic clock every quarter of the threshold. A daemon thread reads
the stamp at the same cadence. When the stamp is older than the threshold, the thread reads the loop thread's current
stack (``sys._current_frames``: the file, line and function of the innermost frames; no locals, no arguments, no
source lines) and logs one WARNING for that stall. The first heartbeat after that stall records the gap between its
stamp and the stalled one, and the thread logs that gap in one INFO: the gap of that one beat, so a late check cannot
make it larger. WARNING lines are bounded per window, and the next one written says how many were refused
(``suppressed=N``); a resume line is written only for a stall whose WARNING was written.

Shutdown: the thread checks the stop event, the loop and ``active`` at the start of every check and again between
reading the frames and writing the WARNING, so a WARNING whose frames were read after any of them said stop is not
written. The heartbeat's cancellation sets the stop event, before anything on that path can log, and joins the thread
for at most ``_JOIN_TIMEOUT_S``. The thread ends at once unless it is inside a logging call (a slow handler); it then
ends when that call returns and writes no further line. It is a daemon, so the interpreter does not wait for the
thread's own code at exit.

The sampler changes nothing the loop runs and adds no wait of its own to the loop thread except that bounded join. The
heartbeat and the thread share one lock, held only to read or write the stamps (no logging, no frame reading and no
wait under it). The thread's log calls use the same handlers as every other thread's: while it writes a line, a log
call from the loop thread that reaches the same handler, or ``logging.shutdown()`` at a normal interpreter exit, waits
for that handler's lock, as it would for any other thread's write. A failure in the thread is dropped at DEBUG with the
error's text only (Tier 1, swallow: a measurement is never a reason for the vessel to fail; a kept traceback would keep
the sampled frames alive). ProbOS requires Python 3.12 or later; CPython issue 106883 (a collection inside
``sys._current_frames`` deadlocked) was seen on 3.11.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from pathlib import PurePath

logger = logging.getLogger(__name__)

THREAD_NAME = "probos-loop-stall-sampler"
_STACK_DEPTH = 12
_JOIN_TIMEOUT_S = 1.0


def _innermost_frames(thread_id: int, depth: int) -> str:
    """The innermost ``depth`` frames of ``thread_id`` as ``dir/file.py:line function``, innermost first."""
    frame = sys._current_frames().get(thread_id)
    if frame is None:
        return "(no frame)"
    try:
        summary = traceback.StackSummary.extract(traceback.walk_stack(frame), limit=depth, lookup_lines=False)
    finally:
        del frame  # on every path: the sampled frame holds the loop thread's locals
    return " <- ".join(
        f"{'/'.join(PurePath(entry.filename).parts[-2:])}:{entry.lineno} {entry.name}" for entry in summary
    )


def _drop(error: Exception) -> None:
    """Tier 1: a failed check is logged at DEBUG with its text only (a kept traceback keeps sampled frames)."""
    try:
        logger.debug("BF-932: a loop-stall check failed and was dropped: %s", repr(error))
    except Exception:
        pass


class _WarningBudget:
    """At most ``max_lines`` WARNING lines per ``window_s``; the next line written after a refusal ends ``suppressed=N``.

    The rule of ``probos.utils.step_timing.TimingLines``, which writes at INFO. It is not reused so that that module,
    which the voice path shares, stays unchanged. ``max_lines`` of 0 or less sets no bound.
    """

    def __init__(self, max_lines: int, window_s: float) -> None:
        self._max_lines = max_lines
        self._window_s = window_s
        self._written: deque[float] = deque()
        self._suppressed = 0

    def emit(self, message: str, *args: object) -> bool:
        """Write the WARNING unless this window's budget is spent; True when it was written."""
        if self._max_lines > 0:
            now = time.monotonic()
            while self._written and now - self._written[0] >= self._window_s:
                self._written.popleft()
            if len(self._written) >= self._max_lines:
                self._suppressed += 1
                return False
            self._written.append(now)
        if self._suppressed:
            message, args = message + " suppressed=%d", (*args, self._suppressed)
            self._suppressed = 0
        logger.warning(message, *args)
        return True


class LoopStallSampler:
    """One heartbeat on the event loop and one daemon thread that watches it (BF-932, #1670).

    ``active`` (optional) is read by the thread at the start of each check and again before each WARNING; once it
    returns False the thread ends. ``clock`` is the monotonic clock the heartbeat stamps and the thread reads.
    ``checks``, ``stall_count`` and ``resume_count`` count the thread's checks, the stalls it found (reported or not)
    and the stalls that ended.
    """

    def __init__(
        self,
        *,
        threshold_s: float,
        max_warnings: int = 10,
        window_s: float = 60.0,
        active: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0.0 < threshold_s / 4.0 <= threading.TIMEOUT_MAX:
            raise ValueError("threshold_s must be finite and greater than 0")
        self._threshold_s = threshold_s
        self._tick_s = threshold_s / 4.0
        self._active = active
        self._clock = clock
        self._warnings = _WarningBudget(max_warnings, window_s)
        self._lock = threading.Lock()  # the three stamps below; held only to read or write them
        self._last_beat = clock()
        self._stalled_beat: float | None = None  # the stamp of the stall the thread found, until it ends
        self._resume_gap_s: float | None = None  # set by the first heartbeat after that stall
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.checks = 0
        self.stall_count = 0
        self.resume_count = 0

    async def run(self) -> None:
        """Beat on the running loop and watch it from a daemon thread until cancelled.

        A second ``run`` while the first one's thread is alive returns at once. AD-824: on cancellation the thread is
        told to stop and joined for at most ``_JOIN_TIMEOUT_S`` (a thread inside a logging call ends when that call
        returns; see the module docstring), and the cancellation propagates.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.debug("BF-932: the loop-stall sampler is already running; this start is ignored")
            return
        loop = asyncio.get_running_loop()
        self._stop.clear()
        self._last_beat = self._clock()
        thread = threading.Thread(
            target=self._watch, args=(loop, threading.get_ident()), name=THREAD_NAME, daemon=True,
        )
        self._thread = thread
        thread.start()
        try:
            while True:
                with self._lock:
                    now = self._clock()
                    if self._last_beat == self._stalled_beat:  # the first beat after the stall the thread found
                        self._resume_gap_s = now - self._last_beat
                    self._last_beat = now
                await asyncio.sleep(self._tick_s)
        finally:  # nothing on the cancellation path logs before the stop event is set
            self._stop.set()
            thread.join(timeout=_JOIN_TIMEOUT_S)

    def _ended(self, loop: asyncio.AbstractEventLoop) -> bool:
        """True once the thread should end: told to stop, the loop closed, or ``active`` says no."""
        return self._stop.is_set() or loop.is_closed() or (self._active is not None and not self._active())

    def _watch(self, loop: asyncio.AbstractEventLoop, loop_thread_id: int) -> None:
        """The thread: one check per tick, until stopped, until the loop closes, or once ``active`` says no."""
        stalled = False
        reported = False
        try:
            while not self._stop.wait(self._tick_s):
                try:
                    if self._ended(loop):
                        return
                    if not loop.is_running():
                        stalled = False  # a loop that is not running is not blocked
                        continue
                    self.checks += 1
                    if not stalled:
                        with self._lock:
                            age_s = self._clock() - self._last_beat
                            if age_s > self._threshold_s:
                                stalled = True
                                self._stalled_beat = self._last_beat  # the heartbeat records the gap that ends it
                                self._resume_gap_s = None
                        if not stalled:
                            continue
                        self.stall_count += 1
                        reported = False
                        frames = _innermost_frames(loop_thread_id, _STACK_DEPTH)
                        if self._ended(loop):
                            return  # shutdown began while the frames were read: they may show shutdown itself
                        reported = self._warnings.emit(
                            "BF-932: event loop blocked for %.0f ms (threshold %.0f ms); loop thread at: %s",
                            age_s * 1000.0,
                            self._threshold_s * 1000.0,
                            frames,
                        )
                        continue
                    with self._lock:
                        gap_s = self._resume_gap_s
                        if gap_s is None:
                            continue  # no heartbeat since the stall: the loop is still held
                        self._stalled_beat = self._resume_gap_s = None
                    stalled = False
                    self.resume_count += 1
                    if reported:
                        logger.info("BF-932: event loop resumed after %.0f ms (heartbeat gap)", gap_s * 1000.0)
                except Exception as error:
                    _drop(error)
        except Exception as error:  # the wait itself: the thread ends
            _drop(error)
