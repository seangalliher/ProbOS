from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "run_test_gate.py"


def _load_gate_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_test_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    return _load_gate_module()


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=repo, check=True, capture_output=True)


def _make_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "tracked.txt").write_text("first\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "initial",
    )
    return repo


def _make_gate_repo(tmp_path: Path) -> Path:
    repo = _make_git_repo(tmp_path)
    (repo / ".gitignore").write_text(
        "/logs/\n__pycache__/\n*.py[cod]\n", encoding="utf-8"
    )
    package = repo / "src" / "probos"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "ORIGIN = 'gate-test-repo'\n", encoding="utf-8"
    )
    (repo / "scripts").mkdir()
    shutil.copy2(
        REPO_ROOT / "scripts" / "_gate_process_supervisor.py",
        repo / "scripts" / "_gate_process_supervisor.py",
    )
    shutil.copy2(
        REPO_ROOT / "scripts" / "_gate_pytest_plugin.py",
        repo / "scripts" / "_gate_pytest_plugin.py",
    )
    (repo / "tests").mkdir()
    _git(
        repo,
        "add",
        ".gitignore",
        "scripts/_gate_pytest_plugin.py",
        "scripts/_gate_process_supervisor.py",
        "src/probos/__init__.py",
    )
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "gate fixture",
    )
    return repo


def _only_manifest(repo: Path) -> dict[str, object]:
    manifests = [
        path
        for path in (repo / "logs" / "gates").glob("*.json")
        if not path.name.endswith(".receipt.json")
        and not path.name.endswith(".collection.json")
    ]
    assert len(manifests) == 1
    return json.loads(manifests[0].read_text(encoding="utf-8"))


def _gate_stub_source(exit_code: int) -> str:
    if exit_code != 0:
        return (
            "from pathlib import Path\n"
            "import sys\n"
            "Path(__file__).with_name('gate-args.txt').write_text(' '.join(sys.argv[1:]))\n"
            f"raise SystemExit({exit_code})\n"
        )
    return """from pathlib import Path
import hashlib
import json
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
Path(__file__).with_name("gate-args.txt").write_text(" ".join(sys.argv[1:]))
label = sys.argv[sys.argv.index("--label") + 1]
receipt_path = Path(sys.argv[sys.argv.index("--receipt") + 1])
receipt_path.parent.mkdir(parents=True, exist_ok=True)
junit_path = receipt_path.with_suffix(".xml")
manifest_path = receipt_path.with_suffix(".manifest.json")
collection_path = receipt_path.with_suffix(".collection.json")
junit = (
    '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
    '<testcase name="stub" file="tests/test_stub.py" />'
    '</testsuite></testsuites>'
)
junit_path.write_text(junit)
totals = {"tests": 1, "failures": 0, "errors": 0, "skipped": 0, "time_seconds": 0.0, "extra_reports": 0}
collection_totals = {"nodes": 1, "workers": 1, "sha256": "fixture-nodes"}
collection_path.write_text(json.dumps({"collected_nodeids": ["tests/test_stub.py::test_stub"]}))
manifest = {
    "wrapper_exit_code": 0,
    "preflight_exit_code": 0,
    "pytest_exit_code": 0,
    "preflight_only": False,
    "tree_changed": False,
    "junit_totals": totals,
    "collection_path": collection_path.relative_to(root).as_posix(),
    "collection_totals": collection_totals,
}
manifest_path.write_text(json.dumps(manifest, sort_keys=True))
git = lambda *args: subprocess.check_output(["git", *args], cwd=root, text=True).strip()
status = subprocess.check_output(
    ["git", "status", "--porcelain=v1", "--untracked-files=all"],
    cwd=root,
    text=True,
)
status_hash = hashlib.sha256("\\n".join(status.splitlines()).encode()).hexdigest()
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
receipt = {
    "schema_version": 1,
    "label": label,
    "status": {
        "wrapper_exit_code": 0,
        "preflight_exit_code": 0,
        "pytest_exit_code": 0,
        "preflight_only": False,
        "tree_changed": False,
    },
    "tree": {
        "head": git("rev-parse", "HEAD"),
        "head_tree": git("rev-parse", "HEAD^{tree}"),
        "index_tree": git("write-tree"),
        "status_sha256": status_hash,
    },
    "manifest": {
        "path": manifest_path.relative_to(root).as_posix(),
        "sha256": sha(manifest_path),
    },
    "junit": {
        "path": junit_path.relative_to(root).as_posix(),
        "sha256": sha(junit_path),
        "totals": totals,
    },
    "collection": {
        "path": collection_path.relative_to(root).as_posix(),
        "sha256": sha(collection_path),
        "totals": collection_totals,
    },
}
receipt_path.write_text(json.dumps(receipt, sort_keys=True))
"""


def test_streaming_command_preserves_failure_exit_and_output(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = io.StringIO()

    exit_code = gate._run_streaming_command(
        [sys.executable, "-c", "import sys; print('gate-canary'); sys.exit(7)"],
        cwd=tmp_path,
        log=log,
        env=os.environ.copy(),
    )

    assert exit_code == 7
    assert "gate-canary" in log.getvalue()
    assert "gate-canary" in capsys.readouterr().out


def test_full_command_uses_stable_parallelism_and_timing_artifacts(
    gate: ModuleType, tmp_path: Path
) -> None:
    junit = tmp_path / "result.xml"

    command = gate._build_full_command(
        repo_root=tmp_path,
        junit_path=junit,
        workers=16,
        distribution="loadfile",
    )

    assert command[:3] == [sys.executable, "-I", "-c"]
    assert "import pytest" in command[3]
    overrides = [
        command[index + 1]
        for index, value in enumerate(command)
        if value == "-o"
    ]
    assert overrides == list(gate._PYTEST_CONFIG_OVERRIDES)
    assert command[command.index("-n") + 1] == "16"
    assert "--dist=loadfile" in command
    assert "--durations=50" in command
    assert f"--junitxml={junit}" in command


def test_preflight_contains_import_origin_generated_and_compile_checks(
    gate: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "src").mkdir()
    _git(tmp_path, "init", "-q")
    specs = gate._preflight_specs(tmp_path)
    flattened = [item for spec in specs for item in spec.command]

    assert [spec.name for spec in specs] == [
        "import-origin",
        "config-reference",
        "ad-ledger",
        "seam-contracts",
        "compile",
    ]
    assert "scripts/gen_config_reference.py" in flattened
    assert "scripts/gen_ad_ledger.py" in flattened
    assert "scripts/check_seam_contracts.py" in flattened
    assert "compileall" in flattened
    assert "probos.__file__" in " ".join(specs[0].command)


def test_worktree_check_rejects_unstaged_then_accepts_staged_change(
    gate: ModuleType, tmp_path: Path
) -> None:
    repo = _make_git_repo(tmp_path)
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")

    errors = gate._blocking_worktree_errors(repo)
    assert any("unstaged" in error.lower() for error in errors)

    _git(repo, "add", "tracked.txt")
    assert gate._blocking_worktree_errors(repo) == []


def test_worktree_check_rejects_untracked_test_but_not_unrelated_note(
    gate: ModuleType, tmp_path: Path
) -> None:
    repo = _make_git_repo(tmp_path)
    (repo / "notes.txt").write_text("local note\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_new.py").write_text(
        "def test_new():\n    assert True\n", encoding="utf-8"
    )

    errors = gate._blocking_worktree_errors(repo)

    assert len(errors) == 1
    assert "tests/test_new.py" in errors[0]
    assert "notes.txt" not in errors[0]


def test_worktree_check_rejects_unicode_untracked_test(
    gate: ModuleType, tmp_path: Path
) -> None:
    repo = _make_git_repo(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_tést.py").write_text(
        "def test_unicode():\n    assert True\n", encoding="utf-8"
    )

    errors = gate._blocking_worktree_errors(repo)

    assert len(errors) == 1
    assert "tests/test_tést.py" in errors[0]


@pytest.mark.parametrize(
    "name",
    [
        ".pytest.ini",
        "conftest.py",
        "pytest.py",
        "sitecustomize.py",
        "usercustomize.py",
    ],
)
def test_worktree_check_rejects_untracked_root_startup_customization(
    gate: ModuleType, tmp_path: Path, name: str
) -> None:
    repo = _make_git_repo(tmp_path)
    (repo / name).write_text("raise RuntimeError('must not load')\n", encoding="utf-8")

    errors = gate._blocking_worktree_errors(repo)

    assert len(errors) == 1
    assert name in errors[0]


def test_worktree_check_rejects_ignored_root_pytest_config(
    gate: ModuleType, tmp_path: Path
) -> None:
    repo = _make_git_repo(tmp_path)
    (repo / ".gitignore").write_text(".pytest.ini\n", encoding="utf-8")
    (repo / ".pytest.ini").write_text(
        "[pytest]\naddopts = --ignore=tests\n", encoding="utf-8"
    )

    errors = gate._blocking_worktree_errors(repo)

    assert any(".pytest.ini" in error for error in errors)


def test_worktree_check_rejects_ignored_nested_conftest(
    gate: ModuleType, tmp_path: Path
) -> None:
    repo = _make_git_repo(tmp_path)
    tests = repo / "tests"
    tests.mkdir()
    (repo / ".gitignore").write_text("tests/conftest.py\n", encoding="utf-8")
    (tests / "conftest.py").write_text(
        "def pytest_collection_modifyitems(items):\n    items.clear()\n",
        encoding="utf-8",
    )

    errors = gate._blocking_worktree_errors(repo)

    assert any("tests/conftest.py" in error for error in errors)


def test_gate_lock_rejects_overlap_and_cleans_up(
    gate: ModuleType, tmp_path: Path
) -> None:
    lock_path = tmp_path / "gate.lock"

    with gate.GateLock(lock_path):
        assert lock_path.exists()
        with pytest.raises(RuntimeError, match="Another run_test_gate.py"):
            with gate.GateLock(lock_path):
                pass
    first_size = lock_path.stat().st_size

    with gate.GateLock(lock_path):
        assert lock_path.exists()
    assert lock_path.stat().st_size == first_size
    assert lock_path.read_bytes().count(b"pid=") == 1


def test_linked_worktrees_share_one_gate_lock(
    gate: ModuleType, tmp_path: Path
) -> None:
    repo = _make_git_repo(tmp_path)
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "--detach", "-q", str(linked), "HEAD")

    main_lock = gate._gate_lock_path(repo)
    linked_lock = gate._gate_lock_path(linked)

    assert linked_lock == main_lock
    with gate.GateLock(main_lock):
        with pytest.raises(RuntimeError, match="Another run_test_gate.py"):
            with gate.GateLock(linked_lock):
                pass


