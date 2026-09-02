#!/usr/bin/env python
"""AD-1185 config-profile contract checker.

Gates, all of which fail the build:

1. **Profile registration** -- ``config/profiles/`` holds exactly
   ``probos.config_profiles.PROFILE_IDS``, and every profile loads through the
   real loader (which pre-validates override keys and enforces the rule graph).
2. **Manifest -> model** -- every ``flags[].path`` resolves to a boolean field
   on ``SystemConfig``. An unresolvable path is a broken row, not a missing
   flag.
3. **Model -> manifest** -- every default-``False`` boolean reachable from
   ``SystemConfig`` is either classified or frozen in ``unclassified_flags``,
   and never both. A NEW flag lands in neither and fails on day one.
4. **Admission** -- every path a profile arms has a row; a path ``supported``
   arms is ``product-feature`` or ``security-control`` with non-empty
   ``evidence_to_promote``; ``profiles:`` agrees with the profiles in both
   directions.
5. **Rules do not fire on tracked configs** -- every declared ``requires`` /
   ``conflicts_with`` is evaluated against ``SystemConfig()``,
   ``config/system.yaml``, ``config/node-1.yaml`` and ``config/node-2.yaml``.
   A rule that would break a tracked config cannot be merged. All four
   evaluations appear in ``--json`` so the property is visible, not implied.
6. **CI divergences, both directions** -- declared->real over
   ``tests/conftest.py``, and real->declared over the environment reads in
   ``src/probos/config.py``.
7. **The smoke still exists and still runs** -- the manifest's
   ``smoke_test_node_id`` is resolved by AST and asserted to carry no
   skip/skipif/xfail marker. A skipped smoke is a non-passing smoke.

Every check accumulates; one run reports every problem.

**"Reaches a default" is decided by validator kind, not by
``validate_default``.** Measured 2026-09-02: ``CognitiveConfig._apply_env_overrides``
is a ``@model_validator(mode="after")``, so ``PROBOS_LLM_URL`` moves the
``SystemConfig()`` dump (sha ``8246174c4f0c9cbe`` -> ``157cd9fac26d6147``)
despite no field carrying ``validate_default=True``. A criterion keyed on
``validate_default`` alone would call that read harmless and miss a real
environment-dependent default.

Nothing under ``src/probos/`` may import this module: the direction is
checker -> data.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from probos.config import SystemConfig, load_config  # noqa: E402
from probos.config_profiles import (  # noqa: E402
    PROFILE_IDS,
    UNRESOLVED,
    ProfileError,
    ProfileRule,
    discover_profile_ids,
    iter_rule_violations,
    load_profile,
    load_profile_document,
    override_paths,
    read_manifest_rules,
    resolve_flag,
)

_DEFAULT_MANIFEST = _REPO_ROOT / "docs" / "development" / "config-profiles.yaml"
_DEFAULT_PROFILE_DIR = _REPO_ROOT / "config" / "profiles"
_DEFAULT_CONFTEST = _REPO_ROOT / "tests" / "conftest.py"
_DEFAULT_CONFIG_MODULE = _REPO_ROOT / "src" / "probos" / "config.py"

#: Exactly the six kinds #1121 names. A seventh is a taxonomy change, which is
#: a review decision rather than a row edit.
VALID_KINDS: frozenset[str] = frozenset(
    {
        "consent-gate",
        "security-control",
        "optional-integration",
        "research-treatment",
        "migration-control",
        "product-feature",
    }
)

#: Kinds a flag must carry before ``supported`` may arm it.
SUPPORTED_ADMISSIBLE_KINDS: frozenset[str] = frozenset(
    {"product-feature", "security-control"}
)

VALID_MECHANISMS: frozenset[str] = frozenset(
    {"config-field-validator", "model-validator", "third-party-env"}
)

#: The tracked configs a declared rule must not break.
_TRACKED_CONFIGS: tuple[str, ...] = (
    "config/system.yaml",
    "config/node-1.yaml",
    "config/node-2.yaml",
)

_SKIP_MARKERS: frozenset[str] = frozenset({"skip", "skipif", "xfail"})

_HEADER = (
    "# AD-1185 config profile contract: which default-OFF flags are classified,\n"
    "# what may arm them, how they depend on and conflict with each other, and\n"
    "# which environment reads make a config resolve differently in CI.\n"
    "#\n"
    "# Regenerate the frozen row set with:\n"
    "#   python scripts/check_config_profiles.py --update-baseline\n"
    "# A blank review.owner/rationale/review_by fails --check on purpose.\n"
    "# Classifying a flag means DELETING its row from unclassified_flags in the\n"
    "# same commit that adds its entry to flags.\n"
)


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)


def default_false_flags() -> list[str]:
    """Every default-``False`` boolean path reachable from ``SystemConfig``.

    Each model type is visited once per path and cycle-guarded, so a model
    reachable by two routes is walked under both prefixes without recursing
    forever on a self-referential type.
    """
    found: list[str] = []

    def walk(model: type[BaseModel], prefix: str, seen: frozenset[type]) -> None:
        if model in seen:
            return
        seen = seen | {model}
        for name, model_field in model.model_fields.items():
            path = f"{prefix}{name}" if prefix else name
            annotation = model_field.annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                walk(annotation, f"{path}.", seen)
            elif annotation is bool:
                default = model_field.default
                if default is PydanticUndefined and model_field.default_factory is not None:
                    default = model_field.default_factory()
                if default is False:
                    found.append(path)

    walk(SystemConfig, "", frozenset())
    return sorted(found)


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ProfileError(f"manifest {path.as_posix()} is missing")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ProfileError(f"manifest {path.as_posix()} must be a mapping")
    return document


def _check_manifest_shape(document: dict[str, Any], errors: list[str]) -> None:
    if document.get("schema_version") != 1:
        errors.append("manifest: schema_version must be 1")
    if not str(document.get("baseline_id") or "").strip():
        errors.append("manifest: baseline_id must be non-empty")
    if not isinstance(document.get("tracking_issue"), int):
        errors.append("manifest: tracking_issue must be an integer issue number")
    if not str(document.get("smoke_test_node_id") or "").strip():
        errors.append("manifest: smoke_test_node_id must be non-empty")
    review = document.get("review")
    if not isinstance(review, dict):
        errors.append("manifest: review block is missing")
        return
    for key in ("owner", "rationale", "review_by"):
        if not str(review.get(key) or "").strip():
            errors.append(
                f"manifest: review.{key} is blank; an unreviewed baseline is "
                "an inventory nobody can fail"
            )


def _check_rows(
    rows: list[Any], errors: list[str]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Validate every ``flags[]`` row; return the rows by path and their order."""
    by_path: dict[str, dict[str, Any]] = {}
    ordered: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"manifest: flags[{index}] is not a mapping")
            continue
        path = row.get("path")
        if not isinstance(path, str) or not path:
            errors.append(f"manifest: flags[{index}] has no usable 'path'")
            continue
        if path in by_path:
            errors.append(f"manifest: {path!r} is classified twice")
            continue
        by_path[path] = row
        ordered.append(path)

        kind = row.get("kind")
        if kind not in VALID_KINDS:
            errors.append(
                f"manifest: {path} has kind {kind!r}; expected one of "
                f"{', '.join(sorted(VALID_KINDS))}"
            )
        if not str(row.get("evidence_to_promote") or "").strip():
            errors.append(
                f"manifest: {path} has a blank evidence_to_promote; a row with "
                "no promotion condition is a classification nobody can act on"
            )
        if kind == "optional-integration" and not str(
            row.get("external_dependency") or ""
        ).strip():
            errors.append(
                f"manifest: {path} is optional-integration but names no "
                "external_dependency; that is the field which makes the kind "
                "checkable"
            )
        for list_field in ("profiles", "requires", "conflicts_with"):
            value = row.get(list_field)
            if value is None:
                continue
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                errors.append(
                    f"manifest: {path}.{list_field} must be a list of strings"
                )
        if row.get("conflicts_with") and not str(
            row.get("conflict_rationale") or ""
        ).strip():
            errors.append(
                f"manifest: {path} declares conflicts_with but no "
                "conflict_rationale; an unexplained conflict cannot be reviewed"
            )
    return by_path, ordered


