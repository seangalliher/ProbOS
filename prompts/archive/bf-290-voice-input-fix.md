# BF-290 — ProfileChatTab voice input: PTT stuck after fallback, conversation mode handlers missing

**Status:** Ready for build
**Closes:** #763
**Estimated tests:** 4 new Vitest cases
**Scope:** `ui/src/components/profile/ProfileChatTab.tsx` (production), `ui/src/__tests__/ProfileChatTab.bf290.test.tsx` (new test file)
**Out of scope:** speechInput.ts, conversationController.ts, whisperStt.ts, voice.ts, server-side. Do NOT touch the live runtime data dir.

---

## Problem

Two production-blocking bugs in the agent DM voice input UX. Captain-confirmed live in HXI.

### Bug 1 — PTT stuck after whisper fallback

`ui/src/components/profile/ProfileChatTab.tsx` mic button onClick. When the browser SpeechRecognition returns two consecutive empty transcripts, the handler arms the local Whisper-STT fallback and bails:

```
747: setListening(true);
748: if (emptyTranscriptCountRef.current >= 2) {
749:   // ... reset counter, subscribe to whisperStt onTranscript ...
761:   armWhisperStt();
762:   return;          // <-- listening stays true forever if user gives up
763: }
```

If the operator presses the mic but never speaks loud enough for VAD, `listening` stays `true`. The next press takes the `if (listening) { stopListening(); setListening(false); return; }` branch at lines 738-741 — but `stopListening()` is a no-op for whisperStt (it only stops the browser SR), so the whisperStt subscription leaks. Press after that toggles UI state but the mic is in a half-armed state, and the user perceives "PTT works once, then stuck."

### Bug 2 — Conversation mode silently drops agent replies

`ui/src/components/profile/ProfileChatTab.tsx` lines 119-133 build the `ArmOptions` passed to `armConversationMode()`:

```tsx
const armOpts: ArmOptions = {
  agentId,
  historyProvider: () => { /* last 20 msgs */ },
  onTranscript: (text: string) => { setInput(text); },
  // MISSING: onAgentReply
  // MISSING: onStateChange (cosmetic)
};
```

`ui/src/audio/conversationController.ts:289` calls `_opts?.onAgentReply?.(replyText);` — undefined handler means the reply text is silently dropped. The controller advances to `agent_speaking` (line 294) and waits for `markAgentReplyComplete()` to be called from the TTS-end side. Nobody ever calls it. Controller stuck in `agent_speaking` forever; next mic press finds it armed and `armConversationMode` returns early at line 184. Net effect: conversation mode never produces an audible reply, never appends to the chat thread, never recovers.

---

## Solution

Two surgical edits in one file. No new modules, no new dependencies.

### Section 1 — PTT stuck fix

Add `setListening(false)` before the early-return so the UI reflects "not actively capturing browser SR" while we wait on whisper. The existing whisper `onTranscript` callback at line 758 already sets `listening=false` after transcription, so this is the matching pre-return cleanup.

Also clean up the leaked whisper subscription if the operator presses again while whisper is armed: add `disarmWhisperStt()` to the stopListening branch.

#### SEARCH/REPLACE 1.1 — `ui/src/components/profile/ProfileChatTab.tsx` (stopListening branch)

```
===SEARCH===
                if (listening) {
                  stopListening();
                  setListening(false);
                  return;
                }
                setListening(true);
===REPLACE===
                if (listening) {
                  stopListening();
                  // BF-290: also disarm whisper fallback in case the previous
                  // press armed it but the operator never spoke. stopListening
                  // only stops the browser SpeechRecognition; whisperStt is a
                  // separate subsystem that needs explicit teardown.
                  try { disarmWhisperStt(); } catch { /* Tier-2 */ }
                  setListening(false);
                  return;
                }
                setListening(true);
===END REPLACE===
```

#### SEARCH/REPLACE 1.2 — `ui/src/components/profile/ProfileChatTab.tsx` (whisper-fallback early return)

```
===SEARCH===
                  armWhisperStt();
                  return;
                }
                let gotResult = false;
===REPLACE===
                  armWhisperStt();
                  // BF-290: clear visual "listening" state so the operator can
                  // press again to abort (which now also disarms whisper via
                  // the stopListening branch above). The whisper onTranscript
                  // handler at the top of this block sets listening=false on
                  // success; this matches that semantics on the give-up path.
                  setListening(false);
                  return;
                }
                let gotResult = false;
===END REPLACE===
```

### Section 2 — Conversation mode handlers

