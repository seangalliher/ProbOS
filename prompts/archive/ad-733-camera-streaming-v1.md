# AD-733 — Camera streaming v1 (frame pipeline + Perception section)

**Status:** Draft (Wave 170)
**Closes:** #641 (parent AD-733 umbrella; AD-733a / AD-733b remain forward markers)
**Dependencies:** AD-741 (Settings panel shell — must land first or in same wave; AD-733 wires the `perception` section into it)
**Estimated tests:** +12 pytest, +5 vitest
**License posture:** 0-line diff. All browser-native APIs (`getUserMedia`, `<canvas>`, `Blob`); 0 new pip / npm deps.

## Problem

The agent fleet has had a vision tier since AD-732 (Wave 153) but no visual sensor stream — vision DMs are paste-only (AD-720 Wave 138 image-paste). Issue #641 calls for a continuous webcam frame pipeline so future ObserverAgents (AD-733b) can react to the Captain's physical environment. The pipeline must be safety-first (instant kill switch, explicit "watching" indicator, default-OFF) and must NOT inline blobs into IntentMessages (AD-731 invariant).

## Solution overview

1. **Server**: new `PerceptionConfig` block on `SystemConfig`; new `vision_observation` IntentDescriptor (non-destructive sensor stream, no consumer in v1 by design); new `POST /api/perception/camera/frame` multipart endpoint that reuses the existing `_validate_and_store_attachment` chain (AD-720a, AD-731 — stores SHA-256-keyed bytes via `AttachmentStore`) and broadcasts an `IntentMessage(intent="vision_observation", params={"attachment_ref": "<sha>", ...})` on the bus. Server-side fps cap rate-limits the endpoint per client session.
2. **HXI**: new `PerceptionSection` rendered under the AD-741 Settings panel — camera enable toggle, fps selector (1/2/4), "Ezri is watching" indicator with instant-revoke kill switch.
3. **Persistent top-bar privacy indicator** (visible from EVERY HXI view when camera is active) — red dot + "CAMERA LIVE" + revoke button. Releases `MediaStream` tracks on revoke, on page hide, and on `beforeunload`.
4. **Anchored episode** on first frame (`AD-541b` reconsolidation guard) — "camera stream began at T+N" so future agents cannot confabulate having seen things before that timestamp.
5. **NO LLM consumer in v1.** The frame is stored, the intent is broadcast, no agent subscribes. This proves the wire shape without committing to inference cadence; AD-733a adds the LLM tick batcher and ObserverAgent in a later wave.

## Architecture decisions

