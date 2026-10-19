"""BF-896 (#1550), milestone M2: the executor's side of the visiting build's confinement.

What the visiting adapter hands ``execute_approved_build`` for a changed file is a whole-file
``modify`` block, ``{"path", "mode": "modify", "content", "base"}``, with no ``replacements``.
Before BF-896 the executor's modify branch applied only ``replacements``: that block logged
"no changes applied", the build reported success and nothing was committed. These tests drive
the REAL executor on real temp git repositories (``run_tests=False`` unless a test says so) and
read the outcome back through git (``git show <branch>:path``): the executor commits on its own
branch and checks ``main`` out again, so the working tree shows the OLD text.

Rules this file keeps:

* Every refusal has its positive control, built on a sibling fixture and asserted FIRST: the
  same block (or the same pinned build) lands when nothing is wrong.
* A probe whose setup could not discriminate fails loudly. The premise assertions say what the
  setup had to achieve: ``rev-parse --absolute-git-dir`` really moved, the localizer really
  produced an excerpt, the repair loop really received the block, the spy really saw the git.
* Fixtures live under ``tmp_path``; repositories carry repo-local identity and
  ``commit.gpgsign false``; the helpers are copied, not imported, from the BF-894 tests.

Evidence limit: the producer half (the adapter's disk scan emitting these blocks) and the whole
adapter -> executor chain are crossed by the M3 seam test; here the blocks are written in the
exact shape the adapter emits.
"""

from __future__ import annotations

import inspect
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import ANY, MagicMock

import pytest

from probos.cognitive import builder as builder_module
from probos.cognitive import copilot_adapter as adapter_module
from probos.cognitive.builder import (
    BuilderAgent,
    BuildResult,
    BuildSpec,
    execute_approved_build,
    repository_identity,
)
from probos.cognitive.code_reviewer import CodeReviewAgent
from probos.runtime import ProbOSRuntime

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

TARGET = "src/probos/a.py"
OTHER = "src/probos/other.py"
NEW = "src/probos/newpkg/fresh.py"
BAD = "src/probos/bad.py"
ORIGINAL = "x = 1\n"
SEED = {TARGET: ORIGINAL, OTHER: "y = 1\n"}
BROKEN = "def broken(:\n"
IDENTITY_ARGS = ["rev-parse", "--absolute-git-dir"]


# ---------------------------------------------------------------------------
# Helpers (copied from tests/test_bf894_builder_write_boundary.py and adapted)
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )


