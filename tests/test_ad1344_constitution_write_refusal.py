"""AD-1344 (#1596) S1: agents cannot amend the Federation Constitution.

``builder_paths.constitution_write_refusal`` is the rule. These tests drive it directly (the form
table), then through each writer that calls it: the native build and the test-fix loop
(``execute_approved_build``), the visiting session's permission handler, the SWE-harness
``write_file`` and ``edit_file``, ``FileWriterAgent`` (the proposal, the write, and a bundled
agent's note) and the office document writers. Each refusal is paired with a neighbour the same
writer still writes. Writer tests use paths inside a temporary vessel tree only, so a mutant that
removes a check writes there; forms outside the tree are judged by the rule alone, and the UNC
form only by the lexical checks. An autouse guard snapshots the repository's own constitution
(bytes and mode) and compares it after each test. Two AST censuses over tracked files pin the
inventory: which functions call the rule, and the file-write calls in the agent-facing modules
with a classification for each.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.agents.file_writer import FileWriterAgent
from probos.agents.utility.organizer_agents import _mesh_write_file
from probos.cognitive import builder as builder_module
from probos.cognitive import builder_paths, standing_orders
from probos.cognitive.builder import BuildSpec, execute_approved_build
from probos.cognitive.builder_paths import (
    builder_write_refusal,
    constitution_write_refusal,
    fix_loop_write_refusal,
)
from probos.cognitive.copilot_adapter import build_session_permission_handler
from probos.cognitive.standing_orders import (
    CONSTITUTION_FILENAME,
    CONSTITUTION_RELATIVE_PATH,
    constitution_path,
    standing_orders_dir,
)
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tools import EditFileTool, WriteFileTool
from probos.skill_framework import DocxAgent, PptxAgent, XlsxAgent
from probos.types import IntentMessage

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REAL_CONSTITUTION = _REPO_ROOT / "config" / "standing_orders" / "federation.md"
_AD = "AD-1344"
_ORIGINAL = "# Federation Constitution\nCONSTITUTION v1\n"
_SHIP = "# Ship Standing Orders\nSHIP v1\n"
_POINTER = "gitdir: ../elsewhere/.git/worktrees/wt\n"


# ── Fixtures and helpers ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _real_constitution_untouched():
    """The repository's own constitution is unchanged by each test (a snapshot, not a frozen hash).

    The file is named by a literal path, not through ``constitution_path()``: a break in that function
    must fail the ownership test (T1), not make every test in this file error in its setup.
    """
    before = (_REAL_CONSTITUTION.read_bytes(), os.stat(_REAL_CONSTITUTION).st_mode)
    yield
    after = (_REAL_CONSTITUTION.read_bytes(), os.stat(_REAL_CONSTITUTION).st_mode)
    assert after == before, "the repository's constitution changed"


@pytest.fixture
def vessel(tmp_path: Path) -> Path:
    root = tmp_path / "vessel"
    orders = root / "config" / "standing_orders"
    orders.mkdir(parents=True)
    (orders / CONSTITUTION_FILENAME).write_text(_ORIGINAL, encoding="utf-8")
    (orders / "ship.md").write_text(_SHIP, encoding="utf-8")
    (root / "config" / "other.yaml").write_text("other: 1\n", encoding="utf-8")
    (root / "docs").mkdir()
    return root


@pytest.fixture
def swe_root(vessel: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(swe_tools, "_PROJECT_ROOT", vessel)
    return vessel


def _constitution(root: Path) -> Path:
    return root.joinpath(*CONSTITUTION_RELATIVE_PATH.split("/"))


def _unchanged(root: Path) -> bool:
    return _constitution(root).read_text(encoding="utf-8") == _ORIGINAL


def _hard_link(root: Path, name: str) -> Path:
    alias = root / "docs" / name
    try:
        os.link(_constitution(root), alias)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"hard links are unavailable here: {exc}")
    assert os.path.samefile(alias, _constitution(root)), "premise: the link is the constitution"
    return alias


def _dir_link(link: Path, target: Path) -> None:
    """A directory link: a junction on Windows (no privilege needed), a symlink elsewhere."""
    try:
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip(f"directory links are unavailable here: {exc}")


def _kind_of(result: object) -> object:
    return result["kind"] if isinstance(result, dict) else result.kind  # type: ignore[union-attr]


# ── The forms ─────────────────────────────────────────────────────────────

# Relative to a writer's root: safe to drive through a real writer rooted in the vessel.
_IN_TREE = {
    "exact": "config/standing_orders/federation.md",
    "case": "CONFIG/Standing_Orders/FEDERATION.MD",
    "backslashes": "config\\standing_orders\\federation.md",
    "dot-prefix": "./config/standing_orders/federation.md",
    "dot-component": "config/./standing_orders/federation.md",
    "empty-component": "config//standing_orders/federation.md",
    "dots-only-component": "config/standing_orders/.../federation.md",
    "dot-dot": "config/standing_orders/notes/../federation.md",
    "trailing-dot": "config/standing_orders/federation.md.",
    "trailing-space": "config/standing_orders/federation.md ",
    "default-stream": "config/standing_orders/federation.md::$DATA",
    "named-stream": "config/standing_orders/federation.md:hidden",
    "short-name-file": "config/standing_orders/FEDERA~1.MD",
    "short-name-directory": "config/STANDI~1/federation.md",
    "hfs-ignorable": "config/standing_orders/fede\u200cration.md",
}
# Outside any test tree: judged by the rule alone, never through a writer.
_OUT_OF_TREE = {
    "windows-absolute": "C:/Users/x/ProbOS/config/standing_orders/federation.md",
    "posix-absolute": "/home/x/ProbOS/config/standing_orders/federation.md",
    "extended-length": "\\\\?\\C:\\ProbOS\\config\\standing_orders\\federation.md",
    "another-worktree": "D:/ProbOS-worktrees/wt/config/standing_orders/federation.md",
    "drive-relative": "C:config/standing_orders/federation.md",
}
# A network form: judged only where nothing is resolved (no host is contacted).
_LEXICAL_ONLY = {"unc": "\\\\server\\share\\ProbOS\\config\\standing_orders\\federation.md"}
_REFUSED = {**_IN_TREE, **_OUT_OF_TREE}
_LEXICAL = {**_REFUSED, **_LEXICAL_ONLY}
_NEIGHBOURS = [
    "config/standing_orders/ship.md",
    "config/standing_orders/engineering.md",
    "config/standing_orders/federation.md.bak",
    "config/standing_orders/federation_notes.md",
    "config/standing_orders/notes/federation.md",
    "config/federation.md",
    "config/standing_orders",
    "config",
    "config/system.yaml",
    "src/probos/federation.md",
]


# ── 1. Ownership ──────────────────────────────────────────────────────────


def test_the_standing_orders_module_owns_the_constitution_path() -> None:
    """T1: the literal location, which the fix loop cannot edit (it cannot write tests/)."""
    assert CONSTITUTION_RELATIVE_PATH == "config/standing_orders/federation.md"
    assert CONSTITUTION_FILENAME == "federation.md"
    assert constitution_path() == standing_orders_dir() / "federation.md"
    root = Path(standing_orders.__file__).resolve().parents[3]
    assert constitution_path() == root / "config" / "standing_orders" / "federation.md"
    assert constitution_path().is_file(), "premise: this checkout carries its constitution"


def test_the_composer_reads_the_constitution_through_the_constant(vessel: Path) -> None:
    """T2: the personnel-record tiers and the composed instructions both read the file."""
    orders = vessel / "config" / "standing_orders"
    tiers = standing_orders.get_order_tiers("builder", orders_dir=orders)
    assert tiers[0] == {
        "tier": "federation", "source_file": CONSTITUTION_FILENAME, "present": True, "text": _ORIGINAL.strip(),
    }
    composed = standing_orders.compose_instructions("builder", "", orders_dir=orders)
    assert "CONSTITUTION v1" in composed


# ── 2. The form table ─────────────────────────────────────────────────────


@pytest.mark.parametrize("path", list(_REFUSED.values()), ids=list(_REFUSED))
def test_the_rule_refuses_every_form_of_the_constitution(path: str) -> None:
    """T3."""
    refusal = constitution_write_refusal(path)
    assert refusal is not None and _AD in refusal
    assert "\n" not in refusal and repr(path) in refusal


@pytest.mark.parametrize("path", _NEIGHBOURS)
def test_the_rule_allows_the_neighbours(path: str) -> None:
    """T4."""
    assert constitution_write_refusal(path) is None


@pytest.mark.parametrize("path", list(_LEXICAL.values()), ids=list(_LEXICAL))
def test_the_builder_boundary_refuses_every_form_with_this_ads_reason(path: str) -> None:
    """T5: lexical only (no work_dir), so the AD-1344 reason can come only from the early check."""
    refusal = builder_write_refusal(path)
    assert refusal is not None and _AD in refusal


@pytest.mark.parametrize("path", _NEIGHBOURS)
def test_the_builder_boundary_allows_the_neighbours(path: str) -> None:
    """T6."""
    assert builder_write_refusal(path) is None


@pytest.mark.parametrize("path", list(_LEXICAL.values()), ids=list(_LEXICAL))
def test_the_fix_loop_refuses_every_form_with_this_ads_reason(path: str) -> None:
    """T7."""
    refusal = fix_loop_write_refusal(path)
    assert refusal is not None and _AD in refusal


def test_a_value_that_is_not_an_exact_str_is_refused_and_the_rule_runs_none_of_its_code(vessel: Path) -> None:
    """T8: the rule runs none of the value's code; ``builder_write_refusal`` refuses it."""
    ran: list[str] = []

    class Spy(str):
        def replace(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            ran.append("replace")
            return str.replace(self, *args, **kwargs)

        def split(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            ran.append("split")
            return str.split(self, *args, **kwargs)

        def __fspath__(self) -> str:
            ran.append("__fspath__")
            return str.__str__(self)

        def __repr__(self) -> str:
            ran.append("__repr__")
            return str.__repr__(self)

    neighbour = Spy("config/standing_orders/ship.md")
    refusal = constitution_write_refusal(neighbour, vessel)
    assert refusal is not None and _AD in refusal and "exact str" in refusal
    assert ran == [], f"the rule ran code of the caller's value: {ran}"
    assert constitution_write_refusal(str.__str__(neighbour), vessel) is None  # control: the same text, exact str
    builder_refusal = builder_write_refusal(Spy(CONSTITUTION_RELATIVE_PATH))
    assert builder_refusal is not None and "exact str" in builder_refusal


# ── 3. Identity, links and failing closed ─────────────────────────────────


def test_a_hard_link_to_the_constitution_is_refused_under_the_writers_root(vessel: Path) -> None:
    """T9."""
    alias = _hard_link(vessel, "alias.md")
    assert builder_write_refusal("docs/alias.md") is None, "premise: no lexical rule names it"
    refusal = constitution_write_refusal("docs/alias.md", vessel)
    assert refusal is not None and _AD in refusal
    assert constitution_write_refusal(str(alias), vessel) is not None
    (vessel / "docs" / "other.md").write_text("x", encoding="utf-8")
    assert constitution_write_refusal("docs/other.md", vessel) is None  # an existing unrelated file
    assert constitution_write_refusal("docs/new.md", vessel) is None  # not on disk yet
    assert constitution_write_refusal("config/standing_orders/ship.md", vessel) is None


def test_a_hard_link_to_the_running_checkouts_constitution_is_refused_without_a_root(
    vessel: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T10."""
    alias = _hard_link(vessel, "alias.md")
    assert constitution_write_refusal(str(alias)) is None, "premise: the running checkout's constitution is another file"
    monkeypatch.setattr(standing_orders, "_DEFAULT_ORDERS_DIR", vessel / "config" / "standing_orders")
    assert constitution_path() == _constitution(vessel), "premise: the checkout is now the vessel"
    refusal = constitution_write_refusal(str(alias))
    assert refusal is not None and _AD in refusal


def test_a_missing_checkout_constitution_still_checks_the_writers_root(
    vessel: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T11."""
    alias = _hard_link(vessel, "alias.md")
    empty = tmp_path / "empty_orders"
    empty.mkdir()
    monkeypatch.setattr(standing_orders, "_DEFAULT_ORDERS_DIR", empty)
    assert not constitution_path().exists(), "premise: the checkout's constitution is missing"
    refusal = constitution_write_refusal(str(alias), vessel)
    assert refusal is not None and _AD in refusal


def test_a_directory_link_into_the_constitutions_directory_is_refused_when_the_file_is_missing(vessel: Path) -> None:
    """T12: identity has nothing to compare, so only the resolved name refuses."""
    _constitution(vessel).unlink()
    _dir_link(vessel / "docs" / "orders", vessel / "config" / "standing_orders")
    assert builder_write_refusal("docs/orders/federation.md") is None, "premise: the written name is not the constitution"
    refusal = constitution_write_refusal("docs/orders/federation.md", vessel)
    assert refusal is not None and _AD in refusal
    assert constitution_write_refusal("docs/orders/ship.md", vessel) is None


def test_a_constitution_that_cannot_be_examined_refuses_the_write(vessel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T13."""
    assert constitution_write_refusal("docs/new.md", vessel) is None, "premise: accepted before the patch"
    real_stat = os.stat

    def _stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path).name == CONSTITUTION_FILENAME:
            raise PermissionError(13, "denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(builder_paths.os, "stat", _stat)
    refusal = constitution_write_refusal("docs/new.md", vessel)
    monkeypatch.undo()
    assert refusal is not None and _AD in refusal and "(constitution: PermissionError)" in refusal


def test_a_target_that_cannot_be_examined_is_refused(vessel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T14."""
    (vessel / "docs" / "other.md").write_text("x", encoding="utf-8")
    assert constitution_write_refusal("docs/other.md", vessel) is None, "premise: accepted before the patch"
    real_stat = os.stat

    def _stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path).name == "other.md":
            raise PermissionError(13, "denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(builder_paths.os, "stat", _stat)
    refusal = constitution_write_refusal("docs/other.md", vessel)
    monkeypatch.undo()
    assert refusal is not None and "(target: PermissionError)" in refusal


def test_a_failure_under_another_metaclass_is_named_exception(vessel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T15: the reason reads no attribute of a class whose metaclass is not exactly ``type``."""
    ran: list[str] = []

    class Meta(type):
        @property
        def __name__(cls) -> str:  # type: ignore[override]
            ran.append("__name__")
            return "Spoofed"

    class Denied(PermissionError, metaclass=Meta):
        pass

    (vessel / "docs" / "other.md").write_text("x", encoding="utf-8")
    real_stat = os.stat

    def _stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path).name == "other.md":
            raise Denied(13, "denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(builder_paths.os, "stat", _stat)
    refusal = constitution_write_refusal("docs/other.md", vessel)
    monkeypatch.undo()
    assert refusal is not None and "(target: Exception)" in refusal
    assert ran == [], "the metaclass's __name__ ran"


def test_a_failure_whose_class_name_is_not_an_exact_identifier_is_named_exception(
    vessel: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T39 (A1, F4): a class name with a line break, or held as a ``str`` subclass, is reported as ``Exception``."""
    ran: list[str] = []

    class Name(str):
        def __format__(self, spec: str) -> str:
            ran.append("__format__")
            return str.__format__(self, spec)

    class TwoLines(PermissionError):
        pass

    class Formatted(PermissionError):
        pass

    TwoLines.__name__ = "Two\nLines"
    Formatted.__name__ = Name("Formatted")
    assert type(TwoLines) is type and type(Formatted.__name__) is Name, "premise: metaclass type, names as set"
    (vessel / "docs" / "other.md").write_text("x", encoding="utf-8")
    real_stat = os.stat
    for cls in (TwoLines, Formatted):

        def _stat(path, *args, _cls=cls, **kwargs):  # type: ignore[no-untyped-def]
            if Path(path).name == "other.md":
                raise _cls(13, "denied")
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(builder_paths.os, "stat", _stat)
        refusal = constitution_write_refusal("docs/other.md", vessel)
        monkeypatch.undo()
        assert refusal is not None and "(target: Exception)" in refusal and "\n" not in refusal, cls
    assert ran == [], "the class name's own code ran"


def test_a_path_that_cannot_be_resolved_is_refused(vessel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T16."""
    assert constitution_write_refusal("docs/probe.md", vessel) is None, "premise: accepted before the patch"
    real_resolve = Path.resolve

    def resolve(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.name == "probe.md":
            raise ValueError("unresolvable")
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    refusal = constitution_write_refusal("docs/probe.md", vessel)
    monkeypatch.undo()
    assert refusal is not None and _AD in refusal and "(resolved: ValueError)" in refusal


def test_a_refusal_changes_nothing_on_disk_and_a_direct_write_still_works(vessel: Path) -> None:
    """T17: no friction. The rule does not lock, chmod or mark the file; a direct write is untouched."""
    fed = _constitution(vessel)
    before = (fed.read_bytes(), os.stat(fed).st_mode)
    assert constitution_write_refusal(CONSTITUTION_RELATIVE_PATH, vessel) is not None
    assert (fed.read_bytes(), os.stat(fed).st_mode) == before
    fed.write_text("CONSTITUTION v2\n", encoding="utf-8")
    assert fed.read_text(encoding="utf-8") == "CONSTITUTION v2\n"


# ── 4. The builder's writers ──────────────────────────────────────────────


def _no_real_git(stack: ExitStack) -> AsyncMock:
    for name, value in (("_git_current_branch", "main"), ("_is_dirty_working_tree", False),
                        ("_git_create_branch", (True, "builder-ad1344")), ("_git_return_to", (True, "ok")),
                        ("_run_git", (0, "", ""))):
        stack.enter_context(patch.object(builder_module, name, AsyncMock(return_value=value)))
    commit = AsyncMock(return_value=(True, "abc123"))
    stack.enter_context(patch.object(builder_module, "_git_add_and_commit", commit))
    return commit


def _create(path: str, content: str) -> dict:
    return {"path": path, "content": content, "mode": "create", "after_line": None}


async def _build(vessel: Path, changes: list[dict]) -> tuple[object, AsyncMock]:
    (vessel / ".git").write_text(_POINTER, encoding="utf-8")
    with ExitStack() as stack:
        commit = _no_real_git(stack)
        result = await execute_approved_build(changes, BuildSpec(title="AD-1344 probe", description=""), str(vessel), run_tests=False)
    return result, commit


@pytest.mark.parametrize("form", ["exact", "case", "backslashes", "dot-prefix"])
async def test_the_native_build_refuses_the_constitution(vessel: Path, form: str) -> None:
    """T18."""
    result, commit = await _build(vessel, [_create(_IN_TREE[form], "AMENDED\n")])
    assert _unchanged(vessel)
    assert result.files_written == [] and _AD in result.error
    commit.assert_not_awaited()


async def test_the_native_build_refuses_a_hard_link_to_the_constitution(vessel: Path) -> None:
    """T19."""
    _hard_link(vessel, "alias.md")
    result, commit = await _build(vessel, [_create("docs/alias.md", "AMENDED\n")])
    assert _unchanged(vessel) and _AD in result.error
    commit.assert_not_awaited()


async def test_the_native_build_still_modifies_the_ship_tier(vessel: Path) -> None:
    """T20."""
    change = {"path": "config/standing_orders/ship.md", "mode": "modify",
              "replacements": [{"search": "SHIP v1", "replace": "SHIP v2"}]}
    result, commit = await _build(vessel, [change])
    assert not result.error, result.error
    assert (vessel / "config" / "standing_orders" / "ship.md").read_text(encoding="utf-8") == "# Ship Standing Orders\nSHIP v2\n"
    assert "config/standing_orders/ship.md" in commit.await_args.args[0]


async def test_the_fix_loop_refuses_a_repair_of_the_constitution(vessel: Path) -> None:
    """T21."""
    (vessel / ".git").write_text(_POINTER, encoding="utf-8")
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=MagicMock(content=f"===FILE: {CONSTITUTION_RELATIVE_PATH}===\nAMENDED\n===END FILE===\n"))
    with ExitStack() as stack:
        _no_real_git(stack)
        stack.enter_context(patch.object(builder_module, "_run_targeted_tests", AsyncMock(return_value=(False, "1 failed", []))))
        result = await execute_approved_build([_create("ok.py", "x = 1\n")], BuildSpec(title="AD-1344 repair", description=""),
                                              str(vessel), run_tests=True, max_fix_attempts=1, llm_client=llm)
    fix_calls = sum("Test Fix Required" in call.args[0].prompt for call in llm.complete.await_args_list)
    assert fix_calls == 1, "premise: the repair loop ran and received the block"
    assert _unchanged(vessel) and _AD in result.error


def test_the_visiting_session_refuses_a_write_to_the_constitution(tmp_path: Path) -> None:
    """T22."""
    session = tmp_path / "session"
    session.mkdir()
    handler = build_session_permission_handler(str(session), ("standing_orders_lookup",))

    def ask(name: str) -> object:
        return _kind_of(handler({"kind": "write", "fileName": name}, {}))

    assert ask("config/standing_orders/ship.md") == "approved"  # controls first
    assert ask(str(session / "config" / "other.yaml")) == "approved"
    assert ask(CONSTITUTION_RELATIVE_PATH) == "denied-by-rules"
    assert ask(str(session / "config" / "standing_orders" / "federation.md")) == "denied-by-rules"
    assert ask("config/standing_orders/FEDERATION.MD") == "denied-by-rules"


# ── 5. SWE harness ────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", list(_IN_TREE.values()), ids=list(_IN_TREE))
async def test_write_file_refuses_the_constitution(swe_root: Path, path: str) -> None:
    """T23."""
    result = await WriteFileTool(SimpleNamespace()).invoke({"path": path, "content": "AMENDED\n"})
    assert not result.success and _AD in (result.error or "")
    assert _unchanged(swe_root)


async def test_write_file_refuses_absolute_paths_and_still_writes_the_neighbours(swe_root: Path) -> None:
    """T24."""
    tool = WriteFileTool(SimpleNamespace())
    for path in (str(_constitution(swe_root)), f"{swe_root}/CONFIG/Standing_Orders/FEDERATION.MD"):
        result = await tool.invoke({"path": path, "content": "AMENDED\n"})
        assert not result.success and _AD in (result.error or ""), path
    assert _unchanged(swe_root)
    for rel, text in (("config/standing_orders/ship.md", "SHIP v2\n"), ("config/other.yaml", "other: 2\n"),
                      ("config/standing_orders/federation_notes.md", "notes\n")):
        result = await tool.invoke({"path": rel, "content": text})
        assert result.success, f"{rel}: {result.error}"
        assert (swe_root / rel).read_text(encoding="utf-8") == text


async def test_write_file_refuses_a_hard_link_and_a_directory_link(swe_root: Path) -> None:
    """T25."""
    _hard_link(swe_root, "alias.md")
    tool = WriteFileTool(SimpleNamespace())
    linked = await tool.invoke({"path": "docs/alias.md", "content": "AMENDED\n"})
    assert not linked.success and _AD in (linked.error or "")
    _dir_link(swe_root / "docs" / "orders", swe_root / "config" / "standing_orders")
    through = await tool.invoke({"path": "docs/orders/federation.md", "content": "AMENDED\n"})
    assert not through.success and _AD in (through.error or "")
    assert _unchanged(swe_root)


async def test_write_file_refuses_under_the_effect_broker_context(swe_root: Path) -> None:
    """T26: the refusal comes before the strict-native lock and the plain write alike."""
    context = {
        "_effect_dispatch_context": object(),
        "_strict_native_target": str(_constitution(swe_root)),
        "_strict_native_root": str(swe_root),
    }
    result = await WriteFileTool(SimpleNamespace()).invoke({"path": CONSTITUTION_RELATIVE_PATH, "content": "AMENDED\n"}, context)
    assert not result.success and _AD in (result.error or "")
    assert _unchanged(swe_root)


@pytest.mark.parametrize("path", list(_IN_TREE.values()), ids=list(_IN_TREE))
async def test_edit_file_refuses_the_constitution(swe_root: Path, path: str) -> None:
    """T27."""
    result = await EditFileTool(SimpleNamespace()).invoke({"path": path, "old_text": "CONSTITUTION v1", "new_text": "AMENDED"})
    assert not result.success and _AD in (result.error or "")
    assert _unchanged(swe_root)


async def test_edit_file_refuses_a_hard_link_and_still_edits_the_ship_tier(swe_root: Path) -> None:
    """T28."""
    tool = EditFileTool(SimpleNamespace())
    ship = await tool.invoke({"path": "config/standing_orders/ship.md", "old_text": "SHIP v1", "new_text": "SHIP v2"})
    assert ship.success and ship.output["replacements"] == 1, f"control: {ship.error}"
    _hard_link(swe_root, "alias.md")
    result = await tool.invoke({"path": "docs/alias.md", "old_text": "CONSTITUTION v1", "new_text": "AMENDED"})
    assert not result.success and _AD in (result.error or "")
    assert _unchanged(swe_root)


async def test_the_swe_tools_log_a_refusal_without_the_callers_path(
    swe_root: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """T37 (A1, F1): the refusal's log line carries the operation and a reason code, not the caller's path.

    Driven with the strict effect context (as ``test_strict_list_files_logging_omits_raw_arguments`` in
    ``tests/test_ad1316_real_effect_routes.py``) and without it; the returned error still names the path.
    """
    caplog.set_level("WARNING", logger=swe_tools.__name__)
    sentinel = f"SENTINEL_PRIVATE_DIR/{CONSTITUTION_RELATIVE_PATH}"
    for context in ({"_effect_dispatch_context": object()}, None):
        written = await WriteFileTool(SimpleNamespace()).invoke({"path": sentinel, "content": "AMENDED\n"}, context)
        edited = await EditFileTool(SimpleNamespace()).invoke(
            {"path": sentinel, "old_text": "CONSTITUTION v1", "new_text": "AMENDED"}, context,
        )
        for result in (written, edited):
            assert not result.success and _AD in (result.error or ""), context
            assert "SENTINEL_PRIVATE_DIR" in (result.error or ""), "the returned error keeps the path"
    assert "SENTINEL_PRIVATE_DIR" not in caplog.text
    assert "operation=write_file reason_code=constitution_refused" in caplog.text
    assert "operation=edit_file reason_code=constitution_refused" in caplog.text
    assert not (swe_root / "SENTINEL_PRIVATE_DIR").exists()


class _ShiftingPath:
    """A caller's path whose text is *first* at its first conversion and *then* afterwards (A1, F2)."""

    def __init__(self, first: str, then: str) -> None:
        self.conversions = 0
        self._first, self._then = first, then

    def __str__(self) -> str:
        self.conversions += 1
        return self._first if self.conversions == 1 else self._then


async def test_the_swe_tools_judge_the_text_they_write(swe_root: Path) -> None:
    """T38 (A1, F2): the tool converts the path once; the rule judges the text it then writes and returns."""
    ship = "config/standing_orders/ship.md"
    written = _ShiftingPath(ship, CONSTITUTION_RELATIVE_PATH)
    result = await WriteFileTool(SimpleNamespace()).invoke({"path": written, "content": "SHIP v2\n"})
    assert result.success, result.error
    assert written.conversions == 1
    assert result.output["path"] == ship
    assert (swe_root / ship).read_text(encoding="utf-8") == "SHIP v2\n"
    assert _unchanged(swe_root)
    edited = _ShiftingPath(ship, CONSTITUTION_RELATIVE_PATH)
    result = await EditFileTool(SimpleNamespace()).invoke({"path": edited, "old_text": "v", "new_text": "V"})
    assert result.success, result.error
    assert edited.conversions == 1
    assert result.output == {"replacements": 1, "path": ship}
    assert (swe_root / ship).read_text(encoding="utf-8") == "SHIP V2\n"
    assert _unchanged(swe_root)


# ── 6. FileWriterAgent ────────────────────────────────────────────────────


async def test_file_writer_refuses_the_proposal_and_the_commit(vessel: Path) -> None:
    """T29."""
    agent = FileWriterAgent(pool="filesystem")
    await agent.start()
    fed = str(_constitution(vessel))
    ship = str(vessel / "config" / "standing_orders" / "ship.md")
    proposal = await agent.handle_intent(IntentMessage(intent="write_file", params={"path": fed, "content": "AMENDED\n"}))
    assert proposal is not None and proposal.success is False and _AD in (proposal.error or "")
    control = await agent.handle_intent(IntentMessage(intent="write_file", params={"path": ship, "content": "SHIP v2\n"}))
    assert control is not None and control.success is True and control.result["requires_consensus"] is True
    committed = await FileWriterAgent.commit_write(fed, "AMENDED\n")
    assert committed["success"] is False and _AD in committed["error"]
    assert (await FileWriterAgent.commit_write(ship, "SHIP v2\n"))["success"] is True
    assert _unchanged(vessel)


async def test_file_writer_commit_refuses_a_hard_link_under_its_working_directory(
    vessel: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T30."""
    alias = _hard_link(vessel, "alias.md")
    assert constitution_write_refusal(str(alias), _REPO_ROOT) is None, "premise: only the vessel's constitution matches"
    monkeypatch.chdir(vessel)
    committed = await FileWriterAgent.commit_write(str(alias), "AMENDED\n")
    assert committed["success"] is False and _AD in committed["error"]
    assert _unchanged(vessel)


async def test_a_bundled_agents_note_cannot_reach_the_constitution(vessel: Path) -> None:
    """T31: the notes agent joins a model-chosen filename to its directory and calls commit_write."""
    notes_dir = vessel / "home" / "notes"
    notes_dir.mkdir(parents=True)
    assert not await _mesh_write_file(None, f"{notes_dir}/../../config/standing_orders/federation.md", "AMENDED\n")
    assert _unchanged(vessel)
    assert await _mesh_write_file(None, f"{notes_dir}/note.md", "a note\n")
    assert (notes_dir / "note.md").read_text(encoding="utf-8") == "a note\n"


# ── 7. Office document writers ────────────────────────────────────────────


async def test_office_create_refuses_the_constitution(vessel: Path) -> None:
    """T32."""
    docx = DocxAgent(pool="office")
    with pytest.raises(PermissionError, match=_AD):
        await docx.handle_intent(IntentMessage(intent="docx_create", params={
            "title": "Amendment", "content": ["x"], "output_path": str(_constitution(vessel))}))
    with pytest.raises(PermissionError, match=_AD):
        await PptxAgent(pool="office").handle_intent(IntentMessage(intent="pptx_create", params={
            "title": "Amendment", "slides": [{"title": "x", "bullets": ["y"]}], "output_path": str(_constitution(vessel))}))
    assert _unchanged(vessel)
    notes = vessel / "config" / "standing_orders" / "notes.docx"
    control = await docx.handle_intent(IntentMessage(intent="docx_create", params={
        "title": "Notes", "content": ["x"], "output_path": str(notes)}))
    assert control is not None and control.success is True and notes.is_file()


async def test_office_revise_and_update_refuse_a_link_to_the_constitution(
    vessel: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T33."""
    docx_alias = _hard_link(vessel, "constitution.docx")
    xlsx_alias = _hard_link(vessel, "constitution.xlsx")
    monkeypatch.chdir(vessel)
    with pytest.raises(PermissionError, match=_AD):
        await DocxAgent(pool="office").handle_intent(IntentMessage(intent="docx_revise", params={
            "file_path": str(docx_alias), "instructions": "amend"}))
    with pytest.raises(PermissionError, match=_AD):
        await XlsxAgent(pool="office").handle_intent(IntentMessage(intent="xlsx_update", params={
            "file_path": str(xlsx_alias), "sheet": "Sheet", "updates": {"A1": "amended"}}))
    assert _unchanged(vessel)
    notes = vessel / "config" / "standing_orders" / "notes.docx"
    await DocxAgent(pool="office").create_docx(title="Notes", content=["x"], output_path=str(notes))
    revised = await DocxAgent(pool="office").handle_intent(IntentMessage(intent="docx_revise", params={
        "file_path": str(notes), "instructions": "tidy"}))
    assert revised is not None and revised.success is True


# ── 8. The inventory (AST censuses over tracked files) ────────────────────

_GUARD = "constitution_write_refusal"
_LEXICAL_HELPERS = frozenset({"_names_constitution", "_constitution_lexical_refusal"})
_EXPECTED_CALLERS = {
    ("src/probos/cognitive/builder_paths.py", "builder_write_refusal"),
    ("src/probos/cognitive/swe_harness/tools.py", "WriteFileTool.invoke"),
    ("src/probos/cognitive/swe_harness/tools.py", "EditFileTool.invoke"),
    ("src/probos/agents/file_writer.py", "FileWriterAgent.act"),
    ("src/probos/agents/file_writer.py", "FileWriterAgent.commit_write"),
    ("src/probos/skill_framework.py", "DocxAgent.create_docx"),
    ("src/probos/skill_framework.py", "DocxAgent.revise_docx"),
    ("src/probos/skill_framework.py", "PptxAgent.create_pptx"),
    ("src/probos/skill_framework.py", "XlsxAgent.update_xlsx"),
}
_CENSUS_SCOPE = (
    "src/probos/agents", "src/probos/tools", "src/probos/cognitive/swe_harness",
    "src/probos/skill_framework.py", "src/probos/cognitive/builder.py", "src/probos/cognitive/copilot_adapter.py",
    "src/probos/cognitive/skill_forge.py", "src/probos/cognitive/skill_catalog.py",
)
_GUARDS = frozenset({"constitution_write_refusal", "builder_write_refusal", "fix_loop_write_refusal"})
_METHOD_WRITES = frozenset({"write_text", "write_bytes", "unlink", "rename", "touch", "rmdir", "symlink_to", "hardlink_to", "save"})
_OS_WRITES = frozenset({"remove", "unlink", "rename", "replace", "link", "symlink", "rmdir", "removedirs", "truncate"})
_MODULE_WRITES = {
    "os": _OS_WRITES,
    "_os": _OS_WRITES,
    "shutil": frozenset({"copy", "copy2", "copyfile", "copytree", "move", "rmtree"}),
}
_GUARDED = "guarded"
_RESTORE = "BF-904a restore: writes back bytes a build saved before its first write to an admitted path, and removes what that build created"
_VAULT = "the credential vault's own file (constructor-injected)"
_RECORDINGS = "expired recordings under the recordings directory"
_WRITE_SITES: dict[tuple[str, str, str], str] = {
    ("src/probos/agents/file_writer.py", "FileWriterAgent.commit_write", ".write_text"): _GUARDED,
    ("src/probos/agents/http_fetch.py", "HttpFetchAgent._record_to_profile", ".save"): "a domain-profile store record, not a file path",
    ("src/probos/agents/utility/avatar_agents.py", "AvatarRendererAgent.act", "os.replace"): "the avatar store; the target is <agent_id>.vrm, not a .md file",
    ("src/probos/cognitive/builder.py", "_restore_pre_build_files", ".rmdir"): _RESTORE,
    ("src/probos/cognitive/builder.py", "_restore_pre_build_files", ".unlink"): _RESTORE,
    ("src/probos/cognitive/builder.py", "_restore_pre_build_files", ".write_bytes"): _RESTORE,
    ("src/probos/cognitive/builder.py", "execute_approved_build", ".write_text"): _GUARDED,
    ("src/probos/cognitive/copilot_adapter.py", "seed_session_directory", ".write_text"): "the build's own session directory; its writes reach the tree through execute_approved_build",
    ("src/probos/cognitive/skill_catalog.py", "CognitiveSkillCatalog._rewrite_frontmatter", ".write_text"): "the SKILL.md of a cataloged skill directory",
    ("src/probos/cognitive/skill_catalog.py", "CognitiveSkillCatalog.import_skill", "shutil.copytree"): "copytree creates its destination and raises on an existing one, so it replaces no file",
    ("src/probos/cognitive/skill_catalog.py", "CognitiveSkillCatalog.remove_skill", "shutil.rmtree"): "a cataloged skill's directory; called from the Captain's skill command (commands_skill.py:293)",
    ("src/probos/cognitive/skill_forge.py", "SkillForge._write_files", ".write_text"): "under the forge's staging directory (resolved containment check, skill_forge.py:305-315)",
    ("src/probos/cognitive/skill_forge.py", "SkillForge.forge", "shutil.rmtree"): "the forge's own staging directory",
    ("src/probos/cognitive/swe_harness/tools.py", "EditFileTool.invoke", ".write_text"): _GUARDED,
    ("src/probos/cognitive/swe_harness/tools.py", "WriteFileTool.invoke", ".write_text"): _GUARDED,
    ("src/probos/skill_framework.py", "DocxAgent.create_docx", ".save"): _GUARDED,
    ("src/probos/skill_framework.py", "DocxAgent.revise_docx", ".save"): _GUARDED,
    ("src/probos/skill_framework.py", "PptxAgent.create_pptx", ".save"): _GUARDED,
    ("src/probos/skill_framework.py", "XlsxAgent.update_xlsx", ".save"): _GUARDED,
    ("src/probos/tools/browser/actions.py", "_action_upload_file", "_os.unlink"): "the temporary credential file this action materialized",
    ("src/probos/tools/browser/credentials.py", "EncryptedFileCredentialVault._save", "open"): _VAULT,
    ("src/probos/tools/browser/credentials.py", "EncryptedFileCredentialVault._save", "os.replace"): _VAULT,
    ("src/probos/tools/browser/credentials.py", "EncryptedFileCredentialVault.materialize_to_temp", "os.unlink"): "a temporary file this vault created",
    ("src/probos/tools/browser/recording_reaper.py", "RecordingReaper._reap_sync", ".rmdir"): _RECORDINGS,
    ("src/probos/tools/browser/recording_reaper.py", "RecordingReaper._reap_sync", ".unlink"): _RECORDINGS,
    ("src/probos/tools/code_execution_tool.py", "CodeExecutionTool._stage_thread_artifacts", ".write_bytes"): "thread attachments staged into the run's own temporary work directory",
    ("src/probos/tools/code_execution_tool.py", "CodeExecutionTool._start_fetch_broker", ".write_text"): "the sandbox helper in the run's own temporary work directory",
    ("src/probos/tools/code_execution_tool.py", "CodeExecutionTool.invoke", "shutil.rmtree"): "the run's own temporary work directory",
}
_CHANNEL_SUFFIXES = (".py", ".ps1", ".sh", ".yml", ".yaml", ".toml", ".cfg")


def _tracked(*specs: str) -> list[str]:
    if shutil.which("git") is None:
        pytest.skip("git is not installed; the census reads tracked files only")
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", *specs], cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return sorted(path for path in listing.split("\0") if path)


def _calls(source: str) -> list[tuple[str, ast.Call]]:
    """Every call, with the qualified name of the innermost function holding it ("<module>" at top level)."""
    found: list[tuple[str, ast.Call]] = []

    def visit(node: ast.AST, scope: str, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, scope, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                visit(child, name, f"{name}.")
            else:
                if isinstance(child, ast.Call):
                    found.append((scope, child))
                visit(child, scope, prefix)

    visit(ast.parse(source), "<module>", "")
    return found


def _callee(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def _opens_for_writing(mode: ast.AST | None) -> bool:
    if mode is None:
        return False
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return any(flag in mode.value for flag in "wax+")
    return True  # a mode the census cannot read is counted


def _write_primitive(call: ast.Call) -> str | None:
    func = call.func
    keyword_mode = next((kw.value for kw in call.keywords if kw.arg == "mode"), None)
    if isinstance(func, ast.Name) and func.id == "open":
        return "open" if _opens_for_writing(call.args[1] if len(call.args) > 1 else keyword_mode) else None
    if not isinstance(func, ast.Attribute):
        return None
    owner = func.value.id if isinstance(func.value, ast.Name) else None
    if owner in _MODULE_WRITES:
        return f"{owner}.{func.attr}" if func.attr in _MODULE_WRITES[owner] else None
    if func.attr in _METHOD_WRITES:
        return f".{func.attr}"
    if func.attr == "open":
        return ".open" if _opens_for_writing(call.args[0] if call.args else keyword_mode) else None
    return None


def _source(rel: str) -> str:
    return (_REPO_ROOT / rel).read_text(encoding="utf-8-sig")


def test_the_rule_is_called_by_the_inventoried_writers_and_its_helpers_stay_private() -> None:
    """T34 (census A)."""
    callers: set[tuple[str, str]] = set()
    helper_files: set[str] = set()
    for rel in _tracked("src/probos"):
        if not rel.endswith(".py"):
            continue
        for scope, call in _calls(_source(rel)):
            name = _callee(call)
            if name == _GUARD:
                callers.add((rel, scope))
            elif name in _LEXICAL_HELPERS:
                helper_files.add(rel)
    assert callers == _EXPECTED_CALLERS
    assert helper_files == {"src/probos/cognitive/builder_paths.py"}, "the lexical-only helpers are the boundary's own"


def test_every_write_in_the_agent_facing_modules_is_guarded_or_classified() -> None:
    """T35 (census B)."""
    found: set[tuple[str, str, str]] = set()
    guarded: set[tuple[str, str]] = set()
    for rel in _tracked(*_CENSUS_SCOPE):
        if not rel.endswith(".py"):
            continue
        for scope, call in _calls(_source(rel)):
            primitive = _write_primitive(call)
            if primitive is not None:
                found.add((rel, scope, primitive))
            if _callee(call) in _GUARDS:
                guarded.add((rel, scope))
    new = sorted(found - set(_WRITE_SITES))
    stale = sorted(set(_WRITE_SITES) - found)
    assert not new, (
        f"unclassified write sites: {new}. Call builder_paths.constitution_write_refusal before the "
        "write, or add a row naming why the path cannot be the constitution"
    )
    assert not stale, f"stale rows (the write moved or went): {stale}"
    unguarded = sorted(key for key, why in _WRITE_SITES.items() if why == _GUARDED and key[:2] not in guarded)
    assert not unguarded, f"rows marked guarded whose function calls no guard: {unguarded}"


def test_the_captains_channels_do_not_consult_the_rule() -> None:
    """T36: no tracked script, hook or workflow with a suffix in ``_CHANNEL_SUFFIXES`` names the rule or ``_names_constitution`` (acceptance 4: no friction)."""
    channels = [rel for rel in _tracked("scripts", ".github", ".githooks", ".pre-commit-config.yaml") if rel.endswith(_CHANNEL_SUFFIXES)]
    assert any(rel.startswith(".github/workflows/") for rel in channels), "premise: CI is tracked and scanned"
    for rel in channels:
        text = (_REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        assert _GUARD not in text and "_names_constitution" not in text, rel
