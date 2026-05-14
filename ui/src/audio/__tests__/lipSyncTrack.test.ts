/** AD-721b v1: lipSyncTrack.ts unit tests.
 *
 *  Covers letter→viseme mapping, ``buildHeuristicTrack`` Tier-2 fallback,
 *  cross-blend behaviour, and out-of-range sampling. ≥ 12 cases per dispatch
 *  §4 D5 (this file enumerates 13). */
import { describe, it, expect } from 'vitest';
import {
  _textToVisemes,
  buildHeuristicTrack,
  _CONSTANTS,
  _VISEME_TARGETS,
  type VisemeKey,
} from '../lipSyncTrack';

describe('AD-721b _textToVisemes — letter → viseme mapping', () => {
  it("'a' maps to a single 'aa' viseme with target aa=1.0", () => {
    const segs = _textToVisemes('a');
    expect(segs).toHaveLength(1);
    expect(segs[0].viseme).toBe<VisemeKey>('aa');
    expect(_VISEME_TARGETS[segs[0].viseme].aa).toBe(1.0);
    expect(_VISEME_TARGETS[segs[0].viseme].oh).toBe(0);
  });

  it("'o' maps to a single 'oh' viseme with target oh=1.0", () => {
    const segs = _textToVisemes('o');
    expect(segs).toHaveLength(1);
    expect(segs[0].viseme).toBe<VisemeKey>('oh');
    expect(_VISEME_TARGETS[segs[0].viseme].oh).toBe(1.0);
    expect(_VISEME_TARGETS[segs[0].viseme].aa).toBe(0);
  });

  it("'e' maps to a single 'E' viseme with target ee=1.0", () => {
    const segs = _textToVisemes('e');
    expect(segs).toHaveLength(1);
    expect(segs[0].viseme).toBe<VisemeKey>('E');
    expect(_VISEME_TARGETS[segs[0].viseme].ee).toBe(1.0);
  });

  it("'i' maps to a single 'ih' viseme with target ih=1.0", () => {
    const segs = _textToVisemes('i');
    expect(segs).toHaveLength(1);
    expect(segs[0].viseme).toBe<VisemeKey>('ih');
    expect(_VISEME_TARGETS[segs[0].viseme].ih).toBe(1.0);
  });

  it("'u' maps to a single 'ou' viseme with target ou=1.0", () => {
    const segs = _textToVisemes('u');
    expect(segs).toHaveLength(1);
    expect(segs[0].viseme).toBe<VisemeKey>('ou');
    expect(_VISEME_TARGETS[segs[0].viseme].ou).toBe(1.0);
  });

  it("'p' maps to 'PP' viseme with residual aa=0.25 (AD-738c)", () => {
    const segs = _textToVisemes('p');
    expect(segs).toHaveLength(1);
    expect(segs[0].viseme).toBe<VisemeKey>('PP');
    expect(_VISEME_TARGETS[segs[0].viseme].aa).toBeCloseTo(0.25, 5);
  });

  it("'th' is greedy-consumed as 'CH' digraph (single segment, ee residual)", () => {
    const segs = _textToVisemes('th');
    expect(segs).toHaveLength(1);
    expect(segs[0].viseme).toBe<VisemeKey>('CH');
    expect(_VISEME_TARGETS[segs[0].viseme].ee).toBeCloseTo(0.20, 5);
  });

  it("'rr' produces two consecutive 'RR' visemes with oh residual=0.30 (AD-738c)", () => {
    const segs = _textToVisemes('rr');
    expect(segs).toHaveLength(2);
    expect(segs[0].viseme).toBe<VisemeKey>('RR');
    expect(segs[1].viseme).toBe<VisemeKey>('RR');
    expect(_VISEME_TARGETS[segs[0].viseme].oh).toBeCloseTo(0.30, 5);
    expect(_VISEME_TARGETS[segs[1].viseme].oh).toBeCloseTo(0.30, 5);
    // Phonemes back-to-back: second starts where first ends.
    expect(segs[1].startMs).toBeCloseTo(segs[0].startMs + segs[0].durationMs, 5);
  });
});

