"""AD-496: Workforce Scheduling Engine — Core Data Model.

Universal Resource Scheduling for AI agents. Seven core entities providing
the scheduling substrate for all ProbOS work management.

Design principles:
- Separation of Work from Scheduling (WorkItem → Requirement → Booking)
- Derived status (WorkItem status computed from booking states)
- Progressive formalization (card → task → work_order)
- Pull-based assignment (Kanban) with push for urgent/trust-gated work
- Event-sourced tracking (BookingTimestamps are append-only)
- Capacity as integer (concurrent task limit)
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import math
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

import aiosqlite

from probos.events import EventType
from probos.protocols import ConnectionFactory, DatabaseConnection, EventEmitterMixin
from probos.types import Priority

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WorkItemStatus(str, Enum):
    """Base statuses common to all work types. Work Type Registry (AD-498) adds type-specific state machines."""
    DRAFT = "draft"
    OPEN = "open"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class BookingStatus(str, Enum):
    """Booking lifecycle states."""
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    ON_BREAK = "on_break"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class JournalType(str, Enum):
    """Types of time segments in a booking journal."""
    WORKING = "working"
    BREAK = "break"
    MAINTENANCE = "maintenance"
    IDLE = "idle"


class ResourceType(str, Enum):
    """Types of bookable resources."""
    CREW = "crew"
    INFRASTRUCTURE = "infrastructure"
    UTILITY = "utility"


class AssignmentMode(str, Enum):
    """How work gets assigned to resources."""
    PUSH = "push"       # Captain assigns directly
    PULL = "pull"       # Agent claims from eligible queue
    OFFER = "offer"     # System offers to qualified agents


# ---------------------------------------------------------------------------
# Terminal statuses (no transitions FROM these)
# ---------------------------------------------------------------------------

_TERMINAL_STATUSES = frozenset({"done", "cancelled", "failed"})


# ---------------------------------------------------------------------------
# Work Type Registry (AD-498)
# ---------------------------------------------------------------------------

@dataclass
class WorkTypeTransition:
    """A valid state transition for a work type."""
    from_status: str
    to_status: str
    requires_assignment: bool = False
    auto_creates_booking: bool = False


@dataclass
class WorkTypeDefinition:
    """Formal definition of a work type with state machine."""
    type_id: str
    display_name: str
    description: str
    initial_status: str
    terminal_statuses: frozenset[str]
    valid_transitions: list[WorkTypeTransition]
    required_fields: list[str] = field(default_factory=list)
    supports_children: bool = False
    auto_assign_eligible: bool = True
    verification_required: bool = False
    default_priority: int = 3
    metadata_schema: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type_id": self.type_id,
            "display_name": self.display_name,
            "description": self.description,
            "initial_status": self.initial_status,
            "terminal_statuses": list(self.terminal_statuses),
            "valid_transitions": [
                {"from_status": t.from_status, "to_status": t.to_status, "requires_assignment": t.requires_assignment}
                for t in self.valid_transitions
            ],
            "required_fields": self.required_fields,
            "supports_children": self.supports_children,
            "auto_assign_eligible": self.auto_assign_eligible,
            "verification_required": self.verification_required,
            "default_priority": self.default_priority,
        }


BUILTIN_WORK_TYPES: dict[str, WorkTypeDefinition] = {
    "card": WorkTypeDefinition(
        type_id="card",
        display_name="Card",
        description="Lightest work unit. No assignment required, no verification.",
        initial_status="draft",
        terminal_statuses=frozenset({"done", "cancelled"}),
        valid_transitions=[
            WorkTypeTransition("draft", "open"),
            WorkTypeTransition("draft", "done"),
            WorkTypeTransition("draft", "cancelled"),
            WorkTypeTransition("open", "done"),
            WorkTypeTransition("open", "cancelled"),
        ],
        default_priority=5,
    ),
    "task": WorkTypeDefinition(
        type_id="task",
        display_name="Task",
        description="Single-agent work. Requires assignment for in_progress.",
        initial_status="open",
        terminal_statuses=frozenset({"done", "failed", "cancelled"}),
        valid_transitions=[
            WorkTypeTransition("open", "in_progress", requires_assignment=True),
            WorkTypeTransition("open", "cancelled"),
            WorkTypeTransition("open", "blocked"),
            WorkTypeTransition("in_progress", "done"),
            WorkTypeTransition("in_progress", "failed"),
            WorkTypeTransition("in_progress", "cancelled"),
            WorkTypeTransition("in_progress", "blocked"),
            WorkTypeTransition("blocked", "in_progress"),
            WorkTypeTransition("blocked", "cancelled"),
        ],
        supports_children=True,
        default_priority=3,
    ),
    "work_order": WorkTypeDefinition(
        type_id="work_order",
        display_name="Work Order",
        description="Multi-step formal work. Requires review before done. Supports children.",
        initial_status="draft",
        terminal_statuses=frozenset({"done", "failed", "cancelled"}),
        valid_transitions=[
            WorkTypeTransition("draft", "open"),
            WorkTypeTransition("draft", "cancelled"),
            WorkTypeTransition("open", "scheduled"),
            WorkTypeTransition("open", "cancelled"),
            WorkTypeTransition("open", "blocked"),
            WorkTypeTransition("scheduled", "in_progress", requires_assignment=True, auto_creates_booking=True),
            WorkTypeTransition("scheduled", "cancelled"),
            WorkTypeTransition("scheduled", "blocked"),
            WorkTypeTransition("in_progress", "review"),
            WorkTypeTransition("in_progress", "failed"),
            WorkTypeTransition("in_progress", "cancelled"),
            WorkTypeTransition("in_progress", "blocked"),
            WorkTypeTransition("review", "done"),
            WorkTypeTransition("review", "in_progress"),
            WorkTypeTransition("review", "failed"),
            WorkTypeTransition("blocked", "in_progress"),
            WorkTypeTransition("blocked", "cancelled"),
        ],
        supports_children=True,
        verification_required=True,
        default_priority=2,
        required_fields=["title"],
    ),
    "duty": WorkTypeDefinition(
        type_id="duty",
        display_name="Duty",
        description="Recurring scheduled work. Auto-creates booking on start.",
        initial_status="scheduled",
        terminal_statuses=frozenset({"done", "failed"}),
        valid_transitions=[
            WorkTypeTransition("scheduled", "in_progress", auto_creates_booking=True),
            WorkTypeTransition("scheduled", "blocked"),
            WorkTypeTransition("in_progress", "done"),
            WorkTypeTransition("in_progress", "failed"),
            WorkTypeTransition("in_progress", "blocked"),
            WorkTypeTransition("blocked", "in_progress"),
            WorkTypeTransition("blocked", "cancelled"),
        ],
        auto_assign_eligible=False,
        default_priority=3,
    ),
    "incident": WorkTypeDefinition(
        type_id="incident",
        display_name="Incident",
        description="High-urgency reactive work. All transitions require assignment.",
        initial_status="open",
        terminal_statuses=frozenset({"done", "failed"}),
        valid_transitions=[
            WorkTypeTransition("open", "in_progress", requires_assignment=True),
            WorkTypeTransition("open", "blocked"),
            WorkTypeTransition("in_progress", "review", requires_assignment=True),
            WorkTypeTransition("in_progress", "failed"),
            WorkTypeTransition("in_progress", "blocked"),
            WorkTypeTransition("review", "done", requires_assignment=True),
            WorkTypeTransition("review", "in_progress", requires_assignment=True),
            WorkTypeTransition("review", "failed"),
            WorkTypeTransition("blocked", "in_progress"),
            WorkTypeTransition("blocked", "cancelled"),
        ],
        default_priority=1,
        required_fields=["title"],
    ),
    "crew_session": WorkTypeDefinition(
        type_id="crew_session",
        display_name="Crew Session",
        description="Durable multi-agent collaboration bound to a task-linked room.",
        initial_status="draft",
        terminal_statuses=frozenset({"done", "failed"}),
        valid_transitions=[
            WorkTypeTransition("draft", "open", requires_assignment=True),
            WorkTypeTransition("open", "in_progress", requires_assignment=True),
            WorkTypeTransition("open", "blocked"),
            WorkTypeTransition("open", "failed"),
            WorkTypeTransition("in_progress", "review"),
            WorkTypeTransition("in_progress", "blocked"),
            WorkTypeTransition("in_progress", "failed"),
            WorkTypeTransition("review", "done"),
            WorkTypeTransition("review", "blocked"),
            WorkTypeTransition("review", "failed"),
            WorkTypeTransition("blocked", "open"),
            WorkTypeTransition("blocked", "in_progress", requires_assignment=True),
            WorkTypeTransition("blocked", "failed"),
        ],
        required_fields=["title"],
        supports_children=True,
        auto_assign_eligible=False,
        verification_required=True,
        default_priority=2,
    ),
}


class WorkTypeRegistry:
    """Registry of work type definitions with state machine validation."""

    def __init__(self) -> None:
        self._types: dict[str, WorkTypeDefinition] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        for wt in BUILTIN_WORK_TYPES.values():
            self._types[wt.type_id] = wt

    def register(self, work_type: WorkTypeDefinition) -> None:
        self._types[work_type.type_id] = work_type

    def get(self, type_id: str) -> WorkTypeDefinition | None:
        return self._types.get(type_id)

    def list_types(self) -> list[WorkTypeDefinition]:
        return list(self._types.values())

    def validate_transition(self, type_id: str, from_status: str, to_status: str) -> tuple[bool, str]:
        wt = self._types.get(type_id)
        if not wt:
            return True, ""  # Unknown type = permissive (backward compat)
        if from_status in wt.terminal_statuses:
            return False, f"Cannot transition from terminal status '{from_status}'"
        valid = any(
            t.from_status == from_status and t.to_status == to_status
            for t in wt.valid_transitions
        )
        if not valid:
            return False, f"Work type '{type_id}' does not allow transition '{from_status}' → '{to_status}'"
        return True, ""

    def transition_requires_assignment(
        self, type_id: str, from_status: str, to_status: str,
    ) -> bool:
        """Return True if the ``from_status → to_status`` edge is flagged
        ``requires_assignment``.

        AD-498 attached ``requires_assignment`` to transitions such as ``task``
        ``open → in_progress`` to encode "you cannot start work without an
        owner", but ``validate_transition`` never read the flag. BF-608 enforces
        it at the store boundary (where ``assigned_to`` is available); this
        helper exposes the per-edge flag without leaking the transition objects.
        Unknown type or unknown edge → ``False`` (permissive, matching
        ``validate_transition``'s backward-compat stance).
        """
        wt = self._types.get(type_id)
        if not wt:
            return False
        for t in wt.valid_transitions:
            if t.from_status == from_status and t.to_status == to_status:
                return bool(t.requires_assignment)
        return False

    def get_valid_targets(self, type_id: str, from_status: str) -> list[str]:
        """Return list of valid target statuses from a given status."""
        wt = self._types.get(type_id)
        if not wt:
            return []
        return [t.to_status for t in wt.valid_transitions if t.from_status == from_status]

    def get_initial_status(self, type_id: str) -> str:
        wt = self._types.get(type_id)
        return wt.initial_status if wt else "open"

    def validate_required_fields(self, type_id: str, work_item: WorkItem) -> tuple[bool, str]:
        wt = self._types.get(type_id)
        if not wt:
            return True, ""
        for field_name in wt.required_fields:
            if getattr(work_item, field_name, None) is None:
                return False, f"Work type '{type_id}' requires field '{field_name}'"
        return True, ""


# ---------------------------------------------------------------------------
# Work Item Templates (AD-498)
# ---------------------------------------------------------------------------

@dataclass
class WorkItemTemplate:
    """Reusable template for creating pre-configured work items."""
    template_id: str
    name: str
    description: str
    work_type: str
    title_pattern: str
    description_pattern: str = ""
    default_steps: list[dict] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    min_trust: float = 0.0
    default_priority: int = 3
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    ttl_seconds: int | None = None
    category: str = "general"

    def to_dict(self) -> dict[str, Any]:
        # Parse variables from patterns
        variables = sorted(set(
            re.findall(r"\{(\w+)\}", self.title_pattern + " " + self.description_pattern)
        ))
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "work_type": self.work_type,
            "title_pattern": self.title_pattern,
            "description_pattern": self.description_pattern,
            "category": self.category,
            "estimated_tokens": self.estimated_tokens,
            "default_priority": self.default_priority,
            "tags": self.tags,
            "default_steps": self.default_steps,
            "min_trust": self.min_trust,
            "variables": variables,
            "ttl_seconds": self.ttl_seconds,
        }


BUILTIN_TEMPLATES: dict[str, WorkItemTemplate] = {
    "security_scan": WorkItemTemplate(
        template_id="security_scan",
        name="Security Scan",
        description="Run a security scan on a target module or subsystem.",
        work_type="work_order",
        title_pattern="Security Scan — {target}",
        description_pattern="Perform security analysis of {target}. Report vulnerabilities and remediation steps.",
        default_steps=[
            {"label": "Analyze", "status": "pending"},
            {"label": "Report", "status": "pending"},
            {"label": "Verify fixes", "status": "pending"},
        ],
        required_capabilities=["security"],
        estimated_tokens=30000,
        min_trust=0.6,
        default_priority=2,
        tags=["security", "scan"],
        category="security",
    ),
    "engineering_diagnostic": WorkItemTemplate(
        template_id="engineering_diagnostic",
        name="Engineering Diagnostic",
        description="Run diagnostics on a system component.",
        work_type="work_order",
        title_pattern="Engineering Diagnostic — {system}",
        description_pattern="Diagnose and report on health of {system}.",
        default_steps=[
            {"label": "Inspect", "status": "pending"},
            {"label": "Diagnose", "status": "pending"},
            {"label": "Report", "status": "pending"},
        ],
        required_capabilities=["engineering"],
        estimated_tokens=25000,
        default_priority=3,
        tags=["engineering", "diagnostic"],
        category="engineering",
    ),
    "code_review": WorkItemTemplate(
        template_id="code_review",
        name="Code Review",
        description="Review code for a given subject.",
        work_type="task",
        title_pattern="Code Review — {subject}",
        description_pattern="Review code changes for {subject}. Check quality, security, and correctness.",
        required_capabilities=["code_review"],
        estimated_tokens=20000,
        default_priority=3,
        tags=["review", "code"],
        category="engineering",
    ),
    "scout_report": WorkItemTemplate(
        template_id="scout_report",
        name="Scout Report",
        description="Periodic reconnaissance report.",
        work_type="duty",
        title_pattern="Scout Report — {date}",
        description_pattern="Compile external intelligence report for {date}.",
        estimated_tokens=15000,
        default_priority=4,
        tags=["operations", "scout"],
        category="operations",
    ),
    "crew_health_check": WorkItemTemplate(
        template_id="crew_health_check",
        name="Crew Health Check",
        description="Periodic crew wellness assessment.",
        work_type="duty",
        title_pattern="Crew Health Check — {date}",
        description_pattern="Assess cognitive health and fitness of all crew for {date}.",
        required_capabilities=["medical"],
        estimated_tokens=10000,
        default_priority=4,
        tags=["medical", "health"],
        category="medical",
    ),
    "night_maintenance": WorkItemTemplate(
        template_id="night_maintenance",
        name="Maintenance Watch",
        description="Night orders: maintenance mode. Run diagnostics, handle routine maintenance.",
        work_type="task",
        title_pattern="Night Orders — Maintenance Watch",
        estimated_tokens=15000,
        default_priority=4,
        tags=["night_orders", "maintenance"],
        ttl_seconds=28800,
        category="night_orders",
        metadata={
            "can_approve_builds": False,
            "alert_boundary": "yellow",
            "escalation_triggers": ["trust_drop", "red_alert", "security_alert"],
            "instructions": "Run scheduled diagnostics. Monitor system health. Escalate anomalies.",
        },
    ),
    "night_build": WorkItemTemplate(
        template_id="night_build",
        name="Build Watch",
        description="Night orders: build mode. Process build queue items.",
        work_type="task",
        title_pattern="Night Orders — Build Watch",
        estimated_tokens=50000,
        default_priority=3,
        tags=["night_orders", "build"],
        ttl_seconds=28800,
        category="night_orders",
        metadata={
            "can_approve_builds": True,
            "alert_boundary": "yellow",
            "escalation_triggers": ["trust_drop", "red_alert", "build_failure"],
            "instructions": "Process build queue. Approve routine builds. Escalate failures.",
        },
    ),
    "night_quiet": WorkItemTemplate(
        template_id="night_quiet",
        name="Quiet Watch",
        description="Night orders: quiet mode. Monitor only, no proactive actions.",
        work_type="task",
        title_pattern="Night Orders — Quiet Watch",
        estimated_tokens=5000,
        default_priority=5,
        tags=["night_orders", "quiet"],
        ttl_seconds=28800,
        category="night_orders",
        metadata={
            "can_approve_builds": False,
            "alert_boundary": "green",
            "escalation_triggers": ["red_alert", "security_alert"],
            "instructions": "Monitor only. No proactive actions. Escalate critical alerts only.",
        },
    ),
}


class TemplateStore:
    """Registry of work item templates."""

    def __init__(self) -> None:
        self._templates: dict[str, WorkItemTemplate] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        for t in BUILTIN_TEMPLATES.values():
            self._templates[t.template_id] = t

    def register(self, template: WorkItemTemplate) -> None:
        self._templates[template.template_id] = template

    def get(self, template_id: str) -> WorkItemTemplate | None:
        return self._templates.get(template_id)

    def list_templates(self, category: str | None = None) -> list[WorkItemTemplate]:
        templates = list(self._templates.values())
        if category:
            templates = [t for t in templates if t.category == category]
        return sorted(templates, key=lambda t: (t.category, t.name))

    def instantiate(
        self,
        template_id: str,
        variables: dict[str, str] | None = None,
        overrides: dict | None = None,
    ) -> dict:
        template = self._templates.get(template_id)
        if not template:
            raise ValueError(f"Template '{template_id}' not found")

        variables = variables or {}
        title = template.title_pattern.format_map(defaultdict(str, variables))
        description = template.description_pattern.format_map(defaultdict(str, variables)) if template.description_pattern else ""

        kwargs: dict = {
            "title": title,
            "description": description,
            "work_type": template.work_type,
            "priority": template.default_priority,
            "estimated_tokens": template.estimated_tokens,
            "trust_requirement": template.min_trust,
            "required_capabilities": list(template.required_capabilities),
            "tags": list(template.tags),
            "steps": [dict(s) for s in template.default_steps],
            "metadata": {**template.metadata, "template_id": template.template_id},
            "template_id": template.template_id,
        }
        if template.ttl_seconds:
            kwargs["ttl_seconds"] = template.ttl_seconds

        if overrides:
            for key in ("priority", "assigned_to", "due_at", "tags", "description"):
                if key in overrides:
                    kwargs[key] = overrides[key]
            if "metadata" in overrides:
                kwargs["metadata"].update(overrides["metadata"])

        return kwargs

    def reload_templates(self, template_dicts: list[dict]) -> int:
        """Hot-reload templates from config dicts. Returns count registered."""
        count = 0
        for td in template_dicts:
            try:
                t = WorkItemTemplate(**td)
                self._templates[t.template_id] = t
                count += 1
            except Exception:
                logger.warning("Failed to load custom template: %s", td.get("template_id", "?"), exc_info=True)
        return count

# (1) WorkItem

@dataclass
class WorkItem:
    """Universal polymorphic work entity.

    Subsumes AgentTask, PersistentTask, and QueuedBuild concepts over time.
    The work_type field determines valid state transitions (AD-498).
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    description: str = ""
    work_type: str = "task"             # card | task | work_order | duty | incident (AD-498 registry)
    status: str = "open"                # WorkItemStatus value; string for extensibility
    priority: int = 3                   # 1 (critical) to 5 (low)
    parent_id: str | None = None        # Recursive containment / WBS
    depends_on: list[str] = field(default_factory=list)
    assigned_to: str | None = None      # agent UUID or pool ID
    created_by: str = "captain"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    due_at: float | None = None
    estimated_tokens: int | None = None
    actual_tokens: int = 0
    trust_requirement: float = 0.0
    required_capabilities: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # AD-926 convention (additive, no schema change): a task room's read-only
    # Input folder reads ``metadata["input_attachments"] = [{content_hash,
    # mime, filename}]`` via GET /api/threads/{thread_id}/inputs. Population is
    # deferred (a future task-seed flow writes it — AD-926a); the key is absent
    # by default and ``to_dict`` already serializes ``metadata`` verbatim.
    steps: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    schedule: dict[str, Any] = field(default_factory=dict)
    ttl_seconds: int | None = None
    template_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "work_type": self.work_type,
            "status": self.status,
            "priority": self.priority,
            "parent_id": self.parent_id,
            "depends_on": self.depends_on,
            "assigned_to": self.assigned_to,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "due_at": self.due_at,
            "estimated_tokens": self.estimated_tokens,
            "actual_tokens": self.actual_tokens,
            "trust_requirement": self.trust_requirement,
            "required_capabilities": self.required_capabilities,
            "tags": self.tags,
            "metadata": self.metadata,
            "steps": self.steps,
            "verification": self.verification,
            "schedule": self.schedule,
            "ttl_seconds": self.ttl_seconds,
            "template_id": self.template_id,
        }


