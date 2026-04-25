# AD-497: Work Tab & Scrumban Board — HXI Surface

## Objective

Build the Captain's workforce management interface in HXI. Two deliverables:

1. **Agent Profile Work Tab** — Rewrite `ProfileWorkTab.tsx` to display an agent's WorkItems, bookings, and duty schedule from the AD-496 Workforce Scheduling Engine.
2. **Crew Scrumban Board** — New full-page board view showing all crew WorkItems as draggable cards across Kanban columns with WIP limits, filters, swim lanes, and real-time updates.

Both consume the AD-496 REST API (14 endpoints already built) and the `workforce` key in the state snapshot (already emitted at `runtime.py:521`).

---

## Design Principles

- **HXI Cockpit View Principle:** "The Captain always needs the stick." Every agent-mediated capability must have a direct manual control in HXI.
- **Subsumes AD-420:** The duty schedule display planned in AD-420 is delivered here inside the Work Tab. AD-420 becomes "delivered via AD-497."
- **Build on AD-496:** Do NOT create new backend data models. All data comes from WorkItemStore endpoints. Do NOT duplicate task tracking — this replaces the old `AgentTaskView` display.
- **Existing patterns:** Follow the Zustand store pattern, WebSocket event handler pattern, and component structure already established in the codebase.

---

## Existing Infrastructure (DO NOT RECREATE)

### Backend (already built, AD-496)

