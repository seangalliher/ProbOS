"""Temporary PR 1410 observation, not an acceptance gate. Remove before release."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import importlib.metadata
import inspect
import json
import math
import os
import signal
import sqlite3
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, TextIO

import aiosqlite
import pytest
import pytest_timeout


_ROOT = Path(__file__).resolve().parent.parent
_PLATFORM = sys.platform
_TEST_FILE = "tests/test_ad1192_owned_steps_store.py"
_SELECTOR = (
    _TEST_FILE + "::test_1000_admitted_rows_reach_real_storage_verdicts_with_bounded_terminal_footprint"
)
_ROWS = (0, 500, 999)
_PHASES = ("start", "submission", "review")
_CATEGORIES = ("read", "write", "begin", "commit", "rollback", "fetch", "close", "other")
_TIMINGS = (
    "enqueue_to_worker_s", "worker_wall_s", "worker_cpu_s",
    "worker_to_resume_s", "await_wall_s",
)
_IO_FIELDS = ("rchar", "wchar", "syscr", "syscw", "read_bytes", "write_bytes", "cancelled_write_bytes")
_RESOURCE_FIELDS = ("ru_maxrss", "ru_inblock", "ru_oublock", "ru_nvcsw", "ru_nivcsw")
_CONTROLS = (
    "PROBOS_GATE_COLLECTION_DIR", "PYTEST_ADDOPTS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    "PYTEST_PLUGINS", "PYTEST_TIMEOUT", "PYTHONPYCACHEPREFIX", "PYTHONOPTIMIZE",
)
_CODES = frozenset("""
    complete incomplete arguments assertions platform imports settings collection execution
    skipped xfailed premise sequence result timeout cancelled assertion sqlite pytest_failure
    interrupted internal_error test_error output_bounds output_privacy output_protocol
    not_observed not_started not_run not_reached partial clock_unavailable os_unavailable
    os_invalid db_missing db_busy db_unreadable db_query_bound db_invalid
    teardown_not_observed durable_mismatch
""".split())
_WORDS = _CODES | frozenset("""
    record diagnostic acceptance mode post_suite_serial begin admission window failure_state finish
    selector python implementation cpython pypy other linux win32 darwin platform versions
    pytest pytest_asyncio pytest_timeout aiosqlite sqlite limits job_s step_s required_timeout_s
    effective_timeout value reason timing_columns enqueue_includes_overhead
    concurrent_xdist_reproduction machine_idle_asserted os_accounting_not_physical_disk
    requested returned active_rows rows mode_active premises_ok
    row population complete wall_s process_cpu_s main_cpu_s sql os
    submitted worker_started worker_finished await_resumed measured sum_s max_s missing
    peak_rss_kib resource_delta io_delta captured_before_teardown task await_chain truncated
    pending done cancelled capacity observer probos asyncio awaitable line kind
    current_row current_phase completed attempted returned_transitions missing_windows operation
    initial_snapshot after_start after_submission after_review final_assertions
    setup call teardown reports report_counts protocols calls collected deselected
    pytest_exit code problem test_error durable counts children verified tokens journal_total
    operation permit submission review seconds method scope signal whole_test observed
    error unavailable
