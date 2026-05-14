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
    (globalThis as any).SpeechSynthesisUtterance = class {
      text: string;
      constructor(t: string) { this.text = t; }
    };
    (globalThis as any).speechSynthesis = {
      cancel: vi.fn(),
      speak: vi.fn(),
      getVoices: () => [],
      addEventListener: vi.fn(),
    };

    const voiceMod = await import('../voice');
    // Prime cache (real reset under MODE=test).
    voiceMod._resetTtsStatusForTests();
    voiceMod.speakResponse('prime');
    await _flush();
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
    (globalThis as any).SpeechSynthesisUtterance = class {
      text: string;
      constructor(t: string) { this.text = t; }
    };
    (globalThis as any).speechSynthesis = {
      cancel: vi.fn(),
      speak: vi.fn(),
      getVoices: () => [],
      addEventListener: vi.fn(),
    };

    const voiceMod = await import('../voice');
    vi.stubEnv('MODE', 'test');
    voiceMod._resetTtsStatusForTests();
    voiceMod.speakResponse('first');
    await _flush();
    const callsAfterFirst = statusCalls;
    expect(callsAfterFirst).toBeGreaterThan(0);

    // Reset under MODE=test must clear cache so next call re-probes.
    voiceMod._resetTtsStatusForTests();
    voiceMod.speakResponse('second');
    await _flush();

    expect(statusCalls).toBeGreaterThan(callsAfterFirst);
  });
});
