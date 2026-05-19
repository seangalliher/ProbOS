# AD-733-2 — Passive screen sensing (`getDisplayMedia` → `vision_observation` source=screen)

**Status:** Drafted 2026-05-19, GATE 1 pending.
**Closes:** [#668](https://github.com/seangalliher/ProbOS/issues/668) (narrowed scope; multi-camera is already covered by AD-742c per-agent bindings).
**Depends on:** AD-733 (camera frame endpoint), AD-733a (`VisionConsumer`), AD-742c-6 (multiplexer pattern), AD-733-1 (frame retention reaper — adopts `origin="perception_frame"` tagging unchanged).
**Estimated tests:** +12 pytest, +5 vitest.

## Problem

AD-733 v1 (Wave 170) shipped camera frame ingestion with `params.source="camera"` hardcoded. The forward marker AD-733-2 (#668) tracks two extensions; **only screen-sensing is in scope for this AD.** Multi-camera is already shipped via AD-742c per-agent device bindings (Wave 176/177 — `useCameraMultiplexerStore` + `bound_agent_ids`).

Captain wants ambient screen awareness: the agent sees what the operator is looking at on the desktop, throttled by the same supervisor that gates the camera (AD-733a `PerceptualHashStrategy`), with its own kill switch and rate limit.

## Solution overview

1. **Browser side**: new `useScreenStream` hook mirrors `useCameraStream` shape. Calls `navigator.mediaDevices.getDisplayMedia({video: {frameRate: 1}, audio: false})`. Browser surfaces the OS-native monitor/window picker; track-ended handler (operator clicks browser's "Stop sharing" pill) auto-stops the stream.
2. **Multipart POST**: same `POST /api/perception/camera/frame` endpoint with a new optional form field `source: str = "camera"`. The endpoint forwards it into `IntentMessage.params["source"]`. Source-aware rate limiter: separate token bucket per (session_id, source).
3. **HXI**: extends `CameraLiveIndicator.tsx` to also render a `SCREEN LIVE` stroke-SVG indicator when screen sharing is active. Extends `PerceptionLivePanel.tsx` with a new SCREEN SOURCES section (collapsible per HXI #5) mirroring the AD-742c-6 CAMERA BINDINGS pattern. Stroke-based screen icon (rectangle + base + stand, per HXI #3 — no emoji).
4. **Per-source HXI toggle**: new `PerceptionConfig.screen.enabled` (default-OFF) parallels `camera.enabled`. Settings panel exposes both independently.
5. **VisionConsumer routing**: NO change in v1. The existing AD-733a supervisor + working-memory pipeline consumes `vision_observation` regardless of `source` value. `WorkingMemoryEntry` stores `source` so downstream consumers can filter (forward marker AD-733-2-1).

## Scope

- IN: `getDisplayMedia` capture hook; `source` form field on the existing endpoint; `params["source"]="screen"` propagation; separate per-source token bucket; SCREEN LIVE indicator; SCREEN SOURCES section in PerceptionLivePanel; `PerceptionConfig.screen` sub-block.
- IN (consensus posture): `vision_observation` remains `requires_consensus=False`. Screen frames are sensor input, NOT destructive — same posture as camera. No change to `VISION_OBSERVATION_DESCRIPTOR.requires_consensus`.
- IN (AD-731): screen frames flow through `_validate_and_store_attachment` → `AttachmentStore.write(sha, blob, "image/jpeg")` → `params["attachment_ref"]=<sha>`. NEVER inline bytes. Source-scan test rerun on `routers/perception.py` + new code.
- IN (AD-733-1 retention): screen frames adopt `origin="perception_frame"` — already covered by the reaper; no new code needed.
- IN (AD-541b): screen-stream-began anchor episode (`trigger_type="screen_stream_began"`, distinct from `camera_stream_began`).
- OUT: VisionConsumer per-source filter / per-source novelty threshold (forward marker AD-733-2-1).
- OUT: agent-targeted screen binding (`bound_agent_ids` already works via existing form field — no new code).
- OUT: real-time WebRTC track instead of multipart frames (forward marker AD-733-2-2).
- OUT: any action verb on the screen (AD-745 ships that).

## Verification: existing code referenced by this AD

```
Select-String -Path src/probos/perception/__init__.py -Pattern "source.*camera" -SimpleMatch
  29:        "source": "camera",

Select-String -Path src/probos/routers/perception.py -Pattern 'source.*camera|"source":' -SimpleMatch
  165:        "source": "camera",

Select-String -Path src/probos/routers/perception.py -Pattern "_check_rate|_buckets" -SimpleMatch
  34:_buckets: dict[str, tuple[float, float]] = {}
  49:def _check_rate(session_id: str, max_fps: int) -> bool:

Select-String -Path src/probos/perception/consumer.py -Pattern "params.get.*source|\.source" -SimpleMatch
  (none — consumer does not yet read source field; safe to add)

Select-String -Path ui/src/hooks/useCameraStream.ts -Pattern "getUserMedia"
  177:    _stream = await navigator.mediaDevices.getUserMedia({

Select-String -Path ui/src/components/perception/CameraLiveIndicator.tsx -Pattern "CAMERA LIVE"
  (file exists; verify exact label in the prompt; the new SCREEN LIVE indicator
   reuses the same component file with a second indicator row.)

Select-String -Path ui/src/store/useCameraMultiplexerStore.ts -Pattern "bindings"
  17:  bindings: Record<string, string>;
```

## Implementation

### Section 0: Config

`src/probos/config.py` — extend `PerceptionConfig`:

```python
class ScreenStreamConfig(BaseModel):
    """AD-733-2: screen-source sub-block. Defaults match camera.* shape."""
    enabled: bool = False
    default_fps: int = Field(default=1, ge=1, le=4)


class PerceptionConfig(BaseModel):
    # ... existing fields ...
    screen: ScreenStreamConfig = Field(default_factory=ScreenStreamConfig)
    screen_max_fps_server: int = Field(default=2, ge=1, le=4,
        description="AD-733-2: server-side fps cap on screen frames.")
```

Add 2 FieldDescriptors to `src/probos/perception/__init__.py:_PERCEPTION_SECTION.fields`: `perception.screen.enabled` (bool, hot_reload=True) + `perception.screen_max_fps_server` (int, hot_reload=False).

### Section 1: Endpoint

`src/probos/routers/perception.py` — extend `upload_camera_frame`:

```
+    source: str = Form("camera"),
```

Validate against `{"camera", "screen"}` allow-list; reject 400 `invalid_source` on anything else. Replace the current `_buckets` lookup so it keys on `(session_id, source)` instead of `session_id` alone (compatibility: existing camera sessions get the same throughput). Branch on `source`:

- `camera`: existing flow unchanged.
- `screen`: gated on `cfg.screen.enabled` (instead of `cfg.camera.enabled`); rate cap = `cfg.screen_max_fps_server`; episode anchor uses `trigger_type="screen_stream_began"`; intent params `source="screen"` (instead of `"camera"`).

### Section 2: Browser hook

New file `ui/src/hooks/useScreenStream.ts` — mirrors `useCameraStream` shape with two key differences:

1. `getDisplayMedia` instead of `getUserMedia`. Surfaces OS-native picker for free; no monitor enumeration needed in v1.
2. `track.onended` handler auto-stops the stream when the operator clicks the browser's "Stop sharing" pill.

Module-singleton `_screenStream` (separate from `_stream` in `useCameraStream`). Multipart POST appends `source=screen` form field.

### Section 3: HXI

`ui/src/components/perception/CameraLiveIndicator.tsx` — add second indicator row when `useScreenStore.active` is true. Stroke-SVG icon: 16x16 rectangle + base + stand, `strokeWidth: 1.5`, `strokeLinecap: round`. Label: `SCREEN LIVE`. REVOKE button calls `stopScreenStream()`.

`ui/src/components/settings/sections/PerceptionLivePanel.tsx` — add SCREEN SOURCES section between CAMERA BINDINGS and the vision-config warnings. Section contents in v1:

- Master toggle (mirrors camera): START/STOP screen sharing.
- Honest-degrade banner when `perception.screen.enabled === false`.
- HTTPS warning on non-localhost (mirrors camera).

New `ui/src/store/useScreenStore.ts` Zustand slice (sibling of `useCameraStore`, NOT a merger — different lifecycles, SRP wins per AD-742c-6 precedent).

### Section 4: AD-731 invariant regression

`tests/test_ad731_invariant_no_inline_base64_in_perception_modules.py` — extend the existing source-scan to also cover `useScreenStream.ts` indirectly via the router (Python-side scan is the load-bearing one).

### Section 5: Tests

`tests/test_ad733_2_screen_source.py`:
1. POST with `source=screen` succeeds when `screen.enabled=True` → intent broadcast with `params["source"]=="screen"`.
2. POST with `source=screen` returns 503 when `screen.enabled=False` (even if `camera.enabled=True`).
3. POST with `source=invalid` returns 400 `invalid_source`.
4. Per-source rate buckets isolated: rapid screen POSTs do NOT consume the camera token budget.
5. AD-541b anchor written with `trigger_type="screen_stream_began"` on first screen frame per session.
6. AD-731 source-scan rerun (no `b64encode`/`base64.b64` in perception router).
7. `params["bound_agent_ids"]` works on `source=screen` (regression check).
8. Episode importance + source field correctly populated.

`ui/src/hooks/__tests__/useScreenStream.test.ts`:
1. `startScreenStream` calls `getDisplayMedia` once.
2. `track.onended` auto-stops the stream.
3. `stopScreenStream` calls `.stop()` on every track.

`ui/src/components/perception/__tests__/CameraLiveIndicator.test.tsx` — extend:
4. SCREEN LIVE row hidden when `useScreenStore.active === false`.
5. SCREEN LIVE row visible + REVOKE button calls `stopScreenStream` when active.

Total: +8 pytest, +5 vitest. (Spec called for ~12; actual count after BF-287 real-fixture work may land 8-12; the AC is "the eight numbered behaviors covered + AD-731 source-scan unchanged.")

## Acceptance criteria

- All 8 pytest pass with `pytest tests/test_ad733_2_screen_source.py -v -n 0`.
- All 5 vitest pass with `cd ui && npx vitest run` (focused on the new files).
- `cd ui && npm run build` exits 0 (BF-279 stale-bundle gate).
- AD-731 invariant source-scan passes on `routers/perception.py`.
- Existing camera path byte-compatible: `pytest tests/test_ad733_*` passes unchanged.
- Zero new pip deps. Zero new npm deps. 0-line diff on `pyproject.toml`, `package.json`, `package-lock.json`, all 5 license files.
- Forward markers filed with TECHNICAL triggers per AD-722c-3:
  - AD-733-2-1 — VisionConsumer per-source filter (separate novelty threshold per source). Trigger: operator demand after >1 wave of dual-source operation OR Captain reports cross-source novelty noise.
  - AD-733-2-2 — Real-time WebRTC screen track. Trigger: multipart frame rate ≥ 4 fps sustained OR Captain demands sub-second screen-share latency.
- PROGRESS.md Wave 178 block updated post-ship.
- DECISIONS.md: NO entry in this AD (handled at wave close per BUILDER-EXECUTION-PLAN).

## Out-of-scope (explicit)

- AD-745 action verbs on the screen.
- VisionConsumer per-source novelty thresholds.
- WebRTC track ingestion.
- Multi-monitor enumeration in the picker (the browser provides this for free; we don't need to expose it).

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`, especially the consensus + minimal-authority + reversibility requirements for destructive screen-action intents.**
