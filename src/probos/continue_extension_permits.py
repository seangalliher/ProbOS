"""AD-1323 (#1478): durable single-use permits for a costed continue extension.

A permit is the only thing that lets a turn that stopped at its token budget run
once more. It is minted in state ``requested`` when the agent files its costed
``continue`` ask, becomes ``active`` only when somebody *other than the asking
agent* approves that exact request, and is spent by one compare-and-set
(``consume``). Nothing else mints, widens or revives one: a standing grant, an
ordinary AD-1164 continue request, or a replayed event confers nothing.

Every transition is one conditional ``UPDATE`` whose ``rowcount`` is the answer,
so two racing callers cannot both win and a crash between steps leaves a row in
a state the startup sweep can read. Rows are never deleted: a spent or voided
permit stays as the record that the extension was used (``ux_cep_work_item``
refuses a second permit for one work item, in any state).

A permit is first reserved *unbound* (``bound = 0``, a work-item-keyed
placeholder id) before its request is filed, and bound to the real request id
once the item is parked on it. An unbound permit can never be activated for a
fulfilment, so nothing is resumable before permit and park agree.

``started_at`` marks the moment a consumed permit's pass is about to make its
first model call (``begin_pass``). A consumed permit that never reached that
point (a crash while the pass queued for a slot) is provably unspent and is
reclaimed once by the startup sweep. A crash after ``begin_pass`` leaves it
consumed and never reclaimed: the extension is lost, double spend is impossible.
Exactly-once across LLM execution is NOT claimed.

Storage goes through :class:`probos.protocols.ConnectionFactory` so a hosted
backend can replace SQLite. Data plus compare-and-set only: it imports nothing
from the runtime.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

STATE_REQUESTED = "requested"
STATE_ACTIVE = "active"
STATE_CONSUMED = "consumed"
STATE_VOIDED = "voided"
STOP_TEXT_MAX_CHARS = 2000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS continue_extension_permits (
    request_id TEXT PRIMARY KEY CHECK (length(request_id) > 0),
    agent_id TEXT NOT NULL CHECK (length(agent_id) > 0),
    work_item_id TEXT NOT NULL CHECK (length(work_item_id) > 0),
    thread_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('requested', 'active', 'consumed', 'voided')),
    cap_tokens INTEGER NOT NULL CHECK (cap_tokens >= 0),
    created_at REAL NOT NULL,
    decided_by TEXT NOT NULL DEFAULT '',
    activated_at REAL,
    expires_at REAL,
    consumed_at REAL,
    voided_at REAL,
    stop_text TEXT,
    plan_mode INTEGER,
    configured_budget INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cep_work_item ON continue_extension_permits(work_item_id);
CREATE INDEX IF NOT EXISTS idx_cep_state ON continue_extension_permits(state, expires_at);
"""

_SNAPSHOT_COLUMNS = (
    ("stop_text", "TEXT"),
    ("plan_mode", "INTEGER"),
    ("configured_budget", "INTEGER"),
    ("bound", "INTEGER NOT NULL DEFAULT 1"),
    ("started_at", "REAL"),
    ("reclaims", "INTEGER NOT NULL DEFAULT 0"),
)
FILING_PREFIX = "filing:"
_COLUMNS = (
    "request_id, agent_id, work_item_id, thread_id, state, cap_tokens, created_at, "
    "decided_by, activated_at, expires_at, consumed_at, voided_at, stop_text, plan_mode, "
    "configured_budget, bound, started_at, reclaims"
)


@dataclass(frozen=True)
class ContinueExtensionPermit:
    """One permit row. ``cap_tokens == 0`` means the turn's own configured budget."""

    request_id: str
    agent_id: str
    work_item_id: str
    thread_id: str
    state: str
    cap_tokens: int
    created_at: float
    decided_by: str = ""
    activated_at: float | None = None
    expires_at: float | None = None
    consumed_at: float | None = None
    voided_at: float | None = None
    stop_text: str | None = None
    plan_mode: bool | None = None
    configured_budget: int | None = None
    bound: bool = True
    started_at: float | None = None
    reclaims: int = 0


