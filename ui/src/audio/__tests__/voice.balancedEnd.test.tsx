/** BF-655 — balanced start/end from the TTS producer (voice.ts).
 *
 *  Every 'start' MUST be followed by exactly one terminal 'end' with the same
 *  agent_id on every path: server 'ended', server supersede/pause, browser
 *  onend, and browser cancel/interrupt (onerror). A missed 'end' strands the
 *  three onSpeechEvent consumers (modulation icon, avatar head-bob, PTT gate)
 *  forever — this is the stuck-"speaking" defect.
 *
 *  Reuses the voice.pipelining.test.tsx harness: a FakeAudio whose play()/
 *  pause() DISPATCH 'play'/'pause' and an .end() hook dispatching 'ended',
 *  plus a FakeUtterance exposing onstart/onend/onerror. Events are captured
 *  via onSpeechEvent.
 *
 *  The watchdog block (#7, #8) mirrors the ProfileChatTab BF-300 gate arm/clear
 *  logic (ProfileChatTab can't mount cheaply here) plus a ?raw source assertion
 *  that pins the production effect wiring.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import profileChatSource from '../../components/profile/ProfileChatTab.tsx?raw';

interface CapturedEvent {
  type: string;
  agent_id?: string;
  source?: string;
}

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
  /** Test hook: simulate playback finishing so a terminal 'end' fires. */
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

/** Piper-backed fetch mock. ``posted`` (when passed) records the POSTed text;
 *  ``pipelining`` sets the status flag. Returns a valid 64-char attachment id. */
