"""AD-622: Persistent storage for ClearanceGrant records.

SQLite-backed with in-memory cache for sync access from
effective_recall_tier(). Follows ConnectionFactory pattern
for cloud-ready storage.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from probos.earned_agency import ClearanceGrant, RecallTier

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clearance_grants (
    id TEXT PRIMARY KEY,
    target_agent_id TEXT NOT NULL,
    recall_tier TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'general',
    reason TEXT NOT NULL DEFAULT '',
    issued_by TEXT NOT NULL DEFAULT 'captain',
    issued_at REAL NOT NULL,
    expires_at REAL,
    revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at REAL
);
CREATE INDEX IF NOT EXISTS idx_grants_target ON clearance_grants(target_agent_id);
CREATE INDEX IF NOT EXISTS idx_grants_active ON clearance_grants(revoked, expires_at);
"""


class ClearanceGrantStore:
    """Persistent grant storage with sync cache for effective_recall_tier().

    - issue_grant() / revoke_grant() write to DB + update cache
    - get_active_grants_sync() reads from cache (zero I/O)
    - start() loads all active grants into cache
    - stop() closes DB connection
    """

    def __init__(
        self,
        db_path: str = "",
        connection_factory: "ConnectionFactory | None" = None,
    ) -> None:
        self.db_path = db_path
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory
        self._db: Any = None
        # In-memory cache: agent_id -> list of active grants
        self._cache: dict[str, list[ClearanceGrant]] = {}

    async def start(self) -> None:
        if self.db_path:
            self._db = await self._connection_factory.connect(self.db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            await self._refresh_cache()
            logger.info("ClearanceGrantStore started (db=%s)", self.db_path)

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _refresh_cache(self) -> None:
        """Load all active grants into memory cache."""
        self._cache.clear()
        if not self._db:
            return
        now = time.time()
        async with self._db.execute(
            "SELECT id, target_agent_id, recall_tier, scope, reason, "
            "issued_by, issued_at, expires_at, revoked, revoked_at "
            "FROM clearance_grants WHERE revoked = 0 "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (now,),
        ) as cursor:
            async for row in cursor:
                grant = self._row_to_grant(row)
                self._cache.setdefault(grant.target_agent_id, []).append(grant)

    def get_active_grants_sync(self, agent_id: str) -> list[ClearanceGrant]:
        """Sync cache read — zero I/O. Used by effective_recall_tier()."""
        now = time.time()
        grants = self._cache.get(agent_id, [])
        # Filter expired grants from cache (lazy cleanup)
        active = [g for g in grants if g.expires_at is None or g.expires_at > now]
        if len(active) != len(grants):
            self._cache[agent_id] = active
        return active

    async def issue_grant(
        self,
        target_agent_id: str,
        recall_tier: RecallTier,
        scope: str = "general",
        reason: str = "",
        issued_by: str = "captain",
        expires_at: float | None = None,
    ) -> ClearanceGrant:
        """Issue a new grant. Writes to DB + updates cache."""
        grant = ClearanceGrant(
            id=str(uuid.uuid4()),
            target_agent_id=target_agent_id,
            recall_tier=recall_tier,
            scope=scope,
            reason=reason,
            issued_by=issued_by,
            issued_at=time.time(),
            expires_at=expires_at,
        )
        if self._db:
            await self._db.execute(
                "INSERT INTO clearance_grants "
                "(id, target_agent_id, recall_tier, scope, reason, "
                "issued_by, issued_at, expires_at, revoked, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)",
                (grant.id, grant.target_agent_id, grant.recall_tier.value,
                 grant.scope, grant.reason, grant.issued_by,
                 grant.issued_at, grant.expires_at),
            )
            await self._db.commit()
        # Update cache
        self._cache.setdefault(grant.target_agent_id, []).append(grant)
        logger.info(
            "AD-622: Grant issued — %s gets %s (scope=%s, by=%s, expires=%s)",
            target_agent_id[:12], recall_tier.value, scope, issued_by,
            expires_at,
        )
        return grant

    async def revoke_grant(self, grant_id: str) -> bool:
        """Soft-delete revocation. Returns True if found and revoked."""
        now = time.time()
        if self._db:
            cursor = await self._db.execute(
                "UPDATE clearance_grants SET revoked = 1, revoked_at = ? "
                "WHERE id = ? AND revoked = 0",
                (now, grant_id),
            )
            await self._db.commit()
            if cursor.rowcount == 0:
                return False
        # Update cache — remove from all agent lists
        for agent_id, grants in self._cache.items():
            self._cache[agent_id] = [g for g in grants if g.id != grant_id]
        logger.info("AD-622: Grant revoked — %s", grant_id[:12])
        return True

    async def list_grants(
        self, active_only: bool = True,
    ) -> list[ClearanceGrant]:
        """List grants. active_only=True filters expired/revoked."""
        if not self._db:
            return []
        now = time.time()
        if active_only:
            query = (
                "SELECT id, target_agent_id, recall_tier, scope, reason, "
                "issued_by, issued_at, expires_at, revoked, revoked_at "
                "FROM clearance_grants WHERE revoked = 0 "
                "AND (expires_at IS NULL OR expires_at > ?) "
                "ORDER BY issued_at DESC"
            )
            params: tuple = (now,)
        else:
            query = (
                "SELECT id, target_agent_id, recall_tier, scope, reason, "
                "issued_by, issued_at, expires_at, revoked, revoked_at "
                "FROM clearance_grants ORDER BY issued_at DESC"
            )
            params = ()
        grants = []
        async with self._db.execute(query, params) as cursor:
            async for row in cursor:
                grants.append(self._row_to_grant(row))
        return grants

    async def get_grant(self, grant_id: str) -> ClearanceGrant | None:
        """Get a specific grant by ID."""
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT id, target_agent_id, recall_tier, scope, reason, "
            "issued_by, issued_at, expires_at, revoked, revoked_at "
            "FROM clearance_grants WHERE id = ?",
            (grant_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_grant(row) if row else None

    @staticmethod
    def _row_to_grant(row: tuple) -> ClearanceGrant:
        return ClearanceGrant(
            id=row[0],
            target_agent_id=row[1],
            recall_tier=RecallTier(row[2]),
            scope=row[3],
            reason=row[4],
            issued_by=row[5],
            issued_at=row[6],
            expires_at=row[7],
            revoked=bool(row[8]),
            revoked_at=row[9],
        )
