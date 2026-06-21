/* usePrefersReducedMotion — OS-level "reduce motion" accessibility preference
   (AD-984b). Mirrors useBreakpoint.ts (pure getter + subscribing hook).

   HONEST-DEGRADE: when `window.matchMedia` is unavailable (jsdom/SSR), both the
   pure function and the hook return `false`. That default keeps the existing
   AD-923/AD-984 speaking-pulse animations ON (reducedMotion=false), so adding
   this hook does not change behavior in tests or environments without
   matchMedia — only an OS that actively requests reduced motion suppresses the
   pulse. */

import { useState, useEffect } from 'react';

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

/** Pure read of the OS reduced-motion preference. Returns false when matchMedia
 *  is absent or throws (jsdom/SSR honest-degrade). */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false;
  }
  try {
    return window.matchMedia(REDUCED_MOTION_QUERY).matches;
  } catch {
    return false;
  }
}

/** Subscribing hook: re-renders when the OS reduced-motion preference flips.
 *  Honest-degrades to a stable `false` when matchMedia is unavailable. */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(prefersReducedMotion());

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }
    let mql: MediaQueryList;
    try {
      mql = window.matchMedia(REDUCED_MOTION_QUERY);
    } catch {
      return;
    }
    const handler = (): void => setReduced(prefersReducedMotion());
    try {
      if (typeof mql.addEventListener === 'function') {
        mql.addEventListener('change', handler);
        return () => {
          try { mql.removeEventListener('change', handler); } catch { /* Tier-2 */ }
        };
      }
      // Old Safari (<14) fallback: deprecated addListener/removeListener.
      mql.addListener(handler);
      return () => {
        try { mql.removeListener(handler); } catch { /* Tier-2 */ }
      };
    } catch {
      return;
    }
  }, []);

  return reduced;
}
