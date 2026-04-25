# AD-496: Workforce Scheduling Engine — Core Data Model

## Overview

Build the Workforce Scheduling Engine — the universal scheduling substrate for all ProbOS work management. This is the foundation that all future work management (AD-497 Scrumban Board, AD-498 Work Type Registry, AD-471 Autonomous Operations) builds upon.

**Design philosophy:** "Universal Resource Scheduling for AI agents." Modeled after Dynamics 365 URS and US Navy 3-M/PMS.

**Key principle:** Separation of Work from Scheduling — WorkItem (what) → ResourceRequirement (match) → Booking (who/when).

---

## Context & Existing Infrastructure

AD-496 must absorb, coexist with, or provide migration paths for five existing work management systems. Understanding each is critical.

### 1. TaskTracker (`src/probos/task_tracker.py`)
- **Status:** ORPHANED. Wired into runtime (`runtime.py:1262`) but **nothing creates tasks through it**.
- **Pattern:** In-memory dict, `AgentTask` dataclass with 12 fields, `TaskStatus` enum (queued/working/review/done/failed).
- **Co-located:** `NotificationQueue` class (AD-323) — agent→Captain notifications. **Keep this** — it's independent of task tracking.
- **Tests:** 32 tests across `test_task_tracker.py` and `test_task_panel.py`.
- **Decision:** TaskTracker is replaced by WorkItemStore. `NotificationQueue` stays in `task_tracker.py` (or moves to its own file). TaskTracker class is **deprecated but not removed** in this AD — existing tests continue to pass. Future AD removes it.
- **Runtime:** `self.task_tracker` attribute stays for backward compatibility. `snapshot()` included in `build_state_snapshot()` at `runtime.py:513`.

### 2. PersistentTaskStore (`src/probos/persistent_tasks.py`)
- **Status:** Most mature existing store. SQLite via aiosqlite. Config-gated (`persistent_tasks.enabled`).
- **Pattern:** `PersistentTask` dataclass (19 fields), tick loop, cron/interval/once scheduling, DAG checkpoint resume, snapshot cache.
- **API:** 7 endpoints under `/api/scheduled-tasks`.
- **Tests:** 39 tests.
- **Decision:** **This is the architectural template for WorkItemStore.** Follow its SQLite lifecycle pattern (start/stop, `_tick_loop`, `_refresh_snapshot_cache`, `_row_to_*`). PersistentTaskStore **coexists** — it handles Captain-created scheduled intents (a different concern than workforce scheduling). Future AD may migrate scheduled intents to WorkItems with `schedule` field, but NOT in this AD.

### 3. BuildQueue (`src/probos/build_queue.py`)
- **Status:** In-memory, functional. Used by builder pipeline.
- **Pattern:** `QueuedBuild` dataclass (12 fields), state machine (queued→dispatched→building→reviewing→merged|failed).
- **API:** 4 endpoints under `/api/build/queue`.
- **Tests:** 31 tests.
- **Decision:** **Coexists.** BuildQueue is specialized for the builder pipeline and works well. Future AD may model builds as WorkItems (type=`work_order`), but NOT in this AD. No changes to BuildQueue.

### 4. DutyScheduleTracker (`src/probos/duty_schedule.py`)
- **Status:** In-memory. Tightly coupled to proactive loop's `_think_for_agent()`.
- **Pattern:** `DutyStatus` dataclass, schedules from config (`DutyScheduleConfig` → `DutyDefinition`), 7 defaults in `config/system.yaml`.
- **API:** None (only exposed via agent profile state snapshot).
- **Tests:** 13+ tests.
- **Decision:** **Coexists in this AD.** DutyScheduleTracker continues to drive proactive duties. AD-498 (Work Type Registry) will add a `duty` work type, and a future AD will evolve DutyScheduleTracker to generate duty-type WorkItems. For now, DutyScheduleTracker is untouched.

### 5. WatchManager (`src/probos/watch_rotation.py`)
- **Status:** NOT wired into runtime.py at all. `DutyShift` dataclass defined but unused. `CaptainOrder` dataclass exists but AD-471 will use WorkItems instead.
- **Pattern:** `WatchType` enum (Alpha/Beta/Gamma), `StandingTask`, `CaptainOrder`, `DutyShift` dataclasses, `WatchManager` class with dispatch loop.
- **Tests:** 16 tests.
- **Decision:** **Deprecated but not removed.** WatchManager's concepts (watch types, duty shifts, standing tasks) will be expressed through WorkItems + AgentCalendar + BookableResource. The `WatchType` enum and `AgentCalendar` in this AD provide the replacement. Tests continue to pass.

---

## Implementation

### File: `src/probos/workforce.py` (NEW)

