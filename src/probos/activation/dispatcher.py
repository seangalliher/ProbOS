"""AD-654c: Dispatcher — routes TaskEvents to agent cognitive queues.

Resolves abstract targets (capability, department, broadcast) to
concrete agent IDs using the registry and ontology. Converts
TaskEvents to IntentMessages for cognitive queue consumption.

Does NOT replace IntentBus — they coexist. IntentBus handles
request/reply (send) and legacy dispatch_async. Dispatcher handles
fire-and-forget TaskEvent routing. AD-654d migrates existing
emitters from IntentBus to Dispatcher.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from probos.activation.task_event import AgentTarget, TaskEvent
from probos.types import IntentMessage

logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    """Result of dispatching a TaskEvent."""

    event_id: str
    target_count: int
    accepted: int
    rejected: int
    unroutable: int
    agent_ids: list[str] = field(default_factory=list)
    dispatch_ms: float = 0.0


class Dispatcher:
    """Routes TaskEvents to agent cognitive queues (AD-654c).

    Resolves abstract targets (capability, department, broadcast) to
    concrete agent IDs using the registry and ontology. Converts
    TaskEvents to IntentMessages for cognitive queue consumption.

    Does NOT replace IntentBus — they coexist. IntentBus handles
    request/reply (send) and legacy dispatch_async. Dispatcher handles
    fire-and-forget TaskEvent routing. AD-654d migrates existing
    emitters from IntentBus to Dispatcher.
    """

    def __init__(
        self,
        *,
        registry: Any,
        ontology: Any | None,
        get_queue: Callable[[str], Any | None],
        dispatch_async_fn: Callable[..., Any] | None = None,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._registry = registry
        self._ontology = ontology
        self._get_queue = get_queue
        self._dispatch_async_fn = dispatch_async_fn
        self._emit_event = emit_event
        self._pending_fallback_tasks: set[asyncio.Task[Any]] = set()

    async def dispatch(self, event: TaskEvent) -> DispatchResult:
        """Route a TaskEvent to the appropriate agent(s).

        Resolution order:
        1. Resolve AgentTarget → list of agent_ids
        2. For each agent: convert TaskEvent → IntentMessage
        3. Enqueue into cognitive queue (via get_queue callback)
        4. Fallback: dispatch_async_fn for agents without queues
        5. If no dispatch_async_fn: fire-and-forget via asyncio.create_task()

        Does NOT check cooldowns, round tracking, or EA trust gates.
        Those are ward-room-specific concerns that stay in the router.
        The Dispatcher is a low-level routing primitive.
        """
        t0 = time.monotonic()

        agent_ids = self._resolve_target(event.target)
        target_count = len(agent_ids)

        if target_count == 0:
            dispatch_ms = (time.monotonic() - t0) * 1000
            reason = self._unroutable_reason(event.target)
            logger.warning(
                "AD-654c: TaskEvent %s unroutable — %s",
                event.event_type, reason,
            )
            if self._emit_event:
                self._emit_event("task_event_unroutable", {
                    "event_id": event.id,
                    "event_type": event.event_type,
                    "target": self._target_summary(event.target),
                    "reason": reason,
                })
            return DispatchResult(
                event_id=event.id,
                target_count=0,
                accepted=0,
                rejected=0,
                unroutable=1,
                dispatch_ms=dispatch_ms,
            )

        if event.target.broadcast:
            logger.info(
                "AD-654c: Dispatching %s to %d crew agents",
                event.event_type, target_count,
            )

        accepted = 0
        rejected = 0
        dispatched_ids: list[str] = []

        for agent_id in agent_ids:
            intent = self._to_intent_message(event, agent_id)
            queue = self._get_queue(agent_id)

            if queue is not None:
                ok = queue.enqueue(intent, event.priority)
                if ok:
                    accepted += 1
                    dispatched_ids.append(agent_id)
                else:
                    rejected += 1
            elif self._dispatch_async_fn is not None:
                try:
                    await self._dispatch_async_fn(intent)
                    accepted += 1
                    dispatched_ids.append(agent_id)
                except Exception:
                    logger.debug(
                        "AD-654c: dispatch_async fallback failed for %s",
                        agent_id, exc_info=True,
                    )
                    rejected += 1
            else:
                # Last-resort: fire-and-forget via create_task
                agent = self._registry.get(agent_id)
                if agent and hasattr(agent, "handle_intent"):
                    task = asyncio.create_task(agent.handle_intent(intent))
                    self._pending_fallback_tasks.add(task)
                    task.add_done_callback(self._pending_fallback_tasks.discard)
                    accepted += 1
                    dispatched_ids.append(agent_id)
                else:
                    rejected += 1

        dispatch_ms = (time.monotonic() - t0) * 1000

        if self._emit_event:
            self._emit_event("task_event_dispatched", {
                "event_id": event.id,
                "event_type": event.event_type,
                "source_type": event.source_type,
                "target_mode": self._target_summary(event.target),
                "agent_count": target_count,
                "accepted": accepted,
                "rejected": rejected,
            })

        return DispatchResult(
            event_id=event.id,
            target_count=target_count,
            accepted=accepted,
            rejected=rejected,
            unroutable=0,
            agent_ids=dispatched_ids,
            dispatch_ms=dispatch_ms,
        )

    def _to_intent_message(self, event: TaskEvent, agent_id: str) -> IntentMessage:
        """Convert TaskEvent to IntentMessage for cognitive queue consumption.

        The cognitive queue (AD-654b) processes IntentMessages. Until the
        queue is refactored to accept TaskEvents directly (future AD),
        the Dispatcher converts at the boundary.
        """
        return IntentMessage(
            intent=event.event_type,
            params={
                **event.payload,
                "_task_event_id": event.id,
                "_source_type": event.source_type,
                "_source_id": event.source_id,
            },
            context="",
            target_agent_id=agent_id,
            ttl_seconds=max(event.deadline - time.monotonic(), 1.0) if event.deadline else 120.0,
        )

    def _resolve_target(self, target: AgentTarget) -> list[str]:
        """Resolve AgentTarget to concrete agent IDs.

        Returns list of agent_ids. May be empty if no agents match.

        When ontology is None (e.g., tests, minimal startup):
        - agent_id targeting works normally (registry-only)
        - capability targeting works normally (registry-only)
        - department targeting returns [] (requires ontology)
        - broadcast returns all agents via is_crew_agent(a, None) fallback
        """
        if target.agent_id:
            agent = self._registry.get(target.agent_id)
            return [target.agent_id] if agent else []

        if target.capability:
            agents = self._registry.get_by_capability(target.capability)
            return [a.id for a in agents]

        if target.department_id:
            from probos.crew_utils import is_crew_agent
            return [
                a.id for a in self._registry.all()
                if is_crew_agent(a, self._ontology)
                and self._ontology
                and self._ontology.get_agent_department(a.agent_type) == target.department_id
            ]

        if target.broadcast:
            from probos.crew_utils import is_crew_agent
            return [
                a.id for a in self._registry.all()
                if is_crew_agent(a, self._ontology)
            ]

        return []

    @staticmethod
    def _target_summary(target: AgentTarget) -> str:
        """Human-readable summary of a target for logging/events."""
        if target.agent_id:
            return f"agent:{target.agent_id}"
        if target.capability:
            return f"capability:{target.capability}"
        if target.department_id:
            return f"department:{target.department_id}"
        if target.broadcast:
            return "broadcast"
        return "unknown"

    @staticmethod
    def _unroutable_reason(target: AgentTarget) -> str:
        """Reason string for unroutable events."""
        if target.agent_id:
            return f"agent {target.agent_id} not found in registry"
        if target.capability:
            return f"no agents with capability '{target.capability}'"
        if target.department_id:
            return f"no crew agents in department '{target.department_id}'"
        if target.broadcast:
            return "no crew agents registered"
        return "invalid target"
