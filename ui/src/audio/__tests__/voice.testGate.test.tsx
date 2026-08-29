/** AD-738a (Wave 158): voice.ts `_resetTtsStatusForTests` MODE-gate.
 *  Asserts that the test-affordance helper is a no-op when
 *  `import.meta.env.MODE !== 'test'` (production builds), preserving
 *  the AD-738 zero-HTTP-per-utterance cache from accidental production
 *  resets. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

beforeEach(() => {
  (globalThis as any).window = globalThis;
  if (!(globalThis as any).localStorage) {
    (globalThis as any).localStorage = {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    };
  }
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  cleanup();
});

async function _flush(): Promise<void> {
  for (let i = 0; i < 10; i++) await Promise.resolve();
}

/** AD-1291: `speakResponse` now ENQUEUES against the speech arbiter, so a
 *  second call queues behind the first instead of reaching the device. Both
 *  cases below prime the cache with one utterance and then probe with a
 *  second, so the first has to be ENDED or the second never dispatches and
 *  neither assertion can discriminate -- the production-guard case in
 *  particular would pass whether or not the cache had been wrongly cleared.
 *  These stubs record their instances so the test can end them. */
let createdUtterances: Array<{ text: string; onend: (() => void) | null }> = [];

function _installSpeechStubs(): void {
  createdUtterances = [];
  (globalThis as any).SpeechSynthesisUtterance = class {
    text: string;
    onstart: (() => void) | null = null;
    onend: (() => void) | null = null;
    onerror: (() => void) | null = null;
    constructor(t: string) { this.text = t; createdUtterances.push(this as any); }
  };
  (globalThis as any).speechSynthesis = {
    cancel: vi.fn(),
    speak: vi.fn(),
    getVoices: () => [],
    addEventListener: vi.fn(),
  };
}

/** End every utterance the arbiter has dispatched so far, releasing the queue. */
async function _endAll(): Promise<void> {
  for (const u of [...createdUtterances]) u.onend?.();
  await _flush();
}

describe('AD-738a _resetTtsStatusForTests MODE-gate', () => {
  it('is a no-op when MODE !== test (production guard)', async () => {
    // Prime the module's status cache via a status probe (under MODE=test
    // which is Vitest default), then stub MODE=production and assert the
    // reset is inert (status probe is NOT re-fetched on next speakResponse).
    let statusCalls = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/api/avatars/tts/status')) {
        statusCalls += 1;
        return {
          ok: true,
          json: async () => ({ enabled: true, backend: 'browser' }),
        } as any;
      }
      throw new Error(`unexpected fetch to ${url}`);
    });
    (globalThis as any).fetch = fetchMock;
    _installSpeechStubs();

    const voiceMod = await import('../voice');
    // Prime cache (real reset under MODE=test).
    voiceMod._resetTtsStatusForTests();
    voiceMod.speakResponse('prime');
    await _flush();
    // AD-1291: release the arbiter before the second call, or 'second' would
    // queue and never probe -- which would make this pass even if the gated
    // reset had wrongly cleared the cache.
    await _endAll();
    const callsAfterPrime = statusCalls;
    expect(callsAfterPrime).toBeGreaterThan(0);

    // Stub MODE=production; reset must be a no-op.
    vi.stubEnv('MODE', 'production');
    voiceMod._resetTtsStatusForTests();
    voiceMod.speakResponse('second');
    await _flush();

    // No new status probe -- cache survived the gated no-op reset.
    expect(statusCalls).toBe(callsAfterPrime);
  });

  it('resets module state when MODE === test (happy path)', async () => {
    let statusCalls = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/api/avatars/tts/status')) {
        statusCalls += 1;
        return {
          ok: true,
          json: async () => ({ enabled: true, backend: 'browser' }),
        } as any;
      }
      throw new Error(`unexpected fetch to ${url}`);
    });
    (globalThis as any).fetch = fetchMock;
    _installSpeechStubs();

    const voiceMod = await import('../voice');
    vi.stubEnv('MODE', 'test');
    voiceMod._resetTtsStatusForTests();
    voiceMod.speakResponse('first');
    await _flush();
    // AD-1291: see the note on `_endAll` -- 'second' cannot re-probe while
    // 'first' still owns the device.
    await _endAll();
    const callsAfterFirst = statusCalls;
    expect(callsAfterFirst).toBeGreaterThan(0);

    // Reset under MODE=test must clear cache so next call re-probes.
    voiceMod._resetTtsStatusForTests();
    voiceMod.speakResponse('second');
    await _flush();

    expect(statusCalls).toBeGreaterThan(callsAfterFirst);
  });
});
