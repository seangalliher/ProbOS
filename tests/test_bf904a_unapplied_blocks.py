"""BF-904a (#1585), milestone M3: an unmatched block, a missing target and an empty outcome are refusals.

Before M3 a MODIFY block that could not apply was skipped silently: a missing target was logged and
passed over, and a SEARCH block that was not found was logged and passed over, so one file could be
committed with only some of its replacements. A change list in which nothing applied wrote nothing,
skipped the tests, and reported ``success=True`` with no commit. The repair loop skipped a missing
target and an unmatched block the same way, so a partial repair could pass the tests and be committed.
M3 refuses all of it:

* a missing MODIFY target, and a SEARCH block that is not found, are refusals in ``validation_errors``
  that name the block's index and the file (never a block's text); the file with an unmatched block is
  not written at all;
* a repair response with one such block applies NONE of its blocks and ends the repair loop
  (``_unapplied_blocks`` matches the blocks in order against the text the earlier blocks of the
  same response leave, creates first, as the parser orders them);
* a main-loop list with one such block writes nothing, so no partial file reaches the review or the
  tests; one file is one ``_same_file_key``, and its text is what the disk returns (``_round_trip``); a new file's key is the host's full-path form of its physical path, so a spelling the host unifies is that file;
* a non-empty change list that changed nothing is a failure, "No change applied: <paths>"; an empty
  list keeps today's result.

Rules this file keeps:

* Real git in repositories under ``tmp_path`` (repo-local identity, ``commit.gpgsign false``,
  ``core.autocrlf false``); the helpers are copied, not imported, from ``tests/test_bf904a_git_hardening.py``
  and ``tests/test_bf904a_failed_build_restore.py``.
* "Left as it found it" is read with plain git by ``_state``: the porcelain status, the HEAD ref, every
  local branch with its tip, and every file's bytes. Every case also asserts what the build DID before it
  failed (the files it wrote, the repair it received), so an early refusal that touches nothing cannot
  pass for a refusal of the block.
* The test's own git calls use ``_control_env()``: the process environment minus every ``GIT_*`` name, and
  an autouse fixture deletes every ``GIT_*`` name from ``os.environ``, so no test depends on the invoking
  shell.
* No sleeps, nothing ordered by wall-clock time, every subprocess the tests start has a timeout, every
  await is bounded.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from collections.abc import Awaitable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive import builder as builder_module
from probos.cognitive.builder import BuilderAgent, BuildResult, BuildSpec, execute_approved_build
from probos.cognitive.builder_paths import builder_write_refusal, fix_loop_write_refusal

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
pytestmark = needs_git

TARGET = "src/probos/a.py"
OTHER = "src/probos/other.py"
NEW = "src/probos/newpkg/fresh.py"
GONE = "src/probos/gone.py"
HELPER = "src/probos/helper.py"
THIRD = "src/probos/third.py"
LINKED = "src/probos/linked.py"
CASE_ALIAS = "src/probos/A.py"
FRESH = "src/probos/fresh.py"
ORIGINAL = "x = 1\n"
SEED = {TARGET: ORIGINAL, OTHER: "y = 1\n"}

# The real runner, captured at import before any test patches ``subprocess.run``: the tests' own git
# calls go through it, so a recorder installed by a test never sees them.
_REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def _no_ambient_git_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every ``GIT_*`` name from the process environment for the test's duration (see the module docstring)."""
    for name in list(os.environ):
        if name.upper().startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Helpers (copied from tests/test_bf904a_git_hardening.py and tests/test_bf904a_failed_build_restore.py)
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


def _head_ref(tree: Path) -> str:
    """The branch HEAD names, or the commit of a detached HEAD (plain git)."""
    named = _REAL_RUN(
        ["git", "symbolic-ref", "-q", "--short", "HEAD"], cwd=tree, capture_output=True, check=False,
        env=_control_env(), stdin=subprocess.DEVNULL, timeout=60,
    )  # bytes, so a ref ending in Unicode whitespace is read exactly as git names it
    if named.returncode == 0:
        return named.stdout.decode("utf-8", "surrogateescape").removesuffix("\n")
    return _out(tree, "rev-parse", "HEAD")


