# Fix: Agent Tooltip Not Appearing on Click/Hover

## Problem

Clicking or hovering on agent nodes in the HXI canvas no longer shows the tooltip with agent info (type, pool, trust, confidence, state). This used to work — it's a regression from recent UI changes.

## Likely causes

1. **Conversation flow rewrite** changed the component structure and the `AgentTooltip` component may no longer be rendered or its state may not be updating
2. **Sphere layout change** updated agent positions but the raycast layer (`AgentRaycastLayer` in `CognitiveCanvas.tsx`) may not be finding intersections because the instanced mesh or its geometry changed
3. **The `AgentRaycastLayer` component** may have been removed or broken during the IntentSurface rewrite

## Diagnosis

Check these files:

1. **`ui/src/App.tsx`** — is `<AgentTooltip />` still rendered?
2. **`ui/src/components/CognitiveCanvas.tsx`** — is `AgentRaycastLayer` still rendered? Does it still have `onPointerMove`, `onPointerOut`, `onClick` handlers on the `<AgentNodes>` component?
3. **`ui/src/components/AgentTooltip.tsx`** — is the component still importing from the store correctly? Check that `hoveredAgent` and `pinnedAgent` state is being read
4. **`ui/src/store/useStore.ts`** — are `hoveredAgent`, `pinnedAgent`, `tooltipPos`, `setHoveredAgent`, `setPinnedAgent` still in the store?
5. **`ui/src/canvas/agents.tsx`** — does the `AgentNodes` component accept and forward pointer event props (`onPointerMove`, `onPointerOut`, `onClick`)?

## Common fix

If the `AgentNodes` component was rewritten and no longer forwards pointer events, add them back:

```tsx
export function AgentNodes({ onPointerMove, onPointerOut, onClick, ...props }) {
  // ... existing instanced mesh rendering
  return (
    <instancedMesh 
      ref={meshRef} 
      args={[undefined, undefined, count]}
      onPointerMove={onPointerMove}
      onPointerOut={onPointerOut}
      onClick={onClick}
    >
      ...
    </instancedMesh>
  );
}
```

## After fix

1. Rebuild: `cd ui && npm run build`
2. Hover an agent node — tooltip with agent info should appear
3. Click an agent node — tooltip should pin
4. Click elsewhere — tooltip should dismiss

---

## ALSO FIX: Heartbeat Sound Continues After Disconnect

The heartbeat sound keeps playing after ProbOS is stopped (WebSocket disconnects). The `setInterval` or `useFrame` loop that triggers the heartbeat sound must check `useStore.getState().connected` before each beat. When `connected` is `false`:
- Stop playing heartbeat
- Stop all ambient sounds
- Clear the heartbeat interval if using `setInterval`

**Check:** `ui/src/audio/soundEngine.ts` — find where the heartbeat loop runs. Add a `connected` check:

```typescript
// Before playing each heartbeat:
if (!useStore.getState().connected) return; // silence when disconnected
```

Also check: is the heartbeat started via `setInterval`? If so, clear the interval when `connected` becomes false and restart it when `connected` becomes true. Use a `useEffect` or store subscription that watches `connected`.
