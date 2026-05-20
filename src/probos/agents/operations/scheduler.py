"""AD-467: Scheduler -- emits TASK_SCHEDULED events at configured cadence."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING
from typing import Any

from probos.duty_schedule import DutySchedule
from probos.events import EventType
from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

if TYPE_CHECKING:
    from probos.persistent_tasks import PersistentTaskStore

logger = logging.getLogger(__name__)


class ProactiveHeartbeatScheduler:
    """Registers proactive heartbeat jobs via the existing persistent task store."""

    _SCAN_TYPES = ("inbox", "calendar", "teams")

    def __init__(self, task_store: "PersistentTaskStore", duty_schedule: DutySchedule) -> None:
        self._task_store = task_store
        self._duty_schedule = duty_schedule

    async def ensure_jobs_registered(self) -> list[str]:
        """Create missing proactive cron jobs and return created task IDs."""
        existing = await self._task_store.list_tasks(limit=500)
        existing_hooks = {task.webhook_name for task in existing if task.webhook_name}
        created: list[str] = []
        cron_expr = self._work_hours_cron_expr()

        for scan_type in self._SCAN_TYPES:
            hook = f"proactive_scan_{scan_type}"
            if hook in existing_hooks:
                continue
            task = await self._task_store.create_task(
                intent_text=f"proactive_scan {scan_type}",
                schedule_type="cron",
                cron_expr=cron_expr,
                name=f"Proactive {scan_type} scan",
                created_by="system",
                webhook_name=hook,
            )
            created.append(task.id)
        return created

    def should_dispatch_scan(self, scan_type: str, dt: datetime | None = None) -> bool:
        """Policy gate used by heartbeat processing paths."""
        check_dt = dt or datetime.now()
        return self._duty_schedule.should_scan(scan_type, check_dt)

    def suppression_reason(self, scan_type: str, dt: datetime | None = None) -> str:
        """Audit reason code for suppressed scans."""
        check_dt = dt or datetime.now()
        return self._duty_schedule.reason_code(scan_type, check_dt)

    def _work_hours_cron_expr(self) -> str:
        start_hour = int(self._duty_schedule.work_hours.start_time.split(":", 1)[0])
        end_hour = int(self._duty_schedule.work_hours.end_time.split(":", 1)[0])
        days = self._duty_schedule.work_hours.days
        if days:
            # Python weekday (Mon=0) -> cron weekday (Mon=1 ... Sun=0)
            cron_days = ",".join(str((day + 1) % 7) for day in sorted(set(days)))
        else:
            cron_days = "*"

        # Inclusive end-hour in cron range to match Captain-visible "8-18".
        hour_range = f"{start_hour}-{end_hour}"
        return f"*/15 {hour_range} * * {cron_days}"


class SchedulerAgent(HeartbeatAgent):
    agent_type = "operations_scheduler"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="task_scheduling",
            detail="Operations-batch task scheduling via TASK_SCHEDULED events",
        ),
    ]
    intent_descriptors: list[IntentDescriptor] = [
        IntentDescriptor(
            name="schedule_task",
            params={
                "task_kind": "task category name",
                "scheduled_at": "epoch seconds when task should run",
            },
            description="Request a task be scheduled at a specific time",
        ),
    ]
    initial_confidence = 0.95

    def __init__(
        self,
        pool: str = "operations_scheduler",
        interval: float = 60.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(pool=pool, interval=interval, **kwargs)
        self._task_cadences: dict[str, float] = kwargs.get(
            "task_cadences",
            {
                "operations_audit": 3600.0,    # hourly
                "operations_summary": 86400.0,  # daily
            },
        )
        self._last_scheduled: dict[str, float] = {}
        self._proactive_jobs_registered = False

    async def collect_metrics(self) -> dict[str, Any]:
        await self._ensure_proactive_jobs_registered()
        now = time.time()
        for kind, cadence in self._task_cadences.items():
            last = self._last_scheduled.get(kind, 0.0)
            if now - last >= cadence:
                self._schedule(kind, now)
                self._last_scheduled[kind] = now
        return {"last_scheduled": dict(self._last_scheduled)}

    async def _ensure_proactive_jobs_registered(self) -> None:
        """One-time registration of proactive heartbeat jobs in persistent store."""
        if self._proactive_jobs_registered:
            return
        rt = self._runtime
        if rt is None:
            return
        task_store = getattr(rt, "persistent_task_store", None)
        duty_schedule = getattr(rt, "duty_schedule", None)
        if task_store is None or duty_schedule is None:
            return

        scheduler = ProactiveHeartbeatScheduler(task_store, duty_schedule)
        created = await scheduler.ensure_jobs_registered()
        self._proactive_jobs_registered = True
        if created:
            logger.info("AD-752: registered proactive heartbeat jobs (%d created)", len(created))

    def _schedule(self, task_kind: str, scheduled_at: float) -> None:
        rt = self._runtime
        if rt is None:
            return
        try:
            rt.emit_event(
                EventType.TASK_SCHEDULED,
                {
                    "task_kind": task_kind,
                    "scheduled_at": scheduled_at,
                    "agent_id": self.id,
                },
            )
        except Exception:
            logger.warning(
                "AD-467: TASK_SCHEDULED emit failed", exc_info=True,
            )
        logger.info("AD-467: scheduled '%s' at %.1f", task_kind, scheduled_at)
