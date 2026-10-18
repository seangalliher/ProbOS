"""BF-904a (#1585), milestone M1: the native build pipeline's git runs no hook, no fsmonitor and no planted config.

Code under test runs as the operator's user in the tree the build writes into, so it can plant a
repository hook, set ``core.fsmonitor`` or add a ``filter.<name>.clean`` driver that a LATER git command of
the pipeline (the commit, the checkout back, the branch delete, the worktree manager's adoption) would run.
M1 closes that two ways. Every git process of the pipeline starts with ``HARDENED_GIT_CONFIG_ARGS``
(``-c core.hooksPath=<null device> -c core.fsmonitor=false``). And a change in the resolved config listing or in
the hooks directory between the start of the test phase and its end, or a capture that failed, refuses the
commit and runs no further git command. A filter driver is not stopped by the options; the digest is its control.

Rules this file keeps:

* Real git in repositories under ``tmp_path`` (repo-local identity, ``commit.gpgsign false``,
  ``core.autocrlf false``); the helpers are copied, not imported, from the BF-896 and BF-897 tests.
* What a hook, an fsmonitor or a filter would run is a write to a marker file. Every "it did not run" is
  paired with a premise asserted FIRST on a sibling fixture with PLAIN git (no override): the marker IS
  written there. A pass therefore cannot be vacuous; if this machine's git does not run that code, the premise
  fails loudly and the test is not to be skipped.
* The test's own git calls use ``_control_env()``: the process environment minus every ``GIT_*`` name. The agent
  harness exports a ``GIT_CONFIG_*`` triple (``core.fsmonitor=false`` at command-line scope, which overrides
  repository config) that would stop a plain ``git status`` from running a repository fsmonitor and fail F1's
  premise in the gate. An autouse fixture also deletes every ``GIT_*`` name from ``os.environ``, so the worktree
  manager's calls (which inherit the whole environment) do not depend on the invoking shell either.
* No sleeps, nothing ordered by wall-clock time, every subprocess the tests start has a timeout, every await is bounded.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import stat
import subprocess
import sys
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.cognitive import builder as builder_module
from probos.cognitive.builder import BuildResult, BuildSpec, execute_approved_build
from probos.execution.command_env import HARDENED_GIT_CONFIG_ARGS
from probos.security.pii_redaction import LogRedactionFormatter
from probos.worktree_manager import WorktreeManager

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
pytestmark = needs_git

TARGET = "src/probos/a.py"
OTHER = "src/probos/other.py"
NEW = "src/probos/newpkg/fresh.py"
BAD = "src/probos/bad.py"
ORIGINAL = "x = 1\n"
SEED = {TARGET: ORIGINAL, OTHER: "y = 1\n"}
BROKEN = "def broken(:\n"
IDENTITY_ARGS = ["rev-parse", "--absolute-git-dir"]
CONFIG_ARGS = ["config", "--list", "--show-origin", "-z"]
BUILD_ID = "bf904a-adopt-0001"  # WorktreeManager.create keeps the first 8 characters: branch builder-bf904a-a
EXEC_BRANCH = "exec-bf904a"
COMMIT_HOOKS = ("pre-commit", "prepare-commit-msg", "commit-msg", "post-commit", "post-checkout", "reference-transaction")

# The real runner, captured at import before any test patches ``subprocess.run`` (E1 does): the tests' own git
# calls go through it, so a recorder installed by a test never sees them.
_REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def _no_ambient_git_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every ``GIT_*`` name from the process environment for the test's duration (see the module docstring)."""
    for name in list(os.environ):
        if name.upper().startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Helpers (copied from tests/test_bf896_executor_identity_and_blocks.py and tests/test_bf897_build_pipeline_scale_and_checkout.py)
# ---------------------------------------------------------------------------


def _control_env() -> dict[str, str]:
    """The environment of every plain git call in this file: the process environment minus every ``GIT_*`` name."""
    return {name: value for name, value in os.environ.items() if not name.upper().startswith("GIT_")}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _REAL_RUN(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        env=_control_env(), stdin=subprocess.DEVNULL, timeout=60,
    )


def _out(cwd: Path, *args: str) -> str:
    done = _git(cwd, *args)
    assert done.returncode == 0, f"premise: git {' '.join(args)} failed: {done.stderr}"
    return done.stdout.strip()


def _init_repo(path: Path, branch: str, files: dict[str, str]) -> None:
    path.mkdir(parents=True)
    for args in (
        ("init", "-q", "-b", branch),
        ("config", "user.email", "bf904a@example.invalid"),
        ("config", "user.name", "BF904a Tester"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.autocrlf", "false"),
    ):
        assert _git(path, *args).returncode == 0, f"premise: git {args[0]} must succeed"
    for rel, text in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))  # exact bytes: no newline translation in the fixture
    assert _git(path, "add", "-A").returncode == 0, "premise: git add must succeed"
    assert _git(path, "commit", "-q", "--allow-empty", "-m", "seed").returncode == 0, "premise: the seed commit"


def _plain_repo(path: Path, files: dict[str, str] | None = None) -> Path:
    _init_repo(path, "main", SEED if files is None else files)
    return path


