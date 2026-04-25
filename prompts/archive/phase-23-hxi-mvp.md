# Phase 23 — HXI MVP: The Living Canvas

## Context

You are building Phase 23 of ProbOS, a probabilistic agent-native OS runtime. Read `PROGRESS.md` for full architectural context. Read `Vibes/hxi-architecture-v2.md` for the full HXI design spec. Current state: **1520/1520 tests passing + 11 skipped. Latest AD: AD-253.**

Phase 22 shipped distribution (`pip install probos`, `probos init`, `probos serve`) and a FastAPI server with `/api/chat`, `/api/status`, `/api/health`, and WebSocket `/ws/events`. The WebSocket already broadcasts DAG execution events. The infrastructure for the HXI is in place — what's missing is the frontend.

This phase builds **HXI Phase 1 from the spec**: the Living Canvas. A browser-based visualization of ProbOS's cognitive mesh that makes the system's dynamics visible and beautiful. This is the product differentiator — the screenshot/GIF that makes people want to install ProbOS.

### What makes this phase different

Previous phases were pure Python. This phase is **two tracks**:
- **Track A (Python):** Enrich the WebSocket event stream with typed events for all system dynamics (agent lifecycle, trust, Hebbian, consensus, gossip, intent flow, self-mod, dream cycles)
- **Track B (TypeScript/React/Three.js):** Build the HXI frontend — Cognitive Canvas + React overlays + chat input

The frontend lives in a new `ui/` directory at the project root (separate from `src/probos/`). It's a standalone React app that connects to `probos serve` via WebSocket.

---

## Pre-Build Audit

Before writing any code, verify:

1. **Latest AD number in PROGRESS.md** — confirm AD-253 is the latest. Phase 23 AD numbers start at **AD-254**. If AD-253 is NOT the latest, adjust upward.
2. **Test count** — confirm 1520 tests pass: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
3. **Read these files thoroughly:**
   - `Vibes/hxi-architecture-v2.md` — the full HXI design spec. Phase 1 scope is in the "Phased Roadmap" section
   - `src/probos/api.py` — existing FastAPI app with `/api/chat`, `/api/status`, `/ws/events`. The HXI frontend connects here
   - `src/probos/runtime.py` — understand `status()`, `process_natural_language()`, the `on_event` callback pattern, `_emergent_detector`, `_semantic_layer`, `dream_scheduler`
   - `src/probos/types.py` — understand all dataclass types that will be serialized as events
   - `src/probos/__main__.py` — understand `probos serve` — the HXI will be served as static files from this server

---

## What To Build

### Track A: Enriched Event Stream (AD-254)

**File:** `src/probos/api.py` (extend), `src/probos/runtime.py` (extend)

**AD-254: Typed event emission for all HXI-relevant system dynamics.**

The existing `/ws/events` WebSocket broadcasts DAG execution events (`node_start`, `node_complete`, etc.) via the `on_event` callback. The HXI needs richer events covering all system dynamics. Add event emission at these points:

#### Event types to add:

**1. Full state snapshot on connect:**
When a WebSocket client connects, immediately send a `state_snapshot` event containing the complete current state — all agents with their trust/confidence/pool/tier, all Hebbian weights, system mode, dream status, active DAGs. This bootstraps the HXI canvas without needing to wait for activity.

```python
# On WebSocket connect, after accept:
snapshot = _build_state_snapshot(runtime)
await websocket.send_json({"type": "state_snapshot", "data": snapshot, "timestamp": time.time()})
```

The snapshot includes:
```python
{
    "agents": [{"id", "agent_type", "pool", "state", "confidence", "trust", "tier"}, ...],
    "connections": [{"source", "target", "rel_type", "weight"}, ...],
    "pools": [{"name", "agent_type", "size", "target_size"}, ...],
    "system_mode": "active" | "idle" | "dreaming",
    "tc_n": float,
    "routing_entropy": float,
}
```

**2. Agent lifecycle events:**
Emit when agents spawn, go active, degrade, or recycle. Wire into `ResourcePool` or `_wire_agent()`.

```json
{"type": "agent_state", "data": {"agent_id": "...", "pool": "...", "state": "active", "confidence": 0.8, "trust": 0.5}}
```

**3. Trust update events:**
Emit from `TrustNetwork.record_outcome()` (wrap or hook).

```json
{"type": "trust_update", "data": {"agent_id": "...", "old_score": 0.5, "new_score": 0.55, "success": true}}
```

**4. Hebbian weight events:**
Emit from `HebbianRouter.record_interaction()`.

```json
{"type": "hebbian_update", "data": {"source": "...", "target": "...", "old_weight": 0.1, "new_weight": 0.15, "rel_type": "intent"}}
```

