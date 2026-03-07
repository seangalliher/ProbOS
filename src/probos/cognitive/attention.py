"""Attention mechanism — priority-based task scheduling.

Replaces the "all agents get equal access" model with a scored attention
budget.  Tasks compete for compute resources based on urgency, deadline
proximity, and dependency chain position.  The DAGExecutor asks the
AttentionManager "which nodes should I run next?" instead of running all
ready nodes simultaneously.

This phase operates per-DAG (within a single ``process_natural_language``
call).  Cross-request attention and preemption are Phase 3b-3 concerns.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.types import AttentionEntry

logger = logging.getLogger(__name__)


class AttentionManager:
    """Priority scorer and budgeter for task execution.

    Does NOT own async execution — it scores and batches tasks.
    The DAGExecutor still owns the ``asyncio.gather()`` calls.
    """

    def __init__(
        self,
        max_concurrent: int = 8,
        decay_rate: float = 0.95,
    ) -> None:
        self.max_concurrent = max_concurrent
        self.decay_rate = decay_rate
        self._queue: dict[str, AttentionEntry] = {}
        self._focus_keywords: list[str] = []
        self._focus_context: str = ""

    # ---- submission / removal ------------------------------------

    def submit(self, entry: AttentionEntry) -> None:
        """Add a task to the attention queue."""
        self._queue[entry.task_id] = entry

    def mark_completed(self, task_id: str) -> None:
        """Remove a completed task from the queue."""
        self._queue.pop(task_id, None)

    def mark_failed(self, task_id: str) -> None:
        """Remove a failed task from the queue."""
        self._queue.pop(task_id, None)

    # ---- scoring -------------------------------------------------

    def compute_scores(self) -> None:
        """Recalculate attention scores for all queued tasks."""
        now = time.time()
        for entry in self._queue.values():
            entry.score = self._compute_single(entry, now)

    def _compute_single(self, entry: AttentionEntry, now: float) -> float:
        """Compute attention score for a single entry.

        score = urgency × relevance × deadline_factor × dep_bonus
        """
        # Deadline factor: increases as TTL drains
        created_ts = entry.created_at.timestamp()
        elapsed = max(now - created_ts, 0.0)
        remaining = max(entry.ttl_seconds - elapsed, 0.001)
        deadline_factor = entry.ttl_seconds / remaining
        # Clamp to avoid extreme values
        deadline_factor = min(deadline_factor, 10.0)
        entry.deadline_factor = deadline_factor

        # Dependency depth bonus: tasks that unblock others get +10% per level
        dep_bonus = 1.0 + (entry.dependency_depth * 0.1)

        return entry.urgency * entry.relevance * deadline_factor * dep_bonus

    # ---- batching ------------------------------------------------

    def get_next_batch(self, budget: int | None = None) -> list[AttentionEntry]:
        """Return the top-N tasks to execute, sorted by score descending.

        If budget is None, uses self.max_concurrent.
        """
        if budget is None:
            budget = self.max_concurrent

        self.compute_scores()

        sorted_entries = sorted(
            self._queue.values(),
            key=lambda e: e.score,
            reverse=True,
        )
        return sorted_entries[:budget]

    # ---- focus tracking ------------------------------------------

    def update_focus(self, intent: str, context: str) -> None:
        """Store the current request's keywords.

        Infrastructure for future cross-request attention (Phase 3b-3).
        Not used in scoring this phase.
        """
        words = intent.lower().split() + context.lower().split()
        self._focus_keywords = [w for w in words if len(w) > 2]
        self._focus_context = context

    @property
    def current_focus(self) -> dict[str, Any]:
        """Return current focus state."""
        return {
            "keywords": self._focus_keywords,
            "context": self._focus_context,
        }

    # ---- introspection -------------------------------------------

    def get_queue_snapshot(self) -> list[AttentionEntry]:
        """Return a copy of all queued tasks, sorted by score."""
        self.compute_scores()
        return sorted(
            self._queue.values(),
            key=lambda e: e.score,
            reverse=True,
        )

    @property
    def queue_size(self) -> int:
        return len(self._queue)
