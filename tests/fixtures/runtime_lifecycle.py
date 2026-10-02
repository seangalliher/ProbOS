"""Runtime-lifecycle detectors and start-failure injection (BF-881 / #1452, BF-882 / #1419).

What a runtime must release, measured the way pytest and the interpreter see it:

* ``pending_tasks_since`` -- asyncio tasks created since a baseline that are still
  pending after a short settle.
* ``nondaemon_threads_since`` -- non-daemon threads (the aiosqlite workers) that would
  keep the interpreter from exiting. The loop's ``asyncio_N`` default-executor threads
  are not leaks -- ``Runner.close`` joins them -- and are excluded.
* ``SqliteTracker`` -- ``sqlite3`` connections opened on the loop thread that are still
  open. It keeps weak references only, so the tracker can never keep a leak alive.
* ``LifecycleBaseline`` -- the three detectors and the YeomanAgent slot counter taken
  together, before a boot and again after a stop or a failed start.

A detector that reports nothing is indistinguishable from one that never ran, so
tests/test_issue1452_stop_leftovers.py plants each leak and requires the detector to
see it before any "nothing is left" assertion is trusted.

``inject_start_failure`` makes ONE startup step raise (or block) and records the facts
it saw when it fired, so a test can assert its own premise: a rollback test that never
reached the phase it claims to cover proves nothing. ``break_stop`` makes a component's
``stop()`` raise, after it ran or before it did (``when=``), to prove a rollback goes on
past a teardown step that fails and then releases what that component still holds without
asking it again (``when="unkillable"`` makes any second call hang the process, to prove it).
"""

from __future__ import annotations

import asyncio
import gc
import os
import sqlite3
import threading
import weakref
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from probos.cognitive.yeoman import YeomanAgent
from probos.config import (
    ArchiveConfig,
    CaptainsLogConfig,
    MemoryConfig,
    NavalOrganizationConfig,
    ObservabilityBridgeConfig,
    PerceptionConfig,
    PlanOfDayConfig,
    SystemConfig,
    WardRoomConfig,
)
from probos.runtime import ProbOSRuntime

# The phases a start can fail in, in boot order. ``fleet_partial`` fails the 4th
# ``create_pool`` (three pools are already running); ``finalize_started_event``
# fails the ``started`` event-log row, when ``_started`` is already True.
START_FAILURE_PHASES: tuple[str, ...] = (
    "pre_infra",
    "after_infra",
    "fleet_entry",
    "fleet_partial",
    "cognitive",
    "communication",
    "finalize_started_event",
)

# The default-executor threads Runner.close() joins; never a leak.
_EXECUTOR_THREAD_PREFIX = "asyncio_"


def lifecycle_config(tmp_path: Path, *, zero_grace: bool = False) -> SystemConfig:
    """A config that turns on every loop and store BF-881 releases, rooted in ``tmp_path``.

    ``archive.db_path`` defaults to ``''``, which resolves to the LIVE vessel's archive
    in a default-config boot, so it is redirected here. Built from sub-models rather
    than by assigning into ``SystemConfig()`` defaults, so nothing is shared between
    configs. ``zero_grace`` removes the two fixed shutdown waits (AD-435, BF-296
    Phase A) for rollback tests; a normal-stop test leaves it False for production
    timing.
    """
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    memory = MemoryConfig(
        shutdown_write_grace_s=0.0, shutdown_dispatch_grace_s=0.0,
    ) if zero_grace else MemoryConfig()
    return SystemConfig(
        archive=ArchiveConfig(enabled=True, db_path=str(archive_dir / "archive.db")),
        observability_bridge=ObservabilityBridgeConfig(enabled=True),
        naval_organization=NavalOrganizationConfig(
            captains_log=CaptainsLogConfig(enabled=True),
            plan_of_day=PlanOfDayConfig(enabled=True),
        ),
        ward_room=WardRoomConfig(enabled=True),
        perception=PerceptionConfig(enabled=True, vision_consumer_enabled=True),
        memory=memory,
    )