def _init_repo(path: Path, branch: str, files: dict[str, str]) -> None:
    path.mkdir(parents=True)
    for args in (
        ("init", "-q", "-b", branch),
        ("config", "user.email", "bf896@example.invalid"),
        ("config", "user.name", "BF896 Tester"),
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
        subprocess.run(["attrib", "-h", str(pointer)], check=True, capture_output=True)
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


def _spec(title: str = "bf896 probe") -> BuildSpec:
    return BuildSpec(title=title, description="")


def _whole(path: str, content: str, **extra: Any) -> dict[str, Any]:
    """A whole-file modify block in the shape the visiting adapter's scan emits (``base`` via extra)."""
    return {"path": path, "mode": "modify", "content": content, **extra}


def _create(path: str, content: str) -> dict[str, Any]:
    return {"path": path, "mode": "create", "content": content}


async def _build(work_dir: Path, changes: list[dict[str, Any]], title: str = "bf896 probe", **kwargs: Any) -> BuildResult:
    kwargs.setdefault("run_tests", False)
    return await execute_approved_build(changes, _spec(title), str(work_dir), **kwargs)


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


class _DirtyCheckSpy:
    def __init__(self, real: Any) -> None:
        self._real = real
        self.calls = 0

    async def __call__(self, work_dir: str) -> bool:
        self.calls += 1
        return await self._real(work_dir)


class _FakeLLM:
    """Replies with *reply* to everything and keeps the prompts it was sent."""

    def __init__(self, reply: str = "") -> None:
        self._reply = reply
        self.prompts: list[str] = []

    async def complete(self, request: Any) -> SimpleNamespace:
        self.prompts.append(request.prompt)
        return SimpleNamespace(content=self._reply)


# ---------------------------------------------------------------------------
# 1. The whole-file modify block: compare-and-swap on `base`
# ---------------------------------------------------------------------------


async def _assert_whole_file_control_lands(root: Path) -> None:
    """The positive control of every refusal below: the same block with the true base lands."""
    repo = _plain_repo(root / "control")
    result = await _build(repo, [_whole(TARGET, "x = 2\n", base=ORIGINAL)], "bf896 control")
    assert result.success and result.commit_hash, f"control: the whole-file modify with its true base must land: {result.error}"
    assert _blob(repo, result.branch_name, TARGET) == "x = 2\n"


@needs_git
async def test_whole_file_modify_block_lands_and_commits(tmp_path: Path) -> None:
    repo = _plain_repo(tmp_path / "repo")
    main_before = _git(repo, "rev-parse", "main").stdout.strip()
    assert _blob(repo, "main", TARGET) == ORIGINAL, "premise: the file is committed with the text the block is based on"
    assert (repo / TARGET).read_text(encoding="utf-8") == ORIGINAL, "premise: and checked out"

    result = await _build(repo, [_whole(TARGET, "x = 2\n", base=ORIGINAL)])

    assert result.success, result.error
    assert result.commit_hash, "a whole-file modify must be committed, not silently dropped (the pre-BF-896 defect)"
    assert result.files_modified == [TARGET] and result.files_written == []
    assert _blob(repo, result.branch_name, TARGET) == "x = 2\n"
    assert _git(repo, "show", "--name-only", "--format=", result.branch_name).stdout.split() == [TARGET]
    assert _git(repo, "rev-parse", "main").stdout.strip() == main_before, "the change lives on the build branch, not main"


@needs_git
@pytest.mark.parametrize(
    "stale_base",
    ["x = 0\n", "x = 1\n  ... [lines 2-9 omitted] ...\n", ORIGINAL + "\n", ""],
    ids=["older-text", "localized-excerpt", "one-extra-newline", "empty-string"],
)
async def test_whole_file_modify_against_a_stale_base_is_refused(tmp_path: Path, stale_base: str) -> None:
    await _assert_whole_file_control_lands(tmp_path)
    repo = _plain_repo(tmp_path / "probe")
    main_before = _git(repo, "rev-parse", "main").stdout.strip()
    assert stale_base != (repo / TARGET).read_text(encoding="utf-8"), "premise: the base really is stale"

    result = await _build(repo, [_whole(TARGET, "x = 2\n", base=stale_base)])

    assert result.success is False
    assert TARGET in result.error, "the refusal must name the file"
    assert not result.commit_hash
    assert result.files_modified == [] and result.files_written == []
    assert (repo / TARGET).read_text(encoding="utf-8") == ORIGINAL, "the file must be unchanged"
    assert _git(repo, "rev-parse", "main").stdout.strip() == main_before
    assert _refs(repo) == ["main"], "the failed build's branch is cleaned up"


@needs_git
@pytest.mark.parametrize("extra", [{}, {"base": None}], ids=["no-base-key", "base-is-none"])
async def test_whole_file_modify_without_base_is_refused(tmp_path: Path, extra: dict[str, Any]) -> None:
    await _assert_whole_file_control_lands(tmp_path)
    repo = _plain_repo(tmp_path / "probe")
    main_before = _git(repo, "rev-parse", "main").stdout.strip()

    result = await _build(repo, [_whole(TARGET, "x = 2\n", **extra)])

    assert result.success is False
    assert TARGET in result.error, "a modify that cannot prove what it was generated against is a visible refusal"
    assert not result.commit_hash
    assert result.files_modified == []
    assert (repo / TARGET).read_text(encoding="utf-8") == ORIGINAL, "the file must be unchanged"
    assert _git(repo, "rev-parse", "main").stdout.strip() == main_before
    assert _refs(repo) == ["main"]


@needs_git
@pytest.mark.parametrize(
    "extra",
    [{}, {"content": "WHOLE = 1\n", "base": "x = 1\ny = 2\n"}],
    ids=["replacements-only", "replacements-win-over-content-and-base"],
)
async def test_replacement_modify_is_unchanged(tmp_path: Path, extra: dict[str, Any]) -> None:
    # BF-896 repair R1-2/R1-3: this case used to carry a deliberately stale base ("not what is on disk"),
    # which pinned "replacements ignore base". Any block carrying a base key is now compare-and-swap, so
    # the base is the TRUE current text here; what the case still pins is that replacements win over content.
    repo = _plain_repo(tmp_path / "repo", {TARGET: "x = 1\ny = 2\n"})
    block = {"path": TARGET, "mode": "modify", "replacements": [{"search": "x = 1", "replace": "x = 10"}], **extra}

    result = await _build(repo, [block])

    assert result.success, result.error
    assert result.commit_hash and result.files_modified == [TARGET] and result.files_written == []
    assert _blob(repo, result.branch_name, TARGET) == "x = 10\ny = 2\n", "SEARCH/REPLACE semantics, never whole-file"


@needs_git
@pytest.mark.parametrize(
    "block_extra",
    [
        {"replacements": [], "content": "WHOLE = 1\n"},
        {},
        {"content": None},
        {"content": 7, "base": ORIGINAL},
    ],
    ids=["empty-replacements-key-present", "no-replacements-no-content", "content-is-none", "content-is-not-a-str"],
)
async def test_modify_blocks_outside_the_whole_file_shape_change_nothing_and_fail(
    tmp_path: Path, block_extra: dict[str, Any]
) -> None:
    """A block is a whole-file change only with NO ``replacements`` key AND a ``str`` ``content``.

    Anything else writes nothing. BF-904a (#1585): a change list that changed nothing is a failure
    with a reason ("No change applied"), no longer a success with nothing to commit.
    """
    await _assert_whole_file_control_lands(tmp_path)
    repo = _plain_repo(tmp_path / "probe")
    tree_before = _tree(repo)

    result = await _build(repo, [{"path": TARGET, "mode": "modify", **block_extra}])

    assert result.success is False and result.error == f"No change applied: {TARGET}", result.error
    assert not result.commit_hash and result.files_modified == [] and result.files_written == []
    assert _tree(repo) == tree_before
    assert _refs(repo) == ["main"]


@needs_git
async def test_replacement_modify_of_an_absent_target_without_base_is_refused(tmp_path: Path) -> None:
    """BF-904a (#1585): this used to pin the silent absent-target skip, which let the other block commit alone.

    A missing MODIFY target is now a refusal that blocks the commit, and the other block is never written.
    """
    repo = _plain_repo(tmp_path / "repo")
    block = {"path": "src/probos/gone.py", "mode": "modify", "replacements": [{"search": "a", "replace": "b"}]}

    result = await _build(repo, [block, _whole(TARGET, "x = 2\n", base=ORIGINAL)])

    assert result.success is False and not result.commit_hash
    assert "MODIFY target src/probos/gone.py does not exist; refused" in result.error, result.error
    assert (repo / TARGET).read_bytes() == ORIGINAL.encode("utf-8"), "the other block is never written"
    assert _refs(repo) == ["main"]


# ---------------------------------------------------------------------------
# 1b. ONE rule: any block carrying a `base` key (create or modify) is compare-and-swap
# ---------------------------------------------------------------------------

EMPTY = "src/probos/empty.py"


def _based(path: str, mode: str, content: str, base: Any) -> dict[str, Any]:
    return {"path": path, "mode": mode, "content": content, "base": base}


def _empty_file_repo(root: Path) -> Path:
    repo = _plain_repo(root, {TARGET: ORIGINAL, EMPTY: ""})
    assert (repo / EMPTY).read_bytes() == b"", "premise: an existing, tracked, empty file"
    return repo


def _independent_commit(repo: Path, rel: str, text: str) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_bytes(text.encode("utf-8"))
    assert _git(repo, "add", "-A").returncode == 0, "premise: git add"
    assert _git(repo, "commit", "-q", "-m", "independent change").returncode == 0, "premise: the independent commit"


@needs_git
async def test_create_with_empty_base_over_a_still_empty_file_is_applied_as_a_modification(tmp_path: Path) -> None:
    repo = _empty_file_repo(tmp_path / "repo")

    result = await _build(repo, [_based(EMPTY, "create", "e = 1\n", "")])

    assert result.success and result.commit_hash, result.error
    assert result.files_modified == [EMPTY] and result.files_written == [], "an overwrite is never a files_written entry"
    assert _blob(repo, result.branch_name, EMPTY) == "e = 1\n"


@needs_git
async def test_create_with_empty_base_over_an_empty_file_changed_by_an_independent_commit_is_refused(
    tmp_path: Path,
) -> None:
    # control first: the same block while the file is still empty lands
    control = _empty_file_repo(tmp_path / "control")
    ok = await _build(control, [_based(EMPTY, "create", "e = 1\n", "")], "bf896 control")
    assert ok.success and ok.commit_hash, ok.error

    repo = _empty_file_repo(tmp_path / "probe")
    _independent_commit(repo, EMPTY, "independent = 1\n")
    head = _git(repo, "rev-parse", "main").stdout.strip()
    state = _repo_state(repo)

    result = await _build(repo, [_based(EMPTY, "create", "e = 1\n", "")])

    assert result.success is False
    assert EMPTY in result.error and "different content" in result.error
    assert not result.commit_hash and result.files_modified == [] and result.files_written == []
    assert (repo / EMPTY).read_text(encoding="utf-8") == "independent = 1\n", "the independent change must survive"
    assert _git(repo, "rev-parse", "main").stdout.strip() == head
    assert _repo_state(repo) == state, "no commit, no branch left behind"


@needs_git
async def test_create_with_empty_base_over_an_absent_path_is_applied_as_a_new_file(tmp_path: Path) -> None:
    repo = _plain_repo(tmp_path / "repo")
    assert not (repo / NEW).exists(), "premise: the path is absent"

    result = await _build(repo, [_based(NEW, "create", "ok = 1\n", "")])

    assert result.success and result.commit_hash, result.error
    assert result.files_written == [NEW] and result.files_modified == []
    assert _blob(repo, result.branch_name, NEW) == "ok = 1\n"


@needs_git
async def test_create_with_empty_base_over_a_path_that_appeared_after_generation_is_refused(tmp_path: Path) -> None:
    ok = await _build(_plain_repo(tmp_path / "control"), [_based(NEW, "create", "ok = 1\n", "")], "bf896 control")
    assert ok.success and ok.commit_hash, ok.error

    repo = _plain_repo(tmp_path / "probe")
    _independent_commit(repo, NEW, "theirs = 1\n")

    result = await _build(repo, [_based(NEW, "create", "ok = 1\n", "")])

    assert result.success is False and NEW in result.error
    assert (repo / NEW).read_text(encoding="utf-8") == "theirs = 1\n"
    assert not result.commit_hash and _refs(repo) == ["main"]


@needs_git
async def test_create_with_nonempty_base_over_a_changed_file_is_refused(tmp_path: Path) -> None:
    ok = await _build(_plain_repo(tmp_path / "control"), [_based(TARGET, "create", "x = 2\n", ORIGINAL)], "bf896 control")
    assert ok.success and ok.commit_hash and ok.files_modified == [TARGET], ok.error

    repo = _plain_repo(tmp_path / "probe")
    _independent_commit(repo, TARGET, "x = 99\n")

    result = await _build(repo, [_based(TARGET, "create", "x = 2\n", ORIGINAL)])

    assert result.success is False and TARGET in result.error
    assert (repo / TARGET).read_text(encoding="utf-8") == "x = 99\n"
    assert not result.commit_hash and result.files_modified == [] and _refs(repo) == ["main"]


@needs_git
async def test_whole_file_modify_with_base_over_a_removed_target_is_refused_and_blocks_the_whole_commit(
    tmp_path: Path,
) -> None:
    control = _plain_repo(tmp_path / "control")
    ok = await _build(control, [_whole(OTHER, "y = 2\n", base="y = 1\n"), _create(NEW, "ok = 1\n")], "bf896 control")
    assert ok.success and ok.commit_hash and ok.files_modified == [OTHER] and ok.files_written == [NEW], ok.error

    repo = _plain_repo(tmp_path / "probe")
    assert _git(repo, "rm", "-q", OTHER).returncode == 0, "premise: the target is removed after generation"
    assert _git(repo, "commit", "-q", "-m", "remove other").returncode == 0
    assert not (repo / OTHER).exists()
    state = _repo_state(repo)

    result = await _build(
        repo,
        [_whole(OTHER, "y = 2\n", base="y = 1\n"), _create(NEW, "ok = 1\n"), _whole(TARGET, "x = 2\n", base=ORIGINAL)],
    )

    assert result.success is False and OTHER in result.error and "different content" in result.error
    assert not result.commit_hash, "the other blocks in the same call must not commit either"
    assert not (repo / NEW).exists(), "the created file of a failed build is cleaned up"
    assert _blob(repo, "main", TARGET) == ORIGINAL, "nothing reached main"
    assert _repo_state(repo)[:2] == state[:2] and _refs(repo) == ["main"]


@needs_git
async def test_modify_with_empty_base_over_an_absent_target_is_refused_not_skipped(tmp_path: Path) -> None:
    ok = await _build(_plain_repo(tmp_path / "control"), [_based(OTHER, "modify", "y = 2\n", "y = 1\n")], "bf896 control")
    assert ok.success and ok.commit_hash, ok.error

    repo = _plain_repo(tmp_path / "probe")
    gone = "src/probos/gone.py"
    assert not (repo / gone).exists(), "premise: the target is absent"

    result = await _build(repo, [_based(gone, "modify", "g = 1\n", ""), _whole(TARGET, "x = 2\n", base=ORIGINAL)])

    assert result.success is False and gone in result.error
    assert not result.commit_hash and not (repo / gone).exists()
    assert _blob(repo, "main", TARGET) == ORIGINAL and _refs(repo) == ["main"], "nothing was committed"


@needs_git
@pytest.mark.parametrize("mode", ["create", "modify"])
@pytest.mark.parametrize(
    "bad_base",
    [None, 7, b"x = 1\n", ["x = 1\n"], ANY],
    ids=["none", "int", "bytes", "list", "equals-anything"],
)
async def test_a_base_block_with_a_non_str_base_is_refused(tmp_path: Path, mode: str, bad_base: Any) -> None:
    ok = await _build(_plain_repo(tmp_path / "control"), [_based(TARGET, mode, "x = 2\n", ORIGINAL)], "bf896 control")
    assert ok.success and ok.commit_hash, ok.error

    repo = _plain_repo(tmp_path / "probe")
    assert bad_base == ORIGINAL or not isinstance(bad_base, str), "premise: the bad base is not a str"
    if bad_base is ANY:
        assert (ANY == ORIGINAL and ORIGINAL == ANY and not (ANY != ORIGINAL)), "premise: it compares equal to the real text"

    result = await _build(repo, [_based(TARGET, mode, "x = 2\n", bad_base)])

    assert result.success is False and TARGET in result.error
    assert not result.commit_hash and (repo / TARGET).read_text(encoding="utf-8") == ORIGINAL and _refs(repo) == ["main"]


@needs_git
async def test_a_replacement_modify_carrying_a_base_is_compare_and_swap(tmp_path: Path) -> None:
    current = "x = 1\ny = 2\n"
    replacement = [{"search": "x = 1", "replace": "x = 10"}]
    # Positive control: the base matches the target's current text, so the SEARCH/REPLACE block applies.
    control = _plain_repo(tmp_path / "control", {TARGET: current})
    ok = await _build(control, [{"path": TARGET, "mode": "modify", "replacements": replacement, "base": current}])
    assert ok.success and ok.commit_hash, ok.error
    assert _blob(control, ok.branch_name, TARGET) == "x = 10\ny = 2\n"

    repo = _plain_repo(tmp_path / "probe", {TARGET: current})
    main_before = _git(repo, "rev-parse", "main").stdout.strip()
    stale = "x = 1\ny = 3\n"
    assert stale != (repo / TARGET).read_text(encoding="utf-8"), "premise: the base differs from the target's text"
    assert "x = 1" in (repo / TARGET).read_text(encoding="utf-8"), "premise: the replacement itself would apply"

    result = await _build(repo, [{"path": TARGET, "mode": "modify", "replacements": replacement, "base": stale}])

    assert result.success is False
    assert TARGET in result.error and "different content" in result.error
    assert not result.commit_hash and result.files_modified == []
    assert (repo / TARGET).read_text(encoding="utf-8") == current, "the file must be unchanged"
    assert _git(repo, "rev-parse", "main").stdout.strip() == main_before
    assert _refs(repo) == ["main"]


@needs_git
async def test_a_create_base_block_whose_path_is_a_directory_is_refused(tmp_path: Path) -> None:
    ok = await _build(_plain_repo(tmp_path / "control"), [_based(NEW, "create", "ok = 1\n", "")], "bf896 control")
    assert ok.success and ok.commit_hash, ok.error

    repo = _plain_repo(tmp_path / "probe")
    (repo / NEW).mkdir(parents=True)
    assert (repo / NEW).is_dir(), "premise: the path is a directory"

    result = await _build(repo, [_based(NEW, "create", "ok = 1\n", "")])

    assert result.success is False and NEW in result.error and "non-regular" in result.error
    assert not result.commit_hash and (repo / NEW).is_dir() and _refs(repo) == ["main"]


@needs_git
async def test_a_modify_base_block_whose_path_is_a_directory_is_refused(tmp_path: Path) -> None:
    ok = await _build(_plain_repo(tmp_path / "control"), [_based(TARGET, "modify", "x = 2\n", ORIGINAL)], "bf896 control")
    assert ok.success and ok.commit_hash, ok.error

    repo = _plain_repo(tmp_path / "probe")
    (repo / NEW).mkdir(parents=True)

    result = await _build(repo, [_based(NEW, "modify", "ok = 1\n", "")])

    assert result.success is False and NEW in result.error and "non-regular" in result.error
    assert not result.commit_hash and (repo / NEW).is_dir() and _refs(repo) == ["main"]


# ---------------------------------------------------------------------------
# 2. A create over a file that existed before the build is a modification
# ---------------------------------------------------------------------------


@needs_git
async def test_create_over_an_existing_file_is_a_modification_and_survives_a_failed_build(tmp_path: Path) -> None:
    # control, first: with valid text the create over a tracked file lands and is classified as a modification
    ok_repo = _plain_repo(tmp_path / "control")
    ok = await _build(ok_repo, [_create(TARGET, "x = 5\n")], "bf896 control")
    assert ok.success and ok.commit_hash, ok.error
    assert ok.files_modified == [TARGET] and ok.files_written == [], "classified as a modification on success too"
    assert _blob(ok_repo, ok.branch_name, TARGET) == "x = 5\n"

    repo = _plain_repo(tmp_path / "probe")
    assert _git(repo, "ls-files", "--error-unmatch", TARGET).returncode == 0, "premise: the file is tracked"

    result = await _build(repo, [_create(TARGET, BROKEN)])

    assert result.success is False and result.error.startswith("Syntax errors"), result.error
    # BF-904a (#1585): stronger than "survives": the failed build writes the file's bytes back.
    assert (repo / TARGET).read_bytes() == ORIGINAL.encode("utf-8"), "a tracked file the build overwrote is restored"
    assert result.files_modified == [TARGET]
    assert result.files_written == [], "the cleanup unlinks files_written; a pre-existing file must never be listed there"
    assert _git(repo, "ls-files", "--error-unmatch", TARGET).returncode == 0
    assert _refs(repo) == ["main"]


@needs_git
async def test_create_of_a_new_file_is_still_cleaned_up_on_failure(tmp_path: Path) -> None:
    repo = _plain_repo(tmp_path / "repo")
    assert not (repo / NEW).exists() and not (repo / NEW).parent.exists(), "premise: the file and its directory are new"

    result = await _build(repo, [_create(NEW, BROKEN)])

    assert result.success is False and result.error.startswith("Syntax errors"), result.error
    assert result.files_written == [NEW] and result.files_modified == [], "a genuinely new file is still files_written"
    assert not (repo / NEW).exists(), "the failed build's new file is unlinked"
    assert not (repo / NEW).parent.exists(), "and its now-empty directory with it"
    assert _tree(repo) == {path: text.encode("utf-8") for path, text in SEED.items()}
    assert _refs(repo) == ["main"]


@needs_git
async def test_a_failed_build_unlinks_only_the_files_it_created(tmp_path: Path) -> None:
    """The two classifications side by side, in one build that fails on a third file."""
    repo = _plain_repo(tmp_path / "repo")

    result = await _build(repo, [_create(NEW, "ok = 1\n"), _create(TARGET, "x = 5\n"), _create(BAD, BROKEN)])

    assert result.success is False and result.error.startswith("Syntax errors"), result.error
    assert result.files_written == [NEW, BAD] and result.files_modified == [TARGET]
    assert not (repo / NEW).exists() and not (repo / BAD).exists(), "the files this build created are unlinked"
    assert (repo / TARGET).exists() and (repo / OTHER).exists(), "files that existed before the build are not"


async def _fail_targeted_tests(work_dir: str, changed_files: list[str], timeout: int = 60) -> tuple[bool, str, list[str]]:
    return False, "1 failed", []


async def _repair_build(
    repo: Path, fix_path: str, title: str, monkeypatch: pytest.MonkeyPatch
) -> tuple[BuildResult, int]:
    """Initial create of NEW; the targeted tests always fail; the LLM's one repair is a ``===FILE:`` block
    (the ``_repair_build`` pattern of tests/test_bf894_builder_write_boundary.py)."""
    llm = _FakeLLM(f"===FILE: {fix_path}===\nx = 3\n===END FILE===\n")
    monkeypatch.setattr(builder_module, "_run_targeted_tests", _fail_targeted_tests)
    result = await _build(repo, [_create(NEW, "ok = 1\n")], title, run_tests=True, max_fix_attempts=1, llm_client=llm)
    return result, sum("Test Fix Required" in prompt for prompt in llm.prompts)


@needs_git
async def test_repair_create_over_an_existing_file_is_a_modification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # control, first: a repair block that creates a NEW file is files_written (and is cleaned up with the build)
    fresh = "src/probos/repaired.py"
    control_repo = _plain_repo(tmp_path / "control")
    control, control_calls = await _repair_build(control_repo, fresh, "bf896 control", monkeypatch)
    assert control_calls == 1, "premise: the repair loop ran and received the block"
    assert control.files_written == [NEW, fresh] and control.files_modified == []
    assert not (control_repo / fresh).exists(), "control: a new repair file is cleaned up with the failed build"

    repo = _plain_repo(tmp_path / "probe")
    result, fix_calls = await _repair_build(repo, TARGET, "bf896 probe", monkeypatch)

    assert fix_calls == 1, "premise: the repair loop ran and received the block over the tracked file"
    assert result.success is False and "Tests failed" in result.error, result.error
    assert result.files_modified == [TARGET], "the repair's create over a pre-existing file is a modification"
    assert TARGET not in result.files_written and result.files_written == [NEW]
    # BF-904a (#1585): the repair wrote TARGET (files_modified above); the failed build writes the original back.
    assert (repo / TARGET).read_bytes() == ORIGINAL.encode("utf-8"), "the repaired file is restored"
    assert not (repo / NEW).exists(), "the build's own new file is still cleaned up"
    assert _git(repo, "ls-files", "--error-unmatch", TARGET).returncode == 0
    assert _refs(repo) == ["main"]


@needs_git
@pytest.mark.parametrize("site", ["approved-twice", "repair-rewrite"])
async def test_a_second_write_of_a_file_this_build_created_stays_files_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, site: str
) -> None:
    """``pre_existing`` means "existed BEFORE this build": a file the build wrote moments ago is not one."""
    repo = _plain_repo(tmp_path / "repo")
    assert not (repo / NEW).exists(), "premise: the file is new to the build"
    if site == "approved-twice":
        result = await _build(repo, [_create(NEW, "a = 1\n"), _create(NEW, "a = 2\n")])
        assert result.success and result.commit_hash, result.error
        assert _blob(repo, result.branch_name, NEW) == "a = 2\n", "premise: the second block was applied over the first"
    else:
        result, fix_calls = await _repair_build(repo, NEW, "bf896 probe", monkeypatch)
        assert fix_calls == 1 and result.fix_attempts == 1, "premise: the repair loop ran and applied its block"

    assert result.files_written == [NEW], "listed once, as a file this build created"
    assert result.files_modified == []


