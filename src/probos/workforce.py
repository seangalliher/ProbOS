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
import hashlib
import inspect
import json
import logging
import math
import re
import sqlite3
import time
import uuid
import weakref
from collections import defaultdict
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Literal, Protocol

import aiosqlite

from probos import work_item_steps as owned_steps
from probos.crew_execution_usage import CREW_EXECUTION_TOKEN_USAGE_KEY
from probos.events import EventType
from probos.protocols import ConnectionFactory, DatabaseConnection, EventEmitterMixin
from probos.types import Priority

if TYPE_CHECKING:
    from probos.crew_session_delivery import (
        CrewSessionDeliveryOutboxEntry,
        CrewSessionDeliveryOutcome,
        CrewSessionDeliveryRecord,
    )

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
            WorkTypeTransition("blocked", "review"),
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
    # AD-1176: soft reference to Project.id. No foreign key and no existence
    # check at insert — matching ChatThread.project_id. A work item pointing at
    # a deleted project still loads; it simply stops matching the filter.
    project_id: str | None = None
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
            "project_id": self.project_id,
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
class ReadyWorkPage:
    items: tuple[WorkItem, ...]
    next_offset: int | None
    item_offsets: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class CrewSessionParentCreate:
    id: str
    title: str
    description: str
    assigned_to: str
    created_by: str
    metadata: dict[str, Any]
    created_at: float | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if any(
            type(value) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(value) is None
            for value in (self.id, self.assigned_to, self.created_by)
        ):
            raise ValueError("crew_session_parent_create_invalid")
        text_fields = (
            (self.title, 4_096, 16_384),
            (self.description, 32_768, 131_072),
        )
        for value, maximum, maximum_bytes in text_fields:
            if (
                type(value) is not str
                or not value.strip()
                or "\x00" in value
                or len(value) > maximum
            ):
                raise ValueError("crew_session_parent_create_invalid")
            try:
                if len(value.encode("utf-8")) > maximum_bytes:
                    raise ValueError("crew_session_parent_create_invalid")
            except UnicodeEncodeError as exc:
                raise ValueError("crew_session_parent_create_invalid") from exc
        if type(self.metadata) is not dict:
            raise ValueError("crew_session_parent_create_invalid")
        metadata_bytes = _compact_exact_json_bytes(
            self.metadata,
            error="crew_session_parent_create_invalid",
        )
        if len(metadata_bytes) > _MAX_WORK_ITEM_METADATA_BYTES:
            raise ValueError("crew_session_parent_create_invalid")
        try:
            steps_json = owned_steps.owned_json_bytes(self.steps).decode("utf-8")
            owned_steps.owned_row_spans(steps_json)
        except (UnicodeError, owned_steps.OwnedStepsError) as exc:
            raise ValueError("crew_session_parent_create_invalid") from exc
        if self.created_at is None:
            created_at = None
        elif (
            type(self.created_at) not in (int, float)
            or not math.isfinite(float(self.created_at))
            or not 0.0 <= float(self.created_at) <= _MAX_WORK_ITEM_TIMESTAMP
        ):
            raise ValueError("crew_session_parent_create_invalid")
        else:
            created_at = float(self.created_at)
        object.__setattr__(
            self,
            "metadata",
            json.loads(metadata_bytes.decode("utf-8")),
        )
        object.__setattr__(self, "created_at", created_at)


class CrewSessionParentReservation(Protocol):
    async def create_parent(
        self,
        request: CrewSessionParentCreate,
    ) -> WorkItem: ...


class CrewSessionAdmissionPort(Protocol):
    def reserve(
        self,
    ) -> AbstractAsyncContextManager[CrewSessionParentReservation]: ...


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
    template_id TEXT,
    -- AD-1176: appended last so a fresh CREATE TABLE and the ALTER TABLE
    -- migration below produce an identical column order.
    project_id TEXT,
    steps_control TEXT
);

CREATE TABLE IF NOT EXISTS owned_steps_journal (
    parent_id TEXT NOT NULL,
    incarnation TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('operation','effect','permit','submission','review','control')),
    record_id TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    payload TEXT NOT NULL CHECK(length(CAST(payload AS BLOB)) <= 2097152),
    step_id TEXT,
    accepted INTEGER,
    PRIMARY KEY (parent_id, incarnation, kind, record_id)
);

CREATE TABLE IF NOT EXISTS owned_steps_observations (
    observation_id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    raw_steps TEXT,
    raw_control TEXT,
    steps_digest TEXT NOT NULL,
    control_digest TEXT,
    source_manifest TEXT NOT NULL CHECK(length(CAST(source_manifest AS BLOB)) <= 2097152),
    source_digest TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_owned_steps_observations_dedup
    ON owned_steps_observations(
        parent_id, actor_id, thread_id, steps_digest, control_digest, source_digest
    );

CREATE TABLE IF NOT EXISTS owned_steps_proposals (
    parent_id TEXT NOT NULL,
    preparation_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL UNIQUE,
    actor_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('adopt_existing','replace_manual_prefix','replan_unstarted')),
    state TEXT NOT NULL CHECK(state IN ('preparing','ready','failed','committed')),
    claim_nonce TEXT NOT NULL,
    manifest TEXT CHECK(manifest IS NULL OR length(CAST(manifest AS BLOB)) <= 2097152),
    manifest_digest TEXT,
    error_code TEXT,
    apply_operation_id TEXT,
    acknowledgement TEXT CHECK(acknowledgement IS NULL OR length(CAST(acknowledgement AS BLOB)) <= 2097152),
    PRIMARY KEY (parent_id, preparation_id),
    FOREIGN KEY (observation_id) REFERENCES owned_steps_observations(observation_id)
);

