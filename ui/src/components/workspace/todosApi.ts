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

/**
 * AD-1084: bind a work item to a workspace room that has none. Captain-created
 * rooms (1:1 promoted to group) never get a task_id (only orchestrator
 * fan-outs do, AD-925), so the Todo loop has nowhere to land. Create a task
 * and link it to the thread, returning the new id. Honest-degrade: throws so
 * the caller leaves the room task-less rather than crashing.
 */
export async function ensureRoomTask(threadId: string, title: string): Promise<string> {
  const created = await fetch('/api/work-items', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, work_type: 'task' }),
  });
  if (!created.ok) throw new Error(`ensureRoomTask:create: ${created.status}`);
  const id = (await created.json())?.work_item?.id;
  if (!id) throw new Error('ensureRoomTask: no id');
  const linked = await fetch(`/api/threads/${encodeURIComponent(threadId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: id }),
  });
  if (!linked.ok) throw new Error(`ensureRoomTask:link: ${linked.status}`);
  return id;
}
