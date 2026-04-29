# AD-445: Decision Queue & Pause/Resume

**Status:** Ready for builder
**Dependencies:** None
**Estimated tests:** ~10

---

## Problem

The `InitiativeEngine` (`initiative.py`) manages `RemediationProposal` objects
with a simple linear list and `approve/reject` methods. But there's no
structured decision queue — proposals can pile up without prioritization,
there's no way to pause decision-making (during incidents, resets, or
maintenance), and there's no structured lifecycle for proposals beyond
the `proposed → approved/rejected → executed` status.

AD-445 adds a `DecisionQueue` that provides prioritized queuing with
pause/resume capability, enabling the Captain or system to temporarily
halt autonomous decision-making.

## Fix

### Section 1: Create `DecisionQueue`

**File:** `src/probos/governance/decision_queue.py` (new file)

**IMPORTANT:** The `src/probos/governance/` directory does not yet exist.
If AD-676 has not been built first, the builder must create:
- `src/probos/governance/__init__.py` (empty file)
- Then create `decision_queue.py` in that directory.

```python
"""Decision Queue — prioritized proposal queue with pause/resume (AD-445).

Provides a structured queue for remediation proposals and other
decisions that require approval or evaluation. Supports pausing
all autonomous decisions during incidents or maintenance.
"""

from __future__ import annotations

import logging
import time
from collections import deque
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
    category: str  # "remediation" | "governance" | "operational"
    priority: int  # 0=lowest, 9=highest (same as Priority enum)
    summary: str
    detail: str
    source_agent_id: str = ""
    state: DecisionState = DecisionState.PENDING
    created_at: float = field(default_factory=time.time)
    resolved_at: float | None = None
    ttl_seconds: float = 300.0  # Auto-expire after 5 minutes
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Whether this decision has exceeded its TTL."""
        return (time.time() - self.created_at) > self.ttl_seconds

    def to_dict(self) -> dict[str, Any]:
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
        return self._pause_reason

    def pause(self, reason: str = "") -> None:
        """Pause autonomous decision processing."""
        self._paused = True
        self._pause_reason = reason
        self._pause_timestamp = time.time()
        logger.info("AD-445: Decision queue PAUSED — %s", reason or "no reason")
        if self._emit_fn:
            from probos.events import EventType
            self._emit_fn(EventType.DECISION_QUEUE_PAUSED, {
                "reason": reason,
                "pending_count": self.pending_count,
                "timestamp": self._pause_timestamp,
            })

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
                "AD-445: Decision queue RESUMED after %.1fs",
                pause_duration,
            )

    def enqueue(self, decision: QueuedDecision) -> bool:
        """Add a decision to the queue. Returns False if queue is full."""
        # Expire stale items first
        self._expire_stale()

        if len(self._queue) >= self._max_size:
            logger.warning(
                "AD-445: Decision queue full (%d), rejecting %s",
                self._max_size, decision.id,
            )
            return False

        self._queue.append(decision)
        # Sort by priority descending, then created_at ascending
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
```

### Section 2: Add `DECISION_QUEUE_PAUSED` event type

**File:** `src/probos/events.py`

Add after `ACTION_RISK_DENIED` (if AD-676 built) or after
`TOOL_PERMISSION_DENIED` (line ~165):

SEARCH:
```python
    TOOL_PERMISSION_DENIED = "tool_permission_denied"
```

REPLACE:
```python
    TOOL_PERMISSION_DENIED = "tool_permission_denied"
    DECISION_QUEUE_PAUSED = "decision_queue_paused"  # AD-445
```

**Note:** If AD-676 has already built (adding `ACTION_RISK_DENIED`),
update the SEARCH block to include that line too.

### Section 3: Wire DecisionQueue in startup

**File:** `src/probos/startup/finalize.py`

Add near the InitiativeEngine wiring. Grep for:
```
grep -n "InitiativeEngine\|initiative_engine" src/probos/startup/finalize.py
```

```python
    # AD-445: Decision Queue
    from probos.governance.decision_queue import DecisionQueue
    decision_queue = DecisionQueue(
        emit_fn=runtime.emit_event,
    )
    runtime._decision_queue = decision_queue
    logger.info("AD-445: DecisionQueue initialized")
```