def _state(tree: Path) -> tuple[str, str, list[str], dict[str, bytes]]:
    """What "the tree as the build found it" means, read with plain git: the porcelain status, the HEAD ref (the
    branch, or the commit of a detached HEAD), every local branch with its tip, and every file's bytes."""
    status = _git(tree, "status", "--porcelain")
    assert status.returncode == 0, f"premise: git status must succeed: {status.stderr}"
    tips = _git(tree, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads")
    assert tips.returncode == 0, f"premise: git for-each-ref must succeed: {tips.stderr}"
    return status.stdout, _head_ref(tree), sorted(tips.stdout.split("\n")), _tree(tree)  # split at LF only; a ref may hold U+0085 or U+2028


def _modify_block(path: str, search: str, replace: str) -> str:
    """A ``===MODIFY:===`` block of a model reply holding one SEARCH/REPLACE pair."""
    return (
        f"===MODIFY: {path}===\n"
        f"===SEARCH===\n{search}\n===REPLACE===\n{replace}\n===END REPLACE===\n"
        "===END MODIFY===\n"
    )


class _FakeModel:
    """A model client whose every answer is *reply* (the code review reads it too). It keeps every prompt and notes
    each repair request, and only those, in *events*."""

    def __init__(self, reply: str, events: list[str]) -> None:
        self._reply = reply
        self._events = events
        self.prompts: list[str] = []

    async def complete(self, request: Any) -> SimpleNamespace:
        self.prompts.append(request.prompt)
        if "Test Fix Required" in request.prompt:
            self._events.append("repair")
        return SimpleNamespace(content=self._reply)

    def fix_prompts(self) -> list[str]:
        """The prompts of the repair requests among the calls so far; the code review's prompt is not one."""
        return [prompt for prompt in self.prompts if "Test Fix Required" in prompt]


class _FakeTargetedTests:
    """Stands in for ``_run_targeted_tests``: run number n reports ``outcomes[n - 1]`` (the last one repeats). Every
    run notes "run" in *events* and keeps what the watched file held at that moment (None while it does not exist)."""

    def __init__(self, watched: Path, outcomes: list[bool], events: list[str]) -> None:
        self.await_count = 0
        self.seen: list[str | None] = []
        self._watched = watched
        self._outcomes = outcomes
        self._events = events

    async def __call__(self, work_dir: str, changed: list[str], **kwargs: Any) -> tuple[bool, str, list[str]]:
        self.await_count += 1
        self._events.append("run")
        self.seen.append(self._watched.read_text(encoding="utf-8") if self._watched.is_file() else None)
        passed = self._outcomes[min(self.await_count, len(self._outcomes)) - 1]
        return passed, ("1 passed" if passed else "1 failed"), ["tests/test_x.py"]


# ---------------------------------------------------------------------------
# S1, S2, S3: the main loop
# ---------------------------------------------------------------------------


async def test_an_unmatched_search_block_fails_the_build_and_writes_nothing(tmp_path: Path) -> None:
    repo = _plain_repo(tmp_path / "repo")
    changes = [{
        "path": TARGET,
        "mode": "modify",
        "replacements": [
            {"search": "x = 1", "replace": "x = 2"},
            {"search": "no such text", "replace": "z"},
        ],
    }]
    text = (repo / TARGET).read_text(encoding="utf-8")
    assert "x = 1" in text and "no such text" not in text, "premise: block 0's text is in the file and block 1's is not"
    before = _state(repo)
    assert before[0] == "", f"premise: the tree starts clean: {before[0]!r}"

    result = await _build(repo, changes)

    assert result.branch_name, f"premise: the build got as far as its branch: {result.error}"
    assert result.success is False
    assert not result.commit_hash
    assert "SEARCH block 1 not found in src/probos/a.py; refused" in result.error, result.error
    assert "SEARCH block 0" not in result.error, "only the unmatched block is named"
    assert result.files_modified == [], "a file with an unmatched block is not written at all, block 0 included"
    assert _state(repo) == before


async def test_a_missing_modify_target_fails_the_build(tmp_path: Path) -> None:
    repo = _plain_repo(tmp_path / "repo")
    changes = [
        {"path": GONE, "mode": "modify", "replacements": [{"search": "a", "replace": "b"}]},
        _create(NEW, "ok = 1\n"),
    ]
    assert not (repo / GONE).exists(), "premise: the MODIFY target is absent"
    assert not (repo / NEW).exists(), "premise: the created file is absent before the build"
    before = _state(repo)
    assert before[0] == "", f"premise: the tree starts clean: {before[0]!r}"

    result = await _build(repo, changes)

    assert result.branch_name, f"premise: the build got as far as its branch: {result.error}"
    assert result.files_written == [], "a list with a missing target writes nothing (A10 D46)"
    assert result.success is False
    assert not result.commit_hash
    assert "MODIFY target src/probos/gone.py does not exist; refused" in result.error, result.error
    assert not (repo / NEW).exists(), "the other change is never written"
    assert _state(repo) == before


async def test_a_change_list_that_changes_nothing_fails_with_a_reason(tmp_path: Path) -> None:
    repo = _plain_repo(tmp_path / "repo")
    changes = [{"path": TARGET, "mode": "modify", "replacements": [{"search": "x = 1", "replace": "x = 1"}]}]
    assert "x = 1" in (repo / TARGET).read_text(encoding="utf-8"), "premise: the block matches, so it is a no-op and not a refusal"
    before = _state(repo)
    assert before[0] == "", f"premise: the tree starts clean: {before[0]!r}"

    result = await _build(repo, changes)

    assert result.branch_name, f"premise: the build got as far as its branch: {result.error}"
    assert result.success is False
    assert result.error == "No change applied: src/probos/a.py", result.error
    assert not result.commit_hash
    assert _state(repo) == before

    # Control, on a fresh tree: an empty change list keeps today's result, a success with nothing to commit.
    control = _plain_repo(tmp_path / "control")
    control_before = _state(control)
    empty = await _build(control, [])
    assert empty.branch_name, f"premise: the empty build got as far as its branch: {empty.error}"
    assert empty.success is True and not empty.error, empty.error
    assert not empty.commit_hash
    assert _state(control) == control_before


# ---------------------------------------------------------------------------
# S4, S5: the repair loop
# ---------------------------------------------------------------------------

# case -> (the repair reply, the (mode, path) pairs the parser must return for it, the refusal the build must carry)
REPAIRS: dict[str, tuple[str, list[tuple[str, str]], str]] = {
    "unmatched": (
        _modify_block(TARGET, "x = 2", "x = 3") + _modify_block(OTHER, "absent", "q"),
        [("modify", TARGET), ("modify", OTHER)],
        f"SEARCH block 0 not found in {OTHER}; refused",
    ),
    "missing": (
        _modify_block(TARGET, "x = 2", "x = 3") + _modify_block(GONE, "a", "b"),
        [("modify", TARGET), ("modify", GONE)],
        f"MODIFY target {GONE} does not exist; refused",
    ),
}


@pytest.mark.parametrize("case", ["unmatched", "missing"])
async def test_a_repair_with_a_block_that_cannot_apply_is_refused_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    repo = _plain_repo(tmp_path / "repo")
    reply, expected_parse, refusal = REPAIRS[case]
    blocks = BuilderAgent._parse_file_blocks(reply)
    assert [(block["mode"], block["path"]) for block in blocks] == expected_parse, "premise: two MODIFY blocks, TARGET's first"
    for block in blocks:
        assert fix_loop_write_refusal(block["path"], str(repo)) is None, (
            f"premise: BF-898's rule admits {block['path']}, so the refusal below is the block's"
        )
    if case == "unmatched":
        assert "absent" not in (repo / OTHER).read_text(encoding="utf-8"), "premise: the second block's SEARCH text is not in its file"
    else:
        assert not (repo / GONE).exists(), "premise: the second block's target is absent"
    events: list[str] = []
    model = _FakeModel(reply, events)
    runner = _FakeTargetedTests(repo / TARGET, [False], events)  # every run fails
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    changes = [{"path": TARGET, "mode": "modify", "replacements": [{"search": "x = 1", "replace": "x = 2"}]}]
    before = _state(repo)
    assert before[0] == "", f"premise: the tree starts clean: {before[0]!r}"

    result = await _build(repo, changes, run_tests=True, max_fix_attempts=2, llm_client=model)

    assert result.branch_name, f"premise: the build got as far as its branch: {result.error}"
    assert runner.seen[:1] == ["x = 2\n"], (
        "premise: the build's own block was applied before the first run, so the repair's first block would apply as well"
    )
    assert events[:2] == ["run", "repair"], f"premise: the runner was awaited once, then the model was asked for a repair: {events}"
    assert result.success is False
    assert runner.await_count == 1 and events == ["run", "repair"], f"the loop stopped at the refusal: {events}"
    assert len(model.fix_prompts()) == 1 and result.fix_attempts == 1
    assert "fix_loop_files" not in result.metadata, "no block of the refused repair was applied, TARGET's included"
    assert refusal in result.error, result.error
    assert _state(repo) == before


async def test_a_repair_that_creates_then_modifies_a_file_applies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The pre-check's control: a block that modifies a file an earlier block of the same response creates is not refused."""
    repo = _plain_repo(tmp_path / "repo")
    reply = f"===FILE: {HELPER}===\nh = 1\n===END FILE===\n" + _modify_block(HELPER, "h = 1", "h = 2")
    blocks = BuilderAgent._parse_file_blocks(reply)
    assert [(block["mode"], block["path"]) for block in blocks] == [("create", HELPER), ("modify", HELPER)], (
        "premise: the parser puts the create first"
    )
    assert fix_loop_write_refusal(HELPER, str(repo)) is None, "premise: BF-898's rule admits the helper"
    assert not (repo / HELPER).exists(), "premise: the helper does not exist before the repair, so the modify has no file on disk to match"
    events: list[str] = []
    model = _FakeModel(reply, events)
    runner = _FakeTargetedTests(repo / HELPER, [False, True], events)  # fails once, then passes
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)

    result = await _build(repo, [_create(NEW, "ok = 1\n")], run_tests=True, max_fix_attempts=2, llm_client=model)

    assert events == ["run", "repair", "run"], f"premise: one failed run, one repair, one passing run: {events}"
    assert runner.seen == [None, "h = 2\n"], "premise: both blocks of the repair were applied before the rerun"
    assert result.success is True, result.error
    assert result.commit_hash
    assert _blob(repo, result.branch_name, HELPER) == "h = 2\n"


