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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from probos.types import AttentionEntry, FocusSnapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AD-1028: ContextAssembler seam — AttentionBid + global token budget.
#
# Every candidate piece of prompt context becomes an ``AttentionBid``. A pure,
# deterministic ``ContextAssembler`` selects the bids that fit a global token
# budget (by salience, pinned always kept), orders the survivors for
# primacy/recency, and renders ONLY the survivors (lazily — a dropped bid's
# renderer is never called). v1 salience is the fixed insertion priority, so
# with a large-enough budget the output is byte-identical to the prior
# push-style prepend chain.
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Estimate the token cost of ``text`` for budget arbitration.

    A transparent ~4-chars-per-token heuristic (no tokenizer dependency on the
    hot path). Returns at least 1 for any non-empty text so a bid is never
    free. Empty text costs 0.
    """
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


@dataclass
class AttentionBid:
    """A single candidate piece of context competing for the prompt window.

    Fields:
        source: provenance tag (e.g. ``"episodic"``, ``"oracle"``,
            ``"captain_message"``) — for audit/introspection.
        render: a LAZY zero-argument renderer returning the bid's text. It is
            called ONLY if the bid is selected; a dropped bid's renderer is
            never invoked.
        modality: content modality (default ``"text"``).
        salience: selection priority — higher wins under a scarce budget. v1 =
            the fixed insertion priority (no salience scoring yet; AD-1030).
        token_cost: estimated size for budget arbitration. Use
            :func:`estimate_tokens` for a default estimate.
        zone_floor: primacy/recency ordering key — survivors are emitted in
            ascending ``(zone_floor, insertion_order)`` order.
        pin: when True the bid is always kept, even under a tiny budget.
    """

    source: str
    render: Callable[[], str]
    modality: str = "text"
    salience: float = 0.0
    token_cost: int = 0
    zone_floor: int = 0
    pin: bool = False


class ContextAssembler:
    """Pure, deterministic selector/orderer for :class:`AttentionBid` lists.

    No I/O. Given a list of bids and a global token budget, it selects the
    bids that fit (pinned always kept; otherwise highest salience first),
    orders the survivors for primacy/recency, and renders only the survivors.
    """

    @staticmethod
    def assemble(bids: list[AttentionBid], *, token_budget: int) -> list[str]:
        """Select, order, and render the winning bids under ``token_budget``.

        Selection: pinned bids are always kept (they may, together, exceed the
        budget — the pin guarantee wins). Unpinned bids are admitted by
        descending salience (ties broken by insertion order) while the running
        total stays within budget — so scarcity drops the LOWEST-salience
        unpinned bids, never blind truncation, and the unpinned total never
        pushes the budget over.

        Ordering: survivors are emitted in ascending ``(zone_floor,
        insertion_order)`` order (primacy/recency).

        Rendering: ``render()`` is called ONLY on survivors — a dropped bid's
        renderer is never invoked.
        """
        if not bids:
            return []

        indexed = list(enumerate(bids))
        pinned = [(i, b) for i, b in indexed if b.pin]
        unpinned = [(i, b) for i, b in indexed if not b.pin]

        used = sum(b.token_cost for _, b in pinned)
        selected: list[tuple[int, AttentionBid]] = list(pinned)

        # Highest salience first; ties keep insertion order for determinism.
        unpinned_by_priority = sorted(unpinned, key=lambda ib: (-ib[1].salience, ib[0]))
        for i, bid in unpinned_by_priority:
            if used + bid.token_cost <= token_budget:
                used += bid.token_cost
                selected.append((i, bid))

        # Order survivors for primacy/recency, then render lazily.
        selected.sort(key=lambda ib: (ib[1].zone_floor, ib[0]))
        return [bid.render() for _, bid in selected]


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

    # ---- bid scoring (AD-1028 seam) ------------------------------

    def score_bid(self, bid: AttentionBid) -> float:
        """Score a context :class:`AttentionBid` (generalizes task scoring).

        Returns the bid's ``salience`` unchanged — a behavior-preserving seam.
        AD-1030 landed the real ``relevance × recency × importance`` linear
        salience in the pure :mod:`probos.cognitive.salience` module; it is
        applied at the DM/WR bid-build (where the per-memory/per-entry data the
        formula needs is in scope) and written onto the episodic/working-memory
        bids' ``salience``. So this seam continues to return whatever salience
        the bid carries — fixed insertion priority by default, the scored value
        when AD-1030 salience scoring is enabled. The task-scoring path
        (:meth:`_compute_single`) is untouched.
        """
        return bid.salience

    def score_bids(self, bids: list[AttentionBid]) -> list[AttentionBid]:
        """Assign salience to every bid via :meth:`score_bid` (in place).

        Returns the same list for convenience. v1 is an identity over the
        fixed insertion priorities (no behavior change).
        """
        for bid in bids:
            bid.salience = self.score_bid(bid)
        return bids

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
