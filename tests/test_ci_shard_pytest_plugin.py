"""AD-1270f P2.7: the CI shard pytest plugin, run for real over a generated tree.

Every integration test starts ``sys.executable -m pytest`` over a small tree under
``tmp_path`` with its own ``pytest.ini`` (empty ``addopts``). CI shard evidence is not
release authority; these tests pin the CI proof, not the canonical gate.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_SHARDS = REPO_ROOT / "scripts" / "ci_shards.py"
PLUGIN = REPO_ROOT / "scripts" / "_ci_shard_pytest_plugin.py"
PLUGIN_ARGS = ("-p", "scripts._ci_shard_pytest_plugin")

ALPHA = [
    "suite/test_alpha.py::TestAlpha::test_one",
    "suite/test_alpha.py::TestAlpha::test_param[1]",
    "suite/test_alpha.py::TestAlpha::test_param[2]",
    "suite/test_alpha.py::TestAlpha::test_param[3]",
    "suite/test_alpha.py::test_alpha_plain",
]
BETA = ["suite/test_beta.py::test_beta_one", "suite/test_beta.py::test_beta_two"]
GAMMA = [
    "suite/test_gamma.py::test_gamma_skipped",
    "suite/test_gamma.py::test_gamma_xfail",
    "suite/test_gamma.py::test_gamma_label[caf\\xe9]",
    "suite/test_gamma.py::test_gamma_label[plain]",
]
DELTA = ["suite/test_delta.py::test_delta_a", "suite/test_delta.py::test_delta_b"]
ALL_NODES = sorted(ALPHA + BETA + GAMMA + DELTA)

# alpha 9 s, beta 8 s, gamma 5 s are recorded; delta is not, so it weighs 2 nodes x the
# known mean of 22000 ms / 11 nodes = 4000 ms. Longest first over two shards:
# alpha -> 1, beta -> 2, gamma -> 2, delta -> 1.
EXPECTED_FILE_SHARDS = {
    "suite/test_alpha.py": 1,
    "suite/test_beta.py": 2,
    "suite/test_gamma.py": 2,
    "suite/test_delta.py": 1,
}

SUITE = {
    "suite/test_alpha.py": (
        "import pytest\n\n\n"
        "class TestAlpha:\n"
        "    def test_one(self):\n        pass\n\n"
        "    @pytest.mark.parametrize('value', [1, 2, 3])\n"
        "    def test_param(self, value):\n        assert value > 0\n\n\n"
        "def test_alpha_plain():\n    pass\n"
    ),
    "suite/test_beta.py": "def test_beta_one():\n    pass\n\n\ndef test_beta_two():\n    pass\n",
    "suite/test_gamma.py": (
        "import pytest\n\n\n"
        "@pytest.mark.skip(reason='skipped during setup')\n"
        "def test_gamma_skipped():\n    pass\n\n\n"
        "@pytest.mark.xfail(strict=True, reason='expected to fail')\n"
        "def test_gamma_xfail():\n    assert False\n\n\n"
        "@pytest.mark.parametrize('label', ['caf\\u00e9', 'plain'])\n"
        "def test_gamma_label(label):\n    pass\n"
    ),
    "suite/test_delta.py": "def test_delta_a():\n    pass\n\n\ndef test_delta_b():\n    pass\n",
}
DURATIONS = {
    "schema_version": 1,
    "files": {"suite/test_alpha.py": 9.0, "suite/test_beta.py": 8.0, "suite/test_gamma.py": 5.0},
}
# The root conftest P1.4 installs, repeated here so the shard filter feeds the real scheduler.
SCHEDULER_CONFTEST = (
    "import pytest\n\n\n"
    "@pytest.hookimpl(optionalhook=True)\n"
    "def pytest_xdist_make_scheduler(config, log):\n"
    "    from tests.fixtures.duration_scheduler import make_duration_scheduler\n\n"
    "    return make_duration_scheduler(config, log)\n"
)


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cs() -> ModuleType:
    return _load("ci_shards_for_plugin_tests", CI_SHARDS)


def make_tree(root: Path, files: dict[str, str] | None = None, durations: Any = DURATIONS) -> Path:
    root.mkdir(parents=True)
    (root / "pytest.ini").write_text("[pytest]\naddopts =\n", encoding="utf-8")
    (root / "conftest.py").write_text(SCHEDULER_CONFTEST, encoding="utf-8")
    (root / "durations.json").write_text(json.dumps(durations), encoding="utf-8")
    for name, source in (files or SUITE).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(source, encoding="utf-8")
    return root


def run_pytest(
    tree: Path, *args: str, cwd: Path | None = None, timeout: float = 180
) -> subprocess.CompletedProcess[str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in {"PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_CURRENT_TEST", "PROBOS_GATE_COLLECTION_DIR"}
        and not name.startswith("PYTEST_XDIST")
    }
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO_ROOT), os.environ.get("PYTHONPATH")]))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:randomly", *args],
        cwd=cwd or tree,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )


def shard_options(index: int, count: int, evidence: Path, durations: str = "durations.json") -> list[str]:
    return [
        *PLUGIN_ARGS,
        f"--probos-shard-index={index}",
        f"--probos-shard-count={count}",
        f"--probos-shard-evidence-dir={evidence}",
        f"--probos-shard-durations={durations}",
    ]


def read_evidence(evidence: Path) -> dict[str, dict[str, Any]]:
    return {
        f"{path.parent.name}/{path.stem}": json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(evidence.glob("shard-*/*.json"))
    }


def verify(cs: ModuleType, evidence: Path, count: int, durations: Path) -> int:
    return cs.main(
        ["verify", "--evidence-root", str(evidence), "--shard-count", str(count), "--durations", str(durations)]
    )


def repo_strays() -> set[str]:
    """Evidence- and stack-shaped names directly under the repository's root, scripts/ and tests/."""
    patterns = ("shard-*", "*evidence*", ".gw*.tmp", ".main.*.tmp", "faulthandler-*", "*stacks*")
    return {
        str(path.relative_to(REPO_ROOT))
        for base in (REPO_ROOT, REPO_ROOT / "scripts", REPO_ROOT / "tests")
        for pattern in patterns
        for path in base.glob(pattern)
    }


