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
import json
import logging
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
        # In-memory registries (populated from ACM at startup)
        self._resources: dict[str, BookableResource] = {}
        self._calendars: dict[str, AgentCalendar] = {}
        # Snapshot cache for sync-safe access
        self._snapshot_cache: dict[str, Any] = {"work_items": [], "bookings": []}
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
                    json.dumps(item.schedule), item.ttl_seconds, item.template_id,
                ),
            )
            # Auto-generate ResourceRequirement
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
                    req.id, req.work_item_id, req.duration_estimate_seconds,
                    req.from_date, req.to_date,
                    json.dumps(req.required_characteristics),
                    req.min_trust, req.department_constraint, req.priority,
                    json.dumps(req.resource_preference), 0,
                ),
            )
            await self._db.commit()
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

    async def update_work_item(self, work_item_id: str, **updates: Any) -> WorkItem | None:
        """Update work item fields. Sets updated_at. Emits 'work_item_updated'."""
        if not self._db:
            return None
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

    async def transition_work_item(
        self, work_item_id: str, new_status: str, source: str = "system",
    ) -> WorkItem | None:
        """Transition work item status with validation."""
        if not self._db:
            return None
        item = await self.get_work_item(work_item_id)
        if not item:
            return None
        # AD-498: Validate against work type state machine
        valid, reason = self.work_type_registry.validate_transition(
            item.work_type, item.status, new_status,
        )
        if not valid:
            logger.warning("Invalid transition for %s: %s", work_item_id, reason)
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
        item = await self.get_work_item(work_item_id)
        if not item:
            return False
        # Get booking IDs for cascade
        cursor = await self._db.execute(
            "SELECT id FROM bookings WHERE work_item_id = ?", (work_item_id,),
        )
        booking_rows = await cursor.fetchall()
        booking_ids = [r["id"] for r in booking_rows]
        # Cascade delete booking timestamps and journals
        for bid in booking_ids:
            await self._db.execute("DELETE FROM booking_timestamps WHERE booking_id = ?", (bid,))
            await self._db.execute("DELETE FROM booking_journals WHERE booking_id = ?", (bid,))
        # Delete bookings
        await self._db.execute("DELETE FROM bookings WHERE work_item_id = ?", (work_item_id,))
        # Delete requirements
        await self._db.execute("DELETE FROM resource_requirements WHERE work_item_id = ?", (work_item_id,))
        # Delete work item
        await self._db.execute("DELETE FROM work_items WHERE id = ?", (work_item_id,))
        await self._db.commit()
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
        item = await self.get_work_item(work_item_id)
        if not item:
            return None
        resource = self.get_resource(resource_id)
        if not resource:
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
        await self._refresh_snapshot_cache()
        self._emit(EventType.WORK_ITEM_ASSIGNED, {
            "work_item": (await self.get_work_item(work_item_id) or item).to_dict(),
            "booking": booking.to_dict(),
            "resource": resource.to_dict(),
        })
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
        booking = await self.get_booking(booking_id)
        if not booking or booking.status not in ("active", "scheduled"):
            return None
        now = time.time()
        await self._db.execute(
            "UPDATE bookings SET status = 'completed', actual_end = ?, total_tokens_consumed = ? WHERE id = ?",
            (now, tokens_consumed, booking_id),
        )
        await self._record_timestamp(booking_id, "completed", "system")
        await self._db.commit()
        # Generate journal entries
        journal = await self.generate_journal(booking_id)
        # Update work item actual_tokens
        if booking.work_item_id:
            await self._db.execute(
                "UPDATE work_items SET actual_tokens = actual_tokens + ?, updated_at = ? WHERE id = ?",
                (tokens_consumed, now, booking.work_item_id),
            )
            await self._db.commit()
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