def _check_paths_resolve(
    paths: list[str], label: str, errors: list[str], *, require_bool: bool = True
) -> None:
    """Resolve each dotted path on a default config.

    ``require_bool`` is on for ``flags[]`` rows, which classify boolean
    switches, and off for a divergence's ``config_path``: ``PROBOS_LLM_URL``
    resolves to ``cognitive.llm_base_url``, a string.
    """
    defaults = SystemConfig()
    for path in paths:
        value = resolve_flag(defaults, path)
        if value is UNRESOLVED:
            errors.append(
                f"{label}: {path!r} does not resolve on SystemConfig; this is a "
                "broken row, not a missing flag"
            )
        elif require_bool and value is not False and value is not True:
            errors.append(
                f"{label}: {path!r} resolves to {type(value).__name__}, not a "
                "boolean; flags: classifies boolean switches"
            )


def _check_profiles(
    manifest_rows: dict[str, dict[str, Any]],
    profile_dir: Path,
    manifest_path: Path,
    errors: list[str],
) -> dict[str, list[str]]:
    """Load every profile and reconcile its overrides with the manifest."""
    discovered = discover_profile_ids(profile_dir)
    if discovered != PROFILE_IDS:
        errors.append(
            f"profiles: {profile_dir.as_posix()} holds {list(discovered)} but "
            f"probos.config_profiles.PROFILE_IDS is {list(PROFILE_IDS)}; an "
            "unregistered profile and a registered-but-absent one both fail here"
        )

    armed: dict[str, list[str]] = {}
    for profile_id in discovered:
        try:
            document = load_profile_document(profile_id, profile_dir)
            load_profile(
                profile_id, profile_dir=profile_dir, manifest_path=manifest_path
            )
        except ProfileError as exc:
            errors.append(f"profiles: {profile_id} does not load: {exc}")
            continue
        paths = override_paths(document.overrides)
        armed[profile_id] = paths
        for path in paths:
            row = manifest_rows.get(path)
            if row is None:
                errors.append(
                    f"profiles: {profile_id} arms {path!r}, which has no "
                    "manifest row"
                )
                continue
            declared = row.get("profiles") or []
            if profile_id not in declared:
                errors.append(
                    f"manifest: {path}.profiles does not name {profile_id!r}, "
                    "which arms it"
                )
            if profile_id == "supported":
                if row.get("kind") not in SUPPORTED_ADMISSIBLE_KINDS:
                    errors.append(
                        f"admission: supported arms {path!r} whose kind is "
                        f"{row.get('kind')!r}; supported v1 admits only "
                        f"{', '.join(sorted(SUPPORTED_ADMISSIBLE_KINDS))}"
                    )
                if not str(row.get("evidence_to_promote") or "").strip():
                    errors.append(
                        f"admission: supported arms {path!r} with no evidence"
                    )

    for path, row in manifest_rows.items():
        for profile_id in row.get("profiles") or []:
            if profile_id not in armed:
                errors.append(
                    f"manifest: {path}.profiles names {profile_id!r}, which is "
                    "not a loadable profile"
                )
            elif path not in armed[profile_id]:
                errors.append(
                    f"manifest: {path}.profiles claims {profile_id!r} arms it, "
                    "but that profile's overrides do not"
                )
    return armed


