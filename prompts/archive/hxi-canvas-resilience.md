# AD-329: HXI Canvas Resilience & Component Tests

## Context

The HXI 3D canvas has performance concerns identified by a GPT-5.4 code review. Reactive Zustand subscriptions inside R3F Canvas components cause unnecessary re-renders on every `agent_state` WebSocket event. The `connections.tsx` pool center computation scans the full agent map per connection on every state change. Additionally, zero component-level Vitest tests exist — only `useStore.test.ts` tests the store logic.

The `animations.tsx` file is the gold standard — it uses `useStore.getState()` inside `useFrame` callbacks with zero reactive subscriptions. The other canvas files should follow this pattern where possible.

## Scope

**TypeScript (frontend):**
- `ui/src/canvas/connections.tsx` — cache pool centers, reduce `agents` subscription scope
- `ui/src/components/CognitiveCanvas.tsx` — remove unnecessary action function subscriptions
- `ui/src/components/AgentTooltip.tsx` — remove unnecessary action function subscription
- `ui/src/__tests__/useStore.test.ts` — new component-level tests

**Do NOT change:**
- `ui/src/canvas/agents.tsx` — the `agents` subscription here is necessary for instanced mesh rendering, and the `useMemo` guards are already correct
- `ui/src/canvas/animations.tsx` — already clean, zero reactive subscriptions
- `ui/src/canvas/effects.tsx` — post-processing bloom, unrelated
- `ui/src/store/useStore.ts` — no store changes needed
- Any Python backend files
- Do not add new files — all changes go in existing files

---

## Step 1: Cache Pool Centers in `connections.tsx`

**File:** `ui/src/canvas/connections.tsx`

### 1a: Replace `useStore((s) => s.agents)` with non-reactive read

The `agents` subscription (line 55) is the hot path — every agent state push triggers a re-render plus full `validConnections` recomputation. Connections only need agent positions for pool center calculation, and positions change slowly (layout computation), not on every trust/confidence update.

Replace the reactive `agents` subscription with a ref that updates less frequently:

```typescript
// BEFORE (lines 54-56):
const connections = useStore((s) => s.connections);
const agents = useStore((s) => s.agents);
const connected = useStore((s) => s.connected);

// AFTER:
const connections = useStore((s) => s.connections);
const connected = useStore((s) => s.connected);
const agentsRef = useRef(useStore.getState().agents);
```

Then add a Zustand subscription that only updates the ref (and triggers re-render) when agent count changes — which is when pool centers actually need recalculating:

```typescript
// Add after the ref declaration:
const [agentCount, setAgentCount] = useState(agentsRef.current.size);

useEffect(() => {
    const unsub = useStore.subscribe((state) => {
        agentsRef.current = state.agents;
        // Only re-render when agent count changes (new agent, removed agent)
        if (state.agents.size !== agentCount) {
            setAgentCount(state.agents.size);
        }
    });
    return unsub;
}, [agentCount]);
```

**Add imports at top of file if needed:** `useState` from React, `useEffect` from React.

### 1b: Cache pool centers with `useMemo`

Replace inline `poolCenter()` calls with a cached pool center map:

```typescript
// Add before the existing validConnections useMemo:
const poolCenters = useMemo(() => {
    const centers = new Map<string, [number, number, number]>();
    const agents = agentsRef.current;
    // Build centers once per agent-count change
    agents.forEach((a) => {
        if (!centers.has(a.pool)) {
            centers.set(a.pool, poolCenter(agents, a.pool));
        }
    });
    return centers;
}, [agentCount]);
```

Then update the `validConnections` `useMemo` to use `poolCenters` instead of calling `poolCenter()` per connection:

In the existing `validConnections` memo, replace `poolCenter(agents, ...)` calls with `poolCenters.get(...)`:

```typescript
// In the validConnections useMemo, wherever poolCenter is called:
// BEFORE:
const src = isAgentSource ? agent.position : poolCenter(agents, c.source);
const tgt = isAgentTarget ? agent.position : poolCenter(agents, c.target);

// AFTER:
const src = isAgentSource ? agent.position : (poolCenters.get(c.source) || [0, 0, 0]);
const tgt = isAgentTarget ? agent.position : (poolCenters.get(c.target) || [0, 0, 0]);
```

Update the `useMemo` dependency array to include `poolCenters` instead of `agents`:

```typescript
// BEFORE:
}, [connections, agents]);

// AFTER:
}, [connections, poolCenters]);
```

**Result:** Pool centers are computed once per agent-count change (O(agents)), not once per connection per agent-state change (O(agents × connections)).

---

## Step 2: Remove Unnecessary Action Subscriptions in `CognitiveCanvas.tsx`

**File:** `ui/src/components/CognitiveCanvas.tsx`

### 2a: Replace action subscriptions with `getState()` reads

Lines 21-22 subscribe to `setHoveredAgent` and `setPinnedAgent` — these are Zustand action functions with stable references that never change. Subscribing to them serves no purpose and adds the component to the subscriber list unnecessarily.

```typescript
// BEFORE (lines 20-22 in AgentRaycastLayer):
const agents = useStore((s) => s.agents);
const setHoveredAgent = useStore((s) => s.setHoveredAgent);
const setPinnedAgent = useStore((s) => s.setPinnedAgent);

// AFTER:
const agents = useStore((s) => s.agents);
```

Then wherever `setHoveredAgent` or `setPinnedAgent` are called in the event handlers, use `useStore.getState()`:

```typescript
// In onPointerMove handler:
useStore.getState().setHoveredAgent(agent, { x: e.clientX, y: e.clientY });

// In onClick handler:
useStore.getState().setPinnedAgent(agent);

// In onPointerOut handler:
useStore.getState().setHoveredAgent(null);
```

**Note:** Find all usages of `setHoveredAgent` and `setPinnedAgent` in this component and replace them. There should be 3-4 call sites in the pointer event handlers.

---

## Step 3: Remove Unnecessary Action Subscription in `AgentTooltip.tsx`

**File:** `ui/src/components/AgentTooltip.tsx`

### 3a: Replace `setPinnedAgent` subscription with `getState()` read

```typescript
// BEFORE (lines 7-10):
const hovered = useStore((s) => s.hoveredAgent);
const pinned = useStore((s) => s.pinnedAgent);
const pos = useStore((s) => s.tooltipPos);
const setPinnedAgent = useStore((s) => s.setPinnedAgent);

// AFTER:
const hovered = useStore((s) => s.hoveredAgent);
const pinned = useStore((s) => s.pinnedAgent);
const pos = useStore((s) => s.tooltipPos);
```

Then replace all `setPinnedAgent(...)` calls in the component with `useStore.getState().setPinnedAgent(...)`.

Also update the `useEffect` dependency array — remove `setPinnedAgent` since it's no longer a local variable:

```typescript
// BEFORE:
}, [pinned, setPinnedAgent]);

// AFTER:
}, [pinned]);
```

---

## Step 4: Component Tests

**File:** `ui/src/__tests__/useStore.test.ts`

Add new test sections for component behavior. Since these components use R3F (`@react-three/fiber`), full rendering tests would require a WebGL context — which is complex in Vitest. Instead, test the **logic** that drives the components: pool center caching, connection filtering, and the store interactions these components depend on.

### 4a: Pool center computation tests

