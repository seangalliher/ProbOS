"""AD-481: Extension-First Architecture — Sealed Core, Open Extensions.

This package ships the OSS substrate for the Extension-First Architecture. It
provides the meta-layer above the eight existing extension points already live
at HEAD (AgentRegistry, ToolRegistry, SkillRegistry, ChannelAdapter,
IntentBus, ModelProvider/LLMTier, EventHook via _emit_event/add_event_listener,
and the Sensory Cortex perception chain).

The eight modules in this package:

- protocol.py      — Extension ABC, ExtensionType / ExtensionRiskLevel /
                     ExtensionState StrEnums, ExtensionManifest Pydantic,
                     EXTENSION_API_VERSION constant
- registry.py      — ExtensionRegistry (register/get/list/enable/disable/remove
                     + lifecycle dispatch to the eight underlying registries)
- discovery.py     — ExtensionDiscovery (filesystem scan +
                     manifest validation + semver compatibility check)
- state_store.py   — ExtensionStateStore (extension_states SQLite table +
                     ConnectionFactory-backed persistence)
- skill_manifest.py — SkillManifest Pydantic + load_skill_from_manifest adapter
                     to existing SkillDefinition (no breaking change to
                     SkillRegistry)
- sealed_core.py   — is_sealed_path helper + load_sealed_globs
- profiles.py      — ExtensionProfile Pydantic + apply_profile

Per docs/development/roadmap.md:3478 + :3595, commercial features (Agent
Marketplace, centralized extension distribution / CDN, hosted extension trust
scoring + revocation registry, paid catalog + billing surface) are tracked in
the private commercial-repo path token. This package is fully OSS substrate.
"""

from probos.extensions.protocol import (
    EXTENSION_API_VERSION,
    Extension,
    ExtensionManifest,
    ExtensionRiskLevel,
    ExtensionState,
    ExtensionType,
    ExtensionsConfig,
)
from probos.extensions.registry import ExtensionRegistry
from probos.extensions.discovery import ExtensionDiscovery
from probos.extensions.state_store import ExtensionStateStore
from probos.extensions.skill_manifest import SkillManifest, load_skill_from_manifest
from probos.extensions.sealed_core import is_sealed_path, load_sealed_globs
from probos.extensions.profiles import ExtensionProfile, apply_profile

__all__ = [
    "EXTENSION_API_VERSION",
    "Extension",
    "ExtensionDiscovery",
    "ExtensionManifest",
    "ExtensionRegistry",
    "ExtensionRiskLevel",
    "ExtensionState",
    "ExtensionStateStore",
    "ExtensionType",
    "ExtensionsConfig",
    "ExtensionProfile",
    "SkillManifest",
    "apply_profile",
    "is_sealed_path",
    "load_sealed_globs",
    "load_skill_from_manifest",
]
