"""BF-1006 (#1870): the gate's worker-exit log, its lost-worker count and the TEMP volume in the receipt.

The plugin half is driven with fake xdist nodes (A1: including attributes that raise and a record that cannot be
rendered) and then by a real ``pytest -n 2`` run whose worker is killed, so one test crosses the seam from xdist's
controller hooks to the wrapper's count. The wrapper half calls the wrapper's
helpers, as ``tests/test_run_test_gate.py`` does.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "run_test_gate.py"
PLUGIN = REPO_ROOT / "scripts" / "_gate_pytest_plugin.py"
EXIT_LOG_ENV = "PROBOS_GATE_WORKER_EXIT_LOG"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    return _load("bf1006_run_test_gate", SCRIPT)


@pytest.fixture
def plugin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = _load("bf1006_gate_pytest_plugin", PLUGIN)
    monkeypatch.setitem(sys.modules, "bf1006_gate_pytest_plugin", module)
    return module


def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_log(path: Path, *records: dict[str, Any]) -> Path:
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


def _down(worker: str, error: str | None = None) -> dict[str, Any]:
    return {"event": "down", "worker": worker, "error": error, "exitstatus": 0 if error is None else None}


# --- The wrapper -------------------------------------------------------------------------------


def test_volume_of_names_the_drive_or_the_mount_point(gate: ModuleType, tmp_path: Path) -> None:
    if os.name == "nt":
        assert gate._volume_of(r"g:\gate-tmp-1\sub") == "G:"
        assert gate._volume_of(r"\\server\share\dir") == r"\\SERVER\SHARE"
    else:
        assert gate._volume_of("/") == "/"
        assert os.path.ismount(gate._volume_of(str(tmp_path)))
    assert str(tmp_path) not in gate._volume_of(str(tmp_path)), "the directory itself is never recorded"


def test_the_count_is_the_exits_with_an_error(gate: ModuleType, tmp_path: Path) -> None:
    clean = _write_log(
        tmp_path / "clean.jsonl",
        {"event": "ready", "worker": "gw0"},
        {"event": "ready", "worker": "gw1"},
        _down("gw0"),
        _down("gw1"),
    )
    assert gate._count_lost_workers(clean, expected_workers=2) == 0
    lost = _write_log(
        tmp_path / "lost.jsonl",
        {"event": "ready", "worker": "gw0"},
        {"event": "ready", "worker": "gw1"},
        _down("gw1", "Not properly terminated"),
        {"event": "crash", "worker": "gw1", "nodeid": "t/test_x.py::test_x"},
        {"event": "ready", "worker": "gw2"},
        _down("gw2"),
        _down("gw0"),
    )
    assert gate._count_lost_workers(lost, expected_workers=2) == 1


@pytest.mark.parametrize(
    ("lines", "match"),
    [
        (None, "no readable worker exit log"),
        ("not json\n", "is not JSON"),
        ("[1, 2]\n", "is not a worker record"),
        (json.dumps({"worker": "gw0"}) + "\n", "is not a worker record"),
        (json.dumps(_down("gw0")) + "\n", "no exit for: gw1"),
        # A2: each malformed gw0 record comes with a clean gw1 exit, so the log is complete and only the error
        # field can refuse it (without gw1 the completeness refusal answered first, a confound).
        (
            json.dumps({"event": "down", "worker": "gw0", "exitstatus": 0}) + "\n" + json.dumps(_down("gw1")) + "\n",
            "is a down record without a null or text error",
        ),
        (
            json.dumps({"event": "down", "worker": "gw0", "error": 1, "exitstatus": None})
            + "\n"
            + json.dumps(_down("gw1"))
            + "\n",
            "is a down record without a null or text error",
        ),
    ],
    ids=[
        "missing",
        "not-json",
        "not-an-object",
        "no-event",
        "an-expected-worker-never-exited",
        "down-without-error",
        "down-with-a-non-text-error",
    ],
)
def test_a_missing_malformed_or_incomplete_log_refuses_the_run(
    gate: ModuleType, tmp_path: Path, lines: str | None, match: str
) -> None:
    path = tmp_path / "workers.jsonl"
    if lines is not None:
        path.write_text(lines, encoding="utf-8")
    with pytest.raises(RuntimeError, match=match):
        gate._count_lost_workers(path, expected_workers=2)


def test_an_empty_error_text_still_counts_the_worker_lost(gate: ModuleType, tmp_path: Path) -> None:
    """Only a null error is a clean exit: an error rendered as an empty text is still an error."""
    log = _write_log(tmp_path / "empty.jsonl", _down("gw0"), _down("gw1", ""))
    assert gate._count_lost_workers(log, expected_workers=2) == 1


def _one_worker_manifest(gate: ModuleType, directory: Path, nodeids: list[str]) -> None:
    directory.mkdir()
    collected = sorted(nodeids)
    digest = gate._node_digest(collected)
    payload = {
        "schema_version": 1,
        "worker_id": "gw0",
        "exitstatus": 0,
        "collection_count": len(collected),
        "collection_sha256": digest,
        "final_count": len(collected),
        "final_sha256": digest,
        "removed_nodeids": [],
        "added_nodeids": [],
        "executed_nodeids": collected,
        "collected_nodeids": collected,
        "collected_files": sorted({nodeid.split("::", 1)[0] for nodeid in collected}),
    }
    (directory / "gw0.json").write_text(json.dumps(payload), encoding="utf-8")


def test_a_worker_lost_after_it_wrote_its_manifest_fails_the_validation(gate: ModuleType, tmp_path: Path) -> None:
    """The manifests alone pass: the worker wrote gw0.json and then died, so no replacement manifest and no crash item."""
    _one_worker_manifest(gate, tmp_path / "workers", ["tests/test_x.py::test_x"])
    arguments: dict[str, Any] = {
        "expected_workers": 1,
        "required_test_files": set(),
        "junit_totals": gate.JUnitTotals(tests=1, failures=0, errors=0, skipped=0, time_seconds=0.1),
    }
    clean = _write_log(tmp_path / "clean.jsonl", _down("gw0"))
    totals = gate._validate_collection_manifests(
        tmp_path / "workers", tmp_path / "clean.collection.json", worker_exit_log=clean, **arguments
    )
    assert (totals.workers, totals.workers_lost) == (1, 0), "premise: the same manifests pass with a clean log"
    lost = _write_log(tmp_path / "lost.jsonl", _down("gw0", "Not properly terminated"))
    with pytest.raises(RuntimeError, match=r"lost 1 worker\(s\)"):
        gate._validate_collection_manifests(
            tmp_path / "workers", tmp_path / "lost.collection.json", worker_exit_log=lost, **arguments
        )


def test_the_pytest_child_gets_the_exit_log_and_this_process_temp(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EXIT_LOG_ENV, "hostile")
    assert EXIT_LOG_ENV not in gate._subprocess_env(tmp_path), "an inherited value is cleared"
    env = gate._pytest_subprocess_env(tmp_path, tmp_path / "workers", worker_exit_log=tmp_path / "run.workers.jsonl")
    assert env[EXIT_LOG_ENV] == str((tmp_path / "run.workers.jsonl").resolve())
    for name in ("TMPDIR", "TEMP", "TMP"):  # the premise of recording the wrapper's own temp directory's volume
        assert env.get(name) == os.environ.get(name), name


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=repo, check=True, capture_output=True)


def _committed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text("/logs/\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "-c", "user.name=ProbOS Tests", "-c", "user.email=tests@probos.invalid", "commit", "-q", "-m", "fixture")
    return repo


@pytest.mark.parametrize("temp_volume", ["G:", None, ""], ids=["recorded", "none", "empty"])
def test_a_success_receipt_carries_the_temp_volume_and_is_refused_without_one(
    gate: ModuleType, tmp_path: Path, temp_volume: str | None
) -> None:
    repo = _committed_repo(tmp_path)
    gates = repo / "logs" / "gates"
    gates.mkdir(parents=True)
    manifest, junit, collection = gates / "r.json", gates / "r.xml", gates / "r.collection.json"
    for path in (manifest, junit, collection):
        path.write_text("{}\n", encoding="utf-8")
    snapshot = gate._snapshot_tree(repo)
    result = gate.GateResult(
        label="r", started_at="2026-11-28T00:00:00Z", finished_at="2026-11-28T00:00:01Z",
        elapsed_seconds=1.0, wrapper_exit_code=0, preflight_exit_code=0, pytest_exit_code=0,
        preflight_only=False, interrupted=False, error="", tree_changed=False,
        snapshot_before=snapshot, snapshot_after=snapshot, command=["pytest"], phases=[],
        sanitized_pytest_environment=[], summary="", log_path="", junit_path=str(junit),
        junit_totals=gate.JUnitTotals(tests=1, failures=0, errors=0, skipped=0, time_seconds=0.1),
        collection_path=str(collection),
        collection_totals=gate.CollectionTotals(nodes=1, workers=1, sha256="0" * 64, workers_lost=0),
        temp_volume=temp_volume,
    )
    receipt = gates / "r.receipt.json"
    arguments = {"repo_root": repo, "result": result, "source_snapshot": snapshot,
                 "manifest_path": manifest, "junit_path": junit, "collection_path": collection}
    if not temp_volume:
        with pytest.raises(RuntimeError, match="TEMP volume"):
            gate._write_success_receipt(receipt, **arguments)
        assert not receipt.exists()
        return
    gate._write_success_receipt(receipt, **arguments)
    written = json.loads(receipt.read_text(encoding="utf-8"))
    assert written["run"] == {"temp_volume": "G:"}
    assert written["collection"]["totals"]["workers_lost"] == 0


# --- The plugin (the controller's hooks) ---------------------------------------------------------


def _node(name: str, **attributes: Any) -> SimpleNamespace:
    return SimpleNamespace(gateway=SimpleNamespace(id=name), **attributes)


def test_the_controller_hooks_write_one_record_per_event(
    plugin: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "workers.jsonl"
    monkeypatch.setenv(EXIT_LOG_ENV, str(log))
    clean, dead = _node("gw0", workeroutput={"exitstatus": 0}), _node("gw1")
    plugin.pytest_testnodeready(clean)
    plugin.pytest_testnodedown(clean, None)
    plugin.pytest_testnodedown(dead, "Not properly terminated")
    assert plugin.pytest_handlecrashitem(
        crashitem="t/test_x.py::test_x", report=SimpleNamespace(node=dead), sched=None
    ) is None, "firstresult: returning None leaves the crash to xdist"

    records = _records(log)
    assert all(isinstance(record.pop("wall"), float) for record in records)
    assert records == [
        {"event": "ready", "worker": "gw0"},
        {"event": "down", "worker": "gw0", "error": None, "exitstatus": 0},
        {"event": "down", "worker": "gw1", "error": "Not properly terminated", "exitstatus": None},
        {"event": "crash", "worker": "gw1", "nodeid": "t/test_x.py::test_x"},
    ]


def test_the_controller_hooks_contain_an_ordinary_fault_and_write_nothing_without_the_variable(
    plugin: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Unprintable(Exception):
        def __str__(self) -> str:
            raise ValueError("no text")

    monkeypatch.delenv(EXIT_LOG_ENV, raising=False)
    plugin.pytest_testnodedown(_node("gw0"), None)
    assert list(tmp_path.iterdir()) == []

    monkeypatch.setenv(EXIT_LOG_ENV, str(tmp_path))  # a directory: the open fails, and the run goes on
    plugin.pytest_testnodedown(_node("gw0"), None)

    log = tmp_path / "workers.jsonl"
    monkeypatch.setenv(EXIT_LOG_ENV, str(log))
    plugin.pytest_testnodedown(object(), Unprintable())
    plugin.pytest_testnodedown(_node("gw3", workeroutput={"exitstatus": True}), "")
    first, second = _records(log)
    assert (first["worker"], first["error"], first["exitstatus"]) == ("unknown", "<unprintable>", None)
    assert (second["worker"], second["error"], second["exitstatus"]) == ("gw3", "str", None)
    assert math.isfinite(first["wall"])


class _Raises:
    """A data descriptor whose read raises ValueError, as a broken xdist attribute might (``getattr``'s default
    absorbs only AttributeError)."""

    def __get__(self, instance: object, owner: type | None = None) -> object:
        raise ValueError("this attribute cannot be read")


class _UnreadableOutput:
    gateway = SimpleNamespace(id="gw0")
    workeroutput = _Raises()


class _UnreadableGateway:
    gateway = _Raises()
    workeroutput = {"exitstatus": 0}


class _UnreadableNode:
    node = _Raises()


class _UnprintableItem:
    def __str__(self) -> str:
        raise ValueError("no text")


def _not_serializable(plugin: ModuleType, monkeypatch: pytest.MonkeyPatch) -> object:
    # The plugin fixture loads a fresh copy of the module per test, so only that copy's clock is replaced.
    monkeypatch.setattr(plugin, "time", SimpleNamespace(time=lambda: math.nan))
    return plugin.pytest_testnodeready(_node("gw0"))


_FAULTS: dict[str, tuple[Callable[[ModuleType, pytest.MonkeyPatch], object], list[dict[str, Any]]]] = {
    "workeroutput-raises": (lambda plugin, _: plugin.pytest_testnodedown(_UnreadableOutput(), None), []),
    "report-node-raises": (
        lambda plugin, _: plugin.pytest_handlecrashitem(
            crashitem="t/test_x.py::test_x", report=_UnreadableNode(), sched=None
        ),
        [],
    ),
    "crashitem-unprintable": (
        lambda plugin, _: plugin.pytest_handlecrashitem(
            crashitem=_UnprintableItem(), report=SimpleNamespace(node=_node("gw1")), sched=None
        ),
        [],
    ),
    "not-serializable": (_not_serializable, []),
    "gateway-raises": (
        lambda plugin, _: plugin.pytest_testnodedown(_UnreadableGateway(), None),
        [{"event": "down", "worker": "unknown", "error": None, "exitstatus": 0}],
    ),
}


@pytest.mark.parametrize("fault", list(_FAULTS))
def test_a_fault_while_building_or_writing_a_record_drops_only_that_record(
    plugin: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    """xdist calls ``pytest_testnodedown`` before its own crash guard (``dsession.py``:240), so a hook that raised
    would change the run. A helper with its own fallback (``_worker_name``) still records; any other fault drops that
    one record, and the wrapper then refuses a run that is missing a ``down`` (``_count_lost_workers``)."""
    log = tmp_path / "workers.jsonl"
    monkeypatch.setenv(EXIT_LOG_ENV, str(log))
    call, expected = _FAULTS[fault]
    assert call(plugin, monkeypatch) is None, "the hook returned normally"
    records = _records(log) if log.exists() else []
    assert all(isinstance(record.pop("wall"), float) for record in records)
    assert records == expected


# --- The chain: a real xdist run, its controller's log, the wrapper's count ------------------------

_ALPHA = "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n"
# xdist requeues a crashed worker's unit, so the crashing test runs again on the replacement: it dies only the first
# time (a marker file beside it), or every replacement would die until xdist's restart limit.
_DIES = (
    "import os\nfrom pathlib import Path\n\n\ndef test_dies():\n"
    "    marker = Path(__file__).with_name('died-once')\n"
    "    if not marker.exists():\n"
    "        marker.write_text('1')\n"
    "        os._exit(1)\n"
)


@pytest.mark.parametrize(("dies", "lost"), [(False, 0), (True, 1)], ids=["clean", "a-worker-dies"])
def test_a_real_run_logs_each_exit_and_the_wrapper_counts_the_lost_worker(
    gate: ModuleType, tmp_path: Path, dies: bool, lost: int
) -> None:
    suite = tmp_path / "t"
    suite.mkdir()
    (suite / "test_alpha.py").write_text(_ALPHA, encoding="utf-8")
    (suite / "test_other.py").write_text(_DIES if dies else _ALPHA.replace("test_", "test_b_"), encoding="utf-8")
    log = tmp_path / "run.workers.jsonl"
    env = {name: value for name, value in os.environ.items() if not name.startswith(("PYTEST_", "COV_CORE", "COVERAGE"))}
    env.update({"PYTHONPATH": str(REPO_ROOT), "PYTHONDONTWRITEBYTECODE": "1", EXIT_LOG_ENV: str(log)})
    env.pop("PROBOS_GATE_COLLECTION_DIR", None)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "t", "-q", "-p", "scripts._gate_pytest_plugin", "-n", "2",
         "--dist=loadfile", "-p", "no:randomly", "-p", "no:cacheprovider", "-o", "addopts="],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300,
    )
    assert completed.returncode == (1 if dies else 0), completed.stdout + completed.stderr

    records = _records(log)
    errors = [record for record in records if record["event"] == "down" and record["error"] is not None]
    crashes = [(record["worker"], record["nodeid"]) for record in records if record["event"] == "crash"]
    assert len(errors) == lost
    assert all(isinstance(record["error"], str) and record["error"] for record in errors)
    assert crashes == [(record["worker"], "t/test_other.py::test_dies") for record in errors]
    assert gate._count_lost_workers(log, expected_workers=2) == lost
