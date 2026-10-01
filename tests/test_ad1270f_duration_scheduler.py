"""AD-1270f P1.4: the duration-ordered ``--dist=loadfile`` scheduler.

These tests drive the *installed* xdist ``LoadFileScheduling`` (the stock class
beside the subclass) with a fake config and fake worker nodes, so what they
prove is what xdist would do: which unit it hands out first, that nothing is
dropped or repeated, and that every step except the order stays xdist's.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import logging
import random
import sys
from collections import OrderedDict, deque
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import xdist
from xdist.remote import Producer
from xdist.scheduler import LoadFileScheduling, LoadScopeScheduling

from tests.fixtures import duration_scheduler as ds
from tests.fixtures.duration_scheduler import (
    DURATIONS_NAME,
    DURATIONS_PATH,
    REPORT_PREFIX,
    DurationDataError,
    DurationOrderedLoadFileScheduling,
    FileDurations,
    load_file_durations,
    make_duration_scheduler,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFTEST = Path(__file__).with_name("conftest.py").resolve()
_MISSING = object()
_QUIET = Producer("ad1270f", enabled=False)


class _Terminal:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write_line(self, line: str) -> None:
        self.lines.append(line)


class _Config:
    """The slice of ``pytest.Config`` that xdist's loadfile scheduler and our hook read."""

    def __init__(
        self,
        *,
        workers: int = 2,
        dist: str = "loadfile",
        reorder: bool = True,
        with_terminal: bool = True,
    ) -> None:
        self.option = SimpleNamespace(dist=dist, loadscopereorder=reorder)
        self.terminal = _Terminal() if with_terminal else None
        self.collect_reports: list[Any] = []
        self._workers = workers
        self.hook = SimpleNamespace(pytest_collectreport=self._collect_report)
        self.pluginmanager = SimpleNamespace(getplugin=self._plugin)

    def _collect_report(self, *, report: Any) -> None:
        self.collect_reports.append(report)

    def _plugin(self, name: str) -> _Terminal | None:
        return self.terminal if name == "terminalreporter" else None

    def getvalue(self, name: str) -> Any:
        if name == "tx":
            return [f"{self._workers}*popen"]
        return getattr(self.option, name)

    def getoption(self, name: str, default: Any = _MISSING) -> Any:
        if hasattr(self.option, name):
            return getattr(self.option, name)
        if default is _MISSING:
            raise ValueError(f"no option named {name!r}")
        return default

    @property
    def lines(self) -> list[str]:
        """Every ``AD-1270f duration scheduler:`` line the session printed."""
        written = self.terminal.lines if self.terminal is not None else []
        return [line for line in written if line.startswith(REPORT_PREFIX)]


class _Node:
    """A worker as the scheduler sees it: it records what it is sent."""

    def __init__(self, name: str, events: list[tuple[str, list[int]]] | None = None) -> None:
        self.gateway = SimpleNamespace(id=name)
        self.sent: list[list[int]] = []
        self.shutting_down = False
        self.shutdowns = 0
        self._events = events

    def send_runtest_some(self, indices: list[int]) -> None:
        self.sent.append(list(indices))
        if self._events is not None:
            self._events.append((self.gateway.id, list(indices)))

    def shutdown(self) -> None:
        self.shutdowns += 1
        self.shutting_down = True


def _collection(spec: dict[str, int]) -> list[str]:
    return [f"{path}::test_{number}" for path, count in spec.items() for number in range(count)]


