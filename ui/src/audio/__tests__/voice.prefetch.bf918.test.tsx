/** BF-918 (#1626): AD-1071 pipelining prefetches the next sentence while one plays;
 *  a stop drops what was prefetched; deferred visemes reach the sentence playing;
 *  barge-in silences Piper. Real voice.ts, real queue, real lip-sync registry; only
 *  Audio, SpeechSynthesis, fetch and (in one case) performance are fakes. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';

let createdUtterances: FakeUtterance[] = [];
let speakCalls: unknown[] = [];
let createdAudios: FakeAudio[] = [];

class FakeUtterance {
  text: string;
  rate = 1; pitch = 1; volume = 1;
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(text: string) {
    this.text = text;
    createdUtterances.push(this);
  }
}

/** Review round 1: how the fake's play() settles. 'resolve': at once, as when
 *  playback starts. 'hold': pending, as a real element's is while its WAV still
 *  loads; a pause() meanwhile fires 'pause' and then rejects it with AbortError
 *  (the HTML pause steps; the reviewer measured this order in Chromium).
 *  'blocked': refused by the autoplay policy (NotAllowedError), and no 'play'. */
let playMode: 'resolve' | 'hold' | 'blocked' = 'resolve';

class FakeAudio {
  src: string;
  volume = 1;
  playbackRate = 1;
  preservesPitch = true;
  played = false;
  discarded = false;
  private _listeners: Record<string, Array<() => void>> = {};
  private _rejectPlay: ((err: unknown) => void) | null = null;
  pause = vi.fn(() => {
    this.emit('pause');
    const reject = this._rejectPlay;
    this._rejectPlay = null;
    if (reject !== null) reject(new DOMException('The play() request was interrupted by a call to pause().', 'AbortError'));
  });
  play = vi.fn((): Promise<void> => {
    if (playMode === 'blocked') {
      return Promise.reject(new DOMException('play() failed because the user did not interact with the document first.', 'NotAllowedError'));
    }
    this.played = true;
    this.emit('play');
    if (playMode === 'resolve') return Promise.resolve();
    return new Promise<void>((_resolve, reject) => { this._rejectPlay = reject; });
  });
  removeAttribute = vi.fn(() => { this.discarded = true; });
  load = vi.fn();
  constructor(src: string) {
    this.src = src;
    createdAudios.push(this);
  }
  addEventListener(ev: string, fn: () => void): void {
    (this._listeners[ev] ||= []).push(fn);
  }
  emit(ev: string): void {
    for (const fn of (this._listeners[ev] || [])) fn();
  }
  end(): void { this.emit('ended'); }
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
    (globalThis as any).localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  }
}

async function _flush(): Promise<void> {
  for (let i = 0; i < 40; i++) await Promise.resolve();
}

interface Plan {
  pipelining: boolean;
  backend?: string;
  holdStatus?: boolean;
  failTts?: number[];
  deferVisemes?: boolean;
  inlineVisemes?: unknown[];
  holdTts?: number[];
  holdLipsync?: boolean;
  framesFor?: (attachmentId: string) => unknown[];
}

