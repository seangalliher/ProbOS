"""AD-481d: ExtensionStateStore — extension_states SQLite persistence."""

from __future__ import annotations

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
