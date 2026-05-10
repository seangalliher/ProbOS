# AD-705 (reframed) — Always-on wake-word voice loop v1

**Status:** READY FOR BUILDER
**Wave:** 137
**Dispatch:** [prompts/WAVE-137-DISPATCH.md](prompts/WAVE-137-DISPATCH.md)
**Depends on:** AD-474 (browser SpeechRecognition wiring), AD-718a (voice proposal infrastructure — only as algorithmic mirror, not modified here), Wave 136 (`onSpeechEvent` lifecycle pub/sub)
**Risk:** **MEDIUM** — net-new client-side state machine + two ONNX bundles + privacy-grade three-state indicator
**Estimated tests:** ~12 Vitest cases, 0 Python (pure UI wave)
**Issue:** [#481](https://github.com/seangalliher/seangalliher/ProbOS/issues/481) (root AD-705 — Builder verifies number at draft-time and updates the link if `#481` does not match the live AD-705 issue)
**Build order:** Ships **first** (commit N). AD-718c (commit N+1) imports the wake-word loop substrate this prompt introduces.

---

## 1. Goal

Implement the **always-on wake-word voice loop** entirely client-side: continuous low-CPU listening, ONNX-detected wake-word fires ("Computer"), VAD-bounded utterance capture, wake-word-aware router (system surface vs `@callsign`), barge-in suppression, and a privacy-grade three-state listening indicator. The Captain explicitly opts in via a default-OFF toggle in `DecisionSurface`.

### Why now (Captain ruling 2026-05-09)

> "Edge Online Natural TTS is quite good — keep it. The killer feature is fluid hands-free conversation with a wake word. Voice stack backends (Whisper / Coqui / Piper / Porcupine) move to forward markers."

Wave 137 reframes AD-705 from "voice-stack backends" to **the wake-word loop**. Backend STT/TTS swaps are firewalled OFF (see Forward markers, §10).

### Privacy boundary (Captain reviews this paragraph)

Audio captured by `getUserMedia()` is consumed in-browser by `onnxruntime-web` for wake-word detection and Silero VAD. **Pre-wake audio NEVER leaves the browser.** Only AFTER a wake-word fires does the existing browser `SpeechRecognition` pipeline activate to transcribe the post-wake utterance — and on some browsers (notably Chrome) that transcription path is cloud-routed by the browser vendor itself. The privacy boundary is the wake word: pre-wake = local-only, post-wake = subject to whatever browser STT does.

---

## 2. Verified Against Codebase (2026-05-09 @ HEAD `31b9e92`)

```
git rev-parse HEAD
  31b9e9278d3a881eb7130966c1d0fb32c6884a2d

# speechInput.ts public API
grep -nE "^export function" ui/src/audio/speechInput.ts
  23: export function isSpeechRecognitionSupported(): boolean {
  49: export function startListening(
  130: export function stopListening(): void {
  139: export function isListening(): boolean {

# voice.ts public API
grep -nE "^export (function|type)" ui/src/audio/voice.ts
  21: export type SpeechEventType = 'start' | 'end' | 'boundary';
  32: export function onSpeechEvent(fn: SpeechListener): () => void {
  96: export function speakResponse(

# voice.ts emits 'start' / 'end' for barge-in subscription
grep -n "'start'\|'end'" ui/src/audio/voice.ts
  142: ...emits 'start'
  143: ...emits 'end'

# useStore.ts toggle slots (DecisionSurface row)
grep -nE "soundEnabled|voiceEnabled|setSoundEnabled|setVoiceEnabled" ui/src/store/useStore.ts
  326: soundEnabled: boolean;
  327: voiceEnabled: boolean;
  405: setSoundEnabled: (v: boolean) => void;
  406: setVoiceEnabled: (v: boolean) => void;
  596: soundEnabled: false,
  597: voiceEnabled: false,
  1134: setSoundEnabled: (v) => {
  1140: setVoiceEnabled: (v) => {

# IntentSurface mic button — extension surface, not replacement
grep -n "isSpeechRecognitionSupported\|startListening" ui/src/components/IntentSurface.tsx
  9:   import { startListening, stopListening, isSpeechRecognitionSupported } from '../audio/speechInput';
  1876: {isSpeechRecognitionSupported() && (
  1885: startListening(

# StaticWakeWordDetector algorithmic reference (Tier-2 fallback mirror)
grep -n "StaticWakeWordDetector\|substring" src/probos/voice/__init__.py
  (verified at HEAD; case-insensitive substring match)

# Models dir does not yet exist — Builder creates ui/public/models/{wake-word,vad}/
Test-Path ui/public/models/  →  False

# Third-party license file does not yet exist — Builder creates THIRD_PARTY_LICENSES.md
Test-Path THIRD_PARTY_LICENSES.md  →  False
```

**Phantom-API false-positives introduced by this prompt** (will appear in pre-check; document in Section 3 as expected):
`startWakeWordLoop`, `stopWakeWordLoop`, `isWakeWordActive`, `getWakeWordState`, `routeWakeTranscript`, `WakeWordIndicator`, `wakeWordEnabled`, `setWakeWordEnabled`.

---

## 3. License posture

OSS Apache-2.0 stays Apache-2.0. New deps are all license-clean.

| Component | License | Adopt? |
|---|---|---|
| `onnxruntime-web` | MIT | **Yes** — D1 |
| openWakeWord stock model (Apache-2.0; e.g. `hey_jarvis_v0.1.onnx` or equivalent — see §4 D1) | Apache-2.0 | **Yes** — D1 |
| Silero VAD ONNX | MIT | **Yes** — D2 |
| WebRTC AEC (`getUserMedia({audio: {echoCancellation, noiseSuppression}})`) | browser-native | **Yes** — implicit; no dep |
| Picovoice Porcupine | non-Apache + AccessKey gate | **REJECTED** — pattern absorption only. AccessKey requirement is incompatible with Apache-2.0 OSS. Hard-stop if introduced. |
| whisper.cpp WASM | MIT | **Defer** to AD-705a (75 MB model, post-v1) |
| Coqui / Piper TTS | mixed (some non-commercial weights) | **Defer** to AD-705b |

**No paid-license deps. No AccessKey-gated services. No model weights with restrictive licenses.**

---

## 4. Scope (v1 only) — Deliverables

### D1. `onnxruntime-web` + stock openWakeWord model (Apache-2.0)

- **File:** `ui/package.json` — add `onnxruntime-web` as a runtime dependency. Pin a recent stable version (Builder picks; record the exact version in the PR description).
- **File:** `ui/public/models/wake-word/<model>.onnx` — bundle one stock community model from openWakeWord. Captain answer Q1 (2026-05-09): **stock model in v1**. Recommended: `hey_jarvis_v0.1.onnx` (closest two-syllable to "Computer"; Captain renames the wake-phrase **label** in the UI but the underlying model is the stock community ONNX). Custom-trained "Computer" model is forward-marker AD-705c.
- **File:** `ui/public/models/wake-word/LICENSE-openwakeword.txt` — Apache-2.0 license text + attribution note ("openWakeWord by David Scripka, https://github.com/dscripka/openWakeWord").
- **Lazy-load constraint (Captain ruling Q5):** the wake-word ONNX bundles MUST NOT load until `wakeWordEnabled === true` for the first time in this session. Use dynamic `await import('onnxruntime-web')` inside `startWakeWordLoop()`, not a top-level static import. First-paint for a Captain who never enables voice MUST NOT be impacted.

### D2. Silero VAD ONNX (MIT)

- **File:** `ui/public/models/vad/silero_vad.onnx` — bundle the small (~1.8 MB) Silero VAD model.
- **File:** `ui/public/models/vad/LICENSE-silero.txt` — MIT license text + attribution ("Silero VAD by Silero Team, https://github.com/snakers4/silero-vad").
- Same lazy-load constraint as D1.

### D3. `ui/src/audio/wakeWord.ts` — pure module (NEW FILE)

Public exports:

```ts
// State machine state. Single source of truth for D7 indicator.
export type WakeWordState = 'off' | 'armed' | 'capturing' | 'fallback-armed' | 'fallback-capturing';

export interface StartWakeWordLoopOptions {
  // Bumps non-empty per-agent wake phrases registered as additional triggers
  // (consumed by AD-718c, ignored in AD-705 v1).
  agentTriggers?: ReadonlyArray<{ callsign: string; phrase: string }>;
  // Captain-toggle abort handle.
  signal?: AbortSignal;
}

export async function startWakeWordLoop(
  onWake: (routed: WakeRoute) => void,
  opts?: StartWakeWordLoopOptions,
): Promise<void>;

export function stopWakeWordLoop(): void;

export function isWakeWordActive(): boolean;

export function getWakeWordState(): WakeWordState;

// Subscribe to state-machine transitions. Returns unsubscribe fn.
export function onWakeWordState(fn: (state: WakeWordState, detail?: WakeWordStateDetail) => void): () => void;

export interface WakeWordStateDetail {
  // For 'fallback-*' states: the reason the loop dropped to fallback.
  fallbackReason?: 'onnx_load_failed' | 'mic_permission_denied' | 'speech_recognition_unavailable';
  // For 'capturing' states: which trigger fired ('Computer' / per-agent callsign).
  trigger?: string;
}
```

**State machine:**

```
off ──startWakeWordLoop──▶ armed ──ONNX wake fires──▶ capturing ──VAD silence ≥ SILENCE_TIMEOUT_MS──▶ submit ──▶ armed
                          │                                       │                                                ▲
                          │                                       └──MAX_DURATION reached──▶ submit ──┘
                          │                                                                          │
                          └──Escape pressed during capturing──▶ cancel ──▶ armed ◀─────────────────┘
                          │
                          └──Escape pressed during armed──▶ off (toggle off)
                          │
                          └──ONNX load fails──▶ fallback-armed (continuous SpeechRecognition + substring match)
```

**Configurable compile-time constants** (drafter pinned values; Captain reviews):

```ts
const WAKE_WORD_THRESHOLD = 0.5;            // ONNX confidence threshold
const UTTERANCE_MAX_DURATION_MS = 10000;    // hard ceiling on capture window
const SILENCE_TIMEOUT_MS = 1500;            // VAD silence → commit utterance
const STATIC_WAKE_PHRASES = ['computer'];   // fallback substring match (case-insensitive)
const FALLBACK_TOAST_DEBOUNCE_MS = 8000;    // suppress duplicate fallback toasts
const PERAGENT_TRIGGER_DEBOUNCE_MS = 500;   // re-collection of agent wake phrases
```

**Tier-2 fallbacks (log-and-degrade, principles tier #2):**

| Failure | Fallback | State exposed |
|---|---|---|
| `onnxruntime-web` import fails | continuous browser `SpeechRecognition` + case-insensitive substring match against `STATIC_WAKE_PHRASES` | `fallback-armed` / `fallback-capturing` |
| `getUserMedia` permission denied | loop disables itself; emits `state='off'` with `fallbackReason='mic_permission_denied'` | `off` (with reason) |
| `isSpeechRecognitionSupported() === false` | loop disables itself even if ONNX loads (no transcription path) | `off` (with reason) |

**Hard requirement:** the loop MUST hold a reference to its inference task and abort cleanly on `stopWakeWordLoop()`. No fire-and-forget. Use `AbortController` internally; expose `signal` option for external abort wiring.

### D4. Wake-word-aware router (pure function, inside `wakeWord.ts` OR sibling `wakeWord.router.ts` — Builder picks)

```ts
export interface WakeRoute {
  surface: 'system' | 'agent';
  agentCallsign?: string;     // present iff surface === 'agent'
  cleanedText: string;        // transcript with the wake-prefix stripped
}

export function routeWakeTranscript(
  transcript: string,
  agents: ReadonlyMap<string, { callsign?: string; voice_profile?: { wake_phrase?: string } }>,
): WakeRoute | null;  // null === unaddressed; discard
```

**Routing rules** (drafter pinned; Builder writes test cases for each):

1. Case-insensitive prefix match. Optional leading filler ("hey", "ok") permitted before the wake.
2. **System wake**: transcript starts with `Computer` (or `STATIC_WAKE_PHRASES[i]`). `surface = 'system'`, `cleanedText = transcript.replace(/^(\s*(hey|ok)?\s*computer[,:\s]+)/i, '')`.
3. **Per-agent wake (AD-718c provides the data; v1 honors empty Map)**: transcript starts with an agent's `callsign` OR (post-AD-718c) `voice_profile.wake_phrase`. `surface = 'agent'`, `agentCallsign = <matched callsign>`, `cleanedText` = remainder with prefix stripped.
4. **Bare transcript (no recognized prefix) AND no preceding wake-word fire**: return `null` (discard — not addressed to anyone). NOTE: if the wake-word ONNX already fired, the transcript IS post-wake and ALWAYS routes to `system` even with no prefix, because the wake-word itself is the addressing.
5. **Ambiguous prefix** (e.g. transcript starts with both "Computer" and an agent callsign — implausible but defensive): system wake wins.

Pure function. No DOM, no fetch, no state. Testable in isolation.

### D5. Mode toggle in `DecisionSurface.tsx`

- Extend the toggle row at `ui/src/components/DecisionSurface.tsx:17-24`.
- Add `wakeWordEnabled: boolean` and `setWakeWordEnabled: (v: boolean) => void` to `useStore` mirroring `voiceEnabled` / `setVoiceEnabled` (`ui/src/store/useStore.ts:326-327, 405-406, 596-597, 1134-1141`).
- **Default OFF.** Persisted via the same localStorage hydration pattern as `voiceEnabled`.
- Inline-SVG icon (`strokeWidth: 1.5`, `strokeLinecap: round`, active `#f0b060`, inactive `#666680`). **No emoji.**
- On toggle ON: call `startWakeWordLoop(...)` once. On toggle OFF: call `stopWakeWordLoop()`.
- Single owner of loop lifecycle: `IntentSurface.tsx`'s top-level `useEffect` keyed on `wakeWordEnabled` (Builder picks the exact mount point, but only ONE component owns the lifecycle to prevent multi-loop leaks across remounts).

### D6. Barge-in suppression

Inside `wakeWord.ts`, subscribe **once** at module init via `onSpeechEvent`:

- On `'start'`: set internal flag `bargedIn = true`. Drop all transcript segments and skip ONNX inference frames while flag is set. **Do not** abort the underlying `startListening` (it's continuous).
- On `'end'`: clear flag. Resume ingestion.
- Unsubscribe on `stopWakeWordLoop()` to prevent leaks.

This is **belt-and-suspenders** on top of browser-native AEC. Test: emit synthetic `'start'`, push transcript, assert dropped; emit `'end'`, push transcript, assert accepted.

### D7. Listening indicator (HXI Design Principle #4 — non-negotiable)

New component `ui/src/components/WakeWordIndicator.tsx`. Rendered from `IntentSurface.tsx` in the **bottom-right corner**, above the input bar, ~16 px diameter, offset from the existing mic icon (Captain answer Q3, 2026-05-09).

**Three visual states (the indicator MUST distinguish all three):**

| State | Visual | Motion (HXI #4) |
|---|---|---|
| `off` (and any `fallback`-state with `fallbackReason='mic_permission_denied'` / `speech_recognition_unavailable`) | dim dot `#666680`, no glow | none |
| `armed` (or `fallback-armed`) | amber stroke `#f0b060`, low glow | slow breathing pulse, **~2 s period** |
| `capturing` (or `fallback-capturing`) | amber stroke `#f0b060`, high glow | faster pulse, **~0.5 s period** |

**Fallback-mode visible status (Captain answer Q6, 2026-05-09):** when `getWakeWordState()` is in any `fallback-*` state OR the loop is OFF due to a load failure, render a one-line text label next to the dot reading **"Voice unavailable: <reason>"** (reasons: `"ONNX runtime failed to load"`, `"Microphone permission denied"`, `"Speech recognition not supported"`). Text color `#aaaabb`, font-size 11 px, no emoji, stroke-SVG-only icons. The Captain MUST see why voice didn't work.

**Inline SVG only.** No emoji literals. Reviewer fails any emoji codepoint in the diff.

### D8. Escape-key handling (Captain answer Q2, 2026-05-09)

- **During `capturing` / `fallback-capturing`:** Escape **cancels the current utterance** (does not submit) and returns to `armed` / `fallback-armed`. Nothing posts to `/api/chat`.
- **During `armed` / `fallback-armed`:** Escape **toggles the entire loop OFF** (calls `setWakeWordEnabled(false)` → `stopWakeWordLoop()`).
- **During `off`:** no effect.

Reuses the same Escape-handler pattern as the `@`-picker in `IntentSurface.tsx` (Builder greps the picker's escape handler, mirrors the `KeyboardEvent` → `e.key === 'Escape'` pattern).

### D9. Wiring (single owner)

`startWakeWordLoop(...)` is invoked from a single `useEffect` in `IntentSurface.tsx` keyed on `wakeWordEnabled`. On mount with flag OFF: nothing runs. On toggle ON at runtime: start. On toggle OFF or unmount: stop. Drafter picks the exact mount point; reviewer flags any duplicate mount.

The `onWake` callback in this single owner posts the routed transcript through the existing `POST /api/chat` path. Nothing else changes about how chat submission works.

---

## 5. Tests required (Vitest, ≥ 12 cases)

New test files (Builder mocks `onnxruntime-web` in all of these):

### `ui/src/__tests__/wakeWord.stateMachine.test.ts` (≥ 5 cases)

1. `startWakeWordLoop` transitions `off → armed`.
2. Synthetic ONNX wake-fire transitions `armed → capturing`.
3. VAD silence ≥ `SILENCE_TIMEOUT_MS` transitions `capturing → submit → armed` and invokes `onWake` with the routed transcript.
4. `MAX_DURATION` reached transitions `capturing → submit → armed`.
5. `stopWakeWordLoop` transitions any-state → `off`.

### `ui/src/__tests__/wakeWord.router.test.ts` (≥ 4 cases)

6. `"Computer, what's the load?"` → `surface='system'`, `cleanedText="what's the load?"`.
7. `"Hey Ezri, run a scan"` with agents map containing `Ezri` callsign → `surface='agent'`, `agentCallsign='Ezri'`, `cleanedText="run a scan"`.
8. `"random words with no prefix"` post-no-wake → `null`.
9. `"random words with no prefix"` post-wake-fired → `surface='system'` (wake-word IS the addressing).

### `ui/src/__tests__/wakeWord.bargeIn.test.ts` (≥ 2 cases)

10. Emit `onSpeechEvent('start')`, push transcript, assert dropped.
11. Emit `onSpeechEvent('end')`, push transcript, assert accepted.

### `ui/src/__tests__/wakeWord.fallback.test.ts` (≥ 2 cases)

12. Mock `onnxruntime-web` import to throw → assert state transitions to `fallback-armed` and `STATIC_WAKE_PHRASES` substring match drives `fallback-capturing`.
13. Mock `getUserMedia` to reject with `NotAllowedError` → assert state transitions to `off` with `fallbackReason='mic_permission_denied'`.

### `ui/src/__tests__/wakeWord.escape.test.ts` (≥ 2 cases)

14. Escape during `capturing` cancels utterance, no `onWake` invocation, returns to `armed`.
15. Escape during `armed` toggles loop OFF.

### `ui/src/__tests__/WakeWordIndicator.test.tsx` (≥ 3 cases)

16. State `off` → dim dot, no animation, no fallback text.
17. State `armed` → amber stroke, breathing pulse class applied.
18. State `fallback-armed` with `fallbackReason='onnx_load_failed'` → amber dot + visible "Voice unavailable: ONNX runtime failed to load" label.

### `ui/src/__tests__/DecisionSurface.wakeWordToggle.test.tsx` (≥ 2 cases)

19. Toggle persists across remount (localStorage round-trip).
20. Default value is `false`.

### `ui/src/__tests__/wakeWord.lazyLoad.test.ts` (≥ 1 case)

21. Module top-level static analysis: `import('onnxruntime-web')` does NOT appear as a top-level static import (regex test against the module source string OR Vitest spy on `import.meta` resolution timing).

(Total ≥ 21; **dispatch §3 and §9 require ≥ 12**, this exceeds floor with margin.)

---

## 6. What this does NOT change (out of scope — hard fences)

- `ui/src/audio/speechInput.ts` public API. **No changes.** Reviewer fails any signature change.
- `ui/src/audio/voice.ts`'s `speakResponse` signature OR the `onSpeechEvent` lifecycle. **No changes.** Subscribe only.
- The IntentSurface click-to-talk mic button (`IntentSurface.tsx:1876-1916`) stays. Wake-word loop is a SEPARATE state machine; the two modes coexist (Builder verifies they don't fire `startListening` over each other — recommended: when `wakeWordEnabled === true`, the click-to-talk button becomes a "force-listen now" override that bypasses wake-word arming for that single utterance).
- Server-side: ZERO new endpoints, ZERO new Pydantic models, ZERO new SQLite tables. No `wave-plan.yaml` change in this prompt.
- `BaseAgent` / `IntentMessage` protocols. Untouched.
- `useStore.agents: Map<string, Agent>` shape. Untouched in this prompt (AD-718c E1 introduces `wake_phrase` on `voice_profile` next).
- TTS path. Edge Online Natural stays. Any change to `voice.ts`'s synthesis path is a HARD STOP.

---

## 7. Hard-stop conditions (verbatim from dispatch §8)

Builder MUST stop and surface to Architect if any of the following occur:

1. **Phantom API.** A grep at HEAD returns zero matches AND the prompt does not introduce it. False-positives introduced by THIS prompt (expected, document in commit message): `startWakeWordLoop`, `stopWakeWordLoop`, `isWakeWordActive`, `getWakeWordState`, `onWakeWordState`, `routeWakeTranscript`, `WakeWordIndicator`, `wakeWordEnabled`, `setWakeWordEnabled`. ALL nine are introduced by D3/D4/D5/D7; flagging them as missing is a false positive.
2. **Architectural contract change required.** Any change to `speechInput.ts`'s public API, `voice.ts`'s `speakResponse` signature, `useStore`'s Agent type, or `BaseAgent`/`IntentMessage` is a HARD STOP.
3. **Working tree integrity.** Pre-flight `git diff --numstat | sort -k2nr | head -5`. Any tracked file with > 200 lines deleted that the Builder did not author is a stop-the-line event (per user-memory note 2026-05-08).
4. **License creep.** Any new third-party dep beyond `onnxruntime-web` (MIT), the openWakeWord stock model (Apache-2.0), and Silero VAD ONNX (MIT) is a HARD STOP. **No Porcupine. No paid-license deps. No AccessKey deps.**
5. **Emoji in diff.** Any emoji literal in `*.tsx` / `*.ts` / `*.py` of the diff is a HARD STOP. HXI Design Principle #3.
6. **TTS replacement.** Any change to `voice.ts` that replaces `speechSynthesis.speak(...)` with anything else is a HARD STOP. Captain ruling: TTS is unchanged in v1.
7. **Default-on toggle.** If `wakeWordEnabled` defaults to `true`, HARD STOP. Captain explicitly opts in.
8. **Audio leaks server-side before wake-word.** Any code path that uploads pre-wake audio to any server (even ours) is a HARD STOP. The privacy boundary is the wake word.
9. **Indicator missing or visually conflated.** If the listening indicator does not distinguish `off` / `armed` / `capturing` (and their `fallback-*` mirrors) with three visually-distinct states, HARD STOP. HXI Design Principle #4.
10. **Eager bundle load.** If `onnxruntime-web` or any wake-word/VAD ONNX is statically imported at module top-level (not inside a dynamic `await import(...)` gated by `wakeWordEnabled`), HARD STOP. Captain answer Q5: lazy-load is non-negotiable; first-paint must not regress for Captains who never enable voice.
11. **`exec` / `eval` / `compile` / `pickle.loads` on transcript or wake-phrase.** HARD STOP.
12. **Test gate failure under `-n 0` after passing under `-n 16`.** Order-dependent test pollution → quarantine via BF entry pointing at AD-682, do NOT block the wave.

---

## 8. Acceptance criteria

Builder MUST:

1. Run `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-705-wake-word-voice-loop-v1.md` and document the nine expected false-positives in §7 above.
2. Pass UI test gate: `cd ui && npx vitest run` — adds ≥ 21 Vitest cases. ALL pass.
3. Pass Python full gate: `pytest tests/ -q -n 16 --dist=loadfile` (fall back to `-n 8` per BUILDER-EXECUTION-PLAN.md). No new Python tests expected; baseline must remain green.
4. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
5. Bundle delta ≤ 12 MB compressed in the production build (Captain answer Q5: 5–10 MB acceptable; ≤ 12 MB tolerance for Builder picking the largest-but-stock community model). Document the actual delta in the PR description (`npm run build` then `du -sh ui/dist`).
6. **Lazy-load verified:** the production bundle's main entry chunk MUST NOT contain `onnxruntime-web` symbols. Verify via `grep -l "onnxruntime" ui/dist/assets/*.js` — only the dynamically-imported chunk should match. Document in PR.
7. License attribution committed: `ui/public/models/wake-word/LICENSE-openwakeword.txt` (Apache-2.0) AND `ui/public/models/vad/LICENSE-silero.txt` (MIT) AND a top-level `THIRD_PARTY_LICENSES.md` listing both. (Top-level file is NEW; does not exist at HEAD.)
8. PROGRESS.md: highest AD unchanged (AD-721i stays; AD-705 is reframed, not new). Add a one-line entry in the current era's progress file noting AD-705 (reframed) shipped.
9. `decisions-era-4-evolution.md` (or current era — Builder verifies which era is active at HEAD) appended with an AD-705 (reframed) entry citing this prompt + the wave dispatch.
10. `docs/development/roadmap.md` Bug Tracker — no new BF entries expected on the happy path.
11. Issue [#481](https://github.com/seangalliher/seangalliher/ProbOS/issues/481) (root AD-705) closed via merge commit message **only if the issue number is verified to be AD-705's root issue**; otherwise Builder updates the link before merging and surfaces the discrepancy to Architect.
12. **Forward markers filed as GitHub issues if not yet filed:**
    - **AD-705a** — Offline STT via Whisper (whisper.cpp WASM). When privacy / offline / non-browser-STT is required.
    - **AD-705b** — Offline TTS via Coqui / Piper. When Edge cloud TTS is unavailable OR Captain wants per-agent voice characters the browser doesn't provide. License audit needed (some Coqui models are non-commercial).
    - **AD-705c** — Custom wake-word model training pipeline. For a true "Computer"-trained model from Captain voice samples. Browser-side openWakeWord training is non-trivial; may move to a CLI-side workflow.
    - **AD-705d** — Mic-permission UX polish. If the v1 first-grant flow needs more handholding (modal-on-first-toggle, deep-link to browser site settings on denial, etc.) Captain reviews v1 UX in the PR; files AD-705d only if Captain flags it.

---

## 9. Engineering principles compliance (Builder verifies — copilot-instructions.md)

- ✅ **Tier-2 log-and-degrade** for both ONNX loads (D3 fallbacks).
- ✅ **Defense in depth** at the router (D4: case-insensitive + leading-position check + callsign verification against `useStore.agents`).
- ✅ **No private-attr access** — only public exports of `speechInput.ts`, `voice.ts`, `useStore`.
- ✅ **No emoji** in HXI surface (D7).
- ✅ **HXI motion communicates state** (D7 three-state pulse).
- ✅ **Async discipline** — `AbortController`, no fire-and-forget, abort cleanly on `stopWakeWordLoop()`.
- ✅ **Privacy** — pre-wake audio local-only; documented in §1.
- ✅ **No new Pydantic config** — UI-only constants.
- ✅ **No episodic write** for wake-fire — existing `/api/chat` writes turn-level episodes.
- ✅ **Trust + Hebbian unchanged** — router is read-only pre-router.
- ✅ **Boundary tests required** — happy path, error case, fallback path. ≥ 21 Vitest cases.
- ✅ **Type annotations** on all public exports (`WakeWordState`, `WakeRoute`, etc.).
- ✅ **Logging quality** — fallback transitions log structured context (`logger.warn('wake-word ONNX load failed; falling back to substring match', { reason })`).

---

## 10. Forward markers (enumerated)

| Marker | Scope | Trigger to file |
|---|---|---|
| **AD-705a** | Offline STT (whisper.cpp WASM, ~75 MB tiny.en model) | Captain wants browser-free / offline STT, OR privacy concerns over browser cloud-routed `SpeechRecognition` |
| **AD-705b** | Offline TTS (Coqui / Piper) | Captain wants per-agent voice characters the browser SpeechSynthesis catalogue doesn't provide, OR airgapped deployment |
| **AD-705c** | Custom wake-word model training pipeline | Captain wants a true "Computer"-trained model rather than `hey_jarvis` re-labeled |
| **AD-705d** | Mic-permission UX polish | v1 first-grant flow needs handholding modal / settings deep-link |

---

## 11. Tracking

| Tracker | Update |
|---|---|
| `PROGRESS.md` | Add one-line entry: "AD-705 (reframed) — wake-word voice loop v1 shipped (Wave 137)" |
| `progress-era-*.md` (current era) | Add detailed entry citing tests + bundle delta |
| `DECISIONS.md` (or `decisions-era-4-evolution.md`) | Append AD-705 (reframed) entry citing wave dispatch |
| `docs/development/roadmap.md` | Mark AD-705 closed in roadmap; note reframe |
| GitHub Issues | Close [#481](https://github.com/seangalliher/seangalliher/ProbOS/issues/481) (verify AD-705 root), file AD-705a/b/c/d if not filed |
| `prompts/wave-plan.yaml` | NOT modified by this prompt (Captain's instruction) — separate post-merge task |
| `prompts/build-reports/wave-137-ad-705.md` | New build report per BUILDER-EXECUTION-PLAN.md |

---

## 12. Issue link

[#481](https://github.com/seangalliher/seangalliher/ProbOS/issues/481) (root AD-705 — Builder verifies the live issue number matches; updates the link in this section AND in §8 #11 if mismatch).