# case -> (the repair reply, the runner's outcomes)
SAME_FILE_REPAIRS: dict[str, tuple[str, list[bool]]] = {
    "dependent": (
        _modify_block(TARGET, "x = 2", "x = 3") + _modify_block(TARGET, "x = 3", "x = 4"),
        [False, True],  # fails once, then passes after the repair
    ),
    "vanished": (
        _modify_block(TARGET, "x = 2", "x = 5") + _modify_block(TARGET, "x = 2", "x = 6"),
        [False],  # every run fails
    ),
}


@pytest.mark.parametrize("case", ["dependent", "vanished"])
async def test_the_blocks_of_one_file_in_a_repair_are_matched_against_the_text_the_earlier_blocks_leave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    repo = _plain_repo(tmp_path / "repo")
    reply, outcomes = SAME_FILE_REPAIRS[case]
    blocks = BuilderAgent._parse_file_blocks(reply)
    assert [(block["mode"], block["path"]) for block in blocks] == [("modify", TARGET), ("modify", TARGET)], (
        "premise: two MODIFY blocks for TARGET, in order"
    )
    assert fix_loop_write_refusal(TARGET, str(repo)) is None, "premise: BF-898's rule admits TARGET, so the outcome below is the pre-check's"
    events: list[str] = []
    model = _FakeModel(reply, events)
    runner = _FakeTargetedTests(repo / TARGET, outcomes, events)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    changes = [{"path": TARGET, "mode": "modify", "replacements": [{"search": "x = 1", "replace": "x = 2"}]}]
    before = _state(repo)
    assert before[0] == "", f"premise: the tree starts clean: {before[0]!r}"

    result = await _build(repo, changes, run_tests=True, max_fix_attempts=2, llm_client=model)

    assert result.branch_name, f"premise: the build got as far as its branch: {result.error}"
    assert runner.seen[:1] == ["x = 2\n"], "premise: the file holds the build's own block's text at the first run, which is the repair's starting text"
    if case == "dependent":
        assert "x = 3" not in runner.seen[0], "premise: the second block's SEARCH text is not in the file at the time of the repair"
        assert result.success is True, result.error
        assert result.commit_hash
        assert events == ["run", "repair", "run"], events
        assert runner.seen == ["x = 2\n", "x = 4\n"], "the second block was matched against the text the first block left"
        assert _blob(repo, result.branch_name, TARGET) == "x = 4\n"
    else:
        assert "x = 2" in runner.seen[0], (
            "premise: block 1's SEARCH text IS in the file at the time of the repair, so only block 0 makes it vanish"
        )
        assert result.success is False
        assert runner.await_count == 1 and events == ["run", "repair"], f"the loop stopped at the refusal: {events}"
        assert len(model.fix_prompts()) == 1 and result.fix_attempts == 1
        assert "fix_loop_files" not in result.metadata, "no block of the refused repair was applied"
        # The parser makes each MODIFY block its own change, so the refused second block is block 0 of its change (A9.5).
        assert f"SEARCH block 0 not found in {TARGET}; refused" in result.error, result.error
        assert result.error.count("SEARCH block") == 1, "exactly one refusal: the first change applies as written, the second is refused"
        assert _state(repo) == before


