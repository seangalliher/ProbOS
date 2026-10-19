"""BF-897 (#1559): the build pipeline refuses to execute or merge in the operator's checkout.

The refusals compare locations and assume the runtime's environment sets no git repository-location variable. Two
injected-only limits are recorded on #1523 (F-118: an inherited ``GIT_DIR`` reaching ``WorktreeManager``; F-119: a
``.git`` pointer file or junction to the checkout's git directory passes the guard); no test below claims otherwise.

Milestone M1-A, the real-git tests. Every repository here is a real temporary one, created with
``git init -b main`` and a repo-local identity. Each refusal is proven twice, by its message and
by a snapshot of the "operator's checkout" taken before and after: branch, HEAD, ``main``,
``status --porcelain``, the bytes of the uncommitted edit and of the untracked file, the stash
list and every branch tip. The snapshot is the data-integrity assertion; a message alone would
pass a guard that ran after the damage.

The shared premise, "the operator's checkout" (``op``): a repository on branch ``captain-work``.
``main`` holds ``src/probos/a.py`` and ``config/system.yaml``. ``captain-work`` is one commit ahead
of ``main`` and that commit touches only ``a.py``, so ``config/system.yaml`` is identical on both
branches: a mutant's ``git checkout main`` succeeds and is observable. ``config/system.yaml``
carries an uncommitted edit and ``notes.txt`` is untracked. ``op_clean`` is the same repository
without those two, so the dirty-tree refusal cannot stand in for the guard under test.

Every path lives under ``tmp_path``; nothing here touches the repository the tests run from.

Milestone M1-C appends two groups. T-C (the test phase) drives ``execute_approved_build`` with its pytest
launch and its git launches replaced by fakes, so no repository is involved: what it proves is which
outcome the test phase reports and what the commit gate does with it. T-B (``/api/build/resolve``) goes
through ``create_app`` and the real router, against the same real "operator's checkout" as above.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.cognitive import builder as builder_module
from probos.cognitive import builder_paths
from probos.cognitive.builder import (
    NO_TARGETED_TESTS,
    TARGETED_TEST_TIMEOUT_S,
    BuilderAgent,
    BuildFailureReport,
    BuildResult,
    BuildSpec,
    _classify_test_run,
    _run_targeted_tests,
    _run_tests,
    execute_approved_build,
)
from probos.cognitive.builder_paths import operator_checkout_refusal
from probos.events import EventType
from probos.routers import build as build_router
from probos.routers.deps import get_runtime
from probos.runtime import ProbOSRuntime
from probos.watch_rotation import NightOrdersManager
from probos.worktree_manager import WorktreeManager

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not found on PATH")

_A = "src/probos/a.py"
_SYSTEM = "config/system.yaml"
_NOTES = "notes.txt"
_NEW = "src/probos/new_mod.py"
_A_V1 = "def a() -> int:\n    return 1\n"
_A_V2 = "def a() -> int:\n    return 2\n"
_A_V3 = "def a() -> int:\n    return 3\n"
_SYSTEM_COMMITTED = "mode: committed\n"
_SYSTEM_EDITED = "mode: edited by the captain\n"
_NOTES_TEXT = "the captain's untracked notes\n"
_NEW_TEXT = "x = 1\n"

# Variables that point a git command at another repository. A gate launched from a git hook
# inherits them, and they would send every git call below (and WorktreeManager's, which passes
# the whole environment) to the repository the tests run from.
_GIT_REDIRECTS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_PREFIX",
    "GIT_NAMESPACE",
)


@pytest.fixture(autouse=True)
def _git_isolated_from_the_runners_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _GIT_REDIRECTS:
        monkeypatch.delenv(name, raising=False)


# -- real git (the helper pattern of tests/test_bf896_dispatcher_confinement_seam.py, copied) ----


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False,
    )


def _out(cwd: Path, *args: str) -> str:
    done = _git(cwd, *args)
    assert done.returncode == 0, f"premise: git {' '.join(args)} failed: {done.stderr}"
    return done.stdout.strip()


def _make_repo(path: Path, files: dict[str, str], branch: str = "main") -> Path:
    """A real repository with one initial commit holding *files* (repo-local identity)."""
    path.mkdir(parents=True)
    for args in (
        ("init", "-q", "-b", branch),
        ("config", "user.email", "bf897@example.invalid"),
        ("config", "user.name", "BF897 Tester"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.autocrlf", "false"),
    ):
        assert _git(path, *args).returncode == 0, f"premise: git {args[0]} must succeed"
    for rel, text in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    _out(path, "add", "--", ".")
    _out(path, "commit", "-q", "-m", "seed")
    return path


def _show(repo: Path, rev: str, rel: str) -> str:
    done = _git(repo, "show", f"{rev}:{rel}")
    assert done.returncode == 0, f"{rel} is not on {rev}: {done.stderr}"
    return done.stdout.replace("\r\n", "\n")


# -- the operator's checkout, its snapshot, linked worktrees -------------------------------------


def _porcelain(repo: Path) -> str:
    """``git status --porcelain=v1 -uall`` with its leading status columns intact (``_out`` strips them)."""
    done = _git(repo, "status", "--porcelain=v1", "-uall")
    assert done.returncode == 0, f"premise: git status failed: {done.stderr}"
    return done.stdout.rstrip("\n")


def _bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def checkout_state(repo: Path) -> dict[str, object]:
    """What the operator can see of their checkout: where it is, what is uncommitted, what is stashed."""
    return {
        "branch": _out(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "head": _out(repo, "rev-parse", "HEAD"),
        "main": _out(repo, "rev-parse", "main"),
        "status": _porcelain(repo),
        "system_yaml": _bytes(repo / _SYSTEM),
        "notes": _bytes(repo / _NOTES),
        "stash": _out(repo, "stash", "list"),
    }


def snapshot(repo: Path) -> dict[str, object]:
    """``checkout_state`` plus every local branch with its tip: a new branch or a moved tip changes it."""
    state = checkout_state(repo)
    heads = _out(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads")
    state["heads"] = sorted(heads.splitlines())
    return state


def _operator_checkout(path: Path, *, dirty: bool) -> Path:
    repo = _make_repo(path, {_A: _A_V1, _SYSTEM: _SYSTEM_COMMITTED})
    _out(repo, "checkout", "-q", "-b", "captain-work")
    (repo / _A).write_text(_A_V2, encoding="utf-8", newline="\n")
    _out(repo, "add", "--", _A)
    _out(repo, "commit", "-q", "-m", "captain work")
    if dirty:
        (repo / _SYSTEM).write_text(_SYSTEM_EDITED, encoding="utf-8", newline="\n")
        (repo / _NOTES).write_text(_NOTES_TEXT, encoding="utf-8", newline="\n")
    return repo


@pytest.fixture
def op(tmp_path: Path) -> Path:
    """The operator's checkout: on captain-work, with an uncommitted edit and an untracked file."""
    return _operator_checkout(tmp_path / "op", dirty=True)