@runtime_checkable
class ContinueExtensionPermitFiling(Protocol):
    """The filing-phase surface: reserve unbound, bind, look up, void."""

    async def reserve(
        self,
        *,
        request_id: str,
        agent_id: str,
        work_item_id: str,
        thread_id: str,
        cap_tokens: int,
        stop_text: str,
        plan_mode: bool,
        configured_budget: int,
    ) -> bool: ...

    async def reserve_filing(
        self,
        *,
        agent_id: str,
        work_item_id: str,
        thread_id: str,
        cap_tokens: int,
        stop_text: str,
        plan_mode: bool,
        configured_budget: int,
    ) -> str | None: ...

    async def bind(self, work_item_id: str, request_id: str) -> bool: ...

    async def get_for_request(
        self, request_id: str, work_item_id: str | None,
    ) -> ContinueExtensionPermit | None: ...

    async def void_unbound(self, work_item_id: str) -> bool: ...

    async def void_reservation(self, work_item_id: str, request_id: str = "") -> bool: ...

    async def list_unbound(self) -> list[ContinueExtensionPermit]: ...

    async def list_requested(self) -> list[ContinueExtensionPermit]: ...

    async def has_work_item(self, work_item_id: str) -> bool: ...


@runtime_checkable
class ContinueExtensionPermitRecovery(Protocol):
    """The crash-recovery surface: mark the first pass, reclaim once, list the unstarted."""

    async def begin_pass(self, request_id: str) -> bool: ...

    async def reclaim_unstarted(self, request_id: str) -> ContinueExtensionPermit | None: ...

    async def list_consumed_unstarted(self) -> list[ContinueExtensionPermit]: ...


@runtime_checkable
class ContinueExtensionPermits(ContinueExtensionPermitFiling, ContinueExtensionPermitRecovery, Protocol):
    """The narrow surface consumers depend on."""

    async def activate(
        self, request_id: str, *, decided_by: str,
    ) -> ContinueExtensionPermit | None: ...

    async def consume(
        self, request_id: str, *, agent_id: str, work_item_id: str, thread_id: str,
    ) -> ContinueExtensionPermit | None: ...

    async def void(self, request_id: str) -> bool: ...

    async def void_expired(self) -> int: ...

    async def get(self, request_id: str) -> ContinueExtensionPermit | None: ...

    async def list_active(self) -> list[ContinueExtensionPermit]: ...


def _decode_plan_mode(value: Any) -> bool | None:
    if type(value) is int and value in (0, 1):
        return bool(value)
    return None


def _row_to_permit(row: Any) -> ContinueExtensionPermit:
    return ContinueExtensionPermit(
        request_id=row[0],
        agent_id=row[1],
        work_item_id=row[2],
        thread_id=row[3],
        state=row[4],
        cap_tokens=int(row[5]),
        created_at=float(row[6]),
        decided_by=row[7] or "",
        activated_at=row[8],
        expires_at=row[9],
        consumed_at=row[10],
        voided_at=row[11],
        stop_text=row[12],
        plan_mode=_decode_plan_mode(row[13]),
        configured_budget=row[14],
        bound=bool(row[15]),
        started_at=row[16],
        reclaims=int(row[17] or 0),
    )


