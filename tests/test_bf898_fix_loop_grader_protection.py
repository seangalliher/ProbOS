"""BF-898 (#1563): the unreviewed test-fix loop may change source only.

The repair step of ``execute_approved_build`` writes the model's repair and re-runs the
build's tests. Before BF-898 it could write any path ``builder_write_refusal`` allowed, so a
failing build could be made to pass by changing what grades it: deleting, skipping or
rewriting its test, adding a ``conftest.py`` hook or a ``pytest.ini`` that deselects the test,
or editing the build's own grader. ``fix_loop_write_refusal`` closes that. It refuses, in this
order, a path holding a control or line-break character (with its own reason), everything
``builder_write_refusal`` refuses (with that reason), then any path that is not a plain relative
path under ``src/probos/``, any of ``FIX_LOOP_PROTECTED_PATHS`` and any file named one of
``FIX_LOOP_REFUSED_NAMES``; ``fix_loop_self_test`` judges the examples in ``FIX_LOOP_SELF_TEST``
against it.

Group T-S (pure: no git, no subprocess) proves the rule and its self-test: the self-test
passes, its examples cover every protected path and refused name and include paths the loop
may write, it reports a wrong example instead of passing vacuously, a control or line-break
character is refused before the write boundary's own reason (which a path without one keeps),
and every BF-898 refusal names the rule and the path as given (quoted with ``repr`` when it
holds a control character).

``_WIDGET`` to ``_REPAIRS`` are the shared fixture text for groups T-U, T-P and T-R: a one-file
approved change, the two-test file that grades it (one test fails against it) and the six repair
replies, five that weaken the grader and one source fix as the control.

Group T-U drives ``execute_approved_build`` with a fake test runner and fake git (the BF-897
``fake_git`` and ``build_tree`` fixtures): a repair response with one refused block is refused
whole and stops the loop, the files the loop changed are disclosed in the metadata and the commit
message, approved writes keep their scope and the fix prompt states the rule. Group T-P proves,
with the real targeted pytest run and no git, that each of the five weakenings would make the
failing test pass, so the replay discriminates. Group T-R is the replay: real git, the real
executor and the real pytest run take each repair reply through parse, refusal, the commit gate
and the git outcome, and the source fix commits.
"""

from __future__ import annotations

import shutil
import subprocess
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.cognitive import builder as builder_module
from probos.cognitive import builder_paths
from probos.cognitive.builder import (
    BuilderAgent,
    BuildResult,
    BuildSpec,
    _build_fix_prompt,
    _run_targeted_tests,
    execute_approved_build,
)
from probos.cognitive.builder_paths import (
    FIX_LOOP_PROTECTED_PATHS,
    FIX_LOOP_REFUSED_NAMES,
    FIX_LOOP_SELF_TEST,
    builder_write_refusal,
    fix_loop_path,
    fix_loop_self_test,
    fix_loop_write_refusal,
    operator_checkout_refusal,
)

# Shared fixture text. The approved change creates _WIDGET with _WIDGET_V1, so the first
# targeted run of _TEST_TEXT is "1 failed, 1 passed" (test_value fails). The test imports
# nothing from the work tree, so no installed ``probos`` package can stand in for it.
_WIDGET = "src/probos/widget.py"
_WIDGET_V1 = "VALUE = 1\n"
_WIDGET_TEST = "tests/test_widget.py"
_TEST_TEXT = (
    "import pathlib\n"
    "import pytest\n"
    "\n"
    "SOURCE = pathlib.Path(__file__).resolve().parent.parent / 'src' / 'probos' / 'widget.py'\n"
    "\n"
    "\n"
    "def test_present() -> None:\n"
    "    assert SOURCE.is_file()\n"
    "\n"
    "\n"
    "def test_value() -> None:\n"
    "    assert 'VALUE = 2' in SOURCE.read_text(encoding='utf-8')\n"
)

# The six repair replies, keyed by case: the exact ===FILE: / ===MODIFY: text the fake model
# returns. The first five try to make test_value stop failing by changing what grades it, and
# each names a path BF-898 refuses; source_fix is the control and changes the source.
_REPAIRS: dict[str, str] = {
    "conftest_hook": (
        "===FILE: tests/conftest.py===\n"
        "def pytest_collection_modifyitems(config, items):\n"
        "    config.hook.pytest_deselected(items=[i for i in items if i.name == 'test_value'])\n"
        "    items[:] = [i for i in items if i.name != 'test_value']\n"
        "===END FILE===\n"
    ),
    "delete_test": (
        "===FILE: " + _WIDGET_TEST + "===\n"
        + _TEST_TEXT.partition("\n\ndef test_value")[0]  # _TEST_TEXT minus test_value
        + "===END FILE===\n"
    ),
    "skip_marker": (
        f"===MODIFY: {_WIDGET_TEST}===\n"
        "===SEARCH===\n"
        "def test_value() -> None:\n"
        "===REPLACE===\n"
        "@pytest.mark.skip(reason='bf898')\n"
        "def test_value() -> None:\n"
        "===END REPLACE===\n"
        "===END MODIFY===\n"
    ),
    "edit_assertion": (
        f"===MODIFY: {_WIDGET_TEST}===\n"
        "===SEARCH===\n"
        "assert 'VALUE = 2' in\n"
        "===REPLACE===\n"
        "assert 'VALUE = 1' in\n"
        "===END REPLACE===\n"
        "===END MODIFY===\n"
    ),
    "root_pytest_ini": (
        "===FILE: pytest.ini===\n"
        "[pytest]\n"
        f"addopts = --deselect {_WIDGET_TEST}::test_value\n"
        "===END FILE===\n"
    ),
    "source_fix": (
        f"===MODIFY: {_WIDGET}===\n"
        "===SEARCH===\n"
        "VALUE = 1\n"
        "===REPLACE===\n"
        "VALUE = 2\n"
        "===END REPLACE===\n"
        "===END MODIFY===\n"
    ),
}