async def test_a_repair_target_that_cannot_be_read_is_refused_whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _plain_repo(tmp_path / "repo")
    undecodable = b"\xff\xfe = 1\n"
    (repo / OTHER).write_bytes(undecodable)
    assert _git(repo, "add", "-A").returncode == 0, "premise: git add must succeed"
    assert _git(repo, "commit", "-q", "-m", "undecodable other").returncode == 0, "premise: the undecodable file is committed"
    with pytest.raises(UnicodeDecodeError):
        undecodable.decode("utf-8")
    reply = _modify_block(OTHER, "a", "b")
    blocks = BuilderAgent._parse_file_blocks(reply)
    assert [(block["mode"], block["path"]) for block in blocks] == [("modify", OTHER)], "premise: one MODIFY block on OTHER"
    assert fix_loop_write_refusal(OTHER, str(repo)) is None, "premise: BF-898's rule admits OTHER, so the refusal below is the read's"
    events: list[str] = []
    model = _FakeModel(reply, events)
    runner = _FakeTargetedTests(repo / TARGET, [False], events)  # every run fails
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    changes = [{"path": TARGET, "mode": "modify", "replacements": [{"search": "x = 1", "replace": "x = 2"}]}]
    before = _state(repo)
    assert before[0] == "", f"premise: the tree starts clean: {before[0]!r}"

    result = await _build(repo, changes, run_tests=True, max_fix_attempts=2, llm_client=model)

    assert result.branch_name, f"premise: the build got as far as its branch: {result.error}"
    assert result.success is False
    assert runner.await_count == 1 and events == ["run", "repair"], f"the loop stopped at the refusal: {events}"
    assert "fix_loop_files" not in result.metadata, "no block of the refused repair was applied"
    assert f"MODIFY target {OTHER} could not be read; refused" in result.error, result.error
    assert _state(repo) == before
    assert (repo / OTHER).read_bytes() == undecodable, "the undecodable file is untouched"


async def test_the_empty_outcome_names_each_path_once_in_sorted_order(tmp_path: Path) -> None:
    repo = _plain_repo(tmp_path / "repo", {TARGET: "x = 1\n", OTHER: "y = 1\n", THIRD: "z = 1\n"})
    changes = [
        {"path": THIRD, "mode": "modify", "replacements": [{"search": "z = 1", "replace": "z = 1"}]},
        {"path": OTHER, "mode": "modify", "replacements": [{"search": "y = 1", "replace": "y = 1"}]},
        {"path": TARGET, "mode": "modify", "replacements": [{"search": "x = 1", "replace": "x = 1"}]},
        {"path": TARGET, "mode": "modify", "replacements": [{"search": "x = 1", "replace": "x = 1"}]},
    ]
    for path, text in ((THIRD, "z = 1"), (OTHER, "y = 1"), (TARGET, "x = 1")):
        assert text in (repo / path).read_text(encoding="utf-8"), f"premise: the block's text is in {path}, so no block is a refusal"
    before = _state(repo)
    assert before[0] == "", f"premise: the tree starts clean: {before[0]!r}"

    result = await _build(repo, changes)

    assert result.branch_name, f"premise: the build got as far as its branch: {result.error}"
    assert result.success is False
    assert result.error == "No change applied: src/probos/a.py, src/probos/other.py, src/probos/third.py", result.error
    assert not result.commit_hash
    assert _state(repo) == before