@pytest.fixture
def op_clean(tmp_path: Path) -> Path:
    """The same checkout without the uncommitted edit and the untracked file."""
    return _operator_checkout(tmp_path / "op_clean", dirty=False)


def _assert_operator_premise(repo: Path, *, dirty: bool = True) -> None:
    """The premise every test starts from; a setup that did not discriminate fails here, loudly."""
    assert (repo / ".git").is_dir(), "premise: the operator's checkout keeps its repository in a .git directory"
    assert _out(repo, "rev-parse", "--abbrev-ref", "HEAD") == "captain-work", "premise: the operator is on captain-work"
    assert _out(repo, "rev-list", "--count", "main..captain-work") == "1", "premise: captain-work is one ahead of main"
    assert _out(repo, "diff", "--name-only", "main", "captain-work") == _A, (
        "premise: the captain-work commit touches only a.py, so config/system.yaml is the same on both branches"
    )
    expected = [f" M {_SYSTEM}", f"?? {_NOTES}"] if dirty else []
    assert _porcelain(repo).splitlines() == expected, "premise: the operator's uncommitted work is as described"


def _add_worktree(repo: Path, path: Path, branch: str) -> Path:
    """A real linked worktree of *repo*, on a new branch cut from main."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _out(repo, "worktree", "add", "-q", "-b", branch, str(path), "main")
    assert (path / ".git").is_file(), "premise: a linked worktree's .git is a pointer file"
    return path


def _common_dir(work_tree: Path) -> Path:
    """The repository directory *work_tree* belongs to; the same for every linked worktree of one repository."""
    return Path(work_tree, _out(work_tree, "rev-parse", "--git-common-dir")).resolve()


def _commits_ahead(repo: Path, base: str, branch: str) -> str:
    return _out(repo, "rev-list", "--count", f"{base}..{branch}")


async def _build_in(work_dir: Path | str) -> BuildResult:
    return await execute_approved_build(
        [{"path": _NEW, "mode": "create", "content": _NEW_TEXT}],
        BuildSpec(title="bf897", description="d"),
        str(work_dir),
        run_tests=False,
    )


# ===== T-A1: operator_checkout_refusal (real directories, real `git worktree add`) ===============


@requires_git
def test_refuses_the_operator_checkout_itself(op: Path) -> None:
    _assert_operator_premise(op)

    refusal = operator_checkout_refusal(op, op)

    assert isinstance(refusal, str), "the operator's own checkout was allowed"
    assert "BF-897" in refusal


@requires_git
def test_refuses_a_subdirectory_of_the_operator_checkout(op: Path) -> None:
    _assert_operator_premise(op)
    subdirectory = op / "src"
    dotdot = str(op / "src" / "..")
    assert subdirectory.is_dir(), "premise: src/ exists in the checkout"
    assert os.path.samefile(dotdot, op) and dotdot != str(op), "premise: src/.. is another spelling of the checkout"

    for target in (subdirectory, dotdot):
        refusal = operator_checkout_refusal(target, op)

        assert isinstance(refusal, str), f"{target} is inside the operator's checkout and was allowed"
        assert "BF-897" in refusal


@requires_git
def test_allows_a_linked_worktree_outside_the_checkout(op: Path, tmp_path: Path) -> None:
    _assert_operator_premise(op)
    linked = _add_worktree(op, tmp_path / "wts" / "out", "wt-out")
    assert os.path.samefile(_common_dir(linked), _common_dir(op)), "premise: a linked worktree of the same repository"
    assert not (op.resolve() in linked.resolve().parents), "premise: the worktree is outside the checkout's directory"

    assert operator_checkout_refusal(linked, op) is None


@requires_git
def test_allows_a_linked_worktree_nested_inside_the_checkout(op: Path) -> None:
    _assert_operator_premise(op)
    nested = _add_worktree(op, op / ".wt" / "in", "wt-in")
    assert os.path.samefile(_common_dir(nested), _common_dir(op)), "premise: a linked worktree of the same repository"
    assert op.resolve() in nested.resolve().parents, "premise: the worktree is inside the checkout's directory"
    assert (nested / "src").is_dir(), "premise: the worktree has a src/ to build in"
    assert operator_checkout_refusal(nested.parent, op) is not None, (
        "premise: the directory holding the worktree is part of the operator's checkout; only the worktree's own "
        ".git entry sets its tree apart"
    )

    # Kills M2: walking past the nested worktree's .git entry would reach the operator's and refuse.
    assert operator_checkout_refusal(nested, op) is None
    assert operator_checkout_refusal(nested / "src", op) is None


@requires_git
def test_allows_a_tree_outside_any_checkout(op: Path, tmp_path: Path) -> None:
    _assert_operator_premise(op)
    plain = tmp_path / "plain"
    plain.mkdir()
    assert not os.path.lexists(plain / ".git"), "premise: plain is not a checkout"

    assert operator_checkout_refusal(plain, op) is None


def test_no_checkout_means_nothing_to_protect(tmp_path: Path) -> None:
    no_checkout = tmp_path / "no_checkout"
    no_checkout.mkdir()
    assert not os.path.lexists(no_checkout / ".git"), "premise: the runtime does not run from a checkout"

    assert operator_checkout_refusal(no_checkout, no_checkout) is None


@requires_git
def test_an_unexaminable_path_is_refused(op: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_operator_premise(op)
    linked = _add_worktree(op, tmp_path / "wts" / "out", "wt-out")
    assert operator_checkout_refusal(linked, op) is None, "premise: this tree is allowed while it can be examined"

    def deny(*_args: object, **_kwargs: object) -> bool:
        raise PermissionError("denied by the test")

    monkeypatch.setattr(builder_paths.os.path, "samefile", deny)

    refusal = operator_checkout_refusal(linked, op)

    assert isinstance(refusal, str), "a tree that could not be examined was allowed"
    assert "BF-897" in refusal
    assert "PermissionError" in refusal


# ===== T-A2: execute_approved_build refuses the operator checkout (data integrity) ===============


async def _assert_build_refused_and_checkout_unchanged(
    repo: Path, monkeypatch: pytest.MonkeyPatch, *, dirty: bool,
) -> None:
    _assert_operator_premise(repo, dirty=dirty)
    monkeypatch.setattr(builder_module, "_PROJECT_ROOT", repo)
    before = snapshot(repo)

    for work_dir in (repo, repo / "src"):
        result = await _build_in(work_dir)

        assert result.success is False, f"a build ran in {work_dir}"
        assert "BF-897" in result.error, f"refused, but not by the guard: {result.error}"
        assert not (repo / _NEW).exists()
        assert not list(repo.rglob(Path(_NEW).name)), "the build wrote a file in the operator's checkout"
        assert snapshot(repo) == before, f"the refused build changed the operator's checkout (work_dir={work_dir})"


@requires_git
async def test_execute_refuses_the_operator_checkout_and_leaves_it_unchanged(
    op: Path, op_clean: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _assert_build_refused_and_checkout_unchanged(op, monkeypatch, dirty=True)

    # The clean variant: the dirty-tree refusal cannot stand in for the guard here. Without the
    # guard this build would create a branch, commit and `git checkout main` in the operator's tree.
    await _assert_build_refused_and_checkout_unchanged(op_clean, monkeypatch, dirty=False)


@requires_git
async def test_execute_refusal_runs_no_git(op: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_operator_premise(op)
    monkeypatch.setattr(builder_module, "_PROJECT_ROOT", op)
    run_mock = MagicMock(name="subprocess.run")
    exec_mock = AsyncMock(name="asyncio.create_subprocess_exec")
    # Both builder.subprocess and builder.asyncio are the real modules, so these patches cover every
    # git launch the executor makes (its own helper and the dirty-tree check); no premise git call
    # may follow them, so the premise above is already asserted.
    monkeypatch.setattr(builder_module.subprocess, "run", run_mock)
    monkeypatch.setattr(builder_module.asyncio, "create_subprocess_exec", exec_mock)

    result = await _build_in(op)

    assert result.success is False and "BF-897" in result.error, f"premise: the guard refused ({result.error})"
    assert run_mock.call_args_list == [], "the refused build launched a subprocess before refusing"
    assert exec_mock.call_args_list == [], "the refused build launched an async subprocess before refusing"
    exec_mock.assert_not_awaited()


# ===== T-A3: control, a linked worktree of the same repository builds normally ===================


@requires_git
async def test_execute_runs_in_a_linked_worktree_and_the_operator_checkout_is_unchanged(
    op: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_operator_premise(op)
    # Not named builder-bf897: that is the branch the executor derives from this spec title
    # ("builder/bf897", sanitized), and a worktree already on it makes the build fail with
    # "Failed to create branch", which would test a name collision and not the guard.
    wt = _add_worktree(op, tmp_path / "wts" / "b", "wt-bf897")
    monkeypatch.setattr(builder_module, "_PROJECT_ROOT", op)
    assert operator_checkout_refusal(wt, op) is None, "premise: the guard allows this worktree"
    assert _out(wt, "rev-parse", "--abbrev-ref", "HEAD") == "wt-bf897", "premise: the worktree is on its own branch"
    assert _porcelain(wt) == "", "premise: the worktree is clean, so the dirty-tree refusal cannot interfere"
    before = checkout_state(op)

    result = await _build_in(wt)

    assert result.success is True, f"the build in a linked worktree failed: {result.error}"
    assert result.commit_hash
    assert _git(op, "cat-file", "-e", result.commit_hash).returncode == 0, "the commit is not in the shared repository"
    tip = _out(op, "rev-parse", f"refs/heads/{result.branch_name}")
    assert tip.startswith(result.commit_hash), "the executor's branch does not end at the build's commit"
    # The executor ends by returning the tree to main, so the file is on the commit, not in the work tree.
    assert _show(wt, result.commit_hash, _NEW) == _NEW_TEXT
    assert checkout_state(op) == before, "a build in a linked worktree changed the operator's checkout"


# ===== T-A4: merge_to_main refuses and runs no git ===============================================


@requires_git
async def test_merge_to_main_refuses_runs_no_git_and_keeps_the_branch(
    op: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_operator_premise(op)
    mgr = WorktreeManager(repo_root=str(op), worktree_base=str(tmp_path / "wts"))
    info = await mgr.create("bf897build01")
    wt = Path(info.path)
    (wt / _A).write_text(_A_V3, encoding="utf-8", newline="\n")
    _out(wt, "add", "--", _A)
    _out(wt, "commit", "-q", "-m", "build change")
    # The branch is cut from the operator's HEAD (captain-work, one commit ahead of main), so it is two
    # commits ahead of main (the operator's and the build's) and one ahead of captain-work (the build's).
    assert _out(wt, "rev-parse", "--abbrev-ref", "HEAD") == info.branch, "premise: the worktree is on its branch"
    assert _commits_ahead(op, "main", info.branch) == "2", "premise: the build's work is unmerged"
    assert _commits_ahead(op, "captain-work", info.branch) == "1", "premise: the build holds one commit of its own"
    before = snapshot(op)

    real_run_git = mgr._run_git
    calls: list[tuple[tuple[str, ...], str | None]] = []

    async def spy(*args: str, cwd: str | None = None) -> tuple[int, str, str]:
        calls.append((args, cwd))
        return await real_run_git(*args, cwd=cwd)

    monkeypatch.setattr(mgr, "_run_git", spy)

    ok, reason = await mgr.merge_to_main("bf897build01")

    assert ok is False
    assert "BF-897" in reason
    assert info.branch in reason
    assert info.path in reason
    assert calls == [], f"merge_to_main ran git: {calls}"
    assert snapshot(op) == before, "merge_to_main changed the operator's checkout"
    assert _commits_ahead(op, "main", info.branch) == "2"
    assert _commits_ahead(op, "captain-work", info.branch) == "1"
    assert wt.is_dir(), "the build's worktree was removed"
    assert mgr.get("bf897build01") is info


async def test_merge_to_main_unknown_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = WorktreeManager(repo_root=str(tmp_path / "repo"), worktree_base=str(tmp_path / "wts"))
    run_git = AsyncMock(return_value=(0, "", ""))
    monkeypatch.setattr(mgr, "_run_git", run_git)
    assert mgr.get("no-such-build") is None, "premise: the build is not registered"

    outcome = await mgr.merge_to_main("no-such-build")

    assert outcome == (False, "unknown build_id")
    run_git.assert_not_called()


# ===== T-C: the test phase (fake runner, standard) ===============================================
#
# The executor runs with its pytest launch (the `_run_targeted_tests` seam, or `subprocess.run` beneath it) and its
# git launches replaced. What is under test is which outcome the test phase reports and what the commit gate does
# with it. "Not committed" is an assertion about a call that did not happen, so the fake git records its awaits.

_FOO = "src/probos/foo.py"
_FOO_TEXT = "x = 1\n"
_UNMAPPED = "src/probos/zz_unmapped.py"
_FIX_BLOCK = (
    f"===MODIFY: {_FOO}===\n"
    "===SEARCH===\nx = 1\n===REPLACE===\nx = 2\n===END REPLACE===\n"
    "===END MODIFY==="
)


class _FakeBuildGit:
    """The git launches of ``execute_approved_build``, replaced: none of them runs git, each records its awaits."""

    def __init__(self) -> None:
        self.create_branch = AsyncMock(return_value=(True, "builder/bf897"))
        # BF-904a (#1585): _git_checkout_main became _git_return_to (the ref the build started from).
        self.return_to = AsyncMock(return_value=(True, "main"))
        self.current_branch = AsyncMock(return_value="main")
        self.add_and_commit = AsyncMock(return_value=(True, "abc1234"))
        self.is_dirty = AsyncMock(return_value=False)
        self.run_git = AsyncMock(return_value=(0, "", ""))

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name, fake in (
            ("_git_create_branch", self.create_branch),
            ("_git_return_to", self.return_to),
            ("_git_current_branch", self.current_branch),
            ("_git_add_and_commit", self.add_and_commit),
            ("_is_dirty_working_tree", self.is_dirty),
            ("_run_git", self.run_git),
        ):
            monkeypatch.setattr(builder_module, name, fake)


class _FakeLLM:
    """A model client whose every answer is the same valid ``===MODIFY:`` block (the code review reads it too)."""

    def __init__(self) -> None:
        self.complete = AsyncMock(return_value=SimpleNamespace(content=_FIX_BLOCK))

    def fix_prompts(self) -> list[str]:
        """The prompts of the fix requests among the calls so far; the code review's prompt is not one."""
        prompts = [call.args[0].prompt for call in self.complete.await_args_list]
        return [prompt for prompt in prompts if "Test Fix Required" in prompt]