def test_parse_pytest_process_lines_filters_noise_and_own_process(
    gate: ModuleType,
) -> None:
    output = (
        "not-a-pid\tpython.exe\tpytest ignored\n"
        "40\tpython.exe\tpython.exe worker.py --note pytest documentation\n"
        "41\tpython.exe\tpython.exe worker.py --label notpytest\n"
        "42\tpython.exe\tpython.exe -m pytest tests/test_one.py\n"
        "43\tpytest.exe\tD:\\ProbOS\\.venv\\Scripts\\pytest.exe tests/ -q\n"
        "44\tpy.test.exe\tpy.test tests/ -q\n"
        "45\tpython.exe\tpython.exe -m py.test tests/\n"
        "46\tpython.exe\tpython.exe -m pytest tests/\n"
        "47\tpython3.12\tpython3.12 -m pytest tests/\n"
    )

    processes = gate._parse_pytest_process_lines(output, own_pid=42)

    assert processes == [
        "pid=43 name=pytest.exe command=D:\\ProbOS\\.venv\\Scripts\\pytest.exe tests/ -q",
        "pid=44 name=py.test.exe command=py.test tests/ -q",
        "pid=45 name=python.exe command=python.exe -m py.test tests/",
        "pid=46 name=python.exe command=python.exe -m pytest tests/",
        "pid=47 name=python3.12 command=python3.12 -m pytest tests/",
    ]


def test_subprocess_env_strips_hidden_pytest_controls(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in gate._PYTEST_CONTROL_ENV:
        monkeypatch.setenv(name, "hostile")

    env = gate._subprocess_env(tmp_path)

    assert gate._PYTEST_CONTROL_ENV.isdisjoint(env)
    assert env["PYTHONPATH"] == str((tmp_path / "src").resolve())
    assert "PYTHONHOME" not in env
    assert env["PYTHONNOUSERSITE"] == "1"


def test_subprocess_env_prevents_pythonoptimize_false_green(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONOPTIMIZE", "1")

    completed = subprocess.run(
        [sys.executable, "-P", "-c", "assert False, 'must execute'"],
        cwd=tmp_path,
        env=gate._subprocess_env(tmp_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode != 0
    assert "must execute" in completed.stderr


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_resolver_finds_common_repo_venv_from_linked_worktree(tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path)
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "--detach", "-q", str(linked), "HEAD")
    expected = repo / ".venv" / "Scripts" / "python.exe"
    expected.parent.mkdir(parents=True)
    expected.write_text("fixture\n", encoding="utf-8")
    resolver = REPO_ROOT / "scripts" / "resolve-python.ps1"
    command = (
        f". '{resolver}'; "
        f"Resolve-ProbOSPython -RepoRoot '{linked}'"
    )
    env = os.environ.copy()
    env.pop("PROBOS_PYTHON", None)

    completed = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert Path(completed.stdout.strip()) == expected.resolve()


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_resolver_rejects_invalid_explicit_interpreter(tmp_path: Path) -> None:
    resolver = REPO_ROOT / "scripts" / "resolve-python.ps1"
    command = (
        f". '{resolver}'; Resolve-ProbOSPython -RepoRoot '{tmp_path}'"
    )
    env = os.environ.copy()
    env["PROBOS_PYTHON"] = str(tmp_path / "missing-python")

    completed = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )

    assert completed.returncode != 0
    assert "PROBOS_PYTHON does not name an existing file" in completed.stderr


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
@pytest.mark.parametrize(
    "helper_body",
    ["raise SystemExit(7)\n", "print('not-json')\n"],
)
def test_phantom_wrapper_fails_closed_when_helper_fails(
    tmp_path: Path, helper_body: str
) -> None:
    repo = tmp_path / "phantom-repo"
    scripts = repo / "scripts"
    (repo / "src" / "probos").mkdir(parents=True)
    scripts.mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "phantom-api-precheck.ps1", scripts)
    shutil.copy2(REPO_ROOT / "scripts" / "resolve-python.ps1", scripts)
    (scripts / "phantom_api_ast_helper.py").write_text(
        helper_body, encoding="utf-8"
    )
    prompt = repo / "prompt.md"
    prompt.write_text("```python\nruntime.foo()\n```\n", encoding="utf-8")
    env = os.environ.copy()
    env["PROBOS_PYTHON"] = sys.executable

    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(scripts / "phantom-api-precheck.ps1"),
            str(prompt),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )

    assert completed.returncode == 2, completed.stdout + completed.stderr
    assert "AST helper failed" in completed.stderr


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_phantom_wrapper_missing_requested_prompt_is_operational_failure(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing-prompt.md"

    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "phantom-api-precheck.ps1"),
            str(missing),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 2
    assert "Prompt path(s) not found" in completed.stderr


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell.exe") is None,
    reason="Windows PowerShell unavailable",
)
def test_phantom_wrapper_rejects_windows_powershell_5(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("# prompt\n", encoding="utf-8")

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "phantom-api-precheck.ps1"),
            str(prompt),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 2
    assert "requires PowerShell 7" in completed.stderr


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AD-1295 / BF-687", "ad-1295-bf-687"),
        ("  ", "gate"),
        ("x" * 80, "x" * 48),
    ],
)
def test_slugify_label_is_stable_and_bounded(
    gate: ModuleType, raw: str, expected: str
) -> None:
    assert gate._slugify_label(raw) == expected


def test_extract_summary_returns_last_completed_pytest_summary(gate: ModuleType) -> None:
    log = "1 failed, 4 passed in 2.00s\nnoise\n10 passed, 2 skipped in 3.25s\n"

    assert gate._extract_summary(log) == "10 passed, 2 skipped in 3.25s"


