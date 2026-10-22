"""BF-904b (#1585), milestone M2: refusals are permanent, syntax is state, and a refused build runs nothing.

Before M2 one list held both: every refusal and every syntax error, recorded when each file was written, so a
syntax error a repair fixed still blocked the commit; the files the targeted tests ran on were fixed before the
first attempt, so a repair's new file was never targeted; and a build holding a refusal still ran its review, its
model-written tests and its repairs (#1523 F-153 item 18). M2 keeps refusals in ``validation_errors``, reads the
syntax of every written file at the commit decision on the files as they are then, reads the changed files at each
attempt, and skips the review, the tests and the repairs after a refusal.

Rules: real git in repositories under ``tmp_path`` (helpers copied from the BF-904a tests). The model and the
targeted-test runner are stand-ins: the model's text is untrusted input and the runner is BF-897's. No sleeps;
every await and subprocess is bounded.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from collections.abc import Awaitable
from pathlib import Path
from types import SimpleNamespace as _SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.cognitive import builder as builder_module
from probos.cognitive.builder import BuildResult, BuildSpec, execute_approved_build

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

TARGET = "src/probos/a.py"
OTHER = "src/probos/other.py"
NEW = "src/probos/newpkg/fresh.py"
BAD = "src/probos/bad.py"
SEED = {TARGET: "x = 1\n", OTHER: "y = 1\n"}
BROKEN = "def broken(:\n"
REFUSED = "../outside.py"
OUTSIDE_TEXT = "external = 1\n"  # A3: valid Python outside the work tree, which the final read must never parse
_Denied = PermissionError  # A3: the injected examination failure's class, aliased like the doubles' names
_REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def _no_ambient_git_names(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.upper().startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)


def _control_env() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if not name.upper().startswith("GIT_")}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _REAL_RUN(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        env=_control_env(), stdin=subprocess.DEVNULL, timeout=60,
    )


def _init_repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True)
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "bf904b@example.invalid"),
        ("config", "user.name", "BF904b Tester"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.autocrlf", "false"),
    ):
        assert _git(path, *args).returncode == 0, f"premise: git {args[0]} must succeed"
    for rel, text in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    assert _git(path, "add", "-A").returncode == 0, "premise: git add must succeed"
    assert _git(path, "commit", "-q", "-m", "seed").returncode == 0, "premise: the seed commit"
    return path


def _blob(repo: Path, ref: str, path: str) -> str:
    shown = _git(repo, "show", f"{ref}:{path}")
    assert shown.returncode == 0, f"{ref}:{path} must exist in the repository ({shown.stderr.strip()})"
    return shown.stdout.replace("\r\n", "\n")


def _create(path: str, content: str) -> dict[str, Any]:
    return {"path": path, "mode": "create", "content": content}


def _modify(path: str, search: str, replace: str) -> dict[str, Any]:
    return {"path": path, "mode": "modify", "replacements": [{"search": search, "replace": replace}]}


async def _bounded(awaited: Awaitable[Any], seconds: float = 120) -> Any:
    return await asyncio.wait_for(awaited, timeout=seconds)


async def _build(work_dir: Path, changes: list[dict[str, Any]], **kwargs: Any) -> BuildResult:
    kwargs.setdefault("run_tests", False)
    return await _bounded(execute_approved_build(changes, BuildSpec(title="bf904b fix loop", description=""), str(work_dir), **kwargs))


class _Targeted:
    """Stands in for ``_run_targeted_tests``: answers *passes* in order and records each call's changed files."""

    def __init__(self, passes: list[bool]) -> None:
        self._passes = list(passes)
        self.calls: list[list[str]] = []

    async def __call__(self, work_dir: str, changed_files: list[str], timeout: int = 60) -> tuple[bool, str, list[str]]:
        self.calls.append(list(changed_files))
        passed = self._passes.pop(0)
        return passed, ("1 passed" if passed else "1 failed"), ["tests/test_a.py"]


class _FakeModel:
    """A model client whose every answer is *reply* (the code review reads it too); it keeps every request."""

    def __init__(self, reply: str) -> None:
        self.complete = AsyncMock(return_value=_SimpleNamespace(content=reply))

    def fix_prompts(self) -> list[str]:
        prompts = [call.args[0].prompt for call in self.complete.await_args_list]
        return [prompt for prompt in prompts if "Test Fix Required" in prompt]


# F1
async def test_a_syntax_error_a_repair_fixes_no_longer_blocks_the_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    targeted = _Targeted([False, True])
    monkeypatch.setattr(builder_module, "_run_targeted_tests", targeted)
    model = _FakeModel(f"===FILE: {BAD}===\nok = 1\n===END FILE===\n")
    result = await _build(repo, [_create(BAD, BROKEN)], run_tests=True, llm_client=model)
    assert result.fix_attempts == 1 and len(model.fix_prompts()) == 1, "premise: the first write failed and one repair ran"
    assert len(targeted.calls) == 2 and result.tests_passed is True, "premise: the tests passed after the repair"
    assert result.success and result.commit_hash, result.error
    assert _blob(repo, result.branch_name, BAD) == "ok = 1\n"