# ---------------------------------------------------------------------------
# S9 to S13 (A10): one file per physical target, the disk's round trip, a whole-list pre-pass, a late match
# ---------------------------------------------------------------------------


def _round_trip_oracle(tmp_path: Path, text: str) -> str:
    """What ``read_text`` returns after ``write_text(text)`` on this host, measured and not assumed."""
    probe = tmp_path / "probe.txt"
    probe.write_text(text, encoding="utf-8")
    return probe.read_text(encoding="utf-8")


def _alias_repo(tmp_path: Path, kind: str) -> tuple[Path, str]:
    """A seeded repository in which a second accepted name reaches TARGET's file: a hard link, or a case variant."""
    repo = _plain_repo(tmp_path / "repo")
    if kind == "hardlink":
        try:
            os.link(repo / TARGET, repo / LINKED)
        except OSError:
            pytest.skip("the filesystem has no hard links")
        assert _git(repo, "add", "-A").returncode == 0, "premise: git add must succeed"
        assert _git(repo, "commit", "-q", "-m", "link").returncode == 0, "premise: the link is committed"
        return repo, LINKED
    if not (repo / CASE_ALIAS).exists():
        pytest.skip("the filesystem does not fold case, so A.py is another file; the hardlink cases cover identity here")
    return repo, CASE_ALIAS


@pytest.mark.parametrize("case", ["vanished", "dependent"])
@pytest.mark.parametrize("kind", ["hardlink", "case"])
async def test_two_names_of_one_file_in_a_repair_are_matched_as_one_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, case: str
) -> None:
    repo, alias = _alias_repo(tmp_path, kind)
    if case == "vanished":
        reply = _modify_block(TARGET, "x = 2", "x = 5") + _modify_block(alias, "x = 2", "x = 6")
    else:
        reply = _modify_block(TARGET, "x = 2", "x = 3") + _modify_block(alias, "x = 3", "x = 4")
    blocks = BuilderAgent._parse_file_blocks(reply)
    assert os.path.samefile(repo / TARGET, repo / alias), "premise: the two names are one file"
    assert fix_loop_write_refusal(alias, str(repo)) is None, "premise: BF-898's rule admits the alias"
    assert [(block["mode"], block["path"]) for block in blocks] == [("modify", TARGET), ("modify", alias)], (
        "premise: two MODIFY blocks, TARGET's first, then the alias's"
    )
    if kind == "hardlink":
        assert builder_module._write_target_key(str(repo), TARGET) != builder_module._write_target_key(str(repo), LINKED), (
            "premise: the write-target keys differ, so only the file identity joins the two names"
        )
    events: list[str] = []
    model = _FakeModel(reply, events)
    runner = _FakeTargetedTests(repo / TARGET, [False, True], events)  # fails once, then passes after the repair
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    changes = [{"path": TARGET, "mode": "modify", "replacements": [{"search": "x = 1", "replace": "x = 2"}]}]
    before = _state(repo)
    assert before[0] == "", f"premise: the tree starts clean: {before[0]!r}"

    result = await _build(repo, changes, run_tests=True, max_fix_attempts=2, llm_client=model)

    assert result.branch_name, f"premise: the build got as far as its branch: {result.error}"
    assert runner.seen[:1] == ["x = 2\n"], "premise: the file holds the build's own block's text at the first run"
    if case == "vanished":
        assert result.success is False, f"the second name's block cannot apply to the text the first leaves: {result.error}"
        assert runner.await_count == 1 and events == ["run", "repair"], f"the loop stopped at the refusal: {events}"
        assert result.fix_attempts == 1
        assert "fix_loop_files" not in result.metadata, "no block of the refused repair was applied"
        assert f"SEARCH block 0 not found in {alias}; refused" in result.error, result.error
        assert result.error.count("SEARCH block") == 1, result.error
        if kind == "case":
            assert _state(repo) == before
        else:
            assert _state(repo)[1:] == before[1:]
            assert os.path.samefile(repo / TARGET, repo / alias), "the link is still one file"
            status = _git(repo, "-c", "core.fscache=false", "status", "--porcelain")
            assert status.returncode == 0 and status.stdout == "", f"the tree is clean: {status.stdout!r} {status.stderr}"
    else:
        assert "x = 3" not in runner.seen[0], "premise: the alias block's SEARCH text is not in the file before the repair"
        assert result.success is True, result.error
        assert result.commit_hash
        assert events == ["run", "repair", "run"], events
        assert runner.seen == ["x = 2\n", "x = 4\n"], "the alias block was matched against the text the first block left"
        assert _blob(repo, result.branch_name, TARGET) == "x = 4\n"


