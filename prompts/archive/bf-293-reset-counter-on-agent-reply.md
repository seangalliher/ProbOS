# BF-293 — Reset PTT empty-transcript counter on agent reply

**Status:** Ready
**Closes:** #766
**Estimated tests:** 3 new (in `ui/src/__tests__/ProfileChatTab.bf293.test.tsx`) + full ProfileChatTab regression
**Risk:** Low — single 7-line `useEffect` addition, no behavior change to existing paths.

---

## Problem

`emptyTranscriptCountRef` in `ProfileChatTab.tsx` accumulates one increment per empty browser-`SpeechRecognition` result (line 840). Once it reaches `>= 2`, the next mic press routes through the `whisperStt` fallback instead of native browser SR (line 803).

The counter resets in three places today:
1. On agent-switch (`useEffect` on `[agentId]`, line 106).
2. When a browser-SR transcript succeeds (line 831).
3. When the whisper fallback fires (line 807).

It does **not** reset when the agent replies to the user. So a stale count from earlier in the conversation (e.g. two empty presses during a noisy moment) silently arms the whisper fallback for a press that happens minutes later — after the operator has had several successful text-only or text+TTS turns in between. From the operator's POV the mic appears to behave normally, then surprise-switches to whisper with no UI indication.

The conversational "round-trip complete" boundary is the natural reset point: once the agent has replied, the previous PTT failure context is no longer relevant.

## Solution

Add a single `useEffect` on `[messages.length]` adjacent to the existing auto-scroll effect (`ProfileChatTab.tsx:264-267`). On every messages append, check whether the last message is from the agent; if so, reset the counter.

Place the new effect **immediately after** the auto-scroll effect so the two `messages.length` effects stay grouped.

---

## Section 1: Add the reset effect

### File: `ui/src/components/profile/ProfileChatTab.tsx`

```
===SEARCH===
  const messages = conversation?.messages ?? [];

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  // AD-430b: Fetch cross-session memories on mount
===REPLACE===
  const messages = conversation?.messages ?? [];

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  // BF-293: reset the empty-transcript counter when the agent replies so
  // the whisperStt fallback isn't surprise-triggered by stale empty
  // results from earlier conversational rounds. Counter still resets on
  // agent-switch (line ~106), on a successful browser-SR transcript
  // (line ~831), and when the fallback fires (line ~807); this closes
  // the cross-turn gap.
  useEffect(() => {
    const last = messages[messages.length - 1];
    if (last?.role === 'agent') {
      emptyTranscriptCountRef.current = 0;
    }
  }, [messages.length]);

  // AD-430b: Fetch cross-session memories on mount
===END REPLACE===
```

---

## Section 2: Tests

### File: `ui/src/__tests__/ProfileChatTab.bf293.test.tsx` (new)

Use the same mock fixture pattern as `ProfileChatTab.bf292.test.tsx` (vi.hoisted mocks for `speechInput`, `whisperStt`, `conversationController`, `voice`; `captureChatCalls()` helper; `beforeEach` reset of mocks + `useStore.setState({ voiceEnabled: true, agentConversations: new Map() })`).

Behavior-level tests (no direct ref pokes; verify via the user-visible effect — i.e. whether the third press fires `armWhisperStt` or `startListening`):

**Test 1 — counter increments on consecutive empty browser-SR transcripts**

- Press mic → drive `onError` callback (no result). Press mic again → drive `onError`. Press mic a third time.
- Assert: `armWhisperStt` is called exactly once (counter reached 2 and routed to fallback).
- This establishes the baseline that increments accumulate across presses, matching the pre-fix behavior on the increment path.

**Test 2 — agent reply resets the counter (the fix)**

- Press mic → empty (`onError`). Press mic → empty (`onError`). Counter is now 2.
- Append an agent reply: `useStore.getState().addAgentMessage('a1', 'agent', 'hello')` wrapped in `act(...)` so React flushes the effect.
- Press mic a third time.
- Assert: `startListening` is called for the third press; `armWhisperStt` is **not** called. (Counter was reset to 0 by the agent reply, so the fallback gate at `>= 2` is no longer crossed.)

**Test 3 — user message append does NOT reset the counter**