def test_parse_junit_requires_executed_tests_and_returns_totals(
    gate: ModuleType, tmp_path: Path
) -> None:
    junit = tmp_path / "result.xml"
    junit.write_text(
        '<testsuites><testsuite tests="3" failures="0" errors="0" '
        'skipped="1" time="1.25"><testcase name="one" />'
        '<testcase name="two"><skipped /></testcase>'
        '<testcase name="three" /></testsuite></testsuites>',
        encoding="utf-8",
    )

    totals = gate._parse_junit(junit)

    assert totals == gate.JUnitTotals(
        tests=3, failures=0, errors=0, skipped=1, time_seconds=1.25
    )

    junit.write_text(
        '<testsuites><testsuite tests="0" failures="0" errors="0" /></testsuites>',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="zero executed tests"):
        gate._parse_junit(junit)

    junit.write_text(
        '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="2">'
        '<testcase name="one"><skipped /></testcase>'
        '<testcase name="two"><skipped /></testcase>'
        '</testsuite></testsuites>',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="zero executed tests"):
        gate._parse_junit(junit)

    junit.write_text(
        '<testsuites><testsuite tests="2" failures="1" errors="1" '
        'skipped="1"><testcase name="one"><failure /></testcase>'
        '<testcase name="two"><error /></testcase></testsuite></testsuites>',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="categories exceed"):
        gate._parse_junit(junit)

    junit.write_text(
        '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0">'
        '<testcase name="only" /></testsuite></testsuites>',
        encoding="utf-8",
    )
    assert gate._parse_junit(junit) == gate.JUnitTotals(
        tests=1,
        failures=0,
        errors=0,
        skipped=0,
        time_seconds=0.0,
        extra_reports=1,
    )

    junit.write_text(
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase name="one" /><testcase name="two" />'
        '</testsuite></testsuites>',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="declared 1 tests but contains 2"):
        gate._parse_junit(junit)


def test_parse_junit_accepts_report_emitted_by_pytest(
    gate: ModuleType, tmp_path: Path
) -> None:
    test_file = tmp_path / "test_sample.py"
    test_file.write_text(
        "import pytest\n\n"
        "def test_passes():\n    assert True\n\n"
        "def test_skips():\n    pytest.skip('fixture')\n",
        encoding="utf-8",
    )
    junit = tmp_path / "pytest.xml"

    completed = subprocess.run(
        [
            sys.executable,
            "-P",
            "-m",
            "pytest",
            str(test_file),
            "-q",
            "-n",
            "0",
            "-p",
            "no:randomly",
            f"--junitxml={junit}",
        ],
        cwd=tmp_path,
        env=gate._subprocess_env(tmp_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert gate._parse_junit(junit) == gate.JUnitTotals(
        tests=2,
        failures=0,
        errors=0,
        skipped=1,
        time_seconds=pytest.approx(0.0, abs=1.0),
    )


def test_artifact_paths_are_unique_for_same_second_and_head(
    gate: ModuleType, tmp_path: Path
) -> None:
    first = gate._artifact_paths(tmp_path, label="same", head="abc123")
    second = gate._artifact_paths(tmp_path, label="same", head="abc123")

    assert set(first).isdisjoint(second)


def test_preflight_import_origin_resolves_selected_worktree(
    gate: ModuleType, tmp_path: Path
) -> None:
    repo = _make_gate_repo(tmp_path)
    import_origin = gate._preflight_specs(repo)[0]

    completed = subprocess.run(
        import_origin.command,
        cwd=repo,
        env=gate._subprocess_env(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert str((repo / "src" / "probos" / "__init__.py").resolve()) in completed.stdout


def test_main_preflight_failure_starts_no_full_gate_and_records_phase(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [
            gate.PhaseSpec(
                "failing-preflight",
                [sys.executable, "-c", "import sys; sys.exit(7)"],
            )
        ],
    )

    exit_code = gate.main(["--repo-root", str(repo), "--label", "preflight-red"])
    manifest = _only_manifest(repo)

    assert exit_code == 7
    assert manifest["wrapper_exit_code"] == 7
    assert manifest["preflight_exit_code"] == 7
    assert manifest["pytest_exit_code"] is None
    assert manifest["command"] is None
    assert manifest["phases"][0]["name"] == "failing-preflight"


def test_main_records_preflight_infrastructure_failure_truthfully(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [gate.PhaseSpec("infra-preflight", ["missing-command"])],
    )

    def fail_to_start(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError("process creation failed")

    monkeypatch.setattr(gate, "_run_streaming_command", fail_to_start)

    exit_code = gate.main(
        ["--repo-root", str(repo), "--preflight-only", "--label", "infra-red"]
    )
    manifest = _only_manifest(repo)

    assert exit_code == 5
    assert manifest["wrapper_exit_code"] == 5
    assert manifest["preflight_exit_code"] == 5
    assert manifest["pytest_exit_code"] is None
    assert manifest["phases"][0]["exit_code"] == 5
    assert manifest["error"] == "process creation failed"


def test_main_records_distinct_pytest_failure_and_summary(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [
            gate.PhaseSpec("preflight", [sys.executable, "-c", "print('ok')"])
        ],
    )
    monkeypatch.setattr(
        gate,
        "_build_full_command",
        lambda **_kwargs: [
            sys.executable,
            "-c",
            "import sys; print('1 failed, 1 passed in 0.01s'); sys.exit(9)",
        ],
    )

    exit_code = gate.main(["--repo-root", str(repo), "--label", "pytest-red"])
    manifest = _only_manifest(repo)

    assert exit_code == 9
    assert manifest["wrapper_exit_code"] == 9
    assert manifest["preflight_exit_code"] == 0
    assert manifest["pytest_exit_code"] == 9
    assert manifest["summary"] == "1 failed, 1 passed in 0.01s"
    assert manifest["tree_changed"] is False


def test_main_refuses_false_green_without_junit(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only")
    monkeypatch.setenv("PYTEST_PLUGINS", "hostile_plugin")
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [gate.PhaseSpec("preflight", [sys.executable, "-c", "pass"])],
    )
    monkeypatch.setattr(
        gate,
        "_build_full_command",
        lambda **_kwargs: [sys.executable, "-c", "print('1 passed in 0.01s')"],
    )

    exit_code = gate.main(["--repo-root", str(repo), "--label", "no-junit"])
    manifest = _only_manifest(repo)

    assert exit_code == 5
    assert manifest["pytest_exit_code"] == 0
    assert manifest["junit_totals"] is None
    assert "without creating" in manifest["error"]
    assert {
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
    } <= set(manifest["sanitized_pytest_environment"])


def test_main_accepts_green_only_with_valid_nonempty_junit(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [gate.PhaseSpec("preflight", [sys.executable, "-c", "pass"])],
    )

    def full_command(**kwargs: object) -> list[str]:
        junit = Path(str(kwargs["junit_path"]))
        code = (
            "from pathlib import Path; "
            f"Path({str(junit)!r}).write_text("
            "'<testsuites><testsuite tests=\"2\" failures=\"0\" errors=\"0\" "
            "skipped=\"1\" time=\"0.02\"><testcase name=\"one\" />"
            "<testcase name=\"two\"><skipped /></testcase>"
            "</testsuite></testsuites>'); "
            "print('1 passed, 1 skipped in 0.02s')"
        )
        return [sys.executable, "-c", code]

    monkeypatch.setattr(gate, "_build_full_command", full_command)

    def collection_validation(
        _directory: Path,
        artifact: Path,
        **_kwargs: object,
    ) -> object:
        artifact.write_text("{}\n", encoding="utf-8")
        return gate.CollectionTotals(nodes=2, workers=16, sha256="fixture")

    monkeypatch.setattr(
        gate, "_validate_collection_manifests", collection_validation
    )

    exit_code = gate.main(["--repo-root", str(repo), "--label", "green-junit"])
    manifest = _only_manifest(repo)

    assert exit_code == 0
    assert manifest["pytest_exit_code"] == 0
    assert manifest["junit_totals"] == {
        "errors": 0,
        "extra_reports": 0,
        "failures": 0,
        "skipped": 1,
        "tests": 2,
        "time_seconds": 0.02,
    }


def test_main_repository_addopts_cannot_deselect_failure(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    (repo / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = "-k selected"\n',
        encoding="utf-8",
    )
    (repo / "tests" / "test_selection.py").write_text(
        "def test_selected():\n    assert True\n\n"
        "def test_must_fail():\n    assert False, 'must execute'\n",
        encoding="utf-8",
    )
    _git(repo, "add", "pyproject.toml", "tests/test_selection.py")
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "selection exploit",
    )
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [gate.PhaseSpec("preflight", [sys.executable, "-c", "pass"])],
    )

    exit_code = gate.main(
        ["--repo-root", str(repo), "--workers", "1", "--label", "addopts"]
    )
    manifest = _only_manifest(repo)

    assert exit_code == 1
    assert manifest["pytest_exit_code"] == 1
    assert manifest["junit_totals"]["tests"] == 2
    assert manifest["junit_totals"]["failures"] == 1


@pytest.mark.parametrize(
    ("config_line", "test_files"),
    [
        (
            'python_files = ["test_selected.py"]',
            {
                "tests/test_selected.py": "def test_passes():\n    assert True\n",
                "tests/test_hidden.py": "def test_fails():\n    assert False\n",
            },
        ),
        (
            'python_classes = ["TestSelected"]',
            {
                "tests/test_classes.py": (
                    "class TestSelected:\n"
                    "    def test_passes(self):\n        assert True\n\n"
                    "class TestHidden:\n"
                    "    def test_fails(self):\n        assert False\n"
                )
            },
        ),
        (
            'python_functions = ["test_selected"]',
            {
                "tests/test_functions.py": (
                    "def test_selected():\n    assert True\n\n"
                    "def test_hidden():\n    assert False\n"
                )
            },
        ),
        (
            'norecursedirs = ["hidden"]',
            {
                "tests/test_visible.py": "def test_passes():\n    assert True\n",
                "tests/hidden/test_hidden.py": "def test_fails():\n    assert False\n",
            },
        ),
    ],
)
def test_main_repository_collection_selectors_cannot_hide_failures(
    gate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_line: str,
    test_files: dict[str, str],
) -> None:
    repo = _make_gate_repo(tmp_path)
    (repo / "pyproject.toml").write_text(
        f"[tool.pytest.ini_options]\n{config_line}\n", encoding="utf-8"
    )
    for relative, content in test_files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "pyproject.toml", *test_files)
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "collection selector exploit",
    )
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [gate.PhaseSpec("preflight", [sys.executable, "-c", "pass"])],
    )

    exit_code = gate.main(
        ["--repo-root", str(repo), "--workers", "1", "--label", "selectors"]
    )
    manifest = _only_manifest(repo)

    assert exit_code == 1
    assert manifest["pytest_exit_code"] == 1
    assert manifest["junit_totals"]["tests"] == 2
    assert manifest["junit_totals"]["failures"] == 1


def test_main_collection_hook_cannot_remove_one_failing_node(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    (repo / "tests" / "conftest.py").write_text(
        "def pytest_collection_modifyitems(items):\n"
        "    items[:] = [item for item in items if item.name != 'test_hidden_failure']\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_nodes.py").write_text(
        "def test_visible_pass():\n    assert True\n\n"
        "def test_hidden_failure():\n    assert False\n",
        encoding="utf-8",
    )
    _git(repo, "add", "tests/conftest.py", "tests/test_nodes.py")
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "node deselection exploit",
    )
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [gate.PhaseSpec("preflight", [sys.executable, "-c", "pass"])],
    )
    receipt = repo / "logs" / "gates" / "nodes.receipt.json"

    exit_code = gate.main(
        [
            "--repo-root",
            str(repo),
            "--workers",
            "1",
            "--label",
            "node-deselection",
            "--receipt",
            str(receipt),
        ]
    )
    manifest = _only_manifest(repo)

    assert exit_code != 0
    assert "canonical gate forbids collection item changes" in manifest["error"]
    assert "test_hidden_failure" in manifest["error"]
    assert not receipt.exists()