# --- T-S: the rule and its self-test (pure, no git) ---


def test_fix_loop_self_test_passes() -> None:
    assert FIX_LOOP_SELF_TEST, "premise: the self-test has examples to judge"
    assert fix_loop_self_test() == ()


def test_self_test_covers_every_protected_path_and_name() -> None:
    assert FIX_LOOP_PROTECTED_PATHS and FIX_LOOP_REFUSED_NAMES, "premise: there is something to cover"
    missing = [path for path in FIX_LOOP_PROTECTED_PATHS if (path, True) not in FIX_LOOP_SELF_TEST]
    for name in FIX_LOOP_REFUSED_NAMES:
        missing += [
            form for form in (name, f"src/probos/{name}") if (form, True) not in FIX_LOOP_SELF_TEST
        ]
    assert missing == [], f"no refused self-test example for: {missing}"
    allowed = [path for path, refused in FIX_LOOP_SELF_TEST if not refused]
    assert len(allowed) >= 5, f"the self-test needs paths the loop may write; found {allowed}"


def test_self_test_reports_a_failing_example(monkeypatch: pytest.MonkeyPatch) -> None:
    assert fix_loop_write_refusal("src/probos/widget.py") is None, "premise: the rule allows widget.py"
    monkeypatch.setattr(builder_paths, "FIX_LOOP_SELF_TEST", (("src/probos/widget.py", True),))
    failures = fix_loop_self_test()
    assert len(failures) == 1, f"expected one failure line, got {failures}"
    assert "src/probos/widget.py" in failures[0] and "expected refused" in failures[0]


def test_a_path_without_a_control_character_keeps_the_write_boundarys_reason() -> None:
    for path in (".git/config", "src/probos/con.py", "src/probos/a:b.py"):
        boundary = builder_write_refusal(path)
        assert boundary is not None, f"premise: the write boundary itself refuses {path}"
        assert fix_loop_write_refusal(path) == boundary, f"{path}: the boundary's reason must be kept"


@pytest.mark.parametrize(
    "path",
    ["tests/test_x.py", "src/probos/cognitive/builder.py", "src/probos/conftest.py", "src/probos//x.py"],
)
def test_every_bf898_refusal_names_the_rule_and_the_path(path: str) -> None:
    assert builder_write_refusal(path) is None, "premise: the write boundary allows it, so the refusal is BF-898's"
    refusal = fix_loop_write_refusal(path)
    assert refusal is not None, f"premise: the fix loop refuses {path}"
    assert "BF-898" in refusal
    assert path in refusal


# BF-898 review r1: the characters (category Cc, Zl or Zp) a path may not hold.
_LINE_BREAKING_CHARS = ["\n", "\r", "\t", "\x0b", "\x0c", "\x00", "\x1b", "\x7f", "\x85", "\u2028", "\u2029"]
_CHAR_IDS = [f"U+{ord(char):04X}" for char in _LINE_BREAKING_CHARS]
_ALLOWED_WIDGET = "src/probos/widget.py"


def _has_line_breaking_char(text: str) -> bool:
    return any(unicodedata.category(char) in ("Cc", "Zl", "Zp") for char in text)


@pytest.mark.parametrize("position", ["file_start", "file_inside", "dir_inside", "path_end"])
@pytest.mark.parametrize("char", _LINE_BREAKING_CHARS, ids=_CHAR_IDS)
def test_control_and_line_break_characters_are_refused_in_every_position(char: str, position: str) -> None:
    builds = {
        "file_start": lambda c: f"src/probos/{c}widget.py",
        "file_inside": lambda c: f"src/probos/wid{c}get.py",
        "dir_inside": lambda c: f"src/probos/su{c}b/widget.py",
        "path_end": lambda c: f"src/probos/widget.py{c}",
    }
    path = builds[position](char)
    neutral = builds[position]("_")
    assert _has_line_breaking_char(char) and _has_line_breaking_char(path), "premise: the path holds the character"
    assert fix_loop_write_refusal(neutral) is None, f"premise: {neutral!r} is allowed, so only the character refuses"

    refusal = fix_loop_write_refusal(path)

    assert refusal is not None
    assert "BF-898" in refusal
    assert not _has_line_breaking_char(refusal), f"the reason must stay one line, got {refusal!r}"
    assert repr(path) in refusal


@pytest.mark.parametrize("char", _LINE_BREAKING_CHARS, ids=_CHAR_IDS)
def test_a_control_character_at_the_start_of_the_whole_path_is_refused_for_the_character(char: str) -> None:
    path = f"{char}{_ALLOWED_WIDGET}"
    neutral_refusal = fix_loop_write_refusal(f"_{_ALLOWED_WIDGET}")
    assert neutral_refusal is not None and "control or line-break" not in neutral_refusal, (
        "premise: with '_' the path is refused for another reason (outside src/probos/)"
    )

    refusal = fix_loop_write_refusal(path)

    assert refusal is not None and "control or line-break" in refusal
    assert repr(path) in refusal and not _has_line_breaking_char(refusal)


