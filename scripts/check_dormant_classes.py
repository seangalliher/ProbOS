"""AD-1270 (#1324): report production classes that nothing in production uses, against a reviewed baseline.

REPORT-ONLY: this check warns and never fails. Its exit status is 0 on every input -- a missing or
malformed baseline, a source file that does not parse, an unknown or incomplete argument --
because nothing may gate on it until the Captain decides to enforce it. It is a separate command:
``scripts/run_test_gate.py`` does not run it, and no test asserts what it finds in the real tree.

A class is dormant when it is defined at the top level of a module under ``src/probos`` and
nothing live uses it. A use is a value reference: a call, an attribute read (``Name.x`` or
``module.Name``), a base class, a decorator, the name passed as a value (a loop tuple, a factory
default, a registry argument) or a string constant whose last ``.`` or ``:`` segment is the name
(a lookup or import by name). These are not uses: an import, an annotation, an assignment target,
an ``__all__`` entry, the second argument of ``isinstance`` or ``issubclass``, an operand of
``is`` or ``is not``, and anything under ``if TYPE_CHECKING:``. A use from another module always
counts. A use inside the class's own module counts only from module-level code, from a top-level
definition with a registering decorator, or from a top-level definition that is itself live.

Names are matched, not resolved (the shape of vulture's dead-code scan and of BF-926's
``check_config_readers.py``), with one exception: an import alias. After ``from m import X as Y``
anywhere in a module, a function body included, a value use of ``Y`` in that module, or a base
written as ``Y``, also counts as ``X``. An alias that is only imported or only annotates is not a
use, and an alias belongs to the module that imports it. ``import m as n`` needs no rule: ``n.X``
reads ``X``. So it under-reports: two classes with one name are live together, a use from a
dormant module still counts, and a use of an alias counts for every name the module imports under
it. It over-reports a class that only a path it cannot see reaches: ``config/``, an entry point,
``getattr`` or an import with a computed name, or an alias imported under that alias from the
module that made it. Protocols, enums, exceptions, TypedDicts, NamedTuples and pydantic models are
schema rather than capability and are not reported; nor are private classes.

The baseline holds one row per dormant class and its disposition and nothing else: ``unreviewed``
until a reviewer sets wire, retire or staged (each with an owner issue or AD) or false-positive
(with a note). Holding nothing else keeps it from becoming a second capability registry
(``platform-maturity-program.md``, AD-1270a).

Usage::

    python -P scripts/check_dormant_classes.py [--check | --update-baseline] [--src PATH] [--baseline PATH]
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent

PREFIX = "DORMANT CLASSES (report-only): "
DEFAULT_SOURCE = _REPO_ROOT / "src" / "probos"
DEFAULT_BASELINE = _REPO_ROOT / "docs" / "development" / "dormant-class-baseline.yaml"
DISPOSITIONS = ("wire", "retire", "staged", "false-positive")
UNREVIEWED = "unreviewed"
OWNER = re.compile(r"#\d+|\b(?:AD|BF)-\d+")
SCHEMA_BASES = frozenset({
    "BaseModel", "RootModel", "BaseSettings", "Protocol", "Enum", "IntEnum", "StrEnum", "Flag", "IntFlag",
    "TypedDict", "NamedTuple", "BaseException", "Exception",
})
INERT_DECORATORS = frozenset({
    "dataclass", "runtime_checkable", "total_ordering", "final", "unique", "lru_cache", "cache",
    "contextmanager", "asynccontextmanager", "overload",
})
TYPE_TESTS = frozenset({"isinstance", "issubclass"})
HEADER = (
    "# AD-1270 (#1324): production classes that nothing in production uses, each with its disposition.\n"
    "# Regenerate with: python -P scripts/check_dormant_classes.py --update-baseline\n"
    "# It keeps reviewed rows, adds new classes as 'unreviewed' and drops rows that are no longer dormant.\n"
    "# disposition: wire, retire or staged (owner: an issue or AD), or false-positive (note: why).\n"
    "# One row per class and nothing more: no description, status or test data. It is not a capability registry.\n"
)


@dataclass(frozen=True)
class Candidate:
    """A dormant class: ``key`` is ``<path relative to the source root>::<name>``."""

    key: str
    line: int


@dataclass
class Report:
    """What one scan found, sorted by key."""

    dormant: list[Candidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Module:
    """One parsed module: its top-level definitions and what its module-level code uses."""

    path: str
    symbols: dict[str, set[str]] = field(default_factory=dict)
    classes: dict[str, tuple[int, list[str]]] = field(default_factory=dict)
    root_uses: set[str] = field(default_factory=set)
    registered: set[str] = field(default_factory=set)

    def uses(self) -> set[str]:
        return self.root_uses.union(*self.symbols.values())


def _display(path: Path) -> str:
    """A path for the output: relative to the repository, or its name alone (never absolute)."""
    try:
        return path.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def _last_name(node: ast.AST) -> str:
    """``b`` for ``a.b``, ``a.b(...)`` or ``a.b[...]``; an empty string for anything else."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def _uses(root: ast.AST) -> set[str]:
    """The names ``root`` uses as values; the module docstring lists what is not a use."""
    found: set[str] = set()
    stack: list[ast.AST] = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.arg):
            continue  # an argument's only child node is its annotation
        if isinstance(node, ast.If) and _last_name(node.test) == "TYPE_CHECKING":
            stack.extend(node.orelse)
            continue
        if isinstance(node, ast.Assign) and any(_last_name(target) == "__all__" for target in node.targets):
            continue
        if isinstance(node, ast.AnnAssign):
            if node.value is not None:
                stack.append(node.value)
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack.extend(child for child in ast.iter_child_nodes(node) if child is not node.returns)
            continue
        if isinstance(node, ast.Call) and _last_name(node.func) in TYPE_TESTS:
            stack.extend([node.func, *node.args[:1], *(keyword.value for keyword in node.keywords)])
            continue
        if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops):
            operands = [node.left, *node.comparators]
            stack.extend(operand for operand in operands if not isinstance(operand, (ast.Name, ast.Attribute)))
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            found.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.add(re.split(r"[.:]", node.value)[-1])
        stack.extend(ast.iter_child_nodes(node))
    return found


