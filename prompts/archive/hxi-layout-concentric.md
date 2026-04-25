# HXI Layout Fix — Heartbeat at Center, Concentric Rings

## Problem

The heartbeat agents are positioned at the edge of the canvas like any other pool. They should be at the CENTER — the system's sun, the core pulse that everything else orbits around.

## New Layout: Concentric Rings

```
         ○ ○ ○ domain agents (outer ring, radius ~8)
       ○ ○ utility agents (middle ring, radius ~5)
     ○ ○ ○ core agents (inner ring, radius ~3)
           ◉ heartbeat (center, [0, 0, 0])
```

Each ring contains pools of that tier. Within each ring, pools are evenly spaced around the circle. Within each pool, agents are clustered tightly together.

## Implementation

**File:** `ui/src/store/useStore.ts` — rewrite `computeLayout()`:

```typescript
function computeLayout(agents: Map<string, Agent>): Map<string, Agent> {
  // Group agents by pool
  const poolGroups = new Map<string, string[]>();
  agents.forEach((a, id) => {
    const list = poolGroups.get(a.pool) || [];
    list.push(id);
    poolGroups.set(a.pool, list);
  });

  // Separate pools by tier
  const heartbeatPools: string[] = [];
  const corePools: string[] = [];
  const utilityPools: string[] = [];
  const domainPools: string[] = [];

  poolGroups.forEach((_, pool) => {
    // Get tier from first agent in this pool
    const firstId = poolGroups.get(pool)![0];
    const agent = agents.get(firstId);
    if (!agent) return;
    
    if (pool === 'system') {
      heartbeatPools.push(pool);
    } else if (agent.tier === 'core') {
      corePools.push(pool);
    } else if (agent.tier === 'utility') {
      utilityPools.push(pool);
    } else {
      domainPools.push(pool);
    }
  });

  // Sort for deterministic layout
  corePools.sort();
  utilityPools.sort();
  domainPools.sort();

  const updated = new Map(agents);

  // Heartbeat at center [0, 0, 0]
  heartbeatPools.forEach((pool) => {
    const ids = poolGroups.get(pool) || [];
    ids.forEach((id, i) => {
      const agent = updated.get(id);
      if (!agent) return;
      // Tight cluster at center
      const offset = (i - (ids.length - 1) / 2) * 0.3;
      updated.set(id, { ...agent, position: [offset, 0, offset * 0.5] });
    });
  });

  // Helper: place pools in a ring
  function placeRing(pools: string[], radius: number, yOffset: number) {
    pools.forEach((pool, poolIndex) => {
      const ids = poolGroups.get(pool) || [];
      const angle = (poolIndex / Math.max(pools.length, 1)) * Math.PI * 2;
      const cx = Math.cos(angle) * radius;
      const cz = Math.sin(angle) * radius;

      ids.forEach((id, i) => {
        const agent = updated.get(id);
        if (!agent) return;
        // Cluster agents within pool — small spread
        const subAngle = (i / Math.max(ids.length, 1)) * Math.PI * 2;
        const spread = 0.4;
        updated.set(id, {
          ...agent,
          position: [
            cx + Math.cos(subAngle) * spread,
            yOffset + Math.sin(i * 0.7) * 0.3,  // slight Y variation
            cz + Math.sin(subAngle) * spread,
          ],
        });
      });
    });
  }

  // Core agents — inner ring
  placeRing(corePools, 3.5, -0.5);

  // Utility agents — middle ring
  placeRing(utilityPools, 5.5, 0);

  // Domain agents — outer ring
  placeRing(domainPools, 8, 0.5);

  return updated;
}
```

## Also update the heartbeat pulse position

**File:** `ui/src/canvas/animations.tsx` — in `HeartbeatPulse`:

The heartbeat pulse sphere should always be at `[0, 0, 0]` (the center) instead of computing the average position of system pool agents. Simplify:

```typescript
// Replace the dynamic position calculation with:
meshRef.current.position.set(0, 0, 0);
meshRef.current.visible = true;
```

## Camera adjustment

**File:** `ui/src/components/CognitiveCanvas.tsx`:

Update the camera to look at the center from a slightly elevated angle that shows the concentric ring structure:

```tsx
camera={{ position: [0, 10, 14], fov: 50, near: 0.1, far: 100 }}
```

The `target` for OrbitControls should be `[0, 0, 0]` (already is).

## Do NOT Change

- No Python code changes
- No store schema changes (only layout computation)
- No new components
- No event protocol changes

## After applying

Rebuild: `cd ui && npm run build`

The heartbeat should now be the brightest glowing center point, with core agents in the first ring, utility in the second, and domain agents in the outer ring — like a solar system of cognition.
