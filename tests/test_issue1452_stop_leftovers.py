"""BF-881 (#1452 item 5): a normal stop() releases what it used to leave behind.

Measured on origin/main before the fix: after a booted runtime is stopped at production
timing, five loops are still running (the AD-641a observability bridge, the AD-477
Captain's Log and Plan of the Day, the AD-485 DM archive loop, and the AD-733c-2
ship-level perception controller that the AD-733c-5 repoint orphaned), three SQLite
handles are still open (``crew_profiles.db``, ``service_profiles.db``,
``semantic_work.db``), and the standing-orders module globals keep the stopped runtime
alive through ``BilletRegistry._emit_event_fn``.

Every assertion below that says "nothing is left" is only trusted because
``test_the_detectors_report_each_planted_leak_and_go_silent_once_it_is_released`` plants
each leak and shows the detector sees it.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import sqlite3
import threading
import weakref
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import aiosqlite
import pytest

from probos.cognitive import standing_orders
from probos.config import CaptainsLogConfig, MemoryConfig
from probos.crew_profile import ProfileStore
from probos.knowledge.semantic_store import SemanticStore
from probos.naval import CaptainsLogService
from probos.service_profile import ServiceProfileStore
from tests.fixtures.runtime_factory import started_runtime
from tests.fixtures.runtime_lifecycle import (
    LifecycleBaseline,
    SqliteTracker,
    describe_task,
    lifecycle_config,
    nondaemon_threads_since,
    pending_tasks_since,
    threads_now,
)

_SHUTDOWN_LOGGER = "probos.startup.shutdown"

# Coroutine-name fragments of the five loops a stop() used to leave running. Matched on
# the coroutine, not the task name: three of the tasks are unnamed.
_LOOPS = {
    "observability bridge": "ObservabilityBridge._publish_loop",
    "captain's log": "CaptainsLogService._run_loop",
    "plan of the day": "PlanOfDayService._run_loop",
    "dm archive": "_dm_archive_loop",
}
_IDLE_WATCHDOG = "PerceptionModeController._run"


def _tasks_running(fragment: str) -> list[asyncio.Task[Any]]:
    return [
        task for task in asyncio.all_tasks()
        if not task.done()
        and getattr(task.get_coro(), "__qualname__", "").endswith(fragment)
    ]


def _held_start_service() -> Any:
    from probos.startup import shutdown as shutdown_module

    return shutdown_module._stop_held_start_service


async def _eventually(predicate: Any, *, timeout: float = 3.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return bool(predicate())


# ---------------------------------------------------------------------------
# The detectors discriminate
# ---------------------------------------------------------------------------

async def test_the_detectors_report_each_planted_leak_and_go_silent_once_it_is_released(
    tmp_path: Path,
) -> None:
    tasks_before = frozenset(asyncio.all_tasks())
    threads_before = threads_now()
    parked = threading.Event()
    with SqliteTracker() as tracker:
        planted_task = asyncio.create_task(asyncio.sleep(3600), name="planted-task")
        planted_thread = threading.Thread(target=parked.wait, name="planted-parked-thread")
        planted_thread.start()
        planted_connection = sqlite3.connect(str(tmp_path / "planted.db"))
        planted_aiosqlite = await aiosqlite.connect(str(tmp_path / "planted-aio.db"))
        try:
            assert [name.split(" ")[0] for name in await pending_tasks_since(tasks_before, settle_s=0.1)] == [
                "planted-task",
            ]
            reported_threads = nondaemon_threads_since(threads_before)
            assert "planted-parked-thread" in reported_threads
            assert len(reported_threads) == 2, reported_threads  # + the aiosqlite worker
            assert tracker.open_connections() == ["planted.db"]
            assert "planted.db" in tracker.opened_names()
        finally:
            planted_task.cancel()
            await asyncio.gather(planted_task, return_exceptions=True)
            parked.set()
            planted_thread.join(timeout=5)
            planted_connection.close()
            await planted_aiosqlite.close()

        assert await pending_tasks_since(tasks_before, settle_s=0.1) == []
        assert await _eventually(lambda: nondaemon_threads_since(threads_before) == [])
        assert tracker.open_connections() == []
        assert "planted.db" in tracker.opened_names()  # recorded, but no longer open


async def test_a_dropped_connection_is_gone_not_open(tmp_path: Path) -> None:
    with SqliteTracker() as tracker:
        connection = sqlite3.connect(str(tmp_path / "dropped.db"))
        assert tracker.open_connections() == ["dropped.db"]
        del connection
        gc.collect()
        assert tracker.open_connections() == []


async def test_the_tracker_ignores_connections_other_threads_open(tmp_path: Path) -> None:
    with SqliteTracker() as tracker:
        keep: list[sqlite3.Connection] = []

        def open_elsewhere() -> None:
            keep.append(sqlite3.connect(str(tmp_path / "elsewhere.db"), check_same_thread=False))

        worker = threading.Thread(target=open_elsewhere)
        worker.start()
        worker.join()
        assert len(keep) == 1
        assert tracker.open_connections() == []
        keep[0].close()


def test_lifecycle_config_turns_on_what_the_leftover_loops_need(tmp_path: Path) -> None:
    """Pydantic ignores an unknown field, so a misspelled one would silently turn nothing on."""
    config = lifecycle_config(tmp_path)

    assert config.observability_bridge.enabled is True
    assert config.naval_organization.captains_log.enabled is True
    assert config.naval_organization.plan_of_day.enabled is True
    assert config.ward_room.enabled is True
    assert config.perception.enabled is True
    assert config.perception.vision_consumer_enabled is True
    assert Path(config.archive.db_path).parent == tmp_path / "archive"
    assert config.memory == MemoryConfig()  # production timing unless asked otherwise
    quick = lifecycle_config(tmp_path, zero_grace=True)
    assert (quick.memory.shutdown_write_grace_s, quick.memory.shutdown_dispatch_grace_s) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# A real boot, stopped at production timing
# ---------------------------------------------------------------------------

def _count_closes(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    counts = {"ProfileStore": 0, "ServiceProfileStore": 0, "SemanticStore": 0}
    for store in (ProfileStore, ServiceProfileStore, SemanticStore):
        original = store.close

        def close(self: Any, _original: Any = original, _name: str = store.__name__) -> Any:
            counts[_name] += 1
            return _original(self)

        monkeypatch.setattr(store, "close", close)
    return counts


async def test_stop_leaves_no_lifecycle_task_thread_or_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)  # relative "data/..." config paths must not land in the checkout
    closes = _count_closes(monkeypatch)
    with SqliteTracker() as tracker:
        baseline = LifecycleBaseline.capture(tracker)
        async with started_runtime(tmp_path, config=lifecycle_config(tmp_path)) as runtime:
            # Premises: without them "nothing is left" would be true of a boot that never
            # started the loops or opened the stores.
            for name, fragment in _LOOPS.items():
                assert _tasks_running(fragment), f"{name} loop is not running before stop()"
            assert {"crew_profiles.db", "service_profiles.db", "semantic_work.db"} <= set(
                tracker.opened_names()
            )
            assert {"crew_profiles.db", "service_profiles.db", "semantic_work.db"} <= set(
                tracker.open_connections()
            )

            problems: list[str] = []
            registered = [
                task for task in runtime._background_tasks
                if getattr(task.get_coro(), "__qualname__", "").endswith(_LOOPS["dm archive"])
            ]
            if len(registered) != 1:
                problems.append(
                    f"the DM-archive task is not in runtime._background_tasks ({len(registered)} found)"
                )

            await runtime.stop()

            leftovers = await baseline.leftovers()
            for kind, items in leftovers.items():
                if items:
                    problems.append(f"{kind} left after stop(): {items}")
            for store, count in closes.items():
                if count != 1:
                    problems.append(f"{store}.close() ran {count} times during stop(), expected 1")
            assert not problems, "\n".join(problems)


async def test_stop_clears_the_standing_orders_globals_and_the_runtime_can_be_collected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    async with started_runtime(tmp_path, config=lifecycle_config(tmp_path)) as runtime:
        # Premises: the globals were this runtime's, so clearing them is what frees it.
        assert standing_orders._billet_registry is runtime.ontology.billet_registry
        assert standing_orders._step_router is not None
        assert standing_orders._task_context is not None

        await runtime.stop()

        assert standing_orders._billet_registry is None
        assert standing_orders._step_router is None
        assert standing_orders._task_context is None
        reference = weakref.ref(runtime)
    del runtime
    await asyncio.sleep(0.05)
    gc.collect()
    survivor = reference()
    if survivor is not None:
        referrers = [type(holder).__name__ for holder in gc.get_referrers(survivor)]
        pytest.fail(f"the stopped runtime is still reachable after gc.collect(); referrers: {referrers}")


async def test_stop_stops_the_ship_level_perception_controller_the_repoint_orphaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    async with started_runtime(tmp_path, config=lifecycle_config(tmp_path)) as runtime:
        registry = runtime.perception_engagement_registry
        assert registry is not None and len(registry) >= 1, "no per-agent controller: the repoint never happened"
        repointed = runtime.perception_mode_controller
        default = getattr(runtime, "perception_default_controller", None)
        assert default is not None, "the AD-733c-2 ship-level controller is not kept on the runtime"
        assert default is not repointed, "perception_mode_controller was not repointed"
        assert repointed in registry.all_controllers().values()
        # Both watchdogs, plus one per registered controller, are running.
        assert len(_tasks_running(_IDLE_WATCHDOG)) == len(registry) + 1

        await runtime.stop()

        assert await _eventually(lambda: not _tasks_running(_IDLE_WATCHDOG))
        assert runtime.perception_default_controller is None


# ---------------------------------------------------------------------------
# _stop_held_start_service
# ---------------------------------------------------------------------------

class _Service:
    """A start()/stop() service in the AD-641a / AD-477 shape."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self._loop_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.started = True
        self._loop_task = asyncio.create_task(self._run(), name="held-service-loop")

    async def _run(self) -> None:
        await asyncio.sleep(3600)

    async def stop(self) -> None:
        self.stopped = True
        if self._loop_task is not None:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)


