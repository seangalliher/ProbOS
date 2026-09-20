import type {
  ApprovalPayload, ApprovalQueue, CapabilityApprovalView, CapabilityDecisionOutcome,
  CapabilityDecisionIntent, CapabilityDecisionFeedback, StandingRuleReceipt,
} from './types';
import type { ResourceState } from '../utils/resourceState';

const FULFILMENT_KINDS = new Set(['grant', 'install', 'build', 'continue']);
const ACTION_KEYS = ['tool_id', 'action', 'params', 'scope_key', 'session_id', 'thread_id'];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const INVISIBLE = /[\u0000-\u001f\u007f-\u009f\p{Cf}\u2028\u2029]/gu;

export interface InspectableAction {
  tool_id: string;
  action: string;
  params: Record<string, unknown>;
  scope_key: string;
  session_id: string | null;
  thread_id: string;
}

export type ActionInspection =
  | { ok: true; payload: InspectableAction; text: string }
  | { ok: false; issue: string };

/** Literal text only: even invisible characters must be visible to the reviewer. */
export function approvalDisplayText(text: string): string {
  return text.replace(INVISIBLE, character => {
    const code = character.codePointAt(0)!;
    return code <= 0xffff ? `\\u${code.toString(16).padStart(4, '0')}` : `\\u{${code.toString(16)}}`;
  });
}

/** Iterative compact JSON avoids recursion and indentation-amplification attacks. */
export function formatApprovalPayload(value: unknown): string {
  type Job = { value: unknown; depth: number } | { literal: string } | { leave: object };
  const jobs: Job[] = [{ value, depth: 0 }];
  const ancestors = new Set<object>();
  const parts: string[] = [];
  let nodes = 0;
  let bytes = 0;
  const encoder = new TextEncoder();
  const append = (text: string): void => {
    const visible = approvalDisplayText(text);
    bytes += encoder.encode(visible).length;
    if (bytes > 32_768) throw new Error('Complete escaped payload exceeds 32,768 UTF-8 bytes.');
    parts.push(visible);
  };
  while (jobs.length) {
    const job = jobs.pop()!;
    if ('literal' in job) { append(job.literal); continue; }
    if ('leave' in job) { ancestors.delete(job.leave); continue; }
    const item = job.value;
    if (++nodes > 4096 || job.depth > 2048) throw new Error('Payload exceeds 4,096 nodes or 2,048 levels.');
    if (item === null || typeof item === 'boolean') { append(String(item)); continue; }
    if (typeof item === 'string') {
      if (!validText(item)) throw new Error('Payload contains invalid Unicode.');
      append(JSON.stringify(item));
      continue;
    }
    if (typeof item === 'number') {
      if (!Number.isFinite(item) || (Number.isInteger(item) && !Number.isSafeInteger(item))) {
        throw new Error('Payload numbers must be finite; integers must be safe.');
      }
      append(Object.is(item, -0) ? '-0' : item.toString());
      continue;
    }
    if (typeof item !== 'object' || ancestors.has(item)) throw new Error('Payload must contain JSON data only.');
    const array = Array.isArray(item);
    const prototype = Object.getPrototypeOf(item);
    if (array ? prototype !== Array.prototype : prototype !== Object.prototype && prototype !== null) {
      throw new Error('Payload must contain JSON data only.');
    }
    const keys = Object.keys(item);
    if (Reflect.ownKeys(item).length !== keys.length + (array ? 1 : 0)
      || (array && keys.length !== item.length)) throw new Error('Payload must contain JSON data only.');
    if (nodes + keys.length > 4096) throw new Error('Payload exceeds 4,096 nodes or 2,048 levels.');
    ancestors.add(item);
    jobs.push({ leave: item }, { literal: array ? ']' : '}' });
    if (!array) keys.sort();
    for (let index = keys.length - 1; index >= 0; index -= 1) {
      const key = array ? String(index) : keys[index];
      const descriptor = Object.getOwnPropertyDescriptor(item, key);
      if (!descriptor || !('value' in descriptor) || !validText(key)) throw new Error('Payload must contain JSON data only.');
      jobs.push({ value: descriptor.value, depth: job.depth + 1 });
      if (!array) {
        if (++nodes > 4096) throw new Error('Payload exceeds 4,096 nodes or 2,048 levels.');
        jobs.push({ literal: `${JSON.stringify(key)}:` });
      }
      if (index > 0) jobs.push({ literal: ',' });
    }
    append(array ? '[' : '{');
  }
  return parts.join('');
}

