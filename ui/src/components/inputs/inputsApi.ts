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
  available?: boolean;
}

export async function fetchThreadInputs(threadId: string): Promise<TaskInput[]> {
  const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}/inputs`);
  if (!res.ok) {
    throw new Error(`fetchThreadInputs: ${res.status}`);
  }
  const body = await res.json();
  if (
    !body || typeof body !== 'object' || Array.isArray(body)
    || body.thread_id !== threadId
    || !(body.task_id === null || typeof body.task_id === 'string')
    || !Array.isArray(body.inputs)
    || !body.inputs.every((input: unknown) => {
      if (!input || typeof input !== 'object' || Array.isArray(input)) return false;
      const row = input as Record<string, unknown>;
      return typeof row.content_hash === 'string' && /^[0-9a-f]{64}$/.test(row.content_hash)
        && typeof row.mime === 'string' && row.mime.trim().length > 0
        && (row.filename === null || typeof row.filename === 'string')
        && (row.size === null || (typeof row.size === 'number' && Number.isSafeInteger(row.size) && row.size >= 0))
        && (row.source === 'task' || row.source === 'message')
        && (row.available === undefined || typeof row.available === 'boolean');
    })
  ) {
    throw new Error('fetchThreadInputs: invalid room inputs response');
  }
  return body.inputs;
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
