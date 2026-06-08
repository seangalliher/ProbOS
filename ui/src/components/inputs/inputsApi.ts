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

/**
 * AD-926a: attach one or more context-input files to a work item (task).
 *
 * Posts a single multipart request (all files under the `files` field) to
 * POST /api/work-items/{work_item_id}/inputs. The server validates + stores
 * each file once (content-addressable, sha256), appends refs to the work
 * item's input_attachments, and returns the updated task-level input list.
 * Honest-degrade: a non-ok response throws so the caller can show a toast.
 */
export async function attachTaskInputs(
  workItemId: string,
  files: File[],
): Promise<TaskInput[]> {
  const fd = new FormData();
  for (const f of files) {
    fd.append('files', f, f.name);
  }
  const res = await fetch(
    `/api/work-items/${encodeURIComponent(workItemId)}/inputs`,
    { method: 'POST', body: fd },
  );
  if (!res.ok) {
    throw new Error(`attachTaskInputs: ${res.status}`);
  }
  const body = await res.json();
  return Array.isArray(body.inputs) ? body.inputs : [];
}
