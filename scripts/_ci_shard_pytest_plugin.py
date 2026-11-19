"""PYTEST_DONT_REWRITE: CI shard filter and execution recorder for .github/workflows/ci.yml.

CI shard evidence is not release authority; the canonical gate
(``scripts/run_test_gate.py``) is. Load this with ``-p scripts._ci_shard_pytest_plugin``
through ``python -m pytest`` (the bare ``pytest`` command leaves the repository root off
``sys.path``) and give all of::

    --probos-shard-index K --probos-shard-count N --probos-shard-evidence-dir DIR

plus, optionally, ``--probos-shard-durations PATH``, ``--probos-shard-stack-dir DIR`` and
``--probos-shard-stall-seconds S`` (BF-985, below). Relative paths resolve against
pytest's rootpath. With none of the first three options the plugin is inert. A partial
set, an index outside 1..N, an unusable durations file, a stall bound without a stack
directory or below 1, a stack directory that is the evidence directory or inside it, or a
stack directory beside pytest's ``faulthandler_timeout`` raises ``pytest.UsageError`` from
``pytest_configure``, before xdist starts any worker.
Pytest's rootdir detection
runs before this plugin loads and reads the value after an unknown option as a path
argument, so pass explicit test paths (CI passes ``tests/``) or write ``--option=value``.

Every pytest process that runs the collection hook (each xdist worker, or the one process
under ``-n 0``) collects the whole suite, refuses to continue if another hook removed,
added or renamed an item, keeps only the files ``scripts/ci_shards.assign_files`` gives
shard K and hands the rest to ``pytest_deselected``. When its session finishes it writes
``DIR/shard-K/<gwN|main>.json`` atomically: the digests of the full collection and of the
assignment, and the node ID of every setup-phase report in execution order with repeats
kept. ``scripts/ci_shards.py verify`` turns those into the exactly-once proof. The plugin
changes no markers, scheduling, timeouts or outcomes. The xdist controller never collects,
so it never writes.

BF-985: with ``--probos-shard-stack-dir DIR`` every pytest process (the xdist controller,
or the only process under ``-n 0``, and each worker) opens
``DIR/faulthandler-<controller|gwN>.txt`` for its whole life and arms
``faulthandler.dump_traceback_later(S, repeat=True)`` on it at session start
(S = ``--probos-shard-stall-seconds``, default 600). Each test event the process sees
re-arms the timer (at most once per S/20 seconds), so the file stays empty unless the
process saw no event for about S seconds; then every thread's stack is written, and again
every S seconds while the silence lasts. The timer is re-armed after pytest's faulthandler
plugin cancels it on a failing phase, and re-armed, never cancelled, at session finish and
unconfigure, so the controller, or the one process under ``-n 0``, is dumped if it hangs in
interpreter shutdown (xdist ends a worker that is still alive 10 s after its run, so with
the default bound a worker held at exit leaves no dump); ``Py_Finalize`` cancels it on a
normal exit. The dumps live outside the evidence directory, which
``verify`` requires to hold evidence files only. The watchdog only writes: it changes no
outcome.
"""

from __future__ import annotations

import faulthandler
import re
import time
import uuid
from collections import Counter
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any, TextIO

import pytest

from scripts import ci_shards

_RECORDER_NAME = "probos-ci-shard-recorder"
_WATCHDOG_NAME = "probos-ci-stall-watchdog"
_PREVIEW_LIMIT = 5
DEFAULT_STALL_SECONDS = 600
# Each dump_traceback_later call joins the old watchdog thread and starts a new one, so a test
# event re-arms at most once per this fraction of the bound.
_REARM_FRACTION = 20
_STACK_WORKER_ID = re.compile(r"gw[0-9]{1,6}")


def _preview(nodeids: list[str]) -> str:
    shown = ", ".join(nodeids[:_PREVIEW_LIMIT])
    extra = len(nodeids) - _PREVIEW_LIMIT
    return f"[{shown}{f', ... +{extra} more' if extra > 0 else ''}]"