# --------------------------------------------------------------------------- tasks


def describe_task(task: asyncio.Task[Any]) -> str:
    coroutine = task.get_coro()
    qualname = getattr(coroutine, "__qualname__", repr(coroutine))
    return f"{task.get_name()} <{qualname}>"


def _pending_tasks(before: Collection[asyncio.Task[Any]]) -> list[str]:
    current = asyncio.current_task()
    return sorted(
        describe_task(task) for task in asyncio.all_tasks()
        if task not in before and task is not current and not task.done()
    )


async def pending_tasks_since(
    before: Collection[asyncio.Task[Any]], *, settle_s: float = 0.5,
) -> list[str]:
    """Tasks created since ``before`` that are still pending, as ``name <coroutine>``.

    Waits at most ``settle_s`` for tasks that are already finishing (a cancelled loop
    needs an iteration to unwind) and returns what is left. The caller's own task is
    never reported.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + settle_s
    while True:
        left = _pending_tasks(before)
        if not left or loop.time() >= deadline:
            return left
        await asyncio.sleep(0.02)


# ------------------------------------------------------------------------- threads


def threads_now() -> frozenset[threading.Thread]:
    return frozenset(threading.enumerate())


def nondaemon_threads_since(before: Collection[threading.Thread]) -> list[str]:
    """Names of non-daemon threads started since ``before`` that are still alive.

    The main thread and the loop's ``asyncio_N`` executor threads are excluded.
    """
    main = threading.main_thread()
    return sorted(
        thread.name for thread in threading.enumerate()
        if thread not in before
        and thread is not main
        and not thread.daemon
        and not thread.name.startswith(_EXECUTOR_THREAD_PREFIX)
    )


# ------------------------------------------------------------------------- sqlite3


class _TrackedConnection(sqlite3.Connection):
    """``sqlite3.Connection`` cannot be weakly referenced; a trivial subclass can."""


class SqliteTracker:
    """Track ``sqlite3`` connections opened on the installing (loop) thread.

    Install it BEFORE the runtime is built: ``ProfileStore`` opens its connection in
    ``ProbOSRuntime.__init__``. Connections other threads open (the aiosqlite
    workers, whose threads ``nondaemon_threads_since`` reports) are not recorded. A
    connection counts as open while ``total_changes`` does not raise
    ``ProgrammingError``; a connection that was garbage collected is gone, not open.
    A caller that passes its own ``factory`` is not tracked.
    """

    def __init__(self) -> None:
        self._records: list[tuple[weakref.ref[sqlite3.Connection], str]] = []
        self._thread_id = threading.get_ident()
        self._original: Callable[..., sqlite3.Connection] | None = None

    def install(self) -> None:
        if self._original is not None:
            return
        original = sqlite3.connect
        self._original = original

        def tracked_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
            wants_default_factory = "factory" not in kwargs and len(args) < 6
            if wants_default_factory:
                kwargs["factory"] = _TrackedConnection
            connection = original(*args, **kwargs)
            if wants_default_factory and threading.get_ident() == self._thread_id:
                database = args[0] if args else kwargs.get("database", "")
                self._records.append((weakref.ref(connection), os.fsdecode(database)))
            return connection

        sqlite3.connect = tracked_connect  # type: ignore[assignment]

    def uninstall(self) -> None:
        if self._original is not None:
            sqlite3.connect = self._original  # type: ignore[assignment]
            self._original = None

    def __enter__(self) -> SqliteTracker:
        self.install()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.uninstall()

    def opened_names(self) -> list[str]:
        """Database file names of every connection recorded, open or not."""
        return sorted({Path(path).name for _, path in self._records})

    def open_connections(self) -> list[str]:
        """Database file names of the recorded connections that are still open.

        Collects first: a connection that is only unreachable garbage in a reference cycle
        has not been closed yet, but nothing can use it and it holds nothing a later
        collection will not release. Open means reachable and not closed.
        """
        gc.collect()
        still_open: list[str] = []
        for reference, path in self._records:
            connection = reference()
            if connection is None:
                continue
            try:
                connection.total_changes
            except sqlite3.ProgrammingError:
                continue
            still_open.append(Path(path).name)
        return sorted(still_open)


# ------------------------------------------------------------------------ baseline


@dataclass(frozen=True)
class LifecycleBaseline:
    """What existed before a boot, so what is left afterwards is attributable to it."""

    tasks: frozenset[asyncio.Task[Any]]
    threads: frozenset[threading.Thread]
    yeoman_count: int
    tracker: SqliteTracker

    @classmethod
    def capture(cls, tracker: SqliteTracker) -> LifecycleBaseline:
        return cls(
            tasks=frozenset(asyncio.all_tasks()),
            threads=threads_now(),
            yeoman_count=YeomanAgent._live_instance_count,
            tracker=tracker,
        )

    async def leftovers(self, *, settle_s: float = 0.5) -> dict[str, list[str]]:
        """Tasks, non-daemon threads and open loop-thread connections left since capture.

        Waits at most ``settle_s`` for what is already unwinding: a cancelled task needs a
        loop iteration, and a worker thread whose connection was closed needs a moment to
        exit. Connections are not waited for: a close is synchronous.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + settle_s
        while True:
            tasks = _pending_tasks(self.tasks)
            threads = nondaemon_threads_since(self.threads)
            if not (tasks or threads) or loop.time() >= deadline:
                break
            await asyncio.sleep(0.02)
        return {"tasks": tasks, "threads": threads, "connections": self.tracker.open_connections()}


