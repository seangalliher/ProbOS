"""AD-482b v1: Capability Proposals.
AD-482e v1: PIVOT/REFINE Decision Loops + IterationGuard.

A `CapabilityProposal` is a typed schema for "here's what was found, why it
matters, and how it fits." Submitted by any agent (research, scout, code
reviewer); flows through the `ApprovalGate` queue (AD-482c).

`PivotRefineDecision` is the autonomous decision primitive: PROCEED (advance to
next stage), REFINE (tweak and retry -- counts against IterationGuard cap), or
PIVOT (abandon and try a different approach -- terminal for this proposal).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from probos.cognitive.self_improvement.grounding import ProposalGroundingResult

logger = logging.getLogger(__name__)


class ProposalState(str, Enum):
    """Lifecycle state of a CapabilityProposal."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REFINING = "refining"
    PIVOTED = "pivoted"


class PivotRefineDecision(str, Enum):
    """AD-482e: autonomous decision primitive.

    PROCEED  -- advance to next stage.
    REFINE   -- tweak inputs and retry (counts against iteration cap).
    PIVOT    -- abandon this approach (terminal for this proposal).
    """

    PROCEED = "proceed"
    REFINE = "refine"
    PIVOT = "pivot"


@dataclass(frozen=True)
class CapabilityProposal:
    """Typed proposal for a discovered capability.

    Mirrors roadmap.md:3672 -- fields surface "what was found, why it matters,
    how it fits."
    """

    id: str
    source: str  # "repo", "paper", "api", "scout", "research", etc.
    source_url: str
    summary: str
    relevance: float  # 0.0 .. 1.0
    fit_assessment: str
    integration_effort_hours: float
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    license: str = ""
    submitted_at: float = 0.0
    submitter_agent_id: str = ""


@dataclass
class IterationGuard:
    """AD-482e: caps PIVOT/REFINE iterations and tracks artifact versions.

    Args:
        max_iterations: Hard cap on REFINE decisions before forcing PIVOT.
        decisions: Append-only log of (timestamp, decision) tuples.
        artifacts: Append-only log of (artifact_id, content_hash) tuples.
    """

    max_iterations: int
    decisions: list[tuple[float, PivotRefineDecision]] = field(default_factory=list)
    artifacts: list[tuple[str, str]] = field(default_factory=list)

    def register(self, decision: PivotRefineDecision, *, now: float | None = None) -> bool:
        """Register a decision. Returns False when REFINE cap exceeded."""
        ts = time.time() if now is None else now
        if decision is PivotRefineDecision.REFINE:
            refine_count = sum(1 for _, d in self.decisions if d is PivotRefineDecision.REFINE)
            if refine_count >= self.max_iterations:
                logger.warning(
                    "AD-482e: IterationGuard REFINE cap %d reached; rejecting",
                    self.max_iterations,
                )
                return False
        self.decisions.append((ts, decision))
        return True

    def record_artifact(self, artifact_id: str, content_hash: str) -> str:
        """Record an artifact version. Returns the artifact_id."""
        self.artifacts.append((artifact_id, content_hash))
        return artifact_id


