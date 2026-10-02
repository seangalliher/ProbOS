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
flush and drain, the event-log rows and slice A's releases included, still runs.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
import subprocess
import sys
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
from probos.runtime import ProbOSRuntime
from probos.startup import shutdown as shutdown_module
from tests.fixtures.runtime_factory import make_runtime
from tests.fixtures.runtime_lifecycle import (
    NOTHING_LEFT,
    START_FAILURE_PHASES,
    BareRuntime,
    InjectedStartFailure,
    LifecycleBaseline,
    RecordedService,
    SqliteTracker,
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
    session = json.loads((runtime._data_dir / "session_last.json").read_text(encoding="utf-8"))
    assert session["reason"] == "startup_failed"
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


@pytest.mark.parametrize(("rollback", "reason"), [(False, "tidy"), (True, "startup_failed")])
async def test_the_session_record_is_written_when_the_registry_has_agents(
    tmp_path: Path, rollback: bool, reason: str,
) -> None:
    """BF-135/BF-137: ``shutdown()`` writes the record before anything can fail. It never did
    with a non-empty registry: a function-local re-import of ``is_crew_agent`` further down
    made the name local to the whole function, so the ``agent_count`` above it raised
    UnboundLocalError, which is logged at debug and swallowed. A stop of a real booted runtime
    wrote no ``session_last.json`` at all (``__main__`` writes its own copy first)."""
    runtime = await _runtime_with_crew_and_other_agents(tmp_path)

    await shutdown_module.shutdown(runtime, reason=reason, rollback=rollback)  # type: ignore[arg-type]

    record = json.loads((runtime._data_dir / "session_last.json").read_text(encoding="utf-8"))
    assert record["reason"] == reason
    assert record["agent_count"] == 2  # architect and scout are crew; calculator is not
    assert record["session_id"] == "bare-runtime"


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

    session = json.loads((runtime._data_dir / "session_last.json").read_text(encoding="utf-8"))
    assert session["reason"] == "startup_failed"


@pytest.mark.parametrize("phase", ["after_infra", "finalize_started_event"])
async def test_after_a_rolled_back_start_stop_is_a_no_op_and_start_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracker: SqliteTracker, phase: str,
) -> None:
    runtime, _, baseline = await _failed_start(tmp_path, monkeypatch, tracker, phase)
    session_path = runtime._data_dir / "session_last.json"
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

@pytest.mark.timeout(600)
def test_a_process_that_failed_two_starts_exits_by_itself_and_boots_again(tmp_path: Path) -> None:
    """Two failed starts and one good boot in one process, each in its own loop, then main
    returns. A non-daemon thread left behind would keep the interpreter alive; the child's
    faulthandler watchdog would dump it and exit 1."""
    import os

    source = Path(probos.__file__).resolve().parent.parent
    hang_dump = tmp_path / "hang_dump.txt"
    work = tmp_path / "work"
    work.mkdir()
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), str(source)]),
        "PROBOS_LIFECYCLE_EXPECT_SRC": str(source),
        "PROBOS_LIFECYCLE_HANGDUMP": str(hang_dump),
        "PROBOS_DATA_DIR": str(tmp_path / "env_data"),
        "PROBOS_NATS_ENABLED": "false",
        "HF_HUB_OFFLINE": "1",
        "PROBOS_DISABLE_OVERLAY": "1",
    }

    completed = subprocess.run(
        [sys.executable, str(_CHILD)],
        cwd=work, env=environment, capture_output=True, text=True, timeout=540,
    )

    assert completed.returncode == 0, (completed.returncode, completed.stdout[-3000:], completed.stderr[-3000:])
    assert "MAIN_DONE" in completed.stdout
    assert not hang_dump.exists() or hang_dump.read_text(encoding="utf-8") == "", hang_dump.read_text(encoding="utf-8")[:3000]
    report_line = next(line for line in completed.stdout.splitlines() if line.startswith("REPORT "))
    report = json.loads(report_line.removeprefix("REPORT "))
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
