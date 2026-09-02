#!/usr/bin/env python
"""Validate the durable-store declaration inventory (AD-1256).

ProbOS partitions durable state across dozens of SQLite files. Nothing recorded
which stores exist, who owns their lifecycle, how long rows live, or whether a
snapshot contains them. ``src/probos/**/storage_declarations.py`` now records
that, and this script is what makes those declarations a **contract** rather
than documentation: an inventory nobody can fail is prose.

It runs in **both** directions.

1.  **Declared -> exists.** Every ``owner_module``/``owner_symbol`` must resolve
    by AST against ``src/probos/``. A declaration naming a deleted store fails.
2.  **Exists -> declared.** Any module that builds a ``CREATE TABLE`` and is
    named by neither a declaration nor the reviewed baseline is an *undeclared
    store* and fails. The existing inventory is frozen into
    ``docs/development/store-baseline.yaml``, so a **new** store fails on day
    one while the pre-existing ones do not.

Usage::

    python scripts/check_store_registry.py --check
    python scripts/check_store_registry.py --check --json report.json
    python scripts/check_store_registry.py --update-baseline

Gating rules
------------
1.  ``declaration-schema`` -- a required field is missing or blank, an enum
    value is outside its closed vocabulary, ``retention`` is not ``bounded``
    without a ``retention_note``, or ``restore: reconstructed`` without a
    ``reconstruction``. A blank fails on purpose: a placeholder would pass a
    non-blank test and ship unreviewed.
2.  ``declaration-duplicate-id`` -- two declarations share an ``id``.
3.  ``declaration-duplicate-path`` -- two declarations claim one
    ``canonical_path``. A store has exactly one canonical spelling.
4.  ``declaration-owner-unresolved`` -- ``owner_module.owner_symbol`` does not
    resolve against ``src/probos/``.
5.  ``declaration-module-unregistered`` -- a ``storage_declarations.py`` exists
    under ``src/probos/`` that ``DECLARATION_MODULES`` does not name, or names
    a module that does not exist. The explicit-tuple pattern is chosen over a
    glob deliberately; this rule is what stops it falling silently behind.
6.  ``baseline-schema`` -- the baseline document is malformed, or its
    ``review`` block has a blank ``owner``/``rationale``/``review_by``.
7.  ``undeclared-store`` -- a module holding a detected ``CREATE TABLE`` that
    is in neither the declarations nor the baseline.
8.  ``stale-baseline-row`` -- a baseline row whose module no longer holds a
    detected schema, or which a declaration now covers. Either way the row must
    be deleted in the same commit.
9.  ``baseline-table-drift`` -- a baselined module's table set changed. Mirrors
    the architecture baseline's count drift: touching an undeclared store's
    schema is the moment to declare it.

Report-only, each with a named promotion condition
--------------------------------------------------
*   ``retention-sufficiency`` -- nothing measures growth, so "has a delete
    path" is not evidence that it works: ``activation_tracker.db`` prunes and
    is still ~1.03 GB. Promotes when AD-1265/1266 land a size census that can
    compare declared policy against observed bytes.
*   ``backup-restore-disposition`` -- AD-1265 owns backup and AD-1266 owns
    restore. The fields ship; the semantics do not. Promotes when AD-1266
    restores a declared point-in-time unit.
*   ``db-connect-debt`` -- direct-connect rows still in the architecture
    baseline. Shrinking them is opportunistic by #1302's own text and a shrink
    gate would force out-of-scope migrations. Promotes when the count reaches a
    reviewed floor of approved adapters only. **A new direct connect already
    fails** -- ``db-connect`` is in the architecture checker's
    ``GATING_CATEGORIES`` and compares symmetrically. AD-1256 adds nothing for
    it.
*   ``connection-factory-adoption`` -- modules holding a schema that never
    mention ``ConnectionFactory``. Same reason, same promotion condition.

Detection is AST-only for Python, and its bounds are real
---------------------------------------------------------
Store detection walks ASTs; it never regexes Python source, because
``CREATE TABLE`` inside a docstring, a code comment or an LLM prompt string
would read as a schema. Three shapes are detected:

*   **a.** a module-scope or local *named constant* bound to a string literal
    holding a ``CREATE [VIRTUAL] TABLE`` statement (51 modules on the tracked
    tree);
*   **b.** a string passed directly to ``execute``/``executescript``/
    ``executemany`` whose *literal* segments hold such a statement -- a plain
    constant, an f-string, a ``+`` concatenation, a ``%`` format or a
    ``str.format`` call (5 modules on the tracked tree: ``cognitive.episodic``,
    ``crew_profile``, ``directive_store``, ``security.audit_log``,
    ``service_profile``);
*   **c.** a tracked ``*.sql`` file under ``src/``. Its text is SQL by
    construction, so it needs no AST and the shared pattern is applied to it
    directly. The store is attributed to the package directory holding the
    file, and must be declared or baselined exactly as a module's is. There are
    no such files on the tracked tree today; the rule exists so the first one
    does not arrive unnoticed.

**Why rule (b) reads dynamic strings and rule (a) does not.** A string handed to
``execute`` is SQL because the callee says so. A string bound to a *name* proves
nothing about itself: ``cognitive.builder_specialists`` assigns an LLM
instruction containing the words ``CREATE TABLE IF NOT EXISTS`` with ``+``, and
joining its literal segments under rule (a) reports it as a store creating a
table named ``IF`` (measured). That is why the widening stops at the call
boundary rather than covering every dynamically built string.

**What still escapes, stated plainly.** Rule (b) reads the literal segments of a
dynamic string, not the string. Three shapes therefore remain invisible, and
none of them is closable by static analysis alone:

*   **A table name known only at runtime.** ``execute(f"CREATE TABLE {name}")``
    carries no literal table name anywhere in the source. The pattern is both
    the schema gate and the name extractor, so with nothing to extract the
    module is not reported at all. This is a real hole, not a rounding error.
*   **A dynamic schema bound to a name and executed through that name.** Rule
    (a) requires a plain constant for the false-positive reason above, so its
    literal segments are never joined.
*   **A schema reaching the database through a helper** that is not one of the
    three named execute methods.

Measured on the tracked tree, 59 modules match the detection pattern as raw text
and 56 are detected. All three that escape are false positives, and they escape
for three different reasons worth stating separately:

*   ``probos.config`` -- the phrase is in a **docstring**. A docstring binds no
    name and is passed to no ``execute``, so it is excluded by construction.
*   ``probos.experience.commands.commands_directives`` -- the phrase is in a
    **comment** (``# Create table``, above a Rich ``Table`` constructor).
    ``ast.parse`` discards comments entirely, so this one cannot reach either
    rule. It is also why a raw text census over-counts: a case-insensitive text
    scan reports 58 ``CREATE TABLE`` modules, and this is the 58th.
*   ``probos.cognitive.builder_specialists`` -- the phrase is in an LLM
    instruction string assembled with ``+`` (an ``ast.BinOp``), so it escapes
    rule (a), which requires a plain constant. Here that bound gives the right
    answer; a *real* schema built the same way would also escape. Do not read
    56/59 as full coverage.

The counterpart bound: this script proves a module *declares a table*, never
that a store is *reachable*, *used*, or *correct*.

Resolution and file listing
---------------------------
Symbols resolve by AST, never by importing ``probos`` -- importing would run
side effects, and under the canonical gate it could bind the *installed*
package rather than the materialized ``HEAD`` worktree, which is the exact
developer-local/gate seam this program exists to close. For the same reason the
file list comes from ``git ls-files`` rather than a disk walk: untracked
work-in-progress must be invisible here, because it is invisible to the gate.

That choice means the declaration schema rules are mirrored here rather than
imported from ``probos.storage.declarations.declaration_errors``. The two
instruments are held in sync by a test that asserts the AST-extracted mapping
for every committed declaration is identical to the imported dataclass's
``to_dict()``.

Writes nothing under ``--check``. The gate wrapper fails the run if preflight
mutates the tree.
"""