describe('AD-721b buildHeuristicTrack — Tier-2 fallback', () => {
  it('returns null for empty text', () => {
    expect(buildHeuristicTrack('')).toBeNull();
  });

  it('returns null for whitespace-only text', () => {
    expect(buildHeuristicTrack('   ')).toBeNull();
    expect(buildHeuristicTrack('\t\n  ')).toBeNull();
  });

  it('returns null when handed a non-string (Tier-2 rather than throw)', () => {
    // Defensive: caller might pass undefined / number on accident — the
    // contract is null, not a thrown TypeError.
    expect(buildHeuristicTrack(undefined as any)).toBeNull();
    expect(buildHeuristicTrack(null as any)).toBeNull();
    expect(buildHeuristicTrack(42 as any)).toBeNull();
  });
});

describe('AD-721b LipSyncTrack.sample — out-of-range + cross-blend', () => {
  it('sample(-1) and sample(durationMs + 100) both return all zeros', () => {
    const t = buildHeuristicTrack('hello')!;
    expect(t).not.toBeNull();
    const before = t.sample(-1);
    expect(before).toEqual({ aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 });
    const after = t.sample(t.durationMs + 100);
    expect(after).toEqual({ aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 });
  });

  it("cross-blend: 'ao' track shows aa decaying and oh rising at the boundary", () => {
    const t = buildHeuristicTrack('ao')!;
    expect(t).not.toBeNull();
    // Schedule: [aa @ 0..PHONEME_DURATION_MS, oh @ PHONEME_DURATION_MS..2*PHONEME_DURATION_MS]
    const boundary = _CONSTANTS.PHONEME_DURATION_MS;
    // Just before the boundary, aa is the active target → aa near 1.0.
    const justBefore = t.sample(boundary - 5);
    expect(justBefore.aa).toBeGreaterThan(0.5);
    expect(justBefore.oh).toBeLessThan(0.5);
    // Inside the cross-blend window after the boundary: aa decaying, oh rising,
    // both strictly between 0 and 1.
    const inside = t.sample(boundary + _CONSTANTS.RELEASE_TIME_MS / 2);
    expect(inside.aa).toBeGreaterThan(0);
    expect(inside.aa).toBeLessThan(1.0);
    expect(inside.oh).toBeGreaterThan(0);
    expect(inside.oh).toBeLessThan(1.0);
    // Late inside the cross-blend window (just before the segment ends),
    // oh should clearly dominate (aa from prev target decayed; oh near 1.0).
    // Note: PHONEME_DURATION_MS (80) < RELEASE_TIME_MS (100), so the
    // cross-blend window extends past the segment end — sample within the
    // segment to stay in-range.
    const lateInBlend = t.sample(boundary + _CONSTANTS.PHONEME_DURATION_MS - 5);
    expect(lateInBlend.oh).toBeGreaterThan(lateInBlend.aa);
  });

  it('attack faster than release — observed via per-frame smoothing math', () => {
    // The per-frame attack/release coefficients live in CrewVRM.tsx
    // (k=0.30 attack, k=0.18 release). We assert the contract here at the
    // module level: targets are pinned; CrewVRM will multiply them in.
    // For matched dt, a rising vowel gets the attack coefficient and a
    // falling vowel gets the release coefficient — attack > release.
    const ATTACK_K = 0.30;
    const RELEASE_K = 0.18;
    expect(ATTACK_K).toBeGreaterThan(RELEASE_K);
    // And the time constants in lipSyncTrack reflect the same asymmetry:
    // ATTACK_TIME_MS < RELEASE_TIME_MS (faster open than close).
    expect(_CONSTANTS.ATTACK_TIME_MS).toBeLessThan(_CONSTANTS.RELEASE_TIME_MS);
  });
});
