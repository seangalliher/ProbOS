/**
 * AD-926: fetch wrapper for the task-room Inputs pane.
 *
 * Endpoint:  GET /api/threads/{thread_id}/inputs
 *   -> { thread_id, task_id, inputs: TaskInput[] }
 * Bytes are fetched via the existing GET /api/chat/attachments/{content_hash}.
 * Honest-degrade: non-ok responses throw so the caller's try/catch shows a
 * toast without crashing the pane.
 */
export interface TaskInput {
  content_hash: string;
  mime: string;
  filename: string | null;
  size: number | null;
  source: 'task' | 'message';
}

export async function fetchThreadInputs(threadId: string): Promise<TaskInput[]> {
  const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}/inputs`);
  if (!res.ok) {
    throw new Error(`fetchThreadInputs: ${res.status}`);
  }
  const body = await res.json();
  return Array.isArray(body.inputs) ? body.inputs : [];
}

export function attachmentUrl(contentHash: string): string {
  return `/api/chat/attachments/${encodeURIComponent(contentHash)}`;
}
