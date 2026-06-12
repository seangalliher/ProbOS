// AD-984c: interruptible auto-scroll helper. Pure unit tests — no DOM.
import { describe, it, expect } from 'vitest';
import { isPinnedToBottom, PIN_THRESHOLD_PX } from '../scrollAnchor';

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
