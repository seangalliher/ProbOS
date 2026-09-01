import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { routeWakeTranscript } from '../audio/wakeWord.router';
import type { WakeAgent } from '../audio/wakeWord.router';

// AD-718c E8 (Vitest): per-agent wake phrase router + collector tests.

vi.mock('../audio/speechInput', () => ({
  startListening: vi.fn(),
  stopListening: vi.fn(),
  isSpeechRecognitionSupported: vi.fn(() => true),
}));
vi.mock('../audio/voice', () => ({
  flushSpeechQueue: vi.fn(),
  getServerPiperVoices: vi.fn(async () => null),
  onSpeechEvent: vi.fn(() => () => undefined),
}));

import {
  startWakeWordLoop,
  _resetForTests,
  _simulateTranscript,
  getWakeWordState,
} from '../audio/wakeWord';

describe('AD-718c per-agent wake-phrase router', () => {
  it('routes "Ezri, run a scan" via per-agent voice_profile.wake_phrase', () => {
    const agents = new Map<string, WakeAgent>([
      [
        'a1',
        {
          callsign: 'Ezri',
          voice_profile: { wake_phrase: 'Ezri' },
        },
      ],
    ]);
    const out = routeWakeTranscript('Ezri, run a scan', agents);
    expect(out).toEqual({
      surface: 'agent',
      agentCallsign: 'Ezri',
      cleanedText: 'run a scan',
    });
  });

  it('agent with empty wake_phrase still matches by callsign', () => {
    const agents = new Map<string, WakeAgent>([
      ['a1', { callsign: 'Ezri', voice_profile: { wake_phrase: '' } }],
    ]);
    const out = routeWakeTranscript('Ezri report', agents);
    expect(out?.surface).toBe('agent');
    expect(out?.agentCallsign).toBe('Ezri');
  });

  it('agent with no voice_profile and no callsign match -> null', () => {
    const agents = new Map<string, WakeAgent>([
      ['a1', { callsign: 'Worf' }],
    ]);
    const out = routeWakeTranscript('Ezri report', agents);
    expect(out).toBeNull();
  });
});

describe('AD-718c per-agent agentTriggers wired into wakeWord loop', () => {
  beforeEach(() => {
    _resetForTests();
    vi.useFakeTimers();
  });
  afterEach(() => {
    _resetForTests();
    vi.useRealTimers();
  });

  it('agentTriggers option fires capturing on a per-agent wake phrase', async () => {
    const onWake = vi.fn();
    await startWakeWordLoop(onWake, {
      agentTriggers: [{ callsign: 'Ezri', phrase: 'Ezri' }],
    });
    expect(getWakeWordState()).toBe('fallback-armed');
    _simulateTranscript('Ezri run a scan now');
    expect(getWakeWordState()).toBe('fallback-capturing');
    vi.advanceTimersByTime(1600);
    expect(onWake).toHaveBeenCalled();
    const arg = onWake.mock.calls[0][0];
    expect(arg.surface).toBe('agent');
    expect(arg.agentCallsign).toBe('Ezri');
  });

  it('empty agentTriggers list does not register per-agent triggers', async () => {
    const onWake = vi.fn();
    await startWakeWordLoop(onWake, { agentTriggers: [] });
    _simulateTranscript('Ezri run a scan');
    // No per-agent trigger registered, so the loop stays armed.
    expect(getWakeWordState()).toBe('fallback-armed');
    expect(onWake).not.toHaveBeenCalled();
  });
});
