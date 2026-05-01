"""AD-457: Maintenance Agent — schedules cleanup work via events."""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.events import EventType
from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)


_MAINTENANCE_TASKS: tuple[str, ...] = (
    "database_compact",
    "log_rotate",
    "cache_evict",
    "pool_rebalance",
)


class MaintenanceAgent(HeartbeatAgent):
    agent_type = "maintenance"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="maintenance",
            detail="Scheduled cleanup task coordinator",
        ),
    ]
    intent_descriptors: list[IntentDescriptor] = [
        IntentDescriptor(
            name="maintenance_request",
            params={
                "task": "task name (database_compact|log_rotate|cache_evict|pool_rebalance)",
                "scheduled_at": "epoch seconds when task should run",
            },
            description="Request a maintenance task be scheduled",
        ),
    ]
    initial_confidence = 0.95

    def __init__(
        self,
        pool: str = "engineering_maintenance",
        interval: float = 300.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(pool=pool, interval=interval, **kwargs)
        self._runtime = kwargs.get("runtime")
        self._task_intervals: dict[str, float] = kwargs.get(
            "task_intervals",
            {
                "database_compact": 86400.0,
                "log_rotate": 86400.0,
                "cache_evict": 3600.0,
                "pool_rebalance": 1800.0,
            },
        )
        self._last_scheduled: dict[str, float] = {}

    async def collect_metrics(self) -> dict[str, Any]:
        now = time.time()
        for task, interval in self._task_intervals.items():
            last = self._last_scheduled.get(task, 0.0)
            if now - last >= interval:
                self._schedule_task(task, now)
                self._last_scheduled[task] = now
        return {"last_scheduled": dict(self._last_scheduled)}

    def _schedule_task(self, task: str, scheduled_at: float) -> None:
        rt = self._runtime
        if rt is None:
            return
        try:
            rt.emit_event(
                EventType.MAINTENANCE_SCHEDULED,
                {
                    "task": task,
                    "scheduled_at": scheduled_at,
                    "agent_id": self.id,
                },
            )
        except Exception:
            logger.warning(
                "AD-457: MAINTENANCE_SCHEDULED emit failed", exc_info=True,
            )
        logger.info("AD-457: scheduled maintenance task '%s'", task)
