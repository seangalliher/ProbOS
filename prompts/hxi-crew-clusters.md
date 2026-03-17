# AD-294: Crew Team Sub-Clusters in HXI Canvas

## Objective

Replace the current flat Fibonacci sphere layout with gravitational sub-clusters that visually group agents by crew team. Each pool group gets its own spatial cluster with a subtle translucent boundary shell, making organizational structure immediately visible on the canvas. Currently agents are sorted by group for adjacency but have no visual boundary — a user can't distinguish teams without hovering on each sphere.

## Architecture

```
Current layout (flat Fibonacci sphere):
    ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉   ← all agents on one sphere, sorted but no boundary
    ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉

New layout (gravitational sub-clusters):
    ┌─ ─ ─ ─ ─ ┐     ┌─ ─ ─ ─ ─ ─ ─ ┐
    │ Medical   │     │ Core Systems  │
    │  ◉ ◉ ◉   │     │ ◉ ◉ ◉ ◉ ◉ ◉ │
    │  ◉ ◉     │     │ ◉ ◉          │
    └─ ─ ─ ─ ─ ┘     └─ ─ ─ ─ ─ ─ ─ ┘
  ┌─ ─ ─ ─ ─ ─ ─ ─ ┐   ┌─ ─ ─ ─ ─ ┐
  │ Bundled Agents   │   │ Self-Mod  │
  │ ◉ ◉ ◉ ◉ ◉ ◉ ◉  │   │  ◉ ◉     │
  │ ◉ ◉ ◉           │   └─ ─ ─ ─ ─ ┘
  └─ ─ ─ ─ ─ ─ ─ ─ ┘
```

Each cluster:
- Has its own center point, positioned on a larger spacing sphere
- Agents within the cluster orbit the center on a mini Fibonacci sphere
- A faint translucent wireframe sphere (the "boundary shell") wraps the cluster
- The shell color matches the team's dominant tint color
- A floating text label displays the team name

## Pre-read

Before starting, read these files:
- `ui/src/store/useStore.ts` — `computeLayout()` function (lines 35-100), pool group data handling (lines 287-295)
- `ui/src/canvas/agents.tsx` — `AgentNodes` instanced mesh rendering
- `ui/src/canvas/scene.ts` — `POOL_TINT_HEXES`, `poolTintBlend()`, tier sizing
- `ui/src/store/types.ts` — `PoolGroupInfo`, `StateSnapshot`, `Agent` interfaces
- `ui/src/components/CognitiveCanvas.tsx` — scene composition
- `ui/src/canvas/connections.tsx` — `poolCenter()` helper (line 38) — already computes pool centers
- `ui/src/canvas/effects.tsx` — bloom post-processing

## Files to Modify

### `ui/src/store/useStore.ts`

**Replace `computeLayout()` with a group-aware cluster layout:**

The new layout algorithm:

1. **Categorize agents by group:** Use the `poolToGroup` map to bucket agents. Agents not in any group go to an "ungrouped" bucket.

2. **Compute cluster center points:** Distribute group centers on a larger spacing sphere. Use Fibonacci sphere for the group centers too, so they're evenly spaced. Radius for group centers: `6.0` (core/domain tiers share the same space now since clustering provides the visual separation that tiers previously did).

3. **Place agents within each cluster:** Each cluster's agents get positioned on a mini Fibonacci sphere centered on the group center. Mini sphere radius scales with agent count: `radius = 0.8 + Math.sqrt(agentCount) * 0.4`. This keeps small teams tight and large teams proportionally bigger.

4. **Heartbeat agents stay at world center (0,0,0)** — same as current behavior.

5. **Store group layout data** for use by the boundary shell renderer. Add to HXI state:

```typescript
// In HXIState interface:
groupCenters: Map<string, { center: [number, number, number]; radius: number; displayName: string; tintHex: string }>;
```

Initialize as `new Map()`. Populate during `computeLayout()`.

**Group tint color mapping** — add after `POOL_HUES`:

```typescript
const GROUP_TINT_HEXES: Record<string, string> = {
  core: '#7090c0',       // cool blue — infrastructure
  bundled: '#70a080',    // teal green — user-facing tools
  medical: '#c06060',    // warm red — sickbay
  self_mod: '#a078b0',   // purple — self-modification
  consensus: '#c85068',  // red — tactical
};
```

**Updated `computeLayout` signature:**

