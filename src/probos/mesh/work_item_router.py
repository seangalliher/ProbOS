"""AD-581a v1: Bridge WORK_ITEM_CREATED -> AD-654c Dispatcher.

Subscribes to WORK_ITEM_CREATED events. For dispatchable work items, asks
DepartmentDispatcher whether to DIRECT-assign or BROADCAST, then constructs
the appropriate AD-654c TaskEvent and forwards to runtime.dispatcher.

Tier-2 log-and-degrade everywhere -- routing is best-effort. A failure here
must NEVER raise into the WorkItemStore emitter or the agent bringing up
the WorkItem.

Out of scope:
- Auto-routing every WorkItem regardless of tags (gated on
  dispatchable_tags + metadata["dispatchable"])
- TaskEvent on WORK_ITEM_UPDATED (only WORK_ITEM_CREATED)
- Cross-process / federation routing
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.activation.dispatcher import Dispatcher
    from probos.config import HybridDispatchConfig
    from probos.mesh.department_dispatcher import DepartmentDispatcher

logger = logging.getLogger(__name__)


class _WorkItemView:
    """Minimal shim exposing the only attribute DepartmentDispatcher reads."""

    __slots__ = ("assigned_to",)

    def __init__(self, assigned_to: str | None) -> None:
        self.assigned_to = assigned_to


class WorkItemRouter:
    """Routes WORK_ITEM_CREATED events to agents via AD-654c Dispatcher."""

    def __init__(
        self,
        *,
        dispatcher: "Dispatcher",
        department_dispatcher: "DepartmentDispatcher",
        registry: Any,
        config: "HybridDispatchConfig",
        emit_event: Any | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._dept_dispatcher = department_dispatcher
        self._registry = registry
        self._config = config
        self._emit = emit_event

    def is_dispatchable(self, work_item_dict: dict[str, Any]) -> bool:
        """True iff the work item carries a configured dispatchable tag OR
        has metadata["dispatchable"] == True. Conservative default."""
        tags = work_item_dict.get("tags") or []
        if any(t in self._config.dispatchable_tags for t in tags):
            return True
        meta = work_item_dict.get("metadata") or {}
        return bool(meta.get("dispatchable"))

    async def on_work_item_created(self, event: dict[str, Any]) -> None:
        """Handle the WORK_ITEM_CREATED event envelope.

        Envelope shape per the runtime emit_event surface:
          ``{"type": "work_item_created", "data": {"work_item": item.to_dict()}, "timestamp": ...}``

        Best-effort: any exception is logged at warning and swallowed.
        """
        try:
            data = event.get("data") or {}
            wi = data.get("work_item") or {}
            if not self.is_dispatchable(wi):
                return

            intent = f"work_item:{wi.get('work_type', '')}".strip(":")
            assigned = wi.get("assigned_to") or None
            tags = wi.get("tags") or []

            candidates = [
                getattr(a, "id", "")
                for a in self._registry.all()
                if getattr(a, "id", "")
            ]

            decision = self._dept_dispatcher.route(
                intent=intent,
                candidates=candidates,
                work_item=_WorkItemView(assigned),
            )

            from probos.activation.task_event import (
                task_event_broadcast,
                task_event_for_agent,
            )

            priority = self._priority_from_int(int(wi.get("priority", 3)))
            payload_out: dict[str, Any] = {
                "work_item_id": wi.get("id", ""),
                "title": wi.get("title", ""),
                "description": wi.get("description", ""),
                "work_type": wi.get("work_type", ""),
                "tags": tags,
                "metadata": wi.get("metadata") or {},
                "routing_reason": decision.reason,
                "routing_confidence": decision.confidence,
            }

            if decision.is_direct() and decision.agent_id:
                task_event = task_event_for_agent(
                    agent_id=decision.agent_id,
                    source_type="work_item_router",
                    source_id=wi.get("id", ""),
                    event_type="work_item_dispatched",
                    priority=priority,
                    payload=payload_out,
                )
                if self._emit is not None:
                    try:
                        self._emit(EventType.HYBRID_DISPATCH_DIRECT, {
                            "work_item_id": wi.get("id", ""),
                            "agent_id": decision.agent_id,
                            "confidence": decision.confidence,
                            "reason": decision.reason,
                            "department_id": decision.department_id,
                        })
                    except Exception:
                        logger.warning(
                            "AD-581a: HYBRID_DISPATCH_DIRECT emit failed",
                            exc_info=True,
                        )
            else:
                task_event = task_event_broadcast(
                    source_type="work_item_router",
                    source_id=wi.get("id", ""),
                    event_type="work_item_dispatched",
                    priority=priority,
                    payload=payload_out,
                )
                if self._emit is not None:
                    try:
                        self._emit(EventType.HYBRID_DISPATCH_BROADCAST, {
                            "work_item_id": wi.get("id", ""),
                            "confidence": decision.confidence,
                            "reason": decision.reason,
                            "department_id": decision.department_id,
                        })
                    except Exception:
                        logger.warning(
                            "AD-581a: HYBRID_DISPATCH_BROADCAST emit failed",
                            exc_info=True,
                        )

            await self._dispatcher.dispatch(task_event)
        except Exception:
            logger.warning(
                "AD-581a: WorkItemRouter.on_work_item_created failed; "
                "work_item dispatch skipped",
                exc_info=True,
            )

    @staticmethod
    def _priority_from_int(p: int) -> Any:
        """Map int priority (1=highest, 5=lowest) -> Priority enum.

        WorkItem.priority is a 1..5 int (workforce.py:559). Priority enum
        has three tiers (CRITICAL/NORMAL/LOW per types.py:85-87).
        Map: 1 -> CRITICAL, 5 -> LOW, anything else -> NORMAL.
        """
        from probos.types import Priority
        if p <= 1:
            return Priority.CRITICAL
        if p >= 5:
            return Priority.LOW
        return Priority.NORMAL