function _makeFetch(plan: Plan) {
  const posted: string[] = [];
  const bodies: Array<Record<string, unknown>> = [];
  const lipsyncIds: string[] = [];
  const held: Array<() => void> = [];
  let nth = 0;
  const fetchMock = vi.fn(async (url: string, opts?: { body?: string }): Promise<any> => {
    if (url.endsWith('/api/avatars/tts/status')) {
      const status = { ok: true, json: async () => ({ enabled: true, backend: plan.backend ?? 'piper', sentence_pipelining_enabled: plan.pipelining }) };
      if (plan.holdStatus) { plan.holdStatus = false; return new Promise((resolve) => { held.push(() => resolve(status)); }); }
      return status;
    }
    if (url === '/api/avatars/tts') {
      const body = JSON.parse(opts?.body ?? '{}');
      bodies.push(body);
      posted.push(body.text);
      nth += 1;
      const sha = String.fromCharCode(97 + nth).repeat(64);
      const response = {
        ok: true,
        json: async () => ({
          backend: 'piper',
          audio_attachment_id: sha,
          mime: 'audio/wav',
          visemes: plan.inlineVisemes ?? [],
          visemes_deferred: plan.deferVisemes === true,
          duration_ms: 0,
        }),
      };
      const answer = plan.failTts?.includes(nth) ? { ok: false, json: async () => ({}) } : response;
      if (plan.holdTts?.includes(nth)) return new Promise((resolve) => { held.push(() => resolve(answer)); });
      return answer;
    }
    if (url === '/api/avatars/lipsync') {
      const id = String(JSON.parse(opts?.body ?? '{}').attachment_id);
      lipsyncIds.push(id);
      const response = { ok: true, json: async () => ({ backend: 'rhubarb', frames: plan.framesFor ? plan.framesFor(id) : [] }) };
      if (plan.holdLipsync) return new Promise((resolve) => { held.push(() => resolve(response)); });
      return response;
    }
    throw new Error(`unexpected fetch to ${url}`);
  });
  return {
    fetchMock, posted, bodies, lipsyncIds,
    release: (): void => { const next = held.shift(); if (next) next(); },
  };
}

const frame = (viseme: string) => [{ time: 0, duration: 0.1, viseme }];

async function _voice() {
  const voiceMod = await import('../voice');
  voiceMod._resetTtsStatusForTests();
  return voiceMod;
}

beforeEach(() => { _installGlobals(); playMode = 'resolve'; });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); cleanup(); });

