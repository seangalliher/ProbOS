import type { TodoStep } from './todosApi';

const MAX_RESPONSE_BYTES = 1024 * 1024;
const DIGEST = /^[a-f0-9]{64}$/;
const ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const MODES = new Set([
  'awaiting_adoption', 'active', 'interrupted', 'cancelled',
  'waiting_manual_gate', 'completed',
]);
const FINALIZATION = new Set(['none', 'pending', 'completed', 'conflict']);
const PERMIT_STATES = new Set([
  'unstarted', 'started', 'submitted', 'terminal', 'revoked', 'interrupted',
]);
const TODO_STATUSES = new Set(['pending', 'in_progress', 'submitted', 'done', 'rejected']);

type RecordValue = Record<string, unknown>;

export interface OwnedStepsViewReference {
  version: 1;
  parent_id: string;
  actor_id: string;
  thread_id: string;
  turn_id: string;
  view_id: string;
  content_hash: string;
}

export interface RepairReference extends OwnedStepsViewReference {
  observation_id: string;
}

export interface ProposalReference extends OwnedStepsViewReference {
  proposal_id: string;
  manifest_digest: string;
}

export interface ProposalLocator {
  version: 1;
  parent_id: string;
  proposal_id: string;
  manifest_digest: string;
}

export interface OwnedStepToken {
  parent_id: string;
  incarnation: string;
  layout_revision: number;
  plan_revision: number;
  plan_digest: string;
  step_id: string;
  row_revision: number;
  row_digest: string;
  source_digest: string | null;
  assignment_epoch: number;
  actor_id: string;
  thread_id: string;
  view_id: string;
  turn_id: string;
}

export interface OwnedStepRow {
  step_id: string;
  ordinal: number;
  kind: 'manual' | 'child';
  child_id: string | null;
  revision: number;
  digest: string;
  todo: TodoStep;
  actions: string[];
  evidence: {
    permit_state: 'unstarted' | 'started' | 'submitted' | 'terminal' | 'revoked' | 'interrupted';
    assignment_epoch: number;
    booking_id: string | null;
    has_submission: boolean;
    review_accepted: boolean | null;
  };
  token: OwnedStepToken | null;
  detail_url: string | null;
}

export interface ManagedOwnedStepsView {
  version: 1;
  mode: 'awaiting_adoption' | 'active' | 'interrupted' | 'cancelled' | 'waiting_manual_gate' | 'completed';
  parent_id: string;
  requested_item_id: string;
  actor_id: string;
  thread_id: string;
  turn_id: string;
  view_id: string;
  layout_revision: number;
  plan_revision: number;
  plan_digest: string;
  steps_digest: string;
  source_digest: string;
  plan_token: RecordValue | null;
  rows: OwnedStepRow[];
  previous_cursor: string | null;
  next_cursor: string | null;
  omitted_step_ids: string[];
  recovery: string[];
  finalization: 'none' | 'pending' | 'completed' | 'conflict';
  reference: OwnedStepsViewReference;
}

export interface UnmanagedOwnedStepsView {
  version: 1;
  mode: 'unmanaged';
  parent_id: string;
  requested_item_id: string;
  reference: null;
  rows: Array<{ ordinal: number; todo: TodoStep }>;
  previous_cursor: string | null;
  next_cursor: string | null;
  recovery: string[];
  finalization: 'none';
}

export type OwnedStepsView = ManagedOwnedStepsView | UnmanagedOwnedStepsView;

export interface OwnedStepsRepair {
  version: 1;
  parent_id: string;
  reference: RepairReference;
  steps_digest: string;
  control_digest: string | null;
  raw_steps: string | null;
  raw_control: string | null;
  omissions: string[];
  actions: string[];
}

