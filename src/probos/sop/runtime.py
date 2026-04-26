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
        self._instances: dict[str, BillInstance] = {}
        self._definitions: dict[str, BillDefinition] = {}  # AD-618d: bill_slug → BillDefinition

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
                assignment = await self._resolve_override(
                    role_id, overrides[role_id],
                )
                if assignment:
                    instance.role_assignments[role_id] = assignment
                else:
                    unassigned_roles.append(role_id)
            else:
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
        """Mark a step as failed. Cascades to BILL_FAILED."""
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

        # Failed step fails the bill
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

    # ------------------------------------------------------------------
    # Definition registry (AD-618d)
    # ------------------------------------------------------------------

    def register_definition(self, defn: BillDefinition) -> None:
        """Register a loaded bill definition for lookup by the API layer."""
        self._definitions[defn.bill] = defn

    def list_definitions(self) -> list[BillDefinition]:
        """List all registered bill definitions."""
        return list(self._definitions.values())

    def get_definition(self, bill_id: str) -> BillDefinition | None:
        """Get a bill definition by slug."""
        return self._definitions.get(bill_id)

    def get_agent_assignments(self, agent_id: str) -> list[dict[str, Any]]:
        """Get all active bill role assignments for an agent."""
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
        role: Any,
    ) -> RoleAssignment | None:
        """Auto-assign an agent to a bill role using BilletRegistry."""
        if not self._billet_registry:
            logger.debug(
                "AD-618b: No BilletRegistry — cannot auto-assign role '%s'",
                role_id,
            )
            return None

        if role.department and role.department != "any":
            candidates = self._billet_registry.get_department_roster(role.department)
        else:
            candidates = self._billet_registry.get_roster()

        candidates = [c for c in candidates if c.holder_agent_id]

        if not candidates:
            logger.debug(
                "AD-618b: No candidates for role '%s' (dept=%s)",
                role_id, role.department,
            )
            return None

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
        """Resolve a manual role override to a RoleAssignment."""
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
        """Check if all steps in an instance are terminal."""
        all_terminal = all(
            ss.status in (StepStatus.COMPLETED, StepStatus.SKIPPED, StepStatus.FAILED)
            for ss in instance.step_states.values()
        )
        if not all_terminal:
            return

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
        """Emit an event if callback is set."""
        if self._emit_event_fn:
            self._emit_event_fn(event_type, data)
