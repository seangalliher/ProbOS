"""AD-581a + AD-581d: Hybrid dispatch routing decision layer.

Pure decision module. Given a candidate pool and an intent (or an unassigned
WorkItem), decide whether to direct-assign to a single agent or to broadcast.
The decision is a function of:

* HebbianRouter weight from intent_type -> agent_id
* Department membership (resolved via VesselOntologyService)
* Configurable confidence_threshold + margin (AD-581d)
* Cold-start floor min_hebbian_weight (AD-581d)
* Per-(intent, agent_id) success-rate ring buffer (AD-581d, accessor-only)

This module DOES NOT dispatch. WorkItemRouter is the side-effect surface;
DepartmentDispatcher returns a RoutingDecision and never emits events,
talks to the bus, or constructs TaskEvents.

Out of scope:
- ASA / BookableResource routing (AD-581c, commercial)
- Project-team cross-department CoC (AD-581e, commercial)
- LLM-driven semantic routing (no LLM call here; pure structural)
- Dream-cycle auto-tuning of confidence_threshold (consumer hook only)
"""
from __future__ import annotations

import collections
import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from probos.mesh.routing import REL_INTENT

if TYPE_CHECKING:
    from probos.config import HybridDispatchConfig
    from probos.mesh.routing import HebbianRouter
    from probos.ontology.service import VesselOntologyService

logger = logging.getLogger(__name__)


class RoutingMode(str, Enum):
    DIRECT = "direct"
    BROADCAST = "broadcast"


@dataclass(frozen=True)
class RoutingDecision:
    """Pure-data result. WorkItemRouter (or any caller) acts on it."""

    mode: RoutingMode
    agent_id: str | None
    confidence: float
    runner_up_weight: float
    reason: str
    department_id: str | None

    def is_direct(self) -> bool:
        return self.mode == RoutingMode.DIRECT

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "agent_id": self.agent_id,
            "confidence": float(self.confidence),
            "runner_up_weight": float(self.runner_up_weight),
            "reason": self.reason,
            "department_id": self.department_id,
        }


class DepartmentDispatcher:
    """Hebbian + ontology routing decision layer.

    Construct via the ``_wire_hybrid_dispatch`` finalize wirer; tests
    construct directly with stub dependencies.
    """

    def __init__(
        self,
        *,
        hebbian_router: "HebbianRouter | None",
        ontology: "VesselOntologyService | None",
        config: "HybridDispatchConfig",
    ) -> None:
        self._hebbian = hebbian_router
        self._ontology = ontology
        self._config = config
        self._success_rings: dict[
            tuple[str, str], collections.deque[bool]
        ] = collections.defaultdict(
            lambda: collections.deque(maxlen=int(config.success_rate_window))
        )

    # ------------------------------------------------------------------
    # AD-581a: routing decision
    # ------------------------------------------------------------------
    def route(
        self,
        *,
        intent: str,
        candidates: list[str],
        work_item: Any | None = None,
    ) -> RoutingDecision:
        """Decide DIRECT vs BROADCAST.

        ``work_item`` is the optional WorkItem whose ``assigned_to`` may force
        a direct-assign hint. ``candidates`` is the pool of agent_ids the
        caller has already filtered (e.g. by capability or department).

        Returns ``RoutingDecision``. Pure -- no side effects.
        """
        if work_item is not None:
            assigned_hint = getattr(work_item, "assigned_to", None)
            if assigned_hint:
                department_id = self._department_for_agent(assigned_hint)
                return RoutingDecision(
                    mode=RoutingMode.DIRECT,
                    agent_id=assigned_hint,
                    confidence=1.0,
                    runner_up_weight=0.0,
                    reason="direct_assigned_hint",
                    department_id=department_id,
                )

        if not candidates:
            return RoutingDecision(
                mode=RoutingMode.BROADCAST,
                agent_id=None,
                confidence=0.0,
                runner_up_weight=0.0,
                reason="broadcast_no_candidates",
                department_id=None,
            )

        if self._hebbian is None:
            return RoutingDecision(
                mode=RoutingMode.BROADCAST,
                agent_id=None,
                confidence=0.0,
                runner_up_weight=0.0,
                reason="broadcast_no_router",
                department_id=None,
            )

        scored: list[tuple[str, float]] = []
        for agent_id in candidates:
            try:
                w = self._hebbian.get_weight(intent, agent_id, REL_INTENT)
            except Exception:
                logger.debug(
                    "AD-581a: get_weight failed for (%s, %s); treating as 0.0",
                    intent, agent_id, exc_info=True,
                )
                w = 0.0
            scored.append((agent_id, float(w)))

        scored.sort(key=lambda x: x[1], reverse=True)
        top_id, top_w = scored[0]
        runner_up_w = scored[1][1] if len(scored) > 1 else 0.0
        department_id = self._department_for_agent(top_id)

        if top_w < self._config.min_hebbian_weight:
            return RoutingDecision(
                mode=RoutingMode.BROADCAST,
                agent_id=None,
                confidence=top_w,
                runner_up_weight=runner_up_w,
                reason="broadcast_below_floor",
                department_id=department_id,
            )

        if top_w < self._config.confidence_threshold:
            return RoutingDecision(
                mode=RoutingMode.BROADCAST,
                agent_id=None,
                confidence=top_w,
                runner_up_weight=runner_up_w,
                reason="broadcast_below_threshold",
                department_id=department_id,
            )

        if (top_w - runner_up_w) < self._config.confidence_margin:
            return RoutingDecision(
                mode=RoutingMode.BROADCAST,
                agent_id=None,
                confidence=top_w,
                runner_up_weight=runner_up_w,
                reason="broadcast_no_margin",
                department_id=department_id,
            )

        return RoutingDecision(
            mode=RoutingMode.DIRECT,
            agent_id=top_id,
            confidence=top_w,
            runner_up_weight=runner_up_w,
            reason="direct_high_confidence",
            department_id=department_id,
        )

    # ------------------------------------------------------------------
    # AD-581d: per-(intent, agent_id) success-rate accessor surface
    # ------------------------------------------------------------------
    def record_outcome(
        self, *, intent: str, agent_id: str, success: bool,
    ) -> None:
        """Append an outcome to the rolling window for (intent, agent_id)."""
        self._success_rings[(intent, agent_id)].append(bool(success))

    def get_success_rate(
        self, *, intent: str, agent_id: str,
    ) -> tuple[float, int]:
        """Return ``(success_rate, sample_count)``.

        ``success_rate`` is 0.0 when sample_count < min_samples_for_routing
        (configured floor). This lets the dream-cycle subscriber distinguish
        "low confidence" from "no data" without a separate flag.
        """
        ring = self._success_rings.get((intent, agent_id))
        if ring is None:
            return 0.0, 0
        n = len(ring)
        if n < self._config.min_samples_for_routing:
            return 0.0, n
        successes = sum(1 for s in ring if s)
        return successes / n, n

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _department_for_agent(self, agent_id: str) -> str | None:
        """Resolve agent_id -> department_id via ontology.

        agent_id often equals agent_type in this codebase (registry IDs are
        usually the agent_type string). When ontology is unavailable, returns
        None gracefully -- the resolution is informational, not gating.
        """
        if self._ontology is None:
            return None
        try:
            return self._ontology.get_agent_department(agent_id)
        except Exception:
            logger.debug(
                "AD-581a: get_agent_department failed for %s",
                agent_id, exc_info=True,
            )
            return None
