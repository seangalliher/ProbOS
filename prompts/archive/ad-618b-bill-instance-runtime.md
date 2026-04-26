# AD-618b: Bill Instance + Runtime

**Issue:** #204 (AD-618 umbrella)
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-618a (Bill Schema + Parser — must be built first), AD-566 (Qualification Programs — complete), AD-429/AD-595a-d (BilletRegistry — complete), AD-496-498 (Workforce Scheduling — complete), AD-423 (Tool Registry — complete)
**Files:** `src/probos/sop/instance.py` (NEW), `src/probos/sop/runtime.py` (NEW), `src/probos/sop/__init__.py` (EDIT — add exports), `src/probos/events.py` (EDIT — add Bill event types), `src/probos/config.py` (EDIT — add BillConfig), `tests/test_ad618b_bill_instance_runtime.py` (NEW)

## Problem

AD-618a delivered the Bill schema (BillDefinition, BillStep, BillRole) and parser. There is no runtime layer to **activate** a Bill — instantiate it, assign agents to roles, track step progression, and emit lifecycle events. Without this, Bills are inert documents.

AD-618b delivers the Bill Instance and Runtime — the execution substrate that brings Bills to life.

**Navy model:** The Watch, Quarter, and Station Bill (WQSB) is a matrix that maps every sailor to a station in every bill. The "set condition" command activates a bill and sends everyone to their assigned station. ProbOS's runtime WQSB computes assignments dynamically from live agent state (trust, qualifications, workload, department).

**Architectural principle:** Bills are "reference, not engine." The runtime presents the bill to agents as structured context — agents consult the SOP with judgment, they are not puppeted by a state machine. Step transitions are tracked for observability, but the agent decides how to execute each step.

**Step ordering caveat:** BillRuntime tracks step states but does **not** enforce step ordering in v1. Steps can be started and completed in any order. Sequencing constraints (prerequisites, gateways) are future — AD-618e's Cognitive JIT bridge will consult step order, but the runtime itself is order-agnostic.

## Design

AD-618b delivers four things:

1. **BillInstance dataclass** (`instance.py`) — tracks a single activation of a BillDefinition: assigned roles, step states, lifecycle timestamps.
2. **BillRuntime service** (`runtime.py`) — activates bills, computes role assignments (WQSB), tracks step progression, emits lifecycle events.
3. **Event types** — `BILL_ACTIVATED`, `BILL_STEP_STARTED`, `BILL_STEP_COMPLETED`, `BILL_COMPLETED`, `BILL_FAILED`, `BILL_CANCELLED`, `BILL_ROLE_ASSIGNED`, `BILL_STEP_FAILED`.
4. **Config** — `BillConfig` with assignment strategy parameters, timeouts, concurrency limits.

**What this does NOT include:**
- Built-in bill YAML files (AD-618c)
- HXI dashboard (AD-618d)
- Cognitive JIT bridge (AD-618e)
- Ward Room notifications to assigned agents (future — agents discover their assignments via the Bill Instance, not push notifications in this AD)
- Workforce Scheduling integration (future — BillRuntime does not create WorkItems; that bridge is a later AD)

---

## Section 1: Add Event Types

**File:** `src/probos/events.py` (EDIT)

Add Bill System event types to the `EventType` enum. Place after the existing `BOOT_CAMP_TIMEOUT` entry (around line 168):

```python
    # Bill System (AD-618b)
    BILL_ACTIVATED = "bill_activated"              # Bill instance created and roles assigned
    BILL_STEP_STARTED = "bill_step_started"        # Agent began a step
    BILL_STEP_COMPLETED = "bill_step_completed"    # Agent finished a step (success or skip)
    BILL_STEP_FAILED = "bill_step_failed"          # Step failed (timeout, error, agent unavailable)
    BILL_COMPLETED = "bill_completed"              # All steps done — bill instance terminal
    BILL_FAILED = "bill_failed"                    # Bill aborted (critical step failed, timeout)
    BILL_CANCELLED = "bill_cancelled"              # Bill cancelled by authority (intentional stop)
    BILL_ROLE_ASSIGNED = "bill_role_assigned"       # Agent assigned to a role in a bill instance
```

