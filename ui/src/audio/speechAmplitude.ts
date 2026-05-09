/** AD-721 D5: Audio amplitude provider for VRM mouth animation.
 *
 * Browsers ship SpeechSynthesis without a routable audio graph by default,
 * so v1 falls back to a synthetic amplitude curve derived from the
 * utterance text length and rate. Phoneme-accurate / real-audio capture
 * is the AD-721b forward marker.
 */

/** Minimum AnalyserNode shape used by the mouth-animation tick. */
export interface FakeAnalyser {
  frequencyBinCount: number;
  getByteFrequencyData(buf: Uint8Array): void;
}

/** Returns a real AnalyserNode if the browser can route SpeechSynthesis through
 *  Web Audio (rare today), otherwise a synthetic FakeAnalyser that pretends.
 *  Tier-2 log-and-degrade: a missing audio context falls back to the synthetic
 *  curve rather than failing. */
export function _attachAnalyserOrSchedule(
  utterance: SpeechSynthesisUtterance,
): AnalyserNode | FakeAnalyser {
  // 1) Real-audio capture path is left for AD-721b — most browsers today
  //    do not let JavaScript route SpeechSynthesis through MediaStreamDestination.
  // 2) Synthetic fallback (default in Chromium/Firefox today):
  const text = utterance.text ?? '';
  const rate = utterance.rate || 0.95;
  // Heuristic duration: ~5 chars/word, ~3 words/sec at rate=1.
  const durationMs = Math.max(400, (text.length / 5) * (1000 / 3) / rate);
  const startedAt = (typeof performance !== 'undefined' ? performance.now() : Date.now());
  const binCount = 32;

  return {
    frequencyBinCount: binCount,
    getByteFrequencyData(buf: Uint8Array): void {
      const now = (typeof performance !== 'undefined' ? performance.now() : Date.now());
      const elapsed = now - startedAt;
      if (elapsed > durationMs) { buf.fill(0); return; }
      // Sine envelope at ~6 Hz (syllable cadence) modulated by mild noise.
      const t = elapsed / 1000;
      const envelope = 0.5 + 0.4 * Math.sin(2 * Math.PI * 6 * t);
      for (let i = 0; i < binCount; i++) {
        const noise = Math.random() * 0.2;
        buf[i] = Math.min(255, Math.floor((envelope + noise) * 200));
      }
    },
  };
}
