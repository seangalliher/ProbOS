# AD-721f — Cognitive-Canvas Avatar Replacement

**Status:** Medium UI. **Closes:** #533. **Tests:** +7 vitest (1 deferred-skip → AD-721f-1). **Wave:** 168. **UI gate required.**

## Problem

The Cognitive Canvas (`ui/src/components/CognitiveCanvas.tsx` + `ui/src/canvas/agents.tsx`) currently renders all agents as glowing instanced spheres (bloom orbs) via `THREE.InstancedMesh` (`agents.tsx:33-34`). With the AD-721 avatar pipeline now mature (per-tier VRMs via AD-721g, browser upload via AD-721h, preview via AD-721d-3, all Wave 167), the canvas should render the agent's actual VRM at canvas scale for idle agents instead of an abstract orb.

Issue #533 specifies: "low-LOD VRM at canvas scale. Performance work."

## Solution

Add a **per-agent toggle** in the canvas to swap an orb instance for a low-LOD VRM. The orb path stays as the default and as a degraded-mode fallback (no VRM loaded, error, performance budget exceeded). Per-frame cost stays bounded by:

1. **LOD frustum**: render VRMs only for agents within a camera-distance threshold; orbs beyond.
2. **Concurrency cap**: at most N VRMs rendered simultaneously (config-gated, default 12).
3. **Shared GLTFLoader**: reuse the loader from `CrewVRM.tsx` — no duplicate loads.
4. **Fallback on error**: any VRM that fails to load reverts that agent to the orb path silently.

Click behavior is unchanged (raycaster opens the agent profile). Tooltip behavior preserved.

## Implementation

### Section 1: Config flag

Add to `src/probos/config.py` `HXIConfig` (or equivalent — verify in pre-flight):

```python
canvas_render_vrm_avatars: bool = Field(
    default=False,
    description=(
        "AD-721f: render registered VRMs in the Cognitive Canvas at canvas "
        "scale for agents within the LOD distance threshold. Default OFF — "
        "operators with low-end GPUs keep the orb-only path."
    ),
)
canvas_max_concurrent_vrms: int = Field(
    default=12, ge=0, le=64,
    description="AD-721f: max VRMs rendered simultaneously in the canvas.",
)
canvas_vrm_lod_distance: float = Field(
    default=15.0, gt=0.0,
    description=(
        "AD-721f: camera-distance threshold (world units) under which "
        "agents render as VRMs. Beyond this distance, orb path is used."
    ),
)
```

Surface these in the existing `/api/system/status` payload if the canvas reads HXI config there.

### Section 2: New `ui/src/canvas/agentVRM.tsx`

A new component that renders **one** agent's VRM at canvas position. Reuses `CrewVRM.tsx` infrastructure (`@pixiv/three-vrm`, `GLTFLoader`). Differences from `CrewVRM`:

- Position driven by `agent.position` from the store (not a fixed `[0, 0, 0]` like the popout).
- Auto-scale to fit the canvas-scale budget (per `cfg.canvas_vrm_lod_distance`).
- `onLoadError`: emit a one-shot signal so `agents.tsx` falls back to the orb instance for this agent.
- No lip-sync wiring — that lives in the popout viewer only.

### Section 3: `ui/src/canvas/agents.tsx` — split orb path from VRM path

In `AgentNodes`:

1. Read `useStore((s) => s.hxiConfig.canvas_render_vrm_avatars)` (or equivalent existing selector).
2. If disabled → render the existing orb instanced mesh path unchanged.
3. If enabled:
   - Compute camera distance per agent in a frame-budget-bounded loop.
   - Pick the closest N agents (`cfg.canvas_max_concurrent_vrms`) within `cfg.canvas_vrm_lod_distance`.
   - Render those as `<AgentVRM agent={agent} />` siblings.
   - Render the remaining agents in the orb instanced mesh path.

**Raycaster preservation.** The orb path keeps `THREE.InstancedMesh` raycasting unchanged. The VRM path uses per-VRM `onClick` / `onPointerOver` on the root group. Both must resolve to the same `useStore.openAgentProfile(agent.id)` / `setHoveredAgent(agent, ...)` callbacks.

**HXI fragility note (per memory):** tooltips break easily when `agents.tsx` is edited. Vitest must cover the hover path post-change.

### Section 4: Per-agent VRM resolution

Reuse the existing AD-721g per-tier baseline resolver. The VRM URL for agent X is `cfg.avatars.vrm_url_for(agent_id, tier)` (or whatever the existing helper is — verify in pre-flight from `baseline_resolver.py`). Designed avatars (AD-721d) take priority over the tier baseline.

