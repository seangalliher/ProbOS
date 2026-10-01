"""P0.5 -- per-worker gate timing, the shared busy-time helper, the duration budget.

Measurement only. Nothing here is release authority: only a validated success
receipt from the gate wrapper is. Every test asserts its own premise first (the
worker files exist, the boundary input really sits on the boundary, the control
run really takes the other branch), because a probe that finds nothing is
indistinguishable from a probe that never ran.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN = REPO_ROOT / "scripts" / "_gate_pytest_plugin.py"
HELPER = REPO_ROOT / "scripts" / "_gate_timing.py"

EVENT_NAMES = (
    "plugin_loaded",
    "session_start",
    "collection_finished",
    "first_test_start",
    "last_test_end",
    "session_finish",
)
PRE_EXISTING_KEYS = {
    "schema_version",
    "worker_id",
    "exitstatus",
    "collection_count",
    "collection_sha256",
    "final_count",
    "final_sha256",
    "removed_nodeids",
    "added_nodeids",
    "executed_nodeids",
}


def _load_timing() -> ModuleType:
    name = "_gate_timing"
    cached = sys.modules.get(name)
    cached_file = getattr(cached, "__file__", None)
    if cached is not None and cached_file and Path(cached_file).resolve() == HELPER:
        return cached
    spec = importlib.util.spec_from_file_location(name, HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def timing() -> ModuleType:
    return _load_timing()


# ---------------------------------------------------------------------------
# A real two-worker pytest run through the plugin
# ---------------------------------------------------------------------------

_ALPHA = '''\
import time

import pytest


@pytest.fixture
def padded():
    time.sleep(0.1)
    yield
    time.sleep(0.1)


def test_one(padded):
    time.sleep(0.15)


def test_two():
    time.sleep(0.15)


def test_three():
    time.sleep(0.15)
'''

_BETA = '''\
import time

import pytest


@pytest.mark.parametrize("step", [1, 2])
def test_param(step):
    time.sleep(0.1)


@pytest.mark.skip(reason="a skipped node still executes its terminal report")
def test_skipped():
    raise AssertionError("never runs")
'''

#: file -> (executed node count, lower bound of the summed phase durations).
#: alpha: setup 0.1 + call 0.15 + teardown 0.1 for one test, 0.15 for two more.
EXPECTED_FILES = {
    "t/test_alpha.py": (3, 0.65),
    "t/test_beta.py": (3, 0.2),
}
CLOCK_SLACK = 0.02


@dataclass(frozen=True)
class RealRun:
    returncode: int
    output: str
    workers_dir: Path
    junit: Path
    wall_before: float
    wall_after: float


def _isolated_env(workers_dir: Path) -> dict[str, str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("PYTEST_", "COV_CORE", "COVERAGE"))
    }
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PROBOS_GATE_COLLECTION_DIR"] = str(workers_dir)
    return env


def _run_real_gate(root: Path, sources: dict[str, str]) -> RealRun:
    """Run real pytest, two xdist workers, loadfile, through the gate plugin."""
    suite = root / "t"
    suite.mkdir()
    for name, source in sources.items():
        (suite / name).write_text(source, encoding="utf-8")
    workers_dir = root / "workers"
    junit = root / "run.xml"
    wall_before = time.time()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "t",
            "-q",
            "-p",
            "scripts._gate_pytest_plugin",
            "-n",
            "2",
            "--dist=loadfile",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
            "-o",
            "junit_family=legacy",
            f"--junitxml={junit}",
        ],
        cwd=root,
        env=_isolated_env(workers_dir),
        capture_output=True,
        text=True,
        timeout=300,
    )
    return RealRun(
        returncode=completed.returncode,
        output=completed.stdout + completed.stderr,
        workers_dir=workers_dir,
        junit=junit,
        wall_before=wall_before,
        wall_after=time.time(),
    )


@pytest.fixture(scope="module")
def real_run(tmp_path_factory: pytest.TempPathFactory) -> RealRun:
    return _run_real_gate(
        tmp_path_factory.mktemp("gate-timing-real"),
        {"test_alpha.py": _ALPHA, "test_beta.py": _BETA},
    )


_SMALL = "import time\n\n\ndef test_a():\n    time.sleep(0.02)\n\n\ndef test_b():\n    time.sleep(0.02)\n"


@pytest.fixture(scope="module")
def real_run_many(tmp_path_factory: pytest.TempPathFactory) -> RealRun:
    """Six files over two workers, so at least one worker owns several files."""
    return _run_real_gate(
        tmp_path_factory.mktemp("gate-timing-many"),
        {f"test_m{index}.py": _SMALL for index in range(6)},
    )


def _worker_payloads(run: RealRun) -> dict[str, dict[str, Any]]:
    """Assert the premise (both worker files exist) before anything reads them."""
    assert run.returncode == 0, run.output[-1500:]
    missing = [
        name
        for name in ("gw0.json", "gw1.json")
        if not (run.workers_dir / name).is_file()
    ]
    assert not missing, f"premise: missing {missing}; output: {run.output[-1500:]}"
    return {
        name: json.loads((run.workers_dir / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("gw0", "gw1")
    }


# ---------------------------------------------------------------------------
# Synthetic per-worker evidence and JUnit reports
# ---------------------------------------------------------------------------


def _stamp(monotonic: float) -> dict[str, float]:
    return {"monotonic": monotonic, "wall": 1_800_000_000.0 + monotonic}


def _block(
    files: dict[str, tuple[float, int]], **event_overrides: Any
) -> dict[str, Any]:
    events: dict[str, Any] = {
        "plugin_loaded": _stamp(100.0),
        "session_start": _stamp(101.0),
        "collection_finished": _stamp(171.0),
        "first_test_start": _stamp(181.5),
        "last_test_end": _stamp(331.5),
        "session_finish": _stamp(332.0),
    }
    events.update(event_overrides)
    return {
        "version": 1,
        "events": events,
        "files": {
            name: {
                "first_start": _stamp(181.5),
                "last_end": _stamp(331.5),
                "duration_seconds": seconds,
                "node_count": count,
            }
            for name, (seconds, count) in files.items()
        },
    }


def _write_worker(
    directory: Path,
    index: int,
    nodes: list[str],
    timing_block: dict[str, Any] | None = None,
    **overrides: Any,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "worker_id": f"gw{index}",
        "exitstatus": 0,
        "executed_nodeids": sorted(nodes),
    }
    if timing_block is not None:
        payload["timing"] = timing_block
    payload.update(overrides)
    path = directory / f"gw{index}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _file_cases(file: str, times: list[float]) -> list[tuple[str, str, str, float]]:
    module = file.removesuffix(".py").replace("/", ".")
    return [(file, module, f"test_{index}", seconds) for index, seconds in enumerate(times)]


def _nodes(file: str, count: int) -> list[str]:
    return [f"{file}::test_{index}" for index in range(count)]


def _write_junit(path: Path, cases: list[tuple[str, str, str, float]]) -> Path:
    """A JUnit report that keeps every digit (pytest itself writes three decimals)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(
        f'<testcase classname="{classname}" name="{name}" file="{file}" '
        f'time="{seconds!r}"/>'
        for file, classname, name, seconds in cases
    )
    path.write_text(
        '<?xml version="1.0"?><testsuites><testsuite name="pytest" '
        f'tests="{len(cases)}">{body}</testsuite></testsuites>',
        encoding="utf-8",
    )
    return path


#: Four workers whose busy times are 150, 120, 110 and 20 s: mean exactly 100 s.
BUDGET_FILES: dict[str, list[float]] = {
    "tests/test_big.py": [12.0, 10.0] + [10.0] * 12 + [8.0],
    "tests/test_edge.py": [10.0] * 12,
    "tests/test_mid.py": [10.0] * 6,
    "tests/test_small.py": [10.0] * 5,
    "tests/test_fill.py": [10.0] * 2,
}
BUDGET_ASSIGNMENT: dict[int, list[str]] = {
    0: ["tests/test_big.py"],
    1: ["tests/test_edge.py"],
    2: ["tests/test_mid.py", "tests/test_small.py"],
    3: ["tests/test_fill.py"],
}