@pytest.fixture(scope="module")
def sharded_run(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """Shard 1/2 under ``-n 2 --dist=loadfile`` and shard 2/2 under ``-n 0``, one evidence dir.

    BF-985: each run also arms the stall watchdog (the default bound) into its own stack dir.
    """
    tree = make_tree(tmp_path_factory.mktemp("shard_tree") / "tree")
    evidence = tree.parent / "evidence"
    stacks = tree.parent / "stacks"
    before = repo_strays()
    first = run_pytest(
        tree, "suite", "-q", "-n", "2", "--dist=loadfile", *shard_options(1, 2, evidence),
        f"--probos-shard-stack-dir={stacks / '1'}",
    )  # fmt: skip
    second = run_pytest(
        tree, "suite", "-q", "-n", "0", *shard_options(2, 2, evidence), f"--probos-shard-stack-dir={stacks / '2'}"
    )
    return SimpleNamespace(
        tree=tree,
        evidence=evidence,
        stacks=stacks,
        durations=tree / "durations.json",
        first=first,
        second=second,
        new_strays=repo_strays() - before,
    )


# --- shard 1/2 under -n 2 and shard 2/2 under -n 0 ----------------------------------


def test_both_shards_pass_and_write_evidence_the_verifier_accepts(
    cs: ModuleType, sharded_run: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    assert sharded_run.first.returncode == 0, sharded_run.first.stdout + sharded_run.first.stderr
    assert sharded_run.second.returncode == 0, sharded_run.second.stdout + sharded_run.second.stderr

    code = verify(cs, sharded_run.evidence, 2, sharded_run.durations)
    out = capsys.readouterr().out

    assert code == 0, out
    assert out.splitlines()[0] == f"verified {len(ALL_NODES)} nodes: every collected node executed exactly once across 2 shards"
    assert "assigned=7 executed=7 workers=2" in out and "assigned=6 executed=6 workers=1" in out


def test_evidence_files_record_the_workers_the_plan_and_every_setup_report(
    sharded_run: SimpleNamespace,
) -> None:
    evidence = read_evidence(sharded_run.evidence)

    assert sorted(evidence) == ["shard-1/gw0", "shard-1/gw1", "shard-2/main"]
    for name, payload in evidence.items():
        assert payload["kind"] == "probos-ci-shard-evidence" and payload["schema_version"] == 1
        assert payload["exitstatus"] == 0 and payload["shard_count"] == 2
        assert payload["collection_count"] == len(ALL_NODES)
        assert payload["durations_path"] == "durations.json"
        assert ("collected_nodeids" in payload) == (name.endswith(("gw0", "main")))
    assert evidence["shard-1/gw0"]["collected_nodeids"] == ALL_NODES
    assert evidence["shard-2/main"]["file_shards"] == EXPECTED_FILE_SHARDS
    assert {evidence["shard-1/gw0"]["worker_count"], evidence["shard-1/gw1"]["worker_count"]} == {2}
    assert evidence["shard-1/gw0"]["testrunuid"] == evidence["shard-1/gw1"]["testrunuid"]
    assert evidence["shard-2/main"]["worker_count"] == 1
    assert re.fullmatch(r"[0-9a-f]{32}", evidence["shard-2/main"]["testrunuid"])
    ran_in_shard_1 = evidence["shard-1/gw0"]["setup_reports"] + evidence["shard-1/gw1"]["setup_reports"]
    assert sorted(ran_in_shard_1) == sorted(ALPHA + DELTA)
    assert sorted(evidence["shard-2/main"]["setup_reports"]) == sorted(BETA + GAMMA)
    assert evidence["shard-1/gw0"]["setup_reports"] and evidence["shard-1/gw1"]["setup_reports"]


def test_the_duration_scheduler_receives_the_shard_filtered_collection(
    sharded_run: SimpleNamespace,
) -> None:
    line = "AD-1270f duration scheduler:"

    assert sharded_run.first.stdout.count(line) == 1
    # The scheduler saw only this shard's 2 files: "heaviest K of N files first ...", N = 2.
    assert "heaviest 2 of 2 files first" in sharded_run.first.stdout
    assert re.search(r"\b7 passed\b", sharded_run.first.stdout)
    assert line not in sharded_run.second.stdout
    assert re.search(r"\b4 passed\b.*\b1 skipped\b.*\b7 deselected\b.*\b1 xfailed\b", sharded_run.second.stdout)


def test_the_runs_wrote_the_evidence_and_empty_stack_files_apart_and_nothing_into_the_repository(
    sharded_run: SimpleNamespace,
) -> None:
    stack_sizes = {
        path.relative_to(sharded_run.stacks).as_posix(): path.stat().st_size
        for path in sharded_run.stacks.rglob("*")
        if path.is_file()
    }

    # BF-985: one stack file per process, outside the evidence, empty after a run that never stalled.
    assert stack_sizes == {
        "1/faulthandler-controller.txt": 0,
        "1/faulthandler-gw0.txt": 0,
        "1/faulthandler-gw1.txt": 0,
        "2/faulthandler-controller.txt": 0,
    }
    assert sharded_run.new_strays == set()
    assert sorted(path.name for path in sharded_run.evidence.iterdir()) == ["shard-1", "shard-2"]
    assert sorted(path.name for path in (sharded_run.evidence / "shard-1").iterdir()) == ["gw0.json", "gw1.json"]
    assert sorted(path.name for path in (sharded_run.evidence / "shard-2").iterdir()) == ["main.json"]


def _copied_evidence(sharded_run: SimpleNamespace, tmp_path: Path) -> Path:
    copy = tmp_path / "evidence"
    shutil.copytree(sharded_run.evidence, copy)
    return copy


def _verify_command_line(evidence: Path, durations: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CI_SHARDS),
            "verify",
            "--evidence-root",
            str(evidence),
            "--shard-count",
            "2",
            "--durations",
            str(durations),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def test_real_evidence_passes_the_verifier_command_line(
    sharded_run: SimpleNamespace, tmp_path: Path
) -> None:
    completed = _verify_command_line(_copied_evidence(sharded_run, tmp_path), sharded_run.durations)

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_dropping_one_node_from_real_evidence_makes_the_verifier_exit_one(
    sharded_run: SimpleNamespace, tmp_path: Path
) -> None:
    evidence = _copied_evidence(sharded_run, tmp_path)
    target = evidence / "shard-2" / "main.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    dropped = payload["setup_reports"].pop()
    target.write_text(json.dumps(payload), encoding="utf-8")

    completed = _verify_command_line(evidence, sharded_run.durations)

    assert completed.returncode == 1
    assert "missing (never executed): 1" in completed.stdout and dropped in completed.stdout
    assert completed.stdout.count("::error") == 1


def test_duplicating_one_node_in_real_evidence_makes_the_verifier_exit_one(
    sharded_run: SimpleNamespace, tmp_path: Path
) -> None:
    evidence = _copied_evidence(sharded_run, tmp_path)
    target = evidence / "shard-2" / "main.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    repeated = payload["setup_reports"][0]
    payload["setup_reports"].append(repeated)
    target.write_text(json.dumps(payload), encoding="utf-8")

    completed = _verify_command_line(evidence, sharded_run.durations)

    assert completed.returncode == 1
    assert f"{repeated} <- shard-2/main x2" in completed.stdout
    assert completed.stdout.count("::error") == 1


def test_real_evidence_executed_in_the_wrong_shard_is_rejected(
    sharded_run: SimpleNamespace, tmp_path: Path
) -> None:
    evidence = _copied_evidence(sharded_run, tmp_path)
    moved = json.loads((evidence / "shard-1" / "gw0.json").read_text(encoding="utf-8"))["setup_reports"][0]
    target = evidence / "shard-2" / "main.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["setup_reports"].append(moved)
    target.write_text(json.dumps(payload), encoding="utf-8")

    completed = _verify_command_line(evidence, sharded_run.durations)

    assert completed.returncode == 1
    assert "belongs to shard-1" in completed.stdout


# --- the filter must never change which tests exist ----------------------------------


@pytest.mark.parametrize(
    ("selection", "removed"),
    [
        (["--deselect=suite/test_beta.py::test_beta_one"], "removed [suite/test_beta.py::test_beta_one]"),
        (["-k", "not beta"], "removed [suite/test_beta.py::test_beta_one, suite/test_beta.py::test_beta_two]"),
    ],
    ids=["deselect", "keyword"],
)
def test_a_run_that_deselects_tests_exits_four_and_names_the_forbidden_change(
    tmp_path: Path, selection: list[str], removed: str
) -> None:
    tree = make_tree(tmp_path / "tree")
    evidence = tmp_path / "evidence"

    result = run_pytest(tree, "suite", "-q", "-n", "0", *selection, *shard_options(1, 2, evidence))

    assert result.returncode == 4, result.stdout + result.stderr
    assert "CI shard plugin forbids another hook removing, adding or renaming collected items" in result.stderr
    assert removed in result.stderr
    assert not evidence.exists()


def test_a_run_without_shard_options_executes_every_test_and_writes_no_evidence(tmp_path: Path) -> None:
    tree = make_tree(tmp_path / "tree")
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    result = run_pytest(tree, "suite", "-v", "-n", "0", *PLUGIN_ARGS)

    outcomes = dict(re.findall(r"^(\S+::\S+) (PASSED|FAILED|SKIPPED|XFAIL|XPASS|ERROR)", result.stdout, re.M))
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(outcomes) == ALL_NODES
    assert outcomes["suite/test_gamma.py::test_gamma_skipped"] == "SKIPPED"
    assert outcomes["suite/test_gamma.py::test_gamma_xfail"] == "XFAIL"
    assert "deselected" not in result.stdout
    assert after == before


def test_the_command_line_form_ci_uses_works_with_space_separated_options(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tree = make_tree(tmp_path / "tree")
    evidence = tmp_path / "ci-shard-evidence"
    stacks = tmp_path / "ci-shard-stacks"
    command = [
        "suite", "-n", "0", "-q", "--tb=short", "--maxfail=10", *PLUGIN_ARGS,
        "--probos-shard-index", "1", "--probos-shard-count", "2",
        "--probos-shard-evidence-dir", str(evidence), "--probos-shard-durations=durations.json",
        "--probos-shard-stack-dir", str(stacks),
    ]  # fmt: skip

    first = run_pytest(tree, *command)
    command[command.index("--probos-shard-index") + 1] = "2"
    second = run_pytest(tree, *command)

    assert (first.returncode, second.returncode) == (0, 0), first.stdout + second.stdout
    assert sorted(read_evidence(evidence)) == ["shard-1/main", "shard-2/main"]
    assert verify(cs, evidence, 2, tree / "durations.json") == 0, capsys.readouterr().out
    assert [(path.name, path.stat().st_size) for path in stacks.iterdir()] == [("faulthandler-controller.txt", 0)]


def test_relative_paths_resolve_against_the_rootpath_not_the_working_directory(tmp_path: Path) -> None:
    tree = make_tree(tmp_path / "tree")

    result = run_pytest(
        tree,
        "-q",
        "-n",
        "0",
        *PLUGIN_ARGS,
        "--probos-shard-index=1",
        "--probos-shard-count=2",
        "--probos-shard-evidence-dir=ev_rel",
        "--probos-shard-durations=durations.json",
        cwd=tree / "suite",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads((tree / "ev_rel" / "shard-1" / "main.json").read_text(encoding="utf-8"))
    assert evidence["durations_path"] == "durations.json"
    assert not (tree / "suite" / "ev_rel").exists()


@pytest.mark.parametrize(
    "case",
    [
        "partial options", "index above count under xdist", "count below one", "default durations absent",
        "bad durations", "stall bound without a stack dir", "stack dir beside faulthandler_timeout under xdist",
    ],
)  # fmt: skip
def test_misconfiguration_exits_four_before_any_test_or_worker_starts(tmp_path: Path, case: str) -> None:
    tree = make_tree(tmp_path / "tree")
    (tree / "bad.json").write_text('{"schema_version": 2, "files": {}}', encoding="utf-8")
    evidence = tmp_path / "evidence"
    stacks = tmp_path / "stacks"
    cases = {
        "partial options": (["-n", "0", *PLUGIN_ARGS, "--probos-shard-index=1"], "must be given together"),
        "index above count under xdist": (
            ["-n", "2", *shard_options(3, 2, evidence)],
            "--probos-shard-index must be within 1..2",
        ),
        "count below one": (["-n", "0", *shard_options(1, 0, evidence)], "--probos-shard-count must be >= 1"),
        "default durations absent": (
            ["-n", "0", *PLUGIN_ARGS, "--probos-shard-index=1", "--probos-shard-count=2",
             f"--probos-shard-evidence-dir={evidence}"],
            "durations file file_durations.json: unreadable",
        ),
        "bad durations": (
            ["-n", "0", *shard_options(1, 2, evidence, durations="bad.json")],
            "durations file bad.json: schema_version must be 1",
        ),
        "stall bound without a stack dir": (
            ["-n", "0", *shard_options(1, 2, evidence), "--probos-shard-stall-seconds=5"],
            "--probos-shard-stall-seconds needs --probos-shard-stack-dir",
        ),
        "stack dir beside faulthandler_timeout under xdist": (
            ["-n", "2", "-o", "faulthandler_timeout=5", *shard_options(1, 2, evidence),
             f"--probos-shard-stack-dir={stacks}"],
            "cannot run with faulthandler_timeout > 0",
        ),
    }  # fmt: skip
    arguments, message = cases[case]

    result = run_pytest(tree, "suite", "-q", *arguments)

    assert result.returncode == 4, result.stdout + result.stderr
    assert message in result.stderr
    assert "bringing up nodes" not in result.stdout and "passed" not in result.stdout
    assert not evidence.exists()
    assert not stacks.exists()


def test_a_red_shard_that_stops_early_is_rejected_for_its_exit_status_and_unexecuted_nodes(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {
        "suite/test_a_fail.py": "def test_first():\n    assert False\n\n\ndef test_second():\n    assert False\n",
        "suite/test_b_pass.py": "def test_b_one():\n    pass\n\n\ndef test_b_two():\n    pass\n",
    }
    tree = make_tree(tmp_path / "tree", files)
    durations = tmp_path / "outside.json"
    durations.write_text('{"schema_version": 1, "files": {}}', encoding="utf-8")
    evidence = tmp_path / "evidence"

    result = run_pytest(
        tree, "suite", "-q", "-n", "0", "--maxfail=1", *shard_options(1, 1, evidence, durations=str(durations))
    )

    payload = read_evidence(evidence)["shard-1/main"]
    assert result.returncode == 1
    assert payload["exitstatus"] == 1
    assert payload["setup_reports"] == ["suite/test_a_fail.py::test_first"]
    assert Path(payload["durations_path"]).is_absolute() and "\\" not in payload["durations_path"]
    assert verify(cs, evidence, 1, durations) == 1
    out = capsys.readouterr().out
    assert "shard-1/main reports exitstatus 1, not 0" in out
    assert "missing (never executed): 3" in out


# --- BF-985: the stall watchdog, against controlled doubles that end by themselves ----

# A distinctively named function that blocks for a few seconds and then returns, so every run ends
# by itself and nothing is killed on the host.
BLOCKER = (
    "def _bf985_blocks_here(seconds):\n"
    "    deadline = time.monotonic() + seconds\n"
    "    while time.monotonic() < deadline:\n"
    "        time.sleep(0.05)\n\n\n"
)
NO_DURATIONS = {"schema_version": 1, "files": {}}


def stack_texts(stacks: Path) -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8", errors="replace") for path in sorted(stacks.iterdir())}


def test_a_worker_that_stalls_inside_a_test_is_dumped_by_name_and_the_controller_shows_its_wait(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {
        "suite/test_stalls.py": "import time\n\n\n" + BLOCKER + "def test_stalls_then_returns():\n    _bf985_blocks_here(5)\n",
        "suite/test_quick.py": "def test_quick():\n    pass\n",
    }
    tree = make_tree(tmp_path / "tree", files, durations=NO_DURATIONS)
    evidence = tmp_path / "evidence"
    stacks = tmp_path / "stacks"

    result = run_pytest(
        tree, "suite", "-q", "-n", "2", "--dist=loadfile", *shard_options(1, 1, evidence),
        f"--probos-shard-stack-dir={stacks}", "--probos-shard-stall-seconds=1",
    )  # fmt: skip

    texts = stack_texts(stacks)
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"\b2 passed\b", result.stdout)
    assert sorted(texts) == ["faulthandler-controller.txt", "faulthandler-gw0.txt", "faulthandler-gw1.txt"]
    stalled = [name for name in ("faulthandler-gw0.txt", "faulthandler-gw1.txt") if "_bf985_blocks_here" in texts[name]]
    assert len(stalled) == 1, texts
    assert "Timeout (0:00:01" in texts[stalled[0]] and "test_stalls_then_returns" in texts[stalled[0]]
    # The controller waits in xdist's event loop while the worker blocks.
    assert "dsession.py" in texts["faulthandler-controller.txt"]
    assert "_bf985_blocks_here" not in texts["faulthandler-controller.txt"]
    assert sorted(path.name for path in evidence.iterdir()) == ["shard-1"]
    assert verify(cs, evidence, 1, tree / "durations.json") == 0, capsys.readouterr().out


def test_a_failing_test_leaves_the_watchdog_armed_for_the_silence_after_it(tmp_path: Path) -> None:
    """pytest's faulthandler plugin cancels the process's one timer in pytest_exception_interact."""
    files = {
        "suite/test_fails.py": (
            "import time\n\nimport pytest\n\n\n" + BLOCKER
            + "@pytest.fixture\ndef slow_teardown():\n    yield\n    _bf985_blocks_here(4)\n\n\n"
            "def test_fails_then_tears_down_slowly(slow_teardown):\n    assert False\n"
        ),
    }
    tree = make_tree(tmp_path / "tree", files, durations=NO_DURATIONS)
    stacks = tmp_path / "stacks"

    result = run_pytest(
        tree, "suite", "-q", "-n", "0", *shard_options(1, 1, tmp_path / "evidence"),
        f"--probos-shard-stack-dir={stacks}", "--probos-shard-stall-seconds=1",
    )  # fmt: skip

    text = stack_texts(stacks)["faulthandler-controller.txt"]
    assert result.returncode == 1, result.stdout + result.stderr
    assert re.search(r"\b1 failed\b", result.stdout)
    assert "_bf985_blocks_here" in text and "slow_teardown" in text


def test_a_process_held_open_at_exit_by_a_leftover_thread_is_dumped_during_shutdown(tmp_path: Path) -> None:
    """The #1419 shape: interpreter shutdown joins a non-daemon thread after every pytest hook ran."""
    files = {
        "suite/test_leaves_a_thread.py": (
            "import threading\nimport time\n\n\n" + BLOCKER
            + "def test_leaves_a_non_daemon_thread_behind():\n"
            "    threading.Thread(target=_bf985_blocks_here, args=(4,), daemon=False).start()\n"
        ),
    }
    tree = make_tree(tmp_path / "tree", files, durations=NO_DURATIONS)
    stacks = tmp_path / "stacks"

    result = run_pytest(
        tree, "suite", "-q", "-n", "0", *shard_options(1, 1, tmp_path / "evidence"),
        f"--probos-shard-stack-dir={stacks}", "--probos-shard-stall-seconds=1",
    )  # fmt: skip

    text = stack_texts(stacks)["faulthandler-controller.txt"]
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"\b1 passed\b", result.stdout)
    assert "_bf985_blocks_here" in text
    assert "_shutdown" in text  # the main thread is in threading._shutdown, after pytest returned


# --- the plugin's hooks, driven in-process for every branch --------------------------


@pytest.fixture(scope="module")
def plugin() -> ModuleType:
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(REPO_ROOT))
        return _load("ci_shard_plugin_under_test", PLUGIN)


class FakeHook:
    def __init__(self) -> None:
        self.deselected: list[list[str]] = []

    def pytest_deselected(self, items: list[Any]) -> None:
        self.deselected.append([item.nodeid for item in items])


class FakeConfig:
    def __init__(self, rootpath: Path, **options: Any) -> None:
        self.rootpath = rootpath
        self.options = options
        self.hook = FakeHook()
        self.registered: list[tuple[str, Any]] = []
        self.pluginmanager = SimpleNamespace(
            register=lambda recorder, name: self.registered.append((name, recorder))
        )

    def getoption(self, name: str) -> Any:
        return self.options.get(name)


def configured(plugin: ModuleType, root: Path, index: int = 2, count: int = 2, **options: Any) -> tuple[FakeConfig, Any]:
    (root / "durations.json").write_text(json.dumps(DURATIONS), encoding="utf-8")
    values = {
        "probos_shard_index": index,
        "probos_shard_count": count,
        "probos_shard_evidence_dir": "ev",
        "probos_shard_durations": "durations.json",
        **options,
    }
    config = FakeConfig(root, **values)
    plugin.pytest_configure(config)
    [(_, recorder)] = config.registered
    return config, recorder


def collect(recorder: Any, config: FakeConfig, nodeids: list[str], between: Any = None) -> list[Any]:
    items = [SimpleNamespace(nodeid=nodeid) for nodeid in nodeids]
    hook = recorder.pytest_collection_modifyitems(session=None, config=config, items=items)
    next(hook)
    if between is not None:
        between(items)
    with pytest.raises(StopIteration):
        hook.send(None)
    return items


def written(root: Path, name: str = "ev/shard-2/main.json") -> dict[str, Any]:
    return json.loads((root / name).read_text(encoding="utf-8"))


class WatchdogConfig(FakeConfig):
    """A FakeConfig with ``getini`` (a missing key raises as pytest does) and an optional ``workerinput``."""

    def __init__(
        self, rootpath: Path, *, ini: dict[str, Any], workerinput: dict[str, Any] | None, **options: Any
    ) -> None:
        super().__init__(rootpath, **options)
        self.ini = ini
        if workerinput is not None:
            self.workerinput = workerinput

    def getini(self, name: str) -> Any:
        if name not in self.ini:
            raise ValueError(f"unknown configuration value: {name!r}")
        return self.ini[name]


def watchdog_configured(
    plugin: ModuleType,
    root: Path,
    *,
    ini: dict[str, Any] | None = None,
    workerinput: dict[str, Any] | None = None,
    **options: Any,
) -> tuple[WatchdogConfig, dict[str, Any]]:
    (root / "durations.json").write_text(json.dumps(DURATIONS), encoding="utf-8")
    values = {
        "probos_shard_index": 2,
        "probos_shard_count": 2,
        "probos_shard_evidence_dir": "ev",
        "probos_shard_durations": "durations.json",
        "probos_shard_stack_dir": "stacks",
        **options,
    }
    config = WatchdogConfig(
        root, ini={"faulthandler_timeout": "0"} if ini is None else ini, workerinput=workerinput, **values
    )
    plugin.pytest_configure(config)
    return config, dict(config.registered)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_plugin_module_is_marked_unrewritten_and_never_imports_the_gate_plugin() -> None:
    import ast

    tree = ast.parse(PLUGIN.read_text(encoding="utf-8"))
    imports = [
        (node.module or "", [alias.name for alias in node.names]) if isinstance(node, ast.ImportFrom)
        else ("", [alias.name for alias in node.names])
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]

    assert "PYTEST_DONT_REWRITE" in (ast.get_docstring(tree) or "")
    assert ("scripts", ["ci_shards"]) in imports
    assert not [entry for entry in imports if "gate" in entry[0] or any("gate" in name for name in entry[1])]


def test_addoption_registers_the_six_options_with_no_defaults(plugin: ModuleType) -> None:
    added: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    group = SimpleNamespace(addoption=lambda *names, **kwargs: added.append((names, kwargs)))
    parser = SimpleNamespace(getgroup=lambda *args: group)

    plugin.pytest_addoption(parser)

    assert [names for names, _ in added] == [
        ("--probos-shard-index",),
        ("--probos-shard-count",),
        ("--probos-shard-evidence-dir",),
        ("--probos-shard-durations",),
        ("--probos-shard-stack-dir",),
        ("--probos-shard-stall-seconds",),
    ]
    assert all(kwargs["default"] is None for _, kwargs in added)
    assert [kwargs.get("type") for _, kwargs in added] == [int, int, None, None, None, int]


def test_configure_is_inert_without_any_of_the_three_shard_options(plugin: ModuleType, tmp_path: Path) -> None:
    for options in (
        {},
        {"probos_shard_durations": "ignored.json"},
        {"probos_shard_stack_dir": "stacks", "probos_shard_stall_seconds": 5},
    ):
        config = FakeConfig(tmp_path, **options)

        plugin.pytest_configure(config)

        assert config.registered == []
    assert not (tmp_path / "stacks").exists()


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"probos_shard_count": None, "probos_shard_evidence_dir": None}, "must be given together"),
        ({"probos_shard_evidence_dir": None}, "must be given together"),
        ({"probos_shard_index": None}, "must be given together"),
        ({"probos_shard_count": 0}, r"--probos-shard-count must be >= 1, got 0"),
        ({"probos_shard_index": 0}, r"within 1\.\.2 .* got 0"),
        ({"probos_shard_index": 3}, r"within 1\.\.2 .* got 3"),
        ({"probos_shard_index": -1}, r"within 1\.\.2 .* got -1"),
        ({"probos_shard_evidence_dir": "  "}, "must not be empty"),
        ({"probos_shard_durations": "absent.json"}, "durations file absent.json: unreadable"),
        ({"probos_shard_stall_seconds": 5}, "--probos-shard-stall-seconds needs --probos-shard-stack-dir"),
        ({"probos_shard_stack_dir": "  "}, "--probos-shard-stack-dir must not be empty"),
        (
            {"probos_shard_stack_dir": "stacks", "probos_shard_stall_seconds": 0},
            r"--probos-shard-stall-seconds must be >= 1, got 0",
        ),
    ],
)
def test_configure_rejects_misconfiguration_with_a_usage_error(
    plugin: ModuleType, tmp_path: Path, options: dict[str, Any], message: str
) -> None:
    (tmp_path / "durations.json").write_text(json.dumps(DURATIONS), encoding="utf-8")
    config = FakeConfig(
        tmp_path,
        probos_shard_index=1,
        probos_shard_count=2,
        probos_shard_evidence_dir="ev",
        probos_shard_durations="durations.json",
    )
    config.options.update(options)

    with pytest.raises(pytest.UsageError, match=message):
        plugin.pytest_configure(config)

    assert config.registered == []