This is the core module. ~500-600 lines.

#### Imports & Constants

```python
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
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

import aiosqlite

logger = logging.getLogger(__name__)
```

#### Enums

```python
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
```

#### Data Model — Seven Core Entities

##### (1) WorkItem

```python
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
    depends_on: list[str] = field(default_factory=list)  # Finish-to-start dependencies (WorkItem IDs)
    assigned_to: str | None = None      # agent UUID or pool ID
    created_by: str = "captain"         # Who created this work item
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    due_at: float | None = None         # Deadline (epoch)
    estimated_tokens: int | None = None # Token budget estimate
    actual_tokens: int = 0              # Tokens consumed so far
    trust_requirement: float = 0.0      # Minimum trust score for assignment (0.0 = any)
    required_capabilities: list[str] = field(default_factory=list)  # Qualification match
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)  # Type-specific extensions
    steps: list[dict[str, Any]] = field(default_factory=list)  # Ordered sub-steps [{label, status, started_at, duration_ms}]
    verification: dict[str, Any] = field(default_factory=dict)  # How to verify completion
    schedule: dict[str, Any] = field(default_factory=dict)  # For recurring: {type: "cron"|"interval", expr: ..., interval_seconds: ...}
    ttl_seconds: int | None = None      # Auto-cancel after TTL (for Night Orders temporary work)
    template_id: str | None = None      # Source template (AD-498)

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
```

##### (2) BookableResource

```python
@dataclass
class BookableResource:
    """Wrapper around agents adding scheduling dimensions.

    Connects to CognitiveAgent and AgentCommissioningManager (ACM) identity.
    """
    resource_id: str = ""               # Agent UUID (from ACM DID)
    resource_type: str = "crew"         # ResourceType value
    agent_type: str = ""                # e.g., "scout", "security_officer"
    callsign: str = ""                  # Agent callsign for display
    capacity: int = 1                   # Concurrent task limit (default: 1 task at a time)
    calendar_id: str | None = None      # Reference to AgentCalendar
    department: str = ""                # Department name
    characteristics: list[dict[str, Any]] = field(default_factory=list)  # [{skill, proficiency, trust_score}]
    display_on_board: bool = True       # Visibility on schedule views (HXI)
    active: bool = True                 # Is this resource currently available?

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
```

##### (3) ResourceRequirement

```python
@dataclass
class ResourceRequirement:
    """The demand side — what a work item needs to be fulfilled.

    Auto-generated from WorkItem fields or manually specified.
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    work_item_id: str = ""
    duration_estimate_seconds: float | None = None
    from_date: float | None = None      # Scheduling window start
    to_date: float | None = None        # Scheduling window end
    required_characteristics: list[dict[str, Any]] = field(default_factory=list)  # [{skill, min_proficiency}]
    min_trust: float = 0.0
    department_constraint: str | None = None
    priority: int = 3
    resource_preference: dict[str, Any] = field(default_factory=dict)  # {preferred: [], required: [], restricted: []}
    fulfilled: bool = False             # Has a booking been created for this?

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
```

##### (4) Booking

```python
@dataclass
class Booking:
    """Assignment link between resource and work item for a time slot."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    resource_id: str = ""               # Agent UUID
    work_item_id: str = ""
    requirement_id: str | None = None
    status: str = "scheduled"           # BookingStatus value
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None       # Planned end
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
```

##### (5) BookingTimestamp

```python
@dataclass
class BookingTimestamp:
    """Append-only event log of every booking status transition.

    Immutable audit trail — event-sourcing pattern.
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    booking_id: str = ""
    status: str = ""                    # The new status
    timestamp: float = field(default_factory=time.time)
    source: str = "system"              # captain | agent | system | scheduler

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "booking_id": self.booking_id,
            "status": self.status,
            "timestamp": self.timestamp,
            "source": self.source,
        }
```

##### (6) BookingJournal

```python
@dataclass
class BookingJournal:
    """Computed time/token segments derived from timestamps upon booking completion.

    Generated by aggregating BookingTimestamp pairs. Foundation for commercial billing.
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    booking_id: str = ""
    journal_type: str = "working"       # JournalType value
    start_time: float = 0.0
    end_time: float = 0.0
    duration_seconds: float = 0.0
    tokens_consumed: int = 0
    billable: bool = True               # Flag for commercial layer (AD-C-010+)

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
```

##### (7) AgentCalendar

