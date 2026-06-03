"""AD-853: Unified capability-request model + single approval queue.

The crew self-unblock loop produces three kinds of capability needs —
clearance grants, dependency installs, and agent builds. Before AD-853 each
flowed through a separate ad-hoc path. This module unifies them behind one
``CapabilityRequest`` record and one ``CapabilityRequestStore`` approval queue,
so the Captain reviews a single pending list regardless of request kind.

SQLite-backed with an in-memory cache, following the ConnectionFactory pattern
for cloud-ready storage (mirrors ``ClearanceGrantStore``). Emits lifecycle
events via ``EventEmitterMixin`` and, on decision, records a trust outcome for
the requesting agent when a trust network is wired.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal

from probos.events import EventType
from probos.protocols import EventEmitterMixin

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory, TrustNetworkProtocol

logger = logging.getLogger(__name__)

_RATIONALE_MAX = 280

_SCHEMA = """
CREATE TABLE IF NOT EXISTS capability_requests (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    work_item_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    decided_at REAL,
    decided_by TEXT NOT NULL DEFAULT '',
    decision_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_caprequests_status ON capability_requests(status);
CREATE INDEX IF NOT EXISTS idx_caprequests_agent ON capability_requests(agent_id);
"""

RequestKind = Literal["grant", "install", "build"]
RequestStatus = Literal["pending", "approved", "denied", "fulfilled", "failed"]


@dataclass
class CapabilityRequest:
    """A single capability need filed by a crew agent for Captain review."""

    id: str = ""
    agent_id: str = ""
    kind: RequestKind = "grant"
    target: str = ""
    rationale: str = ""
    work_item_id: str | None = None
    status: RequestStatus = "pending"
    created_at: float = 0.0
    decided_at: float | None = None
    decided_by: str = ""
    decision_reason: str = ""


class CapabilityRequestStore(EventEmitterMixin):
    """Single approval queue for clearance/install/build capability requests.

    - file_request() inserts a pending request, caches it, emits FILED
    - decide() approves/denies, records a trust outcome, emits DECIDED
    - list_pending() / get() are async cache reads (zero I/O after start)
    - start() loads all requests into cache; stop() closes the DB
    """

    def __init__(
        self,
        db_path: str = "",
        connection_factory: "ConnectionFactory | None" = None,
        emit_event: Callable[..., Any] | None = None,
        trust_network: "TrustNetworkProtocol | None" = None,
    ) -> None:
        self.db_path = db_path
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory
        self._emit_event = emit_event
        self._trust_network = trust_network
        self._db: Any = None
        # In-memory cache: request_id -> CapabilityRequest
        self._cache: dict[str, CapabilityRequest] = {}

    async def start(self) -> None:
        if self.db_path:
            self._db = await self._connection_factory.connect(self.db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            await self._refresh_cache()
            logger.info("CapabilityRequestStore started (db=%s)", self.db_path)

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _refresh_cache(self) -> None:
        """Load all requests into the in-memory cache."""
        self._cache.clear()
        if not self._db:
            return
        async with self._db.execute(
            "SELECT id, agent_id, kind, target, rationale, work_item_id, "
            "status, created_at, decided_at, decided_by, decision_reason "
            "FROM capability_requests"
        ) as cursor:
            async for row in cursor:
                req = self._row_to_request(row)
                self._cache[req.id] = req

    async def file_request(
        self,
        agent_id: str,
        kind: RequestKind,
        target: str,
        rationale: str = "",
        work_item_id: str | None = None,
    ) -> CapabilityRequest:
        """File a new pending capability request. Writes DB + cache, emits FILED."""
        req = CapabilityRequest(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            kind=kind,
            target=target,
            rationale=(rationale or "")[:_RATIONALE_MAX],
            work_item_id=work_item_id,
            status="pending",
            created_at=time.time(),
        )
        if self._db:
            await self._db.execute(
                "INSERT INTO capability_requests "
                "(id, agent_id, kind, target, rationale, work_item_id, "
                "status, created_at, decided_at, decided_by, decision_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, '', '')",
                (req.id, req.agent_id, req.kind, req.target, req.rationale,
                 req.work_item_id, req.status, req.created_at),
            )
            await self._db.commit()
        self._cache[req.id] = req
        self._emit(EventType.CAPABILITY_REQUEST_FILED, {
            "id": req.id,
            "agent_id": req.agent_id,
            "kind": req.kind,
            "target": req.target,
            "work_item_id": req.work_item_id,
        })
        logger.info(
            "AD-853: Capability request filed — %s wants %s '%s' (id=%s)",
            agent_id[:12], kind, target, req.id[:12],
        )
        return req

    async def decide(
        self,
        request_id: str,
        approve: bool,
        reason: str = "",
        decided_by: str = "captain",
    ) -> CapabilityRequest | None:
        """Approve or deny a request. Updates DB + cache, records trust, emits DECIDED.

        Returns the updated request, or None if the id is unknown.
        """
        req = await self.get(request_id)
        if req is None:
            logger.warning(
                "AD-853: decide() called for unknown request %s; ignoring",
                request_id[:12],
            )
            return None
        req.status = "approved" if approve else "denied"
        req.decided_at = time.time()
        req.decided_by = decided_by
        req.decision_reason = reason
        if self._db:
            await self._db.execute(
                "UPDATE capability_requests SET status = ?, decided_at = ?, "
                "decided_by = ?, decision_reason = ? WHERE id = ?",
                (req.status, req.decided_at, req.decided_by,
                 req.decision_reason, req.id),
            )
            await self._db.commit()
        self._cache[req.id] = req
        if self._trust_network is not None:
            try:
                self._trust_network.record_outcome(
                    req.agent_id,
                    approve,
                    weight=1.0,
                    intent_type="capability_request",
                    source="capability_request",
                )
            except Exception as e:  # noqa: BLE001 — trust update is non-critical
                logger.warning(
                    "AD-853: trust outcome failed for %s on request %s: %s; "
                    "decision still recorded",
                    req.agent_id[:12], req.id[:12], e,
                )
        self._emit(EventType.CAPABILITY_REQUEST_DECIDED, {
            "id": req.id,
            "agent_id": req.agent_id,
            "kind": req.kind,
            "status": req.status,
            "decided_by": req.decided_by,
            "decision_reason": req.decision_reason,
        })
        logger.info(
            "AD-853: Capability request %s — %s (by=%s)",
            req.id[:12], req.status, decided_by,
        )
        return req

    async def mark_fulfilled(self, request_id: str) -> CapabilityRequest | None:
        """Mark a request fulfilled once its rung's fulfiller has completed.

        Updates DB + cache and emits FULFILLED. Returns the updated request, or
        None if the id is unknown.
        """
        req = await self.get(request_id)
        if req is None:
            logger.warning(
                "AD-854: mark_fulfilled() called for unknown request %s; ignoring",
                request_id[:12],
            )
            return None
        req.status = "fulfilled"
        if self._db:
            await self._db.execute(
                "UPDATE capability_requests SET status = ? WHERE id = ?",
                (req.status, req.id),
            )
            await self._db.commit()
        self._cache[req.id] = req
        self._emit(EventType.CAPABILITY_REQUEST_FULFILLED, {
            "id": req.id,
            "agent_id": req.agent_id,
            "kind": req.kind,
            "status": req.status,
        })
        logger.info(
            "AD-854: Capability request %s — fulfilled",
            req.id[:12],
        )
        return req

    async def list_pending(self) -> list[CapabilityRequest]:
        """Return all requests still awaiting a decision."""
        return [r for r in self._cache.values() if r.status == "pending"]

    async def get(self, request_id: str) -> CapabilityRequest | None:
        """Return a request by id, or None if unknown."""
        return self._cache.get(request_id)

    @staticmethod
    def _row_to_request(row: tuple) -> CapabilityRequest:
        return CapabilityRequest(
            id=row[0],
            agent_id=row[1],
            kind=row[2],
            target=row[3],
            rationale=row[4],
            work_item_id=row[5],
            status=row[6],
            created_at=row[7],
            decided_at=row[8],
            decided_by=row[9],
            decision_reason=row[10],
        )
