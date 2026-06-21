// AD-984b: unit tests for usePrefersReducedMotion + prefersReducedMotion.
// jsdom does NOT implement window.matchMedia (see src/test/setup.ts — it is
// deliberately absent), so the default path exercises the honest-degrade to
// false. The matched/unmatched paths stub matchMedia via vi.stubGlobal and
// tear it down in afterEach so no other test sees a leaked global.
import { describe, it, expect, afterEach, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { prefersReducedMotion, usePrefersReducedMotion } from '../usePrefersReducedMotion';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('AD-984b prefersReducedMotion (pure)', () => {
  it('honest-degrades to false when matchMedia is absent (jsdom default)', () => {
    expect(prefersReducedMotion()).toBe(false);
  });

  it('returns true when the OS requests reduced motion (matches=true)', () => {
    vi.stubGlobal('matchMedia', () => ({
      matches: true,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    }));
    expect(prefersReducedMotion()).toBe(true);
  });

  it('returns false when matchMedia exists but does not match (matches=false)', () => {
    vi.stubGlobal('matchMedia', () => ({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    }));
    expect(prefersReducedMotion()).toBe(false);
  });
});

describe('AD-984b usePrefersReducedMotion (hook)', () => {
  it('returns false when matchMedia is absent', () => {
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(false);
  });

  it('returns true when matchMedia reports reduced motion', () => {
    vi.stubGlobal('matchMedia', () => ({
      matches: true,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    }));
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(true);
  });

  it('returns false when matchMedia reports no preference', () => {
    vi.stubGlobal('matchMedia', () => ({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    }));
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(false);
  });
});
