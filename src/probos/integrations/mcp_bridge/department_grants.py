"""AD-1019b: DepartmentToolGrantStore — department-keyed MCP tool grants.

The **department locker** tier of the three-tier MCP authorization model
(ship locker → department lockers → agent toolbox). A tool stocked into a
department's locker is available to every agent in that department — and the
same logical tool can sit in many department lockers at once (many-to-many; a
"logical hammer" is in every locker that wants one at zero cost).

Mirrors :class:`~probos.tools.permissions.ToolPermissionStore` (AD-423b) exactly
(ConnectionFactory, WAL, in-memory cache, ``db_path=""`` cache-only, soft-revoke).

**Convention — ``agent_id`` carries the department.** This store reuses the
:class:`~probos.tools.protocol.ToolAccessGrant` dataclass rather than defining a
new type: a department grant is a ``ToolAccessGrant`` whose ``agent_id`` field
holds the *department* string. This is deliberate — the AD-1019 resolver
(:func:`~probos.integrations.mcp_bridge.access.resolve_mcp_access`) only ever
reads ``.tool_id`` and ``.is_restriction`` (never ``.agent_id``), so the
three-source resolver can fold ``list[ToolAccessGrant]`` for BOTH the agent tier
and the department tier with zero type churn and exact back-compat. The
field-name smell is contained here; callers pass a department where the source
type names ``agent_id``.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from probos.protocols import ConnectionFactory
from probos.tools.protocol import ToolAccessGrant, ToolPermission

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS department_tool_grants (
    id TEXT PRIMARY KEY,
    department TEXT NOT NULL,
    tool_id TEXT NOT NULL,
    permission TEXT NOT NULL,
    is_restriction INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    issued_by TEXT NOT NULL DEFAULT 'captain',
    issued_at REAL NOT NULL,
    expires_at REAL,
    revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at REAL
);
CREATE INDEX IF NOT EXISTS idx_dtg_department ON department_tool_grants(department);
CREATE INDEX IF NOT EXISTS idx_dtg_tool ON department_tool_grants(tool_id);
CREATE INDEX IF NOT EXISTS idx_dtg_active ON department_tool_grants(revoked, expires_at);
"""


class DepartmentToolGrantStore:
    """Persistent department-keyed tool grant/restriction store (AD-1019b).

    SQLite-backed with an in-memory cache for zero-I/O sync reads. The
    department-tier counterpart to :class:`ToolPermissionStore`; many-to-many by
    construction (no uniqueness on department×tool).

    Public API:
        start() / stop() — lifecycle
        issue_grant(department, tool_id, permission, ...) -> ToolAccessGrant
        revoke_grant(grant_id) -> bool
        get_active_grants_sync(department, tool_id?) -> list[ToolAccessGrant]
        list_grants(active_only=True) -> list[ToolAccessGrant]
    """

    def __init__(
        self,
        db_path: str = "",
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._db_path = db_path
        self._db: Any = None
        self._cache: list[ToolAccessGrant] = []
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
        """Load all active grants into the cache."""
        self._cache.clear()
        if not self._db:
            return
        now = time.time()
        async with self._db.execute(
            "SELECT * FROM department_tool_grants WHERE revoked = 0 AND (expires_at IS NULL OR expires_at > ?)",
            (now,),
        ) as cur:
            async for row in cur:
                self._cache.append(self._row_to_grant(row))

    def _row_to_grant(self, row: Any) -> ToolAccessGrant:
        # NOTE: agent_id field carries the DEPARTMENT (see module docstring).
        return ToolAccessGrant(
            id=row[0],
            agent_id=row[1],  # = department
            tool_id=row[2],
            permission=ToolPermission(row[3]),
            is_restriction=bool(row[4]),
            reason=row[5],
            issued_by=row[6],
            issued_at=row[7],
            expires_at=row[8],
            revoked=bool(row[9]),
            revoked_at=row[10],
        )

    async def issue_grant(
        self,
        department: str,
        tool_id: str,
        permission: ToolPermission,
        *,
        is_restriction: bool = False,
        reason: str = "",
        issued_by: str = "captain",
        expires_at: float | None = None,
    ) -> ToolAccessGrant:
        """Issue a department-tier tool grant or restriction."""
        grant = ToolAccessGrant(
            id=str(uuid.uuid4()),
            agent_id=department,  # = department (convention)
            tool_id=tool_id,
            permission=permission,
            is_restriction=is_restriction,
            reason=reason,
            issued_by=issued_by,
            issued_at=time.time(),
            expires_at=expires_at,
        )
        if self._db:
            await self._db.execute(
                "INSERT INTO department_tool_grants "
                "(id, department, tool_id, permission, is_restriction, reason, issued_by, issued_at, expires_at, revoked, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)",
                (
                    grant.id,
                    department,
                    grant.tool_id,
                    grant.permission.value,
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
            "AD-1019b: department tool access %s issued: %s → %s = %s%s",
            "restriction" if is_restriction else "grant",
            department,
            tool_id,
            permission.value,
            f" (expires {expires_at})" if expires_at else "",
        )
        return grant

    async def revoke_grant(self, grant_id: str) -> bool:
        """Soft-revoke a grant (retained for audit)."""
        now = time.time()
        if self._db:
            result = await self._db.execute(
                "UPDATE department_tool_grants SET revoked = 1, revoked_at = ? WHERE id = ? AND revoked = 0",
                (now, grant_id),
            )
            await self._db.commit()
            if result.rowcount == 0:
                return False
        self._cache = [g for g in self._cache if g.id != grant_id]
        logger.info("AD-1019b: department tool grant revoked: %s", grant_id)
        return True

    def get_active_grants_sync(
        self,
        department: str,
        tool_id: str | None = None,
    ) -> list[ToolAccessGrant]:
        """Sync read from cache — zero I/O. Lazily drops expired grants."""
        now = time.time()
        active: list[ToolAccessGrant] = []
        expired_ids: list[str] = []
        for g in self._cache:
            if g.agent_id != department:  # agent_id carries the department
                continue
            if tool_id is not None and g.tool_id != tool_id:
                continue
            if g.expires_at is not None and g.expires_at <= now:
                expired_ids.append(g.id)
                continue
            active.append(g)
        if expired_ids:
            self._cache = [g for g in self._cache if g.id not in expired_ids]
        return active

    async def list_grants(self, *, active_only: bool = True) -> list[ToolAccessGrant]:
        """List all department grants from the database."""
        if not self._db:
            return list(self._cache)
        if active_only:
            now = time.time()
            async with self._db.execute(
                "SELECT * FROM department_tool_grants WHERE revoked = 0 AND (expires_at IS NULL OR expires_at > ?) ORDER BY issued_at DESC",
                (now,),
            ) as cur:
                return [self._row_to_grant(row) async for row in cur]
        async with self._db.execute(
            "SELECT * FROM department_tool_grants ORDER BY issued_at DESC"
        ) as cur:
            return [self._row_to_grant(row) async for row in cur]