def _budget_scenario(tmp_path: Path, *, with_timing: bool) -> tuple[Path, Path]:
    junit = _write_junit(
        tmp_path / "run.xml",
        [
            case
            for file, times in BUDGET_FILES.items()
            for case in _file_cases(file, times)
        ],
    )
    workers = tmp_path / "run.collection-workers"
    for index, files in BUDGET_ASSIGNMENT.items():
        nodes = [node for file in files for node in _nodes(file, len(BUDGET_FILES[file]))]
        block = (
            _block({file: (sum(BUDGET_FILES[file]), len(BUDGET_FILES[file])) for file in files})
            if with_timing
            else None
        )
        _write_worker(workers, index, nodes, block)
    return junit, workers


def test_real_run_keeps_every_existing_key_and_adds_only_a_timing_block(
    real_run: RealRun,
) -> None:
    payloads = _worker_payloads(real_run)

    assert sorted(path.name for path in real_run.workers_dir.iterdir()) == [
        "gw0.json",
        "gw1.json",
    ]
    for name, payload in payloads.items():
        expected = PRE_EXISTING_KEYS | {"timing"}
        if name == "gw0":
            expected |= {"collected_nodeids", "collected_files"}
        assert set(payload) == expected
        assert payload["schema_version"] == 1
        assert payload["exitstatus"] == 0
        assert payload["timing"]["version"] == 1
        assert set(payload["timing"]) == {"version", "events", "files"}


def test_real_run_records_all_six_events_as_finite_stamps(real_run: RealRun) -> None:
    payloads = _worker_payloads(real_run)

    for payload in payloads.values():
        events = payload["timing"]["events"]
        assert set(events) == set(EVENT_NAMES)
        assert len(payload["timing"]["files"]) == 1, "premise: one file per worker"
        for name in EVENT_NAMES:
            stamp = events[name]
            assert set(stamp) == {"monotonic", "wall"}, name
            assert math.isfinite(stamp["monotonic"]) and math.isfinite(stamp["wall"])
            assert real_run.wall_before - 1 <= stamp["wall"] <= real_run.wall_after + 1


def test_real_run_stamps_are_ordered_within_each_worker(real_run: RealRun) -> None:
    payloads = _worker_payloads(real_run)

    for name, payload in payloads.items():
        events = payload["timing"]["events"]
        files = payload["timing"]["files"]
        assert files, f"premise: {name} ran at least one file"
        for file_name, entry in files.items():
            chain = [
                events["plugin_loaded"]["monotonic"],
                events["session_start"]["monotonic"],
                events["collection_finished"]["monotonic"],
                events["first_test_start"]["monotonic"],
                entry["first_start"]["monotonic"],
                entry["last_end"]["monotonic"],
                events["last_test_end"]["monotonic"],
                events["session_finish"]["monotonic"],
            ]
            assert chain == sorted(chain), f"{name} {file_name}: {chain}"


def test_real_run_attributes_each_file_to_exactly_one_worker(
    real_run: RealRun,
) -> None:
    payloads = _worker_payloads(real_run)

    attributed: dict[str, list[str]] = {}
    for worker, payload in payloads.items():
        for file_name in payload["timing"]["files"]:
            attributed.setdefault(file_name, []).append(worker)
    assert sorted(attributed) == sorted(EXPECTED_FILES)
    assert all(len(workers) == 1 for workers in attributed.values()), attributed
    for worker, payload in payloads.items():
        for file_name, entry in payload["timing"]["files"].items():
            node_count, floor = EXPECTED_FILES[file_name]
            assert entry["node_count"] == node_count, file_name
            assert entry["duration_seconds"] >= floor - CLOCK_SLACK, file_name
        owned = sum(entry["node_count"] for entry in payload["timing"]["files"].values())
        assert owned == len(payload["executed_nodeids"]), worker


def test_real_run_with_several_files_per_worker_passes_the_strict_validation(
    real_run_many: RealRun, timing: ModuleType
) -> None:
    payloads = _worker_payloads(real_run_many)
    per_worker = {name: payload["timing"]["files"] for name, payload in payloads.items()}
    assert sum(len(files) for files in per_worker.values()) == 6, "premise: all six files ran"
    assert max(len(files) for files in per_worker.values()) >= 3, "premise: several files on one worker"

    load = timing.load_worker_evidence(real_run_many.workers_dir)

    assert load.errors == () and load.warnings == ()
    assert all(worker.timing is not None for worker in load.workers)
    busy = timing.compute_busy(load.workers, timing.read_junit_times(real_run_many.junit))
    assert busy is not None and busy["source"] == "timestamps"
    assert timing.evidence_problems(
        load.workers,
        {name: len(payload["executed_nodeids"]) for name, payload in payloads.items()},
        sorted(node for payload in payloads.values() for node in payload["executed_nodeids"]),
    ) == []


def test_real_run_duration_is_the_sum_of_setup_call_and_teardown(
    real_run: RealRun,
) -> None:
    payloads = _worker_payloads(real_run)

    files = {
        file_name: entry
        for payload in payloads.values()
        for file_name, entry in payload["timing"]["files"].items()
    }
    # Call-only accounting would give 0.45 s for alpha: the fixture adds 0.2 s.
    assert files["t/test_alpha.py"]["duration_seconds"] >= 0.65 - CLOCK_SLACK


def test_real_run_timestamps_and_junit_agree_on_busy_time(
    real_run: RealRun, timing: ModuleType
) -> None:
    payloads = _worker_payloads(real_run)
    junit = timing.read_junit_times(real_run.junit)
    assert junit.unresolved == 0, "premise: every JUnit testcase resolves to a node"

    load = timing.load_worker_evidence(real_run.workers_dir)
    assert load.errors == () and len(load.workers) == 2
    assert all(worker.timing is not None for worker in load.workers)
    busy = timing.compute_busy(load.workers, junit)
    assert busy is not None and busy["source"] == "timestamps"
    for entry, payload in zip(busy["workers"], payloads.values()):
        tolerance = 0.0005 * entry["executed_count"] + 0.001
        assert abs(entry["busy_seconds"] - entry["junit_busy_seconds"]) <= tolerance
        assert entry["executed_count"] == len(payload["executed_nodeids"])
    assert busy["unattributed_junit_seconds"] == 0.0


def test_plugin_adds_no_option_and_keeps_the_rewrite_guard() -> None:
    source = PLUGIN.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "PYTEST_DONT_REWRITE" in (ast.get_docstring(tree) or "")
    names = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert "pytest_addoption" not in names
    assert {
        "pytest_sessionstart",
        "pytest_collection_finish",
        "pytest_runtest_logstart",
        "pytest_runtest_logfinish",
    } <= names, "premise: the new hooks are present"


def test_only_the_collection_guard_in_the_plugin_can_raise() -> None:
    tree = ast.parse(PLUGIN.read_text(encoding="utf-8"))

    raising = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and any(isinstance(child, ast.Raise) for child in ast.walk(node))
    }
    assert raising == {"pytest_collection_modifyitems"}