from __future__ import annotations

import argparse
import ast
import gc
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SRC_ROOT = _REPO_ROOT / "src"
_DEFAULT_BASELINE = _REPO_ROOT / "docs" / "development" / "store-baseline.yaml"

#: Every gating rule this script implements. A completeness test binds this to
#: the documented set, so a rule cannot be added without documenting it.
GATING_RULES: tuple[str, ...] = (
    "declaration-schema",
    "declaration-duplicate-id",
    "declaration-duplicate-path",
    "declaration-owner-unresolved",
    "declaration-module-unregistered",
    "baseline-schema",
    "undeclared-store",
    "stale-baseline-row",
    "baseline-table-drift",
)

#: Reported, never failed. Each entry is (rule, promotion condition).
REPORT_ONLY_RULES: tuple[tuple[str, str], ...] = (
    (
        "retention-sufficiency",
        "AD-1265/1266 land a size census that can compare declared retention "
        "policy against observed bytes",
    ),
    (
        "backup-restore-disposition",
        "AD-1266 restores a declared point-in-time unit",
    ),
    (
        "db-connect-debt",
        "the architecture baseline's db-connect rows reach a reviewed floor of "
        "approved adapters only",
    ),
    (
        "connection-factory-adoption",
        "same as db-connect-debt; migrating a store is out of scope for #1302",
    ),
)

#: Required non-blank fields on every declaration.
_REQUIRED_TEXT_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "owner_module",
    "owner_symbol",
    "canonical_path",
    "lifecycle_owner",
)

#: Required top-level keys in the baseline document.
REQUIRED_BASELINE_KEYS: tuple[str, ...] = (
    "schema_version",
    "baseline_id",
    "tracking_issue",
    "review",
    "undeclared_stores",
)

_EXECUTE_METHODS: frozenset[str] = frozenset(
    {"execute", "executescript", "executemany"}
)

