"""AD-1159: WorkPermitStore — a durable, session-scoped authority to act on a workstation.

A **work permit** is the naval Permit to Work (PTW) applied to a crew session: one
agent, authorized by a *different* agent, to act on one workstation, up to a
bounded hazard tier, until an explicit expiry. It is a structured record rather
than a boolean, and it is *closed* rather than merely allowed to lapse — closure
is where an outcome is recorded.

**Nothing consumes this store in this AD.** AD-1154 set the precedent and it is
repeated here because it is the single most likely thing to be "improved" away:
shipping a gate together with the actions it gates means the gate's first
exercise is in production. AD-1160 wires it; until then the store is constructed
by tests only.

**Why a fifth store and not a widened existing one.** All four siblings were
checked against this requirement and none can express it:

* ``ToolPermissionStore`` (AD-423b) keys on ``(agent_id, tool_id, permission)``
  and ``IntentGrantStore`` (AD-1005) on ``(agent_id, intent_name)``. Both are
  **capability** grants — *may this agent hold this tool* — with no session, no
  workstation, and no notion of exclusive occupancy.
* ``ActionApprovalStore`` (AD-1154) keys on ``(agent_id, tool_id, action,
  scope_key)``. That is an **action** grant — *may this agent perform this shape
  of act* — and it is deliberately additive: two approvals for the same shape
  coexist harmlessly. A permit is an **occupancy** grant — *this agent, and no
  other, holds this space right now* — so the defining property is mutual
  exclusion, which no additive store can provide without changing the meaning of
  every existing row.

So: a new store, mirroring ``ActionApprovalStore`` structurally —
``ConnectionFactory`` injection, WAL, ``busy_timeout=5000``,
``synchronous=NORMAL``, an in-memory cache for zero-I/O sync reads, and lazy
expiry on read rather than a reaper. That makes this the fifth instance of ONE
pattern rather than a fifth pattern.

Four properties are load-bearing:

1. **Single holder.** At most one open, unexpired permit per
   ``(session_id, workstation_id)``. A second :meth:`WorkPermitStore.issue_permit`
   for an occupied space raises :class:`PermitConflict` rather than silently
   superseding. A permit that vanishes because somebody else asked is precisely
   the failure PTW exists to prevent, so the conflict is loud.
2. **Issuing authority is not performing authority.** ``issued_by ==
   holder_id`` is rejected. The crew's standing orders already state this as
   prose (``surgeon.md``: "Every operation must have CMO authorization or Captain
   approval"; ``yeoman.md``: "you do not issue orders on your own authority");
   here it is enforced.
3. **``expires_at`` is ``NOT NULL`` in the schema**, not merely in the method
   signature, following AD-1154 verbatim: an authority with no TTL is a permanent
   privilege escalation nobody remembers granting. :meth:`WorkPermitStore.issue_permit`
   takes a required keyword-only ``ttl_seconds: float`` and there is deliberately
   no ``expires_at: float | None`` overload, so the invariant is carried by the
   type system as well as by the column. ``ttl_seconds`` must also be **finite
   and strictly positive**: a non-positive TTL yields a permit that is already
   expired when it is returned, which reads as a granted authority and grants
   nothing — the success-shaped no-op AD-1154 exists to eliminate — and ``inf``
   is the never-expiring authority this invariant forbids arriving through the
   one parameter that cannot express it.
4. **No wildcards on the authorization path.** ``session_id`` /
   ``workstation_id`` / ``holder_id`` match exactly; ``""`` matches only ``""``.
   AD-1154 rejected wildcard scope for the same reason — it reads as a
   convenience and behaves as "hold every workstation in every session".
   :meth:`WorkPermitStore.list_open_sync` is the one deliberate exception and is
   *not* an authorization predicate; see its docstring.

Expiry is enforced **on read**, not by a reaper: the sync readers filter on
``expires_at > self._clock()`` and drop lapsed rows from the cache on the way
past, and ``_load_cache`` filters the same way at start. This matches all four
existing stores. A row past its TTL is inert immediately; physical cleanup is a
later concern and is deliberately not built here.

The clock is injected (``clock: Callable[[], float] = time.time``), mirroring
``CrewSessionService.__init__``. Every timestamp this module reads — issue,
closure, and all four lazy-expiry sweeps — comes from that one callable, so a
test can advance time deterministically and exercise expiry the way expiry
actually happens, rather than by constructing a permit that was never live.

**Known bound, stated honestly.** The single-holder check reads the in-memory
cache, which is authoritative for one process after :meth:`WorkPermitStore.start`.
Two processes sharing one database file could both pass the check and both
insert; the schema does not carry a partial unique index because one would also
reject an *expired* open row and so contradict lazy expiry above. Every sibling
store shares this single-writer assumption. Multi-writer arbitration is not built
here.

Also deliberately not absorbed from PTW, named so they are not half-built:
watch-turnover revalidation, SIMOPS conflict reconciliation, suspension on
general alarm, and lockout/tagout multi-holder locks. Agent-to-agent transfer is
AD-1161; there is no ``transfer_permit`` in this AD.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

# The hazard ceiling vocabulary is READ from ``classify_action``
# (``probos.tools.browser.actions``), which returns int 1 | 2 | 3. It is
# restated as a literal rather than imported so this store carries no dependency
# on the browser package — a permit names a workstation, and ``browser`` is only
# the first of them. This AD does not alter ``classify_action``.
_VALID_TIERS: tuple[int, ...] = (1, 2, 3)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS work_permits (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    workstation_id TEXT NOT NULL,
    holder_id TEXT NOT NULL,
    issued_by TEXT NOT NULL,
    max_tier INTEGER NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    issued_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    closed INTEGER NOT NULL DEFAULT 0,
    closed_at REAL,
    close_reason TEXT NOT NULL DEFAULT '',
    closed_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_wp_lookup ON work_permits(session_id, workstation_id, closed);
CREATE INDEX IF NOT EXISTS idx_wp_active ON work_permits(closed, expires_at);
"""

