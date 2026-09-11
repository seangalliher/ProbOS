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
from typing import TYPE_CHECKING, Literal, Protocol

from probos.cognitive.agentic_dispatch import (
    AgenticIdentity,
    AgenticIdentityUnresolved,
    AgentIdentityOntology,
    AgentIdentityRegistry,
    AgentIdentityTrust,
    resolve_agentic_identity,
)
from probos.consultation.dispatch import WorkItemSpec

if TYPE_CHECKING:
    from probos.mesh.capability import CapabilityMatch, CapabilityRegistry
    from probos.substrate.agent import BaseAgent

logger = logging.getLogger(__name__)

# Resolution reason constants — why a spec resolved (or didn't).
_REASON_CAPABILITY = "capability_match"
_REASON_CAPABILITY_DEPT_UNAVAILABLE = "capability_match_dept_unavailable"
_REASON_DEPARTMENT_ONLY = "department_only"
_REASON_UNRESOLVED = "unresolved_no_candidate"


class CrewAssignmentRegistry(AgentIdentityRegistry, Protocol):
    def all(self) -> list[BaseAgent]: ...


class CrewAssignmentTrust(AgentIdentityTrust, Protocol):
    def all_scores(self) -> dict[str, float]: ...


@dataclass(frozen=True)
class CrewWorkerEligibility:
    identity: AgenticIdentity | None
    reason: Literal["eligible", "missing", "inactive", "unresolved_identity"]


class CrewWorkerEligibilityResolver(Protocol):
    def check_eligibility(self, agent_id: str) -> CrewWorkerEligibility: ...


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
        ontology: AgentIdentityOntology,
        trust_network: CrewAssignmentTrust,
        agent_registry: CrewAssignmentRegistry,
    ) -> None:
        self._capability_registry = capability_registry
        self._ontology = ontology
        self._trust_network = trust_network
        self._agent_registry = agent_registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_eligibility(self, agent_id: str) -> CrewWorkerEligibility:
        """Check current crew execution eligibility without changing lifecycle."""
        if type(agent_id) is not str or not agent_id:
            return CrewWorkerEligibility(None, "unresolved_identity")
        try:
            agent = self._agent_registry.get(agent_id)
            if agent is None:
                return CrewWorkerEligibility(None, "missing")
            if not agent.is_alive:
                return CrewWorkerEligibility(None, "inactive")
            identity = resolve_agentic_identity(
                agent_id=agent_id,
                agent_registry=self._agent_registry,
                ontology=self._ontology,
                trust_network=self._trust_network,
            )
        except AgenticIdentityUnresolved:
            return CrewWorkerEligibility(None, "unresolved_identity")
        except Exception:
            logger.warning(
                "Crew eligibility lookup failed for agent=%s; "
                "execution identity cannot be established, rejecting candidate",
                agent_id,
                exc_info=True,
            )
            return CrewWorkerEligibility(None, "unresolved_identity")
        return CrewWorkerEligibility(identity, "eligible")

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
        eligible_matches = []
        for match in matches:
            eligibility = self.check_eligibility(match.agent_id)
            if eligibility.identity is not None:
                eligible_matches.append((match, eligibility.identity))
        if not eligible_matches:
            return None

        if department:
            dept_matches = [
                match for match, identity in eligible_matches
                if identity.department == department
            ]
            if dept_matches:
                return self._capability_decision(
                    spec, dept_matches[0], _REASON_CAPABILITY
                )
            # Department filter emptied the list — fall back to the alive
            # capability ranking and flag that the department was unavailable.
            return self._capability_decision(
                spec, eligible_matches[0][0], _REASON_CAPABILITY_DEPT_UNAVAILABLE
            )

        return self._capability_decision(spec, eligible_matches[0][0], _REASON_CAPABILITY)

    def _resolve_by_department(
        self, spec: WorkItemSpec, department: str
    ) -> AssignmentDecision | None:
        """No capability hint, department hint set: pick highest-trust alive in-dept agent."""
        candidates = []
        for agent in self._agent_registry.all():
            identity = self.check_eligibility(agent.id).identity
            if identity is not None and identity.department == department:
                candidates.append(identity)
        if not candidates:
            return None

        # Deterministic tie-break: higher trust first, then agent_id lexical.
        best = min(
            candidates,
            key=lambda identity: (
                -self._trust_network.get_score(identity.agent_id), identity.agent_id
            ),
        )
        return AssignmentDecision(
            spec_id=spec.spec_id,
            agent_id=best.agent_id,
            department=department,
            capability=spec.capability,
            score=self._trust_network.get_score(best.agent_id),
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
