/** AD-718e: voice.ts language-aware voice resolution tests. */
import { describe, it, expect, beforeEach, vi } from 'vitest';

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

// Mixed-language catalog used across all tests in this file.
const fakeVoices: any[] = [
  { name: 'English One', lang: 'en-US' },
  { name: 'Spanish One', lang: 'es-ES' },
  { name: 'French One', lang: 'fr-FR' },
];

beforeEach(() => {
  createdUtterances = [];
  speakCalls = [];
  vi.resetModules();
  (globalThis as any).fetch = undefined;
  (globalThis as any).SpeechSynthesisUtterance = FakeUtterance;
  (globalThis as any).window = globalThis;
  (globalThis as any).speechSynthesis = {
    cancel: vi.fn(),
    speak: vi.fn((u: any) => speakCalls.push(u)),
    getVoices: () => fakeVoices,
    addEventListener: vi.fn(),
  };
  if (!(globalThis as any).localStorage) {
    (globalThis as any).localStorage = {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    };
  }
});

describe('AD-718e voice language resolution', () => {
  it('prefers_voice_matching_profile_language_over_en_fallback', async () => {
    const { speakResponse } = await import('../voice');
    speakResponse('hola', { language: 'es' }, 'agent-x');
    const u = createdUtterances[0];
    expect(u.voice?.lang).toBe('es-ES');
  });

  it('falls_back_to_en_when_profile_language_voice_unavailable', async () => {
    const { speakResponse } = await import('../voice');
    speakResponse('ciao', { language: 'it' }, 'agent-x');
    const u = createdUtterances[0];
    // No it-* voice in the catalog; falls back to findPreferredVoice (en).
    expect(u.voice?.lang.startsWith('en')).toBe(true);
  });

  it('defaults_to_en_when_profile_language_undefined', async () => {
    const { speakResponse } = await import('../voice');
    speakResponse('hi', undefined, 'agent-x');
    const u = createdUtterances[0];
    expect(u.voice?.lang.startsWith('en')).toBe(true);
  });
});