def test_configure_turns_a_key_rule_fault_into_a_usage_error(
    plugin: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "durations.json").write_text(json.dumps(DURATIONS), encoding="utf-8")
    monkeypatch.setattr(plugin.ci_shards, "_GENERATOR_PATH", tmp_path / "missing.py")
    config = FakeConfig(
        tmp_path,
        probos_shard_index=1,
        probos_shard_count=2,
        probos_shard_evidence_dir="ev",
        probos_shard_durations="durations.json",
    )

    with pytest.raises(pytest.UsageError, match=r"cannot load the key rule from missing\.py \(FileNotFoundError\)"):
        plugin.pytest_configure(config)

    assert config.registered == []


def test_configure_uses_the_default_durations_file_under_the_rootpath(plugin: ModuleType, tmp_path: Path) -> None:
    fixtures = tmp_path / "tests" / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "file_durations.json").write_text(json.dumps(DURATIONS), encoding="utf-8")
    config = FakeConfig(
        tmp_path, probos_shard_index=2, probos_shard_count=2, probos_shard_evidence_dir="ev"
    )

    plugin.pytest_configure(config)
    [(name, recorder)] = config.registered
    collect(recorder, config, ALL_NODES)
    recorder.pytest_sessionfinish(SimpleNamespace(config=SimpleNamespace()), 0)

    assert name == "probos-ci-shard-recorder"
    assert written(tmp_path)["durations_path"] == "tests/fixtures/file_durations.json"


