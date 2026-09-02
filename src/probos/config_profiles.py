"""AD-1185: versioned ``SystemConfig`` profiles a CI gate can actually fail.

A profile is a committed YAML **delta against the model defaults** -- not
against ``config/system.yaml``, which is the reference vessel's operator
config rather than the product contract. Anything a profile omits takes the
``SystemConfig`` default, which is what lets ``minimal`` be an empty delta that
resolves byte-identically to ``SystemConfig()``.

**Why a loader exists at all, rather than handing the file to
``SystemConfig.model_validate``.** ``SystemConfig.model_config`` is empty, so
Pydantic v2's default ``extra="ignore"`` applies at every level of the tree.
Measured: ``SystemConfig.model_validate({"nats": {"enabld": True}})`` parses
clean and leaves the flag off. A profile claiming to arm
``browser_tool.action_dispatch_enabled`` but spelling it
``action_dispatch_enable`` would therefore parse, ship the feature off, and
pass every test that only asserts "the profile parses". :func:`load_profile`
resolves every override key against ``SystemConfig.model_fields`` *before*
``model_validate`` sees it, so a typo is an error instead of a silent no-op.
Without that pre-validation the whole contract is unfalsifiable.

That resolution has to follow models through *containers* as well. Six fields
reach a model only through a ``list[...]`` or ``dict[str, ...]``, and Pydantic
drops an unknown key inside one exactly as silently as a top-level typo -- so
:func:`_walk_value` descends them too, treating mapping keys as operator data
and everything beneath them as schema.

Dependency and conflict rules come from the reviewed manifest at
``docs/development/config-profiles.yaml`` and are enforced **at profile
parse**: :func:`load_profile` raises :class:`ProfileConflictError` rather than
returning a ``SystemConfig``. A missing manifest is fatal for the same reason
-- enforcing no rules because the authority is absent is a guard that looks
total and is not.

This module reads data. It must never import the checker
(``scripts/check_config_profiles.py``); the direction is checker -> data.
"""

from __future__ import annotations

import difflib
import re
import types
from dataclasses import dataclass, field as dataclass_field
from functools import lru_cache
from pathlib import Path
from typing import Any, Union, get_args, get_origin

import yaml
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from probos.config import SystemConfig

__all__ = [
    "DEFAULT_MANIFEST_PATH",
    "DEFAULT_PROFILE_DIR",
    "FORBIDDEN_PROFILE_IDS",
    "PROFILE_ARMS",
    "PROFILE_IDS",
    "UNRESOLVED",
    "ProfileConflictError",
    "ProfileDocument",
    "ProfileError",
    "ProfileRule",
    "discover_profile_ids",
    "iter_rule_violations",
    "load_profile",
    "load_profile_document",
    "override_paths",
    "read_manifest_rules",
    "resolve_flag",
    "validate_override_keys",
]

_MODULE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _MODULE_DIR.parent.parent

#: Committed profile deltas. Deliberately ``config/profiles/`` and never
#: ``config/extension_profiles/`` -- see :data:`FORBIDDEN_PROFILE_IDS`.
DEFAULT_PROFILE_DIR = _REPO_ROOT / "config" / "profiles"

#: The reviewed classification, dependency and conflict authority.
DEFAULT_MANIFEST_PATH = _REPO_ROOT / "docs" / "development" / "config-profiles.yaml"

#: Profiles this AD ships. ``scripts/check_config_profiles.py`` asserts the
#: profile directory holds exactly these, so an unregistered YAML and a
#: registered-but-absent profile both fail.
PROFILE_IDS: tuple[str, ...] = (
    "experimental-approval-standing-rules",
    "minimal",
    "supported",
)

#: ``probos.extensions.profiles`` owns ``minimal``/``developer``/``full`` over
#: *extension IDs*, and ``ExtensionsConfig.default_profile`` puts the token
#: ``"minimal"`` inside ``SystemConfig`` already. ``minimal`` is bound by #1121
#: and cannot be renamed, so the two vocabularies are kept provably disjoint at
#: the other end instead: these two are refused here.
FORBIDDEN_PROFILE_IDS: frozenset[str] = frozenset({"developer", "full"})

