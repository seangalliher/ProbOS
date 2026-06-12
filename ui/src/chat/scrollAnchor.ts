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
