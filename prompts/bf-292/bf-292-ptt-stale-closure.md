# BF-292 — PTT auto-send broken by stale `handleSend` closure

**Issue:** [#765](https://github.com/seangalliher/ProbOS/issues/765)
**Status:** Ready to build
**Dependencies:** None (touches `ui/src/components/profile/ProfileChatTab.tsx` only)
**Estimated tests:** 5 new (1 file: `ProfileChatTab.bf292.test.tsx`)
**Test gate:** BOTH `cd ui; npx vitest run ProfileChatTab` AND `cd ui; npm run build` must pass (BF-279 lesson).

---

## Problem

`ProfileChatTab.tsx` PTT (push-to-talk) result handlers do:

```tsx
setInput(text);
setListening(false);
setTimeout(() => handleSend(), 100);
```

`handleSend` is captured by the `setTimeout` arrow at scheduling time. React has not yet re-rendered, so the captured `handleSend` still closes over `input = ''`. When the timer fires, `handleSend` reads `text = ''.trim() === ''`, hits the `if ((!text && pendingAttachments.length === 0) || sending) return;` guard at line 322, and returns silently. The transcript appears in the textarea but the message is never POSTed to `/api/agent/{id}/chat`.

Two affected call sites — both with the same defect:

- `ui/src/components/profile/ProfileChatTab.tsx:798` — whisperStt fallback path (AD-760).
- `ui/src/components/profile/ProfileChatTab.tsx:816` — browser `SpeechRecognition` result path.

(grep confirmed: only these two `setTimeout.*handleSend` sites exist in `ui/src/**`.)

---

## Solution

Factor the body of `handleSend` into a new `sendText(textArg: string)` callback that takes the message text as an **argument**, not from closure. `handleSend` becomes a thin shim that reads current `input` and forwards. The PTT paths pass the freshly-captured transcript directly.

Critical: `sendText` MUST NOT have `input` in its `useCallback` deps array — it reads from `textArg` only. Otherwise the closure is still stale via a different path.

---

## Section 1 — Refactor `handleSend` into `sendText` + `handleSend`

**File:** `ui/src/components/profile/ProfileChatTab.tsx`

### SEARCH

```tsx
  const handleSend = useCallback(async () => {
    const text = input.trim();
    if ((!text && pendingAttachments.length === 0) || sending) return;
    setInput('');
    setSending(true);

    // AD-430b: Capture conversation history BEFORE adding current message
    const conv = useStore.getState().agentConversations.get(agentId);
    const history = (conv?.messages || [])
        .slice(-20)  // Last 20 messages (10 exchanges)
        .map(m => ({
            role: m.role === 'user' ? 'user' : 'agent',
            text: m.text,
        }));

    // Prepend seed memories on first message (no prior conversation)
    const fullHistory = conv?.messages?.length ? history : [...seedMemories, ...history];

    // Compose display text including attachment filenames (so the user sees
    // their own message with the attachments listed).
    const attachmentSummary = pendingAttachments.length
      ? '\n\n' + pendingAttachments.map(a => `[attached: ${a.filename || a.attachment_id}]`).join('\n')
      : '';
    const displayText = (text || '(attachment)') + attachmentSummary;

    // Add user message immediately (after capturing history)
    useStore.getState().addAgentMessage(agentId, 'user', displayText);

    const attachmentIds = pendingAttachments.map(a => a.attachment_id);
    setPendingAttachments([]);

    try {
      const res = await fetch(`/api/agent/${agentId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text || '(attachment)',
          history: fullHistory,
          attachment_ids: attachmentIds,
        }),
      });
      const data = await res.json();
      const reply = data.response || '(no response)';
      useStore.getState().addAgentMessage(agentId, 'agent', reply);
      // AD-718: TTS playback for agent reply only (skip system error placeholders).
      if (ttsEnabled && reply && !reply.startsWith('(')) {
        // AD-738e-1: forward parsed emotion (v1 name) so the TTS endpoint
        // applies per-emotion prosody. ``data.emotion`` may be null on
        // older responses or when divergence detection is OFF — pass
        // ``undefined`` so the speakResponse helper omits the field.
        const _emotion = typeof data?.emotion === 'string' && data.emotion.length > 0
          ? data.emotion
          : undefined;
        speakResponse(stripMarkdownForSpeech(reply), voiceProfile ?? undefined, agentId, _emotion);
      }
    } catch {
      useStore.getState().addAgentMessage(agentId, 'agent', '(communication error)');
    } finally {
      setSending(false);
    }
  }, [agentId, input, sending, seedMemories, ttsEnabled, voiceProfile, pendingAttachments]);