def _aliases(tree: ast.Module) -> dict[str, set[str]]:
    """``{Y: {X, ...}}`` for each ``from m import X as Y`` anywhere in the module, a function body included."""
    aliases: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.asname and alias.asname != alias.name:
                    aliases.setdefault(alias.asname, set()).add(alias.name)
    return aliases


def _resolve(names: set[str], aliases: dict[str, set[str]]) -> set[str]:
    """``names`` and the original name behind each alias among them."""
    return names.union(*(aliases.get(name, set()) for name in names))


def _parse_module(path: str, tree: ast.Module) -> _Module:
    module = _Module(path)
    aliases = _aliases(tree)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module.root_uses |= _resolve(_uses(node), aliases)
            continue
        module.symbols.setdefault(node.name, set()).update(_resolve(_uses(node), aliases))
        if any(_last_name(decorator) not in INERT_DECORATORS for decorator in node.decorator_list):
            module.registered.add(node.name)
        if isinstance(node, ast.ClassDef):
            bases = _resolve({_last_name(base) for base in node.bases}, aliases)
            module.classes[node.name] = (node.lineno, sorted(bases))
    return module


def _live(module: _Module, users: dict[str, set[str]]) -> set[str]:
    """Top-level names of ``module`` that another module, module-level code or a live definition uses."""
    live = {
        name for name in module.symbols
        if users.get(name, set()) - {module.path} or name in module.root_uses or name in module.registered
    }
    frontier = list(live)
    while frontier:
        for name in module.symbols[frontier.pop()].intersection(module.symbols):
            if name not in live:
                live.add(name)
                frontier.append(name)
    return live


def _is_schema_base(name: str) -> bool:
    return name in SCHEMA_BASES or name.endswith(("Error", "Exception", "Warning"))


def _schema_classes(modules: list[_Module]) -> set[str]:
    """Class names whose bases reach a schema kind, matched by name across the tree."""
    bases: dict[str, set[str]] = {}
    for module in modules:
        for name, (_, names) in module.classes.items():
            bases.setdefault(name, set()).update(names)
    schema: set[str] = set()
    grew = True
    while grew:
        grew = False
        for name, names in bases.items():
            if name not in schema and any(_is_schema_base(base) or base in schema for base in names):
                schema.add(name)
                grew = True
    return schema


