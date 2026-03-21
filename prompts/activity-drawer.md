# AD-321: Activity Drawer

## Goal

Add a slide-out Activity Drawer from the right edge of the HXI that gives the Captain a persistent, at-a-glance view of all agent activity organized by urgency. Three sections: **Active** (agents working now), **Needs Attention** (awaiting Captain input), **Recent** (completed tasks). This supplements Mission Control's Kanban view with a lightweight, always-accessible panel.

## Dependencies

- AD-316 (TaskTracker + AgentTask) must be implemented — the drawer reads from `agentTasks` in the store.
- AD-323 (Notification Queue) should be implemented — the "Needs Attention" section can incorporate notifications.

## Files to Create

### `ui/src/components/ActivityDrawer.tsx` (~200 lines)

A slide-out panel from the right edge of the viewport.

**Layout:**

```
┌────────────────────────────────┐
│ ACTIVITY              [X Close]│
├────────────────────────────────┤
│ ▼ NEEDS ATTENTION (2)          │ ← amber section, always first
│ ┌────────────────────────────┐ │
│ │ ⬡ Build: Fix auth bug     │ │  ← compact card
│ │   builder · 3m · review    │ │
│ │   [Approve] [Reject]       │ │
│ └────────────────────────────┘ │
│ ┌────────────────────────────┐ │
│ │ ⬡ Design: Add caching     │ │
│ │   architect · 1m · review  │ │
│ └────────────────────────────┘ │
├────────────────────────────────┤
│ ▼ ACTIVE (3)                   │ ← working tasks
│ ┌────────────────────────────┐ │
│ │ ◈ Build: Refactor shell    │ │
│ │   builder · 5m · step 2/4  │ │
│ │   ▏████████░░░░▕ 50%      │ │  ← step progress bar
│ └────────────────────────────┘ │
├────────────────────────────────┤
│ ▼ RECENT (5)                   │ ← done/failed, collapsed by default
│ ┌────────────────────────────┐ │
│ │ ✓ Build: Add tests   done │ │
│ │   builder · 12m            │ │
│ └────────────────────────────┘ │
└────────────────────────────────┘
```

**Component structure:**

```tsx
export function ActivityDrawer({ onClose }: { onClose: () => void })
```

**Data source:** Read `agentTasks` from the store (populated by AD-316's TaskTracker events).

**Sections:**

1. **Needs Attention** — `agentTasks.filter(t => t.requires_action)`. Cards show action buttons (Approve/Reject for review status). Section header has amber color. Badge count.

2. **Active** — `agentTasks.filter(t => t.status === 'working')`. Cards show step progress bar (step_current / step_total) and current step label. Status dot with pulse animation.

3. **Recent** — `agentTasks.filter(t => t.status === 'done' || t.status === 'failed')`. Most recent first (sort by completed_at descending). Collapsed by default (show header with count, click to expand). Success = green checkmark, Failed = red X.

**Card design:**

Each card (`ActivityCard` component) shows:
- Status icon (dot with color based on status)
- Task type label (e.g. "Build:", "Design:")
- Title (truncated to ~30 chars)
- Agent type, elapsed time, status label
- Step progress bar for working tasks (thin bar, `step_current/step_total` fraction)
- Action buttons for review tasks (Approve/Reject, same style as MissionControl.tsx)
- Error message (truncated) for failed tasks
- Department color accent on left border (same DEPT_COLORS as MissionControl.tsx)

**Slide-out animation:**

```css
/* Panel slides in from right */
transform: translateX(0);  /* open */
transform: translateX(100%);  /* closed */
transition: transform 0.2s ease-out;
```

**Panel styling:**
- Fixed position, right: 0, top: 0, bottom: 0
- Width: 320px
- Background: `#0c0c16` (darker than main HXI)
- Border-left: `1px solid rgba(208, 160, 48, 0.1)`
- z-index: 20 (above MissionControl at 15)
- Overflow-y: auto for scrollable content
- Close button top-right

## Files to Modify

### `ui/src/components/IntentSurface.tsx`

**1. Add import:**

```tsx
import { ActivityDrawer } from './ActivityDrawer';
```

**2. Add state** — use the store for drawer open state. Add to the component body:

```tsx
const activityDrawerOpen = useStore(s => s.activityDrawerOpen);
const agentTasks = useStore(s => s.agentTasks);
```

**3. Add toggle button** in the header area (near the notification bell and Mission Control toggle). Show badge count for needs-attention tasks:

```tsx
{/* Activity drawer toggle (AD-321) */}
<button
  onClick={() => set({ activityDrawerOpen: !activityDrawerOpen })}
  style={{ /* ... header button style ... */ }}
>
  ☰
  {needsAttentionCount > 0 && (
    <span style={{ /* amber badge */ }}>
      {needsAttentionCount}
    </span>
  )}
</button>
```

**4. Render drawer** — add at the end of the component return:

```tsx
{activityDrawerOpen && (
  <ActivityDrawer onClose={() => set({ activityDrawerOpen: false })} />
)}
```

### `ui/src/store/useStore.ts`

**1. Add state field** to `HXIState` interface:

```typescript
activityDrawerOpen: boolean;
```

**2. Initialize** in the state object:

```typescript
activityDrawerOpen: false,
```

## Do NOT Create Tests

This is a UI-only component with no backend logic. No test file needed. The existing vitest suite should continue to pass (34 tests).

## Verification

```bash
cd d:\ProbOS\ui
npx vitest run
```

All 34 existing tests must pass. Do NOT modify any files not listed in this prompt.