def _scope(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def _durations(files: dict[str, float], mean: float = 0.5) -> FileDurations:
    return FileDurations(files=files, mean_test_seconds=mean)


def _ordered(config: _Config, durations: FileDurations) -> DurationOrderedLoadFileScheduling:
    return DurationOrderedLoadFileScheduling(config, _QUIET, durations=durations)


def _stock(config: _Config) -> LoadFileScheduling:
    return LoadFileScheduling(config, _QUIET)


class _Run:
    """One scheduler, its workers and everything it has sent, after the first ``schedule()``."""

    def __init__(
        self,
        make: Callable[[_Config], LoadFileScheduling],
        spec: dict[str, int],
        *,
        workers: int = 2,
        with_terminal: bool = True,
        start: bool = True,
        diverge: bool = False,
    ) -> None:
        self.config = _Config(workers=workers, with_terminal=with_terminal)
        self.scheduler = make(self.config)
        self.collection = _collection(spec)
        self.events: list[tuple[str, list[int]]] = []
        self.nodes = [_Node(f"gw{number}", self.events) for number in range(workers)]
        for node in self.nodes:
            self.scheduler.add_node(node)
        for node in self.nodes:
            collected = self.collection[:-1] if diverge and node is self.nodes[-1] else self.collection
            self.scheduler.add_node_collection(node, collected)
        if start:
            self.scheduler.schedule()

    def scopes_sent(self) -> list[str]:
        """The file of each work unit, in the order xdist handed the units out."""
        return [_scope(self.collection[indices[0]]) for _, indices in self.events]

    def run_to_completion(self) -> dict[str, list[str]]:
        """Complete every sent test, one test at a time per worker, until xdist has no more work."""
        outstanding = {node: deque[int]() for node in self.nodes}
        consumed = {node: 0 for node in self.nodes}
        executed: dict[str, list[str]] = {node.gateway.id: [] for node in self.nodes}

        def absorb(node: _Node) -> None:
            while consumed[node] < len(node.sent):
                outstanding[node].extend(node.sent[consumed[node]])
                consumed[node] += 1

        progressed = True
        while progressed:
            progressed = False
            for node in self.nodes:
                absorb(node)
                if outstanding[node]:
                    index = outstanding[node].popleft()
                    executed[node.gateway.id].append(self.collection[index])
                    self.scheduler.mark_test_complete(node, index)
                    progressed = True
        return executed


def _two_workers(spec: dict[str, int], durations: FileDurations, **kwargs: Any) -> _Run:
    return _Run(lambda config: _ordered(config, durations), spec, **kwargs)


def _stock_workers(spec: dict[str, int], **kwargs: Any) -> _Run:
    return _Run(_stock, spec, **kwargs)


def _valid_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": {
            "junit": "run.xml",
            "collection": "run.collection.json",
            "junit_sha256": "a" * 64,
            "collection_sha256": "b" * 64,
            "testcases": 10,
            "total_seconds": 12.5,
        },
        "mean_test_seconds": 0.5,
        "files": {"tests/test_a.py": 1.5, "tests/test_b.py": 0.0},
    }


# --- Scheduling: what xdist hands out, and in what order ------------------------------

_SPEC = {
    "tests/test_many.py": 6,
    "tests/test_mid.py": 4,
    "tests/test_unit.py": 3,
    "tests/test_heavy.py": 2,
}
_RECORDED = {
    "tests/test_many.py": 2.0,
    "tests/test_mid.py": 8.0,
    "tests/test_unit.py": 1.0,
    "tests/test_heavy.py": 90.0,
}


def test_stock_xdist_sends_the_file_with_most_tests_first_and_the_subclass_the_heaviest() -> None:
    stock = _stock_workers(_SPEC)
    ordered = _two_workers(_SPEC, _durations(_RECORDED))

    assert stock.scopes_sent()[0] == "tests/test_many.py"
    assert ordered.scopes_sent()[0] == "tests/test_heavy.py"


def test_the_subclass_empties_the_queue_in_non_increasing_weight() -> None:
    durations = _durations(_RECORDED)
    run = _two_workers(_SPEC, durations)

    run.run_to_completion()

    order = run.scopes_sent()
    weights = [durations.estimate(scope, _SPEC[scope]) for scope in order]
    assert order == [
        "tests/test_heavy.py",
        "tests/test_mid.py",
        "tests/test_many.py",
        "tests/test_unit.py",
    ]
    assert weights == sorted(weights, reverse=True)


def test_an_unseen_file_weighs_its_test_count_times_the_suite_mean() -> None:
    spec = {"tests/test_new.py": 10, "tests/test_a.py": 2, "tests/test_b.py": 1}
    durations = _durations({"tests/test_a.py": 4.0, "tests/test_b.py": 6.0}, mean=0.5)
    stock = _stock_workers(spec, workers=1)
    ordered = _two_workers(spec, durations, workers=1)

    stock.run_to_completion()
    ordered.run_to_completion()

    assert stock.scopes_sent() == ["tests/test_new.py", "tests/test_a.py", "tests/test_b.py"]
    # b: 6.0 s recorded; new: 10 tests x 0.5 s = 5.0 s estimated; a: 4.0 s recorded.
    assert ordered.scopes_sent() == ["tests/test_b.py", "tests/test_new.py", "tests/test_a.py"]


def test_a_recorded_zero_second_file_is_not_mistaken_for_an_unseen_one() -> None:
    spec = {"tests/test_zero.py": 100, "tests/test_one.py": 1}
    durations = _durations({"tests/test_zero.py": 0.0}, mean=0.5)
    run = _two_workers(spec, durations, workers=1)

    run.run_to_completion()

    assert run.scopes_sent() == ["tests/test_one.py", "tests/test_zero.py"]
    assert durations.estimate("tests/test_zero.py", 100) == 0.0
    assert durations.estimate("tests/test_unseen.py", 100) == 50.0


