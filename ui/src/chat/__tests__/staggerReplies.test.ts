// AD-952: tests for the pure progressive-reveal sequencer (human response
// dynamics). No React, no real timers — the clock is injected so order +
// indicator transitions are asserted deterministically.
import { describe, it, expect, vi } from 'vitest';
import {
  computeTypingDelay,
  revealRepliesProgressively,
  TYPING_MIN_MS,
  TYPING_MAX_MS,
  TYPING_BASE_MS,
  type StaggerReply,
  type RevealDeps,
} from '../staggerReplies';

describe('AD-952 computeTypingDelay', () => {
  it('scales with text length', () => {
    const short = computeTypingDelay('hi');
    const long = computeTypingDelay('x'.repeat(60));
    expect(long).toBeGreaterThan(short);
  });

  it('clamps a very short reply to the minimum', () => {
    expect(computeTypingDelay('a')).toBeGreaterThanOrEqual(TYPING_MIN_MS);
  });

  it('clamps a very long reply to the maximum', () => {
    expect(computeTypingDelay('x'.repeat(10000))).toBe(TYPING_MAX_MS);
  });

  it('treats empty / whitespace as the base floor (min), never NaN', () => {
    const d = computeTypingDelay('   ');
    expect(Number.isFinite(d)).toBe(true);
    // base (480) already exceeds the 360 min, so a blank reply == base.
    expect(d).toBe(TYPING_BASE_MS);
  });

  it('honors option overrides', () => {
    expect(computeTypingDelay('abc', { baseMs: 0, perCharMs: 0, minMs: 0, maxMs: 5000 })).toBe(0);
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
    ...overrides,
  };
  return { deps, events, appended };
}

describe('AD-952 revealRepliesProgressively', () => {
  const replies: StaggerReply[] = [
    { agent_id: 'a1', callsign: 'Scout', text: 'first' },
    { agent_id: 'a2', callsign: 'Bones', text: 'second' },
  ];

  it('reveals replies in order: typing -> append per reply, then a final clear', async () => {
    const { deps, events, appended } = _recordingDeps();
    await revealRepliesProgressively(replies, deps);
    expect(events).toEqual([
      'typing:a1', 'append:a1',
      'typing:a2', 'append:a2',
      'typing:null',
    ]);
    expect(appended.map((r) => r.agent_id)).toEqual(['a1', 'a2']);
  });

  it('skips empty-text replies (no typing beat, no append)', async () => {
    const { deps, events } = _recordingDeps();
    await revealRepliesProgressively(
      [{ agent_id: 'a1', text: '' }, { agent_id: 'a2', callsign: 'Bones', text: 'real' }],
      deps,
    );
    expect(events).toEqual(['typing:a2', 'append:a2', 'typing:null']);
  });

  it('always clears the indicator at the end (finally)', async () => {
    const { deps, events } = _recordingDeps();
    await revealRepliesProgressively(replies, deps);
    expect(events[events.length - 1]).toBe('typing:null');
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
