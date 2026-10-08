/** BF-888 (#1367): where the detached avatar popout opens.
 *
 *  The popout's home is the viewport's bottom-right corner. On a narrow viewport that corner holds the
 *  chat composer (message input, voice and Send), and the popout opened over it. The owner names a region
 *  the popout must not cover; when the home rectangle would cover it, the popout opens on the side of that
 *  region, above or below, with more room, shorter only when that side cannot hold its full height.
 *  Pure: no DOM access, so it is tested without a layout engine. */

export interface PopoutRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** A region the opening placement must not cover. A DOMRect satisfies it. */
export interface KeepClearRect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/** Inset of the home rectangle from the viewport's right and bottom edges. */
const POPOUT_EDGE_INSET = 24;
/** Space left between the popout and the region it keeps clear. */
export const KEEP_CLEAR_GAP = 8;
/** The popout's title bar (22px in CrewAvatarPopout): a shorter popout has no drag handle or close button. */
const POPOUT_TITLE_BAR_H = 22;

/** True when `rect` names a region to keep clear: it has area. The rect of a hidden or unmounted element
 *  (all zeros) does not. */
export function isKeepClearRegion(rect: KeepClearRect | null): rect is KeepClearRect {
  return rect !== null && rect.right > rect.left && rect.bottom > rect.top;
}

function covers(popout: PopoutRect, rect: KeepClearRect): boolean {
  return popout.x < rect.right && rect.left < popout.x + popout.w
    && popout.y < rect.bottom && rect.top < popout.y + popout.h;
}

/** The rectangle the popout opens at: its home, unless the home covers `keepClear`. A region with no area
 *  keeps nothing clear, and when neither side of the region has room for the title bar the home stands. */
export function avatarPopoutOpeningRect(
  viewport: { w: number; h: number },
  size: { w: number; h: number },
  keepClear: KeepClearRect | null,
): PopoutRect {
  const home: PopoutRect = {
    x: Math.max(0, viewport.w - size.w - POPOUT_EDGE_INSET),
    y: Math.max(0, viewport.h - size.h - POPOUT_EDGE_INSET),
    w: size.w,
    h: size.h,
  };
  if (!isKeepClearRegion(keepClear) || !covers(home, keepClear)) return home;
  const roomAbove = keepClear.top - KEEP_CLEAR_GAP;
  const roomBelow = viewport.h - keepClear.bottom - KEEP_CLEAR_GAP;
  const room = Math.max(roomAbove, roomBelow);
  if (room < POPOUT_TITLE_BAR_H) return home;
  const h = Math.min(size.h, room);
  const y = roomAbove >= roomBelow ? roomAbove - h : keepClear.bottom + KEEP_CLEAR_GAP;
  return { x: home.x, y, w: size.w, h };
}

/** BF-888 A-1 (#1367): where a popout that opened before its keep-clear region existed -- another tab was
 *  showing -- goes once the region appears: null while `current` does not cover it, else its opening rectangle. */
export function avatarPopoutLateRect(
  current: PopoutRect,
  viewport: { w: number; h: number },
  size: { w: number; h: number },
  keepClear: KeepClearRect,
): PopoutRect | null {
  return covers(current, keepClear) ? avatarPopoutOpeningRect(viewport, size, keepClear) : null;
}