export function inspectActionPayload(value: unknown): ActionInspection {
  try {
    const text = formatApprovalPayload(value);
    if (!isRecord(value) || Object.keys(value).length !== ACTION_KEYS.length
      || !ACTION_KEYS.every(key => Object.prototype.hasOwnProperty.call(value, key))
      || typeof value.tool_id !== 'string' || !/^[a-z0-9_:.-]{1,64}$/.test(value.tool_id)
      || typeof value.action !== 'string' || !/^[a-z0-9_]{1,64}$/.test(value.action)
      || !isRecord(value.params) || Object.keys(value.params).length > 20
      || !validText(value.scope_key, 253) || !validText(value.thread_id, 64)
      || !(value.session_id === null || validText(value.session_id, 64))) {
      return { ok: false, issue: 'Action payload must have the complete six-field action shape within its field bounds.' };
    }
    if (!hasPossibleActionPayloadSize(value)) {
      return { ok: false, issue: 'Action payload exceeds 4,000 canonical characters.' };
    }
    const payload: InspectableAction = {
      tool_id: value.tool_id,
      action: value.action,
      params: value.params,
      scope_key: value.scope_key,
      session_id: value.session_id,
      thread_id: value.thread_id,
    };
    return { ok: true, payload, text };
  } catch (error) {
    return { ok: false, issue: error instanceof Error ? error.message : 'Action payload is not inspectable.' };
  }
}

export function standingApprovalEligible(request: CapabilityApprovalView): boolean {
  return request.status === 'pending' && ['action', 'continue'].includes(request.kind)
    && request.payload?.tool_id !== 'repair';
}

export function standingApprovalPolicy(config: unknown): { maxHours: number; defaultHours: number; issue: null }
  | { maxHours: null; defaultHours: null; issue: string } {
  const policy = isRecord(config) ? config.approval_inbox : null;
  const unavailable = { maxHours: null, defaultHours: null } as const;
  if (!isRecord(policy)) return { ...unavailable, issue: 'Standing policy is unknown; settings are not available.' };
  if (policy.standing_rules_enabled === false) return { ...unavailable, issue: 'Standing approvals are disabled by policy.' };
  const max = policy.standing_rule_max_ttl_hours;
  const initial = policy.standing_rule_default_ttl_hours;
  if (policy.standing_rules_enabled !== true || typeof max !== 'number' || !Number.isSafeInteger(max) || max < 1
    || typeof initial !== 'number' || !Number.isSafeInteger(initial) || initial < 1) {
    return { ...unavailable, issue: 'Standing policy is unknown; its lifetime settings are invalid.' };
  }
  return { maxHours: max, defaultHours: Math.min(max, initial), issue: null };
}

export function capabilityDecisionBody(
  expected: CapabilityApprovalView, intent: CapabilityDecisionIntent, config: unknown,
): { approve: boolean; reason: string; grant_standing?: true; standing_ttl_hours?: number } {
  if (!isCapabilityRequestView(expected) || !isRecord(intent)
    || !['approve', 'deny', 'retry'].includes(intent.action)) throw new Error('Invalid capability decision intent.');
  if (intent.action === 'retry') {
    if (!expected.can_retry_fulfilment) throw new Error('Capability request is not eligible for fulfilment retry.');
    return { approve: true, reason: '' };
  }
  if (expected.status !== 'pending' || typeof intent.reason !== 'string') throw new Error('Capability request is no longer actionable.');
  const reason = intent.reason.trim();
  if (intent.action === 'deny') {
    if (!reason) throw new Error('A reason is required to deny.');
    return { approve: false, reason };
  }
  const inspection = inspectActionPayload(expected.payload);
  if (expected.kind === 'action' && expected.payload?.tool_id !== 'repair' && !inspection.ok) {
    throw new Error(`Approval disabled: ${inspection.issue}`);
  }
  if (intent.standingTtlHours === undefined) return { approve: true, reason };
  if (!standingApprovalEligible(expected) || !inspection.ok) throw new Error('This request is not eligible for an inspectable standing approval.');
  const policy = standingApprovalPolicy(config);
  if (policy.issue !== null) throw new Error(policy.issue);
  if (!Number.isSafeInteger(intent.standingTtlHours) || intent.standingTtlHours < 1 || intent.standingTtlHours > policy.maxHours) {
    throw new Error(`Standing lifetime must be an integer from 1 through ${policy.maxHours} hours.`);
  }
  return { approve: true, reason, grant_standing: true, standing_ttl_hours: intent.standingTtlHours };
}