@dataclass(frozen=True)
class WorkItemPlanInsert:
    """Validated generic WorkItem fields for one atomic child-plan insert."""

    id: str
    title: str
    description: str
    work_type: str
    priority: int
    depends_on: tuple[str, ...]
    assigned_to: str | None
    created_by: str
    trust_requirement: float
    required_capabilities: tuple[str, ...]
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        identifier_values = (self.id, self.created_by)
        if self.assigned_to is not None:
            identifier_values += (self.assigned_to,)
        if any(
            type(value) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(value) is None
            for value in identifier_values
        ):
            raise ValueError("work_item_plan_insert_invalid")
        if (
            type(self.title) is not str
            or not self.title.strip()
            or "\x00" in self.title
            or len(self.title) > 4_096
            or type(self.description) is not str
            or "\x00" in self.description
            or len(self.description) > 32_768
            or type(self.work_type) is not str
            or not self.work_type
            or "\x00" in self.work_type
            or len(self.work_type) > 128
            or type(self.priority) is not int
            or not 1 <= self.priority <= 5
            or type(self.depends_on) is not tuple
            or len(self.depends_on) > 64
            or any(
                type(value) is not str
                or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(value) is None
                for value in self.depends_on
            )
            or len(set(self.depends_on)) != len(self.depends_on)
            or type(self.required_capabilities) is not tuple
            or len(self.required_capabilities) > 64
            or any(
                type(value) is not str
                or not value
                or "\x00" in value
                or len(value) > 256
                for value in self.required_capabilities
            )
            or type(self.trust_requirement) not in (int, float)
            or not math.isfinite(float(self.trust_requirement))
            or not 0.0 <= float(self.trust_requirement) <= 1.0
            or type(self.metadata) is not dict
        ):
            raise ValueError("work_item_plan_insert_invalid")
        metadata_bytes = _compact_exact_json_bytes(
            self.metadata,
            error="work_item_plan_insert_invalid",
        )
        if len(metadata_bytes) > _MAX_WORK_ITEM_METADATA_BYTES:
            raise ValueError("work_item_plan_insert_invalid")
        object.__setattr__(self, "title", self.title.strip())
        object.__setattr__(self, "trust_requirement", float(self.trust_requirement))
        object.__setattr__(
            self,
            "metadata",
            json.loads(metadata_bytes.decode("utf-8")),
        )


# (2) BookableResource

@dataclass
class BookableResource:
    """Wrapper around agents adding scheduling dimensions."""
    resource_id: str = ""
    resource_type: str = "crew"
    agent_type: str = ""
    callsign: str = ""
    capacity: int = 1
    calendar_id: str | None = None
    department: str = ""
    characteristics: list[dict[str, Any]] = field(default_factory=list)
    display_on_board: bool = True
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "agent_type": self.agent_type,
            "callsign": self.callsign,
            "capacity": self.capacity,
            "calendar_id": self.calendar_id,
            "department": self.department,
            "characteristics": self.characteristics,
            "display_on_board": self.display_on_board,
            "active": self.active,
        }


# (3) ResourceRequirement

@dataclass
class ResourceRequirement:
    """The demand side — what a work item needs to be fulfilled."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    work_item_id: str = ""
    duration_estimate_seconds: float | None = None
    from_date: float | None = None
    to_date: float | None = None
    required_characteristics: list[dict[str, Any]] = field(default_factory=list)
    min_trust: float = 0.0
    department_constraint: str | None = None
    priority: int = 3
    resource_preference: dict[str, Any] = field(default_factory=dict)
    fulfilled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "work_item_id": self.work_item_id,
            "duration_estimate_seconds": self.duration_estimate_seconds,
            "from_date": self.from_date,
            "to_date": self.to_date,
            "required_characteristics": self.required_characteristics,
            "min_trust": self.min_trust,
            "department_constraint": self.department_constraint,
            "priority": self.priority,
            "resource_preference": self.resource_preference,
            "fulfilled": self.fulfilled,
        }


# (4) Booking

@dataclass
class Booking:
    """Assignment link between resource and work item for a time slot."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    resource_id: str = ""
    work_item_id: str = ""
    requirement_id: str | None = None
    status: str = "scheduled"
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    actual_start: float | None = None
    actual_end: float | None = None
    total_tokens_consumed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "resource_id": self.resource_id,
            "work_item_id": self.work_item_id,
            "requirement_id": self.requirement_id,
            "status": self.status,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "actual_start": self.actual_start,
            "actual_end": self.actual_end,
            "total_tokens_consumed": self.total_tokens_consumed,
        }


# (5) BookingTimestamp

@dataclass
class BookingTimestamp:
    """Append-only event log of every booking status transition."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    booking_id: str = ""
    status: str = ""
    timestamp: float = field(default_factory=time.time)
    source: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "booking_id": self.booking_id,
            "status": self.status,
            "timestamp": self.timestamp,
            "source": self.source,
        }


# (6) BookingJournal

@dataclass
class BookingJournal:
    """Computed time/token segments derived from timestamps upon booking completion."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    booking_id: str = ""
    journal_type: str = "working"
    start_time: float = 0.0
    end_time: float = 0.0
    duration_seconds: float = 0.0
    tokens_consumed: int = 0
    billable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "booking_id": self.booking_id,
            "journal_type": self.journal_type,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds,
            "tokens_consumed": self.tokens_consumed,
            "billable": self.billable,
        }


# (7) AgentCalendar

@dataclass
class CalendarEntry:
    """A single work-hour slot in an agent's calendar."""
    day_pattern: str = "*"
    start_hour: int = 0
    end_hour: int = 24
    capacity: int = 1
    repeat_rule: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "day_pattern": self.day_pattern,
            "start_hour": self.start_hour,
            "end_hour": self.end_hour,
            "capacity": self.capacity,
            "repeat_rule": self.repeat_rule,
        }


@dataclass
class AgentCalendar:
    """Work hours and capacity schedule per agent."""
    resource_id: str = ""
    entries: list[CalendarEntry] = field(default_factory=list)
    maintenance_windows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "entries": [e.to_dict() for e in self.entries],
            "maintenance_windows": self.maintenance_windows,
        }


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS work_items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    work_type TEXT NOT NULL DEFAULT 'task',
    status TEXT NOT NULL DEFAULT 'open',
    priority INTEGER NOT NULL DEFAULT 3,
    parent_id TEXT,
    depends_on TEXT NOT NULL DEFAULT '[]',
    assigned_to TEXT,
    created_by TEXT NOT NULL DEFAULT 'captain',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    due_at REAL,
    estimated_tokens INTEGER,
    actual_tokens INTEGER NOT NULL DEFAULT 0,
    trust_requirement REAL NOT NULL DEFAULT 0.0,
    required_capabilities TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}',
    steps TEXT NOT NULL DEFAULT '[]',
    verification TEXT NOT NULL DEFAULT '{}',
    schedule TEXT NOT NULL DEFAULT '{}',
    ttl_seconds INTEGER,
    template_id TEXT
);

CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL,
    work_item_id TEXT NOT NULL,
    requirement_id TEXT,
    status TEXT NOT NULL DEFAULT 'scheduled',
    start_time REAL NOT NULL,
    end_time REAL,
    actual_start REAL,
    actual_end REAL,
    total_tokens_consumed INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (work_item_id) REFERENCES work_items(id)
);

