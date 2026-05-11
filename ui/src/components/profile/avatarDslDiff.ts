/** AD-721d-1: shallow field-path diff between two AvatarDSL snapshots.
 *
 * Returns a Set of dotted paths whose values differ. The popout uses
 * this Set to apply amber-tint highlighting + strikethrough on the
 * previous value, per HXI Design Principle #4 (motion/state encoding).
 *
 * NOT a deep structural diff — we only inspect the fields surfaced
 * in the parametric description renderer.
 */
import type { AvatarDSLDict } from '../../store/types';

const FIELDS: ReadonlyArray<readonly [string, (d: AvatarDSLDict) => unknown]> = [
  ['body.type',           (d) => d.body?.type],
  ['body.height_cm',      (d) => d.body?.height_cm],
  ['hair.style',          (d) => d.hair?.style],
  ['hair.color_hsl',      (d) => JSON.stringify(d.hair?.color_hsl ?? null)],
  ['face.warmth',         (d) => d.face?.warmth],
  ['face.jaw',            (d) => d.face?.jaw],
  ['face.eyes',           (d) => d.face?.eyes],
  ['outfit.style',        (d) => d.outfit?.style],
  ['outfit.primary_color',(d) => d.outfit?.primary_color],
  ['expression_resting',  (d) => d.expression_resting],
  ['notes',               (d) => d.notes],
];

export function diffAvatarDsl(
  prev: AvatarDSLDict | null | undefined,
  curr: AvatarDSLDict,
): Set<string> {
  const changed = new Set<string>();
  if (!prev) return changed;
  for (const [path, get] of FIELDS) {
    if (get(prev) !== get(curr)) changed.add(path);
  }
  return changed;
}
