#!/usr/bin/env python
"""Architecture fitness check for AD-1270b (slice 2 of 3).

The repository states review triggers -- a ~500-line / ~15-method SRP trigger,
lower-to-higher layer imports, direct database connections outside approved
adapters, unowned ``asyncio.create_task`` calls -- and nothing measured them.
A stated principle nobody counts is a preference, not a constraint: existing
debt looks identical to new debt in review, so debt gets copied into new
modules without anyone noticing.

This script measures four such categories against a **reviewed frozen
baseline** (``docs/development/architecture-baseline.yaml``) and fails on any
difference in either direction. Two further categories ship **report-only**
because their candidate sets are not classified yet; see "Report-only" below.

This is a **tool**, not runtime. AD-1270a's ``DECISIONS.md`` D6 fixed the
dependency direction as checker -> data, so nothing under ``src/probos/``
reads, imports, or executes this script or its baseline.

Usage::

    python scripts/check_architecture_principles.py --check
    python scripts/check_architecture_principles.py --check --json report.json
    python scripts/check_architecture_principles.py --update-baseline

Why symmetric difference
------------------------
A key present in the tree but not the baseline is a **new violation**. A key
present in the baseline but not the tree is a **stale row**: the violation was
fixed and the reviewed baseline must shrink in the same commit, or it rots into
a list of things that used to be true. A per-key occurrence ``count`` that moved
in either direction fails for the same reason -- a second ``sqlite3.connect``
added to an already-frozen function is new debt that a key-set difference alone
would miss.

Counting alone was rejected: it permits fixing one violation and adding another
with the total unchanged, which is exactly the "existing debt may not be copied
into a new module" property the program asks for.

What identity survives refactoring
----------------------------------
Never a line number, never a content hash, and **never a magnitude**. A
line-keyed row churns when anything above it moves; a content hash churns when
anything inside the construct is edited, so fixing one line in a 600-line class
would rewrite the baseline. Identity is the enclosing named symbol plus the
semantic tuple of the violation:

===============  ============================================  ===============
Category         Baseline key                                  Frozen payload
===============  ============================================  ===============
``srp-size``     ``<module>::<Class>``                         triggers
``layer-import`` ``<source module> -> <imported module>``      --
``db-connect``   ``<module>::<enclosing symbol>``              callee, count
``unowned-task`` ``<module>::<enclosing symbol>``              callee, count
===============  ============================================  ===============

``CognitiveAgent`` is frozen as ``probos.cognitive.cognitive_agent::CognitiveAgent``
with triggers ``[lines, methods]`` -- *not* with its 10,598 body lines. Current
magnitudes go in the JSON report, which is not gated.

``review_by`` is required and is never time-enforced
----------------------------------------------------
Every ``disposition: debt`` row must carry a non-empty ``owner``, ``rationale``
and ``review_by`` (an ISO date **or** a removal condition). The checker fails
when the field is missing or blank. It does **not** fail because a date has
passed: a gate that turns red at midnight with no code change is
non-deterministic and would break an unrelated commit. Expiry is surfaced in the
report and as a stderr warning. Do not "fix" this later.

Report-only categories are not clean, they are ungated
------------------------------------------------------
``private-access`` and ``source-text-tests`` appear in the report with
``mode: report-only`` and never gate. The program requires them classified
before gating, and freezing thousands of unreviewed rows in a file whose rows
mean "reviewed" would be false. The ``categories`` block exists so a consumer
cannot mistake an absent category for an empty one.

Honest bounds -- what this does NOT catch
-----------------------------------------
1.  **Only five packages are ranked for layers** (``substrate``, ``mesh``,
    ``consensus``, ``cognitive``, ``experience``). Every other package under
    ``probos/`` is unranked and is neither a source nor a target of any layer
    rule, so a lower-to-higher import into or out of an unranked package is
    invisible here. Ranking the rest is a design decision with no current
    authority; doing it wrongly is how the prior art below produced 1,981 rows.
2.  ``cross_layer_analysis.py`` at the repository root is **superseded** by this
    script and its output is unusable: it ranks 10 of 54 packages and falls
    unranked packages through to "may import nothing", so its first reported
    row is a package importing its own sibling module. Do not trust its count.
3.  Static AST only. A connection opened through a dynamically resolved
    attribute, a task created by a helper that wraps ``create_task``, or an
    import performed by ``importlib`` is not seen.
4.  ``unowned-task`` equates a bare-expression statement with discarded
    ownership. That is a genuine ownership fact -- the reference is dropped at
    that statement -- but a call whose result is stored and then never awaited,
    cancelled, or drained is **not** caught. Widening the predicate beyond the
    bare-``ast.Expr`` form would lose the justification for calling these
    unowned, so it stays narrow deliberately.
5.  Untracked files are invisible by construction (see below). That is the
    point, not a gap.
6.  ``srp-size`` counts direct method children of a ``ClassDef`` body, so
    methods contributed by a base class or a mixin are not counted.
7.  ``srp-size`` also misses methods **assigned onto** a class after its body
    (``Widget.handle = _handle``). Adversarial review demonstrated this; the
    class stays small syntactically while its effective surface grows. Catching
    it needs dataflow rather than a body scan, so it is a stated bound rather
    than a silent one.
8.  Import aliases **are** resolved (``import sqlite3 as s``,
    ``from sqlite3 import connect as c``), because those are ordinary import
    style rather than evasion, and review proved the attribute-only matcher let
    real ``sqlite3.connect`` and ``asyncio.create_task`` sites through. A
    binding rebound at runtime, or one reached through a wrapper function, is
    still out of reach -- see bound 3.

Cost
----
About 5 s warm on the reference host over ~915 tracked source files and ~1,440
test files. Measured at **11.9 s** for this phase inside a freshly materialized
gate worktree, where nothing is in the page cache -- budget from that figure,
not from a warm local run.

Untracked files are invisible
-----------------------------
The file list comes from ``git ls-files``, never a disk walk. The canonical gate
materializes ``HEAD`` into a fresh worktree, so a check satisfied by uncommitted
work would pass locally and fail in the gate -- the developer-local/gate seam
this program exists to close.

AST only, never regex over source text: a dotted path inside a docstring or a
``#`` comment must not read as code. This is also the program's own
"Do Not Build" item, and it is why inline ``# noqa``-style pragmas were rejected
as a baseline format.

Writes nothing under ``--check``. The gate wrapper fails the run if preflight
mutates the tree.
"""