NOTHING_LEFT: dict[str, list[str]] = {"tasks": [], "threads": [], "connections": []}


# ------------------------------------------------------------ start-failure injection


class InjectedStartFailure(RuntimeError):
    """The error ``inject_start_failure`` raises, distinct from any real failure."""


@dataclass
class StartFailure:
    """One armed injection: its error, and what the runtime looked like when it fired."""

    phase: str
    block: bool = False
    on_fire: Callable[[ProbOSRuntime], None] | None = None
    armed: bool = True
    fired: bool = False
    facts: dict[str, Any] = field(default_factory=dict)
    reached: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self.error = InjectedStartFailure(f"INJECTED start failure at {self.phase}")

    def disarm(self) -> None:
        """Let every later call through, so a second boot in the same process is clean."""
        self.armed = False

    async def fire(self, runtime: ProbOSRuntime) -> None:
        """Record the premise facts, then raise (or block until cancelled)."""
        self.armed = False
        self.fired = True
        self.facts.update(describe_runtime(runtime))
        if self.on_fire is not None:
            self.on_fire(runtime)
        self.reached.set()
        if self.block:
            await asyncio.Event().wait()
        raise self.error


def describe_runtime(runtime: ProbOSRuntime) -> dict[str, Any]:
    """The facts a premise assertion needs, read when an injection fires."""
    return {
        "started": runtime._started,
        "pools": len(runtime.pools),
        "registry_agents": runtime.registry.count,
        "yeoman_count": YeomanAgent._live_instance_count,
        "event_log_open": runtime.event_log.is_open,
        "background_tasks": len(runtime._background_tasks),
        "audit_log_wired": getattr(runtime, "audit_log", None) is not None,
    }