/** Identity comparison never normalizes text or reorders arrays. */
export function sameCapabilityRequest(first: CapabilityApprovalView, second: CapabilityApprovalView): boolean {
  const fields = ['id', 'agent_id', 'kind', 'target', 'created_at', 'rationale', 'work_item_id',
    'status', 'decided_at', 'decided_by', 'decision_reason', 'can_retry_fulfilment'] as const;
  if (!fields.every(field => Object.is(first[field], second[field]))) return false;
  const pairs: Array<[unknown, unknown]> = [[first.payload, second.payload]];
  const seen = new Map<object, Set<object>>();
  while (pairs.length) {
    const [left, right] = pairs.pop()!;
    if (Object.is(left, right)) continue;
    if (left === null || right === null || typeof left !== 'object' || typeof right !== 'object'
      || Array.isArray(left) !== Array.isArray(right)) return false;
    if (seen.get(left)?.has(right)) continue;
    const rightSeen = seen.get(left) ?? new Set<object>();
    rightSeen.add(right);
    seen.set(left, rightSeen);
    const keys = Object.keys(left);
    if (keys.length !== Object.keys(right).length
      || (Array.isArray(left) && left.length !== (right as unknown[]).length)) return false;
    for (const key of keys) {
      const a = Object.getOwnPropertyDescriptor(left, key);
      const b = Object.getOwnPropertyDescriptor(right, key);
      if (!a || !b || !('value' in a) || !('value' in b)) return false;
      pairs.push([a.value, b.value]);
    }
  }
  return true;
}

