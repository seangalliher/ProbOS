# AD-321: Activity Drawer (React)

## Objective

Create a slide-out Activity Drawer panel on the right edge of the HXI that gives the Captain real-time visibility into all agent activity. The drawer consumes the existing `agentTasks` state (populated by the TaskTracker service, AD-316) — **no new backend code needed**.

## Context

- The TaskTracker backend is already built (AD-316) and emits `task_created` / `task_updated` WebSocket events
- The Zustand store already has `agentTasks: AgentTaskView[] | null` populated from those events
- The `AgentTaskView` and `TaskStepView` interfaces are already defined in `ui/src/store/types.ts`
- The MissionControl Kanban (AD-322) is already an overlay toggled from the top-right header — the Activity Drawer is a complementary slide-out panel, not a replacement
- The drawer toggle button goes in the top-right header area, next to the existing "MISSION CTRL" button
- The project uses **inline styles exclusively** — no CSS files, no CSS-in-JS libraries

## Files to Create

### `ui/src/components/ActivityDrawer.tsx` (NEW — ~250 lines)

A slide-out panel from the right edge of the screen.

**Component signature:**

```tsx
export function ActivityDrawer({ open, onClose }: { open: boolean; onClose: () => void })
```

**Layout:**

```
┌────────────────────────────────┐
│ ACTIVITY              [X Close]│
├────────────────────────────────┤
│ ▼ NEEDS ATTENTION (2)          │  ← amber section header, always first
│ ┌────────────────────────────┐ │
│ │ ● Build: Fix auth bug      │ │  ← compact card
│ │   builder · Engineering    │ │
│ │   3m · review              │ │
│ │   [Approve] [Reject]       │ │
│ └────────────────────────────┘ │
├────────────────────────────────┤
│ ▼ ACTIVE (3)                   │  ← working tasks
│ ┌────────────────────────────┐ │
│ │ ◉ Build: Refactor shell    │ │
│ │   builder · Engineering    │ │
│ │   5m · step 2/4            │ │
│ │   ▏████████░░░░▕ 50%       │ │  ← step progress bar
│ └────────────────────────────┘ │
├────────────────────────────────┤
│ ▼ RECENT (5)                   │  ← done/failed
│ ┌────────────────────────────┐ │
│ │ ✓ Build: Add tests · done  │ │
│ │   builder · 12m            │ │
│ └────────────────────────────┘ │
└────────────────────────────────┘
```

**Three sections, each with a collapsible header:**

1. **Needs Attention** — `agentTasks.filter(t => t.requires_action)`. Section header in amber. Cards show action buttons (Approve/Reject). Always expanded.

2. **Active** — `agentTasks.filter(t => t.status === 'working')`. Cards show step progress bar (`step_current / step_total`) and current step label. Status dot with `neural-pulse` animation (the keyframes already exist globally). Always expanded.

3. **Recent** — `agentTasks.filter(t => t.status === 'done' || t.status === 'failed')`. Most recent first (sort by `completed_at` descending). Cap at 10 items shown. Collapsed by default (toggle header to expand).

