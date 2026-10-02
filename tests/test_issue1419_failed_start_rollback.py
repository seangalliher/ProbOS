"""BF-882 (#1419 G-2): a start() that fails, or is cancelled, rolls back everything it started.

Measured on origin/main before the fix: ``start()`` has no unwind and ``stop()`` returns at
``if not runtime._started`` after writing the session record, so a failed start releases
nothing. Every failure phase left 4-31 non-daemon aiosqlite workers (the interpreter then
cannot exit: 13 of 15 failed-start children hung), ``YeomanAgent._live_instance_count``
stayed at 1 from the cognitive phase on (the next boot in the process raised the AD-766
singleton error), and a failure at the ``started`` event-log row left ``_started`` True,
so a retried ``start()`` returned in 0.000 s without booting and a later ``stop()`` wrote
``shutdown_status.json``.

The rollback reuses ``shutdown()``'s production teardown order with ``rollback=True``. It
writes no marker and persists no session state; everything else, both waits, the AD-1278
flush and drain, the event-log rows and slice A's releases included, still runs. Three
properties were added after review of the first version: every step is best-effort (one that
raises is logged by name and the rollback goes on, so one broken component cannot leave
the rest open), the session record is only refreshed when one exists and never created
(``cognitive_services`` reads ANY record as a stasis recovery, so a record written by a boot
that never completed turned the next boot of a maiden voyage into one), and the
standing-orders globals are cleared after the pools stop and the IntentBus drains, not
before an admitted dispatch has finished composing its prompt.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import json
import logging
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import probos
from probos.agent_onboarding import AgentOnboardingService
from probos.cognitive import standing_orders
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.yeoman import YeomanAgent
from probos.config import MemoryConfig, SystemConfig
from probos.execution.long_runs import LongRunService
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.runtime import ProbOSRuntime
from probos.startup import shutdown as shutdown_module
from probos.types import IntentMessage
from tests.fixtures.runtime_factory import make_runtime
from tests.fixtures.runtime_lifecycle import (
    NOTHING_LEFT,
    START_FAILURE_PHASES,
    BareRuntime,
    BrokenStop,
    InjectedStartFailure,
    LifecycleBaseline,
    RecordedEventLog,
    RecordedService,
    SqliteTracker,
    break_stop,
    inject_start_failure,
    lifecycle_config,
)

_ROLLBACK_LOGGER = "probos.startup.rollback"
_SHUTDOWN_LOGGER = "probos.startup.shutdown"
_START_FAILED = "BF-882: start() already failed and was rolled back; construct a new ProbOSRuntime"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_CHILD = _REPO_ROOT / "tests" / "fixtures" / "failed_start_child.py"


@pytest.fixture(autouse=True)
def _restore_the_yeoman_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    """A start that is not rolled back leaves the class-level counter at 1, which would
    fail every later boot in this worker with the AD-766 error."""
    monkeypatch.setattr(YeomanAgent, "_live_instance_count", YeomanAgent._live_instance_count)


@pytest.fixture
def tracker() -> Iterator[SqliteTracker]:
    with SqliteTracker() as installed:  # before any runtime is built: ProfileStore opens in __init__
        yield installed


# ---------------------------------------------------------------------------
# start() keeps its body and its identity
# ---------------------------------------------------------------------------

def test_start_is_wrapped_but_its_body_and_identity_are_unchanged() -> None:
    start = ProbOSRuntime.start

    assert getattr(start, "__wrapped__", None) is not None
    assert start.__wrapped__ is not start
    assert start.__name__ == "start"
    assert start.__qualname__ == "ProbOSRuntime.start"
    assert start.__doc__ == start.__wrapped__.__doc__ and start.__doc__
    assert inspect.iscoroutinefunction(start)
    assert inspect.iscoroutinefunction(start.__wrapped__)
    assert list(inspect.signature(start).parameters) == ["self"]
    source = inspect.getsource(ProbOSRuntime.start)
    assert source.lstrip().startswith("@rollback_on_failed_start")
    assert "async def start(self) -> None:" in source
    assert "self._startup_complete = True" in source  # the AD-828b last statement of the body


def test_stop_is_unchanged() -> None:
    assert list(inspect.signature(ProbOSRuntime.stop).parameters) == ["self", "reason"]
    source = inspect.getsource(ProbOSRuntime.stop)
    assert "await shutdown(self, reason)" in source
    assert "rollback" not in source


def test_runtime_init_defaults_start_failed_false(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    try:
        assert runtime._start_failed is False
    finally:
        runtime.profile_store.close()  # opened in __init__; nothing else was started


# ---------------------------------------------------------------------------
# rollback_on_failed_start / rollback_failed_start
# ---------------------------------------------------------------------------

class _Recorder:
    """Stands in for ``shutdown()``: records how and where it was called."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.release: asyncio.Event | None = None
        self.began = asyncio.Event()
        self.finished = asyncio.Event()
        self.raises: BaseException | None = None

    async def __call__(self, runtime: Any, reason: str = "", *, rollback: bool = False) -> None:
        task = asyncio.current_task()
        assert task is not None
        self.calls.append({
            "runtime": runtime, "reason": reason, "rollback": rollback,
            "task_name": task.get_name(), "task": task,
            "cancelling": task.cancelling(), "start_failed": runtime._start_failed,
        })
        self.began.set()
        if self.release is not None:
            await self.release.wait()
        if self.raises is not None:
            raise self.raises
        self.finished.set()


def _rollback_module() -> Any:
    """Imported when used, so the cases that name it fail one by one, not at collection."""
    return importlib.import_module("probos.startup.rollback")


def _subject(body: Any) -> Any:
    """A runtime-shaped object whose start() is wrapped exactly as ProbOSRuntime.start is."""
    class Subject:
        def __init__(self) -> None:
            self._start_failed = False
            self._started = True  # a failed start can leave it True (finalize sets it early)
            self.body_runs = 0

        @_rollback_module().rollback_on_failed_start
        async def start(self) -> None:
            self.body_runs += 1
            await body(self)

    return Subject()


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    shutdown_recorder = _Recorder()
    monkeypatch.setattr(shutdown_module, "shutdown", shutdown_recorder)
    return shutdown_recorder


async def _raise_injected(subject: Any) -> None:
    raise InjectedStartFailure("INJECTED in the wrapper test")


async def test_a_failed_start_is_rolled_back_in_its_own_task_and_the_error_propagates(
    recorder: _Recorder, caplog: pytest.LogCaptureFixture,
) -> None:
    subject = _subject(_raise_injected)

    with caplog.at_level(logging.INFO, logger=_ROLLBACK_LOGGER):
        with pytest.raises(InjectedStartFailure):
            await subject.start()

    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert (call["reason"], call["rollback"]) == ("startup_failed", True)
    assert call["runtime"] is subject
    assert call["start_failed"] is True  # set before the teardown begins
    assert call["task_name"] == "bf882-startup-rollback"
    assert call["task"] is not asyncio.current_task()
    assert subject._started is False
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and "BF-882" in errors[0].getMessage()
    assert "InjectedStartFailure" in errors[0].getMessage()


async def test_a_start_that_succeeds_is_not_rolled_back(recorder: _Recorder) -> None:
    async def body(subject: Any) -> None:
        return None

    subject = _subject(body)

    await subject.start()

    assert recorder.calls == []
    assert subject._start_failed is False
    assert subject._started is True


async def test_a_second_start_after_a_failed_one_raises_without_running_the_body_again(
    recorder: _Recorder,
) -> None:
    subject = _subject(_raise_injected)
    with pytest.raises(InjectedStartFailure):
        await subject.start()

    with pytest.raises(RuntimeError) as raised:
        await subject.start()

    assert str(raised.value) == _START_FAILED
    assert subject.body_runs == 1
    assert len(recorder.calls) == 1  # no second rollback


async def test_a_cancelled_start_is_rolled_back_by_a_task_that_is_not_being_cancelled(
    recorder: _Recorder, caplog: pytest.LogCaptureFixture,
) -> None:
    parked = asyncio.Event()

    async def body(subject: Any) -> None:
        parked.set()
        await asyncio.Event().wait()

    subject = _subject(body)
    start_task = asyncio.create_task(subject.start(), name="start-under-test")
    await asyncio.wait_for(parked.wait(), timeout=2)

    with caplog.at_level(logging.WARNING, logger=_ROLLBACK_LOGGER):
        start_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start_task

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["cancelling"] == 0  # the start task's own cancel count did not leak in
    assert subject._started is False
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "BF-882" in warnings[0].getMessage()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_an_outer_cancellation_during_the_rollback_lets_it_finish_then_raises_cancelled_error(
    recorder: _Recorder,
) -> None:
    recorder.release = asyncio.Event()
    subject = _subject(_raise_injected)
    start_task = asyncio.create_task(subject.start(), name="start-under-test")
    await asyncio.wait_for(recorder.began.wait(), timeout=2)

    start_task.cancel()  # the rollback is running and this task is waiting for it
    for _ in range(5):
        await asyncio.sleep(0)
    rollback_task = recorder.calls[0]["task"]
    assert not rollback_task.done(), "the cancellation reached the rollback"
    assert not start_task.done(), "the start task stopped waiting for the rollback"

    recorder.release.set()

    with pytest.raises(asyncio.CancelledError):
        await start_task
    assert recorder.finished.is_set()
    assert rollback_task.cancelled() is False
    assert subject._started is False


