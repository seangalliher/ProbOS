"""BF-932 (#1670) D2: the loop-stall sampler names the code that holds the event loop.

The stalls are real. The loop's own thread blocks until the sampler has reported it: a logging handler on the
sampler's logger sets a ``threading.Event`` when the WARNING names the blocking function, so a stall lasts exactly
until it is detected. Where a test needs exact ages and gaps, a ``_Clock`` the test moves replaces the monotonic clock,
so a slow host cannot change them. A guard timeout fails a hung test; no assertion bounds a duration. Every heartbeat
task a test starts ends inside that test, on success and on failure. tests/conftest.py makes the sampler a no-op for
every other test; each test here that runs it requests ``bf932_live_loop_stall_sampler``.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import threading
import time
import traceback
import weakref
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.config import SystemConfig, SystemInfo
from probos.runtime import ProbOSRuntime
from probos.utils import loop_stall
from probos.utils.loop_stall import THREAD_NAME, LoopStallSampler

_LOGGER = "probos.utils.loop_stall"
_BLOCKED = "BF-932: event loop blocked"
_RESUMED = "BF-932: event loop resumed"
_TASK_NAME = "bf932-loop-stall-sampler"
_GUARD_S = 30.0
_HELD_S = 10.0  # how long an observer waits for the stop event; well under _GUARD_S, the held handler's own limit


@pytest.fixture
def bf932_live_loop_stall_sampler() -> None:
    """Asks tests/conftest.py's _bf932_quiet_loop_stall_sampler to leave the real sampler in place."""
    return None


