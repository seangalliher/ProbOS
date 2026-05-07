"""AD-481e: skill.yaml manifest format + adapter to existing SkillDefinition."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from probos.extensions.protocol import EXTENSION_API_VERSION

logger = logging.getLogger(__name__)


class SkillManifest(BaseModel):
    """Portable skill descriptor read from skill.yaml.

    Mirrors the existing SkillDefinition dataclass at src/probos/skill_framework.py
    field-for-field, plus packaging metadata (version, author, license,
    dependencies). load_skill_from_manifest translates this into the existing
    SkillDefinition without any breaking change to SkillRegistry.
    """

    manifest_version: str = "1.0"
    skill_id: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    author: str = ""
    license: str = ""
    description: str = ""
    category: str = "acquired"          # SkillCategory: "pcc" / "role" / "acquired"
    domain: str = "*"
    prerequisites: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)  # producer contract for AD-481k
    preferred_tools: list[dict[str, Any]] = Field(default_factory=list)
    composite_skill_ids: list[str] = Field(default_factory=list)
    synergy_partners: list[str] = Field(default_factory=list)
    decay_rate_days: int = 14
    required_api_version: str = EXTENSION_API_VERSION

    @field_validator("category")
    @classmethod
    def _validate_category(cls, v: str) -> str:
        if v not in ("pcc", "role", "acquired"):
            raise ValueError(f"category must be one of pcc/role/acquired; got {v!r}")
        return v

    @field_validator("decay_rate_days")
    @classmethod
    def _validate_decay(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"decay_rate_days must be non-negative; got {v}")
        return v


def load_skill_from_manifest(yaml_path: Path) -> Any:
    """Load skill.yaml and return an existing SkillDefinition.

    Pure adapter. No SkillRegistry mutation. Caller passes the returned
    SkillDefinition to SkillRegistry.register_skill() (or uses
    SkillRegistry.register_from_manifest helper added in section 6).
    """
    # Late import to avoid cycle (skill_framework imports from extensions
    # would create a loop; this module imports from skill_framework instead).
    from probos.skill_framework import SkillCategory, SkillDefinition
    from probos.tools.protocol import ToolPreference

    raw = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"skill.yaml at {yaml_path} did not parse to a mapping")

    try:
        manifest = SkillManifest(**raw)
    except ValidationError as exc:
        raise ValueError(f"skill.yaml at {yaml_path} failed validation: {exc}") from exc

    cat_map = {
        "pcc": SkillCategory.PCC,
        "role": SkillCategory.ROLE,
        "acquired": SkillCategory.ACQUIRED,
    }

    preferred_tools = [
        ToolPreference(
            tool_id=p.get("tool_id", ""),
            priority=p.get("priority", 0),
            context=p.get("context", ""),
        )
        for p in manifest.preferred_tools
    ]

    return SkillDefinition(
        skill_id=manifest.skill_id,
        name=manifest.name,
        category=cat_map[manifest.category],
        description=manifest.description,
        domain=manifest.domain,
        prerequisites=list(manifest.prerequisites),
        decay_rate_days=manifest.decay_rate_days,
        origin="acquired",  # manifest-loaded skills are by definition not built-in
        preferred_tools=preferred_tools,
        composite_skill_ids=list(manifest.composite_skill_ids),
        synergy_partners=list(manifest.synergy_partners),
    )
