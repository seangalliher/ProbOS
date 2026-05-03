"""AD-641c: Pure thread-priority scoring.

Deterministic, side-effect-free. Factors:
  Captain involvement       weight 0.30
  Unresolved question       weight 0.20
  Cross-department thread   weight 0.15
  Thread age (recency)      weight 0.20 (24h half-life)
  Endorsement density       weight 0.15

Score is bounded [0.0, 1.0].
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field


_HALF_LIFE_SECONDS = 86400.0  # 24h


@dataclass(frozen=True)
class ThreadPriorityInput:
    """Snapshot of a thread for scoring."""

    thread_id: str
    captain_involved: bool = False
    recent_post_bodies: list[str] = field(default_factory=list)
    participant_departments: list[str] = field(default_factory=list)
    last_post_at: float = 0.0
    endorsement_count: int = 0


@dataclass(frozen=True)
class ThreadPriorityScore:
    thread_id: str
    score: float
    factors: dict[str, float] = field(default_factory=dict)


class ThreadPriorityScorer:
    """Pure scorer. No I/O. No event emission."""

    def __init__(
        self,
        *,
        weight_captain: float = 0.30,
        weight_unresolved: float = 0.20,
        weight_cross_department: float = 0.15,
        weight_recency: float = 0.20,
        weight_endorsement: float = 0.15,
    ) -> None:
        self._w_captain = float(weight_captain)
        self._w_unresolved = float(weight_unresolved)
        self._w_cross = float(weight_cross_department)
        self._w_recency = float(weight_recency)
        self._w_endorsement = float(weight_endorsement)

    def score(self, inp: ThreadPriorityInput) -> ThreadPriorityScore:
        factors: dict[str, float] = {}
        total = 0.0

        if inp.captain_involved:
            factors["captain"] = self._w_captain
            total += self._w_captain

        if any("?" in (b or "") for b in inp.recent_post_bodies):
            factors["unresolved"] = self._w_unresolved
            total += self._w_unresolved

        unique_depts = {d for d in inp.participant_departments if d}
        if len(unique_depts) >= 2:
            factors["cross_department"] = self._w_cross
            total += self._w_cross

        recency = self._recency_factor(inp.last_post_at)
        if recency > 0.0:
            factors["recency"] = recency * self._w_recency
            total += recency * self._w_recency

        endorsement = self._endorsement_factor(inp.endorsement_count)
        if endorsement > 0.0:
            factors["endorsement"] = endorsement * self._w_endorsement
            total += endorsement * self._w_endorsement

        total = max(0.0, min(1.0, total))
        return ThreadPriorityScore(
            thread_id=inp.thread_id, score=total, factors=factors,
        )

    def _recency_factor(self, last_post_at: float) -> float:
        if last_post_at <= 0.0:
            return 0.0
        age_seconds = max(0.0, time.time() - last_post_at)
        return math.exp(-age_seconds / _HALF_LIFE_SECONDS)

    def _endorsement_factor(self, count: int) -> float:
        # Diminishing returns via 1 - exp(-0.5 * count):
        #   0 -> 0.000, 1 -> 0.393, 2 -> 0.632, 5 -> 0.918, 10 -> 0.993.
        if count <= 0:
            return 0.0
        return 1.0 - math.exp(-0.5 * float(count))
