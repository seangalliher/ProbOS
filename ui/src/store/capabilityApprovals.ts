import type {
  ApprovalPayload, ApprovalQueue, CapabilityApprovalView, CapabilityDecisionOutcome,
} from './types';
import type { ResourceState } from '../utils/resourceState';

const FULFILMENT_KINDS = new Set(['grant', 'install', 'build', 'continue']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** Composite keys keep capability and skill tombstones independent. */
export function approvalKey(queue: ApprovalQueue, id: string): string {
  return `${queue}\u0000${id}`;
}

export function isCapabilityRequestView(value: unknown): value is CapabilityApprovalView {
  if (!isRecord(value)) return false;
  return ['id', 'agent_id', 'kind', 'target', 'rationale', 'decided_by', 'decision_reason']
    .every(key => typeof value[key] === 'string')
    && Boolean(value.id) && Boolean(value.agent_id) && Boolean(value.kind)
    && typeof value.created_at === 'number' && Number.isFinite(value.created_at)
    && (value.work_item_id === null || typeof value.work_item_id === 'string')
    && (value.decided_at === null || (typeof value.decided_at === 'number' && Number.isFinite(value.decided_at)))
    && (value.payload === null || isRecord(value.payload))
    && typeof value.status === 'string'
    && ['pending', 'approved', 'denied', 'fulfilled', 'failed'].includes(value.status)
    && typeof value.can_retry_fulfilment === 'boolean'
    && value.can_retry_fulfilment === (value.status === 'approved' && FULFILMENT_KINDS.has(String(value.kind)));
}

export function isActionableCapabilityPayload(value: unknown): value is ApprovalPayload {
  if (!isRecord(value) || value.view !== 'actionable' || !Array.isArray(value.requests)) return false;
  return value.requests.every(row => isCapabilityRequestView(row)
    && (row.status === 'pending' || row.can_retry_fulfilment))
    && new Set(value.requests.map(row => row.id)).size === value.requests.length;
}

export function parseCapabilityDecision(
  value: unknown, expected: CapabilityApprovalView, approve: boolean,
): CapabilityDecisionOutcome {
  if (!isRecord(value) || !isCapabilityRequestView(value.request) || typeof value.fulfilled !== 'boolean') {
    throw new Error('Invalid capability decision response; request state was not confirmed.');
  }
  const request = value.request;
  if (request.id !== expected.id || request.agent_id !== expected.agent_id
    || request.kind !== expected.kind || request.target !== expected.target
    || request.created_at !== expected.created_at || request.work_item_id !== expected.work_item_id
    || request.decided_at === null || !request.decided_by
    || (approve ? !['approved', 'fulfilled'].includes(request.status) : request.status !== 'denied')
    || value.fulfilled !== (request.status === 'fulfilled')
    || (value.fulfilled && !FULFILMENT_KINDS.has(request.kind))) {
    throw new Error('Inconsistent capability decision response; request state was not confirmed.');
  }
  return { request, fulfilled: value.fulfilled };
}

function capabilityRows(resource: ResourceState<ApprovalPayload>): CapabilityApprovalView[] {
  return resource.data?.requests.filter(isCapabilityRequestView) ?? [];
}

function withRows(
  resource: ResourceState<ApprovalPayload>, rows: CapabilityApprovalView[],
): ResourceState<ApprovalPayload> {
  const successful = resource.status === 'ready' || resource.status === 'empty';
  const status = rows.length ? 'ready' : 'empty';
  return {
    ...resource,
    data: { view: 'actionable', requests: rows },
    ...(successful ? { status, lastSuccess: status } : {}),
  };
}

export function applyCapabilityDecision(
  resource: ResourceState<ApprovalPayload>, tombstones: ReadonlySet<string>, outcome: CapabilityDecisionOutcome,
): { resource: ResourceState<ApprovalPayload>; tombstones: Set<string> } {
  const decided = new Set(tombstones);
  const request = outcome.request;
  const key = approvalKey('capability', request.id);
  const rows = capabilityRows(resource);
  if (request.can_retry_fulfilment) {
    // A later authoritative read may already have removed the work. A late POST
    // cannot recreate it, even after a spent terminal tombstone is retired.
    if (decided.has(key) || !rows.some(row => row.id === request.id)) return { resource, tombstones: decided };
    return {
      resource: withRows(resource, rows.map(row => row.id === request.id ? request : row)),
      tombstones: decided,
    };
  }
  decided.add(key);
  return {
    resource: resource.data === null ? resource : withRows(resource, rows.filter(row => row.id !== request.id)),
    tombstones: decided,
  };
}

export function reconcileCapabilityRead(
  outcome: ResourceState<ApprovalPayload>,
  current: ResourceState<ApprovalPayload>,
  tombstones: ReadonlySet<string>,
  preserveApproved: boolean,
): { resource: ResourceState<ApprovalPayload>; tombstones: Set<string> } {
  const decided = new Set(tombstones);
  const successful = outcome.status === 'ready' || outcome.status === 'empty';
  const previous = capabilityRows(current);
  const reported = capabilityRows(outcome);
  if (successful) {
    const ids = new Set(reported.map(row => approvalKey('capability', row.id)));
    for (const key of decided) {
      if (key.startsWith(approvalKey('capability', '')) && !ids.has(key)) decided.delete(key);
    }
  }
  if (outcome.data === null) return { resource: outcome, tombstones: decided };
  let rows = successful ? reported.map(row => {
    const newer = previous.find(candidate => candidate.id === row.id && candidate.can_retry_fulfilment);
    return row.status === 'pending' && newer ? newer : row;
  }) : previous;
  if (successful && preserveApproved) {
    const ids = new Set(rows.map(row => row.id));
    rows = [...rows, ...previous.filter(row => row.can_retry_fulfilment && !ids.has(row.id))];
  }
  // Filter against the pre-retirement set: this response cannot revive a
  // terminal decision simply by agreeing that its tombstone is now spent.
  rows = rows.filter(row => !tombstones.has(approvalKey('capability', row.id)));
  return {
    resource: withRows(outcome, rows),
    tombstones: decided,
  };
}
