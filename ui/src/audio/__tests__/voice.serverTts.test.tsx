/** AD-738 (Wave 157): server-streamed TTS — voice.ts speakResponse tests.
 *  Asserts the load-bearing zero-HTTP-per-utterance default-config guarantee
 *  AND the piper happy path AND honest-degrade fallbacks. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';

let createdUtterances: any[] = [];
let speakCalls: any[] = [];
let createdAudios: FakeAudio[] = [];

class FakeUtterance {
  text: string;
  rate = 1; pitch = 1; volume = 1;
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  constructor(text: string) {
    this.text = text;
    createdUtterances.push(this);
  }
}

class FakeAudio {
  src: string;
  volume = 1;
  playbackRate = 1;
  preservesPitch = true;
  paused = false;
  played = false;
  pause = vi.fn(() => { this.paused = true; });
  play = vi.fn(async () => { this.played = true; });
  private _listeners: Record<string, Array<() => void>> = {};
  constructor(src: string) {
    this.src = src;
    createdAudios.push(this);
  }
  addEventListener(ev: string, fn: () => void): void {
    (this._listeners[ev] ||= []).push(fn);
  }
}

const fakeVoices: any[] = [
  { name: 'Microsoft Aria Online (Natural)', lang: 'en-US' },
];

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
}

async function _flush(): Promise<void> {
  for (let i = 0; i < 10; i++) await Promise.resolve();
}

beforeEach(() => {
  _installGlobals();
});

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

describe('AD-738 speakResponse — default-config (browser) zero-HTTP guarantee', () => {
  it('makes ZERO POST to /api/avatars/tts when status reports backend=browser (default config)', async () => {
    // LOAD-BEARING test for Captain decision #9.
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/api/avatars/tts/status')) {
        return {
          ok: true,
          json: async () => ({ enabled: true, backend: 'browser' }),
        } as any;
      }
      throw new Error(`unexpected fetch to ${url}`);
    });
    (globalThis as any).fetch = fetchMock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('one');
    voiceMod.speakResponse('two');
    voiceMod.speakResponse('three');
    await _flush();

    // Exactly ONE GET probe across the whole session — no POST.
    const urls = fetchMock.mock.calls.map((c) => c[0] as string);
    const probeCalls = urls.filter((u) => u.includes('/api/avatars/tts/status'));
    const ttsPosts = urls.filter((u) => u === '/api/avatars/tts');
    expect(probeCalls.length).toBe(1);
    expect(ttsPosts.length).toBe(0);
    // AD-1291: this line used to read `expect(speakCalls.length).toBe(3)`
    // immediately after the three calls, which pinned the very defect BF-858
    // fixes -- three producers all reaching the one audio device at once, each
    // cancelling the last. `speakResponse` now enqueues, so only the head is
    // dispatched until it ends. The count of 3 is still asserted below; it is
    // now reached by ENDING each utterance, which also proves the arbiter
    // serialises rather than drops.
    expect(speakCalls.length).toBe(1);
    for (let i = 0; i < 3 && createdUtterances[i]; i += 1) {
      createdUtterances[i].onend?.();
      await _flush();
    }
    expect(speakCalls.length).toBe(3);
    // Draining the queue must not have re-probed or started POSTing.
    const urlsAfter = fetchMock.mock.calls.map((c) => c[0] as string);
    expect(urlsAfter.filter((u) => u.includes('/api/avatars/tts/status')).length).toBe(1);
    expect(urlsAfter.filter((u) => u === '/api/avatars/tts').length).toBe(0);
  });
});

describe('AD-738 speakResponse — piper path', () => {
  it('falls back to SpeechSynthesis when /api/avatars/tts returns disabled', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/api/avatars/tts/status')) {
        return { ok: true, json: async () => ({ enabled: true, backend: 'piper' }) } as any;
      }
      if (url === '/api/avatars/tts') {
        return {
          ok: true,
          json: async () => ({
            backend: 'disabled',
            audio_attachment_id: null,
            mime: null,
            visemes: [],
            duration_ms: 0,
          }),
        } as any;
      }
      throw new Error(`unexpected fetch to ${url}`);
    });
    (globalThis as any).fetch = fetchMock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('hi');
    await _flush();

    expect(speakCalls.length).toBe(1);
    expect(createdAudios.length).toBe(0);
  });

  it('falls back to SpeechSynthesis on POST fetch error', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/api/avatars/tts/status')) {
        return { ok: true, json: async () => ({ enabled: true, backend: 'piper' }) } as any;
      }
      throw new Error('network error');
    });
    (globalThis as any).fetch = fetchMock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('hi');
    await _flush();

    expect(speakCalls.length).toBe(1);
    expect(createdAudios.length).toBe(0);
  });

  it('plays <audio> when probe=piper and POST returns valid attachment_id', async () => {
    const sha = 'a'.repeat(64);
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/api/avatars/tts/status')) {
        return { ok: true, json: async () => ({ enabled: true, backend: 'piper' }) } as any;
      }
      return {
        ok: true,
        json: async () => ({
          backend: 'piper',
          audio_attachment_id: sha,
          mime: 'audio/wav',
          visemes: [],
          duration_ms: 1000,
        }),
      } as any;
    });
    (globalThis as any).fetch = fetchMock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('hi');
    await _flush();

    expect(createdAudios.length).toBe(1);
    expect(createdAudios[0].src).toBe(`/api/chat/attachments/${sha}`);
    expect(createdAudios[0].play).toHaveBeenCalled();
    // SpeechSynthesis NOT used in the happy path.
    expect(speakCalls.length).toBe(0);
  });

  it('forwards visemes to useLipSyncCapture via injection registry', async () => {
    const sha = 'b'.repeat(64);
    const visemes = [{ time: 0, duration: 0.1, viseme: 'aa' }];
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/api/avatars/tts/status')) {
        return { ok: true, json: async () => ({ enabled: true, backend: 'piper' }) } as any;
      }
      return {
        ok: true,
        json: async () => ({
          backend: 'piper',
          audio_attachment_id: sha,
          mime: 'audio/wav',
          visemes,
          duration_ms: 100,
        }),
      } as any;
    });
    (globalThis as any).fetch = fetchMock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();
    const { useLipSyncCapture } = await import('../useLipSyncCapture');
    const { result } = renderHook(() =>
      useLipSyncCapture({ enabled: true, agentId: 'agent-7' }),
    );

    voiceMod.speakResponse('hi', undefined, 'agent-7');
    await act(async () => { await _flush(); });

    expect(result.current.frames).toEqual(visemes);
  });

  it('second speakResponse cancels in-flight <audio> from first', async () => {
    // AD-1291: this test used to call `speakResponse` twice back to back and
    // assert the second had ALREADY paused the first -- i.e. it pinned the
    // BF-858 defect as the contract. Two producers no longer race for the
    // device: the second QUEUES. The pause mechanism it guards is still real
    // and still needed, but it is now reached only when the arbiter hands the
    // device over -- either after a terminal 'end' or, as here, after GUARD 2
    // gives up on an utterance whose 'end' never arrived and whose <audio> is
    // therefore still playing. That is the only path on which one utterance's
    // audio can still be live when the next one starts.
    vi.useFakeTimers();
    const sha1 = 'c'.repeat(64);
    const sha2 = 'd'.repeat(64);
    let nth = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/api/avatars/tts/status')) {
        return { ok: true, json: async () => ({ enabled: true, backend: 'piper' }) } as any;
      }
      nth += 1;
      const sha = nth === 1 ? sha1 : sha2;
      return {
        ok: true,
        json: async () => ({
          backend: 'piper',
          audio_attachment_id: sha,
          mime: 'audio/wav',
          visemes: [],
          duration_ms: 0,
        }),
      } as any;
    });
    (globalThis as any).fetch = fetchMock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('first');
    await _flush();
    expect(createdAudios.length).toBe(1);
    const first = createdAudios[0];
    expect(first.play).toHaveBeenCalled();

    // Queued, NOT dispatched: the first still owns the device.
    voiceMod.speakResponse('second');
    await _flush();
    expect(createdAudios.length).toBe(1);
    expect(first.pause).not.toHaveBeenCalled();

    // The first utterance's 'end' never comes; GUARD 2 releases the queue.
    await vi.advanceTimersByTimeAsync(voiceMod.SPEECH_JOIN_TIMEOUT_MS + 1);
    await _flush();

    expect(createdAudios.length).toBe(2);
    // The first audio was paused before the second's play was issued.
    expect(first.pause).toHaveBeenCalled();
    vi.useRealTimers();
  });
});