@pytest.mark.parametrize(
    ("spec", "recorded"),
    [
        pytest.param(
            {"tests/test_c.py": 3, "tests/test_b.py": 2, "tests/test_a.py": 1},
            {"tests/test_c.py": 5.0, "tests/test_b.py": 5.0, "tests/test_a.py": 5.0},
            id="equal-recorded-seconds-keep-the-count-order",
        ),
        pytest.param(
            {"tests/test_z.py": 2, "tests/test_x.py": 2, "tests/test_y.py": 2},
            {},
            id="equal-estimates-keep-the-collection-order",
        ),
    ],
)
def test_ties_keep_xdists_own_order(spec: dict[str, int], recorded: dict[str, float]) -> None:
    stock = _stock_workers(spec, workers=1)
    ordered = _two_workers(spec, _durations(recorded), workers=1)

    stock.run_to_completion()
    ordered.run_to_completion()

    assert ordered.scopes_sent() == stock.scopes_sent()
    assert len(ordered.scopes_sent()) == len(spec)


def test_a_run_to_completion_sends_every_node_exactly_once_and_shuts_every_node_down() -> None:
    rng = random.Random(1270)
    spec = {f"tests/test_{number:02d}.py": rng.randint(1, 9) for number in range(40)}
    recorded = {path: round(rng.uniform(0.0, 50.0), 1) for path in list(spec)[:30]}
    run = _two_workers(spec, _durations(recorded, mean=0.7), workers=4)

    executed = run.run_to_completion()

    flat = [nodeid for nodeids in executed.values() for nodeid in nodeids]
    assert sorted(flat) == sorted(run.collection)
    assert len(flat) == len(set(flat))
    assert run.scheduler.tests_finished
    assert all(node.shutdowns >= 1 for node in run.nodes)
    owners: dict[str, set[str]] = {}
    for worker, nodeids in executed.items():
        for nodeid in nodeids:
            owners.setdefault(_scope(nodeid), set()).add(worker)
    assert set(owners) == set(spec)
    assert all(len(workers) == 1 for workers in owners.values()), "loadfile keeps a file on one worker"


def test_mismatched_collections_still_abort_through_xdist_and_nothing_is_sent_or_printed() -> None:
    run = _two_workers(_SPEC, _durations(_RECORDED), diverge=True)

    assert run.scheduler.collection is None
    assert [report.outcome for report in run.config.collect_reports] == ["failed"]
    assert all(node.sent == [] for node in run.nodes)
    assert run.config.lines == []


def test_workers_beyond_the_number_of_files_are_shut_down_and_get_no_work() -> None:
    spec = {"tests/test_a.py": 4, "tests/test_b.py": 4}
    run = _two_workers(spec, _durations({"tests/test_a.py": 1.0, "tests/test_b.py": 9.0}), workers=4)

    assert [len(node.sent) for node in run.nodes] == [1, 1, 0, 0]
    assert run.scheduler.nodes == run.nodes[:2]
    assert all(node.shutting_down for node in run.nodes)
    assert run.scopes_sent() == ["tests/test_b.py", "tests/test_a.py"]


def test_the_order_is_applied_once_a_crash_requeue_lands_at_the_tail_and_later_schedules_do_not_resort() -> None:
    spec = {f"tests/test_{name}.py": 5 for name in "abcd"}
    recorded = {
        "tests/test_a.py": 10.0,
        "tests/test_b.py": 40.0,
        "tests/test_c.py": 30.0,
        "tests/test_d.py": 20.0,
    }
    run = _two_workers(spec, _durations(recorded))
    crashed, survivor = run.nodes
    assert run.scopes_sent() == ["tests/test_b.py", "tests/test_c.py"]
    assert list(run.scheduler.workqueue) == ["tests/test_d.py", "tests/test_a.py"]

    assert run.scheduler.remove_node(crashed) is not None
    tail = ["tests/test_d.py", "tests/test_a.py", "tests/test_b.py"]
    assert list(run.scheduler.workqueue) == tail, "the heaviest unit is requeued at the tail"
    run.scheduler.schedule()
    assert list(run.scheduler.workqueue) == tail, "a later schedule() must not re-sort"

    for index in survivor.sent[0][:3]:
        run.scheduler.mark_test_complete(survivor, index)
    assert _scope(run.collection[survivor.sent[-1][0]]) == "tests/test_d.py"
    assert len(run.config.lines) == 1