**REST API endpoints** (`api.py:2395-2543`):
| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/work-items` | Create work item |
| `GET` | `/api/work-items` | List with filters: `status`, `assigned_to`, `work_type`, `parent_id`, `priority`, `limit`, `offset` |
| `GET` | `/api/work-items/{id}` | Get by ID |
| `PATCH` | `/api/work-items/{id}` | Update fields |
| `POST` | `/api/work-items/{id}/transition` | Status transition (`{"status": "in_progress"}`) |
| `POST` | `/api/work-items/{id}/assign` | Push assignment (`{"resource_id": "..."}`) |
| `POST` | `/api/work-items/claim` | Pull assignment (`{"resource_id": "...", "capabilities": [...]}`) |
| `DELETE` | `/api/work-items/{id}` | Delete |
| `GET` | `/api/bookings` | List bookings: `resource_id`, `work_item_id`, `status`, `limit` |
| `GET` | `/api/bookings/{id}/journal` | Time/token segments |
| `GET` | `/api/resources` | List bookable resources: `department`, `resource_type` |
| `GET` | `/api/resources/{id}/availability` | Capacity minus active bookings |

All endpoints return 503 if `work_item_store` is not enabled.

**State snapshot** (`runtime.py:521`):
```python
"workforce": self.work_item_store.snapshot() if self.work_item_store else {"work_items": [], "bookings": []}
```
Snapshot returns active work items (excluding done/cancelled/failed) and active bookings (excluding completed/cancelled), max 100 each. Each item is a `to_dict()` serialization.

**WorkItem `to_dict()` shape** (26 fields):
```json
{
  "id": "a1b2c3d4e5f6",
  "title": "Security audit",
  "description": "...",
  "work_type": "task",
  "status": "open",
  "priority": 3,
  "parent_id": null,
  "depends_on": [],
  "assigned_to": null,
  "created_by": "captain",
  "created_at": 1711612800.0,
  "updated_at": 1711612800.0,
  "due_at": null,
  "estimated_tokens": 50000,
  "actual_tokens": 0,
  "trust_requirement": 0.0,
  "required_capabilities": ["security"],
  "tags": [],
  "metadata": {},
  "steps": [],
  "verification": null,
  "schedule": null,
  "ttl_seconds": null,
  "template_id": null
}
```

**Booking `to_dict()` shape** (10 fields):
```json
{
  "id": "b1c2d3e4f5g6",
  "resource_id": "agent-uuid",
  "work_item_id": "a1b2c3d4e5f6",
  "requirement_id": null,
  "status": "active",
  "start_time": 1711612800.0,
  "end_time": null,
  "actual_start": 1711612800.0,
  "actual_end": null,
  "total_tokens_consumed": 12500
}
```

**BookableResource `to_dict()` shape** (10 fields):
```json
{
  "resource_id": "agent-uuid",
  "resource_type": "crew",
  "agent_type": "SecurityAgent",
  "callsign": "Worf",
  "capacity": 1,
  "calendar_id": null,
  "department": "Security",
  "characteristics": [{"name": "security", "value": "expert"}],
  "display_on_board": true,
  "active": true
}
```

**Enums** (for mapping status → column):
- `WorkItemStatus`: draft, open, scheduled, in_progress, review, done, failed, cancelled, blocked
- `BookingStatus`: scheduled, active, on_break, completed, cancelled

### Frontend (existing patterns to follow)

**Zustand store** (`useStore.ts`):
- State shape defined in single `create()` call
- Event handlers in `case` switch on `event.type` inside the WebSocket message handler
- Existing pattern for task events at lines 1107-1130 maps `task_created`/`task_updated` → `agentTasks` + `missionControlTasks`
- `mainViewer: 'canvas' | 'kanban' | 'system'` at line 211 controls which view renders

**Types** (`types.ts`):
- All interfaces defined in this single file
- `MissionControlTask` (line 128-142) — existing kanban card type (build queue only)
- `AgentTaskView` (line 151-170) — per-agent task view (old TaskTracker)
- `StateSnapshot` (line 211-241) — no workforce fields yet

**WebSocket events** (`runtime._emit_event()`):
- Pattern: `runtime._emit_event("event_name", {"key": value})` in api.py
- Received in useStore.ts WebSocket handler, dispatched by `event.type`
- Events broadcast to all connected clients via `_broadcast_event()`

**Agent Profile Panel** (`AgentProfilePanel.tsx`):
- 4 tabs: Chat / Work / Profile / Health
- Work tab currently renders `ProfileWorkTab.tsx` (86 lines, only shows old `AgentTaskView`)
- Panel is 420×580px, draggable, has glass styling

**View switching** (`ViewSwitcher.tsx`):
- 3 tabs: CANVAS / KANBAN / SYSTEM
- Sets `mainViewer` store state
- `App.tsx` renders: `canvas` → `CognitiveCanvas`, `kanban` → `FullKanban`, `system` → `FullSystem`

**Existing FullKanban** (`FullKanban.tsx`, 202 lines):
- Shows `MissionControlTask` items only (build queue)
- 4 columns: QUEUED / WORKING / REVIEW / DONE
- No drag-and-drop, display-only
- This component stays as-is — the new Scrumban board is a SEPARATE view

---

## Part 1: TypeScript Types

**File: `ui/src/store/types.ts`**

Add these interfaces (place after `ScheduledTaskView`, before `ServiceStatus`):

```typescript
// AD-497: Workforce types (mirrors workforce.py to_dict() shapes)

export interface WorkItemView {
  id: string;
  title: string;
  description: string;
  work_type: string;           // card | task | work_order | duty | incident
  status: string;              // draft | open | scheduled | in_progress | review | done | failed | cancelled | blocked
  priority: number;            // 1 (critical) - 5 (low)
  parent_id: string | null;
  depends_on: string[];
  assigned_to: string | null;  // resource_id (= agent UUID)
  created_by: string;
  created_at: number;
  updated_at: number;
  due_at: number | null;
  estimated_tokens: number;
  actual_tokens: number;
  trust_requirement: number;
  required_capabilities: string[];
  tags: string[];
  metadata: Record<string, unknown>;
  steps: Array<{ label: string; status: string }>;
  verification: string | null;
  schedule: string | null;
  ttl_seconds: number | null;
  template_id: string | null;
}