# ---------------------------------------------------------------------------
# 3. The repository-identity pin
# ---------------------------------------------------------------------------


async def _pinned_worktree(root: Path) -> tuple[Path, Path, Path, str]:
    base, victim, wt = _linked_worktree(root)
    pin = await repository_identity(str(wt))
    assert pin is not None, "premise: the capture succeeds on a linked worktree"
    return base, victim, wt, pin


def test_expected_git_dir_is_an_optional_last_parameter() -> None:
    parameters = list(inspect.signature(execute_approved_build).parameters.values())
    assert parameters[-1].name == "expected_git_dir", "last, so no existing positional call changes meaning"
    assert parameters[-1].default is None
    assert all(p.default is not inspect.Parameter.empty for p in parameters[3:]), "everything after work_dir is optional"


@needs_git
async def test_identity_mismatch_at_entry_refuses_before_any_git_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocks = [_create(NEW, "ok = 1\n"), _whole(TARGET, "x = 2\n", base=ORIGINAL)]

    # control, first: the same pinned build on an untouched worktree lands
    _cb, _cv, control_wt, control_pin = await _pinned_worktree(tmp_path / "control")
    control = await _build(control_wt, blocks, "bf896 control", expected_git_dir=control_pin)
    assert control.success and control.commit_hash, f"control: a build whose identity still matches must land: {control.error}"
    assert _blob(control_wt, control.branch_name, NEW) == "ok = 1\n"
    assert _blob(control_wt, control.branch_name, TARGET) == "x = 2\n"

    base, victim, wt, pin = await _pinned_worktree(tmp_path / "probe")
    git_dir_before = _git_dir(wt)
    tree_before = _tree(wt)
    victim_before, base_before = _repo_state(victim), _repo_state(base)
    _repoint(wt, victim)
    assert _git_dir(wt) != git_dir_before, "premise: the swap really moved the repository git resolves for the tree"
    assert await repository_identity(str(wt)) != pin, "premise: and the identity capture sees it"

    spy = _GitSpy(builder_module._run_git)
    dirty_spy = _DirtyCheckSpy(builder_module._is_dirty_working_tree)
    monkeypatch.setattr(builder_module, "_run_git", spy)
    monkeypatch.setattr(builder_module, "_is_dirty_working_tree", dirty_spy)

    result = await _build(wt, blocks, "bf896 probe", expected_git_dir=pin)

    assert result.success is False and "identity" in result.error.lower(), result.error
    assert not result.commit_hash and not result.branch_name, "refused before the build branch was even created"
    assert result.files_written == [] and result.files_modified == []
    assert spy.calls == [(False, IDENTITY_ARGS)], "the only git command allowed is the identity read itself"
    assert dirty_spy.calls == 0, "the dirty-tree check is a git command too: it must come after the identity check"
    assert _tree(wt) == tree_before, "nothing was written into the tree"
    assert _repo_state(victim) == victim_before, "no commit, branch or staged file in the foreign repository"
    assert _repo_state(base) == base_before, "and none in the repository the worktree belonged to"
    assert all(not ref.startswith("builder") for repo in (base, victim) for ref in _refs(repo)), "no build branch anywhere"