# F2
async def test_a_file_a_repair_creates_is_targeted_on_the_next_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    targeted = _Targeted([False, True])
    monkeypatch.setattr(builder_module, "_run_targeted_tests", targeted)
    model = _FakeModel(f"===FILE: {NEW}===\nok = 1\n===END FILE===\n")
    result = await _build(repo, [_modify(TARGET, "x = 1", "x = 2")], run_tests=True, llm_client=model)
    assert result.success and result.commit_hash, result.error
    assert targeted.calls[0] == [TARGET], targeted.calls
    assert NEW in targeted.calls[1], targeted.calls


# F3
async def test_a_refusal_blocks_the_commit_whatever_the_syntax_state(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    result = await _build(repo, [_create(NEW, "ok = 1\n"), _create(REFUSED, "x = 1\n")])
    assert result.files_written == [NEW], "premise: the admitted file was written and parses"
    assert result.success is False and not result.commit_hash
    assert result.error.startswith("Syntax errors") and "Path traversal blocked" in result.error, result.error
    assert not (repo / NEW).exists(), "the failed build deletes the file it created"


# F4
async def test_a_build_with_a_refusal_runs_no_tests_review_or_repair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    targeted = _Targeted([False, True])
    monkeypatch.setattr(builder_module, "_run_targeted_tests", targeted)
    model = _FakeModel(f"===FILE: {NEW}===\nok = 2\n===END FILE===\n")
    result = await _build(repo, [_create(NEW, "ok = 1\n"), _create(REFUSED, "x = 1\n")], run_tests=True, llm_client=model)
    assert result.files_written == [NEW], "premise: the admitted file was written"
    assert targeted.calls == [], "a build holding a refusal runs no model-written tests"
    assert model.complete.await_count == 0, "and asks for no review and no repair"
    assert result.success is False and "Path traversal blocked" in result.error, result.error
    assert not (repo / NEW).exists()


# F5
@pytest.mark.parametrize("where", ["main-create", "main-modify", "repair"])
async def test_a_syntax_error_still_there_after_the_loop_blocks_the_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str,
) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    model: _FakeModel | None = None
    if where == "repair":
        targeted = _Targeted([False, True])
        changes = [_modify(TARGET, "x = 1", "x = 2")]
        model = _FakeModel(f"===FILE: {BAD}===\n{BROKEN}===END FILE===\n")
        broken = BAD
    else:
        targeted = _Targeted([True])
        changes = [_create(BAD, BROKEN)] if where == "main-create" else [_modify(TARGET, "x = 1", "x = (")]
        broken = BAD if where == "main-create" else TARGET
    monkeypatch.setattr(builder_module, "_run_targeted_tests", targeted)
    result = await _build(repo, changes, run_tests=True, llm_client=model)
    assert result.tests_passed is True, "premise: the last test run passed"
    assert result.success is False and not result.commit_hash
    assert result.error.startswith("Syntax errors") and str(repo / broken) in result.error, result.error


# F6
@pytest.mark.parametrize("left", ["broken", "deleted", "undecodable", "directory"])
async def test_the_syntax_state_is_read_from_the_files_the_tests_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, left: str,
) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    created = repo / NEW

    async def tests_that_change_the_file(work_dir: str, changed_files: list[str], timeout: int = 60) -> tuple[bool, str, list[str]]:
        if left == "broken":
            created.write_bytes(BROKEN.encode("utf-8"))
        elif left == "deleted":
            created.unlink()
        elif left == "undecodable":
            created.write_bytes(b"\xff\xfe = 1\n")
        else:  # BF-904b A3: a directory where the file was
            created.unlink()
            created.mkdir()
        return True, "1 passed", ["tests/test_fresh.py"]

    monkeypatch.setattr(builder_module, "_run_targeted_tests", tests_that_change_the_file)
    result = await _build(repo, [_create(NEW, "ok = 1\n")], run_tests=True)
    expected = {
        "broken": "line 1",
        "deleted": "is no longer a regular file",
        "undecodable": "could not be read for the syntax check (UnicodeDecodeError)",
        "directory": "is no longer a regular file",
    }[left]
    assert result.tests_passed is True, "premise: the tests passed"
    assert result.success is False and not result.commit_hash, result.error
    assert result.error.startswith("Syntax errors") and str(created) in result.error and expected in result.error, result.error
    if left != "directory":  # BF-904b A3: a directory the tests left is reported by the cleanup, not removed
        assert not created.exists(), "the failed build deletes the file it created"


