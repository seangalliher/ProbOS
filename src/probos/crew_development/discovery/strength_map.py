"""StrengthMap — per-agent record of discovery-scenario outcomes (AD-512b v1).

Future consumers (AD-486 Holodeck post-scenario hook, AD-487 Personal
Ontology Prober) read this map to enrich self-knowledge. v1 is
observational — :meth:`record_outcome` updates the map and emits an
event; the caller separately decides whether to write a Hebbian edge
(see :func:`cross_functional.suggest_routing`) or store an episode (see
:meth:`to_episode_payload`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StrengthRecord:
    """One scenario outcome recorded against an agent. AD-512b v1."""

    agent_id: str
    scenario_id: str
    capability_category: str
    success: bool
    confidence_self_report: float  # 0.0–1.0; agent's own confidence at attempt
    timestamp: float
    notes: str = ""


@dataclass
class _AgentStrengthAggregate:
    """Per-agent rolling aggregate. Internal."""

    agent_id: str
    successes_by_category: dict[str, int] = field(default_factory=dict)
    failures_by_category: dict[str, int] = field(default_factory=dict)
    last_outcome_at: float = 0.0

    def total_attempts(self, category: str) -> int:
        return (
            self.successes_by_category.get(category, 0)
            + self.failures_by_category.get(category, 0)
        )

    def success_rate(self, category: str) -> float:
        n = self.total_attempts(category)
        if n == 0:
            return 0.0
        return self.successes_by_category.get(category, 0) / n


class StrengthMap:
    """In-memory per-agent strength map. AD-512b v1.

    Public API:
        record_outcome(record) -> None
        records_for(agent_id) -> tuple[StrengthRecord, ...]
        get_strengths(agent_id, *, min_attempts=2, threshold=0.70) -> tuple[str, ...]
        get_struggles(agent_id, *, min_attempts=2, threshold=0.40) -> tuple[str, ...]
        success_rate(agent_id, category) -> float
        total_attempts(agent_id, category) -> int
        to_episode_payload(record) -> dict[str, Any]
    """

    def __init__(self) -> None:
        self._records: list[StrengthRecord] = []
        self._aggregates: dict[str, _AgentStrengthAggregate] = {}
        self.emit_event: Callable[..., None] | None = None

    def record_outcome(self, record: StrengthRecord) -> None:
        """Append a record and update the per-agent aggregate."""
        self._records.append(record)
        agg = self._aggregates.get(record.agent_id)
        if agg is None:
            agg = _AgentStrengthAggregate(agent_id=record.agent_id)
            self._aggregates[record.agent_id] = agg
        bucket = agg.successes_by_category if record.success else agg.failures_by_category
        bucket[record.capability_category] = bucket.get(record.capability_category, 0) + 1
        agg.last_outcome_at = record.timestamp
        self._emit_outcome(record)
        self._emit_map_updated(record.agent_id, record.capability_category)

    def records_for(self, agent_id: str) -> tuple[StrengthRecord, ...]:
        return tuple(r for r in self._records if r.agent_id == agent_id)

    def success_rate(self, agent_id: str, capability_category: str) -> float:
        agg = self._aggregates.get(agent_id)
        if agg is None:
            return 0.0
        return agg.success_rate(capability_category)

    def total_attempts(self, agent_id: str, capability_category: str) -> int:
        agg = self._aggregates.get(agent_id)
        if agg is None:
            return 0
        return agg.total_attempts(capability_category)

    def get_strengths(
        self,
        agent_id: str,
        *,
        min_attempts: int = 2,
        threshold: float = 0.70,
    ) -> tuple[str, ...]:
        """Return capability categories where success_rate >= threshold."""
        agg = self._aggregates.get(agent_id)
        if agg is None:
            return ()
        out: list[str] = []
        all_categories = set(agg.successes_by_category) | set(agg.failures_by_category)
        for cat in sorted(all_categories):
            if agg.total_attempts(cat) >= min_attempts and agg.success_rate(cat) >= threshold:
                out.append(cat)
        return tuple(out)

    def get_struggles(
        self,
        agent_id: str,
        *,
        min_attempts: int = 2,
        threshold: float = 0.40,
    ) -> tuple[str, ...]:
        """Return capability categories where success_rate < threshold."""
        agg = self._aggregates.get(agent_id)
        if agg is None:
            return ()
        out: list[str] = []
        all_categories = set(agg.successes_by_category) | set(agg.failures_by_category)
        for cat in sorted(all_categories):
            if agg.total_attempts(cat) >= min_attempts and agg.success_rate(cat) < threshold:
                out.append(cat)
        return tuple(out)

    @staticmethod
    def to_episode_payload(record: StrengthRecord) -> dict[str, Any]:
        """Build an Episode-shaped dict for caller-driven encoding.

        v1 does NOT call EpisodicMemory.store; the caller (AD-486 Holodeck
        wave) constructs an Episode from this dict and stores it.
        Discovery episodes are high-importance per AD-512 design (importance=8).
        """
        return {
            "user_input": f"discovery:{record.scenario_id}",
            "outcomes": [{
                "scenario_id": record.scenario_id,
                "capability_category": record.capability_category,
                "success": record.success,
                "self_confidence": record.confidence_self_report,
                "notes": record.notes,
            }],
            "agent_ids": [record.agent_id],
            "timestamp": record.timestamp,
            "importance": 8,
            "source": "discovery_learning",
        }

    def _emit_outcome(self, record: StrengthRecord) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.DISCOVERY_OUTCOME_RECORDED,
                {
                    "agent_id": record.agent_id,
                    "scenario_id": record.scenario_id,
                    "capability_category": record.capability_category,
                    "success": record.success,
                },
            )
        except Exception:
            logger.warning(
                "AD-512b: emit_event failed for outcome agent_id=%s; continuing",
                record.agent_id,
                exc_info=True,
            )

    def _emit_map_updated(self, agent_id: str, capability_category: str) -> None:
        if self.emit_event is None:
            return
        try:
            agg = self._aggregates[agent_id]
            self.emit_event(
                EventType.STRENGTH_MAP_UPDATED,
                {
                    "agent_id": agent_id,
                    "capability_category": capability_category,
                    "success_rate": agg.success_rate(capability_category),
                    "total_attempts": agg.total_attempts(capability_category),
                    "last_outcome_at": agg.last_outcome_at,
                },
            )
        except Exception:
            logger.warning(
                "AD-512b: map_updated emit failed for agent_id=%s; continuing",
                agent_id,
                exc_info=True,
            )