export interface BookingView {
  id: string;
  resource_id: string;
  work_item_id: string;
  requirement_id: string | null;
  status: string;              // scheduled | active | on_break | completed | cancelled
  start_time: number;
  end_time: number | null;
  actual_start: number | null;
  actual_end: number | null;
  total_tokens_consumed: number;
}

export interface BookableResourceView {
  resource_id: string;
  resource_type: string;       // crew | infrastructure | utility
  agent_type: string;
  callsign: string;
  capacity: number;
  calendar_id: string | null;
  department: string;
  characteristics: Array<{ name: string; value: string }>;
  display_on_board: boolean;
  active: boolean;
}

export type ScrumbanColumn = 'backlog' | 'ready' | 'in_progress' | 'review' | 'done';
```

**Update `StateSnapshot`** to include workforce:
```typescript
// Add to StateSnapshot interface:
workforce: {
  work_items: WorkItemView[];
  bookings: BookingView[];
};
```

**Update `mainViewer`** union type wherever it appears:
```typescript
mainViewer: 'canvas' | 'kanban' | 'system' | 'work';
```

---

## Part 2: Zustand Store Additions

**File: `ui/src/store/useStore.ts`**

### New state fields

Add after `agentTasks` (line 212):
```typescript
workItems: WorkItemView[] | null;
workBookings: BookingView[] | null;
bookableResources: BookableResourceView[] | null;
```

Add corresponding initializers in the store creation (set to `null`).

### Snapshot hydration

In the existing snapshot hydration handler (where `state_snapshot` is processed), add:
```typescript
if (snapshot.workforce) {
  set({
    workItems: snapshot.workforce.work_items?.length ? snapshot.workforce.work_items : null,
    workBookings: snapshot.workforce.bookings?.length ? snapshot.workforce.bookings : null,
  });
}
```

### New WebSocket event handlers

Add these `case` blocks in the WebSocket event switch (after the `task_created`/`task_updated` block around line 1130):

```typescript
case 'work_item_created':
case 'work_item_updated':
case 'work_item_assigned': {
  // Re-fetch work items from snapshot — simplest approach
  // The event data contains the affected item; merge into existing state
  const item = data.work_item as WorkItemView;
  if (item) {
    const current = get().workItems || [];
    const idx = current.findIndex(w => w.id === item.id);
    if (idx >= 0) {
      const updated = [...current];
      updated[idx] = item;
      set({ workItems: updated });
    } else {
      set({ workItems: [...current, item] });
    }
  }
  break;
}

case 'work_item_deleted': {
  const deletedId = data.work_item_id as string;
  if (deletedId) {
    const current = get().workItems || [];
    set({ workItems: current.filter(w => w.id !== deletedId) });
  }
  break;
}

case 'booking_status_changed': {
  const booking = data.booking as BookingView;
  if (booking) {
    const current = get().workBookings || [];
    const idx = current.findIndex(b => b.id === booking.id);
    if (idx >= 0) {
      const updated = [...current];
      updated[idx] = booking;
      set({ workBookings: updated });
    } else {
      set({ workBookings: [...current, booking] });
    }
  }
  break;
}
```

### New actions

Add helper actions for the Scrumban board:
```typescript
moveWorkItem: async (itemId: string, newStatus: string) => {
  try {
    const resp = await fetch(`/api/work-items/${itemId}/transition`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
    });
    if (!resp.ok) throw new Error(await resp.text());
  } catch (e) {
    console.error('Failed to move work item:', e);
  }
},

assignWorkItem: async (itemId: string, resourceId: string) => {
  try {
    const resp = await fetch(`/api/work-items/${itemId}/assign`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resource_id: resourceId }),
    });
    if (!resp.ok) throw new Error(await resp.text());
  } catch (e) {
    console.error('Failed to assign work item:', e);
  }
},