def _fresh_plugin(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, PLUGIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _drive_one_worker_session(
    plugin: ModuleType,
    destination: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    first_nodeid: Any = "t/test_x.py::test_a",
    duration: Any = 0.25,
    before_finish: Any = None,
) -> dict[str, Any]:
    monkeypatch.setenv("PROBOS_GATE_COLLECTION_DIR", str(destination))
    report = SimpleNamespace(
        when="call",
        failed=False,
        skipped=False,
        nodeid="t/test_x.py::test_a",
        duration=duration,
    )
    plugin.pytest_sessionstart()
    plugin.pytest_collection_finish()
    plugin.pytest_runtest_logstart(first_nodeid)
    plugin.pytest_runtest_logreport(report)
    plugin.pytest_runtest_logfinish("t/test_x.py::test_a")
    if before_finish is not None:
        before_finish(plugin)
    session = SimpleNamespace(
        config=SimpleNamespace(workerinput={"workerid": "gw0"})
    )
    plugin.pytest_sessionfinish(session, 0)
    return json.loads((destination / "gw0.json").read_text(encoding="utf-8"))


def test_a_healthy_session_writes_a_timing_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = _fresh_plugin("gate_plugin_control")

    payload = _drive_one_worker_session(plugin, tmp_path, monkeypatch)

    assert payload["timing"]["files"]["t/test_x.py"]["node_count"] == 1
    assert payload["timing"]["files"]["t/test_x.py"]["duration_seconds"] == 0.25


def test_an_idle_worker_records_null_for_events_that_never_happened(
    timing: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = _fresh_plugin("gate_plugin_idle")
    monkeypatch.setenv("PROBOS_GATE_COLLECTION_DIR", str(tmp_path))
    plugin.pytest_sessionstart()
    plugin.pytest_collection_finish()
    session = SimpleNamespace(config=SimpleNamespace(workerinput={"workerid": "gw1"}))
    plugin.pytest_sessionfinish(session, 0)
    payload = json.loads((tmp_path / "gw1.json").read_text(encoding="utf-8"))

    events = payload["timing"]["events"]
    assert events["first_test_start"] is None and events["last_test_end"] is None
    for name in ("plugin_loaded", "session_start", "collection_finished", "session_finish"):
        assert events[name] is not None, name
    assert payload["timing"]["files"] == {}
    load = timing.load_worker_evidence(tmp_path)
    assert load.errors == () and load.warnings == ()
    assert load.workers[0].timing is not None, "the consumer accepts null stamps"


@pytest.mark.parametrize(
    ("first_nodeid", "duration"),
    [(None, 0.25), ("t/test_x.py::test_a", "not-a-number")],
    ids=["unusable-nodeid", "unusable-duration"],
)
def test_a_timing_fault_withholds_the_block_and_never_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_nodeid: Any,
    duration: Any,
) -> None:
    control = _drive_one_worker_session(
        _fresh_plugin("gate_plugin_fault_control"),
        tmp_path / "control",
        monkeypatch,
    )
    assert "timing" in control, "premise: the same session without a fault has timing"

    faulted = _drive_one_worker_session(
        _fresh_plugin("gate_plugin_fault"),
        tmp_path / "fault",
        monkeypatch,
        first_nodeid=first_nodeid,
        duration=duration,
    )

    assert "timing" not in faulted
    assert set(faulted) == set(control) - {"timing"}
    assert faulted["executed_nodeids"] == control["executed_nodeids"]


def _strict(text: str) -> Any:
    """Parse JSON the way a strict reader does: NaN and Infinity are errors."""

    def refuse(constant: str) -> None:
        raise ValueError(f"non-strict JSON constant {constant}")

    return json.loads(text, parse_constant=refuse)


@pytest.mark.parametrize(
    "duration",
    [float("nan"), float("inf"), -0.5],
    ids=["nan", "infinite", "negative"],
)
def test_a_non_finite_or_negative_report_duration_withholds_the_timing_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, duration: float
) -> None:
    control = _drive_one_worker_session(
        _fresh_plugin("gate_plugin_duration_control"), tmp_path / "control", monkeypatch
    )
    assert "timing" in control, "premise: a finite duration is recorded"

    faulted = _drive_one_worker_session(
        _fresh_plugin("gate_plugin_duration_fault"),
        tmp_path / "fault",
        monkeypatch,
        duration=duration,
    )

    assert "timing" not in faulted
    assert set(faulted) == set(control) - {"timing"}
    assert faulted["executed_nodeids"] == control["executed_nodeids"]
    _strict((tmp_path / "fault" / "gw0.json").read_text(encoding="utf-8"))


def test_a_timing_block_that_cannot_be_written_strictly_is_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def poison(plugin: ModuleType) -> None:
        plugin._TIMING_FILES["t/test_x.py"]["duration_seconds"] = float("inf")

    control = _drive_one_worker_session(
        _fresh_plugin("gate_plugin_strict_control"), tmp_path / "control", monkeypatch
    )
    assert "timing" in control, "premise: the same session writes a block"

    poisoned = _drive_one_worker_session(
        _fresh_plugin("gate_plugin_strict_fault"),
        tmp_path / "fault",
        monkeypatch,
        before_finish=poison,
    )

    assert "timing" not in poisoned
    assert set(poisoned) == set(control) - {"timing"}
    assert _strict((tmp_path / "fault" / "gw0.json").read_text(encoding="utf-8")) == poisoned


def test_the_timing_guard_does_not_swallow_a_keyboard_interrupt() -> None:
    plugin = _fresh_plugin("gate_plugin_interrupt")

    def interrupted() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        plugin._guarded(interrupted)


# ---------------------------------------------------------------------------
# Busy time, the critical path and the timeline
# ---------------------------------------------------------------------------


def _busy_for(
    timing: ModuleType, tmp_path: Path, *, with_timing: bool
) -> tuple[dict[str, Any], Any, Any]:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=with_timing)
    load = timing.load_worker_evidence(workers_dir)
    assert load.errors == () and len(load.workers) == 4, "premise: four valid workers"
    assert all((w.timing is not None) is with_timing for w in load.workers)
    junit = timing.read_junit_times(junit_path)
    assert junit.unresolved == 0, "premise: every testcase resolves to a node ID"
    busy = timing.compute_busy(load.workers, junit)
    assert busy is not None
    return busy, load, junit


def test_timestamp_busy_time_agrees_with_junit_within_a_millisecond(
    timing: ModuleType, tmp_path: Path
) -> None:
    busy, _, junit = _busy_for(timing, tmp_path, with_timing=True)

    assert sum(junit.node_seconds.values()) == 400.0
    assert busy["source"] == "timestamps"
    assert [w["busy_source"] for w in busy["workers"]] == ["timestamps"] * 4
    assert [w["busy_seconds"] for w in busy["workers"]] == [150.0, 120.0, 110.0, 20.0]
    for entry in busy["workers"]:
        assert abs(entry["busy_seconds"] - entry["junit_busy_seconds"]) <= 0.001
    assert (busy["mean_seconds"], busy["max_seconds"], busy["min_seconds"]) == (
        100.0,
        150.0,
        20.0,
    )
    assert busy["unattributed_junit_seconds"] == 0.0


def test_a_valid_timing_block_wins_over_junit_when_they_differ(
    timing: ModuleType, tmp_path: Path
) -> None:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=True)
    big = "tests/test_big.py"
    _write_worker(
        workers_dir, 0, _nodes(big, 15), _block({big: (149.0, 15)})
    )
    load = timing.load_worker_evidence(workers_dir)
    assert load.errors == () and load.warnings == ()

    busy = timing.compute_busy(load.workers, timing.read_junit_times(junit_path))

    first = busy["workers"][0]
    assert (first["busy_seconds"], first["junit_busy_seconds"]) == (149.0, 150.0)
    assert first["busy_source"] == "timestamps"


def test_without_a_timing_block_busy_time_is_the_junit_sum(
    timing: ModuleType, tmp_path: Path
) -> None:
    busy, _, junit = _busy_for(timing, tmp_path, with_timing=False)

    totals = [
        sum(
            junit.node_seconds[node]
            for file in files
            for node in _nodes(file, len(BUDGET_FILES[file]))
        )
        for _, files in sorted(BUDGET_ASSIGNMENT.items())
    ]
    assert totals == [150.0, 120.0, 110.0, 20.0], "premise: the JUnit sums"
    assert busy["source"] == "junit"
    assert [w["busy_source"] for w in busy["workers"]] == ["junit"] * 4
    assert [w["busy_seconds"] for w in busy["workers"]] == totals
    assert [w["junit_busy_seconds"] for w in busy["workers"]] == totals
    timeline = (
        "collection_seconds",
        "start_wait_seconds",
        "active_span_seconds",
        "in_span_gap_seconds",
        "tail_seconds",
        "first_test_start_wall",
        "last_test_end_wall",
    )
    assert all(w[field] is None for w in busy["workers"] for field in timeline)