```python
@dataclass
class CalendarEntry:
    """A single work-hour slot in an agent's calendar."""
    day_pattern: str = "*"              # "*" = every day, "mon-fri" = weekdays, "sat,sun" = weekends
    start_hour: int = 0                 # 24-hour (0-23)
    end_hour: int = 24                  # 24-hour (1-24, exclusive)
    capacity: int = 1                   # Concurrent task limit during this window
    repeat_rule: str = ""               # Optional rrule for complex patterns

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
    """Work hours and capacity schedule per agent.

    Availability = CalendarEntries - ExistingBookings - MaintenanceWindows.
    Foundation for watch sections (AD-471).
    """
    resource_id: str = ""               # Agent UUID
    entries: list[CalendarEntry] = field(default_factory=list)
    maintenance_windows: list[dict[str, Any]] = field(default_factory=list)  # [{start, end, reason}]

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "entries": [e.to_dict() for e in self.entries],
            "maintenance_windows": self.maintenance_windows,
        }
```

---

### WorkItemStore — SQLite-backed persistence

Follow the `PersistentTaskStore` pattern exactly:
- `aiosqlite` for async SQLite
- `start()` / `stop()` lifecycle
- `_tick_loop()` for TTL expiry and recurring work item re-scheduling
- `_refresh_snapshot_cache()` for sync-safe `build_state_snapshot()` access
- Config-gated via `WorkforceConfig`

#### SQLite Schema

**Five tables.** BookableResource and AgentCalendar are kept in-memory (populated from ACM agent registry at startup) — they are projections of agent state, not independent persistent entities.

```python
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
```

#### WorkItemStore class

```python
class WorkItemStore:
    """SQLite-backed workforce scheduling engine.

    Follows the PersistentTaskStore lifecycle pattern.
    """

    def __init__(
        self,
        db_path: str | None = None,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
        tick_interval: float = 10.0,
    ):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._emit_event = emit_event
        self._tick_interval = tick_interval
        self._tick_task: asyncio.Task | None = None
        self._running = False
        # In-memory registries (populated from ACM at startup)
        self._resources: dict[str, BookableResource] = {}
        self._calendars: dict[str, AgentCalendar] = {}
        # Snapshot cache for sync-safe access
        self._snapshot_cache: dict[str, Any] = {"work_items": [], "bookings": []}

    # -- Lifecycle --

    async def start(self) -> None:
        """Open DB, create schema, start tick loop."""
        if self.db_path:
            self._db = await aiosqlite.connect(self.db_path)
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

    # -- Event emission --

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self._emit_event:
            self._emit_event(event_type, data)
```

#### WorkItem CRUD Methods

Implement these methods on `WorkItemStore`:

```python
    async def create_work_item(self, **kwargs) -> WorkItem:
        """Create and persist a new work item.

        Validates work_type against known types (extensible).
        Sets created_at and updated_at to now.
        Emits 'work_item_created' event.
        Refreshes snapshot cache.
        """
        # Build WorkItem from kwargs
        # JSON-serialize list/dict fields (depends_on, required_capabilities, tags, metadata, steps, verification, schedule)
        # INSERT into work_items table
        # Auto-generate ResourceRequirement from WorkItem fields (trust_requirement, required_capabilities, etc.)
        # Return WorkItem

    async def get_work_item(self, work_item_id: str) -> WorkItem | None:
        """Fetch a single work item by ID."""

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

    async def update_work_item(self, work_item_id: str, **updates) -> WorkItem | None:
        """Update work item fields. Sets updated_at. Emits 'work_item_updated'."""
        # Only allow updating mutable fields (not id, created_at, created_by)
        # JSON-serialize list/dict fields as needed

    async def transition_work_item(self, work_item_id: str, new_status: str, source: str = "system") -> WorkItem | None:
        """Transition work item status with validation.

        For now, basic validation: no transition FROM terminal states (done, cancelled).
        AD-498 (Work Type Registry) adds per-type state machine validation.
        Sets updated_at. Emits 'work_item_status_changed'.
        """

    async def delete_work_item(self, work_item_id: str) -> bool:
        """Delete a work item and its associated bookings/requirements. Returns True if found."""
        # CASCADE: delete related bookings, timestamps, journals, requirements
```

#### Assignment Engine Methods

```python
    # -- Assignment --

    async def assign_work_item(
        self,
        work_item_id: str,
        resource_id: str,
        source: str = "captain",
    ) -> Booking | None:
        """Push assignment: Captain assigns work directly to an agent.

        Validates: resource exists, resource is active, capacity not exceeded,
        agent meets trust_requirement and required_capabilities.
        Creates Booking (status=scheduled), BookingTimestamp, marks requirement fulfilled.
        Updates WorkItem.assigned_to. Emits 'work_item_assigned'.
        """

    async def claim_work_item(
        self,
        resource_id: str,
        work_type: str | None = None,
        department: str | None = None,
    ) -> tuple[WorkItem, Booking] | None:
        """Pull assignment: Agent claims highest-priority eligible unassigned work.

        Finds work items where: status='open', assigned_to IS NULL,
        agent meets trust_requirement and required_capabilities.
        Optional filters: work_type, department.
        Creates Booking, updates WorkItem. Emits 'work_item_claimed'.
        Returns (WorkItem, Booking) or None if nothing eligible.
        """

    async def unassign_work_item(self, work_item_id: str, reason: str = "") -> bool:
        """Remove assignment. Cancels active booking. Resets assigned_to to NULL."""
```

