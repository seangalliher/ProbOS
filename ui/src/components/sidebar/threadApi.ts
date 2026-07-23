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
import type {
  CrewSessionDetailProjection,
  CrewSessionState,
  CrewSessionSummaryProjection,
  CrewTaskDetailOutcome,
  LegacyCrewChildView,
  LegacyCrewTaskTree,
  LegacyCrewVerdict,
  LegacyCrewWorkItemView,
  RoomSummary,
} from '../../store/types';

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

const CREW_SESSION_STATES: readonly CrewSessionState[] = [
  'discussing',
  'executing',
  'verifying',
  'blocked_needs_captain',
  'done',
  'failed',
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length
    && actual.every((key, index) => key === expected[index]);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || isFiniteNumber(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(item => typeof item === 'string');
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

function isSessionState(value: unknown): value is CrewSessionState {
  return typeof value === 'string'
    && CREW_SESSION_STATES.includes(value as CrewSessionState);
}

function isDetailProgress(value: unknown): boolean {
  if (!isRecord(value) || !hasExactKeys(value, [
    'total', 'done', 'failed', 'active', 'active_child',
  ])) return false;
  const activeChild = value.active_child;
  const validChild = activeChild === null || (
    isRecord(activeChild)
    && hasExactKeys(activeChild, ['id', 'title', 'status', 'owner_id'])
    && typeof activeChild.id === 'string'
    && typeof activeChild.title === 'string'
    && typeof activeChild.status === 'string'
    && (activeChild.owner_id === null || typeof activeChild.owner_id === 'string')
  );
  return ['total', 'done', 'failed', 'active'].every(
    key => Number.isInteger(value[key]) && (value[key] as number) >= 0,
  ) && validChild;
}

export function isCrewSessionDetailProjection(
  value: unknown,
): value is CrewSessionDetailProjection {
  if (!isRecord(value) || !hasExactKeys(value, [
    'task_id', 'thread_id', 'goal', 'origin', 'originator_id',
    'facilitator_id', 'owner_ids', 'state', 'revision', 'success_criteria',
    'expected_deliverable', 'timestamps', 'progress', 'last_result_summary',
    'blocker', 'result', 'verification', 'duplicate_resume_count',
  ])) return false;
  const timestamps = value.timestamps;
  if (!isRecord(timestamps) || !hasExactKeys(timestamps, [
    'created_at', 'transitioned_at', 'started_at', 'first_result_at',
    'verified_at', 'completed_at',
  ])) return false;
  if (!isFiniteNumber(timestamps.created_at)
    || !isFiniteNumber(timestamps.transitioned_at)
    || !isNullableNumber(timestamps.started_at)
    || !isNullableNumber(timestamps.first_result_at)
    || !isNullableNumber(timestamps.verified_at)
    || !isNullableNumber(timestamps.completed_at)) return false;
  const blocker = value.blocker;
  if (blocker !== null && (!isRecord(blocker)
    || !hasExactKeys(blocker, ['reason', 'since', 'duration_seconds', 'action'])
    || typeof blocker.reason !== 'string'
    || !isFiniteNumber(blocker.since)
    || !isFiniteNumber(blocker.duration_seconds)
    || blocker.action !== 'retry_start_work')) return false;
  const sha = /^[0-9a-f]{64}$/;
  const result = value.result;
  if (result !== null && (!isRecord(result)
    || !hasExactKeys(result, ['artifact_id', 'content_hash', 'result_ref', 'evidence_refs'])
    || typeof result.artifact_id !== 'string'
    || typeof result.content_hash !== 'string' || !sha.test(result.content_hash)
    || typeof result.result_ref !== 'string' || !sha.test(result.result_ref)
    || !isStringArray(result.evidence_refs)
    || !result.evidence_refs.every(ref => sha.test(ref)))) return false;
  const verification = value.verification;
  if (verification !== null && (!isRecord(verification)
    || !hasExactKeys(verification, [
      'verifier_agent_id', 'confidence', 'critique', 'accepted_count',
      'total_count', 'convergence_rounds',
    ])
    || typeof verification.verifier_agent_id !== 'string'
    || !isFiniteNumber(verification.confidence)
    || typeof verification.critique !== 'string'
    || !Number.isInteger(verification.accepted_count)
    || !Number.isInteger(verification.total_count)
    || !Number.isInteger(verification.convergence_rounds))) return false;
  return typeof value.task_id === 'string'
    && typeof value.thread_id === 'string'
    && typeof value.goal === 'string'
    && (value.origin === 'captain' || value.origin === 'agent')
    && typeof value.originator_id === 'string'
    && typeof value.facilitator_id === 'string'
    && isStringArray(value.owner_ids)
    && isSessionState(value.state)
    && Number.isInteger(value.revision)
    && isStringArray(value.success_criteria)
    && typeof value.expected_deliverable === 'string'
    && isDetailProgress(value.progress)
    && typeof value.last_result_summary === 'string'
    && Number.isInteger(value.duplicate_resume_count);
}

export function isCrewSessionSummaryProjection(
  value: unknown,
): value is CrewSessionSummaryProjection {
  if (!isRecord(value) || !hasExactKeys(value, [
    'task_id', 'thread_id', 'goal', 'state', 'facilitator_id', 'owner_ids',
    'progress', 'last_result_summary', 'blocker', 'needs_attention',
    'result_artifact_id', 'verified_at',
  ])) return false;
  const progress = value.progress;
  const blocker = value.blocker;
  return typeof value.task_id === 'string'
    && typeof value.thread_id === 'string'
    && typeof value.goal === 'string'
    && isSessionState(value.state)
    && typeof value.facilitator_id === 'string'
    && isStringArray(value.owner_ids)
    && isRecord(progress)
    && hasExactKeys(progress, ['total', 'done', 'failed', 'active'])
    && ['total', 'done', 'failed', 'active'].every(
      key => Number.isInteger(progress[key]) && (progress[key] as number) >= 0,
    )
    && typeof value.last_result_summary === 'string'
    && (blocker === null || (
      isRecord(blocker)
      && hasExactKeys(blocker, ['reason', 'since', 'duration_seconds'])
      && typeof blocker.reason === 'string'
      && isFiniteNumber(blocker.since)
      && isFiniteNumber(blocker.duration_seconds)
    ))
    && typeof value.needs_attention === 'boolean'
    && (value.result_artifact_id === null || typeof value.result_artifact_id === 'string')
    && isNullableNumber(value.verified_at);
}

const LEGACY_WORK_ITEM_KEYS = [
  'id', 'title', 'description', 'work_type', 'status', 'priority', 'parent_id',
  'depends_on', 'assigned_to', 'created_by', 'created_at', 'updated_at', 'due_at',
  'estimated_tokens', 'actual_tokens', 'trust_requirement', 'required_capabilities',
  'tags', 'metadata', 'steps', 'verification', 'schedule', 'ttl_seconds', 'template_id',
] as const;

function hasLegacyWorkItemFields(value: Record<string, unknown>): boolean {
  return typeof value.id === 'string'
    && typeof value.title === 'string'
    && typeof value.description === 'string'
    && typeof value.work_type === 'string'
    && typeof value.status === 'string'
    && isFiniteNumber(value.priority)
    && isNullableString(value.parent_id)
    && isStringArray(value.depends_on)
    && isNullableString(value.assigned_to)
    && typeof value.created_by === 'string'
    && isFiniteNumber(value.created_at)
    && isFiniteNumber(value.updated_at)
    && isNullableNumber(value.due_at)
    && isNullableNumber(value.estimated_tokens)
    && isFiniteNumber(value.actual_tokens)
    && isFiniteNumber(value.trust_requirement)
    && isStringArray(value.required_capabilities)
    && isStringArray(value.tags)
    && isRecord(value.metadata)
    && Array.isArray(value.steps)
    && value.steps.every(isRecord)
    && isRecord(value.verification)
    && isRecord(value.schedule)
    && isNullableNumber(value.ttl_seconds)
    && isNullableString(value.template_id);
}

function isLegacyCrewWorkItemView(value: unknown): value is LegacyCrewWorkItemView {
  return isRecord(value)
    && hasExactKeys(value, LEGACY_WORK_ITEM_KEYS)
    && hasLegacyWorkItemFields(value);
}

function isLegacyCrewVerdict(value: unknown): value is LegacyCrewVerdict {
  return isRecord(value)
    && hasExactKeys(value, [
      'accepted', 'confidence', 'critique', 'verifier_agent_id',
    ])
    && (value.accepted === null || typeof value.accepted === 'boolean')
    && isNullableNumber(value.confidence)
    && typeof value.critique === 'string'
    && typeof value.verifier_agent_id === 'string';
}

function isLegacyCrewChildView(value: unknown): value is LegacyCrewChildView {
  if (!isRecord(value) || !hasExactKeys(value, [
    ...LEGACY_WORK_ITEM_KEYS, 'verdict', 'rounds',
  ])) return false;
  return hasLegacyWorkItemFields(value)
    && (value.verdict === null || isLegacyCrewVerdict(value.verdict))
    && isNullableNumber(value.rounds);
}

function isLegacyCrewTaskTree(value: unknown): value is LegacyCrewTaskTree {
  return isRecord(value)
    && hasExactKeys(value, ['parent', 'children', 'count'])
    && isLegacyCrewWorkItemView(value.parent)
    && Array.isArray(value.children)
    && value.children.every(isLegacyCrewChildView)
    && Number.isInteger(value.count)
    && (value.count as number) >= 0
    && value.count === value.children.length;
}

export async function fetchCrewTaskDetail(parentId: string): Promise<CrewTaskDetailOutcome> {
  try {
    const res = await fetch(`/api/crew-tasks/${encodeURIComponent(parentId)}`);
    if (res.status === 404) return { kind: 'empty' };
    if (!res.ok) return { kind: 'error', status: res.status };
    const data: unknown = await res.json();
    if (isRecord(data) && hasExactKeys(data, ['session'])
      && isCrewSessionDetailProjection(data.session)
      && data.session.task_id === parentId) {
      return { kind: 'success', response: { session: data.session } };
    }
    if (isLegacyCrewTaskTree(data)) {
      return { kind: 'success', response: data };
    }
    return { kind: 'error', status: res.status };
  } catch {
    return { kind: 'error', status: null };
  }
}

export function isRoomSummary(value: unknown): value is RoomSummary {
  if (!isRecord(value)) return false;
  const hasSession = Object.prototype.hasOwnProperty.call(value, 'session');
  if (!hasExactKeys(value, hasSession
    ? ['outputs', 'steps_total', 'steps_done', 'topic', 'session']
    : ['outputs', 'steps_total', 'steps_done', 'topic'])) return false;
  return Number.isInteger(value.outputs)
    && Number.isInteger(value.steps_total)
    && Number.isInteger(value.steps_done)
    && typeof value.topic === 'string'
    && (!hasSession || isCrewSessionSummaryProjection(value.session));
}

// AD-1092: per-room status summaries (todos done/total + outputs) in one call.
export async function fetchRoomSummaries(): Promise<Record<string, RoomSummary>> {
  try {
    const res = await fetch('/api/threads/summaries');
    if (!res.ok) return {};
    const data: unknown = await res.json();
    if (!isRecord(data) || !isRecord(data.summaries)) return {};
    const summaries: Record<string, RoomSummary> = {};
    for (const [threadId, summary] of Object.entries(data.summaries)) {
      if (!isRoomSummary(summary)) continue;
      if ('session' in summary && summary.session.thread_id !== threadId) {
        summaries[threadId] = {
          outputs: summary.outputs,
          steps_total: summary.steps_total,
          steps_done: summary.steps_done,
          topic: summary.topic,
        };
        continue;
      }
      summaries[threadId] = summary;
    }
    return summaries;
  } catch {
    return {};
  }
}

export type RoomSummaryRepairOutcome =
  | { readonly kind: 'success'; readonly summaries: Readonly<Record<string, RoomSummary>> }
  | { readonly kind: 'error'; readonly status: number | null };

export async function repairRoomSummaries(): Promise<RoomSummaryRepairOutcome> {
  try {
    const res = await fetch('/api/threads/summaries');
    if (!res.ok) return { kind: 'error', status: res.status };
    const text = await res.text();
    if (new TextEncoder().encode(text).byteLength > 1024 * 1024) {
      return { kind: 'error', status: res.status };
    }
    let data: unknown;
    try {
      data = JSON.parse(text);
    } catch {
      return { kind: 'error', status: res.status };
    }
    if (!isRecord(data) || !hasExactKeys(data, ['summaries']) || !isRecord(data.summaries)) {
      return { kind: 'error', status: res.status };
    }
    if (Object.keys(data.summaries).length > 1000) {
      return { kind: 'error', status: res.status };
    }
    const summaries: Record<string, RoomSummary> = {};
    for (const [threadId, summary] of Object.entries(data.summaries)) {
      if (!isBoundedLiveThreadId(threadId) || !isRoomSummary(summary)) {
        return { kind: 'error', status: res.status };
      }
      if ('session' in summary && summary.session.thread_id !== threadId) {
        return { kind: 'error', status: res.status };
      }
      summaries[threadId] = summary;
    }
    return { kind: 'success', summaries };
  } catch {
    return { kind: 'error', status: null };
  }
}

function isBoundedLiveThreadId(value: string): boolean {
  return value.length > 0 && value.length <= 128;
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
 * AD-971: fetch a single thread's CURRENT persisted state.
 * GET /api/threads/{id}  -> thread.to_dict() (404/parse/!ok honest-degrade to
 * null). Used to re-hydrate a thread on open so newly-added participants (which
 * the backend persisted) are never clobbered by a stale in-memory list object.
 */
export async function getThread(
  threadId: string,
): Promise<AD791aChatThreadView | null> {
  try {
    const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}`);
    if (!res.ok) return null;
    const data = (await res.json()) as AD791aChatThreadView;
    return data && typeof data.id === 'string' ? data : null;
  } catch {
    return null;
  }
}

/**
 * AD-1058: get-or-create the canonical default 1:1 thread for a crew agent
 * WITHOUT sending a message — lets the HXI start a call from a fresh chat. The
 * server returns the SAME race-safe default thread the first DM resolves to, so
 * a later message reconciles to it (never forks a parallel thread). 404 (unknown
 * agent) / 400 (non-crew) / parse / !ok all honest-degrade to null.
 */
export async function getOrCreateAgentThread(
  agentId: string,
): Promise<AD791aChatThreadView | null> {
  try {
    const res = await fetch(`/api/agent/${encodeURIComponent(agentId)}/thread`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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

/**
 * AD-938: a single thread message as returned by GET /api/threads/{id}/messages.
 * Verified shape (ChatThreadMessage.to_dict, ``threads/__init__.py:140``):
 * ``{id, thread_id, author_id, role, body, created_at, metadata}``.
 */
export interface ThreadMessageDTO {
  id: string;
  thread_id: string;
  author_id: string;
  role: string;
  body: string;
  created_at: number;
  metadata?: Record<string, unknown> | null;
}

export type ThreadMessageRepairOutcome =
  | { readonly kind: 'success'; readonly messages: readonly ThreadMessageDTO[] }
  | { readonly kind: 'error'; readonly status: number | null };

function isThreadMessageDTO(value: unknown, threadId: string): value is ThreadMessageDTO {
  return isRecord(value)
    && hasExactKeys(value, [
      'id', 'thread_id', 'author_id', 'role', 'body', 'created_at', 'metadata',
    ])
    && typeof value.id === 'string' && value.id.length > 0 && value.id.length <= 128
    && value.thread_id === threadId
    && typeof value.author_id === 'string' && value.author_id.length > 0 && value.author_id.length <= 128
    && ['captain', 'agent', 'system'].includes(String(value.role))
    && typeof value.body === 'string'
    && isFiniteNumber(value.created_at) && value.created_at >= 0
    && isRecord(value.metadata);
}

export async function repairThreadMessages(
  threadId: string,
): Promise<ThreadMessageRepairOutcome> {
  try {
    const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}/messages?limit=200`);
    if (!res.ok) return { kind: 'error', status: res.status };
    const text = await res.text();
    if (new TextEncoder().encode(text).byteLength > 1024 * 1024) {
      return { kind: 'error', status: res.status };
    }
    let data: unknown;
    try {
      data = JSON.parse(text);
    } catch {
      return { kind: 'error', status: res.status };
    }
    if (!isRecord(data) || !hasExactKeys(data, ['thread_id', 'messages'])) {
      return { kind: 'error', status: res.status };
    }
    if (data.thread_id !== threadId || !Array.isArray(data.messages) || data.messages.length > 200) {
      return { kind: 'error', status: res.status };
    }
    const seen = new Set<string>();
    const messages: ThreadMessageDTO[] = [];
    for (const candidate of data.messages) {
      if (!isThreadMessageDTO(candidate, threadId) || seen.has(candidate.id)) {
        return { kind: 'error', status: res.status };
      }
      seen.add(candidate.id);
      messages.push(candidate);
    }
    return { kind: 'success', messages };
  } catch {
    return { kind: 'error', status: null };
  }
}

/**
 * AD-938: list a thread's persisted messages.
 * GET /api/threads/{id}/messages?limit=N -> {thread_id, messages: [...]} (verified
 * ``routers/threads.py:302``). Tier-2 honest-degrade: returns ``[]`` on a
 * network/!ok/parse failure so the transcript keeps rendering its current state.
 */
export async function listMessages(threadId: string, limit = 200): Promise<ThreadMessageDTO[]> {
  try {
    const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}/messages?limit=${limit}`);
    if (!res.ok) return [];
    const data = (await res.json()) as { messages?: ThreadMessageDTO[] };
    return Array.isArray(data?.messages) ? data.messages : [];
  } catch {
    return [];
  }
}
