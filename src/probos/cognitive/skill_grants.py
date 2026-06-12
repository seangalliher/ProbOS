"""AD-983b: SkillGrantStore — per-agent cognitive-skill grants and restrictions.

The skill counterpart to ``ToolPermissionStore`` (AD-423b). Tools already had
per-agent grants; cognitive skills were gated only by department + rank
(``CognitiveSkillCatalog.list_entries``), so a skill could not be enabled on one
agent and withheld from its department peers. This store closes that gap: a
SQLite-backed, in-memory-cached, per-agent overlay of skill grants and
restrictions that ``CognitiveSkillCatalog.effective_entries_for_agent`` layers
on top of the dept/rank defaults.

Mirrors ``ToolPermissionStore`` exactly (ConnectionFactory, WAL, sync cache
read, lazy expiry, soft-revoke for audit) — minus the permission level, since a
cognitive skill is binary (an agent either holds it or not).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_access_grants (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    is_restriction INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    issued_by TEXT NOT NULL DEFAULT 'captain',
    issued_at REAL NOT NULL,
    expires_at REAL,
    revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at REAL
);
CREATE INDEX IF NOT EXISTS idx_sag_agent ON skill_access_grants(agent_id);
CREATE INDEX IF NOT EXISTS idx_sag_skill ON skill_access_grants(skill_name);
CREATE INDEX IF NOT EXISTS idx_sag_active ON skill_access_grants(revoked, expires_at);
"""


@dataclass
class SkillAccessGrant:
    """A per-agent cognitive-skill grant (or restriction)."""

    id: str
    agent_id: str
    skill_name: str
    is_restriction: bool = False
    reason: str = ""
    issued_by: str = "captain"
    issued_at: float = 0.0
    expires_at: float | None = None
    revoked: bool = False
    revoked_at: float | None = None


class SkillGrantStore:
    """Persistent per-agent cognitive-skill grant/restriction store.

    SQLite-backed with an in-memory cache for zero-I/O sync reads
    (``get_active_grants_sync``). Follows the ``ToolPermissionStore`` pattern.

    Public API:
        start() / stop() — lifecycle
        issue_grant(...) → SkillAccessGrant
        revoke_grant(grant_id) → bool
        get_active_grants_sync(agent_id, skill_name?) → list[SkillAccessGrant]
        list_grants(active_only=True) → list[SkillAccessGrant]
    """

    def __init__(
        self,
        db_path: str = "",
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._db_path = db_path
        self._db: Any = None
        self._cache: list[SkillAccessGrant] = []
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            self._connection_factory = default_factory

    async def start(self) -> None:
        if self._db_path:
            self._db = await self._connection_factory.connect(self._db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            await self._load_cache()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _load_cache(self) -> None:
        self._cache.clear()
        if not self._db:
            return
        now = time.time()
        async with self._db.execute(
            "SELECT * FROM skill_access_grants WHERE revoked = 0 AND (expires_at IS NULL OR expires_at > ?)",
            (now,),
        ) as cur:
            async for row in cur:
                self._cache.append(self._row_to_grant(row))

    def _row_to_grant(self, row: Any) -> SkillAccessGrant:
        return SkillAccessGrant(
            id=row[0],
            agent_id=row[1],
            skill_name=row[2],
            is_restriction=bool(row[3]),
            reason=row[4],
            issued_by=row[5],
            issued_at=row[6],
            expires_at=row[7],
            revoked=bool(row[8]),
            revoked_at=row[9],
        )

    async def issue_grant(
        self,
        agent_id: str,
        skill_name: str,
        *,
        is_restriction: bool = False,
        reason: str = "",
        issued_by: str = "captain",
        expires_at: float | None = None,
    ) -> SkillAccessGrant:
        """Issue a per-agent skill grant or restriction."""
        grant = SkillAccessGrant(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            skill_name=skill_name,
            is_restriction=is_restriction,
            reason=reason,
            issued_by=issued_by,
            issued_at=time.time(),
            expires_at=expires_at,
        )
        if self._db:
            await self._db.execute(
                "INSERT INTO skill_access_grants "
                "(id, agent_id, skill_name, is_restriction, reason, issued_by, issued_at, expires_at, revoked, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)",
                (
                    grant.id,
                    grant.agent_id,
                    grant.skill_name,
                    int(grant.is_restriction),
                    grant.reason,
                    grant.issued_by,
                    grant.issued_at,
                    grant.expires_at,
                ),
            )
            await self._db.commit()
        self._cache.append(grant)
        logger.info(
            "Skill access %s issued: %s → %s%s",
            "restriction" if is_restriction else "grant",
            agent_id,
            skill_name,
            f" (expires {expires_at})" if expires_at else "",
        )
        return grant

    async def revoke_grant(self, grant_id: str) -> bool:
        """Soft-revoke a grant (retained for audit)."""
        now = time.time()
        if self._db:
            result = await self._db.execute(
                "UPDATE skill_access_grants SET revoked = 1, revoked_at = ? WHERE id = ? AND revoked = 0",
                (now, grant_id),
            )
            await self._db.commit()
            if result.rowcount == 0:
                return False
        self._cache = [g for g in self._cache if g.id != grant_id]
        logger.info("Skill access grant revoked: %s", grant_id)
        return True

    def get_active_grants_sync(
        self,
        agent_id: str,
        skill_name: str | None = None,
    ) -> list[SkillAccessGrant]:
        """Sync read from cache — zero I/O. Filters expired grants lazily."""
        now = time.time()
        active: list[SkillAccessGrant] = []
        expired_ids: list[str] = []
        for g in self._cache:
            if g.agent_id != agent_id:
                continue
            if skill_name is not None and g.skill_name != skill_name:
                continue
            if g.expires_at is not None and g.expires_at <= now:
                expired_ids.append(g.id)
                continue
            active.append(g)
        if expired_ids:
            self._cache = [g for g in self._cache if g.id not in expired_ids]
        return active

    async def list_grants(self, *, active_only: bool = True) -> list[SkillAccessGrant]:
        """List all grants from the database."""
        if not self._db:
            return list(self._cache)
        if active_only:
            now = time.time()
            async with self._db.execute(
                "SELECT * FROM skill_access_grants WHERE revoked = 0 AND (expires_at IS NULL OR expires_at > ?) ORDER BY issued_at DESC",
                (now,),
            ) as cur:
                return [self._row_to_grant(row) async for row in cur]
        async with self._db.execute(
            "SELECT * FROM skill_access_grants ORDER BY issued_at DESC",
        ) as cur:
            return [self._row_to_grant(row) async for row in cur]


__all__ = ["SkillGrantStore", "SkillAccessGrant"]
