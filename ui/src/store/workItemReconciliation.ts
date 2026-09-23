/* Issue #1375: sole writer of HXI work-item records. Frames only invalidate an ID or a
 * parent's scope; the existing REST reads are the record source, fenced per key (I1-I5). */
import { useEffect, useSyncExternalStore } from 'react';

import type { LiveReadFence } from './liveReadFence';
import type { WorkItemView } from './types';
import { idleResource, requestResource } from '../utils/resourceState';
import type { ResourceState, ResourceStatus } from '../utils/resourceState';

export type WorkItemFetch = (url: string, init?: RequestInit) => Promise<Response>;

/** Why a cached record is not a fresh read: maybe outdated, kept after an invalid body, or dropped on 401/403. */
export type WorkItemReadState = 'stale' | 'failed' | 'unauthorized';

export type WorkItemBucket =
  | 'draft' | 'open' | 'scheduled' | 'in_progress' | 'review' | 'blocked' | 'failed' | 'done' | 'cancelled';

export type WorkItemRead =
  | { readonly kind: 'item'; readonly id: string }
  | { readonly kind: 'parent'; readonly parentId: string }
  | { readonly kind: 'bucket'; readonly status: WorkItemBucket }
  | { readonly kind: 'assignee'; readonly assignedTo: string; readonly done: boolean };

type ListRead = Exclude<WorkItemRead, { readonly kind: 'item' }>;

/** What the last read of a status bucket or assignee scope said, for rendering load state. */
export interface WorkItemScopeMeta {
  readonly status: ResourceStatus;
  readonly truncated: boolean;
  readonly observedAt: number | null;
  readonly populated: boolean;
  readonly stale: boolean;
}

export type WorkItemCacheState = 'idle' | 'loading' | 'ready' | 'unavailable' | 'unauthorized' | 'stale';

export interface WorkItemResponse {
  readonly work_item: WorkItemView;
}

export interface WorkItemListResponse {
  readonly work_items: readonly WorkItemView[];
  readonly count: number;
}

export interface WorkItemReconcilerDeps {
  readonly fetch: WorkItemFetch;
  readonly fence: LiveReadFence;
  readonly apply: (records: readonly WorkItemView[]) => void;
  readonly remove: (ids: readonly string[]) => void;
  readonly setMeta: (key: string, state: WorkItemReadState | null) => void;
  /** The records currently cached; a complete scope read confirms the ones it omits. */
  readonly cached: () => readonly WorkItemView[];
}

export const WORK_ITEM_QUEUE_LIMIT = 256;
// At most this many uncached failed IDs wait for a confirming read, behind every queued read.
export const WORK_ITEM_CONFIRM_LIMIT = 32;
// A scope read asks for one row more, so a page longer than this is known to be truncated.
export const WORK_ITEM_SCOPE_LIMIT = 1000;
export const WORK_ITEMS_CACHE_KEY = 'items';
// In the scopes while some by-ID read's last outcome was stale, failed or unauthorized.
export const ITEM_READS_KEY = 'item-reads';
// M3: the refresh reads each status bucket up to its cap, in this order.
export const WORK_ITEM_BUCKET_CAPS: Readonly<Record<WorkItemBucket, number>> = {
  draft: 100, open: 100, scheduled: 100, in_progress: 100, review: 100, blocked: 100, failed: 100,
  done: 20, cancelled: 20,
};
export const WORK_ITEM_BUCKETS = Object.keys(WORK_ITEM_BUCKET_CAPS) as readonly WorkItemBucket[];
// More queued frame reads than this collapse into one refresh.
export const WORK_ITEM_BURST_LIMIT = 20;
export const ASSIGNEE_SCOPE_LIMIT = 100;
export const ASSIGNEE_DONE_LIMIT = 10;

export const IDLE_SCOPE_META: WorkItemScopeMeta = {
  status: 'idle', truncated: false, observedAt: null, populated: false, stale: false,
};

export function workItemKey(id: string): string {
  return `item:${id}`;
}

export function parentScopeKey(parentId: string): string {
  return `scope:parent:${parentId}`;
}

// Bucket and assignee keys are `scope:` keys, so the item epoch fences them too.
export function bucketKey(status: WorkItemBucket): string {
  return `scope:status:${status}`;
}

