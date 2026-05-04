"""AD-522 v1: AgentCalibrationProfile — per-agent SPC control chart."""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Deque


@dataclass
class AgentCalibrationProfile:
    """Per-agent SPC control chart. AD-522 v1.

    Maintains a bounded sample window (default 100 most recent observations)
    and exposes mean (X̄), standard deviation (σ), and 3σ control limits
    (UCL/LCL) computed via stdlib ``statistics``.
    """

    agent_id: str
    sample_window: int = 100
    sigma_multiplier: float = 3.0
    _samples: Deque[float] = field(default_factory=deque)

    def __post_init__(self) -> None:
        if self._samples.maxlen != self.sample_window:
            self._samples = deque(self._samples, maxlen=self.sample_window)

    def record_observation(self, value: float) -> None:
        self._samples.append(float(value))

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    @property
    def mean(self) -> float:
        return statistics.fmean(self._samples) if self._samples else 0.0

    @property
    def stdev(self) -> float:
        return statistics.stdev(self._samples) if len(self._samples) >= 2 else 0.0

    @property
    def ucl(self) -> float:
        return self.mean + (self.sigma_multiplier * self.stdev)

    @property
    def lcl(self) -> float:
        return self.mean - (self.sigma_multiplier * self.stdev)

    def zone(self, value: float) -> str:
        """Return SPC zone label. Returns 'unknown' when insufficient samples."""
        if self.sample_count < 2 or self.stdev == 0.0:
            return "unknown"
        delta = abs(value - self.mean)
        if delta > 3.0 * self.stdev:
            return "beyond_3sigma"
        if delta > 2.0 * self.stdev:
            return "zone_a"  # 2-3σ
        if delta > 1.0 * self.stdev:
            return "zone_b"  # 1-2σ
        return "zone_c"      # within 1σ

    def recent_values(self, n: int) -> tuple[float, ...]:
        """Most recent n samples (oldest-first within the slice)."""
        if n <= 0 or not self._samples:
            return ()
        return tuple(list(self._samples)[-n:])
