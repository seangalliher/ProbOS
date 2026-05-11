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

/** AD-722-1: rule-table values come from ``./modulation_manifest.json`` —
 *  the single source of truth shared with ``src/probos/avatars/telemetry.py``.
 *  Vite + tsconfig (``moduleResolution: bundler``) handle JSON imports
 *  natively; no plugin, no new dependency. The Python loader validates
 *  the manifest schema at import; the TS side trusts that gate.
 *
 *  Public API (every exported name below) is unchanged — only the
 *  *source* of the values moved. Consumers do not need updating. */
import manifest from './modulation_manifest.json';

/** Threshold above which the modulation indicator (E5) treats the
 *  modulation as perceptible. Pitch / rate / volume that diverge >5%
 *  from baseline trigger the active state. */
export const MODULATION_DIVERGENCE_THRESHOLD: number =
  manifest.modulation_divergence_threshold;

/** Web Speech API + VoiceProfile validator bounds (single source of
 *  truth — same numbers on both sides). */
export const PITCH_BOUNDS: readonly [number, number] = [
  manifest.pitch_bounds[0], manifest.pitch_bounds[1],
];
export const RATE_BOUNDS: readonly [number, number] = [
  manifest.rate_bounds[0], manifest.rate_bounds[1],
];
export const VOLUME_BOUNDS: readonly [number, number] = [
  manifest.volume_bounds[0], manifest.volume_bounds[1],
];

/** Trust-delta thresholds (Captain-canonical, not magnitude-proportional). */
const TRUST_DELTA_HIGH: number = manifest.trust_delta_high;
const TRUST_DELTA_LOW: number = manifest.trust_delta_low;

/** Multiplicative factors per rule (small — modulation is perceptible
 *  but never overrides the agent's baseline character). */
const RESPONDING_RATE_FACTOR: number = manifest.responding_rate_factor;
const BLOCKED_RATE_FACTOR: number = manifest.blocked_rate_factor;
const BLOCKED_PITCH_FACTOR: number = manifest.blocked_pitch_factor;
const HIGH_TRUST_PITCH_FACTOR: number = manifest.high_trust_pitch_factor;
const LOW_TRUST_PITCH_FACTOR: number = manifest.low_trust_pitch_factor;
const TIER3_RATE_FACTOR: number = manifest.tier3_rate_factor;
const TIER3_VOLUME_FACTOR: number = manifest.tier3_volume_factor;

const DEFAULT_PITCH: number = manifest.default_pitch;
const DEFAULT_RATE: number = manifest.default_rate;
const DEFAULT_VOLUME: number = manifest.default_volume;

/** AD-722a-7: intent rule table -- byte-parity with
 *  ``src/probos/avatars/telemetry.py:INTENT_RULES``. Keyed by emotion;
 *  ``rule_name`` is the canonical fired-rule identifier. */
const INTENT_RULES: Record<
  string,
  { pitch: number; rate: number; volume: number; rule_name: string }
> = manifest.intent_rules;

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
 *   - AD-722a-7 ``intent`` (optional)    → ``intent_<name>`` factors from
 *     ``manifest.intent_rules``. Applied AFTER operational rules.
 *
 * Rules compose multiplicatively. Output is clamped to both Web Speech
 * API bounds and ``VoiceProfile`` validator bounds (same numbers).
 *
 * Pure function. Input is never mutated. ``voice_name`` passes through.
 */
export function applyEmotionalModulation(
  profile: VoiceProfile,
  signals: AgentSignals,
  intent?: string,
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

  // AD-722a-7: intent layering. Apply after operational rules; clamp
  // covers both stages. Unknown intent names are silently dropped --
  // the server-side parser (parse_intent_self_tag) is the boundary.
  if (intent !== undefined && intent !== null) {
    const rule = INTENT_RULES[intent];
    if (rule !== undefined) {
      pitch *= rule.pitch;
      rate *= rule.rate;
      volume *= rule.volume;
    }
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