def _alias(link: Path, target: Path) -> bool:
    """Make *link* an alias of *target*: a symbolic link, else on Windows a junction to a directory; False if neither."""
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name != "nt" or not target.is_dir():
        return False
    made = _REAL_RUN(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True, check=False,
        stdin=subprocess.DEVNULL, timeout=60,
    )
    return made.returncode == 0 and os.path.isjunction(link)


# F7
@pytest.mark.parametrize("where", ["ancestor", "leaf"])
async def test_an_alias_the_tests_leave_is_refused_and_its_target_never_parsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str,
) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    created = repo / NEW
    outside = tmp_path / "outside" / "newpkg"
    outside.mkdir(parents=True)
    (outside / "fresh.py").write_bytes(OUTSIDE_TEXT.encode("utf-8"))
    link, target = (created.parent, outside) if where == "ancestor" else (created, outside / "fresh.py")
    if not _alias(tmp_path / "probe", target):
        pytest.skip("this host can make neither a symbolic link nor a junction for this alias")
    made: list[bool] = []

    async def tests_that_leave_an_alias(work_dir: str, changed_files: list[str], timeout: int = 60) -> tuple[bool, str, list[str]]:
        created.unlink()
        if where == "ancestor":
            created.parent.rmdir()
        made.append(_alias(link, target))
        return True, "1 passed", ["tests/test_fresh.py"]

    real_parse = builder_module.ast.parse
    parsed: list[Any] = []

    def parse_and_record(source: Any, *args: Any, **kwargs: Any) -> Any:
        parsed.append(source)
        return real_parse(source, *args, **kwargs)

    monkeypatch.setattr(builder_module, "_run_targeted_tests", tests_that_leave_an_alias)
    monkeypatch.setattr(builder_module.ast, "parse", parse_and_record)
    result = await _build(repo, [_create(NEW, "ok = 1\n")], run_tests=True)
    assert made == [True] and result.tests_passed is True, "premise: the tests passed and left the alias"
    assert OUTSIDE_TEXT not in parsed, "the text outside the work tree is never parsed"
    assert result.success is False and not result.commit_hash, result.error
    assert result.error.startswith("Syntax errors") and f"{created}: resolves outside the work tree; refused" in result.error, result.error
    # Not asserted: that the outside file outlives the build. The failed build's cleanup deletes the created path
    # through an ancestor alias (_restore_pre_build_files); that is F-124 on #1523, not the syntax read.


# F8
@pytest.mark.parametrize("fault", ["stat-fails", "swapped-before-open"])
async def test_a_file_that_cannot_be_examined_after_the_tests_is_one_syntax_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    repo = _init_repo(tmp_path / "repo", SEED)
    created = repo / NEW
    names = {os.path.normcase(os.path.abspath(name)) for name in (created, os.path.join(os.path.realpath(repo), NEW))}
    armed: list[bool] = []
    faults: list[str] = []

    def failing(real_call: Any) -> Any:
        def call(target: Any, *args: Any, **kwargs: Any) -> Any:
            if armed and not isinstance(target, int) and os.path.normcase(os.path.abspath(os.fspath(target))) in names:
                faults.append(os.fspath(target))
                raise _Denied(13, "injected stat failure", os.fspath(target))
            return real_call(target, *args, **kwargs)

        return call

    def swapped_open(name: str, flags: int) -> int:
        return os.open(repo / OTHER, os.O_RDONLY | getattr(os, "O_BINARY", 0))

    async def tests_then_arm(work_dir: str, changed_files: list[str], timeout: int = 60) -> tuple[bool, str, list[str]]:
        armed.append(True)
        return True, "1 passed", ["tests/test_fresh.py"]

    real_syntax_errors = builder_module._syntax_errors

    def syntax_then_disarm(*args: Any) -> list[str]:
        try:
            return real_syntax_errors(*args)
        finally:
            armed.clear()  # the cleanup's own examination of the file runs unfaulted

    if fault == "stat-fails":
        monkeypatch.setattr(os, "stat", failing(os.stat))
        monkeypatch.setattr(os, "lstat", failing(os.lstat))
    else:
        # raising=False: before A3 there is no opener to replace, and the build must then fail the assertions below.
        monkeypatch.setattr(builder_module, "_syntax_read_opener", swapped_open, raising=False)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", tests_then_arm)
    monkeypatch.setattr(builder_module, "_syntax_errors", syntax_then_disarm)
    result = await _build(repo, [_create(NEW, "ok = 1\n")], run_tests=True)
    expected = {
        "stat-fails": "could not be read for the syntax check (PermissionError)",
        "swapped-before-open": "changed while it was read",
    }[fault]
    assert result.tests_passed is True, "premise: the tests passed"
    assert fault != "stat-fails" or faults, "premise: the injected failure fired after the tests"
    assert result.success is False and not result.commit_hash, result.error
    assert result.error.startswith("Syntax errors") and f"{created}: {expected}; refused" in result.error, result.error
    assert not created.exists(), "the failed build deletes the file it created"