def _linked_worktree(root: Path, files: dict[str, str] | None = None) -> tuple[Path, Path, Path]:
    """``(base, victim, wt)``: ``wt`` is a linked worktree of ``base`` (its ``.git`` is a pointer
    file) on branch ``main``; ``victim`` is an unrelated repository the pointer can be turned on."""
    base, victim, wt = root / "base", root / "victim", root / "wt"
    _init_repo(base, "trunk", SEED if files is None else files)
    _init_repo(victim, "trunk", {"victim.txt": "victim\n"})
    assert _git(base, "worktree", "add", "-q", "-b", "main", str(wt)).returncode == 0, "premise: git worktree add"
    pointer = wt / ".git"
    assert pointer.is_file(), "premise: a linked worktree's .git is a pointer file"
    if sys.platform == "win32":
        _REAL_RUN(["attrib", "-h", str(pointer)], check=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
        assert not os.stat(pointer).st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN, "premise: pointer not hidden"
    return base, victim, wt


def _repoint(wt: Path, victim: Path) -> None:
    """Rewrite ``wt``'s ``.git`` pointer so it names ``victim``'s repository (the BF-894 round-2 swap)."""
    (wt / ".git").write_bytes(f"gitdir: {(victim / '.git').as_posix()}\n".encode("utf-8"))


def _git_dir(wt: Path) -> str:
    return _git(wt, "rev-parse", "--absolute-git-dir").stdout.strip()


def _blob(repo: Path, ref: str, path: str) -> str:
    shown = _git(repo, "show", f"{ref}:{path}")
    assert shown.returncode == 0, f"{ref}:{path} must exist in the repository ({shown.stderr.strip()})"
    return shown.stdout


def _refs(repo: Path) -> list[str]:
    return sorted(_git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout.split())


def _commit_count(repo: Path) -> int:
    return int(_git(repo, "rev-list", "--all", "--count").stdout.strip())


def _repo_state(repo: Path) -> tuple[str, int, str]:
    """Every ref with its commit, the commit count and the porcelain status: any commit, branch
    or staged file in the repository changes this value."""
    refs = _git(repo, "for-each-ref", "--format=%(refname) %(objectname)").stdout
    return refs, _commit_count(repo), _git(repo, "status", "--porcelain").stdout


def _tree(root: Path) -> dict[str, bytes]:
    """Every file under *root* except anything named ``.git`` (a worktree's pointer is one)."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(root).parts
    }


def _common_dir(work_tree: Path) -> Path:
    """The repository directory *work_tree* belongs to; the same for every linked worktree of one repository."""
    return Path(work_tree, _out(work_tree, "rev-parse", "--git-common-dir")).resolve()


def _spec(title: str = "bf904a probe") -> BuildSpec:
    return BuildSpec(title=title, description="")


def _whole(path: str, content: str, **extra: Any) -> dict[str, Any]:
    """A whole-file modify block in the shape the visiting adapter's scan emits (``base`` via extra)."""
    return {"path": path, "mode": "modify", "content": content, **extra}


def _create(path: str, content: str) -> dict[str, Any]:
    return {"path": path, "mode": "create", "content": content}


async def _bounded(awaited: Awaitable[Any], seconds: float = 120) -> Any:
    """Await *awaited* for at most *seconds*: a hung git fails the test instead of hanging the run."""
    return await asyncio.wait_for(awaited, timeout=seconds)


async def _build(work_dir: Path, changes: list[dict[str, Any]], title: str = "bf904a probe", **kwargs: Any) -> BuildResult:
    kwargs.setdefault("run_tests", False)
    return await _bounded(execute_approved_build(changes, _spec(title), str(work_dir), **kwargs))


class _GitSpy:
    """Records every ``_run_git`` call the executor makes, with the phase flag at call time, then runs the real one."""

    def __init__(self, real: Any) -> None:
        self._real = real
        self.calls: list[tuple[bool, list[str]]] = []
        self.swapped = False

    async def __call__(self, args: list[str], work_dir: str, **kwargs: Any) -> tuple[int, str, str]:
        # BF-904a A1: the safety capture reads the config listing with lossless=True; forward it.
        self.calls.append((self.swapped, list(args)))
        return await self._real(args, work_dir, **kwargs)

    def args_before_swap(self) -> list[list[str]]:
        return [args for swapped, args in self.calls if not swapped]

    def args_after_swap(self) -> list[list[str]]:
        return [args for swapped, args in self.calls if swapped]


class _FakeTests:
    """Stands for ``_run_targeted_tests``: runs the "model code" (what the tests under test could do) and passes."""

    def __init__(self, model_code: Callable[[], None] | None = None) -> None:
        self._model_code = model_code
        self.runs = 0

    async def __call__(self, work_dir: str, changed_files: list[str], timeout: int = 60) -> tuple[bool, str, list[str]]:
        self.runs += 1
        if self._model_code is not None:
            self._model_code()
        return True, "1 passed", []


class _ConfigReadFails:
    """Wraps the real ``_run_git``: the ``config --list`` read answers rc 1, on the first call or after the tests ran."""

    def __init__(self, real: Any, when: str) -> None:
        self._real = real
        self._when = when
        self.config_reads = 0
        self.injected = 0
        self.tests_ran = False

    def mark_tests_ran(self) -> None:
        self.tests_ran = True

    async def __call__(self, args: list[str], work_dir: str, **kwargs: Any) -> tuple[int, str, str]:
        # BF-904a A1: forward lossless=True to the real runner.
        if args == CONFIG_ARGS:
            self.config_reads += 1
            if (self._when == "before" and self.config_reads == 1) or (self._when == "after" and self.tests_ran):
                self.injected += 1
                return 1, "", "fatal: bf904a"
        return await self._real(args, work_dir, **kwargs)


# ---------------------------------------------------------------------------
# Planted code: what a hook, an fsmonitor or a filter would run is a write to a marker file
# ---------------------------------------------------------------------------


def _plant_hook(hooks_dir: Path, name: str, marker: Path, drain_stdin: bool = True) -> None:
    """Write executable ``hooks_dir/name`` (LF bytes) that appends its own path to *marker*."""
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook = hooks_dir / name
    drain = "cat >/dev/null 2>&1\n" if drain_stdin else ""
    hook.write_bytes(f'#!/bin/sh\n{drain}echo "$0" >> "{marker.as_posix()}"\n'.encode("utf-8"))
    os.chmod(hook, 0o755)


def _set_fsmonitor(repo: Path, marker: Path) -> None:
    """A hook-path fsmonitor in *repo*'s hooks directory, named in the repository's own config."""
    hooks_dir = _common_dir(repo) / "hooks"
    _plant_hook(hooks_dir, "fsmonitor-bf904a", marker, drain_stdin=False)  # git gives an fsmonitor hook no input to drain
    assert _git(repo, "config", "core.fsmonitor", (hooks_dir / "fsmonitor-bf904a").as_posix()).returncode == 0, (
        "premise: git config core.fsmonitor must succeed"
    )


def _filter_command(marker: Path) -> str:
    return f"sh -c 'echo bf904a-filter-command >> {marker.as_posix()}; cat'"


def _set_filter(repo: Path, marker: Path) -> None:
    """A clean filter driver in *repo*'s config, selected for every path by ``info/attributes``."""
    assert _git(repo, "config", "filter.bf904a.clean", _filter_command(marker)).returncode == 0, (
        "premise: git config filter.bf904a.clean must succeed"
    )
    attributes = _common_dir(repo) / "info" / "attributes"
    attributes.parent.mkdir(parents=True, exist_ok=True)
    attributes.write_bytes(b"* filter=bf904a\n")


def _ran(marker: Path) -> set[str]:
    """The names of the planted hooks that ran (each echoes its own path); empty when nothing ever wrote *marker*."""
    if not marker.exists():
        return set()
    text = marker.read_text(encoding="utf-8", errors="replace")
    return {Path(line.strip()).name for line in text.splitlines() if line.strip()}


def _verb(argv: list[str]) -> str:
    """The git verb of *argv*: the first element after the program and any leading options."""
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        i += 2 if argv[i] == "-c" else 1
    return argv[i] if i < len(argv) else ""


def _commit_on_branch(work_tree: Path, branch: str) -> str:
    """Plain git in *work_tree*: a new *branch* carrying one commit. Returns that commit."""
    assert _git(work_tree, "checkout", "-q", "-b", branch).returncode == 0, "premise: the executor's branch is created"
    (work_tree / "adopted.txt").write_bytes(b"adopted\n")
    assert _git(work_tree, "add", "--", "adopted.txt").returncode == 0, "premise: git add must succeed"
    assert _git(work_tree, "commit", "-q", "-m", "exec").returncode == 0, "premise: the executor's commit"
    return _out(work_tree, "rev-parse", "HEAD")


# ---------------------------------------------------------------------------
# H1, H2, H3: hooks
# ---------------------------------------------------------------------------


async def test_a_hook_present_before_the_build_never_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocks = [_create(NEW, "ok = 1\n"), _whole(TARGET, "x = 2\n", base=ORIGINAL)]

    # premise, first (sibling repository, plain git): the six hooks run at a commit and at a branch creation
    sibling = _plain_repo(tmp_path / "sibling")
    sibling_marker = tmp_path / "sibling-marker.txt"
    for name in COMMIT_HOOKS:
        _plant_hook(_common_dir(sibling) / "hooks", name, sibling_marker)
    assert not sibling_marker.exists(), "premise: planting a hook runs nothing"
    assert _git(sibling, "commit", "-q", "--allow-empty", "-m", "p").returncode == 0, "premise: plain git commits"
    assert _git(sibling, "checkout", "-q", "-b", "p").returncode == 0, "premise: plain git creates a branch"
    seen = _ran(sibling_marker)
    assert {"pre-commit", "post-commit", "post-checkout", "reference-transaction"} <= seen, (
        f"premise: this git must run planted hooks under plain git (ran: {sorted(seen)}); report this, do not skip"
    )

    # probe: the same hooks sit in the repository before the build starts, so the baseline includes them
    probe = _plain_repo(tmp_path / "probe")
    marker = tmp_path / "probe-marker.txt"
    for name in COMMIT_HOOKS:
        _plant_hook(_common_dir(probe) / "hooks", name, marker)
    assert not marker.exists(), "premise: planting a hook runs nothing"
    fake = _FakeTests()
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)

    result = await _build(probe, blocks, run_tests=True)
    ran = _ran(marker)  # read at once: no other git command of the test comes first

    assert fake.runs == 1, "premise: the test phase ran, so the baseline was taken and the comparison made"
    assert result.success and result.commit_hash, f"the build commits, the planted hooks being unchanged: {result.error}"
    assert ran == set(), f"no planted hook ran at any git command of the build (ran: {sorted(ran)})"
    assert not marker.exists()
    assert _blob(probe, result.branch_name, NEW) == "ok = 1\n"
    assert _blob(probe, result.branch_name, TARGET) == "x = 2\n"


async def test_a_hook_planted_during_the_tests_is_refused_and_no_git_runs_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = ("post-checkout", "reference-transaction")

    # premise, first (sibling repository, plain git): both hooks run at a branch creation
    sibling = _plain_repo(tmp_path / "sibling")
    sibling_marker = tmp_path / "sibling-marker.txt"
    for name in names:
        _plant_hook(_common_dir(sibling) / "hooks", name, sibling_marker)
    assert _git(sibling, "checkout", "-q", "-b", "p").returncode == 0, "premise: plain git creates a branch"
    seen = _ran(sibling_marker)
    assert set(names) <= seen, f"premise: this git must run planted hooks under plain git (ran: {sorted(seen)}); report this, do not skip"

    probe = _plain_repo(tmp_path / "probe")
    hooks_dir = _common_dir(probe) / "hooks"
    marker = tmp_path / "probe-marker.txt"
    tree_before = _tree(probe)
    spy = _GitSpy(builder_module._run_git)

    def plant() -> None:  # the code under test: runs after the baseline, before the comparison
        for name in names:
            _plant_hook(hooks_dir, name, marker)
        spy.swapped = True

    fake = _FakeTests(plant)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)
    monkeypatch.setattr(builder_module, "_run_git", spy)

    result = await _build(probe, [_create(NEW, "ok = 1\n")], run_tests=True)
    ran = _ran(marker)  # read at once: no other git command of the test comes first

    assert fake.runs == 1 and spy.swapped, "premise: the hooks were planted inside the build, after the baseline"
    assert (hooks_dir / "post-checkout").exists(), "premise: the plant is on disk"
    assert any(args[:2] == ["checkout", "-b"] for args in spy.args_before_swap()), "premise: the spy saw the build branch created"
    assert result.tests_passed, "the tests passed: the refusal is the comparison's"
    assert result.success is False, result.error
    for needle in (
        "Git configuration or hooks changed while the tests ran", "post-checkout", "reference-transaction", result.branch_name,
    ):
        assert needle in result.error, f"{needle!r} must be in the error: {result.error}"
    assert not result.commit_hash
    assert spy.args_after_swap() == [IDENTITY_ARGS, CONFIG_ARGS], (
        "after the plant: the identity re-read, then the config listing; no add, commit, checkout, reset or branch"
    )
    assert ran == set() and not marker.exists(), f"no planted hook ran (ran: {sorted(ran)})"
    assert _git(probe, "symbolic-ref", "--short", "HEAD").stdout.strip() == result.branch_name, (
        "the checkout is left on the build branch, as the error says"
    )
    assert not (probe / NEW).exists(), "the file this build created is unlinked, with no git"
    assert _tree(probe) == tree_before, "and no other file changed"
    assert result.branch_name in _refs(probe), "the build branch is kept: no branch -D ran"


