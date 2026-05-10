/** AD-718d: Pure-function emotional voice modulation.
 *
 * Reads ``AgentSignals`` (the same selector-derived channel that feeds the
 * VRM expression layer) and produces a modulated ``VoiceProfile`` clamped
 * to Web Speech API bounds. No DOM access, no store access, no side
 * effects — call sites resolve signals and pass them in.
 *
 * Voice + avatar align by sourcing the same signal contract.
 */

import type { VoiceProfile } from './voice';
import type { AgentSignals } from '../components/profile/avatarSignals';

/** Threshold above which the modulation indicator (E5) treats the
 *  modulation as perceptible. Pitch / rate / volume that diverge >5%
 *  from baseline trigger the active state. */
// NOTE: this rule table is duplicated in src/probos/avatars/telemetry.py.
// Keep them in lockstep — byte-parity is enforced by a Python test that
// file-reads this source. AD-722-1 will extract to a YAML manifest.
export const MODULATION_DIVERGENCE_THRESHOLD = 0.05;

/** Web Speech API + VoiceProfile validator bounds (single source of
 *  truth — same numbers on both sides). */
export const PITCH_BOUNDS: readonly [number, number] = [0, 2];
export const RATE_BOUNDS: readonly [number, number] = [0.1, 10];
export const VOLUME_BOUNDS: readonly [number, number] = [0, 1];

/** Trust-delta thresholds (Captain-canonical, not magnitude-proportional). */
const TRUST_DELTA_HIGH = 0.2;
const TRUST_DELTA_LOW = -0.2;

/** Multiplicative factors per rule (small — modulation is perceptible
 *  but never overrides the agent's baseline character). */
const RESPONDING_RATE_FACTOR = 1.05;
const BLOCKED_RATE_FACTOR = 0.92;
const BLOCKED_PITCH_FACTOR = 0.95;
const HIGH_TRUST_PITCH_FACTOR = 1.03;
const LOW_TRUST_PITCH_FACTOR = 0.97;
const TIER3_RATE_FACTOR = 1.15;
const TIER3_VOLUME_FACTOR = 1.05;

const DEFAULT_PITCH = 0.9;
const DEFAULT_RATE = 0.95;
const DEFAULT_VOLUME = 0.8;

function clamp(value: number, bounds: readonly [number, number]): number {
  return Math.max(bounds[0], Math.min(bounds[1], value));
}

/**
 * Apply emotional modulation to a baseline ``VoiceProfile``.
 *
 * Rules (per Captain-canonical modulation table):
 *   - ``working_state === 'responding'`` → rate × 1.05
 *   - ``working_state === 'blocked'``    → rate × 0.92, pitch × 0.95
 *   - ``trust_delta > 0.2``              → pitch × 1.03
 *   - ``trust_delta < -0.2``             → pitch × 0.97
 *   - ``tier3_alert``                    → rate × 1.15, volume × 1.05
 *
 * Rules compose multiplicatively. Output is clamped to both Web Speech
 * API bounds and ``VoiceProfile`` validator bounds (same numbers).
 *
 * Pure function. Input is never mutated. ``voice_name`` passes through.
 */
export function applyEmotionalModulation(
  profile: VoiceProfile,
  signals: AgentSignals,
): VoiceProfile {
  const basePitch = profile.pitch ?? DEFAULT_PITCH;
  const baseRate = profile.rate ?? DEFAULT_RATE;
  const baseVolume = profile.volume ?? DEFAULT_VOLUME;

  let pitch = basePitch;
  let rate = baseRate;
  let volume = baseVolume;

  if (signals.working_state === 'responding') {
    rate *= RESPONDING_RATE_FACTOR;
  } else if (signals.working_state === 'blocked') {
    rate *= BLOCKED_RATE_FACTOR;
    pitch *= BLOCKED_PITCH_FACTOR;
  }

  if (signals.trust_delta > TRUST_DELTA_HIGH) {
    pitch *= HIGH_TRUST_PITCH_FACTOR;
  } else if (signals.trust_delta < TRUST_DELTA_LOW) {
    pitch *= LOW_TRUST_PITCH_FACTOR;
  }

  if (signals.tier3_alert) {
    rate *= TIER3_RATE_FACTOR;
    volume *= TIER3_VOLUME_FACTOR;
  }

  return {
    voice_name: profile.voice_name,
    pitch: clamp(pitch, PITCH_BOUNDS),
    rate: clamp(rate, RATE_BOUNDS),
    volume: clamp(volume, VOLUME_BOUNDS),
  };
}

/**
 * Returns ``true`` iff the modulated profile diverges from the baseline
 * by more than ``MODULATION_DIVERGENCE_THRESHOLD`` (5%) in pitch, rate,
 * or volume. Drives the modulation indicator (E5).
 *
 * Treats a zero baseline as "always meaningful" if modulated is non-zero
 * (guards against division-by-zero on pathological baselines).
 */
export function hasMeaningfulModulation(
  baseline: VoiceProfile,
  modulated: VoiceProfile,
): boolean {
  const pairs: Array<[number | undefined, number | undefined, number]> = [
    [baseline.pitch, modulated.pitch, DEFAULT_PITCH],
    [baseline.rate, modulated.rate, DEFAULT_RATE],
    [baseline.volume, modulated.volume, DEFAULT_VOLUME],
  ];
  for (const [b, m, fallback] of pairs) {
    const baseVal = b ?? fallback;
    const modVal = m ?? fallback;
    if (baseVal === 0) {
      if (modVal !== 0) return true;
      continue;
    }
    const ratio = Math.abs(modVal - baseVal) / Math.abs(baseVal);
    if (ratio > MODULATION_DIVERGENCE_THRESHOLD) return true;
  }
  return false;
}
