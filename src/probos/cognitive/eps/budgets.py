"""AD-469: Department budgets -- priority-weighted allocation table."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DepartmentBudget:
    """Single department's allocation entry.

    percent is a fraction of total LLM throughput in [0.0, 1.0].
    priority is a positive integer; lower priorities run first when
    Captain override forces a renormalization (AD-469b alert-aware
    reallocation will consume priority).
    """

    name: str
    percent: float
    priority: int = 5  # 1..10; lower = higher priority


@dataclass
class DepartmentBudgetTable:
    """In-memory allocation surface.

    v1 public API:
      - ``allocations()`` -> ``dict[str, float]`` -- name -> percent, summing to 1.0.
      - ``set_override(name, percent)`` -- Captain-side override; renormalizes
        remaining departments proportionally so total stays 1.0.
      - ``clear_override(name)`` -- restores the configured percent.

    Construction: from a ``list[DepartmentBudget]`` (typically built from
    ``EPSConfig.departments``). If percentages don't sum to 1.0 at
    construction time, log warning and renormalize.
    """

    departments: list[DepartmentBudget] = field(default_factory=list)
    _overrides: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        total = sum(d.percent for d in self.departments)
        if self.departments and abs(total - 1.0) > 0.01:
            logger.warning(
                "AD-469: department budget percents sum to %.3f (expected 1.0); "
                "renormalizing on read",
                total,
            )

    def allocations(self) -> dict[str, float]:
        if not self.departments:
            return {}
        # Apply overrides first; remaining departments share what's left.
        out: dict[str, float] = {}
        overridden_total = 0.0
        for d in self.departments:
            if d.name in self._overrides:
                pct = self._overrides[d.name]
                out[d.name] = pct
                overridden_total += pct
        remaining = max(0.0, 1.0 - overridden_total)
        configured_total = sum(
            d.percent for d in self.departments if d.name not in self._overrides
        )
        for d in self.departments:
            if d.name in self._overrides:
                continue
            if configured_total > 0:
                out[d.name] = remaining * (d.percent / configured_total)
            else:
                out[d.name] = 0.0
        return out

    def set_override(self, name: str, percent: float) -> bool:
        if not name or percent < 0.0 or percent > 1.0:
            return False
        if not any(d.name == name for d in self.departments):
            return False
        self._overrides[name] = percent
        return True

    def clear_override(self, name: str) -> bool:
        return self._overrides.pop(name, None) is not None
