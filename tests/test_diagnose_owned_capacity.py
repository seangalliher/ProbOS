"""Small probes for the temporary observer; never execute the capacity workload."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import importlib.util
import io
import itertools
import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import aiosqlite
import pytest
import pytest_timeout


ROOT = Path(__file__).resolve().parent.parent
BASE = "7767887f8fa7cae3ccd3d2777bef0a2649e92159"
SECRET = "SENTINEL_PRIVATE_PAYLOAD_do_not_emit"


@pytest.fixture(scope="module")
def diagnostic() -> Iterator[ModuleType]:
    path = ROOT / "scripts" / "diagnose_owned_capacity.py"
    spec = importlib.util.spec_from_file_location("owned_capacity_unit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        assert module._ROOT == ROOT
        import probos
        assert Path(probos.__file__).resolve() == ROOT / "src" / "probos" / "__init__.py"
        yield module
    finally:
        sys.modules.pop(spec.name, None)


@pytest.fixture
def plugin(diagnostic: ModuleType) -> Iterator[tuple[Any, io.StringIO]]:
    stream = io.StringIO()
    output = diagnostic._Output(stream)
    output.emit("begin")
    with contextlib.ExitStack() as stack:
        result = diagnostic._Plugin(output, stack)
        yield result, stream


def _resume(generator: Any, value: Any = None) -> Any:
    with pytest.raises(StopIteration) as stopped:
        generator.send(value)
    return stopped.value.value


def _item(diagnostic: ModuleType, **options: Any) -> SimpleNamespace:
    manager = SimpleNamespace(hasplugin=lambda name: name == "terminalreporter")
    config = SimpleNamespace(
        option=SimpleNamespace(collectonly=False, numprocesses=0, keyword="", markexpr="", **options),
        pluginmanager=manager,
    )
    return SimpleNamespace(nodeid=diagnostic._SELECTOR, config=config, module=ModuleType("fake"))


def _collected(plugin: Any, diagnostic: ModuleType, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    item = _item(diagnostic)
    monkeypatch.setattr(diagnostic, "_origins", lambda item: None)
    monkeypatch.setattr(plugin.observation, "intercept", lambda module: contextlib.nullcontext())
    hook = plugin.pytest_collection_modifyitems([item])
    next(hook)
    _resume(hook)
    finish = plugin.pytest_collection_finish(SimpleNamespace(items=[item], config=item.config))
    next(finish)
    _resume(finish)
    return item


def _successful_state(plugin: Any, diagnostic: ModuleType) -> None:
    plugin.collected = plugin.protocols = plugin.calls = 1
    plugin.collection_ok = True
    plugin.timer = {"seconds": 180, "method": "signal", "scope": "whole_test", "observed": True}
    plugin.reports = dict.fromkeys(("setup", "call", "teardown"), "passed")
    plugin.report_counts = dict.fromkeys(plugin.reports, 1)
    observed = plugin.observation
    observed.admissions = 1
    observed.requested = observed.children = observed.active = observed.rows = 1000
    observed.mode_active = True
    observed.attempted = [1000, 1000, 1000]
    observed.returned = [1000, 1000, 1000]
    observed.completed = 1000
    observed.windows = {
        row: SimpleNamespace(complete=True, population=row, stats={
            "read": dict.fromkeys(("submitted", "worker_started", "worker_finished", "await_resumed"), 1),
        }) for row in diagnostic._ROWS
    }


class _Start:
    pass


class _Submit:
    pass


class _Review:
    pass


class _Rows:
    def __init__(self, state: str = "unstarted", accepted: bool = True, count: int = 1000) -> None:
        self.row = SimpleNamespace(kind="child", permit_state=state, review_accepted=accepted)
        self.count = count

    def __len__(self) -> int:
        return self.count

    def __iter__(self) -> Iterator[SimpleNamespace]:
        return itertools.repeat(self.row, self.count)

    def __getitem__(self, index: int) -> SimpleNamespace:
        if not 0 <= index < self.count:
            raise IndexError(index)
        return self.row


def _snapshot(state: str = "unstarted", *, accepted: bool = True, count: int = 1000) -> SimpleNamespace:
    return SimpleNamespace(control=SimpleNamespace(mode="active", rows=_Rows(state, accepted, count)))


def _helpers(path: Path) -> tuple[ModuleType, SimpleNamespace]:
    module = ModuleType("tiny_capacity_helpers")
    module.steps = SimpleNamespace(
        StartOwnedStepCommand=_Start, SubmitOwnedStepCommand=_Submit, ReviewOwnedStepCommand=_Review,
    )
    harness = SimpleNamespace(path=path, calls=[], admitted=(SimpleNamespace(id="parent-1"), _Rows()))

    async def legacy(*args: Any, **kwargs: Any) -> Any:
        harness.calls.append((args, kwargs))
        return harness.admitted

    async def apply(*args: Any, **kwargs: Any) -> Any:
        harness.calls.append((args, kwargs))
        state = {_Start: "started", _Submit: "submitted", _Review: "terminal"}[type(args[3])]
        result = (SimpleNamespace(snapshot=_snapshot(state), disposition="new"), object())
        harness.last_result = result
        return result

    module._legacy_plan, module._apply = legacy, apply
    return module, harness


def _small_database(path: Path, children: int = 2) -> None:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE work_items (parent_id TEXT, verification TEXT, actual_tokens INTEGER)")
        db.execute("CREATE TABLE owned_steps_journal (kind TEXT)")
        db.executemany(
            "INSERT INTO work_items VALUES ('parent-1', ?, 1)",
            [('{"accepted":true}',)] * children,
        )
        db.executemany("INSERT INTO owned_steps_journal VALUES (?)", [(kind,) for kind in ("operation", "permit", "submission", "review")])


def test_workflow_exact_additions_preserve_all_prior_commands_settings_and_comments() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    baseline = subprocess.run(
        ["git", "show", f"{BASE}:.github/workflows/ci.yml"],
        cwd=ROOT, text=True, capture_output=True, check=True,
    ).stdout
    addition = """      - name: Diagnose owned capacity (temporary PR 1410)
        if: >-
          ${{ failure() && !cancelled()
              && github.event_name == 'pull_request'
              && github.event.pull_request.number == 1410
              && steps.required_python_tests.outcome == 'failure' }}
        timeout-minutes: 4
        run: .venv/bin/python -u scripts/diagnose_owned_capacity.py