# Applied to an SQL string already extracted by AST, never to Python source.
# SQL has no AST available here; this parses the statement, not the module.
#
# This one pattern is BOTH the "is there a schema here" gate and the table-name
# extractor, deliberately. When those were two instruments -- a `"CREATE TABLE"
# in source` substring test plus this regex -- they disagreed: `CREATE VIRTUAL
# TABLE` does not contain the substring `CREATE TABLE`, so a store whose only
# schema is an FTS5 virtual table was invisible to the gate while the extractor
# was written to handle it. Sharing the pattern makes that class of
# disagreement unrepresentable.
_TABLE_NAME_RE = re.compile(
    r"CREATE\s+(?:VIRTUAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"[\"'`\[]?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)

_DECLARATION_MODULE_SUFFIX = "storage_declarations"


# ── symbol resolution ────────────────────────────────────────────────
# Mirrored from scripts/check_seam_contracts.py rather than imported: the gate
# invokes preflight phases with `python -P`, which suppresses prepending the
# script's own directory to sys.path, so a cross-script import is unavailable.


@dataclass(frozen=True)
class SymbolIndex:
    """Module-scope names and class methods under a source root.

    No inheritance walk: a method inherited from a base class in another module
    does not resolve, which keeps a false *pass* impossible at the cost of some
    false failures a reviewer can see and fix.
    """

    modules: dict[str, set[str]] = field(default_factory=dict)
    class_methods: dict[str, dict[str, set[str]]] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    #: Detected tables per module, filled from the tree this index already
    #: parsed. Detection needs the AST of every module now that there is no
    #: raw-source prefilter, and parsing ~915 modules a second time to get it
    #: would double the phase's cost for nothing.
    tables: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: The root this index was built from, so non-Python store shapes under it
    #: (rule (c)) can be found without threading the path through every caller.
    src_root: Path | None = None


def _module_dotted_path(py_file: Path, src_root: Path) -> str | None:
    """Return the dotted module path for ``py_file``, or None if outside."""
    try:
        relative = py_file.resolve().relative_to(src_root.resolve())
    except ValueError:
        return None
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    return ".".join(parts) if parts else None


def _tracked_files(src_root: Path, pathspec: str) -> list[Path] | None:
    """Files under ``src_root`` matching ``pathspec`` that git actually tracks.

    Returns ``None`` when git cannot answer, so the caller can fall back to a
    disk walk rather than silently indexing nothing.
    """
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z", "--", pathspec],
            cwd=src_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return [src_root / name for name in (completed.stdout or "").split("\0") if name]


def _tracked_python_files(src_root: Path) -> list[Path] | None:
    """Tracked Python files under ``src_root``; ``None`` when git cannot answer."""
    return _tracked_files(src_root, "*.py")


def build_symbol_index(src_root: Path) -> SymbolIndex:
    """Build the module/class/method index for ``src_root`` by AST.

    A file that does not parse is skipped rather than fatal: an unparseable
    source file is the ``compile`` preflight phase's failure to report, and
    duplicating it here would produce two errors for one defect.
    """
    index = SymbolIndex(src_root=src_root)
    if not src_root.is_dir():
        return index
    tracked = _tracked_python_files(src_root)
    if tracked is None:
        print(
            f"warning: git could not enumerate {src_root}; falling back to a "
            "disk walk. Untracked files may satisfy resolution here but not in "
            "the canonical gate.",
            file=sys.stderr,
        )
        candidates = sorted(src_root.rglob("*.py"))
    else:
        candidates = sorted(path for path in tracked if path.is_file())

    for py_file in candidates:
        dotted = _module_dotted_path(py_file, src_root)
        if dotted is None:
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        names: set[str] = set()
        classes: dict[str, set[str]] = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
                classes[node.name] = {
                    child.name
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names.update(
                    target.id
                    for target in node.targets
                    if isinstance(target, ast.Name)
                )
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
        index.modules[dotted] = names
        index.class_methods[dotted] = classes
        index.sources[dotted] = source
        index.tables[dotted] = _tables_from_tree(tree)
    return index


def resolve_symbol(module: str, symbol: str, index: SymbolIndex) -> str | None:
    """Return None when ``module``/``symbol`` resolves, else a reason string."""
    if module not in index.modules:
        return f"no module under src/ named {module!r}"
    if symbol in index.modules[module]:
        return None
    return f"module {module!r} exists but defines no module-scope {symbol!r}"


# ── store detection (exists -> declared) ─────────────────────────────


def _docstring_constant_ids(tree: ast.Module) -> set[int]:
    """Object ids of every docstring node, so detection can exclude them."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr):
                value = body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    found.add(id(value))
    return found


def _literal_text(node: ast.AST, is_docstring: Callable[[ast.AST], bool]) -> str | None:
    """Concatenate the literal string segments of a possibly dynamic string.

    An f-string, a ``+`` concatenation, a ``%`` format and ``str.format`` all
    bind no plain ``ast.Constant``, so a schema written that way used to be
    invisible to detection entirely. Interpolated segments contribute nothing,
    which is exactly the residual bound the module docstring states: a table
    name that only exists at runtime leaves no literal to extract.

    Returns ``None`` when the node carries no literal text at all.
    """
    parts: list[str] = []

    def visit(current: ast.AST) -> None:
        if isinstance(current, ast.Constant):
            if isinstance(current.value, str) and not is_docstring(current):
                parts.append(current.value)
        elif isinstance(current, ast.JoinedStr):
            for piece in current.values:
                visit(piece)
        elif isinstance(current, ast.BinOp) and isinstance(current.op, ast.Add):
            visit(current.left)
            visit(current.right)
        elif isinstance(current, ast.BinOp) and isinstance(current.op, ast.Mod):
            visit(current.left)  # the right operand is the argument tuple
        elif (
            isinstance(current, ast.Call)
            and isinstance(current.func, ast.Attribute)
            and current.func.attr == "format"
        ):
            visit(current.func.value)

    visit(node)
    return "".join(parts) if parts else None


def detect_tables(source: str) -> tuple[str, ...]:
    """Table names this module creates, detected by AST. Sorted, deduplicated.

    See the module docstring for the detected shapes and what escapes them.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    return _tables_from_tree(tree)


def _tables_from_tree(tree: ast.Module) -> tuple[str, ...]:
    """The tree walk behind :func:`detect_tables`, for an already-parsed module."""
    statements: list[str] = []
    docstrings: set[int] | None = None

    def _is_docstring(node: ast.AST) -> bool:
        """Deferred: finding docstrings is a second full walk of the tree.

        Detection now needs every module's AST, and the overwhelming majority
        hold no schema at all. Asking the cheap question first -- does this
        string even look like DDL -- keeps that walk off the common path.
        """
        nonlocal docstrings
        if docstrings is None:
            docstrings = _docstring_constant_ids(tree)
        return id(node) in docstrings

    def _sql_of(node: ast.AST) -> str | None:
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _TABLE_NAME_RE.search(node.value)
            and not _is_docstring(node)
        ):
            return node.value
        return None

    def _executed_sql_of(node: ast.AST) -> str | None:
        """Rule (b): the callee proves this argument is SQL, so read it dynamically."""
        text = _literal_text(node, _is_docstring)
        if text is not None and _TABLE_NAME_RE.search(text):
            return text
        return None

    for node in ast.walk(tree):
        # (a) a named constant bound to a schema literal
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) for target in node.targets
        ):
            sql = _sql_of(node.value)
            if sql is not None:
                statements.append(sql)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            sql = _sql_of(node.value)
            if sql is not None:
                statements.append(sql)
        # (b) a schema passed to execute*/executescript, literal or assembled
        elif isinstance(node, ast.Call):
            func = node.func
            called = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else ""
            )
            if called in _EXECUTE_METHODS:
                for argument in node.args:
                    sql = _executed_sql_of(argument)
                    if sql is not None:
                        statements.append(sql)

    tables: set[str] = set()
    for statement in statements:
        tables.update(_TABLE_NAME_RE.findall(statement))
    return tuple(sorted(tables))