---

## Section 2: Add BillConfig

**File:** `src/probos/config.py` (EDIT)

Add a `BillConfig` class. Follow the existing pattern — all config classes in `config.py` extend Pydantic `BaseModel` (NOT `@dataclass`). Place among the other config classes (e.g., near `QualificationConfig`):

```python
class BillConfig(BaseModel):
    """Configuration for the Bill System runtime (AD-618b)."""

    # Maximum concurrent bill instances (0 = unlimited)
    max_concurrent_instances: int = 10

    # Default step timeout in seconds (0 = no timeout)
    default_step_timeout_seconds: float = 300.0

    # Whether to allow bills to activate with unfilled roles
    # If False, activation fails if any role cannot be assigned
    allow_partial_assignment: bool = False
```

Add `bill: BillConfig = BillConfig()` to the `SystemConfig` class (Pydantic `BaseModel` pattern — direct default, not `field(default_factory=...)`).

---

## Section 3: Create `src/probos/sop/instance.py`

**File:** `src/probos/sop/instance.py` (NEW)

This module defines the `BillInstance` and `StepState` dataclasses — the runtime state of an activated bill.

```python
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
    PENDING = "pending"          # Created but roles not yet assigned
    ACTIVE = "active"            # Roles assigned, execution in progress
    COMPLETED = "completed"      # All steps done successfully
    FAILED = "failed"            # Aborted due to critical failure
    CANCELLED = "cancelled"      # Manually cancelled by authority


class StepStatus(str, Enum):
    """Individual step lifecycle states."""
    PENDING = "pending"          # Not yet started
    ACTIVE = "active"            # Agent is executing this step
    COMPLETED = "completed"      # Step finished successfully
    SKIPPED = "skipped"          # Step skipped (XOR branch not taken)
    FAILED = "failed"            # Step failed (timeout, error)
    BLOCKED = "blocked"          # Waiting on prerequisite


@dataclass
class StepState:
    """Runtime state of a single step within a BillInstance."""
    step_id: str
    status: StepStatus = StepStatus.PENDING
    action: str = ""                        # BillStep.action snapshot (set at start_step)
    assigned_agent_id: str | None = None    # Agent executing this step
    assigned_agent_type: str | None = None  # Agent type (for AD-618e JIT bridge)
    assigned_agent_callsign: str | None = None
    started_at: float | None = None         # wall-clock timestamp (time.time())
    completed_at: float | None = None       # wall-clock timestamp (time.time())
    result: dict[str, Any] = field(default_factory=dict)  # Step outputs
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
    bill_id: str = ""                       # BillDefinition.bill slug
    bill_title: str = ""                    # BillDefinition.title (snapshot)
    bill_version: int = 1                   # BillDefinition.version (snapshot)
    status: InstanceStatus = InstanceStatus.PENDING
    activated_by: str = ""                  # Agent or authority who activated
    activated_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    # Role assignments (computed by WQSB at activation)
    role_assignments: dict[str, RoleAssignment] = field(default_factory=dict)
    # Key = role_id from BillDefinition.roles

    # Step states (one per BillStep in the definition)
    step_states: dict[str, StepState] = field(default_factory=dict)
    # Key = step_id from BillDefinition.steps

    # Activation data (passed in when bill is activated)
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
        """Completion progress 0.0–1.0 based on step states."""
        if not self.step_states:
            return 0.0
        done = sum(
            1 for ss in self.step_states.values()
            if ss.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
        )
        return done / len(self.step_states)
```

---

## Section 4: Create `src/probos/sop/runtime.py`

**File:** `src/probos/sop/runtime.py` (NEW)

The BillRuntime service — activates bills, assigns roles, tracks steps.

