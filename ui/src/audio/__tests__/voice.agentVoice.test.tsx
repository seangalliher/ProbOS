/** AD-738f (#1868) S1: each spoken sentence carries the speaking crew member's id, so the server
 *  can give each role its own Kokoro voice. No id, no field; the browser path posts nothing. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

const AGENT = 'counselor_counselor_0_1a2b3c4d';
const SHA = 'c'.repeat(64);
let speakCalls: any[] = [];
let createdAudios: FakeAudio[] = [];

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
  for (let i = 0; i < 30; i++) await Promise.resolve();
}

function fetchFor(status: Record<string, unknown>) {
  const posts: Array<Record<string, unknown>> = [];
  const mock = vi.fn(async (url: string, init?: { body?: string }) => {
    if (url.endsWith('/api/avatars/tts/status')) return { ok: true, json: async () => status } as any;
    if (url === '/api/avatars/tts') {
      posts.push(JSON.parse(init?.body ?? '{}'));
      return {
        ok: true,
        json: async () => ({ backend: 'kokoro', audio_attachment_id: SHA, mime: 'audio/wav', visemes: [], duration_ms: 1000 }),
      } as any;
    }
    throw new Error(`unexpected fetch to ${url}`);
  });
  return { mock, posts };
}

beforeEach(() => {
  vi.resetModules();
  installGlobals();
});

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

describe('AD-738f speakResponse sends the speaking agent id', () => {
  it('a sentence spoken for an agent carries its id', async () => {
    const { mock, posts } = fetchFor({ enabled: true, backend: 'kokoro', sentence_pipelining_enabled: false });
    (globalThis as any).fetch = mock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('Good evening, Captain.', undefined, AGENT);
    await flush();

    expect(posts).toEqual([{ text: 'Good evening, Captain.', defer_visemes: true, agent_id: AGENT }]);
    expect(createdAudios.length).toBe(1);
  });

  it('a sentence spoken for no agent carries no agent_id', async () => {
    const { mock, posts } = fetchFor({ enabled: true, backend: 'kokoro', sentence_pipelining_enabled: false });
    (globalThis as any).fetch = mock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('Good evening, Captain.');
    await flush();

    expect(posts).toEqual([{ text: 'Good evening, Captain.', defer_visemes: true }]);
  });

  it('every pipelined sentence carries the id', async () => {
    const { mock, posts } = fetchFor({ enabled: true, backend: 'kokoro', sentence_pipelining_enabled: true });
    (globalThis as any).fetch = mock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('First sentence here. Second sentence here.', undefined, AGENT);
    await flush();
    await flush();
    await flush();

    expect(posts.map((p) => p.text)).toEqual(['First sentence here.', 'Second sentence here.']);
    expect(posts.map((p) => p.agent_id)).toEqual([AGENT, AGENT]);
  });

  it('the browser backend posts nothing, even for an agent', async () => {
    const { mock, posts } = fetchFor({ enabled: true, backend: 'browser', sentence_pipelining_enabled: false });
    (globalThis as any).fetch = mock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('hi', undefined, AGENT);
    await flush();

    expect(posts).toEqual([]);
    expect(mock.mock.calls.filter((c) => c[0] === '/api/avatars/tts').length).toBe(0);
    expect(speakCalls.length).toBe(1);
  });
});