def _sql_owner_package(sql_file: Path, src_root: Path) -> str | None:
    """Dotted package owning a ``.sql`` file: the directory that holds it."""
    try:
        relative = sql_file.resolve().relative_to(src_root.resolve())
    except (ValueError, OSError):
        return None
    parts = list(relative.parts[:-1])
    return ".".join(parts) if parts else None


def detect_sql_file_stores(src_root: Path) -> dict[str, tuple[str, ...]]:
    """Rule (c): tables created by tracked ``.sql`` files, by owning package.

    A schema in a ``.sql`` file is still a store; it just has no Python AST to
    walk. The whole file is SQL by construction, so the shared pattern reads its
    text directly -- the docstring/comment ambiguity that forces AST-only
    reading of ``.py`` does not arise. A commented-out ``CREATE TABLE`` in a
    migration therefore reads as a schema, which fails in the visible direction:
    a reviewer sees the failure, where a false pass would show nothing.
    """
    if not src_root.is_dir():
        return {}
    tracked = _tracked_files(src_root, "*.sql")
    candidates = sorted(src_root.rglob("*.sql")) if tracked is None else sorted(tracked)

    found: dict[str, set[str]] = {}
    for sql_file in candidates:
        if not sql_file.is_file():
            continue
        package = _sql_owner_package(sql_file, src_root)
        if package is None:
            continue
        try:
            text = sql_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        tables = set(_TABLE_NAME_RE.findall(text))
        if tables:
            found.setdefault(package, set()).update(tables)
    return {package: tuple(sorted(tables)) for package, tables in found.items()}


def detect_stores(index: SymbolIndex) -> dict[str, tuple[str, ...]]:
    """Every module or package that creates at least one table, to its tables.

    There is deliberately no raw-source prefilter. One existed, and it was a
    second instrument that disagreed with the first: rule (b) joins the literal
    segments of a dynamic string, so ``execute("CREATE TABLE " + "widgets")``
    produces a match the AST can see and no contiguous run of source text can.
    The prefilter skipped the module before ``detect_tables`` ever ran. It also
    contradicted this module's own rule that detection never regexes Python
    source. Detection therefore needs every module's AST, which
    :func:`build_symbol_index` already parsed and cached in ``index.tables``.
    """
    found: dict[str, tuple[str, ...]] = {}
    for module, source in index.sources.items():
        tables = index.tables.get(module)
        if tables is None:  # a hand-built index that never parsed anything
            tables = detect_tables(source)
        if tables:
            found[module] = tables
    if index.src_root is not None:
        for package, tables in detect_sql_file_stores(index.src_root).items():
            found[package] = tuple(sorted(set(found.get(package, ())) | set(tables)))
    return found


# ── declaration reading (declared -> exists) ─────────────────────────


def read_declaration_modules(src_root: Path) -> tuple[tuple[str, ...], list[str]]:
    """Read ``DECLARATION_MODULES`` from the store registry by AST."""
    registry = src_root / "probos" / "storage" / "registry.py"
    if not registry.is_file():
        return (), [
            f"{registry.as_posix()} does not exist; the store registry is the "
            "authority for which modules declare stores"
        ]
    try:
        tree = ast.parse(registry.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        return (), [f"{registry.as_posix()}: cannot be parsed: {exc}"]
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "DECLARATION_MODULES"
            for target in targets
        ):
            continue
        value = node.value
        if not isinstance(value, (ast.Tuple, ast.List)):
            return (), [
                "DECLARATION_MODULES must be a literal tuple or list of dotted "
                "module names so it can be read without importing"
            ]
        names: list[str] = []
        for element in value.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                names.append(element.value)
        return tuple(names), []
    return (), ["DECLARATION_MODULES is not defined in probos/storage/registry.py"]