def test_recorder_keeps_only_its_shards_files_and_deselects_the_rest(plugin: ModuleType, tmp_path: Path) -> None:
    config, recorder = configured(plugin, tmp_path, index=1)

    items = collect(recorder, config, ALL_NODES)

    assert sorted(item.nodeid for item in items) == sorted(ALPHA + DELTA)
    assert config.hook.deselected == [[node for node in ALL_NODES if node in BETA + GAMMA]]


def test_recorder_does_not_report_a_deselection_when_its_shard_owns_everything(
    plugin: ModuleType, tmp_path: Path
) -> None:
    config, recorder = configured(plugin, tmp_path, index=1, count=1)

    items = collect(recorder, config, ALL_NODES)

    assert [item.nodeid for item in items] == ALL_NODES
    assert config.hook.deselected == []


def test_recorder_allows_another_hook_to_reorder_the_items(plugin: ModuleType, tmp_path: Path) -> None:
    config, recorder = configured(plugin, tmp_path, index=2)

    items = collect(recorder, config, ALL_NODES, between=lambda collected: collected.reverse())

    assert [item.nodeid for item in items] == [node for node in reversed(ALL_NODES) if node in BETA + GAMMA]


def test_recorder_refuses_items_another_hook_removed(plugin: ModuleType, tmp_path: Path) -> None:
    config, recorder = configured(plugin, tmp_path)

    def remove(items: list[Any]) -> None:
        del items[0]

    with pytest.raises(pytest.UsageError, match=r"removed \[suite/test_alpha.py::TestAlpha::test_one\], added \[\]"):
        collect(recorder, config, ALL_NODES, between=remove)

    assert config.hook.deselected == []


