/** AD-921: pure meeting-voice sequencer tests. The audio layer is INJECTED as
 *  fakes -- no real TTS / WebAudio. Drives a fake ``subscribe`` that records
 *  its listener so the test can fire synthetic ``'end'`` events, and a fake
 *  ``speak`` that records ``(text, profile, agentId)``. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  speakRepliesSequentially,
  createVoiceProfileResolver,
  type MeetingVoiceDeps,
  type PerAgentReply,
} from '../meetingVoice';
import type { VoiceProfile, SpeechEvent } from '../voice';
// Vite ``?raw`` reads the source body for the HXI no-emoji guard without
// pulling in Node fs/path types.
import meetingVoiceSource from '../meetingVoice?raw';

interface FakeOpts {
  resolveProfile?: (id: string) => Promise<VoiceProfile | undefined>;
  strip?: (s: string) => string;
  utteranceTimeoutMs?: number;
}

interface SpeakCall {
  text: string;
  profile: VoiceProfile | undefined;
  agentId: string;
}

function makeFake(opts: FakeOpts = {}) {
  const listeners: Array<(e: SpeechEvent) => void> = [];
  const speakCalls: SpeakCall[] = [];
  const speakingChanges: Array<string | null> = [];
  const deps: MeetingVoiceDeps = {
    speak: (text, profile, agentId) => { speakCalls.push({ text, profile, agentId }); },
    subscribe: (fn) => {
      listeners.push(fn);
      return () => {
        const i = listeners.indexOf(fn);
        if (i >= 0) listeners.splice(i, 1);
      };
    },
    resolveProfile: opts.resolveProfile ?? (async () => undefined),
    onSpeakingChange: (id) => { speakingChanges.push(id); },
    strip: opts.strip,
    // Default 0 disables the per-utterance safety timer so tests drive
    // advancement purely by firing synthetic 'end' events.
    utteranceTimeoutMs: opts.utteranceTimeoutMs ?? 0,
  };
  const fireEnd = (agentId?: string): void => {
    const e: SpeechEvent = {
      type: 'end',
      agent_id: agentId,
      utterance: {} as unknown as SpeechSynthesisUtterance,
    };
    for (const fn of [...listeners]) fn(e);
  };
  return { deps, speakCalls, speakingChanges, fireEnd };
}

function r(agentId: string): PerAgentReply {
  return { agent_id: agentId, text: `text-${agentId}` };
}

/** Flush microtasks + one macrotask (real timers). The sequencer sets no
 *  timer when utteranceTimeoutMs is 0, so this leaves no lingering timers. */
const tick = (): Promise<void> => new Promise<void>((resolve) => setTimeout(resolve, 0));

afterEach(() => {
  vi.useRealTimers();
});