def test_release_census_matches_default_ablation_collection_policy(
    gate: ModuleType,
) -> None:
    census = gate._tracked_test_census(REPO_ROOT)

    assert gate._RELEASE_TEST_FILE_EXCLUSIONS == {
        "tests/ablation/test_sigma_ablation.py",
        "tests/ablation/test_sigma_harness_structural.py",
    }
    assert gate._RELEASE_TEST_FILE_EXCLUSIONS.isdisjoint(census)
    assert all((REPO_ROOT / path).is_file() for path in gate._RELEASE_TEST_FILE_EXCLUSIONS)
    env = os.environ.copy()
    env.pop("PROBOS_ABLATION", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            "tests/ablation",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 5
    assert "test_sigma_ablation" not in completed.stdout
    assert "test_sigma_harness_structural" not in completed.stdout


def test_main_rejects_junit_omitting_tracked_test_file_census(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    for name in ("test_one.py", "test_two.py"):
        (repo / "tests" / name).write_text(
            f"def {name.removesuffix('.py')}():\n    assert True\n",
            encoding="utf-8",
        )
    _git(repo, "add", "tests/test_one.py", "tests/test_two.py")
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "census fixture",
    )
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [gate.PhaseSpec("preflight", [sys.executable, "-c", "pass"])],
    )

    def incomplete_command(**kwargs: object) -> list[str]:
        junit = Path(str(kwargs["junit_path"]))
        xml = (
            '<testsuites><testsuite tests="1" failures="0" errors="0" '
            'skipped="0"><testcase name="test_one" file="tests/test_one.py" />'
            "</testsuite></testsuites>"
        )
        return [
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(junit)!r}).write_text({xml!r})",
        ]

    monkeypatch.setattr(gate, "_build_full_command", incomplete_command)

    exit_code = gate.main(["--repo-root", str(repo), "--label", "census"])
    manifest = _only_manifest(repo)

    assert exit_code == 5
    assert "tests/test_two.py" in manifest["error"]


def test_main_rejects_junit_outcome_counter_contradiction(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [gate.PhaseSpec("preflight", [sys.executable, "-c", "pass"])],
    )

    def contradictory_command(**kwargs: object) -> list[str]:
        junit = Path(str(kwargs["junit_path"]))
        xml = (
            '<testsuites><testsuite tests="1" failures="0" errors="0" '
            'skipped="0"><testcase name="forged"><failure /></testcase>'
            "</testsuite></testsuites>"
        )
        return [
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(junit)!r}).write_text({xml!r})",
        ]

    monkeypatch.setattr(gate, "_build_full_command", contradictory_command)

    exit_code = gate.main(["--repo-root", str(repo), "--label", "contradiction"])
    manifest = _only_manifest(repo)

    assert exit_code == 5
    assert "outcome counters disagree" in manifest["error"]


def test_main_selected_source_cannot_impersonate_pytest(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    (repo / "src" / "pytest.py").write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "junit = next(value.split('=', 1)[1] for value in sys.argv "
        "if value.startswith('--junitxml='))\n"
        "Path(junit).write_text('<testsuites><testsuite tests=\"1\" failures=\"0\" "
        "errors=\"0\" skipped=\"0\"><testcase name=\"forged\" />"
        "</testsuite></testsuites>')\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_failure.py").write_text(
        "def test_must_fail():\n    assert False, 'real pytest ran'\n",
        encoding="utf-8",
    )
    _git(repo, "add", "src/pytest.py", "tests/test_failure.py")
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "runner shadow exploit",
    )
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [gate.PhaseSpec("preflight", [sys.executable, "-c", "pass"])],
    )

    exit_code = gate.main(
        ["--repo-root", str(repo), "--workers", "1", "--label", "runner-origin"]
    )
    manifest = _only_manifest(repo)

    assert exit_code == 1
    assert manifest["pytest_exit_code"] == 1
    assert manifest["junit_totals"]["tests"] == 1
    assert manifest["junit_totals"]["failures"] == 1


def test_main_materializes_staged_tree_before_source_mutate_restore(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    tracked = repo / "tracked.txt"
    tracked.write_text("staged\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    marker = tmp_path / "source-mutated.txt"
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    mutation = (
        "from pathlib import Path; "
        f"path=Path({str(tracked)!r}); original=path.read_bytes(); "
        "path.write_text('transient\\n'); "
        f"Path({str(marker)!r}).write_text('observed'); "
        "path.write_bytes(original)"
    )
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [
            gate.PhaseSpec(
                "materialized-staged-tree",
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; "
                    "assert Path('tracked.txt').read_text() == 'staged\\n'; "
                    + mutation,
                ],
            )
        ],
    )

    exit_code = gate.main(
        [
            "--repo-root",
            str(repo),
            "--preflight-only",
            "--label",
            "materialized",
        ]
    )
    manifest = _only_manifest(repo)

    assert marker.read_text() == "observed"
    assert tracked.read_text() == "staged\n"
    assert exit_code == 0
    assert manifest["tree_changed"] is False


