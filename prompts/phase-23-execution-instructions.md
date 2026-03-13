# Phase 23 — Execution Instructions

## How To Use This Document

1. Read `prompts/phase-23-hxi-mvp.md` first (the full spec)
2. Read `Vibes/hxi-architecture-v2.md` for the full HXI design vision (Phase 23 implements Phase 1 of that spec)
3. This document repeats highest-risk constraints and provides execution guidance
4. This phase has TWO tracks: Python (event stream) and TypeScript (frontend)

## Critical Constraints (stated redundantly)

### AD Numbering — HARD RULE
- **Current highest: AD-253** (Phase 22)
- Phase 23 uses: AD-254, AD-255, AD-256, AD-257, AD-258, AD-259, AD-260, AD-261
- VERIFY by reading PROGRESS.md before assigning any AD number

### Python Test Gate — HARD RULE
- Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` after Track A (AD-254) and after AD-261
- All 1520 existing tests must continue passing
- ~12 new Python tests → ~1532 total

### Scope — DO NOT BUILD
- No full collaboration model (guided decomposition, node pause, step injection, annotation — HXI Phase 2-3)
- No dream pathway replay ghost traces (HXI Phase 2) — only color grading shift
- No gossip wave visualization (HXI Phase 2)
- No governance panel (HXI Phase 3)
- No federation visualization (HXI Phase 4)
- No temporal navigation (HXI Phase 5)
- No mobile responsiveness
- No authentication
- No changes to ProbOS runtime behavior — only additive event listeners
- No Python–TypeScript coupling beyond the WebSocket protocol

### Visual Design — FOLLOW THE SPEC
- Read `Vibes/hxi-architecture-v2.md` "Visual Design Specification" section
- Dark field background (`#0a0a12` to `#0f0e18`)
- Trust spectrum colors: warm amber (high) → blue-white (medium) → cool violet (low)  
- Confidence → luminosity (brightness = vitality)
- Bloom post-processing (not flat CSS glow)
- Organic easing on all animations (no linear, no CSS ease-in-out)
- **If it looks like a Grafana panel, start over**

### Architecture — FACADE PRINCIPLE
- The HXI has NO independent state beyond the reactive Zustand store
- The Zustand store is updated EXCLUSIVELY from WebSocket events
- No synthetic dynamics. No client-side simulation. If ProbOS isn't doing it, the HXI doesn't show it
- If WebSocket disconnects, HXI freezes. Reconnect and state catches up via `state_snapshot`

## Execution Sequence

### Track A: Python (do first)

**Step 1: AD-254 — Enriched event stream**
- Edit `src/probos/runtime.py` — add `_event_listeners` list, `add_event_listener()`, `_emit_event()`
- Instrument: `TrustNetwork.record_outcome()` → trust_update, `HebbianRouter.record_interaction()` → hebbian_update, agent state changes → agent_state, dream start/end → system_mode, consensus → consensus
- Edit `src/probos/api.py` — register event listener on app startup, send `state_snapshot` on WebSocket connect, add `_build_state_snapshot()` helper
- Run Python tests → 1520 must pass

### Track B: TypeScript (after Track A)

**Step 2: AD-255 — Scaffold**
- Create `ui/` directory with package.json, tsconfig.json, vite.config.ts, index.html
- Install deps: react, react-dom, three, @react-three/fiber, @react-three/drei, @react-three/postprocessing, zustand, vite
- Create Zustand store with TypeScript types matching Python event schema
- Create WebSocket hook with reconnection logic
- Verify: `cd ui && npm install && npm run dev` opens in browser (empty page connecting to WS)

**Step 3: AD-256 — Cognitive Canvas**
- Three.js scene with dark field background
- Agent nodes as instanced meshes with trust-spectrum colors and confidence-luminosity
- Force-directed layout grouping by pool
- Hebbian connection curves (bezier) with weight-based thickness
- Post-processing: UnrealBloomPass for glow, color grading for system mode
- Verify: canvas shows agent topology with glowing nodes and connections

**Step 4: AD-257 — Intent Surface**
- React overlay floating above canvas (translucent, backdrop-blur)
- Chat input field: type + Enter → POST /api/chat → response in Decision Surface
- Chat history: last 50 messages, user on right, system on left
- Active DAG: horizontal node flow with status colors during execution
- Verify: can chat through the HXI, see DAG progress

**Step 5: AD-258 — Decision Surface**
- React overlay at bottom, rises when results arrive
- Result text display (scrollable)
- Feedback buttons: Approve, Correct, Reject (call /api/chat with feedback commands)
- System status bar: agent count, health, mode, TC_N
- Verify: results appear after chat, feedback buttons work