""".split()) | set(_CATEGORIES + _TIMINGS + _PHASES + _IO_FIELDS + _RESOURCE_FIELDS) | {
    _SELECTOR, "passed", "failed", "skipped",
}
_SCOPE: contextvars.ContextVar[_Window | None] = contextvars.ContextVar("owned_capacity", default=None)


class _Fault(Exception):
    def __init__(self, code: str) -> None:
        if code not in _CODES or code == "complete":
            code = "internal_error"
        self.code = code
        super().__init__(code)


def _metric(value: Any, reason: str = "not_observed") -> dict[str, Any]:
    return {"value": value, "reason": reason if value is None else None}


def _safe(value: Any) -> bool:
    if value is None or type(value) is bool:
        return True
    if type(value) is int:
        return abs(value) < 2**63
    if type(value) is float:
        return math.isfinite(value) and abs(value) < 2**63
    if type(value) is str:
        return value in _WORDS
    if type(value) in (list, tuple):
        return len(value) <= 32 and all(_safe(item) for item in value)
    if type(value) is dict:
        return len(value) <= 40 and all(key in _WORDS and _safe(item) for key, item in value.items())
    return False


class _Output:
    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self.records = 0
        self.bytes = 0
        self.finished = False

    def emit(self, kind: str, **fields: Any) -> None:
        if (
            self.finished or kind not in {"begin", "admission", "window", "failure_state", "finish"}
            or (self.records == 0) != (kind == "begin")
            or {"record", "diagnostic", "acceptance"} & fields.keys()
        ):
            raise _Fault("output_protocol")
        record = {"record": kind, "diagnostic": True, "acceptance": False, **fields}
        if not _safe(record):
            raise _Fault("output_privacy")
        line = json.dumps(record, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n"
        size = len(line.encode("ascii"))
        terminal = kind == "finish"
        if size > 4096 or self.records >= (8 if terminal else 7) or (
            self.bytes + size > (32768 if terminal else 32768 - 4096)
        ):
            raise _Fault("output_bounds")
        self.stream.write(line)
        self.stream.flush()
        self.records += 1
        self.bytes += size
        self.finished = terminal


@contextlib.contextmanager
def _quiet_channel(*, restore: bool = True) -> Iterator[TextIO]:
    # A duplicated descriptor survives pytest capture and the timeout terminal writer.
    stdout, stderr = sys.stdout, sys.stderr
    stdout.flush()
    stderr.flush()
    saved = (os.dup(1), os.dup(2))
    try:
        with os.fdopen(os.dup(1), "w", encoding="ascii", buffering=1) as channel:
            with open(os.devnull, "w", encoding="utf-8") as sink:
                try:
                    os.dup2(sink.fileno(), 1)
                    os.dup2(sink.fileno(), 2)
                    sys.stdout = sys.stderr = sink
                    yield channel
                finally:
                    sink.flush()
                    if restore:
                        os.dup2(saved[0], 1)
                        os.dup2(saved[1], 2)
                    sys.stdout, sys.stderr = stdout, stderr
    finally:
        for descriptor in saved:
            os.close(descriptor)


@contextlib.contextmanager
def _local_controls() -> Iterator[None]:
    prior = {name: os.environ.get(name) for name in _CONTROLS}
    path, cwd, bytecode = sys.path[:], Path.cwd(), sys.dont_write_bytecode
    try:
        for name in _CONTROLS:
            os.environ.pop(name, None)
        sys.path[:0] = [str(_ROOT / "src"), str(_ROOT)]
        sys.dont_write_bytecode = True
        os.chdir(_ROOT)
        yield
    finally:
        sys.path[:] = path
        sys.dont_write_bytecode = bytecode
        os.chdir(cwd)
        for name, value in prior.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _version(name: str) -> dict[str, Any]:
    try:
        parts = importlib.metadata.version(name).split(".")
    except (importlib.metadata.PackageNotFoundError, OSError):
        return _metric(None, "imports")
    if not 2 <= len(parts) <= 4 or not all(part.isascii() and part.isdigit() and len(part) <= 3 for part in parts):
        return _metric(None, "imports")
    return _metric([int(part) for part in parts])


def _thread_cpu() -> float | None:
    try:
        return time.thread_time()
    except (AttributeError, OSError):
        return None


def _os_counters() -> dict[str, Any]:
    resource_values = io_values = None
    resource_reason = io_reason = "os_unavailable"
    if _PLATFORM == "linux":
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            resource_values = {key: int(getattr(usage, key)) for key in _RESOURCE_FIELDS}
        except (ImportError, OSError, ValueError):
            pass  # Optional numeric evidence; the explicit unavailable reason is retained.
        try:
            with open("/proc/self/io", encoding="ascii") as source:
                text = source.read(1025)
            if len(text) > 1024:
                raise ValueError
            parsed = dict(line.split(":", 1) for line in text.splitlines())
            io_values = {key: int(parsed[key]) for key in _IO_FIELDS}
        except OSError:
            pass
        except (UnicodeError, ValueError, KeyError):
            io_reason = "os_invalid"
    return {"resource_delta": _metric(resource_values, resource_reason), "io_delta": _metric(io_values, io_reason)}


def _os_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    result = {}
    resource = after["resource_delta"]["value"]
    result["peak_rss_kib"] = _metric(None if resource is None else resource["ru_maxrss"], after["resource_delta"]["reason"])
    for group in ("resource_delta", "io_delta"):
        first, last = before[group]["value"], after[group]["value"]
        result[group] = _metric(
            None if first is None or last is None else {
                key: last[key] - first[key] for key in last if key != "ru_maxrss"
            },
            before[group]["reason"] or after[group]["reason"],
        )
    return result


def _category(fn: Callable[..., Any], args: tuple[Any, ...]) -> str:
    name = getattr(fn, "__name__", "")
    if name in {"commit", "rollback", "close"}:
        return name
    if name in {"fetchone", "fetchall", "fetchmany"}:
        return "fetch"
    if name in {"execute", "executemany", "executescript", "_execute_insert", "_execute_fetchall"} and args and isinstance(args[0], str):
        verb = args[0].lstrip()[:16].split(maxsplit=1)
        word = verb[0].upper() if verb else ""
        if word in {"SELECT", "EXPLAIN"}:
            return "read"
        if word in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER"}:
            return "write"
        if word in {"BEGIN", "COMMIT", "ROLLBACK"}:
            return word.lower()
    return "other"


def _empty_stats() -> dict[str, Any]:
    return {
        "submitted": 0, "worker_started": 0, "worker_finished": 0, "await_resumed": 0,
        "measured": [0] * 5, "sum_s": [0.0] * 5, "max_s": [0.0] * 5,
    }


class _Window:
    def __init__(self, row: int, population: int, task: asyncio.Task[Any] | None) -> None:
        self.row, self.population, self.task = row, population, task
        self.start = (time.perf_counter(), time.process_time(), _thread_cpu())
        self.os_start = _os_counters()
        self.end: tuple[float, float, float | None] | None = None
        self.os_end: dict[str, Any] | None = None
        self.complete = False
        self.lock = threading.Lock()
        self.stats: dict[str, dict[str, Any]] = {}
        self.last: dict[str, Any] | None = None
        self.frozen = False

    def stop(self, complete: bool) -> None:
        if self.end is None:
            self.end = (time.perf_counter(), time.process_time(), _thread_cpu())
            self.os_end = _os_counters()
            self.complete = complete

    def mark(self, operation: dict[str, Any], stage: str, stamp: float, cpu: float | None = None) -> None:
        with self.lock:
            if self.frozen:
                return
            operation[stage] = stamp
            if stage == "worker_started":
                operation["cpu"] = cpu
            category = operation["kind"]
            if category not in self.stats:
                self.stats[category] = _empty_stats()
            aggregate = self.stats[category]
            aggregate[stage] += 1
            if stage == "submitted":
                self.last = operation
            values: dict[int, float] = {}
            if stage == "worker_started":
                values[0] = stamp - operation["submitted"]
            elif stage == "worker_finished":
                values[1] = stamp - operation["worker_started"]
                if cpu is not None and operation.get("cpu") is not None:
                    values[2] = cpu - operation["cpu"]
            elif stage == "await_resumed":
                values[4] = stamp - operation["submitted"]
                if "worker_finished" in operation:
                    values[3] = stamp - operation["worker_finished"]
            for index, value in values.items():
                aggregate["measured"][index] += 1
                aggregate["sum_s"][index] += value
                aggregate["max_s"][index] = max(aggregate["max_s"][index], value)

    def operation_state(self) -> dict[str, Any]:
        with self.lock:
            return _metric(None) if self.last is None else _metric({
                "kind": self.last["kind"],
                **{key: key in self.last for key in ("submitted", "worker_started", "worker_finished", "await_resumed")},
            })

    def report(self) -> dict[str, Any]:
        self.stop(False)
        assert self.end is not None and self.os_end is not None
        with self.lock:
            self.frozen = True
            sql = {
                category: {
                    **{key: value for key, value in aggregate.items() if key not in {"sum_s", "max_s"}},
                    **{key: [round(value, 6) if count else None for value, count in zip(aggregate[key], aggregate["measured"])]
                       for key in ("sum_s", "max_s")},
                    "missing": [
                        None if count and count == aggregate["submitted"] else "partial" if count
                        else "clock_unavailable" if index == 2 and aggregate["worker_finished"]
                        else "not_observed"
                        for index, count in enumerate(aggregate["measured"])
                    ],
                }
                for category in _CATEGORIES
                for aggregate in (self.stats.get(category, _empty_stats()),)
            }
        return {
            "row": self.row, "population": self.population, "complete": self.complete,
            **{key: _metric(None if start is None or end is None else round(end - start, 6), "clock_unavailable")
               for key, start, end in zip(("wall_s", "process_cpu_s", "main_cpu_s"), self.start, self.end)},
            "sql": sql, "os": _os_delta(self.os_start, self.os_end),
        }


def _error(exc: BaseException) -> str:
    if isinstance(exc, _Fault):
        return exc.code
    traceback = exc.__traceback__
    for _ in range(64):
        if traceback is None:
            break
        if traceback.tb_frame.f_code is pytest_timeout.timeout_sigalrm.__code__:
            return "timeout"
        traceback = traceback.tb_next
    for kind, code in (
        (asyncio.CancelledError, "cancelled"), (KeyboardInterrupt, "interrupted"),
        (ImportError, "imports"),
        (AssertionError, "assertion"), (sqlite3.Error, "sqlite"),
        (pytest.fail.Exception, "pytest_failure"),
    ):
        if isinstance(exc, kind):
            return code
    return "test_error"


def _task_state(task: asyncio.Task[Any] | None) -> dict[str, Any]:
    if task is None:
        return _metric(None, "not_started")
    chain = []
    coroutine = task.get_coro()
    for _ in range(12):
        if coroutine is None:
            break
        code = getattr(coroutine, "cr_code", getattr(coroutine, "gi_code", None))
        kind = "awaitable"
        if code is not None:
            filename = Path(code.co_filename).resolve()
            kind = (
                "capacity" if filename == _ROOT / _TEST_FILE
                else "observer" if filename == Path(__file__).resolve()
                else "probos" if filename.is_relative_to(_ROOT / "src" / "probos")
                else "sqlite" if "aiosqlite" in filename.parts
                else "asyncio" if "asyncio" in filename.parts else "other"
            )
        chain.append({"kind": kind, "line": _metric(code.co_firstlineno if code is not None else None)})
        coroutine = getattr(coroutine, "cr_await", getattr(coroutine, "gi_yieldfrom", None))
    return _metric({
        "task": "cancelled" if task.cancelled() else "done" if task.done() else "pending",
        "await_chain": chain, "truncated": coroutine is not None,
    })


class _Observation:
    def __init__(self) -> None:
        self.requested: int | None = None
        self.children: int | None = None
        self.active: int | None = None
        self.rows: int | None = None
        self.mode_active = False
        self.admissions = 0
        self.attempted = [0, 0, 0]
        self.returned = [0, 0, 0]
        self.completed = self.next_phase = 0
        self.row: int | None = None
        self.phase = "not_started"
        self.problem: str | None = None
        self.test_error: str | None = None
        self.task: asyncio.Task[Any] | None = None
        self.path: Path | None = None
        self.windows: dict[int, _Window] = {}

    def reject(self, code: str) -> None:
        self.problem = self.problem or code

    def premises(self) -> bool:
        return self.admissions == 1 and self.requested == self.children == self.active == self.rows == 1000 and self.mode_active

    @contextlib.contextmanager
    def intercept(self, module: ModuleType) -> Iterator[None]:
        legacy, apply, execute = module._legacy_plan, module._apply, aiosqlite.Connection._execute

        @functools.wraps(legacy)
        async def admission(*args: Any, **kwargs: Any) -> Any:
            self.admissions += 1
            self.task = asyncio.current_task()
            harness = args[0] if args else kwargs["harness"]
            self.path = Path(harness.path)
            requested = kwargs.get("children_count", 2)
            self.requested = requested if type(requested) is int else None
            self.phase = "admission"
            result = await legacy(*args, **kwargs)
            self.children = len(result[1])
            if result[0].id != "parent-1" or self.requested != 1000 or self.children != 1000:
                self.reject("premise")
            self.phase = "initial_snapshot"
            return result

        @functools.wraps(apply)
        async def transition(harness: Any, snapshot: Any, index: int, command: Any, **kwargs: Any) -> Any:
            kinds = (module.steps.StartOwnedStepCommand, module.steps.SubmitOwnedStepCommand, module.steps.ReviewOwnedStepCommand)
            phase = next((i for i, kind in enumerate(kinds) if isinstance(command, kind)), None)
            self.row = index if type(index) is int and 0 <= index < 1000 else None
            self.phase = _PHASES[phase] if phase is not None else "other"
            if not any(self.attempted):
                self.rows = len(snapshot.control.rows)
                self.active = sum(row.kind == "child" and row.permit_state == "unstarted" for row in snapshot.control.rows)
                self.mode_active = snapshot.control.mode == "active"
                if not self.premises():
                    self.reject("premise")
            ordered = phase is not None and self.row == self.completed and phase == self.next_phase and asyncio.current_task() is self.task
            if not ordered:
                self.reject("sequence")
            if phase is not None:
                self.attempted[phase] += 1
            if ordered and phase == 0 and index in _ROWS and index not in self.windows:
                self.windows[index] = _Window(index, self.completed, self.task)
            window = self.windows.get(index) if ordered else None
            token = _SCOPE.set(window)
            try:
                result = await apply(harness, snapshot, index, command, **kwargs)
                if phase is not None:
                    self.returned[phase] += 1
                if ordered:
                    changed = result[0].snapshot
                    row = changed.control.rows[index] if changed is not None and index < len(changed.control.rows) else None
                    valid = row is not None and row.permit_state == ("started", "submitted", "terminal")[phase]
                    valid = valid and (phase != 0 or result[0].disposition == "new")
                    valid = valid and (phase != 2 or row.review_accepted is True)
                    if not valid:
                        self.reject("result")
                    else:
                        self.next_phase = (phase + 1) % 3
                        if phase == 2:
                            self.completed += 1
                            if window is not None:
                                window.stop(True)
                self.phase = (
                    "final_assertions" if self.completed == 1000
                    else "after_" + _PHASES[phase] if phase is not None else "other"
                )
                return result
            except BaseException as exc:
                self.test_error = _error(exc)
                if window is not None:
                    window.stop(False)
                raise
            finally:
                _SCOPE.reset(token)

        async def measured(connection: aiosqlite.Connection, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            window = _SCOPE.get()
            if window is None or asyncio.current_task() is not window.task:
                return await execute(connection, fn, *args, **kwargs)
            operation: dict[str, Any] = {"kind": _category(fn, args)}

            def worker(*worker_args: Any, **worker_kwargs: Any) -> Any:
                window.mark(operation, "worker_started", time.perf_counter(), _thread_cpu())
                try:
                    return fn(*worker_args, **worker_kwargs)
                finally:
                    window.mark(operation, "worker_finished", time.perf_counter(), _thread_cpu())

            window.mark(operation, "submitted", time.perf_counter())
            try:
                return await execute(connection, worker, *args, **kwargs)
            finally:
                window.mark(operation, "await_resumed", time.perf_counter())

        with contextlib.ExitStack() as stack:
            for obj, name, replacement in (
                (module, "_legacy_plan", admission), (module, "_apply", transition),
                (aiosqlite.Connection, "_execute", measured),
            ):
                stack.callback(setattr, obj, name, getattr(obj, name))
                setattr(obj, name, replacement)
            yield


def _origins(item: pytest.Item) -> None:
    expected = _ROOT / _TEST_FILE
    module = item.module
    if Path(module.__file__).resolve() != expected:
        raise _Fault("imports")
    for function in (item.obj, module._legacy_plan, module._apply, module.stores):
        if Path(inspect.unwrap(function).__code__.co_filename).resolve() != expected:
            raise _Fault("imports")
    for name, loaded in tuple(sys.modules.items()):
        if name == "probos" or name.startswith("probos.") or name == "tests" or name.startswith("tests."):
            filename = getattr(loaded, "__file__", None)
            root = _ROOT / "src" / "probos" if name.startswith("probos") else _ROOT / "tests"
            if filename is None or not Path(filename).resolve().is_relative_to(root):
                raise _Fault("imports")
    if aiosqlite.__version__ != "0.22.1" or tuple(inspect.signature(aiosqlite.Connection._execute).parameters) != ("self", "fn", "args", "kwargs"):
        raise _Fault("imports")


class _Plugin:
    def __init__(self, output: _Output, stack: contextlib.ExitStack) -> None:
        self.output, self.stack = output, stack
        self.observation = _Observation()
        self.collected = self.deselected = self.protocols = self.calls = 0
        self.before_collection = False
        self.collection_ok = False
        self.timer: dict[str, Any] | None = None
        self.reports = {phase: None for phase in ("setup", "call", "teardown")}
        self.report_counts = {phase: 0 for phase in self.reports}
        self.captured = False

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> Any:
        self.before_collection = len(items) == 1 and items[0].nodeid == _SELECTOR
        yield
        if not self.before_collection or len(items) != 1 or items[0].nodeid != _SELECTOR:
            raise _Fault("collection")

    def pytest_deselected(self, items: list[pytest.Item]) -> None:
        self.deselected += len(items)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_collection_finish(self, session: pytest.Session) -> Any:
        yield
        self.collected = len(session.items)
        config = session.config
        if (
            not self.before_collection or self.deselected or self.collected != 1
            or session.items[0].nodeid != _SELECTOR
        ):
            raise _Fault("collection")
        if (
            config.option.collectonly or config.option.numprocesses != 0
            or config.option.keyword or config.option.markexpr
            or not config.pluginmanager.hasplugin("terminalreporter")
            or config.pluginmanager.hasplugin("randomly")
        ):
            raise _Fault("settings")
        _origins(session.items[0])
        self.stack.enter_context(self.observation.intercept(session.items[0].module))
        self.collection_ok = True

    @pytest.hookimpl(hookwrapper=True, tryfirst=True, optionalhook=True)
    def pytest_timeout_set_timer(self, item: pytest.Item, settings: Any) -> Any:
        implementations = item.config.pluginmanager.hook.pytest_timeout_set_timer.get_hookimpls()
        if (
            self.timer is not None or settings.timeout != 180 or settings.method != "signal"
            or settings.func_only is not False or _PLATFORM != "linux"
            or threading.current_thread() is not threading.main_thread()
            or pytest_timeout.is_debugging()
            or [hook.function for hook in implementations if not hook.hookwrapper and not hook.wrapper]
            != [pytest_timeout.pytest_timeout_set_timer]
        ):
            raise _Fault("settings")
        outcome = yield
        handler = signal.getsignal(signal.SIGALRM)
        remaining, interval = signal.getitimer(signal.ITIMER_REAL)
        if (
            outcome.get_result() is not True or not 0 < remaining <= 180 or interval != 0
            or not callable(handler) or getattr(handler, "__module__", None) != "pytest_timeout"
            or not callable(getattr(item, "cancel_timeout", None))
        ):
            raise _Fault("settings")
        self.timer = {"seconds": 180, "method": "signal", "scope": "whole_test", "observed": True}

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_protocol(self, item: pytest.Item) -> None:
        self.protocols += 1
        if not self.collection_ok or item.nodeid != _SELECTOR or self.protocols != 1:
            raise _Fault("execution")

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_call(self, item: pytest.Item) -> None:
        self.calls += 1
        if self.timer is None or self.calls != 1 or item.nodeid != _SELECTOR:
            raise _Fault("execution")

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: pytest.CallInfo[Any]) -> Any:
        if call.excinfo is not None:
            self.observation.test_error = _error(call.excinfo.value)
        report = yield
        self.reports[report.when] = report.outcome
        self.report_counts[report.when] += 1
        if report.skipped:
            self.observation.reject("skipped")
        if hasattr(report, "wasxfail"):
            self.observation.reject("xfailed")
        return report

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_teardown(self, item: pytest.Item) -> None:
        self.capture(True)

    def pytest_internalerror(self, excrepr: Any, excinfo: pytest.ExceptionInfo[BaseException]) -> None:
        self.observation.reject(_error(excinfo.value))

    def pytest_keyboard_interrupt(self, excinfo: pytest.ExceptionInfo[BaseException]) -> None:
        self.observation.test_error = _error(excinfo.value)

    def capture(self, before_teardown: bool) -> None:
        if self.captured:
            return
        self.captured = True
        observed = self.observation
        task = _task_state(observed.task)
        current = observed.windows.get(observed.row)
        operation = _metric(None) if current is None else current.operation_state()
        self.output.emit(
            "admission", requested=_metric(observed.requested), returned=_metric(observed.children),
            active_rows=_metric(observed.active), rows=_metric(observed.rows),
            mode_active=observed.mode_active, premises_ok=observed.premises(),
        )
        for window in observed.windows.values():
            self.output.emit("window", **window.report())
        self.output.emit(
            "failure_state", captured_before_teardown=before_teardown,
            task=task, current_row=_metric(observed.row, "not_started"), current_phase=observed.phase,
            completed=observed.completed, operation=operation,
            missing_windows={"value": [row for row in _ROWS if row not in observed.windows],
                             "reason": "not_reached" if len(observed.windows) != 3 else None},
        )


_AGGREGATE_SQL = """
SELECT c.children, c.verified, c.tokens, j.operation, j.permit, j.submission, j.review, j.total
FROM (SELECT COUNT(*) children,
             COALESCE(SUM(json_extract(verification, '$.accepted') = 1), 0) verified,
             COALESCE(SUM(actual_tokens), 0) tokens
      FROM work_items WHERE parent_id = 'parent-1') c
