"""AD-1005: IntentGrantStore — per-agent mesh-intent grants and restrictions.

The intent counterpart to ``ToolPermissionStore`` (AD-423b) and
``SkillGrantStore`` (AD-983b). It is the **authorization substrate** for the
settled per-agent write-intent gating design (AD-1004 discussion): a crew agent
that *originates* a consensus-gated WRITE intent (e.g. ``run_python``) must be
granted that intent — per-agent authorization, checked at origination, layered
with (never replacing) the per-call consensus gate.

**Mechanism only — default OFF.** This store is NOT wired into any enforcement
path yet (mirrors the AD-1004 hook-bus discipline: build the substrate, wire it
in a later slice). Until a ``PreDispatch`` hook reads these grants, an empty
store changes nothing — no agent is gated. Today's write paths stay as they are
(Captain/decomposer → global ``execution.enabled`` + consensus; agentic-loop
tool calls → ``ToolPermissionStore``; the ``[MESH …]`` affordance is read-only).

Mirrors ``SkillGrantStore`` exactly (ConnectionFactory, WAL, sync cache read,
lazy expiry, soft-revoke for audit) — an intent grant is binary (held or not),
like a skill grant.

NOTE (refactor candidate, not done here): this is the third store mirroring
``ToolPermissionStore`` (tools / skills / intents). A unified
``CapabilityGrantStore`` parameterized by capability-kind is the natural
consolidation, but unifying three live stores is a separate refactor that must
not block the gating substrate. Mirror now; unify later.
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
CREATE TABLE IF NOT EXISTS intent_access_grants (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    intent_name TEXT NOT NULL,
    is_restriction INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    issued_by TEXT NOT NULL DEFAULT 'captain',
    issued_at REAL NOT NULL,
    expires_at REAL,
    revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at REAL
);
CREATE INDEX IF NOT EXISTS idx_iag_agent ON intent_access_grants(agent_id);
CREATE INDEX IF NOT EXISTS idx_iag_intent ON intent_access_grants(intent_name);
CREATE INDEX IF NOT EXISTS idx_iag_active ON intent_access_grants(revoked, expires_at);
"""


@dataclass
class IntentAccessGrant:
    """A per-agent mesh-intent grant (or restriction)."""

    id: str
    agent_id: str
    intent_name: str
    is_restriction: bool = False
    reason: str = ""
    issued_by: str = "captain"
    issued_at: float = 0.0
    expires_at: float | None = None
    revoked: bool = False
    revoked_at: float | None = None