async def test_a_rollback_that_itself_ended_cancelled_does_not_hang_the_start_task(
    recorder: _Recorder, caplog: pytest.LogCaptureFixture,
) -> None:
    recorder.raises = asyncio.CancelledError()  # what a loop teardown does to a task
    subject = _subject(_raise_injected)

    with caplog.at_level(logging.WARNING, logger=_ROLLBACK_LOGGER):
        with pytest.raises(InjectedStartFailure):  # the waiter was not cancelled: its error stands
            await asyncio.wait_for(subject.start(), timeout=5)

    assert subject._started is False
    assert any("cancelled" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


async def test_a_rollback_that_raises_is_logged_and_the_start_error_still_propagates(
    recorder: _Recorder, caplog: pytest.LogCaptureFixture,
) -> None:
    recorder.raises = RuntimeError("the rollback broke")
    subject = _subject(_raise_injected)

    with caplog.at_level(logging.ERROR, logger=_ROLLBACK_LOGGER):
        with pytest.raises(InjectedStartFailure):
            await subject.start()

    assert subject._started is False
    logged = [r for r in caplog.records if "the rollback broke" in repr(r.exc_info)]
    assert len(logged) == 1 and logged[0].exc_info is not None
    assert "BF-882" in logged[0].getMessage()


async def test_closing_a_suspended_start_is_not_rolled_back(recorder: _Recorder) -> None:
    """GeneratorExit is thrown into a coroutine that is closed; awaiting a rollback there
    would raise ``coroutine ignored GeneratorExit``."""
    async def body(subject: Any) -> None:
        await asyncio.get_running_loop().create_future()

    subject = _subject(body)
    coroutine = subject.start()
    coroutine.send(None)  # runs to the first suspension

    coroutine.close()

    assert recorder.calls == []
    assert subject._start_failed is False


async def test_rollback_failed_start_flags_the_runtime_before_it_tears_anything_down(
    recorder: _Recorder,
) -> None:
    subject = SimpleNamespace(_start_failed=False, _started=True)

    await _rollback_module().rollback_failed_start(subject, InjectedStartFailure("direct"))  # type: ignore[arg-type]

    assert recorder.calls[0]["start_failed"] is True
    assert subject._started is False


# ---------------------------------------------------------------------------
# shutdown(rollback=True) against a runtime double
# ---------------------------------------------------------------------------

def _no_waits() -> SystemConfig:
    return SystemConfig(memory=MemoryConfig(shutdown_write_grace_s=0.0, shutdown_dispatch_grace_s=0.0))


class _Sleeps:
    """Records the delays of the sleeps ``shutdown()`` asks for, without waiting them out."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.delays: list[float] = []
        real_sleep = asyncio.sleep

        async def recording_sleep(delay: float, result: Any = None) -> Any:
            if delay >= 0.1:  # the loops' own zero-length yields are not shutdown's waits
                self.delays.append(delay)
                return await real_sleep(0, result)
            return await real_sleep(delay, result)

        monkeypatch.setattr(asyncio, "sleep", recording_sleep)


class _IntegritySpy:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import probos.shutdown_integrity as integrity

        self.calls: list[str] = []
        for name in ("mark_clean_shutdown", "mark_dirty_shutdown"):
            original = getattr(integrity, name)

            def spy(*args: Any, _name: str = name, _original: Any = original, **kwargs: Any) -> Any:
                self.calls.append(_name)
                return _original(*args, **kwargs)

            monkeypatch.setattr(integrity, name, spy)


async def test_rollback_passes_the_started_and_bf598_guards_and_keeps_the_configured_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SystemConfig(memory=MemoryConfig(shutdown_write_grace_s=0.25, shutdown_dispatch_grace_s=0.5))
    runtime = BareRuntime(tmp_path / "data", config=config, started=False, shutdown_started=True)
    runtime.intent_bus = SimpleNamespace(close_to_new_dispatches=lambda: None, _agent_queues={})  # the BF-296 wait is gated on it
    sleeps = _Sleeps(monkeypatch)
    integrity = _IntegritySpy(monkeypatch)

    await shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True)  # type: ignore[arg-type]

    assert sleeps.delays[:2] == [0.25, 0.5]
    assert runtime.event_log.events == ["stopping", "stopped"]
    assert runtime.calls[-6:] == [
        "gossip.stop", "signal_manager.stop", "hebbian_router.stop", "trust_network.stop",
        "event_log.stop", "llm_client.close",
    ]
    assert integrity.calls == []
    assert not (runtime._data_dir / "shutdown_status.json").exists()
    assert not (runtime._data_dir / "session_last.json").exists()  # none existed: a rollback creates none
    assert runtime._shutdown_started is True
    assert runtime._started is False


async def test_without_rollback_a_started_runtime_is_torn_down_and_marked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control for the test above: the same double, today's behaviour, and the spy sees the marker."""
    runtime = BareRuntime(tmp_path / "data", config=_no_waits(), started=True)
    integrity = _IntegritySpy(monkeypatch)

    await shutdown_module.shutdown(runtime, reason="test")  # type: ignore[arg-type]

    assert integrity.calls == ["mark_dirty_shutdown"]
    assert (runtime._data_dir / "shutdown_status.json").is_file()
    assert runtime.calls[-1] == "llm_client.close"


async def test_without_rollback_a_not_started_runtime_still_returns_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = BareRuntime(tmp_path / "data", config=SystemConfig(), started=False)
    sleeps = _Sleeps(monkeypatch)

    await shutdown_module.shutdown(runtime, reason="never started")  # type: ignore[arg-type]

    assert sleeps.delays == []
    assert runtime.event_log.events == []
    assert "gossip.stop" not in runtime.calls
    assert (runtime._data_dir / "session_last.json").is_file()  # BF-137: written before the guard
    assert not (runtime._data_dir / "shutdown_status.json").exists()


async def test_without_rollback_a_second_shutdown_still_returns_before_writing_anything(
    tmp_path: Path,
) -> None:
    runtime = BareRuntime(tmp_path / "data", config=_no_waits(), started=True, shutdown_started=True)

    await shutdown_module.shutdown(runtime, reason="again")  # type: ignore[arg-type]

    assert runtime.calls == []
    assert not (runtime._data_dir / "session_last.json").exists()


async def test_shutdown_gains_only_a_keyword_only_rollback_parameter_defaulting_to_false() -> None:
    parameters = inspect.signature(shutdown_module.shutdown).parameters
    assert list(parameters) == ["runtime", "reason", "rollback"]
    assert parameters["rollback"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["rollback"].default is False


async def _runtime_with_every_session_write(tmp_path: Path) -> BareRuntime:
    runtime = BareRuntime(tmp_path / "data", config=_no_waits(), started=True)
    calls = runtime.calls
    # A crew agent with working memory, so the AD-573 freeze has something to write.
    await runtime.registry.register(SimpleNamespace(  # type: ignore[arg-type]
        id="crew-1", agent_type="architect", pool="p", is_alive=False,
        working_memory=SimpleNamespace(to_dict=lambda: {"item": 1}),
    ))
    runtime.ward_room = SimpleNamespace(
        is_started=True,
        get_channel_by_name=_async_returning(SimpleNamespace(id="all-hands")),
        create_thread=_async_recording(calls, "ward_room.create_thread"),
        stop_prune_loop=_async_recording(calls, "ward_room.stop_prune_loop"),
        stop=_async_recording(calls, "ward_room.stop"),
    )
    runtime.dream_scheduler = SimpleNamespace(
        engine=SimpleNamespace(consolidate_for_shutdown=_async_returning(
            SimpleNamespace(episodes_replayed=0, weights_strengthened=0, weights_pruned=0),
            calls, "dream.consolidate_for_shutdown",
        )),
        stop_gracefully=_async_returning(True, calls, "dream_scheduler.stop_gracefully"),
        stop=_async_recording(calls, "dream_scheduler.stop"),
    )
    runtime.episodic_memory = RecordedService(calls, "episodic_memory")
    runtime.proactive_loop = SimpleNamespace(
        _agent_cooldowns={"agent-1": 1.0}, stop=_async_recording(calls, "proactive_loop.stop"),
    )
    runtime._night_orders_mgr = SimpleNamespace(active=True, expire=lambda: calls.append("night_orders.expire"))
    runtime.watch_manager = RecordedService(calls, "watch_manager")
    runtime._knowledge_store = SimpleNamespace(
        store_cooldowns=_async_recording(calls, "knowledge_store.store_cooldowns"),
        store_manifest=_async_recording(calls, "knowledge_store.store_manifest"),
        store_trust_snapshot=_async_recording(calls, "knowledge_store.store_trust_snapshot"),
        store_routing_weights=_async_recording(calls, "knowledge_store.store_routing_weights"),
        store_workflows=_async_recording(calls, "knowledge_store.store_workflows"),
        flush=_async_recording(calls, "knowledge_store.flush"),
    )
    runtime._build_manifest = lambda: {}
    runtime.trust_network.raw_scores = lambda: {}
    runtime.hebbian_router.all_weights_typed = lambda: {}
    runtime.workflow_cache = SimpleNamespace(export_all=lambda: [])
    runtime.working_memory_store = SimpleNamespace(
        save_all=_async_recording(calls, "working_memory_store.save_all"),
        stop=_async_recording(calls, "working_memory_store.stop"),
    )
    return runtime


def _async_recording(calls: list[str], label: str) -> Any:
    async def call(*args: Any, **kwargs: Any) -> None:
        calls.append(label)
    return call


def _async_returning(result: Any, calls: list[str] | None = None, label: str = "") -> Any:
    async def call(*args: Any, **kwargs: Any) -> Any:
        if calls is not None:
            calls.append(label)
        return result
    return call


_SESSION_WRITES = {
    "ward_room.create_thread",
    "dream.consolidate_for_shutdown",
    "knowledge_store.store_cooldowns",
    "night_orders.expire",
    "knowledge_store.store_manifest",
    "knowledge_store.store_trust_snapshot",
    "knowledge_store.store_routing_weights",
    "knowledge_store.store_workflows",
    "knowledge_store.flush",
    "working_memory_store.save_all",
}
_RELEASES = {
    "ward_room.stop", "dream_scheduler.stop_gracefully", "dream_scheduler.stop", "episodic_memory.stop",
    "proactive_loop.stop", "watch_manager.stop", "working_memory_store.stop", "gossip.stop",
    "signal_manager.stop", "hebbian_router.stop", "trust_network.stop", "event_log.stop", "llm_client.close",
}


async def test_a_clean_stop_makes_every_session_write_and_the_spies_see_them(tmp_path: Path) -> None:
    """The control: it proves each write below is reachable on this double and is recorded."""
    runtime = await _runtime_with_every_session_write(tmp_path)

    await shutdown_module.shutdown(runtime, reason="test")  # type: ignore[arg-type]

    assert _SESSION_WRITES <= set(runtime.calls), _SESSION_WRITES - set(runtime.calls)
    assert _RELEASES <= set(runtime.calls), _RELEASES - set(runtime.calls)


async def test_a_rollback_makes_no_session_write_and_still_makes_every_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = await _runtime_with_every_session_write(tmp_path)
    integrity = _IntegritySpy(monkeypatch)

    await shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True)  # type: ignore[arg-type]

    assert not _SESSION_WRITES & set(runtime.calls), _SESSION_WRITES & set(runtime.calls)
    assert _RELEASES <= set(runtime.calls), _RELEASES - set(runtime.calls)
    assert integrity.calls == []
    assert not (runtime._data_dir / "shutdown_status.json").exists()


_DEGRADED_STOPS = (
    "episodic_memory", "red_team_lead", "_eviction_audit", "red_team_agent",
    "gossip", "signal_manager", "hebbian_router", "trust_network", "event_log",
)


def _runtime_with_a_failing_stop(tmp_path: Path, failing: str) -> BareRuntime:
    runtime = BareRuntime(tmp_path / "data", config=_no_waits(), started=True)
    boom = RuntimeError(f"{failing} refused to stop")
    if failing in ("gossip", "signal_manager", "hebbian_router", "trust_network"):
        setattr(runtime, failing, RecordedService(runtime.calls, failing, stop_raises=boom))
    elif failing == "event_log":
        original = runtime.event_log.stop

        async def stop() -> None:
            await original()
            raise boom

        runtime.event_log.stop = stop  # type: ignore[method-assign]
    elif failing == "red_team_agent":
        agent = RecordedService(runtime.calls, "red_team_agent", stop_raises=boom)
        agent.id = "red-team-1"  # type: ignore[attr-defined]
        runtime.red_team_agents = [agent]
    else:
        setattr(runtime, failing, RecordedService(runtime.calls, failing, stop_raises=boom))
    return runtime


@pytest.mark.parametrize("failing", _DEGRADED_STOPS)
async def test_a_rollback_logs_a_failing_stop_and_still_closes_everything_after_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, failing: str,
) -> None:
    runtime = _runtime_with_a_failing_stop(tmp_path, failing)

    with caplog.at_level(logging.WARNING, logger=_SHUTDOWN_LOGGER):
        await shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True)  # type: ignore[arg-type]

    warned = [r for r in caplog.records if r.levelno == logging.WARNING and "refused to stop" in repr(r.exc_info)]
    assert len(warned) == 1, "the failing stop was not logged exactly once, with its traceback"
    assert f"{failing}.stop" in runtime.calls  # it was attempted
    for later in ("gossip", "signal_manager", "hebbian_router", "trust_network", "event_log"):
        assert f"{later}.stop" in runtime.calls, f"{later} was never stopped after {failing} failed"
    assert runtime.calls[-1] == "llm_client.close"
    assert runtime._started is False


