/** AD-1291 (BF-858) — the speech arbiter owns the audio device.
 *
 *  Seven producers share one audio output and used to cancel one another on
 *  arrival. Worse than a truncation: `voice.ts` emits the terminal 'end'
 *  carrying the SUPERSEDED utterance's id (BF-767), and the BF-764 drain
 *  correlates on exactly that id -- so a foreign producer's cancel RESOLVED
 *  the drain and advanced it, launching the next utterance on top of the
 *  interloper. A mutual-cancellation cascade, with BF-764's own correlation
 *  guard as the propagation mechanism.
 *
 *  These exercise the REAL `voice.ts` against a fake browser engine, because
 *  the serialisation being tested lives in that module. A test that mocked it
 *  would be asserting the mock.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

interface CapturedEvent {
  type: string;
  agent_id?: string;
  utterance_id?: number;
  reason?: string;
}

let createdUtterances: FakeUtterance[] = [];
let speakCalls: FakeUtterance[] = [];

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

function _installGlobals(): void {
  createdUtterances = [];
  speakCalls = [];
  (globalThis as any).SpeechSynthesisUtterance = FakeUtterance;
  (globalThis as any).window = globalThis;
  // Force the synchronous browser fallback: no fetch means no server probe,
  // which keeps every dispatch observable in the same tick.
  (globalThis as any).fetch = undefined;
  (globalThis as any).speechSynthesis = {
    cancel: vi.fn(),
    speak: vi.fn((u: FakeUtterance) => { speakCalls.push(u); u.onstart?.(); }),
    getVoices: () => [],
    addEventListener: vi.fn(),
  };
  if (!(globalThis as any).localStorage) {
    (globalThis as any).localStorage = {
      getItem: () => null, setItem: () => {}, removeItem: () => {},
    };
  }
}

async function _flush(): Promise<void> {
  for (let i = 0; i < 12; i++) await Promise.resolve();
}

const _unsubs: Array<() => void> = [];

async function _capture(): Promise<CapturedEvent[]> {
  const events: CapturedEvent[] = [];
  const voiceMod = await import('../voice');
  const unsub = voiceMod.onSpeechEvent((e) => {
    events.push({
      type: e.type, agent_id: e.agent_id, utterance_id: e.utterance_id, reason: e.reason,
    });
  });
  _unsubs.push(unsub);
  return events;
}

/** What has actually reached the device, in dispatch order. */
function spokenTexts(): string[] {
  return speakCalls.map((u) => u.text);
}

/** End the utterance the device is currently playing. */
async function endSpoken(index: number): Promise<void> {
  speakCalls[index].onend?.();
  await _flush();
}

beforeEach(() => { _installGlobals(); });
afterEach(() => {
  while (_unsubs.length) { try { _unsubs.pop()!(); } catch { /* ignore */ } }
  vi.restoreAllMocks();
  vi.useRealTimers();
  cleanup();
});