class _FilingPermits:
    """AD-1323 filing phase of the store: the permit before, during and just after the request is filed.

    Methods run against the host store's ``_write``, ``_require_db``, ``_now``, ``_list`` and ``get``;
    it exists only to keep each class to one reason to change.
    """

    async def reserve(
        self,
        *,
        request_id: str,
        agent_id: str,
        work_item_id: str,
        thread_id: str,
        cap_tokens: int,
        stop_text: str,
        plan_mode: bool,
        configured_budget: int,
    ) -> bool:
        """Record a ``requested`` permit; ``False`` when this work item already has one.

        Raises on a malformed argument or a storage failure; the caller treats
        either as "no permit", so the ask mints nothing.
        """
        for label, value in (
            ("request_id", request_id), ("agent_id", agent_id), ("work_item_id", work_item_id),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"AD-1323: {label} must be a non-empty string")
        if type(thread_id) is not str:
            raise ValueError("AD-1323: thread_id must be a string")
        if type(cap_tokens) is not int or cap_tokens < 0:
            raise ValueError("AD-1323: cap_tokens must be a non-negative int")
        if type(configured_budget) is not int or configured_budget < 1:
            raise ValueError("AD-1323: configured_budget must be a positive int")
        text = (stop_text or "").strip()[:STOP_TEXT_MAX_CHARS]
        now = self._now()
        db = self._require_db()
        async with self._lock:
            try:
                cursor = await db.execute(
                    "INSERT OR IGNORE INTO continue_extension_permits "
                    "(request_id, agent_id, work_item_id, thread_id, state, cap_tokens, "
                    "created_at, stop_text, plan_mode, configured_budget) "
                    "VALUES (?, ?, ?, ?, 'requested', ?, ?, ?, ?, ?)",
                    (
                        request_id, agent_id, work_item_id, thread_id, cap_tokens, now,
                        text, 1 if plan_mode else 0, configured_budget,
                    ),
                )
                count = int(cursor.rowcount)
                await db.commit()
            except BaseException:
                try:
                    await db.execute("ROLLBACK")
                except Exception:  # noqa: BLE001
                    logger.debug("AD-1323: rollback found no open transaction")
                raise
        return count == 1

    async def reserve_filing(
        self,
        *,
        agent_id: str,
        work_item_id: str,
        thread_id: str,
        cap_tokens: int,
        stop_text: str,
        plan_mode: bool,
        configured_budget: int,
    ) -> str | None:
        """Record an UNBOUND ``requested`` permit for the item; ``None`` if it has any row.

        One conditional statement. The placeholder id is ``filing:<work_item_id>``
        until :meth:`bind` swaps in the filed request's id.
        """
        for label, value in (("agent_id", agent_id), ("work_item_id", work_item_id)):
            if type(value) is not str or not value:
                raise ValueError(f"AD-1323: {label} must be a non-empty string")
        if type(thread_id) is not str:
            raise ValueError("AD-1323: thread_id must be a string")
        if type(cap_tokens) is not int or cap_tokens < 0:
            raise ValueError("AD-1323: cap_tokens must be a non-negative int")
        if type(configured_budget) is not int or configured_budget < 1:
            raise ValueError("AD-1323: configured_budget must be a positive int")
        placeholder = FILING_PREFIX + work_item_id
        text = (stop_text or "").strip()[:STOP_TEXT_MAX_CHARS]
        count = await self._write(
            "INSERT OR IGNORE INTO continue_extension_permits "
            "(request_id, agent_id, work_item_id, thread_id, state, cap_tokens, created_at, "
            "stop_text, plan_mode, configured_budget, bound) "
            "SELECT ?, ?, ?, ?, 'requested', ?, ?, ?, ?, ?, 0 "
            "WHERE NOT EXISTS (SELECT 1 FROM continue_extension_permits WHERE work_item_id = ?)",
            (
                placeholder, agent_id, work_item_id, thread_id, cap_tokens, self._now(),
                text, 1 if plan_mode else 0, configured_budget, work_item_id,
            ),
        )
        return placeholder if count == 1 else None

    async def bind(self, work_item_id: str, request_id: str) -> bool:
        """Attach the filed request's id to the item's unbound permit, exactly once."""
        if type(request_id) is not str or not request_id:
            return False
        count = await self._write(
            "UPDATE continue_extension_permits SET request_id = ?, bound = 1 "
            "WHERE work_item_id = ? AND bound = 0 AND state = 'requested'",
            (request_id, work_item_id),
        )
        return count == 1

    async def get_for_request(
        self, request_id: str, work_item_id: str | None,
    ) -> ContinueExtensionPermit | None:
        """The permit row for ``request_id``, else the item's still-unbound row."""
        permit = await self.get(request_id)
        if permit is not None or not work_item_id:
            return permit
        db = self._require_db()
        async with db.execute(
            f"SELECT {_COLUMNS} FROM continue_extension_permits "
            "WHERE work_item_id = ? AND bound = 0 AND state = 'requested'",
            (work_item_id,),
        ) as cur:
            row = await cur.fetchone()
        return None if row is None else _row_to_permit(row)

    async def void_unbound(self, work_item_id: str) -> bool:
        """Void the item's unbound permit (filing failed or the process died mid-filing)."""
        count = await self._write(
            "UPDATE continue_extension_permits SET state = 'voided', voided_at = ? "
            "WHERE work_item_id = ? AND bound = 0 AND state = 'requested'",
            (self._now(), work_item_id),
        )
        return count == 1

    async def void_reservation(self, work_item_id: str, request_id: str = "") -> bool:
        """Void the item's still-``requested`` permit, unbound or bound to ``request_id``.

        One conditional statement, so it can never void an ``active``, ``consumed`` or
        already ``voided`` row: a cancelled filer does not revoke a Captain approval.
        ``False`` means nothing was voided (already settled), not an error.
        """
        if type(work_item_id) is not str or type(request_id) is not str or not work_item_id:
            return False
        count = await self._write(
            "UPDATE continue_extension_permits SET state = 'voided', voided_at = ? "
            "WHERE work_item_id = ? AND state = 'requested' AND (bound = 0 OR request_id = ?)",
            (self._now(), work_item_id, request_id),
        )
        return count == 1

    async def list_unbound(self) -> list[ContinueExtensionPermit]:
        """Every unbound ``requested`` permit, oldest first."""
        return await self._list("WHERE bound = 0 AND state = 'requested' ORDER BY created_at")

    async def list_requested(self) -> list[ContinueExtensionPermit]:
        """Every bound permit still ``requested``: its request awaits, or just got, a decision."""
        return await self._list("WHERE bound = 1 AND state = 'requested' ORDER BY created_at")

    async def has_work_item(self, work_item_id: str) -> bool:
        """Whether any permit, in any state, exists for ``work_item_id``."""
        db = self._require_db()
        async with db.execute(
            "SELECT 1 FROM continue_extension_permits WHERE work_item_id = ?",
            (work_item_id,),
        ) as cur:
            return await cur.fetchone() is not None