@pytest.mark.parametrize("failing", _DEGRADED_STOPS)
async def test_without_rollback_a_failing_stop_still_propagates(tmp_path: Path, failing: str) -> None:
    runtime = _runtime_with_a_failing_stop(tmp_path, failing)

    with pytest.raises(RuntimeError, match="refused to stop"):
        await shutdown_module.shutdown(runtime, reason="test")  # type: ignore[arg-type]


class _Crew:
    """A registry member double: ``is_alive`` until its stop() runs."""

    def __init__(self, calls: list[str], agent_id: str, *, alive: bool, raises: bool = False) -> None:
        self.id = agent_id
        self.agent_type = "crew"
        self.pool = "p"
        self.is_alive = alive
        self._calls = calls
        self._raises = raises

    async def stop(self) -> None:
        self._calls.append(f"{self.id}.stop")
        self.is_alive = False
        if self._raises:
            raise RuntimeError(f"{self.id} would not stop")


async def _runtime_with_survivors(tmp_path: Path) -> tuple[BareRuntime, list[_Crew]]:
    runtime = BareRuntime(tmp_path / "data", config=_no_waits(), started=True)
    survivors = [
        _Crew(runtime.calls, "survivor", alive=True),
        _Crew(runtime.calls, "stopped", alive=False),
        _Crew(runtime.calls, "stubborn", alive=True, raises=True),
        _Crew(runtime.calls, "last", alive=True),
    ]
    for agent in survivors:
        await runtime.registry.register(agent)  # type: ignore[arg-type]
    runtime.pools = {"p": RecordedService(runtime.calls, "pool.p")}
    return runtime, survivors


async def test_a_rollback_stops_every_agent_a_failed_pool_stop_left_alive(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    runtime, _ = await _runtime_with_survivors(tmp_path)

    with caplog.at_level(logging.WARNING, logger=_SHUTDOWN_LOGGER):
        await shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True)  # type: ignore[arg-type]

    stops = [call for call in runtime.calls if call.endswith(".stop") and call.split(".")[0] in {"survivor", "stopped", "stubborn", "last"}]
    assert stops == ["survivor.stop", "stubborn.stop", "last.stop"]  # alive ones only, one failure does not stop the rest
    assert runtime.calls.index("pool.p.stop") < runtime.calls.index("survivor.stop") < runtime.calls.index("gossip.stop")
    assert any("stubborn" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert runtime.registry.count == 4  # the pool ownership policy is unchanged: nothing is unregistered


async def _runtime_with_crew_and_other_agents(tmp_path: Path) -> BareRuntime:
    runtime = BareRuntime(tmp_path / "data", config=_no_waits(), started=True)
    for agent_id, agent_type in (("a1", "architect"), ("c1", "calculator"), ("s1", "scout")):
        agent = _Crew(runtime.calls, agent_id, alive=False)
        agent.agent_type = agent_type
        await runtime.registry.register(agent)  # type: ignore[arg-type]
    return runtime


async def test_the_session_record_is_written_when_the_registry_has_agents(tmp_path: Path) -> None:
    """BF-135/BF-137: ``shutdown()`` writes the record before anything can fail. It never did
    with a non-empty registry: a function-local re-import of ``is_crew_agent`` further down
    made the name local to the whole function, so the ``agent_count`` above it raised
    UnboundLocalError, which is logged at debug and swallowed. A stop of a real booted runtime
    wrote no ``session_last.json`` at all (``__main__`` writes its own copy first)."""
    runtime = await _runtime_with_crew_and_other_agents(tmp_path)

    await shutdown_module.shutdown(runtime, reason="tidy")  # type: ignore[arg-type]

    record = json.loads((runtime._data_dir / "session_last.json").read_text(encoding="utf-8"))
    assert record["reason"] == "tidy"
    assert record["agent_count"] == 2  # architect and scout are crew; calculator is not
    assert record["session_id"] == "bare-runtime"


def _write_session_record(data_dir: Path, *, shutdown_time_utc: float) -> dict[str, Any]:
    """What a real earlier session left: the record ``cognitive_services`` reads at boot."""
    record = {
        "session_id": "previous-session",
        "start_time_utc": shutdown_time_utc - 600.0,
        "shutdown_time_utc": shutdown_time_utc,
        "uptime_seconds": 600.0,
        "agent_count": 7,
        "reason": "tidy",
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "session_last.json").write_text(json.dumps(record), encoding="utf-8")
    return record


async def test_a_rollback_refreshes_an_existing_session_record(tmp_path: Path) -> None:
    """BF-137: a failed start must not leave the previous session's timestamp, or the next
    boot's stasis duration would be counted from a shutdown that is no longer the latest."""
    runtime = await _runtime_with_crew_and_other_agents(tmp_path)
    stale = time.time() - 86_400.0
    _write_session_record(runtime._data_dir, shutdown_time_utc=stale)
    before = time.time()

    await shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True)  # type: ignore[arg-type]

    record = json.loads((runtime._data_dir / "session_last.json").read_text(encoding="utf-8"))
    assert record["reason"] == "startup_failed"
    assert record["shutdown_time_utc"] >= before  # refreshed, not the day-old stamp
    assert record["agent_count"] == 2
    assert record["session_id"] == "bare-runtime"


async def test_a_rollback_does_not_create_a_session_record(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """``cognitive_services`` reads ANY record as a stasis recovery, so a boot that never
    completed must not leave one behind for a maiden voyage to be misread against."""
    runtime = await _runtime_with_crew_and_other_agents(tmp_path)
    assert not (runtime._data_dir / "session_last.json").exists()  # the premise

    with caplog.at_level(logging.INFO, logger=_SHUTDOWN_LOGGER):
        await shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True)  # type: ignore[arg-type]

    assert not (runtime._data_dir / "session_last.json").exists()
    assert any("does not create" in r.getMessage() for r in caplog.records if r.levelno == logging.INFO)
    assert runtime._started is False