Wire `onAgentReply` to:
1. Append the agent reply to the per-agent conversation thread via `addAgentMessage`.
2. Speak the reply via `speakResponse(stripMarkdownForSpeech(replyText), voiceProfile ?? undefined, agentId)` when `ttsEnabled` is true.
3. Subscribe to `onSpeechEvent` (one-shot) to call `markAgentReplyComplete()` when the matching `'end'` event for this agent fires, OR call it immediately when TTS is disabled.

Also wire `onStateChange` as a one-line console.info — cheap, helps debugging, no UI effect. Skip if it complicates the diff.

The handler must import `markAgentReplyComplete` from `../../audio/conversationController` (already the source of `armConversationMode` / `disarmConversationMode`).

#### SEARCH/REPLACE 2.1 — `ui/src/components/profile/ProfileChatTab.tsx` (import)

```
===SEARCH===
import {
  armConversationMode,
  disarmConversationMode,
  type ArmOptions,
} from '../../audio/conversationController';
===REPLACE===
import {
  armConversationMode,
  disarmConversationMode,
  markAgentReplyComplete,
  type ArmOptions,
} from '../../audio/conversationController';
import { onSpeechEvent } from '../../audio/voice';
===END REPLACE===
```

#### SEARCH/REPLACE 2.2 — `ui/src/components/profile/ProfileChatTab.tsx` (ArmOptions wiring)

```
===SEARCH===
    const armOpts: ArmOptions = {
      agentId,
      historyProvider: () => {
        const conv = useStore.getState().agentConversations.get(agentId);
        const msgs = conv?.messages ?? [];
        return msgs.slice(-20).map((m) => ({
          role: m.role === 'user' ? 'user' : 'agent',
          content: m.text,
        }));
      },
      onTranscript: (text: string) => {
        setInput(text);
      },
    };
===REPLACE===
    const armOpts: ArmOptions = {
      agentId,
      historyProvider: () => {
        const conv = useStore.getState().agentConversations.get(agentId);
        const msgs = conv?.messages ?? [];
        return msgs.slice(-20).map((m) => ({
          role: m.role === 'user' ? 'user' : 'agent',
          content: m.text,
        }));
      },
      onTranscript: (text: string) => {
        setInput(text);
      },
      // BF-290: wire agent-reply path. Without this the controller posts the
      // user transcript, gets a reply, calls _opts?.onAgentReply?.(replyText)
      // which is undefined, advances to agent_speaking, and waits forever
      // for markAgentReplyComplete() to be called. Stuck state blocks the
      // next mic press because armConversationMode returns early when armed.
      onAgentReply: (replyText: string) => {
        // 1. Append to the per-agent conversation so the operator sees it
        // in the DM thread.
        useStore.getState().addAgentMessage(agentId, 'agent', replyText);
        // 2. Speak it (when TTS is enabled for this agent) and signal
        // controller completion when the TTS 'end' event fires. When TTS
        // is disabled, signal completion immediately so the controller
        // advances to silence_pending and the silence timer can run.
        const currentTtsEnabled = localStorage.getItem(ttsKey) === '1'
          || (localStorage.getItem(ttsKey) === null && useStore.getState().voiceEnabled);
        if (!currentTtsEnabled) {
          markAgentReplyComplete();
          return;
        }
        // Subscribe BEFORE speakResponse so we don't race the 'start' event.
        // We listen for the matching 'end' for this agent_id, then unsubscribe.
        const unsub = onSpeechEvent((event) => {
          if (event.type !== 'end') return;
          if (event.agent_id && event.agent_id !== agentId) return;
          try { unsub(); } catch { /* Tier-2 */ }
          markAgentReplyComplete();
        });
        speakResponse(stripMarkdownForSpeech(replyText), voiceProfile ?? undefined, agentId);
      },
      onStateChange: (state) => {
        console.info(`AD-747/BF-290: conversation state for ${agentId}: ${state}`);
      },
    };
===END REPLACE===
```

Notes for the Builder:
- `voiceProfile` and `ttsKey` are already in scope (declared above this `useEffect`).
- `useStore`, `speakResponse`, `stripMarkdownForSpeech` are already imported at the top of the file — do not re-import.
- The `localStorage.getItem(ttsKey) === '1' || (... === null && voiceEnabled)` mirrors the `useState` initializer at the top of the component so the handler reads fresh state at call time (not stale closure from when the effect was set up).

---

## Tests

