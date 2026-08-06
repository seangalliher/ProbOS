"""AD-906: Agent skill-request model + Captain approval queue.

Crew agents (or the Counselor / a Department Chief on their behalf) can file a
request to acquire a cognitive skill. Each request flows through a small state
machine — ``requested -> approved | denied -> in_training -> completed`` — with
the Captain owning the approve/deny decision. Approved requests are linked to a
holodeck team simulation (AD-907 completion-side wiring), and a request advances
to ``completed`` once that simulation finishes.

SQLite-backed with an in-memory cache, following the ConnectionFactory pattern
for cloud-ready storage (structurally mirrors ``CapabilityRequestStore``, AD-853).
Emits lifecycle events via ``EventEmitterMixin`` and, on decision, records a
trust outcome for the requesting agent when a trust network is wired.

This module is deliberately separable from the clinical-confidential counselor
surfaces (#866/867/868): it touches no clinical notes store and no disclosure
gate. The entire cluster is gated dark behind ``config.skill_requests.enabled``
(Pydantic default ``False``).
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Callable, Literal

from probos.events import EventType
from probos.protocols import EventEmitterMixin

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory, TrustNetworkProtocol

logger = logging.getLogger(__name__)

_RATIONALE_MAX = 280

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_requests (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    skill_label TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'self',
    justification TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'requested',
    linked_simulation_id TEXT,
    created_at REAL NOT NULL,
    decided_at REAL,
    decided_by TEXT NOT NULL DEFAULT '',
    decision_reason TEXT NOT NULL DEFAULT '',
    pre_metric REAL,
    post_metric REAL
);
CREATE INDEX IF NOT EXISTS idx_skillrequests_status ON skill_requests(status);
CREATE INDEX IF NOT EXISTS idx_skillrequests_agent ON skill_requests(agent_id);
"""

SkillRequestStatus = Literal[
    "requested", "approved", "denied", "in_training", "completed"
]
SkillRequestSource = Literal["self", "counselor", "chief"]


@dataclass
class SkillRequest:
    """A single skill-acquisition need filed by (or for) a crew agent."""

    id: str = ""
    agent_id: str = ""
    skill_id: str = ""
    skill_label: str = ""
    source: SkillRequestSource = "self"
    justification: str = ""
    status: SkillRequestStatus = "requested"
    linked_simulation_id: str | None = None
    created_at: float = 0.0
    decided_at: float | None = None
    decided_by: str = ""
    decision_reason: str = ""
    pre_metric: float | None = None
    post_metric: float | None = None