```typescript
function computeLayout(
  agents: Map<string, Agent>,
  poolToGroup?: Record<string, string>,
  poolGroups?: Record<string, PoolGroupInfo>,
): { agents: Map<string, Agent>; groupCenters: Map<string, { center: [number, number, number]; radius: number; displayName: string; tintHex: string }> }
```

The function now returns both the positioned agents and the group center metadata.

**Update all `computeLayout()` call sites** (there are 3: `state_snapshot` handler, `agent_state` handler, and the fallback). Each now destructures `{ agents, groupCenters }` and sets both in state.

### `ui/src/canvas/clusters.tsx` (NEW FILE)

**Create a new component `TeamClusters` that renders:**

1. **Boundary shells** — one per group. A translucent wireframe sphere at each group center:

```typescript
import { useStore } from '../store/useStore';
import { Text } from '@react-three/drei';
import * as THREE from 'three';

export function TeamClusters() {
  const groupCenters = useStore((s) => s.groupCenters);
  const connected = useStore((s) => s.connected);

  if (!connected || groupCenters.size === 0) return null;

  return (
    <group>
      {Array.from(groupCenters.entries()).map(([name, { center, radius, displayName, tintHex }]) => (
        <group key={name} position={center}>
          {/* Boundary shell — translucent wireframe sphere */}
          <mesh>
            <sphereGeometry args={[radius * 1.15, 16, 12]} />
            <meshBasicMaterial
              color={tintHex}
              transparent
              opacity={0.04}
              wireframe
              toneMapped={false}
              depthWrite={false}
            />
          </mesh>
          {/* Faint solid inner glow */}
          <mesh>
            <sphereGeometry args={[radius * 1.1, 16, 12]} />
            <meshBasicMaterial
              color={tintHex}
              transparent
              opacity={0.015}
              side={THREE.BackSide}
              toneMapped={false}
              depthWrite={false}
            />
          </mesh>
          {/* Team name label — floats above the cluster */}
          <Text
            position={[0, radius * 1.3, 0]}
            fontSize={0.25}
            color={tintHex}
            anchorX="center"
            anchorY="bottom"
            fillOpacity={0.5}
            font={undefined}
          >
            {displayName}
          </Text>
        </group>
      ))}
    </group>
  );
}
```

**Design notes for the shell:**
- Wireframe sphere at `opacity={0.04}` — barely visible, just enough to suggest a boundary
- Inner BackSide solid sphere at `opacity={0.015}` — adds a subtle volumetric glow behind the agents
- Both use `depthWrite={false}` so they don't occlude agents or connections
- Both use `toneMapped={false}` so bloom post-processing amplifies the glow naturally
- The text uses `fillOpacity={0.5}` — visible but not dominant
- `@react-three/drei` `Text` is already a dependency (used by OrbitControls from drei)

### `ui/src/components/CognitiveCanvas.tsx`

**Add `TeamClusters` to the scene:**

```typescript
import { TeamClusters } from '../canvas/clusters';
```

Add `<TeamClusters />` after `<AgentRaycastLayer />` and before `<Connections />`:

```tsx
<AgentRaycastLayer />
<TeamClusters />
<Connections />
```

### `ui/src/canvas/connections.tsx`

**No changes needed** — the existing `poolCenter()` function computes connection endpoints from agent positions, so connections will naturally follow agents to their new cluster positions.

### `ui/src/store/types.ts`

**No changes needed** — `PoolGroupInfo` already carries the data we need. The `groupCenters` map is a derived layout structure stored in the Zustand state, not a type from the backend.

## Layout Algorithm Detail

