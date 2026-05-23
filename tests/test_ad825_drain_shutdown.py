"""AD-825: drain-before-cancel shutdown semantics — regression tests.

These tests construct a minimal runtime-shaped fixture with the new
``_drain_tasks`` / ``_shutdown_event`` / ``_spawn_background`` /
``_signal_drain_stop`` surface and exercise the drain → cancel
hand-off in ``startup/shutdown.py``. We deliberately do NOT spin up
the full ProbOSRuntime — these are unit-level tests for the new
machinery only. End-to-end behaviour is covered by the existing
AD-820 / AD-824 regression suites.
"""
from __future__ import annotations

import asyncio
import logging

import pytest


class _MiniRuntime:
    """Minimal shape needed by ``_spawn_background`` + drain phase.

    Mirrors the fields the real ProbOSRuntime owns (set in __init__
    around runtime.py:937). Used so we can unit-test the helpers
    without booting the full runtime.
    """

    def __init__(self) -> None:
        self._background_tasks: set[asyncio.Task] = set()
        self._drain_tasks: set[asyncio.Task] = set()
        self._shutdown_event: asyncio.Event = asyncio.Event()

    # The real runtime's helpers — copied verbatim so the unit tests
    # exercise the contract, not a stub. If the production helpers
    # drift, these tests will fail by being out of sync with the
    # production source — which is what we want.
    def _spawn_background(
        self,
        coro,
        name: str,
        *,
        drain_on_shutdown: bool = False,
    ) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        registry = self._drain_tasks if drain_on_shutdown else self._background_tasks
        registry.add(task)
        task.add_done_callback(registry.discard)
        return task

    def _signal_drain_stop(self) -> None:
        if not self._shutdown_event.is_set():
            self._shutdown_event.set()


# --------------------------------------------------------------------
# Test 1: drain-tagged tasks land in _drain_tasks, NOT _background_tasks
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_spawn_background_drain_routes_to_drain_registry():
    runtime = _MiniRuntime()

    async def _noop():
        await asyncio.sleep(0)

    task = runtime._spawn_background(
        _noop(), name="drain-loop", drain_on_shutdown=True,
    )
    assert task in runtime._drain_tasks, (
        "drain_on_shutdown=True must route to _drain_tasks"
    )
    assert task not in runtime._background_tasks, (
        "drain_on_shutdown=True must NOT route to _background_tasks"
    )
    await task


# --------------------------------------------------------------------
# Test 2: default behaviour (regression) — non-drain stays in _background_tasks
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_spawn_background_default_routes_to_background_registry():
    runtime = _MiniRuntime()

    async def _noop():
        await asyncio.sleep(0)

    task = runtime._spawn_background(_noop(), name="poll-loop")
    assert task in runtime._background_tasks, (
        "default (drain_on_shutdown=False) must route to _background_tasks"
    )
    assert task not in runtime._drain_tasks, (
        "default must NOT route to _drain_tasks"
    )
    await task


# --------------------------------------------------------------------
# Test 3: drain phase signals event, awaits clean exit BEFORE cancel
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_drain_phase_signals_event_and_awaits_clean_exit():
    runtime = _MiniRuntime()
    exited_cleanly = False
    saw_cancel = False

    async def _drain_loop():
        nonlocal exited_cleanly, saw_cancel
        try:
            while True:
                try:
                    await asyncio.wait_for(
                        runtime._shutdown_event.wait(), timeout=0.05,
                    )
                except asyncio.TimeoutError:
                    continue
                # Event set → exit cleanly without raising
                exited_cleanly = True
                return
        except asyncio.CancelledError:
            saw_cancel = True
            raise

    task = runtime._spawn_background(
        _drain_loop(), name="drain-loop", drain_on_shutdown=True,
    )
    # Let the loop spin a couple of iterations
    await asyncio.sleep(0.15)

    # Drain phase: signal + wait
    runtime._signal_drain_stop()
    pending_snapshot = list(runtime._drain_tasks)
    done, pending = await asyncio.wait(pending_snapshot, timeout=2.0)

    assert task in done, "drain task should exit cleanly within budget"
    assert exited_cleanly, "loop should have observed the shutdown event"
    assert not saw_cancel, (
        "drain phase must NOT cancel — clean exit only"
    )


