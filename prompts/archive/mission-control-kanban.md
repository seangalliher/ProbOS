# Build Prompt: Mission Control Kanban Board (AD-322)

## File Footprint
- `ui/src/components/MissionControl.tsx` (NEW) — Kanban board component
- `ui/src/components/IntentSurface.tsx` (MODIFIED) — add Mission Control toggle/tab
- `ui/src/store/types.ts` (MODIFIED) — add MissionControlTask interface
- `ui/src/store/useStore.ts` (MODIFIED) — add mission control state and event handlers

## Context

Mission Control is the Captain's operational dashboard — a Kanban board showing all active
agent work flowing through the ship. Today, cognitive agents work in a black box. Mission
Control gives the Captain full visibility.

The Kanban board has 4 columns mapping to the build dispatch lifecycle:
- **Queued** — work waiting to be picked up
- **Working** — actively being executed by an agent
- **Needs Review** — completed, awaiting Captain approval
- **Done** — merged or resolved

This directly surfaces the BuildQueue (AD-371-375) plus any future task types. Each card
shows: agent type icon, task title, team color, elapsed time, and status.

### Existing systems this surfaces:
- `BuildQueueItem` in types.ts — build dispatch queue items already have status lifecycle
- `build_queue_update` / `build_queue_item` WebSocket events — real-time updates
- `GET /api/build/queue` — polling fallback
- `/api/build/queue/approve` and `/api/build/queue/reject` — action endpoints

### Design principles:
1. **Mission Control is a view mode, not a replacement** — the existing HXI chat/orb view
   remains. Mission Control is an alternative view toggled by a button.
2. **Cards are universal** — while builds are the first card type, the Kanban model supports
   future card types (design tasks, diagnostic sweeps, etc.)
3. **Color-coded by department** — Engineering (amber), Science (teal), Medical (blue),
   Security (red), Bridge (gold)

---

## Changes

### File: `ui/src/store/types.ts`

Add a universal task card interface (after `BuildQueueItem`):

```typescript
export interface MissionControlTask {
  id: string;
  type: 'build' | 'design' | 'diagnostic' | 'assessment';  // extensible
  title: string;
  department: string;       // 'engineering', 'science', 'medical', 'security', 'bridge'
  status: 'queued' | 'working' | 'review' | 'done' | 'failed';
  agent_type: string;       // which agent is handling this
  agent_id: string;
  started_at: number;       // unix timestamp
  completed_at: number;     // 0 if not complete
  priority: number;
  ad_number: number;
  error: string;
  metadata: Record<string, unknown>;  // type-specific data (file_footprint, commit_hash, etc.)
}
```

### File: `ui/src/store/useStore.ts`

Add state field and event handler:

```typescript
// In the store state, add:
missionControlTasks: MissionControlTask[] | null;
missionControlView: boolean;  // toggle between HXI and Mission Control

// Add a helper that converts BuildQueueItems to MissionControlTasks
// (builds are the first task source; more will follow)

// Add WebSocket handler for 'mission_control_update' event type
// Also derive mission control tasks from existing buildQueue items as a bridge:
// map buildQueue status → mission control status:
//   queued → queued
//   dispatched → working
//   building → working
//   reviewing → review
//   merged → done
//   failed → failed
```

### File: `ui/src/components/MissionControl.tsx` (NEW)

Create the Kanban board component:

```
Architecture:
- 4 columns: Queued | Working | Review | Done
- Each column has a header with count badge
- Cards show:
  - Department color bar on left edge
  - Task title (truncated to 40 chars)
  - Agent type badge
  - AD number (if present)
  - Elapsed time since started (live updating for Working items)
  - Status dot (same colors as build queue card)
  - Action buttons for Review column (Approve/Reject)
  - Error message for Failed items
- Column backgrounds slightly tinted by typical department color
- Responsive: columns stack vertically on narrow viewports
```

**Styling guidelines (match existing HXI aesthetic):**
- Background: `#0a0a12` (ship dark)
- Card background: `rgba(255, 255, 255, 0.03)` with `1px solid rgba(255, 255, 255, 0.06)`
- Column headers: uppercase, letter-spacing 2px, font-size 10px
- Department colors:
  - engineering: `#b0a050` (amber)
  - science: `#50b0a0` (teal)
  - medical: `#5090d0` (blue)
  - security: `#d05050` (red)
  - bridge: `#d0a030` (gold)
- Card left border: 3px solid department color
- Count badges: circular, department color background, white text
- Approve button: green (`#50c878`), same style as build queue card
- Reject button: red (`#ff5555`), same style as build queue card

