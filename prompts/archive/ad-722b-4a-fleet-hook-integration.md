# AD-722b-4a — Integrate `useFleetAvatarTelemetry` hook into HXI

**Wave:** 161
**Closes:** #655
**Status:** ready to build
**Dependencies:** AD-722b-4 (Wave 160 — fleet endpoint + hook stub shipped at `ui/src/avatars/useFleetAvatarTelemetry.ts`).
**Estimated tests:** +4 vitest, 0 pytest.
**Scope tag:** UI-only. Pure internal change. No new pip/npm deps. Apache 2.0.

---

## Problem

Wave 160 shipped two pieces of fleet telemetry plumbing:

1. Server: `GET WS /api/agent/avatar-telemetry/stream` (single fan-out connection for all agents, every frame carries `agent_id`).
2. Client: `ui/src/avatars/useFleetAvatarTelemetry.ts` (React hook that opens the WS and dispatches frames via `onFrame` callback).

But **no component imports the hook**. Vite tree-shook the hook out of the production bundle (`ui/dist/assets/index-BDgoocuQ.js` hash unchanged across the Wave 160 deploy). The endpoint is reachable; the hook compiles; the data path simply isn't wired.

This AD wires the hook into `CognitiveCanvas.tsx` so fleet telemetry frames merge into the zustand store, where `AgentNodes` / `Connections` / `Effects` can read them via existing selectors.

---

## Solution overview

1. Add an `avatarTelemetry: Map<string, AvatarTelemetry>` field + a `setAvatarTelemetryFrame(agent_id, type, payload)` action to `ui/src/store/useStore.ts`.
2. In `CognitiveCanvas.tsx`, call `useFleetAvatarTelemetry({ onFrame: ... })` once at the top of the component. The callback merges snapshot/diff frames into the store via the new action.
3. Frame contract:
   - `type === "snapshot"`: replace the per-agent entry entirely.
   - `type === "diff"`: shallow-merge `changed` into the existing entry; drop the frame if there's no prior snapshot for that agent.
   - `type === "ping"`: no-op (keep-alive).
   - `type === "error"`: log to console once per agent_id, no store write.