```typescript
describe('poolCenter computation (AD-329)', () => {
    it('computes correct center for agents in same pool', () => {
        const agents = new Map<string, Agent>();
        agents.set('a1', {
            id: 'a1', agentType: 'alpha', pool: 'science',
            state: 'active', confidence: 0.8, trust: 0.7, tier: 'domain',
            position: [1, 2, 3],
        });
        agents.set('a2', {
            id: 'a2', agentType: 'beta', pool: 'science',
            state: 'active', confidence: 0.8, trust: 0.7, tier: 'domain',
            position: [3, 4, 5],
        });
        // Import poolCenter or inline the logic
        let cx = 0, cy = 0, cz = 0, count = 0;
        agents.forEach((a) => {
            if (a.pool === 'science') {
                cx += a.position[0]; cy += a.position[1]; cz += a.position[2];
                count++;
            }
        });
        const center: [number, number, number] = [cx / count, cy / count, cz / count];
        expect(center).toEqual([2, 3, 4]);
    });

    it('returns [0,0,0] for empty pool', () => {
        const agents = new Map<string, Agent>();
        let cx = 0, cy = 0, cz = 0, count = 0;
        agents.forEach((a) => {
            if (a.pool === 'nonexistent') {
                cx += a.position[0]; cy += a.position[1]; cz += a.position[2];
                count++;
            }
        });
        const center: [number, number, number] = count === 0 ? [0, 0, 0] : [cx / count, cy / count, cz / count];
        expect(center).toEqual([0, 0, 0]);
    });
});
```

### 4b: Connection filtering tests

```typescript
describe('connection filtering (AD-329)', () => {
    it('filters connections requiring missing agents', () => {
        const agents = new Map<string, Agent>();
        agents.set('a1', {
            id: 'a1', agentType: 'alpha', pool: 'science',
            state: 'active', confidence: 0.8, trust: 0.7, tier: 'domain',
            position: [0, 0, 0],
        });

        const connections = [
            { source: 'a1', target: 'a2', weight: 0.5 },  // a2 doesn't exist
            { source: 'a1', target: 'intent_hub', weight: 0.8 },  // valid
        ];

        // Simulate the filter logic from connections.tsx
        const valid = connections.filter((c) => {
            const sourceIsAgent = agents.has(c.source);
            const targetIsAgent = agents.has(c.target);
            const sourceIsPool = !sourceIsAgent && c.source.includes('_');
            const targetIsPool = !targetIsAgent && c.target.includes('_');
            return (sourceIsAgent || sourceIsPool) && (targetIsAgent || targetIsPool);
        });

        // a1->a2 filtered out (a2 not in map and not a pool), a1->intent_hub kept
        expect(valid.length).toBe(1);
        expect(valid[0].target).toBe('intent_hub');
    });
});
```

### 4c: Tooltip state interaction tests

```typescript
describe('AgentTooltip state (AD-329)', () => {
    it('hoveredAgent and tooltipPos update together', () => {
        const agent: Agent = {
            id: 'test1', agentType: 'test', pool: 'science',
            state: 'active', confidence: 0.9, trust: 0.8, tier: 'domain',
            position: [0, 0, 0],
        };

        useStore.getState().setHoveredAgent(agent, { x: 100, y: 200 });
        expect(useStore.getState().hoveredAgent).toBe(agent);
        expect(useStore.getState().tooltipPos).toEqual({ x: 100, y: 200 });
    });

    it('clearing hoveredAgent sets null', () => {
        useStore.getState().setHoveredAgent(null);
        expect(useStore.getState().hoveredAgent).toBeNull();
    });

    it('pinnedAgent persists after hover clears', () => {
        const agent: Agent = {
            id: 'pin1', agentType: 'pinned', pool: 'eng',
            state: 'active', confidence: 0.9, trust: 0.8, tier: 'domain',
            position: [0, 0, 0],
        };
        useStore.getState().setPinnedAgent(agent);
        useStore.getState().setHoveredAgent(null);
        expect(useStore.getState().pinnedAgent).toBe(agent);
    });
});
```

### 4d: Animation event clearing tests