Create **new** file `ui/src/__tests__/ProfileChatTab.bf290.test.tsx`. The existing `ProfileChatTabVoice.test.tsx` and `ProfileChatTab.conversationWiring.test.tsx` are fine to keep untouched; this file isolates the BF-290 regression checks.

Mock surface (copy the hoisted-mock pattern from `ProfileChatTab.conversationWiring.test.tsx` lines 6-40 — it already mocks `speechInput`, `voice`, `conversationController`, `whisperStt` correctly). Add `markAgentReplyComplete` to the conversationController mock.

### Test 1 — PTT happy path: 2 presses, mic toggles correctly

- Render `ProfileChatTab` with `agentId='a1'`.
- Click mic button — expect `startListeningMock` called once, `listening` UI in armed state.
- Click mic button again — expect `stopListeningMock` called once, `disarmWhisperSttMock` called once (BF-290 cleanup), `listening` UI in idle state.

### Test 2 — PTT recovery after whisper fallback

- Pre-seed: directly mutate the test by calling `emptyTranscriptCountRef` via two simulated empty results. The cleanest path: invoke `startListening` mock with `(onResult, onError, onEnd, _opts)`, then call `onError()` and `onEnd()` to drive `emptyTranscriptCountRef.current += 1` twice across two presses.
- Third press should hit the whisper-fallback branch: expect `armWhisperSttMock` called, `listening` set back to **false** after the early-return (BF-290 fix), `whisperOnTranscriptMock` subscribed.
- Fourth press (operator gave up on whisper): expect `stopListeningMock` AND `disarmWhisperSttMock` both called (BF-290 cleanup).
- After cleanup, fifth press should start a fresh `startListeningMock` session.

### Test 3 — Conversation mode 2-turn exchange

- Enable conversation mode: `localStorage.setItem('hxi_chat_mic_mode_a1', 'conversation')` and `useStore.setState({ voiceEnabled: true })` before render.
- Render. Expect `armConversationModeMock` called with an `ArmOptions` that has BOTH `onAgentReply` AND `onStateChange` defined (BF-290 fix — assert via `expect.objectContaining({ onAgentReply: expect.any(Function), onStateChange: expect.any(Function) })`).
- Capture the `onAgentReply` callback from the most recent call: `const onAgentReply = armConversationModeMock.mock.calls[0][0].onAgentReply`.
- Invoke it with `'Hello, Captain.'`. Expect:
  - `useStore.getState().agentConversations.get('a1')?.messages` contains a message with role='agent', text='Hello, Captain.'
  - `speakResponseMock` called with `('Hello, Captain.', undefined, 'a1')` (no voiceProfile fetched yet in jsdom).
  - `onSpeechEventMock` called once (subscription).
- Simulate TTS 'end': retrieve the listener passed to `onSpeechEventMock`, call it with `{ type: 'end', agent_id: 'a1', utterance: {} }`. Expect `markAgentReplyCompleteMock` called once.
- Invoke `onAgentReply` again with `'Second turn.'`. Expect the message count to be 2 and `speakResponseMock` called a second time.

### Test 4 — Conversation mode TTS-disabled path

- Set `localStorage.setItem('hxi_chat_tts_a1', '0')` before render so per-agent TTS is off.
- Render with `voiceEnabled: true` and conversation mode armed.
- Invoke captured `onAgentReply('Hi.')`. Expect:
  - `addAgentMessage` path runs (message appended).
  - `speakResponseMock` is **NOT** called.
  - `markAgentReplyCompleteMock` called **immediately** (no waiting on speech 'end').

---

## What this does NOT change

- `conversationController.ts` — already correct; the bug was missing handlers at the consumer side.
- `speechInput.ts` — continuous mode + gap accumulator behavior left as-is.
- `whisperStt.ts` — arm/disarm semantics unchanged.
- `voice.ts` — TTS lifecycle unchanged.
- Server-side routes, agents, runtime — zero Python changes.
- PTT-as-onMouseDown/onMouseUp refactor (forward marker, separate AD if Captain wants it).

---

## Tracking

Update `PROGRESS.md`:
- Add to BF closed list: `BF-290 (CLOSED 2026-05-22) — ProfileChatTab voice: PTT stuck after whisper fallback (missing setListening(false) + disarmWhisperStt cleanup) and conversation mode broken (missing onAgentReply / onStateChange handlers). Closes #763. ~30 LOC + 4 Vitest tests.`

Update `docs/development/roadmap.md` Bug Tracker table: add row for BF-290.

No DECISIONS.md entry — pure consumer-side wiring bug, no architectural decision.

---

## Acceptance Criteria

