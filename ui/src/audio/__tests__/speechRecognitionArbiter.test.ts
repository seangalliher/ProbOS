/**
 * BF-318 — speechRecognitionArbiter contract tests.
 *
 * Pure logic tests (the arbiter has zero dependencies). Cover the
 * full boundary surface: happy + queue + preempt + release-fan-out
 * + tie + idempotency.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  acquire,
  release,
  currentHolder,
  _resetForTests,
  PRIORITY_PRESS_TO_TALK,
  PRIORITY_CONVERSATION,
  PRIORITY_WAKE_WORD,
} from '../speechRecognitionArbiter';

beforeEach(() => {
  _resetForTests();
});

describe('BF-318 speechRecognitionArbiter', () => {
  it('acquire returns lease when no current holder', () => {
    const onAcquired = vi.fn();
    const lease = acquire({
      holder: 'press_to_talk',
      priority: PRIORITY_PRESS_TO_TALK,
      onAcquired,
    });
    expect(lease).not.toBeNull();
    expect(lease!.holder).toBe('press_to_talk');
    expect(lease!.priority).toBe(PRIORITY_PRESS_TO_TALK);
    expect(onAcquired).toHaveBeenCalledTimes(1);
    expect(currentHolder()).toEqual({
      holder: 'press_to_talk',
      priority: PRIORITY_PRESS_TO_TALK,
    });
  });

  it('lower-priority acquire while held returns null and queues', () => {
    const ptt = acquire({
      holder: 'press_to_talk',
      priority: PRIORITY_PRESS_TO_TALK,
    });
    const queuedAcquired = vi.fn();
    const queued = acquire({
      holder: 'wake_word',
      priority: PRIORITY_WAKE_WORD,
      onAcquired: queuedAcquired,
    });
    expect(queued).toBeNull();
    expect(queuedAcquired).not.toHaveBeenCalled();
    expect(currentHolder()!.holder).toBe('press_to_talk');

    // Release the press-to-talk lease — wake-word's queued onAcquired
    // should now fire.
    release(ptt!);
    expect(queuedAcquired).toHaveBeenCalledTimes(1);
    expect(currentHolder()!.holder).toBe('wake_word');
  });

  it('higher-priority acquire preempts current holder', () => {
    const wakePreempted = vi.fn();
    acquire({
      holder: 'wake_word',
      priority: PRIORITY_WAKE_WORD,
      onPreempted: wakePreempted,
    });
    const pttAcquired = vi.fn();
    const ptt = acquire({
      holder: 'press_to_talk',
      priority: PRIORITY_PRESS_TO_TALK,
      onAcquired: pttAcquired,
    });
    expect(ptt).not.toBeNull();
    expect(wakePreempted).toHaveBeenCalledWith('press_to_talk');
    expect(pttAcquired).toHaveBeenCalledTimes(1);
    expect(currentHolder()!.holder).toBe('press_to_talk');
  });

  it('release fires onReleased on queued waiters', () => {
    const ptt = acquire({
      holder: 'press_to_talk',
      priority: PRIORITY_PRESS_TO_TALK,
    });
    const wakeOnReleased = vi.fn();
    acquire({
      holder: 'wake_word',
      priority: PRIORITY_WAKE_WORD,
      onReleased: wakeOnReleased,
    });
    release(ptt!);
    expect(wakeOnReleased).toHaveBeenCalledTimes(1);
  });

  it('same-priority second acquire returns null (no preemption ties)', () => {
    const firstPreempted = vi.fn();
    const first = acquire({
      holder: 'conversation_a',
      priority: PRIORITY_CONVERSATION,
      onPreempted: firstPreempted,
    });
    const secondAcquired = vi.fn();
    const second = acquire({
      holder: 'conversation_b',
      priority: PRIORITY_CONVERSATION,
      onAcquired: secondAcquired,
    });
    expect(first).not.toBeNull();
    expect(second).toBeNull();
    expect(firstPreempted).not.toHaveBeenCalled();
    expect(secondAcquired).not.toHaveBeenCalled();
    expect(currentHolder()!.holder).toBe('conversation_a');
    // Releasing the first promotes the queued second.
    release(first!);
    expect(secondAcquired).toHaveBeenCalledTimes(1);
    expect(currentHolder()!.holder).toBe('conversation_b');
  });

  it('release with stale lease is a no-op', () => {
    const staleHolder = vi.fn();
    const stale = acquire({
      holder: 'wake_word',
      priority: PRIORITY_WAKE_WORD,
      onReleased: staleHolder,
    });
    acquire({
      holder: 'press_to_talk',
      priority: PRIORITY_PRESS_TO_TALK,
    });
    // Wake-word is now preempted; its lease is stale. Release should
    // be a no-op (NOT clear the active press-to-talk holder).
    release(stale!);
    expect(staleHolder).not.toHaveBeenCalled();
    expect(currentHolder()!.holder).toBe('press_to_talk');
  });

  it('PRIORITY_CONVERSATION constant exported for AD-747 consumer', () => {
    expect(PRIORITY_CONVERSATION).toBe(75);
    expect(PRIORITY_PRESS_TO_TALK).toBeGreaterThan(PRIORITY_CONVERSATION);
    expect(PRIORITY_CONVERSATION).toBeGreaterThan(PRIORITY_WAKE_WORD);
  });
});