async def test_without_rollback_a_stop_still_creates_the_session_record(tmp_path: Path) -> None:
    runtime = await _runtime_with_crew_and_other_agents(tmp_path)
    assert not (runtime._data_dir / "session_last.json").exists()  # the same premise as above

    await shutdown_module.shutdown(runtime, reason="tidy")  # type: ignore[arg-type]

    assert (runtime._data_dir / "session_last.json").is_file()


async def test_without_rollback_no_agent_is_force_stopped(tmp_path: Path) -> None:
    runtime, _ = await _runtime_with_survivors(tmp_path)

    await shutdown_module.shutdown(runtime, reason="test")  # type: ignore[arg-type]

    assert not [call for call in runtime.calls if call.split(".")[0] in {"survivor", "stopped", "stubborn", "last"}]


async def test_a_rollback_also_makes_slice_a_releases(tmp_path: Path) -> None:
    runtime = BareRuntime(tmp_path / "data", config=_no_waits(), started=True)
    closed: list[str] = []
    runtime.service_profiles = SimpleNamespace(close=lambda: closed.append("service_profiles"))
    runtime._semantic_store = SimpleNamespace(close=lambda: closed.append("semantic_store"))
    runtime.profile_store = SimpleNamespace(close=lambda: closed.append("profile_store"))
    marker = object()
    standing_orders.set_billet_registry(marker)  # type: ignore[arg-type]
    standing_orders.set_step_router(marker)  # type: ignore[arg-type]
    standing_orders.set_task_context(marker)
    try:
        await shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True)  # type: ignore[arg-type]

        assert sorted(closed) == ["profile_store", "semantic_store", "service_profiles"]
        assert runtime._semantic_store is None and runtime.service_profiles is None
        assert runtime.profile_store is not None  # closed, attribute kept
        assert standing_orders._billet_registry is None
        assert standing_orders._step_router is None
        assert standing_orders._task_context is None
    finally:
        standing_orders.set_billet_registry(None)
        standing_orders.set_step_router(None)
        standing_orders.set_task_context(None)


# ---------------------------------------------------------------------------
# YeomanAgent: one slot, released once, only after the agent has stopped
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_yeoman_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(YeomanAgent, "_live_instance_count", 0)


def _yeoman(agent_id: str) -> YeomanAgent:
    return YeomanAgent(pool="yeoman", agent_id=agent_id)


async def test_a_constructed_yeoman_holds_the_slot_and_stop_releases_it_once(
    clean_yeoman_slot: None,
) -> None:
    yeoman = _yeoman("yeo-1")
    assert YeomanAgent._live_instance_count == 1
    assert yeoman._holds_singleton_slot is True

    await yeoman.stop()
    assert YeomanAgent._live_instance_count == 0
    assert yeoman._holds_singleton_slot is False

    await yeoman.stop()  # a second stop (a forced quiescence after a pool stop) frees nothing more
    assert YeomanAgent._live_instance_count == 0


async def test_a_stale_instance_cannot_free_a_live_successors_slot(clean_yeoman_slot: None) -> None:
    first = _yeoman("yeo-1")
    await first.stop()
    second = _yeoman("yeo-2")
    assert YeomanAgent._live_instance_count == 1

    await first.stop()  # the stale one again

    assert YeomanAgent._live_instance_count == 1  # the live successor still holds it
    with pytest.raises(RuntimeError, match="singleton"):
        _yeoman("yeo-3")
    await second.stop()
    assert YeomanAgent._live_instance_count == 0