### Section 4: Add decision queue API endpoints

**File:** `src/probos/routers/system.py`

```python
@router.get("/api/decision-queue")
async def get_decision_queue(runtime: Any = Depends(get_runtime)) -> dict:
    """Return decision queue status (AD-445)."""
    queue = getattr(runtime, "_decision_queue", None)
    if not queue:
        return {"status": "disabled"}
    return {
        **queue.get_summary(),
        "decisions": [d.to_dict() for d in queue.get_all()],
    }


@router.post("/api/decision-queue/pause")
async def pause_decision_queue(
    body: dict[str, Any],
    runtime: Any = Depends(get_runtime),
) -> dict:
    """Pause the decision queue (AD-445)."""
    queue = getattr(runtime, "_decision_queue", None)
    if not queue:
        return {"status": "disabled"}
    reason = body.get("reason", "")
    queue.pause(reason)
    return {"status": "paused", "reason": reason}


@router.post("/api/decision-queue/resume")
async def resume_decision_queue(runtime: Any = Depends(get_runtime)) -> dict:
    """Resume the decision queue (AD-445)."""
    queue = getattr(runtime, "_decision_queue", None)
    if not queue:
        return {"status": "disabled"}
    queue.resume()
    return {"status": "resumed"}
```

## Tests

**File:** `tests/test_ad445_decision_queue.py`

10 tests:

1. `test_decision_state_enum` — verify PENDING, APPROVED, REJECTED, DEFERRED,
   EXPIRED exist
2. `test_queued_decision_creation` — create `QueuedDecision`, verify fields
3. `test_queued_decision_expiry` — create with `ttl_seconds=0`, verify
   `is_expired` is True
4. `test_enqueue_and_next_pending` — enqueue 2 decisions, verify
   `next_pending()` returns highest priority
5. `test_enqueue_full_queue` — set `max_size=1`, enqueue 2 → second returns False
6. `test_pause_blocks_next_pending` — pause queue, verify `next_pending()`
   returns None even with pending decisions
7. `test_resume_unblocks` — pause, resume, verify `next_pending()` returns
   decision
8. `test_resolve_decision` — enqueue, resolve as APPROVED, verify state changed
9. `test_expire_stale_decisions` — enqueue with `ttl_seconds=0`, call
   `get_all()`, verify state is EXPIRED
10. `test_decision_queue_paused_event` — mock `emit_fn`, pause queue, verify
    `DECISION_QUEUE_PAUSED` event emitted

## What This Does NOT Change

- `InitiativeEngine` unchanged — it continues using its own `_proposals` list.
  Future AD can bridge InitiativeEngine → DecisionQueue.
- `RemediationProposal` unchanged
- No changes to `approve_proposal()` / `reject_proposal()` on InitiativeEngine
- Does NOT add automatic proposal→decision bridging
- Does NOT add decision persistence — in-memory only (resets on restart)
- Does NOT add quorum-based approval (future enhancement)

## Tracking

- `PROGRESS.md`: Add AD-445 as COMPLETE
- `docs/development/roadmap.md`: Update AD-445 status

## Acceptance Criteria

- `DecisionQueue` with `enqueue()`, `next_pending()`, `resolve()` exists
- Pause/resume blocks/unblocks `next_pending()`
- Priority ordering works (higher priority first)
- TTL expiration works
- `EventType.DECISION_QUEUE_PAUSED` exists
- API endpoints for queue status, pause, resume work
- All 10 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# InitiativeEngine proposals
grep -n "class RemediationProposal\|_proposals\|approve_proposal\|reject_proposal" \
  src/probos/initiative.py
  40: RemediationProposal dataclass
  108: self._proposals: list[RemediationProposal]
  292: approve_proposal(proposal_id)
  300: reject_proposal(proposal_id)

# No existing decision queue
grep -rn "DecisionQueue\|decision_queue\|pending_decision" src/probos/ → no matches

# Governance directory
ls src/probos/governance/ → may not exist (AD-676 creates it)

# Events insertion point
grep -n "TOOL_PERMISSION_DENIED" src/probos/events.py
  165: TOOL_PERMISSION_DENIED = "tool_permission_denied"
```