**Step 6: AD-259 — Visual polish**
- Heartbeat pulse animation on heartbeat agents (~1.2s interval)
- Consensus golden flash on quorum events
- Self-mod bloom: new agent node materializes with rapid bloom + flare
- Dream mode: warm color grade shift when system_mode = "dreaming"
- Intent routing pulse: luminous trace from intent to handling agent
- Breathing animation on all agents (±3% radius, offset phases)
- Verify: animations fire on real ProbOS events, dream mode looks meditative

**Step 7: AD-260 — Serve integration**
- `npm run build` produces `ui/dist/`
- `api.py` mounts `ui/dist/` as static files at root
- `probos serve` auto-opens browser to localhost:18900
- CORS middleware for dev
- Verify: `probos serve` opens HXI in browser, full functionality

### Track C: Tests

**Step 8: AD-261 — Python event tests**
- Create `tests/test_hxi_events.py` — 12 tests for event emission
- Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` → ~1532 pass

### Step 9: PROGRESS.md update

## Highest-Risk Items

1. **Three.js + React integration.** `@react-three/fiber` bridges React and Three.js but has specific patterns. Don't mix imperative Three.js code with R3F's declarative approach — pick one. R3F is recommended for consistency with React.

2. **WebSocket reconnection.** The HXI must handle WebSocket disconnects gracefully (server restart, network blip). On reconnect, request a fresh `state_snapshot` to rebuild state. Use exponential backoff (1s, 2s, 4s, max 30s).

3. **Force-directed layout performance.** With ~45 agents, a basic force simulation is fine. Use `d3-force-3d` or a simple spring-force implementation. Don't over-optimize — 45 nodes is trivial. But DO memoize positions — layout shouldn't reset on every state update.

4. **Event volume.** During active processing, many events fire simultaneously (trust updates, Hebbian updates, agent states). The Zustand store should batch updates to avoid excessive re-renders. Use `zustand`'s `setState` merging.

5. **Build artifact size.** Three.js is large (~600KB gzipped). The HXI is a local tool, not a production website — bundle size is not a critical concern. Don't spend time on code splitting for MVP.

6. **`probos serve` must work without `ui/dist/`.** If the frontend hasn't been built (user cloned repo but didn't run `npm run build`), the API still works. The HXI route returns a helpful message, not a 500 error.

## Manual Testing Checklist

After all code is written and Python tests pass:

- [ ] `probos serve` starts and opens browser to HXI
- [ ] Agent nodes visible as glowing spheres in dark field
- [ ] Trust colors correct: warm = high trust, cool = low trust
- [ ] Connections visible between agents, thickness varies by weight
- [ ] Chat input works: type "hello", Enter, see response
- [ ] Chat input works: type "read the file at /tmp/test.txt", see DAG execute
- [ ] DAG progress shows nodes lighting up during execution
- [ ] Self-mod test: type "translate hello to japanese" (if no translate agent), see new node bloom into canvas
- [ ] Consensus flash: type "write hello to /tmp/out.txt", see golden flash
- [ ] Heartbeat pulse: heartbeat agent nodes pulse rhythmically
- [ ] Bloom post-processing: luminous glow, not flat circles
- [ ] Breathing: agent nodes subtly oscillate in size
- [ ] System status bar shows agent count, health, mode
- [ ] Zoom/pan/rotate with mouse works on canvas
- [ ] Chat history scrollable, user messages on right, system on left

## Key Design Decisions Summary

| AD | What |
|----|------|
| AD-254 | Python event enrichment: `_event_listeners` on runtime, `_emit_event()`, `state_snapshot` on WS connect, trust/Hebbian/agent/mode/consensus events |
| AD-255 | Frontend scaffold: Vite + React + Three.js + Zustand + TypeScript. WebSocket hook with reconnection. Typed store matching Python event schema |
| AD-256 | Cognitive Canvas: dark-field WebGL, instanced agent spheres, trust-spectrum colors, confidence-luminosity, Hebbian bezier curves, bloom post-processing |
| AD-257 | Intent Surface: translucent React overlay, chat input → /api/chat, message history, active DAG horizontal flow |
| AD-258 | Decision Surface: result display, feedback buttons (approve/correct/reject), system status bar |
| AD-259 | Visual polish: heartbeat pulse, consensus flash, self-mod bloom, dream mode color grade, intent routing trace, breathing animation |
| AD-260 | Serve integration: Vite build → ui/dist/, FastAPI static mount, auto-open browser, CORS, graceful fallback without build |
| AD-261 | 12 Python tests for event emission: snapshot, trust, Hebbian, mode, consensus, agent state, listener lifecycle |