class IntentGrantStore:
    """Persistent per-agent mesh-intent grant/restriction store.

    SQLite-backed with an in-memory cache for zero-I/O sync reads
    (``get_active_grants_sync``). Follows the ``SkillGrantStore`` pattern.

    Public API:
        start() / stop() — lifecycle
        issue_grant(...) → IntentAccessGrant
        revoke_grant(grant_id) → bool
        get_active_grants_sync(agent_id, intent_name?) → list[IntentAccessGrant]
        is_granted_sync(agent_id, intent_name) → bool
        list_grants(active_only=True) → list[IntentAccessGrant]
    """

    def __init__(
        self,
        db_path: str = "",
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._db_path = db_path
        self._db: Any = None
        self._cache: list[IntentAccessGrant] = []
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
            "SELECT * FROM intent_access_grants WHERE revoked = 0 AND (expires_at IS NULL OR expires_at > ?)",
            (now,),
        ) as cur:
            async for row in cur:
                self._cache.append(self._row_to_grant(row))

    def _row_to_grant(self, row: Any) -> IntentAccessGrant:
        return IntentAccessGrant(
            id=row[0],
            agent_id=row[1],
            intent_name=row[2],
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
        intent_name: str,
        *,
        is_restriction: bool = False,
        reason: str = "",
        issued_by: str = "captain",
        expires_at: float | None = None,
    ) -> IntentAccessGrant:
        """Issue a per-agent intent grant or restriction."""
        grant = IntentAccessGrant(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            intent_name=intent_name,
            is_restriction=is_restriction,
            reason=reason,
            issued_by=issued_by,
            issued_at=time.time(),
            expires_at=expires_at,
        )
        if self._db:
            await self._db.execute(
                "INSERT INTO intent_access_grants "
                "(id, agent_id, intent_name, is_restriction, reason, issued_by, issued_at, expires_at, revoked, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)",
                (
                    grant.id,
                    grant.agent_id,
                    grant.intent_name,
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
            "Intent access %s issued: %s → %s%s",
            "restriction" if is_restriction else "grant",
            agent_id,
            intent_name,
            f" (expires {expires_at})" if expires_at else "",
        )
        return grant

    async def revoke_grant(self, grant_id: str) -> bool:
        """Soft-revoke a grant (retained for audit)."""
        now = time.time()
        if self._db:
            result = await self._db.execute(
                "UPDATE intent_access_grants SET revoked = 1, revoked_at = ? WHERE id = ? AND revoked = 0",
                (now, grant_id),
            )
            await self._db.commit()
            if result.rowcount == 0:
                return False
        self._cache = [g for g in self._cache if g.id != grant_id]
        logger.info("Intent access grant revoked: %s", grant_id)
        return True

    def get_active_grants_sync(
        self,
        agent_id: str,
        intent_name: str | None = None,
    ) -> list[IntentAccessGrant]:
        """Sync read from cache — zero I/O. Filters expired grants lazily."""
        now = time.time()
        active: list[IntentAccessGrant] = []
        expired_ids: list[str] = []
        for g in self._cache:
            if g.agent_id != agent_id:
                continue
            if intent_name is not None and g.intent_name != intent_name:
                continue
            if g.expires_at is not None and g.expires_at <= now:
                expired_ids.append(g.id)
                continue
            active.append(g)
        if expired_ids:
            self._cache = [g for g in self._cache if g.id not in expired_ids]
        return active

    def is_granted_sync(self, agent_id: str, intent_name: str) -> bool:
        """Whether ``agent_id`` is authorized to originate ``intent_name``.

        A restriction wins over a grant (most-restrictive, mirrors the AD-983b
        skill overlay). Returns True only when an active grant exists AND no
        active restriction exists. This is the read a future ``PreDispatch`` hook
        consumes; it is not yet called by any enforcement path (default-OFF).
        """
        grants = self.get_active_grants_sync(agent_id, intent_name)
        if not grants:
            return False
        if any(g.is_restriction for g in grants):
            return False
        return any(not g.is_restriction for g in grants)

    def resolve_sync(self, agent_id: str, intent_name: str) -> str:
        """AD-1007: three-state per-agent capability resolution (agent-precedence).

        Returns one of:
          - ``"restricted"`` — the agent is explicitly DISABLED for this intent
            (a Captain restriction). The role/ship default must NOT override it.
          - ``"granted"`` — the agent is explicitly ENABLED for this intent
            (a Captain grant). Overrides a role default that would disable it.
          - ``"no_opinion"`` — no explicit per-agent decision; the caller falls
            back to the role/ship default.

        The Captain's AD-1007 precedence rule: an explicit per-agent decision
        wins over the role default in BOTH directions. Unlike the binary
        ``is_granted_sync`` (default-deny), this distinguishes "no decision"
        from "restricted" so an enforcement caller can correctly fall through to
        the role default when the agent has no per-agent override.

        The ``capabilities/set`` endpoint revokes the opposite active decision
        before issuing a new one, so a (agent, intent) pair carries at most one
        active decision. This method is defensive about a conflict anyway: the
        most-recent decision wins, and an exact ``issued_at`` tie resolves to
        ``"restricted"`` (fail-safe).
        """
        grants = self.get_active_grants_sync(agent_id, intent_name)
        if not grants:
            return "no_opinion"
        latest = max(g.issued_at for g in grants)
        top = [g for g in grants if g.issued_at == latest]
        if any(g.is_restriction for g in top):
            return "restricted"
        return "granted"

    async def list_grants(self, *, active_only: bool = True) -> list[IntentAccessGrant]:
        """List all grants from the database."""
        if not self._db:
            return list(self._cache)
        if active_only:
            now = time.time()
            async with self._db.execute(
                "SELECT * FROM intent_access_grants WHERE revoked = 0 AND (expires_at IS NULL OR expires_at > ?) ORDER BY issued_at DESC",
                (now,),
            ) as cur:
                return [self._row_to_grant(row) async for row in cur]
        async with self._db.execute(
            "SELECT * FROM intent_access_grants ORDER BY issued_at DESC",
        ) as cur:
            return [self._row_to_grant(row) async for row in cur]


__all__ = ["IntentGrantStore", "IntentAccessGrant"]