def _literal(node: ast.expr) -> Any:
    """Best-effort literal value of an AST node, or a marker for enums.

    Enum members arrive as ``StoreCriticality.REQUIRED``; they are returned as
    the ``("enum", "StoreCriticality", "REQUIRED")`` triple so the caller can
    resolve them against the vocabulary read from the same tree.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return ("enum", node.value.id, node.attr)
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def read_vocabulary(src_root: Path) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Read the closed vocabularies from ``storage/declarations.py`` by AST.

    Read from the tree rather than imported so the checker validates against
    the vocabulary in the materialized worktree, not whatever version of the
    package happens to be installed.
    """
    model = src_root / "probos" / "storage" / "declarations.py"
    if not model.is_file():
        return {}, [f"{model.as_posix()} does not exist"]
    try:
        tree = ast.parse(model.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        return {}, [f"{model.as_posix()}: cannot be parsed: {exc}"]

    vocabulary: dict[str, dict[str, str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in {
            "StoreCriticality",
            "StoreRetention",
        }:
            members: dict[str, str] = {}
            for child in node.body:
                if isinstance(child, ast.Assign) and isinstance(
                    child.value, ast.Constant
                ):
                    for target in child.targets:
                        if isinstance(target, ast.Name) and isinstance(
                            child.value.value, str
                        ):
                            members[target.id] = child.value.value
            vocabulary[node.name] = members
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in {"BACKUP_DISPOSITIONS", "RESTORE_DISPOSITIONS"}:
                value = node.value
                literal: Any = None
                if isinstance(value, ast.Call) and value.args:
                    literal = _literal(value.args[0])
                if isinstance(literal, (set, frozenset, list, tuple)):
                    vocabulary[node.target.id] = {
                        str(item): str(item) for item in literal
                    }

    errors: list[str] = []
    for required in (
        "StoreCriticality",
        "StoreRetention",
        "BACKUP_DISPOSITIONS",
        "RESTORE_DISPOSITIONS",
    ):
        if not vocabulary.get(required):
            errors.append(
                f"probos/storage/declarations.py: {required} is missing or not "
                "a literal the checker can read without importing"
            )
    return vocabulary, errors


def read_declarations(
    module_names: tuple[str, ...], index: SymbolIndex, src_root: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract every ``STORE_DECLARATIONS`` entry by AST."""
    declarations: list[dict[str, Any]] = []
    errors: list[str] = []
    for module_name in module_names:
        source = index.sources.get(module_name)
        if source is None:
            errors.append(
                f"[declaration-module-unregistered] DECLARATION_MODULES names "
                f"{module_name!r}, which is not a tracked module under "
                f"{src_root.as_posix()}. Remove it from DECLARATION_MODULES in "
                "probos/storage/registry.py, or add the module."
            )
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            errors.append(f"{module_name}: cannot be parsed: {exc}")
            continue
        found = False
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "STORE_DECLARATIONS"
                for target in targets
            ):
                continue
            found = True
            value = node.value
            if not isinstance(value, (ast.Tuple, ast.List)):
                errors.append(
                    f"{module_name}: STORE_DECLARATIONS must be a literal tuple "
                    "of StoreDeclaration(...) calls"
                )
                continue
            for element in value.elts:
                if not isinstance(element, ast.Call):
                    errors.append(
                        f"{module_name}: STORE_DECLARATIONS holds a "
                        f"{type(element).__name__}, expected StoreDeclaration(...)"
                    )
                    continue
                fields: dict[str, Any] = {
                    "_declared_in": module_name,
                    "_line": element.lineno,
                }
                for keyword in element.keywords:
                    if keyword.arg is None:
                        errors.append(
                            f"{module_name}:{element.lineno}: **kwargs in a "
                            "StoreDeclaration(...) call cannot be read "
                            "statically; write every field explicitly"
                        )
                        continue
                    fields[keyword.arg] = _literal(keyword.value)
                if element.args:
                    errors.append(
                        f"{module_name}:{element.lineno}: StoreDeclaration(...) "
                        "must be called with keyword arguments only, so the "
                        "checker can read it without importing"
                    )
                declarations.append(fields)
        if not found:
            errors.append(
                f"{module_name}: declares no STORE_DECLARATIONS tuple; either "
                "add one or remove the module from DECLARATION_MODULES"
            )
    return declarations, errors


def find_declaration_modules_on_disk(index: SymbolIndex) -> tuple[str, ...]:
    """Every tracked module whose name ends in ``storage_declarations``."""
    return tuple(
        sorted(
            module
            for module in index.sources
            if module.rsplit(".", 1)[-1] == _DECLARATION_MODULE_SUFFIX
        )
    )


# ── validation ───────────────────────────────────────────────────────


def _enum_value(
    raw: Any, expected_class: str, vocabulary: dict[str, dict[str, str]]
) -> str | None:
    """Resolve an AST-extracted enum reference to its string value."""
    if isinstance(raw, tuple) and len(raw) == 3 and raw[0] == "enum":
        _, class_name, member = raw
        if class_name != expected_class:
            return None
        return vocabulary.get(expected_class, {}).get(member)
    if isinstance(raw, str):
        # A bare string is accepted only if it is a legal value of the enum.
        return raw if raw in vocabulary.get(expected_class, {}).values() else None
    return None


def declaration_schema_errors(
    declaration: dict[str, Any], vocabulary: dict[str, dict[str, str]]
) -> list[str]:
    """Every schema problem with one AST-extracted declaration.

    Mirrors ``probos.storage.declarations.declaration_errors``; see the module
    docstring for why it is mirrored rather than imported, and for the test that
    holds the two in sync.
    """
    problems: list[str] = []
    raw_id = declaration.get("id")
    where = raw_id if isinstance(raw_id, str) and raw_id.strip() else "<blank id>"
    origin = f"{declaration.get('_declared_in')}:{declaration.get('_line')}"

    for field_name in _REQUIRED_TEXT_FIELDS:
        value = declaration.get(field_name)
        if not isinstance(value, str) or not value.strip():
            problems.append(
                f"[declaration-schema] {origin} {where}: {field_name!r} is "
                "missing or blank. Every declaration must state it; a blank is "
                "an error rather than a warning because a blank is "
                "indistinguishable from nobody having looked."
            )

    criticality = _enum_value(
        declaration.get("criticality"), "StoreCriticality", vocabulary
    )
    if criticality is None:
        problems.append(
            f"[declaration-schema] {origin} {where}: criticality "
            f"{declaration.get('criticality')!r} is not a StoreCriticality "
            f"member; expected one of "
            f"{sorted(vocabulary.get('StoreCriticality', {}).values())}"
        )
    retention = _enum_value(
        declaration.get("retention"), "StoreRetention", vocabulary
    )
    if retention is None:
        problems.append(
            f"[declaration-schema] {origin} {where}: retention "
            f"{declaration.get('retention')!r} is not a StoreRetention member; "
            f"expected one of "
            f"{sorted(vocabulary.get('StoreRetention', {}).values())}"
        )

    backup = declaration.get("backup")
    if backup not in vocabulary.get("BACKUP_DISPOSITIONS", {}):
        problems.append(
            f"[declaration-schema] {origin} {where}: backup {backup!r} is not "
            f"one of {sorted(vocabulary.get('BACKUP_DISPOSITIONS', {}))}"
        )
    restore = declaration.get("restore")
    if restore not in vocabulary.get("RESTORE_DISPOSITIONS", {}):
        problems.append(
            f"[declaration-schema] {origin} {where}: restore {restore!r} is not "
            f"one of {sorted(vocabulary.get('RESTORE_DISPOSITIONS', {}))}"
        )

    note = declaration.get("retention_note") or ""
    if retention is not None and retention != "bounded" and not str(note).strip():
        problems.append(
            f"[declaration-schema] {origin} {where}: retention is {retention!r} "
            "so 'retention_note' is required. Unbounded growth is legal here, "
            "but only deliberately and in writing."
        )
    reconstruction = declaration.get("reconstruction") or ""
    if restore == "reconstructed" and not str(reconstruction).strip():
        problems.append(
            f"[declaration-schema] {origin} {where}: restore is 'reconstructed' "
            "so 'reconstruction' is required and must name how the data comes "
            "back."
        )
    if restore != "reconstructed" and str(reconstruction).strip():
        problems.append(
            f"[declaration-schema] {origin} {where}: 'reconstruction' is set but "
            f"restore is {restore!r}; a reconstruction method only means "
            "something when restore is 'reconstructed'."
        )
    return problems


def load_baseline(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """Load and shape-check the baseline document."""
    if not path.is_file():
        return None, [
            f"[baseline-schema] {path.as_posix()} does not exist; generate it "
            "with python scripts/check_store_registry.py --update-baseline and "
            "review every row before committing"
        ]
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return None, [f"[baseline-schema] {path.name}: does not parse as YAML: {exc}"]
    if not isinstance(document, dict):
        return None, [
            f"[baseline-schema] {path.name}: top level is "
            f"{type(document).__name__}, expected a mapping"
        ]
    errors = [
        f"[baseline-schema] {path.name}: missing required top-level key {key!r}"
        for key in REQUIRED_BASELINE_KEYS
        if key not in document
    ]
    review = document.get("review")
    if not isinstance(review, dict):
        errors.append(
            f"[baseline-schema] {path.name}: 'review' is "
            f"{type(review).__name__}, expected a mapping with owner, "
            "rationale and review_by"
        )
    else:
        for required in ("owner", "rationale", "review_by"):
            value = review.get(required)
            if value is None or not str(value).strip():
                errors.append(
                    f"[baseline-schema] {path.name}: review.{required} is "
                    "missing or blank; a frozen inventory needs an owner, a "
                    "rationale and a review_by date or removal condition"
                )
    return document, errors


def baseline_rows(
    document: dict[str, Any], label: str
) -> tuple[dict[str, tuple[str, ...]], list[str]]:
    """Validate and return the baseline's undeclared-store rows."""
    errors: list[str] = []
    rows: dict[str, tuple[str, ...]] = {}
    raw_rows = document.get("undeclared_stores") or []
    if not isinstance(raw_rows, list):
        return rows, [
            f"[baseline-schema] {label}: undeclared_stores is "
            f"{type(raw_rows).__name__}, expected a list"
        ]
    for position, raw in enumerate(raw_rows):
        where = f"{label}:undeclared_stores[{position}]"
        if not isinstance(raw, dict):
            errors.append(
                f"[baseline-schema] {where}: row is {type(raw).__name__}, "
                "expected a mapping"
            )
            continue
        module = raw.get("module")
        if not isinstance(module, str) or not module.strip():
            errors.append(f"[baseline-schema] {where}: module is missing or blank")
            continue
        if module in rows:
            errors.append(
                f"[baseline-schema] {label}: duplicate row for module {module!r}"
            )
            continue
        tables = raw.get("tables") or []
        if not isinstance(tables, list) or any(
            not isinstance(item, str) for item in tables
        ):
            errors.append(
                f"[baseline-schema] {label}[{module}]: tables must be a list of "
                "strings"
            )
            tables = []
        rows[module] = tuple(sorted(str(item) for item in tables))
    return rows, errors


def _fix_command(baseline_path: Path) -> str:
    suffix = ""
    if baseline_path.resolve() != _DEFAULT_BASELINE.resolve():
        suffix = f" --baseline {baseline_path.as_posix()}"
    return f"python scripts/check_store_registry.py --update-baseline{suffix}"


def compare_to_baseline(
    detected: dict[str, tuple[str, ...]],
    declared_modules: set[str],
    rows: dict[str, tuple[str, ...]],
    baseline_path: Path,
) -> list[str]:
    """Symmetric difference plus per-row table equality.

    Every difference is reported, never just the first, and each message names
    the exact module and the exact command that fixes it -- a symmetric gate
    that does not tell you how to satisfy it becomes a tax that gets disabled.
    """
    errors: list[str] = []
    fix = _fix_command(baseline_path)
    undeclared = {
        module: tables
        for module, tables in detected.items()
        if module not in declared_modules
    }

    for module in sorted(set(undeclared) - set(rows)):
        errors.append(
            f"[undeclared-store] {module} creates "
            f"{list(undeclared[module])} but is named by no declaration and is "
            f"not in {baseline_path.name}. Declare it in a "
            "storage_declarations.py beside its owner -- every NEW store "
            f"registers immediately -- or, if it is pre-existing, run: {fix}"
        )

    for module in sorted(set(rows) - set(undeclared)):
        if module in declared_modules:
            reason = "is now covered by a declaration"
        else:
            reason = "no longer creates any table the checker can detect"
        errors.append(
            f"[stale-baseline-row] {module} {reason}. Delete this row from "
            f"{baseline_path.name} in the same commit that changed it, or "
            f"run: {fix}"
        )

    for module in sorted(set(rows) & set(undeclared)):
        if rows[module] != undeclared[module]:
            errors.append(
                f"[baseline-table-drift] {module}: baseline records "
                f"{list(rows[module])}, tree now creates "
                f"{list(undeclared[module])}. Touching an undeclared store's "
                "schema is the moment to declare it; otherwise update the "
                f"reviewed row in the same commit: {fix}"
            )
    return errors


# ── orchestration ────────────────────────────────────────────────────


@dataclass
class CheckResult:
    """Outcome of one full check."""

    errors: list[str] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)
    detected: dict[str, tuple[str, ...]] = field(default_factory=dict)
    declarations: list[dict[str, Any]] = field(default_factory=list)


def check(
    baseline_path: Path = _DEFAULT_BASELINE,
    src_root: Path = _DEFAULT_SRC_ROOT,
) -> CheckResult:
    """Run every rule and accumulate every error."""
    errors: list[str] = []
    index = build_symbol_index(src_root)
    vocabulary, vocabulary_errors = read_vocabulary(src_root)
    errors.extend(vocabulary_errors)

    module_names, module_errors = read_declaration_modules(src_root)
    errors.extend(module_errors)

    on_disk = find_declaration_modules_on_disk(index)
    for module in on_disk:
        if module not in module_names:
            errors.append(
                f"[declaration-module-unregistered] {module} exists but "
                "DECLARATION_MODULES does not name it, so its stores are "
                "invisible to the registry. Add it to DECLARATION_MODULES in "
                "probos/storage/registry.py."
            )

    declarations, declaration_errors_found = read_declarations(
        module_names, index, src_root
    )
    errors.extend(declaration_errors_found)

    seen_ids: dict[str, str] = {}
    seen_paths: dict[str, str] = {}
    declared_modules: set[str] = set()
    for declaration in declarations:
        errors.extend(declaration_schema_errors(declaration, vocabulary))
        store_id = declaration.get("id")
        origin = f"{declaration.get('_declared_in')}:{declaration.get('_line')}"
        if isinstance(store_id, str) and store_id.strip():
            previous = seen_ids.get(store_id)
            if previous is not None:
                errors.append(
                    f"[declaration-duplicate-id] {origin} {store_id!r} is "
                    f"already declared at {previous}. Two declarations sharing "
                    "an id silently merge two stores' metadata."
                )
            else:
                seen_ids[store_id] = origin
        canonical = declaration.get("canonical_path")
        if isinstance(canonical, str) and canonical.strip():
            previous = seen_paths.get(canonical)
            if previous is not None:
                errors.append(
                    f"[declaration-duplicate-path] {origin} claims "
                    f"canonical_path {canonical!r}, already claimed at "
                    f"{previous}. A store has exactly one canonical path."
                )
            else:
                seen_paths[canonical] = origin
        owner_module = declaration.get("owner_module")
        owner_symbol = declaration.get("owner_symbol")
        if isinstance(owner_module, str) and isinstance(owner_symbol, str):
            reason = resolve_symbol(owner_module, owner_symbol, index)
            if reason is not None:
                errors.append(
                    f"[declaration-owner-unresolved] {origin} "
                    f"{store_id!r} names owner {owner_module}.{owner_symbol}: "
                    f"{reason}. Point the declaration at a symbol that exists, "
                    "or delete the declaration if the store is gone."
                )
            else:
                declared_modules.add(owner_module)

    detected = detect_stores(index)

    document, baseline_load_errors = load_baseline(baseline_path)
    errors.extend(baseline_load_errors)
    rows: dict[str, tuple[str, ...]] = {}
    if document is not None:
        rows, row_errors = baseline_rows(document, baseline_path.name)
        errors.extend(row_errors)
        errors.extend(
            compare_to_baseline(detected, declared_modules, rows, baseline_path)
        )

    undeclared = sorted(set(detected) - declared_modules)
    factory_absent = sorted(
        module
        for module in detected
        if "ConnectionFactory" not in index.sources.get(module, "")
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "gating_rules": list(GATING_RULES),
        "report_only": {
            rule: {"promotion": promotion} for rule, promotion in REPORT_ONLY_RULES
        },
        "declarations": len(declarations),
        "declaration_modules": list(module_names),
        "detected_store_modules": len(detected),
        "undeclared_store_modules": len(undeclared),
        "baseline_rows": len(rows),
        "connection_factory_absent": len(factory_absent),
        "errors": len(errors),
    }
    return CheckResult(
        errors=errors, report=report, detected=detected, declarations=declarations
    )


def render_baseline(
    detected: dict[str, tuple[str, ...]],
    declared_modules: set[str],
    previous: dict[str, Any] | None,
) -> str:
    """Render the baseline YAML, preserving reviewed metadata.

    New rows carry only evidence -- the module and the tables it creates. The
    review fields live once at document level: every row here means the same
    thing (a store that predates the registry), so per-row rationales would be
    fifty copies of one sentence, and a field that is always the same sentence
    stops being read. A **blank** document-level owner/rationale/review_by
    fails ``--check`` on purpose.
    """
    previous = previous or {}
    review = previous.get("review")
    if not isinstance(review, dict):
        review = {"owner": "", "rationale": "", "review_by": ""}
    document: dict[str, Any] = {
        "schema_version": 1,
        "baseline_id": previous.get("baseline_id", "ad-1256-store-inventory-v1"),
        "tracking_issue": previous.get("tracking_issue", 1302),
        "review": {
            "owner": review.get("owner") or "",
            "rationale": review.get("rationale") or "",
            "review_by": review.get("review_by") or "",
        },
        "undeclared_stores": [
            {"module": module, "tables": list(detected[module])}
            for module in sorted(set(detected) - declared_modules)
        ],
    }
    header = (
        "# AD-1256 store inventory baseline: every module that creates a table\n"
        "# and does not yet have a declaration. Frozen so a NEW undeclared\n"
        "# store fails on day one while the pre-existing ones do not.\n"
        "#\n"
        "# Regenerate the row set with:\n"
        "#   python scripts/check_store_registry.py --update-baseline\n"
        "# A blank review.owner/rationale/review_by fails --check on purpose.\n"
        "# Declaring a store means DELETING its row here in the same commit.\n"
    )
    body = yaml.safe_dump(
        document,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10**9,
    )
    return header + body


def _declared_modules_for_baseline(
    src_root: Path, index: SymbolIndex
) -> set[str]:
    """Owner modules named by declarations, for baseline rendering."""
    module_names, _ = read_declaration_modules(src_root)
    declarations, _ = read_declarations(module_names, index, src_root)
    return {
        declaration["owner_module"]
        for declaration in declarations
        if isinstance(declaration.get("owner_module"), str)
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Store registry inventory check")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate and exit non-zero on any failure (writes nothing)",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help=(
            "rewrite the baseline from the current tree; unreachable from the "
            "gate, and the resulting diff is the reviewed artifact"
        ),
    )
    parser.add_argument(
        "--json", metavar="PATH", help="also write the machine-readable report"
    )
    parser.add_argument("--baseline", metavar="PATH", default=str(_DEFAULT_BASELINE))
    parser.add_argument("--src-root", metavar="PATH", default=str(_DEFAULT_SRC_ROOT))
    args = parser.parse_args(argv)

    baseline_path = Path(args.baseline)
    src_root = Path(args.src_root)

    if args.update_baseline:
        index = build_symbol_index(src_root)
        detected = detect_stores(index)
        declared = _declared_modules_for_baseline(src_root, index)
        document, _ = load_baseline(baseline_path)
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            render_baseline(detected, declared, document), encoding="utf-8"
        )
        print(
            f"wrote {baseline_path.as_posix()}; review every row before committing"
        )
        return 0

    # Retaining the AST nodes for ~915 modules makes the cyclic collector
    # rescan them on every generation-2 pass. Scoped to the CLI and restored in
    # `finally` so an in-process caller's GC semantics are never changed.
    collecting = gc.isenabled()
    gc.disable()
    try:
        result = check(baseline_path=baseline_path, src_root=src_root)
    finally:
        if collecting:
            gc.enable()

    if args.json:
        Path(args.json).write_text(
            json.dumps(result.report, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )

    if result.errors:
        print(
            f"store registry check failed with {len(result.errors)} problem(s):",
            file=sys.stderr,
        )
        for problem in result.errors:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    report = result.report
    print(
        "store registry check passed ("
        f"declarations={report['declarations']}, "
        f"store modules={report['detected_store_modules']}, "
        f"undeclared={report['undeclared_store_modules']}, "
        f"baselined={report['baseline_rows']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
