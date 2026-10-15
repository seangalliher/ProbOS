"""BF-892 (#1543): model-authored code outside the run_python sandbox no longer inherits the runtime's environment.

Four tests are child-boundary checks (the two pytest runners over model-written tests, the in-process
container sandbox, and the three dependency installs): each plants a synthetic credential-shaped variable,
first proves that a child which INHERITS this process's environment sees it (the premise), then proves the
site's child does not. One test is that premise on its own (a control: it stays green if the fix is
reverted). Two check the VIRTUAL_ENV extension of the install environment (passed when set, omitted when
unset). Two check the builder's git launches (each is handed the allowlist; a commit still finds its
identity through the home variables the allowlist keeps). Children print or write only booleans,
never an environment value or listing.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from probos.cognitive import builder as builder_module
from probos.cognitive import dependency_resolver as dependency_resolver_module
from probos.cognitive.builder import _is_dirty_working_tree, _run_git, _run_targeted_tests, _run_tests
from probos.cognitive.dependency_resolver import DependencyResolver
from probos.security.container_sandbox import ContainerExec, InProcessContainerSandbox, SandboxLimits

PLANT_NAME = "BF892_PROBE_API_KEY"
PLANT_VALUE = "bf892-planted-secret-4c1"
_SEES_PLANT = f"import os; print(os.environ.get({PLANT_NAME!r}) == {PLANT_VALUE!r})"


@pytest.fixture
def plant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PLANT_NAME, PLANT_VALUE)


def _inheriting_child_sees_plant() -> bool:
    done = subprocess.run([sys.executable, "-c", _SEES_PLANT], env=None, capture_output=True, text=True, timeout=60)
    return done.stdout.strip() == "True"


def _write_model_test(work: Path) -> Path:
    tests = work / "tests"
    tests.mkdir()
    (tests / "test_probe_env.py").write_text(
        "import json, os\n\n"
        "def test_records_what_the_child_sees():\n"
        f"    seen = {{'plant': os.environ.get({PLANT_NAME!r}) == {PLANT_VALUE!r},\n"
        f"            'pythonpath': {str(work)!r} in os.environ.get('PYTHONPATH', '').split(os.pathsep)}}\n"
        "    open('seen.json', 'w').write(json.dumps(seen))\n",
        encoding="utf-8",
    )
    return work / "seen.json"


def test_premise_an_inheriting_child_sees_the_plant(plant: None) -> None:
    assert _inheriting_child_sees_plant(), "premise: a child that inherits this process's environment must see the planted variable"


@pytest.mark.timeout(150)
async def test_run_tests_hides_the_plant_and_keeps_pythonpath(plant: None, tmp_path: Path) -> None:
    assert _inheriting_child_sees_plant(), "premise: an inheriting child must see the planted variable"
    seen_path = _write_model_test(tmp_path)

    passed, _ = await _run_tests(str(tmp_path), timeout=120)

    assert passed and seen_path.exists(), "premise: the model test must run and pass under _run_tests"
    assert json.loads(seen_path.read_text(encoding="utf-8")) == {"plant": False, "pythonpath": True}


@pytest.mark.timeout(150)
async def test_run_targeted_tests_hides_the_plant(plant: None, tmp_path: Path) -> None:
    assert _inheriting_child_sees_plant(), "premise: an inheriting child must see the planted variable"
    seen_path = _write_model_test(tmp_path)

    passed, _, test_files = await _run_targeted_tests(str(tmp_path), ["tests/test_probe_env.py"], timeout=120)

    assert test_files == [str(tmp_path / "tests" / "test_probe_env.py")], (
        "premise: the targeted path must run, not the full-suite fallback"
    )
    assert passed and seen_path.exists(), "premise: the targeted model test must run and pass"
    assert json.loads(seen_path.read_text(encoding="utf-8")) == {"plant": False, "pythonpath": True}


async def test_inprocess_container_hides_the_plant_and_keeps_request_env(plant: None) -> None:
    assert _inheriting_child_sees_plant(), "premise: an inheriting child must see the planted variable"
    request = ContainerExec(
        command=[
            sys.executable,
            "-c",
            f"import os; print(os.environ.get({PLANT_NAME!r}) == {PLANT_VALUE!r}, os.environ.get('BF892_EXTENSION') == 'kept')",
        ],
        egress_policy="bridge",
        env={"BF892_EXTENSION": "kept"},
        limits=SandboxLimits(wall_timeout_seconds=30),
    )

    out = await InProcessContainerSandbox().run(request)

    # Read into locals so a failed assert shows booleans and tokens, never the outcome's repr.
    ran_to_completion = out.success
    words = out.stdout.split()
    assert ran_to_completion, "premise: the probe command must run to completion in the in-process sandbox"
    assert words == ["False", "True"]


async def test_dependency_install_hides_the_plant_on_every_method(plant: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # Captured BEFORE the patch below: subprocess.run is one module-wide attribute, so the
    # premise and every probe child must go through the real function, not the stand-in.
    real_run = subprocess.run
    premise = real_run([sys.executable, "-c", _SEES_PLANT], env=None, capture_output=True, text=True, timeout=60)
    inheriting_child_sees_plant = premise.stdout.strip() == "True"
    assert inheriting_child_sees_plant, "premise: an inheriting child must see the planted variable"

    seen: list[tuple[str, bool]] = []

    def _probe_run(argv, **kw):
        # .strip(): the child prints "True\n"; comparing without it would never flip the flag.
        done = real_run([sys.executable, "-c", _SEES_PLANT], env=kw.get("env"), capture_output=True, text=True, timeout=60)
        seen.append((" ".join(map(str, argv[1:3])), done.stdout.strip() == "True"))
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(dependency_resolver_module.subprocess, "run", _probe_run)
    monkeypatch.setattr(dependency_resolver_module.shutil, "which", lambda name: "uv-bf892-fake")

    ok, _ = await DependencyResolver(allowed_imports=[])._install_package("bf892-not-a-package")

    assert ok is False
    assert [label for label, _ in seen] == ["-m pip", "pip install", "add bf892-not-a-package"]
    assert [flag for _, flag in seen] == [False, False, False]


async def test_dependency_install_keeps_virtual_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path))
    envs: list[dict[str, str] | None] = []

    def _record_run(argv, **kw):
        envs.append(kw.get("env"))
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(dependency_resolver_module.subprocess, "run", _record_run)
    monkeypatch.setattr(dependency_resolver_module.shutil, "which", lambda name: "uv-bf892-fake")

    await DependencyResolver(allowed_imports=[])._install_package("bf892-not-a-package")

    launch_count = len(envs)
    assert launch_count == 3, "premise: pip, uv pip and uv add must each be reached"
    assert all(env is not None for env in envs), "premise: every method must be handed an explicit environment"
    assert [env.get("VIRTUAL_ENV") == str(tmp_path) for env in envs] == [True, True, True]


async def test_dependency_install_omits_unset_virtual_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    envs: list[dict[str, str] | None] = []

    def _record_run(argv, **kw):
        envs.append(kw.get("env"))
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(dependency_resolver_module.subprocess, "run", _record_run)
    monkeypatch.setattr(dependency_resolver_module.shutil, "which", lambda name: "uv-bf892-fake")

    await DependencyResolver(allowed_imports=[])._install_package("bf892-not-a-package")

    launch_count = len(envs)
    assert launch_count == 3, "premise: pip, uv pip and uv add must each be reached"
    assert all(env is not None for env in envs), "premise: every method must be handed an explicit environment"
    assert ["VIRTUAL_ENV" not in env for env in envs] == [True, True, True]


async def test_builder_git_launches_get_the_allowlist(
    plant: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Captured BEFORE the patches below: both are module-wide attributes, so each recorder
    # must call through to the real function, not to itself.
    real_run = subprocess.run
    real_exec = asyncio.create_subprocess_exec
    seen: list[dict[str, str] | None] = []

    def _record_run(*args, **kwargs):
        seen.append(kwargs.get("env"))
        return real_run(*args, **kwargs)

    async def _record_exec(*args, **kwargs):
        seen.append(kwargs.get("env"))
        return await real_exec(*args, **kwargs)

    monkeypatch.setattr(builder_module.subprocess, "run", _record_run)
    monkeypatch.setattr(builder_module.asyncio, "create_subprocess_exec", _record_exec)

    await _run_git(["init", "-q"], str(tmp_path))
    await _is_dirty_working_tree(str(tmp_path))

    # A count in a local, not len(seen) inside the assert: a failed assert must never render the environments.
    launch_count = len(seen)
    assert launch_count == 3, "premise: _run_git (one run) and _is_dirty_working_tree (two exec calls) must each be reached"
    assert all(env is not None for env in seen), "premise: every git launch must be handed an explicit environment"
    assert [PLANT_NAME in env for env in seen] == [False, False, False]
    assert ["PATH" in env for env in seen] == [True, True, True]


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
async def test_builder_git_commit_finds_identity_under_the_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text(
        "[user]\n\tname = BF892 Tester\n\temail = bf892@example.invalid\n", encoding="utf-8"
    )
    # Every home variable points at the temp home, so a runner's own HOME (Git Bash) cannot leak in.
    drive, rest = os.path.splitdrive(str(home))
    monkeypatch.setenv("HOMEDRIVE", drive)
    monkeypatch.setenv("HOMEPATH", rest)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()

    init_rc, _, _ = await _run_git(["init", "-q"], str(repo))
    commit_rc, _, _ = await _run_git(["commit", "--allow-empty", "-m", "bf892"], str(repo))
    _, author, _ = await _run_git(["log", "-1", "--format=%an"], str(repo))

    assert init_rc == 0, "premise: git init must succeed in the temp repository"
    assert commit_rc == 0, "the commit must find an identity under the allowlisted environment"
    # The premise check: the name can only have come from the temp home's .gitconfig, reached
    # through the home variables the allowlist keeps.
    assert author == "BF892 Tester"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
async def test_builder_git_reads_home_when_it_differs_from_the_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Git for Windows reads HOME before USERPROFILE. The profile is a decoy with no identity and
    # no excludes, so both results below can only come from HOME's .gitconfig.
    home = tmp_path / "home"
    profile = tmp_path / "profile"
    home.mkdir()
    profile.mkdir()
    excludes = home / "global-ignore"
    excludes.write_text("ignored.txt\n", encoding="utf-8")
    (home / ".gitconfig").write_text(
        "[user]\n\tname = BF892 Home\n\temail = bf892-home@example.invalid\n"
        f"[core]\n\texcludesFile = {excludes.as_posix()}\n",
        encoding="utf-8",
    )
    drive, rest = os.path.splitdrive(str(profile))
    monkeypatch.setenv("HOMEDRIVE", drive)
    monkeypatch.setenv("HOMEPATH", rest)
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tracked.txt").write_text("x\n", encoding="utf-8")
    (repo / "ignored.txt").write_text("x\n", encoding="utf-8")

    init_rc, _, _ = await _run_git(["init", "-q"], str(repo))
    committed, _ = await builder_module._git_add_and_commit(["tracked.txt"], "bf892", str(repo))
    _, author, _ = await _run_git(["log", "-1", "--format=%an"], str(repo))
    dirty_with_only_ignored_file = await _is_dirty_working_tree(str(repo))
    (repo / "untracked.txt").write_text("x\n", encoding="utf-8")
    dirty_with_untracked_file = await _is_dirty_working_tree(str(repo))

    assert init_rc == 0, "premise: git init must succeed in the temp repository"
    assert dirty_with_untracked_file is True, "premise: the dirty check must see an untracked file"
    assert committed, "the builder's commit must find the identity in HOME's .gitconfig"
    assert author == "BF892 Home"
    assert dirty_with_only_ignored_file is False, "a file HOME's excludesFile ignores must not make the tree dirty"
