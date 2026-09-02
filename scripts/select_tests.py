#!/usr/bin/env python
"""Fail-broad impact selection in shadow mode (AD-1270f, slice 1 of N).

The canonical gate is ~15.4 minutes over 26,340 nodes. Running it after every
small issue caps throughput, but filename-only selection cannot see fixtures,
dynamic imports, indirect consumers or seam contracts, so it buys speed with
false confidence.

This script is an **acceleration tool with no release authority whatsoever.**
It never shortens, replaces, gates, or reorders the canonical full run; it has
no preflight phase; it does not touch the frozen gate's collected node set.
Only a validated success receipt from ``scripts/run_test_gate.py`` is release
authority. ``--select`` output is advisory and no workflow may consume it as
evidence.

Promotion condition (write it here so it cannot be quietly dropped)
------------------------------------------------------------------
The selector may stop being shadow-only when **all** hold:

1. the enrollment series reaches 20 eligible rows with zero detected misses;
2. the historical BF mutation corpus is predeclared, hashed, and scores zero
   misses; and
3. a Captain-ratified decision records the change.

**None of those are met.** The 20-run series cannot complete in one session --
it needs 20 distinct eligible source-changing tree fingerprints recorded after
the declared cutoff. This slice ships the enrollment header and the machinery.
Any text describing the series, the BF corpus, the p95 leaf-feedback figure, or
the "zero misses" acceptance as complete is false.

Usage::

    python scripts/select_tests.py --capture-map            # out of band, on demand
    python scripts/select_tests.py --select
    python scripts/select_tests.py --shadow
    python scripts/select_tests.py --declare-enrollment
    python scripts/select_tests.py --check
    python scripts/select_tests.py --gate-balance COLLECTION JUNIT

Fail broad on doubt
-------------------
Every rule in :data:`FAIL_BROAD_RULES` promotes the verdict to ``fail-broad``,
which means *run the whole suite*. Rules accumulate: one run reports every rule
that fired, never just the first. An empty measurement -- git unable to answer,
a map that will not parse, a collection artifact that will not load -- means
fail-broad, never "select nothing".

What this does NOT catch
------------------------
1.  **Parametrized tests collapse to one coverage context.** Measured on this
    tree: of 414 non-empty contexts, 0 carried a ``[param]`` suffix, and 4
    contexts fanned out to 8, 16 and 4 collected nodes. Fan-out is conservative
    -- one context selects every parameterisation -- so this is safety, not
    precision.
2.  **A test that executes no measured line produces no context.** Measured:
    466 tests executed, 441 nodes reachable from contexts, **25 tests had no
    context at all**. Those nodes are recorded in the map's
    ``uncontexted_tests`` census and are **unconditionally selected on every
    run**; a collected node that is in neither the resolved set nor that census
    fires ``uncontexted-test``. Scoping the rule to *unaccounted* nodes rather
    than to *uncontexted* ones is deliberate: the literal reading is
    permanently on against any real map, and a rule that never turns off is not
    a safety property, it is a broken selector that merely looks safe.
3.  **Context to node-ID translation is a translation, and translations rot.**
    Contexts render dotted (``tests.test_builder_agent.TestAct.test_x``) while
    the gate speaks node IDs (``tests/test_builder_agent.py::TestAct::test_x``).
    Verified against the live 26,340-node collection: 414 of 414 non-empty
    contexts resolved to at least one collected node, 0 unresolvable. A context
    that resolves to nothing fails broad; it is never silently dropped.
4.  **Static AST only, never regex over source text.** A dotted path inside a
    docstring or a ``#`` comment must not read as behaviour. Callees are
    canonicalised through a per-module import-alias map, because
    ``from importlib import import_module`` renders a bare name with no
    attribute node at all. A binding rebound at runtime, or a helper that wraps
    an import, is still not seen.
5.  **Untracked files are invisible by construction**, because the file index
    comes from ``git ls-files``. That is the point: the canonical gate
    materializes ``HEAD``, so anything satisfied by uncommitted work would pass
    locally and fail in the gate.
6.  **Coverage sees executed lines, not files opened.** A changed ``.yaml``,
    ``.md`` or ``.json`` that a test reads produces no context anywhere -- 101
    of this repository's 1,441 test files reference ``docs/``, ``config/`` or
    ``.yaml`` paths. So ``unknown-module`` is scoped **broader** than the
    program's literal wording: any changed path the map can neither measure nor
    resolve as a test file fails broad, and an empty selection for a non-empty
    change set fails broad by construction. Measured on the live tree: the
    three doc-only edits present during this build selected **0 of 26,340**
    nodes before that widening, which is the exact miss shape the ledger would
    have recorded as a clean ``selected`` verdict.
7.  **The 1.74x coverage multiplier is a 466-node subset figure**, not a
    suite-wide measurement. Coverage overhead scales with executed bytecode,
    not wall time.
8.  **``--gate-balance`` measures, it does not rebalance.** Under
    ``--dist=loadfile`` the imbalance is a duration property of file grouping,
    not of any single large file, so per-worker node counts alone understate
    it. This slice changes no distribution.

Writes nothing in ``--select``, ``--check`` and ``--gate-balance``. ``--shadow``
writes exactly two artifacts of its own -- the bulky record under the ignored
``logs/gates/shadow/`` and one appended line in the tracked ledger -- and never
edits source, tests, or configuration. ``--capture-map`` runs an instrumented
suite out of band and writes only its map; it is never invoked by
``run_test_gate.py`` and must never be, because coverage instrumentation
measured **1.74x** on a 466-node subset, which extrapolates to roughly +11
minutes on release authority.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SEAMS_DIR = _REPO_ROOT / "docs" / "development" / "seams"
_DEFAULT_LEDGER = (
    _REPO_ROOT / "docs" / "development" / "test-selection-shadow-ledger.jsonl"
)
_DEFAULT_ARTIFACT_DIR = _REPO_ROOT / "logs" / "gates"

#: Bumped when the map payload shape changes. A drift fires ``map-schema``.
SCHEMA_VERSION = 1

#: Bumped when selection semantics change in a way that invalidates an existing
#: map. A map captured by a different selector cannot be trusted to mean the
#: same thing, so a mismatch fires ``map-schema`` rather than being tolerated.
SELECTOR_VERSION = "ad-1270f.1"

#: Bumped when the capture procedure changes (coverage configuration, context
#: mode, measured roots).
MAP_VERSION = "1"

LEDGER_SCHEMA_VERSION = 1
SERIES_NAME = "selector-shadow-v1"
TARGET_RUNS = 20

#: Every fail-broad rule ID, the single source of truth. ``tests/
#: test_ad1270f_impact_selector.py`` asserts that this set equals the set of
#: IDs covered by firing tests, so adding a rule without a firing test fails
#: the suite.
#:
#: ``uncontexted-test`` covers the three ways the selector can fail to enumerate
#: the tests it is responsible for including: a collected node accounted for
#: neither by a resolved context nor by the map's uncontexted census; a map
#: context that resolves to no collected node; and a seam manifest whose
#: ``crossing_test`` values cannot be read. All three mean the same thing --
#: there are tests the selector cannot see -- so they share one ID.
FAIL_BROAD_RULES: tuple[str, ...] = (
    "map-missing",
    "map-schema",
    "map-base-unknown",
    "map-not-ancestor",
    "map-tree-mismatch",
    "change-deleted",
    "change-renamed",
    "blast-radius",
    "unknown-module",
    "dynamic-import",
    "uncontexted-test",
    "selector-self-change",
)

#: ``fnmatch`` patterns over repo-relative POSIX paths. ``fnmatch`` ``*``
#: crosses ``/``, which is what makes these globs the deliberately broader
#: choice: ``src/probos/*protocol*.py`` covers ``src/probos/protocols.py`` and
#: every per-domain ``discovery/protocol.py`` alike. Any uncertainty selects
#: more tests, never fewer. Root ``conftest.py`` and ``requirements*.txt`` do
#: not exist on this tree today; they are globs rather than literals so one
#: appearing later is caught without a code change.
BLAST_RADIUS_PATTERNS: tuple[str, ...] = (
    "src/probos/runtime.py",
    "src/probos/startup/*",
    "src/probos/config.py",
    "src/probos/config_profiles.py",
    "config/profiles/*",
    "src/probos/types.py",
    "src/probos/*protocol*.py",
    "src/probos/*event*.py",
    "pyproject.toml",
    "requirements*.txt",
    "*conftest.py",
    "scripts/run_test_gate.py",
    "scripts/_gate_pytest_plugin.py",
    "scripts/_gate_process_supervisor.py",
)

#: Changing the selector, its map, its ledger, or its own tests invalidates any
#: claim the selector makes about that same tree.
SELECTOR_SELF_PATTERNS: tuple[str, ...] = (
    "scripts/select_tests.py",
    "tests/test_ad1270f_impact_selector.py",
    "docs/development/test-selection-shadow-ledger.jsonl",
    "logs/gates/testmap-*.json",
)

#: Canonical dynamic-import callees, compared after alias canonicalisation.
DYNAMIC_IMPORT_CALLEES: frozenset[str] = frozenset(
    {"importlib.import_module", "__import__"}
)

_MEASURED_SOURCE_PREFIX = "src/probos/"


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def node_digest(values: Sequence[str]) -> str:
    """Digest of a node sequence, byte-identical to the gate's ``_node_digest``.

    Same shape as ``_digest`` in ``scripts/_gate_pytest_plugin.py``: a JSON dump
    of the tuple with ``ensure_ascii=True`` and ``separators=(",", ":")``. This
    is what makes a later miss recomputable rather than merely assertable.
    """
    payload = json.dumps(
        tuple(values), ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256(payload)


def _git(
    repo_root: Path, *arguments: str
) -> subprocess.CompletedProcess[str] | None:
    """Run git, returning ``None`` when it cannot be executed at all.

    ``check=False``: several callers treat a nonzero exit as the answer
    (``merge-base --is-ancestor`` exits 1 for "not an ancestor"), so raising
    would discard the measurement.
    """
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return None


def _git_text(repo_root: Path, *arguments: str) -> str | None:
    completed = _git(repo_root, *arguments)
    if completed is None or completed.returncode != 0:
        return None
    return completed.stdout.strip()


def tracked_files(repo_root: Path, *patterns: str) -> list[str] | None:
    """Repo-relative POSIX names git tracks, or ``None`` when git cannot answer.

    ``None`` rather than ``[]`` so the caller degrades loudly. For this script
    an empty measurement must mean fail-broad; reading it as "nothing to
    select" is the worst available failure mode.
    """
    completed = _git(repo_root, "ls-files", "-z", "--", *patterns)
    if completed is None or completed.returncode != 0:
        return None
    return sorted(
        name.replace("\\", "/") for name in (completed.stdout or "").split("\0") if name
    )


def tree_fingerprint(repo_root: Path) -> str | None:
    """SHA-256 over canonical status lines plus the staged diff.

    The receipt idiom from ``run_test_gate.py``: it identifies *this tree*, not
    a timestamp, so a same-tree retry is detectable and cannot pad the sample.
    """
    status = _git(
        repo_root, "status", "--porcelain=v1", "--untracked-files=all"
    )
    staged = _git(repo_root, "diff", "--cached", "--binary", "--no-ext-diff")
    if status is None or status.returncode != 0:
        return None
    if staged is None or staged.returncode != 0:
        return None
    canonical = "\n".join((status.stdout or "").splitlines()).encode("utf-8")
    return _sha256(canonical + b"\0" + (staged.stdout or "").encode("utf-8"))


# ---------------------------------------------------------------------------
# Context <-> node-ID translation
# ---------------------------------------------------------------------------


def context_for_node(node_id: str) -> str | None:
    """Dotted coverage context for a pytest node ID, or ``None``.

    ``tests/test_builder_agent.py::TestAct::test_x[1]`` becomes
    ``tests.test_builder_agent.TestAct.test_x``. The ``[param]`` suffix is
    dropped because ``dynamic_context = test_function`` names the function, not
    the parameterisation -- so every parameterisation of a test shares one
    context and one context selects all of them.
    """
    path, separator, rest = node_id.replace("\\", "/").partition("::")
    if not separator or not path.endswith(".py") or not rest:
        return None
    dotted = path[: -len(".py")].replace("/", ".")
    tail = rest.split("[")[0].replace("::", ".")
    if not tail:
        return None
    return f"{dotted}.{tail}"


def build_context_index(nodes: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """Map each context to every collected node that resolves to it (fan-out)."""
    index: dict[str, list[str]] = {}
    for node in nodes:
        context = context_for_node(node)
        if context is None:
            continue
        index.setdefault(context, []).append(node)
    return {context: tuple(sorted(found)) for context, found in index.items()}


# ---------------------------------------------------------------------------
# Change set
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChangeEntry:
    """One line of ``git diff --name-status --find-renames -M``."""

    status: str
    raw_status: str
    path: str
    old_path: str | None = None


def changed_entries(
    repo_root: Path, base: str
) -> tuple[tuple[ChangeEntry, ...], tuple[str, ...]]:
    """Changes between ``base`` and the working tree, plus any hard errors."""
    completed = _git(
        repo_root, "diff", "--name-status", "--find-renames", "-M", "-z", base
    )
    if completed is None or completed.returncode != 0:
        detail = "git is unavailable" if completed is None else completed.stderr.strip()
        return (), (f"git diff against {base} failed: {detail or 'unknown error'}",)

    fields = [item for item in (completed.stdout or "").split("\0") if item]
    entries: list[ChangeEntry] = []
    index = 0
    while index < len(fields):
        raw_status = fields[index]
        letter = raw_status[:1]
        index += 1
        if letter in {"R", "C"}:
            if index + 1 >= len(fields):
                break
            old_path = fields[index].replace("\\", "/")
            new_path = fields[index + 1].replace("\\", "/")
            index += 2
            entries.append(ChangeEntry(letter, raw_status, new_path, old_path))
        else:
            if index >= len(fields):
                break
            path = fields[index].replace("\\", "/")
            index += 1
            entries.append(ChangeEntry(letter, raw_status, path))
    return tuple(sorted(entries, key=lambda item: (item.path, item.status))), ()


def changed_paths(entries: Sequence[ChangeEntry]) -> tuple[str, ...]:
    """Every path a change touches, including the source side of a rename."""
    paths: set[str] = set()
    for entry in entries:
        paths.add(entry.path)
        if entry.old_path:
            paths.add(entry.old_path)
    return tuple(sorted(paths))


def matches_any(path: str, patterns: Sequence[str]) -> str | None:
    """The first pattern matching ``path``, or ``None``."""
    for pattern in patterns:
        if fnmatch.fnmatchcase(path, pattern):
            return pattern
    return None


# ---------------------------------------------------------------------------
# Dynamic-import detection (AST only)
# ---------------------------------------------------------------------------


def import_aliases(tree: ast.AST) -> dict[str, str]:
    """Map every imported binding to its canonical dotted name.

    Without this an attribute-only matcher is walked straight through by
    ordinary import style: ``from importlib import import_module`` renders a
    bare ``import_module`` with no attribute node at all. Collected in a
    pre-pass because a function-level import may sit below the call it binds.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def render_callee(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = render_callee(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def canonical_callee(rendered: str, aliases: dict[str, str]) -> str:
    """Rewrite through ``aliases`` so equivalent import styles compare equal."""
    if not rendered:
        return rendered
    head, _, tail = rendered.partition(".")
    target = aliases.get(head)
    if target is None:
        return rendered
    return f"{target}.{tail}" if tail else target


def dynamic_import_sites(source: str, path: str) -> list[str]:
    """Non-constant ``import_module`` / ``__import__`` call sites in ``source``.

    A constant argument is a static import the map already sees. A computed one
    is a dependency edge no static index can follow, which is precisely the
    class filename-only selection gets wrong.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # An unparseable file is the ``compile`` preflight phase's failure to
        # report; duplicating it here would produce two errors for one defect.
        # Fail broad rather than silently treating it as clean.
        return [f"{path}: could not be parsed"]
    aliases = import_aliases(tree)
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = canonical_callee(render_callee(node.func), aliases)
        if callee not in DYNAMIC_IMPORT_CALLEES:
            continue
        first = node.args[0] if node.args else None
        if first is None or not isinstance(first, ast.Constant):
            findings.append(f"{path}:{node.lineno}: {callee}(...) on a non-constant")
    return findings


# ---------------------------------------------------------------------------
# Seam manifest input
# ---------------------------------------------------------------------------


def seam_crossing_tests(seams_dir: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Every non-null ``crossing_test`` node ID, plus any read errors.

    On this tree the input is empty by design -- all 8 ``crossing_test`` values
    in ``docs/development/seams/p0-manifest.yaml`` are ``null`` because
    AD-1270b slice 3 has not shipped. A rule whose input is empty looks
    identical to a rule that works, so the union path is proven against a
    fixture manifest carrying non-null values, not against the live one.
    """
    if not seams_dir.is_dir():
        return (), (f"{seams_dir.as_posix()}: seams directory does not exist",)
    found: set[str] = set()
    errors: list[str] = []
    for path in sorted(seams_dir.glob("*.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"{path.name}: unreadable seam manifest: {exc}")
            continue
        if not isinstance(document, dict):
            errors.append(f"{path.name}: seam manifest is not a mapping")
            continue
        entries = document.get("seams")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            crossing = entry.get("crossing_test")
            if isinstance(crossing, str) and crossing.strip():
                found.add(crossing.strip())
            elif crossing is not None and not isinstance(crossing, str):
                errors.append(
                    f"{path.name}: crossing_test is not a string: {crossing!r}"
                )
    return tuple(sorted(found)), tuple(errors)


# ---------------------------------------------------------------------------
# The per-test map
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TestMap:
    """A captured coverage map, bound to the tree identity it was captured on."""

    schema_version: int
    selector_version: str
    map_version: str
    base_commit: str
    base_tree: str
    contexts: dict[str, tuple[str, ...]]
    measured_files: tuple[str, ...]
    uncontexted_tests: tuple[str, ...]

    def files_to_contexts(self) -> dict[str, tuple[str, ...]]:
        reverse: dict[str, list[str]] = {}
        for context, files in self.contexts.items():
            for name in files:
                reverse.setdefault(name, []).append(context)
        return {name: tuple(sorted(found)) for name, found in reverse.items()}


def load_map(path: Path) -> tuple[TestMap | None, list[str]]:
    """Parse a map file. Any failure is a ``map-missing`` input, never a crash."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"{path.as_posix()}: unreadable test map: {exc}"]
    if not isinstance(payload, dict):
        return None, [f"{path.as_posix()}: test map is not a JSON object"]
    contexts_raw = payload.get("contexts")
    if not isinstance(contexts_raw, dict):
        return None, [f"{path.as_posix()}: test map has no contexts mapping"]
    contexts = {
        str(context): tuple(
            sorted(str(name).replace("\\", "/") for name in files)
        )
        for context, files in contexts_raw.items()
        if isinstance(files, list)
    }
    measured = payload.get("measured_files")
    uncontexted = payload.get("uncontexted_tests")
    return (
        TestMap(
            schema_version=payload.get("schema_version"),
            selector_version=str(payload.get("selector_version", "")),
            map_version=str(payload.get("map_version", "")),
            base_commit=str(payload.get("base_commit", "")),
            base_tree=str(payload.get("base_tree", "")),
            contexts=contexts,
            measured_files=tuple(
                sorted(str(name).replace("\\", "/") for name in measured)
            )
            if isinstance(measured, list)
            else (),
            uncontexted_tests=tuple(sorted(str(node) for node in uncontexted))
            if isinstance(uncontexted, list)
            else (),
        ),
        [],
    )


def validate_map(
    test_map: TestMap, repo_root: Path
) -> list[tuple[str, str]]:
    """Rule/detail pairs for every way ``test_map`` cannot be related to HEAD.

    A difference between ``base_tree`` and the current tree is **not** staleness
    -- it is the normal case and exactly what the selector is for. Staleness
    means the map cannot be *related* to this tree at all.
    """
    problems: list[tuple[str, str]] = []
    if (
        test_map.schema_version != SCHEMA_VERSION
        or test_map.selector_version != SELECTOR_VERSION
        or test_map.map_version != MAP_VERSION
    ):
        problems.append(
            (
                "map-schema",
                "map header drift: "
                f"schema={test_map.schema_version!r} (want {SCHEMA_VERSION!r}), "
                f"selector={test_map.selector_version!r} (want {SELECTOR_VERSION!r}), "
                f"map={test_map.map_version!r} (want {MAP_VERSION!r})",
            )
        )
    base = test_map.base_commit
    if not base:
        problems.append(("map-base-unknown", "map declares no base_commit"))
        return problems

    exists = _git(repo_root, "cat-file", "-e", f"{base}^{{commit}}")
    if exists is None or exists.returncode != 0:
        problems.append(
            ("map-base-unknown", f"base commit {base} is not present in this repository")
        )
        return problems

    ancestor = _git(repo_root, "merge-base", "--is-ancestor", base, "HEAD")
    if ancestor is None or ancestor.returncode != 0:
        problems.append(
            (
                "map-not-ancestor",
                f"base commit {base} is not an ancestor of HEAD "
                "(rebased or unrelated history)",
            )
        )

    declared = _git_text(repo_root, "rev-parse", f"{base}^{{tree}}")
    if declared is None:
        problems.append(
            ("map-tree-mismatch", f"could not resolve the tree of base commit {base}")
        )
    elif declared != test_map.base_tree:
        problems.append(
            (
                "map-tree-mismatch",
                f"base commit {base} has tree {declared}, map declares "
                f"{test_map.base_tree or '<empty>'}",
            )
        )
    return problems


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectionResult:
    verdict: str
    reasons: tuple[str, ...]
    details: tuple[str, ...]
    nodes: tuple[str, ...]
    full_nodes: tuple[str, ...]
    changed: tuple[ChangeEntry, ...] = ()
    base_commit: str = ""

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return changed_paths(self.changed)

    def to_report(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "selector_version": SELECTOR_VERSION,
            "map_version": MAP_VERSION,
            "verdict": self.verdict,
            "reasons": list(self.reasons),
            "details": list(self.details),
            "base_commit": self.base_commit,
            "changed_path_count": len(self.changed_paths),
            "changed_paths": list(self.changed_paths),
            "selected": {
                "node_count": len(self.nodes),
                "nodes_sha256": node_digest(self.nodes),
            },
            "full": {
                "node_count": len(self.full_nodes),
                "nodes_sha256": node_digest(self.full_nodes),
            },
        }


def load_collection(path: Path) -> tuple[tuple[str, ...], list[str]]:
    """Collected node IDs from a shipped gate collection artifact."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (), [f"{path.as_posix()}: unreadable collection artifact: {exc}"]
    nodes = payload.get("collected_nodeids") if isinstance(payload, dict) else None
    if not isinstance(nodes, list) or not all(isinstance(node, str) for node in nodes):
        return (), [f"{path.as_posix()}: collection artifact has no collected_nodeids"]
    return tuple(sorted(nodes)), []


def latest_artifact(directory: Path, suffix: str) -> Path | None:
    """Newest artifact by name. Names are timestamp-prefixed, so name order is
    time order and the choice is deterministic without stat calls."""
    if not directory.is_dir():
        return None
    candidates = sorted(directory.glob(f"*{suffix}"))
    return candidates[-1] if candidates else None


def select(
    *,
    repo_root: Path,
    test_map: TestMap | None,
    map_errors: Sequence[str],
    full_nodes: Sequence[str],
    seams_dir: Path,
    base: str | None = None,
) -> SelectionResult:
    """Select tests for the current tree, accumulating every fail-broad reason."""
    reasons: set[str] = set()
    details: list[str] = []
    full = tuple(sorted(full_nodes))

    if test_map is None:
        reasons.add("map-missing")
        details.extend(map_errors or ["no usable test map"])
        return SelectionResult(
            verdict="fail-broad",
            reasons=tuple(sorted(reasons)),
            details=tuple(details),
            nodes=full,
            full_nodes=full,
            base_commit=base or "",
        )

    for rule, detail in validate_map(test_map, repo_root):
        reasons.add(rule)
        details.append(f"{rule}: {detail}")

    base_ref = base or test_map.base_commit
    entries: tuple[ChangeEntry, ...] = ()
    if "map-base-unknown" in reasons:
        details.append("change set not computed: the map's base commit is unknown")
    else:
        entries, diff_errors = changed_entries(repo_root, base_ref)
        if diff_errors:
            # An empty measurement must not read as "nothing changed".
            reasons.update({"change-deleted", "change-renamed"})
            details.extend(diff_errors)

    for entry in entries:
        if entry.status == "D":
            reasons.add("change-deleted")
            details.append(f"change-deleted: {entry.path}")
        elif entry.status in {"R", "C"}:
            reasons.add("change-renamed")
            details.append(
                f"change-renamed: {entry.old_path} -> {entry.path} ({entry.raw_status})"
            )

    paths = changed_paths(entries)
    for path in paths:
        pattern = matches_any(path, BLAST_RADIUS_PATTERNS)
        if pattern is not None:
            reasons.add("blast-radius")
            details.append(f"blast-radius: {path} matches {pattern}")
        self_pattern = matches_any(path, SELECTOR_SELF_PATTERNS)
        if self_pattern is not None:
            reasons.add("selector-self-change")
            details.append(f"selector-self-change: {path} matches {self_pattern}")

    measured = set(test_map.measured_files)
    # Broader than the program's literal wording ("a changed src/probos/**.py
    # module absent from the measured set"), deliberately. Coverage measures
    # executed lines, not files opened, so a changed `.yaml` or `.md` that 101
    # of this repository's test files read is invisible to every context -- and
    # the observable result would be a "selected" verdict with zero nodes, the
    # worst shape this tool can emit. A changed path is relatable only when the
    # map measures it, or when it is a test file whose own nodes are selectable.
    for path in paths:
        if path in measured:
            continue
        if path.startswith("tests/") and path.endswith(".py"):
            continue
        reasons.add("unknown-module")
        if path.startswith(_MEASURED_SOURCE_PREFIX) and path.endswith(".py"):
            details.append(f"unknown-module: {path} is absent from the map")
        else:
            details.append(
                f"unknown-module: {path} cannot be related to any test by the map"
            )

    for entry in entries:
        if entry.status == "D" or not entry.path.endswith(".py"):
            continue
        source_path = repo_root / entry.path
        try:
            source = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            reasons.add("dynamic-import")
            details.append(f"dynamic-import: {entry.path} could not be read: {exc}")
            continue
        for finding in dynamic_import_sites(source, entry.path):
            reasons.add("dynamic-import")
            details.append(f"dynamic-import: {finding}")

    context_index = build_context_index(full)
    resolved: set[str] = set()
    unresolvable: list[str] = []
    for context in sorted(test_map.contexts):
        nodes = context_index.get(context)
        if not nodes:
            unresolvable.append(context)
        else:
            resolved.update(nodes)
    known_uncontexted = set(test_map.uncontexted_tests)
    unaccounted = sorted(set(full) - resolved - known_uncontexted)
    if unresolvable:
        reasons.add("uncontexted-test")
        details.append(
            "uncontexted-test: "
            f"{len(unresolvable)} map context(s) resolve to no collected node, "
            f"first={unresolvable[0]}"
        )
    if unaccounted:
        reasons.add("uncontexted-test")
        details.append(
            "uncontexted-test: "
            f"{len(unaccounted)} collected node(s) are in neither the resolved set "
            f"nor the map's uncontexted census, first={unaccounted[0]}"
        )

    crossing, seam_errors = seam_crossing_tests(seams_dir)
    if seam_errors:
        # Unreadable crossing tests are tests the selector cannot enumerate,
        # which is the same failure the rule already covers in two directions.
        reasons.add("uncontexted-test")
        details.extend(
            f"uncontexted-test: seam manifest: {problem}" for problem in seam_errors
        )

    if reasons:
        return SelectionResult(
            verdict="fail-broad",
            reasons=tuple(sorted(reasons)),
            details=tuple(details),
            nodes=full,
            full_nodes=full,
            changed=entries,
            base_commit=base_ref,
        )

    full_set = set(full)
    files_to_contexts = test_map.files_to_contexts()
    selected: set[str] = set(known_uncontexted & full_set)
    selected.update(node for node in crossing if node in full_set)
    for path in paths:
        for context in files_to_contexts.get(path, ()):
            selected.update(context_index.get(context, ()))
        if path.endswith(".py"):
            selected.update(
                node for node in full if node.split("::", 1)[0] == path
            )

    if paths and not selected:
        # A real change that resolves to no test at all is not a fast run, it is
        # a selector that decided the change needs no evidence. Structurally
        # refuse to emit that shape.
        return SelectionResult(
            verdict="fail-broad",
            reasons=("unknown-module",),
            details=(
                *details,
                "unknown-module: "
                f"{len(paths)} changed path(s) resolved to zero tests; an empty "
                "selection for a non-empty change set is fail-broad by construction",
            ),
            nodes=full,
            full_nodes=full,
            changed=entries,
            base_commit=base_ref,
        )

    return SelectionResult(
        verdict="selected",
        reasons=(),
        details=tuple(details),
        nodes=tuple(sorted(selected)),
        full_nodes=full,
        changed=entries,
        base_commit=base_ref,
    )


# ---------------------------------------------------------------------------
# Map capture (out of band; never on the gate path)
# ---------------------------------------------------------------------------


def _pytest_base_command() -> list[str]:
    """Shared pytest flags. ``-o addopts=`` is mandatory: ``pyproject.toml``
    sets ``addopts = "-n 16 --dist=loadfile"``, and inheriting it spawns sixteen
    xdist workers per invocation."""
    return [
        "-q",
        "-n",
        "0",
        "-p",
        "no:randomly",
        "-p",
        "no:cacheprovider",
        "-o",
        "addopts=",
    ]


def _collect_nodes(repo_root: Path, targets: Sequence[str]) -> tuple[str, ...]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
            *targets,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    nodes = [
        line.strip()
        for line in (completed.stdout or "").splitlines()
        if "::" in line and not line.startswith(" ")
    ]
    return tuple(sorted(set(nodes)))


def capture_map(
    *, repo_root: Path, targets: Sequence[str], output: Path | None
) -> tuple[Path | None, list[str]]:
    """Run the instrumented suite out of band and write a map.

    **Never invoked by ``run_test_gate.py``.** Coverage instrumentation measured
    1.74x on a 466-node subset, which extrapolates to roughly +11 minutes on
    release authority; putting an acceleration tool on the critical path of the
    frozen gate is the exact boundary AD-1270f draws.

    ``tests`` must be inside the coverage ``source``: ``dynamic_context =
    test_function`` only labels a context when the *measured* frame is a test
    function, so restricting ``source`` to ``src/probos`` yields zero contexts.
    Measured on this tree -- 0 contexts with ``source = src/probos``, 202 with
    ``source = src/probos,tests``.
    """
    try:
        import coverage
    except ImportError:
        return None, ["coverage is not installed; cannot capture a test map"]

    head = _git_text(repo_root, "rev-parse", "HEAD")
    head_tree = _git_text(repo_root, "rev-parse", "HEAD^{tree}")
    if head is None or head_tree is None:
        return None, ["git could not resolve HEAD; refusing to capture an unbound map"]
    # The map is measured against the working tree but declares HEAD as its
    # base, and every staleness rule trusts that binding. Capturing on a dirty
    # tree would produce a map that passes validation while describing content
    # no commit contains -- undetectable afterwards, so it is refused here.
    dirty = _git(repo_root, "status", "--porcelain=v1", "--untracked-files=no")
    if dirty is None or dirty.returncode != 0:
        return None, ["git could not report worktree status; refusing to capture"]
    if dirty.stdout.strip():
        return None, [
            "refusing to capture a map on a dirty tree: the map would declare "
            f"base_commit {head[:12]} while measuring uncommitted content. "
            "Capture at a known-green commit."
        ]

    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="probos-testmap-") as scratch:
        scratch_dir = Path(scratch)
        data_file = scratch_dir / "cov.data"
        rc_file = scratch_dir / "coveragerc"
        rc_file.write_text(
            "[run]\n"
            "branch = False\n"
            "source = src/probos,tests\n"
            "relative_files = True\n"
            f"data_file = {data_file.as_posix()}\n"
            "dynamic_context = test_function\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "coverage",
                "run",
                f"--rcfile={rc_file}",
                "-m",
                "pytest",
                *targets,
                *_pytest_base_command(),
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            errors.append(
                "instrumented run exited "
                f"{completed.returncode}; a map captured from a red tree is not usable"
            )
            return None, errors

        data = coverage.CoverageData(basename=str(data_file))
        data.read()
        measured = sorted(
            name.replace("\\", "/")
            for name in data.measured_files()
            if name.replace("\\", "/").startswith(_MEASURED_SOURCE_PREFIX)
        )
        contexts: dict[str, list[str]] = {}
        for name in measured:
            for found in data.contexts_by_lineno(name).values():
                for context in found:
                    if context:
                        contexts.setdefault(context, []).append(name)
        payload_contexts = {
            context: sorted(set(files)) for context, files in contexts.items()
        }

    collected = _collect_nodes(repo_root, targets)
    covered_contexts = set(payload_contexts)
    uncontexted = sorted(
        node
        for node in collected
        if (context_for_node(node) or "") not in covered_contexts
    )

    destination = output or (
        _DEFAULT_ARTIFACT_DIR / f"testmap-{head_tree[:12]}.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "selector_version": SELECTOR_VERSION,
                "map_version": MAP_VERSION,
                "base_commit": head,
                "base_tree": head_tree,
                "targets": list(targets),
                "measured_files": measured,
                "contexts": payload_contexts,
                "uncontexted_tests": uncontexted,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return destination, errors


# ---------------------------------------------------------------------------
# The shadow ledger
# ---------------------------------------------------------------------------


def verify_append(before: bytes, after: bytes) -> None:
    """Raise unless ``after`` is ``before`` plus new bytes.

    The ledger is append-only and a tool that reads the same file it writes
    invites a rewrite bug, so every write is checked against the prior bytes
    rather than trusted. Truncation and in-place rewrites both fail here.
    """
    if len(after) < len(before):
        raise RuntimeError(
            "refusing a ledger write that shortens the file: "
            f"{len(before)} -> {len(after)} bytes"
        )
    if not after.startswith(before):
        raise RuntimeError(
            "refusing a ledger write that rewrites existing bytes; the ledger is "
            "append-only and extending, restarting or excluding a series requires "
            "a Captain-ratified decision recorded before the replacement series runs"
        )
    if len(after) == len(before):
        raise RuntimeError("ledger write added no bytes")


def read_ledger(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse the ledger into records, accumulating every malformed line."""
    if not path.is_file():
        return [], []
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{number}: unparseable ledger line: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{path.name}:{number}: ledger line is not a JSON object")
            continue
        records.append(payload)
    return records, errors


def ledger_lines(path: Path) -> list[str]:
    """Every non-blank raw line, exactly as stored.

    The hash chain is over stored bytes, so it cannot be verified from parsed
    records: re-serialising a record would recompute the digest from the value
    rather than from what is on disk, which is the one thing the chain exists to
    check.
    """
    if not path.is_file():
        return []
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def line_digest(line: str) -> str:
    """SHA-256 of one stored ledger line."""
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _append_ledger(path: Path, payload: dict[str, Any]) -> None:
    before = path.read_bytes() if path.is_file() else b""
    if before and not before.endswith(b"\n"):
        raise RuntimeError("refusing to append to a ledger whose last line is partial")
    existing = ledger_lines(path)
    # Chain to the previous stored line. Append-only is otherwise unenforceable:
    # review demonstrated two valid rows being swapped with no problem reported,
    # because every row validated fine in isolation.
    payload = dict(payload)
    payload["prev_sha256"] = line_digest(existing[-1]) if existing else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    verify_append(before, path.read_bytes())


def declare_enrollment(
    path: Path, *, repo_root: Path, target_runs: int = TARGET_RUNS
) -> tuple[bool, str]:
    """Write the fixed-enrollment header, once.

    The cutoff is recorded *before* any observation so the sample cannot be
    chosen after the fact. A second call is refused.
    """
    records, errors = read_ledger(path)
    if errors:
        return False, "; ".join(errors)
    if any(record.get("kind") == "enrollment" for record in records):
        return False, (
            "an enrollment header already exists; extending, restarting or "
            "excluding a series requires a Captain-ratified decision recorded "
            "before the replacement series runs"
        )
    if records:
        return False, "the ledger already has rows but no enrollment header"
    head = _git_text(repo_root, "rev-parse", "HEAD") or ""
    now = _utc_now()
    _append_ledger(
        path,
        {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "kind": "enrollment",
            "series": SERIES_NAME,
            "target_runs": target_runs,
            "cutoff_utc": now,
            "enrollment_commit": head,
            "declared_at_utc": now,
            "selector_version": SELECTOR_VERSION,
            "note": (
                "Fixed enrollment declared before observation. The series is "
                "NOT complete and no promotion claim may cite it until it "
                f"holds {target_runs} eligible rows with zero detected misses."
            ),
        },
    )
    return True, f"declared enrollment series {SERIES_NAME} in {path.as_posix()}"


def ledger_status(path: Path) -> dict[str, Any]:
    records, errors = read_ledger(path)
    header = next((r for r in records if r.get("kind") == "enrollment"), None)
    rows = [r for r in records if r.get("kind") == "run"]
    eligible = [r for r in rows if r.get("eligible") is True]
    misses = [r for r in eligible if (r.get("miss") or {}).get("detected") is True]
    target = int(header.get("target_runs", TARGET_RUNS)) if header else TARGET_RUNS
    return {
        "path": path.as_posix(),
        "errors": errors,
        "has_header": header is not None,
        "series": header.get("series") if header else None,
        "cutoff_utc": header.get("cutoff_utc") if header else None,
        "target_runs": target,
        "row_count": len(rows),
        "eligible_count": len(eligible),
        "detected_misses": len(misses),
        "series_complete": False,
        "series_status": (
            f"{len(eligible)}/{target} eligible rows; the series is NOT complete "
            "and no promotion claim may cite it"
        ),
    }


def _chain_problems(path: Path) -> list[str]:
    """Verify each row's ``prev_sha256`` against the line actually before it.

    This is what makes the ledger append-only in fact rather than by convention.
    Rows written before the chain existed carry no ``prev_sha256``; those are
    reported as unchained rather than as breaks, so the historical record is not
    retroactively condemned for a field it could not have had.
    """
    problems: list[str] = []
    lines = ledger_lines(path)
    for index, line in enumerate(lines[1:], start=2):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue  # already reported by read_ledger
        if not isinstance(payload, dict) or payload.get("kind") != "run":
            continue
        recorded = payload.get("prev_sha256")
        if recorded is None:
            problems.append(
                f"{path.name}:{index}: row predates the hash chain (no prev_sha256); "
                "it cannot be proven to sit where it was written"
            )
            continue
        expected = line_digest(lines[index - 2])
        if recorded != expected:
            problems.append(
                f"{path.name}:{index}: prev_sha256 {recorded!r} does not match the "
                f"preceding line ({expected!r}); rows were reordered, rewritten, "
                "or removed"
            )
    return problems


def check_ledger(path: Path) -> list[str]:
    """Structural problems with the ledger. Writes nothing."""
    problems: list[str] = []
    records, errors = read_ledger(path)
    problems.extend(errors)
    problems.extend(_chain_problems(path))
    if not records:
        if path.is_file():
            problems.append(f"{path.name}: ledger has no records")
        else:
            problems.append(f"{path.as_posix()}: ledger does not exist")
        return problems
    if records[0].get("kind") != "enrollment":
        problems.append(f"{path.name}: the first record is not the enrollment header")
    headers = [r for r in records if r.get("kind") == "enrollment"]
    if len(headers) > 1:
        problems.append(f"{path.name}: {len(headers)} enrollment headers; expected 1")
    for index, record in enumerate(records[1:], start=2):
        if record.get("kind") != "run":
            problems.append(f"{path.name}:{index}: unexpected record kind")
    cutoff = headers[0].get("cutoff_utc") if headers else None
    seen: set[str] = set()
    for index, record in enumerate(records, start=1):
        if record.get("kind") != "run":
            continue
        fingerprint = record.get("tree_fingerprint")
        eligible = record.get("eligible")
        expected = bool(
            isinstance(fingerprint, str)
            and fingerprint
            and fingerprint not in seen
            and record.get("changed_path_count")
            and cutoff
            and str(record.get("recorded_at_utc", "")) > str(cutoff)
        )
        if eligible is not expected:
            problems.append(
                f"{path.name}:{index}: eligible={eligible!r} disagrees with the "
                f"recomputed value {expected!r}"
            )
        if isinstance(fingerprint, str):
            seen.add(fingerprint)
        selector = record.get("selector") or {}
        nodes = record.get("selected_nodes")
        if isinstance(nodes, list) and selector.get("nodes_sha256") != node_digest(
            [str(node) for node in nodes]
        ):
            problems.append(f"{path.name}:{index}: selected nodes_sha256 disagrees")
    return problems


# ---------------------------------------------------------------------------
# Shadow run
# ---------------------------------------------------------------------------


def run_shadow(
    *,
    repo_root: Path,
    result: SelectionResult,
    collection_path: Path,
    ledger_path: Path,
    record_dir: Path,
    dry_run: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """Record one shadow observation: bulky record on disk, digest row in git.

    The record holds the full node lists; the ledger row holds only hashes, so a
    later claim that the selector "would have caught it" is recomputable rather
    than believed. ``logs/gates/`` is git-ignored and the gate's janitor sweeps
    materialized worktrees, so evidence for a fixed-enrollment series cannot
    live there alone.
    """
    problems: list[str] = []
    head = _git_text(repo_root, "rev-parse", "HEAD") or ""
    head_tree = _git_text(repo_root, "rev-parse", "HEAD^{tree}") or ""
    fingerprint = tree_fingerprint(repo_root)
    if fingerprint is None:
        problems.append("git could not fingerprint the tree; row marked ineligible")

    records, ledger_errors = read_ledger(ledger_path)
    problems.extend(ledger_errors)
    if ledger_errors:
        # Refuse to extend a ledger that is already structurally broken. Review
        # showed the append succeeding while the corruption was merely reported,
        # which lets rows pile onto a record whose integrity nobody can restate.
        problems.append(
            "refusing to append: repair the existing ledger first "
            "(python scripts/select_tests.py --check)"
        )
        return {"kind": "shadow", "appended": False, "problems": list(problems)}, problems
    header = next((r for r in records if r.get("kind") == "enrollment"), None)
    if header is None:
        problems.append(
            "no enrollment header; run --declare-enrollment before recording rows"
        )
    seen = {
        record.get("tree_fingerprint")
        for record in records
        if record.get("kind") == "run"
    }
    recorded_at = _utc_now()
    cutoff = str(header.get("cutoff_utc", "")) if header else ""
    eligible = bool(
        fingerprint
        and fingerprint not in seen
        and result.changed_paths
        and cutoff
        and recorded_at > cutoff
    )

    selected_missing = sorted(set(result.full_nodes) - set(result.nodes))
    miss_detected = result.verdict == "selected" and bool(selected_missing)

    record_payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "shadow-record",
        "recorded_at_utc": recorded_at,
        "head": head,
        "head_tree": head_tree,
        "tree_fingerprint": fingerprint,
        "base_commit": result.base_commit,
        "changed_paths": list(result.changed_paths),
        "verdict": result.verdict,
        "reasons": list(result.reasons),
        "details": list(result.details),
        "selected_nodes": list(result.nodes),
        "collected_nodes": list(result.full_nodes),
        "not_selected_nodes": selected_missing,
        "note": (
            "Shadow observation only. This record has no release authority and "
            "the enrollment series is not complete."
        ),
    }

    if dry_run:
        return {
            "record": None,
            "ledger_row": None,
            "eligible": eligible,
            "problems": problems,
        }, problems

    record_dir.mkdir(parents=True, exist_ok=True)
    record_path = record_dir / (
        f"{_utc_stamp()}-{(head_tree or 'unknown')[:12]}-p{os.getpid()}.shadow.json"
    )
    record_path.write_text(
        json.dumps(record_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    row = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "kind": "run",
        "recorded_at_utc": recorded_at,
        "head": head,
        "head_tree": head_tree,
        "tree_fingerprint": fingerprint,
        "eligible": eligible,
        "changed_path_count": len(result.changed_paths),
        "changed_paths": list(result.changed_paths),
        "selector": {
            "verdict": result.verdict,
            "reasons": list(result.reasons),
            "node_count": len(result.nodes),
            "nodes_sha256": node_digest(result.nodes),
        },
        "full": {
            "node_count": len(result.full_nodes),
            "nodes_sha256": node_digest(result.full_nodes),
            "source": collection_path.as_posix(),
        },
        "miss": {
            "detected": miss_detected,
            "missed_node_count": len(selected_missing) if miss_detected else 0,
            "missed_nodes_sha256": (
                node_digest(selected_missing) if miss_detected else None
            ),
        },
        "selector_version": SELECTOR_VERSION,
        "map_version": MAP_VERSION,
        "map_base_commit": result.base_commit,
        "record": {
            "path": _relative_posix(record_path, repo_root),
            "sha256": _sha256_file(record_path),
        },
    }
    _append_ledger(ledger_path, row)
    return {
        "record": _relative_posix(record_path, repo_root),
        "ledger_row": row,
        "eligible": eligible,
        "problems": problems,
    }, problems


def _relative_posix(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# ---------------------------------------------------------------------------
# Balance measurement (measurement only; changes no distribution)
# ---------------------------------------------------------------------------


def junit_node_id(attributes: dict[str, str]) -> str | None:
    """Reconstruct a pytest node ID from a JUnit ``testcase`` element.

    ``classname`` is the dotted module path plus any class chain, so the class
    chain is whatever remains after stripping the module derived from ``file``.
    """
    file_name = (attributes.get("file") or "").replace("\\", "/").removeprefix("./")
    name = attributes.get("name") or ""
    classname = attributes.get("classname") or ""
    if not file_name.endswith(".py") or not name:
        return None
    module = file_name[: -len(".py")].replace("/", ".")
    if classname == module:
        chain: list[str] = []
    elif classname.startswith(f"{module}."):
        chain = classname[len(module) + 1 :].split(".")
    else:
        return None
    return "::".join([file_name, *chain, name])


def gate_balance(collection_path: Path, junit_path: Path) -> dict[str, Any]:
    """Per-worker counts, per-node durations, union equality, duplicates.

    Reports the imbalance; it does **not** change the distribution. Under
    ``--dist=loadfile`` the imbalance is a duration property of file grouping,
    so per-worker node counts alone understate it -- durations come from the
    JUnit ``time`` attributes.
    """
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "collection": collection_path.as_posix(),
        "junit": junit_path.as_posix(),
        "errors": [],
    }
    try:
        payload = json.loads(collection_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report["errors"].append(f"unreadable collection artifact: {exc}")
        return report
    collected = payload.get("collected_nodeids")
    if not isinstance(collected, list):
        report["errors"].append("collection artifact has no collected_nodeids")
        return report
    collected_strings = [str(node) for node in collected]
    duplicate_collected = sorted(
        {node for node in collected_strings if collected_strings.count(node) > 1}
    ) if len(collected_strings) != len(set(collected_strings)) else []

    worker_counts = payload.get("worker_execution_counts")
    counts = (
        {str(key): int(value) for key, value in worker_counts.items()}
        if isinstance(worker_counts, dict)
        else {}
    )

    try:
        root = ET.parse(junit_path).getroot()
    except (ET.ParseError, OSError) as exc:
        report["errors"].append(f"unreadable JUnit report: {exc}")
        return report
    testcases = [
        element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "testcase"
    ]
    junit_nodes: list[str] = []
    durations: dict[str, float] = {}
    file_durations: dict[str, float] = {}
    unresolved = 0
    for testcase in testcases:
        node = junit_node_id(dict(testcase.attrib))
        if node is None:
            unresolved += 1
            continue
        junit_nodes.append(node)
        try:
            seconds = float(testcase.attrib.get("time", "0"))
        except ValueError:
            seconds = 0.0
        durations[node] = durations.get(node, 0.0) + seconds
        file_name = node.split("::", 1)[0]
        file_durations[file_name] = file_durations.get(file_name, 0.0) + seconds

    duplicate_junit = sorted({node for node in junit_nodes if junit_nodes.count(node) > 1}) if len(junit_nodes) != len(set(junit_nodes)) else []
    collected_set = set(collected_strings)
    junit_set = set(junit_nodes)
    only_collected = sorted(collected_set - junit_set)
    only_junit = sorted(junit_set - collected_set)

    slowest_files = sorted(
        file_durations.items(), key=lambda item: (-item[1], item[0])
    )[:10]
    report.update(
        {
            "collected_node_count": len(collected_strings),
            "junit_testcase_count": len(testcases),
            "junit_node_count": len(junit_nodes),
            "junit_unresolved_testcases": unresolved,
            "union_equal": not only_collected and not only_junit and unresolved == 0,
            "only_in_collection": only_collected[:12],
            "only_in_junit": only_junit[:12],
            "only_in_collection_count": len(only_collected),
            "only_in_junit_count": len(only_junit),
            "duplicate_collected_nodes": duplicate_collected[:12],
            "duplicate_junit_nodes": duplicate_junit[:12],
            "worker_execution_counts": dict(sorted(counts.items())),
            "worker_count": len(counts),
            "worker_min": min(counts.values()) if counts else None,
            "worker_max": max(counts.values()) if counts else None,
            "worker_spread_ratio": (
                round(max(counts.values()) / min(counts.values()), 2)
                if counts and min(counts.values()) > 0
                else None
            ),
            "worker_total": sum(counts.values()) if counts else 0,
            "worker_total_matches_collection": (
                sum(counts.values()) == len(collected_strings) if counts else False
            ),
            "total_duration_seconds": round(sum(durations.values()), 3),
            "slowest_files": [
                {"file": name, "seconds": round(seconds, 3)}
                for name, seconds in slowest_files
            ],
            "note": (
                "Measurement only. --dist=loadfile groups by file, so the "
                "imbalance is a duration property of grouping rather than of any "
                "single large file. This slice changes no distribution."
            ),
        }
    )
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _resolve_inputs(
    args: argparse.Namespace, repo_root: Path
) -> tuple[Path | None, Path | None]:
    map_path = (
        Path(args.map)
        if args.map
        else latest_artifact(_DEFAULT_ARTIFACT_DIR, "testmap-*.json")
    )
    collection_path = (
        Path(args.collection)
        if args.collection
        else latest_artifact(_DEFAULT_ARTIFACT_DIR, ".collection.json")
    )
    return map_path, collection_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-broad impact selection in shadow mode. This tool has no "
            "release authority: only a validated receipt from "
            "scripts/run_test_gate.py authorizes a release."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--select", action="store_true", help="select and report (read-only)")
    mode.add_argument(
        "--shadow",
        action="store_true",
        help="select, write a shadow record, and append one ledger row",
    )
    mode.add_argument(
        "--capture-map",
        action="store_true",
        help="run the instrumented suite out of band and write a test map",
    )
    mode.add_argument(
        "--declare-enrollment",
        action="store_true",
        help="write the fixed-enrollment ledger header once (refused if present)",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="validate the shadow ledger and exit non-zero on any problem (writes nothing)",
    )
    mode.add_argument(
        "--gate-balance",
        nargs=2,
        metavar=("COLLECTION", "JUNIT"),
        help="report per-worker counts and per-node durations for a shipped gate",
    )
    parser.add_argument("--map", metavar="PATH", help="test map to select against")
    parser.add_argument(
        "--collection", metavar="PATH", help="gate collection artifact for the full set"
    )
    parser.add_argument(
        "--ledger", metavar="PATH", default=str(_DEFAULT_LEDGER)
    )
    parser.add_argument(
        "--seams-dir", metavar="PATH", default=str(_DEFAULT_SEAMS_DIR)
    )
    parser.add_argument("--base", metavar="COMMIT", help="override the map's base commit")
    parser.add_argument(
        "--target",
        action="append",
        metavar="PATH",
        help="pytest target for --capture-map (repeatable; defaults to tests)",
    )
    parser.add_argument("--output", metavar="PATH", help="--capture-map destination")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="with --shadow, compute everything and write nothing",
    )
    parser.add_argument("--json", metavar="PATH", help="also write the report as JSON")
    args = parser.parse_args(argv)

    repo_root = _REPO_ROOT
    ledger_path = Path(args.ledger)
    report: dict[str, Any]

    if args.gate_balance:
        report = gate_balance(Path(args.gate_balance[0]), Path(args.gate_balance[1]))
        _emit(report, args.json)
        if report["errors"]:
            for problem in report["errors"]:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print(
            "gate balance: "
            f"{report['collected_node_count']} collected, union_equal="
            f"{report['union_equal']}, workers={report['worker_count']}, "
            f"min={report['worker_min']}, max={report['worker_max']}, "
            f"spread={report['worker_spread_ratio']}x"
        )
        return 0

    if args.check:
        problems = check_ledger(ledger_path)
        report = {"kind": "check", "ledger": ledger_status(ledger_path), "problems": problems}
        _emit(report, args.json)
        if problems:
            print(
                f"shadow ledger check failed with {len(problems)} problem(s):",
                file=sys.stderr,
            )
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print(f"shadow ledger check passed; {report['ledger']['series_status']}")
        return 0

    if args.declare_enrollment:
        written, message = declare_enrollment(ledger_path, repo_root=repo_root)
        print(message, file=sys.stdout if written else sys.stderr)
        return 0 if written else 1

    if args.capture_map:
        targets = args.target or ["tests"]
        destination, errors = capture_map(
            repo_root=repo_root, targets=targets, output=Path(args.output) if args.output else None
        )
        for problem in errors:
            print(f"  - {problem}", file=sys.stderr)
        if destination is None:
            return 1
        print(f"wrote {_relative_posix(destination, repo_root)}")
        return 0

    map_path, collection_path = _resolve_inputs(args, repo_root)
    if collection_path is None or not collection_path.is_file():
        print(
            "no gate collection artifact available; selection cannot enumerate the "
            "full node set. Pass --collection PATH.",
            file=sys.stderr,
        )
        return 1
    full_nodes, collection_errors = load_collection(collection_path)
    if collection_errors:
        for problem in collection_errors:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    test_map: TestMap | None = None
    map_errors: list[str] = []
    if map_path is None:
        map_errors = ["no test map found; run --capture-map at a known-green commit"]
    else:
        test_map, map_errors = load_map(map_path)

    result = select(
        repo_root=repo_root,
        test_map=test_map,
        map_errors=map_errors,
        full_nodes=full_nodes,
        seams_dir=Path(args.seams_dir),
        base=args.base,
    )
    report = result.to_report()
    report["map"] = map_path.as_posix() if map_path else None
    report["collection"] = collection_path.as_posix()

    if args.shadow:
        shadow, _ = run_shadow(
            repo_root=repo_root,
            result=result,
            collection_path=collection_path,
            ledger_path=ledger_path,
            record_dir=_DEFAULT_ARTIFACT_DIR / "shadow",
            dry_run=args.dry_run,
        )
        report["shadow"] = shadow
        report["ledger"] = ledger_status(ledger_path)

    _emit(report, args.json)
    for detail in result.details:
        print(f"  - {detail}", file=sys.stderr)
    print(
        f"verdict={result.verdict} selected={len(result.nodes)}/"
        f"{len(result.full_nodes)} reasons={','.join(result.reasons) or 'none'}"
    )
    print(
        "advisory only: this output is not release authority and the shadow "
        "series is not complete"
    )
    return 0


def _emit(report: dict[str, Any], json_path: str | None) -> None:
    if json_path:
        Path(json_path).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    raise SystemExit(main())
