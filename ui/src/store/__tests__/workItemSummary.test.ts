/** Issue #1375 M5: the one work-item counter selector, its identities, the origin rule and the count labels. */
import { describe, expect, it } from 'vitest';

import type { WorkItemView } from '../types';
import {
  ITEM_READS_KEY, WORK_ITEM_BUCKETS, bucketKey, type WorkItemBucket, type WorkItemScopeMeta,
} from '../workItemReconciliation';
import { formatWorkItemCount, summarizeWorkItems, workItemOrigin } from '../workItemSummary';

function record(id: string, status: string, overrides: Partial<WorkItemView> = {}): WorkItemView {
  return {
    id, title: `Work ${id}`, description: '', work_type: 'task', status, priority: 3,
    parent_id: null, project_id: null, depends_on: [], assigned_to: null, created_by: 'captain',
    created_at: 1, updated_at: 1, due_at: null, estimated_tokens: 0, actual_tokens: 0,
    trust_requirement: 0, required_capabilities: [], tags: [], metadata: {}, steps: [],
    verification: null, schedule: null, ttl_seconds: null, template_id: null, ...overrides,
  };
}

// turn_promotion.py _create_promoted_work_item: the shape of a promoted DM turn.
function continuation(id: string, status: string): WorkItemView {
  return record(id, status, {
    created_by: 'captain', assigned_to: 'agent-a', tags: ['conversational-turn'],
    metadata: { source: 'dm_agentic_promotion', thread_id: 'dm-thread', agent_id: 'agent-a' },
  });
}

function delegated(id: string, status: string): WorkItemView {
  return record(id, status, { created_by: 'captain', assigned_to: 'agent-a' });
}

const READ: WorkItemScopeMeta = { status: 'ready', truncated: false, observedAt: 1, populated: true, stale: false };

/** Every status bucket read once, with per-bucket overrides. */
function scopes(
  overrides: Partial<Record<WorkItemBucket, Partial<WorkItemScopeMeta>>> = {},
): ReadonlyMap<string, WorkItemScopeMeta> {
  return new Map(WORK_ITEM_BUCKETS.map(status => [bucketKey(status), { ...READ, ...overrides[status] }]));
}

// The Board's columns hold these statuses; every other status is its Blocked/Failed row.
const BOARD_COLUMN_STATUSES = ['draft', 'open', 'scheduled', 'in_progress', 'review', 'done'] as const;

const POPULATION: readonly WorkItemView[] = [
  record('draft-1', 'draft'), record('open-1', 'open'), record('scheduled-1', 'scheduled'),
  record('running-1', 'in_progress'), record('review-1', 'review'), record('blocked-1', 'blocked'),
  record('failed-1', 'failed'), continuation('turn-failed', 'failed'), continuation('turn-running', 'in_progress'),
  continuation('turn-done', 'done'), record('done-1', 'done'), record('cancelled-1', 'cancelled'),
  record('odd-1', 'quarantined'),
  record('bind-open', 'open', { metadata: { ui_scaffold: 1 } }),
  record('bind-failed', 'failed', { metadata: { ui_scaffold: true } }),
];

describe('summarizeWorkItems', () => {
  it('the Board columns plus its Blocked/Failed row account for every counted item exactly once', () => {
    const summary = summarizeWorkItems(POPULATION, scopes());
    const columns = BOARD_COLUMN_STATUSES.reduce((sum, status) => sum + summary.byStatus[status], 0);
    const blockedRow = summary.failed + summary.blocked + summary.cancelled + summary.byStatus.unknown;

    expect(summary.total).toBe(13);
    expect(columns + blockedRow).toBe(summary.total);
    expect(Object.values(summary.byStatus).reduce((sum, count) => sum + count, 0)).toBe(summary.total);
  });

  it('not done is everything except done and cancelled, so failed, blocked and unknown count in it', () => {
    const summary = summarizeWorkItems(POPULATION, scopes());

    expect(summary.notDone).toBe(summary.total - summary.done - summary.cancelled);
    expect(summary).toMatchObject({ notDone: 10, failed: 2, blocked: 1, cancelled: 1, done: 2 });
    expect(summary.byStatus.unknown).toBe(1);
  });

  it('a failed item counts in not done and never in done', () => {
    const running = summarizeWorkItems([record('a', 'in_progress')], scopes());
    const failed = summarizeWorkItems([record('a', 'failed')], scopes());

    expect([running.notDone, running.done, running.failed]).toEqual([1, 0, 0]);
    expect([failed.notDone, failed.done, failed.failed]).toEqual([1, 0, 1]);
  });

  it('never counts a scaffold row (I6)', () => {
    const turn = continuation('bind-turn', 'failed');
    const summary = summarizeWorkItems([
      record('bind-open', 'open', { metadata: { ui_scaffold: 1 } }),
      record('bind-failed', 'failed', { metadata: { ui_scaffold: true } }),
      { ...turn, metadata: { ...turn.metadata, ui_scaffold: 1 } },
    ], scopes());

    expect(summary).toMatchObject({ total: 0, notDone: 0, failed: 0 });
    expect(summary.continuations).toEqual({ total: 0, notDone: 0, failed: 0 });
  });

  it('counts the continuations among the items, the failed ones included', () => {
    const summary = summarizeWorkItems(POPULATION, scopes());

    expect(summary.continuations).toEqual({ total: 3, notDone: 2, failed: 1 });
  });

  it('with no items and no reads it counts nothing and is not loaded', () => {
    const summary = summarizeWorkItems([], new Map());

    expect(summary).toMatchObject({
      total: 0, notDone: 0, failed: 0, blocked: 0, cancelled: 0, done: 0,
      loaded: false, complete: false, truncated: false, stale: false,
    });
    expect(Object.values(summary.byStatus).every(count => count === 0)).toBe(true);
  });

  it('is loaded only once every status bucket has been read, and not while access is refused', () => {
    expect(summarizeWorkItems([], scopes()).loaded).toBe(true);
    expect(summarizeWorkItems([], scopes({ cancelled: { populated: false, status: 'loading' } })).loaded).toBe(false);
    expect(summarizeWorkItems([], scopes({ open: { status: 'unauthorized' } })).loaded).toBe(false);
  });

  it('is complete only when loaded, current and untruncated', () => {
    expect(summarizeWorkItems([], scopes())).toMatchObject({ complete: true, truncated: false, stale: false });
    expect(summarizeWorkItems([], scopes({ open: { truncated: true } })))
      .toMatchObject({ complete: false, truncated: true, stale: false });
    expect(summarizeWorkItems([], scopes({ failed: { stale: true } })))
      .toMatchObject({ complete: false, truncated: false, stale: true });
  });
});

