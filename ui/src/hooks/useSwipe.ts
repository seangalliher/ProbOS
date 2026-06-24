/* useSwipe — reusable, dependency-free horizontal swipe detector (AD-708d).
   Pure pointer start+end detection (no live drag): records the start point on
   pointer-down and, on pointer-up, fires onSwipeLeft / onSwipeRight only for a
   dominant-horizontal gesture (|dx| > |dy|) past `threshold`. Vertical-dominant
   gestures (chat scroll) and taps are ignored, and no preventDefault is called,
   so native scrolling is never blocked. Pointer events (not touch) keep this
   codebase-consistent (SpatialExplorerPanel uses onPointerDown/Up + e.clientX)
   and unit-testable with a minimal coord shape. NO emoji (HXI #3). */
import { useRef, useCallback } from 'react';

/** Minimal coord shape — a supertype of React.PointerEvent (which has clientX/
 *  clientY), so the returned handlers are assignable to onPointerDown/onPointerUp
 *  on a JSX element AND callable directly in unit tests with plain { clientX, clientY }. */
export interface SwipeCoords {
  readonly clientX: number;
  readonly clientY: number;
}

export interface UseSwipeOptions {
  readonly onSwipeLeft?: () => void;
  readonly onSwipeRight?: () => void;
  /** Minimum dominant-horizontal travel (px) to register a swipe. Default 50. */
  readonly threshold?: number;
}

export interface SwipeHandlers {
  readonly onPointerDown: (e: SwipeCoords) => void;
  readonly onPointerUp: (e: SwipeCoords) => void;
}

/** Reusable pointer-based horizontal swipe detector. Pure start+end detection
 *  (no live drag): records the start point on pointer-down and, on pointer-up,
 *  fires onSwipeLeft / onSwipeRight only for a dominant-horizontal gesture
 *  (|dx| > |dy|) past `threshold`. Vertical-dominant gestures (chat scroll) and
 *  taps are ignored. No preventDefault, so native scrolling is never blocked. */
export function useSwipe({ onSwipeLeft, onSwipeRight, threshold = 50 }: UseSwipeOptions): SwipeHandlers {
  const start = useRef<{ x: number; y: number } | null>(null);

  const onPointerDown = useCallback((e: SwipeCoords): void => {
    start.current = { x: e.clientX, y: e.clientY };
  }, []);

  const onPointerUp = useCallback((e: SwipeCoords): void => {
    const s = start.current;
    start.current = null;
    if (!s) return;
    const dx = e.clientX - s.x;
    const dy = e.clientY - s.y;
    if (Math.abs(dx) <= Math.abs(dy)) return;   // vertical-dominant -> ignore (scroll/tap)
    if (dx < -threshold) onSwipeLeft?.();
    else if (dx > threshold) onSwipeRight?.();
  }, [onSwipeLeft, onSwipeRight, threshold]);

  return { onPointerDown, onPointerUp };
}