class _RecoveryPermits:
    """AD-1323 crash-recovery phase of the store: the first-model-call mark and the one reclaim.

    Runs against the host store's ``_write``, ``_now``, ``_list`` and ``get``.
    """

    async def begin_pass(self, request_id: str) -> bool:
        """Mark a consumed permit's pass as about to call the model; once only."""
        count = await self._write(
            "UPDATE continue_extension_permits SET started_at = ? "
            "WHERE request_id = ? AND state = 'consumed' AND started_at IS NULL",
            (self._now(), request_id),
        )
        return count == 1

    async def reclaim_unstarted(self, request_id: str) -> ContinueExtensionPermit | None:
        """Return a consumed, never-started, unexpired permit to ``active``, once per row."""
        now = self._now()
        count = await self._write(
            "UPDATE continue_extension_permits SET state = 'active', consumed_at = NULL, "
            "reclaims = reclaims + 1 "
            "WHERE request_id = ? AND state = 'consumed' AND started_at IS NULL "
            "AND reclaims < 1 AND expires_at > ?",
            (request_id, now),
        )
        if count != 1:
            return None
        return await self.get(request_id)

    async def list_consumed_unstarted(self) -> list[ContinueExtensionPermit]:
        """Every consumed permit whose pass never reached its first model call."""
        return await self._list(
            "WHERE state = 'consumed' AND started_at IS NULL ORDER BY consumed_at"
        )


