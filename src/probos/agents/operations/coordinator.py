"""AD-467: Coordinator -- multi-step workflow start/track via events."""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.events import EventType
from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

logger = logging.getLogger(__name__)

START_CREW_SESSION_DESCRIPTOR = IntentDescriptor(
    name="start_crew_session",
    params={
        "goal": "crew session goal",
        "success_criteria": "ordered list of success criteria",
        "expected_deliverable": "expected verified deliverable",
        "facilitator_id": "live crew facilitator id",
        "owner_ids": "optional ordered collaborator ids",
    },
    description="Start or resume one deduplicated CrewSession",
)


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
        self.intent_descriptors = list(type(self).intent_descriptors)
        runtime = self._runtime
        config = getattr(runtime, "config", None) if runtime is not None else None
        operations = getattr(config, "operations", None)
        dispatch = getattr(config, "agentic_dispatch", None)
        if (
            runtime is not None
            and getattr(operations, "enabled", False)
            and getattr(dispatch, "orchestrator_enabled", False)
        ):
            self.intent_descriptors.append(START_CREW_SESSION_DESCRIPTOR)
            self.handle_intent = self._handle_intent

    async def _handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Run the standard lifecycle for the enabled CrewSession intent."""
        if intent.intent != START_CREW_SESSION_DESCRIPTOR.name or all(
            descriptor.name != START_CREW_SESSION_DESCRIPTOR.name
            for descriptor in self.intent_descriptors
        ):
            return None
        try:
            observation = await self.perceive({
                "intent": intent.intent,
                "params": dict(intent.params),
            })
            plan = await self.decide(observation)
            outcome = await self.act(plan)
            result = await self.report(outcome)
        except (TypeError, ValueError) as exc:
            return IntentResult(
                intent_id=intent.id,
                agent_id=self.id,
                success=False,
                error=str(exc),
                confidence=0.0,
            )
        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=True,
            result=result,
            confidence=self.confidence,
        )

    async def perceive(self, intent: dict[str, Any]) -> dict[str, Any]:
        params = intent.get("params", {})
        if type(params) is not dict:
            raise ValueError("crew_session_intent_params_invalid")
        return {
            "goal": params.get("goal"),
            "success_criteria": params.get("success_criteria"),
            "expected_deliverable": params.get("expected_deliverable"),
            "facilitator_id": params.get("facilitator_id"),
            "owner_ids": params.get("owner_ids"),
        }

    async def decide(self, observation: Any) -> dict[str, Any]:
        if type(observation) is not dict:
            raise ValueError("crew_session_intent_params_invalid")
        return dict(observation)

    async def act(self, plan: Any) -> Any:
        if type(plan) is not dict or self._runtime is None:
            raise ValueError("crew_session_intent_unavailable")
        service = getattr(self._runtime, "crew_session_service", None)
        if service is None:
            raise ValueError("crew_session_intent_unavailable")
        return await service.open_or_resume(
            principal=service.captain_principal(),
            goal=plan.get("goal"),
            success_criteria=plan.get("success_criteria"),
            expected_deliverable=plan.get("expected_deliverable"),
            facilitator_id=plan.get("facilitator_id"),
            owner_ids=plan.get("owner_ids"),
        )

    async def report(self, result: Any) -> dict[str, Any]:
        return {
            "disposition": result.disposition,
            "parent_id": result.parent_id,
            "thread_id": result.thread_id,
            "state": result.state,
            "facilitator_id": result.facilitator_id,
            "owner_ids": list(result.owner_ids),
            "duplicate_resume_count": result.duplicate_resume_count,
            "scheduled": result.scheduled,
        }

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
