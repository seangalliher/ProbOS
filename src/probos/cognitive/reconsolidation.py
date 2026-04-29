"""AD-574: Episodic Decay & Reconsolidation Scheduling.

Ebbinghaus-inspired spaced review scheduling for high-importance episodes.
Intervals scale inversely with importance: more important memories get
shorter initial intervals and slower interval growth.

In-memory only -- schedule is rebuilt from activation_tracker on restart.
No SQLite persistence for the schedule itself.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ReconsolidationEntry:
    """Tracks the reconsolidation schedule for a single episode."""

    episode_id: str
    importance: int
    review_count: int = 0
    next_review_at: float = 0.0
    last_reviewed_at: float = 0.0
    retained: bool = True


class ReconsolidationScheduler:
    """Manages Ebbinghaus-style spaced reconsolidation reviews."""

    def __init__(
        self,
        config: Any,
        episodic_memory: Any = None,
    ) -> None:
        self._episodic_memory = episodic_memory
        self._enabled: bool = config.enabled
        self._base_intervals_hours: list[float] = list(config.base_intervals_hours)
        self._importance_scale_factor: float = config.importance_scale_factor
        self._max_scheduled: int = config.max_scheduled
        self._schedule: dict[str, ReconsolidationEntry] = {}

    def schedule_review(self, episode_id: str, importance: int) -> None:
        """Add an episode to the reconsolidation review schedule."""
        if not self._enabled:
            return

        if episode_id in self._schedule:
            return

        if len(self._schedule) >= self._max_scheduled:
            logger.debug(
                "AD-574: Reconsolidation schedule at capacity (%d), skipping %s",
                self._max_scheduled,
                episode_id,
            )
            return

        now = time.time()
        next_review = self._compute_next_review(review_count=0, importance=importance)
        self._schedule[episode_id] = ReconsolidationEntry(
            episode_id=episode_id,
            importance=importance,
            review_count=0,
            next_review_at=now + next_review,
            last_reviewed_at=now,
            retained=True,
        )

    def get_due_reviews(self, now: float | None = None, limit: int = 10) -> list[str]:
        """Return episode IDs due for reconsolidation review."""
        if not self._enabled:
            return []

        if now is None:
            now = time.time()

        due = [
            entry for entry in self._schedule.values()
            if entry.retained and entry.next_review_at <= now
        ]
        due.sort(key=lambda entry: entry.next_review_at)
        return [entry.episode_id for entry in due[:limit]]

    def mark_reviewed(self, episode_id: str, retained: bool) -> None:
        """Update schedule after a reconsolidation review."""
        entry = self._schedule.get(episode_id)
        if entry is None:
            return

        now = time.time()
        entry.last_reviewed_at = now

        if retained:
            entry.review_count += 1
            interval = self._compute_next_review(
                review_count=entry.review_count,
                importance=entry.importance,
            )
            entry.next_review_at = now + interval
            entry.retained = True
        else:
            entry.retained = False
            logger.info(
                "AD-574: Episode %s marked not-retained after %d reviews, flagged for pruning consideration",
                episode_id,
                entry.review_count,
            )

    def _compute_next_review(self, review_count: int, importance: int) -> float:
        """Compute the next review interval in seconds."""
        idx = min(review_count, len(self._base_intervals_hours) - 1)
        base_hours = self._base_intervals_hours[idx]
        scale = max(
            self._importance_scale_factor,
            1.0 - (importance - 1) * self._importance_scale_factor,
        )
        return base_hours * 3600.0 * scale

    @property
    def scheduled_count(self) -> int:
        """Number of episodes currently in the reconsolidation schedule."""
        return len(self._schedule)

    def snapshot(self) -> dict[str, Any]:
        """Diagnostic snapshot for monitoring."""
        retained = sum(1 for entry in self._schedule.values() if entry.retained)
        return {
            "scheduled_count": self.scheduled_count,
            "retained_count": retained,
            "not_retained_count": self.scheduled_count - retained,
            "enabled": self._enabled,
        }