4. Hook is **enabled by default** when the canvas mounts. Unmount closes the WS (handled by hook's existing cleanup).
5. Do NOT replace the per-agent `SelfImageTab` WS — that endpoint stays. This AD only ADDS the fleet path; the per-agent path keeps working for the profile view's dense diff stream.

### What this does NOT change

- The fleet endpoint contract (Wave 160 / AD-722b-4 is frozen).
- The per-agent WS at `/api/agent/{id}/avatar-telemetry-stream` and its consumer in `SelfImageTab.tsx`.
- `AgentNodes` / `Connections` / `Effects` rendering logic. They MAY read from `avatarTelemetry` going forward, but adding consumers is out of scope here — this AD is wiring only.
- Per-agent telemetry stores. Forward marker AD-722b-4b (filed in roadmap) covers migrating per-agent store consumers to read from the unified map.

---

## Section 1 — Store additions (`ui/src/store/useStore.ts`)

Add the field + action. Frame `payload` shape matches the existing `AvatarTelemetry` interface in `ui/src/components/profile/SelfImageTab.tsx` (snapshot is a flat dict; diff `changed` is a partial of the same shape).

Add to the store state:

```ts
// AD-722b-4a: fleet-level avatar telemetry, keyed by agent_id.
// Populated by the WS at /api/agent/avatar-telemetry/stream via
// useFleetAvatarTelemetry. Per-agent SelfImageTab WS remains the
// canonical source for the profile view; this map is for canvas-wide
// consumers (AgentNodes / Connections) that need every agent's frame.
avatarTelemetry: Map<string, Record<string, unknown>>;
setAvatarTelemetryFrame: (
  agent_id: string,
  type: "snapshot" | "diff" | "ping" | "error",
  payload: Record<string, unknown>,
) => void;
```

Action body:

```ts
setAvatarTelemetryFrame: (agent_id, type, payload) => {
  if (type === "ping") return;
  if (type === "error") {
    // Log once per agent_id per session (best-effort; no dedup state needed —
    // the server should not be sending error frames in steady state).
    if (typeof console !== "undefined") {
      console.warn("avatar-telemetry error frame for", agent_id, payload);
    }
    return;
  }
  set((state) => {
    const next = new Map(state.avatarTelemetry);
    if (type === "snapshot") {
      next.set(agent_id, payload);
    } else {
      // diff
      const prev = next.get(agent_id);
      if (prev === undefined) {
        // No prior snapshot — drop the diff. The server's full_snapshot_every_n
        // cadence guarantees a snapshot within N ticks; until then we have
        // nothing to merge into.
        return state;
      }
      next.set(agent_id, { ...prev, ...payload });
    }
    return { avatarTelemetry: next };
  });
},
```

Initialize `avatarTelemetry: new Map()` in the store's initial state.

---

## Section 2 — Canvas integration (`ui/src/components/CognitiveCanvas.tsx`)

Locate the top of `CognitiveCanvas()` (after `const grading = modeGrading(systemMode);`, before the `return`):

```tsx
export function CognitiveCanvas() {
  const systemMode = useStore((s) => s.systemMode);
  const connected = useStore((s) => s.connected);
  const grading = modeGrading(systemMode);

  return (
```

Insert the hook call:

```tsx
export function CognitiveCanvas() {
  const systemMode = useStore((s) => s.systemMode);
  const connected = useStore((s) => s.connected);
  const grading = modeGrading(systemMode);

  // AD-722b-4a: open the fleet telemetry WS for as long as the canvas
  // is mounted. Frames merge into useStore.avatarTelemetry; canvas
  // children read via selectors (forward markers cover specific consumers).
  const setAvatarTelemetryFrame = useStore((s) => s.setAvatarTelemetryFrame);
  useFleetAvatarTelemetry({
    onFrame: (frame) => {
      setAvatarTelemetryFrame(frame.agent_id, frame.type, frame.payload);
    },
  });

  return (
```

Add the import alongside the existing imports:

```tsx
import { useFleetAvatarTelemetry } from '../avatars/useFleetAvatarTelemetry';
```

---

## Section 3 — Tests

### `ui/src/__tests__/useStore.avatarTelemetry.test.ts` (new file, +3 vitest)

Tests against the store action directly — no React rendering needed.

1. **snapshot replaces entry** — call `setAvatarTelemetryFrame("a1", "snapshot", { emotion: "calm" })`, verify `state.avatarTelemetry.get("a1")` returns the payload; call again with different payload, verify replacement.
2. **diff before snapshot is dropped** — call `setAvatarTelemetryFrame("a2", "diff", { working_state: "thinking" })` with no prior snapshot; verify `avatarTelemetry.get("a2")` is `undefined`.
3. **diff after snapshot shallow-merges** — snapshot `{ emotion: "calm", working_state: "idle" }`, then diff `{ working_state: "thinking" }`; verify result is `{ emotion: "calm", working_state: "thinking" }`.

### `ui/src/__tests__/CognitiveCanvas.fleetHook.test.tsx` (new file, +1 vitest)

Tests the integration shape — verifies `useFleetAvatarTelemetry` is invoked when `CognitiveCanvas` mounts, by mocking the hook module and asserting the mock was called with an `onFrame` callback.

Use vitest's `vi.mock("../avatars/useFleetAvatarTelemetry", ...)` to capture the call. Render `<CognitiveCanvas />` (wrap with whatever zustand provider pattern the existing canvas tests use; check `ui/src/__tests__/` for the established pattern). Assert the mock was called exactly once with an object whose `onFrame` is a function.

**Do not** assert WebSocket behavior — `useFleetAvatarTelemetry.test.ts` from Wave 160 already covers that surface. This test is integration-shape only.

---

## Standing rules (must comply)

- **BF-274** — When editing `CognitiveCanvas.tsx`, use a **single** `replace_string_in_file` call for the hook-insertion block (the import + the call site). `multi_replace_string_in_file` with adjacent edits has shipped two pre-AD-731 image-code restores; canvas regressions cost hours.
- **BF-280** — N/A (UI-only AD; no Python subprocess calls).
- **BF-282** — N/A (no subprocess binary output).
- **BF-286** — N/A (no subprocess test scaffolding).
- **AD-738b / per-wave UI gate** — every commit that touches `ui/src/**` runs BOTH:
  - `cd ui ; npx vitest run`
  - `cd ui ; npm run build`
  - If `npm run build` fails (TS error, JSX.Element resolution under React 19 bundler-mode, missing import resolution), STOP and surface. Vitest greens are not sufficient.
- **HXI Canvas regression class** — after the change, manually verify (or have the operator verify) that:
  - Tooltips still appear on hover (`AgentRaycastLayer` setHoveredAgent path).
  - Bloom position on agent nodes is unchanged (`SelfModBloom` reads agent positions, not telemetry).
  - Raycasting still resolves instanceId → agent profile open on click.
  - If ANY of these regress, STOP — HXI Canvas regression is a known hard-stop class.
- **No emoji** — none of this code emits user-facing strings; if console messages are added, ASCII only.
- **AD-731 invariant** — N/A; this AD touches no attachment paths.
- **AD-722c-3 forward-marker style** — any forward markers filed below MUST use technical triggers, not commercial-tier language.

---

## Forward markers (file in `docs/development/roadmap.md`)

- **AD-722b-4b** — Migrate `SelfImageTab.tsx` per-agent WS consumer to read from `useStore.avatarTelemetry`, eliminating the second WebSocket. **Trigger:** `avatarTelemetry` map reaches 2+ canvas consumers AND fleet endpoint snapshot+diff parity with per-agent endpoint is verified by integration test.
- **AD-722b-4c** — Add canvas-side selectors (`useAgentEmotion(agent_id)`, `useAgentWorkingState(agent_id)`) so `AgentNodes` / `Connections` can render telemetry without subscribing to the full map. **Trigger:** more than one canvas component reads `avatarTelemetry` directly (re-render cost becomes measurable).

---

## Acceptance criteria

1. `useFleetAvatarTelemetry` is imported and invoked exactly once in `CognitiveCanvas.tsx`.
2. `useStore.avatarTelemetry` is initialized as `new Map()`.
3. `setAvatarTelemetryFrame` handles all four frame types per Section 2.
4. New tests (4 vitest) pass.
5. `cd ui ; npx vitest run` green (+4 vitest tests over HEAD baseline).
6. `cd ui ; npm run build` green (no `tsc -b` errors).
7. `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` green (pytest gate unchanged — this AD doesn't touch Python).
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Tracking

- **PROGRESS.md** — add to Wave 161 "in flight" block; close #655 on ship.
- **DECISIONS.md** — append AD-722b-4a entry.
- **docs/development/roadmap.md** — bump status; add forward markers per "Forward markers" section.

---

## Verified Against Codebase (2026-05-15)

```
ui/src/avatars/useFleetAvatarTelemetry.ts:
  19: export function useFleetAvatarTelemetry({
  21:   onFrame,
  22:   enabled = true,
  23:   url,
  66:   return `${proto}//${window.location.host}/api/agent/avatar-telemetry/stream`;

ui/src/components/CognitiveCanvas.tsx:
  61: export function CognitiveCanvas() {
  62:   const systemMode = useStore((s) => s.systemMode);
  63:   const connected = useStore((s) => s.connected);
  64:   const grading = modeGrading(systemMode);

ui/src/store/useStore.ts: (zustand store — verified exists)
ui/src/store/types.ts: (verified exists)
ui/src/__tests__/useFleetAvatarTelemetry.test.ts: (Wave 160 hook tests)
```