#: ``control`` is the ablation baseline, ``product`` the supported contract,
#: ``experiment`` a named treatment.
PROFILE_ARMS: tuple[str, ...] = ("control", "product", "experiment")

_PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
_REQUIRED_METADATA_KEYS = frozenset({"id", "version", "description", "arm"})
_TOP_LEVEL_KEYS = frozenset({"profile", "overrides"})

#: :func:`resolve_flag` sentinel: the dotted path does not exist on the model.
#: Public because the checker must distinguish "absent" from "off" too, and a
#: broken manifest row read as "off" is a rule that silently never fires.
UNRESOLVED = object()


class ProfileError(ValueError):
    """A profile is malformed, unknown, or names a key the model does not have."""


class ProfileConflictError(ProfileError):
    """A profile's resolved config violates a declared ``requires``/``conflicts_with``.

    Subclasses :class:`ProfileError` so ``except ProfileError`` catches every
    refusal to hand back a config, while callers that care specifically about
    the rule graph can still discriminate.
    """


@dataclass(frozen=True)
class ProfileRule:
    """One manifest row's dependency and conflict edges."""

    path: str
    requires: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfileDocument:
    """A parsed profile file: validated metadata plus its raw override tree."""

    profile_id: str
    version: int
    description: str
    arm: str
    overrides: dict[str, Any] = dataclass_field(default_factory=dict)
    source: Path | None = None


@lru_cache(maxsize=None)
def _input_names(model: type[BaseModel]) -> dict[str, FieldInfo]:
    """Every key ``model`` actually accepts, mapped to the field it feeds.

    Not ``model_fields``: with ``model_config == {}`` there is no
    ``populate_by_name``, so a field carrying a ``validation_alias`` is
    reachable *only* through that alias. Measured on a probe model, ``real``
    with ``validation_alias="only_this"`` ignores ``{"real": 5}`` outright.
    Resolving against field names alone would therefore refuse a key Pydantic
    honours (``sensorium.token_budget_warning``) while accepting one it drops.
    """
    accepted: dict[str, FieldInfo] = {}
    populate_by_name = bool(model.model_config.get("populate_by_name"))
    for name, field in model.model_fields.items():
        names: list[str] = []
        if field.validation_alias is not None:
            choices = getattr(field.validation_alias, "choices", None)
            if choices is None:
                choices = [field.validation_alias]
            names = [choice for choice in choices if isinstance(choice, str)]
            if populate_by_name:
                names.append(name)
        elif field.alias is not None:
            names = [field.alias]
            if populate_by_name:
                names.append(name)
        else:
            names = [name]
        for accepted_name in names:
            accepted.setdefault(accepted_name, field)
    return accepted


def _union_members(annotation: Any) -> tuple[Any, ...]:
    """Union members with ``None`` dropped; a non-union annotation yields itself."""
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        return tuple(
            argument
            for argument in get_args(annotation)
            if argument is not type(None)
        )
    return (annotation,)


def _bears_model(annotation: Any) -> bool:
    """Whether a ``BaseModel`` is reachable through this annotation."""
    for member in _union_members(annotation):
        origin = get_origin(member)
        if origin is not None:
            if any(
                argument is not Ellipsis and _bears_model(argument)
                for argument in get_args(member)
            ):
                return True
        elif isinstance(member, type) and issubclass(member, BaseModel):
            return True
    return False


def _model_bearing_member(annotation: Any) -> Any | None:
    """The first union member a ``BaseModel`` is reachable through, if any."""
    for member in _union_members(annotation):
        if _bears_model(member):
            return member
    return None