async def test_a_stop_that_fails_before_quiescence_keeps_the_slot(
    clean_yeoman_slot: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    yeoman = _yeoman("yeo-1")

    async def unwired(self: CognitiveAgent) -> None:
        raise RuntimeError("the agent would not stop")

    monkeypatch.setattr(CognitiveAgent, "stop", unwired)
    with pytest.raises(RuntimeError, match="would not stop"):
        await yeoman.stop()

    assert YeomanAgent._live_instance_count == 1  # never freed before the agent has stopped
    assert yeoman._holds_singleton_slot is True
    monkeypatch.undo()
    await yeoman.stop()
    assert YeomanAgent._live_instance_count == 0


async def test_an_instance_built_without_init_still_releases_on_stop(
    clean_yeoman_slot: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shape tests/test_yeoman_agent.py builds: the counter is raised by hand and the
    instance has no ``_holds_singleton_slot``."""
    async def unwired(self: CognitiveAgent) -> None:
        return None

    monkeypatch.setattr(CognitiveAgent, "stop", unwired)
    yeoman = object.__new__(YeomanAgent)
    yeoman._flush_task = None
    yeoman._pending_dispatch_tasks = set()
    YeomanAgent._live_instance_count += 1

    await yeoman.stop()

    assert YeomanAgent._live_instance_count == 0


# ---------------------------------------------------------------------------
# A real boot that fails
# ---------------------------------------------------------------------------

_BOOT_FACTS = {
    "pre_infra": {"started": False, "event_log_open": False, "pools": 0, "yeoman": 0},
    "after_infra": {"started": False, "event_log_open": True, "pools": 0, "yeoman": 0},
    "fleet_entry": {"started": False, "event_log_open": True, "pools": 0, "yeoman": 0},
    "fleet_partial": {"started": False, "event_log_open": True, "pools": 3, "yeoman": 0},
    "cognitive": {"started": False, "event_log_open": True, "yeoman": 1},
    "communication": {"started": False, "event_log_open": True, "yeoman": 1},
    "finalize_started_event": {"started": True, "event_log_open": True, "yeoman": 1},
}


def _assert_the_injection_reached_its_phase(phase: str, facts: dict[str, Any], baseline: LifecycleBaseline) -> None:
    """The premise: a rollback test that never reached the phase it names proves nothing."""
    expected = dict(_BOOT_FACTS[phase])
    assert facts["yeoman_count"] - baseline.yeoman_count == expected.pop("yeoman"), facts
    for key, value in expected.items():
        assert facts[key] == value, (phase, key, facts)
    if phase in ("cognitive", "communication", "finalize_started_event"):
        assert facts["pools"] > 3, facts  # the whole fleet is up


async def _assert_fully_rolled_back(runtime: ProbOSRuntime, baseline: LifecycleBaseline) -> None:
    assert runtime._started is False
    assert runtime.pools == {}
    assert runtime.registry.count == 0
    assert YeomanAgent._live_instance_count == baseline.yeoman_count
    assert not (runtime._data_dir / "shutdown_status.json").exists()
    assert await baseline.leftovers() == NOTHING_LEFT


async def _failed_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tracker: SqliteTracker,
    phase: str,
    **injection: Any,
) -> tuple[ProbOSRuntime, Any, LifecycleBaseline]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    baseline = LifecycleBaseline.capture(tracker)
    runtime = make_runtime(tmp_path, config=lifecycle_config(tmp_path, zero_grace=True))
    failure = inject_start_failure(monkeypatch, runtime, phase, **injection)
    with pytest.raises(InjectedStartFailure) as raised:
        await runtime.start()
    assert raised.value is failure.error
    assert failure.fired
    _assert_the_injection_reached_its_phase(phase, failure.facts, baseline)
    return runtime, failure, baseline


@pytest.mark.parametrize("phase", START_FAILURE_PHASES)
async def test_a_failed_start_rolls_back_everything_the_partial_boot_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracker: SqliteTracker, phase: str,
) -> None:
    runtime, _, baseline = await _failed_start(tmp_path, monkeypatch, tracker, phase)

    await _assert_fully_rolled_back(runtime, baseline)

    # A maiden voyage that failed to start leaves no session record, which is what keeps
    # the next boot a first boot (see the same-directory tests below).
    assert not (runtime._data_dir / "session_last.json").exists()


@pytest.mark.parametrize("phase", ["after_infra", "finalize_started_event"])
async def test_after_a_rolled_back_start_stop_is_a_no_op_and_start_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracker: SqliteTracker, phase: str,
) -> None:
    _write_session_record(tmp_path / "data", shutdown_time_utc=time.time() - 3600.0)
    runtime, _, baseline = await _failed_start(tmp_path, monkeypatch, tracker, phase)
    session_path = runtime._data_dir / "session_last.json"
    assert json.loads(session_path.read_text(encoding="utf-8"))["reason"] == "startup_failed"  # refreshed by the rollback
    session_before = session_path.read_bytes()

    await runtime.stop()  # BF-598: nothing to tear down, and nothing written

    assert not (runtime._data_dir / "shutdown_status.json").exists()
    assert session_path.read_bytes() == session_before
    with pytest.raises(RuntimeError) as raised:
        await runtime.start()
    assert str(raised.value) == _START_FAILED
    await _assert_fully_rolled_back(runtime, baseline)


@pytest.mark.parametrize("phase", ["cognitive", "finalize_started_event"])
async def test_after_a_rolled_back_start_a_fresh_runtime_boots_and_stops_in_the_same_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracker: SqliteTracker, phase: str,
) -> None:
    _, failure, baseline = await _failed_start(tmp_path / "first", monkeypatch, tracker, phase)
    failure.disarm()
    monkeypatch.chdir(tmp_path)

    fresh = make_runtime(tmp_path / "second", config=lifecycle_config(tmp_path / "second", zero_grace=True))
    await fresh.start()
    try:
        assert fresh._started is True
        assert YeomanAgent._live_instance_count == baseline.yeoman_count + 1
    finally:
        await fresh.stop()

    assert YeomanAgent._live_instance_count == baseline.yeoman_count
    assert await baseline.leftovers() == NOTHING_LEFT


async def test_an_unwire_failure_cannot_keep_the_yeoman_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracker: SqliteTracker, caplog: pytest.LogCaptureFixture,
) -> None:
    """ResourcePool unwires an agent before it stops it and keeps ownership when the unwire
    fails, so the pool stop alone leaves the Yeoman running and holding the slot. The forced
    quiescence stops it, and only then is the slot freed (never two live Yeomans)."""
    original = AgentOnboardingService.unwire_agent

    async def unwire_agent(self: AgentOnboardingService, agent_id: str) -> None:
        agent = self._registry.get(agent_id)
        if agent is not None and agent.agent_type == "yeoman":
            raise RuntimeError("INJECTED unwire failure")
        await original(self, agent_id)

    monkeypatch.setattr(AgentOnboardingService, "unwire_agent", unwire_agent)

    with caplog.at_level(logging.ERROR, logger=_SHUTDOWN_LOGGER):
        runtime, _, baseline = await _failed_start(tmp_path, monkeypatch, tracker, "communication")

    assert YeomanAgent._live_instance_count == baseline.yeoman_count
    assert "yeoman" in runtime.pools  # ownership is retained, as before
    assert any("Pool 'yeoman' failed to stop" in r.getMessage() for r in caplog.records)
    assert runtime._started is False
    leftovers = await baseline.leftovers()
    assert leftovers["threads"] == [], leftovers
    assert leftovers["connections"] == [], leftovers


async def test_a_start_cancelled_while_blocked_completes_the_rollback_then_raises_cancelled_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracker: SqliteTracker,
) -> None:
    monkeypatch.chdir(tmp_path)
    baseline = LifecycleBaseline.capture(tracker)
    runtime = make_runtime(tmp_path, config=lifecycle_config(tmp_path, zero_grace=True))
    failure = inject_start_failure(monkeypatch, runtime, "cognitive", block=True)
    start_task = asyncio.create_task(runtime.start(), name="blocked-start")
    await asyncio.wait_for(failure.reached.wait(), timeout=60)
    _assert_the_injection_reached_its_phase("cognitive", failure.facts, baseline)

    start_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await start_task

    await _assert_fully_rolled_back(runtime, baseline)


async def test_a_second_cancellation_during_the_rollback_lets_it_finish_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracker: SqliteTracker,
) -> None:
    """Default waits (1 s + 2 s) give the rollback a window to be cancelled in."""
    monkeypatch.chdir(tmp_path)
    baseline = LifecycleBaseline.capture(tracker)
    runtime = make_runtime(tmp_path, config=lifecycle_config(tmp_path, zero_grace=False))
    failure = inject_start_failure(monkeypatch, runtime, "after_infra", block=True)
    start_task = asyncio.create_task(runtime.start(), name="blocked-start")
    await asyncio.wait_for(failure.reached.wait(), timeout=60)

    start_task.cancel()
    await asyncio.sleep(0.3)  # inside the write-grace wait of the rollback
    assert not start_task.done()
    start_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await start_task

    await _assert_fully_rolled_back(runtime, baseline)


async def test_a_failing_stop_during_the_rollback_does_not_leave_the_stores_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracker: SqliteTracker, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.chdir(tmp_path)
    baseline = LifecycleBaseline.capture(tracker)
    runtime = make_runtime(tmp_path, config=lifecycle_config(tmp_path, zero_grace=True))
    runtime._eviction_audit = RecordedService([], "eviction_audit", stop_raises=RuntimeError("eviction audit refused"))
    inject_start_failure(monkeypatch, runtime, "after_infra")

    with caplog.at_level(logging.WARNING, logger=_SHUTDOWN_LOGGER):
        with pytest.raises(InjectedStartFailure):
            await runtime.start()

    assert any(
        r.levelno == logging.WARNING and "eviction audit refused" in repr(r.exc_info)
        for r in caplog.records
    )
    assert runtime.event_log.is_open is False
    assert await baseline.leftovers() == NOTHING_LEFT  # event-log, trust, Hebbian and identity workers are gone


# ---------------------------------------------------------------------------
# One teardown step that raises must not end the rollback
# ---------------------------------------------------------------------------
#
# Review of the first BF-882: a real boot that failed at the ``started`` row, with the ACM's
# stop() raising, left the event log open, 43 pools running, 70 registry entries and the
# Yeoman slot held. One unguarded step aborted everything after it, and the rollback only
# logged the abort. Every step is best-effort in a rollback now; a normal stop is unchanged.

_BOOM = "INJECTED teardown step failure"

# runtime attribute -> the step name shutdown() logs for it. Each component's async stop() is
# one step of the teardown.
_STOPPED_COMPONENTS: tuple[tuple[str, str], ...] = (
    ("episodic_memory", "episodic memory stop"),
    ("red_team_lead", "red team lead stop"),
    ("_eviction_audit", "eviction audit log stop"),
    ("acm", "ACM stop"),
    ("visiting_officers", "visiting officer registry stop"),
    ("workflow_cron", "workflow cron stop"),
    ("identity_registry", "identity registry stop"),
    ("sif", "SIF stop"),
    ("initiative", "initiative engine stop"),
    ("proactive_loop", "proactive loop stop"),
    ("watch_manager", "watch manager stop"),
    ("persistent_task_store", "persistent task store stop"),
    ("work_item_store", "workforce store stop"),
    ("build_dispatcher", "build dispatcher stop"),
    ("cognitive_journal", "cognitive journal stop"),
    ("clearance_grant_store", "clearance grant store stop"),
    ("clinical_notes_store", "clinical notes store stop"),
    ("tool_permission_store", "tool permission store stop"),
    ("skill_grant_store", "skill grant store stop"),
    ("intent_grant_store", "intent grant store stop"),
    ("action_approval_store", "action approval store stop"),
    ("mcp_server_store", "MCP server store stop"),
    ("department_tool_grant_store", "department tool grant store stop"),
    ("mcp_tool_risk_store", "MCP tool risk store stop"),
    ("_counselor_profile_store", "counselor profile store stop"),
    ("_procedure_store", "procedure store stop"),
    ("_drift_scheduler", "drift scheduler stop"),
    ("_qualification_store", "qualification store stop"),
    ("_retrieval_practice_engine", "retrieval practice engine stop"),
    ("_activation_tracker", "activation tracker stop"),
    ("cognitive_skill_catalog", "cognitive skill catalog stop"),
    ("skill_service", "skill service stop"),
    ("skill_registry", "skill registry stop"),
    ("assignment_service", "assignment service stop"),
    ("pool_scaler", "pool scaler stop"),
    ("federation_telemetry_relay", "federation telemetry relay stop"),
    ("federation_bridge", "federation bridge stop"),
    ("_federation_transport", "federation transport stop"),
    ("gossip", "gossip protocol stop"),
    ("signal_manager", "signal manager stop"),
    ("hebbian_router", "Hebbian router stop"),
    ("trust_network", "trust network stop"),
    ("dream_scheduler", "dream scheduler stop"),
    ("task_scheduler", "task scheduler stop"),
    ("_semantic_layer", "semantic knowledge layer stop"),
)

# The steps that are not a plain ``await component.stop()``: a synchronous close, a module-level
# helper, two stops that share one object, and the two statements in the middle of a larger
# block that guard themselves (tests/test_ad654d_internal_emitters.py runs them on their own).
_OTHER_STEPS: tuple[str, ...] = (
    "crew scheduling close",
    "confab probe scheduling close",
    "run_python long-run close",
    "crew orchestrator stop",
    "run_python long-run settle",
    "periodic flush task cancel",
    "runtime SQLite sidecars stop",
    "recreation turns stop",
    "cognitive queue shutdown",
    "crew session delivery close",
    "directive store close",
    "ward room prune loop stop",
    "ward room stop",
    "AD-1278 early audit flush",
    "red team agent red-1 stop",
    "red team agent red-1 unregister",
    "remote avatar telemetry cache clear",
    "pools stop and intent bus drain",
    "standing-orders globals clear",
    "event log stop",
    "LLM client close",
    "AD-1278 audit drain",
)
_ALL_STEPS: tuple[str, ...] = tuple(label for _, label in _STOPPED_COMPONENTS) + _OTHER_STEPS


def _sync_hook(calls: list[str], name: str, error: BaseException | None) -> Any:
    def hook(*args: Any, **kwargs: Any) -> None:
        calls.append(name)
        if error is not None:
            raise error
    return hook


def _async_hook(calls: list[str], name: str, error: BaseException | None, result: Any = None) -> Any:
    async def hook(*args: Any, **kwargs: Any) -> Any:
        calls.append(name)
        if error is not None:
            raise error
        return result
    return hook


class _EventLogThatFailsToStop(RecordedEventLog):
    def __init__(self, calls: list[str], error: BaseException | None) -> None:
        super().__init__(calls)
        self._error = error

    async def stop(self) -> None:
        await super().stop()
        if self._error is not None:
            raise self._error


def _stocked_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    rollback: bool,
    failing: str | None = None,
    everything: bool = False,
    raises: BaseException | None = None,
) -> tuple[BareRuntime, dict[str, BaseException]]:
    """A runtime double with a recording stand-in for every teardown step ``shutdown()`` has.

    Each step records its call and then raises when it is the ``failing`` one (or when
    ``everything`` is set). Two runtimes built alike except for ``failing`` therefore record
    the same calls in the same order exactly when the failure skipped nothing.
    """
    runtime = BareRuntime(tmp_path / "data", config=_no_waits(), started=not rollback)
    calls = runtime.calls
    errors: dict[str, BaseException] = {
        label: raises if raises is not None and label == failing else RuntimeError(f"{_BOOM}: {label}")
        for label in _ALL_STEPS
    }

    def error_for(label: str) -> BaseException | None:
        return errors[label] if everything or label == failing else None

    for attribute, label in _STOPPED_COMPONENTS:
        setattr(runtime, attribute, RecordedService(calls, attribute, stop_raises=error_for(label)))
    runtime.event_log = _EventLogThatFailsToStop(calls, error_for("event log stop"))
    runtime.crew_orchestrator = SimpleNamespace(
        close_scheduling=_sync_hook(calls, "crew.close_scheduling", error_for("crew scheduling close")),
        stop=_async_hook(calls, "crew.stop", error_for("crew orchestrator stop")),
    )
    runtime.close_confab_probe_scheduling = _sync_hook(  # type: ignore[method-assign]
        calls, "close_confab_probe_scheduling", error_for("confab probe scheduling close"),
    )
    runtime.execution_long_runs = LongRunService()
    monkeypatch.setattr(
        LongRunService, "close", _sync_hook(calls, "long_runs.close", error_for("run_python long-run close")),
    )
    monkeypatch.setattr(
        LongRunService, "wait_settled",
        _async_hook(calls, "long_runs.wait_settled", error_for("run_python long-run settle"), True),
    )
    runtime._flush_task = SimpleNamespace(
        cancel=_sync_hook(calls, "flush_task.cancel", error_for("periodic flush task cancel")),
    )
    monkeypatch.setattr(
        shutdown_module, "_stop_runtime_sqlite_sidecars",
        _async_hook(calls, "sidecars.stop", error_for("runtime SQLite sidecars stop")),
    )
    runtime.recreation_service = SimpleNamespace(turns=SimpleNamespace(
        stop=_async_hook(calls, "recreation.turns.stop", error_for("recreation turns stop")),
    ))
    runtime.intent_bus = SimpleNamespace(
        close_to_new_dispatches=lambda: None,
        _agent_queues={"agent-q": SimpleNamespace(
            shutdown=_async_hook(calls, "agent_queue.shutdown", error_for("cognitive queue shutdown")),
        )},
    )
    runtime.crew_session_delivery_service = SimpleNamespace(
        close=_async_hook(calls, "crew_session_delivery.close", error_for("crew session delivery close")),
    )
    runtime.directive_store = SimpleNamespace(
        close=_sync_hook(calls, "directive_store.close", error_for("directive store close")),
    )
    runtime.ward_room = SimpleNamespace(
        is_started=False,
        stop_prune_loop=_async_hook(calls, "ward_room.stop_prune_loop", error_for("ward room prune loop stop")),
        stop=_async_hook(calls, "ward_room.stop", error_for("ward room stop")),
    )
    monkeypatch.setattr(
        shutdown_module, "_flush_audit_log",
        _async_hook(calls, "audit.flush", error_for("AD-1278 early audit flush")),
    )
    red_team_agent = RecordedService(calls, "red_team_agent", stop_raises=error_for("red team agent red-1 stop"))
    red_team_agent.id = "red-1"  # type: ignore[attr-defined]
    runtime.red_team_agents = [red_team_agent]
    monkeypatch.setattr(
        runtime.registry, "unregister",
        _async_hook(calls, "registry.unregister", error_for("red team agent red-1 unregister")),
    )
    runtime.remote_avatar_telemetry_cache = SimpleNamespace(
        clear=_sync_hook(calls, "avatar_cache.clear", error_for("remote avatar telemetry cache clear")),
    )
    monkeypatch.setattr(
        shutdown_module, "_stop_pools_and_drain_intent_bus",
        _async_hook(calls, "pools.stop_and_drain", error_for("pools stop and intent bus drain")),
    )
    monkeypatch.setattr(
        standing_orders, "set_billet_registry",
        _sync_hook(calls, "standing_orders.clear", error_for("standing-orders globals clear")),
    )
    monkeypatch.setattr(
        shutdown_module, "_close_llm_client_after_confab_probes",
        _async_hook(calls, "llm_client.close", error_for("LLM client close")),
    )
    monkeypatch.setattr(
        shutdown_module, "_drain_audit_log",
        _async_hook(calls, "audit.drain", error_for("AD-1278 audit drain")),
    )
    return runtime, errors


def _named_step_warnings(caplog: pytest.LogCaptureFixture, label: str) -> list[logging.LogRecord]:
    return [
        record for record in caplog.records
        if record.levelno == logging.WARNING and f"step {label!r}" in record.getMessage()
    ]


def test_every_guarded_step_in_shutdown_has_a_case_in_this_file() -> None:
    """A step guarded in ``shutdown()`` that no case below exercises is a guard nobody checked."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(shutdown_module.shutdown)))
    guarded: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "steps":
            (argument,) = node.args
            if isinstance(argument, ast.Constant):
                guarded.add(argument.value)
            else:  # an f-string: the red team agent's id is its only formatted part
                guarded.add("".join(
                    part.value if isinstance(part, ast.Constant) else "red-1" for part in argument.values
                ))
    guarded |= {"recreation turns stop", "cognitive queue shutdown"}  # inline in shutdown(), not ``steps``
    assert guarded == set(_ALL_STEPS), guarded ^ set(_ALL_STEPS)
    assert len(_ALL_STEPS) == len(set(_ALL_STEPS))


@pytest.mark.parametrize("label", _ALL_STEPS)
async def test_a_rollback_goes_on_past_a_teardown_step_that_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, label: str,
) -> None:
    control, _ = _stocked_runtime(tmp_path / "control", monkeypatch, rollback=True)
    await shutdown_module.shutdown(control, reason="startup_failed", rollback=True)  # type: ignore[arg-type]
    runtime, errors = _stocked_runtime(tmp_path / "failing", monkeypatch, rollback=True, failing=label)

    with caplog.at_level(logging.WARNING, logger=_SHUTDOWN_LOGGER):
        await shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True)  # type: ignore[arg-type]

    assert runtime.calls == control.calls  # every step ran, in the same order, as if nothing had failed
    named = _named_step_warnings(caplog, label)
    assert len(named) == 1, f"{label!r} was not logged exactly once"
    assert named[0].exc_info is not None and named[0].exc_info[1] is errors[label]
    assert runtime._started is False
    assert runtime._shutdown_started is True


