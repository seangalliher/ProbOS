# AD-742c-6 — HXI camera multiplexer integration

**Parent AD:** AD-742c (per-agent camera selection — shipped Wave 176 backend-only).
**Issue:** none (forward marker filed in `docs/development/roadmap.md` Wave 176; no GH issue per AD-722c-3 standing rule).
**Status:** GATE 1 — drafting (Wave 177).
**Depends on:** AD-742c backend (`GET /api/perception/cameras`, `POST /api/perception/cameras/binding`, `agent_ids` form field on `/camera/frame`), AD-733c-5-4 (CameraLiveIndicator per-agent badge surface — built first in this wave so the camera-label rendering integrates cleanly).
**Estimated tests:** +4 vitest. Zero new pytest.

---

## Problem

AD-742c (Wave 176) shipped the backend half of per-agent camera selection:

- `GET /api/perception/cameras` returns the persisted `{agent_id: device_id}` map.
- `POST /api/perception/cameras/binding` accepts `{agent_id, device_id}` and persists via `ProfileStore.update`.
- `POST /api/perception/camera/frame` accepts an optional `agent_ids` comma-separated form field that threads `bound_agent_ids` into the consumer's selective fan-out.

But the HXI doesn't enumerate cameras, doesn't render bindings, and doesn't open multiple streams. The operator can't actually drive the feature — they'd have to hand-edit profile JSON or POST to the endpoint with curl.

## Solution

Three browser-side pieces:

1. **`ui/src/store/useCameraMultiplexerStore.ts`** (NEW Zustand slice — SIBLING of `useCameraStore`, not a merger; see cross-AD note). Owns:
   - `bindings: Record<string, string>` — persisted per-agent → device_id map (mirrors backend).
   - `devices: MediaDeviceInfo[]` — enumerated browser-side via `navigator.mediaDevices.enumerateDevices()`.
   - `refresh()` — fetch `/api/perception/cameras` AND `enumerateDevices()` in parallel.
   - `bindAgent(agent_id, device_id)` — POST to `/api/perception/cameras/binding`; on 200 update local state.
   - `clearAgent(agent_id)` — same as `bindAgent` with empty `device_id`.

2. **`ui/src/hooks/useCameraStream.ts`** — extend with multi-deviceId support. Current implementation is a module-singleton (`let _stream: MediaStream | null = null`). The v1 multiplexer EXTENDS this without rewriting: when bindings are non-empty AND distinct from the shared default, the hook maintains a `Map<deviceId, MediaStream>` keyed by device_id. `startCameraStream({deviceId})` accepts a new optional kwarg; the existing zero-arg call preserves legacy single-stream semantics (back-compat). The capture loop iterates active streams and POSTs each frame with the corresponding `agent_ids` form field (computed from the binding map). **NB**: this is a non-trivial refactor of a load-bearing hook; Builder MUST preserve all existing AD-733 / BF-301 / BF-302 / BF-305 invariants (4-corner snap, preview position, force-frame, visibility-change handling).