@needs_git
async def test_identity_change_before_commit_refuses_and_runs_no_git_in_the_foreign_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocks = [_create(NEW, "ok = 1\n"), _whole(TARGET, "x = 2\n", base=ORIGINAL)]

    # control, first: the tests run (and pass) without touching .git, so the commit lands
    async def _passing(work_dir: str, changed_files: list[str], timeout: int = 60) -> tuple[bool, str, list[str]]:
        return True, "ok", []

    monkeypatch.setattr(builder_module, "_run_targeted_tests", _passing)
    _cb, _cv, control_wt, control_pin = await _pinned_worktree(tmp_path / "control")
    control = await _build(control_wt, blocks, "bf896 control", run_tests=True, expected_git_dir=control_pin)
    assert control.success and control.commit_hash, f"control: tests passing and identity intact must commit: {control.error}"
    assert control.tests_passed and _blob(control_wt, control.branch_name, TARGET) == "x = 2\n"

    base, victim, wt, pin = await _pinned_worktree(tmp_path / "probe")
    git_dir_before = _git_dir(wt)
    victim_before, base_commits = _repo_state(victim), _commit_count(base)
    spy = _GitSpy(builder_module._run_git)

    async def _swap_then_pass(work_dir: str, changed_files: list[str], timeout: int = 60) -> tuple[bool, str, list[str]]:
        _repoint(wt, victim)  # the tests ran arbitrary code: it rewrote the worktree's .git pointer
        spy.swapped = True
        return True, "ok", []

    monkeypatch.setattr(builder_module, "_run_targeted_tests", _swap_then_pass)
    monkeypatch.setattr(builder_module, "_run_git", spy)

    result = await _build(wt, blocks, "bf896 probe", run_tests=True, expected_git_dir=pin)

    assert spy.swapped, "premise: the swap happened inside the build"
    assert _git_dir(wt) != git_dir_before, "premise: the swap really moved the repository git resolves for the tree"
    assert any(args[:2] == ["checkout", "-b"] for args in spy.args_before_swap()), "premise: the spy saw the build branch created"
    assert result.tests_passed and result.test_result == "ok", "the tests passed: the refusal is the identity check's"
    assert result.success is False and "identity" in result.error.lower(), result.error
    assert not result.commit_hash
    assert spy.args_after_swap() == [IDENTITY_ARGS], "after the swap: the identity read only (no add, commit, checkout, branch -D)"
    assert _repo_state(victim) == victim_before, "no commit, branch or staged file in the foreign repository"
    assert _commit_count(base) == base_commits, "no commit in the original repository either"
    assert _git(base, "rev-parse", result.branch_name).stdout == _git(base, "rev-parse", "main").stdout, "build branch holds no commit"
    assert result.files_written == [NEW] and result.files_modified == [TARGET]
    assert not (wt / NEW).exists(), "the file this build created is unlinked"
    assert (wt / TARGET).exists(), "a file that existed before the build is not"