def _runtime_with(service: Any, start_task: Any = None) -> SimpleNamespace:
    return SimpleNamespace(held_service=service, held_service_start_task=start_task)


async def _stop_held(runtime: Any, *, with_start_task: bool = True) -> None:
    await _held_start_service()(
        runtime,
        service_attr="held_service",
        start_task_attr="held_service_start_task" if with_start_task else None,
        label="test service",
    )


async def test_a_pending_start_task_is_cancelled_so_the_service_never_starts() -> None:
    service = _Service()
    runtime = _runtime_with(service, asyncio.create_task(service.start()))  # has not run yet

    await _stop_held(runtime)

    assert service.started is False
    assert service.stopped is True
    assert runtime.held_service is None and runtime.held_service_start_task is None


async def test_a_finished_start_task_is_not_cancelled_and_the_service_is_stopped() -> None:
    service = _Service()
    start_task = asyncio.create_task(service.start())
    await start_task
    runtime = _runtime_with(service, start_task)

    await _stop_held(runtime)

    assert service.started is True and service.stopped is True
    assert start_task.cancelled() is False
    assert runtime.held_service is None and runtime.held_service_start_task is None


async def test_a_stop_that_reraises_its_own_loops_cancellation_does_not_abort_shutdown() -> None:
    """AD-477's stop() cancels its loop and awaits it, so the loop's CancelledError
    propagates out of stop() by contract (naval/*.py is not changed)."""
    probe = CaptainsLogService(SimpleNamespace(), CaptainsLogConfig())
    await probe.start()
    with pytest.raises(asyncio.CancelledError):  # the premise: stop() really raises its own loop's
        await probe.stop()

    service = CaptainsLogService(SimpleNamespace(), CaptainsLogConfig())
    await service.start()
    assert len(_tasks_running("CaptainsLogService._run_loop")) == 1
    runtime = _runtime_with(service)

    await _stop_held(runtime, with_start_task=False)  # returns normally

    assert runtime.held_service is None
    assert not _tasks_running("CaptainsLogService._run_loop")


