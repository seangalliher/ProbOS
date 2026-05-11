/** AD-718d E6: applyEmotionalModulation pure-function tests. */
import { describe, it, expect } from 'vitest';
import {
  MODULATION_DIVERGENCE_THRESHOLD,
  applyEmotionalModulation,
  hasMeaningfulModulation,
} from '../audio/voiceModulation';
import type { AgentSignals } from '../components/profile/avatarSignals';
import type { VoiceProfile } from '../audio/voice';

function baseline(overrides: Partial<VoiceProfile> = {}): VoiceProfile {
  return { voice_name: '', pitch: 1.0, rate: 1.0, volume: 1.0, ...overrides };
}

function signals(overrides: Partial<AgentSignals> = {}): AgentSignals {
  return {
    trust_delta: 0,
    load: 0,
    working_state: 'idle',
    tier3_alert: false,
    ...overrides,
  };
}

const FLOAT_TOL = 1e-9;

describe('AD-718d applyEmotionalModulation', () => {
  it('idle signals return baseline values', () => {
    const out = applyEmotionalModulation(baseline(), signals());
    expect(out.pitch).toBeCloseTo(1.0, 9);
    expect(out.rate).toBeCloseTo(1.0, 9);
    expect(out.volume).toBeCloseTo(1.0, 9);
    expect(out.voice_name).toBe('');
  });

  it("working_state 'responding' increases rate by 5%", () => {
    const out = applyEmotionalModulation(baseline(), signals({ working_state: 'responding' }));
    expect(out.rate).toBeCloseTo(1.05, 9);
    expect(out.pitch).toBeCloseTo(1.0, 9);
    expect(out.volume).toBeCloseTo(1.0, 9);
  });

  it("working_state 'blocked' lowers rate (×0.92) and pitch (×0.95)", () => {
    const out = applyEmotionalModulation(baseline(), signals({ working_state: 'blocked' }));
    expect(out.rate).toBeCloseTo(0.92, 9);
    expect(out.pitch).toBeCloseTo(0.95, 9);
    expect(out.volume).toBeCloseTo(1.0, 9);
  });

  it('trust_delta > 0.2 raises pitch by 3%', () => {
    const out = applyEmotionalModulation(baseline(), signals({ trust_delta: 0.3 }));
    expect(out.pitch).toBeCloseTo(1.03, 9);
  });

  it('trust_delta < -0.2 lowers pitch by 3%', () => {
    const out = applyEmotionalModulation(baseline(), signals({ trust_delta: -0.3 }));
    expect(out.pitch).toBeCloseTo(0.97, 9);
  });

  it('trust_delta within ±0.2 leaves pitch unchanged', () => {
    const out = applyEmotionalModulation(baseline(), signals({ trust_delta: 0.15 }));
    expect(out.pitch).toBeCloseTo(1.0, 9);
  });

  it('tier3_alert raises rate (×1.15) and volume (×1.05)', () => {
    const out = applyEmotionalModulation(baseline(), signals({ tier3_alert: true }));
    expect(out.rate).toBeCloseTo(1.15, 9);
    expect(out.volume).toBeCloseTo(1.0, 9);  // clamped at 1.0 from 1.05
  });

  it('rules compose multiplicatively', () => {
    const out = applyEmotionalModulation(
      baseline(),
      signals({ working_state: 'responding', tier3_alert: true }),
    );
    // rate composes 1.05 * 1.15 = 1.2075
    expect(out.rate).toBeCloseTo(1.05 * 1.15, 9);
  });

  it('clamps pitch upper bound at 2.0', () => {
    const out = applyEmotionalModulation(
      baseline({ pitch: 1.95 }),
      signals({ trust_delta: 0.5 }),
    );
    expect(out.pitch).toBeLessThanOrEqual(2.0);
    expect(out.pitch).toBeGreaterThan(1.99);  // saturated
  });

  it('clamps pitch lower bound at 0.0', () => {
    const out = applyEmotionalModulation(
      baseline({ pitch: 0.0 }),
      signals({ trust_delta: -0.5, working_state: 'blocked' }),
    );
    expect(out.pitch).toBeGreaterThanOrEqual(0.0);
  });

  it('clamps rate lower bound at 0.1', () => {
    const out = applyEmotionalModulation(
      baseline({ rate: 0.11 }),
      signals({ working_state: 'blocked' }),
    );
    expect(out.rate).toBeGreaterThanOrEqual(0.1);
  });

  it('clamps volume upper bound at 1.0', () => {
    const out = applyEmotionalModulation(
      baseline({ volume: 0.99 }),
      signals({ tier3_alert: true }),
    );
    expect(out.volume).toBeLessThanOrEqual(1.0);
  });

  it('does not mutate input profile', () => {
    const input = baseline({ pitch: 1.05, rate: 0.92, volume: 0.85 });
    const before = { ...input };
    applyEmotionalModulation(input, signals({ tier3_alert: true }));
    expect(input).toEqual(before);
  });

  it('passes voice_name through unchanged', () => {
    const out = applyEmotionalModulation(
      baseline({ voice_name: 'Aria' }),
      signals({ trust_delta: 0.3 }),
    );
    expect(out.voice_name).toBe('Aria');
  });

  it('counselor worked example: trust_delta=+0.3 working_state=responding', () => {
    // Counselor / Echo / Troi baseline.
    const counselor = baseline({ pitch: 1.05, rate: 0.92, volume: 0.85 });
    const out = applyEmotionalModulation(
      counselor,
      signals({ trust_delta: 0.3, working_state: 'responding' }),
    );
    // pitch ≈ 1.05 * 1.03 ≈ 1.0815
    expect(out.pitch).toBeCloseTo(1.05 * 1.03, 9);
    expect(out.pitch).toBeGreaterThan(1.08);
    expect(out.pitch).toBeLessThan(1.083);
    // rate ≈ 0.92 * 1.05 = 0.966
    expect(out.rate).toBeCloseTo(0.92 * 1.05, 9);
    expect(out.rate).toBeGreaterThan(0.965);
    expect(out.rate).toBeLessThan(0.967);
    expect(out.volume).toBeCloseTo(0.85, 9);
    // All within Web Speech API bounds.
    expect(out.pitch).toBeLessThanOrEqual(2.0);
    expect(out.pitch).toBeGreaterThanOrEqual(0.0);
    expect(out.rate).toBeLessThanOrEqual(10.0);
    expect(out.rate).toBeGreaterThanOrEqual(0.1);
  });
});

