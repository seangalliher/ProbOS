# AD-481 v1 — Extension-First Architecture (Sealed Core, Open Extensions)

**Wave:** 88
**Closes:** GH #75
**HEAD at draft:** `e39e262`
**Baseline pytest:** 11762 → **target ≥ 11842** (+80 floor; ~80 tests planned).
**Vitest:** 306 unchanged (no UI surface touched — HXI panel parked at AD-481i).
**Builder:** one commit. Read `prompts/WAVE-88-DISPATCH.md` for full reframe rationale.

## Scope (verified against HEAD)

Eight concrete OSS sub-AD letters:

- **481a** — Extension protocol substrate: `Extension` ABC, `ExtensionType` / `ExtensionRiskLevel` / `ExtensionState` StrEnums, `ExtensionManifest` Pydantic, `EXTENSION_API_VERSION = "1.0.0"` constant, `ExtensionsConfig` Pydantic (in `src/probos/extensions/protocol.py` + `config.py`)
- **481b** — `ExtensionRegistry` — register/get/list/enable/disable/remove + lifecycle dispatch (in `src/probos/extensions/registry.py`)
- **481c** — `ExtensionDiscovery` — filesystem scan over `src/probos/extensions/{agents,channels,hooks,skills,tools}/` + manifest validation + contract-version compatibility check (in `src/probos/extensions/discovery.py`)
- **481d** — `ExtensionStateStore` + `extension_states` SQLite table + load-on-startup state restoration (in `src/probos/extensions/state_store.py`)
- **481e** — Skill manifest format (`skill.yaml`) — `SkillManifest` Pydantic schema + `load_skill_from_manifest` adapter to existing `SkillDefinition` (in `src/probos/extensions/skill_manifest.py`)
- **481f** — Sealed Core boundary — `config/sealed_modules.yaml` + `is_sealed_path()` helper + warn-only Builder pre-write check at four sites in `cognitive/builder.py` (in `src/probos/extensions/sealed_core.py` + edits to `cognitive/builder.py`)
- **481g** — Extension Profiles — three preset YAMLs `minimal`/`developer`/`full` + `apply_profile()` (in `config/extension_profiles/*.yaml` + `src/probos/extensions/profiles.py`)
- **481h** — `/extensions` slash command — `list`/`enable`/`disable`/`remove`/`profile`/`info` subcommands (in `src/probos/experience/commands/commands_extensions.py` + edits to `src/probos/experience/shell.py`)

Out of scope (NOT v1 deferrals — see dispatch reframe section): AD-481i HXI extension toggle panel UI (control surface lands at 481h slash command — UI follow-up is its own vitest-budget wave), AD-481j `probos init --profile` wizard prompt (depends on AD-484c onboarding wizard partial), AD-481k auto-installation of declared skill dependencies (touches pip subprocess + needs sandboxing under AD-456 — manifest schema declares dependencies field so producers record contract, AD-481k consumer resolves them), AD-481l Builder hard-block on sealed paths (default-False flag flip — depends on AD-482 v1 RedTeam baseline), AD-481m Marketplace publishing/discovery wire protocol (depends on AD-480 + AD-479), commercial Agent Marketplace / centralized extension distribution / hosted extension trust scoring + revocation registry / paid catalog + billing surface (carved out per `roadmap.md:3478` + `:3595` to the private commercial-repo path token).

---

## Section 0 — New file: `src/probos/extensions/__init__.py`

Create the new package directory `src/probos/extensions/`. Add this `__init__.py`:

```python
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
```

Also create five empty subdirectories with `.gitkeep` markers so the layout is committed:

```
src/probos/extensions/agents/.gitkeep
src/probos/extensions/channels/.gitkeep
src/probos/extensions/hooks/.gitkeep
src/probos/extensions/skills/.gitkeep
src/probos/extensions/tools/.gitkeep
```

Each `.gitkeep` is a single line: `# AD-481: Extension subdirectory — Builder-created extensions land here.`

---

## Section 1 — New file: `src/probos/extensions/protocol.py` (AD-481a)

Pure data + ABC + Pydantic. No I/O. ~150 LOC.

```python
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
```

---

## Section 2 — New file: `src/probos/extensions/registry.py` (AD-481b)

In-memory registry. Mirrors `AgentRegistry` `asyncio.Lock()` pattern. ~200 LOC.