"""
    assert workflow.count(addition) == 1
    assert workflow.replace(addition, "").replace("        id: required_python_tests\n", "", 1) == baseline
    assert "run: uv run pytest tests/ -n auto --maxfail=10 -q --tb=short\n\n" + addition in workflow
    assert workflow.count("id: required_python_tests") == 1
    assert "      - name: Run tests\n        id: required_python_tests\n" in workflow
    assert "    timeout-minutes: 45\n" in workflow and "    timeout-minutes: 15\n" in workflow
    assert "name: CI\n" in workflow and "  python-tests:\n" in workflow and "  ui-tests:\n" in workflow
    assert "continue-on-error" not in workflow


@pytest.mark.parametrize("before,after", [(0, 0), (2, 2), (1, 0), (1, 2)])
def test_collection_rejects_wrong_counts_after_other_hooks(
    diagnostic: ModuleType, plugin: Any, before: int, after: int,
) -> None:
    observer, _ = plugin
    items = [_item(diagnostic) for _ in range(before)]
    hook = observer.pytest_collection_modifyitems(items)
    next(hook)
    items[:] = [_item(diagnostic) for _ in range(after)]
    with pytest.raises(diagnostic._Fault, match="collection"):
        hook.send(None)


def test_collection_rejects_wrong_node_without_echoing_it(diagnostic: ModuleType, plugin: Any) -> None:
    observer, _ = plugin
    hook = observer.pytest_collection_modifyitems([SimpleNamespace(nodeid=SECRET)])
    next(hook)
    with pytest.raises(diagnostic._Fault, match="collection") as error:
        hook.send(None)
    assert SECRET not in str(error.value)


@pytest.mark.parametrize("change", ["late_remove", "late_replace", "deselected", "collectonly", "parallel", "keyword", "markexpr", "no_terminal", "randomly"])
def test_final_collection_and_effective_settings_fail_closed(
    diagnostic: ModuleType, plugin: Any, monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    observer, _ = plugin
    item = _collected(observer, diagnostic, monkeypatch)
    items = [item]
    hook = observer.pytest_collection_finish(SimpleNamespace(items=items, config=item.config))
    next(hook)
    if change == "late_remove":
        items.clear()
    elif change == "late_replace":
        items[0] = SimpleNamespace(nodeid=SECRET)
    elif change == "deselected":
        observer.pytest_deselected([item])
    elif change in {"collectonly", "parallel", "keyword", "markexpr"}:
        key, value = {
            "collectonly": ("collectonly", True), "parallel": ("numprocesses", 1),
            "keyword": ("keyword", SECRET), "markexpr": ("markexpr", SECRET),
        }[change]
        setattr(item.config.option, key, value)
    else:
        item.config.pluginmanager.hasplugin = lambda name: change == "randomly"
    with pytest.raises(diagnostic._Fault, match="collection|settings"):
        hook.send(None)


def test_original_imports_verified_without_executing_original_test(
    diagnostic: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    module = importlib.import_module("tests.test_ad1192_owned_steps_store")
    item = SimpleNamespace(module=module, obj=getattr(module, diagnostic._SELECTOR.split("::")[1]))
    diagnostic._origins(item)
    monkeypatch.setattr(module, "__file__", str(tmp_path / "wrong.py"))
    with pytest.raises(diagnostic._Fault, match="imports"):
        diagnostic._origins(item)


@pytest.mark.parametrize("field,value", [
    ("calls", 0), ("calls", 2), ("protocols", 2), ("collected", 0), ("deselected", 1),
    ("timer", None), ("collection_ok", False),
])
def test_finish_rejects_missing_or_duplicate_execution(
    diagnostic: ModuleType, plugin: Any, field: str, value: Any,
) -> None:
    observer, _ = plugin
    _successful_state(observer, diagnostic)
    setattr(observer, field, value)
    result, report = diagnostic._finish(observer, 0, diagnostic._metric(diagnostic._EXPECTED_COUNTS))
    assert result != 0 and not report["complete"]


@pytest.mark.parametrize("when,outcome,xfail", [
    ("setup", "skipped", False), ("call", "skipped", True),
    ("call", "passed", True), ("call", "failed", False), ("teardown", "failed", False),
])
def test_reports_preserve_original_outcome_and_reject_skip_xfail_and_failures(
    diagnostic: ModuleType, plugin: Any, when: str, outcome: str, xfail: bool,
) -> None:
    observer, _ = plugin
    _successful_state(observer, diagnostic)
    observer.report_counts[when] = 0
    report = SimpleNamespace(when=when, outcome=outcome, skipped=outcome == "skipped")
    if xfail:
        report.wasxfail = SECRET
    hook = observer.pytest_runtest_makereport(_item(diagnostic), SimpleNamespace(excinfo=None))
    next(hook)
    assert _resume(hook, report) is report
    result, evidence = diagnostic._finish(observer, 0, diagnostic._metric(diagnostic._EXPECTED_COUNTS))
    assert result != 0 and not evidence["complete"]


@pytest.mark.parametrize("attribute,value", [
    ("requested", 999), ("children", 999), ("active", 999), ("rows", 999),
    ("mode_active", False), ("admissions", 2), ("completed", 999), ("next_phase", 1),
    ("returned", [1001, 999, 1000]), ("attempted", [1000, 1000, 1001]),
    ("problem", "sequence"), ("test_error", "timeout"),
])
def test_premises_and_false_3000_count_cannot_create_success(
    diagnostic: ModuleType, plugin: Any, attribute: str, value: Any,
) -> None:
    observer, _ = plugin
    _successful_state(observer, diagnostic)
    setattr(observer.observation, attribute, value)
    result, evidence = diagnostic._finish(observer, 0, diagnostic._metric(diagnostic._EXPECTED_COUNTS))
    assert result != 0 and not evidence["complete"]


def test_complete_requires_durable_counts_and_original_assertion_reports(
    diagnostic: ModuleType, plugin: Any,
) -> None:
    observer, _ = plugin
    _successful_state(observer, diagnostic)
    result, evidence = diagnostic._finish(observer, 0, diagnostic._metric(diagnostic._EXPECTED_COUNTS))
    assert result == 0 and evidence["complete"]
    observer.report_counts["call"] = 0
    assert diagnostic._finish(observer, 0, diagnostic._metric(diagnostic._EXPECTED_COUNTS))[0] != 0
    observer.report_counts["call"] = 1
    for durable in (diagnostic._metric(None, "db_busy"), diagnostic._metric({**diagnostic._EXPECTED_COUNTS, "tokens": 999})):
        result, evidence = diagnostic._finish(observer, 0, durable)
        assert result != 0 and not evidence["complete"]


@pytest.mark.asyncio
@pytest.mark.parametrize("row,sampled", [(0, True), (1, False), (499, False), (500, True), (998, False), (999, True)])
async def test_helpers_delegate_same_arguments_results_and_sample_only_actual_populations(
    diagnostic: ModuleType, tmp_path: Path, row: int, sampled: bool,
) -> None:
    module, harness = _helpers(tmp_path / "shared.db")
    observed = diagnostic._Observation()
    originals = module._legacy_plan, module._apply, aiosqlite.Connection._execute
    async with aiosqlite.connect(harness.path) as db:
        await db.execute("CREATE TABLE tiny (value TEXT)")
        apply = module._apply

        async def disk_apply(*args: Any, **kwargs: Any) -> Any:
            await db.execute("INSERT INTO tiny VALUES (?)", (SECRET,))
            await db.commit()
            async with db.execute("SELECT count(*) FROM tiny") as cursor:
                await cursor.fetchone()
            return await apply(*args, **kwargs)

        module._apply = disk_apply
        with observed.intercept(module):
            admitted = await module._legacy_plan(harness, children_count=1000)
            assert admitted is harness.admitted
            assert observed.phase == "initial_snapshot"
            observed.completed = row
            observed.attempted = [row] * 3
            observed.returned = [row] * 3
            observed.active = observed.rows = 1000
            observed.mode_active = True
            snapshot = _snapshot()
            for phase, command in enumerate((_Start(), _Submit(), _Review())):
                result = await module._apply(harness, snapshot, row, command, actor=SECRET, role="executor")
                assert result is harness.last_result
                assert observed.phase == ("final_assertions" if row == 999 and phase == 2 else "after_" + diagnostic._PHASES[phase])
                assert harness.calls[-1] == ((harness, snapshot, row, command), {"actor": SECRET, "role": "executor"})
                snapshot = result[0].snapshot
            assert diagnostic._SCOPE.get() is None
        assert module._legacy_plan is originals[0] and module._apply is disk_apply
        assert aiosqlite.Connection._execute is originals[2]
    assert observed.completed == row + 1 and observed.returned == [row + 1] * 3
    assert (row in observed.windows) is sampled
    if sampled:
        report = observed.windows[row].report()
        assert report["population"] == row and report["complete"]
        assert {"read", "write", "commit", "fetch", "close"} <= report["sql"].keys()
        assert all(stat["measured"] == [stat["submitted"]] * 5 for stat in report["sql"].values())
        output = diagnostic._Output(io.StringIO())
        output.emit("begin")
        output.emit("window", **report)
        assert SECRET not in output.stream.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("command,index", [(_Submit(), 0), (_Review(), 0), (_Start(), 500), (_Start(), 999)])
async def test_out_of_order_or_unearned_window_does_not_advance(
    diagnostic: ModuleType, tmp_path: Path, command: Any, index: int,
) -> None:
    module, harness = _helpers(tmp_path / "shared.db")
    observed = diagnostic._Observation()
    with observed.intercept(module):
        await module._legacy_plan(harness, children_count=1000)
        result = await module._apply(harness, _snapshot(), index, command)
        assert result is harness.last_result
    assert observed.problem == "sequence"
    assert observed.completed == 0 and not observed.windows


@pytest.mark.asyncio
async def test_rejected_review_is_not_a_completed_chain(diagnostic: ModuleType, tmp_path: Path) -> None:
    module, harness = _helpers(tmp_path / "shared.db")
    apply = module._apply

    async def reject(*args: Any, **kwargs: Any) -> Any:
        result = await apply(*args, **kwargs)
        if isinstance(args[3], _Review):
            result[0].snapshot.control.rows.row.review_accepted = False
        return result

    module._apply = reject
    observed = diagnostic._Observation()
    with observed.intercept(module):
        await module._legacy_plan(harness, children_count=1000)
        snapshot = _snapshot()
        for command in (_Start(), _Submit(), _Review()):
            result = await module._apply(harness, snapshot, 0, command)
            snapshot = result[0].snapshot
    assert observed.returned == [1, 1, 1] and observed.completed == 0
    assert observed.problem == "result" and not observed.windows[0].complete


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [None, AssertionError(SECRET), sqlite3.OperationalError(SECRET), asyncio.CancelledError(SECRET)])
async def test_real_worker_callable_once_off_main_preserves_identity_and_exceptions(
    diagnostic: ModuleType, tmp_path: Path, error: BaseException | None,
) -> None:
    module, _ = _helpers(tmp_path / "shared.db")
    observed = diagnostic._Observation()
    window = diagnostic._Window(0, 0, asyncio.current_task())
    token = diagnostic._SCOPE.set(window)
    result, calls = object(), []

    def work(argument: Any, *, keyword: str) -> Any:
        calls.append((argument, keyword, threading.get_ident()))
        if error is not None:
            raise error
        return result

    original = aiosqlite.Connection._execute
    try:
        async with aiosqlite.connect(tmp_path / "shared.db") as db:
            with observed.intercept(module):
                if error is None:
                    assert await db._execute(work, result, keyword=SECRET) is result
                else:
                    with pytest.raises(type(error)) as caught:
                        await db._execute(work, result, keyword=SECRET)
                    assert caught.value is error
            assert aiosqlite.Connection._execute is original
    finally:
        diagnostic._SCOPE.reset(token)
    assert calls == [(result, SECRET, calls[0][2])] and calls[0][2] != threading.get_ident()
    stats = window.report()["sql"]["other"]
    assert stats["submitted"] == 1 and stats["measured"] == [1] * 5


@pytest.mark.asyncio
async def test_inherited_context_does_not_sample_another_task(diagnostic: ModuleType, tmp_path: Path) -> None:
    module, _ = _helpers(tmp_path / "shared.db")
    window = diagnostic._Window(0, 0, asyncio.current_task())
    token = diagnostic._SCOPE.set(window)
    try:
        async with aiosqlite.connect(tmp_path / "shared.db") as db:
            with diagnostic._Observation().intercept(module):
                child = asyncio.create_task(db._execute(lambda: 7))
                assert await child == 7
                assert not window.stats
                assert await db._execute(lambda: 8) == 8
    finally:
        diagnostic._SCOPE.reset(token)
    assert window.report()["sql"]["other"]["submitted"] == 1


@pytest.mark.asyncio
async def test_cancellation_before_worker_finishes_has_missing_not_zero_durations(
    diagnostic: ModuleType, tmp_path: Path,
) -> None:
    module, _ = _helpers(tmp_path / "shared.db")
    started, release = threading.Event(), threading.Event()
    windows, calls = [], []

    def blocked() -> int:
        calls.append(1)
        started.set()
        if not release.wait(5):
            raise AssertionError("unit probe did not release its worker")
        return 9

    async with aiosqlite.connect(tmp_path / "shared.db") as db:
        with diagnostic._Observation().intercept(module):
            async def operation() -> None:
                window = diagnostic._Window(0, 0, asyncio.current_task())
                windows.append(window)
                token = diagnostic._SCOPE.set(window)
                try:
                    await db._execute(blocked)
                finally:
                    diagnostic._SCOPE.reset(token)

            task = asyncio.create_task(operation())
            try:
                assert await asyncio.to_thread(started.wait, 3)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert windows[0].operation_state()["value"] == {
                    "kind": "other", "submitted": True, "worker_started": True,
                    "worker_finished": False, "await_resumed": True,
                }
                stats = windows[0].report()["sql"]["other"]
                assert stats["measured"] == [1, 0, 0, 0, 1]
                assert stats["sum_s"][1:4] == [None, None, None]
                assert stats["missing"][1:4] == ["not_observed"] * 3
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                assert await db._execute(lambda: True)
    assert calls == [1]


@pytest.mark.asyncio
async def test_failure_state_before_teardown_is_bounded_and_retains_partial_phase(
    diagnostic: ModuleType, plugin: Any,
) -> None:
    observer, stream = plugin
    ready, hold = asyncio.Event(), asyncio.Event()

    async def pending() -> None:
        ready.set()
        await hold.wait()

    task = asyncio.create_task(pending())
    try:
        await ready.wait()
        observer.observation.task = task
        observer.observation.row, observer.observation.phase = 500, "submission"
        observer.observation.completed = 500
        observer.pytest_runtest_teardown(_item(diagnostic))
        state = json.loads(stream.getvalue().splitlines()[-1])
        assert state["captured_before_teardown"] and state["completed"] == 500
        assert state["current_row"]["value"] == 500 and state["current_phase"] == "submission"
        assert state["task"]["value"]["task"] == "pending"
        assert 1 <= len(state["task"]["value"]["await_chain"]) <= 12
        assert state["missing_windows"]["value"] == [0, 500, 999]
        observer.capture(False)
        assert len(stream.getvalue().splitlines()) == 3
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert diagnostic._task_state(task)["value"]["task"] == "cancelled"


def _signal_probe(diagnostic: ModuleType, observer: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, dict[str, Any]]:
    state: dict[str, Any] = {}
    monkeypatch.setattr(diagnostic, "_PLATFORM", "linux")
    monkeypatch.setattr(pytest_timeout, "is_debugging", lambda: False)
    monkeypatch.setattr(diagnostic.signal, "SIGALRM", 14, raising=False)
    monkeypatch.setattr(diagnostic.signal, "ITIMER_REAL", 0, raising=False)
    monkeypatch.setattr(diagnostic.signal, "signal", lambda signum, handler: state.update(handler=handler))
    monkeypatch.setattr(diagnostic.signal, "setitimer", lambda which, seconds: state.update(seconds=seconds), raising=False)
    monkeypatch.setattr(diagnostic.signal, "getsignal", lambda signum: state["handler"])
    monkeypatch.setattr(diagnostic.signal, "getitimer", lambda which: (state["seconds"], 0), raising=False)
    manager = pytest.PytestPluginManager()
    manager.hook.pytest_addhooks.call_historic(kwargs={"pluginmanager": manager})
    manager.register(pytest_timeout)
    manager.register(observer)
    item = SimpleNamespace(nodeid=diagnostic._SELECTOR, config=SimpleNamespace(pluginmanager=manager))
    return item, state


def test_timeout_observer_uses_real_firstresult_implementation_without_replacing_it(
    diagnostic: ModuleType, plugin: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer, _ = plugin
    item, state = _signal_probe(diagnostic, observer, monkeypatch)
    original = pytest_timeout.pytest_timeout_set_timer
    settings = pytest_timeout.Settings(180, "signal", False, False)
    assert item.config.pluginmanager.hook.pytest_timeout_set_timer(item=item, settings=settings) is True
    assert pytest_timeout.pytest_timeout_set_timer is original
    assert observer.timer == {"seconds": 180, "method": "signal", "scope": "whole_test", "observed": True}
    assert state["seconds"] == 180 and state["handler"].__module__ == "pytest_timeout"
    item.cancel_timeout()
    assert state["seconds"] == 0


@pytest.mark.parametrize("seconds,method,func_only", [(0, "signal", False), (179, "signal", False), (181, "signal", False), (180, "thread", False), (180, "signal", True)])
def test_incompatible_observed_timeout_is_rejected(
    diagnostic: ModuleType, plugin: Any, monkeypatch: pytest.MonkeyPatch,
    seconds: int, method: str, func_only: bool,
) -> None:
    observer, _ = plugin
    item, state = _signal_probe(diagnostic, observer, monkeypatch)
    with pytest.raises(diagnostic._Fault, match="settings"):
        item.config.pluginmanager.hook.pytest_timeout_set_timer(
            item=item, settings=pytest_timeout.Settings(seconds, method, func_only, False),
        )
    assert not state and observer.timer is None


def test_timeout_handler_output_is_private_and_original_caplog_still_works(
    diagnostic: ModuleType, plugin: Any, monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture,
) -> None:
    from _pytest._io import TerminalWriter

    observer, _ = plugin
    item, state = _signal_probe(diagnostic, observer, monkeypatch)
    settings = pytest_timeout.Settings(180, "signal", False, False)
    item.config.pluginmanager.hook.pytest_timeout_set_timer(item=item, settings=settings)
    caplog.set_level(logging.INFO, logger="capacity_privacy_probe")
    capfd.readouterr()
    with diagnostic._quiet_channel() as channel:
        terminal = TerminalWriter(file=sys.stdout)
        item.config.get_terminal_writer = lambda: terminal
        output = diagnostic._Output(channel)
        output.emit("begin")
        print(SECRET)
        print(SECRET, file=sys.stderr)
        os.write(1, SECRET.encode())
        os.write(2, SECRET.encode())
        logging.getLogger("capacity_privacy_probe").info(SECRET)
        with pytest.raises(pytest.fail.Exception) as caught:
            state["handler"](14, None)
        assert diagnostic._error(caught.value) == "timeout"
        assert any(record.getMessage() == SECRET for record in caplog.records)
        output.emit("finish", complete=False, code=diagnostic._error(caught.value))
    item.cancel_timeout()
    captured = capfd.readouterr()
    assert not captured.err and SECRET not in captured.out
    assert [json.loads(line)["record"] for line in captured.out.splitlines()] == ["begin", "finish"]
    assert captured.out.isascii()


def test_hidden_controls_and_local_import_path_are_restored_on_error(
    diagnostic: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in diagnostic._CONTROLS:
        monkeypatch.setenv(name, SECRET)
    monkeypatch.setenv("PROBOS_EMBEDDINGS", SECRET)
    before = sys.path[:], Path.cwd(), sys.dont_write_bytecode
    with pytest.raises(RuntimeError):
        with diagnostic._local_controls():
            assert all(name not in os.environ for name in diagnostic._CONTROLS)
            assert os.environ["PROBOS_EMBEDDINGS"] == SECRET
            assert sys.path[:2] == [str(ROOT / "src"), str(ROOT)]
            raise RuntimeError(SECRET)
    assert all(os.environ[name] == SECRET for name in diagnostic._CONTROLS)
    assert (sys.path, Path.cwd(), sys.dont_write_bytecode) == before


@pytest.mark.parametrize("value", [SECRET, float("nan"), float("inf"), object(), {"secret": 1}, "\u2603", 2**64])
def test_privacy_schema_rejects_unknown_text_objects_and_nonfinite_numbers(
    diagnostic: ModuleType, value: Any,
) -> None:
    stream = io.StringIO()
    output = diagnostic._Output(stream)
    output.emit("begin")
    with pytest.raises(diagnostic._Fault, match="output_privacy"):
        output.emit("window", value=value)
    output.emit("finish", complete=False, code="output_privacy")
    assert SECRET not in stream.getvalue() and stream.getvalue().isascii()


def test_record_byte_count_and_total_bounds_reserve_terminal_record(diagnostic: ModuleType) -> None:
    stream = io.StringIO()
    output = diagnostic._Output(stream)
    output.emit("begin")
    with pytest.raises(diagnostic._Fault, match="output_bounds"):
        output.emit("window", sql=[{"read": [0] * 32, "write": [0] * 32}] * 32)
    for _ in range(6):
        output.emit("window")
    with pytest.raises(diagnostic._Fault, match="output_bounds"):
        output.emit("window")
    output.emit("finish", complete=False, code="output_bounds")
    with pytest.raises(diagnostic._Fault, match="output_protocol"):
        output.emit("finish")
    lines = stream.getvalue().encode("ascii").splitlines(keepends=True)
    assert len(lines) == 8 and max(map(len, lines)) <= 4096 and sum(map(len, lines)) <= 32768
    assert all(json.loads(line)["acceptance"] is False for line in lines)


def test_snapshot_one_readonly_zero_wait_real_disk_query(diagnostic: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "small.db"
    _small_database(path)
    before = path.read_bytes()
    original, calls = diagnostic.sqlite3.connect, []

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(diagnostic.sqlite3, "connect", connect)
    snapshot = diagnostic._snapshot(path)
    assert snapshot == diagnostic._metric(dict(zip(diagnostic._COUNT_KEYS, (2, 2, 2, 1, 1, 1, 1, 4))))
    assert len(calls) == 1 and calls[0][1] == {"uri": True, "timeout": 0.0}
    assert calls[0][0][0].endswith("?mode=ro")
    assert path.read_bytes() == before


def test_snapshot_busy_missing_unreadable_and_progress_bound_are_explicit(diagnostic: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "missing.db"
    assert diagnostic._snapshot(path) == diagnostic._metric(None, "db_missing")
    assert diagnostic._snapshot(None) == diagnostic._metric(None, "db_missing")
    assert not path.exists()
    path.write_bytes(SECRET.encode())
    assert diagnostic._snapshot(path) == diagnostic._metric(None, "db_unreadable")
    path.unlink()
    _small_database(path, children=256)
    with sqlite3.connect(path) as locker:
        locker.execute("BEGIN EXCLUSIVE")
        assert diagnostic._snapshot(path) == diagnostic._metric(None, "db_busy")
        locker.rollback()
    ticks = iter((0.0, 1.0, 1.0))
    monkeypatch.setattr(diagnostic.time, "perf_counter", lambda: next(ticks))
    assert diagnostic._snapshot(path) == diagnostic._metric(None, "db_query_bound")


@pytest.mark.parametrize("available", [False, True])
def test_os_counters_are_fixed_numeric_allowlist_or_explicitly_unavailable(
    diagnostic: ModuleType, monkeypatch: pytest.MonkeyPatch, available: bool,
) -> None:
    monkeypatch.setattr(diagnostic, "_PLATFORM", "linux")
    resource = ModuleType("resource")
    resource.RUSAGE_SELF = 0
    resource.getrusage = lambda who: SimpleNamespace(**dict.fromkeys(diagnostic._RESOURCE_FIELDS, 12))
    monkeypatch.setitem(sys.modules, "resource", resource)

    def read(*args: Any, **kwargs: Any) -> io.StringIO:
        assert args == ("/proc/self/io",)
        if not available:
            raise FileNotFoundError(SECRET)
        return io.StringIO("\n".join(f"{key}: 9" for key in diagnostic._IO_FIELDS) + f"\n{SECRET}: 42")

    monkeypatch.setattr("builtins.open", read)
    sample = diagnostic._os_counters()
    assert sample["resource_delta"]["value"] == dict.fromkeys(diagnostic._RESOURCE_FIELDS, 12)
    assert sample["io_delta"] == diagnostic._metric(dict.fromkeys(diagnostic._IO_FIELDS, 9) if available else None, "os_unavailable")
    assert SECRET not in json.dumps(sample)
    delta = diagnostic._os_delta(sample, sample)
    assert delta["peak_rss_kib"]["value"] == 12
    assert delta["resource_delta"]["value"] == dict.fromkeys(diagnostic._RESOURCE_FIELDS[1:], 0)


def test_unavailable_platform_and_thread_cpu_are_null_with_reason(diagnostic: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diagnostic, "_PLATFORM", "win32")
    monkeypatch.delattr(diagnostic.time, "thread_time")
    window = diagnostic._Window(0, 0, None)
    report = window.report()
    assert report["main_cpu_s"] == diagnostic._metric(None, "clock_unavailable")
    assert report["os"]["io_delta"] == diagnostic._metric(None, "os_unavailable")
    assert report["os"]["peak_rss_kib"] == diagnostic._metric(None, "os_unavailable")


def test_fixed_main_invokes_pytest_once_and_cannot_accept_alternate_workloads(
    diagnostic: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diagnostic, "_PLATFORM", "linux")
    monkeypatch.setattr(diagnostic.sys, "argv", ["diagnose_owned_capacity.py"])
    original = aiosqlite.Connection._execute
    calls = []

    def run(args: list[str], plugins: list[Any]) -> int:
        calls.append(args)
        assert diagnostic._SELECTOR == args[0]
        assert args[args.index("-n") + 1] == "0" and "addopts=" in args
        assert "no:randomly" in args and "no:terminal" not in args
        assert all(name not in os.environ for name in diagnostic._CONTROLS)
        assert len(plugins) == 1
        return 0  # No collection or workload: a zero pytest exit is not evidence.

    monkeypatch.setattr(diagnostic.pytest, "main", run)
    for argv, expected_calls in [(["diagnose_owned_capacity.py"], 1), (["diagnose_owned_capacity.py", SECRET], 1)]:
        monkeypatch.setattr(diagnostic.sys, "argv", argv)
        stream = io.StringIO()
        assert diagnostic._run(diagnostic._Output(stream)) != 0
        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        assert records[0]["record"] == "begin" and records[-1]["record"] == "finish"
        assert records[-1]["complete"] is False and SECRET not in stream.getvalue()
        assert records[0]["concurrent_xdist_reproduction"] is False
        assert len(calls) == expected_calls and aiosqlite.Connection._execute is original


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [AssertionError(SECRET), sqlite3.OperationalError(SECRET), asyncio.CancelledError(SECRET)])
async def test_helper_failure_restores_hooks_context_and_does_not_count_a_return(
    diagnostic: ModuleType, tmp_path: Path, error: BaseException,
) -> None:
    module, harness = _helpers(tmp_path / "shared.db")
    calls = []

    async def fail(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))
        raise error

    module._apply = fail
    originals = module._legacy_plan, module._apply, aiosqlite.Connection._execute
    observed = diagnostic._Observation()
    with pytest.raises(type(error)) as caught:
        with observed.intercept(module):
            assert await module._legacy_plan(harness=harness, children_count=1000) is harness.admitted
            await module._apply(harness, _snapshot(), 0, _Start())
    assert caught.value is error and len(calls) == 1
    assert (module._legacy_plan, module._apply, aiosqlite.Connection._execute) == originals
    assert diagnostic._SCOPE.get() is None
    assert observed.attempted == [1, 0, 0] and observed.returned == [0, 0, 0] and observed.completed == 0
    assert not observed.windows[0].complete


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["children", "requested", "rows", "mode", "kind", "state", "null_result"])
async def test_actual_admission_and_result_premises_reject_mismatch_without_substitution(
    diagnostic: ModuleType, tmp_path: Path, fault: str,
) -> None:
    module, harness = _helpers(tmp_path / "shared.db")
    if fault == "children":
        harness.admitted = (harness.admitted[0], _Rows(count=999))
    if fault == "null_result":
        async def apply(*args: Any, **kwargs: Any) -> Any:
            result = (SimpleNamespace(snapshot=None, disposition="new"), object())
            harness.last_result = result
            return result
        module._apply = apply
    observed = diagnostic._Observation()
    initial = _snapshot(count=999 if fault == "rows" else 1000)
    if fault == "mode":
        initial.control.mode = "inactive"
    elif fault == "kind":
        initial.control.rows.row.kind = "manual"
    elif fault == "state":
        initial.control.rows.row.permit_state = "terminal"
    with observed.intercept(module):
        await module._legacy_plan(harness, children_count=999 if fault == "requested" else 1000)
        assert await module._apply(harness, initial, 0, _Start()) is harness.last_result
    assert observed.problem == ("result" if fault == "null_result" else "premise")
    assert observed.returned == [1, 0, 0] and observed.completed == 0


@pytest.mark.parametrize("function,sql,expected", [
    ("execute", "SELECT 1", "read"), ("execute", "EXPLAIN SELECT 1", "read"),
    ("execute", " INSERT INTO tiny VALUES (?)", "write"), ("executemany", "UPDATE tiny SET x=?", "write"),
    ("execute", "BEGIN IMMEDIATE", "begin"), ("execute", "COMMIT", "commit"),
    ("execute", "ROLLBACK", "rollback"), ("fetchone", None, "fetch"),
    ("fetchmany", None, "fetch"), ("fetchall", None, "fetch"), ("close", None, "close"),
    ("commit", None, "commit"), ("rollback", None, "rollback"),
    ("execute", "", "other"), ("execute", "WITH x AS (SELECT 1) SELECT * FROM x", "other"),
    ("execute", "PRAGMA user_version", "other"), ("unknown", SECRET, "other"),
])
def test_sql_classification_never_retains_sql_or_parameters(
    diagnostic: ModuleType, function: str, sql: str | None, expected: str,
) -> None:
    def worker() -> None:
        pass
    worker.__name__ = function
    assert diagnostic._category(worker, () if sql is None else (sql, (SECRET,))) == expected


def test_real_tiny_pytest_protocol_timeout_teardown_snapshot_and_private_json(
    diagnostic: ModuleType, tmp_path: Path,
) -> None:
    # Only this tiny generated node runs in the child; no original fixture or workload is imported.
    tests = tmp_path / "tests"
    tests.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntimeout=180\ntimeout_method="signal"\nasyncio_mode="auto"\n',
        encoding="ascii",
    )
    (tests / "test_ad1192_owned_steps_store.py").write_text(
        f'''
import logging
import signal
import sqlite3
import sys
import pytest

async def _legacy_plan(*args, **kwargs):
    raise AssertionError("the unit probe must not call admission")

async def _apply(*args, **kwargs):
    raise AssertionError("the unit probe must not call transitions")

@pytest.fixture
def stores(tmp_path):
    path = tmp_path / "shared.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE work_items (parent_id TEXT, verification TEXT, actual_tokens INTEGER)")
        db.execute("CREATE TABLE owned_steps_journal (kind TEXT)")
        db.execute("INSERT INTO work_items VALUES ('parent-1', '{{\\"accepted\\":true}}', 1)")
    OBSERVER.observation.path = path
    yield path
    assert OBSERVER.captured
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO owned_steps_journal VALUES ('review')")

def {diagnostic._SELECTOR.split("::")[1]}(stores, caplog):
    caplog.set_level(logging.INFO, logger="tiny_probe")
    for _ in range(9):
        logging.getLogger("tiny_probe").info({SECRET!r})
    assert len([record for record in caplog.records if record.name == "tiny_probe"]) == 9
    print({SECRET!r})
    print({SECRET!r}, file=sys.stderr)
    signal.getsignal(signal.SIGALRM)(signal.SIGALRM, None)
''',
        encoding="ascii",
    )
    probe = f'''
import importlib.util
import pathlib
import signal
import sys

spec = importlib.util.spec_from_file_location("capacity_probe", {str(Path(diagnostic.__file__))!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module._ROOT == pathlib.Path({str(ROOT)!r})
module._ROOT = pathlib.Path.cwd()

def origins(item):
    assert pathlib.Path(item.module.__file__).resolve() == module._ROOT / module._TEST_FILE
    assert item.nodeid == module._SELECTOR
    item.module.OBSERVER = next(p for p in item.config.pluginmanager.get_plugins() if isinstance(p, module._Plugin))
module._origins = origins

state = {{}}
signal.SIGALRM = 14
signal.ITIMER_REAL = 0
signal.signal = lambda number, handler: state.update(handler=handler)
signal.setitimer = lambda which, seconds: state.update(seconds=seconds)
signal.getsignal = lambda number: state["handler"]
signal.getitimer = lambda which: (state["seconds"], 0)
module.pytest_timeout.HAVE_SIGALRM = True
module.pytest_timeout.DEFAULT_METHOD = "signal"
module._PLATFORM = "linux"
sys.argv = [{str(Path(diagnostic.__file__))!r}]
raise SystemExit(module.main())
'''
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=tmp_path, capture_output=True, text=True, timeout=30,
        env={**os.environ, "PYTEST_ADDOPTS": "--collect-only -k should_never_select",
             "PYTEST_PLUGINS": SECRET, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_TIMEOUT": "1"},
    )
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert not result.stderr and SECRET not in result.stdout and result.stdout.isascii()
    lines = result.stdout.splitlines(keepends=True)
    assert len(lines) <= 8 and max(len(line.encode("ascii")) for line in lines) <= 4096
    assert sum(len(line.encode("ascii")) for line in lines) <= 32768
    records = [json.loads(line) for line in lines]
    assert records[0]["record"] == "begin"
    before = next(record for record in records if record["record"] == "failure_state")
    assert before["captured_before_teardown"] and before["completed"] == 0, result.stdout
    finish = records[-1]
    assert finish["record"] == "finish" and not finish["complete"]
    assert finish["test_error"] == "timeout" and finish["pytest_exit"]["value"] == 1
    assert finish["effective_timeout"]["value"] == {
        "seconds": 180, "method": "signal", "scope": "whole_test", "observed": True,
    }
    assert finish["calls"] == finish["protocols"] == finish["collected"] == 1
    assert finish["reports"] == {
        "setup": diagnostic._metric("passed"), "call": diagnostic._metric("failed"),
        "teardown": diagnostic._metric("passed"),
    }
    assert finish["durable"]["value"]["review"] == 1


@pytest.mark.parametrize("error,code", [
    (AssertionError(SECRET), "assertion"), (sqlite3.OperationalError(SECRET), "sqlite"),
    (asyncio.CancelledError(SECRET), "cancelled"), (KeyboardInterrupt(SECRET), "interrupted"),
    (RuntimeError(SECRET), "test_error"), (ImportError(SECRET), "imports"),
])
def test_pytest_failure_classification_restores_interception_and_never_emits_exception_text(
    diagnostic: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    error: BaseException, code: str,
) -> None:
    monkeypatch.setattr(diagnostic, "_PLATFORM", "linux")
    monkeypatch.setattr(diagnostic.sys, "argv", [diagnostic.__file__])
    module, _ = _helpers(tmp_path / "shared.db")
    originals = module._legacy_plan, module._apply, aiosqlite.Connection._execute

    def run(args: list[str], plugins: list[Any]) -> None:
        plugins[0].stack.enter_context(plugins[0].observation.intercept(module))
        raise error

    monkeypatch.setattr(diagnostic.pytest, "main", run)
    stream = io.StringIO()
    assert diagnostic._run(diagnostic._Output(stream)) != 0
    assert (module._legacy_plan, module._apply, aiosqlite.Connection._execute) == originals
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert records[-1]["code"] == code and records[-1]["complete"] is False
    assert SECRET not in stream.getvalue()


def test_partial_before_worker_start_and_unavailable_worker_cpu_are_not_fabricated(diagnostic: ModuleType) -> None:
    waiting = diagnostic._Window(500, 500, None)
    operation = {"kind": "read"}
    waiting.mark(operation, "submitted", 1.0)
    waiting.mark(operation, "await_resumed", 2.0)
    report = waiting.report()
    assert not report["complete"]
    stats = report["sql"]["read"]
    assert stats["measured"] == [0, 0, 0, 0, 1]
    assert stats["sum_s"] == [None, None, None, None, 1.0]
    cpu_missing = diagnostic._Window(0, 0, None)
    operation = {"kind": "other"}
    for stage, stamp in zip(("submitted", "worker_started", "worker_finished", "await_resumed"), (1.0, 2.0, 3.0, 4.0)):
        cpu_missing.mark(operation, stage, stamp)
    stats = cpu_missing.report()["sql"]["other"]
    assert stats["sum_s"] == [1.0, 1.0, None, 1.0, 3.0]
    assert stats["missing"][2] == "clock_unavailable"
    unused = waiting.report()["sql"]["rollback"]
    assert unused["submitted"] == 0 and unused["sum_s"] == [None] * 5
    assert unused["missing"] == ["not_observed"] * 5


def test_all_categories_and_os_fields_fit_three_maximal_window_records(
    diagnostic: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diagnostic, "_os_counters", lambda: {
        "resource_delta": diagnostic._metric(dict.fromkeys(diagnostic._RESOURCE_FIELDS, 2**48)),
        "io_delta": diagnostic._metric(dict.fromkeys(diagnostic._IO_FIELDS, 2**48)),
    })
    stream = io.StringIO()
    output = diagnostic._Output(stream)
    output.emit("begin")
    for row in diagnostic._ROWS:
        window = diagnostic._Window(row, row, None)
        for category in diagnostic._CATEGORIES:
            operation = {"kind": category}
            for stage, stamp in zip(("submitted", "worker_started", "worker_finished", "await_resumed"), (1.0, 2.0, 3.0, 4.0)):
                window.mark(operation, stage, stamp, 1.0 if stage == "worker_started" else 2.0)
        output.emit("window", **window.report())
    output.emit("finish", complete=False, code="incomplete")
    assert all(len(line.encode("ascii")) <= 4096 for line in stream.getvalue().splitlines(keepends=True))
    assert output.bytes <= 32768


@pytest.mark.parametrize("raw", ["read_bytes: not_numeric", "rchar: 1", "x" * 1025])
def test_invalid_os_counters_are_unavailable_without_echoing_input(
    diagnostic: ModuleType, monkeypatch: pytest.MonkeyPatch, raw: str,
) -> None:
    monkeypatch.setattr(diagnostic, "_PLATFORM", "linux")
    monkeypatch.setitem(sys.modules, "resource", None)
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: io.StringIO(raw))
    sample = diagnostic._os_counters()
    assert sample["resource_delta"] == diagnostic._metric(None, "os_unavailable")
    assert sample["io_delta"] == diagnostic._metric(None, "os_invalid")


def test_await_chain_is_bounded_without_repr_or_arbitrary_symbol_names(diagnostic: ModuleType) -> None:
    coroutine = None
    for _ in range(20):
        coroutine = SimpleNamespace(cr_code=None, cr_await=coroutine)

    class _Task:
        def get_coro(self) -> Any:
            return coroutine

        def done(self) -> bool:
            return False

        def cancelled(self) -> bool:
            return False

        def __repr__(self) -> str:
            raise AssertionError("task repr must not be observed")

    state = diagnostic._task_state(_Task())["value"]
    assert state["truncated"] and len(state["await_chain"]) == 12
    assert state["await_chain"][0]["line"] == diagnostic._metric(None)


@pytest.mark.parametrize("invalid", ["platform", "assertions", "imports"])
def test_startup_premises_prevent_any_pytest_execution(
    diagnostic: ModuleType, monkeypatch: pytest.MonkeyPatch, invalid: str,
) -> None:
    monkeypatch.setattr(diagnostic.sys, "argv", [diagnostic.__file__])
    monkeypatch.setattr(diagnostic, "_PLATFORM", "linux")
    if invalid == "platform":
        monkeypatch.setattr(diagnostic, "_PLATFORM", "win32")
    elif invalid == "assertions":
        monkeypatch.setattr(diagnostic.sys, "flags", SimpleNamespace(optimize=1))
    else:
        monkeypatch.setattr(diagnostic, "_version", lambda name: diagnostic._metric(None, "imports"))
    calls = []
    monkeypatch.setattr(diagnostic.pytest, "main", lambda *args, **kwargs: calls.append(1))
    stream = io.StringIO()
    assert diagnostic._run(diagnostic._Output(stream)) != 0
    assert not calls and json.loads(stream.getvalue().splitlines()[-1])["code"] == invalid


def test_executable_mutes_interpreter_shutdown_output_after_terminal_record(
    diagnostic: ModuleType,
) -> None:
    probe = f"""