def _walk_value(
    value: Any,
    annotation: Any,
    path: str,
    errors: list[str],
    leaves: list[str],
) -> None:
    """Descend an override value alongside its annotation.

    A model nested inside a container is still schema, so its unknown fields
    must be rejected here for the same reason a directly-nested one is:
    Pydantic drops them silently. Containers differ in *which* segment is data.
    In ``dict[str, Model]`` the key is operator data (a department name, a
    server name) and only what sits beneath it is schema, so keys are never
    resolved against fields. In a sequence the elements are positional, so
    each is walked as a model at ``path[i]``.
    """
    member = _model_bearing_member(annotation)
    if member is None:
        leaves.append(path)
        return

    origin = get_origin(member)
    if origin is None:
        if isinstance(value, dict):
            _walk_overrides(value, member, f"{path}.", errors, leaves)
        else:
            leaves.append(path)
        return

    arguments = [
        argument for argument in get_args(member) if argument is not Ellipsis
    ]
    if not value:
        leaves.append(path)
        return

    if origin is dict:
        if not isinstance(value, dict):
            leaves.append(path)
            return
        for key, item in value.items():
            _walk_value(item, arguments[-1], f"{path}.{key}", errors, leaves)
        return

    if isinstance(value, dict):
        errors.append(
            f"{path!r} is a sequence field, but it is addressed as a mapping "
            f"keyed by {sorted(map(repr, value))[0]}. Write it as a YAML list; "
            "an index-as-key mapping is not a supported override form and "
            "Pydantic would reject it as a type error."
        )
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk_value(item, arguments[0], f"{path}[{index}]", errors, leaves)
        return
    leaves.append(path)


def _walk_overrides(
    node: Any,
    model: type[BaseModel],
    prefix: str,
    errors: list[str],
    leaves: list[str],
) -> None:
    """Resolve every key in ``node`` against ``model``, accumulating all failures."""
    if not isinstance(node, dict):
        return
    fields = _input_names(model)
    for key, value in node.items():
        if not isinstance(key, str):
            errors.append(
                f"{prefix or '<root>'}: key {key!r} is {type(key).__name__}, "
                "not a string; profile override keys are config field names"
            )
            continue
        path = f"{prefix}{key}"
        field = fields.get(key)
        if field is None:
            close = difflib.get_close_matches(key, list(fields), n=1)
            hint = (
                f"; closest valid sibling is {close[0]!r}"
                if close
                else f"; {model.__name__} has no similarly-named field"
            )
            errors.append(
                f"{path!r} does not resolve on SystemConfig{hint}. Pydantic "
                "would ignore this key and ship the setting unchanged, so it "
                "is rejected here instead."
            )
            continue
        _walk_value(value, field.annotation, path, errors, leaves)


def validate_override_keys(overrides: dict[str, Any]) -> list[str]:
    """Return one message per override key that does not resolve on ``SystemConfig``.

    Every bad key is reported, not just the first, so one edit fixes the file.
    """
    errors: list[str] = []
    _walk_overrides(overrides, SystemConfig, "", errors, [])
    return errors


def override_paths(overrides: dict[str, Any]) -> list[str]:
    """Dotted leaf paths an override tree sets, in sorted order."""
    leaves: list[str] = []
    _walk_overrides(overrides, SystemConfig, "", [], leaves)
    return sorted(leaves)


def resolve_flag(config: Any, path: str) -> Any:
    """Walk a dotted ``path`` over ``config``; :data:`UNRESOLVED` when absent.

    Absence is distinguished from a falsey value on purpose: an unresolvable
    path is a broken manifest row, not a disabled flag, and reporting it as
    "off" would let a typo'd rule silently never fire.
    """
    current: Any = config
    for part in path.split("."):
        if not hasattr(current, part):
            return UNRESOLVED
        current = getattr(current, part)
    return current


def iter_rule_violations(config: Any, rules: list[ProfileRule]) -> list[str]:
    """Every ``requires``/``conflicts_with`` breach the resolved config exhibits.

    A rule is evaluated only when its subject is armed: ``requires`` states
    what an armed flag depends on, so an unarmed subject constrains nothing.
    """
    violations: list[str] = []
    for rule in rules:
        subject = resolve_flag(config, rule.path)
        if subject is UNRESOLVED:
            violations.append(
                f"{rule.path!r} does not resolve on the config; this is a "
                "broken manifest row, not a disabled flag"
            )
            continue
        if subject is not True:
            continue
        for required in rule.requires:
            value = resolve_flag(config, required)
            if value is UNRESOLVED:
                violations.append(
                    f"{rule.path} requires {required!r}, which does not "
                    "resolve on the config"
                )
            elif value is not True:
                violations.append(
                    f"{rule.path} is on but requires {required}, which is off"
                )
        for conflicting in rule.conflicts_with:
            value = resolve_flag(config, conflicting)
            if value is UNRESOLVED:
                violations.append(
                    f"{rule.path} conflicts with {conflicting!r}, which does "
                    "not resolve on the config"
                )
            elif value is True:
                violations.append(
                    f"{rule.path} conflicts with {conflicting}, but both are on"
                )
    return violations