def test_a_control_character_is_refused_before_the_write_boundary_reason() -> None:
    plain = ".git/config"
    broken = ".git/config\nx"
    assert builder_write_refusal(plain) is not None, "premise: BF-894 refuses the .git alias"
    assert builder_write_refusal(broken) is not None, "premise: BF-894 refuses it with the character too"

    refusal = fix_loop_write_refusal(broken)

    assert refusal is not None and "control or line-break" in refusal
    assert refusal != builder_write_refusal(broken), "the control character, not BF-894's reason, is named"
    assert fix_loop_write_refusal(plain) == builder_write_refusal(plain), (
        "a path without a control character keeps BF-894's reason"
    )


def test_a_nul_in_a_path_is_refused_before_the_filesystem_check(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "src" / "probos").mkdir(parents=True)
    path = "src/probos/a\x00b.py"
    with pytest.raises(ValueError):
        builder_write_refusal(path, tmp_path)  # premise: the BF-894 check alone raises on a NUL

    refusal = fix_loop_write_refusal(path, tmp_path)

    assert refusal is not None and "BF-898" in refusal
    assert repr(path) in refusal and not _has_line_breaking_char(refusal)


def test_fix_loop_path_puts_a_path_in_one_spelling() -> None:
    assert fix_loop_path("src\\probos\\widget.py") == "src/probos/widget.py"
    assert fix_loop_path("src/probos\\x.py") == "src/probos/x.py"
    assert fix_loop_path("src/probos/x.py") == "src/probos/x.py", "premise: a slash path is unchanged"
    for spelled in ("src\\probos\\widget.py", "src/probos\\x.py", "a\\b/c"):
        assert fix_loop_path(fix_loop_path(spelled)) == fix_loop_path(spelled), "idempotent"
    assert fix_loop_path("") == ""


def test_the_rule_gives_one_verdict_for_both_spellings_of_a_path() -> None:
    admitted = "src/probos/widget.py"
    refused = "src/probos/cognitive/builder.py"
    assert fix_loop_write_refusal(admitted) is None, "premise: the slash spelling is admitted"
    assert fix_loop_write_refusal(refused) is not None, "premise: the slash spelling is refused"

    assert fix_loop_write_refusal(admitted.replace("/", "\\")) is None
    assert fix_loop_write_refusal(fix_loop_path(admitted.replace("/", "\\"))) is None
    assert fix_loop_write_refusal(refused.replace("/", "\\")) is not None
    assert fix_loop_write_refusal("src\\probos\\cognitive\\builder.py") is not None


@pytest.mark.parametrize("char", _LINE_BREAKING_CHARS, ids=_CHAR_IDS)
def test_self_test_has_a_refused_example_for_each_line_breaking_character(char: str) -> None:
    assert FIX_LOOP_SELF_TEST, "premise: the self-test has examples"
    assert (f"src/probos/a{char}b.py", True) in FIX_LOOP_SELF_TEST


# --- helpers for groups T-U, T-P and T-R ---
#
# Copied, not imported, from tests/test_bf897_build_pipeline_scale_and_checkout.py; its _FakeLLM
# takes the reply as a parameter here. Every repository and work tree below is a temporary one under
# ``tmp_path``: no test in this file touches the repository it runs from.

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not found on PATH")

# Variables that point a git command at another repository. A gate launched from a git hook
# inherits them, and they would send every git call below to the repository the tests run from.
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
        ("config", "user.email", "bf898@example.invalid"),
        ("config", "user.name", "BF898 Tester"),
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


# -- the executor's launches, replaced, and a model client that keeps what it was asked ----------


class _FakeBuildGit:
    """The git launches of ``execute_approved_build``, replaced: none of them runs git, each records its awaits."""

    def __init__(self) -> None:
        self.create_branch = AsyncMock(return_value=(True, "builder/bf898"))
        self.checkout_main = AsyncMock(return_value=(True, "switched to main"))
        self.current_branch = AsyncMock(return_value="main")
        self.add_and_commit = AsyncMock(return_value=(True, "abc1234"))
        self.is_dirty = AsyncMock(return_value=False)
        self.run_git = AsyncMock(return_value=(0, "", ""))

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name, fake in (
            ("_git_create_branch", self.create_branch),
            ("_git_checkout_main", self.checkout_main),
            ("_git_current_branch", self.current_branch),
            ("_git_add_and_commit", self.add_and_commit),
            ("_is_dirty_working_tree", self.is_dirty),
            ("_run_git", self.run_git),
        ):
            monkeypatch.setattr(builder_module, name, fake)


class _FakeLLM:
    """A model client whose every answer is *reply* (the code review reads it too); it keeps every request."""

    def __init__(self, reply: str) -> None:
        self.complete = AsyncMock(return_value=SimpleNamespace(content=reply))

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


def _seed(tree: Path, rel: str, text: str) -> Path:
    """Write *text* to *rel* under *tree* (LF endings) and return the file."""
    target = tree / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


# The path each weakening reply names, which BF-898 must refuse; source_fix, the control, has none.
_REFUSED_PATH: dict[str, str] = {
    "conftest_hook": "tests/conftest.py",
    "delete_test": _WIDGET_TEST,
    "skip_marker": _WIDGET_TEST,
    "edit_assertion": _WIDGET_TEST,
    "root_pytest_ini": "pytest.ini",
}