@pytest.mark.parametrize("case", ["vanished", "dependent", "created"])
async def test_a_repair_is_matched_against_the_text_the_disk_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    repo = _plain_repo(tmp_path / "repo")
    in_memory = "x = 3\r\nz = 1\n"
    disk = _round_trip_oracle(tmp_path, in_memory)
    assert "\r" not in disk, "premise: this host's read never returns a carriage return"
    events: list[str] = []
    if case == "created":
        created = "h = 1\r\nk = 1\n"
        disk_h = _round_trip_oracle(tmp_path, created)
        assert "\r" not in disk_h, "premise: the created file reads back without a carriage return"
        reply = f"===FILE: {HELPER}===\n{created}===END FILE===\n" + _modify_block(HELPER, disk_h.rstrip("\n"), "h = 2")
        blocks = BuilderAgent._parse_file_blocks(reply)
        assert [(block["mode"], block["path"]) for block in blocks] == [("create", HELPER), ("modify", HELPER)], (
            "premise: the parser puts the create first"
        )
        assert blocks[0]["content"] == created, "premise: the parsed content keeps the carriage return"
        assert not (repo / HELPER).exists(), "premise: the helper does not exist before the repair"
        outcomes = [False, True]
        watched = repo / HELPER
    else:
        second = "x = 3\r\nz = 1" if case == "vanished" else disk.rstrip("\n")
        reply = _modify_block(TARGET, "x = 2", "x = 3\r\nz = 1") + _modify_block(TARGET, second, "x = 4")
        blocks = BuilderAgent._parse_file_blocks(reply)
        assert [(block["mode"], block["path"]) for block in blocks] == [("modify", TARGET), ("modify", TARGET)], (
            "premise: two MODIFY blocks for TARGET, in order"
        )
        assert blocks[0]["replacements"][0]["replace"] == "x = 3\r\nz = 1", "premise: the parsed replacement keeps the carriage return"
        if case == "vanished":
            assert second in in_memory and second not in disk, "premise: the second SEARCH is in the in-memory text and not on the disk"
        else:
            assert second in disk and second not in in_memory, "premise: the second SEARCH is on the disk and not in the in-memory text"
        outcomes = [False, True]
        watched = repo / TARGET
    model = _FakeModel(reply, events)
    runner = _FakeTargetedTests(watched, outcomes, events)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    changes = [{"path": TARGET, "mode": "modify", "replacements": [{"search": "x = 1", "replace": "x = 2"}]}]
    before = _state(repo)
    assert before[0] == "", f"premise: the tree starts clean: {before[0]!r}"

    result = await _build(repo, changes, run_tests=True, max_fix_attempts=2, llm_client=model)

    assert result.branch_name, f"premise: the build got as far as its branch: {result.error}"
    if case == "vanished":
        assert runner.seen[:1] == ["x = 2\n"], "premise: the file holds the build's own block's text at the first run"
        assert result.success is False, f"the second block cannot apply to the text the disk returns: {result.error}"
        assert runner.await_count == 1 and events == ["run", "repair"], f"the loop stopped at the refusal: {events}"
        assert result.fix_attempts == 1
        assert "fix_loop_files" not in result.metadata, "no block of the refused repair was applied"
        assert f"SEARCH block 0 not found in {TARGET}; refused" in result.error, result.error
        assert result.error.count("SEARCH block") == 1, result.error
        assert _state(repo) == before
    elif case == "dependent":
        assert runner.seen[:1] == ["x = 2\n"], "premise: the file holds the build's own block's text at the first run"
        assert result.success is True, result.error
        assert result.commit_hash
        assert events == ["run", "repair", "run"], events
        assert runner.seen == ["x = 2\n", "x = 4\n"], "the second block was matched against the text the disk returns"
        assert _blob(repo, result.branch_name, TARGET) == "x = 4\n"
    else:
        assert result.success is True, result.error
        assert result.commit_hash
        assert events == ["run", "repair", "run"], events
        assert runner.seen == [None, "h = 2\n"], "the modify was matched against the text the disk returns for the created file"
        assert _blob(repo, result.branch_name, HELPER) == "h = 2\n"


async def test_no_change_of_a_list_with_an_unmatched_block_reaches_the_review_or_the_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _plain_repo(tmp_path / "repo")
    changes = BuilderAgent._parse_file_blocks(
        _modify_block(OTHER, "y = 1", "y = 2") + _modify_block(TARGET, "x = 1", "x = 2") + _modify_block(TARGET, "no such text", "z")
    )
    assert [(change["mode"], change["path"]) for change in changes] == [("modify", OTHER), ("modify", TARGET), ("modify", TARGET)], (
        "premise: three MODIFY changes, in order"
    )
    events: list[str] = []
    runner = _FakeTargetedTests(repo / TARGET, [True], events)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    before = _state(repo)
    assert before[0] == "", f"premise: the tree starts clean: {before[0]!r}"

    result = await _build(repo, changes, run_tests=True)

    assert result.branch_name, f"premise: the build got as far as its branch: {result.error}"
    assert result.success is False
    assert not result.commit_hash
    assert runner.await_count == 0, "the tests never ran: no partial file reached them"
    assert result.files_modified == [] and result.files_written == [], (result.files_modified, result.files_written)
    assert "SEARCH block 0 not found in src/probos/a.py; refused" in result.error, result.error
    assert result.error.count("SEARCH block") == 1, result.error
    assert _state(repo) == before