- **No new IntentBus subscriber.** `vision_observation` is registered as an IntentDescriptor (so the decomposer prompt knows about it) but no agent claims it. Per the dynamic intent discovery design, an unconsumed intent is broadcast and dropped — that's exactly the wire shape we want to validate. Audit trail still lands in the journal.
- **`requires_consensus=False`** for `vision_observation` — read-only sensor stream, never destructive. Verify in `IntentDescriptor` shape: `src/probos/types.py:629` confirms `requires_consensus: bool = False` default.
- **AD-731 invariant.** Frame bytes flow through `AttachmentStore.write(sha, blob, "image/jpeg")` only. `IntentMessage.params` carries `{"attachment_ref": "<sha>", "mime": "image/jpeg", "captured_at": <unix>, "source": "camera"}` — never `{"blob_b64": ...}`. Source-scan test asserts this.
- **Server-side fps cap.** `PerceptionConfig.camera_max_fps_server` default 4 (client default 1). Per-session token-bucket on the frame endpoint; 429 + `Retry-After` on overflow. Mirrors AD-270 per-domain rate limiter pattern.
- **Honest-degrade.** Enabling camera with no vision tier configured → frontend surfaces "Vision tier not configured — frames will be stored but no agent will observe them." Reuses `VISION_UNCONFIGURED_MESSAGE` from `src/probos/cognitive/vision_dispatch.py` (BF-274 — one module owns these strings). The endpoint still accepts the frames; it just warns the operator that v1 has no consumer.
- **Privacy indicator placement.** Persistent top-bar component `CameraLiveIndicator` rendered in `App.tsx` at top-level (always visible, every view including Bridge / Ward Room / Settings). When `useStore.cameraStreamActive` is true → red pulsing dot + "CAMERA LIVE" + revoke button. When false → renders nothing (no decoration noise).
- **Stream cleanup contract.** `MediaStream.getTracks().forEach(t => t.stop())` MUST be called on: explicit revoke, fps change, page `visibilitychange` → hidden (pause; resume on visible), `beforeunload`. Test mocks must verify the cleanup happens.
- **Browser memory bound.** Ring buffer NOT needed in v1: each frame is sent immediately via `fetch(POST multipart)` and the `Blob` is freed once GC runs. No client-side retention beyond the in-flight upload.
- **HTTPS requirement.** `getUserMedia` requires a secure context. **localhost is exempt by browser spec** (Chrome / Firefox / Safari all grant `getUserMedia` on `http://localhost:*`). Production deployment on a public hostname will need HTTPS — document explicitly in the section description; surface a banner if `window.location.hostname !== 'localhost' && location.protocol !== 'https:'`.
- **Anchored episode pattern.** On the first successful frame upload per runtime boot, write an episode with `tags=["camera_stream_began", "anchor"]`, importance=0.8 (mirrors Wave 169 image-gen anchor). If episodic store unavailable, log WARNING and continue (Tier-2 honest-degrade).
- **Frame retention.** `AttachmentStore` has no automatic GC of vision-observation-tagged frames. Document this as a known limitation; forward marker AD-733-1 for retention policy.

## Implementation

### Section 1 — `PerceptionConfig`

In `src/probos/config.py`, add a new model alongside `LipSyncConfig` (`config.py:1900`):

```python
class CameraStreamConfig(BaseModel):
    """AD-733: client-side camera streaming controls."""
    enabled: bool = False  # Default-OFF per privacy posture; flipped by operator.
    default_fps: int = Field(default=1, ge=1, le=4,
        description="Client-side capture cadence. Vision tier inference budget caps this; 1 fps is the safe default.")
    frame_jpeg_quality: float = Field(default=0.6, ge=0.2, le=0.95)
    frame_max_dimension: int = Field(default=512, ge=128, le=1024,
        description="Longest-edge downsample target for capture.")

class PerceptionConfig(BaseModel):
    """AD-733: visual sensor input from operator-side capture devices."""
    enabled: bool = False  # Master switch for the entire perception subsystem.
    camera: CameraStreamConfig = Field(default_factory=CameraStreamConfig)
    camera_max_fps_server: int = Field(default=4, ge=1, le=10,
        description="Server-side hard cap on frame ingestion rate per session.")
    frame_max_size_bytes: int = Field(default=512 * 1024, ge=4096, le=5 * 1024 * 1024,
        description="Reject frame uploads larger than this. Default 512 KB.")
```

Wire onto `SystemConfig` (around line 4250, alphabetically with other CrewLayer configs):
```python
perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
```

### Section 2 — `vision_observation` IntentDescriptor

Two parts:

**(a) IntentDescriptor registration.** No new agent is needed — but the decomposer prompt registry expects every intent to have a descriptor. Add a registry-only entry in a new file `src/probos/perception/__init__.py` (mirrors `cloud_pickers/__init__.py`):

```python
"""AD-733: Visual perception subsystem — frame ingestion + episode anchoring."""
from probos.types import IntentDescriptor

VISION_OBSERVATION_DESCRIPTOR = IntentDescriptor(
    name="vision_observation",
    params={
        "attachment_ref": "<sha256>",
        "mime": "image/jpeg",
        "captured_at": "<unix_timestamp>",
        "source": "camera",
    },
    description=(
        "A visual frame captured from an operator-side camera. "
        "AD-731 invariant: bytes are stored in AttachmentStore by SHA-256 — "
        "params['attachment_ref'] holds the SHA. No agent consumes this in v1 "
        "(see AD-733a forward marker)."
    ),
    requires_consensus=False,
    tier="domain",
)
```

