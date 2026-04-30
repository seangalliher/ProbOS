"""Compensation & Recovery Pattern (AD-446).

Handles failed decision execution with structured recovery:
- Retry with adjusted parameters
- Escalation to higher approval gate
- Rollback tracking for reversible actions

Works with AD-445 DecisionQueue — processes decisions whose
execution failed after approval. Escalation callback failures are
logged and degraded without retry; callers receive the selected
strategy and can decide whether additional recovery is appropriate.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class RecoveryStrategy(str, Enum):
    """Recovery strategy for a failed decision (AD-446)."""

    RETRY = "retry"
    ESCALATE = "escalate"
    ROLLBACK = "rollback"
    ABANDON = "abandon"


@dataclass
class CompensationRecord:
    """Mutable record of a compensation attempt (AD-446)."""

    decision_id: str
    strategy: RecoveryStrategy
    attempt_number: int
    timestamp: float = field(default_factory=time.time)
    success: bool = False
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class CompensationHandler:
    """Handles failed decision recovery (AD-446).

    Usage:
        handler = CompensationHandler(max_retries=3)
        record = handler.handle_failure(
            decision_id="dec-123",
            error="Resource limit exceeded",
            attempt=1,
        )
        # record.strategy tells the caller what to do next
    """

    def __init__(
        self,
        *,
        max_retries: int = 3,
        escalation_fn: Callable[[str], None] | None = None,
        emit_fn: Callable[[Any, dict[str, Any]], None] | None = None,
    ) -> None:
        self._max_retries = max_retries
        self._escalation_fn = escalation_fn
        self._emit_fn = emit_fn
        self._history: list[CompensationRecord] = []

    def handle_failure(
        self,
        decision_id: str,
        error: str,
        attempt: int = 1,
        *,
        category: str = "",
    ) -> CompensationRecord:
        """Determine recovery strategy for a failed decision.

        Rules:
        - attempt < max_retries → RETRY
        - attempt == max_retries → ESCALATE
        - attempt > max_retries → ABANDON

        Returns a CompensationRecord with the chosen strategy.
        """
        if attempt < self._max_retries:
            strategy = RecoveryStrategy.RETRY
        elif attempt == self._max_retries:
            strategy = RecoveryStrategy.ESCALATE
            if self._escalation_fn:
                try:
                    self._escalation_fn(decision_id)
                except Exception:
                    logger.warning(
                        "AD-446: Escalation callback failed for decision_id=%s; human escalation may be delayed; continuing with compensation record",
                        decision_id,
                        exc_info=True,
                    )
        else:
            strategy = RecoveryStrategy.ABANDON

        record = CompensationRecord(
            decision_id=decision_id,
            strategy=strategy,
            attempt_number=attempt,
            error=error,
            metadata={"category": category} if category else {},
        )
        self._history.append(record)

        logger.info(
            "AD-446: Compensation selected for decision_id=%s attempt=%d strategy=%s; caller should execute recovery action; error=%s",
            decision_id,
            attempt,
            strategy.value,
            error[:80],
        )

        if self._emit_fn:
            from probos.events import EventType

            self._emit_fn(
                EventType.COMPENSATION_TRIGGERED,
                {
                    "decision_id": decision_id,
                    "strategy": strategy.value,
                    "attempt": attempt,
                    "error": error,
                    "timestamp": record.timestamp,
                },
            )

        return record

    def record_rollback(
        self,
        decision_id: str,
        *,
        success: bool = True,
        error: str = "",
    ) -> CompensationRecord:
        """Record a rollback attempt for a failed decision."""
        record = CompensationRecord(
            decision_id=decision_id,
            strategy=RecoveryStrategy.ROLLBACK,
            attempt_number=0,
            success=success,
            error=error,
        )
        self._history.append(record)
        return record

    def get_history(
        self, *, decision_id: str = "", limit: int = 50,
    ) -> list[CompensationRecord]:
        """Query compensation history."""
        results = self._history
        if decision_id:
            results = [r for r in results if r.decision_id == decision_id]
        return results[-limit:]

    def get_summary(self) -> dict[str, Any]:
        """Return compensation statistics."""
        by_strategy: dict[str, int] = {}
        for record in self._history:
            key = record.strategy.value
            by_strategy[key] = by_strategy.get(key, 0) + 1
        return {
            "total_compensations": len(self._history),
            "by_strategy": by_strategy,
        }