```python
"""AD-618b: BillRuntime — activates Bills and tracks execution.

Ship's Computer infrastructure service. No agent identity.
Provides: activate(), advance_step(), complete_step(), fail_step(),
cancel(), get_instance(), list_instances().

Role assignment (WQSB) queries BilletRegistry for candidates, filters
by qualification (QualificationStore), ranks by trust/workload, assigns
the best-fit agent to each role.

Events emitted via late-bound callback (same pattern as ToolRegistry,
BilletRegistry).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from probos.config import BillConfig
from probos.events import EventType
from probos.sop.instance import (
    BillInstance,
    InstanceStatus,
    RoleAssignment,
    StepState,
    StepStatus,
)
from probos.sop.schema import BillDefinition, GatewayType

logger = logging.getLogger(__name__)


class BillActivationError(Exception):
    """Raised when a bill cannot be activated."""


class BillRuntime:
    """Activates BillDefinitions into BillInstances and tracks execution.

    Parameters
    ----------
    config : BillConfig
        Runtime configuration (timeouts, assignment strategy, etc.).
    billet_registry : BilletRegistry | None
        For role assignment queries. Optional — if None, role assignment
        is manual (caller must provide assignments).
    emit_event_fn : callable | None
        ``(EventType, dict) -> None`` for lifecycle events.
    """

    def __init__(
        self,
        config: BillConfig | None = None,
        billet_registry: Any = None,
        emit_event_fn: Callable[[EventType, dict[str, Any]], None] | None = None,
    ) -> None:
        from probos.config import BillConfig as _BC
        self._config = config or _BC()
        self._billet_registry = billet_registry
        self._emit_event_fn = emit_event_fn
        self._instances: dict[str, BillInstance] = {}  # instance_id → BillInstance

    def set_event_callback(
        self, fn: Callable[[EventType, dict[str, Any]], None],
    ) -> None:
        """Late-bind event emission (same pattern as BilletRegistry)."""
        self._emit_event_fn = fn

    def set_billet_registry(self, registry: Any) -> None:
        """Late-bind BilletRegistry."""
        self._billet_registry = registry

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    async def activate(
        self,
        bill: BillDefinition,
        activated_by: str = "captain",
        activation_data: dict[str, Any] | None = None,
        *,
        role_overrides: dict[str, str] | None = None,
    ) -> BillInstance:
        """Activate a Bill — create instance, assign roles, initialize steps.

        Parameters
        ----------
        bill : BillDefinition
            The parsed bill to activate.
        activated_by : str
            Who activated (agent_id, "captain", or authority title).
        activation_data : dict
            Data passed to the bill (available as step inputs via
            source="activation_data").
        role_overrides : dict
            Manual role assignments: {role_id: agent_id}. Bypasses
            WQSB for specified roles. Used for targeted activations.

        Returns
        -------
        BillInstance

        Raises
        ------
        BillActivationError
            If max concurrent instances exceeded, or required roles
            cannot be assigned and allow_partial_assignment is False.
        """
        # Concurrency limit
        active_count = sum(
            1 for inst in self._instances.values()
            if inst.status == InstanceStatus.ACTIVE
        )
        if self._config.max_concurrent_instances > 0 and active_count >= self._config.max_concurrent_instances:
            raise BillActivationError(
                f"Max concurrent bill instances ({self._config.max_concurrent_instances}) reached"
            )

        instance = BillInstance(
            bill_id=bill.bill,
            bill_title=bill.title,
            bill_version=bill.version,
            activated_by=activated_by,
            activation_data=activation_data or {},
        )

        # Initialize step states
        for step in bill.steps:
            instance.step_states[step.id] = StepState(step_id=step.id)

        # Assign roles (WQSB)
        overrides = role_overrides or {}
        unassigned_roles: list[str] = []

        for role_id, role in bill.roles.items():
            if role_id in overrides:
                # Manual override — caller provided the agent
                assignment = await self._resolve_override(
                    role_id, overrides[role_id],
                )
                if assignment:
                    instance.role_assignments[role_id] = assignment
                else:
                    unassigned_roles.append(role_id)
            else:
                # WQSB: auto-assign from BilletRegistry
                assignment = await self._assign_role(role_id, role)
                if assignment:
                    instance.role_assignments[role_id] = assignment
                else:
                    unassigned_roles.append(role_id)

        # Check assignment completeness
        if unassigned_roles and not self._config.allow_partial_assignment:
            raise BillActivationError(
                f"Cannot assign roles: {', '.join(unassigned_roles)}. "
                f"Bill '{bill.bill}' requires all roles filled."
            )

        if unassigned_roles:
            logger.warning(
                "AD-618b: Bill '%s' activated with unfilled roles: %s",
                bill.bill, unassigned_roles,
            )

        instance.status = InstanceStatus.ACTIVE
        self._instances[instance.id] = instance

        # Emit events
        self._emit(EventType.BILL_ACTIVATED, {
            "instance_id": instance.id,
            "bill_id": bill.bill,
            "bill_title": bill.title,
            "activated_by": activated_by,
            "roles_assigned": len(instance.role_assignments),
            "roles_unassigned": len(unassigned_roles),
            "total_steps": len(bill.steps),
        })

        for role_id, ra in instance.role_assignments.items():
            self._emit(EventType.BILL_ROLE_ASSIGNED, {
                "instance_id": instance.id,
                "bill_id": bill.bill,
                "role_id": role_id,
                "agent_id": ra.agent_id,
                "callsign": ra.callsign,
                "department": ra.department,
            })

        logger.info(
            "AD-618b: Bill '%s' activated — instance %s, %d/%d roles assigned, %d steps",
            bill.bill, instance.id,
            len(instance.role_assignments), len(bill.roles),
            len(bill.steps),
        )

        return instance

    # ------------------------------------------------------------------
    # Step lifecycle
    # ------------------------------------------------------------------

    def start_step(
        self,
        instance_id: str,
        step_id: str,
        agent_id: str,
        agent_type: str = "",
        agent_callsign: str = "",
        action: str = "",
    ) -> bool:
        """Mark a step as started by an agent.

        Returns True if the step was successfully started, False if the
        step doesn't exist, is not PENDING, or the instance is terminal.

        Parameters
        ----------
        action : str
            BillStep.action value (e.g. "decide", "post", "dm"). Snapshot
            onto StepState so complete_step can emit it without needing
            the BillDefinition.
        """
        instance = self._instances.get(instance_id)
        if not instance or instance.is_terminal:
            return False

        step_state = instance.step_states.get(step_id)
        if not step_state or step_state.status != StepStatus.PENDING:
            return False

        step_state.status = StepStatus.ACTIVE
        step_state.assigned_agent_id = agent_id
        step_state.assigned_agent_type = agent_type
        step_state.assigned_agent_callsign = agent_callsign
        step_state.action = action
        step_state.started_at = time.time()

        self._emit(EventType.BILL_STEP_STARTED, {
            "instance_id": instance_id,
            "bill_id": instance.bill_id,
            "step_id": step_id,
            "agent_id": agent_id,
            "callsign": agent_callsign,
        })

        return True

    def complete_step(
        self,
        instance_id: str,
        step_id: str,
        result: dict[str, Any] | None = None,
    ) -> bool:
        """Mark a step as completed with optional output data.

        Returns True on success. If all steps are now complete/skipped,
        the instance transitions to COMPLETED.
        """
        instance = self._instances.get(instance_id)
        if not instance or instance.is_terminal:
            return False

        step_state = instance.step_states.get(step_id)
        if not step_state or step_state.status != StepStatus.ACTIVE:
            return False

        step_state.status = StepStatus.COMPLETED
        step_state.completed_at = time.time()
        step_state.result = result or {}

        self._emit(EventType.BILL_STEP_COMPLETED, {
            "instance_id": instance_id,
            "bill_id": instance.bill_id,
            "step_id": step_id,
            "action": step_state.action,
            "agent_id": step_state.assigned_agent_id,
            "agent_type": step_state.assigned_agent_type,
            "duration_s": (
                step_state.completed_at - step_state.started_at
                if step_state.started_at else 0.0
            ),
        })

        # Check if all steps are terminal
        self._check_completion(instance)

        return True

    def fail_step(
        self,
        instance_id: str,
        step_id: str,
        error: str = "",
    ) -> bool:
        """Mark a step as failed. May cascade to BILL_FAILED depending on config."""
        instance = self._instances.get(instance_id)
        if not instance or instance.is_terminal:
            return False

        step_state = instance.step_states.get(step_id)
        if not step_state or step_state.status not in (StepStatus.PENDING, StepStatus.ACTIVE):
            return False

        step_state.status = StepStatus.FAILED
        step_state.completed_at = time.time()
        step_state.error = error

        self._emit(EventType.BILL_STEP_FAILED, {
            "instance_id": instance_id,
            "bill_id": instance.bill_id,
            "step_id": step_id,
            "agent_id": step_state.assigned_agent_id,
            "error": error,
        })

        # For now, a failed step fails the bill. Future: configurable
        # per-step criticality (some steps are optional).
        instance.status = InstanceStatus.FAILED
        instance.completed_at = time.time()

        self._emit(EventType.BILL_FAILED, {
            "instance_id": instance_id,
            "bill_id": instance.bill_id,
            "reason": f"Step '{step_id}' failed: {error}",
        })

        return True

    def skip_step(
        self,
        instance_id: str,
        step_id: str,
    ) -> bool:
        """Mark a step as skipped (XOR branch not taken, optional step)."""
        instance = self._instances.get(instance_id)
        if not instance or instance.is_terminal:
            return False

        step_state = instance.step_states.get(step_id)
        if not step_state or step_state.status != StepStatus.PENDING:
            return False

        step_state.status = StepStatus.SKIPPED
        step_state.completed_at = time.time()

        # Check if all steps are terminal
        self._check_completion(instance)

        return True

    def cancel(self, instance_id: str, reason: str = "") -> bool:
        """Cancel a bill instance."""
        instance = self._instances.get(instance_id)
        if not instance or instance.is_terminal:
            return False

        instance.status = InstanceStatus.CANCELLED
        instance.completed_at = time.time()

        self._emit(EventType.BILL_CANCELLED, {
            "instance_id": instance_id,
            "bill_id": instance.bill_id,
            "reason": reason,
        })

        logger.info(
            "AD-618b: Bill instance %s cancelled: %s", instance_id, reason,
        )

        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_instance(self, instance_id: str) -> BillInstance | None:
        """Get a bill instance by ID."""
        return self._instances.get(instance_id)

    def list_instances(
        self,
        *,
        bill_id: str | None = None,
        status: InstanceStatus | None = None,
        active_only: bool = False,
    ) -> list[BillInstance]:
        """List bill instances with optional filters."""
        results = list(self._instances.values())
        if bill_id:
            results = [i for i in results if i.bill_id == bill_id]
        if status:
            results = [i for i in results if i.status == status]
        if active_only:
            results = [i for i in results if i.status == InstanceStatus.ACTIVE]
        return sorted(results, key=lambda i: i.activated_at, reverse=True)

    def get_agent_assignments(self, agent_id: str) -> list[dict[str, Any]]:
        """Get all active bill role assignments for an agent.

        Returns list of dicts with instance_id, bill_id, role_id, bill_title.
        Agents can use this to discover which bills they're assigned to.
        """
        assignments: list[dict[str, Any]] = []
        for instance in self._instances.values():
            if instance.is_terminal:
                continue
            for role_id, ra in instance.role_assignments.items():
                if ra.agent_id == agent_id:
                    assignments.append({
                        "instance_id": instance.id,
                        "bill_id": instance.bill_id,
                        "bill_title": instance.bill_title,
                        "role_id": role_id,
                    })
        return assignments

    @property
    def active_count(self) -> int:
        """Number of currently active bill instances."""
        return sum(
            1 for i in self._instances.values()
            if i.status == InstanceStatus.ACTIVE
        )

    # ------------------------------------------------------------------
    # WQSB: Role Assignment
    # ------------------------------------------------------------------

    async def _assign_role(
        self,
        role_id: str,
        role: Any,  # BillRole from schema
    ) -> RoleAssignment | None:
        """Auto-assign an agent to a bill role using BilletRegistry.

        Assignment strategy:
        1. Get roster from BilletRegistry (all assigned agents).
        2. Filter by department (if role.department != "any").
        3. Filter by qualifications (if role.qualifications non-empty).
        4. Return the first qualified match.

        Future: rank by trust/Hebbian/workload based on config strategy.

        **Builder verification:** Before implementing, grep ``class BilletHolder``,
        ``def check_qualifications``, ``def get_roster``, ``def get_department_roster``
        in ``billet_registry.py`` and confirm field names and signatures match this
        prompt's usage.  If anything diverges, match the live code — not this prompt.
        """
        if not self._billet_registry:
            logger.debug(
                "AD-618b: No BilletRegistry — cannot auto-assign role '%s'",
                role_id,
            )
            return None

        # Get candidates from roster
        if role.department and role.department != "any":
            candidates = self._billet_registry.get_department_roster(role.department)
        else:
            candidates = self._billet_registry.get_roster()

        # Filter to assigned (non-vacant) billets
        candidates = [c for c in candidates if c.holder_agent_id]

        if not candidates:
            logger.debug(
                "AD-618b: No candidates for role '%s' (dept=%s)",
                role_id, role.department,
            )
            return None

        # Qualification filter (check_qualifications handles missing store gracefully)
        if role.qualifications:
            qualified_candidates = []
            for c in candidates:
                qualified, _missing = await self._billet_registry.check_qualifications(
                    c.billet_id, c.holder_agent_type or "", c.holder_agent_id or "",
                )
                if qualified:
                    qualified_candidates.append(c)
            candidates = qualified_candidates

        if not candidates:
            logger.debug(
                "AD-618b: No qualified candidates for role '%s'",
                role_id,
            )
            return None

        # Pick first candidate (simple strategy for now)
        pick = candidates[0]
        return RoleAssignment(
            role_id=role_id,
            agent_id=pick.holder_agent_id or "",
            agent_type=pick.holder_agent_type or "",
            callsign=pick.holder_callsign or "",
            department=pick.department,
        )

    async def _resolve_override(
        self,
        role_id: str,
        agent_id: str,
    ) -> RoleAssignment | None:
        """Resolve a manual role override to a RoleAssignment.

        Looks up the agent in BilletRegistry to get callsign/department.
        Falls back to a minimal assignment if registry unavailable.
        """
        if self._billet_registry:
            roster = self._billet_registry.get_roster()
            for bh in roster:
                if bh.holder_agent_id == agent_id:
                    return RoleAssignment(
                        role_id=role_id,
                        agent_id=agent_id,
                        agent_type=bh.holder_agent_type or "",
                        callsign=bh.holder_callsign or "",
                        department=bh.department,
                    )

        # Fallback: minimal assignment without registry metadata
        return RoleAssignment(
            role_id=role_id,
            agent_id=agent_id,
            agent_type="",
            callsign="",
            department="",
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_completion(self, instance: BillInstance) -> None:
        """Check if all steps in an instance are terminal → complete the bill."""
        all_terminal = all(
            ss.status in (StepStatus.COMPLETED, StepStatus.SKIPPED, StepStatus.FAILED)
            for ss in instance.step_states.values()
        )
        if not all_terminal:
            return

        # If any step failed, the bill is failed
        any_failed = any(
            ss.status == StepStatus.FAILED
            for ss in instance.step_states.values()
        )
        if any_failed:
            instance.status = InstanceStatus.FAILED
            instance.completed_at = time.time()
            self._emit(EventType.BILL_FAILED, {
                "instance_id": instance.id,
                "bill_id": instance.bill_id,
                "reason": "One or more steps failed",
            })
        else:
            instance.status = InstanceStatus.COMPLETED
            instance.completed_at = time.time()
            self._emit(EventType.BILL_COMPLETED, {
                "instance_id": instance.id,
                "bill_id": instance.bill_id,
                "bill_title": instance.bill_title,
                "duration_s": instance.completed_at - instance.activated_at,
                "steps_completed": sum(
                    1 for ss in instance.step_states.values()
                    if ss.status == StepStatus.COMPLETED
                ),
                "steps_skipped": sum(
                    1 for ss in instance.step_states.values()
                    if ss.status == StepStatus.SKIPPED
                ),
            })
            logger.info(
                "AD-618b: Bill '%s' instance %s completed (%.1fs)",
                instance.bill_id, instance.id,
                instance.completed_at - instance.activated_at,
            )

    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Emit an event if callback is set.

        Contract: ``emit_event_fn`` is **synchronous** (``(EventType, dict) -> None``).
        Callers wire it to ``runtime._emit_event_fn = lambda et, d: runtime.event_bus.emit(et, d)``
        or equivalent.  If the callback is async, wrap it in a sync shim at
        the wiring site — BillRuntime never awaits it.
        """
        if self._emit_event_fn:
            self._emit_event_fn(event_type, data)
```