def _resolve(rootpath: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else rootpath / path


def _durations_label(rootpath: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(rootpath.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("probos-ci-shard", "ProbOS CI shard evidence (not release authority)")
    group.addoption(
        "--probos-shard-index",
        dest="probos_shard_index",
        type=int,
        default=None,
        metavar="K",
        help="run only shard K (1-based) of --probos-shard-count",
    )
    group.addoption(
        "--probos-shard-count",
        dest="probos_shard_count",
        type=int,
        default=None,
        metavar="N",
        help="split the collected test files into N shards",
    )
    group.addoption(
        "--probos-shard-evidence-dir",
        dest="probos_shard_evidence_dir",
        default=None,
        metavar="DIR",
        help="write shard-K/<worker>.json evidence under DIR",
    )
    group.addoption(
        "--probos-shard-durations",
        dest="probos_shard_durations",
        default=None,
        metavar="PATH",
        help=f"durations JSON for the split (default: {ci_shards.DEFAULT_DURATIONS_PATH})",
    )
    group.addoption(
        "--probos-shard-stack-dir",
        dest="probos_shard_stack_dir",
        default=None,
        metavar="DIR",
        help="arm a stall watchdog that writes every thread's stack to DIR/faulthandler-<process>.txt",
    )
    group.addoption(
        "--probos-shard-stall-seconds",
        dest="probos_shard_stall_seconds",
        type=int,
        default=None,
        metavar="S",
        help=f"seconds without a test event before a stack dump (default: {DEFAULT_STALL_SECONDS})",
    )


class ShardRecorder:
    """Keeps this process's shard of the collection and records what it executes."""

    def __init__(
        self,
        *,
        index: int,
        count: int,
        evidence_dir: Path,
        durations_label: str,
        durations: ci_shards.DurationsFile,
    ) -> None:
        self._index = index
        self._count = count
        self._evidence_dir = evidence_dir
        self._durations_label = durations_label
        self._durations = durations
        self._run_uid = uuid.uuid4().hex
        self._collection: list[str] | None = None
        self._plan: ci_shards.ShardPlan | None = None
        self._setup_reports: list[str] = []

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(
        self,
        session: pytest.Session,
        config: pytest.Config,
        items: list[pytest.Item],
    ) -> Generator[None, Any, Any]:
        before = [item.nodeid for item in items]
        result = yield
        after = [item.nodeid for item in items]
        duplicated = sorted(nodeid for nodeid, seen in Counter(before).items() if seen > 1)
        if duplicated:
            raise pytest.UsageError(
                f"CI shard plugin: the collection has duplicate node IDs {_preview(duplicated)}"
            )
        removed = sorted((Counter(before) - Counter(after)).elements())
        added = sorted((Counter(after) - Counter(before)).elements())
        if removed or added:
            raise pytest.UsageError(
                "CI shard plugin forbids another hook removing, adding or renaming "
                f"collected items (-k, -m, --deselect, --lf ...): removed {_preview(removed)}, "
                f"added {_preview(added)}"
            )
        collection = sorted(before)
        try:
            plan = ci_shards.assign_files(collection, self._durations.milliseconds, self._count)
        except ci_shards.ShardError as exc:
            raise pytest.UsageError(
                f"CI shard plugin cannot split the collection into {self._count} shards: {exc}"
            ) from exc
        kept: list[pytest.Item] = []
        dropped: list[pytest.Item] = []
        for item in items:
            owner = plan.file_shards[ci_shards.node_file(item.nodeid)]
            (kept if owner == self._index else dropped).append(item)
        items[:] = kept
        if dropped:
            config.hook.pytest_deselected(items=dropped)
        self._collection = collection
        self._plan = plan
        return result

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if self._plan is not None and report.when == "setup":
            self._setup_reports.append(report.nodeid)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self._collection is None or self._plan is None:
            return
        worker_input = getattr(session.config, "workerinput", None)
        if isinstance(worker_input, dict):
            worker_id = str(worker_input["workerid"])
            worker_count = int(worker_input["workercount"])
            testrunuid = str(worker_input["testrunuid"])
        else:
            worker_id, worker_count, testrunuid = "main", 1, self._run_uid
        payload = ci_shards.build_evidence(
            shard_index=self._index,
            shard_count=self._count,
            worker_id=worker_id,
            worker_count=worker_count,
            testrunuid=testrunuid,
            exitstatus=int(exitstatus),
            durations_path=self._durations_label,
            durations_sha256=self._durations.sha256,
            collection=self._collection,
            plan=self._plan,
            setup_reports=self._setup_reports,
        )
        ci_shards.write_evidence(self._evidence_dir, payload)


class StallWatchdog:
    """BF-985: writes every thread's stack to this process's file after a silence of the bound.

    One ``faulthandler`` dump timer exists per process, and ``dump_traceback_later`` replaces it.
    pytest's own faulthandler plugin cancels that timer in ``pytest_exception_interact``, so this
    re-arms after that hook; ``pytest_configure`` refuses ``faulthandler_timeout`` > 0 beside it,
    because pytest then arms and cancels the same timer around every test.
    """

    def __init__(
        self,
        *,
        stream: TextIO,
        stall_seconds: int,
        arm: Callable[..., None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._stream = stream
        self._stall_seconds = stall_seconds
        self._rearm_gap = stall_seconds / _REARM_FRACTION
        self._arm_timer = faulthandler.dump_traceback_later if arm is None else arm
        self._clock = clock
        self._armed_at: float | None = None

    @property
    def stream(self) -> TextIO:
        """The file the dumps go to; it stays open for the life of the process."""
        return self._stream

    @property
    def stall_seconds(self) -> int:
        return self._stall_seconds

    def arm(self) -> None:
        """Restart the timer: a dump after ``stall_seconds`` unless re-armed, then every ``stall_seconds``."""
        self._arm_timer(self._stall_seconds, repeat=True, file=self._stream)
        self._armed_at = self._clock()

    def _rearm_on_event(self) -> None:
        if self._armed_at is None or self._clock() - self._armed_at >= self._rearm_gap:
            self.arm()

    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionstart(self) -> None:
        self.arm()

    def pytest_runtest_logstart(self) -> None:
        self._rearm_on_event()

    def pytest_runtest_logreport(self) -> None:
        self._rearm_on_event()

    @pytest.hookimpl(trylast=True)
    def pytest_exception_interact(self) -> None:
        # pytest's faulthandler plugin (tryfirst) has just cancelled this process's one timer.
        self.arm()

    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionfinish(self) -> None:
        # Re-armed, never cancelled: a process can still hang after this, in another plugin's
        # session finish, in unconfigure or in interpreter shutdown.
        self.arm()

    @pytest.hookimpl(trylast=True)
    def pytest_unconfigure(self) -> None:
        # The last arm covers threading._shutdown joining a leftover non-daemon thread in the
        # controller (xdist ends a worker still alive 10 s after its run); Py_Finalize cancels
        # the timer when the process exits normally.
        self.arm()


def _stack_file(config: pytest.Config) -> Path | None:
    """Check the BF-985 options; return this process's stack file, or None without a stack directory."""
    stack_dir = config.getoption("probos_shard_stack_dir")
    stall = config.getoption("probos_shard_stall_seconds")
    if stack_dir is None:
        if stall is not None:
            raise pytest.UsageError("--probos-shard-stall-seconds needs --probos-shard-stack-dir")
        return None
    if not stack_dir.strip():
        raise pytest.UsageError("--probos-shard-stack-dir must not be empty")
    if stall is not None and stall < 1:
        raise pytest.UsageError(f"--probos-shard-stall-seconds must be >= 1, got {stall}")
    try:
        pytest_timeout = config.getini("faulthandler_timeout")
    except ValueError:  # pytest's faulthandler plugin is off (-p no:faulthandler): nothing else drives the timer
        pytest_timeout = 0.0
    if float(pytest_timeout or 0.0) > 0:
        raise pytest.UsageError(
            "--probos-shard-stack-dir cannot run with faulthandler_timeout > 0: pytest's faulthandler "
            "plugin arms and cancels the same per-process dump timer around every test"
        )
    worker_input = getattr(config, "workerinput", None)
    name = "controller"
    if isinstance(worker_input, dict):
        name = str(worker_input["workerid"])
        if _STACK_WORKER_ID.fullmatch(name) is None:
            raise pytest.UsageError(f"CI shard plugin cannot name a stack file after worker id {name!r}")
    return _resolve(config.rootpath, stack_dir) / f"faulthandler-{name}.txt"


def _open_stack_file(path: Path) -> TextIO:
    """Create the stack directory and open this process's file for the rest of its life."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # faulthandler writes to this file's descriptor from its own C thread, without the GIL, and
    # holds a reference to it; nothing closes it, so a dump during shutdown still lands.
    return path.open("w", encoding="utf-8")


def pytest_configure(config: pytest.Config) -> None:
    index = config.getoption("probos_shard_index")
    count = config.getoption("probos_shard_count")
    evidence_dir = config.getoption("probos_shard_evidence_dir")
    given = [value is not None for value in (index, count, evidence_dir)]
    if not any(given):
        return
    if not all(given):
        raise pytest.UsageError(
            "--probos-shard-index, --probos-shard-count and --probos-shard-evidence-dir "
            "must be given together"
        )
    if count < 1:
        raise pytest.UsageError(f"--probos-shard-count must be >= 1, got {count}")
    if not 1 <= index <= count:
        raise pytest.UsageError(
            f"--probos-shard-index must be within 1..{count} (--probos-shard-count), got {index}"
        )
    if not evidence_dir.strip():
        raise pytest.UsageError("--probos-shard-evidence-dir must not be empty")
    override = config.getoption("probos_shard_durations")
    durations_path = _resolve(
        config.rootpath, ci_shards.DEFAULT_DURATIONS_PATH if override is None else override
    )
    try:
        durations = ci_shards.read_durations(durations_path)
    except ci_shards.ShardError as exc:
        raise pytest.UsageError(f"CI shard plugin: {exc}") from exc
    stack_file = _stack_file(config)
    evidence_path = _resolve(config.rootpath, evidence_dir)
    if stack_file is not None and stack_file.parent.resolve().is_relative_to(evidence_path.resolve()):
        raise pytest.UsageError(
            "--probos-shard-stack-dir must not be the evidence directory or inside it: "
            "scripts/ci_shards.py verify rejects every entry there but shard-K/<worker>.json"
        )
    stream = None if stack_file is None else _open_stack_file(stack_file)
    recorder = ShardRecorder(
        index=index,
        count=count,
        evidence_dir=evidence_path,
        durations_label=_durations_label(config.rootpath, durations_path),
        durations=durations,
    )
    config.pluginmanager.register(recorder, _RECORDER_NAME)
    if stream is not None:
        stall = config.getoption("probos_shard_stall_seconds")
        watchdog = StallWatchdog(
            stream=stream,
            stall_seconds=DEFAULT_STALL_SECONDS if stall is None else stall,
        )
        config.pluginmanager.register(watchdog, _WATCHDOG_NAME)
