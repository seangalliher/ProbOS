/** AD-718: voice.ts unit tests — VoiceProfile, listeners, stripMarkdownForSpeech. */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// Capture utterance instances for assertion.
let createdUtterances: any[] = [];
let speakCalls: any[] = [];

class FakeUtterance {
  text: string;
  rate = 1;
  pitch = 1;
  volume = 1;
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  constructor(text: string) {
    this.text = text;
    createdUtterances.push(this);
  }
}

const fakeVoices: any[] = [
  { name: 'Microsoft Aria Online (Natural)', lang: 'en-US' },
  { name: 'Default', lang: 'en-US' },
];

beforeEach(() => {
  createdUtterances = [];
  speakCalls = [];
  (globalThis as any).SpeechSynthesisUtterance = FakeUtterance;
  (globalThis as any).window = globalThis;
  (globalThis as any).speechSynthesis = {
    cancel: vi.fn(),
    speak: vi.fn((u: any) => speakCalls.push(u)),
    getVoices: () => fakeVoices,
    addEventListener: vi.fn(),
  };
  // Silence localStorage in this environment.
  if (!(globalThis as any).localStorage) {
    (globalThis as any).localStorage = {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    };
  }
});

describe('AD-718 speakResponse', () => {
  it('uses profile pitch/rate/volume when provided', async () => {
    const { speakResponse } = await import('../voice');
    speakResponse('hello', { pitch: 1.05, rate: 0.92, volume: 0.85 }, 'agent-007');
    expect(speakCalls.length).toBe(1);
    const u = createdUtterances[0];
    expect(u.pitch).toBeCloseTo(1.05);
    expect(u.rate).toBeCloseTo(0.92);
    expect(u.volume).toBeCloseTo(0.85);
  });

  it('falls back to v0 defaults when profile omitted', async () => {
    const { speakResponse } = await import('../voice');
    speakResponse('hello');
    const u = createdUtterances[0];
    expect(u.pitch).toBeCloseTo(0.9);
    expect(u.rate).toBeCloseTo(0.95);
    expect(u.volume).toBeCloseTo(0.8);
  });

  it('resolves voice by name when present in catalogue', async () => {
    const { speakResponse } = await import('../voice');
    speakResponse('hi', { voice_name: 'Microsoft Aria Online (Natural)' });
    const u = createdUtterances[0];
    expect(u.voice?.name).toBe('Microsoft Aria Online (Natural)');
  });
});

describe('AD-718 stripMarkdownForSpeech', () => {
  it('strips bold/italic/headings/lists/code/links/blank lines', async () => {
    const { stripMarkdownForSpeech } = await import('../voice');
    const input = '**Bold** and *italic*\n# Heading\n- bullet\n`code`\n[link](http://x)\n\nnew para';
    const out = stripMarkdownForSpeech(input);
    expect(out).toContain('Bold and italic');
    expect(out).toContain('Heading');
    expect(out).toContain('bullet');
    expect(out).toContain('code');
    expect(out).toContain('link');
    expect(out).not.toContain('**');
    expect(out).not.toContain('`');
  });
});

describe('AD-718 onSpeechEvent', () => {
  it('fires start and end with agent_id', async () => {
    const { speakResponse, onSpeechEvent } = await import('../voice');
    const events: any[] = [];
    const off = onSpeechEvent((e) => events.push(e));
    speakResponse('hi', undefined, 'agent-42');
    const u = createdUtterances[0];
    u.onstart?.();
    u.onend?.();
    off();
    expect(events.length).toBe(2);
    expect(events[0].type).toBe('start');
    expect(events[0].agent_id).toBe('agent-42');
    expect(events[1].type).toBe('end');
  });

  it('a throwing listener does not break TTS for other listeners', async () => {
    const { speakResponse, onSpeechEvent } = await import('../voice');
    const errSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const calls: string[] = [];
    const off1 = onSpeechEvent(() => { throw new Error('boom'); });
    const off2 = onSpeechEvent(() => calls.push('ok'));
    speakResponse('hi');
    const u = createdUtterances[0];
    u.onstart?.();
    off1(); off2();
    expect(calls).toEqual(['ok']);
    errSpy.mockRestore();
  });
});