describe('workItemOrigin', () => {
  it('a continuation and a delegated task both created by the captain classify differently', () => {
    const turn = continuation('turn', 'in_progress');
    const task = delegated('task', 'in_progress');

    expect([turn.created_by, task.created_by]).toEqual(['captain', 'captain']);
    expect(workItemOrigin(turn)).toBe('continuation');
    expect(workItemOrigin(task)).toBe('delegated');
  });

  it('only the exact DM-promotion source marks a continuation; the tag alone does not', () => {
    expect(workItemOrigin(record('tagged', 'open', { tags: ['conversational-turn'] }))).toBe('delegated');
    expect(workItemOrigin(record('other', 'open', { metadata: { source: 'dm_agentic_promotion_v2' } }))).toBe('delegated');
    expect(workItemOrigin(record('bare', 'open'))).toBe('delegated');
  });
});

describe('formatWorkItemCount', () => {
  const items = Array.from({ length: 12 }, (_, index) => record(`open-${index}`, 'open'));

  it('prints the count when every bucket is read, current and untruncated', () => {
    expect(formatWorkItemCount(summarizeWorkItems(items, scopes()), 'notDone')).toBe('12');
  });

  it('marks a lower bound when a bucket the count covers hit its cap', () => {
    const capped = Array.from({ length: 100 }, (_, index) => record(`open-${index}`, 'open'));

    expect(formatWorkItemCount(summarizeWorkItems(capped, scopes({ open: { truncated: true } })), 'notDone')).toBe('100+');
  });

  it('says the count is last known when a bucket is stale', () => {
    expect(formatWorkItemCount(summarizeWorkItems(items, scopes({ review: { stale: true } })), 'notDone'))
      .toBe('12 (last known)');
    expect(formatWorkItemCount(summarizeWorkItems(items, scopes({ open: { stale: true, truncated: true } })), 'notDone'))
      .toBe('12+ (last known)');
  });

  it('says unknown until every bucket has been read, whatever is cached', () => {
    expect(formatWorkItemCount(summarizeWorkItems(items, new Map()), 'notDone')).toBe('unknown');
    expect(formatWorkItemCount(summarizeWorkItems([], scopes({ done: { populated: false } })), 'failed')).toBe('unknown');
  });

  // RV1: an outstanding by-ID read failure is at least last known, never worse than the buckets say.
  it('says every count is last known while a by-ID read failure is outstanding', () => {
    const failing = new Map(scopes());
    failing.set(ITEM_READS_KEY, { ...READ, status: 'failed', stale: true });
    const summary = summarizeWorkItems(items, failing);

    expect(summary).toMatchObject({ loaded: true, complete: false, stale: true });
    expect(formatWorkItemCount(summary, 'notDone')).toBe('12 (last known)');
    expect(formatWorkItemCount(summary, 'failed')).toBe('0 (last known)');
  });

  it('keeps an unloaded count unknown while a by-ID read failure is outstanding', () => {
    const failing = new Map(scopes({ done: { populated: false } }));
    failing.set(ITEM_READS_KEY, { ...READ, status: 'failed', stale: true });

    expect(formatWorkItemCount(summarizeWorkItems(items, failing), 'notDone')).toBe('unknown');
  });

  it('leaves the not-done count exact when only the done window is truncated', () => {
    const done = Array.from({ length: 21 }, (_, index) => record(`done-${index}`, 'done'));
    const summary = summarizeWorkItems([...items, ...done], scopes({ done: { truncated: true } }));

    expect(formatWorkItemCount(summary, 'notDone')).toBe('12');
    expect(formatWorkItemCount(summary, 'done')).toBe('21+');
    expect(formatWorkItemCount(summary, 'total')).toBe('33+');
  });

  it('formats a sub-count with the flags of the count it belongs to', () => {
    const summary = summarizeWorkItems(POPULATION, scopes({ failed: { truncated: true } }));

    expect(formatWorkItemCount(summary, 'failed', summary.continuations.failed)).toBe('1+');
    expect(formatWorkItemCount(summary, 'blocked')).toBe('1');
  });
});
