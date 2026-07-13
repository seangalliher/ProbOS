/** AD-984c: interruptible auto-scroll for the chat transcript.
 *
 *  Auto-scroll-to-latest is the right default, but it must not yank the Captain
 *  back to the bottom while they have scrolled up to re-read an earlier turn
 *  (the standard chat-log pattern). This pure helper answers "is the scroll
 *  container currently pinned to the bottom?" so the caller can auto-scroll
 *  ONLY when pinned. Pure + DI-friendly so it is unit-testable without a DOM.
 */

/** Minimal shape of the scroll metrics we read — a real `HTMLElement` satisfies
 *  it, and tests can pass a plain object. */
export interface ScrollMetrics {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}

/** Distance (px) from the bottom within which we still consider the view
 *  "pinned" — a small tolerance absorbs sub-pixel rounding and the in-progress
 *  smooth-scroll so a steady reader at the bottom keeps auto-following. */
export const PIN_THRESHOLD_PX = 80;

/** True when the container is scrolled to (or within `threshold` px of) the
 *  bottom. A container that doesn't overflow (scrollHeight <= clientHeight) is
 *  trivially pinned. Pure. */
export function isPinnedToBottom(
  el: ScrollMetrics | null | undefined,
  threshold: number = PIN_THRESHOLD_PX,
): boolean {
  if (!el) return true;
  const { scrollTop, scrollHeight, clientHeight } = el;
  if (scrollHeight <= clientHeight) return true;
  const distanceFromBottom = scrollHeight - clientHeight - scrollTop;
  return distanceFromBottom <= threshold;
}

/** AD-1075: the scroll action for a transcript update. */
export interface ScrollDecision {
  /** Snap to the bottom with NO animation (bulk load / context switch). */
  jump: boolean;
  /** Smooth-follow to the bottom (an incremental message we should track). */
  follow: boolean;
}

/** BF-664: the observed transition metadata needed by the scroll policy. */
export interface ScrollUpdate {
  switched: boolean;
  remounted: boolean;
  prevCount: number;
  count: number;
  prevTailId: string | null;
  tailId: string | null;
  previousTailContinues: boolean;
  pinned: boolean;
  lastFromSelf: boolean;
}

/** AD-1075 / BF-664: decide how the transcript should scroll when its message
 *  set changes. Pure + DOM-free so it is unit-testable.
 *
 *  - **Bulk load / replacement / context switch / transcript remount** →
 *    `jump` to the bottom instantly.
 *  - **Incremental message** means the tail changed and the previous tail is
 *    now its immediate predecessor. This includes both ordinary +1 appends and
 *    bounded equal-count appends. Follow smoothly iff pinned or Captain-authored.
 *  - **Same count + unrelated changed tail** is a replacement, not an append.
 *  - **Same count + same tail / empty** → do nothing.
 */
export function decideScrollOnUpdate(opts: ScrollUpdate): ScrollDecision {
  const {
    switched, remounted, prevCount, count, prevTailId, tailId,
    previousTailContinues, pinned, lastFromSelf,
  } = opts;
  if (count === 0) return { jump: false, follow: false };
  if (switched || remounted) return { jump: true, follow: false };
  if (count === prevCount && tailId === prevTailId) {
    return { jump: false, follow: false };
  }
  const tailChanged = prevTailId !== null && tailId !== null && tailId !== prevTailId;
  const isIncremental = tailChanged
    && previousTailContinues
    && (count === prevCount + 1 || count === prevCount);
  if (isIncremental) {
    return { jump: false, follow: pinned || lastFromSelf };
  }
  return { jump: true, follow: false };
}
