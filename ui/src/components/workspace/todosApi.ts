/**
 * AD-1083: fetch wrappers for the room Todo checklist (the AD-1080 steps +
 * the AD-1081/1082 senior-validation loop). Endpoints (mounted at /api):
 *   GET   /work-items/{id}/steps          -> { steps, gate_completion }
 *   PATCH /work-items/{id}/steps/{index}  -> transition one step
 * Honest-degrade: non-ok responses throw so the caller's try/catch shows an
 * empty section instead of crashing the rail.
 */
import type { StartWorkRequest, StartWorkResult } from '../../store/types';
import { isCrewSessionDetailProjection } from '../sidebar/threadApi';

export type { StartWorkRequest, StartWorkResult } from '../../store/types';

export interface TodoStep {
  label: string;
  status: 'pending' | 'in_progress' | 'submitted' | 'done' | 'rejected';
  assigned_to?: string | null;
  submitted_by?: string | null;
  confirmed_by?: string | null;
  note?: string | null;
}

const TODO_STATUSES = new Set([
  'pending', 'in_progress', 'submitted', 'done', 'rejected',
]);
const MAX_TODO_ROWS = 1000;
const MAX_TODO_RESPONSE_BYTES = 1024 * 1024;

function isTodoStep(value: unknown): value is TodoStep {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  const allowed = new Set([
    'label', 'status', 'assigned_to', 'submitted_by', 'confirmed_by', 'note',
  ]);
  if (Object.keys(row).some(key => !allowed.has(key))) return false;
  if (
    typeof row.label !== 'string'
    || row.label.length === 0
    || row.label.length > 4096
    || typeof row.status !== 'string'
    || !TODO_STATUSES.has(row.status)
  ) return false;
  return ['assigned_to', 'submitted_by', 'confirmed_by', 'note'].every((key) => (
    row[key] === undefined
    || row[key] === null
    || (typeof row[key] === 'string' && (row[key] as string).length <= 4096)
  ));
}

export async function fetchTaskSteps(taskId: string): Promise<TodoStep[]> {
  const res = await fetch(`/api/work-items/${encodeURIComponent(taskId)}/steps?limit=1001`);
  if (!res.ok) throw new Error(`fetchTaskSteps: ${res.status}`);
  const text = await res.text();
  if (new TextEncoder().encode(text).byteLength > MAX_TODO_RESPONSE_BYTES) {
    throw new Error('fetchTaskSteps: response_too_large');
  }
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    throw new Error('fetchTaskSteps: malformed_response');
  }
  if (
    typeof body !== 'object'
    || body === null
    || Array.isArray(body)
    || Object.keys(body).length !== 2
    || !Object.prototype.hasOwnProperty.call(body, 'steps')
    || !Object.prototype.hasOwnProperty.call(body, 'gate_completion')
  ) throw new Error('fetchTaskSteps: malformed_response');
  const record = body as Record<string, unknown>;
  if (!Array.isArray(record.steps) || typeof record.gate_completion !== 'boolean') {
    throw new Error('fetchTaskSteps: malformed_response');
  }
  if (record.steps.length > MAX_TODO_ROWS) {
    throw new Error('fetchTaskSteps: count_exceeded');
  }
  if (!record.steps.every(isTodoStep)) {
    throw new Error('fetchTaskSteps: malformed_row');
  }
  return record.steps;
}

export async function updateTaskStep(
  taskId: string,
  index: number,
  body: { status: string; actor?: string; note?: string },
): Promise<void> {
  const res = await fetch(
    `/api/work-items/${encodeURIComponent(taskId)}/steps/${index}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) throw new Error(`updateTaskStep: ${res.status}`);
}

export async function startRoomWork(
  threadId: string,
  body: StartWorkRequest,
): Promise<StartWorkResult> {
  const response = await fetch(
    `/api/threads/${encodeURIComponent(threadId)}/start-work`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  );
  if (!response.ok) {
    let detail = `Start Work failed (${response.status})`;
    try {
      const payload = await response.json();
      if (typeof payload?.detail === 'string' && payload.detail.trim()) {
        detail = payload.detail.slice(0, 256);
      }
    } catch {
      // Keep the bounded status fallback.
    }
    throw new Error(detail);
  }
  const result: unknown = await response.json();
  if (
    typeof result !== 'object'
    || result === null
    || typeof (result as Record<string, unknown>).parent_id !== 'string'
    || !(result as Record<string, unknown>).parent_id
    || typeof (result as Record<string, unknown>).thread_id !== 'string'
    || !(result as Record<string, unknown>).thread_id
    || !isCrewSessionDetailProjection((result as Record<string, unknown>).session)
  ) {
    throw new Error('Start Work returned an invalid result');
  }
  const typed = result as unknown as StartWorkResult;
  if (
    typed.session.task_id !== typed.parent_id
    || typed.session.thread_id !== typed.thread_id
    || typed.session.state !== typed.state
  ) {
    throw new Error('Start Work returned an invalid result');
  }
  return typed;
}