---

## Section 5: Update `src/probos/sop/__init__.py`

**File:** `src/probos/sop/__init__.py` (EDIT)

Add the new exports from `instance` and `runtime` modules. After the existing imports from `schema` and `parser`, add:

```python
from probos.sop.instance import (
    BillInstance,
    InstanceStatus,
    RoleAssignment,
    StepState,
    StepStatus,
)
from probos.sop.runtime import BillActivationError, BillRuntime
```

And add these names to `__all__` if one exists. If there's no `__all__`, don't create one — just add the imports.

---

## Section 6: Tests

**File:** `tests/test_ad618b_bill_instance_runtime.py` (NEW)

Write comprehensive tests. Minimum coverage:

### Instance Tests
1. **BillInstance defaults** — id generated, status PENDING, empty role_assignments/step_states
2. **BillInstance.to_dict()** — serializes all fields including nested role_assignments and step_states
3. **BillInstance.is_terminal** — True for COMPLETED/FAILED/CANCELLED, False for PENDING/ACTIVE
4. **BillInstance.progress** — 0.0 with no steps complete, 0.5 with half done, 1.0 with all done
5. **StepState lifecycle** — PENDING → ACTIVE → COMPLETED transitions tracked

### Runtime Tests
6. **activate() — creates instance with correct bill metadata** — bill_id, bill_title, bill_version from BillDefinition
7. **activate() — initializes step states for all steps** — one StepState per BillStep, all PENDING
8. **activate() — concurrency limit** — raises BillActivationError when max_concurrent_instances exceeded
9. **activate() — emits BILL_ACTIVATED event** — verify event data includes instance_id, bill_id, roles_assigned count
10. **activate() — emits BILL_ROLE_ASSIGNED for each assigned role** — one event per role
11. **activate() — manual role overrides** — role_overrides dict bypasses WQSB
12. **activate() — allow_partial_assignment=False rejects incomplete** — raises BillActivationError
13. **activate() — allow_partial_assignment=True allows incomplete** — warning logged, instance created