export interface ProposalPage {
  version: 1;
  proposal: ProposalLocator;
  reference: ProposalReference | null;
  kind: 'adopt_existing' | 'replace_manual_prefix' | 'replan_unstarted';
  state: 'preparing' | 'ready' | 'failed' | 'committed';
  before_digest: string | null;
  after_digest: string | null;
  gate_completion: boolean | null;
  manual_count: number;
  child_count: number;
  retired_count: number;
  rows: RecordValue[];
  previous_cursor: string | null;
  next_cursor: string | null;
  coverage: RecordValue;
  omissions: string[];
  actions: string[];
  error_code: string | null;
  acknowledgement: RecordValue | null;
}

export type OwnedRowCommand =
  | { operation_id: string; step_id: string; kind: 'manual_submit' | 'manual_confirm' | 'cancel_execution' | 'abandon' }
  | { operation_id: string; step_id: string; kind: 'manual_reject' | 'edit_note'; note: string }
  | { operation_id: string; step_id: string; kind: 'reassign_unstarted'; assignee_id: string }
  | { operation_id: string; step_id: string; kind: 'pause_accounting' | 'resume_accounting'; booking_id: string; resource_id: string };

export class OwnedStepsApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly parentId: string;
  readonly viewId: string | null;
  readonly actions: string[];
  readonly feedback: string;

  constructor(
    status: number,
    code: string,
    message: string,
    parentId = '',
    viewId: string | null = null,
    actions: string[] = [],
    feedback = '',
  ) {
    super(message);
    this.name = 'OwnedStepsApiError';
    this.status = status;
    this.code = code;
    this.parentId = parentId;
    this.viewId = viewId;
    this.actions = actions;
    this.feedback = feedback || message;
  }
}