CREATE TABLE IF NOT EXISTS booking_timestamps (
    id TEXT PRIMARY KEY,
    booking_id TEXT NOT NULL,
    status TEXT NOT NULL,
    timestamp REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'system',
    FOREIGN KEY (booking_id) REFERENCES bookings(id)
);

CREATE TABLE IF NOT EXISTS booking_journals (
    id TEXT PRIMARY KEY,
    booking_id TEXT NOT NULL,
    journal_type TEXT NOT NULL DEFAULT 'working',
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    duration_seconds REAL NOT NULL DEFAULT 0.0,
    tokens_consumed INTEGER NOT NULL DEFAULT 0,
    billable INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (booking_id) REFERENCES bookings(id)
);

CREATE TABLE IF NOT EXISTS resource_requirements (
    id TEXT PRIMARY KEY,
    work_item_id TEXT NOT NULL,
    duration_estimate_seconds REAL,
    from_date REAL,
    to_date REAL,
    required_characteristics TEXT NOT NULL DEFAULT '[]',
    min_trust REAL NOT NULL DEFAULT 0.0,
    department_constraint TEXT,
    priority INTEGER NOT NULL DEFAULT 3,
    resource_preference TEXT NOT NULL DEFAULT '{}',
    fulfilled INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (work_item_id) REFERENCES work_items(id)
);

