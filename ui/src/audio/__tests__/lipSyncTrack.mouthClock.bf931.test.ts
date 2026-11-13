/** BF-931 (#1669): the heuristic mouth track is sampled on the clock the voice runs on.
 *
 * The speech 'start' event fires when `play()` is requested, not when sound begins, and the heuristic viseme track
 * (the avatar's schedule until the rhubarb frames arrive, BF-918) was sampled on a wall clock started at that
 * event, so the mouth led the voice by however long the audio took to start. `mouthClockMs(audioMs, wallMs)`
 * picks the clock: the audio element's time when server audio is active (0 until it plays, where the track is
 * closed), the wall clock otherwise (browser speech).
 *
 * The function is read from the module namespace, through a cast, so this file type-checks and loads before it
 * exists; the cases that need it are `built`, which is `it.fails` until BF-931 M2 sets it to `it`. With
 * BF931_RUNXFAIL=1 they run as ordinary cases and each stops at the call. The text is synthetic.
 */
import { describe, it, expect } from 'vitest';
import * as track from '../lipSyncTrack';
import { buildHeuristicTrack } from '../lipSyncTrack';

const built = process.env.BF931_RUNXFAIL === '1' ? it : it.fails;

function mouthClockMs(audioMs: number | null, wallMs: number): number {
  const fn = (track as unknown as {
    mouthClockMs?: (audioMs: number | null, wallMs: number) => number;
  }).mouthClockMs;
  if (fn === undefined) throw new Error('mouthClockMs is not exported by lipSyncTrack yet');
  return fn(audioMs, wallMs);
}

const TEXT = 'Okay, ready when you are.';
const CLOSED = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };

describe('BF-931: the heuristic mouth is sampled on the voice clock', () => {
  it('premise: a heuristic track is closed at time zero and before it, and open 200 ms in', () => {
    const heuristic = buildHeuristicTrack(TEXT, { rate: 1 });
    expect(heuristic).not.toBeNull();
    expect(heuristic!.sample(0)).toEqual(CLOSED);
    expect(heuristic!.sample(-1)).toEqual(CLOSED);
    expect(heuristic!.sample(200)).not.toEqual(CLOSED);
  });

  built('runs on the wall clock when no server audio is active (browser speech)', () => {
    expect(mouthClockMs(null, 120)).toBe(120);
  });

  built('stays at the start while the audio exists but has not started, whatever the wall clock says', () => {
    expect(mouthClockMs(0, 200)).toBe(0);
    expect(mouthClockMs(0, 5000)).toBe(0);
  });

  built('follows the audio time once it plays, not the wall clock', () => {
    expect(mouthClockMs(40, 400)).toBe(40);
    expect(mouthClockMs(1250, 300)).toBe(1250);
  });

  built('counts a non-finite or negative audio time as not started', () => {
    expect(mouthClockMs(Number.NaN, 500)).toBe(0);
    expect(mouthClockMs(-5, 500)).toBe(0);
  });

  built('closes the mouth at the instant the wall clock opened it: the defect in numbers', () => {
    const heuristic = buildHeuristicTrack(TEXT, { rate: 1 })!;
    expect(heuristic.sample(mouthClockMs(0, 200))).toEqual(CLOSED);
    expect(heuristic.sample(200)).not.toEqual(CLOSED);
  });
});