#### Booking Lifecycle Methods

```python
    # -- Booking lifecycle --

    async def start_booking(self, booking_id: str) -> Booking | None:
        """Transition booking: scheduled → active. Records actual_start. Creates BookingTimestamp."""

    async def pause_booking(self, booking_id: str) -> Booking | None:
        """Transition booking: active → on_break. Creates BookingTimestamp."""

    async def resume_booking(self, booking_id: str) -> Booking | None:
        """Transition booking: on_break → active. Creates BookingTimestamp."""

    async def complete_booking(self, booking_id: str, tokens_consumed: int = 0) -> Booking | None:
        """Transition booking: active → completed.
        Records actual_end, total_tokens_consumed.
        Generates BookingJournal entries from BookingTimestamp pairs.
        Updates WorkItem.actual_tokens.
        Creates BookingTimestamp. Emits 'booking_completed'.
        """

    async def cancel_booking(self, booking_id: str) -> Booking | None:
        """Cancel a booking. Creates BookingTimestamp. Emits 'booking_cancelled'."""

    async def get_booking(self, booking_id: str) -> Booking | None:
        """Fetch a single booking."""

    async def list_bookings(
        self,
        resource_id: str | None = None,
        work_item_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Booking]:
        """List bookings with optional filters."""

    async def get_booking_journal(self, booking_id: str) -> list[BookingJournal]:
        """Get time/token segments for a completed booking."""

    async def generate_journal(self, booking_id: str) -> list[BookingJournal]:
        """Generate journal entries from BookingTimestamp pairs.

        Algorithm:
        1. Fetch all BookingTimestamps for booking, ordered by timestamp
        2. Walk pairs: active→on_break = working segment, on_break→active = break segment, etc.
        3. INSERT journal entries
        4. Return generated entries
        """
```

#### Resource Registry Methods

```python
    # -- Resource registry (in-memory, populated from ACM) --

    def register_resource(self, resource: BookableResource) -> None:
        """Register a bookable resource (called during startup from ACM agent list)."""
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

    def get_resource_availability(self, resource_id: str) -> dict[str, Any]:
        """Calculate availability: calendar entries minus active bookings.

        Returns: {resource_id, capacity, active_bookings: int, available_capacity: int, calendar: {...}}
        For this AD, availability = capacity - count of active bookings (simplified).
        Full calendar-based availability computation deferred to AD-497/commercial.
        """

    # -- Calendar registry (in-memory) --

    def register_calendar(self, calendar: AgentCalendar) -> None:
        """Register an agent calendar."""
        self._calendars[calendar.resource_id] = calendar

    def get_calendar(self, resource_id: str) -> AgentCalendar | None:
        """Get agent calendar."""
        return self._calendars.get(resource_id)
```

#### Capability Matching

```python
    def _check_eligibility(self, resource: BookableResource, work_item: WorkItem) -> bool:
        """Check if a resource is eligible for a work item.

        Checks:
        1. Resource is active
        2. Available capacity (active bookings < capacity)
        3. Trust requirement met (resource characteristics include trust >= work_item.trust_requirement)
        4. Required capabilities met (each required_capability in work_item matched by resource characteristics)
        5. Department constraint (if ResourceRequirement has department_constraint)
        """
```

#### Tick Loop

```python
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
        """Cancel work items past their TTL (for Night Orders temporary work)."""
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
        """Log warnings for overdue work items (due_at passed, not done)."""
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
            logger.warning("Overdue work item %s: '%s' (due %.0fs ago)",
                          row["id"], row["title"], now - row["due_at"])
```

#### Snapshot & Helpers

