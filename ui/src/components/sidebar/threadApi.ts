/*
 * AD-792 (Wave 195) — Thin fetch wrappers for the threads REST surface.
 *
 * Centralizes the response-shape contracts so the React component and
 * its tests both agree:
 *   - GET /api/threads                  -> {threads: ChatThreadView[]}
 *   - GET /api/threads/search?q=...     -> {query: string, results: ChatThreadView[]}
 *   - POST /api/threads                 -> ChatThreadView (thread.to_dict() DIRECT)
 *   - PATCH /api/threads/{id}           -> ChatThreadView
 *   - DELETE /api/threads/{id}          -> {deleted: true, thread_id: string}
 *
 * Verified against ``src/probos/routers/threads.py`` (Wave 193/194):
 *   line 82: return {"threads": [...]}    (list)
 *   line 94: return {"query": q, "results": [...]}    (search)
 *   line 117: return thread.to_dict()      (create — DIRECT, NOT wrapped)
 *   line 174: return thread.to_dict()      (patch)
 *   line 183: return {"deleted": True, "thread_id": ...}    (delete)
 *
 * All wrappers honest-degrade on network failure: they return ``null``
 * (or empty array) so the sidebar can keep rendering its current state
 * instead of throwing — Tier-2 log-and-degrade per the engineering
 * principles stack.
 */
import type { AD791aChatThreadView } from '../../store/useStore';

export interface ListThreadsOptions {
  includeArchived?: boolean;
  limit?: number;
}

export async function listThreads(opts: ListThreadsOptions = {}): Promise<AD791aChatThreadView[]> {
  const includeArchived = opts.includeArchived ?? false;
  const limit = opts.limit ?? 100;
  try {
    const res = await fetch(`/api/threads?include_archived=${includeArchived}&limit=${limit}`);
    if (!res.ok) return [];
    const data = (await res.json()) as { threads?: AD791aChatThreadView[] };
    return Array.isArray(data?.threads) ? data.threads : [];
  } catch {
    return [];
  }
}

export async function searchThreads(query: string): Promise<AD791aChatThreadView[]> {
  if (!query.trim()) return [];
  try {
    const res = await fetch(`/api/threads/search?q=${encodeURIComponent(query)}`);
    if (!res.ok) return [];
    const data = (await res.json()) as { query?: string; results?: AD791aChatThreadView[] };
    return Array.isArray(data?.results) ? data.results : [];
  } catch {
    return [];
  }
}

export interface CreateThreadBody {
  title: string;
  participants: string[];
  project_id?: string | null;
  task_id?: string | null;
  preprompt?: string | null;
  model?: string | null;
}

export async function createThread(body: CreateThreadBody): Promise<AD791aChatThreadView | null> {
  try {
    const res = await fetch('/api/threads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    // POST /api/threads returns thread.to_dict() DIRECTLY (verified
    // at routers/threads.py:117) — not wrapped under {thread: ...}.
    const data = (await res.json()) as AD791aChatThreadView;
    return data && typeof data.id === 'string' ? data : null;
  } catch {
    return null;
  }
}

export interface PatchThreadBody {
  title?: string;
  title_locked?: boolean;
  pinned?: boolean;
  archived?: boolean;
  // AD-793 (Wave 196): re-parenting threads between projects via the
  // existing PATCH endpoint (the server already supports project_id
  // per AD-791a).
  project_id?: string | null;
  // AD-920: meeting-mode flag — routes server-side through
  // store.set_meeting_active (a scoped metadata RMW).
  meeting_active?: boolean;
}

export async function patchThread(
  threadId: string,
  body: PatchThreadBody,
): Promise<AD791aChatThreadView | null> {
  try {
    const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as AD791aChatThreadView;
    return data && typeof data.id === 'string' ? data : null;
  } catch {
    return null;
  }
}

/**
 * AD-920: start/end meeting mode on a group thread.
 * PATCH /api/threads/{id}  body {meeting_active}  -> updated thread.to_dict()
 * (404 honest-degrades to null). The returned thread carries
 * metadata.meeting_active so the caller can setChatThread(updated).
 */
export async function setMeetingActive(
  threadId: string,
  active: boolean,
): Promise<AD791aChatThreadView | null> {
  return patchThread(threadId, { meeting_active: active });
}

export async function deleteThread(threadId: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}`, {
      method: 'DELETE',
    });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * AD-917: add a crew agent to a thread.
 * POST /api/threads/{id}/participants  body {agent_id}  -> updated thread.to_dict()
 * (404 if thread missing, 400 if agent_id empty — both honest-degrade to null.)
 */
export async function addParticipant(
  threadId: string,
  agentId: string,
): Promise<AD791aChatThreadView | null> {
  try {
    const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}/participants`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: agentId }),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as AD791aChatThreadView;
    return data && typeof data.id === 'string' ? data : null;
  } catch {
    return null;
  }
}

/**
 * AD-917: remove a participant.
 * DELETE /api/threads/{id}/participants/{agent_id}  -> updated thread.to_dict()
 */
export async function removeParticipant(
  threadId: string,
  agentId: string,
): Promise<AD791aChatThreadView | null> {
  try {
    const res = await fetch(
      `/api/threads/${encodeURIComponent(threadId)}/participants/${encodeURIComponent(agentId)}`,
      { method: 'DELETE' },
    );
    if (!res.ok) return null;
    const data = (await res.json()) as AD791aChatThreadView;
    return data && typeof data.id === 'string' ? data : null;
  } catch {
    return null;
  }
}

export interface AppendMessageBody {
  author_id: string;
  role: 'captain' | 'agent' | 'system';
  body: string;
  metadata?: Record<string, unknown>;
  attachment_ids?: string[];
}

/**
 * AD-923: append a message to a thread.
 * POST /api/threads/{id}/messages -> appended message dict (or null on failure).
 * Tier-2 honest-degrade: a network/!ok failure returns null so callers can
 * continue (e.g. still end the meeting even if the marker append failed).
 * A ``role:'system'`` append skips the AD-914 ``role=="captain"`` fan-out gate
 * (no agent dispatch) — exactly what an end-of-meeting transcript marker wants.
 */
export async function appendMessage(
  threadId: string,
  body: AppendMessageBody,
): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    return (await res.json()) as Record<string, unknown>;
  } catch {
    return null;
  }
}