```python
"""AD-481b: ExtensionRegistry — in-memory catalog dispatching to the eight
underlying extension points.

The registry never owns the underlying point — it dispatches register/unregister
calls to AgentRegistry / ToolRegistry / SkillRegistry / ChannelAdapter manager
/ IntentBus / runtime event-listener APIs. Manifests + states are tracked
locally and persisted via ExtensionStateStore.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from probos.extensions.protocol import (
    Extension,
    ExtensionManifest,
    ExtensionRiskLevel,
    ExtensionState,
    ExtensionType,
)

logger = logging.getLogger(__name__)


class ExtensionRegistryError(Exception):
    """Raised when an extension registration violates an invariant."""


class ExtensionRegistry:
    """Catalog of registered extensions + lifecycle dispatch.

    Uses asyncio.Lock for thread/task safety, mirroring AgentRegistry's
    pattern at src/probos/substrate/registry.py:17. State persistence is
    delegated to ExtensionStateStore (AD-481d).
    """

    def __init__(
        self,
        runtime: Any,
        state_store: Any | None = None,  # ExtensionStateStore — typed Any to avoid import cycle
    ) -> None:
        self._runtime = runtime
        self._state_store = state_store
        self._extensions: dict[str, Extension] = {}        # extension_id → Extension instance
        self._manifests: dict[str, ExtensionManifest] = {} # extension_id → manifest
        self._states: dict[str, ExtensionState] = {}       # extension_id → state
        self._lock = asyncio.Lock()

    async def register(self, extension: Extension) -> ExtensionState:
        """Register an extension. Dispatches to the underlying point.

        Returns the resulting ExtensionState. LOW risk → ENABLED. MEDIUM risk →
        PENDING_APPROVAL (caller must invoke approve_extension to activate).
        HIGH risk → ExtensionRegistryError (must go through full BuildSpec
        approval pipeline at AD-482).
        """
        manifest = extension.manifest
        async with self._lock:
            if manifest.extension_id in self._extensions:
                raise ExtensionRegistryError(
                    f"Extension {manifest.extension_id!r} already registered"
                )

            if manifest.risk_level == ExtensionRiskLevel.HIGH:
                raise ExtensionRegistryError(
                    f"HIGH-risk extension {manifest.extension_id!r} cannot register via "
                    f"ExtensionRegistry; route through AD-482 BuildSpec approval pipeline"
                )

            self._extensions[manifest.extension_id] = extension
            self._manifests[manifest.extension_id] = manifest

            if manifest.risk_level == ExtensionRiskLevel.LOW:
                await extension.activate(self._runtime)
                self._states[manifest.extension_id] = ExtensionState.ENABLED
                logger.info(
                    "Auto-approved low-risk extension %s (type=%s, version=%s)",
                    manifest.extension_id, manifest.extension_type.value, manifest.version,
                )
            else:  # MEDIUM
                self._states[manifest.extension_id] = ExtensionState.PENDING_APPROVAL
                logger.info(
                    "Staged medium-risk extension %s (type=%s) pending Captain approval",
                    manifest.extension_id, manifest.extension_type.value,
                )

            if self._state_store is not None:
                await self._state_store.record_state(
                    manifest.extension_id, self._states[manifest.extension_id], manifest,
                )

            return self._states[manifest.extension_id]

    async def approve_extension(self, extension_id: str) -> None:
        """Activate a PENDING_APPROVAL medium-risk extension."""
        async with self._lock:
            if extension_id not in self._extensions:
                raise ExtensionRegistryError(f"Unknown extension {extension_id!r}")
            if self._states[extension_id] != ExtensionState.PENDING_APPROVAL:
                raise ExtensionRegistryError(
                    f"Extension {extension_id!r} not pending approval "
                    f"(state={self._states[extension_id].value})"
                )
            await self._extensions[extension_id].activate(self._runtime)
            self._states[extension_id] = ExtensionState.ENABLED
            if self._state_store is not None:
                await self._state_store.record_state(
                    extension_id, ExtensionState.ENABLED, self._manifests[extension_id],
                )
            logger.info("Captain approved extension %s — now ENABLED", extension_id)

    async def disable(self, extension_id: str) -> None:
        """Deactivate an enabled extension. Manifest preserved for re-enable."""
        async with self._lock:
            if extension_id not in self._extensions:
                raise ExtensionRegistryError(f"Unknown extension {extension_id!r}")
            if self._states[extension_id] != ExtensionState.ENABLED:
                logger.warning(
                    "disable(%s) called on non-enabled extension (state=%s); no-op",
                    extension_id, self._states[extension_id].value,
                )
                return
            await self._extensions[extension_id].deactivate(self._runtime)
            self._states[extension_id] = ExtensionState.DISABLED
            if self._state_store is not None:
                await self._state_store.record_state(
                    extension_id, ExtensionState.DISABLED, self._manifests[extension_id],
                )
            logger.info("Disabled extension %s", extension_id)

    async def enable(self, extension_id: str) -> None:
        """Re-activate a previously disabled extension."""
        async with self._lock:
            if extension_id not in self._extensions:
                raise ExtensionRegistryError(f"Unknown extension {extension_id!r}")
            if self._states[extension_id] == ExtensionState.ENABLED:
                return  # already enabled — idempotent
            if self._states[extension_id] not in (
                ExtensionState.DISABLED, ExtensionState.PENDING_APPROVAL,
            ):
                raise ExtensionRegistryError(
                    f"Cannot enable extension {extension_id!r} from state "
                    f"{self._states[extension_id].value}"
                )
            await self._extensions[extension_id].activate(self._runtime)
            self._states[extension_id] = ExtensionState.ENABLED
            if self._state_store is not None:
                await self._state_store.record_state(
                    extension_id, ExtensionState.ENABLED, self._manifests[extension_id],
                )
            logger.info("Enabled extension %s", extension_id)

    async def remove(self, extension_id: str) -> None:
        """Uninstall completely. Audit row preserved at REMOVED state."""
        async with self._lock:
            if extension_id not in self._extensions:
                raise ExtensionRegistryError(f"Unknown extension {extension_id!r}")
            if self._states[extension_id] == ExtensionState.ENABLED:
                await self._extensions[extension_id].deactivate(self._runtime)
            self._states[extension_id] = ExtensionState.REMOVED
            if self._state_store is not None:
                await self._state_store.record_state(
                    extension_id, ExtensionState.REMOVED, self._manifests[extension_id],
                )
            del self._extensions[extension_id]
            logger.info("Removed extension %s", extension_id)

    def get_state(self, extension_id: str) -> ExtensionState | None:
        return self._states.get(extension_id)

    def get_manifest(self, extension_id: str) -> ExtensionManifest | None:
        return self._manifests.get(extension_id)

    def list_extensions(self) -> list[ExtensionManifest]:
        """Return manifests for all known extensions (any state)."""
        return list(self._manifests.values())

    def list_by_type(self, extension_type: ExtensionType) -> list[ExtensionManifest]:
        return [m for m in self._manifests.values() if m.extension_type == extension_type]

    def list_enabled(self) -> list[ExtensionManifest]:
        return [
            self._manifests[eid]
            for eid, state in self._states.items()
            if state == ExtensionState.ENABLED
        ]
```

---

## Section 3 — New file: `src/probos/extensions/discovery.py` (AD-481c)

Filesystem scanner. ~120 LOC.

