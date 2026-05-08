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

    # ------------------------------------------------------------------
    # AD-522b: Process capability indices Cp / Cpk
    # ------------------------------------------------------------------

    def cp(self, *, lower_spec: float, upper_spec: float) -> float | None:
        """AD-522b: process potential capability index Cp.

        Returns ``None`` when stdev is zero or insufficient samples.
        Cp >= 1.33 conventionally indicates a capable process.
        """
        if self.stdev == 0.0 or self.sample_count < 2:
            return None
        if upper_spec <= lower_spec:
            return None
        return (upper_spec - lower_spec) / (6.0 * self.stdev)

    def cpk(self, *, lower_spec: float, upper_spec: float) -> float | None:
        """AD-522b: process performance capability index Cpk.

        Cpk accounts for process centering. Returns ``None`` when stdev
        is zero or insufficient samples. Cpk < Cp indicates the process
        is off-center within its specification range.
        """
        if self.stdev == 0.0 or self.sample_count < 2:
            return None
        if upper_spec <= lower_spec:
            return None
        upper_dist = (upper_spec - self.mean) / (3.0 * self.stdev)
        lower_dist = (self.mean - lower_spec) / (3.0 * self.stdev)
        return min(upper_dist, lower_dist)

    def capability_summary(
        self, *, lower_spec: float, upper_spec: float,
    ) -> dict[str, float | str | None]:
        """AD-522b: structured capability snapshot.

        Returns ``{cp, cpk, classification}`` where classification is
        derived from Cpk per Juran/AIAG conventions:
            >= 1.67  excellent
            >= 1.33  capable
            >= 1.00  marginal
            <  1.00  inadequate
        """
        cp = self.cp(lower_spec=lower_spec, upper_spec=upper_spec)
        cpk = self.cpk(lower_spec=lower_spec, upper_spec=upper_spec)
        if cpk is None:
            classification: str = "unknown"
        elif cpk >= 1.67:
            classification = "excellent"
        elif cpk >= 1.33:
            classification = "capable"
        elif cpk >= 1.00:
            classification = "marginal"
        else:
            classification = "inadequate"
        return {"cp": cp, "cpk": cpk, "classification": classification}


# ---------------------------------------------------------------------------
# AD-522c: SPC -> graduated-response zone mapping
# ---------------------------------------------------------------------------


def spc_zone_to_response_color(zone: str) -> str:
    """Map an SPC zone label to AD-506 graduated-response color.

    zone_c (within 1σ)        -> green
    zone_b (1-2σ)             -> green
    zone_a (2-3σ)             -> amber
    beyond_3sigma             -> red
    unknown                   -> green (insufficient data; default safe)
    """
    if zone == "beyond_3sigma":
        return "red"
    if zone == "zone_a":
        return "amber"
    return "green"


def graduated_response_for_value(
    profile: "AgentCalibrationProfile", value: float,
) -> dict[str, str]:
    """One-shot helper: zone + color for an observation against a profile."""
    z = profile.zone(value)
    return {"zone": z, "color": spc_zone_to_response_color(z)}