### Step Lifecycle Tests
14. **start_step() — marks step ACTIVE with agent info** — sets assigned_agent_id, started_at
15. **start_step() — returns False for non-PENDING step** — idempotent safety
16. **start_step() — returns False for terminal instance** — no mutation after completion
17. **complete_step() — marks step COMPLETED with result** — sets completed_at, result dict
18. **complete_step() — triggers bill completion when all steps done** — for each step: start_step() then complete_step(); after the last step completes, instance.status == COMPLETED and BILL_COMPLETED event emitted
19. **complete_step() — emits BILL_STEP_COMPLETED event** — verify duration_s
20. **fail_step() — marks step and instance FAILED** — cascading failure
21. **fail_step() — emits BILL_STEP_FAILED and BILL_FAILED events**
22. **skip_step() — marks step SKIPPED** — for XOR branch not taken
23. **skip_step() + complete_step() — mixed terminal states still complete bill** — skip step A (stays PENDING→SKIPPED), start_step()+complete_step() step B; instance → COMPLETED with progress 1.0
24. **cancel() — cancels active instance** — status → CANCELLED
25. **cancel() — returns False for already-terminal instance**

### Query Tests
26. **get_instance() — returns None for unknown ID**
27. **list_instances() — filters by bill_id, status, active_only**
28. **get_agent_assignments() — returns active assignments for agent**
29. **get_agent_assignments() — excludes terminal instances**
30. **active_count property** — counts only ACTIVE instances

