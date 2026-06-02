"""AD-818 (#751): Schema-version sidecar for episodic-memory migrations.

A small SQLite sidecar that records *which migration ran at which version*.
The boot path consults it so a migration whose recorded version matches the
current code version is skipped without scanning the entire ChromaDB
collection — turning an O(N) full-collection load into an O(1) indexed lookup
on every boot after the first.

Mirrors the AD-570b ``ParticipantIndex`` sidecar pattern: abstract connection
interface via ``connection_factory`` for Cloud-Ready Storage.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# AD-818: version string per versioned migration. Bump a value when that
# migration's OUTPUT SHAPE changes, so every store re-runs it exactly once.
# ⚠️ BUMP CONTRACT: if you change a migration's output metadata, you MUST bump
# its value here, or every store will SKIP the corrected migration. (The
# data-shape-derived hash from #751 is the explicit AD-818 follow-up seam.)
# BF-207 (hash heal-sweep) is intentionally absent — it is not a one-shot
# schema migration and must keep running every boot.
MIGRATION_VERSIONS: dict[str, str] = {
    "BF-103": "1",
    "AD-570": "1",
    "AD-570b": "1",
    "AD-584": "1",
    "AD-605": "1",
}


class SchemaVersionStore:
    """SQLite sidecar recording which episodic migration ran at which version.

    Lets the boot path skip a migration's full-collection scan when its recorded
    version_hash matches the current code version (AD-818). Mirrors the AD-570b
    ParticipantIndex sidecar pattern for Cloud-Ready Storage.

    Parameters
    ----------
    connection_factory : callable
        Async callable returning an ``aiosqlite``-compatible connection.
        If ``None``, uses a default aiosqlite.connect to *db_path*.
    db_path : str
        Fallback path for SQLite if no connection_factory provided.
    """

    _SCHEMA = """\
CREATE TABLE IF NOT EXISTS schema_versions (
    migration_id TEXT PRIMARY KEY,
    applied_at REAL NOT NULL DEFAULT 0.0,
    episode_count INTEGER NOT NULL DEFAULT 0,
    version_hash TEXT NOT NULL DEFAULT ''
);
"""

    def __init__(
        self,
        *,
        connection_factory: Callable[..., Any] | None = None,
        db_path: str = "",
    ) -> None:
        self._connection_factory = connection_factory
        self._db_path = db_path
        self._db: Any = None

    async def start(self) -> None:
        """Initialize SQLite connection and create schema."""
        if self._connection_factory:
            self._db = await self._connection_factory()
        else:
            import aiosqlite
            self._db = await aiosqlite.connect(self._db_path)
        for stmt in self._SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await self._db.execute(stmt)
        await self._db.commit()

    async def stop(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def get(self, migration_id: str) -> dict | None:
        """Return {migration_id, applied_at, episode_count, version_hash} or None.

        Returns ``None`` when no row exists for *migration_id* or on any DB
        error (Tier-2 log-and-degrade: a read fault must not crash boot — the
        caller treats a missing row as "not current" and runs the migration)."""
        if not self._db:
            return None
        try:
            cursor = await self._db.execute(
                "SELECT migration_id, applied_at, episode_count, version_hash "
                "FROM schema_versions WHERE migration_id = ?",
                (migration_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
        except Exception:
            logger.warning(
                "AD-818: schema_versions get failed for migration_id=%s "
                "(non-fatal); treating as no recorded version",
                migration_id,
                exc_info=True,
            )
            return None
        if row is None:
            return None
        return {
            "migration_id": row[0],
            "applied_at": row[1],
            "episode_count": row[2],
            "version_hash": row[3],
        }

    async def record(
        self,
        migration_id: str,
        *,
        episode_count: int,
        version_hash: str,
        applied_at: float | None = None,
    ) -> None:
        """INSERT OR REPLACE the row (applied_at defaults to time.time()).

        On any DB error: Tier-2 log-and-degrade (swallow, never propagate) — a
        sidecar write fault must not crash a boot whose migration already
        succeeded; the row simply re-versions next boot."""
        if not self._db:
            return
        if applied_at is None:
            applied_at = time.time()
        try:
            await self._db.execute(
                "INSERT OR REPLACE INTO schema_versions "
                "(migration_id, applied_at, episode_count, version_hash) "
                "VALUES (?, ?, ?, ?)",
                (migration_id, applied_at, episode_count, version_hash),
            )
            await self._db.commit()
        except Exception:
            logger.warning(
                "AD-818: schema_versions record failed for migration_id=%s "
                "(non-fatal); migration will re-version next boot",
                migration_id,
                exc_info=True,
            )

    async def is_current(self, migration_id: str, version_hash: str) -> bool:
        """True iff a row exists for migration_id AND its version_hash matches.

        Returns False on any DB error (log-and-degrade → caller runs the
        migration, never crashes boot)."""
        row = await self.get(migration_id)
        if row is None:
            return False
        return row.get("version_hash") == version_hash
