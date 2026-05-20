# AD-705a — Offline STT via whisper.cpp WASM

**Issue:** [#555](https://github.com/seangalliher/ProbOS/issues/555)
**Status:** GATE 1 — drafting (Wave 179).
**Depends on:** AD-721b-3 (model bundle + `whisperLoader.ts` factory + `data/whisper/` path), AD-733c-7 + AD-733c-7-5 (existing `voiceActivity.ts` mic stream + Silero VAD).
**Consumed by:** AD-705c training pipeline (negative-sample augmentation references the loader; no functional coupling).
**Estimated tests:** +5 pytest, +8 vitest.

---

## Problem

AD-705 v1 (Wave 137) shipped the wake-word voice loop using browser-native `SpeechRecognition`. On Chrome this is **cloud-routed to Google** — audio leaves the browser. Captains who want offline / privacy-preserving voice (and operators in jurisdictions with strict data-residency rules) cannot use the existing path safely.

AD-721b-3 lands the whisper.cpp WASM runtime + tiny.en model file as an operator-pulled artifact. AD-705a wires it into the conversation path: when `offline_stt_enabled=true` and the model is present, the VAD-bounded utterance is transcribed locally and the resulting text is dispatched to the existing `agent_chat` endpoint as if the Captain typed it.

The browser-native `SpeechRecognition` path stays as the Tier-2 fallback per AD-705's documented degrade behavior. No regression for Captains who haven't pulled the model.

## Solution

Three browser-side modules + one config knob + one HXI surface:

1. **Extend `ui/src/audio/voiceActivity.ts`** to expose a PCM ring-buffer tap. New `subscribePcm(callback: (frames: Float32Array, sampleRate: number) => void): () => void` returns an unsubscribe handle. Frames flow at the existing 16 kHz / 30 ms cadence the VAD loop already runs. The tap is opt-in — when no subscribers, no buffer is retained (zero overhead). The existing speech-start / speech-end events also fire on the tap so STT can window cleanly.
2. **New `ui/src/audio/whisperStt.ts`** (~180 lines). Subscribes to `voiceActivity.ts` PCM tap when armed; on VAD `speech_start`, opens a Float32 ring buffer; on `speech_end`, calls `whisperLoader.loadWhisperModel()` (memoized — one model instance per session lifetime), invokes `handle.transcribeBuffer(buffer, 16000)`, dispatches the resulting transcript to `IntentSurface` via a new module-level emitter (`onTranscript(callback)` subscription). Honest-degrades when (a) `whisperLoader` returns `null` (model not pulled), (b) `transcribeBuffer` throws or returns empty, (c) `offline_stt_enabled=false` — in any case, falls through to existing `SpeechRecognition` path (no regression).
3. **Modify `ui/src/components/IntentSurface.tsx`** to subscribe to `whisperStt.onTranscript()` and dispatch the transcribed string through the existing `handleSubmit` flow (same path keyboard input takes). Adds a transcript-preview pill while inference is running (HXI Principle #5 progressive disclosure).
4. **Config knob.** New `CognitiveConfig.offline_stt_enabled: bool = False` (default OFF — convention #14 transitional gate; opt-in until model artifact is in place). Hot-reload via existing BF-308 settings watcher (the loop arms/disarms based on the live snapshot).
5. **HXI status badge** in `CameraLiveIndicator.tsx`: tiny `STT` badge alongside the existing SPEECH badge from AD-733c-7-5. States: hidden when `offline_stt_enabled=false`; dim grey when armed but model not loaded; amber when model loaded and listening; pulse-amber when actively transcribing (between speech_end and transcript-ready). Inline SVG only (HXI #3).

### Engaged-mode integration with AD-733c-5

The STT path is orthogonal to the perception mode controller. When AD-705a transcribes a Captain utterance, it does NOT call `note_voice_activity()` directly — that's already firing from `voiceActivity.ts` per AD-733c-7's existing wire. The STT path only emits the transcript; the engagement transition has already happened upstream by the time `transcribeBuffer` resolves.

### Existing `SpeechRecognition` fallback preserved

`wakeWord.ts` continues to run continuous `SpeechRecognition` (which on Chrome is still cloud-routed for transcript text — privacy-conscious operators should also disable the wake-word loop when running with offline STT). The AD-705 toggle is independent. v1: both can run side-by-side. Forward marker `AD-705a-7` for the "fully offline" mode that disables `SpeechRecognition` entirely when `offline_stt_enabled=true`.

## Scope

- Modify `ui/src/audio/voiceActivity.ts` — add `subscribePcm` exporter + ring buffer machinery.
- New `ui/src/audio/whisperStt.ts` (~180 lines).
- Modify `ui/src/components/IntentSurface.tsx` — subscribe to transcript events + transcript-preview pill. Single `replace_string_in_file` per adjacent edit block (BF-274).
- Modify `ui/src/components/perception/CameraLiveIndicator.tsx` — STT badge.
- Modify `src/probos/config.py` — `offline_stt_enabled: bool = False` on `CognitiveConfig`.
- Modify `src/probos/settings/section_registry.py` — one `FieldDescriptor` in LLM Tiers section.
- Modify `THIRD_PARTY_LICENSES.md` — +1 entry for whisper.cpp (MIT) + +1 entry for OpenAI Whisper model weights (MIT).

## NOT in scope

- Replacing `SpeechRecognition`. Stays as Tier-2 fallback. Forward marker `AD-705a-7` for the fully-offline-mode flag.
- Streaming / incremental decode. v1 = batch on VAD-end. Forward marker `AD-705a-4`.
- Multilingual or non-English models. v1 = tiny.en. Forward marker `AD-705a-6` for `tiny`, `base.en`, `base`, etc.
- Server-side Whisper backend (cloud-routed). NEVER — the privacy posture is offline-only.
- Audio multipart upload to the runtime. Audio NEVER leaves the browser. The transcript string crosses the wire; nothing else.
- Persisting the audio buffer to disk. Buffer is discarded after `transcribeBuffer` returns. Forward marker `AD-705a-8` for opt-in transcript audit log (transcript + timestamp, NOT audio).
- Changing the AD-733c-7 endpoint contract.

## Pre-flight grep anchors (Builder MUST verify before locking edits)

1. `ui/src/audio/voiceActivity.ts:38-58` — existing module-level `_state` LoopState. The PCM ring needs to attach here (new fields: `pcmSubscribers: Set<callback>`, `pcmBuffer: Float32Array | null`). Verify the `_processFrame` test seam still passes after the extension.
2. `ui/src/audio/voiceActivity.ts:25-30` — `import { createVadSession, type VadSession } from './silero-vad';` — confirm the dependency chain that `whisperStt.ts` will piggyback on.
3. `ui/src/audio/whisperLoader.ts` — DOES NOT EXIST YET. Lands in AD-721b-3 (Wave 179 build group 1). **Builder MUST verify AD-721b-3 has shipped before this AD builds; if not, file a `RequiresPrior` decision and stop.**
4. `ui/src/components/IntentSurface.tsx` — locate the `handleSubmit` flow (search for `handleSubmit` or `onSubmit`). The transcript event dispatches into the same path keyboard input takes.
5. `ui/src/components/perception/CameraLiveIndicator.tsx` — locate the SPEECH badge added by AD-733c-7-5 (search for `perception-speech-badge`). STT badge sits adjacent.
6. `src/probos/config.py: class CognitiveConfig` — confirm location. Add `offline_stt_enabled: bool = False` after the `whisper_model_path` field landed by AD-721b-3.
7. `src/probos/settings/section_registry.py` — same LLM Tiers section AD-721b-3 added `whisper_model_path` to. Append the `offline_stt_enabled` descriptor below it.
8. `THIRD_PARTY_LICENSES.md` — file tail. Append two new entries (whisper.cpp MIT + Whisper model weights MIT). Mirror the AD-733c-7 Silero VAD entry shape.

## Engineering-principles audit

- **SOLID — DIP.** `whisperStt.ts` depends on `whisperLoader.loadWhisperModel()` (factory) and `voiceActivity.subscribePcm()` (Protocol). Both are seam-able for tests.
- **Defaults preserve current behavior.** `offline_stt_enabled=False` default. ProbOS boots identically.
- **Privacy invariant (AD-733c-7, extended).** Audio bytes NEVER leave the browser. The fetch body in `agent_chat` carries the transcript STRING (same as keyboard input). Regression test asserts no fetch body in `whisperStt.ts` references base64 / pcm / arraybuffer.
- **License posture.** +2 entries in THIRD_PARTY_LICENSES.md (whisper.cpp + Whisper model weights, both MIT). 0-line diff on `pyproject.toml`, `package.json`, `package-lock.json`, `LICENSE`.
- **Hot-reload (BF-308).** `offline_stt_enabled` hot-reload — the loop subscribes to the settings snapshot via `useSettingsStore.subscribe` and arms/disarms accordingly.
- **AD-541b memory integrity.** STT transcripts attach to episodes via the existing `agent_chat` path — same anchor flow as keyboard input. No new episode shape, no bypass.
- **HXI Principle #3 (no emoji).** STT badge = inline SVG mic-with-text-line glyph; amber active, dim idle.
- **HXI Principle #4 (motion).** STT badge: static dim when armed-no-model; static amber when armed-model-ready; pulse during transcription. Static-bright is forbidden (would imply real-time always-on listening signal).
- **HXI Principle #5 (progressive disclosure).** Transcript-preview pill appears between VAD speech_end and transcript dispatch; disappears once dispatched. Hidden entirely when `offline_stt_enabled=false`.
- **HXI Principle #11 (agentic-first).** STT result feeds the same agentic path keyboard input feeds. The "Captain talks, agent acts" loop is the prototypical agentic interaction.
- **AD-738b UI gate.** `cd ui && npx vitest run` + `cd ui && npm run build`.
- **BF-274 single-replace discipline.** Multiple edits to `IntentSurface.tsx` / `CameraLiveIndicator.tsx` use single `replace_string_in_file` per adjacent block.
- **BF-287 (MagicMock at substrate boundary).** Tests stub `fetch` and the `whisperLoader.loadWhisperModel()` seam. Tests do NOT stub `useSettingsStore` — real store.

## Test plan

### pytest (+5 in `tests/test_ad705a_offline_stt_config.py`)

1. `test_offline_stt_enabled_default_false` — `SystemConfig().cognitive.offline_stt_enabled is False`.
2. `test_offline_stt_enabled_field_validates_bool` — assert assigning `"true"` (string) raises a Pydantic validation error.
3. `test_field_descriptor_registered` — `offline_stt_enabled` descriptor present in the LLM Tiers section with `requires_restart=False` (hot-reload-capable).
4. `test_license_file_carries_whisper_cpp_entry` — read `THIRD_PARTY_LICENSES.md`, assert it contains `"whisper.cpp"` AND `"MIT"` adjacent.
5. `test_license_file_carries_whisper_model_entry` — read `THIRD_PARTY_LICENSES.md`, assert it contains `"Whisper"` AND `"OpenAI"` AND `"MIT"` within one section.

### vitest (+8 across `ui/src/audio/__tests__/whisperStt.test.ts` and component test files)

`ui/src/audio/__tests__/whisperStt.test.ts` (+5):
1. `armWhisperStt subscribes to PCM tap when offline_stt_enabled=true` — set snapshot, call `armWhisperStt()`, assert `voiceActivity.subscribePcm` was called.
2. `does NOT arm when offline_stt_enabled=false` — assert no subscription.
3. `transcribes on VAD speech_end and emits transcript` — pump PCM frames + fire speech_end; assert `onTranscript` listener received the stubbed transcript text.
4. `honest-degrades when whisperLoader.loadWhisperModel() returns null` — stub returns null; pump speech_end; assert no transcript emitted; assert no throw.
5. `audio bytes never reach a fetch call` — install a fetch spy; pump frames + speech_end + transcript dispatch through `IntentSurface` integration mock; assert no fetch body contains "base64" / "pcm" / "arraybuffer" / "audio".

`ui/src/audio/__tests__/voiceActivity.pcmTap.test.ts` (+2):
6. `subscribePcm returns an unsubscribe handle that detaches the callback`.
7. `pcm ring buffer is not retained when no subscribers` — assert `_state.pcmBuffer` stays null when no subscribers.

`ui/src/components/perception/__tests__/CameraLiveIndicator.sttBadge.test.tsx` (+1):
8. `STT badge renders amber when offline_stt_enabled and model loaded` — set snapshot + simulate model-loaded state via the loader stub; assert `data-testid="perception-stt-badge"` present and color matches the amber class.

## Tracker updates (at ship time, NOT now)

- `PROGRESS.md` — flip AD-705a line to **SHIPPED** under Wave 179 in-flight block.
- `docs/development/roadmap.md` — flip the AD-705a row (added Wave 179) to **SHIPPED Wave 179**.
- `DECISIONS.md` — append at build time.
- `THIRD_PARTY_LICENSES.md` — +2 entries (whisper.cpp MIT + Whisper model weights MIT).

## Acceptance criteria

1. `ui/src/audio/voiceActivity.ts` exposes `subscribePcm(callback): () => void`; ring buffer is allocated only when subscribers exist.
2. `ui/src/audio/whisperStt.ts` exists; arms on `offline_stt_enabled=true`; transcribes on VAD speech_end via `whisperLoader.loadWhisperModel()`; honest-degrades to no-op when model unavailable.
3. `IntentSurface.tsx` dispatches transcript through the same `handleSubmit` path keyboard input takes.
4. `CameraLiveIndicator.tsx` renders STT badge (hidden / dim / amber / pulse states).
5. `CognitiveConfig.offline_stt_enabled` field added, default `False`.
6. `THIRD_PARTY_LICENSES.md` +2 entries.
7. Privacy regression test passes: no audio bytes in any fetch body.
8. All 5 new pytest + 8 new vitest pass.
9. `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` exits 0; `cd ui && npx vitest run` exits 0; `cd ui && npm run build` exits 0.
10. **Zero diff** on `pyproject.toml`, `package.json`, `package-lock.json`, `LICENSE`.
11. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-19)

```
ui/src/audio/voiceActivity.ts:25-60       (state shape + dependency on silero-vad)
ui/src/audio/silero-vad.ts:31-60          (lazy-loader reference)
ui/src/components/IntentSurface.tsx       (handleSubmit + DM dispatch path; confirm before locking)
ui/src/components/perception/CameraLiveIndicator.tsx  (SPEECH badge from AD-733c-7-5)
src/probos/config.py: CognitiveConfig     (field-add location)
src/probos/settings/section_registry.py   (AD-741 registry; LLM Tiers section is canonical)
THIRD_PARTY_LICENSES.md (tail)            (Silero VAD entry as shape reference)
ui/src/store/useSettingsStore.ts          (snapshot path for offline_stt_enabled — AD-733c-7-5 reads this same path)
```