createWorkItem: async (item: { title: string; priority?: number; work_type?: string; assigned_to?: string; description?: string }) => {
  try {
    const resp = await fetch('/api/work-items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(item),
    });
    if (!resp.ok) throw new Error(await resp.text());
  } catch (e) {
    console.error('Failed to create work item:', e);
  }
},
```

---

## Part 3: Backend — WebSocket Event Emission

**File: `src/probos/api.py`**

The AD-496 endpoints currently return JSON but do NOT emit WebSocket events. Add `_broadcast_event()` calls to notify HXI of changes.

**After successful `create_work_item`** (after `return`):
```python
item = await runtime.work_item_store.create_work_item(**body)
_broadcast_event({"type": "work_item_created", "data": {"work_item": item.to_dict()}})
return {"work_item": item.to_dict()}
```

**After successful `update_work_item`** (PATCH):
```python
_broadcast_event({"type": "work_item_updated", "data": {"work_item": result.to_dict()}})
```

**After successful `transition_work_item`**:
```python
_broadcast_event({"type": "work_item_updated", "data": {"work_item": result.to_dict()}})
```

**After successful `assign_work_item`**:
```python
_broadcast_event({"type": "work_item_assigned", "data": {"work_item": result["work_item"], "booking": result.get("booking")}})
```
(Verify the return shape from `work_item_store.push_assign()` — it may return a dict with work_item and booking keys, or just the work item. Adapt accordingly.)

**After successful `claim_work_item`**:
```python
_broadcast_event({"type": "work_item_assigned", "data": {"work_item": result.to_dict() if hasattr(result, 'to_dict') else result}})
```

**After successful `delete_work_item`**:
```python
_broadcast_event({"type": "work_item_deleted", "data": {"work_item_id": item_id}})
```

**Pattern reference:** See how `build_queue_update` is emitted at `api.py:1451` after build queue mutations.

---

## Part 4: Profile Work Tab Rewrite

**File: `ui/src/components/profile/ProfileWorkTab.tsx`** (REWRITE, currently 86 lines)

Replace the entire component. The new Work Tab has 4 sections:

### Section layout

```
┌─────────────────────────────────┐
│ [+ Create Task]                 │  ← top bar with create button
├─────────────────────────────────┤
│ ▶ Active Work (3)               │  ← collapsible, default open
│   ┌──────────────────────────┐  │
│   │ 🔴 Security audit        │  │  ← priority dot + title
│   │    In Progress · 12.5K ⊛ │  │  ← status + tokens
│   │    ████████░░ 80%        │  │  ← step progress
│   └──────────────────────────┘  │
│   ┌──────────────────────────┐  │
│   │ ...more items...         │  │
│   └──────────────────────────┘  │
├─────────────────────────────────┤
│ ▶ Blocked (1)                   │  ← collapsible
│   ┌──────────────────────────┐  │
│   │ ⬛ Code review PR #42    │  │
│   │    Blocked · Dependency  │  │
│   │    [Reassign] [Cancel]   │  │  ← action buttons
│   └──────────────────────────┘  │
├─────────────────────────────────┤
│ ▶ Completed (5)                 │  ← collapsible, default closed
│   ┌──────────────────────────┐  │
│   │ ✓ Systems check          │  │
│   │    Done · 2m ago · 8K ⊛  │  │
│   └──────────────────────────┘  │
├─────────────────────────────────┤
│ ▶ Duty Schedule                 │  ← from scheduled_tasks
│   09:00  Scout Report      ✓   │
│   12:00  Systems Check    ⏳   │
│   18:00  Security Audit   ·    │
└─────────────────────────────────┘
```

### Data sources

- **Active Work:** `workItems` from store, filtered by `assigned_to === selectedAgent.id` AND status IN (`open`, `scheduled`, `in_progress`, `review`)
- **Blocked:** Same filter but status IN (`failed`, `blocked`)
- **Completed:** Fetch via `GET /api/work-items?assigned_to={agentId}&status=done&limit=10` (not in snapshot — done items are excluded). Use `useEffect` fetch on tab open, cache in local state.
- **Duty Schedule:** Use `scheduledTasks` from existing store (already hydrated), filtered by agent. Show today's duties with time, name, and status indicator (completed ✓, overdue ⏳, pending ·).
- **Booking data:** Match `workBookings` by `resource_id === selectedAgent.id` to show elapsed time and tokens on active work items.
- **Create Task form:** Simple modal/popover with title (required), priority (1-5 dropdown, default 3), work type (card/task dropdown, default "task"), description (optional textarea). Calls `createWorkItem()` action with `assigned_to` pre-set to this agent's ID.

### Actions on work items

- **Reassign** (on blocked/failed items): Opens a small dropdown of available agents (from `bookableResources` or `agents` store), calls `assignWorkItem(itemId, newResourceId)`
- **Cancel**: Calls `moveWorkItem(itemId, 'cancelled')`
- **Retry** (on failed items): Calls `moveWorkItem(itemId, 'open')` to reset

### Styling

Follow existing profile tab patterns — same glass panel background, same padding/margins, same scrollable overflow. Use existing CSS variables. Priority dots: P1 red, P2 orange, P3 yellow, P4 blue, P5 gray. Work type as small badge (same pattern as department badges in `ProfileInfoTab.tsx`).

---

## Part 5: Crew Scrumban Board

**File: `ui/src/components/work/WorkBoard.tsx`** (NEW)

Full-page Scrumban board replacing the main content area when `mainViewer === 'work'`.

### Column mapping

Map `WorkItemStatus` to Scrumban columns:

| Scrumban Column | WorkItem Statuses | WIP Limit |
|----------------|-------------------|-----------|
| **Backlog** | `draft`, `open` | None |
| **Ready** | `scheduled` | None |
| **In Progress** | `in_progress` | 10 |
| **Review** | `review` | 5 |
| **Done** | `done` | None (last 20 shown) |

`failed`, `cancelled`, `blocked` items appear in a separate "Blocked/Failed" row below the main board (collapsed by default, expand to see).

### Board layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Crew Work Board          [Filters ▾]  [Swim Lanes ▾]  [+ Quick Create]    │
├──────────┬──────────┬──────────────┬──────────┬──────────────────────────────┤
│ BACKLOG  │ READY    │ IN PROGRESS  │ REVIEW   │ DONE                       │
│ (12)     │ (4)      │ (7/10)       │ (2/5)    │ (20)                       │
├──────────┼──────────┼──────────────┼──────────┼──────────────────────────────┤
│ ┌──────┐ │ ┌──────┐ │ ┌──────────┐ │ ┌──────┐ │ ┌──────┐                  │
│ │ Card │ │ │ Card │ │ │ Card     │ │ │ Card │ │ │ Card │                  │
│ └──────┘ │ └──────┘ │ │ 🟢 Worf  │ │ └──────┘ │ └──────┘                  │
│ ┌──────┐ │          │ │ ████░ 75%│ │          │                            │
│ │ Card │ │          │ └──────────┘ │          │                            │
│ └──────┘ │          │ ┌──────────┐ │          │                            │
│          │          │ │ Card     │ │          │                            │
│          │          │ └──────────┘ │          │                            │
├──────────┴──────────┴──────────────┴──────────┴──────────────────────────────┤
│ ▶ Blocked/Failed (2)                                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Card component

Each card shows:
- **Title** (bold, truncated to 2 lines)
- **Priority dot** (P1=red, P2=orange, P3=yellow, P4=blue, P5=gray) — top-left corner
- **Work type badge** (small pill: "task", "card", "work_order", "duty", "incident")
- **Assigned agent** — agent avatar (colored dot from agent's pool color) + callsign. If unassigned: "Unassigned" in muted text
- **Token estimate** — e.g., "50K ⊛" (if estimated_tokens > 0)
- **Due date** — relative time ("in 2h", "overdue") if `due_at` is set. Red text if overdue.
- **Step progress** — thin bar at card bottom if `steps.length > 0`. Fill% = completed steps / total steps.
- **Tags** — small chips below title (max 3 shown, "+N" overflow)

### Drag and Drop

Use HTML5 drag-and-drop API (no external library — keep bundle small):

- Cards are `draggable`
- Columns have `onDragOver` (prevent default) and `onDrop` handlers
- On drop: determine target column → map to target status → call `moveWorkItem(itemId, targetStatus)`
- Column status mapping for drop targets:
  - Drop on "Backlog" → transition to `open`
  - Drop on "Ready" → transition to `scheduled`
  - Drop on "In Progress" → transition to `in_progress`
  - Drop on "Review" → transition to `review`
  - Drop on "Done" → transition to `done`
- **WIP limit enforcement:** If target column is at WIP limit, show a brief warning toast but still allow the move (soft limit, not hard block). WIP limits are display-only constraints, not enforced server-side.
- Visual feedback: highlight target column on drag-over, dim source card while dragging.

### Quick Create

"+" button in toolbar opens an inline form at the top of the Backlog column:
- Title (text input, required)
- Priority (1-5 select, default 3)
- On submit: call `createWorkItem({ title, priority, work_type: 'card' })` — auto-typed as "card" (lightest weight)
- On Escape or blur: cancel

### Pull Assignment

For unassigned cards in Ready column:
- Show small agent avatar row below card (from `bookableResources` filtered by capabilities match)
- Click avatar → call `assignWorkItem(itemId, resourceId)`
- "Auto" button → call `POST /api/work-items/claim` on behalf of the best-match agent

### Filters

Filter toolbar (collapsed by default, expand on click):
- **Department:** multi-select checkboxes from agent departments
- **Agent:** multi-select from crew list (show callsigns)
- **Priority:** P1-P5 toggle buttons
- **Work type:** multi-select (card/task/work_order/duty/incident)
- **Tags:** text filter
- Filters are local state (not persisted). Filter logic: AND across categories, OR within category.

### Swim Lanes

Optional grouping selector in toolbar:
- **None** (default) — flat board
- **By Department** — horizontal swim lanes per department
- **By Priority** — horizontal swim lanes per priority level (P1 at top)
- **By Agent** — horizontal swim lanes per assigned agent (+ "Unassigned" lane)

Swim lane rendering: each lane is a full-width row with a lane header on the left, containing the same 5 columns. Cards in each lane are filtered by the lane's grouping value.

### Real-time Updates

WebSocket events update `workItems` in the store → React re-renders the board automatically. No polling needed.

**Done column:** Only show the 20 most recent completed items (by `updated_at`). Fetch done items on board mount via `GET /api/work-items?status=done&limit=20`.

---

## Part 6: View Switcher Update

**File: `ui/src/components/ViewSwitcher.tsx`**

Add a 4th tab: `WORK`

```typescript
// Add to tabs array:
{ key: 'work', label: 'WORK' }
```

This sets `mainViewer` to `'work'`.

**File: `ui/src/App.tsx`**

Add the render case for the work view:

```typescript
import WorkBoard from './components/work/WorkBoard';

