"""AD-654c: TaskEvent protocol — universal activation event format.

TaskEvent is the lingua franca for all activation sources in UAAA.
Every source (ward room, game, agent, kanban, external) creates a
TaskEvent; the Dispatcher routes it to the right agent(s).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from probos.types import Priority


@dataclass(frozen=True)
class AgentTarget:
    """Specifies who should receive a TaskEvent.

    Exactly one of agent_id, capability, department_id must be set.
    If broadcast=True, all crew agents receive the event.
    """

    agent_id: str | None = None
    capability: str | None = None
    department_id: str | None = None
    broadcast: bool = False

    def __post_init__(self) -> None:
        """Validate exactly one targeting mode is set."""
        modes = sum([
            self.agent_id is not None,
            self.capability is not None,
            self.department_id is not None,
            self.broadcast,
        ])
        if modes != 1:
            raise ValueError(
                f"AgentTarget must specify exactly one of agent_id, capability, "
                f"department_id, or broadcast=True (got {modes} modes)"
            )


@dataclass(frozen=True)
class TaskEvent:
    """Universal activation event — the lingua franca for all event sources.

    Every activation source (ward room, game, agent, captain, kanban, external)
    creates a TaskEvent. The Dispatcher routes it to the right agent(s).

    Note: frozen=True prevents field reassignment but does NOT prevent
    mutation of the payload dict's contents. Consumers MUST treat
    payload as read-only. (MappingProxyType considered but adds
    serialization friction for minimal gain at this layer.)
    """

    source_type: str
    source_id: str
    event_type: str
    priority: Priority
    target: AgentTarget
    payload: dict[str, Any]
    thread_id: str | None = None
    deadline: float | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.monotonic)


# ── Factory functions ────────────────────────────────────────────


def task_event_for_agent(
    *,
    agent_id: str,
    source_type: str,
    source_id: str,
    event_type: str,
    priority: Priority,
    payload: dict[str, Any],
    thread_id: str | None = None,
    deadline: float | None = None,
) -> TaskEvent:
    """Create a TaskEvent targeted at a specific agent."""
    return TaskEvent(
        source_type=source_type,
        source_id=source_id,
        event_type=event_type,
        priority=priority,
        target=AgentTarget(agent_id=agent_id),
        payload=payload,
        thread_id=thread_id,
        deadline=deadline,
    )


def task_event_for_department(
    *,
    department_id: str,
    source_type: str,
    source_id: str,
    event_type: str,
    priority: Priority,
    payload: dict[str, Any],
    thread_id: str | None = None,
) -> TaskEvent:
    """Create a TaskEvent for all agents in a department."""
    return TaskEvent(
        source_type=source_type,
        source_id=source_id,
        event_type=event_type,
        priority=priority,
        target=AgentTarget(department_id=department_id),
        payload=payload,
        thread_id=thread_id,
    )


def task_event_broadcast(
    *,
    source_type: str,
    source_id: str,
    event_type: str,
    priority: Priority,
    payload: dict[str, Any],
    thread_id: str | None = None,
) -> TaskEvent:
    """Create a TaskEvent for all crew agents."""
    return TaskEvent(
        source_type=source_type,
        source_id=source_id,
        event_type=event_type,
        priority=priority,
        target=AgentTarget(broadcast=True),
        payload=payload,
        thread_id=thread_id,
    )