CROSS JOIN (SELECT COALESCE(SUM(kind = 'operation'), 0) operation,
                   COALESCE(SUM(kind = 'permit'), 0) permit,
                   COALESCE(SUM(kind = 'submission'), 0) submission,
                   COALESCE(SUM(kind = 'review'), 0) review, COUNT(*) total
            FROM owned_steps_journal) j
"""
_COUNT_KEYS = ("children", "verified", "tokens", "operation", "permit", "submission", "review", "journal_total")
_EXPECTED_COUNTS = dict(zip(_COUNT_KEYS, (1000, 1000, 1000, 3000, 1000, 1000, 1000, 6000)))


def _snapshot(path: Path | None) -> dict[str, Any]:
    started, instructions = time.perf_counter(), 0

    def progress() -> int:
        nonlocal instructions
        instructions += 1000
        return int(instructions >= 500_000 or time.perf_counter() - started >= 0.1)

    try:
        if path is None or not path.is_file():
            return _metric(None, "db_missing")
        with contextlib.closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.0)) as db:
            db.set_progress_handler(progress, 1000)
            row = db.execute(_AGGREGATE_SQL).fetchone()
            if row is None or len(row) != len(_COUNT_KEYS):
                return _metric(None, "db_invalid")
            counts = dict(zip(_COUNT_KEYS, row))
            if any(type(value) is not int or not 0 <= value < 2**63 for value in counts.values()):
                return _metric(None, "db_invalid")
            return _metric(counts)
    except sqlite3.Error as exc:
        code = getattr(exc, "sqlite_errorcode", 0) & 255
        reason = {sqlite3.SQLITE_BUSY: "db_busy", sqlite3.SQLITE_LOCKED: "db_busy", sqlite3.SQLITE_INTERRUPT: "db_query_bound"}.get(code, "db_unreadable")
        return _metric(None, reason)
    except OSError:
        return _metric(None, "db_unreadable")


def _finish(plugin: _Plugin, exit_code: int | None, durable: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    observed = plugin.observation
    protocol_ok = (
        plugin.collection_ok and plugin.collected == 1 and plugin.deselected == 0
        and plugin.protocols == plugin.calls == 1 and plugin.timer is not None
        and all(value == "passed" for value in plugin.reports.values())
        and all(value == 1 for value in plugin.report_counts.values())
    )
    workload_ok = (
        observed.premises() and observed.completed == 1000 and observed.next_phase == 0
        and observed.attempted == observed.returned == [1000, 1000, 1000]
        and tuple(observed.windows) == _ROWS
        and all(
            window.complete and window.population == row and window.stats
            and all(stat["submitted"] == stat["worker_started"] == stat["worker_finished"] == stat["await_resumed"] > 0
                    for stat in window.stats.values())
            for row, window in observed.windows.items()
        )
    )
    code = observed.problem or observed.test_error
    if code is None:
        code = (
            "execution" if not protocol_ok else "incomplete" if not workload_ok
            else durable["reason"] if durable["value"] is None
            else "durable_mismatch" if durable["value"] != _EXPECTED_COUNTS
            else "complete" if exit_code == 0 else "incomplete"
        )
    complete = (
        code == "complete" and exit_code == 0 and protocol_ok and workload_ok
        and durable["value"] == _EXPECTED_COUNTS and not observed.problem and not observed.test_error
    )
    return (0 if complete else 2), {
        "complete": complete, "code": code, "problem": observed.problem, "test_error": observed.test_error,
        "timeout": observed.test_error == "timeout", "interrupted": observed.test_error == "interrupted",
        "cancelled": observed.test_error == "cancelled",
        "pytest_exit": _metric(exit_code, "not_run"), "effective_timeout": _metric(plugin.timer),
        "collected": plugin.collected, "deselected": plugin.deselected,
        "protocols": plugin.protocols, "calls": plugin.calls,
        "reports": {key: _metric(value, "not_run") for key, value in plugin.reports.items()},
        "report_counts": plugin.report_counts,
        "attempted": dict(zip(_PHASES, observed.attempted)),
        "returned_transitions": dict(zip(_PHASES, observed.returned)),
        "completed": observed.completed, "durable": durable,
    }


def _run(output: _Output) -> int:
    versions = {name.replace("-", "_"): _version(name) for name in ("pytest", "pytest-asyncio", "pytest-timeout", "aiosqlite")}
    output.emit(
        "begin", mode="post_suite_serial", selector=_SELECTOR,
        platform=_PLATFORM if _PLATFORM in {"linux", "win32", "darwin"} else "other",
        python=list(sys.version_info[:3]),
        implementation=sys.implementation.name if sys.implementation.name in {"cpython", "pypy"} else "other",
        versions=versions,
        sqlite=list(sqlite3.sqlite_version_info),
        limits={"job_s": 2700, "step_s": 240, "required_timeout_s": 180},
        effective_timeout=_metric(None), timing_columns=_TIMINGS,
        enqueue_includes_overhead=True, concurrent_xdist_reproduction=False,
        machine_idle_asserted=False, os_accounting_not_physical_disk=True,
    )
    exit_code = None
    with contextlib.ExitStack() as stack:
        plugin = _Plugin(output, stack)
        try:
            if len(sys.argv) != 1:
                raise _Fault("arguments")
            if not __debug__ or sys.flags.optimize:
                raise _Fault("assertions")
            if _PLATFORM != "linux":
                raise _Fault("platform")
            if any(version["value"] is None for version in versions.values()):
                raise _Fault("imports")
            with _local_controls():
                exit_code = int(pytest.main([
                    _SELECTOR, "-c", str(_ROOT / "pyproject.toml"), "--rootdir", str(_ROOT),
                    "-o", "addopts=", "-n", "0", "-p", "no:randomly", "--capture=no",
                    "--tb=no", "--show-capture=no", "-q",
                ], plugins=[plugin]))
        except BaseException as exc:
            plugin.observation.reject(_error(exc))
    try:
        plugin.capture(False)
        durable = _snapshot(plugin.observation.path) if plugin.report_counts["teardown"] else _metric(None, "teardown_not_observed")
        result, fields = _finish(plugin, exit_code, durable)
        output.emit("finish", **fields)
        return result
    except _Fault as exc:
        output.emit("finish", complete=False, code=exc.code)
        return 2


def main() -> int:
    # An executable also mutes late interpreter/atexit output; embedded calls restore descriptors.
    with _quiet_channel(restore=__name__ != "__main__") as channel:
        output = _Output(channel)
        try:
            return _run(output)
        except BaseException as exc:
            if not output.finished:
                if output.records == 0:
                    output.emit("begin")
                output.emit("finish", complete=False, code=_error(exc))
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
