"""BF-904a (#1585), milestone M2: a failed build leaves the operator's checkout as it found it.

Before M2 a build that did not commit ended with ``git checkout main`` and ``git branch -D <build branch>``, then
deleted the files it had created. From any other starting point that moved the operator: off a branch of their
own, off a detached HEAD, and out of a linked worktree whose ``main`` is checked out elsewhere (the checkout failed,
so the build branch stayed checked out). The tracked files the build changed stayed changed, and a commit that
failed after ``git add`` left the paths staged. M2 puts the tree back. No git writes the bytes: each file that
existed before the build is written back byte for byte and each file the build created is deleted. Then the
checkout returns to the ref the build STARTED from (a branch, or the commit of a detached HEAD, never a guessed
``main``), and the build branch is deleted only when that return succeeded. Every step that fails is named in
``metadata["cleanup_errors"]``. The Captain's ``abort`` runs no git, and ``commit_override`` runs the cached
changes again through ``execute_approved_build`` with only the test gate off.

Rules this file keeps:

* Real git in repositories under ``tmp_path`` (repo-local identity, ``commit.gpgsign false``,
  ``core.autocrlf false``); the helpers are copied, not imported, from ``tests/test_bf904a_git_hardening.py``
  (which copied them from the BF-896 and BF-897 tests).
* "Left as it found it" is read with plain git by ``_state``: the porcelain status, the HEAD ref (the branch, or
  the commit of a detached HEAD), every local branch with its tip, and every file's bytes. Every case also
  asserts what the build DID before it failed (the files it wrote, the repair it received, the paths it had
  staged), so an early refusal that touches nothing cannot pass for a restore.
* The test's own git calls use ``_control_env()``: the process environment minus every ``GIT_*`` name, and an
  autouse fixture deletes every ``GIT_*`` name from ``os.environ``, so no test depends on the invoking shell.
* No sleeps, nothing ordered by wall-clock time, every subprocess the tests start has a timeout, every await is bounded.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Awaitable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.api_models import BuildResolveRequest
from probos.cognitive import builder as builder_module
from probos.cognitive.builder import (
    BuildFailureReport,
    BuilderAgent,
    BuildResult,
    BuildSpec,
    classify_build_failure,
    execute_approved_build,
)
from probos.cognitive.builder_paths import builder_write_refusal
from probos.events import EventType
from probos.execution.command_env import HARDENED_GIT_CONFIG_ARGS

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
pytestmark = needs_git

TARGET = "src/probos/a.py"
OTHER = "src/probos/other.py"
NEW = "src/probos/newpkg/fresh.py"
BAD = "src/probos/bad.py"
ORIGINAL = "x = 1\n"
SEED = {TARGET: ORIGINAL, OTHER: "y = 1\n"}
BROKEN = "def broken(:\n"
RESOLVE_ID = "bf904a-m2-resolve"
OVERRIDE_MARKER = "[Test gate overridden by Captain]"  # the literal of the contract: an import would fail collection on the old source
REPAIR_OTHER = (
    f"===MODIFY: {OTHER}===\n"
    "===SEARCH===\ny = 1\n===REPLACE===\ny = 3\n===END REPLACE===\n"
    "===END MODIFY===\n"
)

# The real runner, captured at import before any test patches ``subprocess.run`` (R5 does): the tests' own git
# calls go through it, so a recorder installed by a test never sees them.
_REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def _no_ambient_git_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every ``GIT_*`` name from the process environment for the test's duration (see the module docstring)."""
    for name in list(os.environ):
        if name.upper().startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Helpers (copied from tests/test_bf904a_git_hardening.py)
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


def _blob(repo: Path, ref: str, path: str) -> str:
    shown = _git(repo, "show", f"{ref}:{path}")
    assert shown.returncode == 0, f"{ref}:{path} must exist in the repository ({shown.stderr.strip()})"
    return shown.stdout


def _refs(repo: Path) -> list[str]:
    return sorted(_git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout.split())


def _tree(root: Path) -> dict[str, bytes]:
    """Every file under *root* except anything named ``.git`` (a worktree's pointer is one)."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(root).parts
    }


def _spec(title: str = "bf904a probe") -> BuildSpec:
    return BuildSpec(title=title, description="")


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


# ---------------------------------------------------------------------------
# Fixtures and the state a failed build must not change
# ---------------------------------------------------------------------------


def _on_captain_work(path: Path) -> Path:
    """A repository on the Captain's own branch ``captain-work``, one commit ahead of ``main``."""
    _plain_repo(path)
    assert _git(path, "checkout", "-q", "-b", "captain-work").returncode == 0, "premise: git checkout -b"
    (path / "captain.txt").write_bytes(b"captain\n")
    assert _git(path, "add", "--", "captain.txt").returncode == 0, "premise: git add must succeed"
    assert _git(path, "commit", "-q", "-m", "captain work").returncode == 0, "premise: the Captain's commit"
    return path


def _head_ref(tree: Path) -> str:
    """The branch HEAD names, or the commit of a detached HEAD (plain git)."""
    named = _REAL_RUN(
        ["git", "symbolic-ref", "-q", "--short", "HEAD"], cwd=tree, capture_output=True, check=False,
        env=_control_env(), stdin=subprocess.DEVNULL, timeout=60,
    )  # BF-904a A4 (D33): bytes, so a ref ending in Unicode whitespace is read exactly as git names it
    if named.returncode == 0:
        return named.stdout.decode("utf-8", "surrogateescape").removesuffix("\n")
    return _out(tree, "rev-parse", "HEAD")


_STATE_PARTS = ("porcelain status", "HEAD ref", "local branches and their tips", "file bytes")


