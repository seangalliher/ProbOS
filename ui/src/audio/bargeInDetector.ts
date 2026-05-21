/**
 * AD-760 — Schmitt-trigger barge-in detector.
 *
 * Watches the Silero VAD probability stream (forwarded by
 * ``voiceActivity.subscribePcm`` as the third arg to ``onFrame``) and
 * fires ``onBargeIn`` when the operator interrupts the agent's TTS
 * playback. Uses hysteresis (separate onset/offset thresholds) +
 * sustained-frame debouncing + amplitude floor + per-detector
 * cooldown to suppress false positives from TTS bleed, HVAC, and
 * brief throat noises.
 *
 * Per-detector-instance cooldown is load-bearing — switching agents
 * during a cancelled-onset cooldown must not carry suppression across
 * controllers. (Verified by the cross-detector independence test.)
 */

import { subscribePcm, type PcmTapHandler } from './voiceActivity';

export interface BargeInOptions {
  /** Silero probability above which a frame counts toward onset. */
  onsetConfidence: number;
  /** Silero probability below which a frame counts toward release. */
  offsetConfidence: number;
  /** Sustained-onset frame count needed to fire ``onBargeIn``. */
  debounceFrames: number;
  /** Release frame count needed to return to ``below`` once ``above``. */
  releaseFrames: number;
  /** RMS dBFS floor — frames below this never count toward onset. */
  amplitudeFloorDb: number;
  /** Suppression window after a cancelled onset (ms). Per-instance. */
  cooldownMs: number;
  /** Fires once per onset transition (``below`` → ``above``). */
  onBargeIn: () => void;
}

interface InternalState {
  phase: 'below' | 'above';
  onsetCount: number;
  releaseCount: number;
  cooldownUntil: number; // ms epoch; 0 = no cooldown
  unsub: (() => void) | null;
}

const SILENCE_DBFS = -120;

/** Compute RMS dBFS for a Float32 PCM frame. Empty / silent frames
 *  return -120 dBFS as a stand-in for ``-Infinity`` so callers can
 *  safely compare against ``amplitudeFloorDb``. */
export function _rmsDbfs(frame: Float32Array): number {
  if (frame.length === 0) return SILENCE_DBFS;
  let sumSq = 0;
  for (let i = 0; i < frame.length; i++) {
    const s = frame[i];
    sumSq += s * s;
  }
  const rms = Math.sqrt(sumSq / frame.length);
  if (rms <= 0) return SILENCE_DBFS;
  return 20 * Math.log10(rms);
}

/**
 * Attach a Schmitt-trigger barge-in detector to the voice-activity
 * PCM tap. Returns a disarm function that detaches the detector and
 * clears its cooldown.
 *
 * Detector instance state is fully local — two simultaneously-armed
 * detectors share no module-global suppression state.
 */
export function attachBargeInDetector(opts: BargeInOptions): () => void {
  const state: InternalState = {
    phase: 'below',
    onsetCount: 0,
    releaseCount: 0,
    cooldownUntil: 0,
    unsub: null,
  };

  const handler: PcmTapHandler = {
    onFrame: (frame: Float32Array, _sr: number, score?: number): void => {
      // Score is the load-bearing signal. If voiceActivity didn't
      // forward it (e.g. pre-AD-760 worklet path), honest-degrade by
      // doing nothing — the controller still has the manual stop
      // affordance.
      if (typeof score !== 'number') return;

      const now = Date.now();
      if (now < state.cooldownUntil) {
        // Suppression window after a cancelled onset.
        return;
      }

      if (state.phase === 'below') {
        // Amplitude floor guards against high-score low-RMS frames
        // (steady noise, fan, HVAC).
        const db = _rmsDbfs(frame);
        if (db < opts.amplitudeFloorDb) {
          // Cancel any partial onset that was building.
          if (state.onsetCount > 0) {
            state.onsetCount = 0;
            state.cooldownUntil = now + opts.cooldownMs;
          }
          return;
        }
        if (score >= opts.onsetConfidence) {
          state.onsetCount += 1;
          if (state.onsetCount >= opts.debounceFrames) {
            state.phase = 'above';
            state.onsetCount = 0;
            state.releaseCount = 0;
            try { opts.onBargeIn(); } catch { /* Tier-2 */ }
          }
        } else if (state.onsetCount > 0) {
          // Probability dropped before sustained-onset completed —
          // cancel and enter cooldown.
          state.onsetCount = 0;
          state.cooldownUntil = now + opts.cooldownMs;
        }
      } else {
        // phase === 'above'
        if (score < opts.offsetConfidence) {
          state.releaseCount += 1;
          if (state.releaseCount >= opts.releaseFrames) {
            state.phase = 'below';
            state.releaseCount = 0;
            state.onsetCount = 0;
          }
        } else {
          state.releaseCount = 0;
        }
      }
    },
  };

  state.unsub = subscribePcm(handler);
  return (): void => {
    if (state.unsub) {
      try { state.unsub(); } catch { /* Tier-2 */ }
      state.unsub = null;
    }
    state.phase = 'below';
    state.onsetCount = 0;
    state.releaseCount = 0;
    state.cooldownUntil = 0;
  };
}