@pytest.mark.parametrize("label", _ALL_STEPS)
async def test_without_rollback_a_teardown_step_that_raises_still_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, label: str,
) -> None:
    runtime, errors = _stocked_runtime(tmp_path, monkeypatch, rollback=False, failing=label)

    with pytest.raises(RuntimeError) as raised:
        await shutdown_module.shutdown(runtime, reason="test")  # type: ignore[arg-type]

    assert raised.value is errors[label]


async def test_a_rollback_in_which_every_step_raises_still_runs_every_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    control, _ = _stocked_runtime(tmp_path / "control", monkeypatch, rollback=True)
    await shutdown_module.shutdown(control, reason="startup_failed", rollback=True)  # type: ignore[arg-type]
    runtime, errors = _stocked_runtime(tmp_path / "failing", monkeypatch, rollback=True, everything=True)

    with caplog.at_level(logging.WARNING, logger=_SHUTDOWN_LOGGER):
        await shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True)  # type: ignore[arg-type]

    assert runtime.calls == control.calls
    for label in _ALL_STEPS:
        assert len(_named_step_warnings(caplog, label)) == 1, label
    assert runtime._started is False


async def test_a_cancelled_error_nobody_asked_for_in_a_rollback_step_is_logged_and_the_rollback_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """AD-477's stop() re-raises its own loop's cancellation by contract; that is not a request to
    stop the task that awaited it."""
    control, _ = _stocked_runtime(tmp_path / "control", monkeypatch, rollback=True)
    await shutdown_module.shutdown(control, reason="startup_failed", rollback=True)  # type: ignore[arg-type]
    runtime, _ = _stocked_runtime(
        tmp_path / "failing", monkeypatch, rollback=True, failing="ACM stop", raises=asyncio.CancelledError(),
    )

    with caplog.at_level(logging.WARNING, logger=_SHUTDOWN_LOGGER):
        await shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True)  # type: ignore[arg-type]

    assert runtime.calls == control.calls
    assert len(_named_step_warnings(caplog, "ACM stop")) == 1
    assert runtime._started is False


