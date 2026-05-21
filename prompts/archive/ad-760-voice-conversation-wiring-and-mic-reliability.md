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
- Wire the context menu in `ui/src/components/profile/ProfileChatTab.tsx` (1:1 agent DM panel) ONLY for v1. **WardRoom DM has no mic affordance today** (verified: zero `startListening|speechInput|mic` matches in `ui/src/components/wardroom/**/*.tsx`). Adding a mic + conversation-mode affordance to `WardRoomThreadDetail.tsx` / `ChatInput.tsx` is filed as forward marker AD-760c.
- The `onTranscript` callback populates the input box (preview pill) before submission; `onAgentReply` triggers the same TTS path the manual flow uses.
- Accessibility: the mic button must also be activatable as a menu via keyboard — `Shift+F10` or the context-menu key on the focused mic opens the same popover. `aria-haspopup="menu"` on the button. Ship the activation logic as a small shared hook `ui/src/hooks/useContextMenuKeyboard.ts` (input: `(open: boolean, setOpen: (v: boolean) => void)`; output: `{ onKeyDown }` returning a React `KeyboardEventHandler`). Apply it to the new mic menu in this AD; AD-760d backfills the same hook into the existing screen-share, volume, and voice-picker `onContextMenu` sites for a11y parity.

### 2. Decouple mic button from global voice toggle (perception side)
- The mic button must work standalone — independent of `voiceEnabled`.
- In `App.tsx`, when the user clicks the mic in any DM, ensure the perception VAD loop is started on-demand (one-shot bring-up) if `perception.vad_engagement_enabled` is true but `startVoiceActivity` hasn't yet been called this session due to autoplay policy. Resume the `AudioContext` from the mic click handler (user gesture satisfies autoplay).
- If `perception.vad_engagement_enabled=false`, the mic button still works (uses browser SpeechRecognition directly without Silero endpointing) — surface a one-line hint in the existing `MicPermissionHint` component when transcripts come back empty repeatedly.

### 3. Press-to-talk reliability fix
- **Capability already exists**: `ListenOptions` in `speechInput.ts:53,57` already exposes `continuous?: boolean` and `interimResults?: boolean` (AD-474b). The current `ProfileChatTab.tsx:621` call site passes neither, so they default to `false`/`false`.
- **Fix at the call site + extend `ListenOptions`**: add a new optional `endOfSpeechGapMs?: number` field to `ListenOptions` (default 1500). When set together with `continuous: true`, `speechInput.ts` accumulates final transcripts and only fires `onResult` after either (a) the caller calls `stopListening()`, or (b) the configured silence gap elapses with no new finals. Default behaviour (no `endOfSpeechGapMs`, `continuous=false`) is unchanged — load-bearing for IntentSurface (deferred to AD-760a) and any other caller.
- Flip `ProfileChatTab.tsx:621` to pass `{ continuous: true, interimResults: true, endOfSpeechGapMs: 1500 }`.
- Add a fallback: if 2 consecutive `startListening` calls return empty transcripts AND Silero VAD is available, route the next press-to-talk through `whisperStt.armWhisperStt()` with a short bounded window instead of `SpeechRecognition`. This gives the Captain a reliable local-Whisper path on the press-to-talk button without forcing the natural-conversation state machine.

### 4. Conversation mode: agent-speaking handling + barge-in robustness
- **Do not mute the mic during `agent_speaking`.** Silero VAD keeps running so barge-in has zero warm-up latency.
- The existing state machine already gates transcript submission on `state === 'listening'`, so whisperStt output is dropped while the agent is speaking. Keep that invariant; add an explicit assertion in the controller's `_onTranscript` to log-and-drop when called outside `listening`.
- **Barge-in uses a Schmitt-trigger (hysteresis) detector over the Silero probability stream, not a single threshold.** Separate onset and offset thresholds prevent flapping on borderline audio. The detector is a **new module** `ui/src/audio/bargeInDetector.ts` (SRP — `voiceActivity.ts` stays content-agnostic, `conversationController.ts` stays state-machine-only).

  **API**:
  ```ts
  export interface BargeInOptions {
    onsetConfidence: number;     // default 0.80
    offsetConfidence: number;    // default 0.40
    debounceFrames: number;      // sustained-onset frame count, default 8 (~256 ms)
    releaseFrames: number;       // release frame count, default 3 (~96 ms)
    amplitudeFloorDb: number;    // default -45 (frames below this never count)
    cooldownMs: number;          // default 500 (suppression after cancelled onset)
    onBargeIn: () => void;       // fires when detector transitions below → above
  }
  export function attachBargeInDetector(opts: BargeInOptions): () => void; // returns disarm
  ```

  Detector subscribes via `voiceActivity.subscribePcm(handler)`. **`PcmTapHandler.onFrame` must be extended to forward the per-frame Silero score** as an optional third arg (`onFrame(buffer: Float32Array, sampleRate: number, score?: number) => void`) — today it only receives `buffer` and `sampleRate`, so the detector cannot run without re-evaluating Silero (CPU duplication). The extension is backward-compatible (existing subscribers ignore the new arg). Update `voiceActivity._processFrame` to pass `score` to the fan-out.

  **State machine** (per detector instance): starts `below`. Per-frame, compute RMS dBFS; if below `amplitudeFloorDb`, reset onset counter. Else if `score >= onsetConfidence`, increment onset counter; if it reaches `debounceFrames`, transition to `above`, fire `onBargeIn`, reset counters. If onset counter is partially built (>0) and `score` drops below `onsetConfidence`, cancel — enter cooldown for `cooldownMs` (timer local to this detector instance, **never module-global** — prevents cross-agent leakage when controller re-arms for a different agent). While `above`, only release when `score < offsetConfidence` for `releaseFrames`. The 0.4 gap between onset (0.80) and offset (0.40) absorbs natural voiced/unvoiced oscillation.

  **Controller wiring**: in `conversationController.ts`, attach the detector when `_setState('agent_speaking')` is called; the detector's `onBargeIn` invokes the existing `_onVadSpeechStart()` barge-in branch (or directly calls `_stopSpeaking()` + `_setState('listening')` — pick one for SRP). Detach (`disarmFn()`) on state exit from `agent_speaking`.

  | Phase | Detector active | Onset | Offset | Onset frames | Release frames |
  |---|---|---|---|---|---|
  | `listening` | no — use voiceActivity's existing speech-start fan-out | 0.50 | 0.35 | 3 (~96 ms) | 3 (~96 ms) |
  | `agent_speaking` (barge-in) | yes — bargeInDetector | **0.80** | **0.40** | 8 (~256 ms) | 3 (~96 ms) |
