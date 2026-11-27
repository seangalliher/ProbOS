/** AD-738g (#1662) S1: any TTS backend other than `browser` takes the server path.
 *  The gate used to test `backend !== 'piper'`, so a `kokoro` status made the browser speak. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

let speakCalls: any[] = [];
let createdAudios: FakeAudio[] = [];
const SHA = 'b'.repeat(64);

class FakeUtterance {
  text: string;
  rate = 1; pitch = 1; volume = 1;
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  constructor(text: string) { this.text = text; }
}

class FakeAudio {
  src: string;
  volume = 1;
  playbackRate = 1;
  preservesPitch = true;
  paused = false;
  pause = vi.fn(() => { this.paused = true; });
  play = vi.fn(async () => {});
  listeners: Record<string, Array<() => void>> = {};
  constructor(src: string) { this.src = src; createdAudios.push(this); }
  addEventListener(ev: string, fn: () => void): void { (this.listeners[ev] ||= []).push(fn); }
}

function installGlobals(): void {
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
    (globalThis as any).localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  }
}

async function flush(): Promise<void> {
  for (let i = 0; i < 10; i++) await Promise.resolve();
}

function fetchFor(status: Record<string, unknown>) {
  return vi.fn(async (url: string) => {
    if (url.endsWith('/api/avatars/tts/status')) return { ok: true, json: async () => status } as any;
    if (url === '/api/avatars/tts') {
      return {
        ok: true,
        json: async () => ({ backend: 'kokoro', audio_attachment_id: SHA, mime: 'audio/wav', visemes: [], duration_ms: 1000 }),
      } as any;
    }
    throw new Error(`unexpected fetch to ${url}`);
  });
}

const count = (m: ReturnType<typeof fetchFor>, pred: (u: string) => boolean) =>
  m.mock.calls.map((c) => c[0] as string).filter(pred).length;

beforeEach(() => {
  vi.resetModules();
  installGlobals();
});

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

describe('AD-738g speakResponse: the kokoro backend takes the server path', () => {
  it('posts to /api/avatars/tts and plays the audio when the status reports backend=kokoro', async () => {
    const fetchMock = fetchFor({ enabled: true, backend: 'kokoro', sentence_pipelining_enabled: false });
    (globalThis as any).fetch = fetchMock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('Good evening, Captain.');
    await flush();

    expect(count(fetchMock, (u) => u === '/api/avatars/tts')).toBe(1);
    expect(createdAudios.length).toBe(1);
    expect(createdAudios[0].src).toBe(`/api/chat/attachments/${SHA}`);
    expect(speakCalls.length).toBe(0);
  });

  it('makes no POST when the status reports kokoro but enabled=false', async () => {
    const fetchMock = fetchFor({ enabled: false, backend: 'kokoro', sentence_pipelining_enabled: false });
    (globalThis as any).fetch = fetchMock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('hi');
    await flush();

    expect(count(fetchMock, (u) => u === '/api/avatars/tts')).toBe(0);
    expect(speakCalls.length).toBe(1);
  });

  it('a cached kokoro status takes the server path on the next utterance without a second probe', async () => {
    const fetchMock = fetchFor({ enabled: true, backend: 'kokoro', sentence_pipelining_enabled: false });
    (globalThis as any).fetch = fetchMock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('one');
    await flush();
    expect(createdAudios.length).toBe(1);
    (createdAudios[0].listeners.ended || []).forEach((fn) => fn());
    await flush();
    voiceMod.speakResponse('two');
    await flush();

    expect(count(fetchMock, (u) => u.includes('/api/avatars/tts/status'))).toBe(1);
    expect(count(fetchMock, (u) => u === '/api/avatars/tts')).toBe(2);
    expect(speakCalls.length).toBe(0);
  });
});