from __future__ import annotations

import argparse
import ast
import gc
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_BASELINE = _REPO_ROOT / "docs" / "development" / "architecture-baseline.yaml"
_DEFAULT_SRC_ROOT = _REPO_ROOT / "src"
_DEFAULT_TESTS_ROOT = _REPO_ROOT / "tests"

#: Categories compared against the frozen baseline. A difference in either
#: direction fails.
GATING_CATEGORIES: tuple[str, ...] = (
    "srp-size",
    "layer-import",
    "db-connect",
    "unowned-task",
)

#: Categories that appear in the report and never gate (D3).
REPORT_ONLY_CATEGORIES: tuple[str, ...] = ("private-access", "source-text-tests")

ALL_CATEGORIES: tuple[str, ...] = GATING_CATEGORIES + REPORT_ONLY_CATEGORIES

VALID_DISPOSITIONS: frozenset[str] = frozenset({"approved", "debt"})

#: Top-level keys the baseline document must carry.
REQUIRED_BASELINE_KEYS: tuple[str, ...] = (
    "schema_version",
    "baseline_id",
    "owner",
    "tracking_issue",
    "layers",
    "gating_categories",
    "report_only_categories",
    "violations",
)

#: The repository's stated SRP review triggers.
SRP_MAX_BODY_LINES = 500
SRP_MAX_DIRECT_METHODS = 15

#: Exact callee renders that count as a direct database connection.
DB_CONNECT_CALLEES: frozenset[str] = frozenset(
    {"sqlite3.connect", "aiosqlite.connect"}
)

#: Canonical unowned-scheduling callees. ``ensure_future`` is here because the
#: repository bans it outright ("Never use ``asyncio.ensure_future()``"), so a
#: bare one is unowned scheduling by definition.
TASK_CREATE_CALLEES: frozenset[str] = frozenset(
    {"asyncio.create_task", "asyncio.ensure_future"}
)


