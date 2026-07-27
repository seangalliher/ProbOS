"""AD-1154: ActionApprovalStore — standing, TTL-bounded approvals for a tool action.

A standing approval answers an approval-inbox ask once, so the same shape of act
does not have to be asked again on the next run. It is the "don't ask me again"
lever, deliberately narrow.

**Why a fourth store and not a widened existing one.** Both sibling stores were
checked against this requirement and neither can express it:

* ``ToolPermissionStore`` (AD-423b) keys a grant on ``(agent_id, tool_id,
  permission)``. There is no action column and no scope column, so granting
  ``browser`` grants *every* browser verb — including ``eval_js`` and
  ``fill_credential``.
* ``IntentGrantStore`` (AD-1005) keys on ``(agent_id, intent_name)``. Same shape
  one layer up, and ``browser`` is not a mesh intent at all.

Both are **capability** grants: *may this agent hold this tool*. A standing
approval is an **action** grant: *may this agent perform this shape of act, in
this scope, until this time*. Adding ``action`` + ``scope_key`` to
``ToolPermissionStore`` would change the meaning of every existing row and of
``check_permission``, which sits on the hot path of every tool call in the
system. So: a new store, and this module mirrors ``IntentGrantStore``
structurally — ConnectionFactory, WAL, ``busy_timeout=5000``,
``synchronous=NORMAL``, in-memory cache for a zero-I/O sync read, soft revoke for
audit — making it the fourth instance of ONE pattern rather than a fourth
pattern. ``intent_grants.py``'s own note that a unified ``CapabilityGrantStore``
is the eventual consolidation applies here too, and is still not done here.

Two properties are load-bearing and differ from the siblings:

1. **``expires_at`` is ``NOT NULL`` in the schema**, not only in the method
   signature. The three sibling stores all declare ``expires_at REAL`` nullable
   = never expires. A standing rule with no TTL is a permanent privilege
   escalation nobody remembers granting, so the invariant lives where a future
   caller passing ``None`` cannot bypass it. :meth:`ActionApprovalStore.issue_approval`
   takes ``ttl_seconds: float`` rather than ``expires_at: float | None`` so the
   type system carries it too.
2. **No wildcard.** :meth:`ActionApprovalStore.is_approved_sync` matches all four
   of ``(agent_id, tool_id, action, scope_key)`` exactly. A ``scope_key == ""``
   wildcard meaning "any scope" was considered and rejected: it reads as a
   convenience and behaves as "approve every click on every site
   forever-until-TTL", the single most dangerous row this table could hold and
   one typo away. A rule with ``scope_key=""`` matches only asks whose computed
   ``scope_key`` is ``""``.

``scope_key`` is **producer-computed**; this store never parses a URL. For
``tool_id == "browser"`` the producer supplies the lowercased registrable host;
for any other tool it supplies ``""``. That keeps the store generic without
giving it a URL parser, and it means a browser standing rule is always
domain-scoped — the operator cannot accidentally issue a global one.

Expiry is enforced **on read**, not by a reaper: :meth:`is_approved_sync` filters
on ``expires_at > time.time()`` and ``_load_cache`` filters the same way at
start, mirroring ``IntentGrantStore._load_cache``. A row past its TTL is inert
immediately; physical cleanup is a later concern and is deliberately not built
here.

Consulted ONLY by the approval-inbox wrapper in ``cognitive/agentic_dispatch.py``.
It grants nothing about mesh intents, so a standing rule can never satisfy a
quorum requirement.
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
CREATE TABLE IF NOT EXISTS action_approvals (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    tool_id TEXT NOT NULL,
    action TEXT NOT NULL,
    scope_key TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    issued_by TEXT NOT NULL DEFAULT 'captain',
    issued_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at REAL
);
CREATE INDEX IF NOT EXISTS idx_aa_lookup ON action_approvals(agent_id, tool_id, action, scope_key);
CREATE INDEX IF NOT EXISTS idx_aa_active ON action_approvals(revoked, expires_at);
"""


@dataclass
class ActionApproval:
    """A standing, expiring approval for one action shape in one scope."""

    id: str
    agent_id: str
    tool_id: str
    action: str
    scope_key: str = ""
    reason: str = ""
    issued_by: str = "captain"
    issued_at: float = 0.0
    expires_at: float = 0.0
    revoked: bool = False
    revoked_at: float | None = None