```python
"""AD-481c: ExtensionDiscovery — scan extensions/ subdirs, validate manifests."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from probos.extensions.protocol import (
    EXTENSION_API_VERSION,
    ExtensionManifest,
)

logger = logging.getLogger(__name__)


_SUBDIR_TO_TYPE: dict[str, str] = {
    "agents": "agent",
    "tools": "tool",
    "skills": "skill",
    "channels": "channel_adapter",
    "hooks": "event_hook",
}


class ExtensionDiscovery:
    """Filesystem scanner for extension manifests.

    Walks the configured extensions_dir and reads per-extension extension.yaml
    files. Validates against ExtensionManifest, then checks contract-version
    semver compatibility against EXTENSION_API_VERSION.
    """

    def __init__(self, extensions_dir: Path) -> None:
        self._root = Path(extensions_dir)

    def scan(self) -> list[ExtensionManifest]:
        """Walk the extensions/ tree, validate every extension.yaml found.

        Returns the list of valid, version-compatible manifests. Logs warnings
        for invalid or incompatible manifests but does not raise.
        """
        manifests: list[ExtensionManifest] = []
        if not self._root.exists():
            logger.debug("ExtensionDiscovery: extensions_dir %s does not exist", self._root)
            return manifests

        for subdir_name in _SUBDIR_TO_TYPE:
            subdir = self._root / subdir_name
            if not subdir.exists():
                continue
            for manifest_path in subdir.rglob("extension.yaml"):
                m = self._load_one(manifest_path)
                if m is not None:
                    manifests.append(m)
        return manifests

    def _load_one(self, manifest_path: Path) -> ExtensionManifest | None:
        try:
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as exc:
            logger.warning("ExtensionDiscovery: cannot read %s — %s", manifest_path, exc)
            return None

        if not isinstance(raw, dict):
            logger.warning(
                "ExtensionDiscovery: %s did not parse to a mapping; skipping", manifest_path,
            )
            return None

        try:
            manifest = ExtensionManifest(**raw)
        except ValidationError as exc:
            logger.warning(
                "ExtensionDiscovery: %s failed manifest validation — %s", manifest_path, exc,
            )
            return None

        if not self._is_compatible(manifest):
            logger.warning(
                "ExtensionDiscovery: %s declares required_api_version=%s; "
                "current EXTENSION_API_VERSION=%s (major mismatch); skipping",
                manifest_path, manifest.required_api_version, EXTENSION_API_VERSION,
            )
            return None

        return manifest

    @staticmethod
    def _is_compatible(manifest: ExtensionManifest) -> bool:
        """Check semver major-version compatibility.

        Manifests targeting major version N work on runtime major version N
        regardless of minor / patch. Major version mismatch → incompatible.
        """
        manifest_major = manifest.required_api_version.split(".")[0]
        runtime_major = EXTENSION_API_VERSION.split(".")[0]
        return manifest_major == runtime_major
```

---

## Section 4 — New file: `src/probos/extensions/state_store.py` (AD-481d)

SQLite persistence. Follows AD-441 / AD-428 ConnectionFactory pattern. ~120 LOC.

```python
"""AD-481d: ExtensionStateStore — extension_states SQLite persistence."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from probos.extensions.protocol import ExtensionManifest, ExtensionState
from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS extension_states (
    extension_id      TEXT PRIMARY KEY,
    status            TEXT NOT NULL,
    profile           TEXT DEFAULT '',
    enabled_at        REAL DEFAULT 0,
    disabled_at       REAL DEFAULT 0,
    manifest_json     TEXT DEFAULT '',
    last_updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ext_status ON extension_states(status);
"""


class ExtensionStateStore:
    """Persists per-extension state + manifest snapshot in SQLite.

    ConnectionFactory-backed (cloud-ready storage convention preserved).
    Schema is additive — `CREATE TABLE IF NOT EXISTS` only.
    """

    def __init__(
        self,
        db_path: str | None = None,
        connection_factory: ConnectionFactory | None = None,
    ):
        self._db_path = db_path
        self._db: DatabaseConnection | None = None
        if connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            connection_factory = default_factory
        self._connection_factory = connection_factory

    async def start(self) -> None:
        if not self._db_path:
            return
        self._db = await self._connection_factory.connect(self._db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def record_state(
        self,
        extension_id: str,
        state: ExtensionState,
        manifest: ExtensionManifest,
        profile: str = "",
    ) -> None:
        """Upsert (extension_id, state, manifest_json) row."""
        if self._db is None:
            return
        now = time.time()
        manifest_json = manifest.model_dump_json()
        # Set enabled_at on transition to ENABLED, disabled_at on transition to DISABLED/REMOVED
        enabled_at = now if state == ExtensionState.ENABLED else 0.0
        disabled_at = now if state in (ExtensionState.DISABLED, ExtensionState.REMOVED) else 0.0
        await self._db.execute(
            """
            INSERT INTO extension_states
              (extension_id, status, profile, enabled_at, disabled_at, manifest_json, last_updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(extension_id) DO UPDATE SET
              status = excluded.status,
              profile = COALESCE(NULLIF(excluded.profile, ''), extension_states.profile),
              enabled_at = CASE WHEN excluded.status = 'enabled' THEN excluded.enabled_at ELSE extension_states.enabled_at END,
              disabled_at = CASE WHEN excluded.status IN ('disabled', 'removed') THEN excluded.disabled_at ELSE extension_states.disabled_at END,
              manifest_json = excluded.manifest_json,
              last_updated_at = excluded.last_updated_at
            """,
            (extension_id, state.value, profile, enabled_at, disabled_at, manifest_json, now),
        )
        await self._db.commit()

    async def get_state(self, extension_id: str) -> ExtensionState | None:
        if self._db is None:
            return None
        async with self._db.execute(
            "SELECT status FROM extension_states WHERE extension_id = ?",
            (extension_id,),
        ) as cur:
            row = await cur.fetchone()
        return ExtensionState(row[0]) if row else None

    async def list_enabled(self) -> list[tuple[str, ExtensionManifest]]:
        """Return (extension_id, manifest) pairs for all currently-enabled rows."""
        if self._db is None:
            return []
        async with self._db.execute(
            "SELECT extension_id, manifest_json FROM extension_states WHERE status = 'enabled'"
        ) as cur:
            rows = await cur.fetchall()
        out: list[tuple[str, ExtensionManifest]] = []
        for ext_id, manifest_json in rows:
            try:
                manifest = ExtensionManifest.model_validate_json(manifest_json)
                out.append((ext_id, manifest))
            except Exception as exc:
                logger.warning(
                    "ExtensionStateStore: cannot rehydrate manifest for %s — %s", ext_id, exc,
                )
        return out

    async def set_profile(self, profile: str) -> None:
        """Persist the active profile name on every row (audit trail)."""
        if self._db is None:
            return
        await self._db.execute(
            "UPDATE extension_states SET profile = ?, last_updated_at = ?",
            (profile, time.time()),
        )
        await self._db.commit()
```