describe('speakRepliesSequentially', () => {
  it('test_speaks_replies_in_facilitator_array_order', async () => {
    const fake = makeFake();
    const p = speakRepliesSequentially([r('alpha'), r('bravo'), r('charlie')], fake.deps);
    await tick();
    expect(fake.speakCalls.map((c) => c.agentId)).toEqual(['alpha']);
    fake.fireEnd('alpha'); await tick();
    expect(fake.speakCalls.map((c) => c.agentId)).toEqual(['alpha', 'bravo']);
    fake.fireEnd('bravo'); await tick();
    expect(fake.speakCalls.map((c) => c.agentId)).toEqual(['alpha', 'bravo', 'charlie']);
    fake.fireEnd('charlie');
    await p;
    expect(fake.speakCalls.map((c) => c.agentId)).toEqual(['alpha', 'bravo', 'charlie']);
  });

  it('test_waits_for_previous_end_before_next', async () => {
    const fake = makeFake();
    const p = speakRepliesSequentially([r('a'), r('b')], fake.deps);
    await tick();
    expect(fake.speakCalls).toHaveLength(1);
    // No 'end' fired yet -- additional ticks must NOT advance the queue.
    await tick();
    await tick();
    expect(fake.speakCalls).toHaveLength(1);
    fake.fireEnd('a'); await tick();
    expect(fake.speakCalls).toHaveLength(2);
    fake.fireEnd('b');
    await p;
  });

  it('test_end_for_other_agent_does_not_advance', async () => {
    const fake = makeFake();
    const p = speakRepliesSequentially([r('a'), r('b')], fake.deps);
    await tick();
    expect(fake.speakCalls).toHaveLength(1);
    // An 'end' for a DIFFERENT agent_id must not resolve the current utterance.
    fake.fireEnd('someone-else'); await tick();
    expect(fake.speakCalls).toHaveLength(1);
    fake.fireEnd('a'); await tick();
    expect(fake.speakCalls).toHaveLength(2);
    fake.fireEnd('b');
    await p;
  });

  it('test_per_agent_profile_passed_to_speak', async () => {
    const profiles: Record<string, VoiceProfile> = {
      a: { pitch: 1.1, rate: 0.9 },
      b: { pitch: 0.8, rate: 1.0 },
    };
    const fake = makeFake({ resolveProfile: async (id) => profiles[id] });
    const p = speakRepliesSequentially([r('a'), r('b')], fake.deps);
    await tick();
    expect(fake.speakCalls[0]).toMatchObject({ agentId: 'a', profile: { pitch: 1.1, rate: 0.9 } });
    fake.fireEnd('a'); await tick();
    expect(fake.speakCalls[1]).toMatchObject({ agentId: 'b', profile: { pitch: 0.8, rate: 1.0 } });
    fake.fireEnd('b');
    await p;
  });

  it('test_speaking_change_set_then_cleared_around_each_utterance', async () => {
    const fake = makeFake();
    const p = speakRepliesSequentially([r('a'), r('b')], fake.deps);
    await tick();
    // Before the first 'end': set to 'a', not yet cleared.
    expect(fake.speakingChanges).toEqual(['a']);
    fake.fireEnd('a'); await tick();
    expect(fake.speakingChanges).toEqual(['a', null, 'b']);
    fake.fireEnd('b');
    await p;
    expect(fake.speakingChanges).toEqual(['a', null, 'b', null]);
  });

  it('test_safety_timeout_drains_queue_when_end_never_fires', async () => {
    vi.useFakeTimers();
    const fake = makeFake({ utteranceTimeoutMs: 50 });
    const p = speakRepliesSequentially([r('a'), r('b')], fake.deps);
    // Flush microtasks (resolveProfile) to reach the first speak.
    await vi.advanceTimersByTimeAsync(0);
    expect(fake.speakCalls).toHaveLength(1);
    // No 'end' ever fires (TTS unavailable) -- the safety timeout drains it.
    await vi.advanceTimersByTimeAsync(50);
    expect(fake.speakCalls).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(50);
    await p;
    expect(fake.speakCalls.map((c) => c.agentId)).toEqual(['a', 'b']);
  });

  it('test_should_continue_false_supersedes_remaining', async () => {
    const fake = makeFake();
    // Continue only while nothing has been spoken yet: the first utterance
    // proceeds; the next iteration's top-of-loop check breaks (no talk-over).
    fake.deps.shouldContinue = () => fake.speakCalls.length < 1;
    const p = speakRepliesSequentially([r('a'), r('b'), r('c')], fake.deps);
    await tick();
    expect(fake.speakCalls.map((c) => c.agentId)).toEqual(['a']);
    fake.fireEnd('a'); await tick();
    await p;
    expect(fake.speakCalls.map((c) => c.agentId)).toEqual(['a']);
  });

  it('test_empty_or_whitespace_text_skipped', async () => {
    const fake = makeFake();
    const replies: PerAgentReply[] = [
      { agent_id: 'a', text: '   ' },
      { agent_id: 'b', text: 'hello' },
    ];
    const p = speakRepliesSequentially(replies, fake.deps);
    await tick();
    // 'a' is whitespace -> skipped: no speak, no onSpeakingChange.
    expect(fake.speakCalls.map((c) => c.agentId)).toEqual(['b']);
    expect(fake.speakingChanges).toEqual(['b']);
    fake.fireEnd('b');
    await p;
  });

  it('test_resolve_profile_rejection_degrades_to_undefined', async () => {
    const fake = makeFake({ resolveProfile: async () => { throw new Error('boom'); } });
    const p = speakRepliesSequentially([r('a')], fake.deps);
    await tick();
    // Distinct-voice -> same-voice degrade (never silence).
    expect(fake.speakCalls).toHaveLength(1);
    expect(fake.speakCalls[0].profile).toBeUndefined();
    fake.fireEnd('a');
    await p;
  });

  it('test_strip_applied_to_spoken_text', async () => {
    const fake = makeFake({ strip: (s) => `[stripped]${s}` });
    const reply: PerAgentReply = { agent_id: 'a', callsign: 'Bones', text: '**bold**' };
    const p = speakRepliesSequentially([reply], fake.deps);
    await tick();
    expect(fake.speakCalls[0].text).toBe('[stripped]**bold**');
    // The callsign prefix is NOT spoken -- the voice conveys the speaker.
    expect(fake.speakCalls[0].text).not.toContain('Bones');
    fake.fireEnd('a');
    await p;
  });
});

describe('createVoiceProfileResolver', () => {
  it('test_resolver_caches_and_degrades', async () => {
    const vp: VoiceProfile = { pitch: 1.2, rate: 0.95 };
    const okFetch = vi.fn(async () => ({ ok: true, json: async () => ({ voiceProfile: vp }) }));
    const resolve = createVoiceProfileResolver(okFetch as unknown as typeof fetch);
    expect(await resolve('a')).toEqual(vp);
    // Second call for the same agent is served from cache (no second fetch).
    expect(await resolve('a')).toEqual(vp);
    expect(okFetch).toHaveBeenCalledTimes(1);

    const badFetch = vi.fn(async () => ({ ok: false, json: async () => ({}) }));
    const resolveBad = createVoiceProfileResolver(badFetch as unknown as typeof fetch);
    expect(await resolveBad('x')).toBeUndefined();

    const throwFetch = vi.fn(async () => { throw new Error('network'); });
    const resolveThrow = createVoiceProfileResolver(throwFetch as unknown as typeof fetch);
    expect(await resolveThrow('y')).toBeUndefined();
  });
});

describe('meetingVoice source hygiene', () => {
  it('source module contains no emoji (HXI #3)', () => {
    expect(meetingVoiceSource).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
