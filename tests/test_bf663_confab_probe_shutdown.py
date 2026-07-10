"""BF-663: confab probe tasks are reaped before LLM client shutdown."""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from probos.runtime import ProbOSRuntime
from probos.startup.shutdown import (
    _cancel_confab_probe_tasks,
    _close_llm_client_after_confab_probes,
    shutdown,
)


class _StrictLLM:
    def __init__(
        self, order: list[str], tasks: tuple[asyncio.Task[None], ...]
    ) -> None:
        self._order = order
        self._tasks = tasks

    async def close(self) -> None:
        assert all(task.done() for task in self._tasks)
        self._order.append("llm_close")


class _ProbeRuntime(SimpleNamespace):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            confab_probe_tasks=set(),
            _confab_probe_scheduling_open=True,
            **kwargs,
        )

    def schedule_confab_probe(
        self, probe_factory: Any, *, name: str = "confab-probe"
    ) -> asyncio.Task[Any] | None:
        return ProbOSRuntime.schedule_confab_probe(
            self, probe_factory, name=name
        )

    def close_confab_probe_scheduling(self) -> None:
        ProbOSRuntime.close_confab_probe_scheduling(self)


async def test_probe_cancelled_and_done_before_llm_close() -> None:
    order: list[str] = []
    entered = asyncio.Event()

    async def _slow_probe() -> None:
        try:
            entered.set()
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            order.append("probe_cancelled")
            raise
        finally:
            order.append("probe_done")

    task = asyncio.create_task(_slow_probe(), name="bf663-slow-probe")
    tasks = {task}
    runtime = _ProbeRuntime(llm_client=_StrictLLM(order, tuple(tasks)))
    runtime.confab_probe_tasks = tasks
    await entered.wait()

    runtime.close_confab_probe_scheduling()
    await _close_llm_client_after_confab_probes(runtime)

    assert order == ["probe_cancelled", "probe_done", "llm_close"]
    assert task.cancelled() is True
    assert tasks == set()


async def test_empty_or_missing_probe_registry_is_noop() -> None:
    empty_runtime = SimpleNamespace(confab_probe_tasks=set())
    missing_runtime = SimpleNamespace()

    await _cancel_confab_probe_tasks(empty_runtime)
    await _cancel_confab_probe_tasks(missing_runtime)

    assert empty_runtime.confab_probe_tasks == set()


async def test_finished_probe_is_awaited_and_cleared_without_recancel() -> None:
    async def _finished_probe() -> None:
        return None

    task = asyncio.create_task(_finished_probe(), name="bf663-finished-probe")
    await task
    runtime = SimpleNamespace(confab_probe_tasks={task})

    await _cancel_confab_probe_tasks(runtime)

    assert task.cancelled() is False
    assert task.cancelling() == 0
    assert runtime.confab_probe_tasks == set()


async def test_probe_exception_is_reaped_and_registry_cleared() -> None:
    async def _failed_probe() -> None:
        raise RuntimeError("probe cleanup failure")

    task = asyncio.create_task(_failed_probe(), name="bf663-failed-probe")
    await asyncio.sleep(0)
    runtime = SimpleNamespace(confab_probe_tasks={task})

    await _cancel_confab_probe_tasks(runtime)

    assert task.done() is True
    assert runtime.confab_probe_tasks == set()


async def test_outer_cancellation_does_not_second_cancel_async_child_cleanup() -> None:
    probe_entered = asyncio.Event()
    cleanup_entered = asyncio.Event()
    release_cleanup = asyncio.Event()
    cleanup_done = asyncio.Event()

    async def _slow_probe() -> None:
        try:
            probe_entered.set()
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup_entered.set()
            await release_cleanup.wait()
            cleanup_done.set()
            raise

    probe = asyncio.create_task(_slow_probe(), name="bf663-outer-cancel-probe")
    runtime = SimpleNamespace(confab_probe_tasks={probe})
    await probe_entered.wait()
    cleanup = asyncio.create_task(_cancel_confab_probe_tasks(runtime))
    await cleanup_entered.wait()

    cleanup.cancel()
    await asyncio.sleep(0)

    assert cleanup.done() is False
    assert probe.done() is False
    assert probe.cancelling() == 1
    assert cleanup_done.is_set() is False

    release_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await cleanup

    assert cleanup_done.is_set()
    assert probe.done() is True
    assert runtime.confab_probe_tasks == set()