### Test Setup Pattern
- Create `BillDefinition` instances directly (don't depend on parser/YAML — that's AD-618a)
- Use `BillRole` and `BillStep` dataclasses from `probos.sop.schema`
- Mock `BilletRegistry` for role assignment tests
- Capture events via a list-appending callback

---

## Engineering Principles Compliance

- **SOLID/S** — BillInstance is pure state, BillRuntime is pure orchestration, WQSB assignment is a private method. Each has one reason to change.
- **SOLID/O** — `emit_event_fn` callback and `set_billet_registry()` allow extension without modifying BillRuntime.
- **SOLID/D** — Constructor injection for BilletRegistry and event callback. BillRuntime depends on abstractions (callable, Any), not concrete classes.
- **Law of Demeter** — `_assign_role` calls BilletRegistry's public API (`get_roster`, `get_department_roster`, `check_qualifications`). No reaching through internal state.
- **Fail Fast** — `BillActivationError` raised immediately on concurrency limit or missing required roles. Step lifecycle methods return `False` on invalid state rather than silently succeeding.
- **Cloud-Ready Storage** — BillRuntime is in-memory only (transient). No database dependency. Future persistence (if needed) will go through an abstract interface.
- **DRY** — `_emit` helper centralizes event emission. `_check_completion` reused by `complete_step`, `skip_step`, and `fail_step`.