@pytest.mark.parametrize("when", ["before", "after"])
async def test_a_failed_capture_counts_as_a_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str) -> None:
    blocks = [_create(NEW, "ok = 1\n")]

    # control, first: the same build with nothing failing commits
    control_repo = _plain_repo(tmp_path / "control")
    monkeypatch.setattr(builder_module, "_run_targeted_tests", _FakeTests())
    control = await _build(control_repo, blocks, run_tests=True)
    assert control.success and control.commit_hash, f"control: with every read answering, the build commits: {control.error}"

    probe = _plain_repo(tmp_path / "probe")
    wrapper = _ConfigReadFails(builder_module._run_git, when)
    fake = _FakeTests(wrapper.mark_tests_ran)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)
    monkeypatch.setattr(builder_module, "_run_git", wrapper)

    result = await _build(probe, blocks, run_tests=True)

    assert fake.runs == 1, "premise: the test phase ran"
    assert result.success is False and not result.commit_hash, result.error
    assert f"could not be read {when} the tests" in result.error, result.error
    assert wrapper.injected == 1, "and the refusal is the injected failure's"


# ---------------------------------------------------------------------------
# H4, H5, H6, H3b: what the hooks listing watches (the shared directory, the bytes, an absent directory, an unreadable one)
# ---------------------------------------------------------------------------

REFUSAL = "Git configuration or hooks changed while the tests ran"


async def test_a_hook_added_to_the_shared_hooks_directory_of_a_linked_worktree_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocks = [_create(NEW, "ok = 1\n")]

    # control, first: a linked worktree whose shared hooks directory stays as it was commits
    _control_base, _control_victim, control_wt = _linked_worktree(tmp_path / "control")
    monkeypatch.setattr(builder_module, "_run_targeted_tests", _FakeTests())
    control = await _build(control_wt, blocks, run_tests=True)
    assert control.success and control.commit_hash, f"control: nothing planted, the build commits: {control.error}"

    _base, _victim, wt = _linked_worktree(tmp_path / "probe")
    hooks_dir = _common_dir(wt) / "hooks"
    assert _common_dir(wt) != Path(_git_dir(wt)).resolve(), (
        "premise: the worktree's own git directory is not the repository's common directory, so a --git-dir read would watch the wrong one"
    )
    assert hooks_dir.is_dir(), "premise: the shared hooks directory exists"
    marker = tmp_path / "probe-marker.txt"
    fake = _FakeTests(lambda: _plant_hook(hooks_dir, "post-checkout", marker))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)

    result = await _build(wt, blocks, run_tests=True)

    assert fake.runs == 1 and (hooks_dir / "post-checkout").exists(), "premise: the hook was planted in the shared directory during the tests"
    assert result.success is False, result.error
    for needle in (REFUSAL, "post-checkout"):
        assert needle in result.error, f"{needle!r} must be in the error: {result.error}"
    assert not result.commit_hash
    assert not marker.exists(), "no planted hook ran"


async def test_a_hook_changed_in_place_during_the_tests_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocks = [_create(NEW, "ok = 1\n")]

    def append_line(hooks_dir: Path) -> None:
        with (hooks_dir / "pre-commit").open("ab") as handle:
            handle.write(b"# changed in place\n")

    # control, first: the same hook in the repository before the build, left alone by the tests, commits
    control_repo = _plain_repo(tmp_path / "control")
    _plant_hook(_common_dir(control_repo) / "hooks", "pre-commit", tmp_path / "control-marker.txt")
    monkeypatch.setattr(builder_module, "_run_targeted_tests", _FakeTests())
    control = await _build(control_repo, blocks, run_tests=True)
    assert control.success and control.commit_hash, f"control: the hook is unchanged, the build commits: {control.error}"

    probe = _plain_repo(tmp_path / "probe")
    hooks_dir = _common_dir(probe) / "hooks"
    marker = tmp_path / "probe-marker.txt"
    _plant_hook(hooks_dir, "pre-commit", marker)  # before the build: the baseline holds it
    bytes_before = (hooks_dir / "pre-commit").read_bytes()
    fake = _FakeTests(lambda: append_line(hooks_dir))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)

    result = await _build(probe, blocks, run_tests=True)

    assert fake.runs == 1, "premise: the test phase ran"
    assert (hooks_dir / "pre-commit").is_file(), "premise: the same hook file is there after the tests"
    assert (hooks_dir / "pre-commit").read_bytes() != bytes_before, "premise: its bytes differ from the baseline's"
    assert result.success is False, result.error
    for needle in (REFUSAL, "pre-commit"):
        assert needle in result.error, f"{needle!r} must be in the error: {result.error}"
    assert not result.commit_hash
    assert not marker.exists(), "no planted hook ran"


@pytest.mark.parametrize("case", ["stays-absent", "appears-during-the-tests"])
async def test_a_repository_without_a_hooks_directory_is_not_refused_by_that_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    blocks = [_create(NEW, "ok = 1\n")]
    repo = _plain_repo(tmp_path / "repo")
    hooks_dir = _common_dir(repo) / "hooks"
    shutil.rmtree(hooks_dir)
    assert not hooks_dir.exists(), "premise: the repository has no hooks directory"
    marker = tmp_path / "marker.txt"
    fake = _FakeTests(lambda: _plant_hook(hooks_dir, "post-checkout", marker) if case == "appears-during-the-tests" else None)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)

    result = await _build(repo, blocks, run_tests=True)

    assert fake.runs == 1, "premise: the test phase ran"
    if case == "stays-absent":
        assert result.success and result.commit_hash, f"an absent directory is an empty listing, not a change: {result.error}"
    else:
        assert (hooks_dir / "post-checkout").exists(), "premise: the directory and the hook appeared during the tests"
        assert result.success is False, result.error
        for needle in (REFUSAL, "post-checkout"):
            assert needle in result.error, f"{needle!r} must be in the error: {result.error}"
        assert not result.commit_hash
        assert not marker.exists(), "no planted hook ran"


def _dir_forms(directory: Path) -> frozenset[str]:
    """BF-904a A2: every string form a path to *directory* can take (absolute, and with links resolved), case-normalised.
    Computed BEFORE a seam installs: a seam must not resolve a path from inside the function it patches (on POSIX
    ``Path.resolve`` calls ``os.lstat``, so a resolve inside a patched ``os.lstat`` re-enters the patch without end)."""
    return frozenset(os.path.normcase(form) for form in (os.path.abspath(directory), os.path.realpath(directory)))


def _lexical_parent_in(path: Any, forms: frozenset[str]) -> str | None:
    """BF-904a A2: the last component of *path* when its parent directory is one of *forms*; a pure string operation."""
    if not isinstance(path, (str, os.PathLike)):
        return None
    text = os.fspath(path)
    if not isinstance(text, str):
        return None
    if os.path.normcase(os.path.dirname(os.path.abspath(text))) in forms:
        return os.path.basename(text)
    return None


