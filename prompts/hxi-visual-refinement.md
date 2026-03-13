# HXI Visual Refinement — "Make It Wow"

## Context

The HXI MVP (Phase 23) is functionally complete — WebSocket event stream, Zustand store, Three.js canvas, React overlays, 47 agent nodes, status bar, chat input. But it looks like **dots on a dark background**, not **bioluminescent cognition**. The spec (`Vibes/hxi-architecture-v2.md`) describes a visual experience that makes people stop scrolling. What's on screen doesn't do that yet.

This is a **visual polish iteration**, not a new phase. No Python changes. No new tests. No architectural changes. Only TypeScript/Three.js rendering improvements in the existing `ui/src/` files.

**Current state:** 1532/1532 Python tests passing. AD-261 highest. No AD numbers consumed for visual refinement — this is craft work within the existing AD-256 through AD-259 scope.

**Goal:** After this pass, a 5-second GIF of the HXI with a self-mod trigger (new agent blooming into existence) should make someone say "what is this?" and click through.

---

## Read First

- `Vibes/hxi-architecture-v2.md` — section "Visual Design Specification" through "Motion System". This is the visual bible. Every fix below refers back to it.

---

## Problems and Fixes

### Problem 1: No visible connections — the mesh looks like scattered dots

**Root cause:** `Connections` component in `connections.tsx` filters on `agents.has(c.source) && agents.has(c.target)`. Hebbian weights have source=intent name (e.g., "read_file"), target=agent_id. The intent name is NOT an agent ID, so `agents.has(c.source)` returns false. All connections are filtered out.

