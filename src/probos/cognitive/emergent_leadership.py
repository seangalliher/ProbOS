"""AD-439: Emergent Leadership Detection.

Read-only analytics that compares the designed chain of command (ontology)
with the emergent influence graph (Hebbian weights). Surfaces divergences
where an agent's strongest peer-influence target is NOT its designated
superior. Captain-facing diagnostic; no mutations.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.mesh.routing import HebbianRouter
    from probos.ontology.service import VesselOntologyService
    from probos.substrate.registry import AgentRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LeadershipDivergence:
    """One subordinate-vs-superior mismatch."""

    agent_id: str
    agent_type: str
    designed_superior_post: str
    emergent_target_id: str
    emergent_weight: float
    designed_weight: float
    detected_at: float


@dataclass(frozen=True)
class LeadershipReport:
    """Full divergence snapshot."""

    generated_at: float
    divergences: list[LeadershipDivergence]
    sample_size: int
    skipped: int


class EmergentLeadershipDetector:
    """Compare designed authority_over hierarchy against Hebbian influence.

    Read-only on shared state. Each ``analyze()`` call produces a fresh
    ``LeadershipReport``. Caller is responsible for scheduling.
    """

    def __init__(
        self,
        *,
        ontology: "VesselOntologyService",
        hebbian: "HebbianRouter",
        registry: "AgentRegistry",
        emit_event: Any | None = None,
        min_weight: float = 0.10,
        min_ratio: float = 1.5,
    ) -> None:
        self._ontology = ontology
        self._hebbian = hebbian
        self._registry = registry
        self._emit_event = emit_event
        self._min_weight = min_weight
        self._min_ratio = min_ratio

    def analyze(self) -> LeadershipReport:
        """Produce a divergence report. Does not mutate any source."""
        agents = list(self._registry.all())
        divergences: list[LeadershipDivergence] = []
        skipped = 0
        sample = 0
        now = time.time()

        for agent in agents:
            if not getattr(agent, "is_alive", True):
                skipped += 1
                continue
            agent_type = getattr(agent, "agent_type", "")
            agent_id = getattr(agent, "id", "")
            if not agent_type or not agent_id:
                skipped += 1
                continue

            assignment = self._ontology.get_assignment_for_agent(agent_type)
            if assignment is None:
                skipped += 1
                continue
            post = self._ontology.get_post(assignment.post_id)
            if post is None or not post.reports_to:
                skipped += 1
                continue

            weights = self._hebbian.get_agent_weights(agent_id)
            if not weights:
                skipped += 1
                continue

            target_id, target_weight = max(weights.items(), key=lambda kv: kv[1])
            if target_weight < self._min_weight:
                skipped += 1
                continue

            superior_assignments = self._superior_agent_ids(post.reports_to)
            designed_weight = max(
                (weights.get(sid, 0.0) for sid in superior_assignments),
                default=0.0,
            )

            if target_id in superior_assignments:
                sample += 1
                continue

            if designed_weight > 0 and target_weight < designed_weight * self._min_ratio:
                sample += 1
                continue

            divergences.append(LeadershipDivergence(
                agent_id=agent_id,
                agent_type=agent_type,
                designed_superior_post=post.reports_to,
                emergent_target_id=target_id,
                emergent_weight=target_weight,
                designed_weight=designed_weight,
                detected_at=now,
            ))
            sample += 1

            if self._emit_event:
                try:
                    self._emit_event(
                        EventType.LEADERSHIP_DIVERGENCE,
                        {
                            "agent_id": agent_id,
                            "agent_type": agent_type,
                            "designed_superior_post": post.reports_to,
                            "emergent_target_id": target_id,
                            "emergent_weight": target_weight,
                            "designed_weight": designed_weight,
                        },
                    )
                except Exception:
                    logger.warning(
                        "AD-439: emit failed for %s; divergence still recorded",
                        agent_id,
                        exc_info=True,
                    )

        report = LeadershipReport(
            generated_at=now,
            divergences=divergences,
            sample_size=sample,
            skipped=skipped,
        )
        if divergences:
            logger.info(
                "AD-439: %d leadership divergences in %d sampled agents",
                len(divergences), sample,
            )
        return report

    def _superior_agent_ids(self, superior_post_id: str) -> set[str]:
        """All agent_ids currently filling the superior post."""
        try:
            assignments = self._ontology.get_agents_for_post(superior_post_id)
        except Exception:
            return set()
        result: set[str] = set()
        for a in assignments:
            sup_agent_type = a.agent_type
            for agent in self._registry.all():
                if getattr(agent, "agent_type", "") == sup_agent_type:
                    result.add(getattr(agent, "id", ""))
        return result - {""}