_SELECT_COLUMNS = (
    "id, session_id, workstation_id, holder_id, issued_by, max_tier, reason, "
    "issued_at, expires_at, closed, closed_at, close_reason, closed_by"
)


class PermitConflict(Exception):
    """Raised when a space already has a live holder.

    Distinct from ``ValueError`` (which this module raises for a malformed
    request) because a conflict is a statement about the *world* — the
    workstation is occupied — not about the caller's arguments. A caller can
    retry a conflict after the incumbent permit is closed; it can never retry a
    ``ValueError`` without changing what it asked for.
    """


@dataclass
class WorkPermit:
    """A single-holder, expiring authority to act on one workstation."""

    id: str
    session_id: str
    workstation_id: str
    holder_id: str
    issued_by: str
    max_tier: int
    reason: str = ""
    issued_at: float = 0.0
    expires_at: float = 0.0
    closed: bool = False
    closed_at: float | None = None
    close_reason: str = ""
    closed_by: str = ""


class WorkPermitStore:
    """Persistent work-permit store, scoped to one workstation in one session.

    SQLite-backed with an in-memory cache of live permits, so the ``*_sync``
    readers do zero I/O and are safe on the dispatch path. Follows the
    ``ActionApprovalStore`` pattern.

    The cache holds only permits that are open and were unexpired at load time;
    closing removes a permit from it, and expired entries are dropped lazily by
    the first sync read that walks past them. Every ``*_sync`` reader therefore
    answers about *live* permits, and a closed or lapsed permit is indistinguishable
    from one that never existed — which is the correct answer for an authorization
    question and the reason the readers are not a general row-inspection API.

    Public API:
        start() / stop() — lifecycle
        issue_permit(...) → WorkPermit
        close_permit(permit_id, closed_by=..., close_reason=...) → bool
        revoke_permit(permit_id, revoked_by=...) → bool
        holder_sync(session_id, workstation_id) → str | None
        permitted_tier_sync(agent_id, session_id, workstation_id) → int
        get_sync(permit_id) → WorkPermit | None
        list_open_sync(session_id="") → list[WorkPermit]
    """

    def __init__(
        self,
        db_path: str = "",
        connection_factory: ConnectionFactory | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Construct the store.

        Args:
            db_path: SQLite path. Empty means cache-only (no persistence), which
                is the shape the sync readers are tested against directly.
            connection_factory: injected per the Cloud-Ready Storage rule; the
                default SQLite factory is imported lazily so the module carries
                no import-time dependency on a concrete backend.
            clock: the single source of "now" for this store — issue time,
                closure time, and all four lazy-expiry sweeps. Injected rather
                than read from ``time.time`` at each site so expiry is testable
                deterministically; mirrors ``CrewSessionService.__init__``.
        """
        self._db_path = db_path
        self._db: Any = None
        self._cache: list[WorkPermit] = []
        self._clock = clock
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            self._connection_factory = default_factory

    async def start(self) -> None:
        """Open the database, apply the schema, and load live permits into cache."""
        if self._db_path:
            self._db = await self._connection_factory.connect(self._db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            await self._load_cache()
            logger.info(
                "AD-1159: WorkPermitStore started (db=%s, live permits=%d)",
                self._db_path,
                len(self._cache),
            )

    async def stop(self) -> None:
        """Close the database handle. The cache is left intact for inspection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def _load_cache(self) -> None:
        self._cache.clear()
        if not self._db:
            return
        now = self._clock()
        async with self._db.execute(
            f"SELECT {_SELECT_COLUMNS} FROM work_permits "
            "WHERE closed = 0 AND expires_at > ?",
            (now,),
        ) as cur:
            async for row in cur:
                self._cache.append(self._row_to_permit(row))

    def _row_to_permit(self, row: Any) -> WorkPermit:
        return WorkPermit(
            id=row[0],
            session_id=row[1],
            workstation_id=row[2],
            holder_id=row[3],
            issued_by=row[4],
            max_tier=row[5],
            reason=row[6],
            issued_at=row[7],
            expires_at=row[8],
            closed=bool(row[9]),
            closed_at=row[10],
            close_reason=row[11],
            closed_by=row[12],
        )

    async def issue_permit(
        self,
        *,
        session_id: str,
        workstation_id: str,
        holder_id: str,
        issued_by: str,
        max_tier: int,
        ttl_seconds: float,
        reason: str = "",
    ) -> WorkPermit:
        """Issue a permit over one workstation, expiring ``ttl_seconds`` from now.

        Raises:
            ValueError: if ``max_tier`` is not one of 1, 2, 3 — including the
                ``bool`` case, because ``isinstance(True, int)`` is ``True`` in
                Python and ``max_tier=True`` would otherwise silently mean tier 1,
                an authorization created by a typo. Also raised when
                ``ttl_seconds`` is not a finite positive real (see below), and
                when ``issued_by == holder_id``: the officer who authorizes never
                performs, and self-issue removes the only check the permit adds.
            PermitConflict: if the space already has a live holder. The incumbent
                permit is left untouched; the caller must close it first.

        ``ttl_seconds`` must be **strictly positive and finite**. A zero or
        negative TTL would compute an ``expires_at`` that is already in the past,
        so the returned :class:`WorkPermit` would report a granted authority that
        every reader immediately treats as absent — a *success-shaped no-op*,
        which is the exact failure mode AD-1154 was written to eliminate. NaN is
        rejected for the same reason with an extra edge: ``float("nan") <= 0`` is
        ``False``, so a bare positivity test would let it through and every
        subsequent ``expires_at > now`` comparison would also be ``False``,
        producing an inert permit that no error ever explained. ``inf`` is
        rejected because it is the never-expiring authority the mandatory-expiry
        invariant exists to forbid, arriving through the one parameter that
        cannot express it.

        There is deliberately NO parameter that can produce a NULL ``expires_at``
        — ``ttl_seconds`` is required and keyword-only, and the column is
        ``NOT NULL``, so a never-expiring authority cannot be created through this
        API or written behind it.
        """
        if type(max_tier) is not int or max_tier not in _VALID_TIERS:
            logger.warning(
                "AD-1159: permit refused for %s on %s/%s — max_tier=%r is not one "
                "of %s (bool is rejected explicitly: max_tier=True would silently "
                "mean tier 1). No permit was issued and the space is unchanged.",
                holder_id[:12],
                session_id[:12],
                workstation_id,
                max_tier,
                _VALID_TIERS,
            )
            raise ValueError(
                f"max_tier must be one of {_VALID_TIERS} (int, not bool); got {max_tier!r}"
            )
        if (
            (type(ttl_seconds) is not int and type(ttl_seconds) is not float)
            or not math.isfinite(ttl_seconds)
            or ttl_seconds <= 0
        ):
            logger.warning(
                "AD-1159: permit refused for %s on %s/%s — ttl_seconds=%r is not a "
                "finite positive real (bool is rejected explicitly, as is NaN, "
                "which survives a bare positivity test). A permit issued with this "
                "TTL would expire at or before the moment it was returned, so it "
                "would read as a granted authority while granting nothing. No "
                "permit was issued and the space is unchanged.",
                holder_id[:12],
                session_id[:12],
                workstation_id,
                ttl_seconds,
            )
            raise ValueError(
                "ttl_seconds must be a finite positive real (int or float, not "
                f"bool); got {ttl_seconds!r}"
            )
        if issued_by == holder_id:
            logger.warning(
                "AD-1159: permit refused on %s/%s — issuing authority %s is also "
                "the performing authority. Self-issue removes the separation the "
                "permit exists to enforce. No permit was issued.",
                session_id[:12],
                workstation_id,
                holder_id[:12],
            )
            raise ValueError(
                "issued_by must differ from holder_id: the issuing authority "
                f"never performs the work (both were {holder_id!r})"
            )
        incumbent = self._live_permit_sync(session_id, workstation_id)
        if incumbent is not None:
            logger.warning(
                "AD-1159: permit refused for %s on %s/%s — the space is already "
                "held by %s until %.0f (permit %s). The incumbent permit is "
                "untouched; close it before reissuing.",
                holder_id[:12],
                session_id[:12],
                workstation_id,
                incumbent.holder_id[:12],
                incumbent.expires_at,
                incumbent.id[:12],
            )
            raise PermitConflict(
                f"workstation {workstation_id!r} in session {session_id!r} is "
                f"already held by {incumbent.holder_id!r} (permit {incumbent.id})"
            )
        now = self._clock()
        permit = WorkPermit(
            id=str(uuid.uuid4()),
            session_id=session_id,
            workstation_id=workstation_id,
            holder_id=holder_id,
            issued_by=issued_by,
            max_tier=max_tier,
            reason=reason,
            issued_at=now,
            expires_at=now + float(ttl_seconds),
        )
        if self._db:
            await self._db.execute(
                "INSERT INTO work_permits "
                "(id, session_id, workstation_id, holder_id, issued_by, max_tier, "
                "reason, issued_at, expires_at, closed, closed_at, close_reason, "
                "closed_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, '', '')",
                (
                    permit.id,
                    permit.session_id,
                    permit.workstation_id,
                    permit.holder_id,
                    permit.issued_by,
                    permit.max_tier,
                    permit.reason,
                    permit.issued_at,
                    permit.expires_at,
                ),
            )
            await self._db.commit()
        self._cache.append(permit)
        logger.info(
            "AD-1159: work permit issued by %s — %s holds %s in session %s to "
            "tier %d until %.0f (id=%s)",
            issued_by[:12],
            holder_id[:12],
            workstation_id,
            session_id[:12],
            max_tier,
            permit.expires_at,
            permit.id[:12],
        )
        return permit

    async def close_permit(
        self,
        permit_id: str,
        *,
        closed_by: str,
        close_reason: str = "",
    ) -> bool:
        """Close a permit, returning the space to normal. Closure is terminal.

        Returns ``True`` if this call closed an open permit, ``False`` if the
        permit is unknown or was already closed. Closing twice is not an error —
        a caller unwinding a failed hand-off should not have to distinguish
        "I closed it" from "it was already closed", and raising would turn
        idempotent cleanup into a second failure.

        An *expired* but still-open permit can be closed: expiry makes a permit
        inert, closure is what records an outcome against it, and losing that
        record because a TTL elapsed first would defeat the point.
        """
        now = self._clock()
        if self._db:
            result = await self._db.execute(
                "UPDATE work_permits SET closed = 1, closed_at = ?, "
                "close_reason = ?, closed_by = ? WHERE id = ? AND closed = 0",
                (now, close_reason, closed_by, permit_id),
            )
            await self._db.commit()
            if result.rowcount == 0:
                logger.debug(
                    "AD-1159: close_permit(%s) by %s was a no-op — the permit is "
                    "unknown or already closed. Closure is terminal, so the "
                    "caller may safely treat this as done.",
                    permit_id[:12],
                    closed_by[:12],
                )
                return False
        elif not any(p.id == permit_id for p in self._cache):
            return False
        self._cache = [p for p in self._cache if p.id != permit_id]
        logger.info(
            "AD-1159: work permit closed by %s (id=%s, reason=%r) — the "
            "workstation is free to be reissued.",
            closed_by[:12],
            permit_id[:12],
            close_reason,
        )
        return True

    async def revoke_permit(self, permit_id: str, *, revoked_by: str) -> bool:
        """Captain-side unconditional close, recorded with ``close_reason='revoked'``.

        A separate ``revoked`` column is deliberately not carried: revocation is
        a closure with a distinguishing reason, and a second boolean would create
        a fourth state (closed *and* revoked, or revoked *and not* closed) that
        no reader wants to interpret.
        """
        return await self.close_permit(
            permit_id, closed_by=revoked_by, close_reason="revoked"
        )

    def _live_permit_sync(
        self, session_id: str, workstation_id: str
    ) -> WorkPermit | None:
        """The single live permit for this space, else None. Zero I/O.

        Sweeps lapsed entries out of the cache on the way past — this is the
        whole of expiry enforcement, and the reason no reaper exists.
        """
        now = self._clock()
        expired_ids: list[str] = []
        found: WorkPermit | None = None
        for permit in self._cache:
            if permit.expires_at <= now:
                expired_ids.append(permit.id)
                continue
            if permit.closed:
                continue
            if (
                permit.session_id == session_id
                and permit.workstation_id == workstation_id
            ):
                found = permit
        if expired_ids:
            self._cache = [p for p in self._cache if p.id not in expired_ids]
        return found

    def holder_sync(self, session_id: str, workstation_id: str) -> str | None:
        """The agent id currently holding this workstation, else ``None``.

        Exact match on both fields — ``""`` matches only ``""``. Zero I/O;
        expired permits answer as ``None`` and are dropped on the way past.
        """
        permit = self._live_permit_sync(session_id, workstation_id)
        return permit.holder_id if permit is not None else None

    def permitted_tier_sync(
        self, agent_id: str, session_id: str, workstation_id: str
    ) -> int:
        """The hazard ceiling this agent may act up to here; ``0`` means no permit.

        Agent-scoped: an agent that is not the holder gets ``0`` even when the
        space has a live permit, because a permit authorizes *its holder* and a
        bystander reading a non-zero tier is exactly the confusion single-holder
        occupancy exists to remove.

        Zero I/O — this is the dispatch-path read.
        """
        permit = self._live_permit_sync(session_id, workstation_id)
        if permit is None or permit.holder_id != agent_id:
            return 0
        return permit.max_tier

    def get_sync(self, permit_id: str) -> WorkPermit | None:
        """The live permit with this id, else ``None``. Zero I/O.

        Closed and expired permits answer ``None``: the cache is a cache of live
        authority, not a row-inspection API. The rows are retained in SQLite for
        audit and are reachable there.
        """
        now = self._clock()
        expired_ids: list[str] = []
        found: WorkPermit | None = None
        for permit in self._cache:
            if permit.expires_at <= now:
                expired_ids.append(permit.id)
                continue
            if permit.id == permit_id and not permit.closed:
                found = permit
        if expired_ids:
            self._cache = [p for p in self._cache if p.id not in expired_ids]
        return found

    def list_open_sync(self, session_id: str = "") -> list[WorkPermit]:
        """Live permits, optionally narrowed to one session. Zero I/O.

        ``session_id=""`` means **unfiltered** — every live permit across every
        session. This is the one place ``""`` is not an exact match, and it is
        not a violation of the no-wildcard rule above: that rule governs the
        *authorization* predicates (:meth:`holder_sync`, :meth:`permitted_tier_sync`),
        where a wildcard would grant something. This method grants nothing; it
        enumerates. Reading it as an exact match would also make listing every
        open permit impossible, since a permit whose ``session_id`` is genuinely
        ``""`` is a degenerate row rather than a useful query.
        """
        now = self._clock()
        expired_ids: list[str] = []
        rows: list[WorkPermit] = []
        for permit in self._cache:
            if permit.expires_at <= now:
                expired_ids.append(permit.id)
                continue
            if permit.closed:
                continue
            if session_id and permit.session_id != session_id:
                continue
            rows.append(permit)
        if expired_ids:
            self._cache = [p for p in self._cache if p.id not in expired_ids]
        return rows
