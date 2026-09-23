import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { liveReadFence, resetLiveReadFenceForTests } from '../liveReadFence';
import {
  IDLE_SCOPE_META, ITEM_READS_KEY, WORK_ITEM_BUCKETS, WORK_ITEM_BURST_LIMIT, WORK_ITEM_CONFIRM_LIMIT, WORK_ITEM_QUEUE_LIMIT,
  WORK_ITEM_SCOPE_LIMIT, WORK_ITEMS_CACHE_KEY, WorkItemReconciler, assigneeScopeKey, bucketKey, isScaffoldWorkItem,
  isWorkItemListResponse, isWorkItemResponse, isWorkItemView, parentScopeKey, workItemCacheState, workItemKey,
  workItemReadUrl, type WorkItemCacheState, type WorkItemReadState, type WorkItemScopeMeta,
} from '../workItemReconciliation';
import { useStore, workItemReconciler } from '../useStore';
import type { BookingView, CrewSessionDetailProjection, WSEvent, WorkItemView } from '../types';
import { RESOURCE_TIMEOUT_MS } from '../../utils/resourceState';

const GENERATION = 'a'.repeat(32);

// The shape WorkItem.to_dict() serves (workforce.py:666-692), including its nulls and dicts.
function wire(id: string, status: string, updatedAt = 1): Record<string, unknown> {
  return {
    id, title: `Task ${id}`, description: '', work_type: 'task', status, priority: 3,
    parent_id: null, project_id: null, depends_on: [], assigned_to: 'worker-a',
    created_by: 'captain', created_at: 1, updated_at: updatedAt, due_at: null,
    estimated_tokens: null, actual_tokens: 0, trust_requirement: 0.0,
    required_capabilities: [], tags: [], metadata: { source: 'dm_agentic_promotion' },
    steps: [], verification: {}, schedule: {}, ttl_seconds: null, template_id: null,
  };
}

function view(id: string, status: string, updatedAt = 1): WorkItemView {
  return wire(id, status, updatedAt) as unknown as WorkItemView;
}

function childWire(id: string, status: string, parentId = 'p'): Record<string, unknown> {
  return { ...wire(id, status), parent_id: parentId };
}

function childView(id: string, status: string, parentId = 'p'): WorkItemView {
  return childWire(id, status, parentId) as unknown as WorkItemView;
}

function page(rows: readonly Record<string, unknown>[]): Record<string, unknown> {
  return { work_items: rows, count: rows.length };
}

const SCOPE_URL = '/api/work-items?parent_id=p&limit=1001';
// M3: the nine status buckets, in refresh order, each asking for one row past its cap.
const BUCKET_URLS = [
  '/api/work-items?status=draft&limit=101',
  '/api/work-items?status=open&limit=101',
  '/api/work-items?status=scheduled&limit=101',
  '/api/work-items?status=in_progress&limit=101',
  '/api/work-items?status=review&limit=101',
  '/api/work-items?status=blocked&limit=101',
  '/api/work-items?status=failed&limit=101',
  '/api/work-items?status=done&limit=21',
  '/api/work-items?status=cancelled&limit=21',
];
const ASSIGNEE_URL = '/api/work-items?assigned_to=a1&limit=101';
const ASSIGNEE_DONE_URL = '/api/work-items?assigned_to=a1&status=done&limit=11';

function reply(status: number, body: unknown): Response {
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  });
}

interface PendingFetch {
  readonly url: string;
  resolve(response: Response): void;
  reject(error: Error): void;
}

class FetchLog {
  readonly calls: PendingFetch[] = [];
  inFlight = 0;
  maxInFlight = 0;

  readonly fetch = (url: string): Promise<Response> => new Promise<Response>((resolve, reject) => {
    this.inFlight += 1;
    this.maxInFlight = Math.max(this.maxInFlight, this.inFlight);
    const settle = (): void => { this.inFlight -= 1; };
    this.calls.push({
      url,
      resolve: (response) => { settle(); resolve(response); },
      reject: (error) => { settle(); reject(error); },
    });
  });

  urls(): string[] {
    return this.calls.map(call => call.url);
  }
}

function harness(
  fetch?: (url: string) => Promise<Response>,
  cached: () => readonly WorkItemView[] = () => [],
) {
  const log = new FetchLog();
  const applied: WorkItemView[][] = [];
  const removed: string[][] = [];
  const meta: Array<[string, WorkItemReadState | null]> = [];
  const reconciler = new WorkItemReconciler({
    fetch: fetch ?? log.fetch,
    fence: liveReadFence,
    apply: (records) => { applied.push([...records]); },
    remove: (ids) => { removed.push([...ids]); },
    setMeta: (key, state) => { meta.push([key, state]); },
    cached,
  });
  return { log, applied, removed, meta, reconciler };
}

async function calls(log: FetchLog, count: number): Promise<void> {
  await vi.waitFor(() => expect(log.calls).toHaveLength(count));
}

function frame(type: string, data: Record<string, unknown>, sequence: number): WSEvent {
  return { type, data, timestamp: 1, stream: { generation: GENERATION, sequence } };
}

// A shape-valid AD-1132 projection (parseCrewSessionProjection) for parent `parentId` in thread `t`.
function projectionData(parentId: string, revision: number): Record<string, unknown> {
  const progress = { total: 1, done: 0, failed: 1, active: 0 };
  const session: CrewSessionDetailProjection = {
    task_id: parentId, thread_id: 't', goal: 'Goal', origin: 'captain', originator_id: 'captain',
    facilitator_id: 'facilitator-a', owner_ids: ['facilitator-a'], state: 'executing', revision,
    success_criteria: ['Done'], expected_deliverable: 'Report',
    timestamps: {
      created_at: 1, transitioned_at: 1, started_at: 1, first_result_at: null,
      verified_at: null, completed_at: null,
    },
    progress: { ...progress, active_child: null }, last_result_summary: '', blocker: null,
    result: null, verification: null, duplicate_resume_count: 0,
  };
  return {
    parent_id: parentId, thread_id: 't', revision, session,
    room_summary: {
      outputs: 0, steps_total: 1, steps_done: 0, topic: 'Goal',
      session: {
        task_id: parentId, thread_id: 't', goal: 'Goal', state: 'executing',
        facilitator_id: 'facilitator-a', owner_ids: ['facilitator-a'], progress,
        last_result_summary: '', blocker: null, needs_attention: false,
        result_artifact_id: null, verified_at: null,
      },
    },
  };
}

beforeEach(() => {
  resetLiveReadFenceForTests();
});

