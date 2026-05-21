# Review: AD-760 — Voice conversation wiring + mic reliability
**Verdict:** ⚠️ Conditional
**Wire-up direction is correct, but two scope claims don't survive grep and three ambiguities (Schmitt-trigger placement, AEC site, Section-3 capability vs. caller) will burn Builder time if not pinned.**

Current highest AD in prompts/: **AD-766** (`ad-766-yeoman-agent-bridge-crew.md`). Highest AD in `PROGRESS.md` closed list: **AD-758**. AD-760 fits cleanly. Wave-plan id `185-voice-conversation-wiring` confirmed in `prompts/wave-plan.yaml:4066`.

## Required (must fix before building)

1. **WardRoom DM has no mic to wire.** Prompt Section 1 says: *"Wire the same context menu in: ... The WardRoom DM mic (verify path in `ui/src/components/wardroom/*`)"*. Grep across `ui/src/components/wardroom/**/*.tsx` for `startListening|speechInput|mic|Mic` returns **zero** matches. `WardRoomThreadDetail.tsx` and `ChatInput.tsx` have no mic affordance today. The only mic call sites in the codebase are `IntentSurface.tsx:2281` and `ProfileChatTab.tsx:621` (verified — only two matches besides test mocks). IntentSurface is explicitly deferred to forward-marker AD-760a. **Scope v1 to `ProfileChatTab.tsx` only**; file the WardRoom wiring as a new forward marker (suggest AD-760c — "Add mic + conversation-mode affordance to WardRoom DM ChatInput") so the prompt's deliverables match what's in the tree.

2. **Schmitt-trigger detector placement is unspecified.** Prompt says *"Barge-in uses a Schmitt-trigger (hysteresis) detector over the Silero probability stream"* but never says which file owns it. `voiceActivity._processFrame` (lines 1–46 of the function body — verified) already fans speech-start events on a single threshold, and the controller's `_onVadSpeechStart` only reacts to those events. Three plausible homes:
   - (A) Phase-aware threshold inside `voiceActivity._processFrame` (couples VAD to controller phase).
   - (B) Subscribe via `subscribePcm` from inside `conversationController.ts` and run the detector there.
   - (C) New module `ui/src/audio/bargeInDetector.ts` exposing `attachBargeInDetector(opts) → disarmFn`, consumed by the controller's `agent_speaking` branch.
   
   **Recommend (C)** for SRP — the existing controller is already 270+ lines and `voiceActivity.ts` should not learn controller state. Pin this in the prompt with: (a) the new module's exported API, (b) where in the controller it's armed/disarmed (state transitions to/from `agent_speaking`), (c) what the detector subscribes to (`subscribePcm` returning Float32 frame + score — verify the score is exposed on the PCM tap; currently `PcmTapHandler.onFrame(buffer, SAMPLE_RATE)` does **not** receive the Silero score, only the raw PCM. Either expose the score on `onFrame` via a new optional arg, or the detector re-runs the Silero session — adds CPU. **This is the load-bearing detail.**).

