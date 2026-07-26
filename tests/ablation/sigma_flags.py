"""AD-1143 DD-6 — the Σ flag set, in exactly one place.

`SIGMA_ON` and `SIGMA_OFF` are the *only* place the ablation names a config
knob. The runner reads these dicts; it never names a flag inline. AD-1140
(``publish_finding``) and AD-1141 (Σ into the crew loop) extend **this module
and nothing else**.

Two guards live in ``test_sigma_harness_structural.py`` and they are the reason
this module exists as a module rather than two literals in the runner:

1. ``set(SIGMA_ON) == set(SIGMA_OFF)`` — the arms must differ in *values*,
   never in *which knobs exist*. A key present in one dict only is a silent
   asymmetry that would show up as an effect.
2. Every dotted path resolves against a live ``SystemConfig()`` and the
   resolved attribute is a ``bool``. If AD-1141 renames a field, that guard
   goes red instead of the flag becoming a no-op that quietly turns the
   treatment arm into a second control arm.

No I/O at import. Production is imported for the config type only — this module
never modifies it.
"""

from __future__ import annotations

from typing import Any

from probos.config import SystemConfig

# Dotted paths against ``SystemConfig``. Verified at HEAD b4e4fc93:
#   config.py:6428  records: RecordsConfig
#   config.py:3400  semantic_index_enabled: bool = False        # AD-1138
#   config.py:6509  agentic_tools: AgenticToolsConfig
#   config.py:6057  oracle_query_enabled: bool = False          # AD-1139
SIGMA_OFF: dict[str, Any] = {
    "records.semantic_index_enabled": False,
    "agentic_tools.oracle_query_enabled": False,
}

SIGMA_ON: dict[str, Any] = {
    "records.semantic_index_enabled": True,
    "agentic_tools.oracle_query_enabled": True,
}

ARMS: dict[str, dict[str, Any]] = {
    "sigma_off": SIGMA_OFF,
    "sigma_on": SIGMA_ON,
}

#: Arm names in a stable order. Used wherever a deterministic iteration order
#: matters (blind-order seeding, artifact key order, report rendering).
ARM_NAMES: tuple[str, ...] = ("sigma_off", "sigma_on")

CONTROL_ARM = "sigma_off"
TREATMENT_ARM = "sigma_on"


def resolve_flag(config: SystemConfig, path: str) -> Any:
    """Walk ``path`` (dotted) on ``config`` and return the resolved value.

    Raises ``AttributeError`` naming the failing segment when the path does not
    resolve — a rename in ``config.py`` must be loud, not a silent no-op.
    """
    if not path:
        raise ValueError("sigma_flag_path_empty")
    current: Any = config
    walked: list[str] = []
    for segment in path.split("."):
        walked.append(segment)
        if not hasattr(current, segment):
            raise AttributeError(
                f"sigma flag path {path!r} does not resolve on SystemConfig: "
                f"no attribute {segment!r} at {'.'.join(walked[:-1]) or '<root>'}"
            )
        current = getattr(current, segment)
    return current


def _set_path(config: SystemConfig, path: str, value: Any) -> None:
    """Set ``path`` on ``config`` in place. Assumes ``path`` already resolves."""
    segments = path.split(".")
    owner: Any = config
    for segment in segments[:-1]:
        owner = getattr(owner, segment)
    setattr(owner, segments[-1], value)


def set_paths(config: SystemConfig, values: dict[str, Any]) -> SystemConfig:
    """Return a **new** ``SystemConfig`` with every dotted path in ``values`` set.

    ``config`` is never mutated — each arm/trial gets its own object so a stray
    write in one arm cannot leak into the other. Every path is validated
    (it resolves, and the new value has the same type as the existing one)
    *before* any write, so a partially-applied config is never returned.

    Shared by the Σ arm applier and by DD-5's ``agentic_loop`` pinning.
    """
    for path, value in values.items():
        current = resolve_flag(config, path)
        if type(current) is not type(value):
            raise TypeError(
                f"config path {path!r} resolves to {type(current).__name__} "
                f"but was given a {type(value).__name__}; the harness only "
                f"overrides a value with one of the same type"
            )
    applied = config.model_copy(deep=True)
    for path, value in values.items():
        _set_path(applied, path, value)
    return applied


def apply_flags(config: SystemConfig, flags: dict[str, Any]) -> SystemConfig:
    """Return a **new** ``SystemConfig`` with the Σ ``flags`` applied.

    Additionally requires every target *and* every value to be a ``bool``: the
    ablation only toggles boolean gates, and a non-bool here would mean a flag
    path had drifted onto something that is not a feature gate.
    """
    for path, value in flags.items():
        current = resolve_flag(config, path)
        if type(current) is not bool:
            raise TypeError(
                f"sigma flag path {path!r} resolves to "
                f"{type(current).__name__}, not bool; the ablation only "
                f"toggles boolean gates"
            )
        if type(value) is not bool:
            raise TypeError(
                f"sigma flag {path!r} was given a {type(value).__name__} "
                f"value; the ablation only toggles boolean gates"
            )
    return set_paths(config, flags)


def flag_snapshot(config: SystemConfig) -> dict[str, Any]:
    """Read every Σ path off ``config``, for the artifact's ``flags`` block.

    Reads the *runtime-visible* values rather than echoing the arm dict, so an
    arm whose flags failed to apply is visible in the artifact.
    """
    return {path: resolve_flag(config, path) for path in sorted(SIGMA_OFF)}
