"""AD-635 / AD-635b / AD-635c — Clinical Telemetry Query Facade.

Clearance-gated read-only query service enabling Medical (Chapel,
chief_medical/FULL) and Counselor (Echo, counselor/ORACLE) to perform
cross-agent clinical diagnostics over substrate telemetry.

v3 surfaces THREE data domains:
  - Dream cycle history (via EmergentDetector.recent_dreams; AD-635 v1)
  - Cross-agent cognitive journal chain traces (via CognitiveJournal.get_recent_chain_traces; AD-635 v1)
  - Cognitive circuit breaker state + zone transition history (via CircuitBreakerHistoryStore; AD-635c)

REST endpoints, shell command, and proactive injection are deferred to AD-635d/e/f.

AD-635b adds optional SQLite write-through persistence of the audit ring
via ``ClinicalAuditStore``. AD-635c adds optional SQLite write-through
persistence of cognitive-circuit-breaker transitions via
``CircuitBreakerHistoryStore`` plus the clearance-gated
``query_circuit_breaker_history`` reader. Both are default-off; opt-in
via ``audit_persistence_enabled`` and
``circuit_breaker_history_persistence_enabled`` respectively.

Authorization model (AD-620/622): caller must hold a clearance tier of FULL
or ORACLE (resolved via effective_recall_tier from rank + billet + active
grants) AND have a clinical agent_type. Denied queries return [] and log
a warning — they never raise. Every query is logged to a bounded in-memory
audit ring (and durably to SQLite when persistence is enabled).
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from typing import TYPE_CHECKING, Any

from probos.earned_agency import (
    RecallTier,
    effective_recall_tier,
    resolve_active_grants,
    resolve_billet_clearance,
)

if TYPE_CHECKING:
    # AD-635b / AD-635c: forward-refs to avoid runtime import cycles
    # with the persistence modules (defense in depth — current shapes
    # have no cycle).
    from probos.cognitive.clinical_audit_store import ClinicalAuditStore
    from probos.cognitive.circuit_breaker_history_store import (
        CircuitBreakerHistoryStore,
    )

logger = logging.getLogger(__name__)


# Clinical agent_types authorized (in addition to clearance gate).
CLINICAL_ROLES: frozenset[str] = frozenset({"diagnostician", "counselor"})

# Tier floor — caller must hold FULL or ORACLE.
QUALIFYING_TIERS: frozenset[RecallTier] = frozenset(
    {RecallTier.FULL, RecallTier.ORACLE}
)


class ClinicalTelemetryService:
    """AD-635 v1: Read-only clearance-gated cross-agent clinical query facade."""

    def __init__(
        self,
        runtime: Any,
        *,
        audit_max_entries: int = 1000,
        audit_store: "ClinicalAuditStore | None" = None,
        circuit_breaker_history_store: "CircuitBreakerHistoryStore | None" = None,
    ) -> None:
        self._runtime = runtime
        self._audit: collections.deque[dict[str, Any]] = collections.deque(
            maxlen=max(1, int(audit_max_entries))
        )
        # AD-635b: optional SQLite write-through. None preserves AD-635 v1
        # in-memory-only behavior bit-for-bit. Tasks are tracked per the
        # Standing Order on async hygiene (fire-and-forget references held).
        self._audit_store = audit_store
        self._write_tasks: set[asyncio.Task[None]] = set()
        # AD-635c: optional CircuitBreakerHistoryStore handle for the
        # query_circuit_breaker_history reader. None disables the third
        # data domain (returns [] like the other domains do when their
        # underlying store is unavailable).
        self._circuit_breaker_history_store = circuit_breaker_history_store

    # ---- Public API ------------------------------------------------------

    async def query_dream_history(
        self,
        *,
        requester_agent_id: str,
        limit: int = 20,
        captain_override: bool = False,
    ) -> list[dict[str, Any]]:
        """Return up to `limit` recent dream reports, most recent first.

        Returns [] (not raises) if requester lacks clearance or if the
        EmergentDetector is unavailable. Every call is logged to the audit ring.

        AD-635e: when `captain_override=True`, the clearance gate is bypassed
        and the audit-ring entry is stamped `by_captain=True`. This kwarg is
        kwarg-only and not exposed via the AD-635d REST router (callers there
        cannot reach it). Used only by the in-process `/clinical` shell command.
        """
        if captain_override:
            granted = True
        else:
            granted = self._authorize_clinical_query(requester_agent_id)
        if not granted:
            self._record_audit(
                requester_agent_id, "dream_history", granted=False, result_count=0
            )
            logger.warning(
                "AD-635: dream_history denied for %s (clearance/role gate)",
                requester_agent_id,
            )
            return []

        detector = getattr(self._runtime, "_emergent_detector", None)
        if detector is None or not hasattr(detector, "recent_dreams"):
            self._record_audit(
                requester_agent_id, "dream_history", granted=True, result_count=0
            )
            return []

        try:
            rows = detector.recent_dreams(limit=max(0, int(limit)))
        except Exception:
            logger.warning(
                "AD-635: dream_history accessor failed for %s", requester_agent_id,
                exc_info=True,
            )
            self._record_audit(
                requester_agent_id, "dream_history", granted=True, result_count=0
            )
            return []

        self._record_audit(
            requester_agent_id, "dream_history", granted=True,
            result_count=len(rows), by_captain=captain_override,
        )
        return rows

    async def query_agent_chain_traces(
        self,
        *,
        requester_agent_id: str,
        target_agent_id: str,
        limit: int = 20,
        captain_override: bool = False,
    ) -> list[dict[str, Any]]:
        """Return up to `limit` recent chain traces for `target_agent_id`.

        Returns [] (not raises) if requester lacks clearance, if the journal
        is unavailable, or on any underlying failure.

        AD-635e: when `captain_override=True`, the clearance gate is bypassed
        and the audit-ring entry is stamped `by_captain=True` (see
        `query_dream_history` for the policy rationale).
        """
        if captain_override:
            granted = True
        else:
            granted = self._authorize_clinical_query(requester_agent_id)
        if not granted:
            self._record_audit(
                requester_agent_id,
                "chain_traces",
                granted=False,
                result_count=0,
                target_agent_id=target_agent_id,
            )
            logger.warning(
                "AD-635: chain_traces denied for %s (clearance/role gate)",
                requester_agent_id,
            )
            return []

        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is None or not hasattr(journal, "get_recent_chain_traces"):
            self._record_audit(
                requester_agent_id,
                "chain_traces",
                granted=True,
                result_count=0,
                target_agent_id=target_agent_id,
            )
            return []

        try:
            rows = await journal.get_recent_chain_traces(
                limit=max(0, int(limit)),
                agent_id=target_agent_id,
            )
        except Exception:
            logger.warning(
                "AD-635: chain_traces query failed for %s -> %s",
                requester_agent_id, target_agent_id,
                exc_info=True,
            )
            self._record_audit(
                requester_agent_id,
                "chain_traces",
                granted=True,
                result_count=0,
                target_agent_id=target_agent_id,
            )
            return []

        self._record_audit(
            requester_agent_id,
            "chain_traces",
            granted=True,
            result_count=len(rows),
            target_agent_id=target_agent_id,
            by_captain=captain_override,
        )
        return rows

    @property
    def audit_log(self) -> list[dict[str, Any]]:
        """Snapshot of the audit ring (most recent last). Returns a copy."""
        return list(self._audit)

    async def query_circuit_breaker_history(
        self,
        *,
        requester_agent_id: str,
        target_agent_id: str | None = None,
        limit: int = 50,
        captain_override: bool = False,
    ) -> list[dict[str, Any]]:
        """AD-635c: Return up to `limit` recent breaker transitions.

        When `target_agent_id` is provided, filters to that agent.
        When None, returns transitions across all agents (most recent
        first). Returns [] (not raises) if requester lacks clearance,
        if the store is unavailable, or on any underlying failure.
        Every call is logged to the audit ring.

        AD-635e: when `captain_override=True`, the clearance gate is bypassed
        and the audit-ring entry is stamped `by_captain=True`.
        """
        if captain_override:
            granted = True
        else:
            granted = self._authorize_clinical_query(requester_agent_id)
        if not granted:
            self._record_audit(
                requester_agent_id,
                "circuit_breaker_history",
                granted=False,
                result_count=0,
                target_agent_id=target_agent_id,
            )
            logger.warning(
                "AD-635c: circuit_breaker_history denied for %s "
                "(clearance/role gate)",
                requester_agent_id,
            )
            return []

        store = self._circuit_breaker_history_store
        if store is None:
            self._record_audit(
                requester_agent_id,
                "circuit_breaker_history",
                granted=True,
                result_count=0,
                target_agent_id=target_agent_id,
            )
            return []

        try:
            rows = await store.recent(
                max(0, int(limit)),
                agent_id=target_agent_id,
            )
        except Exception:
            logger.warning(
                "AD-635c: circuit_breaker_history query failed for %s -> %s",
                requester_agent_id, target_agent_id,
                exc_info=True,
            )
            self._record_audit(
                requester_agent_id,
                "circuit_breaker_history",
                granted=True,
                result_count=0,
                target_agent_id=target_agent_id,
            )
            return []

        self._record_audit(
            requester_agent_id,
            "circuit_breaker_history",
            granted=True,
            result_count=len(rows),
            target_agent_id=target_agent_id,
            by_captain=captain_override,
        )
        return rows

    # ---- Internals -------------------------------------------------------

    def _authorize_clinical_query(self, agent_id: str) -> bool:
        """Resolve effective clearance tier + clinical role for `agent_id`."""
        agent_type = self._resolve_agent_type(agent_id)
        if not agent_type or agent_type not in CLINICAL_ROLES:
            return False

        billet_clearance = ""
        ontology = getattr(self._runtime, "ontology", None)
        try:
            billet_clearance = resolve_billet_clearance(agent_type, ontology)
        except Exception:
            logger.debug("AD-635: billet clearance lookup failed", exc_info=True)

        grants: list[Any] = []
        try:
            grants = resolve_active_grants(
                agent_id,
                getattr(self._runtime, "clearance_grant_store", None),
            )
        except Exception:
            logger.debug("AD-635: grant lookup failed", exc_info=True)

        rank = self._resolve_rank(agent_id)

        try:
            tier = effective_recall_tier(rank, billet_clearance, grants)
        except Exception:
            logger.debug("AD-635: tier resolution failed", exc_info=True)
            return False

        return tier in QUALIFYING_TIERS

    def _resolve_agent_type(self, agent_id: str) -> str:
        registry = getattr(self._runtime, "registry", None)
        if registry is None:
            return ""
        try:
            agent = registry.get(agent_id)
        except Exception:
            return ""
        if agent is None:
            return ""
        return getattr(agent, "agent_type", "") or ""

    def _resolve_rank(self, agent_id: str) -> Any:
        acm = getattr(self._runtime, "acm", None)
        if acm is None:
            return None
        try:
            profile = acm.get(agent_id)
        except Exception:
            return None
        if profile is None:
            return None
        return getattr(profile, "rank", None)

    def _record_audit(
        self,
        requester_agent_id: str,
        query_type: str,
        *,
        granted: bool,
        result_count: int,
        target_agent_id: str | None = None,
        by_captain: bool = False,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": time.time(),
            "requester_agent_id": requester_agent_id,
            "query_type": query_type,
            "granted": bool(granted),
            "result_count": int(result_count),
        }
        if target_agent_id is not None:
            entry["target_agent_id"] = target_agent_id
        if by_captain:
            entry["by_captain"] = True
        # In-memory ring append happens FIRST. A write-through-side failure
        # MUST NOT prevent the in-memory record (DLog #11). Tier-2 log-and-
        # degrade applies to the persistence side, not the ring.
        self._audit.append(entry)
        if self._audit_store is not None:
            self._schedule_write_through(entry)

    def _schedule_write_through(self, entry: dict[str, Any]) -> None:
        """AD-635b: fire-and-forget SQLite persistence task."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug(
                "AD-635b: no running event loop; audit write-through skipped",
            )
            return
        task = loop.create_task(self._write_through(entry))
        self._write_tasks.add(task)
        task.add_done_callback(self._write_tasks.discard)

    async def _write_through(self, entry: dict[str, Any]) -> None:
        """AD-635b: persist one audit entry; tier-2 log-and-degrade on failure."""
        try:
            await self._audit_store.append(entry)
        except Exception:
            logger.warning(
                "AD-635b: audit write-through failed for %s/%s",
                entry.get("requester_agent_id"),
                entry.get("query_type"),
                exc_info=True,
            )