- **Why 0.80 onset during playback.** Silero's known false-positive bands for TTS bleed sit in the 0.55–0.70 range on most laptop AEC stacks. Above 0.75 the model rarely confuses synthesized speech for live human voice. This is empirical, not theoretical — defaults are tunable.
- **Amplitude floor.** Reject frames whose RMS is below ~-45 dBFS even if Silero's probability is high. Guards against the known false-positive on low-level steady noise (HVAC, fan). Applied as a precondition on every frame before it counts toward the sustained-onset tally.
- **Cooldown after a cancelled barge-in.** If the sustained-onset timer cancels because probability dropped below the onset threshold before reaching the frame count, suppress new barge-in attempts for ~500 ms. Prevents stutter interrupts on brief throat noises.
- **All gates exposed on `ArmOptions`** with defaults: `bargeInOnsetConfidence=0.80`, `bargeInOffsetConfidence=0.40`, `bargeInDebounceMs=250`, `bargeInReleaseMs=100`, `bargeInAmplitudeFloorDb=-45`, `bargeInCooldownMs=500`. Captain-tunable via the existing settings snapshot without code changes. **Defaults live at the controller read site** (where the detector is attached) — not on the interface — so existing callers continue to omit them.

  Exact `ArmOptions` extension in `conversationController.ts`:
  ```ts
  // SEARCH (immediately after `bargeInEnabled?: boolean;` on line 84):
    bargeInEnabled?: boolean;
  }

  // REPLACE:
    bargeInEnabled?: boolean;
    /** AD-760: Schmitt-trigger barge-in detector tuning. All optional;
     *  defaults applied at the controller read site so existing callers
     *  remain source-compatible. See bargeInDetector.ts for semantics. */
    bargeInOnsetConfidence?: number;
    bargeInOffsetConfidence?: number;
    bargeInDebounceMs?: number;
    bargeInReleaseMs?: number;
    bargeInAmplitudeFloorDb?: number;
    bargeInCooldownMs?: number;
  }
  ```
- **AEC constraints on the mic stream — single site.** Update `ui/src/audio/voiceActivity.ts:213` from `md.getUserMedia({ audio: true })` to `md.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })`. This is the only `getUserMedia` site the conversation pipeline owns. The press-to-talk path uses browser `SpeechRecognition`, which performs its own internal audio capture **not** reachable from JS — AEC there is browser-implementation-defined and out of operator control. Browser AEC on the VAD stream is the first line of defense; the Schmitt detector is the second.
- Out of scope for v1: WebAudio-based echo cancellation using the TTS audio element as the reference signal — defer to AD-760b only if real-world false barge-ins persist after the above.

## Tests

### Vitest (ui/)
- `ProfileChatTab.conversationWiring.test.tsx`:
  - Right-click on mic button opens menu with `Press to talk` and `Conversation mode` items.
  - Selecting `Conversation mode` calls `armConversationMode` with the correct `agentId` and persists `hxi_chat_mic_mode_${agentId}=conversation`.
  - Selecting `Press to talk` calls disarm and persists `ptt`.
  - On mount, if persisted mode is `conversation` and `voiceEnabled=true`, arm fires automatically.
  - On `voiceEnabled` flip false → disarm; flip true (with persisted `conversation`) → arm. Persisted preference (`hxi_chat_mic_mode_${agentId}`) survives the cycle.
  - **Agent-switch invariant**: mount panel for agent A with persisted `conversation`, switch to agent B with persisted `conversation` — assert A's disarm fires before B's arm (single-armed-controller invariant from `conversationController.ts:78-82`).
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
- New tests for the detector module:
  - `bargeInDetector.test.ts`: onset latency = `debounceFrames` exactly; release latency = `releaseFrames`; amplitude floor rejects high-score low-RMS frames; cancelled-onset cooldown suppresses the next onset for `cooldownMs`; cooldown is per-detector-instance (two detectors don't share state).

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
- AD-760c — add mic + conversation-mode affordance to the WardRoom DM (`WardRoomThreadDetail.tsx` / `ChatInput.tsx`); no mic exists in that surface today.
- AD-760d — a11y parity: keyboard `Shift+F10` activation for the existing screen-share, volume, and voice-picker context menus (`ProfileChatTab.tsx:435`, `DecisionSurface.tsx:133,173`). AD-760 ships the helper hook used for the new mic menu; this AD applies it across the established `onContextMenu` sites.

## Engineering principles compliance

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- Type annotations on all new public TS exports.
- No emoji in any new UI element (HXI Design Principle #3).
- Mic button must keep behaving as press-to-talk override — never change BF-318 priority order.
- Tests cover happy path + flip + unmount + arbiter-preempt boundary.
