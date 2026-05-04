"""AD-539d v1: Fleet-Level Gap Aggregation (Local-Ship).

Aggregates GapReport instances into a snapshot. v1 ships LOCAL-SHIP
aggregation only — "fleet" = current ship's gaps. Cross-ship federated
aggregation is deferred to AD-539d-i (depends on AD-479 federation).

Privacy: snapshot payload contains COUNTS only — no agent_ids, no
descriptions, no per-gap detail.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FleetGapSnapshot:
    """v1 local-ship snapshot. AD-539d."""

    snapshot_at: float  # UTC timestamp
    total_gaps: int
    by_gap_type: dict[str, int]  # {"knowledge": N, "capability": N, "data": N}
    by_priority: dict[str, int]  # {"low": N, ..., "critical": N}
    by_department: dict[str, int]  # department → gap count (best-effort via agent ontology lookup)
    top_intents: tuple[tuple[str, int], ...]  # top 5 most-affected intents (intent → gap count)


class FleetGapAggregator:
    """v1 local-ship aggregator. AD-539d.

    Fleet = current ship in v1. Cross-ship federation deferred to AD-539d-i.
    """

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self.emit_event: Callable[..., None] | None = None

    def take_snapshot(self, gap_reports: Iterable[Any]) -> FleetGapSnapshot:
        """Aggregate gap reports into a fleet snapshot.

        Args:
            gap_reports: Iterable of GapReport instances (typically from a recent
                dream cycle's detect_gaps output, OR a persisted set).

        Returns:
            FleetGapSnapshot (frozen dataclass).

        Side effects:
            - Emits FLEET_GAP_SNAPSHOT_TAKEN with snapshot summary (counts only).
        """
        # Materialize once — iterators get consumed by multiple counters.
        reports = list(gap_reports)
        total = len(reports)

        by_gap_type = self._count_by_field(reports, "gap_type")
        by_priority = self._count_by_field(reports, "priority")

        by_department: dict[str, int] = {}
        for r in reports:
            agent_type = getattr(r, "agent_type", "") or ""
            dept = self._resolve_department(agent_type)
            if dept:
                by_department[dept] = by_department.get(dept, 0) + 1

        top = self._top_intents(reports, n=5)

        snapshot = FleetGapSnapshot(
            snapshot_at=time.time(),
            total_gaps=total,
            by_gap_type=by_gap_type,
            by_priority=by_priority,
            by_department=by_department,
            top_intents=top,
        )

        if self.emit_event is not None:
            try:
                # Privacy: counts only. No agent_ids, no descriptions.
                self.emit_event(
                    EventType.FLEET_GAP_SNAPSHOT_TAKEN,
                    {
                        "total_gaps": snapshot.total_gaps,
                        "by_gap_type": dict(snapshot.by_gap_type),
                        "by_priority": dict(snapshot.by_priority),
                        "by_department": dict(snapshot.by_department),
                        "top_intents": [list(pair) for pair in snapshot.top_intents],
                    },
                )
            except Exception:
                logger.warning(
                    "AD-539d: emit_event failed for fleet gap snapshot (total=%d); snapshot returned to caller, downstream listeners skipped",
                    snapshot.total_gaps,
                )

        return snapshot

    def _count_by_field(
        self,
        reports: Iterable[Any],
        field_name: str,
    ) -> dict[str, int]:
        """Generic counter helper. Empty dict for empty input."""
        counter: Counter[str] = Counter()
        for r in reports:
            val = getattr(r, field_name, "") or ""
            if val:
                counter[str(val)] += 1
        return dict(counter)

    def _top_intents(
        self,
        reports: Iterable[Any],
        n: int = 5,
    ) -> tuple[tuple[str, int], ...]:
        """Aggregate intent counts across all reports' affected_intent_types."""
        counter: Counter[str] = Counter()
        for r in reports:
            intents = getattr(r, "affected_intent_types", None) or ()
            for intent in intents:
                if intent:
                    counter[str(intent)] += 1
        return tuple(counter.most_common(n))

    def _resolve_department(self, agent_type: str) -> str:
        """Best-effort department lookup via runtime.ontology.

        Calls `runtime.ontology.get_agent_department(agent_type)` — the live
        ontology API takes `agent_type`, NOT `agent_id` (verified at
        proactive.py:2380, dreaming.py:1098, cognitive_agent.py:985).
        `GapReport.agent_type` (gap_predictor.py:194) is the natural caller
        — `take_snapshot` reads `report.agent_type` directly when bucketing
        by department.

        Unwraps the returned department: returns `dept.department_id` when
        the attribute is present, else `str(dept)` (idiom from
        dreaming.py:1099). Returns empty string when ontology absent,
        `agent_type` not in roster, or any lookup exception.
        """
        if not agent_type:
            return ""
        ontology = getattr(self._runtime, "ontology", None)
        if ontology is None:
            return ""
        try:
            dept = ontology.get_agent_department(agent_type)
        except Exception:
            return ""
        if not dept:
            return ""
        if hasattr(dept, "department_id"):
            return str(dept.department_id)
        return str(dept)
