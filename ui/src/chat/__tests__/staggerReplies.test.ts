// AD-952 / AD-960: tests for the pure progressive-reveal sequencer (human
// response dynamics). No React, no real timers — the clock is injected so
// order + indicator transitions + the AD-960 think/type pacing are asserted
// deterministically.
import { describe, it, expect, vi } from 'vitest';
import {
  computeTypingDelay,
  computeProcessingDelay,
  revealRepliesProgressively,
  TYPING_MIN_MS,
  TYPING_MAX_MS,
  TYPING_MS_PER_WORD,
  PROCESSING_FIRST_MS,
  PROCESSING_CASCADE_MS,
  type StaggerReply,
  type RevealDeps,
} from '../staggerReplies';

describe('AD-960 computeTypingDelay (60 wpm, word-based)', () => {
  it('scales with word count', () => {
    const short = computeTypingDelay('one two');
    const long = computeTypingDelay('one two three four five');
    expect(long).toBeGreaterThan(short);
  });

  it('is ~1s per word (60 wpm) inside the clamp', () => {
    // 4 words → 4000ms, within [min, max].
    expect(computeTypingDelay('one two three four')).toBe(4 * TYPING_MS_PER_WORD);
  });

  it('clamps a long reply to the maximum', () => {
    // 40 words × 1000ms = 40000ms → capped.
    expect(computeTypingDelay('word '.repeat(40))).toBe(TYPING_MAX_MS);
  });

  it('treats empty / whitespace as the minimum, never NaN', () => {
    const d = computeTypingDelay('   ');
    expect(Number.isFinite(d)).toBe(true);
    expect(d).toBe(TYPING_MIN_MS);
  });

  it('honors option overrides', () => {
    expect(computeTypingDelay('a b c', { msPerWord: 100, minMs: 0, maxMs: 5000 })).toBe(300);
  });
});

describe('AD-960 computeProcessingDelay (think-time)', () => {
  it('gives the first revealed reply the full processing beat', () => {
    expect(computeProcessingDelay(0)).toBe(PROCESSING_FIRST_MS);
  });

  it('gives later cascade replies the shorter inter-turn beat', () => {
    expect(computeProcessingDelay(1)).toBe(PROCESSING_CASCADE_MS);
    expect(computeProcessingDelay(5)).toBe(PROCESSING_CASCADE_MS);
  });

  it('first beat is longer than the cascade beat (deliberate first pause)', () => {
    expect(computeProcessingDelay(0)).toBeGreaterThan(computeProcessingDelay(1));
  });

  it('honors option overrides', () => {
    expect(computeProcessingDelay(0, { firstMs: 100 })).toBe(100);
    expect(computeProcessingDelay(2, { cascadeMs: 50 })).toBe(50);
  });
});

function _recordingDeps(overrides: Partial<RevealDeps> = {}): {
  deps: RevealDeps;
  events: string[];
  appended: StaggerReply[];
} {
  const events: string[] = [];
  const appended: StaggerReply[] = [];
  const deps: RevealDeps = {
    setTyping: (t) => events.push(t ? `typing:${t.agentId}` : 'typing:null'),
    appendReply: (r) => { events.push(`append:${r.agent_id}`); appended.push(r); },
    sleep: async () => { /* instant fake clock */ },
    delayFor: () => 0,
    processingFor: () => 0,
    ...overrides,
  };
  return { deps, events, appended };
}