def read_manifest_rules(manifest_path: Path | None = None) -> list[ProfileRule]:
    """Load the dependency/conflict edges from the reviewed manifest.

    A missing or malformed manifest raises rather than degrading to "no rules":
    enforcing an empty rule set because the authority is absent would make
    every conflicting profile load cleanly.
    """
    path = Path(manifest_path) if manifest_path is not None else DEFAULT_MANIFEST_PATH
    if not path.is_file():
        raise ProfileError(
            f"config profile manifest {path.as_posix()} is missing; profile "
            "conflicts cannot be enforced without it"
        )
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileError(
            f"config profile manifest {path.as_posix()} is not valid YAML: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise ProfileError(
            f"config profile manifest {path.as_posix()} must be a mapping"
        )
    rows = document.get("flags")
    if not isinstance(rows, list):
        raise ProfileError(
            f"config profile manifest {path.as_posix()} has no 'flags:' list"
        )
    rules: list[ProfileRule] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ProfileError(
                f"{path.as_posix()}: flags[{index}] is not a mapping"
            )
        flag_path = row.get("path")
        if not isinstance(flag_path, str) or not flag_path:
            raise ProfileError(
                f"{path.as_posix()}: flags[{index}] has no usable 'path'"
            )
        rules.append(
            ProfileRule(
                path=flag_path,
                requires=tuple(_string_list(row.get("requires"), path, flag_path, "requires")),
                conflicts_with=tuple(
                    _string_list(row.get("conflicts_with"), path, flag_path, "conflicts_with")
                ),
            )
        )
    return rules