afterEach(async () => {
  await workItemReconciler.whenIdle();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('workItemReadUrl and validators (issue #1375)', () => {
  it('builds the by-ID read URL with the id encoded', () => {
    expect(workItemReadUrl({ kind: 'item', id: 'c1ac8be2b94a' })).toBe('/api/work-items/c1ac8be2b94a');
    expect(workItemReadUrl({ kind: 'item', id: 'a/b?c' })).toBe('/api/work-items/a%2Fb%3Fc');
  });

  it('builds the parent-scope read URL one past the scope limit, with the id encoded', () => {
    expect(WORK_ITEM_SCOPE_LIMIT).toBe(1000);
    expect(workItemReadUrl({ kind: 'parent', parentId: 'p' })).toBe(SCOPE_URL);
    expect(workItemReadUrl({ kind: 'parent', parentId: 'a&b=c' }))
      .toBe('/api/work-items?parent_id=a%26b%3Dc&limit=1001');
    expect(parentScopeKey('p')).toBe('scope:parent:p');
  });

  it('builds the status-bucket and assignee read URLs one past their caps, with values encoded', () => {
    expect(WORK_ITEM_BUCKETS.map(status => workItemReadUrl({ kind: 'bucket', status }))).toEqual(BUCKET_URLS);
    expect(workItemReadUrl({ kind: 'assignee', assignedTo: 'a1', done: false })).toBe(ASSIGNEE_URL);
    expect(workItemReadUrl({ kind: 'assignee', assignedTo: 'a1', done: true })).toBe(ASSIGNEE_DONE_URL);
    expect(workItemReadUrl({ kind: 'assignee', assignedTo: 'a&b=c', done: false }))
      .toBe('/api/work-items?assigned_to=a%26b%3Dc&limit=101');
    // Bucket and assignee keys are scope keys, so the item epoch fences them too.
    expect([bucketKey('done'), assigneeScopeKey('a1', false), assigneeScopeKey('a1', true)])
      .toEqual(['scope:status:done', 'scope:assignee:a1', 'scope:assignee-done:a1']);
  });

  it.each([
    [1, true], [true, true], [0, false], ['1', false], [false, false], [undefined, false],
  ])('treats metadata.ui_scaffold=%j as scaffold: %s', (flag, expected) => {
    const metadata = flag === undefined ? {} : { ui_scaffold: flag };
    expect(isScaffoldWorkItem({ ...view('x', 'open'), metadata })).toBe(expected);
  });

  it('accepts a served list page, including an empty one', () => {
    expect(isWorkItemListResponse(page([wire('x', 'failed'), wire('y', 'quarantined')]))).toBe(true);
    expect(isWorkItemListResponse(page([]))).toBe(true);
  });

  it.each([
    ['a non-object', null],
    ['an array', [wire('x', 'open')]],
    ['a by-ID envelope', { work_item: wire('x', 'open') }],
    ['non-array rows', { work_items: 'x', count: 1 }],
    ['an invalid row', { work_items: [{ id: 'x' }], count: 1 }],
    ['a count that disagrees', { work_items: [wire('x', 'open')], count: 2 }],
    ['a fractional count', { work_items: [], count: 0.5 }],
  ])('rejects a list page with %s', (_name, value) => {
    expect(isWorkItemListResponse(value)).toBe(false);
  });

  it('accepts the served record with extra keys and an unknown status', () => {
    expect(isWorkItemView(wire('x', 'failed'))).toBe(true);
    expect(isWorkItemView({ ...wire('x', 'quarantined'), future_field: [1] })).toBe(true);
    expect(isWorkItemResponse({ work_item: wire('x', 'failed') })).toBe(true);
  });

  it.each([
    ['a non-object', null],
    ['an array', [wire('x', 'open')]],
    ['an empty id', { ...wire('x', 'open'), id: '' }],
    ['an overlong id', { ...wire('x', 'open'), id: 'x'.repeat(129) }],
    ['a missing status', { ...wire('x', 'open'), status: undefined }],
    ['an empty status', { ...wire('x', 'open'), status: '' }],
    ['a non-finite updated_at', { ...wire('x', 'open'), updated_at: Number.NaN }],
    ['non-string tags', { ...wire('x', 'open'), tags: [1] }],
    ['array metadata', { ...wire('x', 'open'), metadata: [] }],
    ['non-object steps', { ...wire('x', 'open'), steps: ['step'] }],
  ])('rejects a record with %s', (_name, value) => {
    expect(isWorkItemView(value)).toBe(false);
    expect(isWorkItemResponse({ work_item: value })).toBe(false);
  });

  it.each([null, [], {}, { work_items: [wire('x', 'open')] }])('rejects the envelope %j', (value) => {
    expect(isWorkItemResponse(value)).toBe(false);
  });
});

describe('WorkItemReconciler (issue #1375)', () => {
  it('serializes by-ID reads with one fetch in flight, in invalidation order', async () => {
    const { log, applied, reconciler } = harness();
    reconciler.invalidate('a');
    reconciler.invalidate('b');
    reconciler.invalidate('c');
    expect(log.urls()).toEqual(['/api/work-items/a']);

    log.calls[0].resolve(reply(200, { work_item: wire('a', 'open') }));
    await calls(log, 2);
    expect(log.inFlight).toBe(1);
    log.calls[1].resolve(reply(200, { work_item: wire('b', 'open') }));
    await calls(log, 3);
    log.calls[2].resolve(reply(200, { work_item: wire('c', 'open') }));
    await reconciler.whenIdle();

    expect(log.urls()).toEqual(['/api/work-items/a', '/api/work-items/b', '/api/work-items/c']);
    expect(log.maxInFlight).toBe(1);
    expect(applied.map(batch => batch.map(item => item.id))).toEqual([['a'], ['b'], ['c']]);
  });

  it('rejects a response issued before a newer frame and re-reads it exactly once', async () => {
    const { log, applied, reconciler } = harness();
    reconciler.invalidate('x');
    reconciler.invalidate('x');
    log.calls[0].resolve(reply(200, { work_item: wire('x', 'in_progress') }));
    await calls(log, 2);
    log.calls[1].resolve(reply(200, { work_item: wire('x', 'failed', 2) }));
    await reconciler.whenIdle();

    expect(log.calls).toHaveLength(2);
    expect(applied.map(batch => batch[0].status)).toEqual(['failed']);
  });

  it('re-reads by ID exactly once when an item epoch rejects an in-flight response', async () => {
    const { log, applied, reconciler } = harness();
    reconciler.invalidate('x');
    reconciler.observeItemEpoch();
    log.calls[0].resolve(reply(200, { work_item: wire('x', 'in_progress') }));
    await calls(log, 2);
    log.calls[1].resolve(reply(200, { work_item: wire('x', 'failed', 2) }));
    await reconciler.whenIdle();

    expect(log.urls()).toEqual(['/api/work-items/x', '/api/work-items/x']);
    expect(applied.map(batch => batch[0].status)).toEqual(['failed']);
  });

  it('coalesces three frames during one in-flight read into one follow-up read', async () => {
    const { log, applied, reconciler } = harness();
    reconciler.invalidate('x');
    reconciler.invalidate('x');
    reconciler.invalidate('x');
    reconciler.invalidate('x');
    log.calls[0].resolve(reply(200, { work_item: wire('x', 'in_progress') }));
    await calls(log, 2);
    log.calls[1].resolve(reply(200, { work_item: wire('x', 'failed', 2) }));
    await reconciler.whenIdle();

    expect(log.calls).toHaveLength(2);
    expect(applied).toHaveLength(1);
  });

  it.each([404, 410])('removes the record when a current read returns %s', async (status) => {
    const { log, applied, removed, meta, reconciler } = harness();
    reconciler.invalidate('x');
    log.calls[0].resolve(reply(status, { detail: 'Work item not found' }));
    await reconciler.whenIdle();

    expect(removed).toEqual([['x']]);
    expect(applied).toEqual([]);
    expect(meta).toEqual([[workItemKey('x'), null]]);
  });

  it('does not remove on a 404 issued before a newer frame, and re-reads instead', async () => {
    const { log, applied, removed, reconciler } = harness();
    reconciler.invalidate('x');
    reconciler.invalidate('x');
    log.calls[0].resolve(reply(404, { detail: 'Work item not found' }));
    await calls(log, 2);
    log.calls[1].resolve(reply(200, { work_item: wire('x', 'open') }));
    await reconciler.whenIdle();

    expect(removed).toEqual([]);
    expect(applied.map(batch => batch[0].id)).toEqual(['x']);
  });

  it.each([401, 403])('drops the content on %s', async (status) => {
    const { log, applied, removed, meta, reconciler } = harness();
    reconciler.invalidate('x');
    log.calls[0].resolve(reply(status, { detail: 'denied' }));
    await reconciler.whenIdle();

    expect(removed).toEqual([['x']]);
    expect(applied).toEqual([]);
    expect(meta).toEqual([[workItemKey('x'), 'unauthorized']]);
  });

  // RV1: a refusal obeys I2 like every other outcome; the reviewer's sequence, its re-read failing.
  it.each([401, 403])('keeps the record when a %s was issued before a newer frame, and the one re-read decides', async (status) => {
    const codes = [status, 503];
    const urls: string[] = [];
    const { applied, removed, meta, reconciler } = harness(async (url) => {
      urls.push(url);
      return reply(codes.shift() ?? 503, { detail: 'refused' });
    });
    reconciler.invalidate('x');
    // Premise: the refused read was issued before the newer frame below.
    expect(urls).toEqual(['/api/work-items/x']);
    reconciler.invalidate('x');
    await reconciler.whenIdle();

    expect(urls).toEqual(['/api/work-items/x', '/api/work-items/x']);
    expect([applied, removed]).toEqual([[], []]);
    expect(meta).toEqual([[workItemKey('x'), 'stale']]);
  });

  it.each([401, 403])('a %s issued before a newer frame never removes the record its re-read updates', async (status) => {
    const urls: string[] = [];
    const { applied, removed, meta, reconciler } = harness(async (url) => {
      urls.push(url);
      return urls.length === 1
        ? reply(status, { detail: 'denied' })
        : reply(200, { work_item: wire('x', 'failed', 2) });
    });
    reconciler.invalidate('x');
    expect(urls).toHaveLength(1);
    reconciler.invalidate('x');
    await reconciler.whenIdle();

    expect(urls).toEqual(['/api/work-items/x', '/api/work-items/x']);
    expect(removed).toEqual([]);
    expect(applied.map(batch => batch.map(item => `${item.id}:${item.status}`))).toEqual([['x:failed']]);
    expect(meta).toEqual([[workItemKey('x'), null]]);
  });

  it('keeps the record and marks it stale on 503', async () => {
    const { log, applied, removed, meta, reconciler } = harness();
    reconciler.invalidate('x');
    log.calls[0].resolve(reply(503, { detail: 'Workforce engine not enabled' }));
    await reconciler.whenIdle();

    expect([applied, removed]).toEqual([[], []]);
    expect(meta).toEqual([[workItemKey('x'), 'stale']]);
  });

  it('keeps the record and marks it stale on a network error', async () => {
    const { log, applied, removed, meta, reconciler } = harness();
    reconciler.invalidate('x');
    log.calls[0].reject(new TypeError('network down'));
    await reconciler.whenIdle();

    expect([applied, removed]).toEqual([[], []]);
    expect(meta).toEqual([[workItemKey('x'), 'stale']]);
  });

  it('keeps the record and marks it stale when the read times out', async () => {
    vi.useFakeTimers();
    try {
      const { log, applied, removed, meta, reconciler } = harness();
      reconciler.invalidate('x');
      // Premise: the read is in flight and never answers.
      expect(log.calls).toHaveLength(1);
      await vi.advanceTimersByTimeAsync(RESOURCE_TIMEOUT_MS);
      await reconciler.whenIdle();

      expect([applied, removed]).toEqual([[], []]);
      expect(meta).toEqual([[workItemKey('x'), 'stale']]);
    } finally {
      vi.useRealTimers();
    }
  });

  it.each([
    ['an invalid body', { work_item: { id: 'x', status: 'failed' } }],
    ['a record for another id', { work_item: wire('y', 'failed') }],
    ['non-JSON text', 'not json'],
  ])('keeps the record and marks the read failed on %s', async (_name, body) => {
    const { log, applied, removed, meta, reconciler } = harness();
    reconciler.invalidate('x');
    log.calls[0].resolve(reply(200, body));
    await reconciler.whenIdle();

    expect([applied, removed]).toEqual([[], []]);
    expect(meta).toEqual([[workItemKey('x'), 'failed']]);
  });

  it('clears a prior read mark when a later read succeeds', async () => {
    const { log, meta, reconciler } = harness();
    reconciler.invalidate('x');
    log.calls[0].resolve(reply(503, {}));
    await reconciler.whenIdle();
    reconciler.invalidate('x');
    log.calls[1].resolve(reply(200, { work_item: wire('x', 'open') }));
    await reconciler.whenIdle();

    expect(meta).toEqual([[workItemKey('x'), 'stale'], [workItemKey('x'), null]]);
  });

  it('discards a late result and the queued keys after a reset', async () => {
    const { log, applied, meta, reconciler } = harness();
    reconciler.invalidate('x');
    reconciler.invalidate('y');
    resetLiveReadFenceForTests();
    log.calls[0].resolve(reply(200, { work_item: wire('x', 'failed') }));
    await reconciler.whenIdle();

    expect(log.calls).toHaveLength(1);
    expect(applied).toEqual([]);
    expect(meta).toEqual([]);
  });

  it(`overflows to invalidateAll past ${WORK_ITEM_QUEUE_LIMIT} queued keys`, async () => {
    const { log, meta, reconciler } = harness();
    reconciler.invalidate('in-flight');
    for (let index = 0; index < WORK_ITEM_QUEUE_LIMIT; index += 1) reconciler.invalidate(`k${index}`);
    expect(meta).toEqual([]);

    reconciler.invalidate('one-too-many');

    expect(meta).toEqual([[WORK_ITEMS_CACHE_KEY, 'stale']]);
    log.calls[0].resolve(reply(200, { work_item: wire('in-flight', 'open') }));
    await reconciler.whenIdle();
    expect(log.calls).toHaveLength(1);
  });

  it.each(['', 'x'.repeat(129)])('ignores an invalid id %j', async (id) => {
    const { log, reconciler } = harness();
    reconciler.invalidate(id);
    await reconciler.whenIdle();
    expect(log.calls).toEqual([]);
  });

  it('never leaves an unhandled rejection when fetch throws synchronously or apply fails', async () => {
    const thrown = harness(() => { throw new TypeError('no fetch'); });
    thrown.reconciler.invalidate('x');
    await thrown.reconciler.whenIdle();
    expect(thrown.meta).toEqual([[workItemKey('x'), 'stale']]);

    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const log = new FetchLog();
    const reconciler = new WorkItemReconciler({
      fetch: log.fetch, fence: liveReadFence,
      apply: () => { throw new Error('store rejected the batch'); },
      remove: () => {}, setMeta: () => {}, cached: () => [],
    });
    reconciler.invalidate('x');
    reconciler.invalidate('y');
    log.calls[0].resolve(reply(200, { work_item: wire('x', 'open') }));
    await calls(log, 2);
    log.calls[1].resolve(reply(503, {}));
    await reconciler.whenIdle();
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it('seeds snapshot rows as a read issued on arrival, never removing, and fences older reads', async () => {
    const { log, applied, removed, reconciler } = harness();
    reconciler.invalidate('x');
    reconciler.observeItemEpoch();
    reconciler.applySnapshotRows([wire('x', 'failed', 2), { id: 'broken' }, wire('y', 'open')]);
    expect(applied.map(batch => batch.map(item => `${item.id}:${item.status}`))).toEqual([['x:failed', 'y:open']]);

    log.calls[0].resolve(reply(200, { work_item: wire('x', 'in_progress') }));
    await calls(log, 2);
    log.calls[1].resolve(reply(200, { work_item: wire('x', 'failed', 2) }));
    await reconciler.whenIdle();

    expect(applied.flat().map(item => `${item.id}:${item.status}`)).toEqual(['x:failed', 'y:open', 'x:failed']);
    expect(removed).toEqual([]);
    reconciler.applySnapshotRows('not rows');
    expect(applied).toHaveLength(2);
  });

  it('is idle immediately when nothing was invalidated', async () => {
    const { log, reconciler } = harness();
    await reconciler.whenIdle();
    expect(log.calls).toEqual([]);
  });
});

describe('WorkItemReconciler parent scope (issue #1375 M2)', () => {
  it('reads the parent scope, then the parent by ID, one at a time', async () => {
    const { log, applied, meta, reconciler } = harness();
    reconciler.invalidateScope('p');
    expect(log.urls()).toEqual([SCOPE_URL]);

    log.calls[0].resolve(reply(200, page([childWire('c1', 'failed')])));
    await calls(log, 2);
    log.calls[1].resolve(reply(200, { work_item: wire('p', 'in_progress') }));
    await reconciler.whenIdle();

    expect(log.urls()).toEqual([SCOPE_URL, '/api/work-items/p']);
    expect(log.maxInFlight).toBe(1);
    expect(applied.map(batch => batch.map(item => `${item.id}:${item.status}`)))
      .toEqual([['c1:failed'], ['p:in_progress']]);
    expect(meta).toContainEqual([parentScopeKey('p'), null]);
  });

  it('confirms by ID the cached children a complete scope omits, never removing them itself', async () => {
    const cached = [childView('gone', 'open'), childView('moved', 'open'), childView('kept', 'open'),
      childView('elsewhere', 'open', 'q')];
    const { log, applied, removed, reconciler } = harness(undefined, () => cached);
    reconciler.invalidateScope('p');
    log.calls[0].resolve(reply(200, page([childWire('kept', 'failed')])));
    await calls(log, 2);
    log.calls[1].resolve(reply(503, {}));
    await calls(log, 3);
    // Premise: the omitted children are unchanged until their own by-ID reads answer.
    expect(removed).toEqual([]);
    log.calls[2].resolve(reply(404, { detail: 'Work item not found' }));
    await calls(log, 4);
    log.calls[3].resolve(reply(200, { work_item: childWire('moved', 'open', 'q') }));
    await reconciler.whenIdle();

    expect(log.urls()).toEqual([SCOPE_URL, '/api/work-items/p', '/api/work-items/gone', '/api/work-items/moved']);
    expect(removed).toEqual([['gone']]);
    expect(applied.flat().map(item => `${item.id}:${item.parent_id}`)).toEqual(['kept:p', 'moved:q']);
  });

  it('does not confirm omissions from a truncated scope', async () => {
    const rows = Array.from({ length: WORK_ITEM_SCOPE_LIMIT + 1 }, (_, index) => childWire(`c${index}`, 'open'));
    const urls: string[] = [];
    // Every read answers at once, so an unexpected confirm read shows up in `urls` instead of hanging.
    const answerAll = async (url: string): Promise<Response> => {
      urls.push(url);
      return url === SCOPE_URL ? reply(200, page(rows)) : reply(503, {});
    };
    const { applied, reconciler } = harness(answerAll, () => [childView('beyond', 'open')]);
    reconciler.invalidateScope('p');
    await reconciler.whenIdle();

    expect(urls).toEqual([SCOPE_URL, '/api/work-items/p']);
    expect(applied[0]).toHaveLength(WORK_ITEM_SCOPE_LIMIT + 1);
  });

  it('coalesces scope invalidations during an in-flight read and never applies the stale page', async () => {
    const { log, applied, reconciler } = harness();
    reconciler.invalidateScope('p');
    reconciler.invalidateScope('p');
    reconciler.invalidateScope('p');
    log.calls[0].resolve(reply(200, page([childWire('c1', 'in_progress')])));
    await calls(log, 2);
    log.calls[1].resolve(reply(200, { work_item: wire('p', 'in_progress') }));
    await calls(log, 3);
    log.calls[2].resolve(reply(200, page([childWire('c1', 'failed')])));
    await reconciler.whenIdle();

    expect(log.urls()).toEqual([SCOPE_URL, '/api/work-items/p', SCOPE_URL]);
    expect(applied.flat().map(item => `${item.id}:${item.status}`)).toEqual(['p:in_progress', 'c1:failed']);
  });

  it('re-reads the scope once when an item epoch rejects an in-flight scope page', async () => {
    const { log, applied, reconciler } = harness();
    reconciler.invalidateScope('p');
    reconciler.observeItemEpoch();
    log.calls[0].resolve(reply(200, page([childWire('c1', 'in_progress')])));
    await calls(log, 2);
    log.calls[1].resolve(reply(200, { work_item: wire('p', 'in_progress') }));
    await calls(log, 3);
    log.calls[2].resolve(reply(200, page([childWire('c1', 'failed')])));
    await reconciler.whenIdle();

    expect(log.urls()).toEqual([SCOPE_URL, '/api/work-items/p', SCOPE_URL]);
    expect(applied.flat().map(item => `${item.id}:${item.status}`)).toEqual(['p:in_progress', 'c1:failed']);
  });

  it('re-reads by ID a scope row whose item was observed live after the scope read was issued', async () => {
    const { log, applied, reconciler } = harness();
    reconciler.invalidateScope('p');
    reconciler.invalidate('c1');
    log.calls[0].resolve(reply(200, page([childWire('c1', 'in_progress'), childWire('c2', 'open')])));
    await calls(log, 2);
    log.calls[1].resolve(reply(200, { work_item: wire('p', 'in_progress') }));
    await calls(log, 3);
    log.calls[2].resolve(reply(200, { work_item: childWire('c1', 'failed') }));
    await reconciler.whenIdle();

    expect(log.urls()).toEqual([SCOPE_URL, '/api/work-items/p', '/api/work-items/c1']);
    expect(applied.flat().map(item => `${item.id}:${item.status}`))
      .toEqual(['c2:open', 'p:in_progress', 'c1:failed']);
  });

  it.each([
    ['a 503', (call: PendingFetch) => call.resolve(reply(503, { detail: 'Workforce engine not enabled' }))],
    ['a network error', (call: PendingFetch) => call.reject(new TypeError('network down'))],
  ])('keeps records and marks the scope stale on %s', async (_name, settle) => {
    const { log, applied, removed, meta, reconciler } = harness(undefined, () => [childView('c1', 'open')]);
    reconciler.invalidateScope('p');
    settle(log.calls[0]);
    await calls(log, 2);
    log.calls[1].resolve(reply(503, {}));
    await reconciler.whenIdle();

    expect([applied, removed]).toEqual([[], []]);
    expect(log.urls()).toEqual([SCOPE_URL, '/api/work-items/p']);
    expect(meta).toContainEqual([parentScopeKey('p'), 'stale']);
  });

  it.each([
    ['a row from another parent', page([childWire('c1', 'open', 'q')])],
    ['an invalid row', page([{ id: 'c1' }])],
    ['a by-ID envelope', { work_item: childWire('c1', 'open') }],
  ])('keeps records and marks the scope failed on %s', async (_name, body) => {
    const { log, applied, removed, meta, reconciler } = harness(undefined, () => [childView('c1', 'open')]);
    reconciler.invalidateScope('p');
    log.calls[0].resolve(reply(200, body));
    await calls(log, 2);
    log.calls[1].resolve(reply(503, {}));
    await reconciler.whenIdle();

    expect([applied, removed]).toEqual([[], []]);
    expect(log.urls()).toEqual([SCOPE_URL, '/api/work-items/p']);
    expect(meta).toContainEqual([parentScopeKey('p'), 'failed']);
  });

  it.each([401, 403])('on %s marks the scope unauthorized and confirms its cached children by ID', async (status) => {
    const { log, removed, meta, reconciler } = harness(undefined, () => [childView('c1', 'open')]);
    reconciler.invalidateScope('p');
    log.calls[0].resolve(reply(status, { detail: 'denied' }));
    await calls(log, 2);
    log.calls[1].resolve(reply(503, {}));
    await calls(log, 3);
    expect(removed).toEqual([]);
    log.calls[2].resolve(reply(status, { detail: 'denied' }));
    await reconciler.whenIdle();

    expect(log.urls()).toEqual([SCOPE_URL, '/api/work-items/p', '/api/work-items/c1']);
    expect(meta).toContainEqual([parentScopeKey('p'), 'unauthorized']);
    expect(removed).toEqual([['c1']]);
  });

  it.each([401, 403])('a scope %s issued before a newer projection neither refuses nor confirms; the re-read decides', async (status) => {
    const urls: string[] = [];
    const { removed, meta, reconciler } = harness(async (url) => {
      urls.push(url);
      if (url !== SCOPE_URL) return reply(503, {});
      return urls.length === 1 ? reply(status, { detail: 'denied' }) : reply(200, page([childWire('c1', 'failed')]));
    }, () => [childView('c1', 'open')]);
    reconciler.invalidateScope('p');
    // Premise: the refused scope read was issued before the newer projection.
    expect(urls).toEqual([SCOPE_URL]);
    reconciler.invalidateScope('p');
    await reconciler.whenIdle();

    expect(urls).toEqual([SCOPE_URL, '/api/work-items/p', SCOPE_URL]);
    expect(removed).toEqual([]);
    expect(meta).not.toContainEqual([parentScopeKey('p'), 'unauthorized']);
    expect(meta).toContainEqual([parentScopeKey('p'), null]);
  });

  it.each(['', 'x'.repeat(129)])('ignores an invalid parent id %j', async (parentId) => {
    const { log, reconciler } = harness();
    reconciler.invalidateScope(parentId);
    await reconciler.whenIdle();
    expect(log.calls).toEqual([]);
  });
});

describe('WorkItemReconciler population (issue #1375 M3)', () => {
  const emptyPage = (): Response => reply(200, page([]));

  // Answers every read at once, so an unexpected read shows up in `urls` instead of hanging.
  function serve(respond: (url: string) => Response): { urls: string[]; fetch: (url: string) => Promise<Response> } {
    const urls: string[] = [];
    return { urls, fetch: async (url) => { urls.push(url); return respond(url); } };
  }

  function scope(reconciler: WorkItemReconciler, key: string): WorkItemScopeMeta | undefined {
    return reconciler.scopes.get(key);
  }

  it('refreshAll reads the nine status buckets one at a time, each asking for one past its cap', async () => {
    const { log, reconciler } = harness();
    reconciler.refreshAll();
    for (let index = 0; index < BUCKET_URLS.length; index += 1) {
      await calls(log, index + 1);
      expect(log.inFlight).toBe(1);
      log.calls[index].resolve(emptyPage());
    }
    await reconciler.whenIdle();

    expect(log.urls()).toEqual(BUCKET_URLS);
    expect(log.maxInFlight).toBe(1);
  });

  it('no fetch happens without interest', async () => {
    const { log, reconciler } = harness();
    const issuedBefore = liveReadFence.begin();
    reconciler.frameChanged('x');
    reconciler.frameScopeChanged('p');
    // Premise: an ignored frame still fences older reads of what it named.
    expect(liveReadFence.accepts(workItemKey('x'), issuedBefore)).toBe(false);
    expect(liveReadFence.accepts(parentScopeKey('p'), issuedBefore)).toBe(false);
    reconciler.observeItemEpoch();
    await reconciler.whenIdle();

    expect(log.calls).toEqual([]);
  });

  it('an epoch with interest triggers a refresh', async () => {
    const answered = serve(emptyPage);
    const { reconciler } = harness(answered.fetch);
    const release = reconciler.acquireInterest();
    await reconciler.whenIdle();
    expect(answered.urls).toEqual(BUCKET_URLS);

    reconciler.observeItemEpoch();
    await reconciler.whenIdle();

    expect(answered.urls).toEqual([...BUCKET_URLS, ...BUCKET_URLS]);
    release();
  });

  it('first interest refreshes, a second over the fresh cache does not, and interest over a stale cache does', async () => {
    const answered = serve(emptyPage);
    const { reconciler } = harness(answered.fetch);
    const first = reconciler.acquireInterest();
    await reconciler.whenIdle();
    const second = reconciler.acquireInterest();
    await reconciler.whenIdle();
    expect(answered.urls).toEqual(BUCKET_URLS);

    first();
    second();
    reconciler.observeItemEpoch();
    await reconciler.whenIdle();
    // Premise: without interest the epoch only marked the cache stale.
    expect(answered.urls).toEqual(BUCKET_URLS);
    expect(scope(reconciler, bucketKey('open'))?.stale).toBe(true);
    const third = reconciler.acquireInterest();
    await reconciler.whenIdle();

    expect(answered.urls).toEqual([...BUCKET_URLS, ...BUCKET_URLS]);
    third();
  });

  it('a populated fresh cache keeps reading frames by ID after its interest is released', async () => {
    const answered = serve(url => (url.startsWith('/api/work-items?') ? emptyPage() : reply(503, {})));
    const { reconciler } = harness(answered.fetch);
    reconciler.acquireInterest()();
    await reconciler.whenIdle();

    reconciler.frameChanged('x');
    await reconciler.whenIdle();

    expect(answered.urls).toEqual([...BUCKET_URLS, '/api/work-items/x']);
  });

  it('stops reading frames once an epoch leaves an uninterested cache stale', async () => {
    const answered = serve(url => (url.startsWith('/api/work-items?') ? emptyPage() : reply(503, {})));
    const { reconciler } = harness(answered.fetch);
    reconciler.acquireInterest()();
    await reconciler.whenIdle();
    reconciler.observeItemEpoch();

    reconciler.frameChanged('x');
    reconciler.frameScopeChanged('p');
    await reconciler.whenIdle();

    expect(answered.urls).toEqual(BUCKET_URLS);
  });

  it('a truncated bucket never triggers the omission rule; a complete one confirms by ID and a 404 removes', async () => {
    const cached = [view('gone', 'open'), view('beyond', 'in_progress')];
    const truncated = Array.from({ length: 101 }, (_, index) => wire(`ip${index}`, 'in_progress'));
    const answered = serve((url) => {
      if (url === '/api/work-items?status=in_progress&limit=101') return reply(200, page(truncated));
      if (url.startsWith('/api/work-items?')) return emptyPage();
      return reply(404, { detail: 'Work item not found' });
    });
    const { removed, reconciler } = harness(answered.fetch, () => cached);
    reconciler.refreshAll();
    await reconciler.whenIdle();

    expect(answered.urls).toEqual([...BUCKET_URLS, '/api/work-items/gone']);
    expect(removed).toEqual([['gone']]);
    expect(scope(reconciler, bucketKey('in_progress'))?.truncated).toBe(true);
    expect(scope(reconciler, bucketKey('open'))?.truncated).toBe(false);
  });

  it('the omission rule skips scaffold rows, which list reads never return', async () => {
    const cached = [{ ...view('binding', 'open'), metadata: { ui_scaffold: 1 } }];
    const answered = serve(url => (url.startsWith('/api/work-items?') ? emptyPage() : reply(404, {})));
    const { reconciler } = harness(answered.fetch, () => cached);
    reconciler.refreshAll();
    await reconciler.whenIdle();

    expect(answered.urls).toEqual(BUCKET_URLS);
  });

  it('records bucket metadata: status, truncation, observedAt, populated and stale', async () => {
    const answered = serve((url) => {
      if (url.includes('status=draft')) return reply(503, {});
      if (url.includes('status=open')) return reply(200, page([wire('o', 'open')]));
      return emptyPage();
    });
    const { reconciler } = harness(answered.fetch);
    const release = reconciler.acquireInterest();
    expect(scope(reconciler, bucketKey('draft'))).toEqual({ ...IDLE_SCOPE_META, status: 'loading' });
    await reconciler.whenIdle();

    expect(scope(reconciler, bucketKey('draft'))).toEqual({ ...IDLE_SCOPE_META, status: 'unavailable' });
    expect(scope(reconciler, bucketKey('open'))).toEqual({
      status: 'ready', truncated: false, observedAt: expect.any(Number), populated: true, stale: false,
    });
    expect(scope(reconciler, bucketKey('done'))).toMatchObject({ status: 'empty', populated: true, stale: false });
    release();
    reconciler.observeItemEpoch();
    expect(scope(reconciler, bucketKey('open'))).toMatchObject({ status: 'ready', populated: true, stale: true });
  });

  it.each<[string, Partial<WorkItemScopeMeta>[] | Partial<WorkItemScopeMeta>, string]>([
    ['nothing requested', [], 'idle'],
    ['a first load in flight', [{ status: 'loading' }], 'loading'],
    ['a first load part-way', [{ status: 'ready', populated: true }, { status: 'loading' }], 'loading'],
    ['every bucket fresh', { status: 'empty', populated: true }, 'ready'],
    ['a refused bucket', [{ status: 'unauthorized' }], 'unauthorized'],
    ['a first load that failed', { status: 'unavailable' }, 'unavailable'],
    ['a refresh that failed', [{ status: 'unavailable', populated: true, stale: true }], 'stale'],
    ['a refresh after an epoch', { status: 'loading', populated: true, stale: true }, 'stale'],
  ])('derives the cache state from %s', (_name, metas, expected) => {
    // A single meta applies to every bucket; a list applies to the buckets in refresh order.
    const perBucket = Array.isArray(metas) ? metas : WORK_ITEM_BUCKETS.map(() => metas);
    const scopes = new Map(perBucket.map((meta, index) => [
      bucketKey(WORK_ITEM_BUCKETS[index]), { ...IDLE_SCOPE_META, ...meta },
    ]));
    expect(workItemCacheState(scopes)).toBe(expected);
  });

  it('keeps 20 queued frames as by-ID reads', async () => {
    const answered = serve(url => (url.startsWith('/api/work-items?') ? emptyPage() : reply(503, {})));
    const { reconciler } = harness(answered.fetch);
    const release = reconciler.acquireInterest();
    await reconciler.whenIdle();
    expect(WORK_ITEM_BURST_LIMIT).toBe(20);
    for (let index = 0; index <= 20; index += 1) reconciler.frameChanged(`k${index}`);
    await reconciler.whenIdle();

    // The first read left the queue at once, so 20 were queued behind it.
    expect(answered.urls.slice(BUCKET_URLS.length)).toEqual(
      Array.from({ length: 21 }, (_, index) => `/api/work-items/k${index}`),
    );
    release();
  });

  it('a by-ID burst of more than 20 frames refreshes every bucket instead', async () => {
    const answered = serve(url => (url.startsWith('/api/work-items?') ? emptyPage() : reply(503, {})));
    const { reconciler } = harness(answered.fetch);
    const release = reconciler.acquireInterest();
    await reconciler.whenIdle();
    for (let index = 0; index <= 21; index += 1) reconciler.frameChanged(`k${index}`);
    await reconciler.whenIdle();

    // RV2: this pinned no read after the refresh; k0's 503 left it failed and uncached, so the refresh confirms it once.
    expect(answered.urls.slice(BUCKET_URLS.length)).toEqual(['/api/work-items/k0', ...BUCKET_URLS, '/api/work-items/k0']);
    release();
  });

  it('invalidateAll refreshes every bucket while interested', async () => {
    const answered = serve(url => (url.startsWith('/api/work-items?') ? emptyPage() : reply(503, {})));
    const { meta, reconciler } = harness(answered.fetch);
    const release = reconciler.acquireInterest();
    await reconciler.whenIdle();
    reconciler.invalidate('in-flight');
    for (let index = 0; index <= WORK_ITEM_QUEUE_LIMIT; index += 1) reconciler.invalidate(`k${index}`);
    await reconciler.whenIdle();

    // RV2: this pinned no read after the refresh; the in-flight 503 left it failed and uncached, so it is confirmed once.
    expect(answered.urls.slice(BUCKET_URLS.length)).toEqual([
      '/api/work-items/in-flight', ...BUCKET_URLS, '/api/work-items/in-flight',
    ]);
    // The whole cache was stale until the refresh read every bucket again.
    expect(meta.filter(([key]) => key === WORK_ITEMS_CACHE_KEY)).toEqual([
      [WORK_ITEMS_CACHE_KEY, null], [WORK_ITEMS_CACHE_KEY, 'stale'], [WORK_ITEMS_CACHE_KEY, null],
    ]);
    release();
  });

  it('forgets interest and bucket metadata when the live-read session resets', async () => {
    const answered = serve(emptyPage);
    const { reconciler } = harness(answered.fetch);
    reconciler.acquireInterest();
    await reconciler.whenIdle();

    resetLiveReadFenceForTests();
    reconciler.frameChanged('x');
    await reconciler.whenIdle();

    expect(answered.urls).toEqual(BUCKET_URLS);
    expect(scope(reconciler, bucketKey('open'))).toEqual(IDLE_SCOPE_META);
  });

  it('a released interest is released once', async () => {
    const answered = serve(url => (url.startsWith('/api/work-items?') ? emptyPage() : reply(503, {})));
    const { reconciler } = harness(answered.fetch);
    const release = reconciler.acquireInterest();
    const held = reconciler.acquireInterest();
    await reconciler.whenIdle();
    release();
    release();
    reconciler.observeItemEpoch();
    await reconciler.whenIdle();

    // The second interest still holds, so the epoch refreshed instead of only marking stale.
    expect(answered.urls).toEqual([...BUCKET_URLS, ...BUCKET_URLS]);
    held();
  });

  it('profile interest reads the assignee scopes and confirms their omissions by ID', async () => {
    const mine = { ...wire('mine', 'in_progress'), assigned_to: 'a1' };
    const cached = [mine as unknown as WorkItemView];
    const answered = serve((url) => {
      if (url === '/api/work-items?status=in_progress&limit=101') return reply(200, page([mine]));
      if (url.startsWith('/api/work-items?')) return emptyPage();
      return reply(200, { work_item: { ...mine, assigned_to: 'b2' } });
    });
    const { applied, reconciler } = harness(answered.fetch, () => cached);
    const release = reconciler.acquireInterest('a1');
    await reconciler.whenIdle();

    expect(answered.urls).toEqual([...BUCKET_URLS, ASSIGNEE_URL, ASSIGNEE_DONE_URL, '/api/work-items/mine']);
    expect(applied.flat().map(item => `${item.id}:${item.assigned_to}`)).toEqual(['mine:a1', 'mine:b2']);
    expect(scope(reconciler, assigneeScopeKey('a1', true))).toMatchObject({ status: 'empty', populated: true });
    release();
  });

  it('marks the assignee done scope truncated past its ten rows', async () => {
    const done = Array.from({ length: 11 }, (_, index) => ({ ...wire(`d${index}`, 'done'), assigned_to: 'a1' }));
    const answered = serve(url => (url === ASSIGNEE_DONE_URL ? reply(200, page(done)) : emptyPage()));
    const { reconciler } = harness(answered.fetch);
    const release = reconciler.acquireInterest('a1');
    await reconciler.whenIdle();

    expect(scope(reconciler, assigneeScopeKey('a1', true))).toMatchObject({ status: 'ready', truncated: true });
    expect(scope(reconciler, assigneeScopeKey('a1', false))).toMatchObject({ status: 'empty', truncated: false });
    release();
  });

  it('a row assigned to someone else invalidates the assignee page', async () => {
    const answered = serve(url => (url === ASSIGNEE_URL
      ? reply(200, page([{ ...wire('theirs', 'open'), assigned_to: 'b2' }]))
      : emptyPage()));
    const { applied, reconciler } = harness(answered.fetch);
    const release = reconciler.acquireInterest('a1');
    await reconciler.whenIdle();

    expect(applied).toEqual([]);
    expect(scope(reconciler, assigneeScopeKey('a1', false))).toMatchObject({ status: 'failed', populated: false });
    release();
  });

  it('notifies subscribers when scope metadata changes', async () => {
    const answered = serve(emptyPage);
    const { reconciler } = harness(answered.fetch);
    const listener = vi.fn();
    const unsubscribe = reconciler.subscribe(listener);
    const release = reconciler.acquireInterest();
    await reconciler.whenIdle();
    unsubscribe();
    const seen = listener.mock.calls.length;
    reconciler.observeItemEpoch();
    await reconciler.whenIdle();

    expect(seen).toBeGreaterThan(0);
    expect(listener).toHaveBeenCalledTimes(seen);
    release();
  });

  it.each([401, 403])('a bucket %s issued before an epoch neither refuses the population nor confirms by ID; its re-read decides', async (status) => {
    const draftUrl = BUCKET_URLS[0];
    const urls: string[] = [];
    let refuse!: (response: Response) => void;
    const { removed, reconciler } = harness(async (url) => {
      urls.push(url);
      if (urls.length === 1) return new Promise<Response>((resolve) => { refuse = resolve; });
      if (url === draftUrl) return reply(200, page([wire('d1', 'draft')]));
      return url.startsWith('/api/work-items?') ? emptyPage() : reply(status, { detail: 'denied' });
    }, () => [view('d1', 'draft')]);
    const release = reconciler.acquireInterest();
    // Premise: the draft bucket read is in flight when the epoch arrives.
    expect(urls).toEqual([draftUrl]);
    reconciler.observeItemEpoch();
    refuse(reply(status, { detail: 'denied' }));
    await reconciler.whenIdle();

    expect(urls).toEqual([...BUCKET_URLS, draftUrl]);
    expect(removed).toEqual([]);
    expect(scope(reconciler, bucketKey('draft'))).toMatchObject({ status: 'ready', populated: true, stale: false });
    expect(workItemCacheState(reconciler.scopes)).toBe('ready');
    release();
  });

  describe('by-ID read failures and displayed freshness (RV1)', () => {
    const outstanding: WorkItemScopeMeta = { ...IDLE_SCOPE_META, status: 'failed', populated: true, stale: true };

    it.each([
      ['a 503', 503, { detail: 'Workforce engine not enabled' }],
      ['an invalid body', 200, { work_item: { id: 'x' } }],
      ['a current 401', 401, { detail: 'denied' }],
    ])('%s by ID leaves a fresh population last known until that item reads fresh', async (_name, code, body) => {
      let byId = 0;
      const answered = serve((url) => {
        if (url.startsWith('/api/work-items?')) return emptyPage();
        byId += 1;
        return byId === 1 ? reply(code, body) : reply(200, { work_item: wire('x', 'open') });
      });
      const { reconciler } = harness(answered.fetch);
      const release = reconciler.acquireInterest();
      await reconciler.whenIdle();
      // Premise: the nine buckets read fresh, so the population alone says ready.
      expect(workItemCacheState(reconciler.scopes)).toBe('ready');

      reconciler.frameChanged('x');
      await reconciler.whenIdle();
      expect(workItemCacheState(reconciler.scopes)).toBe('stale');

      reconciler.frameChanged('x');
      await reconciler.whenIdle();
      expect(answered.urls.slice(BUCKET_URLS.length)).toEqual(['/api/work-items/x', '/api/work-items/x']);
      expect(workItemCacheState(reconciler.scopes)).toBe('ready');
      release();
    });

    it.each([
      ['a refresh that serves it', (reconciler: WorkItemReconciler) => reconciler.observeItemEpoch()],
      ['a snapshot row', (reconciler: WorkItemReconciler) => reconciler.applySnapshotRows([wire('x', 'open')])],
    ] as const)('%s clears the by-ID failure of that item', async (_name, recover) => {
      const answered = serve((url) => {
        if (url === '/api/work-items?status=open&limit=101') return reply(200, page([wire('x', 'open')]));
        return url.startsWith('/api/work-items?') ? emptyPage() : reply(503, {});
      });
      const { reconciler } = harness(answered.fetch);
      const release = reconciler.acquireInterest();
      await reconciler.whenIdle();
      reconciler.frameChanged('x');
      await reconciler.whenIdle();
      // The failure shows first, so the clearing below is observable.
      expect(workItemCacheState(reconciler.scopes)).toBe('stale');

      recover(reconciler);
      await reconciler.whenIdle();

      expect(reconciler.scopes.has(ITEM_READS_KEY)).toBe(false);
      expect(workItemCacheState(reconciler.scopes)).toBe('ready');
      release();
    });

    it.each<[string, WorkItemCacheState, Partial<WorkItemScopeMeta>]>([
      ['every bucket fresh', 'stale', { status: 'empty', populated: true }],
      ['a refused bucket', 'unauthorized', { status: 'unauthorized' }],
      ['a first load in flight', 'loading', { status: 'loading' }],
      ['a first load that failed', 'unavailable', { status: 'unavailable' }],
      ['nothing requested', 'idle', {}],
    ])('with a by-ID failure outstanding and %s, the cache state is %s', (_name, expected, bucketMeta) => {
      const scopes = new Map<string, WorkItemScopeMeta>(WORK_ITEM_BUCKETS.map(status => [
        bucketKey(status), { ...IDLE_SCOPE_META, ...bucketMeta },
      ]));
      scopes.set(ITEM_READS_KEY, outstanding);

      expect(workItemCacheState(scopes)).toBe(expected);
    });

    it('derives a surface state from the scopes it names, with the same by-ID rule', () => {
      const keys = [assigneeScopeKey('a1', false), assigneeScopeKey('a1', true)];
      const fresh: WorkItemScopeMeta = { ...IDLE_SCOPE_META, status: 'ready', populated: true };
      const scopes = new Map<string, WorkItemScopeMeta>(keys.map(key => [key, fresh]));
      // Premise: no status bucket was read, so the population state is idle.
      expect(workItemCacheState(scopes)).toBe('idle');
      expect(workItemCacheState(scopes, keys)).toBe('ready');

      scopes.set(ITEM_READS_KEY, outstanding);

      expect(workItemCacheState(scopes, keys)).toBe('stale');
    });

    it('forgets by-ID failures when the live-read session resets', async () => {
      const answered = serve(url => (url.startsWith('/api/work-items?') ? emptyPage() : reply(503, {})));
      const { reconciler } = harness(answered.fetch);
      reconciler.acquireInterest();
      await reconciler.whenIdle();
      reconciler.frameChanged('x');
      await reconciler.whenIdle();
      // The failure is outstanding before the reset.
      expect(reconciler.scopes.get(ITEM_READS_KEY)?.stale).toBe(true);

      resetLiveReadFenceForTests();
      const release = reconciler.acquireInterest();
      await reconciler.whenIdle();
      expect(reconciler.scopes.has(ITEM_READS_KEY)).toBe(false);
      expect(workItemCacheState(reconciler.scopes)).toBe('ready');

      // A failure in the new session still shows; nothing left from the old one masks it.
      reconciler.frameChanged('y');
      await reconciler.whenIdle();
      expect(workItemCacheState(reconciler.scopes)).toBe('stale');
      release();
    });

    it('RV2 a refresh with more uncached failures than the queue holds confirms without overflowing into a refresh', async () => {
      let bucketReads = 0;
      // Past two refreshes a bucket read fails, so a refresh the confirming reads caused would end, not repeat.
      const answered = serve((url) => {
        if (!url.startsWith('/api/work-items?')) return reply(503, {});
        bucketReads += 1;
        return bucketReads <= 2 * BUCKET_URLS.length ? emptyPage() : reply(503, {});
      });
      const { meta, reconciler } = harness(answered.fetch);
      const release = reconciler.acquireInterest();
      await reconciler.whenIdle();
      for (const batch of ['a', 'b']) {
        for (let index = 0; index < 150; index += 1) reconciler.invalidate(`${batch}${index}`);
        await reconciler.whenIdle();
      }
      // Premise: more failed, uncached IDs than the queue holds.
      const failed = new Set(meta.filter(([key, state]) => key.startsWith('item:') && state === 'stale').map(([key]) => key));
      expect(failed.size).toBe(300);
      expect(failed.size).toBeGreaterThan(WORK_ITEM_QUEUE_LIMIT);

      reconciler.observeItemEpoch();
      await reconciler.whenIdle();

      expect(bucketReads).toBe(2 * BUCKET_URLS.length);
      // RV3: this pinned WORK_ITEM_QUEUE_LIMIT confirming reads in the normal queue, where they starved live frames; they now wait apart.
      expect(answered.urls.filter(url => !url.startsWith('/api/work-items?'))).toHaveLength(300 + WORK_ITEM_CONFIRM_LIMIT);
      expect(meta.filter(([key]) => key === WORK_ITEMS_CACHE_KEY)).toEqual([
        [WORK_ITEMS_CACHE_KEY, null], [WORK_ITEMS_CACHE_KEY, 'stale'], [WORK_ITEMS_CACHE_KEY, null],
      ]);
      release();
    });

    it('RV3 each complete refresh schedules at most 32 confirming reads, and successive refreshes reach every orphaned ID', async () => {
      const answered = serve(url => (url.startsWith('/api/work-items?') ? emptyPage() : reply(503, {})));
      const { reconciler } = harness(answered.fetch);
      const release = reconciler.acquireInterest();
      await reconciler.whenIdle();
      const orphaned = Array.from({ length: 70 }, (_, index) => `/api/work-items/f${index}`);
      for (let index = 0; index < orphaned.length; index += 1) reconciler.invalidate(`f${index}`);
      await reconciler.whenIdle();
      // Premise: more failed, uncached IDs than two refreshes confirm.
      expect(WORK_ITEM_CONFIRM_LIMIT).toBe(32);
      expect(answered.urls.slice(BUCKET_URLS.length)).toEqual(orphaned);

      const confirmed: string[][] = [];
      for (let refresh = 0; refresh < 3; refresh += 1) {
        const before = answered.urls.length;
        reconciler.observeItemEpoch();
        await reconciler.whenIdle();
        expect(answered.urls.slice(before, before + BUCKET_URLS.length)).toEqual(BUCKET_URLS);
        confirmed.push(answered.urls.slice(before + BUCKET_URLS.length));
      }

      expect(confirmed.map(reads => reads.length)).toEqual([32, 32, 32]);
      // Fair: every orphaned ID is confirmed once before any is confirmed twice.
      expect(confirmed.flat().slice(0, orphaned.length).sort()).toEqual([...orphaned].sort());
      release();
    });

    it.each([
      ['queued when the refresh completes', BUCKET_URLS[BUCKET_URLS.length - 1], 0],
      ['waiting for its confirming read', '/api/work-items/f0', 1],
    ] as const)('RV3 an orphaned ID invalidated while %s is read once, ahead of every other confirming read', async (_name, heldUrl, position) => {
      let armed = false;
      let releaseHeld!: (response: Response) => void;
      const urls: string[] = [];
      const { reconciler } = harness(async (url) => {
        urls.push(url);
        if (armed && url === heldUrl) {
          armed = false;
          return new Promise<Response>((resolve) => { releaseHeld = resolve; });
        }
        return url.startsWith('/api/work-items?') ? emptyPage() : reply(503, {});
      });
      const release = reconciler.acquireInterest();
      await reconciler.whenIdle();
      for (let index = 0; index < 40; index += 1) reconciler.invalidate(`f${index}`);
      await reconciler.whenIdle();
      const refreshAt = urls.length;
      armed = true;
      reconciler.observeItemEpoch();
      await vi.waitFor(() => expect(armed).toBe(false));
      reconciler.invalidate('f5');
      releaseHeld(heldUrl.startsWith('/api/work-items?') ? emptyPage() : reply(503, {}));
      await reconciler.whenIdle();

      const byId = urls.slice(refreshAt).filter(url => !url.startsWith('/api/work-items?'));
      expect(byId.filter(url => url === '/api/work-items/f5')).toHaveLength(1);
      expect(byId.indexOf('/api/work-items/f5')).toBe(position);
      release();
    });

    it('RV3 a confirming read an epoch voids is dropped, never queued again', async () => {
      let armed = false;
      let releaseHeld!: (response: Response) => void;
      const urls: string[] = [];
      const { removed, reconciler } = harness(async (url) => {
        urls.push(url);
        if (armed && url === '/api/work-items/x') {
          armed = false;
          return new Promise<Response>((resolve) => { releaseHeld = resolve; });
        }
        return url.startsWith('/api/work-items?') ? emptyPage() : reply(503, {});
      });
      const release = reconciler.acquireInterest();
      await reconciler.whenIdle();
      reconciler.invalidate('x');
      await reconciler.whenIdle();
      armed = true;
      reconciler.observeItemEpoch();
      await vi.waitFor(() => expect(armed).toBe(false));
      const heldAt = urls.length;
      // Without interest this epoch only marks the cache stale, so nothing else reads x.
      release();
      reconciler.observeItemEpoch();
      releaseHeld(reply(404, { detail: 'Work item not found' }));
      await reconciler.whenIdle();

      expect(urls.slice(heldAt)).toEqual([]);
      expect(removed).toEqual([]);
      expect(reconciler.scopes.has(ITEM_READS_KEY)).toBe(true);
    });

    it('RV3 a live-read session reset forgets the confirming reads still waiting', async () => {
      let armed = false;
      let releaseHeld!: (response: Response) => void;
      const urls: string[] = [];
      const { reconciler } = harness(async (url) => {
        urls.push(url);
        if (armed && url === '/api/work-items/x0') {
          armed = false;
          return new Promise<Response>((resolve) => { releaseHeld = resolve; });
        }
        return url.startsWith('/api/work-items?') ? emptyPage() : reply(503, {});
      });
      reconciler.acquireInterest();
      await reconciler.whenIdle();
      for (const id of ['x0', 'x1', 'x2']) reconciler.invalidate(id);
      await reconciler.whenIdle();
      armed = true;
      reconciler.observeItemEpoch();
      await vi.waitFor(() => expect(armed).toBe(false));
      const heldAt = urls.length;

      resetLiveReadFenceForTests();
      releaseHeld(reply(503, {}));
      await reconciler.whenIdle();

      expect(urls.slice(heldAt)).toEqual([]);
    });
  });
});

describe('useStore work-item wiring (issue #1375)', () => {
  // Records only by-ID and parent-scope URLs; snapshots and resyncs also poll /api/recreation/active.
  // M3: status buckets answer empty so a test can populate the cache without recording them.
  function answer(respond: (url: string) => Response | Promise<Response>): string[] {
    const urls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (!url.startsWith('/api/work-items')) return reply(404, {});
      if (url.startsWith('/api/work-items?status=')) return reply(200, page([]));
      urls.push(url);
      return respond(url);
    }));
    return urls;
  }

  // M3 gates frames on interest: a loaded, fresh cache nobody watches any more still reads them.
  async function populated(): Promise<void> {
    const release = workItemReconciler.acquireInterest();
    await workItemReconciler.whenIdle();
    release();
  }

  beforeEach(() => {
    useStore.setState({ workItems: null, workBookings: null, liveGeneration: GENERATION, liveSequence: 0 });
  });

  it('never writes a done payload when REST says failed', async () => {
    const statuses: string[] = [];
    const unsubscribe = useStore.subscribe((state) => {
      for (const item of state.workItems ?? []) if (item.id === 'x') statuses.push(item.status);
    });
    answer(() => reply(200, { work_item: wire('x', 'failed', 2) }));
    await populated();
    try {
      useStore.getState().handleEvent(frame('work_item_updated', { work_item: wire('x', 'done', 3) }, 1));
      await workItemReconciler.whenIdle();
    } finally {
      unsubscribe();
    }
    expect(statuses).not.toContain('done');
    expect(useStore.getState().workItems?.map(item => item.status)).toEqual(['failed']);
  });

  it.each([
    'work_item_created', 'work_item_updated', 'work_item_status_changed',
    'work_item_assigned', 'work_item_claimed',
  ])('%s reads the record by ID instead of applying the payload', async (type) => {
    const urls = answer(() => reply(503, {}));
    await populated();
    useStore.getState().handleEvent(frame(type, { work_item: wire('x', 'open') }, 1));
    await workItemReconciler.whenIdle();
    expect(urls).toEqual(['/api/work-items/x']);
    expect(useStore.getState().workItems).toBeNull();
  });

  it('keeps the booking upsert on work_item_assigned', async () => {
    answer(() => reply(503, {}));
    const booking = { id: 'b-1', resource_id: 'worker-a', work_item_id: 'x' } as unknown as BookingView;
    useStore.getState().handleEvent(frame('work_item_assigned', { work_item: wire('x', 'scheduled'), booking }, 1));
    await workItemReconciler.whenIdle();
    expect(useStore.getState().workBookings).toEqual([booking]);
  });

  it('removes a deleted item only after its by-ID read returns 404', async () => {
    const urls = answer(() => reply(404, { detail: 'Work item not found' }));
    await populated();
    useStore.setState({ workItems: [view('x', 'open'), view('y', 'open')] });
    useStore.getState().handleEvent(frame('work_item_deleted', { work_item_id: 'x' }, 1));
    expect(useStore.getState().workItems?.map(item => item.id)).toEqual(['x', 'y']);
    await workItemReconciler.whenIdle();
    expect(urls).toEqual(['/api/work-items/x']);
    expect(useStore.getState().workItems?.map(item => item.id)).toEqual(['y']);
  });

  // RV1: the reviewer's probe, through handleEvent; the older refusal must not remove x.
  it.each([401, 403])('an older %s cannot remove the item a newer frame re-reads; a 503 re-read keeps it, stale', async (status) => {
    let release!: (response: Response) => void;
    const urls = answer(() => (urls.length === 1
      ? new Promise<Response>((resolve) => { release = resolve; })
      : reply(503, {})));
    await populated();
    useStore.setState({ workItems: [view('x', 'in_progress')], workItemReadStates: new Map() });
    useStore.getState().handleEvent(frame('work_item_status_changed', { work_item: wire('x', 'in_progress') }, 1));
    await vi.waitFor(() => expect(urls).toHaveLength(1));
    useStore.getState().handleEvent(frame('work_item_status_changed', { work_item: wire('x', 'failed') }, 2));
    release(reply(status, { detail: 'denied' }));
    await workItemReconciler.whenIdle();

    expect(urls).toEqual(['/api/work-items/x', '/api/work-items/x']);
    expect(useStore.getState().workItems?.map(item => item.id)).toEqual(['x']);
    expect(useStore.getState().workItemReadStates.get(workItemKey('x'))).toBe('stale');
  });

  it.each([401, 403])('a current %s still removes the item and marks it unauthorized', async (status) => {
    const urls = answer(() => reply(status, { detail: 'denied' }));
    await populated();
    useStore.setState({ workItems: [view('x', 'in_progress'), view('y', 'open')], workItemReadStates: new Map() });
    useStore.getState().handleEvent(frame('work_item_status_changed', { work_item: wire('x', 'failed') }, 1));
    await workItemReconciler.whenIdle();

    expect(urls).toEqual(['/api/work-items/x']);
    expect(useStore.getState().workItems?.map(item => item.id)).toEqual(['y']);
    expect(useStore.getState().workItemReadStates.get(workItemKey('x'))).toBe('unauthorized');
  });

  it('upserts snapshot rows without removing records the snapshot omits', async () => {
    useStore.setState({ workItems: [view('kept', 'review')] });
    const urls = answer(() => reply(503, {}));
    useStore.getState().handleEvent({
      type: 'state_snapshot', timestamp: 1, stream: { generation: GENERATION, sequence: 0 },
      data: {
        agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0,
        workforce: { work_items: [wire('seeded', 'open')], bookings: [], resources: [] },
      },
    });
    await workItemReconciler.whenIdle();
    expect(urls).toEqual([]);
    expect(useStore.getState().workItems?.map(item => item.id)).toEqual(['kept', 'seeded']);
  });

  it.each([
    ['a resync', () => frame('resync_required', {}, 2)],
    ['a sequence gap', () => frame('system_mode', { mode: 'active' }, 5)],
  ])('re-reads an in-flight item after %s', async (_name, next) => {
    let release!: (response: Response) => void;
    const urls = answer(() => (urls.length === 1
      ? new Promise<Response>((resolve) => { release = resolve; })
      : reply(200, { work_item: wire('x', 'failed', 2) })));
    await populated();
    useStore.getState().handleEvent(frame('work_item_status_changed', { work_item: wire('x', 'in_progress') }, 1));
    await vi.waitFor(() => expect(urls).toHaveLength(1));
    useStore.getState().handleEvent(next());
    release(reply(200, { work_item: wire('x', 'in_progress') }));
    await workItemReconciler.whenIdle();

    expect(urls).toEqual(['/api/work-items/x', '/api/work-items/x']);
    expect(useStore.getState().workItems?.map(item => item.status)).toEqual(['failed']);
  });

  it.each(['moveWorkItem', 'assignWorkItem'] as const)('a successful %s reads the item back', async (action) => {
    const urls = answer((url) => (url.endsWith('/x') ? reply(503, {}) : reply(200, {})));
    await useStore.getState()[action]('x', 'in_progress');
    await workItemReconciler.whenIdle();
    expect(urls.filter(url => url === '/api/work-items/x')).toHaveLength(1);
  });

  it.each(['moveWorkItem', 'assignWorkItem'] as const)('a refused %s reads nothing back', async (action) => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    const urls = answer(() => reply(409, { detail: 'refused' }));
    await useStore.getState()[action]('x', 'in_progress');
    await workItemReconciler.whenIdle();
    expect(urls.filter(url => url === '/api/work-items/x')).toEqual([]);
    expect(error).toHaveBeenCalled();
  });

  it('a crew_session_projection reads its parent scope, then the parent, even when the projection is dropped', async () => {
    const urls = answer(() => reply(503, {}));
    await populated();
    const cached = projectionData('p', 3).session as CrewSessionDetailProjection;
    useStore.setState({ liveCrewOwnerParentId: 'p', crewSessionsByParent: new Map([['p', cached]]) });
    try {
      useStore.getState().handleEvent(frame('crew_session_projection', projectionData('p', 2), 1));
      // Premise: the revision check dropped this projection.
      expect(useStore.getState().crewSessionsByParent.get('p')).toBe(cached);
      await workItemReconciler.whenIdle();
      expect(urls).toEqual([SCOPE_URL, '/api/work-items/p']);
    } finally {
      useStore.setState({ liveCrewOwnerParentId: null, crewSessionsByParent: new Map() });
    }
  });

  it.each([
    'work_item_created', 'work_item_updated', 'work_item_status_changed',
    'work_item_assigned', 'work_item_claimed',
  ])('%s for a child stamps crew:<parent> and publishes crewParentRefresh', async (type) => {
    answer(() => reply(503, {}));
    useStore.setState({ crewParentRefresh: null });
    const issuedBefore = liveReadFence.begin();
    useStore.getState().handleEvent(frame(type, { work_item: childWire('c', 'failed') }, 1));

    const refresh = useStore.getState().crewParentRefresh;
    expect(refresh?.parentId).toBe('p');
    expect(refresh!.stamp).toBeGreaterThan(issuedBefore);
    expect(liveReadFence.accepts('crew:p', issuedBefore)).toBe(false);
    expect(liveReadFence.accepts('crew:p', liveReadFence.begin())).toBe(true);
    await workItemReconciler.whenIdle();
  });

  it('successive child frames publish distinct refreshes with increasing stamps', async () => {
    answer(() => reply(503, {}));
    useStore.getState().handleEvent(frame('work_item_updated', { work_item: childWire('c', 'open') }, 1));
    const first = useStore.getState().crewParentRefresh;
    useStore.getState().handleEvent(frame('work_item_updated', { work_item: childWire('c', 'failed') }, 2));
    const second = useStore.getState().crewParentRefresh;

    expect(second).not.toBe(first);
    expect(second!.stamp).toBeGreaterThan(first!.stamp);
    await workItemReconciler.whenIdle();
  });

  it('a parentless work-item frame publishes no crewParentRefresh', async () => {
    answer(() => reply(503, {}));
    useStore.setState({ crewParentRefresh: null });
    useStore.getState().handleEvent(frame('work_item_updated', { work_item: wire('x', 'open') }, 1));
    expect(useStore.getState().crewParentRefresh).toBeNull();
    await workItemReconciler.whenIdle();
  });

  it('drops a duplicate frame and coalesces different sequences into one read', async () => {
    let release!: (response: Response) => void;
    const urls = answer(() => (urls.length === 1
      ? new Promise<Response>((resolve) => { release = resolve; })
      : reply(200, { work_item: wire('x', 'failed', 2) })));
    await populated();
    const changed = (sequence: number): WSEvent => frame(
      'work_item_status_changed', { work_item: wire('x', 'in_progress') }, sequence,
    );
    useStore.getState().handleEvent(changed(1));
    await vi.waitFor(() => expect(urls).toHaveLength(1));
    const drops = useStore.getState().liveDropCount;
    useStore.getState().handleEvent(changed(1));
    // Premise: the replay guard dropped the duplicate before any work-item handler saw it.
    expect(useStore.getState().liveDropCount).toBe(drops + 1);
    useStore.getState().handleEvent(changed(2));
    useStore.getState().handleEvent(changed(3));
    release(reply(200, { work_item: wire('x', 'in_progress') }));
    await workItemReconciler.whenIdle();

    expect(urls).toEqual(['/api/work-items/x', '/api/work-items/x']);
    expect(useStore.getState().workItems?.map(item => item.status)).toEqual(['failed']);
  });

  it('without interest a work-item frame, a projection and an epoch read nothing', async () => {
    const urls = answer(() => reply(503, {}));
    useStore.getState().handleEvent(frame('work_item_status_changed', { work_item: wire('x', 'failed') }, 1));
    useStore.getState().handleEvent(frame('crew_session_projection', projectionData('p', 1), 2));
    useStore.getState().handleEvent(frame('resync_required', {}, 3));
    await workItemReconciler.whenIdle();

    expect(urls).toEqual([]);
    useStore.setState({ crewSessionSummariesByThread: new Map(), roomSummariesByThread: new Map() });
  });

  describe('a refused item that a complete refresh cannot see (RV2)', () => {
    let release: (() => void) | null = null;

    afterEach(() => {
      release?.();
      release = null;
    });

    // The reviewer's sequence: nine fresh buckets, a current 401 by ID drops x, then a resync re-reads every bucket without x.
    async function refusedThenRefreshed(confirming: () => Response): Promise<{ buckets: string[]; items: string[] }> {
      const reads = { buckets: [] as string[], items: [] as string[] };
      vi.stubGlobal('fetch', vi.fn(async (url: string) => {
        if (!url.startsWith('/api/work-items')) return reply(404, {});
        if (url.startsWith('/api/work-items?status=')) {
          reads.buckets.push(url);
          return reply(200, page([]));
        }
        reads.items.push(url);
        return reads.items.length === 1 ? reply(401, { detail: 'denied' }) : confirming();
      }));
      release = workItemReconciler.acquireInterest();
      await workItemReconciler.whenIdle();
      useStore.setState({ workItems: [view('x', 'in_progress')], workItemReadStates: new Map() });
      useStore.getState().handleEvent(frame('work_item_status_changed', { work_item: wire('x', 'failed') }, 1));
      await workItemReconciler.whenIdle();
      // Premise: the current refusal dropped x and left the fresh population last known.
      expect(useStore.getState().workItems).toEqual([]);
      expect(useStore.getState().workItemReadStates.get(workItemKey('x'))).toBe('unauthorized');
      expect(workItemCacheState(workItemReconciler.scopes)).toBe('stale');

      useStore.getState().handleEvent(frame('resync_required', {}, 2));
      await workItemReconciler.whenIdle();
      // Premise: 18 successful bucket reads, none of which served x.
      expect(reads.buckets).toEqual([...BUCKET_URLS, ...BUCKET_URLS]);
      return reads;
    }

    it('RV2 a confirming 404 clears the refusal after one confirming read, and the cache reads ready', async () => {
      const reads = await refusedThenRefreshed(() => reply(404, { detail: 'Work item not found' }));

      expect(reads.items).toEqual(['/api/work-items/x', '/api/work-items/x']);
      expect(useStore.getState().workItemReadStates.has(workItemKey('x'))).toBe(false);
      expect(workItemReconciler.scopes.has(ITEM_READS_KEY)).toBe(false);
      expect(workItemCacheState(workItemReconciler.scopes)).toBe('ready');
    });

    it('RV2 a confirming 200 applies the record, and the cache reads ready', async () => {
      const reads = await refusedThenRefreshed(() => reply(200, { work_item: wire('x', 'failed', 2) }));

      expect(reads.items).toEqual(['/api/work-items/x', '/api/work-items/x']);
      expect(useStore.getState().workItems?.map(item => `${item.id}:${item.status}`)).toEqual(['x:failed']);
      expect(useStore.getState().workItemReadStates.has(workItemKey('x'))).toBe(false);
      expect(workItemCacheState(workItemReconciler.scopes)).toBe('ready');
    });

    it('RV2 a confirming 401 stays refused and last known, with one confirming read per refresh', async () => {
      const reads = await refusedThenRefreshed(() => reply(401, { detail: 'denied' }));
      expect(reads.items).toEqual(['/api/work-items/x', '/api/work-items/x']);
      expect(useStore.getState().workItemReadStates.get(workItemKey('x'))).toBe('unauthorized');
      // One item's refusal leaves the population last known; it never refuses the whole Board.
      expect(workItemCacheState(workItemReconciler.scopes)).toBe('stale');

      useStore.getState().handleEvent(frame('resync_required', {}, 3));
      await workItemReconciler.whenIdle();

      expect(reads.buckets).toHaveLength(3 * BUCKET_URLS.length);
      expect(reads.items).toEqual(['/api/work-items/x', '/api/work-items/x', '/api/work-items/x']);
      expect(workItemCacheState(workItemReconciler.scopes)).toBe('stale');
    });
  });

  describe('a live frame behind waiting confirming reads (RV3)', () => {
    let release: (() => void) | null = null;

    afterEach(() => {
      release?.();
      release = null;
    });

    // The reviewer's probe: more orphaned failures than the queue holds, a complete refresh, then one live frame.
    it('RV3 the frame is read before any further confirming read, with no overflow and no further refresh', async () => {
      const reads = { buckets: 0, items: [] as string[] };
      let hold = false;
      let releaseHeld!: (response: Response) => void;
      vi.stubGlobal('fetch', vi.fn(async (url: string) => {
        if (!url.startsWith('/api/work-items')) return reply(404, {});
        if (url.startsWith('/api/work-items?status=')) {
          reads.buckets += 1;
          return reply(200, page([]));
        }
        reads.items.push(url);
        if (hold) {
          hold = false;
          return new Promise<Response>((resolve) => { releaseHeld = resolve; });
        }
        return url === '/api/work-items/y' ? reply(200, { work_item: wire('y', 'review', 2) }) : reply(503, {});
      }));
      release = workItemReconciler.acquireInterest();
      await workItemReconciler.whenIdle();
      for (const batch of ['a', 'b']) {
        for (let index = 0; index < 150; index += 1) workItemReconciler.invalidate(`${batch}${index}`);
        await workItemReconciler.whenIdle();
      }
      // Premise: more failed IDs than the queue holds, none of them cached.
      expect(reads.items).toHaveLength(300);
      expect(reads.items.length).toBeGreaterThan(WORK_ITEM_QUEUE_LIMIT);
      expect(useStore.getState().workItems).toBeNull();

      hold = true;
      useStore.getState().handleEvent(frame('resync_required', {}, 1));
      await vi.waitFor(() => expect(reads.items).toHaveLength(301));
      // Premise: the refresh read every bucket, and its first confirming read is in flight.
      expect(reads.buckets).toBe(2 * BUCKET_URLS.length);
      useStore.getState().handleEvent(frame('work_item_status_changed', { work_item: wire('y', 'review') }, 2));
      releaseHeld(reply(503, {}));
      await workItemReconciler.whenIdle();

      expect(reads.items.slice(300, 302)).toEqual(['/api/work-items/a0', '/api/work-items/y']);
      expect(reads.items.filter(url => url === '/api/work-items/y')).toHaveLength(1);
      expect(reads.items).toHaveLength(301 + WORK_ITEM_CONFIRM_LIMIT);
      expect(reads.buckets).toBe(2 * BUCKET_URLS.length);
      expect(useStore.getState().workItems?.map(item => `${item.id}:${item.status}`)).toEqual(['y:review']);
    });
  });
});
