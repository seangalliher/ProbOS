#!/usr/bin/env python
"""AD-1270e1 configuration facade contract checker.

``probos.config`` is a 304-name public surface over 224 models and 1,784 field
definitions that 703 tracked files reach into. AD-1270e2/e3 move those models
out. This script freezes what the facade *is* before anything moves, so a
mechanical extraction that silently changes a default, an alias, a field order
or a class identity fails as a **data diff** rather than passing review as a
large, plausible-looking rename.

Five dimensions, one artifact
-----------------------------
``docs/development/config-facade-baseline.yaml`` records, per public name, its
``kind`` and ``tier``; per model its ``qualname``, MRO ``bases``, schema digest
and *ordered* field list; and per field its normalised default, alias and
``validate_default`` flag. Imports, defaults, aliases, schema and dump order are
therefore all one document with one regeneration command.

**Schema is a digest, not a dump, on purpose.** 224 full JSON schemas would be
megabytes and would restate defaults, order and aliases -- which are already
explicit dimensions above. The digest exists to catch only what those four
miss: type and constraint changes. Do not "improve" it into a full schema dump.

**One order is stored; three are proven.** Field-declaration order
(``list(M.model_fields)``) is the stored one because it needs no instantiation
-- which covers the six models that raise on ``M()`` -- and no environment,
which ``model_dump()`` order does not. Pydantic *derives* dump order and schema
``properties`` order from it, so freezing either of those would freeze a
symptom. ``--check`` re-proves both as invariants: a divergence is a Pydantic
behaviour change and a hard failure, never a regeneration.

Why the capture runs in a scrubbed subprocess
---------------------------------------------
Two defaults are environment-dependent, by two different mechanisms, and one of
them is already resolved before any in-process scrub could act:

*   ``PROBOS_NATS_ENABLED`` -- ``NatsConfig.model_fields['enabled']`` carries
    ``validate_default=True``, so Pydantic validates the class-level default
    **once, at import**, while building ``SystemConfig.model_fields['nats']``.
    The ``mode="before"`` field validator reads the variable at that moment.
    Every later ``SystemConfig()`` deep-copies that already-validated instance,
    so ``a.nats is b.nats`` is ``False`` and the validator never re-runs.
    Distinct objects, frozen value: ``monkeypatch.setenv`` genuinely cannot
    move it, and testing ``is`` identity to "prove sharing" returns ``False``
    and points at the wrong mechanism. Only a fresh interpreter can move it.
*   ``PROBOS_LLM_URL`` -- ``CognitiveConfig._apply_env_overrides`` is a
    ``model_validator(mode="after")``, which runs on every construction
    regardless of ``validate_default``.

Capturing under pytest would be worse than useless: ``tests/conftest.py`` uses
``os.environ.setdefault("PROBOS_NATS_ENABLED", "false")``, so the baked value
would be *the generating developer's ambient variable* whenever it is set, and
``false`` only otherwise. The artifact would vary by whose machine produced it
and would agree with the true default just often enough to stay invisible.

Three gates, and the door each one closes
-----------------------------------------
G1 **Capture** -- the canonical surface and dump come from a child interpreter
whose environment is rebuilt explicitly: every ``PROBOS_*`` name and every name
G2 enumerated is deleted before the child starts. The child re-asserts that for
itself, so a broken parent env-build fails loudly instead of silently baking a
value.

G2 **Enumerate** -- AST scan of the movement-proof path set (``config.py``
*plus* ``config_models/**/*.py`` once e2 creates it) for every literal argument
of ``os.environ.get``, ``os.getenv`` and ``os.environ[...]``. A **non-literal**
name is a hard failure: a name that cannot be enumerated cannot be proven
harmless. Scanning the future path set from day one is what stops e2 escaping
this guard by moving models out.

The gate resolves *how* ``os`` was reached, not just how it was spelled at the
call site. ``import os as _os``, ``from os import environ, getenv``,
``env = os.environ`` and ``getattr(os, "environ")`` all reach the same mapping,
and a scanner that only recognised the dotted spelling was bypassable by three
lines of ordinary Python -- measured, each returning zero errors end to end.
Resolution is deliberately **flow-insensitive**: a name bound to ``environ``
anywhere in a module is treated as ``environ`` throughout it. Over-detection
costs a loud failure a human resolves in one edit; under-detection admits an
undeclared read that nothing ever reports again. For the same reason an
``environ`` reference that is *neither* consumed by a recognised read *nor* the
direct source of a binding -- ``dict(os.environ)``, ``helper(os.environ)``,
``os.environ.setdefault(...)`` -- is itself a hard failure, because the scan
cannot follow where it went. Measured on the live path set: zero such
references, so the strictness costs nothing today and closes the indirection
class permanently.

G3 **Differential** -- one child per enumerated name, with only that name set to
a sentinel, and the moved dotted-path set must *exactly* equal the declared set.
Plus a **control**: a sentinel name nothing reads, which must move zero paths.
The control asserts the harness's own premise -- a differential that cannot show
a known mover, or that reports movement for a name nothing reads, has proven
nothing and every other row it produced is meaningless.

So a third environment-reading validator meets three closed doors: a new literal
name has no baseline row and fails on day one; an already-declared name with a
widened blast radius fails G3's exact-set comparison; a computed name fails G2.

The platform trap this file is built around
-------------------------------------------
Three ``Path``-valued defaults are reachable from ``SystemConfig``, and
``model_dump(mode="json")`` renders them with **backslashes** on Windows. A raw
dump hash is therefore guaranteed to differ from Linux CI. This is not
hypothetical: ``scripts/gen_config_reference.py`` documents the same failure
turning CI red three commits running while ``--check`` passed locally. Every
value that reaches this baseline goes through :func:`render_value`, which
normalises ``PurePath`` to POSIX **recursively** -- top-level type is not a
reliable guard, because a ``list[Path]`` or ``dict[str, Path]`` default hides
the same trap one level down.

Relatedly: ``model_json_schema()`` silently **drops** those three defaults
(three ``PydanticJsonSchemaWarning``s). Defaults come from ``model_fields``.
Never from the schema.

Cross-check, not absorption
---------------------------
``scripts/check_config_profiles.py`` already ships
``env_reads_reaching_defaults``, keyed on validator *kind* rather than
``validate_default`` for exactly the ``PROBOS_LLM_URL`` reason. It is not
rewritten or imported here; ``tests/test_ad1270e1_config_facade.py`` asserts the
two instruments agree. Two independent instruments agreeing is evidence; one
instrument is an assumption.

Its ``_DEFAULT_CONFIG_MODULE`` is pinned to a single file, so it goes blind the
moment e2 moves models into a package. Fixing that is e2's job. Making e2 unable
to forget is this slice's: two tripwires fail as soon as
``src/probos/config_models/`` exists while that scan is still single-file, or
while ``select_tests.BLAST_RADIUS_PATTERNS`` has no pattern covering it.

Both tripwires read their targets by **AST**, never by importing them:
``check_config_profiles`` imports ``probos.config`` at module scope, and this
parent process must stay free of it so no ambient-environment value can leak
into a comparison.

Usage::

    python scripts/check_config_facade.py --check
    python scripts/check_config_facade.py --update-baseline

Every check accumulates; one run reports every problem. Writes nothing under
``--check`` -- the gate wrapper fails the run if preflight mutates the tree.
Environment variable **names** are logged; values never are, because the
ambient environment holds secrets.

Nothing under ``src/probos/`` may import this module: the direction is
checker -> data.
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
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from types import ModuleType
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

_REPO_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_BASELINE = _REPO_ROOT / "docs" / "development" / "config-facade-baseline.yaml"

#: The module whose public surface is the facade contract.
FACADE_MODULE = "probos.config"

#: The path set G2 scans. ``config_models/`` does not exist today; scanning it
#: from day one is what stops e2 escaping the environment guard by moving
#: models into a package the scan never looked at.
CONFIG_MODULE_RELPATH = "src/probos/config.py"
CONFIG_MODELS_RELDIR = "src/probos/config_models"

#: The dotted form of :data:`CONFIG_MODELS_RELDIR`, derived rather than
#: repeated so ownership and environment-scanning can never point at different
#: directories.
CONFIG_MODELS_PACKAGE = ".".join(CONFIG_MODELS_RELDIR.split("/")[1:])

#: A ``PROBOS_*`` name nothing reads. Its differential row must move zero paths;
#: if it moves anything, the harness is broken and every other row is void.
CONTROL_VARIABLE = "PROBOS_CONFIG_FACADE_CONTROL_SENTINEL"

#: Passed to the child so it can assert its own scrub. Deliberately not
#: ``PROBOS_``-prefixed, so it never collides with the surface under test.
_INJECTED_MARKER = "_CONFIG_FACADE_INJECTED"

#: 2.4x the ~2.5s measured cost, leaving room for a slower CI host. A checker
#: that silently grows into the preflight budget is a checker nobody keeps.
SELF_TIMEOUT_SECONDS = 6.0

#: Fixed-point bound for alias resolution. Each pass can only add names, so the
#: loop exits early on the first pass that adds none; the bound exists so a
#: pathological file cannot spin, not because four levels of ``a = b = os.environ``
#: indirection is expected.
_BINDING_RESOLUTION_PASSES = 8

#: Sentinel values are literals, never anything read from the ambient
#: environment, so no real secret can reach a child or an error message.
_SENTINEL_VALUES: dict[str, str] = {
    "PROBOS_NATS_ENABLED": "true",
    "PROBOS_LLM_URL": "http://ad1270e1-sentinel.invalid/v1",
}
_DEFAULT_SENTINEL = "ad1270e1-sentinel"

BASELINE_SCHEMA_VERSION = 1
BASELINE_ID = "ad-1270e1-config-facade-v1"

#: Distinguishes "absent from this dump" from "present and set to None".
_MISSING = object()


class ChildFailure(RuntimeError):
    """A capture subprocess failed, so nothing it would have proven holds."""

_HEADER = (
    "# AD-1270e1 configuration facade contract: the public surface of\n"
    "# probos.config -- names, tiers, model identity, field order, defaults,\n"
    "# aliases and schema digests -- frozen before AD-1270e2/e3 move any model.\n"
    "#\n"
    "# Regenerate with:\n"
    "#   python scripts/check_config_facade.py --update-baseline\n"
    "#\n"
    "# Read before editing:\n"
    "#   * `fields` is DECLARATION order. --check re-proves that model_dump()\n"
    "#     order and schema `properties` order still derive from it; a\n"
    "#     divergence is a Pydantic behaviour change, not a regeneration.\n"
    "#   * `schema_sha256` is a digest, not a dump. Defaults, order and aliases\n"
    "#     are explicit dimensions above it; the digest catches type and\n"
    "#     constraint changes only. Do not expand it into a full schema.\n"
    "#   * Defaults come from model_fields, never from model_json_schema(),\n"
    "#     which silently drops the three Path-valued defaults.\n"
    "#   * Path values are POSIX-normalised. A raw dump is Windows-only and\n"
    "#     goes red on Linux CI while --check passes locally.\n"
    "#   * `tier: owned` is the contract. `tier: incidental` names are import\n"
    "#     leakage recorded so nothing is invisible; removing one is a\n"
    "#     reviewable diff, not a contract break.\n"
    "#   * A re-export keeps qualname/bases/fields and passes, provided the\n"
    "#     model moved into src/probos/config_models/ -- the same directory G2\n"
    "#     scans for environment reads. A wrapper or subclass changes `bases`;\n"
    "#     a partial clone changes `fields`.\n"
    "#   * The `environment` rows are captured in a scrubbed subprocess. Adding\n"
    "#     an environment read without a row here fails on day one.\n"
    "#   * Written with the platform's default line endings, like every other\n"
    "#     generated doc here, so a Windows working tree holds CRLF and the\n"
    "#     index holds LF. Nothing compares these bytes -- both the checker and\n"
    "#     its tests compare the parsed document -- but a raw read_bytes()\n"
    "#     probe must fold newlines before hashing or it will disagree with\n"
    "#     `git show :<path>` on Windows and agree on Linux.\n"
    "# A blank review.owner/rationale/review_by fails --check on purpose.\n"
)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def render_value(value: Any) -> str:
    """Render a value platform-independently and deterministically.

    ``repr()`` of a ``pathlib.Path`` is ``WindowsPath('data')`` on Windows and
    ``PosixPath('data')`` on Linux, so a baseline built from raw reprs is
    permanently "stale" on the other platform -- the failure
    ``gen_config_reference.py`` was patched for after it turned CI red three
    commits running. Paths render as their POSIX string form.

    Applied recursively, because the top-level type is not a reliable guard: a
    ``list[Path]`` or ``dict[str, Path]`` default hides the same trap one level
    down. Sets are sorted because their iteration order depends on
    ``PYTHONHASHSEED``. Model instances render as their type only -- their own
    fields are a separate row, and a nested ``repr`` would be both enormous and
    environment-sensitive.
    """
    if value is PydanticUndefined:
        return "<required>"
    if isinstance(value, PurePath):
        return repr(value.as_posix())
    if isinstance(value, BaseModel):
        return f"{type(value).__qualname__}(...)"
    if isinstance(value, list):
        return "[" + ", ".join(render_value(item) for item in value) + "]"
    if isinstance(value, tuple):
        inner = ", ".join(render_value(item) for item in value)
        return f"({inner},)" if len(value) == 1 else f"({inner})"
    if isinstance(value, frozenset):
        return "frozenset({" + ", ".join(sorted(render_value(i) for i in value)) + "})"
    if isinstance(value, set):
        return "{" + ", ".join(sorted(render_value(item) for item in value)) + "}"
    if isinstance(value, dict):
        body = ", ".join(
            f"{render_value(k)}: {render_value(v)}" for k, v in value.items()
        )
        return "{" + body + "}"
    return repr(value)


def normalise_json(value: Any) -> Any:
    """POSIX-normalise any ``PurePath`` reachable inside a JSON-ish structure."""
    if isinstance(value, PurePath):
        return value.as_posix()
    if isinstance(value, dict):
        return {key: normalise_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalise_json(item) for item in value]
    return value


def flatten_dump(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dump to dotted leaf paths, for the G3 differential."""
    flat: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            flat.update(flatten_dump(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            flat.update(flatten_dump(item, f"{prefix}[{index}]"))
    else:
        flat[prefix] = normalise_json(value)
    return flat


def digest(value: Any) -> str:
    """Stable SHA-256 over a JSON-ish structure."""
    payload = json.dumps(
        normalise_json(value), sort_keys=True, ensure_ascii=True, default=repr
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# G2 -- environment read enumeration
# ---------------------------------------------------------------------------


@dataclass
class EnvScan:
    """Literal environment names found, and every non-literal read's location."""

    names: dict[str, str] = field(default_factory=dict)
    non_literal: list[str] = field(default_factory=list)
    scanned: list[str] = field(default_factory=list)


def movement_proof_paths(repo_root: Path) -> list[Path]:
    """``config.py`` plus ``config_models/**/*.py`` once e2 creates it."""
    paths = [repo_root / CONFIG_MODULE_RELPATH]
    models_dir = repo_root / CONFIG_MODELS_RELDIR
    if models_dir.is_dir():
        paths.extend(sorted(models_dir.rglob("*.py")))
    return [path for path in paths if path.is_file()]


def _decorator_names(node: ast.AST) -> list[str]:
    decorators = getattr(node, "decorator_list", [])
    names = []
    for decorator in decorators:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        names.append(str(getattr(target, "id", getattr(target, "attr", ""))))
    return names


def _env_mechanism(parents: dict[ast.AST, ast.AST], node: ast.AST) -> str:
    """Classify *where* a read sits: validator kind, or a plain function.

    A read inside a ``model_validator`` runs on every construction. A read
    inside a ``field_validator`` reaches a default only when the field carries
    ``validate_default=True``. A read in a module-level function reaches a
    default on no platform, which is the load-bearing reason ``XDG_DATA_HOME``
    is harmless -- *not* the measured zero, which was taken on Windows where
    ``resolve_archive_db_path`` takes the ``win32`` branch and the XDG line is
    unreachable. That measurement does not discriminate; the structure does.
    """
    function: ast.AST | None = None
    current = parents.get(node)
    while current is not None:
        if function is None and isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            function = current
        current = parents.get(current)
    if function is None:
        return "module-scope"
    decorators = _decorator_names(function)
    if "model_validator" in decorators:
        return "model-validator"
    if "field_validator" in decorators:
        return "config-field-validator"
    return "module-function"


def enumerate_env_reads(paths: list[Path]) -> EnvScan:
    """Collect literal environment names; anything unresolvable is a failure.

    ``os.environ.get(name)``, ``os.getenv(name)`` and ``os.environ[name]`` are
    all matched, through whatever binding reached ``os`` -- an ``import os as
    _os`` alias, a ``from os import environ`` name, a local ``env = os.environ``
    rebinding or a ``getattr(os, "environ")``. A non-literal argument is
    recorded rather than resolved: a name that cannot be enumerated cannot be
    run through the G3 differential, so it cannot be proven harmless, so it
    cannot be admitted.
    """
    scan = EnvScan()
    for path in paths:
        scan.scanned.append(path.name)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        bindings = _collect_os_bindings(tree)
        scan.non_literal.extend(
            f"{path.name}:{lineno} ({reason})" for lineno, reason in bindings.unresolved
        )

        consumed: set[int] = set()
        for node in ast.walk(tree):
            argument = _env_read_argument(node, bindings, consumed)
            if argument is None:
                continue
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                name = argument.value
                mechanism = _env_mechanism(parents, node)
                # A name read twice keeps the mechanism that reaches furthest.
                if name not in scan.names or scan.names[name] == "module-function":
                    scan.names[name] = mechanism
            else:
                scan.non_literal.append(
                    f"{path.name}:{argument.lineno} ({type(argument).__name__})"
                )

        for node in _escaping_environ_references(tree, bindings, consumed):
            scan.non_literal.append(
                f"{path.name}:{node.lineno} (environ reference this scan cannot "
                "follow)"
            )
    return scan


@dataclass
class _OsBindings:
    """Every module-local name that reaches ``os``, ``environ`` or ``getenv``.

    Flow-insensitive on purpose -- see the module docstring. The set is the
    union over the whole file, never per-branch.
    """

    #: Seeded with the canonical spelling so a read is still recognised in a
    #: fragment that never shows its import.
    os_names: set[str] = field(default_factory=lambda: {"os"})
    environ_names: set[str] = field(default_factory=set)
    getenv_names: set[str] = field(default_factory=set)
    unresolved: list[tuple[int, str]] = field(default_factory=list)


def _binding_sources(value: ast.expr) -> list[ast.expr]:
    """The expressions an assignment binds a name *to*, not the ones it calls.

    ``env = os.environ`` binds the mapping; ``x = os.getenv("A")`` binds a
    string. Descending into a ``Call`` would conflate the two and make ``x``
    look like a callable environment reader, so containers and conditionals are
    unwrapped and calls are not.
    """
    if isinstance(value, (ast.Tuple, ast.List)):
        return [item for element in value.elts for item in _binding_sources(element)]
    if isinstance(value, ast.BoolOp):
        return [item for element in value.values for item in _binding_sources(element)]
    if isinstance(value, ast.IfExp):
        return _binding_sources(value.body) + _binding_sources(value.orelse)
    return [value]


def _collect_os_bindings(tree: ast.AST) -> _OsBindings:
    """Resolve module-local aliases for ``os``, ``os.environ`` and ``os.getenv``.

    Iterated to a fixed point because a binding can be introduced after its
    first use in the file, and because ``a = os.environ`` followed by ``b = a``
    needs a second pass to reach ``b``.
    """
    bindings = _OsBindings()
    for _ in range(_BINDING_RESOLUTION_PASSES):
        before = (
            len(bindings.os_names),
            len(bindings.environ_names),
            len(bindings.getenv_names),
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "os":
                        bindings.os_names.add(alias.asname or "os")
                    elif alias.name.startswith("os.") and alias.asname is None:
                        # ``import os.path`` binds the top-level ``os`` name.
                        bindings.os_names.add("os")
            elif isinstance(node, ast.ImportFrom) and node.module == "os":
                for alias in node.names:
                    if alias.name == "environ":
                        bindings.environ_names.add(alias.asname or "environ")
                    elif alias.name == "getenv":
                        bindings.getenv_names.add(alias.asname or "getenv")
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                if node.value is None:
                    continue
                targets = (
                    list(node.targets) if isinstance(node, ast.Assign) else [node.target]
                )
                sources = _binding_sources(node.value)
                if any(_environ_reference(item, bindings) for item in sources):
                    bindings.environ_names.update(_plain_name_targets(targets))
                if any(_getenv_reference(item, bindings) for item in sources):
                    bindings.getenv_names.update(_plain_name_targets(targets))
        if (
            len(bindings.os_names),
            len(bindings.environ_names),
            len(bindings.getenv_names),
        ) == before:
            break

    for node in ast.walk(tree):
        attribute = _dynamic_os_attribute(node, bindings)
        if attribute is not None:
            bindings.unresolved.append(
                (attribute.lineno, "computed getattr on the os module")
            )
    return bindings


def _plain_name_targets(targets: list[ast.expr]) -> set[str]:
    """The module-local names an assignment binds, ignoring anything else.

    ``self.env = os.environ`` and ``cache["env"] = os.environ`` bind no name
    this scan can follow. Returning nothing for them is what lets
    :func:`_escaping_environ_references` report them instead of treating the
    assignment as having accounted for the mapping.
    """
    names: set[str] = set()
    for target in targets:
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Starred):
            names |= _plain_name_targets([target.value])
        elif isinstance(target, (ast.Tuple, ast.List)):
            names |= _plain_name_targets(list(target.elts))
    return names


def _os_module_reference(node: ast.AST, bindings: _OsBindings) -> bool:
    return isinstance(node, ast.Name) and node.id in bindings.os_names


def _os_getattr(node: ast.AST, bindings: _OsBindings) -> str | None:
    """The attribute name of a ``getattr(<os alias>, "literal")``, if any."""
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and _os_module_reference(node.args[0], bindings)
    ):
        return None
    attribute = node.args[1]
    if isinstance(attribute, ast.Constant) and isinstance(attribute.value, str):
        return attribute.value
    return None


def _dynamic_os_attribute(node: ast.AST, bindings: _OsBindings) -> ast.Call | None:
    """A ``getattr(os, <computed>)`` -- unresolvable, so it cannot be admitted."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and _os_module_reference(node.args[0], bindings)
        and _os_getattr(node, bindings) is None
    ):
        return node
    return None


def _environ_reference(node: ast.AST, bindings: _OsBindings) -> bool:
    """Whether an expression *provably* evaluates to the process environment.

    Requires a resolved ``os`` alias or a name this module bound to ``environ``.
    Binding and escape reporting both use this, because both produce a hard
    failure and a hard failure must not be reachable by an unrelated attribute
    that merely happens to be spelled ``environ`` -- a config model with an
    ``environ`` field is entirely plausible and is not this gate's business.
    """
    if isinstance(node, ast.Name):
        return isinstance(node.ctx, ast.Load) and node.id in bindings.environ_names
    if isinstance(node, ast.Attribute):
        return node.attr == "environ" and _os_module_reference(node.value, bindings)
    return _os_getattr(node, bindings) == "environ"


def _environ_read_receiver(node: ast.AST, bindings: _OsBindings) -> bool:
    """Whether an expression is *shaped like* the environment for a read.

    Looser than :func:`_environ_reference` on purpose, and only ever used to
    decide that something is a read. An unrecognised base -- ``posix.environ``,
    a re-exported shim -- yields an extra enumerated name, which fails loudly
    against the baseline and is trivially explained. Missing it would admit an
    undeclared read silently, which is the failure this gate exists to prevent.
    """
    if isinstance(node, ast.Attribute) and node.attr == "environ":
        return True
    return _environ_reference(node, bindings)


def _getenv_reference(node: ast.AST, bindings: _OsBindings) -> bool:
    """Whether an expression evaluates to ``os.getenv``."""
    if isinstance(node, ast.Name):
        return isinstance(node.ctx, ast.Load) and node.id in bindings.getenv_names
    if isinstance(node, ast.Attribute):
        return node.attr == "getenv" and _os_module_reference(node.value, bindings)
    return _os_getattr(node, bindings) == "getenv"


def _env_read_key(node: ast.Call) -> ast.expr:
    """The key expression of an ``os.getenv``/``environ.get`` call.

    ``os.getenv(key="NAME")`` reaches the environment exactly as the
    positional spelling does -- ``os.getenv`` and ``MutableMapping.get``
    (which is what ``os.environ`` inherits) both bind their first parameter
    as ``key``, so both accept it. Scanning only ``node.args`` let that
    spelling through with zero names and zero non-literals recorded, which
    is silence, not a pass.

    Returns the call itself when no key can be resolved -- ``os.getenv()``
    or ``os.getenv(**names)`` -- so an unreadable read is reported as
    non-literal instead of vanishing.
    """
    if node.args:
        return node.args[0]
    for keyword in node.keywords:
        if keyword.arg == "key":
            return keyword.value
    return node


def _env_read_argument(
    node: ast.AST, bindings: _OsBindings, consumed: set[int]
) -> ast.expr | None:
    """The name expression of an environment read, or ``None``.

    Records the receiver in *consumed* so
    :func:`_escaping_environ_references` can tell a read it resolved from an
    ``environ`` that leaked into an expression it cannot follow.
    """
    if isinstance(node, ast.Call):
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and _environ_read_receiver(func.value, bindings)
        ):
            consumed.add(id(func.value))
            return _env_read_key(node)
        if _getenv_reference(func, bindings):
            consumed.add(id(func))
            return _env_read_key(node)
    if isinstance(node, ast.Subscript) and _environ_read_receiver(node.value, bindings):
        consumed.add(id(node.value))
        return node.slice if isinstance(node.slice, ast.expr) else None
    return None


def _escaping_environ_references(
    tree: ast.AST, bindings: _OsBindings, consumed: set[int]
) -> list[ast.expr]:
    """``environ`` references that neither a read nor a binding accounted for.

    ``dict(os.environ)`` and ``helper(os.environ)`` hand the mapping to code
    this scan does not follow, ``self.env = os.environ`` parks it on an
    attribute, and ``os.environ.setdefault(...)`` reads through an accessor it
    does not model. Each is reported rather than ignored: an undeclared read
    that nothing reports is the defect this gate exists to prevent.
    """
    bound: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and node.value:
            targets = (
                list(node.targets) if isinstance(node, ast.Assign) else [node.target]
            )
            # Only an assignment that bound a followable name accounts for its
            # source; anything else merely moved the mapping out of sight.
            if _plain_name_targets(targets):
                bound.update(id(item) for item in _binding_sources(node.value))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.expr)
        and _environ_reference(node, bindings)
        and id(node) not in consumed
        and id(node) not in bound
    ]



# ---------------------------------------------------------------------------
# G1/G3 -- scrubbed child processes
# ---------------------------------------------------------------------------


def scrubbed_env(
    repo_root: Path,
    scrub_names: set[str],
    inject: tuple[str, str] | None = None,
) -> dict[str, str]:
    """Build the child environment explicitly rather than inheriting it.

    Every ``PROBOS_*`` name and every G2-enumerated name is removed, so the
    capture cannot bake in the operator's shell. Only names are ever handled
    here; the ambient environment holds secrets and no value is copied into a
    log, an error or the baseline.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PROBOS_") and key not in scrub_names
    }
    env["PYTHONPATH"] = str(repo_root / "src")
    env[_INJECTED_MARKER] = ""
    if inject is not None:
        env[inject[0]] = inject[1]
        env[_INJECTED_MARKER] = inject[0]
    return env


def run_child(
    repo_root: Path,
    emit: str,
    scrub_names: set[str],
    inject: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """Run this script in a fresh interpreter with an explicitly-built env."""
    proc = subprocess.run(
        [sys.executable, "-P", str(Path(__file__).resolve()), "--emit", emit],
        env=scrubbed_env(repo_root, scrub_names, inject),
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    label = inject[0] if inject else "canonical"
    if proc.returncode != 0:
        raise ChildFailure(
            f"capture child for {label} exited {proc.returncode}: "
            f"{proc.stderr.strip()[-800:]}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as error:  # pragma: no cover - defensive
        raise ChildFailure(
            f"capture child for {label} produced unparsable output: {error}"
        ) from error


# ---------------------------------------------------------------------------
# Child side -- the only code that imports probos.config
# ---------------------------------------------------------------------------


def _assert_child_scrubbed() -> None:
    """Fail loudly if the parent's env-build let a ``PROBOS_*`` name through.

    Without this the harness cannot tell a scrubbed capture from an inherited
    one, and an inherited one is exactly the artifact this slice exists to
    prevent.
    """
    injected = os.environ.get(_INJECTED_MARKER, "")
    allowed = {injected} if injected else set()
    leaked = sorted(
        name
        for name in os.environ
        if name.startswith("PROBOS_") and name not in allowed
    )
    if leaked:
        raise SystemExit(
            "capture environment is not scrubbed; these names leaked into the "
            f"child (names only, never values): {leaked}"
        )


def _import_facade() -> ModuleType:
    src = str(_REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    import probos.config as facade

    return facade


def owns(module: str | None) -> bool:
    """Whether a defining module is *inside* the facade's own contract.

    Ownership cannot be ``__module__ == probos.config``: that is the one
    predicate a legitimate AD-1270e2 extraction is guaranteed to break. Moving
    ``SensoriumConfig`` to ``probos.config_models.sensorium`` and re-exporting
    it changes nothing a consumer can observe -- same class object, qualname,
    MRO, fields and schema digest, measured -- yet reclassifies it as import
    leakage and fails on four counts. A baseline a correct move cannot pass is
    worse than no baseline, because the only way past it is to regenerate, and
    a regenerated baseline proves nothing.

    Nor is it ``__module__.startswith("probos.")``. That would re-own genuine
    leakage -- a ``from probos.types import X`` is exactly what the incidental
    tier exists to record -- and, worse, would let e2 move models into some
    other package while still reading ``owned``, with G2's environment scan
    pointed at ``config_models/`` and therefore blind, and both tripwires
    silent because they only fire once that directory exists.

    So ownership is the facade *or the package G2 already scans*, derived from
    one constant. A move to any other destination fails loudly here, and the
    only fix is to point both at the same place.
    """
    if not module:
        return False
    if module == FACADE_MODULE or module == CONFIG_MODELS_PACKAGE:
        return True
    return module.startswith(f"{CONFIG_MODELS_PACKAGE}.")


def _classify(obj: Any) -> tuple[str, str]:
    """Return ``(kind, tier)`` for a public name.

    ``tier: owned`` is the 291-name contract. ``tier: incidental`` is the 13
    names that leaked in through ``import`` -- recorded so nothing is invisible,
    but removable in e3 without breaking the contract.
    """
    if isinstance(obj, ModuleType):
        return "module", "incidental"
    if isinstance(obj, type):
        kind = "model" if issubclass(obj, BaseModel) else "class"
        owned = owns(getattr(obj, "__module__", None))
        return kind, "owned" if owned else "incidental"
    if callable(obj):
        owned = owns(getattr(obj, "__module__", None))
        return "function", "owned" if owned else "incidental"
    if type(obj).__module__ == "builtins":
        return "constant", "owned"
    return "other", "incidental"


def _accepted_names(field_info: Any, field_name: str) -> list[str]:
    """The set of input keys Pydantic will accept for a field.

    With ``populate_by_name`` off everywhere (measured: zero models carry a
    non-empty ``model_config``) and Pydantic's default ``extra='ignore'``, a
    field whose accepted names exclude its own name silently swallows the
    field-name spelling and falls back to its default. An existing
    ``config/system.yaml`` key would stop working with no error at all, which is
    why that shape is a hard failure rather than a recorded fact.
    """
    validation_alias = getattr(field_info, "validation_alias", None)
    alias = getattr(field_info, "alias", None)
    if validation_alias is not None:
        choices = getattr(validation_alias, "choices", None)
        if choices is not None:
            return [choice for choice in choices if isinstance(choice, str)]
        if isinstance(validation_alias, str):
            return [validation_alias]
        return []
    if alias is not None:
        return [alias]
    return [field_name]


@dataclass
class ModelRecord:
    """One model's frozen identity, plus what inspecting it revealed."""

    record: dict[str, Any]
    aliased_fields: int = 0
    alias_violations: list[str] = field(default_factory=list)
    derived_order_violations: list[str] = field(default_factory=list)
    instantiable: bool = True
    schema_available: bool = True


def model_record(name: str, model: type[BaseModel]) -> ModelRecord:
    """Freeze one model, recording rather than raising on the awkward ones.

    Six models raise on ``M()`` and ``BaseModel`` raises on
    ``model_json_schema()``. A generator that crashes on the first one produces
    a partial baseline that looks complete, so both are recorded and the run
    continues; ``--check`` then asserts the recorded lists have not silently
    shrunk.
    """
    result = ModelRecord(record={})
    declared = list(model.model_fields)

    entries: list[dict[str, Any]] = []
    for field_name in declared:
        info = model.model_fields[field_name]
        entry: dict[str, Any] = {
            "name": field_name,
            "default": render_value(getattr(info, "default", PydanticUndefined)),
        }
        if getattr(info, "default_factory", None) is not None:
            entry["has_default_factory"] = True
        if getattr(info, "validate_default", None):
            entry["validate_default"] = True
        accepted = _accepted_names(info, field_name)
        if accepted != [field_name]:
            result.aliased_fields += 1
            entry["accepted_names"] = accepted
            serialization = getattr(info, "serialization_alias", None)
            if serialization is not None:
                entry["serialization_alias"] = serialization
            plain = getattr(info, "alias", None)
            if plain is not None:
                entry["alias"] = plain
        if field_name not in accepted:
            result.alias_violations.append(f"{name}.{field_name} accepts {accepted}")
        entries.append(entry)

    schema_digest: str | None = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            schema = model.model_json_schema()
    except Exception:
        result.schema_available = False
        schema = None
    if schema is not None:
        schema_digest = digest(schema)
        properties = list(schema.get("properties", {}))
        if properties != declared:
            result.derived_order_violations.append(
                f"{name}: schema properties order {properties} != declared "
                f"order {declared}"
            )

    try:
        instance: BaseModel | None = model()
    except Exception:
        result.instantiable = False
        instance = None
    if instance is not None:
        dumped = list(instance.model_dump())
        if dumped != declared:
            result.derived_order_violations.append(
                f"{name}: model_dump() order {dumped} != declared order {declared}"
            )
        if list(instance.model_dump(by_alias=True)) != dumped:
            result.derived_order_violations.append(
                f"{name}: model_dump(by_alias=True) order differs from "
                "model_dump() order"
            )

    result.record = {
        "qualname": model.__qualname__,
        "bases": [base.__qualname__ for base in model.__mro__[1:]],
        "schema_sha256": schema_digest,
        "fields": entries,
    }
    return result


def build_surface() -> dict[str, Any]:
    """Introspect the facade. Runs only inside a scrubbed child."""
    import pydantic

    facade = _import_facade()
    public = sorted(name for name in vars(facade) if not name.startswith("_"))

    names: dict[str, dict[str, str]] = {}
    models: dict[str, dict[str, Any]] = {}
    constants: dict[str, str] = {}
    non_instantiable: list[str] = []
    schema_unavailable: list[str] = []
    with_model_config: list[str] = []
    derived_violations: list[str] = []
    alias_violations: list[str] = []
    field_definitions = 0
    aliased_fields = 0

    for name in public:
        obj = getattr(facade, name)
        kind, tier = _classify(obj)
        row: dict[str, str] = {"kind": kind, "tier": tier}
        if tier == "incidental":
            row["removable_in"] = "e3"
        names[name] = row
        if kind == "constant":
            constants[name] = render_value(obj)
        if kind != "model":
            continue

        if getattr(obj, "model_config", None):
            with_model_config.append(name)
        inspected = model_record(name, obj)
        field_definitions += len(obj.model_fields)
        aliased_fields += inspected.aliased_fields
        alias_violations.extend(inspected.alias_violations)
        derived_violations.extend(inspected.derived_order_violations)
        if not inspected.instantiable:
            non_instantiable.append(name)
        if not inspected.schema_available:
            schema_unavailable.append(name)
        models[name] = inspected.record

    system = facade.SystemConfig()
    flat = flatten_dump(system.model_dump(mode="json"))

    owned = sum(1 for row in names.values() if row["tier"] == "owned")
    return {
        "pydantic_version": pydantic.VERSION,
        "counts": {
            "public_names": len(names),
            "owned": owned,
            "incidental": len(names) - owned,
            "own_models": sum(
                1
                for name, row in names.items()
                if row["kind"] == "model" and row["tier"] == "owned"
            ),
            "field_definitions": field_definitions,
            "aliased_fields": aliased_fields,
            "canonical_dump_leaves": len(flat),
        },
        "names": names,
        "constants": constants,
        "models": models,
        "non_instantiable": sorted(non_instantiable),
        "schema_unavailable": sorted(schema_unavailable),
        "models_with_model_config": sorted(with_model_config),
        "canonical_dump_sha256": digest(flat),
        "canonical_flat": flat,
        "derived_order_violations": sorted(derived_violations),
        "alias_violations": sorted(alias_violations),
    }


def _emit(mode: str) -> int:
    _assert_child_scrubbed()
    if mode == "capture":
        payload = build_surface()
    elif mode == "dump":
        facade = _import_facade()
        payload = {"flat": flatten_dump(facade.SystemConfig().model_dump(mode="json"))}
    else:  # pragma: no cover - argparse constrains the choices
        raise SystemExit(f"unknown emit mode: {mode}")
    json.dump(payload, sys.stdout, sort_keys=True)
    return 0


# ---------------------------------------------------------------------------
# Tripwires -- read by AST, never imported
# ---------------------------------------------------------------------------


def _module_assignment(source: str, target: str) -> ast.expr | None:
    tree = ast.parse(source)
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for item in targets:
            if isinstance(item, ast.Name) and item.id == target and node.value:
                return node.value
    return None


def config_profiles_scan_is_single_file(source: str) -> bool:
    """Whether ``check_config_profiles`` still scans exactly one module file.

    Read by AST because that script imports ``probos.config`` at module scope,
    and this process must never do that: an ambient-environment value reaching
    a comparison here is the whole failure mode the slice guards against.
    """
    value = _module_assignment(source, "_DEFAULT_CONFIG_MODULE")
    if value is None:
        return False
    literals = [
        node.value
        for node in ast.walk(value)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    # Any ``.py`` component means the scan terminates at one module file.
    # Deliberately not "the last literal": ``ast.walk`` is breadth-first, so on
    # ``_REPO_ROOT / "src" / "probos" / "config.py"`` it yields the filename
    # first and ``"src"`` last.
    return any(literal.endswith(".py") for literal in literals)


def blast_radius_patterns(source: str) -> list[str]:
    """The literal ``BLAST_RADIUS_PATTERNS`` strings from ``select_tests``."""
    value = _module_assignment(source, "BLAST_RADIUS_PATTERNS")
    if value is None:
        return []
    return [
        node.value
        for node in ast.walk(value)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def tripwire_problems(repo_root: Path) -> list[str]:
    """Fail the moment e2 creates ``config_models/`` without its two updates."""
    problems: list[str] = []
    if not (repo_root / CONFIG_MODELS_RELDIR).is_dir():
        return problems

    profiles = repo_root / "scripts" / "check_config_profiles.py"
    if profiles.is_file() and config_profiles_scan_is_single_file(
        profiles.read_text(encoding="utf-8")
    ):
        problems.append(
            "facade-tripwire-config-profiles-scan: "
            f"{CONFIG_MODELS_RELDIR}/ exists but "
            "check_config_profiles._DEFAULT_CONFIG_MODULE still resolves to a "
            "single file, so its real->declared environment gate now scans a "
            "module the models have left and passes blind. AD-1270e2 owns this "
            "fix; widen it to the package in the same commit."
        )

    selector = repo_root / "scripts" / "select_tests.py"
    if selector.is_file():
        patterns = blast_radius_patterns(selector.read_text(encoding="utf-8"))
        probe = f"{CONFIG_MODELS_RELDIR}/example.py"
        if not any(fnmatch.fnmatch(probe, pattern) for pattern in patterns):
            problems.append(
                "facade-tripwire-selector-blast-radius: "
                f"{CONFIG_MODELS_RELDIR}/ exists but no "
                "select_tests.BLAST_RADIUS_PATTERNS entry matches it, so a "
                "config-model change no longer selects the full suite. "
                "AD-1270e2 adds the pattern in the same commit that creates "
                "the directory."
            )
    return problems


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    """Strip YAML flow-style wrappers so stored and captured data compare."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def compare_surface(stored: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """Every drift, each with its own message. Nothing short-circuits."""
    problems: list[str] = []

    stored_pydantic = stored.get("pydantic_version")
    actual_pydantic = actual.get("pydantic_version")
    pydantic_moved = bool(stored_pydantic) and stored_pydantic != actual_pydantic
    if pydantic_moved:
        problems.append(
            "facade-pydantic-version: baseline was generated against pydantic "
            f"{stored_pydantic}, this interpreter has {actual_pydantic}. Schema "
            "digests are not comparable across versions; regenerate the "
            "baseline and review the resulting diff."
        )

    stored_counts = _plain(stored.get("surface_counts") or {})
    actual_counts = _plain(actual.get("counts") or {})
    for key in sorted(set(stored_counts) | set(actual_counts)):
        if stored_counts.get(key) != actual_counts.get(key):
            problems.append(
                f"facade-counts: {key} {stored_counts.get(key)!r} -> "
                f"{actual_counts.get(key)!r}"
            )

    stored_names = _plain(stored.get("names") or {})
    actual_names = _plain(actual.get("names") or {})
    for name in sorted(set(stored_names) - set(actual_names)):
        tier = (stored_names[name] or {}).get("tier", "owned")
        problems.append(
            f"facade-symbol-removed: {tier} name {name!r} is no longer exported "
            f"by {FACADE_MODULE}"
        )
    for name in sorted(set(actual_names) - set(stored_names)):
        problems.append(
            f"facade-symbol-added: {name!r} is exported by {FACADE_MODULE} and "
            "has no baseline row"
        )
    for name in sorted(set(stored_names) & set(actual_names)):
        before, after = stored_names[name], actual_names[name]
        for key in ("kind", "tier"):
            if before.get(key) != after.get(key):
                problems.append(
                    f"facade-symbol-kind: {name!r} {key} "
                    f"{before.get(key)!r} -> {after.get(key)!r}"
                )

    stored_constants = _plain(stored.get("constants") or {})
    actual_constants = _plain(actual.get("constants") or {})
    for name in sorted(set(stored_constants) & set(actual_constants)):
        if stored_constants[name] != actual_constants[name]:
            problems.append(
                f"facade-constant-value: {name} {stored_constants[name]} -> "
                f"{actual_constants[name]}"
            )

    stored_models = _plain(stored.get("models") or {})
    actual_models = _plain(actual.get("models") or {})
    for name in sorted(set(stored_models) & set(actual_models)):
        before, after = stored_models[name], actual_models[name]
        if before.get("qualname") != after.get("qualname"):
            problems.append(
                f"facade-model-qualname: {name} {before.get('qualname')!r} -> "
                f"{after.get('qualname')!r}"
            )
        if before.get("bases") != after.get("bases"):
            problems.append(
                f"facade-model-bases: {name} MRO {before.get('bases')} -> "
                f"{after.get('bases')}. A re-export keeps the MRO; a wrapper or "
                "subclass does not."
            )
        if not pydantic_moved and before.get("schema_sha256") != after.get(
            "schema_sha256"
        ):
            problems.append(
                f"facade-schema-digest: {name} {before.get('schema_sha256')} -> "
                f"{after.get('schema_sha256')} (a type or constraint changed)"
            )
        problems.extend(_compare_fields(name, before, after))

    return problems


def _compare_fields(
    name: str, before: dict[str, Any], after: dict[str, Any]
) -> list[str]:
    problems: list[str] = []
    stored_fields = before.get("fields") or []
    actual_fields = after.get("fields") or []
    stored_order = [entry.get("name") for entry in stored_fields]
    actual_order = [entry.get("name") for entry in actual_fields]
    if stored_order != actual_order:
        if set(stored_order) == set(actual_order):
            problems.append(
                f"facade-field-order: {name} field order {stored_order} -> "
                f"{actual_order} (same fields, reordered; dump and schema "
                "property order derive from this)"
            )
        else:
            for missing in sorted(set(stored_order) - set(actual_order)):
                problems.append(f"facade-field-removed: {name}.{missing}")
            for added in sorted(set(actual_order) - set(stored_order)):
                problems.append(f"facade-field-added: {name}.{added}")
        return problems

    stored_by_name = {entry.get("name"): entry for entry in stored_fields}
    actual_by_name = {entry.get("name"): entry for entry in actual_fields}
    for field_name in stored_order:
        old, new = stored_by_name[field_name], actual_by_name[field_name]
        if old.get("default") != new.get("default"):
            problems.append(
                f"facade-field-default: {name}.{field_name} "
                f"{old.get('default')} -> {new.get('default')}"
            )
        for key in ("has_default_factory", "validate_default"):
            if bool(old.get(key)) != bool(new.get(key)):
                problems.append(
                    f"facade-field-flag: {name}.{field_name} {key} "
                    f"{bool(old.get(key))} -> {bool(new.get(key))}"
                )
        old_accepted = old.get("accepted_names") or [field_name]
        new_accepted = new.get("accepted_names") or [field_name]
        if old_accepted != new_accepted:
            problems.append(
                f"facade-field-alias: {name}.{field_name} accepted names "
                f"{old_accepted} -> {new_accepted}"
            )
    return problems


def check_environment(
    repo_root: Path,
    stored: dict[str, Any],
    canonical_flat: dict[str, Any],
    scan: EnvScan,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Run G3 against the G2 scan, reporting every disagreement with the rows."""
    problems: list[str] = []

    for location in scan.non_literal:
        problems.append(
            f"facade-env-nonliteral: unresolvable environment read at {location}. "
            "A name that cannot be enumerated cannot be run through the "
            "differential, so it cannot be proven harmless. Read it as a string "
            "literal through os.environ.get / os.getenv / os.environ[...]."
        )

    declared_rows = {
        row.get("name"): _plain(row)
        for row in (stored.get("environment") or {}).get("reads") or []
        if isinstance(row, dict)
    }
    # The control is a declared row but is deliberately unreadable by the
    # facade, so it can never appear in a G2 enumeration. Comparing it against
    # one would report it stale on every run.
    declared_reads = set(declared_rows) - {CONTROL_VARIABLE}
    for name in sorted(set(scan.names) - declared_reads):
        problems.append(
            f"facade-env-undeclared: {FACADE_MODULE} reads {name!r} and the "
            "baseline has no row for it. Regenerate the baseline and review "
            "what the new read moves."
        )
    for name in sorted(declared_reads - set(scan.names)):
        problems.append(
            f"facade-env-stale: baseline declares {name!r} but no enumerated "
            "read remains; delete the row in the same commit."
        )

    scrub = set(scan.names) | {CONTROL_VARIABLE}
    measured: list[dict[str, Any]] = []
    for name in sorted(set(scan.names) | {CONTROL_VARIABLE}):
        is_control = name == CONTROL_VARIABLE
        sentinel = _SENTINEL_VALUES.get(name, _DEFAULT_SENTINEL)
        child = run_child(repo_root, "dump", scrub, inject=(name, sentinel))
        other = child["flat"]
        moved = sorted(
            key
            for key in set(canonical_flat) | set(other)
            if canonical_flat.get(key, _MISSING) != other.get(key, _MISSING)
        )
        row: dict[str, Any] = {"name": name, "moves": moved}
        if is_control:
            row["mechanism"] = "control"
            row["reaches_defaults"] = False
            if moved:
                problems.append(
                    "facade-env-control: the control variable "
                    f"{CONTROL_VARIABLE!r} moved {moved}. Nothing reads it, so "
                    "the differential harness is broken and every other "
                    "environment row it produced is meaningless."
                )
            measured.append(row)
            continue


        mechanism = scan.names[name]
        reaches = mechanism in {"model-validator", "config-field-validator"}
        row["mechanism"] = mechanism
        row["reaches_defaults"] = reaches
        declared = declared_rows.get(name, {})
        declared_moves = list(declared.get("moves") or [])
        if declared_moves != moved:
            problems.append(
                f"facade-env-differential: {name!r} moves {moved}, the baseline "
                f"declares {declared_moves}. An environment read whose blast "
                "radius widened is a new contract, not a regeneration."
            )
        if declared and declared.get("mechanism") != mechanism:
            problems.append(
                f"facade-env-mechanism: {name!r} mechanism "
                f"{declared.get('mechanism')!r} -> {mechanism!r}"
            )
        if reaches and not moved:
            problems.append(
                f"facade-env-differential: {name!r} sits in a {mechanism} and "
                "should reach a default, but the differential measured zero "
                "moved paths. The harness has not shown a known mover, so it "
                "has asserted nothing."
            )
        if not reaches and moved:
            problems.append(
                f"facade-env-differential: {name!r} is declared structurally "
                f"unable to reach a default ({mechanism}) yet moved {moved}."
            )
        measured.append(row)
    return problems, measured


# ---------------------------------------------------------------------------
# Baseline document
# ---------------------------------------------------------------------------


class _Flow(dict):
    """A mapping rendered on one YAML line, so one field is one diff line."""


class _BaselineDumper(yaml.SafeDumper):
    """A private dumper, so importing this module mutates no shared global."""


_BaselineDumper.add_representer(
    _Flow,
    lambda dumper, data: dumper.represent_mapping(
        "tag:yaml.org,2002:map", data, flow_style=True
    ),
)


DEFAULT_REVIEW: dict[str, str] = {
    "owner": "AD-1270e1",
    "rationale": (
        "AD-1270e2/e3 move 224 models out of a 304-name module that 703 tracked "
        "files import. Freezing imports, defaults, aliases, schema digests and "
        "field order first means an extraction that changes behaviour shows up "
        "as a data diff on the exact symbol, not as a large mechanical rename "
        "nobody can read. The five dimensions are one document because a "
        "reviewer comparing a moved model wants one place to look, and because "
        "a per-domain split would pre-commit the domain boundary e2 is supposed "
        "to decide."
    ),
    "review_by": (
        "AD-1270e3 has landed the thin permanent facade and every incidental "
        "row is gone, or a domain partition exists and this file has been split "
        "to match it."
    ),
}

HANDOFF_TO_E2: list[str] = [
    "Widen check_config_profiles._DEFAULT_CONFIG_MODULE from a single file to "
    "the config_models package. Its real->declared environment gate scans one "
    "path and goes blind the moment models move; the config-facade checker "
    "fails the day the directory appears so this cannot be forgotten.",
    "Add a select_tests.BLAST_RADIUS_PATTERNS entry covering "
    "src/probos/config_models/*. src/probos/config.py is a blast-radius entry "
    "today; a moved model must keep selecting the full suite. Add it in the "
    "same commit that creates the directory -- changing the selector "
    "invalidates selector claims about that same tree, so it cannot be done "
    "here in advance.",
    "Re-export moved models from probos.config, and move them into "
    "src/probos/config_models/. Identity is compared by qualname, MRO bases "
    "and ordered fields, never by __module__, so a re-export passes and a "
    "wrapper, subclass or partial clone fails. Ownership -- the owned/incidental "
    "tier -- does read __module__, and accepts probos.config or that one "
    "package, because it is the same directory G2 scans for environment reads. "
    "A move anywhere else fails here rather than silently keeping the tier "
    "while the environment scan goes blind.",
    "Regenerating this baseline is expected during e2/e3. Regenerating it to "
    "make a failure go away is not: every row here is a behaviour a consumer "
    "already depends on.",
]


def render_baseline(surface: dict[str, Any], environment: list[dict[str, Any]]) -> str:
    """Render the committed document. Order is explicit, never hash order."""
    models: dict[str, Any] = {}
    for name in sorted(surface["models"]):
        record = surface["models"][name]
        models[name] = {
            "qualname": record["qualname"],
            "bases": list(record["bases"]),
            "schema_sha256": record["schema_sha256"],
            "fields": [_Flow(entry) for entry in record["fields"]],
        }

    document: dict[str, Any] = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "baseline_id": BASELINE_ID,
        "epic": 1324,
        "review": dict(DEFAULT_REVIEW),
        "handoff_to_e2": list(HANDOFF_TO_E2),
        "pydantic_version": surface["pydantic_version"],
        "surface_counts": dict(surface["counts"]),
        "canonical_dump_sha256": surface["canonical_dump_sha256"],
        "non_instantiable": list(surface["non_instantiable"]),
        "schema_unavailable": list(surface["schema_unavailable"]),
        "models_with_model_config": list(surface["models_with_model_config"]),
        "environment": {
            "control_variable": CONTROL_VARIABLE,
            "reads": [
                _Flow(
                    {
                        "name": row["name"],
                        "mechanism": row["mechanism"],
                        "reaches_defaults": row["reaches_defaults"],
                        "moves": list(row["moves"]),
                    }
                )
                for row in environment
            ],
        },
        "constants": {
            name: surface["constants"][name] for name in sorted(surface["constants"])
        },
        "names": {
            name: _Flow(surface["names"][name]) for name in sorted(surface["names"])
        },
        "models": models,
    }
    body = yaml.dump(
        document,
        Dumper=_BaselineDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10**9,
    )
    return _HEADER + body


def load_baseline(path: Path) -> tuple[dict[str, Any], list[str]]:
    """Parse the baseline; a malformed or unreviewed document is a failure."""
    problems: list[str] = []
    if not path.is_file():
        return {}, [
            f"facade-baseline-missing: {path.as_posix()} does not exist; run "
            "python scripts/check_config_facade.py --update-baseline"
        ]
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return {}, [f"facade-baseline-schema: {path.as_posix()} is not valid YAML: {error}"]
    if not isinstance(document, dict):
        return {}, [f"facade-baseline-schema: {path.as_posix()} is not a mapping"]
    if document.get("schema_version") != BASELINE_SCHEMA_VERSION:
        problems.append(
            f"facade-baseline-schema: schema_version "
            f"{document.get('schema_version')!r} != {BASELINE_SCHEMA_VERSION}"
        )
    if document.get("baseline_id") != BASELINE_ID:
        problems.append(
            f"facade-baseline-schema: baseline_id {document.get('baseline_id')!r} "
            f"!= {BASELINE_ID!r}"
        )
    review = document.get("review")
    if not isinstance(review, dict):
        problems.append("facade-baseline-schema: review block is missing")
    else:
        for key in ("owner", "rationale", "review_by"):
            if not str(review.get(key) or "").strip():
                problems.append(
                    f"facade-baseline-schema: review.{key} is blank; a "
                    "placeholder would pass a non-blank test and ship unreviewed"
                )
    return document, problems


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)


def check(baseline_path: Path, repo_root: Path = _REPO_ROOT) -> CheckResult:
    """Run every gate, accumulate every problem, report them all once."""
    started = time.monotonic()
    errors: list[str] = []

    document, baseline_problems = load_baseline(baseline_path)
    errors.extend(baseline_problems)

    scan = enumerate_env_reads(movement_proof_paths(repo_root))
    scrub = set(scan.names) | {CONTROL_VARIABLE}
    try:
        surface = run_child(repo_root, "capture", scrub)
    except ChildFailure as failure:
        errors.append(f"facade-capture: {failure}")
        return CheckResult(errors=errors, report={"elapsed_seconds": 0.0})

    errors.extend(
        f"facade-derived-order: {violation}. model_dump() and schema property "
        "order derive from declaration order; a divergence is a Pydantic "
        "behaviour change, not a regeneration."
        for violation in surface["derived_order_violations"]
    )
    errors.extend(
        f"facade-alias-excludes-field-name: {violation}. With populate_by_name "
        "off and extra='ignore', the field-name spelling would be swallowed "
        "with no error and the field would silently take its default."
        for violation in surface["alias_violations"]
    )

    stored_config = _plain(document.get("models_with_model_config") or [])
    if stored_config != surface["models_with_model_config"]:
        errors.append(
            "facade-model-config: models carrying a non-empty model_config "
            f"{stored_config} -> {surface['models_with_model_config']}. "
            "model_config decides populate_by_name and extra handling for every "
            "field on the model, so this is a facade-wide behaviour change."
        )
    for key, label in (
        ("non_instantiable", "facade-non-instantiable"),
        ("schema_unavailable", "facade-schema-unavailable"),
    ):
        stored_list = _plain(document.get(key) or [])
        if stored_list != surface[key]:
            errors.append(
                f"{label}: {stored_list} -> {surface[key]}. A silently shrinking "
                "list means the generator crashed early and produced a partial "
                "baseline that looks complete."
            )

    errors.extend(compare_surface(document, surface))

    # The capture child already built SystemConfig() for the derived-order
    # invariants, so its flattened dump is the canonical one -- re-running it in
    # a second child would cost another interpreter start to learn the same
    # bytes.
    canonical_flat: dict[str, Any] = surface.get("canonical_flat") or {}
    measured: list[dict[str, Any]] = []
    if canonical_flat:
        stored_digest = document.get("canonical_dump_sha256")
        if stored_digest and stored_digest != digest(canonical_flat):
            errors.append(
                "facade-canonical-dump: the resolved SystemConfig() dump digest "
                f"{stored_digest} no longer matches. A nested model default "
                "changed; the per-field rows above name which one."
            )
        try:
            env_problems, measured = check_environment(
                repo_root, document, canonical_flat, scan
            )
            errors.extend(env_problems)
        except ChildFailure as failure:
            errors.append(f"facade-env-differential: {failure}")

    errors.extend(tripwire_problems(repo_root))

    elapsed = time.monotonic() - started
    if elapsed > SELF_TIMEOUT_SECONDS:
        errors.append(
            f"facade-timeout: the check took {elapsed:.2f}s, over its "
            f"{SELF_TIMEOUT_SECONDS:.1f}s budget. It runs as a preflight phase; "
            "a check that grows into the gate budget is a check nobody keeps. "
            "Reduce the differential row count or move it to a pytest phase."
        )
    return CheckResult(
        errors=errors,
        report={
            "elapsed_seconds": round(elapsed, 3),
            "counts": surface["counts"],
            "environment": measured,
            "non_literal_env_reads": scan.non_literal,
            "scanned_modules": scan.scanned,
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Configuration facade contract check")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate and exit non-zero on any drift (writes nothing)",
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
        "--emit",
        choices=("capture", "dump"),
        help=argparse.SUPPRESS,  # internal: the scrubbed child entry point
    )
    parser.add_argument("--json", metavar="PATH", help="also write the report")
    parser.add_argument("--baseline", metavar="PATH", default=str(_DEFAULT_BASELINE))
    parser.add_argument("--repo-root", metavar="PATH", default=str(_REPO_ROOT))
    args = parser.parse_args(argv)

    if args.emit:
        return _emit(args.emit)

    baseline_path = Path(args.baseline)
    repo_root = Path(args.repo_root)

    if args.update_baseline:
        scan = enumerate_env_reads(movement_proof_paths(repo_root))
        if scan.non_literal:
            print(
                "refusing to write a baseline while a computed environment name "
                f"exists: {scan.non_literal}",
                file=sys.stderr,
            )
            return 1
        scrub = set(scan.names) | {CONTROL_VARIABLE}
        surface = run_child(repo_root, "capture", scrub)
        _, measured = check_environment(
            repo_root, {}, surface["canonical_flat"], scan
        )
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            render_baseline(surface, measured), encoding="utf-8"
        )
        print(
            f"wrote {baseline_path.as_posix()}; review every row before committing"
        )
        return 0

    result = check(baseline_path=baseline_path, repo_root=repo_root)

    if args.json:
        Path(args.json).write_text(
            json.dumps(result.report, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )

    if result.errors:
        print(
            f"config facade check failed with {len(result.errors)} problem(s):",
            file=sys.stderr,
        )
        for problem in result.errors:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    counts = result.report["counts"]
    print(
        "config facade check passed ("
        f"names={counts['public_names']}, owned={counts['owned']}, "
        f"incidental={counts['incidental']}, models={counts['own_models']}, "
        f"fields={counts['field_definitions']}, "
        f"env rows={len(result.report['environment'])}, "
        f"{result.report['elapsed_seconds']}s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