**(b) Make sure the registry sees it.** Grep how IntentDescriptors are aggregated for the decomposer's prompt-builder (the agents declare them in `_intent_descriptors()`; standalone descriptors need an explicit registration hook). Add the line:
```python
# in src/probos/runtime.py near where pool _intent_descriptors() are gathered:
from probos.perception import VISION_OBSERVATION_DESCRIPTOR
# append VISION_OBSERVATION_DESCRIPTOR to the descriptors list used to build the prompt.
```
**Verify before drafting:** grep `_intent_descriptors\|all_intent_descriptors` in runtime.py and prompt_builder.py to find the canonical aggregation point. Pattern is per agent today — additive change.

**Collision check.** Grep current intent names: `grep -rE 'IntentDescriptor\(name="' src/probos/agents/` shows no `vision_observation` collision (verified — full agent intent list audited).

### Section 3 — Frame ingestion endpoint

Create `src/probos/routers/perception.py`:

```python
"""AD-733: Camera frame ingestion endpoint."""
from __future__ import annotations
import logging, time
from typing import Any
from fastapi import APIRouter, Depends, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse
from probos.routers.auth import require_crew_scope
from probos.routers._common import get_runtime
from probos.routers.chat import _validate_and_store_attachment
from probos.types import IntentMessage
from probos.perception import VISION_OBSERVATION_DESCRIPTOR  # noqa: F401 — ensures registry import

router = APIRouter(prefix="/api/perception", tags=["perception"])
logger = logging.getLogger(__name__)

# Per-session token bucket (session_id -> (last_refill, tokens)).
_buckets: dict[str, tuple[float, float]] = {}
_ANCHOR_WRITTEN: set[str] = set()  # one anchor per runtime boot, keyed by session_id.

def _check_rate(session_id: str, max_fps: int) -> bool:
    now = time.monotonic()
    last, tokens = _buckets.get(session_id, (now, float(max_fps)))
    elapsed = now - last
    tokens = min(float(max_fps), tokens + elapsed * max_fps)
    if tokens < 1.0:
        _buckets[session_id] = (now, tokens)
        return False
    _buckets[session_id] = (now, tokens - 1.0)
    return True

@router.post("/camera/frame", dependencies=[Depends(require_crew_scope)])
async def upload_camera_frame(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    runtime: Any = Depends(get_runtime),
) -> Any:
    cfg = getattr(runtime.config, "perception", None)
    if cfg is None or not cfg.enabled:
        return JSONResponse(status_code=503, content={"error": "perception_disabled"})
    if not cfg.camera.enabled:
        return JSONResponse(status_code=503, content={"error": "camera_disabled"})

    if not _check_rate(session_id, cfg.camera_max_fps_server):
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited"},
            headers={"Retry-After": "1"},
        )

    blob = await file.read()
    if len(blob) > cfg.frame_max_size_bytes:
        return JSONResponse(status_code=413, content={"error": "frame_too_large"})
    if len(blob) < 12:
        return JSONResponse(status_code=400, content={"error": "frame_too_small"})

    ok, result = await _validate_and_store_attachment(
        runtime, blob, "image/jpeg",
        declared_filename=None, declared_hash_or_None=None,
    )
    if not ok:
        return JSONResponse(status_code=result["status_code"], content=result["body"])

    sha = result["attachment_id"]
    captured_at = time.time()

    # AD-731: refs only on the bus.
    msg = IntentMessage(
        intent="vision_observation",
        params={
            "attachment_ref": sha,
            "mime": "image/jpeg",
            "captured_at": captured_at,
            "source": "camera",
            "session_id": session_id,
        },
    )
    try:
        await runtime.intent_bus.broadcast(msg)
    except Exception as ex:
        # Tier-2 honest-degrade — frame is stored, but no agent sees it.
        logger.warning("AD-733 intent_bus.broadcast failed: %s; frame stored at %s", ex, sha)

    # AD-541b anchored episode on first frame per session per boot.
    if session_id not in _ANCHOR_WRITTEN:
        _ANCHOR_WRITTEN.add(session_id)
        try:
            await runtime.episodic_memory.store(
                content=f"Camera stream began (session={session_id}, sha={sha[:8]})",
                tags=["camera_stream_began", "anchor", "ad733"],
                importance=0.8,
                metadata={"session_id": session_id, "attachment_ref": sha},
            )
        except Exception as ex:
            logger.warning("AD-733 anchor episode store failed: %s", ex)

    return {"ok": True, "attachment_ref": sha, "captured_at": captured_at}
```

