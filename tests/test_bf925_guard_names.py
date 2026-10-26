"""BF-925 (#1655): a production hasattr/getattr guard must name an attribute production code defines.

The defect class: a guard on a name nothing defines turns a missing API into a silent empty result
(#1655: the Insights report, @mention links, the procedural bridge, the Chiefs' stats).

A *guard* is ``hasattr(obj, "name")`` or ``getattr(obj, "name", default)`` (a string literal), inside
a function, whose receiver's root is ``self``, ``cls``, ``rt`` or ``runtime``, or a local name
assigned in an enclosing function from such an expression (to a fixed point). A name is *defined*
when production code under src/probos has it as a def or class name, a module- or class-level
assignment target (class attributes, dataclass and pydantic fields, enum members), any attribute
assignment target (``self.x = ...``), a ``__slots__`` string, a ``setattr`` literal, a module-level
import name, or an argparse ``dest`` or first long option. Dunder names are skipped. AST only:
nothing is imported, and this checkout's src is scanned.

It cannot see: a guard on a parameter or a local not derived from those roots; a name an unrelated
production class happens to define (F12's ``recent``; ``pending_proposals``); dynamic names;
``try/except AttributeError``; module-level guards; ``__getattr__``. Third-party attributes on owned
receivers are allow-listed as ``duck`` in tests/fixtures/guard_name_allowlist.txt.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src" / "probos"
_ALLOW_LIST = Path(__file__).resolve().parent / "fixtures" / "guard_name_allowlist.txt"
_OWNED = frozenset({"self", "cls", "rt", "runtime"})
_KINDS = frozenset({"duck", "finding"})


def _literal(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _add_call_definitions(call: ast.Call, names: set[str]) -> None:
    func = call.func
    called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
    if called == "setattr" and len(call.args) >= 2 and _literal(call.args[1]) is not None:
        names.add(_literal(call.args[1]))
    for keyword in call.keywords:
        if keyword.arg == "dest" and _literal(keyword.value) is not None:
            names.add(_literal(keyword.value))
    if called == "add_argument":
        options = [option for option in (_literal(arg) for arg in call.args) if option is not None]
        longs = [option for option in options if option.startswith("--")]
        chosen = longs[0] if longs else (options[0] if options else "")
        if chosen:
            names.add(chosen.lstrip("-").replace("-", "_"))


def _defined_names(trees: list[ast.AST]) -> set[str]:
    names: set[str] = set()

    def add_target(target: ast.AST, scoped: bool) -> None:
        if isinstance(target, ast.Attribute):
            names.add(target.attr)
        elif isinstance(target, ast.Name) and scoped:
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                add_target(element, scoped)
        elif isinstance(target, ast.Starred):
            add_target(target.value, scoped)

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(child.name)
                visit(child, "function")
                continue
            if isinstance(child, ast.ClassDef):
                names.add(child.name)
                visit(child, "class")
                continue
            if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    add_target(target, scope in ("module", "class"))
                    if isinstance(target, ast.Name) and target.id == "__slots__" and child.value is not None:
                        names.update(
                            item for item in (_literal(n) for n in ast.walk(child.value)) if item is not None
                        )
            if isinstance(child, (ast.Import, ast.ImportFrom)) and scope == "module":
                names.update((alias.asname or alias.name).split(".")[0] for alias in child.names)
            if isinstance(child, ast.Call):
                _add_call_definitions(child, names)
            visit(child, scope)

    for tree in trees:
        visit(tree, "module")
    return names


def _root(expr: ast.AST) -> str:
    while True:
        if isinstance(expr, (ast.Attribute, ast.Subscript)):
            expr = expr.value
        elif isinstance(expr, ast.Call):
            if isinstance(expr.func, ast.Name) and expr.func.id == "getattr" and expr.args:
                expr = expr.args[0]
            else:
                expr = expr.func
        else:
            return expr.id if isinstance(expr, ast.Name) else ""


def _value_root(value: ast.AST) -> str:
    if isinstance(value, ast.BoolOp) and value.values:
        return _value_root(value.values[0])
    if isinstance(value, ast.IfExp):
        return _value_root(value.body)
    if isinstance(value, ast.Await):
        return _value_root(value.value)
    return _root(value)


def _owned_names(function: ast.AST) -> set[str]:
    owned = set(_OWNED)
    assigns = [
        node for node in ast.walk(function)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
    ]
    changed = True
    while changed:
        changed = False
        for node in assigns:
            if _value_root(node.value) not in owned:
                continue
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(target, ast.Name) and target.id not in owned:
                    owned.add(target.id)
                    changed = True
    return owned


def _guarded_name(node: ast.AST) -> str | None:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
        return None
    arity = {"hasattr": 2, "getattr": 3}.get(node.func.id)
    if arity is None or len(node.args) != arity:
        return None
    return _literal(node.args[1])


def unresolved_guards(sources: dict[str, str]) -> set[tuple[str, str]]:
    """(path, name) of every owned guard whose non-dunder name no source defines."""
    trees = {path: ast.parse(text, filename=path) for path, text in sources.items()}
    defined = _defined_names(list(trees.values()))
    found: set[tuple[str, str]] = set()
    for path, tree in trees.items():
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            owned = _owned_names(function)
            for node in ast.walk(function):
                name = _guarded_name(node)
                if name is None or (name.startswith("__") and name.endswith("__")) or name in defined:
                    continue
                if _root(node.args[0]) in owned:
                    found.add((path, name))
    return found


def load_allow_list(path: Path) -> dict[tuple[str, str], tuple[str, str]]:
    entries: dict[tuple[str, str], tuple[str, str]] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = [part.strip() for part in line.split("|")]
        if len(fields) != 4 or not all(fields) or fields[2] not in _KINDS:
            raise ValueError(f"{path.name}:{number}: expected 'path | name | duck|finding | reason': {raw!r}")
        key = (fields[0], fields[1])
        if key in entries:
            raise ValueError(f"{path.name}:{number}: duplicate entry {key}")
        entries[key] = (fields[2], fields[3])
    return entries


def compare(hits: set[tuple[str, str]], allowed: set[tuple[str, str]]) -> tuple[list, list]:
    """(guards not allow-listed, allow-list entries that are no longer a hit)."""
    return sorted(hits - allowed), sorted(allowed - hits)


def _production_sources() -> dict[str, str]:
    return {path.relative_to(_REPO).as_posix(): path.read_text(encoding="utf-8") for path in sorted(_SRC.rglob("*.py"))}


def test_production_guards_name_attributes_production_code_defines() -> None:
    new, stale = compare(unresolved_guards(_production_sources()), set(load_allow_list(_ALLOW_LIST)))
    assert new == [], f"guards on names no production code defines (wire the real API, or allow-list with a reason): {new}"
    assert stale == [], f"allow-list entries whose name is now defined or no longer guarded in that file: {stale}"


def test_a_guard_on_an_undefined_name_is_reported() -> None:
    source = (
        "class A:\n"
        "    def run(self, rt):\n"
        "        store = self._store\n"
        "        return hasattr(store, 'list_all') or getattr(rt, 'agent_pool', None)\n"
    )
    assert unresolved_guards({"pkg/a.py": source}) == {("pkg/a.py", "list_all"), ("pkg/a.py", "agent_pool")}


_GUARD = "class A:\n    def run(self):\n        return hasattr(self, 'target')\n"


@pytest.mark.parametrize("definition", [
    "class B:\n    def target(self):\n        return 1\n",
    "class B:\n    target: int = 0\n",
    "import enum\nclass B(enum.Enum):\n    target = 1\n",
    "class B:\n    def __init__(self):\n        self.target = 1\n",
    "class B:\n    __slots__ = ('target',)\n",
    "def f(o):\n    setattr(o, 'target', 1)\n",
    "def f(parser):\n    parser.add_argument('--target')\n",
], ids=["def", "field", "enum-member", "self-assign", "slots", "setattr", "argparse"])
def test_a_name_defined_by_production_code_is_not_reported(definition: str) -> None:
    assert unresolved_guards({"pkg/a.py": _GUARD, "pkg/b.py": definition}) == set()


@pytest.mark.parametrize("source", [
    "def f(page):\n    return getattr(page, 'mouse', None)\n",
    "class A:\n    def f(self):\n        return hasattr(self, '__aiter__')\n",
    "class A:\n    def f(self):\n        return getattr(self, 'missing')\n",
], ids=["parameter-receiver", "dunder", "two-argument-getattr"])
def test_guards_this_scan_does_not_own_are_not_reported(source: str) -> None:
    assert unresolved_guards({"pkg/a.py": source}) == set()


def test_a_stale_allow_list_entry_is_reported(tmp_path: Path) -> None:
    allow_list = tmp_path / "allow.txt"
    allow_list.write_text(
        "pkg/a.py | list_all | finding | defined now\npkg/a.py | gone_name | duck | no longer guarded\n",
        encoding="utf-8",
    )
    guard = "class A:\n    def run(self):\n        return hasattr(self._store, 'list_all')\n"
    definition = "class Store:\n    def list_all(self):\n        return []\n"
    hits = unresolved_guards({"pkg/a.py": guard, "pkg/store.py": definition})
    new, stale = compare(hits, set(load_allow_list(allow_list)))
    assert (new, stale) == ([], [("pkg/a.py", "gone_name"), ("pkg/a.py", "list_all")])


def test_the_allow_list_has_one_reason_per_entry() -> None:
    entries = load_allow_list(_ALLOW_LIST)  # raises on a malformed line or a duplicate
    assert entries, "the allow-list is empty: delete it with this test's checks, or restore it"
    for (path, _name), (_kind, reason) in entries.items():
        assert (_REPO / path).is_file(), f"{path} does not exist"
        assert len(reason) >= 10, f"{path}: the reason is too short to review"