```python
    # -- Snapshot (sync-safe for build_state_snapshot) --

    def snapshot(self) -> dict[str, Any]:
        """Return cached snapshot for build_state_snapshot."""
        return dict(self._snapshot_cache)

    async def _refresh_snapshot_cache(self) -> None:
        """Rebuild in-memory snapshot cache from DB."""
        if not self._db:
            self._snapshot_cache = {"work_items": [], "bookings": []}
            return
        # Active work items
        cursor = await self._db.execute(
            "SELECT * FROM work_items WHERE status NOT IN ('done', 'cancelled', 'failed') ORDER BY priority ASC, created_at DESC LIMIT 100"
        )
        rows = await cursor.fetchall()
        work_items = [self._row_to_work_item(r).to_dict() for r in rows]
        # Active bookings
        cursor = await self._db.execute(
            "SELECT * FROM bookings WHERE status NOT IN ('completed', 'cancelled') ORDER BY start_time DESC LIMIT 100"
        )
        rows = await cursor.fetchall()
        bookings = [self._row_to_booking(r).to_dict() for r in rows]
        self._snapshot_cache = {"work_items": work_items, "bookings": bookings}

    # -- Row converters --

    @staticmethod
    def _row_to_work_item(row: Any) -> WorkItem:
        """Convert aiosqlite Row to WorkItem. JSON-deserialize list/dict fields."""

    @staticmethod
    def _row_to_booking(row: Any) -> Booking:
        """Convert aiosqlite Row to Booking."""

    @staticmethod
    def _row_to_timestamp(row: Any) -> BookingTimestamp:
        """Convert aiosqlite Row to BookingTimestamp."""

    @staticmethod
    def _row_to_journal(row: Any) -> BookingJournal:
        """Convert aiosqlite Row to BookingJournal."""

    @staticmethod
    def _row_to_requirement(row: Any) -> ResourceRequirement:
        """Convert aiosqlite Row to ResourceRequirement."""
```

---

### Config: `src/probos/config.py`

Add `WorkforceConfig` class alongside existing config classes:

```python
class WorkforceConfig(BaseModel):
    """Workforce Scheduling Engine configuration (AD-496)."""
    enabled: bool = False
    tick_interval_seconds: float = 10.0
    default_capacity: int = 1           # Default concurrent task limit per agent
    ttl_check_interval_seconds: float = 30.0
```

Add to `ProbOSConfig`:

```python
class ProbOSConfig(BaseModel):
    # ... existing fields ...
    workforce: WorkforceConfig = WorkforceConfig()
```

---

### Runtime Integration: `src/probos/runtime.py`

#### Add to ProbOSRuntime.__init__:

```python
self.work_item_store: Any = None  # WorkItemStore | None
```

#### Add to _start_services (after persistent_task_store init, ~line 1294):

```python
# Workforce Scheduling Engine (AD-496)
if self.config.workforce.enabled:
    from probos.workforce import WorkItemStore
    data_dir = Path(self.config.data_dir) if self.config.data_dir else Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    self.work_item_store = WorkItemStore(
        db_path=str(data_dir / "workforce.db"),
        emit_event=self._emit_event,
        tick_interval=self.config.workforce.tick_interval_seconds,
    )
    await self.work_item_store.start()
    # Register agents as BookableResources
    await self._register_workforce_resources()
```

#### Add helper method:

```python
async def _register_workforce_resources(self) -> None:
    """Register all commissioned agents as BookableResources."""
    if not self.work_item_store:
        return
    from probos.workforce import BookableResource, AgentCalendar, CalendarEntry
    for agent in self._agents.values():
        resource = BookableResource(
            resource_id=getattr(agent, 'agent_uuid', '') or agent.agent_id,
            resource_type="crew" if hasattr(agent, 'personality') else "infrastructure",
            agent_type=agent.agent_type,
            callsign=getattr(agent, 'callsign', agent.agent_type),
            capacity=self.config.workforce.default_capacity,
            department=getattr(agent, 'department', ''),
            characteristics=self._build_resource_characteristics(agent),
            display_on_board=hasattr(agent, 'personality'),
            active=True,
        )
        self.work_item_store.register_resource(resource)
        # Default calendar: always available (24/7), single capacity
        calendar = AgentCalendar(
            resource_id=resource.resource_id,
            entries=[CalendarEntry()],  # Default: all day, every day, capacity=1
        )
        self.work_item_store.register_calendar(calendar)

def _build_resource_characteristics(self, agent: Any) -> list[dict[str, Any]]:
    """Build characteristics list from agent capabilities and trust."""
    characteristics = []
    # Add agent_type as a skill
    characteristics.append({
        "skill": agent.agent_type,
        "proficiency": 1.0,
    })
    # Add department as a skill
    dept = getattr(agent, 'department', '')
    if dept:
        characteristics.append({"skill": dept, "proficiency": 1.0})
    # Add trust score from TrustNetwork
    if self.trust_network:
        trust = self.trust_network.get_trust(agent.agent_id)
        characteristics.append({"skill": "trust", "proficiency": trust})
    return characteristics
```

#### Add to build_state_snapshot (after "scheduled_tasks" ~line 517):

```python
"workforce": self.work_item_store.snapshot() if self.work_item_store else {"work_items": [], "bookings": []},
```

