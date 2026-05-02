"""AD-467: Scheduler -- emits TASK_SCHEDULED events at configured cadence."""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.events import EventType
from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)


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

    async def collect_metrics(self) -> dict[str, Any]:
        now = time.time()
        for kind, cadence in self._task_cadences.items():
            last = self._last_scheduled.get(kind, 0.0)
            if now - last >= cadence:
                self._schedule(kind, now)
                self._last_scheduled[kind] = now
        return {"last_scheduled": dict(self._last_scheduled)}

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
