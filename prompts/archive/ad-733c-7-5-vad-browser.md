# AD-733c-7-5 — HXI Silero VAD browser integration

**Parent AD:** AD-733c-7 (Silero VAD secondary engagement trigger — shipped Wave 176 backend-only).
**Issue:** none (forward marker filed in `docs/development/roadmap.md` Wave 176; no GH issue per AD-722c-3 standing rule).
**Status:** GATE 1 — drafting (Wave 177).
**Depends on:** AD-733c-7 backend (`POST /api/perception/voice-activity` endpoint + `PerceptionConfig.vad_engagement_enabled` flag), AD-733c-5-4 (CameraLiveIndicator per-agent badge surface — built first in this wave so the SPEECH badge can sit alongside MODE badges).
**Estimated tests:** +5 vitest. Zero new pytest.

---

## Problem

AD-733c-7 (Wave 176) shipped the backend half of Silero VAD secondary engagement:

- `POST /api/perception/voice-activity` accepts `{agent?, source: "vad"|"manual"}` JSON and calls `controller.note_voice_activity()` (3s cooldown, step-wise DORMANT→AMBIENT→ENGAGED ramp).
- `PerceptionConfig.vad_engagement_enabled` defaults `False` (Captain explicit opt-in).
- `scripts/silero-vad-fetch.ps1` lets the operator download the ONNX model into `data/silero-vad/`.
- `THIRD_PARTY_LICENSES.md` carries the Silero VAD MIT attribution.

But the browser doesn't tap the mic, run the VAD model, or fire the endpoint. The feature is a hollow tube end-to-end — Captain enables `vad_engagement_enabled=true`, restarts, speaks, and nothing happens.

## Solution

Three browser-side modules:

