"""AD-481a: Extension protocol substrate — ABC, enums, manifest, config."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


EXTENSION_API_VERSION: str = "1.0.0"
"""Semantic version of the extension contract surface.

Manifests declare `required_api_version`. ExtensionDiscovery rejects manifests
whose major version does not match the major version of EXTENSION_API_VERSION.
Minor / patch differences are tolerated (semver compatibility).
"""


class ExtensionType(StrEnum):
    """The eight extension-point types corresponding to roadmap.md:3604–3611.

    Each value maps to one of the eight existing extension points already live
    at HEAD. The ExtensionRegistry dispatches register/unregister calls to the
    underlying point based on this enum.
    """

    AGENT = "agent"                          # → AgentRegistry.register
    TOOL = "tool"                            # → ToolRegistry.register (AD-423a)
    SKILL = "skill"                          # → SkillRegistry.register_skill (AD-428)
    CHANNEL_ADAPTER = "channel_adapter"      # → ChannelAdapter subclass (Phase 24)
    MODEL_PROVIDER = "model_provider"        # → LLMTier config (AD-463)
    PERCEPTION_PROCESSOR = "perception_processor"  # → manifest declaration only in v1
    INTENT_SUBSCRIBER = "intent_subscriber"  # → IntentBus.subscribe
    EVENT_HOOK = "event_hook"                # → runtime.add_event_listener (AD-637d)


class ExtensionRiskLevel(StrEnum):
    """Graduated autonomy tier for an extension.

    - LOW: auto-approves on register; logs at info level.
    - MEDIUM: stages in PENDING_APPROVAL state; requires
      ExtensionRegistry.approve_extension(extension_id) before activation.
    - HIGH: refuses to register; emits an event requiring the existing
      approval-pipeline path (AD-482 BuildSpec gate, when shipped).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExtensionState(StrEnum):
    """Lifecycle state of a registered extension.

    Persisted in the extension_states SQLite table by ExtensionStateStore.
    """

    PENDING_APPROVAL = "pending_approval"  # MEDIUM-risk awaiting approve_extension
    ENABLED = "enabled"                    # active — registered with underlying point
    DISABLED = "disabled"                  # inactive — manifest preserved, point unregistered
    REMOVED = "removed"                    # uninstalled — preserved as audit row only


class ExtensionManifest(BaseModel):
    """Per-extension manifest read from extension.yaml.

    Validates at parse time. ExtensionDiscovery rejects malformed manifests.
    """

    manifest_version: str = "1.0"
    extension_id: str = Field(..., min_length=1, max_length=128)
    extension_type: ExtensionType
    name: str = Field(..., min_length=1, max_length=256)
    version: str = Field(..., min_length=1)
    author: str = ""
    license: str = ""
    description: str = ""
    required_api_version: str = EXTENSION_API_VERSION
    risk_level: ExtensionRiskLevel = ExtensionRiskLevel.LOW
    entry_point: str = ""              # importable module path, e.g. "extensions.agents.foo"
    dependencies: list[str] = Field(default_factory=list)  # producer contract for AD-481k
    platform_constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("extension_id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                f"extension_id must be alphanumeric with underscores/hyphens; got {v!r}"
            )
        return v

    @field_validator("manifest_version", "version", "required_api_version")
    @classmethod
    def _validate_semver(cls, v: str) -> str:
        parts = v.split(".")
        if not (1 <= len(parts) <= 3) or not all(p.isdigit() for p in parts):
            raise ValueError(f"version must be semver (major[.minor[.patch]]); got {v!r}")
        return v


class Extension(ABC):
    """Abstract base for in-process extension implementations.

    Subclasses register themselves with the ExtensionRegistry by providing
    a manifest and an activate/deactivate lifecycle. The registry dispatches
    activate() to the underlying registry (AgentRegistry / ToolRegistry / …)
    based on manifest.extension_type.
    """

    @property
    @abstractmethod
    def manifest(self) -> ExtensionManifest:
        """Return the static manifest describing this extension."""

    @abstractmethod
    async def activate(self, runtime: Any) -> None:
        """Register the extension with the appropriate underlying point."""

    @abstractmethod
    async def deactivate(self, runtime: Any) -> None:
        """Unregister from the underlying point. Manifest preserved."""


class ExtensionsConfig(BaseModel):
    """AD-481 master config block — added to SystemConfig.extensions.

    All flags default to False per AD-695 precedent for opt-in transitional
    flags. Even if the package is imported and an extension is discovered,
    the master switch keeps registrations inert until Captain explicitly opts
    in via system.yaml or runtime override.
    """

    enabled: bool = False
    """Master switch for the extension subsystem. Default False."""

    enforce_sealed_core: bool = False
    """When True, the Builder pre-write check warns on sealed-path writes.
    Hard-block (raised exception) ships at AD-481l. Default False."""

    default_profile: str = "minimal"
    """Profile name applied on first startup if no profile persisted yet."""

    extensions_dir: str = "src/probos/extensions"
    """Filesystem root for ExtensionDiscovery.scan."""

    @field_validator("default_profile")
    @classmethod
    def _validate_profile(cls, v: str) -> str:
        if v not in ("minimal", "developer", "full"):
            raise ValueError(f"default_profile must be one of minimal/developer/full; got {v!r}")
        return v
