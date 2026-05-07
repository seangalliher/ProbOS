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