```typescript
function computeLayout(
  agents: Map<string, Agent>,
  poolToGroup?: Record<string, string>,
  poolGroups?: Record<string, PoolGroupInfo>,
) {
  const updated = new Map(agents);
  const groupCenters = new Map<string, { center: [number, number, number]; radius: number; displayName: string; tintHex: string }>();

  // 1. Heartbeat agents at center
  const heartbeatIds: string[] = [];
  agents.forEach((a, id) => {
    if (a.pool === 'system') heartbeatIds.push(id);
  });
  heartbeatIds.forEach((id, i) => {
    const agent = updated.get(id);
    if (!agent) return;
    const offset = (i - (heartbeatIds.length - 1) / 2) * 0.25;
    updated.set(id, { ...agent, position: [offset * 0.5, 0, offset * 0.3] });
  });

  // 2. Bucket non-heartbeat agents by group
  const groups: Record<string, string[]> = {};  // groupName -> agentIds
  const ungrouped: string[] = [];

  agents.forEach((a, id) => {
    if (a.pool === 'system') return;  // already handled
    const groupName = poolToGroup?.[a.pool];
    if (groupName) {
      (groups[groupName] ??= []).push(id);
    } else {
      ungrouped.push(id);
    }
  });

  // 3. Compute group center positions on a spacing sphere
  const groupNames = Object.keys(groups).sort();
  if (ungrouped.length > 0) groupNames.push('_ungrouped');

  const groupCenterRadius = 6.0;
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  const totalGroups = groupNames.length;

  groupNames.forEach((gName, gi) => {
    const ids = gName === '_ungrouped' ? ungrouped : groups[gName];
    if (!ids || ids.length === 0) return;

    // Fibonacci point for this group's center
    const y = 1 - (gi / (totalGroups - 1 || 1)) * 2;
    const radiusAtY = Math.sqrt(1 - y * y);
    const theta = goldenAngle * gi;
    const cx = Math.cos(theta) * radiusAtY * groupCenterRadius;
    const cz = Math.sin(theta) * radiusAtY * groupCenterRadius;
    const cy = y * groupCenterRadius * 0.5;  // compress Y

    // Mini Fibonacci sphere for agents within this group
    const clusterRadius = 0.8 + Math.sqrt(ids.length) * 0.4;

    ids.forEach((id, ai) => {
      const agent = updated.get(id);
      if (!agent) return;
      const n = ids.length;
      const ay = 1 - (ai / (n - 1 || 1)) * 2;
      const ar = Math.sqrt(1 - ay * ay);
      const at = goldenAngle * ai;
      const ax = Math.cos(at) * ar * clusterRadius + cx;
      const az = Math.sin(at) * ar * clusterRadius + cz;
      const ayPos = ay * clusterRadius * 0.6 + cy;
      updated.set(id, { ...agent, position: [ax, ayPos, az] });
    });

    // Store group center for shell rendering
    const displayName = poolGroups?.[gName]?.display_name || gName;
    const tintHex = GROUP_TINT_HEXES[gName] || '#8888a0';
    groupCenters.set(gName, {
      center: [cx, cy, cz],
      radius: clusterRadius,
      displayName,
      tintHex,
    });
  });

  return { agents: updated, groupCenters };
}
```

## Testing

### `ui/src/__tests__/useStore.test.ts`

Add tests:

1. **`test('computeLayout clusters agents by group')`** — Create agents in medical and core pools, provide poolToGroup map. Verify agents in the same group are positioned near each other (distance < cluster radius) and agents in different groups are far apart (distance > group spacing).

2. **`test('computeLayout returns groupCenters')`** — Verify groupCenters map contains entries for each group with center, radius, displayName, and tintHex.

3. **`test('computeLayout handles ungrouped agents')`** — Create agents not in any pool group. Verify they get positioned (not left at origin) and appear in the `_ungrouped` group center.

4. **`test('computeLayout heartbeat stays at center')`** — Verify system pool agents remain near world origin regardless of grouping.

5. **`test('state_snapshot populates groupCenters')`** — Simulate a state_snapshot event with pool_groups data. Verify state.groupCenters is populated.

## Constraints

- **No new npm dependencies** — `@react-three/drei` (for `Text`) is already installed
- **Performance** — boundary shells are low-poly (16 segments) wireframe with `depthWrite={false}`. No per-frame allocation. Only re-rendered when agents change.
- **Backward compatible** — if no pool groups data arrives (e.g., old backend), falls back to current flat Fibonacci sphere layout
- **Dream mode** — shells should dim/fade with the rest during dream mode (handled by existing bloom adjustment)
- **Fog compatibility** — shells are within fog range, so distant clusters naturally fade

## Success Criteria

- Agents visually cluster by crew team on the canvas
- Each cluster has a faint translucent boundary shell in the team's tint color
- Team names float above each cluster
- Medical agents (warm red cluster) are clearly separated from core agents (blue cluster), bundled agents (green cluster), and self-mod agents (purple cluster)
- Heartbeat agents remain at world center
- Connections still render correctly between agents across clusters
- Bloom post-processing amplifies the shell glow subtly
- All existing Vitest tests pass
- 5 new layout tests pass
- The canvas still performs smoothly (no frame drops from the new geometry)
