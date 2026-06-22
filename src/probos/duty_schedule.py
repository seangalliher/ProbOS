"""Agent Duty Schedule — Plan of the Day (AD-419).

Tracks recurring duties per agent type and determines which duties
are due on each proactive cycle. Uses croniter for cron-based scheduling
and simple interval math for interval-based duties.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from probos.config import DutyPolicyConfig, PolicyWindowConfig

if TYPE_CHECKING:
    from probos.workforce import WorkItemStore

logger = logging.getLogger(__name__)


def _parse_hhmm(value: str) -> tuple[int, int]:
    """Parse HH:MM format into hour/minute tuple."""
    parts = value.split(":", 1)
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    return hour, minute


@dataclass
class PolicyWindow:
    """A daily policy window with optional weekday filtering."""

    start_time: str
    end_time: str
    days: list[int]

    @classmethod
    def from_config(cls, config: PolicyWindowConfig) -> "PolicyWindow":
        """Construct from PolicyWindowConfig."""
        return cls(
            start_time=config.start_time,
            end_time=config.end_time,
            days=list(config.days),
        )

    def is_active(self, dt: datetime) -> bool:
        """Check whether dt is inside this policy window."""
        if self.days and dt.weekday() not in self.days:
            return False

        start_hour, start_minute = _parse_hhmm(self.start_time)
        end_hour, end_minute = _parse_hhmm(self.end_time)
        start_minutes = start_hour * 60 + start_minute
        end_minutes = end_hour * 60 + end_minute
        now_minutes = dt.hour * 60 + dt.minute

        # Equal boundaries mean "all day" for policy simplicity.
        if start_minutes == end_minutes:
            return True
        if start_minutes < end_minutes:
            return start_minutes <= now_minutes < end_minutes
        # Overnight window, e.g. 19:00 -> 08:00
        return now_minutes >= start_minutes or now_minutes < end_minutes


class DutySchedule:
    """Policy gate for proactive scans (work-hours, quiet-hours, throttles)."""

    def __init__(
        self,
        config: DutyPolicyConfig,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.work_hours = PolicyWindow.from_config(config.work_hours)
        self.quiet_hours = PolicyWindow.from_config(config.quiet_hours)
        self.scan_throttle_sec: dict[str, int] = dict(config.scan_throttle_sec)
        self.daily_briefing_time = config.daily_briefing_time
        self.briefing_reminder_throttle_sec = config.briefing_reminder_throttle_sec
        self.exceptions: dict[str, PolicyWindow] = {}
        self._last_scan_at: dict[str, datetime] = {}
        self._now_fn = now_fn or datetime.now

    def set_exception(self, date_key: str, window: PolicyWindow) -> None:
        """Set date-specific override window (YYYY-MM-DD -> window)."""
        self.exceptions[date_key] = window

    def record_scan(self, scan_type: str, dt: datetime | None = None) -> None:
        """Record scan execution for throttle enforcement."""
        stamp = dt or self._now_fn()
        self._last_scan_at[scan_type] = stamp

    def should_scan(self, scan_type: str, dt: datetime | None = None) -> bool:
        """Return True when scan is permitted by policy right now."""
        check_dt = dt or self._now_fn()
        return self.reason_code(scan_type, check_dt) == "allowed"

    def next_scan_window(self, scan_type: str, dt: datetime | None = None) -> datetime:
        """Return next datetime where scan_type is allowed by policy."""
        base = dt or self._now_fn()
        # Search up to 7 days ahead at 1-minute granularity.
        for minute in range(0, 7 * 24 * 60 + 1):
            candidate = base + timedelta(minutes=minute)
            if self.should_scan(scan_type, candidate):
                return candidate
        return base

    def reason_code(self, scan_type: str, dt: datetime) -> str:
        """Return reason code for blocked scans, or "allowed"."""
        date_key = dt.date().isoformat()
        exception_window = self.exceptions.get(date_key)
        if exception_window and exception_window.is_active(dt):
            if self._is_throttled(scan_type, dt):
                return "recent_scan_throttle"
            return "allowed"

        if not self.work_hours.is_active(dt):
            return "outside_work_hours"
        if self.quiet_hours.is_active(dt):
            return "quiet_hours_active"
        if self._is_throttled(scan_type, dt):
            return "recent_scan_throttle"
        return "allowed"

    def _is_throttled(self, scan_type: str, dt: datetime) -> bool:
        throttle_seconds = int(self.scan_throttle_sec.get(scan_type, 0))
        if throttle_seconds <= 0:
            return False
        last = self._last_scan_at.get(scan_type)
        if last is None:
            return False
        return (dt - last).total_seconds() < throttle_seconds


@dataclass
class DutyStatus:
    """Tracks execution state for a single duty."""
    duty_id: str
    agent_type: str
    last_executed: float = 0.0     # time.time() of last execution
    execution_count: int = 0
    success_count: int = 0         # AD-903: outcome counters (capture wiring → AD-903a)
    failure_count: int = 0


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

    def list_duties_for_agent(self, agent_type: str) -> list[Any]:
        """AD-891: Return the agent type's configured duties without mutating state.

        Unlike :meth:`get_due_duties` (which evaluates "what is due right now"
        against execution status), this returns the *configured* schedule — the
        stable personnel-record view. It never reads or writes execution status.

        Returns duties sorted by priority descending (highest first).
        """
        duties = list(self._schedules.get(agent_type, []))
        duties.sort(key=lambda d: d.priority, reverse=True)
        return duties

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

    def record_outcome(self, agent_type: str, duty_id: str, success: bool) -> None:
        """AD-903: record a success/failure outcome for a duty.

        Increments only the outcome counters; ``execution_count`` /
        ``last_executed`` remain owned by :meth:`record_execution` so the two
        concerns stay separable (AD-903a's capture wiring decides whether a
        cycle records execution, outcome, or both). Creates the status row if
        absent.
        """
        key = self._status_key(agent_type, duty_id)
        status = self._status.get(key)
        if status is None:
            status = DutyStatus(duty_id=duty_id, agent_type=agent_type)
            self._status[key] = status
        if success:
            status.success_count += 1
        else:
            status.failure_count += 1

    def success_rate(self, agent_type: str) -> float | None:
        """AD-903: aggregate duty success rate for an agent type.

        Returns ``success / (success + failure)`` summed across the agent
        type's duties, or ``None`` when no outcomes have been recorded yet (so
        callers can distinguish "no data" from "0% success").
        """
        success = 0
        failure = 0
        for status in self._status.values():
            if status.agent_type == agent_type:
                success += status.success_count
                failure += status.failure_count
        total = success + failure
        if total == 0:
            return None
        return success / total

    async def emit_due_duties_as_work_items(
        self,
        agent_type: str,
        work_item_store: "WorkItemStore",
    ) -> list[str]:
        """AD-500: Emit one duty WorkItem per due DutyDefinition. Producer side only.

        Returns list of WorkItem IDs created. Does NOT call record_execution
        (that remains on the legacy path until AD-500a-1).
        """
        due = self.get_due_duties(agent_type)
        work_item_ids: list[str] = []
        for duty in due:
            item = await work_item_store.create_work_item(
                work_type="duty",
                assigned_to=agent_type,
                title=getattr(duty, "description", duty.duty_id) or duty.duty_id,
                metadata={
                    "duty_id": duty.duty_id,
                    "agent_type": agent_type,
                },
            )
            work_item_ids.append(item.id)
        return work_item_ids

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