export function assigneeScopeKey(assignedTo: string, done: boolean): string {
  return `scope:${done ? 'assignee-done' : 'assignee'}:${assignedTo}`;
}

const INITIAL_SCOPES: ReadonlyMap<string, WorkItemScopeMeta> = new Map(
  WORK_ITEM_BUCKETS.map(status => [bucketKey(status), IDLE_SCOPE_META]),
);

const BUCKET_KEYS: readonly string[] = WORK_ITEM_BUCKETS.map(bucketKey);

const ITEM_READS_OUTSTANDING: WorkItemScopeMeta = {
  status: 'failed', truncated: false, observedAt: null, populated: true, stale: true,
};

/** The single builder of work-item read URLs. */
export function workItemReadUrl(read: WorkItemRead): string {
  switch (read.kind) {
    case 'item':
      return `/api/work-items/${encodeURIComponent(read.id)}`;
    case 'parent':
      return `/api/work-items?parent_id=${encodeURIComponent(read.parentId)}&limit=${WORK_ITEM_SCOPE_LIMIT + 1}`;
    case 'bucket':
      return `/api/work-items?status=${read.status}&limit=${WORK_ITEM_BUCKET_CAPS[read.status] + 1}`;
    case 'assignee':
      return read.done
        ? `/api/work-items?assigned_to=${encodeURIComponent(read.assignedTo)}&status=done&limit=${ASSIGNEE_DONE_LIMIT + 1}`
        : `/api/work-items?assigned_to=${encodeURIComponent(read.assignedTo)}&limit=${ASSIGNEE_SCOPE_LIMIT + 1}`;
  }
}

function readKey(read: WorkItemRead): string {
  switch (read.kind) {
    case 'item': return workItemKey(read.id);
    case 'parent': return parentScopeKey(read.parentId);
    case 'bucket': return bucketKey(read.status);
    case 'assignee': return assigneeScopeKey(read.assignedTo, read.done);
  }
}

function listCap(read: ListRead): number {
  switch (read.kind) {
    case 'parent': return WORK_ITEM_SCOPE_LIMIT;
    case 'bucket': return WORK_ITEM_BUCKET_CAPS[read.status];
    case 'assignee': return read.done ? ASSIGNEE_DONE_LIMIT : ASSIGNEE_SCOPE_LIMIT;
  }
}

// A served row outside its read's scope voids the page; a cached record inside it may be omitted.
function inScope(read: ListRead, record: WorkItemView): boolean {
  switch (read.kind) {
    case 'parent': return record.parent_id === read.parentId;
    case 'bucket': return record.status === read.status;
    case 'assignee': return record.assigned_to === read.assignedTo && (!read.done || record.status === 'done');
  }
}

/** I6: a UI binding row, never displayed or counted (workforce.py _SCAFFOLD_EXCLUSION_SQL). */
export function isScaffoldWorkItem(item: WorkItemView): boolean {
  const flag = item.metadata.ui_scaffold;
  return flag === 1 || flag === true;
}

function isFailedStatus(status: ResourceStatus): boolean {
  return status === 'unavailable' || status === 'failed' || status === 'disabled';
}

/** Whether some by-ID read's last outcome was stale, failed or unauthorized. */
export function workItemReadsStale(scopes: ReadonlyMap<string, WorkItemScopeMeta>): boolean {
  return scopes.get(ITEM_READS_KEY)?.stale === true;
}

/** The load state of the reads behind a surface: the nine status buckets unless `keys` names other scopes. */
export function workItemCacheState(
  scopes: ReadonlyMap<string, WorkItemScopeMeta>,
  keys: readonly string[] = BUCKET_KEYS,
): WorkItemCacheState {
  const state = scopeCacheState(keys.map(key => scopes.get(key) ?? IDLE_SCOPE_META));
  // An outstanding by-ID failure makes fresh scopes last known; one item's refusal never refuses them all.
  return state === 'ready' && workItemReadsStale(scopes) ? 'stale' : state;
}