#### Add to _stop_services (before persistent_task_store stop):

```python
if self.work_item_store:
    await self.work_item_store.stop()
    self.work_item_store = None
```

---

### REST API: `src/probos/api.py`

Add a new section of endpoints. Place after the scheduled-tasks endpoints.

```python
# ── Workforce Scheduling Engine (AD-496) ──────────────────────────

@app.post("/api/work-items")
async def create_work_item(request: Request) -> dict[str, Any]:
    """Create a new work item."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    item = await runtime.work_item_store.create_work_item(**body)
    return {"work_item": item.to_dict()}

@app.get("/api/work-items")
async def list_work_items(
    status: str | None = None,
    assigned_to: str | None = None,
    work_type: str | None = None,
    parent_id: str | None = None,
    priority: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List work items with filters."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    items = await runtime.work_item_store.list_work_items(
        status=status, assigned_to=assigned_to, work_type=work_type,
        parent_id=parent_id, priority=priority, limit=limit, offset=offset,
    )
    return {"work_items": [i.to_dict() for i in items], "count": len(items)}

@app.get("/api/work-items/{work_item_id}")
async def get_work_item(work_item_id: str) -> dict[str, Any]:
    """Get a work item by ID."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    item = await runtime.work_item_store.get_work_item(work_item_id)
    if not item:
        raise HTTPException(404, "Work item not found")
    return {"work_item": item.to_dict()}

@app.patch("/api/work-items/{work_item_id}")
async def update_work_item(work_item_id: str, request: Request) -> dict[str, Any]:
    """Update work item fields."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    item = await runtime.work_item_store.update_work_item(work_item_id, **body)
    if not item:
        raise HTTPException(404, "Work item not found")
    return {"work_item": item.to_dict()}

@app.post("/api/work-items/{work_item_id}/transition")
async def transition_work_item(work_item_id: str, request: Request) -> dict[str, Any]:
    """Transition work item status."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    item = await runtime.work_item_store.transition_work_item(
        work_item_id, body["status"], source=body.get("source", "captain"),
    )
    if not item:
        raise HTTPException(404, "Work item not found or invalid transition")
    return {"work_item": item.to_dict()}

@app.post("/api/work-items/{work_item_id}/assign")
async def assign_work_item(work_item_id: str, request: Request) -> dict[str, Any]:
    """Push assignment: assign work to a specific agent."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    booking = await runtime.work_item_store.assign_work_item(
        work_item_id, body["resource_id"], source=body.get("source", "captain"),
    )
    if not booking:
        raise HTTPException(400, "Assignment failed (ineligible or no capacity)")
    return {"booking": booking.to_dict()}

@app.post("/api/work-items/claim")
async def claim_work_item(request: Request) -> dict[str, Any]:
    """Pull assignment: agent claims highest-priority eligible work."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    body = await request.json()
    result = await runtime.work_item_store.claim_work_item(
        body["resource_id"],
        work_type=body.get("work_type"),
        department=body.get("department"),
    )
    if not result:
        raise HTTPException(404, "No eligible work items")
    work_item, booking = result
    return {"work_item": work_item.to_dict(), "booking": booking.to_dict()}

@app.delete("/api/work-items/{work_item_id}")
async def delete_work_item(work_item_id: str) -> dict[str, Any]:
    """Delete a work item."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    deleted = await runtime.work_item_store.delete_work_item(work_item_id)
    if not deleted:
        raise HTTPException(404, "Work item not found")
    return {"deleted": True}

# -- Bookings --

@app.get("/api/bookings")
async def list_bookings(
    resource_id: str | None = None,
    work_item_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List bookings with filters."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    bookings = await runtime.work_item_store.list_bookings(
        resource_id=resource_id, work_item_id=work_item_id, status=status, limit=limit,
    )
    return {"bookings": [b.to_dict() for b in bookings], "count": len(bookings)}

@app.get("/api/bookings/{booking_id}/journal")
async def get_booking_journal(booking_id: str) -> dict[str, Any]:
    """Get time/token segments for a booking."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    entries = await runtime.work_item_store.get_booking_journal(booking_id)
    return {"journal": [e.to_dict() for e in entries]}

# -- Resources --

@app.get("/api/resources")
async def list_resources(
    department: str | None = None,
    resource_type: str | None = None,
) -> dict[str, Any]:
    """List bookable resources."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    resources = runtime.work_item_store.list_resources(
        department=department, resource_type=resource_type,
    )
    return {"resources": [r.to_dict() for r in resources], "count": len(resources)}

@app.get("/api/resources/{resource_id}/availability")
async def get_resource_availability(resource_id: str) -> dict[str, Any]:
    """Get resource availability (capacity minus active bookings)."""
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    availability = runtime.work_item_store.get_resource_availability(resource_id)
    if not availability:
        raise HTTPException(404, "Resource not found")
    return availability
```

