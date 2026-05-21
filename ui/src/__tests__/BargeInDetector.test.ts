/** AD-760 — bargeInDetector tests (Schmitt-trigger hysteresis). */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Capture subscribed handlers so tests can pump frames synchronously.
type PcmHandler = {
  onFrame: (frame: Float32Array, sr: number, score?: number) => void;
};
const captured: { handler: PcmHandler | null; unsub: ReturnType<typeof vi.fn> } = {
  handler: null,
  unsub: vi.fn(),
};

vi.mock('../audio/voiceActivity', () => ({
  subscribePcm: (h: PcmHandler) => {
    captured.handler = h;
    captured.unsub = vi.fn(() => {
      captured.handler = null;
    });
    return captured.unsub;
  },
}));

import { attachBargeInDetector, _rmsDbfs } from '../audio/bargeInDetector';

/** Build a frame at a known RMS level (linear amplitude). */
function loudFrame(amplitude = 0.5): Float32Array {
  const f = new Float32Array(480);
  for (let i = 0; i < f.length; i++) f[i] = amplitude;
  return f;
}

function silentFrame(): Float32Array {
  return new Float32Array(480);
}

beforeEach(() => {
  captured.handler = null;
  captured.unsub = vi.fn();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('AD-760 bargeInDetector — Schmitt hysteresis', () => {
  it('fires onBargeIn after exactly debounceFrames sustained high-score frames', () => {
    const onBargeIn = vi.fn();
    attachBargeInDetector({
      onsetConfidence: 0.80,
      offsetConfidence: 0.40,
      debounceFrames: 8,
      releaseFrames: 3,
      amplitudeFloorDb: -45,
      cooldownMs: 500,
      onBargeIn,
    });
    expect(captured.handler).not.toBeNull();
    const h = captured.handler!;

    // 7 frames above onset — must NOT fire yet.
    for (let i = 0; i < 7; i++) {
      h.onFrame(loudFrame(), 16000, 0.95);
    }
    expect(onBargeIn).not.toHaveBeenCalled();

    // 8th frame fires.
    h.onFrame(loudFrame(), 16000, 0.95);
    expect(onBargeIn).toHaveBeenCalledTimes(1);
  });

  it('cancels onset and enters cooldown when score drops mid-buildup', () => {
    vi.useFakeTimers();
    const onBargeIn = vi.fn();
    attachBargeInDetector({
      onsetConfidence: 0.80,
      offsetConfidence: 0.40,
      debounceFrames: 8,
      releaseFrames: 3,
      amplitudeFloorDb: -45,
      cooldownMs: 500,
      onBargeIn,
    });
    const h = captured.handler!;

    // Build to 4 frames.
    for (let i = 0; i < 4; i++) h.onFrame(loudFrame(), 16000, 0.95);
    // Drop — cancels, enters cooldown.
    h.onFrame(loudFrame(), 16000, 0.10);

    // Immediately drive 8 high-score frames — cooldown suppresses.
    for (let i = 0; i < 8; i++) h.onFrame(loudFrame(), 16000, 0.95);
    expect(onBargeIn).not.toHaveBeenCalled();

    // Advance past cooldown; then 8 high-score frames should fire.
    vi.advanceTimersByTime(600);
    for (let i = 0; i < 8; i++) h.onFrame(loudFrame(), 16000, 0.95);
    expect(onBargeIn).toHaveBeenCalledTimes(1);
  });

  it('amplitude floor suppresses high-score low-RMS frames', () => {
    const onBargeIn = vi.fn();
    attachBargeInDetector({
      onsetConfidence: 0.80,
      offsetConfidence: 0.40,
      debounceFrames: 8,
      releaseFrames: 3,
      amplitudeFloorDb: -45,
      cooldownMs: 500,
      onBargeIn,
    });
    const h = captured.handler!;
    // High score but silent frame (RMS -> -120 dBFS).
    for (let i = 0; i < 20; i++) h.onFrame(silentFrame(), 16000, 0.99);
    expect(onBargeIn).not.toHaveBeenCalled();
  });

  it('release requires releaseFrames sustained sub-offset frames', () => {
    const onBargeIn = vi.fn();
    const disarm = attachBargeInDetector({
      onsetConfidence: 0.80,
      offsetConfidence: 0.40,
      debounceFrames: 2,
      releaseFrames: 3,
      amplitudeFloorDb: -45,
      cooldownMs: 500,
      onBargeIn,
    });
    const h = captured.handler!;

    // Fire onset.
    h.onFrame(loudFrame(), 16000, 0.95);
    h.onFrame(loudFrame(), 16000, 0.95);
    expect(onBargeIn).toHaveBeenCalledTimes(1);

    // Now phase=above. 2 release frames not enough.
    h.onFrame(loudFrame(), 16000, 0.10);
    h.onFrame(loudFrame(), 16000, 0.10);
    // Re-enter onset territory; should NOT re-fire (still above).
    h.onFrame(loudFrame(), 16000, 0.95);
    h.onFrame(loudFrame(), 16000, 0.95);
    h.onFrame(loudFrame(), 16000, 0.95);
    expect(onBargeIn).toHaveBeenCalledTimes(1);
    disarm();
  });

  it('cooldown is per-detector-instance (no cross-talk)', () => {
    vi.useFakeTimers();
    const onBargeInA = vi.fn();
    const onBargeInB = vi.fn();
    // Both detectors share a single captured handler slot in our mock —
    // emulate by attaching A, draining, then B.
    attachBargeInDetector({
      onsetConfidence: 0.80, offsetConfidence: 0.40,
      debounceFrames: 4, releaseFrames: 3,
      amplitudeFloorDb: -45, cooldownMs: 1000,
      onBargeIn: onBargeInA,
    });
    const hA = captured.handler!;
    // Trigger cooldown on A.
    for (let i = 0; i < 2; i++) hA.onFrame(loudFrame(), 16000, 0.95);
    hA.onFrame(loudFrame(), 16000, 0.10); // cancel -> 1s cooldown on A
    // A is suppressed for 1s.
    for (let i = 0; i < 4; i++) hA.onFrame(loudFrame(), 16000, 0.95);
    expect(onBargeInA).not.toHaveBeenCalled();

    // Attach B (independent instance, fresh state).
    attachBargeInDetector({
      onsetConfidence: 0.80, offsetConfidence: 0.40,
      debounceFrames: 4, releaseFrames: 3,
      amplitudeFloorDb: -45, cooldownMs: 1000,
      onBargeIn: onBargeInB,
    });
    const hB = captured.handler!;
    expect(hB).not.toBe(hA);
    for (let i = 0; i < 4; i++) hB.onFrame(loudFrame(), 16000, 0.95);
    // B has no cooldown — fires.
    expect(onBargeInB).toHaveBeenCalledTimes(1);
  });

  it('honest-degrades when score is undefined (no fire, no throw)', () => {
    const onBargeIn = vi.fn();
    attachBargeInDetector({
      onsetConfidence: 0.80, offsetConfidence: 0.40,
      debounceFrames: 2, releaseFrames: 3,
      amplitudeFloorDb: -45, cooldownMs: 500,
      onBargeIn,
    });
    const h = captured.handler!;
    for (let i = 0; i < 10; i++) h.onFrame(loudFrame(), 16000, undefined);
    expect(onBargeIn).not.toHaveBeenCalled();
  });

  it('disarm detaches the subscriber', () => {
    const onBargeIn = vi.fn();
    const disarm = attachBargeInDetector({
      onsetConfidence: 0.80, offsetConfidence: 0.40,
      debounceFrames: 2, releaseFrames: 3,
      amplitudeFloorDb: -45, cooldownMs: 500,
      onBargeIn,
    });
    expect(captured.unsub).not.toHaveBeenCalled();
    disarm();
    expect(captured.unsub).toHaveBeenCalledTimes(1);
  });
});

describe('AD-760 bargeInDetector — RMS dBFS helper', () => {
  it('returns floor value for empty / silent frame', () => {
    expect(_rmsDbfs(new Float32Array(0))).toBeLessThanOrEqual(-100);
    expect(_rmsDbfs(new Float32Array(480))).toBeLessThanOrEqual(-100);
  });
  it('returns ~0 dBFS for full-scale frame', () => {
    const f = new Float32Array(480);
    for (let i = 0; i < f.length; i++) f[i] = 1.0;
    expect(_rmsDbfs(f)).toBeCloseTo(0, 1);
  });
  it('returns lower value for quieter frame', () => {
    const f = new Float32Array(480);
    for (let i = 0; i < f.length; i++) f[i] = 0.01;
    const db = _rmsDbfs(f);
    expect(db).toBeLessThan(-30);
    expect(db).toBeGreaterThan(-50);
  });
});