async def test_a_task_already_cancelled_before_the_rollback_still_gets_the_rest_of_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BF-303: the rollback of a Ctrl+C'd start runs in a task whose cancel count is above zero for
    the whole teardown, so the guard compares with the count at entry, not with zero."""
    control, _ = _stocked_runtime(tmp_path / "control", monkeypatch, rollback=True)
    await shutdown_module.shutdown(control, reason="startup_failed", rollback=True)  # type: ignore[arg-type]
    runtime, _ = _stocked_runtime(
        tmp_path / "failing", monkeypatch, rollback=True, failing="ACM stop", raises=asyncio.CancelledError(),
    )

    async def rollback_after_a_cancelled_wait() -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass  # the task keeps cancelling() == 1 from here on
        await shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True)  # type: ignore[arg-type]

    task = asyncio.create_task(rollback_after_a_cancelled_wait())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.wait_for(task, timeout=10)

    assert task.cancelling() == 1  # the premise: this is the count a naive ``== 0`` check would trip on
    assert runtime.calls == control.calls


async def test_a_cancellation_that_arrives_during_a_rollback_step_ends_the_rollback(
    tmp_path: Path,
) -> None:
    runtime = BareRuntime(tmp_path / "data", config=_no_waits(), started=False)
    entered = asyncio.Event()

    class _Blocked:
        async def stop(self) -> None:
            entered.set()
            await asyncio.Event().wait()

    runtime.acm = _Blocked()
    task = asyncio.create_task(shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True))  # type: ignore[arg-type]
    await asyncio.wait_for(entered.wait(), timeout=10)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=10)

    assert task.cancelled()
    assert "gossip.stop" not in runtime.calls  # the caller's cancellation is not swallowed by the guard


def test_without_rollback_the_step_guard_changes_nothing_and_never_reads_the_running_task() -> None:
    """Built outside any event loop: a guard that asked for the running task would raise here."""
    steps = shutdown_module._RollbackSteps(False)

    with pytest.raises(ValueError, match="propagates"):
        with steps("any step"):
            raise ValueError("propagates")
    with pytest.raises(asyncio.CancelledError):
        with steps("any step"):
            raise asyncio.CancelledError()
    with steps("any step"):
        pass


async def test_a_rollback_whose_flush_task_cannot_be_cancelled_does_not_wait_for_it_forever(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A swallowed failure of ``cancel()`` must not turn into an unbounded wait for a task that is
    still running: that would hang the very teardown that has to end."""
    runtime = BareRuntime(tmp_path / "data", config=_no_waits(), started=False)

    class _Stuck:
        awaited = False

        def cancel(self) -> None:
            raise RuntimeError("cancel refused")

        def __await__(self) -> Any:
            self.awaited = True
            return asyncio.Event().wait().__await__()

    stuck = _Stuck()
    runtime._flush_task = stuck

    with caplog.at_level(logging.WARNING, logger=_SHUTDOWN_LOGGER):
        await asyncio.wait_for(
            shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True),  # type: ignore[arg-type]
            timeout=3,
        )

    assert stuck.awaited is False  # waiting is what would hang; the old await also swallows a timeout's cancel
    assert len(_named_step_warnings(caplog, "periodic flush task cancel")) == 1
    assert runtime._started is False


_BREAKABLE_AT_THE_STARTED_ROW = ("acm", "ward_room", "pool_scaler", "task_scheduler")


@pytest.mark.parametrize("attribute", _BREAKABLE_AT_THE_STARTED_ROW)
async def test_a_real_boot_that_fails_late_is_fully_rolled_back_even_when_one_stop_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracker: SqliteTracker,
    caplog: pytest.LogCaptureFixture, attribute: str,
) -> None:
    """The review's reproducer: the ``started`` row fails (``_started`` is True, the fleet is up,
    the Yeoman holds its slot) and one component's stop() raises. Before the fix, ACM left the
    event log open, 43 pools, 70 registry entries and the slot behind."""
    broken: list[BrokenStop] = []

    with caplog.at_level(logging.WARNING, logger=_SHUTDOWN_LOGGER):
        runtime, _, baseline = await _failed_start(
            tmp_path, monkeypatch, tracker, "finalize_started_event",
            on_fire=lambda failing_runtime: broken.append(break_stop(failing_runtime, attribute)),
        )

    assert [stop.calls for stop in broken] == [1]  # the premise: the broken stop was reached, once
    assert any(
        record.levelno == logging.WARNING and record.exc_info and record.exc_info[1] is broken[0].error
        for record in caplog.records
    )
    await _assert_fully_rolled_back(runtime, baseline)
    assert runtime.event_log.is_open is False


_EVERY_BREAKABLE_COMPONENT = (
    "red_team_lead", "acm", "identity_registry", "sif", "initiative", "_counselor_profile_store",
    "_procedure_store", "_drift_scheduler", "_qualification_store", "cognitive_skill_catalog",
    "skill_service", "skill_registry", "pool_scaler", "ward_room", "gossip", "signal_manager",
    "hebbian_router", "trust_network", "event_log", "task_scheduler",
)


async def test_a_real_boot_is_fully_rolled_back_when_every_component_that_can_stop_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracker: SqliteTracker,
) -> None:
    broken: list[BrokenStop] = []

    runtime, _, baseline = await _failed_start(
        tmp_path, monkeypatch, tracker, "finalize_started_event",
        on_fire=lambda failing_runtime: broken.extend(
            break_stop(failing_runtime, attribute) for attribute in _EVERY_BREAKABLE_COMPONENT
        ),
    )

    assert {stop.attribute: stop.calls for stop in broken} == {
        attribute: 1 for attribute in _EVERY_BREAKABLE_COMPONENT
    }
    await _assert_fully_rolled_back(runtime, baseline)
    assert runtime.event_log.is_open is False


# ---------------------------------------------------------------------------
# The session record: refreshed when one exists, never created
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phase", ["after_infra", "finalize_started_event"])
async def test_a_failed_maiden_start_leaves_the_next_boot_in_the_same_directory_a_first_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracker: SqliteTracker, phase: str,
) -> None:
    """``cognitive_services`` reads ANY ``session_last.json`` as a stasis recovery. The rollback used
    to write one, so the second boot in the same directory reported ``stasis_recovery`` with
    ``previous_reason == "startup_failed"`` on a ship that had never completed a session."""
    _, failure, baseline = await _failed_start(tmp_path, monkeypatch, tracker, phase)
    failure.disarm()
    assert not (tmp_path / "data" / "session_last.json").exists()

    fresh = make_runtime(tmp_path, config=lifecycle_config(tmp_path, zero_grace=True))
    assert fresh._data_dir == tmp_path / "data"  # the premise: the same data directory
    await fresh.start()
    try:
        assert fresh._lifecycle_state == "first_boot"
        assert fresh._previous_session is None
        assert fresh._stasis_duration == 0.0
    finally:
        await fresh.stop()

    assert await baseline.leftovers() == NOTHING_LEFT


@pytest.mark.parametrize("phase", ["after_infra", "finalize_started_event"])
async def test_a_failed_start_after_a_real_session_leaves_the_next_boot_a_stasis_recovery_from_the_failed_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracker: SqliteTracker, phase: str,
) -> None:
    """BF-137's intent, kept: the rollback refreshes the record, so the next boot's stasis is counted
    from the failed start and not from a shutdown that is no longer the latest."""
    monkeypatch.chdir(tmp_path)
    record_path = tmp_path / "data" / "session_last.json"
    first = make_runtime(tmp_path, config=lifecycle_config(tmp_path, zero_grace=True))
    await first.start()
    await first.stop()  # a real session ends and writes its record
    real = json.loads(record_path.read_text(encoding="utf-8"))
    assert real["reason"] != "startup_failed"
    stale = time.time() - 86_400.0
    record_path.write_text(json.dumps({**real, "shutdown_time_utc": stale}), encoding="utf-8")
    failed_at_or_after = time.time()

    _, failure, baseline = await _failed_start(tmp_path, monkeypatch, tracker, phase)
    failure.disarm()

    refreshed = json.loads(record_path.read_text(encoding="utf-8"))
    assert refreshed["reason"] == "startup_failed"
    assert refreshed["shutdown_time_utc"] >= failed_at_or_after  # not the day-old stamp
    second = make_runtime(tmp_path, config=lifecycle_config(tmp_path, zero_grace=True))
    await second.start()
    try:
        assert second._lifecycle_state == "stasis_recovery"
        assert second._previous_session is not None
        assert second._previous_session["shutdown_time_utc"] == refreshed["shutdown_time_utc"]
        assert second._previous_session["reason"] == "startup_failed"
        assert 0.0 <= second._stasis_duration < 3600.0  # a day old if the stamp had not been refreshed
    finally:
        await second.stop()

    assert await baseline.leftovers() == NOTHING_LEFT


# ---------------------------------------------------------------------------
# The standing-orders globals live until the IntentBus has drained
# ---------------------------------------------------------------------------

def _standing_orders_globals() -> tuple[Any, Any, Any]:
    return (
        standing_orders._billet_registry, standing_orders._step_router, standing_orders._task_context,
    )


@pytest.mark.parametrize("rollback", [False, True])
async def test_an_admitted_dispatch_still_resolves_the_standing_orders_globals_until_the_drain_completes(
    tmp_path: Path, rollback: bool,
) -> None:
    """A dispatch admitted before the bus closed is still composing its prompt while the stores below
    the pools are stopped (sub_tasks/compose.py and analyze.py call ``get_step_instructions``, which
    reads these globals and silently drops the billet and step text when they are None). Measured
    at default grace before the fix: the handler saw ``billet_registry`` None with one dispatch pending."""
    runtime = BareRuntime(tmp_path / "data", config=_no_waits(), started=not rollback)
    bus = IntentBus(SignalManager())
    runtime.intent_bus = bus
    markers = (object(), object(), object())
    standing_orders.set_billet_registry(markers[0])  # type: ignore[arg-type]
    standing_orders.set_step_router(markers[1])  # type: ignore[arg-type]
    standing_orders.set_task_context(markers[2])
    handler_started = asyncio.Event()
    release = asyncio.Event()
    seen: list[tuple[Any, Any, Any]] = []

    async def handler(intent: IntentMessage) -> None:
        handler_started.set()
        await release.wait()
        seen.append(_standing_orders_globals())

    async def stop_prune_loop() -> None:
        release.set()  # runs just after the position the globals used to be cleared at

    bus.subscribe("agent-1", handler, ["probe"])
    runtime.ward_room = SimpleNamespace(
        is_started=False, stop_prune_loop=stop_prune_loop, stop=_async_recording(runtime.calls, "ward_room.stop"),
    )
    try:
        admission = await bus.dispatch_async(IntentMessage(intent="probe", target_agent_id="agent-1"))
        assert admission.admitted and admission.route == "task"  # the premise: a handler is in flight
        await asyncio.wait_for(handler_started.wait(), timeout=5)
        assert len(bus._pending_sub_tasks) == 1

        await shutdown_module.shutdown(runtime, reason="startup_failed" if rollback else "test", rollback=rollback)  # type: ignore[arg-type]

        after = _standing_orders_globals()
    finally:
        standing_orders.set_billet_registry(None)
        standing_orders.set_step_router(None)
        standing_orders.set_task_context(None)

    assert seen == [markers]  # the handler composed against live globals, after the drain began waiting on it
    assert after == (None, None, None)
    assert bus._pending_sub_tasks == set()


