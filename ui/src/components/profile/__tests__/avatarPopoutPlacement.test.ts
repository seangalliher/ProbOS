/** BF-888 (#1367): where the detached avatar popout opens. */
import { describe, it, expect } from 'vitest';
import {
  avatarPopoutLateRect, avatarPopoutOpeningRect, isKeepClearRegion, KEEP_CLEAR_GAP, type KeepClearRect,
  type PopoutRect,
} from '../avatarPopoutPlacement';

const SIZE = { w: 320, h: 480 };
const NARROW = { w: 430, h: 932 };
const DESKTOP = { w: 1440, h: 1000 };
const NARROW_HOME: PopoutRect = { x: 86, y: 428, w: 320, h: 480 };
const DESKTOP_HOME: PopoutRect = { x: 1096, y: 496, w: 320, h: 480 };
// The composer row as Chromium measures it with the panel at its default position: (11,634) 390x45 at
// 430x932, holding voice at (308.6,644.5) as on the 2026-10-07 run, and (101,634) 390x45 at 1440x1000.
const NARROW_COMPOSER: KeepClearRect = { left: 11, top: 634, right: 401, bottom: 679 };
const DESKTOP_COMPOSER: KeepClearRect = { left: 101, top: 634, right: 491, bottom: 679 };

function covers(p: PopoutRect, r: KeepClearRect): boolean {
  return p.x < r.right && r.left < p.x + p.w && p.y < r.bottom && r.top < p.y + p.h;
}

describe('BF-888 avatarPopoutOpeningRect', () => {
  it('opens at the bottom-right home when no region is named', () => {
    expect(avatarPopoutOpeningRect(NARROW, SIZE, null)).toEqual(NARROW_HOME);
    expect(avatarPopoutOpeningRect(DESKTOP, SIZE, null)).toEqual(DESKTOP_HOME);
  });

  it('keeps the home when it does not cover the region, including a region touching its edge', () => {
    expect(avatarPopoutOpeningRect(DESKTOP, SIZE, DESKTOP_COMPOSER)).toEqual(DESKTOP_HOME);
    expect(avatarPopoutOpeningRect(NARROW, SIZE, { left: 11, top: 908, right: 403, bottom: 932 })).toEqual(NARROW_HOME);
  });

  it('opens directly above the composer at 430x932 instead of covering it', () => {
    expect(covers(NARROW_HOME, NARROW_COMPOSER)).toBe(true);
    const rect = avatarPopoutOpeningRect(NARROW, SIZE, NARROW_COMPOSER);
    expect(rect).toEqual({ x: 86, y: 634 - KEEP_CLEAR_GAP - 480, w: 320, h: 480 });
    expect(covers(rect, NARROW_COMPOSER)).toBe(false);
  });

  it('opens below the region when there is more room beneath it', () => {
    const region = { left: 11, top: 420, right: 403, bottom: 464 };
    const rect = avatarPopoutOpeningRect(NARROW, SIZE, region);
    expect(rect).toEqual({ x: 86, y: 464 + KEEP_CLEAR_GAP, w: 320, h: 932 - 464 - KEEP_CLEAR_GAP });
    expect(covers(rect, region)).toBe(false);
  });

  it('opens shorter, from the top, when the room above cannot hold its full height', () => {
    const region = { left: 11, top: 376, right: 403, bottom: 420 };
    const rect = avatarPopoutOpeningRect({ w: 430, h: 420 }, SIZE, region);
    expect(rect).toEqual({ x: 86, y: 0, w: 320, h: 376 - KEEP_CLEAR_GAP });
    expect(covers(rect, region)).toBe(false);
  });

  it('treats a region with no area, or a NaN edge, as nothing to keep clear', () => {
    expect(avatarPopoutOpeningRect(NARROW, SIZE, { left: 200, top: 650, right: 200, bottom: 650 })).toEqual(NARROW_HOME);
    expect(avatarPopoutOpeningRect(NARROW, SIZE, { ...NARROW_COMPOSER, bottom: Number.NaN })).toEqual(NARROW_HOME);
  });

  it('keeps the home when neither side of the region has room for the title bar', () => {
    const region = { left: 0, top: 10, right: 430, bottom: 40 };
    expect(avatarPopoutOpeningRect({ w: 430, h: 60 }, SIZE, region)).toEqual({ x: 86, y: 0, w: 320, h: 480 });
  });
});

describe('BF-888 A-1 a keep-clear region that appears after the popout opened', () => {
  it('counts only a rectangle with area as a region', () => {
    expect(isKeepClearRegion(NARROW_COMPOSER)).toBe(true);
    expect(isKeepClearRegion(null)).toBe(false);
    expect(isKeepClearRegion({ left: 0, top: 0, right: 0, bottom: 0 })).toBe(false);
    expect(isKeepClearRegion({ ...NARROW_COMPOSER, top: Number.NaN })).toBe(false);
  });

  it('sends a popout that covers the late region to its opening rectangle for it (430x932)', () => {
    expect(avatarPopoutLateRect(NARROW_HOME, NARROW, SIZE, NARROW_COMPOSER)).toEqual({ x: 86, y: 146, w: 320, h: 480 });
  });

  it('leaves a popout that does not cover the late region where it is (the 1440x1000 home)', () => {
    expect(avatarPopoutLateRect(DESKTOP_HOME, DESKTOP, SIZE, DESKTOP_COMPOSER)).toBeNull();
  });
});
