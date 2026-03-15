# Fix: Self-Mod Bloom Positioned at New Agent, Not Origin

## Problem

The `SelfModBloom` component in `ui/src/canvas/animations.tsx` renders a flare sphere at `[0,0,0]` (the origin) — which is where the heartbeat agents sit. The bloom should appear at the **new agent's position** on the canvas.

## Fix

### File: `ui/src/canvas/animations.tsx` — `SelfModBloom` component

The `pendingSelfModBloom` value is the agent type string (e.g., `"get_crypto_price"`). Look up any agent with that `agentType` from the store's `agents` map and position the bloom mesh at that agent's coordinates.

Change the component to:

1. Read `agents` from the store: `const agents = useStore((s) => s.agents);`
2. When `bloomAgent` is set, find the matching agent: `const target = [...agents.values()].find(a => a.agentType === bloomAgent);`
3. If found, position the mesh at `target.position`: `meshRef.current.position.set(...target.position);`
4. If not found (agent not yet in the map — possible timing issue), fall back to `[0, 0, 0]`

Update the `useEffect` block:

```typescript
useEffect(() => {
    if (bloomAgent) {
      activeRef.current = true;
      progressRef.current = 0;
      // Position bloom at the new agent's location
      const target = [...agents.values()].find(a => a.agentType === bloomAgent);
      if (target && meshRef.current) {
        meshRef.current.position.set(target.position[0], target.position[1], target.position[2]);
      }
    }
  }, [bloomAgent, agents]);
```

## Constraints

- Only touch `ui/src/canvas/animations.tsx`
- Do NOT change the bloom visual (color, size, timing, opacity curve)
- Do NOT change how `pendingSelfModBloom` is set in the store
- Do NOT modify any Python files
- After editing, rebuild the UI: `cd ui && npm run build`
- Run Python tests to verify no regressions: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