def inject_start_failure(
    monkeypatch: pytest.MonkeyPatch,
    runtime: ProbOSRuntime,
    phase: str,
    *,
    block: bool = False,
    on_fire: Callable[[ProbOSRuntime], None] | None = None,
) -> StartFailure:
    """Make exactly one startup step of ``runtime.start()`` raise (or block forever).

    Everything before the step really started. The returned ``StartFailure`` records
    ``facts`` when the step fires; ``reached`` is set then, which is how a test knows a
    ``block=True`` start is parked at the phase and can be cancelled. ``on_fire`` runs
    at that moment, after the facts are read, so a test can install spies exactly at
    the injection point. One-shot: the step passes through once it has fired or been
    disarmed.
    """
    if phase not in START_FAILURE_PHASES:
        raise ValueError(f"unknown start-failure phase {phase!r}; expected one of {START_FAILURE_PHASES}")
    failure = StartFailure(phase=phase, block=block, on_fire=on_fire)

    def replace_step(module_name: str, attribute: str) -> None:
        module = __import__(module_name, fromlist=[attribute])
        original = getattr(module, attribute)

        async def step(*args: Any, **kwargs: Any) -> Any:
            if failure.armed:
                await failure.fire(runtime)
            return await original(*args, **kwargs)

        monkeypatch.setattr(module, attribute, step)

    if phase == "pre_infra":
        replace_step("probos.startup.infrastructure", "boot_infrastructure")
    elif phase == "after_infra":
        replace_step("probos.startup.nats", "init_nats")
    elif phase == "fleet_entry":
        replace_step("probos.startup.agent_fleet", "create_agent_fleet")
    elif phase == "cognitive":
        replace_step("probos.startup.cognitive_services", "init_cognitive_services")
    elif phase == "communication":
        replace_step("probos.startup.communication", "init_communication")
    elif phase == "fleet_partial":
        original_create_pool = runtime.create_pool
        calls = {"count": 0}

        async def create_pool(*args: Any, **kwargs: Any) -> Any:
            calls["count"] += 1
            if failure.armed and calls["count"] == 4:
                await failure.fire(runtime)
            return await original_create_pool(*args, **kwargs)

        monkeypatch.setattr(runtime, "create_pool", create_pool)
    else:
        original_log = runtime.event_log.log

        async def log(*args: Any, **kwargs: Any) -> Any:
            if failure.armed and kwargs.get("event") == "started":
                await failure.fire(runtime)
            return await original_log(*args, **kwargs)

        monkeypatch.setattr(runtime.event_log, "log", log)
    return failure


def direct_connection_attributes(component: Any) -> list[str]:
    """The attributes of ``component`` that hold an aiosqlite or sqlite3 connection, one level deep.

    A test-side probe, written independently of the production last-resort scan so that the
    premise "this component held its connection directly when its stop failed" is not
    checked by the code it is meant to test.
    """
    import aiosqlite

    return sorted(
        name for name, value in vars(component).items()
        if isinstance(value, (aiosqlite.Connection, sqlite3.Connection))
    )


@dataclass
class BrokenStop:
    """One component whose ``stop()`` was made to raise, and what happened to it.

    ``calls`` counts every call. A rollback makes one, the step: it never asks a stop() that
    failed again. ``cleaned_up`` counts the calls on which the component's real ``stop()`` ran
    to completion before the error was raised (always 0 for ``when="before"`` and
    ``"unkillable"``). ``cancellations_ignored`` counts the cancellations an ``"unkillable"``
    stop swallowed (0 unless something called it again). ``connections`` are the attributes
    that held a sqlite connection when the break was installed, which is the premise for a
    test of what happens to those connections.
    """

    attribute: str
    error: BaseException
    when: str = "after"
    calls: int = 0
    cleaned_up: int = 0
    cancellations_ignored: int = 0
    connections: list[str] = field(default_factory=list)