**Card component:**
```tsx
function TaskCard({ task }: { task: MissionControlTask }) {
  const deptColor = {
    engineering: '#b0a050',
    science: '#50b0a0',
    medical: '#5090d0',
    security: '#d05050',
    bridge: '#d0a030',
  }[task.department] || '#888';

  // Elapsed time: for working items, show live timer
  // For done items, show total duration
  // For queued, show time waiting

  return (
    <div style={{
      background: 'rgba(255, 255, 255, 0.03)',
      border: '1px solid rgba(255, 255, 255, 0.06)',
      borderLeft: `3px solid ${deptColor}`,
      borderRadius: 6,
      padding: '8px 10px',
      marginBottom: 6,
      fontSize: 11,
      color: '#e0dcd4',
    }}>
      {/* Title line */}
      <div style={{ fontWeight: 600, marginBottom: 4 }}>
        {task.ad_number > 0 && (
          <span style={{ color: deptColor, marginRight: 6 }}>AD-{task.ad_number}</span>
        )}
        {task.title.slice(0, 40)}
      </div>
      {/* Meta line */}
      <div style={{ fontSize: 9, color: '#888', display: 'flex', gap: 8 }}>
        <span>{task.agent_type}</span>
        <span>{elapsedTime(task)}</span>
      </div>
      {/* Action buttons for review status */}
      {task.status === 'review' && (
        <div style={{ marginTop: 6, display: 'flex', gap: 6 }}>
          {/* Approve and Reject buttons — same as build queue card */}
        </div>
      )}
      {/* Error for failed */}
      {task.status === 'failed' && task.error && (
        <div style={{ color: '#ff5555', fontSize: 9, marginTop: 4 }}>
          {task.error.slice(0, 80)}
        </div>
      )}
    </div>
  );
}
```

**Kanban board layout:**
```tsx
export function MissionControl() {
  const tasks = useStore(s => s.missionControlTasks) || [];

  const columns = [
    { key: 'queued', label: 'QUEUED', items: tasks.filter(t => t.status === 'queued') },
    { key: 'working', label: 'WORKING', items: tasks.filter(t => t.status === 'working') },
    { key: 'review', label: 'REVIEW', items: tasks.filter(t => t.status === 'review') },
    { key: 'done', label: 'DONE', items: tasks.filter(t => t.status === 'done' || t.status === 'failed') },
  ];

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(4, 1fr)',
      gap: 12,
      padding: 16,
      height: '100%',
      overflow: 'hidden',
    }}>
      {columns.map(col => (
        <div key={col.key} style={{
          background: 'rgba(255, 255, 255, 0.01)',
          borderRadius: 8,
          padding: 10,
          overflow: 'auto',
        }}>
          <div style={{
            textTransform: 'uppercase',
            letterSpacing: 2,
            fontSize: 10,
            color: '#888',
            marginBottom: 10,
            display: 'flex',
            justifyContent: 'space-between',
          }}>
            {col.label}
            <span style={{
              background: 'rgba(255,255,255,0.1)',
              borderRadius: '50%',
              width: 18, height: 18,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 9,
            }}>{col.items.length}</span>
          </div>
          {col.items.map(task => <TaskCard key={task.id} task={task} />)}
        </div>
      ))}
    </div>
  );
}
```

### File: `ui/src/components/IntentSurface.tsx`

Add a toggle button to switch between the chat/orb HXI view and Mission Control:

1. Import MissionControl: `import { MissionControl } from './MissionControl';`
2. Read `missionControlView` from the store
3. Add a toggle button in the top bar area (near existing controls)
4. When `missionControlView` is true, render `<MissionControl />` instead of the
   normal HXI content (orbs + cards + chat)
5. Button style: small, subtle, matches existing UI — use ship dark theme

The toggle button:
```tsx
<button
  onClick={() => useStore.setState(s => ({ missionControlView: !s.missionControlView }))}
  style={{
    padding: '3px 8px',
    borderRadius: 4,
    border: '1px solid rgba(255, 255, 255, 0.15)',
    background: missionControlView ? 'rgba(208, 160, 48, 0.2)' : 'transparent',
    color: missionControlView ? '#d0a030' : '#888',
    fontSize: 9,
    fontWeight: 600,
    cursor: 'pointer',
    letterSpacing: 1,
  }}
>
  {missionControlView ? 'HXI' : 'MISSION CTRL'}
</button>
```

---

## Constraints

- Do NOT modify api.py or any Python files — this is UI only
- Derive `MissionControlTask` from existing `BuildQueueItem` data (mapping function)
- The Kanban board reads from the same Zustand store that already receives build queue events
- No new WebSocket events needed — reuse `build_queue_update` / `build_queue_item`
- No new API endpoints needed — reuse `GET /api/build/queue`, approve/reject endpoints
- Keep the existing build queue card in IntentSurface — it remains when not in Mission Control view
- Done column shows both merged and failed items (with visual distinction)
- Elapsed time should use `Date.now() / 1000 - task.started_at` for live timer
- No external dependencies — pure React + existing Zustand store
