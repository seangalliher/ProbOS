"""AD-864: Capability × trust × department → agent_id resolution for crew sub-tasks.

AD-863 annotated each plan-derived :class:`WorkItemSpec` with two optional hints:
a one-phrase ``capability`` ("kind of work") and an optional ``department``.
:class:`CrewAssignmentResolver` is the **pure decision** that turns those hints
into a concrete worker ``agent_id`` using the live registry, the capability
registry, the vessel ontology (for the department lookup), and the trust
network (so a capable-but-untrusted agent loses to a capable-and-proven one).

It is the resolution sibling of dispatch: no LLM, no side effects, no
``WorkItem`` mutation. When nothing qualifies, the result honest-degrades to
``agent_id=None`` with a logged reason — the executor (AD-867) fails that child
explicitly rather than silently mis-routing it. ``resolve`` never raises: any
unexpected collaborator error is Tier-2 log-and-degraded to the unresolved
decision, because the caller sits on the dispatch path.

Chain-of-command delegation (AD-865) and runtime wiring (AD-867) are out of
scope — this AD resolves straight to the worker.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from probos.consultation.dispatch import WorkItemSpec

if TYPE_CHECKING:
    from probos.consensus.trust import TrustNetwork
    from probos.mesh.capability import CapabilityMatch, CapabilityRegistry
    from probos.ontology import VesselOntologyService
    from probos.substrate.registry import AgentRegistry

logger = logging.getLogger(__name__)

# Resolution reason constants — why a spec resolved (or didn't).
_REASON_CAPABILITY = "capability_match"
_REASON_CAPABILITY_DEPT_UNAVAILABLE = "capability_match_dept_unavailable"
_REASON_DEPARTMENT_ONLY = "department_only"
_REASON_UNRESOLVED = "unresolved_no_candidate"


@dataclass(frozen=True)
class AssignmentDecision:
    """The outcome of resolving one :class:`WorkItemSpec` to a worker.

    ``agent_id`` is the chosen worker, or ``None`` when nothing qualified
    (honest-degrade — the executor fails that child). ``department`` and
    ``capability`` echo the spec's hints. ``score`` is the chosen candidate's
    qualification strength (trust-weighted capability score for a capability
    match, trust score for a department-only pick) and is exactly ``0.0`` when
    unresolved. ``reason`` records which branch produced the decision.
    """

    spec_id: str
    agent_id: str | None
    department: str | None
    capability: str | None
    score: float
    reason: str


class CrewAssignmentResolver:
    """Map hint-annotated :class:`WorkItemSpec`s to concrete worker agent_ids.

    Pure decision: reads the live registry, capability registry, ontology, and
    trust network; writes nothing. Honest-degrades to ``agent_id=None`` instead
    of raising, since the caller is on the dispatch path.
    """

    def __init__(
        self,
        *,
        capability_registry: "CapabilityRegistry",
        ontology: "VesselOntologyService",
        trust_network: "TrustNetwork",
        agent_registry: "AgentRegistry",
    ) -> None:
        self._capability_registry = capability_registry
        self._ontology = ontology
        self._trust_network = trust_network
        self._agent_registry = agent_registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, spec: WorkItemSpec) -> AssignmentDecision:
        """Resolve a single spec to an :class:`AssignmentDecision`.

        Never raises: an unexpected collaborator error is logged and degraded
        to the unresolved decision so a malformed spec cannot crash dispatch.
        """
        capability = spec.capability
        department = spec.department
        try:
            all_scores = self._trust_network.all_scores()

            if capability:
                decision = self._resolve_by_capability(spec, capability, department, all_scores)
                if decision is not None:
                    return decision
            elif department:
                decision = self._resolve_by_department(spec, department)
                if decision is not None:
                    return decision
        except Exception:  # Tier-2 log-and-degrade: dispatch path must not crash.
            logger.warning(
                "Crew assignment failed for spec=%s (capability=%r department=%r); "
                "degrading to unresolved",
                spec.spec_id,
                capability,
                department,
                exc_info=True,
            )

        return self._unresolved(spec)

    def resolve_all(self, specs: list[WorkItemSpec]) -> list[AssignmentDecision]:
        """Resolve a list of specs, one :class:`AssignmentDecision` per spec."""
        return [self.resolve(s) for s in specs]

    # ------------------------------------------------------------------
    # Resolution branches
    # ------------------------------------------------------------------

    def _resolve_by_capability(
        self,
        spec: WorkItemSpec,
        capability: str,
        department: str | None,
        all_scores: dict[str, float],
    ) -> AssignmentDecision | None:
        """Capability hint set: query, filter to alive (and in-department), pick top."""
        matches = self._capability_registry.query(capability, trust_scores=all_scores)
        alive_matches = [m for m in matches if self._is_alive(m.agent_id)]
        if not alive_matches:
            return None

        if department:
            dept_matches = [
                m for m in alive_matches if self._department_of(m.agent_id) == department
            ]
            if dept_matches:
                return self._capability_decision(
                    spec, dept_matches[0], _REASON_CAPABILITY
                )
            # Department filter emptied the list — fall back to the alive
            # capability ranking and flag that the department was unavailable.
            return self._capability_decision(
                spec, alive_matches[0], _REASON_CAPABILITY_DEPT_UNAVAILABLE
            )

        return self._capability_decision(spec, alive_matches[0], _REASON_CAPABILITY)

    def _resolve_by_department(
        self, spec: WorkItemSpec, department: str
    ) -> AssignmentDecision | None:
        """No capability hint, department hint set: pick highest-trust alive in-dept agent."""
        candidates = [
            a for a in self._agent_registry.all() if self._department_of(a.id) == department
        ]
        if not candidates:
            return None

        # Deterministic tie-break: higher trust first, then agent_id lexical.
        best = min(
            candidates,
            key=lambda a: (-self._trust_network.get_score(a.id), a.id),
        )
        return AssignmentDecision(
            spec_id=spec.spec_id,
            agent_id=best.id,
            department=department,
            capability=spec.capability,
            score=self._trust_network.get_score(best.id),
            reason=_REASON_DEPARTMENT_ONLY,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _capability_decision(
        self, spec: WorkItemSpec, match: "CapabilityMatch", reason: str
    ) -> AssignmentDecision:
        return AssignmentDecision(
            spec_id=spec.spec_id,
            agent_id=match.agent_id,
            department=spec.department,
            capability=spec.capability,
            score=match.score,
            reason=reason,
        )

    def _unresolved(self, spec: WorkItemSpec) -> AssignmentDecision:
        return AssignmentDecision(
            spec_id=spec.spec_id,
            agent_id=None,
            department=spec.department,
            capability=spec.capability,
            score=0.0,
            reason=_REASON_UNRESOLVED,
        )

    def _is_alive(self, agent_id: str) -> bool:
        return self._agent_registry.get(agent_id) is not None

    def _department_of(self, agent_id: str) -> str | None:
        agent = self._agent_registry.get(agent_id)
        if agent is None:
            return None
        return self._ontology.get_agent_department(agent.agent_type)