def _with_timing_block(tmp_path: Path, block: Any) -> tuple[Path, Path]:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=True)
    _write_worker(workers_dir, 0, _nodes("tests/test_big.py", 15), block)
    return junit_path, workers_dir


def _rejected_blocks() -> dict[str, Any]:
    big = "tests/test_big.py"
    good = lambda: _block({big: (150.0, 15)})  # noqa: E731
    wrong_version = good()
    wrong_version["version"] = 2
    missing_event = good()
    del missing_event["events"]["session_finish"]
    non_finite = good()
    non_finite["events"]["session_start"]["monotonic"] = float("nan")
    negative = good()
    negative["files"][big]["duration_seconds"] = -1.0
    nan_duration = good()
    nan_duration["files"][big]["duration_seconds"] = float("nan")
    miscounted = good()
    miscounted["files"][big]["node_count"] = 14
    no_last_end = good()
    del no_last_end["files"][big]["last_end"]
    reversed_events = good()
    reversed_events["events"]["session_start"] = _stamp(500.0)
    reversed_file = good()
    reversed_file["files"][big]["first_start"] = _stamp(300.0)
    reversed_file["files"][big]["last_end"] = _stamp(200.0)
    before_the_first_test = good()
    before_the_first_test["files"][big]["first_start"] = _stamp(100.0)
    unexecuted = good()
    unexecuted["files"]["tests/test_ghost.py"] = dict(unexecuted["files"][big])
    unexecuted["files"]["tests/test_ghost.py"]["node_count"] = 0
    missing_entry = good()
    missing_entry["files"] = {}
    over_the_span = _block({big: (150.03, 15)})
    no_first_test = good()
    no_first_test["events"]["first_test_start"] = None
    return {
        "wrong-version": wrong_version,
        "missing-event": missing_event,
        "non-finite-stamp": non_finite,
        "negative-duration": negative,
        "nan-duration": nan_duration,
        "miscounted-nodes": miscounted,
        "missing-last-end": no_last_end,
        "reversed-events": reversed_events,
        "reversed-file-stamps": reversed_file,
        "file-before-the-first-test": before_the_first_test,
        "unexecuted-file": unexecuted,
        "executed-file-without-an-entry": missing_entry,
        "durations-exceed-the-span": over_the_span,
        "null-first-test-stamp": no_first_test,
        "not-an-object": [],
    }


@pytest.mark.parametrize("case", sorted(_rejected_blocks()))
def test_a_rejected_timing_block_falls_back_to_junit_with_a_warning(
    timing: ModuleType, tmp_path: Path, case: str
) -> None:
    control_junit, control_dir = _budget_scenario(tmp_path / "control", with_timing=True)
    control = timing.load_worker_evidence(control_dir)
    assert control.warnings == () and control.workers[0].timing is not None

    junit_path, workers_dir = _with_timing_block(
        tmp_path / "case", _rejected_blocks()[case]
    )
    load = timing.load_worker_evidence(workers_dir)
    busy = timing.compute_busy(load.workers, timing.read_junit_times(junit_path))

    assert load.errors == ()
    assert load.workers[0].timing is None
    assert len(load.warnings) == 1 and load.warnings[0].startswith("gw0:")
    assert "JUnit" in load.warnings[0]
    assert busy["workers"][0]["busy_source"] == "junit"
    assert busy["workers"][0]["busy_seconds"] == 150.0
    assert busy["source"] == "mixed"


def test_durations_may_overshoot_the_span_by_one_clock_tick_but_no_more(
    timing: ModuleType, tmp_path: Path
) -> None:
    """Windows ``time.monotonic()`` ticks every 15.625 ms, so a span is only known to
    one tick; the measured worst overshoot was 14.5 ms. Anything past the pinned
    epsilon cannot be clock granularity."""
    assert 0.015625 <= timing._MONOTONIC_EPSILON_SECONDS <= 0.05, "premise: one tick"
    big = "tests/test_big.py"
    results: dict[float, Any] = {}
    for seconds in (150.015, 150.03):
        junit_path, workers_dir = _budget_scenario(tmp_path / str(seconds), with_timing=True)
        _write_worker(workers_dir, 0, _nodes(big, 15), _block({big: (seconds, 15)}))
        load = timing.load_worker_evidence(workers_dir)
        results[seconds] = (load, timing.compute_busy(load.workers, timing.read_junit_times(junit_path)))

    accepted, accepted_busy = results[150.015]
    assert accepted.warnings == () and accepted.workers[0].timing is not None
    first = accepted_busy["workers"][0]
    assert first["busy_seconds"] == 150.015 and first["busy_source"] == "timestamps"
    assert first["in_span_gap_seconds"] == 0.0, "a gap below zero is clamped, not shown"
    rejected, rejected_busy = results[150.03]
    assert rejected.workers[0].timing is None and len(rejected.warnings) == 1
    assert rejected_busy["workers"][0]["busy_source"] == "junit"


def test_a_load_by_worker_id_reads_only_the_named_files(
    timing: ModuleType, tmp_path: Path
) -> None:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=True)
    (workers_dir / "gw9.json").write_text("{not json", encoding="utf-8")
    (workers_dir / "gwx.json").write_text("{}", encoding="utf-8")
    assert len(timing.load_worker_evidence(workers_dir).errors) == 2, "premise: junk is seen by a scan"

    named = timing.load_worker_evidence(workers_dir, ["gw0", "gw1", "gw2", "gw3"])
    budget = timing.build_duration_budget(junit_path, workers_dir, ["gw0", "gw1", "gw2", "gw3"])

    assert named.errors == () and [w.worker for w in named.workers] == ["gw0", "gw1", "gw2", "gw3"]
    assert budget["error"] is None and budget["critical_path"]["worker"] == "gw0"


def test_a_load_by_worker_id_reports_a_missing_file(
    timing: ModuleType, tmp_path: Path
) -> None:
    _, workers_dir = _budget_scenario(tmp_path, with_timing=True)
    (workers_dir / "gw3.json").unlink()

    load = timing.load_worker_evidence(workers_dir, ["gw0", "gw1", "gw2", "gw3"])

    assert load.errors == ("missing worker evidence gw3.json",)
    assert [w.worker for w in load.workers] == ["gw0", "gw1", "gw2"]


def test_workers_a_tenth_of_a_millisecond_apart_are_not_a_tie(
    timing: ModuleType, tmp_path: Path
) -> None:
    junit_path = _write_junit(
        tmp_path / "run.xml",
        _file_cases("tests/test_a.py", [100.0003]) + _file_cases("tests/test_b.py", [100.0004]),
    )
    workers_dir = tmp_path / "run.collection-workers"
    _write_worker(workers_dir, 0, _nodes("tests/test_a.py", 1))
    _write_worker(workers_dir, 1, _nodes("tests/test_b.py", 1))
    load = timing.load_worker_evidence(workers_dir)

    busy = timing.compute_busy(load.workers, timing.read_junit_times(junit_path))

    assert [w["busy_seconds"] for w in busy["workers"]] == [100.0, 100.0], "premise: they display equal"
    assert busy["critical_path"]["worker"] == "gw1"
    assert busy["max_seconds"] == 100.0 and busy["mean_seconds"] == 100.0


def test_workers_that_are_exactly_equal_still_tie_to_the_lowest_index(
    timing: ModuleType, tmp_path: Path
) -> None:
    junit_path = _write_junit(
        tmp_path / "run.xml",
        _file_cases("tests/test_a.py", [100.0003]) + _file_cases("tests/test_b.py", [100.0003]),
    )
    workers_dir = tmp_path / "run.collection-workers"
    _write_worker(workers_dir, 0, _nodes("tests/test_a.py", 1))
    _write_worker(workers_dir, 1, _nodes("tests/test_b.py", 1))
    load = timing.load_worker_evidence(workers_dir)

    busy = timing.compute_busy(load.workers, timing.read_junit_times(junit_path))

    assert busy["critical_path"]["worker"] == "gw0"