async def test_scheduler_refusal_does_not_create_unawaited_coroutine() -> None:
    runtime = _ProbeRuntime()
    runtime.close_confab_probe_scheduling()
    created = False

    async def _probe() -> None:
        return None

    def _factory() -> Any:
        nonlocal created
        created = True
        return _probe()

    task = runtime.schedule_confab_probe(_factory)

    assert task is None
    assert created is False
    assert runtime.confab_probe_tasks == set()


async def test_scheduler_closes_factory_coroutine_when_task_creation_fails(
    monkeypatch,
) -> None:
    runtime = _ProbeRuntime()
    probe_coro = asyncio.sleep(0)
    monkeypatch.setattr(
        asyncio,
        "create_task",
        lambda coro, *, name=None: (_ for _ in ()).throw(RuntimeError("no loop")),
    )

    try:
        runtime.schedule_confab_probe(lambda: probe_coro)
    except RuntimeError:
        pass

    assert inspect.getcoroutinestate(probe_coro) == inspect.CORO_CLOSED
    assert runtime.confab_probe_tasks == set()


async def test_production_shutdown_entry_refuses_late_probe_before_first_await(
    tmp_path,
) -> None:
    order: list[str] = []
    first_await_reached = asyncio.Event()
    release_first_await = asyncio.Event()
    first_await_returned = asyncio.Event()
    late_probe_started = False

    class _Registry:
        def all(self) -> list[Any]:
            return []

    class _EventLog:
        async def log(self, *, category: str, event: str) -> None:
            first_await_reached.set()
            await release_first_await.wait()
            first_await_returned.set()

    runtime = _ProbeRuntime(
        _shutdown_started=False,
        _started=True,
        _session_id="bf663-production-seam",
        _start_time_wall=0.0,
        _start_time=0.0,
        _data_dir=tmp_path,
        registry=_Registry(),
        ontology=None,
        event_log=_EventLog(),
        ward_room=None,
    )

    async def _late_probe() -> None:
        nonlocal late_probe_started
        late_probe_started = True

    shutdown_task = asyncio.create_task(shutdown(runtime, reason="bf663-race"))
    await first_await_reached.wait()

    late_task = runtime.schedule_confab_probe(_late_probe, name="late-probe")

    assert late_task is None
    assert late_probe_started is False
    assert runtime.confab_probe_tasks == set()

    release_first_await.set()
    await first_await_returned.wait()
    await asyncio.sleep(0)
    shutdown_task.cancel()
    try:
        await shutdown_task
    except asyncio.CancelledError:
        pass


async def test_production_shutdown_missing_close_contract_fails() -> None:
    runtime = SimpleNamespace(_shutdown_started=False)

    with pytest.raises(AttributeError, match="close_confab_probe_scheduling"):
        await shutdown(runtime)

    assert runtime._shutdown_started is True


async def test_cleanup_start_blocks_late_registration_before_llm_close() -> None:
    order: list[str] = []
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    late_probe_started = False

    async def _active_probe() -> None:
        try:
            cleanup_started.set()
            await asyncio.Event().wait()
        finally:
            await release_cleanup.wait()
            order.append("active_probe_done")

    runtime = _ProbeRuntime()
    active = runtime.schedule_confab_probe(_active_probe, name="active-probe")
    assert active is not None
    runtime.llm_client = _StrictLLM(order, (active,))
    await cleanup_started.wait()

    runtime.close_confab_probe_scheduling()
    close_task = asyncio.create_task(
        _close_llm_client_after_confab_probes(runtime)
    )
    while active.cancelling() == 0:
        await asyncio.sleep(0)

    async def _late_probe() -> None:
        nonlocal late_probe_started
        late_probe_started = True

    late = runtime.schedule_confab_probe(_late_probe, name="late-probe")
    release_cleanup.set()
    await close_task

    assert late is None
    assert late_probe_started is False
    assert order == ["active_probe_done", "llm_close"]
    assert runtime.confab_probe_tasks == set()
