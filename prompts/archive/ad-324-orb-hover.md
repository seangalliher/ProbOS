# AD-324: Orb Hover Enhancement

## Overview

Upgrade the existing agent orb tooltip and add visual indicators on the 3D
orbs themselves for active tasks and Captain-attention states.

## Changes

### 1. Enhanced AgentTooltip with current task info

Modify `ui/src/components/AgentTooltip.tsx` to show the agent's current task
when hovered or pinned:

**Add to tooltip (below existing metadata):**

- **Current task title** — truncated to 50 chars, e.g. "Building AD-323..."
- **Current step label** — e.g. "Step 3 of 5: Running tests"
- **Elapsed time** — `started_at` to now, formatted as "2m 15s"
- **Progress fraction** — e.g. "3/5" with a mini progress bar (thin line,
  4px height, department-colored fill)

**Data source:** Subscribe to `agentTasks` from the Zustand store. Filter:
```typescript
const agentTasks = useStore((s) => s.agentTasks);
const currentTask = agentTasks?.find(
  t => t.agent_id === agent.id && (t.status === 'working' || t.status === 'review')
);
```

**Layout:** Add a divider line (`1px solid rgba(255,255,255,0.08)`) between
the existing agent metadata section and the new task section. Only show the
task section when `currentTask` exists.

**Action required indicator:** If `currentTask.requires_action` is true, show
a small amber badge next to the task title: `⚠ Needs attention` in `#f0b060`.

**Click-through to Activity Drawer:** When the tooltip is pinned (clicked) and
shows a task, add a small "View in Activity" link/button that:
1. Opens the Activity Drawer: `useStore.setState({ ... })` — but since
   ActivityDrawer is controlled by `drawerOpen` state in IntentSurface via
   `useState`, a simpler approach is to emit a custom event or add a
   `drawerOpen` flag to the Zustand store. **Simplest approach:** Add
   `activityDrawerOpen: boolean` to the store and read it in IntentSurface
   instead of local useState. Then the tooltip can set it.

### 2. Amber pulsing orbs for requires_action

Modify `ui/src/canvas/agents.tsx` to add a pulsing amber effect on any agent
orb that has a task with `requires_action === true`.

**In the `useFrame` loop** (~line 54), after the existing breathing animation:

1. Check if the agent has an active task requiring attention:
   ```typescript
   const agentTasks = useStore.getState().agentTasks;
   const needsAttention = agentTasks?.some(
     t => t.agent_id === agent.id && t.requires_action
   );
   ```

2. If `needsAttention`, apply an amber pulse:
   - Override the instance color to pulse between the normal color and amber
     `(0.94, 0.69, 0.38)` using a sine wave at ~2Hz frequency
   - Increase the breathing amplitude from 0.03 to 0.08 for emphasis
   - This should visually distinguish attention-needed agents from normal ones

**Performance note:** `useStore.getState()` in `useFrame` is fine — Zustand's
`getState()` is synchronous and non-reactive (no re-render). But avoid calling
it per-agent — call it once per frame, build a Set of agent_ids needing
attention, then check membership per instance:
```typescript
const tasks = useStore.getState().agentTasks;
const attentionSet = new Set(
  tasks?.filter(t => t.requires_action).map(t => t.agent_id) ?? []
);
// Then in the per-instance loop:
const needsAttention = attentionSet.has(agent.id);
```

### 3. Department label in tooltip

Add the agent's department to the existing tooltip metadata. The department
can be derived from the pool-to-group mapping already in the store:
```typescript
const poolToGroup = useStore((s) => s.poolToGroup);
const department = poolToGroup?.[agent.pool] || '';
```

Show it after the pool name, colored with DEPT_COLORS (same palette used in
ActivityDrawer and NotificationDropdown).

## Files to modify

- `ui/src/components/AgentTooltip.tsx` — add task info, department, progress bar, attention badge, click-through
- `ui/src/canvas/agents.tsx` — amber pulsing in useFrame loop
- `ui/src/store/useStore.ts` — add `activityDrawerOpen: boolean` to store (move from IntentSurface local state)
- `ui/src/components/IntentSurface.tsx` — read `activityDrawerOpen` from store instead of local useState

## Files to read first

- `ui/src/components/AgentTooltip.tsx` — current tooltip (94 lines)
- `ui/src/canvas/agents.tsx` — orb rendering + useFrame animation loop
- `ui/src/canvas/scene.ts` — color/sizing functions
- `ui/src/components/CognitiveCanvas.tsx` — AgentRaycastLayer raycasting
- `ui/src/store/types.ts` — Agent, AgentTaskView interfaces
- `ui/src/store/useStore.ts` — hoveredAgent, tooltipPos, pinnedAgent, agentTasks, poolToGroup
- `ui/src/components/ActivityDrawer.tsx` — DEPT_COLORS constant (reuse)

## Tests

Add vitest tests in `ui/src/__tests__/`:

1. **test tooltip shows current task** — set hoveredAgent + agentTasks with
   matching agent_id → verify task title renders
2. **test tooltip shows no task section when agent has no active task** —
   hoveredAgent without matching task → verify no task section
3. **test attention badge shows for requires_action task** — task with
   `requires_action: true` → verify amber badge renders
4. **test activityDrawerOpen store field** — set and read
   `activityDrawerOpen` from store

## Acceptance criteria

- Hovering an agent orb shows current task title, step, elapsed time, progress
- Agents with `requires_action` tasks pulse amber in the 3D view
- Amber pulse is performant (Set lookup per frame, not per-agent store call)
- Department label shown in tooltip, colored by department
- Pinned tooltip has "View in Activity" to open the drawer
- `activityDrawerOpen` moved from IntentSurface local state to Zustand store
- All existing tests pass
- New vitest tests cover the tooltip enhancements
