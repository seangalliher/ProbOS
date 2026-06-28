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

/** AD-1075: decide how the transcript should scroll when its message set
 *  changes. Pure + DOM-free so it is unit-testable.
 *
 *  - **Bulk load / context switch** (agent or thread changed, or more than one
 *    message appeared at once) → `jump` to the bottom instantly.
 *  - **One new incremental message** → `follow` smoothly to the bottom **iff**
 *    the Captain is already pinned to the bottom OR the new message is the
 *    Captain's own send (sending always follows your own message — the BF the
 *    Captain hit: a sent/received message left the view a little short).
 *  - **No change / empty** → do nothing.
 */
export function decideScrollOnUpdate(opts: {
  switched: boolean;
  prevCount: number;
  count: number;
  pinned: boolean;
  lastFromSelf: boolean;
}): ScrollDecision {
  const { switched, prevCount, count, pinned, lastFromSelf } = opts;
  if (count === 0) return { jump: false, follow: false };
  const isIncremental = !switched && count === prevCount + 1;
  if (isIncremental) {
    return { jump: false, follow: pinned || lastFromSelf };
  }
  return { jump: true, follow: false };
}