def _state(tree: Path) -> tuple[str, str, list[str], dict[str, bytes]]:
    """What "the tree as the build found it" means, read with plain git: the porcelain status, the HEAD ref (the
    branch, or the commit of a detached HEAD), every local branch with its tip, and every file's bytes."""
    status = _git(tree, "status", "--porcelain")
    assert status.returncode == 0, f"premise: git status must succeed: {status.stderr}"
    tips = _git(tree, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads")
    assert tips.returncode == 0, f"premise: git for-each-ref must succeed: {tips.stderr}"
    return status.stdout, _head_ref(tree), sorted(tips.stdout.split("\n")), _tree(tree)  # BF-904a A4: split at LF only; a ref may hold U+0085 or U+2028


def _failing_changes() -> list[dict[str, Any]]:
    """Four changes that all write and then fail the syntax check: a modify, a create over an existing file, a
    create in a new directory, and a create whose text does not parse."""
    return [
        {"path": TARGET, "mode": "modify", "replacements": [{"search": "x = 1", "replace": "x = 2"}]},
        _create(OTHER, "y = 2\n"),
        _create(NEW, "ok = 1\n"),
        _create(BAD, BROKEN),
    ]


class _FakeModel:
    """A model client whose every answer is *reply* (the code review reads it too); it keeps every request."""

    def __init__(self, reply: str) -> None:
        self.complete = AsyncMock(return_value=SimpleNamespace(content=reply))

    def fix_prompts(self) -> list[str]:
        """The prompts of the repair requests among the calls so far; the code review's prompt is not one."""
        prompts = [call.args[0].prompt for call in self.complete.await_args_list]
        return [prompt for prompt in prompts if "Test Fix Required" in prompt]


def _fail_the_return(
    monkeypatch: pytest.MonkeyPatch, detail: str = "bf904a: simulated return failure"
) -> list[tuple[bool, str]]:
    """Replace ``_git_return_to`` with a wrapper that runs the real one, keeps its answer, then reports a failure
    whose text is *detail* (A3: R8 varies it)."""
    real_return = builder_module._git_return_to
    real_answers: list[tuple[bool, str]] = []

    async def return_then_fail(branch: str | None, commit: str | None, work_dir: str) -> tuple[bool, str]:
        real_answers.append(await real_return(branch, commit, work_dir))
        return False, detail

    monkeypatch.setattr(builder_module, "_git_return_to", return_then_fail)
    return real_answers


def _route_modules() -> tuple[Any, Any]:
    """``(probos.api, probos.routers.build)``. The second takes its failure cache from the first, so it loads first."""
    import probos.api as api_module
    from probos.routers import build as build_router

    return api_module, build_router


# ---------------------------------------------------------------------------
# R1: the tree and HEAD as they were, from every starting point
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    ["other-branch", "detached", "linked-worktree-main-elsewhere", "fix-loop-edit", "commit-failed-after-add"],
)
async def test_a_failed_build_leaves_the_tree_and_head_as_they_were(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    base: Path | None = None
    changes = _failing_changes()
    kwargs: dict[str, Any] = {}
    model: _FakeModel | None = None
    add_codes: list[int] = []
    staged: list[str] = []
    wrote = ([NEW, BAD], [TARGET, OTHER])  # (files_written, files_modified) once the four changes are written

    if case == "other-branch":
        tree = _on_captain_work(tmp_path / "repo")
        assert _head_ref(tree) == "captain-work", "premise: the build starts on the Captain's own branch"
        assert _out(tree, "rev-list", "--count", "main..captain-work") == "1", "premise: one commit ahead of main"
    elif case == "detached":
        tree = _plain_repo(tmp_path / "repo")
        assert _git(tree, "checkout", "-q", "--detach", "HEAD").returncode == 0, "premise: git checkout --detach"
        assert _git(tree, "symbolic-ref", "-q", "HEAD").returncode != 0, "premise: HEAD names no branch"
    elif case == "linked-worktree-main-elsewhere":
        base = _plain_repo(tmp_path / "base")
        tree = tmp_path / "wt"
        assert _git(base, "worktree", "add", "-q", "-b", "wt-bf904a", str(tree), "main").returncode == 0, (
            "premise: git worktree add"
        )
        main_worktree = _out(base, "worktree", "list", "--porcelain").split("\n\n")[0]
        assert "branch refs/heads/main" in main_worktree, f"premise: main is checked out in the base: {main_worktree}"
        assert _head_ref(tree) == "wt-bf904a", "premise: the build runs on the linked worktree's own branch"
    elif case == "fix-loop-edit":
        tree = _plain_repo(tmp_path / "repo")
        changes = [_create(NEW, "ok = 1\n")]
        model = _FakeModel(REPAIR_OTHER)
        monkeypatch.setattr(
            builder_module, "_run_targeted_tests", AsyncMock(return_value=(False, "1 failed", ["tests/test_x.py"]))
        )
        kwargs = {"run_tests": True, "max_fix_attempts": 1, "llm_client": model}
        wrote = ([NEW], [OTHER])
        repairs = BuilderAgent._parse_file_blocks(REPAIR_OTHER)
        assert [(b["mode"], b["path"]) for b in repairs] == [("modify", OTHER)], "premise: the repair edits OTHER"
    else:
        tree = _plain_repo(tmp_path / "repo")
        changes = [
            {"path": TARGET, "mode": "modify", "replacements": [{"search": "x = 1", "replace": "x = 2"}]},
            _create(NEW, "ok = 1\n"),
        ]
        real_run_git = builder_module._run_git

        async def add_then_refuse(files: list[str], message: str, work_dir: str) -> tuple[bool, str]:
            code, _stdout, _stderr = await real_run_git(["add", "--", *files], work_dir)
            add_codes.append(code)
            staged.extend(_git(Path(work_dir), "diff", "--cached", "--name-only").stdout.split())
            return False, "bf904a: commit refused"

        monkeypatch.setattr(builder_module, "_git_add_and_commit", add_then_refuse)
        wrote = ([NEW], [TARGET])

    before = _state(tree)
    base_before = _state(base) if base is not None else None
    assert before[0] == "", f"premise: the tree starts clean: {before[0]!r}"

    result = await _build(tree, changes, **kwargs)

    assert result.branch_name, f"premise: the build got as far as its branch: {result.error}"
    assert (result.files_written, result.files_modified) == wrote, (
        f"premise: the build wrote its files before it failed: {result.error}"
    )
    if case == "fix-loop-edit":
        assert model is not None and len(model.fix_prompts()) == 1, "premise: the model received one repair request"
        assert result.metadata["fix_loop_files"] == [OTHER], "premise: the repair changed OTHER"
        assert result.error.startswith("Tests failed after 1 fix attempt(s)"), result.error
    elif case == "commit-failed-after-add":
        assert add_codes == [0], f"premise: git add ran and succeeded: {add_codes}"
        assert sorted(staged) == sorted([TARGET, NEW]), f"premise: the add staged both paths: {staged}"
        assert result.error.startswith("Commit failed: bf904a: commit refused"), result.error
    else:
        assert result.error.startswith("Syntax errors"), result.error
    assert result.success is False and not result.commit_hash, result.error

    after = _state(tree)
    for label, was, now in zip(_STATE_PARTS, before, after):
        assert now == was, f"{case}: the failed build changed the {label}: {was!r} -> {now!r}"
    if base is not None and base_before is not None:
        base_after = _state(base)
        for label, was, now in zip(_STATE_PARTS, base_before, base_after):
            assert now == was, f"{case}: the failed build changed the base repository's {label}: {was!r} -> {now!r}"


# ---------------------------------------------------------------------------
# R2, R2b: a return that fails is reported, never hidden
# ---------------------------------------------------------------------------


async def test_a_failed_return_is_reported_and_keeps_the_build_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _plain_repo(tmp_path / "repo")
    real_answers = _fail_the_return(monkeypatch)

    result = await _build(repo, _failing_changes())

    assert len(real_answers) == 1 and real_answers[0][0] is True, f"premise: the real return succeeded: {real_answers}"
    assert result.success is False and result.branch_name, result.error
    assert result.error.startswith("Syntax errors"), f"the build's own error comes first: {result.error}"
    assert "\nCleanup incomplete: " in result.error and "simulated return failure" in result.error, result.error
    entries = result.metadata.get("cleanup_errors", [])
    assert len(entries) == 1, f"exactly one cleanup error is recorded: {entries}"
    assert result.branch_name in entries[0] and "kept" in entries[0], entries[0]
    assert result.branch_name in _refs(repo), "a branch whose return failed is kept, not deleted"
    assert _tree(repo) == {path: text.encode("utf-8") for path, text in SEED.items()}, "every file's bytes are the seed's"
    assert classify_build_failure(result, _spec()).cleanup_errors == result.metadata["cleanup_errors"], (
        "A3 (D28): the structured notes reach the failure report"  # crosses the builder-to-report seam
    )


async def test_a_committed_build_that_cannot_return_stays_a_success_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    repo = _plain_repo(tmp_path / "repo")
    real_answers = _fail_the_return(monkeypatch)
    caplog.set_level(logging.DEBUG)

    result = await _build(repo, [_create(NEW, "ok = 1\n")])

    assert len(real_answers) == 1 and real_answers[0][0] is True, f"premise: the real return succeeded: {real_answers}"
    assert result.success is True and result.commit_hash, f"a commit is a success whatever the cleanup said: {result.error}"
    assert result.metadata.get("cleanup_errors"), "the failed return is recorded"
    assert "Cleanup incomplete" not in result.error, "a success carries no failure text"
    logged = [r for r in caplog.records if r.levelno == logging.ERROR and "build cleanup incomplete" in r.getMessage()]
    assert logged, "the failed return is logged at ERROR: " + " | ".join(r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# R3: a committed build returns to the branch it started on
# ---------------------------------------------------------------------------


async def test_a_committed_build_returns_to_the_branch_it_started_on(tmp_path: Path) -> None:
    repo = _on_captain_work(tmp_path / "repo")
    assert _head_ref(repo) == "captain-work", "premise: the build starts on the Captain's own branch"

    result = await _build(repo, [_create(NEW, "ok = 1\n")])

    assert result.success is True and result.commit_hash, f"premise: the build committed: {result.error}"
    assert _out(repo, "symbolic-ref", "--short", "HEAD") == "captain-work", "the checkout is back on the Captain's branch"
    assert _blob(repo, result.branch_name, NEW) == "ok = 1\n", "the commit is on the build branch"
    assert _git(repo, "status", "--porcelain").stdout == "", "a committed build leaves no change behind"


# ---------------------------------------------------------------------------
# R4: no branch and no commit to return to
# ---------------------------------------------------------------------------


async def test_a_tree_with_neither_branch_nor_commit_is_refused_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _git(plain, "rev-parse", "--git-dir").returncode != 0, "premise: the directory is not inside a repository"
    spy = _GitSpy(builder_module._run_git)
    monkeypatch.setattr(builder_module, "_run_git", spy)

    result = await _build(plain, [_create(NEW, "ok = 1\n")])

    assert spy.calls, "premise: the spy saw the build's git calls"
    assert result.success is False
    assert result.error.startswith("Cannot read the checkout's current branch or commit"), result.error
    assert [args for _swapped, args in spy.calls if args[:2] == ["checkout", "-b"]] == [], "no build branch was attempted"
    assert _tree(plain) == {} and not (plain / "src").exists(), "nothing was written"


# ---------------------------------------------------------------------------
# R5, R6: the Captain's resolutions
# ---------------------------------------------------------------------------


async def test_abort_runs_no_git_and_leaves_the_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api_module, build_router = _route_modules()
    repo = _on_captain_work(tmp_path / "repo")
    assert build_router._pending_failures is api_module._pending_failures, "premise: the router reads the seeded cache"
    assert RESOLVE_ID not in api_module._pending_failures, "premise: no entry is left over"
    assert build_router.operator_checkout_refusal(repo, build_router._REPO_ROOT) is None, "premise: the guard allows this tree"
    assert _head_ref(repo) == "captain-work", "premise: the checkout is on the Captain's branch"
    monkeypatch.setitem(api_module._pending_failures, RESOLVE_ID, {
        "file_changes": [],
        "spec": BuildSpec(title="bf904a abort", description="d"),
        "work_dir": str(repo),
        "report": BuildFailureReport(),
        "timestamp": time.time(),
    })

    recorded: list[list[str]] = []
    real_exec = asyncio.create_subprocess_exec

    def run_recorder(argv: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(argv, (list, tuple)) and argv and argv[0] == "git":
            recorded.append([str(part) for part in argv])  # subprocess.run takes the argv as one list
        return _REAL_RUN(argv, *args, **kwargs)

    async def exec_recorder(*argv: Any, **kwargs: Any) -> Any:
        if argv and argv[0] == "git":
            recorded.append([str(part) for part in argv])  # create_subprocess_exec takes it as positional arguments
        return await real_exec(*argv, **kwargs)

    monkeypatch.setattr(builder_module.subprocess, "run", run_recorder)
    monkeypatch.setattr(builder_module.asyncio, "create_subprocess_exec", exec_recorder)
    await _bounded(builder_module._run_git(["rev-parse", "HEAD"], str(repo)))  # control: the recorder sees the builder's git
    assert len(recorded) == 1 and recorded[0][-2:] == ["rev-parse", "HEAD"], f"premise: the recorder is live: {recorded}"
    recorded.clear()
    rt = MagicMock()
    tracked: list[Any] = []

    def capture(coro: Any, name: str | None = None) -> None:
        tracked.append(coro)

    response = await _bounded(build_router.resolve_build(
        BuildResolveRequest(build_id=RESOLVE_ID, resolution="abort"), runtime=rt, track_task=capture,
    ))

    assert response == {"status": "ok", "resolution": "abort"}, response
    assert recorded == [], f"the abort ran git: {recorded}"
    assert tracked == [], "the abort starts no background build"
    assert _head_ref(repo) == "captain-work", "the checkout stays where the failed build left it"
    assert RESOLVE_ID not in api_module._pending_failures, "the resolved failure leaves the cache"
    rt.emit_event.assert_called_once()
    event_type, data = rt.emit_event.call_args.args
    assert event_type == EventType.BUILD_RESOLVED and data["resolution"] == "abort", (event_type, data)
    assert "main branch" not in data["message"], data["message"]


async def test_commit_override_reruns_the_cached_changes_without_the_test_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api_module, build_router = _route_modules()
    repo = _on_captain_work(tmp_path / "repo")
    assert build_router._pending_failures is api_module._pending_failures, "premise: the router reads the seeded cache"
    assert RESOLVE_ID not in api_module._pending_failures, "premise: no entry is left over"
    assert build_router.operator_checkout_refusal(repo, build_router._REPO_ROOT) is None, "premise: the guard allows this tree"
    assert _head_ref(repo) == "captain-work", "premise: the checkout is on the Captain's branch"
    targeted = AsyncMock(return_value=(True, "1 passed", []))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", targeted)
    monkeypatch.setitem(api_module._pending_failures, RESOLVE_ID, {
        "file_changes": [_create(NEW, "ok = 1\n")],
        "spec": BuildSpec(title="bf904a override", description="d"),
        "work_dir": str(repo),
        "report": BuildFailureReport(),
        "timestamp": time.time(),
    })
    rt = MagicMock()
    rt.llm_client = None  # a bare mock attribute would be a truthy client the code review would call
    tracked: list[Any] = []

    def capture(coro: Any, name: str | None = None) -> None:
        tracked.append(coro)

    response = await _bounded(build_router.resolve_build(
        BuildResolveRequest(build_id=RESOLVE_ID, resolution="commit_override"), runtime=rt, track_task=capture,
    ))

    assert response == {"status": "ok", "resolution": "commit_override", "build_id": RESOLVE_ID}, response
    assert len(tracked) == 1 and asyncio.iscoroutine(tracked[0]), "premise: the rerun was handed to track_task"
    assert RESOLVE_ID not in api_module._pending_failures, "the resolved failure leaves the cache"
    await _bounded(tracked[0])

    events = [call.args for call in rt.emit_event.call_args_list]
    types = [args[0] for args in events]
    assert types == [EventType.BUILD_RESOLVED, EventType.BUILD_PROGRESS, EventType.BUILD_SUCCESS], (
        f"{types}; failure: {[args[1].get('error') for args in events if args[0] == EventType.BUILD_FAILURE]}"
    )
    assert EventType.BUILD_FAILURE not in types
    targeted.assert_not_awaited()  # the override lifts the test gate, and only that
    branch = events[2][1]["branch"]
    message = _git(repo, "log", "-1", "--format=%B", branch).stdout.splitlines()
    assert message[:3] == ["bf904a override", "", OVERRIDE_MARKER], message
    assert _blob(repo, branch, NEW) == "ok = 1\n", "the commit's tree holds the cached change"
    assert _head_ref(repo) == "captain-work", "the checkout is back on the Captain's branch"
    assert _git(repo, "status", "--porcelain").stdout == "", "the rerun leaves no change behind"


# ---------------------------------------------------------------------------
# R7, R8 (A3, D25): the cleanup's messages carry every build-authored or git-authored text as an escaped token
# ---------------------------------------------------------------------------

HOSTILE = "\u202e`"  # a right-to-left override and a backtick: legal in a file name, and builder_write_refusal accepts both
HOSTILE_DETAIL = "\x1b[31m\r\n\u202e" + "d" * 5000
SEPARATOR = "\nCleanup incomplete: "


async def test_cleanup_messages_carry_build_authored_names_escaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    restored_name = "r" + HOSTILE + "x.txt"
    deleted_name = "d" + HOSTILE + "x.txt"
    logged_name = "l" + HOSTILE + "x.txt"
    seeded = f"src/probos/{restored_name}"
    repo = _plain_repo(tmp_path / "repo", {**SEED, seeded: "z = 1\n"})
    assert seeded in _git(repo, "ls-files", "-z").stdout.split("\0"), "premise: the hostile file name is tracked"
    assert _git(repo, "status", "--porcelain").stdout == "", "premise: the tree starts clean"
    changes = _failing_changes() + [
        {"path": seeded, "mode": "modify", "replacements": [{"search": "z = 1", "replace": "z = 2"}]},
        _create(f"src/probos/{deleted_name}", "d = 1\n"),
        _create(f"src/probos/{logged_name}", "l = 1\n"),
    ]

    raised = {"write_bytes": 0, "unlink": 0}
    real_write_bytes = Path.write_bytes
    real_unlink = Path.unlink

    def write_bytes(self: Path, data: Any) -> int:
        if self.name == restored_name:  # a string comparison only: no filesystem call before the saved original
            raised["write_bytes"] += 1
            raise PermissionError("bf904a: simulated write refusal")
        return real_write_bytes(self, data)

    def unlink(self: Path, *args: Any, **kwargs: Any) -> None:
        if self.name == deleted_name:
            raised["unlink"] += 1
            raise PermissionError("bf904a: simulated delete refusal")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_bytes", write_bytes)
    monkeypatch.setattr(Path, "unlink", unlink)
    caplog.set_level(logging.INFO)

    result = await _build(repo, changes)

    assert result.branch_name and result.error.startswith("Syntax errors"), f"premise: the build failed late: {result.error}"
    assert raised == {"write_bytes": 1, "unlink": 1}, f"premise: each seam raised exactly once: {raised}"
    assert not (repo / "src" / "probos" / logged_name).exists(), "premise: the file that could be deleted was deleted"

    assert SEPARATOR in result.error, result.error
    tail = result.error.split(SEPARATOR, 1)[1]
    assert all(ch.isprintable() for ch in tail), f"an unprintable character reaches the cleanup text: {tail!r}"
    assert "\u202e" not in tail, "the raw override never reaches the cleanup text"
    assert "\\u202e" in tail and "\\x60" in tail, f"the name is escaped: {tail}"
    entries = result.metadata["cleanup_errors"]
    assert len(entries) == 2, entries
    for entry in entries:
        assert all(ch.isprintable() for ch in entry) and "\u202e" not in entry, entry
    assert sorted(entry.split("`", 1)[0] for entry in entries) == ["could not delete ", "could not restore "], entries

    logged = [
        r.getMessage() for r in caplog.records
        if "Cleaned up untracked file from failed build" in r.getMessage()
        and (logged_name in r.getMessage() or "l\\u202e" in r.getMessage())
    ]
    assert len(logged) == 1, f"premise: one record names the deleted file: {logged}"
    assert all(ch.isprintable() for ch in logged[0]) and "\\u202e" in logged[0], logged[0]


@pytest.mark.parametrize("case", ["return", "branch-delete"])
async def test_cleanup_messages_carry_git_answers_and_refs_escaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    repo = _plain_repo(tmp_path / "repo")
    bidi_branch = False
    if case == "return":
        started = "captain\u2067work"
        made = _git(repo, "checkout", "-q", "-b", started)
        shown = _git(repo, "symbolic-ref", "-q", "--short", "HEAD").stdout.strip()
        bidi_branch = made.returncode == 0 and shown == started
        if not bidi_branch:  # this host's git refuses the name: the plain name keeps the rest of the case (row R-t is then unchecked)
            started = "captain-work"
            assert _git(repo, "checkout", "-q", "-b", started).returncode == 0, "premise: git checkout -b"
        assert _head_ref(repo) == started, "premise: the build starts on the branch under test"
        real_answers = _fail_the_return(monkeypatch, detail=HOSTILE_DETAIL)
    else:
        real_run_git = builder_module._run_git
        deletes: list[list[str]] = []

        async def refuse_branch_delete(args: list[str], work_dir: str, **kwargs: Any) -> tuple[int, str, str]:
            if args[:2] == ["branch", "-D"]:
                deletes.append(list(args))
                return 1, "", HOSTILE_DETAIL
            return await real_run_git(args, work_dir, **kwargs)

        monkeypatch.setattr(builder_module, "_run_git", refuse_branch_delete)

    result = await _build(repo, _failing_changes())

    assert result.branch_name and result.error.startswith("Syntax errors"), f"premise: the build failed late: {result.error}"
    if case == "return":
        assert len(real_answers) == 1 and real_answers[0][0] is True, f"premise: the real return succeeded: {real_answers}"
    else:
        assert len(deletes) == 1, f"premise: the build branch's delete was asked for once: {deletes}"
    assert SEPARATOR in result.error, result.error
    tail = result.error.split(SEPARATOR, 1)[1]
    entries = result.metadata["cleanup_errors"]
    assert len(entries) == 1, entries
    assert all(ch.isprintable() for ch in tail), f"an unprintable character reaches the cleanup text: {tail!r}"
    assert "\\x1b" in tail and "\\u202e" in tail, f"git's answer is escaped: {tail}"
    if bidi_branch:
        assert "\\u2067" in tail, f"the starting branch is escaped: {tail}"
    assert "d" * 201 not in tail, "git's answer is cut"
    assert len(tail) < 1000, len(tail)
    assert entries[0].startswith("could not return to `" if case == "return" else "git branch exited 1: `"), entries[0]


# ---------------------------------------------------------------------------
# R9, R10 (A3, D28 to D30): abort names an incomplete cleanup; a resolution that runs a build is refused after one
# ---------------------------------------------------------------------------


def _record_git(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record every git argv the builder starts (``subprocess.run`` and ``create_subprocess_exec``), as R5 does."""
    recorded: list[list[str]] = []
    real_exec = asyncio.create_subprocess_exec

    def run_recorder(argv: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(argv, (list, tuple)) and argv and argv[0] == "git":
            recorded.append([str(part) for part in argv])
        return _REAL_RUN(argv, *args, **kwargs)

    async def exec_recorder(*argv: Any, **kwargs: Any) -> Any:
        if argv and argv[0] == "git":
            recorded.append([str(part) for part in argv])
        return await real_exec(*argv, **kwargs)

    monkeypatch.setattr(builder_module.subprocess, "run", run_recorder)
    monkeypatch.setattr(builder_module.asyncio, "create_subprocess_exec", exec_recorder)
    return recorded


@pytest.mark.parametrize("case", ["clean", "incomplete"])
async def test_abort_reports_an_incomplete_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    api_module, build_router = _route_modules()
    repo = _on_captain_work(tmp_path / "repo")
    assert build_router._pending_failures is api_module._pending_failures, "premise: the router reads the seeded cache"
    assert RESOLVE_ID not in api_module._pending_failures, "premise: no entry is left over"
    assert build_router.operator_checkout_refusal(repo, build_router._REPO_ROOT) is None, "premise: the guard allows this tree"
    assert _head_ref(repo) == "captain-work", "premise: the checkout is on the Captain's branch"
    report = BuildFailureReport() if case == "clean" else BuildFailureReport(cleanup_errors=["bf904a: simulated"])
    assert bool(getattr(report, "cleanup_errors", [])) is (case == "incomplete"), "premise: the report matches the case"  # getattr: the clean control must run on the source before A3.6a
    monkeypatch.setitem(api_module._pending_failures, RESOLVE_ID, {
        "file_changes": [],
        "spec": BuildSpec(title="bf904a abort", description="d"),
        "work_dir": str(repo),
        "report": report,
        "timestamp": time.time(),
    })
    recorded = _record_git(monkeypatch)
    await _bounded(builder_module._run_git(["rev-parse", "HEAD"], str(repo)))  # control: the recorder sees the builder's git
    assert len(recorded) == 1 and recorded[0][-2:] == ["rev-parse", "HEAD"], f"premise: the recorder is live: {recorded}"
    recorded.clear()
    rt = MagicMock()
    tracked: list[Any] = []

    def capture(coro: Any, name: str | None = None) -> None:
        tracked.append(coro)

    response = await _bounded(build_router.resolve_build(
        BuildResolveRequest(build_id=RESOLVE_ID, resolution="abort"), runtime=rt, track_task=capture,
    ))

    assert recorded == [], f"the abort ran git: {recorded}"
    assert tracked == [], "the abort starts no background build"
    assert _head_ref(repo) == "captain-work", "the checkout stays where the failed build left it"
    assert RESOLVE_ID not in api_module._pending_failures, "the resolved failure leaves the cache"
    rt.emit_event.assert_called_once()
    event_type, data = rt.emit_event.call_args.args
    assert event_type == EventType.BUILD_RESOLVED and data["resolution"] == "abort", (event_type, data)
    if case == "clean":
        assert response == {"status": "ok", "resolution": "abort"}, response
        assert data["message"] == "Build aborted. Its changes were discarded when it failed.", data["message"]
    else:
        assert response["message"] == build_router.ABORT_CLEANUP_INCOMPLETE, response
        assert data["message"] == build_router.ABORT_CLEANUP_INCOMPLETE, data["message"]
        assert "bf904a: simulated" not in response["message"] and "bf904a: simulated" not in data["message"]


@pytest.mark.parametrize("resolution", ["commit_override", "retry_extended", "retry_targeted", "retry_fix", "retry_full"])
async def test_a_resolution_that_runs_a_build_is_refused_after_an_incomplete_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resolution: str
) -> None:
    api_module, build_router = _route_modules()
    repo = _on_captain_work(tmp_path / "repo")
    assert build_router._pending_failures is api_module._pending_failures, "premise: the router reads the seeded cache"
    assert RESOLVE_ID not in api_module._pending_failures, "premise: no entry is left over"
    assert build_router.operator_checkout_refusal(repo, build_router._REPO_ROOT) is None, "premise: the guard allows this tree"
    assert _head_ref(repo) == "captain-work", "premise: the checkout is on the Captain's branch"
    targeted = AsyncMock(return_value=(True, "1 passed", []))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", targeted)
    report = BuildFailureReport(cleanup_errors=["bf904a: simulated"])
    assert report.cleanup_errors, "premise: the cleanup was incomplete"
    monkeypatch.setitem(api_module._pending_failures, RESOLVE_ID, {
        "file_changes": [_create(NEW, "ok = 1\n")],
        "spec": BuildSpec(title="bf904a refused", description="d"),
        "work_dir": str(repo),
        "report": report,
        "timestamp": time.time(),
    })
    recorded = _record_git(monkeypatch)
    rt = MagicMock()
    rt.llm_client = None
    tracked: list[Any] = []

    def capture(coro: Any, name: str | None = None) -> None:
        tracked.append(coro)

    response = await _bounded(build_router.resolve_build(
        BuildResolveRequest(build_id=RESOLVE_ID, resolution=resolution), runtime=rt, track_task=capture,
    ))

    assert response == {"status": "error", "message": build_router.RESOLVE_CLEANUP_INCOMPLETE}, response
    assert tracked == [], "no background build was started"
    assert recorded == [], f"the refusal ran git: {recorded}"
    rt.emit_event.assert_not_called()
    targeted.assert_not_awaited()
    assert RESOLVE_ID in api_module._pending_failures, "the failure stays cached so abort remains available"

    aborted = await _bounded(build_router.resolve_build(
        BuildResolveRequest(build_id=RESOLVE_ID, resolution="abort"), runtime=rt, track_task=capture,
    ))

    assert aborted["message"] == build_router.ABORT_CLEANUP_INCOMPLETE, aborted
    assert RESOLVE_ID not in api_module._pending_failures


# ---------------------------------------------------------------------------
# BF-904a A4 (D31 to D35): R11 to R15
# ---------------------------------------------------------------------------

ABORT_DESCRIPTION = "Dismiss the failed build. Runs no git: its cleanup already ran; check the report for any cleanup notes"


# R11 (D31): a branch the build did not create is never deleted


@pytest.mark.parametrize("title", ["same", "different"])
async def test_a_build_never_deletes_a_branch_it_did_not_create(tmp_path: Path, title: str) -> None:
    repo = _on_captain_work(tmp_path / "repo")
    first = await _build(repo, [_create("src/probos/first.py", "f = 1\n")], title="bf904a repeat")
    assert first.success is True and first.commit_hash, f"premise: the first build committed: {first.error}"
    assert first.branch_name == "builder-bf904a-repeat", f"premise: the build branch is named from the title: {first.branch_name}"
    tip = _out(repo, "rev-parse", first.branch_name)
    assert tip.startswith(first.commit_hash), f"premise: the branch tip is the build's commit: {tip} {first.commit_hash}"
    assert _head_ref(repo) == "captain-work", "premise: the build returned to the Captain's branch"
    before = _state(repo)

    result = await _build(repo, _failing_changes(), title="bf904a repeat" if title == "same" else "bf904a other")

    after = _state(repo)
    if title == "same":
        assert result.error.startswith("Failed to create branch: branch builder-bf904a-repeat already exists"), result.error
        assert result.branch_name == "", result.branch_name
        assert result.files_written == [] and result.files_modified == [], (result.files_written, result.files_modified)
        assert "cleanup_errors" not in result.metadata, result.metadata
    else:
        assert result.error.startswith("Syntax errors"), f"control: the other title builds and fails late: {result.error}"
        assert (result.files_written, result.files_modified) == ([NEW, BAD], [TARGET, OTHER]), "control: the files were written"
    for label, was, now in zip(_STATE_PARTS, before, after):
        assert now == was, f"{title}: the second build changed the {label}: {was!r} -> {now!r}"
    assert _out(repo, "rev-parse", first.branch_name) == tip, "the first build's branch keeps its tip"


# R12 (D32): one file under two accepted spellings is restored to the bytes of its first snapshot


def _count_restore_writes(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Count every ``Path.write_bytes`` by lower-cased file name (a string compare only), then run the real one.
    Installed after the fixture is built: the build itself writes with ``write_text``, so these are the restore's."""
    counts: dict[str, int] = {}
    real_write_bytes = Path.write_bytes

    def write_bytes(self: Path, data: Any) -> int:
        counts[self.name.lower()] = counts.get(self.name.lower(), 0) + 1
        return real_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", write_bytes)
    return counts


@pytest.mark.parametrize("case", ["dot-main-main", "dot-main-fix", "case-alias", "hardlink", "found-deleted-recreated"])
async def test_one_file_under_two_spellings_is_restored_to_its_first_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    alias = "src/probos/A.py" if case == "case-alias" else "src/probos/./a.py"
    linked = "src/probos/b.py"
    seed = {**SEED, linked: "x = 1\n"} if case == "hardlink" else SEED
    repo = _plain_repo(tmp_path / "repo", seed)
    kwargs: dict[str, Any] = {}
    expected_writes: dict[str, int] | None = {"a.py": 1}
    failed_tests = (False, "1 failed", ["tests/test_x.py"])
    model: _FakeModel | None = None

    def modify(path: str, search: str, replace: str) -> dict[str, Any]:
        return {"path": path, "mode": "modify", "replacements": [{"search": search, "replace": replace}]}

    if case in ("dot-main-main", "case-alias"):
        if case == "case-alias" and not (repo / alias).exists():
            pytest.skip("this filesystem distinguishes case; the ./ cases cover aliasing here")
        assert os.path.samefile(repo / TARGET, repo / alias), "premise: the two spellings name one file"
        for spelling in (TARGET, alias):
            assert builder_write_refusal(spelling, str(repo)) is None, f"premise: {spelling} is an accepted spelling"
        changes = [modify(TARGET, "x = 1", "x = 2"), modify(alias, "x = 2", "x = 3"), _create(BAD, BROKEN)]
    elif case == "hardlink":
        (repo / linked).unlink()
        try:
            os.link(repo / TARGET, repo / linked)
        except OSError as exc:
            pytest.skip(f"this filesystem cannot hard link: {exc}")
        assert os.path.samefile(repo / TARGET, repo / linked), "premise: the two names are one file"
        assert _git(repo, "status", "--porcelain").stdout == "", "premise: the hard link leaves the tree clean"
        changes = [modify(TARGET, "x = 1", "x = 2"), modify(linked, "x = 2", "x = 3"), _create(BAD, BROKEN)]
        expected_writes = {"a.py": 1, "b.py": 1}
    elif case == "dot-main-fix":
        assert builder_write_refusal(alias, str(repo)) is None and os.path.samefile(repo / TARGET, repo / alias), (
            "premise: the alias is an accepted spelling of the file"
        )
        changes = [modify(alias, "x = 1", "x = 2"), _create(NEW, "ok = 1\n")]
        model = _FakeModel(f"===MODIFY: {TARGET}===\n===SEARCH===\nx = 2\n===REPLACE===\nx = 3\n===END REPLACE===\n===END MODIFY===\n")
        monkeypatch.setattr(builder_module, "_run_targeted_tests", AsyncMock(return_value=failed_tests))
        kwargs = {"run_tests": True, "max_fix_attempts": 1, "llm_client": model}
    else:
        changes = [modify(TARGET, "x = 1", "x = 2"), _create(NEW, "ok = 1\n")]
        model = _FakeModel(f"===FILE: {TARGET}===\nx = 3\n===END FILE===\n")
        deletions: list[int] = []

        async def delete_the_saved_file_once(work_dir: str, files: list[str], **kw: Any) -> tuple[bool, str, list[str]]:
            if not deletions:
                (repo / TARGET).unlink()  # the tests delete a file the build saved
                deletions.append(1)
            return failed_tests

        monkeypatch.setattr(builder_module, "_run_targeted_tests", delete_the_saved_file_once)
        kwargs = {"run_tests": True, "max_fix_attempts": 1, "llm_client": model}
        expected_writes = None

    before = _state(repo)
    counts = _count_restore_writes(monkeypatch)

    result = await _build(repo, changes, **kwargs)

    assert result.branch_name, f"premise: the build got as far as its branch: {result.error}"
    if case in ("dot-main-main", "case-alias", "hardlink"):
        assert result.error.startswith("Syntax errors"), f"premise: the build failed late: {result.error}"
        assert result.files_modified == [changes[0]["path"], changes[1]["path"]], f"premise: both spellings were modified: {result.files_modified}"
    else:
        assert model is not None and len(model.fix_prompts()) == 1, "premise: the model received one repair request"
        assert result.error.startswith("Tests failed after 1 fix attempt(s)"), result.error
        assert result.metadata["fix_loop_files"] == [TARGET], f"premise: the repair changed the file: {result.metadata}"
    if case == "found-deleted-recreated":
        assert TARGET in result.files_written + result.files_modified, "premise: the file is on the build's lists"
        assert TARGET not in result.files_written, "a saved file the tests deleted is modified, never created"
        assert (repo / TARGET).read_bytes() == ORIGINAL.encode(), "the saved bytes are written back"
    if expected_writes is not None:
        assert counts == expected_writes, f"{case}: restore writes per file: {counts}"
    assert "cleanup_errors" not in result.metadata, result.metadata
    after = _state(repo)
    compared = list(zip(_STATE_PARTS, before, after))
    if case == "hardlink":
        # BF-904a A6 (D38): NTFS refreshes the other hard link's directory entry lazily, so git's stat-based status can call
        # b.py modified for a moment although its bytes are the saved ones. Compare the content, not the status.
        assert os.path.samefile(repo / TARGET, repo / linked), "the two names are still one file"
        for name in (TARGET, linked):
            hashed = _git(repo, "hash-object", "--", name).stdout.strip()
            assert hashed == _out(repo, "rev-parse", f"HEAD:{name}"), f"{name}: the saved bytes are written back"
        # BF-904a A7 (D41): the status part is read as the next build's dirty check reads it: uncached.
        uncached = _git(repo, "-c", "core.fscache=false", "status", "--porcelain").stdout
        assert uncached == before[0], f"hardlink: the next build's dirty check would see {uncached!r}"
        compared = compared[1:]  # the cached porcelain status: replaced by the uncached read above
    for label, was, now in compared:
        assert now == was, f"{case}: the failed build changed the {label}: {was!r} -> {now!r}"


# R13 (D34): an exception inside a cleanup helper is reported, and the other steps run


class _Halt(BaseException):
    """A BaseException (as a cancellation is): the cleanup must not swallow it."""


@pytest.mark.parametrize("case", ["restore-raises", "reset-raises", "checkout-raises", "halt"])
async def test_an_exception_inside_the_cleanup_is_reported_and_the_rest_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    repo = _plain_repo(tmp_path / "repo")
    changes = _failing_changes()
    own_error = "Syntax errors"
    raised: dict[str, int] = {}
    exc_type: type[BaseException] = _Halt if case == "halt" else RuntimeError
    real_run_git = builder_module._run_git

    def raise_on(prefix: list[str]) -> None:
        async def run_git(args: list[str], work_dir: str, **kw: Any) -> tuple[int, str, str]:
            if args[: len(prefix)] == prefix:
                raised[prefix[0]] = raised.get(prefix[0], 0) + 1
                raise exc_type("bf904a: simulated cleanup failure")
            return await real_run_git(args, work_dir, **kw)

        monkeypatch.setattr(builder_module, "_run_git", run_git)

    if case in ("reset-raises", "halt"):
        changes = [
            {"path": TARGET, "mode": "modify", "replacements": [{"search": "x = 1", "replace": "x = 2"}]},
            _create(NEW, "ok = 1\n"),
        ]
        own_error = "Commit failed: bf904a: commit refused"

        async def add_then_refuse(files: list[str], message: str, work_dir: str) -> tuple[bool, str]:
            code, _stdout, _stderr = await real_run_git(["add", "--", *files], work_dir)
            assert code == 0, "premise: git add succeeds"
            return False, "bf904a: commit refused"

        monkeypatch.setattr(builder_module, "_git_add_and_commit", add_then_refuse)
        raise_on(["reset"])
    elif case == "checkout-raises":
        raise_on(["checkout", "-q"])
    else:
        armed = {"on": False}
        real_restore = builder_module._restore_pre_build_files
        real_write_bytes = Path.write_bytes
        real_exists = Path.exists

        def restore_armed(*args: Any, **kw: Any) -> list[str]:
            armed["on"] = True
            try:
                return real_restore(*args, **kw)
            finally:
                armed["on"] = False

        def write_bytes(self: Path, data: Any) -> int:
            if self.name == "other.py":  # a string comparison only: no filesystem call before the saved original
                raised["write_bytes"] = raised.get("write_bytes", 0) + 1
                raise RuntimeError("bf904a: simulated write failure")
            return real_write_bytes(self, data)

        def exists(self: Path, *args: Any, **kw: Any) -> bool:
            if armed["on"] and self.name == "fresh.py":
                raised["exists"] = raised.get("exists", 0) + 1
                raise RuntimeError("bf904a: simulated check failure")
            return real_exists(self, *args, **kw)

        monkeypatch.setattr(builder_module, "_restore_pre_build_files", restore_armed)
        monkeypatch.setattr(Path, "write_bytes", write_bytes)
        monkeypatch.setattr(Path, "exists", exists)

    before = _state(repo)

    if case == "halt":
        with pytest.raises(_Halt):
            await _build(repo, changes)
        assert raised == {"reset": 1}, f"premise: the reset was asked for once: {raised}"
        return

    result = await _build(repo, changes)

    assert result.success is False and result.branch_name, f"premise: the build failed after its branch: {result.error}"
    assert result.error.startswith(own_error), f"the build's own error comes first: {result.error}"
    assert SEPARATOR in result.error, result.error
    entries = result.metadata["cleanup_errors"]
    assert classify_build_failure(result, _spec()).cleanup_errors == entries
    root = repo / "src" / "probos"
    if case == "restore-raises":
        assert raised == {"write_bytes": 1, "exists": 1}, f"premise: each seam raised exactly once: {raised}"
        assert len(entries) == 2, entries
        assert entries[0].startswith("could not restore ") and entries[1].startswith("could not delete "), entries
        assert all(entry.endswith("(RuntimeError)") for entry in entries), entries
        assert (repo / TARGET).read_text(encoding="utf-8") == ORIGINAL, "the other saved file was still restored"
        assert not (repo / BAD).exists(), "the other created file was still deleted"
        assert _head_ref(repo) == before[1], "the checkout still returned to its ref"
        assert "builder-bf904a-probe" not in _refs(repo), "the build branch was still deleted"
    elif case == "reset-raises":
        assert raised == {"reset": 1}, f"premise: the reset was asked for once: {raised}"
        assert entries[0] == "git reset could not start (RuntimeError)", entries
        assert (repo / TARGET).read_text(encoding="utf-8") == ORIGINAL, "the saved file was still restored"
        assert not (root / "newpkg" / "fresh.py").exists(), "the created file was still deleted"
        assert _head_ref(repo) == before[1], "the checkout still returned to its ref"
    else:
        assert raised == {"checkout": 1}, f"premise: the return was asked for once: {raised}"
        assert len(entries) == 1, entries
        assert entries[0].startswith("could not return to ") and entries[0].endswith("branch builder-bf904a-probe kept"), entries
        assert (repo / TARGET).read_text(encoding="utf-8") == ORIGINAL, "the saved file was still restored"
        assert not (repo / NEW).exists() and not (repo / BAD).exists(), "the created files were still deleted"


# R14 (D33): the return checks out the ref exactly as git names it


@pytest.mark.parametrize("name", ["captain-work", "captain-work\u00a0"])
async def test_the_return_checks_out_the_exact_ref_git_named(tmp_path: Path, name: str) -> None:
    repo = _plain_repo(tmp_path / "repo")
    assert _git(repo, "branch", "captain-work").returncode == 0, "premise: the plain branch exists"
    made = _git(repo, "checkout", "-q", "-b", name) if name != "captain-work" else _git(repo, "checkout", "-q", name)
    assert made.returncode == 0, f"premise: git must accept the branch {name!r}: {made.stderr!r}"

    def raw_head() -> bytes:
        return _REAL_RUN(
            ["git", "symbolic-ref", "--short", "HEAD"], cwd=repo, capture_output=True, check=False,
            env=_control_env(), stdin=subprocess.DEVNULL, timeout=60,
        ).stdout

    assert raw_head() == (name + "\n").encode(), f"premise: git names HEAD exactly {name!r}: {raw_head()!r}"
    before = _state(repo)

    result = await _build(repo, _failing_changes())

    assert result.branch_name and result.error.startswith("Syntax errors"), f"premise: the build failed late: {result.error}"
    assert raw_head() == (name + "\n").encode(), f"the build left HEAD on {raw_head()!r}"
    assert "cleanup_errors" not in result.metadata, result.metadata
    for label, was, now in zip(_STATE_PARTS, before, _state(repo)):
        assert now == was, f"the failed build changed the {label}: {was!r} -> {now!r}"


# R15 (D35): the Abort option promises no checkout


@pytest.mark.parametrize(
    ("error", "category"),
    [
        ("timed out after 60s", "timeout"),
        ("1 failed", "test_failure"),
        ("SyntaxError", "syntax_error"),
        ("Request timeout", "llm_error"),
        ("Commit failed: x", "commit_error"),
    ],
)
def test_the_abort_option_promises_no_checkout(error: str, category: str) -> None:
    report = classify_build_failure(BuildResult(success=False, spec=_spec(), error=error), _spec())

    assert report.failure_category == category, f"premise: {error!r} is a {category} failure: {report.failure_category}"
    abort = [option for option in report.resolution_options if option["id"] == "abort"]
    assert len(abort) == 1, report.resolution_options
    assert abort[0]["description"] == ABORT_DESCRIPTION, abort[0]
    assert "main" not in abort[0]["description"], abort[0]


# ---------------------------------------------------------------------------
# BF-904a A5 (D36): R16
# ---------------------------------------------------------------------------

REPEAT_TITLE = "builder/bf904a-repeat"
REPEAT_SAFE = "builder-bf904a-repeat"
REPEAT_REF = f"refs/heads/{REPEAT_SAFE}"
COLLISION_LIST_ARGV = ["branch", "--list", "--format=%(refname)", REPEAT_SAFE]

# R16 (D36): the collision check compares the exact ref name git prints, never "any output"


_FAKE_ANSWERS = {
    "exact": (REPEAT_REF, True),
    "superstring": (f"{REPEAT_REF}-2", False),
    "prefix-of": ("refs/heads/builder-bf904a", False),
    "other-namespace": (f"refs/remotes/origin/{REPEAT_SAFE}", False),
    "legacy-mock": ("main", False),
    "crlf-two-lines": (f"refs/heads/main\r\n{REPEAT_REF}", True),
}


@pytest.mark.parametrize(
    "case",
    [*_FAKE_ANSWERS, "real-superstring", "real-checked-out-here", "real-other-worktree", "real-detached"],
)
async def test_the_collision_check_matches_the_exact_branch_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str,
) -> None:
    if case.startswith("real-"):
        await _collision_check_against_real_git(tmp_path, case)
        return
    answer, collides = _FAKE_ANSWERS[case]
    listed: list[list[str]] = []
    created: list[list[str]] = []

    async def fake(args: list[str], work_dir: str, **kwargs: Any) -> tuple[int, str, str]:
        if args[:2] == ["branch", "--list"]:
            listed.append(list(args))
            return 0, answer, ""
        if args[:2] == ["checkout", "-b"]:
            created.append(list(args))
            return 0, "", ""
        pytest.fail(f"{case}: unexpected git call {args!r}")

    monkeypatch.setattr(builder_module, "_run_git", fake)

    ok, message = await builder_module._git_create_branch(REPEAT_TITLE, str(tmp_path))

    assert listed == [COLLISION_LIST_ARGV], f"premise: the check asks git for the full ref name: {listed}"
    if collides:
        assert ok is False and "already exists" in message, (case, ok, message)
        assert created == [], f"{case}: a collision never reaches checkout -b: {created}"
    else:
        assert (ok, message) == (True, REPEAT_SAFE), (case, ok, message)
        assert len(created) == 1 and created[0][:3] == ["checkout", "-b", REPEAT_SAFE], (case, created)


async def _collision_check_against_real_git(tmp_path: Path, case: str) -> None:
    repo = _plain_repo(tmp_path / "repo")
    if case == "real-superstring":
        assert _git(repo, "branch", f"{REPEAT_SAFE}-2").returncode == 0, "premise: the superstring branch is made"
    elif case == "real-checked-out-here":
        assert _git(repo, "checkout", "-q", "-b", REPEAT_SAFE).returncode == 0, "premise: the branch is checked out"
    elif case == "real-other-worktree":
        added = _git(repo, "worktree", "add", "-q", "-b", REPEAT_SAFE, str(tmp_path / "wt"), "main")
        assert added.returncode == 0, f"premise: git worktree add must succeed on this host: {added.stderr}"
    else:
        assert _git(repo, "branch", REPEAT_SAFE).returncode == 0, "premise: the branch is made"
        assert _git(repo, "checkout", "-q", "--detach", "HEAD").returncode == 0, "premise: HEAD is detached"
    try:
        printed = _out(repo, "branch", "--list", "--format=%(refname)", REPEAT_SAFE)
        assert printed in ("", REPEAT_REF), f"premise: git prints only the exact ref for a glob-free pattern: {printed!r}"

        ok, message = await builder_module._git_create_branch(REPEAT_TITLE, str(repo))

        if case == "real-superstring":
            assert (ok, message) == (True, REPEAT_SAFE), (case, ok, message)
            names = _out(repo, "branch", "--format=%(refname:short)").split()
            assert REPEAT_SAFE in names and f"{REPEAT_SAFE}-2" in names, names
        else:
            assert ok is False and "already exists" in message, (case, ok, message)
            assert _out(repo, "rev-parse", "--verify", REPEAT_REF), "the branch still exists"
            if case == "real-checked-out-here":
                assert _head_ref(repo) == REPEAT_SAFE, "HEAD is still that branch"
            if case == "real-detached":
                assert _git(repo, "symbolic-ref", "-q", "HEAD").returncode != 0, "HEAD is still detached"
    finally:
        if case == "real-other-worktree":
            _git(repo, "worktree", "remove", "--force", str(tmp_path / "wt"))


# ---------------------------------------------------------------------------
# BF-904a A7: the start ref reaches git unchanged or the build is refused; the full ref; an uncached dirty
# check; directory pruning never stops the cleanup
# ---------------------------------------------------------------------------

D39_REFUSAL_START = "The checkout's branch `captain-\\udcff` cannot be passed to git unchanged"


def _raw_symbolic_ref(repo: Path, *args: str) -> bytes:
    """The bytes of ``git symbolic-ref <args> HEAD``, read with the real runner and no decoding."""
    return _REAL_RUN(
        ["git", "symbolic-ref", *args, "HEAD"], cwd=repo, capture_output=True, check=False,
        env=_control_env(), stdin=subprocess.DEVNULL, timeout=60,
    ).stdout


# R17 (D39): a start branch git would not receive unchanged is refused before any write


@pytest.mark.parametrize("case", ["windows-surrogate", "windows-nbsp", "posix-surrogate", "real-host", "real-packed-ref"])
async def test_a_branch_git_would_not_receive_unchanged_is_refused_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    if case == "real-host":
        if sys.getfilesystemencoding() != "utf-8":
            pytest.skip(f"the filesystem encoding is {sys.getfilesystemencoding()!r}, not utf-8: the host model needs utf-8")
        assert builder_module._ref_survives_argv("captain-work\u00a0") is True
        assert builder_module._ref_survives_argv("captain-\udcff") is (sys.platform != "win32")
        return

    if case == "real-packed-ref":
        repo = _plain_repo(tmp_path / "repo")
        sha = _out(repo, "rev-parse", "HEAD")
        packed = repo / ".git" / "packed-refs"
        header = packed.read_bytes() if packed.exists() else b"# pack-refs with: peeled fully-peeled sorted \n"
        packed.write_bytes(header + f"{sha} ".encode() + b"refs/heads/captain-\xff\n")
        (repo / ".git" / "HEAD").write_bytes(b"ref: refs/heads/captain-\xff\n")
        raw = _raw_symbolic_ref(repo, "-q")
        assert raw == b"refs/heads/captain-\xff\n", f"premise: git names HEAD exactly as the packed ref: {raw!r}"
        before = _state(repo)

        result = await _build(repo, _failing_changes())

        if sys.platform == "win32":
            assert result.error.startswith(D39_REFUSAL_START), result.error
        else:
            assert result.error.startswith("Syntax errors"), f"premise: the build failed late: {result.error}"
            assert _raw_symbolic_ref(repo, "-q") == b"refs/heads/captain-\xff\n", "the build left HEAD on another ref"
            assert "cleanup_errors" not in result.metadata, result.metadata
        assert _state(repo) == before, "the tree is as the build found it"
        return

    name = "captain-work\u00a0" if case == "windows-nbsp" else "captain-\udcff"
    repo = _on_captain_work(tmp_path / "repo")
    assert getattr(builder_module, "_argv_bytes", os.fsencode) is os.fsencode, "premise: the seam is the real os.fsencode"
    if case.startswith("windows"):
        def model(text: str) -> bytes:
            return text.encode("utf-8", "surrogatepass")
    else:
        def model(text: str) -> bytes:
            return text.encode("utf-8", "surrogateescape")
    monkeypatch.setattr(builder_module, "_argv_bytes", model, raising=False)
    real_run_git = builder_module._run_git
    symbolic: list[list[str]] = []

    async def run_git(args: list[str], work_dir: str, **kw: Any) -> tuple[int, str, str]:
        if args[:1] == ["symbolic-ref"]:
            symbolic.append(list(args))
            return 0, f"refs/heads/{name}\n", ""
        return await real_run_git(args, work_dir, **kw)

    dirty = AsyncMock(return_value=True)
    monkeypatch.setattr(builder_module, "_run_git", run_git)
    monkeypatch.setattr(builder_module, "_is_dirty_working_tree", dirty)
    before = _state(repo)

    result = await _build(repo, _failing_changes())

    assert len(symbolic) == 1, f"premise: the start branch was read once: {symbolic}"
    if case == "windows-surrogate":
        assert result.error.startswith(D39_REFUSAL_START), result.error
        assert "\udcff" not in result.error, "the name is shown escaped"
        dirty.assert_not_awaited()
        assert result.branch_name == "", "no build branch"
        assert _state(repo) == before, "nothing was written"
    else:
        assert result.error.startswith("Working tree has uncommitted changes"), f"control: the name passes the check: {result.error}"
        dirty.assert_awaited_once()


# R18 (D40): a tag that shares the branch's name does not detach the return


@pytest.mark.parametrize("name", ["main", "captain-work\u00a0"])
async def test_the_return_names_the_branch_when_a_tag_shares_its_name(tmp_path: Path, name: str) -> None:
    repo = _plain_repo(tmp_path / "repo")
    if name != "main":
        assert _git(repo, "checkout", "-q", "-b", name).returncode == 0, f"premise: git must accept the branch {name!r}"
    assert _git(repo, "tag", name).returncode == 0, f"premise: git must accept the tag {name!r}"
    short = _raw_symbolic_ref(repo, "--short")
    full = _raw_symbolic_ref(repo, "-q")
    assert short == f"heads/{name}\n".encode(), f"premise: git disambiguates the short name: {short!r}"
    assert full == f"refs/heads/{name}\n".encode(), f"premise: the full ref: {full!r}"
    before = _state(repo)

    result = await _build(repo, _failing_changes())

    assert result.branch_name and result.error.startswith("Syntax errors"), f"premise: the build failed late: {result.error}"
    assert _raw_symbolic_ref(repo, "-q") == full, "HEAD was detached or moved by the return"
    assert "cleanup_errors" not in result.metadata, result.metadata
    for label, was, now in zip(_STATE_PARTS, before, _state(repo)):
        assert now == was, f"the failed build changed the {label}: {was!r} -> {now!r}"


# R19 (D40): the branch read takes only a local branch


@pytest.mark.parametrize(
    ("case", "answer", "expected"),
    [
        ("heads", (0, "refs/heads/x\u00a0\n", ""), "x\u00a0"),
        ("tag", (0, "refs/tags/v1\n", ""), None),
        ("remote", (0, "refs/remotes/origin/main\n", ""), None),
        ("detached", (1, "", ""), None),
    ],
)
async def test_the_branch_read_takes_only_a_local_branch(
    monkeypatch: pytest.MonkeyPatch, case: str, answer: tuple[int, str, str], expected: str | None
) -> None:
    seen: list[tuple[list[str], dict[str, Any]]] = []

    async def run_git(args: list[str], work_dir: str, **kw: Any) -> tuple[int, str, str]:
        seen.append((list(args), dict(kw)))
        return answer

    monkeypatch.setattr(builder_module, "_run_git", run_git)

    branch = await builder_module._git_current_branch("unused")

    assert [args for args, _kw in seen] == [["symbolic-ref", "-q", "HEAD"]], f"{case}: the full ref is read: {seen}"
    assert seen[0][1].get("lossless") is True, f"{case}: the read is lossless: {seen[0][1]}"
    assert branch == expected, f"{case}: {branch!r}"


# R20 (D41): the dirty check reads a restored hard link uncached


@pytest.mark.parametrize("case", ["argv", "next-build"])
async def test_the_dirty_check_reads_hard_links_uncached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    if case == "argv":
        repo = _plain_repo(tmp_path / "repo")
        real_exec = asyncio.create_subprocess_exec
        recorded: list[list[str]] = []

        async def exec_recorder(*argv: Any, **kwargs: Any) -> Any:
            if argv and argv[0] == "git":
                recorded.append([str(part) for part in argv])
            return await real_exec(*argv, **kwargs)

        monkeypatch.setattr(builder_module.asyncio, "create_subprocess_exec", exec_recorder)

        assert await builder_module._is_dirty_working_tree(str(repo)) is False
        status = [argv for argv in recorded if "status" in argv]
        assert status == [["git", *HARDENED_GIT_CONFIG_ARGS, "-c", "core.fscache=false", "status", "--porcelain"]], status
        return

    linked = "src/probos/b.py"
    repo = _plain_repo(tmp_path / "repo", {**SEED, linked: "x = 1\n"})
    (repo / linked).unlink()
    try:
        os.link(repo / TARGET, repo / linked)
    except OSError as exc:
        pytest.skip(f"this filesystem cannot hard link: {exc}")
    assert os.path.samefile(repo / TARGET, repo / linked), "premise: the two names are one file"
    assert _git(repo, "status", "--porcelain").stdout == "", "premise: the hard link leaves the tree clean"

    def modify(path: str, search: str, replace: str) -> dict[str, Any]:
        return {"path": path, "mode": "modify", "replacements": [{"search": search, "replace": replace}]}

    changes = [modify(TARGET, "x = 1", "x = 2"), modify(linked, "x = 2", "x = 3"), _create(BAD, BROKEN)]
    errors: list[str] = []
    for i in range(16):  # nothing runs between two builds: the next build's dirty check owns the first status read
        result = await _build(repo, changes, title=f"bf904a next {i}")
        errors.append(result.error)

    refused = [(i, error) for i, error in enumerate(errors) if not error.startswith("Syntax errors")]
    assert refused == [], f"{len(refused)} of 16 builds were refused or failed early: {refused}"
    assert os.path.samefile(repo / TARGET, repo / linked), "the two names are still one file"
    for name in (TARGET, linked):
        hashed = _git(repo, "hash-object", "--", name).stdout.strip()
        assert hashed == _out(repo, "rev-parse", f"HEAD:{name}"), f"{name}: the saved bytes are written back"
    assert _git(repo, "-c", "core.fscache=false", "status", "--porcelain").stdout == ""


# R21 (D42): a failed directory prune does not stop the cleanup


@pytest.mark.parametrize("exc", [RuntimeError, _Halt])
async def test_a_failed_directory_prune_does_not_stop_the_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc: type[BaseException]
) -> None:
    repo = _plain_repo(tmp_path / "repo")
    raised: list[str] = []
    real_rmdir = Path.rmdir

    def rmdir(self: Path) -> None:
        if self.name == "newpkg" and not raised:  # a string comparison only: no filesystem call before the saved original
            raised.append(self.name)
            raise exc("bf904a: simulated prune failure")
        real_rmdir(self)

    monkeypatch.setattr(Path, "rmdir", rmdir)
    before = _state(repo)

    if exc is _Halt:
        with pytest.raises(_Halt):
            await _build(repo, _failing_changes())
        assert raised == ["newpkg"], f"premise: the prune was reached once: {raised}"
        return

    result = await _build(repo, _failing_changes())

    assert result.files_written.index(NEW) < result.files_written.index(BAD), f"premise: a created file follows the failing prune: {result.files_written}"
    assert raised == ["newpkg"], f"premise: the seam raised once: {raised}"
    assert result.error.startswith("Syntax errors") and SEPARATOR not in result.error, result.error
    assert "cleanup_errors" not in result.metadata, result.metadata
    assert not (repo / NEW).exists() and not (repo / BAD).exists(), "the created files are gone"
    assert (repo / TARGET).read_text(encoding="utf-8") == ORIGINAL, "the saved file is restored"
    assert _head_ref(repo) == before[1], "the return still ran"
    assert "builder-bf904a-probe" not in _refs(repo), "the build branch was still deleted"
    assert _state(repo) == before, "the tree is as the build found it"


# R22 (D43): a raising log handler does not stop the cleanup

_CLEANUP_FORMATS = (
    "Cleaned up untracked file from failed build: %s",
    "Cleaning up failed build branch '%s'",
    "BuilderAgent: build cleanup incomplete: %s",
)
R22_ID = "bf904a-m2-r22"


class _RaisingHandler(logging.Handler):
    """Raises from ``emit`` for the cleanup's three log lines only (a string comparison); passes every other record."""

    def __init__(self, exc: type[BaseException]) -> None:
        super().__init__(logging.DEBUG)
        self.exc = exc
        self.raised: list[tuple[str, str]] = []  # (format string, funcName)

    def emit(self, record: logging.LogRecord) -> None:
        if record.msg in _CLEANUP_FORMATS:
            self.raised.append((record.msg, record.funcName))
            raise self.exc("bf904a: simulated handler failure")


@pytest.mark.parametrize("case", ["failed-build", "committed", "halt"])
async def test_a_raising_log_handler_does_not_stop_the_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    repo = _plain_repo(tmp_path / "repo")
    handler = _RaisingHandler(_Halt if case == "halt" else RuntimeError)
    builder_logger = builder_module.logger
    old_level = builder_logger.level
    builder_logger.setLevel(logging.DEBUG)  # setLevel clears the logger's enabled-for cache
    builder_logger.addHandler(handler)
    cached: dict[str, Any] | None = None
    try:
        if case == "halt":
            with pytest.raises(_Halt):
                await _build(repo, _failing_changes())
            assert [m for m, _f in handler.raised] == [_CLEANUP_FORMATS[0]], f"premise: the first deletion's line raised once: {handler.raised}"
            return
        if case == "committed":
            _fail_the_return(monkeypatch)
            result = await _build(repo, [_create(NEW, "ok = 1\n")])
            assert result.success is True and result.commit_hash, f"a commit stays a success: {result.error}"
            assert result.metadata.get("cleanup_errors"), "the failed return is recorded"
            assert handler.raised == [(_CLEANUP_FORMATS[2], "execute_approved_build")], handler.raised
            return
        api_module, build_router = _route_modules()
        assert build_router._pending_failures is api_module._pending_failures, "premise: the router reads the cache"
        assert R22_ID not in api_module._pending_failures, "premise: no entry is left over"
        before = _state(repo)
        rt = SimpleNamespace(emit_event=MagicMock(), llm_client=None)
        try:
            await _bounded(build_router._execute_build(R22_ID, _failing_changes(), _spec(), str(repo), rt, run_tests=False))
            cached = api_module._pending_failures.get(R22_ID)
        finally:
            api_module._pending_failures.pop(R22_ID, None)
    finally:
        builder_logger.removeHandler(handler)
        builder_logger.setLevel(old_level)

    deletions = [f for m, f in handler.raised if m == _CLEANUP_FORMATS[0]]
    assert len(deletions) >= 2 and set(deletions) == {"_restore_pre_build_files"}, f"every deletion's line raised and the rest ran: {handler.raised}"
    assert handler.raised[-1] == (_CLEANUP_FORMATS[1], "execute_approved_build"), handler.raised
    assert cached is not None, "the failure is cached"
    assert cached["report"].cleanup_errors == [], "a lost log line is not a cleanup error (D30 would refuse retries)"
    failures = [c.args[1] for c in rt.emit_event.call_args_list if c.args[0] == EventType.BUILD_FAILURE]
    assert len(failures) == 1 and "report" in failures[0] and "error" not in failures[0], failures
    assert "builder-bf904a-probe" not in _refs(repo), "the build branch was deleted"
    assert _state(repo) == before, "the tree, HEAD and branches are as the build found them"