3. **AEC constraints land in `voiceActivity.ts:213`, not in `speechInput.ts`.** Browser `SpeechRecognition` uses its own internal audio capture and does **not** go through `getUserMedia` — confirmed by grep (no `getUserMedia` call in `speechInput.ts`). The only relevant call site for the conversation pipeline is `ui/src/audio/voiceActivity.ts:213` (`stream = await md.getUserMedia({ audio: true });`). `useCameraStream.ts:177` is camera, not mic. Replace the prompt's *"everywhere the conversation pipeline opens a stream"* with the explicit single site, and acknowledge that browser `SpeechRecognition`'s internal capture is **out of operator control** (the press-to-talk path can't have AEC applied from JS).

4. **Section 3 "set continuous=true and interimResults=true" is a caller change, not an API change.** Verified: `speechInput.ts:53,57` already exposes `continuous?: boolean` and `interimResults?: boolean` on `ListenOptions` (AD-474b). The fix is at the **call sites** (`ProfileChatTab.tsx:621` for v1 scope) — pass `{ continuous: true, interimResults: true }`, then add the accumulator + 1.5s end-of-speech gap timer **at the call site** or inside `speechInput.ts` as a new opt-in field (e.g., `endOfSpeechGapMs?: number`). Prompt must pick one — co-locating the gap timer inside `speechInput.ts` is cleaner DRY (IntentSurface gets the fix for free when AD-760a wires it) but adds API surface. **Recommend the new `endOfSpeechGapMs` field on `ListenOptions`** and a default of `1500`; flip `ProfileChatTab.tsx:621` to set it. Document explicitly that this does **not** change v0 behavior because the default for `continuous` stays `false`.

5. **`ArmOptions` extension is interface-compatible but needs a SEARCH/REPLACE block.** Verified: `conversationController.ts:68` defines `ArmOptions` with all fields optional except `agentId` — adding the six new optional barge-in tuning fields (`bargeInOnsetConfidence`, etc.) is non-breaking. But the prompt only describes the fields in prose. Add a minimal SEARCH/REPLACE showing the exact insertion order (after `bargeInEnabled?: boolean;` on line 84) so the Builder doesn't reverse-engineer it.

## Recommended

6. **Pin where the cooldown timer state lives.** *"Cooldown after a cancelled barge-in (500 ms)"* needs to be detector-local, not module-global on `conversationController.ts`, otherwise switching agents during cooldown carries the suppression across controllers. If the detector module is its own file (per Required #2 option C), this is naturally local; flag it explicitly.

7. **Add an agent-switch test.** Module-global controller state (`_agentId`, `_lease`, `_opts`) means arming for agent B implicitly disarms agent A. Add: "Arming for agent B while A is armed disarms A first (single-armed-controller invariant)." Two-component test in `ProfileChatTab.conversationWiring.test.tsx` — render A, switch to B, assert A's disarm fires, B's arm fires.

8. **Persistence cycle test for `voiceEnabled` toggle.** Prompt mentions disarm on false / re-arm on true. Add: "voiceEnabled flips false → disarm fires + `hxi_chat_mic_mode_${agentId}` still reads `conversation`; flips true → arm re-fires for the active agent."

9. **Shift+F10 a11y has no established pattern in HXI.** Grep for `onContextMenu` returns 3 sites (`DecisionSurface.tsx:133,173`, `ProfileChatTab.tsx:435`); **none** handle `Shift+F10` keyboard activation. The screen-share popover at `ProfileChatTab.tsx:435` is the closest analogue and lacks keyboard activation. Two options: (a) ship a small shared `useContextMenuKeyboard(menuOpen, setMenuOpen)` hook and apply it to both mic + screen-share menus (one extra wire, removes the gap for both), or (b) implement Shift+F10 only on the new mic menu and file AD-760d as a forward marker for screen-share + voice-picker a11y parity. **Recommend (a)** — the hook is ~10 lines and removes the inconsistency the first time the Captain tabs through the composer.

## Nits

- Replace the "Wire the same context menu in the WardRoom DM mic" sentence with one acknowledging the WardRoom DM has no mic affordance today; deliverable list reduces to one component (`ProfileChatTab.tsx`).
- Schmitt-trigger math sanity-checks: @ 16 kHz with 512-sample frames (~32 ms each), 8 onset frames ≈ 256 ms, 3 release frames ≈ 96 ms — matches the prompt's "~250 ms" / "~100 ms" claim. OK.
- The phrase *"All gates exposed on `ArmOptions` with defaults"* — add the note that defaults live in the **controller's read site** (not on the interface) so existing callers don't need to know about them.

## Verified Improvements

- `armConversationMode(opts: ArmOptions) → () => void` exported at `conversationController.ts:123`. Confirmed extensible (all fields except `agentId` are optional). `disarmConversationMode` exported at `:264`. `_onVadSpeechStart` at `:183`, `_onTranscript` at `:200`.
- `PRIORITY_PRESS_TO_TALK = 100`, `PRIORITY_CONVERSATION = 75`, `PRIORITY_WAKE_WORD = 50` confirmed at `speechRecognitionArbiter.ts:29-31`. `acquire`/`release`/lease shape (`AcquireOptions`, `Lease`) confirmed at `:33-58`. BF-318 preemption invariant preserved: press-to-talk always wins over conversation.
- `speechInput.ts:53,57` — `continuous?` and `interimResults?` already part of `ListenOptions` (AD-474b). Current `ProfileChatTab.tsx:621` caller passes neither (defaults to `false`/`false`), confirming the prompt's diagnosis of single-shot behavior.
- `whisperStt.armWhisperStt()` at `whisperStt.ts:154`, `onTranscript(listener)` at `:184`. Used by the conversation controller's `_wireSubscriptionsAndListen()`.
- `voiceActivity.subscribePcm(handler)` at `:285`; `PcmTapHandler.onFrame(buffer, SAMPLE_RATE)` does **not** currently receive the Silero score — relevant to Required #2.
- `voice.stopSpeaking()` confirmed at `voice.ts:364`. Imported by the controller as `_stopSpeaking` at `conversationController.ts:58`.
- `ProfileChatTab.tsx:610-657` — the AD-718 mic button is present and uses `pulse-mic` keyframe. Adjacent share-screen `onContextMenu` popover at `:435` is the right reference pattern for the new mic context menu (same composer row, same styling).
- localStorage keys: `hxi_chat_screen_mode_${agentId}` (`ProfileChatTab.tsx:25`), `hxi_chat_tts_${agentId}` (`:50`). Proposed `hxi_chat_mic_mode_${agentId}` is consistent.
- `getUserMedia({ audio: true })` confirmed at `voiceActivity.ts:213` — no AEC constraints today (Required #3 fix site).
- Existing tests `ProfileChatTabVoice.test.tsx`, `ProfileChatTab.screenShare.test.tsx`, `conversationController.test.ts`, `speechRecognitionArbiter.test.ts` confirmed; the new vitest files are additive.

## Wave 185 GATE 1 recommendation: **YELLOW**

Five Required findings — all addressable in-prompt without a re-architecture. The shape of the AD is correct; the gaps are scope boundary (WardRoom phantom), placement ambiguity (Schmitt detector), and capability-vs-caller framing (Section 3). Apply Required fixes → re-review → GREEN.


## Re-review (2026-05-21)

**Verdict:** ✅ Approved
**All five Required findings cleared. Three of the five Recommended findings applied; two (cooldown-storage flag, defaults-at-read-site flag) were folded into the Required #2 and #5 patches respectively.**

### Required clearances
1. **WardRoom phantom** — scope now ProfileChatTab-only; AD-760c forward marker filed.
2. **Schmitt detector placement** — `ui/src/audio/bargeInDetector.ts` named as a new module with full API surface, state-machine spec, controller wiring contract, and cooldown locality invariant. `PcmTapHandler.onFrame` score extension explicitly required and called out as backward-compatible.
3. **AEC site** — `voiceActivity.ts:213` named explicitly; press-to-talk path's lack of AEC control documented.
4. **Section 3 framing** — capability-already-exists noted; new `endOfSpeechGapMs?` field on `ListenOptions` with default 1500; default `continuous=false` invariant preserved for IntentSurface (AD-760a) and other callers.
5. **ArmOptions extension** — exact SEARCH/REPLACE block landed; defaults explicitly at controller read site, not on interface.

### Recommended applied
- Agent-switch test case added (single-armed-controller invariant).
- `voiceEnabled` false→true cycle preserves persisted preference, asserted in test list.
- Shared `useContextMenuKeyboard` hook with AD-760d filed for backfill to existing context menus.
- New `bargeInDetector.test.ts` test file enumerated.

### Recommended deferred to Builder judgment
- The choice between detector's `onBargeIn` calling `_onVadSpeechStart()` vs. directly `_stopSpeaking() + _setState('listening')` is left for the Builder to pick during implementation (the prompt now flags this explicitly as a binary SRP decision rather than a freeform).

**Ready for GATE 1 → GREEN.**