- Press mic → empty. Press mic → empty. Counter is now 2.
- Append a user message: `useStore.getState().addAgentMessage('a1', 'user', 'typed text')` in `act(...)`.
- Press mic a third time.
- Assert: `armWhisperStt` is called exactly once. (User-side appends must not reset; the trigger condition is specifically agent reply.)

### Notes for the Builder

- Import `act` from `@testing-library/react` for store-mutation flushes.
- The `addAgentMessage` action lives on `useStore` (see `ui/src/store/useStore.ts:367,956`). Signature: `(agentId, role: 'user' | 'agent', text)`.
- After each `fireEvent.click(mic)` that drives `startListening`, the mock receives `(onResult, onError, onEnd, opts)` — the empty path is `mock.calls[i][1]()`.
- `screen.findByLabelText('Voice input')` is the mic-button accessor used by bf290/bf292; reuse it.

---

## What this does NOT change

- The existing increment site at line 840.
- The reset on agent-switch (line 106), on successful browser-SR transcript (line 831), or on whisper-fallback fire (line 807).
- The `>= 2` threshold for routing into `whisperStt`.
- Any other `messages.length` effect, the conversation controller arming, or the natural-conversation path.
- Server-side, runtime, or any non-UI code.

---

## Test Gates (both REQUIRED)

```powershell
cd D:\ProbOS\ui
npx vitest run ProfileChatTab
npm run build
```

- `vitest run ProfileChatTab` must include the new `bf293.test.tsx` (3 new tests) and pass all existing `ProfileChatTab.*` regressions.
- `npm run build` MUST succeed. **A green Vitest run alone is not sufficient** — `tsc -b` strict checks only run in `npm run build`. Multiple prior waves shipped to `main` with TS errors that Vitest silently ignored (BF-279 / Wave 155-157 stale-bundle pattern).

---

## Acceptance Criteria

- 3+ new tests pass in `ProfileChatTab.bf293.test.tsx`.
- All existing `ProfileChatTab.*` tests still pass.
- `cd ui; npm run build` exits 0.
- Single commit with `Closes #766` in the message body.
- Pushed to `origin/main` only after **both** gates are green.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Standing Constraints

- Do **NOT** touch the live runtime or any process under `C:\Users\seang\AppData\Local\ProbOS\`.
- Do **NOT** modify any file outside `ui/src/components/profile/ProfileChatTab.tsx` and the new test file.
- Do **NOT** refactor the existing `emptyTranscriptCountRef` increment / reset sites — this BF is additive only.
- No `multi_replace_string_in_file` for the source edit; single `replace_string_in_file` (the user-memory rule from the 2026-05-12 BF-274/278 incidents).

---

## Verified Against Codebase (2026-05-22)

```
grep -n "emptyTranscriptCountRef" ui/src/components/profile/ProfileChatTab.tsx
   77:   const emptyTranscriptCountRef = useRef(0);
  106:     emptyTranscriptCountRef.current = 0;            # agent-switch reset
  803:     if (emptyTranscriptCountRef.current >= 2) {     # whisper fallback gate
  807:       emptyTranscriptCountRef.current = 0;          # fires-fallback reset
  831:       emptyTranscriptCountRef.current = 0;          # successful-transcript reset
  840:       emptyTranscriptCountRef.current += 1;         # increment on empty

grep -n "messages.length" ui/src/components/profile/ProfileChatTab.tsx
  264:   // Auto-scroll on new messages
  265:   useEffect(() => {
  266:     messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  267:   }, [messages.length]);

grep -n "addAgentMessage" ui/src/store/useStore.ts
  367:   addAgentMessage: (agentId: string, role: 'user' | 'agent', text: string) => void;
  956:   addAgentMessage: (agentId, role, text) => { ... }

ls ui/src/__tests__/ProfileChatTab.bf29*.test.tsx
  ProfileChatTab.bf290.test.tsx       # fixture reference
  ProfileChatTab.bf292.test.tsx       # fixture reference (closest analog)
  # ProfileChatTab.bf293.test.tsx does NOT exist — Builder creates it
```

Message shape confirmed: `messages` is `conversation?.messages ?? []` (line 262), and message objects carry a `role: 'user' | 'agent'` field — matches the `addAgentMessage` action signature.