class SqliteContinueExtensionPermitStore(_FilingPermits, _RecoveryPermits):
    """SQLite-backed permit store; see the module docstring for the guarantees.

    Public API:
        start() / stop()
        reserve(...) -> bool                       bound permit; one per work item, ever
        reserve_filing(...) -> str | None          unbound permit before the request is filed
        bind(work_item_id, request_id) -> bool     unbound -> bound, exactly once
        get_for_request(request_id, work_item_id)  by id, else the item's unbound row
        void_unbound(work_item_id) / list_unbound()
        begin_pass(request_id) -> bool             consumed, about to call the model
        reclaim_unstarted(request_id)              consumed, never started: once
        list_consumed_unstarted() / list_requested()
        has_work_item(work_item_id) -> bool
        activate(request_id, *, decided_by) -> ContinueExtensionPermit | None
        consume(request_id, *, agent_id, work_item_id, thread_id) -> permit | None
        void(request_id) -> bool
        void_expired() -> int
        get(request_id) / list_active()
    """

    def __init__(
        self,
        db_path: str,
        connection_factory: ConnectionFactory | None = None,
        clock: Callable[[], float] = time.time,
        ttl_seconds: int = 3600,
    ) -> None:
        self._db_path = db_path
        self._db: Any = None
        self._clock = clock
        self._ttl = max(60, min(86400, int(ttl_seconds)))
        self._lock = asyncio.Lock()
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            self._connection_factory = default_factory

    async def start(self) -> None:
        """Open the database, apply the schema and the idempotent snapshot migration."""
        self._db = await self._connection_factory.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(_SCHEMA)
        existing: set[str] = set()
        async with self._db.execute("PRAGMA table_info(continue_extension_permits)") as cur:
            async for row in cur:
                existing.add(row[1])
        for name, kind in _SNAPSHOT_COLUMNS:
            if name not in existing:
                await self._db.execute(
                    f"ALTER TABLE continue_extension_permits ADD COLUMN {name} {kind}"
                )
        await self._db.commit()
        logger.info("AD-1323: continue extension permit store started (db=%s)", self._db_path)

    async def stop(self) -> None:
        """Close the database; later calls fail closed."""
        db, self._db = self._db, None
        if db is not None:
            await db.close()

    def _now(self) -> float:
        now = self._clock()
        if type(now) not in (int, float) or not math.isfinite(now):
            raise RuntimeError("AD-1323: the permit store clock is not a finite real")
        return float(now)

    def _require_db(self) -> Any:
        if self._db is None:
            raise RuntimeError("AD-1323: the continue extension permit store is not running")
        return self._db

    async def _write(self, sql: str, params: tuple[Any, ...]) -> int:
        """One conditional statement, committed; the rowcount is the verdict."""
        db = self._require_db()
        async with self._lock:
            try:
                cursor = await db.execute(sql, params)
                count = int(cursor.rowcount)
                await db.commit()
            except BaseException:
                try:
                    await db.execute("ROLLBACK")
                except Exception:  # noqa: BLE001 -- no open transaction is the common case
                    logger.debug("AD-1323: rollback found no open transaction")
                raise
        return count

    async def _list(self, tail: str) -> list[ContinueExtensionPermit]:
        db = self._require_db()
        out: list[ContinueExtensionPermit] = []
        async with db.execute(
            f"SELECT {_COLUMNS} FROM continue_extension_permits {tail}"
        ) as cur:
            async for row in cur:
                out.append(_row_to_permit(row))
        return out

    async def activate(
        self, request_id: str, *, decided_by: str,
    ) -> ContinueExtensionPermit | None:
        """``requested`` -> ``active`` by somebody other than the asking agent.

        Returns the permit when it is active afterwards (including a replayed
        approval of an already-active one), else ``None``: unknown, spent,
        voided, blank approver, or the agent approving its own ask.
        """
        if type(decided_by) is not str or not decided_by.strip():
            return None
        now = self._now()
        count = await self._write(
            "UPDATE continue_extension_permits SET state = 'active', decided_by = ?, "
            "activated_at = ?, expires_at = ? "
            "WHERE request_id = ? AND state = 'requested' AND bound = 1 AND agent_id <> ? "
            "AND length(?) > 0",
            (decided_by, now, now + self._ttl, request_id, decided_by, decided_by),
        )
        permit = await self.get(request_id)
        if count == 1:
            return permit
        if permit is not None and permit.state == STATE_ACTIVE and permit.decided_by == decided_by:
            return permit
        return None

    async def consume(
        self, request_id: str, *, agent_id: str, work_item_id: str, thread_id: str,
    ) -> ContinueExtensionPermit | None:
        """Spend an active, unexpired permit exactly once; ``None`` for everyone else."""
        now = self._now()
        count = await self._write(
            "UPDATE continue_extension_permits SET state = 'consumed', consumed_at = ? "
            "WHERE request_id = ? AND agent_id = ? AND work_item_id = ? AND thread_id = ? "
            "AND state = 'active' AND expires_at > ?",
            (now, request_id, agent_id, work_item_id, thread_id, now),
        )
        if count != 1:
            return None
        return await self.get(request_id)

    async def void(self, request_id: str) -> bool:
        """Void a ``requested`` or ``active`` permit; a spent one stays spent."""
        count = await self._write(
            "UPDATE continue_extension_permits SET state = 'voided', voided_at = ? "
            "WHERE request_id = ? AND state IN ('requested', 'active')",
            (self._now(), request_id),
        )
        return count == 1

    async def void_expired(self) -> int:
        """Void every active permit whose approval has lapsed."""
        now = self._now()
        return await self._write(
            "UPDATE continue_extension_permits SET state = 'voided', voided_at = ? "
            "WHERE state = 'active' AND expires_at <= ?",
            (now, now),
        )

    async def get(self, request_id: str) -> ContinueExtensionPermit | None:
        db = self._require_db()
        async with db.execute(
            f"SELECT {_COLUMNS} FROM continue_extension_permits WHERE request_id = ?",
            (request_id,),
        ) as cur:
            row = await cur.fetchone()
        return None if row is None else _row_to_permit(row)

    async def list_active(self) -> list[ContinueExtensionPermit]:
        """Every ``active`` permit, oldest first."""
        db = self._require_db()
        out: list[ContinueExtensionPermit] = []
        async with db.execute(
            f"SELECT {_COLUMNS} FROM continue_extension_permits "
            "WHERE state = 'active' ORDER BY activated_at",
        ) as cur:
            async for row in cur:
                out.append(_row_to_permit(row))
        return out
