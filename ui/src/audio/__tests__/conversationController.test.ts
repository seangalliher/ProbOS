/**
 * AD-747 — ConversationController state-machine + wiring tests.
 *
 * Mocks the cross-module collaborators at the import boundary so the
 * controller's logic is exercised in isolation:
 *   - whisperStt (armWhisperStt, disarmWhisperStt, onTranscript)
 *   - voiceActivity (subscribePcm)
 *   - voice (stopSpeaking)
 *   - speechRecognitionArbiter (acquire, release)
 *
 * Network: fetch is stubbed via vi.spyOn(global, 'fetch').
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// --- Mocks at the module boundary --------------------------------------------

const _whisperState: {
  armed: boolean;
  listener: ((text: string) => void) | null;
} = { armed: false, listener: null };

vi.mock('../whisperStt', () => ({
  armWhisperStt: () => {
    _whisperState.armed = true;
    return () => { _whisperState.armed = false; };
  },
  disarmWhisperStt: () => { _whisperState.armed = false; },
  onTranscript: (l: (text: string) => void) => {
    _whisperState.listener = l;
    return () => { _whisperState.listener = null; };
  },
}));

const _vadState: {
  handler: { onSpeechStart?: () => void; onSpeechEnd?: () => void } | null;
} = { handler: null };

vi.mock('../voiceActivity', () => ({
  subscribePcm: (h: { onSpeechStart?: () => void; onSpeechEnd?: () => void }) => {
    _vadState.handler = h;
    return () => { _vadState.handler = null; };
  },
}));

const _voiceState: { stopSpeakingCalls: number } = { stopSpeakingCalls: 0 };
vi.mock('../voice', () => ({
  stopSpeaking: () => { _voiceState.stopSpeakingCalls += 1; },
}));

// Imports must come AFTER vi.mock declarations.
import {
  armConversationMode,
  disarmConversationMode,
  getConversationState,
  markAgentReplyComplete,
  _resetConversationControllerForTests,
} from '../conversationController';
import {
  _resetForTests as _resetArbiter,
  PRIORITY_PRESS_TO_TALK,
  acquire as arbiterAcquire,
  currentHolder,
} from '../speechRecognitionArbiter';

function _resetAll(): void {
  _resetConversationControllerForTests();
  _resetArbiter();
  _whisperState.armed = false;
  _whisperState.listener = null;
  _vadState.handler = null;
  _voiceState.stopSpeakingCalls = 0;
}

beforeEach(() => {
  _resetAll();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('AD-747 ConversationController', () => {
  it('arm grants arbiter lease at PRIORITY_CONVERSATION', () => {
    armConversationMode({ agentId: 'counselor-001' });
    expect(currentHolder()).toEqual({
      holder: 'conversation',
      priority: 75,
    });
    expect(getConversationState()).toBe('listening');
    expect(_whisperState.armed).toBe(true);
    expect(_vadState.handler).not.toBeNull();
  });

  it('arm without agentId is a no-op', () => {
    armConversationMode({ agentId: '' });
    expect(getConversationState()).toBe('inactive');
    expect(currentHolder()).toBeNull();
  });

  it('disarm releases lease and cancels silence timer', () => {
    armConversationMode({ agentId: 'a' });
    disarmConversationMode();
    expect(getConversationState()).toBe('inactive');
    expect(currentHolder()).toBeNull();
    expect(_whisperState.armed).toBe(false);
    expect(_vadState.handler).toBeNull();
  });

  it('VAD speech_end + whisper transcript triggers POST to /api/agent/{id}/chat', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'Hello, Captain.' }),
    } as unknown as Response);
    armConversationMode({ agentId: 'counselor-001' });
    expect(_whisperState.listener).not.toBeNull();
    // Whisper fires a finalized transcript.
    _whisperState.listener!('how are you');
    // Allow the awaited fetch chain to resolve.
    await vi.runAllTimersAsync();
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/agent/counselor-001/chat',
      expect.objectContaining({ method: 'POST' }),
    );
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toMatchObject({
      message: 'how are you',
    });
  });

  it('agent reply transitions controller to agent_speaking', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'Hi.' }),
    } as unknown as Response);
    armConversationMode({ agentId: 'counselor-001' });
    _whisperState.listener!('hello');
    await vi.runAllTimersAsync();
    expect(getConversationState()).toBe('agent_speaking');
  });

  it('barge-in: VAD speech_start during agent_speaking calls stopSpeaking and re-enters listening', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'Hi.' }),
    } as unknown as Response);
    armConversationMode({ agentId: 'counselor-001' });
    _whisperState.listener!('hello');
    await vi.runAllTimersAsync();
    expect(getConversationState()).toBe('agent_speaking');
    // User barges in.
    _vadState.handler!.onSpeechStart!();
    expect(_voiceState.stopSpeakingCalls).toBe(1);
    expect(getConversationState()).toBe('listening');
  });

  it('barge-in OFF: VAD speech_start during agent_speaking does NOT call stopSpeaking', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'Hi.' }),
    } as unknown as Response);
    armConversationMode({
      agentId: 'counselor-001',
      bargeInEnabled: false,
    });
    _whisperState.listener!('hello');
    await vi.runAllTimersAsync();
    expect(getConversationState()).toBe('agent_speaking');
    _vadState.handler!.onSpeechStart!();
    expect(_voiceState.stopSpeakingCalls).toBe(0);
    expect(getConversationState()).toBe('agent_speaking');
  });

  it('silence timer: markAgentReplyComplete starts the timer; expiry disarms', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'Hi.' }),
    } as unknown as Response);
    armConversationMode({
      agentId: 'counselor-001',
      silenceTimeoutMs: 5000,
    });
    _whisperState.listener!('hello');
    await vi.runAllTimersAsync();
    expect(getConversationState()).toBe('agent_speaking');
    markAgentReplyComplete();
    expect(getConversationState()).toBe('silence_pending');
    vi.advanceTimersByTime(5000);
    expect(getConversationState()).toBe('inactive');
    expect(currentHolder()).toBeNull();
  });

  it('press-to-talk preempts the conversation lease and disarms cleanly', () => {
    armConversationMode({ agentId: 'counselor-001' });
    expect(currentHolder()!.holder).toBe('conversation');
    arbiterAcquire({
      holder: 'press_to_talk',
      priority: PRIORITY_PRESS_TO_TALK,
    });
    // Preemption fired the controller's onPreempted → disarm.
    expect(getConversationState()).toBe('inactive');
    expect(currentHolder()!.holder).toBe('press_to_talk');
  });

  it('transcript hook fires before submission (HXI preview pill seam)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ reply: 'ok' }),
    } as unknown as Response);
    const captured: string[] = [];
    armConversationMode({
      agentId: 'counselor-001',
      onTranscript: (t) => captured.push(t),
    });
    _whisperState.listener!('what is the weather');
    await vi.runAllTimersAsync();
    expect(captured).toEqual(['what is the weather']);
  });

  it('empty transcript is dropped (no fetch fired)', async () => {
    armConversationMode({ agentId: 'counselor-001' });
    // Spy AFTER arm so we only see fetches caused by transcript handling.
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({}),
    } as unknown as Response);
    fetchSpy.mockClear();
    _whisperState.listener!('   ');
    await vi.runAllTimersAsync();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(getConversationState()).toBe('listening');
  });
});