class ActionApprovalStore:
    """Persistent standing-approval store, scoped to an action shape.

    SQLite-backed with an in-memory cache for a zero-I/O sync read
    (:meth:`is_approved_sync`, called on the dispatch path). Follows the
    ``IntentGrantStore`` pattern.

    Public API:
        start() / stop() — lifecycle
        issue_approval(...) → ActionApproval
        revoke_approval(approval_id) → bool
        is_approved_sync(agent_id, tool_id, action, scope_key) → bool
        list_approvals(active_only=True) → list[ActionApproval]
    """

    def __init__(
        self,
        db_path: str = "",
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._db_path = db_path
        self._db: Any = None
        self._cache: list[ActionApproval] = []
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
            logger.info("ActionApprovalStore started (db=%s)", self._db_path)

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
            "SELECT id, agent_id, tool_id, action, scope_key, reason, issued_by, "
            "issued_at, expires_at, revoked, revoked_at FROM action_approvals "
            "WHERE revoked = 0 AND expires_at > ?",
            (now,),
        ) as cur:
            async for row in cur:
                self._cache.append(self._row_to_approval(row))

    def _row_to_approval(self, row: Any) -> ActionApproval:
        return ActionApproval(
            id=row[0],
            agent_id=row[1],
            tool_id=row[2],
            action=row[3],
            scope_key=row[4],
            reason=row[5],
            issued_by=row[6],
            issued_at=row[7],
            expires_at=row[8],
            revoked=bool(row[9]),
            revoked_at=row[10],
        )

    async def issue_approval(
        self,
        agent_id: str,
        tool_id: str,
        action: str,
        *,
        scope_key: str = "",
        ttl_seconds: float,
        reason: str = "",
        issued_by: str = "captain",
    ) -> ActionApproval:
        """Issue a standing approval that expires ``ttl_seconds`` from now.

        There is deliberately NO parameter that can produce a NULL ``expires_at``
        — ``ttl_seconds`` is required and keyword-only, and the column is
        ``NOT NULL``, so a never-expiring standing rule cannot be created through
        this API or written behind it.
        """
        now = time.time()
        approval = ActionApproval(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            tool_id=tool_id,
            action=action,
            scope_key=scope_key,
            reason=reason,
            issued_by=issued_by,
            issued_at=now,
            expires_at=now + float(ttl_seconds),
        )
        if self._db:
            await self._db.execute(
                "INSERT INTO action_approvals "
                "(id, agent_id, tool_id, action, scope_key, reason, issued_by, "
                "issued_at, expires_at, revoked, revoked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)",
                (
                    approval.id,
                    approval.agent_id,
                    approval.tool_id,
                    approval.action,
                    approval.scope_key,
                    approval.reason,
                    approval.issued_by,
                    approval.issued_at,
                    approval.expires_at,
                ),
            )
            await self._db.commit()
        self._cache.append(approval)
        logger.info(
            "AD-1154: standing approval issued by %s — %s may %s.%s in scope %r "
            "until %.0f (id=%s)",
            issued_by,
            agent_id[:12],
            tool_id,
            action,
            scope_key,
            approval.expires_at,
            approval.id[:12],
        )
        return approval

    async def revoke_approval(self, approval_id: str) -> bool:
        """Soft-revoke a standing approval (the row is retained for audit)."""
        now = time.time()
        if self._db:
            result = await self._db.execute(
                "UPDATE action_approvals SET revoked = 1, revoked_at = ? "
                "WHERE id = ? AND revoked = 0",
                (now, approval_id),
            )
            await self._db.commit()
            if result.rowcount == 0:
                return False
        self._cache = [a for a in self._cache if a.id != approval_id]
        logger.info("AD-1154: standing approval revoked: %s", approval_id[:12])
        return True

    def is_approved_sync(
        self,
        agent_id: str,
        tool_id: str,
        action: str,
        scope_key: str,
    ) -> bool:
        """Whether a live standing approval covers exactly this action shape.

        All FOUR fields must match exactly, plus ``revoked == 0`` and
        ``expires_at > now``. There is no wildcard: an approval whose
        ``scope_key`` is ``""`` matches only an ask whose ``scope_key`` is ``""``.

        Zero-I/O cache read; expired rows are dropped lazily on the way past.
        """
        return self.get_active_expiry_sync(agent_id, tool_id, action, scope_key) is not None

    def get_active_expiry_sync(
        self,
        agent_id: str,
        tool_id: str,
        action: str,
        scope_key: str,
    ) -> float | None:
        """The latest ``expires_at`` of a live approval for this shape, else None.

        Same four-part exact match and same no-wildcard rule as
        :meth:`is_approved_sync`; separated so a caller that wants to *tell the
        agent when the rule lapses* does not have to reach into the cache. Zero
        I/O; expired rows are dropped lazily on the way past.
        """
        now = time.time()
        expired_ids: list[str] = []
        latest: float | None = None
        for approval in self._cache:
            if approval.expires_at <= now:
                expired_ids.append(approval.id)
                continue
            if (
                approval.agent_id == agent_id
                and approval.tool_id == tool_id
                and approval.action == action
                and approval.scope_key == scope_key
                and not approval.revoked
            ):
                if latest is None or approval.expires_at > latest:
                    latest = approval.expires_at
        if expired_ids:
            self._cache = [a for a in self._cache if a.id not in expired_ids]
        return latest

    async def list_approvals(self, active_only: bool = True) -> list[ActionApproval]:
        """List standing approvals. ``active_only`` excludes expired and revoked."""
        if not self._db:
            if not active_only:
                return list(self._cache)
            now = time.time()
            return [
                a for a in self._cache if not a.revoked and a.expires_at > now
            ]
        sql = (
            "SELECT id, agent_id, tool_id, action, scope_key, reason, issued_by, "
            "issued_at, expires_at, revoked, revoked_at FROM action_approvals"
        )
        params: tuple[Any, ...] = ()
        if active_only:
            sql += " WHERE revoked = 0 AND expires_at > ?"
            params = (time.time(),)
        rows: list[ActionApproval] = []
        async with self._db.execute(sql, params) as cur:
            async for row in cur:
                rows.append(self._row_to_approval(row))
        return rows
