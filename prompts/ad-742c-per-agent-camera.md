# AD-742c — Per-agent camera selection

**Issue:** [#671](https://github.com/seangalliher/ProbOS/issues/671)
**Status:** GATE 1 — drafting (Wave 176)
**Depends on:** AD-733 (camera streaming v1, Wave 170), AD-733a
(VisionConsumer per-observer registration, Wave 171),
**AD-733c-5 (this wave — ships `CrewProfile.perception`)**,
AD-742d (pluggable supervisor strategies, Wave 175 — confirmed
unaffected; supervisor lives below the camera multiplexer).
**Estimated tests:** +10 pytest, +4 vitest.
**Build order:** MUST land AFTER AD-733c-5 (which introduces
`CrewProfile.perception` block carrying `camera_device_id`).

---

## Problem

AD-733 / AD-733a v1: all agents in the runtime share the same
physical camera; each agent maintains independent working memory but
sees the same frames. Future: per-agent camera selection (Captain's
webcam for Ezri, USB camera 2 for Worf "watch the airlock").

The browser already enumerates cameras via
`navigator.mediaDevices.enumerateDevices()`. The HXI's
`useCameraStream` hook currently picks the default camera. The gap:
binding a `deviceId` per agent + multiplexing capture loops.

## Solution

### `CrewProfile.perception.camera_device_id` (from AD-733c-5)

AD-733c-5 shipped the `PerceptionProfile` dataclass block on
`CrewProfile`. This AD wires `camera_device_id` into the capture
path:

```python
@dataclass
class PerceptionProfile:
    engagement_enabled: bool = True
    initial_mode: str = "ambient"
    camera_device_id: str = ""   # ← AD-742c populates this
```

Empty string = "shared default camera" (current v1 behavior).
Non-empty = bind this agent to the specific browser deviceId.

### Browser side — multiplexed capture

Today: one `useCameraStream` instance owns one MediaStream and
posts every frame as `vision_observation` (no `agent_id` on the
upload because the consumer fans out to ALL registered observers).

Goal: when ≥2 agents have distinct non-empty `camera_device_id`
values, the HXI opens N MediaStreams (one per unique deviceId) and
tags each upload with the binding agent_ids.

- `useCameraStream` refactored from singleton to per-deviceId
  instances managed by a new `CameraMultiplexer` (Zustand slice).
- The multiplexer reads
  `runtime.perception_engagement_registry.current_modes()` +
  per-agent `camera_device_id` (via existing
  `GET /api/perception/engagement` extended to include
  `bindings: {agent_id: device_id}`).
- Upload endpoint extended: `POST /api/perception/camera/frame`
  accepts a new optional `agent_ids` form field (comma-separated)
  carrying the agents that this frame is bound to.
- When `agent_ids` is omitted, the legacy fan-out-to-all behavior
  is preserved (back-compat).

### Backend side — selective fan-out

- `VisionConsumer._handle` (frame consumer, currently fans out to
  `self._observer_agent_ids`) gains an early branch: if the
  intent carries `agent_ids` in params, restrict fan-out to that
  set (intersected with registered observers).
- New `IntentMessage` param key: `bound_agent_ids: list[str]`
  (sibling of existing `attachment_ref`, `mime`, `captured_at`,
  `source`, `session_id`).
- AD-731 invariant preserved — bytes still flow as SHA refs.
- New API endpoint:
  `GET /api/perception/cameras` returns
  `{enumerated: [{device_id, label}], bindings: {agent_id:
  device_id}}` — HXI uses this to render the binding UI in
  Settings → Perception → Camera Bindings.
- New API endpoint:
  `POST /api/perception/cameras/binding {agent_id, device_id}` —
  Captain assigns/changes a binding. Persists to the CrewProfile
  via the existing `ProfileStore.update_profile` path.

### HXI surface

- New section in `PerceptionLivePanel.tsx`: "CAMERA BINDINGS" table
  with one row per crew agent + dropdown of enumerated devices.
- `CameraMultiplexer` opens / closes MediaStreams as the bindings
  change.
- HXI Principle #3: dropdowns use stroke-style chevron SVG, no emoji.

## Cross-AD interaction notes

- **AD-733c-5 dependency is HARD** — Builder MUST verify
  `CrewProfile.perception` block exists at HEAD before starting.
  If AD-733c-5 has not landed, hard-stop.
- **AD-742d supervisor strategies are UNAFFECTED** — per-camera
  frames flow through the same supervisor; the supervisor doesn't
  know or care about agent_id.
- **AD-733c-7 VAD is UNAFFECTED** — voice activity is audio-only.
- **AD-733-2 multi-source camera+screen capture** (forward marker
  shipped Wave 170) is a SIBLING, not a dependency. v1 of this AD
  is camera-only; screen-capture binding is AD-742c-1.

## Scope

- New constant: `BoundAgentIdsType = list[str]` (small alias).
- Modify: `routers/perception.py:104` — `upload_camera_frame`
  accepts optional `agent_ids` form field; threads into
  `IntentMessage.params["bound_agent_ids"]`.
- Modify: `perception/consumer.py:_handle` — early branch on
  `bound_agent_ids`; restrict fan-out.
- New endpoints in `routers/perception.py`:
  `GET /api/perception/cameras`,
  `POST /api/perception/cameras/binding`.
- Modify: `CrewProfile.from_dict` / `to_dict` — already handles
  `perception` block from AD-733c-5; verify `camera_device_id`
  roundtrips.
- New file: `ui/src/store/useCameraMultiplexerStore.ts`.
- Refactor: `ui/src/hooks/useCameraStream.ts` from singleton to
  per-deviceId instance, called by the multiplexer.
- Modify: `ui/src/components/settings/sections/PerceptionLivePanel.tsx`
  — add CAMERA BINDINGS table.
- Modify: `ui/src/components/perception/CameraLiveIndicator.tsx`
  — show N active streams (one badge per unique deviceId).

## NOT in scope

- Screen-capture binding → AD-742c-1 forward marker.
- Federation cross-host camera sync → AD-742c-2 forward marker.
- IP-camera RTSP ingestion → AD-742c-3 forward marker (would need
  server-side capture, fundamentally different shape).
- Audio device per-agent binding → AD-742c-4 forward marker.
- Permissions per agent (e.g. Ezri can see all cameras but Worf
  can only see airlock cam) → AD-742c-5 forward marker.

## Pre-flight grep anchors (Builder MUST verify before locking edits)

1. **HARD DEPENDENCY**: `src/probos/crew_profile.py` —
   `class PerceptionProfile` exists at HEAD with `camera_device_id`
   field. If absent, AD-733c-5 hasn't landed; hard-stop.
2. `src/probos/routers/perception.py:104` —
   `@router.post("/camera/frame"...)` signature. Add optional
   `agent_ids` form field.
3. `src/probos/perception/consumer.py:_handle` — current fan-out
   loop iterates `self._observer_agent_ids`. Add the
   `bound_agent_ids` branch BEFORE the loop.
4. `src/probos/types.py` — `IntentMessage.params: dict[str, Any]`
   accepts arbitrary keys; no schema change needed (verify by grep
   that `params` is `dict[str, Any]`, not a TypedDict).
5. `ui/src/hooks/useCameraStream.ts` — current singleton shape.
6. `src/probos/crew_profile.py:501` — `class ProfileStore` and
   its `update_profile` method (verify exact name).
7. `ui/src/components/settings/sections/PerceptionLivePanel.tsx`
   exists at HEAD.

## Engineering-principles audit

- **SOLID load-bearing**: Open/Closed — extending the existing
  `vision_observation` wire shape with one new optional param key
  (`bound_agent_ids`) without modifying the consumer's core
  fan-out contract.
- **Defaults preserve behavior**: When `camera_device_id == ""` on
  every profile (default for legacy profiles), the multiplexer
  opens ONE stream (default camera) and uploads without
  `agent_ids` — bit-for-bit identical to AD-733a behavior.
- **AD-731 invariant**: Bytes still flow as SHA refs via the
  existing `_validate_and_store_attachment` chain. Source-scan
  test asserts `routers/perception.py` STILL contains no
  `b64encode`. **HARD test required** — adding a new form field is
  the kind of change that tempts inline-bytes; the regression test
  must remain green.
- **AD-541b memory integrity**: Anchored episodes already carry
  `agent_ids` via BF-311 (consumer.py:436). When `bound_agent_ids`
  restricts fan-out, the anchor is written ONLY for those agents
  — correct semantics.
- **Hot-reload posture**:
  - `camera_device_id` per profile → hot-reload via the new
    binding endpoint (multiplexer reacts to the
    `cameras/binding` POST without restart).
  - `useCameraMultiplexerStore` polls bindings every 5s (matches
    AD-742e budget polling cadence).
- **Anti-deadlock**: `_handle` runs on the bus subscriber loop;
  the `bound_agent_ids` branch is a set intersection — pure sync.
- **Async discipline**: Each `useCameraStream` instance owns
  its own `setInterval` capture loop; multiplexer holds Map of
  instances + cleanup on unmount.
- **License posture**: 0-line diff on all 5 license files. All
  browser-native APIs (`MediaDevices`, `MediaStream`); backend
  uses existing FastAPI multipart.
- **Test scaffolding**: real `CrewProfile()` + real
  `FilesystemAttachmentStore` (BF-287). Mock browser via the
  existing `_FakeMediaStream` / `_FakeTrack` stubs (BF-286).
- **HXI Principle #3**: CAMERA BINDINGS table uses stroke-style
  glyphs; no emoji.

## Test plan (+10 pytest, +4 vitest)

`tests/test_ad742c_per_agent_camera.py`:

1. `test_perception_profile_camera_device_id_default_empty` —
   AD-733c-5 default verified.
2. `test_upload_frame_with_agent_ids_threads_bound_agent_ids` —
   form field with `agent_ids="e1,w1"` produces `IntentMessage`
   with `params["bound_agent_ids"] == ["e1", "w1"]`.
3. `test_upload_frame_without_agent_ids_backcompat` — no form
   field → params lacks `bound_agent_ids` key (default fan-out).
4. `test_consumer_fan_out_restricted_by_bound_agent_ids` —
   `_handle` only writes to WM for the bound agents.
5. `test_consumer_fan_out_intersects_with_registered_observers` —
   bound_agent_ids includes an unregistered id → silently
   ignored (Tier-2).
6. `test_anchor_episode_only_for_bound_agents` — verifies
   BF-311 `agent_ids_json` matches the bound set.
7. `test_get_cameras_endpoint_returns_enumerated_and_bindings`.
8. `test_post_camera_binding_persists_to_profile` — POST writes
   to CrewProfile via ProfileStore, GET reflects the change.
9. `test_post_camera_binding_unknown_agent_404`.
10. `test_ad731_invariant_no_inline_base64_in_perception_router` —
    re-runs AD-733 source-scan to guard against regression
    (AD-742c modifies the router, so regression risk is highest
    here).

`ui/src/components/perception/__tests__/CameraMultiplexer.test.tsx`
(+4 vitest):

1. Single binding → one stream opened.
2. Two distinct bindings → two streams opened.
3. Two agents bound to same deviceId → one stream, both agent_ids
   on upload.
4. Binding change → old stream closed, new one opened (cleanup
   verified).

## Tracker updates (Builder)

- `PROGRESS.md` — Wave 176 line.
- `docs/development/roadmap.md` — `AD-742c` row + forward markers
  AD-742c-1 (screen capture), AD-742c-2 (federation),
  AD-742c-3 (RTSP), AD-742c-4 (audio device binding),
  AD-742c-5 (per-agent camera permissions).
- `DECISIONS.md` — at build time.

## Acceptance criteria

1. All legacy profiles (empty `camera_device_id`) → identical
   v1 behavior; one shared camera, fan-out to all observers.
2. Profile with `camera_device_id = "<browser-deviceId>"` → that
   agent's frames originate from that physical device.
3. Two agents with distinct deviceIds → two MediaStreams,
   independent capture loops.
4. Frame upload with `agent_ids` form field → consumer restricts
   fan-out + episodic anchor.
5. Captain can change a binding via the HXI; multiplexer
   reacts within one poll interval (≤5s); no restart required.
6. AD-731 invariant source-scan still green after router
   modification.
7. All 10 pytest + 4 vitest pass.
8. `cd ui && npm run build` exit 0.
9. Zero new pip / npm deps. 0-line diff on all 5 license files.
10. **Verify all changes comply with the Engineering Principles
    in `.github/copilot-instructions.md`.**