### Section 5: Honest-degrade matrix

| Condition | Behavior |
|---|---|
| `canvas_render_vrm_avatars=False` | Orb path only (current behavior). |
| Enabled + no VRM resolved for agent | That agent stays as an orb instance. |
| Enabled + VRM load error | That agent reverts to orb instance silently; log warning. |
| Enabled + agent outside LOD distance | Orb instance. |
| Enabled + concurrency cap reached | Closest N rendered as VRM, rest as orbs. |

## Tests

`ui/src/canvas/__tests__/agentVRM.test.tsx` (+5 vitest, one `.skip` until AD-721f-1):

1. `renders orb path when flag disabled` — store mock with flag=false, no `AgentVRM` mounted.
2. `mounts AgentVRM for agents inside LOD distance when flag enabled` — camera at known position, mock agents at varying distances, assert exactly the close ones get VRM mounts.
3. `respects canvas_max_concurrent_vrms cap` — 20 agents inside LOD distance with cap=5 → exactly 5 VRMs mounted.
4. `falls back to orb instance on VRM load error` — mock GLTFLoader rejection, assert the failed agent appears in the orb instanced mesh count.
5. *(deferred → AD-721f-1 forward marker)* `per-frame useFrame cost stays under budget at N=12 VRMs` — fixture-based assertion that the cumulative cost of every mounted `AgentVRM`'s `useFrame` callback stays below a configurable budget (default `8 ms` per frame at N=12). Vitest under jsdom has no real WebGL renderer, so the only reliable measurement is wall-time of the React Three Fiber `useFrame` callbacks themselves. Builder ships this as a `test.skip(...)` with a TODO referencing `AD-721f-1: per-frame budget instrumentation` and files a follow-up issue at merge time. If a synthetic measurement path (e.g. instrumented mock of `useFrame` that sums callback wall-times across mounted components in a single tick) proves stable in pre-flight, ship it as a non-skipped Test 5 instead.

`ui/src/canvas/__tests__/agents.tooltip.test.tsx` (+2 vitest):

6. `tooltip fires on VRM hover (flag enabled)` — assert `setHoveredAgent` called with the right agent on VRM `onPointerOver`.
7. `tooltip fires on orb hover (flag disabled)` — regression guard for the existing path.

## What this does NOT change

- `CrewVRM.tsx` and `CrewAvatarPopout.tsx` — untouched.
- AD-721d preview / propose / approve endpoints — untouched.
- Orb-rendering performance for the default (flag-off) case — must remain bit-for-bit equivalent.
- Lip-sync wiring — stays popout-only.

## Tracking

- `DECISIONS.md` — append AD-721f shipped entry.
- `PROGRESS.md` — bump highest-AD line if needed.
- `docs/development/roadmap.md` — mark AD-721f shipped.
- `gh issue close 533 --comment "Shipped Wave 168 (AD-721f). Low-LOD VRM at canvas scale with LOD distance + concurrency cap; orb path preserved as default. See DECISIONS.md."`

## Acceptance Criteria

1. New config: `canvas_render_vrm_avatars` (default False), `canvas_max_concurrent_vrms` (default 12), `canvas_vrm_lod_distance` (default 15.0).
2. New file: `ui/src/canvas/agentVRM.tsx`.
3. `agents.tsx` split path: orb-only when flag off; mixed when on.
4. 6 vitest pass.
5. `cd ui; npm run build` succeeds (AD-738b gate — `tsc -b` must pass).
6. `cd ui; npx vitest run` green.
7. Full Python gate green: `pytest tests/ -q -n 4 --dist=loadfile`.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-17)

```
ls ui/src/canvas/
  agents.tsx       11206 bytes  (THREE.InstancedMesh — line 33-34)
  animations.tsx   10259 bytes
  clusters.tsx
  connections.tsx
  effects.tsx
  scene.ts

grep "InstancedMesh" ui/src/canvas/agents.tsx
  line 33: const meshRef = useRef<THREE.InstancedMesh>(null);
  line 34: const ringRef = useRef<THREE.InstancedMesh>(null);

ls ui/src/components/profile/
  CrewVRM.tsx            (component to reuse)
  CrewAvatarPopout.tsx   (popout wrapper — DO NOT touch)

grep "CognitiveCanvas" ui/src/components/CognitiveCanvas.tsx
  line 63: export function CognitiveCanvas()

ls src/probos/avatars/baseline_resolver.py  # AD-721g per-tier baseline VRM resolver
  2650 bytes (Wave 167)
```