---

## Tracking Updates

### PROGRESS.md
Add after the AD-618 entry:
```
AD-618b COMPLETE. Bill Instance + Runtime — BillInstance/StepState dataclasses, BillRuntime with activation/WQSB role assignment/step lifecycle/event emission. BillConfig. 7 EventType entries. 30 tests. Issue #204.
```

### DECISIONS.md
Add entry:
```
### AD-618b — Bill Instance + Runtime (2026-04-24)
**Context:** AD-618a delivered the Bill schema. Needed a runtime layer to activate bills, assign agents to roles, and track step progression.
**Decision:** BillRuntime is a stateless in-memory service (no persistence). BillInstances are transient — they live for the duration of the SOP execution. Role assignment uses BilletRegistry's existing roster with qualification filtering. Step lifecycle is tracked but NOT enforced — agents consult the SOP with judgment (reference, not engine). Failed steps cascade to bill failure (future: per-step criticality). No Ward Room push notifications in this AD — agents discover assignments via get_agent_assignments(). All timestamps use ``time.time()`` (wall-clock) — ``time.monotonic()`` rejected because serialized timestamps must be meaningful across process restarts. ``BILL_CANCELLED`` is a distinct event from ``BILL_FAILED`` — cancellation is intentional (authority decision), failure is unintentional (step error).
**Consequences:** Bills can now be activated and tracked. AD-618c can provide built-in YAML files. AD-618d can build a dashboard. AD-618e can bridge step completions to Cognitive JIT. Future AD: WorkItem integration (bill activation creates work items).
```

### docs/development/roadmap.md
Update AD-618b entry to COMPLETE.