@pytest.fixture
def fake_git(monkeypatch: pytest.MonkeyPatch) -> _FakeBuildGit:
    git = _FakeBuildGit()
    git.install(monkeypatch)
    return git


def _plain_tree(tmp_path: Path, name: str) -> Path:
    """A work tree the BF-897 entry guard allows: the runtime's checkout (``_PROJECT_ROOT``) holds no repository."""
    tree = tmp_path / name
    tree.mkdir()
    assert operator_checkout_refusal(tree, builder_module._PROJECT_ROOT) is None, (
        "premise: the entry guard allows this tree, so its refusal cannot stand in for the behaviour under test"
    )
    return tree


@pytest.fixture
def build_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    monkeypatch.setattr(builder_module, "_PROJECT_ROOT", runtime_root)
    return _plain_tree(tmp_path, "work")


def _add_test_file(tree: Path, name: str) -> Path:
    tests_dir = tree / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_file = tests_dir / name
    test_file.write_text("def test_it() -> None:\n    assert True\n", encoding="utf-8", newline="\n")
    return test_file


async def _gated_build(
    tree: Path, *, path: str = _FOO, max_fix_attempts: int = 2, llm_client: _FakeLLM | None = None,
) -> BuildResult:
    """``execute_approved_build`` with the test phase on, creating one file in *tree*."""
    return await execute_approved_build(
        [{"path": path, "mode": "create", "content": _FOO_TEXT}],
        BuildSpec(title="bf897", description="d"),
        str(tree),
        run_tests=True,
        max_fix_attempts=max_fix_attempts,
        llm_client=llm_client,
    )