describe('BF-918 prefetch (AD-1071 pipelining on)', () => {
  it('P1 synthesizes the next sentence while one plays, and plays them in order', async () => {
    const f = _makeFetch({ pipelining: true });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();

    voiceMod.speakResponse('One. Two. Three.');
    await _flush();
    expect(f.posted).toEqual(['One.', 'Two.']);
    expect(createdAudios.map((a) => a.played)).toEqual([true, false]);
    expect(f.bodies.every((b) => b.defer_visemes === true)).toBe(true);

    createdAudios[0].end();
    await _flush();
    expect(f.posted).toEqual(['One.', 'Two.', 'Three.']);
    expect(createdAudios.map((a) => a.played)).toEqual([true, true, false]);

    createdAudios[1].end();
    await _flush();
    expect(createdAudios.map((a) => a.played)).toEqual([true, true, true]);
    createdAudios[2].end();
    await _flush();
    expect(f.posted.length).toBe(3);
  });

  it('P2 a stop during sentence one silences it and drops the prefetched sentence two, which fires no start', async () => {
    const f = _makeFetch({ pipelining: true });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const events: string[] = [];
    const off = voiceMod.onSpeechEvent((e) => { events.push(`${e.type}:${e.utterance?.text ?? ''}`); });
    try {
      voiceMod.speakResponse('One. Two. Three.');
      await _flush();
      const audiosWhileOnePlayed = createdAudios.length;

      voiceMod.stopSpeaking();
      await _flush();

      // Review round 1: the cancellation first, so a tree without it fails here,
      // not at the prefetch premise below.
      expect(createdAudios[0].pause).toHaveBeenCalled();
      expect(events.filter((e) => e.startsWith('start'))).toEqual(['start:One.']);
      expect(events.filter((e) => e.startsWith('end'))).toEqual(['end:One.']);
      expect(events.filter((e) => e.startsWith('dropped'))).toEqual([]); // its audio started: it ends, it is not dropped
      // The prefetch premise: sentence two had been prepared while one played.
      expect(audiosWhileOnePlayed).toBe(2);
      expect(f.posted).toEqual(['One.', 'Two.']);
      expect(createdAudios[1].played).toBe(false);
      expect(createdAudios[1].discarded).toBe(true);
    } finally {
      off();
    }
  });

  it('P3 a sentence still being synthesized when the reply stops is never played', async () => {
    const f = _makeFetch({ pipelining: true, holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const starts: string[] = [];
    const off = voiceMod.onSpeechEvent((e) => { if (e.type === 'start') starts.push(e.utterance?.text ?? ''); });
    try {
      voiceMod.speakResponse('One. Two. Three.');
      await _flush();
      const postedWhileOnePlayed = [...f.posted];
      const audiosWhileOnePlayed = createdAudios.length; // Two's response has not arrived

      voiceMod.stopSpeaking();
      await _flush();
      f.release();
      await _flush();

      // Review round 1: the cancellation first (see P2).
      expect(createdAudios[0].pause).toHaveBeenCalled();
      expect(starts).toEqual(['One.']);
      expect(createdAudios.length).toBe(2); // made when its response arrived...
      expect(createdAudios[1].played).toBe(false); // ...and never played
      expect(createdAudios[1].discarded).toBe(true);
      // The prefetch premise: Two was requested while One played, and was in flight.
      expect(postedWhileOnePlayed).toEqual(['One.', 'Two.']);
      expect(audiosWhileOnePlayed).toBe(1);
    } finally {
      off();
    }
  });
});

describe('BF-918 deferred visemes', () => {
  it('P4 fetches them for the stored audio and injects them while it plays; late ones are dropped', async () => {
    const f = _makeFetch({
      pipelining: false, deferVisemes: true, holdLipsync: true,
      framesFor: (id) => frame(id[0] === 'b' ? 'aa' : 'oh'),
    });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const { useLipSyncCapture } = await import('../useLipSyncCapture');
    const { result } = renderHook(() => useLipSyncCapture({ enabled: true, agentId: 'agent-7' }));

    voiceMod.speakResponse('hi', undefined, 'agent-7');
    await act(async () => { await _flush(); });
    expect(f.lipsyncIds).toEqual(['b'.repeat(64)]);
    expect(result.current.frames).toEqual([]); // the heuristic schedule animates meanwhile
    await act(async () => { f.release(); await _flush(); });
    expect(result.current.frames).toEqual(frame('aa'));

    createdAudios[0].end();
    await act(async () => { await _flush(); });
    voiceMod.speakResponse('bye', undefined, 'agent-7');
    await act(async () => { await _flush(); });
    expect(f.lipsyncIds.length).toBe(2);
    createdAudios[1].end(); // its audio ends before its frames arrive
    await act(async () => { f.release(); await _flush(); });
    expect(result.current.frames).toEqual(frame('aa')); // 'oh' was dropped
  });

  it('P5 an older server that sends visemes inline still has them injected, with no lipsync request', async () => {
    const f = _makeFetch({ pipelining: false, inlineVisemes: frame('ee') });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const { useLipSyncCapture } = await import('../useLipSyncCapture');
    const { result } = renderHook(() => useLipSyncCapture({ enabled: true, agentId: 'agent-7' }));

    voiceMod.speakResponse('hi', undefined, 'agent-7');
    await act(async () => { await _flush(); });

    expect(result.current.frames).toEqual(frame('ee'));
    expect(f.lipsyncIds).toEqual([]);
  });

  it('P6 pipelined: each sentence gets its own deferred visemes, the prefetched one at its own play', async () => {
    const f = _makeFetch({
      pipelining: true, deferVisemes: true,
      framesFor: (id) => frame(id[0] === 'b' ? 'aa' : 'ih'),
    });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const { useLipSyncCapture } = await import('../useLipSyncCapture');
    const { result } = renderHook(() => useLipSyncCapture({ enabled: true, agentId: 'agent-7' }));

    voiceMod.speakResponse('One. Two.', undefined, 'agent-7');
    await act(async () => { await _flush(); });
    expect(result.current.frames).toEqual(frame('aa'));
    expect(f.lipsyncIds).toEqual(['b'.repeat(64), 'c'.repeat(64)]); // the second fetched while the first plays
    expect(createdAudios[1].played).toBe(false);

    await act(async () => { createdAudios[0].end(); await _flush(); });

    expect(createdAudios[1].played).toBe(true);
    expect(result.current.frames).toEqual(frame('ih'));
  });
});

describe('BF-918 stop and timing', () => {
  it('P7 stopSpeaking silences server audio on the single-call path and fires its one end', async () => {
    const f = _makeFetch({ pipelining: false });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const ends: string[] = [];
    const off = voiceMod.onSpeechEvent((e) => { if (e.type === 'end') ends.push(e.utterance?.text ?? ''); });
    try {
      voiceMod.speakResponse('One. Two.');
      await _flush();
      voiceMod.stopSpeaking();
      await _flush();
      expect(createdAudios[0].pause).toHaveBeenCalled();
      expect(ends).toEqual(['One. Two.']);
    } finally {
      off();
    }
  });

  it('P8 records first audio and the gap between sentences as User Timing measures', async () => {
    const measure = vi.fn();
    vi.stubGlobal('performance', {
      now: () => Date.now(),
      measure,
      getEntriesByName: () => [],
      clearMeasures: vi.fn(),
    });
    const f = _makeFetch({ pipelining: true });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();

    voiceMod.speakResponse('One. Two.');
    await _flush();
    createdAudios[0].emit('playing');
    expect(measure.mock.calls.map((c) => c[0])).toEqual(['bf918:first-audio']);
    createdAudios[0].end();
    await _flush();
    createdAudios[1].emit('playing');
    expect(measure.mock.calls.map((c) => c[0])).toEqual(['bf918:first-audio', 'bf918:sentence-gap']);
  });
});

describe('BF-918 review round 1: a stop before audio, and a stop of a pending play (D7a)', () => {
  const spoken = (): string[] => speakCalls.map((u) => (u as FakeUtterance).text);

  async function _record() {
    const voiceMod = await import('../voice');
    const events: string[] = [];
    const drops: Array<{ id?: number; reason?: string }> = [];
    const off = voiceMod.onSpeechEvent((e) => {
      events.push(`${e.type}:${e.source ?? ''}:${e.utterance?.text ?? ''}`);
      if (e.type === 'dropped') drops.push({ id: e.utterance_id, reason: e.reason });
    });
    return { events, drops, off };
  }

  it('P9 pipelined: a stop while sentence one synthesizes plays nothing and frees the arbiter for the next reply (C1)', async () => {
    const f = _makeFetch({ pipelining: true, holdTts: [1] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _record();
    try {
      const stopped = voiceMod.speakResponse('One. Two.');
      await _flush();
      expect(f.posted).toEqual(['One.']); // sentence one is synthesizing; nothing plays yet
      expect(createdAudios.length).toBe(0);

      voiceMod.stopSpeaking();
      await _flush();
      f.release(); // its synthesis answers after the stop
      await _flush();
      voiceMod.speakResponse('Next.');
      await _flush();

      // C1: the next reply is dispatched now, not after SPEECH_JOIN_TIMEOUT_MS.
      expect(f.posted).toEqual(['One.', 'Next.']);
      expect(createdAudios.map((a) => a.played)).toEqual([false, true]);
      expect(createdAudios[0].discarded).toBe(true);
      // No 'start' for the stopped reply, so no 'end': one 'dropped' ends it.
      expect(r.events).toEqual(['dropped::One. Two.', 'start:server:Next.']);
      expect(r.drops).toEqual([{ id: stopped, reason: 'cancelled-before-audio' }]);
    } finally {
      r.off();
    }
  });

  it('P10 single call: a reply whose synthesis answers after a stop is never played, and the next reply is dispatched (C3)', async () => {
    const f = _makeFetch({ pipelining: false, holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _record();
    try {
      // Control: an answer that arrives with no stop plays.
      voiceMod.speakResponse('Control.');
      await _flush();
      expect(createdAudios[0].played).toBe(true);
      createdAudios[0].end();
      await _flush();

      const stopped = voiceMod.speakResponse('Only one.');
      await _flush();
      expect(f.posted).toEqual(['Control.', 'Only one.']);
      voiceMod.stopSpeaking();
      await _flush();
      f.release();
      await _flush();

      expect(createdAudios.length).toBe(2);
      expect(createdAudios[1].played).toBe(false); // C3: nothing starts after the stop
      expect(createdAudios[1].discarded).toBe(true);
      voiceMod.speakResponse('Next.');
      await _flush();
      expect(f.posted).toEqual(['Control.', 'Only one.', 'Next.']);
      expect(r.events.filter((e) => !e.startsWith('end'))).toEqual(['start:server:Control.', 'dropped::Only one.', 'start:server:Next.']);
      expect(r.drops).toEqual([{ id: stopped, reason: 'cancelled-before-audio' }]);
    } finally {
      r.off();
    }
  });

  it('P11 a synthesis that fails after a stop is not spoken by the browser either; unstopped, it is (C3)', async () => {
    const f = _makeFetch({ pipelining: false, failTts: [1, 2], holdTts: [2] });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _record();
    try {
      // Control: an unstopped reply whose synthesis fails is spoken by the browser.
      voiceMod.speakResponse('Control.');
      await _flush();
      expect(spoken()).toEqual(['Control.']);
      (speakCalls[0] as FakeUtterance).onend?.();
      await _flush();

      const stopped = voiceMod.speakResponse('Only one.');
      await _flush();
      expect(f.posted).toEqual(['Control.', 'Only one.']);
      voiceMod.stopSpeaking();
      await _flush();
      f.release();
      await _flush();

      expect(spoken()).toEqual(['Control.']); // C3: no fallback after the stop
      expect(createdAudios.length).toBe(0);
      expect(r.drops).toEqual([{ id: stopped, reason: 'cancelled-before-audio' }]);
    } finally {
      r.off();
    }
  });

  it('P12 a stop during the first status probe speaks nothing; the next reply is spoken (C3)', async () => {
    const f = _makeFetch({ pipelining: false, backend: 'browser', holdStatus: true });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _record();
    try {
      const stopped = voiceMod.speakResponse('Probe.');
      await _flush();
      expect(spoken()).toEqual([]); // the probe has not answered
      voiceMod.stopSpeaking();
      f.release();
      await _flush();

      expect(spoken()).toEqual([]);
      expect(r.drops).toEqual([{ id: stopped, reason: 'cancelled-before-audio' }]);
      // Control: the next reply, with the browser backend now cached, is spoken, with no POST.
      voiceMod.speakResponse('Next.');
      await _flush();
      expect(spoken()).toEqual(['Next.']);
      expect(f.posted).toEqual([]);
    } finally {
      r.off();
    }
  });

  it('P13 a stop while play() is still pending ends that utterance once and speaks nothing in its place (C2)', async () => {
    const f = _makeFetch({ pipelining: false });
    (globalThis as any).fetch = f.fetchMock;
    const voiceMod = await _voice();
    const r = await _record();
    try {
      // Control: a play() the autoplay policy refuses, with no stop, is spoken by the browser.
      playMode = 'blocked';
      voiceMod.speakResponse('Refused.');
      await _flush();
      expect(spoken()).toEqual(['Refused.']);
      (speakCalls[0] as FakeUtterance).onend?.();
      await _flush();
      r.events.length = 0;

      // The WAV is still loading, so play() is pending when the stop pauses it.
      playMode = 'hold';
      voiceMod.speakResponse('Pending.');
      await _flush();
      expect(createdAudios[1].played).toBe(true); // its 'play' fired: the server 'start' is out
      voiceMod.stopSpeaking();
      await _flush();
      expect(createdAudios[1].pause).toHaveBeenCalled();
      expect(spoken()).toEqual(['Refused.']); // C2: nothing speaks in its place

      // Control: a play() that had resolved (playback started) when the stop came.
      playMode = 'resolve';
      voiceMod.speakResponse('Playing.');
      await _flush();
      voiceMod.stopSpeaking();
      await _flush();
      expect(spoken()).toEqual(['Refused.']);
      // Exactly one terminal 'end' for each 'start', and nothing dropped.
      expect(r.events).toEqual(['start:server:Pending.', 'end:server:Pending.', 'start:server:Playing.', 'end:server:Playing.']);
    } finally {
      r.off();
    }
  });
});
