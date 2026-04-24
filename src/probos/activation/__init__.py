"""AD-654c: Activation package — TaskEvent protocol and Dispatcher.

Re-exports for clean imports::

    from probos.activation import TaskEvent, Dispatcher, task_event_for_agent
"""

from probos.activation.task_event import (
    AgentTarget,
    TaskEvent,
    task_event_broadcast,
    task_event_for_agent,
    task_event_for_department,
)
from probos.activation.dispatcher import Dispatcher, DispatchResult

__all__ = [
    "AgentTarget",
    "Dispatcher",
    "DispatchResult",
    "TaskEvent",
    "task_event_broadcast",
    "task_event_for_agent",
    "task_event_for_department",
]
