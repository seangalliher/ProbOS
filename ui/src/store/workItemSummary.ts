/* Issue #1375: the one selector for work-item counters (Board and Bridge) and the continuation origin.
 * Pure: records and status-bucket read metadata in, counts and labels out. */
import type { WorkItemView } from './types';
import {
  IDLE_SCOPE_META, WORK_ITEM_BUCKETS, bucketKey, isScaffoldWorkItem, workItemReadsStale,
  type WorkItemBucket, type WorkItemScopeMeta,
} from './workItemReconciliation';

export type WorkItemSummaryStatus = WorkItemBucket | 'unknown';

export interface WorkItemContinuationCounts {
  readonly total: number;
  readonly notDone: number;
  readonly failed: number;
}

export interface WorkItemSummary {
  /** One entry per status bucket, plus `unknown` for any status outside them. */
  readonly byStatus: Readonly<Record<WorkItemSummaryStatus, number>>;
  readonly total: number;
  /** Everything except done and cancelled, so failed, blocked and unknown statuses count here. */
  readonly notDone: number;
  readonly failed: number;
  readonly blocked: number;
  readonly cancelled: number;
  readonly done: number;
  /** Conversation continuations (DM promotions) among the counted items. */
  readonly continuations: WorkItemContinuationCounts;
  /** Every status bucket has been read, and none refused access. */
  readonly loaded: boolean;
  /** Loaded, current and untruncated: every count is exact. */
  readonly complete: boolean;
  /** Some bucket hit its cap, so a count covering that status is a lower bound. */
  readonly truncated: boolean;
  /** Some bucket is outdated (its refresh failed, or the stream lost continuity unread), or some by-ID read failed. */
  readonly stale: boolean;
  readonly truncatedStatuses: ReadonlySet<WorkItemBucket>;
}

export type WorkItemCountKey = 'total' | 'notDone' | 'failed' | 'blocked' | 'cancelled' | 'done';

export type WorkItemOrigin = 'continuation' | 'delegated';

// turn_promotion.py PROMOTION_SOURCE.
const CONTINUATION_SOURCE = 'dm_agentic_promotion';

const BUCKET_STATUSES: ReadonlySet<string> = new Set(WORK_ITEM_BUCKETS);

// The buckets whose truncation makes each count a lower bound.
const COUNT_BUCKETS: Readonly<Record<WorkItemCountKey, readonly WorkItemBucket[]>> = {
  total: WORK_ITEM_BUCKETS,
  notDone: WORK_ITEM_BUCKETS.filter(status => status !== 'done' && status !== 'cancelled'),
  failed: ['failed'],
  blocked: ['blocked'],
  cancelled: ['cancelled'],
  done: ['done'],
};

function isClosed(status: WorkItemSummaryStatus): boolean {
  return status === 'done' || status === 'cancelled';
}

/** Presentation only (H9): anyone who creates an item can set `metadata.source`, so it never grants or hides anything. */
export function workItemOrigin(item: WorkItemView): WorkItemOrigin {
  return item.metadata.source === CONTINUATION_SOURCE ? 'continuation' : 'delegated';
}

/** Counts `items` by status, leaving scaffold rows out (I6), with the load state of the status-bucket reads. */
export function summarizeWorkItems(
  items: readonly WorkItemView[],
  scopes: ReadonlyMap<string, WorkItemScopeMeta>,
): WorkItemSummary {
  const byStatus = Object.fromEntries(
    [...WORK_ITEM_BUCKETS, 'unknown'].map(status => [status, 0]),
  ) as Record<WorkItemSummaryStatus, number>;
  const continuations = { total: 0, notDone: 0, failed: 0 };
  let total = 0;
  for (const item of items) {
    if (isScaffoldWorkItem(item)) continue;
    const status = BUCKET_STATUSES.has(item.status) ? item.status as WorkItemBucket : 'unknown';
    byStatus[status] += 1;
    total += 1;
    if (workItemOrigin(item) !== 'continuation') continue;
    continuations.total += 1;
    if (!isClosed(status)) continuations.notDone += 1;
    if (status === 'failed') continuations.failed += 1;
  }
  const metas = WORK_ITEM_BUCKETS.map(status => [status, scopes.get(bucketKey(status)) ?? IDLE_SCOPE_META] as const);
  const loaded = metas.every(([, meta]) => meta.populated && meta.status !== 'unauthorized');
  const stale = metas.some(([, meta]) => meta.stale) || workItemReadsStale(scopes);
  const truncatedStatuses: ReadonlySet<WorkItemBucket> = new Set(
    metas.filter(([, meta]) => meta.truncated).map(([status]) => status),
  );
  return {
    byStatus,
    total,
    notDone: total - byStatus.done - byStatus.cancelled,
    failed: byStatus.failed,
    blocked: byStatus.blocked,
    cancelled: byStatus.cancelled,
    done: byStatus.done,
    continuations,
    loaded,
    complete: loaded && !stale && truncatedStatuses.size === 0,
    truncated: truncatedStatuses.size > 0,
    stale,
    truncatedStatuses,
  };
}

/** `12`, `100+` when a bucket the count covers hit its cap, `12 (last known)` when stale, `unknown` before every bucket is read. */
export function formatWorkItemCount(
  summary: WorkItemSummary,
  key: WorkItemCountKey,
  count: number = summary[key],
): string {
  if (!summary.loaded) return 'unknown';
  const lowerBound = COUNT_BUCKETS[key].some(status => summary.truncatedStatuses.has(status));
  return `${count}${lowerBound ? '+' : ''}${summary.stale ? ' (last known)' : ''}`;
}
