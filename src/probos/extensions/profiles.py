"""AD-481g: Extension Profiles — three preset enable-lists."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


_PROFILES_DIR = Path("config/extension_profiles")
_VALID_PROFILES = ("minimal", "developer", "full")


class ExtensionProfile(BaseModel):
    """Preset describing which extensions to enable for a deployment style."""

    profile_name: str
    description: str = ""
    enabled_extensions: list[str] = Field(default_factory=list)

    @field_validator("profile_name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if v not in _VALID_PROFILES:
            raise ValueError(f"profile_name must be one of {_VALID_PROFILES}; got {v!r}")
        return v


def load_profile(profile_name: str, profiles_dir: Path | None = None) -> ExtensionProfile:
    """Load a preset YAML by name. Raises FileNotFoundError if missing."""
    if profile_name not in _VALID_PROFILES:
        raise ValueError(f"Unknown profile {profile_name!r}; valid: {_VALID_PROFILES}")
    target_dir = profiles_dir or _PROFILES_DIR
    target = target_dir / f"{profile_name}.yaml"
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Profile YAML at {target} did not parse to a mapping")
    return ExtensionProfile(**raw)


def apply_profile(profile_name: str, profiles_dir: Path | None = None) -> list[str]:
    """Return the list of extension_ids the profile enables.

    Caller is responsible for invoking ExtensionRegistry.enable() on each
    returned id (and ExtensionRegistry.disable() on extensions not in the
    list, if they are currently ENABLED).
    """
    profile = load_profile(profile_name, profiles_dir)
    return list(profile.enabled_extensions)