**Fix in `ui/src/canvas/connections.tsx`:**
- Change the filter: if `source` is not an agent ID (not in the agents map), treat it as an intent hub at the center of its target agent's pool cluster
- For intent→agent connections: position the source at the pool center (average position of all agents in the target agent's pool), draw the curve from there
- For agent→agent connections: use both agent positions directly
- Increase the minimum opacity so connections are visible: `opacity = Math.min(0.3 + weight * 0.5, 0.9)` (was `0.15 + weight * 0.6`)
- Use a warmer, more luminous line color: `#f0dcc0` instead of `#f0e8e0`
- Add a subtle glow by making lines thicker: use `linewidth: 1 + weight * 3` (note: WebGL line width may be capped at 1 on some platforms — consider using `THREE.TubeGeometry` for thicker curves if `linewidth` doesn't work)

**Alternative for thick glowing connections:** Replace `THREE.Line` with a thin `THREE.TubeGeometry` along the bezier curve. Radius = `0.01 + weight * 0.03`. Use `MeshBasicMaterial` with `toneMapped: false` so it glows through bloom. This creates the "luminous nerve fiber" look from the spec.

### Problem 2: No bloom glow — agents are flat circles, not luminous spheres

**Root cause:** Bloom post-processing is present (`Effects` component) but the bloom settings are too conservative and the agent material isn't configured to emit light that triggers bloom.

**Fix in `ui/src/canvas/effects.tsx`:**
```tsx
<Bloom
  intensity={1.5}           // was: grading.bloomStrength (likely ~0.8)
  luminanceThreshold={0.1}   // was: 0.2 — lower threshold catches more glow
  luminanceSmoothing={0.4}   // was: 0.9 — sharper bloom edges
  mipmapBlur
/>
```

**Fix in `ui/src/canvas/agents.tsx`:**
```tsx
<meshStandardMaterial
  color="#ffffff"
  emissive="#f0b060"
  emissiveIntensity={1.5}    // was: 0.5 — much brighter emission
  toneMapped={false}          // CRITICAL — exempt from tone mapping so emissive goes above 1.0
  transparent
  opacity={0.95}
/>
```

Also: the instanced color is being set in `useFrame` via `_tempColor.multiplyScalar(intensity)`, but the instance color multiplied by `emissiveIntensity` might not be reaching bloom threshold. Consider using `MeshBasicMaterial` instead of `MeshStandardMaterial` with `toneMapped: false` — basic material doesn't respond to lighting but produces consistent bright colors that bloom cleanly.

**Test:** After this fix, agents should have a visible soft glow halo around them, not just a colored circle.

### Problem 3: All agents are the same amber color — no trust differentiation

**Root cause:** `trustToColor()` in `scene.ts` is implemented correctly (amber→blue→violet), but in the screenshot all 47 agents are amber, suggesting all agents have trust ≥ 0.8 (the default Beta(2,2) = 0.5 should be blue-white, not amber).

**Investigation:** Check `build_state_snapshot()` in `runtime.py` — verify it sends actual trust scores, not default 0.5. Check `useStore.ts` — verify the snapshot handler maps trust correctly.

**If trust data IS being sent correctly:** Then all agents genuinely have high trust (they've been running successfully). Make the spectrum more visually distinct by widening the hue bands:
- High trust (0.7-1.0): warm amber/gold
- Medium trust (0.4-0.7): cooler blue-white  
- Low trust (0.0-0.4): deep violet
- Also: slightly vary the hue per-pool using `poolTint()` blend — mix 70% trust color + 30% pool tint for visual variety even when trust is similar

### Problem 4: No depth — everything looks flat on a 2D plane

**Root cause:** Camera at `[0, 6, 12]` looking down at a flat plane of agents all at similar Y values.

**Fixes:**
- **Stagger Y positions by tier more dramatically:** `TIER_Y = { core: -3, utility: 0, domain: 3 }` (was -2/0/2)
- **Add Z variation within pools:** offset agents in Z as well as X. Use a slight spiral: `position = [cx + cos(i * 0.5) * 0.4, tierY + sin(i * 0.3) * 0.3, cz + sin(i * 0.5) * 0.4]`
- **Add a subtle particle field** in the background — hundreds of tiny dim points at random positions, just enough to give the dark field depth. Use `THREE.Points` with `PointsMaterial({ size: 0.02, color: '#303040', transparent: true, opacity: 0.3 })`
- **Add a very faint fog:** `<fog attach="fog" args={['#0a0a12', 15, 35]} />` in the Canvas. Far agents slightly dimmer than near ones → depth perception

### Problem 5: Agent nodes are too small and too uniformly sized

**Fix in `ui/src/canvas/agents.tsx`:**
- Increase base size: `const baseSize = 0.25 + agent.confidence * 0.25` (was `0.15 + agent.confidence * 0.15`)
- Different sizes for different tiers: core agents slightly smaller (0.2), domain agents larger (0.35), utility agents medium (0.25). This creates visual hierarchy

### Problem 6: The heartbeat pulse is barely visible

**Root cause:** The heartbeat sphere has max opacity of 0.15 and is using `BackSide` rendering. It's nearly invisible.

**Fix in `ui/src/canvas/animations.tsx`:**
- Increase heartbeat opacity: `mat.opacity = pulse * 0.35` (was `pulse * 0.15`)
- Add a second, smaller inner sphere with `FrontSide` that pulses more intensely: opacity `pulse * 0.5`
- Use `MeshBasicMaterial` with `toneMapped: false` so the pulse triggers bloom
- Increase heartbeat sphere radius: `args={[2.5, 16, 16]}` (was 1.5)

### Problem 7: No visual activity when idle — screen is static

**Fix:** Add a subtle ambient animation to make the canvas feel alive even when nothing is happening:
- **Floating particles:** tiny dim points that drift slowly upward in the background (think fireflies or dust in sunlight). 50-100 particles, very slow motion (0.01 units/frame), wrapping at top
- **Connection shimmer:** on each frame, very slightly vary the opacity of 2-3 random connections by ±5% — creates a sense of quiet activity in the mesh
- **Camera micro-drift:** add an extremely subtle auto-rotation or micro-sway to the camera orbit. `autoRotateSpeed: 0.05` (barely perceptible) — the scene breathes

### Problem 8: Status bar is functional but not atmospheric

**Fix in `ui/src/components/DecisionSurface.tsx`:**
- Use a translucent dark background with `backdrop-filter: blur(12px)` instead of solid dark
- Add a very subtle top-edge glow: `border-top: 1px solid rgba(240, 176, 96, 0.15)`
- Status values should use the trust spectrum colors: TC_N in blue, Health in amber when high / red when low, agent count in white
- Mode indicator: "active" in green, "dreaming" in amber-rose, "idle" in dim

---

## Implementation Order

Work through fixes 1-8 in order. After each fix, refresh the browser and verify visually:

1. **Connections** — can you see the mesh now? Curves between nodes?
2. **Bloom** — do agents glow? Is there a visible halo?
3. **Trust colors** — can you see color differentiation?
4. **Depth** — does the scene feel 3D? Can you see far vs near?
5. **Agent size** — are the nodes prominent enough?
6. **Heartbeat** — can you see the system's pulse?
7. **Ambient motion** — does the idle screen feel alive?
8. **Status bar** — does the bottom feel atmospheric, not a debug bar?

After all 8: take a screenshot. Compare to the HXI spec's description. If it still doesn't make you want to show it to someone, look at Three.js demos on [threejs.org/examples](https://threejs.org/examples/) for inspiration on bloom, particles, and atmospheric effects.

---

### Problem 9: Chat shows "(No response)" for conversational inputs

**Root cause:** The `IntentSurface.tsx` sends to `POST /api/chat` and reads the response, but conversational replies (like "hello") return `{"response": "Hello! I'm ProbOS..."}` with `dag: null`. The frontend may be looking for `dag` or `results` and showing "(No response)" when there's no DAG, even though the `response` field has text.

**Fix in `ui/src/components/IntentSurface.tsx`:**
- After calling `/api/chat`, check `data.response` first — if it has text, show it as the system's reply regardless of whether `dag` exists
- Only show "(No response)" if ALL fields are empty/null: no `response`, no `dag`, no `results`
- Display the `response` text in the chat history as a system message

**Also check:** Is the chat POST actually succeeding? Check browser console for 500 errors or CORS issues. If `probos serve` and the Vite dev server are on different ports, the CORS middleware in `api.py` must allow the Vite port (`localhost:5173`).

### Problem 10: No interactivity on agent nodes — clicking does nothing

**Root cause:** Agent nodes are instanced meshes. R3F instanced meshes don't support per-instance click events by default — you need raycasting with `instanceId` detection.

**Fix — add hover tooltips and click-to-inspect:**

**Option A (simpler — HTML tooltip overlay):**
- Add an `onPointerMove` handler to the `<Canvas>` that raycasts against the instanced mesh
- On hit: get the `instanceId`, look up the agent from the store, show a floating HTML tooltip near the cursor with:
  ```
  Agent: file_reader_filesystem_0_abc12345
  Pool: filesystem | Tier: core
  Trust: 0.78 (▲ high)
  Confidence: 0.85
  State: active
  ```
- Style: translucent dark panel with `backdrop-filter: blur(8px)`, warm border, trust-spectrum colored dot
- On no hit: hide tooltip
- On click: select the agent — keep the tooltip pinned, highlight the agent node brighter, dim others slightly

**Option B (R3F — use `@react-three/drei` `Html` component):**
- Use `Html` from drei to render a tooltip anchored to the 3D position of the hovered agent
- This is more Three.js-native but can be jankier with instanced meshes

**Recommend Option A** — an HTML div positioned via CSS, updated from the raycast hit. Simpler, smoother, works well with instancing.

**Implementation sketch for `CognitiveCanvas.tsx` or a new `AgentTooltip` component:**
```tsx
const [hovered, setHovered] = useState<Agent | null>(null);
const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

// In Canvas onPointerMove:
// raycast against instancedMesh → get instanceId → lookup agent → setHovered

// Render tooltip as HTML overlay (outside Canvas, positioned absolute):
{hovered && (
  <div style={{
    position: 'absolute', left: tooltipPos.x + 16, top: tooltipPos.y - 40,
    background: 'rgba(10, 10, 18, 0.85)', backdropFilter: 'blur(8px)',
    border: '1px solid rgba(240, 176, 96, 0.3)', borderRadius: 8,
    padding: '8px 12px', color: '#e0dcd4', fontSize: 13, pointerEvents: 'none',
    maxWidth: 280,
  }}>
    <div style={{ fontWeight: 600 }}>{hovered.agentType}</div>
    <div style={{ opacity: 0.7, fontSize: 11 }}>Pool: {hovered.pool} · {hovered.tier}</div>
    <div>Trust: {(hovered.trust * 100).toFixed(0)}% · Confidence: {(hovered.confidence * 100).toFixed(0)}%</div>
    <div style={{ opacity: 0.5, fontSize: 10 }}>{hovered.id}</div>
  </div>
)}
```

### Problem 11: No onboarding — new users don't know what they're looking at

**Fix — add a first-visit overlay and persistent legend:**

**A. Welcome overlay (first visit only):**
- Show a translucent centered card on first load (use `localStorage` to track `hxi_seen_intro`):
  ```
  Welcome to ProbOS
  
  You're looking at a living cognitive mesh — 47 AI agents 
  self-organizing to handle your requests.
  
  • Each glowing node is an autonomous agent
  • Connections show learned routing between intents and agents
  • Brighter = higher confidence | Warmer = higher trust
  • Ask it anything in the input box above
  
  Try: "What's the weather in Tokyo?" or "Translate hello to French"
  
  [Got it]
  ```
- Dismiss on click → set `localStorage.hxi_seen_intro = true`

**B. Persistent legend (toggle):**
- Small `(?)` button in the bottom-right corner
- Click toggles a compact legend overlay:
  ```
  🟠 High trust   🔵 Medium trust   🟣 Low trust
  Brighter = more confident   Larger = more active
  ◐ Pulsing = heartbeat   ✦ Flash = consensus
  ```
- Style: same translucent dark panel as the tooltip

**C. Status bar enhancement:**
- Change "connected" dot to a meaningful label: "● Live — 47 agents" 
- Add tooltips to status bar metrics: hover TC_N shows "Total Correlation — how much agents cooperate"
- Change "H(r)" to "Routing Entropy" (H(r) means nothing to newcomers)

---

## Do NOT Change

- No Python code changes (except if needed to fix the /api/chat response issue — check frontend first)
- No Zustand store schema changes (can add `hoveredAgent` and `showIntro` state)
- No WebSocket protocol changes
- New React components are OK for tooltip and onboarding overlay (these are UI additions, not architecture)
- No new npm dependencies
- No changes to the event schema
- No test changes

This is visual craft + UX work in the existing rendering layer.
