# HXI Layout Fix — Smaller Heartbeat + Spherical Distribution + Visible Connections

## Problems

1. **Heartbeat pulse ring is too large** — it overlaps and covers other agents. The heartbeat should be a small, pulsing nucleus at the center, not a giant ring that obscures everything
2. **Agents are on a flat plane** — the concentric rings layout is 2D. A spherical distribution would look more organic and three-dimensional, like a cell viewed under a microscope
3. **Connections are washed out** — the Hebbian connection curves are faint, low-opacity lines that get lost against the bloom glow. They need color, opacity, and width that cuts through the atmosphere

## Fix 1: Smaller heartbeat pulse

**File:** `ui/src/canvas/animations.tsx` — in `HeartbeatPulse`:

Reduce the heartbeat sphere sizes dramatically:
- The current sphere geometry `args={[2.5, 16, 16]}` (or whatever it is now) should be `args={[0.8, 16, 16]}` — much smaller
- If there are multiple concentric rings for the pulse, reduce all of them proportionally
- The heartbeat should be a compact, bright, pulsing point at center — NOT a large translucent sphere that covers agents
- Max opacity of the pulse: 0.25 (not higher — it shouldn't obscure anything behind it)

## Fix 2: Spherical agent distribution

**File:** `ui/src/store/useStore.ts` — rewrite `computeLayout()`:

Instead of placing agents on flat concentric rings, distribute them on the surface of concentric SPHERES. Each tier gets a sphere at a different radius. Agents are distributed using a Fibonacci sphere (golden angle) for even spacing.

```typescript
function computeLayout(agents: Map<string, Agent>): Map<string, Agent> {
  const poolGroups = new Map<string, string[]>();
  agents.forEach((a, id) => {
    const list = poolGroups.get(a.pool) || [];
    list.push(id);
    poolGroups.set(a.pool, list);
  });

  // Collect all agents by tier
  const heartbeat: string[] = [];
  const core: string[] = [];
  const utility: string[] = [];
  const domain: string[] = [];

  agents.forEach((a, id) => {
    if (a.pool === 'system') heartbeat.push(id);
    else if (a.tier === 'core') core.push(id);
    else if (a.tier === 'utility') utility.push(id);
    else domain.push(id);
  });

  const updated = new Map(agents);

  // Heartbeat at center — tight cluster
  heartbeat.forEach((id, i) => {
    const agent = updated.get(id);
    if (!agent) return;
    const offset = (i - (heartbeat.length - 1) / 2) * 0.25;
    updated.set(id, { ...agent, position: [offset * 0.5, 0, offset * 0.3] });
  });

  // Fibonacci sphere distribution for even spacing
  function fibonacciSphere(ids: string[], radius: number) {
    const n = ids.length;
    const goldenAngle = Math.PI * (3 - Math.sqrt(5)); // ~2.3999 radians
    
    ids.forEach((id, i) => {
      const agent = updated.get(id);
      if (!agent) return;
      
      // Fibonacci sphere point distribution
      const y = 1 - (i / (n - 1 || 1)) * 2; // y goes from 1 to -1
      const radiusAtY = Math.sqrt(1 - y * y);
      const theta = goldenAngle * i;
      
      const x = Math.cos(theta) * radiusAtY * radius;
      const z = Math.sin(theta) * radiusAtY * radius;
      const yPos = y * radius * 0.6; // compress Y a bit so it's not too tall
      
      updated.set(id, { ...agent, position: [x, yPos, z] });
    });
  }

  // Place tiers on concentric spheres
  fibonacciSphere(core, 3.5);     // inner sphere
  fibonacciSphere(utility, 5.5);   // middle sphere  
  fibonacciSphere(domain, 7.5);    // outer sphere

  return updated;
}
```

This creates a 3D cloud of agents surrounding the heartbeat nucleus. When you orbit the camera, you see agents at different depths — some in front, some behind. It looks like a living cell with organelles distributed throughout.

**Pool clustering:** The Fibonacci sphere distributes agents evenly but doesn't group by pool. To maintain pool clustering while using the sphere:

```typescript
// Sort agents by pool BEFORE distributing on sphere
// This groups agents from the same pool into adjacent Fibonacci positions
core.sort((a, b) => {
  const poolA = agents.get(a)?.pool || '';
  const poolB = agents.get(b)?.pool || '';
  return poolA.localeCompare(poolB);
});
// Same for utility and domain
```

This way agents from the same pool end up near each other on the sphere surface — they cluster naturally without explicit positioning.

## Camera adjustment

**File:** `ui/src/components/CognitiveCanvas.tsx`:

The camera should start at a position that shows the spherical depth:

```tsx
camera={{ position: [0, 5, 16], fov: 50, near: 0.1, far: 100 }}
```

Enable a very slow auto-rotation so newcomers see the 3D structure:

```tsx
<OrbitControls
  autoRotate
  autoRotateSpeed={0.15}   // very slow — barely perceptible
  enablePan
  enableZoom
  enableRotate
  // ... rest unchanged
/>
```

The auto-rotation stops when the user interacts (OrbitControls does this automatically) and resumes after they let go.

## Fix 3: Make connections visible and vibrant

**File:** `ui/src/canvas/connections.tsx`

The connections are washed out — they blend into the bloom and disappear. Fix:

1. **Use a brighter, more saturated color** — not `#f0e8e0` (warm white, gets lost in bloom). Use a distinct accent color that contrasts with the agent glow:
   - Suggest: electric cyan `#00d4ff` or bright teal `#40e0d0` — these contrast with the warm amber/gold agent glow and won't wash out against bloom
   - Alternative: bright warm gold `#ffaa30` with high opacity — stands out against the cool blue agents

2. **Increase minimum opacity** — connections should never be nearly invisible:
   - Minimum opacity: `0.4` (was likely 0.15-0.3)
   - Maximum opacity: `0.9`
   - Formula: `opacity = 0.4 + weight * 0.5`

3. **Use `toneMapped={false}`** on the connection material — this prevents the tone mapping pass from darkening the connections. The connections should be as bright as the agents

4. **If using `LineBasicMaterial`** — set `linewidth` higher (though WebGL caps this at 1 on most platforms). If lines are too thin:
   - Replace `THREE.Line` with `THREE.TubeGeometry` along the bezier curve for thicker, glowing connections
   - Tube radius: `0.015 + weight * 0.025` — thin but visible
   - Use `MeshBasicMaterial` with the accent color and `toneMapped: false`
   - This creates connections that GLOW through the bloom like luminous nerve fibers

5. **Consider using `@react-three/drei`'s `Line` component** if available — it supports `lineWidth` in screen-space pixels (via WebGL2 + drei shaders), bypassing the WebGL1 linewidth cap. `lineWidth={1.5 + weight * 3}` would give visible, weight-differentiated lines

## Do NOT Change

- No Python code changes
- No store schema changes (only layout computation)
- No new components
- No event protocol changes
- Keep the concentric tier concept (heartbeat center, core inner, utility middle, domain outer) — just distribute on spheres instead of flat rings

## After applying

Rebuild: `cd ui && npm run build`

The canvas should show a 3D cloud of glowing agents surrounding a small bright nucleus. Rotating the camera reveals depth — agents in front and behind. Pool clusters are visible as groups of similar-colored nodes on the sphere surface.