class _ResolveGuard:
    """BF-904a A2: makes the re-entrancy class detectable on Windows. While a seam's installed function runs (``scope``),
    ``Path.resolve`` and ``os.path.realpath`` raise instead of answering: a filesystem-resolving call inside a patched
    ``os`` function is a defect on POSIX (unbounded recursion through ``os.lstat``) even where Windows survives it.
    The counter is per thread: the listing runs in an executor thread while the loop thread is idle."""

    MESSAGE = "a filesystem-resolving call inside the listing seam"

    def __init__(self) -> None:
        self._local = threading.local()

    @property
    def inside(self) -> int:
        return getattr(self._local, "depth", 0)

    def scope(self) -> "_ResolveGuard._Scope":
        return _ResolveGuard._Scope(self)

    class _Scope:
        def __init__(self, guard: "_ResolveGuard") -> None:
            self._guard = guard

        def __enter__(self) -> None:
            self._guard._local.depth = self._guard.inside + 1

        def __exit__(self, *exc: object) -> None:
            self._guard._local.depth = self._guard.inside - 1

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        guard = self
        for owner, name in ((Path, "resolve"), (os.path, "realpath")):
            real = getattr(owner, name)

            def guarded(*args: Any, _real: Any = real, **kwargs: Any) -> Any:
                if guard.inside:
                    raise AssertionError(_ResolveGuard.MESSAGE)
                return _real(*args, **kwargs)

            monkeypatch.setattr(owner, name, guarded)


class _Unreadable:
    """Patches ``os.scandir`` or ``os.open`` so that, for the hooks directory (``scandir``) or a direct child of it
    (``open``), the first listing (``before``) or every one made after the tests ran (``after``) raises ``PermissionError``.
    BF-904a A1: the listing reads through ``os.scandir``, ``os.lstat`` and ``os.open`` now (it used ``Path.iterdir`` and
    ``Path.read_bytes``), so the injection point moved with it; what is injected, and when, is unchanged.
    BF-904a A2: the comparison is lexical against forms computed before ``install``; no path is resolved inside the patch."""

    def __init__(self, hooks_dir: Path, target: str, when: str) -> None:
        self._forms = _dir_forms(hooks_dir)
        self._guard = _ResolveGuard()
        self._target = target
        self._when = when
        self.injected = 0
        self.tests_ran = False

    def mark_tests_ran(self) -> None:
        self.tests_ran = True

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = getattr(os, self._target)
        guard = self

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            path = args[0] if args else None
            with guard._guard.scope():
                if guard._target == "scandir":
                    watched = isinstance(path, (str, os.PathLike)) and os.path.normcase(os.path.abspath(path)) in guard._forms
                else:
                    watched = _lexical_parent_in(path, guard._forms) is not None
                if watched and (
                    (guard._when == "before" and guard.injected == 0 and not guard.tests_ran)
                    or (guard._when == "after" and guard.tests_ran)
                ):
                    guard.injected += 1
                    raise PermissionError(13, "bf904a: unreadable", str(path))
                return real(*args, **kwargs)

        self._guard.install(monkeypatch)
        monkeypatch.setattr(os, self._target, wrapper)


@pytest.mark.parametrize("target,when", [("iterdir", "before"), ("iterdir", "after"), ("entry", "before"), ("entry", "after")])
async def test_an_unreadable_hooks_directory_or_entry_counts_as_a_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str, when: str
) -> None:
    blocks = [_create(NEW, "ok = 1\n")]

    # control, first: the same build with nothing unreadable commits
    control_repo = _plain_repo(tmp_path / "control")
    monkeypatch.setattr(builder_module, "_run_targeted_tests", _FakeTests())
    control = await _build(control_repo, blocks, run_tests=True)
    assert control.success and control.commit_hash, f"control: with every read answering, the build commits: {control.error}"

    probe = _plain_repo(tmp_path / "probe")
    hooks_dir = _common_dir(probe) / "hooks"
    _plant_hook(hooks_dir, "pre-commit", tmp_path / "probe-marker.txt")
    assert any(child.is_file() for child in hooks_dir.iterdir()), "premise: the hooks directory has an entry that is read as bytes"
    unreadable = _Unreadable(hooks_dir, "scandir" if target == "iterdir" else "open", when)  # BF-904a A1: the listing's own calls
    fake = _FakeTests(unreadable.mark_tests_ran)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)
    unreadable.install(monkeypatch)

    result = await _build(probe, blocks, run_tests=True)

    assert fake.runs == 1, "premise: the test phase ran"
    assert unreadable.injected == 1, "premise: exactly the intended read failed"
    assert result.success is False and not result.commit_hash, result.error
    assert "could not be read" in result.error, result.error
    if when == "before":
        assert "could not be read before the tests" in result.error, result.error
    else:
        assert "the hooks directory" in result.error and "before the tests" not in result.error, result.error


# ---------------------------------------------------------------------------
# F1, F2: fsmonitor and filter
# ---------------------------------------------------------------------------


async def test_an_fsmonitor_set_before_the_build_never_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The agent harness exports this pair (command-line scope, which overrides repository config). Reproduce it, so the
    # test means the same in every environment: the control strips it, and the pipeline's git never receives it.
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")

    # premise, first (sibling repository, plain git): a hook-path fsmonitor runs at `git status`
    sibling = _plain_repo(tmp_path / "sibling")
    sibling_marker = tmp_path / "sibling-marker.txt"
    _set_fsmonitor(sibling, sibling_marker)
    assert not sibling_marker.exists(), "premise: setting the option runs nothing"
    assert _git(sibling, "status").returncode == 0, "premise: plain git status succeeds"
    assert sibling_marker.exists(), "premise: this git runs a hook-path fsmonitor; report this, do not skip"

    # probe: the same fsmonitor is set before the build, so the baseline includes it and the comparison cannot catch it
    probe = _plain_repo(tmp_path / "probe")
    marker = tmp_path / "probe-marker.txt"
    _set_fsmonitor(probe, marker)
    assert not marker.exists(), "premise: setting the option runs nothing"
    fake = _FakeTests()
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)

    result = await _build(probe, [_create(NEW, "ok = 1\n")], run_tests=True)
    ran = marker.exists()  # read at once: no other git command of the test comes first

    assert fake.runs == 1, "premise: the test phase ran"
    assert result.success and result.commit_hash, f"the build commits, the config being unchanged: {result.error}"
    assert ran is False, "no git command of the build ran the fsmonitor"
    assert _blob(probe, result.branch_name, NEW) == "ok = 1\n"


async def test_a_filter_planted_during_the_tests_is_refused_and_never_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    # premise, first (sibling repository, plain git): the clean filter runs at `git add`
    sibling = _plain_repo(tmp_path / "sibling")
    sibling_marker = tmp_path / "sibling-marker.txt"
    _set_filter(sibling, sibling_marker)
    (sibling / "f.txt").write_bytes(b"filtered\n")
    assert not sibling_marker.exists(), "premise: configuring the filter runs nothing"
    assert _git(sibling, "add", "--", "f.txt").returncode == 0, "premise: plain git add succeeds"
    assert sibling_marker.exists(), "premise: this git runs a clean filter; report this, do not skip"

    probe = _plain_repo(tmp_path / "probe")
    marker = tmp_path / "probe-marker.txt"
    fake = _FakeTests(lambda: _set_filter(probe, marker))  # the code under test: runs after the baseline
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)

    result = await _build(probe, [_create(NEW, "ok = 1\n")], run_tests=True)
    ran = marker.exists()  # read at once: no other git command of the test comes first

    assert fake.runs == 1, "premise: the filter was planted inside the build, after the baseline"
    assert _git(probe, "config", "--get", "filter.bf904a.clean").returncode == 0, "premise: the entry is in the config"
    assert result.success is False, result.error
    assert "filter.bf904a.clean" in result.error, f"the key is named: {result.error}"
    assert not result.commit_hash
    assert "bf904a-filter-command" not in result.error, "the value never leaves memory: not in the error"
    assert all("bf904a-filter-command" not in record.getMessage() for record in caplog.records), (
        "nor in any log record: " + " | ".join(record.getMessage() for record in caplog.records)
    )
    assert ran is False, "the filter never ran: no git add, commit or checkout was run after the plant"


# ---------------------------------------------------------------------------
# P1: no pin from the caller
# ---------------------------------------------------------------------------


async def test_an_unpinned_build_is_pinned_at_entry_and_refuses_a_rewritten_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocks = [_create(NEW, "ok = 1\n"), _whole(TARGET, "x = 2\n", base=ORIGINAL)]

    # control, first (fresh fixture): with nothing rewritten the same unpinned build commits
    _cb, _cv, control_wt = _linked_worktree(tmp_path / "control")
    monkeypatch.setattr(builder_module, "_run_targeted_tests", _FakeTests())
    control = await _build(control_wt, blocks, run_tests=True)
    assert control.success and control.commit_hash, f"control: the unpinned build commits when nothing changes: {control.error}"
    assert _blob(control_wt, control.branch_name, NEW) == "ok = 1\n"

    base, victim, wt = _linked_worktree(tmp_path / "probe")
    git_dir_before = _git_dir(wt)
    victim_before, base_commits = _repo_state(victim), _commit_count(base)
    fake = _FakeTests(lambda: _repoint(wt, victim))  # the tests ran arbitrary code: it rewrote the worktree's .git pointer
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)

    result = await _build(wt, blocks, run_tests=True)

    assert fake.runs == 1, "premise: the pointer was rewritten inside the build"
    assert _git_dir(wt) != git_dir_before, "premise: the swap really moved the repository git resolves for the tree"
    assert result.tests_passed, "the tests passed: the refusal is the identity check's"
    assert result.success is False and "identity" in result.error.lower(), result.error
    assert not result.commit_hash
    assert _repo_state(victim) == victim_before, "no commit, branch or staged file in the foreign repository"
    assert _commit_count(base) == base_commits, "no commit in the original repository either"