class _Signals(logging.Handler):
    """The sampler's lines as written; sets ``blocked`` for a WARNING naming ``marker`` and ``resumed`` for an INFO.

    With a ``gate``, the thread that writes the WARNING naming ``marker`` is held inside this handler until the gate is
    set: a slow handler, which holds its lock while it is held. The level is INFO, and a test that holds it sets the
    logger to INFO, so the loop thread's DEBUG lines do not reach it there; the verbose-configuration test lowers both
    to DEBUG, where a log call from the loop thread that reaches this handler waits for that lock.
    """

    def __init__(self, marker: str, gate: threading.Event | None = None) -> None:
        super().__init__(level=logging.INFO)
        self.marker = marker
        self.gate = gate
        self.gate_expired = False
        self.blocked = threading.Event()
        self.resumed = threading.Event()
        self.lines: list[tuple[int, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        self.lines.append((record.levelno, message))
        if record.levelno == logging.WARNING and message.startswith(_BLOCKED) and self.marker in message:
            self.blocked.set()
            if self.gate is not None:
                if not self.gate.wait(_GUARD_S):
                    self.gate_expired = True
        elif record.levelno == logging.INFO and message.startswith(_RESUMED):
            self.resumed.set()


class _Clock:
    """A clock the test moves. ``stamped`` lists the values read on the loop's own thread: the heartbeat's stamps."""

    def __init__(self, now: float) -> None:
        self.now = now
        self.loop_thread = threading.get_ident()
        self.stamped: list[float] = []

    def __call__(self) -> float:
        value = self.now
        if threading.get_ident() == self.loop_thread:
            self.stamped.append(value)
        return value


class _NoStack:
    """Stands in for ``traceback.StackSummary``: reading the stack fails."""

    @staticmethod
    def extract(*args: object, **kwargs: object) -> object:
        raise RuntimeError("bf932 test: the stack could not be read")


class _FailingWait(threading.Event):
    """An Event whose wait raises, as ``Event.wait`` does for a timeout past ``threading.TIMEOUT_MAX``."""

    def wait(self, timeout: float | None = None) -> bool:
        raise OverflowError("bf932 test: timeout out of range")


class _Witness:
    """A local of the loop thread's blocked frame: alive while anything keeps that frame."""


def _dropped(caplog: pytest.LogCaptureFixture) -> bool:
    return any(
        r.name == _LOGGER and "a loop-stall check failed and was dropped" in r.getMessage() for r in caplog.records
    )


def _samplers(before: set[threading.Thread]) -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t not in before and t.name == THREAD_NAME and t.is_alive()]


async def _until(predicate: Callable[[], bool]) -> None:
    """Yield to the loop until ``predicate`` holds; the guard fails a test that never gets there."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _GUARD_S
    while not predicate():
        assert loop.time() < deadline, "guard: the awaited condition never held"
        await asyncio.sleep(0.01)


def _hold_the_loop_until(event: threading.Event) -> None:
    """Blocks the event loop's own thread until the sampler reports it; the WARNING must name this function."""
    assert event.wait(_GUARD_S), "guard: the sampler never reported the blocked loop"


def _hold_the_loop_while(predicate: Callable[[], bool]) -> None:
    """Blocks the event loop's own thread while ``predicate`` holds; ``time.sleep`` lets the sampler's thread run."""
    deadline = time.monotonic() + _GUARD_S
    while predicate():
        assert time.monotonic() < deadline, "guard: the sampler never counted the stall"
        time.sleep(0.005)


def _stall_the_loop(clock: _Clock, reported: threading.Event) -> None:
    """Moves the clock 0.5 past the last heartbeat (100.0) and holds the loop's own thread until the WARNING names this
    function; the loop then resumes with the clock at 101.25, which its first heartbeat after the stall reads."""
    clock.now = 100.5
    assert reported.wait(_GUARD_S), "guard: the sampler never reported the stall"
    clock.now = 101.25


def _hold_the_loop_with_a_witness_until(dropped: Callable[[], bool]) -> weakref.ref[_Witness]:
    """Blocks the loop's own thread, with a local its frame refers to, until the sampler has dropped a failed check."""
    witness = _Witness()
    deadline = time.monotonic() + _GUARD_S
    while not dropped():
        assert time.monotonic() < deadline, "guard: the sampler never dropped a check"
        time.sleep(0.005)
    return weakref.ref(witness)


async def _turn(clock: _Clock, until: float) -> None:
    """Turns the loop, moving the clock 0.01 a turn. The clock moves only while the loop turns, so a paused host cannot
    age the stamp, and a heartbeat that stops stamping falls 0.01 further behind each turn."""
    while clock.now < until:
        clock.now = round(clock.now + 0.01, 2)
        await asyncio.sleep(0.01)


async def _stop(task: asyncio.Task[None]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_d2_a_blocked_loop_gets_one_warning_naming_the_blocker_then_a_resume_line(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    signals = _Signals(_hold_the_loop_until.__name__)
    sampler_logger = logging.getLogger(_LOGGER)
    sampler_logger.addHandler(signals)
    before = set(threading.enumerate())
    task = asyncio.create_task(LoopStallSampler(threshold_s=0.2).run())
    try:
        await _until(lambda: bool(_samplers(before)))
        _hold_the_loop_until(signals.blocked)
        await _until(signals.resumed.is_set)
    finally:
        sampler_logger.removeHandler(signals)
        await _stop(task)
    named = [m for level, m in signals.lines if level == logging.WARNING and _hold_the_loop_until.__name__ in m]
    assert len(named) == 1  # one WARNING for the one stall
    assert "tests/test_bf932_d2_loop_stall_sampler.py:" in named[0]  # dir/file:line of the blocking frame
    assert "<threading.Event" not in named[0]  # no arguments and no locals
    assert any(level == logging.INFO and m.startswith(_RESUMED) for level, m in signals.lines)


@pytest.mark.asyncio
async def test_d2_a_loop_that_keeps_turning_gets_no_line(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    clock = _Clock(100.0)
    sampler = LoopStallSampler(threshold_s=0.2, clock=clock)
    task = asyncio.create_task(sampler.run())
    try:
        await _turn(clock, 101.0)  # 100 turns: without heartbeats the stamp would be 1.0 old, five thresholds
        await _until(lambda: sampler.checks >= 10)
    finally:
        await _stop(task)
    assert [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.INFO] == []
    assert sampler.stall_count == 0
    assert len(set(clock.stamped)) >= 5  # the heartbeat stamped the moving clock


@pytest.mark.asyncio
@pytest.mark.parametrize(("threshold_s", "expected"), [(1.0, 1), (0.0, 0)])
async def test_d2_the_runtime_starts_one_sampler_by_default_and_none_at_0(
    bf932_live_loop_stall_sampler: None, tmp_path, threshold_s: float, expected: int,
) -> None:
    before = set(threading.enumerate())
    rt = ProbOSRuntime(
        config=SystemConfig(system=SystemInfo(loop_stall_warn_seconds=threshold_s)),
        data_dir=tmp_path,
        episodic_memory=MockEpisodicMemory(relevance_threshold=0.3),
    )
    await rt.start()
    try:
        assert [t.get_name() for t in rt._background_tasks].count(_TASK_NAME) == expected
        if expected:
            await _until(lambda: len(_samplers(before)) == 1)
    finally:
        await rt.stop()
    assert _samplers(before) == []  # the stop's AD-824 sweep cancelled the heartbeat, which joined the thread


@pytest.mark.asyncio
async def test_d2_a_second_run_starts_no_second_thread_and_a_cancel_ends_the_one(
    bf932_live_loop_stall_sampler: None,
) -> None:
    before = set(threading.enumerate())
    sampler = LoopStallSampler(threshold_s=0.2, clock=lambda: 100.0)
    first = asyncio.create_task(sampler.run())
    try:
        await _until(lambda: len(_samplers(before)) == 1)
        await asyncio.wait_for(sampler.run(), _GUARD_S)  # returns at once: the first run's thread is alive
        threads = _samplers(before)
        assert len(threads) == 1 and threads[0].daemon is True
    finally:
        await _stop(first)
    assert not threads[0].is_alive()


def test_d2_a_closed_loop_ends_the_thread(bf932_live_loop_stall_sampler: None) -> None:
    before = set(threading.enumerate())
    sampler = LoopStallSampler(threshold_s=0.2, clock=lambda: 100.0)
    held: list[asyncio.Task[None]] = []  # keeps the heartbeat task alive, so only the closed loop can end the thread
    threads: list[threading.Thread] = []
    destroyed: list[str] = []
    loop = asyncio.new_event_loop()
    # The heartbeat task is still pending when the loop closes. It is destroyed inside this test (gc.collect below),
    # on success and on failure; asyncio's report of it goes to this loop's handler, not to a log another test reads.
    loop.set_exception_handler(lambda _loop, context: destroyed.append(str(context.get("message"))))
    try:

        async def _start() -> None:
            held.append(asyncio.get_running_loop().create_task(sampler.run()))
            await _until(lambda: bool(_samplers(before)))
            threads.extend(_samplers(before))

        loop.run_until_complete(_start())
    finally:
        loop.close()
        for thread in threads:
            thread.join(_GUARD_S)  # guard
        ended = [not thread.is_alive() for thread in threads]
        held.clear()
        gc.collect()
    assert ended == [True]
    assert destroyed == ["Task was destroyed but it is pending!"]


@pytest.mark.asyncio
async def test_d2_warnings_are_bounded_and_a_refused_stall_writes_no_resume_line(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    before = set(threading.enumerate())
    sampler = LoopStallSampler(threshold_s=0.2, max_warnings=2, window_s=3600.0)
    task = asyncio.create_task(sampler.run())
    try:
        await _until(lambda: bool(_samplers(before)))
        for n in (1, 2, 3):
            _hold_the_loop_while(lambda: sampler.stall_count < n)
            await _until(lambda: sampler.resume_count >= n)
    finally:
        await _stop(task)
    lines = [r for r in caplog.records if r.name == _LOGGER]
    assert sampler.stall_count >= 3
    assert len([r for r in lines if r.levelno == logging.WARNING]) == 2
    assert len([r for r in lines if r.levelno == logging.INFO and r.getMessage().startswith(_RESUMED)]) == 2


@pytest.mark.parametrize("value", [0.0, 0.1, 1.0, 60.0])
def test_d2_the_threshold_accepts_0_or_a_value_from_a_tenth_to_60(value: float) -> None:
    assert SystemInfo(loop_stall_warn_seconds=value).loop_stall_warn_seconds == value


@pytest.mark.parametrize("value", [0.05, -1.0, 60.5, float("inf"), float("nan")])
def test_d2_the_threshold_refuses_anything_else(value: float) -> None:
    with pytest.raises(ValidationError):
        SystemInfo(loop_stall_warn_seconds=value)


def test_d2_the_sampler_is_on_by_default() -> None:
    assert SystemConfig().system.loop_stall_warn_seconds == 1.0


@pytest.mark.asyncio
async def test_d2_the_resume_line_carries_the_first_heartbeat_gap_however_late_the_thread_reads_it(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    clock = _Clock(100.0)
    release = threading.Event()  # holds the thread inside the WARNING's handler, so its next check comes late
    signals = _Signals(_stall_the_loop.__name__, gate=release)
    sampler_logger = logging.getLogger(_LOGGER)
    sampler_logger.addHandler(signals)
    sampler = LoopStallSampler(threshold_s=0.2, clock=clock)
    task = asyncio.create_task(sampler.run())
    try:
        await _until(lambda: sampler.checks >= 2)
        _stall_the_loop(clock, signals.blocked)
        await _until(lambda: 101.25 in clock.stamped)  # the first heartbeat after the stall: a gap of 1.25
        clock.now = 109.0
        await _until(lambda: 109.0 in clock.stamped)  # a later heartbeat, before the thread's next check
        release.set()
        await _until(signals.resumed.is_set)
    finally:
        release.set()
        sampler_logger.removeHandler(signals)
        await _stop(task)
    warnings = [m for level, m in signals.lines if level == logging.WARNING]
    assert len(warnings) == 1 and _stall_the_loop.__name__ in warnings[0]
    assert warnings[0].startswith("BF-932: event loop blocked for 500 ms (threshold 200 ms); loop thread at: ")
    assert [m for level, m in signals.lines if level == logging.INFO] == [
        "BF-932: event loop resumed after 1250 ms (heartbeat gap)"
    ]


@pytest.mark.asyncio
async def test_d2_no_warning_is_written_once_shutdown_begins_while_the_frames_are_read(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    state = {"active": True}

    def _shutdown_begins_while_reading(thread_id: int, depth: int) -> str:
        state["active"] = False  # as shutdown() setting _shutdown_started while the thread reads the frames
        return "(frames read as shutdown began)"

    monkeypatch.setattr(loop_stall, "_innermost_frames", _shutdown_begins_while_reading)
    before = set(threading.enumerate())
    sampler = LoopStallSampler(threshold_s=0.2, active=lambda: state["active"])
    task = asyncio.create_task(sampler.run())
    try:
        await _until(lambda: bool(_samplers(before)))
        _hold_the_loop_while(lambda: state["active"])
        await _until(lambda: _samplers(before) == [])  # the thread ended: inactive
    finally:
        await _stop(task)
    assert sampler.stall_count == 1
    assert [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.INFO] == []


@pytest.mark.asyncio
async def test_d2_a_thread_held_in_a_logging_call_at_cancel_ends_when_the_call_returns_and_writes_nothing_more(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    release = threading.Event()
    signals = _Signals(_hold_the_loop_until.__name__, gate=release)
    sampler_logger = logging.getLogger(_LOGGER)
    sampler_logger.addHandler(signals)
    before = set(threading.enumerate())
    task = asyncio.create_task(LoopStallSampler(threshold_s=0.2).run())
    try:
        await _until(lambda: bool(_samplers(before)))
        threads = _samplers(before)
        _hold_the_loop_until(signals.blocked)  # the thread is now inside the WARNING's handler, held by the gate
        await _stop(task)  # sets the stop event; the join gives up after _JOIN_TIMEOUT_S
        held_at_cancel = threads[0].is_alive()
    finally:
        release.set()
        sampler_logger.removeHandler(signals)
        await _stop(task)
    threads[0].join(_GUARD_S)  # guard
    assert held_at_cancel is True  # the timed join returned while the thread was inside the handler
    assert not threads[0].is_alive()  # it ended when the handler returned
    lines = [r for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.INFO]
    assert lines and lines[-1].levelno == logging.WARNING  # nothing after the held WARNING
    assert _hold_the_loop_until.__name__ in lines[-1].getMessage()


@pytest.mark.asyncio
async def test_d2_a_cancel_sets_the_stop_event_while_a_debug_level_handler_is_held_by_the_warning(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)  # the verbose configuration: DEBUG records reach the handlers
    release = threading.Event()
    signals = _Signals(_hold_the_loop_until.__name__, gate=release)
    signals.setLevel(logging.DEBUG)  # a DEBUG line from the loop thread would wait for this handler's lock
    sampler_logger = logging.getLogger(_LOGGER)
    sampler_logger.addHandler(signals)
    sampler = LoopStallSampler(threshold_s=0.2)
    stop_set_while_held: list[bool] = []

    def _observe_the_stop_event() -> None:
        # Off the loop. The handler stays held until this thread has its answer, so True means the stop event was set
        # while the WARNING's handler still held its lock.
        stop_set_while_held.append(sampler._stop.wait(_HELD_S))
        release.set()

    observer = threading.Thread(target=_observe_the_stop_event, name="bf932-test-stop-observer", daemon=True)
    before = set(threading.enumerate())
    threads: list[threading.Thread] = []
    task = asyncio.create_task(sampler.run())
    try:
        await _until(lambda: bool(_samplers(before)))
        threads = _samplers(before)
        _hold_the_loop_until(signals.blocked)  # the thread is now inside the WARNING's handler, holding its lock
        observer.start()
        await _stop(task)  # the cancellation must set the stop event without waiting for that lock
    finally:
        release.set()
        sampler_logger.removeHandler(signals)
        await _stop(task)
        if observer.is_alive():
            observer.join(_GUARD_S)  # guard
        for thread in threads:
            thread.join(_GUARD_S)  # guard
    assert not signals.gate_expired, "guard: the held handler's gate expired; the hold did not cover the cancellation"
    assert stop_set_while_held == [True]
    assert not observer.is_alive() and not any(thread.is_alive() for thread in threads)


@pytest.mark.asyncio
async def test_d2_a_stall_whose_warning_failed_gets_no_resume_line(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    real = loop_stall._innermost_frames
    reads: list[int] = []

    def _every_read_after_the_first_fails(thread_id: int, depth: int) -> str:
        reads.append(thread_id)
        if len(reads) >= 2:
            raise RuntimeError("bf932 test: the stack could not be read")
        return real(thread_id, depth)

    monkeypatch.setattr(loop_stall, "_innermost_frames", _every_read_after_the_first_fails)
    before = set(threading.enumerate())
    sampler = LoopStallSampler(threshold_s=0.2)
    task = asyncio.create_task(sampler.run())
    try:
        await _until(lambda: bool(_samplers(before)))
        for n in (1, 2):
            _hold_the_loop_while(lambda: sampler.stall_count < n)
            await _until(lambda: sampler.resume_count >= n)
    finally:
        await _stop(task)
    lines = [r for r in caplog.records if r.name == _LOGGER]
    assert len([r for r in lines if r.levelno == logging.WARNING]) == 1  # only the first read succeeded
    assert len([r for r in lines if r.levelno == logging.INFO and r.getMessage().startswith(_RESUMED)]) == 1


@pytest.mark.asyncio
async def test_d2_a_failed_stack_read_keeps_no_frame_of_the_loop_alive(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)  # caplog keeps every record, as a buffering handler would
    monkeypatch.setattr(
        loop_stall, "traceback", SimpleNamespace(walk_stack=traceback.walk_stack, StackSummary=_NoStack),
    )
    before = set(threading.enumerate())
    task = asyncio.create_task(LoopStallSampler(threshold_s=0.2).run())
    try:
        await _until(lambda: bool(_samplers(before)))
        witness = _hold_the_loop_with_a_witness_until(lambda: _dropped(caplog))
    finally:
        await _stop(task)  # the thread is told to stop and joined, so none of its frames is running
    gc.collect()
    assert witness() is None  # the dropped record keeps no frame of the loop thread
    assert [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.INFO] == []


@pytest.mark.parametrize("threshold_s", [float("inf"), float("nan"), 1e300])
def test_d2_the_sampler_refuses_a_threshold_its_wait_cannot_take(threshold_s: float) -> None:
    with pytest.raises(ValueError):
        LoopStallSampler(threshold_s=threshold_s)


@pytest.mark.asyncio
async def test_d2_a_failing_wait_ends_the_thread_at_debug_and_nothing_escapes(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    monkeypatch.setattr(
        loop_stall,
        "threading",
        SimpleNamespace(
            Event=_FailingWait, Lock=threading.Lock, Thread=threading.Thread, get_ident=threading.get_ident,
            TIMEOUT_MAX=threading.TIMEOUT_MAX,
        ),
    )
    escaped: list[object] = []
    previous_hook = threading.excepthook
    threading.excepthook = escaped.append  # an exception that leaves the thread lands here
    before = set(threading.enumerate())
    task = asyncio.create_task(LoopStallSampler(threshold_s=0.2).run())
    try:
        await _until(lambda: bool(escaped) or _dropped(caplog))
    finally:
        threading.excepthook = previous_hook
        await _stop(task)
    assert escaped == []
    assert _samplers(before) == []