**Each task card shows:**
- Left border stripe in department color (use the DEPT_COLORS constant below — duplicate, don't import from MissionControl)
- Status dot (color from STATUS_COLORS below, `neural-pulse` animation for working status)
- Task type badge: small capitalized label — "BUILD", "DESIGN", "DIAGNOSTIC", "ASSESSMENT", "QUERY" — in muted color
- Title (truncated to 50 chars with ellipsis)
- Agent type name (e.g., "builder", "architect")
- Department name (capitalized)
- Elapsed time (compute from `started_at`, show "Xs", "Xm Ys", or "Xh Ym")
- AD number if > 0 (e.g., "AD-386") in department color

**Expanded card (click card to toggle):**
- Full title (not truncated)
- Step-by-step checklist from `steps[]` array:
  - Each step: `○` pending, `◐` in_progress, `●` done, `✕` failed — then label — then duration if done (e.g., "1.2s")
  - Overall progress bar: thin bar showing `step_current / step_total`
- Action buttons for tasks with `requires_action`:
  - Approve + Reject buttons (same visual style as MissionControl.tsx TaskCard)
  - Call `POST /api/build/queue/approve` with `{ build_id: task.id }` and `POST /api/build/queue/reject` with `{ build_id: task.id }`
- Error text for failed tasks (first 200 chars, muted red, collapsible)
- Metadata display: if `task.metadata` has keys, show as key-value pairs in small text

**Styling:**
- Position: fixed, right: 0, top: 0, bottom: 0, width: 320px
- Background: glass panel — `rgba(10, 10, 18, 0.92)` with `backdrop-filter: blur(16px)`
- Border-left: `1px solid rgba(240, 176, 96, 0.15)` (matches IntentSurface glass style)
- z-index: 20 (above canvas, below Mission Control overlay z:25 buttons)
- Slide animation: `transform: translateX(open ? 0 : '100%')`, `transition: transform 0.25s ease-out`
- Always render the component (don't conditionally mount/unmount) — use transform to slide in/out. This enables smooth animation.
- Scrollable interior with `overflow-y: auto`
- Close button: "×" in top-right of drawer header
- Section headers: uppercase, letter-spacing: 2px, font-size: 10px, color: #888 (amber #f0b060 for Needs Attention when non-empty)

**Empty states:**
- Each section shows muted italic text when empty: "No tasks need attention", "No active tasks", "No recent tasks"

**Constants to define locally in ActivityDrawer.tsx:**

```typescript
const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};

const STATUS_COLORS: Record<string, string> = {
  queued: '#555566',
  working: '#ffaa44',
  review: '#66ccff',
  done: '#50c878',
  failed: '#ff5555',
};
```

## Files to Modify

### `ui/src/components/IntentSurface.tsx`

**1. Add import:**

```tsx
import { ActivityDrawer } from './ActivityDrawer';
```

**2. Add local state and store selectors** inside the `IntentSurface()` component body (near existing state declarations around line 27-36):

```tsx
const [drawerOpen, setDrawerOpen] = useState(false);
const agentTasks = useStore((s) => s.agentTasks);
const needsAttentionCount = agentTasks?.filter(t => t.requires_action).length ?? 0;
```

**3. Add drawer toggle button** — place it BEFORE the existing Mission Control toggle button (around line 312). Position it to the left:

```tsx
{/* ── Activity Drawer toggle (AD-321) ── */}
<button
  onClick={() => setDrawerOpen(prev => !prev)}
  style={{
    position: 'fixed',
    top: 12,
    right: 110,
    zIndex: 25,
    padding: '3px 8px',
    borderRadius: 4,
    border: '1px solid rgba(255, 255, 255, 0.15)',
    background: drawerOpen ? 'rgba(240, 176, 96, 0.2)' : 'transparent',
    color: drawerOpen ? '#f0b060' : '#888',
    fontSize: 9,
    fontWeight: 600,
    cursor: 'pointer',
    letterSpacing: 1,
    pointerEvents: 'auto',
  }}
>
  {'ACTIVITY' + (needsAttentionCount > 0 ? ` (${needsAttentionCount})` : '')}
</button>
```

**4. Render the drawer** — add right after the Mission Control overlay rendering (around line 336):

```tsx
{/* ── Activity Drawer (AD-321) ── */}
<ActivityDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
```

## Files NOT to Modify

- `ui/src/store/useStore.ts` — no changes needed, `agentTasks` is already wired
- `ui/src/store/types.ts` — no changes needed, `AgentTaskView` and `TaskStepView` already defined
- No Python backend files — this is pure frontend

## Verification

```bash
cd d:\ProbOS\ui
npx vitest run
npx tsc --noEmit
```

All existing tests (34 vitest) must pass. TypeScript must compile cleanly. Do NOT modify any files not listed in this prompt.