# ---------------------------------------------------------------------------
# A1: the worktree manager
# ---------------------------------------------------------------------------


async def _adoptable(root: Path) -> tuple[Path, WorktreeManager, Any, str]:
    """A repository, a manager worktree of it, and in that worktree a branch ``EXEC_BRANCH`` with one commit
    (made with plain git, before any hook exists). Returns ``(base, manager, info, commit)``."""
    base = _plain_repo(root / "base")
    manager = WorktreeManager(repo_root=str(base), worktree_base=str(root / "wts"))
    info = await _bounded(manager.create(BUILD_ID))
    return base, manager, info, _commit_on_branch(Path(info.path), EXEC_BRANCH)


async def test_adopt_commit_runs_no_repository_hook(tmp_path: Path) -> None:
    names = ("post-checkout", "post-merge", "reference-transaction")

    # premise, first (sibling fixture built the same way, plain git): the three hooks run at the three steps of the adoption
    sibling_base, _manager, sibling_info, _commit = await _adoptable(tmp_path / "sibling")
    sibling_marker = tmp_path / "sibling-marker.txt"
    for name in names:
        _plant_hook(_common_dir(sibling_base) / "hooks", name, sibling_marker)
    sibling_wt = Path(sibling_info.path)
    assert _git(sibling_wt, "checkout", sibling_info.branch).returncode == 0, "premise: plain git checks out the branch"
    assert _git(sibling_wt, "merge", "--ff-only", EXEC_BRANCH).returncode == 0, "premise: plain git fast-forwards"
    assert _git(sibling_wt, "branch", "-D", EXEC_BRANCH).returncode == 0, "premise: plain git deletes the branch"
    seen = _ran(sibling_marker)
    assert set(names) <= seen, f"premise: this git must run planted hooks under plain git (ran: {sorted(seen)}); report this, do not skip"

    # probe: the hooks sit in the common hooks directory the tested worktree shares
    base, manager, info, commit = await _adoptable(tmp_path / "probe")
    marker = tmp_path / "probe-marker.txt"
    for name in names:
        _plant_hook(_common_dir(base) / "hooks", name, marker)
    assert not marker.exists(), "premise: planting a hook runs nothing"

    adopted = await _bounded(manager.adopt_commit(BUILD_ID, EXEC_BRANCH))
    ran = _ran(marker)  # read at once: no other git command of the test comes first

    assert adopted == (True, commit), f"the adoption lands the commit: {adopted}"
    assert ran == set(), f"no planted hook ran at the adoption's checkout, merge or branch delete (ran: {sorted(ran)})"
    assert not marker.exists()
    assert _out(Path(info.path), "rev-parse", f"refs/heads/{info.branch}") == commit, "the manager's branch holds the commit"


# ---------------------------------------------------------------------------
# E1: every git process of the pipeline
# ---------------------------------------------------------------------------


async def test_every_git_process_of_the_pipeline_carries_both_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_run, real_exec = subprocess.run, asyncio.create_subprocess_exec  # captured BEFORE anything is patched

    # every fixture first: a recorder must not see the test's own setup
    committed_repo = _plain_repo(tmp_path / "committed")
    failed_repo = _plain_repo(tmp_path / "failed")
    manager_repo = _plain_repo(tmp_path / "manager")
    manager = WorktreeManager(repo_root=str(manager_repo), worktree_base=str(tmp_path / "wts"))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", _FakeTests())

    recorded: list[list[str]] = []

    def run_recorder(argv: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(argv, (list, tuple)) and argv and argv[0] == "git":
            recorded.append([str(part) for part in argv])  # subprocess.run takes the argv as one list
        return real_run(argv, *args, **kwargs)

    async def exec_recorder(*argv: Any, **kwargs: Any) -> Any:
        if argv and argv[0] == "git":
            recorded.append([str(part) for part in argv])  # create_subprocess_exec takes it as positional arguments
        return await real_exec(*argv, **kwargs)

    monkeypatch.setattr(builder_module.subprocess, "run", run_recorder)
    monkeypatch.setattr(builder_module.asyncio, "create_subprocess_exec", exec_recorder)

    committed = await _build(committed_repo, [_create(NEW, "ok = 1\n")], run_tests=True)
    failed = await _build(failed_repo, [_create(BAD, BROKEN)])
    info = await _bounded(manager.create(BUILD_ID))
    _commit_on_branch(Path(info.path), EXEC_BRANCH)  # plain git through the real runner: never recorded
    adopted = await _bounded(manager.adopt_commit(BUILD_ID, EXEC_BRANCH))
    removed = await _bounded(manager.remove(BUILD_ID))

    assert committed.success and committed.commit_hash, f"premise: a real build committed: {committed.error}"
    assert failed.success is False and not failed.commit_hash and "Syntax errors" in failed.error, (
        f"premise: a real build failed at the syntax check and cleaned up: {failed.error}"
    )
    assert adopted[0] is True and removed is True, f"premise: the manager created, adopted and removed: {adopted}, {removed}"
    verbs = {_verb(argv) for argv in recorded}
    wanted = {"rev-parse", "status", "config", "checkout", "add", "commit", "branch", "worktree", "merge"}
    assert wanted <= verbs, f"premise: the pipeline's git verbs seen lack {sorted(wanted - verbs)} (seen: {sorted(verbs)})"
    assert HARDENED_GIT_CONFIG_ARGS == ("-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false")
    bare = [argv[:7] for argv in recorded if argv[1:5] != list(HARDENED_GIT_CONFIG_ARGS)]
    assert bare == [], f"{len(bare)} of {len(recorded)} git processes lack the hardening options, e.g. {bare[:3]}"


# ---------------------------------------------------------------------------
# BF-904a A1: a bounded off-loop hooks listing, a lossless config comparison, escaped names, a fail-closed capture
# ---------------------------------------------------------------------------


def _stat_as(real: os.stat_result, mode: int) -> os.stat_result:
    """*real* with st_mode replaced: the seam that stands for a pipe, a link or other mode bits on any OS."""
    return os.stat_result((mode,) + tuple(real)[1:10])


class _ListingSeam:
    """Answers os.lstat / os.readlink / os.fstat for named hook entries and records each open, read and close.
    A FIFO, a device and a symlink are not creatable portably (Windows), so a real regular file stands in.
    BF-904a A2: ``_name`` is a pure string comparison against forms computed before ``install``; no installed function
    resolves a path (the guard makes ``Path.resolve`` and ``os.path.realpath`` raise while one runs)."""

    def __init__(self, hooks_dir: Path) -> None:
        self.hooks_dir = hooks_dir.resolve()
        self._forms = _dir_forms(hooks_dir)
        self.guard = _ResolveGuard()
        self.modes: dict[str, int] = {}
        self.links: dict[str, str] = {}
        self.fstat_modes: dict[str, int] = {}
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.reads: list[int] = []
        self._fds: dict[int, str] = {}

    def _name(self, path: Any) -> str | None:
        return _lexical_parent_in(path, self._forms)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = {name: getattr(os, name) for name in ("lstat", "readlink", "open", "fstat", "read", "close")}
        seam = self

        def lstat(path: Any, *a: Any, **k: Any) -> os.stat_result:
            with seam.guard.scope():
                st, name = real["lstat"](path, *a, **k), seam._name(path)
                return _stat_as(st, seam.modes[name]) if name in seam.modes else st

        def readlink(path: Any, *a: Any, **k: Any) -> str:
            with seam.guard.scope():
                name = seam._name(path)
                return seam.links[name] if name in seam.links else real["readlink"](path, *a, **k)

        def open_(path: Any, *a: Any, **k: Any) -> int:
            with seam.guard.scope():
                fd, name = real["open"](path, *a, **k), seam._name(path)
                if name is not None:
                    seam.opened.append(name)
                    seam._fds[fd] = name
                return fd

        def fstat(fd: int, *a: Any, **k: Any) -> os.stat_result:
            with seam.guard.scope():
                st, name = real["fstat"](fd, *a, **k), seam._fds.get(fd)
                return _stat_as(st, seam.fstat_modes[name]) if name in seam.fstat_modes else st

        def read(fd: int, n: int, *a: Any, **k: Any) -> bytes:
            with seam.guard.scope():
                if fd in seam._fds:
                    seam.reads.append(n)
                return real["read"](fd, n, *a, **k)

        def close(fd: int, *a: Any, **k: Any) -> None:
            with seam.guard.scope():
                name = seam._fds.pop(fd, None)
                if name is not None:
                    seam.closed.append(name)
                return real["close"](fd, *a, **k)

        seam.guard.install(monkeypatch)
        for name, fn in (("lstat", lstat), ("readlink", readlink), ("open", open_), ("fstat", fstat), ("read", read), ("close", close)):
            monkeypatch.setattr(os, name, fn)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_the_hooks_listing_records_each_entry_kind_and_opens_only_regular_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_bytes(b"a")
    (hooks / "pre-push").write_bytes(b"b")
    (hooks / "post-merge").write_bytes(b"")
    (hooks / "sub").mkdir()
    seam = _ListingSeam(hooks)
    seam.modes = {"pre-commit": stat.S_IFREG | 0o644, "pre-push": stat.S_IFLNK | 0o777, "post-merge": stat.S_IFIFO | 0o644}
    seam.links = {"pre-push": "target-a"}
    seam.install(monkeypatch)

    first = builder_module._hooks_listing(hooks)

    assert first == (
        ("post-merge", f"other:{stat.S_IFIFO:o}"),
        ("pre-commit", "file:644:" + _sha(b"a")),
        ("pre-push", "link:target-a"),
        ("sub", "dir"),
    )
    assert seam.opened == ["pre-commit"], "only a regular file is opened: a link, a pipe and a directory are not"
    assert seam.closed == ["pre-commit"]

    seam.links["pre-push"] = "target-b"  # a re-pointed link
    second = builder_module._hooks_listing(hooks)
    assert second is not None and first is not None
    assert {item for item in set(second) ^ set(first)} == {("pre-push", "link:target-a"), ("pre-push", "link:target-b")}
    assert dict(second)["pre-push"] == "link:target-b"

    seam.links["pre-push"] = "target-a"
    seam.modes["pre-commit"] = stat.S_IFREG | 0o755  # a chmod makes a present file run
    third = builder_module._hooks_listing(hooks)
    assert third is not None
    changed = {name for name, _token in set(third) ^ set(first)}
    assert changed == {"pre-commit"}
    assert dict(third)["pre-commit"].startswith("file:755:")


def test_an_entry_no_longer_regular_when_opened_fails_the_listing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_bytes(b"a")
    seam = _ListingSeam(hooks)
    seam.install(monkeypatch)
    assert builder_module._hooks_listing(hooks) is not None, "control: a regular file lists"

    seam.opened.clear()
    seam.closed.clear()
    seam.fstat_modes = {"pre-commit": stat.S_IFIFO | 0o644}  # swapped for a pipe after the lstat

    assert builder_module._hooks_listing(hooks) is None
    assert seam.opened == ["pre-commit"]
    assert seam.closed == ["pre-commit"], "the descriptor is closed"


@pytest.mark.parametrize("bound", ["entries", "bytes"])
def test_the_hooks_listing_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bound: str) -> None:
    assert (
        builder_module._HOOKS_MAX_ENTRIES,
        builder_module._HOOKS_MAX_TOTAL_BYTES,
        builder_module._HOOKS_READ_CHUNK,
        builder_module._GIT_CONFIG_LISTING_MAX_CHARS,
    ) == (256, 64 * 1024 * 1024, 64 * 1024, 4 * 1024 * 1024)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    if bound == "entries":
        monkeypatch.setattr(builder_module, "_HOOKS_MAX_ENTRIES", 3)
        for name in ("a", "b", "c"):
            (hooks / name).write_bytes(b"")
        listing = builder_module._hooks_listing(hooks)
        assert listing is not None and len(listing) == 3
        (hooks / "d").write_bytes(b"")
        assert builder_module._hooks_listing(hooks) is None
    else:
        monkeypatch.setattr(builder_module, "_HOOKS_MAX_TOTAL_BYTES", 100)
        monkeypatch.setattr(builder_module, "_HOOKS_READ_CHUNK", 16)
        (hooks / "a").write_bytes(b"x" * 50)
        (hooks / "b").write_bytes(b"y" * 50)
        seam = _ListingSeam(hooks)
        seam.install(monkeypatch)
        assert builder_module._hooks_listing(hooks) is not None
        assert seam.reads, "premise: the file bytes were read through os.read"
        assert set(seam.reads) == {16}, f"every read asks for one chunk: {seam.reads}"
        with (hooks / "b").open("ab") as handle:
            handle.write(b"z")
        assert builder_module._hooks_listing(hooks) is None