async def test_a_stop_run_from_an_already_cancelled_task_still_swallows_its_own_loops_cancellation() -> None:
    """BF-303: shutdown runs from a task the operator's Ctrl+C already cancelled, so that
    task's cancel count is above zero for the whole teardown. Only a cancellation that
    ARRIVES during the stop is an outer one; a count compared with zero would abort the
    teardown at the first AD-477 stop."""
    service = CaptainsLogService(SimpleNamespace(), CaptainsLogConfig())
    await service.start()
    runtime = _runtime_with(service)
    observed: dict[str, Any] = {}

    async def interrupted_then_tearing_down() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            current = asyncio.current_task()
            assert current is not None
            observed["cancelling_at_teardown"] = current.cancelling()
            await _stop_held(runtime, with_start_task=False)  # the `finally:` teardown
            observed["teardown_finished"] = True
            raise

    task = asyncio.create_task(interrupted_then_tearing_down())
    await asyncio.sleep(0)  # park it in its sleep
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert observed["cancelling_at_teardown"] == 1  # the premise: the ambient count is above zero
    assert observed.get("teardown_finished") is True
    assert not _tasks_running("CaptainsLogService._run_loop")


async def test_a_second_cancellation_during_a_teardown_that_was_already_cancelled_still_propagates() -> None:
    entered = asyncio.Event()

    class _Blocked:
        async def stop(self) -> None:
            entered.set()
            await asyncio.Event().wait()

    runtime = _runtime_with(_Blocked())
    outcome: dict[str, bool] = {}

    async def interrupted_then_tearing_down() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            try:
                await _stop_held(runtime, with_start_task=False)
            except asyncio.CancelledError:
                outcome["propagated"] = True
                raise
            outcome["propagated"] = False
            raise

    task = asyncio.create_task(interrupted_then_tearing_down())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.wait_for(entered.wait(), timeout=2)

    task.cancel()  # the second one, delivered while the teardown is running

    with pytest.raises(asyncio.CancelledError):
        await task
    assert outcome == {"propagated": True}