**5. System mode events:**
Emit when the system transitions between active/idle/dreaming.

```json
{"type": "system_mode", "data": {"mode": "dreaming", "previous": "idle"}}
```

**6. Self-mod events:**
Already emitted by the renderer (`self_mod_design`, `self_mod_success`, `self_mod_failure`). Ensure they broadcast to WebSocket.

**7. Consensus events:**
Emit during quorum evaluation with vote details.

```json
{"type": "consensus", "data": {"intent": "write_file", "outcome": "approved", "votes": [...], "shapley": {...}}}
```

**Implementation approach:** Create a `_ws_broadcast()` helper in `api.py` that the runtime can call. The runtime gets a reference to this function (passed during `create_app()` or via a global). Events are fire-and-forget — if no WebSocket clients are connected, events are dropped silently.

**Alternative approach (preferred):** Add an `event_listeners` list on the runtime. The API server registers a listener that broadcasts to WebSocket clients. This avoids coupling the runtime to the API module.

```python
# In runtime.py
self._event_listeners: list[Callable] = []

def add_event_listener(self, fn: Callable) -> None:
    self._event_listeners.append(fn)

def _emit_event(self, event_type: str, data: dict) -> None:
    for fn in self._event_listeners:
        try:
            fn({"type": event_type, "data": data, "timestamp": time.time()})
        except Exception:
            pass
```

Then call `self._emit_event("trust_update", {...})` at each instrumentation point. The API server does `runtime.add_event_listener(_broadcast_event)`.

**Run tests: all 1520 must still pass. Event emission is additive — no behavior changes.**

---

### Track B: HXI Frontend (AD-255 through AD-259)

**Directory:** `ui/` at project root

This is a standalone React + TypeScript + Three.js application.

#### AD-255: Project scaffold and data pipeline

**Setup:**
```
ui/
  package.json
  tsconfig.json
  vite.config.ts
  index.html
  src/
    main.tsx              # Entry point
    App.tsx               # Root component
    store/
      useStore.ts         # Zustand reactive state store
      types.ts            # TypeScript types matching Python event schema
    hooks/
      useWebSocket.ts     # WebSocket connection + event handling
    components/
      CognitiveCanvas.tsx # Three.js WebGL canvas wrapper
      IntentSurface.tsx   # Chat input + DAG visualization (React overlay)
      DecisionSurface.tsx # Results + feedback (React overlay)
    canvas/
      scene.ts            # Three.js scene setup
      agents.ts           # Agent node rendering (instanced spheres)
      connections.ts      # Hebbian connection curves
      effects.ts          # Bloom, color grading post-processing
      animations.ts       # Heartbeat, spawning, consensus, dream motions
```

**Dependencies:** `react`, `react-dom`, `three`, `@react-three/fiber`, `@react-three/drei`, `@react-three/postprocessing`, `zustand`, `vite`

**Zustand store (`useStore.ts`):**
```typescript
interface Agent {
  id: string;
  agentType: string;
  pool: string;
  state: 'spawning' | 'active' | 'degraded' | 'recycling';
  confidence: number;
  trust: number;
  tier: 'core' | 'utility' | 'domain';
  position: [number, number, number]; // computed by layout
}

interface Connection {
  source: string;
  target: string;
  relType: string;
  weight: number;
}

interface HXIState {
  agents: Map<string, Agent>;
  connections: Connection[];
  systemMode: 'active' | 'idle' | 'dreaming';
  activeDag: DagNode[] | null;
  chatHistory: ChatMessage[];
  tcN: number;
  routingEntropy: number;
  // ... actions
  handleEvent: (event: WSEvent) => void;
  sendMessage: (text: string) => void;
}
```

The store is the *single source of truth*. Both the Three.js canvas and the React overlays subscribe to it. Updated exclusively from WebSocket events.

**WebSocket hook (`useWebSocket.ts`):**
- Connects to `ws://localhost:18900/ws/events` on mount
- Receives `state_snapshot` on connect → populates full store
- Receives incremental events → updates store
- Reconnects on disconnect with exponential backoff
- Sends chat messages via `fetch('/api/chat', ...)` (REST, not WebSocket)

#### AD-256: Cognitive Canvas — Agent Topology

**Files:** `ui/src/canvas/scene.ts`, `ui/src/canvas/agents.ts`, `ui/src/canvas/connections.ts`, `ui/src/components/CognitiveCanvas.tsx`

The core visual experience. A dark-field WebGL canvas with luminous agent nodes and flowing connection curves.