**Verify before commit:**
- `runtime.intent_bus.broadcast` signature — grep `intent_bus.broadcast` in tests and existing routers to confirm shape.
- `runtime.episodic_memory.store` signature — grep an existing caller for the canonical kwargs. If the signature differs (e.g. `add_episode` instead of `store`, or different kwarg names), adjust. Pattern from Wave 169 image-gen anchor: `tests/test_ad730_3_*` shows the call shape.
- `_validate_and_store_attachment` return shape — read `routers/chat.py` to confirm `result["attachment_id"]` is the canonical key.

### Section 4 — Register the router

In `src/probos/routers/__init__.py`:
```python
from probos.routers import perception as _perception_router
app.include_router(_perception_router.router)
```

### Section 5 — Add `perception` section to AD-741 registry

In `src/probos/settings/section_registry.py` (created by AD-741), insert in the `SECTIONS` tuple — domain `Crew`:

```python
SectionDescriptor(
    section_id="perception",
    label="Perception",
    glyph="▣",
    domain="Crew",
    wired=True,
    description="Visual sensor input from operator-side capture devices (camera, screen).",
    fields=(
        FieldDescriptor("perception.enabled", "Perception subsystem", "bool"),
        FieldDescriptor("perception.camera.enabled", "Camera streaming", "bool"),
        FieldDescriptor("perception.camera.default_fps", "Frames per second", "int",
            description="1 = safe default. 4 max — vision tier inference cadence is the bottleneck."),
        FieldDescriptor("perception.camera_max_fps_server", "Server fps cap", "int"),
        FieldDescriptor("perception.frame_max_size_bytes", "Max frame size (bytes)", "int"),
    ),
),
```

### Section 6 — HXI Perception section + persistent indicator

Files:
- `ui/src/components/settings/sections/PerceptionSection.tsx` — renders inside AD-741 SettingsMain when `selectedSectionId === "perception"`.
- `ui/src/components/perception/CameraLiveIndicator.tsx` — persistent top-bar component, rendered from `App.tsx` at top level (zIndex above everything else).
- `ui/src/hooks/useCameraStream.ts` — owns `MediaStream`, capture loop, frame upload.
- `ui/src/store/useStore.ts` extension:
  ```ts
  cameraStreamActive: boolean
  cameraSessionId: string | null
  cameraError: string | null
  startCameraStream: () => Promise<void>
  stopCameraStream: () => void
  ```

`useCameraStream` contract:
```ts
// On start:
//   - navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } })
//   - sessionId = crypto.randomUUID()
//   - create offscreen <canvas>, every (1000/fps)ms:
//       drawImage(video) → toBlob('image/jpeg', quality) → fetch(POST /api/perception/camera/frame)
//   - downsample longest-edge to frame_max_dimension
// On stop:
//   - clearInterval
//   - stream.getTracks().forEach(t => t.stop())
//   - cameraStreamActive = false
// Visibilitychange → hidden: pause (clearInterval, keep stream alive).
// Visibilitychange → visible: resume.
// beforeunload: stop() unconditionally.
// 429 response: back off 1s, retry. 413: log error, do not retry the frame.
// 503: stop the stream and surface the error.
```

