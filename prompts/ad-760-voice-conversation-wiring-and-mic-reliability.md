# AD-760 — Wire natural-conversation mode into DM panels + decouple mic from global voice toggle + STT reliability

Status: drafted
Issue: #706
Depends on: AD-747 (ConversationController), BF-318 (mic arbiter), AD-733c-7-5 (Silero VAD), AD-705a (whisperStt)

## Captain bug report (2026-05-20)

Three related voice defects, observed in production HXI:

1. The mic in a 1:1 agent DM does not work until the **global voice toggle** in the bottom tray is turned on.
2. Even once enabled, the Captain has to **click the mic button every time** to speak to the agent — natural duplex conversation (AD-747) is not active.
3. When the mic is used, speech is **not picked up reliably** — utterances drop or come back empty.

## Root-cause analysis

### Bug 1 — apparent "global voice gates the mic"
- `ui/src/components/profile/ProfileChatTab.tsx` reads `voiceEnabled` from the store and initialises the per-agent TTS button from it. The mic button calls `startListening()` from `ui/src/audio/speechInput.ts`, which acquires the arbiter at `PRIORITY_PRESS_TO_TALK` and uses browser `SpeechRecognition` directly. The mic is **not technically gated** by `voiceEnabled` — but:
- The perception VAD loop (`startVoiceActivity`) in `App.tsx` only runs when `perception.vad_engagement_enabled=true`. Without VAD running, browser-side endpointing is poor and the mic appears unresponsive until the Captain "does something" to wake the audio stack. The global voice toggle has a side effect of resuming `AudioContext` (browser autoplay rules) which then makes the mic work — that is the actual coupling the Captain is observing.

### Bug 2 — natural conversation never engages
- `ui/src/audio/conversationController.ts` (AD-747) exports `armConversationMode({ agentId, ... })` and is fully unit-tested.
- `grep` confirms **zero non-test callers**. No component ever invokes it. The DM panel (`ProfileChatTab.tsx`) and the WardRoom DM surface still rely on the manual mic button.
- Result: every DM open requires a click-to-talk per utterance; the duplex state machine (listening → transcribing → submitted → agent_speaking → silence_pending → listening) never runs in production.

### Bug 3 — unreliable transcription on the mic button
- `speechInput.ts` `startListening` is a single-shot `SpeechRecognition` instance with `continuous=false` (default). It auto-ends on the first silent gap, and on Chromium often returns empty `final` transcripts when the user pauses briefly mid-utterance.
- There is no VAD-bounded fallback path through `whisperStt` for the press-to-talk mic — that path is only used by the conversation controller, which isn't wired.

## Scope (v1, this AD)

### 1. Wire `armConversationMode` into the DM surfaces (right-click mic = mode picker)
- Activation gesture is the **mic-button context menu** (right-click on desktop, long-press on touch). Left-click stays press-to-talk; right-click opens a small popover with two options:
  - **Press to talk** (default, checkmark when active)
  - **Conversation mode** (checkmark when active)
  Selecting Conversation mode calls `armConversationMode({ agentId, historyProvider, onTranscript, onAgentReply })` and persists the choice per-agent in `localStorage` under `hxi_chat_mic_mode_${agentId}` (`ptt` | `conversation`, default `ptt`).
- While Conversation mode is active for an agent:
  - The mic icon switches to a "listening loop" visual (existing pulse-mic animation, amber instead of red).
  - On unmount or agent switch, call the returned disarm function.
  - On `voiceEnabled` flips false → disarm but keep the per-agent mode preference (re-arms when voice is re-enabled).
  - Left-clicking the mic during Conversation mode is press-to-talk preemption (PRIORITY_PRESS_TO_TALK > PRIORITY_CONVERSATION per BF-318) and on release returns to Conversation mode (re-arm).
- Wire the same context menu in:
  - `ui/src/components/profile/ProfileChatTab.tsx` (1:1 agent DM panel)
  - The WardRoom DM mic (verify path in `ui/src/components/wardroom/*`)
- The `onTranscript` callback populates the input box (preview pill) before submission; `onAgentReply` triggers the same TTS path the manual flow uses.
- Accessibility: the mic button must also be activatable as a menu via keyboard — `Shift+F10` or context-menu key on focused mic opens the same popover. `aria-haspopup="menu"` on the button.

### 2. Decouple mic button from global voice toggle (perception side)
- The mic button must work standalone — independent of `voiceEnabled`.
- In `App.tsx`, when the user clicks the mic in any DM, ensure the perception VAD loop is started on-demand (one-shot bring-up) if `perception.vad_engagement_enabled` is true but `startVoiceActivity` hasn't yet been called this session due to autoplay policy. Resume the `AudioContext` from the mic click handler (user gesture satisfies autoplay).
- If `perception.vad_engagement_enabled=false`, the mic button still works (uses browser SpeechRecognition directly without Silero endpointing) — surface a one-line hint in the existing `MicPermissionHint` component when transcripts come back empty repeatedly.

### 3. Press-to-talk reliability fix
- In `speechInput.ts`, set `continuous=true` and `interimResults=true` on the `SpeechRecognition` instance, and accumulate final transcripts until either: (a) the caller calls `stopListening()`, or (b) a 1.5 s end-of-speech gap is observed (configurable). This eliminates the "auto-ends on first pause, returns empty" failure mode.
- Add a fallback: if 2 consecutive `startListening` calls return empty transcripts AND Silero VAD is available, route the next press-to-talk through `whisperStt.armWhisperStt()` with a short bounded window instead of `SpeechRecognition`. This gives the Captain a reliable local-Whisper path on the press-to-talk button without forcing the natural-conversation state machine.

