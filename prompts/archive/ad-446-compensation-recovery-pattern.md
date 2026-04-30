# AD-446: Compensation & Recovery Pattern

**Status:** Ready for builder
**Dependencies:** AD-445 (Decision Queue & Pause/Resume)
**Estimated tests:** ~8

---

## Problem

AD-445 adds `DecisionQueue` with enqueue/resolve lifecycle. But when a
resolved decision fails during execution (e.g., a RECYCLE action crashes,
a SCALE action hits resource limits), there's no structured recovery.
The decision is marked APPROVED but the action never completed.

AD-446 adds a compensation pattern for failed decisions — structured
retry, escalation, and rollback tracking so the system can recover
from failed autonomous actions.

## Fix

### Section 1: Create `CompensationHandler`

**File:** `src/probos/governance/compensation.py` (new file)

**Note:** `src/probos/governance/` directory is created by AD-676 (Wave 2).
If AD-676/AD-445 have not been built first, create `src/probos/governance/__init__.py`
(empty file) before creating this file.

```python
"""Compensation & Recovery Pattern (AD-446).

Handles failed decision execution with structured recovery:
- Retry with adjusted parameters
- Escalation to higher approval gate
- Rollback tracking for reversible actions

Works with AD-445 DecisionQueue — processes decisions whose
execution failed after approval.
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

    RETRY = "retry"           # Retry with same or adjusted parameters
    ESCALATE = "escalate"     # Bump to higher approval gate
    ROLLBACK = "rollback"     # Reverse the partial action
    ABANDON = "abandon"       # Mark as failed, no further action


@dataclass
class CompensationRecord:
    """Record of a compensation attempt (AD-446)."""

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
        emit_fn: Callable[[str, dict[str, Any]], None] | None = None,
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
                        "AD-446: Escalation failed for %s",
                        decision_id, exc_info=True,
                    )
        else:
            strategy = RecoveryStrategy.ABANDON

        record = CompensationRecord(
            decision_id=decision_id,
            strategy=strategy,
            attempt_number=attempt,
            error=error,
        )
        self._history.append(record)

        logger.info(
            "AD-446: Decision %s attempt %d → %s (%s)",
            decision_id, attempt, strategy.value, error[:80],
        )

        if self._emit_fn:
            from probos.events import EventType
            self._emit_fn(EventType.COMPENSATION_TRIGGERED, {
                "decision_id": decision_id,
                "strategy": strategy.value,
                "attempt": attempt,
                "error": error,
                "timestamp": record.timestamp,
            })

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
```

### Section 2: Add `COMPENSATION_TRIGGERED` event type

**File:** `src/probos/events.py`

Add near the decision-related events:

SEARCH:
```python
    TOOL_PERMISSION_DENIED = "tool_permission_denied"
```

REPLACE:
```python
    TOOL_PERMISSION_DENIED = "tool_permission_denied"
    COMPENSATION_TRIGGERED = "compensation_triggered"  # AD-446
```

**Note:** If AD-445 has already built (adding `DECISION_QUEUE_PAUSED`) or
AD-448 has already built (adding `TOOL_INVOKED`) after this line, update
the SEARCH block to include those lines too.

### Section 3: Wire CompensationHandler in startup

**File:** `src/probos/startup/finalize.py`

Add near the DecisionQueue wiring (added by AD-445):

```python
    # AD-446: Compensation & Recovery
    from probos.governance.compensation import CompensationHandler
    compensation_handler = CompensationHandler(
        emit_fn=runtime.emit_event,
    )
    runtime._compensation_handler = compensation_handler
    logger.info("AD-446: CompensationHandler initialized")
```

## Tests

**File:** `tests/test_ad446_compensation_recovery.py`

8 tests:

1. `test_recovery_strategy_enum` — verify RETRY, ESCALATE, ROLLBACK, ABANDON exist
2. `test_compensation_record_creation` — create `CompensationRecord`, verify fields
3. `test_handle_failure_retry` — attempt 1 of 3 → RETRY strategy
4. `test_handle_failure_escalate` — attempt 3 of 3 → ESCALATE strategy
5. `test_handle_failure_abandon` — attempt 4 of 3 → ABANDON strategy
6. `test_escalation_fn_called` — mock escalation_fn, verify called on ESCALATE
7. `test_record_rollback` — call `record_rollback()`, verify strategy=ROLLBACK
8. `test_compensation_triggered_event` — mock emit_fn, handle failure, verify
   `COMPENSATION_TRIGGERED` event emitted with correct payload

## What This Does NOT Change

- DecisionQueue unchanged — CompensationHandler is a complementary system
- InitiativeEngine unchanged
- RemediationProposal unchanged
- Does NOT automatically detect execution failures — callers must invoke
  `handle_failure()` when a decision's action fails
- Does NOT implement actual rollback actions — only tracks that a rollback
  was attempted
- Does NOT add persistence (in-memory history only)
- Does NOT modify DecisionState enum (AD-445)

## Tracking

- `PROGRESS.md`: Add AD-446 as COMPLETE
- `docs/development/roadmap.md`: Update AD-446 status

## Acceptance Criteria

- `RecoveryStrategy` enum with RETRY/ESCALATE/ROLLBACK/ABANDON
- `CompensationHandler.handle_failure()` selects strategy based on attempt count
- Escalation triggers `escalation_fn` callback
- `record_rollback()` tracks rollback attempts
- `EventType.COMPENSATION_TRIGGERED` exists and is emitted
- All 8 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# AD-445 creates DecisionQueue
# File: src/probos/governance/decision_queue.py
# DecisionState: PENDING, APPROVED, REJECTED, DEFERRED, EXPIRED

# No existing compensation/recovery
grep -rn "CompensationHandler\|compensation_handler\|RecoveryStrategy" src/probos/ → no matches

# Governance directory
ls src/probos/governance/ → created by AD-445 or AD-676

# Events insertion point
grep -n "TOOL_PERMISSION_DENIED" src/probos/events.py
  165: TOOL_PERMISSION_DENIED = "tool_permission_denied"
```