```typescript
describe('animation event clearing (AD-329)', () => {
    it('clearAnimationEvent resets pendingSelfModBloom', () => {
        useStore.setState({ pendingSelfModBloom: 'test_agent' });
        useStore.getState().clearAnimationEvent('pendingSelfModBloom');
        expect(useStore.getState().pendingSelfModBloom).toBeNull();
    });

    it('clearAnimationEvent resets pendingConsensusFlash', () => {
        useStore.setState({ pendingConsensusFlash: 'flash_1' });
        useStore.getState().clearAnimationEvent('pendingConsensusFlash');
        expect(useStore.getState().pendingConsensusFlash).toBeNull();
    });
});
```

**Total: ~8-10 new Vitest tests** across 4 describe blocks.

---

## Step 5: Update Tracking Files

After all code changes and tests pass:

### PROGRESS.md (line 3)
Update: `Phase 32o complete — Phase 32 in progress (NNNN/NNNN tests + NN Vitest + NN skipped)`

### DECISIONS.md
Append:
```
## Phase 32o: HXI Canvas Resilience & Component Tests (AD-329)

| AD | Decision |
|----|----------|
| AD-329 | HXI Canvas Resilience & Component Tests — (a) `connections.tsx` agents subscription replaced with ref + count-based re-render. Pool centers cached in `useMemo` keyed on agent count, eliminating O(agents×connections) per-state-change recomputation. (b) Unnecessary Zustand action subscriptions removed from `CognitiveCanvas.tsx` and `AgentTooltip.tsx` — stable action refs read via `getState()` instead. (c) Component-level Vitest tests for pool center computation, connection filtering, tooltip state, and animation event clearing. |

**Status:** Complete — N new Vitest tests, NNNN Python + NN Vitest total
```

### progress-era-4-evolution.md
Append:
```
## Phase 32o: HXI Canvas Resilience & Component Tests (AD-329)

**Decision:** AD-329 — Cached pool centers, reduced reactive subscriptions, component tests for canvas logic.

**Status:** Phase 32o complete — NNNN Python + NN Vitest
```

---

## Verification Checklist

Before committing, verify:

1. [ ] `connections.tsx` no longer has `const agents = useStore((s) => s.agents)` — uses ref + count pattern
2. [ ] Pool centers cached in `useMemo` keyed on `agentCount`, not recomputed per connection
3. [ ] `validConnections` memo uses `poolCenters.get()` instead of `poolCenter(agents, ...)`
4. [ ] `CognitiveCanvas.tsx` `AgentRaycastLayer` no longer subscribes to `setHoveredAgent` / `setPinnedAgent`
5. [ ] Event handlers in `AgentRaycastLayer` use `useStore.getState().setHoveredAgent(...)` etc.
6. [ ] `AgentTooltip.tsx` no longer subscribes to `setPinnedAgent`
7. [ ] `useEffect` dependency array in `AgentTooltip` no longer includes `setPinnedAgent`
8. [ ] ~8-10 new Vitest tests in `useStore.test.ts` across 4 describe blocks
9. [ ] Vitest passes: `cd ui && npx vitest run`
10. [ ] Full Python suite still passes: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
11. [ ] PROGRESS.md, DECISIONS.md, progress-era-4-evolution.md updated

## Anti-Scope (Do NOT Build)

- Do NOT modify `canvas/agents.tsx` — its `agents` subscription is needed for instanced mesh rendering
- Do NOT modify `canvas/animations.tsx` — already clean (zero reactive subscriptions)
- Do NOT modify `canvas/effects.tsx` — post-processing bloom, unrelated
- Do NOT modify `store/useStore.ts` — no store changes needed
- Do NOT add R3F rendering tests (require WebGL context) — test the logic, not the rendering
- Do NOT throttle `AgentTooltip` `tooltipPos` updates — the current behavior is functionally correct
- Do NOT create new test files — add all tests to existing `useStore.test.ts`
- Do NOT modify any Python files
- Do NOT export `poolCenter` from `connections.tsx` — test the logic inline in tests