async def test_only_the_first_occurrence_is_replaced_before_the_next_block_is_matched(tmp_path: Path) -> None:
    """A control: the pre-check replaces one occurrence, as the writer does."""
    repo = _plain_repo(tmp_path / "repo", {TARGET: "a = 1\na = 1\n", OTHER: "y = 1\n"})
    changes = [{
        "path": TARGET,
        "mode": "modify",
        "replacements": [{"search": "a = 1", "replace": "a = 2"}, {"search": "a = 1", "replace": "a = 3"}],
    }]
    assert (repo / TARGET).read_text(encoding="utf-8").count("a = 1") == 2, "premise: the text holds the SEARCH text twice"

    result = await _build(repo, changes)

    assert result.success is True, result.error
    assert result.commit_hash
    assert result.files_modified == [TARGET], result.files_modified
    assert _blob(repo, result.branch_name, TARGET) == "a = 2\na = 3\n"


@pytest.mark.parametrize("which", ["main", "repair"])
async def test_the_write_time_checks_refuse_what_the_pre_check_missed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, which: str
) -> None:
    monkeypatch.setattr(builder_module, "_unapplied_blocks", lambda changes, work_dir: [])
    repo = _plain_repo(tmp_path / "repo")
    before = _state(repo)
    assert before[0] == "", f"premise: the tree starts clean: {before[0]!r}"
    if which == "main":
        changes = [
            {
                "path": TARGET,
                "mode": "modify",
                "replacements": [{"search": "x = 1", "replace": "x = 2"}, {"search": "no such text", "replace": "z"}],
            },
            {"path": GONE, "mode": "modify", "replacements": [{"search": "a", "replace": "b"}]},
        ]
        assert "no such text" not in (repo / TARGET).read_text(encoding="utf-8"), "premise: block 1's text is not in the file"
        assert not (repo / GONE).exists(), "premise: the MODIFY target is absent"

        result = await _build(repo, changes)

        assert result.branch_name, f"premise: the build got as far as its branch: {result.error}"
        assert result.success is False
        assert "SEARCH block 1 not found in src/probos/a.py; refused" in result.error, result.error
        assert "MODIFY target src/probos/gone.py does not exist; refused" in result.error, result.error
        assert result.files_modified == []
        assert _state(repo) == before
    else:
        reply = SAME_FILE_REPAIRS["vanished"][0]
        blocks = BuilderAgent._parse_file_blocks(reply)
        assert [(block["mode"], block["path"]) for block in blocks] == [("modify", TARGET), ("modify", TARGET)], (
            "premise: two MODIFY blocks for TARGET, in order"
        )
        events: list[str] = []
        model = _FakeModel(reply, events)
        runner = _FakeTargetedTests(repo / TARGET, [False, True], events)
        monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
        changes = [{"path": TARGET, "mode": "modify", "replacements": [{"search": "x = 1", "replace": "x = 2"}]}]

        result = await _build(repo, changes, run_tests=True, max_fix_attempts=2, llm_client=model)

        assert result.branch_name, f"premise: the build got as far as its branch: {result.error}"
        assert runner.seen[:1] == ["x = 2\n"], "premise: the file holds the build's own block's text at the first run"
        assert result.success is False
        assert not result.commit_hash
        assert runner.await_count == 1, f"the loop stopped at the late refusal: {events}"
        assert result.fix_attempts == 1
        assert result.metadata["fix_loop_files"] == [TARGET], result.metadata
        assert f"SEARCH block 0 not found in {TARGET} when applied; refused" in result.error, result.error
        assert _state(repo) == before, "the refusal keeps the normal cleanup"


# ---------------------------------------------------------------------------
# S14 (A11): a new file's other spellings are the file the host writes
# ---------------------------------------------------------------------------


def _host_unifies(tmp_path: Path, canonical: str, alias: str) -> bool:
    """True when this host's file calls reach one file by both names (answered by writing, never by a platform name)."""
    target = tmp_path / "oracle" / canonical
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("f = 1\n", encoding="utf-8")
    return (tmp_path / "oracle" / alias).is_file()


@pytest.mark.parametrize(
    ("canonical", "alias", "visiting"),
    [
        pytest.param(FRESH, "src//probos/fresh.py", False, id="double-slash"),
        pytest.param(FRESH, "src/./probos/fresh.py", False, id="dot-segment"),
        pytest.param(FRESH, "src/probos/fresh.py.", False, id="trailing-dot"),
        pytest.param(FRESH, "src/probos/fresh.py .", False, id="space-dot"),
        pytest.param(NEW, "src/probos/newpkg./fresh.py", False, id="new-dir-dot"),
        pytest.param(FRESH, "src/probos/Fresh.py", False, id="new-case"),
        pytest.param(FRESH, "src/probos/fresh.py.", True, id="visiting"),
    ],
)
async def test_a_new_file_named_again_under_another_spelling_is_the_file_the_host_writes(
    tmp_path: Path, canonical: str, alias: str, visiting: bool
) -> None:
    repo = _plain_repo(tmp_path / "repo")
    changes = BuilderAgent._parse_file_blocks(
        f"===FILE: {canonical}===\nf = 1\n===END FILE===\n" + _modify_block(alias, "f = 1", "f = 1")
    )
    if visiting:
        for block in changes:
            if "replacements" not in block:
                block["base"] = ""  # as copilot_adapter.py does for a parsed whole-file block
    unified = _host_unifies(tmp_path, canonical, alias)

    assert [(c["mode"], c["path"]) for c in changes] == [("create", canonical), ("modify", alias)], (
        "premise: the CREATE comes first, then the MODIFY under the alias"
    )
    assert builder_write_refusal(canonical, str(repo)) is None, "premise: the canonical name is an allowed write"
    assert builder_write_refusal(alias, str(repo)) is None, "premise: the alias is an allowed write"
    assert not (repo / canonical).exists(), "premise: the file does not exist yet"
    if visiting:
        assert changes[0]["base"] == "", "premise: the CREATE carries an empty base"
        assert "base" not in changes[1], "premise: the MODIFY carries no base"
    if canonical == FRESH and alias in ("src//probos/fresh.py", "src/./probos/fresh.py"):
        assert unified is True, "every host joins these names"
    if alias == "src/probos/Fresh.py" and unified and os.path.normcase("A") == "A":
        pytest.skip("a case-folding POSIX filesystem: the A10.10 false refusal")
    before = _state(repo)
    assert before[0] == "", f"premise: the tree starts clean: {before[0]!r}"

    result = await _build(repo, changes)

    if unified:
        assert result.success is True, result.error
        assert result.commit_hash
        assert result.files_written == [canonical], result.files_written
        assert result.files_modified == [], result.files_modified
        assert _blob(repo, result.branch_name, canonical) == "f = 1\n"
    else:
        assert result.success is False
        assert not result.commit_hash
        assert f"MODIFY target {alias} does not exist; refused" in result.error, result.error
        assert result.files_written == [], result.files_written
        assert _state(repo) == before


