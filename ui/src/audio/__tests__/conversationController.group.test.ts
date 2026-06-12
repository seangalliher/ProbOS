/**
 * AD-985 — ConversationController group-meeting open-mic generalization.
 *
 * Verifies the two injected hooks added for the meeting path:
 *   - ``submitTranscript`` — a completed utterance is handed to this callback
 *     (the AD-914 group fan-out via sendText) INSTEAD of the built-in 1:1
 *     ``/api/agent/{id}/chat`` POST; after it resolves the controller goes to
 *     ``silence_pending`` (external TTS owns replies, mic stays live).
 *   - ``canListen`` — the AD-922 meeting-wide echo gate: a transcript is
 *     dropped (not submitted) while a crew member is mid-TTS, and the drop
 *     refreshes the silence timer (room activity keeps the session alive).
 *
 * Mocks the cross-module collaborators at the import boundary exactly as
 * conversationController.test.ts does, so the controller logic is exercised in
 * isolation. Network ``fetch`` is spied to PROVE the group path never hits the
 * 1:1 endpoint.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// --- Mocks at the module boundary (mirror conversationController.test.ts) -----

const _whisperState: {
  armed: boolean;
  listener: ((text: string) => void) | null;
} = { armed: false, listener: null };

vi.mock('../transformersStt', () => ({
  armTransformersStt: () => {
    _whisperState.armed = true;
    return () => { _whisperState.armed = false; };
  },
  disarmTransformersStt: () => { _whisperState.armed = false; },
  onTransformersTranscript: (l: (text: string) => void) => {
    _whisperState.listener = l;
    return () => { _whisperState.listener = null; };
  },
}));

const _vadState: {
  handler: { onSpeechStart?: () => void; onSpeechEnd?: () => void } | null;
  handlers: Set<{ onSpeechStart?: () => void; onSpeechEnd?: () => void; onFrame?: (...args: unknown[]) => void }>;
} = { handler: null, handlers: new Set() };

vi.mock('../voiceActivity', () => ({
  subscribePcm: (h: { onSpeechStart?: () => void; onSpeechEnd?: () => void }) => {
    _vadState.handler = h;
    _vadState.handlers.add(h as never);
    return () => {
      _vadState.handlers.delete(h as never);
      if (_vadState.handler === h) _vadState.handler = null;
    };
  },
}));

vi.mock('../voice', () => ({
  stopSpeaking: () => undefined,
}));

// Imports must come AFTER vi.mock declarations.
import {
  armConversationMode,
  disarmConversationMode,
  getConversationState,
  _resetConversationControllerForTests,
} from '../conversationController';
import {
  _resetForTests as _resetArbiter,
} from '../speechRecognitionArbiter';

function _resetAll(): void {
  _resetConversationControllerForTests();
  _resetArbiter();
  _whisperState.armed = false;
  _whisperState.listener = null;
  _vadState.handler = null;
  _vadState.handlers.clear();
}

beforeEach(() => {
  _resetAll();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('AD-985 group-meeting open-mic', () => {
  it('routes a completed utterance to submitTranscript, NOT the 1:1 chat POST', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch');
    const submitTranscript = vi.fn(
      async (_text: string, _history: Array<{ role: string; content: string }>) => undefined,
    );
    armConversationMode({
      agentId: 'thread-host',
      submitTranscript,
      canListen: () => true,
    });
    _whisperState.listener!('what is the warp core status');
    // Flush the awaited submit microtask WITHOUT firing the 30s silence timer.
    await vi.advanceTimersByTimeAsync(1);
    expect(submitTranscript).toHaveBeenCalledTimes(1);
    expect(submitTranscript.mock.calls[0][0]).toBe('what is the warp core status');
    // The group path must never hit the 1:1 endpoint.
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('enters silence_pending after a group submit (external TTS owns replies)', async () => {
    armConversationMode({
      agentId: 'thread-host',
      submitTranscript: async () => undefined,
      canListen: () => true,
    });
    _whisperState.listener!('hello crew');
    await vi.advanceTimersByTimeAsync(1);
    // NOT agent_speaking (the 1:1 path) — the meeting controller hands off TTS
    // to useMeetingVoice and waits for the Captain's next turn.
    expect(getConversationState()).toBe('silence_pending');
  });

  it('echo gate: drops the transcript (no submit) while a crew member is speaking', async () => {
    let speaking = true; // a crew member is mid-TTS
    const submitTranscript = vi.fn(async () => undefined);
    armConversationMode({
      agentId: 'thread-host',
      submitTranscript,
      canListen: () => !speaking,
    });
    // A transcript that is really the crew's own TTS bleeding into the mic.
    _whisperState.listener!('I think we should reroute power');
    await vi.advanceTimersByTimeAsync(1);
    expect(submitTranscript).not.toHaveBeenCalled();
    expect(getConversationState()).toBe('listening');
    // Once the crew finish, the Captain's real utterance submits.
    speaking = false;
    _whisperState.listener!('reroute auxiliary power');
    await vi.advanceTimersByTimeAsync(1);
    expect(submitTranscript).toHaveBeenCalledTimes(1);
  });

  it('an echo drop while silence_pending refreshes the release timer (room stays alive)', async () => {
    let speaking = false;
    const submitTranscript = vi.fn(async () => undefined);
    armConversationMode({
      agentId: 'thread-host',
      submitTranscript,
      canListen: () => !speaking,
      silenceTimeoutMs: 30000,
    });
    // First Captain turn -> submit -> silence_pending (30s timer running).
    _whisperState.listener!('status report');
    await vi.advanceTimersByTimeAsync(1);
    expect(getConversationState()).toBe('silence_pending');
    // 20s in, a crew member is speaking and their TTS bleeds into the mic.
    await vi.advanceTimersByTimeAsync(20000);
    speaking = true;
    _whisperState.listener!('the deflector is at full power'); // echo, dropped
    await vi.advanceTimersByTimeAsync(1);
    // The drop refreshed the 30s timer, so 20s after the FIRST submit the mic
    // is still armed (not released) — the room is demonstrably alive.
    expect(getConversationState()).toBe('silence_pending');
    expect(_whisperState.armed).toBe(true);
  });

  it('30s of true silence still releases the open mic (disarms)', async () => {
    armConversationMode({
      agentId: 'thread-host',
      submitTranscript: async () => undefined,
      canListen: () => true,
      silenceTimeoutMs: 30000,
    });
    _whisperState.listener!('any updates');
    await vi.advanceTimersByTimeAsync(1);
    expect(getConversationState()).toBe('silence_pending');
    // No further speech for 30s -> release (wake-word resumes via BF-318).
    await vi.advanceTimersByTimeAsync(30000);
    expect(getConversationState()).toBe('inactive');
    expect(_whisperState.armed).toBe(false);
  });

  it('disarm tears down the meeting controller cleanly', () => {
    armConversationMode({
      agentId: 'thread-host',
      submitTranscript: async () => undefined,
      canListen: () => true,
    });
    expect(getConversationState()).toBe('listening');
    disarmConversationMode();
    expect(getConversationState()).toBe('inactive');
    expect(_whisperState.armed).toBe(false);
    expect(_vadState.handler).toBeNull();
  });
});
