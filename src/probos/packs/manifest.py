"""AD-1003a: Capability-Pack manifest parser + validator.

ProbOS adopts the cross-tool agent-plugin format shared by VS Code / GitHub
Copilot CLI / Claude Code (the ``plugin.json`` manifest). A **Capability Pack**
bundles any combination of skills, agents, hooks, MCP servers (+ ProbOS-native
mesh-intent grants and standing-order overlays) into one installable unit. This
module is the **read-only parsing + validation** layer:

* ``PackManifest`` — a Pydantic model of the cross-tool ``plugin.json`` schema
  (name / description / version / author + component paths), with the same
  kebab-case ``name`` rule the IDEs enforce (invalid names silently fail to load
  there; here they raise, loudly, so a malformed pack is caught at parse time).
* ``find_manifest`` — locate the manifest in a pack directory, checking the same
  format-specific paths VS Code auto-detects (``.plugin/plugin.json`` →
  ``plugin.json`` → ``.github/plugin/plugin.json`` → ``.claude-plugin/plugin.json``).
* ``load_manifest`` / ``parse_manifest`` — read + validate → ``PackManifest``.
* ``describe_pack`` — a read-only summary of what a pack *would* contribute
  (component counts), for the future Ship's Locker "install" preview.

**Scope: parse + validate only.** NOTHING is installed, executed, registered, or
wired. No hook runs, no MCP server starts, no skill/agent is loaded. Consuming a
pack into the live registries (and the operator trust/consensus gate around that)
is a later slice — this is the safe, additive substrate it builds on.

License/portability note: a ProbOS pack stays loadable as a base plugin in the
IDEs because ProbOS extensions (mesh-intent grants, standing-order overlays) are
*additive + namespaced* keys the base schema ignores; ``extra="allow"`` preserves
them on parse.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

# The cross-tool kebab-case rule: lowercase letters, digits, hyphens; <= 64 chars;
# no slashes/colons/namespace prefixes (those silently fail to load in the IDEs).
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_MAX_NAME = 64
_MAX_DESCRIPTION = 1024

# Manifest auto-detection order — mirrors VS Code's plugin-format detection.
_MANIFEST_PATHS = (
    ".plugin/plugin.json",
    "plugin.json",
    ".github/plugin/plugin.json",
    ".claude-plugin/plugin.json",
)


class PackParseError(ValueError):
    """Raised when a Capability-Pack manifest is missing or invalid."""


class PackAuthor(BaseModel):
    """Pack author block (name required, email/url optional)."""

    model_config = ConfigDict(extra="allow")
    name: str
    email: str = ""
    url: str = ""


class PackManifest(BaseModel):
    """Parsed + validated ``plugin.json`` (the cross-tool agent-plugin manifest).

    Component fields accept the IDE shapes: ``skills``/``agents`` are a path or
    list of paths (default the conventional dir), ``hooks``/``mcpServers`` are a
    path to a config file or an inline object. ProbOS-native additive keys
    (mesh-intent grants, standing-order overlays) ride through via ``extra``.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    description: str = ""
    version: str = ""
    author: PackAuthor | None = None
    skills: str | list[str] = Field(default_factory=lambda: "skills/")
    agents: str | list[str] = Field(default_factory=lambda: "agents/")
    hooks: str | dict[str, Any] | None = None
    mcp_servers: str | dict[str, Any] | None = Field(default=None, alias="mcpServers")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v or not _NAME_RE.match(v):
            raise ValueError(
                f"pack name {v!r} must be kebab-case (lowercase letters, digits, "
                "hyphens; no slashes/colons/namespace prefixes)"
            )
        if len(v) > _MAX_NAME:
            raise ValueError(f"pack name exceeds {_MAX_NAME} chars: {len(v)}")
        return v

    @field_validator("description")
    @classmethod
    def _validate_description(cls, v: str) -> str:
        if len(v) > _MAX_DESCRIPTION:
            raise ValueError(f"description exceeds {_MAX_DESCRIPTION} chars: {len(v)}")
        return v

    def skill_paths(self) -> list[str]:
        return [self.skills] if isinstance(self.skills, str) else list(self.skills)

    def agent_paths(self) -> list[str]:
        return [self.agents] if isinstance(self.agents, str) else list(self.agents)

    def has_hooks(self) -> bool:
        return self.hooks is not None

    def has_mcp(self) -> bool:
        return self.mcp_servers is not None


@dataclass(frozen=True)
class PackSummary:
    """A read-only description of what a pack would contribute (install preview)."""

    name: str
    version: str
    description: str
    skill_paths: list[str]
    agent_paths: list[str]
    has_hooks: bool
    has_mcp: bool


def parse_manifest(data: dict[str, Any]) -> PackManifest:
    """Validate a manifest dict → :class:`PackManifest`. Raises ``PackParseError``."""
    if not isinstance(data, dict):
        raise PackParseError(f"manifest must be a JSON object, got {type(data).__name__}")
    try:
        return PackManifest.model_validate(data)
    except Exception as exc:
        raise PackParseError(f"invalid pack manifest: {exc}") from exc


def find_manifest(pack_dir: str | Path) -> Path | None:
    """Locate the manifest file in ``pack_dir`` (cross-tool detection order).

    Returns the first existing path among the format-specific locations, or
    ``None`` if the directory has no recognizable manifest.
    """
    base = Path(pack_dir)
    for rel in _MANIFEST_PATHS:
        candidate = base / rel
        if candidate.is_file():
            return candidate
    return None


def load_manifest(pack_dir: str | Path) -> PackManifest:
    """Find + read + validate the manifest in ``pack_dir``. Read-only.

    Raises ``PackParseError`` when no manifest is found or it is malformed JSON /
    fails validation. Nothing is installed or executed.
    """
    manifest_path = find_manifest(pack_dir)
    if manifest_path is None:
        raise PackParseError(
            f"no plugin.json manifest found in {pack_dir} "
            f"(checked: {', '.join(_MANIFEST_PATHS)})"
        )
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PackParseError(f"could not read {manifest_path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PackParseError(f"malformed JSON in {manifest_path}: {exc}") from exc
    return parse_manifest(data)


def describe_pack(manifest: PackManifest) -> PackSummary:
    """A read-only summary of what the pack would contribute (no install)."""
    return PackSummary(
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        skill_paths=manifest.skill_paths(),
        agent_paths=manifest.agent_paths(),
        has_hooks=manifest.has_hooks(),
        has_mcp=manifest.has_mcp(),
    )


__all__ = [
    "PackManifest",
    "PackAuthor",
    "PackSummary",
    "PackParseError",
    "parse_manifest",
    "find_manifest",
    "load_manifest",
    "describe_pack",
]
