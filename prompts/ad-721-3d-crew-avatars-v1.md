# AD-721 v1 — 3D Crew Avatars (VRM popout from profile card)

**Issue:** [#515](https://github.com/seangalliher/ProbOS/issues/515)
**Type:** Architecture Decision (HXI presence — agent-bodied UI)
**Depends on:** AD-376 (`CrewProfile`), AD-597a (`McpAppRegistry` — referenced for v2 only), AD-718 (`onSpeechEvent` mouth-animation hook)
**Wave:** 133

## Goal

Every crew member gets a 3D avatar that pops out of their profile card. The avatar reacts to runtime state — trust delta, cognitive load, working state, tier-3 alerts — through VRM blend-shape expressions, and its mouth opens in time with AD-718's TTS playback. Counselor (Echo) is the first design partner. v1 ships the loader, the popout, the expression mapping, the audio-amplitude mouth animation, and a parametric fallback when no `appearance.json` exists.

This AD ships in the same wave as AD-718 so the TTS-audio→mouth coupling lands as one designed thing, not a retrofit.

## VRM library decision

- **Adopt:** `@pixiv/three-vrm` v2 (1.9k stars, MIT, https://github.com/pixiv/three-vrm). Canonical VRM 1.0 loader for Three.js; load → update → expressions → look-at → spring bones; works directly with `@react-three/fiber`'s `useFrame` loop already on the stack.
- **Reject for v1:** `@readyplayerme/visage` (90 stars, MIT). It is a React wrapper over an opinionated Ready Player Me hosted-service flow; agent-authored appearance is the long-term direction (forward marker AD-721d), and Visage's RPM-hosted assumption fights that. We can revisit if a future commercial overlay wants RPM avatars.
- **Already on the stack** (`ui/package.json:11–22`): `three ^0.172.0`, `@react-three/fiber ^9.0.0`, `@react-three/drei ^10.0.0`, `@react-three/postprocessing ^3.0.0`. v1 adds **only** `@pixiv/three-vrm`.

## Verified Against Codebase (2026-05-08)

Line numbers are "around line N" (per `review-criteria.md` §6); greps below are ground truth at 2026-05-08 HEAD.

```
grep -n "@react-three/fiber\|@react-three/drei\|three" ui/package.json
  12:    "@react-three/drei": "^10.0.0",
  13:    "@react-three/fiber": "^9.0.0",
  14:    "@react-three/postprocessing": "^3.0.0",
  20:    "three": "^0.172.0",
```

- ✅ `ui/package.json` around lines 12–20 — Three.js stack already installed; only `@pixiv/three-vrm` is new.
- ✅ `ui/src/components/profile/AgentProfilePanel.tsx` around lines 1–14 — imports `ProfileChatTab`, `ProfileWorkTab`, `ProfileInfoTab`, `ProfileHealthTab`, `ProfileMemoryTab`. Tabs are `'chat' | 'work' | 'profile' | 'health' | 'memory'`. **D3 attaches the avatar popout to the panel header (above the tab bar), not as a new tab.**
- ✅ `ui/src/components/profile/AgentProfilePanel.tsx` around line 20 — `DEPT_COLORS` mapping (engineering=#b0a050, science=#50b0a0, medical=#5090d0, security=#d05050, bridge=#d0a030). **D7 reuses this for the parametric fallback tint.**
- ✅ `ui/src/components/profile/AgentProfilePanel.tsx` — `agent.callsign`, `agent.displayName`, `agent.agentType` are available on the agent object passed in. **D3 popout receives `agentId` and reads the same store entry.**
- ✅ `ui/src/components/profile/AgentProfilePanel.tsx` around line 92 — `isCrew = profileData?.isCrew ?? true` (BF-017: defaults to true until profile loads). **Non-crew agents do not get the avatar popout.**
- ✅ `ui/src/canvas/agents.tsx`, `animations.tsx`, `clusters.tsx`, `connections.tsx`, `scene.ts` — existing canvas modules. **D3 explicitly does NOT touch these.** The popout is a self-contained `<Canvas>` from `@react-three/fiber` rendered inside a fixed-position React modal — not part of the cognitive canvas's scene graph.
- ✅ `src/probos/crew_profile.py` around line 116 — `class CrewProfile`. D2 adds an `appearance: AppearanceProfile = field(default_factory=AppearanceProfile)` field with the same nested-dataclass pattern AD-718 uses for `voice`.
- ✅ `src/probos/routers/agents.py` around line 40 — `@router.get("/{agent_id}/profile")` — D5 adds `"appearance": ...` to the returned dict (same site that AD-718 D5 adds `"voiceProfile"`; both edits are in one path — the `profile_data = {` block around line 110).
- ✅ AD-718 D1 introduces `onSpeechEvent(fn)` in `ui/src/audio/voice.ts` emitting `'start' | 'end'` events with `agent_id`. **D5 below subscribes to that hook**; if AD-718 is not yet merged when AD-721 is built, the Builder MUST land AD-718 first (same wave, AD-718 has the lower number for that reason).
- ✅ `data/avatars/` directory does NOT exist at HEAD. D2 creates it with a `.gitkeep`. v1 ships NO `.vrm` binaries in the OSS repo (license / size). Operators drop their own VRM models in.
- ✅ `src/probos/routers/system.py` does NOT yet serve `/avatars/*.vrm`. **D6 adds a static-file route** under FastAPI's existing app, scoped to `data/avatars/`.
- ✅ `src/probos/mcp_apps/registry.py` around line 42 — `MCPAppRegistry` exists; `McpAppFrame` is **not** a real React component name in HEAD (verified during AD-706 review). v1 renders the popout directly in the React tree, NOT in an iframe — fine-grained reactive expression updates beat iframe isolation here, and the dispatch's "default recommendation" agrees.
**Dispatch contradictions surfaced:**

1. Dispatch references `data/avatars/_defaults/{ensign,lieutenant,commander,senior_officer}.vrm` as if VRMs already exist. They don't, and we don't ship third-party VRMs in the OSS repo. v1 uses a **parametric Three.js fallback** (D7), not a default VRM.
2. Dispatch suggests adding `appearance` to a non-existent `src/probos/profile_store.py`. The real edit site is `src/probos/crew_profile.py` `CrewProfile` dataclass.

## Scope (v1 only)

- `@pixiv/three-vrm` loader + viewer in a React popout.
- Expression mapping from runtime signals → VRM blend shapes.
- Audio-amplitude mouth animation driven by AD-718's `onSpeechEvent` callbacks.
- `appearance` field on `CrewProfile` with `vrm_url`, `expression_overrides`, `color_palette_hint`.
- Parametric fallback (capsule + glow + department-color tint) when `appearance.vrm_url` is empty or load fails.
- Counselor (Echo) is the named v1 reference; her `appearance.json` is shipped as a YAML stanza in her crew profile if and only if the Captain provides a VRM. Otherwise Echo gets the parametric fallback tinted bridge-gold.
- Default-disabled via a new `BrowserAvatarsConfig.enabled: bool = False` (Wave 10 convention #14). When disabled, the popout button is hidden.

## Non-Goals (explicit)

- Photorealistic rendering, advanced shaders, hair simulation, cloth simulation.
- Phoneme-accurate lip-sync — D5 ships amplitude-only; phoneme work is AD-721b.
- In-app avatar editor — Captain hand-edits `appearance.json` for v1 (AD-721a).
- Agent-driven appearance authoring — AD-721d.
- VR / spatial-scene avatars — AD-721c.
- Full skeletal animation library (idle variations, gestures) — AD-721e (Mixamo absorption candidate).
- Replacing the cognitive canvas avatars (`ui/src/canvas/agents.tsx`) — those stay as glowing nodes; the 3D avatar lives only in the profile-card popout.
- Captain-watch streaming for the avatar (it's local-only) — out of scope; no relation to AD-706a.

## Deliverables

### D1. New dependency

`ui/package.json` — add to `dependencies`:

```json
"@pixiv/three-vrm": "^2.0.0"
```

`npm install` runs in pre-flight; commit the `package-lock.json` delta with the rest of the change.

### D2. New `AppearanceProfile` dataclass in `src/probos/crew_profile.py`

Insert immediately after `VoiceProfile` (added by AD-718 D3):

```python
@dataclass
class AppearanceProfile:
    """AD-721: per-agent 3D avatar appearance.

    `vrm_url` is a URL relative to the HXI's static-file root (served by
    ``routers/system.py``'s avatar route, D6). Empty `vrm_url` means
    "use the parametric fallback" (D7). `expression_overrides` maps
    VRM blend-shape names to scalar offsets so a single VRM model can
    be re-skinned per agent without authoring a new `.vrm` file.
    `color_palette_hint` is consumed by the parametric fallback only.
    """
    vrm_url: str = ""                                   # "" = parametric fallback
    expression_overrides: dict[str, float] = field(default_factory=dict)
    color_palette_hint: str = ""                        # any CSS color; "" = use department color

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppearanceProfile":
        return cls(
            vrm_url=data.get("vrm_url", ""),
            expression_overrides=dict(data.get("expression_overrides", {})),
            color_palette_hint=data.get("color_palette_hint", ""),
        )
```

Add the field to `CrewProfile`:

```python
    appearance: AppearanceProfile = field(default_factory=AppearanceProfile)
```

Extend `to_dict()` / `from_dict()` symmetrically (same pattern as AD-718 D3 for `voice`).

Create `data/avatars/.gitkeep` so the directory ships even without VRM binaries. Add `data/avatars/*.vrm` to `.gitignore` (operators bring their own models).

### D3. `CrewAvatarPopout.tsx` — new React component

`ui/src/components/profile/CrewAvatarPopout.tsx`:

```typescript
import { Suspense, useEffect, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { onSpeechEvent } from '../../audio/voice';
import { CrewVRM } from './CrewVRM';
import { ParametricAvatar } from './ParametricAvatar';

interface Props {
  agentId: string;
  appearance: { vrm_url: string; expression_overrides: Record<string, number>; color_palette_hint: string } | null;
  departmentColor: string;
  agentSignals: AgentSignals;   // trust delta, load, working_state, tier3_alert (D4)
  onClose: () => void;
}

export function CrewAvatarPopout({ agentId, appearance, departmentColor, agentSignals, onClose }: Props) {
  const [loadFailed, setLoadFailed] = useState(false);
  const useVRM = !!appearance?.vrm_url && !loadFailed;

  return (
    <div
      role="dialog"
      aria-label={`Avatar — ${agentId}`}
      style={{
        position: 'fixed', right: 24, bottom: 24,
        width: 320, height: 480,
        background: 'rgba(10, 10, 18, 0.92)',
        border: '1px solid rgba(240, 176, 96, 0.2)',
        borderRadius: 12,
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        zIndex: 30,
        animation: 'popout-in 220ms ease-out',
      }}
    >
      <button onClick={onClose} aria-label="Close avatar"
        style={{ position: 'absolute', top: 6, right: 6, background: 'none', border: 'none', color: '#8888a0', fontSize: 16, cursor: 'pointer' }}>
        &#x2715;
      </button>
      <Canvas camera={{ position: [0, 1.4, 1.5], fov: 30 }}>
        <ambientLight intensity={0.6} />
        <directionalLight position={[2, 4, 2]} intensity={0.8} />
        <Suspense fallback={null}>
          {useVRM ? (
            <CrewVRM
              vrmUrl={appearance!.vrm_url}
              agentId={agentId}
              expressionOverrides={appearance!.expression_overrides}
              signals={agentSignals}
              onLoadError={() => setLoadFailed(true)}
            />
          ) : (
            <ParametricAvatar tint={appearance?.color_palette_hint || departmentColor} signals={agentSignals} />
          )}
        </Suspense>
      </Canvas>
    </div>
  );
}
```

The popout opens from a small "Show avatar" button placed in `AgentProfilePanel.tsx`'s header (between the title text and the close button), rendered only when `isCrew` is true and `BrowserAvatarsConfig.enabled` is true (the latter surfaced via the existing config-fetch path or a feature-flag store entry — Builder picks the simpler one in pre-flight).

### D4. `AgentSignals` — runtime → expression channel mapping

```typescript
// ui/src/components/profile/avatarSignals.ts
export interface AgentSignals {
  trust_delta: number;       // last cycle trust delta, [-1, +1]
  load: number;              // 0..1, 1 = LLM call active
  working_state: 'idle' | 'responding' | 'blocked';
  tier3_alert: boolean;
}

export function deriveAgentSignals(agentId: string, store: any): AgentSignals {
  // Read from the existing useStore. Map trust history delta, processing flag,
  // working_state from agent record, and notifications for tier-3.
  // Concrete shapes: store.agents.get(agentId), store.processing, store.notifications.
  // Builder fills this from the live store schema in pre-flight.
}
```

Channel mapping (consumed in `CrewVRM.tsx`):

| Signal | VRM blend-shape (`VRMExpressionPresetName`) | Mapping |
|---|---|---|
| `trust_delta > 0` | `happy` | weight = clamp(`trust_delta * 2`, 0, 1) |
| `trust_delta < 0` | `sad` | weight = clamp(`-trust_delta * 2`, 0, 1) |
| `load > 0.5` | `lookUp` + `oh` | thinking gesture; both at 0.3 |
| `working_state === 'blocked'` | `angry` | weight = 0.4 (concerned, not hostile) |
| `tier3_alert` | `surprised` | weight = 0.6 |

Apply `expression_overrides` from `AppearanceProfile` AFTER the signal-driven weights — overrides bias the baseline expression (e.g. Counselor's `{"relaxed": 0.2}` keeps her gentle even at idle).

### D5. TTS-driven mouth animation (synergy with AD-718)

In `CrewVRM.tsx`, subscribe to AD-718's `onSpeechEvent` on mount, filter to events whose `agent_id` matches this avatar's, and drive the `aa` blend shape from a Web Audio `AnalyserNode`:

```typescript
useEffect(() => {
  let analyser: AnalyserNode | null = null;
  let stream: MediaStream | null = null;
  let raf = 0;

  const unsubscribe = onSpeechEvent((e) => {
    if (e.agent_id !== agentId) return;
    if (e.type === 'start') {
      // Hook the SpeechSynthesisUtterance through a MediaStreamDestination.
      // Browsers ship SpeechSynthesis without a routable audio graph by default,
      // so v1 falls back to a SCHEDULED amplitude curve derived from utterance.text length
      // when AudioContext capture is unavailable.
      analyser = _attachAnalyserOrSchedule(e.utterance);
      const tick = () => {
        if (!analyser) return;
        const buf = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(buf);
        const amp = buf.reduce((a, b) => a + b, 0) / buf.length / 255;  // 0..1
        if (vrmRef.current) {
          vrmRef.current.expressionManager?.setValue('aa', Math.min(0.9, amp * 1.4));
        }
        raf = requestAnimationFrame(tick);
      };
      tick();
    } else if (e.type === 'end') {
      cancelAnimationFrame(raf);
      vrmRef.current?.expressionManager?.setValue('aa', 0);
      analyser = null;
      stream?.getTracks().forEach(t => t.stop());
      stream = null;
    }
  });

  return () => {
    unsubscribe();
    cancelAnimationFrame(raf);
    stream?.getTracks().forEach(t => t.stop());
  };
}, [agentId]);
```

`_attachAnalyserOrSchedule` is a small helper in `ui/src/audio/speechAmplitude.ts` — Tier-2 log-and-degrade: if real-time capture isn't possible (most browsers, today), it returns a fake `AnalyserNode`-shaped object that synthesises a plausible amplitude curve. The fake exposes the minimum surface the `useFrame` consumer above touches:

```typescript
// ui/src/audio/speechAmplitude.ts

/** AD-721 D5: minimum AnalyserNode shape used by the mouth-animation tick. */
export interface FakeAnalyser {
  frequencyBinCount: number;             // size of the buffer the consumer allocates
  getByteFrequencyData(buf: Uint8Array): void;  // writes 0..255 amplitude values
}

/** Returns a real AnalyserNode if the browser can route SpeechSynthesis through
 *  Web Audio (rare today), otherwise a synthetic FakeAnalyser that pretends. */
export function _attachAnalyserOrSchedule(
  utterance: SpeechSynthesisUtterance,
): AnalyserNode | FakeAnalyser {
  // 1) Try a real AudioContext + MediaStreamDestination capture path.
  //    If unsupported, fall through to the synthetic curve.

  // 2) Synthetic fallback (default in Chromium/Firefox today):
  const text = utterance.text ?? '';
  const rate = utterance.rate || 0.95;
  // Heuristic duration: ~5 chars/word, ~3 words/sec at rate=1.
  const durationMs = Math.max(400, (text.length / 5) * (1000 / 3) / rate);
  const startedAt = performance.now();
  const binCount = 32;

  return {
    frequencyBinCount: binCount,
    getByteFrequencyData(buf: Uint8Array): void {
      const elapsed = performance.now() - startedAt;
      if (elapsed > durationMs) { buf.fill(0); return; }
      // Sine envelope at ~6 Hz (syllable cadence) modulated by mild noise.
      const t = elapsed / 1000;
      const envelope = 0.5 + 0.4 * Math.sin(2 * Math.PI * 6 * t);
      for (let i = 0; i < binCount; i++) {
        const noise = Math.random() * 0.2;
        buf[i] = Math.min(255, Math.floor((envelope + noise) * 200));
      }
    },
  };
}
```

This keeps the mouth moving in lockstep with audio without claiming phoneme-accuracy. The synthetic curve never claims to read real audio — it's a known visual approximation. **Phoneme accuracy and real-audio capture are AD-721b.**

### D6. Static-file serving for `data/avatars/`

In `src/probos/routers/system.py`, mount a static-file route under `/avatars`:

```python
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# In the router setup:
_avatars_dir = Path("data/avatars")
_avatars_dir.mkdir(parents=True, exist_ok=True)
# This is a router-level mount, NOT app.mount — preserves the same auth/middleware path.
# If the existing system.py serves UI assets via `ui://` resource handler, follow that pattern instead.
```

**Builder note:** the dispatch and AD-706 verify-first establish that `routers/system.py` already serves UI assets via a `ui://` resource handler. **Pre-flight: Builder greps `src/probos/routers/system.py` for the existing `ui://` resource handler and mirrors its auth/middleware path** — add a custom `GET /avatars/{filename}` route immediately adjacent to it rather than mounting `StaticFiles` at the app level (so security middleware applies uniformly). Refuse paths that escape `data/avatars/` (path-traversal defense; `Path.resolve().is_relative_to(...)`).

### D7. Parametric fallback — `ParametricAvatar.tsx`

When `appearance.vrm_url` is empty OR the VRM load throws, render a soft-glow capsule made from `@react-three/drei`'s `RoundedBox` + a faint emissive-tinted point light. Tint is `appearance.color_palette_hint` if set, otherwise the department color from `DEPT_COLORS`. Animations (driven by `useFrame`):

- Idle (`working_state==='idle'`): gentle Y-axis breathing at 0.3 Hz.
- Responding (`working_state==='responding'`): faster pulse at 1.2 Hz + emissive ramp to 0.8.
- Blocked (`working_state==='blocked'`): tilt + dimmer emissive (0.3).
- Tier-3 alert: red rim flash at 2 Hz overriding the tint.
- TTS playback (subscribed via `onSpeechEvent`): scale Y by amplitude (mouth analogue).

Ship this even when `BrowserAvatarsConfig.enabled` is true and an operator hasn't provided a VRM — Counselor's first-run experience is the parametric fallback tinted bridge-gold, NOT a 404.

### D8. New `AvatarsConfig` Pydantic model in `src/probos/config.py`

```python
class AvatarsConfig(BaseModel):
    """AD-721: 3D crew avatars (VRM popout)."""
    enabled: bool = False                                # Wave 10 convention #14
    avatars_dir: str = "data/avatars"
    max_vrm_size_bytes: int = 25 * 1024 * 1024           # 25 MB hard cap on uploaded VRM size
    fallback_to_parametric_on_error: bool = True
```

Add to `SystemConfig` near the other AD-numbered configs:

```python
    avatars: AvatarsConfig = Field(default_factory=AvatarsConfig)  # AD-721
```

`AvatarsConfig.enabled` must be exposed to the HXI as a boolean flag. **Pre-flight Builder check:** grep `src/probos/routers/system.py` and `src/probos/routers/config.py` (if present) for any existing config-flag GET endpoint (e.g. `/api/config`, `/api/flags`, `/api/system/config`). If one exists, append `avatars_enabled: bool` to its response shape and read it in the HXI. **If no such endpoint exists**, add a new minimal route `GET /api/config/avatars-enabled` returning `{"enabled": runtime.config.avatars.enabled}` — single endpoint, no parameters, no auth surface beyond the existing router stack. Do NOT design new generic config-API surface in this AD; that's a separate forward marker if needed.

### D9. Tests

**Python (`tests/test_ad721_avatars.py`):**

1. `test_appearance_profile_defaults` — `AppearanceProfile()` has empty strings + empty dict.
2. `test_appearance_profile_to_from_dict_roundtrip` — round-trip preserves all fields.
3. `test_crew_profile_appearance_persistence` — `CrewProfile.to_dict()/from_dict()` round-trip preserves `appearance`.
4. `test_avatars_config_defaults` — `enabled=False`, sane defaults.
5. `test_avatar_get_path_traversal_rejected` — `GET /avatars/../etc/passwd` returns 400/403.
6. `test_avatar_get_unknown_file_404` — known directory, missing filename.
7. `test_avatar_get_oversize_rejected` — file >25 MB returns 413.
8. `test_avatar_get_happy_path` — small fake `.vrm` returns 200 + `application/octet-stream`.
9. `test_get_profile_includes_appearance` — `GET /api/agent/{id}/profile` includes `"appearance"` with all three fields.

**Vitest (`ui/src/components/profile/__tests__/CrewAvatarPopout.test.tsx`):**

10. `popout renders parametric fallback when appearance.vrm_url is empty` — assert `<ParametricAvatar>` mounted, no `<CrewVRM>`.
11. `popout renders parametric fallback when VRM load throws` — `onLoadError` triggered → state flip → fallback rendered.
12. `popout subscribes and unsubscribes onSpeechEvent` — mount/unmount asserts add/remove listener.
13. `mouth amplitude updates only for matching agent_id` — fire `onSpeechEvent` with another `agent_id` → no `setValue('aa', ...)` call.
14. `popout closes when onClose prop fires` — click X → `onClose` invoked.
15. `popout NOT shown for non-crew agents` — `isCrew=false` → "Show avatar" button hidden.

**Vitest (`ui/src/components/profile/__tests__/ParametricAvatar.test.tsx`):**

16. `parametric uses department tint when color_palette_hint is empty` — color prop trace.
17. `parametric uses color_palette_hint when set` — overrides department.
18. `parametric reacts to working_state transitions` — animation params change idle→responding (assert mock-frame deltas).
19. `parametric flashes red on tier3_alert` — emissive-rim color ≈ red within 1 frame.

**Vitest (`ui/src/components/profile/__tests__/avatarSignals.test.ts`):**

20. `deriveAgentSignals maps trust delta correctly` — known store state → expected delta.
21. `deriveAgentSignals maps working_state from agent record` — covers idle/responding/blocked.

Tests are order-independent. VRM loader is mocked (no GLB fixtures in the test harness); audio `AnalyserNode` is mocked; `onSpeechEvent` is the real hook from AD-718.

## Acceptance criteria

- Pre-flight: working-tree integrity check (`git diff --numstat | sort -k2nr | Select-Object -First 5`; >200 deletions on any tracked file = STOP and surface).
- AD-718 must be merged before AD-721's tests run; if not, surface and stop.
- `npm install` in `ui/` adds `@pixiv/three-vrm` and updates `package-lock.json`.
- Focused gate: `pytest tests/test_ad721_avatars.py -v -n 0` green; `cd ui && npx vitest run` green for the four new test files.
- Full Python gate: `pytest tests/ -q -n 8 --dist=loadfile` non-decreasing test count.
- Full UI gate: `cd ui && npx vitest run` green.
- With `avatars.enabled=False` (default), the "Show avatar" button is hidden in `AgentProfilePanel.tsx`. With `enabled=True` and no VRM in `data/avatars/`, clicking the button opens the parametric fallback (department-tinted).
- With `enabled=True` and a Counselor VRM at `data/avatars/echo.vrm` plus `appearance.vrm_url = "/avatars/echo.vrm"`, the popout loads the VRM and her mouth animates while AD-718's TTS plays her reply.
- The cognitive canvas (`ui/src/canvas/agents.tsx`) is unchanged.
- HXI design principles: no emoji used; popout uses the existing amber/blue/violet palette; motion communicates state.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- AD-numbering re-verification at commit time: confirm AD-721 has no live entry in `PROGRESS.md` / era files / `decisions-era-*.md` before authoring the new entry.

## Tracking

- `PROGRESS.md` — add CLOSED row when shipped.
- `decisions-era-5-unification.md` — append the AD-721 entry block.
- `docs/development/roadmap.md` — flip the "3D crew avatars" row to shipped with AD-721 reference.
- `.gitignore` — add `data/avatars/*.vrm`.
- GH issue #515 — close on merge with link to the merge commit.

## Forward markers

The Builder MUST file each of these as a GH issue at gate-3 (per BUILDER-EXECUTION-PLAN Post-Sweep step 6):

- **AD-721a** — Captain's avatar editor UI. Edit `appearance.json` (vrm_url, expression overrides, color hint) without touching JSON. Live-preview within the popout.
- **AD-721b** — Phoneme-accurate lip-sync. Replace D5's amplitude-only mouth animation with phoneme estimation (regex-based `aa/ih/ou/ee/oh` mapping or an ML phoneme model). Hooks into AD-718's reserved `'boundary'` SpeechEvent.
- **AD-721c** — VR / spatial-scene avatar mode. Room-scale crew on the cognitive canvas itself; not the popout.
- **AD-721d** — Agent-authored appearance pipeline. Agent reflects on its own personality and proposes appearance edits; Counselor reviews; Captain approves. Closes the loop on "agent picks own face."
- **AD-721e** — Skeletal animation library. Idle variations, gestures, hand poses. Mixamo absorption candidate (license review required before adoption).
- **AD-721f** — Cognitive-canvas avatar replacement. Replace the glowing-node renderer in `ui/src/canvas/agents.tsx` with a low-LOD VRM at canvas scale. Performance work; out of scope for v1.
- **AD-721g** — Per-tier baseline VRMs (ensign / lieutenant / commander / senior). Requires either authoring or licensing four VRMs; tracked but not committed.
- **AD-721h** — Browser-based VRM upload UI. Captain drags `.vrm` into the avatar editor; backend validates + writes to `data/avatars/`. Defense-in-depth on file-type and size.

## Verified Against Codebase (2026-05-08) — grep evidence

```
grep -n "@pixiv/three-vrm\|@react-three" ui/package.json
  12:    "@react-three/drei": "^10.0.0",
  13:    "@react-three/fiber": "^9.0.0",
  14:    "@react-three/postprocessing": "^3.0.0",
  20:    "three": "^0.172.0",
  (no @pixiv/three-vrm — confirms it must be added)

grep -n "DEPT_COLORS\|isCrew\|AgentProfilePanel" ui/src/components/profile/AgentProfilePanel.tsx
   20: const DEPT_COLORS: Record<string, string> = {
   91: const deptColor = DEPT_COLORS[department?.toLowerCase()] || '#666';
   92: const isCrew = profileData?.isCrew ?? true;
   95: const visibleTabs = isCrew
  206: {effectiveTab === 'chat' && isCrew && <ProfileChatTab agentId={agentId} />}

grep -n "^class\|^@dataclass" src/probos/crew_profile.py
   50: @dataclass
   51: class PersonalityTraits:
  115: @dataclass
  116: class CrewProfile:
  215: class ProfileStore:

grep -n "agent_id.*profile\|profile_data = " src/probos/routers/agents.py
   40: @router.get("/{agent_id}/profile")
  110: profile_data = {

grep -n "class MCPAppRegistry" src/probos/mcp_apps/registry.py
   42: class MCPAppRegistry:
  (Builder pre-flight: grep src/probos/routers/system.py for the ui:// resource handler and mirror its pattern; AD-706 review documented it but at-HEAD line drift may apply.)

grep -n "speakResponse\|onSpeechEvent" ui/src/audio/voice.ts
  (HEAD: only speakResponse; onSpeechEvent is added by AD-718 D1 — same wave)
```

Every concrete file path, line number, class name, and import path asserted in this prompt maps to one of the greps above. New entities introduced by this prompt (`AppearanceProfile`, `AvatarsConfig`, `CrewAvatarPopout`, `CrewVRM`, `ParametricAvatar`, `avatarSignals.ts`, `speechAmplitude.ts`, `/avatars/{filename}` route, `data/avatars/` directory, `tests/test_ad721_avatars.py`, the four Vitest files) are introduced by D1–D9 above and should not be flagged as missing during review. `onSpeechEvent` and `VoiceProfile` are introduced by AD-718 in the same wave — Builder lands AD-718 first.

## Revision (2026-05-08)

Applied review findings from `prompts/Reviews/ad-721-3d-crew-avatars-v1-review.md`:

- **Recommended #1 (D5 fake AnalyserNode shape)** — expanded `_attachAnalyserOrSchedule` from a one-paragraph stub to a full TypeScript sketch (around body L255–L290) with a `FakeAnalyser` interface (`frequencyBinCount`, `getByteFrequencyData`), a duration heuristic from `text.length / rate`, and a sine envelope at ~6 Hz (syllable cadence) plus mild noise. The `useFrame` consumer in D5 already calls exactly these two members; Builder no longer reinvents the shape.
- **Recommended #2 (D8 enabled-flag plumbing)** — rewrote the closing paragraph of D8 (around body L308–L309) to commit to one path: pre-flight grep for an existing config-flag endpoint and append `avatars_enabled: bool` to its response, OR add a single dedicated `GET /api/config/avatars-enabled` route returning `{"enabled": ...}`. Explicitly bans designing new generic config-API surface in this AD.
- **Recommended #3 (line drift on AgentProfilePanel.tsx)** — corrected the Verified bullets (around body L31–L36) and the bottom grep block (around body L376–L380) to actual HEAD line numbers (`DEPT_COLORS` ~20, `isCrew` ~92). Switched to "around line N" notation per `review-criteria.md` §6 throughout the Verified section. Also corrected `class CrewProfile` 130→~116, `class PersonalityTraits` 53→~51, `profile_data = {` 117→~110, `MCPAppRegistry` 42→~42 (verified).
- **Recommended #4 (D6 static-file route ui:// reference)** — rewrote D6's Builder-note paragraph (around body L213) to make the pre-flight grep instruction explicit: "Builder greps `src/probos/routers/system.py` for the existing `ui://` resource handler and mirrors its auth/middleware path." Removed the unverified `routers/system.py:590` line citation. Path-traversal defense unchanged.
- **Nit #1 (`from_dict` style consistency)** — cosmetic; left D2's explicit `data.get(...)` pattern as-is. Both styles work.
- **Nit #2 (raw inline `style={...}`)** — cosmetic; v1 keeps inline styles (centralisation deferred to AD-721a).