1. **`ui/src/audio/silero-vad.ts`** — ONNX runtime wrapper. Dynamic-loads `onnxruntime-web` via the same lazy-import pattern as `ui/src/audio/wakeWord.ts:268-289` (indirect string variable so Vite/Vitest don't statically analyze the optional dep). Loads the Silero ONNX model from `/data/silero-vad/silero_vad.onnx` (operator-fetched). Exposes `createVadSession()` returning `{score(buffer: Float32Array): Promise<number>, destroy(): void}`.
2. **`ui/src/audio/voiceActivity.ts`** — mic-tap + chunked detection loop. Opens `navigator.mediaDevices.getUserMedia({audio: true})`, runs an `AudioWorklet` (fallback: `ScriptProcessor`) to chunk 30ms frames at 16 kHz, feeds them to the VAD session, applies the configured debounce floor (`vad_min_speech_duration_ms` — read from settings; defaults to 400ms), and on a confirmed speech event, fires `void fetch('/api/perception/voice-activity', { method: 'POST', body: JSON.stringify({agent, source: 'vad'}) })`. Honest-degrades to a no-op when (a) the endpoint returns 503 (subsystem disabled), (b) the model fails to load (onnxruntime-web absent OR model file missing), (c) `getUserMedia` permission denied.
3. **`ui/src/components/perception/CameraLiveIndicator.tsx`** — SPEECH badge alongside the MODE badge(s). Flashes when a speech event was detected in the last 1.5s; static-dim otherwise. Conditional render: only when `vadEnabled` (read from settings snapshot).

### Mic-tap audio context

**Cross-AD design note.** No existing browser-side raw-audio capture exists in the codebase. `ui/src/audio/wakeWord.ts` uses the browser's `SpeechRecognition` API (transcript-level, not PCM); `ui/src/hooks/useCameraStream.ts` requests `getUserMedia({video: true, audio: false})` — explicit audio:false. The VAD path opens a **new, separate** `getUserMedia({audio: true})` stream. This is not a DRY violation — the two existing audio surfaces operate at fundamentally different abstraction layers (transcript words vs raw PCM). Forward marker AD-733c-7-5-1 if a future feature needs both raw audio and transcripts from a shared mic stream.

### Subscription lifecycle

`voiceActivity.ts` exposes `startVoiceActivity()` / `stopVoiceActivity()`. Mounted/unmounted from `App.tsx` (or the existing top-level mount point that owns `useCameraStream` lifecycle) **conditional on** `snapshot.config.perception.vad_engagement_enabled === true`. When the toggle flips off via settings APPLY, the watcher calls `stopVoiceActivity()` and releases the mic.

## Scope

- New file `ui/src/audio/silero-vad.ts` (~120 lines): lazy-loader, session factory, deterministic test seam exported as `_loadOnnxRuntime` (mirrors wakeWord.ts pattern).
- New file `ui/src/audio/voiceActivity.ts` (~180 lines): mic-tap loop + debounce + endpoint POST + lifecycle exports.
- Modify `ui/src/components/perception/CameraLiveIndicator.tsx`: add `<span data-testid="perception-speech-badge">` next to the existing mode badge area. Flash animation = single short `<animate attributeName="opacity" values="1;0.4;1" dur="1s" repeatCount="1"/>` triggered on each speech event (via React state with timeout reset).
- Modify settings wiring (locate via grep — likely `App.tsx` or a `useEffect`-bearing layout component): mount `startVoiceActivity()` / `stopVoiceActivity()` watcher tied to `snapshot.config.perception.vad_engagement_enabled`.
- Modify `ui/src/store/usePerceptionModeStore.ts` (OR add a sibling slice — Builder picks whichever is cleaner): add a `lastSpeechAt: number | null` field + `noteSpeechEvent()` setter so the badge can subscribe to a single source of truth.

## NOT in scope

- Replacing the wake-word path. AD-733c-7 is a SECONDARY trigger; the wake-word path stays as the primary engagement vector. Forward marker AD-733c-7-4 covers VAD-driven wake-word muting (CPU savings).
- Pre-VAD audio normalization, RNN noise suppression, or any audio pre-processing beyond what Silero requires.
- Multi-mic disambiguation (Forward marker AD-733c-7-2).
- Speaker diarization / "whose voice is it" (Forward marker AD-733c-7-3).
- Backend changes — `POST /api/perception/voice-activity` already exists and routes per-agent. Builder MUST NOT modify `src/probos/routers/perception.py`.
- Storing audio bytes anywhere. Privacy invariant from AD-733c-7: audio NEVER leaves the browser. The POST body carries only `{agent?, source}` metadata. Builder MUST NOT add a multipart audio upload path.
- A `vad_enabled` Zustand persistence layer. The configured value comes from `useSettingsStore.snapshot.config.perception.vad_engagement_enabled` — single source of truth.

## Pre-flight grep anchors (Builder MUST verify before locking edits)

1. `src/probos/routers/perception.py:403` — `@router.post("/voice-activity", ...)` confirmed. Request body shape: `{agent?: string, source: "vad"|"manual"}`. Response shape: `{ok, mode, transitioned, reason, agent_id}`. 503 honest-degrade when `vad_engagement_enabled=false`. **Builder must NOT touch this file.**
2. `src/probos/config.py` — `PerceptionConfig.vad_engagement_enabled: bool = False` + `vad_min_speech_duration_ms: int = 400`. Confirm both fields exist before integrating.
3. `ui/package.json:26` — `"onnxruntime-web": "^1.18.0"` in `optionalDependencies`. **Builder must NOT promote to `dependencies`** (license posture preserved as opt-in browser load).
4. `ui/src/audio/wakeWord.ts:261-289` — `_loadOnnxRuntime` lazy-import pattern. Mirror this exactly: `const moduleName = 'onnxruntime-web'; const _mod = await import(/* @vite-ignore */ moduleName);`. Static `import { InferenceSession } from 'onnxruntime-web'` is FORBIDDEN — first-paint regression for Captains who never enable VAD.
5. `ui/src/components/perception/CameraLiveIndicator.tsx:46-100` — existing mode badge block. SPEECH badge sits adjacent to (not inside) this block.
6. `ui/src/store/useSettingsStore.ts` — confirm `snapshot.config.perception.vad_engagement_enabled` is reachable. If the path is different at HEAD, Builder uses the actual path.
7. `scripts/silero-vad-fetch.ps1` exists at HEAD (shipped Wave 176). Confirms the model file lands at `data/silero-vad/silero_vad.onnx`. The browser fetch path is `/data/silero-vad/silero_vad.onnx` — Builder verifies the static-file route serves `data/` (or documents the alternate path).

## Engineering-principles audit

- **HXI Principle #3 (no emoji, inline SVG, amber/dim).** SPEECH badge uses inline SVG for any glyph (a stroke-only mic-or-soundwave shape). Active color amber `#f0b060`; idle dim `#666680`. Text label `SPK` (3-letter to match the per-agent badge compact format from AD-733c-5-4).
- **HXI Principle #4 (motion communicates state).** Flash on speech detected (amber pulse, 1s decay). Static-dim when no recent speech. Static-bright would be misleading (the runtime can't show real-time mic activity without leaking PCM — flash = "event happened" not "currently listening").
- **HXI Principle #5 (progressive disclosure).** Badge hidden entirely when `vad_engagement_enabled=false`. Operator opts in via settings; the badge only appears after restart.
- **HXI Principle #9 (alert-driven layout).** Speech event is a precondition for engagement; the flash gives the operator a real-time signal that the system heard them.
- **HXI Principle #11 (agentic-first).** N/A for this surface — VAD is a passive trigger feeding the agentic engagement path. The flow remains agentic: Captain speaks → VAD detects → backend transitions per-agent controller → MODE badges update.
- **Privacy invariant (AD-733c-7).** Audio bytes NEVER leave the browser. Tests must include a regression check that the endpoint POST body contains ONLY `{agent?, source}` — assert by string-matching on the captured fetch body in a vitest.
- **License posture.** `onnxruntime-web` already in `optionalDependencies` — 0-line diff. Silero VAD ONNX bytes are operator-pulled; not committed. 0-line license diff expected on all 5 license files.
- **AD-738b UI gate.** Builder MUST run `cd ui && npx vitest run` AND `cd ui && npm run build`.
- **BF-274 single-replace discipline.** TSX edits use single `replace_string_in_file` per adjacent block.
- **BF-287 (MagicMock at substrate boundary).** Tests mock `fetch` (network boundary) and the dynamic ONNX import (via the exported `_loadOnnxRuntime` stub seam). Tests do NOT mock the Zustand store.

## Test plan (+5 vitest)

New file: `ui/src/audio/__tests__/voiceActivity.test.ts`.

1. **`POSTs to /api/perception/voice-activity on speech event`** — stub `_loadOnnxRuntime` to return a fake session that returns score 0.9 on first call. Drive the loop manually (Builder exposes a `_pumpForTest()` seam OR the test imports the internal frame handler). Assert `fetch` called once with method=POST, URL=`/api/perception/voice-activity`, body string contains `"source":"vad"` and does NOT contain `"audio"` or `"buffer"` or `"pcm"` or `"base64"` (privacy regression).
2. **`debounces sub-threshold events`** — score 0.9 fires at t=0, then 0.9 again at t=100ms (under the 400ms `vad_min_speech_duration_ms` floor). Assert `fetch` called ONCE not twice.
3. **`honest-degrades on 503`** — `fetch` mock returns `{status: 503}`. Subsequent score 0.9 events MUST stop firing (or fire at backoff, Builder picks). Loop must not throw, must not console.error.
4. **`releases mic on stopVoiceActivity()`** — install a fake MediaStream with a track-stop spy. Call `startVoiceActivity()` then `stopVoiceActivity()`. Assert track-stop was called.
5. **`CameraLiveIndicator SPEECH badge`** — in `ui/src/components/perception/__tests__/CameraLiveIndicator.speech.test.tsx`: seed `useSettingsStore` snapshot with `vad_engagement_enabled=true`, call `usePerceptionModeStore.getState().noteSpeechEvent()` (or set `lastSpeechAt` directly). Mount the indicator. Assert `data-testid="perception-speech-badge"` is present and has amber color. Advance the clock past the 1.5s flash window (via `vi.useFakeTimers()`) and assert the badge fades to dim.

## Tracker updates (Builder)

- `PROGRESS.md` — append AD-733c-7-5 line under the Wave 177 in-flight block.
- `docs/development/roadmap.md` — flip the AD-733c-7-5 row to `**SHIPPED Wave 177** (browser-side `silero-vad.ts` + `voiceActivity.ts` + CameraLiveIndicator SPEECH badge)`.
- `DECISIONS.md` — append at build time.

## Acceptance criteria

1. `ui/src/audio/silero-vad.ts` exists; lazy-loads `onnxruntime-web` via indirect string variable (mirrors `wakeWord.ts:268-289`).
2. `ui/src/audio/voiceActivity.ts` exists; opens `getUserMedia({audio: true})`, chunks at 30ms / 16 kHz, debounces by `vad_min_speech_duration_ms`, POSTs to `/api/perception/voice-activity`.
3. `CameraLiveIndicator.tsx` renders SPEECH badge conditional on `vad_engagement_enabled`; flashes on speech event; dim when idle.
4. All 5 new vitest pass.
5. Privacy regression test passes: fetch body never contains audio bytes / base64 / buffer / pcm.
6. `cd ui && npx vitest run` exits 0; `cd ui && npm run build` exits 0.
7. No static `import` of `onnxruntime-web` introduced anywhere — first-paint regression-free for Captains with `vad_engagement_enabled=false`.
8. Zero diff on `src/probos/`, `tests/`, `pyproject.toml`, `LICENSE`, `THIRD_PARTY_LICENSES.md`, `package.json`, `package-lock.json`.
9. Mic released on `stopVoiceActivity()` — verified by track-stop spy.
10. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md` (especially HXI Principles #3 / #4 / #5 / #11 + AD-738b UI gate + AD-733c-7 privacy invariant).**