def test_a_tie_does_not_depend_on_the_order_the_times_are_summed_in(
    timing: ModuleType, tmp_path: Path
) -> None:
    assert 0.3 + 0.2 + 0.1 != 0.1 + 0.2 + 0.3, "premise: left-to-right addition disagrees by order"
    junit_path = _write_junit(
        tmp_path / "run.xml",
        _file_cases("tests/test_a.py", [0.3, 0.2, 0.1]) + _file_cases("tests/test_b.py", [0.1, 0.2, 0.3]),
    )
    workers_dir = tmp_path / "run.collection-workers"
    _write_worker(workers_dir, 0, _nodes("tests/test_a.py", 3))
    _write_worker(workers_dir, 1, _nodes("tests/test_b.py", 3))
    load = timing.load_worker_evidence(workers_dir)

    busy = timing.compute_busy(load.workers, timing.read_junit_times(junit_path))

    assert busy["critical_path"]["worker"] == "gw0", "the same times are the same busy time"


def test_files_a_tenth_of_a_millisecond_apart_are_not_a_tie(
    timing: ModuleType, tmp_path: Path
) -> None:
    junit_path = _write_junit(
        tmp_path / "run.xml",
        _file_cases("tests/test_a.py", [5.0003]) + _file_cases("tests/test_b.py", [5.0004]),
    )
    workers_dir = tmp_path / "run.collection-workers"
    _write_worker(workers_dir, 0, _nodes("tests/test_a.py", 1) + _nodes("tests/test_b.py", 1))
    load = timing.load_worker_evidence(workers_dir)

    busy = timing.compute_busy(load.workers, timing.read_junit_times(junit_path))

    worker = busy["workers"][0]
    assert worker["file_count"] == 2
    # Rounded they are both 5.0, and the smaller path would win a tie; raw, b is larger.
    assert (worker["dominant_file"], worker["dominant_file_seconds"]) == ("tests/test_b.py", 5.0)
    assert busy["critical_path"]["file"] == "tests/test_b.py"


def test_workers_with_and_without_timing_are_reported_as_mixed(
    timing: ModuleType, tmp_path: Path
) -> None:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=True)
    first = json.loads((workers_dir / "gw0.json").read_text(encoding="utf-8"))
    assert "timing" in first, "premise: gw0 starts with a timing block"
    del first["timing"]
    (workers_dir / "gw0.json").write_text(json.dumps(first), encoding="utf-8")

    load = timing.load_worker_evidence(workers_dir)
    busy = timing.compute_busy(load.workers, timing.read_junit_times(junit_path))

    assert [w["busy_source"] for w in busy["workers"]] == [
        "junit",
        "timestamps",
        "timestamps",
        "timestamps",
    ]
    assert busy["source"] == "mixed"


@pytest.mark.parametrize("with_timing", [False, True], ids=["junit", "timestamps"])
def test_the_critical_path_is_the_busiest_worker_and_its_largest_file(
    timing: ModuleType, tmp_path: Path, with_timing: bool
) -> None:
    busy, _, _ = _busy_for(timing, tmp_path, with_timing=with_timing)

    assert busy["critical_path"] == {
        "worker": "gw0",
        "busy_seconds": 150.0,
        "file": "tests/test_big.py",
        "file_seconds": 150.0,
    }
    runner_up = busy["workers"][2]
    assert runner_up["dominant_file"] == "tests/test_mid.py"
    assert runner_up["dominant_file_seconds"] == 60.0
    assert runner_up["file_count"] == 2


def test_a_busy_tie_goes_to_the_lowest_numeric_gw_index(
    timing: ModuleType, tmp_path: Path
) -> None:
    indexes = [10, 2, 9]
    assert min(f"gw{i}" for i in indexes) == "gw10", "premise: text order differs"
    files = {index: f"tests/test_w{index}.py" for index in indexes}
    junit_path = _write_junit(
        tmp_path / "run.xml",
        [case for file in files.values() for case in _file_cases(file, [10.0] * 3)],
    )
    workers_dir = tmp_path / "run.collection-workers"
    for index, file in files.items():
        _write_worker(workers_dir, index, _nodes(file, 3))
    load = timing.load_worker_evidence(workers_dir)

    busy = timing.compute_busy(load.workers, timing.read_junit_times(junit_path))

    assert [w["worker"] for w in busy["workers"]] == ["gw2", "gw9", "gw10"]
    assert {w["busy_seconds"] for w in busy["workers"]} == {30.0}
    assert busy["critical_path"]["worker"] == "gw2"


@pytest.mark.parametrize("with_timing", [False, True], ids=["junit", "timestamps"])
def test_a_dominant_file_tie_goes_to_the_smallest_path(
    timing: ModuleType, tmp_path: Path, with_timing: bool
) -> None:
    later, earlier = "tests/test_b.py", "tests/test_a.py"
    junit_path = _write_junit(
        tmp_path / "run.xml",
        _file_cases(later, [10.0, 10.0]) + _file_cases(earlier, [10.0, 10.0]),
    )
    nodes = _nodes(later, 2) + _nodes(earlier, 2)
    block = (
        _block({later: (20.0, 2), earlier: (20.0, 2)}) if with_timing else None
    )
    workers_dir = tmp_path / "run.collection-workers"
    _write_worker(workers_dir, 0, nodes, block)
    load = timing.load_worker_evidence(workers_dir)
    junit = timing.read_junit_times(junit_path)
    assert junit.file_seconds[earlier] == junit.file_seconds[later] == 20.0, "premise"

    busy = timing.compute_busy(load.workers, junit)

    assert busy["workers"][0]["file_count"] == 2
    assert busy["workers"][0]["dominant_file"] == earlier
    assert busy["critical_path"]["file"] == earlier
    assert busy["workers"][0]["dominant_file_seconds"] == 20.0


def test_timeline_fields_come_from_the_monotonic_stamps(
    timing: ModuleType, tmp_path: Path
) -> None:
    big = "tests/test_big.py"
    junit_path = _write_junit(tmp_path / "run.xml", _file_cases(big, [10.0] * 14))
    workers_dir = tmp_path / "run.collection-workers"
    _write_worker(workers_dir, 0, _nodes(big, 14), _block({big: (140.0, 14)}))
    _write_worker(
        workers_dir,
        1,
        [],
        _block({}, first_test_start=None, last_test_end=None),
    )
    load = timing.load_worker_evidence(workers_dir)
    assert load.errors == () and load.warnings == ()

    busy = timing.compute_busy(load.workers, timing.read_junit_times(junit_path))

    busy_worker, idle_worker = busy["workers"]
    assert busy_worker["collection_seconds"] == 70.0
    assert busy_worker["start_wait_seconds"] == 10.5
    assert busy_worker["active_span_seconds"] == 150.0
    assert busy_worker["in_span_gap_seconds"] == 10.0
    assert busy_worker["tail_seconds"] == 0.5
    assert busy_worker["first_test_start_wall"] == 1_800_000_181.5
    assert busy_worker["last_test_end_wall"] == 1_800_000_331.5
    assert idle_worker["collection_seconds"] == 70.0
    assert idle_worker["start_wait_seconds"] is None
    assert idle_worker["active_span_seconds"] is None
    assert idle_worker["in_span_gap_seconds"] is None
    assert idle_worker["tail_seconds"] is None
    assert idle_worker["dominant_file"] is None
    assert idle_worker["busy_seconds"] == 0.0


def test_junit_time_no_worker_executed_is_unattributed(
    timing: ModuleType, tmp_path: Path
) -> None:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=False)
    load = timing.load_worker_evidence(workers_dir)
    baseline = timing.compute_busy(load.workers, timing.read_junit_times(junit_path))
    assert baseline is not None and baseline["unattributed_junit_seconds"] == 0.0
    cases = [
        case for file, times in BUDGET_FILES.items() for case in _file_cases(file, times)
    ] + _file_cases("tests/test_orphan.py", [7.0])
    _write_junit(junit_path, cases)

    busy = timing.compute_busy(load.workers, timing.read_junit_times(junit_path))

    assert busy["unattributed_junit_seconds"] == 7.0


