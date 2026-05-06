"""AD-633e: Prediction Accuracy Tracking — per-agent ring buffer + rates."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum


class PredictionOutcome(str, Enum):
    """AD-633e: Outcome categories for a single prediction lifecycle."""

    HIT = "hit"            # Cache served pre-computed analysis to a matching observation
    MISS = "miss"          # Cache lookup found nothing; fell to operational LLM
    FLUSHED = "flushed"    # Cache entry evicted before consumption
    ERROR = "error"        # Predicted intent differed from actual intent


@dataclass(frozen=True)
class AccuracyRates:
    """AD-633e: Per-agent accuracy snapshot."""

    hit_rate: float
    miss_rate: float
    flush_rate: float
    error_rate: float
    sample_count: int


class AccuracyTracker:
    """AD-633e: Per-agent ring buffer of recent prediction outcomes.

    Pure data structure — no event emission. Consumed by SpeculationBudget
    for flush-rate feedback and by introspection surfaces for observability.
    """

    def __init__(self, *, ring_size: int) -> None:
        if ring_size < 10:
            raise ValueError("ring_size must be >= 10")
        self._ring_size = int(ring_size)
        self._rings: dict[str, deque[PredictionOutcome]] = {}

    def record(self, *, agent_id: str, outcome: PredictionOutcome) -> None:
        ring = self._rings.setdefault(agent_id, deque(maxlen=self._ring_size))
        ring.append(outcome)

    def get_rates(self, agent_id: str) -> AccuracyRates:
        ring = self._rings.get(agent_id)
        if not ring:
            return AccuracyRates(0.0, 0.0, 0.0, 0.0, 0)
        total = len(ring)
        hits = sum(1 for o in ring if o == PredictionOutcome.HIT)
        misses = sum(1 for o in ring if o == PredictionOutcome.MISS)
        flushes = sum(1 for o in ring if o == PredictionOutcome.FLUSHED)
        errors = sum(1 for o in ring if o == PredictionOutcome.ERROR)
        return AccuracyRates(
            hit_rate=hits / total,
            miss_rate=misses / total,
            flush_rate=flushes / total,
            error_rate=errors / total,
            sample_count=total,
        )
