"""AD-467: Coordinator -- multi-step workflow start/track via events."""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.events import EventType
from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)


class CoordinatorAgent(HeartbeatAgent):
    agent_type = "operations_coordinator"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="workflow_coordination",
            detail="Multi-step workflow dispatch and tracking",
        ),
    ]
    intent_descriptors: list[IntentDescriptor] = [
        IntentDescriptor(
            name="start_workflow",
            params={
                "workflow_name": "workflow identifier",
                "steps": "list of step names",
            },
            description="Start a multi-step workflow",
        ),
    ]
    initial_confidence = 0.95

    def __init__(
        self,
        pool: str = "operations_coordinator",
        interval: float = 60.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(pool=pool, interval=interval, **kwargs)
        self._active_workflows: dict[str, dict[str, Any]] = {}

    async def collect_metrics(self) -> dict[str, Any]:
        # Coordinator is event-driven, not poll-driven.
        return {
            "active_workflows": len(self._active_workflows),
        }

    def start_workflow(self, workflow_name: str, steps: list[str]) -> bool:
        """Record and emit a workflow start.

        Returns True on accept, False if a workflow with this name is already
        active.
        """
        if not workflow_name:
            return False
        if workflow_name in self._active_workflows:
            return False
        now = time.time()
        self._active_workflows[workflow_name] = {
            "steps": list(steps),
            "started_at": now,
        }
        rt = self._runtime
        if rt is not None:
            try:
                rt.emit_event(
                    EventType.WORKFLOW_STARTED,
                    {
                        "workflow_name": workflow_name,
                        "step_count": len(steps),
                        "started_at": now,
                        "agent_id": self.id,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-467: WORKFLOW_STARTED emit failed", exc_info=True,
                )
        logger.info(
            "AD-467: workflow '%s' started (%d steps)", workflow_name, len(steps),
        )
        return True

    def complete_workflow(self, workflow_name: str) -> bool:
        return self._active_workflows.pop(workflow_name, None) is not None