`PerceptionSection`:
- Render bool toggle for `perception.camera.enabled` AS the master enable (writes to AD-741 settings draft AND triggers immediate `startCameraStream` / `stopCameraStream` even before APPLY — because camera is a live thing, not just config).
- Render fps selector (1 / 2 / 4 buttons; mirrors `system.log_level` enum-button shape).
- Render honest-degrade banner if `cognitive.llm_base_url_vision` is empty: "Vision tier not configured. Frames will be stored, but no agent will observe them. Configure under Cognitive → Vision tier."
- Render HTTPS warning banner if `window.location.protocol !== 'https:' && hostname !== 'localhost'`.
- "Ezri is watching" indicator + revoke button (large, unambiguous).

`CameraLiveIndicator` (rendered from `App.tsx` at top-level):
```tsx
const cameraStreamActive = useStore(s => s.cameraStreamActive)
const stopCameraStream = useStore(s => s.stopCameraStream)
if (!cameraStreamActive) return null
return (
  <div style={{ position: 'fixed', top: 8, right: 8, zIndex: 999,
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '4px 10px', background: 'rgba(180,40,40,0.15)',
                border: '1px solid #c84030', borderRadius: 6 }}>
    <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#e04030',
                   animation: 'pulse 1s infinite' }} />
    <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1, color: '#e0a0a0' }}>CAMERA LIVE</span>
    <button onClick={stopCameraStream}
            style={{ fontSize: 10, padding: '2px 6px', background: 'transparent',
                     border: '1px solid #c84030', color: '#e0a0a0', cursor: 'pointer' }}>
      REVOKE
    </button>
  </div>
)
```

In `App.tsx`, render `<CameraLiveIndicator />` at the top of the return tree, AND add `window.addEventListener('beforeunload', stopCameraStream)` in a top-level `useEffect`.

### Section 7 — Tests

**pytest** (`tests/test_ad733_perception_config.py`, +3):
1. Default `PerceptionConfig()` has `enabled=False` and `camera.enabled=False`.
2. `PerceptionConfig(camera={"default_fps": 99})` raises ValidationError (le=4).
3. `PerceptionConfig(camera_max_fps_server=99)` raises ValidationError (le=10).

**pytest** (`tests/test_ad733_intent_descriptor.py`, +2):
1. `VISION_OBSERVATION_DESCRIPTOR.requires_consensus is False`.
2. `VISION_OBSERVATION_DESCRIPTOR.name == "vision_observation"` and `tier == "domain"`.

**pytest** (`tests/test_ad733_frame_endpoint.py`, +7) — real `SystemConfig()` + real `FilesystemAttachmentStore` per BF-287:
1. POST with `perception.enabled=False` → 503 `perception_disabled`.
2. POST with `camera.enabled=False` → 503 `camera_disabled`.
3. POST with valid frame (small JPEG bytes) → 200 + `attachment_ref` is a 64-char hex string.
4. POST broadcasts `vision_observation` IntentMessage with `attachment_ref` in params and NO inline blob (assert `params` keys ⊆ `{"attachment_ref","mime","captured_at","source","session_id"}`).
5. POST 5x in quick succession with `camera_max_fps_server=2` → at least one 429 with `Retry-After` header.
6. POST with 600 KB blob and `frame_max_size_bytes=512*1024` → 413.
7. **AD-731 source-scan** — assert that `src/probos/routers/perception.py` contains no `b64encode`, no `base64.b64`, no `"blob_b64"`, no `"blob"` in IntentMessage construction (regex grep on file contents).

**vitest** (`ui/src/hooks/__tests__/useCameraStream.test.ts`, +3):
1. `startCameraStream` calls `navigator.mediaDevices.getUserMedia` and sets `cameraStreamActive=true`.
2. `stopCameraStream` calls `track.stop()` on every track returned by `getUserMedia` mock.
3. Frame upload loop POSTs to `/api/perception/camera/frame` with multipart body and `session_id`.

**vitest** (`ui/src/components/perception/__tests__/CameraLiveIndicator.test.tsx`, +2):
1. Renders nothing when `cameraStreamActive=false`.
2. Renders red dot + REVOKE button when `cameraStreamActive=true`; clicking REVOKE calls `stopCameraStream`.

## Tracking

