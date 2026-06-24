export type EntryTarget = 'compact' | 'mobile' | 'desktop';

/** Pure entry-routing decision (AD-708b). Mirrors the `#compact` hash idiom and
 *  adds the AD-708b device gate + `#desktop` escape hatch / kill-switch.
 *  Precedence: compact (Electron tray) > `#desktop` escape > device gate.
 *  A desktop OR narrow-desktop client (isPad=false, no hash) resolves to
 *  'desktop' — byte-identical to the pre-AD-708b render path. */
export function resolveEntryTarget(hash: string, isPad: boolean): EntryTarget {
  const h = (hash ?? '').toLowerCase();
  if (h.includes('compact')) return 'compact';
  if (h.includes('desktop')) return 'desktop';
  return isPad ? 'mobile' : 'desktop';
}
