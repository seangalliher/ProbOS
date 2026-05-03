"""AD-469: EPSCoordinator -- composes capacity tracker + budgets, emits events."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EPSReport:
    """One snapshot of ProbOS LLM capacity + allocations."""

    capacity: Any  # CapacitySummary; Any avoids circular import in dataclass typing
    allocations: dict[str, float] = field(default_factory=dict)
    overrides: dict[str, float] = field(default_factory=dict)
    saturated: bool = False


class EPSCoordinator:
    """v1 coordinator over CapacityTracker + DepartmentBudgetTable.

    Public surface:
      - ``report()`` -> ``EPSReport``
      - ``override(name, percent)`` -> ``bool`` (Captain-side; emits ``EPS_REALLOCATION``)
      - ``clear_override(name)`` -> ``bool``
      - ``check_budgets()`` -> ``list[str]`` (department names whose recent usage
        exceeded their allocation by ``over_budget_threshold``; emits
        ``EPS_BUDGET_EXCEEDED`` per offender). Consultation-only; no gating.

    v1 contract: ``check_budgets()`` returns ``[]`` until the per-agent ->
    department resolver lands in AD-469b. The empty-list contract is
    honest; ``EPS_BUDGET_EXCEEDED`` is reserved for AD-469b.
    """

    def __init__(
        self,
        *,
        capacity_tracker: Any,
        budget_table: Any,
        emit_event: Any | None = None,
        over_budget_threshold: float = 1.25,  # 25% over alloc => exceeded
    ) -> None:
        self._capacity = capacity_tracker
        self._budgets = budget_table
        self._emit_event = emit_event
        self._over_budget_threshold = over_budget_threshold

    async def report(self) -> EPSReport:
        cap = await self._capacity.summary()
        alloc = self._budgets.allocations()
        overrides = dict(getattr(self._budgets, "_overrides", {}))
        # Saturation: any single agent at >50% of total tokens, or total > 0
        # tokens_per_minute crossing a hard ceiling could be a future hint.
        saturated = bool(
            cap.total_tokens > 0
            and cap.by_agent
            and max(cap.by_agent.values()) > 0.5 * cap.total_tokens
        )
        return EPSReport(
            capacity=cap,
            allocations=alloc,
            overrides=overrides,
            saturated=saturated,
        )

    def override(self, name: str, percent: float) -> bool:
        applied = self._budgets.set_override(name, percent)
        if applied:
            self._emit_reallocation(name, percent, cleared=False)
        return applied

    def clear_override(self, name: str) -> bool:
        cleared = self._budgets.clear_override(name)
        if cleared:
            self._emit_reallocation(name, 0.0, cleared=True)
        return cleared

    async def check_budgets(self) -> list[str]:
        """Emit EPS_BUDGET_EXCEEDED for any department whose share of recent
        tokens exceeds (allocation * over_budget_threshold).

        v1 contract: returns ``[]`` until AD-469b's agent->department
        resolver lands. The empty-list-by-design is honest deferral
        (convention #7); no event is emitted from check_budgets in v1.
        """
        return []

    def _emit_reallocation(self, name: str, percent: float, *, cleared: bool) -> None:
        if self._emit_event is None:
            return
        try:
            self._emit_event(
                EventType.EPS_REALLOCATION,
                {
                    "department": name,
                    "percent": percent,
                    "cleared": cleared,
                },
            )
        except Exception:
            logger.warning(
                "AD-469: EPS_REALLOCATION emit failed (department=%s)",
                name, exc_info=True,
            )