# ---------------------------------------------------------------------------
# S15 and S16 (A12): the physical path first, then the host's full-path form
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["dependent", "vanished"])
def test_a_work_directory_named_through_a_symbolic_link_and_dotdot_is_keyed_where_its_files_are(
    tmp_path: Path, case: str
) -> None:
    repo, alias = _alias_repo(tmp_path / "actual", "hardlink")
    (tmp_path / "actual" / "subdir").mkdir()
    (tmp_path / "v").mkdir()
    try:
        os.symlink(tmp_path / "actual" / "subdir", tmp_path / "v" / "link", target_is_directory=True)
    except OSError:
        pytest.skip("this host cannot create a directory symbolic link without a privilege (Windows error 1314)")
    work = os.path.join(str(tmp_path), "v", "link", "..", "repo")
    if not (Path(work) / TARGET).is_file():
        pytest.skip("this host takes '..' lexically (Win32 full-path rules), so the spelling names another directory")
    assert os.path.samefile(work, repo), "premise: the kernel takes '..' after the link, so the spelling is the repository"
    assert not os.path.exists(os.path.abspath(work)), "premise: the lexical form of the spelling names no directory"
    assert os.path.samefile(Path(work) / TARGET, Path(work) / alias), "premise: the two names are one file"
    second = "x = 2" if case == "dependent" else "x = 1"
    changes = BuilderAgent._parse_file_blocks(_modify_block(TARGET, "x = 1", "x = 2") + _modify_block(alias, second, "x = 3"))
    assert [(c["mode"], c["path"]) for c in changes] == [("modify", TARGET), ("modify", alias)], "premise: two MODIFY blocks"

    refusals = builder_module._unapplied_blocks(changes, work)

    if case == "dependent":
        assert refusals == [], "the alias block is matched against the text the first block leaves"
    else:
        assert refusals == [f"SEARCH block 0 not found in {alias}; refused"], refusals


def test_a_target_key_is_the_full_path_form_of_the_physical_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as m:  # markers that resolve nothing: no path resolution inside a patched os function
        m.setattr(os.path, "realpath", lambda p, *args, **kwargs: os.fspath(p) + "|r")
        m.setattr(os.path, "abspath", lambda p: os.fspath(p) + "|a")
        got = builder_module._same_file_key(str(tmp_path), FRESH)
    assert got[0] == "path", got  # os.stat of a marked name fails on every host
    assert got[1].endswith("fresh.py|r|a"), "realpath first, then abspath: " + got[1]
    assert got[1].count("|") == 2, "each applied once: " + got[1]


# ---------------------------------------------------------------------------
# E2: privacy
# ---------------------------------------------------------------------------


async def test_no_refusal_message_or_log_carries_file_content(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    content_sentinel = "BF904A-CONTENT"
    search_sentinel = "BF904A-SEARCH"
    repo = _plain_repo(tmp_path / "repo", {TARGET: f'secret = "{content_sentinel}"\n', OTHER: "y = 1\n"})
    changes = [{"path": TARGET, "mode": "modify", "replacements": [{"search": search_sentinel, "replace": "z"}]}]
    text = (repo / TARGET).read_text(encoding="utf-8")
    assert content_sentinel in text and search_sentinel not in text, "premise: the file holds the content, not the SEARCH text"
    caplog.set_level(logging.DEBUG)

    result = await _build(repo, changes)

    assert result.success is False
    assert f"SEARCH block 0 not found in {TARGET}; refused" in result.error, (
        f"premise: the block was refused, so the messages below are the refusal's: {result.error}"
    )
    assert any(record.name == "probos.cognitive.builder" for record in caplog.records), (
        "premise: the capture holds the build's own records, so their absence of the sentinels is a finding"
    )
    for sentinel in (content_sentinel, search_sentinel):
        assert sentinel not in result.error, f"the error carries {sentinel}"
        leaked = [record.getMessage() for record in caplog.records if sentinel in record.getMessage()]
        assert not leaked, f"a log record carries {sentinel}: {leaked}"