def import_aliases(tree: ast.AST) -> dict[str, str]:
    """Map every imported binding in ``tree`` to its canonical dotted name.

    Without this the gate is bypassed by ordinary import style, not by anything
    clever: ``import sqlite3 as s`` renders ``s.connect``, and
    ``from sqlite3 import connect`` renders a bare ``connect`` with no attribute
    node at all. Adversarial review demonstrated both, plus the ``create_task``
    equivalents. Collected in a pre-pass because a function-level import may sit
    below the call it binds.
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


def canonical_callee(rendered: str, aliases: dict[str, str]) -> str:
    """Rewrite ``rendered`` through ``aliases`` so equivalent forms compare equal.

    ``s.connect`` -> ``sqlite3.connect``; a bare ``connect`` bound by
    ``from sqlite3 import connect`` -> ``sqlite3.connect``. An unknown head is
    returned unchanged rather than guessed at.
    """
    if not rendered:
        return rendered
    head, _, tail = rendered.partition(".")
    target = aliases.get(head)
    if target is None:
        return rendered
    return f"{target}.{tail}" if tail else target

#: Receiver names whose private attributes are language mechanics rather than
#: reach-through into another object's internals (report-only narrowing).
_NARROWING_RECEIVERS: frozenset[str] = frozenset(
    {"type", "dict", "list", "str", "set", "tuple", "int", "super", "cls"}
)

#: Substrings that must appear in a test file's text before it is worth
#: parsing for ``source-text-tests``. See ``iter_modules``.
SOURCE_TEXT_MARKERS: tuple[str, ...] = ("getsource", "read_text")


@dataclass(frozen=True)
class Finding:
    """One measured violation.

    ``category``/``key``/``callee``/``triggers``/``count`` form the baseline
    identity and payload. ``file``, ``line`` and ``detail`` are for humans and
    are **never** compared against the baseline (see "What identity survives
    refactoring" above).
    """

    category: str
    key: str
    file: str
    line: int
    triggers: tuple[str, ...] = ()
    callee: str | None = None
    count: int = 1
    detail: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def identity(self) -> tuple[str, str, str | None]:
        """Row identity: category, key, and callee where the callee is part of
        the fact. Degenerates to ``(category, key)`` for the callee-free
        categories, which is what the baseline schema documents."""
        return (self.category, self.key, self.callee)

    def sort_key(self) -> tuple[str, str, str, str, int]:
        """A **total** order, so report order never depends on walk order.

        ``category``/``key``/``callee`` alone do not discriminate two
        report-only rows for the same receiver in the same symbol on different
        lines; ``file`` and ``line`` finish the ordering.
        """
        return (self.category, self.key, self.callee or "", self.file, self.line)


# ---------------------------------------------------------------------------
# File discovery and parsing
# ---------------------------------------------------------------------------


def _tracked_python_files(root: Path) -> list[str] | None:
    """Root-relative POSIX names of the Python files git tracks under ``root``.

    Returns ``None`` when git cannot answer so the caller can fall back to a
    disk walk *loudly* rather than silently measuring nothing -- an empty
    measurement would read as "no violations", which is the worst possible
    failure mode for a gate.

    Names rather than ``Path`` objects on purpose: ``Path.resolve()`` costs
    roughly a quarter of a millisecond on Windows, and resolving every tracked
    file twice cost more than two seconds of a preflight phase.
    """
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.py"],
            cwd=root,
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
    return [name.replace("\\", "/") for name in stdout.split("\0") if name]


def _dotted_from_relative(name: str) -> str | None:
    """Dotted module path from a root-relative POSIX ``*.py`` name.

    Names stay POSIX and dotted throughout. ``repr()`` of a ``Path`` is
    ``WindowsPath('x')`` on Windows and ``PosixPath('x')`` on Linux, and that
    drift has already turned this repository's CI red while ``--check`` passed
    locally (``scripts/gen_config_reference.py``).
    """
    parts = name.split("/")
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    return ".".join(parts) if parts else None


@dataclass(frozen=True)
class ModuleSource:
    """One parsed module: its dotted name, repo-relative POSIX path, and AST."""

    dotted: str
    path: str
    tree: ast.Module


def tracked_module_names(root: Path) -> list[str]:
    """Sorted, root-relative POSIX names of the Python files to measure."""
    if not root.is_dir():
        return []
    names = _tracked_python_files(root)
    if names is None:
        print(
            f"warning: git could not enumerate {root}; falling back to a disk "
            "walk. Untracked files are visible here but absent from the "
            "canonical gate's materialized worktree.",
            file=sys.stderr,
        )
        names = [
            path.relative_to(root).as_posix() for path in root.rglob("*.py")
        ]
    return sorted(names)


def iter_modules(
    root: Path,
    names: list[str],
    *,
    text_prefilter: tuple[str, ...] | None = None,
) -> Iterator[ModuleSource]:
    """Yield one parsed module at a time, retaining none of them.

    Streaming rather than building a ``{dotted: tree}`` index. Retaining every
    tree still satisfies "parse once, visit many" -- every visitor sees each
    tree during the single pass -- but holding ~1.7M AST nodes to the end of
    the process cost 5.5 s of *interpreter teardown* alone, measured by
    comparing a normal exit against ``os._exit``. Streaming keeps peak memory
    at one tree and makes teardown free.

    A file that does not parse is skipped rather than fatal: an unparseable
    source file is the ``compile`` preflight phase's failure to report, and
    duplicating it here would produce two errors for one defect.

    ``text_prefilter`` skips parsing a file whose text contains none of the
    given substrings. It is **not** a violation predicate: it cannot create a
    finding, only avoid a parse that could not have produced one, because an
    attribute named ``getsource`` cannot exist in an AST unless that text is
    present in the source. A file carrying the substring only in a comment is
    still parsed and still correctly yields nothing.
    """
    for name in names:
        dotted = _dotted_from_relative(name)
        if dotted is None:
            continue
        try:
            text = (root / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if text_prefilter is not None and not any(
            marker in text for marker in text_prefilter
        ):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        yield ModuleSource(dotted=dotted, path=f"{root.name}/{name}", tree=tree)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def render_callee(node: ast.AST) -> str:
    """Render a callee expression as dotted text, e.g. ``asyncio.create_task``.

    A call in the receiver chain renders as ``f()`` so that
    ``asyncio.get_running_loop().create_task`` stays distinguishable from
    ``asyncio.create_task``.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{render_callee(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return f"{render_callee(node.func)}()"
    return "?"


def _is_type_checking_test(test: ast.expr) -> bool:
    """True for ``if TYPE_CHECKING:`` and ``if typing.TYPE_CHECKING:``.

    Without this exclusion the two reviewed dependency-injection edges in this
    tree reappear as layer violations.
    """
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _iter_scoped(tree: ast.Module) -> Any:
    """Yield ``(node, enclosing_symbol_chain, inside_type_checking)`` once.

    Iterative rather than a recursive generator: six visitors need this walk,
    and chained ``yield from`` costs O(depth) per node, which made a single
    full-tree pass take longer than the whole preflight budget.
    """
    stack: list[tuple[ast.AST, tuple[str, ...], bool]] = [(tree, (), False)]
    while stack:
        node, chain, in_type_checking = stack.pop()
        for child in ast.iter_child_nodes(node):
            child_type_checking = in_type_checking or (
                isinstance(child, ast.If) and _is_type_checking_test(child.test)
            )
            yield child, chain, child_type_checking
            child_chain = (
                chain + (child.name,)
                if isinstance(
                    child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                )
                else chain
            )
            stack.append((child, child_chain, child_type_checking))


def _enclosing_symbol(chain: tuple[str, ...]) -> str:
    return ".".join(chain) if chain else "<module>"


# ---------------------------------------------------------------------------
# Category collectors
# ---------------------------------------------------------------------------


def _is_unowned_task_callee(rendered: str) -> bool:
    """A canonical scheduling call, or ``.create_task`` on a loop-ish receiver.

    ``rendered`` is expected to have been canonicalised through the module's
    import aliases already. The broad "any attribute named ``create_task``"
    predicate over-matches domain store methods such as
    ``work_store.create_task``, so an unrecognised receiver chain must mention a
    loop.
    """
    if rendered in TASK_CREATE_CALLEES:
        return True
    if not rendered.endswith((".create_task", ".ensure_future")):
        return False
    receiver = rendered.rsplit(".", 1)[0]
    return "loop" in receiver.lower()


@dataclass
class SourceScan:
    """Everything the source-tree visitors produce in one streaming walk."""

    findings: list[Finding] = field(default_factory=list)
    broad_create_task: int = 0
    modules: int = 0
    top_level: set[str] = field(default_factory=set)


def collect_source_findings(
    modules: Iterator[ModuleSource], layers: dict[str, int]
) -> SourceScan:
    """Measure every source category in a **single** walk per module.

    Five visitors share one traversal because five separate ones cost ~25 s
    against a 90 s preflight budget, most of it re-deriving the same child
    lists. Each visitor below is a pure predicate over ``(node, chain)``; the
    walk is the only shared machinery.

    ``srp-size`` -- a ``ClassDef`` whose body span or direct-method count
    crosses the repository's stated review trigger. Both triggers land on one
    row so a class dropping below the line trigger while keeping 40 methods
    does not silently become a "new" violation.

    ``layer-import`` -- a module-scope import from a lower ranked layer into a
    higher one. In scope only when **both** ends are ranked and the layers
    differ, so an intra-package import is never a violation: that artifact
    alone accounts for the head of ``cross_layer_analysis.py``'s unusable
    1,981 rows. Relative imports cannot cross a package boundary upward in
    this layout and are skipped.

    ``db-connect`` / ``unowned-task`` -- call sites collapsed to one row per
    (enclosing symbol, callee) with an occurrence ``count``, so the row is
    line-independent while a second call added to an already-frozen symbol
    stays visible.

    ``private-access`` -- report-only broad candidate set.
    """
    scan = SourceScan()
    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}

    for module in modules:
        dotted, path, tree = module.dotted, module.path, module.tree
        scan.modules += 1
        parts = dotted.split(".")
        if len(parts) >= 2 and parts[0] == "probos":
            scan.top_level.add(parts[1])
        ranked = (
            len(parts) >= 2 and parts[0] == "probos" and parts[1] in layers
        )
        source_rank = layers[parts[1]] if ranked else -1
        # ``id()`` of every Call that is the whole of an expression statement.
        # The walk yields a parent before its descendants, so this is populated
        # before the Call itself is visited. Recording it here -- rather than
        # handling the Expr and the Call in the same branch -- is what keeps a
        # bare-statement call from being counted twice.
        bare_call_ids: set[int] = set()
        aliases = import_aliases(tree)

        for node, chain, type_checking in _iter_scoped(tree):
            # -- srp-size -------------------------------------------------
            if isinstance(node, ast.ClassDef):
                span = (node.end_lineno or node.lineno) - node.lineno + 1
                methods = sum(
                    1
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
                triggers: list[str] = []
                if span > SRP_MAX_BODY_LINES:
                    triggers.append("lines")
                if methods > SRP_MAX_DIRECT_METHODS:
                    triggers.append("methods")
                if triggers:
                    scan.findings.append(
                        Finding(
                            category="srp-size",
                            key=f"{dotted}::{'.'.join(chain + (node.name,))}",
                            file=path,
                            line=node.lineno,
                            triggers=tuple(triggers),
                            detail={
                                "body_lines": span,
                                "direct_methods": methods,
                            },
                        )
                    )
                continue

            # -- layer-import ---------------------------------------------
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if not ranked or type_checking:
                    continue
                if isinstance(node, ast.ImportFrom):
                    if node.level or not node.module:
                        continue
                    targets = [node.module]
                else:
                    targets = [alias.name for alias in node.names]
                for target in targets:
                    target_parts = target.split(".")
                    if (
                        len(target_parts) < 2
                        or target_parts[0] != "probos"
                        or target_parts[1] not in layers
                        or target_parts[1] == parts[1]
                    ):
                        continue
                    if layers[target_parts[1]] > source_rank:
                        scan.findings.append(
                            Finding(
                                category="layer-import",
                                key=f"{dotted} -> {target}",
                                file=path,
                                line=node.lineno,
                                detail={
                                    "source_layer": parts[1],
                                    "target_layer": target_parts[1],
                                },
                            )
                        )
                continue

            # -- private-access (report-only) -----------------------------
            if isinstance(node, ast.Attribute):
                if not node.attr.startswith("_"):
                    continue
                receiver = node.value
                if isinstance(receiver, ast.Name) and receiver.id == "self":
                    continue
                rendered = render_callee(receiver)
                base = rendered[:-2] if rendered.endswith("()") else rendered
                dunder = node.attr.startswith("__") and node.attr.endswith("__")
                scan.findings.append(
                    Finding(
                        category="private-access",
                        key=(
                            f"{dotted}::{_enclosing_symbol(chain)}"
                            f"::{rendered}.{node.attr}"
                        ),
                        file=path,
                        line=node.lineno,
                        detail={
                            "attribute": node.attr,
                            "receiver": rendered,
                            "dunder": dunder,
                            "narrowed": (
                                not dunder and base not in _NARROWING_RECEIVERS
                            ),
                        },
                    )
                )
                continue

            # -- db-connect and unowned-task ------------------------------
            if isinstance(node, ast.Expr):
                if isinstance(node.value, ast.Call):
                    bare_call_ids.add(id(node.value))
                continue
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                rendered = canonical_callee(render_callee(func), aliases)
                if func.attr == "create_task":
                    scan.broad_create_task += 1
            elif isinstance(func, ast.Name):
                # A bare call is invisible unless resolved through the aliases:
                # `from sqlite3 import connect` produces no Attribute node.
                rendered = canonical_callee(func.id, aliases)
                if rendered.endswith(".create_task"):
                    scan.broad_create_task += 1
            else:
                continue
            if not rendered.endswith((".connect", ".create_task", ".ensure_future")):
                continue
            category: str | None = None
            if rendered in DB_CONNECT_CALLEES:
                category = "db-connect"
            elif id(node) in bare_call_ids and _is_unowned_task_callee(rendered):
                category = "unowned-task"
            if category is None:
                continue
            key = f"{dotted}::{_enclosing_symbol(chain)}"
            bucket = buckets.setdefault(
                (category, key, rendered),
                {"file": path, "line": node.lineno, "lines": []},
            )
            bucket["lines"].append(node.lineno)
            bucket["line"] = min(bucket["line"], node.lineno)

    for (category, key, callee), bucket in buckets.items():
        scan.findings.append(
            Finding(
                category=category,
                key=key,
                file=bucket["file"],
                line=bucket["line"],
                callee=callee,
                count=len(bucket["lines"]),
                detail={"lines": sorted(bucket["lines"])},
            )
        )
    return scan


@dataclass
class TestScan:
    """``source-text-tests`` findings plus how many files were actually parsed."""

    findings: list[Finding] = field(default_factory=list)
    scanned: int = 0


def collect_source_text_tests(modules: Iterator[ModuleSource]) -> TestScan:
    """Report-only: tests asserting on source text rather than behavior.

    ``classification`` is a null placeholder. The program asks for these to be
    classified as architectural/security invariants or candidates for
    behavioral replacement; that is a classification deliverable, not a gate,
    and freezing them unclassified under a field meaning "reviewed" would be
    false.
    """
    scan = TestScan()
    for module in modules:
        path, tree = module.path, module.tree
        scan.scanned += 1
        for node, chain, _type_checking in _iter_scoped(tree):
            probe: str | None = None
            if isinstance(node, ast.Attribute) and render_callee(node) == (
                "inspect.getsource"
            ):
                probe = "inspect.getsource"
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "read_text"
                and "__file__" in render_callee(node.func.value)
            ):
                probe = "read_text(__file__)"
            if probe is None:
                continue
            scan.findings.append(
                Finding(
                    category="source-text-tests",
                    key=f"{path}::{_enclosing_symbol(chain)}",
                    file=path,
                    line=node.lineno,
                    callee=probe,
                    detail={"classification": None},
                )
            )
    return scan


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------


def load_baseline(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """Load and shape-check the baseline document."""
    errors: list[str] = []
    if not path.is_file():
        return None, [
            f"baseline file {path.as_posix()} does not exist; generate it with "
            "python scripts/check_architecture_principles.py --update-baseline "
            "and review every row before committing"
        ]
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return None, [f"{path.name}: does not parse as YAML: {exc}"]
    if not isinstance(document, dict):
        return None, [
            f"{path.name}: top level is {type(document).__name__}, expected a mapping"
        ]
    for required in REQUIRED_BASELINE_KEYS:
        if required not in document:
            errors.append(f"{path.name}: missing required top-level key {required!r}")
    return document, errors


def validate_baseline_rows(
    document: dict[str, Any], label: str
) -> tuple[dict[tuple[str, str, str | None], dict[str, Any]], list[str]]:
    """Validate every row's schema and return them keyed by row identity."""
    errors: list[str] = []
    rows: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    violations = document.get("violations")
    if violations is None:
        violations = []
    if not isinstance(violations, list):
        errors.append(
            f"{label}: violations is {type(violations).__name__}, expected a list"
        )
        return rows, errors

    for position, raw in enumerate(violations):
        where = f"{label}:violations[{position}]"
        if not isinstance(raw, dict):
            errors.append(
                f"{where}: row is {type(raw).__name__}, expected a mapping"
            )
            continue
        category = raw.get("category")
        key = raw.get("key")
        if not isinstance(category, str) or category not in GATING_CATEGORIES:
            errors.append(
                f"{where}: category {category!r} is not one of "
                f"{list(GATING_CATEGORIES)}"
            )
            continue
        if not isinstance(key, str) or not key.strip():
            errors.append(f"{where}: key is missing or blank")
            continue
        where = f"{label}[{category} {key}]"
        callee = raw.get("callee")
        if callee is not None and not isinstance(callee, str):
            errors.append(
                f"{where}: callee is {type(callee).__name__}, expected a string "
                "or absent"
            )
            callee = None
        identity = (category, key, callee)
        if identity in rows:
            errors.append(
                f"{where}: duplicate row; a key plus callee must appear at most "
                "once per category"
            )
            continue

        disposition = raw.get("disposition")
        if disposition not in VALID_DISPOSITIONS:
            errors.append(
                f"{where}: disposition {disposition!r} is not one of "
                f"{sorted(VALID_DISPOSITIONS)}"
            )
        for required in ("owner", "rationale", "review_by"):
            value = raw.get(required)
            if value is None or not str(value).strip():
                errors.append(
                    f"{where}: {required!r} is missing or blank; every reviewed "
                    "row needs an owner, a rationale, and a review_by date or "
                    "removal condition"
                )
        count = raw.get("count", 1)
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            errors.append(
                f"{where}: count {count!r} is not a positive integer"
            )
            count = 1
        triggers = raw.get("triggers", [])
        if triggers is None:
            triggers = []
        if not isinstance(triggers, list) or any(
            not isinstance(item, str) for item in triggers
        ):
            errors.append(f"{where}: triggers must be a list of strings")
            triggers = []
        rows[identity] = {
            "category": category,
            "key": key,
            "callee": callee,
            "count": count,
            "triggers": tuple(triggers),
            "disposition": disposition,
            "owner": raw.get("owner"),
            "rationale": raw.get("rationale"),
            "review_by": raw.get("review_by"),
        }
    return rows, errors


def _fix_command(baseline_path: Path) -> str:
    suffix = ""
    if baseline_path.resolve() != _DEFAULT_BASELINE.resolve():
        suffix = f" --baseline {baseline_path.as_posix()}"
    return (
        f"python scripts/check_architecture_principles.py --update-baseline{suffix}"
    )


def compare_to_baseline(
    findings: list[Finding],
    rows: dict[tuple[str, str, str | None], dict[str, Any]],
    baseline_path: Path,
) -> list[str]:
    """Symmetric difference plus per-row count and trigger equality.

    Every difference is reported, never just the first, and each message names
    the exact row and the exact command that fixes it -- a symmetric gate that
    does not tell you how to satisfy it becomes a tax that gets disabled.
    """
    errors: list[str] = []
    current = {
        finding.identity: finding
        for finding in findings
        if finding.category in GATING_CATEGORIES
    }
    fix = _fix_command(baseline_path)

    for identity in sorted(
        set(current) - set(rows), key=lambda item: (item[0], item[1], item[2] or "")
    ):
        finding = current[identity]
        errors.append(
            f"NEW VIOLATION [{finding.category}] {finding.key}"
            + (f" (callee {finding.callee})" if finding.callee else "")
            + f" at {finding.file}:{finding.line}. This is not in the reviewed "
            "baseline. Fix the code, or -- if it is accepted debt -- add the row "
            f"with an owner, rationale and review_by: {fix}"
        )

    for identity in sorted(
        set(rows) - set(current), key=lambda item: (item[0], item[1], item[2] or "")
    ):
        category, key, callee = identity
        errors.append(
            f"STALE BASELINE ROW [{category}] {key}"
            + (f" (callee {callee})" if callee else "")
            + f" no longer occurs in the tree. Delete this row from "
            f"{baseline_path.name} in the same commit that fixed it, or run: {fix}"
        )

    for identity in sorted(
        set(rows) & set(current), key=lambda item: (item[0], item[1], item[2] or "")
    ):
        finding = current[identity]
        row = rows[identity]
        category, key, callee = identity
        if finding.count != row["count"]:
            direction = "rose" if finding.count > row["count"] else "fell"
            errors.append(
                f"COUNT DRIFT [{category}] {key}"
                + (f" (callee {callee})" if callee else "")
                + f": occurrences {direction} from {row['count']} to "
                f"{finding.count} at {finding.file}:{finding.line}. Update the "
                f"reviewed row in the same commit: {fix}"
            )
        if finding.category == "srp-size" and tuple(row["triggers"]) != (
            finding.triggers
        ):
            errors.append(
                f"TRIGGER DRIFT [{category}] {key}: baseline records "
                f"{list(row['triggers'])}, tree now shows "
                f"{list(finding.triggers)} at {finding.file}:{finding.line}. "
                f"Update the reviewed row in the same commit: {fix}"
            )
    return errors


def expiry_warnings(
    rows: dict[tuple[str, str, str | None], dict[str, Any]], today: str
) -> list[str]:
    """Rows whose ISO ``review_by`` date has passed.

    Warnings only, never failures: a gate that turns red at midnight with no
    code change is non-deterministic and would break an unrelated commit.
    """
    warnings: list[str] = []
    for identity in sorted(rows, key=lambda item: (item[0], item[1], item[2] or "")):
        row = rows[identity]
        review_by = str(row.get("review_by") or "")
        if len(review_by) == 10 and review_by[4] == "-" and review_by[7] == "-":
            if review_by < today:
                warnings.append(
                    f"[{row['category']}] {row['key']}: review_by {review_by} has "
                    f"passed (owner {row['owner']})"
                )
    return warnings


# ---------------------------------------------------------------------------
# Report and top-level check
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    errors: list[str]
    warnings: list[str]
    report: dict[str, Any]
    findings: list[Finding]


def _finding_report_row(finding: Finding) -> dict[str, Any]:
    row: dict[str, Any] = {
        "category": finding.category,
        "key": finding.key,
        "file": finding.file,
        "line": finding.line,
    }
    if finding.triggers:
        row["triggers"] = list(finding.triggers)
    if finding.callee is not None:
        row["callee"] = finding.callee
    if finding.count != 1:
        row["count"] = finding.count
    if finding.detail:
        row["detail"] = {k: finding.detail[k] for k in sorted(finding.detail)}
    return row


def check(
    *,
    baseline_path: Path = _DEFAULT_BASELINE,
    src_root: Path = _DEFAULT_SRC_ROOT,
    tests_root: Path = _DEFAULT_TESTS_ROOT,
    today: str | None = None,
) -> CheckResult:
    """Measure every category, compare the gating ones, and build the report."""
    errors: list[str] = []
    document, load_errors = load_baseline(baseline_path)
    errors.extend(load_errors)

    layers: dict[str, int] = {}
    rows: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    if document is not None:
        raw_layers = document.get("layers")
        if isinstance(raw_layers, dict) and all(
            isinstance(name, str) and isinstance(rank, int) and not isinstance(rank, bool)
            for name, rank in raw_layers.items()
        ):
            layers = dict(raw_layers)
        else:
            errors.append(
                f"{baseline_path.name}: layers must be a mapping of package name "
                "to integer rank; layer-import cannot be measured without it"
            )
        row_map, row_errors = validate_baseline_rows(document, baseline_path.name)
        rows = row_map
        errors.extend(row_errors)

    src_names = tracked_module_names(src_root)
    test_names = tracked_module_names(tests_root)
    scan = collect_source_findings(iter_modules(src_root, src_names), layers)
    test_scan = collect_source_text_tests(
        iter_modules(tests_root, test_names, text_prefilter=SOURCE_TEXT_MARKERS)
    )
    source_text = test_scan.findings
    private_access = [
        finding for finding in scan.findings if finding.category == "private-access"
    ]
    findings: list[Finding] = scan.findings + source_text
    findings.sort(key=Finding.sort_key)

    errors.extend(compare_to_baseline(findings, rows, baseline_path))

    warnings = expiry_warnings(rows, today or date.today().isoformat())

    by_category: dict[str, list[Finding]] = {name: [] for name in ALL_CATEGORIES}
    for finding in findings:
        by_category.setdefault(finding.category, []).append(finding)

    baseline_counts: dict[str, int] = {name: 0 for name in GATING_CATEGORIES}
    for category, _key, _callee in rows:
        baseline_counts[category] = baseline_counts.get(category, 0) + 1

    narrowed_private = sum(
        1 for finding in private_access if finding.detail.get("narrowed")
    )
    dunder_private = sum(
        1 for finding in private_access if finding.detail.get("dunder")
    )
    unranked = sorted(scan.top_level - set(layers))

    categories: dict[str, Any] = {}
    for name in GATING_CATEGORIES:
        categories[name] = {
            "mode": "gating",
            "current": len(by_category[name]),
            "baseline": baseline_counts.get(name, 0),
        }
    categories["unowned-task"]["broad_create_task_calls"] = scan.broad_create_task
    categories["layer-import"]["ranked_packages"] = sorted(layers)
    categories["layer-import"]["unranked_top_level"] = unranked
    categories["private-access"] = {
        "mode": "report-only",
        "current": len(private_access),
        "dunder": dunder_private,
        "narrowed": narrowed_private,
        "promotion": (
            "classify the narrowed predicate (no dunders, no builtin receivers) "
            "and freeze the reviewed rows"
        ),
    }
    categories["source-text-tests"] = {
        "mode": "report-only",
        "current": len(source_text),
        "files": len({finding.file for finding in source_text}),
        "promotion": (
            "every row carries classification: invariant|replace-with-behavioral, "
            "then gate the delta"
        ),
    }

    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_by": "scripts/check_architecture_principles.py",
        "src_root": src_root.name,
        "tests_root": tests_root.name,
        "src_modules": scan.modules,
        "test_modules_scanned": test_scan.scanned,
        "test_files_tracked": len(test_names),
        "categories": categories,
        "findings": [_finding_report_row(finding) for finding in findings],
        "warnings": warnings,
        "errors": errors,
    }
    return CheckResult(
        errors=errors, warnings=warnings, report=report, findings=findings
    )


def render_baseline(
    findings: list[Finding],
    previous: dict[str, Any] | None,
    rows: dict[tuple[str, str, str | None], dict[str, Any]],
) -> str:
    """Render the baseline YAML, preserving reviewed metadata for known rows.

    A row that is new gets **blank** ``owner``/``rationale``/``review_by`` on
    purpose: blank fails ``--check``, so the reviewer has to fill them in. A
    placeholder string would pass the non-blank test and ship unreviewed.
    """
    previous = previous or {}
    document: dict[str, Any] = {
        "schema_version": 1,
        "baseline_id": previous.get(
            "baseline_id", "ad-1270b-architecture-fitness-v1"
        ),
        "owner": previous.get("owner", "AD-1270b"),
        "tracking_issue": previous.get("tracking_issue", 1324),
        "source_commit": previous.get("source_commit", ""),
        "layers": previous.get(
            "layers",
            {
                "substrate": 0,
                "mesh": 1,
                "consensus": 2,
                "cognitive": 3,
                "experience": 4,
            },
        ),
        "gating_categories": list(GATING_CATEGORIES),
        "report_only_categories": previous.get(
            "report_only_categories",
            {
                name: {
                    "reason": "",
                    "promotion": "",
                    "owner": "AD-1270b",
                }
                for name in REPORT_ONLY_CATEGORIES
            },
        ),
        "violations": [],
    }
    emitted: list[dict[str, Any]] = []
    for finding in sorted(
        (f for f in findings if f.category in GATING_CATEGORIES),
        key=Finding.sort_key,
    ):
        known = rows.get(finding.identity, {})
        row: dict[str, Any] = {"category": finding.category, "key": finding.key}
        if finding.triggers:
            row["triggers"] = list(finding.triggers)
        if finding.callee is not None:
            row["callee"] = finding.callee
            row["count"] = finding.count
        row["disposition"] = known.get("disposition") or "debt"
        row["owner"] = known.get("owner") or ""
        row["rationale"] = known.get("rationale") or ""
        row["review_by"] = known.get("review_by") or ""
        emitted.append(row)
    document["violations"] = emitted
    header = (
        "# AD-1270b architecture fitness baseline. Reviewed rows only.\n"
        "# Regenerate the row set with:\n"
        "#   python scripts/check_architecture_principles.py --update-baseline\n"
        "# then review every added row: a blank owner/rationale/review_by fails\n"
        "# --check on purpose. Magnitudes are deliberately absent -- storing a\n"
        "# line count here would rewrite this file on every edit.\n"
    )
    body = yaml.safe_dump(
        document,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10**9,
    )
    return header + body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Architecture fitness check")
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
    parser.add_argument(
        "--baseline", metavar="PATH", default=str(_DEFAULT_BASELINE)
    )
    parser.add_argument("--src-root", metavar="PATH", default=str(_DEFAULT_SRC_ROOT))
    parser.add_argument(
        "--tests-root", metavar="PATH", default=str(_DEFAULT_TESTS_ROOT)
    )
    args = parser.parse_args(argv)

    baseline_path = Path(args.baseline)
    # Retaining ~1.7M AST nodes makes the cyclic collector rescan them on every
    # generation-2 pass; measured 10.8 s with the collector on and 4.2 s with it
    # off, for identical output. Scoped to the CLI and restored in `finally` so
    # an in-process caller's GC semantics are never changed underneath it.
    collecting = gc.isenabled()
    gc.disable()
    try:
        result = check(
            baseline_path=baseline_path,
            src_root=Path(args.src_root),
            tests_root=Path(args.tests_root),
        )
    finally:
        if collecting:
            gc.enable()

    if args.update_baseline:
        document, _ = load_baseline(baseline_path)
        rows: dict[tuple[str, str, str | None], dict[str, Any]] = {}
        if document is not None:
            rows, _ = validate_baseline_rows(document, baseline_path.name)
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            render_baseline(result.findings, document, rows), encoding="utf-8"
        )
        print(f"wrote {baseline_path.as_posix()}; review every row before committing")
        return 0

    if args.json:
        Path(args.json).write_text(
            json.dumps(result.report, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )

    for warning in result.warnings:
        print(f"warning: review_by has passed: {warning}", file=sys.stderr)

    if result.errors:
        print(
            f"architecture fitness check failed with {len(result.errors)} "
            "problem(s):",
            file=sys.stderr,
        )
        for problem in result.errors:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    counts = ", ".join(
        f"{name}={result.report['categories'][name]['current']}"
        for name in GATING_CATEGORIES
    )
    print(f"architecture fitness check passed ({counts})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