**Agent nodes:**
- Instanced spheres (one draw call for all agents) with per-instance: color (trust spectrum), size (scaled by confidence), glow intensity (confidence bloom)
- Trust color mapping from the spec: high trust = warm amber `#f0b060`, medium = blue-white `#88a4c8`, low = cool violet `#7060a8`, new = silver `#a0a8b8`
- Grouped by pool using force-directed layout. Core tier agents at the bottom (substrate), utility in the middle, domain at the top
- Breathing animation: ±3% radius oscillation, offset per agent (not synchronized)
- Pool hue tints as defined in the spec

**Connection curves:**
- Bezier curves between connected agent nodes (source/target from Hebbian weights)
- Thickness and opacity proportional to weight
- Animated flow: subtle particle flow along the curve direction (source → target)
- Strengthening pulse: warm white flash along the curve when weight increases
- Decay: gradual thinning and fading

**Camera:**
- Orbit controls (rotate, zoom, pan)
- Default position: looking slightly down at the agent field
- Auto-frame: camera adjusts to keep all agents visible

**Post-processing:**
- Bloom pass (UnrealBloomPass): makes luminous elements glow
- Color grading: shifts based on system mode (neutral for active, warm for dreaming)

**Background:**
- Dark field: `#0a0a12` base
- Subtle radial gradient centered on active region

#### AD-257: Intent Surface — Chat + DAG

**File:** `ui/src/components/IntentSurface.tsx`

React overlay floating above the canvas. Translucent with backdrop blur.

**Components:**
- **Chat input:** Full-width text field at the top. Enter to send. Calls `POST /api/chat` via fetch. Response appears in Decision Surface. During processing, a subtle glow animates in the canvas (processing indicator)
- **Chat history:** Scrollable message list above the input. User messages on the right (warm tint), system responses on the left (cool tint). Keeps last 50 messages
- **Active DAG display:** When a DAG is executing, render nodes as small rounded rectangles in a horizontal flow. Status colors: pending=dim, active=bright, completed=green check, failed=red. Dependencies shown as thin lines between nodes

This is *not* the full collaboration model from the HXI spec (guided decomposition, node pause, injection). MVP only: chat input + message history + DAG status display.

#### AD-258: Decision Surface — Results + Feedback

**File:** `ui/src/components/DecisionSurface.tsx`

React overlay at the bottom. Rises from bottom when results arrive.

**Components:**
- **Result display:** Shows the LLM's response/reflection as formatted text. Scrollable
- **Feedback strip:** Three buttons — Approve (👍), Correct (✏️), Reject (👎). Calls existing `/api/chat` with feedback commands (same as `/feedback good`, `/feedback bad`, `/correct`)
- **System status bar:** Agent count, health, system mode, TC_N — compact one-liner at the very bottom

MVP only: result display + simple feedback. Not the full escalation queue or annotation system from the spec.

#### AD-259: Visual Polish — Animations + Atmosphere

**Files:** `ui/src/canvas/effects.ts`, `ui/src/canvas/animations.ts`

The craft that makes it worth sharing.

**Animations:**
- **Heartbeat pulse:** Heartbeat agent nodes pulse at ~1.2s intervals. Subtle radial light pulse illuminates nearby connections
- **Consensus flash:** When a consensus event arrives, participating agents briefly flash golden, connections between them brighten, a convergence point flares
- **Self-mod bloom:** When a self-mod event arrives, a new agent node materializes with a rapid bloom animation. Bright spawn flare that settles. The "wow" moment
- **Dream mode transition:** When system mode = "dreaming", the entire scene shifts: warm amber-rose color grading, slower animations, increased bloom, softer edges. Ghost traces of replayed pathways. The screen becomes meditative
- **Intent routing pulse:** When a DAG node starts executing, a luminous pulse traces from the intent to the handling agent along the Hebbian connection

**Atmosphere:**
- System healthy idle: warm ambient glow, slow heartbeat, occasional shimmer
- Active processing: brighter around active agents, routing pulses visible
- Dreaming: full warm shift, diffuse light, pathway replay ghosts

---

### Track C: Serve Integration (AD-260)

**File:** `src/probos/__main__.py`, `src/probos/api.py`

**AD-260: `probos serve` serves the HXI frontend.**

1. **Build step:** `ui/` has a Vite build that produces `ui/dist/`. Add an npm script: `npm run build` → outputs to `ui/dist/`
2. **Static file serving:** In `api.py`, mount `ui/dist/` as static files:
   ```python
   from fastapi.staticfiles import StaticFiles
   app.mount("/", StaticFiles(directory="ui/dist", html=True), name="hxi")
   ```
