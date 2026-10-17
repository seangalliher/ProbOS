"""BF-894 (#1547): the builder's write-path boundary.

Every negative has a control: the exact ``.git`` form is refused too, and legitimate paths
are accepted with the same work_dir. The Windows-only forms are refused lexically on every
platform; whether they WRITE THROUGH to ``.git`` can be shown only on a case-insensitive
filesystem, so their end-to-end rows skip elsewhere. The hard-link alias proves the identity
check and the write-through on every platform, Linux CI included.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive import builder as builder_module
from probos.cognitive import builder_paths
from probos.cognitive.builder import BuildSpec, _git_add_and_commit, _map_source_to_tests, _validate_file_path, execute_approved_build
from probos.cognitive.builder_paths import builder_write_refusal

_HAS_GIT = shutil.which("git") is not None
_POINTER = "gitdir: ../elsewhere/.git/worktrees/wt\n"
_LEGIT = ("src/probos/x.py", "tests/test_x.py", "config/system.yaml", "docs/a b.md", "conftest.py", ".gitignore", "tests/fixtures/.gitkeep", "tests/-n.py")
_ALIASES = [".GiT", "GIT~1", ".git.", ".git::$DATA", "pointer-alias"]


def _refused(path: str, work_dir: Path | None = None) -> str:
    refusal = builder_write_refusal(path, work_dir)
    assert refusal is not None, f"{path!r} must be refused"
    return refusal


def test_premise_exact_forms_refused_and_legitimate_paths_accepted() -> None:
    assert "Forbidden" in _refused(".git") and "Forbidden" in _refused(".git/config")
    assert [builder_write_refusal(p) for p in _LEGIT] == [None] * len(_LEGIT)
    assert _validate_file_path is builder_write_refusal


@pytest.mark.parametrize("alias", [".GiT", ".Git", ".GIT", ".g\u0131t", "src/.GIT/config"])
def test_validate_rejects_case_variant_git(alias: str) -> None:
    assert "Forbidden" in _refused(alias)


@pytest.mark.parametrize("alias", [".git.", ".git ", ".git. .", ".git::$DATA", ".GiT::$DATA", ".git\\.", "src\\.git"])
def test_validate_rejects_trailing_dot_and_stream_forms(alias: str) -> None:
    assert "Forbidden" in _refused(alias)


@pytest.mark.parametrize("alias", ["GIT~1", "git~1", "git~2/config", "GITHUB~1/workflows/ci.yml", "PYPROJ~1.TOM"])
def test_validate_rejects_short_name_forms(alias: str) -> None:
    assert "8.3" in _refused(alias)


@pytest.mark.parametrize("alias", [".g\u200cit", "\ufeff.git", ".gi\u206at"])
def test_validate_rejects_hfs_ignorable_forms(alias: str) -> None:
    assert "Forbidden" in _refused(alias)


@pytest.mark.parametrize(
    "name",
    ["nul", "src/NUL", "src/con.py", "src/aux.tar.gz", "tests/com1.py", "src/lpt9 .py", "src/Nul.", "src/com\u00b9.py"],
)
def test_validate_rejects_windows_device_names(name: str) -> None:
    assert builder_write_refusal("src/console.py") is None  # control: a name that only starts like a device
    assert "device" in _refused(name)


@pytest.mark.parametrize(
    "name", ["src/console.py", "src/auxiliary.py", "src/null_test.py", "src/com10.py", "docs/nulls.md", "src/prn_table.py"],
)
def test_validate_accepts_names_that_only_resemble_devices(name: str) -> None:
    assert builder_write_refusal(name) is None


@pytest.mark.parametrize("alias", [".ENV", ".env.", "PyProject.toml", "pyproject.toml ", ".GitHub/workflows/ci.yml"])
def test_validate_rejects_variants_of_the_other_forbidden_paths(alias: str) -> None:
    assert "Forbidden" in _refused(".env") and "Forbidden" in _refused("pyproject.toml")  # premise
    assert "Forbidden" in _refused(alias)


@pytest.mark.parametrize("name", ["-n.py", "--output=x.txt", "-"])
def test_validate_rejects_option_shaped_first_component(name: str) -> None:
    assert builder_write_refusal("tests/-n.py") is None  # control: only the first component reaches argv first
    assert "Option-shaped" in _refused(name)


@pytest.mark.parametrize("empty", ["", "   "])
def test_validate_rejects_empty_path(empty: str) -> None:
    assert "Empty" in _refused(empty)


def _make_pointer(root: Path) -> Path:
    pointer = root / ".git"
    pointer.write_text(_POINTER, encoding="utf-8")
    return pointer


def test_identity_check_refuses_a_hard_link_to_the_git_pointer(tmp_path: Path) -> None:
    pointer = _make_pointer(tmp_path)
    os.link(pointer, tmp_path / "pointer-alias")
    (tmp_path / "other.txt").write_text("x", encoding="utf-8")
    assert os.path.samefile(tmp_path / "pointer-alias", pointer), "premise: the link is the same file"
    assert builder_write_refusal("pointer-alias") is None, "premise: no lexical rule names it"
    assert "same file as .git" in _refused("pointer-alias", tmp_path)
    assert builder_write_refusal("other.txt", tmp_path) is None  # control: an existing unrelated file
    assert builder_write_refusal("src/new.py", tmp_path) is None  # control: not on disk yet


def test_without_a_git_entry_the_lexical_rules_still_apply(tmp_path: Path) -> None:
    assert not (tmp_path / ".git").exists(), "premise"
    assert builder_write_refusal("src/new.py", tmp_path) is None
    assert "Forbidden" in _refused(".GiT", tmp_path)


def test_identity_check_fails_closed_when_a_prefix_cannot_be_examined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_pointer(tmp_path)
    (tmp_path / "src").mkdir()
    assert builder_write_refusal("src/new.py", tmp_path) is None, "premise: accepted before the patch"
    real_stat = os.stat

    def _stat(path, *args, **kwargs):
        if Path(path).name == "src":
            raise PermissionError(13, "denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(builder_paths.os, "stat", _stat)
    refusal = builder_write_refusal("src/new.py", tmp_path)
    monkeypatch.undo()
    assert refusal is not None and "Cannot verify" in refusal


def _no_real_git(stack: ExitStack) -> AsyncMock:
    for name, value in (("_git_current_branch", "main"), ("_is_dirty_working_tree", False),
                        ("_git_create_branch", (True, "builder-bf894")), ("_git_checkout_main", (True, "ok")),
                        ("_run_git", (0, "", ""))):
        stack.enter_context(patch.object(builder_module, name, AsyncMock(return_value=value)))
    commit = AsyncMock(return_value=(True, "abc123"))
    stack.enter_context(patch.object(builder_module, "_git_add_and_commit", commit))
    return commit


def _setup_root(tmp_path: Path, alias: str) -> tuple[Path, set[str]]:
    pointer = _make_pointer(tmp_path)
    if alias == "pointer-alias":
        os.link(pointer, tmp_path / alias)
    return pointer, set(os.listdir(tmp_path))


def _create(path: str, content: str = "gitdir: /victim/.git\n") -> dict:
    return {"path": path, "content": content, "mode": "create", "after_line": None}


@pytest.mark.parametrize("alias", _ALIASES)
async def test_initial_write_is_path_validated(tmp_path: Path, alias: str) -> None:
    pointer, before = _setup_root(tmp_path, alias)
    with ExitStack() as stack:
        commit = _no_real_git(stack)
        result = await execute_approved_build([_create(alias)], BuildSpec(title="BF-894 probe", description=""), str(tmp_path), run_tests=False)
    assert pointer.read_text(encoding="utf-8") == _POINTER  # catches write-through (Windows, hard link)
    assert set(os.listdir(tmp_path)) == before  # catches a new distinct file (case-sensitive filesystems)
    assert result.files_written == [] and "Forbidden" in result.error
    commit.assert_not_awaited()


async def test_initial_write_control_legitimate_path_is_written_and_committed(tmp_path: Path) -> None:
    _make_pointer(tmp_path)
    with ExitStack() as stack:
        commit = _no_real_git(stack)
        result = await execute_approved_build([_create("src/ok.py", "x = 1\n")], BuildSpec(title="BF-894 control", description=""), str(tmp_path), run_tests=False)
    assert result.files_written == ["src/ok.py"] and not result.error
    assert (tmp_path / "src" / "ok.py").read_text(encoding="utf-8") == "x = 1\n"
    assert commit.await_args.args[0] == ["src/ok.py"]


async def _repair_build(tmp_path: Path, fix_path: str) -> tuple[object, int]:
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=MagicMock(content=f"===FILE: {fix_path}===\ngitdir: /victim/.git\n===END FILE===\n"))
    with ExitStack() as stack:
        _no_real_git(stack)
        stack.enter_context(patch.object(builder_module, "_run_targeted_tests", AsyncMock(return_value=(False, "1 failed", []))))
        result = await execute_approved_build([_create("ok.py", "x = 1\n")], BuildSpec(title="BF-894 repair", description=""),
                                              str(tmp_path), run_tests=True, max_fix_attempts=1, llm_client=llm)
    fix_calls = sum("Test Fix Required" in call.args[0].prompt for call in llm.complete.await_args_list)
    return result, fix_calls


@pytest.mark.parametrize("alias", _ALIASES)
async def test_repair_write_is_path_validated(tmp_path: Path, alias: str) -> None:
    pointer, before = _setup_root(tmp_path, alias)
    result, fix_calls = await _repair_build(tmp_path, alias)
    assert fix_calls == 1, "premise: the repair loop ran and received the alias block"
    assert pointer.read_text(encoding="utf-8") == _POINTER
    assert set(os.listdir(tmp_path)) == before  # ok.py was cleaned up; no alias file appeared
    assert alias not in result.files_written and "Forbidden" in result.error


async def test_repair_write_control_legitimate_fix_is_written(tmp_path: Path) -> None:
    _make_pointer(tmp_path)
    # BF-898 (#1563): a repair may no longer write a test; the legitimate control is a source file.
    result, fix_calls = await _repair_build(tmp_path, "src/probos/fixed.py")
    assert fix_calls == 1
    assert "src/probos/fixed.py" in result.files_written and "Forbidden" not in result.error


def test_targeted_pytest_argv_is_anchored_under_work_dir(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    for name in ("test_-k.py", "test_-n.py"):
        (tests_dir / name).write_text("", encoding="utf-8")
    found = _map_source_to_tests(["test_-k.py", "src/-n.py"], str(tmp_path))
    assert len(found) == 2, "premise: both option-shaped names are mapped"
    assert all(p.startswith(str(tests_dir)) for p in found)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _init_repo(path: Path, branch: str) -> None:
    path.mkdir()
    for args in (("init", "-q", "-b", branch), ("config", "user.email", "bf894@example.invalid"),
                 ("config", "user.name", "BF894 Tester"), ("config", "commit.gpgsign", "false"),
                 ("commit", "-q", "--allow-empty", "-m", "seed")):
        assert _git(path, *args).returncode == 0, f"premise: git {args[0]} must succeed"


@pytest.mark.skipif(not _HAS_GIT, reason="git is not installed")
async def test_git_add_stages_an_option_shaped_name(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, "main")
    name = "--bf894-option-shaped.txt"
    (repo / name).write_text("x\n", encoding="utf-8")
    bare = _git(repo, "add", name)
    staged = _git(repo, "diff", "--cached", "--name-only").stdout.splitlines()
    assert bare.returncode != 0 and name not in staged, "premise: without '--' git parses the name as an option"
    ok, sha = await _git_add_and_commit([name], "bf894 probe", str(repo))
    assert ok, sha
    assert name in _git(repo, "ls-tree", "--name-only", "HEAD").stdout.splitlines()


def _linked_worktree(tmp_path: Path) -> tuple[Path, Path, Path]:
    base, victim, wt = tmp_path / "base", tmp_path / "victim", tmp_path / "wt"
    _init_repo(base, "trunk")
    _init_repo(victim, "trunk")
    assert _git(base, "worktree", "add", "-q", "-b", "main", str(wt)).returncode == 0, "premise"
    (base / ".git" / "info").mkdir(exist_ok=True)
    with open(base / ".git" / "info" / "exclude", "a", encoding="utf-8") as fh:
        fh.write("pointer-alias\n")  # keeps the hard link out of `git status`
    pointer = wt / ".git"
    assert pointer.is_file(), "premise: a linked worktree's .git is a pointer file"
    if sys.platform == "win32":
        subprocess.run(["attrib", "-h", str(pointer)], check=True, capture_output=True)
        assert not os.stat(pointer).st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN, "premise: pointer not hidden"
    return wt, victim, pointer


@pytest.mark.skipif(not _HAS_GIT, reason="git is not installed")
@pytest.mark.parametrize("alias", ["pointer-alias", ".GiT", "GIT~1"])
async def test_alias_write_does_not_move_the_repository(tmp_path: Path, alias: str) -> None:
    wt, victim, pointer = _linked_worktree(tmp_path)
    if alias == "pointer-alias":
        os.link(pointer, wt / alias)
    if not (wt / alias).exists() or not os.path.samefile(wt / alias, pointer):
        pytest.skip(f"{alias} is not an alias of .git here (case-sensitive filesystem or no 8.3 names)")
    git_dir = _git(wt, "rev-parse", "--absolute-git-dir").stdout.strip()
    victim_head = _git(victim, "rev-parse", "HEAD").stdout.strip()
    pointer_bytes = pointer.read_bytes()
    assert _git(wt, "status", "--porcelain").stdout == "", "premise: the worktree is clean, so the build runs"
    change = _create(alias, f"gitdir: {(victim / '.git').as_posix()}\n")
    result = await execute_approved_build([change], BuildSpec(title="BF-894 probe", description=""), str(wt), run_tests=False)
    assert "Forbidden" in result.error
    assert pointer.read_bytes() == pointer_bytes
    assert _git(wt, "rev-parse", "--absolute-git-dir").stdout.strip() == git_dir
    assert _git(victim, "rev-parse", "HEAD").stdout.strip() == victim_head
    assert _git(victim, "branch", "--list").stdout.split() == ["*", "trunk"]


@pytest.mark.skipif(not _HAS_GIT, reason="git is not installed")
async def test_legitimate_build_commits_in_the_linked_worktree(tmp_path: Path) -> None:
    wt, victim, _pointer = _linked_worktree(tmp_path)
    git_dir = _git(wt, "rev-parse", "--absolute-git-dir").stdout.strip()
    victim_head = _git(victim, "rev-parse", "HEAD").stdout.strip()
    result = await execute_approved_build([_create("src/ok.py", "x = 1\n")], BuildSpec(title="BF-894 control", description=""), str(wt), run_tests=False)
    assert result.success and result.commit_hash, result.error
    assert _git(wt, "log", "-1", "--format=%s", result.branch_name).stdout.strip() == "BF-894 control"
    assert _git(wt, "rev-parse", "--absolute-git-dir").stdout.strip() == git_dir
    assert _git(victim, "rev-parse", "HEAD").stdout.strip() == victim_head