---

### WebSocket Events

Emit these events (via `self._emit_event`) so HXI can react in real time:

| Event | Payload |
|-------|---------|
| `work_item_created` | `{work_item: {...}}` |
| `work_item_updated` | `{work_item: {...}}` |
| `work_item_status_changed` | `{work_item: {...}, old_status, new_status}` |
| `work_item_assigned` | `{work_item: {...}, booking: {...}, resource: {...}}` |
| `work_item_claimed` | `{work_item: {...}, booking: {...}, resource: {...}}` |
| `booking_started` | `{booking: {...}}` |
| `booking_completed` | `{booking: {...}, journal: [...]}` |
| `booking_cancelled` | `{booking: {...}}` |

---

### Config Default: `config/system.yaml`

Add workforce section:

```yaml
workforce:
  enabled: true
  tick_interval_seconds: 10.0
  default_capacity: 1
```

---

### Tests: `tests/test_workforce.py` (NEW)

Implement comprehensive tests organized into these test classes:

#### TestWorkItemCRUD (~15 tests)

```
test_create_work_item_basic
test_create_work_item_all_fields
test_get_work_item
test_get_work_item_not_found
test_list_work_items_empty
test_list_work_items_filter_status
test_list_work_items_filter_assigned_to
test_list_work_items_filter_work_type
test_list_work_items_filter_parent_id
test_list_work_items_pagination
test_update_work_item
test_update_work_item_not_found
test_transition_work_item
test_transition_from_terminal_status_rejected
test_delete_work_item_cascades
```

#### TestAssignmentEngine (~10 tests)

```
test_push_assign_basic
test_push_assign_creates_booking
test_push_assign_ineligible_trust
test_push_assign_ineligible_capacity
test_push_assign_ineligible_capabilities
test_pull_claim_highest_priority
test_pull_claim_respects_trust_requirement
test_pull_claim_no_eligible_returns_none
test_pull_claim_filter_work_type
test_unassign_work_item
```

#### TestBookingLifecycle (~10 tests)

```
test_booking_start
test_booking_pause_resume
test_booking_complete
test_booking_cancel
test_booking_timestamps_appended
test_generate_journal_working_segment
test_generate_journal_with_break
test_complete_booking_generates_journal
test_list_bookings_filter_resource
test_list_bookings_filter_status
```

#### TestResourceRegistry (~8 tests)

```
test_register_resource
test_unregister_resource
test_list_resources_filter_department
test_list_resources_filter_type
test_list_resources_active_only
test_get_resource_availability_basic
test_get_resource_availability_with_active_bookings
test_eligibility_check
```

#### TestWorkItemStoreTick (~5 tests)

```
test_ttl_expiry
test_ttl_not_expired_ignored
test_overdue_item_logged
test_tick_loop_starts_and_stops
test_snapshot_cache_refreshed
```

#### TestWorkforceAPI (~12 tests)

```
test_api_create_work_item
test_api_list_work_items
test_api_get_work_item
test_api_update_work_item
test_api_transition_work_item
test_api_assign_work_item
test_api_claim_work_item
test_api_delete_work_item
test_api_list_bookings
test_api_get_booking_journal
test_api_list_resources
test_api_get_resource_availability
test_api_disabled_returns_503
```

#### TestWorkforceSnapshot (~3 tests)

```
test_snapshot_includes_active_items
test_snapshot_excludes_terminal_items
test_snapshot_included_in_state_snapshot
```

**Total: ~63 tests**

#### Test patterns to follow:

- Use `aiosqlite` with `":memory:"` for test databases
- Follow existing test patterns from `tests/test_persistent_tasks.py`
- Use `pytest.mark.asyncio` for all async tests
- Create helper fixtures for common setup (store with resources registered, store with work items)
- Mock `emit_event` to verify event emission

---

### Tracking Updates

Update these files to reflect AD-496 status:

#### PROGRESS.md
- Change AD-496 status from `PLANNED` to `COMPLETE`

#### DECISIONS.md
- Add AD-496 decision entry documenting: WorkItemStore as SQLite-backed engine following PersistentTaskStore pattern, coexistence strategy (TaskTracker deprecated, PersistentTaskStore/BuildQueue/DutyScheduleTracker coexist), 7 core entities, assignment engine (push/pull/offer)

#### docs/development/roadmap.md
- Mark AD-496 as *(complete)* in the roadmap section

#### dashboard.html
- Update stats, move AD-496 to completed, adjust "Up Next" cards