def test_main_full_gate_rejects_staged_tree_that_push_would_not_send(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    (repo / "tests" / "test_staged.py").write_text(
        "def test_only_in_index():\n    assert True\n", encoding="utf-8"
    )
    _git(repo, "add", "tests/test_staged.py")
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])

    receipt = repo / "logs" / "gates" / "staged.receipt.json"
    exit_code = gate.main(
        [
            "--repo-root",
            str(repo),
            "--label",
            "staged-release",
            "--receipt",
            str(receipt),
        ]
    )
    manifest = _only_manifest(repo)

    assert exit_code == 2
    assert manifest["preflight_exit_code"] is None
    assert manifest["pytest_exit_code"] is None
    assert "requires a committed tree" in manifest["error"]
    assert not receipt.exists()


def test_main_success_receipt_binds_committed_tree_manifest_and_junit(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    (repo / "tests" / "test_receipt.py").write_text(
        "def test_receipt():\n    assert True\n", encoding="utf-8"
    )
    _git(repo, "add", "tests/test_receipt.py")
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "receipt fixture",
    )
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [gate.PhaseSpec("preflight", [sys.executable, "-c", "pass"])],
    )
    receipt_path = repo / "logs" / "gates" / "caller.receipt.json"

    exit_code = gate.main(
        [
            "--repo-root",
            str(repo),
            "--workers",
            "1",
            "--label",
            "receipt",
            "--receipt",
            str(receipt_path),
        ]
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    manifest_path = repo / receipt["manifest"]["path"]
    junit_path = repo / receipt["junit"]["path"]
    collection_path = repo / receipt["collection"]["path"]

    assert exit_code == 0
    assert receipt["schema_version"] == 1
    assert receipt["status"] == {
        "preflight_exit_code": 0,
        "preflight_only": False,
        "pytest_exit_code": 0,
        "tree_changed": False,
        "wrapper_exit_code": 0,
    }
    assert receipt["tree"]["head"] == subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    assert receipt["tree"]["head_tree"] == receipt["tree"]["index_tree"]
    assert receipt["manifest"]["sha256"] == gate._sha256_file(manifest_path)
    assert receipt["junit"]["sha256"] == gate._sha256_file(junit_path)
    assert receipt["junit"]["totals"]["tests"] == 1
    assert receipt["junit"]["totals"]["failures"] == 0
    assert receipt["junit"]["totals"]["errors"] == 0
    assert receipt["collection"]["sha256"] == gate._sha256_file(collection_path)
    assert receipt["collection"]["totals"]["nodes"] == 1
    assert receipt["collection"]["totals"]["workers"] == 1


def test_materialized_gate_tree_retries_and_verifies_cleanup(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    expected = gate._snapshot_tree(repo)
    real_run = subprocess.run
    remove_calls = 0

    def flaky_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        nonlocal remove_calls
        command = args[0]
        if isinstance(command, list) and command[:3] == ["git", "worktree", "remove"]:
            remove_calls += 1
            if remove_calls == 1:
                return subprocess.CompletedProcess(
                    command, 1, stdout="", stderr="injected cleanup failure"
                )
        return real_run(*args, **kwargs)

    monkeypatch.setattr(gate.subprocess, "run", flaky_run)

    with gate._materialized_gate_tree(repo, expected) as materialized:
        materialized_path = materialized
        assert materialized.is_dir()

    assert remove_calls == 2
    assert not materialized_path.exists()
    listing = subprocess.check_output(
        ["git", "worktree", "list", "--porcelain"], cwd=repo, text=True
    )
    assert str(materialized_path) not in listing


def test_materialized_gate_tree_attaches_cleanup_failure_to_primary_error(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    expected = gate._snapshot_tree(repo)
    real_remove = gate._remove_materialized_gate_tree

    def cleanup_then_report(repo_root: Path, gate_root: Path) -> str:
        assert real_remove(repo_root, gate_root) is None
        return "injected cleanup failure"

    monkeypatch.setattr(gate, "_remove_materialized_gate_tree", cleanup_then_report)

    with pytest.raises(ValueError, match="primary") as raised:
        with gate._materialized_gate_tree(repo, expected):
            raise ValueError("primary")

    assert raised.value.__notes__ == [
        "Unable to remove materialized gate tree: injected cleanup failure"
    ]
    assert "injected cleanup failure" in gate._exception_text(raised.value)


def test_main_invalidates_persistent_source_change_outside_materialized_tree(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    tracked = repo / "tracked.txt"
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    mutation = (
        "from pathlib import Path; "
        f"Path({str(tracked)!r}).write_text('persistent\\n')"
    )
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [gate.PhaseSpec("source-mutation", [sys.executable, "-c", mutation])],
    )

    exit_code = gate.main(
        ["--repo-root", str(repo), "--preflight-only", "--label", "source-change"]
    )
    manifest = _only_manifest(repo)

    assert exit_code == 3
    assert manifest["tree_changed"] is True


def test_main_invalidates_gate_when_preflight_changes_tracked_tree(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [
            gate.PhaseSpec(
                "mutating-preflight",
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('tracked.txt').write_text('changed\\n')",
                ],
            )
        ],
    )
    full_command_calls: list[dict[str, object]] = []

    def full_command(**kwargs: object) -> list[str]:
        full_command_calls.append(kwargs)
        return [sys.executable, "-c", "raise AssertionError('must not run')"]

    monkeypatch.setattr(gate, "_build_full_command", full_command)

    exit_code = gate.main(["--repo-root", str(repo), "--label", "tree-change"])
    manifest = _only_manifest(repo)

    assert exit_code == 3
    assert manifest["preflight_exit_code"] == 0
    assert manifest["pytest_exit_code"] is None
    assert manifest["command"] is None
    assert manifest["tree_changed"] is True
    assert full_command_calls == []


def test_main_records_interruption_as_non_success(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_gate_repo(tmp_path)
    monkeypatch.setattr(gate, "_running_pytest_processes", lambda: [])
    monkeypatch.setattr(
        gate,
        "_preflight_specs",
        lambda _root: [
            gate.PhaseSpec("interrupt", [sys.executable, "-c", "print('unused')"])
        ],
    )

    def interrupt(*_args: object, **_kwargs: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(gate, "_run_streaming_command", interrupt)

    exit_code = gate.main(
        ["--repo-root", str(repo), "--preflight-only", "--label", "interrupted"]
    )
    manifest = _only_manifest(repo)

    assert exit_code == 130
    assert manifest["wrapper_exit_code"] == 130
    assert manifest["preflight_exit_code"] == 130
    assert manifest["interrupted"] is True
    assert manifest["error"] == "Interrupted"
    assert manifest["phases"][0]["exit_code"] == 130


def _process_exists(process_id: int) -> bool:
    if os.name == "nt":
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"if (Get-Process -Id {process_id} -ErrorAction SilentlyContinue) {{ exit 0 }} else {{ exit 1 }}",
            ],
            check=False,
            capture_output=True,
        )
        return completed.returncode == 0
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    return True


def test_terminate_process_tree_reaps_child_and_grandchild(
    gate: ModuleType, tmp_path: Path
) -> None:
    pid_file = tmp_path / "pids.txt"
    child_code = "import time; time.sleep(60)"
    parent_code = (
        "from pathlib import Path; import os, subprocess, sys, time; "
        f"child=subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        f"Path({str(pid_file)!r}).write_text(f'{{os.getpid()}},{{child.pid}}'); "
        "print('ready', flush=True); time.sleep(60)"
    )
    kwargs: dict[str, object] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen([sys.executable, "-c", parent_code], **kwargs)
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"
        parent_id, child_id = [int(value) for value in pid_file.read_text().split(",")]

        gate._terminate_process_tree(process)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and (
            _process_exists(parent_id) or _process_exists(child_id)
        ):
            time.sleep(0.05)
        assert not _process_exists(parent_id)
        assert not _process_exists(child_id)
    finally:
        if process.poll() is None:
            gate._terminate_process_tree(process)


def test_streaming_supervisor_kills_resistant_orphan_after_leader_exits(
    gate: ModuleType, tmp_path: Path
) -> None:
    pid_file = tmp_path / "orphan-pid.txt"
    orphan_code = (
        "import signal,time; "
        "signal.signal(signal.SIGTERM, lambda *_: None); "
        "time.sleep(60)"
    )
    leader_code = (
        "from pathlib import Path; import subprocess,sys; "
        f"child=subprocess.Popen([sys.executable, '-c', {orphan_code!r}]); "
        f"Path({str(pid_file)!r}).write_text(str(child.pid)); "
        "print('leader-exit', flush=True)"
    )
    log = io.StringIO()

    started = time.monotonic()
    exit_code = gate._run_streaming_command(
        [sys.executable, "-c", leader_code],
        cwd=tmp_path,
        log=log,
        env=os.environ.copy(),
    )
    elapsed = time.monotonic() - started
    orphan_pid = int(pid_file.read_text())

    assert exit_code == 0
    assert elapsed < 5
    assert "leader-exit" in log.getvalue()
    assert not _process_exists(orphan_pid)


def test_supervisor_parent_death_terminates_child(tmp_path: Path) -> None:
    pid_file = tmp_path / "liveness-child.txt"
    supervisor_pid_file = tmp_path / "supervisor-pid.txt"
    child_code = (
        "from pathlib import Path; import os,time; "
        f"Path({str(pid_file)!r}).write_text(str(os.getpid())); "
        "time.sleep(60)"
    )
    supervisor = REPO_ROOT / "scripts" / "_gate_process_supervisor.py"
    parent_code = (
        "from pathlib import Path\n"
        "import os, subprocess, sys, time\n"
        "process = subprocess.Popen(\n"
        "    [sys.executable, "
        f"{str(supervisor)!r}, '--parent-pid', str(os.getpid()), '--', "
        f"sys.executable, '-c', {child_code!r}],\n"
        "    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL,\n"
        ")\n"
        f"Path({str(supervisor_pid_file)!r}).write_text(str(process.pid))\n"
        "process.stdin.write(b'G')\n"
        "process.stdin.close()\n"
        f"target = Path({str(pid_file)!r})\n"
        "for _ in range(100):\n"
        "    if target.exists():\n"
        "        break\n"
        "    time.sleep(0.05)\n"
        "os._exit(0)\n"
    )
    parent = subprocess.Popen([sys.executable, "-c", parent_code])
    try:
        parent.wait(timeout=10)
        deadline = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pid_file.exists(), "the supervised child never started"
        child_pid = int(pid_file.read_text())
        supervisor_pid = int(supervisor_pid_file.read_text())

        deadline = time.monotonic() + 5
        while (
            _process_exists(child_pid) or _process_exists(supervisor_pid)
        ) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _process_exists(child_pid)
        assert not _process_exists(supervisor_pid)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()


def test_wrapper_hard_death_cleans_command_worktree_registration_and_lock(
    gate: ModuleType, tmp_path: Path
) -> None:
    repo = _make_gate_repo(tmp_path)
    phase_pid_file = tmp_path / "hard-death-phase-pid.txt"
    (repo / "scripts" / "gen_config_reference.py").write_text(
        "from pathlib import Path\n"
        "import os, time\n"
        f"Path({str(phase_pid_file)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    (repo / "scripts" / "gen_ad_ledger.py").write_text(
        "raise SystemExit(0)\n", encoding="utf-8"
    )
    _git(
        repo,
        "add",
        "scripts/gen_config_reference.py",
        "scripts/gen_ad_ledger.py",
    )
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "hard death fixture",
    )
    wrapper_code = (
        "import importlib.util, sys\n"
        f"spec=importlib.util.spec_from_file_location('hard_death_gate', {str(SCRIPT)!r})\n"
        "module=importlib.util.module_from_spec(spec)\n"
        "sys.modules[spec.name]=module\n"
        "spec.loader.exec_module(module)\n"
        "module._running_pytest_processes=lambda: []\n"
        f"raise SystemExit(module.main(['--repo-root', {str(repo)!r}, "
        "'--preflight-only', '--label', 'hard-death']))\n"
    )
    wrapper = subprocess.Popen(
        [sys.executable, "-c", wrapper_code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    gate_root: Path | None = None
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            listing = subprocess.check_output(
                ["git", "worktree", "list", "--porcelain"],
                cwd=repo,
                text=True,
            )
            worktrees = [
                Path(line.removeprefix("worktree "))
                for line in listing.splitlines()
                if line.startswith("worktree ")
                and ".probos-gate-" in line
            ]
            if phase_pid_file.exists() and worktrees:
                gate_root = worktrees[0]
                break
            time.sleep(0.05)
        assert gate_root is not None, "wrapper never entered its materialized preflight"
        phase_pid = int(phase_pid_file.read_text())

        wrapper.kill()
        wrapper.wait(timeout=10)

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            listing = subprocess.check_output(
                ["git", "worktree", "list", "--porcelain"],
                cwd=repo,
                text=True,
            )
            if (
                not _process_exists(phase_pid)
                and not gate_root.exists()
                and str(gate_root) not in listing
            ):
                break
            time.sleep(0.1)
        assert not _process_exists(phase_pid)
        assert not gate_root.exists()
        assert str(gate_root) not in listing
        with gate.GateLock(gate._gate_lock_path(repo)):
            pass
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
            wrapper.wait()
        if gate_root is not None and gate_root.exists():
            gate._remove_materialized_gate_tree(repo, gate_root)


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal semantics only")
def test_supervisor_posix_signal_terminates_command_and_descendant(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "signal-pids.txt"
    descendant_code = "import time; time.sleep(60)"
    command_code = (
        "from pathlib import Path; import os,subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable, '-c', {descendant_code!r}]); "
        f"Path({str(pid_file)!r}).write_text(f'{{os.getpid()}},{{child.pid}}'); "
        "time.sleep(60)"
    )
    supervisor = REPO_ROOT / "scripts" / "_gate_process_supervisor.py"
    process = subprocess.Popen(
        [
            sys.executable,
            str(supervisor),
            "--parent-pid",
            str(os.getpid()),
            "--",
            sys.executable,
            "-c",
            command_code,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        assert process.stdin is not None
        process.stdin.write(b"G")
        process.stdin.close()
        deadline = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pid_file.exists(), "the supervised POSIX process tree never started"
        command_pid, descendant_pid = [
            int(value) for value in pid_file.read_text().split(",")
        ]

        os.kill(process.pid, signal.SIGTERM)
        assert process.wait(timeout=10) == 128 + signal.SIGTERM

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and (
            _process_exists(command_pid) or _process_exists(descendant_pid)
        ):
            time.sleep(0.05)
        assert not _process_exists(command_pid)
        assert not _process_exists(descendant_pid)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
@pytest.mark.parametrize("gate_exit", [0, 7])
def test_wave_orchestrator_verify_propagates_canonical_gate_exit(
    tmp_path: Path, gate_exit: int
) -> None:
    repo = tmp_path / f"orchestrator-{gate_exit}"
    scripts = repo / "scripts"
    prompts = repo / "prompts"
    scripts.mkdir(parents=True)
    prompts.mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "wave-orchestrator.ps1", scripts)
    shutil.copy2(REPO_ROOT / "scripts" / "resolve-python.ps1", scripts)
    (scripts / "run_test_gate.py").write_text(
        _gate_stub_source(gate_exit),
        encoding="utf-8",
    )
    (prompts / "wave-plan.yaml").write_text(
        "waves:\n  - id: test-wave\n    kind: main\n    status: pending\n",
        encoding="utf-8",
    )
    (prompts / "wave-orchestrator-state.json").write_text(
        json.dumps(
            {
                "current_wave": "test-wave",
                "current_stage": "verify_build",
                "history": [],
                "verify_build_receipt": {
                    "wave_id": "stale-wave",
                    "tree": {
                        "head": "stale",
                        "index_tree": "stale",
                        "status_sha256": "stale",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text(
        "/logs/\n/prompts/wave-orchestrator-state.json\n/scripts/gate-args.txt\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "fixture",
    )

    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env["PROBOS_PYTHON"] = sys.executable
    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(scripts / "wave-orchestrator.ps1"),
            "verify",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )

    assert completed.returncode == gate_exit, completed.stdout + completed.stderr
    gate_arguments = (scripts / "gate-args.txt").read_text(encoding="utf-8")
    assert gate_arguments.startswith("--label wave-test-wave --receipt ")
    assert Path(gate_arguments.split("--receipt ", 1)[1]).is_file() == (
        gate_exit == 0
    )
    state = json.loads(
        (prompts / "wave-orchestrator-state.json").read_text(encoding="utf-8-sig")
    )
    if gate_exit == 0:
        assert state["verify_build_receipt"]["wave_id"] == "test-wave"
        completed = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(scripts / "wave-orchestrator.ps1"),
                "advance",
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            env=env,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        state = json.loads(
            (prompts / "wave-orchestrator-state.json").read_text(
                encoding="utf-8-sig"
            )
        )
        assert state["current_stage"] == "gate_2"
    else:
        assert "verify_build_receipt" not in state


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_wave_orchestrator_rejects_zero_exit_without_gate_artifacts(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "orchestrator-no-artifacts"
    scripts = repo / "scripts"
    prompts = repo / "prompts"
    scripts.mkdir(parents=True)
    prompts.mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "wave-orchestrator.ps1", scripts)
    shutil.copy2(REPO_ROOT / "scripts" / "resolve-python.ps1", scripts)
    (scripts / "run_test_gate.py").write_text(
        "raise SystemExit(0)\n", encoding="utf-8"
    )
    (prompts / "wave-plan.yaml").write_text(
        "waves:\n  - id: test-wave\n    kind: main\n    status: pending\n",
        encoding="utf-8",
    )
    (prompts / "wave-orchestrator-state.json").write_text(
        json.dumps(
            {
                "current_wave": "test-wave",
                "current_stage": "verify_build",
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text(
        "/logs/\n/prompts/wave-orchestrator-state.json\n", encoding="utf-8"
    )
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "fixture",
    )
    env = os.environ.copy()
    env["PROBOS_PYTHON"] = sys.executable

    completed = _run_orchestrator(repo, env, "verify")
    state = json.loads(
        (prompts / "wave-orchestrator-state.json").read_text(encoding="utf-8-sig")
    )

    assert completed.returncode == 5
    assert "did not create" in completed.stderr.lower()
    assert "verify_build_receipt" not in state


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_wave_orchestrator_rejects_staged_index_before_full_gate(
    tmp_path: Path,
) -> None:
    repo, _remote, env = _make_push_orchestrator_repo(tmp_path)
    (repo / "staged.txt").write_text("not committed\n", encoding="utf-8")
    _git(repo, "add", "staged.txt")

    completed = _run_orchestrator(repo, env, "verify")
    state = json.loads(
        (repo / "prompts" / "wave-orchestrator-state.json").read_text(
            encoding="utf-8-sig"
        )
    )

    assert completed.returncode == 2
    assert "index to equal the committed head tree" in completed.stderr.lower()
    assert "verify_build_receipt" not in state
    assert not (repo / "scripts" / "gate-args.txt").exists()


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_wave_orchestrator_rejects_tampered_gate_artifact_before_advance(
    tmp_path: Path,
) -> None:
    repo, _remote, env = _make_push_orchestrator_repo(tmp_path)
    assert _run_orchestrator(repo, env, "verify").returncode == 0
    state_path = repo / "prompts" / "wave-orchestrator-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    receipt_path = repo / state["verify_build_receipt"]["artifact"]["path"]
    receipt_path.write_text("{}\n", encoding="utf-8")

    completed = _run_orchestrator(repo, env, "advance")

    assert completed.returncode == 2
    assert "artifact hash changed" in completed.stderr.lower()
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    assert state["current_stage"] == "verify_build"


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_wave_orchestrator_rejects_inconsistent_junit_extra_reports(
    tmp_path: Path,
) -> None:
    repo, _remote, env = _make_push_orchestrator_repo(tmp_path)
    assert _run_orchestrator(repo, env, "verify").returncode == 0
    state_path = repo / "prompts" / "wave-orchestrator-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    receipt_path = repo / state["verify_build_receipt"]["artifact"]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["junit"]["totals"]["extra_reports"] = 999
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    state["verify_build_receipt"]["artifact"]["sha256"] = hashlib.sha256(
        receipt_path.read_bytes()
    ).hexdigest()
    state_path.write_text(json.dumps(state), encoding="utf-8")

    completed = _run_orchestrator(repo, env, "advance")

    assert completed.returncode == 2
    assert "junit totals are absent, red, or inconsistent" in completed.stderr.lower()
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    assert state["current_stage"] == "verify_build"


def _make_push_orchestrator_repo(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    repo = tmp_path / "orchestrator-push"
    remote = tmp_path / "remote.git"
    scripts = repo / "scripts"
    prompts = repo / "prompts"
    scripts.mkdir(parents=True)
    prompts.mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "wave-orchestrator.ps1", scripts)
    shutil.copy2(REPO_ROOT / "scripts" / "resolve-python.ps1", scripts)
    (scripts / "run_test_gate.py").write_text(
        _gate_stub_source(0), encoding="utf-8"
    )
    (prompts / "wave-plan.yaml").write_text(
        "waves:\n  - id: test-wave\n    kind: main\n    status: pending\n",
        encoding="utf-8",
    )
    (prompts / "wave-orchestrator-state.json").write_text(
        json.dumps(
            {
                "current_wave": "test-wave",
                "current_stage": "verify_build",
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text(
        "/logs/\n/prompts/wave-orchestrator-state.json\n/scripts/gate-args.txt\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "fixture",
    )
    subprocess.run(
        ["git", "init", "--bare", "-q", str(remote)],
        check=True,
        capture_output=True,
    )
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "HEAD")
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env["PROBOS_PYTHON"] = sys.executable
    return repo, remote, env


def _run_orchestrator(
    repo: Path, env: dict[str, str], command: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo / "scripts" / "wave-orchestrator.ps1"),
            command,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_wave_orchestrator_push_requires_matching_receipt_and_remote_commit(
    tmp_path: Path,
) -> None:
    repo, _remote, env = _make_push_orchestrator_repo(tmp_path)
    state_path = repo / "prompts" / "wave-orchestrator-state.json"

    assert _run_orchestrator(repo, env, "verify").returncode == 0
    assert _run_orchestrator(repo, env, "advance").returncode == 0
    assert _run_orchestrator(repo, env, "advance").returncode == 0
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    assert state["current_stage"] == "push"
    assert state["verify_build_receipt"]["wave_id"] == "test-wave"

    blocked = _run_orchestrator(repo, env, "advance")
    assert blocked.returncode == 2
    assert "push receipt" in blocked.stderr.lower()

    pushed = _run_orchestrator(repo, env, "verify")
    assert pushed.returncode == 0, pushed.stdout + pushed.stderr
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    upstream = subprocess.check_output(
        ["git", "rev-parse", "@{upstream}"], cwd=repo, text=True
    ).strip()
    assert state["push_receipt"]["commit"] == head == upstream

    advanced = _run_orchestrator(repo, env, "advance")
    assert advanced.returncode == 0, advanced.stdout + advanced.stderr
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    assert state["current_stage"] == "gate_3"


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_wave_orchestrator_push_rejects_commit_created_after_gate(
    tmp_path: Path,
) -> None:
    repo, _remote, env = _make_push_orchestrator_repo(tmp_path)

    assert _run_orchestrator(repo, env, "verify").returncode == 0
    assert _run_orchestrator(repo, env, "advance").returncode == 0
    assert _run_orchestrator(repo, env, "advance").returncode == 0
    upstream_before = subprocess.check_output(
        ["git", "rev-parse", "@{upstream}"], cwd=repo, text=True
    ).strip()
    (repo / "ungated.txt").write_text("ungated\n", encoding="utf-8")
    _git(repo, "add", "ungated.txt")
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "ungated",
    )

    blocked = _run_orchestrator(repo, env, "verify")

    assert blocked.returncode == 2
    assert "gate receipt is stale" in blocked.stderr.lower()
    assert subprocess.check_output(
        ["git", "rev-parse", "@{upstream}"], cwd=repo, text=True
    ).strip() == upstream_before
    assert subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip() != upstream_before


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_wave_orchestrator_push_race_cannot_publish_concurrent_commit(
    tmp_path: Path,
) -> None:
    repo, _remote, env = _make_push_orchestrator_repo(tmp_path)
    assert _run_orchestrator(repo, env, "verify").returncode == 0
    assert _run_orchestrator(repo, env, "advance").returncode == 0
    assert _run_orchestrator(repo, env, "advance").returncode == 0
    gated_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    real_git = shutil.which("git")
    assert real_git is not None
    wrapper_dir = tmp_path / "git-wrapper"
    wrapper_dir.mkdir()
    wrapper_script = wrapper_dir / "git_wrapper.py"
    wrapper_script.write_text(
        "from pathlib import Path\n"
        "import os, subprocess, sys\n"
        "arguments = ['HEAD^{tree}' if value == 'HEAD{tree}' else value "
        "for value in sys.argv[1:]]\n"
        "repo = Path(os.environ['RACE_REPO'])\n"
        "marker = repo / '.race-committed'\n"
        "git = os.environ['REAL_GIT']\n"
        "if 'push' in arguments and not marker.exists():\n"
        "    marker.write_text('once')\n"
        "    (repo / 'concurrent.txt').write_text('concurrent\\n')\n"
        "    subprocess.run([git, '-C', str(repo), 'add', 'concurrent.txt'], check=True)\n"
        "    subprocess.run([git, '-C', str(repo), '-c', 'user.name=ProbOS Tests', "
        "'-c', 'user.email=tests@probos.invalid', 'commit', '-q', '-m', "
        "'concurrent'], check=True)\n"
        "raise SystemExit(subprocess.run([git, *arguments]).returncode)\n",
        encoding="utf-8",
    )
    (wrapper_dir / "git.cmd").write_text(
        f'@"{sys.executable}" "%~dp0git_wrapper.py" %*\r\n',
        encoding="utf-8",
    )
    env["PATH"] = str(wrapper_dir) + os.pathsep + env.get("PATH", "")
    env["REAL_GIT"] = real_git
    env["RACE_REPO"] = str(repo)

    pushed = _run_orchestrator(repo, env, "verify")

    local_commit = subprocess.check_output(
        [real_git, "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    remote_commit = subprocess.check_output(
        [real_git, "-C", str(repo), "rev-parse", "@{upstream}"], text=True
    ).strip()
    assert pushed.returncode == 3
    assert "git tree changed" in pushed.stderr.lower()
    assert local_commit != gated_commit
    assert remote_commit == gated_commit


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_wave_orchestrator_push_ignores_remote_push_refspec_redirect(
    tmp_path: Path,
) -> None:
    repo, remote, env = _make_push_orchestrator_repo(tmp_path)
    assert _run_orchestrator(repo, env, "verify").returncode == 0
    assert _run_orchestrator(repo, env, "advance").returncode == 0
    assert _run_orchestrator(repo, env, "advance").returncode == 0
    (repo / "committed.txt").write_text("gated\n", encoding="utf-8")
    _git(repo, "add", "committed.txt")
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "gated commit",
    )
    state_path = repo / "prompts" / "wave-orchestrator-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    state["current_stage"] = "verify_build"
    state.pop("verify_build_receipt", None)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    assert _run_orchestrator(repo, env, "verify").returncode == 0
    assert _run_orchestrator(repo, env, "advance").returncode == 0
    assert _run_orchestrator(repo, env, "advance").returncode == 0
    _git(repo, "config", "remote.origin.push", "HEAD:refs/heads/other")

    pushed = _run_orchestrator(repo, env, "verify")

    assert pushed.returncode == 0, pushed.stdout + pushed.stderr
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    merge_ref = subprocess.check_output(
        [
            "git",
            "config",
            "--get",
            f"branch.{subprocess.check_output(['git', 'branch', '--show-current'], cwd=repo, text=True).strip()}.merge",
        ],
        cwd=repo,
        text=True,
    ).strip()
    main = subprocess.check_output(
        ["git", "--git-dir", str(remote), "rev-parse", merge_ref],
        text=True,
    ).strip()
    other = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/other"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert main == head
    assert other.returncode != 0


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
@pytest.mark.parametrize("receipt", [None, "stale"])
def test_wave_orchestrator_advance_rejects_missing_or_stale_gate_receipt(
    tmp_path: Path, receipt: str | None
) -> None:
    repo = tmp_path / f"orchestrator-receipt-{receipt}"
    scripts = repo / "scripts"
    prompts = repo / "prompts"
    scripts.mkdir(parents=True)
    prompts.mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "wave-orchestrator.ps1", scripts)
    shutil.copy2(REPO_ROOT / "scripts" / "resolve-python.ps1", scripts)
    (prompts / "wave-plan.yaml").write_text(
        "waves:\n  - id: test-wave\n    kind: main\n    status: pending\n",
        encoding="utf-8",
    )
    state: dict[str, object] = {
        "current_wave": "test-wave",
        "current_stage": "verify_build",
        "history": [],
    }
    if receipt is not None:
        state["verify_build_receipt"] = {
            "wave_id": "test-wave",
            "tree": {
                "head": "stale",
                "index_tree": "stale",
                "status_sha256": "stale",
            },
        }
    (prompts / "wave-orchestrator-state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )
    (repo / ".gitignore").write_text(
        "/prompts/wave-orchestrator-state.json\n", encoding="utf-8"
    )
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        "fixture",
    )
    env = os.environ.copy()
    env["PROBOS_PYTHON"] = sys.executable

    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(scripts / "wave-orchestrator.ps1"),
            "advance",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )

    assert completed.returncode == 2
    assert "receipt" in completed.stderr.lower()
    persisted = json.loads(
        (prompts / "wave-orchestrator-state.json").read_text(encoding="utf-8-sig")
    )
    assert persisted["current_stage"] == "verify_build"


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_wave_orchestrator_precheck_rejects_each_missing_prompt_pattern(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "orchestrator-missing-pattern"
    scripts = repo / "scripts"
    prompts = repo / "prompts"
    scripts.mkdir(parents=True)
    prompts.mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "wave-orchestrator.ps1", scripts)
    shutil.copy2(REPO_ROOT / "scripts" / "resolve-python.ps1", scripts)
    (prompts / "present.md").write_text("present\n", encoding="utf-8")
    (prompts / "wave-plan.yaml").write_text(
        "waves:\n"
        "  - id: test-wave\n"
        "    kind: main\n"
        "    status: pending\n"
        "    prompt_paths:\n"
        "      - prompts/present.md\n"
        "      - prompts/missing.md\n",
        encoding="utf-8",
    )
    (prompts / "wave-orchestrator-state.json").write_text(
        json.dumps(
            {
                "current_wave": "test-wave",
                "current_stage": "precheck",
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PROBOS_PYTHON"] = sys.executable

    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(scripts / "wave-orchestrator.ps1"),
            "verify",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
    )

    assert completed.returncode == 2
    assert "prompts/missing.md" in completed.stderr


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
def test_wave_orchestrator_verify_without_active_wave_is_nonzero(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "orchestrator-no-wave"
    scripts = repo / "scripts"
    prompts = repo / "prompts"
    scripts.mkdir(parents=True)
    prompts.mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "wave-orchestrator.ps1", scripts)
    shutil.copy2(REPO_ROOT / "scripts" / "resolve-python.ps1", scripts)
    (prompts / "wave-orchestrator-state.json").write_text(
        json.dumps(
            {"current_wave": None, "current_stage": "idle", "history": []}
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(scripts / "wave-orchestrator.ps1"),
            "verify",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 2
    assert "No active wave" in completed.stderr


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell unavailable")
@pytest.mark.parametrize(
    ("plan", "stage", "expected_message"),
    [
        ("waves: []\n", "verify_outputs", "absent from wave-plan.yaml"),
        (
            "waves:\n  - id: test-wave\n    kind: meta\n    status: pending\n",
            "verify_outputs",
            "no expected outputs",
        ),
        ("not: [valid\n", "verify_outputs", "parser failed"),
    ],
)
def test_wave_orchestrator_verify_fails_closed_on_invalid_plan_state(
    tmp_path: Path, plan: str, stage: str, expected_message: str
) -> None:
    repo = tmp_path / "orchestrator-invalid"
    scripts = repo / "scripts"
    prompts = repo / "prompts"
    scripts.mkdir(parents=True)
    prompts.mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "wave-orchestrator.ps1", scripts)
    shutil.copy2(REPO_ROOT / "scripts" / "resolve-python.ps1", scripts)
    (prompts / "wave-plan.yaml").write_text(plan, encoding="utf-8")
    (prompts / "wave-orchestrator-state.json").write_text(
        json.dumps(
            {
                "current_wave": "test-wave",
                "current_stage": stage,
                "history": [],
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PROBOS_PYTHON"] = sys.executable

    completed = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(scripts / "wave-orchestrator.ps1"),
            "verify",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )

    assert completed.returncode != 0
    assert expected_message.lower() in (completed.stdout + completed.stderr).lower()