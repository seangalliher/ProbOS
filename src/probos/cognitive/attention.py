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

from probos.types import AttentionEntry, FocusSnapshot

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
        focus_history_size: int = 10,
        background_demotion_factor: float = 0.25,
    ) -> None:
        self.max_concurrent = max_concurrent
        self.decay_rate = decay_rate
        self._focus_history_size = focus_history_size
        self._background_demotion_factor = background_demotion_factor
        self._queue: dict[str, AttentionEntry] = {}
        self._focus_keywords: list[str] = []
        self._focus_context: str = ""
        self._focus_history: list[FocusSnapshot] = []

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

        # Cross-request relevance from focus history
        relevance = self._compute_relevance(entry)

        score = entry.urgency * relevance * deadline_factor * dep_bonus

        # Background demotion
        if entry.is_background:
            score *= self._background_demotion_factor

        return score

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
        """Store the current request's keywords and append to focus history.

        Maintains a ring buffer of FocusSnapshot entries for cross-request
        relevance scoring.
        """
        words = intent.lower().split() + context.lower().split()
        self._focus_keywords = [w for w in words if len(w) > 2]
        self._focus_context = context

        snapshot = FocusSnapshot(
            keywords=list(self._focus_keywords),
            context=context,
        )
        self._focus_history.append(snapshot)
        # Evict oldest when exceeding max size
        while len(self._focus_history) > self._focus_history_size:
            self._focus_history.pop(0)

    @property
    def current_focus(self) -> dict[str, Any]:
        """Return current focus state."""
        return {
            "keywords": self._focus_keywords,
            "context": self._focus_context,
        }

    @property
    def focus_history(self) -> list[FocusSnapshot]:
        """Return a copy of the focus history ring buffer."""
        return list(self._focus_history)

    def _compute_relevance(self, entry: AttentionEntry) -> float:
        """Compute keyword overlap between entry intent and recent focus.

        Uses the union of keywords from the last 3 focus snapshots.
        Returns max(overlap_ratio, 0.3) so unfocused tasks get a floor score.
        """
        if not self._focus_history:
            return 1.0

        # Union of keywords from the last 3 snapshots
        recent = self._focus_history[-3:]
        focus_words: set[str] = set()
        for snap in recent:
            focus_words.update(snap.keywords)

        if not focus_words:
            return 1.0

        # Tokenize entry intent (split on underscores and spaces)
        intent_tokens: set[str] = set()
        for part in entry.intent.lower().replace("_", " ").split():
            if len(part) > 2:
                intent_tokens.add(part)

        if not intent_tokens:
            return 0.3

        overlap = len(intent_tokens & focus_words)
        ratio = overlap / len(intent_tokens)
        return max(ratio, 0.3)

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