describe('AD-718d hasMeaningfulModulation', () => {
  it('returns false when modulated diverges below threshold', () => {
    const base = baseline();
    const mod = baseline({ pitch: 1.03 });  // 3% — below 5% threshold
    expect(hasMeaningfulModulation(base, mod)).toBe(false);
  });

  it('returns true when modulated diverges above threshold in any field', () => {
    const base = baseline();
    const mod = baseline({ rate: 1.06 });  // 6% — above 5% threshold
    expect(hasMeaningfulModulation(base, mod)).toBe(true);
  });

  it('exposes the divergence threshold constant', () => {
    expect(MODULATION_DIVERGENCE_THRESHOLD).toBe(0.05);
  });
});

// ─── AD-722a-7: intent-driven modulation ─────────────────────────────────

describe('AD-722a-7 applyEmotionalModulation intent layering', () => {
  it('intent=warm on idle baseline applies pitch ×1.04, rate ×0.98', () => {
    const out = applyEmotionalModulation(baseline(), signals(), 'warm');
    expect(out.pitch).toBeCloseTo(1.04, 6);
    expect(out.rate).toBeCloseTo(0.98, 6);
    expect(out.volume).toBeCloseTo(1.0, 6);
  });

  it('intent=concerned on idle baseline applies rate ×0.92 only', () => {
    const out = applyEmotionalModulation(baseline(), signals(), 'concerned');
    expect(out.pitch).toBeCloseTo(1.0, 6);
    expect(out.rate).toBeCloseTo(0.92, 6);
    expect(out.volume).toBeCloseTo(1.0, 6);
  });

  it('intent=excited on idle baseline applies pitch ×1.06, rate ×1.05', () => {
    const out = applyEmotionalModulation(baseline(), signals(), 'excited');
    expect(out.pitch).toBeCloseTo(1.06, 6);
    expect(out.rate).toBeCloseTo(1.05, 6);
    expect(out.volume).toBeCloseTo(1.0, 6);
  });

  it('intent=apologetic applies pitch ×0.96 and volume ×0.94', () => {
    const out = applyEmotionalModulation(baseline(), signals(), 'apologetic');
    expect(out.pitch).toBeCloseTo(0.96, 6);
    expect(out.rate).toBeCloseTo(1.0, 6);
    expect(out.volume).toBeCloseTo(0.94, 6);
  });

  it('intent=neutral leaves numeric output unchanged', () => {
    const ops = applyEmotionalModulation(baseline(), signals());
    const withNeutral = applyEmotionalModulation(baseline(), signals(), 'neutral');
    expect(withNeutral.pitch).toBeCloseTo(ops.pitch, 9);
    expect(withNeutral.rate).toBeCloseTo(ops.rate, 9);
    expect(withNeutral.volume).toBeCloseTo(ops.volume, 9);
  });

  it('intent layers multiplicatively on operational rules', () => {
    // responding (rate ×1.05) + excited (rate ×1.05) = 1.1025
    const out = applyEmotionalModulation(
      baseline(),
      signals({ working_state: 'responding' }),
      'excited',
    );
    expect(out.rate).toBeCloseTo(1.05 * 1.05, 9);
    expect(out.pitch).toBeCloseTo(1.06, 9);
  });

  it('unknown intent name is silently dropped', () => {
    const out = applyEmotionalModulation(baseline(), signals(), 'nonexistent');
    expect(out.pitch).toBeCloseTo(1.0, 9);
    expect(out.rate).toBeCloseTo(1.0, 9);
    expect(out.volume).toBeCloseTo(1.0, 9);
  });

  it('intent param undefined preserves pre-AD-722a-7 behavior', () => {
    const withoutIntent = applyEmotionalModulation(baseline(), signals({ working_state: 'responding' }));
    const explicitUndefined = applyEmotionalModulation(baseline(), signals({ working_state: 'responding' }), undefined);
    expect(explicitUndefined).toEqual(withoutIntent);
  });

  it('clamps composed pitch at upper bound 2.0', () => {
    const out = applyEmotionalModulation(
      baseline({ pitch: 1.9 }),
      signals({ trust_delta: 0.5 }),
      'excited',
    );
    expect(out.pitch).toBeLessThanOrEqual(2.0);
  });
});