class ProposalStore:
    """In-memory append-only registry of CapabilityProposals.

    Terminal decisions (APPROVED, REJECTED, PIVOTED) emit a lesson to the
    EvolutionStore via ``evolution_store_callback`` (optional dependency
    injection -- None disables lesson emission).
    """

    def __init__(
        self,
        *,
        evolution_store_callback: Callable[[str, str, str, str, dict[str, Any]], str] | None = None,
        event_emit_fn: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.time,
        iteration_cap: int = 5,
    ) -> None:
        self._records: dict[str, CapabilityProposal] = {}
        self._states: dict[str, ProposalState] = {}
        self._guards: dict[str, IterationGuard] = {}
        self._grounding: dict[str, ProposalGroundingResult] = {}
        self._evolution_callback = evolution_store_callback
        self._emit = event_emit_fn
        self._clock = clock
        self._iteration_cap = iteration_cap

    def submit(self, proposal: CapabilityProposal) -> str:
        """Register a new proposal in PENDING state. Returns the proposal id."""
        if proposal.id in self._records:
            logger.warning(
                "AD-482b: duplicate proposal id %r; replacing existing entry",
                proposal.id,
            )
        # Stamp submitted_at if caller left it default
        if proposal.submitted_at == 0.0:
            stamped = CapabilityProposal(
                id=proposal.id,
                source=proposal.source,
                source_url=proposal.source_url,
                summary=proposal.summary,
                relevance=proposal.relevance,
                fit_assessment=proposal.fit_assessment,
                integration_effort_hours=proposal.integration_effort_hours,
                dependencies=proposal.dependencies,
                license=proposal.license,
                submitted_at=self._clock(),
                submitter_agent_id=proposal.submitter_agent_id,
            )
        else:
            stamped = proposal
        self._records[stamped.id] = stamped
        self._states[stamped.id] = ProposalState.PENDING
        self._guards[stamped.id] = IterationGuard(max_iterations=self._iteration_cap)
        self._emit_event("CAPABILITY_PROPOSAL_CREATED", stamped.id, "submit")
        return stamped.id

    def get(self, proposal_id: str) -> CapabilityProposal | None:
        return self._records.get(proposal_id)

    def list_pending(self) -> list[CapabilityProposal]:
        return [
            self._records[pid]
            for pid, state in self._states.items()
            if state is ProposalState.PENDING
        ]

    def attach_grounding(
        self, proposal_id: str, result: "ProposalGroundingResult"
    ) -> None:
        """AD-833: associate a grounding result with a known proposal.

        Unknown id -> warn and return (advisory, never raises).
        """
        if proposal_id not in self._records:
            logger.warning(
                "AD-833: attach_grounding for unknown proposal %r; ignoring",
                proposal_id,
            )
            return
        self._grounding[proposal_id] = result

    def get_grounding(self, proposal_id: str) -> "ProposalGroundingResult | None":
        """AD-833: return the grounding result for a proposal, or None."""
        return self._grounding.get(proposal_id)

    def state(self, proposal_id: str) -> ProposalState | None:
        return self._states.get(proposal_id)

    def guard(self, proposal_id: str) -> IterationGuard | None:
        return self._guards.get(proposal_id)

    def transition(
        self,
        proposal_id: str,
        decision: PivotRefineDecision,
        *,
        rationale: str = "",
    ) -> bool:
        """Apply a PIVOT/REFINE/PROCEED decision. Returns False on cap exceeded
        or unknown proposal id."""
        if proposal_id not in self._records:
            return False
        guard = self._guards[proposal_id]
        accepted = guard.register(decision, now=self._clock())
        if not accepted:
            return False
        if decision is PivotRefineDecision.PIVOT:
            self._states[proposal_id] = ProposalState.PIVOTED
            self._record_lesson(proposal_id, "pivot", rationale)
        elif decision is PivotRefineDecision.REFINE:
            self._states[proposal_id] = ProposalState.REFINING
        # PROCEED leaves state at PENDING (caller advances via approve/reject)
        self._emit_event("PIVOT_REFINE_DECIDED", proposal_id, decision.value, rationale=rationale)
        return True

    def update_state(
        self,
        proposal_id: str,
        new_state: ProposalState,
        *,
        rationale: str = "",
    ) -> bool:
        """Force-set the proposal state (used by ApprovalGate)."""
        if proposal_id not in self._records:
            return False
        old_state = self._states[proposal_id]
        self._states[proposal_id] = new_state
        if new_state in (ProposalState.APPROVED, ProposalState.REJECTED):
            self._record_lesson(proposal_id, new_state.value, rationale)
        logger.info(
            "AD-482b: proposal %s %s -> %s (%s)",
            proposal_id,
            old_state.value,
            new_state.value,
            rationale[:80] if rationale else "no rationale",
        )
        return True

    def _record_lesson(self, proposal_id: str, outcome: str, rationale: str) -> None:
        if self._evolution_callback is None:
            return
        try:
            proposal = self._records.get(proposal_id)
            if proposal is None:
                return
            payload = {
                "source": proposal.source,
                "fit_assessment": proposal.fit_assessment,
                "rationale": rationale,
            }
            self._evolution_callback(
                outcome,  # category
                proposal.summary,  # summary
                proposal_id,  # source_proposal_id
                outcome,  # outcome
                payload,  # payload
            )
        except Exception:
            logger.warning(
                "AD-482b: evolution_callback failed for proposal %s; lesson lost",
                proposal_id,
                exc_info=True,
            )

    def _emit_event(self, name: str, proposal_id: str, action: str, **extra: Any) -> None:
        if self._emit is None:
            return
        try:
            self._emit(name, {"proposal_id": proposal_id, "action": action, **extra})
        except Exception:
            logger.warning("AD-482b: event_emit %s failed", name, exc_info=True)


def make_proposal_id() -> str:
    """Return a new random proposal id (uuid4 hex prefix)."""
    return uuid.uuid4().hex[:12]
