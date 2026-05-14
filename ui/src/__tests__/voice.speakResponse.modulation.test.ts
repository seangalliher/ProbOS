/** AD-718d E7: speakResponse modulation integration tests. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

interface FakeVoice { name: string; lang: string; }

class FakeUtterance {
  text: string;
  rate = 1;
  pitch = 1;
  volume = 1;
  voice: FakeVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  constructor(text: string) { this.text = text; }
}

describe('AD-718d speakResponse modulation', () => {
  let speakSpy: ReturnType<typeof vi.fn>;
  let cancelSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    speakSpy = vi.fn();
    cancelSpy = vi.fn();
    vi.stubGlobal('speechSynthesis', {
      speak: speakSpy,
      cancel: cancelSpy,
      getVoices: () => [],
      addEventListener: vi.fn(),
    });
    vi.stubGlobal(
      'SpeechSynthesisUtterance',
      FakeUtterance as unknown as typeof SpeechSynthesisUtterance,
    );
    // AD-738: route through synchronous browser fallback by removing fetch.
    vi.stubGlobal('fetch', undefined);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
    vi.restoreAllMocks();
  });

  it('without agent_id: utterance receives un-modulated values', async () => {
    vi.resetModules();
    const { speakResponse } = await import('../audio/voice');
    speakResponse('hello', { pitch: 1.0, rate: 1.0, volume: 1.0 });
    expect(speakSpy).toHaveBeenCalledTimes(1);
    const utt = speakSpy.mock.calls[0][0] as FakeUtterance;
    expect(utt.pitch).toBeCloseTo(1.0, 9);
    expect(utt.rate).toBeCloseTo(1.0, 9);
    expect(utt.volume).toBeCloseTo(1.0, 9);
  });

  it('with agent_id: utterance receives modulated values from store signals', async () => {
    vi.resetModules();
    // Mock the useStore module so deriveAgentSignals reads a controlled snapshot.
    vi.doMock('../store/useStore', () => {
      const agents = new Map();
      agents.set('agent-007', { id: 'agent-007', state: 'active' });
      return {
        useStore: {
          getState: () => ({
            agents,
            processing: true,        // → working_state: 'responding'
            notifications: [],
          }),
        },
      };
    });
    const { speakResponse } = await import('../audio/voice');
    speakResponse('hello', { pitch: 1.0, rate: 1.0, volume: 1.0 }, 'agent-007');
    const utt = speakSpy.mock.calls[0][0] as FakeUtterance;
    // working_state 'responding' multiplies rate by 1.05.
    expect(utt.rate).toBeCloseTo(1.05, 9);
    // pitch and volume unchanged by the rule.
    expect(utt.pitch).toBeCloseTo(1.0, 9);
  });

  it('with agent_id but failing store: falls back to unmodulated baseline', async () => {
    vi.resetModules();
    vi.doMock('../store/useStore', () => ({
      useStore: {
        getState: () => { throw new Error('store unavailable'); },
      },
    }));
    const { speakResponse } = await import('../audio/voice');
    expect(() => speakResponse('hi', { pitch: 1.0, rate: 1.0, volume: 1.0 }, 'agent-007')).not.toThrow();
    expect(speakSpy).toHaveBeenCalledTimes(1);
    const utt = speakSpy.mock.calls[0][0] as FakeUtterance;
    expect(utt.pitch).toBeCloseTo(1.0, 9);
    expect(utt.rate).toBeCloseTo(1.0, 9);
    expect(utt.volume).toBeCloseTo(1.0, 9);
  });
});