# ---------------------------------------------------------------------------
# Nothing a clean stop persists is persisted by a rollback
# ---------------------------------------------------------------------------

class _PersistenceSpies:
    """Records the session writes a clean stop makes, installed on a running runtime."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []
        self._monkeypatch = monkeypatch

    def _wrap(self, target: Any, name: str, label: str) -> None:
        original = getattr(target, name)

        if inspect.iscoroutinefunction(original):
            async def async_spy(*args: Any, **kwargs: Any) -> Any:
                self.calls.append(label + (f":{kwargs['title']}" if "title" in kwargs else ""))
                return await original(*args, **kwargs)

            self._monkeypatch.setattr(target, name, async_spy)
        else:
            def spy(*args: Any, **kwargs: Any) -> Any:
                self.calls.append(label)
                return original(*args, **kwargs)

            self._monkeypatch.setattr(target, name, spy)

    def watch(self, runtime: ProbOSRuntime) -> None:
        import probos.shutdown_integrity as integrity

        for name in ("mark_clean_shutdown", "mark_dirty_shutdown"):
            self._wrap(integrity, name, f"shutdown_integrity.{name}")
        knowledge = runtime._knowledge_store
        for name in (
            "store_manifest", "store_trust_snapshot", "store_routing_weights",
            "store_workflows", "store_cooldowns", "flush",
        ):
            self._wrap(knowledge, name, f"knowledge_store.{name}")
        if runtime.working_memory_store is not None:
            self._wrap(runtime.working_memory_store, "save_all", "working_memory_store.save_all")
        if runtime.ward_room is not None:
            self._wrap(runtime.ward_room, "create_thread", "ward_room.create_thread")
        if runtime.dream_scheduler is not None:
            self._wrap(runtime.dream_scheduler.engine, "consolidate_for_shutdown", "dream.consolidate_for_shutdown")
        if getattr(runtime, "audit_log", None) is not None:
            self._wrap(runtime.audit_log, "drain", "audit_log.drain")


_ALWAYS_PERSISTED_BY_A_CLEAN_STOP = (
    "knowledge_store.store_manifest",
    "knowledge_store.store_trust_snapshot",
    "knowledge_store.store_routing_weights",
    "knowledge_store.store_workflows",
    "knowledge_store.flush",
    "ward_room.create_thread:Entering Stasis",
)


async def test_a_rollback_persists_nothing_a_clean_stop_persists_and_drains_the_audit_log_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracker: SqliteTracker,
) -> None:
    monkeypatch.chdir(tmp_path)

    # The control: a real boot, stopped normally, shows what these spies can see.
    control = make_runtime(tmp_path / "control", config=lifecycle_config(tmp_path / "control", zero_grace=True))
    await control.start()
    try:
        control_spies = _PersistenceSpies(monkeypatch)
        control_spies.watch(control)
    finally:
        await control.stop()
    persisted_by_a_clean_stop = set(control_spies.calls)
    assert set(_ALWAYS_PERSISTED_BY_A_CLEAN_STOP) <= persisted_by_a_clean_stop, persisted_by_a_clean_stop
    assert any(call.startswith("shutdown_integrity.") for call in persisted_by_a_clean_stop)
    assert control_spies.calls.count("audit_log.drain") == 1

    baseline = LifecycleBaseline.capture(tracker)
    runtime = make_runtime(tmp_path / "rolled", config=lifecycle_config(tmp_path / "rolled", zero_grace=True))
    rollback_spies = _PersistenceSpies(monkeypatch)
    failure = inject_start_failure(monkeypatch, runtime, "finalize_started_event", on_fire=rollback_spies.watch)
    with pytest.raises(InjectedStartFailure):
        await runtime.start()

    assert failure.facts["started"] is True and failure.facts["audit_log_wired"] is True
    persisted_by_the_rollback = (persisted_by_a_clean_stop & set(rollback_spies.calls)) - {"audit_log.drain"}
    assert not persisted_by_the_rollback, persisted_by_the_rollback
    assert not [call for call in rollback_spies.calls if call.startswith("shutdown_integrity.")]
    assert rollback_spies.calls.count("audit_log.drain") == 1  # AD-1278 still runs
    await _assert_fully_rolled_back(runtime, baseline)


# ---------------------------------------------------------------------------
# The interpreter exits by itself
# ---------------------------------------------------------------------------

@pytest.fixture
def run_failed_start_child(tmp_path: Path) -> Any:
    """Runs tests/fixtures/failed_start_child.py in its own process and returns its report.

    The child returns from ``main`` and is left to exit by itself: a non-daemon thread left
    behind would keep the interpreter alive, and the child's faulthandler watchdog would dump
    it into ``hang_dump.txt`` and exit 1. This asserts the clean exit, an empty dump and the
    report, so every caller starts from "the process ended on its own".
    """
    import os

    def run(**extra_environment: str) -> dict[str, Any]:
        source = Path(probos.__file__).resolve().parent.parent
        hang_dump = tmp_path / "hang_dump.txt"
        work = tmp_path / "work"
        work.mkdir(exist_ok=True)
        environment = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), str(source)]),
            "PROBOS_LIFECYCLE_EXPECT_SRC": str(source),
            "PROBOS_LIFECYCLE_HANGDUMP": str(hang_dump),
            "PROBOS_DATA_DIR": str(tmp_path / "env_data"),
            "PROBOS_NATS_ENABLED": "false",
            "HF_HUB_OFFLINE": "1",
            "PROBOS_DISABLE_OVERLAY": "1",
            **extra_environment,
        }

        completed = subprocess.run(
            [sys.executable, str(_CHILD)],
            cwd=work, env=environment, capture_output=True, text=True, timeout=540,
        )

        assert completed.returncode == 0, (completed.returncode, completed.stdout[-3000:], completed.stderr[-3000:])
        assert "MAIN_DONE" in completed.stdout
        assert not hang_dump.exists() or hang_dump.read_text(encoding="utf-8") == "", hang_dump.read_text(encoding="utf-8")[:3000]
        report_line = next(line for line in completed.stdout.splitlines() if line.startswith("REPORT "))
        return json.loads(report_line.removeprefix("REPORT "))

    return run


@pytest.mark.timeout(600)
def test_a_process_that_failed_two_starts_exits_by_itself_and_boots_again(run_failed_start_child: Any) -> None:
    """Two failed starts and one good boot in one process, each in its own loop, then main
    returns. A non-daemon thread left behind would keep the interpreter alive; the child's
    faulthandler watchdog would dump it and exit 1."""
    report = run_failed_start_child()

    infra, finalize = report["failures"]
    baseline = report["baseline_yeoman"]
    assert infra["start_raised"] == "INJECTED start failure at after_infra"
    assert finalize["start_raised"] == "INJECTED start failure at finalize_started_event"
    assert finalize["facts"]["yeoman_count"] == baseline + 1  # the premise: the slot was held when it failed
    assert finalize["facts"]["started"] is True
    for failed in (infra, finalize):
        assert "error" not in failed, failed
        assert failed["started_after"] is False
        assert failed["yeoman_after"] == baseline
    assert report["boot"] == {
        "started": True, "yeoman_during": baseline + 1, "stopped": True, "yeoman_after": baseline,
    }


@pytest.mark.timeout(600)
def test_a_process_whose_rollback_met_failing_stops_still_exits_by_itself_and_boots_again(
    run_failed_start_child: Any,
) -> None:
    """The review's reproducer in a process of its own: at the ``started`` row three components'
    stop() raise (ACM, the Ward Room, the pool scaler). Before the fix the first of them aborted
    the rollback and the child hung on the aiosqlite workers it left open."""
    report = run_failed_start_child(
        PROBOS_LIFECYCLE_PHASES="finalize_started_event",
        PROBOS_LIFECYCLE_BREAK_STEPS="acm,ward_room,pool_scaler",
    )

    (finalize,) = report["failures"]
    baseline = report["baseline_yeoman"]
    assert "error" not in finalize, finalize
    assert finalize["start_raised"] == "INJECTED start failure at finalize_started_event"
    assert finalize["facts"]["yeoman_count"] == baseline + 1  # the premise: the slot was held when it failed
    assert finalize["broken_stop_calls"] == {"acm": 1, "ward_room": 1, "pool_scaler": 1}  # each broken stop ran
    assert finalize["started_after"] is False
    assert finalize["pools_after"] == 0 and finalize["registry_after"] == 0
    assert finalize["yeoman_after"] == baseline
    assert report["boot"] == {
        "started": True, "yeoman_during": baseline + 1, "stopped": True, "yeoman_after": baseline,
    }
