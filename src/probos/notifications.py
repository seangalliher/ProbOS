"""AD-323/AD-501: Agent → Captain notification queue.

Moved from `probos.task_tracker` in AD-501 (TaskTracker deprecation).
NotificationQueue + AgentNotification are unchanged from their pre-AD-501
form; only the import path has moved.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from probos.events import EventType


@dataclass
class AgentNotification:
    """A notification emitted by any agent for the Captain (AD-323)."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_id: str = ""
    agent_type: str = ""
    department: str = ""
    notification_type: str = "info"  # "info" | "action_required" | "error"
    title: str = ""
    detail: str = ""
    action_url: str = ""  # optional link context (e.g. task_id, intent)
    # AD-1053: optional actionable affordance. When present, the HXI renders an
    # "Accept" button; POST /api/notifications/{id}/accept dispatches the carried
    # intent into the mesh. Shape (all keys optional except a non-empty "intent"
    # is required to dispatch):
    #   {"label": str,             # button text (Ship's-Computer voiced)
    #    "intent": str,            # IntentMessage.intent to dispatch
    #    "params": dict,           # IntentMessage.params
    #    "target_agent_id": str}   # optional; targeted send() vs broadcast()
    # The producer authors the action; the client only references a notification
    # id (it cannot inject an intent). Default None -> no button, byte-identical
    # to pre-AD-1053 notifications.
    suggested_action: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    acknowledged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "department": self.department,
            "notification_type": self.notification_type,
            "title": self.title,
            "detail": self.detail,
            "action_url": self.action_url,
            "suggested_action": self.suggested_action,
            "created_at": self.created_at,
            "acknowledged": self.acknowledged,
        }


class NotificationQueue:
    """Persistent notification queue for agent→Captain notifications (AD-323)."""

    def __init__(self, on_event: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self._notifications: dict[str, AgentNotification] = {}
        self._on_event = on_event
        self._max_acknowledged: int = 50  # keep last 50 acked for history

    def notify(
        self,
        agent_id: str,
        agent_type: str,
        department: str,
        title: str,
        detail: str = "",
        notification_type: str = "info",
        action_url: str = "",
        suggested_action: dict[str, Any] | None = None,
    ) -> AgentNotification:
        n = AgentNotification(
            agent_id=agent_id,
            agent_type=agent_type,
            department=department,
            title=title,
            detail=detail,
            notification_type=notification_type,
            action_url=action_url,
            suggested_action=suggested_action,
        )
        self._notifications[n.id] = n
        self._emit(EventType.NOTIFICATION, n)
        return n

    def get(self, notification_id: str) -> AgentNotification | None:
        """Return a notification by id, or None if not present (AD-1053)."""
        return self._notifications.get(notification_id)

    def acknowledge(self, notification_id: str) -> bool:
        n = self._notifications.get(notification_id)
        if not n:
            return False
        n.acknowledged = True
        self._emit(EventType.NOTIFICATION_ACK, n)
        self._prune_acknowledged()
        return True

    def acknowledge_all(self) -> int:
        count = 0
        for n in self._notifications.values():
            if not n.acknowledged:
                n.acknowledged = True
                count += 1
        if count > 0:
            self._emit_snapshot()
        self._prune_acknowledged()
        return count

    def snapshot(self) -> list[dict[str, Any]]:
        return [n.to_dict() for n in sorted(
            self._notifications.values(),
            key=lambda n: n.created_at,
            reverse=True,
        )]

    def unread_count(self) -> int:
        return sum(1 for n in self._notifications.values() if not n.acknowledged)

    def _emit(self, event_type: str, n: AgentNotification) -> None:
        if self._on_event:
            self._on_event(event_type, {
                "notification": n.to_dict(),
                "notifications": self.snapshot(),
                "unread_count": self.unread_count(),
            })

    def _emit_snapshot(self) -> None:
        if self._on_event:
            self._on_event(EventType.NOTIFICATION_SNAPSHOT, {
                "notifications": self.snapshot(),
                "unread_count": self.unread_count(),
            })

    def _prune_acknowledged(self) -> None:
        acked = [n for n in self._notifications.values() if n.acknowledged]
        if len(acked) > self._max_acknowledged:
            for n in sorted(acked, key=lambda n: n.created_at)[:len(acked) - self._max_acknowledged]:
                del self._notifications[n.id]
