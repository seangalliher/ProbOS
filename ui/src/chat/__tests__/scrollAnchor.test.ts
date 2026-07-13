// AD-984c: interruptible auto-scroll helper. Pure unit tests — no DOM.
import { describe, it, expect } from 'vitest';
import { isPinnedToBottom, PIN_THRESHOLD_PX, decideScrollOnUpdate } from '../scrollAnchor';

describe('AD-984c isPinnedToBottom', () => {
  it('treats a null/undefined element as pinned (nothing to scroll yet)', () => {
    expect(isPinnedToBottom(null)).toBe(true);
    expect(isPinnedToBottom(undefined)).toBe(true);
  });

  it('treats a non-overflowing container as pinned', () => {
    // content fits — scrollHeight <= clientHeight
    expect(isPinnedToBottom({ scrollTop: 0, scrollHeight: 200, clientHeight: 400 })).toBe(true);
  });

  it('is pinned when scrolled to the exact bottom', () => {
    // scrollTop = scrollHeight - clientHeight
    expect(isPinnedToBottom({ scrollTop: 600, scrollHeight: 1000, clientHeight: 400 })).toBe(true);
  });

  it('is pinned within the threshold of the bottom', () => {
    // distanceFromBottom = 1000 - 400 - 560 = 40 <= 80
    expect(isPinnedToBottom({ scrollTop: 560, scrollHeight: 1000, clientHeight: 400 })).toBe(true);
  });

  it('is NOT pinned when scrolled up beyond the threshold (the Captain reading earlier turns)', () => {
    // distanceFromBottom = 1000 - 400 - 200 = 400 > 80
    expect(isPinnedToBottom({ scrollTop: 200, scrollHeight: 1000, clientHeight: 400 })).toBe(false);
  });

  it('honors a custom threshold', () => {
    // distanceFromBottom = 100; default 80 -> not pinned; threshold 150 -> pinned
    const el = { scrollTop: 500, scrollHeight: 1000, clientHeight: 400 };
    expect(isPinnedToBottom(el)).toBe(false);
    expect(isPinnedToBottom(el, 150)).toBe(true);
  });

  it('exposes a sane default threshold', () => {
    expect(PIN_THRESHOLD_PX).toBeGreaterThan(0);
  });
});

describe('AD-1075 decideScrollOnUpdate', () => {
  it('does nothing for an empty transcript', () => {
    expect(decideScrollOnUpdate({
      switched: false, remounted: false, prevCount: 0, count: 0,
      prevTailId: null, tailId: null, previousTailContinues: false,
      pinned: true, lastFromSelf: false,
    }))
      .toEqual({ jump: false, follow: false });
  });

  it('jumps (instant) on a context switch (agent/thread changed)', () => {
    expect(decideScrollOnUpdate({
      switched: true, remounted: false, prevCount: 30, count: 30,
      prevTailId: 'old-tail', tailId: 'new-tail', previousTailContinues: false,
      pinned: false, lastFromSelf: false,
    }))
      .toEqual({ jump: true, follow: false });
  });

  it('jumps (instant) when a hidden transcript remounts', () => {
    expect(decideScrollOnUpdate({
      switched: false, remounted: true, prevCount: 30, count: 30,
      prevTailId: 'tail-30', tailId: 'tail-30', previousTailContinues: false,
      pinned: false, lastFromSelf: false,
    }))
      .toEqual({ jump: true, follow: false });
  });

  it('jumps (instant) on an initial load with no prior-tail continuity', () => {
    expect(decideScrollOnUpdate({
      switched: false, remounted: false, prevCount: 0, count: 30,
      prevTailId: null, tailId: 'tail-30', previousTailContinues: false,
      pinned: true, lastFromSelf: false,
    }))
      .toEqual({ jump: true, follow: false });
  });

  it('does nothing when count and tail are unchanged', () => {
    expect(decideScrollOnUpdate({
      switched: false, remounted: false, prevCount: 10, count: 10,
      prevTailId: 'tail-10', tailId: 'tail-10', previousTailContinues: false,
      pinned: true, lastFromSelf: false,
    }))
      .toEqual({ jump: false, follow: false });
  });

  it('follows an ordinary agent append when pinned to the bottom', () => {
    expect(decideScrollOnUpdate({
      switched: false, remounted: false, prevCount: 10, count: 11,
      prevTailId: 'tail-10', tailId: 'tail-11', previousTailContinues: true,
      pinned: true, lastFromSelf: false,
    }))
      .toEqual({ jump: false, follow: true });
  });

  it('does NOT follow an ordinary agent append when the Captain has scrolled up', () => {
    expect(decideScrollOnUpdate({
      switched: false, remounted: false, prevCount: 10, count: 11,
      prevTailId: 'tail-10', tailId: 'tail-11', previousTailContinues: true,
      pinned: false, lastFromSelf: false,
    }))
      .toEqual({ jump: false, follow: false });
  });

  it('ALWAYS follows an ordinary Captain append when not pinned', () => {
    expect(decideScrollOnUpdate({
      switched: false, remounted: false, prevCount: 10, count: 11,
      prevTailId: 'tail-10', tailId: 'tail-11', previousTailContinues: true,
      pinned: false, lastFromSelf: true,
    }))
      .toEqual({ jump: false, follow: true });
  });

  it('follows an equal-count capped agent append when pinned', () => {
    expect(decideScrollOnUpdate({
      switched: false, remounted: false, prevCount: 200, count: 200,
      prevTailId: 'tail-200', tailId: 'tail-201', previousTailContinues: true,
      pinned: true, lastFromSelf: false,
    }))
      .toEqual({ jump: false, follow: true });
  });

  it('does NOT follow an equal-count capped agent append when unpinned', () => {
    expect(decideScrollOnUpdate({
      switched: false, remounted: false, prevCount: 200, count: 200,
      prevTailId: 'tail-200', tailId: 'tail-201', previousTailContinues: true,
      pinned: false, lastFromSelf: false,
    }))
      .toEqual({ jump: false, follow: false });
  });

  it('ALWAYS follows an equal-count capped Captain append when unpinned', () => {
    expect(decideScrollOnUpdate({
      switched: false, remounted: false, prevCount: 200, count: 200,
      prevTailId: 'tail-200', tailId: 'tail-201', previousTailContinues: true,
      pinned: false, lastFromSelf: true,
    }))
      .toEqual({ jump: false, follow: true });
  });

  it('jumps for a same-count changed-tail replacement without continuity', () => {
    expect(decideScrollOnUpdate({
      switched: false, remounted: false, prevCount: 200, count: 200,
      prevTailId: 'old-tail', tailId: 'replacement-tail', previousTailContinues: false,
      pinned: true, lastFromSelf: false,
    }))
      .toEqual({ jump: true, follow: false });
  });

  it('jumps when count increases by one without tail continuity', () => {
    expect(decideScrollOnUpdate({
      switched: false, remounted: false, prevCount: 10, count: 11,
      prevTailId: 'old-tail', tailId: 'replacement-tail', previousTailContinues: false,
      pinned: true, lastFromSelf: false,
    }))
      .toEqual({ jump: true, follow: false });
  });

  it('jumps (instant) on a multi-message load', () => {
    expect(decideScrollOnUpdate({
      switched: false, remounted: false, prevCount: 5, count: 25,
      prevTailId: 'tail-5', tailId: 'tail-25', previousTailContinues: false,
      pinned: true, lastFromSelf: false,
    }))
      .toEqual({ jump: true, follow: false });
  });
});