function isRecord(value: unknown): value is RecordValue {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function exact(value: unknown, keys: readonly string[]): value is RecordValue {
  return isRecord(value)
    && Object.keys(value).length === keys.length
    && keys.every(key => Object.prototype.hasOwnProperty.call(value, key));
}

function isId(value: unknown, blank = false): value is string {
  return typeof value === 'string' && ((blank && value === '') || ID.test(value));
}

function isDigest(value: unknown): value is string {
  return typeof value === 'string' && DIGEST.test(value);
}

function isRevision(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 1;
}

function isCount(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(item => typeof item === 'string');
}

function decodeTodo(value: unknown): TodoStep {
  if (!isRecord(value)) throw malformed('owned_steps_malformed_todo');
  const allowed = new Set([
    'label', 'status', 'assigned_to', 'submitted_by', 'confirmed_by', 'note',
  ]);
  if (
    Object.keys(value).some(key => !allowed.has(key))
    || typeof value.label !== 'string'
    || value.label.length === 0
    || typeof value.status !== 'string'
    || !TODO_STATUSES.has(value.status)
    || !['assigned_to', 'submitted_by', 'confirmed_by', 'note']
      .every(key => value[key] === undefined || nullableString(value[key]))
  ) throw malformed('owned_steps_malformed_todo');
  return value as unknown as TodoStep;
}

function decodeViewReference(value: unknown): OwnedStepsViewReference {
  const keys = ['version', 'parent_id', 'actor_id', 'thread_id', 'turn_id', 'view_id', 'content_hash'];
  if (
    !exact(value, keys) || value.version !== 1 || !isId(value.parent_id)
    || !isId(value.actor_id) || !isId(value.thread_id, true) || !isId(value.turn_id)
    || !isId(value.view_id) || !isDigest(value.content_hash)
  ) throw malformed('owned_steps_malformed_reference');
  return value as unknown as OwnedStepsViewReference;
}

function decodeRepairReference(value: unknown): RepairReference {
  const keys = [
    'version', 'parent_id', 'actor_id', 'thread_id', 'turn_id', 'view_id',
    'content_hash', 'observation_id',
  ];
  if (!exact(value, keys) || !isId(value.observation_id)) {
    throw malformed('owned_steps_malformed_repair_reference');
  }
  decodeViewReference(Object.fromEntries(
    Object.entries(value).filter(([key]) => key !== 'observation_id'),
  ));
  return value as unknown as RepairReference;
}

function decodeProposalReference(value: unknown): ProposalReference {
  const keys = [
    'version', 'parent_id', 'actor_id', 'thread_id', 'turn_id', 'view_id',
    'content_hash', 'proposal_id', 'manifest_digest',
  ];
  if (!exact(value, keys) || !isId(value.proposal_id) || !isDigest(value.manifest_digest)) {
    throw malformed('owned_steps_malformed_proposal_reference');
  }
  decodeViewReference(Object.fromEntries(
    Object.entries(value).filter(([key]) => !['proposal_id', 'manifest_digest'].includes(key)),
  ));
  return value as unknown as ProposalReference;
}

function decodeProposalLocator(value: unknown): ProposalLocator {
  const keys = ['version', 'parent_id', 'proposal_id', 'manifest_digest'];
  if (
    !exact(value, keys) || value.version !== 1 || !isId(value.parent_id)
    || !isId(value.proposal_id) || !isDigest(value.manifest_digest)
  ) throw malformed('owned_steps_malformed_proposal_locator');
  return value as unknown as ProposalLocator;
}

function decodeToken(value: unknown): OwnedStepToken | null {
  if (value === null) return null;
  const keys = [
    'parent_id', 'incarnation', 'layout_revision', 'plan_revision', 'plan_digest',
    'step_id', 'row_revision', 'row_digest', 'source_digest', 'assignment_epoch',
    'actor_id', 'thread_id', 'view_id', 'turn_id',
  ];
  if (
    !exact(value, keys) || !isId(value.parent_id) || !isId(value.incarnation)
    || !isRevision(value.layout_revision) || !isRevision(value.plan_revision)
    || !isDigest(value.plan_digest) || !isId(value.step_id)
    || !isRevision(value.row_revision) || !isDigest(value.row_digest)
    || !(value.source_digest === null || isDigest(value.source_digest))
    || !isRevision(value.assignment_epoch) || !isId(value.actor_id)
    || !isId(value.thread_id, true) || !isId(value.view_id) || !isId(value.turn_id)
  ) throw malformed('owned_steps_malformed_token');
  return value as unknown as OwnedStepToken;
}

function decodeEvidence(value: unknown): OwnedStepRow['evidence'] {
  const keys = ['permit_state', 'assignment_epoch', 'booking_id', 'has_submission', 'review_accepted'];
  if (
    !exact(value, keys) || typeof value.permit_state !== 'string'
    || !PERMIT_STATES.has(value.permit_state) || !isRevision(value.assignment_epoch)
    || !(value.booking_id === null || isId(value.booking_id))
    || typeof value.has_submission !== 'boolean'
    || !(value.review_accepted === null || typeof value.review_accepted === 'boolean')
  ) throw malformed('owned_steps_malformed_evidence');
  return value as OwnedStepRow['evidence'];
}

function decodeRow(value: unknown): OwnedStepRow {
  const keys = [
    'step_id', 'ordinal', 'kind', 'child_id', 'revision', 'digest', 'todo',
    'actions', 'evidence', 'token', 'detail_url',
  ];
  if (
    !exact(value, keys) || !isId(value.step_id) || !isCount(value.ordinal)
    || (value.kind !== 'manual' && value.kind !== 'child')
    || !(value.child_id === null || isId(value.child_id))
    || !isRevision(value.revision) || !isDigest(value.digest)
    || !stringArray(value.actions)
    || !(value.detail_url === null || typeof value.detail_url === 'string')
  ) throw malformed('owned_steps_malformed_row');
  return {
    ...(value as unknown as OwnedStepRow),
    todo: decodeTodo(value.todo),
    evidence: decodeEvidence(value.evidence),
    token: decodeToken(value.token),
  };
}

function decodeManaged(value: RecordValue): ManagedOwnedStepsView {
  const keys = [
    'version', 'parent_id', 'requested_item_id', 'actor_id', 'thread_id', 'turn_id',
    'view_id', 'mode', 'layout_revision', 'plan_revision', 'plan_digest',
    'steps_digest', 'source_digest', 'plan_token', 'rows', 'previous_cursor',
    'next_cursor', 'omitted_step_ids', 'recovery', 'finalization', 'reference',
  ];
  if (
    !exact(value, keys) || value.version !== 1 || !isId(value.parent_id)
    || !isId(value.requested_item_id) || !isId(value.actor_id)
    || !isId(value.thread_id, true) || !isId(value.turn_id) || !isId(value.view_id)
    || typeof value.mode !== 'string' || !MODES.has(value.mode)
    || !isRevision(value.layout_revision) || !isRevision(value.plan_revision)
    || !isDigest(value.plan_digest) || !isDigest(value.steps_digest)
    || !isDigest(value.source_digest)
    || !(value.plan_token === null || isRecord(value.plan_token))
    || !Array.isArray(value.rows) || value.rows.length > 20
    || !nullableString(value.previous_cursor) || !nullableString(value.next_cursor)
    || !stringArray(value.omitted_step_ids) || !stringArray(value.recovery)
    || typeof value.finalization !== 'string' || !FINALIZATION.has(value.finalization)
  ) throw malformed('owned_steps_malformed_view');
  const reference = decodeViewReference(value.reference);
  if (
    reference.parent_id !== value.parent_id || reference.actor_id !== value.actor_id
    || reference.thread_id !== value.thread_id || reference.turn_id !== value.turn_id
    || reference.view_id !== value.view_id
  ) throw malformed('owned_steps_reference_conflict');
  return {
    ...(value as unknown as ManagedOwnedStepsView),
    rows: value.rows.map(decodeRow),
    reference,
  };
}

function decodeUnmanaged(value: RecordValue): UnmanagedOwnedStepsView {
  const keys = [
    'version', 'mode', 'parent_id', 'requested_item_id', 'reference', 'rows',
    'previous_cursor', 'next_cursor', 'recovery', 'finalization',
  ];
  if (
    !exact(value, keys) || value.version !== 1 || value.mode !== 'unmanaged'
    || !isId(value.parent_id) || !isId(value.requested_item_id) || value.reference !== null
    || !Array.isArray(value.rows) || value.rows.length > 20
    || !nullableString(value.previous_cursor) || !nullableString(value.next_cursor)
    || !stringArray(value.recovery) || value.finalization !== 'none'
  ) throw malformed('owned_steps_malformed_unmanaged_view');
  const rows = value.rows.map((row) => {
    if (!exact(row, ['ordinal', 'todo']) || !isCount(row.ordinal)) {
      throw malformed('owned_steps_malformed_unmanaged_row');
    }
    return { ordinal: row.ordinal as number, todo: decodeTodo(row.todo) };
  });
  return { ...(value as unknown as UnmanagedOwnedStepsView), rows };
}

function malformed(code: string): OwnedStepsApiError {
  return new OwnedStepsApiError(0, code, 'Owned steps returned an invalid response.');
}

function decodeError(status: number, value: unknown): OwnedStepsApiError {
  const detail = isRecord(value) && isRecord(value.detail) ? value.detail : null;
  if (
    detail && typeof detail.code === 'string' && typeof detail.message === 'string'
    && typeof detail.parent_id === 'string'
    && (detail.view_id === null || typeof detail.view_id === 'string')
    && stringArray(detail.actions)
    && typeof detail.feedback === 'string'
  ) {
    return new OwnedStepsApiError(
      status, detail.code, detail.message, detail.parent_id,
      detail.view_id, detail.actions, detail.feedback,
    );
  }
  const message = isRecord(value) && typeof value.detail === 'string'
    ? value.detail
    : `Owned steps request failed (${status}).`;
  return new OwnedStepsApiError(status, 'owned_steps_http_error', message);
}

async function requestJson(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(path, init);
  const text = await response.text();
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw malformed('owned_steps_response_too_large');
  }
  let value: unknown;
  try {
    value = text ? JSON.parse(text) : null;
  } catch {
    throw malformed('owned_steps_malformed_response');
  }
  if (!response.ok) throw decodeError(response.status, value);
  return value;
}