export function capabilityFeedbackText(feedback: CapabilityDecisionFeedback): string {
  const { outcome } = feedback;
  const decision = outcome.request.status === 'denied' ? 'Denial recorded.'
    : outcome.fulfilled ? 'Approval recorded; fulfilment confirmed.'
      : outcome.request.can_retry_fulfilment ? 'Approval recorded; awaiting fulfilment.'
        : 'Approval recorded; the original action was not replayed.';
  if (feedback.standingRequested && !outcome.standingRule) {
    return 'Approval recorded; standing authority was not confirmed. Future runs may ask again.';
  }
  if (outcome.standingRuleIssue) return `${decision} Standing authority was not confirmed; the returned receipt was invalid.`;
  if (!outcome.standingRule) return decision;
  const rule = outcome.standingRule;
  return `${decision} Standing authority confirmed for agent ${approvalDisplayText(rule.agent_id)}, `
    + `tool ${approvalDisplayText(rule.tool_id)}, action ${approvalDisplayText(rule.action)}, `
    + `scope ${rule.scope_key === '' ? 'exact empty scope' : approvalDisplayText(JSON.stringify(rule.scope_key))}; `
    + `issued ${new Date(rule.issued_at * 1000).toISOString()}, expires ${new Date(rule.expires_at * 1000).toISOString()}.`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function validText(value: unknown, max = Infinity): value is string {
  return typeof value === 'string' && [...value].length <= max && !/[\uD800-\uDFFF]/u.test(value);
}

function hasPossibleActionPayloadSize(value: unknown): boolean {
  // Python owns exact canonical admission. Numeric zero gives only a necessary
  // lower bound on raw JSON, before display escaping, without changing values.
  // Valid JSON numbers can decode to either infinity; NaN cannot. Display
  // finiteness remains the formatter's concern, not repair eligibility's.
  const lowerBound = JSON.stringify(value, (key, item: unknown) => {
    if (!validText(key) || (typeof item === 'string' && !validText(item))
      || (typeof item === 'number' && Number.isNaN(item))
      || ['undefined', 'function', 'symbol', 'bigint'].includes(typeof item)) {
      throw new Error('Payload must contain valid JSON data only.');
    }
    return typeof item === 'number' ? 0 : item;
  });
  return typeof lowerBound === 'string' && [...lowerBound].length <= 4000;
}

function canFulfil(kind: unknown, payload: unknown): boolean {
  if (FULFILMENT_KINDS.has(String(kind))) return true;
  if (kind !== 'action' || !isRecord(payload)) return false;
  const keys = ['tool_id', 'action', 'params', 'scope_key', 'session_id', 'thread_id'];
  if (Object.keys(payload).length !== keys.length || !keys.every(key => key in payload)
    || payload.tool_id !== 'repair' || payload.action !== 'dispatch'
    || payload.session_id !== null || !isRecord(payload.params)
    || Object.keys(payload.params).length > 20
    || !validText(payload.scope_key, 128) || !payload.scope_key
    || !validText(payload.thread_id, 64)
    || !validText(payload.params.fault_id, 128) || !payload.params.fault_id
    || typeof payload.params.signature !== 'string' || !/^[0-9a-f]{64}$/.test(payload.params.signature)) {
    return false;
  }
  try {
    return hasPossibleActionPayloadSize(payload);
  } catch {
    return false;
  }
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
    && value.can_retry_fulfilment === (value.status === 'approved' && canFulfil(value.kind, value.payload));
}

export function isActionableCapabilityPayload(value: unknown): value is ApprovalPayload {
  if (!isRecord(value) || value.view !== 'actionable' || !Array.isArray(value.requests)) return false;
  return value.requests.every(row => isCapabilityRequestView(row)
    && (row.status === 'pending' || row.can_retry_fulfilment))
    && new Set(value.requests.map(row => row.id)).size === value.requests.length;
}

export function parseCapabilityDecision(
  value: unknown, expected: CapabilityApprovalView, approve: boolean,
  requestedStandingHours?: number,
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
    || (request.can_retry_fulfilment && !canFulfil(expected.kind, expected.payload))
    || (value.fulfilled && (!canFulfil(request.kind, request.payload) || !canFulfil(expected.kind, expected.payload)))) {
    throw new Error('Inconsistent capability decision response; request state was not confirmed.');
  }
  if (!sameCapabilityRequest(request, {
    ...expected, status: request.status, decided_at: request.decided_at,
    decided_by: request.decided_by, decision_reason: request.decision_reason,
    can_retry_fulfilment: request.can_retry_fulfilment,
  })) throw new Error('Inconsistent capability decision response; request identity or payload changed.');
  const outcome: CapabilityDecisionOutcome = { request, fulfilled: value.fulfilled };
  if (value.standing_rule == null) return outcome;
  const rule = value.standing_rule;
  const inspection = inspectActionPayload(expected.payload);
  const timestamp = (time: unknown): time is number => typeof time === 'number' && Number.isFinite(time)
    && Number.isFinite(new Date(time * 1000).getTime());
  if (!approve || !standingApprovalEligible(expected) || !inspection.ok || !isRecord(rule)
    || typeof rule.id !== 'string' || !UUID.test(rule.id) || rule.agent_id !== expected.agent_id
    || rule.tool_id !== inspection.payload.tool_id || rule.action !== inspection.payload.action
    || rule.scope_key !== inspection.payload.scope_key
    || !timestamp(rule.issued_at) || !timestamp(rule.expires_at) || rule.expires_at <= rule.issued_at
    || (requestedStandingHours !== undefined && (!Number.isSafeInteger(requestedStandingHours)
      || requestedStandingHours < 1 || rule.expires_at - rule.issued_at > requestedStandingHours * 3600))) {
    return { ...outcome, standingRuleIssue: 'invalid' };
  }
  return { ...outcome, standingRule: rule as unknown as StandingRuleReceipt };
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
