# AD-721e — Skeletal Animation Library

**Status:** Medium-large UI + asset manifest. **Closes:** #532. **Tests:** +12 vitest. **Wave:** 168. **UI gate required.**

## Problem

Issue #532 (AD-721e) — Idle variations, gestures, hand poses for VRM avatars. Mixamo was originally suggested but is **REJECTED** per AD-721i-1 (Wave 166 license whitelist) — Mixamo's redistribution terms disqualify it for OSS.

Today `CrewVRM.tsx` has only:
- A relaxed A-pose at load (`CrewVRM.tsx:115`).
- A procedural idle "breathing + gentle sway" loop (`CrewVRM.tsx:398`).
- Lip-sync viseme animation (AD-721 + Wave 158 BF-285).

What's missing: real **AnimationClip**-based skeletal motion for idle variants, talking gestures, listening pose, thinking pose.

## Solution

Three-layer change:

1. **Source CC0/MIT animation clips.** Quaternius and KayKit ship CC0 humanoid animation packs. Choose one (preferred: Quaternius "Ultimate Animated Character Pack" — CC0, mixamo-compatible rig). Document the choice in a license-disposition note. Operator-install pattern (mirrors AD-721g per-tier VRM downloads, AD-721i-1 license whitelist).
2. **Manifest + asset_manifest.py extension.** Extend `src/probos/avatars/asset_manifest.py` to track animation clips with SHA-256, license, source URL. Manifest entries point at the operator's local clip files.
3. **CrewVRM AnimationMixer integration.** Add `THREE.AnimationMixer` + `AnimationClip` playback driven by a new `signals.bodyState: 'idle' | 'talking' | 'listening' | 'thinking'` prop. Procedural breathing/sway stays as a fallback when no clip is available for the requested state.

**No new npm deps.** `three` already ships `AnimationMixer` and `AnimationClip`.

## Implementation

### Section 1: License disposition