def _check_rule_evaluations(
    rules: list[ProfileRule], repo_root: Path, errors: list[str]
) -> dict[str, Any]:
    """Evaluate every rule against the default config and the tracked YAMLs."""
    evaluations: dict[str, Any] = {}
    configs: list[tuple[str, Any]] = [("SystemConfig()", SystemConfig())]
    for relative in _TRACKED_CONFIGS:
        path = repo_root / relative
        if not path.is_file():
            errors.append(
                f"rules: tracked config {relative} is missing; the proof that "
                "no declared rule breaks it cannot be produced"
            )
            continue
        configs.append((relative, load_config(path)))

    for label, config in configs:
        violations = iter_rule_violations(config, rules)
        evaluations[label] = {
            "rules_evaluated": len(rules),
            "violations": violations,
        }
        for violation in violations:
            errors.append(
                f"rules: {label} violates a declared rule -- {violation}. A "
                "conflict rule that would break a tracked config cannot be "
                "merged."
            )
    return evaluations


def _conftest_setdefaults(conftest: Path) -> dict[str, str]:
    """``os.environ.setdefault(name, value)`` pairs in ``conftest``, by AST.

    Never a text scan: a regex over source cannot tell a live call from one
    inside a string or a comment, and this check exists to notice when the
    override is genuinely gone.
    """
    if not conftest.is_file():
        return {}
    tree = ast.parse(conftest.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "setdefault":
            continue
        target = node.func.value
        if not (isinstance(target, ast.Attribute) and target.attr == "environ"):
            continue
        if len(node.args) != 2:
            continue
        name, value = node.args
        if isinstance(name, ast.Constant) and isinstance(value, ast.Constant):
            found[str(name.value)] = str(value.value)
    return found


def env_reads_reaching_defaults(config_module: Path) -> dict[str, str]:
    """Environment reads in ``config.py`` that can change a *default* config.

    Returns ``{env_var: mechanism}``. A read reaches a default when it sits in
    a ``model_validator`` (which runs on every construction, defaults included)
    or in a ``field_validator`` for a field declared ``validate_default=True``.
    Keying this on ``validate_default`` alone would miss ``PROBOS_LLM_URL``,
    which is measured moving the ``SystemConfig()`` dump from a
    ``model_validator``.
    """
    tree = ast.parse(config_module.read_text(encoding="utf-8"))
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def enclosing(node: ast.AST) -> tuple[Any, Any]:
        function = None
        current = parents.get(node)
        while current is not None:
            if function is None and isinstance(
                current, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                function = current
            elif isinstance(current, ast.ClassDef):
                return function, current
            current = parents.get(current)
        return function, None

    def decorator_name(decorator: ast.expr) -> str:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        return str(getattr(target, "id", getattr(target, "attr", "")))

    def validates_default(class_node: ast.ClassDef, fields: list[str]) -> bool:
        for statement in class_node.body:
            target_name = None
            if isinstance(statement, ast.AnnAssign) and isinstance(
                statement.target, ast.Name
            ):
                target_name = statement.target.id
            if target_name is None or target_name not in fields:
                continue
            value = statement.value
            if isinstance(value, ast.Call):
                for keyword in value.keywords:
                    if keyword.arg == "validate_default" and isinstance(
                        keyword.value, ast.Constant
                    ):
                        return bool(keyword.value.value)
        return False

    reaching: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        is_environ_get = node.func.attr == "get" and isinstance(
            node.func.value, ast.Attribute
        ) and node.func.value.attr == "environ"
        if not is_environ_get or not node.args:
            continue
        argument = node.args[0]
        if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
            continue
        env_var = argument.value
        function, class_node = enclosing(node)
        if function is None:
            continue
        decorators = [decorator_name(item) for item in function.decorator_list]
        if "model_validator" in decorators:
            reaching[env_var] = "model-validator"
        elif "field_validator" in decorators and class_node is not None:
            fields = [
                item.value
                for decorator in function.decorator_list
                if isinstance(decorator, ast.Call)
                and decorator_name(decorator) == "field_validator"
                for item in decorator.args
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            if validates_default(class_node, fields):
                reaching[env_var] = "config-field-validator"
    return reaching


def _check_divergences(
    document: dict[str, Any],
    conftest: Path,
    config_module: Path,
    errors: list[str],
) -> dict[str, Any]:
    rows = document.get("ci_divergences")
    if not isinstance(rows, list) or not rows:
        errors.append("manifest: ci_divergences must be a non-empty list")
        return {}

    declared: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"manifest: ci_divergences[{index}] is not a mapping")
            continue
        env_var = row.get("env_var")
        if not isinstance(env_var, str) or not env_var:
            errors.append(f"manifest: ci_divergences[{index}] has no env_var")
            continue
        declared[env_var] = row
        mechanism = row.get("mechanism")
        if mechanism not in VALID_MECHANISMS:
            errors.append(
                f"divergence {env_var}: mechanism {mechanism!r} is not one of "
                f"{', '.join(sorted(VALID_MECHANISMS))}"
            )
        for key in ("id", "production_resolution", "rationale"):
            if not str(row.get(key) or "").strip():
                errors.append(f"divergence {env_var}: {key} is blank")
        config_path = row.get("config_path")
        if mechanism == "third-party-env" and config_path is not None:
            errors.append(
                f"divergence {env_var}: a third-party-env mechanism is outside "
                "SystemConfig, so config_path must be null"
            )
        if isinstance(config_path, str) and config_path:
            _check_paths_resolve(
                [config_path], f"divergence {env_var}", errors, require_bool=False
            )

    # Declared -> real: an override that has been removed makes its row stale.
    setdefaults = _conftest_setdefaults(conftest)
    for env_var, row in declared.items():
        set_by = row.get("set_by")
        if set_by is None:
            continue
        if set_by != "tests/conftest.py":
            errors.append(
                f"divergence {env_var}: set_by {set_by!r} is not checkable; "
                "this checker resolves tests/conftest.py only"
            )
            continue
        if env_var not in setdefaults:
            errors.append(
                f"divergence {env_var}: declared as set by tests/conftest.py, "
                "but no os.environ.setdefault for it survives there"
            )
        elif setdefaults[env_var] != str(row.get("set_to")):
            errors.append(
                f"divergence {env_var}: conftest sets "
                f"{setdefaults[env_var]!r} but the row declares "
                f"{row.get('set_to')!r}"
            )

    # Real -> declared: a new environment-dependent default must be declared.
    reaching = env_reads_reaching_defaults(config_module)
    for env_var, mechanism in sorted(reaching.items()):
        row = declared.get(env_var)
        if row is None:
            errors.append(
                f"divergence: {env_var} is read in src/probos/config.py from a "
                f"{mechanism} and can therefore change a DEFAULT config, but "
                "no ci_divergences row declares it"
            )
        elif row.get("mechanism") != mechanism:
            errors.append(
                f"divergence {env_var}: declared mechanism "
                f"{row.get('mechanism')!r} but it is read from a {mechanism}"
            )
    return {
        "declared": sorted(declared),
        "conftest_setdefaults": setdefaults,
        "env_reads_reaching_defaults": reaching,
    }


def _check_smoke_node(node_id: str, repo_root: Path, errors: list[str]) -> dict[str, Any]:
    """Resolve the smoke's node ID by AST and refuse a skip/xfail marker."""
    detail: dict[str, Any] = {"node_id": node_id, "resolved": False, "markers": []}
    parts = node_id.split("::")
    if len(parts) < 2:
        errors.append(
            f"smoke: {node_id!r} is not a pytest node id (path::name)"
        )
        return detail
    test_file = repo_root / parts[0]
    if not test_file.is_file():
        errors.append(f"smoke: {parts[0]} does not exist")
        return detail
    try:
        tree = ast.parse(test_file.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        errors.append(f"smoke: {parts[0]} does not parse: {exc}")
        return detail

    body: list[ast.stmt] = tree.body
    for segment in parts[1:-1]:
        found = next(
            (
                node
                for node in body
                if isinstance(node, ast.ClassDef) and node.name == segment
            ),
            None,
        )
        if found is None:
            errors.append(f"smoke: class {segment!r} not found in {parts[0]}")
            return detail
        body = found.body

    function = next(
        (
            node
            for node in body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == parts[-1]
        ),
        None,
    )
    if function is None:
        errors.append(
            f"smoke: {parts[-1]!r} not found in {parts[0]}; the manifest names "
            "a boot smoke that has been renamed or deleted"
        )
        return detail
    detail["resolved"] = True

    markers: list[str] = []
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = getattr(target, "attr", getattr(target, "id", ""))
        if name in _SKIP_MARKERS:
            markers.append(str(name))
    detail["markers"] = markers
    if markers:
        errors.append(
            f"smoke: {node_id} carries {', '.join(markers)}; a skipped smoke is "
            "a non-passing smoke, and a moving skip count is invisible in the "
            "suite's passed total"
        )
    return detail


def check(
    manifest_path: Path = _DEFAULT_MANIFEST,
    profile_dir: Path = _DEFAULT_PROFILE_DIR,
    repo_root: Path = _REPO_ROOT,
    conftest: Path = _DEFAULT_CONFTEST,
    config_module: Path = _DEFAULT_CONFIG_MODULE,
) -> CheckResult:
    errors: list[str] = []
    try:
        document = load_manifest(manifest_path)
    except ProfileError as exc:
        return CheckResult(errors=[str(exc)], report={})

    _check_manifest_shape(document, errors)

    rows = document.get("flags")
    if not isinstance(rows, list):
        errors.append("manifest: 'flags:' must be a list")
        rows = []
    by_path, ordered = _check_rows(rows, errors)
    _check_paths_resolve(ordered, "manifest", errors)

    baseline = document.get("unclassified_flags")
    if baseline is None:
        baseline = []
    if not isinstance(baseline, list) or not all(
        isinstance(item, str) for item in baseline
    ):
        errors.append("manifest: unclassified_flags must be a list of strings")
        baseline = []

    classified = set(ordered)
    frozen = set(baseline)
    both = sorted(classified & frozen)
    for path in both:
        errors.append(
            f"manifest: {path} is both classified and frozen as unclassified; "
            "classifying a flag means deleting its baseline row in the same "
            "commit"
        )

    live = set(default_false_flags())
    missing = sorted(live - classified - frozen)
    for path in missing:
        errors.append(
            f"model: {path} is a default-False flag in neither flags: nor "
            "unclassified_flags:. A new flag must be classified or explicitly "
            "frozen; it cannot be grandfathered as compliant."
        )
    stale = sorted(frozen - live)
    for path in stale:
        errors.append(
            f"manifest: unclassified_flags names {path}, which is no longer a "
            "default-False flag on SystemConfig"
        )

    armed = _check_profiles(by_path, profile_dir, manifest_path, errors)

    try:
        rules = read_manifest_rules(manifest_path)
    except ProfileError as exc:
        errors.append(str(exc))
        rules = []
    evaluations = _check_rule_evaluations(rules, repo_root, errors)

    divergences = _check_divergences(document, conftest, config_module, errors)

    node_id = str(document.get("smoke_test_node_id") or "")
    smoke = _check_smoke_node(node_id, repo_root, errors) if node_id else {}

    report = {
        "manifest": manifest_path.relative_to(repo_root).as_posix()
        if manifest_path.is_relative_to(repo_root)
        else manifest_path.as_posix(),
        "baseline_id": document.get("baseline_id"),
        "default_false_flags": len(live),
        "classified": len(classified),
        "frozen_unclassified": len(frozen),
        "profiles": {name: paths for name, paths in sorted(armed.items())},
        "rules": len(rules),
        "rule_evaluations": evaluations,
        "divergences": divergences,
        "smoke": smoke,
        "errors": errors,
    }
    return CheckResult(errors=errors, report=report)


def render_manifest(document: dict[str, Any], unclassified: list[str]) -> str:
    document = dict(document)
    document["unclassified_flags"] = unclassified
    body = yaml.safe_dump(
        document,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=88,
    )
    return _HEADER + body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AD-1185 config profile check")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate and exit non-zero on any failure (writes nothing)",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help=(
            "rewrite unclassified_flags from the current model; unreachable "
            "from the gate, and the resulting diff is the reviewed artifact"
        ),
    )
    parser.add_argument(
        "--json", metavar="PATH", help="also write the machine-readable report"
    )
    parser.add_argument("--baseline", metavar="PATH", default=str(_DEFAULT_MANIFEST))
    parser.add_argument(
        "--profile-dir", metavar="PATH", default=str(_DEFAULT_PROFILE_DIR)
    )
    parser.add_argument("--src-root", metavar="PATH", default=str(_REPO_ROOT))
    args = parser.parse_args(argv)

    manifest_path = Path(args.baseline)
    profile_dir = Path(args.profile_dir)
    repo_root = Path(args.src_root)

    if args.update_baseline:
        document = load_manifest(manifest_path)
        classified = {
            row.get("path")
            for row in document.get("flags") or []
            if isinstance(row, dict)
        }
        unclassified = [
            path for path in default_false_flags() if path not in classified
        ]
        manifest_path.write_text(
            render_manifest(document, unclassified), encoding="utf-8"
        )
        print(
            f"wrote {manifest_path.as_posix()} with {len(unclassified)} frozen "
            "row(s); review every row before committing"
        )
        return 0

    result = check(
        manifest_path=manifest_path,
        profile_dir=profile_dir,
        repo_root=repo_root,
        conftest=repo_root / "tests" / "conftest.py",
        config_module=repo_root / "src" / "probos" / "config.py",
    )

    if args.json:
        Path(args.json).write_text(
            json.dumps(result.report, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )

    if result.errors:
        print(
            f"config profile check failed with {len(result.errors)} problem(s):",
            file=sys.stderr,
        )
        for problem in result.errors:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    report = result.report
    print(
        "config profile check passed ("
        f"profiles={len(report['profiles'])}, "
        f"classified={report['classified']}, "
        f"frozen={report['frozen_unclassified']}, "
        f"default-OFF flags={report['default_false_flags']}, "
        f"rules={report['rules']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