# --- T-U: the fix loop with a fake runner and fake git ---
#
# The two tests that drive a repair (the first two) seed src/probos/foo.py before the build, and the
# approved change is a create over it with the same text. The file is pre-existing, so it lands in
# files_modified and survives the failed-build cleanup, which unlinks only files_written: a file the
# fix loop created is gone after a failed build whether or not it was written, so the seeded file is
# what tells "written" from "refused". The approved-scope test runs no tests and so has no repair
# and no failed build to survive; the prompt test calls ``_build_fix_prompt`` alone.

_FOO = "src/probos/foo.py"
_FOO_TEXT = "x = 1\n"
_OTHER = "src/probos/other.py"
_OTHER_TEXT = "z = 1\n"
_HELPER = "src/probos/helper.py"
_CONFTEST = "tests/conftest.py"
_MAPPED = ["tests/test_foo.py"]
_FOO_TO_2 = (
    f"===MODIFY: {_FOO}===\n"
    "===SEARCH===\nx = 1\n===REPLACE===\nx = 2\n===END REPLACE===\n"
    "===END MODIFY===\n"
)


async def _gated_build(tree: Path, llm: _FakeLLM, *, max_fix_attempts: int = 2) -> BuildResult:
    """``execute_approved_build`` with the test phase on: a create over the seeded ``foo.py`` with its own text."""
    return await execute_approved_build(
        [{"path": _FOO, "mode": "create", "content": _FOO_TEXT}],
        BuildSpec(title="bf898", description="d"),
        str(tree),
        run_tests=True,
        max_fix_attempts=max_fix_attempts,
        llm_client=llm,
    )


async def test_a_response_with_one_refused_block_is_refused_whole_and_stops_the_loop(
    build_tree: Path, tmp_path: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch,
) -> None:
    foo = _seed(build_tree, _FOO, _FOO_TEXT)
    runner = AsyncMock(return_value=(False, "1 failed", _MAPPED))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    reply = _FOO_TO_2 + f"===FILE: {_CONFTEST}===\ncollect_ignore = ['test_foo.py']\n===END FILE===\n"
    llm = _FakeLLM(reply)
    parsed = sorted((block["mode"], block["path"]) for block in BuilderAgent._parse_file_blocks(reply))
    assert parsed == [("create", _CONFTEST), ("modify", _FOO)], "premise: one source block and one conftest block"
    assert fix_loop_write_refusal(_FOO) is None, "premise: the source block alone would be allowed"
    assert fix_loop_write_refusal(_CONFTEST) is not None, "premise: the conftest block is refused"

    result = await _gated_build(build_tree, llm, max_fix_attempts=2)

    assert len(llm.fix_prompts()) == 1, f"a refused response stops the loop: one repair request only: {result.error}"
    assert foo.read_text(encoding="utf-8") == _FOO_TEXT, (
        "no block of the response may be written, the allowed one included"
    )
    assert runner.await_count == 1, "a refused response stops the loop: no rerun"
    assert result.fix_attempts == 1
    fake_git.add_and_commit.assert_not_awaited()
    assert result.success is False
    assert "BF-898" in result.error and _CONFTEST in result.error, result.error
    assert "fix_loop_files" not in result.metadata

    # Control, on a fresh tree: the same response without the conftest block is applied and the
    # rerun commits, so the untouched foo.py above is the refusal's doing, not a block that cannot apply.
    control_tree = _plain_tree(tmp_path, "control")
    control_foo = _seed(control_tree, _FOO, _FOO_TEXT)
    control_runner = AsyncMock(side_effect=[(False, "1 failed", _MAPPED), (True, "1 passed", _MAPPED)])
    monkeypatch.setattr(builder_module, "_run_targeted_tests", control_runner)

    control = await _gated_build(control_tree, _FakeLLM(_FOO_TO_2), max_fix_attempts=2)

    assert control.success is True, control.error
    assert control_runner.await_count == 2
    assert control_foo.read_text(encoding="utf-8") == "x = 2\n"
    fake_git.add_and_commit.assert_awaited_once()


