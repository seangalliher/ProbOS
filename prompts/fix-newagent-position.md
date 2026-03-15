# Fix: New Agent Spawns at Center + Self-Mod Visual Distinction

## Problem 1: New agents spawn at [0,0,0]

When self-mod creates a new agent, it appears at the center of the canvas (near the heartbeat) instead of on the outer domain sphere where it belongs. The Fibonacci sphere layout is only computed on initial state_snapshot — dynamically added agents don't get repositioned.

## Fix 1: Recalculate layout when agents change

**File:** `ui/src/store/useStore.ts`

The `computeLayout()` function runs when processing a `state_snapshot` event. It also needs to run when:
- A new agent appears (via `agent_state` or `self_mod_success` WebSocket event)
- The agent count changes

In the event handler, after adding a new agent to the `agents` Map, recompute layout for ALL agents:

```typescript
// After updating agents map with new agent:
const updatedAgents = computeLayout(get().agents);
set({ agents: updatedAgents });
```

Make sure `computeLayout()` preserves existing agents' positions when possible — only assign new positions to agents that don't have one (or have [0,0,0]). This prevents existing agents from jumping when a new one is added.

```typescript
function computeLayout(agents: Map<string, Agent>): Map<string, Agent> {
    // ... existing Fibonacci sphere logic ...
    
    // For each agent, only update position if it's at [0,0,0] (unpositioned)
    // OR if it's a new agent not yet in the layout
    // This prevents existing agents from repositioning when a new one spawns
}
```

## Problem 2: Self-mod bloom looks like heartbeat

The self-mod new-agent bloom effect (golden flash) fires at [0,0,0] — same location as the heartbeat pulse. They're visually indistinguishable.

## Fix 2: Self-mod bloom at the NEW agent's position

**File:** `ui/src/canvas/animations.tsx` — in `SelfModBloom`

Instead of flashing at a fixed position (center), the bloom should:
1. Wait for the `computeLayout()` to assign the new agent its position on the domain sphere
2. Flash at THAT position — the outer ring where the new agent actually appears
3. Use a DIFFERENT visual than heartbeat — brighter, faster bloom with a rising particle trail. Not just a bigger heartbeat pulse

If the new agent's position isn't known yet when the bloom triggers, add a small delay (200ms) before the flash to let layout recalculate:

```typescript
// When self_mod_success event arrives:
// 1. Agent gets added to store
// 2. Layout recalculates (agent gets position on domain sphere)
// 3. After 200ms delay, bloom flash at the new agent's computed position
```

The bloom effect should be visually distinct:
- **Color:** bright cyan-white (distinct from heartbeat's warm amber)
- **Shape:** expanding ring that settles into the agent node (not a sphere pulse)
- **Duration:** 800ms (faster than heartbeat's 1.2s cycle)
- **Brightness:** 2x brighter than heartbeat pulse

## After fix

1. Rebuild: `cd ui && npm run build`
2. Restart `probos serve`
3. Trigger self-mod: "Send a message to my Discord channel saying hello"
4. Click [✨ Build Agent]
5. Watch: new agent should appear on the OUTER ring of the sphere, with a distinct bright bloom
6. The bloom should NOT be at the center near the heartbeat