async def test_no_mapped_tests_runs_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with_tests = tmp_path / "with_tests"
    other_test = _add_test_file(with_tests, "test_other.py")
    without_tests = tmp_path / "without_tests"
    without_tests.mkdir()
    assert other_test.is_file(), "premise: one tree has a tests/ directory"
    assert not (without_tests / "tests").exists(), "premise: the other has none"
    never = MagicMock(side_effect=AssertionError("pytest ran"))
    monkeypatch.setattr(builder_module.subprocess, "run", never)

    for tree in (with_tests, without_tests):
        outcome = await _run_targeted_tests(str(tree), [_UNMAPPED])

        assert outcome == (False, NO_TARGETED_TESTS, []), f"{tree.name}: a change with no mapped test must run nothing"
    never.assert_not_called()

    # Control: a change that does map reaches the runner in the same tree, so the silence above is the mapping's.
    ran = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=b"1 passed", stderr=b""))
    monkeypatch.setattr(builder_module.subprocess, "run", ran)

    passed, _output, files = await _run_targeted_tests(str(with_tests), ["src/probos/other.py"])

    assert passed is True
    assert files == [str(other_test)]
    assert ran.call_count == 1


async def test_targeted_timeout_output_is_classified_timed_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mapped_test = _add_test_file(tmp_path, "test_foo.py")
    times_out = MagicMock(side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=60))
    monkeypatch.setattr(builder_module.subprocess, "run", times_out)
    assert mapped_test.is_file() and times_out.call_count == 0, "premise: a mapped test exists and nothing has run"

    passed, output, files = await _run_targeted_tests(str(tmp_path), [_FOO], timeout=60)

    assert times_out.call_count == 1, "the runner was never reached, so there was no timeout to classify"
    assert files == [str(mapped_test)]
    assert passed is False
    assert output.startswith("pytest timed out after")
    assert _classify_test_run(passed, output) == "timed_out"

    # The same prefix comes out of the whole-suite runner (kept, with no build caller).
    full_passed, full_output = await _run_tests(str(tmp_path), timeout=5)

    assert times_out.call_count == 2
    assert full_passed is False
    assert full_output.startswith("pytest timed out after")
    assert _classify_test_run(full_passed, full_output) == "timed_out"

    # Control: a run that ends in a real failure is a failure, not a timeout.
    failing = subprocess.CompletedProcess(args=[], returncode=1, stdout=b"1 failed", stderr=b"")
    monkeypatch.setattr(builder_module.subprocess, "run", MagicMock(return_value=failing))

    passed, output, _files = await _run_targeted_tests(str(tmp_path), [_FOO], timeout=60)

    assert passed is False
    assert "1 failed" in output
    assert _classify_test_run(passed, output) == "failed"


