# AD-324: Orb Hover Enhancement

## Goal

Upgrade the existing 3D system health orb visualization with per-agent hover tooltips and a pulsing amber indicator when any agent requires Captain attention. Currently, hovering over agent orbs in the WebGL scene shows no task context. This AD adds informative tooltips showing what each agent is doing right now.

## Dependencies

- AD-316 (TaskTracker + AgentTask) must be implemented — tooltips read from `agentTasks` in the store.

## Files to Modify

### `ui/src/components/SystemOrb.tsx` (or wherever agent orbs are rendered in the 3D scene)

Find the existing agent orb rendering code. The orbs are rendered in the WebGL/Three.js scene. Agent hover events likely already exist (for displaying agent names).

**1. Add task context to hover tooltip:**

When hovering over an agent orb, look up the agent's current task from `agentTasks`:

```tsx
// Inside the orb component, where hover state is managed:
const agentTasks = useStore(s => s.agentTasks);

// On hover, find the agent's active task:
const activeTask = agentTasks?.find(
  t => t.agent_id === hoveredAgent.id && t.status === 'working'
);
const reviewTask = agentTasks?.find(
  t => t.agent_id === hoveredAgent.id && t.status === 'review'
);
const task = reviewTask || activeTask;  // review takes priority in display
```

**2. Render tooltip content:**

The tooltip (HTML overlay positioned near the hovered orb) should show:
- Agent display name (already exists)
- If task exists:
  - Task title (truncated to ~40 chars)
  - Current step label (from `steps` array, find the `in_progress` one)
  - Step progress: "Step 2 of 4" (from `step_current` / `step_total`)
  - Elapsed time since `started_at`
  - If `requires_action`: amber "Needs attention" badge
- If no task: "Idle" in dim text

Tooltip styling:
- Background: `rgba(12, 12, 22, 0.95)` with `backdrop-filter: blur(4px)`
- Border: `1px solid rgba(255, 255, 255, 0.08)`
- Border-left: `3px solid {deptColor}` (department color)
- Padding: 8px 12px
- Font size: 10px
- Max-width: 220px
- Positioned above or beside the orb, avoid going off-screen

**3. Amber pulse indicator:**

Add a visual indicator on agent orbs when they require Captain attention. Find the orb material/mesh and modify:

```tsx
// If this agent has a task requiring action, add amber pulse
const needsAttention = agentTasks?.some(
  t => t.agent_id === agent.id && t.requires_action
);

// Apply to the orb mesh material:
if (needsAttention) {
  // Add amber emissive glow with animation
  // Use existing neural-pulse CSS keyframe or add a Three.js animation
  material.emissive = new THREE.Color('#ffaa44');
  material.emissiveIntensity = 0.3 + Math.sin(Date.now() * 0.003) * 0.2;
}
```

**4. Click-through:**

If the agent has an active task requiring attention, clicking the orb should open the Activity Drawer (AD-321):

```tsx
// On orb click, if agent needs attention:
if (needsAttention) {
  useStore.getState().set?.({ activityDrawerOpen: true });
}
```

### Important notes for implementation:

- **Read the existing orb code first** — the 3D scene may use Three.js, React Three Fiber, or custom WebGL. Adapt the tooltip pattern to match the existing hover/tooltip implementation.
- **The tooltip is an HTML overlay** — not rendered in WebGL. It's positioned via CSS based on the projected screen coordinates of the hovered orb. Look for existing tooltip/overlay patterns in the codebase.
- **Department colors** — use the same `DEPT_COLORS` map as MissionControl.tsx: engineering=#b0a050, science=#50b0a0, medical=#5090d0, security=#d05050, bridge=#d0a030.
- **Performance** — the task lookup happens only on hover, not every frame. Use React state for hovered agent, not Three.js animation loop.

## Do NOT Create Tests

This is a UI-only enhancement to existing 3D visualization. No test file needed. The existing vitest suite should continue to pass (34 tests).

## Verification

```bash
cd d:\ProbOS\ui
npx vitest run
```

All 34 existing tests must pass. Do NOT modify any files not listed in this prompt.