---

## Section 5 — New file: `src/probos/extensions/skill_manifest.py` (AD-481e)

Pure adapter. No SkillRegistry change. ~110 LOC.

```python
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
```

---

## Section 6 — Edit: `src/probos/skill_framework.py` (AD-481e helper)

Add a thin async helper to `SkillRegistry` that composes load + register. **No breaking change** — purely additive method.

SEARCH (anchor on the existing `register_skill` method opening — verified at line 505):

```python
    async def register_skill(self, defn: SkillDefinition) -> SkillDefinition:
```

REPLACE (insert new helper *above* `register_skill`):

```python
    async def register_from_manifest(self, yaml_path: "Path") -> SkillDefinition:
        """AD-481e: load skill.yaml + register the resulting SkillDefinition.

        Thin composition helper — equivalent to:
            defn = load_skill_from_manifest(yaml_path)
            return await self.register_skill(defn)
        """
        from probos.extensions.skill_manifest import load_skill_from_manifest
        defn = load_skill_from_manifest(yaml_path)
        return await self.register_skill(defn)

    async def register_skill(self, defn: SkillDefinition) -> SkillDefinition:
```

Add the `Path` import at the top of the file (alongside the existing imports). SEARCH (verified at top of file):

```python
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any
```

REPLACE:

```python
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
```

---

## Section 7 — New file: `src/probos/extensions/sealed_core.py` + `config/sealed_modules.yaml` (AD-481f)

### 7a. `config/sealed_modules.yaml`

```yaml
# AD-481f: Sealed-Core Boundary
#
# Path globs (relative to repo root) that are read-only to the Builder
# under the sealed-core convention. The Builder's pre-write helper
# _check_sealed_path consults this list when
# runtime.config.extensions.enforce_sealed_core is True.
#
# v1 emits logger.warning(...) only — hard-block ships at AD-481l.

sealed_globs:
  - "src/probos/substrate/**"
  - "src/probos/consensus/**"
  - "src/probos/mesh/**"
  - "src/probos/identity.py"
  - "src/probos/runtime.py"
  - "src/probos/cognitive/builder.py"
  - "src/probos/cognitive/llm_client.py"
  - "src/probos/cognitive/architect.py"
  - "src/probos/extensions/protocol.py"
  - "src/probos/extensions/registry.py"
  - "src/probos/extensions/sealed_core.py"
```

### 7b. `src/probos/extensions/sealed_core.py`