def test_busy_time_without_workers_is_none(timing: ModuleType, tmp_path: Path) -> None:
    junit_path = _write_junit(tmp_path / "run.xml", _file_cases("tests/test_a.py", [1.0]))

    assert timing.compute_busy([], timing.read_junit_times(junit_path)) is None


# ---------------------------------------------------------------------------
# The report-only duration budget
# ---------------------------------------------------------------------------

BUDGET_KEYS = {
    "version",
    "report_only",
    "thresholds",
    "busy_source",
    "worker_busy",
    "mean_busy_seconds",
    "critical_path",
    "slow_tests",
    "slow_files",
    "unresolved_junit_testcases",
    "error",
}


def _budget(timing: ModuleType, tmp_path: Path, *, with_timing: bool = True) -> dict[str, Any]:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=with_timing)
    return timing.build_duration_budget(junit_path, workers_dir)


def test_a_twelve_second_test_is_listed_and_a_ten_second_test_is_not(
    timing: ModuleType, tmp_path: Path
) -> None:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=True)
    seconds = timing.read_junit_times(junit_path).node_seconds
    assert seconds["tests/test_big.py::test_0"] == 12.0
    assert seconds["tests/test_big.py::test_1"] == 10.0
    assert sum(1 for value in seconds.values() if value == 10.0) == 38, "premise"

    budget = timing.build_duration_budget(junit_path, workers_dir)

    assert budget["slow_tests"] == {
        "count": 1,
        "truncated": False,
        "items": [{"id": "tests/test_big.py::test_0", "seconds": 12.0}],
    }


def test_a_test_just_over_the_limit_is_listed_though_it_displays_as_the_limit(
    timing: ModuleType, tmp_path: Path
) -> None:
    edge = "tests/test_edge.py"
    junit_path = _write_junit(
        tmp_path / "run.xml", _file_cases(edge, [10.0004, 10.0, 9.9999])
    )
    workers_dir = tmp_path / "run.collection-workers"
    _write_worker(workers_dir, 0, _nodes(edge, 3))
    seconds = timing.read_junit_times(junit_path).node_seconds
    assert seconds[f"{edge}::test_0"] == 10.0004, "premise: the writer kept every digit"

    budget = timing.build_duration_budget(junit_path, workers_dir)

    assert budget["slow_tests"] == {
        "count": 1,
        "truncated": False,
        "items": [{"id": f"{edge}::test_0", "seconds": 10.0}],
    }


def test_a_file_just_over_the_file_limit_is_flagged_and_one_exactly_on_it_is_not(
    timing: ModuleType, tmp_path: Path
) -> None:
    over, on = "tests/test_over.py", "tests/test_on.py"
    junit_path = _write_junit(
        tmp_path / "run.xml",
        _file_cases(over, [60.0002, 60.0002]) + _file_cases(on, [60.0, 60.0]),
    )
    workers_dir = tmp_path / "run.collection-workers"
    _write_worker(workers_dir, 0, _nodes(over, 2))
    _write_worker(workers_dir, 1, _nodes(on, 2))
    files = timing.read_junit_times(junit_path).file_seconds
    assert files[over] == 120.0004 and files[on] == 120.0, "premise: the sums"

    budget = timing.build_duration_budget(junit_path, workers_dir)

    flagged = {item["file"]: item for item in budget["slow_files"]["items"]}
    assert flagged[over]["over_file_seconds"] is True
    assert flagged[over]["seconds"] == 120.0, "displayed rounded, decided raw"
    assert flagged[on]["over_file_seconds"] is False


def test_a_file_just_over_the_share_is_flagged_and_one_exactly_on_it_is_not(
    timing: ModuleType, tmp_path: Path
) -> None:
    just_over = 50.0 + 2**-14  # exactly representable, so the mean below is exactly 100.0
    junit_path = _write_junit(
        tmp_path / "run.xml",
        _file_cases("tests/test_over.py", [just_over])
        + _file_cases("tests/test_pad.py", [100.0 - just_over])
        + _file_cases("tests/test_on.py", [50.0])
        + _file_cases("tests/test_pad2.py", [50.0]),
    )
    workers_dir = tmp_path / "run.collection-workers"
    _write_worker(
        workers_dir, 0, _nodes("tests/test_over.py", 1) + _nodes("tests/test_pad.py", 1)
    )
    _write_worker(
        workers_dir, 1, _nodes("tests/test_on.py", 1) + _nodes("tests/test_pad2.py", 1)
    )

    budget = timing.build_duration_budget(junit_path, workers_dir)

    assert budget["mean_busy_seconds"] == 100.0, "premise: the mean is exactly 100"
    flagged = {item["file"]: item for item in budget["slow_files"]["items"]}
    assert flagged["tests/test_over.py"]["over_mean_busy_share"] is True
    assert flagged["tests/test_over.py"]["seconds"] == 50.0
    assert "tests/test_on.py" not in flagged


def test_the_share_limit_uses_the_raw_mean_not_the_displayed_one(
    timing: ModuleType, tmp_path: Path
) -> None:
    """Workers at 99.9996 and 100.0 s: the raw mean is 99.9998 (displayed 100.0), so
    half of it is 49.9999 and a 49.99995 s file is over it; the displayed mean
    would have set the limit at 50.0 and missed it."""
    junit_path = _write_junit(
        tmp_path / "run.xml",
        _file_cases("tests/test_edge.py", [49.99995])
        + _file_cases("tests/test_pad.py", [99.9996 - 49.99995])
        + _file_cases("tests/test_other.py", [100.0]),
    )
    workers_dir = tmp_path / "run.collection-workers"
    _write_worker(
        workers_dir, 0, _nodes("tests/test_edge.py", 1) + _nodes("tests/test_pad.py", 1)
    )
    _write_worker(workers_dir, 1, _nodes("tests/test_other.py", 1))

    budget = timing.build_duration_budget(junit_path, workers_dir)

    assert budget["mean_busy_seconds"] == 100.0, "premise: it displays as 100"
    flagged = {item["file"]: item for item in budget["slow_files"]["items"]}
    assert flagged["tests/test_edge.py"]["over_mean_busy_share"] is True


def test_budget_lists_order_by_raw_seconds_before_the_id(
    timing: ModuleType, tmp_path: Path
) -> None:
    edge = "tests/test_edge.py"
    junit_path = _write_junit(
        tmp_path / "run.xml", _file_cases(edge, [10.0003, 10.0004, 10.0003])
    )
    workers_dir = tmp_path / "run.collection-workers"
    _write_worker(workers_dir, 0, _nodes(edge, 3))

    items = timing.build_duration_budget(junit_path, workers_dir)["slow_tests"]["items"]

    assert [item["seconds"] for item in items] == [10.0, 10.0, 10.0], "premise: equal when shown"
    assert [item["id"] for item in items] == [f"{edge}::test_1", f"{edge}::test_0", f"{edge}::test_2"]


def test_each_file_flag_names_its_own_reason(
    timing: ModuleType, tmp_path: Path
) -> None:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=True)
    files = timing.read_junit_times(junit_path).file_seconds
    assert files["tests/test_edge.py"] == 120.0, "premise: exactly on the file limit"
    assert files["tests/test_small.py"] == 50.0, "premise: exactly half the mean"

    budget = timing.build_duration_budget(junit_path, workers_dir)

    assert budget["mean_busy_seconds"] == 100.0
    assert budget["slow_files"] == {
        "count": 3,
        "truncated": False,
        "items": [
            {
                "file": "tests/test_big.py",
                "seconds": 150.0,
                "over_file_seconds": True,
                "over_mean_busy_share": True,
            },
            {
                "file": "tests/test_edge.py",
                "seconds": 120.0,
                "over_file_seconds": False,
                "over_mean_busy_share": True,
            },
            {
                "file": "tests/test_mid.py",
                "seconds": 60.0,
                "over_file_seconds": False,
                "over_mean_busy_share": True,
            },
        ],
    }