import atexit
import os
import runpy
import sys
atexit.register(lambda: os.write(2, {SECRET.encode()!r}))
atexit.register(lambda: print({SECRET!r}))
sys.argv = [{diagnostic.__file__!r}, "rejected-unit-probe"]
runpy.run_path({diagnostic.__file__!r}, run_name="__main__")
"""
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    assert not result.stderr and SECRET not in result.stdout
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert records[-1]["record"] == "finish" and records[-1]["code"] == "arguments"


@pytest.mark.asyncio
async def test_unknown_transition_stays_non_success_and_reports_only_safe_phase(
    diagnostic: ModuleType, plugin: Any, tmp_path: Path,
) -> None:
    observer, stream = plugin
    module, harness = _helpers(tmp_path / "shared.db")
    result = object()

    async def apply(*args: Any, **kwargs: Any) -> Any:
        return result

    module._apply = apply
    with observer.observation.intercept(module):
        await module._legacy_plan(harness, children_count=1000)
        assert await module._apply(harness, _snapshot(), 0, object()) is result
    assert observer.observation.problem == "sequence"
    assert observer.observation.attempted == observer.observation.returned == [0, 0, 0]
    observer.capture(True)
    state = json.loads(stream.getvalue().splitlines()[-1])
    assert state["current_phase"] == "other" and state["completed"] == 0