```python
"""AD-481f: Sealed-Core boundary helpers.

Reads config/sealed_modules.yaml, exposes is_sealed_path(path) for the Builder
pre-write check at cognitive/builder.py write sites.
"""

from __future__ import annotations

import fnmatch
import functools
import logging
from pathlib import Path
from typing import Iterable

import yaml

logger = logging.getLogger(__name__)


_DEFAULT_SEALED_CONFIG = Path("config/sealed_modules.yaml")


@functools.lru_cache(maxsize=1)
def load_sealed_globs(config_path: str | None = None) -> tuple[str, ...]:
    """Read sealed_modules.yaml and return the configured glob list.

    Cached after first read. Returns an empty tuple if the config file is
    missing or malformed (fail-open per Tier 2 log-and-degrade).
    """
    target = Path(config_path) if config_path else _DEFAULT_SEALED_CONFIG
    if not target.exists():
        logger.debug("sealed_modules.yaml not found at %s; returning empty glob list", target)
        return ()
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        logger.warning("Cannot read %s — %s; treating as empty", target, exc)
        return ()
    if not isinstance(raw, dict):
        return ()
    globs = raw.get("sealed_globs") or []
    if not isinstance(globs, list):
        return ()
    return tuple(str(g) for g in globs if isinstance(g, str))


def is_sealed_path(path: str | Path, sealed_globs: Iterable[str] | None = None) -> bool:
    """Return True if path matches any sealed glob.

    Uses fnmatch with `**` pattern interpreted as recursive (multi-segment)
    match — the canonical pattern for sealed_modules.yaml entries like
    `src/probos/substrate/**`.
    """
    if sealed_globs is None:
        sealed_globs = load_sealed_globs()
    p = str(path).replace("\\", "/")
    for glob in sealed_globs:
        glob_norm = glob.replace("\\", "/")
        # fnmatch treats `**` as `*` for path matching; emulate recursive glob
        # by also testing against a flattened form (drop the `**` segment).
        if fnmatch.fnmatch(p, glob_norm):
            return True
        if "**" in glob_norm:
            collapsed = glob_norm.replace("**", "*")
            if fnmatch.fnmatch(p, collapsed):
                return True
            # Also match parent-prefix form: glob "a/b/**" should match "a/b/c/d.py"
            prefix = glob_norm.split("**")[0].rstrip("/")
            if prefix and (p.startswith(prefix + "/") or p == prefix):
                return True
    return False
```

---

## Section 8 — Edit: `src/probos/cognitive/builder.py` (AD-481f Builder pre-write check)

Add a helper method on `BuilderAgent` (or whichever class owns the write sites — verify by reading lines around 2050) and call it before each of the five `write_text(...)` invocations.

Add the helper method. The helper is added to whichever class owns lines 2585/2604/2724/2729 — Builder reads two-line context around line 2580 to confirm the class name, then inserts the helper at the bottom of that class (immediately above the next top-level definition).

Helper body:

```python
    def _check_sealed_path(self, target_path: "Path") -> None:
        """AD-481f: warn-only sealed-core pre-write check.

        Reads `runtime.config.extensions.enforce_sealed_core` (default False).
        When True, emits `logger.warning(...)` — never raises in v1. Hard-block
        ships at AD-481l after AD-482 RedTeam baseline establishes false-
        positive rate. Per-BuildSpec override (`core_modification` flag) is
        intentionally NOT introduced in v1 — that knob lands with AD-481l when
        the warn becomes a raise.

        `self._runtime` follows the established BuilderAgent attribute pattern
        (verified at builder.py:2036, 2057). `runtime.config.extensions` is
        guaranteed by `SystemConfig.extensions = Field(default_factory=ExtensionsConfig)`.
        """
        if self._runtime is None:
            return
        if not self._runtime.config.extensions.enforce_sealed_core:
            return
        from probos.extensions.sealed_core import is_sealed_path
        if is_sealed_path(target_path):
            logger.warning(
                "AD-481f: Builder writing to sealed-core path %s "
                "(enforce_sealed_core=True); v1 is observation-only — "
                "hard-block ships at AD-481l",
                target_path,
            )
```

Insert this method on the Builder class. The exact insertion anchor: **read the class definition line that contains the write sites** and add the helper at the bottom of that class (before the next top-level definition). Builder may use any unique two-line context anchor near the write sites; the canonical pattern is to insert above the first write-site method.

Then at four write sites — lines 2585, 2604, 2724, 2729 — insert one line of pre-write check directly above the existing `path.write_text(...)` call. **Site at line 2053 (`dest.write_text` inside the visiting-Copilot tmp-dir copy phase) is intentionally NOT in scope** — that site copies *existing repo files into an isolated sandbox*, not a repo write, and the temp-dir absolute path will not match a repo-relative sealed glob anyway.

**Sites 1–4 — lines 2585, 2604, 2724, 2729 (`path.write_text`):** for each, insert `self._check_sealed_path(path)` on the line directly above. Builder must locate each by reading the surrounding context (3–5 lines above and below) and applying SEARCH/REPLACE blocks anchored on that local context — the bare `path.write_text(...)` line is not unique enough on its own, so each block must include 3 lines of preceding context. (Builder: read lines 2580–2735 first, then construct four separate SEARCH/REPLACE blocks.)

Net effect: four new lines of `self._check_sealed_path(...)` calls, one helper method added to BuilderAgent.

---

## Section 9 — New files: `config/extension_profiles/{minimal,developer,full}.yaml` + `src/probos/extensions/profiles.py` (AD-481g)

### 9a. Three preset YAMLs

```yaml
# config/extension_profiles/minimal.yaml
profile_name: minimal
description: |
  Safest preset — chat-only experience. No file-write extensions, no shell
  access, no self-improvement extensions enabled. New users start here.
enabled_extensions: []
```

```yaml
# config/extension_profiles/developer.yaml
profile_name: developer
description: |
  Developer preset — chat + build pipeline + code tools. File-write
  extensions enabled; shell access enabled; self-improvement extensions
  remain MEDIUM-risk pending Captain approval per extension.
enabled_extensions: []
```

```yaml
# config/extension_profiles/full.yaml
profile_name: full
description: |
  Power-user preset — every shipped extension enabled. Use only after
  reviewing the extension list and risk levels.
enabled_extensions: []
```

(v1 ships zero curated extensions — `enabled_extensions` lists are empty placeholders. Future waves populate these as concrete LOW-risk extensions land in `src/probos/extensions/{agents,channels,hooks,skills,tools}/`.)

### 9b. `src/probos/extensions/profiles.py`

```python
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
```

---

## Section 10 — Edit: `src/probos/config.py` (AD-481a config integration)

Add `ExtensionsConfig` import and `extensions` field on `SystemConfig`.

SEARCH (anchor on existing `mcp: MCPConfig = MCPConfig()` line near `config.py:2570`):

```python
    eps: EPSConfig = EPSConfig()  # AD-469
    mcp: MCPConfig = MCPConfig()  # AD-449
```

REPLACE:

```python
    eps: EPSConfig = EPSConfig()  # AD-469
    mcp: MCPConfig = MCPConfig()  # AD-449
    extensions: "ExtensionsConfig" = Field(default_factory=lambda: ExtensionsConfig())  # AD-481
```

Add `ExtensionsConfig` to `config.py` itself (top-level import to avoid circular). SEARCH (top of `config.py` — verify by reading line 1–30; pick a stable anchor like the existing top-level imports). Builder: insert the `ExtensionsConfig` import at the top of `config.py` adjacent to existing extension-config imports if any, or import it lazily by adding the model definition directly:

```python
# After the other Config classes, before SystemConfig (around line 2500):

class ExtensionsConfig(BaseModel):
    """AD-481: Extension subsystem master config.

    Mirrors src/probos/extensions/protocol.py:ExtensionsConfig — duplicated here
    to avoid circular import (config.py is imported very early; extensions/
    package imports config indirectly via runtime).
    """
    enabled: bool = False
    enforce_sealed_core: bool = False
    default_profile: str = "minimal"
    extensions_dir: str = "src/probos/extensions"
```

(Alternatively, Builder can place the `ExtensionsConfig` class in `config.py` only and have `extensions/protocol.py` re-export from there. Either approach is acceptable — pick the one that doesn't introduce a new circular import. Tests assert the field exists on `SystemConfig`; they do not assert which file owns the class.)

---

## Section 11 — New file: `src/probos/experience/commands/commands_extensions.py` (AD-481h)

Mirror the AD-596d `/skill` precedent. ~180 LOC.

```python
"""AD-481h: /extensions shell command — extension subsystem management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def cmd_extensions(runtime: "ProbOSRuntime", console: Console, args: str) -> None:
    """/extensions — extension subsystem management.

    Subcommands: list, enable, disable, remove, profile, info.
    """
    parts = args.split(maxsplit=1) if args else []
    sub = parts[0].lower() if parts else ""

    if sub == "list":
        await _ext_list(runtime, console)
    elif sub == "enable":
        await _ext_enable(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "disable":
        await _ext_disable(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "remove":
        await _ext_remove(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "profile":
        await _ext_profile(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "info":
        await _ext_info(runtime, console, parts[1] if len(parts) > 1 else "")
    else:
        console.print("[yellow]Usage: /extensions <list|enable|disable|remove|profile|info>[/yellow]")
        console.print("  list                   — list all known extensions with state")
        console.print("  enable <id>            — enable a previously-disabled extension")
        console.print("  disable <id>           — disable an enabled extension (manifest preserved)")
        console.print("  remove <id>            — uninstall an extension")
        console.print("  profile <name>         — apply a profile (minimal/developer/full)")
        console.print("  info <id>              — show full manifest details")


async def _ext_list(runtime: "ProbOSRuntime", console: Console) -> None:
    registry = getattr(runtime, "extension_registry", None)
    if registry is None:
        console.print("[red]Extension registry not available (extensions.enabled=False?).[/red]")
        return
    manifests = registry.list_extensions()
    if not manifests:
        console.print("[dim]No extensions registered.[/dim]")
        return
    table = Table(title="Registered Extensions")
    table.add_column("ID", style="cyan")
    table.add_column("Type")
    table.add_column("State", style="bold")
    table.add_column("Risk")
    table.add_column("Version")
    table.add_column("Description")
    for m in manifests:
        state = registry.get_state(m.extension_id)
        state_str = state.value if state else "unknown"
        table.add_row(
            m.extension_id,
            m.extension_type.value,
            state_str,
            m.risk_level.value,
            m.version,
            m.description[:60] + ("..." if len(m.description) > 60 else ""),
        )
    console.print(table)


async def _ext_enable(runtime: "ProbOSRuntime", console: Console, ext_id: str) -> None:
    if not ext_id:
        console.print("[yellow]Usage: /extensions enable <extension_id>[/yellow]")
        return
    registry = getattr(runtime, "extension_registry", None)
    if registry is None:
        console.print("[red]Extension registry not available.[/red]")
        return
    try:
        await registry.enable(ext_id)
        console.print(f"[green]Enabled extension {ext_id!r}.[/green]")
    except Exception as exc:
        console.print(f"[red]Failed to enable {ext_id!r}: {exc}[/red]")


async def _ext_disable(runtime: "ProbOSRuntime", console: Console, ext_id: str) -> None:
    if not ext_id:
        console.print("[yellow]Usage: /extensions disable <extension_id>[/yellow]")
        return
    registry = getattr(runtime, "extension_registry", None)
    if registry is None:
        console.print("[red]Extension registry not available.[/red]")
        return
    try:
        await registry.disable(ext_id)
        console.print(f"[green]Disabled extension {ext_id!r}.[/green]")
    except Exception as exc:
        console.print(f"[red]Failed to disable {ext_id!r}: {exc}[/red]")


async def _ext_remove(runtime: "ProbOSRuntime", console: Console, ext_id: str) -> None:
    if not ext_id:
        console.print("[yellow]Usage: /extensions remove <extension_id>[/yellow]")
        return
    registry = getattr(runtime, "extension_registry", None)
    if registry is None:
        console.print("[red]Extension registry not available.[/red]")
        return
    try:
        await registry.remove(ext_id)
        console.print(f"[green]Removed extension {ext_id!r}.[/green]")
    except Exception as exc:
        console.print(f"[red]Failed to remove {ext_id!r}: {exc}[/red]")


async def _ext_profile(runtime: "ProbOSRuntime", console: Console, profile_name: str) -> None:
    if not profile_name:
        console.print("[yellow]Usage: /extensions profile <minimal|developer|full>[/yellow]")
        return
    from probos.extensions.profiles import apply_profile
    try:
        enable_list = apply_profile(profile_name)
    except Exception as exc:
        console.print(f"[red]Failed to load profile {profile_name!r}: {exc}[/red]")
        return
    registry = getattr(runtime, "extension_registry", None)
    if registry is None:
        console.print("[red]Extension registry not available.[/red]")
        return
    enabled = 0
    disabled = 0
    enable_set = set(enable_list)
    for manifest in registry.list_extensions():
        try:
            if manifest.extension_id in enable_set:
                await registry.enable(manifest.extension_id)
                enabled += 1
            else:
                await registry.disable(manifest.extension_id)
                disabled += 1
        except Exception as exc:
            logger.warning(
                "Profile %s: failed to transition %s — %s",
                profile_name, manifest.extension_id, exc,
            )
    state_store = getattr(runtime, "extension_state_store", None)
    if state_store is not None:
        await state_store.set_profile(profile_name)
    console.print(
        f"[green]Applied profile {profile_name!r}: "
        f"{enabled} enabled, {disabled} disabled.[/green]"
    )


async def _ext_info(runtime: "ProbOSRuntime", console: Console, ext_id: str) -> None:
    if not ext_id:
        console.print("[yellow]Usage: /extensions info <extension_id>[/yellow]")
        return
    registry = getattr(runtime, "extension_registry", None)
    if registry is None:
        console.print("[red]Extension registry not available.[/red]")
        return
    manifest = registry.get_manifest(ext_id)
    if manifest is None:
        console.print(f"[red]Unknown extension {ext_id!r}.[/red]")
        return
    state = registry.get_state(ext_id)
    console.print(f"[bold cyan]{manifest.name}[/bold cyan] ({manifest.extension_id})")
    console.print(f"  type:           {manifest.extension_type.value}")
    console.print(f"  state:          {state.value if state else 'unknown'}")
    console.print(f"  risk:           {manifest.risk_level.value}")
    console.print(f"  version:        {manifest.version}")
    console.print(f"  required API:   {manifest.required_api_version}")
    console.print(f"  author:         {manifest.author or '-'}")
    console.print(f"  license:        {manifest.license or '-'}")
    console.print(f"  description:    {manifest.description or '-'}")
    if manifest.dependencies:
        console.print(f"  dependencies:   {', '.join(manifest.dependencies)}")
```

---

## Section 12 — Edit: `src/probos/experience/shell.py` (AD-481h slash wiring)

Add `/extensions` to help table and dispatch dict.

SEARCH (verified at line 104):

```python
        "/skill":     "Manage cognitive skills (list/discover/import/info/enrich/remove)",
```

REPLACE:

```python
        "/skill":     "Manage cognitive skills (list/discover/import/info/enrich/remove)",
        "/extensions": "Manage extensions (list/enable/disable/remove/profile/info) — AD-481",
```

SEARCH (verified at line 290):

```python
            "/skill":      lambda: commands_skill.cmd_skill(rt, con, arg),
```

REPLACE:

```python
            "/skill":      lambda: commands_skill.cmd_skill(rt, con, arg),
            "/extensions": lambda: commands_extensions.cmd_extensions(rt, con, arg),
```

Add the import at the top of `shell.py` adjacent to the existing `commands_skill` import:

SEARCH:

```python
from probos.experience.commands import commands_skill
```

REPLACE:

```python
from probos.experience.commands import commands_extensions, commands_skill
```

(Builder: if the existing import line uses a different shape, e.g., `from probos.experience.commands.commands_skill import cmd_skill`, mirror that style for `commands_extensions`. Read shell.py imports to confirm.)

---

## Section 13 — Edit: `docs/development/roadmap.md` (AD-481 v1 status update)

Update the AD-481 entry at `roadmap.md:7033` to reflect the v1 ship.

SEARCH:

```
**AD-481: Extension-First Architecture — Sealed Core, Open Extensions** *(planned)*
```

REPLACE:

```
**AD-481: Extension-First Architecture — Sealed Core, Open Extensions** *(partial — v1 ships eight concrete sub-AD letters 481a/b/c/d/e/f/g/h; HXI panel deferred to AD-481i, init-wizard profile prompt to AD-481j depending on AD-484c, auto-install of skill dependencies to AD-481k depending on AD-456 sandboxing, Builder hard-block on sealed paths to AD-481l depending on AD-482 RedTeam, Marketplace wire protocol to AD-481m depending on AD-480 + AD-479; commercial Agent Marketplace + centralized distribution + hosted trust scoring + paid catalog tracked in the private commercial-repo path token per `roadmap.md:3478` + `:3595`)*
```

---

## Tests — eight classes, ~80 tests total

Builder creates one new test file: `tests/test_ad481_extensions.py`. Eight classes:

- `TestExtensionProtocol` (~10 tests) — ExtensionType / ExtensionRiskLevel / ExtensionState StrEnum values; ExtensionManifest validation (good shape, malformed extension_id, malformed semver, default values); EXTENSION_API_VERSION format; ExtensionsConfig defaults all False; ExtensionsConfig.default_profile validator rejects unknown names.
- `TestExtensionRegistry` (~12 tests) — register LOW auto-enables; register MEDIUM stages PENDING_APPROVAL; register HIGH raises ExtensionRegistryError; duplicate register raises; approve_extension transitions PENDING_APPROVAL→ENABLED; approve on non-pending raises; disable→enable round-trip; remove transitions to REMOVED + drops from _extensions but keeps state row; list_extensions returns all manifests; list_by_type filters; list_enabled excludes DISABLED/PENDING/REMOVED; state_store.record_state called on every transition.
- `TestExtensionDiscovery` (~10 tests) — scan empty dir returns []; scan dir without subdirs returns []; valid manifest under agents/ accepted; invalid YAML logged + skipped; failing pydantic validation logged + skipped; major-version mismatch rejected (manifest required_api_version=2.0.0 vs runtime 1.0.0); minor-version drift accepted; manifest under all five subdirs (agents/channels/hooks/skills/tools) all detected; nested extension dirs supported via rglob; non-mapping YAML rejected.
- `TestExtensionStateStore` (~10 tests) — start creates table; record_state inserts new row; record_state upserts existing row; enabled_at set on ENABLED transition; disabled_at set on DISABLED/REMOVED; get_state returns None for unknown; list_enabled excludes DISABLED rows; manifest_json round-trips through ExtensionManifest.model_validate_json; set_profile updates all rows; stop closes connection.
- `TestSkillManifest` (~8 tests) — load_skill_from_manifest happy path produces SkillDefinition; missing required field raises ValueError; bad category raises ValueError; negative decay_rate_days raises; preferred_tools list translates to ToolPreference list; dependencies field preserved (producer contract for AD-481k); composite_skill_ids + synergy_partners passthrough; SkillRegistry.register_from_manifest end-to-end (load + register + lookup).
- `TestSealedCore` (~10 tests) — load_sealed_globs reads YAML; missing file returns empty tuple; malformed YAML returns empty tuple; is_sealed_path matches `src/probos/substrate/agent.py` against `src/probos/substrate/**`; matches `src/probos/identity.py` against `src/probos/identity.py`; rejects `src/probos/extensions/agents/foo.py`; case-sensitive on POSIX; backslash-to-slash normalization on Windows; LRU cache returns same tuple across repeated calls; Builder._check_sealed_path emits warning when enforce_sealed_core=True + sealed path; Builder._check_sealed_path silent when enforce_sealed_core=False (default).
- `TestExtensionProfiles` (~8 tests) — load_profile minimal returns ExtensionProfile; load_profile developer returns ExtensionProfile; load_profile full returns ExtensionProfile; load_profile rejects unknown name; apply_profile returns enabled_extensions list; ExtensionProfile validator rejects bad name; profile YAML missing required field raises; profiles_dir parameter overrides default.
- `TestSlashExtensionsCommand` (~12 tests) — cmd_extensions with no args prints usage; list with no extensions prints "no extensions registered"; list with three extensions renders table; enable on unknown id prints error; enable on disabled extension transitions to ENABLED; disable on enabled extension transitions to DISABLED; remove drops from registry; profile minimal applies (registry.disable called for non-listed); profile rejects unknown name; info on unknown id prints error; info on known id renders manifest details; help is helpful when subcommand unrecognized.

**Test count target: 80 floor (~80 actual). Pytest baseline 11762 → ≥ 11842.**

Tests use real Pydantic instances (`ExtensionsConfig()`, `ExtensionManifest(...)`) — never `_FakeConfig`. State store tests use `tmp_path` fixture for SQLite paths. Slash command tests use `_FakeRuntime` with `extension_registry` attribute holding a real `ExtensionRegistry` over a `_FakeStateStore`.

---

## What This Does NOT Change

- No edits to `BaseAgent`, `IntentMessage`, `IntentResult`, `TaskDAG`, `acm.py`, `episodic.py`, consensus, trust, attention, dreaming, decomposer, prompt builder, runtime.py boot ordering (only finalize-phase wiring of the registry).
- No new EventType.
- No new pool, no new agent, no new Intent, no router edit, no Hebbian touch, no Shapley change.
- No new AD numbers minted (sub-AD letters 481a–m organizational only).
- No UI surface — vitest unchanged at 306. HXI panel parked at AD-481i with explicit forcing function.
- No edits to existing tests.
- No `_FakeConfig`-style stubs introduced — tests use real `ExtensionsConfig()`.
- No edit to `SkillRegistry.register_skill` — only adds new helper `register_from_manifest` above it.
- No removal of any existing config field, table, or helper.

## Tracking

- Update `PROGRESS.md` test count: 11762 → final.
- Update `docs/development/roadmap.md:7033` AD-481 status from `*(planned)*` to `*(partial — v1 ships ...)*` per Section 13.
- No new entry in `DECISIONS.md` — AD-481 is pre-allocated; sub-AD letters are organizational.
- Append archive entry to `prompts/archive/` (Builder moves dispatch + prompt on completion).

## Acceptance Criteria

- All ~80 new tests pass under serial (`-n 0`) and full parallel (`-n 4 --dist=loadfile`) gates.
- Pytest baseline 11762 → ≥ 11842 floor (allow Builder to overshoot if extra boundary tests land).
- vitest unchanged at 306 (305 passing + 1 pre-existing `WardRoomDmSync` failure).
- `git status -s` after build shows only Wave 88 artifacts + the standard PROGRESS.md / roadmap.md edits.
- Pre-commit hook passes (zero banned-pattern hits across all staged files).
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
- Single commit message: `AD-481: Extension-First Architecture v1 (sealed core + 8 extension types + skill manifest format + toggle + profiles + /extensions slash) (+80 tests)`.
- Close GH #75 with the closure note from the dispatch.
- Archive `prompts/WAVE-88-DISPATCH.md` and `prompts/ad-481-extension-first-v1.md` to `prompts/archive/`.

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  e39e262

# Pytest baseline:
.venv\Scripts\pytest.exe --collect-only -q tests/
  11762 tests collected in 5.94s

# Roadmap line anchors (verified):
docs/development/roadmap.md:3463          # Skill Manifest Format header (AD-481)
docs/development/roadmap.md:3478          # "Pairs with the commercial Agent Marketplace ..."
docs/development/roadmap.md:3595          # Extension-First Architecture header (AD-481)
docs/development/roadmap.md:3604–3611     # eight extension points enumerated
docs/development/roadmap.md:3643          # Extension Toggle header (AD-481)
docs/development/roadmap.md:7033          # AD-481 backlog entry (insertion site for partial-status)

# Eight extension points already live (verified):
src/probos/substrate/registry.py:17       # class AgentRegistry; :28 register
src/probos/tools/registry.py:49           # class ToolRegistry (AD-423a/b)
src/probos/skill_framework.py:427         # class SkillRegistry (AD-428); :505 register_skill
src/probos/channels/base.py:34            # class ChannelAdapter(ABC)
src/probos/mesh/intent.py:72              # class IntentBus
src/probos/config.py:230                  # def tier_config (LLMTier — ModelProvider analogue, AD-463)
# PerceptionPipeline registry NOT yet at HEAD — manifest-only declaration in v1
# EventHook = runtime._emit_event + add_event_listener (AD-637d)

# Slash command precedent (verified — AD-596d /skill is the template):
src/probos/experience/commands/commands_skill.py:1     # AD-596d module header
src/probos/experience/commands/commands_skill.py:17    # async def cmd_skill entrypoint
src/probos/experience/shell.py:104                     # "/skill": "Manage cognitive skills..." help table
src/probos/experience/shell.py:290                     # "/skill": lambda: commands_skill.cmd_skill(...) dispatch

# Builder write sites (verified — four locations need _check_sealed_path call):
src/probos/cognitive/builder.py:2585      # path.write_text(modified, encoding="utf-8")  — sealed-core check site 1
src/probos/cognitive/builder.py:2585      # path.write_text(modified, encoding="utf-8")
src/probos/cognitive/builder.py:2604      # path.write_text(change["content"], encoding="utf-8")
src/probos/cognitive/builder.py:2724      # path.write_text(mod, encoding="utf-8")
src/probos/cognitive/builder.py:2729      # path.write_text(...)

# ConnectionFactory storage convention (verified):
src/probos/identity.py:307–363            # _IDENTITY_SCHEMA — pattern for new CREATE TABLE IF NOT EXISTS
src/probos/identity.py:377                # def __init__(self, ..., connection_factory: ConnectionFactory | None = None)
src/probos/skill_framework.py:436         # SkillRegistry.__init__ ConnectionFactory parameter

# SystemConfig integration site (verified):
src/probos/config.py:2507                 # class SystemConfig(BaseModel)
src/probos/config.py:~2570                # mcp: MCPConfig — anchor for new extensions: ExtensionsConfig field

# Greenfield (verified):
src/probos/extensions/                    # does not exist at HEAD — Wave 88 creates the package

# Pre-commit hook patterns (verified for audit safety):
.git/hooks/pre-commit:5–17                # 11 banned patterns; literal forms NOT reproduced anywhere in this prompt
```
