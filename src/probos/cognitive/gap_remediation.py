"""AD-539c v1: Observational Gap Remediation Tracker.

Records remediation candidates for gaps identified by the AD-539 pipeline.
v1 is OBSERVATIONAL ONLY — it never triggers remediation actions. Active
remediation is deferred to AD-539c-i.

Forcing function for AD-539c-i: Captain decides to switch from observational
to action mode after reviewing recorded candidates.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemediationCandidate:
    """v1 observational record. AD-539c."""

    gap_id: str  # references GapReport.id
    agent_id: str
    gap_type: str  # "knowledge" | "capability" | "data"
    proposed_action: str  # "trigger_qualification" | "request_data_routing" | "escalate_capability" | "no_action"
    reason: str
    candidate_at: float  # UTC timestamp


class GapRemediationTracker:
    """v1 observational only. Records remediation candidates for gaps. AD-539c."""

    def __init__(self, runtime: Any, max_history: int = 100) -> None:
        self._runtime = runtime
        self._max_history = max_history
        self._candidates: deque[RemediationCandidate] = deque(maxlen=max_history)
        # Sibling pattern AD-456/AD-530: public emit_event field assigned by wiring.
        self.emit_event: Callable[..., None] | None = None

    def record_candidate(self, gap_report: Any) -> RemediationCandidate:
        """Record a remediation candidate for a gap.

        Args:
            gap_report: A GapReport (gap_predictor.py:186). Reads gap_type +
                qualification_path_id + priority to derive proposed_action.

        Returns:
            RemediationCandidate (frozen dataclass). Caller stores or ignores.

        Side effects:
            - Appends to bounded ring (evicts oldest beyond max_history).
            - Emits GAP_REMEDIATION_RECORDED via emit_event (if set).

        v1 NEVER actually triggers the remediation. It only records what
        the system WOULD do. Active remediation is AD-539c-i.
        """
        action = self.proposed_action_for(gap_report)
        reason = self._reason_for(gap_report, action)
        candidate = RemediationCandidate(
            gap_id=getattr(gap_report, "id", ""),
            agent_id=getattr(gap_report, "agent_id", ""),
            gap_type=getattr(gap_report, "gap_type", ""),
            proposed_action=action,
            reason=reason,
            candidate_at=time.time(),
        )
        self._candidates.append(candidate)

        if self.emit_event is not None:
            try:
                self.emit_event(
                    EventType.GAP_REMEDIATION_RECORDED,
                    {
                        "gap_id": candidate.gap_id,
                        "agent_id": candidate.agent_id,
                        "gap_type": candidate.gap_type,
                        "proposed_action": candidate.proposed_action,
                        "reason": candidate.reason,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-539c: emit_event failed for gap_id=%s; candidate recorded locally, downstream listeners skipped",
                    candidate.gap_id,
                )

        return candidate

    def proposed_action_for(self, gap_report: Any) -> str:
        """Map gap → proposed action string (deterministic; no side effects).

        - gap_type="knowledge" + qualification_path_id non-empty → "trigger_qualification"
        - gap_type="data" → "request_data_routing"
        - gap_type="capability" → "escalate_capability"
        - else → "no_action"

        Note (observational hole, AD-539c-i): a `knowledge` gap with an EMPTY
        `qualification_path_id` falls through to `"no_action"` — same return
        as an unrecognized gap_type. v1 accepts this; AD-539c-i may add a
        distinct `"knowledge_no_path"` sentinel if downstream observability
        needs to disambiguate the two fall-through cases.
        """
        gap_type = getattr(gap_report, "gap_type", "")
        if gap_type == "knowledge":
            qpath = getattr(gap_report, "qualification_path_id", "") or ""
            if qpath:
                return "trigger_qualification"
            return "no_action"
        if gap_type == "data":
            return "request_data_routing"
        if gap_type == "capability":
            return "escalate_capability"
        return "no_action"

    def recent_candidates(self, limit: int = 20) -> tuple[RemediationCandidate, ...]:
        """Return most-recent candidates (newest first), capped at limit."""
        if limit <= 0:
            return ()
        # deque is oldest→newest; reverse and slice.
        newest_first = list(reversed(self._candidates))
        return tuple(newest_first[:limit])

    def candidates_for_agent(self, agent_id: str) -> tuple[RemediationCandidate, ...]:
        """Return candidates filtered by agent_id (newest first)."""
        newest_first = reversed(self._candidates)
        return tuple(c for c in newest_first if c.agent_id == agent_id)

    def _reason_for(self, gap_report: Any, action: str) -> str:
        priority = getattr(gap_report, "priority", "medium")
        gap_type = getattr(gap_report, "gap_type", "")
        if action == "trigger_qualification":
            qpath = getattr(gap_report, "qualification_path_id", "")
            return f"knowledge gap (priority={priority}) → qualification path {qpath}"
        if action == "request_data_routing":
            return f"data gap (priority={priority}) → request data routing"
        if action == "escalate_capability":
            return f"capability gap (priority={priority}) → escalate"
        return f"no remediation mapping for gap_type={gap_type!r}"