def test_recorder_refuses_items_another_hook_added_or_renamed(plugin: ModuleType, tmp_path: Path) -> None:
    config, recorder = configured(plugin, tmp_path)

    with pytest.raises(pytest.UsageError, match=r"removed \[\], added \[suite/test_new.py::test_new\]"):
        collect(recorder, config, ALL_NODES, between=lambda items: items.append(SimpleNamespace(nodeid="suite/test_new.py::test_new")))
    with pytest.raises(pytest.UsageError, match=r"removed \[suite/test_beta.py::test_beta_one\].*added \[suite/test_beta.py::renamed\]"):
        collect(
            recorder,
            config,
            ALL_NODES,
            between=lambda items: setattr(
                next(item for item in items if item.nodeid == BETA[0]), "nodeid", "suite/test_beta.py::renamed"
            ),
        )


def test_recorder_refuses_a_collection_with_duplicate_node_ids(plugin: ModuleType, tmp_path: Path) -> None:
    config, recorder = configured(plugin, tmp_path)

    with pytest.raises(pytest.UsageError, match=r"duplicate node IDs \[suite/test_beta.py::test_beta_one\]"):
        collect(recorder, config, [*ALL_NODES, BETA[0]])


def test_recorder_cannot_split_fewer_files_than_shards(plugin: ModuleType, tmp_path: Path) -> None:
    config, recorder = configured(plugin, tmp_path, index=1, count=2)

    with pytest.raises(pytest.UsageError, match="cannot split the collection into 2 shards"):
        collect(recorder, config, ALPHA)