async def test_the_hooks_listing_runs_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loop_thread = threading.get_ident()
    threads: list[int] = []
    real = builder_module._hooks_listing

    def recorder(hooks_dir: Path | None) -> Any:
        threads.append(threading.get_ident())
        return real(hooks_dir)

    monkeypatch.setattr(builder_module, "_hooks_listing", recorder)
    repo = _plain_repo(tmp_path / "repo")
    monkeypatch.setattr(builder_module, "_run_targeted_tests", _FakeTests())

    result = await _build(repo, [_create(NEW, "ok = 1\n")], run_tests=True)

    assert result.success and result.commit_hash, f"the build commits: {result.error}"
    assert len(threads) == 2, f"the listing ran at the baseline and at the comparison: {threads}"
    assert loop_thread not in threads, "the listing never ran on the event loop's thread"


@pytest.mark.parametrize("case", ["config-before", "config-after", "entries-before", "entries-after", "bytes-after"])
async def test_a_capture_past_a_bound_refuses_the_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    probe = _plain_repo(tmp_path / "probe")
    hooks = _common_dir(probe) / "hooks"
    rc, listing, _err = await builder_module._run_git(list(CONFIG_ARGS), str(probe), lossless=True)
    assert rc == 0, "premise: the config listing reads"
    n_cfg = len(listing)
    n_ent = len(os.listdir(hooks))
    n_bytes = sum(item.stat().st_size for item in hooks.iterdir() if item.is_file())
    assert n_ent >= 1, "premise: git init wrote hook samples"
    model_code: Callable[[], None] | None = None
    if case == "config-before":
        monkeypatch.setattr(builder_module, "_GIT_CONFIG_LISTING_MAX_CHARS", n_cfg - 1)
    elif case == "config-after":
        monkeypatch.setattr(builder_module, "_GIT_CONFIG_LISTING_MAX_CHARS", n_cfg)
        model_code = lambda: _out(probe, "config", "bf904a.grow", "1")  # noqa: E731
    elif case == "entries-before":
        monkeypatch.setattr(builder_module, "_HOOKS_MAX_ENTRIES", n_ent - 1)
    elif case == "entries-after":
        monkeypatch.setattr(builder_module, "_HOOKS_MAX_ENTRIES", n_ent)
        model_code = lambda: (hooks / "extra.sample").write_bytes(b"x")  # noqa: E731
    else:
        monkeypatch.setattr(builder_module, "_HOOKS_MAX_TOTAL_BYTES", n_bytes)
        sample = next(item for item in sorted(hooks.iterdir()) if item.is_file())

        def grow() -> None:
            with sample.open("ab") as handle:
                handle.write(b"x")

        model_code = grow
    fake = _FakeTests(model_code)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)

    result = await _build(probe, [_create(NEW, "ok = 1\n")], run_tests=True)

    assert result.success is False and not result.commit_hash, result.error
    assert fake.runs == 1, "premise: the test phase ran"
    if case.endswith("-before"):
        assert "could not be read before the tests" in result.error, result.error
    elif case == "config-after":
        assert "could not be read after the tests" in result.error, result.error
    else:
        assert "the hooks directory" in result.error and "could not be read" in result.error, result.error
        assert "before the tests" not in result.error, result.error


def _append_config(repo: Path, data: bytes) -> None:
    with (_common_dir(repo) / "config").open("ab") as handle:
        handle.write(data)


def _rewrite_config_byte(repo: Path, old: bytes, new: bytes) -> None:
    config = _common_dir(repo) / "config"
    config.write_bytes(config.read_bytes().replace(old, new))