class SkillRequestStore(EventEmitterMixin):
    """Captain approval queue for crew skill-acquisition requests.

    - file_request() inserts a requested request, caches it, emits FILED
    - decide() approves/denies, records a trust outcome, emits DECIDED
    - begin_training() links an approved request to a simulation, emits
      TRAINING_STARTED
    - complete_for_simulation() advances the linked in-training request to
      completed once its simulation finishes, emits COMPLETED
    - list_pending() / list_by_agent() / get() are async cache reads (zero
      I/O after start)
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
        # In-memory cache: request_id -> SkillRequest
        self._cache: dict[str, SkillRequest] = {}

    async def start(self) -> None:
        if self.db_path:
            self._db = await self._connection_factory.connect(self.db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            await self._refresh_cache()
            logger.info("SkillRequestStore started (db=%s)", self.db_path)

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
            "SELECT id, agent_id, skill_id, skill_label, source, justification, "
            "status, linked_simulation_id, created_at, decided_at, decided_by, "
            "decision_reason, pre_metric, post_metric "
            "FROM skill_requests"
        ) as cursor:
            async for row in cursor:
                req = self._row_to_request(row)
                self._cache[req.id] = req

    async def file_request(
        self,
        agent_id: str,
        skill_id: str,
        *,
        skill_label: str = "",
        source: SkillRequestSource = "self",
        justification: str = "",
    ) -> SkillRequest:
        """File a new skill request. Writes DB + cache, emits FILED."""
        req = SkillRequest(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            skill_id=skill_id,
            skill_label=skill_label,
            source=source,
            justification=(justification or "")[:_RATIONALE_MAX],
            status="requested",
            created_at=time.time(),
        )
        if self._db:
            await self._db.execute(
                "INSERT INTO skill_requests "
                "(id, agent_id, skill_id, skill_label, source, justification, "
                "status, linked_simulation_id, created_at, decided_at, "
                "decided_by, decision_reason, pre_metric, post_metric) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, '', '', NULL, NULL)",
                (req.id, req.agent_id, req.skill_id, req.skill_label, req.source,
                 req.justification, req.status, req.created_at),
            )
            await self._db.commit()
        self._cache[req.id] = req
        self._emit(EventType.SKILL_REQUEST_FILED, {
            "id": req.id,
            "agent_id": req.agent_id,
            "skill_id": req.skill_id,
            "skill_label": req.skill_label,
            "source": req.source,
        })
        logger.info(
            "AD-906: Skill request filed — %s wants skill '%s' (source=%s, id=%s)",
            agent_id[:12], skill_id, source, req.id[:12],
        )
        return req

    async def decide(
        self,
        request_id: str,
        approve: bool,
        reason: str = "",
        decided_by: str = "captain",
    ) -> SkillRequest | None:
        """Approve or deny a request. Updates DB + cache, records trust, emits DECIDED.

        Returns the updated request, or None if the id is unknown.

        BF-722: the decision is built as a NEW object, committed, and only then
        published into the cache. :meth:`get` hands out the cached instance
        itself, so mutating it before the write made the in-memory queue report
        a decision the durable row had not taken; a failed lock or commit left
        the request out of ``list_pending()`` while the row stayed ``requested``,
        resurrected on the next restart. The exception propagates untouched —
        the caller decides how to degrade — and the cache still holds the
        undecided original. Trust and DECIDED follow the commit for the same
        reason: a decision that did not persist must not move trust.
        """
        req = await self.get(request_id)
        if req is None:
            logger.warning(
                "AD-906: decide() called for unknown skill request %s; ignoring",
                request_id[:12],
            )
            return None
        updated = replace(
            req,
            status="approved" if approve else "denied",
            decided_at=time.time(),
            decided_by=decided_by,
            decision_reason=reason,
        )
        if self._db:
            await self._db.execute(
                "UPDATE skill_requests SET status = ?, decided_at = ?, "
                "decided_by = ?, decision_reason = ? WHERE id = ?",
                (updated.status, updated.decided_at, updated.decided_by,
                 updated.decision_reason, updated.id),
            )
            await self._db.commit()
        self._cache[updated.id] = updated
        if self._trust_network is not None:
            try:
                self._trust_network.record_outcome(
                    updated.agent_id,
                    approve,
                    weight=1.0,
                    intent_type="skill_request",
                    source="skill_request",
                )
            except Exception as e:  # noqa: BLE001 — trust update is non-critical
                logger.warning(
                    "AD-906: trust outcome failed for %s on skill request %s: %s; "
                    "decision still recorded",
                    updated.agent_id[:12], updated.id[:12], e,
                )
        self._emit(EventType.SKILL_REQUEST_DECIDED, {
            "id": updated.id,
            "agent_id": updated.agent_id,
            "skill_id": updated.skill_id,
            "status": updated.status,
            "decided_by": updated.decided_by,
            "decision_reason": updated.decision_reason,
        })
        logger.info(
            "AD-906: Skill request %s — %s (by=%s)",
            updated.id[:12], updated.status, decided_by,
        )
        return updated

    async def begin_training(
        self,
        request_id: str,
        simulation_id: str,
    ) -> SkillRequest | None:
        """Link an approved request to a simulation and advance to in_training.

        Updates DB + cache and emits TRAINING_STARTED. Returns the updated
        request, or None if the id is unknown. The pending/approved-state guard
        is owned by the router (mirrors AD-857), so a caller is responsible for
        only invoking this on an approved request.
        """
        req = await self.get(request_id)
        if req is None:
            logger.warning(
                "AD-907: begin_training() called for unknown skill request %s; "
                "ignoring",
                request_id[:12],
            )
            return None
        req.status = "in_training"
        req.linked_simulation_id = simulation_id
        if self._db:
            await self._db.execute(
                "UPDATE skill_requests SET status = ?, linked_simulation_id = ? "
                "WHERE id = ?",
                (req.status, req.linked_simulation_id, req.id),
            )
            await self._db.commit()
        self._cache[req.id] = req
        self._emit(EventType.SKILL_REQUEST_TRAINING_STARTED, {
            "id": req.id,
            "agent_id": req.agent_id,
            "skill_id": req.skill_id,
            "linked_simulation_id": req.linked_simulation_id,
        })
        logger.info(
            "AD-907: Skill request %s — training started (simulation=%s)",
            req.id[:12], str(simulation_id)[:12],
        )
        return req

    async def complete_for_simulation(
        self,
        simulation_id: str,
        *,
        score: float | None = None,
    ) -> SkillRequest | None:
        """Advance the in-training request linked to a finished simulation.

        Finds the ``in_training`` request whose ``linked_simulation_id`` matches
        ``simulation_id``, sets it ``completed`` with ``post_metric`` and emits
        COMPLETED. Returns the updated request, or None when no in-training
        request is linked to that simulation (a benign no-op).
        """
        target: SkillRequest | None = None
        for r in self._cache.values():
            if r.status == "in_training" and r.linked_simulation_id == simulation_id:
                target = r
                break
        if target is None:
            logger.info(
                "AD-907: no in-training skill request linked to simulation %s; "
                "completion is a no-op",
                str(simulation_id)[:12],
            )
            return None
        target.status = "completed"
        if score is not None:
            target.post_metric = float(score)
        if self._db:
            await self._db.execute(
                "UPDATE skill_requests SET status = ?, post_metric = ? WHERE id = ?",
                (target.status, target.post_metric, target.id),
            )
            await self._db.commit()
        self._cache[target.id] = target
        self._emit(EventType.SKILL_REQUEST_COMPLETED, {
            "id": target.id,
            "agent_id": target.agent_id,
            "skill_id": target.skill_id,
            "linked_simulation_id": target.linked_simulation_id,
            "post_metric": target.post_metric,
        })
        logger.info(
            "AD-907: Skill request %s — completed (simulation=%s, score=%s)",
            target.id[:12], str(simulation_id)[:12], target.post_metric,
        )
        return target

    async def list_pending(self) -> list[SkillRequest]:
        """Return all requests still awaiting a decision (status=requested)."""
        return [r for r in self._cache.values() if r.status == "requested"]

    async def list_by_agent(self, agent_id: str) -> list[SkillRequest]:
        """Return all requests filed for a given agent, regardless of status."""
        return [r for r in self._cache.values() if r.agent_id == agent_id]

    async def get(self, request_id: str) -> SkillRequest | None:
        """Return a request by id, or None if unknown."""
        return self._cache.get(request_id)

    @staticmethod
    def _row_to_request(row: tuple) -> SkillRequest:
        return SkillRequest(
            id=row[0],
            agent_id=row[1],
            skill_id=row[2],
            skill_label=row[3],
            source=row[4],
            justification=row[5],
            status=row[6],
            linked_simulation_id=row[7],
            created_at=row[8],
            decided_at=row[9],
            decided_by=row[10],
            decision_reason=row[11],
            pre_metric=row[12],
            post_metric=row[13],
        )