3. **`ui/src/components/settings/sections/PerceptionLivePanel.tsx`** — add a CAMERA BINDINGS section below the existing MODE block. Renders:
   - A table of `agent_id` → `device_label` rows (one per crew agent with a profile).
   - A select dropdown per row populated from `useCameraMultiplexerStore.devices`.
   - A "clear binding" stroke-X glyph button per row.
   - The block COLLAPSES by default (HXI Principle #5 progressive disclosure) — a `data-testid="perception-camera-bindings-toggle"` button expands it.

## Cross-AD design notes

- **Sibling Zustand slice (not a `useCameraStore` merger).** `useCameraStore` (AD-733) tracks the SINGLE-stream lifecycle (active / framesSent / fps / preview position / indicator corner). `useCameraMultiplexerStore` tracks the MULTIPLE-binding configuration (which agent uses which device). These are orthogonal concerns: the multiplexer state survives stream stop; the stream state cycles with each start/stop. SRP wins over slice reuse. The two stores reference each other through clean exported APIs (e.g. `useCameraStream.startCameraStream({deviceId})` is the integration seam).
- **CameraLiveIndicator integration.** The indicator stays ONE component (per the cross-AD decision baked into Wave 177 dispatch). When multi-stream is active, the indicator gains an additional compact label `CAMS:N` (where N = number of active streams) rather than rendering N indicators. Clicking the label expands an overlay listing each `agent_id → device_label` pair. Single-stream deployments render bit-for-bit identical UI to HEAD.
- **NOT extending `usePerceptionModeStore`.** Per-agent MODE state (AD-733c-5-4) and per-agent camera bindings (this AD) are read from DIFFERENT endpoints (`/api/perception/mode` vs `/api/perception/cameras`) and have different refresh cadences. Separate slices.

## Scope

- New file `ui/src/store/useCameraMultiplexerStore.ts` (~150 lines).
- Modify `ui/src/hooks/useCameraStream.ts` — add `deviceId?: string` kwarg to `startCameraStream`; add a `_streams: Map<string, MediaStream>` module-level map alongside the existing `_stream` for back-compat single-stream path; add `agent_ids` form field threading when bindings present.
- Modify `ui/src/components/perception/CameraLiveIndicator.tsx` — add `CAMS:N` compact label conditional on `_streams.size > 1`. Reuse the existing inline-SVG icon style.
- Modify `ui/src/components/settings/sections/PerceptionLivePanel.tsx` — add the CAMERA BINDINGS section (collapsible). Include a "REFRESH DEVICES" button that calls `useCameraMultiplexerStore.refresh()`.

## NOT in scope

- **Replacing `useCameraStore`.** It stays as the lifecycle store for the indicator/preview UI. Multiplexer is additive.
- **Backend changes.** `GET /cameras` + `POST /cameras/binding` + `agent_ids` form field already exist. Builder MUST NOT touch `src/probos/routers/perception.py`.
- **Screen capture binding** — Forward marker AD-742c-1.
- **Federation cross-host camera sync** — Forward marker AD-742c-2.
- **IP camera RTSP ingestion** — Forward marker AD-742c-3.
- **Audio device per-agent binding** — Forward marker AD-742c-4.
- **Per-agent camera permissions modal** — Forward marker AD-742c-5.
- **Bind-via-agent path** (agent says "bind your camera to me"). HXI v1 ships the dropdown only; agentic path is a future polish (HXI Principle #11 nudge — see audit). The dropdown stays in v1 because the agentic path requires a new intent + tool-permission grant that's out of scope.

## Pre-flight grep anchors (Builder MUST verify before locking edits)

1. `src/probos/routers/perception.py:572` — `@router.get('/cameras', ...)`. Response shape: `{bindings: {agent_id: device_id}}`. **Builder must NOT touch this file.**
2. `src/probos/routers/perception.py:601` — `@router.post('/cameras/binding', ...)`. Request body: `{agent_id, device_id}`. Response: `{ok, agent_id, device_id}`. 404 on unknown agent.
3. `src/probos/routers/perception.py:108-110` — `agent_ids: str = Form("")` field on `/camera/frame`. Confirm. The browser submits a comma-separated list when multiple agents are bound to the same device.
4. `ui/src/hooks/useCameraStream.ts:18-27` — module-singleton state (`_stream`, `_intervalId`, `_video`, `_canvas`, `_sessionId`). Builder must EXTEND not replace.
5. `ui/src/hooks/useCameraStream.ts:115-150` — `startCameraStream` function. New `deviceId?: string` kwarg lands here.
6. `ui/src/hooks/useCameraStream.ts:88-90` — `form.append('file', blob, 'frame.jpg'); form.append('session_id', _sessionId);`. The `agent_ids` field is appended here when bindings present.
7. `ui/src/components/settings/sections/PerceptionLivePanel.tsx:215-232` — closing block of the MODE section. CAMERA BINDINGS section inserts after this.

## Engineering-principles audit

- **HXI Principle #3 (no emoji, inline SVG, amber/dim).** Dropdown rows use mono font + amber/dim color scheme. "Clear binding" X is inline stroke-SVG. "REFRESH DEVICES" button is uppercase mono text + small refresh-arrow SVG icon (stroke 1.5).
- **HXI Principle #4 (motion communicates state).** No new motion in v1 — bindings are configuration, not real-time signal. Forward marker AD-742c-6-1 if a future polish wants a fade-on-unbind animation.
- **HXI Principle #5 (progressive disclosure).** CAMERA BINDINGS section COLLAPSES by default. Single-agent deployments never see the table unless they expand it. Multi-agent deployments where all bindings are empty still see the table only after expanding.
- **HXI Principle #9 (alert-driven layout).** Unbound agents render their row with dim color; bound agents render amber. The eye is drawn to configured bindings naturally.
- **HXI Principle #11 (agentic-first).** v1 ships the dropdown as a workstation pattern. **Audit verdict**: acceptable because the agentic path requires (a) a new intent type for "bind camera to me" and (b) a tool-permission grant for the agent to call `POST /cameras/binding` on its own behalf. Both are out of scope for this prompt. The dropdown is the v1 UX; AD-742c-6-2 (forward marker) covers the agentic-first variant.
- **AD-731 invariant.** Image bytes still flow as SHA refs. `agent_ids` field is a STRING — the regression source-scan from AD-742c already covers `routers/perception.py`. UI-side does not introduce inline bytes; the multipart blob continues to be the JPEG itself.
- **AD-738b UI gate.** Builder MUST run `cd ui && npx vitest run` AND `cd ui && npm run build`.
- **BF-274 single-replace discipline.** The `useCameraStream.ts` refactor is the highest-risk file in this prompt — adjacent module-level state declarations are easy to clobber. Builder uses single `replace_string_in_file` per logical edit; NO `multi_replace_string_in_file` on this file.
- **BF-287 (MagicMock at substrate boundary).** Vitest mocks `fetch` + `navigator.mediaDevices.enumerateDevices` + `getUserMedia` at the network/browser boundary. Does NOT mock the Zustand store internals.

## Test plan (+4 vitest)

New file: `ui/src/store/__tests__/useCameraMultiplexerStore.test.ts`.

1. **`refresh() populates bindings and devices in parallel`** — mock `fetch('/api/perception/cameras')` to return `{bindings: {e1: 'devA', e2: ''}}` and `navigator.mediaDevices.enumerateDevices` to return `[{deviceId: 'devA', label: 'Front Cam'}, {deviceId: 'devB', label: 'Side Cam'}]`. Call `refresh()`. Assert store state matches both sources.
2. **`bindAgent posts to backend and updates local state on 200`** — mock fetch returning `{ok: true, agent_id: 'e1', device_id: 'devB'}`. Call `bindAgent('e1', 'devB')`. Assert POST body parses to `{agent_id: 'e1', device_id: 'devB'}`. Assert local `bindings.e1 === 'devB'`.

New file: `ui/src/components/settings/sections/__tests__/PerceptionLivePanel.cameraBindings.test.tsx`.

3. **`CAMERA BINDINGS section collapsed by default; expands on click`** — mount the panel. Assert `data-testid="perception-camera-bindings-table"` is NOT in the DOM until the toggle is clicked.
4. **`bind dropdown POSTs to /api/perception/cameras/binding`** — seed the multiplexer store with `bindings = {e1: ''}` and `devices = [{deviceId: 'devA', label: 'Cam'}]`. Mount panel, expand bindings, change the dropdown for `e1` to `devA`. Assert `fetch` called with method=POST, URL=`/api/perception/cameras/binding`, body matches `{agent_id: 'e1', device_id: 'devA'}`.

All tests use REAL Zustand stores (no MagicMock at the slice boundary).

## Tracker updates (Builder)

- `PROGRESS.md` — append AD-742c-6 line under the Wave 177 in-flight block.
- `docs/development/roadmap.md` — flip the AD-742c-6 row to `**SHIPPED Wave 177** (CameraMultiplexer Zustand + useCameraStream multi-deviceId + PerceptionLivePanel CAMERA BINDINGS)`.
- `DECISIONS.md` — append at build time.

## Acceptance criteria

1. `useCameraMultiplexerStore` exists as a sibling slice (NOT merged into `useCameraStore`); `refresh()` populates both bindings and devices.
2. `useCameraStream.startCameraStream({deviceId})` opens a stream against the specified device; zero-arg call preserves legacy single-stream behavior.
3. When multiple bindings are active, the capture loop POSTs each frame with the correct `agent_ids` form field.
4. CAMERA BINDINGS table renders one row per crew agent with profile; dropdown populated from `enumerateDevices`; X-button clears the binding.
5. CAMERA BINDINGS section collapses by default (HXI Principle #5).
6. Single-stream deployments render bit-for-bit identical UI to HEAD (back-compat regression test in vitest).
7. All 4 new vitest pass.
8. `cd ui && npx vitest run` exits 0; `cd ui && npm run build` exits 0.
9. Zero diff on `src/probos/`, `tests/`, `pyproject.toml`, `LICENSE`, `THIRD_PARTY_LICENSES.md`, `package.json`, `package-lock.json`.
10. AD-731 invariant preserved — no inline image bytes in any new fetch body; the existing multipart-JPEG path is the only image-byte channel.
11. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md` (especially HXI Principles #3 / #4 / #5 / #11 + AD-738b UI gate + AD-731 ref-not-blob invariant).**
