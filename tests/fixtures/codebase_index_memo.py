"""AD-1270f P1.3: build the real CodebaseIndex once per test worker process.

Every runtime boot builds a ``CodebaseIndex`` by AST-parsing every file under
``src/probos`` -- about 2 s, paid again for every runtime a test boots. The tree
under test does not change during a test session, so this memo builds it once
per worker, keeps a pristine snapshot of the built state, and hands every later
build of the same tree a deep copy. Deep, because the index fills caches lazily
at query time (``_caller_cache``), so instances must never share state.

A copy is served only when all of these hold; otherwise the build runs for real
and nothing is cached:

* the index is over the real package tree -- a test's ``tmp_path`` tree always
  builds for real;
* every input the build reads -- each ``*.py`` under the root and the project
  documents -- has the same content digest as when the snapshot was taken;
* nothing ``build()`` can consult has been replaced or changed: every attribute
  of ``CodebaseIndex`` (methods, helpers, constants) by identity; every global
  of its module by identity, with container globals such as ``_KEY_CLASSES``
  also compared by content; every direct dependency the module dereferences --
  each ``module.attribute`` its source uses (``ast.parse``, ``ast.unparse``,
  ...) -- by identity; and the concrete path class and its bases wholesale, keys
  included, because path instances resolve ``read_text``/``rglob`` through them
  and a new subclass attribute can shadow an inherited one. A test that patches
  any of these is therefore never answered from the memo, and cannot seed it.

Stated bound: standard-library internals below those direct dependencies (for
example ``io.open`` underneath ``Path.read_text``) are not tracked.
"""

from __future__ import annotations

import ast
import copy
import functools
import hashlib
import inspect
import types
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from probos.cognitive import codebase_index as _codebase_index
from probos.cognitive.codebase_index import CodebaseIndex

#: The tree a runtime boot indexes: ``startup/agent_fleet.py`` builds over the
#: directory that contains the ``probos`` package's modules.
REAL_SOURCE_ROOT = Path(_codebase_index.__file__).resolve().parent.parent

_MISSING = object()
_active: CodebaseIndexBuildMemo | None = None


def _digest(path: Path) -> bytes:
    return hashlib.blake2b(path.read_bytes(), digest_size=16).digest()


def build_inputs_fingerprint(source_root: Path) -> tuple[tuple[str, bytes], ...] | None:
    """(path, content digest) for every input ``build()`` reads, or None if unreadable."""
    try:
        entries = [
            (path.relative_to(source_root).as_posix(), _digest(path))
            for path in sorted(source_root.rglob("*.py"))
        ]
        project_root = source_root.parent.parent
        for relative in _codebase_index._PROJECT_DOCS:
            document = project_root / relative
            if document.is_file():
                entries.append((f"docs:{relative}", _digest(document)))
    except OSError:
        return None
    return tuple(entries)


def _container_content(value: Any) -> tuple[str, Any] | None:
    """A comparable rendering of a container global, so in-place edits show."""
    if isinstance(value, (set, frozenset)):
        return ("set", tuple(sorted(map(repr, value))))
    if isinstance(value, dict):
        return ("dict", tuple(sorted((repr(k), repr(v)) for k, v in value.items())))
    if isinstance(value, (list, tuple)):
        return ("sequence", repr(value))
    return None


def _direct_dependencies() -> list[tuple[Any, str]]:
    """(owner, attribute) pairs the index module reaches through its globals.

    Derived from the module's own source, so a dependency added later is covered:
    every ``name.attribute`` whose ``name`` is a module or class global. Methods
    called on path *instances* (``path.read_text``) are covered separately, by
    comparing the concrete path classes wholesale.
    """
    source = Path(_codebase_index.__file__).read_text(encoding="utf-8")
    module_globals = vars(_codebase_index)
    referenced: set[tuple[str, str]] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            owner = module_globals.get(node.value.id)
            if isinstance(owner, (types.ModuleType, type)) and owner is not CodebaseIndex:
                referenced.add((node.value.id, node.attr))
    return [(module_globals[name], attr) for name, attr in sorted(referenced)]


def _path_classes() -> list[type]:
    """The concrete path class and its bases: where ``path.read_text`` resolves."""
    return [klass for klass in type(Path()).__mro__ if klass is not object]


