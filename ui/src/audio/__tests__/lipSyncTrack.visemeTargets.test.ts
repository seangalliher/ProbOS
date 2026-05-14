/** AD-738c (Wave 158): consonant residual visibility threshold.
 *  Snapshot test pinning the bumped residuals (0.25 / 0.20 / 0.30)
 *  above the perceptual visibility threshold (0.20). */
import { describe, it, expect } from 'vitest';
import { _VISEME_TARGETS } from '../lipSyncTrack';

describe('AD-738c: VISEME_TARGETS consonant residuals', () => {
  it('all consonant residuals are >= 0.20 (perceptual visibility threshold)', () => {
    const consonants = ['PP', 'FF', 'TH', 'DD', 'kk', 'SS', 'nn', 'RR', 'CH'] as const;
    for (const c of consonants) {
      const row = _VISEME_TARGETS[c];
      const maxResidual = Math.max(row.aa, row.ih, row.ou, row.ee, row.oh);
      expect(maxResidual, `${c} residual must be >= 0.20`).toBeGreaterThanOrEqual(0.20);
    }
  });
});
