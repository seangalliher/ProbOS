/*
 * AD-792 (Wave 195) — Time-of-life grouping helper for the ThreadSidebar
 * Recents section. Pure function, no React/store dependencies, so it can
 * be exercised by a focused vitest without a DOM.
 *
 * The Recents list is bucketed Today / Yesterday / Earlier relative to
 * the operator's local midnight boundary. Threads carry
 * ``last_active_at`` as a UNIX seconds timestamp on the server (see
 * ``ChatThread.to_dict`` in ``src/probos/persistence/chat_threads.py``).
 * The helper accepts seconds and converts to ms internally so callers
 * don't have to pre-multiply.
 */

export type TimeOfLifeGroup = 'today' | 'yesterday' | 'earlier';

/**
 * Bucket a thread's ``last_active_at`` (UNIX seconds) into one of the
 * three Recents groups. ``now`` is supplied so tests can pin a fixed
 * reference instant without mocking ``Date.now()`` globally.
 */
export function timeOfLifeGroup(lastActiveAtSec: number, nowMs: number): TimeOfLifeGroup {
  const lastActiveMs = lastActiveAtSec * 1000;
  const dayMs = 86_400_000;
  const startOfToday = new Date(nowMs).setHours(0, 0, 0, 0);
  const startOfYesterday = startOfToday - dayMs;
  if (lastActiveMs >= startOfToday) return 'today';
  if (lastActiveMs >= startOfYesterday) return 'yesterday';
  return 'earlier';
}

export const TIME_OF_LIFE_LABELS: Record<TimeOfLifeGroup, string> = {
  today: 'Today',
  yesterday: 'Yesterday',
  earlier: 'Earlier',
};