// In the mainViewer switch:
{mainViewer === 'work' && <WorkBoard />}
```

---

## Part 7: Backend — Agent Profile Work Data

**File: `src/probos/api.py`**

Enhance the existing `GET /api/agent/{agent_id}/profile` endpoint (lines 1554-1645) to include workforce data for the agent.

Add to the profile response dict:
```python
# After existing profile fields...
if runtime.work_item_store:
    agent_uuid = agent.uuid if hasattr(agent, 'uuid') else agent_id
    # Active work items assigned to this agent
    active_items = await runtime.work_item_store.list_work_items(
        assigned_to=agent_uuid,
        status=None,  # all statuses
        limit=50,
    )
    profile_data["work_items"] = [wi.to_dict() for wi in active_items]
    # Active bookings for this agent
    bookings = await runtime.work_item_store.list_bookings(
        resource_id=agent_uuid,
        limit=20,
    )
    profile_data["bookings"] = [b.to_dict() for b in bookings]
```

This keeps the profile panel self-contained — one fetch gets all agent data including work.

---

## Part 8: Bookable Resources Hydration

The Scrumban board needs to know about available agents for the pull assignment feature. Bookable resources are registered at startup but not currently in the snapshot.

**File: `src/probos/workforce.py`**

Add to `snapshot()` method:
```python
def snapshot(self) -> dict[str, Any]:
    """Return cached snapshot for build_state_snapshot."""
    result = dict(self._snapshot_cache)
    result["resources"] = [r.to_dict() for r in self._resources.values()]
    return result