// ─── AD-722a-7 §7: byte-parity with Python actuator ──────────────────────

import parityVectors from '../../../tests/fixtures/intent_parity_vectors.json';

interface ParityVector {
  intent: string;
  signals: {
    trust_delta: number;
    load: number;
    working_state: string;
    tier3_alert: boolean;
  };
  baseline: { pitch: number; rate: number; volume: number };
  expected: { pitch: number; rate: number; volume: number };
}

describe('AD-722a-7 byte-parity with Python actuator', () => {
  const vectors = parityVectors as ParityVector[];

  it('fixture has the expected 144 vectors', () => {
    expect(vectors.length).toBe(144);
  });

  it('every fixture vector matches the TS actuator to 6 decimal places', () => {
    for (const v of vectors) {
      const profile: VoiceProfile = {
        voice_name: '',
        pitch: v.baseline.pitch,
        rate: v.baseline.rate,
        volume: v.baseline.volume,
      };
      const sig: AgentSignals = {
        trust_delta: v.signals.trust_delta,
        load: v.signals.load,
        working_state: v.signals.working_state as AgentSignals['working_state'],
        tier3_alert: v.signals.tier3_alert,
      };
      const out = applyEmotionalModulation(profile, sig, v.intent);
      const ctx = `intent=${v.intent} ws=${v.signals.working_state} td=${v.signals.trust_delta} t3=${v.signals.tier3_alert}`;
      expect(out.pitch, `pitch ${ctx}`).toBeCloseTo(v.expected.pitch, 6);
      expect(out.rate, `rate ${ctx}`).toBeCloseTo(v.expected.rate, 6);
      expect(out.volume, `volume ${ctx}`).toBeCloseTo(v.expected.volume, 6);
    }
  });
});