describe('AD-1291 speech arbiter — one device, one owner', () => {
  it('dispatches narration FIFO, one at a time', async () => {
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('One.');
    voiceMod.speakResponse('Two.');
    await _flush();

    expect(spokenTexts()).toEqual(['One.']);
    await endSpoken(0);
    expect(spokenTexts()).toEqual(['One.', 'Two.']);
  });

  it('an interactive utterance pre-empts queued narration and says why', async () => {
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();
    const events = await _capture();

    voiceMod.speakResponse('Playing.');
    const droppedA = voiceMod.speakResponse('Queued A.');
    const droppedB = voiceMod.speakResponse('Queued B.');
    await _flush();
    expect(spokenTexts()).toEqual(['Playing.']);

    voiceMod.speakResponse('Live turn.', undefined, 'ezri', undefined, 'interactive');
    await _flush();

    const drops = events.filter((e) => e.type === 'dropped');
    expect(drops.map((d) => d.utterance_id).sort()).toEqual([droppedA, droppedB].sort());
    // No silent drops: every one carries a reason the Captain's tooling can read.
    expect(drops.every((d) => d.reason === 'preempted-by-interactive')).toBe(true);

    // The pre-empted narration must never reach the device, before or after.
    await endSpoken(0);
    expect(spokenTexts()).toEqual(['Playing.', 'Live turn.']);
  });

  it('does not drop the utterance already playing', async () => {
    // Only queued-but-unstarted entries are pre-emptible. Dropping a started
    // one would cut audio the Captain is already hearing.
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();
    const events = await _capture();

    const live = voiceMod.speakResponse('Already playing.');
    await _flush();
    voiceMod.speakResponse('Live turn.', undefined, 'ezri', undefined, 'interactive');
    await _flush();

    expect(events.filter((e) => e.type === 'dropped')).toEqual([]);
    expect(spokenTexts()).toEqual(['Already playing.']);
    await endSpoken(0);
    expect(spokenTexts()).toEqual(['Already playing.', 'Live turn.']);
    expect(live).toBeTypeOf('number');
  });

  it('queues an interactive utterance behind another interactive one', async () => {
    // Two live turns are both current; neither is redundant with visible text,
    // so nothing here may be dropped.
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();
    const events = await _capture();

    voiceMod.speakResponse('Turn one.', undefined, 'ezri', undefined, 'interactive');
    voiceMod.speakResponse('Turn two.', undefined, 'ezri', undefined, 'interactive');
    await _flush();

    expect(events.filter((e) => e.type === 'dropped')).toEqual([]);
    expect(spokenTexts()).toEqual(['Turn one.']);
    await endSpoken(0);
    expect(spokenTexts()).toEqual(['Turn one.', 'Turn two.']);
  });

  it('GUARD 1: an entry that can never emit an end does not wedge the queue', async () => {
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('First.');
    voiceMod.speakResponse('Second.');
    await _flush();
    expect(spokenTexts()).toEqual(['First.']);

    // The engine disappears between enqueue and dispatch, so nothing will ever
    // emit an 'end' for 'Second.'. Waiting on one would wedge every later
    // entry -- a silence defect, strictly worse than the overlap being fixed.
    delete (globalThis as any).speechSynthesis;
    delete (globalThis as any).Audio;
    speakCalls[0].onend?.();
    await _flush();

    // Queue drained rather than wedged: restoring the engine speaks again
    // immediately, with no timer having had to rescue it.
    _installGlobals();
    voiceMod._resetTtsStatusForTests();
    voiceMod.speakResponse('Third.');
    await _flush();
    expect(spokenTexts()).toEqual(['Third.']);
  });

  it('GUARD 2: a lost end releases on the bounded timeout, and not before', async () => {
    vi.useFakeTimers();
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('First.');
    voiceMod.speakResponse('Second.');
    await _flush();
    expect(spokenTexts()).toEqual(['First.']);

    // Both sides of the boundary: the ceiling must never fire on a legitimate
    // utterance, or it would reintroduce the very overlap it guards.
    await vi.advanceTimersByTimeAsync(voiceMod.SPEECH_JOIN_TIMEOUT_MS - 1);
    expect(spokenTexts()).toEqual(['First.']);

    await vi.advanceTimersByTimeAsync(2);
    expect(spokenTexts()).toEqual(['First.', 'Second.']);
  });

  it('returns a distinct id synchronously, at enqueue', async () => {
    // BF-764's drain and BF-290 both capture this return value and correlate
    // an 'end' against it BEFORE awaiting anything, so it cannot become async.
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    const first = voiceMod.speakResponse('One.');
    const second = voiceMod.speakResponse('Two.');

    expect(first).toBeTypeOf('number');
    expect(second).toBeTypeOf('number');
    expect(second).not.toBe(first);
    // 'Two.' is queued, not spoken -- but it still got a real id.
    expect(spokenTexts()).toEqual(['One.']);
  });

  it('returns undefined ONLY when no engine exists at all', async () => {
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();
    // BF-764 GUARD 1 reads `undefined` as "nothing will ever speak". A merely
    // queued utterance must not look like that.
    expect(voiceMod.speakResponse('Queued behind nothing.')).toBeTypeOf('number');
    expect(voiceMod.speakResponse('Queued behind something.')).toBeTypeOf('number');

    delete (globalThis as any).speechSynthesis;
    delete (globalThis as any).Audio;
    expect(voiceMod.speakResponse('No engine.')).toBeUndefined();
  });

  it('emits no start or end for a queued-but-unstarted entry', async () => {
    // THE MICROPHONE-GATING INVARIANT. `wakeWord` sets its barge-in flag on
    // 'start' and the BF-300 PTT gate blocks the mic on it. If the arbiter
    // announced an utterance at ENQUEUE time, the Captain's microphone would
    // be gated while the room is silent -- a worse defect than the one fixed.
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();
    const events = await _capture();

    voiceMod.speakResponse('Playing.', undefined, 'ezri');
    const queued = voiceMod.speakResponse('Waiting.', undefined, 'ezri');
    await _flush();

    expect(events.filter((e) => e.utterance_id === queued)).toEqual([]);
    expect(events.map((e) => e.type)).toEqual(['start']);

    await endSpoken(0);
    // Only once it actually reaches the device does it announce itself.
    expect(events.some((e) => e.utterance_id === queued && e.type === 'start')).toBe(true);
  });

  it('flushSpeechQueue empties the backlog without cutting the live utterance', async () => {
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();
    const events = await _capture();

    const live = voiceMod.speakResponse('Playing.', undefined, 'ezri');
    voiceMod.speakResponse('Backlog one.', undefined, 'ezri');
    voiceMod.speakResponse('Backlog two.', undefined, 'ezri');
    await _flush();

    voiceMod.flushSpeechQueue('test-flush');
    expect(events.filter((e) => e.type === 'dropped').map((e) => e.reason))
      .toEqual(['test-flush', 'test-flush']);

    // The in-flight utterance is not the flush's to cut, and its consumers
    // must still receive its terminal 'end'.
    await endSpoken(0);
    expect(events.some((e) => e.type === 'end' && e.utterance_id === live)).toBe(true);
    expect(spokenTexts()).toEqual(['Playing.']);
  });

  it('barge-in leaves nothing queued to talk over the Captain', async () => {
    // The regression the queue would otherwise INTRODUCE: before the arbiter,
    // barge-in stopped the utterance and nothing followed. With a queue,
    // cancelling would immediately dispatch the next one -- so the Captain is
    // talked over by a backlog at the moment they try to speak.
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('Playing.');
    voiceMod.speakResponse('Backlog.');
    await _flush();

    voiceMod.stopSpeaking();
    await _flush();
    // The live utterance's engine-level cancel fires its terminal 'end'; the
    // backlog must NOT step into the gap.
    speakCalls[0].onerror?.();
    await _flush();

    expect(spokenTexts()).toEqual(['Playing.']);
  });

  it('barge-in drops a queued INTERACTIVE utterance too, and says so', async () => {
    // The "interactive is never dropped" invariant is scoped to PRE-EMPTION.
    // Barge-in is the Captain saying stop, not the arbiter ranking utterances,
    // so it clears either class -- preserving an interactive backlog would
    // resume speech the Captain just interrupted. What the invariant DOES
    // require is that the drop is never silent. Adversarial review found the
    // unscoped claim in DECISIONS.md with no test either way.
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    const dropped: string[] = [];
    const unsubscribe = voiceMod.onSpeechEvent(e => {
      if (e.type === 'dropped') dropped.push(String(e.utterance?.text ?? ''));
    });
    try {
      voiceMod.speakResponse('Playing.', undefined, undefined, undefined, 'interactive');
      voiceMod.speakResponse('Queued interactive.', undefined, undefined, undefined, 'interactive');
      await _flush();

      voiceMod.stopSpeaking();
      await _flush();
      speakCalls[0].onerror?.();
      await _flush();

      expect(spokenTexts()).toEqual(['Playing.']);
      expect(dropped).toContain('Queued interactive.');
    } finally {
      unsubscribe();
    }
  });

  it('an unmounting surface drops only its own queued narration', async () => {
    // A tab leaving must not silence whatever another surface is queueing --
    // there is one device, but several producers on it.
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();
    const events = await _capture();

    voiceMod.speakResponse('Playing.', undefined, 'ezri');
    const mine = voiceMod.speakResponse('Leaving tab.', undefined, 'ezri');
    voiceMod.speakResponse('Other surface.', undefined, 'meridian');
    await _flush();

    voiceMod.flushSpeechQueue('unmount', 'ezri');

    const drops = events.filter((e) => e.type === 'dropped');
    expect(drops.map((d) => d.utterance_id)).toEqual([mine]);

    await endSpoken(0);
    expect(spokenTexts()).toEqual(['Playing.', 'Other surface.']);
  });
});
