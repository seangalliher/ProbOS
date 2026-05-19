/**
 * AD-721b-3 — Whisper loader tests.
 *
 * BF-287 posture: fetch + document.createElement stubbed at the global
 * boundary; module-scoped factory cache reset between tests.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
  loadWhisperModel,
  _injectWhisperGlue,
  _fetchArtifact,
  _resetWhisperLoader,
} from '../whisperLoader';

function stubFetch(map: Record<string, { ok: boolean; status?: number; bytes?: Uint8Array }>) {
  (globalThis as any).fetch = vi.fn(async (url: string) => {
    const entry = map[url] ?? { ok: false, status: 404 };
    return {
      ok: entry.ok,
      status: entry.status ?? (entry.ok ? 200 : 404),
      arrayBuffer: async () =>
        entry.bytes ? entry.bytes.buffer.slice(0) : new ArrayBuffer(0),
    } as Response;
  });
}

function stubScriptInjection(factory: unknown | null) {
  // Replace document.createElement('script') so onload fires synchronously
  // with the factory registered on window.Module.
  const origCreate = document.createElement.bind(document);
  vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
    if (tag !== 'script') return origCreate(tag);
    const fake: any = {
      tagName: 'SCRIPT',
      set src(_v: string) {
        // Schedule load/error in a microtask so the listener attaches first.
        queueMicrotask(() => {
          if (factory) {
            (window as any).Module = factory;
            fake.onload?.();
          } else {
            fake.onerror?.(new Event('error'));
          }
        });
      },
      onload: null as null | (() => void),
      onerror: null as null | ((e: Event) => void),
    };
    return fake as HTMLScriptElement;
  });
  vi.spyOn(document.head, 'appendChild').mockImplementation((node) => node);
}

beforeEach(() => {
  _resetWhisperLoader();
  (window as any).Module = undefined;
  (window as any).whisper_factory = undefined;
});

afterEach(() => {
  vi.restoreAllMocks();
  _resetWhisperLoader();
});

describe('loadWhisperModel', () => {
  it('returns null when glue script 404s', async () => {
    stubFetch({
      '/data/whisper/whisper.js': { ok: false, status: 404 },
    });
    const handle = await loadWhisperModel();
    expect(handle).toBeNull();
  });

  it('returns null when model bin 404s', async () => {
    stubFetch({
      '/data/whisper/whisper.js': { ok: true, bytes: new Uint8Array([1, 2]) },
      '/data/whisper/whisper.wasm': { ok: true, bytes: new Uint8Array([3, 4]) },
      '/data/whisper/ggml-tiny.en.bin': { ok: false, status: 404 },
    });
    const fakeFactory = vi.fn(async () => ({
      transcribeBuffer: async () => 'should not reach',
    }));
    stubScriptInjection(fakeFactory);
    const handle = await loadWhisperModel();
    expect(handle).toBeNull();
  });

  it('returns a handle with transcribeBuffer when all artifacts load', async () => {
    stubFetch({
      '/data/whisper/whisper.js': { ok: true, bytes: new Uint8Array([1]) },
      '/data/whisper/whisper.wasm': { ok: true, bytes: new Uint8Array([2]) },
      '/data/whisper/ggml-tiny.en.bin': { ok: true, bytes: new Uint8Array([3]) },
    });
    const transcribeBuffer = vi.fn(async (_buf: Float32Array, _sr: number) => 'hello');
    const fakeFactory = vi.fn(async () => ({ transcribeBuffer }));
    stubScriptInjection(fakeFactory);
    const handle = await loadWhisperModel();
    expect(handle).not.toBeNull();
    expect(typeof handle!.transcribeBuffer).toBe('function');
    const text = await handle!.transcribeBuffer(new Float32Array([0, 0, 0]), 16000);
    expect(text).toBe('hello');
  });
});

// _fetchArtifact is exercised indirectly above; expose a direct sanity
// check so refactors that change the helper's contract surface fast.
describe('_fetchArtifact', () => {
  it('returns null on 404', async () => {
    stubFetch({});
    expect(await _fetchArtifact('/data/whisper/whisper.wasm')).toBeNull();
  });
});

describe('_injectWhisperGlue', () => {
  it('returns null when glue probe fails', async () => {
    stubFetch({});
    expect(await _injectWhisperGlue()).toBeNull();
  });
});