class _BuildEnvironment:
    """Everything ``CodebaseIndex.build()`` can consult, captured for comparison."""

    def __init__(self) -> None:
        self._class_attrs = self._class_now()
        self._module_attrs = self._module_now()
        self._contents = {
            name: content
            for name, value in self._module_attrs.items()
            if (content := _container_content(value)) is not None
        }
        self._dependencies = [
            (owner, attr, inspect.getattr_static(owner, attr, _MISSING))
            for owner, attr in _direct_dependencies()
        ]
        # Whole mappings, keys included: a new attribute on a subclass shadows
        # an inherited one (``WindowsPath.read_text`` over ``Path.read_text``).
        self._path_classes = [(klass, dict(vars(klass))) for klass in _path_classes()]

    @staticmethod
    def _class_now() -> dict[str, Any]:
        # ``build`` itself is what the memo replaces, so it is the one exclusion.
        return {name: value for name, value in vars(CodebaseIndex).items() if name != "build"}

    @staticmethod
    def _module_now() -> dict[str, Any]:
        return {name: value for name, value in vars(_codebase_index).items() if not name.startswith("__")}

    def unchanged(self) -> bool:
        current_class = self._class_now()
        if current_class.keys() != self._class_attrs.keys():
            return False
        if any(current_class[name] is not value for name, value in self._class_attrs.items()):
            return False
        current_module = self._module_now()
        if current_module.keys() != self._module_attrs.keys():
            return False
        if any(current_module[name] is not value for name, value in self._module_attrs.items()):
            return False
        if any(
            inspect.getattr_static(owner, attr, _MISSING) is not value
            for owner, attr, value in self._dependencies
        ):
            return False
        for klass, attributes in self._path_classes:
            current = vars(klass)
            if current.keys() != attributes.keys():
                return False
            if any(current[name] is not value for name, value in attributes.items()):
                return False
        return all(
            _container_content(current_module[name]) == content
            for name, content in self._contents.items()
        )


class CodebaseIndexBuildMemo:
    """Serve deep copies of one real build of ``source_root``; see the module docstring."""

    def __init__(
        self,
        real_build: Callable[[CodebaseIndex], None],
        source_root: Path = REAL_SOURCE_ROOT,
    ) -> None:
        self._real_build = real_build
        self._source_root = Path(source_root).resolve()
        self._environment = _BuildEnvironment()
        self._snapshot: dict[str, Any] | None = None
        self._fingerprint: tuple[tuple[str, bytes], ...] | None = None
        self.real_builds = 0
        self.copies_served = 0

    def build(self, index: CodebaseIndex) -> None:
        """Build ``index`` for real, or fill it with a deep copy of a cached build."""
        if not self._eligible(index):
            self._real_build(index)
            return
        fingerprint = build_inputs_fingerprint(self._source_root)
        if fingerprint is None:
            self._real_build(index)
            return
        if self._snapshot is not None and fingerprint == self._fingerprint:
            vars(index).update(copy.deepcopy(self._snapshot))
            self.copies_served += 1
            return
        self._real_build(index)
        self.real_builds += 1
        self._snapshot = copy.deepcopy(vars(index))
        self._fingerprint = fingerprint

    def _eligible(self, index: CodebaseIndex) -> bool:
        try:
            root = Path(vars(index).get("_source_root", _MISSING)).resolve()
        except (OSError, TypeError):
            return False
        return root == self._source_root and self._environment.unchanged()


def active_memo() -> CodebaseIndexBuildMemo | None:
    """The memo installed by :func:`install_codebase_index_memo`, if any."""
    return _active


@contextmanager
def install_codebase_index_memo(
    source_root: Path = REAL_SOURCE_ROOT,
) -> Iterator[CodebaseIndexBuildMemo]:
    """Route ``CodebaseIndex.build`` through a memo for the duration of the context."""
    global _active
    previous_build = CodebaseIndex.build
    previous_active = _active
    memo = CodebaseIndexBuildMemo(previous_build, source_root)

    @functools.wraps(previous_build)
    def build(self: CodebaseIndex) -> None:
        memo.build(self)

    CodebaseIndex.build = build  # type: ignore[method-assign]
    _active = memo
    try:
        yield memo
    finally:
        CodebaseIndex.build = previous_build  # type: ignore[method-assign]
        _active = previous_active