function jsonInit(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

export async function fetchOwnedSteps(
  taskId: string,
  options: { cursor?: string; detail?: string; presentationBudget?: number } = {},
): Promise<OwnedStepsView> {
  const params = new URLSearchParams();
  if (options.cursor !== undefined) params.set('cursor', options.cursor);
  if (options.detail !== undefined) params.set('detail', options.detail);
  if (options.presentationBudget !== undefined) {
    params.set('presentation_budget', String(options.presentationBudget));
  }
  const suffix = params.size ? `?${params.toString()}` : '';
  const value = await requestJson(
    `/api/work-items/${encodeURIComponent(taskId)}/owned-steps${suffix}`,
  );
  if (!isRecord(value) || typeof value.mode !== 'string') {
    throw malformed('owned_steps_malformed_view');
  }
  return value.mode === 'unmanaged' ? decodeUnmanaged(value) : decodeManaged(value);
}

export async function fetchOwnedStepDetail(
  taskId: string,
  stepId: string,
): Promise<RecordValue> {
  const value = await requestJson(
    `/api/work-items/${encodeURIComponent(taskId)}/owned-steps?detail=${encodeURIComponent(stepId)}`,
  );
  const keys = [
    'version', 'parent_id', 'step_id', 'ordinal', 'kind', 'child_id', 'revision',
    'digest', 'todo', 'evidence', 'read_only',
  ];
  if (
    !exact(value, keys) || value.version !== 1 || value.read_only !== true
    || !isId(value.parent_id) || !isId(value.step_id) || !isCount(value.ordinal)
    || (value.kind !== 'manual' && value.kind !== 'child')
    || !(value.child_id === null || isId(value.child_id))
    || !isRevision(value.revision) || !isDigest(value.digest)
  ) throw malformed('owned_steps_malformed_detail');
  decodeTodo(value.todo);
  decodeEvidence(value.evidence);
  return value;
}

export async function fetchOwnedRepair(taskId: string): Promise<OwnedStepsRepair> {
  const value = await requestJson(
    `/api/work-items/${encodeURIComponent(taskId)}/owned-steps/repair`,
  );
  const keys = [
    'version', 'parent_id', 'reference', 'steps_digest', 'control_digest',
    'raw_steps', 'raw_control', 'omissions', 'actions',
  ];
  if (
    !exact(value, keys) || value.version !== 1 || !isId(value.parent_id)
    || !isDigest(value.steps_digest)
    || !(value.control_digest === null || isDigest(value.control_digest))
    || !nullableString(value.raw_steps) || !nullableString(value.raw_control)
    || !stringArray(value.omissions) || !stringArray(value.actions)
  ) throw malformed('owned_steps_malformed_repair');
  return {
    ...(value as unknown as OwnedStepsRepair),
    reference: decodeRepairReference(value.reference),
  };
}

export type ProposalRequest =
  | { version: 1; kind: 'adopt_existing'; preparation_id: string; reference: OwnedStepsViewReference }
  | { version: 1; kind: 'replace_manual_prefix'; preparation_id: string; reference: OwnedStepsViewReference | RepairReference; prefix_json: string }
  | { version: 1; kind: 'replan_unstarted'; preparation_id: string; reference: OwnedStepsViewReference | RepairReference }
  | { version: 1; kind: 'inspect_proposal'; proposal: ProposalLocator; cursor?: string };

function decodeProposalPage(value: unknown): ProposalPage {
  const keys = [
    'version', 'proposal', 'reference', 'kind', 'state', 'before_digest',
    'after_digest', 'gate_completion', 'manual_count', 'child_count',
    'retired_count', 'rows', 'previous_cursor', 'next_cursor', 'coverage',
    'omissions', 'actions', 'error_code', 'acknowledgement',
  ];
  if (
    !exact(value, keys) || value.version !== 1
    || !['adopt_existing', 'replace_manual_prefix', 'replan_unstarted'].includes(String(value.kind))
    || !['preparing', 'ready', 'failed', 'committed'].includes(String(value.state))
    || !(value.before_digest === null || isDigest(value.before_digest))
    || !(value.after_digest === null || isDigest(value.after_digest))
    || !(value.gate_completion === null || typeof value.gate_completion === 'boolean')
    || !isCount(value.manual_count) || !isCount(value.child_count) || !isCount(value.retired_count)
    || !Array.isArray(value.rows) || !value.rows.every(isRecord)
    || !nullableString(value.previous_cursor) || !nullableString(value.next_cursor)
    || !isRecord(value.coverage) || !stringArray(value.omissions) || !stringArray(value.actions)
    || !(value.error_code === null || typeof value.error_code === 'string')
    || !(value.acknowledgement === null || isRecord(value.acknowledgement))
  ) throw malformed('owned_steps_malformed_proposal');
  return {
    ...(value as unknown as ProposalPage),
    proposal: decodeProposalLocator(value.proposal),
    reference: value.reference === null ? null : decodeProposalReference(value.reference),
  };
}

export async function previewOwnedProposal(
  taskId: string,
  request: ProposalRequest,
): Promise<ProposalPage> {
  const value = await requestJson(
    `/api/work-items/${encodeURIComponent(taskId)}/owned-steps/preview`,
    jsonInit(request),
  );
  if (!exact(value, ['proposal'])) throw malformed('owned_steps_malformed_proposal_envelope');
  return decodeProposalPage(value.proposal);
}

export async function applyOwnedProposal(
  taskId: string,
  request: { version: 1; operation_id: string; reference: ProposalReference },
  kind: ProposalPage['kind'],
): Promise<'applied' | 'duplicate'> {
  const operation = kind === 'adopt_existing' ? 'adopt' : 'commands';
  const value = await requestJson(
    `/api/work-items/${encodeURIComponent(taskId)}/owned-steps/${operation}`,
    jsonInit(request),
  );
  if (
    !exact(value, ['disposition'])
    || (value.disposition !== 'applied' && value.disposition !== 'duplicate')
  ) throw malformed('owned_steps_malformed_application');
  return value.disposition;
}

export async function sendOwnedCommands(
  taskId: string,
  reference: OwnedStepsViewReference,
  commands: OwnedRowCommand[],
): Promise<Array<{ operation_id: string; disposition: string }>> {
  const value = await requestJson(
    `/api/work-items/${encodeURIComponent(taskId)}/owned-steps/commands`,
    jsonInit({ version: 1, reference, commands }),
  );
  if (
    !exact(value, ['results']) || !Array.isArray(value.results)
    || !value.results.every(result => (
      exact(result, ['operation_id', 'disposition'])
      && isId(result.operation_id) && typeof result.disposition === 'string'
    ))
  ) throw malformed('owned_steps_malformed_command_result');
  return value.results as Array<{ operation_id: string; disposition: string }>;
}

export async function finalizeOwnedSteps(
  taskId: string,
  reference: OwnedStepsViewReference,
): Promise<string> {
  const value = await requestJson(
    `/api/work-items/${encodeURIComponent(taskId)}/owned-steps/finalize`,
    jsonInit({ version: 1, reference }),
  );
  if (!exact(value, ['disposition']) || typeof value.disposition !== 'string') {
    throw malformed('owned_steps_malformed_finalization');
  }
  return value.disposition;
}

export function newOwnedOperationId(prefix: string): string {
  const random = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${random}`.slice(0, 128);
}