async def test_a_config_value_that_differs_only_in_undecodable_bytes_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocks = [_create(NEW, "ok = 1\n")]

    # premise, first (sibling repository): the lossy default cannot tell the two values apart, the lossless read can
    sibling = _plain_repo(tmp_path / "sibling")
    _append_config(sibling, b"[bf904a]\n\tkey = \x80\n")
    rc_a, text_a, _e = await builder_module._run_git(list(CONFIG_ARGS), str(sibling))
    rc_la, lossless_a, _e = await builder_module._run_git(list(CONFIG_ARGS), str(sibling), lossless=True)
    _rewrite_config_byte(sibling, b"\x80", b"\x81")
    rc_b, text_b, _e = await builder_module._run_git(list(CONFIG_ARGS), str(sibling))
    rc_lb, lossless_b, _e = await builder_module._run_git(list(CONFIG_ARGS), str(sibling), lossless=True)
    assert rc_a == rc_la == rc_b == rc_lb == 0, "premise: git lists a config value of undecodable bytes"
    assert text_a == text_b, "premise: the lossy default decoding collides on this git"
    assert lossless_a != lossless_b, "premise: the lossless reads differ"

    # control, first (fresh repository with the \x80 config, unchanged): a non-UTF-8 config is no false positive
    control_repo = _plain_repo(tmp_path / "control")
    _append_config(control_repo, b"[bf904a]\n\tkey = \x80\n")
    monkeypatch.setattr(builder_module, "_run_targeted_tests", _FakeTests())
    control = await _build(control_repo, blocks, run_tests=True)
    assert control.success and control.commit_hash, f"control: the config is unchanged, the build commits: {control.error}"

    probe = _plain_repo(tmp_path / "probe")
    _append_config(probe, b"[bf904a]\n\tkey = \x80\n")
    fake = _FakeTests(lambda: _rewrite_config_byte(probe, b"\x80", b"\x81"))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)

    result = await _build(probe, blocks, run_tests=True)

    assert fake.runs == 1, "premise: the value was rewritten inside the build"
    assert result.success is False, result.error
    for needle in (REFUSAL, "bf904a.key", "`"):
        assert needle in result.error, f"{needle!r} must be in the error: {result.error}"
    assert "\ufffd" not in result.error
    result.error.encode("utf-8")  # no lone surrogate reaches the message


def test_display_tokens_are_escaped_bounded_and_markdown_literal() -> None:
    token = builder_module._display_token
    assert token("a\nb\rc\x1bd\u202ee\udc80f`g\\h*_[x](y)<z>", 100) == "`a\\x0ab\\x0dc\\x1bd\\u202ee\\udc80f\\x60g\\\\h*_[x](y)<z>`"
    assert token("k" * 20013, 100) == "`" + "k" * 100 + "` ...[19913 more characters]"
    assert token("k" * 99 + "\x1b" + "z", 100) == "`" + "k" * 99 + "` ...[2 more characters]", "an escape is never split"
    assert token("k" * 100, 100) == "`" + "k" * 100 + "`"
    assert token("\U0001f600\U000e0001", 100) == "`\U0001f600\\U000e0001`"

    before = "file:c\0a.b\nv\0"
    after = before + "".join(f"file:c\0z.k{i:02d}\nv\0" for i in range(12))
    shown = builder_module._config_change_names(before, after)
    assert shown.endswith(", ...[2 more])")
    assert shown.count("`file:c`") == 10

    snapshot = builder_module._GitSafetySnapshot(config="file:x\0user.password\nsecret-value\0", hooks_dir=None, hooks=())
    assert "secret-value" not in repr(snapshot)


async def test_hostile_config_and_hook_names_reach_no_message_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    hostile = b'[bf904a "a\rb\x1bc\x80\xe2\x80\xae`' + b"s" * 20000 + b'"]\n\tkey = v\n'

    # premise, first (sibling repository, plain git): git lists this subsection, with its CR and ESC raw
    sibling = _plain_repo(tmp_path / "sibling")
    _append_config(sibling, hostile)
    plain = _REAL_RUN(
        ["git", "config", "--list", "-z"], cwd=sibling, capture_output=True, env=_control_env(),
        stdin=subprocess.DEVNULL, timeout=60, check=False,
    )
    assert plain.returncode == 0, f"premise: plain git lists the hostile subsection: {plain.stderr!r}"
    assert b"\x1b" in plain.stdout and b"\r" in plain.stdout, "premise: the control characters reach the listing raw"

    probe = _plain_repo(tmp_path / "probe")
    hooks = _common_dir(probe) / "hooks"

    def plant() -> None:
        _append_config(probe, hostile)
        (hooks / ("h" * 120)).write_bytes(b"#!/bin/sh\n")

    fake = _FakeTests(plant)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)

    result = await _build(probe, [_create(NEW, "ok = 1\n")], run_tests=True)

    assert fake.runs == 1, "premise: the plant ran inside the build"
    assert result.success is False, result.error
    assert REFUSAL in result.error, result.error
    assert all(ch.isprintable() for ch in result.error), "no control character reaches the error"
    assert len(result.error) < 6000, len(result.error)
    for needle in ("\\x0d", "\\x1b", "\\udc80", "\\u202e", "\\x60", "h" * 100):
        assert needle in result.error, f"{needle!r} must be in the error: {result.error[:600]}"
    assert "s" * 101 not in result.error and "h" * 101 not in result.error
    [record] = [r for r in caplog.records if "git configuration or hooks changed" in r.getMessage()]
    rendered = LogRedactionFormatter("%(message)s").format(record)
    assert "\r" not in rendered and "\n" not in rendered and "\x1b" not in rendered
    assert all(ch.isprintable() for ch in rendered)


class _CommonDirAnswers:
    """Wraps the real ``_run_git``: ``rev-parse --git-common-dir`` gets the given outcome; everything else runs for real."""

    def __init__(self, real: Any, outcome: tuple[int, str, str]) -> None:
        self._real = real
        self._outcome = outcome
        self.asked = 0

    async def __call__(self, args: list[str], work_dir: str, **kwargs: Any) -> tuple[int, str, str]:
        if args == ["rev-parse", "--git-common-dir"]:
            self.asked += 1
            return self._outcome
        return await self._real(args, work_dir, **kwargs)


@pytest.mark.parametrize("case", ["nonzero", "empty", "unproven"])
async def test_a_hooks_location_git_does_not_name_is_a_failed_capture_in_a_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    blocks = [_create(NEW, "ok = 1\n")]

    # control, first: the same build with no wrapper commits
    control_repo = _plain_repo(tmp_path / "control")
    monkeypatch.setattr(builder_module, "_run_targeted_tests", _FakeTests())
    control = await _build(control_repo, blocks, run_tests=True)
    assert control.success and control.commit_hash, f"control: with every read answering, the build commits: {control.error}"

    probe = _plain_repo(tmp_path / "probe")
    outcome = (0, "", "") if case == "empty" else (128, "", "fatal: bf904a")
    wrapper = _CommonDirAnswers(builder_module._run_git, outcome)
    monkeypatch.setattr(builder_module, "_run_git", wrapper)
    if case == "unproven":
        monkeypatch.setattr(builder_module, "repository_identity", AsyncMock(return_value=None))  # no pin: D5 applies

    result = await _build(probe, blocks, run_tests=True)

    assert wrapper.asked == 1, "premise: the hooks location was asked for once"
    if case == "unproven":
        assert result.success and result.commit_hash, f"no repository was shown at entry: the build commits: {result.error}"
    else:
        assert result.success is False and not result.commit_hash, result.error
        assert "could not be read before the tests" in result.error, result.error


@pytest.mark.parametrize("raised", ["error", "cancel"])
async def test_an_error_or_cancellation_after_the_test_phase_began_runs_no_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raised: str
) -> None:
    blocks = [_create(NEW, "ok = 1\n")]
    real_run_git = builder_module._run_git

    # control, first: with the real comparison the build commits and the checkout goes back to main
    control_repo = _plain_repo(tmp_path / "control")
    control_spy = _GitSpy(real_run_git)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", _FakeTests(lambda: setattr(control_spy, "swapped", True)))
    monkeypatch.setattr(builder_module, "_run_git", control_spy)
    control = await _build(control_repo, blocks, run_tests=True)
    assert control.success and control.commit_hash, f"control: the build commits: {control.error}"
    assert ["checkout", "main"] in control_spy.args_after_swap(), "control: the checkout back runs when git is safe"
    assert _out(control_repo, "symbolic-ref", "--short", "HEAD") == "main"

    probe = _plain_repo(tmp_path / "probe")
    spy = _GitSpy(real_run_git)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", _FakeTests(lambda: setattr(spy, "swapped", True)))
    monkeypatch.setattr(builder_module, "_run_git", spy)

    async def injected(work_dir: str, before: Any) -> str | None:
        if raised == "error":
            raise RuntimeError("bf904a-injected")
        raise asyncio.CancelledError()

    monkeypatch.setattr(builder_module, "_git_safety_change", injected)

    if raised == "error":
        result = await _build(probe, blocks, run_tests=True)
        assert result.success is False and "bf904a-injected" in result.error, result.error
        build_branch = result.branch_name
    else:
        task = asyncio.create_task(execute_approved_build(blocks, _spec(), str(probe), run_tests=True))
        await asyncio.wait({task}, timeout=120)
        assert task.cancelled(), "premise: the injected cancellation ended the build"
        build_branch = next(args[2] for args in spy.args_before_swap() if args[:2] == ["checkout", "-b"])

    assert spy.args_after_swap() == [IDENTITY_ARGS], "after the test phase began: the identity re-read only, no checkout or branch delete"
    assert _out(probe, "symbolic-ref", "--short", "HEAD") == build_branch, "the checkout is left on the build branch"
    assert not (probe / NEW).exists(), "the file this build created is unlinked, with no git"


