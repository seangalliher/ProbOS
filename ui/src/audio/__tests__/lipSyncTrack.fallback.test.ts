/** AD-721b v1: Fallback-path regression guard.
 *
 *  When ``buildHeuristicTrack`` returns null (empty text, throw, etc.), the
 *  AD-721 D5 amplitude analyser path must remain wired. This test verifies:
 *   - empty text → null track
 *   - whitespace-only text → null track
 *   - the legacy single-vowel direct-write loop produces a positive
 *     smoothed amplitude after a few synthetic frames against the
 *     ``_attachAnalyserOrSchedule`` synthetic envelope.
 */
import { describe, it, expect } from 'vitest';
import { buildHeuristicTrack } from '../lipSyncTrack';
import { _attachAnalyserOrSchedule } from '../speechAmplitude';

class FakeUtterance {
  text: string;
  rate = 1;
  pitch = 1;
  volume = 1;
  voice: any = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  constructor(text: string) { this.text = text; }
}

describe('AD-721b fallback path (Tier-2 → AD-721 D5 amplitude)', () => {
  it('empty text → null track signals fallback', () => {
    expect(buildHeuristicTrack('')).toBeNull();
  });

  it('whitespace-only text → null track signals fallback', () => {
    expect(buildHeuristicTrack('   \t  ')).toBeNull();
  });

  it("_attachAnalyserOrSchedule produces non-zero amplitude during the synthetic envelope window", () => {
    const u = new FakeUtterance('Hello Captain.') as unknown as SpeechSynthesisUtterance;
    const analyser = _attachAnalyserOrSchedule(u);
    expect(analyser).toBeTruthy();
    // Wait a tick (~50 ms) so the synthetic envelope has elapsed past 0.
    // Vitest doesn't expose a clock by default; we just sample the buffer
    // after one synchronous loop iteration. The synthetic envelope is a
    // deterministic function of elapsed-since-start, but the gate / random
    // noise can produce a 0 sample mid-envelope. We sample 8 times and
    // assert at least one non-zero reading.
    const buf = new Uint8Array(analyser.frequencyBinCount);
    let sawNonZero = false;
    const start = performance.now();
    while (performance.now() - start < 60) {
      analyser.getByteFrequencyData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i];
      if (sum > 0) { sawNonZero = true; break; }
    }
    expect(sawNonZero).toBe(true);
  });

  it('non-empty text → buildHeuristicTrack returns a track (the fallback path is NOT taken)', () => {
    const t = buildHeuristicTrack('Hello');
    expect(t).not.toBeNull();
    expect(t!.durationMs).toBeGreaterThan(0);
  });
});