@needs_git
async def test_pin_on_a_non_repository_refuses_where_no_pin_keeps_the_old_failure(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _git(plain, "rev-parse", "--git-dir").returncode != 0, "premise: the directory is not inside a repository"

    unpinned = await _build(plain, [_create(NEW, "ok = 1\n")])
    # BF-904a (#1585): a tree with neither a branch nor a commit is now refused at entry, before the branch.
    assert unpinned.success is False and unpinned.error.startswith("Cannot read the checkout's current branch or commit"), unpinned.error

    pinned = await _build(plain, [_create(NEW, "ok = 1\n")], expected_git_dir="C:/some/pinned/.git")
    assert pinned.success is False and "identity" in pinned.error.lower(), pinned.error
    assert "found None" in pinned.error, "an unreadable identity is a mismatch: fail closed"
    assert not (plain / NEW).exists()


@needs_git
async def test_no_pin_is_pinned_at_entry_when_readable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # BF-904a (#1585): this test used to pin the gap ("without a pin repository_identity is never consulted").
    # A caller that gives no pin (the /api/build routes, BuildPipeline) now gets the identity read at entry and
    # compared again before the commit, so the unpinned path is guarded too.
    repo = _plain_repo(tmp_path / "repo")
    spy = _GitSpy(builder_module._run_git)
    identity_calls: list[str] = []
    real_identity = builder_module.repository_identity

    async def _identity_spy(work_dir: str) -> str | None:
        identity_calls.append(work_dir)
        return await real_identity(work_dir)

    monkeypatch.setattr(builder_module, "_run_git", spy)
    monkeypatch.setattr(builder_module, "repository_identity", _identity_spy)

    result = await _build(repo, [_whole(TARGET, "x = 2\n", base=ORIGINAL)])

    assert spy.calls, "premise: the spy sees the executor's git"
    assert result.success and result.commit_hash, result.error
    assert result.files_modified == [TARGET] and _blob(repo, result.branch_name, TARGET) == "x = 2\n"
    assert identity_calls == [str(repo), str(repo)], "pinned at entry, compared again before the commit"
    assert spy.calls[0][1] == IDENTITY_ARGS, "the entry pin is the executor's first git command"
    assert result.branch_name and _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"


@needs_git
async def test_repository_identity(tmp_path: Path) -> None:
    base, victim, wt = _linked_worktree(tmp_path / "fixture")
    git_dir = _git_dir(wt)

    first = await repository_identity(str(wt))
    second = await repository_identity(str(wt))
    assert isinstance(first, str) and first, "control: a linked worktree has an identity"
    assert first == second, "two captures of the same tree compare equal"
    assert first == os.path.normcase(os.path.realpath(git_dir)), "the identity is git's absolute git dir in normal form"
    victim_identity = await repository_identity(str(victim))
    assert victim_identity and victim_identity != first, "premise: two repositories have two identities"

    _repoint(wt, victim)
    assert _git_dir(wt) != git_dir, "premise: the swap really moved the repository git resolves for the tree"
    swapped = await repository_identity(str(wt))
    assert swapped is not None and swapped != first, "the identity changes when .git becomes a gitfile to another repo"
    assert swapped == victim_identity, "and it is the other repository's identity"


@needs_git
async def test_repository_identity_is_none_when_it_cannot_be_determined(tmp_path: Path) -> None:
    repo = _plain_repo(tmp_path / "repo")
    assert await repository_identity(str(repo)) == os.path.normcase(os.path.realpath(str(repo / ".git"))), "control"
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _git(plain, "rev-parse", "--git-dir").returncode != 0, "premise: the directory is not inside a repository"

    assert await repository_identity(str(plain)) is None, "git exits non-zero outside a repository"
    assert await repository_identity(str(tmp_path / "missing")) is None, "a missing directory cannot start git"
    assert await repository_identity("bad\x00dir") is None, "a path git cannot even be started in"


def _stub_git(outcome: Any) -> Any:
    async def _fake(args: list[str], work_dir: str) -> tuple[int, str, str]:
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return _fake


@needs_git
@pytest.mark.parametrize(
    "outcome",
    [(0, "", ""), (128, "fatal: not a git repository", ""), (1, "/looks/valid/.git", ""), OSError("no git"), ValueError("nul")],
    ids=["empty-output", "nonzero-exit", "nonzero-exit-with-output", "oserror", "valueerror"],
)
async def test_repository_identity_none_for_a_failed_git_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: Any
) -> None:
    repo = _plain_repo(tmp_path / "repo")
    assert await repository_identity(str(repo)), "control: the same call on a real repository has an identity"
    monkeypatch.setattr(builder_module, "_run_git", _stub_git(outcome))

    assert await repository_identity(str(repo)) is None