def test_classify_test_run_table() -> None:
    table = [
        (True, "x", "passed"),
        (False, "1 failed", "failed"),
        (False, "pytest timed out after 60s", "timed_out"),
        (False, NO_TARGETED_TESTS, "not_run"),
        # The timeout prefix must lead: a failure whose text mentions a timeout is still a failure.
        (False, "FAILED t.py - pytest timed out after 3s", "failed"),
        # The untested-change message is matched whole: anything after it is another output.
        (False, NO_TARGETED_TESTS + "\nmore", "failed"),
        (False, "", "failed"),
    ]
    for passed, output, expected in table:
        assert _classify_test_run(passed, output) == expected, f"({passed!r}, {output!r}) should be {expected}"


async def test_full_suite_never_runs_and_is_reported_not_run(
    build_tree: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch,
) -> None:
    targeted_outcome = (True, "1 passed", ["tests/test_x.py"])
    targeted = AsyncMock(return_value=targeted_outcome)
    full_suite = AsyncMock(return_value=(True, "2254 passed"))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", targeted)
    monkeypatch.setattr(builder_module, "_run_tests", full_suite)
    targeted_passed, _targeted_output, targeted_files = targeted_outcome
    assert targeted_passed and targeted_files, "premise: the targeted run passed on mapped files (old phase-2 trigger)"

    result = await _gated_build(build_tree)

    assert result.success is True and result.tests_passed is True, result.error
    assert targeted.await_count == 1
    full_suite.assert_not_awaited()
    assert result.metadata["full_suite"] == "not_run"
    assert result.metadata["targeted_tests"] == "passed"
    fake_git.add_and_commit.assert_awaited_once()


