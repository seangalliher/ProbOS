import { describe, it, expect } from 'vitest';
import { routeWakeTranscript } from '../audio/wakeWord.router';
import type { WakeAgent } from '../audio/wakeWord.router';

// AD-705 D8 test #6-9: router cases.

const _agentMap = (
  rows: Array<{ id: string; callsign: string; wakePhrase?: string }>,
): ReadonlyMap<string, WakeAgent> => {
  const m = new Map<string, WakeAgent>();
  for (const r of rows) {
    m.set(r.id, {
      callsign: r.callsign,
      voice_profile: r.wakePhrase ? { wake_phrase: r.wakePhrase } : undefined,
    });
  }
  return m;
};

describe('routeWakeTranscript (AD-705 D4)', () => {
  it('6. "Computer, ..." routes to the system surface, prefix stripped', () => {
    const out = routeWakeTranscript(
      "Computer, what's the load?",
      new Map(),
    );
    expect(out).toEqual({
      surface: 'system',
      cleanedText: "what's the load?",
    });
  });

  it('7. "Hey Ezri, ..." routes to the agent surface with cleaned text', () => {
    const out = routeWakeTranscript(
      'Hey Ezri, run a scan',
      _agentMap([{ id: 'a1', callsign: 'Ezri' }]),
    );
    expect(out).toEqual({
      surface: 'agent',
      agentCallsign: 'Ezri',
      cleanedText: 'run a scan',
    });
  });

  it('8. transcript with no recognised prefix and no preceding wake -> null', () => {
    const out = routeWakeTranscript(
      'random words with no prefix',
      _agentMap([{ id: 'a1', callsign: 'Ezri' }]),
    );
    expect(out).toBeNull();
  });

  it('9. transcript with no prefix BUT postWakeWord=true routes to system', () => {
    const out = routeWakeTranscript(
      'random words with no prefix',
      new Map(),
      { postWakeWord: true },
    );
    expect(out).toEqual({
      surface: 'system',
      cleanedText: 'random words with no prefix',
    });
  });

  it('ambiguous prefix: system wake wins over agent callsign', () => {
    const out = routeWakeTranscript(
      'Computer help',
      _agentMap([{ id: 'a1', callsign: 'Computer' }]),
    );
    expect(out?.surface).toBe('system');
  });

  it('agent voice_profile.wake_phrase takes precedence over callsign', () => {
    const out = routeWakeTranscript(
      'Counselor what now',
      _agentMap([{ id: 'a1', callsign: 'Ezri', wakePhrase: 'Counselor' }]),
    );
    expect(out).toEqual({
      surface: 'agent',
      agentCallsign: 'Ezri',
      cleanedText: 'what now',
    });
  });
});