function scopeCacheState(metas: readonly WorkItemScopeMeta[]): WorkItemCacheState {
  if (metas.some(meta => meta.status === 'unauthorized')) return 'unauthorized';
  if (metas.every(meta => meta.populated && !meta.stale && !isFailedStatus(meta.status))) return 'ready';
  const failed = metas.some(meta => isFailedStatus(meta.status));
  if (!metas.some(meta => meta.populated)) {
    if (metas.some(meta => meta.status === 'loading')) return 'loading';
    return failed ? 'unavailable' : 'idle';
  }
  return failed || metas.some(meta => meta.stale) ? 'stale' : 'loading';
}

function sameMeta(a: WorkItemScopeMeta, b: WorkItemScopeMeta): boolean {
  return a.status === b.status && a.truncated === b.truncated && a.observedAt === b.observedAt
    && a.populated === b.populated && a.stale === b.stale;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isBoundedId(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= 128;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isNullableNumber(value: unknown): boolean {
  return value === null || isFiniteNumber(value);
}

function isNullableString(value: unknown): boolean {
  return value === null || typeof value === 'string';
}

function isStringArray(value: unknown): boolean {
  return Array.isArray(value) && value.every(item => typeof item === 'string');
}

function isDocument(value: unknown): boolean {
  return value === null || typeof value === 'string' || isRecord(value);
}

// Mirrors WorkItem.to_dict(); the wire sends null estimated_tokens and dict verification/schedule.
export function isWorkItemView(value: unknown): value is WorkItemView {
  return isRecord(value)
    && isBoundedId(value.id)
    && typeof value.title === 'string'
    && typeof value.description === 'string'
    && typeof value.work_type === 'string'
    && typeof value.status === 'string' && value.status.length > 0
    && isFiniteNumber(value.priority)
    && isNullableString(value.parent_id)
    && isNullableString(value.project_id)
    && isStringArray(value.depends_on)
    && isNullableString(value.assigned_to)
    && typeof value.created_by === 'string'
    && isFiniteNumber(value.created_at)
    && isFiniteNumber(value.updated_at)
    && isNullableNumber(value.due_at)
    && isNullableNumber(value.estimated_tokens)
    && isFiniteNumber(value.actual_tokens)
    && isFiniteNumber(value.trust_requirement)
    && isStringArray(value.required_capabilities)
    && isStringArray(value.tags)
    && isRecord(value.metadata)
    && Array.isArray(value.steps) && value.steps.every(isRecord)
    && isDocument(value.verification)
    && isDocument(value.schedule)
    && isNullableNumber(value.ttl_seconds)
    && isNullableString(value.template_id);
}

export function isWorkItemResponse(value: unknown): value is WorkItemResponse {
  return isRecord(value) && isWorkItemView(value.work_item);
}

// The `{work_items, count}` page GET /api/work-items serves; `count` is the page length.
export function isWorkItemListResponse(value: unknown): value is WorkItemListResponse {
  return isRecord(value)
    && Array.isArray(value.work_items) && value.work_items.every(isWorkItemView)
    && Number.isInteger(value.count) && value.count === value.work_items.length;
}

interface InterestToken {
  readonly assignedTo: string | null;
}

export class WorkItemReconciler {
  private readonly deps: WorkItemReconcilerDeps;
  private readonly pending = new Map<string, WorkItemRead>();
  // Queued by-ID reads a frame asked for; more than the burst limit collapse into one refresh.
  private readonly frameReads = new Set<string>();
  private readonly interests = new Set<InterestToken>();
  private readonly listeners = new Set<() => void>();
  // IDs whose last by-ID outcome was stale, failed or unauthorized.
  private readonly itemFailures = new Set<string>();
  // Uncached failed IDs waiting for one confirming read; never in `pending`, so never counted against its limit.
  private readonly confirmPending = new Set<string>();
  private scopeMetas = INITIAL_SCOPES;
  private session: number;
  private running = false;
  private idle: Promise<void> = Promise.resolve();
  private inFlight: AbortController | null = null;
  private inFlightKey: string | null = null;

  constructor(deps: WorkItemReconcilerDeps) {
    this.deps = deps;
    this.session = deps.fence.session;
  }

  /** Bucket and assignee read metadata; each status bucket is always present, `ITEM_READS_KEY` while a by-ID read failed. */
  get scopes(): ReadonlyMap<string, WorkItemScopeMeta> {
    return this.session === this.deps.fence.session ? this.scopeMetas : INITIAL_SCOPES;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  /** A surface shows the population (and optionally one assignee's work); returns its release. */
  acquireInterest(assignedTo: string | null = null): () => void {
    this.syncSession();
    const token: InterestToken = { assignedTo: isBoundedId(assignedTo) ? assignedTo : null };
    this.interests.add(token);
    if (!this.bucketsFresh()) this.refreshAll();
    if (token.assignedTo !== null) this.refreshAssignee(token.assignedTo, false);
    return () => { this.interests.delete(token); };
  }

  /** Reads the nine status buckets one at a time, each asking for one row past its cap. */
  refreshAll(): void {
    this.syncSession();
    for (const status of WORK_ITEM_BUCKETS) this.enqueueList({ kind: 'bucket', status });
  }

  /** A live frame says `id` changed; it is read by ID only while the cache is live. */
  frameChanged(id: string): void {
    if (!isBoundedId(id)) return;
    this.syncSession();
    const key = workItemKey(id);
    if (!this.isLive()) {
      // No read, but still fenced: an older read in flight must not apply.
      this.deps.fence.observe(key);
      return;
    }
    if (!this.pending.has(key)) {
      if (this.frameReads.size >= WORK_ITEM_BURST_LIMIT) {
        this.deps.fence.observe(key);
        this.collapseBurst();
        return;
      }
      this.frameReads.add(key);
    }
    this.invalidate(id);
  }

  /** A live projection for `parentId` arrived; its scope is read only while the cache is live. */
  frameScopeChanged(parentId: string): void {
    if (!isBoundedId(parentId)) return;
    this.syncSession();
    if (!this.isLive()) {
      this.deps.fence.observe(parentScopeKey(parentId));
      this.deps.fence.observe(workItemKey(parentId));
      return;
    }
    this.invalidateScope(parentId);
  }

  /** A live frame says `id` changed: fence older reads and queue one by-ID read. */
  invalidate(id: string): void {
    if (!isBoundedId(id)) return;
    this.syncSession();
    this.deps.fence.observe(workItemKey(id));
    this.enqueue({ kind: 'item', id });
  }

  /** A live projection for `parentId` arrived: queue a read of its children's scope, then of the parent by ID. */
  invalidateScope(parentId: string): void {
    if (!isBoundedId(parentId)) return;
    this.syncSession();
    this.deps.fence.observe(parentScopeKey(parentId));
    this.enqueue({ kind: 'parent', parentId });
    this.invalidate(parentId);
  }

  /** Too many changes to track one by one: drop the queue, then refresh or mark the cache stale. */
  invalidateAll(): void {
    this.syncSession();
    this.pending.clear();
    this.frameReads.clear();
    this.repair();
  }

  /** A snapshot, resync or gap: every item read issued before now is suspect. */
  observeItemEpoch(): void {
    this.syncSession();
    this.deps.fence.observeItemEpoch();
    this.repair();
  }

  /** I1: snapshot rows are a read issued on arrival; they upsert and never remove. */
  applySnapshotRows(rows: unknown): void {
    if (!Array.isArray(rows)) return;
    this.syncSession();
    const { fence } = this.deps;
    const issuedAt = fence.begin();
    const accepted: WorkItemView[] = [];
    for (const row of rows) {
      if (!isWorkItemView(row)) continue;
      if (fence.accepts(workItemKey(row.id), issuedAt)) accepted.push(row);
      else this.enqueue({ kind: 'item', id: row.id });
    }
    if (accepted.length === 0) return;
    this.deps.apply(accepted);
    for (const row of accepted) {
      fence.markApplied(workItemKey(row.id), issuedAt);
      this.setItemMeta(row.id, null);
    }
  }

  /** Resolves once no read is in flight or queued. */
  async whenIdle(): Promise<void> {
    while (this.running) await this.idle;
  }

  private syncSession(): void {
    const current = this.deps.fence.session;
    if (current === this.session) return;
    this.session = current;
    this.pending.clear();
    this.frameReads.clear();
    this.interests.clear();
    this.itemFailures.clear();
    this.confirmPending.clear();
    this.inFlight?.abort();
    this.inFlightKey = null;
    if (this.scopeMetas === INITIAL_SCOPES) return;
    this.scopeMetas = INITIAL_SCOPES;
    this.notify();
  }

  // Frames are read while a surface is interested, or while the loaded population is still fresh.
  private isLive(): boolean {
    return this.interests.size > 0 || this.bucketsFresh();
  }

  private bucketsFresh(): boolean {
    return WORK_ITEM_BUCKETS.every((status) => {
      const meta = this.scopeMetas.get(bucketKey(status));
      return meta !== undefined && meta.populated && !meta.stale;
    });
  }

  // A snapshot, resync, gap, overflow or burst: refresh what surfaces show, else only mark it stale.
  private repair(): void {
    this.markStale();
    if (this.interests.size === 0) return;
    this.refreshAll();
    const assignees = new Set([...this.interests].map(token => token.assignedTo));
    for (const assignedTo of assignees) {
      if (assignedTo !== null) this.refreshAssignee(assignedTo, true);
    }
  }

  private refreshAssignee(assignedTo: string, force: boolean): void {
    for (const done of [false, true]) {
      const meta = this.scopeMetas.get(assigneeScopeKey(assignedTo, done));
      if (force || meta === undefined || !meta.populated || meta.stale) {
        this.enqueueList({ kind: 'assignee', assignedTo, done });
      }
    }
  }

  private collapseBurst(): void {
    for (const key of this.frameReads) this.pending.delete(key);
    this.frameReads.clear();
    this.repair();
  }

  private markStale(): void {
    let next: Map<string, WorkItemScopeMeta> | null = null;
    for (const [key, meta] of this.scopeMetas) {
      if (!meta.populated || meta.stale) continue;
      next ??= new Map(this.scopeMetas);
      next.set(key, { ...meta, stale: true });
    }
    if (next !== null) {
      this.scopeMetas = next;
      this.notify();
    }
    this.deps.setMeta(WORK_ITEMS_CACHE_KEY, 'stale');
  }

  private setScope(key: string, meta: WorkItemScopeMeta): void {
    const current = this.scopeMetas.get(key);
    if (current !== undefined && sameMeta(current, meta)) return;
    const next = new Map(this.scopeMetas);
    next.set(key, meta);
    this.scopeMetas = next;
    this.notify();
  }

  private notify(): void {
    for (const listener of [...this.listeners]) listener();
  }

  // Every item read state goes through here, so the scopes say when a by-ID failure is outstanding.
  private setItemMeta(id: string, state: WorkItemReadState | null): void {
    this.deps.setMeta(workItemKey(id), state);
    const wasOutstanding = this.itemFailures.size > 0;
    if (state === null) this.itemFailures.delete(id);
    else this.itemFailures.add(id);
    if ((this.itemFailures.size > 0) === wasOutstanding) return;
    const next = new Map(this.scopeMetas);
    if (wasOutstanding) next.delete(ITEM_READS_KEY);
    else next.set(ITEM_READS_KEY, ITEM_READS_OUTSTANDING);
    this.scopeMetas = next;
    this.notify();
  }

  private enqueueList(read: ListRead): void {
    const key = readKey(read);
    if (read.kind !== 'parent') {
      this.setScope(key, { ...(this.scopeMetas.get(key) ?? IDLE_SCOPE_META), status: 'loading' });
    }
    // The read in flight answers for this one; an epoch since it was issued rejects and re-queues it.
    if (key === this.inFlightKey) return;
    this.enqueue(read);
  }

  private enqueue(read: WorkItemRead): void {
    const key = readKey(read);
    if (!this.pending.has(key) && this.pending.size >= WORK_ITEM_QUEUE_LIMIT) {
      this.invalidateAll();
      return;
    }
    // The queued read answers for a waiting confirming read of the same item.
    if (read.kind === 'item') this.confirmPending.delete(read.id);
    this.pending.set(key, read);
    if (this.running) return;
    this.running = true;
    this.idle = this.run();
  }

  private async run(): Promise<void> {
    try {
      for (;;) {
        this.syncSession();
        const next = this.takeNext();
        if (next === null) return;
        const { key, read, confirming } = next;
        this.inFlightKey = key;
        try {
          await (read.kind === 'item' ? this.readItem(read.id, confirming) : this.readList(read));
        } catch (error) {
          console.warn(
            'Issue #1375: reconciling %s failed (%s); its cached records are kept and '
            + 'the next invalidation re-reads them',
            key, error instanceof Error ? error.message : String(error),
          );
        } finally {
          this.inFlightKey = null;
        }
      }
    } finally {
      this.running = false;
    }
  }

  // Every queued read goes first; a confirming read runs only while none is queued.
  private takeNext(): { readonly key: string; readonly read: WorkItemRead; readonly confirming: boolean } | null {
    const queued = this.pending.entries().next();
    if (!queued.done) {
      const [key, read] = queued.value;
      this.pending.delete(key);
      this.frameReads.delete(key);
      return { key, read, confirming: false };
    }
    const waiting = this.confirmPending.values().next();
    if (waiting.done) return null;
    this.confirmPending.delete(waiting.value);
    return { key: workItemKey(waiting.value), read: { kind: 'item', id: waiting.value }, confirming: true };
  }

  // "Gone" is decided from the HTTP status the injected fetch saw, not from ResourceState.
  private async request<Data>(
    url: string,
    validate: (payload: unknown) => payload is Data,
  ): Promise<{ readonly result: ResourceState<Data> | null; readonly status: number | null }> {
    const controller = new AbortController();
    const seen: { status: number | null } = { status: null };
    const tracked: typeof fetch = async (input, init) => {
      const response = await this.deps.fetch(String(input), init);
      seen.status = response.status;
      return response;
    };
    this.inFlight = controller;
    try {
      const result = await requestResource(
        url, idleResource<Data>(url), validate, () => false, controller.signal, tracked,
      );
      return { result, status: seen.status };
    } finally {
      if (this.inFlight === controller) this.inFlight = null;
    }
  }

  private async readItem(id: string, confirming = false): Promise<void> {
    const { fence } = this.deps;
    const session = this.session;
    const read: WorkItemRead = { kind: 'item', id };
    const key = workItemKey(id);
    const issuedAt = fence.begin();
    const { result, status } = await this.request(workItemReadUrl(read), isWorkItemResponse);
    if (result === null || session !== fence.session) return;
    if (status === 404 || status === 410) {
      if (!this.admit(key, read, issuedAt, confirming)) return;
      this.deps.remove([id]);
      fence.markApplied(key, issuedAt);
      this.setItemMeta(id, null);
      return;
    }
    if (result.status === 'unauthorized') {
      // A superseded refusal waits for the newer read: delivered content is not newly disclosed; a current one drops it.
      if (!this.admit(key, read, issuedAt, confirming)) return;
      this.deps.remove([id]);
      fence.markApplied(key, issuedAt);
      this.setItemMeta(id, 'unauthorized');
      return;
    }
    const record = result.status === 'ready' ? result.data?.work_item : undefined;
    if (record !== undefined && record.id === id) {
      if (!this.admit(key, read, issuedAt, confirming)) return;
      this.deps.apply([record]);
      fence.markApplied(key, issuedAt);
      this.setItemMeta(id, null);
      return;
    }
    this.setItemMeta(id, result.status === 'unavailable' || result.status === 'disabled' ? 'stale' : 'failed');
  }

  private async readList(read: ListRead): Promise<void> {
    const { fence } = this.deps;
    const session = this.session;
    const key = readKey(read);
    const issuedAt = fence.begin();
    const { result } = await this.request(workItemReadUrl(read), isWorkItemListResponse);
    if (result === null || session !== fence.session) return;
    const rows = result.status === 'ready' ? result.data?.work_items : undefined;
    if (rows === undefined || rows.some(row => !inScope(read, row))) {
      if (result.status === 'unauthorized') {
        if (!this.admit(key, read, issuedAt)) return;
        // I5: a current 401/403 drops the content, one record at a time through its own by-ID read.
        this.confirmOmitted(read, new Set());
        this.deps.setMeta(key, 'unauthorized');
        this.recordFailure(read, 'unauthorized');
        return;
      }
      this.deps.setMeta(key, result.status === 'unavailable' || result.status === 'disabled' ? 'stale' : 'failed');
      this.recordFailure(read, rows === undefined ? result.status : 'failed');
      return;
    }
    // A newer scope invalidation or an item epoch voids the whole page; its re-read replaces it.
    if (!this.admit(key, read, issuedAt)) return;
    const accepted: WorkItemView[] = [];
    for (const row of rows) {
      if (fence.accepts(workItemKey(row.id), issuedAt)) accepted.push(row);
      else this.enqueue({ kind: 'item', id: row.id });
    }
    if (accepted.length > 0) this.deps.apply(accepted);
    for (const row of accepted) {
      fence.markApplied(workItemKey(row.id), issuedAt);
      this.setItemMeta(row.id, null);
    }
    const truncated = rows.length > listCap(read);
    if (!truncated) this.confirmOmitted(read, new Set(rows.map(row => row.id)));
    fence.markApplied(key, issuedAt);
    this.deps.setMeta(key, null);
    if (read.kind === 'parent') return;
    this.setScope(key, {
      status: rows.length === 0 ? 'empty' : 'ready', truncated, observedAt: result.observedAt,
      populated: true, stale: false,
    });
    if (read.kind === 'bucket' && this.bucketsFresh()) {
      this.deps.setMeta(WORK_ITEMS_CACHE_KEY, null);
      // The refresh is complete once no bucket read is queued behind this one.
      if (!BUCKET_KEYS.some(bucket => this.pending.has(bucket))) this.confirmUncachedFailures();
    }
  }

  private recordFailure(read: ListRead, status: ResourceStatus): void {
    if (read.kind === 'parent') return;
    const key = readKey(read);
    const meta = this.scopeMetas.get(key) ?? IDLE_SCOPE_META;
    this.setScope(key, { ...meta, status, stale: meta.populated });
  }

  // An omission is not a deletion: each cached record a complete read did not return is re-read by ID.
  private confirmOmitted(read: ListRead, present: ReadonlySet<string>): void {
    for (const record of this.deps.cached()) {
      // List reads never serve scaffold rows (S29), so their absence confirms nothing.
      if (inScope(read, record) && !present.has(record.id) && !isScaffoldWorkItem(record)) {
        this.enqueue({ kind: 'item', id: record.id });
      }
    }
  }

  // confirmOmitted only sees cached records, so failed IDs the cache no longer holds wait for a confirming read by ID.
  private confirmUncachedFailures(): void {
    const cached = new Set(this.deps.cached().map(record => record.id));
    const due = [...this.itemFailures].filter(id => !cached.has(id) && !this.pending.has(workItemKey(id)));
    for (const id of due.slice(0, WORK_ITEM_CONFIRM_LIMIT - this.confirmPending.size)) {
      this.confirmPending.add(id);
      // To the back, so the next refresh starts with the IDs this one skipped.
      this.itemFailures.delete(id);
      this.itemFailures.add(id);
    }
  }

  // I2: an outcome the fence rejects is not applied; the same read is queued again instead.
  private admit(key: string, read: WorkItemRead, issuedAt: number, confirming = false): boolean {
    if (this.deps.fence.accepts(key, issuedAt)) return true;
    // A voided confirming read is dropped: the ID stays failed, so a later complete refresh confirms it.
    if (!confirming) this.enqueue(read);
    return false;
  }
}

let bound: WorkItemReconciler | null = null;

/** Makes `reconciler` the one the work-surface hooks use, and returns it. */
export function bindWorkItemReconciler(reconciler: WorkItemReconciler): WorkItemReconciler {
  bound = reconciler;
  return reconciler;
}

/** Keeps the work-item population, and `assignedTo`'s work if given, loaded while mounted. */
export function useWorkItemInterest(assignedTo: string | null = null): void {
  useEffect(() => bound?.acquireInterest(assignedTo), [assignedTo]);
}

function subscribeBound(listener: () => void): () => void {
  return bound === null ? () => {} : bound.subscribe(listener);
}

function boundScopes(): ReadonlyMap<string, WorkItemScopeMeta> {
  return bound === null ? INITIAL_SCOPES : bound.scopes;
}

/** The bucket and assignee read metadata, for load state and truncation labels. */
export function useWorkItemScopes(): ReadonlyMap<string, WorkItemScopeMeta> {
  return useSyncExternalStore(subscribeBound, boundScopes);
}
