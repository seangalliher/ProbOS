"""AD-316: AgentTask Data Model + TaskTracker Service."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class TaskType(str, Enum):
    BUILD = "build"
    DESIGN = "design"
    DIAGNOSTIC = "diagnostic"
    ASSESSMENT = "assessment"
    QUERY = "query"


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    WORKING = "working"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"


@dataclass
class TaskStep:
    """A single step in an agent task."""
    label: str
    status: StepStatus = StepStatus.PENDING
    started_at: float = 0.0
    duration_ms: float = 0.0

    def start(self) -> None:
        self.status = StepStatus.IN_PROGRESS
        self.started_at = time.time()

    def complete(self) -> None:
        self.status = StepStatus.DONE
        if self.started_at > 0:
            self.duration_ms = (time.time() - self.started_at) * 1000

    def fail(self) -> None:
        self.status = StepStatus.FAILED
        if self.started_at > 0:
            self.duration_ms = (time.time() - self.started_at) * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "status": self.status.value,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
        }


@dataclass
class AgentTask:
    """A trackable unit of agent work."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_id: str = ""
    agent_type: str = ""
    department: str = ""
    task_type: TaskType = TaskType.QUERY
    title: str = ""
    status: TaskStatus = TaskStatus.QUEUED
    steps: list[TaskStep] = field(default_factory=list)
    requires_action: bool = False
    action_type: str = ""  # "approve", "review", "respond", or ""
    started_at: float = 0.0
    completed_at: float = 0.0
    error: str = ""
    priority: int = 3
    ad_number: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def start(self) -> None:
        self.status = TaskStatus.WORKING
        self.started_at = time.time()

    def set_review(self, action_type: str = "approve") -> None:
        self.status = TaskStatus.REVIEW
        self.requires_action = True
        self.action_type = action_type

    def complete(self) -> None:
        self.status = TaskStatus.DONE
        self.completed_at = time.time()
        self.requires_action = False
        self.action_type = ""

    def fail(self, error: str = "") -> None:
        self.status = TaskStatus.FAILED
        self.completed_at = time.time()
        self.error = error
        self.requires_action = False

    def add_step(self, label: str) -> TaskStep:
        step = TaskStep(label=label)
        self.steps.append(step)
        return step

    def current_step(self) -> TaskStep | None:
        for step in self.steps:
            if step.status == StepStatus.IN_PROGRESS:
                return step
        return None

    def step_progress(self) -> tuple[int, int]:
        done = sum(1 for s in self.steps if s.status in (StepStatus.DONE, StepStatus.FAILED))
        return done, len(self.steps)

    def to_dict(self) -> dict[str, Any]:
        current, total = self.step_progress()
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "department": self.department,
            "type": self.task_type.value,
            "title": self.title,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "requires_action": self.requires_action,
            "action_type": self.action_type,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "priority": self.priority,
            "ad_number": self.ad_number,
            "metadata": self.metadata,
            "step_current": current,
            "step_total": total,
        }


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
    ) -> AgentNotification:
        n = AgentNotification(
            agent_id=agent_id,
            agent_type=agent_type,
            department=department,
            title=title,
            detail=detail,
            notification_type=notification_type,
            action_url=action_url,
        )
        self._notifications[n.id] = n
        self._emit("notification", n)
        return n

    def acknowledge(self, notification_id: str) -> bool:
        n = self._notifications.get(notification_id)
        if not n:
            return False
        n.acknowledged = True
        self._emit("notification_ack", n)
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
            self._on_event("notification_snapshot", {
                "notifications": self.snapshot(),
                "unread_count": self.unread_count(),
            })

    def _prune_acknowledged(self) -> None:
        acked = [n for n in self._notifications.values() if n.acknowledged]
        if len(acked) > self._max_acknowledged:
            for n in sorted(acked, key=lambda n: n.created_at)[:len(acked) - self._max_acknowledged]:
                del self._notifications[n.id]


class TaskTracker:
    """Central registry of active and recent agent tasks (AD-316).

    Agents register tasks, emit step updates, and mark completion.
    The tracker emits events via a callback for WebSocket broadcasting.
    """

    def __init__(self, on_event: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self._tasks: dict[str, AgentTask] = {}
        self._on_event = on_event
        self._max_done: int = 50  # keep last N completed tasks

    # --- Task lifecycle ---

    def create_task(
        self,
        *,
        agent_id: str = "",
        agent_type: str = "",
        department: str = "",
        task_type: TaskType = TaskType.QUERY,
        title: str = "",
        priority: int = 3,
        ad_number: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> AgentTask:
        task = AgentTask(
            agent_id=agent_id,
            agent_type=agent_type,
            department=department,
            task_type=task_type,
            title=title,
            priority=priority,
            ad_number=ad_number,
            metadata=metadata or {},
        )
        self._tasks[task.id] = task
        self._emit("task_created", task)
        return task

    def start_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.start()
            self._emit("task_updated", task)

    def advance_step(self, task_id: str, step_label: str) -> TaskStep | None:
        """Complete the current step (if any) and start a new one."""
        task = self._tasks.get(task_id)
        if not task:
            return None
        # Complete current in-progress step
        current = task.current_step()
        if current:
            current.complete()
        # Start new step
        step = task.add_step(step_label)
        step.start()
        self._emit("task_updated", task)
        return step

    def complete_step(self, task_id: str) -> None:
        """Complete the current in-progress step without starting a new one."""
        task = self._tasks.get(task_id)
        if task:
            current = task.current_step()
            if current:
                current.complete()
            self._emit("task_updated", task)

    def set_review(self, task_id: str, action_type: str = "approve") -> None:
        task = self._tasks.get(task_id)
        if task:
            task.set_review(action_type)
            self._emit("task_updated", task)

    def complete_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task:
            # Complete any remaining in-progress step
            current = task.current_step()
            if current:
                current.complete()
            task.complete()
            self._emit("task_updated", task)
            self._prune_done()

    def fail_task(self, task_id: str, error: str = "") -> None:
        task = self._tasks.get(task_id)
        if task:
            current = task.current_step()
            if current:
                current.fail()
            task.fail(error)
            self._emit("task_updated", task)

    # --- Queries ---

    def get_task(self, task_id: str) -> AgentTask | None:
        return self._tasks.get(task_id)

    def active_tasks(self) -> list[AgentTask]:
        return [t for t in self._tasks.values()
                if t.status in (TaskStatus.QUEUED, TaskStatus.WORKING, TaskStatus.REVIEW)]

    def needs_attention(self) -> list[AgentTask]:
        return [t for t in self._tasks.values() if t.requires_action]

    def all_tasks(self) -> list[AgentTask]:
        return list(self._tasks.values())

    def snapshot(self) -> list[dict[str, Any]]:
        """Return all tasks as dicts for WebSocket broadcast."""
        return [t.to_dict() for t in self._tasks.values()]

    # --- Internal ---

    def _emit(self, event_type: str, task: AgentTask) -> None:
        if self._on_event:
            self._on_event(event_type, {"task": task.to_dict(), "tasks": self.snapshot()})

    def _prune_done(self) -> None:
        done = [t for t in self._tasks.values()
                if t.status in (TaskStatus.DONE, TaskStatus.FAILED)]
        if len(done) > self._max_done:
            done.sort(key=lambda t: t.completed_at)
            for t in done[: len(done) - self._max_done]:
                del self._tasks[t.id]