```

### REPLACE

```tsx
  // BF-292: sendText reads message body from the ``textArg`` parameter, NOT
  // from the ``input`` state. PTT paths call ``setInput(text)`` then schedule
  // a setTimeout; at scheduling time React has not re-rendered, so any
  // callback that reads ``input`` from closure would see ``''`` and bail at
  // the guard below. By taking the text as an argument we capture the
  // transcript at call-time and bypass the stale-closure race.
  // ``input`` is intentionally NOT in the deps array — it is not read here.
  const sendText = useCallback(async (textArg: string) => {
    const text = textArg.trim();
    if ((!text && pendingAttachments.length === 0) || sending) return;
    setInput('');
    setSending(true);

    // AD-430b: Capture conversation history BEFORE adding current message
    const conv = useStore.getState().agentConversations.get(agentId);
    const history = (conv?.messages || [])
        .slice(-20)  // Last 20 messages (10 exchanges)
        .map(m => ({
            role: m.role === 'user' ? 'user' : 'agent',
            text: m.text,
        }));

    // Prepend seed memories on first message (no prior conversation)
    const fullHistory = conv?.messages?.length ? history : [...seedMemories, ...history];

    // Compose display text including attachment filenames (so the user sees
    // their own message with the attachments listed).
    const attachmentSummary = pendingAttachments.length
      ? '\n\n' + pendingAttachments.map(a => `[attached: ${a.filename || a.attachment_id}]`).join('\n')
      : '';
    const displayText = (text || '(attachment)') + attachmentSummary;

    // Add user message immediately (after capturing history)
    useStore.getState().addAgentMessage(agentId, 'user', displayText);

    const attachmentIds = pendingAttachments.map(a => a.attachment_id);
    setPendingAttachments([]);

    try {
      const res = await fetch(`/api/agent/${agentId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text || '(attachment)',
          history: fullHistory,
          attachment_ids: attachmentIds,
        }),
      });
      const data = await res.json();
      const reply = data.response || '(no response)';
      useStore.getState().addAgentMessage(agentId, 'agent', reply);
      // AD-718: TTS playback for agent reply only (skip system error placeholders).
      if (ttsEnabled && reply && !reply.startsWith('(')) {
        // AD-738e-1: forward parsed emotion (v1 name) so the TTS endpoint
        // applies per-emotion prosody. ``data.emotion`` may be null on
        // older responses or when divergence detection is OFF — pass
        // ``undefined`` so the speakResponse helper omits the field.
        const _emotion = typeof data?.emotion === 'string' && data.emotion.length > 0
          ? data.emotion
          : undefined;
        speakResponse(stripMarkdownForSpeech(reply), voiceProfile ?? undefined, agentId, _emotion);
      }
    } catch {
      useStore.getState().addAgentMessage(agentId, 'agent', '(communication error)');
    } finally {
      setSending(false);
    }
  }, [agentId, sending, seedMemories, ttsEnabled, voiceProfile, pendingAttachments]);

  // BF-292: thin shim for the textarea Enter-key + send-button paths. Reads
  // current ``input`` at call time and forwards to sendText. The Enter-key
  // and form-submit handlers are synchronous reactions to user keystrokes
  // where ``input`` is guaranteed to be current, so closure-staleness is not
  // a concern on this path.
  const handleSend = useCallback(() => {
    void sendText(input);
  }, [input, sendText]);
```

---

## Section 2 — Update whisperStt fallback PTT path

**File:** `ui/src/components/profile/ProfileChatTab.tsx` (around line 798)

### SEARCH

```tsx
                  const unsub = onWhisperTranscript((text: string) => {
                    try { unsub(); } catch { /* Tier-2 */ }
                    try { disarmWhisperStt(); } catch { /* Tier-2 */ }
                    setInput(text);
                    setListening(false);
                    setTimeout(() => handleSend(), 100);
                  });
```

### REPLACE

```tsx
                  const unsub = onWhisperTranscript((text: string) => {
                    try { unsub(); } catch { /* Tier-2 */ }
                    try { disarmWhisperStt(); } catch { /* Tier-2 */ }
                    setInput(text);
                    setListening(false);
                    // BF-292: pass ``text`` as an argument so the timer
                    // does not depend on the post-render value of ``input``.
                    setTimeout(() => { void sendText(text); }, 100);
                  });
```

---

## Section 3 — Update browser SpeechRecognition PTT path

**File:** `ui/src/components/profile/ProfileChatTab.tsx` (around line 816)

### SEARCH

```tsx
                startListening(
                  (text) => {
                    gotResult = true;
                    emptyTranscriptCountRef.current = 0;
                    setInput(text);
                    setListening(false);
                    setTimeout(() => handleSend(), 100);
                  },
```

### REPLACE

```tsx
                startListening(
                  (text) => {
                    gotResult = true;
                    emptyTranscriptCountRef.current = 0;
                    setInput(text);
                    setListening(false);
                    // BF-292: pass ``text`` as an argument so the timer
                    // does not depend on the post-render value of ``input``.
                    setTimeout(() => { void sendText(text); }, 100);
                  },
```

---

## Section 4 — Tests

**File (new):** `ui/src/__tests__/ProfileChatTab.bf292.test.tsx`

Use the mock topology from `ProfileChatTab.bf290.test.tsx` as a fixture template (same `vi.hoisted` mocks for `audio/voice`, `audio/speechInput`, `audio/conversationController`, `audio/whisperStt`). Use `vi.useFakeTimers()` so the 100ms setTimeout fires deterministically via `vi.advanceTimersByTime(100)`. Capture POST bodies via `vi.spyOn(global, 'fetch')`.

Required tests (minimum 5):

1. **`browser-SR transcript triggers POST with transcript body`**
   - Render `<ProfileChatTab agentId="a1" />`, click mic.
   - Grab `onResult = startListeningMock.mock.calls[0][0]`.
   - Call `onResult('hello world')`.
   - `vi.advanceTimersByTime(100)`.
   - Assert `fetch` was called with URL `/api/agent/a1/chat` and body containing `"message":"hello world"`.

2. **`whisperStt fallback transcript triggers POST with transcript body`**
   - Drive two empty browser-SR results to enter the whisper fallback branch (mirror the BF-290 test setup).
   - Click mic a 3rd time; `armWhisperStt` is called.
   - Grab the transcript callback from `whisperOnTranscriptMock.mock.calls[0][0]`.
   - Call it with `'whisper transcript'`.
   - `vi.advanceTimersByTime(100)`.
   - Assert `fetch` was called with body containing `"message":"whisper transcript"`.

3. **`empty transcript still bails — no chat POST`**
   - Click mic. Call `onResult('   ')` (whitespace only).
   - `vi.advanceTimersByTime(100)`.
   - Assert `fetch` was NOT called with `/api/agent/a1/chat` (history-fetch + profile-fetch from initial render are allowed).

4. **`sending=true guard still honored — no double-send`**
   - Click mic. Call `onResult('first message')`. `vi.advanceTimersByTime(100)`. First chat POST fires.
   - Before the first POST resolves, click mic again, call `onResult('second message')`, `vi.advanceTimersByTime(100)`.
   - Assert only ONE chat POST was made (the second was guarded by `sending`).

5. **`pending attachments attach to PTT-sent message`**
   - Pre-seed `pendingAttachments` (either via the file-upload helper or by setting state via the store).
   - Click mic. Call `onResult('see this')`. `vi.advanceTimersByTime(100)`.
   - Assert the chat POST body has `attachment_ids` containing the pre-seeded id.

6. **(Optional regression) `textarea Enter key still sends via handleSend → sendText`**
   - Render, type into the textarea (`fireEvent.change` on the textarea with `'typed message'`).
   - `fireEvent.keyDown` with `Enter`.
   - Assert chat POST body contains `"message":"typed message"`.

Notes:
- Restore real timers in `afterEach` via `vi.useRealTimers()` (or scope `useFakeTimers` per test).
- Use `await waitFor(() => expect(fetch).toHaveBeenCalledWith(...))` after `advanceTimersByTime` to flush any awaited microtasks.
- Match fetch call body via `JSON.parse(init.body as string)` then `.toMatchObject({ message: 'hello world' })`.

---

## What this does NOT change

- `useStore`, agentConversations, addAgentMessage — untouched.
- `audio/speechInput`, `audio/whisperStt`, `audio/conversationController` — untouched.
- The conversation-mode (hands-free) path — untouched (it uses `armConversationMode`, not `setTimeout`).
- The Enter-key handler (`handleKeyDown`) — still calls `handleSend()`; `handleSend` now reads current `input` synchronously and forwards.
- Form submission via the send button — still calls `handleSend`.
- AD-760 empty-transcript fallback counter — unchanged.
- BF-290 cleanup semantics — unchanged.

---

## Tracking

- `PROGRESS.md` — append `BF-292 (CLOSED): PTT auto-send broken by stale handleSend closure — factored sendText(textArg) callback so PTT timers pass the captured transcript instead of reading stale ``input`` state. Fixes #765.`
- `docs/development/roadmap.md` Bug Tracker — add row for BF-292 pointing at this prompt + issue #765.
- `DECISIONS.md` — NOT required (BF, not AD).

---

## Acceptance criteria

- Section 1–3 SEARCH/REPLACE blocks applied cleanly.
- New file `ui/src/__tests__/ProfileChatTab.bf292.test.tsx` exists with ≥5 passing tests covering both PTT paths, empty-bail, sending-guard, and pending-attachments.
- `cd ui; npx vitest run ProfileChatTab` passes (new file + no regression on `ProfileChatTab.test.tsx`, `ProfileChatTabVoice.test.tsx`, `ProfileChatTab.bf290.test.tsx`, `ProfileChatTab.screenShare.test.tsx`, `ProfileChatTab.conversationWiring.test.tsx`).
- `cd ui; npm run build` succeeds (MUST be run — BF-279 stale-bundle lesson: Vitest passing is not enough).
- One commit, message ends with `Closes #765`.
- Push to `origin/main` only after BOTH gates green.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Standing constraints

- DO NOT touch the live runtime at `D:\ProbOS` (the Captain may have `probos serve --interactive` running).
- DO NOT touch anything under `C:\Users\seang\AppData\Local\ProbOS\`.
- DO NOT modify any file outside `ui/src/components/profile/ProfileChatTab.tsx` and the new test file.

---

## Verified Against Codebase (2026-05-22)

```
read_file ui/src/components/profile/ProfileChatTab.tsx 320-385
  320: const handleSend = useCallback(async () => {
  321:   const text = input.trim();
  322:   if ((!text && pendingAttachments.length === 0) || sending) return;
  ...
  383: }, [agentId, input, sending, seedMemories, ttsEnabled, voiceProfile, pendingAttachments]);

read_file ui/src/components/profile/ProfileChatTab.tsx 793-825
  797:   const unsub = onWhisperTranscript((text: string) => {
  798:     ...
  798 (inner): setTimeout(() => handleSend(), 100);
  ...
  813:   startListening(
  814:     (text) => {
  815:       ...
  816:       setTimeout(() => handleSend(), 100);

grep -n "setTimeout.*handleSend" ui/src/**
  ProfileChatTab.tsx:798
  ProfileChatTab.tsx:816
  (no other call sites)

file_search ui/src/__tests__/ProfileChatTab*.test.tsx
  ProfileChatTabVoice.test.tsx
  ProfileChatTab.test.tsx
  ProfileChatTab.screenShare.test.tsx
  ProfileChatTab.conversationWiring.test.tsx
  ProfileChatTab.bf290.test.tsx           ← fixture template
```

All concrete claims in this prompt grep-verified at HEAD on 2026-05-22.
