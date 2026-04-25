# HXI Disconnected State — "The Mesh Goes Dark"

## Problem

When the WebSocket disconnects (server shutdown, network loss), the HXI canvas continues animating — agents keep glowing, heartbeat keeps pulsing, breathing continues. This is wrong. If the connection is lost, the mesh should visually go dark. The UI is lying about the system's state.

## The Spec Says

From `hxi-architecture-v2.md`: "If the WebSocket disconnects, the HXI freezes but ProbOS continues working. Reconnect and the state catches up."

## What Should Happen

When `connected` becomes `false` in the Zustand store:

### Visual Changes
1. **All agent nodes dim** — reduce emissive intensity to near zero (0.05). They become barely visible dark spheres. Not invisible — dark, like lights turned off
2. **Heartbeat pulse stops** — no pulse animation. The system's heart isn't beating (from the UI's perspective)
3. **Breathing stops** — no ±3% radius oscillation. Agents are frozen
4. **Bloom intensity drops** — reduce bloom to 0.2 (barely any glow)
5. **Connections fade** — connection opacity drops to 0.05 (nearly invisible)
6. **Color grading shifts cool/dark** — the scene gets colder, darker
7. **Background particles stop** — ambient motion ceases
8. **Auto-rotation stops** — camera freezes where it was

### UI Changes
1. **Status bar shows "● Disconnected" in red** — replaces "● Live — 43 agents"
2. **A subtle overlay message** in the center of the canvas: "Connection lost — reconnecting..." (translucent, not blocking the view)
3. **Reconnection pulse** — every reconnect attempt makes the "reconnecting..." text briefly brighten

### When Connection Restores
1. **State snapshot arrives** — store rebuilds from the fresh snapshot
2. **Agents bloom back to life** — emissive intensity ramps back up over 1 second
3. **Heartbeat resumes** — first beat after reconnect is slightly stronger (a "waking up" beat)
4. **Breathing resumes**
5. **Bloom restores**
6. **Status bar shows "● Live" again in green**
7. **"Reconnecting..." overlay fades out**

## Implementation

### File: `ui/src/canvas/agents.tsx`

In the `useFrame` callback, check the connected state:

```typescript
const connected = useStore.getState().connected;

// Confidence/emissive modulation based on connection
const effectiveIntensity = connected 
  ? confidenceToIntensity(agent.confidence)
  : 0.05; // nearly dark

// Breathing only when connected
const breathScale = connected 
  ? (1 + Math.sin(breathPhase) * 0.03)
  : 1.0; // frozen
```

### File: `ui/src/canvas/animations.tsx`

In `HeartbeatPulse`:
```typescript
const connected = useStore.getState().connected;
if (!connected) {
  // No pulse — hide
  meshRef.current.visible = false;
  return;
}
```

### File: `ui/src/canvas/effects.tsx`

Adjust bloom based on connection:
```typescript
const connected = useStore((s) => s.connected);
const bloomIntensity = connected ? grading.bloomStrength : 0.2;
```

### File: `ui/src/canvas/connections.tsx`

Fade connections when disconnected:
```typescript
const connected = useStore.getState().connected;
const opacity = connected 
  ? (0.4 + weight * 0.5) 
  : 0.05;
```

### File: `ui/src/components/DecisionSurface.tsx` (or status bar component)

Show disconnected state:
```typescript
const connected = useStore((s) => s.connected);
// Change status indicator: "● Disconnected" in red vs "● Live" in green
```

### File: `ui/src/components/CognitiveCanvas.tsx`

Add a centered reconnecting overlay when disconnected:
```tsx
{!connected && (
  <div style={{
    position: 'absolute',
    top: '50%', left: '50%',
    transform: 'translate(-50%, -50%)',
    color: 'rgba(200, 56, 72, 0.6)',
    fontSize: 16,
    fontFamily: "'Inter', sans-serif",
    textAlign: 'center',
    zIndex: 15,
    pointerEvents: 'none',
  }}>
    Connection lost — reconnecting...
  </div>
)}
```

### File: `ui/src/components/CognitiveCanvas.tsx`

Stop auto-rotation when disconnected:
```tsx
<OrbitControls
  autoRotate={connected}
  ...
/>
```

## Do NOT Change
- No Python code changes
- No WebSocket protocol changes
- No store schema changes (the `connected` boolean already exists)
- The reconnection logic in `useWebSocket.ts` already handles reconnection with exponential backoff — just make sure it updates `connected` in the store

## After Applying
1. Rebuild: `cd ui && npm run build`
2. Start `probos serve`
3. Open HXI in browser — should be live and glowing
4. Stop `probos serve` (Ctrl+C) — the HXI should go dark within seconds: agents dim, heartbeat stops, "Disconnected" appears
5. Restart `probos serve` — the HXI should bloom back to life when it reconnects
