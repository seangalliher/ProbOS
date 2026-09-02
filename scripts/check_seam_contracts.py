#!/usr/bin/env python
"""Validate the distributed seam contract catalog (AD-1270b, slice 1 of 3).

``docs/development/seams/*.yaml`` is the canonical P0 denominator for the
AD-1270 platform-maturity program. Nothing read it before this script, which
made it a text file: an ID could be deleted rather than tombstoned, and the
``seam_ids`` references that already live in the production declaration modules
could rot against it without any signal.

This is a **tool**, not runtime. AD-1270a's ``DECISIONS.md`` D6 fixed the
dependency direction as checker -> data, never runtime -> manifest, so nothing
under ``src/probos/`` reads, parses, or validates against the catalog. The
consequence is that ``CapabilityDeclaration.seam_ids`` stays opaque free text
and this script is the only thing that makes it a reference.

Usage::

    python scripts/check_seam_contracts.py --check
    python scripts/check_seam_contracts.py --check --require-crossing-tests
    python scripts/check_seam_contracts.py --check --json report.json

What fails today (default mode)
-------------------------------
1.  A ``*.yaml`` under the seams directory does not parse, or omits a required
    top-level key.
2.  An entry is missing a required field, or carries a bad ``tier`` / ``status``
    / ``evidence_status``.
3.  Two entries anywhere in ``seams`` + ``tombstones`` share an ``id``.
4.  An ``id`` does not match ``^(T[AB]-P0)-(\\d{3})-[a-z0-9-]+$``.
5.  A per-prefix ordinal gap, duplicate, or an ordinal above the declared
    ``id_allocation`` high-water mark.
6.  A tombstone missing ``rationale`` / ``replacement`` / ``decision`` / ``date``
    (ISO ``YYYY-MM-DD``).
7.  A ``producer_symbol`` / ``consumer_symbol`` that does not resolve against
    ``src/probos/``.
8.  An active Tier-A entry that is both ``symbol_status: unresolved`` and
    ``evidence_status: proven``.
9.  A ``seam_ids`` string in a declaration module that does not name an
    **active** manifest entry. Naming a tombstoned ID is a failure, not a
    warning -- the reference is dead either way.
10. A non-null ``crossing_test`` whose node ID does not collect. pytest exit 5
    (``EXIT_NOTESTSCOLLECTED``) counts as failure: uncollected is non-passing.
11. ``evidence_status: proven`` with ``crossing_test: null``.

What fails later
----------------
12. ``--require-crossing-tests``: any active Tier-A entry with
    ``crossing_test: null``. Ships here disabled so AD-1270b slice 3 fills node
    IDs and flips one default rather than writing enforcement under deadline.

Resolution is AST-only
----------------------
Symbols and ``seam_ids`` literals are read by walking ASTs, never by importing
from ``src/probos/`` (side effects, non-hermetic) and never by regex over source
text (a dotted path inside a docstring or a ``#`` comment would read as
resolved). This mirrors ``scripts/phantom_api_ast_helper.py``.

Honest bound on deletion detection
----------------------------------
The ``id_allocation`` high-water mark catches a *silent* deletion: the ordinals
in ``seams`` union ``tombstones`` must be exactly ``1..N`` per prefix, so
removing any entry -- including the highest -- opens a gap. It does **not** stop
a reviewer who deletes an entry *and* lowers ``N`` in the same commit. That is
deliberate: lowering ``N`` is a conspicuous line in a reviewed diff, which is
the "adding an ID is an explicit reviewed manifest change" property the program
asks for. Do not read this as tamper-proof.

Writes nothing under ``--check``. The gate wrapper fails the run if preflight
mutates the tree.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SEAMS_DIR = _REPO_ROOT / "docs" / "development" / "seams"
_DEFAULT_SRC_ROOT = _REPO_ROOT / "src"

#: Top-level keys every seam file must carry.
REQUIRED_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "schema_version",
    "manifest_id",
    "owner",
    "tracking_issue",
    "id_allocation",
    "rules",
    "seams",
    "tombstones",
)

#: Fields every ``seams`` entry must carry, regardless of tier.
REQUIRED_ENTRY_FIELDS: tuple[str, ...] = (
    "id",
    "tier",
    "status",
    "evidence_status",
    "owner",
    "producer",
    "consumer",
    "path",
    "crossing_test",
)

#: Additionally required on an active Tier-A entry. A null value is permitted
#: only under the ``symbol_status: unresolved`` escape hatch (D2).
REQUIRED_TIER_A_FIELDS: tuple[str, ...] = ("producer_symbol", "consumer_symbol")

#: Fields every ``tombstones`` entry must carry beyond ``id``.
REQUIRED_TOMBSTONE_FIELDS: tuple[str, ...] = (
    "rationale",
    "replacement",
    "decision",
    "date",
)

VALID_TIERS: frozenset[str] = frozenset({"A", "B"})
VALID_STATUSES: frozenset[str] = frozenset({"active", "retired"})
VALID_EVIDENCE_STATUSES: frozenset[str] = frozenset({"planned", "proven"})

_ID_RE = re.compile(r"^(T[AB]-P0)-(\d{3})-[a-z0-9-]+$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Symbol index cache, keyed by resolved src root. A single run resolves ~16
#: symbols plus the declaration modules against the same tree.
_INDEX_CACHE: dict[str, "SymbolIndex"] = {}


@dataclass(frozen=True)
class SymbolIndex:
    """Module-scope names and class methods under a source root.

    ``modules`` maps a dotted module path to its module-scope names (classes,
    functions, and assigned names). ``class_methods`` maps a dotted module path
    to each of its module-scope classes and that class's method names. No
    inheritance walk: a method inherited from a base class in another module
    does not resolve, which keeps a false *pass* impossible at the cost of some
    false failures a reviewer can see and fix.
    """

    modules: dict[str, set[str]] = field(default_factory=dict)
    class_methods: dict[str, dict[str, set[str]]] = field(default_factory=dict)


def _module_dotted_path(py_file: Path, src_root: Path) -> str | None:
    """Return the dotted module path for ``py_file``, or None if it is outside."""
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


def _tracked_python_files(src_root: Path) -> list[Path] | None:
    """Python files under ``src_root`` that git actually tracks.

    Resolution must not see untracked work. The canonical gate materializes
    ``HEAD`` into a fresh worktree, so a symbol satisfied by an uncommitted file
    passes locally and fails in the gate - the developer-local/gate seam this
    program exists to close. Returns ``None`` when git cannot answer, so the
    caller can fall back to a disk walk rather than silently index nothing.
    """
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.py"],
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
    stdout = completed.stdout or ""
    return [src_root / name for name in stdout.split("\0") if name]


def build_symbol_index(src_root: Path) -> SymbolIndex:
    """Build the module/class/method index for ``src_root`` by AST.

    Cached per resolved root. A file that does not parse is skipped rather than
    fatal: an unparseable source file is the ``compile`` preflight phase's
    failure to report, and duplicating it here would produce two errors for one
    defect.
    """
    cache_key = str(src_root.resolve())
    cached = _INDEX_CACHE.get(cache_key)
    if cached is not None:
        return cached

    index = SymbolIndex()
    if src_root.is_dir():
        tracked = _tracked_python_files(src_root)
        if tracked is None:
            print(
                f"warning: git could not enumerate {src_root}; falling back to "
                "a disk walk. Untracked files may satisfy symbol resolution "
                "here but not in the canonical gate.",
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
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
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
                        if isinstance(
                            child, (ast.FunctionDef, ast.AsyncFunctionDef)
                        )
                    } | {
                        target.id
                        for child in node.body
                        if isinstance(child, ast.Assign)
                        for target in child.targets
                        if isinstance(target, ast.Name)
                    } | {
                        child.target.id
                        for child in node.body
                        if isinstance(child, ast.AnnAssign)
                        and isinstance(child.target, ast.Name)
                    }
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(node.name)
                elif isinstance(node, ast.Assign):
                    names.update(
                        target.id
                        for target in node.targets
                        if isinstance(target, ast.Name)
                    )
                elif isinstance(node, ast.AnnAssign) and isinstance(
                    node.target, ast.Name
                ):
                    names.add(node.target.id)
            index.modules[dotted] = names
            index.class_methods[dotted] = classes

    _INDEX_CACHE[cache_key] = index
    return index


def resolve_symbol(dotted: str, index: SymbolIndex) -> str | None:
    """Return None when ``dotted`` resolves, else a reason string.

    Accepts ``module.Class``, ``module.Class.method``, and ``module.function``.
    A bare name is rejected outright: measured, a bare ``record_outcome``
    matches thirteen production definitions, so it resolves to everything, which
    is the same as resolving to nothing.
    """
    if not isinstance(dotted, str) or not dotted.strip():
        return "symbol is empty"
    parts = dotted.split(".")
    if len(parts) < 2:
        return (
            f"{dotted!r} is a bare name; symbols must be fully-qualified "
            "dotted paths (module.Class, module.Class.method, module.function)"
        )
    if any(not part for part in parts):
        return f"{dotted!r} is not a well-formed dotted path"

    # Longest module prefix first, so `probos.attachments.store.AttachmentStore`
    # binds to the `store` module rather than the `attachments` package. Stop at
    # a two-part remainder: nothing shorter can resolve, and trying anyway makes
    # `probos.no.such.module.Thing` report "nested too deep" when the real
    # problem is that no such module exists.
    shortest = max(1, len(parts) - 2)
    for split in range(len(parts) - 1, shortest - 1, -1):
        module = ".".join(parts[:split])
        remainder = parts[split:]
        if module not in index.modules:
            continue
        if len(remainder) == 1:
            if remainder[0] in index.modules[module]:
                return None
            return (
                f"module {module!r} exists but defines no module-scope "
                f"{remainder[0]!r}"
            )
        class_name, attribute = remainder
        methods = index.class_methods.get(module, {}).get(class_name)
        if methods is None:
            return f"module {module!r} defines no class {class_name!r}"
        if attribute in methods:
            return None
        return f"class {module}.{class_name} defines no {attribute!r}"
    return f"no module under src/ matches any prefix of {dotted!r}"


def declaration_modules(src_root: Path) -> tuple[str, ...]:
    """Read ``DECLARATION_MODULES`` from the maturity registry by AST.

    Reads the constant rather than calling ``load_default_registry()``, which
    would import production code and give this checker side effects.
    """
    registry = src_root / "probos" / "maturity" / "registry.py"
    if not registry.is_file():
        return ()
    try:
        tree = ast.parse(registry.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return ()
    for node in ast.walk(tree):
        target_names: list[str] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            target_names = [
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            ]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(
            node.target, ast.Name
        ):
            target_names = [node.target.id]
            value = node.value
        if "DECLARATION_MODULES" not in target_names or value is None:
            continue
        if isinstance(value, (ast.Tuple, ast.List)):
            return tuple(
                element.value
                for element in value.elts
                if isinstance(element, ast.Constant)
                and isinstance(element.value, str)
            )
    return ()


def declared_seam_ids(src_root: Path) -> dict[str, list[str]]:
    """Map each declaration module to the ``seam_ids`` strings it declares.

    AST-based on purpose: a regex over source text would match a seam ID inside
    a docstring or a ``#`` comment and report a dead reference as live.
    """
    found: dict[str, list[str]] = {}
    for dotted in declaration_modules(src_root):
        module_file = src_root / Path(*dotted.split(".")).with_suffix(".py")
        if not module_file.is_file():
            continue
        try:
            tree = ast.parse(module_file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        ids: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.keyword) or node.arg != "seam_ids":
                continue
            if isinstance(node.value, (ast.Tuple, ast.List)):
                ids.extend(
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                )
        if ids:
            found[dotted] = ids
    return found


def _collects(node_id: str, repo_root: Path) -> str | None:
    """Return None when ``node_id`` collects under pytest, else a reason.

    ``-o addopts=`` is mandatory: ``pyproject.toml`` sets
    ``addopts = "-n 16 --dist=loadfile"``, and inheriting it spawns sixteen
    xdist workers per node ID. Exit 5 (``EXIT_NOTESTSCOLLECTED``) is a failure
    -- a crossing test that collects nothing is not evidence.
    """
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-o",
                "addopts=",
                "-p",
                "no:cacheprovider",
                node_id,
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"could not run pytest --collect-only: {exc}"
    if completed.returncode == 0:
        return None
    if completed.returncode == 5:
        return "collected no tests (pytest exit 5); uncollected is non-passing"
    tail = (completed.stdout + completed.stderr).strip().splitlines()
    detail = tail[-1] if tail else "no output"
    return f"pytest --collect-only exited {completed.returncode}: {detail}"


def _load_seam_files(seams_dir: Path) -> tuple[list[tuple[Path, dict]], list[str]]:
    """Parse every ``*.yaml`` under ``seams_dir``.

    Loads every file rather than a hard-coded ``p0-manifest.yaml``: the program
    specifies ``seams/*.yaml``, and a fixed filename would silently ignore the
    second file the moment one is added.
    """
    errors: list[str] = []
    documents: list[tuple[Path, dict]] = []
    if not seams_dir.is_dir():
        return documents, [f"{seams_dir}: seams directory does not exist"]
    paths = sorted(seams_dir.glob("*.yaml"))
    if not paths:
        return documents, [f"{seams_dir}: contains no *.yaml seam manifest"]
    for path in paths:
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, UnicodeDecodeError, OSError) as exc:
            errors.append(f"{path.name}: does not parse as YAML: {exc}")
            continue
        if not isinstance(document, dict):
            errors.append(
                f"{path.name}: top level is {type(document).__name__}, "
                "expected a mapping"
            )
            continue
        documents.append((path, document))
    return documents, errors


def _check_entry_fields(
    label: str, entry: Any, errors: list[str]
) -> dict | None:
    """Validate one ``seams`` entry's required fields and enumerations."""
    if not isinstance(entry, dict):
        errors.append(
            f"{label}: entry is {type(entry).__name__}, expected a mapping"
        )
        return None
    entry_id = entry.get("id")
    where = f"{label}[{entry_id}]" if isinstance(entry_id, str) else label
    for required in REQUIRED_ENTRY_FIELDS:
        if required not in entry:
            errors.append(f"{where}: missing required field {required!r}")
    tier = entry.get("tier")
    if tier is not None and tier not in VALID_TIERS:
        errors.append(
            f"{where}: tier is {tier!r}, expected one of "
            f"{sorted(VALID_TIERS)}"
        )
    status = entry.get("status")
    if status is not None and status not in VALID_STATUSES:
        errors.append(
            f"{where}: status is {status!r}, expected one of "
            f"{sorted(VALID_STATUSES)}"
        )
    evidence = entry.get("evidence_status")
    if evidence is not None and evidence not in VALID_EVIDENCE_STATUSES:
        errors.append(
            f"{where}: evidence_status is {evidence!r}, expected one of "
            f"{sorted(VALID_EVIDENCE_STATUSES)}"
        )
    return entry


def _check_symbols(
    where: str, entry: dict, index: SymbolIndex, errors: list[str]
) -> None:
    """Enforce D2: fully-qualified symbols, or a declared unresolved gap."""
    is_active_tier_a = (
        entry.get("tier") == "A" and entry.get("status") == "active"
    )
    symbol_status = entry.get("symbol_status")
    if is_active_tier_a:
        for required in REQUIRED_TIER_A_FIELDS:
            if required not in entry:
                errors.append(
                    f"{where}: active Tier-A entry is missing required field "
                    f"{required!r} (use null plus symbol_status: unresolved "
                    "when no owning symbol exists)"
                )
    for key in REQUIRED_TIER_A_FIELDS:
        if key not in entry:
            continue
        value = entry[key]
        if value is None:
            if symbol_status != "unresolved":
                errors.append(
                    f"{where}: {key} is null without symbol_status: "
                    "unresolved; do not leave a symbol blank silently"
                )
            elif not str(entry.get("symbol_note") or "").strip():
                errors.append(
                    f"{where}: symbol_status: unresolved requires a "
                    "non-empty symbol_note explaining why"
                )
            continue
        reason = resolve_symbol(value, index)
        if reason is not None:
            errors.append(f"{where}: {key} does not resolve -- {reason}")
    if (
        is_active_tier_a
        and symbol_status == "unresolved"
        and entry.get("evidence_status") == "proven"
    ):
        errors.append(
            f"{where}: symbol_status: unresolved cannot carry "
            "evidence_status: proven -- an unresolved seam has no owning "
            "symbol to have proven anything about"
        )


def _check_ordinals(
    label: str,
    allocation: Any,
    ordinals_by_prefix: dict[str, list[tuple[int, str]]],
    errors: list[str],
) -> None:
    """Enforce D4: per-prefix ordinals are exactly ``1..N``."""
    if not isinstance(allocation, dict):
        errors.append(
            f"{label}: id_allocation is {type(allocation).__name__}, "
            "expected a mapping of prefix to high-water mark"
        )
        return
    for prefix in sorted(ordinals_by_prefix):
        if prefix not in allocation:
            errors.append(
                f"{label}: prefix {prefix!r} is used by an entry but has no "
                "id_allocation high-water mark"
            )
    for prefix, high_water in sorted(allocation.items()):
        if not isinstance(high_water, int) or isinstance(high_water, bool):
            errors.append(
                f"{label}: id_allocation[{prefix!r}] is "
                f"{high_water!r}, expected an integer"
            )
            continue
        if high_water < 0:
            errors.append(
                f"{label}: id_allocation[{prefix!r}] is negative"
            )
            continue
        seen = ordinals_by_prefix.get(prefix, [])
        counts: dict[int, list[str]] = {}
        for ordinal, entry_id in seen:
            counts.setdefault(ordinal, []).append(entry_id)
        for ordinal in sorted(counts):
            if len(counts[ordinal]) > 1:
                errors.append(
                    f"{label}: prefix {prefix!r} allocates ordinal "
                    f"{ordinal:03d} more than once: "
                    f"{sorted(counts[ordinal])}"
                )
        above = sorted(o for o in counts if o > high_water)
        if above:
            errors.append(
                f"{label}: prefix {prefix!r} has ordinals above the "
                f"id_allocation high-water mark {high_water}: "
                f"{[f'{o:03d}' for o in above]}; bump id_allocation in the "
                "same reviewed change that adds the ID"
            )
        missing = sorted(
            ordinal
            for ordinal in range(1, high_water + 1)
            if ordinal not in counts
        )
        if missing:
            errors.append(
                f"{label}: prefix {prefix!r} is missing ordinals "
                f"{[f'{o:03d}' for o in missing]} below the id_allocation "
                f"high-water mark {high_water}; an ID that is no longer "
                "active belongs in tombstones, not deleted"
            )


def validate(
    *,
    seams_dir: Path = _DEFAULT_SEAMS_DIR,
    src_root: Path = _DEFAULT_SRC_ROOT,
    repo_root: Path = _REPO_ROOT,
    require_crossing_tests: bool = False,
) -> list[str]:
    """Validate every seam manifest under ``seams_dir``.

    Returns every failure found, in file order, rather than the first: a
    checker that reports one problem per run costs one gate cycle per problem.
    An empty list means the catalog is valid.
    """
    documents, errors = _load_seam_files(seams_dir)
    index = build_symbol_index(src_root)

    active_ids: set[str] = set()
    tombstoned_ids: set[str] = set()
    seen_ids: dict[str, str] = {}

    for path, document in documents:
        label = path.name
        for required in REQUIRED_TOP_LEVEL_KEYS:
            if required not in document:
                errors.append(
                    f"{label}: missing required top-level key {required!r}"
                )

        ordinals_by_prefix: dict[str, list[tuple[int, str]]] = {}

        def _register_id(entry_id: Any, where: str) -> None:
            if not isinstance(entry_id, str):
                errors.append(
                    f"{where}: id is {type(entry_id).__name__}, expected a "
                    "string"
                )
                return
            previous = seen_ids.get(entry_id)
            if previous is not None:
                errors.append(
                    f"{where}: id {entry_id!r} is already declared in "
                    f"{previous}; ids must be unique across seams and "
                    "tombstones in every file"
                )
            else:
                seen_ids[entry_id] = where
            match = _ID_RE.match(entry_id)
            if match is None:
                errors.append(
                    f"{where}: id {entry_id!r} does not match "
                    f"{_ID_RE.pattern}"
                )
                return
            prefix, ordinal = match.group(1), int(match.group(2))
            ordinals_by_prefix.setdefault(prefix, []).append(
                (ordinal, entry_id)
            )

        seams = document.get("seams")
        if seams is None:
            seams = []
        if not isinstance(seams, list):
            errors.append(
                f"{label}: seams is {type(seams).__name__}, expected a list"
            )
            seams = []
        for position, raw_entry in enumerate(seams):
            entry = _check_entry_fields(f"{label}:seams[{position}]", raw_entry, errors)
            if entry is None:
                continue
            entry_id = entry.get("id")
            where = (
                f"{label}[{entry_id}]"
                if isinstance(entry_id, str)
                else f"{label}:seams[{position}]"
            )
            _register_id(entry_id, where)
            if isinstance(entry_id, str) and entry.get("status") == "active":
                active_ids.add(entry_id)
            _check_symbols(where, entry, index, errors)

            crossing_test = entry.get("crossing_test")
            blank_crossing_test = (
                isinstance(crossing_test, str) and not crossing_test.strip()
            )
            if blank_crossing_test:
                # Present-but-blank is malformed input, not "no test declared".
                # Treating it as absent would let it slip through slice 1 and
                # only surface when --require-crossing-tests is turned on.
                errors.append(
                    f"{where}: crossing_test is present but blank; use null to "
                    "declare no crossing test yet, or a pytest node ID"
                )
            if entry.get("evidence_status") == "proven" and not crossing_test:
                errors.append(
                    f"{where}: evidence_status: proven with no crossing_test; "
                    "a missing crossing test is not passing evidence"
                )
            if crossing_test and not blank_crossing_test:
                if not isinstance(crossing_test, str):
                    errors.append(
                        f"{where}: crossing_test is "
                        f"{type(crossing_test).__name__}, expected a pytest "
                        "node ID string or null"
                    )
                else:
                    reason = _collects(crossing_test, repo_root)
                    if reason is not None:
                        errors.append(
                            f"{where}: crossing_test {crossing_test!r} "
                            f"{reason}"
                        )
            elif (
                require_crossing_tests
                and entry.get("tier") == "A"
                and entry.get("status") == "active"
            ):
                errors.append(
                    f"{where}: active Tier-A entry has crossing_test: null "
                    "and --require-crossing-tests is set"
                )

        tombstones = document.get("tombstones")
        if tombstones is None:
            tombstones = []
        if not isinstance(tombstones, list):
            errors.append(
                f"{label}: tombstones is {type(tombstones).__name__}, "
                "expected a list"
            )
            tombstones = []
        for position, raw_entry in enumerate(tombstones):
            where = f"{label}:tombstones[{position}]"
            if not isinstance(raw_entry, dict):
                errors.append(
                    f"{where}: tombstone is {type(raw_entry).__name__}, "
                    "expected a mapping"
                )
                continue
            entry_id = raw_entry.get("id")
            if isinstance(entry_id, str):
                where = f"{label}[{entry_id}]"
                tombstoned_ids.add(entry_id)
            _register_id(entry_id, where)
            for required in REQUIRED_TOMBSTONE_FIELDS:
                value = raw_entry.get(required)
                if value is None or not str(value).strip():
                    errors.append(
                        f"{where}: tombstone is missing required field "
                        f"{required!r}"
                    )
            date = raw_entry.get("date")
            if (
                date is not None
                and str(date).strip()
                and not _ISO_DATE_RE.match(str(date))
            ):
                errors.append(
                    f"{where}: tombstone date {date!r} is not ISO YYYY-MM-DD"
                )

        _check_ordinals(
            label, document.get("id_allocation"), ordinals_by_prefix, errors
        )

    for module, ids in sorted(declared_seam_ids(src_root).items()):
        for seam_id in ids:
            if seam_id in active_ids:
                continue
            if seam_id in tombstoned_ids:
                errors.append(
                    f"{module}: seam_ids references {seam_id!r}, which is "
                    "tombstoned; update the declaration in the same change "
                    "that retires the seam"
                )
            else:
                errors.append(
                    f"{module}: seam_ids references {seam_id!r}, which names "
                    "no active manifest entry"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate and exit non-zero on any failure (writes nothing)",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="also write the failure list to PATH as JSON",
    )
    parser.add_argument(
        "--require-crossing-tests",
        action="store_true",
        help=(
            "additionally fail when an active Tier-A entry has no "
            "crossing_test node ID (AD-1270b slice 3 flips this default)"
        ),
    )
    parser.add_argument(
        "--seams-dir",
        metavar="PATH",
        default=str(_DEFAULT_SEAMS_DIR),
        help="directory of *.yaml seam manifests",
    )
    args = parser.parse_args()

    errors = validate(
        seams_dir=Path(args.seams_dir),
        require_crossing_tests=args.require_crossing_tests,
    )

    if args.json:
        Path(args.json).write_text(
            json.dumps({"errors": errors}, indent=2) + "\n", encoding="utf-8"
        )

    if errors:
        print(
            f"seam contract check failed with {len(errors)} problem(s):",
            file=sys.stderr,
        )
        for problem in errors:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print("seam contract check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