describe('AD-952 / AD-960 revealRepliesProgressively', () => {
  const replies: StaggerReply[] = [
    { agent_id: 'a1', callsign: 'Scout', text: 'first' },
    { agent_id: 'a2', callsign: 'Bones', text: 'second' },
  ];

  it('reveals in order: typing -> clear -> append per reply, then a final clear', async () => {
    const { deps, events, appended } = _recordingDeps();
    await revealRepliesProgressively(replies, deps);
    expect(events).toEqual([
      'typing:a1', 'typing:null', 'append:a1',
      'typing:a2', 'typing:null', 'append:a2',
      'typing:null',
    ]);
    expect(appended.map((r) => r.agent_id)).toEqual(['a1', 'a2']);
  });

  it('clears the indicator BEFORE each message lands (no lingering "typing")', async () => {
    const { deps, events } = _recordingDeps();
    await revealRepliesProgressively([replies[0]], deps);
    const appendIdx = events.indexOf('append:a1');
    expect(events[appendIdx - 1]).toBe('typing:null');
  });

  it('skips empty-text replies (no typing beat, no append)', async () => {
    const { deps, events } = _recordingDeps();
    await revealRepliesProgressively(
      [{ agent_id: 'a1', text: '' }, { agent_id: 'a2', callsign: 'Bones', text: 'real' }],
      deps,
    );
    expect(events).toEqual(['typing:a2', 'typing:null', 'append:a2', 'typing:null']);
  });

  it('always clears the indicator at the end (finally)', async () => {
    const { deps, events } = _recordingDeps();
    await revealRepliesProgressively(replies, deps);
    expect(events[events.length - 1]).toBe('typing:null');
  });

  it('AD-960: the first reply waits longer than a later reply of equal length', async () => {
    // Real processing + typing (no overrides) with a recording clock. Equal
    // text => equal typing => the delta is purely the processing beat.
    const slept: number[] = [];
    const equalLen: StaggerReply[] = [
      { agent_id: 'a1', callsign: 'Scout', text: 'same length here now' },
      { agent_id: 'a2', callsign: 'Bones', text: 'same length here now' },
    ];
    const deps: RevealDeps = {
      setTyping: () => { /* noop */ },
      appendReply: () => { /* noop */ },
      sleep: async (ms) => { slept.push(ms); },
    };
    await revealRepliesProgressively(equalLen, deps);
    expect(slept).toHaveLength(2);
    expect(slept[0]).toBeGreaterThan(slept[1]);
    expect(slept[0] - slept[1]).toBe(PROCESSING_FIRST_MS - PROCESSING_CASCADE_MS);
  });

  it('AD-960: an empty leading reply does not consume the first-reply beat', async () => {
    const slept: number[] = [];
    const deps: RevealDeps = {
      setTyping: () => { /* noop */ },
      appendReply: () => { /* noop */ },
      sleep: async (ms) => { slept.push(ms); },
      delayFor: () => 0, // isolate the processing component
    };
    await revealRepliesProgressively(
      [{ agent_id: 'a0', text: '' }, { agent_id: 'a1', callsign: 'Scout', text: 'real reply' }],
      deps,
    );
    expect(slept).toEqual([PROCESSING_FIRST_MS]);
  });

  it('aborts before a reply when shouldContinue() is false (and still clears)', async () => {
    const { deps, events, appended } = _recordingDeps({ shouldContinue: () => false });
    await revealRepliesProgressively(replies, deps);
    // No reply revealed; the finally still clears.
    expect(appended).toEqual([]);
    expect(events).toEqual(['typing:null']);
  });

  it('stops mid-queue when shouldContinue flips false after the first reply', async () => {
    let calls = 0;
    const { deps, appended } = _recordingDeps({
      shouldContinue: () => { calls += 1; return calls <= 2; }, // allow reply 1's two checks
    });
    await revealRepliesProgressively(replies, deps);
    expect(appended.map((r) => r.agent_id)).toEqual(['a1']);
  });

  it('never throws even when a dep throws; the queue continues', async () => {
    const appended: StaggerReply[] = [];
    const deps: RevealDeps = {
      setTyping: vi.fn(() => { throw new Error('boom'); }),
      appendReply: (r) => appended.push(r),
      sleep: async () => { /* noop */ },
      delayFor: () => 0,
    };
    await expect(revealRepliesProgressively(replies, deps)).resolves.toBeUndefined();
    // setTyping throwing did not block the appends.
    expect(appended.map((r) => r.agent_id)).toEqual(['a1', 'a2']);
  });

  it('an empty replies array just clears the indicator and resolves', async () => {
    const { deps, events } = _recordingDeps();
    await revealRepliesProgressively([], deps);
    expect(events).toEqual(['typing:null']);
  });
});