def test_the_budget_reports_thresholds_busy_and_the_critical_path(
    timing: ModuleType, tmp_path: Path
) -> None:
    budget = _budget(timing, tmp_path)

    assert set(budget) == BUDGET_KEYS
    assert budget["version"] == 1 and budget["report_only"] is True
    assert budget["thresholds"] == {
        "test_seconds": 10.0,
        "file_seconds": 120.0,
        "mean_busy_share": 0.5,
        "item_limit": 500,
    }
    assert budget["busy_source"] == "timestamps"
    assert budget["worker_busy"] == [
        {"worker": "gw0", "busy_seconds": 150.0, "busy_source": "timestamps"},
        {"worker": "gw1", "busy_seconds": 120.0, "busy_source": "timestamps"},
        {"worker": "gw2", "busy_seconds": 110.0, "busy_source": "timestamps"},
        {"worker": "gw3", "busy_seconds": 20.0, "busy_source": "timestamps"},
    ]
    assert budget["critical_path"] == {
        "worker": "gw0",
        "busy_seconds": 150.0,
        "file": "tests/test_big.py",
        "file_seconds": 150.0,
    }
    assert budget["unresolved_junit_testcases"] == 0
    assert budget["error"] is None


def test_the_thresholds_are_module_constants_read_when_the_budget_is_built(
    timing: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=True)
    assert timing.build_duration_budget(junit_path, workers_dir)["slow_tests"]["count"] == 1

    monkeypatch.setattr(timing, "_DURATION_BUDGET_TEST_SECONDS", 11.0)
    monkeypatch.setattr(timing, "_DURATION_BUDGET_FILE_SECONDS", 140.0)
    monkeypatch.setattr(timing, "_DURATION_BUDGET_MEAN_BUSY_SHARE", 1.5)
    lowered = timing.build_duration_budget(junit_path, workers_dir)

    assert lowered["thresholds"]["test_seconds"] == 11.0
    assert lowered["thresholds"]["mean_busy_share"] == 1.5
    assert lowered["slow_tests"]["count"] == 1
    assert [item["file"] for item in lowered["slow_files"]["items"]] == [
        "tests/test_big.py"
    ]
    flags = lowered["slow_files"]["items"][0]
    assert (flags["over_file_seconds"], flags["over_mean_busy_share"]) == (True, False)


def test_budget_lists_are_sorted_exactly_counted_and_flag_truncation(
    timing: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=True)
    monkeypatch.setattr(timing, "_DURATION_BUDGET_TEST_SECONDS", 9.0)

    full = timing.build_duration_budget(junit_path, workers_dir)["slow_tests"]
    assert full["count"] == 39 and full["truncated"] is False, "premise: ties exist"
    keys = [(-item["seconds"], item["id"]) for item in full["items"]]
    assert keys == sorted(keys)
    assert full["items"][0]["id"] == "tests/test_big.py::test_0"

    monkeypatch.setattr(timing, "_DURATION_BUDGET_ITEM_LIMIT", 5)
    bounded = timing.build_duration_budget(junit_path, workers_dir)

    assert bounded["slow_tests"]["count"] == 39
    assert bounded["slow_tests"]["truncated"] is True
    assert bounded["slow_tests"]["items"] == full["items"][:5]
    assert bounded["thresholds"]["item_limit"] == 5


def test_a_budget_without_worker_evidence_still_lists_the_junit_findings(
    timing: ModuleType, tmp_path: Path
) -> None:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=True)
    assert workers_dir.is_dir(), "premise: the evidence exists before it is removed"
    for path in workers_dir.iterdir():
        path.unlink()
    workers_dir.rmdir()

    budget = timing.build_duration_budget(junit_path, workers_dir)

    assert budget["error"].startswith("per-worker evidence is unavailable")
    assert budget["busy_source"] is None and budget["worker_busy"] == []
    assert budget["mean_busy_seconds"] is None and budget["critical_path"] is None
    assert budget["slow_tests"]["count"] == 1
    assert [item["file"] for item in budget["slow_files"]["items"]] == [
        "tests/test_big.py"
    ]
    assert budget["slow_files"]["items"][0]["over_mean_busy_share"] is None


def test_a_budget_with_an_invalid_worker_file_reports_it_and_keeps_the_findings(
    timing: ModuleType, tmp_path: Path
) -> None:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=True)
    assert timing.build_duration_budget(junit_path, workers_dir)["error"] is None
    (workers_dir / "gw1.json").write_text("{not json", encoding="utf-8")

    budget = timing.build_duration_budget(junit_path, workers_dir)

    assert budget["error"].startswith("per-worker evidence is invalid")
    assert "gw1.json" in budget["error"]
    assert budget["critical_path"] is None and budget["worker_busy"] == []
    assert budget["slow_tests"]["count"] == 1


def test_the_budget_is_strict_json_and_never_keys_an_object_by_path_or_node_id(
    timing: ModuleType, tmp_path: Path
) -> None:
    budget = _budget(timing, tmp_path)

    json.dumps(budget, allow_nan=False)
    keys: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                keys.append(key)
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(budget)
    assert "id" in keys and "file" in keys, "premise: the lists were walked"
    assert not [key for key in keys if "/" in key or "::" in key or ".py" in key]


def test_unresolved_junit_testcases_are_counted_not_listed(
    timing: ModuleType, tmp_path: Path
) -> None:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=True)
    text = junit_path.read_text(encoding="utf-8")
    junit_path.write_text(
        text.replace("</testsuite>", '<testcase classname="x" name="loose" time="99.000"/></testsuite>'),
        encoding="utf-8",
    )

    budget = timing.build_duration_budget(junit_path, workers_dir)

    assert budget["unresolved_junit_testcases"] == 1
    assert budget["slow_tests"]["count"] == 1, "a 99 s testcase with no node ID is not listed"


def test_an_unreadable_junit_report_raises_for_the_wrapper_guard_to_contain(
    timing: ModuleType, tmp_path: Path
) -> None:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=True)
    junit_path.write_text("<not-xml", encoding="utf-8")

    with pytest.raises(ET.ParseError):
        timing.build_duration_budget(junit_path, workers_dir)


# ---------------------------------------------------------------------------
# Reading the evidence
# ---------------------------------------------------------------------------


def test_junit_times_sum_duplicates_and_treat_bad_times_as_zero(
    timing: ModuleType, tmp_path: Path
) -> None:
    path = tmp_path / "run.xml"
    path.write_text(
        '<testsuites><testsuite>'
        '<testcase classname="tests.test_a" name="test_x" file="tests/test_a.py" time="1.500"/>'
        '<testcase classname="tests.test_a" name="test_x" file="tests/test_a.py" time="0.500"/>'
        '<testcase classname="tests.test_a" name="test_nan" file="tests/test_a.py" time="nan"/>'
        '<testcase classname="tests.test_a" name="test_inf" file="tests/test_a.py" time="inf"/>'
        '<testcase classname="tests.test_a" name="test_junk" file="tests/test_a.py" time="soon"/>'
        '<testcase classname="tests.test_a" name="test_none" file="tests/test_a.py"/>'
        '<testcase classname="x" name="unresolvable" time="9.000"/>'
        '</testsuite></testsuites>',
        encoding="utf-8",
    )

    junit = timing.read_junit_times(path)

    assert junit.testcase_count == 7 and junit.unresolved == 1
    assert junit.nodes.count("tests/test_a.py::test_x") == 2, "premise: a duplicate"
    assert junit.node_seconds["tests/test_a.py::test_x"] == 2.0
    assert [junit.node_seconds[f"tests/test_a.py::test_{n}"] for n in ("nan", "inf", "junk", "none")] == [0.0] * 4
    assert junit.file_seconds == {"tests/test_a.py": 2.0}


def test_the_default_workers_dir_sits_beside_the_collection_artifact(
    timing: ModuleType, tmp_path: Path
) -> None:
    stemmed = tmp_path / "20260101-gate-abc.collection.json"
    bare = tmp_path / "collection.json"

    assert timing.default_workers_dir(stemmed) == tmp_path / "20260101-gate-abc.collection-workers"
    assert timing.default_workers_dir(bare) == tmp_path / "collection.collection-workers"