```

This adds `resources` to the workforce snapshot alongside `work_items` and `bookings`.

**Update frontend** `StateSnapshot` accordingly and hydrate `bookableResources` from `snapshot.workforce.resources`.

---

## Testing

### Frontend tests (Vitest)

**File: `ui/src/components/work/WorkBoard.test.tsx`** (NEW)

1. `renders column headers` — Board shows all 5 column headers
2. `renders work items in correct columns` — Items with status "open" in Backlog, "in_progress" in In Progress, etc.
3. `shows WIP limit indicator` — In Progress column shows "7/10" format
4. `WIP limit warning on full column` — When column at limit, visual indicator changes
5. `renders card with all fields` — Card shows title, priority dot, work type badge, agent callsign, token estimate
6. `filters by department` — Department filter reduces visible items
7. `filters by priority` — Priority toggle filters items
8. `filters by agent` — Agent filter reduces visible items
9. `quick create opens form` — "+" button shows inline create form
10. `quick create submits` — Form submission calls fetch with correct payload
11. `done column shows limited items` — Done column shows max 20 items
12. `blocked items in separate section` — Failed/blocked items rendered below main board
13. `swim lanes by department` — Selecting "By Department" grouping creates lane per department
14. `empty state` — Board with no items shows helpful empty message

**File: `ui/src/components/profile/ProfileWorkTab.test.tsx`** (NEW or update existing)

15. `renders active work items` — Shows items assigned to selected agent with active statuses
16. `renders blocked items with actions` — Blocked items show Reassign/Cancel buttons
17. `renders completed items` — Fetches and displays done items
18. `renders duty schedule` — Shows today's scheduled tasks
19. `create task form` — Create button opens form, submit calls API
20. `shows booking tokens` — Active items show token consumption from matching booking
21. `empty state` — No work items shows "No active work" message

### Backend tests (pytest)

**File: `tests/test_api.py`** (append to existing)

22. `test_work_item_create_broadcasts_event` — POST /api/work-items triggers WebSocket event
23. `test_agent_profile_includes_work_items` — GET /api/agent/{id}/profile returns work_items array
24. `test_workforce_snapshot_includes_resources` — Snapshot includes bookable resources

---

## Recommendations

### Items NOT in the AD-497 spec but should be considered:

1. **Work Item Detail Modal** — Clicking a card on the Scrumban board should open a detail view (modal or slide-out panel) showing full description, steps, journal entries, booking history, and allowing inline edits. *Recommendation: Include a basic detail modal in this AD. Full journal/history display can be AD-498+ territory.*

2. **Keyboard shortcuts** — Power users (the Captain) will want `N` for new item, arrow keys for navigation, `Enter` to open detail. *Recommendation: Defer to a future AD. Not critical for v1.*

3. **Board persistence** — Filter and swim lane selections reset on page reload. *Recommendation: Store in `localStorage` if simple. Don't over-engineer.*

4. **Token consumption live updates** — While a booking is active, `total_tokens_consumed` increases. The snapshot only refreshes periodically. *Recommendation: Accept snapshot staleness for v1. Real-time token streaming is AD-498+ territory.*

5. **Column collapse** — Dense boards benefit from collapsing less-used columns (Backlog, Done). *Recommendation: Include simple collapse toggle per column — low effort, high value.*

6. **Sound effects** — The HXI has a sound engine (`soundEngine`). Card movements could trigger subtle audio feedback. *Recommendation: Add a subtle click sound on drag-drop completion, matching existing HXI audio patterns.*

7. **Notification integration** — When a work item assigned to an agent becomes blocked or fails, a notification should appear in the orb/bridge. *Recommendation: Defer — this is the AD-500/501 notification rework territory.*

8. **Offline/503 handling** — If workforce is disabled (config-gated), the Work board and Work tab should show a clear "Workforce not enabled" message rather than empty state. *Recommendation: Include this — simple conditional check.*

---

## Deferred Items (tracked in other ADs)

| Item | Deferred To | Rationale |
|------|------------|-----------|
| Work Type Registry + state machines | AD-498 | Separate concern, different AD |
| Templates + template picker in board | AD-498 | Requires type registry first |
| DutyScheduleTracker → WorkItem migration | AD-500 | Needs AD-498 for duty work type |
| Commercial Schedule Board (full Gantt/timeline) | AD-C-010 | Commercial overlay |
| Capacity planning / optimization | AD-C-011 | Commercial feature |
| Night Orders → WorkItem creation | AD-471 | Depends AD-496 + AD-498 |

---

## Verification

1. **Backend events:** `uv run pytest tests/test_api.py -k "work_item_create_broadcasts or profile_includes_work or snapshot_includes_resources"` — new tests pass
2. **Frontend tests:** `cd ui && npx vitest run` — all existing + new tests pass
3. **Visual — Work Tab:** Open HXI → click any agent → Work tab shows active items, blocked items, completed history, duty schedule. Create Task button works.
4. **Visual — Scrumban Board:** Click WORK tab in ViewSwitcher → full board renders with columns. Create items via Quick Create. Drag cards between columns. Filter by department/priority/agent. Toggle swim lanes.
5. **Real-time:** Create work item via API (`curl -X POST localhost:8000/api/work-items ...`) → card appears on board without refresh. Transition status → card moves columns.
6. **Full regression:** `uv run pytest` — all existing tests pass
7. **Frontend regression:** `cd ui && npx vitest run` — all existing tests pass

---

## File Summary

| File | Action | Description |
|------|--------|-------------|
| `ui/src/store/types.ts` | MODIFY | Add WorkItemView, BookingView, BookableResourceView, ScrumbanColumn; update StateSnapshot and mainViewer |
| `ui/src/store/useStore.ts` | MODIFY | Add workforce state, WebSocket handlers, snapshot hydration, action methods |
| `ui/src/components/profile/ProfileWorkTab.tsx` | REWRITE | Full rewrite with active/blocked/completed/duty sections |
| `ui/src/components/work/WorkBoard.tsx` | NEW | Scrumban board with drag-drop, filters, swim lanes |
| `ui/src/components/ViewSwitcher.tsx` | MODIFY | Add WORK tab |
| `ui/src/App.tsx` | MODIFY | Route mainViewer 'work' to WorkBoard |
| `src/probos/api.py` | MODIFY | Add WebSocket event broadcasts to workforce endpoints; add work data to agent profile |
| `src/probos/workforce.py` | MODIFY | Add resources to snapshot |
| `ui/src/components/work/WorkBoard.test.tsx` | NEW | 14 tests for Scrumban board |
| `ui/src/components/profile/ProfileWorkTab.test.tsx` | NEW | 7 tests for Work Tab |
| `tests/test_api.py` | MODIFY | 3 backend tests for events + profile + snapshot |
