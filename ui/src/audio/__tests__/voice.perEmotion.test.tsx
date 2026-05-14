/** AD-738e-1 (Wave 158): voice.ts per-emotion POST body.
 *  Two tests pinning the emotion-forwarding contract. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

let createdUtterances: any[] = [];
let speakCalls: any[] = [];
let createdAudios: any[] = [];

class FakeUtterance {
  text: string;
  rate = 1; pitch = 1; volume = 1;
  voice: any = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  constructor(text: string) { this.text = text; createdUtterances.push(this); }
}

class FakeAudio {
  src: string;
  volume = 1;
  playbackRate = 1;
  preservesPitch = true;
  paused = false;
  pause = vi.fn(() => { this.paused = true; });
  play = vi.fn(async () => {});
  private _listeners: Record<string, Array<() => void>> = {};
  constructor(src: string) { this.src = src; createdAudios.push(this); }
  addEventListener(ev: string, fn: () => void): void {
    (this._listeners[ev] ||= []).push(fn);
  }
}

function _installGlobals() {
  createdUtterances = [];
  speakCalls = [];
  createdAudios = [];
  (globalThis as any).SpeechSynthesisUtterance = FakeUtterance;
  (globalThis as any).Audio = FakeAudio;
  (globalThis as any).window = globalThis;
  (globalThis as any).speechSynthesis = {
    cancel: vi.fn(),
    speak: vi.fn((u: any) => speakCalls.push(u)),
    getVoices: () => [],
    addEventListener: vi.fn(),
  };
  if (!(globalThis as any).localStorage) {
    (globalThis as any).localStorage = {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    };
  }
}

async function _flush(): Promise<void> {
  for (let i = 0; i < 15; i++) await Promise.resolve();
}

beforeEach(() => { _installGlobals(); });

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

function _makeFetchMock(): { fetch: any; postBodies: string[] } {
  const postBodies: string[] = [];
  const fetchMock = vi.fn(async (url: string, init?: any) => {
    if (url.endsWith('/api/avatars/tts/status')) {
      return {
        ok: true,
        json: async () => ({ enabled: true, backend: 'piper' }),
      } as any;
    }
    if (url.endsWith('/api/avatars/tts')) {
      if (init && typeof init.body === 'string') {
        postBodies.push(init.body);
      }
      return {
        ok: true,
        json: async () => ({
          backend: 'piper',
          audio_attachment_id: 'a'.repeat(64),
          mime: 'audio/wav',
          visemes: [],
          duration_ms: 0,
        }),
      } as any;
    }
    throw new Error(`unexpected fetch to ${url}`);
  });
  return { fetch: fetchMock, postBodies };
}

describe('AD-738e-1 speakResponse emotion forwarding', () => {
  it('includes emotion field in POST body when provided', async () => {
    const { fetch, postBodies } = _makeFetchMock();
    (globalThis as any).fetch = fetch;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('hello', undefined, 'counselor', 'concerned');
    await _flush();
    await _flush();

    expect(postBodies.length).toBe(1);
    expect(JSON.parse(postBodies[0])).toEqual({
      text: 'hello',
      emotion: 'concerned',
    });
  });

  it('omits emotion field when undefined (backward compat)', async () => {
    const { fetch, postBodies } = _makeFetchMock();
    (globalThis as any).fetch = fetch;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('hello', undefined, 'counselor');
    await _flush();
    await _flush();

    expect(postBodies.length).toBe(1);
    expect(JSON.parse(postBodies[0])).toEqual({ text: 'hello' });
  });
});