3. **`probos serve` opens browser:** After starting the server, open `http://localhost:18900` in the default browser using `webbrowser.open()`
4. **Fallback:** If `ui/dist/` doesn't exist (not built), serve a simple HTML page saying "HXI not built. Run `cd ui && npm install && npm run build`"

**CORS:** Add CORS middleware to the FastAPI app for development (localhost origins).

---

### Track D: Python Tests (AD-261)

**File:** `tests/test_hxi_events.py` (new)

**AD-261: Tests for the enriched event stream.** The frontend is tested via manual inspection (it's visual). The Python event infrastructure is testable:

#### Event emission tests (12 tests)
- `state_snapshot` sent on WebSocket connect (1 test)
- `state_snapshot` contains agents, connections, pools, system_mode (1 test)
- `trust_update` event emitted on `record_outcome()` (1 test)
- `hebbian_update` event emitted on `record_interaction()` (1 test)
- `system_mode` event emitted on dream cycle start/end (1 test)
- `consensus` event emitted during quorum evaluation (1 test)
- `agent_state` event emitted on agent state change (1 test)
- Event listener registration and removal (1 test)
- Event emission when no listeners doesn't crash (1 test)
- Event emission with failing listener doesn't crash other listeners (1 test)
- `_build_state_snapshot()` returns valid JSON-serializable dict (1 test)
- Event timestamps are monotonically increasing (1 test)

**Total: ~12 Python tests → ~1532 total**

---

## What NOT To Build

- **No full collaboration model** — MVP is chat input + message history + DAG display. No guided decomposition, node pause, step injection, or annotation. These are HXI Phase 2-3
- **No dream mode pathway replay** — just the color grading shift. Ghost traces are HXI Phase 2
- **No gossip wave visualization** — HXI Phase 2
- **No governance panel** — HXI Phase 3
- **No federation visualization** — HXI Phase 4
- **No temporal navigation** — HXI Phase 5
- **No participant profile or expertise calibration** — HXI Phase 2
- **No bias mitigation** — HXI Phase 5
- **No clarification requests** — HXI Phase 2
- **No mobile responsiveness** — desktop-first MVP
- **No authentication** — localhost only
- **No SSR or SEO** — it's a SPA connecting to a local server
- **No changes to core ProbOS runtime behavior** — only event emission additions

---

## QA Discipline

### Python side
- Test gate after Track A: all 1520 existing tests must pass
- 12 new event emission tests
- No changes to runtime behavior — only additive event listeners

### Frontend side
- The frontend is visual — tested via manual inspection, not unit tests
- **Manual test checklist:**
  - [ ] `probos serve` opens browser to HXI
  - [ ] Agent nodes visible in canvas with correct colors (trust spectrum)
  - [ ] Connections visible between agents with weight-based thickness
  - [ ] Chat input works — type message, press Enter, see result
  - [ ] DAG progress visible during execution (nodes lighting up)
  - [ ] Self-mod creates visible new agent node with bloom animation
  - [ ] Dream mode color shift when idle (if dreaming triggers)
  - [ ] Consensus flash animation on write/command operations
  - [ ] Heartbeat pulse visible on heartbeat agent nodes
  - [ ] Zoom/pan/rotate works on canvas

---

## Implementation Order

1. **AD-254: Event stream enrichment** (Python — `api.py` + `runtime.py`) → run Python tests
2. **AD-255: Frontend scaffold** (TypeScript — `ui/` setup, Zustand store, WebSocket hook)
3. **AD-256: Cognitive Canvas** (Three.js — agent nodes, connections, post-processing)
4. **AD-257: Intent Surface** (React — chat input, message history, DAG display)
5. **AD-258: Decision Surface** (React — results, feedback buttons, status bar)
6. **AD-259: Visual polish** (Three.js — animations, atmosphere, dream mode)
7. **AD-260: Serve integration** (Python — static files, `probos serve` opens browser)
8. **AD-261: Python tests** → run tests, verify all pass
9. **Manual testing** — run through the visual checklist

**After Track A (AD-254), run Python tests. After AD-261, run Python tests again.**
**Frontend testing is visual — use the manual checklist.**

---

## PROGRESS.md Update

After all tests pass and visual checklist confirmed:

1. **Line 2** — Update status line: `Phase 23 — HXI MVP: The Living Canvas (XXXX/XXXX tests + 11 skipped)`
2. **What's Been Built section** — Add HXI section with event bridge + frontend description
3. **Architectural Decisions** — Add AD-254 through AD-261
4. **Active Roadmap** — Mark Phase 23 complete (with note: "HXI Phase 1 — Living Canvas"), set current phase to 24

**AD numbering: Current highest is AD-253. This phase uses AD-254 through AD-261. Verify before committing.**