@needs_git
@pytest.mark.parametrize("failure", [OSError("cannot resolve"), ValueError("embedded null")], ids=["oserror", "valueerror"])
async def test_repository_identity_none_when_the_path_cannot_be_normalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    repo = _plain_repo(tmp_path / "repo")
    assert await repository_identity(str(repo)), "control: normalization works on a real repository"

    def _boom(path: str) -> str:
        raise failure

    monkeypatch.setattr(builder_module, "_run_git", _stub_git((0, str(repo / ".git"), "")))
    with monkeypatch.context() as scoped:
        scoped.setattr(os.path, "realpath", _boom)
        assert await repository_identity(str(repo)) is None


def _short_spelling(path: Path) -> str | None:
    """The 8.3 spelling of *path* on Windows, or None where there is none (other platform, 8.3 disabled)."""
    if sys.platform != "win32":
        return None
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))  # type: ignore[attr-defined]
    return buffer.value if length and buffer.value.lower() != str(path).lower() else None


def _spelling_of(kind: str, git_dir: Path, tmp_path: Path) -> str:
    """One spelling of *git_dir*; skips the test where this platform cannot produce that spelling."""
    if kind == "dotdot":
        return str(git_dir / ".." / ".git")
    if kind == "forward-slashes":
        return git_dir.as_posix()
    if kind == "upper-case":
        if sys.platform != "win32":
            pytest.skip("upper-casing a path names the same directory only on a case-insensitive filesystem")
        return str(git_dir).upper()
    if kind == "8.3":
        short = _short_spelling(git_dir)
        if short is None:
            pytest.skip("no distinct 8.3 short name for this path (not Windows, or 8.3 name creation is disabled)")
        return short
    link = tmp_path / "alias"
    try:
        os.symlink(git_dir, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create a directory symlink here ({exc})")
    return str(link)


@needs_git
@pytest.mark.parametrize("kind", ["dotdot", "forward-slashes", "upper-case", "8.3", "symlink"])
async def test_repository_identity_normalizes_the_spelling_of_one_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    repo = _plain_repo(tmp_path / "repo")
    real = await repository_identity(str(repo))
    assert real, "control: a real repository has an identity"
    spelling = _spelling_of(kind, repo / ".git", tmp_path)
    assert os.path.samefile(spelling, repo / ".git"), f"premise: the {kind} spelling names the same directory"

    monkeypatch.setattr(builder_module, "_run_git", _stub_git((0, spelling, "")))

    assert await repository_identity(str(repo)) == real, f"the {kind} spelling must normalize to the same identity"


# ---------------------------------------------------------------------------
# 4. The code reviewer sees a whole-file modify's text
# ---------------------------------------------------------------------------


def _reviewer() -> CodeReviewAgent:
    return CodeReviewAgent(agent_id="code_reviewer", name="CodeReviewAgent")


def test_code_reviewer_renders_a_whole_file_modify() -> None:
    reviewer = _reviewer()
    marker = "WHOLE_FILE_MARKER = 42"

    # controls, first: the other block shapes render as they always did
    replacement = reviewer._format_changes(
        [{"path": TARGET, "mode": "modify", "replacements": [{"search": "old_text", "replace": "new_text"}]}]
    )
    assert f"### MODIFY: {TARGET}" in replacement and "SEARCH:\nold_text" in replacement and "REPLACE:\nnew_text" in replacement
    create = reviewer._format_changes([_create(NEW, "ok = 1\n")])
    assert f"### CREATE: {NEW}" in create and "ok = 1" in create

    rendered = reviewer._format_changes([_whole(TARGET, f"{marker}\n", base=ORIGINAL)])

    assert marker in rendered, "the new text of a whole-file MODIFY must reach the reviewer (it rendered an empty MODIFY)"
    assert TARGET in rendered and "MODIFY" in rendered
    assert "SEARCH:" not in rendered and "REPLACE:" not in rendered
    assert ORIGINAL.strip() not in rendered, "the base is the old text: the reviewer is shown the change, not the base"


def test_code_reviewer_truncates_a_whole_file_modify_like_a_create() -> None:
    reviewer = _reviewer()
    assert "TAIL" in reviewer._format_changes([_create(NEW, "a" * 2990 + "TAIL")]), "control: a CREATE keeps its first 3000 chars"

    rendered = reviewer._format_changes([_whole(TARGET, "a" * 3000 + "TAIL", base=ORIGINAL)])

    assert "a" * 3000 in rendered and "TAIL" not in rendered


async def test_code_reviewer_review_prompt_carries_a_whole_file_modify() -> None:
    marker = "WHOLE_FILE_MARKER = 42"
    llm = _FakeLLM('{"approved": true, "issues": [], "suggestions": [], "summary": "ok"}')

    review = await _reviewer().review(
        file_changes=[_whole(TARGET, f"{marker}\n", base=ORIGINAL)], spec_title="bf896", llm_client=llm
    )

    assert review.approved is True
    assert len(llm.prompts) == 1 and marker in llm.prompts[0], "the text reaches the LLM call, not just the formatter"


# ---------------------------------------------------------------------------
# 5. The native visiting path seeds only inside its own temp dir
# ---------------------------------------------------------------------------


class _SeedProbeResult:
    success = True
    file_blocks = [{"path": "a.py", "mode": "create", "content": "x = 1\n"}]
    raw_output = "out"
    error = None


class _SeedProbeAdapter:
    """Stands in for `CopilotBuilderAdapter`; at ``execute`` time it records what the session directory holds."""

    last: _SeedProbeAdapter | None = None

    def __init__(self, *, cwd: str = "", **_kw: Any) -> None:
        self.cwd = cwd
        self.files: dict[str, str] | None = None
        self.seeded: dict[str, bytes] | None = None
        type(self).last = self

    async def start(self) -> None:
        return None

    async def execute(self, _spec: Any, files: dict[str, str]) -> _SeedProbeResult:
        self.files = dict(files)
        root = Path(self.cwd)
        self.seeded = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        return _SeedProbeResult()

    async def stop(self) -> None:
        return None


async def test_native_visiting_path_does_not_seed_outside_its_temp_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An absolute target key used to be written at its ORIGINAL location (``tmp / "<absolute>"`` is the
    absolute path). Once ``perceive`` has localized a large target to an excerpt, that overwrote the real
    file with the excerpt. The setup below makes the excerpt differ from the file, so the old loop is visible."""
    original = "".join(f"value_{i:04d} = {i}  # padding that makes this file large enough to be localized\n" for i in range(800))
    target = tmp_path / "big_target.py"
    target.write_bytes(original.encode("utf-8"))
    reference = "pyproject.toml"
    assert (builder_module._PROJECT_ROOT / reference).is_file(), "premise: a project-relative reference exists"
    assert len(original) > BuilderAgent._LOCALIZE_THRESHOLD, "premise: perceive will localize this target"

    _SeedProbeAdapter.last = None
    monkeypatch.setattr(adapter_module, "CopilotBuilderAdapter", lambda **kw: _SeedProbeAdapter(**kw))
    agent = BuilderAgent(agent_id="builder-bf896", llm_client=MagicMock(), runtime=MagicMock(spec=ProbOSRuntime))

    await agent.perceive(
        {
            "intent": "build_code",
            "params": {
                "title": "t",
                "description": "d",
                "target_files": [str(target)],
                "reference_files": [reference],
                "force_visiting": True,
            },
        }
    )

    adapter = _SeedProbeAdapter.last
    assert adapter is not None and adapter.files is not None and adapter.seeded is not None, "premise: the visiting path ran"
    # control, first: a project-relative key IS seeded under the session directory, with the text the adapter was handed
    assert reference in adapter.files and reference in adapter.seeded, "control: seeding ran and wrote a relative key inside"
    assert adapter.seeded[reference].decode("utf-8").replace("\r\n", "\n") == adapter.files[reference]
    # premise: the absolute key reached the adapter carrying an excerpt, not the file
    key = str(target)
    assert os.path.isabs(key) and key in adapter.files
    assert adapter.files[key] != original and len(adapter.files[key]) < len(original), "premise: the target was localized"

    assert target.read_bytes() == original.encode("utf-8"), "the original file outside the temp dir was rewritten"