def _string_list(value: Any, source: Path, flag_path: str, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProfileError(
            f"{source.as_posix()}: {flag_path}.{field_name} must be a list of "
            "dotted config paths"
        )
    return list(value)


def discover_profile_ids(profile_dir: Path | None = None) -> tuple[str, ...]:
    """Profile IDs present on disk, sorted. Empty when the directory is absent."""
    directory = Path(profile_dir) if profile_dir is not None else DEFAULT_PROFILE_DIR
    if not directory.is_dir():
        return ()
    return tuple(sorted(path.stem for path in directory.glob("*.yaml")))


def load_profile_document(
    profile_id: str, profile_dir: Path | None = None
) -> ProfileDocument:
    """Parse and shape-check one profile file without resolving it to a config.

    Validates the file's structure, its metadata block, and every override key.
    It does **not** evaluate dependency or conflict rules -- that needs a
    resolved ``SystemConfig`` and belongs to :func:`load_profile`.
    """
    directory = Path(profile_dir) if profile_dir is not None else DEFAULT_PROFILE_DIR
    if not isinstance(profile_id, str) or not profile_id:
        raise ProfileError("profile id must be a non-empty string")
    if profile_id in FORBIDDEN_PROFILE_IDS:
        raise ProfileError(
            f"{profile_id!r} is reserved by probos.extensions.profiles, which "
            "governs extension IDs rather than SystemConfig fields. Config "
            f"profiles are {', '.join(PROFILE_IDS)}."
        )
    if not _PROFILE_ID_RE.match(profile_id):
        raise ProfileError(
            f"{profile_id!r} is not a valid profile id; expected lowercase "
            "words joined by single hyphens"
        )

    path = directory / f"{profile_id}.yaml"
    if not path.is_file():
        available = discover_profile_ids(directory)
        raise ProfileError(
            f"no config profile {profile_id!r} at {path.as_posix()}; "
            f"available: {', '.join(available) if available else '<none>'}"
        )
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileError(f"{path.as_posix()} is not valid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise ProfileError(f"{path.as_posix()} must be a mapping with 'profile' and 'overrides'")

    unknown_top = sorted(set(document) - _TOP_LEVEL_KEYS)
    if unknown_top:
        raise ProfileError(
            f"{path.as_posix()} has unexpected top-level key(s) "
            f"{', '.join(repr(key) for key in unknown_top)}; a profile is "
            "exactly 'profile:' and 'overrides:'"
        )
    missing_top = sorted(_TOP_LEVEL_KEYS - set(document))
    if missing_top:
        raise ProfileError(
            f"{path.as_posix()} is missing required top-level key(s) "
            f"{', '.join(repr(key) for key in missing_top)}"
        )

    metadata = document.get("profile")
    if not isinstance(metadata, dict):
        raise ProfileError(f"{path.as_posix()}: 'profile:' must be a mapping")
    unknown_meta = sorted(set(metadata) - _REQUIRED_METADATA_KEYS)
    if unknown_meta:
        raise ProfileError(
            f"{path.as_posix()}: unexpected key(s) in 'profile:' "
            f"{', '.join(repr(key) for key in unknown_meta)}"
        )
    missing_meta = sorted(_REQUIRED_METADATA_KEYS - set(metadata))
    if missing_meta:
        raise ProfileError(
            f"{path.as_posix()}: 'profile:' is missing "
            f"{', '.join(repr(key) for key in missing_meta)}"
        )
    if metadata["id"] != profile_id:
        raise ProfileError(
            f"{path.as_posix()}: declares id {metadata['id']!r} but is filed "
            f"as {profile_id!r}"
        )
    version = metadata["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ProfileError(
            f"{path.as_posix()}: 'version' must be an integer >= 1, got {version!r}"
        )
    description = metadata["description"]
    if not isinstance(description, str) or not description.strip():
        raise ProfileError(f"{path.as_posix()}: 'description' must be a non-empty string")
    arm = metadata["arm"]
    if arm not in PROFILE_ARMS:
        raise ProfileError(
            f"{path.as_posix()}: 'arm' must be one of {', '.join(PROFILE_ARMS)}, "
            f"got {arm!r}"
        )

    overrides = document.get("overrides")
    if overrides is None:
        raise ProfileError(
            f"{path.as_posix()}: 'overrides:' is empty. Write 'overrides: {{}}' "
            "to state that the profile is an empty delta."
        )
    if not isinstance(overrides, dict):
        raise ProfileError(f"{path.as_posix()}: 'overrides:' must be a mapping")

    key_errors = validate_override_keys(overrides)
    if key_errors:
        joined = "\n  - ".join(key_errors)
        raise ProfileError(
            f"{path.as_posix()} names {len(key_errors)} override key(s) that "
            f"SystemConfig does not have:\n  - {joined}"
        )

    return ProfileDocument(
        profile_id=profile_id,
        version=version,
        description=description,
        arm=arm,
        overrides=overrides,
        source=path,
    )


def load_profile(
    profile_id: str,
    *,
    profile_dir: Path | None = None,
    manifest_path: Path | None = None,
) -> SystemConfig:
    """Resolve a profile ID to a validated :class:`SystemConfig`.

    Raises :class:`ProfileError` for a malformed file or an unresolvable
    override key, and :class:`ProfileConflictError` when the resolved config
    breaches a declared ``requires``/``conflicts_with`` edge. A profile that
    conflicts never becomes a ``SystemConfig``.
    """
    document = load_profile_document(profile_id, profile_dir)
    config = SystemConfig.model_validate(document.overrides)

    rules = read_manifest_rules(manifest_path)
    violations = iter_rule_violations(config, rules)
    if violations:
        joined = "\n  - ".join(violations)
        source = document.source.as_posix() if document.source else profile_id
        raise ProfileConflictError(
            f"{source} resolves to a config that breaks "
            f"{len(violations)} declared rule(s):\n  - {joined}"
        )
    return config