def test_recorder_writes_the_evidence_of_a_single_process_run(plugin: ModuleType, tmp_path: Path) -> None:
    config, recorder = configured(plugin, tmp_path, index=2)
    collect(recorder, config, ALL_NODES)
    for when, nodeid in [("setup", BETA[0]), ("call", BETA[0]), ("teardown", BETA[0]), ("setup", BETA[0]), ("setup", GAMMA[0])]:
        recorder.pytest_runtest_logreport(SimpleNamespace(when=when, nodeid=nodeid))

    recorder.pytest_sessionfinish(SimpleNamespace(config=SimpleNamespace()), pytest.ExitCode.TESTS_FAILED)

    payload = written(tmp_path)
    assert payload["setup_reports"] == [BETA[0], BETA[0], GAMMA[0]]
    assert (payload["worker_id"], payload["worker_count"], payload["exitstatus"]) == ("main", 1, 1)
    assert re.fullmatch(r"[0-9a-f]{32}", payload["testrunuid"])
    assert payload["collected_nodeids"] == ALL_NODES and payload["assigned_count"] == len(BETA + GAMMA)


def test_recorder_writes_the_evidence_of_an_xdist_worker(plugin: ModuleType, tmp_path: Path) -> None:
    config, recorder = configured(plugin, tmp_path, index=1)
    collect(recorder, config, ALL_NODES)
    worker = SimpleNamespace(workerinput={"workerid": "gw3", "workercount": 4, "testrunuid": "abc123"})

    recorder.pytest_sessionfinish(SimpleNamespace(config=worker), 0)

    payload = written(tmp_path, "ev/shard-1/gw3.json")
    assert (payload["worker_id"], payload["worker_count"], payload["testrunuid"]) == ("gw3", 4, "abc123")
    assert "collected_nodeids" not in payload and payload["setup_reports"] == []