1. Both SEARCH/REPLACE pairs in Section 1 applied; both pairs in Section 2 applied.
2. New file `ui/src/__tests__/ProfileChatTab.bf290.test.tsx` exists with **at least 4 passing tests** covering the scenarios above.
3. **Gate A (Vitest):** `cd ui; npx vitest run` — full UI suite green. No regressions in existing `ProfileChatTab.test.tsx` / `ProfileChatTabVoice.test.tsx` / `ProfileChatTab.conversationWiring.test.tsx` / `ProfileChatTab.screenShare.test.tsx`.
4. **Gate B (production bundle):** `cd ui; npm run build` — must succeed. This runs `tsc -b && vite build`; a TypeScript error blocks bundle output, which means the operator's browser will keep serving the stale pre-fix bundle. Per BF-279 (2026-05-13 lesson): Vitest passing is NOT sufficient evidence that the change reaches the operator. **Both gates required. Either failing = stop and report.**
5. Single commit message: `BF-290: ProfileChatTab voice — PTT stuck after fallback fix + conversation mode handlers. Closes #763.` Push to `origin/main`.
6. PROGRESS.md and roadmap.md Bug Tracker updated in the same commit.
7. Do NOT touch anything under `C:\Users\seang\AppData\Local\ProbOS\` (live runtime data dir). Do NOT restart or touch the running ProbOS process. Test against the repo's `ui/` only.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`. Specifically:
   - HXI Design Principles #3 (no emoji), #4 (motion communicates state) — neither is touched here, but do not introduce emoji in the new code or test fixtures.
   - Tier-2 log-and-degrade on the `unsub()` and `disarmWhisperStt()` calls (already in the SEARCH/REPLACE blocks).
   - Type annotations on the new `onAgentReply` and `onStateChange` lambdas (already typed via `ArmOptions` inference).
   - No `try/except Exception` wrappers around imports (BF-274 lesson) — the imports added in 2.1 are static and resolved at module load.

---

## Verified Against Codebase (2026-05-22)

```
grep -n "armWhisperStt\(\|emptyTranscriptCountRef" ui/src/components/profile/ProfileChatTab.tsx
  747: setListening(true);
  748: if (emptyTranscriptCountRef.current >= 2) {
  752:   emptyTranscriptCountRef.current = 0;
  761:   armWhisperStt();
  762:   return;    <-- early-return without setListening(false) (Bug 1)

grep -n "armConversationMode\|onAgentReply\|markAgentReplyComplete" ui/src/audio/conversationController.ts
  176: export function armConversationMode(opts: ArmOptions): () => void {
  289:   _opts?.onAgentReply?.(replyText);   <-- silent drop when undefined (Bug 2)
  294:   _setState('agent_speaking');
  305: export function markAgentReplyComplete(): void {

grep -n "ArmOptions" ui/src/audio/conversationController.ts
  68: export interface ArmOptions {
  75:   onStateChange?: (state: ConversationState) => void;
  78:   onTranscript?: (text: string) => void;
  80:   onAgentReply?: (text: string) => void;

grep -n "addAgentMessage" ui/src/store/useStore.ts
  367: addAgentMessage: (agentId: string, role: 'user' | 'agent', text: string) => void;
  956: addAgentMessage: (agentId, role, text) => {

grep -n "^export function" ui/src/audio/voice.ts
  49: export function onSpeechEvent(fn: SpeechListener): () => void
  200: export function speakResponse(text, profile?, agent_id?, emotion?): void
  419: export function stripMarkdownForSpeech(text: string): string

grep -n "SpeechEvent " ui/src/audio/voice.ts
  36: export interface SpeechEvent {
  37:   type: SpeechEventType;       <-- 'start' | 'end' | 'boundary'
  38:   agent_id?: string;
  39:   utterance: SpeechSynthesisUtterance;
  42:   source?: SpeechEventSource;

grep -n "\"build\":\|\"test\":" ui/package.json
  7:  "build": "tsc -b && vite build",
  10: "test": "vitest run",

ls ui/src/__tests__/ProfileChatTab*
  ProfileChatTab.test.tsx
  ProfileChatTab.conversationWiring.test.tsx  <-- mock pattern to copy
  ProfileChatTab.screenShare.test.tsx
  ProfileChatTabVoice.test.tsx
  (ProfileChatTab.bf290.test.tsx — NEW, created by this prompt)
```

All concrete claims in this prompt map to a grep hit above. Builder: re-grep before committing if any of these line numbers have drifted since draft time.