---

## Recommendations & Unconsidered Items

### Included in this AD (should be built):

1. **TTL field on WorkItem** — Added `ttl_seconds` field. Night Orders (AD-471) creates temporary WorkItems with TTL; the tick loop auto-cancels expired ones. Not in the original roadmap spec but essential for AD-471.

2. **Template reference on WorkItem** — Added `template_id` field. When AD-498 templates create WorkItems, they stamp their origin. Needed for traceability.

3. **`updated_at` field on WorkItem** — Not in original spec but critical for conflict detection, cache invalidation, and sorting by recency.

4. **Database indexes** — Added indexes on frequently-queried columns (status, assigned_to, work_type, parent_id, resource_id, booking_id). Essential for performance as work items accumulate.

5. **Cascade deletes** — Deleting a WorkItem cascades to bookings, timestamps, journals, and requirements. Without this, orphan records accumulate.

### Deferred to AD-498 (Work Type Registry):

6. **Per-type state machine validation** — AD-496 does basic validation (no transitions from terminal states). AD-498 adds formal state machine per work type with valid transition matrix.

7. **Template instantiation endpoint** — `POST /api/work-items/from-template/{template_id}` belongs in AD-498.

### Deferred to AD-497 (HXI Surface):

8. **Scrumban Board WebSocket hydration** — The events and snapshot are ready. AD-497 builds the frontend.

9. **Work Tab in Agent Profile** — AD-497 adds the "Work" tab showing active/completed/blocked items per agent.

### Deferred to AD-471 (Autonomous Operations):

10. **Night Orders creating WorkItems** — AD-471 rewrite will use `create_work_item(ttl_seconds=..., work_type="task")` instead of standalone CaptainOrders.

11. **Watch sections mapped to AgentCalendar** — The calendar infrastructure is ready; AD-471 populates it with watch section patterns (Alpha/Beta/Gamma → calendar entries).

### Deferred to commercial (AD-C-010+):

12. **Billing integration** — BookingJournal.billable flag is set but no billing logic. Commercial AD-C-015 (ACM Integration) uses journals for cost calculation.

13. **Scheduling optimization** — Offer-based assignment with timeout escalation. Commercial Schedule Board (AD-C-010).

14. **Capacity planning** — Full calendar-based availability with maintenance windows. Commercial AD-C-012.

### Considerations for the architect:

15. **DutyScheduleTracker migration timing** — Currently duties fire via proactive loop's `_think_for_agent()`. When AD-498 adds `duty` work type, DutyScheduleTracker should be evolved to generate WorkItems instead of directly triggering thinks. This is a breaking change to the proactive loop and should be its own AD.

16. **TaskTracker removal timing** — TaskTracker is orphaned but has 32 tests and is wired into `build_state_snapshot()`. Plan a cleanup AD that: moves NotificationQueue to its own file, removes TaskTracker class, updates tests, removes snapshot entry. Not urgent.

17. **BuildQueue migration** — The builder pipeline (BuildQueue + BuildReviewer) is well-encapsulated. Migrating builds to WorkItems (type=`work_order`) would unify all work tracking but risks breaking a working pipeline. Evaluate after AD-498 proves stable.

18. **ResourceRequirement auto-generation** — When creating a WorkItem with `trust_requirement` or `required_capabilities`, auto-generate a `ResourceRequirement` row. This keeps the URS "demand side" populated without requiring explicit requirement creation. Implemented in `create_work_item()`.

19. **Event consistency** — All state changes go through methods that emit events. No direct SQL updates bypassing the event system. This ensures HXI stays in sync.

20. **Database file location** — `data/workforce.db` alongside existing `data/scheduled_tasks.db`. Follow the same data directory pattern.

---

## Build Checklist

The builder should execute in this order:

1. [ ] Create `src/probos/workforce.py` — all 7 entities + WorkItemStore + all methods
2. [ ] Add `WorkforceConfig` to `src/probos/config.py`
3. [ ] Add `workforce:` section to `config/system.yaml`
4. [ ] Wire into `src/probos/runtime.py` — init, start, snapshot, stop, resource registration
5. [ ] Add REST API endpoints to `src/probos/api.py`
6. [ ] Create `tests/test_workforce.py` — all ~63 tests
7. [ ] Run targeted tests: `pytest tests/test_workforce.py -v`
8. [ ] Run existing tests to verify no regressions: `pytest tests/test_persistent_tasks.py tests/test_task_tracker.py tests/test_task_panel.py tests/test_build_queue.py tests/test_duty_schedule.py tests/test_watch_rotation.py -v`
9. [ ] Update PROGRESS.md, DECISIONS.md, roadmap.md, dashboard.html
