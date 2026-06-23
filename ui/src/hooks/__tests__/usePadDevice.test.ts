// AD-708a: unit tests for usePadDevice + the pure getters hasCoarsePointer /
// isPadDevice. jsdom does NOT implement window.matchMedia (see
// src/test/setup.ts and usePrefersReducedMotion.test.ts), so the default path
// exercises the honest-degrade to false. The pointer axis is stubbed via
// vi.stubGlobal('matchMedia', ...) and torn down in afterEach; the width axis
// is set via Object.defineProperty(window,'innerWidth',...) and restored in
// afterEach (the AD-392 GlassAdaptive convention).
import { describe, it, expect, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { hasCoarsePointer, isPadDevice, usePadDevice } from '../usePadDevice';

const originalInnerWidth = window.innerWidth;

/** Stub matchMedia so only the (pointer: coarse) query reports `coarse`. */
function stubMatchMedia(coarse: boolean): void {
  vi.stubGlobal('matchMedia', (q: string) => ({
    matches: String(q).includes('coarse') ? coarse : false,
    media: q,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent() { return false; },
  }));
}

function setWidth(value: number): void {
  Object.defineProperty(window, 'innerWidth', { value, writable: true, configurable: true });
}

afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(window, 'innerWidth', {
    value: originalInnerWidth,
    writable: true,
    configurable: true,
  });
});

describe('AD-708a hasCoarsePointer (pure)', () => {
  it('honest-degrades to false when matchMedia is absent (jsdom default)', () => {
    expect(hasCoarsePointer()).toBe(false);
  });

  it('returns true when (pointer: coarse) matches', () => {
    stubMatchMedia(true);
    expect(hasCoarsePointer()).toBe(true);
  });

  it('returns false when matchMedia exists but the pointer is not coarse', () => {
    stubMatchMedia(false);
    expect(hasCoarsePointer()).toBe(false);
  });
});

describe('AD-708a isPadDevice (pure)', () => {
  it('returns false for a coarse pointer at desktop width (width gate)', () => {
    stubMatchMedia(true);
    setWidth(1920);
    expect(isPadDevice()).toBe(false);
  });

  it('returns false for mobile width with no coarse pointer (narrow desktop window stays out)', () => {
    setWidth(375);
    expect(isPadDevice()).toBe(false);
  });

  it('returns true for a coarse pointer at mobile width (<= 768)', () => {
    stubMatchMedia(true);
    setWidth(375);
    expect(isPadDevice()).toBe(true);
  });
});

describe('AD-708a usePadDevice (hook)', () => {
  it('returns false when matchMedia is absent', () => {
    setWidth(375);
    const { result } = renderHook(() => usePadDevice());
    expect(result.current).toBe(false);
  });

  it('returns true for a coarse pointer at mobile width', () => {
    stubMatchMedia(true);
    setWidth(375);
    const { result } = renderHook(() => usePadDevice());
    expect(result.current).toBe(true);
  });

  it('updates when innerWidth changes and a resize event fires', () => {
    stubMatchMedia(true);
    setWidth(1920);
    const { result } = renderHook(() => usePadDevice());
    expect(result.current).toBe(false);

    setWidth(375);
    act(() => {
      window.dispatchEvent(new Event('resize'));
    });
    expect(result.current).toBe(true);
  });
});