def build_report(source_root: Path) -> Report:
    """Scan every module under ``source_root`` and list its dormant classes, sorted by key."""
    report = Report()
    root = Path(source_root)
    if not root.is_dir():
        report.warnings.append(f"source root {_display(root)} is not a directory")
        return report
    modules: list[_Module] = []
    for path in sorted(root.rglob("*.py"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (SyntaxError, ValueError, UnicodeDecodeError, OSError) as exc:
            report.warnings.append(f"skipped {relative}: {type(exc).__name__}")
            continue
        modules.append(_parse_module(relative, tree))
    users: dict[str, set[str]] = {}
    for module in modules:
        for name in module.uses():
            users.setdefault(name, set()).add(module.path)
    schema = _schema_classes(modules)
    for module in modules:
        live = _live(module, users)
        for name, (line, _) in module.classes.items():
            if not (name.startswith("_") or name in schema or name in live):
                report.dormant.append(Candidate(f"{module.path}::{name}", line))
    report.dormant.sort(key=lambda candidate: candidate.key)
    return report


def load_baseline(path: Path, warnings: list[str]) -> dict[str, dict[str, Any]] | None:
    """The baseline's rows: ``{}`` when the file is absent, ``None`` when it cannot be read."""
    import yaml

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        warnings.append(f"no baseline at {_display(path)}; every dormant class is new")
        return {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        warnings.append(f"baseline not read ({_display(path)}): {type(exc).__name__}")
        return None  # unreadable
    rows = document.get("classes") if isinstance(document, dict) else None
    if not isinstance(rows, dict):
        warnings.append(f"baseline {_display(path)} has no 'classes' mapping")
        return None  # not a baseline document
    return {str(key): row if isinstance(row, dict) else {} for key, row in rows.items()}


def gap(row: dict[str, Any]) -> str | None:
    """Why a row has no reviewed disposition, or None when it has one."""
    disposition = row.get("disposition")
    if disposition == UNREVIEWED:
        return "unreviewed"
    if disposition not in DISPOSITIONS:
        return f"unknown disposition {disposition!r}"
    if disposition == "false-positive":
        return None if str(row.get("note") or "").strip() else "false-positive without a note"
    return None if OWNER.search(str(row.get("owner") or "")) else f"{disposition} without an owner issue or AD"


def merge(report: Report, rows: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Rows for the current dormant classes: reviewed fields kept, new classes ``unreviewed``."""
    merged: dict[str, dict[str, str]] = {}
    for candidate in report.dormant:
        kept = rows.get(candidate.key, {})
        row = {"disposition": str(kept.get("disposition") or UNREVIEWED)}
        row.update({name: str(kept[name]) for name in ("owner", "note") if kept.get(name)})
        merged[candidate.key] = row
    return merged


def render_baseline(merged: dict[str, dict[str, str]]) -> str:
    """The baseline text: sorted, ASCII and without a timestamp. Keys are relative paths; a retained owner or note is kept as written."""
    import yaml

    body = yaml.safe_dump(
        {"schema_version": 1, "classes": merged},
        sort_keys=True, allow_unicode=False, default_flow_style=False, width=4096,
    )
    return HEADER + body


def _where(candidate: Candidate) -> str:
    path, name = candidate.key.split("::")
    return f"{path}:{candidate.line} {name}"


def render(report: Report, rows: dict[str, dict[str, Any]]) -> str:
    """The summary line, then one line per finding."""
    dormant = {candidate.key: candidate for candidate in report.dormant}
    new = [key for key in dormant if key not in rows]
    left = sorted(key for key in rows if key not in dormant)
    gaps = [(key, reason) for key in dormant if key in rows and (reason := gap(rows[key]))]
    lines = [
        f"{PREFIX}{len(dormant)} dormant class(es): {len(new)} new, {len(gaps)} without a reviewed disposition, "
        f"{len(left)} baseline row(s) no longer dormant; this check warns and never fails"
    ]
    lines.extend(f"  new: {_where(dormant[key])}" for key in new)
    lines.extend(f"  {reason}: {_where(dormant[key])}" for key, reason in gaps)
    lines.extend(f"  no longer dormant (remove the row): {key}" for key in left)
    lines.extend(f"  warning: {item}" for item in report.warnings)
    return "\n".join(lines)


def _emit(text: str) -> None:
    """Write ``text`` and a newline as UTF-8 with LF line ends to stdout's byte buffer.

    A stdout without a ``buffer`` (a text-only stream) gets ``print``, so that stream's own newline
    translation applies.
    """
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        print(text)
        return
    sys.stdout.flush()
    stream.write(text.encode("utf-8") + b"\n")
    stream.flush()


def main(argv: list[str] | None = None) -> int:
    """Print the findings, rewriting the baseline first when asked. Returns 0 on every path.

    ``--help`` is answered here, not by argparse, so its first line also starts with ``PREFIX`` and it
    is written through ``_emit``.
    """
    try:
        parser = argparse.ArgumentParser(
            description="Report production classes nothing in production uses (report-only).", add_help=False
        )
        parser.add_argument("-h", "--help", action="store_true", help="show this help and check nothing")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--check", action="store_true", help="compare the tree with the baseline (the default)")
        mode.add_argument("--update-baseline", action="store_true", help="rewrite the baseline, keeping reviewed rows")
        parser.add_argument("--src", default=str(DEFAULT_SOURCE), help="source tree scanned")
        parser.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="baseline file of dispositions")
        args, unknown = parser.parse_known_args(argv)
    except SystemExit as exc:  # argparse exits on a malformed command line; this check never does
        if exc.code not in (0, None):
            _emit(f"{PREFIX}could not parse the arguments (argparse exit {exc.code}); nothing checked")
        return 0
    try:
        if args.help:
            _emit(f"{PREFIX}help; nothing checked\n{parser.format_help().rstrip()}")
            return 0  # help is the whole output
        report = build_report(Path(args.src))
        scan_complete = not report.warnings
        baseline = Path(args.baseline)
        rows = load_baseline(baseline, report.warnings)
        if args.update_baseline and scan_complete and rows is not None:
            rows = merge(report, rows)
            baseline.write_text(render_baseline(rows), encoding="utf-8", newline="\n")
            report.warnings.append(f"baseline rewritten: {_display(baseline)}")
        elif args.update_baseline:
            report.warnings.append("baseline not rewritten: the scan was incomplete or the baseline could not be read")
        report.warnings.extend(f"ignored argument {item!r}" for item in unknown)
        _emit(render(report, rows or {}))
    except Exception as exc:  # report-only: a failure to report is itself only reported
        _emit(f"{PREFIX}could not run: {type(exc).__name__}")
    return 0  # report-only: the status never reflects the findings


if __name__ == "__main__":
    raise SystemExit(main())
