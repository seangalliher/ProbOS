/** AD-1071 — Sentence pipelining orchestration through speakResponse.
 *  Uses a FakeAudio harness that can dispatch 'play'/'ended'/'pause' so the
 *  sequential-queue wiring (next sentence starts after prev ends) is exercised
 *  end-to-end. The LOAD-BEARING test here is the flag-OFF default: a
 *  multi-sentence reply still makes exactly ONE POST of the full text
 *  (byte-identical to today). */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

let createdUtterances: FakeUtterance[] = [];
let speakCalls: unknown[] = [];
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
  private _listeners: Record<string, Array<() => void>> = {};
  pause = vi.fn(() => { this.paused = true; this._dispatch('pause'); });
  play = vi.fn(async () => { this.played = true; this._dispatch('play'); });
  constructor(src: string) {
    this.src = src;
    createdAudios.push(this);
  }
  addEventListener(ev: string, fn: () => void): void {
    (this._listeners[ev] ||= []).push(fn);
  }
  private _dispatch(ev: string): void {
    for (const fn of (this._listeners[ev] || [])) fn();
  }
  /** Test hook: simulate playback finishing so the queue advances. */
  end(): void { this._dispatch('ended'); }
}

const fakeVoices: unknown[] = [{ name: 'Microsoft Aria Online (Natural)', lang: 'en-US' }];

function _installGlobals(): void {
  createdUtterances = [];
  speakCalls = [];
  createdAudios = [];
  (globalThis as any).SpeechSynthesisUtterance = FakeUtterance;
  (globalThis as any).Audio = FakeAudio;
  (globalThis as any).window = globalThis;
  (globalThis as any).speechSynthesis = {
    cancel: vi.fn(),
    speak: vi.fn((u: unknown) => speakCalls.push(u)),
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
  for (let i = 0; i < 12; i++) await Promise.resolve();
}

/** Build a fetch mock that records the POSTed text and returns a valid piper
 *  response. ``pipelining`` sets the status flag. */
function _makeFetch(pipelining: boolean, posted: string[]) {
  let nth = 0;
  return vi.fn(async (url: string, opts?: { body?: string }) => {
    if (url.endsWith('/api/avatars/tts/status')) {
      return {
        ok: true,
        json: async () => ({
          enabled: true,
          backend: 'piper',
          sentence_pipelining_enabled: pipelining,
        }),
      } as any;
    }
    if (url === '/api/avatars/tts') {
      const body = JSON.parse(opts?.body ?? '{}');
      posted.push(body.text);
      nth += 1;
      const sha = String.fromCharCode(97 + nth).repeat(64); // 'bbb…','ccc…' — 64 hex-ish
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
    }
    throw new Error(`unexpected fetch to ${url}`);
  });
}

beforeEach(() => { _installGlobals(); });
afterEach(() => { vi.restoreAllMocks(); cleanup(); });

describe('AD-1071 speakResponse — flag OFF (default) is byte-identical', () => {
  it('multi-sentence reply makes exactly ONE POST of the FULL text', async () => {
    // LOAD-BEARING: default-OFF must not change today's one-call-per-reply path.
    const posted: string[] = [];
    (globalThis as any).fetch = _makeFetch(false, posted);
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('One sentence. Two sentence. Three sentence.');
    await _flush();

    expect(posted).toEqual(['One sentence. Two sentence. Three sentence.']);
    expect(createdAudios.length).toBe(1);
  });
});

describe('AD-1071 speakResponse — flag ON pipelines sentences', () => {
  it('speaks sentences sequentially in order; next only after prev ends', async () => {
    const posted: string[] = [];
    (globalThis as any).fetch = _makeFetch(true, posted);
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('One. Two. Three.');
    await _flush();

    // First-audio wins: only the FIRST sentence is synthesized so far.
    expect(posted).toEqual(['One.']);
    expect(createdAudios.length).toBe(1);

    // Finishing sentence[0] triggers sentence[1] — and only then.
    createdAudios[0].end();
    await _flush();
    expect(posted).toEqual(['One.', 'Two.']);
    expect(createdAudios.length).toBe(2);

    createdAudios[1].end();
    await _flush();
    expect(posted).toEqual(['One.', 'Two.', 'Three.']);
    expect(createdAudios.length).toBe(3);

    createdAudios[2].end();
    await _flush();
    // No 4th synthesis after the last sentence ends.
    expect(posted.length).toBe(3);
  });

  it('single-sentence reply with flag ON still uses the single-call path', async () => {
    const posted: string[] = [];
    (globalThis as any).fetch = _makeFetch(true, posted);
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('Only one sentence here.');
    await _flush();

    expect(posted).toEqual(['Only one sentence here.']);
    expect(createdAudios.length).toBe(1);
  });

  it('honest-degrade: a failed sentence synth does not abort the remaining sentences', async () => {
    const posted: string[] = [];
    let nth = 0;
    (globalThis as any).fetch = vi.fn(async (url: string, opts?: { body?: string }) => {
      if (url.endsWith('/api/avatars/tts/status')) {
        return {
          ok: true,
          json: async () => ({ enabled: true, backend: 'piper', sentence_pipelining_enabled: true }),
        } as any;
      }
      const body = JSON.parse(opts?.body ?? '{}');
      posted.push(body.text);
      nth += 1;
      if (nth === 2) {
        // Second sentence's synth fails — must not abort sentence[2].
        return { ok: false, status: 500, json: async () => ({}) } as any;
      }
      const sha = String.fromCharCode(97 + nth).repeat(64);
      return {
        ok: true,
        json: async () => ({
          backend: 'piper', audio_attachment_id: sha, mime: 'audio/wav', visemes: [], duration_ms: 0,
        }),
      } as any;
    });
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('Alpha. Bravo. Charlie.');
    await _flush();
    expect(posted).toEqual(['Alpha.']);
    // Advance past sentence[0].
    createdAudios[0].end();
    await _flush();
    // Sentence[1] synth failed (fell back to browser) and resolved immediately,
    // so the queue already advanced to sentence[2] without a new 'ended'.
    expect(posted).toEqual(['Alpha.', 'Bravo.', 'Charlie.']);
  });

  it('flag ON but browser backend does NOT pipeline (browser fallback)', async () => {
    const posted: string[] = [];
    (globalThis as any).fetch = vi.fn(async (url: string) => {
      if (url.endsWith('/api/avatars/tts/status')) {
        return {
          ok: true,
          json: async () => ({ enabled: true, backend: 'browser', sentence_pipelining_enabled: true }),
        } as any;
      }
      throw new Error(`unexpected fetch to ${url}`);
    });
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('One. Two. Three.');
    await _flush();

    // No POST to the synth endpoint; browser SpeechSynthesis handled it once.
    expect(posted.length).toBe(0);
    expect(createdAudios.length).toBe(0);
    expect(speakCalls.length).toBe(1);
  });
});
