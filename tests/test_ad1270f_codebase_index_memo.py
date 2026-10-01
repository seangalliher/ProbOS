"""AD-1270f P1.3: the per-process CodebaseIndex build memo used by the test suite.

The memo answers every runtime boot after the first in a worker with a deep copy
of one real build. These tests pin when it may do that -- and, as importantly,
when it must not: another tree, changed input content, or anything the build
consults having been patched or edited.
"""

from __future__ import annotations

import ast
import functools
import inspect
import os
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive import codebase_index as codebase_index_module
from probos.cognitive.codebase_index import CodebaseIndex
from tests.fixtures.codebase_index_memo import (
    REAL_SOURCE_ROOT,
    CodebaseIndexBuildMemo,
    active_memo,
    build_inputs_fingerprint,
    install_codebase_index_memo,
)

_REAL_BUILD = inspect.unwrap(CodebaseIndex.build)
#: Every attribute ``build()`` could consult on the class, computed from the
#: class itself so a helper added later is covered without editing this file.
_CLASS_ATTRIBUTES = sorted(
    name for name in vars(CodebaseIndex) if not name.startswith("__") and name != "build"
)


def _tree(root: Path) -> Path:
    source_root = root / "src" / "probos"
    (source_root / "cognitive").mkdir(parents=True)
    (source_root / "runtime.py").write_text(
        '"""Runtime."""\n\nclass ProbOSRuntime:\n    def start(self) -> None:\n        pass\n',
        encoding="utf-8",
    )
    (source_root / "cognitive" / "agent.py").write_text(
        '"""Agent."""\n\nfrom probos.runtime import ProbOSRuntime\n\nclass Alpha:\n    pass\n',
        encoding="utf-8",
    )
    return source_root


def _seeded(source_root: Path) -> CodebaseIndexBuildMemo:
    memo = CodebaseIndexBuildMemo(_REAL_BUILD, source_root)
    memo.build(CodebaseIndex(source_root))
    assert (memo.real_builds, memo.copies_served) == (1, 0)
    return memo


def test_a_second_build_of_an_unchanged_tree_is_an_independent_copy(tmp_path: Path) -> None:
    source_root = _tree(tmp_path)
    memo = CodebaseIndexBuildMemo(_REAL_BUILD, source_root)
    first, second = CodebaseIndex(source_root), CodebaseIndex(source_root)

    memo.build(first)
    memo.build(second)

    assert (memo.real_builds, memo.copies_served) == (1, 1)
    assert second._built is True
    assert second._file_tree == first._file_tree
    assert second._import_graph == first._import_graph
    assert second._file_tree is not first._file_tree
    second._caller_cache["start"] = [{"file": "x"}]
    second._file_tree["runtime.py"]["classes"].append("Leaked")
    assert "start" not in first._caller_cache
    assert "Leaked" not in first._file_tree["runtime.py"]["classes"]
    third = CodebaseIndex(source_root)
    memo.build(third)
    assert "Leaked" not in third._file_tree["runtime.py"]["classes"], "the snapshot stays pristine"