def test_a_missing_or_empty_workers_dir_is_a_warning_not_an_error(
    timing: ModuleType, tmp_path: Path
) -> None:
    missing = timing.load_worker_evidence(tmp_path / "absent")
    (tmp_path / "empty").mkdir()
    empty = timing.load_worker_evidence(tmp_path / "empty")

    for load in (missing, empty):
        assert load.workers == () and load.errors == ()
        assert len(load.warnings) == 1
    assert "no per-worker evidence directory" in missing.warnings[0]
    assert "no gw*.json files" in empty.warnings[0]


@pytest.mark.parametrize(
    ("name", "content", "needle"),
    [
        ("gw1.json", "{not json", "unreadable worker evidence gw1.json"),
        ("gw1.json", "[" * 100_000 + "]" * 100_000, "unreadable worker evidence gw1.json"),
        ("gw1.json", "[]", "not a JSON object"),
        ("gw1.json", json.dumps({"schema_version": 2, "worker_id": "gw1", "executed_nodeids": []}), "schema_version"),
        ("gw1.json", json.dumps({"schema_version": 1, "worker_id": "gw9", "executed_nodeids": []}), "worker_id"),
        ("gw1.json", json.dumps({"schema_version": 1, "worker_id": "gw1", "executed_nodeids": "x"}), "executed_nodeids"),
        ("gw1.json", json.dumps({"schema_version": 1, "worker_id": "gw1", "executed_nodeids": [1]}), "executed_nodeids"),
        ("gwx.json", "{}", "unexpected worker evidence file name"),
    ],
    ids=["bad-json", "too-deeply-nested", "not-object", "schema", "worker-id", "nodes-not-list", "node-not-str", "file-name"],
)
def test_an_unreadable_or_invalid_worker_file_is_an_error(
    timing: ModuleType, tmp_path: Path, name: str, content: str, needle: str
) -> None:
    _write_worker(tmp_path, 0, ["tests/test_a.py::test_one"])
    assert timing.load_worker_evidence(tmp_path).errors == (), "premise: a valid control"
    (tmp_path / name).write_text(content, encoding="utf-8")

    load = timing.load_worker_evidence(tmp_path)

    assert len(load.errors) == 1 and needle in load.errors[0]
    assert [worker.worker for worker in load.workers] == ["gw0"]


# ---------------------------------------------------------------------------
# Evidence has to stand for the whole gate before a critical path is drawn from it
# ---------------------------------------------------------------------------


def _complete_evidence(timing: ModuleType) -> tuple[list[Any], dict[str, int], list[str]]:
    a, b = "tests/test_a.py", "tests/test_b.py"
    workers = [
        timing.WorkerEvidence("gw0", 0, 0, tuple(_nodes(a, 2)), None),
        timing.WorkerEvidence("gw1", 1, 0, tuple(_nodes(b, 1)), None),
    ]
    return workers, {"gw0": 2, "gw1": 1}, _nodes(a, 2) + _nodes(b, 1)


def _replace_worker(workers: list[Any], index: int, **changes: Any) -> list[Any]:
    import dataclasses

    patched = list(workers)
    patched[index] = dataclasses.replace(patched[index], **changes)
    return patched


def test_complete_evidence_has_no_problems(timing: ModuleType) -> None:
    workers, counts, collected = _complete_evidence(timing)

    assert timing.evidence_problems(workers, counts, collected) == []


@pytest.mark.parametrize(
    "case",
    [
        "missing-worker",
        "unexpected-worker",
        "non-zero-exit",
        "no-exit-status",
        "duplicate-within-a-worker",
        "duplicate-across-workers",
        "count-differs",
        "node-never-executed",
        "node-not-collected",
    ],
)
def test_incomplete_or_inconsistent_evidence_is_reported(
    timing: ModuleType, case: str
) -> None:
    workers, counts, collected = _complete_evidence(timing)
    assert timing.evidence_problems(workers, counts, collected) == [], "premise: a control"
    needle = {
        "missing-worker": "missing ['gw1']",
        "unexpected-worker": "unexpected ['gw1']",
        "non-zero-exit": "exit status 1",
        "no-exit-status": "exit status None",
        "duplicate-within-a-worker": "more than once",
        "duplicate-across-workers": "more than one worker",
        "count-differs": "records 2",
        "node-never-executed": "1 missing",
        "node-not-collected": "1 unexpected",
    }[case]
    if case == "missing-worker":
        workers = workers[:1]
    elif case == "unexpected-worker":
        counts = {"gw0": 2}
    elif case == "non-zero-exit":
        workers = _replace_worker(workers, 1, exitstatus=1)
    elif case == "no-exit-status":
        workers = _replace_worker(workers, 1, exitstatus=None)
    elif case == "duplicate-within-a-worker":
        nodes = workers[0].executed_nodeids
        workers = _replace_worker(workers, 0, executed_nodeids=nodes + (nodes[0],))
        counts = {"gw0": 3, "gw1": 1}
    elif case == "duplicate-across-workers":
        workers = _replace_worker(
            workers, 1, executed_nodeids=workers[1].executed_nodeids + (workers[0].executed_nodeids[0],)
        )
        counts = {"gw0": 2, "gw1": 2}
    elif case == "count-differs":
        counts = {"gw0": 2, "gw1": 2}
    elif case == "node-never-executed":
        collected = collected + ["tests/test_c.py::test_0"]
    else:
        workers = _replace_worker(
            workers, 1, executed_nodeids=workers[1].executed_nodeids + ("tests/test_z.py::test_0",)
        )
        counts = {"gw0": 2, "gw1": 2}

    problems = timing.evidence_problems(workers, counts, collected)

    assert any(needle in problem for problem in problems), problems


def test_a_worker_file_records_its_exit_status(
    timing: ModuleType, tmp_path: Path
) -> None:
    _write_worker(tmp_path, 0, ["tests/test_a.py::test_one"])
    _write_worker(tmp_path, 1, ["tests/test_b.py::test_one"], exitstatus=1)
    _write_worker(tmp_path, 2, ["tests/test_c.py::test_one"], exitstatus="0")

    load = timing.load_worker_evidence(tmp_path)

    assert [(w.worker, w.exitstatus) for w in load.workers] == [("gw0", 0), ("gw1", 1), ("gw2", None)]


# ---------------------------------------------------------------------------
# What the helper is allowed to be
# ---------------------------------------------------------------------------


def test_the_helper_is_standard_library_only_and_imports_neither_consumer() -> None:
    tree = ast.parse(HELPER.read_text(encoding="utf-8"))

    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert {"json", "xml", "pathlib"} <= imported, "premise: the imports were found"
    assert imported <= set(sys.stdlib_module_names)
    assert not imported & {"run_test_gate", "select_tests", "scripts"}


def test_the_helper_has_typed_public_functions_and_never_writes() -> None:
    tree = ast.parse(HELPER.read_text(encoding="utf-8"))
    public = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    ]
    assert {node.name for node in public} >= {
        "junit_node_id",
        "read_junit_times",
        "load_worker_evidence",
        "evidence_problems",
        "default_workers_dir",
        "compute_busy",
        "build_duration_budget",
    }
    for node in public:
        assert node.returns is not None, node.name
        assert all(arg.annotation is not None for arg in node.args.args), node.name

    writers = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "rename", "touch"}
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not called & writers
    opened_for_write = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "open"
    ]
    assert opened_for_write == []


def test_reading_leaves_the_evidence_directory_byte_for_byte_unchanged(
    timing: ModuleType, tmp_path: Path
) -> None:
    junit_path, workers_dir = _budget_scenario(tmp_path, with_timing=True)

    def snapshot() -> list[tuple[str, int, int]]:
        return sorted(
            (str(path.relative_to(tmp_path)), path.stat().st_size, path.stat().st_mtime_ns)
            for path in tmp_path.rglob("*")
            if path.is_file()
        )

    before = snapshot()
    assert len(before) == 5, "premise: the JUnit report and four worker files"
    timing.build_duration_budget(junit_path, workers_dir)
    timing.load_worker_evidence(workers_dir)

    assert snapshot() == before