async def test_targeted_phase_uses_the_targeted_budget(
    build_tree: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str], object]] = []

    async def targeted(work_dir: str, changed_files: list[str], timeout: object = None) -> tuple[bool, str, list[str]]:
        calls.append((work_dir, list(changed_files), timeout))
        return True, "1 passed", ["tests/test_x.py"]

    monkeypatch.setattr(builder_module, "_run_targeted_tests", AsyncMock(side_effect=targeted))
    assert calls == [], "premise: the targeted phase has not run"

    result = await _gated_build(build_tree)

    assert result.success is True, result.error
    assert calls == [(str(build_tree), [_FOO], 60)], "the targeted phase must be given the 60 s targeted budget"
    assert TARGETED_TEST_TIMEOUT_S == 60


async def test_targeted_timeout_requests_no_fix_and_is_not_committed(
    build_tree: Path, tmp_path: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch,
) -> None:
    timed_out = (False, "pytest timed out after 60s", ["tests/test_x.py"])
    targeted = AsyncMock(return_value=timed_out)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", targeted)
    llm = _FakeLLM()
    assert _classify_test_run(timed_out[0], timed_out[1]) == "timed_out", "premise: this output is a timeout"
    blocks = BuilderAgent._parse_file_blocks(_FIX_BLOCK)
    assert [(block["mode"], block["path"]) for block in blocks] == [("modify", _FOO)], "premise: a valid fix block"

    result = await _gated_build(build_tree, max_fix_attempts=2, llm_client=llm)

    assert targeted.await_count == 1
    assert llm.fix_prompts() == []
    assert result.fix_attempts == 0
    assert result.success is False
    assert result.error.startswith("Targeted tests timed out")
    fake_git.add_and_commit.assert_not_awaited()
    assert result.metadata["targeted_tests"] == "timed_out"

    # Control, on a fresh tree: the same build with the output "1 failed" does enter the fix loop.
    control_tree = _plain_tree(tmp_path, "control")
    control_targeted = AsyncMock(return_value=(False, "1 failed", ["tests/test_x.py"]))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", control_targeted)
    control_llm = _FakeLLM()

    control = await _gated_build(control_tree, max_fix_attempts=2, llm_client=control_llm)

    assert control_targeted.await_count == 3
    assert len(control_llm.fix_prompts()) == 2
    assert control.fix_attempts == 2
    assert control.metadata["targeted_tests"] == "failed"
    fake_git.add_and_commit.assert_not_awaited()

    # The whole chain, with only the pytest process faked: the real runner times out, the real classifier reads
    # its message, and the gate refuses without a fix request. The half-tests above cannot see a runner whose
    # message the classifier no longer recognises.
    chain_tree = _plain_tree(tmp_path, "chain")
    chain_test = _add_test_file(chain_tree, "test_foo.py")
    pytest_launch = MagicMock(side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=60))
    monkeypatch.setattr(builder_module.subprocess, "run", pytest_launch)
    chain_targeted = AsyncMock(side_effect=_run_targeted_tests)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", chain_targeted)
    chain_llm = _FakeLLM()
    assert chain_test.is_file() and pytest_launch.call_count == 0, "premise: a mapped test, and nothing launched yet"

    chain = await _gated_build(chain_tree, max_fix_attempts=2, llm_client=chain_llm)

    assert pytest_launch.call_count == 1, "the timeout was followed by another pytest launch"
    assert chain_targeted.await_count == 1
    assert chain_llm.fix_prompts() == []
    assert chain.fix_attempts == 0
    assert chain.metadata["targeted_tests"] == "timed_out"
    assert chain.error.startswith("Targeted tests timed out")
    fake_git.add_and_commit.assert_not_awaited()