def test_recorder_ignores_reports_and_writes_nothing_when_it_never_collected(
    plugin: ModuleType, tmp_path: Path
) -> None:
    config, recorder = configured(plugin, tmp_path)

    recorder.pytest_runtest_logreport(SimpleNamespace(when="setup", nodeid=BETA[0]))
    recorder.pytest_sessionfinish(SimpleNamespace(config=SimpleNamespace()), 0)

    assert not (tmp_path / "ev").exists()


def test_recorder_writes_nothing_after_the_collection_was_refused(plugin: ModuleType, tmp_path: Path) -> None:
    config, recorder = configured(plugin, tmp_path)
    with pytest.raises(pytest.UsageError):
        collect(recorder, config, [*ALL_NODES, BETA[0]])

    recorder.pytest_sessionfinish(SimpleNamespace(config=SimpleNamespace()), 4)

    assert not (tmp_path / "ev").exists()


def test_recorder_records_a_durations_file_outside_the_rootpath_as_an_absolute_posix_path(
    plugin: ModuleType, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(DURATIONS), encoding="utf-8")
    config, recorder = configured(plugin, root, probos_shard_durations=str(outside))
    collect(recorder, config, ALL_NODES)

    recorder.pytest_sessionfinish(SimpleNamespace(config=SimpleNamespace()), 0)

    assert written(root)["durations_path"] == outside.resolve().as_posix()


def test_recorder_refuses_a_worker_id_it_cannot_name_a_file_after(plugin: ModuleType, tmp_path: Path) -> None:
    config, recorder = configured(plugin, tmp_path)
    collect(recorder, config, ALL_NODES)
    worker = SimpleNamespace(workerinput={"workerid": "../gw0", "workercount": 2, "testrunuid": "u"})

    with pytest.raises(ValueError, match="not main or gw"):
        recorder.pytest_sessionfinish(SimpleNamespace(config=worker), 0)

    assert not (tmp_path / "ev").exists()