- PROGRESS.md — Wave 170 AD-733 entry.
- DECISIONS.md — AD-733 entry (camera streaming v1; v1 has no LLM consumer by design; AD-731 invariant preserved).
- `docs/development/roadmap.md` — promote AD-733 to "shipped" + retain AD-733a / AD-733b as forward markers.
- Close GitHub issue #641 (parent AD-733).
- File new GitHub issues for AD-733-1 forward marker (AttachmentStore retention policy for vision_observation frames).

## Forward markers (file as GitHub issues)

- **AD-733a** — Fast vision tier (`llm_model_vision_fast`) + 1-Hz working-memory tick batcher + LLM consumer subscribed to `vision_observation`. **Technical trigger:** Captain enables camera and asks "what does Ezri see right now?"
- **AD-733b** — `ObserverAgent` type that proactively surfaces detected events (faces, objects, posture changes) into the bridge alerts stream. **Technical trigger:** AD-733a in place + Captain asks for proactive observation notifications.
- **AD-733-1** — AttachmentStore retention policy for frames tagged `source=camera` — periodic reaper (default: delete frames older than 1 hour, configurable). **Technical trigger:** disk fills up with stored frames after 24h of camera-on time.
- **AD-733-2** — Multi-camera support (front + back, screen capture). **Technical trigger:** operator asks for desktop screen sensing alongside webcam.

## Acceptance criteria

- All tests pass under `pytest tests/test_ad733_*.py -v -n 0` and `cd ui; npx vitest run`.
- Full gate `pytest tests/ -q -n 4 --dist=loadfile` passes with delta ≈ +12 over baseline.
- `cd ui; npm run build` succeeds (BF-279 / AD-738b gate).
- End-to-end smoke: open HXI → Settings → Perception → toggle camera enable → browser permission prompt → CAMERA LIVE indicator appears top-right → frames upload (verify via journal entry for `vision_observation` intent broadcast).
- Clicking REVOKE in the indicator stops the stream within 1s and the browser camera light goes out.
- Closing the browser tab releases the camera (`beforeunload` handler).
- Disabling the camera under Settings → Perception is equivalent to clicking REVOKE.
- AD-731 source-scan test passes — frame upload path has zero inline base64 in IntentMessage params.
- Anchored episode written on first frame; assert via `runtime.episodic_memory` query for `camera_stream_began` tag.
- 0 new pip / npm deps; license posture clean (all browser-native APIs).
- 0 emoji in the new UI files; all glyphs inline stroke SVG per HXI Design Principle #3.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## What this does NOT change

- Does NOT add an LLM consumer for `vision_observation` (AD-733a forward marker).
- Does NOT add an `ObserverAgent` type (AD-733b forward marker).
- Does NOT change the existing AD-720 paste-attachment path.
- Does NOT change the vision tier (`llm_*_vision`) wiring from AD-732.
- Does NOT add screen capture or multi-camera (AD-733-2 forward marker).
- Does NOT add retention-based reaper for stored frames (AD-733-1 forward marker — known issue documented).
- Does NOT add per-frame consent prompts (one-time enable in Settings is the consent gate).

## Verified Against Codebase (2026-05-17)

```
grep -n "vision_observation" src/probos/    # 0 hits — name is free
grep -n "IntentDescriptor" src/probos/agents/   # 18 hits, name collision check passed
grep -n "_validate_and_store_attachment" src/probos/routers/chat.py
  (confirmed; chat.py:719+ defines /chat/attachments and /chat/attachments/multipart
   both delegate to this helper)
grep -n "class LipSyncConfig" src/probos/config.py
  1900: class LipSyncConfig(BaseModel):    # insertion point for PerceptionConfig sibling
grep -n "VISION_UNCONFIGURED_MESSAGE" src/probos/cognitive/vision_dispatch.py
  (confirmed via BF-274 lineage — single source of truth for honest-degrade strings)
grep -n "AD-541b" src/probos/   # anchor pattern in use
grep -n "Content-Security-Policy\|getUserMedia" ui/   # 0 hits — no CSP to fight
grep -n "requires_consensus: bool = False" src/probos/types.py
  629: requires_consensus: bool = False   # default matches AD-733's posture
```