CREATE INDEX IF NOT EXISTS idx_work_items_status ON work_items(status);
CREATE INDEX IF NOT EXISTS idx_work_items_assigned_to ON work_items(assigned_to);
CREATE INDEX IF NOT EXISTS idx_work_items_work_type ON work_items(work_type);
CREATE INDEX IF NOT EXISTS idx_work_items_parent_id ON work_items(parent_id);
CREATE INDEX IF NOT EXISTS idx_bookings_resource_id ON bookings(resource_id);
CREATE INDEX IF NOT EXISTS idx_bookings_work_item_id ON bookings(work_item_id);
CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
CREATE INDEX IF NOT EXISTS idx_booking_timestamps_booking_id ON booking_timestamps(booking_id);
"""

# Fields that are JSON-serialized in SQLite
_JSON_FIELDS = frozenset({
    "depends_on", "required_capabilities", "tags",
    "metadata", "steps", "verification", "schedule",
    "required_characteristics", "resource_preference",
})

# Immutable fields that cannot be updated
_IMMUTABLE_FIELDS = frozenset({"id", "created_at", "created_by"})

_MAX_WORK_ITEM_METADATA_BYTES = 1_048_576
_MAX_WORK_ITEM_VERIFICATION_BYTES = 262_144
_MAX_WORK_ITEM_ACTUAL_TOKENS = 9_223_372_036_854_775_807
_MAX_WORK_ITEM_METADATA_EXPECTED_KEYS = 1_024
_MAX_WORK_ITEM_METADATA_KEY_CODEPOINTS = 256
_MAX_WORK_ITEM_METADATA_KEY_BYTES = 1_024
_MAX_WORK_ITEM_CHILD_SNAPSHOT_BYTES = 1_572_864
_MAX_WORK_ITEM_CHILD_SNAPSHOTS_BYTES = 33_554_432
_MAX_WORK_ITEM_DIRECT_CHILDREN = 1_000
_MAX_WORK_ITEM_CHILD_SNAPSHOT_DEPTH = 64
_MAX_WORK_ITEM_CHILD_SNAPSHOT_NODES = 65_536
_MAX_WORK_ITEM_CHILD_SNAPSHOT_CONTAINER_ENTRIES = 16_384
_MAX_WORK_ITEM_CHILD_SNAPSHOT_STRING_BYTES = 1_048_576
_MISSING_METADATA_VALUE = object()
_WORK_ITEM_CHILD_SNAPSHOT_KEYS = frozenset({
    "id",
    "title",
    "description",
    "work_type",
    "status",
    "priority",
    "parent_id",
    "depends_on",
    "assigned_to",
    "created_by",
    "created_at",
    "due_at",
    "estimated_tokens",
    "actual_tokens",
    "trust_requirement",
    "required_capabilities",
    "tags",
    "metadata",
    "steps",
    "verification",
    "schedule",
    "ttl_seconds",
    "template_id",
})
_WORK_ITEM_PLAN_ADOPTION_SNAPSHOT_KEYS = (
    _WORK_ITEM_CHILD_SNAPSHOT_KEYS | {"updated_at"}
)
_WORK_ITEM_PUBLICATION_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
)


class _OmittedWorkItemExpectation:
    __slots__ = ()


_OMITTED_WORK_ITEM_EXPECTATION = _OmittedWorkItemExpectation()


def _valid_work_item_metadata_expectation_key(value: Any) -> bool:
    if (
        type(value) is not str
        or not value
        or "\x00" in value
        or len(value) > _MAX_WORK_ITEM_METADATA_KEY_CODEPOINTS
    ):
        return False
    try:
        return len(value.encode("utf-8")) <= _MAX_WORK_ITEM_METADATA_KEY_BYTES
    except UnicodeEncodeError:
        return False


def _json_values_exactly_equal(current: Any, expected: Any) -> bool:
    if type(current) is not type(expected):
        return False
    if type(current) is dict:
        if (
            any(type(key) is not str for key in current)
            or any(type(key) is not str for key in expected)
            or current.keys() != expected.keys()
        ):
            return False
        return all(
            _json_values_exactly_equal(current[key], expected[key])
            for key in current
        )
    if type(current) is list:
        return len(current) == len(expected) and all(
            _json_values_exactly_equal(current_value, expected_value)
            for current_value, expected_value in zip(current, expected)
        )
    if current is None:
        return True
    if type(current) in (bool, int, float, str):
        return current == expected
    return False


def _compact_exact_json_bytes(value: Any, *, error: str) -> bytes:
    def _validate(current: Any) -> None:
        if current is None or type(current) in (bool, int, str):
            return
        if type(current) is float:
            if not math.isfinite(current):
                raise ValueError(error)
            return
        if type(current) is list:
            for item in current:
                _validate(item)
            return
        if type(current) is dict:
            if any(type(key) is not str for key in current):
                raise ValueError(error)
            for item in current.values():
                _validate(item)
            return
        raise ValueError(error)

    try:
        _validate(value)
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError(error) from exc


def _bounded_child_snapshot_bytes(
    value: dict[str, Any],
    *,
    error: str,
    seen_containers: set[int],
) -> bytes:
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    container_entries = 0
    string_bytes = 0
    exact_bytes = 0

    def _add_string(current: str) -> int:
        nonlocal string_bytes
        encoded = current.encode("utf-8", errors="strict")
        string_bytes += len(encoded)
        if string_bytes > _MAX_WORK_ITEM_CHILD_SNAPSHOT_STRING_BYTES:
            raise ValueError(error)
        return len(json.dumps(
            current,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict"))

    try:
        while stack:
            current, depth = stack.pop()
            nodes += 1
            if (
                nodes > _MAX_WORK_ITEM_CHILD_SNAPSHOT_NODES
                or depth > _MAX_WORK_ITEM_CHILD_SNAPSHOT_DEPTH
            ):
                raise ValueError(error)
            if current is None or type(current) in (bool, int):
                exact_bytes += len(json.dumps(
                    current,
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8"))
            elif type(current) is float:
                if not math.isfinite(current):
                    raise ValueError(error)
                exact_bytes += len(json.dumps(
                    current,
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8"))
            elif type(current) is str:
                exact_bytes += _add_string(current)
            elif type(current) is list:
                identity = id(current)
                if identity in seen_containers:
                    raise ValueError(error)
                seen_containers.add(identity)
                container_entries += len(current)
                if (
                    container_entries
                    > _MAX_WORK_ITEM_CHILD_SNAPSHOT_CONTAINER_ENTRIES
                ):
                    raise ValueError(error)
                exact_bytes += 2 + max(0, len(current) - 1)
                for item in reversed(current):
                    stack.append((item, depth + 1))
            elif type(current) is dict:
                identity = id(current)
                if identity in seen_containers:
                    raise ValueError(error)
                seen_containers.add(identity)
                container_entries += len(current)
                if (
                    container_entries
                    > _MAX_WORK_ITEM_CHILD_SNAPSHOT_CONTAINER_ENTRIES
                ):
                    raise ValueError(error)
                exact_bytes += 2 + max(0, len(current) - 1) + len(current)
                for key, item in current.items():
                    if type(key) is not str:
                        raise ValueError(error)
                    nodes += 1
                    if nodes > _MAX_WORK_ITEM_CHILD_SNAPSHOT_NODES:
                        raise ValueError(error)
                    exact_bytes += _add_string(key)
                    stack.append((item, depth + 1))
            else:
                raise ValueError(error)
            if exact_bytes > _MAX_WORK_ITEM_CHILD_SNAPSHOT_BYTES:
                raise ValueError(error)

        serialized = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise ValueError(error) from exc
    if len(serialized) != exact_bytes or len(serialized) > _MAX_WORK_ITEM_CHILD_SNAPSHOT_BYTES:
        raise ValueError(error)
    return serialized


def _detach_direct_child_snapshots(
    work_item_id: str,
    value: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    error = "work_item_child_barrier_invalid"
    if (
        type(work_item_id) is not str
        or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(work_item_id) is None
        or type(value) is not tuple
        or not 1 <= len(value) <= _MAX_WORK_ITEM_DIRECT_CHILDREN
    ):
        raise ValueError(error)
    detached: list[dict[str, Any]] = []
    previous_id = ""
    aggregate_bytes = 0
    seen_containers: set[int] = set()
    for raw in value:
        if type(raw) is not dict or set(raw) != _WORK_ITEM_CHILD_SNAPSHOT_KEYS:
            raise ValueError(error)
        child_id = raw["id"]
        parent_id = raw["parent_id"]
        assigned_to = raw["assigned_to"]
        if (
            type(child_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(child_id) is None
            or child_id <= previous_id
            or type(parent_id) is not str
            or parent_id != work_item_id
            or type(assigned_to) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(assigned_to) is None
            or raw["status"] != "done"
            or type(raw["status"]) is not str
            or any(
                type(raw[key]) is not str
                for key in ("title", "description", "work_type", "created_by")
            )
            or type(raw["priority"]) is not int
            or type(raw["actual_tokens"]) is not int
            or raw["actual_tokens"] < 0
            or type(raw["depends_on"]) is not list
            or type(raw["required_capabilities"]) is not list
            or type(raw["tags"]) is not list
            or type(raw["steps"]) is not list
            or type(raw["metadata"]) is not dict
            or type(raw["verification"]) is not dict
            or type(raw["schedule"]) is not dict
            or (
                raw["estimated_tokens"] is not None
                and type(raw["estimated_tokens"]) is not int
            )
            or (
                raw["ttl_seconds"] is not None
                and type(raw["ttl_seconds"]) is not int
            )
            or (
                raw["template_id"] is not None
                and type(raw["template_id"]) is not str
            )
        ):
            raise ValueError(error)
        for key in ("created_at", "trust_requirement"):
            numeric = raw[key]
            if type(numeric) not in (int, float) or not math.isfinite(float(numeric)):
                raise ValueError(error)
        due_at = raw["due_at"]
        if due_at is not None and (
            type(due_at) not in (int, float) or not math.isfinite(float(due_at))
        ):
            raise ValueError(error)
        serialized = _bounded_child_snapshot_bytes(
            raw,
            error=error,
            seen_containers=seen_containers,
        )
        aggregate_bytes += len(serialized)
        if aggregate_bytes > _MAX_WORK_ITEM_CHILD_SNAPSHOTS_BYTES:
            raise ValueError(error)
        detached.append(json.loads(serialized.decode("utf-8")))
        previous_id = child_id
    return tuple(detached)


def _work_item_child_snapshot(item: WorkItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "work_type": item.work_type,
        "status": item.status,
        "priority": item.priority,
        "parent_id": item.parent_id,
        "depends_on": item.depends_on,
        "assigned_to": item.assigned_to,
        "created_by": item.created_by,
        "created_at": item.created_at,
        "due_at": item.due_at,
        "estimated_tokens": item.estimated_tokens,
        "actual_tokens": item.actual_tokens,
        "trust_requirement": item.trust_requirement,
        "required_capabilities": item.required_capabilities,
        "tags": item.tags,
        "metadata": item.metadata,
        "steps": item.steps,
        "verification": item.verification,
        "schedule": item.schedule,
        "ttl_seconds": item.ttl_seconds,
        "template_id": item.template_id,
    }


def _detach_plan_adoption_children(
    parent_id: str,
    children: tuple[WorkItem, ...],
) -> tuple[dict[str, Any], ...]:
    error = "work_item_plan_adoption_invalid"
    if (
        type(parent_id) is not str
        or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(parent_id) is None
        or type(children) is not tuple
        or not 1 <= len(children) <= _MAX_WORK_ITEM_DIRECT_CHILDREN
        or any(type(child) is not WorkItem for child in children)
    ):
        raise ValueError(error)
    child_ids = tuple(child.id for child in children)
    if child_ids != tuple(sorted(child_ids)) or len(set(child_ids)) != len(child_ids):
        raise ValueError(error)
    detached: list[dict[str, Any]] = []
    aggregate_bytes = 0
    for child in children:
        snapshot = child.to_dict()
        if (
            type(snapshot) is not dict
            or set(snapshot) != _WORK_ITEM_PLAN_ADOPTION_SNAPSHOT_KEYS
            or child.parent_id != parent_id
            or type(child.id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(child.id) is None
        ):
            raise ValueError(error)
        serialized = _bounded_child_snapshot_bytes(
            snapshot,
            error=error,
            seen_containers=set(),
        )
        aggregate_bytes += len(serialized)
        if aggregate_bytes > _MAX_WORK_ITEM_CHILD_SNAPSHOTS_BYTES:
            raise ValueError(error)
        detached.append(json.loads(serialized.decode("utf-8")))
    return tuple(detached)

# AD-1080: room-Todo checklist step state machine. A step is a dict
# {label, status, assigned_to?, submitted_by?, confirmed_by?, note?}. The loop:
# an agent works a step (in_progress), self-reports it done (submitted), and a
# SENIOR agent confirms (done) or rejects it (rejected -> back to in_progress) —
# nothing is 'done' until senior-validated.
STEP_STATUSES: frozenset[str] = frozenset(
    {"pending", "in_progress", "submitted", "done", "rejected"}
)
_STEP_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"in_progress", "submitted"}),
    "in_progress": frozenset({"submitted", "pending"}),
    "submitted": frozenset({"done", "rejected", "in_progress"}),
    "rejected": frozenset({"in_progress", "submitted"}),
    "done": frozenset(),
}


def validate_step_transition(old: str, new: str) -> bool:
    """AD-1080: True iff a Todo step may move old->new (a same-status set is an
    idempotent no-op)."""
    if new not in STEP_STATUSES:
        return False
    if old == new:
        return True
    return new in _STEP_TRANSITIONS.get(old, frozenset())


def _all_steps_done(steps: list[dict[str, Any]]) -> bool:
    """AD-1080: True iff there is at least one step and every step is confirmed
    'done' (the completion gate — nothing complete until validated)."""
    return bool(steps) and all(
        str(s.get("status", "pending")) == "done" for s in steps
    )


# ---------------------------------------------------------------------------
# WorkItemStore — SQLite-backed persistence
# ---------------------------------------------------------------------------

class WorkItemStore(EventEmitterMixin):
    """SQLite-backed workforce scheduling engine.

    Follows the PersistentTaskStore lifecycle pattern.
    """

    def __init__(
        self,
        db_path: str | None = None,
        emit_event: Callable[..., Any] | None = None,
        tick_interval: float = 10.0,
        config: dict | None = None,
        connection_factory: ConnectionFactory | None = None,
    ):
        self.db_path = db_path
        self._db: DatabaseConnection | None = None
        self._emit_event = emit_event
        self._tick_interval = tick_interval
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory
        self._tick_task: asyncio.Task[None] | None = None
        self._running = False
        self._dispatcher: Any | None = None  # AD-654d: set via attach_dispatcher()
        # In-memory registries (populated from ACM at startup)
        self._resources: dict[str, BookableResource] = {}
        self._calendars: dict[str, AgentCalendar] = {}
        # Snapshot cache for sync-safe access
        self._snapshot_cache: dict[str, Any] = {"work_items": [], "bookings": []}
        self._work_item_row_write_lock = asyncio.Lock()
        # AD-498: Work Type Registry + Template Store
        self.work_type_registry = WorkTypeRegistry()
        self.template_store = TemplateStore()
        # Load custom types/templates from config
        if config:
            for ct in config.get("custom_work_types", []):
                try:
                    transitions = [WorkTypeTransition(**t) for t in ct.pop("valid_transitions", [])]
                    ct["valid_transitions"] = transitions
                    ct["terminal_statuses"] = frozenset(ct.get("terminal_statuses", []))
                    self.work_type_registry.register(WorkTypeDefinition(**ct))
                except Exception:
                    logger.warning("Failed to load custom work type: %s", ct.get("type_id", "?"), exc_info=True)
            for td in config.get("custom_templates", []):
                try:
                    self.template_store.register(WorkItemTemplate(**td))
                except Exception:
                    logger.warning("Failed to load custom template: %s", td.get("template_id", "?"), exc_info=True)

    # -- Lifecycle --

    def attach_dispatcher(self, dispatcher: Any) -> None:
        """AD-654d: Late-bind dispatcher for work_item_assigned TaskEvent."""
        self._dispatcher = dispatcher

    async def start(self) -> None:
        """Open DB, create schema, start tick loop."""
        if self.db_path:
            self._db = await self._connection_factory.connect(self.db_path)
            await self._db.execute("PRAGMA foreign_keys = ON")
            self._db.row_factory = aiosqlite.Row
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
        await self._refresh_snapshot_cache()
        self._running = True
        self._tick_task = asyncio.create_task(self._tick_loop())
        logger.info("WorkItemStore started (tick=%.1fs)", self._tick_interval)

    async def stop(self) -> None:
        """Stop tick loop and close DB."""
        self._running = False
        if self._tick_task:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
            self._tick_task = None
        if self._db:
            await self._db.close()
            self._db = None
        logger.info("WorkItemStore stopped")

    # ======================================================================
    # WorkItem CRUD
    # ======================================================================

    async def create_work_item(self, **kwargs: Any) -> WorkItem:
        """Create and persist a new work item."""
        now = time.time()
        kwargs.setdefault("created_at", now)
        kwargs.setdefault("updated_at", now)
        # AD-498: Set initial status from work type registry if not explicitly provided
        work_type = kwargs.get("work_type", "task")
        if "status" not in kwargs:
            kwargs["status"] = self.work_type_registry.get_initial_status(work_type)
        item = WorkItem(**kwargs)
        if self._db:
            async with self._work_item_row_write_lock:
                try:
                    await self._db.execute(
                        """INSERT INTO work_items (
                            id, title, description, work_type, status, priority,
                            parent_id, depends_on, assigned_to, created_by,
                            created_at, updated_at, due_at, estimated_tokens,
                            actual_tokens, trust_requirement, required_capabilities,
                            tags, metadata, steps, verification, schedule,
                            ttl_seconds, template_id
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            item.id, item.title, item.description, item.work_type,
                            item.status, item.priority, item.parent_id,
                            json.dumps(item.depends_on), item.assigned_to,
                            item.created_by, item.created_at, item.updated_at,
                            item.due_at, item.estimated_tokens, item.actual_tokens,
                            item.trust_requirement,
                            json.dumps(item.required_capabilities),
                            json.dumps(item.tags), json.dumps(item.metadata),
                            json.dumps(item.steps), json.dumps(item.verification),
                            json.dumps(item.schedule), item.ttl_seconds,
                            item.template_id,
                        ),
                    )
                    req = ResourceRequirement(
                        work_item_id=item.id,
                        min_trust=item.trust_requirement,
                        priority=item.priority,
                        required_characteristics=[
                            {"skill": c, "min_proficiency": 0.5}
                            for c in item.required_capabilities
                        ],
                    )
                    await self._db.execute(
                        """INSERT INTO resource_requirements (
                            id, work_item_id, duration_estimate_seconds, from_date,
                            to_date, required_characteristics, min_trust,
                            department_constraint, priority, resource_preference, fulfilled
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            req.id, req.work_item_id,
                            req.duration_estimate_seconds, req.from_date,
                            req.to_date,
                            json.dumps(req.required_characteristics),
                            req.min_trust, req.department_constraint,
                            req.priority, json.dumps(req.resource_preference), 0,
                        ),
                    )
                    await self._db.commit()
                except BaseException:
                    try:
                        await self._db.execute("ROLLBACK")
                    except Exception:
                        pass
                    raise
        await self._refresh_snapshot_cache()
        self._emit(EventType.WORK_ITEM_CREATED, {"work_item": item.to_dict()})
        return item

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        """Fetch a single work item by ID."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM work_items WHERE id = ?", (work_item_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_work_item(row)

    async def list_work_items(
        self,
        status: str | None = None,
        assigned_to: str | None = None,
        work_type: str | None = None,
        parent_id: str | None = None,
        priority: int | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WorkItem]:
        """List work items with optional filters. Ordered by priority ASC, created_at DESC."""
        if not self._db:
            return []
        conditions: list[str] = []
        params: list[Any] = []
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if assigned_to is not None:
            conditions.append("assigned_to = ?")
            params.append(assigned_to)
        if work_type is not None:
            conditions.append("work_type = ?")
            params.append(work_type)
        if parent_id is not None:
            conditions.append("parent_id = ?")
            params.append(parent_id)
        if priority is not None:
            conditions.append("priority = ?")
            params.append(priority)
        where = " AND ".join(conditions) if conditions else "1=1"
        query = f"SELECT * FROM work_items WHERE {where} ORDER BY priority ASC, created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        items = [self._row_to_work_item(r) for r in rows]
        if tags:
            tag_set = set(tags)
            items = [i for i in items if tag_set.intersection(i.tags)]
        return items

    async def list_crew_session_recovery_candidates(
        self,
        *,
        limit: int,
    ) -> list[WorkItem]:
        """Return one globally bounded oldest-first CrewSession recovery scan."""
        if type(limit) is not int or not 1 <= limit <= 1_000:
            raise ValueError("crew_session_recovery_scan_limit_invalid")
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM work_items WHERE work_type = ? "
            "AND status IN (?, ?, ?) ORDER BY created_at ASC, id ASC LIMIT ?",
            ("crew_session", "open", "in_progress", "review", limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_work_item(row) for row in rows]

    async def install_child_plan_with_parent_metadata(
        self,
        parent_id: str,
        *,
        expected_parent_metadata: dict[str, Any],
        expected_status: str,
        expected_assigned_to: str,
        parent_patch: dict[str, Any],
        children: tuple[WorkItemPlanInsert, ...],
        source: str = "crew_session_plan_install",
    ) -> tuple[WorkItem, tuple[WorkItem, ...]]:
        """Atomically install a zero-child parent patch and its complete plan."""
        if (
            type(parent_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(parent_id) is None
            or type(expected_parent_metadata) is not dict
            or type(expected_status) is not str
            or not expected_status
            or type(expected_assigned_to) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(expected_assigned_to) is None
            or type(parent_patch) is not dict
            or any(type(key) is not str for key in parent_patch)
            or type(children) is not tuple
            or not 1 <= len(children) <= _MAX_WORK_ITEM_DIRECT_CHILDREN
            or any(type(child) is not WorkItemPlanInsert for child in children)
            or type(source) is not str
            or not source
        ):
            raise ValueError("work_item_plan_install_invalid")
        expected_bytes = _compact_exact_json_bytes(
            expected_parent_metadata,
            error="work_item_plan_install_invalid",
        )
        patch_bytes = _compact_exact_json_bytes(
            parent_patch,
            error="work_item_plan_install_invalid",
        )
        if (
            len(expected_bytes) > _MAX_WORK_ITEM_METADATA_BYTES
            or len(patch_bytes) > _MAX_WORK_ITEM_METADATA_BYTES
        ):
            raise ValueError("work_item_plan_install_invalid")
        child_ids = tuple(child.id for child in children)
        if len(set(child_ids)) != len(child_ids):
            raise ValueError("work_item_plan_install_invalid")
        child_id_set = set(child_ids)
        remaining_dependencies = {
            child.id: set(child.depends_on)
            for child in children
        }
        if any(
            child.id in dependencies
            or not dependencies.issubset(child_id_set)
            for child, dependencies in (
                (child, remaining_dependencies[child.id]) for child in children
            )
        ):
            raise ValueError("work_item_plan_install_invalid")
        completed: set[str] = set()
        while len(completed) < len(children):
            ready = {
                child_id
                for child_id, dependencies in remaining_dependencies.items()
                if child_id not in completed and dependencies.issubset(completed)
            }
            if not ready:
                raise ValueError("work_item_plan_install_invalid")
            completed.update(ready)
        if not self._db:
            raise ValueError("work_item_plan_install_unavailable")

        detached_expected = json.loads(expected_bytes.decode("utf-8"))
        detached_patch = json.loads(patch_bytes.decode("utf-8"))
        created: list[WorkItem] = []
        updated_parent: WorkItem | None = None
        async with self._work_item_row_write_lock:
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                parent = await self.get_work_item(parent_id)
                if parent is None:
                    raise ValueError("work_item_plan_parent_not_found")
                if (
                    parent.work_type != "crew_session"
                    or parent.status != expected_status
                    or parent.assigned_to != expected_assigned_to
                    or not _json_values_exactly_equal(
                        parent.metadata,
                        detached_expected,
                    )
                ):
                    raise ValueError("work_item_plan_parent_conflict")
                cursor = await self._db.execute(
                    "SELECT id FROM work_items WHERE parent_id = ? LIMIT ?",
                    (parent_id, _MAX_WORK_ITEM_DIRECT_CHILDREN + 1),
                )
                if await cursor.fetchone() is not None:
                    raise ValueError("work_item_plan_children_conflict")
                for child_id in child_ids:
                    cursor = await self._db.execute(
                        "SELECT id FROM work_items WHERE id = ?",
                        (child_id,),
                    )
                    if await cursor.fetchone() is not None:
                        raise ValueError("work_item_plan_child_id_conflict")

                merged_metadata = dict(parent.metadata)
                merged_metadata.update(detached_patch)
                merged_bytes = _compact_exact_json_bytes(
                    merged_metadata,
                    error="work_item_plan_install_invalid",
                )
                if len(merged_bytes) > _MAX_WORK_ITEM_METADATA_BYTES:
                    raise ValueError("work_item_metadata_too_large")
                now = time.time()
                for child_insert in children:
                    child = WorkItem(
                        id=child_insert.id,
                        title=child_insert.title,
                        description=child_insert.description,
                        work_type=child_insert.work_type,
                        status=self.work_type_registry.get_initial_status(
                            child_insert.work_type,
                        ),
                        priority=child_insert.priority,
                        parent_id=parent_id,
                        depends_on=list(child_insert.depends_on),
                        assigned_to=child_insert.assigned_to,
                        created_by=child_insert.created_by,
                        created_at=now,
                        updated_at=now,
                        trust_requirement=child_insert.trust_requirement,
                        required_capabilities=list(
                            child_insert.required_capabilities,
                        ),
                        metadata=dict(child_insert.metadata),
                    )
                    await self._db.execute(
                        """INSERT INTO work_items (
                            id, title, description, work_type, status, priority,
                            parent_id, depends_on, assigned_to, created_by,
                            created_at, updated_at, due_at, estimated_tokens,
                            actual_tokens, trust_requirement, required_capabilities,
                            tags, metadata, steps, verification, schedule,
                            ttl_seconds, template_id
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            child.id, child.title, child.description,
                            child.work_type, child.status, child.priority,
                            child.parent_id, json.dumps(child.depends_on),
                            child.assigned_to, child.created_by, child.created_at,
                            child.updated_at, child.due_at, child.estimated_tokens,
                            child.actual_tokens, child.trust_requirement,
                            json.dumps(child.required_capabilities),
                            json.dumps(child.tags), json.dumps(child.metadata),
                            json.dumps(child.steps), json.dumps(child.verification),
                            json.dumps(child.schedule), child.ttl_seconds,
                            child.template_id,
                        ),
                    )
                    requirement = ResourceRequirement(
                        work_item_id=child.id,
                        min_trust=child.trust_requirement,
                        priority=child.priority,
                        required_characteristics=[
                            {"skill": capability, "min_proficiency": 0.5}
                            for capability in child.required_capabilities
                        ],
                    )
                    await self._db.execute(
                        """INSERT INTO resource_requirements (
                            id, work_item_id, duration_estimate_seconds, from_date,
                            to_date, required_characteristics, min_trust,
                            department_constraint, priority, resource_preference,
                            fulfilled
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            requirement.id, requirement.work_item_id,
                            requirement.duration_estimate_seconds,
                            requirement.from_date, requirement.to_date,
                            json.dumps(requirement.required_characteristics),
                            requirement.min_trust,
                            requirement.department_constraint,
                            requirement.priority,
                            json.dumps(requirement.resource_preference),
                            0,
                        ),
                    )
                    created.append(child)
                await self._db.execute(
                    "UPDATE work_items SET metadata = ?, updated_at = ? WHERE id = ?",
                    (merged_bytes.decode("utf-8"), now, parent_id),
                )
                await self._db.commit()
                updated_parent = await self.get_work_item(parent_id)
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        if updated_parent is None:
            raise ValueError("work_item_plan_install_failed")
        await self._refresh_snapshot_cache()
        self._emit(
            EventType.WORK_ITEM_UPDATED,
            {"work_item": updated_parent.to_dict()},
        )
        for child in created:
            self._emit(EventType.WORK_ITEM_CREATED, {"work_item": child.to_dict()})
        return updated_parent, tuple(created)

    async def adopt_child_plan_with_parent_metadata(
        self,
        parent_id: str,
        *,
        expected_parent_metadata: dict[str, Any],
        expected_status: str,
        expected_assigned_to: str,
        parent_patch: dict[str, Any],
        expected_children: tuple[WorkItem, ...],
        source: str = "crew_session_plan_adoption",
    ) -> WorkItem:
        """Patch one parent only after an exact lock-held child snapshot proof."""
        if (
            type(parent_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(parent_id) is None
            or type(expected_parent_metadata) is not dict
            or type(expected_status) is not str
            or not expected_status
            or type(expected_assigned_to) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(expected_assigned_to) is None
            or type(parent_patch) is not dict
            or any(type(key) is not str for key in parent_patch)
            or type(source) is not str
            or not source
        ):
            raise ValueError("work_item_plan_adoption_invalid")
        expected_bytes = _compact_exact_json_bytes(
            expected_parent_metadata,
            error="work_item_plan_adoption_invalid",
        )
        patch_bytes = _compact_exact_json_bytes(
            parent_patch,
            error="work_item_plan_adoption_invalid",
        )
        if (
            len(expected_bytes) > _MAX_WORK_ITEM_METADATA_BYTES
            or len(patch_bytes) > _MAX_WORK_ITEM_METADATA_BYTES
        ):
            raise ValueError("work_item_plan_adoption_invalid")
        detached_expected = json.loads(expected_bytes.decode("utf-8"))
        detached_patch = json.loads(patch_bytes.decode("utf-8"))
        detached_children = _detach_plan_adoption_children(
            parent_id,
            expected_children,
        )
        if not self._db:
            raise ValueError("work_item_plan_adoption_unavailable")

        updated_parent: WorkItem | None = None
        async with self._work_item_row_write_lock:
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                parent = await self.get_work_item(parent_id)
                if parent is None:
                    raise ValueError("work_item_plan_parent_not_found")
                if (
                    parent.work_type != "crew_session"
                    or parent.status != expected_status
                    or parent.assigned_to != expected_assigned_to
                    or not _json_values_exactly_equal(
                        parent.metadata,
                        detached_expected,
                    )
                ):
                    raise ValueError("work_item_plan_parent_conflict")
                cursor = await self._db.execute(
                    "SELECT * FROM work_items WHERE parent_id = ? "
                    "ORDER BY id ASC LIMIT ?",
                    (parent_id, _MAX_WORK_ITEM_DIRECT_CHILDREN + 1),
                )
                rows = await cursor.fetchall()
                if (
                    len(rows) != len(detached_children)
                    or len(rows) > _MAX_WORK_ITEM_DIRECT_CHILDREN
                ):
                    raise ValueError("work_item_plan_children_conflict")
                live_children = tuple(self._row_to_work_item(row) for row in rows)
                for live, expected_child in zip(live_children, detached_children):
                    if not _json_values_exactly_equal(
                        live.to_dict(),
                        expected_child,
                    ):
                        raise ValueError("work_item_plan_children_conflict")
                merged_metadata = dict(parent.metadata)
                merged_metadata.update(detached_patch)
                merged_bytes = _compact_exact_json_bytes(
                    merged_metadata,
                    error="work_item_plan_adoption_invalid",
                )
                if len(merged_bytes) > _MAX_WORK_ITEM_METADATA_BYTES:
                    raise ValueError("work_item_metadata_too_large")
                await self._db.execute(
                    "UPDATE work_items SET metadata = ?, updated_at = ? WHERE id = ?",
                    (merged_bytes.decode("utf-8"), time.time(), parent_id),
                )
                await self._db.commit()
                updated_parent = await self.get_work_item(parent_id)
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        if updated_parent is None:
            raise ValueError("work_item_plan_adoption_failed")
        await self._refresh_snapshot_cache()
        self._emit(
            EventType.WORK_ITEM_UPDATED,
            {"work_item": updated_parent.to_dict(), "source": source},
        )
        return updated_parent

    async def compare_and_set_work_item_assignment(
        self,
        work_item_id: str,
        *,
        expected_parent_id: str,
        expected_status: str,
        expected_assigned_to: str | None,
        expected_depends_on: list[str],
        expected_metadata: dict[str, Any],
        new_assigned_to: str,
        metadata: dict[str, Any],
        source: str = "crew_session_assignment",
    ) -> WorkItem | None:
        """Atomically assign one exact untouched planned child."""
        if (
            any(
                type(value) is not str
                or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(value) is None
                for value in (
                    work_item_id,
                    expected_parent_id,
                    new_assigned_to,
                )
            )
            or type(expected_status) is not str
            or not expected_status
            or (
                expected_assigned_to is not None
                and (
                    type(expected_assigned_to) is not str
                    or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(
                        expected_assigned_to,
                    ) is None
                )
            )
            or type(expected_depends_on) is not list
            or any(type(value) is not str for value in expected_depends_on)
            or type(expected_metadata) is not dict
            or type(metadata) is not dict
            or type(source) is not str
            or not source
        ):
            raise ValueError("work_item_assignment_invalid")
        expected_metadata_bytes = _compact_exact_json_bytes(
            expected_metadata,
            error="work_item_assignment_invalid",
        )
        metadata_bytes = _compact_exact_json_bytes(
            metadata,
            error="work_item_assignment_invalid",
        )
        if (
            len(expected_metadata_bytes) > _MAX_WORK_ITEM_METADATA_BYTES
            or len(metadata_bytes) > _MAX_WORK_ITEM_METADATA_BYTES
        ):
            raise ValueError("work_item_assignment_invalid")
        if not self._db:
            return None
        detached_expected_metadata = json.loads(
            expected_metadata_bytes.decode("utf-8"),
        )
        updated: WorkItem | None = None
        async with self._work_item_row_write_lock:
            item = await self.get_work_item(work_item_id)
            if item is None:
                return None
            if (
                item.parent_id != expected_parent_id
                or item.status != expected_status
                or not _json_values_exactly_equal(
                    item.assigned_to,
                    expected_assigned_to,
                )
                or not _json_values_exactly_equal(
                    item.depends_on,
                    expected_depends_on,
                )
                or not _json_values_exactly_equal(
                    item.metadata,
                    detached_expected_metadata,
                )
            ):
                raise ValueError("work_item_assignment_conflict")
            now = time.time()
            try:
                await self._db.execute(
                    "UPDATE work_items SET assigned_to = ?, metadata = ?, "
                    "updated_at = ? WHERE id = ?",
                    (
                        new_assigned_to,
                        metadata_bytes.decode("utf-8"),
                        now,
                        work_item_id,
                    ),
                )
                await self._db.commit()
                updated = await self.get_work_item(work_item_id)
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        await self._refresh_snapshot_cache()
        self._emit(
            EventType.WORK_ITEM_UPDATED,
            {"work_item": updated.to_dict() if updated else {}},
        )
        self._emit(
            EventType.WORK_ITEM_ASSIGNED,
            {
                "work_item": updated.to_dict() if updated else {},
                "source": source,
            },
        )
        return updated

    async def update_work_item(self, work_item_id: str, **updates: Any) -> WorkItem | None:
        """Update work item fields. Sets updated_at. Emits 'work_item_updated'."""
        if not self._db:
            return None
        async with self._work_item_row_write_lock:
            item = await self.get_work_item(work_item_id)
            if not item:
                return None
            set_clauses: list[str] = []
            params: list[Any] = []
            for key, value in updates.items():
                if key in _IMMUTABLE_FIELDS:
                    continue
                if key in _JSON_FIELDS and not isinstance(value, str):
                    value = json.dumps(value)
                set_clauses.append(f"{key} = ?")
                params.append(value)
            if not set_clauses:
                return item
            set_clauses.append("updated_at = ?")
            params.append(time.time())
            params.append(work_item_id)
            await self._db.execute(
                f"UPDATE work_items SET {', '.join(set_clauses)} WHERE id = ?",
                params,
            )
            await self._db.commit()
            updated = await self.get_work_item(work_item_id)
        await self._refresh_snapshot_cache()
        self._emit(EventType.WORK_ITEM_UPDATED, {"work_item": updated.to_dict() if updated else {}})
        return updated

    async def set_steps(
        self, work_item_id: str, steps: list, *, gate_completion: bool = False,
        facilitator: str | None = None,
    ) -> "WorkItem | None":
        """AD-1080: seed/replace a work item's Todo checklist (the room plan).
        Each step normalizes to {label, status}; a bare string becomes a pending
        step. ``gate_completion`` marks the item so it cannot transition to 'done'
        until every step is senior-confirmed. AD-1087: ``facilitator`` records the
        plan creator so they can confirm/complete regardless of rank."""
        item = await self.get_work_item(work_item_id)
        if not item:
            return None
        norm: list[dict[str, Any]] = []
        for s in steps or []:
            if isinstance(s, str):
                label = s.strip()
                if label:
                    norm.append({"label": label, "status": "pending"})
                continue
            if not isinstance(s, dict):
                continue
            label = str(s.get("label", "")).strip()
            if not label:
                continue
            st = str(s.get("status", "pending"))
            if st not in STEP_STATUSES:
                st = "pending"
            entry: dict[str, Any] = {"label": label, "status": st}
            for k in ("assigned_to", "submitted_by", "confirmed_by", "note"):
                if s.get(k):
                    entry[k] = s[k]
            norm.append(entry)
        updates: dict[str, Any] = {"steps": norm}
        if gate_completion or facilitator:
            md = dict(item.metadata or {})
            if gate_completion:
                md["steps_gate_completion"] = True
            if facilitator:
                md["facilitator"] = facilitator
            updates["metadata"] = md
        return await self.update_work_item(work_item_id, **updates)

    async def update_step(
        self, work_item_id: str, index: int, *,
        status: str | None = None, actor: str | None = None,
        note: str | None = None,
    ) -> "WorkItem | None":
        """AD-1080: transition one Todo step (the senior-validation loop). Records
        the actor by destination status (assigned_to on in_progress, submitted_by
        on submitted, confirmed_by on done/rejected). Returns None on a bad index
        or an invalid step transition (prior steps left untouched)."""
        item = await self.get_work_item(work_item_id)
        if not item or index < 0 or index >= len(item.steps):
            return None
        steps = [dict(s) for s in item.steps]
        step = steps[index]
        old = str(step.get("status", "pending"))
        if status is not None and status != old:
            if not validate_step_transition(old, status):
                logger.warning(
                    "AD-1080: invalid step transition %s->%s on %s[%d]",
                    old, status, work_item_id, index,
                )
                return None
            step["status"] = status
            if actor:
                if status == "in_progress":
                    step["assigned_to"] = actor
                elif status == "submitted":
                    step["submitted_by"] = actor
                elif status in ("done", "rejected"):
                    step["confirmed_by"] = actor
        if note is not None:
            step["note"] = note
        return await self.update_work_item(work_item_id, steps=steps)

    def _validate_work_item_status_transition(
        self, item: WorkItem, new_status: str,
    ) -> bool:
        if (
            new_status == "done"
            and (item.metadata or {}).get("steps_gate_completion")
            and not _all_steps_done(item.steps)
        ):
            logger.info(
                "AD-1080: refusing 'done' for %s — %d/%d steps confirmed",
                item.id,
                sum(1 for step in item.steps if str(step.get("status")) == "done"),
                len(item.steps),
            )
            return False
        valid, reason = self.work_type_registry.validate_transition(
            item.work_type, item.status, new_status,
        )
        if not valid:
            logger.warning("Invalid transition for %s: %s", item.id, reason)
            return False
        if item.assigned_to is None and self.work_type_registry.transition_requires_assignment(
            item.work_type, item.status, new_status,
        ):
            logger.warning(
                "BF-608: refusing %s transition '%s' → '%s' for work item %s: "
                "this transition requires assignment but the item is unassigned; "
                "it remains '%s' and dispatchable until an agent claims it",
                item.work_type, item.status, new_status, item.id, item.status,
            )
            return False
        return True

    async def merge_work_item_metadata(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any] | None = None,
        expected_absent_keys: frozenset[str] = frozenset(),
        expected_present_keys: frozenset[str] = frozenset(),
        expected_work_type: str | None = None,
        expected_status: str | None = None,
        expected_assigned_to: str | None = None,
        expected_assigned_to_exact: (
            str | None | _OmittedWorkItemExpectation
        ) = _OMITTED_WORK_ITEM_EXPECTATION,
        expected_parent_id: (
            str | None | _OmittedWorkItemExpectation
        ) = _OMITTED_WORK_ITEM_EXPECTATION,
        expected_depends_on: (
            list[str] | _OmittedWorkItemExpectation
        ) = _OMITTED_WORK_ITEM_EXPECTATION,
        expected_unresolved_dependency_ids: (
            list[str] | _OmittedWorkItemExpectation
        ) = _OMITTED_WORK_ITEM_EXPECTATION,
        new_status: str | None = None,
        actual_tokens_delta: int = 0,
        source: str = "system",
    ) -> WorkItem | None:
        """Atomically shallow-merge top-level metadata for this store instance."""
        if not self._db:
            return None
        if type(patch) is not dict or any(type(key) is not str for key in patch):
            raise ValueError("work_item_metadata_patch_invalid")
        if expected is not None and (
            type(expected) is not dict
            or any(type(key) is not str for key in expected)
        ):
            raise ValueError("work_item_metadata_expected_invalid")
        key_expectations = (expected_absent_keys, expected_present_keys)
        if any(
            type(keys) is not frozenset
            or len(keys) > _MAX_WORK_ITEM_METADATA_EXPECTED_KEYS
            or any(
                not _valid_work_item_metadata_expectation_key(key)
                for key in keys
            )
            for keys in key_expectations
        ) or (
            expected is not None
            and not expected_absent_keys.isdisjoint(expected)
        ) or not expected_absent_keys.isdisjoint(expected_present_keys):
            raise ValueError("work_item_metadata_expected_invalid")
        if (
            type(actual_tokens_delta) is not int
            or not 0 <= actual_tokens_delta <= _MAX_WORK_ITEM_ACTUAL_TOKENS
        ):
            raise ValueError("work_item_actual_tokens_delta_invalid")
        if (
            expected_assigned_to_exact is not _OMITTED_WORK_ITEM_EXPECTATION
            and expected_assigned_to_exact is not None
            and type(expected_assigned_to_exact) is not str
        ):
            raise ValueError("work_item_expected_state_invalid")
        if (
            expected_parent_id is not _OMITTED_WORK_ITEM_EXPECTATION
            and expected_parent_id is not None
            and type(expected_parent_id) is not str
        ):
            raise ValueError("work_item_expected_state_invalid")
        if (
            expected_depends_on is not _OMITTED_WORK_ITEM_EXPECTATION
            and (
                type(expected_depends_on) is not list
                or any(type(value) is not str for value in expected_depends_on)
            )
        ):
            raise ValueError("work_item_expected_state_invalid")
        if (
            expected_unresolved_dependency_ids
            is not _OMITTED_WORK_ITEM_EXPECTATION
            and (
                type(expected_unresolved_dependency_ids) is not list
                or any(
                    type(value) is not str
                    for value in expected_unresolved_dependency_ids
                )
            )
        ):
            raise ValueError("work_item_expected_state_invalid")
        async with self._work_item_row_write_lock:
            item = await self.get_work_item(work_item_id)
            if item is None:
                return None
            if (
                type(item.actual_tokens) is not int
                or not 0 <= item.actual_tokens <= _MAX_WORK_ITEM_ACTUAL_TOKENS
            ):
                raise ValueError("work_item_actual_tokens_current_invalid")
            if item.actual_tokens > _MAX_WORK_ITEM_ACTUAL_TOKENS - actual_tokens_delta:
                raise ValueError("work_item_actual_tokens_overflow")
            if (
                (expected_work_type is not None and item.work_type != expected_work_type)
                or (expected_status is not None and item.status != expected_status)
                or (
                    expected_assigned_to is not None
                    and item.assigned_to != expected_assigned_to
                )
                or (
                    expected_assigned_to_exact
                    is not _OMITTED_WORK_ITEM_EXPECTATION
                    and not _json_values_exactly_equal(
                        item.assigned_to,
                        expected_assigned_to_exact,
                    )
                )
                or (
                    expected_parent_id is not _OMITTED_WORK_ITEM_EXPECTATION
                    and not _json_values_exactly_equal(
                        item.parent_id,
                        expected_parent_id,
                    )
                )
                or (
                    expected_depends_on is not _OMITTED_WORK_ITEM_EXPECTATION
                    and not _json_values_exactly_equal(
                        item.depends_on,
                        expected_depends_on,
                    )
                )
            ):
                raise ValueError("work_item_state_conflict")
            if (
                expected_unresolved_dependency_ids
                is not _OMITTED_WORK_ITEM_EXPECTATION
            ):
                if type(item.depends_on) is not list:
                    raise ValueError("work_item_dependency_state_conflict")
                live_unresolved: list[str] = []
                for dependency_id in item.depends_on:
                    cursor = await self._db.execute(
                        "SELECT status FROM work_items WHERE id = ?",
                        (dependency_id,),
                    )
                    dependency_row = await cursor.fetchone()
                    if (
                        dependency_row is None
                        or dependency_row["status"] != "done"
                    ):
                        live_unresolved.append(dependency_id)
                if not _json_values_exactly_equal(
                    live_unresolved,
                    expected_unresolved_dependency_ids,
                ):
                    raise ValueError("work_item_dependency_state_conflict")
            current = dict(item.metadata or {})
            if expected is not None:
                for key, value in expected.items():
                    current_value = current.get(key, _MISSING_METADATA_VALUE)
                    if current_value is _MISSING_METADATA_VALUE:
                        if value is not None:
                            raise ValueError("work_item_metadata_conflict")
                    elif not _json_values_exactly_equal(current_value, value):
                        raise ValueError("work_item_metadata_conflict")
            if any(key in current for key in expected_absent_keys):
                raise ValueError("work_item_metadata_conflict")
            if any(key not in current for key in expected_present_keys):
                raise ValueError("work_item_metadata_conflict")

            merged = dict(current)
            merged.update(patch)
            status_changed = new_status is not None and new_status != item.status
            if status_changed and not self._validate_work_item_status_transition(
                dataclasses.replace(item, metadata=merged), new_status,
            ):
                return None
            if merged == current and not status_changed and actual_tokens_delta == 0:
                return item

            serialized = json.dumps(
                merged,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            if len(serialized.encode("utf-8")) > _MAX_WORK_ITEM_METADATA_BYTES:
                raise ValueError("work_item_metadata_too_large")

            old_status = item.status
            now = time.time()
            try:
                if status_changed:
                    if actual_tokens_delta:
                        await self._db.execute(
                            "UPDATE work_items SET metadata = ?, status = ?, "
                            "actual_tokens = actual_tokens + ?, updated_at = ? "
                            "WHERE id = ?",
                            (
                                serialized,
                                new_status,
                                actual_tokens_delta,
                                now,
                                work_item_id,
                            ),
                        )
                    else:
                        await self._db.execute(
                            "UPDATE work_items SET metadata = ?, status = ?, updated_at = ? "
                            "WHERE id = ?",
                            (serialized, new_status, now, work_item_id),
                        )
                else:
                    if actual_tokens_delta:
                        await self._db.execute(
                            "UPDATE work_items SET metadata = ?, "
                            "actual_tokens = actual_tokens + ?, updated_at = ? WHERE id = ?",
                            (serialized, actual_tokens_delta, now, work_item_id),
                        )
                    else:
                        await self._db.execute(
                            "UPDATE work_items SET metadata = ?, updated_at = ? WHERE id = ?",
                            (serialized, now, work_item_id),
                        )
                await self._db.commit()
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise

            updated = await self.get_work_item(work_item_id)
        await self._refresh_snapshot_cache()
        self._emit(
            EventType.WORK_ITEM_UPDATED,
            {"work_item": updated.to_dict() if updated else {}},
        )
        if status_changed:
            self._emit(EventType.WORK_ITEM_STATUS_CHANGED, {
                "work_item": updated.to_dict() if updated else {},
                "old_status": old_status,
                "new_status": new_status,
                "source": source,
            })
        return updated

    async def compare_and_set_work_item_verification(
        self,
        work_item_id: str,
        verification: dict[str, Any],
        *,
        expected_verification: dict[str, Any],
        expected_work_type: str,
        expected_status: str,
        expected_assigned_to: str,
        expected_parent_id: str,
        expected_title: str,
        expected_description: str,
        expected_depends_on: list[str],
        expected_metadata: dict[str, Any],
        expected_actual_tokens: int,
        metadata_patch: dict[str, Any] | None = None,
        actual_tokens_delta: int = 0,
        source: str = "crew_session_finalizer",
    ) -> WorkItem | None:
        """Commit one exact child verification record and correction-token delta."""
        if type(work_item_id) is not str or not work_item_id:
            raise ValueError("work_item_verification_invalid")
        if type(verification) is not dict or type(expected_verification) is not dict:
            raise ValueError("work_item_verification_invalid")
        if type(expected_metadata) is not dict or (
            metadata_patch is not None and type(metadata_patch) is not dict
        ):
            raise ValueError("work_item_verification_invalid")
        if (
            type(expected_depends_on) is not list
            or any(type(value) is not str for value in expected_depends_on)
            or any(
                type(value) is not str
                for value in (
                    expected_work_type,
                    expected_status,
                    expected_assigned_to,
                    expected_parent_id,
                    expected_title,
                    expected_description,
                    source,
                )
            )
        ):
            raise ValueError("work_item_verification_invalid")
        if (
            type(expected_actual_tokens) is not int
            or not 0 <= expected_actual_tokens <= _MAX_WORK_ITEM_ACTUAL_TOKENS
            or type(actual_tokens_delta) is not int
            or not 0 <= actual_tokens_delta <= _MAX_WORK_ITEM_ACTUAL_TOKENS
        ):
            raise ValueError("work_item_actual_tokens_delta_invalid")
        serialized = _compact_exact_json_bytes(
            verification,
            error="work_item_verification_invalid",
        )
        if len(serialized) > _MAX_WORK_ITEM_VERIFICATION_BYTES:
            raise ValueError("work_item_verification_too_large")
        expected_verification_bytes = _compact_exact_json_bytes(
            expected_verification,
            error="work_item_verification_invalid",
        )
        if len(expected_verification_bytes) > _MAX_WORK_ITEM_VERIFICATION_BYTES:
            raise ValueError("work_item_verification_invalid")
        expected_metadata_bytes = _compact_exact_json_bytes(
            expected_metadata,
            error="work_item_verification_invalid",
        )
        if len(expected_metadata_bytes) > _MAX_WORK_ITEM_METADATA_BYTES:
            raise ValueError("work_item_verification_invalid")
        detached_expected_verification = json.loads(expected_verification_bytes)
        detached_expected_metadata = json.loads(expected_metadata_bytes)
        metadata_patch_bytes = _compact_exact_json_bytes(
            metadata_patch or {},
            error="work_item_verification_invalid",
        )
        if len(metadata_patch_bytes) > _MAX_WORK_ITEM_METADATA_BYTES:
            raise ValueError("work_item_verification_invalid")
        detached_metadata_patch = json.loads(metadata_patch_bytes)
        detached_expected_depends_on = list(expected_depends_on)
        if not self._db:
            return None

        async with self._work_item_row_write_lock:
            item = await self.get_work_item(work_item_id)
            if item is None:
                return None
            if (
                item.work_type != expected_work_type
                or item.status != expected_status
                or item.assigned_to != expected_assigned_to
                or item.parent_id != expected_parent_id
                or item.title != expected_title
                or item.description != expected_description
                or not _json_values_exactly_equal(
                    item.depends_on,
                    detached_expected_depends_on,
                )
                or not _json_values_exactly_equal(
                    item.metadata,
                    detached_expected_metadata,
                )
                or not _json_values_exactly_equal(
                    item.verification,
                    detached_expected_verification,
                )
                or type(item.actual_tokens) is not int
                or item.actual_tokens != expected_actual_tokens
            ):
                raise ValueError("work_item_verification_conflict")
            if item.actual_tokens > _MAX_WORK_ITEM_ACTUAL_TOKENS - actual_tokens_delta:
                raise ValueError("work_item_actual_tokens_overflow")
            merged_metadata = dict(item.metadata)
            merged_metadata.update(detached_metadata_patch)
            merged_metadata_bytes = _compact_exact_json_bytes(
                merged_metadata,
                error="work_item_verification_invalid",
            )
            if len(merged_metadata_bytes) > _MAX_WORK_ITEM_METADATA_BYTES:
                raise ValueError("work_item_verification_invalid")
            now = time.time()
            try:
                await self._db.execute(
                    "UPDATE work_items SET verification = ?, metadata = ?, "
                    "actual_tokens = actual_tokens + ?, updated_at = ? WHERE id = ?",
                    (
                        serialized.decode("utf-8"),
                        merged_metadata_bytes.decode("utf-8"),
                        actual_tokens_delta,
                        now,
                        work_item_id,
                    ),
                )
                await self._db.commit()
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            updated = await self.get_work_item(work_item_id)

        await self._refresh_snapshot_cache()
        self._emit(
            EventType.WORK_ITEM_UPDATED,
            {"work_item": updated.to_dict() if updated else {}},
        )
        return updated

    async def publish_work_item_metadata_with_child_barrier(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected: dict[str, Any],
        expected_absent_keys: frozenset[str],
        expected_present_keys: frozenset[str],
        expected_work_type: str,
        expected_status: str,
        expected_assigned_to: str,
        expected_direct_children: tuple[dict[str, Any], ...],
        new_status: str,
        source: str = "crew_session_verified_result",
    ) -> WorkItem | None:
        """Publish parent metadata/status after one exact direct-child proof."""
        if (
            type(patch) is not dict
            or any(type(key) is not str for key in patch)
            or type(expected) is not dict
            or any(type(key) is not str for key in expected)
            or any(
                type(value) is not str or not value
                for value in (
                    expected_work_type,
                    expected_status,
                    expected_assigned_to,
                    new_status,
                    source,
                )
            )
        ):
            raise ValueError("work_item_metadata_expected_invalid")
        key_expectations = (expected_absent_keys, expected_present_keys)
        if any(
            type(keys) is not frozenset
            or len(keys) > _MAX_WORK_ITEM_METADATA_EXPECTED_KEYS
            or any(
                not _valid_work_item_metadata_expectation_key(key)
                for key in keys
            )
            for keys in key_expectations
        ) or not expected_absent_keys.isdisjoint(expected) or not (
            expected_absent_keys.isdisjoint(expected_present_keys)
        ):
            raise ValueError("work_item_metadata_expected_invalid")
        patch_bytes = _compact_exact_json_bytes(
            patch,
            error="work_item_metadata_patch_invalid",
        )
        expected_bytes = _compact_exact_json_bytes(
            expected,
            error="work_item_metadata_expected_invalid",
        )
        if (
            len(patch_bytes) > _MAX_WORK_ITEM_METADATA_BYTES
            or len(expected_bytes) > _MAX_WORK_ITEM_METADATA_BYTES
        ):
            raise ValueError("work_item_metadata_too_large")
        detached_patch = json.loads(patch_bytes.decode("utf-8"))
        detached_expected = json.loads(expected_bytes.decode("utf-8"))
        detached_children = _detach_direct_child_snapshots(
            work_item_id,
            expected_direct_children,
        )
        if not self._db:
            return None

        status_changed = False
        old_status = expected_status
        updated: WorkItem | None = None
        async with self._work_item_row_write_lock:
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                item = await self.get_work_item(work_item_id)
                if item is None:
                    await self._db.execute("ROLLBACK")
                    return None
                if (
                    item.work_type != expected_work_type
                    or item.status != expected_status
                    or item.assigned_to != expected_assigned_to
                ):
                    raise ValueError("work_item_state_conflict")
                current = dict(item.metadata or {})
                for key, value in detached_expected.items():
                    current_value = current.get(key, _MISSING_METADATA_VALUE)
                    if current_value is _MISSING_METADATA_VALUE:
                        if value is not None:
                            raise ValueError("work_item_metadata_conflict")
                    elif not _json_values_exactly_equal(current_value, value):
                        raise ValueError("work_item_metadata_conflict")
                if any(key in current for key in expected_absent_keys):
                    raise ValueError("work_item_metadata_conflict")
                if any(key not in current for key in expected_present_keys):
                    raise ValueError("work_item_metadata_conflict")

                cursor = await self._db.execute(
                    "SELECT * FROM work_items WHERE parent_id = ? "
                    "ORDER BY id ASC LIMIT ?",
                    (work_item_id, _MAX_WORK_ITEM_DIRECT_CHILDREN + 1),
                )
                rows = await cursor.fetchall()
                if (
                    not rows
                    or len(rows) > _MAX_WORK_ITEM_DIRECT_CHILDREN
                    or len(rows) != len(detached_children)
                ):
                    raise ValueError("work_item_child_barrier_conflict")
                live_children = tuple(self._row_to_work_item(row) for row in rows)
                for live, expected_child in zip(live_children, detached_children):
                    if not _json_values_exactly_equal(
                        _work_item_child_snapshot(live),
                        expected_child,
                    ):
                        raise ValueError("work_item_child_barrier_conflict")

                merged = dict(current)
                merged.update(detached_patch)
                status_changed = new_status != item.status
                if status_changed and not self._validate_work_item_status_transition(
                    dataclasses.replace(item, metadata=merged),
                    new_status,
                ):
                    await self._db.execute("ROLLBACK")
                    return None
                serialized = _compact_exact_json_bytes(
                    merged,
                    error="work_item_metadata_invalid",
                )
                if len(serialized) > _MAX_WORK_ITEM_METADATA_BYTES:
                    raise ValueError("work_item_metadata_too_large")
                now = time.time()
                await self._db.execute(
                    "UPDATE work_items SET metadata = ?, status = ?, "
                    "updated_at = ? WHERE id = ?",
                    (
                        serialized.decode("utf-8"),
                        new_status,
                        now,
                        work_item_id,
                    ),
                )
                await self._db.commit()
                updated = await self.get_work_item(work_item_id)
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise

        await self._refresh_snapshot_cache()
        self._emit(
            EventType.WORK_ITEM_UPDATED,
            {"work_item": updated.to_dict() if updated else {}},
        )
        if status_changed:
            self._emit(EventType.WORK_ITEM_STATUS_CHANGED, {
                "work_item": updated.to_dict() if updated else {},
                "old_status": old_status,
                "new_status": new_status,
                "source": source,
            })
        return updated

    async def transition_work_item(
        self, work_item_id: str, new_status: str, source: str = "system",
    ) -> WorkItem | None:
        """Transition work item status with validation."""
        if not self._db:
            return None
        async with self._work_item_row_write_lock:
            item = await self.get_work_item(work_item_id)
            if not item:
                return None
            # BF-606: A same-status transition is an idempotent no-op, not a state
            # machine violation. ``work_item_dispatched`` is delivered at-least-once
            # (broadcast fan-out to every crew agent, AD-855 capability-gap resume
            # which sets in_progress *then* re-dispatches, and bus redelivery), so an
            # already-in_progress item is repeatedly re-dispatched. Treating
            # ``in_progress -> in_progress`` as invalid spammed "Invalid transition"
            # warnings dozens of times for a single stuck item (observed: work item
            # 1e0ffcdb7b57) and returned None, which callers read as failure. Return
            # the item unchanged: no DB write, no STATUS_CHANGED event, no warning.
            if new_status == item.status:
                return item
            if not self._validate_work_item_status_transition(item, new_status):
                return None
            old_status = item.status
            now = time.time()
            await self._db.execute(
                "UPDATE work_items SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, now, work_item_id),
            )
            await self._db.commit()
            updated = await self.get_work_item(work_item_id)
        await self._refresh_snapshot_cache()
        self._emit(EventType.WORK_ITEM_STATUS_CHANGED, {
            "work_item": updated.to_dict() if updated else {},
            "old_status": old_status,
            "new_status": new_status,
        })
        return updated

    async def delete_work_item(self, work_item_id: str) -> bool:
        """Delete a work item and its associated bookings/requirements. Returns True if found."""
        if not self._db:
            return False
        async with self._work_item_row_write_lock:
            item = await self.get_work_item(work_item_id)
            if not item:
                return False
            try:
                cursor = await self._db.execute(
                    "SELECT id FROM bookings WHERE work_item_id = ?",
                    (work_item_id,),
                )
                booking_rows = await cursor.fetchall()
                booking_ids = [row["id"] for row in booking_rows]
                for booking_id in booking_ids:
                    await self._db.execute(
                        "DELETE FROM booking_timestamps WHERE booking_id = ?",
                        (booking_id,),
                    )
                    await self._db.execute(
                        "DELETE FROM booking_journals WHERE booking_id = ?",
                        (booking_id,),
                    )
                await self._db.execute(
                    "DELETE FROM bookings WHERE work_item_id = ?",
                    (work_item_id,),
                )
                await self._db.execute(
                    "DELETE FROM resource_requirements WHERE work_item_id = ?",
                    (work_item_id,),
                )
                await self._db.execute(
                    "DELETE FROM work_items WHERE id = ?",
                    (work_item_id,),
                )
                await self._db.commit()
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        await self._refresh_snapshot_cache()
        return True

    async def create_from_template(
        self,
        template_id: str,
        variables: dict[str, str] | None = None,
        overrides: dict | None = None,
        created_by: str = "captain",
    ) -> WorkItem:
        """Create a work item from a template with variable substitution."""
        kwargs = self.template_store.instantiate(template_id, variables, overrides)
        kwargs["created_by"] = created_by
        return await self.create_work_item(**kwargs)

    # ======================================================================
    # Assignment Engine
    # ======================================================================

    async def assign_work_item(
        self,
        work_item_id: str,
        resource_id: str,
        source: str = "captain",
    ) -> Booking | None:
        """Push assignment: Captain assigns work directly to an agent."""
        resource = self.get_resource(resource_id)
        if not resource:
            return None
        async with self._work_item_row_write_lock:
            item = await self.get_work_item(work_item_id)
            if not item:
                return None
            if not self._check_eligibility(resource, item):
                return None
            now = time.time()
            booking = Booking(
                resource_id=resource_id,
                work_item_id=work_item_id,
                status="scheduled",
                start_time=now,
            )
            # Find requirement to mark fulfilled
            req_id = None
            if self._db:
                cursor = await self._db.execute(
                    "SELECT id FROM resource_requirements WHERE work_item_id = ? AND fulfilled = 0 LIMIT 1",
                    (work_item_id,),
                )
                req_row = await cursor.fetchone()
                if req_row:
                    req_id = req_row["id"]
                    await self._db.execute(
                        "UPDATE resource_requirements SET fulfilled = 1 WHERE id = ?",
                        (req_id,),
                    )
                booking.requirement_id = req_id
                await self._db.execute(
                    """INSERT INTO bookings (
                        id, resource_id, work_item_id, requirement_id, status,
                        start_time, end_time, actual_start, actual_end, total_tokens_consumed
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        booking.id, booking.resource_id, booking.work_item_id,
                        booking.requirement_id, booking.status, booking.start_time,
                        booking.end_time, booking.actual_start, booking.actual_end,
                        booking.total_tokens_consumed,
                    ),
                )
                # Record timestamp
                await self._record_timestamp(booking.id, "scheduled", source)
                # Update work item
                await self._db.execute(
                    "UPDATE work_items SET assigned_to = ?, status = ?, updated_at = ? WHERE id = ?",
                    (resource_id, "scheduled", now, work_item_id),
                )
                await self._db.commit()
            updated_item = await self.get_work_item(work_item_id) or item
        await self._refresh_snapshot_cache()
        self._emit(EventType.WORK_ITEM_ASSIGNED, {
            "work_item": updated_item.to_dict(),
            "booking": booking.to_dict(),
            "resource": resource.to_dict(),
        })

        # AD-654d: Emit TaskEvent to notify the assigned agent
        if self._dispatcher and resource_id:
            try:
                from probos.activation import task_event_for_agent
                event = task_event_for_agent(
                    agent_id=resource_id,
                    source_type="workforce",
                    source_id=work_item_id,
                    event_type="work_item_assigned",
                    priority=Priority.NORMAL,
                    payload={
                        "work_item_id": work_item_id,
                        "title": item.title,
                        "description": item.description,
                        "work_type": item.work_type,
                        "status": "scheduled",
                        "assigned_by": source,
                    },
                )
                await self._dispatcher.dispatch(event)
            except Exception:
                logger.debug("AD-654d: work_item_assigned TaskEvent emission failed", exc_info=True)

        return booking

    async def claim_work_item(
        self,
        resource_id: str,
        work_type: str | None = None,
        department: str | None = None,
    ) -> tuple[WorkItem, Booking] | None:
        """Pull assignment: Agent claims highest-priority eligible unassigned work."""
        resource = self.get_resource(resource_id)
        if not resource:
            return None
        if not self._db:
            return None
        # Find eligible unassigned work
        conditions = ["status = 'open'", "assigned_to IS NULL"]
        params: list[Any] = []
        if work_type:
            conditions.append("work_type = ?")
            params.append(work_type)
        where = " AND ".join(conditions)
        cursor = await self._db.execute(
            f"SELECT * FROM work_items WHERE {where} ORDER BY priority ASC, created_at ASC LIMIT 50",
            params,
        )
        rows = await cursor.fetchall()
        for row in rows:
            item = self._row_to_work_item(row)
            if department and hasattr(resource, 'department') and resource.department != department:
                continue
            if self._check_eligibility(resource, item):
                booking = await self.assign_work_item(item.id, resource_id, source="agent")
                if booking:
                    updated_item = await self.get_work_item(item.id) or item
                    self._emit(EventType.WORK_ITEM_CLAIMED, {
                        "work_item": updated_item.to_dict(),
                        "booking": booking.to_dict(),
                        "resource": resource.to_dict(),
                    })
                    return (updated_item, booking)
        return None

    async def unassign_work_item(self, work_item_id: str, reason: str = "") -> bool:
        """Remove assignment. Cancels active booking. Resets assigned_to to NULL."""
        if not self._db:
            return False
        item = await self.get_work_item(work_item_id)
        if not item or not item.assigned_to:
            return False
        # Cancel active bookings
        cursor = await self._db.execute(
            "SELECT id FROM bookings WHERE work_item_id = ? AND status NOT IN ('completed', 'cancelled')",
            (work_item_id,),
        )
        booking_rows = await cursor.fetchall()
        for row in booking_rows:
            await self.cancel_booking(row["id"])
        # Reset assignment
        async with self._work_item_row_write_lock:
            item = await self.get_work_item(work_item_id)
            if not item or not item.assigned_to:
                return False
            await self._db.execute(
                "UPDATE work_items SET assigned_to = NULL, status = 'open', updated_at = ? WHERE id = ?",
                (time.time(), work_item_id),
            )
            await self._db.commit()
        await self._refresh_snapshot_cache()
        return True

    # ======================================================================
    # Booking lifecycle
    # ======================================================================

    async def start_booking(self, booking_id: str) -> Booking | None:
        """Transition booking: scheduled → active."""
        if not self._db:
            return None
        booking = await self.get_booking(booking_id)
        if not booking or booking.status != "scheduled":
            return None
        now = time.time()
        await self._db.execute(
            "UPDATE bookings SET status = 'active', actual_start = ? WHERE id = ?",
            (now, booking_id),
        )
        await self._record_timestamp(booking_id, "active", "system")
        await self._db.commit()
        # Update work item status
        async with self._work_item_row_write_lock:
            item = await self.get_work_item(booking.work_item_id)
            if item is not None:
                await self._db.execute(
                    "UPDATE work_items SET status = 'in_progress', updated_at = ? WHERE id = ?",
                    (now, booking.work_item_id),
                )
                await self._db.commit()
        await self._refresh_snapshot_cache()
        updated = await self.get_booking(booking_id)
        self._emit(EventType.BOOKING_STARTED, {"booking": updated.to_dict() if updated else {}})
        return updated

    async def pause_booking(self, booking_id: str) -> Booking | None:
        """Transition booking: active → on_break."""
        if not self._db:
            return None
        booking = await self.get_booking(booking_id)
        if not booking or booking.status != "active":
            return None
        await self._db.execute(
            "UPDATE bookings SET status = 'on_break' WHERE id = ?", (booking_id,),
        )
        await self._record_timestamp(booking_id, "on_break", "system")
        await self._db.commit()
        return await self.get_booking(booking_id)

    async def resume_booking(self, booking_id: str) -> Booking | None:
        """Transition booking: on_break → active."""
        if not self._db:
            return None
        booking = await self.get_booking(booking_id)
        if not booking or booking.status != "on_break":
            return None
        await self._db.execute(
            "UPDATE bookings SET status = 'active' WHERE id = ?", (booking_id,),
        )
        await self._record_timestamp(booking_id, "active", "system")
        await self._db.commit()
        return await self.get_booking(booking_id)

    async def complete_booking(self, booking_id: str, tokens_consumed: int = 0) -> Booking | None:
        """Transition booking: active → completed. Generates journal entries."""
        if not self._db:
            return None
        if (
            type(tokens_consumed) is not int
            or not 0 <= tokens_consumed <= _MAX_WORK_ITEM_ACTUAL_TOKENS
        ):
            raise ValueError("work_item_actual_tokens_delta_invalid")
        async with self._work_item_row_write_lock:
            booking = await self.get_booking(booking_id)
            if not booking or booking.status not in ("active", "scheduled"):
                return None
            item = (
                await self.get_work_item(booking.work_item_id)
                if booking.work_item_id
                else None
            )
            if item is not None:
                if (
                    type(item.actual_tokens) is not int
                    or not 0
                    <= item.actual_tokens
                    <= _MAX_WORK_ITEM_ACTUAL_TOKENS
                ):
                    raise ValueError("work_item_actual_tokens_current_invalid")
                if (
                    item.actual_tokens
                    > _MAX_WORK_ITEM_ACTUAL_TOKENS - tokens_consumed
                ):
                    raise ValueError("work_item_actual_tokens_overflow")
            now = time.time()
            try:
                await self._db.execute(
                    "UPDATE bookings SET status = 'completed', actual_end = ?, "
                    "total_tokens_consumed = ? WHERE id = ?",
                    (now, tokens_consumed, booking_id),
                )
                await self._record_timestamp(booking_id, "completed", "system")
                if item is not None and tokens_consumed:
                    await self._db.execute(
                        "UPDATE work_items SET actual_tokens = actual_tokens + ?, "
                        "updated_at = ? WHERE id = ?",
                        (tokens_consumed, now, item.id),
                    )
                await self._db.commit()
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        journal = await self.generate_journal(booking_id)
        await self._refresh_snapshot_cache()
        updated = await self.get_booking(booking_id)
        self._emit(EventType.BOOKING_COMPLETED, {
            "booking": updated.to_dict() if updated else {},
            "journal": [j.to_dict() for j in journal],
        })
        return updated

    async def cancel_booking(self, booking_id: str) -> Booking | None:
        """Cancel a booking."""
        if not self._db:
            return None
        booking = await self.get_booking(booking_id)
        if not booking or booking.status in ("completed", "cancelled"):
            return None
        await self._db.execute(
            "UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,),
        )
        await self._record_timestamp(booking_id, "cancelled", "system")
        await self._db.commit()
        await self._refresh_snapshot_cache()
        updated = await self.get_booking(booking_id)
        self._emit(EventType.BOOKING_CANCELLED, {"booking": updated.to_dict() if updated else {}})
        return updated

    async def get_booking(self, booking_id: str) -> Booking | None:
        """Fetch a single booking."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_booking(row)

    async def list_bookings(
        self,
        resource_id: str | None = None,
        work_item_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Booking]:
        """List bookings with optional filters."""
        if not self._db:
            return []
        conditions: list[str] = []
        params: list[Any] = []
        if resource_id is not None:
            conditions.append("resource_id = ?")
            params.append(resource_id)
        if work_item_id is not None:
            conditions.append("work_item_id = ?")
            params.append(work_item_id)
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)
        cursor = await self._db.execute(
            f"SELECT * FROM bookings WHERE {where} ORDER BY start_time DESC LIMIT ?",
            params,
        )
        rows = await cursor.fetchall()
        return [self._row_to_booking(r) for r in rows]

    async def get_booking_journal(self, booking_id: str) -> list[BookingJournal]:
        """Get time/token segments for a completed booking."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM booking_journals WHERE booking_id = ? ORDER BY start_time ASC",
            (booking_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_journal(r) for r in rows]

    async def generate_journal(self, booking_id: str) -> list[BookingJournal]:
        """Generate journal entries from BookingTimestamp pairs."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM booking_timestamps WHERE booking_id = ? ORDER BY timestamp ASC",
            (booking_id,),
        )
        rows = await cursor.fetchall()
        timestamps = [self._row_to_timestamp(r) for r in rows]
        if len(timestamps) < 2:
            return []
        entries: list[BookingJournal] = []
        for i in range(len(timestamps) - 1):
            ts_start = timestamps[i]
            ts_end = timestamps[i + 1]
            # Determine segment type
            if ts_start.status == "active":
                jtype = "working"
            elif ts_start.status == "on_break":
                jtype = "break"
            else:
                jtype = "idle"
            duration = ts_end.timestamp - ts_start.timestamp
            entry = BookingJournal(
                booking_id=booking_id,
                journal_type=jtype,
                start_time=ts_start.timestamp,
                end_time=ts_end.timestamp,
                duration_seconds=duration,
                billable=(jtype == "working"),
            )
            await self._db.execute(
                """INSERT INTO booking_journals (
                    id, booking_id, journal_type, start_time, end_time,
                    duration_seconds, tokens_consumed, billable
                ) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    entry.id, entry.booking_id, entry.journal_type,
                    entry.start_time, entry.end_time, entry.duration_seconds,
                    entry.tokens_consumed, 1 if entry.billable else 0,
                ),
            )
            entries.append(entry)
        await self._db.commit()
        return entries

    # ======================================================================
    # Resource registry (in-memory, populated from ACM)
    # ======================================================================

    def register_resource(self, resource: BookableResource) -> None:
        """Register a bookable resource."""
        self._resources[resource.resource_id] = resource

    def unregister_resource(self, resource_id: str) -> None:
        """Remove a resource from the registry."""
        self._resources.pop(resource_id, None)

    def get_resource(self, resource_id: str) -> BookableResource | None:
        """Get a bookable resource by ID."""
        return self._resources.get(resource_id)

    def list_resources(
        self,
        department: str | None = None,
        resource_type: str | None = None,
        active_only: bool = True,
    ) -> list[BookableResource]:
        """List bookable resources with optional filters."""
        result = list(self._resources.values())
        if active_only:
            result = [r for r in result if r.active]
        if department:
            result = [r for r in result if r.department == department]
        if resource_type:
            result = [r for r in result if r.resource_type == resource_type]
        return result

    def get_resource_availability(self, resource_id: str) -> dict[str, Any] | None:
        """Calculate availability: capacity minus active bookings (simplified)."""
        resource = self.get_resource(resource_id)
        if not resource:
            return None
        # Count active bookings (sync — from snapshot cache)
        active_bookings = sum(
            1 for b in self._snapshot_cache.get("bookings", [])
            if b.get("resource_id") == resource_id
            and b.get("status") in ("scheduled", "active")
        )
        return {
            "resource_id": resource_id,
            "capacity": resource.capacity,
            "active_bookings": active_bookings,
            "available_capacity": max(0, resource.capacity - active_bookings),
            "calendar": self._calendars.get(resource_id, AgentCalendar()).to_dict(),
        }

    # -- Calendar registry (in-memory) --

    def register_calendar(self, calendar: AgentCalendar) -> None:
        """Register an agent calendar."""
        self._calendars[calendar.resource_id] = calendar

    def get_calendar(self, resource_id: str) -> AgentCalendar | None:
        """Get agent calendar."""
        return self._calendars.get(resource_id)

    # ======================================================================
    # Capability matching
    # ======================================================================

    def _check_eligibility(self, resource: BookableResource, work_item: WorkItem) -> bool:
        """Check if a resource is eligible for a work item."""
        # 1. Resource must be active
        if not resource.active:
            return False
        # 2. Available capacity
        avail = self.get_resource_availability(resource.resource_id)
        if avail and avail["available_capacity"] <= 0:
            return False
        # 3. Trust requirement
        if work_item.trust_requirement > 0:
            trust_char = next(
                (c for c in resource.characteristics if c.get("skill") == "trust"),
                None,
            )
            if not trust_char or trust_char.get("proficiency", 0) < work_item.trust_requirement:
                return False
        # 4. Required capabilities
        resource_skills = {c.get("skill", "") for c in resource.characteristics}
        for cap in work_item.required_capabilities:
            if cap not in resource_skills:
                return False
        return True

    # ======================================================================
    # Tick loop
    # ======================================================================

    async def _tick_loop(self) -> None:
        """Background loop for housekeeping tasks."""
        while self._running:
            try:
                await self._expire_ttl_items()
                await self._check_overdue_items()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("WorkItemStore tick error")
            try:
                await asyncio.sleep(self._tick_interval)
            except asyncio.CancelledError:
                break

    async def _expire_ttl_items(self) -> None:
        """Cancel work items past their TTL."""
        if not self._db:
            return
        now = time.time()
        cursor = await self._db.execute(
            """SELECT * FROM work_items
               WHERE ttl_seconds IS NOT NULL
               AND status NOT IN ('done', 'cancelled', 'failed')
               AND (created_at + ttl_seconds) < ?""",
            (now,),
        )
        rows = await cursor.fetchall()
        for row in rows:
            work_item_id = row["id"]
            await self.transition_work_item(work_item_id, "cancelled", source="ttl_expiry")
            logger.info("TTL expired work item %s", work_item_id)

    async def _check_overdue_items(self) -> None:
        """Log warnings for overdue work items."""
        if not self._db:
            return
        now = time.time()
        cursor = await self._db.execute(
            """SELECT id, title, due_at FROM work_items
               WHERE due_at IS NOT NULL
               AND due_at < ?
               AND status NOT IN ('done', 'cancelled', 'failed')""",
            (now,),
        )
        rows = await cursor.fetchall()
        for row in rows:
            logger.warning(
                "Overdue work item %s: '%s' (due %.0fs ago)",
                row["id"], row["title"], now - row["due_at"],
            )

    # ======================================================================
    # Snapshot (sync-safe for build_state_snapshot)
    # ======================================================================

    def snapshot(self) -> dict[str, Any]:
        """Return cached snapshot for build_state_snapshot."""
        result = dict(self._snapshot_cache)
        result["resources"] = [r.to_dict() for r in self._resources.values()]
        result["work_types"] = [wt.to_dict() for wt in self.work_type_registry.list_types()]
        result["templates"] = [t.to_dict() for t in self.template_store.list_templates()]
        return result

    async def _refresh_snapshot_cache(self) -> None:
        """Rebuild in-memory snapshot cache from DB."""
        if not self._db:
            self._snapshot_cache = {"work_items": [], "bookings": []}
            return
        cursor = await self._db.execute(
            "SELECT * FROM work_items WHERE status NOT IN ('done', 'cancelled', 'failed') ORDER BY priority ASC, created_at DESC LIMIT 100",
        )
        rows = await cursor.fetchall()
        work_items = [self._row_to_work_item(r).to_dict() for r in rows]
        cursor = await self._db.execute(
            "SELECT * FROM bookings WHERE status NOT IN ('completed', 'cancelled') ORDER BY start_time DESC LIMIT 100",
        )
        rows = await cursor.fetchall()
        bookings = [self._row_to_booking(r).to_dict() for r in rows]
        self._snapshot_cache = {"work_items": work_items, "bookings": bookings}

    # ======================================================================
    # Row converters
    # ======================================================================

    @staticmethod
    def _row_to_work_item(row: aiosqlite.Row) -> WorkItem:
        """Convert aiosqlite Row to WorkItem."""
        return WorkItem(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            work_type=row["work_type"],
            status=row["status"],
            priority=row["priority"],
            parent_id=row["parent_id"],
            depends_on=json.loads(row["depends_on"]) if row["depends_on"] else [],
            assigned_to=row["assigned_to"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            due_at=row["due_at"],
            estimated_tokens=row["estimated_tokens"],
            actual_tokens=row["actual_tokens"],
            trust_requirement=row["trust_requirement"],
            required_capabilities=json.loads(row["required_capabilities"]) if row["required_capabilities"] else [],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            steps=json.loads(row["steps"]) if row["steps"] else [],
            verification=json.loads(row["verification"]) if row["verification"] else {},
            schedule=json.loads(row["schedule"]) if row["schedule"] else {},
            ttl_seconds=row["ttl_seconds"],
            template_id=row["template_id"],
        )

    @staticmethod
    def _row_to_booking(row: aiosqlite.Row) -> Booking:
        """Convert aiosqlite Row to Booking."""
        return Booking(
            id=row["id"],
            resource_id=row["resource_id"],
            work_item_id=row["work_item_id"],
            requirement_id=row["requirement_id"],
            status=row["status"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            actual_start=row["actual_start"],
            actual_end=row["actual_end"],
            total_tokens_consumed=row["total_tokens_consumed"],
        )

    @staticmethod
    def _row_to_timestamp(row: aiosqlite.Row) -> BookingTimestamp:
        """Convert aiosqlite Row to BookingTimestamp."""
        return BookingTimestamp(
            id=row["id"],
            booking_id=row["booking_id"],
            status=row["status"],
            timestamp=row["timestamp"],
            source=row["source"],
        )

    @staticmethod
    def _row_to_journal(row: aiosqlite.Row) -> BookingJournal:
        """Convert aiosqlite Row to BookingJournal."""
        return BookingJournal(
            id=row["id"],
            booking_id=row["booking_id"],
            journal_type=row["journal_type"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            duration_seconds=row["duration_seconds"],
            tokens_consumed=row["tokens_consumed"],
            billable=bool(row["billable"]),
        )

    @staticmethod
    def _row_to_requirement(row: aiosqlite.Row) -> ResourceRequirement:
        """Convert aiosqlite Row to ResourceRequirement."""
        return ResourceRequirement(
            id=row["id"],
            work_item_id=row["work_item_id"],
            duration_estimate_seconds=row["duration_estimate_seconds"],
            from_date=row["from_date"],
            to_date=row["to_date"],
            required_characteristics=json.loads(row["required_characteristics"]) if row["required_characteristics"] else [],
            min_trust=row["min_trust"],
            department_constraint=row["department_constraint"],
            priority=row["priority"],
            resource_preference=json.loads(row["resource_preference"]) if row["resource_preference"] else {},
            fulfilled=bool(row["fulfilled"]),
        )

    # ======================================================================
    # Internal helpers
    # ======================================================================

    async def _record_timestamp(
        self, booking_id: str, status: str, source: str,
    ) -> None:
        """Append a BookingTimestamp."""
        if not self._db:
            return
        ts = BookingTimestamp(
            booking_id=booking_id,
            status=status,
            source=source,
        )
        await self._db.execute(
            """INSERT INTO booking_timestamps (id, booking_id, status, timestamp, source)
               VALUES (?,?,?,?,?)""",
            (ts.id, ts.booking_id, ts.status, ts.timestamp, ts.source),
        )
