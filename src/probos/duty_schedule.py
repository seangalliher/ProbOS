"""Agent Duty Schedule — Plan of the Day (AD-419).

Tracks recurring duties per agent type and determines which duties
are due on each proactive cycle. Uses croniter for cron-based scheduling
and simple interval math for interval-based duties.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DutyStatus:
    """Tracks execution state for a single duty."""
    duty_id: str
    agent_type: str
    last_executed: float = 0.0     # time.time() of last execution
    execution_count: int = 0


class DutyScheduleTracker:
    """Tracks duty execution and determines which duties are due.

    The tracker is in-memory — on restart, all duties show as "never executed"
    and will fire on their first eligible cycle. This is correct behavior:
    a fresh start means fresh duties.
    """

    def __init__(self, schedules: dict[str, list[Any]]) -> None:
        """Initialize with schedule config.

        Args:
            schedules: dict mapping agent_type -> list of DutyDefinition objects
        """
        self._schedules = schedules
        self._status: dict[str, DutyStatus] = {}  # keyed by "agent_type:duty_id"

    def _status_key(self, agent_type: str, duty_id: str) -> str:
        return f"{agent_type}:{duty_id}"

    def get_due_duties(self, agent_type: str) -> list[Any]:
        """Return list of DutyDefinition objects that are currently due.

        A duty is due if:
        - cron-based: the next fire time after last_executed is <= now
        - interval-based: now - last_executed >= interval_seconds
        - never executed: always due (first cycle after startup)

        Returns duties sorted by priority (highest first).
        """
        duties = self._schedules.get(agent_type, [])
        if not duties:
            return []

        now = time.time()
        due: list[Any] = []

        for duty in duties:
            key = self._status_key(agent_type, duty.duty_id)
            status = self._status.get(key)
            last = status.last_executed if status else 0.0

            is_due = False

            if duty.cron:
                try:
                    from croniter import croniter
                    cron = croniter(duty.cron, last)
                    next_fire = cron.get_next(float)
                    if next_fire <= now:
                        is_due = True
                except Exception:
                    logger.debug("Invalid cron for duty %s: %s", duty.duty_id, duty.cron, exc_info=True)
            elif duty.interval_seconds > 0:
                if now - last >= duty.interval_seconds:
                    is_due = True

            if is_due:
                due.append(duty)

        # Sort by priority descending (highest first)
        due.sort(key=lambda d: d.priority, reverse=True)
        return due

    def record_execution(self, agent_type: str, duty_id: str) -> None:
        """Record that a duty was executed."""
        key = self._status_key(agent_type, duty_id)
        status = self._status.get(key)
        if status:
            status.last_executed = time.time()
            status.execution_count += 1
        else:
            self._status[key] = DutyStatus(
                duty_id=duty_id,
                agent_type=agent_type,
                last_executed=time.time(),
                execution_count=1,
            )

    def get_status(self, agent_type: str) -> list[dict[str, Any]]:
        """Return status of all duties for an agent type (for state snapshot)."""
        duties = self._schedules.get(agent_type, [])
        result = []
        for duty in duties:
            key = self._status_key(agent_type, duty.duty_id)
            status = self._status.get(key)
            result.append({
                "duty_id": duty.duty_id,
                "description": duty.description,
                "last_executed": status.last_executed if status else 0.0,
                "execution_count": status.execution_count if status else 0,
                "priority": duty.priority,
            })
        return result