def test_the_rebuild_is_in_place_with_the_same_scope_keys_and_work_unit_objects() -> None:
    class Recording(DurationOrderedLoadFileScheduling):
        before: list[tuple[str, dict[str, bool]]] | None = None

        def _assign_work_unit(self, node: Any) -> None:
            if self.before is None:
                self.before = list(self.workqueue.items())
            super()._assign_work_unit(node)

    durations = _durations(_RECORDED)
    run = _Run(lambda config: Recording(config, _QUIET, durations=durations), _SPEC, start=False)
    scheduler = run.scheduler
    queue = scheduler.workqueue

    scheduler.schedule()

    assert scheduler.workqueue is queue and isinstance(queue, OrderedDict)
    assert [scope for scope, _ in scheduler.before] == [  # xdist's own order, before the rebuild
        "tests/test_many.py",
        "tests/test_mid.py",
        "tests/test_unit.py",
        "tests/test_heavy.py",
    ]
    after = dict(queue)
    for assigned in scheduler.assigned_work.values():
        after.update(assigned)
    assert set(after) == {scope for scope, _ in scheduler.before}
    assert all(after[scope] is unit for scope, unit in scheduler.before)
    assert scheduler.collection == run.collection
    assert all(scheduler.registered_collections[node] == run.collection for node in run.nodes)


def test_scheduling_writes_nothing_to_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    committed = DURATIONS_PATH.read_bytes()
    spec, _ = _suite(1272)
    run = _Run(lambda config: make_duration_scheduler(config, _QUIET), spec, workers=3)

    run.run_to_completion()

    assert list(tmp_path.iterdir()) == []
    assert DURATIONS_PATH.read_bytes() == committed


def test_an_error_before_the_first_assignment_still_clears_the_one_shot_flag() -> None:
    run = _two_workers({"tests/test_a.py": 3}, _durations({"tests/test_a.py": 1.0}), workers=3, start=False)

    def refuse(*_: Any) -> None:
        raise RuntimeError("worker gone")

    run.nodes[2].shutdown = refuse  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="worker gone"):
        run.scheduler.schedule()
    assert run.config.lines == []

    run.scheduler.schedule()

    assert run.config.lines == [], "the failed first distribution must not leave the order armed"


# --- Reporting: exactly one line per loadfile session ----------------------------------


def _dead_nodes_run(*, with_terminal: bool = True) -> _Run:
    """Both workers die after collecting and before the first distribution."""
    run = _two_workers(_SPEC, _durations(_RECORDED), start=False, with_terminal=with_terminal)
    for node in run.nodes:
        assert run.scheduler.remove_node(node) is None
    run.scheduler.schedule()
    return run


def test_the_applied_line_counts_recorded_and_estimated_files() -> None:
    run = _two_workers(_SPEC, _durations(_RECORDED))

    assert run.config.lines == [
        f"{REPORT_PREFIX} LPT order over 4 files (4 recorded, 0 estimated) from {DURATIONS_NAME}"
    ]


@pytest.mark.parametrize(
    ("unseen", "ellipsis"),
    [pytest.param(5, "", id="five-estimated-are-all-named"), pytest.param(8, ", ...", id="more-than-five-are-cut")],
)
def test_the_applied_line_names_at_most_five_estimated_files(unseen: int, ellipsis: str) -> None:
    spec = {f"tests/test_new_{number}.py": number for number in range(unseen, 0, -1)}
    spec["tests/test_known.py"] = 2
    run = _two_workers(spec, _durations({"tests/test_known.py": 3.0}, mean=0.5))

    named = ", ".join(f"tests/test_new_{number}.py" for number in range(unseen, unseen - 5, -1))
    assert run.config.lines == [
        f"{REPORT_PREFIX} LPT order over {unseen + 1} files (1 recorded, {unseen} estimated at "
        f"0.5000 s/test; {named}{ellipsis}) from {DURATIONS_NAME}"
    ]


def test_a_first_distribution_that_never_assigns_prints_order_not_applied() -> None:
    run = _dead_nodes_run()

    assert run.scheduler.collection == run.collection
    assert run.events == []
    [line] = run.config.lines
    assert line.startswith(f"{REPORT_PREFIX} order NOT applied")
    assert "LPT order" not in line


def test_an_empty_collection_prints_nothing() -> None:
    run = _two_workers({}, _durations(_RECORDED))

    assert run.scheduler.collection == []
    assert run.config.lines == []


