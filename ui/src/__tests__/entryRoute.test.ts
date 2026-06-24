// AD-708b: tests for resolveEntryTarget (pure entry-routing) + its integration
// with the AD-708a isPadDevice() device gate. Pure-branch cases assert the
// precedence (compact > `#desktop` escape > device gate). Integration cases
// drive a REAL isPadDevice() via the AD-708a matchMedia/innerWidth stub idiom
// (usePadDevice.test.ts), torn down in afterEach so no global state leaks.
import { describe, it, expect, afterEach, vi } from 'vitest';
import { resolveEntryTarget } from '../entryRoute';
import { isPadDevice } from '../hooks/usePadDevice';

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

describe('AD-708b resolveEntryTarget (pure)', () => {
  it('routes #compact to compact even on a PADD (compact wins)', () => {
    expect(resolveEntryTarget('#compact', true)).toBe('compact');
  });

  it('routes #desktop to desktop on a PADD (escape hatch)', () => {
    expect(resolveEntryTarget('#desktop', true)).toBe('desktop');
  });

  it('routes a fine-pointer client with no hash to desktop', () => {
    expect(resolveEntryTarget('', false)).toBe('desktop');
  });

  it('routes a PADD with no hash to mobile', () => {
    expect(resolveEntryTarget('', true)).toBe('mobile');
  });

  it('routes a PADD with an unrelated view hash to mobile', () => {
    expect(resolveEntryTarget('#view=agents', true)).toBe('mobile');
  });
});

describe('AD-708b resolveEntryTarget x isPadDevice (integration)', () => {
  it('a coarse pointer at mobile width resolves to mobile', () => {
    stubMatchMedia(true);
    setWidth(390);
    expect(resolveEntryTarget('', isPadDevice())).toBe('mobile');
  });

  it('a fine pointer at mobile width resolves to desktop (narrow-desktop guard)', () => {
    setWidth(390);
    expect(resolveEntryTarget('', isPadDevice())).toBe('desktop');
  });

  it('a coarse pointer at desktop width resolves to desktop (width gate)', () => {
    stubMatchMedia(true);
    setWidth(1920);
    expect(resolveEntryTarget('', isPadDevice())).toBe('desktop');
  });
});
