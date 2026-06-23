/* usePadDevice — device-class predicate for the PADD mobile-companion
   experience (AD-708a, #484). Three exports: two pure getters
   (hasCoarsePointer, isPadDevice) plus a subscribing hook (usePadDevice).
   Mirrors usePrefersReducedMotion.ts (pure getter + subscribing hook) and
   composes AD-392 getBreakpoint for the width axis.

   A PADD is a real handheld: a COARSE primary pointer (touch) AND the 'mobile'
   viewport breakpoint. This is intentionally distinct from the width-only
   useBreakpoint — a narrow DESKTOP window (innerWidth <= 768 with a fine mouse
   pointer) is NOT a PADD and must keep the full desktop HXI. Routing on width
   alone would dump a desktop user who snaps a window narrow into the chat-only
   mobile projection (an untested-UI break the HXI has suffered before).

   This is the progressive-disclosure (HXI Design Principle #5) DEVICE gate:
   the later mobile shell (AD-708b) and gesture layer (AD-708d) route on it.

   HONEST-DEGRADE: when window.matchMedia is unavailable (jsdom/SSR) or throws,
   hasCoarsePointer returns false, so isPadDevice and usePadDevice return a
   stable false. That default keeps every client on the existing desktop HXI,
   so this primitive changes no behavior until something is wired to it. */

import { useState, useEffect } from 'react';
import { getBreakpoint } from './useBreakpoint';

const COARSE_POINTER_QUERY = '(pointer: coarse)';

/** Pure read of whether the primary pointer is coarse (touch). Returns false
 *  when matchMedia is absent or throws (jsdom/SSR honest-degrade). */
export function hasCoarsePointer(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false;
  }
  try {
    return window.matchMedia(COARSE_POINTER_QUERY).matches;
  } catch {
    return false;
  }
}

/** Pure device-class predicate: true only for a real handheld PADD — a coarse
 *  primary pointer AND the 'mobile' width breakpoint (composes AD-392). A
 *  narrow desktop window (fine pointer) is excluded by the pointer gate. */
export function isPadDevice(): boolean {
  return hasCoarsePointer() && getBreakpoint() === 'mobile';
}

/** Subscribing hook: re-renders when the device class flips. Re-evaluates on
 *  BOTH the window `resize` event (width axis) and the `(pointer: coarse)`
 *  MediaQueryList `change` event (pointer axis). Honest-degrades to a stable
 *  false when matchMedia is unavailable, and cleans up all listeners on
 *  unmount. */
export function usePadDevice(): boolean {
  const [isPad, setIsPad] = useState<boolean>(isPadDevice());

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }
    const handler = (): void => setIsPad(isPadDevice());

    // Width axis: window resize re-evaluates the breakpoint gate.
    window.addEventListener('resize', handler);

    // Pointer axis: subscribe to the (pointer: coarse) MediaQueryList change.
    let detachPointer: () => void = () => { /* no pointer listener attached */ };
    let mql: MediaQueryList | undefined;
    try {
      mql = window.matchMedia(COARSE_POINTER_QUERY);
    } catch {
      mql = undefined;
    }
    if (mql) {
      const pointerMql = mql;
      try {
        if (typeof pointerMql.addEventListener === 'function') {
          pointerMql.addEventListener('change', handler);
          detachPointer = () => {
            try { pointerMql.removeEventListener('change', handler); } catch { /* Tier-2 */ }
          };
        } else {
          // Old Safari (<14) fallback: deprecated addListener/removeListener.
          pointerMql.addListener(handler);
          detachPointer = () => {
            try { pointerMql.removeListener(handler); } catch { /* Tier-2 */ }
          };
        }
      } catch {
        detachPointer = () => { /* attach failed; nothing to detach */ };
      }
    }

    return () => {
      window.removeEventListener('resize', handler);
      detachPointer();
    };
  }, []);

  return isPad;
}