def test_without_a_terminal_reporter_the_not_applied_line_is_a_logging_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=ds.__name__):
        run = _dead_nodes_run(with_terminal=False)

    records = [record for record in caplog.records if record.name == ds.__name__]
    assert [record.levelno for record in records] == [logging.WARNING]
    assert records[0].getMessage().startswith(f"{REPORT_PREFIX} order NOT applied")
    assert run.config.lines == []


def test_without_a_terminal_reporter_the_applied_line_is_a_logging_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=ds.__name__):
        _two_workers(_SPEC, _durations(_RECORDED), with_terminal=False)

    messages = [record.getMessage() for record in caplog.records if record.name == ds.__name__]
    assert messages == [
        f"{REPORT_PREFIX} LPT order over 4 files (4 recorded, 0 estimated) from {DURATIONS_NAME}"
    ]


# --- Activation: when the hook returns the subclass, and when it must return None ------


@pytest.mark.parametrize("dist", ["each", "load", "loadscope", "loadgroup", "worksteal", "no"])
def test_other_dist_modes_return_none_without_printing(dist: str) -> None:
    config = _Config(dist=dist)

    assert make_duration_scheduler(config, _QUIET) is None
    assert config.lines == []


def test_no_loadscope_reorder_returns_none_and_prints_one_disabled_line() -> None:
    config = _Config(reorder=False)

    assert make_duration_scheduler(config, _QUIET) is None
    assert config.lines == [
        f"{REPORT_PREFIX} disabled (--no-loadscope-reorder); "
        "using xdist's stock LoadFileScheduling order"
    ]


def test_loadfile_with_the_committed_data_returns_the_subclass() -> None:
    config = _Config()

    scheduler = make_duration_scheduler(config, _QUIET)

    assert isinstance(scheduler, DurationOrderedLoadFileScheduling)
    assert isinstance(scheduler, LoadFileScheduling)
    assert isinstance(scheduler.workqueue, OrderedDict)
    assert scheduler.collection is None
    assert config.lines == [], "the line is printed when the order is applied, not when it is built"


def test_absent_data_returns_none_and_prints_one_disabled_line(tmp_path: Path) -> None:
    config = _Config()

    assert make_duration_scheduler(config, _QUIET, durations_path=tmp_path / "missing.json") is None
    assert config.lines == [
        f"{REPORT_PREFIX} disabled (missing.json is unreadable (FileNotFoundError)); "
        "using xdist's stock LoadFileScheduling order"
    ]