### 4. Conversation mode: agent-speaking handling + barge-in robustness
- **Do not mute the mic during `agent_speaking`.** Silero VAD keeps running so barge-in has zero warm-up latency.
- The existing state machine already gates transcript submission on `state === 'listening'`, so whisperStt output is dropped while the agent is speaking. Keep that invariant; add an explicit assertion in the controller's `_onTranscript` to log-and-drop when called outside `listening`.
- **Barge-in uses a Schmitt-trigger (hysteresis) detector over the Silero probability stream, not a single threshold.** Separate onset and offset thresholds prevent flapping on borderline audio.

  | Phase | Onset threshold | Offset threshold | Sustained frames (onset) | Release frames (offset) |
  |---|---|---|---|---|
  | `listening` (default VAD speech-start) | 0.50 | 0.35 | 3 (~100 ms) | 3 (~100 ms) |
  | `agent_speaking` (barge-in) | **0.80** | **0.40** | 8 (~250 ms) | 3 (~100 ms) |

  Detector state machine: starts `below`. When per-frame probability crosses the **onset** threshold and stays above it for the sustained-frame count, transition to `above` and fire the event (barge-in during playback, speech-start during listening). Once `above`, only release when probability falls below the **offset** threshold for the release-frame count. The 0.4 gap between onset (0.80) and offset (0.40) during playback absorbs the natural oscillation in voiced/unvoiced phoneme transitions and prevents stutter releases.
- **Why 0.80 onset during playback.** Silero's known false-positive bands for TTS bleed sit in the 0.55–0.70 range on most laptop AEC stacks. Above 0.75 the model rarely confuses synthesized speech for live human voice. This is empirical, not theoretical — defaults are tunable.
- **Amplitude floor.** Reject frames whose RMS is below ~-45 dBFS even if Silero's probability is high. Guards against the known false-positive on low-level steady noise (HVAC, fan). Applied as a precondition on every frame before it counts toward the sustained-onset tally.
- **Cooldown after a cancelled barge-in.** If the sustained-onset timer cancels because probability dropped below the onset threshold before reaching the frame count, suppress new barge-in attempts for ~500 ms. Prevents stutter interrupts on brief throat noises.
- **All gates exposed on `ArmOptions`** with defaults: `bargeInOnsetConfidence=0.80`, `bargeInOffsetConfidence=0.40`, `bargeInDebounceMs=250`, `bargeInReleaseMs=100`, `bargeInAmplitudeFloorDb=-45`, `bargeInCooldownMs=500`. Captain-tunable via the existing settings snapshot without code changes.
- **AEC constraints on the mic stream.** Ensure `getUserMedia` is called with `{ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }` everywhere the conversation pipeline opens a stream. Browser AEC is the first line of defense; the Schmitt detector is the second.
- Out of scope for v1: WebAudio-based echo cancellation using the TTS audio element as the reference signal — defer to AD-760b only if real-world false barge-ins persist after the above.

## Tests

### Vitest (ui/)
- `ProfileChatTab.conversationWiring.test.tsx`:
  - Right-click on mic button opens menu with `Press to talk` and `Conversation mode` items.
  - Selecting `Conversation mode` calls `armConversationMode` with the correct `agentId` and persists `hxi_chat_mic_mode_${agentId}=conversation`.
  - Selecting `Press to talk` calls disarm and persists `ptt`.
  - On mount, if persisted mode is `conversation` and `voiceEnabled=true`, arm fires automatically.
  - On `voiceEnabled` flip false → disarm; flip true (with persisted `conversation`) → arm.
  - On unmount, disarm fires.
  - Left-click mic while in Conversation mode preempts via `PRIORITY_PRESS_TO_TALK` (BF-318 invariant — assert no regression).
  - Keyboard `Shift+F10` on focused mic opens the same menu (a11y).
- `speechInput.continuousMode.test.ts`:
  - `startListening` configures `continuous=true`, `interimResults=true`.
  - Multiple interim results accumulate; final fires on 1.5 s gap or explicit stop.
  - Empty-result fallback to `whisperStt` triggers after N failures when Silero is available.
- Existing tests:
  - `conversationController.test.ts` — must still pass unchanged (engine is correct; only callers change).
  - `speechRecognitionArbiter.test.ts` — must still pass.

### Pytest (no backend changes expected)
- Targeted run for any backend touched: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -k "voice or speech or perception" -p no:xdist`.

## Out of scope (do NOT bundle into this AD)

- Server-side ASR endpoint changes.
- New voice modulation features.
- Native packaged tray app (AD-759).
- Changing the `voiceEnabled` default to true.

## Acceptance signals

- Opening a DM with an agent while `voiceEnabled=true` and `vad_engagement_enabled=true` engages duplex conversation automatically — Captain can speak, agent replies via TTS, Captain interrupts (barge-in) without clicking.
- Mic button in DM panel works even when `voiceEnabled=false`.
- Press-to-talk transcripts no longer drop on mid-utterance pauses.
- All existing ProfileChatTab / conversationController / speechRecognitionArbiter / speechInput tests pass.
- New vitest coverage for the three behaviors above.
- `npm run build` clean.

## Forward markers

- AD-760a — extend natural-conversation wiring to the IntentSurface omnibus (decomposer) chat, not just agent DMs.
- AD-760b — emit explicit telemetry when natural-conversation arm/disarm fires, so the Captain can audit "was duplex actually live during that conversation?" from journal logs.

## Engineering principles compliance

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- Type annotations on all new public TS exports.
- No emoji in any new UI element (HXI Design Principle #3).
- Mic button must keep behaving as press-to-talk override — never change BF-318 priority order.
- Tests cover happy path + flip + unmount + arbiter-preempt boundary.