async def test_untested_change_requests_no_fix_and_is_not_committed(
    build_tree: Path, tmp_path: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch,
) -> None:
    unmapped = (False, NO_TARGETED_TESTS, [])
    targeted = AsyncMock(return_value=unmapped)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", targeted)
    llm = _FakeLLM()
    assert _classify_test_run(unmapped[0], unmapped[1]) == "not_run", "premise: this output is an untested change"

    result = await _gated_build(build_tree, max_fix_attempts=2, llm_client=llm)

    assert targeted.await_count == 1
    assert llm.fix_prompts() == []
    assert result.fix_attempts == 0
    assert result.success is False
    assert result.error.startswith("No targeted tests ran")
    fake_git.add_and_commit.assert_not_awaited()
    assert result.metadata["targeted_tests"] == "not_run"

    # The whole chain, with only the pytest process faked (and forbidden): a tree whose tests/ maps nothing to the
    # change, the real runner, the real classifier, the gate.
    chain_tree = _plain_tree(tmp_path, "chain")
    _add_test_file(chain_tree, "test_other.py")
    assert builder_module._map_source_to_tests([_UNMAPPED], str(chain_tree)) == [], "premise: nothing maps"
    pytest_launch = MagicMock(side_effect=AssertionError("pytest ran"))
    monkeypatch.setattr(builder_module.subprocess, "run", pytest_launch)
    chain_targeted = AsyncMock(side_effect=_run_targeted_tests)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", chain_targeted)
    chain_llm = _FakeLLM()

    chain = await _gated_build(chain_tree, path=_UNMAPPED, max_fix_attempts=2, llm_client=chain_llm)

    pytest_launch.assert_not_called()
    assert chain_targeted.await_count == 1
    assert chain_llm.fix_prompts() == []
    assert chain.fix_attempts == 0
    assert chain.metadata["targeted_tests"] == "not_run"
    assert chain.error.startswith("No targeted tests ran")
    fake_git.add_and_commit.assert_not_awaited()


