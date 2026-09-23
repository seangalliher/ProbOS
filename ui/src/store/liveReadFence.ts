/* Issue #1375: per-key issue-stamp fence for live REST reads, on one logical clock.
 * Importless so test setup can reset it without pre-empting a test file's vi.mock hoisting. */

export interface LiveReadFence {
  /** Changes only on reset; a consumer discards any read begun in an older session. */
  readonly session: number;
  /** Stamps a read as issued now. */
  begin(): number;
  /** Records that the live stream reported a change to `key` now, and returns that stamp. */
  observe(key: string): number;
  /** Records a stream discontinuity that makes every earlier work-item read, by ID or scope, suspect. */
  observeItemEpoch(): void;
  /** I2: whether a read of `key` issued at `issuedAt` may be applied. */
  accepts(key: string, issuedAt: number): boolean;
  /** Records that a read of `key` issued at `issuedAt` was applied. */
  markApplied(key: string, issuedAt: number): void;
  /** Number of keys that still retain a stamp. */
  trackedKeyCount(): number;
}

// Work-item reads, by ID (`item:`) and by scope (`scope:`), are the keys the item epoch fences.
const ITEM_EPOCH_PREFIXES = ['item:', 'scope:'];

let clock = 0;
let session = 0;
let sessionStartedAt = 0;
let itemEpochAt = 0;
const observedAt = new Map<string, number>();
const appliedAt = new Map<string, number>();

function stamp(): number {
  clock += 1;
  return clock;
}

function isItemEpochKey(key: string): boolean {
  return ITEM_EPOCH_PREFIXES.some(prefix => key.startsWith(prefix));
}

function dropItemEntries(entries: Map<string, number>): void {
  for (const key of [...entries.keys()]) {
    if (isItemEpochKey(key)) entries.delete(key);
  }
}

export const liveReadFence: LiveReadFence = {
  get session(): number {
    return session;
  },
  begin(): number {
    return stamp();
  },
  observe(key: string): number {
    const observed = stamp();
    observedAt.set(key, observed);
    return observed;
  },
  observeItemEpoch(): void {
    itemEpochAt = stamp();
    // The epoch now dominates every earlier item and scope stamp.
    dropItemEntries(observedAt);
    dropItemEntries(appliedAt);
  },
  accepts(key: string, issuedAt: number): boolean {
    if (issuedAt <= sessionStartedAt) return false;
    if (issuedAt <= (observedAt.get(key) ?? 0) || issuedAt <= (appliedAt.get(key) ?? 0)) return false;
    return !isItemEpochKey(key) || issuedAt > itemEpochAt;
  },
  markApplied(key: string, issuedAt: number): void {
    if (issuedAt <= (appliedAt.get(key) ?? 0)) return;
    appliedAt.set(key, issuedAt);
    if ((observedAt.get(key) ?? 0) < issuedAt) observedAt.delete(key);
  },
  trackedKeyCount(): number {
    return new Set([...observedAt.keys(), ...appliedAt.keys()]).size;
  },
};

export function resetLiveReadFenceForTests(): void {
  session += 1;
  sessionStartedAt = stamp();
  itemEpochAt = 0;
  observedAt.clear();
  appliedAt.clear();
}
