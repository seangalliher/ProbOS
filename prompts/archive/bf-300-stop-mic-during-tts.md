# BF-300 — Stop mic during TTS playback (PTT echo-loop fix)

**Status:** Ready for Builder
**GitHub Issue:** #774
**Dependencies:** none (builds on BF-290/292/293/294/294b, AD-760, AD-826)
**Estimated tests:** 5 new Vitest cases in `ui/src/__tests__/ProfileChatTab.bf300.test.tsx`

## Problem

In Chrome PTT mode, after the operator's utterance is auto-sent and the agent replies via TTS, the browser SpeechRecognition session **stays open** (`continuous: true`), the mic picks up the TTS audio routed through speakers, transcribes it, and the same result callback auto-sends the agent's own words back as a new user message. This creates a runaway echo loop.

Reproduced 2026-05-23 (issue #774 body).

Two compounding root causes:

1. **`continuous: true` SR session is never explicitly stopped after a PTT result.** All three PTT result callbacks (`d:\ProbOS\ui\src\components\profile\ProfileChatTab.tsx` lines 937–942, 979–984, 1029–1034) call `setListening(false)` (visual only) then `setTimeout(sendText, 100)`. The underlying `SpeechRecognition` instance is still running — it keeps emitting `onresult` for every utterance the mic picks up, including TTS playback.
2. **No mic-gate during TTS playback.** When `speakResponse` fires, nothing pauses audio capture. Browser AEC (`echoCancellation`) is unreliable for same-device-speakers-to-mic loopback.

The conversation-mode path (BF-290) handles this via `markAgentReplyComplete` already (`ProfileChatTab.tsx:256-261`), but PTT does not.

## Solution

Two-layer fix. Layer 3 (`getUserMedia` constraints) is **out of scope** — `startListening` does not own `getUserMedia`; the browser `SpeechRecognition` API does, and constraints aren't part of its surface. Document this in the prompt; do not implement.

### Layer 1 — explicit `stopListening` / `disarmWhisperStt` in PTT result callbacks (primary fix)

In all three PTT browser-SR result callbacks AND in both whisper-fallback transcript handlers, terminate the underlying capture session **before** the `setTimeout(sendText, 100)` fires. The existing `setListening(false)` only flips visual state; this adds the missing session termination.

### Layer 2 — `ttsActive` gate on PTT click (defense in depth)

Persistent `onSpeechEvent` subscription tracks TTS lifecycle. While a TTS utterance is playing, the PTT click handler refuses to start a new SR/whisper session and logs INFO. The mic icon shows a new `muted` visual state so the operator knows why a click didn't take.

Conversation mode is **already safe** via BF-290's `markAgentReplyComplete` wiring (`ProfileChatTab.tsx:256-261`). The new gate must coexist — verify by regression test.

---

## Section 0 — New MicIndicator state

Add a fourth `muted` state to `MicIndicator` for the TTS-active visual. Minimal addition: 1 enum value, 1 palette entry, 1 ring branch.

### `ui/src/components/profile/MicIndicator.tsx`

```search
===SEARCH===
export type MicIndicatorState = 'idle' | 'listening' | 'processing';
===REPLACE===
export type MicIndicatorState = 'idle' | 'listening' | 'processing' | 'muted';
===END REPLACE===
```

```search
===SEARCH===
const PALETTE = {
  idle: '#8888aa',
  listening: '#f0b060',
  processing: '#a08040',
} as const;
===REPLACE===
const PALETTE = {
  idle: '#8888aa',
  listening: '#f0b060',
  processing: '#a08040',
  // BF-300 — muted-during-TTS. Dim violet so it's visually distinct from
  // both idle (grey) and processing (dim amber). HXI #4: motion
  // communicates state — the static dashed ring tells the operator the
  // mic is intentionally inactive, not broken.
  muted: '#6a5a8a',
} as const;
```

Add a ring branch beside the existing `state === 'processing'` block (after it, before the `<svg>`):

```search
===SEARCH===
      {state === 'processing' && (
        <span
          data-testid="mic-indicator-ring-processing"
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: -4,
            borderRadius: '50%',
            border: `1.5px dashed ${PALETTE.processing}`,
            animation: 'bf294-mic-process 1.4s linear infinite',
            pointerEvents: 'none',
          }}
        />
      )}
===REPLACE===
      {state === 'processing' && (
        <span
          data-testid="mic-indicator-ring-processing"
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: -4,
            borderRadius: '50%',
            border: `1.5px dashed ${PALETTE.processing}`,
            animation: 'bf294-mic-process 1.4s linear infinite',
            pointerEvents: 'none',
          }}
        />
      )}
      {state === 'muted' && (
        // BF-300 — static dashed violet ring while TTS is playing.
        // No animation: the absence of motion signals intentional
        // suppression (vs. the active pulse of 'listening' or the
        // shimmer of 'processing').
        <span
          data-testid="mic-indicator-ring-muted"
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: -4,
            borderRadius: '50%',
            border: `1.5px dashed ${PALETTE.muted}`,
            pointerEvents: 'none',
          }}
        />
      )}
===END REPLACE===
```

---

## Section 1 — `ttsActive` ref + subscription in `ProfileChatTab.tsx`

Add a persistent `onSpeechEvent` subscription that tracks any TTS in flight for this agent. The existing per-reply subscription inside `armConversationMode.onAgentReply` (line 256) stays — it's scoped to conversation-mode handoff. The new subscription is at the component level, fires for every speak/stop, and drives both the ref (for the click-handler synchronous check) and a state (for `MicIndicator`).

Locate the `audioIntensity` useState block (around line 71) and add immediately after the BF-294b state declarations (before the BF-294b effect comment block).

```search
===SEARCH===
  const intensityRef = useRef(0);       // EMA accumulator, written from onFrame
  const rafPendingRef = useRef(false);  // RAF coalescing flag
===REPLACE===
  const intensityRef = useRef(0);       // EMA accumulator, written from onFrame
  const rafPendingRef = useRef(false);  // RAF coalescing flag

  // BF-300 — TTS-active gate. ``ttsActiveRef`` is the synchronous source
  // of truth read by the PTT click handler; ``ttsActive`` state drives
  // the MicIndicator 'muted' visual. Both update on 'start'/'end' events
  // fired by ``audio/voice.ts`` for THIS agent (or unscoped events from
  // legacy callers that don't pass agent_id).
  const ttsActiveRef = useRef(false);
  const [ttsActive, setTtsActive] = useState(false);
===END REPLACE===
```

Then add a new `useEffect` immediately after the existing `useEffect` that subscribes to `onSpeechEvent` inside the conversation arming block. The new effect lives at the top level so it persists for the lifetime of the component, independent of `micMode`. Place it directly after the `armConversationMode` useEffect (after the `}, [agentId, micMode, globalVoiceEnabled]);` closer around line 274 — i.e. between the conversation-mode effect and the `useEffect` that handles the mic popover outside-click (around line 277).

```search
===SEARCH===
    return () => {
      disarmConversationMode();
    };
  }, [agentId, micMode, globalVoiceEnabled]);

  // AD-760: dismiss the mic popover on outside click or Escape.
===REPLACE===
    return () => {
      disarmConversationMode();
    };
  }, [agentId, micMode, globalVoiceEnabled]);

  // BF-300 — persistent TTS-lifecycle subscription. Tracks every speak
  // event for this agent so the PTT click handler can refuse to start a
  // new SR session while TTS is playing (echo-loop guard), and the
  // MicIndicator can show the 'muted' visual.
  //
  // Coexists with the per-reply subscription inside ``armConversationMode``
  // (line ~256): that one fires ``markAgentReplyComplete`` on 'end' to
  // hand back to the controller; this one is purely for PTT gating and
  // does not call into the controller.
  useEffect(() => {
    const unsub = onSpeechEvent((event) => {
      if (event.agent_id && event.agent_id !== agentId) return;
      if (event.type === 'start') {
        ttsActiveRef.current = true;
        setTtsActive(true);
      } else if (event.type === 'end') {
        ttsActiveRef.current = false;
        setTtsActive(false);
      }
    });
    return () => {
      try { unsub(); } catch { /* Tier-2 */ }
    };
  }, [agentId]);

  // AD-760: dismiss the mic popover on outside click or Escape.
===END REPLACE===
```

---

## Section 2 — Gate the PTT click handler

Add the entry-guard at the top of the `onClick` handler (line 897), BEFORE the `if (listening)` stop branch. We do not want to gate the *stop* path — the operator must always be able to abort a stuck session.

```search
===SEARCH===
              onClick={() => {
                if (micMode === 'conversation') {
                  // In conversation mode, left-click is press-to-talk
                  // preemption (PRIORITY_PRESS_TO_TALK wins per BF-318);
                  // we still drive it through the standard PTT path
                  // below — the ConversationController will see the
                  // preempt and re-arm on release. The mode-switching
                  // logic stays in the popover.
                }
                if (listening) {
                  stopListening();
===REPLACE===
              onClick={() => {
                if (micMode === 'conversation') {
                  // In conversation mode, left-click is press-to-talk
                  // preemption (PRIORITY_PRESS_TO_TALK wins per BF-318);
                  // we still drive it through the standard PTT path
                  // below — the ConversationController will see the
                  // preempt and re-arm on release. The mode-switching
                  // logic stays in the popover.
                }
                if (listening) {
                  stopListening();
===END REPLACE===
```

(No-op SEARCH/REPLACE above; the gate goes AFTER the stop branch, before the listening-start path. Use this:)

```search
===SEARCH===
                if (listening) {
                  stopListening();
                  // BF-290: also disarm whisper fallback in case the previous
                  // press armed it but the operator never spoke. stopListening
                  // only stops the browser SpeechRecognition; whisperStt is a
                  // separate subsystem that needs explicit teardown.
                  try { disarmWhisperStt(); } catch { /* Tier-2 */ }
                  setListening(false);
                  setProcessing(false); // BF-294: cancel any pending processing visual
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
                  setProcessing(false); // BF-294: cancel any pending processing visual
                  return;
                }
                // BF-300 — TTS-active gate. Refuse to start a new SR
                // session while the agent's own TTS is playing through
                // the speakers; otherwise the mic captures it and
                // auto-sends it back as a new user message (echo loop,
                // #774). The 'muted' MicIndicator state communicates
                // this state to the operator (HXI #4 motion conveys
                // state). Stop-path above is intentionally NOT gated:
                // the operator must always be able to abort.
                if (ttsActiveRef.current) {
                  console.info(
                    `BF-300: mic press ignored for agent ${agentId} — TTS playback in progress`,
                  );
                  return;
                }
                setListening(true);
===END REPLACE===
```

---

## Section 3 — `stopListening` / `disarmWhisperStt` in all PTT result callbacks

Five sites total: three browser-SR result callbacks + two whisper-transcript callbacks. Each one currently calls `setListening(false)` + `setTimeout(sendText, 100)`. We add the explicit session-stop call between them.

### 3a — browser SR result (AD-826 fallback path, ~line 937)

```search
===SEARCH===
                    let gotResult = false;
                    startListening(
                      (text) => {
                        gotResult = true;
                        setInput(text);
                        setListening(false);
                        setTimeout(() => { void sendText(text); }, 100);
                      },
                      () => {
                        // BF-293 mirror: empty browser SR in whisper-
                        // primary fallback mode does NOT increment the
                        // whisper counter; the operator already paid the
                        // whisper-empty price to get here.
                        if (!gotResult) { /* no counter update */ }
                        setListening(false);
                      },
                      () => setListening(false),
                      { continuous: true, interimResults: true, endOfSpeechGapMs: 1500 },
                    );
                    return;
                  }
===REPLACE===
                    let gotResult = false;
                    startListening(
                      (text) => {
                        gotResult = true;
                        setInput(text);
                        setListening(false);
                        // BF-300: terminate the continuous SR session so
                        // the upcoming TTS reply isn't captured as the
                        // next utterance (#774 echo loop).
                        try { stopListening(); } catch { /* Tier-2 */ }
                        setTimeout(() => { void sendText(text); }, 100);
                      },
                      () => {
                        // BF-293 mirror: empty browser SR in whisper-
                        // primary fallback mode does NOT increment the
                        // whisper counter; the operator already paid the
                        // whisper-empty price to get here.
                        if (!gotResult) { /* no counter update */ }
                        setListening(false);
                      },
                      () => setListening(false),
                      { continuous: true, interimResults: true, endOfSpeechGapMs: 1500 },
                    );
                    return;
                  }
===END REPLACE===
```

### 3b — whisper-primary onTranscript (~line 957)

```search
===SEARCH===
                  const unsub = onWhisperTranscript((text: string) => {
                    try { unsub(); } catch { /* Tier-2 */ }
                    try { disarmWhisperStt(); } catch { /* Tier-2 */ }
                    if (text && text.trim().length > 0) {
                      emptyWhisperCountRef.current = 0;
                      setInput(text);
                      setListening(false);
                      setTimeout(() => { void sendText(text); }, 100);
                    } else {
                      emptyWhisperCountRef.current += 1;
                      setListening(false);
                    }
                  });
                  armWhisperStt();
                  return;
                }
===REPLACE===
                  const unsub = onWhisperTranscript((text: string) => {
                    try { unsub(); } catch { /* Tier-2 */ }
                    try { disarmWhisperStt(); } catch { /* Tier-2 */ }
                    if (text && text.trim().length > 0) {
                      emptyWhisperCountRef.current = 0;
                      setInput(text);
                      setListening(false);
                      // BF-300: disarmWhisperStt above already terminated
                      // whisper capture; nothing further needed here.
                      // (The browser SR session is not running in this
                      // path.)
                      setTimeout(() => { void sendText(text); }, 100);
                    } else {
                      emptyWhisperCountRef.current += 1;
                      setListening(false);
                    }
                  });
                  armWhisperStt();
                  return;
                }
===END REPLACE===
```

### 3c — browser-SR honest-degrade path (~line 979)

```search
===SEARCH===
                  let gotResult = false;
                  startListening(
                    (text) => {
                      gotResult = true;
                      setInput(text);
                      setListening(false);
                      setTimeout(() => { void sendText(text); }, 100);
                    },
                    () => {
                      if (!gotResult) { /* no counter update on honest-degrade press */ }
                      setListening(false);
                    },
                    () => setListening(false),
                    { continuous: true, interimResults: true, endOfSpeechGapMs: 1500 },
                  );
                  return;
                }

                // primary === 'browser' — AD-760 legacy path preserved verbatim.
===REPLACE===
                  let gotResult = false;
                  startListening(
                    (text) => {
                      gotResult = true;
                      setInput(text);
                      setListening(false);
                      // BF-300: terminate the continuous SR session — see 3a.
                      try { stopListening(); } catch { /* Tier-2 */ }
                      setTimeout(() => { void sendText(text); }, 100);
                    },
                    () => {
                      if (!gotResult) { /* no counter update on honest-degrade press */ }
                      setListening(false);
                    },
                    () => setListening(false),
                    { continuous: true, interimResults: true, endOfSpeechGapMs: 1500 },
                  );
                  return;
                }

                // primary === 'browser' — AD-760 legacy path preserved verbatim.
===END REPLACE===
```

### 3d — AD-760 whisper fallback (~line 1006)

```search
===SEARCH===
                  const unsub = onWhisperTranscript((text: string) => {
                    try { unsub(); } catch { /* Tier-2 */ }
                    try { disarmWhisperStt(); } catch { /* Tier-2 */ }
                    setInput(text);
                    setListening(false);
                    // BF-292: pass ``text`` as an argument so the timer
                    // does not depend on the post-render value of ``input``.
                    setTimeout(() => { void sendText(text); }, 100);
                  });
===REPLACE===
                  const unsub = onWhisperTranscript((text: string) => {
                    try { unsub(); } catch { /* Tier-2 */ }
                    try { disarmWhisperStt(); } catch { /* Tier-2 */ }
                    setInput(text);
                    setListening(false);
                    // BF-300: disarmWhisperStt above terminated whisper
                    // capture. The legacy AD-760 browser-SR path is not
                    // running in this fallback branch.
                    // BF-292: pass ``text`` as an argument so the timer
                    // does not depend on the post-render value of ``input``.
                    setTimeout(() => { void sendText(text); }, 100);
                  });
===END REPLACE===
```

### 3e — primary browser-SR path (~line 1029)

```search
===SEARCH===
                let gotResult = false;
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
                  () => {
                    if (!gotResult) {
                      emptyTranscriptCountRef.current += 1;
                    }
                    setListening(false);
                  },
                  () => setListening(false),
                  { continuous: true, interimResults: true, endOfSpeechGapMs: 1500 },
                );
              }}
===REPLACE===
                let gotResult = false;
                startListening(
                  (text) => {
                    gotResult = true;
                    emptyTranscriptCountRef.current = 0;
                    setInput(text);
                    setListening(false);
                    // BF-300: terminate the continuous SR session so the
                    // agent's TTS reply isn't captured and auto-sent as
                    // the next user message (#774 echo loop).
                    try { stopListening(); } catch { /* Tier-2 */ }
                    // BF-292: pass ``text`` as an argument so the timer
                    // does not depend on the post-render value of ``input``.
                    setTimeout(() => { void sendText(text); }, 100);
                  },
                  () => {
                    if (!gotResult) {
                      emptyTranscriptCountRef.current += 1;
                    }
                    setListening(false);
                  },
                  () => setListening(false),
                  { continuous: true, interimResults: true, endOfSpeechGapMs: 1500 },
                );
              }}
===END REPLACE===
```

---

## Section 4 — Drive the `muted` MicIndicator state

Update the `MicIndicator` render at line ~1089. Priority order: `processing > muted > listening > idle`. Processing still wins so an in-flight whisper transcription isn't masked by a concurrent TTS reply (rare but possible — e.g. operator pressed to talk during another agent's reply).

```search
===SEARCH===
              <MicIndicator state={processing ? 'processing' : listening ? 'listening' : 'idle'} size={14} intensity={audioIntensity} />
===REPLACE===
              <MicIndicator
                state={
                  processing
                    ? 'processing'
                    : ttsActive
                      ? 'muted'
                      : listening
                        ? 'listening'
                        : 'idle'
                }
                size={14}
                intensity={audioIntensity}
              />
===END REPLACE===
```

---

## Tests

Create `ui/src/__tests__/ProfileChatTab.bf300.test.tsx`. Follow the mock shape from `ProfileChatTab.bf294.test.tsx` verbatim (already verified compatible with the production code path) — the only difference is that `onSpeechEventMock` must be reachable from the test so it can dispatch synthetic `'start'` / `'end'` events.

```tsx
/** BF-300 — PTT mic must not capture TTS playback as the next utterance.
 *
 * Issue: #774 (echo loop). Fixes:
 *  - Layer 1: explicit stopListening / disarmWhisperStt in every PTT result callback.
 *  - Layer 2: ttsActive gate refuses new SR sessions during TTS playback.
 *  - MicIndicator 'muted' visual signals the gate to the operator.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  startListeningMock: vi.fn(),
  stopListeningMock: vi.fn(),
  armConversationModeMock: vi.fn(() => () => {}),
  disarmConversationModeMock: vi.fn(),
  markAgentReplyCompleteMock: vi.fn(),
  armWhisperSttMock: vi.fn(),
  disarmWhisperSttMock: vi.fn(),
  whisperOnTranscriptMock: vi.fn(() => () => {}),
  whisperOnTranscribingMock: vi.fn(() => () => {}),
  speakResponseMock: vi.fn(),
  onSpeechEventMock: vi.fn(() => () => {}),
}));

vi.mock('../audio/voice', () => ({
  getServerPiperVoices: vi.fn(async () => null),
  speakResponse: mocks.speakResponseMock,
  stripMarkdownForSpeech: (s: string) => s,
  onSpeechEvent: mocks.onSpeechEventMock,
}));

vi.mock('../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => true,
  startListening: mocks.startListeningMock,
  stopListening: mocks.stopListeningMock,
}));

vi.mock('../audio/conversationController', () => ({
  armConversationMode: mocks.armConversationModeMock,
  disarmConversationMode: mocks.disarmConversationModeMock,
  markAgentReplyComplete: mocks.markAgentReplyCompleteMock,
}));

vi.mock('../audio/whisperStt', () => ({
  armWhisperStt: mocks.armWhisperSttMock,
  disarmWhisperStt: mocks.disarmWhisperSttMock,
  onTranscript: mocks.whisperOnTranscriptMock,
  onTranscribing: mocks.whisperOnTranscribingMock,
}));

import { ProfileChatTab } from '../components/profile/ProfileChatTab';
import { useStore } from '../store/useStore';

// Capture every onSpeechEvent listener registered by ProfileChatTab.
// The component registers two: one inside armConversationMode (BF-290)
// and one at the top level (BF-300). Tests dispatch by iterating the
// captured listeners so we exercise the production code path exactly.
const speechListeners: Array<(e: any) => void> = [];

function setDefaultFetch(): void {
  global.fetch = vi.fn((url: any) => {
    const target = String(url);
    if (target.endsWith('/chat/history')) {
      return Promise.resolve({ ok: true, json: async () => ({ memories: [] }) }) as any;
    }
    if (target.endsWith('/profile')) {
      return Promise.resolve({ ok: true, json: async () => ({ voiceProfile: null }) }) as any;
    }
    return Promise.resolve({ ok: true, json: async () => ({}) }) as any;
  }) as any;
}

beforeEach(() => {
  speechListeners.length = 0;
  Object.values(mocks).forEach((m) => {
    if (typeof m === 'function' && 'mockReset' in m) (m as any).mockReset();
  });
  mocks.armConversationModeMock.mockReturnValue(() => {});
  mocks.whisperOnTranscriptMock.mockReturnValue(() => {});
  mocks.whisperOnTranscribingMock.mockReturnValue(() => {});
  mocks.onSpeechEventMock.mockImplementation((fn: any) => {
    speechListeners.push(fn);
    return () => {
      const i = speechListeners.indexOf(fn);
      if (i >= 0) speechListeners.splice(i, 1);
    };
  });
  localStorage.clear();
  useStore.setState({
    voiceEnabled: true,
    agentConversations: new Map(),
  });
  setDefaultFetch();
  if (!(Element.prototype as any).scrollIntoView) {
    (Element.prototype as any).scrollIntoView = vi.fn();
  }
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

function dispatchSpeechEvent(type: 'start' | 'end', agentId?: string): void {
  // Fire only the top-level BF-300 listener — the BF-290 listener is
  // scoped to in-flight agent replies and is per-call. To be safe,
  // dispatch to ALL listeners; the BF-290 one no-ops unless its inner
  // state matches.
  act(() => {
    for (const fn of [...speechListeners]) {
      try {
        fn({ type, agent_id: agentId, utterance: {} as any });
      } catch {
        /* ignore */
      }
    }
  });
}

describe('BF-300 — PTT mic does not capture TTS playback', () => {
  it('browser-SR result callback calls stopListening before sendText fires', async () => {
    vi.useFakeTimers();
    try {
      render(<ProfileChatTab agentId="a1" />);
      const mic = await screen.findByLabelText(/Voice input/);
      fireEvent.click(mic);
      expect(mocks.startListeningMock).toHaveBeenCalledTimes(1);
      const onResult = (mocks.startListeningMock.mock.calls[0] as any)[0] as (t: string) => void;

      // Fire the result. stopListening MUST be called synchronously,
      // BEFORE the 100 ms sendText timer elapses.
      act(() => { onResult('hello ezri'); });
      expect(mocks.stopListeningMock).toHaveBeenCalledTimes(1);

      // Confirm setTimeout hasn't fired yet.
      // (sendText is async and would call fetch with /chat. Pre-timer:
      //  only the /chat/history + /profile from initial mount.)
      const fetchCalls = (global.fetch as any).mock.calls.map((c: any[]) => String(c[0]));
      expect(fetchCalls.some((u: string) => u.endsWith('/chat') || u.includes('/chat?'))).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it('whisper-primary onTranscript path disarms whisper before sendText', async () => {
    vi.useFakeTimers();
    try {
      // Wire whisper as primary + healthy so the click takes the
      // whisper-onTranscript branch (line ~957).
      global.fetch = vi.fn((url: any) => {
        const target = String(url);
        if (target.endsWith('/voice/health')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              primary_stt: 'whisper',
              engine: 'whisper',
              backend_available: true,
              healthy: true,
            }),
          }) as any;
        }
        if (target.endsWith('/chat/history')) {
          return Promise.resolve({ ok: true, json: async () => ({ memories: [] }) }) as any;
        }
        if (target.endsWith('/profile')) {
          return Promise.resolve({ ok: true, json: async () => ({ voiceProfile: null }) }) as any;
        }
        return Promise.resolve({ ok: true, json: async () => ({}) }) as any;
      }) as any;

      render(<ProfileChatTab agentId="a1" />);
      const mic = await screen.findByLabelText(/Voice input/);

      // Let the voice-health fetch resolve.
      await act(async () => { await Promise.resolve(); });

      fireEvent.click(mic);
      expect(mocks.armWhisperSttMock).toHaveBeenCalledTimes(1);
      const onTranscript = (mocks.whisperOnTranscriptMock.mock.calls[0] as any)[0] as (t: string) => void;

      act(() => { onTranscript('hello ezri'); });
      // disarmWhisperStt fires synchronously inside the transcript callback,
      // BEFORE the 100 ms setTimeout(sendText).
      expect(mocks.disarmWhisperSttMock).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('clicking the mic while TTS is playing is a no-op (ttsActive gate)', async () => {
    render(<ProfileChatTab agentId="a1" />);
    const mic = await screen.findByLabelText(/Voice input/);

    // Wait for the BF-300 useEffect to register its onSpeechEvent listener.
    expect(speechListeners.length).toBeGreaterThan(0);

    dispatchSpeechEvent('start', 'a1');
    fireEvent.click(mic);
    expect(mocks.startListeningMock).not.toHaveBeenCalled();
    expect(mocks.armWhisperSttMock).not.toHaveBeenCalled();
  });

  it('after onSpeechEvent("end"), mic click works normally', async () => {
    render(<ProfileChatTab agentId="a1" />);
    const mic = await screen.findByLabelText(/Voice input/);

    dispatchSpeechEvent('start', 'a1');
    dispatchSpeechEvent('end', 'a1');
    fireEvent.click(mic);
    expect(mocks.startListeningMock).toHaveBeenCalledTimes(1);
  });

  it('MicIndicator shows muted state during TTS playback', async () => {
    render(<ProfileChatTab agentId="a1" />);
    await screen.findByLabelText(/Voice input/);

    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');
    dispatchSpeechEvent('start', 'a1');
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('muted');
    dispatchSpeechEvent('end', 'a1');
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');
  });
});
```

---

## What this does NOT change

- `startListening` / `stopListening` / `speechRecognitionArbiter` semantics — no changes to `ui/src/audio/speechInput.ts`.
- `whisperStt` arming/disarming semantics — no changes to `ui/src/audio/whisperStt.ts`.
- TTS path (`audio/voice.ts`) — `speakResponse` / `onSpeechEvent` shape unchanged.
- Conversation mode (`armConversationMode` + `markAgentReplyComplete`) — BF-290 wiring intact.
- The Layer 3 `getUserMedia` echo-cancellation constraints from issue #774's "optional, defer": deferred. `SpeechRecognition` doesn't expose `getUserMedia` constraints; revisiting would require switching off the browser SR API entirely.
- `MicIndicator` palette/animation for existing `idle`/`listening`/`processing` states — additive only.

## Test gates (BOTH required — BF-279 lesson)

From `d:\ProbOS\ui\` directory:

1. `npx vitest run` — full UI suite passes (must include new file `ProfileChatTab.bf300.test.tsx`).
2. `npm run build` — production bundle compiles cleanly. **Vitest passes do NOT imply tsc strict passes** (BF-279 / Wave 155–157 stale-bundle lesson).

Both must succeed before the commit lands.

## Tracking

- `PROGRESS.md` — append entry "CLOSED BF-300 — PTT mic gate + ttsActive guard (#774)" under the active Bug Tracker section.
- `docs/development/roadmap.md` Bug Tracker — add a row for BF-300 with one-line summary + link to #774.
- `DECISIONS.md` — no entry needed (BFs do not get their own AD entries).

## Acceptance criteria

- 5 new Vitest tests pass.
- Pre-existing voice tests pass: `ProfileChatTab.bf290.test.tsx`, `ProfileChatTab.bf292.test.tsx`, `ProfileChatTab.bf293.test.tsx`, `ProfileChatTab.bf294.test.tsx`, `ProfileChatTab.ad826.test.tsx`, `ProfileChatTab.conversationWiring.test.tsx`, `ProfileChatTabVoice.test.tsx`.
- `cd ui; npm run build` succeeds (tsc + vite both clean).
- One commit titled `BF-300 — Stop mic during TTS playback (#774)` with `Closes #774` in body.
- Push to `origin/main` only after both gates green.
- HXI #4 satisfied: `muted` MicIndicator state communicates "intentionally inactive" via the static dashed violet ring (absence of motion is itself motion-communicates-state).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Standing constraints

- DO NOT touch the live runtime; do not run `probos serve` from the workspace venv.
- DO NOT touch anything under `C:\Users\seang\AppData\Local\ProbOS\`.
- DO NOT broad-kill python by path/name (use `scripts/kill-stale-pytest.ps1` if a vitest worker hangs).

---

## Verified Against Codebase (2026-05-23)

```
grep -n "continuous: true" ui/src/components/profile/ProfileChatTab.tsx
  949:                      { continuous: true, interimResults: true, endOfSpeechGapMs: 1500 },
  992:                    { continuous: true, interimResults: true, endOfSpeechGapMs: 1500 },
 1040:                    { continuous: true, interimResults: true, endOfSpeechGapMs: 1500 },

grep -n "export function (stopListening|isListening)" ui/src/audio/speechInput.ts
  239: export function stopListening(): void {
  266: export function isListening(): boolean {

grep -n "recognition.abort()" ui/src/audio/speechInput.ts
  (_abortActiveRecognition at line 262: try { activeRecognition.abort(); } catch { /* already stopped */ })

grep -n "export function (armWhisperStt|disarmWhisperStt)" ui/src/audio/whisperStt.ts
  154: export function armWhisperStt(): () => void {
  168: export function disarmWhisperStt(): void {

grep -n "onSpeechEvent" ui/src/audio/voice.ts
  50: export function onSpeechEvent(fn: SpeechListener): () => void {

grep -n "SpeechEventType|SpeechEvent " ui/src/audio/voice.ts
  35: export type SpeechEventType = 'start' | 'end' | 'boundary';
  37: export interface SpeechEvent {
  38:   type: SpeechEventType;
  39:   agent_id?: string;
  40:   utterance: SpeechSynthesisUtterance;
  41:   source?: SpeechEventSource;

grep -n "onSpeechEvent" ui/src/components/profile/ProfileChatTab.tsx
  18: import { onSpeechEvent } from '../../audio/voice';
  256:         const unsub = onSpeechEvent((event) => {   # existing BF-290 per-reply subscription

grep -n "MicIndicator state=" ui/src/components/profile/ProfileChatTab.tsx
  1089:              <MicIndicator state={processing ? 'processing' : listening ? 'listening' : 'idle'} ...

grep -n "MicIndicatorState" ui/src/components/profile/MicIndicator.tsx
  22: export type MicIndicatorState = 'idle' | 'listening' | 'processing';

grep -n "disarmWhisperStt" ui/src/components/profile/ProfileChatTab.tsx
   21,  911,  955, 1006  (4 sites; result-side disarms at 955 and 1006)

grep -n "import { startListening" ui/src/components/profile/ProfileChatTab.tsx
   4: import { startListening, stopListening, isSpeechRecognitionSupported } from '../../audio/speechInput';
```

All concrete claims verified. No phantom APIs.