function _makePiperFetch(opts?: { pipelining?: boolean; posted?: string[] }) {
  const pipelining = opts?.pipelining ?? false;
  const posted = opts?.posted;
  let nth = 0;
  return vi.fn(async (url: string, init?: { body?: string }) => {
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
      if (posted) {
        const body = JSON.parse(init?.body ?? '{}');
        posted.push(body.text);
      }
      nth += 1;
      const sha = String.fromCharCode(97 + nth).repeat(64); // 64-char id
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

const _unsubs: Array<() => void> = [];

/** Subscribe to onSpeechEvent, capturing {type, agent_id, source} per fire. */
async function _capture(): Promise<CapturedEvent[]> {
  const events: CapturedEvent[] = [];
  const voiceMod = await import('../voice');
  const unsub = voiceMod.onSpeechEvent((e) => {
    events.push({ type: e.type, agent_id: e.agent_id, source: e.source });
  });
  _unsubs.push(unsub);
  return events;
}

beforeEach(() => { _installGlobals(); });
afterEach(() => {
  while (_unsubs.length) { try { _unsubs.pop()!(); } catch { /* ignore */ } }
  vi.restoreAllMocks();
  cleanup();
});

describe('BF-655 producer — server path fires balanced end', () => {
  it('server_ended_fires_exactly_one_start_and_one_end', async () => {
    (globalThis as any).fetch = _makePiperFetch();
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();
    const events = await _capture();

    voiceMod.speakResponse('hello', undefined, 'ezri');
    await _flush();
    // play() dispatched 'play' -> start.
    expect(events.map((e) => e.type)).toEqual(['start']);

    createdAudios[0].end(); // 'ended' -> end
    await _flush();

    expect(events.map((e) => e.type)).toEqual(['start', 'end']);
    expect(events[0]).toMatchObject({ type: 'start', agent_id: 'ezri', source: 'server' });
    expect(events[1]).toMatchObject({ type: 'end', agent_id: 'ezri', source: 'server' });
  });

  it('supersede_pause_fires_end_for_the_older_utterance', async () => {
    // HEADLINE / stuck-latch regression: a newer speakResponse pauses the prior
    // audio; the OLDER utterance must emit its terminal 'end' (same agent_id)
    // BEFORE the newer utterance's 'start', so the latch clears. Pre-fix: no
    // such 'end' -> icon/head/PTT stranded forever.
    //
    // AD-1291: the trigger changed, the invariant did not. This used to call
    // `speakResponse` twice back to back and assert the second had already
    // superseded the first SYNCHRONOUSLY -- which pinned the BF-858 defect
    // (two producers on one device) as the contract. The second call now
    // queues, so supersession is only reachable when the arbiter hands the
    // device over with the previous <audio> still live: the GUARD 2 path,
    // where an utterance's 'end' never arrived. The assertion below is
    // unchanged -- ['start', 'end', 'start'], the older 'end' strictly before
    // the newer 'start' -- because that ordering is the actual BF-655 rule.
    vi.useFakeTimers();
    (globalThis as any).fetch = _makePiperFetch();
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();
    const events = await _capture();

    voiceMod.speakResponse('first', undefined, 'ezri');
    await _flush();
    expect(events.map((e) => e.type)).toEqual(['start']); // first start

    // Queued behind 'first', which still owns the device: nothing yet.
    voiceMod.speakResponse('second', undefined, 'ezri');
    await _flush();
    expect(events.map((e) => e.type)).toEqual(['start']);

    // 'first' never reports that it ended. GUARD 2 releases the queue, and
    // dispatching 'second' pauses the still-playing first audio -> its
    // terminal 'end' fires, and must land BEFORE the second's 'start'.
    await vi.advanceTimersByTimeAsync(voiceMod.SPEECH_JOIN_TIMEOUT_MS + 1);
    await _flush();

    expect(events.map((e) => e.type)).toEqual(['start', 'end', 'start']);
    expect(events[1]).toMatchObject({ type: 'end', agent_id: 'ezri', source: 'server' });
    vi.useRealTimers();
  });

  it('no_double_end_when_ended_then_pause', async () => {
    (globalThis as any).fetch = _makePiperFetch();
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();
    const events = await _capture();

    voiceMod.speakResponse('solo', undefined, 'ezri');
    await _flush();

    createdAudios[0].end();   // 'ended' -> end (settles)
    createdAudios[0].pause(); // 'pause' after settle -> no-op (guard)
    await _flush();

    expect(events.map((e) => e.type)).toEqual(['start', 'end']);
    expect(events.filter((e) => e.type === 'end').length).toBe(1);
  });
});

describe('BF-655 producer — browser fallback fires a single balanced end', () => {
  it('browser_cancel_fires_end_via_onerror', async () => {
    // Force the synchronous browser fallback (fetch unavailable).
    (globalThis as any).fetch = undefined;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();
    const events = await _capture();

    voiceMod.speakResponse('hi', undefined, 'ezri');
    expect(createdUtterances.length).toBe(1);
    const u = createdUtterances[0];

    u.onstart?.();  // -> start
    u.onerror?.();  // interrupt/cancel -> end (guard)

    expect(events.map((e) => e.type)).toEqual(['start', 'end']);
    expect(events[1]).toMatchObject({ type: 'end', agent_id: 'ezri', source: 'browser' });

    // The other terminal is now a no-op (single-settle guard).
    u.onend?.();
    expect(events.filter((e) => e.type === 'end').length).toBe(1);
  });

  it('browser_onend_still_fires_single_end', async () => {
    (globalThis as any).fetch = undefined;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();
    const events = await _capture();

    voiceMod.speakResponse('hi', undefined, 'ezri');
    const u = createdUtterances[0];

    u.onstart?.(); // -> start
    u.onend?.();   // normal end (guard does not suppress the happy path)

    expect(events.map((e) => e.type)).toEqual(['start', 'end']);
    expect(events[1]).toMatchObject({ type: 'end', agent_id: 'ezri', source: 'browser' });

    // A late onerror after onend is a no-op.
    u.onerror?.();
    expect(events.filter((e) => e.type === 'end').length).toBe(1);
  });
});

describe('BF-655 producer — AD-1071 flag-OFF single-POST is byte-identical', () => {
  it('pipelining_still_one_post_when_flag_off', async () => {
    // Edit A must not disturb the AD-1071 queue: flag OFF + multi-sentence ->
    // exactly ONE POST of the full text (one audio element).
    const posted: string[] = [];
    (globalThis as any).fetch = _makePiperFetch({ pipelining: false, posted });
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('One sentence. Two sentence. Three sentence.');
    await _flush();

    expect(posted).toEqual(['One sentence. Two sentence. Three sentence.']);
    expect(createdAudios.length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// PTT watchdog (BF-655 defense-in-depth). ProfileChatTab can't mount cheaply
// here, so mirror the arm/clear/cleanup logic (like ProfileChatTab.ad1062's
// mirror) and pin the production wiring with a ?raw source assertion.
// ---------------------------------------------------------------------------

const PTT_TTS_WATCHDOG_MS = 45000;

/** Faithful mirror of the ProfileChatTab BF-300 gate + BF-655 watchdog.
 *  ``selfHeals`` counts watchdog firings so tests can prove the timer was
 *  cleared on re-arm / 'end' / cleanup. If production changes, update this
 *  mirror — the source-level suite below fails loud if the wiring disappears. */
function makeWatchdogGate() {
  const ttsActiveRef = { current: false };
  let ttsActive = false;
  const setTtsActive = (v: boolean) => { ttsActive = v; };
  const ttsWatchdogRef: { current: ReturnType<typeof setTimeout> | null } = { current: null };
  let selfHeals = 0;

  const onEvent = (type: 'start' | 'end') => {
    if (type === 'start') {
      ttsActiveRef.current = true;
      setTtsActive(true);
      if (ttsWatchdogRef.current !== null) clearTimeout(ttsWatchdogRef.current);
      ttsWatchdogRef.current = setTimeout(() => {
        ttsWatchdogRef.current = null;
        ttsActiveRef.current = false;
        setTtsActive(false);
        selfHeals += 1;
      }, PTT_TTS_WATCHDOG_MS);
    } else {
      ttsActiveRef.current = false;
      setTtsActive(false);
      if (ttsWatchdogRef.current !== null) {
        clearTimeout(ttsWatchdogRef.current);
        ttsWatchdogRef.current = null;
      }
    }
  };
  const cleanup = () => {
    if (ttsWatchdogRef.current !== null) {
      clearTimeout(ttsWatchdogRef.current);
      ttsWatchdogRef.current = null;
    }
  };
  return {
    onEvent, cleanup, ttsActiveRef,
    get ttsActive() { return ttsActive; },
    get selfHeals() { return selfHeals; },
  };
}

describe('BF-655 PTT watchdog (mirror)', () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it('ptt_watchdog_clears_gate_after_ceiling_with_no_end', async () => {
    const g = makeWatchdogGate();
    g.onEvent('start');
    expect(g.ttsActiveRef.current).toBe(true);
    expect(g.ttsActive).toBe(true);

    // No 'end' ever arrives — advance past the ceiling.
    vi.advanceTimersByTime(PTT_TTS_WATCHDOG_MS);

    expect(g.ttsActiveRef.current).toBe(false);
    expect(g.ttsActive).toBe(false);
    expect(g.selfHeals).toBe(1);
    g.cleanup();
  });

  it('ptt_watchdog_reset_on_fresh_start_and_cleared_on_end', async () => {
    const g = makeWatchdogGate();
    g.onEvent('start');                       // timer A armed (fires at +45s)
    vi.advanceTimersByTime(20000);            // < ceiling
    g.onEvent('start');                       // re-arm: clear A, arm B (+45s)
    vi.advanceTimersByTime(30000);            // t=50s: A would have fired at 45s

    // Reset-on-fresh-start: A was cleared, so the gate is still active and the
    // watchdog has NOT self-healed.
    expect(g.ttsActiveRef.current).toBe(true);
    expect(g.selfHeals).toBe(0);

    g.onEvent('end');                         // normal end clears gate + timer B
    expect(g.ttsActiveRef.current).toBe(false);
    expect(g.ttsActive).toBe(false);

    // No stale timer fires afterwards (B was cleared on 'end').
    vi.advanceTimersByTime(60000);
    expect(g.selfHeals).toBe(0);
    expect(g.ttsActiveRef.current).toBe(false);
    g.cleanup();
  });
});

describe('BF-655 PTT watchdog (production wiring, source-level)', () => {
  it('defines the PTT_TTS_WATCHDOG_MS ceiling as a module const', () => {
    expect(profileChatSource).toMatch(/const PTT_TTS_WATCHDOG_MS = 45000/);
  });

  it('arms the watchdog on start and clears it on end and on cleanup', () => {
    expect(profileChatSource).toMatch(/ttsWatchdogRef/);
    // Armed via setTimeout(..., PTT_TTS_WATCHDOG_MS).
    expect(profileChatSource).toMatch(/setTimeout\([\s\S]*?PTT_TTS_WATCHDOG_MS\)/);
    // Cleared (on re-arm, on 'end', and on effect cleanup).
    expect(profileChatSource).toMatch(/clearTimeout\(ttsWatchdogRef\.current\)/);
  });
});