@pytest.mark.parametrize("case", ["hook-files", "unreadable-directory"])
async def test_a_hostile_hooks_path_reaches_the_refusal_only_as_an_escaped_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    blocks = [_create(NEW, "ok = 1\n")]
    bidi = "\u202e"  # a bidi override: a valid file name on NTFS and on POSIX

    # control, first (fresh repository, ordinary name, nothing planted): the build commits
    control_repo = _plain_repo(tmp_path / "control")
    monkeypatch.setattr(builder_module, "_run_targeted_tests", _FakeTests())
    control = await _build(control_repo, blocks, run_tests=True)
    assert control.success and control.commit_hash, f"control: nothing changed, the build commits: {control.error}"

    # premise: the repository path carries the character and plain git works there
    probe = _plain_repo(tmp_path / f"rep{bidi}o")
    hooks = _common_dir(probe) / "hooks"
    assert bidi in str(probe) and bidi in str(hooks), "premise: the hooks path contains the bidi override"
    assert _git(probe, "status", "--porcelain").returncode == 0, "premise: plain git status works in that directory"
    n_ent = len(os.listdir(hooks))
    assert n_ent >= 1, "premise: git init wrote hook samples"
    if case == "hook-files":
        plant = lambda: (hooks / "post-checkout").write_bytes(b"#!/bin/sh\n")  # noqa: E731
    else:
        monkeypatch.setattr(builder_module, "_HOOKS_MAX_ENTRIES", n_ent)
        plant = lambda: (hooks / "extra.sample").write_bytes(b"x")  # noqa: E731
    fake = _FakeTests(plant)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)

    result = await _build(probe, blocks, run_tests=True)

    assert fake.runs == 1, "premise: the plant ran inside the build"
    assert result.success is False, result.error
    assert REFUSAL in result.error, result.error
    assert "\\u202e" in result.error, f"the override is escaped: {result.error}"
    assert bidi not in result.error, "the raw override never reaches the error"
    assert all(ch.isprintable() for ch in result.error), "no unprintable character reaches the error"
    if case == "hook-files":
        assert "post-checkout" in result.error, result.error
        assert "hook files in `" in result.error, "the hooks path is one code-span token"
    else:
        assert "the hooks directory `" in result.error, "the hooks path is one code-span token"
        assert "could not be read" in result.error, result.error


async def test_more_than_ten_changed_hook_names_are_counted_not_listed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocks = [_create(NEW, "ok = 1\n")]

    # control, first (fresh repository, nothing planted): the build commits
    control_repo = _plain_repo(tmp_path / "control")
    monkeypatch.setattr(builder_module, "_run_targeted_tests", _FakeTests())
    control = await _build(control_repo, blocks, run_tests=True)
    assert control.success and control.commit_hash, f"control: nothing changed, the build commits: {control.error}"

    probe = _plain_repo(tmp_path / "probe")
    hooks = _common_dir(probe) / "hooks"
    names = [f"hook-{index:02d}" for index in range(12)]

    def plant() -> None:
        for name in names:
            (hooks / name).write_bytes(b"#!/bin/sh\n")

    fake = _FakeTests(plant)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)

    result = await _build(probe, blocks, run_tests=True)

    assert fake.runs == 1, "premise: the plant ran inside the build"
    assert all((hooks / name).is_file() for name in names), "premise: 12 hook files exist after the tests"
    assert result.success is False, result.error
    assert REFUSAL in result.error, result.error
    assert result.error.count("`hook-") == 10, result.error
    assert "...[2 more]" in result.error, result.error
    assert "hook-11" not in result.error, "the names sort: only the first ten are shown"


# ---------------------------------------------------------------------------
# BF-904a A2 (N13): a hooks directory whose name ends in whitespace is read byte-exactly
# ---------------------------------------------------------------------------

WHITESPACE_NAMED = "admin\u00a0"  # a nonbreaking space ends the directory name; str.strip() removes it, git keeps it


def _remove_whitespace_named_dir(path: Path) -> None:
    """Remove *path* (its name ends in whitespace): an ordinary Windows path cannot name it, the extended-length form can."""

    def make_writable(func: Callable[[str], Any], failing: str, _exc: BaseException) -> None:
        os.chmod(failing, stat.S_IWRITE)  # git's object files are read-only on Windows
        func(failing)

    target = "\\\\?\\" + str(path.absolute()) if sys.platform == "win32" else str(path)
    if os.path.exists(target):
        shutil.rmtree(target, onexc=make_writable)


def _whitespace_named_repo(root: Path, layout: str, request: pytest.FixtureRequest) -> tuple[Path, Path]:
    """``(admin, build_dir)``: a repository whose separate git directory ``admin`` ends in a nonbreaking space; the build
    directory is its work tree, or (``linked-worktree-of-it``) a linked worktree of it. A finalizer removes ``admin``."""
    root.mkdir(parents=True)
    admin, work = root / WHITESPACE_NAMED, root / "work"
    request.addfinalizer(lambda: _remove_whitespace_named_dir(admin))
    made = _git(root, "init", "-q", "-b", "main", "--separate-git-dir", str(admin), str(work))
    assert made.returncode == 0, f"premise: git init --separate-git-dir must succeed: {made.stderr}"
    for args in (
        ("config", "user.email", "bf904a@example.invalid"),
        ("config", "user.name", "BF904a Tester"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.autocrlf", "false"),
    ):
        assert _git(work, *args).returncode == 0, f"premise: git {args[0]} must succeed"
    for rel, text in SEED.items():
        target = work / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    assert _git(work, "add", "-A").returncode == 0, "premise: git add must succeed"
    assert _git(work, "commit", "-q", "--allow-empty", "-m", "seed").returncode == 0, "premise: the seed commit"
    if layout == "separate-git-dir":
        return admin, work
    linked = root / "wt"
    assert _git(work, "worktree", "add", "-q", "-b", "wt", str(linked)).returncode == 0, "premise: git worktree add"
    return admin, linked


@pytest.mark.parametrize("layout", ["separate-git-dir", "linked-worktree-of-it"])
async def test_a_hooks_directory_whose_name_ends_in_whitespace_is_watched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest, layout: str
) -> None:
    blocks = [_create(NEW, "ok = 1\n")]

    # premises, first (sibling pair, plain git, raw bytes): git names the directory WITH the trailing character and
    # one newline; the stripped text names a directory that does not exist, the exact text one that does
    sibling_admin, sibling_dir = _whitespace_named_repo(tmp_path / "sibling", layout, request)
    asked = _REAL_RUN(
        ["git", "rev-parse", "--git-common-dir"], cwd=sibling_dir, capture_output=True, env=_control_env(),
        stdin=subprocess.DEVNULL, timeout=60, check=False,
    )
    assert asked.returncode == 0, f"premise: git names the common directory: {asked.stderr!r}"
    assert asked.stdout.endswith(WHITESPACE_NAMED.encode("utf-8") + b"\n"), f"premise: git's answer ends with the character and one LF: {asked.stdout!r}"
    named = asked.stdout.decode("utf-8")
    assert not os.path.exists(Path(sibling_dir, named.strip())), "premise: the stripped text names a directory that does not exist"
    assert os.path.exists(Path(sibling_dir, named.removesuffix("\n"))), "premise: the exact text names the directory"
    sibling_hooks = sibling_admin / "hooks"
    assert sibling_hooks.is_dir() and any(sibling_hooks.iterdir()), "premise: the hooks directory exists and holds entries"

    # control, first (a fresh pair, nothing planted): the build commits
    _control_admin, control_dir = _whitespace_named_repo(tmp_path / "control", layout, request)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", _FakeTests())
    control = await _build(control_dir, blocks, run_tests=True)
    assert control.success and control.commit_hash, f"control: nothing planted, the build commits: {control.error}"

    admin, probe_dir = _whitespace_named_repo(tmp_path / "probe", layout, request)
    marker = tmp_path / "probe-marker.txt"
    fake = _FakeTests(lambda: _plant_hook(admin / "hooks", "post-checkout", marker))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", fake)

    result = await _build(probe_dir, blocks, run_tests=True)

    assert fake.runs == 1 and (admin / "hooks" / "post-checkout").exists(), "premise: the hook was planted during the tests"
    assert result.success is False, result.error
    for needle in (REFUSAL, "post-checkout"):
        assert needle in result.error, f"{needle!r} must be in the error: {result.error}"
    assert not result.commit_hash
    assert not marker.exists(), "no planted hook ran"
