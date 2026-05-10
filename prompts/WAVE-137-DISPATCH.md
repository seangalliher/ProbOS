# WAVE 137 DISPATCH — Always-on wake-word voice loop (AD-705 reframed + AD-718c)

**Wave:** 137
**Mode:** main
**Depends on:** 133 (AD-718 v1 voice profile baseline), 136 (AD-718a agent-authored voice + AD-718d emotional modulation)
**Builder required:** yes
**Issues to close:** AD-705 root issue (verify number at draft-time), [#524](https://github.com/seangalliher/ProbOS/issues/524) (AD-718c)
**Date:** 2026-05-09

---

## 1. Goal

Captain ruling 2026-05-09 reframes AD-705 from "voice stack backends (Whisper/Coqui/Piper/Porcupine)" to **the always-on wake-word voice loop**. Edge Online Natural TTS is "quite good" and stays as v1 TTS; the killer feature is **fluid hands-free voice conversation with a wake word**.

Two paired prompts ship the v1 wake-word loop entirely client-side:

- **AD-705 (reframed)** — system-wide wake word ("Computer") with continuous-listen + VAD-bounded utterance capture, wake-word-aware router (system vs `@callsign`), barge-in suppression, and a privacy-grade listening indicator. Risk: **MEDIUM**.
- **AD-718c** — per-agent wake phrase ("Hey Ezri", "Counselor"), governed by the existing AD-718a propose/approve flow. Risk: **LOW–MEDIUM**.

Both prompts stay **strictly client-side**. The runtime sees only the final transcript via the existing `POST /api/chat` path. Zero new server protocols, zero new server config tables.

Backend STT/TTS swaps (Whisper / Coqui / Piper / native menubar) are firewalled OFF and re-filed as forward markers (see §7).

---

## 2. Prior-work + license disposition

| Prior work / candidate | What we found at HEAD | Disposition |
|---|---|---|
| `ui/src/audio/speechInput.ts` `startListening(onResult, onEnd?, onError?, opts?)` | Verified at HEAD: `continuous`, `interimResults`, `onSpeechEnd` options; auto-restarts on `onend` when `continuous: true` (AD-474b/c). `stopListening()`, `isListening()`, `isSpeechRecognitionSupported()` all public. | **Reuse as the bottom of the audio stack.** The wake-word loop sits on top of `startListening` in continuous mode. Do NOT reimplement browser SpeechRecognition. Do NOT modify `speechInput.ts`'s public API in this wave. |
| `ui/src/audio/voice.ts` `speakResponse(text, profile?, agent_id?)` | Verified at HEAD lines 92–148. AD-718d modulation hook in place. `onSpeechEvent(fn)` lifecycle pub/sub fires `'start'` and `'end'`. | **Reuse for barge-in suppression.** D6 subscribes to `onSpeechEvent` to gate the wake-word loop's input ingestion while `'start'` → `'end'` is open. **Do NOT replace browser TTS** (Captain ruling). AD-705b firewalled OFF. |
| `src/probos/voice/__init__.py` Protocols | Verified at HEAD: `SpeechRecognizer`, `WakeWordDetector`, `TextToSpeech`, `TranscriptionResult`, `BrowserSpeechRecognizer` (no-op stub), `StaticWakeWordDetector` (case-insensitive substring match), `SilentTextToSpeech`. AD-474. | **Reference only.** v1 wake-word loop is browser-side; the Python Protocols are the future backend seam (AD-705a Whisper) and stay untouched in this wave. `StaticWakeWordDetector`'s substring-match algorithm is the **algorithmic reference** for the browser fallback when ONNX wake-word fails to load (Tier-2 log-and-degrade — see §3). |
| `IntentSurface.tsx` mic button | Verified at HEAD around line 1885: click-to-talk with `startListening` in single-shot mode; auto-submits on result. `isSpeechRecognitionSupported()` gate. Local `listening` state, pulse animation, amber/red color scheme. | **Extend, don't replace.** Click-to-talk path stays as the manual mode. The wake-word loop is a SEPARATE state machine (`wakeListening`) that, when active, drives transcript through the same submit path. The two modes are mutually exclusive — engaging the wake-word toggle disables the click-to-talk button briefly while it's hot, OR the click-to-talk button becomes a "force-listen now" override. Drafter picks; document in AD-705 prompt §1. |
| `ProfileChatTab.tsx` mic button | Verified at HEAD line 229: same click-to-talk pattern as IntentSurface. | **Same disposition.** ProfileChatTab participates in the wake-word loop ONLY when the per-agent wake-phrase fires (AD-718c). System-wide "Computer" stays in IntentSurface (Ship's Computer surface). |
| `DecisionSurface.tsx` toggles | Verified at HEAD lines 17–24: `soundEnabled`, `voiceEnabled`, voice picker UI. `useStore` exposes `setSoundEnabled` / `setVoiceEnabled` / `volume`. | **Extend.** Add `wakeWordEnabled` global toggle next to `voiceEnabled`. Persisted in localStorage via the same store pattern. Inline-SVG icon. Off by default. Captain explicitly opts in. |
| `useStore.agents: Map<string, Agent>` | Verified at HEAD line 81+. Agent type carries identifying fields used elsewhere (channels, notebooks, profile chat). Drafter MUST verify the Agent type's `callsign` shape at HEAD before AD-718c draft — agents are listed by callsign in many surfaces. | **Reuse as the wake-phrase source for AD-718c.** When AD-718c lands, each Agent carries an optional `voice_profile.wake_phrase` that the wake-word loop subscribes to. NO new Agent fields beyond what AD-718c's E1 introduces. |
| `runtime.callsign_registry` (Python) | Verified at HEAD: `agent_onboarding.py:46`, `channels/base.py:90`, `agents/introspect.py:300`. Resolves callsign → agent_type. | **Reference only.** v1 wake-word loop does NOT call into `callsign_registry`; the UI store already mirrors callsign data. Forward marker: AD-705a may use the registry server-side once Whisper lands. |
| **openWakeWord** (https://github.com/dscripka/openWakeWord) | Apache-2.0, ONNX models, runs in-browser via `onnxruntime-web`. No AccessKey, no per-user license. Custom-phrase training pipeline available offline. | **Adopt.** D1 introduces the dependency. License-clean for OSS Apache-2.0 posture. Initial model: stock "computer" or "hey jarvis"-class small model (drafter picks; ~ a few MB). |
| **Silero VAD** (https://github.com/snakers4/silero-vad) | MIT, ONNX, ~1.8 MB, browser-compatible. | **Adopt.** D2 introduces the dependency. Used as the utterance-boundary detector inside the active-listen window. Falls back to `onspeechend` (already wired) if model load fails — Tier-2 log-and-degrade. |
| **Picovoice Porcupine** | Free tier requires AccessKey; non-Apache. | **Reject.** Pattern-absorption only (we already learned what good wake-word UX looks like from their docs). License creep is the dealbreaker for an Apache-2.0 OSS repo. |
| **whisper.cpp WASM / whisper-web** | MIT, browser-compatible, but model is ~75 MB (tiny.en). | **Defer to AD-705a.** Browser SpeechRecognition (already wired) is sufficient for v1. Whisper goes to a separate wave when offline / privacy-only STT is required. |
| **WebRTC AEC** (`getUserMedia({audio: {echoCancellation, noiseSuppression}})`) | Browser-native. Already implicitly active when `getUserMedia` is invoked with default constraints. | **Use.** AD-705 does NOT explicitly toggle these; the browser defaults handle the common case. Barge-in suppression (D6) is **belt-and-suspenders** on top of AEC: even if AEC leaks the agent's TTS into the mic, the loop pauses ingestion during `speechSynthesis.speaking`. |

**Top-level license posture:** OSS Apache 2.0 stays Apache 2.0. Two new JS deps: `onnxruntime-web` (MIT), `openWakeWord` (Apache-2.0), and the Silero VAD ONNX file (MIT). All license-clean. Bundle size impact: ~few MB of ONNX runtime + ~few MB of wake-word + ~1.8 MB Silero. Drafter pins exact bundle delta in the AD-705 prompt §1 ("verified bundle size delta in dev build"). **No paid-license deps. No AccessKey-gated services. No model weights with restrictive licenses.**

---

## 3. Engineering-principles checklist

Builder must verify each in the per-prompt acceptance criteria. Reviewer flags any miss as **Required**.

| Principle (`.github/copilot-instructions.md`) | Where it applies | Verifying deliverable |
|---|---|---|
| **Tier-2 log-and-degrade for model loads** | D1 (openWakeWord), D2 (Silero VAD) | Both ONNX loads run in `try { ... } catch { logger.warn(...); fallback }`. Wake-word fallback: substring match against transcript text (algorithmic mirror of `StaticWakeWordDetector`). VAD fallback: `onspeechend` heuristic (already wired). The wake-word loop MUST function — at degraded quality — even if both ONNX models fail to load. Tests verify both fallback paths. |
| **Barge-in suppression** | D6 | While `speechSynthesis.speaking === true`, the wake-word loop's ingestion path is gated via `onSpeechEvent` listener (subscribed once at module init, unsubscribe on `stopWakeWordLoop`). Resume on `'end'`. Test: emit a synthetic `'start'` event with mock signals, assert ingestion is suppressed; emit `'end'`, assert ingestion resumes. |
| **Defense in depth** | D4 (router) | Router input is the recognized transcript (already a string from browser SpeechRecognition). Two boundary checks: (1) wake-phrase match (case-insensitive, leading-or-near-leading position required — drafter pins exact rule and test cases), (2) callsign resolution against `useStore.agents`. Unknown callsign falls back to system surface (Ship's Computer). NEVER treats raw transcript as a system command — transcript ALWAYS routes through the existing `POST /api/chat`. No `eval`, no template-string-as-code. |
| **No private-attr access** | D3, D4, D5 | The wake-word module imports only public exports of `speechInput.ts`, `voice.ts`, and `useStore`. No reaching into `_activeRecognition` or any private state. Toggle persistence uses the existing `useStore` pattern (additive `wakeWordEnabled` flag with `setWakeWordEnabled`). |
| **No emoji in HXI** (HXI Design Principle #3) | D7 indicator + D5 toggle icon | Inline SVG `strokeWidth: 1.5`, `strokeLinecap: round`. Active amber `#f0b060`, inactive dim `#666680`. Reviewer fails on any emoji literal in the diff. |
| **HXI Design Principle #4 (motion communicates state)** | D7 listening indicator | Pulse when actively listening (post-wake-word, within the utterance window). Steady (low-amplitude) glow when armed-but-not-active (idle wake-word watch). Off when toggle is OFF. Three distinct visual states map to three system states. **Captain MUST never be uncertain about whether the mic is hot.** Reviewer fails the prompt if any state is missing or visually conflated. |
| **Async discipline** | D3 (loop), D6 (barge-in) | All async work uses `async`/`await`; no `new Promise(...)` anti-patterns. ONNX inference runs off the main thread where possible (drafter checks `onnxruntime-web` worker support; if not viable in v1, document the mainline-blocking trade-off and pin a max-frame budget). No fire-and-forget; the loop holds a reference to its inference task and aborts cleanly on `stopWakeWordLoop()`. |
| **Privacy** | D7 + the entire wave | Audio NEVER leaves the browser before a wake-word fires. The mic stream from `getUserMedia` is consumed directly by the in-browser ONNX detector. Only AFTER a wake-word fires does the existing browser SpeechRecognition (already cloud-routed in some browsers — Chrome especially) activate. The privacy boundary is the wake-word: pre-wake audio is local-only. Drafter calls this out explicitly in the AD-705 prompt §1 — Captain reviews. |
| **Configuration via Pydantic** | None server-side | Wave 137 introduces ZERO new Pydantic config. All UI knobs live in `ui/src/audio/wakeWord.ts` as compile-time constants (`WAKE_WORD_THRESHOLD = 0.5`, `UTTERANCE_MAX_DURATION_MS = 10000`, `SILENCE_TIMEOUT_MS = 1500`). Drafter pins values; Captain reviews. Future server-side knobs land in AD-705a. |
| **Episodic completeness** | D4 router | Each wake-word-fired transcript goes through the existing `POST /api/chat` path, which already writes an episode for each turn. **No new episode write.** Wake-word fire itself is NOT an episode (too high-frequency, too low-signal). If Captain wants wake-fire telemetry, file as a separate AD. |
| **Trust + Hebbian alignment** | D4 router | Routing choice (system vs `@callsign`) does NOT update trust or Hebbian weights. The downstream `/api/chat` path drives those updates as it always has. The wake-word router is a **read-only** pre-router. |
| **Test gates** | Both prompts | Per-prompt: `pytest tests/test_ad705_*.py -v -n 0` (none expected — pure UI wave) AND `cd ui && npx vitest run` MUST be green. Full gate: `pytest tests/ -q -n 16 --dist=loadfile` (fall back per BUILDER-EXECUTION-PLAN.md). UI Vitest count grows by ~12 (wake-word state machine ~5, router ~3, toggle persistence ~2, barge-in ~2). |

---

## 4. AD-705 (reframed) scope — System-wide wake-word loop

**Issue:** root AD-705 (drafter verifies issue number at draft-time before final). The original "voice backend" scope is reframed; backend swaps move to AD-705a/b/c per §7. This wave ships the **always-on wake-word loop** with browser-only deps.

### Deliverables

| ID | Deliverable | File(s) | Verification |
|---|---|---|---|
| **D1** | `onnxruntime-web` + `openWakeWord` model (Apache-2.0) | `ui/package.json` (extend); new `ui/public/models/wake-word/computer.onnx` (or equivalent path; drafter picks under `ui/public/`) | Add `onnxruntime-web` dep. Bundle the small wake-word model under `ui/public/` so it's served via the same origin (no CDN). Bundle delta documented in PR description. |
| **D2** | Silero VAD ONNX (MIT) | New `ui/public/models/vad/silero_vad.onnx` (drafter picks path) | Same origin. ~1.8 MB. License attribution committed alongside the model file (LICENSE-silero or `THIRD_PARTY_LICENSES.md` row). |
| **D3** | `ui/src/audio/wakeWord.ts` — pure module | New file | Public exports: `startWakeWordLoop(onWake, opts?)`, `stopWakeWordLoop()`, `isWakeWordActive()`. State machine: `idle → armed (low-CPU monitoring) → triggered (post-wake) → capturing (continuous startListening + VAD) → submit → armed`. Configurable: `WAKE_WORD_THRESHOLD`, `UTTERANCE_MAX_DURATION_MS = 10000`, `SILENCE_TIMEOUT_MS = 1500`. Tier-2 fallback: if ONNX load fails, fall back to substring-match wake detection on continuous browser SpeechRecognition (verified at HEAD: `StaticWakeWordDetector` algorithm). |
| **D4** | Wake-word-aware router | New helper inside `wakeWord.ts` OR alongside `IntentSurface.tsx` (drafter picks; recommended: standalone helper for testability) | `routeWakeTranscript(transcript: string, agents: Map<string, Agent>): { surface: 'system' \| 'agent'; agentCallsign?: string; cleanedText: string }`. Cases (drafter pins all in AD-705 prompt §4): "Computer, …" → system surface, transcript = remainder; "Ezri, …" or "Hey Ezri, …" → agent surface with callsign 'Ezri', transcript = remainder; bare transcript with no recognized prefix → discard (not addressed to anyone). Pure function — fully testable without DOM. |
| **D5** | Mode toggle in DecisionSurface | `ui/src/components/DecisionSurface.tsx` (extend the toggle row at lines 17–24 + the rendered toggles below) | Adds `wakeWordEnabled` boolean to store with `setWakeWordEnabled`, persisted in localStorage. New inline-SVG button next to existing voice/sound toggles. Default OFF. When ON: `startWakeWordLoop` invoked at app mount (or toggle moment); when OFF: `stopWakeWordLoop`. Test: toggle persists across remount. |
| **D6** | Barge-in suppression | Inside `wakeWord.ts` | Subscribes via `onSpeechEvent` (verified public export of `voice.ts` at HEAD). On `'start'`: gate ingestion (set internal flag; do not abort the underlying `startListening` since it's continuous). On `'end'`: clear gate. Test: emit synthetic `'start'`, push transcript through ingestion, assert it's dropped; emit `'end'`, push another transcript, assert it's accepted. |
| **D7** | Listening indicator (HXI Design Principle #4) | New component `ui/src/components/WakeWordIndicator.tsx`, rendered from `IntentSurface.tsx` (or wherever the global HXI corner-bug lives — drafter verifies at HEAD; if a "global status corner" component already exists, render INSIDE it; otherwise add a fixed-position element with `z-index` lower than modals) | Three visual states: OFF (not rendered, or invisible) / ARMED (low-amplitude steady glow, dim amber) / ACTIVE (pulsing bright amber, indicates capture in progress). Inline SVG, no emoji, no Material icons. Test: each of three states renders distinguishably. |
| **D8** | Tests (Vitest) | New `ui/src/__tests__/wakeWord.test.ts`, `wakeWord.router.test.ts`, `wakeWord.bargeIn.test.ts`, `WakeWordIndicator.test.tsx`, `DecisionSurface.wakeWordToggle.test.tsx` | (1) State machine: idle → armed on `startWakeWordLoop`; armed → triggered on synthetic wake fire; triggered → capturing → submit → armed cycle; armed → idle on `stopWakeWordLoop`. (2) Router: 4–6 cases (system, agent, ambiguous, no-prefix). (3) Barge-in: as in D6. (4) Toggle persistence: localStorage round-trip. (5) Indicator: three states. (6) Fallback: simulated ONNX-load failure exercises the substring-match path. |

### Wiring

`startWakeWordLoop` is invoked from a single place — IntentSurface mount when `wakeWordEnabled` is true (drafter picks: a `useEffect` keyed on the toggle state). On mount with the flag OFF: nothing runs. On toggle ON at runtime: start. On toggle OFF: stop. On unmount: stop. Single owner of the loop lifecycle prevents leaks across remounts.

---

## 5. AD-718c scope — Per-agent wake phrase

**Issue:** [#524](https://github.com/seangalliher/ProbOS/issues/524). Each crew member's `VoiceProfile` gains an optional `wake_phrase`. Default empty (system-wide "Computer" only). Captain or agent self-design (AD-718a) can propose a custom phrase. Per-agent wake hits route directly to that agent's `@`-mention path.

### Deliverables

| ID | Deliverable | File(s) | Verification |
|---|---|---|---|
| **E1** | `wake_phrase` field on `VoiceProfile` | `src/probos/crew_profile.py` (extend `VoiceProfile` dataclass) | New optional field: `wake_phrase: str = ""`. Validation: max length 50 chars (compile-time constant). `__post_init__` strips whitespace. Empty string == "no per-agent wake phrase". `from_dict` / `to_dict` round-trip the field. |
| **E2** | Pydantic mirror in `VoiceProposal` | `src/probos/voice/proposal.py` (extend `VoiceProposal` model from AD-718a) | Add `wake_phrase: str = Field(default="", max_length=50)`. Same validation as E1. AD-718a parser changes are minimal — adds one optional field; LLM output that omits it parses fine. |
| **E3** | Capability prompt update | `src/probos/cognitive/cognitive_agent.py` `propose_voice` (extend AD-718a's instructions string) | LLM is now informed it MAY propose a wake phrase. Prompt guidance (drafter pins exact wording): "Two-syllable phrases work best. May be the agent's first name, callsign, or rank. Keep it short and distinct." Captain reviews phrasing. |
| **E4** | API surface | `src/probos/routers/agents.py` PUT `/voice-profile` (extend) | Existing PUT request body gains optional `wake_phrase` field on `SetVoiceProfileRequest`. PUT round-trips through `VoiceProfile(...)` constructor (per AD-718a §3 defense-in-depth). GET surface returns `wake_phrase` in the response payload. |
| **E5** | UI: wake-phrase row in voice picker | `ui/src/components/profile/ProfileInfoTab.tsx` (extend voice editor block) | Text input for wake phrase, max 50 chars enforced client-side too. "Propose" affordance from AD-718a now also surfaces a proposed `wake_phrase`. Captain can hand-edit before approve. **No emoji.** |
| **E6** | UI: wake-phrase loaded into wake-word loop | `ui/src/audio/wakeWord.ts` (extend) | At loop init: read all agents from `useStore.agents`, collect non-empty `voice_profile.wake_phrase` values, register each as an additional wake trigger that routes directly to the corresponding agent's `@callsign` path. When agents update (via store), re-collect (debounced — drafter picks debounce window; recommended 500ms). |
| **E7** | Governance — Captain approves the phrase | Reuses AD-718a flow | No new approve flow. The agent proposes via `propose_voice`, the Captain reviews the candidate `VoiceProfile` (including `wake_phrase`) in the existing UI preview, approves via existing PUT. Episode is written via the existing approve-from-proposal episode hook (AD-718a D7) — `signals` dict gains a `wake_phrase` key. |
| **E8** | Tests | New `tests/test_ad718c_wake_phrase.py`; new `ui/src/__tests__/wakeWord.perAgent.test.ts`, `ProfileInfoTab.wakePhrase.test.tsx` | (1) `VoiceProfile(wake_phrase="hey ezri")` round-trips through `to_dict`/`from_dict`. (2) `VoiceProposal.model_validate({"wake_phrase": "x" * 51})` raises (max length). (3) PUT accepts `wake_phrase`; GET returns it. (4) `propose_voice` LLM output with `wake_phrase` parses cleanly. (5) UI: text input renders; persists via PUT. (6) Wake-word loop registers per-agent triggers and routes correctly. (7) Empty `wake_phrase` does NOT register a trigger. |

### Server-side

Minimal: one new field on the dataclass, one new field on the Pydantic model, one optional field on the request schema. Zero new endpoints, zero new tables.

---

## 6. Cross-AD integration points

| Integration | What it means | Builder action |
|---|---|---|
| **Captain ruling: TTS unchanged** | Edge Online Natural stays. AD-705b (Coqui/Piper) firewalled OFF. | Reviewer fails any change to `voice.ts` beyond barge-in event subscription. The TTS path is sacrosanct in this wave. |
| **Privacy boundary at the wake word** | Pre-wake-word audio is local-only (in-browser ONNX). Post-wake audio uses browser SpeechRecognition (which may go cloud in some browsers). | AD-705 prompt body §1 explicitly documents this. Captain reviews. If the Captain wants fully-local STT, that's AD-705a (Whisper). |
| **Three-tier wake gate** | (1) ONNX wake-word fires (low confidence allowed) → (2) browser SpeechRecognition activates → (3) router classifies system vs agent. Each layer has independent fail-safe. | Tests cover each layer's degradation: ONNX missing → substring fallback; browser STT missing → loop disables itself with a one-time warning toast. |
| **AD-705 → AD-718c sequencing** | AD-705 ships the loop with a single "Computer" wake. AD-718c adds the per-agent triggers. | Per-agent triggers register as ADDITIONAL waker phrases; they do NOT replace "Computer". Captain saying "Computer" still goes to Ship's Computer even if AD-718c lands. |
| **Indicator state derived from loop state** | The indicator (D7) is a pure function of the loop's state machine (D3). | Component subscribes to `isWakeWordActive()` AND a separate "is currently capturing" signal. Drafter picks: either expose two boolean predicates from the module, or a single state-string export (`'off' \| 'armed' \| 'capturing'`). Recommended: state-string. |
| **Toggle persistence == feature opt-in** | Wave 137 ships the loop OFF by default. Captain explicitly opts in via the toggle. | Reviewer fails the prompt if the default is ON. The Captain must consent before audio is continuously captured. |
| **Fallback path is a real product surface, not a placeholder** | If ONNX models fail to load (corporate firewall blocks the model file, browser doesn't support `onnxruntime-web`, etc.), the system falls back to continuous browser SpeechRecognition + substring-match wake detection. | Tests cover the fallback path. Performance is documented as "degraded — higher false-positive rate, more cloud STT round-trips". Toast or status indicator surfaces "wake-word running in fallback mode" so the Captain knows. |

---

## 7. Out-of-scope / deferred to later waves

- **AD-705a** — Offline STT via Whisper (whisper.cpp WASM). When privacy / offline / non-browser-STT is required. Deferred. Drafter files issue if not yet filed.
- **AD-705b** — Offline TTS via Coqui / Piper. When Edge cloud TTS is unavailable (offline, intranet-only deployment) OR when the Captain wants per-agent voice characters that the browser doesn't provide. Deferred. License audit needed before adoption (some Coqui models are non-commercial).
- **AD-705c / AD-474g** — Native menubar push-to-talk (Tauri/Electron). System-wide hotkey from outside the browser tab. Already filed as AD-474g.
- **AD-718e** — Multi-language voice. Issue [#526](https://github.com/seangalliher/ProbOS/issues/526). Depends on Whisper.
- **Picovoice Porcupine** — License-rejected. Pattern-absorption only.
- **Server-side wake-word telemetry** — Wake-fire frequency / accuracy metrics. Filed as AD-705-1 if Captain wants it.
- **Captain-side voice training** — Training a custom wake-word model from Captain's voice samples. Filed as AD-705-2 (depends on openWakeWord training pipeline running browser-side, which is non-trivial).
- **VAD-driven mid-utterance interruption** ("…actually no, never mind") — out of scope; v1 commits the utterance on first `SILENCE_TIMEOUT_MS` window.
- **Multi-speaker / who-is-talking** — out of scope. v1 assumes single Captain.

---

## 8. Hard-stop conditions for the Builder

Builder MUST stop and surface to Architect if any of the following occur:

1. **Phantom API.** A grep at HEAD returns zero matches AND the prompt does not introduce it. Examples introduced by this wave (false positives): `startWakeWordLoop`, `stopWakeWordLoop`, `isWakeWordActive`, `routeWakeTranscript`, `WakeWordIndicator`, `wakeWordEnabled`, `setWakeWordEnabled`, `voice_profile.wake_phrase`. All EIGHT are introduced by this wave; flagging them as missing is a false positive.
2. **Architectural contract change required.** Any change to `speechInput.ts`'s public API, `voice.ts`'s `speakResponse` signature, `useStore`'s Agent type beyond AD-718c E1, or `BaseAgent`/`IntentMessage` is a HARD STOP.
3. **Working tree integrity.** Pre-flight `git diff --numstat | sort -k2nr | head -5`. Any file with >200 lines deleted that the Builder did not author is a stop-the-line event (per user-memory note 2026-05-08).
4. **License creep.** Any new third-party dep beyond `onnxruntime-web` (MIT), the openWakeWord model (Apache-2.0), and the Silero VAD ONNX (MIT) is a HARD STOP. **No Porcupine. No paid-license deps. No AccessKey deps.**
5. **Emoji in diff.** Any emoji literal in `*.tsx` / `*.ts` / `*.py` of the diff is a HARD STOP. HXI Design Principle #3.
6. **TTS replacement.** Any change to `voice.ts` that replaces `speechSynthesis.speak(...)` with anything else is a HARD STOP. Captain ruling: TTS is unchanged in v1.
7. **Default-on toggle.** If `wakeWordEnabled` defaults to `true`, HARD STOP. Captain explicitly opts in.
8. **Audio leaks server-side before wake-word.** Any code path that uploads pre-wake audio to any server (even ours) is a HARD STOP. The privacy boundary is the wake word.
9. **Indicator missing or visually conflated.** If the listening indicator does not distinguish OFF / ARMED / ACTIVE with three visually-distinct states, HARD STOP. HXI Design Principle #4.
10. **Test gate failure under `-n 0` after passing under `-n 16`.** Order-dependent test pollution → quarantine via BF entry pointing at AD-682, do NOT block the wave. (Wave 137 expects nearly all tests to be Vitest-side; this rule applies to any incidental Python test addition.)
11. **`exec`/`eval`/`compile`/`pickle.loads` on transcript or wake-phrase.** HARD STOP.
12. **Anchor-alias-tag tokens accepted by AD-718c's `wake_phrase` field.** Already covered by AD-718a's parser; if the wake_phrase field somehow bypasses the parser, HARD STOP.

---

## 9. Acceptance criteria

For each prompt, the Builder MUST:

1. Run `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-705-…-v1.md` and `…ad-718c-…-v1.md` after drafting; resolve any flagged phantoms (or document them in the prompt's "Verified Against Codebase" footer as introduced-by-this-prompt).
2. Pass per-prompt UI test gate: `cd ui && npx vitest run`. AD-705 adds ~12 Vitest cases; AD-718c adds ~5.
3. Pass per-prompt Python test gate (AD-718c only): `pytest tests/test_ad718c_*.py -v -n 0`. ~7 tests.
4. Pass full test gate: `pytest tests/ -q -n 16 --dist=loadfile` (fall back to `-n 8` per BUILDER-EXECUTION-PLAN.md).
5. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
6. PROGRESS.md updated: highest AD bumped if any new top-level AD is filed (AD-705a/b/c forward markers may be filed during this wave but not implemented). AD-721i remains the highest AD if only sub-letter ADs land.
7. `decisions-era-*.md` (drafter picks the right era file) appended with AD-705 (reframed) + AD-718c entries citing the wave dispatch.
8. `docs/development/roadmap.md` Bug Tracker — no new BF entries expected from happy path.
9. Issues closed: AD-705 root issue (verify number), [#524](https://github.com/seangalliher/ProbOS/issues/524). Verify the `wave-plan.yaml` entry matches before merging (wave-plan was NOT modified during this dispatch per Captain instruction; Builder-side update of wave-plan is a separate post-merge task).
10. Forward markers filed as GitHub issues IF NOT YET FILED: AD-705a (offline STT), AD-705b (offline TTS), AD-705-1 (telemetry), AD-705-2 (custom wake training). AD-705c is already AD-474g; verify and skip if duplicate.
11. License attribution: openWakeWord (Apache-2.0) and Silero VAD (MIT) attributed in `THIRD_PARTY_LICENSES.md` (or equivalent file at HEAD; drafter verifies). Model files committed under `ui/public/models/` with adjacent `LICENSE-*` files.
12. Memory artifacts: nothing new for `/memories/probos-architect-learnings.md` unless a fresh pattern emerges. The "ONNX-in-browser as a license-clean alternative to AccessKey'd wake-word" is a reusable pattern; if Wave 137 confirms the pattern works end-to-end, add a one-liner.

---

## 10. AD-numbering verification

**Current highest AD as of HEAD:** **AD-721i** (verified at `PROGRESS.md:11`: *"DECISIONS.md — append-only architectural decisions (current highest AD: AD-721i)"*).

**This wave:**

| AD | Issue | Status |
|---|---|---|
| AD-705 (reframed) | root AD-705 issue (verify at draft) | Top-level number, already exists; reframed scope. No new top-level AD. |
| AD-718c | [#524](https://github.com/seangalliher/ProbOS/issues/524) | Sub-letter of AD-718; no collision. |

**No new top-level ADs in this wave.** Highest stays at AD-721i.

**Forward markers may be filed as new issues during this wave** but their AD numbers are already pre-allocated as AD-705a, AD-705b, AD-705-1, AD-705-2. Sub-letter / dash-numbered ADs do not bump the highest.

---

## Final report (Architect)

- **Path written:** [prompts/WAVE-137-DISPATCH.md](prompts/WAVE-137-DISPATCH.md)
- **Outline:** Wave 137 reframes AD-705 from "voice-stack backends" to **the always-on wake-word voice loop** per Captain ruling 2026-05-09. Two prompts: AD-705 (reframed) ships browser-side openWakeWord + Silero VAD + a wake-word-aware router on top of the existing `startListening` continuous mode, with a privacy-grade three-state listening indicator and barge-in suppression. AD-718c adds an optional per-agent `wake_phrase` field governed by the existing AD-718a propose/approve flow, so saying "Hey Ezri" routes directly to Counselor without typing the `@`. Edge Online Natural TTS stays as v1 TTS — backend swaps deferred to AD-705a/b/c. Two new license-clean JS deps (Apache-2.0 + MIT). All audio stays client-side until a wake fires; Captain explicitly opts in via a default-OFF toggle.
- **Open Captain questions:**
  1. **Wake-word model choice for v1.** openWakeWord ships several stock models ("hey jarvis", "alexa", "computer-class"). Wave 137 says "Computer" because the Ship's Computer identity is canonical. Recommendation: ship with a "computer"-class stock model. If accuracy is poor, file AD-705-2 for custom-Captain-voice training. Does the Captain want a stock model in v1 or a custom-trained one before merge? (Recommendation: stock for v1; custom is its own AD.)
  2. **Capture-window UX.** When the wake-word fires, the loop captures continuously until silence > 1.5s or the 10s ceiling. Should the Captain be able to interrupt mid-capture by saying "cancel" or pressing Escape? Recommendation: ship Escape-to-cancel in v1; voice cancel is a follow-up.
  3. **Indicator placement.** D7 says "fixed-position corner". The Captain's HXI is dense; where exactly? Recommendation: bottom-right of IntentSurface, above the input bar, small (~16px), offset from the existing mic icon. Drafter places; Captain reviews PR screenshot.
  4. **Per-agent wake-phrase governance opt-out.** AD-718c lets agents propose their own wake phrases via AD-718a. Should the Captain be able to globally disable per-agent wake phrases (system-only mode)? Recommendation: ship with a single `wakeWordEnabled` toggle in v1; per-agent opt-out is a follow-up if needed (Captain can also just leave all `wake_phrase` fields empty manually).
  5. **Bundle size.** Two ONNX models + onnxruntime-web add ~few MB to the dev bundle. Acceptable for an OSS project? Recommendation: yes — this is the point of in-browser inference. Document the delta in the AD-705 PR description; the Captain reviews and pulls the brake if the size is excessive.
  6. **Wake-word fallback toast.** When ONNX models fail to load and the loop falls back to substring-match, a toast surfaces "Voice loop running in degraded mode (ONNX models unavailable)." Should this be silent (logged only) or visible? Recommendation: visible — degraded mode has higher false-positive rate, the Captain should know. Toast dismisses automatically after 8s.
- **Risk classification:**
  - **AD-705 (reframed)** — **MEDIUM**. Net new client-side state machine, two new ONNX models, two new browser deps, three-state indicator (HXI Principle #4 — non-negotiable), privacy boundary documentation. The technical risk is the ONNX-in-browser surface (model load latency, worker support, bundle size). The UX risk is "is the indicator unmistakable?" — Captain reviews on PR.
  - **AD-718c** — **LOW–MEDIUM**. Single dataclass field + Pydantic mirror + UI text input + wake-word loop multi-trigger registration. Reuses AD-718a propose/approve flow.
  - **Wave overall** — **MEDIUM**. The reframe + new client-side audio surface is non-trivial. License posture is clean. No backend protocol changes. No backend storage migrations. Most of the risk is in the UX (does it FEEL like a hands-free conversation?) which is best resolved by Captain in the PR review.
- **Phantom-API check output:** _Run `pwsh scripts/phantom-api-precheck.ps1 prompts/WAVE-137-DISPATCH.md` after this file lands. Expected hits introduced by this wave (false positives, document in per-AD prompt footers): `startWakeWordLoop`, `stopWakeWordLoop`, `isWakeWordActive`, `routeWakeTranscript`, `WakeWordIndicator`, `wakeWordEnabled`, `setWakeWordEnabled`, `voice_profile.wake_phrase`. Verified-at-HEAD references all grepped clean during dispatch drafting (see Audit trail)._
- **Audit trail (files actually read during drafting):**
  - `ui/src/audio/speechInput.ts` lines 1–148 — `startListening`/`stopListening`/`isSpeechRecognitionSupported` confirmed; `continuous`+`interimResults`+`onSpeechEnd` opts confirmed; auto-restart in continuous mode at L122–124 confirmed.
  - `ui/src/audio/voice.ts` lines 1–200 — `speakResponse(text, profile?, agent_id?)` confirmed; `onSpeechEvent`/`SpeechEvent` lifecycle pub/sub confirmed; AD-718d emotional modulation hook in place; `'start'`/`'end'` events emitted at L143–144.
  - `src/probos/voice/__init__.py` lines 1–34 — Python protocols confirmed: `BrowserSpeechRecognizer`, `StaticWakeWordDetector`, `SpeechRecognizer`, `WakeWordDetector`, `TextToSpeech`, `TranscriptionResult`, `SilentTextToSpeech`, plus AD-718a `parse_voice_proposal`/`VoiceProposalError`.
  - `ui/src/components/IntentSurface.tsx` lines 1860–1920 — click-to-talk mic pattern confirmed at L1885; auto-submit-on-result confirmed at L1893–1897; pulse animation + amber/red color scheme at L1908–1916.
  - `ui/src/components/profile/ProfileChatTab.tsx` line 229 — same click-to-talk pattern.
  - `ui/src/components/DecisionSurface.tsx` lines 17–24 — `soundEnabled`/`voiceEnabled`/voice picker state confirmed; this is the location for the new `wakeWordEnabled` toggle.
  - `ui/src/store/useStore.ts` lines 81, 202, 486 — `agents: Map<string, Agent>` confirmed; this is the source for AD-718c's per-agent wake-phrase collection.
  - `src/probos/agent_onboarding.py` line 46, `src/probos/channels/base.py` line 90, `src/probos/agents/introspect.py` line 300 — `callsign_registry` confirmed (server-side; not consumed by v1 wake-word loop).
  - `prompts/archive/WAVE-136-DISPATCH.md` (entire) — structural template for this dispatch (10-section format, audit trail format, hard-stop / acceptance-criteria layout).
  - `PROGRESS.md` line 11 — highest AD = AD-721i.
  - `prompts/wave-plan.yaml` (grep for "137") — no Wave 137 entry yet; per Captain instruction not modified during this dispatch.
- **External references / OSS landscape (URLs cited in user request, not browser-fetched during drafting; Builder verifies before AD-705 prompt finalization):**
  - openWakeWord — https://github.com/dscripka/openWakeWord (Apache-2.0, ONNX, browser-compatible, no AccessKey).
  - Silero VAD — https://github.com/snakers4/silero-vad (MIT, ONNX, ~1.8 MB).
  - whisper.cpp WASM / whisper-web — MIT; deferred to AD-705a (model size ~75 MB).
  - Picovoice Porcupine — REJECTED (AccessKey + non-Apache free tier).
  - WebRTC AEC via `getUserMedia({audio: {echoCancellation, noiseSuppression}})` — browser-native, no dep.

- **What was NOT done (per Captain instruction):**
  - `prompts/ad-705-…-v1.md` and `prompts/ad-718c-…-v1.md` — not drafted. Per-AD prompts come after Captain approval of this dispatch.
  - `prompts/wave-plan.yaml` — not modified.
  - Production code — not touched.