async def test_a_real_failure_still_says_tests_failed(
    build_tree: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = (False, "1 failed", [])
    targeted = AsyncMock(return_value=failed)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", targeted)
    assert _classify_test_run(failed[0], failed[1]) == "failed", "premise: a failure, not a timeout or untested change"

    result = await _gated_build(build_tree, max_fix_attempts=0)

    assert result.success is False
    assert "Tests failed after 0 fix attempt(s)" in result.error
    assert "Targeted tests timed out" not in result.error
    assert "No targeted tests ran" not in result.error
    assert targeted.await_count == 1
    assert result.metadata["targeted_tests"] == "failed"
    fake_git.add_and_commit.assert_not_awaited()


async def test_no_repair_client_stops_after_the_first_failing_run(
    build_tree: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    failing = (False, "1 failed", ["tests/test_x.py"])
    targeted = AsyncMock(return_value=failing)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", targeted)
    assert _classify_test_run(failing[0], failing[1]) == "failed", "premise: a failure, not a timeout or untested change"

    result = await _gated_build(build_tree, max_fix_attempts=2, llm_client=None)

    # Without a repair client the tree cannot change, so a second run would repeat the first and no repair is requested.
    assert targeted.await_count == 1
    assert result.fix_attempts == 0
    assert result.success is False
    assert result.error.startswith("Tests failed after 0 fix attempt(s)")
    fake_git.add_and_commit.assert_not_awaited()

    # Control: with a client the same failing output is repaired twice, so the stop above is the missing client's.
    control_targeted = AsyncMock(return_value=failing)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", control_targeted)
    llm = _FakeLLM()

    control = await _gated_build(_plain_tree(tmp_path, "control"), max_fix_attempts=2, llm_client=llm)

    assert control_targeted.await_count == 3
    assert len(llm.fix_prompts()) == 2
    assert control.fix_attempts == 2


# ===== T-B: routers (real router through create_app) ==============================================

_RESOLVE_ID = "bf897r"


@requires_git
def test_resolve_refuses_a_cached_operator_checkout(
    op: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import probos.api as api_module  # first: probos.routers.build takes its failure cache from it
    from fastapi.testclient import TestClient
    from probos.routers import build as build_router
    from probos.runtime import ProbOSRuntime

    _assert_operator_premise(op)
    monkeypatch.setattr(build_router, "_REPO_ROOT", op)
    assert build_router._pending_failures is api_module._pending_failures, "premise: the router reads the seeded cache"
    assert _RESOLVE_ID not in api_module._pending_failures, "premise: no entry is left over"
    assert isinstance(operator_checkout_refusal(op, op), str), "premise: the cached tree is the one the router protects"
    rt = MagicMock(spec=ProbOSRuntime)
    # create_app mounts model directories under the runtime's data dir; a bare mock would make the path "MagicMock/..."
    # in the current directory (the repository root: the BF-326 janitor's warning).
    rt._data_dir = tmp_path / "data"
    client = TestClient(api_module.create_app(rt))

    def seed(work_dir: Path) -> None:
        monkeypatch.setitem(api_module._pending_failures, _RESOLVE_ID, {
            "file_changes": [],
            "spec": BuildSpec(title="t", description="d"),
            "work_dir": str(work_dir),
            "report": BuildFailureReport(files_modified=[_SYSTEM]),
            "timestamp": time.time(),
        })

    for resolution in ("abort", "commit_override"):
        seed(op)
        before = snapshot(op)
        assert _RESOLVE_ID in api_module._pending_failures, "premise: the failed build is cached"

        response = client.post("/api/build/resolve", json={"build_id": _RESOLVE_ID, "resolution": resolution})

        body = response.json()
        assert response.status_code == 200
        # The old abort switched the operator's checkout to main; the old override committed config/system.yaml.
        assert body["status"] == "error", f"{resolution} ran in the operator's checkout: {body}"
        assert "BF-897" in body["message"]
        assert _RESOLVE_ID not in api_module._pending_failures, f"{resolution}: the refused failure stays cached"
        assert snapshot(op) == before, f"{resolution} changed the operator's checkout"

    # Control: a cached failure in a linked worktree of the same repository is still resolved.
    linked = _add_worktree(op, tmp_path / "wts" / "r", "wt-resolve")
    assert operator_checkout_refusal(linked, op) is None, "premise: the guard allows this worktree"
    seed(linked)
    before_control = checkout_state(op)

    response = client.post("/api/build/resolve", json={"build_id": _RESOLVE_ID, "resolution": "abort"})

    assert response.json() == {"status": "ok", "resolution": "abort"}
    # BF-904a (#1585): abort runs no git (the failed build already returned to its ref), so the worktree stays put.
    assert _out(linked, "rev-parse", "--abbrev-ref", "HEAD") == "wt-resolve", "the abort ran git in the worktree"
    assert checkout_state(op) == before_control, "resolving a worktree's failure changed the operator's checkout"


# ===== Review round 1 repair (F1, F4) =============================================================
#
# F1: the approve refusal emits ``build_failure`` through the real runtime emission methods, with the Night Orders
# hook live for that event; the refusal must not escalate (``not_executed``) and must survive a failing emit.
# F4 (no repair client stops the fix loop) sits with the T-C group above.


class _NightOrdersEmitHost:
    """BF-708 shape: the unmodified runtime emission methods on a minimal object, Night Orders active."""

    add_event_listener = ProbOSRuntime.add_event_listener
    emit_event = ProbOSRuntime.emit_event
    _emit_event = ProbOSRuntime._emit_event
    _emit_event_local = ProbOSRuntime._emit_event_local
    _check_night_order_escalation = ProbOSRuntime._check_night_order_escalation

    def __init__(self) -> None:
        self._event_listeners: list[Any] = []
        self._live_event_listeners: list[Any] = []
        self._event_listener_tasks: set[Any] = set()
        self._nats_publish_tasks: set[Any] = set()
        self._nats_events_wired = False
        self.nats_bus = None
        self.conn_manager = MagicMock()
        self.bridge_alerts = None
        self._night_orders_mgr = NightOrdersManager()
        self._night_orders_mgr.set_night_orders(["probe"], escalation_triggers=["build_failure"])
        self.events: list[dict[str, Any]] = []
        self.add_event_listener(self.events.append)


def _approve_client(runtime: object) -> TestClient:
    app = FastAPI()
    app.include_router(build_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def test_approve_refusal_is_not_escalated_by_night_orders() -> None:
    host = _NightOrdersEmitHost()
    assert host._night_orders_mgr.active is True, "premise: Night Orders is active"
    assert host._night_orders_mgr.check_escalation("build_failure") is True, (
        "premise: the hook is live for this event, so silence below is the marker's"
    )
    client = _approve_client(host)

    response = client.post("/api/build/approve", json={"build_id": "b1"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["build_id"] == "b1"
    assert body["message"] == build_router.APPROVE_REFUSED
    assert len(host.events) == 1
    event = host.events[0]
    assert event["type"] == "build_failure"
    assert event["data"]["not_executed"] is True
    assert event["data"]["build_id"] == "b1"
    host.conn_manager.check_escalation.assert_not_called()


@pytest.mark.parametrize(
    "marker",
    [{}, {"not_executed": False}, {"not_executed": "true"}, {"not_executed": 1}],
    ids=["absent", "false", "string-true", "int-one"],
)
def test_an_unmarked_build_failure_still_escalates(marker: dict[str, object]) -> None:
    host = _NightOrdersEmitHost()
    assert host._night_orders_mgr.check_escalation("build_failure") is True, "premise: the hook is live"
    host.conn_manager.check_escalation.assert_not_called()

    host.emit_event(EventType.BUILD_FAILURE, {"build_id": "b2", "message": "m", **marker})

    # ``is True`` is the contract: a truthy value that is not True still escalates.
    host.conn_manager.check_escalation.assert_called_once()
    assert host.conn_manager.check_escalation.call_args.args[0] == "build_failure"


def test_approve_refusal_survives_a_failing_event_emit() -> None:
    stub = SimpleNamespace(emit_event=MagicMock(side_effect=RuntimeError("listener failed")))
    client = _approve_client(stub)

    response = client.post("/api/build/approve", json={"build_id": "b1"})

    stub.emit_event.assert_called_once()  # the emit was attempted, so the guard is what saved the response
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["message"] == build_router.APPROVE_REFUSED
