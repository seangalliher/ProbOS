# WAVE 86 DISPATCH — AD-474 v1 Voice (STT/TTS) — Harden + Hands-Free

**Wave id:** 86
**Umbrella AD:** AD-474 (Voice Interaction — Full Stack STT/TTS)
**OSS sub-AD letters in scope (concrete v1):** AD-474a (vitest backfill for shipped browser TTS + STT modules), AD-474b (continuous-listen mode + auto-restart), AD-474c (`onSpeechEnd` VAD callback for hands-free UX).
**OSS sub-AD letters parked as future ADs (NOT v1 deferrals):** AD-474d (wake-word detection — Porcupine / OpenWakeWord — needs new browser-side WASM model file 1-3 MB + on-device ML loop), AD-474e (`SpeechRecognizer` ABC + Whisper / Deepgram backends — needs new Python deps `openai-whisper` or `deepgram-sdk` + API keys + `/api/voice/transcribe` endpoint), AD-474f (`VoiceProvider` ABC + Piper / FishAudio / ElevenLabs Ship's Computer voice — needs new Python TTS dep + voice training artifacts), AD-474g (macOS menubar PTT — needs Tauri / Electron desktop wrapper, its own AD class), AD-474h (PWA mobile mic permission UX — depends on AD-473e responsive HXI mobile layout, itself parked from Wave 85).
**Closes:** GH issue #68
**HEAD at draft:** `6e46444` (post-Wave-85)
**Baseline test counts:** 11705 pytest (no Python source touched — expected Δ 0); vitest **306** (305 passing + 1 pre-existing `WardRoomDmSync` failure inherited from before Wave 85, **not** introduced by this wave) → expected **≥ 334** vitest (+28 floor; 33 tests planned across three describe groups).
**Builder required:** true (one focused build prompt; UI-only, browser-API-only — zero new deps).
**AD numbering:** Highest stem at HEAD remains **AD-696** (Wave 72). AD-474 pre-allocated by `docs/development/roadmap.md:4207`; sub-AD letters a–h are organizational catalog markers only, mirroring AD-473 a–g (Wave 85) and AD-512 a–f (Wave 84) precedent — no new AD numbers minted.

## Verdict

Verify-first against HEAD `6e46444` reveals the AD-474 **substrate is already shipped and live in the HXI** — but completely untested:

- **TTS substrate live:** `ui/src/audio/voice.ts` (90 LOC) — `speakResponse(text)`, `stopSpeaking()`, `findPreferredVoice()` with Edge neural / Google / Samantha priority cascade, `setPreferredVoiceName()` + localStorage `hxi_voice_name`, `voiceschanged` event handler, `getAvailableVoices()`, `getCurrentVoiceName()`. Wired into `ui/src/components/IntentSurface.tsx:195` (auto-speak responses when `voiceEnabled && response && !response.startsWith('(')`, with markdown stripping). Voice picker UI in `ui/src/components/DecisionSurface.tsx:165-218` (right-click mic toggle, amber-on-dark stroke icons, no emoji — HXI principle #3 compliant).
- **STT substrate live:** `ui/src/audio/speechInput.ts` (78 LOC) — `isSpeechRecognitionSupported()` (vendor-prefix-aware), `startListening(onResult, onEnd?, onError?)`, `stopListening()`, `isListening()`. Configured `continuous: false`, `interimResults: false`, `lang: 'en-US'`. Wired into `IntentSurface.tsx:1467` (mic button gated by capability check, auto-submit-on-result via `setTimeout(form.requestSubmit, 100)`).
- **Store integration live:** `ui/src/store/useStore.ts:300/365/539/1010` — `voiceEnabled: boolean` flag, `setVoiceEnabled(v)` setter, persisted in `localStorage.hxi_voice_enabled`.
- **Zero tests for any of it:** `Test-Path ui/src/__tests__/voice.test.ts` → False. `Test-Path ui/src/__tests__/speechInput.test.ts` → False. `Select-String -Path ui/src/__tests__/*.{ts,tsx} -Pattern 'voice|Voice|speech|Speech'` → 0 hits. Roughly 168 LOC of production-shipping voice code with no regression coverage.

This is the same configuration that warranted Wave 85 framing AD-473 v1 as "ship the substrate, document the consumer" — except Wave 86 inherits an already-shipped substrate that needs **harden + extend**, not "ship from scratch." Captain rule "don't defer unless no choice" is honored by **building everything we can without new deps and locking the existing surface with tests** — every browser-only zero-dep extension ships; only multi-MB ML deps (Porcupine / Whisper / Piper) and new desktop-app substrate (Tauri menubar) get parked with explicit forcing functions:

| Roadmap component (line 4207) | Wave 86 action |
|---|---|
| (1) Speech-to-Text — `SpeechRecognizer` ABC with BrowserSTT, WhisperSTT, DeepgramSTT | **PARTIAL — BUILD continuation.** BrowserSTT layer is live (`speechInput.ts`). v1 hardens it via AD-474a (test backfill — 11 tests covering capability detection, vendor-prefix path, abort-before-start, error filtering, lifecycle). Whisper / Deepgram backends parked as **AD-474e** — they need Python-side `SpeechRecognizer` ABC + new Python deps (`openai-whisper` >100 MB on-device model, or `deepgram-sdk` + API key) + new server-side `/api/voice/transcribe` endpoint + governance through the Intent bus. UI-only wave cannot ship the substrate. |
| (2) Wake word detection — Porcupine / OpenWakeWord for "Computer" activation | **PARKED as AD-474d.** Needs new browser-side WASM model file (1-3 MB Porcupine `.ppn` keyword file or OpenWakeWord ONNX) + audio capture loop + permanent microphone permission grant. Forcing function: AD-474b's continuous-listen mode is the hook point for the wake-word loop in v2 — the loop will `await isWakeWord(audioFrame)` before kicking the existing `startListening()` path. |
| (3) Continuous talk mode — hold-to-talk or VAD for hands-free | **BUILD AD-474b.** Browser-API-only. Extend `startListening()` with an `opts` parameter: `{ continuous?: boolean; interimResults?: boolean; autoRestart?: boolean }`. When `continuous: true`, set `recognition.continuous = true`, fire `onResult` per **final** result, auto-restart on `onend` until `stopListening()` sets a guard flag. Plus AD-474c — `onSpeechEnd` callback exposing `recognition.onspeechend` (browser-native VAD) so the consumer can show "processing…" mid-utterance without polling. ~6 tests for AD-474b, ~4 tests for AD-474c. Zero new deps. |
| (4) Voice pipeline — wake → STT → intent → runtime → response → TTS | **PARTIAL — already wired post-wake-word.** STT → intent → runtime → response → TTS is live (`IntentSurface.tsx:1467` mic submits, `:195` speaks response). The wake-word leg (AD-474d) is the missing prefix; v1 leaves the integration point in place. |
| (5) Platform integration — macOS menubar PTT, browser mic button, PWA mic API | **PARTIAL.** Browser mic button live (`IntentSurface.tsx:1467`). macOS menubar PTT parked as **AD-474g** — needs Tauri / Electron desktop wrapper (its own AD class). PWA mobile mic UX parked as **AD-474h** — depends on AD-473e (responsive HXI mobile layout) which itself was parked from Wave 85. Cascade-park: forcing function is "land AD-473e first." |
| (Bundled) Voice Provider & Ship's Computer Voice — Piper / FishAudio / ElevenLabs | **PARKED as AD-474f.** Roadmap line 4207 bundles this under AD-474. Needs Python-side `VoiceProvider` ABC + at least one new TTS dep (`piper-tts` or `elevenlabs-python`) + voice-cloning artifacts for the LCARS Ship's Computer timbre. UI-only wave cannot ship the substrate. Forcing function: `voice.ts` v1 keeps the `findPreferredVoice()` localStorage cascade — when the Python `VoiceProvider` lands in AD-474f, the UI consumer hits a new `/api/voice/synthesize` endpoint via a new sibling `voiceServer.ts`, leaving `voice.ts`'s browser path as the offline fallback. |

AD-474 v1 (three concrete sub-AD letters + five future-AD letters with explicit forcing functions) is **fully buildable in one wave**. Captain rule "don't defer unless no choice" is honored: every item the substrate had enough information to build, ships in v1; every parked item lists the missing input.

## Reframe decision (Captain rule applied)

**Three concrete sub-AD letters built + five future-AD letters with explicit forcing functions + zero hard-deferrals.** Strictest application of "don't defer unless no choice" available for AD-474 — the entire browser-API-zero-dep slice ships, plus the test backfill that retroactively locks the live behavior and prevents regression.

Five things that LOOK like deferrals but aren't:

1. **Wake-word park is a model-file dependency, not a UI choice.** AD-474d needs a Porcupine `.ppn` keyword model (or OpenWakeWord ONNX) shipped as a 1-3 MB binary asset, plus a permanent-grant microphone audio loop running before `startListening()`. Wedging a wake-word stub into a UI-only wave with no model file would create dead code paths the Captain cannot exercise. v1 ships the **continuous-listen substrate (AD-474b) that AD-474d will hook** — that is the cleanest forcing function available.
2. **Whisper / Deepgram park is a Python-side substrate dependency, not a UI choice.** AD-474e needs the `SpeechRecognizer` ABC + a new Python dep (`openai-whisper` ships >100 MB local model, `deepgram-sdk` ships cloud API client requiring keys) + a new `/api/voice/transcribe` endpoint plumbed through the Intent bus. UI-only wave cannot ship the substrate. The browser-STT path live in `speechInput.ts` becomes the offline fallback when AD-474e ships the cloud path.
3. **Ship's Computer custom voice (AD-474f) park is a Python TTS dep + voice-asset dependency, not a UI choice.** Needs `VoiceProvider` ABC + Piper / FishAudio / ElevenLabs dep + cloned-voice artifacts. The browser `SpeechSynthesis` cascade in `voice.ts` (Edge Online Natural → Google → Samantha) is genuinely the best LCARS-adjacent voice available without server-side TTS — Edge's "Online (Natural)" voices are quite good. Captain can pick a preferred voice via the right-click picker today.
4. **macOS menubar PTT (AD-474g) park is a desktop-app substrate dependency, not a UI choice.** Needs a Tauri or Electron wrapper — its own AD class entirely. Cascade-park.
5. **PWA mobile mic UX (AD-474h) cascades from Wave 85's AD-473e park.** AD-473e (responsive HXI mobile layout) was parked Wave 85 pending Captain UX decisions on chat-vs-canvas-vs-swipe. AD-474h's mic UX (iOS Safari `getUserMedia` permission flow, mobile mic-button placement, hold-to-talk gestures) cannot be designed before the mobile layout is decided. Cascade-park is correct.

GH #68 closure note (drafted; commits with Builder's PR): "Closed by Wave 86 (AD-474 v1 — three concrete OSS sub-AD letters 474a/b/c). Browser TTS + STT substrate already shipping live in HXI is now (a) regression-locked with 20 vitest tests, (b) extended with continuous-listen mode + auto-restart for hands-free voice (AD-474b), and (c) extended with `onSpeechEnd` VAD callback for mid-utterance UX feedback (AD-474c). Components parked as future sub-ADs 474d/e/f/g/h with explicit forcing functions: 474d wake-word (needs Porcupine / OpenWakeWord model file + audio loop — AD-474b's continuous mode is the hook point), 474e `SpeechRecognizer` ABC + Whisper / Deepgram backends (needs Python `openai-whisper` or `deepgram-sdk` dep + `/api/voice/transcribe` endpoint), 474f Ship's Computer custom voice (needs Python `VoiceProvider` ABC + Piper / FishAudio / ElevenLabs dep + voice-clone artifacts), 474g macOS menubar PTT (needs Tauri / Electron desktop wrapper — its own AD class), 474h PWA mobile mic UX (cascades from AD-473e responsive layout, itself parked from Wave 85). Captain rule honored — every browser-only zero-dep extension shipped in v1; only multi-MB ML deps and new desktop substrate parked."

## Commercial-leak audit (pre-commit hook safety)

**Banned-pattern sweep on draft** (`prompts/WAVE-86-DISPATCH.md` + `prompts/ad-474-voice-stt-tts-v1.md`), per `.git/hooks/pre-commit` — all 11 banned patterns confirmed **0 literal hits across both files**. The patterns are referenced via placeholder forms only (the e-word + tier; the private commercial-repo path token; the GTM-pattern phrase; the recurring-revenue acronym; the price/month and price/mo regexes; the revenue-projection phrase; the patterns-to-absorb phrase) so the audit text itself does not trip the hook regex. The Wave 84 / Wave 85 audit precedent is applied verbatim — Captain's request explicitly warned about this self-trip class, again.

- AD-474 umbrella entry on `docs/development/roadmap.md:4207` carries no `*(Commercial)*` tag — verified via `Select-String '\bAD-474\b.*Commercial' docs/development/roadmap.md` returning zero hits. Wave is fully OSS; no boundary disambiguation required.
- "Cloud STT adapter" language in the parked-AD-474e forcing function uses neutral developer phrasing ("API key", "new Python dep", "cloud streaming") — no go-to-market vocabulary.
- AD-474f Ship's Computer custom voice references `ElevenLabs` / `FishAudio` / `Piper` as competing TTS engines (technical neutral); no positioning, no pricing.
- Wave is UI-only with zero pricing surface, zero packaging surface, zero distribution-channel surface — there is genuinely nothing here that would require commercial-boundary discussion even if the substrate had to grow it later.

**Verdict:** clean. Pre-commit hook will not trip on this wave's artifacts.

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  6e46444

# Highest AD stem at HEAD (no new AD minted by this wave):
docs/development/roadmap.md:4207
  "AD-474: Voice Interaction — Full Stack STT/TTS (planned)"
docs/development/roadmap.md:1550
  "Voice Interaction (Full Stack) (AD-474)"
# Wave 85 closure confirmed AD-696 still highest minted; AD-474 pre-allocated.

# Pytest baseline (verified — no Python source touched):
git log -1 --format=%s 6e46444
  "Wave 85 archive: AD-473 mobile PWA (#67)"
# Wave 85 archive note: pytest 11705 post-build.

# Vitest baseline (verified):
cd ui && npx vitest run
  Test Files  1 failed | 17 passed (18)
  Tests       1 failed | 305 passed (306)
  # WardRoomDmSync.test.tsx pre-existing failure — NOT introduced by Wave 85 or 86.

# AD-474 substrate already shipped (verified live):
ui/src/audio/voice.ts:1-90                  # speakResponse, stopSpeaking, findPreferredVoice cascade, voice picker, localStorage hxi_voice_name, voiceschanged handler
ui/src/audio/speechInput.ts:1-78            # isSpeechRecognitionSupported, startListening, stopListening, isListening; continuous=false, interimResults=false, lang=en-US
ui/src/components/IntentSurface.tsx:8       # import { startListening, stopListening, isSpeechRecognitionSupported } from '../audio/speechInput'
ui/src/components/IntentSurface.tsx:195     # voiceEnabled && response → speakResponse(cleanText)
ui/src/components/IntentSurface.tsx:1467    # isSpeechRecognitionSupported() && (<button … startListening …/>)
ui/src/components/DecisionSurface.tsx:19-20 # voiceEnabled, setVoiceEnabled from store
ui/src/components/DecisionSurface.tsx:165   # voice toggle button
ui/src/components/DecisionSurface.tsx:170   # stroke-based amber-on-dark SVG icon, no emoji — HXI principle #3 compliant
ui/src/components/DecisionSurface.tsx:206   # speakResponse('Voice selected') on picker change
ui/src/store/useStore.ts:300                # voiceEnabled: boolean (interface)
ui/src/store/useStore.ts:365                # setVoiceEnabled: (v: boolean) => void (interface)
ui/src/store/useStore.ts:539                # voiceEnabled: false (initial state)
ui/src/store/useStore.ts:1010-1011          # set({ voiceEnabled: v }), localStorage write

# Greenfield (verified absent — no collision):
ui/src/__tests__/voice.test.ts              # absent
ui/src/__tests__/speechInput.test.ts        # absent
# zero existing voice/speech vitest coverage at HEAD

# Test pattern source (vitest + jsdom + @testing-library):
ui/vitest.config.ts:7                       # environment: 'jsdom', globals: true
ui/src/test/setup.ts:1                      # @testing-library/jest-dom global setup
ui/src/__tests__/ComponentRendering.test.tsx:6  # render/screen/fireEvent imports — pattern source
```

## Captain rule honored — full breakdown

| Wave 86 action | Captain rule status |
|---|---|
| AD-474a vitest backfill for live `voice.ts` + `speechInput.ts` (~22 tests) | "don't defer unless no choice" — built |
| AD-474b continuous-listen mode + auto-restart (~7 tests) | "don't defer unless no choice" — built |
| AD-474c `onSpeechEnd` VAD callback (~4 tests) | "don't defer unless no choice" — built |
| Wake-word detection parked → AD-474d | NO CHOICE — needs Porcupine / OpenWakeWord model file (1-3 MB binary) + audio capture loop; AD-474b is its hook point |
| `SpeechRecognizer` ABC + Whisper / Deepgram parked → AD-474e | NO CHOICE — UI-only wave; needs Python dep + API endpoint + governance |
| Custom Ship's Computer voice parked → AD-474f | NO CHOICE — UI-only wave; needs Python `VoiceProvider` ABC + Piper / FishAudio / ElevenLabs dep + voice-clone artifacts |
| macOS menubar PTT parked → AD-474g | NO CHOICE — needs Tauri / Electron desktop wrapper, its own AD class |
| PWA mobile mic UX parked → AD-474h | NO CHOICE — cascades from AD-473e responsive HXI mobile layout (parked Wave 85) |

## What this wave does NOT change

- No Python source touched. `pytest` delta = **0** (target 11705).
- No new Python dependency. `pyproject.toml` untouched.
- No new UI dependency. `ui/package.json` `dependencies` and `devDependencies` untouched. STT and TTS remain browser-native; no Porcupine, no Whisper, no Deepgram, no Piper, no `vite-plugin-*`.
- No edits to `App.tsx`, `CognitiveCanvas.tsx`, `animations.tsx`, `GlassLayer.tsx`, or any HXI canvas surface (HXI design principles preserved verbatim).
- No edits to `DecisionSurface.tsx` voice picker (already HXI-compliant; AD-474a only adds tests; no behavior change).
- No new EventType, agent, pool, Intent, router edit, consensus change, trust scorer touch, episodic store touch.
- No new AD numbers minted (sub-AD letters a-h are organizational only — AD-473 a-g (Wave 85) and AD-512 a-f (Wave 84) precedents).
- No commercial language (AD-474 umbrella is fully OSS — zero `*(Commercial)*` tags on `roadmap.md:4207`; pre-commit hook banned phrases confirmed 0 hits across dispatch, prompt, and this notes block).

## Tracking updates (Builder responsibility, post-build)

- `PROGRESS.md` — bump current pytest count line if changed (expected unchanged at 11705); record Wave 86 closure with vitest count delta in the era progress file.
- `docs/development/roadmap.md:4207` — mark AD-474 with `*(v1 shipped 2026-05-06 — see Wave 86; 474d/e/f/g/h parked with forcing functions)*`.
- No `DECISIONS.md` entry required (no new architectural decision; the substrate was already in place — Wave 86 hardens and extends).
- GH #68 close with the closure note above.

## Builder hand-off

Read `prompts/ad-474-voice-stt-tts-v1.md` for the build spec. One commit. Acceptance: `pytest tests/ -q -n 4 --dist=loadfile` shows 11705, `cd ui && npx vitest run` shows ≥ 334 tests with the 1 pre-existing `WardRoomDmSync` failure unchanged.