CREATE TABLE IF NOT EXISTS owned_steps_retired_children (
    parent_id TEXT NOT NULL,
    child_id TEXT NOT NULL,
    old_incarnation TEXT,
    successor_incarnation TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    apply_operation_id TEXT NOT NULL,
    child_snapshot_digest TEXT NOT NULL,
    post_cancellation_source_digest TEXT NOT NULL,
    PRIMARY KEY (parent_id, child_id),
    FOREIGN KEY (proposal_id) REFERENCES owned_steps_proposals(proposal_id)
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

CREATE TABLE IF NOT EXISTS crew_trust_outbox (
    outcome_id       TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL,
    session_revision INTEGER NOT NULL,
    evidence_sha256  TEXT NOT NULL,
    payload_json     TEXT NOT NULL,
    delivered        INTEGER NOT NULL DEFAULT 0,
    created_at       REAL NOT NULL,
    delivered_at     REAL
);

CREATE TABLE IF NOT EXISTS crew_delivery_outbox (
    delivery_id      TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL,
    session_revision INTEGER NOT NULL,
    outcome          TEXT NOT NULL,
    occurred_at      REAL NOT NULL,
    payload_json     TEXT NOT NULL,
    delivered        INTEGER NOT NULL DEFAULT 0,
    created_at       REAL NOT NULL,
    delivered_at     REAL,
    UNIQUE (session_id, session_revision, outcome)
);

CREATE TABLE IF NOT EXISTS promoted_report_outbox (
    message_id   TEXT PRIMARY KEY,
    work_item_id TEXT NOT NULL,
    thread_id    TEXT NOT NULL,
    agent_id     TEXT NOT NULL,
    body         TEXT NOT NULL,
    created_at   REAL NOT NULL,
    delivered    INTEGER NOT NULL DEFAULT 0,
    queued_at    REAL NOT NULL,
    delivered_at REAL,
    tool_trace_ref TEXT
);

CREATE INDEX IF NOT EXISTS idx_work_items_status ON work_items(status);
CREATE INDEX IF NOT EXISTS idx_work_items_assigned_to ON work_items(assigned_to);
CREATE INDEX IF NOT EXISTS idx_work_items_work_type ON work_items(work_type);
CREATE INDEX IF NOT EXISTS idx_work_items_parent_id ON work_items(parent_id);
CREATE INDEX IF NOT EXISTS idx_bookings_resource_id ON bookings(resource_id);
CREATE INDEX IF NOT EXISTS idx_bookings_work_item_id ON bookings(work_item_id);
CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
CREATE INDEX IF NOT EXISTS idx_booking_timestamps_booking_id ON booking_timestamps(booking_id);
CREATE INDEX IF NOT EXISTS idx_crew_trust_outbox_pending
    ON crew_trust_outbox(delivered, created_at, outcome_id);
CREATE INDEX IF NOT EXISTS idx_crew_delivery_outbox_pending
    ON crew_delivery_outbox(delivered, created_at, delivery_id);
CREATE INDEX IF NOT EXISTS idx_promoted_report_outbox_pending
    ON promoted_report_outbox(delivered, queued_at, message_id);
CREATE INDEX IF NOT EXISTS idx_work_items_crew_session_metrics
    ON work_items(work_type, created_at DESC, id DESC);
"""

# Fields that are JSON-serialized in SQLite
_JSON_FIELDS = frozenset({
    "depends_on", "required_capabilities", "tags",
    "metadata", "steps", "verification", "schedule",
    "required_characteristics", "resource_preference",
})

_WORK_ITEM_PUBLIC_COLUMNS = ", ".join(item.name for item in dataclasses.fields(WorkItem))

_WORK_ITEM_JSON_FIELDS = tuple(
    item.name for item in dataclasses.fields(WorkItem) if item.name in _JSON_FIELDS
)


@lru_cache(maxsize=owned_steps.MAX_OWNED_ROWS * 4)
def _validated_work_item_json(raw: str) -> None:
    # The same decoder as _row_to_work_item, not the stricter owned format.
    # Retain only a successful parse, never its mutable containers or DB state.
    json.loads(raw)


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
_MAX_WORK_ITEM_TIMESTAMP = 253_402_300_799.0
_MAX_WORK_ITEM_DIRECT_CHILDREN = 1_000
_MAX_CREW_TRUST_EFFECTS = (_MAX_WORK_ITEM_DIRECT_CHILDREN * 10) + 2
_MAX_CREW_TRUST_EFFECT_BYTES = 8_192
_MAX_CREW_DELIVERY_RECORD_BYTES = 8_192
_MAX_CREW_DELIVERY_PENDING_ROWS = 1_001
# AD-1274: a promoted run's report is a Captain-facing narrative, not a compact
# outcome record, so it needs far more room than the 8 KiB crew delivery
# payload. 64 KiB is generous for prose and still refuses a runaway body rather
# than letting one row fill workforce.db.
_MAX_PROMOTED_REPORT_PENDING_ROWS = 1_001
_MAX_PROMOTED_REPORT_BODY_BYTES = 65_536
_MAX_CREW_SESSION_METRIC_ROWS = 10_001
_MAX_WORK_ITEM_CHILD_SNAPSHOT_DEPTH = 64
_MAX_WORK_ITEM_CHILD_SNAPSHOT_NODES = 65_536
_MAX_WORK_ITEM_CHILD_SNAPSHOT_CONTAINER_ENTRIES = 16_384
_MAX_WORK_ITEM_CHILD_SNAPSHOT_STRING_BYTES = 1_048_576
_MISSING_METADATA_VALUE = object()
# The crew child barrier compares ``WorkItem.to_dict()`` minus ``updated_at``
# (see ``crew_finalizer._publication_child_snapshot``), so this set MUST equal
# ``set(WorkItem().to_dict()) - {"updated_at"}``. Every field added to the
# dataclass has to be listed here and emitted by ``_work_item_child_snapshot``
# below, or publication raises ``work_item_child_barrier_invalid``. Neither
# barrier is persisted — both are recomputed from live rows inside the write
# transaction — so growing them does not invalidate anything on disk.
# AD-1176 added ``project_id``; ``test_ad1176_work_item_project.py`` guards the
# agreement.
# AD-1271: a row carrying this metadata flag is a UI BINDING, not a unit of
# work — a chat thread needs a ``task_id`` for its FILES rail to bind to, and
# BF-735's 36 ``Room workspace`` rows are what that left behind. Listers exclude
# it by default so the Captain is not told about work nobody can act on.
#
# Reserved on the WRITE side too, and that is the load-bearing half. Review
# measured an ordinary ``create_work_item`` / ``update_work_item`` setting the
# flag on a REAL work item and the row vanishing from every default consumer —
# an invisibility switch reachable from ``POST /api/work-items``. Only the
# one-off migration writes it, and it does so in raw SQL, below this layer.
SCAFFOLD_METADATA_FLAG = "ui_scaffold"

# ``IS NOT 1`` rather than ``!= 1``: ``json_extract`` yields NULL for a row
# whose metadata is absent or carries no such key, and ``NULL != 1`` is NULL,
# which SQLite treats as false — that spelling would drop every ordinary row.
# The ``json_valid`` guard keeps a hand-edited non-JSON column from raising
# instead of degrading. Written against ``item.metadata`` so an aliased query
# can use it verbatim.
_SCAFFOLD_EXCLUSION_SQL = (
    "(item.metadata IS NULL OR NOT json_valid(item.metadata) "
    f"OR json_extract(item.metadata, '$.{SCAFFOLD_METADATA_FLAG}') IS NOT 1)"
)


def _reject_reserved_metadata(metadata: Any) -> None:
    """Refuse an ordinary write that would set the scaffold flag.

    Raises rather than stripping, mirroring ``crew_session_write_reserved``
    beside it: a caller that silently had its value discarded would believe it
    had taken effect. This is a data-integrity boundary — the flag decides
    whether a row is visible to the Captain at all — so it propagates.
    """
    if type(metadata) is str:
        metadata = json.loads(metadata)
    if type(metadata) is dict:
        if SCAFFOLD_METADATA_FLAG in metadata:
            raise ValueError("ui_scaffold_write_reserved")
        if "steps_control" in metadata:
            raise owned_steps.OwnedStepsError("owned_steps_control_reserved")


_WORK_ITEM_CHILD_SNAPSHOT_KEYS = frozenset({
    "id",
    "title",
    "description",
    "work_type",
    "status",
    "priority",
    "parent_id",
    "project_id",
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
# The plan-adoption barrier compares whole ``to_dict()`` payloads, so this set
# must equal ``set(WorkItem().to_dict())``.
_WORK_ITEM_PLAN_ADOPTION_SNAPSHOT_KEYS = (
    _WORK_ITEM_CHILD_SNAPSHOT_KEYS | {"updated_at"}
)
_WORK_ITEM_PUBLICATION_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
)
_CREW_PROVISIONING_ERROR_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,127}$")


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


def _detach_crew_trust_effects(
    effects: tuple[Any, ...],
    *,
    session_id: str,
    session_revision: int,
) -> tuple[dict[str, Any], ...]:
    from probos.consensus.crew_trust_effect import CrewTrustEffect

    if (
        type(effects) is not tuple
        or len(effects) > _MAX_CREW_TRUST_EFFECTS
        or type(session_id) is not str
        or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(session_id) is None
        or type(session_revision) is not int
        or not 1 <= session_revision <= 2_147_483_647
    ):
        raise ValueError("crew_trust_outbox_invalid")
    validated_effects: list[Any] = []
    for effect in effects:
        if type(effect) is not CrewTrustEffect:
            raise ValueError("crew_trust_outbox_invalid")
        validated = CrewTrustEffect.from_payload(effect.to_payload())
        if (
            validated.session_id != session_id
            or validated.session_revision != session_revision
        ):
            raise ValueError("crew_trust_outbox_invalid")
        validated_effects.append(validated)
    validated_effects.sort(key=lambda item: item.outcome_id)
    if len({item.outcome_id for item in validated_effects}) != len(validated_effects):
        raise ValueError("crew_trust_outbox_invalid")
    detached: list[dict[str, Any]] = []
    for validated in validated_effects:
        payload = validated.to_payload()
        encoded = _compact_exact_json_bytes(
            payload,
            error="crew_trust_outbox_invalid",
        )
        if len(encoded) > _MAX_CREW_TRUST_EFFECT_BYTES:
            raise ValueError("crew_trust_outbox_invalid")
        detached.append(json.loads(encoded.decode("utf-8")))
    return tuple(detached)


async def _insert_crew_trust_effects(
    db: DatabaseConnection,
    effects: tuple[dict[str, Any], ...],
) -> None:
    for payload in effects:
        encoded = _compact_exact_json_bytes(
            payload,
            error="crew_trust_outbox_invalid",
        ).decode("utf-8")
        cursor = await db.execute(
            "SELECT session_id, session_revision, evidence_sha256, payload_json "
            "FROM crew_trust_outbox WHERE outcome_id = ?",
            (payload["outcome_id"],),
        )
        row = await cursor.fetchone()
        if row is not None:
            if (
                type(row[0]) is not str
                or row[0] != payload["session_id"]
                or type(row[1]) is not int
                or row[1] != payload["session_revision"]
                or type(row[2]) is not str
                or row[2] != payload["evidence_sha256"]
                or type(row[3]) is not str
                or row[3] != encoded
            ):
                raise ValueError("trust_outcome_identity_conflict")
            continue
        await db.execute(
            "INSERT INTO crew_trust_outbox "
            "(outcome_id, session_id, session_revision, evidence_sha256, "
            "payload_json, delivered, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (
                payload["outcome_id"],
                payload["session_id"],
                payload["session_revision"],
                payload["evidence_sha256"],
                encoded,
                time.time(),
            ),
        )


def _detach_crew_session_delivery(
    record: CrewSessionDeliveryRecord | None,
    *,
    session_id: str,
    contract_payload: Any,
) -> dict[str, Any] | None:
    from probos.crew_session_delivery import (
        CrewSessionDeliveryRecord,
        build_crew_session_delivery_record_from_payload,
    )

    if record is None:
        return None
    if (
        type(record) is not CrewSessionDeliveryRecord
        or type(session_id) is not str
        or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(session_id) is None
        or type(contract_payload) is not dict
    ):
        raise ValueError("crew_delivery_outbox_invalid")
    validated = CrewSessionDeliveryRecord.from_payload(record.to_payload())
    expected = build_crew_session_delivery_record_from_payload(contract_payload)
    if (
        validated.session_id != session_id
        or validated.canonical_bytes() != expected.canonical_bytes()
    ):
        raise ValueError("crew_delivery_identity_conflict")
    encoded = validated.canonical_bytes()
    if len(encoded) > _MAX_CREW_DELIVERY_RECORD_BYTES:
        raise ValueError("crew_delivery_outbox_invalid")
    return json.loads(encoded.decode("utf-8"))


async def _insert_crew_session_delivery(
    db: DatabaseConnection,
    payload: dict[str, Any] | None,
) -> None:
    if payload is None:
        return
    encoded = _compact_exact_json_bytes(
        payload,
        error="crew_delivery_outbox_invalid",
    )
    if len(encoded) > _MAX_CREW_DELIVERY_RECORD_BYTES:
        raise ValueError("crew_delivery_outbox_invalid")
    payload_json = encoded.decode("utf-8")
    cursor = await db.execute(
        "SELECT session_id, session_revision, outcome, occurred_at, payload_json "
        "FROM crew_delivery_outbox WHERE delivery_id = ?",
        (payload["delivery_id"],),
    )
    row = await cursor.fetchone()
    if row is not None:
        if (
            type(row[0]) is not str
            or row[0] != payload["session_id"]
            or type(row[1]) is not int
            or row[1] != payload["session_revision"]
            or type(row[2]) is not str
            or row[2] != payload["outcome"]
            or type(row[3]) is not float
            or row[3] != payload["occurred_at"]
            or type(row[4]) is not str
            or row[4] != payload_json
        ):
            raise ValueError("crew_delivery_identity_conflict")
        return
    cursor = await db.execute(
        "SELECT delivery_id FROM crew_delivery_outbox WHERE session_id = ? "
        "AND session_revision = ? AND outcome = ?",
        (
            payload["session_id"],
            payload["session_revision"],
            payload["outcome"],
        ),
    )
    if await cursor.fetchone() is not None:
        raise ValueError("crew_delivery_identity_conflict")
    await db.execute(
        "INSERT INTO crew_delivery_outbox "
        "(delivery_id, session_id, session_revision, outcome, occurred_at, "
        "payload_json, delivered, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
        (
            payload["delivery_id"],
            payload["session_id"],
            payload["session_revision"],
            payload["outcome"],
            payload["occurred_at"],
            payload_json,
            time.time(),
        ),
    )


def _crew_delivery_entry_from_row(row: Any) -> CrewSessionDeliveryOutboxEntry:
    from probos.crew_session_delivery import (
        CrewSessionDeliveryOutboxEntry,
        CrewSessionDeliveryRecord,
    )

    try:
        payload = json.loads(row[5])
        record = CrewSessionDeliveryRecord.from_payload(payload)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("crew_delivery_outbox_corrupt") from exc
    if (
        type(row[0]) is not str
        or row[0] != record.delivery_id
        or type(row[1]) is not str
        or row[1] != record.session_id
        or type(row[2]) is not int
        or row[2] != record.session_revision
        or type(row[3]) is not str
        or row[3] != record.outcome
        or type(row[4]) is not float
        or row[4] != record.occurred_at
        or type(row[5]) is not str
        or row[5] != record.canonical_bytes().decode("utf-8")
        or type(row[6]) is not int
        or row[6] not in (0, 1)
        or type(row[7]) is not float
        or (row[8] is not None and type(row[8]) is not float)
    ):
        raise ValueError("crew_delivery_outbox_corrupt")
    return CrewSessionDeliveryOutboxEntry(
        record=record,
        delivered=bool(row[6]),
        created_at=row[7],
        delivered_at=row[8],
    )


@dataclass(frozen=True)
class PromotedReportOutboxEntry:
    """AD-1274: one durably pending promoted-run report.

    ``message_id`` is the id the reporter minted for
    ``ChatThreadStore.append_message_once``, and ``created_at`` is the timestamp
    it minted alongside. Both are replayed VERBATIM on redelivery: the store's
    exact-match check compares every field, so a drifted timestamp would raise
    ``chat_thread_message_conflict`` rather than recognising the message it
    already holds.
    """

    message_id: str
    work_item_id: str
    thread_id: str
    agent_id: str
    body: str
    created_at: float
    delivered: bool
    queued_at: float
    delivered_at: float | None
    tool_trace_ref: str | None = None


def _promoted_report_entry_from_row(row: Any) -> PromotedReportOutboxEntry:
    if (
        len(row) != 10
        or type(row[0]) is not str
        or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(row[0]) is None
        or type(row[1]) is not str
        or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(row[1]) is None
        or type(row[2]) is not str
        or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(row[2]) is None
        or type(row[3]) is not str
        or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(row[3]) is None
        or type(row[4]) is not str
        or len(row[4].encode("utf-8")) > _MAX_PROMOTED_REPORT_BODY_BYTES
        or type(row[5]) is not float
        or not math.isfinite(row[5])
        or not 0.0 <= row[5] <= _MAX_WORK_ITEM_TIMESTAMP
        or type(row[6]) is not int
        or row[6] not in (0, 1)
        or type(row[7]) is not float
        or (row[8] is not None and type(row[8]) is not float)
        or (
            row[9] is not None
            and (
                type(row[9]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", row[9]) is None
            )
        )
    ):
        raise ValueError("promoted_report_outbox_corrupt")
    return PromotedReportOutboxEntry(
        message_id=row[0],
        work_item_id=row[1],
        thread_id=row[2],
        agent_id=row[3],
        body=row[4],
        created_at=row[5],
        delivered=bool(row[6]),
        queued_at=row[7],
        delivered_at=row[8],
        tool_trace_ref=row[9],
    )


def _build_crew_session_parent(
    request: CrewSessionParentCreate,
) -> WorkItem:
    if type(request) is not CrewSessionParentCreate:
        raise ValueError("crew_session_parent_create_invalid")
    metadata_bytes = _compact_exact_json_bytes(
        request.metadata,
        error="crew_session_parent_create_invalid",
    )
    if len(metadata_bytes) > _MAX_WORK_ITEM_METADATA_BYTES:
        raise ValueError("crew_session_parent_create_invalid")
    detached_metadata = json.loads(metadata_bytes.decode("utf-8"))
    steps_bytes = owned_steps.owned_json_bytes(request.steps)
    owned_steps.owned_row_spans(steps_bytes.decode("utf-8"))
    detached_steps = json.loads(steps_bytes)
    if request.created_at is None:
        created_at = time.time()
    else:
        created_at = request.created_at
    return WorkItem(
        id=request.id,
        title=request.title,
        description=request.description,
        work_type="crew_session",
        status="draft",
        priority=3,
        parent_id=None,
        depends_on=[],
        assigned_to=request.assigned_to,
        created_by=request.created_by,
        created_at=created_at,
        updated_at=created_at,
        due_at=None,
        estimated_tokens=None,
        actual_tokens=0,
        trust_requirement=0.0,
        required_capabilities=[],
        tags=[],
        metadata=detached_metadata,
        steps=detached_steps,
        verification={},
        schedule={},
        ttl_seconds=None,
        template_id=None,
    )


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
    *,
    retry_evidence: bool = False,
) -> tuple[dict[str, Any], ...]:
    error = "work_item_child_barrier_invalid"
    if (
        type(work_item_id) is not str
        or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(work_item_id) is None
        or type(value) is not tuple
        or not (0 if retry_evidence else 1) <= len(value) <= _MAX_WORK_ITEM_DIRECT_CHILDREN
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
            or not (
                retry_evidence and assigned_to is None
                or type(assigned_to) is str
                and _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(assigned_to) is not None
            )
            or (not retry_evidence and raw["status"] != "done")
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
            or (
                raw["project_id"] is not None
                and type(raw["project_id"]) is not str
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


class WorkItemRetryConflict(ValueError):
    """An atomic native retry proof no longer matches durable rows."""

    def __init__(self) -> None:
        super().__init__("work_item_retry_barrier_conflict")


@dataclasses.dataclass(frozen=True, init=False)
class WorkItemRetryBarrier:
    """Detached bounded observations for native retry or failure disposition."""

    parent_id: str
    parent_work_type: str
    parent_status: str
    parent_assigned_to: str | None
    parent_metadata: bytes
    children: tuple[bytes, ...]
    mode: Literal["untouched", "observed"]

    def __init__(
        self,
        parent: WorkItem,
        children: tuple[WorkItem, ...],
        *,
        mode: Literal["untouched", "observed"] = "untouched",
    ) -> None:
        error = "work_item_retry_barrier_invalid"
        if (
            type(parent) is not WorkItem
            or type(children) is not tuple
            or not (0 if mode == "observed" else 1) <= len(children) <= _MAX_WORK_ITEM_DIRECT_CHILDREN
            or any(type(child) is not WorkItem for child in children)
            or type(mode) is not str
            or mode not in {"untouched", "observed"}
            or type(parent.work_type) is not str
            or parent.work_type != "crew_session"
            or type(parent.status) is not str
            or parent.status not in {"open", "blocked", "in_progress"}
            or type(parent.assigned_to) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(parent.assigned_to) is None
            or type(parent.metadata) is not dict
        ):
            raise ValueError(error)
        metadata = _bounded_child_snapshot_bytes(
            parent.metadata, error=error, seen_containers=set(),
        )
        snapshots = _detach_direct_child_snapshots(
            parent.id,
            tuple(_work_item_child_snapshot(child) for child in children),
            retry_evidence=True,
        )
        object.__setattr__(self, "parent_id", parent.id)
        object.__setattr__(self, "parent_work_type", parent.work_type)
        object.__setattr__(self, "parent_status", parent.status)
        object.__setattr__(self, "parent_assigned_to", parent.assigned_to)
        object.__setattr__(self, "parent_metadata", metadata)
        object.__setattr__(self, "children", tuple(
            _bounded_child_snapshot_bytes(snapshot, error=error, seen_containers=set())
            for snapshot in snapshots
        ))
        object.__setattr__(self, "mode", mode)


def _work_item_child_snapshot(item: WorkItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "work_type": item.work_type,
        "status": item.status,
        "priority": item.priority,
        "parent_id": item.parent_id,
        "project_id": item.project_id,
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


class _CrewSessionParentReservation:
    def __init__(
        self,
        store: WorkItemStore,
        context: _CrewSessionAdmissionContext,
        generation: object,
        owner: asyncio.Task[Any],
    ) -> None:
        self._store = store
        self._context = context
        self._generation = generation
        self._owner = owner
        self._created = False

    async def create_parent(
        self,
        request: CrewSessionParentCreate,
    ) -> WorkItem:
        if (
            self._created
            or asyncio.current_task() is not self._owner
            or not self._context.owns(
                store=self._store,
                generation=self._generation,
                reservation=self,
            )
        ):
            raise RuntimeError("crew_session_admission_reservation_invalid")
        item = _build_crew_session_parent(request)
        self._created = True
        return await self._store._insert_work_item(item)

    def invalidate(self) -> None:
        self._generation = object()


class _CrewSessionAdmissionContext(
    AbstractAsyncContextManager[CrewSessionParentReservation]
):
    def __init__(
        self,
        store: WorkItemStore,
        lock: asyncio.Lock,
    ) -> None:
        self._store = store
        self._lock = lock
        self._entered = False
        self._acquired = False
        self._generation: object | None = None
        self._reservation: _CrewSessionParentReservation | None = None

    async def __aenter__(self) -> CrewSessionParentReservation:
        if self._entered:
            raise RuntimeError("crew_session_admission_reservation_invalid")
        self._entered = True
        await self._lock.acquire()
        self._acquired = True
        owner = asyncio.current_task()
        if owner is None:
            self._lock.release()
            self._acquired = False
            raise RuntimeError("crew_session_admission_reservation_invalid")
        self._generation = object()
        self._reservation = _CrewSessionParentReservation(
            self._store,
            self,
            self._generation,
            owner,
        )
        return self._reservation

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        self._generation = None
        if self._reservation is not None:
            self._reservation.invalidate()
        if self._acquired:
            self._lock.release()
            self._acquired = False

    def owns(
        self,
        *,
        store: WorkItemStore,
        generation: object,
        reservation: _CrewSessionParentReservation,
    ) -> bool:
        return (
            self._acquired
            and self._store is store
            and self._generation is generation
            and self._reservation is reservation
        )


class _CrewSessionAdmissionPort:
    def __init__(self, store: WorkItemStore, lock: asyncio.Lock) -> None:
        self._store = store
        self._lock = lock

    def reserve(
        self,
    ) -> AbstractAsyncContextManager[CrewSessionParentReservation]:
        return _CrewSessionAdmissionContext(self._store, self._lock)


# ---------------------------------------------------------------------------
# WorkItemStore — SQLite-backed persistence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _OwnedStepsWriteBinding:
    parent_id: str
    child_ids: frozenset[str]
    operation: str
    execution_scope: _OwnedExecutionScope | owned_steps.OwnedOwnerInvocation | None = None


@dataclass(frozen=True, eq=False)
class _OwnedExecutionScope:
    port: object
    plan: owned_steps.OwnedStepsSeedPlan
    rows: tuple[owned_steps.OwnedStepRecord, ...] = ()


@dataclass(frozen=True)
class _OwnedStoreWrite:
    binding: owned_steps.OwnedStoreBinding
    snapshot: owned_steps.OwnedStepsSnapshot
    grant: owned_steps.OwnedStepsGrant


@dataclass(frozen=True)
class _OwnedStepPostCommit:
    parent: WorkItem
    updated_parent: WorkItem
    children: dict[str, WorkItem]
    updated_children: tuple[WorkItem, ...]
    command_kind: str
    booking_events: tuple[tuple[EventType, dict[str, Any]], ...]
    continuation_parent_id: str | None


class _OwnedStepsExecutionPort:
    def __init__(
        self, store: object, admit: Callable[..., Any], start: Callable[..., Any],
        submit: Callable[..., Any], validate: Callable[..., Any], unstarted: Callable[..., Any],
    ) -> None:
        self._store = store
        self._admit = admit
        self._start = start
        self._submit = submit
        self._validate = validate
        self._unstarted = unstarted

    def owns_store(self, store: object) -> bool:
        return self._store is store

    async def admit(
        self, parent_id: str, *, children: tuple[WorkItem, ...], thread_id: str,
    ) -> owned_steps.OwnedExecutionLease:
        return await self._admit(self, parent_id, children=children, thread_id=thread_id)

    async def start(
        self, lease: owned_steps.OwnedExecutionLease, child_id: str, *, execution_nonce: str,
    ) -> owned_steps.OwnedStepMutationResult:
        return await self._start(self, lease, child_id, execution_nonce=execution_nonce)

    async def submit(
        self, lease: owned_steps.OwnedExecutionLease, submission: owned_steps.OwnedExecutionSubmission,
    ) -> owned_steps.OwnedStepMutationResult:
        return await self._submit(self, lease, submission)

    async def validate(
        self, lease: owned_steps.OwnedExecutionLease, permit: owned_steps.OwnedStepExecutionPermit,
    ) -> None:
        await self._validate(self, lease, permit)

    async def record_unstarted(
        self, lease: owned_steps.OwnedExecutionLease, submission: owned_steps.OwnedUnstartedSubmission,
    ) -> owned_steps.OwnedStepMutationResult:
        return await self._unstarted(self, lease, submission)


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
        pull_resource_resolver: Callable[
            [str, Literal["discover", "claim", "assign", "resume"], bool],
            BookableResource | None,
        ] | None = None,
        owned_steps_authorizer: owned_steps.OwnedStepsAuthorizer | None = None,
        owned_steps_ttl_owner: owned_steps.OwnedStepsTTLOwner | None = None,
        owned_steps_content: owned_steps.OwnedStepsContentReader | None = None,
    ) -> None:
        self.db_path = db_path
        self._db: DatabaseConnection | None = None
        self._emit_event = emit_event
        self._tick_interval = tick_interval
        self._connection_factory = connection_factory
        self._pull_resource_resolver = pull_resource_resolver
        self._owned_steps_authorizer = owned_steps_authorizer
        self._owned_steps_ttl_owner = owned_steps_ttl_owner
        self._owned_steps_content = owned_steps_content
        self._owned_steps_write_binding: _OwnedStepsWriteBinding | None = None
        self._owned_execution_port: _OwnedStepsExecutionPort | None = None
        self._owned_execution_scopes: weakref.WeakSet[_OwnedExecutionScope] = weakref.WeakSet()
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
        self._crew_session_admission_lock = asyncio.Lock()
        self._crew_session_admission_port_claimed = False
        self._crew_session_admission_port = _CrewSessionAdmissionPort(
            self,
            self._crew_session_admission_lock,
        )
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

    def claim_crew_session_admission_port(self) -> CrewSessionAdmissionPort:
        if self._crew_session_admission_port_claimed:
            raise RuntimeError("crew_session_admission_port_claimed")
        self._crew_session_admission_port_claimed = True
        return self._crew_session_admission_port

    def get_owned_steps_execution_port(self) -> owned_steps.OwnedStepsExecutionPort:
        if self._owned_execution_port is None:
            self._owned_execution_port = _OwnedStepsExecutionPort(
                self, self._admit_legacy_execution, self._start_legacy_execution,
                self._submit_legacy_execution, self._validate_legacy_execution, self._submit_unstarted_legacy_execution,
            )
        return self._owned_execution_port

    def bind_owned_steps_owner(
        self, authorizer: owned_steps.OwnedStepsAuthorizer,
        ttl_owner: owned_steps.OwnedStepsTTLOwner,
        content: owned_steps.OwnedStepsContentReader | None = None,
    ) -> None:
        """Bind the existing owner after construction, never per-request authority."""
        if self._owned_steps_authorizer is not None or self._owned_steps_ttl_owner is not None:
            raise owned_steps.OwnedStepsError("owned_steps_owner_already_bound")
        if authorizer is None or ttl_owner is None:
            raise owned_steps.OwnedStepsError("owned_steps_owner_invalid")
        if content is not None:
            self.bind_owned_steps_content(content)
        self._owned_steps_authorizer = authorizer
        self._owned_steps_ttl_owner = ttl_owner

    def bind_owned_steps_content(self, content: owned_steps.OwnedStepsContentReader) -> None:
        if content is None:
            raise owned_steps.OwnedStepsError("owned_steps_content_unavailable")
        if self._owned_steps_content is not None and self._owned_steps_content is not content:
            raise owned_steps.OwnedStepsError("owned_steps_content_already_bound")
        self._owned_steps_content = content

    def owned_steps_owner_matches(self, owner: owned_steps.OwnedStepsAuthorizer) -> bool:
        return self._owned_steps_authorizer is owner

    def has_owned_steps_owner(self) -> bool:
        return (
            self._owned_steps_authorizer is not None
            and self._owned_steps_ttl_owner is not None
        )

    async def read_steps_projection(self, parent_id: str) -> tuple[str, str]:
        if self._db is None:
            raise owned_steps.OwnedStepsError("owned_steps_unavailable", parent_id=parent_id)
        cursor = await self._db.execute("SELECT steps FROM work_items WHERE id=?", (parent_id,))
        row = await cursor.fetchone()
        if row is None:
            raise owned_steps.OwnedStepsError("owned_steps_parent_missing", parent_id=parent_id)
        return row["steps"], owned_steps.owned_digest(row["steps"])

    async def _prepare_owned_store_write(
        self, work_item_id: str, binding: owned_steps.OwnedStoreBinding | None,
        operation: str, payload: dict[str, Any],
    ) -> _OwnedStoreWrite | None:
        parent_id = await self._owned_parent_id(work_item_id)
        if parent_id is None:
            if binding is not None:
                raise owned_steps.OwnedStepsError("owned_steps_not_managed")
            return None
        if type(binding) is not owned_steps.OwnedStoreBinding or binding.operation != operation:
            raise owned_steps.OwnedStepsError("owned_steps_write_reserved", parent_id=parent_id)
        if operation == "verification":
            if binding.step_id is None or (
                (binding.reviewed_result is None) == (binding.unassessed_checkpoint is None)
            ):
                raise owned_steps.OwnedStepsError("owned_steps_review_conflict", parent_id=parent_id)
        elif binding.unassessed_checkpoint is not None:
            raise owned_steps.OwnedStepsError("owned_steps_review_conflict", parent_id=parent_id)
        actual_digest = owned_steps.owned_digest(owned_steps.owned_json_bytes(payload))
        if binding.request_digest != actual_digest:
            raise owned_steps.OwnedStepsError("owned_steps_owner_binding_conflict", parent_id=parent_id)
        authorize = getattr(self._owned_steps_authorizer, "authorize_owned_store_write", None)
        if not callable(authorize):
            raise owned_steps.OwnedStepsError("owned_steps_authority_required", parent_id=parent_id)
        grant = await authorize(binding)
        current, _, _ = await self._load_owned_steps(parent_id, step_id=binding.step_id)
        previous, live = binding.snapshot.control, current.control
        if (
            type(grant) is not owned_steps.OwnedStepsGrant or grant.parent_id != parent_id
            or grant.thread_id != live.thread_id or grant.role not in ("owner", "facilitator", "verifier")
            or previous.parent_id != parent_id or previous.incarnation != live.incarnation
            or previous.plan_digest != live.plan_digest or previous.plan_revision != live.plan_revision
            or previous.layout_revision != live.layout_revision
        ):
            raise owned_steps.OwnedStepsError("owned_steps_owner_binding_conflict", parent_id=parent_id)
        if binding.step_id is None:
            if work_item_id != parent_id or binding.snapshot.source_digest != current.source_digest or previous.steps_digest != live.steps_digest:
                raise owned_steps.OwnedStepsError("owned_steps_plan_conflict", parent_id=parent_id)
            if operation == "steps_finalize":
                receipt = binding.finalize_receipt
                if (
                    receipt is None
                    or receipt.parent_id != live.parent_id
                    or receipt.owner_kind != "canonical"
                    or receipt.thread_id != live.thread_id
                    or receipt.incarnation != live.incarnation
                    or receipt.plan_digest != live.plan_digest
                    or receipt.source_review_digest
                    != owned_steps.owned_source_review_digest(live)
                    or grant.role != "owner"
                ):
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_finalization_conflict",
                        parent_id=parent_id,
                    )
                for reference in (receipt.output, receipt.manifest):
                    await self.read_owned_steps_content(reference)
                for row in live.rows:
                    if row.child is None:
                        continue
                    if (
                        row.permit_state != "terminal"
                        or row.submission is None
                        or row.reviewed_result is None
                    ):
                        raise owned_steps.OwnedStepsError(
                            "owned_steps_finalization_state",
                            parent_id=parent_id,
                        )
                    await self._read_owned_evidence(
                        parent_id,
                        live.incarnation,
                        "review",
                        row.reviewed_result,
                    )
        else:
            old = next((row for row in previous.rows if row.step_id == binding.step_id), None)
            row = next((row for row in live.rows if row.step_id == binding.step_id), None)
            if old is None or row is None or old != row or row.child is None or row.child.child_id != work_item_id:
                raise owned_steps.OwnedStepsError("owned_steps_row_conflict", parent_id=parent_id)
            if operation == "verification" and binding.unassessed_checkpoint is not None:
                await self._validate_unassessed_store_write(binding, current, row, grant, payload)
            elif operation == "verification" and (
                row.permit_state != "submitted" or row.reviewed_result is not None
                or binding.reviewed_result is None or row.submission != binding.reviewed_result.submission_digest
                or grant.actor_id != binding.reviewed_result.reviewer_id or grant.actor_id == row.assignee_id
            ):
                raise owned_steps.OwnedStepsError("owned_steps_review_conflict", parent_id=parent_id)
        return _OwnedStoreWrite(binding, current, grant)

    async def _validate_unassessed_store_write(
        self, binding: owned_steps.OwnedStoreBinding, snapshot: owned_steps.OwnedStepsSnapshot,
        row: owned_steps.OwnedStepRecord, grant: owned_steps.OwnedStepsGrant, payload: dict[str, Any],
    ) -> None:
        control = snapshot.control
        checkpoint = owned_steps.UnassessedStepCheckpoint.model_validate_json(
            binding.unassessed_checkpoint.model_dump_json()
        )
        if (
            control.owner_kind != "canonical" or grant.role != "owner"
            or grant.actor_id != control.facilitator_id
            or row.permit_state != "submitted" or row.reviewed_result is not None
            or row.review_accepted is not None or row.permit is None
            or row.submission != checkpoint.submission_digest
        ):
            raise owned_steps.OwnedStepsError("owned_steps_review_conflict", parent_id=control.parent_id)
        permit = await self._read_owned_evidence(control.parent_id, control.incarnation, "permit", row.permit)
        submission = await self._read_owned_evidence(control.parent_id, control.incarnation, "submission", row.submission)
        if (
            not isinstance(permit, owned_steps.OwnedStepExecutionPermit)
            or not isinstance(submission, (owned_steps.OwnedStepSubmission, owned_steps.OwnedExecutionSubmission))
            or checkpoint.permit != permit or submission.permit != permit
            or permit.parent_id != control.parent_id or permit.incarnation != control.incarnation
            or permit.plan_digest != control.plan_digest or permit.plan_revision != control.plan_revision
            or permit.step_id != row.step_id or permit.child_id != row.child.child_id
            or permit.assignee_id != row.assignee_id or permit.assignment_epoch != row.assignment_epoch
            or permit.booking_id != row.booking_id or submission.output is None
        ):
            raise owned_steps.OwnedStepsError("owned_steps_review_conflict", parent_id=control.parent_id)
        verification = owned_steps.owned_json_loads(
            (await self.read_owned_steps_content(checkpoint.verification)).decode("utf-8")
        )
        convergence = owned_steps.owned_json_loads(
            (await self.read_owned_steps_content(checkpoint.convergence)).decode("utf-8")
        )
        output = await self.read_owned_steps_content(submission.output)
        child = await self.get_work_item(row.child.child_id)
        execution = owned_steps.owned_json_loads(submission.execution_json)
        if (
            child is None or child.verification != {}
            or "crew_verification_recovery" in child.metadata
            or not _json_values_exactly_equal(verification, payload["verification"])
            or not _json_values_exactly_equal(execution, child.metadata.get("crew_execution"))
            or not _json_values_exactly_equal(
                submission.output.model_dump(mode="json"), child.metadata.get("crew_execution_output"),
            )
            or convergence["parent_id"] != control.parent_id or convergence["thread_id"] != control.thread_id
            or convergence["work_item_id"] != child.id or convergence["producer_agent_id"] != child.assigned_to
            or convergence["execution_output_ref"] != submission.output.content_hash
        ):
            raise owned_steps.OwnedStepsError("owned_steps_review_conflict", parent_id=control.parent_id)
        result = convergence["outcome"]["result"]
        history = convergence["outcome"]["history"]
        first = history[0]
        if (
            first["result_text"].encode("utf-8") != output
            or first["result_sha256"] != submission.output.content_hash
            or first["tool_trace_ref"] != execution["tool_trace_ref"]
            or not _json_values_exactly_equal(first["artifact_refs"], execution["artifact_refs"])
            or result["work_item_id"] != child.id or result["spec_id"] != row.child.spec_id
            or result["agent_id"] != child.assigned_to
            or result["status"] != execution["status"] or result["stopped_reason"] != execution["stopped_reason"]
            or result["started_at"] != execution["started_at"] or result["finished_at"] != execution["finished_at"]
            or not _json_values_exactly_equal(result["blocked_dependency_ids"], execution["blocked_dependency_ids"])
            or result["actual_tokens"] != (
                execution["tokens_used"] if len(history) == 1 else history[-1]["correction_tokens"]
            )
        ):
            raise owned_steps.OwnedStepsError("owned_steps_review_conflict", parent_id=control.parent_id)

    async def _finish_owned_store_write(self, context: _OwnedStoreWrite | None) -> None:
        if context is None:
            return
        assert self._db is not None
        control = context.snapshot.control
        binding = context.binding
        parent = await self.get_work_item(control.parent_id)
        assert parent is not None
        rows = list(control.rows)
        projection = control.authorized_steps_json
        if binding.operation == "steps_finalize":
            receipt = binding.finalize_receipt
            assert receipt is not None
            manual_pending = bool(
                parent.metadata.get("steps_gate_completion")
            ) and any(
                row.kind == "manual"
                and owned_steps.owned_json_loads(row.todo_json)["status"]
                != "done"
                for row in rows
            )
            completed = parent.status == "done"
            if not completed and not manual_pending:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_finalization_state",
                    parent_id=parent.id,
                )
            disposition = "completed" if completed else "pending"
            mode = "completed" if completed else "waiting_manual_gate"
            if (
                control.finalization == receipt
                and control.finalization_disposition == disposition
                and control.mode == mode
            ):
                return
            candidate = control.with_finalization(
                receipt=receipt,
                disposition=disposition,
                mode=mode,
                parent_source_digest=await self._owned_parent_digest(parent),
            )
            await self._db.execute(
                "UPDATE work_items SET steps_control=? WHERE id=?",
                (candidate.model_dump_json(), parent.id),
            )
            return
        if binding.step_id is not None:
            index = next(i for i, row in enumerate(rows) if row.step_id == binding.step_id)
            row = rows[index]
            child = await self.get_work_item(row.child.child_id)
            assert child is not None
            updates: dict[str, Any] = {"source_digest": await self._owned_child_source(
                child, protected_metadata_keys=tuple(child.metadata) if control.owner_kind == "canonical" else row.plan_metadata_keys,
            )}
            if binding.operation == "verification" and binding.reviewed_result is not None:
                review = binding.reviewed_result
                for reference in (review.reviewed_result, review.verification):
                    await self.read_owned_steps_content(reference)
                updates.update(
                    reviewed_result=await self._write_owned_evidence(review),
                    review_accepted=review.accepted, permit_state="terminal",
                )
                todo = owned_steps.owned_json_loads(row.todo_json)
                todo.update(status="done" if review.accepted else "rejected", confirmed_by=review.reviewer_id)
                todo_json = owned_steps.owned_json_bytes(todo).decode("utf-8")
                updates.update(todo_json=todo_json, digest=owned_steps.owned_digest(todo_json))
            rows[index] = row.model_copy(update={**updates, "revision": row.revision + 1})
            projection = owned_steps.replace_owned_row(projection, index, rows[index].todo_json)
        candidate = control.with_projection(
            rows=tuple(rows), projection=projection, mode=control.mode, layout_revision=control.layout_revision,
        )
        candidate = candidate.model_copy(update={"parent_source_digest": await self._owned_parent_digest(parent)})
        candidate = owned_steps.parse_owned_control(candidate.model_dump_json())
        await self._db.execute(
            "UPDATE work_items SET steps=?,steps_control=? WHERE id=?",
            (projection, candidate.model_dump_json(), parent.id),
        )

    async def read_owned_steps_content(self, reference: owned_steps.OwnedContentReference) -> bytes:
        reference = owned_steps.OwnedContentReference.model_validate(reference)
        if self._owned_steps_content is None:
            raise owned_steps.OwnedStepsError("owned_steps_content_unavailable")
        content = await self._owned_steps_content.read(reference.content_hash)
        if (
            type(content) is not bytes or len(content) != reference.size_bytes
            or owned_steps.owned_digest(content) != reference.content_hash
        ):
            raise owned_steps.OwnedStepsError("owned_steps_content_conflict")
        return content

    async def start(self) -> None:
        """Open DB, create schema, start tick loop."""
        if self._running:
            return
        try:
            if self.db_path:
                self._db = await self._connection_factory.connect(self.db_path)
                await self._db.execute("PRAGMA foreign_keys = ON")
                self._db.row_factory = aiosqlite.Row
                await self._db.executescript(_SCHEMA)
                await self._db.commit()

                # AD-1176: Migrate project_id column onto pre-AD-1176 databases.
                # A fresh DB already has it from _SCHEMA; an existing one gets it
                # here. Both end up with project_id as the trailing column.
                try:
                    await self._db.execute(
                        "ALTER TABLE work_items ADD COLUMN project_id TEXT",
                    )
                    await self._db.commit()
                except sqlite3.OperationalError:
                    pass  # Column already exists — migration idempotency
                async with self._booking_transaction():
                    cursor = await self._db.execute("PRAGMA table_info(work_items)")
                    columns = {row["name"]: row for row in await cursor.fetchall()}
                    if "steps_control" not in columns:
                        await self._db.execute(
                            "ALTER TABLE work_items ADD COLUMN steps_control TEXT",
                        )
                    elif columns["steps_control"]["type"].upper() != "TEXT":
                        raise owned_steps.OwnedStepsError("owned_steps_schema_invalid")
                await self._migrate_promoted_report_trace()
                await self._migrate_owned_steps_history()
            await self._refresh_snapshot_cache()
            self._running = True
            self._tick_task = asyncio.create_task(self._tick_loop())
        except BaseException:
            await self.stop()
            raise
        logger.info("WorkItemStore started (tick=%.1fs)", self._tick_interval)

    async def _migrate_promoted_report_trace(self) -> None:
        """Append the nullable carrier without changing legacy row positions.

        Rollback retains this column. Before using an older drainer, producers
        must be quiescent and the newer drainer must resolve pending traced
        reports: an older metadata replay can conflict after acknowledgement loss.
        """
        assert self._db is not None
        async with self._work_item_row_write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await self._db.execute(
                    "PRAGMA table_info(promoted_report_outbox)",
                )
                columns = await cursor.fetchall()
                existing = next(
                    (column for column in columns if column[1] == "tool_trace_ref"),
                    None,
                )
                if existing is None:
                    await self._db.execute(
                        "ALTER TABLE promoted_report_outbox "
                        "ADD COLUMN tool_trace_ref TEXT",
                    )
                elif (
                    existing[0] != len(columns) - 1
                    or existing[2].upper() != "TEXT"
                    or existing[3] != 0
                    or (
                        existing[4] is not None
                        and (
                            type(existing[4]) is not str
                            or existing[4].strip().upper() != "NULL"
                        )
                    )
                    or existing[5] != 0
                ):
                    raise ValueError("promoted_report_trace_column_incompatible")
                await self._db.commit()
            except BaseException:
                logger.error(
                    "AD-1243: report trace migration failed; the schema is "
                    "unverified so startup stops and the owned connection closes",
                )
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    logger.error(
                        "AD-1243: report trace migration rollback failed; startup "
                        "cannot safely continue and the owned connection is closed",
                    )
                raise

    async def stop(self) -> None:
        """Stop tick loop and close DB."""
        self._running = False
        self._owned_execution_scopes.clear()
        self._owned_execution_port = None
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

    @staticmethod
    def _event_work_item_projection(item: WorkItem | None) -> dict[str, Any]:
        if item is None:
            return {}
        if item.work_type == "crew_session":
            return {
                "id": item.id,
                "work_type": item.work_type,
                "status": item.status,
            }
        return item.to_dict()

    def _require_execution_port(self, port: object) -> None:
        if port is not self._owned_execution_port or not self._running or self._db is None:
            raise owned_steps.OwnedStepsError("owned_steps_execution_port_expired")

    def _execution_scope(
        self, port: object, lease: owned_steps.OwnedExecutionLease,
    ) -> _OwnedExecutionScope:
        self._require_execution_port(port)
        if type(lease) is not owned_steps.OwnedExecutionLease:
            raise owned_steps.OwnedStepsError("owned_steps_execution_scope_invalid")
        context = lease.authority.context
        if (
            type(context) is not _OwnedExecutionScope or context not in self._owned_execution_scopes
            or context.port is not port
        ):
            raise owned_steps.OwnedStepsError("owned_steps_execution_scope_invalid")
        return context

    async def _admit_legacy_execution(
        self, port: object, parent_id: str, *, children: tuple[WorkItem, ...], thread_id: str,
    ) -> owned_steps.OwnedExecutionLease:
        self._require_execution_port(port)
        expected = _detach_plan_adoption_children(parent_id, tuple(sorted(children, key=lambda child: child.id)))
        changed = False
        async with self._booking_transaction():
            self._require_execution_port(port)
            parent = await self.get_work_item(parent_id)
            if parent is None or parent.work_type == "crew_session":
                raise owned_steps.OwnedStepsError("owned_steps_execution_scope_denied", parent_id=parent_id)
            cursor = await self._db.execute(
                "SELECT steps,steps_control FROM work_items WHERE id = ?", (parent_id,),
            )
            raw = await cursor.fetchone()
            existing_snapshot: owned_steps.OwnedStepsSnapshot | None = None
            cursor = await self._db.execute(
                "SELECT * FROM work_items WHERE parent_id = ? ORDER BY id LIMIT ?",
                (parent_id, owned_steps.MAX_OWNED_ROWS + 1),
            )
            direct = tuple(self._row_to_work_item(row) for row in await cursor.fetchall())
            if raw["steps_control"] is None:
                live = direct
                if len(live) != len(expected) or any(
                    not _json_values_exactly_equal(child.to_dict(), previous)
                    for child, previous in zip(live, expected)
                ):
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_execution_plan_conflict",
                        parent_id=parent_id,
                    )
            else:
                existing_snapshot, _, active = await self._load_owned_steps(parent_id)
                live = tuple(
                    active[row.child.child_id]
                    for row in existing_snapshot.control.rows
                    if row.child is not None
                )
                if {child.id for child in live} != {
                    previous["id"] for previous in expected
                }:
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_execution_plan_conflict",
                        parent_id=parent_id,
                    )
            if raw["steps_control"] is None:
                commitments = tuple(
                    owned_steps.OwnedStepChild(
                        child_id=child.id, spec_id=child.metadata.get("spec_id", child.id),
                        commitment_digest=owned_steps.owned_child_commitment(child.to_dict()),
                    ) for child in children
                )
                plan = owned_steps.OwnedStepsSeedPlan(
                    parent_id=parent_id, owner_kind="legacy", thread_id=thread_id, facilitator_id=None,
                    incarnation=uuid.uuid4().hex,
                    plan_digest=owned_steps.owned_digest(owned_steps.owned_json_bytes(
                        [entry.model_dump(mode="json") for entry in commitments],
                    )),
                    expected_steps_digest=owned_steps.owned_digest(raw["steps"]), children=commitments,
                )
                bootstrap = _OwnedExecutionScope(port, plan)
                self._owned_execution_scopes.add(bootstrap)
                seed = owned_steps.OwnedStepsSeed(plan, owned_steps.OwnedStepsAuthority(bootstrap))
                request_digest = owned_steps.owned_digest(_compact_exact_json_bytes(
                    {"parent_id": parent_id, "thread_id": thread_id, "children": list(expected)},
                    error="owned_steps_execution_scope_invalid",
                ))
                await self._seed_owned_steps(parent, live, seed, request_digest)
                await self._db.execute("UPDATE work_items SET updated_at=? WHERE id=?", (time.time(), parent_id))
                changed = True
            if existing_snapshot is None:
                snapshot, parent, _ = await self._load_owned_steps(parent_id)
            else:
                snapshot = existing_snapshot
            control = snapshot.control
            if control.owner_kind != "legacy" or control.thread_id != thread_id:
                raise owned_steps.OwnedStepsError("owned_steps_execution_scope_denied", parent_id=parent_id)
            plan = owned_steps.OwnedStepsSeedPlan(
                parent_id=parent_id, owner_kind="legacy", thread_id=control.thread_id,
                facilitator_id=control.facilitator_id, incarnation=control.incarnation,
                plan_digest=control.plan_digest, expected_steps_digest=control.steps_digest,
                children=tuple(row.child for row in control.rows if row.child),
            )
            scope = _OwnedExecutionScope(port, plan, control.rows)
            self._owned_execution_scopes.add(scope)
            lease = owned_steps.OwnedExecutionLease(snapshot, owned_steps.OwnedStepsAuthority(scope))
        if changed:
            await self._refresh_snapshot_cache()
            self._emit(EventType.WORK_ITEM_UPDATED, {"work_item": self._event_work_item_projection(parent)})
        return lease

    @staticmethod
    def _execution_view(
        lease: owned_steps.OwnedExecutionLease, row: owned_steps.OwnedStepRecord,
    ) -> owned_steps.StepViewToken:
        return owned_steps.execution_step_token(lease, row)

    async def validate_owned_execution_permit(
        self, permit: owned_steps.OwnedStepExecutionPermit, authority: owned_steps.OwnedStepsAuthority,
    ) -> None:
        if self._db is None:
            raise owned_steps.OwnedStepsError("owned_steps_unavailable", parent_id=permit.parent_id)
        async with self._booking_transaction():
            snapshot, _, _ = await self._load_owned_steps(permit.parent_id, step_id=permit.step_id)
            await self._authorize_owned_steps(authority, parent_id=permit.parent_id, operation="execution_active", token=permit)
            row = next((row for row in snapshot.control.rows if row.step_id == permit.step_id), None)
            permit_digest = owned_steps.owned_digest(
                owned_steps.owned_json_bytes(permit.model_dump(mode="json"))
            )
            if permit.review_attempt_id is None:
                valid = (
                    row is not None
                    and row.permit_state == "started"
                    and row.assignment_epoch == permit.assignment_epoch
                    and row.permit == permit_digest
                )
            else:
                stored = await self._read_owned_journal(
                    permit.parent_id,
                    permit.incarnation,
                    "permit",
                    permit_digest,
                )
                valid = (
                    row is not None
                    and row.permit_state == "submitted"
                    and row.reviewed_result is None
                    and row.assignment_epoch == permit.assignment_epoch
                    and row.source_digest == permit.source_digest
                    and stored is not None
                    and owned_steps.OwnedStepExecutionPermit.model_validate_json(
                        stored
                    ) == permit
                )
            if (
                not valid
                or snapshot.control.incarnation != permit.incarnation
                or snapshot.control.plan_digest != permit.plan_digest
            ):
                raise owned_steps.OwnedStepsError("owned_steps_execution_revoked", parent_id=permit.parent_id)

    async def admit_owned_correction(
        self,
        snapshot: owned_steps.OwnedStepsSnapshot,
        child_id: str,
        *,
        reviewer_id: str,
        review_attempt_id: str,
        execution_nonce: str,
        authority: owned_steps.OwnedStepsAuthority,
    ) -> owned_steps.OwnedStepMutationResult:
        if self._db is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_unavailable",
                parent_id=snapshot.control.parent_id,
            )
        operation_id = owned_steps.owned_digest(
            owned_steps.owned_json_bytes(
                [
                    "correction_start",
                    snapshot.control.incarnation,
                    child_id,
                    review_attempt_id,
                    execution_nonce,
                ]
            )
        )
        request_digest = owned_steps.owned_digest(
            owned_steps.owned_json_bytes(
                {
                    "child_id": child_id,
                    "reviewer_id": reviewer_id,
                    "review_attempt_id": review_attempt_id,
                    "execution_nonce": execution_nonce,
                }
            )
        )
        async with self._booking_transaction():
            live, _, children = await self._load_owned_steps(
                snapshot.control.parent_id,
                step_id=next(
                    (
                        row.step_id
                        for row in snapshot.control.rows
                        if row.child is not None and row.child.child_id == child_id
                    ),
                    None,
                ),
            )
            row = next(
                (
                    row
                    for row in live.control.rows
                    if row.child is not None and row.child.child_id == child_id
                ),
                None,
            )
            captured = next(
                (
                    row
                    for row in snapshot.control.rows
                    if row.child is not None and row.child.child_id == child_id
                ),
                None,
            )
            if row is None or captured is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_row_missing",
                    parent_id=snapshot.control.parent_id,
                )
            if row.permit is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_correction_conflict",
                    parent_id=live.control.parent_id,
                )
            original = await self._read_owned_evidence(
                live.control.parent_id,
                live.control.incarnation,
                "permit",
                row.permit,
            )
            grant = await self._authorize_owned_steps(
                authority,
                parent_id=live.control.parent_id,
                operation="admit_correction",
                token=original,
            )
            if (
                captured != row
                or snapshot.control.incarnation != live.control.incarnation
                or snapshot.control.plan_digest != live.control.plan_digest
                or row.permit_state != "submitted"
                or row.reviewed_result is not None
                or row.submission is None
                or grant.role != "verifier"
                or grant.actor_id != reviewer_id
                or reviewer_id == row.assignee_id
                or original.review_attempt_id is not None
                or child_id not in children
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_correction_conflict",
                    parent_id=live.control.parent_id,
                )
            replay = await self._owned_operation_receipt(
                live.control.parent_id,
                live.control.incarnation,
                operation_id,
            )
            if replay is not None:
                if replay.request_digest != request_digest:
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_operation_conflict",
                        parent_id=live.control.parent_id,
                    )
                return owned_steps.OwnedStepMutationResult(
                    None,
                    "already_started",
                    replay.permit,
                    replay,
                )
            cursor = await self._db.execute(
                "SELECT COUNT(*) FROM owned_steps_journal "
                "WHERE parent_id=? AND incarnation=? AND kind='permit' "
                "AND step_id=? AND json_extract(payload,'$.review_attempt_id') IS NOT NULL",
                (live.control.parent_id, live.control.incarnation, row.step_id),
            )
            if (await cursor.fetchone())[0] >= 8:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_correction_limit",
                    parent_id=live.control.parent_id,
                )
            permit = original.model_copy(
                update={
                    "execution_nonce": execution_nonce,
                    "review_attempt_id": review_attempt_id,
                    "source_digest": row.source_digest,
                }
            )
            await self._write_owned_evidence(permit)
            receipt = owned_steps.OwnedOperationReceipt(
                operation_id=operation_id,
                request_digest=request_digest,
                step_id=row.step_id,
                disposition="correction_started",
                permit=permit,
                observation=owned_steps.OwnedStepObservation(
                    parent_id=live.control.parent_id,
                    incarnation=live.control.incarnation,
                    plan_digest=live.control.plan_digest,
                    plan_revision=live.control.plan_revision,
                    layout_revision=live.control.layout_revision,
                    observation_revision=live.control.observation_revision,
                    steps_digest=live.control.steps_digest,
                    step_id=row.step_id,
                    row_revision=row.revision,
                    row_digest=row.digest,
                    todo_json=row.todo_json,
                    source_digest=row.source_digest,
                    permit_state=row.permit_state,
                ),
            )
            await self._write_owned_journal(
                live.control.parent_id,
                live.control.incarnation,
                "operation",
                operation_id,
                owned_steps.owned_json_bytes(receipt.model_dump(mode="json")).decode(
                    "utf-8"
                ),
                step_id=row.step_id,
            )
        return owned_steps.OwnedStepMutationResult(
            live,
            "new",
            permit,
            receipt,
        )

    async def record_owned_correction(
        self,
        snapshot: owned_steps.OwnedStepsSnapshot,
        correction: owned_steps.OwnedCorrectionResult,
        authority: owned_steps.OwnedStepsAuthority,
    ) -> owned_steps.OwnedStepMutationResult:
        permit = correction.permit
        if self._db is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_unavailable",
                parent_id=permit.parent_id,
            )
        record_id = owned_steps.owned_digest(
            owned_steps.owned_json_bytes(
                ["correction_result", permit.review_attempt_id]
            )
        )
        payload = owned_steps.owned_json_bytes(
            correction.model_dump(mode="json")
        ).decode("utf-8")
        async with self._booking_transaction():
            live, _, _ = await self._load_owned_steps(
                permit.parent_id,
                step_id=permit.step_id,
            )
            row = next(
                (
                    row
                    for row in live.control.rows
                    if row.step_id == permit.step_id
                ),
                None,
            )
            grant = await self._authorize_owned_steps(
                authority,
                parent_id=permit.parent_id,
                operation="record_correction",
                token=permit,
            )
            permit_digest = owned_steps.owned_digest(
                owned_steps.owned_json_bytes(permit.model_dump(mode="json"))
            )
            stored_permit = await self._read_owned_journal(
                permit.parent_id,
                permit.incarnation,
                "permit",
                permit_digest,
            )
            if (
                snapshot.control.incarnation != live.control.incarnation
                or snapshot.control.plan_digest != live.control.plan_digest
                or row is None
                or row.permit_state != "submitted"
                or row.reviewed_result is not None
                or row.assignment_epoch != permit.assignment_epoch
                or row.source_digest != permit.source_digest
                or permit.review_attempt_id is None
                or grant.role != "verifier"
                or grant.actor_id != correction.reviewer_id
                or grant.actor_id == row.assignee_id
                or stored_permit is None
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_correction_conflict",
                    parent_id=permit.parent_id,
                )
            created = await self._write_owned_journal(
                permit.parent_id,
                permit.incarnation,
                "operation",
                record_id,
                payload,
                step_id=row.step_id,
            )
        return owned_steps.OwnedStepMutationResult(
            live,
            "new" if created else "duplicate",
            permit,
        )

    async def read_owned_correction(
        self,
        snapshot: owned_steps.OwnedStepsSnapshot,
        permit: owned_steps.OwnedStepExecutionPermit,
    ) -> owned_steps.OwnedCorrectionResult | None:
        if self._db is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_unavailable",
                parent_id=permit.parent_id,
            )
        record_id = owned_steps.owned_digest(
            owned_steps.owned_json_bytes(
                ["correction_result", permit.review_attempt_id]
            )
        )
        async with self._booking_transaction():
            live, _, _ = await self._load_owned_steps(
                permit.parent_id,
                step_id=permit.step_id,
            )
            if (
                snapshot.control.incarnation != live.control.incarnation
                or snapshot.control.plan_digest != live.control.plan_digest
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_correction_conflict",
                    parent_id=permit.parent_id,
                )
            payload = await self._read_owned_journal(
                permit.parent_id,
                permit.incarnation,
                "operation",
                record_id,
            )
            if payload is None:
                return None
            try:
                result = owned_steps.OwnedCorrectionResult.model_validate_json(
                    payload
                )
            except ValueError as exc:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_journal_integrity",
                    parent_id=permit.parent_id,
                ) from exc
            if result.permit != permit:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_correction_conflict",
                    parent_id=permit.parent_id,
                )
            return result

    async def _start_legacy_execution(
        self, port: object, lease: owned_steps.OwnedExecutionLease, child_id: str, *, execution_nonce: str,
    ) -> owned_steps.OwnedStepMutationResult:
        scope = self._execution_scope(port, lease)
        row = next((row for row in scope.rows if row.child and row.child.child_id == child_id), None)
        if row is None:
            raise owned_steps.OwnedStepsError("owned_steps_execution_scope_denied", parent_id=scope.plan.parent_id)
        return await self.compare_and_set_owned_step(owned_steps.OwnedStepMutation(
            owned_steps.OwnedStepChange(
                operation_id=owned_steps.owned_digest(owned_steps.owned_json_bytes(
                    ["start", scope.plan.incarnation, child_id, execution_nonce],
                )),
                token=self._execution_view(lease, row),
                command=owned_steps.StartOwnedStepCommand(execution_nonce=execution_nonce),
            ),
            lease.authority,
        ))

    async def _submit_legacy_execution(
        self, port: object, lease: owned_steps.OwnedExecutionLease,
        submission: owned_steps.OwnedExecutionSubmission,
    ) -> owned_steps.OwnedStepMutationResult:
        self._execution_scope(port, lease)
        return await self.compare_and_set_owned_step(owned_steps.OwnedStepMutation(
            owned_steps.OwnedStepChange(
                operation_id=owned_steps.owned_digest(owned_steps.owned_json_bytes(
                    ["submit", submission.permit.incarnation, submission.permit.child_id, submission.permit.execution_nonce],
                )),
                token=submission.permit,
                command=owned_steps.SubmitOwnedStepCommand(submission=submission),
            ),
            lease.authority,
        ))

    async def _validate_legacy_execution(
        self, port: object, lease: owned_steps.OwnedExecutionLease,
        permit: owned_steps.OwnedStepExecutionPermit,
    ) -> None:
        scope = self._execution_scope(port, lease)
        async with self._booking_transaction():
            self._execution_scope(port, lease)
            snapshot, _, _ = await self._load_owned_steps(scope.plan.parent_id, step_id=permit.step_id)
            if (
                snapshot.control.owner_kind != "legacy" or snapshot.control.thread_id != scope.plan.thread_id
                or snapshot.control.incarnation != scope.plan.incarnation
                or snapshot.control.plan_digest != scope.plan.plan_digest
            ):
                raise owned_steps.OwnedStepsError("owned_steps_execution_scope_denied", parent_id=scope.plan.parent_id)
            await self._authorize_owned_steps(
                lease.authority, parent_id=scope.plan.parent_id, operation="execution_active", token=permit,
            )
            row = next((row for row in snapshot.control.rows if row.step_id == permit.step_id), None)
            if (
                row is None or row.permit_state != "started"
                or row.permit != owned_steps.owned_digest(owned_steps.owned_json_bytes(permit.model_dump(mode="json")))
                or row.assignment_epoch != permit.assignment_epoch
            ):
                raise owned_steps.OwnedStepsError("owned_steps_execution_revoked", parent_id=scope.plan.parent_id)

    async def _submit_unstarted_legacy_execution(
        self, port: object, lease: owned_steps.OwnedExecutionLease, submission: owned_steps.OwnedUnstartedSubmission,
    ) -> owned_steps.OwnedStepMutationResult:
        scope = self._execution_scope(port, lease)
        row = next((row for row in scope.rows if row.step_id == submission.step_id and row.child), None)
        if row is None:
            raise owned_steps.OwnedStepsError("owned_steps_execution_scope_denied", parent_id=scope.plan.parent_id)
        return await self.compare_and_set_owned_step(owned_steps.OwnedStepMutation(
            owned_steps.OwnedStepChange(
                operation_id=owned_steps.owned_digest(owned_steps.owned_json_bytes(
                    ["unstarted", scope.plan.incarnation, row.step_id, row.assignment_epoch],
                )),
                token=self._execution_view(lease, row), command=owned_steps.UnstartedOwnedStepCommand(submission=submission),
            ),
            lease.authority,
        ))

    async def _read_owned_journal(
        self, parent_id: str, incarnation: str, kind: str, record_id: str,
    ) -> str | None:
        assert self._db is not None
        if (
            any(type(value) is not str or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(value) is None
                for value in (parent_id, incarnation, record_id))
            or kind not in ("operation", "effect", "permit", "submission", "review", "control")
        ):
            raise owned_steps.OwnedStepsError("owned_steps_journal_key_invalid")
        cursor = await self._db.execute(
            "SELECT payload, payload_digest FROM owned_steps_journal "
            "WHERE parent_id = ? AND incarnation = ? AND kind = ? AND record_id = ?",
            (parent_id, incarnation, kind, record_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        payload = row["payload"]
        if (
            type(payload) is not str
            or len(payload.encode("utf-8")) > owned_steps.MAX_OWNED_MANIFEST_BYTES
            or owned_steps.owned_digest(payload) != row["payload_digest"]
            or (kind in ("permit", "submission", "review", "control") and record_id != row["payload_digest"])
        ):
            raise owned_steps.OwnedStepsError("owned_steps_journal_integrity", parent_id=parent_id)
        return payload

    async def _write_owned_journal(
        self, parent_id: str, incarnation: str, kind: str, record_id: str,
        payload: str, *, step_id: str | None = None, accepted: bool | None = None,
    ) -> bool:
        """Insert only; a conflicting copy cannot replace a receipt or claim."""
        assert self._db is not None
        if len(payload.encode("utf-8")) > owned_steps.MAX_OWNED_MANIFEST_BYTES:
            raise owned_steps.OwnedStepsError("owned_steps_manifest_too_large", parent_id=parent_id)
        digest = owned_steps.owned_digest(payload)
        cursor = await self._db.execute(
            "SELECT payload, payload_digest, step_id, accepted FROM owned_steps_journal "
            "WHERE parent_id = ? AND incarnation = ? AND kind = ? AND record_id = ?",
            (parent_id, incarnation, kind, record_id),
        )
        previous = await cursor.fetchone()
        if previous is not None:
            if (
                previous["payload"] != payload or previous["payload_digest"] != digest
                or previous["step_id"] != step_id or previous["accepted"] != accepted
            ):
                raise owned_steps.OwnedStepsError("owned_steps_journal_conflict", parent_id=parent_id)
            return False
        await self._db.execute(
            "INSERT INTO owned_steps_journal "
            "(parent_id,incarnation,kind,record_id,payload_digest,payload,step_id,accepted) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (parent_id, incarnation, kind, record_id, digest, payload, step_id, accepted),
        )
        return True

    async def _write_owned_evidence(
        self, evidence: (
            owned_steps.OwnedStepExecutionPermit | owned_steps.OwnedStepSubmission
            | owned_steps.ReviewedStepResult
        ),
    ) -> str:
        kinds = {
            owned_steps.OwnedStepExecutionPermit: "permit",
            owned_steps.OwnedStepSubmission: "submission",
            owned_steps.OwnedExecutionSubmission: "submission",
            owned_steps.OwnedUnstartedSubmission: "submission",
            owned_steps.ReviewedStepResult: "review",
        }
        if type(evidence) not in kinds:
            raise owned_steps.OwnedStepsError("owned_steps_evidence_invalid")
        permit = (
            evidence if isinstance(evidence, (owned_steps.OwnedStepExecutionPermit, owned_steps.OwnedUnstartedSubmission))
            else evidence.permit
        )
        payload = owned_steps.owned_json_bytes(evidence.model_dump(mode="json")).decode("utf-8")
        digest = owned_steps.owned_digest(payload)
        await self._write_owned_journal(
            permit.parent_id, permit.incarnation, kinds[type(evidence)], digest, payload,
            step_id=permit.step_id,
            accepted=evidence.accepted if isinstance(evidence, owned_steps.ReviewedStepResult) else None,
        )
        return digest

    async def _read_owned_evidence(
        self, parent_id: str, incarnation: str, kind: str, digest: str,
    ) -> owned_steps.OwnedStepExecutionPermit | owned_steps.OwnedStepSubmission | owned_steps.ReviewedStepResult:
        models = {
            "permit": owned_steps.OwnedStepExecutionPermit,
            "submission": owned_steps.OwnedStepSubmission,
            "review": owned_steps.ReviewedStepResult,
        }
        if kind not in models:
            raise owned_steps.OwnedStepsError("owned_steps_evidence_invalid", parent_id=parent_id)
        payload = await self._read_owned_journal(parent_id, incarnation, kind, digest)
        if payload is None:
            raise owned_steps.OwnedStepsError("owned_steps_evidence_missing", parent_id=parent_id)
        try:
            raw = owned_steps.owned_json_loads(payload)
            model = models[kind]
            if kind == "submission" and raw.get("version") == 2:
                model = (
                    owned_steps.OwnedUnstartedSubmission if raw.get("admission") == "not_started"
                    else owned_steps.OwnedExecutionSubmission
                )
            evidence = model.model_validate_json(payload)
            if evidence.model_dump(mode="json") != owned_steps.owned_json_loads(payload):
                raise ValueError("owned_steps_evidence_incomplete")
        except ValueError as exc:
            raise owned_steps.OwnedStepsError("owned_steps_evidence_invalid", parent_id=parent_id) from exc
        permit = (
            evidence if isinstance(evidence, (owned_steps.OwnedStepExecutionPermit, owned_steps.OwnedUnstartedSubmission))
            else evidence.permit
        )
        if permit.parent_id != parent_id or permit.incarnation != incarnation:
            raise owned_steps.OwnedStepsError("owned_steps_evidence_conflict", parent_id=parent_id)
        return evidence

    async def get_owned_step_evidence(
        self, parent_id: str, incarnation: str,
        kind: Literal["permit", "submission", "review"], digest: str,
    ) -> owned_steps.OwnedStepExecutionPermit | owned_steps.OwnedStepSubmission | owned_steps.ReviewedStepResult:
        if self._db is None:
            raise owned_steps.OwnedStepsError("owned_steps_unavailable", parent_id=parent_id)
        async with self._booking_transaction():
            return await self._read_owned_evidence(parent_id, incarnation, kind, digest)

    async def _owned_operation_receipt(
        self, parent_id: str, incarnation: str, operation_id: str,
    ) -> owned_steps.OwnedOperationReceipt | None:
        payload = await self._read_owned_journal(parent_id, incarnation, "operation", operation_id)
        if payload is None:
            return None
        try:
            receipt = owned_steps.OwnedOperationReceipt.model_validate_json(payload)
            if (
                receipt.operation_id != operation_id
                or receipt.model_dump(mode="json") != owned_steps.owned_json_loads(payload)
                or (receipt.permit is not None and (
                    receipt.permit.parent_id != parent_id or receipt.permit.incarnation != incarnation
                ))
                or (receipt.observation is not None and (
                    receipt.observation.parent_id != parent_id or receipt.observation.incarnation != incarnation
                ))
            ):
                raise ValueError("owned_steps_receipt_conflict")
            return receipt
        except ValueError as exc:
            raise owned_steps.OwnedStepsError("owned_steps_journal_integrity", parent_id=parent_id) from exc

    async def get_owned_operation_receipt(
        self, parent_id: str, incarnation: str, operation_id: str,
    ) -> owned_steps.OwnedOperationReceipt | None:
        if self._db is None:
            raise owned_steps.OwnedStepsError("owned_steps_unavailable", parent_id=parent_id)
        async with self._booking_transaction():
            return await self._owned_operation_receipt(parent_id, incarnation, operation_id)

    async def get_owned_effect_attempt(
        self, parent_id: str, incarnation: str, effect_id: str,
    ) -> owned_steps.OwnedEffectAttempt | None:
        if self._db is None:
            raise owned_steps.OwnedStepsError("owned_steps_unavailable", parent_id=parent_id)
        async with self._booking_transaction():
            return await self._owned_effect_attempt(parent_id, incarnation, effect_id)

    async def _owned_effect_attempt(
        self, parent_id: str, incarnation: str, effect_id: str,
    ) -> owned_steps.OwnedEffectAttempt | None:
        payload = await self._read_owned_journal(parent_id, incarnation, "effect", effect_id)
        if payload is None:
            return None
        try:
            attempt = owned_steps.OwnedEffectAttempt.model_validate_json(payload)
            if attempt.effect_id != effect_id or attempt.model_dump(mode="json") != owned_steps.owned_json_loads(payload):
                raise ValueError("owned_steps_effect_conflict")
            return attempt
        except ValueError as exc:
            raise owned_steps.OwnedStepsError("owned_steps_journal_integrity", parent_id=parent_id) from exc

    async def claim_owned_effect_attempt(
        self, claim: owned_steps.OwnedEffectClaim,
    ) -> owned_steps.OwnedEffectClaimResult:
        """Claim before a legacy effect; never execute, retire, or retry it here."""
        if type(claim) is not owned_steps.OwnedEffectClaim:
            raise owned_steps.OwnedStepsError("owned_steps_effect_invalid")
        token = owned_steps.OwnedStepsPlanToken.model_validate(claim.token)
        attempt = owned_steps.OwnedEffectAttempt.model_validate(claim.attempt)
        if self._db is None:
            raise owned_steps.OwnedStepsError("owned_steps_unavailable", parent_id=token.parent_id)
        async with self._booking_transaction():
            snapshot, _, _ = await self._load_owned_steps(token.parent_id)
            control = snapshot.control
            grant = await self._authorize_owned_steps(
                claim.authority, parent_id=token.parent_id, operation="claim_effect", token=token,
            )
            if grant.role != "owner":
                self._require_owned_manager(control, grant)
            if (
                token.incarnation != control.incarnation or token.plan_digest != control.plan_digest
                or token.plan_revision != control.plan_revision
            ):
                raise owned_steps.OwnedStepsError("owned_steps_plan_conflict", parent_id=token.parent_id)
            previous = await self._owned_effect_attempt(token.parent_id, token.incarnation, attempt.effect_id)
            if previous is not None:
                if previous != attempt:
                    raise owned_steps.OwnedStepsError("owned_steps_effect_conflict", parent_id=token.parent_id)
                return owned_steps.OwnedEffectClaimResult(previous, False)
            if (
                control.owner_kind != "legacy" or control.finalization is None
                or control.finalization_disposition != "pending"
                or token.source_digest != snapshot.source_digest
                or token.steps_digest != control.steps_digest
                or token.layout_revision != control.layout_revision
            ):
                raise owned_steps.OwnedStepsError("owned_steps_effect_binding_required", parent_id=token.parent_id)
            created = await self._write_owned_journal(
                token.parent_id, token.incarnation, "effect", attempt.effect_id,
                owned_steps.owned_json_bytes(attempt.model_dump(mode="json")).decode("utf-8"),
            )
            return owned_steps.OwnedEffectClaimResult(attempt, created)

    async def claim_owned_synthesis(
        self, token: owned_steps.OwnedStepsPlanToken, authority: owned_steps.OwnedStepsAuthority,
    ) -> owned_steps.OwnedStepMutationResult:
        """Fence synthesis before any model call; an uncertain start never re-arms."""
        token = owned_steps.OwnedStepsPlanToken.model_validate(token)
        if self._db is None:
            raise owned_steps.OwnedStepsError("owned_steps_unavailable", parent_id=token.parent_id)
        async with self._booking_transaction():
            snapshot, _, _ = await self._load_owned_steps(token.parent_id)
            control = snapshot.control
            grant = await self._authorize_owned_steps(
                authority, parent_id=token.parent_id, operation="begin_synthesis", token=token,
            )
            if grant.role != "owner" or (
                token.incarnation != control.incarnation or token.plan_digest != control.plan_digest
                or token.plan_revision != control.plan_revision or token.thread_id != control.thread_id
            ):
                raise owned_steps.OwnedStepsError("owned_steps_authority_denied", parent_id=token.parent_id)
            digest = owned_steps.owned_digest(owned_steps.owned_json_bytes({
                "parent_id": control.parent_id, "incarnation": control.incarnation,
                "plan_digest": control.plan_digest,
                "source_review_digest": owned_steps.owned_source_review_digest(control),
            }))
            previous = await self._owned_operation_receipt(control.parent_id, control.incarnation, "synthesis-start")
            if previous is not None:
                if previous.request_digest != digest or previous.disposition != "synthesis_started":
                    raise owned_steps.OwnedStepsError("owned_steps_operation_conflict", parent_id=token.parent_id)
                return owned_steps.OwnedStepMutationResult(None, "already_started", receipt=previous)
            if (
                control.mode != "active" or control.finalization is not None
                or token.layout_revision != control.layout_revision
                or token.steps_digest != control.steps_digest or token.source_digest != snapshot.source_digest
                or any(row.child and row.permit_state != "terminal" for row in control.rows)
            ):
                raise owned_steps.OwnedStepsError("owned_steps_finalization_state", parent_id=token.parent_id)
            receipt = owned_steps.OwnedOperationReceipt(
                operation_id="synthesis-start", request_digest=digest, step_id=None,
                disposition="synthesis_started",
                observation=owned_steps.OwnedStepObservation(
                    parent_id=control.parent_id, incarnation=control.incarnation,
                    plan_digest=control.plan_digest, plan_revision=control.plan_revision,
                    layout_revision=control.layout_revision, observation_revision=control.observation_revision,
                    steps_digest=control.steps_digest, step_id=None, row_revision=None, row_digest=None,
                    todo_json=None, source_digest=None, permit_state=None,
                ),
            )
            await self._write_owned_journal(
                control.parent_id, control.incarnation, "operation", receipt.operation_id,
                owned_steps.owned_json_bytes(receipt.model_dump(mode="json")).decode("utf-8"),
            )
            return owned_steps.OwnedStepMutationResult(snapshot, "new", receipt=receipt)

    async def get_owned_synthesis_claim(
        self,
        parent_id: str,
    ) -> owned_steps.OwnedOperationReceipt | None:
        """Return the exact durable synthesis-start fence for the live incarnation."""
        if type(parent_id) is not str or not parent_id:
            raise owned_steps.OwnedStepsError("owned_steps_parent_invalid")
        if self._db is None:
            return None
        async with self._booking_transaction():
            snapshot, _, _ = await self._load_owned_steps(parent_id)
            control = snapshot.control
            receipt = await self._owned_operation_receipt(
                control.parent_id,
                control.incarnation,
                "synthesis-start",
            )
            if receipt is None:
                return None
            digest = owned_steps.owned_digest(owned_steps.owned_json_bytes({
                "parent_id": control.parent_id,
                "incarnation": control.incarnation,
                "plan_digest": control.plan_digest,
                "source_review_digest": owned_steps.owned_source_review_digest(control),
            }))
            if (
                receipt.request_digest != digest
                or receipt.disposition != "synthesis_started"
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_operation_conflict",
                    parent_id=parent_id,
                )
            return receipt

    async def compare_and_set_owned_finalization(
        self, finalization: owned_steps.OwnedFinalization,
    ) -> owned_steps.OwnedFinalizationResult:
        """Bind or close an exact frozen finalization receipt under owner CAS.

        ``bind`` persists the immutable receipt (disposition ``pending``) so a
        legacy effect claim has a durable anchor before its incidental effect;
        ``complete`` closes it and also self-binds when no prior pending receipt
        exists, so finalize-only recovery is a single validate-and-close call.
        This never runs a worker, verifier, synthesis or decomposition. The same
        receipt replays idempotently; a changed receipt or source/review vector,
        wrong incarnation/plan or advanced projection is a typed conflict.
        """
        if type(finalization) is not owned_steps.OwnedFinalization:
            raise owned_steps.OwnedStepsError("owned_steps_finalization_invalid")
        token = owned_steps.OwnedStepsPlanToken.model_validate(finalization.token)
        receipt = owned_steps.FinalizeReceipt.model_validate(finalization.receipt)
        if type(finalization.source_review_digest) is not str:
            raise owned_steps.OwnedStepsError("owned_steps_finalization_invalid", parent_id=token.parent_id)
        if finalization.phase not in ("bind", "complete"):
            raise owned_steps.OwnedStepsError("owned_steps_finalization_invalid", parent_id=token.parent_id)
        if self._db is None:
            raise owned_steps.OwnedStepsError("owned_steps_unavailable", parent_id=token.parent_id)
        result: owned_steps.OwnedFinalizationResult | None = None
        committed = False
        async with self._booking_transaction():
            snapshot, parent, _ = await self._load_owned_steps(token.parent_id)
            control = snapshot.control
            grant = await self._authorize_owned_steps(
                finalization.authority, parent_id=parent.id, operation="finalize", token=token,
            )
            if grant.role != "owner":
                self._require_owned_manager(control, grant)
            already_bound = control.finalization == receipt
            if (
                token.incarnation != control.incarnation or token.plan_digest != control.plan_digest
                or token.plan_revision != control.plan_revision
                or token.layout_revision != control.layout_revision
                or (not already_bound and token.steps_digest != control.steps_digest)
                or (not already_bound and token.source_digest != snapshot.source_digest)
                or token.thread_id != control.thread_id
            ):
                raise owned_steps.OwnedStepsError("owned_steps_plan_conflict", parent_id=parent.id)
            if (
                receipt.parent_id != control.parent_id or receipt.owner_kind != control.owner_kind
                or receipt.thread_id != control.thread_id or receipt.incarnation != control.incarnation
                or receipt.plan_digest != control.plan_digest
                or receipt.source_review_digest != finalization.source_review_digest
                or finalization.source_review_digest != owned_steps.owned_source_review_digest(control)
            ):
                raise owned_steps.OwnedStepsError("owned_steps_finalization_conflict", parent_id=parent.id)
            # Read back and hash-validate the exact frozen blobs the receipt binds
            # before any CAS; a missing/altered blob fails visibly, never silently.
            for reference in (receipt.output, receipt.manifest):
                await self.read_owned_steps_content(reference)
            for row in control.rows:
                if row.child is None:
                    continue
                if row.permit_state != "terminal" or row.submission is None:
                    raise owned_steps.OwnedStepsError("owned_steps_finalization_state", parent_id=parent.id)
                submission = await self._read_owned_evidence(
                    parent.id, control.incarnation, "submission", row.submission,
                )
                execution = owned_steps.owned_json_loads(submission.execution_json)
                if execution["status"] == "done":
                    if row.reviewed_result is None:
                        raise owned_steps.OwnedStepsError("owned_steps_finalization_state", parent_id=parent.id)
                    await self._read_owned_evidence(parent.id, control.incarnation, "review", row.reviewed_result)
            manual_pending = bool(parent.metadata.get("steps_gate_completion")) and any(
                row.kind == "manual" and owned_steps.owned_json_loads(row.todo_json)["status"] != "done"
                for row in control.rows
            )
            if control.finalization is not None:
                if control.finalization != receipt:
                    raise owned_steps.OwnedStepsError("owned_steps_finalization_conflict", parent_id=parent.id)
                if control.finalization_disposition == "completed" or finalization.phase == "bind" or manual_pending:
                    return owned_steps.OwnedFinalizationResult(
                        snapshot, control.finalization_disposition, False,
                    )
            if control.mode not in ("active", "waiting_manual_gate"):
                raise owned_steps.OwnedStepsError("owned_steps_finalization_state", parent_id=parent.id)
            complete = finalization.phase == "complete" and not manual_pending
            if complete:
                if control.owner_kind != "legacy":
                    raise owned_steps.OwnedStepsError("owned_steps_canonical_publication_required", parent_id=parent.id)
                if not self._validate_work_item_status_transition(parent, "done"):
                    raise owned_steps.OwnedStepsError("owned_steps_finalization_state", parent_id=parent.id)
                await self._db.execute(
                    "UPDATE work_items SET status='done',updated_at=? WHERE id=?", (time.time(), parent.id),
                )
                parent = await self.get_work_item(parent.id)
            candidate = control.with_finalization(
                receipt=receipt, disposition="completed" if complete else "pending",
                mode="completed" if complete else "waiting_manual_gate" if manual_pending else control.mode,
                parent_source_digest=await self._owned_parent_digest(parent),
            )
            await self._db.execute(
                "UPDATE work_items SET steps_control = ?, updated_at = ? WHERE id = ?",
                (candidate.model_dump_json(), time.time(), parent.id),
            )
            result = owned_steps.OwnedFinalizationResult(
                self._owned_snapshot(candidate), candidate.finalization_disposition, True,
            )
            committed = True
        if committed:
            await self._refresh_snapshot_cache()
            self._emit(EventType.WORK_ITEM_UPDATED, {"work_item": self._event_work_item_projection(parent)})
            if result.disposition == "completed":
                self._emit(EventType.WORK_ITEM_STATUS_CHANGED, {
                    "work_item": self._event_work_item_projection(parent), "new_status": "done",
                })
        assert result is not None
        return result

    async def _migrate_owned_steps_history(self) -> None:
        """Retain v1 facts atomically; no events, effects, or invented observations."""
        assert self._db is not None
        async with self._booking_transaction():
            cursor = await self._db.execute(
                "SELECT id, steps_control FROM work_items WHERE steps_control IS NOT NULL ORDER BY id",
            )
            while (stored := await cursor.fetchone()) is not None:
                raw = stored["steps_control"]
                header = owned_steps.owned_json_loads(raw)
                if type(header) is not dict:
                    raise owned_steps.OwnedStepsError("owned_steps_control_invalid", parent_id=stored["id"])
                if type(header.get("version")) is int and header["version"] == 2:
                    owned_steps.parse_owned_control(raw)
                    continue
                old = owned_steps.parse_inline_owned_control(raw)
                if old.parent_id != stored["id"]:
                    raise owned_steps.OwnedStepsError("owned_steps_parent_conflict", parent_id=stored["id"])
                for previous in old.operations:
                    receipt = owned_steps.OwnedOperationReceipt(**previous.model_dump())
                    if receipt.permit is not None and (
                        receipt.permit.parent_id != old.parent_id or receipt.permit.incarnation != old.incarnation
                    ):
                        raise owned_steps.OwnedStepsError("owned_steps_evidence_conflict", parent_id=old.parent_id)
                    await self._write_owned_journal(
                        old.parent_id, old.incarnation, "operation", receipt.operation_id,
                        owned_steps.owned_json_bytes(receipt.model_dump(mode="json")).decode("utf-8"),
                        step_id=receipt.step_id,
                    )
                for attempt in old.effect_attempts:
                    await self._write_owned_journal(
                        old.parent_id, old.incarnation, "effect", attempt.effect_id,
                        owned_steps.owned_json_bytes(attempt.model_dump(mode="json")).decode("utf-8"),
                    )
                rows: list[dict[str, Any]] = []
                for row in old.rows:
                    values = row.model_dump(mode="json")
                    for field in ("permit", "submission", "reviewed_result"):
                        evidence = getattr(row, field)
                        values[field] = await self._write_owned_evidence(evidence) if evidence is not None else None
                    values["review_accepted"] = row.reviewed_result.accepted if row.reviewed_result else None
                    rows.append(values)
                try:
                    owned_steps.owned_row_spans(old.original_steps_json)
                    owned_steps.owned_row_spans(old.authorized_steps_json)
                except owned_steps.OwnedStepsError:
                    archive = owned_steps.owned_digest(raw)
                    await self._write_owned_journal(old.parent_id, old.incarnation, "control", archive, raw)
                    control = owned_steps.OwnedStepsRepairControl(
                        parent_id=old.parent_id, incarnation=old.incarnation, owner_kind=old.owner_kind,
                        thread_id=old.thread_id, facilitator_id=old.facilitator_id, plan_digest=old.plan_digest,
                        child_ids=tuple(row.child.child_id for row in old.rows if row.child),
                        archived_control=archive, original_steps_digest=owned_steps.owned_digest(old.original_steps_json),
                        steps_digest=old.steps_digest,
                    )
                else:
                    values = old.model_dump(mode="json", exclude={"operations", "effect_attempts"})
                    values.update(version=2, rows=rows)
                    control = owned_steps.OwnedStepsControl.model_validate_json(owned_steps.owned_json_bytes(values))
                await self._db.execute(
                    "UPDATE work_items SET steps_control = ? WHERE id = ?",
                    (control.model_dump_json(), old.parent_id),
                )

    async def _owned_parent_id(self, work_item_id: str) -> str | None:
        if self._db is None:
            return None
        cursor = await self._db.execute(
            "SELECT owner.id FROM work_items AS owner "
            "WHERE owner.steps_control IS NOT NULL AND (owner.id = ? "
            "OR owner.id = (SELECT parent_id FROM work_items WHERE id = ?) "
            "OR EXISTS (SELECT 1 FROM json_each("
            "CASE WHEN json_valid(owner.steps_control) THEN owner.steps_control ELSE '{}' END, "
            "'$.rows') AS entry WHERE json_extract("
            "CASE WHEN json_valid(entry.value) THEN entry.value ELSE '{}' END, '$.child.child_id') = ?) "
            "OR EXISTS (SELECT 1 FROM json_each("
            "CASE WHEN json_valid(owner.steps_control) THEN owner.steps_control ELSE '{}' END, "
            "'$.child_ids') AS member WHERE member.value = ?))",
            (work_item_id, work_item_id, work_item_id, work_item_id),
        )
        rows = await cursor.fetchall()
        if len(rows) > 1:
            raise owned_steps.OwnedStepsError("owned_steps_membership_conflict")
        return rows[0]["id"] if rows else None

    async def resolve_owned_steps_parent_id(self, work_item_id: str) -> str | None:
        """Resolve a managed parent for either the parent or one committed child."""
        if type(work_item_id) is not str or not work_item_id:
            raise owned_steps.OwnedStepsError("owned_steps_item_invalid")
        return await self._owned_parent_id(work_item_id)

    async def read_owned_steps_raw_identity(
        self,
        parent_id: str,
    ) -> owned_steps.OwnedStepsRawIdentity | None:
        """Read identity columns without decoding steps, control, or metadata."""
        if (
            self._db is None
            or type(parent_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(parent_id) is None
        ):
            if self._db is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_unavailable",
                    parent_id=parent_id if type(parent_id) is str else "",
                )
            raise owned_steps.OwnedStepsError("owned_steps_item_invalid")
        cursor = await self._db.execute(
            "SELECT id,work_type,status,parent_id,assigned_to,created_by,title,"
            "description,metadata,steps,steps_control FROM work_items WHERE id=?",
            (parent_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return owned_steps.OwnedStepsRawIdentity(
            parent_id=row["id"],
            work_type=row["work_type"],
            status=row["status"],
            parent_id_value=row["parent_id"],
            assigned_to=row["assigned_to"],
            created_by=row["created_by"],
            title=row["title"],
            description=row["description"],
            raw_metadata=row["metadata"],
            raw_steps=row["steps"],
            raw_control=row["steps_control"],
        )

    async def _owned_steps_observation_source(
        self,
        parent_id: str,
    ) -> tuple[owned_steps.OwnedStepsRawIdentity, str, str]:
        assert self._db is not None
        identity = await self.read_owned_steps_raw_identity(parent_id)
        if identity is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_parent_missing",
                parent_id=parent_id,
            )
        cursor = await self._db.execute(
            "SELECT * FROM work_items WHERE parent_id=? ORDER BY id",
            (parent_id,),
        )
        child_rows = await cursor.fetchall()
        active_ids: set[str] | None = None
        if identity.raw_control is not None:
            try:
                control = owned_steps.parse_owned_control(identity.raw_control)
            except owned_steps.OwnedStepsError:
                control = None
            if isinstance(control, owned_steps.OwnedStepsControl):
                active_ids = {
                    row.child.child_id
                    for row in control.rows
                    if row.child is not None
                }
            elif isinstance(control, owned_steps.OwnedStepsRepairControl):
                active_ids = set(control.child_ids)
        if active_ids is None:
            if len(child_rows) > owned_steps.MAX_OWNED_ROWS:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_membership_conflict",
                    parent_id=parent_id,
                )
            active_ids = {row["id"] for row in child_rows}
        child_items = {
            row["id"]: self._row_to_work_item(row)
            for row in child_rows
        }
        child_sources = await self._owned_children_sources(
            parent_id,
            child_items,
            {
                child_id: tuple(child.metadata)
                for child_id, child in child_items.items()
            },
        )
        children: list[dict[str, Any]] = []
        child_hasher = hashlib.sha256()
        for row in child_rows:
            child = child_items[row["id"]]
            projection = {
                "id": child.id,
                "snapshot_digest": owned_steps.owned_digest(
                    owned_steps.owned_json_bytes(child.to_dict())
                ),
                "source_digest": child_sources[child.id],
            }
            child_hasher.update(owned_steps.owned_json_bytes(projection))
            if child.id in active_ids:
                children.append(projection)
        if {entry["id"] for entry in children} != active_ids:
            raise owned_steps.OwnedStepsError(
                "owned_steps_membership_conflict",
                parent_id=parent_id,
            )
        cursor = await self._db.execute(
            "SELECT parent_id,incarnation,kind,record_id,payload_digest,step_id,"
            "accepted FROM owned_steps_journal WHERE parent_id=? "
            "ORDER BY incarnation,kind,record_id",
            (parent_id,),
        )
        journal_hasher = hashlib.sha256()
        journal_count = 0
        for row in await cursor.fetchall():
            journal_hasher.update(owned_steps.owned_json_bytes(dict(row)))
            journal_count += 1
        cursor = await self._db.execute(
            "SELECT parent_id,child_id,old_incarnation,successor_incarnation,"
            "proposal_id,apply_operation_id,child_snapshot_digest,"
            "post_cancellation_source_digest FROM owned_steps_retired_children "
            "WHERE parent_id=? ORDER BY child_id",
            (parent_id,),
        )
        retired_hasher = hashlib.sha256()
        retired_count = 0
        for row in await cursor.fetchall():
            retired_hasher.update(owned_steps.owned_json_bytes(dict(row)))
            retired_count += 1
        manifest = owned_steps.owned_json_bytes({
            "version": 1,
            "parent": {
                "id": identity.parent_id,
                "work_type": identity.work_type,
                "status": identity.status,
                "parent_id": identity.parent_id_value,
                "assigned_to": identity.assigned_to,
                "created_by": identity.created_by,
                "title_digest": owned_steps.owned_digest(identity.title),
                "description_digest": owned_steps.owned_digest(identity.description),
                "metadata_digest": (
                    owned_steps.owned_digest(identity.raw_metadata)
                    if identity.raw_metadata is not None
                    else None
                ),
            },
            "steps_digest": (
                owned_steps.owned_digest(identity.raw_steps)
                if identity.raw_steps is not None
                else None
            ),
            "control_digest": (
                owned_steps.owned_digest(identity.raw_control)
                if identity.raw_control is not None
                else None
            ),
            "children": children,
            "all_children": {
                "count": len(child_rows),
                "digest": child_hasher.hexdigest(),
            },
            "journals": {
                "count": journal_count,
                "digest": journal_hasher.hexdigest(),
            },
            "retired_children": {
                "count": retired_count,
                "digest": retired_hasher.hexdigest(),
            },
        }).decode("utf-8")
        return identity, manifest, owned_steps.owned_digest(manifest)

    async def capture_owned_steps_repair_observation(
        self,
        parent_id: str,
        authority: owned_steps.OwnedStepsAuthority,
    ) -> owned_steps.RepairObservation:
        """Retain exact raw projection/control bytes after server authorization."""
        if self._db is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_unavailable",
                parent_id=parent_id,
            )
        grant = await self._authorize_owned_steps(
            authority,
            parent_id=parent_id,
            operation="capture_repair_observation",
        )
        async with self._booking_transaction():
            identity, manifest, source_digest = (
                await self._owned_steps_observation_source(parent_id)
            )
            steps_digest = owned_steps.owned_digest(
                identity.raw_steps if identity.raw_steps is not None else b""
            )
            control_digest = (
                owned_steps.owned_digest(identity.raw_control)
                if identity.raw_control is not None
                else None
            )
            cursor = await self._db.execute(
                "SELECT * FROM owned_steps_observations WHERE parent_id=? "
                "AND actor_id=? AND thread_id=? AND steps_digest=? "
                "AND control_digest IS ? AND source_digest=? ORDER BY created_at LIMIT 1",
                (
                    parent_id,
                    grant.actor_id,
                    grant.thread_id,
                    steps_digest,
                    control_digest,
                    source_digest,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                observation_id = uuid.uuid4().hex
                created_at = time.time()
                await self._db.execute(
                    "INSERT INTO owned_steps_observations("
                    "observation_id,parent_id,actor_id,thread_id,raw_steps,"
                    "raw_control,steps_digest,control_digest,source_manifest,"
                    "source_digest,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        observation_id,
                        parent_id,
                        grant.actor_id,
                        grant.thread_id,
                        identity.raw_steps,
                        identity.raw_control,
                        steps_digest,
                        control_digest,
                        manifest,
                        source_digest,
                        created_at,
                    ),
                )
            else:
                observation_id = row["observation_id"]
                created_at = row["created_at"]
                manifest = row["source_manifest"]
        return owned_steps.RepairObservation(
            observation_id=observation_id,
            parent_id=parent_id,
            actor_id=grant.actor_id,
            thread_id=grant.thread_id,
            raw_steps=identity.raw_steps,
            raw_control=identity.raw_control,
            steps_digest=steps_digest,
            control_digest=control_digest,
            source_manifest=manifest,
            source_digest=source_digest,
            created_at=created_at,
        )

    async def claim_owned_steps_proposal(
        self,
        preparation: owned_steps.ProposalPreparation,
        authority: owned_steps.OwnedStepsAuthority,
    ) -> owned_steps.ProposalClaim:
        """Claim one preparation identity before any planner invocation."""
        preparation = owned_steps.ProposalPreparation.model_validate(preparation)
        if self._db is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_unavailable",
                parent_id=preparation.parent_id,
            )
        grant = await self._authorize_owned_steps(
            authority,
            parent_id=preparation.parent_id,
            operation="claim_proposal",
        )
        async with self._booking_transaction():
            cursor = await self._db.execute(
                "SELECT * FROM owned_steps_observations WHERE observation_id=? "
                "AND parent_id=?",
                (preparation.observation_id, preparation.parent_id),
            )
            if await cursor.fetchone() is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_observation_missing",
                    parent_id=preparation.parent_id,
                )
            cursor = await self._db.execute(
                "SELECT * FROM owned_steps_proposals WHERE parent_id=? "
                "AND preparation_id=?",
                (preparation.parent_id, preparation.preparation_id),
            )
            row = await cursor.fetchone()
            is_new = row is None
            if row is None:
                proposal_id = uuid.uuid4().hex
                claim_nonce = uuid.uuid4().hex
                await self._db.execute(
                    "INSERT INTO owned_steps_proposals("
                    "parent_id,preparation_id,proposal_id,actor_id,thread_id,"
                    "request_digest,observation_id,kind,state,claim_nonce"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        preparation.parent_id,
                        preparation.preparation_id,
                        proposal_id,
                        grant.actor_id,
                        grant.thread_id,
                        preparation.request_digest,
                        preparation.observation_id,
                        preparation.kind,
                        "preparing",
                        claim_nonce,
                    ),
                )
                state = "preparing"
            else:
                if (
                    row["request_digest"] != preparation.request_digest
                    or row["observation_id"] != preparation.observation_id
                    or row["kind"] != preparation.kind
                    or row["actor_id"] != grant.actor_id
                    or row["thread_id"] != grant.thread_id
                ):
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_preparation_conflict",
                        parent_id=preparation.parent_id,
                    )
                proposal_id = row["proposal_id"]
                claim_nonce = row["claim_nonce"]
                state = row["state"]
            manifest_digest = row["manifest_digest"] if row is not None else None
        return owned_steps.ProposalClaim(
            parent_id=preparation.parent_id,
            preparation_id=preparation.preparation_id,
            proposal_id=proposal_id,
            actor_id=grant.actor_id,
            thread_id=grant.thread_id,
            request_digest=preparation.request_digest,
            observation_id=preparation.observation_id,
            kind=preparation.kind,
            state=state,
            claim_nonce=claim_nonce,
            is_new=is_new,
            manifest_digest=manifest_digest,
        )

    async def publish_owned_steps_proposal(
        self,
        claim: owned_steps.ProposalClaim,
        manifest: owned_steps.ProposalManifest,
        authority: owned_steps.OwnedStepsAuthority,
    ) -> owned_steps.ProposalLocator:
        """Publish one immutable bounded manifest for an exact new claim."""
        if self._db is None or type(claim) is not owned_steps.ProposalClaim:
            raise owned_steps.OwnedStepsError(
                "owned_steps_proposal_invalid",
                parent_id=getattr(claim, "parent_id", ""),
            )
        manifest = owned_steps.ProposalManifest.model_validate(manifest)
        if manifest.kind != claim.kind or manifest.observation_id != claim.observation_id:
            raise owned_steps.OwnedStepsError(
                "owned_steps_proposal_conflict",
                parent_id=claim.parent_id,
            )
        await self._authorize_owned_steps(
            authority,
            parent_id=claim.parent_id,
            operation="publish_proposal",
        )
        raw = owned_steps.owned_json_bytes(manifest.model_dump(mode="json")).decode("utf-8")
        digest = owned_steps.owned_digest(raw)
        async with self._booking_transaction():
            cursor = await self._db.execute(
                "SELECT * FROM owned_steps_proposals WHERE parent_id=? "
                "AND preparation_id=?",
                (claim.parent_id, claim.preparation_id),
            )
            row = await cursor.fetchone()
            if (
                row is None
                or row["proposal_id"] != claim.proposal_id
                or row["claim_nonce"] != claim.claim_nonce
                or row["request_digest"] != claim.request_digest
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_proposal_claim_conflict",
                    parent_id=claim.parent_id,
                )
            if row["state"] == "preparing":
                await self._db.execute(
                    "UPDATE owned_steps_proposals SET state='ready',manifest=?,"
                    "manifest_digest=?,error_code=NULL WHERE parent_id=? "
                    "AND preparation_id=?",
                    (raw, digest, claim.parent_id, claim.preparation_id),
                )
            elif (
                row["state"] not in ("ready", "committed")
                or row["manifest"] != raw
                or row["manifest_digest"] != digest
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_proposal_state_conflict",
                    parent_id=claim.parent_id,
                )
        return owned_steps.ProposalLocator(
            parent_id=claim.parent_id,
            proposal_id=claim.proposal_id,
            manifest_digest=digest,
        )

    async def fail_owned_steps_proposal(
        self,
        claim: owned_steps.ProposalClaim,
        error_code: str,
        authority: owned_steps.OwnedStepsAuthority,
    ) -> None:
        if (
            self._db is None
            or type(claim) is not owned_steps.ProposalClaim
            or type(error_code) is not str
            or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", error_code) is None
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_proposal_invalid",
                parent_id=getattr(claim, "parent_id", ""),
            )
        await self._authorize_owned_steps(
            authority,
            parent_id=claim.parent_id,
            operation="publish_proposal",
        )
        async with self._booking_transaction():
            cursor = await self._db.execute(
                "SELECT state,proposal_id,claim_nonce FROM owned_steps_proposals "
                "WHERE parent_id=? AND preparation_id=?",
                (claim.parent_id, claim.preparation_id),
            )
            row = await cursor.fetchone()
            if (
                row is None
                or row["proposal_id"] != claim.proposal_id
                or row["claim_nonce"] != claim.claim_nonce
                or row["state"] != "preparing"
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_proposal_state_conflict",
                    parent_id=claim.parent_id,
                )
            await self._db.execute(
                "UPDATE owned_steps_proposals SET state='failed',error_code=? "
                "WHERE parent_id=? AND preparation_id=?",
                (error_code, claim.parent_id, claim.preparation_id),
            )

    @staticmethod
    def _owned_proposal_acknowledgement(
        raw: str | None,
        *,
        parent_id: str,
        proposal_id: str,
        operation_id: str | None,
        manifest: owned_steps.ProposalManifest,
    ) -> owned_steps.ProposalAcknowledgement:
        try:
            acknowledgement = (
                owned_steps.ProposalAcknowledgement.model_validate_json(raw)
            )
        except (TypeError, ValueError) as exc:
            raise owned_steps.OwnedStepsError(
                "owned_steps_proposal_receipt_conflict",
                parent_id=parent_id,
            ) from exc
        if (
            acknowledgement.parent_id != parent_id
            or acknowledgement.proposal_id != proposal_id
            or acknowledgement.operation_id != operation_id
            or acknowledgement.kind != manifest.kind
            or acknowledgement.steps_digest != manifest.after_digest
            or (
                manifest.kind == "replan_unstarted"
                and (
                    acknowledgement.incarnation != manifest.successor_incarnation
                    or acknowledgement.plan_digest != manifest.successor_plan_digest
                )
            )
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_proposal_receipt_conflict",
                parent_id=parent_id,
            )
        return acknowledgement

    @classmethod
    def _owned_proposal_record(cls, row: Any) -> owned_steps.ProposalRecord:
        if row["manifest"] is not None and (
            owned_steps.owned_digest(row["manifest"]) != row["manifest_digest"]
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_proposal_manifest_conflict",
                parent_id=row["parent_id"],
            )
        try:
            manifest = (
                owned_steps.ProposalManifest.model_validate_json(row["manifest"])
                if row["manifest"] is not None
                else None
            )
        except (TypeError, ValueError) as exc:
            raise owned_steps.OwnedStepsError(
                "owned_steps_proposal_manifest_conflict",
                parent_id=row["parent_id"],
            ) from exc
        if manifest is not None and (
            manifest.kind != row["kind"]
            or manifest.observation_id != row["observation_id"]
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_proposal_manifest_conflict",
                parent_id=row["parent_id"],
            )
        if row["state"] == "committed":
            if manifest is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_proposal_receipt_conflict",
                    parent_id=row["parent_id"],
                )
            cls._owned_proposal_acknowledgement(
                row["acknowledgement"],
                parent_id=row["parent_id"],
                proposal_id=row["proposal_id"],
                operation_id=row["apply_operation_id"],
                manifest=manifest,
            )
        return owned_steps.ProposalRecord(
            claim=owned_steps.ProposalClaim(
                parent_id=row["parent_id"],
                preparation_id=row["preparation_id"],
                proposal_id=row["proposal_id"],
                actor_id=row["actor_id"],
                thread_id=row["thread_id"],
                request_digest=row["request_digest"],
                observation_id=row["observation_id"],
                kind=row["kind"],
                state=row["state"],
                claim_nonce=row["claim_nonce"],
                is_new=False,
                manifest_digest=row["manifest_digest"],
            ),
            manifest=manifest,
            manifest_digest=row["manifest_digest"],
            error_code=row["error_code"],
            apply_operation_id=row["apply_operation_id"],
            acknowledgement=row["acknowledgement"],
        )

    async def get_owned_steps_proposal(
        self,
        locator: owned_steps.ProposalLocator,
        authority: owned_steps.OwnedStepsAuthority,
    ) -> owned_steps.ProposalRecord:
        locator = owned_steps.ProposalLocator.model_validate(locator)
        if self._db is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_unavailable",
                parent_id=locator.parent_id,
            )
        grant = await self._authorize_owned_steps(
            authority,
            parent_id=locator.parent_id,
            operation="inspect_proposal",
        )
        cursor = await self._db.execute(
            "SELECT * FROM owned_steps_proposals WHERE parent_id=? "
            "AND proposal_id=?",
            (locator.parent_id, locator.proposal_id),
        )
        row = await cursor.fetchone()
        if (
            row is None
            or row["actor_id"] != grant.actor_id
            or row["thread_id"] != grant.thread_id
            or (
                row["manifest_digest"] is not None
                and row["manifest_digest"] != locator.manifest_digest
            )
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_proposal_missing",
                parent_id=locator.parent_id,
            )
        return self._owned_proposal_record(row)

    async def _owned_steps_observation_row(
        self,
        observation_id: str,
        parent_id: str,
    ) -> Any:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT * FROM owned_steps_observations WHERE observation_id=? "
            "AND parent_id=?",
            (observation_id, parent_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_observation_missing",
                parent_id=parent_id,
            )
        return row

    async def _assert_owned_steps_observation_current(self, row: Any) -> None:
        _, _, source_digest = await self._owned_steps_observation_source(
            row["parent_id"]
        )
        if source_digest != row["source_digest"]:
            raise owned_steps.OwnedStepsError(
                "owned_steps_proposal_stale",
                parent_id=row["parent_id"],
                actions=("refresh", "inspect_source"),
            )

    async def _replacement_control(
        self,
        parent: WorkItem,
        raw_control: str | None,
        prefix_json: str,
        *,
        actor_id: str,
        thread_id: str,
    ) -> tuple[owned_steps.OwnedStepsControl, str]:
        assert self._db is not None
        spans = owned_steps.owned_row_spans(prefix_json)
        previous: owned_steps.OwnedStepsControl | None = None
        if raw_control is not None:
            try:
                parsed = owned_steps.parse_owned_control(raw_control)
            except owned_steps.OwnedStepsError:
                parsed = None
            if isinstance(parsed, owned_steps.OwnedStepsRepairControl):
                archived = await self._read_owned_journal(
                    parsed.parent_id,
                    parsed.incarnation,
                    "control",
                    parsed.archived_control,
                )
                if archived is None:
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_repair_evidence_conflict",
                        parent_id=parent.id,
                    )
                try:
                    archived_control = owned_steps.parse_owned_control(archived)
                except owned_steps.OwnedStepsError:
                    restored = owned_steps.parse_inline_owned_control(archived)
                    values = restored.model_dump(
                        mode="json",
                        exclude={"operations", "effect_attempts"},
                    )
                    rows: list[dict[str, Any]] = []
                    for archived_row in restored.rows:
                        row_values = archived_row.model_dump(mode="json")
                        for field_name in (
                            "permit",
                            "submission",
                            "reviewed_result",
                        ):
                            evidence = getattr(archived_row, field_name)
                            row_values[field_name] = (
                                owned_steps.owned_digest(
                                    owned_steps.owned_json_bytes(
                                        evidence.model_dump(mode="json")
                                    )
                                )
                                if evidence is not None
                                else None
                            )
                        row_values["review_accepted"] = (
                            archived_row.reviewed_result.accepted
                            if archived_row.reviewed_result is not None
                            else None
                        )
                        rows.append(row_values)
                    values.update(version=2, rows=rows)
                    previous = owned_steps.OwnedStepsControl.model_validate_json(
                        owned_steps.owned_json_bytes(values)
                    )
                else:
                    if not isinstance(
                        archived_control,
                        owned_steps.OwnedStepsControl,
                    ):
                        raise owned_steps.OwnedStepsError(
                            "owned_steps_repair_evidence_conflict",
                            parent_id=parent.id,
                        )
                    previous = archived_control
            elif isinstance(parsed, owned_steps.OwnedStepsControl):
                previous = parsed
            else:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_repair_evidence_conflict",
                    parent_id=parent.id,
                )
        previous_manual = (
            previous.rows[:previous.manual_prefix_length]
            if previous is not None
            else ()
        )
        manual_rows: list[owned_steps.OwnedStepRecord] = []
        for ordinal, (start, end) in enumerate(spans):
            todo_json = prefix_json[start:end]
            retained = (
                previous_manual[ordinal]
                if ordinal < len(previous_manual)
                and previous_manual[ordinal].todo_json == todo_json
                else None
            )
            manual_rows.append(
                retained
                if retained is not None
                else owned_steps.OwnedStepRecord(
                    step_id=uuid.uuid4().hex,
                    kind="manual",
                    todo_json=todo_json,
                    digest=owned_steps.owned_digest(todo_json),
                )
            )
        if previous is not None:
            child_rows = tuple(previous.rows[previous.manual_prefix_length:])
            mode = previous.mode
            suffix = tuple(row.todo_json for row in child_rows)
            projection = (
                prefix_json
                if mode == "awaiting_adoption"
                else owned_steps.append_owned_rows(prefix_json, suffix)
            )
            values = previous.model_dump(mode="json")
            values.update({
                "layout_revision": previous.layout_revision + 1,
                "observation_revision": previous.observation_revision + 1,
                "manual_prefix_length": len(manual_rows),
                "original_steps_json": prefix_json,
                "authorized_steps_json": projection,
                "steps_digest": owned_steps.owned_digest(projection),
                "rows": [
                    row.model_dump(mode="json")
                    for row in (*manual_rows, *child_rows)
                ],
            })
            return (
                owned_steps.OwnedStepsControl.model_validate_json(
                    owned_steps.owned_json_bytes(values)
                ),
                projection,
            )

        cursor = await self._db.execute(
            "SELECT * FROM work_items WHERE parent_id=? ORDER BY id LIMIT ?",
            (parent.id, owned_steps.MAX_OWNED_ROWS + 1),
        )
        child_rows_raw = await cursor.fetchall()
        if not child_rows_raw or len(child_rows_raw) > owned_steps.MAX_OWNED_ROWS:
            raise owned_steps.OwnedStepsError(
                "owned_steps_commitment_conflict",
                parent_id=parent.id,
            )
        child_rows: list[owned_steps.OwnedStepRecord] = []
        commitments: list[owned_steps.OwnedStepChild] = []
        for raw in child_rows_raw:
            child = self._row_to_work_item(raw)
            commitment = owned_steps.OwnedStepChild(
                child_id=child.id,
                spec_id=child.metadata.get("spec_id", child.id),
                commitment_digest=owned_steps.owned_child_commitment(
                    child.to_dict()
                ),
            )
            commitments.append(commitment)
            cursor = await self._db.execute(
                "SELECT * FROM bookings WHERE work_item_id=? AND status NOT IN "
                "('completed','cancelled') ORDER BY id",
                (child.id,),
            )
            bookings = await cursor.fetchall()
            if len(bookings) > 1:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_booking_conflict",
                    parent_id=parent.id,
                )
            initial = self.work_type_registry.get_initial_status(child.work_type)
            untouched = (
                child.status in (initial, "scheduled")
                and child.actual_tokens == 0
                and not child.verification
                and not any(
                    key.startswith(("crew_execution", "crew_verification"))
                    for key in child.metadata
                )
                and not bookings
            )
            todo_json = owned_steps.owned_json_bytes({
                "label": child.title,
                "status": "pending",
                "assigned_to": child.assigned_to,
            }).decode("utf-8")
            child_rows.append(owned_steps.OwnedStepRecord(
                step_id=uuid.uuid4().hex,
                kind="child",
                todo_json=todo_json,
                digest=owned_steps.owned_digest(todo_json),
                child=commitment,
                source_digest=await self._owned_child_source(
                    child,
                    protected_metadata_keys=tuple(child.metadata),
                ),
                plan_metadata_keys=tuple(sorted(child.metadata)),
                assignee_id=child.assigned_to,
                booking_id=bookings[0]["id"] if bookings else None,
                permit_state="unstarted" if untouched else "interrupted",
            ))
        incarnation = uuid.uuid4().hex
        plan_digest = owned_steps.owned_digest(owned_steps.owned_json_bytes(
            [entry.model_dump(mode="json") for entry in commitments]
        ))
        projection = prefix_json
        control = owned_steps.OwnedStepsControl(
            owner_kind="legacy",
            parent_id=parent.id,
            thread_id=thread_id,
            facilitator_id=actor_id if actor_id != "captain" else None,
            incarnation=incarnation,
            plan_digest=plan_digest,
            seed_digest=owned_steps.owned_digest(
                owned_steps.owned_json_bytes({
                    "incarnation": incarnation,
                    "children": [
                        entry.model_dump(mode="json") for entry in commitments
                    ],
                })
            ),
            seed_request_digest=owned_steps.owned_digest(
                owned_steps.owned_json_bytes({
                    "parent_id": parent.id,
                    "steps_digest": owned_steps.owned_digest(
                        parent.steps and owned_steps.owned_json_bytes(parent.steps) or b"[]"
                    ),
                })
            ),
            steps_digest=owned_steps.owned_digest(projection),
            parent_source_digest=await self._owned_parent_digest(parent),
            manual_prefix_length=len(manual_rows),
            original_steps_json=prefix_json,
            authorized_steps_json=projection,
            gate_json=owned_steps.owned_json_bytes({
                key: value
                for key, value in parent.metadata.items()
                if key == "steps_gate_completion"
            }).decode("utf-8"),
            mode="awaiting_adoption",
            rows=tuple((*manual_rows, *child_rows)),
        )
        return control, projection

    async def _owned_replan_booking_ids_locked(
        self,
        parent_id: str,
        control: owned_steps.OwnedStepsControl,
        active_children: tuple[WorkItem, ...],
    ) -> tuple[str, ...]:
        assert self._db is not None
        if (
            control.finalization is not None
            or control.finalization_disposition is not None
            or control.mode not in ("active", "awaiting_adoption")
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_replan_conflict",
                parent_id=parent_id,
            )
        cursor = await self._db.execute(
            "SELECT 1 FROM owned_steps_journal WHERE parent_id=? "
            "AND incarnation=? AND (kind IN ('permit','submission','review','effect') "
            "OR (kind='operation' AND record_id='synthesis-start')) LIMIT 1",
            (parent_id, control.incarnation),
        )
        if await cursor.fetchone() is not None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_replan_started",
                parent_id=parent_id,
            )
        active = {child.id: child for child in active_children}
        booking_ids: list[str] = []
        for row in control.rows[control.manual_prefix_length:]:
            child = active.get(row.child.child_id) if row.child is not None else None
            if (
                child is None
                or row.permit_state != "unstarted"
                or row.permit is not None
                or row.submission is not None
                or row.reviewed_result is not None
                or row.review_accepted is not None
                or child.status
                not in (
                    self.work_type_registry.get_initial_status(child.work_type),
                    "scheduled",
                )
                or child.actual_tokens != 0
                or bool(child.verification)
                or any(
                    key.startswith((
                        "crew_execution",
                        "crew_verification",
                        "crew_convergence",
                        "crew_synthesis",
                        "crew_final",
                    ))
                    for key in child.metadata
                )
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_replan_started",
                    parent_id=parent_id,
                )
            cursor = await self._db.execute(
                "SELECT * FROM bookings WHERE work_item_id=? ORDER BY id",
                (child.id,),
            )
            bookings = await cursor.fetchall()
            live = [
                booking
                for booking in bookings
                if booking["status"] not in ("completed", "cancelled")
            ]
            if row.booking_id is None:
                if live:
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_booking_conflict",
                        parent_id=parent_id,
                    )
                continue
            matching = next(
                (
                    booking
                    for booking in bookings
                    if booking["id"] == row.booking_id
                ),
                None,
            )
            if (
                matching is None
                or matching["status"] != "scheduled"
                or matching["actual_start"] is not None
                or matching["actual_end"] is not None
                or matching["total_tokens_consumed"] != 0
                or any(booking["id"] != row.booking_id for booking in live)
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_booking_conflict",
                    parent_id=parent_id,
                )
            cursor = await self._db.execute(
                "SELECT status FROM booking_timestamps WHERE booking_id=? "
                "ORDER BY timestamp,id",
                (row.booking_id,),
            )
            timestamps = await cursor.fetchall()
            if not timestamps or any(
                timestamp["status"] != "scheduled"
                for timestamp in timestamps
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_replan_started",
                    parent_id=parent_id,
                )
            cursor = await self._db.execute(
                "SELECT 1 FROM booking_journals WHERE booking_id=? LIMIT 1",
                (row.booking_id,),
            )
            if await cursor.fetchone() is not None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_replan_started",
                    parent_id=parent_id,
                )
            booking_ids.append(row.booking_id)
        return tuple(booking_ids)

    async def assert_owned_steps_replan_eligible(
        self,
        parent_id: str,
    ) -> None:
        """Validate an exact managed plan without changing planner or work state."""
        if self._db is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_unavailable",
                parent_id=parent_id,
            )
        async with self._booking_transaction():
            cursor = await self._db.execute(
                "SELECT steps_control FROM work_items WHERE id=?",
                (parent_id,),
            )
            parent_row = await cursor.fetchone()
            if parent_row is None or parent_row["steps_control"] is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_not_managed",
                    parent_id=parent_id,
                )
            parsed = owned_steps.parse_owned_control(
                parent_row["steps_control"]
            )
            if not isinstance(parsed, owned_steps.OwnedStepsControl):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_repair_required",
                    parent_id=parent_id,
                )
            active_ids = {
                row.child.child_id
                for row in parsed.rows
                if row.child is not None
            }
            cursor = await self._db.execute(
                "SELECT * FROM work_items WHERE parent_id=? ORDER BY id",
                (parent_id,),
            )
            active_children = tuple(
                self._row_to_work_item(row)
                for row in await cursor.fetchall()
                if row["id"] in active_ids
            )
            if {child.id for child in active_children} != active_ids:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_membership_conflict",
                    parent_id=parent_id,
                )
            await self._owned_replan_booking_ids_locked(
                parent_id,
                parsed,
                active_children,
            )

    async def _apply_owned_replan(
        self,
        parent: WorkItem,
        parent_row: Any,
        manifest: owned_steps.ProposalManifest,
        proposal_row: Any,
        operation_id: str,
    ) -> tuple[owned_steps.OwnedStepsControl, str]:
        assert self._db is not None
        parsed = owned_steps.parse_owned_control(parent_row["steps_control"])
        if not isinstance(parsed, owned_steps.OwnedStepsControl):
            raise owned_steps.OwnedStepsError(
                "owned_steps_repair_required",
                parent_id=parent.id,
            )
        if (
            manifest.successor_incarnation is None
            or manifest.successor_plan_digest is None
            or manifest.successor_seed_digest is None
            or tuple(manifest.current_child_ids)
            != tuple(
                row.child.child_id
                for row in parsed.rows
                if row.child is not None
            )
            or tuple(manifest.retired_child_ids) != manifest.current_child_ids
            or parsed.finalization is not None
            or parsed.finalization_disposition is not None
            or parsed.mode not in ("active", "awaiting_adoption")
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_replan_conflict",
                parent_id=parent.id,
            )
        membership = await self._get_owned_crew_children_locked(parent.id, parsed)
        observation = await self._owned_steps_observation_row(
            manifest.observation_id,
            parent.id,
        )
        observed_manifest = owned_steps.owned_json_loads(
            observation["source_manifest"]
        )
        observed_children = {
            entry["id"]: entry
            for entry in observed_manifest.get("children", [])
            if type(entry) is dict and type(entry.get("id")) is str
        }
        booking_ids = list(
            await self._owned_replan_booking_ids_locked(
                parent.id,
                parsed,
                membership.active,
            )
        )
        if tuple(booking_ids) != manifest.cancelled_booking_ids:
            raise owned_steps.OwnedStepsError(
                "owned_steps_booking_conflict",
                parent_id=parent.id,
            )
        if len(manifest.proposed_children) == 0 or len(manifest.proposed_children) > owned_steps.MAX_OWNED_ROWS:
            raise owned_steps.OwnedStepsError(
                "owned_steps_replan_conflict",
                parent_id=parent.id,
            )
        now = time.time()
        binding = _OwnedStepsWriteBinding(
            parent.id,
            frozenset(child.id for child in membership.active),
            "replan_unstarted",
        )
        previous_binding = self._owned_steps_write_binding
        self._owned_steps_write_binding = binding
        try:
            for booking_id in booking_ids:
                await self._db.execute(
                    "UPDATE bookings SET status='cancelled',actual_end=? WHERE id=?",
                    (now, booking_id),
                )
                await self._record_timestamp(
                    booking_id,
                    "cancelled",
                    "owned_steps_replan",
                    binding=binding,
                )
        finally:
            self._owned_steps_write_binding = previous_binding
        new_children: list[WorkItem] = []
        new_rows: list[owned_steps.OwnedStepRecord] = []
        for entry in manifest.proposed_children:
            if type(entry) is not dict:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_proposal_manifest_conflict",
                    parent_id=parent.id,
                )
            insert = WorkItemPlanInsert(
                id=entry["id"],
                title=entry["title"],
                description=entry["description"],
                work_type=entry["work_type"],
                priority=entry["priority"],
                depends_on=tuple(entry["depends_on"]),
                assigned_to=entry.get("assigned_to"),
                created_by=entry["created_by"],
                trust_requirement=entry["trust_requirement"],
                required_capabilities=tuple(entry["required_capabilities"]),
                metadata=dict(entry["metadata"]),
            )
            commitment = owned_steps.OwnedStepChild.model_validate(
                entry["commitment"]
            )
            if insert.id != commitment.child_id:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_proposal_manifest_conflict",
                    parent_id=parent.id,
                )
            cursor = await self._db.execute(
                "SELECT 1 FROM work_items WHERE id=?",
                (insert.id,),
            )
            if await cursor.fetchone() is not None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_replan_child_conflict",
                    parent_id=parent.id,
                )
            child = WorkItem(
                id=insert.id,
                title=insert.title,
                description=insert.description,
                work_type=insert.work_type,
                status=self.work_type_registry.get_initial_status(insert.work_type),
                priority=insert.priority,
                parent_id=parent.id,
                depends_on=list(insert.depends_on),
                assigned_to=insert.assigned_to,
                created_by=insert.created_by,
                created_at=now,
                updated_at=now,
                trust_requirement=insert.trust_requirement,
                required_capabilities=list(insert.required_capabilities),
                metadata=dict(insert.metadata),
            )
            await self._db.execute(
                """INSERT INTO work_items (
                    id,title,description,work_type,status,priority,parent_id,
                    depends_on,assigned_to,created_by,created_at,updated_at,
                    due_at,estimated_tokens,actual_tokens,trust_requirement,
                    required_capabilities,tags,metadata,steps,verification,
                    schedule,ttl_seconds,template_id,project_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    child.id,
                    child.title,
                    child.description,
                    child.work_type,
                    child.status,
                    child.priority,
                    child.parent_id,
                    json.dumps(child.depends_on),
                    child.assigned_to,
                    child.created_by,
                    child.created_at,
                    child.updated_at,
                    child.due_at,
                    child.estimated_tokens,
                    child.actual_tokens,
                    child.trust_requirement,
                    json.dumps(child.required_capabilities),
                    json.dumps(child.tags),
                    json.dumps(child.metadata),
                    json.dumps(child.steps),
                    json.dumps(child.verification),
                    json.dumps(child.schedule),
                    child.ttl_seconds,
                    child.template_id,
                    child.project_id,
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
                    id,work_item_id,duration_estimate_seconds,from_date,to_date,
                    required_characteristics,min_trust,department_constraint,
                    priority,resource_preference,fulfilled
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    requirement.id,
                    requirement.work_item_id,
                    requirement.duration_estimate_seconds,
                    requirement.from_date,
                    requirement.to_date,
                    json.dumps(requirement.required_characteristics),
                    requirement.min_trust,
                    requirement.department_constraint,
                    requirement.priority,
                    json.dumps(requirement.resource_preference),
                    0,
                ),
            )
            todo_json = entry["todo_json"]
            owned_steps.owned_row_spans("[" + todo_json + "]")
            new_rows.append(owned_steps.OwnedStepRecord(
                step_id=entry["step_id"],
                kind="child",
                todo_json=todo_json,
                digest=owned_steps.owned_digest(todo_json),
                child=commitment,
                source_digest=await self._owned_child_source(
                    child,
                    protected_metadata_keys=tuple(child.metadata),
                ),
                plan_metadata_keys=tuple(sorted(child.metadata)),
                assignee_id=child.assigned_to,
            ))
            new_children.append(child)
        metadata = dict(parent.metadata)
        if manifest.canonical_metadata_patch is not None:
            metadata.update(manifest.canonical_metadata_patch)
        parent_with_metadata = dataclasses.replace(parent, metadata=metadata)
        manual_rows = parsed.rows[:parsed.manual_prefix_length]
        suffix = tuple(row.todo_json for row in new_rows)
        prefix = parsed.current_manual_prefix_json()
        projection = (
            prefix
            if parsed.mode == "awaiting_adoption"
            else owned_steps.append_owned_rows(prefix, suffix)
        )
        values = parsed.model_dump(mode="json")
        values.update({
            "incarnation": manifest.successor_incarnation,
            "layout_revision": parsed.layout_revision + 1,
            "plan_revision": parsed.plan_revision + 1,
            "observation_revision": parsed.observation_revision + 1,
            "plan_digest": manifest.successor_plan_digest,
            "seed_digest": manifest.successor_seed_digest,
            "seed_request_digest": proposal_row["request_digest"],
            "steps_digest": owned_steps.owned_digest(projection),
            "parent_source_digest": await self._owned_parent_digest(
                parent_with_metadata
            ),
            "authorized_steps_json": projection,
            "rows": [
                row.model_dump(mode="json")
                for row in (*manual_rows, *new_rows)
            ],
            "finalization": None,
            "finalization_disposition": None,
        })
        control = owned_steps.OwnedStepsControl.model_validate_json(
            owned_steps.owned_json_bytes(values)
        )
        if manifest.canonical_metadata_patch is not None:
            await self._db.execute(
                "UPDATE work_items SET metadata=? WHERE id=?",
                (
                    owned_steps.owned_json_bytes(metadata).decode("utf-8"),
                    parent.id,
                ),
            )
        for old in membership.active:
            observed = observed_children.get(old.id)
            if observed is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_retirement_conflict",
                    parent_id=parent.id,
                )
            post_source = await self._owned_child_source(
                old,
                protected_metadata_keys=tuple(old.metadata),
            )
            await self._db.execute(
                "INSERT INTO owned_steps_retired_children("
                "parent_id,child_id,old_incarnation,successor_incarnation,"
                "proposal_id,apply_operation_id,child_snapshot_digest,"
                "post_cancellation_source_digest) VALUES(?,?,?,?,?,?,?,?)",
                (
                    parent.id,
                    old.id,
                    parsed.incarnation,
                    manifest.successor_incarnation,
                    proposal_row["proposal_id"],
                    operation_id,
                    observed["snapshot_digest"],
                    post_source,
                ),
            )
        return control, projection

    async def apply_owned_steps_proposal(
        self,
        approval: owned_steps.OwnedStepsProposalApplyRequest,
        authority: owned_steps.OwnedStepsAuthority,
    ) -> owned_steps.OwnedStepMutationResult:
        """Apply an immutable proposal and its acknowledgement in one transaction."""
        approval = owned_steps.OwnedStepsProposalApplyRequest.model_validate(
            approval
        )
        if self._db is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_unavailable",
                parent_id=approval.reference.parent_id,
            )
        grant = await self._authorize_owned_steps(
            authority,
            parent_id=approval.reference.parent_id,
            operation="apply_proposal",
        )
        if (
            grant.actor_id != approval.reference.actor_id
            or grant.thread_id != approval.reference.thread_id
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_proposal_scope_conflict",
                parent_id=approval.reference.parent_id,
            )
        async with self._booking_transaction():
            cursor = await self._db.execute(
                "SELECT * FROM owned_steps_proposals WHERE parent_id=? "
                "AND proposal_id=?",
                (
                    approval.reference.parent_id,
                    approval.reference.proposal_id,
                ),
            )
            proposal_row = await cursor.fetchone()
            if (
                proposal_row is None
                or proposal_row["manifest_digest"]
                != approval.reference.manifest_digest
                or proposal_row["actor_id"] != grant.actor_id
                or proposal_row["thread_id"] != grant.thread_id
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_proposal_conflict",
                    parent_id=approval.reference.parent_id,
                )
            record = self._owned_proposal_record(proposal_row)
            if proposal_row["state"] == "committed":
                if proposal_row["apply_operation_id"] != approval.operation_id:
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_operation_conflict",
                        parent_id=approval.reference.parent_id,
                    )
                if record.manifest is None:
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_proposal_receipt_conflict",
                        parent_id=approval.reference.parent_id,
                    )
                acknowledgement = self._owned_proposal_acknowledgement(
                    record.acknowledgement,
                    parent_id=record.claim.parent_id,
                    proposal_id=record.claim.proposal_id,
                    operation_id=record.apply_operation_id,
                    manifest=record.manifest,
                )
                return owned_steps.OwnedStepMutationResult(
                    None,
                    "duplicate",
                    proposal_acknowledgement=acknowledgement,
                )
            if proposal_row["state"] != "ready":
                raise owned_steps.OwnedStepsError(
                    "owned_steps_proposal_unconfirmed",
                    parent_id=approval.reference.parent_id,
                )
            manifest = record.manifest
            if manifest is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_proposal_manifest_conflict",
                    parent_id=approval.reference.parent_id,
                )
            observation = await self._owned_steps_observation_row(
                proposal_row["observation_id"],
                approval.reference.parent_id,
            )
            await self._assert_owned_steps_observation_current(observation)
            cursor = await self._db.execute(
                "SELECT * FROM work_items WHERE id=?",
                (approval.reference.parent_id,),
            )
            parent_row = await cursor.fetchone()
            if parent_row is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_parent_missing",
                    parent_id=approval.reference.parent_id,
                )
            detached_parent = dict(parent_row)
            detached_parent["steps"] = "[]"
            parent = self._row_to_work_item(detached_parent)
            if manifest.kind == "adopt_existing":
                control = owned_steps.parse_owned_control(
                    parent_row["steps_control"]
                )
                if (
                    not isinstance(control, owned_steps.OwnedStepsControl)
                    or control.mode != "awaiting_adoption"
                ):
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_adoption_not_pending",
                        parent_id=parent.id,
                    )
                projection = owned_steps.append_owned_rows(
                    control.current_manual_prefix_json(),
                    tuple(
                        row.todo_json
                        for row in control.rows[
                            control.manual_prefix_length:
                        ]
                    ),
                )
                values = control.model_dump(mode="json")
                values.update({
                    "mode": "active",
                    "layout_revision": control.layout_revision + 1,
                    "observation_revision": control.observation_revision + 1,
                    "authorized_steps_json": projection,
                    "steps_digest": owned_steps.owned_digest(projection),
                })
                next_control = owned_steps.OwnedStepsControl.model_validate_json(
                    owned_steps.owned_json_bytes(values)
                )
            elif manifest.kind == "replace_manual_prefix":
                next_control, projection = await self._replacement_control(
                    parent,
                    parent_row["steps_control"],
                    manifest.after_prefix_json,
                    actor_id=grant.actor_id,
                    thread_id=grant.thread_id,
                )
            else:
                next_control, projection = await self._apply_owned_replan(
                    parent,
                    parent_row,
                    manifest,
                    proposal_row,
                    approval.operation_id,
                )
            if owned_steps.owned_digest(projection) != manifest.after_digest:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_proposal_manifest_conflict",
                    parent_id=parent.id,
                )
            committed_at = time.time()
            await self._db.execute(
                "UPDATE work_items SET steps=?,steps_control=?,updated_at=? "
                "WHERE id=?",
                (
                    projection,
                    next_control.model_dump_json(),
                    committed_at,
                    parent.id,
                ),
            )
            acknowledgement = owned_steps.ProposalAcknowledgement(
                parent_id=parent.id,
                proposal_id=proposal_row["proposal_id"],
                operation_id=approval.operation_id,
                kind=manifest.kind,
                committed_at=committed_at,
                incarnation=next_control.incarnation,
                plan_digest=next_control.plan_digest,
                steps_digest=next_control.steps_digest,
            )
            await self._db.execute(
                "UPDATE owned_steps_proposals SET state='committed',"
                "apply_operation_id=?,acknowledgement=? WHERE parent_id=? "
                "AND proposal_id=? AND state='ready'",
                (
                    approval.operation_id,
                    owned_steps.owned_json_bytes(
                        acknowledgement.model_dump(mode="json")
                    ).decode("utf-8"),
                    parent.id,
                    proposal_row["proposal_id"],
                ),
            )
            if manifest.kind == "replan_unstarted":
                await self._get_owned_crew_children_locked(
                    parent.id,
                    next_control,
                )
        await self._refresh_snapshot_cache()
        snapshot = await self.get_owned_steps(parent.id)
        return owned_steps.OwnedStepMutationResult(
            snapshot,
            "applied",
            proposal_acknowledgement=acknowledgement,
        )

    async def _guard_owned_write(
        self, work_item_id: str, *, metadata: dict[str, Any] | None = None,
        replacement: bool = False,
        binding: _OwnedStepsWriteBinding | None = None,
    ) -> None:
        parent_id = await self._owned_parent_id(work_item_id)
        if parent_id is None:
            return
        if (
            binding is not None and binding is self._owned_steps_write_binding
            and binding.parent_id == parent_id
            and work_item_id in binding.child_ids
        ):
            return
        if metadata is not None:
            current = await self.get_work_item(work_item_id)
            assert current is not None
            assert self._db is not None
            cursor = await self._db.execute("SELECT steps_control FROM work_items WHERE id = ?", (parent_id,))
            control = owned_steps.parse_owned_control((await cursor.fetchone())["steps_control"])
            if isinstance(control, owned_steps.OwnedStepsRepairControl):
                raise owned_steps.OwnedStepsError("owned_steps_repair_required", parent_id=parent_id)
            bound = next((row for row in control.rows if row.child and row.child.child_id == work_item_id), None)
            if work_item_id != parent_id and bound is None:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_retired_write_reserved",
                    parent_id=parent_id,
                    actions=("owned_controls", "inspect_source"),
                )
            plan_keys = set(bound.plan_metadata_keys) if bound else set()
            # Canonical recovery hashes every non-runtime child metadata key as
            # spec_metadata. Such keys are plan data, not incidental siblings.
            if bound is not None and control.owner_kind == "canonical":
                plan_keys.update(current.metadata.keys() | metadata.keys())
            protected = {
                key for key in (current.metadata.keys() | metadata.keys())
                if owned_steps.owned_metadata_key(key) or key in plan_keys
            }
            if replacement:
                allowed = all(
                    key in current.metadata and key in metadata
                    and _json_values_exactly_equal(current.metadata[key], metadata[key])
                    for key in protected
                )
            else:
                allowed = not protected.intersection(metadata)
            if allowed:
                return
        raise owned_steps.OwnedStepsError(
            "owned_steps_write_reserved", parent_id=parent_id,
            actions=("owned_controls", "inspect_source"),
        )

    async def _guard_owned_booking(
        self, booking_id: str, binding: _OwnedStepsWriteBinding | None = None,
    ) -> None:
        booking = await self.get_booking(booking_id)
        if booking is not None:
            await self._guard_owned_write(booking.work_item_id, binding=binding)

    async def _authorize_owned_steps(
        self, authority: owned_steps.OwnedStepsAuthority, *, parent_id: str,
        operation: str,
        token: (
            owned_steps.StepViewToken | owned_steps.OwnedStepsPlanToken
            | owned_steps.OwnedStepExecutionPermit | None
        ) = None,
    ) -> owned_steps.OwnedStepsGrant:
        if type(authority) is not owned_steps.OwnedStepsAuthority:
            raise owned_steps.OwnedStepsError("owned_steps_authority_required", parent_id=parent_id)
        context = authority.context
        if type(context) is _OwnedExecutionScope:
            self._require_execution_port(context.port)
            if (
                context not in self._owned_execution_scopes or context.plan.parent_id != parent_id
                or context.plan.owner_kind != "legacy"
            ):
                raise owned_steps.OwnedStepsError("owned_steps_execution_scope_denied", parent_id=parent_id)
            if operation == "seed" and not context.rows and context.plan.facilitator_id is None and token is None:
                return owned_steps.OwnedStepsGrant(parent_id, parent_id, context.plan.thread_id, "executor")
            if operation not in ("admit_execution", "submit_execution", "execution_active", "record_unstarted_execution") or not isinstance(
                token, (owned_steps.StepViewToken, owned_steps.OwnedStepExecutionPermit),
            ):
                raise owned_steps.OwnedStepsError("owned_steps_execution_scope_denied", parent_id=parent_id)
            row = next((row for row in context.rows if row.step_id == token.step_id and row.child), None)
            if (
                row is None or token.incarnation != context.plan.incarnation
                or token.plan_digest != context.plan.plan_digest
                or token.assignment_epoch != row.assignment_epoch
                or (isinstance(token, owned_steps.StepViewToken) and (
                    token.thread_id != context.plan.thread_id
                    or token.actor_id != (row.assignee_id or parent_id)
                ))
                or (isinstance(token, owned_steps.OwnedStepExecutionPermit) and (
                    token.child_id != row.child.child_id or token.assignee_id != row.assignee_id
                    or (row.permit is None and token.source_digest != row.source_digest)
                    or (row.permit is not None and row.permit != owned_steps.owned_digest(
                        owned_steps.owned_json_bytes(token.model_dump(mode="json")),
                    ))
                ))
            ):
                raise owned_steps.OwnedStepsError("owned_steps_execution_scope_denied", parent_id=parent_id)
            return owned_steps.OwnedStepsGrant(parent_id, row.assignee_id or parent_id, context.plan.thread_id, "executor")
        if self._owned_steps_authorizer is None:
            raise owned_steps.OwnedStepsError("owned_steps_authority_required", parent_id=parent_id)
        grant = await self._owned_steps_authorizer.authorize_owned_steps(
            authority, parent_id=parent_id, operation=operation, token=token,
        )
        if (
            type(grant) is not owned_steps.OwnedStepsGrant or grant.parent_id != parent_id
            or grant.role not in ("captain", "facilitator", "executor", "verifier", "ttl", "owner")
            or any(
                type(value) is not str or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(value) is None
                for value in (grant.actor_id,)
            )
            or type(grant.thread_id) is not str
            or (grant.thread_id != "" and _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(grant.thread_id) is None)
            or (isinstance(token, (owned_steps.StepViewToken, owned_steps.OwnedStepsPlanToken)) and (
                token.actor_id != grant.actor_id or token.thread_id != grant.thread_id
            ))
            or (isinstance(token, owned_steps.OwnedStepExecutionPermit)
                and not (
                    grant.role == "verifier"
                    and (
                        operation in {
                            "record_review",
                            "admit_correction",
                        }
                        or (
                            operation in {
                                "record_correction",
                                "execution_active",
                            }
                            and token.review_attempt_id is not None
                        )
                    )
                )
                and token.assignee_id != grant.actor_id)
        ):
            raise owned_steps.OwnedStepsError("owned_steps_authority_denied", parent_id=parent_id)
        return grant

    async def _owned_parent_digest(self, parent: WorkItem) -> str:
        return await self._owned_child_source(parent, exclude_steps=True)

    async def _owned_child_source(
        self, child: WorkItem, *, exclude_steps: bool = False,
        protected_metadata_keys: tuple[str, ...] = (),
    ) -> str:
        assert self._db is not None
        projection = owned_steps.owned_source_projection(
            child.to_dict(), protected_metadata_keys=protected_metadata_keys,
        )
        if exclude_steps:
            projection.pop("steps")
        evidence: dict[str, Any] = {
            "child": projection,
        }
        for table in ("bookings", "resource_requirements"):
            cursor = await self._db.execute(
                f"SELECT * FROM {table} WHERE work_item_id = ? ORDER BY id", (child.id,),
            )
            evidence[table] = [dict(row) for row in await cursor.fetchall()]
        for table in ("booking_timestamps", "booking_journals"):
            cursor = await self._db.execute(
                f"SELECT detail.* FROM {table} AS detail JOIN bookings AS booking "
                "ON detail.booking_id = booking.id WHERE booking.work_item_id = ? "
                "ORDER BY detail.id", (child.id,),
            )
            evidence[table] = [dict(row) for row in await cursor.fetchall()]
        return owned_steps.owned_digest(owned_steps.owned_json_bytes(evidence))

    async def _owned_children_sources(
        self,
        parent_id: str,
        children: dict[str, WorkItem],
        protected_metadata_keys: dict[str, tuple[str, ...]],
    ) -> dict[str, str]:
        assert self._db is not None
        if not children:
            return {}
        evidence = {
            child_id: {
                "child": owned_steps.owned_source_projection(
                    child.to_dict(),
                    protected_metadata_keys=protected_metadata_keys[child_id],
                ),
                "bookings": [],
                "resource_requirements": [],
                "booking_timestamps": [],
                "booking_journals": [],
            }
            for child_id, child in children.items()
        }
        for table in ("bookings", "resource_requirements"):
            cursor = await self._db.execute(
                f"SELECT detail.* FROM {table} AS detail "
                "JOIN work_items AS item ON detail.work_item_id=item.id "
                "WHERE item.parent_id=? ORDER BY detail.work_item_id,detail.id",
                (parent_id,),
            )
            for row in await cursor.fetchall():
                child_id = row["work_item_id"]
                if child_id in evidence:
                    evidence[child_id][table].append(dict(row))
        for table in ("booking_timestamps", "booking_journals"):
            cursor = await self._db.execute(
                f"SELECT detail.*,booking.work_item_id AS owned_work_item_id "
                f"FROM {table} AS detail JOIN bookings AS booking "
                "ON detail.booking_id=booking.id JOIN work_items AS item "
                "ON booking.work_item_id=item.id WHERE item.parent_id=? "
                "ORDER BY booking.work_item_id,detail.id",
                (parent_id,),
            )
            for row in await cursor.fetchall():
                values = dict(row)
                child_id = values.pop("owned_work_item_id")
                if child_id in evidence:
                    evidence[child_id][table].append(values)
        return {
            child_id: owned_steps.owned_digest(
                owned_steps.owned_json_bytes(values)
            )
            for child_id, values in evidence.items()
        }

    async def _load_owned_steps(
        self, parent_id: str, *, allow_projection_mismatch: bool = False,
        step_id: str | None = None,
    ) -> tuple[owned_steps.OwnedStepsSnapshot, WorkItem, dict[str, WorkItem]]:
        assert self._db is not None
        cursor = await self._db.execute("SELECT * FROM work_items WHERE id = ?", (parent_id,))
        raw_parent = await cursor.fetchone()
        if raw_parent is None or raw_parent["steps_control"] is None:
            raise owned_steps.OwnedStepsError("owned_steps_not_managed", parent_id=parent_id)
        control = owned_steps.parse_owned_control(raw_parent["steps_control"])
        if control.parent_id != parent_id:
            raise owned_steps.OwnedStepsError("owned_steps_parent_conflict", parent_id=parent_id)
        if isinstance(control, owned_steps.OwnedStepsRepairControl):
            raw_steps = raw_parent["steps"]
            raise owned_steps.OwnedStepsError(
                "owned_steps_repair_required", parent_id=parent_id,
                actions=("inspect_source", "replace_manual_prefix", "replan_unstarted"),
                repair_evidence=owned_steps.OwnedStepsRepairEvidence(
                    parent_id, raw_steps, owned_steps.owned_digest(raw_steps),
                ),
            )
        # Repair may inspect malformed projection bytes, but it may not adopt
        # them as a baseline or change any other source evidence.
        detached = dict(raw_parent)
        detached["steps"] = control.authorized_steps_json
        parent = self._row_to_work_item(detached)
        if await self._owned_parent_digest(parent) != control.parent_source_digest:
            raise owned_steps.OwnedStepsError("owned_steps_source_conflict", parent_id=parent_id)
        matches = raw_parent["steps"] == control.authorized_steps_json
        if not matches and not allow_projection_mismatch:
            raise owned_steps.OwnedStepsError(
                "owned_steps_projection_conflict", parent_id=parent_id,
                actions=("repair_projection", "inspect_source"),
            )
        relevant_rows = tuple(row for row in control.rows if step_id is None or row.step_id == step_id)
        bound_ids = frozenset(row.child.child_id for row in relevant_rows if row.child is not None)
        membership = await self._get_owned_crew_children_locked(
            parent_id, control, needed_ids=bound_ids if step_id is not None else None,
        )
        if {child.id for child in membership.active} != bound_ids:
            raise owned_steps.OwnedStepsError(
                "owned_steps_membership_conflict",
                parent_id=parent_id,
            )
        children = {child.id: child for child in membership.active}
        protected_metadata_keys = {
            child.id: (
                tuple(child.metadata)
                if control.owner_kind == "canonical"
                else next(
                    row.plan_metadata_keys
                    for row in relevant_rows
                    if row.child is not None
                    and row.child.child_id == child.id
                )
            )
            for child in children.values()
        }
        if step_id is not None and len(children) == 1:
            child = next(iter(children.values()))
            sources = {child.id: await self._owned_child_source(
                child, protected_metadata_keys=protected_metadata_keys[child.id],
            )}
        else:
            sources = await self._owned_children_sources(
                parent_id,
                children,
                protected_metadata_keys,
            )
        for row in relevant_rows:
            if row.child is not None:
                if sources[row.child.child_id] != row.source_digest:
                    raise owned_steps.OwnedStepsError("owned_steps_source_conflict", parent_id=parent_id)
        await self._check_owned_evidence_references(control, relevant_rows)
        return self._owned_snapshot(
            control, matches, raw_control=raw_parent["steps_control"],
        ), parent, children

    async def _get_owned_crew_children_locked(
        self,
        parent_id: str,
        control: owned_steps.OwnedStepsControl,
        *,
        needed_ids: frozenset[str] | None = None,
    ) -> owned_steps.OwnedCrewChildren:
        assert self._db is not None
        active_ids = tuple(
            row.child.child_id
            for row in control.rows
            if row.child is not None
        )
        active_id_set = set(active_ids)
        if len(active_ids) > owned_steps.MAX_OWNED_ROWS or len(active_id_set) != len(active_ids):
            raise owned_steps.OwnedStepsError(
                "owned_steps_membership_conflict",
                parent_id=parent_id,
            )
        cursor = await self._db.execute(
            "SELECT * FROM work_items WHERE parent_id=? ORDER BY id",
            (parent_id,),
        )
        direct: dict[str, WorkItem] = {}
        direct_ids: set[str] = set()
        for row in await cursor.fetchall():
            child_id = row["id"]
            direct_ids.add(child_id)
            if needed_ids is None or child_id in needed_ids or child_id not in active_id_set:
                direct[child_id] = self._row_to_work_item(row)
            else:
                # Full fresh membership and JSON validation remain mandatory.
                # Only unused active WorkItem objects are omitted; any possible
                # retired/extra child is still materialized before proving it.
                self._validate_unmaterialized_work_item(row)
        cursor = await self._db.execute(
            "SELECT retired.*,proposal.state AS proposal_state,"
            "proposal.manifest AS proposal_manifest,"
            "proposal.manifest_digest AS proposal_manifest_digest,"
            "proposal.apply_operation_id AS proposal_operation_id,"
            "proposal.acknowledgement AS proposal_acknowledgement,"
            "observation.source_manifest AS observation_manifest,"
            "observation.source_digest AS observation_source_digest,"
            "observation.raw_control AS observation_control,"
            "observation.control_digest AS observation_control_digest "
            "FROM owned_steps_retired_children AS retired "
            "JOIN owned_steps_proposals AS proposal "
            "ON proposal.proposal_id=retired.proposal_id "
            "AND proposal.parent_id=retired.parent_id "
            "JOIN owned_steps_observations AS observation "
            "ON observation.observation_id=proposal.observation_id "
            "WHERE retired.parent_id=? ORDER BY retired.child_id",
            (parent_id,),
        )
        retired_rows = await cursor.fetchall()
        retired_ids = {row["child_id"] for row in retired_rows}
        lineage = {
            row["old_incarnation"]: row["successor_incarnation"]
            for row in retired_rows
            if row["old_incarnation"] is not None
        }
        if (
            active_id_set & retired_ids
            or direct_ids != active_id_set | retired_ids
        ):
            raise owned_steps.OwnedStepsError(
                "owned_steps_membership_conflict",
                parent_id=parent_id,
            )
        retired_children = {
            child_id: direct[child_id]
            for child_id in retired_ids
            if child_id in direct
        }
        retired_sources = await self._owned_children_sources(
            parent_id,
            retired_children,
            {
                child_id: tuple(child.metadata)
                for child_id, child in retired_children.items()
            },
        )
        proposal_sources: dict[
            str,
            tuple[
                owned_steps.ProposalManifest,
                owned_steps.ProposalAcknowledgement,
                str,
                dict[str, dict[str, Any]],
            ],
        ] = {}
        retired: list[owned_steps.RetiredOwnedChild] = []
        for row in retired_rows:
            child = direct.get(row["child_id"])
            successor = row["successor_incarnation"]
            visited: set[str] = set()
            while successor != control.incarnation and successor not in visited:
                visited.add(successor)
                successor = lineage.get(successor, "")
            if (
                child is None
                or row["proposal_state"] != "committed"
                or successor != control.incarnation
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_retirement_conflict",
                    parent_id=parent_id,
                )
            proposal_source = proposal_sources.get(row["proposal_id"])
            if proposal_source is None:
                try:
                    if (
                        owned_steps.owned_digest(row["proposal_manifest"])
                        != row["proposal_manifest_digest"]
                        or owned_steps.owned_digest(row["observation_manifest"])
                        != row["observation_source_digest"]
                        or owned_steps.owned_digest(row["observation_control"])
                        != row["observation_control_digest"]
                    ):
                        raise ValueError("owned_steps_retirement_digest_conflict")
                    proposal_manifest = (
                        owned_steps.ProposalManifest.model_validate_json(
                            row["proposal_manifest"]
                        )
                    )
                    observation_manifest = owned_steps.owned_json_loads(
                        row["observation_manifest"]
                    )
                    acknowledgement = self._owned_proposal_acknowledgement(
                        row["proposal_acknowledgement"],
                        parent_id=parent_id,
                        proposal_id=row["proposal_id"],
                        operation_id=row["proposal_operation_id"],
                        manifest=proposal_manifest,
                    )
                    previous_control = owned_steps.parse_owned_control(
                        row["observation_control"]
                    )
                    if (
                        not isinstance(previous_control, owned_steps.OwnedStepsControl)
                        or previous_control.parent_id != parent_id
                        or observation_manifest.get("control_digest")
                        != row["observation_control_digest"]
                    ):
                        raise ValueError("owned_steps_retirement_source_conflict")
                except Exception as exc:
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_retirement_conflict",
                        parent_id=parent_id,
                    ) from exc
                originals = {
                    entry["id"]: entry
                    for entry in observation_manifest.get("children", [])
                    if type(entry) is dict and type(entry.get("id")) is str
                }
                proposal_source = (
                    proposal_manifest,
                    acknowledgement,
                    previous_control.incarnation,
                    originals,
                )
                proposal_sources[row["proposal_id"]] = proposal_source
            proposal_manifest, acknowledgement, old_incarnation, originals = proposal_source
            original = originals.get(child.id)
            if (
                proposal_manifest.kind != "replan_unstarted"
                or row["apply_operation_id"] != acknowledgement.operation_id
                or row["successor_incarnation"] != acknowledgement.incarnation
                or row["old_incarnation"] != old_incarnation
                or child.id not in proposal_manifest.retired_child_ids
                or original is None
                or original.get("snapshot_digest") != row["child_snapshot_digest"]
                or retired_sources.get(child.id)
                != row["post_cancellation_source_digest"]
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_retirement_conflict",
                    parent_id=parent_id,
                )
            retired.append(owned_steps.RetiredOwnedChild(
                child=child,
                old_incarnation=row["old_incarnation"],
                successor_incarnation=row["successor_incarnation"],
                proposal_id=row["proposal_id"],
                apply_operation_id=row["apply_operation_id"],
                child_snapshot_digest=row["child_snapshot_digest"],
                post_cancellation_source_digest=row["post_cancellation_source_digest"],
            ))
        active = tuple(
            direct[child_id] for child_id in active_ids
            if needed_ids is None or child_id in needed_ids
        )
        return owned_steps.OwnedCrewChildren(
            parent_id=parent_id,
            incarnation=control.incarnation,
            plan_digest=control.plan_digest,
            active=active,
            retired=tuple(retired),
        )

    async def get_owned_crew_children(
        self,
        parent_id: str,
        expected_plan: owned_steps.OwnedStepsSeedPlan | str | None = None,
    ) -> owned_steps.OwnedCrewChildren:
        """Prove every direct child is current-active or receipt-retired."""
        if self._db is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_unavailable",
                parent_id=parent_id,
            )
        cursor = await self._db.execute(
            "SELECT steps_control FROM work_items WHERE id=?",
            (parent_id,),
        )
        row = await cursor.fetchone()
        if row is None or row["steps_control"] is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_not_managed",
                parent_id=parent_id,
            )
        control = owned_steps.parse_owned_control(row["steps_control"])
        if isinstance(control, owned_steps.OwnedStepsRepairControl):
            raise owned_steps.OwnedStepsError(
                "owned_steps_repair_required",
                parent_id=parent_id,
            )
        if expected_plan is not None:
            expected_digest = (
                expected_plan.plan_digest
                if isinstance(expected_plan, owned_steps.OwnedStepsSeedPlan)
                else expected_plan
            )
            expected_ids = (
                tuple(child.child_id for child in expected_plan.children)
                if isinstance(expected_plan, owned_steps.OwnedStepsSeedPlan)
                else None
            )
            actual_ids = tuple(
                entry.child.child_id
                for entry in control.rows
                if entry.child is not None
            )
            if (
                type(expected_digest) is not str
                or expected_digest != control.plan_digest
                or (expected_ids is not None and expected_ids != actual_ids)
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_plan_conflict",
                    parent_id=parent_id,
                )
        return await self._get_owned_crew_children_locked(parent_id, control)

    async def _check_owned_evidence_references(
        self, control: owned_steps.OwnedStepsControl, rows: tuple[owned_steps.OwnedStepRecord, ...],
    ) -> None:
        assert self._db is not None
        refs = [
            (kind, digest, row.step_id, row.review_accepted if kind == "review" else None)
            for row in rows
            for kind, digest in (("permit", row.permit), ("submission", row.submission), ("review", row.reviewed_result))
            if digest is not None
        ]
        if not refs:
            return
        # CROSS JOIN fixes the tiny reference set as the outer loop. An ordinary
        # JOIN lets SQLite scan a parent's entire growing journal before filtering.
        cursor = await self._db.execute(
            "SELECT journal.kind,journal.record_id,journal.payload_digest,journal.step_id,journal.accepted "
            "FROM json_each(?) AS wanted CROSS JOIN owned_steps_journal AS journal "
            "WHERE journal.parent_id = ? AND journal.incarnation = ? "
            "AND journal.kind = json_extract(wanted.value,'$[0]') "
            "AND journal.record_id = json_extract(wanted.value,'$[1]')",
            (json.dumps([[kind, digest] for kind, digest, _, _ in refs]), control.parent_id, control.incarnation),
        )
        actual = {(entry["kind"], entry["record_id"]): entry for entry in await cursor.fetchall()}
        for kind, digest, step_id, accepted in refs:
            stored = actual.get((kind, digest))
            if (
                stored is None or stored["payload_digest"] != digest
                or stored["step_id"] != step_id or stored["accepted"] != accepted
            ):
                raise owned_steps.OwnedStepsError("owned_steps_evidence_conflict", parent_id=control.parent_id)

    @staticmethod
    def _owned_snapshot(
        control: owned_steps.OwnedStepsControl, projection_matches: bool = True,
        *, raw_control: str | None = None,
    ) -> owned_steps.OwnedStepsSnapshot:
        source_digest = owned_steps.owned_snapshot_source_digest(
            raw_control if raw_control is not None else control,
        )
        return owned_steps.OwnedStepsSnapshot(control, source_digest, projection_matches)

    async def get_owned_steps(self, parent_id: str) -> owned_steps.OwnedStepsSnapshot | None:
        """Resolve a parent or committed child without extending WorkItem's wire."""
        if type(parent_id) is not str or not parent_id:
            raise owned_steps.OwnedStepsError("owned_steps_parent_invalid")
        if self._db is None:
            return None
        owner_id = await self._owned_parent_id(parent_id)
        if owner_id is None:
            return None
        cursor = await self._db.execute(
            "SELECT steps_control FROM work_items WHERE id = ?",
            (owner_id,),
        )
        stored = await cursor.fetchone()
        if stored is None or stored["steps_control"] is None:
            return None
        async with self._booking_transaction():
            snapshot, _, _ = await self._load_owned_steps(owner_id, allow_projection_mismatch=True)
            return snapshot

    async def _seed_owned_steps(
        self, parent: WorkItem, children: tuple[WorkItem, ...],
        seed: owned_steps.OwnedStepsSeed, request_digest: str,
    ) -> None:
        assert self._db is not None
        if type(seed) is not owned_steps.OwnedStepsSeed:
            raise owned_steps.OwnedStepsError("owned_steps_seed_invalid")
        plan = owned_steps.OwnedStepsSeedPlan.model_validate(seed.plan)
        grant = await self._authorize_owned_steps(
            seed.authority, parent_id=parent.id, operation="seed",
        )
        execution_seed = (
            type(seed.authority.context) is _OwnedExecutionScope
            and seed.authority.context in self._owned_execution_scopes
            and seed.authority.context.plan == plan and not seed.authority.context.rows
            and plan.owner_kind == "legacy" and plan.facilitator_id is None
        )
        canonical_seed = (
            plan.owner_kind == "canonical" and grant.role == "owner"
            and grant.actor_id == plan.facilitator_id
        )
        if (
            (grant.role not in ("captain", "facilitator") and not execution_seed and not canonical_seed)
            or grant.thread_id != plan.thread_id or plan.parent_id != parent.id
            or (grant.role == "facilitator" and grant.actor_id != plan.facilitator_id)
            or ((parent.work_type == "crew_session") != (plan.owner_kind == "canonical"))
            or len({child.child_id for child in plan.children}) != len(plan.children)
        ):
            raise owned_steps.OwnedStepsError("owned_steps_seed_invalid", parent_id=parent.id)
        cursor = await self._db.execute(
            "SELECT steps, steps_control FROM work_items WHERE id = ?", (parent.id,),
        )
        raw = await cursor.fetchone()
        if raw["steps_control"] is not None:
            raise owned_steps.OwnedStepsError("owned_steps_already_managed", parent_id=parent.id)
        prefix = raw["steps"]
        try:
            spans = owned_steps.owned_row_spans(prefix)
        except owned_steps.OwnedStepsError as exc:
            raise owned_steps.OwnedStepsError(
                "owned_steps_repair_required", parent_id=parent.id,
                actions=("inspect_source", "replace_manual_prefix", "replan_unstarted"),
                repair_evidence=owned_steps.OwnedStepsRepairEvidence(parent.id, prefix, owned_steps.owned_digest(prefix)),
            ) from exc
        if owned_steps.owned_digest(prefix) != plan.expected_steps_digest:
            raise owned_steps.OwnedStepsError("owned_steps_seed_conflict", parent_id=parent.id)
        by_id = {child.id: child for child in children}
        if set(by_id) != {child.child_id for child in plan.children}:
            raise owned_steps.OwnedStepsError("owned_steps_membership_conflict", parent_id=parent.id)
        if len(spans) + len(children) > owned_steps.MAX_OWNED_ROWS:
            raise owned_steps.OwnedStepsError("owned_steps_rows_invalid", parent_id=parent.id)
        if plan.owner_kind == "canonical":
            session = parent.metadata.get("crew_session")
            recovery = parent.metadata.get("crew_recovery")
            committed = recovery.get("plan") if type(recovery) is dict else None
            if (
                type(session) is not dict or session.get("thread_id") != plan.thread_id
                or session.get("facilitator_id") != plan.facilitator_id
                or parent.assigned_to != plan.facilitator_id
                or type(committed) is not dict or committed.get("plan_hash") != plan.plan_digest
                or committed.get("children") != [
                    {"child_id": child.child_id, "spec_id": child.spec_id,
                     "row_hash": child.commitment_digest}
                    for child in plan.children
                ]
            ):
                raise owned_steps.OwnedStepsError("owned_steps_commitment_conflict", parent_id=parent.id)
        else:
            if plan.plan_digest != owned_steps.owned_digest(owned_steps.owned_json_bytes(
                [child.model_dump(mode="json") for child in plan.children],
            )):
                raise owned_steps.OwnedStepsError("owned_steps_commitment_conflict", parent_id=parent.id)
        records: list[owned_steps.OwnedStepRecord] = []
        for start, end in spans:
            todo_json = prefix[start:end]
            records.append(owned_steps.OwnedStepRecord(
                step_id=uuid.uuid4().hex, kind="manual", todo_json=todo_json,
                digest=owned_steps.owned_digest(todo_json),
            ))
        historical = False
        for commitment in plan.children:
            child = by_id[commitment.child_id]
            await self._guard_owned_write(child.id)
            if (
                child.parent_id != parent.id
                or child.metadata.get("spec_id", child.id) != commitment.spec_id
                or (plan.owner_kind == "legacy"
                    and owned_steps.owned_child_commitment(child.to_dict()) != commitment.commitment_digest)
            ):
                raise owned_steps.OwnedStepsError("owned_steps_commitment_conflict", parent_id=parent.id)
            cursor = await self._db.execute(
                "SELECT * FROM bookings WHERE work_item_id = ? AND resource_id = ? "
                "AND status NOT IN ('completed', 'cancelled') ORDER BY id",
                (child.id, child.assigned_to),
            )
            matching = await cursor.fetchall()
            if len(matching) > 1:
                raise owned_steps.OwnedStepsError("owned_steps_booking_conflict", parent_id=parent.id)
            executed = (
                child.status not in (self.work_type_registry.get_initial_status(child.work_type), "scheduled")
                or child.actual_tokens != 0 or bool(child.verification)
                or any(key.startswith(("crew_execution", "crew_verification")) for key in child.metadata)
                or bool(matching and (
                    matching[0]["status"] != "scheduled" or matching[0]["actual_start"] is not None
                    or matching[0]["actual_end"] is not None or matching[0]["total_tokens_consumed"]
                ))
            )
            historical |= executed
            todo = {"label": child.title, "status": "pending", "assigned_to": child.assigned_to}
            todo_json = owned_steps.owned_json_bytes(todo).decode("utf-8")
            plan_metadata_keys = tuple(sorted(child.metadata))
            records.append(owned_steps.OwnedStepRecord(
                step_id=uuid.uuid4().hex, kind="child", todo_json=todo_json,
                digest=owned_steps.owned_digest(todo_json), child=commitment,
                source_digest=await self._owned_child_source(child, protected_metadata_keys=plan_metadata_keys),
                plan_metadata_keys=plan_metadata_keys, assignee_id=child.assigned_to,
                booking_id=matching[0]["id"] if matching else None,
                permit_state="interrupted" if executed else "unstarted",
            ))
        projection = (
            prefix
            if spans
            else owned_steps.append_owned_rows(
                prefix,
                tuple(
                    row.todo_json
                    for row in records[len(spans):]
                ),
            )
        )
        control = owned_steps.OwnedStepsControl(
            owner_kind=plan.owner_kind, parent_id=parent.id, thread_id=plan.thread_id,
            facilitator_id=plan.facilitator_id, incarnation=plan.incarnation,
            plan_digest=plan.plan_digest,
            seed_digest=owned_steps.owned_digest(owned_steps.owned_json_bytes(plan.model_dump(mode="json"))),
            seed_request_digest=request_digest,
            steps_digest=owned_steps.owned_digest(projection),
            parent_source_digest=await self._owned_parent_digest(parent),
            manual_prefix_length=len(spans), original_steps_json=prefix,
            authorized_steps_json=projection, gate_json=owned_steps.owned_json_bytes({
                key: value for key, value in parent.metadata.items() if key == "steps_gate_completion"
            }).decode("utf-8"),
            mode=(
                "awaiting_adoption"
                if spans
                else "interrupted"
                if historical
                else "active"
            ),
            rows=tuple(records),
        )
        await self._db.execute(
            "UPDATE work_items SET steps = ?, steps_control = ? WHERE id = ?",
            (projection, control.model_dump_json(), parent.id),
        )

    async def _replay_owned_seed(
        self, parent_id: str, seed: owned_steps.OwnedStepsSeed | None, request_digest: str,
    ) -> tuple[WorkItem, tuple[WorkItem, ...]] | None:
        if seed is None:
            return None
        if type(seed) is not owned_steps.OwnedStepsSeed:
            raise owned_steps.OwnedStepsError("owned_steps_seed_invalid", parent_id=parent_id)
        assert self._db is not None
        cursor = await self._db.execute("SELECT steps_control FROM work_items WHERE id = ?", (parent_id,))
        stored = await cursor.fetchone()
        if stored is None or stored["steps_control"] is None:
            return None
        snapshot, parent, children = await self._load_owned_steps(parent_id)
        grant = await self._authorize_owned_steps(seed.authority, parent_id=parent_id, operation="seed")
        self._require_owned_manager(snapshot.control, grant)
        if (
            snapshot.control.seed_digest
            != owned_steps.owned_digest(owned_steps.owned_json_bytes(seed.plan.model_dump(mode="json")))
            or snapshot.control.seed_request_digest != request_digest
        ):
            raise owned_steps.OwnedStepsError("owned_steps_seed_conflict", parent_id=parent_id)
        return parent, tuple(children[entry.child_id] for entry in seed.plan.children)

    async def preview_owned_steps_adoption(
        self, parent_id: str, *, authority: owned_steps.OwnedStepsAuthority,
        view_id: str, turn_id: str,
    ) -> owned_steps.OwnedStepsAdoptionPreview:
        if self._db is None:
            raise owned_steps.OwnedStepsError("owned_steps_unavailable", parent_id=parent_id)
        async with self._booking_transaction():
            snapshot, _, _ = await self._load_owned_steps(parent_id)
            control = snapshot.control
            grant = await self._authorize_owned_steps(
                authority, parent_id=parent_id, operation="preview_adoption",
            )
            self._require_owned_manager(control, grant)
            if control.mode != "awaiting_adoption":
                raise owned_steps.OwnedStepsError("owned_steps_adoption_not_pending", parent_id=parent_id)
            token = owned_steps.OwnedStepsPlanToken(
                parent_id=parent_id, incarnation=control.incarnation,
                layout_revision=control.layout_revision, plan_revision=control.plan_revision,
                plan_digest=control.plan_digest, steps_digest=control.steps_digest,
                source_digest=snapshot.source_digest, actor_id=grant.actor_id,
                thread_id=grant.thread_id, view_id=view_id, turn_id=turn_id,
            )
            payload = {
                "token": token.model_dump(mode="json"), "prefix_json": control.authorized_steps_json,
                "suffix_json": [row.todo_json for row in control.rows[control.manual_prefix_length:]],
                "children": [row.child.model_dump(mode="json") for row in control.rows if row.child],
                "gate_json": control.gate_json,
            }
            digest = owned_steps.owned_digest(owned_steps.owned_json_bytes(payload))
            return owned_steps.OwnedStepsAdoptionPreview.model_validate_json(
                owned_steps.owned_json_bytes({**payload, "preview_digest": digest}),
            )

    @staticmethod
    def _require_owned_manager(
        control: owned_steps.OwnedStepsControl, grant: owned_steps.OwnedStepsGrant,
    ) -> None:
        if grant.thread_id != control.thread_id or (
            grant.role != "captain"
            and not (
                grant.role == "facilitator"
                and grant.actor_id == control.facilitator_id
            )
        ):
            raise owned_steps.OwnedStepsError("owned_steps_authority_denied", parent_id=control.parent_id)

    async def start_owned_legacy_parent(
        self,
        snapshot: owned_steps.OwnedStepsSnapshot,
        authority: owned_steps.OwnedStepsAuthority,
    ) -> owned_steps.OwnedStepsSnapshot:
        """Move an admitted legacy coordination parent to ``in_progress``.

        This owner CAS deliberately leaves the parent assignment unchanged.  It
        exists because generic task transition requires an assignee, while the
        legacy parent is a coordination container whose child rows carry the
        actual worker assignments.
        """
        if self._db is None:
            raise owned_steps.OwnedStepsError(
                "owned_steps_unavailable",
                parent_id=snapshot.control.parent_id,
            )
        changed = False
        async with self._booking_transaction():
            live, parent, _ = await self._load_owned_steps(
                snapshot.control.parent_id,
            )
            control = live.control
            grant = await self._authorize_owned_steps(
                authority,
                parent_id=parent.id,
                operation="start_parent",
                token=snapshot,
            )
            if (
                grant.role != "owner"
                or control.owner_kind != "legacy"
                or snapshot.control != control
                or snapshot.source_digest != live.source_digest
                or control.mode != "active"
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_parent_start_conflict",
                    parent_id=parent.id,
                )
            if parent.status == "in_progress":
                return live
            valid, _ = self.work_type_registry.validate_transition(
                parent.work_type,
                parent.status,
                "in_progress",
            )
            if not valid:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_parent_start_conflict",
                    parent_id=parent.id,
                )
            now = time.time()
            await self._db.execute(
                "UPDATE work_items SET status = 'in_progress', updated_at = ? "
                "WHERE id = ?",
                (now, parent.id),
            )
            updated_parent = await self.get_work_item(parent.id)
            assert updated_parent is not None
            candidate = control.model_copy(
                update={
                    "parent_source_digest": await self._owned_parent_digest(
                        updated_parent
                    )
                }
            )
            await self._db.execute(
                "UPDATE work_items SET steps_control = ? WHERE id = ?",
                (candidate.model_dump_json(), parent.id),
            )
            result = self._owned_snapshot(candidate)
            changed = True
        if changed:
            await self._refresh_snapshot_cache()
            self._emit(
                EventType.WORK_ITEM_STATUS_CHANGED,
                {
                    "work_item": self._event_work_item_projection(updated_parent),
                    "old_status": parent.status,
                    "new_status": "in_progress",
                    "source": "owned_legacy_parent",
                },
            )
        return result

    async def compare_and_set_owned_step(
        self, mutation: owned_steps.OwnedStepMutation,
    ) -> owned_steps.OwnedStepMutationResult:
        """Commit one source-checked owner mutation and publish its effects."""
        result, effects = await self._compare_and_set_owned_step_core(
            mutation,
            transaction_open=False,
        )
        if effects is not None:
            await self._publish_owned_step_effects((effects,))
        return result

    async def compare_and_set_owned_steps_batch(
        self,
        mutations: tuple[owned_steps.OwnedStepMutation, ...],
    ) -> tuple[owned_steps.OwnedStepMutationResult, ...]:
        """Commit a finite viewed command batch in one database transaction."""
        if (
            type(mutations) is not tuple
            or not 1 <= len(mutations) <= owned_steps.MAX_OWNED_VIEW_ROWS
            or any(type(mutation) is not owned_steps.OwnedStepMutation for mutation in mutations)
        ):
            raise owned_steps.OwnedStepsError("owned_steps_batch_invalid")
        parent_ids = {mutation.change.token.parent_id for mutation in mutations}
        if len(parent_ids) != 1:
            raise owned_steps.OwnedStepsError("owned_steps_batch_scope_conflict")
        effects: list[_OwnedStepPostCommit] = []
        results: list[owned_steps.OwnedStepMutationResult] = []
        async with self._booking_transaction():
            for mutation in mutations:
                result, pending = await self._compare_and_set_owned_step_core(
                    mutation,
                    transaction_open=True,
                )
                results.append(result)
                if pending is not None:
                    effects.append(pending)
        await self._publish_owned_step_effects(tuple(effects))
        return tuple(results)

    @asynccontextmanager
    async def _owned_step_transaction(
        self,
        *,
        transaction_open: bool,
    ) -> AsyncIterator[None]:
        if transaction_open:
            yield
            return
        async with self._booking_transaction():
            yield

    async def _compare_and_set_owned_step_core(
        self,
        mutation: owned_steps.OwnedStepMutation,
        *,
        transaction_open: bool,
    ) -> tuple[owned_steps.OwnedStepMutationResult, _OwnedStepPostCommit | None]:
        """Mutate within either a newly opened or caller-held write transaction."""
        if type(mutation) is not owned_steps.OwnedStepMutation:
            raise owned_steps.OwnedStepsError("owned_steps_mutation_invalid")
        change = owned_steps.OwnedStepChange.model_validate(mutation.change)
        token, command = change.token, change.command
        execution_token = isinstance(token, owned_steps.OwnedStepExecutionPermit)
        if execution_token and (
            not isinstance(command, (owned_steps.SubmitOwnedStepCommand, owned_steps.ReviewOwnedStepCommand))
            or (
                command.submission.permit if isinstance(command, owned_steps.SubmitOwnedStepCommand)
                else command.result.permit
            ) != token
        ):
            raise owned_steps.OwnedStepsError("owned_steps_execution_binding_invalid", parent_id=token.parent_id)
        if self._db is None:
            raise owned_steps.OwnedStepsError("owned_steps_unavailable", parent_id=token.parent_id)
        request_digest = owned_steps.owned_digest(owned_steps.owned_json_bytes(change.model_dump(mode="json")))
        booking_events: list[tuple[EventType, dict[str, Any]]] = []
        changed_child_ids: set[str] = set()
        result_permit: owned_steps.OwnedStepExecutionPermit | None = None
        disposition: Literal["applied", "new"] = "applied"
        continuation_parent_id: str | None = None
        async with self._owned_step_transaction(transaction_open=transaction_open):
            snapshot, parent, children = await self._load_owned_steps(
                token.parent_id, allow_projection_mismatch=command.kind == "repair_projection",
                step_id=token.step_id if isinstance(token, (owned_steps.StepViewToken, owned_steps.OwnedStepExecutionPermit)) else None,
            )
            control = snapshot.control
            grant = await self._authorize_owned_steps(
                mutation.authority, parent_id=parent.id, operation=command.kind, token=token,
            )
            if (
                token.incarnation != control.incarnation or token.plan_digest != control.plan_digest
                or token.plan_revision != control.plan_revision
                or (not execution_token and token.thread_id != control.thread_id)
            ):
                raise owned_steps.OwnedStepsError("owned_steps_plan_conflict", parent_id=parent.id)
            replay = await self._owned_operation_receipt(parent.id, control.incarnation, change.operation_id)
            if replay is not None:
                if replay.request_digest != request_digest:
                    raise owned_steps.OwnedStepsError("owned_steps_operation_conflict", parent_id=parent.id)
                disposition = (
                    "already_started" if replay.disposition in ("started", "observed_started") else
                    "terminal" if replay.disposition == "observed_terminal" else "duplicate"
                )
                # An acknowledgement is not a fresh view or another execution permit.
                return (
                    owned_steps.OwnedStepMutationResult(
                        None,
                        disposition,
                        replay.permit,
                        replay,
                    ),
                    None,
                )
            if not execution_token and token.layout_revision != control.layout_revision:
                raise owned_steps.OwnedStepsError("owned_steps_layout_conflict", parent_id=parent.id)
            rows = list(control.rows)
            index: int | None = None
            row: owned_steps.OwnedStepRecord | None = None
            if isinstance(token, (owned_steps.StepViewToken, owned_steps.OwnedStepExecutionPermit)):
                index = next((i for i, entry in enumerate(rows) if entry.step_id == token.step_id), None)
                if index is None:
                    raise owned_steps.OwnedStepsError("owned_steps_row_missing", parent_id=parent.id)
                row = rows[index]
                if execution_token:
                    digest = owned_steps.owned_digest(owned_steps.owned_json_bytes(token.model_dump(mode="json")))
                    if row.permit != digest or row.assignment_epoch != token.assignment_epoch:
                        raise owned_steps.OwnedStepsError("owned_steps_submission_conflict", parent_id=parent.id)
                elif (
                    row.revision != token.row_revision or row.digest != token.row_digest
                    or row.assignment_epoch != token.assignment_epoch or row.source_digest != token.source_digest
                ):
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_row_conflict", parent_id=parent.id, view_id=token.view_id,
                    )
            elif token.steps_digest != control.steps_digest or token.source_digest != snapshot.source_digest:
                raise owned_steps.OwnedStepsError("owned_steps_plan_conflict", parent_id=parent.id)
            projection = control.authorized_steps_json
            control_updates: dict[str, Any] = {}
            receipt_disposition: str = "applied"
            binding = _OwnedStepsWriteBinding(
                parent.id, frozenset({row.child.child_id} if row is not None and row.child else ()),
                command.kind,
                mutation.authority.context if type(mutation.authority.context) in (
                    _OwnedExecutionScope, owned_steps.OwnedOwnerInvocation,
                ) else None,
            )
            self._owned_steps_write_binding = binding
            try:
                if isinstance(command, owned_steps.AdoptOwnedStepsCommand):
                    self._require_owned_manager(control, grant)
                    preview = command.preview
                    payload = preview.model_dump(mode="json", exclude={"preview_digest"})
                    if (
                        not isinstance(token, owned_steps.OwnedStepsPlanToken)
                        or preview.token != token or control.mode != "awaiting_adoption"
                        or preview.preview_digest != owned_steps.owned_digest(owned_steps.owned_json_bytes(payload))
                        or preview.prefix_json != projection or preview.gate_json != control.gate_json
                        or preview.suffix_json != tuple(entry.todo_json for entry in rows[control.manual_prefix_length:])
                        or preview.children != tuple(entry.child for entry in rows if entry.child)
                    ):
                        raise owned_steps.OwnedStepsError("owned_steps_adoption_conflict", parent_id=parent.id)
                    projection = owned_steps.append_owned_rows(projection, preview.suffix_json)
                    control_updates = {
                        "mode": "interrupted" if any(entry.permit_state == "interrupted" for entry in rows) else "active",
                        "layout_revision": control.layout_revision + 1,
                    }
                    receipt_disposition = "adopted"
                elif isinstance(command, owned_steps.RepairOwnedStepsCommand):
                    self._require_owned_manager(control, grant)
                    if not isinstance(token, owned_steps.OwnedStepsPlanToken):
                        raise owned_steps.OwnedStepsError("owned_steps_plan_token_required", parent_id=parent.id)
                    cursor = await self._db.execute("SELECT steps FROM work_items WHERE id = ?", (parent.id,))
                    raw = (await cursor.fetchone())["steps"]
                    if owned_steps.owned_digest(raw) != command.observed_steps_digest:
                        raise owned_steps.OwnedStepsError("owned_steps_projection_conflict", parent_id=parent.id)
                    if raw == projection:
                        receipt = await self._record_owned_operation(control, change, request_digest, "noop", None)
                        return (
                            owned_steps.OwnedStepMutationResult(
                                snapshot,
                                "duplicate",
                                receipt=receipt,
                            ),
                            None,
                        )
                    control_updates["layout_revision"] = control.layout_revision + 1
                    receipt_disposition = "repaired"
                else:
                    if row is None or index is None:
                        raise owned_steps.OwnedStepsError("owned_steps_row_token_required", parent_id=parent.id)
                    if control.mode != "active" and not (
                        isinstance(command, owned_steps.ManualStepCommand)
                        and control.mode in ("awaiting_adoption", "waiting_manual_gate")
                    ) and not (
                        isinstance(
                            command,
                            (
                                owned_steps.CancelOwnedStepCommand,
                                owned_steps.AbandonOwnedStepCommand,
                            ),
                        )
                        and control.mode in ("awaiting_adoption", "interrupted", "waiting_manual_gate")
                    ):
                        raise owned_steps.OwnedStepsError(
                            "owned_steps_not_active", parent_id=parent.id,
                            actions=("preview_adoption", "inspect_source", "interrupted_work"),
                        )
                    if isinstance(command, owned_steps.ManualStepCommand):
                        self._require_owned_manager(control, grant)
                        if row.kind != "manual":
                            raise owned_steps.OwnedStepsError("owned_steps_evidence_owned", parent_id=parent.id)
                        todo = owned_steps.owned_json_loads(row.todo_json)
                        statuses = {"manual_submit": "submitted", "manual_confirm": "done", "manual_reject": "rejected"}
                        if command.kind in statuses:
                            target = statuses[command.kind]
                            if not validate_step_transition(todo["status"], target):
                                raise owned_steps.OwnedStepsError("owned_steps_transition_invalid", parent_id=parent.id)
                            if target != todo["status"]:
                                todo["status"] = target
                                todo["submitted_by" if target == "submitted" else "confirmed_by"] = grant.actor_id
                        if command.kind == "edit_note" or command.note is not None:
                            todo["note"] = command.note
                        if todo == owned_steps.owned_json_loads(row.todo_json):
                            receipt = await self._record_owned_operation(control, change, request_digest, "noop", row)
                            return (
                                owned_steps.OwnedStepMutationResult(
                                    snapshot,
                                    "duplicate",
                                    receipt=receipt,
                                ),
                                None,
                            )
                        todo_json = owned_steps.owned_json_bytes(todo).decode("utf-8")
                        row = row.model_copy(update={"todo_json": todo_json, "digest": owned_steps.owned_digest(todo_json)})
                    else:
                        if row.child is None:
                            raise owned_steps.OwnedStepsError("owned_steps_child_required", parent_id=parent.id)
                        child = children[row.child.child_id]
                        changed, row, receipt_disposition, result_permit = await self._mutate_owned_child(
                            control, row, child, parent, command, grant, binding, booking_events,
                        )
                        if not changed:
                            state = "duplicate"
                            receipt_disposition = "noop"
                            if isinstance(command, owned_steps.StartOwnedStepCommand):
                                state = "already_started" if row.permit_state == "started" else "terminal"
                                receipt_disposition = "observed_started" if state == "already_started" else "observed_terminal"
                            receipt = await self._record_owned_operation(
                                control, change, request_digest, receipt_disposition, row, result_permit,
                            )
                            return (
                                owned_steps.OwnedStepMutationResult(
                                    snapshot,
                                    state,
                                    result_permit,
                                    receipt,
                                ),
                                None,
                            )
                        if isinstance(command, owned_steps.StartOwnedStepCommand):
                            disposition = "new"
                        fresh_child = await self.get_work_item(child.id)
                        assert fresh_child is not None
                        if not _json_values_exactly_equal(fresh_child.to_dict(), child.to_dict()):
                            changed_child_ids.add(child.id)
                        row = row.model_copy(update={"source_digest": await self._owned_child_source(
                            fresh_child, protected_metadata_keys=(
                                tuple(fresh_child.metadata) if control.owner_kind == "canonical"
                                else row.plan_metadata_keys
                            ),
                        )})
                    row = row.model_copy(update={"revision": row.revision + 1})
                    rows[index] = row
                    if control.mode != "awaiting_adoption" or index < control.manual_prefix_length:
                        projection = owned_steps.replace_owned_row(projection, index, row.todo_json)
                candidate, encoded_control = control.prepare_projection(
                    rows=tuple(rows), projection=projection,
                    mode=control_updates.get("mode", control.mode),
                    layout_revision=control_updates.get("layout_revision", control.layout_revision),
                )
                if (
                    isinstance(command, owned_steps.ManualStepCommand)
                    and control.mode == "waiting_manual_gate"
                    and control.finalization is not None
                    and control.finalization_disposition == "pending"
                    and any(
                        owned_steps.owned_json_loads(entry.todo_json)["status"] != "done"
                        for entry in control.rows[:control.manual_prefix_length]
                    )
                    and all(
                        owned_steps.owned_json_loads(entry.todo_json)["status"] == "done"
                        for entry in candidate.rows[:candidate.manual_prefix_length]
                    )
                ):
                    continuation_parent_id = parent.id
                receipt = await self._record_owned_operation(
                    candidate, change, request_digest, receipt_disposition, row, result_permit,
                )
                await self._db.execute(
                    "UPDATE work_items SET steps = ?, steps_control = ?, updated_at = ? WHERE id = ?",
                    (projection, encoded_control, time.time(), parent.id),
                )
                result_snapshot = self._owned_snapshot(candidate, raw_control=encoded_control)
                updated_parent = await self.get_work_item(parent.id)
                updated_children = [await self.get_work_item(child_id) for child_id in sorted(changed_child_ids)]
            finally:
                self._owned_steps_write_binding = None
        assert updated_parent is not None
        committed_children = tuple(
            item for item in updated_children if item is not None
        )
        effects = _OwnedStepPostCommit(
            parent=parent,
            updated_parent=updated_parent,
            children=children,
            updated_children=committed_children,
            command_kind=command.kind,
            booking_events=tuple(booking_events),
            continuation_parent_id=continuation_parent_id,
        )
        return (
            owned_steps.OwnedStepMutationResult(
                result_snapshot,
                disposition,
                result_permit,
                receipt,
            ),
            effects,
        )

    async def _publish_owned_step_effects(
        self,
        effects: tuple[_OwnedStepPostCommit, ...],
    ) -> None:
        if not effects:
            return
        await self._refresh_snapshot_cache()
        for pending in effects:
            for item in (pending.updated_parent, *pending.updated_children):
                self._emit(
                    EventType.WORK_ITEM_UPDATED,
                    {"work_item": self._event_work_item_projection(item)},
                )
            for item in pending.updated_children:
                previous = pending.children[item.id]
                if item.status != previous.status:
                    self._emit(EventType.WORK_ITEM_STATUS_CHANGED, {
                        "work_item": self._event_work_item_projection(item),
                        "old_status": previous.status,
                        "new_status": item.status,
                        "source": pending.command_kind,
                    })
                if item.assigned_to != previous.assigned_to:
                    self._emit(EventType.WORK_ITEM_ASSIGNED, {
                        "work_item": self._event_work_item_projection(item),
                        "source": pending.command_kind,
                    })
            for event_type, payload in pending.booking_events:
                self._emit(event_type, payload)
            if pending.continuation_parent_id is not None:
                notify = getattr(
                    self._owned_steps_authorizer,
                    "owned_manual_gate_released",
                    None,
                )
                if not callable(notify):
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_continuation_owner_unavailable",
                        parent_id=pending.continuation_parent_id,
                    )
                await notify(pending.continuation_parent_id)

    async def _record_owned_operation(
        self, control: owned_steps.OwnedStepsControl, change: owned_steps.OwnedStepChange,
        request_digest: str, disposition: str, row: owned_steps.OwnedStepRecord | None,
        permit: owned_steps.OwnedStepExecutionPermit | None = None,
    ) -> owned_steps.OwnedOperationReceipt:
        receipt = owned_steps.OwnedOperationReceipt(
            operation_id=change.operation_id, request_digest=request_digest,
            step_id=row.step_id if row else None, disposition=disposition, permit=permit,
            observation=owned_steps.OwnedStepObservation(
                parent_id=control.parent_id, incarnation=control.incarnation,
                plan_digest=control.plan_digest, plan_revision=control.plan_revision,
                layout_revision=control.layout_revision, observation_revision=control.observation_revision,
                steps_digest=control.steps_digest, step_id=row.step_id if row else None,
                row_revision=row.revision if row else None, row_digest=row.digest if row else None,
                todo_json=row.todo_json if row else None, source_digest=row.source_digest if row else None,
                permit_state=row.permit_state if row else None,
            ),
        )
        await self._write_owned_journal(
            control.parent_id, control.incarnation, "operation", receipt.operation_id,
            owned_steps.owned_json_bytes(receipt.model_dump(mode="json")).decode("utf-8"),
            step_id=receipt.step_id,
        )
        return receipt

    async def _mutate_owned_child(
        self, control: owned_steps.OwnedStepsControl, row: owned_steps.OwnedStepRecord,
        child: WorkItem, parent: WorkItem, command: owned_steps.OwnedStepsCommand,
        grant: owned_steps.OwnedStepsGrant, binding: _OwnedStepsWriteBinding,
        booking_events: list[tuple[EventType, dict[str, Any]]],
    ) -> tuple[bool, owned_steps.OwnedStepRecord, str, owned_steps.OwnedStepExecutionPermit | None]:
        assert self._db is not None
        booking = await self.get_booking(row.booking_id) if row.booking_id else None
        if row.booking_id and (
            booking is None or booking.work_item_id != child.id or booking.resource_id != row.assignee_id
        ):
            raise owned_steps.OwnedStepsError("owned_steps_booking_conflict", parent_id=parent.id)
        now = time.time()
        todo = owned_steps.owned_json_loads(row.todo_json)
        updates: dict[str, Any] = {}
        receipt = "applied"
        permit = None
        if isinstance(command, (owned_steps.StartOwnedStepCommand, owned_steps.SubmitOwnedStepCommand, owned_steps.UnstartedOwnedStepCommand)):
            actor = row.assignee_id or (parent.id if isinstance(command, owned_steps.UnstartedOwnedStepCommand) else None)
            if grant.role != "executor" or grant.actor_id != actor or grant.thread_id != control.thread_id:
                raise owned_steps.OwnedStepsError("owned_steps_authority_denied", parent_id=parent.id)
        elif isinstance(command, owned_steps.ReviewOwnedStepCommand):
            if (
                grant.role != "verifier" or grant.actor_id != command.result.reviewer_id
                or grant.actor_id == row.assignee_id or grant.thread_id != control.thread_id
            ):
                raise owned_steps.OwnedStepsError("owned_steps_authority_denied", parent_id=parent.id)
        elif isinstance(command, owned_steps.ReassignOwnedStepCommand):
            if grant.role == "owner":
                if grant.thread_id != control.thread_id:
                    raise owned_steps.OwnedStepsError(
                        "owned_steps_authority_denied",
                        parent_id=parent.id,
                    )
            else:
                self._require_owned_manager(control, grant)
        elif grant.role != "ttl":
            self._require_owned_manager(control, grant)
        elif not isinstance(command, owned_steps.CancelOwnedStepCommand):
            raise owned_steps.OwnedStepsError("owned_steps_authority_denied", parent_id=parent.id)
        if isinstance(command, owned_steps.StartOwnedStepCommand):
            if row.permit_state != "unstarted":
                previous = (
                    await self._read_owned_evidence(parent.id, control.incarnation, "permit", row.permit)
                    if row.permit is not None else None
                )
                return False, row, "started", previous
            if (
                child.status not in (self.work_type_registry.get_initial_status(child.work_type), "scheduled")
                or child.assigned_to != row.assignee_id
                or child.actual_tokens or child.verification
                or any(key.startswith(("crew_execution", "crew_verification")) for key in child.metadata)
            ):
                raise owned_steps.OwnedStepsError("owned_steps_execution_conflict", parent_id=parent.id)
            # Scheduled bookings use the existing start_booking lifecycle;
            # "scheduled" is not a task-registry state for ordinary tasks.
            if booking is None and not self._validate_work_item_status_transition(child, "in_progress"):
                raise owned_steps.OwnedStepsError("owned_steps_execution_transition", parent_id=parent.id)
            resource = self._resolve_pull_resource(row.assignee_id, "assign", False)
            if (
                (resource is None and not (binding.execution_scope is not None and booking is None))
                or (resource is not None and (
                    not self._check_eligibility(resource, child) or not await self._requirements_allow(child, resource)
                ))
            ):
                raise owned_steps.OwnedStepsError("owned_steps_assignment_ineligible", parent_id=parent.id)
            for dependency_id in child.depends_on:
                dependency = await self.get_work_item(dependency_id)
                if dependency is None or dependency.status != "done":
                    raise owned_steps.OwnedStepsError("owned_steps_dependency_pending", parent_id=parent.id)
            if booking is not None:
                if booking.status != "scheduled":
                    raise owned_steps.OwnedStepsError("owned_steps_booking_conflict", parent_id=parent.id)
                cursor = await self._db.execute(
                    "SELECT COUNT(*) FROM bookings WHERE resource_id = ? AND id != ? "
                    "AND status IN ('scheduled', 'active')", (booking.resource_id, booking.id),
                )
                if (await cursor.fetchone())[0] >= resource.capacity:
                    raise owned_steps.OwnedStepsError("owned_steps_booking_capacity", parent_id=parent.id)
                await self._db.execute(
                    "UPDATE bookings SET status = 'active', actual_start = ? WHERE id = ?", (now, booking.id),
                )
                await self._record_timestamp(booking.id, "active", "owned_execution", binding=binding)
                started = await self.get_booking(booking.id)
                booking_events.append((EventType.BOOKING_STARTED, {"booking": started.to_dict()}))
            permit = owned_steps.OwnedStepExecutionPermit(
                parent_id=parent.id, incarnation=control.incarnation, plan_digest=control.plan_digest,
                plan_revision=control.plan_revision, step_id=row.step_id, child_id=child.id,
                assignee_id=row.assignee_id, assignment_epoch=row.assignment_epoch,
                execution_nonce=command.execution_nonce, source_digest=row.source_digest,
                booking_id=row.booking_id,
            )
            await self._db.execute(
                "UPDATE work_items SET status = 'in_progress', updated_at = ? WHERE id = ?", (now, child.id),
            )
            updates.update(permit=await self._write_owned_evidence(permit), permit_state="started")
            todo["status"] = "in_progress"
            receipt = "started"
        elif isinstance(command, owned_steps.SubmitOwnedStepCommand):
            submission = command.submission
            execution = owned_steps.owned_json_loads(submission.execution_json)
            if (
                row.permit_state != "started" or row.permit != owned_steps.owned_digest(
                    owned_steps.owned_json_bytes(submission.permit.model_dump(mode="json")),
                )
                or child.status != "in_progress" or execution["thread_id"] != control.thread_id
                or child.actual_tokens > _MAX_WORK_ITEM_ACTUAL_TOKENS - execution["tokens_used"]
            ):
                raise owned_steps.OwnedStepsError("owned_steps_submission_conflict", parent_id=parent.id)
            if await self._read_owned_evidence(parent.id, control.incarnation, "permit", row.permit) != submission.permit:
                raise owned_steps.OwnedStepsError("owned_steps_submission_conflict", parent_id=parent.id)
            if execution["status"] == "done" and submission.output is None and not (
                control.owner_kind == "legacy" and isinstance(submission, owned_steps.OwnedExecutionSubmission)
                and isinstance(submission.result, owned_steps.OwnedExecutionResult)
            ):
                raise owned_steps.OwnedStepsError("owned_steps_output_required", parent_id=parent.id)
            if not self._validate_work_item_status_transition(child, execution["status"]):
                raise owned_steps.OwnedStepsError("owned_steps_execution_transition", parent_id=parent.id)
            if submission.output is not None:
                if self._owned_steps_content is None:
                    raise owned_steps.OwnedStepsError("owned_steps_content_unavailable", parent_id=parent.id)
                content = await self._owned_steps_content.read(submission.output.content_hash)
                if (
                    type(content) is not bytes or len(content) != submission.output.size_bytes
                    or owned_steps.owned_digest(content) != submission.output.content_hash
                ):
                    raise owned_steps.OwnedStepsError("owned_steps_content_conflict", parent_id=parent.id)
            if isinstance(submission, owned_steps.OwnedExecutionSubmission):
                exact = submission.result
                if isinstance(exact, owned_steps.OwnedContentReference):
                    if self._owned_steps_content is None:
                        raise owned_steps.OwnedStepsError("owned_steps_content_unavailable", parent_id=parent.id)
                    raw_result = await self._owned_steps_content.read(exact.content_hash)
                    if (
                        type(raw_result) is not bytes or len(raw_result) != exact.size_bytes
                        or owned_steps.owned_digest(raw_result) != exact.content_hash
                    ):
                        raise owned_steps.OwnedStepsError("owned_steps_content_conflict", parent_id=parent.id)
                    exact = owned_steps.OwnedExecutionResult.model_validate_json(raw_result)
                if exact.spec_id != row.child.spec_id:
                    raise owned_steps.OwnedStepsError("owned_steps_result_conflict", parent_id=parent.id)
                owned_steps.OwnedExecutionSubmission.model_validate({
                    **submission.model_dump(), "result": exact,
                })
                if submission.output is not None and (
                    (isinstance(exact.output, owned_steps.OwnedContentReference) and exact.output != submission.output)
                    or (type(exact.output) is str and (
                        owned_steps.owned_digest(exact.output) != submission.output.content_hash
                        or len(exact.output.encode("utf-8")) != submission.output.size_bytes
                    ))
                ):
                    raise owned_steps.OwnedStepsError("owned_steps_result_conflict", parent_id=parent.id)
            metadata = dict(child.metadata)
            metadata["crew_execution"] = execution
            if submission.output is not None:
                metadata["crew_execution_output"] = submission.output.model_dump(mode="json")
            if submission.token_usage_json is not None:
                metadata[CREW_EXECUTION_TOKEN_USAGE_KEY] = owned_steps.owned_json_loads(submission.token_usage_json)
            encoded = owned_steps.owned_json_bytes(metadata)
            if len(encoded) > _MAX_WORK_ITEM_METADATA_BYTES:
                raise owned_steps.OwnedStepsError("owned_steps_submission_too_large", parent_id=parent.id)
            await self._db.execute(
                "UPDATE work_items SET status = ?, metadata = ?, actual_tokens = actual_tokens + ?, "
                "updated_at = ? WHERE id = ?",
                (execution["status"], encoded.decode("utf-8"), execution["tokens_used"], now, child.id),
            )
            if booking is not None:
                if booking.status not in ("active", "on_break") or await self.get_booking_journal(booking.id):
                    raise owned_steps.OwnedStepsError("owned_steps_booking_conflict", parent_id=parent.id)
                await self._db.execute(
                    "UPDATE bookings SET status = 'completed', actual_end = ?, total_tokens_consumed = ? WHERE id = ?",
                    (now, execution["tokens_used"], booking.id),
                )
                await self._record_timestamp(booking.id, "completed", "owned_execution", binding=binding)
                journal = await self._generate_journal(booking.id, binding=binding)
                completed = await self.get_booking(booking.id)
                booking_events.append((EventType.BOOKING_COMPLETED, {
                    "booking": completed.to_dict(), "journal": [entry.to_dict() for entry in journal],
                }))
            todo.update(status="submitted" if execution["status"] == "done" else "rejected", submitted_by=grant.actor_id)
            updates.update(
                submission=await self._write_owned_evidence(submission),
                permit_state="submitted" if execution["status"] == "done" else "terminal",
            )
            receipt = "submitted"
        elif isinstance(command, owned_steps.UnstartedOwnedStepCommand):
            submission = command.submission
            execution = owned_steps.owned_json_loads(submission.execution_json)
            if (
                row.permit_state != "unstarted" or row.permit is not None or row.submission is not None
                or submission.parent_id != parent.id or submission.incarnation != control.incarnation
                or submission.plan_digest != control.plan_digest or submission.step_id != row.step_id
                or submission.child_id != child.id or submission.assignment_epoch != row.assignment_epoch
                or submission.assignee_id != row.assignee_id or submission.thread_id != control.thread_id
                or submission.source_digest != row.source_digest or submission.result.spec_id != row.child.spec_id
                or child.verification or any(key.startswith("crew_execution") for key in child.metadata)
            ):
                raise owned_steps.OwnedStepsError("owned_steps_unstarted_evidence_conflict", parent_id=parent.id)
            reason = execution["stopped_reason"]
            if (reason == "unassigned" and child.assigned_to is not None) or (
                reason == "agent_unresolvable" and child.assigned_to is None
            ):
                raise owned_steps.OwnedStepsError("owned_steps_unstarted_evidence_conflict", parent_id=parent.id)
            if reason == "dependency_blocked":
                unresolved = []
                for dependency_id in child.depends_on:
                    dependency = await self.get_work_item(dependency_id)
                    if (
                        (dependency is None or dependency.status != "done")
                        and dependency_id not in unresolved
                    ):
                        unresolved.append(dependency_id)
                if not unresolved or unresolved != execution["blocked_dependency_ids"]:
                    raise owned_steps.OwnedStepsError("owned_steps_dependency_conflict", parent_id=parent.id)
            if not self._validate_work_item_status_transition(child, "blocked"):
                raise owned_steps.OwnedStepsError("owned_steps_execution_transition", parent_id=parent.id)
            metadata = {**child.metadata, "crew_execution": execution}
            await self._db.execute(
                "UPDATE work_items SET metadata=?,status='blocked',updated_at=? WHERE id=?",
                (owned_steps.owned_json_bytes(metadata).decode("utf-8"), now, child.id),
            )
            if booking is not None:
                if booking.status != "scheduled":
                    raise owned_steps.OwnedStepsError("owned_steps_booking_conflict", parent_id=parent.id)
                cancelled = await self._cancel_booking(booking, binding=binding)
                booking_events.append((EventType.BOOKING_CANCELLED, {"booking": cancelled.to_dict()}))
            updates.update(submission=await self._write_owned_evidence(submission), permit_state="terminal")
            todo["status"] = "rejected"
            receipt = "submitted"
        elif isinstance(command, owned_steps.ReviewOwnedStepCommand):
            result = command.result
            if (
                row.permit_state != "submitted" or row.reviewed_result is not None
                or row.submission != result.submission_digest
            ):
                raise owned_steps.OwnedStepsError("owned_steps_review_conflict", parent_id=parent.id)
            submission = await self._read_owned_evidence(parent.id, control.incarnation, "submission", row.submission)
            if submission.permit != result.permit:
                raise owned_steps.OwnedStepsError("owned_steps_review_conflict", parent_id=parent.id)
            if self._owned_steps_content is None:
                raise owned_steps.OwnedStepsError("owned_steps_content_unavailable", parent_id=parent.id)
            verification_bytes = b""
            for reference in (result.reviewed_result, result.verification):
                content = await self._owned_steps_content.read(reference.content_hash)
                if (
                    type(content) is not bytes or len(content) != reference.size_bytes
                    or owned_steps.owned_digest(content) != reference.content_hash
                ):
                    raise owned_steps.OwnedStepsError("owned_steps_content_conflict", parent_id=parent.id)
                if reference == result.verification:
                    verification_bytes = content
            verification = owned_steps.owned_json_loads(verification_bytes.decode("utf-8"))
            if (
                type(verification) is not dict or type(verification.get("accepted")) is not bool
                or verification["accepted"] != result.accepted
                or verification.get("parent_id") != parent.id
                or verification.get("work_item_id") != child.id
                or verification.get("thread_id") != control.thread_id
                or verification.get("producer_agent_id") != row.assignee_id
                or len(verification_bytes) > _MAX_WORK_ITEM_VERIFICATION_BYTES
            ):
                raise owned_steps.OwnedStepsError("owned_steps_review_conflict", parent_id=parent.id)
            await self._db.execute(
                "UPDATE work_items SET verification = ?, updated_at = ? WHERE id = ?",
                (verification_bytes.decode("utf-8"), now, child.id),
            )
            updates.update(
                reviewed_result=await self._write_owned_evidence(result),
                review_accepted=result.accepted, permit_state="terminal",
            )
            todo.update(status="done" if result.accepted else "rejected", confirmed_by=result.reviewer_id)
            receipt = "reviewed"
        elif isinstance(command, owned_steps.ReassignOwnedStepCommand):
            if (
                row.permit_state != "unstarted" or row.permit is not None
                or child.status not in (self.work_type_registry.get_initial_status(child.work_type), "scheduled")
                or child.actual_tokens or child.verification
                or any(key.startswith(("crew_execution", "crew_verification")) for key in child.metadata)
                or (booking is not None and booking.status != "scheduled")
            ):
                raise owned_steps.OwnedStepsError("owned_steps_reassignment_conflict", parent_id=parent.id)
            if command.assignee_id == row.assignee_id:
                return False, row, receipt, None
            resource = self._resolve_pull_resource(command.assignee_id, "assign", False)
            owner_booking_free = grant.role == "owner" and booking is None
            if (
                (resource is None and not owner_booking_free)
                or (
                    resource is not None
                    and (
                        not self._check_eligibility(resource, child)
                        or not await self._requirements_allow(child, resource)
                    )
                )
                or (booking is not None and not await self._has_booking_capacity(resource))
            ):
                raise owned_steps.OwnedStepsError("owned_steps_assignment_ineligible", parent_id=parent.id)
            if booking is not None:
                cancelled = await self._cancel_booking(booking, binding=binding)
                replacement = dataclasses.replace(
                    booking, id=uuid.uuid4().hex[:12], resource_id=resource.resource_id, start_time=now,
                )
                await self._db.execute(
                    "INSERT INTO bookings (id,resource_id,work_item_id,requirement_id,status,start_time,"
                    "end_time,actual_start,actual_end,total_tokens_consumed) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (replacement.id, replacement.resource_id, replacement.work_item_id, replacement.requirement_id,
                     replacement.status, replacement.start_time, replacement.end_time, replacement.actual_start,
                     replacement.actual_end, replacement.total_tokens_consumed),
                )
                await self._record_timestamp(replacement.id, "scheduled", "owned_assignment", binding=binding)
                updates["booking_id"] = replacement.id
                booking_events.append((EventType.BOOKING_CANCELLED, {"booking": cancelled.to_dict()}))
            merged_metadata = dict(child.metadata)
            merged_metadata.update(command.metadata_patch)
            metadata_bytes = owned_steps.owned_json_bytes(merged_metadata)
            if len(metadata_bytes) > _MAX_WORK_ITEM_METADATA_BYTES:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_assignment_invalid",
                    parent_id=parent.id,
                )
            await self._db.execute(
                "UPDATE work_items SET assigned_to = ?, metadata = ?, updated_at = ? WHERE id = ?",
                (
                    command.assignee_id,
                    metadata_bytes.decode("utf-8"),
                    now,
                    child.id,
                ),
            )
            todo["assigned_to"] = command.assignee_id
            updates.update(assignee_id=command.assignee_id, assignment_epoch=row.assignment_epoch + 1)
        elif isinstance(command, owned_steps.AccountingOwnedStepCommand):
            if (
                booking is None or booking.id != command.booking_id or booking.resource_id != command.resource_id
                or row.permit_state != "started" or row.permit is None
            ):
                raise owned_steps.OwnedStepsError("owned_steps_booking_conflict", parent_id=parent.id)
            old, target = ("active", "on_break") if command.kind == "pause_accounting" else ("on_break", "active")
            if booking.status == target:
                return False, row, receipt, None
            if booking.status != old:
                raise owned_steps.OwnedStepsError("owned_steps_booking_conflict", parent_id=parent.id)
            if target == "active":
                resource = self._resolve_pull_resource(booking.resource_id, "resume", False)
                if (
                    resource is None or not self._check_eligibility(resource, child)
                    or not await self._requirements_allow(child, resource)
                    or not await self._has_booking_capacity(resource)
                ):
                    raise owned_steps.OwnedStepsError("owned_steps_booking_capacity", parent_id=parent.id)
            await self._db.execute("UPDATE bookings SET status = ? WHERE id = ?", (target, booking.id))
            await self._record_timestamp(booking.id, target, "owned_accounting", binding=binding)
        elif isinstance(
            command,
            (
                owned_steps.CancelOwnedStepCommand,
                owned_steps.AbandonOwnedStepCommand,
            ),
        ):
            if (
                isinstance(command, owned_steps.AbandonOwnedStepCommand)
                and row.permit_state != "interrupted"
            ):
                raise owned_steps.OwnedStepsError(
                    "owned_steps_abandon_conflict",
                    parent_id=parent.id,
                )
            if isinstance(command, owned_steps.AbandonOwnedStepCommand):
                command = owned_steps.CancelOwnedStepCommand()
            if grant.role == "ttl":
                expiring = parent if command.expired_item_id == parent.id else child
                if (
                    command.expired_item_id != expiring.id or command.observed_at is None
                    or command.observed_at > now or expiring.ttl_seconds is None
                    or expiring.status in _TERMINAL_STATUSES
                    or expiring.created_at + expiring.ttl_seconds >= command.observed_at
                ):
                    raise owned_steps.OwnedStepsError("owned_steps_ttl_conflict", parent_id=parent.id)
            elif command.expired_item_id is not None or command.observed_at is not None:
                raise owned_steps.OwnedStepsError("owned_steps_authority_denied", parent_id=parent.id)
            if row.permit_state in ("revoked", "terminal") or row.reviewed_result is not None:
                return False, row, "cancelled", None
            if (
                child.status not in _TERMINAL_STATUSES and booking is None
                and not self._validate_work_item_status_transition(child, "cancelled")
            ):
                raise owned_steps.OwnedStepsError("owned_steps_execution_transition", parent_id=parent.id)
            if booking is not None and booking.status in ("scheduled", "active", "on_break"):
                cancelled = await self._cancel_booking(booking, binding=binding)
                booking_events.append((EventType.BOOKING_CANCELLED, {"booking": cancelled.to_dict()}))
            if child.status not in _TERMINAL_STATUSES:
                await self._db.execute(
                    "UPDATE work_items SET status = 'cancelled', updated_at = ? WHERE id = ?", (now, child.id),
                )
            updates.update(permit_state="revoked", assignment_epoch=row.assignment_epoch + 1)
            receipt = "cancelled"
        else:
            raise owned_steps.OwnedStepsError("owned_steps_command_invalid", parent_id=parent.id)
        todo_json = owned_steps.owned_json_bytes(todo).decode("utf-8")
        updates.update(todo_json=todo_json, digest=owned_steps.owned_digest(todo_json))
        return True, row.model_copy(update=updates), receipt, permit

    async def create_work_item(self, **kwargs: Any) -> WorkItem:
        """Create and persist a new work item."""
        if "steps_control" in kwargs:
            raise owned_steps.OwnedStepsError("owned_steps_control_reserved")
        if kwargs.get("work_type", "task") == "crew_session":
            raise ValueError("crew_session_write_reserved")
        _reject_reserved_metadata(kwargs.get("metadata"))
        now = time.time()
        kwargs.setdefault("created_at", now)
        kwargs.setdefault("updated_at", now)
        # AD-498: Set initial status from work type registry if not explicitly provided
        work_type = kwargs.get("work_type", "task")
        if "status" not in kwargs:
            kwargs["status"] = self.work_type_registry.get_initial_status(work_type)
        item = WorkItem(**kwargs)
        return await self._insert_work_item(item)

    async def _insert_work_item(self, item: WorkItem) -> WorkItem:
        _reject_reserved_metadata(item.metadata)
        if self._db:
            async with self._booking_transaction():
                try:
                    if item.parent_id is not None:
                        await self._guard_owned_write(item.parent_id)
                    await self._db.execute(
                        """INSERT INTO work_items (
                            id, title, description, work_type, status, priority,
                            parent_id, depends_on, assigned_to, created_by,
                            created_at, updated_at, due_at, estimated_tokens,
                            actual_tokens, trust_requirement, required_capabilities,
                            tags, metadata, steps, verification, schedule,
                            ttl_seconds, template_id, project_id
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                            item.template_id, item.project_id,
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
                except BaseException:
                    try:
                        await self._db.execute("ROLLBACK")
                    except Exception:
                        pass
                    raise
        await self._refresh_snapshot_cache()
        self._emit(
            EventType.WORK_ITEM_CREATED,
            {"work_item": self._event_work_item_projection(item)},
        )
        return item

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        """Fetch a single work item by ID."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            f"SELECT {_WORK_ITEM_PUBLIC_COLUMNS} FROM work_items WHERE id = ?", (work_item_id,),
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
        project_id: str | None = None,
        include_scaffold: bool = False,
    ) -> list[WorkItem]:
        """List work items with optional filters. Ordered by priority ASC, created_at DESC.

        AD-1271: a row carrying ``metadata.ui_scaffold`` is a UI BINDING, not a
        unit of work, and is excluded by default. BF-735's 36 ``Room workspace``
        rows exist only because a chat thread needs a ``task_id`` for its FILES
        rail to bind to; nothing was ever meant to complete them, and while they
        sat in ``open`` the ship told the Captain it had 36 open work items in
        THREE separate narrations (``captains_log``, ``plan_of_day``,
        ``ship_state_snapshot``) on top of the board and the Quartermaster's
        sweep.

        The exclusion is here rather than in any one of those consumers for
        exactly the reason #1194 gives against a per-view filter: "every
        consumer then has to know better". One default at the store makes all of
        them honest at once, and the Quartermaster inherits it, which retires
        the ``unassigned_dispatchable`` reachability in ``work_reconciler``
        rather than relying on a ``dispatchable_tags`` list that one line could
        widen.

        Pass ``include_scaffold=True`` to see them anyway -- a migration or an
        operator asking "what is actually in there" needs the unfiltered view.
        """
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
        if project_id is not None:
            # AD-1176: filtered in SQL alongside the other scalar columns, not
            # in memory like ``tags`` — the LIMIT must apply after the filter.
            conditions.append("project_id = ?")
            params.append(project_id)
        if priority is not None:
            conditions.append("priority = ?")
            params.append(priority)
        if not include_scaffold:
            # AD-1271: in SQL, for the same reason as ``project_id`` — filtering
            # after the fetch would let scaffolding consume the LIMIT and hide
            # real work behind it.
            conditions.append(_SCAFFOLD_EXCLUSION_SQL.replace("item.", ""))
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

    async def list_ws_visible_work_items(
        self,
        *,
        limit: int,
    ) -> list[WorkItem]:
        """Return at most ``limit + 1`` WebSocket-visible rows as an overflow sentinel."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("ws_visible_work_items_limit_invalid")
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT item.* FROM work_items AS item "
            "WHERE item.work_type != ? "
            "AND NOT EXISTS ("
            "SELECT 1 FROM work_items AS parent "
            "WHERE parent.id = item.parent_id AND parent.work_type = ?"
            ") "
            # AD-1271: the board's live source. Review measured scaffolding
            # still reaching it after ``list_work_items`` was filtered -- this
            # lister has its own SQL and does not go through it, so a per-method
            # fix here is exactly the "every consumer has to know better" shape
            # the store-level default exists to avoid. There is deliberately no
            # override: nothing renders a UI binding on a work board.
            f"AND {_SCAFFOLD_EXCLUSION_SQL} "
            "ORDER BY item.priority ASC, item.created_at DESC, item.id ASC "
            "LIMIT ?",
            ("crew_session", "crew_session", limit + 1),
        )
        rows = await cursor.fetchall()
        return [self._row_to_work_item(row) for row in rows]

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

    async def list_owned_legacy_recovery_candidates(
        self,
        *,
        limit: int,
    ) -> list[WorkItem]:
        """Return bounded managed legacy parents that still require owner work."""
        if type(limit) is not int or not 1 <= limit <= 1_000:
            raise ValueError("owned_steps_recovery_scan_limit_invalid")
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM work_items WHERE work_type != ? "
            "AND steps_control IS NOT NULL "
            "AND status NOT IN ('done', 'failed', 'cancelled') "
            "ORDER BY created_at ASC, id ASC LIMIT ?",
            ("crew_session", limit + 1),
        )
        rows = await cursor.fetchall()
        if len(rows) > limit:
            raise ValueError("owned_steps_recovery_scan_overflow")
        result: list[WorkItem] = []
        for row in rows:
            control = owned_steps.parse_owned_control(row["steps_control"])
            if control.owner_kind == "legacy":
                result.append(self._row_to_work_item(row))
        return result

    async def list_crew_session_ingress_candidates(
        self,
        *,
        limit: int,
    ) -> list[WorkItem]:
        """Return one complete bounded oldest-first nonterminal ingress scan."""
        if type(limit) is not int or not 1 <= limit <= 1_000:
            raise ValueError("crew_session_ingress_scan_limit_invalid")
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM work_items WHERE work_type = ? "
            "AND status IN (?, ?, ?, ?) "
            "ORDER BY created_at ASC, id ASC LIMIT ?",
            (
                "crew_session",
                "open",
                "in_progress",
                "review",
                "blocked",
                limit + 1,
            ),
        )
        rows = await cursor.fetchall()
        if len(rows) > limit:
            raise ValueError("crew_session_ingress_scan_overflow")
        return [self._row_to_work_item(row) for row in rows]

    async def list_crew_session_provisioning_candidates(
        self,
        *,
        limit: int,
    ) -> list[WorkItem]:
        """Return one complete bounded oldest-first provisioning-marker scan."""
        if type(limit) is not int or not 1 <= limit <= 1_000:
            raise ValueError("crew_provisioning_scan_limit_invalid")
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM work_items WHERE work_type = ? "
            "AND json_type(metadata, '$.crew_provisioning') IS NOT NULL "
            "ORDER BY created_at ASC, id ASC LIMIT ?",
            ("crew_session", limit + 1),
        )
        rows = await cursor.fetchall()
        if len(rows) > limit:
            raise ValueError("crew_provisioning_scan_overflow")
        return [self._row_to_work_item(row) for row in rows]

    async def clear_crew_session_provisioning(
        self,
        parent_id: str,
        *,
        expected_marker: dict[str, Any],
        expected_session: dict[str, Any],
        expected_recovery: dict[str, Any],
        owned_binding: owned_steps.OwnedStoreBinding | None = None,
    ) -> WorkItem | None:
        """Remove only an exact installed provisioning marker sibling."""
        if (
            type(parent_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(parent_id) is None
            or any(
                type(value) is not dict
                for value in (expected_marker, expected_session, expected_recovery)
            )
        ):
            raise ValueError("crew_provisioning_clear_invalid")
        for value in (expected_marker, expected_session, expected_recovery):
            _compact_exact_json_bytes(value, error="crew_provisioning_clear_invalid")
        if not self._db:
            return None
        async with self._booking_transaction():
            item = await self.get_work_item(parent_id)
            owned_write = await self._prepare_owned_store_write(
                parent_id,
                owned_binding,
                "metadata",
                {
                    "work_item_id": parent_id,
                    "operation": "clear_crew_session_provisioning",
                    "expected_marker": expected_marker,
                    "expected_session": expected_session,
                    "expected_recovery": expected_recovery,
                },
            )
            if item is None or item.work_type != "crew_session":
                return None
            metadata = dict(item.metadata or {})
            session_state = expected_session.get("state")
            status_by_state = {
                "discussing": "open",
                "executing": "in_progress",
                "verifying": "review",
                "blocked_needs_captain": "blocked",
                "done": "done",
                "failed": "failed",
            }
            facilitator_id = expected_session.get("facilitator_id")
            if (
                type(session_state) is not str
                or status_by_state.get(session_state) != item.status
                or type(facilitator_id) is not str
                or item.assigned_to != facilitator_id
            ):
                raise ValueError("crew_provisioning_clear_conflict")
            if not all(
                key in metadata and _json_values_exactly_equal(metadata[key], value)
                for key, value in (
                    ("crew_provisioning", expected_marker),
                    ("crew_session", expected_session),
                    ("crew_recovery", expected_recovery),
                )
            ):
                raise ValueError("crew_provisioning_clear_conflict")
            metadata.pop("crew_provisioning")
            serialized = _compact_exact_json_bytes(
                metadata,
                error="crew_provisioning_clear_invalid",
            )
            if len(serialized) > _MAX_WORK_ITEM_METADATA_BYTES:
                raise ValueError("work_item_metadata_too_large")
            try:
                await self._db.execute(
                    "UPDATE work_items SET metadata = ?, updated_at = ? WHERE id = ?",
                    (serialized.decode("utf-8"), time.time(), parent_id),
                )
                await self._finish_owned_store_write(owned_write)
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            updated = await self.get_work_item(parent_id)
        await self._refresh_snapshot_cache()
        self._emit(
            EventType.WORK_ITEM_UPDATED,
            {"work_item": self._event_work_item_projection(updated)},
        )
        return updated

    async def delete_untouched_crew_session_provisioning(
        self,
        parent_id: str,
        *,
        expected_marker: dict[str, Any],
        expected_assigned_to: str,
    ) -> bool:
        """Delete only an exact pre-session marker parent with no child work."""
        if (
            type(parent_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(parent_id) is None
            or type(expected_marker) is not dict
            or type(expected_assigned_to) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(expected_assigned_to) is None
        ):
            raise ValueError("crew_provisioning_delete_invalid")
        _compact_exact_json_bytes(
            expected_marker,
            error="crew_provisioning_delete_invalid",
        )
        if not self._db:
            return False
        async with self._booking_transaction():
            item = await self.get_work_item(parent_id)
            await self._guard_owned_write(parent_id)
            if item is None:
                return False
            child_cursor = await self._db.execute(
                "SELECT 1 FROM work_items WHERE parent_id = ? LIMIT 1",
                (parent_id,),
            )
            has_child = await child_cursor.fetchone() is not None
            booking_cursor = await self._db.execute(
                "SELECT 1 FROM bookings WHERE work_item_id = ? LIMIT 1",
                (parent_id,),
            )
            has_booking = await booking_cursor.fetchone() is not None
            requirement_cursor = await self._db.execute(
                "SELECT duration_estimate_seconds, from_date, to_date, "
                "required_characteristics, min_trust, department_constraint, "
                "priority, resource_preference, fulfilled "
                "FROM resource_requirements WHERE work_item_id = ?",
                (parent_id,),
            )
            requirement_rows = await requirement_cursor.fetchall()
            requirement_untouched = (
                len(requirement_rows) == 1
                and requirement_rows[0]["duration_estimate_seconds"] is None
                and requirement_rows[0]["from_date"] is None
                and requirement_rows[0]["to_date"] is None
                and requirement_rows[0]["required_characteristics"] == "[]"
                and requirement_rows[0]["min_trust"] == 0.0
                and requirement_rows[0]["department_constraint"] is None
                and requirement_rows[0]["priority"] == 3
                and requirement_rows[0]["resource_preference"] == "{}"
                and requirement_rows[0]["fulfilled"] == 0
            )
            untouched = (
                item.work_type == "crew_session"
                and item.status == "draft"
                and item.title == str(expected_marker.get("goal", ""))[:200]
                and item.description == expected_marker.get("goal")
                and item.priority == 3
                and item.assigned_to == expected_assigned_to
                and item.created_by == expected_marker.get("created_by")
                and item.parent_id is None
                and item.depends_on == []
                and item.due_at is None
                and item.estimated_tokens is None
                and item.actual_tokens == 0
                and item.trust_requirement == 0.0
                and item.required_capabilities == []
                and item.tags == []
                and item.steps == []
                and item.verification == {}
                and item.schedule == {}
                and item.ttl_seconds is None
                and item.template_id is None
                and not has_child
                and not has_booking
                and requirement_untouched
                and _json_values_exactly_equal(
                    item.metadata,
                    {"crew_provisioning": expected_marker},
                )
            )
            if not untouched:
                return False
            try:
                await self._db.execute(
                    "DELETE FROM resource_requirements WHERE work_item_id = ?",
                    (parent_id,),
                )
                await self._db.execute(
                    "DELETE FROM work_items WHERE id = ?",
                    (parent_id,),
                )
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        await self._refresh_snapshot_cache()
        return True

    async def fail_crew_session_provisioning(
        self,
        parent_id: str,
        *,
        expected_marker: dict[str, Any],
        error_code: str,
    ) -> WorkItem | None:
        """Mark one exact pre-session provisioning authority irreparable."""
        if (
            type(parent_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(parent_id) is None
            or type(expected_marker) is not dict
            or type(error_code) is not str
            or _CREW_PROVISIONING_ERROR_RE.fullmatch(error_code) is None
        ):
            raise ValueError("crew_provisioning_failure_invalid")
        _compact_exact_json_bytes(
            expected_marker,
            error="crew_provisioning_failure_invalid",
        )
        if not self._db:
            return None
        failed_marker = dict(expected_marker)
        failed_marker.update({"phase": "failed", "last_error_code": error_code})
        _compact_exact_json_bytes(
            failed_marker,
            error="crew_provisioning_failure_invalid",
        )
        async with self._booking_transaction():
            item = await self.get_work_item(parent_id)
            await self._guard_owned_write(parent_id)
            if item is None or item.work_type != "crew_session":
                return None
            metadata = dict(item.metadata or {})
            if (
                item.status != "draft"
                or item.assigned_to != expected_marker.get("facilitator_id")
                or not _json_values_exactly_equal(
                    metadata.get("crew_provisioning"),
                    expected_marker,
                )
            ):
                raise ValueError("crew_provisioning_failure_conflict")
            metadata["crew_provisioning"] = failed_marker
            serialized = _compact_exact_json_bytes(
                metadata,
                error="crew_provisioning_failure_invalid",
            )
            if len(serialized) > _MAX_WORK_ITEM_METADATA_BYTES:
                raise ValueError("work_item_metadata_too_large")
            try:
                await self._db.execute(
                    "UPDATE work_items SET metadata = ?, updated_at = ? WHERE id = ?",
                    (serialized.decode("utf-8"), time.time(), parent_id),
                )
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            updated = await self.get_work_item(parent_id)
        await self._refresh_snapshot_cache()
        self._emit(
            EventType.WORK_ITEM_UPDATED,
            {"work_item": self._event_work_item_projection(updated)},
        )
        return updated

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
        steps_seed: owned_steps.OwnedStepsSeed | None = None,
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
        _reject_reserved_metadata(detached_patch)
        for child in children:
            _reject_reserved_metadata(child.metadata)
        seed_request_digest = owned_steps.owned_digest(_compact_exact_json_bytes({
            "expected_metadata": detached_expected, "patch": detached_patch,
            "status": expected_status, "assignee": expected_assigned_to,
            "children": [json.loads(json.dumps(dataclasses.asdict(child))) for child in children],
        }, error="owned_steps_seed_invalid")) if steps_seed is not None else ""
        created: list[WorkItem] = []
        updated_parent: WorkItem | None = None
        async with self._work_item_row_write_lock:
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                replay = await self._replay_owned_seed(parent_id, steps_seed, seed_request_digest)
                if replay is not None:
                    await self._db.commit()
                    return replay
                parent = await self.get_work_item(parent_id)
                if parent is None:
                    raise ValueError("work_item_plan_parent_not_found")
                await self._guard_owned_write(parent_id)
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
                if steps_seed is not None:
                    await self._seed_owned_steps(
                        dataclasses.replace(parent, metadata=merged_metadata),
                        tuple(created), steps_seed, seed_request_digest,
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
            {"work_item": self._event_work_item_projection(updated_parent)},
        )
        for child in created:
            self._emit(
                EventType.WORK_ITEM_CREATED,
                {"work_item": self._event_work_item_projection(child)},
            )
        return updated_parent, tuple(created)

    async def adopt_child_plan_with_parent_metadata(
        self,
        parent_id: str,
        *,
        expected_parent_metadata: dict[str, Any],
        expected_status: str,
        expected_assigned_to: str | None,
        parent_patch: dict[str, Any],
        expected_children: tuple[WorkItem, ...],
        source: str = "crew_session_plan_adoption",
        steps_seed: owned_steps.OwnedStepsSeed | None = None,
    ) -> WorkItem:
        """Patch one parent only after an exact lock-held child snapshot proof."""
        if (
            type(parent_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(parent_id) is None
            or type(expected_parent_metadata) is not dict
            or type(expected_status) is not str
            or not expected_status
            or not (
                (type(expected_assigned_to) is str
                 and _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(expected_assigned_to) is not None)
                or (expected_assigned_to is None and type(steps_seed) is owned_steps.OwnedStepsSeed
                    and steps_seed.plan.owner_kind == "legacy")
            )
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
        _reject_reserved_metadata(detached_patch)
        detached_children = _detach_plan_adoption_children(
            parent_id,
            expected_children,
        )
        seed_request_digest = owned_steps.owned_digest(_compact_exact_json_bytes({
            "expected_metadata": detached_expected, "patch": detached_patch,
            "status": expected_status, "assignee": expected_assigned_to,
            "children": list(detached_children),
        }, error="owned_steps_seed_invalid")) if steps_seed is not None else ""
        if not self._db:
            raise ValueError("work_item_plan_adoption_unavailable")

        updated_parent: WorkItem | None = None
        async with self._work_item_row_write_lock:
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                replay = await self._replay_owned_seed(parent_id, steps_seed, seed_request_digest)
                if replay is not None:
                    await self._db.commit()
                    return replay[0]
                parent = await self.get_work_item(parent_id)
                if parent is None:
                    raise ValueError("work_item_plan_parent_not_found")
                await self._guard_owned_write(parent_id)
                if (
                    (parent.work_type != "crew_session" and not (
                        type(steps_seed) is owned_steps.OwnedStepsSeed
                        and steps_seed.plan.owner_kind == "legacy"
                    ))
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
                if steps_seed is not None:
                    await self._seed_owned_steps(
                        dataclasses.replace(parent, metadata=merged_metadata),
                        live_children, steps_seed, seed_request_digest,
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
            {
                "work_item": self._event_work_item_projection(updated_parent),
                "source": source,
            },
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
        async with self._booking_transaction():
            item = await self.get_work_item(work_item_id)
            await self._guard_owned_write(work_item_id)
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
            {"work_item": self._event_work_item_projection(updated)},
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
        if "steps_control" in updates:
            raise owned_steps.OwnedStepsError("owned_steps_control_reserved", parent_id=work_item_id)
        if any(key not in WorkItem.__dataclass_fields__ for key in updates):
            raise ValueError("work_item_update_field_invalid")
        if not self._db:
            return None
        if updates.get("work_type") == "crew_session":
            raise ValueError("crew_session_write_reserved")
        if "metadata" in updates:
            _reject_reserved_metadata(updates.get("metadata"))
        async with self._booking_transaction():
            item = await self.get_work_item(work_item_id)
            if not item:
                return None
            if set(updates) == {"metadata"}:
                metadata = updates["metadata"]
                if type(metadata) is str:
                    metadata = owned_steps.owned_json_loads(metadata)
                await self._guard_owned_write(work_item_id, metadata=metadata, replacement=True)
            else:
                await self._guard_owned_write(work_item_id)
            if updates.get("parent_id") is not None:
                await self._guard_owned_write(updates["parent_id"])
            if item.work_type == "crew_session":
                raise ValueError("crew_session_write_reserved")
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
            updated = await self.get_work_item(work_item_id)
        await self._refresh_snapshot_cache()
        self._emit(
            EventType.WORK_ITEM_UPDATED,
            {"work_item": self._event_work_item_projection(updated)},
        )
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
        if self._db is not None:
            async with self._booking_transaction():
                await self._guard_owned_write(work_item_id)
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
        if self._db is not None:
            async with self._booking_transaction():
                await self._guard_owned_write(work_item_id)
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
        crew_session_delivery: CrewSessionDeliveryRecord | None = None,
        retry_barrier: WorkItemRetryBarrier | None = None,
        source: str = "system",
        owned_binding: owned_steps.OwnedStoreBinding | None = None,
    ) -> WorkItem | None:
        """Atomically shallow-merge top-level metadata for this store instance."""
        if retry_barrier is not None:
            if type(retry_barrier) is not WorkItemRetryBarrier:
                raise ValueError("work_item_retry_barrier_invalid")
            patch = json.loads(_bounded_child_snapshot_bytes(
                patch, error="work_item_retry_barrier_invalid", seen_containers=set(),
            ))
            if expected is not None:
                expected = json.loads(_bounded_child_snapshot_bytes(
                    expected,
                    error="work_item_retry_barrier_invalid",
                    seen_containers=set(),
                ))
            self._validate_retry_merge(
                work_item_id, retry_barrier, patch, new_status, source,
                actual_tokens_delta, crew_session_delivery,
            )
        if not self._db:
            if retry_barrier is not None:
                raise WorkItemRetryConflict()
            return None
        if type(patch) is not dict or any(type(key) is not str for key in patch):
            raise ValueError("work_item_metadata_patch_invalid")
        _reject_reserved_metadata(patch)
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
        async with self._work_item_row_write_lock, self._retry_barrier_transaction(
            work_item_id, retry_barrier,
        ):
            item = await self.get_work_item(work_item_id)
            if item is None:
                return None
            owned_write = None
            if owned_binding is not None:
                owned_write = await self._prepare_owned_store_write(
                    work_item_id, owned_binding, "metadata",
                    {"work_item_id": work_item_id, "patch": patch, "new_status": new_status,
                     "actual_tokens_delta": actual_tokens_delta},
                )
            elif new_status is not None or actual_tokens_delta or crew_session_delivery is not None or retry_barrier is not None:
                await self._guard_owned_write(work_item_id)
            else:
                await self._guard_owned_write(work_item_id, metadata=patch)
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
            delivery_payload = _detach_crew_session_delivery(
                crew_session_delivery,
                session_id=work_item_id,
                contract_payload=merged.get("crew_session"),
            )
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
            await _insert_crew_session_delivery(self._db, delivery_payload)
            await self._finish_owned_store_write(owned_write)

            updated = await self.get_work_item(work_item_id)
        await self._refresh_snapshot_cache()
        self._emit(
            EventType.WORK_ITEM_UPDATED,
            {"work_item": self._event_work_item_projection(updated)},
        )
        if status_changed:
            self._emit(EventType.WORK_ITEM_STATUS_CHANGED, {
                "work_item": self._event_work_item_projection(updated),
                "old_status": old_status,
                "new_status": new_status,
                "source": source,
            })
        return updated

    def _validate_retry_merge(
        self,
        work_item_id: str,
        barrier: WorkItemRetryBarrier,
        patch: dict[str, Any],
        new_status: str | None,
        source: str,
        actual_tokens_delta: int,
        delivery: CrewSessionDeliveryRecord | None,
    ) -> None:
        error = "work_item_retry_barrier_invalid"
        if (
            type(work_item_id) is not str
            or work_item_id != barrier.parent_id
            or type(patch) is not dict
            or set(patch) != {"crew_session", "crew_recovery"}
            or type(actual_tokens_delta) is not int
            or actual_tokens_delta != 0
            or type(source) is not str
            or type(new_status) is not str
        ):
            raise ValueError(error)
        metadata = json.loads(barrier.parent_metadata)
        current = metadata.get("crew_session")
        recovery = metadata.get("crew_recovery")
        target = patch["crew_session"]
        checkpoint = patch["crew_recovery"]
        if any(type(value) is not dict for value in (current, recovery, target, checkpoint)):
            raise ValueError(error)
        if type(recovery.get("phase")) is not str:
            raise ValueError(error)
        phase_pair = {
            "planned": ("discussing", "open"),
            "executing": ("executing", "in_progress"),
        }.get(recovery.get("phase"))
        if phase_pair is None or "crew_provisioning" in metadata:
            raise ValueError(error)
        active_state, active_status = phase_pair
        mutable_session_keys = {
            "revision", "state", "previous_state", "transitioned_at",
            "blocked_reason", "blocked_since", "blocked_duration_seconds",
            "owner_ids", "duplicate_resume_count",
        } if source == "crew_session_ingress_resume" else {
            "revision", "state", "previous_state", "transitioned_at",
            "blocked_reason", "blocked_since", "last_result_summary", "first_result_at",
        }
        mutable_recovery_keys = {
            "retry_count", "next_attempt_at", "last_error_code", "interrupted_child_ids",
        } if source == "crew_session_ingress_resume" else {"last_error_code"}
        if (
            set(current) != set(target)
            or set(recovery) != set(checkpoint)
            or any(
                not _json_values_exactly_equal(value, target[key])
                for key, value in current.items() if key not in mutable_session_keys
            )
            or any(
                not _json_values_exactly_equal(value, checkpoint[key])
                for key, value in recovery.items() if key not in mutable_recovery_keys
            )
            or current.get("task_id") != work_item_id
            or current.get("facilitator_id") != barrier.parent_assigned_to
            or type(current.get("revision")) is not int
            or type(target.get("revision")) is not int
            or target["revision"] != current["revision"] + 1
            or checkpoint.get("phase") != recovery.get("phase")
            or recovery.get("plan") is None
            or not _json_values_exactly_equal(recovery.get("plan"), checkpoint.get("plan"))
            or any(
                not _json_values_exactly_equal(current.get(key), target.get(key))
                for key in ("task_id", "thread_id", "facilitator_id", "goal", "origin", "originator_id")
            )
        ):
            raise ValueError(error)
        blocked = (
            barrier.parent_status == "blocked"
            and current.get("state") == "blocked_needs_captain"
            and current.get("previous_state") == active_state
            and current.get("blocked_reason") == "crew_worker_unavailable"
            and recovery.get("last_error_code") == "crew_worker_unavailable"
        )
        if source == "crew_session_ingress_resume":
            if (
                not blocked
                or barrier.mode != "untouched"
                or new_status != active_status
                or target.get("state") != active_state
                or target.get("previous_state") != "blocked_needs_captain"
                or target.get("blocked_reason") is not None
                or checkpoint.get("last_error_code") is not None
                or recovery.get("interrupted_child_ids") != []
                or delivery is not None
            ):
                raise ValueError(error)
        elif source == "crew_session_retry_failure":
            reason = target.get("blocked_reason")
            if (
                not (blocked or (barrier.parent_status == active_status and current.get("state") == active_state))
                or new_status != "blocked"
                or target.get("state") != "blocked_needs_captain"
                or target.get("previous_state") != active_state
                or type(reason) is not str
                or re.fullmatch(r"[a-z0-9][a-z0-9_]{0,127}", reason) is None
                or not (reason in {"crew_worker_unavailable", "crew_worker_identity_lost"} or reason.startswith("crew_recovery_"))
                or checkpoint.get("last_error_code") != reason
                or (reason == "crew_worker_unavailable" and barrier.mode != "untouched")
                or (reason != "crew_worker_unavailable" and barrier.mode != "observed")
            ):
                raise ValueError(error)
        else:
            raise ValueError(error)

    @asynccontextmanager
    async def _retry_barrier_transaction(
        self,
        work_item_id: str,
        barrier: WorkItemRetryBarrier | None,
    ) -> AsyncIterator[None]:
        if barrier is None:
            assert self._db is not None
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                yield
                await self._db.commit()
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    logger.error(
                        "Workforce metadata rollback failed; durable state is uncertain "
                        "and the original failure is propagated",
                    )
                raise
            return
        assert self._db is not None
        try:
            await self._db.execute("BEGIN IMMEDIATE")
            parent = await self.get_work_item(work_item_id)
            if (
                parent is None
                or parent.work_type != barrier.parent_work_type
                or parent.status != barrier.parent_status
                or not _json_values_exactly_equal(parent.assigned_to, barrier.parent_assigned_to)
                or not _json_values_exactly_equal(parent.metadata, json.loads(barrier.parent_metadata))
            ):
                raise WorkItemRetryConflict()
            recovery = parent.metadata.get("crew_recovery")
            plan = recovery.get("plan") if type(recovery) is dict else None
            try:
                membership = await self.get_owned_crew_children(
                    work_item_id,
                    plan.get("plan_hash") if type(plan) is dict else None,
                )
                children = sorted(membership.active, key=lambda child: child.id)
            except owned_steps.OwnedStepsError as exc:
                if exc.code != "owned_steps_not_managed":
                    raise
                cursor = await self._db.execute(
                    "SELECT * FROM work_items WHERE parent_id = ? ORDER BY id ASC LIMIT ?",
                    (work_item_id, _MAX_WORK_ITEM_DIRECT_CHILDREN + 1),
                )
                children = [self._row_to_work_item(row) for row in await cursor.fetchall()]
            if len(children) != len(barrier.children):
                raise WorkItemRetryConflict()
            for child, snapshot in zip(children, barrier.children):
                if not _json_values_exactly_equal(_work_item_child_snapshot(child), json.loads(snapshot)):
                    raise WorkItemRetryConflict()
                if barrier.mode == "untouched":
                    definition = self.work_type_registry.get(child.work_type)
                    if (
                        definition is None
                        or child.status != definition.initial_status
                        or not _json_values_exactly_equal(child.verification, {})
                        or any(key in child.metadata for key in (
                            "crew_execution", "crew_execution_output", "crew_verification_recovery",
                            CREW_EXECUTION_TOKEN_USAGE_KEY,
                        ))
                    ):
                        raise WorkItemRetryConflict()
            yield
            await self._db.commit()
        except BaseException:
            try:
                await self._db.execute("ROLLBACK")
            except Exception:
                pass
            raise

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
        owned_binding: owned_steps.OwnedStoreBinding | None = None,
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

        async with self._booking_transaction():
            item = await self.get_work_item(work_item_id)
            owned_write = await self._prepare_owned_store_write(
                work_item_id, owned_binding, "verification",
                {"work_item_id": work_item_id, "verification": verification,
                 "metadata_patch": metadata_patch or {}, "actual_tokens_delta": actual_tokens_delta},
            )
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
                await self._finish_owned_store_write(owned_write)
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
            {"work_item": self._event_work_item_projection(updated)},
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
        crew_trust_effects: tuple[Any, ...] = (),
        crew_session_delivery: CrewSessionDeliveryRecord | None = None,
        source: str = "crew_session_verified_result",
        owned_binding: owned_steps.OwnedStoreBinding | None = None,
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
        contract_payload = detached_patch.get("crew_session")
        if type(contract_payload) is not dict:
            raise ValueError("crew_trust_outbox_invalid")
        effects = _detach_crew_trust_effects(
            crew_trust_effects,
            session_id=work_item_id,
            session_revision=contract_payload.get("revision"),
        )
        delivery_payload = _detach_crew_session_delivery(
            crew_session_delivery,
            session_id=work_item_id,
            contract_payload=contract_payload,
        )
        if not self._db:
            return None

        status_changed = False
        publication_changed = True
        old_status = expected_status
        updated: WorkItem | None = None
        async with self._work_item_row_write_lock:
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                item = await self.get_work_item(work_item_id)
                owned_write = await self._prepare_owned_store_write(
                    work_item_id,
                    owned_binding,
                    "steps_finalize",
                    {
                        "work_item_id": work_item_id,
                        "patch": detached_patch,
                        "new_status": new_status,
                        "expected_direct_children": list(detached_children),
                    },
                )
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

                if owned_write is not None:
                    membership = await self._get_owned_crew_children_locked(
                        work_item_id,
                        owned_write.snapshot.control,
                    )
                    live_children = tuple(
                        sorted(membership.active, key=lambda child: child.id)
                    )
                else:
                    cursor = await self._db.execute(
                        "SELECT * FROM work_items WHERE parent_id = ? "
                        "ORDER BY id ASC LIMIT ?",
                        (work_item_id, _MAX_WORK_ITEM_DIRECT_CHILDREN + 1),
                    )
                    rows = await cursor.fetchall()
                    live_children = tuple(
                        self._row_to_work_item(row) for row in rows
                    )
                if (
                    not live_children
                    or len(live_children) > _MAX_WORK_ITEM_DIRECT_CHILDREN
                    or len(live_children) != len(detached_children)
                ):
                    raise ValueError("work_item_child_barrier_conflict")
                for live, expected_child in zip(live_children, detached_children):
                    if not _json_values_exactly_equal(
                        _work_item_child_snapshot(live),
                        expected_child,
                    ):
                        raise ValueError("work_item_child_barrier_conflict")

                merged = dict(current)
                merged.update(detached_patch)
                status_changed = new_status != item.status
                manual_pending = (
                    owned_write is not None
                    and bool(item.metadata.get("steps_gate_completion"))
                    and any(
                        row.kind == "manual"
                        and owned_steps.owned_json_loads(row.todo_json)["status"]
                        != "done"
                        for row in owned_write.snapshot.control.rows
                    )
                )
                if manual_pending:
                    publication_changed = not (
                        owned_write.snapshot.control.finalization
                        == owned_binding.finalize_receipt
                        and owned_write.snapshot.control.finalization_disposition
                        == "pending"
                        and owned_write.snapshot.control.mode
                        == "waiting_manual_gate"
                    )
                    await self._finish_owned_store_write(owned_write)
                    await self._db.commit()
                    updated = await self.get_work_item(work_item_id)
                    status_changed = False
                    old_status = item.status
                    continue_publication = False
                else:
                    continue_publication = True
                if not continue_publication:
                    pass
                elif status_changed and not self._validate_work_item_status_transition(
                    dataclasses.replace(item, metadata=merged),
                    new_status,
                ):
                    await self._db.execute("ROLLBACK")
                    return None
                if continue_publication:
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
                    await _insert_crew_trust_effects(self._db, effects)
                    await _insert_crew_session_delivery(self._db, delivery_payload)
                    await self._finish_owned_store_write(owned_write)
                    await self._db.commit()
                    updated = await self.get_work_item(work_item_id)
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise

        await self._refresh_snapshot_cache()
        if publication_changed:
            self._emit(
                EventType.WORK_ITEM_UPDATED,
                {"work_item": self._event_work_item_projection(updated)},
            )
        if status_changed:
            self._emit(EventType.WORK_ITEM_STATUS_CHANGED, {
                "work_item": self._event_work_item_projection(updated),
                "old_status": old_status,
                "new_status": new_status,
                "source": source,
            })
        return updated

    async def transition_crew_session_terminal_with_trust(
        self,
        work_item_id: str,
        patch: dict[str, Any],
        *,
        expected_metadata: dict[str, Any],
        expected_status: str,
        expected_assigned_to: str,
        new_status: str,
        crew_trust_effects: tuple[Any, ...],
        crew_session_delivery: CrewSessionDeliveryRecord,
        source: str = "crew_session_verified_failure",
    ) -> WorkItem | None:
        """Commit one failed CrewSession contract and its trust outbox together."""
        if (
            type(patch) is not dict
            or type(expected_metadata) is not dict
            or new_status != "failed"
            or any(
                type(value) is not str or not value
                for value in (
                    work_item_id,
                    expected_status,
                    expected_assigned_to,
                    source,
                )
            )
        ):
            raise ValueError("crew_trust_terminal_invalid")
        patch_bytes = _compact_exact_json_bytes(
            patch,
            error="crew_trust_terminal_invalid",
        )
        expected_bytes = _compact_exact_json_bytes(
            expected_metadata,
            error="crew_trust_terminal_invalid",
        )
        if (
            len(patch_bytes) > _MAX_WORK_ITEM_METADATA_BYTES
            or len(expected_bytes) > _MAX_WORK_ITEM_METADATA_BYTES
        ):
            raise ValueError("crew_trust_terminal_invalid")
        detached_patch = json.loads(patch_bytes.decode("utf-8"))
        detached_expected = json.loads(expected_bytes.decode("utf-8"))
        contract_payload = detached_patch.get("crew_session")
        if (
            type(contract_payload) is not dict
            or contract_payload.get("state") != "failed"
        ):
            raise ValueError("crew_trust_terminal_invalid")
        effects = _detach_crew_trust_effects(
            crew_trust_effects,
            session_id=work_item_id,
            session_revision=contract_payload.get("revision"),
        )
        delivery_payload = _detach_crew_session_delivery(
            crew_session_delivery,
            session_id=work_item_id,
            contract_payload=contract_payload,
        )
        if not effects or not self._db:
            return None

        updated: WorkItem | None = None
        async with self._work_item_row_write_lock:
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                item = await self.get_work_item(work_item_id)
                await self._guard_owned_write(work_item_id)
                if item is None:
                    await self._db.execute("ROLLBACK")
                    return None
                if (
                    item.work_type != "crew_session"
                    or item.status != expected_status
                    or item.assigned_to != expected_assigned_to
                    or not _json_values_exactly_equal(
                        item.metadata,
                        detached_expected,
                    )
                ):
                    raise ValueError("crew_trust_terminal_conflict")
                merged = dict(item.metadata)
                merged.update(detached_patch)
                if not self._validate_work_item_status_transition(
                    dataclasses.replace(item, metadata=merged),
                    new_status,
                ):
                    await self._db.execute("ROLLBACK")
                    return None
                serialized = _compact_exact_json_bytes(
                    merged,
                    error="crew_trust_terminal_invalid",
                )
                if len(serialized) > _MAX_WORK_ITEM_METADATA_BYTES:
                    raise ValueError("crew_trust_terminal_invalid")
                await self._db.execute(
                    "UPDATE work_items SET metadata = ?, status = ?, "
                    "updated_at = ? WHERE id = ?",
                    (
                        serialized.decode("utf-8"),
                        new_status,
                        time.time(),
                        work_item_id,
                    ),
                )
                await _insert_crew_trust_effects(self._db, effects)
                await _insert_crew_session_delivery(self._db, delivery_payload)
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
            {"work_item": self._event_work_item_projection(updated)},
        )
        self._emit(EventType.WORK_ITEM_STATUS_CHANGED, {
            "work_item": self._event_work_item_projection(updated),
            "old_status": expected_status,
            "new_status": new_status,
            "source": source,
        })
        return updated

    async def list_pending_crew_trust_outcomes(
        self,
        *,
        limit: int,
    ) -> tuple[dict[str, Any], ...]:
        """Return a bounded deterministic batch of validated pending effects."""
        from probos.consensus.crew_trust_effect import CrewTrustEffect

        if type(limit) is not int or not 1 <= limit <= _MAX_CREW_TRUST_EFFECTS:
            raise ValueError("crew_trust_outbox_limit_invalid")
        if not self._db:
            return ()
        async with self._work_item_row_write_lock:
            cursor = await self._db.execute(
                "SELECT outcome_id, session_id, session_revision, evidence_sha256, "
                "payload_json FROM crew_trust_outbox WHERE delivered = 0 "
                "ORDER BY created_at ASC, outcome_id ASC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
        effects: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row[4])
                effect = CrewTrustEffect.from_payload(payload)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("crew_trust_outbox_corrupt") from exc
            if (
                effect.outcome_id != row[0]
                or effect.session_id != row[1]
                or effect.session_revision != row[2]
                or effect.evidence_sha256 != row[3]
            ):
                raise ValueError("crew_trust_outbox_corrupt")
            effects.append(effect.to_payload())
        return tuple(effects)

    async def has_exact_crew_trust_outcomes(
        self,
        effects: tuple[Any, ...],
        *,
        session_id: str,
        session_revision: int,
    ) -> bool:
        """Return whether one terminal revision owns exactly these outbox rows."""
        expected = _detach_crew_trust_effects(
            effects,
            session_id=session_id,
            session_revision=session_revision,
        )
        if not expected or not self._db:
            return False
        async with self._work_item_row_write_lock:
            cursor = await self._db.execute(
                "SELECT outcome_id, evidence_sha256, payload_json "
                "FROM crew_trust_outbox WHERE session_id = ? "
                "AND session_revision = ? ORDER BY outcome_id ASC",
                (session_id, session_revision),
            )
            rows = await cursor.fetchall()
        if len(rows) != len(expected):
            return False
        for row, payload in zip(rows, expected):
            encoded = _compact_exact_json_bytes(
                payload,
                error="crew_trust_outbox_invalid",
            ).decode("utf-8")
            if (
                type(row[0]) is not str
                or row[0] != payload["outcome_id"]
                or type(row[1]) is not str
                or row[1] != payload["evidence_sha256"]
                or type(row[2]) is not str
                or row[2] != encoded
            ):
                return False
        return True

    async def get_crew_session_delivery(
        self,
        delivery_id: str,
    ) -> CrewSessionDeliveryOutboxEntry | None:
        """Read one validated delivery, including already delivered records."""
        if (
            type(delivery_id) is not str
            or re.fullmatch(r"[0-9a-f]{64}", delivery_id) is None
        ):
            raise ValueError("crew_delivery_outbox_identity_invalid")
        async with self._work_item_row_write_lock:
            if self._db is None:
                raise RuntimeError("crew_delivery_outbox_unavailable")
            cursor = await self._db.execute(
                "SELECT delivery_id, session_id, session_revision, outcome, "
                "occurred_at, payload_json, delivered, created_at, delivered_at "
                "FROM crew_delivery_outbox WHERE delivery_id = ?",
                (delivery_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else _crew_delivery_entry_from_row(row)

    async def list_pending_crew_session_deliveries(
        self,
        *,
        limit: int,
        session_id: str | None = None,
        session_revision: int | None = None,
    ) -> tuple[CrewSessionDeliveryOutboxEntry, ...]:
        """Return a bounded deterministic batch of validated delivery rows."""
        if (
            type(limit) is not int
            or not 1 <= limit <= _MAX_CREW_DELIVERY_PENDING_ROWS
            or (session_id is None and session_revision is not None)
            or (
                session_id is not None
                and (
                    type(session_id) is not str
                    or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(session_id) is None
                )
            )
            or (
                session_revision is not None
                and (
                    type(session_revision) is not int
                    or not 1 <= session_revision <= 2_147_483_647
                )
            )
        ):
            raise ValueError("crew_delivery_outbox_limit_invalid")
        if not self._db:
            return ()
        query = (
            "SELECT delivery_id, session_id, session_revision, outcome, "
            "occurred_at, payload_json, delivered, created_at, delivered_at "
            "FROM crew_delivery_outbox WHERE delivered = 0"
        )
        params: list[Any] = []
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
            if session_revision is not None:
                query += " AND session_revision = ?"
                params.append(session_revision)
        query += " ORDER BY created_at ASC, delivery_id ASC LIMIT ?"
        params.append(limit)
        async with self._work_item_row_write_lock:
            cursor = await self._db.execute(query, tuple(params))
            rows = await cursor.fetchall()
        return tuple(_crew_delivery_entry_from_row(row) for row in rows)

    async def has_exact_crew_session_delivery(
        self,
        record: CrewSessionDeliveryRecord,
        *,
        session_id: str,
        session_revision: int,
        outcome: CrewSessionDeliveryOutcome,
    ) -> bool:
        """Return whether one exact outcome revision owns this delivery row."""
        return await self.get_exact_crew_session_delivery(
            record,
            session_id=session_id,
            session_revision=session_revision,
            outcome=outcome,
        ) is not None

    async def get_exact_crew_session_delivery(
        self,
        record: CrewSessionDeliveryRecord,
        *,
        session_id: str,
        session_revision: int,
        outcome: CrewSessionDeliveryOutcome,
    ) -> CrewSessionDeliveryOutboxEntry | None:
        """Read and validate one exact delivery row under the store lock."""
        from probos.crew_session_delivery import CrewSessionDeliveryRecord

        if (
            type(record) is not CrewSessionDeliveryRecord
            or type(session_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(session_id) is None
            or type(session_revision) is not int
            or not 1 <= session_revision <= 2_147_483_647
            or type(outcome) is not str
            or outcome not in {"done", "failed", "blocked_needs_captain"}
        ):
            raise ValueError("crew_delivery_outbox_identity_invalid")
        validated = type(record).from_payload(record.to_payload())
        if not self._db:
            return None
        if (
            validated.session_id != session_id
            or validated.session_revision != session_revision
            or validated.outcome != outcome
        ):
            raise ValueError("crew_delivery_identity_conflict")
        async with self._work_item_row_write_lock:
            cursor = await self._db.execute(
                "SELECT delivery_id, session_id, session_revision, outcome, "
                "occurred_at, payload_json, delivered, created_at, delivered_at "
                "FROM crew_delivery_outbox WHERE delivery_id = ?",
                (record.delivery_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        entry = _crew_delivery_entry_from_row(row)
        if entry.record.canonical_bytes() != validated.canonical_bytes():
            raise ValueError("crew_delivery_identity_conflict")
        return entry

    async def mark_crew_session_delivery_delivered(
        self,
        delivery_id: str,
        *,
        session_id: str,
        session_revision: int,
        outcome: CrewSessionDeliveryOutcome,
    ) -> bool:
        """Mark one exact pending delivery row acknowledged."""
        if (
            type(delivery_id) is not str
            or re.fullmatch(r"[0-9a-f]{64}", delivery_id) is None
            or type(session_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(session_id) is None
            or type(session_revision) is not int
            or not 1 <= session_revision <= 2_147_483_647
            or type(outcome) is not str
            or outcome not in {"done", "failed", "blocked_needs_captain"}
        ):
            raise ValueError("crew_delivery_outbox_identity_invalid")
        if not self._db:
            return False
        async with self._work_item_row_write_lock:
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                cursor = await self._db.execute(
                    "SELECT delivery_id, session_id, session_revision, outcome, "
                    "occurred_at, payload_json, delivered, created_at, delivered_at "
                    "FROM crew_delivery_outbox WHERE delivery_id = ?",
                    (delivery_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    await self._db.execute("ROLLBACK")
                    return False
                entry = _crew_delivery_entry_from_row(row)
                if (
                    entry.record.session_id != session_id
                    or entry.record.session_revision != session_revision
                    or entry.record.outcome != outcome
                ):
                    await self._db.execute("ROLLBACK")
                    return False
                if entry.delivered:
                    await self._db.execute("ROLLBACK")
                    return True
                cursor = await self._db.execute(
                    "UPDATE crew_delivery_outbox SET delivered = 1, "
                    "delivered_at = ? WHERE delivery_id = ? AND session_id = ? "
                    "AND session_revision = ? AND outcome = ? AND delivered = 0",
                    (
                        time.time(),
                        delivery_id,
                        session_id,
                        session_revision,
                        outcome,
                    ),
                )
                changed = cursor.rowcount == 1
                if changed:
                    await self._db.commit()
                else:
                    await self._db.execute("ROLLBACK")
                return changed
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    # --- AD-1274: promoted-report outbox -------------------------------------
    #
    # A sibling of ``crew_delivery_outbox``, deliberately NOT a reuse of it.
    # That table is session-shaped -- ``UNIQUE (session_id, session_revision,
    # outcome)``, and its drainer validates ``thread.task_id ==
    # record.session_id``. A promoted report has a work item, not a session
    # revision, and forcing it in would corrupt uniqueness semantics that crew
    # sessions depend on elsewhere.
    #
    # It lives in ``workforce.db`` because the resource it is a fallback for is
    # ``chat_threads.db``. An error path must not fail the way the thing it
    # reports on failed: different file, different lock.
    #
    # ``message_id`` is the primary key AND the id the reporter already minted
    # for ``ChatThreadStore.append_message_once``. That one identity makes an
    # at-least-once drain an exactly-once delivery, with no distributed
    # transaction: a redelivery of a row whose write actually committed finds
    # the existing message and returns it without inserting.

    async def enqueue_promoted_report(
        self,
        *,
        message_id: str,
        work_item_id: str,
        thread_id: str,
        agent_id: str,
        body: str,
        created_at: float,
        tool_trace_ref: str | None = None,
    ) -> bool:
        """Record one undeliverable promoted report as durably pending.

        Idempotent on ``message_id``: re-queueing the same report leaves the
        original row, including its ``queued_at`` ordering, untouched.
        """
        if (
            type(message_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(message_id) is None
            or type(work_item_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(work_item_id) is None
            or type(thread_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(thread_id) is None
            or type(agent_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(agent_id) is None
            or type(body) is not str
            or len(body.encode("utf-8")) > _MAX_PROMOTED_REPORT_BODY_BYTES
            or type(created_at) not in {int, float}
            or not math.isfinite(float(created_at))
            or not 0.0 <= float(created_at) <= _MAX_WORK_ITEM_TIMESTAMP
            or (
                tool_trace_ref is not None
                and (
                    type(tool_trace_ref) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", tool_trace_ref) is None
                )
            )
        ):
            raise ValueError("promoted_report_outbox_invalid")
        if not self._db:
            return False
        async with self._work_item_row_write_lock:
            cursor = await self._db.execute(
                "INSERT OR IGNORE INTO promoted_report_outbox "
                "(message_id, work_item_id, thread_id, agent_id, body, "
                "created_at, delivered, queued_at, delivered_at, tool_trace_ref) "
                "VALUES (?,?,?,?,?,?,0,?,NULL,?)",
                (
                    message_id,
                    work_item_id,
                    thread_id,
                    agent_id,
                    body,
                    float(created_at),
                    time.time(),
                    tool_trace_ref,
                ),
            )
            await self._db.commit()
        return cursor.rowcount == 1

    async def list_pending_promoted_reports(
        self,
        *,
        limit: int,
    ) -> tuple[PromotedReportOutboxEntry, ...]:
        """Return a bounded deterministic batch of validated pending rows."""
        if (
            type(limit) is not int
            or not 1 <= limit <= _MAX_PROMOTED_REPORT_PENDING_ROWS
        ):
            raise ValueError("promoted_report_outbox_limit_invalid")
        if not self._db:
            return ()
        async with self._work_item_row_write_lock:
            cursor = await self._db.execute(
                "SELECT message_id, work_item_id, thread_id, agent_id, body, "
                "created_at, delivered, queued_at, delivered_at, tool_trace_ref "
                "FROM promoted_report_outbox WHERE delivered = 0 "
                "ORDER BY queued_at ASC, message_id ASC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
        return tuple(_promoted_report_entry_from_row(row) for row in rows)

    async def mark_promoted_report_delivered(self, message_id: str) -> bool:
        """Mark one pending report acknowledged. Already-marked returns True."""
        if (
            type(message_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(message_id) is None
        ):
            raise ValueError("promoted_report_outbox_invalid")
        if not self._db:
            return False
        async with self._work_item_row_write_lock:
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                cursor = await self._db.execute(
                    "SELECT delivered FROM promoted_report_outbox "
                    "WHERE message_id = ?",
                    (message_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    await self._db.execute("ROLLBACK")
                    return False
                if row[0] == 1:
                    await self._db.execute("ROLLBACK")
                    return True
                cursor = await self._db.execute(
                    "UPDATE promoted_report_outbox SET delivered = 1, "
                    "delivered_at = ? WHERE message_id = ? AND delivered = 0",
                    (time.time(), message_id),
                )
                changed = cursor.rowcount == 1
                if changed:
                    await self._db.commit()
                else:
                    await self._db.execute("ROLLBACK")
                return changed
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    async def mark_promoted_report_undeliverable(self, message_id: str) -> bool:
        """Retire one pending report that can never be delivered (AD-1274).

        ``delivered = 2`` is a THIRD state, deliberately not ``1``. Two of the
        drainer's failures are permanent -- a thread that no longer exists, and
        a message the store rejects -- and asking again cannot change either
        answer. Left pending they sat at the head of an oldest-first, bounded
        queue and consumed the whole batch on every pass, so a handful of them
        starved every newer report behind them. Review measured exactly that:
        three poison rows ahead of one deliverable report, three drains, zero
        delivered.

        Recording them as ``delivered`` would have unblocked the queue too, and
        would have been a lie -- the Captain never received them, and the
        pending count is the only signal an operator has that a report is owed.
        So the row leaves the pending set while still saying, truthfully, that
        it was never delivered.
        """
        if (
            type(message_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(message_id) is None
        ):
            raise ValueError("promoted_report_outbox_invalid")
        if not self._db:
            return False
        async with self._work_item_row_write_lock:
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                cursor = await self._db.execute(
                    "SELECT delivered FROM promoted_report_outbox "
                    "WHERE message_id = ?",
                    (message_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    await self._db.execute("ROLLBACK")
                    return False
                if row[0] != 0:
                    # Already terminal. A row that genuinely reached the Captain
                    # must NEVER be rewritten as undeliverable.
                    await self._db.execute("ROLLBACK")
                    return row[0] == 2
                cursor = await self._db.execute(
                    "UPDATE promoted_report_outbox SET delivered = 2, "
                    "delivered_at = ? WHERE message_id = ? AND delivered = 0",
                    (time.time(), message_id),
                )
                changed = cursor.rowcount == 1
                if changed:
                    await self._db.commit()
                else:
                    await self._db.execute("ROLLBACK")
                return changed
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise

    async def list_crew_session_metric_work_items(
        self,
        *,
        window_start: float,
        window_end: float,
        limit: int,
    ) -> tuple[WorkItem, ...]:
        """Return a bounded CrewSession window newest first."""
        if (
            type(window_start) is not float
            or not math.isfinite(window_start)
            or window_start < -(365 * 86_400.0)
            or type(window_end) is not float
            or not math.isfinite(window_end)
            or window_end < window_start
            or window_end > _MAX_WORK_ITEM_TIMESTAMP
            or type(limit) is not int
            or not 1 <= limit <= _MAX_CREW_SESSION_METRIC_ROWS
        ):
            raise ValueError("crew_session_metrics_query_invalid")
        if not self._db:
            return ()
        async with self._work_item_row_write_lock:
            cursor = await self._db.execute(
                "SELECT * FROM work_items WHERE work_type = 'crew_session' "
                "AND created_at >= ? AND created_at <= ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (window_start, window_end, limit),
            )
            rows = await cursor.fetchall()
        try:
            return tuple(self._row_to_work_item(row) for row in rows)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("crew_session_metrics_row_invalid") from exc

    async def mark_crew_trust_outcome_delivered(
        self,
        outcome_id: str,
        *,
        session_id: str,
        session_revision: int,
        evidence_sha256: str,
    ) -> bool:
        """Mark one exact pending effect delivered using all identity fields."""
        if (
            type(outcome_id) is not str
            or re.fullmatch(r"[0-9a-f]{64}", outcome_id) is None
            or type(session_id) is not str
            or _WORK_ITEM_PUBLICATION_ID_RE.fullmatch(session_id) is None
            or type(session_revision) is not int
            or not 1 <= session_revision <= 2_147_483_647
            or type(evidence_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", evidence_sha256) is None
        ):
            raise ValueError("crew_trust_outbox_identity_invalid")
        if not self._db:
            return False
        async with self._work_item_row_write_lock:
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                cursor = await self._db.execute(
                    "UPDATE crew_trust_outbox SET delivered = 1, delivered_at = ? "
                    "WHERE outcome_id = ? AND session_id = ? "
                    "AND session_revision = ? AND evidence_sha256 = ? "
                    "AND delivered = 0",
                    (
                        time.time(),
                        outcome_id,
                        session_id,
                        session_revision,
                        evidence_sha256,
                    ),
                )
                changed = cursor.rowcount == 1
                if not changed:
                    cursor = await self._db.execute(
                        "SELECT delivered FROM crew_trust_outbox "
                        "WHERE outcome_id = ? AND session_id = ? "
                        "AND session_revision = ? AND evidence_sha256 = ?",
                        (
                            outcome_id,
                            session_id,
                            session_revision,
                            evidence_sha256,
                        ),
                    )
                    row = await cursor.fetchone()
                    changed = row is not None and row[0] == 1
                await self._db.commit()
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        return changed

    async def transition_work_item(
        self, work_item_id: str, new_status: str, source: str = "system",
    ) -> WorkItem | None:
        """Transition work item status with validation."""
        if not self._db:
            return None
        async with self._booking_transaction():
            item = await self.get_work_item(work_item_id)
            await self._guard_owned_write(work_item_id)
            if not item:
                return None
            if item.work_type == "crew_session":
                raise ValueError("crew_session_write_reserved")
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
            updated = await self.get_work_item(work_item_id)
        await self._refresh_snapshot_cache()
        self._emit(EventType.WORK_ITEM_STATUS_CHANGED, {
            "work_item": self._event_work_item_projection(updated),
            "old_status": old_status,
            "new_status": new_status,
        })
        return updated

    async def delete_work_item(self, work_item_id: str) -> bool:
        """Delete a work item and its associated bookings/requirements. Returns True if found."""
        if not self._db:
            return False
        async with self._booking_transaction():
            item = await self.get_work_item(work_item_id)
            await self._guard_owned_write(work_item_id)
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
        if overrides is not None and "steps_control" in overrides:
            raise owned_steps.OwnedStepsError("owned_steps_control_reserved")
        if overrides is not None:
            _reject_reserved_metadata(overrides.get("metadata"))
        kwargs = self.template_store.instantiate(template_id, variables, overrides)
        kwargs["created_by"] = created_by
        return await self.create_work_item(**kwargs)

    # ======================================================================
    # Assignment Engine
    # ======================================================================

    @asynccontextmanager
    async def _booking_transaction(self) -> AsyncIterator[None]:
        async with self._work_item_row_write_lock:
            assert self._db is not None
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                yield
                await self._db.commit()
            except BaseException:
                try:
                    await self._db.execute("ROLLBACK")
                except Exception:
                    logger.error(
                        "Workforce admission rollback failed; durable state is "
                        "uncertain and the original failure is propagated",
                    )
                raise

    def _resolve_pull_resource(
        self,
        resource_id: str,
        action: Literal["discover", "claim", "assign", "resume"],
        agent_pull: bool,
    ) -> BookableResource | None:
        resource = self.get_resource(resource_id)
        if self._pull_resource_resolver is not None:
            resolved = self._pull_resource_resolver(resource_id, action, agent_pull)
            if resolved is None or resource is None:
                resource = None
            elif resolved.resource_id != resource_id:
                resource = None
            else:
                resource = dataclasses.replace(
                    resolved, capacity=resource.capacity, active=resource.active,
                )
        elif agent_pull:
            resource = None
        if resource is not None and (
            resource.resource_id != resource_id
            or resource.active is not True
            or type(resource.capacity) is not int
            or resource.capacity < 1
            or type(resource.department) is not str
            or type(resource.agent_type) is not str
            or type(resource.characteristics) is not list
            or any(
                type(characteristic) is not dict
                or type(characteristic.get("skill")) is not str
                or type(characteristic.get("proficiency")) not in (int, float)
                or not math.isfinite(characteristic["proficiency"])
                or not 0 <= characteristic["proficiency"] <= 1
                for characteristic in resource.characteristics
            )
        ):
            resource = None
        if resource is None and agent_pull:
            raise PermissionError("work_pull_authority_denied")
        return resource

    async def _has_booking_capacity(self, resource: BookableResource) -> bool:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM bookings WHERE resource_id = ? "
            "AND status IN ('scheduled', 'active')",
            (resource.resource_id,),
        )
        row = await cursor.fetchone()
        return row[0] < resource.capacity

    @staticmethod
    def _standalone_pull_item(item: WorkItem) -> bool:
        return (
            item.work_type != "crew_session"
            and item.parent_id is None
            and type(item.metadata) is dict
            and not any(
                key in item.metadata
                for key in (
                    SCAFFOLD_METADATA_FLAG, "crew_session", "crew_execution",
                    "thread_id", "room_id", "session_id",
                )
            )
        )

    @staticmethod
    def _pull_visible(item: WorkItem, resource: BookableResource) -> bool:
        publication = item.metadata.get("agent_pull")
        if type(publication) is not dict or type(publication.get("version")) is not int:
            return False
        if publication["version"] != 1:
            return False
        if publication.get("scope") == "ship":
            return set(publication) == {"version", "scope"}
        return (
            publication.get("scope") == "department"
            and set(publication) == {"version", "scope", "department"}
            and type(publication.get("department")) is str
            and bool(publication["department"])
            and publication["department"] == resource.department
        )

    async def _requirements_allow(
        self, item: WorkItem, resource: BookableResource,
    ) -> bool:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT department_constraint FROM resource_requirements "
            "WHERE work_item_id = ?",
            (item.id,),
        )
        return all(
            not row[0] or row[0] == resource.department
            for row in await cursor.fetchall()
        )

    async def _ready_for_pull(
        self, item: WorkItem, resource: BookableResource, *, agent_pull: bool,
    ) -> bool:
        if await self._owned_parent_id(item.id) is not None:
            return False
        if agent_pull and (type(item.id) is not str or not 1 <= len(item.id) <= 128):
            return False
        if (
            item.status != "open"
            or item.assigned_to is not None
            or not self._standalone_pull_item(item)
            or (agent_pull and not self._pull_visible(item, resource))
            or not self._check_eligibility(resource, item)
            or (
                item.ttl_seconds is not None
                and time.time() >= item.created_at + item.ttl_seconds
            )
            or not await self._requirements_allow(item, resource)
        ):
            return False
        for dependency_id in item.depends_on:
            dependency = await self.get_work_item(dependency_id)
            if dependency is None or dependency.status != "done":
                return False
        return True

    async def _pull_candidates(
        self,
        resource: BookableResource,
        *,
        work_type: str | None,
        agent_pull: bool,
        limit: int,
        offset: int = 0,
    ) -> list[WorkItem]:
        assert self._db is not None
        conditions = [
            "status = 'open'", "assigned_to IS NULL",
            "work_type != 'crew_session'", "parent_id IS NULL",
            "steps_control IS NULL",
        ]
        params: list[Any] = []
        if work_type is not None:
            conditions.append("work_type = ?")
            params.append(work_type)
        if agent_pull:
            # Hidden rows do not consume or reveal positions in a peer's page.
            conditions.append(
                "CASE WHEN json_valid(metadata) THEN "
                "json_type(metadata, '$.agent_pull') = 'object' "
                "AND json_type(metadata, '$.agent_pull.version') = 'integer' "
                "AND json_extract(metadata, '$.agent_pull.version') = 1 "
                "AND ((json_extract(metadata, '$.agent_pull.scope') = 'ship' "
                "AND (SELECT COUNT(*) FROM json_each(metadata, '$.agent_pull')) = 2) "
                "OR (json_extract(metadata, '$.agent_pull.scope') = 'department' "
                "AND json_type(metadata, '$.agent_pull.department') = 'text' "
                "AND json_extract(metadata, '$.agent_pull.department') = ? "
                "AND (SELECT COUNT(*) FROM json_each(metadata, '$.agent_pull')) = 3)) "
                "ELSE 0 END"
            )
            params.append(resource.department)
        cursor = await self._db.execute(
            f"SELECT * FROM work_items WHERE {' AND '.join(conditions)} "
            "ORDER BY priority ASC, created_at ASC, id ASC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return [self._row_to_work_item(row) for row in await cursor.fetchall()]

    async def list_claimable_work_items(
        self, resource_id: str, *, work_type: str | None = None,
        limit: int = 20, offset: int = 0,
    ) -> ReadyWorkPage:
        if (
            type(resource_id) is not str or not resource_id
            or type(limit) is not int or not 1 <= limit <= 50
            or type(offset) is not int or offset < 0
            or (
                work_type is not None
                and (type(work_type) is not str or not 1 <= len(work_type) <= 64)
            )
        ):
            raise ValueError("work_pull_query_invalid")
        if self._db is None:
            raise RuntimeError("work_pull_store_unavailable")
        async with self._work_item_row_write_lock:
            resource = self._resolve_pull_resource(resource_id, "discover", True)
            assert resource is not None
            if not await self._has_booking_capacity(resource):
                return ReadyWorkPage((), None)
            candidates = await self._pull_candidates(
                resource, work_type=work_type, agent_pull=True, limit=200, offset=offset,
            )
            items: list[WorkItem] = []
            item_offsets: list[int] = []
            examined = 0
            for item in candidates:
                examined += 1
                if await self._ready_for_pull(item, resource, agent_pull=True):
                    items.append(item)
                    item_offsets.append(offset + examined - 1)
                    if len(items) == limit:
                        break
            more = examined < len(candidates) or len(candidates) == 200
            return ReadyWorkPage(
                tuple(items), offset + examined if more else None, tuple(item_offsets),
            )

    @staticmethod
    def _prepare_claim(
        item: WorkItem, booking: Booking,
        prepare_claim: Callable[[WorkItem, Booking], None] | None,
    ) -> None:
        if prepare_claim is None:
            return
        before = (dataclasses.asdict(item), dataclasses.asdict(booking))
        result = prepare_claim(item, booking)
        if inspect.iscoroutine(result):
            result.close()
        if result is not None or before != (
            dataclasses.asdict(item), dataclasses.asdict(booking),
        ):
            raise ValueError("work_pull_preparation_invalid")

    async def _assign_work_item(
        self, item: WorkItem, resource: BookableResource, source: str,
        *,
        prepare_claim: Callable[[WorkItem, Booking], None] | None = None,
    ) -> Booking | None:
        assert self._db is not None
        await self._guard_owned_write(item.id)
        now = time.time()
        booking = Booking(
            resource_id=resource.resource_id, work_item_id=item.id,
            status="scheduled", start_time=now,
        )
        cursor = await self._db.execute(
            "SELECT id FROM resource_requirements WHERE work_item_id = ? "
            "AND fulfilled = 0 ORDER BY id LIMIT 1",
            (item.id,),
        )
        requirement = await cursor.fetchone()
        if requirement:
            booking.requirement_id = requirement["id"]
        planned_item = dataclasses.replace(
            item, assigned_to=resource.resource_id, status="scheduled", updated_at=now,
        )
        self._prepare_claim(planned_item, booking, prepare_claim)
        cursor = await self._db.execute(
            "UPDATE work_items SET assigned_to = ?, status = 'scheduled', "
            "updated_at = ? WHERE id = ? AND assigned_to IS NULL AND status = ?",
            (planned_item.assigned_to, planned_item.updated_at, item.id, item.status),
        )
        if cursor.rowcount != 1:
            return None
        if requirement:
            await self._db.execute(
                "UPDATE resource_requirements SET fulfilled = 1 WHERE id = ?",
                (booking.requirement_id,),
            )
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
        await self._record_timestamp(booking.id, "scheduled", source)
        return booking

    async def assign_work_item(
        self,
        work_item_id: str,
        resource_id: str,
        source: str = "captain",
    ) -> Booking | None:
        """Push assignment: Captain assigns work directly to an agent."""
        if self._db is None:
            return None
        async with self._booking_transaction():
            item = await self.get_work_item(work_item_id)
            await self._guard_owned_write(work_item_id)
            if not item:
                return None
            if item.work_type == "crew_session":
                raise ValueError("crew_session_write_reserved")
            resource = self._resolve_pull_resource(resource_id, "assign", False)
            if resource is None:
                return None
            if (
                item.assigned_to is not None or item.status in _TERMINAL_STATUSES
                or not self._check_eligibility(resource, item)
                or not await self._requirements_allow(item, resource)
                or not await self._has_booking_capacity(resource)
            ):
                return None
            booking = await self._assign_work_item(item, resource, source)
            if booking is None:
                return None
            updated_item = await self.get_work_item(work_item_id) or item
        await self._publish_assignment(updated_item, booking, resource, source=source)
        return booking

    async def _publish_assignment(
        self, item: WorkItem, booking: Booking, resource: BookableResource, *,
        source: str, claimed: bool = False, agent_pull: bool = False,
    ) -> None:
        try:
            await self._refresh_snapshot_cache()
        except Exception:
            logger.warning(
                "Workforce snapshot refresh failed after assignment; the booking "
                "is committed and event delivery continues",
                exc_info=True,
            )
        events = [EventType.WORK_ITEM_ASSIGNED]
        if claimed:
            events.append(EventType.WORK_ITEM_CLAIMED)
        for event_type in events:
            try:
                self._emit(event_type, {
                    "work_item": item.to_dict(),
                    "booking": booking.to_dict(),
                    "resource": resource.to_dict(),
                })
            except Exception:
                logger.warning(
                    "Workforce assignment event delivery failed after commit; "
                    "the booking stands and is not re-created",
                    exc_info=True,
                )
        if self._dispatcher and not agent_pull:
            try:
                from probos.activation import task_event_for_agent
                event = task_event_for_agent(
                    agent_id=resource.resource_id,
                    source_type="workforce",
                    source_id=item.id,
                    event_type="work_item_assigned",
                    priority=Priority.NORMAL,
                    payload={
                        "work_item_id": item.id,
                        "title": item.title,
                        "description": item.description,
                        "work_type": item.work_type,
                        "status": "scheduled",
                        "assigned_by": source,
                    },
                )
                _res = await asyncio.wait_for(self._dispatcher.dispatch(event), timeout=5)
                if not _res.accepted:
                    # BF-810: the booking is durable and stands; only the
                    # notification failed. Say so rather than dropping it.
                    logger.warning(
                        "AD-654d: work_item_assigned for %s reached no agent "
                        "(rejected=%d unroutable=%d); booking still stands",
                        item.id, _res.rejected, _res.unroutable,
                    )
            except Exception:
                logger.warning(
                    "Workforce assignment notification failed after commit; "
                    "the booking stands and the committed result is returned",
                    exc_info=True,
                )

    async def claim_work_item(
        self,
        resource_id: str,
        work_type: str | None = None,
        department: str | None = None,
        *,
        work_item_id: str | None = None,
        agent_pull: bool = False,
        prepare_claim: Callable[[WorkItem, Booking], None] | None = None,
    ) -> tuple[WorkItem, Booking] | None:
        """Claim selected work, or the highest-priority eligible legacy candidate.

        ``prepare_claim`` is synchronous, read-only validation of the actual
        planned outcome. It must not perform I/O or reenter the store. A prepared
        result is usable only after this method successfully returns ownership.
        """
        if (
            type(agent_pull) is not bool
            or type(resource_id) is not str or not resource_id
            or (
                prepare_claim is not None
                and (not callable(prepare_claim) or inspect.iscoroutinefunction(prepare_claim))
            )
            or (
                work_item_id is not None
                and (type(work_item_id) is not str or not 1 <= len(work_item_id) <= 128)
            )
            or (
                agent_pull
                and (work_item_id is None or department is not None or work_type is not None)
            )
        ):
            raise ValueError("work_pull_claim_invalid")
        if work_type == "crew_session":
            raise ValueError("crew_session_write_reserved")
        if not self._db:
            if agent_pull:
                raise RuntimeError("work_pull_store_unavailable")
            return None
        async with self._booking_transaction():
            if work_item_id is not None:
                await self._guard_owned_write(work_item_id)
            resource = self._resolve_pull_resource(resource_id, "claim", agent_pull)
            if resource is None:
                return None
            if work_item_id is not None:
                item = await self.get_work_item(work_item_id)
                if item is None or (agent_pull and not self._standalone_pull_item(item)):
                    return None
                cursor = await self._db.execute(
                    "SELECT * FROM bookings WHERE work_item_id = ?", (item.id,),
                )
                bookings = [self._row_to_booking(row) for row in await cursor.fetchall()]
                live = [b for b in bookings if b.status not in ("completed", "cancelled")]
                if len(live) > 1:
                    raise RuntimeError("work_pull_booking_integrity")
                owned_before = any(b.resource_id == resource_id for b in bookings)
                if item.assigned_to is not None or owned_before:
                    if (
                        item.assigned_to == resource_id
                        and item.status not in _TERMINAL_STATUSES
                        and len(live) == 1
                        and live[0].resource_id == resource_id
                    ):
                        self._prepare_claim(item, live[0], prepare_claim)
                        return item, live[0]
                    return None
                if live:
                    raise RuntimeError("work_pull_booking_integrity")
                candidates = [item]
            else:
                candidates = await self._pull_candidates(
                    resource, work_type=work_type, agent_pull=False, limit=50,
                )
            if (
                (department and resource.department != department)
                or not await self._has_booking_capacity(resource)
            ):
                return None
            booking = None
            for item in candidates:
                if await self._ready_for_pull(item, resource, agent_pull=agent_pull):
                    booking = await self._assign_work_item(
                        item, resource, "agent", prepare_claim=prepare_claim,
                    )
                    if booking is not None:
                        break
            if booking is None:
                return None
            updated_item = await self.get_work_item(booking.work_item_id)
            assert updated_item is not None
        await self._publish_assignment(
            updated_item, booking, resource,
            source="agent", claimed=True, agent_pull=agent_pull,
        )
        return updated_item, booking

    async def unassign_work_item(self, work_item_id: str, reason: str = "") -> bool:
        """Remove assignment. Cancels active booking. Resets assigned_to to NULL."""
        if not self._db:
            return False
        cancelled: list[Booking] = []
        async with self._booking_transaction():
            item = await self.get_work_item(work_item_id)
            await self._guard_owned_write(work_item_id)
            if not item:
                return False
            if item.work_type == "crew_session":
                raise ValueError("crew_session_write_reserved")
            if not item.assigned_to:
                return False
            cursor = await self._db.execute(
                "SELECT * FROM bookings WHERE work_item_id = ? "
                "AND status NOT IN ('completed', 'cancelled')",
                (work_item_id,),
            )
            for row in await cursor.fetchall():
                cancelled.append(await self._cancel_booking(self._row_to_booking(row)))
            await self._db.execute(
                "UPDATE work_items SET assigned_to = NULL, status = 'open', updated_at = ? WHERE id = ?",
                (time.time(), work_item_id),
            )
        await self._refresh_snapshot_cache()
        for booking in cancelled:
            self._emit(EventType.BOOKING_CANCELLED, {"booking": booking.to_dict()})
        return True

    # ======================================================================
    # Booking lifecycle
    # ======================================================================

    async def start_booking(self, booking_id: str) -> Booking | None:
        """Transition booking: scheduled → active."""
        if not self._db:
            return None
        async with self._booking_transaction():
            booking = await self.get_booking(booking_id)
            await self._guard_owned_booking(booking_id)
            if not booking or booking.status != "scheduled":
                return None
            item = await self.get_work_item(booking.work_item_id)
            if item is not None and item.work_type == "crew_session":
                raise ValueError("crew_session_write_reserved")
            now = time.time()
            await self._db.execute(
                "UPDATE bookings SET status = 'active', actual_start = ? WHERE id = ?",
                (now, booking_id),
            )
            await self._record_timestamp(booking_id, "active", "system")
            if item is not None:
                await self._db.execute(
                    "UPDATE work_items SET status = 'in_progress', updated_at = ? WHERE id = ?",
                    (now, booking.work_item_id),
                )
            updated = await self.get_booking(booking_id)
        await self._refresh_snapshot_cache()
        self._emit(EventType.BOOKING_STARTED, {"booking": updated.to_dict() if updated else {}})
        return updated

    async def pause_booking(self, booking_id: str) -> Booking | None:
        """Transition booking: active → on_break."""
        if not self._db:
            return None
        async with self._booking_transaction():
            booking = await self.get_booking(booking_id)
            await self._guard_owned_booking(booking_id)
            if not booking or booking.status != "active":
                return None
            await self._db.execute(
                "UPDATE bookings SET status = 'on_break' WHERE id = ?", (booking_id,),
            )
            await self._record_timestamp(booking_id, "on_break", "system")
            updated = await self.get_booking(booking_id)
        await self._refresh_snapshot_cache()
        return updated

    async def resume_booking(self, booking_id: str) -> Booking | None:
        """Transition booking: on_break → active."""
        if not self._db:
            return None
        async with self._booking_transaction():
            booking = await self.get_booking(booking_id)
            await self._guard_owned_booking(booking_id)
            if not booking or booking.status != "on_break":
                return None
            resource = self._resolve_pull_resource(booking.resource_id, "resume", False)
            if resource is None or not await self._has_booking_capacity(resource):
                return None
            await self._db.execute(
                "UPDATE bookings SET status = 'active' WHERE id = ?", (booking_id,),
            )
            await self._record_timestamp(booking_id, "active", "system")
            updated = await self.get_booking(booking_id)
        await self._refresh_snapshot_cache()
        return updated

    async def complete_booking(self, booking_id: str, tokens_consumed: int = 0) -> Booking | None:
        """Transition booking: active → completed. Generates journal entries."""
        if not self._db:
            return None
        if (
            type(tokens_consumed) is not int
            or not 0 <= tokens_consumed <= _MAX_WORK_ITEM_ACTUAL_TOKENS
        ):
            raise ValueError("work_item_actual_tokens_delta_invalid")
        async with self._booking_transaction():
            booking = await self.get_booking(booking_id)
            await self._guard_owned_booking(booking_id)
            if not booking or booking.status not in ("active", "scheduled"):
                return None
            item = (
                await self.get_work_item(booking.work_item_id)
                if booking.work_item_id
                else None
            )
            if item is not None:
                if item.work_type == "crew_session":
                    raise ValueError("crew_session_write_reserved")
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
            journal = await self._generate_journal(booking_id)
            updated = await self.get_booking(booking_id)
        await self._refresh_snapshot_cache()
        self._emit(EventType.BOOKING_COMPLETED, {
            "booking": updated.to_dict() if updated else {},
            "journal": [j.to_dict() for j in journal],
        })
        return updated

    async def cancel_booking(self, booking_id: str) -> Booking | None:
        """Cancel a booking."""
        if not self._db:
            return None
        async with self._booking_transaction():
            booking = await self.get_booking(booking_id)
            await self._guard_owned_booking(booking_id)
            if not booking or booking.status in ("completed", "cancelled"):
                return None
            updated = await self._cancel_booking(booking)
        await self._refresh_snapshot_cache()
        self._emit(EventType.BOOKING_CANCELLED, {"booking": updated.to_dict()})
        return updated

    async def _cancel_booking(
        self, booking: Booking, *, binding: _OwnedStepsWriteBinding | None = None,
    ) -> Booking:
        assert self._db is not None
        await self._guard_owned_booking(booking.id, binding)
        await self._db.execute(
            "UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking.id,),
        )
        await self._record_timestamp(booking.id, "cancelled", "system", binding=binding)
        return dataclasses.replace(booking, status="cancelled")

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
        async with self._booking_transaction():
            return await self._generate_journal(booking_id)

    async def _generate_journal(
        self, booking_id: str, *, binding: _OwnedStepsWriteBinding | None = None,
    ) -> list[BookingJournal]:
        assert self._db is not None
        await self._guard_owned_booking(booking_id, binding)
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
        if (
            type(work_item.trust_requirement) not in (int, float)
            or not math.isfinite(work_item.trust_requirement)
            or not 0 <= work_item.trust_requirement <= 1
        ):
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
            try:
                if await self._owned_parent_id(work_item_id) is not None:
                    if self._owned_steps_ttl_owner is None:
                        raise owned_steps.OwnedStepsError("owned_steps_ttl_owner_unavailable")
                    changed = await self._owned_steps_ttl_owner.expire_owned_steps(work_item_id, now)
                else:
                    changed = await self.transition_work_item(work_item_id, "cancelled", source="ttl_expiry")
                if changed:
                    logger.info(
                        "TTL expiry committed for work item %s; its owner cancelled expired work "
                        "and remaining expirations continue", work_item_id,
                    )
                else:
                    logger.warning(
                        "TTL owner declined work item %s; it remains unchanged and unrelated expirations continue",
                        work_item_id,
                    )
            except Exception:
                logger.warning(
                    "TTL cancellation failed for work item %s; ownership/evidence is retained "
                    "and unrelated expirations continue", work_item_id, exc_info=True,
                )

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
            f"SELECT {_WORK_ITEM_PUBLIC_COLUMNS} FROM work_items WHERE status NOT IN ('done', 'cancelled', 'failed') ORDER BY priority ASC, created_at DESC LIMIT 100",
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
    def _validate_unmaterialized_work_item(row: aiosqlite.Row) -> None:
        for key in _WORK_ITEM_JSON_FIELDS:
            raw = row[key]
            if not raw or raw in ("[]", "{}"):
                continue
            # At most 4,000 exact strings of at most 1,024 characters. Larger
            # inputs and non-text SQL values keep the uncached decoder path.
            if type(raw) is str and len(raw) <= 1024:
                _validated_work_item_json(raw)
            else:
                json.loads(raw)

    @staticmethod
    def _row_to_work_item(row: aiosqlite.Row) -> WorkItem:
        """Convert aiosqlite Row to WorkItem."""
        # Exact empty JSON literals need fresh containers, not another parse.
        # All other bytes still pass through the decoder on every read.
        return WorkItem(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            work_type=row["work_type"],
            status=row["status"],
            priority=row["priority"],
            parent_id=row["parent_id"],
            project_id=row["project_id"],
            depends_on=json.loads(row["depends_on"]) if row["depends_on"] and row["depends_on"] != "[]" else [],
            assigned_to=row["assigned_to"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            due_at=row["due_at"],
            estimated_tokens=row["estimated_tokens"],
            actual_tokens=row["actual_tokens"],
            trust_requirement=row["trust_requirement"],
            required_capabilities=json.loads(row["required_capabilities"]) if row["required_capabilities"] and row["required_capabilities"] != "[]" else [],
            tags=json.loads(row["tags"]) if row["tags"] and row["tags"] != "[]" else [],
            metadata=json.loads(row["metadata"]) if row["metadata"] and row["metadata"] != "{}" else {},
            steps=json.loads(row["steps"]) if row["steps"] and row["steps"] != "[]" else [],
            verification=json.loads(row["verification"]) if row["verification"] and row["verification"] != "{}" else {},
            schedule=json.loads(row["schedule"]) if row["schedule"] and row["schedule"] != "{}" else {},
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
        *, binding: _OwnedStepsWriteBinding | None = None,
    ) -> None:
        """Append a BookingTimestamp."""
        if not self._db:
            return
        await self._guard_owned_booking(booking_id, binding)
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
