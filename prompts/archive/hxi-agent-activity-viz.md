# HXI Agent Activity Visualization Fix (AD-287)

> **Context:** During demo recording, only the center heartbeat node visually pulses.
> Individual agent nodes (introspection, file readers, etc.) should flash when they
> execute a task, but three bugs prevent this from happening.

## Pre-read

Before starting, read these files to understand the current code:
- `src/probos/cognitive/decomposer.py` — focus on `node_start` event emission (~line 749-756)
- `src/probos/types.py` — `TaskNode` dataclass (~line 249-261)
- `src/probos/api.py` — `_safe_serialize()` (~line 565-581) and WebSocket event broadcasting
- `ui/src/store/useStore.ts` — `node_start` case handler (~line 381-401)
- `ui/src/canvas/animations.tsx` — `RoutingPulse` component (~line 213-260) and `SelfModBloom` (~line 172-175) for reference
- `ui/src/canvas/agents.tsx` — `AgentNodes` component, per-frame animation (~line 54-87)
- `ui/src/store/types.ts` — `Agent` type definition (has `state` field)

## Problem Summary

| # | Issue | File(s) |
|---|-------|---------|
| 1 | `node_start` event sends `{"node": <TaskNode>}` but frontend reads `data.agent_id` (always undefined) | `decomposer.py`, `useStore.ts` |
| 2 | `RoutingPulse` mesh never moves from `[0,0,0]` (center) — needs to read target agent position | `animations.tsx` |
| 3 | Agent nodes have no "just triggered" flash — `agent.state` is never used in rendering | `agents.tsx` |

## Step 1: Include agent_id in node_start Event Data

**File:** `src/probos/cognitive/decomposer.py`

When emitting `node_start`, the event data is `{"node": node}`. The frontend needs `agent_id` at the top level. After the agent is selected for execution but before the event fires, add the agent_id to the event data.

Find where `node_start` is emitted. The `agent_id` should come from whichever agent is assigned to execute the node. Look at how the node gets routed to an agent — the agent_id should be available from the routing/dispatch result. Add it to the event data:

```python
event_data: dict[str, Any] = {
    "node": node,
    "agent_id": agent_id,  # ID of the agent executing this node
    "intent": node.intent,  # Promote to top level for frontend
}
```

If the agent_id is not available at the `node_start` emission point, check `node_complete` or the routing step to see where the executing agent is known, and either:
- Move the event emission to after routing, or
- Add a separate `agent_active` event when the agent begins execution

**Important:** Do not break any existing event consumers. The `node` field must remain.

## Step 2: Position RoutingPulse at Target Agent

**File:** `ui/src/canvas/animations.tsx`

The `RoutingPulse` component creates a mesh at `[0,0,0]` and never moves it. Fix this by looking up the target agent's position from the store when the pulse triggers.

Follow the pattern used by `SelfModBloom` (same file, ~line 172-175):

```typescript
// Inside RoutingPulse's useFrame callback, when a new pulse triggers:
const agents = useAppStore.getState().agents;
const target = [...agents.values()].find(a => a.agentId === pulse.target);
if (target && meshRef.current) {
    meshRef.current.position.set(target.position[0], target.position[1], target.position[2]);
}
```

## Step 3: Fix Frontend to Read Correct Event Fields

**File:** `ui/src/store/useStore.ts`

In the `node_start` case handler, update to read the new top-level fields:

```typescript
case 'node_start': {
    soundEngine.playIntentRouting();
    set((s) => {
        const target = data.agent_id as string | undefined;
        const source = data.intent as string | undefined;
        if (target && source) {
            return { pendingRoutingPulse: { source, target } };
        }
        return {};
    });
    break;
}
```

This code may already look like this — the issue was the backend not sending `agent_id`. Verify the field names match what you added in Step 1.

## Step 4: Add Per-Agent Activity Flash

**File:** `ui/src/canvas/agents.tsx`

Agent nodes currently animate breathing and trust-based color but never flash when active. Add a brief brightness boost when an agent's state indicates it was just triggered.

Option A (preferred — timestamp-based):
- Add an `activatedAt` field to the `Agent` type in `ui/src/store/types.ts`
- When `node_start` fires, set `activatedAt = Date.now()` on the target agent in the store
- In `AgentNodes` useFrame loop, check `Date.now() - agent.activatedAt < 500` (500ms flash)
- During the flash window, multiply the color intensity by 2-3x, then ease back to normal

Option B (simpler — state-based):
- In the useFrame loop in `agents.tsx`, read `agent.state`
- If `agent.state === 'active'`, boost color intensity
- This requires the backend to set agent state to 'active' during execution and back to 'idle' after

**Color boost example** (in the existing color assignment section of useFrame):
```typescript
// After computing base color from trust/pool:
const timeSinceActive = Date.now() - (agent.activatedAt ?? 0);
if (timeSinceActive < 500) {
    const flash = 1 + 2 * (1 - timeSinceActive / 500); // 3x -> 1x over 500ms
    color.multiplyScalar(flash);
}
```

## Step 5: Update Agent Store on node_start

**File:** `ui/src/store/useStore.ts`

In the `node_start` handler, also update the target agent's `activatedAt`:

```typescript
case 'node_start': {
    soundEngine.playIntentRouting();
    set((s) => {
        const target = data.agent_id as string | undefined;
        const source = data.intent as string | undefined;
        const updates: Partial<AppState> = {};

        if (target && source) {
            updates.pendingRoutingPulse = { source, target };

            // Flash the target agent
            const agents = new Map(s.agents);
            const agent = agents.get(target);
            if (agent) {
                agents.set(target, { ...agent, activatedAt: Date.now() });
                updates.agents = agents;
            }
        }
        return updates;
    });
    break;
}
```

## Run Tests

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
cd ui && npx vitest run
```

## Verification

After the fix:
1. Open the HXI in a browser
2. Send a query like "read pyproject.toml"
3. The file_reader agent node should briefly flash brighter when it starts executing
4. The RoutingPulse sphere should appear at the agent's position, not the center
5. Send "how are you doing?" to trigger introspection — the introspect agent node should flash
6. The center heartbeat pulse should continue as before (unchanged)
7. All existing tests pass
8. Report final test count

## Update PROGRESS.md

- Update test count on line 2
- Add AD-287 under the appropriate phase noting the HXI activity visualization fix
