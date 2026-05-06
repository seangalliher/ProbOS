"""AD-482c v1: Human Approval Gate.

A `ProposalStore`-backed queue surface with approve/reject semantics. Wraps
(does NOT replace) the existing ``SelfModificationPipeline._user_approval_fn``
callback. Designed-agent flow can keep the bool callback OR route through
ApprovalGate (operator choice via config).

Audit trail: every decision emits a typed event and persists the rationale
to the proposal lesson record (AD-482d EvolutionStore terminal-decision flow).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from probos.cognitive.self_improvement.proposal import (
    CapabilityProposal,
    ProposalState,
    ProposalStore,
)

logger = logging.getLogger(__name__)


class ApprovalGate:
    """Captain-facing approval queue for capability proposals."""

    def __init__(
        self,
        *,
        proposal_store: ProposalStore,
        event_emit_fn: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._proposals = proposal_store
        self._emit = event_emit_fn
        self._clock = clock
        # audit_log: append-only (proposal_id, decision, approver, ts, rationale)
        self._audit_log: list[tuple[str, str, str, float, str]] = []

    def enqueue(self, proposal: CapabilityProposal) -> str:
        """Add a proposal to the pending queue. Returns the proposal id.

        This is a thin wrapper over `ProposalStore.submit` for callers that
        prefer the queue-language API.
        """
        return self._proposals.submit(proposal)

    def pending_count(self) -> int:
        return len(self._proposals.list_pending())

    def list_pending(self) -> list[CapabilityProposal]:
        return self._proposals.list_pending()

    def approve(
        self,
        proposal_id: str,
        *,
        approver: str,
        modifications: dict[str, Any] | None = None,
    ) -> bool:
        """Approve a proposal. Optional modifications dict captured in audit.

        Returns False if proposal_id is unknown or not in PENDING state.
        """
        state = self._proposals.state(proposal_id)
        if state is None or state is not ProposalState.PENDING:
            logger.warning(
                "AD-482c: approve %s rejected -- state is %s",
                proposal_id,
                state.value if state else "unknown",
            )
            return False
        rationale = "approved"
        if modifications:
            rationale = f"approved with modifications: {sorted(modifications.keys())}"
        ok = self._proposals.update_state(
            proposal_id, ProposalState.APPROVED, rationale=rationale,
        )
        if not ok:
            return False
        self._audit_log.append(
            (proposal_id, "approve", approver, self._clock(), rationale),
        )
        self._emit_event(
            "CAPABILITY_PROPOSAL_APPROVED",
            proposal_id=proposal_id,
            approver=approver,
            modifications=modifications or {},
        )
        return True

    def reject(self, proposal_id: str, *, approver: str, reason: str) -> bool:
        """Reject a proposal with a required rationale.

        Returns False if proposal_id is unknown or not in PENDING state.
        """
        state = self._proposals.state(proposal_id)
        if state is None or state is not ProposalState.PENDING:
            logger.warning(
                "AD-482c: reject %s rejected -- state is %s",
                proposal_id,
                state.value if state else "unknown",
            )
            return False
        if not reason:
            logger.warning("AD-482c: reject %s requires non-empty reason", proposal_id)
            return False
        ok = self._proposals.update_state(
            proposal_id, ProposalState.REJECTED, rationale=reason,
        )
        if not ok:
            return False
        self._audit_log.append(
            (proposal_id, "reject", approver, self._clock(), reason),
        )
        self._emit_event(
            "CAPABILITY_PROPOSAL_REJECTED",
            proposal_id=proposal_id,
            approver=approver,
            reason=reason,
        )
        return True

    def audit_entries(self, *, proposal_id: str | None = None) -> list[tuple[str, str, str, float, str]]:
        """Return a copy of the audit log, optionally filtered by proposal_id."""
        if proposal_id is None:
            return list(self._audit_log)
        return [entry for entry in self._audit_log if entry[0] == proposal_id]

    def _emit_event(self, name: str, **payload: Any) -> None:
        if self._emit is None:
            return
        try:
            self._emit(name, payload)
        except Exception:
            logger.warning("AD-482c: event_emit %s failed", name, exc_info=True)
