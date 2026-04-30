"""Decision Queue — prioritized proposal queue with pause/resume (AD-445).

Provides a structured queue for remediation proposals and other
decisions that require approval or evaluation. Supports pausing
all autonomous decisions during incidents or maintenance.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class DecisionState(str, Enum):
    """Lifecycle state for a queued decision."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    EXPIRED = "expired"


@dataclass
class QueuedDecision:
    """A decision item in the queue (AD-445)."""

    id: str
    category: str
    priority: int
    summary: str
    detail: str
    source_agent_id: str = ""
    state: DecisionState = DecisionState.PENDING
    created_at: float = field(default_factory=time.time)
    resolved_at: float | None = None
    ttl_seconds: float = 300.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Whether this decision has exceeded its TTL."""
        return (time.time() - self.created_at) >= self.ttl_seconds

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable representation of the decision."""
        return {
            "id": self.id,
            "category": self.category,
            "priority": self.priority,
            "summary": self.summary,
            "state": self.state.value,
            "source_agent_id": self.source_agent_id,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "is_expired": self.is_expired,
        }


class DecisionQueue:
    """Prioritized decision queue with pause/resume (AD-445).

    Decisions are ordered by priority (descending) then by creation
    time (ascending). When paused, no decisions are dequeued for
    autonomous processing — they remain pending until resumed.
    """

    def __init__(
        self,
        *,
        max_size: int = 100,
        emit_fn: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._queue: list[QueuedDecision] = []
        self._max_size = max_size
        self._paused = False
        self._pause_reason: str = ""
        self._pause_timestamp: float | None = None
        self._emit_fn = emit_fn
        self._resolved_count: int = 0

    @property
    def paused(self) -> bool:
        """Whether the queue is paused."""
        return self._paused

    @property
    def pause_reason(self) -> str:
        """Reason recorded for the current pause, if any."""
        return self._pause_reason

    def pause(self, reason: str = "") -> None:
        """Pause autonomous decision processing."""
        self._paused = True
        self._pause_reason = reason
        self._pause_timestamp = time.time()
        logger.info(
            "AD-445: Decision queue paused; autonomous decisions are halted until resume; reason=%s",
            reason or "unspecified",
        )
        if self._emit_fn:
            from probos.events import EventType

            self._emit_fn(
                EventType.DECISION_QUEUE_PAUSED,
                {
                    "reason": reason,
                    "pending_count": self.pending_count,
                    "timestamp": self._pause_timestamp,
                },
            )

    def resume(self) -> None:
        """Resume autonomous decision processing."""
        was_paused = self._paused
        self._paused = False
        pause_duration = 0.0
        if self._pause_timestamp:
            pause_duration = time.time() - self._pause_timestamp
        self._pause_reason = ""
        self._pause_timestamp = None
        if was_paused:
            logger.info(
                "AD-445: Decision queue resumed after %.1fs; autonomous decisions may continue",
                pause_duration,
            )

    def enqueue(self, decision: QueuedDecision) -> bool:
        """Add a decision to the queue. Returns False if queue is full."""
        self._expire_stale()

        if len(self._queue) >= self._max_size:
            logger.warning(
                "AD-445: Decision queue full at max_size=%d; rejecting decision_id=%s; caller may retry after decisions resolve",
                self._max_size,
                decision.id,
            )
            return False

        self._queue.append(decision)
        self._queue.sort(
            key=lambda d: (-d.priority, d.created_at),
        )
        return True

    def next_pending(self) -> QueuedDecision | None:
        """Get the highest-priority pending decision.

        Returns None if paused or no pending decisions.
        """
        if self._paused:
            return None
        self._expire_stale()
        for decision in self._queue:
            if decision.state == DecisionState.PENDING:
                return decision
        return None

    def resolve(
        self,
        decision_id: str,
        state: DecisionState,
    ) -> bool:
        """Resolve a decision (approve/reject/defer). Returns True if found."""
        for decision in self._queue:
            if decision.id == decision_id:
                decision.state = state
                decision.resolved_at = time.time()
                self._resolved_count += 1
                return True
        return False

    @property
    def pending_count(self) -> int:
        """Number of pending (unresolved, unexpired) decisions."""
        self._expire_stale()
        return sum(
            1 for d in self._queue
            if d.state == DecisionState.PENDING
        )

    def get_all(self, *, include_resolved: bool = False) -> list[QueuedDecision]:
        """Return queue contents."""
        self._expire_stale()
        if include_resolved:
            return list(self._queue)
        return [d for d in self._queue if d.state == DecisionState.PENDING]

    def get_summary(self) -> dict[str, Any]:
        """Return queue status summary."""
        self._expire_stale()
        return {
            "paused": self._paused,
            "pause_reason": self._pause_reason,
            "pending": self.pending_count,
            "total": len(self._queue),
            "resolved_total": self._resolved_count,
        }

    def _expire_stale(self) -> None:
        """Mark expired decisions."""
        for decision in self._queue:
            if (
                decision.state == DecisionState.PENDING
                and decision.is_expired
            ):
                decision.state = DecisionState.EXPIRED
                decision.resolved_at = time.time()