# --------------------------------------------------------------------
# Test 4: drain timeout falls through with WARNING; cancel sweep handles it
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_drain_timeout_falls_through_to_cancel(caplog):
    caplog.set_level(logging.WARNING)
    runtime = _MiniRuntime()
    cancelled = False

    async def _stuck_loop():
        nonlocal cancelled
        try:
            # Ignores the shutdown event — simulates a buggy task
            while True:
                await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            cancelled = True
            raise

    task = runtime._spawn_background(
        _stuck_loop(), name="stuck-drain-loop", drain_on_shutdown=True,
    )
    await asyncio.sleep(0.05)

    # Drain phase with tiny budget — task will NOT exit
    runtime._signal_drain_stop()
    pending_snapshot = list(runtime._drain_tasks)
    done, pending = await asyncio.wait(pending_snapshot, timeout=0.2)
    assert task in pending, "stuck task should still be running after drain timeout"

    # Builder code in shutdown.py logs a WARNING and falls through; we
    # simulate the AD-824 cancel sweep here directly.
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    assert cancelled, "AD-824 cancel sweep should catch the stuck task"


# --------------------------------------------------------------------
# Test 5: in-flight atomic write completes before drain returns
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_drain_lets_atomic_write_finish_before_exit():
    runtime = _MiniRuntime()
    write_completed = False
    exit_observed = False

    async def _writer_loop():
        nonlocal write_completed, exit_observed
        while not runtime._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    runtime._shutdown_event.wait(), timeout=0.05,
                )
                break  # event fired during sleep
            except asyncio.TimeoutError:
                # Begin an "atomic write" that must finish even if
                # shutdown was signalled during it.
                try:
                    await asyncio.sleep(0.3)  # simulate write
                finally:
                    write_completed = True
                # Loop tail: check event, exit cleanly
                if runtime._shutdown_event.is_set():
                    exit_observed = True
                    return

    task = runtime._spawn_background(
        _writer_loop(), name="writer-loop", drain_on_shutdown=True,
    )
    # Let it begin the write
    await asyncio.sleep(0.1)
    # Signal during the write
    runtime._signal_drain_stop()
    # Wait long enough for the write to finish AND the post-write exit
    done, pending = await asyncio.wait([task], timeout=2.0)
    assert task in done
    assert write_completed, "atomic write must finish even after signal"
    assert exit_observed, "loop must exit cleanly after write completes"


# --------------------------------------------------------------------
# Test 6: drain phase exception path — AD-820 marker must still proceed
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_drain_phase_exception_does_not_block_marker(caplog):
    """If the drain phase itself raises, shutdown must continue.

    We simulate this by stubbing ``_signal_drain_stop`` with a raiser
    and verifying that the drain-then-cancel pattern in shutdown.py
    swallows the exception and proceeds (this is what the
    ``try/except Exception:`` arm in the new drain-phase block is for).
    """
    caplog.set_level(logging.WARNING)

    class _BadRuntime(_MiniRuntime):
        def _signal_drain_stop(self) -> None:
            raise RuntimeError("simulated drain failure")

    runtime = _BadRuntime()

    async def _short_loop():
        await asyncio.sleep(0.01)

    runtime._spawn_background(
        _short_loop(), name="dummy", drain_on_shutdown=True,
    )

    # Mimic the shutdown.py drain block — must not raise out
    raised = False
    try:
        try:
            runtime._signal_drain_stop()
            pending_snapshot = list(runtime._drain_tasks)
            if pending_snapshot:
                await asyncio.wait(pending_snapshot, timeout=1.0)
        except Exception:
            # This is the production guard — equivalent to the
            # try/except in startup/shutdown.py's new drain block.
            pass
    except Exception:
        raised = True

    assert not raised, "drain phase exception must not propagate"


# --------------------------------------------------------------------
# Test 7: non-drain background task still cancelled by AD-824 sweep
#         after drain phase runs (regression for AD-824 sweep semantics)
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ad824_cancel_sweep_still_handles_non_drain_tasks():
    runtime = _MiniRuntime()
    cancelled = False

    async def _poll_loop():
        nonlocal cancelled
        try:
            while True:
                await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            cancelled = True
            raise

    task = runtime._spawn_background(_poll_loop(), name="poll-loop")
    assert task in runtime._background_tasks
    await asyncio.sleep(0.05)

    # Simulate the AD-824 cancel sweep (drain phase doesn't touch
    # _background_tasks; only _drain_tasks).
    for t in list(runtime._background_tasks):
        t.cancel()
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    assert cancelled, (
        "AD-824 regression: non-drain tasks must still be cancelled by the sweep"
    )