async def test_fix_loop_files_are_disclosed_in_metadata_and_commit_message(
    build_tree: Path, tmp_path: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(build_tree, _FOO, _FOO_TEXT)
    other = _seed(build_tree, _OTHER, _OTHER_TEXT)
    runner = AsyncMock(side_effect=[(False, "1 failed", _MAPPED), (True, "1 passed", _MAPPED)])
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    reply = (
        _FOO_TO_2
        + f"===FILE: {_HELPER}===\ny = 1\n===END FILE===\n"
        + f"===MODIFY: {_OTHER}===\n===SEARCH===\nnope\n===REPLACE===\nz = 2\n===END REPLACE===\n===END MODIFY===\n"
    )
    llm = _FakeLLM(reply)
    parsed = sorted((block["mode"], block["path"]) for block in BuilderAgent._parse_file_blocks(reply))
    assert parsed == [("create", _HELPER), ("modify", _FOO), ("modify", _OTHER)], "premise: three source blocks"
    assert "nope" not in other.read_text(encoding="utf-8"), "premise: the third block's SEARCH text is not in the file"

    result = await _gated_build(build_tree, llm, max_fix_attempts=2)

    assert runner.await_count == 2 and len(llm.fix_prompts()) == 1, (
        f"premise: one repair was requested and applied, and the rerun passed: {result.error}"
    )
    assert other.read_text(encoding="utf-8") == _OTHER_TEXT, "premise: the third block changed nothing"
    assert result.success is True, result.error
    assert result.metadata["fix_loop_files"] == [_FOO, _HELPER], "only real changes are disclosed"
    message = fake_git.add_and_commit.await_args.args[1]
    assert f"Changed by the unreviewed test-fix loop (BF-898): {_FOO}, {_HELPER}" in message

    # Control, on a fresh tree: the first run passes, no repair is requested, and nothing is disclosed.
    control_tree = _plain_tree(tmp_path, "control")
    _seed(control_tree, _FOO, _FOO_TEXT)
    control_runner = AsyncMock(return_value=(True, "1 passed", _MAPPED))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", control_runner)
    control_llm = _FakeLLM(reply)

    control = await _gated_build(control_tree, control_llm, max_fix_attempts=2)

    assert control.success is True, control.error
    assert control_runner.await_count == 1 and control_llm.fix_prompts() == [], "premise: no repair was requested"
    assert fake_git.add_and_commit.await_count == 2, "premise: the control committed"
    control_message = fake_git.add_and_commit.await_args.args[1]
    assert "test-fix loop" not in control_message
    assert "fix_loop_files" not in control.metadata


async def test_approved_writes_keep_their_scope(build_tree: Path, fake_git: _FakeBuildGit) -> None:
    approved = [
        {"path": "tests/test_new.py", "mode": "create", "content": "def test_new() -> None:\n    assert True\n"},
        {"path": _CONFTEST, "mode": "create", "content": "collect_ignore = []\n"},
        {"path": "pytest.ini", "mode": "create", "content": "[pytest]\n"},
        {"path": "src/probos/cognitive/code_reviewer.py", "mode": "create", "content": "x = 1\n"},
    ]
    paths = [change["path"] for change in approved]
    for path in paths:
        assert builder_write_refusal(path) is None, f"premise: the write boundary allows {path}"
        assert fix_loop_write_refusal(path) is not None, f"premise: the fix loop's rule would refuse {path}"

    result = await execute_approved_build(
        approved, BuildSpec(title="bf898", description="d"), str(build_tree), run_tests=False,
    )

    assert result.success is True, result.error
    committed = fake_git.add_and_commit.await_args.args[0]
    for path in paths:
        assert path in committed, f"{path} was approved and must be committed"
        assert (build_tree / path).is_file(), f"{path} was approved and must be written"
    assert "BF-898" not in result.error


def _parsed(reply: str) -> list[tuple[str, str]]:
    return [(block["mode"], block["path"]) for block in BuilderAgent._parse_file_blocks(reply)]


_DIR_MODIFY = (
    "===MODIFY: src/probos/subdir===\n"
    "===SEARCH===\na\n===REPLACE===\nb\n===END REPLACE===\n"
    "===END MODIFY===\n"
)


async def test_an_error_in_a_later_block_keeps_the_attempt_and_the_disclosure(
    build_tree: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch,
) -> None:
    foo = _seed(build_tree, _FOO, _FOO_TEXT)
    (build_tree / "src/probos/subdir").mkdir()
    runner = AsyncMock(return_value=(False, "1 failed", _MAPPED))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    reply = _FOO_TO_2 + _DIR_MODIFY
    llm = _FakeLLM(reply)
    assert _parsed(reply) == [("modify", _FOO), ("modify", "src/probos/subdir")], "premise: parse order"
    assert fix_loop_write_refusal(_FOO) is None and fix_loop_write_refusal("src/probos/subdir") is None, (
        "premise: the rule admits both paths, so the error is the executor's"
    )

    result = await _gated_build(build_tree, llm, max_fix_attempts=2)

    assert result.success is False
    assert result.error, "the directory block must raise and be reported"
    assert foo.read_text(encoding="utf-8") == "x = 2\n", "premise: the earlier block was applied before the error"
    assert result.fix_attempts == 1
    assert result.metadata["fix_loop_files"] == [_FOO]
    assert fake_git.add_and_commit.await_count == 0
    assert len(llm.fix_prompts()) == 1


async def test_an_error_raised_by_the_validation_after_a_write_keeps_the_disclosure(
    build_tree: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    foo = _seed(build_tree, _FOO, _FOO_TEXT)
    runner = AsyncMock(return_value=(False, "1 failed", _MAPPED))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    llm = _FakeLLM(_FOO_TO_2)
    real_validate = builder_module._validate_python
    repaired = _seed(tmp_path, "premise/repaired.py", "x = 2\n")
    assert not real_validate(repaired), "premise: the real validation accepts the repaired text"
    assert fix_loop_write_refusal(_FOO) is None, "premise: the rule admits the path, so the error is the validation's"
    calls: list[Path] = []

    def validate_then_raise(path: Path) -> str | None:
        calls.append(path)
        if len(calls) == 1:
            return real_validate(path)  # the approved write's validation
        raise RecursionError("maximum recursion depth exceeded during compilation")

    monkeypatch.setattr(builder_module, "_validate_python", validate_then_raise)

    result = await _gated_build(build_tree, llm, max_fix_attempts=2)

    assert len(calls) == 2, "premise: the second validation is the repair's, and it raised"
    assert result.success is False
    assert "recursion" in result.error.lower()
    assert result.fix_attempts == 1
    assert result.metadata["fix_loop_files"] == [_FOO]
    assert foo.read_text(encoding="utf-8") == "x = 2\n", "the write happened before the error"
    assert fake_git.add_and_commit.await_count == 0
    assert len(llm.fix_prompts()) == 1


async def test_a_write_that_fails_after_truncating_the_file_is_still_disclosed(
    build_tree: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch,
) -> None:
    foo = _seed(build_tree, _FOO, _FOO_TEXT)
    runner = AsyncMock(return_value=(False, "1 failed", _MAPPED))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    llm = _FakeLLM(_FOO_TO_2)
    assert fix_loop_write_refusal(_FOO) is None, "premise: the rule admits the path, so the error is the write's"
    real_write_text = Path.write_text
    foo_writes: list[str] = []

    def flaky(self: Path, data: str, *args: Any, **kwargs: Any) -> int:
        if self.name != "foo.py":
            return real_write_text(self, data, *args, **kwargs)
        foo_writes.append(data)
        if len(foo_writes) == 1:
            return real_write_text(self, data, *args, **kwargs)  # the approved write
        real_write_text(self, "", *args, **kwargs)  # open("w") truncates before the failure
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", flaky)

    result = await _gated_build(build_tree, llm, max_fix_attempts=2)

    assert len(foo_writes) == 2, "premise: the second write to foo.py is the repair's"
    assert foo.read_text(encoding="utf-8") == "", "the file was truncated by the failed write"
    assert result.metadata["fix_loop_files"] == [_FOO]
    assert result.fix_attempts == 1
    assert result.success is False
    assert "No space left" in result.error
    assert fake_git.add_and_commit.await_count == 0


_NO_OP_MODIFY = (
    f"===MODIFY: {_FOO}===\n"
    "===SEARCH===\nnot in the file\n===REPLACE===\nx = 9\n===END REPLACE===\n"
    "===END MODIFY===\n"
)
_IDENTICAL_CREATE = f"===FILE: {_FOO}===\n{_FOO_TEXT}===END FILE===\n"
_ABSENT = "src/probos/absent.py"
_MISSING_MODIFY = (
    f"===MODIFY: {_ABSENT}===\n"
    "===SEARCH===\nx = 1\n===REPLACE===\nx = 2\n===END REPLACE===\n"
    "===END MODIFY===\n"
)
# case -> (the leading block, the (mode, path) pairs the parser must return for the reply)
_UNCHANGED_BLOCKS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "no_op_modify": (_NO_OP_MODIFY, [("modify", _FOO), ("modify", "src/probos/subdir")]),
    "identical_create": (_IDENTICAL_CREATE, [("create", _FOO), ("modify", "src/probos/subdir")]),
    "missing_modify": (_MISSING_MODIFY, [("modify", _ABSENT), ("modify", "src/probos/subdir")]),
}


@pytest.mark.parametrize("case", list(_UNCHANGED_BLOCKS))
async def test_a_block_that_changes_nothing_is_not_disclosed_when_a_later_block_raises(
    case: str, build_tree: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch,
) -> None:
    foo = _seed(build_tree, _FOO, _FOO_TEXT)
    (build_tree / "src/probos/subdir").mkdir()
    runner = AsyncMock(return_value=(False, "1 failed", _MAPPED))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    leading, expected_parse = _UNCHANGED_BLOCKS[case]
    reply = leading + _DIR_MODIFY
    llm = _FakeLLM(reply)
    assert _parsed(reply) == expected_parse, f"premise: {case} parse order"
    for block in BuilderAgent._parse_file_blocks(reply):
        assert fix_loop_write_refusal(block["path"]) is None, "premise: the rule admits every path"
    if case == "missing_modify":
        assert not (build_tree / _ABSENT).exists(), "premise: the modified file does not exist"

    result = await _gated_build(build_tree, llm, max_fix_attempts=2)

    assert result.success is False
    assert result.error, "the directory block must raise and be reported"
    assert result.fix_attempts == 1
    assert "fix_loop_files" not in result.metadata
    assert foo.read_text(encoding="utf-8") == _FOO_TEXT
    assert fake_git.add_and_commit.await_count == 0


def test_fix_loop_changed_helper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    changed = builder_module._fix_loop_changed
    absent = tmp_path / "absent.py"
    existing = tmp_path / "existing.py"
    existing.write_bytes(b"x = 1\n")
    directory = tmp_path / "subdir"
    directory.mkdir()

    assert changed(absent, None) is False
    assert changed(existing, b"x = 1\n") is False
    assert changed(existing, b"x = 2\n") is True
    assert changed(directory, None) is False
    assert changed(existing, b"x = 1\n") is False, "premise: unpatched, the same call is False"

    def unreadable(self: Path) -> bytes:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_bytes", unreadable)

    assert changed(existing, b"x = 1\n") is True, "a file that cannot be read back is not shown unchanged"


async def test_an_error_in_the_first_block_still_counts_the_repair_request(
    build_tree: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch,
) -> None:
    foo = _seed(build_tree, _FOO, _FOO_TEXT)
    (build_tree / "src/probos/subdir").mkdir()
    runner = AsyncMock(return_value=(False, "1 failed", _MAPPED))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    llm = _FakeLLM(_DIR_MODIFY)
    assert _parsed(_DIR_MODIFY) == [("modify", "src/probos/subdir")], "premise: only the directory block"
    assert fix_loop_write_refusal("src/probos/subdir") is None, "premise: the rule admits it"

    result = await _gated_build(build_tree, llm, max_fix_attempts=2)

    assert result.success is False and result.error
    assert len(llm.fix_prompts()) == 1, "premise: the repair request was sent"
    assert result.fix_attempts == 1
    assert "fix_loop_files" not in result.metadata
    assert foo.read_text(encoding="utf-8") == _FOO_TEXT
    assert fake_git.add_and_commit.await_count == 0


async def test_a_line_break_in_a_path_is_refused_whole_and_never_reaches_the_commit_message(
    build_tree: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch,
) -> None:
    foo = _seed(build_tree, _FOO, _FOO_TEXT)
    runner = AsyncMock(return_value=(False, "1 failed", _MAPPED))
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    bad_path = "src/probos/a\nb.py"
    reply = _FOO_TO_2 + f"===FILE: {bad_path}===\nx = 1\n===END FILE===\n"
    llm = _FakeLLM(reply)
    assert ("create", bad_path) in _parsed(reply), "premise: the parser returns exactly that path"
    assert [path for _, path in _parsed(reply)].count(_FOO) == 1, "premise: the allowed block is in the reply"
    assert builder_write_refusal(bad_path) is None, "premise: the write boundary allows the path"
    assert fix_loop_write_refusal(bad_path) is not None, "premise: BF-898's rule refuses it"

    result = await _gated_build(build_tree, llm, max_fix_attempts=2)

    assert foo.read_text(encoding="utf-8") == _FOO_TEXT, "the allowed block is not written either"
    assert runner.await_count == 1
    assert fake_git.add_and_commit.await_count == 0
    assert "fix_loop_files" not in result.metadata
    assert result.success is False
    assert repr(bad_path) in result.error
    assert "a\nb" not in result.error


async def test_a_backslash_path_is_written_and_recorded_in_one_spelling(
    build_tree: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(build_tree, _FOO, _FOO_TEXT)
    runner = AsyncMock(side_effect=[(False, "1 failed", _MAPPED), (True, "1 passed", _MAPPED)])
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    reply = "===FILE: src\\probos\\widget.py===\nw = 1\n===END FILE===\n"
    llm = _FakeLLM(reply)
    parsed = _parsed(reply)
    assert len(parsed) == 1 and "\\" in parsed[0][1], f"premise: the parser keeps the backslashes: {parsed}"
    assert fix_loop_write_refusal(parsed[0][1]) is None, "premise: the rule admits the backslash spelling"

    result = await _gated_build(build_tree, llm, max_fix_attempts=2)

    assert result.success is True, result.error
    assert (build_tree / "src/probos/widget.py").read_text(encoding="utf-8") == "w = 1\n"
    assert result.files_written == ["src/probos/widget.py"]
    assert result.metadata["fix_loop_files"] == ["src/probos/widget.py"]
    assert fake_git.add_and_commit.await_count == 1
    committed, message = fake_git.add_and_commit.await_args.args[:2]
    assert "src/probos/widget.py" in committed
    assert all("\\" not in path for path in committed), committed
    assert "\\" not in message, message


async def test_the_disclosure_is_one_paragraph_of_a_four_paragraph_commit_message(
    build_tree: Path, fake_git: _FakeBuildGit, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(build_tree, _FOO, _FOO_TEXT)
    runner = AsyncMock(side_effect=[(False, "1 failed", _MAPPED), (True, "1 passed", _MAPPED)])
    monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)
    reply = _FOO_TO_2 + f"===FILE: {_HELPER}===\ny = 1\n===END FILE===\n"
    llm = _FakeLLM(reply)
    assert sorted(_parsed(reply)) == [("create", _HELPER), ("modify", _FOO)], "premise: a plain two-file repair"

    result = await _gated_build(build_tree, llm, max_fix_attempts=2)

    assert result.success is True, result.error
    assert result.metadata["fix_loop_files"] == [_FOO, _HELPER], "premise: both files are disclosed"
    message = fake_git.add_and_commit.await_args.args[1]
    prefix = "Changed by the unreviewed test-fix loop (BF-898):"
    assert [line for line in message.split("\n") if line.startswith(prefix)] == [f"{prefix} {_FOO}, {_HELPER}"]
    assert len(message.split("\n\n")) == 4, message.split("\n\n")


def test_fix_prompt_states_the_source_only_rule() -> None:
    prompt = _build_fix_prompt("t", "1 failed", [{"path": _FOO, "mode": "modify"}], 1)

    assert "Test Fix Required" in prompt, "premise: this is the fix prompt"
    assert "only source files under src/probos/" in prompt
    assert "output no blocks" in prompt


# --- T-P: premise. Each weakening really passes the real targeted run (real pytest, no git) ---
#
# Without BF-898's rule each of the five weakenings would make the rerun pass and the build commit.
# This group proves that on the real targeted runner, so the replay below discriminates: it is the
# rule that stops them, not a repair that fails to make the test pass.


def _apply_by_hand(root: Path, reply: str) -> list[str]:
    """Apply a repair reply to *root* the way the fix loop would without the rule; return the paths it changed.

    A FILE block writes the file; a MODIFY block replaces its SEARCH text once, and the SEARCH text must be there.
    """
    blocks = BuilderAgent._parse_file_blocks(reply)
    assert blocks, "premise: the reply holds at least one block"
    for block in blocks:
        target = root / block["path"]
        if block["mode"] == "create":
            _seed(root, block["path"], block["content"])
            continue
        text = target.read_text(encoding="utf-8")
        for replacement in block["replacements"]:
            assert replacement["search"] in text, (
                f"premise: the SEARCH text {replacement['search']!r} is present in {block['path']}"
            )
            text = text.replace(replacement["search"], replacement["replace"], 1)
        _seed(root, block["path"], text)
    return [block["path"] for block in blocks]


@pytest.mark.timeout(150)
@pytest.mark.parametrize("case", [*_REPAIRS, "none"])
async def test_premise_each_weakening_passes_the_real_targeted_run(case: str, tmp_path: Path) -> None:
    plain = tmp_path / "p"
    _seed(plain, _WIDGET, _WIDGET_V1)
    _seed(plain, _WIDGET_TEST, _TEST_TEXT)
    changed = [] if case == "none" else _apply_by_hand(plain, _REPAIRS[case])
    assert bool(changed) == (case != "none"), "premise: every case but none changes a file"

    passed, output, test_files = await _run_targeted_tests(str(plain), [_WIDGET], timeout=120)

    assert test_files == [str(plain / "tests" / "test_widget.py")], (
        "premise: the real targeted run maps the widget change to the widget test"
    )
    if case == "none":
        assert passed is False, f"control: with no repair test_value must fail:\n{output}"
        assert "1 failed" in output, output
    else:
        assert passed is True, f"{case}: the rerun must pass, which is what makes the weakening dangerous:\n{output}"


# --- T-R: the deterministic replay (real git, the real executor, real pytest) ---
#
# The seam test of record: model reply, parse, refusal, the commit gate and the git outcome, in one
# test. The tree is the repository itself, cut from nothing but the seed commit on ``main``. After a
# failed build the executor runs ``git checkout main``, deletes its branch (``builder-bf898-replay``,
# which the test never creates) and unlinks every file in files_written, so a file the fix loop
# *created* is gone whether or not it was written. The tests below therefore discriminate with the
# number of targeted runs, with the existing test file's bytes and with the committed tree
# (``git show <sha>:<path>``), never with the presence of a created file alone.


class _TargetedSpy:
    """Wraps the real targeted runner: counts its calls, keeps the timeout each was given, then runs it."""

    def __init__(self, real: Any) -> None:
        self._real = real
        self.calls = 0
        self.timeouts: list[int] = []

    async def __call__(
        self, work_dir: str, changed_files: list[str], timeout: int = 60,
    ) -> tuple[bool, str, list[str]]:
        self.calls += 1
        self.timeouts.append(timeout)
        return await self._real(work_dir, changed_files, timeout=timeout)


@requires_git
@pytest.mark.timeout(150)
@pytest.mark.parametrize("case", list(_REPAIRS))
async def test_replay_a_grader_weakening_repair_is_refused_and_a_source_fix_commits(
    case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path / "repo", {_WIDGET_TEST: _TEST_TEXT})
    assert operator_checkout_refusal(repo, builder_module._PROJECT_ROOT) is None, (
        "premise: the entry guard allows the replay repository, so its refusal cannot stand in for BF-898's"
    )
    # A slow nested pytest under the parallel gate must not turn "failed" into "timed_out", which skips the fix loop.
    monkeypatch.setattr(builder_module, "TARGETED_TEST_TIMEOUT_S", 120)
    spy = _TargetedSpy(builder_module._run_targeted_tests)
    monkeypatch.setattr(builder_module, "_run_targeted_tests", spy)
    llm = _FakeLLM(_REPAIRS[case])
    approved = {"path": _WIDGET, "mode": "create", "content": _WIDGET_V1}

    result = await execute_approved_build(
        [approved],
        BuildSpec(title="bf898 replay", description=""),
        str(repo),
        run_tests=True,
        max_fix_attempts=2,
        llm_client=llm,
    )

    fix_prompts = llm.fix_prompts()
    assert len(fix_prompts) == 1, (
        f"premise: the first real run failed and one repair was requested, got {len(fix_prompts)}: {result.error}"
    )
    assert "1 failed" in fix_prompts[0] and "test_value" in fix_prompts[0], "premise: test_value is what failed"
    assert spy.timeouts == [120] * spy.calls, "premise: the patched test budget reached the runner"

    if case == "source_fix":
        # Control: a repair that changes source is applied, the rerun passes and the build commits.
        assert result.success is True, result.error
        assert result.commit_hash
        assert spy.calls == 2
        assert result.metadata["targeted_tests"] == "passed"
        assert _show(repo, result.commit_hash, _WIDGET) == "VALUE = 2\n"
        assert _show(repo, result.commit_hash, _WIDGET_TEST) == _TEST_TEXT
        assert result.metadata["fix_loop_files"] == [_WIDGET]
        message = _out(repo, "log", "-1", "--format=%B", result.commit_hash)
        assert f"Changed by the unreviewed test-fix loop (BF-898): {_WIDGET}" in message
        assert "BF-898" not in result.error
    else:
        # A weakening: refused whole, the build is not committed and the checkout is left as it was.
        refused_path = _REFUSED_PATH[case]
        assert result.success is False, f"{case}: not refused; the build committed {result.commit_hash}"
        assert result.commit_hash == ""
        assert "BF-898" in result.error and refused_path in result.error, result.error
        assert spy.calls == 1, "no rerun after the refusal"
        assert _out(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
        assert sorted(_out(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines()) == ["main"]
        assert _out(repo, "rev-list", "--all", "--count") == "1"
        assert (repo / _WIDGET_TEST).read_bytes() == _TEST_TEXT.encode("utf-8"), "the existing test was never touched"
        assert not (repo / "tests" / "conftest.py").exists()
        assert not (repo / "pytest.ini").exists()
        assert "fix_loop_files" not in result.metadata