def break_stop(
    runtime: Any,
    attribute: str,
    *,
    error: BaseException | None = None,
    when: str = "after",
) -> BrokenStop:
    """Make ``runtime.<attribute>.stop()`` raise, after or before it has cleaned up.

    ``when="after"``: the component really stops first, so what a test finds left behind
    afterwards is what the teardown did not reach once this step failed, not what the broken
    component itself held. ``when="before"``: the error is raised at once and the component's
    real ``stop()`` never runs, so whatever it holds (its connections and their worker
    threads) stays open unless the rollback closes it. A test that only ever breaks a stop
    ``"after"`` cannot see that: it makes zero leftovers a foregone conclusion.
    ``when="unkillable"``: as ``"before"`` for the first call, and any LATER call ignores
    every cancellation, forever. A rollback that asked it again would leave a task nothing can
    end, which ``asyncio.run`` cancels and awaits when it shuts the loop down: the process
    would never exit. Only a test in a process of its own may use it.

    Raises ``AssertionError`` if the component does not exist yet: a break that was not
    installed proves nothing, so the setup fails loudly instead of the test passing. Meant
    for ``inject_start_failure``'s ``on_fire``, when the phase's components exist.
    """
    if when not in ("after", "before", "unkillable"):
        raise ValueError(f"when must be 'after', 'before' or 'unkillable', not {when!r}")
    service = getattr(runtime, attribute, None)
    assert service is not None, f"runtime.{attribute} does not exist at this phase; nothing to break"
    original = service.stop
    broken = BrokenStop(
        attribute,
        error if error is not None else RuntimeError(f"INJECTED {attribute}.stop() failure"),
        when=when,
        connections=direct_connection_attributes(service),
    )

    async def stop(*args: Any, **kwargs: Any) -> Any:
        broken.calls += 1
        if when == "unkillable" and broken.calls > 1:
            while True:
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    broken.cancellations_ignored += 1
        if when == "after":
            await original(*args, **kwargs)
            broken.cleaned_up += 1
        raise broken.error

    service.stop = stop
    return broken


# ------------------------------------------------------------------- runtime double


class RecordedService:
    """A component double whose async ``stop()`` is recorded, and can be made to raise."""

    def __init__(self, calls: list[str], name: str, *, stop_raises: BaseException | None = None) -> None:
        self._calls = calls
        self._name = name
        self._stop_raises = stop_raises

    async def stop(self) -> None:
        self._calls.append(f"{self._name}.stop")
        if self._stop_raises is not None:
            raise self._stop_raises

    async def close(self) -> None:
        self._calls.append(f"{self._name}.close")


class RecordedEventLog:
    """An event-log double: records each row and the stop."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.events: list[str] = []

    async def log(self, *args: Any, **kwargs: Any) -> None:
        self.events.append(kwargs.get("event", ""))

    async def stop(self) -> None:
        self._calls.append("event_log.stop")


class BareRuntime:
    """The smallest runtime double ``startup.shutdown.shutdown`` runs to the end on.

    The attributes ``shutdown()`` reads without a default are real objects here, with the
    stops of the mesh and event-log components recorded in ``calls``. Every other name
    reads as ``None`` (an optional service that was never started), except the one
    ``shutdown()`` probes with ``hasattr`` (``_flush_task`` exists only after the finalize
    phase). Assign any attribute to give a step something to do.
    """

    _ABSENT = frozenset({"_flush_task"})

    def __init__(
        self,
        data_dir: Path,
        *,
        config: Any = None,
        started: bool = True,
        shutdown_started: bool = False,
    ) -> None:
        from probos.substrate.registry import AgentRegistry

        self.calls: list[str] = []
        self._data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        self._started = started
        self._shutdown_started = shutdown_started
        self._startup_complete = True
        self._session_id = "bare-runtime"
        self._start_time_wall = 0.0
        self._start_time = 0.0
        self.config = config if config is not None else SystemConfig()
        self.registry = AgentRegistry()
        self.pools: dict[str, Any] = {}
        self.red_team_agents: list[Any] = []
        self.confab_probe_tasks: set[Any] = set()
        self.gossip = RecordedService(self.calls, "gossip")
        self.signal_manager = RecordedService(self.calls, "signal_manager")
        self.hebbian_router = RecordedService(self.calls, "hebbian_router")
        self.trust_network = RecordedService(self.calls, "trust_network")
        self.llm_client = RecordedService(self.calls, "llm_client")
        self.event_log = RecordedEventLog(self.calls)

    def close_confab_probe_scheduling(self) -> None:
        self.calls.append("close_confab_probe_scheduling")

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") or name in self._ABSENT:
            raise AttributeError(name)
        return None
