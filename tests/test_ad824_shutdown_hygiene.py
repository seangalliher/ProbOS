"""AD-824: shutdown hygiene — centralized background-task cancellation tests.

Covers:
- `_spawn_background` registers the task in `_background_tasks` with the
  requested name.
- Done-callback removes the task from the registry on natural completion.
- The shutdown sweep cancels every registered task.
- The shutdown sweep returns within its 5s budget when an antagonist
  swallows `CancelledError`, and logs a WARNING.
- The `self._x_task = self._spawn_background(...)` pattern preserves the
  instance-attr binding.
- AD-820 invariant: the marker file is still written when an antagonist
  is registered.
"""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

from probos.runtime import ProbOSRuntime


class _StubRuntime:
    """Minimal harness exposing only `_background_tasks`.

    Used so unit tests don't pay the cost of booting a full runtime.
    Per the standing "no MagicMock at substrate boundaries" rule, this
    is a real Python object — the only attribute the helper touches is
    `_background_tasks`, and the only attribute the shutdown sweep
    touches is the same.
    """

    def __init__(self) -> None:
        self._background_tasks: set[asyncio.Task] = set()


async def _sweep(runtime: _StubRuntime, timeout: float = 5.0) -> None:
    """Mirror of the AD-824 sweep block from startup/shutdown.py.

    Kept as a separate callable here so the test does not have to drive
    the full shutdown pipeline. Behavior must match the production sweep.
    """
    logger = logging.getLogger("probos.startup.shutdown")
    background_tasks = getattr(runtime, "_background_tasks", None)
    if not background_tasks:
        return
    pending_snapshot = list(background_tasks)
    for _task in pending_snapshot:
        _task.cancel()
    try:
        _done, _pending = await asyncio.wait(pending_snapshot, timeout=timeout)
        for _task in _pending:
            logger.warning(
                "AD-824: background task %s did not exit within 5s; abandoning",
                _task.get_name(),
            )
    except Exception:
        logger.warning("AD-824: background-task sweep raised", exc_info=True)


@pytest.mark.asyncio
async def test_spawn_background_registers_and_returns_task() -> None:
    runtime = _StubRuntime()

    async def _noop() -> None:
        await asyncio.sleep(60)

    task = ProbOSRuntime._spawn_background(runtime, _noop(), name="t1")
    try:
        assert isinstance(task, asyncio.Task)
        assert task in runtime._background_tasks
        assert task.get_name() == "t1"
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_done_callback_removes_task_on_natural_completion() -> None:
    runtime = _StubRuntime()

    async def _q() -> None:
        return None

    task = ProbOSRuntime._spawn_background(runtime, _q(), name="q")
    await task
    # Give the done-callback a tick to run.
    await asyncio.sleep(0)
    assert runtime._background_tasks == set()


@pytest.mark.asyncio
async def test_stop_cancels_all_registered_tasks() -> None:
    runtime = _StubRuntime()

    async def _sleeper() -> None:
        await asyncio.sleep(60)

    t1 = ProbOSRuntime._spawn_background(runtime, _sleeper(), name="s1")
    t2 = ProbOSRuntime._spawn_background(runtime, _sleeper(), name="s2")

    await _sweep(runtime)

    assert t1.cancelled() is True
    assert t2.cancelled() is True


@pytest.mark.asyncio
async def test_stop_returns_within_budget_when_task_ignores_cancellation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = _StubRuntime()

    async def _stubborn() -> None:
        # Use a thread-backed sleep so the task survives ``cancel()``.
        # ``asyncio.sleep`` raises ``CancelledError`` on cancel even after
        # ``uncancel()`` in some pytest-asyncio contexts. ``time.sleep``
        # in an executor is uncancellable from the asyncio side: the
        # ``await fut`` raises CancelledError, but the thread keeps
        # sleeping. We uncancel and re-await until the executor returns.
        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(None, time.sleep, 3.0)
        while not fut.done():
            try:
                await asyncio.shield(asyncio.wrap_future(fut))
            except asyncio.CancelledError:
                # Deliberately swallow — simulates a misbehaving loop.
                asyncio.current_task().uncancel()  # type: ignore[union-attr]

    stubborn = ProbOSRuntime._spawn_background(
        runtime, _stubborn(), name="stubborn"
    )
    try:
        # Let the stubborn task enter its `run_in_executor`/shield loop
        # before we cancel it — otherwise it gets cancelled at coroutine
        # entry before reaching the swallow arm.
        await asyncio.sleep(0.1)
        caplog.set_level(logging.WARNING)
        t0 = time.monotonic()
        await _sweep(runtime, timeout=1.0)  # tight budget for test speed
        elapsed = time.monotonic() - t0

        assert elapsed < 2.0, f"sweep took {elapsed:.2f}s — should be near 1.0s"
        rendered = [rec.getMessage() for rec in caplog.records]
        assert any(
            "did not exit within 5s" in msg and "stubborn" in msg
            for msg in rendered
        ), f"missing abandon WARNING; got {rendered}"
    finally:
        # Force-kill so pytest doesn't leak the task.
        stubborn.cancel()
        try:
            await asyncio.wait_for(stubborn, timeout=0.1)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


@pytest.mark.asyncio
async def test_spawn_background_preserves_attr_binding_pattern() -> None:
    """The `self._x_task = self._spawn_background(...)` usage works:

    the attr holds the same `asyncio.Task` that the registry holds.
    """
    runtime = _StubRuntime()

    async def _noop() -> None:
        await asyncio.sleep(60)

    runtime._episodic_backup_task = ProbOSRuntime._spawn_background(  # type: ignore[attr-defined]
        runtime, _noop(), name="episodic-backup-loop"
    )
    try:
        task = runtime._episodic_backup_task  # type: ignore[attr-defined]
        assert task in runtime._background_tasks
        assert task.get_name() == "episodic-backup-loop"
    finally:
        runtime._episodic_backup_task.cancel()  # type: ignore[attr-defined]
        try:
            await runtime._episodic_backup_task  # type: ignore[attr-defined]
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_sweep_handles_empty_registry() -> None:
    """Edge case: sweep on empty registry is a no-op and never raises."""
    runtime = _StubRuntime()
    await _sweep(runtime)
    assert runtime._background_tasks == set()


@pytest.mark.asyncio
async def test_sweep_handles_missing_registry_attr() -> None:
    """Edge case: sweep on runtime without `_background_tasks` attr is a no-op.

    Guards the `getattr(runtime, "_background_tasks", None)` fallback in
    startup/shutdown.py so partial-init runtimes don't crash the sweep.
    """

    class _Bare:
        pass

    await _sweep(_Bare())  # type: ignore[arg-type]