async def test_an_outer_cancellation_during_stop_still_propagates() -> None:
    entered = asyncio.Event()

    class _Blocked:
        async def stop(self) -> None:
            entered.set()
            await asyncio.Event().wait()

    runtime = _runtime_with(_Blocked())
    outer = asyncio.create_task(_stop_held(runtime, with_start_task=False))
    await asyncio.wait_for(entered.wait(), timeout=2)

    outer.cancel()

    with pytest.raises(asyncio.CancelledError):
        await outer
    assert runtime.held_service is None  # the reference is dropped either way


async def test_an_outer_cancellation_while_a_pending_start_task_unwinds_still_propagates() -> None:
    unwinding = asyncio.Event()

    async def slow_start() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            unwinding.set()
            await asyncio.sleep(0.2)  # slow cleanup, still cancelled when it ends
            raise

    service = _Service()
    start_task = asyncio.create_task(slow_start())
    await asyncio.sleep(0)  # let it begin, so the cancel is delivered into the body
    runtime = _runtime_with(service, start_task)
    outer = asyncio.create_task(_stop_held(runtime))
    await asyncio.wait_for(unwinding.wait(), timeout=2)

    outer.cancel()

    with pytest.raises(asyncio.CancelledError):
        await outer


async def test_a_magicmock_runtime_is_skipped_not_awaited() -> None:
    runtime = MagicMock()

    await _stop_held(runtime)

    runtime.held_service.stop.assert_not_called()


async def test_a_stop_that_raises_is_logged_and_shutdown_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Broken:
        async def stop(self) -> None:
            raise RuntimeError("disk gone")

    runtime = _runtime_with(_Broken())

    with caplog.at_level(logging.WARNING, logger=_SHUTDOWN_LOGGER):
        await _stop_held(runtime, with_start_task=False)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "test service" in warnings[0].getMessage()
    assert warnings[0].exc_info is not None
    assert runtime.held_service is None


async def test_a_runtime_without_the_service_is_left_alone() -> None:
    runtime = SimpleNamespace()

    await _stop_held(runtime)

    assert vars(runtime) == {}


async def test_describe_task_names_the_coroutine() -> None:
    task = asyncio.create_task(asyncio.sleep(3600), name="described")
    try:
        assert describe_task(task).startswith("described <")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
