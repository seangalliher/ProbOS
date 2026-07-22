/**
 * AD-1083: fetch wrappers for the room Todo checklist (the AD-1080 steps +
 * the AD-1081/1082 senior-validation loop). Endpoints (mounted at /api):
 *   GET   /work-items/{id}/steps          -> { steps, gate_completion }
 *   PATCH /work-items/{id}/steps/{index}  -> transition one step
 * Honest-degrade: non-ok responses throw so the caller's try/catch shows an
 * empty section instead of crashing the rail.
 */
export interface TodoStep {
  label: string;
  status: 'pending' | 'in_progress' | 'submitted' | 'done' | 'rejected';
  assigned_to?: string | null;
  submitted_by?: string | null;
  confirmed_by?: string | null;
  note?: string | null;
}

export async function fetchTaskSteps(taskId: string): Promise<TodoStep[]> {
  const res = await fetch(`/api/work-items/${encodeURIComponent(taskId)}/steps`);
  if (!res.ok) throw new Error(`fetchTaskSteps: ${res.status}`);
  const body = await res.json();
  return Array.isArray(body.steps) ? body.steps : [];
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

export interface StartWorkRequest {
  goal: string;
  success_criteria: string[];
  expected_deliverable: string;
  retry_blocked: boolean;
}

export interface StartWorkResult {
  disposition: 'created' | 'resumed' | 'blocked';
  parent_id: string;
  thread_id: string;
  state: string;
  scheduled: boolean;
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
  const result = await response.json();
  if (
    typeof result?.parent_id !== 'string'
    || !result.parent_id
    || typeof result.thread_id !== 'string'
    || !result.thread_id
  ) {
    throw new Error('Start Work returned an invalid result');
  }
  return result as StartWorkResult;
}