def test_a_same_size_edit_with_restored_mtime_rebuilds_for_real(tmp_path: Path) -> None:
    """Content, not metadata, decides: the edit keeps the size and the mtime."""
    source_root = _tree(tmp_path)
    memo = _seeded(source_root)
    agent = source_root / "cognitive" / "agent.py"
    stat = agent.stat()
    agent.write_text(agent.read_text(encoding="utf-8").replace("Alpha", "Bravo"), encoding="utf-8")
    os.utime(agent, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert (agent.stat().st_size, agent.stat().st_mtime_ns) == (stat.st_size, stat.st_mtime_ns)

    rebuilt = CodebaseIndex(source_root)
    memo.build(rebuilt)

    assert (memo.real_builds, memo.copies_served) == (2, 0)
    assert rebuilt._file_tree["cognitive/agent.py"]["classes"] == ["Bravo"]


def test_another_tree_is_never_served_from_the_memo(tmp_path: Path) -> None:
    memo = CodebaseIndexBuildMemo(_REAL_BUILD, _tree(tmp_path / "memoised"))
    other_root = _tree(tmp_path / "other")
    other = CodebaseIndex(other_root)

    memo.build(other)
    memo.build(CodebaseIndex(other_root))

    assert (memo.real_builds, memo.copies_served) == (0, 0)
    assert other._built is True and "runtime.py" in other._file_tree


@pytest.mark.parametrize("name", _CLASS_ATTRIBUTES)
def test_any_patched_class_attribute_bypasses_the_memo(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = _tree(tmp_path)
    memo = _seeded(source_root)
    original = inspect.getattr_static(CodebaseIndex, name)
    assert inspect.isfunction(original), f"{name} is not a plain function; extend this test"

    @functools.wraps(original)
    def delegating(*args: Any, **kwargs: Any) -> Any:
        return original(*args, **kwargs)

    monkeypatch.setattr(CodebaseIndex, name, delegating)
    patched = CodebaseIndex(source_root)
    memo.build(patched)

    assert memo.copies_served == 0, f"a patched {name} was answered from the memo"
    assert patched._built is True and "runtime.py" in patched._file_tree


@pytest.mark.parametrize(
    ("owner", "attribute"),
    [(ast, "parse"), (ast, "iter_child_nodes"), (Path, "read_text"), (Path, "rglob")],
    ids=["ast.parse", "ast.iter_child_nodes", "Path.read_text", "Path.rglob"],
)
def test_a_patched_direct_dependency_bypasses_the_memo(
    owner: Any, attribute: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patching an attribute *of* a module or class the index binds leaves the
    binding's identity unchanged, so the dependencies themselves are checked."""
    source_root = _tree(tmp_path)
    memo = _seeded(source_root)
    original = getattr(owner, attribute)
    calls: list[str] = []

    @functools.wraps(original)
    def delegating(*args: Any, **kwargs: Any) -> Any:
        calls.append(attribute)
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, attribute, delegating)
    patched = CodebaseIndex(source_root)
    memo.build(patched)

    assert memo.copies_served == 0, f"a patched {attribute} was answered from the memo"
    assert calls, f"the real build never reached the patched {attribute}"
    assert patched._built is True and "runtime.py" in patched._file_tree


def test_the_derived_dependencies_include_what_build_calls() -> None:
    """Premise for the test above: the source-derived list is not empty or stale."""
    from tests.fixtures.codebase_index_memo import _direct_dependencies

    pairs = {(getattr(owner, "__name__", repr(owner)), attr) for owner, attr in _direct_dependencies()}

    assert {("ast", "parse"), ("ast", "iter_child_nodes"), ("ast", "unparse")} <= pairs


def test_a_shadowing_attribute_on_the_concrete_path_class_bypasses_the_memo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``WindowsPath``/``PosixPath`` inherit ``read_text``; a new attribute on the
    concrete class shadows it without changing any existing binding."""
    source_root = _tree(tmp_path)
    memo = _seeded(source_root)
    concrete = type(Path())
    assert "read_text" not in vars(concrete), "premise: read_text is inherited here"
    inherited = Path.read_text
    calls: list[str] = []

    @functools.wraps(inherited)
    def shadow(self: Path, *args: Any, **kwargs: Any) -> str:
        calls.append(self.name)
        return inherited(self, *args, **kwargs)

    monkeypatch.setattr(concrete, "read_text", shadow)
    patched = CodebaseIndex(source_root)
    memo.build(patched)

    assert memo.copies_served == 0, "a shadowing read_text was answered from the memo"
    assert calls, "the real build never reached the shadowing read_text"
    assert patched._built is True and "runtime.py" in patched._file_tree

def test_a_replaced_module_global_bypasses_the_memo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = _tree(tmp_path)
    memo = _seeded(source_root)
    monkeypatch.setattr(
        codebase_index_module, "_KEY_CLASSES", set(codebase_index_module._KEY_CLASSES) - {"ProbOSRuntime"}
    )

    patched = CodebaseIndex(source_root)
    memo.build(patched)

    assert memo.copies_served == 0
    assert patched.get_api_surface("ProbOSRuntime") == []


def test_an_in_place_edit_of_a_module_global_bypasses_the_memo(tmp_path: Path) -> None:
    source_root = _tree(tmp_path)
    memo = _seeded(source_root)
    key_classes = codebase_index_module._KEY_CLASSES
    key_classes.add("Alpha")
    try:
        edited = CodebaseIndex(source_root)
        memo.build(edited)
    finally:
        key_classes.discard("Alpha")

    assert memo.copies_served == 0
    assert "Alpha" in edited.get_full_api_surface()


def test_an_unreadable_input_builds_for_real_without_caching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = _tree(tmp_path)
    memo = CodebaseIndexBuildMemo(_REAL_BUILD, source_root)
    monkeypatch.setattr(
        "tests.fixtures.codebase_index_memo.build_inputs_fingerprint", lambda root: None
    )
    first, second = CodebaseIndex(source_root), CodebaseIndex(source_root)

    memo.build(first)
    memo.build(second)

    assert (memo.real_builds, memo.copies_served) == (0, 0), "nothing is cached"
    for index in (first, second):
        assert index._built is True and "cognitive/agent.py" in index._file_tree


def test_the_fingerprint_covers_sources_and_project_documents(tmp_path: Path) -> None:
    source_root = _tree(tmp_path)
    before = build_inputs_fingerprint(source_root)
    (tmp_path / "PROGRESS.md").write_text("# Progress\n", encoding="utf-8")

    after = build_inputs_fingerprint(source_root)

    assert before is not None and after is not None
    assert {entry[0] for entry in before} == {"cognitive/agent.py", "runtime.py"}
    assert "docs:PROGRESS.md" in {entry[0] for entry in after}


def test_install_routes_build_through_the_memo_and_restores_it(tmp_path: Path) -> None:
    source_root = _tree(tmp_path)
    before = CodebaseIndex.build
    outer = active_memo()

    with install_codebase_index_memo(source_root) as memo:
        assert active_memo() is memo
        CodebaseIndex(source_root).build()
        CodebaseIndex(source_root).build()
        assert (memo.real_builds, memo.copies_served) == (1, 1)

    assert CodebaseIndex.build is before
    assert active_memo() is outer


def test_the_session_memo_is_installed_for_the_real_tree() -> None:
    """Premise for the time saving: conftest installs the memo for this worker."""
    memo = active_memo()

    assert memo is not None, "tests/conftest.py did not install the memo"
    assert inspect.unwrap(CodebaseIndex.build) is not CodebaseIndex.build
    assert REAL_SOURCE_ROOT.name == "probos" and (REAL_SOURCE_ROOT / "runtime.py").is_file()
