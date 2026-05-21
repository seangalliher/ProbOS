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

### 1. Wire `armConversationMode` into the DM surfaces
- In `ProfileChatTab.tsx`:
  - On mount (when the panel becomes visible for `agentId`), if `voiceEnabled` is true AND `perception.vad_engagement_enabled` is true, call `armConversationMode({ agentId, historyProvider, onTranscript, onAgentReply })`.
  - On unmount or agent switch, call the returned disarm function.
  - The `onTranscript` callback populates the input box (preview pill) before submission; `onAgentReply` triggers the same TTS path the manual flow uses.
  - When `voiceEnabled` flips false, disarm. When it flips true, arm.
- Same wiring in the WardRoom DM panel where 1:1 conversations live (verify path in `ui/src/components/wardroom/*` — the WardRoom DM component is the second surface that needs parity).
- Preserve the manual mic button as a fallback / explicit override (press-to-talk at `PRIORITY_PRESS_TO_TALK` correctly preempts the conversation lease per BF-318).

### 2. Decouple mic button from global voice toggle (perception side)
- The mic button must work standalone — independent of `voiceEnabled`.
- In `App.tsx`, when the user clicks the mic in any DM, ensure the perception VAD loop is started on-demand (one-shot bring-up) if `perception.vad_engagement_enabled` is true but `startVoiceActivity` hasn't yet been called this session due to autoplay policy. Resume the `AudioContext` from the mic click handler (user gesture satisfies autoplay).
- If `perception.vad_engagement_enabled=false`, the mic button still works (uses browser SpeechRecognition directly without Silero endpointing) — surface a one-line hint in the existing `MicPermissionHint` component when transcripts come back empty repeatedly.

### 3. Press-to-talk reliability fix
- In `speechInput.ts`, set `continuous=true` and `interimResults=true` on the `SpeechRecognition` instance, and accumulate final transcripts until either: (a) the caller calls `stopListening()`, or (b) a 1.5 s end-of-speech gap is observed (configurable). This eliminates the "auto-ends on first pause, returns empty" failure mode.
- Add a fallback: if 2 consecutive `startListening` calls return empty transcripts AND Silero VAD is available, route the next press-to-talk through `whisperStt.armWhisperStt()` with a short bounded window instead of `SpeechRecognition`. This gives the Captain a reliable local-Whisper path on the press-to-talk button without forcing the natural-conversation state machine.

## Tests

### Vitest (ui/)
- `ProfileChatTab.conversationWiring.test.tsx`:
  - On mount with `voiceEnabled=true` + `vad_engagement_enabled=true`, `armConversationMode` is called with the correct `agentId`.
  - On `voiceEnabled` flip false → true, arm fires.
  - On unmount, disarm fires.
  - When the press-to-talk mic is clicked while the conversation is armed, the arbiter preempts conversation in favor of `PRIORITY_PRESS_TO_TALK` (BF-318 invariant — already covered, just assert no regression here).
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
