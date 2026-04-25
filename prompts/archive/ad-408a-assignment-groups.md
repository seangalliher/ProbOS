# AD-408a: Dynamic Assignment Groups — Backend Foundation

## Context

Agents have a permanent **department** (pool group) and optional temporary **assignments** (where they're working now). Assignments are transient overlays — they don't change pool membership or agent routing. They provide visual clustering on the canvas and auto-create Ward Room channels.

**Design document:** `docs/development/assignment-groups-design.md` — read this first for full context.

**Key concept:** Three assignment types — Bridge (session-scoped, auto-activates), Away Team (mission-scoped, auto-dissolves), Working Group (open-ended, Captain dissolves). All assignments auto-create a Ward Room channel for team communication.

## Part 1: AssignmentService (`src/probos/assignment.py`)

Create the `AssignmentService` class following the same patterns as `WardRoomService` (see `src/probos/ward_room.py`).

### Data Classes

```python
from dataclasses import dataclass, field
import uuid
import time

@dataclass
class Assignment:
    id: str
    name: str
    assignment_type: str          # "bridge" | "away_team" | "working_group"
    members: list[str]            # agent_ids
    created_by: str               # "captain" or agent_id
    created_at: float
    completed_at: float | None = None
    mission: str = ""             # Brief description of purpose
    ward_room_channel_id: str = ""  # Auto-created Ward Room channel
    status: str = "active"        # "active" | "completed" | "dissolved"
```

### SQLite Schema

```python
import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assignments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    assignment_type TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    completed_at REAL,
    mission TEXT NOT NULL DEFAULT '',
    ward_room_channel_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS assignment_members (
    assignment_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    joined_at REAL NOT NULL,
    PRIMARY KEY (assignment_id, agent_id),
    FOREIGN KEY (assignment_id) REFERENCES assignments(id)
);
"""
```

### AssignmentService Class

```python
class AssignmentService:
    """Dynamic assignment groups — transient team overlays on the static department structure."""

    def __init__(self, db_path: str | None = None, emit_event=None, ward_room=None):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._emit_event = emit_event
        self._ward_room = ward_room  # WardRoomService reference for auto-channel creation

    async def start(self) -> None:
        if self.db_path:
            self._db = await aiosqlite.connect(self.db_path)
            await self._db.executescript(_SCHEMA)
            await self._db.commit()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
```

### Required Methods

**CRUD operations:**

- `async def create_assignment(name, assignment_type, created_by, members, mission="") -> Assignment`
  - Validate: `assignment_type` is one of "bridge", "away_team", "working_group"
  - Validate: `members` is non-empty list of agent_ids
  - Validate: no duplicate active assignment with same name
  - Generate UUID for assignment ID
  - Insert assignment record + member records
  - **If Ward Room is available** (`self._ward_room` is not None):
    - Create a Ward Room channel: `channel_type="custom"`, name=assignment name, `created_by=created_by`
    - Subscribe all members to the channel
    - Store the `ward_room_channel_id` on the assignment
  - Emit `assignment_created` event with full assignment data
  - Return the Assignment

- `async def get_assignment(assignment_id) -> Assignment | None`
  - Load assignment + members from DB
  - Return None if not found

- `async def list_assignments(status="active") -> list[Assignment]`
  - Return all assignments matching status filter
  - Include member lists
  - Sort by `created_at` desc

- `async def add_member(assignment_id, agent_id) -> Assignment`
  - Validate assignment exists and is active
  - Validate agent not already a member
  - Insert member record
  - If Ward Room channel exists, subscribe the agent
  - Emit `assignment_updated` event
  - Return updated assignment

- `async def remove_member(assignment_id, agent_id) -> Assignment`
  - Validate assignment exists and is active
  - Remove member record
  - If no members remain, auto-dissolve the assignment
  - Emit `assignment_updated` event
  - Return updated assignment

- `async def complete_assignment(assignment_id) -> Assignment`
  - Set `status = "completed"`, `completed_at = time.time()`
  - If Ward Room channel exists, archive it (set `archived = True` on the channel via ward_room)
  - Emit `assignment_completed` event
  - Return updated assignment

- `async def dissolve_assignment(assignment_id) -> Assignment`
  - Set `status = "dissolved"`, `completed_at = time.time()`
  - If Ward Room channel exists, archive it
  - Emit `assignment_completed` event (same event type, status distinguishes)
  - Return updated assignment

- `async def get_agent_assignments(agent_id) -> list[Assignment]`
  - Return all active assignments where agent is a member

- `async def get_assignment_snapshot() -> list[dict]`
  - Return all active assignments as dicts (for WebSocket state_snapshot)
  - Used by runtime to include assignments in state broadcast

**Event emission:**

- `_emit(event_type, data)` — Same pattern as WardRoomService: calls `self._emit_event({"type": event_type, "data": data, "timestamp": time.time()})` if callback is set.

### Important Implementation Notes

- All DB operations need `if not self._db: return` guards (in-memory mode for testing).
- Ward Room integration is optional — if `self._ward_room` is None, skip channel creation/subscription. This allows the assignment system to work independently of the Ward Room feature flag.
- When archiving a Ward Room channel on assignment completion, catch any errors gracefully (channel might not exist if Ward Room was disabled when assignment was created).
- Generate IDs with `str(uuid.uuid4())`.

## Part 2: Config (`src/probos/config.py`)

Add assignment config:

```python
class AssignmentConfig(BaseModel):
    """Dynamic assignment groups configuration (AD-408)."""

    enabled: bool = False  # Disabled by default — enable after HXI surface is ready
```

Add to `SystemConfig`:

```python
assignments: AssignmentConfig = AssignmentConfig()
```

## Part 3: Runtime Integration (`src/probos/runtime.py`)

### In `__init__`:

```python
self.assignment_service: Any | None = None  # Initialized in start()
```

### In `start()`:

After Ward Room initialization (so ward_room reference is available):

```python
if self.config.assignments.enabled:
    from probos.assignment import AssignmentService
    self.assignment_service = AssignmentService(
        db_path=str(self._data_dir / "assignments.db"),
        emit_event=self._emit_event,
        ward_room=self.ward_room,  # May be None if WR disabled
    )
    await self.assignment_service.start()
    logger.info("assignment-service started")
```

### In `stop()`:

```python
if self.assignment_service:
    await self.assignment_service.stop()
    self.assignment_service = None
```

### In `build_state_snapshot()`:

```python
if self.assignment_service:
    result["assignments"] = await self.assignment_service.get_assignment_snapshot()
```

Note: `build_state_snapshot()` is NOT async in the current codebase. If `get_assignment_snapshot()` needs to be async (for DB access), either:
- Make it sync by caching the snapshot in memory, OR
- Add `assignments` to the snapshot via a separate mechanism

Check the current `build_state_snapshot()` signature. If it's sync, make `get_assignment_snapshot()` sync by maintaining an in-memory cache of active assignments that updates on every create/complete/dissolve/member change. This avoids making the snapshot async.

## Part 4: API Endpoints (`src/probos/api.py`)

Add these routes inside `create_app()`. Add Pydantic models at module level.

### Pydantic Models

```python
class CreateAssignmentRequest(BaseModel):
    name: str
    assignment_type: str  # "bridge" | "away_team" | "working_group"
    members: list[str]    # agent_ids
    created_by: str = "captain"
    mission: str = ""

class ModifyMembersRequest(BaseModel):
    agent_id: str
    action: str = "add"  # "add" | "remove"
```

### Routes

```python
# --- Assignments (AD-408) ---

@app.get("/api/assignments")
async def list_assignments(status: str = "active"):
    if not runtime.assignment_service:
        return {"assignments": []}
    assignments = await runtime.assignment_service.list_assignments(status=status)
    return {"assignments": [vars(a) for a in assignments]}

@app.post("/api/assignments")
async def create_assignment(req: CreateAssignmentRequest):
    if not runtime.assignment_service:
        raise HTTPException(503, "Assignment service not available")
    try:
        assignment = await runtime.assignment_service.create_assignment(
            name=req.name,
            assignment_type=req.assignment_type,
            created_by=req.created_by,
            members=req.members,
            mission=req.mission,
        )
        return vars(assignment)
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.get("/api/assignments/{assignment_id}")
async def get_assignment(assignment_id: str):
    if not runtime.assignment_service:
        raise HTTPException(503, "Assignment service not available")
    assignment = await runtime.assignment_service.get_assignment(assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    return vars(assignment)

@app.post("/api/assignments/{assignment_id}/members")
async def modify_assignment_members(assignment_id: str, req: ModifyMembersRequest):
    if not runtime.assignment_service:
        raise HTTPException(503, "Assignment service not available")
    try:
        if req.action == "remove":
            assignment = await runtime.assignment_service.remove_member(assignment_id, req.agent_id)
        else:
            assignment = await runtime.assignment_service.add_member(assignment_id, req.agent_id)
        return vars(assignment)
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.post("/api/assignments/{assignment_id}/complete")
async def complete_assignment(assignment_id: str):
    if not runtime.assignment_service:
        raise HTTPException(503, "Assignment service not available")
    try:
        assignment = await runtime.assignment_service.complete_assignment(assignment_id)
        return vars(assignment)
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.delete("/api/assignments/{assignment_id}")
async def dissolve_assignment(assignment_id: str):
    if not runtime.assignment_service:
        raise HTTPException(503, "Assignment service not available")
    try:
        assignment = await runtime.assignment_service.dissolve_assignment(assignment_id)
        return vars(assignment)
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.get("/api/assignments/agent/{agent_id}")
async def agent_assignments(agent_id: str):
    if not runtime.assignment_service:
        return {"assignments": []}
    assignments = await runtime.assignment_service.get_agent_assignments(agent_id)
    return {"assignments": [vars(a) for a in assignments]}
```

## Part 5: Frontend Store Types (`ui/src/store/types.ts`)

Add after Ward Room types:

```typescript
// Assignment types (AD-408)

export interface Assignment {
  id: string;
  name: string;
  assignment_type: 'bridge' | 'away_team' | 'working_group';
  members: string[];
  created_by: string;
  created_at: number;
  completed_at: number | null;
  mission: string;
  ward_room_channel_id: string;
  status: 'active' | 'completed' | 'dissolved';
}
```

## Part 6: Frontend Store (`ui/src/store/useStore.ts`)

Add state and WebSocket handlers:

### State additions:

```typescript
// In HXIState interface:
assignments: Assignment[];

// In initial state:
assignments: [],
```

### State snapshot handler:

In the `state_snapshot` handler, after existing hydration:

```typescript
if ((data as any).assignments) {
  set({ assignments: (data as any).assignments as Assignment[] });
}
```

### WebSocket event handlers:

```typescript
case 'assignment_created':
case 'assignment_updated':
case 'assignment_completed': {
    // For now, just update the assignments list
    // Full canvas integration is Phase 2 (AD-408b)
    // Refetch from snapshot on next reconnect
    break;
}
```

## Part 7: Tests (`tests/test_assignment.py`)

Create comprehensive tests. Use `pytest` and `pytest-asyncio`.

```python
import pytest
import pytest_asyncio
from probos.assignment import AssignmentService, Assignment


@pytest_asyncio.fixture
async def assignment_service(tmp_path):
    events = []
    def capture_event(event):
        events.append(event)

    svc = AssignmentService(
        db_path=str(tmp_path / "assignments.db"),
        emit_event=capture_event,
    )
    await svc.start()
    svc._captured_events = events
    yield svc
    await svc.stop()


@pytest_asyncio.fixture
async def assignment_with_wardroom(tmp_path):
    """Assignment service with a real WardRoomService for integration tests."""
    from probos.ward_room import WardRoomService

    events = []
    def capture_event(event):
        events.append(event)

    wr = WardRoomService(
        db_path=str(tmp_path / "ward_room.db"),
        emit_event=capture_event,
    )
    await wr.start()

    svc = AssignmentService(
        db_path=str(tmp_path / "assignments.db"),
        emit_event=capture_event,
        ward_room=wr,
    )
    await svc.start()
    svc._captured_events = events
    yield svc
    await svc.stop()
    await wr.stop()
```

### Required Test Cases

**Basic CRUD:**
1. `test_create_away_team` — Create away team, verify fields populated
2. `test_create_bridge_assignment` — Create bridge assignment
3. `test_create_working_group` — Create working group
4. `test_invalid_assignment_type_rejected` — Invalid type raises ValueError
5. `test_empty_members_rejected` — Empty members list raises ValueError
6. `test_duplicate_name_rejected` — Duplicate active assignment name raises ValueError
7. `test_get_assignment` — Retrieve by ID
8. `test_get_nonexistent_returns_none` — Nonexistent ID returns None
9. `test_list_active_assignments` — Lists only active assignments
10. `test_list_completed_assignments` — Lists completed assignments when filtered

**Member management:**
11. `test_add_member` — Add member to existing assignment
12. `test_add_duplicate_member_rejected` — Adding existing member raises ValueError
13. `test_remove_member` — Remove member from assignment
14. `test_remove_last_member_auto_dissolves` — Removing last member auto-dissolves
15. `test_get_agent_assignments` — Get all active assignments for an agent

**Lifecycle:**
16. `test_complete_assignment` — Complete sets status and completed_at
17. `test_dissolve_assignment` — Dissolve sets status to "dissolved"
18. `test_complete_already_completed_rejected` — Completing inactive assignment raises ValueError

**Ward Room integration:**
19. `test_create_with_wardroom_creates_channel` — When WardRoomService available, channel auto-created (use `assignment_with_wardroom` fixture)
20. `test_create_with_wardroom_subscribes_members` — Members auto-subscribed to channel
21. `test_add_member_with_wardroom_subscribes` — New member auto-subscribed
22. `test_complete_archives_wardroom_channel` — Completing archives the WR channel
23. `test_create_without_wardroom_works` — When ward_room=None, assignment works without channel

**Event emission:**
24. `test_create_emits_event` — Creating emits `assignment_created`
25. `test_add_member_emits_event` — Adding member emits `assignment_updated`
26. `test_complete_emits_event` — Completing emits `assignment_completed`

**Snapshot:**
27. `test_get_assignment_snapshot` — Returns all active assignments as dicts

### API Tests (`tests/test_api_assignment.py`)

Create a separate test file for API tests. Mirror the fixture pattern from `tests/test_api_wardroom.py`.

**Required API tests:**
1. `test_list_assignments_empty` — GET returns empty list when none exist
2. `test_create_assignment` — POST creates assignment, GET retrieves it
3. `test_add_remove_member` — POST members endpoint works
4. `test_complete_assignment` — POST complete endpoint works
5. `test_dissolve_assignment` — DELETE dissolves assignment
6. `test_agent_assignments` — GET agent assignments returns correct list
7. `test_assignment_not_found` — GET nonexistent returns 404

## Verification

```bash
# Assignment service tests
uv run pytest tests/test_assignment.py -v --tb=short

# Assignment API tests
uv run pytest tests/test_api_assignment.py -v --tb=short

# Ward Room tests still pass (integration)
uv run pytest tests/test_ward_room.py -v --tb=short

# Full regression
uv run pytest tests/ --tb=short -q

# Frontend build
cd ui && npm run build
```

All tests must pass. Zero TypeScript build errors.

## Commit Message

```
Add dynamic assignment groups backend (AD-408a)

AssignmentService with bridge, away team, and working group types.
SQLite persistence, Ward Room channel auto-creation, 7 API endpoints,
WebSocket events. Phase 1 backend only — no canvas integration yet.
```

## What NOT to Build

- Canvas layout changes (Phase 2 — AD-408b)
- Shell commands `/assign` (Phase 3 — AD-408c)
- Bridge auto-activation on Captain login (Phase 3)
- Smooth agent position animation (Phase 2)
- Transient cluster rendering (Phase 2)
- Ghost department connection lines (Phase 2)
