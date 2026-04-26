"""AD-618b: BillInstance — runtime state of an activated Bill.

A BillInstance tracks one activation of a BillDefinition: which agents
are assigned to which roles, which steps have been started/completed,
and the overall lifecycle state.

Immutable reference to the BillDefinition. Mutable step states and
role assignments.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from probos.sop.schema import BillDefinition


class InstanceStatus(str, Enum):
    """Bill instance lifecycle states."""
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    """Individual step lifecycle states."""
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class StepState:
    """Runtime state of a single step within a BillInstance."""
    step_id: str
    status: StepStatus = StepStatus.PENDING
    action: str = ""
    assigned_agent_id: str | None = None
    assigned_agent_type: str | None = None
    assigned_agent_callsign: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class RoleAssignment:
    """Maps a BillRole to a concrete agent."""
    role_id: str
    agent_id: str
    agent_type: str
    callsign: str
    department: str
    assigned_at: float = field(default_factory=time.time)


@dataclass
class BillInstance:
    """Runtime state of one activation of a BillDefinition.

    Created by BillRuntime.activate(). The BillDefinition is the
    immutable reference; this tracks mutable execution state.
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    bill_id: str = ""
    bill_title: str = ""
    bill_version: int = 1
    status: InstanceStatus = InstanceStatus.PENDING
    activated_by: str = ""
    activated_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    role_assignments: dict[str, RoleAssignment] = field(default_factory=dict)
    step_states: dict[str, StepState] = field(default_factory=dict)
    activation_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API/event payloads."""
        return {
            "id": self.id,
            "bill_id": self.bill_id,
            "bill_title": self.bill_title,
            "bill_version": self.bill_version,
            "status": self.status.value,
            "activated_by": self.activated_by,
            "activated_at": self.activated_at,
            "completed_at": self.completed_at,
            "role_assignments": {
                rid: {
                    "agent_id": ra.agent_id,
                    "agent_type": ra.agent_type,
                    "callsign": ra.callsign,
                    "department": ra.department,
                }
                for rid, ra in self.role_assignments.items()
            },
            "step_states": {
                sid: {
                    "status": ss.status.value,
                    "assigned_agent_id": ss.assigned_agent_id,
                    "assigned_agent_callsign": ss.assigned_agent_callsign,
                    "started_at": ss.started_at,
                    "completed_at": ss.completed_at,
                    "error": ss.error,
                }
                for sid, ss in self.step_states.items()
            },
            "activation_data": self.activation_data,
        }

    @property
    def is_terminal(self) -> bool:
        """True if this instance is in a terminal state."""
        return self.status in (
            InstanceStatus.COMPLETED,
            InstanceStatus.FAILED,
            InstanceStatus.CANCELLED,
        )

    @property
    def progress(self) -> float:
        """Completion progress 0.0-1.0 based on step states."""
        if not self.step_states:
            return 0.0
        done = sum(
            1 for ss in self.step_states.values()
            if ss.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
        )
        return done / len(self.step_states)