def test_a_directory_and_a_non_utf8_file_are_unreadable(tmp_path: Path) -> None:
    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\xff\xfe\x00{")

    with pytest.raises(DurationDataError, match="unreadable"):
        load_file_durations(tmp_path)
    with pytest.raises(DurationDataError, match="UnicodeDecodeError"):
        load_file_durations(binary)


def _mutated(mutate: Callable[[dict[str, Any]], None]) -> Callable[[], str]:
    def build() -> str:
        payload = _valid_payload()
        mutate(payload)
        return json.dumps(payload)

    return build


def _with_source(**changes: Any) -> Callable[[], str]:
    return _mutated(lambda payload: payload["source"].update(changes))


def _with_top(**changes: Any) -> Callable[[], str]:
    return _mutated(lambda payload: payload.update(changes))


def _with_file_key(key: str) -> Callable[[], str]:
    return _mutated(lambda payload: payload.update(files={key: 1.0}))


def _swap_first_file_seconds(token: str) -> Callable[[], str]:
    return lambda: json.dumps(_valid_payload()).replace('"tests/test_a.py": 1.5', f'"tests/test_a.py": {token}')


def _without(*path: str) -> Callable[[], str]:
    def delete(payload: dict[str, Any]) -> None:
        holder = payload
        for key in path[:-1]:
            holder = holder[key]
        del holder[path[-1]]

    return _mutated(delete)


_INVALID_DATA: list[tuple[str, Callable[[], str], str]] = [
    ("malformed-json", lambda: "{", "not valid JSON"),
    ("deeply-nested-json", lambda: "[" * 100_000, "nested too deeply"),
    ("top-level-array", lambda: "[]", "must hold exactly"),
    ("duplicate-key", lambda: '{"schema_version": 1, "schema_version": 1}', "repeats a key"),
    ("nan-seconds", _swap_first_file_seconds("NaN"), "non-finite JSON constant NaN"),
    ("infinite-seconds", _swap_first_file_seconds("Infinity"), "non-finite JSON constant Infinity"),
    ("negative-infinite-seconds", _swap_first_file_seconds("-Infinity"), "non-finite JSON constant -Infinity"),
    ("overflowing-seconds", _swap_first_file_seconds("1e999"), "is not finite"),
    ("huge-integer-seconds", _swap_first_file_seconds("1" + "0" * 400), "is out of range"),
    ("schema-version-two", _with_top(schema_version=2), "schema_version must be 1"),
    ("schema-version-bool", _with_top(schema_version=True), "schema_version must be 1"),
    ("schema-version-string", _with_top(schema_version="1"), "schema_version must be 1"),
    ("missing-top-level-key", _without("mean_test_seconds"), "must hold exactly"),
    ("extra-top-level-key", _with_top(extra=1), "must hold exactly"),
    ("source-not-an-object", _with_top(source=[]), "source must hold exactly"),
    ("source-missing-key", _without("source", "testcases"), "source must hold exactly"),
    ("source-extra-key", _with_source(extra=1), "source must hold exactly"),
    ("source-junit-with-a-path", _with_source(junit="logs/run.xml"), "source.junit must be a file basename"),
    ("source-junit-with-a-backslash", _with_source(junit="logs\\run.xml"), "source.junit must be a file basename"),
    ("source-collection-empty", _with_source(collection=""), "source.collection must be a file basename"),
    ("source-sha-uppercase", _with_source(junit_sha256="A" * 64), "64 lowercase hex"),
    ("source-sha-short", _with_source(collection_sha256="a" * 63), "64 lowercase hex"),
    ("source-sha-trailing-newline", _with_source(junit_sha256="a" * 64 + "\n"), "64 lowercase hex"),
    ("source-testcases-bool", _with_source(testcases=True), "source.testcases must be an int > 0"),
    ("source-testcases-zero", _with_source(testcases=0), "source.testcases must be an int > 0"),
    ("source-testcases-float", _with_source(testcases=10.0), "source.testcases must be an int > 0"),
    ("source-total-negative", _with_source(total_seconds=-1.0), "source.total_seconds must be >= 0"),
    ("source-total-bool", _with_source(total_seconds=True), "source.total_seconds is not a number"),
    ("mean-bool", _with_top(mean_test_seconds=True), "mean_test_seconds is not a number"),
    ("mean-string", _with_top(mean_test_seconds="0.5"), "mean_test_seconds is not a number"),
    ("mean-zero", _with_top(mean_test_seconds=0), "mean_test_seconds must be > 0"),
    ("mean-negative", _with_top(mean_test_seconds=-0.1), "mean_test_seconds must be > 0"),
    ("seconds-bool", _with_top(files={"tests/test_a.py": True}), "is not a number"),
    ("seconds-string", _with_top(files={"tests/test_a.py": "1.5"}), "is not a number"),
    ("seconds-negative", _with_top(files={"tests/test_a.py": -1}), "must be >= 0"),
    ("files-empty", _with_top(files={}), "files must be a non-empty object"),
    ("files-not-an-object", _with_top(files=[]), "files must be a non-empty object"),
    ("key-absolute-posix", _with_file_key("/abs/test_a.py"), "relative test path"),
    ("key-absolute-windows", _with_file_key("C:/abs/test_a.py"), "relative test path"),
    ("key-backslash", _with_file_key("tests\\test_a.py"), "relative test path"),
    ("key-dotdot-segment", _with_file_key("tests/../test_a.py"), "relative test path"),
    ("key-nodeid", _with_file_key("tests/test_a.py::test_one"), "relative test path"),
    ("key-empty", _with_file_key(""), "relative test path"),
]


def test_the_baseline_payload_the_invalid_cases_start_from_is_valid(tmp_path: Path) -> None:
    path = tmp_path / "file_durations.json"
    path.write_text(json.dumps(_valid_payload()), encoding="utf-8")

    loaded = load_file_durations(path)

    assert dict(loaded.files) == {"tests/test_a.py": 1.5, "tests/test_b.py": 0.0}
    assert loaded.mean_test_seconds == 0.5
    with pytest.raises(TypeError):
        loaded.files["tests/test_c.py"] = 1.0  # type: ignore[index]


def test_whole_number_seconds_load_as_floats(tmp_path: Path) -> None:
    path = tmp_path / "file_durations.json"
    path.write_text(_with_top(files={"tests/test_a.py": 3})(), encoding="utf-8")

    assert dict(load_file_durations(path).files) == {"tests/test_a.py": 3.0}


@pytest.mark.parametrize(
    ("build", "message"),
    [pytest.param(build, message, id=name) for name, build, message in _INVALID_DATA],
)
def test_invalid_data_is_refused_and_the_stock_order_is_used(
    tmp_path: Path, build: Callable[[], str], message: str
) -> None:
    path = tmp_path / "file_durations.json"
    path.write_text(build(), encoding="utf-8")

    with pytest.raises(DurationDataError) as refused:
        load_file_durations(path)
    assert message in str(refused.value)

    config = _Config()
    assert make_duration_scheduler(config, _QUIET, durations_path=path) is None
    [line] = config.lines
    assert line.startswith(f"{REPORT_PREFIX} disabled (")
    assert line.endswith("); using xdist's stock LoadFileScheduling order")


@pytest.mark.parametrize("name", ["schedule", "_assign_work_unit"])
def test_missing_xdist_internals_return_none_and_print_one_disabled_line(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(LoadScopeScheduling, name, None)
    config = _Config()

    assert make_duration_scheduler(config, _QUIET) is None
    [line] = config.lines
    assert line == (
        f"{REPORT_PREFIX} disabled (xdist LoadFileScheduling has no {name}); "
        "using xdist's stock LoadFileScheduling order"
    )


@pytest.mark.parametrize(("attribute", "value"), [("workqueue", {}), ("collection", [])])
def test_an_unexpected_initial_state_is_not_used(
    monkeypatch: pytest.MonkeyPatch, attribute: str, value: Any
) -> None:
    original = LoadFileScheduling.__init__

    def init(self: LoadFileScheduling, config: Any, log: Any = None) -> None:
        original(self, config, log)
        setattr(self, attribute, value)

    monkeypatch.setattr(LoadFileScheduling, "__init__", init)
    config = _Config()

    assert make_duration_scheduler(config, _QUIET) is None
    [line] = config.lines
    assert line.startswith(f"{REPORT_PREFIX} disabled (") and "OrderedDict" in line


# --- The conftest hook: registration and delegation ------------------------------------


def _registered_hook_impls(config: pytest.Config) -> list[Any]:
    caller = config.pluginmanager.hook.pytest_xdist_make_scheduler
    return [
        impl
        for impl in caller.get_hookimpls()
        if Path(impl.function.__code__.co_filename).resolve() == _CONFTEST
    ]


def test_the_conftest_hookimpl_is_registered_optional_and_neither_first_nor_last(
    pytestconfig: pytest.Config,
) -> None:
    [impl] = _registered_hook_impls(pytestconfig)

    assert impl.function.__name__ == "pytest_xdist_make_scheduler"
    assert impl.optionalhook is True
    assert not impl.tryfirst and not impl.trylast
    assert not impl.hookwrapper and not impl.wrapper
    assert tuple(impl.argnames) == ("config", "log")


def test_the_hook_delegates_to_make_duration_scheduler_with_its_own_arguments(
    pytestconfig: pytest.Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    [impl] = _registered_hook_impls(pytestconfig)
    seen: list[tuple[Any, Any]] = []
    sentinel = object()
    monkeypatch.setattr(
        ds, "make_duration_scheduler", lambda config, log: seen.append((config, log)) or sentinel
    )
    config = _Config()

    assert impl.function(config, _QUIET) is sentinel
    assert seen == [(config, _QUIET)]


def test_pluggy_dispatch_reaches_the_conftest_hook_and_returns_the_subclass(
    pytestconfig: pytest.Config,
) -> None:
    result = pytestconfig.pluginmanager.hook.pytest_xdist_make_scheduler(
        config=_Config(), log=_QUIET
    )

    assert isinstance(result, DurationOrderedLoadFileScheduling)


def test_pluggy_dispatch_for_another_dist_mode_does_not_return_the_subclass(
    pytestconfig: pytest.Config,
) -> None:
    result = pytestconfig.pluginmanager.hook.pytest_xdist_make_scheduler(
        config=_Config(dist="load"), log=_QUIET
    )

    assert not isinstance(result, DurationOrderedLoadFileScheduling)


# --- The committed data, the xdist pin, and the canonical wrapper's checks --------------


def test_the_committed_durations_file_loads_as_valid() -> None:
    durations = load_file_durations(DURATIONS_PATH)

    assert len(durations.files) > 1000
    assert 0 < durations.mean_test_seconds < 5
    assert all(path.startswith("tests/") and path.endswith(".py") for path in durations.files)


def test_xdist_is_the_version_the_private_internals_were_verified_against() -> None:
    """The override leans on ``LoadScopeScheduling._assign_work_unit`` (private) and on
    ``schedule()`` calling it only after the whole work queue is built. ``uv.lock`` pins
    3.8.0. When xdist is upgraded, re-verify the first-pop contract the scheduling tests
    above encode, then move this pin."""
    assert xdist.__version__.startswith("3.8."), (
        f"xdist {xdist.__version__}: re-verify DurationOrderedLoadFileScheduling against "
        "its LoadScopeScheduling.schedule, then update this pin"
    )
    assert LoadFileScheduling._assign_work_unit is LoadScopeScheduling._assign_work_unit
    assert LoadFileScheduling.schedule is LoadScopeScheduling.schedule
    assert list(inspect.signature(LoadScopeScheduling._assign_work_unit).parameters) == ["self", "node"]


@pytest.fixture(scope="module")
def gate() -> Iterator[ModuleType]:
    """The unmodified wrapper, under a private module name so nothing else sees it."""
    name = "_ad1270f_p14_run_test_gate"
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / "run_test_gate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(name, None)


def _validate_with_the_wrapper(
    gate: ModuleType, tmp_path: Path, run: _Run, executed: dict[str, list[str]]
) -> Any:
    """Write the per-worker manifests ``scripts/_gate_pytest_plugin.py`` would write, then validate."""
    directory = tmp_path / "workers"
    directory.mkdir()
    collected = sorted(run.collection)
    digest = gate._node_digest(collected)
    for worker, nodeids in executed.items():
        payload: dict[str, Any] = {
            "schema_version": 1,
            "worker_id": worker,
            "exitstatus": 0,
            "collection_count": len(collected),
            "collection_sha256": digest,
            "final_count": len(collected),
            "final_sha256": digest,
            "removed_nodeids": [],
            "added_nodeids": [],
            "executed_nodeids": sorted(nodeids),
        }
        if worker == "gw0":
            payload["collected_nodeids"] = collected
            payload["collected_files"] = sorted({_scope(nodeid) for nodeid in collected})
        (directory / f"{worker}.json").write_text(json.dumps(payload), encoding="utf-8")
    return gate._validate_collection_manifests(
        directory,
        tmp_path / "run.collection.json",
        expected_workers=len(run.nodes),
        required_test_files=set(),
        junit_totals=gate.JUnitTotals(
            tests=len(collected), failures=0, errors=0, skipped=0, time_seconds=1.0
        ),
    )


def _suite(seed: int) -> tuple[dict[str, int], FileDurations]:
    rng = random.Random(seed)
    spec = {f"tests/test_{number:02d}.py": rng.randint(1, 9) for number in range(25)}
    recorded = {path: round(rng.uniform(0.0, 40.0), 1) for path in list(spec)[:20]}
    return spec, _durations(recorded, mean=0.6)


def test_manifests_from_a_scheduled_run_pass_the_unmodified_wrapper_check(
    gate: ModuleType, tmp_path: Path
) -> None:
    spec, durations = _suite(1271)
    run = _two_workers(spec, durations, workers=4)
    executed = run.run_to_completion()

    totals = _validate_with_the_wrapper(gate, tmp_path, run, executed)

    artifact = json.loads((tmp_path / "run.collection.json").read_bytes())
    assert totals.nodes == len(run.collection) == artifact["collection_count"]
    assert totals.workers == 4
    assert sum(artifact["worker_execution_counts"].values()) == len(run.collection)
    assert sorted(artifact["executed_nodeids"]) == sorted(run.collection)


class _LosesTheLightestUnit(DurationOrderedLoadFileScheduling):
    """A broken scheduler: it quietly drops one unassigned work unit."""

    _dropped = False

    def _assign_work_unit(self, node: Any) -> None:
        super()._assign_work_unit(node)
        if not self._dropped and self.workqueue:
            self._dropped = True
            self.workqueue.popitem(last=True)


def test_a_subclass_that_drops_one_work_unit_is_rejected_by_the_wrapper_check(
    gate: ModuleType, tmp_path: Path
) -> None:
    durations = _durations(_RECORDED)
    run = _Run(
        lambda config: _LosesTheLightestUnit(config, _QUIET, durations=durations), _SPEC
    )
    executed = run.run_to_completion()

    missing = [nodeid for nodeid in run.collection if nodeid not in sum(executed.values(), [])]
    assert missing == [f"tests/test_unit.py::test_{number}" for number in range(3)]
    with pytest.raises(RuntimeError, match="execution does not match protected collection") as refused:
        _validate_with_the_wrapper(gate, tmp_path, run, executed)
    assert "tests/test_unit.py::test_0" in str(refused.value)