Pre-flight: confirm chosen animation source. Default candidate: **Quaternius "Ultimate Animated Character"** (CC0, https://quaternius.com). Backup: **KayKit Character Animations** (CC0).

If neither is available with the four required clips (idle / talking / listening / thinking), surface for Captain ruling before drafting code. Do NOT proceed with Mixamo, ActorCore, ReadyPlayerMe animation packs (license-incompatible).

Document the chosen source + license in `docs/research/skeletal-animations-license.md`:

```markdown
# Skeletal Animation Library — License Disposition (AD-721e)

**Chosen source:** Quaternius "Ultimate Animated Character Pack" v1.x
**License:** CC0 (public domain)
**Source URL:** https://quaternius.com/packs/ultimateanimatedcharacter.html
**Whitelist match:** CC0 — top of `.github/copilot-instructions.md` Captain 2026-05-09 license whitelist.
**Operator install:** see `scripts/animations-fetch.ps1` (this AD).
**Files NOT shipped in repo** (per Captain rule on embedded-licensing files): operator runs the fetch script.

**Selected clips:** idle / talking / listening / thinking (4 minimum). Optional pack: gesture / nod / shrug / typing.
```

### Section 2: Asset manifest extension

Add to `src/probos/avatars/asset_manifest.py`:

```python
@dataclass(frozen=True)
class AnimationClipEntry:
    name: str                    # 'idle' / 'talking' / 'listening' / 'thinking'
    file_path: Path              # operator-local path (gitignored)
    sha256: str                  # for integrity verification
    license: str                 # 'CC0' / 'MIT' / 'Apache-2.0' etc — whitelist enforced
    source_url: str
    duration_s: float


class AnimationManifest:
    """AD-721e: registry of skeletal animation clips available to CrewVRM.

    Operator-managed via scripts/animations-fetch.ps1. Manifest entries are
    integrity-checked on load (SHA-256 match). License field is enforced
    against the AD-721i-1 whitelist on registration.
    """
    _ALLOWED_LICENSES = frozenset({"CC0", "MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "CC-BY-4.0", "MPL-2.0"})

    def register(self, entry: AnimationClipEntry) -> None: ...
    def get(self, name: str) -> AnimationClipEntry | None: ...
    def list_available(self) -> list[str]: ...
```

### Section 3: Server endpoint

Add `GET /api/avatars/animations` to surface the available clip names + URLs to the browser. Returns:

```json
{
  "clips": [
    {"name": "idle", "url": "/api/avatars/animations/idle", "duration_s": 4.2, "license": "CC0"},
    {"name": "talking", "url": "/api/avatars/animations/talking", "duration_s": 6.1, "license": "CC0"}
  ]
}
```

Honest-degrade: if no clips registered, return `{"clips": []}` — browser uses procedural idle only.

### Section 4: `GET /api/avatars/animations/{name}` — clip bytes

Serves the .glb/.gltf bytes with `Content-Type: model/gltf-binary`. Cache headers: `max-age=3600` (clips are immutable per SHA).

### Section 4b: Bone Retargeting (Mixamo → VRM Humanoid)

**The constraint.** Quaternius "Ultimate Animated Character Pack" ships Mixamo-rigged GLBs with bone names like `mixamorig:Hips`, `mixamorig:Spine`, `mixamorig:LeftArm`, etc. `@pixiv/three-vrm` Humanoid uses unprefixed standardized VRM Humanoid bone names (`hips`, `spine`, `leftUpperArm`, etc., per VRM spec). Playing a Mixamo `AnimationClip` directly against `vrm.scene` via `mixer.clipAction(clip).play()` silently fails to bind — `THREE.AnimationMixer` matches tracks by node name, and the VRM scene has no `mixorig:Hips` node. The animation runs (mixer ticks, time advances) but no bones move. No console warning.

**Two builder options:**

- **(a) Pre-bake** through Blender's VRM exporter / Blender's bone-rename tooling: load Quaternius source → rename armature bones to VRM Humanoid spec → re-export GLB with embedded retargeted clips. Operator-side pre-processing step. Source assets must be modified before fetch script lands them.
- **(b) Runtime remap table** (recommended): ship a static `MIXAMO_TO_VRM` map and rewrite each `THREE.KeyframeTrack.name` from `mixamorig:LeftArm.quaternion` → `leftUpperArm.quaternion` before calling `mixer.clipAction(clip)`. Source assets stay as-shipped (CC0 source preserved verbatim — no derivative-redistribution complications, no Blender step in the fetch script).

**Recommend (b).** Add a `retargetMixamoToVRM(clip: THREE.AnimationClip): THREE.AnimationClip` helper in `ui/src/canvas/animation/retarget.ts` (new file). Apply at clip-load time inside Section 5's `clipsCache` population step BEFORE `mixer.clipAction(...)`. Vitest must cover the remap (load a fixture clip with `mixorig:` track names, assert post-remap tracks use VRM bone names AND the count of tracks is preserved).

Minimal map (the 22 VRM Humanoid required bones — full VRM spec list in `@pixiv/three-vrm` source). Tracks whose source bone has no VRM-Humanoid equivalent (e.g., `mixamorig:LeftHandIndex3` for fingers — VRM finger bones are optional) are dropped silently with a debug log.

```typescript
export const MIXAMO_TO_VRM: Record<string, string> = {
  "mixamorig:Hips": "hips",
  "mixamorig:Spine": "spine",
  "mixamorig:Spine1": "chest",
  "mixamorig:Spine2": "upperChest",
  "mixamorig:Neck": "neck",
  "mixamorig:Head": "head",
  "mixamorig:LeftShoulder": "leftShoulder",
  "mixamorig:LeftArm": "leftUpperArm",
  "mixamorig:LeftForeArm": "leftLowerArm",
  "mixamorig:LeftHand": "leftHand",
  "mixamorig:RightShoulder": "rightShoulder",
  "mixamorig:RightArm": "rightUpperArm",
  "mixamorig:RightForeArm": "rightLowerArm",
  "mixamorig:RightHand": "rightHand",
  "mixamorig:LeftUpLeg": "leftUpperLeg",
  "mixamorig:LeftLeg": "leftLowerLeg",
  "mixamorig:LeftFoot": "leftFoot",
  "mixamorig:LeftToeBase": "leftToes",
  "mixamorig:RightUpLeg": "rightUpperLeg",
  "mixamorig:RightLeg": "rightLowerLeg",
  "mixamorig:RightFoot": "rightFoot",
  "mixamorig:RightToeBase": "rightToes",
};
```

### Section 5: `CrewVRM.tsx` — AnimationMixer integration

Add a `bodyState?: 'idle' | 'talking' | 'listening' | 'thinking'` prop (optional, defaults to 'idle'). New internal state:

- `mixerRef: useRef<THREE.AnimationMixer | null>(null)`.
- `clipsCache: useRef<Map<string, THREE.AnimationClip>>(new Map())`.
- On mount: `GET /api/avatars/animations` → load each available clip via `GLTFLoader` → pass through `retargetMixamoToVRM(clip)` (Section 4b) → store in `clipsCache`.
- On `bodyState` change: cross-fade from current action to target action over ~300 ms.
- `useFrame` ticks the mixer (`mixerRef.current?.update(delta)`).

**Procedural idle fallback preserved:** when `bodyState` is 'idle' AND no idle clip available, current breathing-sway loop runs unchanged.

**Lip-sync precedence:** viseme morph targets continue to override mouth shape regardless of body animation (lip-sync writes to morphTargetInfluences, animation writes to bone transforms — no conflict, but document the precedence in a comment).

### Section 6: Operator fetch script

`scripts/animations-fetch.ps1`:

```powershell
# AD-721e: fetch skeletal animation clips from Quaternius CC0 pack.
# Operator runs this once; clips land in data/avatars/animations/ (gitignored).
# Mirrors scripts/piper-voice-fetch.ps1 and scripts/avatar-assets-fetch.ps1.
```

Add `data/avatars/animations/` to `.gitignore`.

### Section 7: Config

Add to `AvatarsConfig` in `src/probos/config.py`:

```python
animations_dir: str = Field(
    default="data/avatars/animations",
    description="AD-721e: directory of operator-installed CC0/MIT animation clips.",
)
animations_enabled: bool = Field(
    default=False,
    description=(
        "AD-721e: enable AnimationMixer playback in CrewVRM. Default OFF — "
        "operators without animations installed keep the procedural idle "
        "fallback."
    ),
)
```

## Tests

`tests/test_ad721e_animation_manifest.py` (+6 pytest):

1. `register accepts CC0 entry`.
2. `register rejects AGPL entry` (whitelist violation).
3. `get returns None for unknown clip name`.
4. `list_available returns registered names`.
5. `SHA-256 integrity check fails on tampered file`.
6. `GET /api/avatars/animations returns empty list when manifest empty`.

`ui/src/components/profile/__tests__/CrewVRM.animations.test.tsx` (+4 vitest):

7. `loads available clips on mount` — mock GET /api/avatars/animations → assert clip URLs fetched.
8. `cross-fades on bodyState change` — assert mixer.clipAction called for both old + new state.
9. `falls back to procedural idle when no idle clip available` — empty manifest → existing breathing loop runs.
10. `lip-sync precedence preserved` — assert morphTargetInfluences updates unaffected by animation playback.

`ui/src/canvas/animation/__tests__/retarget.test.ts` (+2 vitest, total +12 vitest — update header count if needed):

11. `retargetMixamoToVRM rewrites mixamorig:* track names to VRM Humanoid names` — load fixture clip with `mixamorig:Hips.position`, `mixamorig:LeftArm.quaternion` tracks; assert post-remap track names are `hips.position`, `leftUpperArm.quaternion`; assert keyframe data preserved verbatim.
12. `retargetMixamoToVRM drops tracks with no VRM equivalent` — fixture with `mixamorig:LeftHandIndex3.quaternion` (no VRM finger map) → post-remap track count = input - 1; debug log emitted.

## What this does NOT change

- Lip-sync wiring (AD-721 + AD-738e-1) — bone animation is orthogonal to morphTargetInfluences.
- A-pose fallback at load (`CrewVRM.tsx:115`) — applies before any clip loads.
- Procedural breathing-sway (`CrewVRM.tsx:398`) — runs when `bodyState='idle'` AND no idle clip.
- VRM file format / loader — `@pixiv/three-vrm` already supports `AnimationMixer`.
- No new pip deps. No new npm deps.

## Tracking

- `DECISIONS.md` — append AD-721e shipped entry with license disposition reference.
- `PROGRESS.md` — bump highest-AD line if needed.
- `docs/development/roadmap.md` — mark AD-721e shipped.
- New file: `docs/research/skeletal-animations-license.md`.
- New file: `scripts/animations-fetch.ps1`.
- `.gitignore`: add `data/avatars/animations/`.
- `gh issue close 532 --comment "Shipped Wave 168 (AD-721e). Quaternius CC0 pack via AnimationMixer; Mixamo REJECTED per AD-721i-1 whitelist. See DECISIONS.md."`

## Acceptance Criteria

1. License disposition doc shipped (`docs/research/skeletal-animations-license.md`).
2. `AnimationManifest` class with whitelist enforcement.
3. Two new endpoints (`GET /api/avatars/animations`, `GET /api/avatars/animations/{name}`).
4. `CrewVRM.tsx` AnimationMixer integration with cross-fade.
5. Procedural idle fallback preserved (verified by test 9).
6. Lip-sync precedence preserved (verified by test 10).
7. 6 pytest + 4 vitest pass.
8. `cd ui; npm run build` succeeds.
9. `cd ui; npx vitest run` green.
10. `pytest tests/ -q -n 4 --dist=loadfile` green.
11. Zero new pip / npm deps. Animation files NOT committed to repo (operator-fetched per `.gitignore`).
12. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-17)

```
ls src/probos/avatars/asset_manifest.py
  4831 bytes (extension point)

grep "relaxed A-pose" ui/src/components/profile/CrewVRM.tsx
  line 115: /** Set a relaxed A-pose so VRMs without an animation clip don't ship as

grep "Idle body animation" ui/src/components/profile/CrewVRM.tsx
  line 398: // Idle body animation: breathing + gentle sway. Adds life when no clip exists.

grep "AD-721i-1" DECISIONS.md  # license whitelist parent (Wave 166)

ls scripts/piper-voice-fetch.ps1     # operator-fetch precedent (BF-291)
ls scripts/avatar-assets-fetch.ps1   # operator-fetch precedent (AD-721g Wave 167)
```