def test_recorder_lets_an_unwritable_evidence_directory_fail_loudly(plugin: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "ev").write_text("a file where the evidence directory belongs", encoding="utf-8")
    config, recorder = configured(plugin, tmp_path)
    collect(recorder, config, ALL_NODES)

    with pytest.raises(OSError):
        recorder.pytest_sessionfinish(SimpleNamespace(config=SimpleNamespace()), 0)


# --- BF-985: the stall watchdog's configuration and hooks -----------------------------


@pytest.mark.parametrize("value", ["5", 5.0])
def test_configure_refuses_a_stack_dir_beside_pytests_faulthandler_timeout(
    plugin: ModuleType, tmp_path: Path, value: Any
) -> None:
    with pytest.raises(pytest.UsageError, match="cannot run with faulthandler_timeout > 0"):
        watchdog_configured(plugin, tmp_path, ini={"faulthandler_timeout": value})

    assert not (tmp_path / "stacks").exists()


@pytest.mark.parametrize(
    "ini", [{"faulthandler_timeout": "0"}, {}], ids=["timeout zero", "pytest faulthandler plugin off"]
)
def test_configure_accepts_a_stack_dir_when_nothing_else_drives_the_timer(
    plugin: ModuleType, tmp_path: Path, ini: dict[str, Any]
) -> None:
    _, registered = watchdog_configured(plugin, tmp_path, ini=ini, probos_shard_stall_seconds=7)
    watchdog = registered["probos-ci-stall-watchdog"]
    watchdog.stream.close()

    assert list(registered) == ["probos-ci-shard-recorder", "probos-ci-stall-watchdog"]
    assert watchdog.stall_seconds == 7


@pytest.mark.parametrize(
    ("workerinput", "name"),
    [
        (None, "faulthandler-controller.txt"),
        ({"workerid": "gw3", "workercount": 4, "testrunuid": "u"}, "faulthandler-gw3.txt"),
    ],
)
def test_configure_opens_this_processs_stack_file_and_arms_only_when_the_session_starts(
    plugin: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workerinput: dict[str, Any] | None,
    name: str,
) -> None:
    calls: list[tuple[int, dict[str, Any]]] = []
    monkeypatch.setattr(plugin.faulthandler, "dump_traceback_later", lambda seconds, **kw: calls.append((seconds, kw)))

    _, registered = watchdog_configured(plugin, tmp_path, workerinput=workerinput)
    watchdog = registered["probos-ci-stall-watchdog"]
    try:
        assert Path(watchdog.stream.name) == tmp_path / "stacks" / name
        assert sorted(path.name for path in (tmp_path / "stacks").iterdir()) == [name]
        assert watchdog.stall_seconds == 600 and calls == []

        watchdog.pytest_sessionstart()

        assert calls == [(600, {"repeat": True, "file": watchdog.stream})]
    finally:
        watchdog.stream.close()
    assert (tmp_path / "stacks" / name).read_text(encoding="utf-8") == ""


def test_configure_refuses_a_worker_id_it_cannot_name_a_stack_file_after(plugin: ModuleType, tmp_path: Path) -> None:
    worker = {"workerid": "../gw0", "workercount": 2, "testrunuid": "u"}

    with pytest.raises(pytest.UsageError, match="cannot name a stack file"):
        watchdog_configured(plugin, tmp_path, workerinput=worker)

    assert not (tmp_path / "stacks").exists()


def test_watchdog_rearms_on_test_events_at_most_once_per_twentieth_of_the_bound(
    plugin: ModuleType, tmp_path: Path
) -> None:
    calls: list[tuple[int, dict[str, Any]]] = []
    clock = FakeClock()
    with (tmp_path / "s.txt").open("w", encoding="utf-8") as stream:
        fresh = plugin.StallWatchdog(stream=stream, stall_seconds=600, arm=lambda s, **kw: calls.append((s, kw)), clock=clock)
        fresh.pytest_runtest_logreport()  # never armed: the first event arms
        assert len(calls) == 1
        calls.clear()
        watchdog = plugin.StallWatchdog(
            stream=stream, stall_seconds=600, arm=lambda s, **kw: calls.append((s, kw)), clock=clock
        )
        watchdog.pytest_sessionstart()
        armed = []
        for now, hook in [
            (10.0, watchdog.pytest_runtest_logstart),
            (29.9, watchdog.pytest_runtest_logreport),
            (30.0, watchdog.pytest_runtest_logreport),
            (59.9, watchdog.pytest_runtest_logstart),
            (60.0, watchdog.pytest_runtest_logstart),
        ]:
            clock.now = now
            before = len(calls)
            hook()
            armed.append(len(calls) > before)

    assert armed == [False, False, True, False, True]
    assert calls == [(600, {"repeat": True, "file": stream})] * 3


def test_watchdog_rearms_inside_the_gap_where_pytest_cancels_the_timer_and_as_the_session_ends(
    plugin: ModuleType, tmp_path: Path
) -> None:
    calls: list[float] = []
    clock = FakeClock()
    with (tmp_path / "s.txt").open("w", encoding="utf-8") as stream:
        watchdog = plugin.StallWatchdog(
            stream=stream, stall_seconds=600, arm=lambda s, **kw: calls.append(clock.now), clock=clock
        )
        watchdog.pytest_sessionstart()
        for now, hook in [
            (1.0, watchdog.pytest_exception_interact),
            (2.0, watchdog.pytest_sessionfinish),
            (3.0, watchdog.pytest_unconfigure),
            (3.5, watchdog.pytest_runtest_logreport),
        ]:
            clock.now = now
            hook()

    assert calls == [0.0, 1.0, 2.0, 3.0]
