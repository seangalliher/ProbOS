// AD-938: thread-keyed transcript helpers for the profile chat tab.
//
// Extracted from ProfileChatTab (the AD-936 ChatMessageRow precedent): the
// parent module pulls in heavy audio/screen deps that make it impractical to
// import under jsdom, so these pure/data-path helpers live here to stay
// independently testable. ProfileChatTab imports ``selectTranscriptMessages``
// (render source switch) and ``loadThreadMessages`` (the load-on-open effect).
import type { Agent, AgentProfileMessage } from '../../store/types';
import { listMessages, type ThreadMessageDTO } from '../sidebar/threadApi';

/** Map a persisted thread message (GET /messages DTO) into the profile
 *  transcript model. ``role`` collapses to the AD-936 three-state set: a
 *  ``captain`` author becomes a right-aligned ``'user'`` bubble (no avatar); an
 *  ``agent`` author keeps its per-message identity (``authorId`` + resolved
 *  ``callsign``) so ChatMessageRow shows the author avatar + name label;
 *  anything else renders as a centered ``'system'`` note. */
export function threadDtoToMessage(
  m: ThreadMessageDTO, agents: Map<string, Agent>,
): AgentProfileMessage {
  const isAgent = m.role === 'agent';
  return {
    id: m.id,
    role: m.role === 'captain' ? 'user' : (isAgent ? 'agent' : 'system'),
    text: m.body,
    timestamp: m.created_at,
    authorId: isAgent ? m.author_id : undefined,
    callsign: isAgent ? (agents.get(m.author_id)?.callsign ?? undefined) : undefined,
  };
}

/** Choose the displayed transcript. With an active thread (group or warm 1:1)
 *  render that thread's real messages; with no thread (a cold 1:1 before its
 *  first send) fall back to the per-agent ``agentConversations`` buffer so the
 *  AD-406 first-send UX is unchanged. */
export function selectTranscriptMessages(
  activeThreadId: string | null | undefined,
  threadMsgs: AgentProfileMessage[] | undefined,
  conversationMsgs: AgentProfileMessage[] | undefined,
): AgentProfileMessage[] {
  return activeThreadId ? (threadMsgs ?? []) : (conversationMsgs ?? []);
}

// AD-1056: chat transcript day-separators + render cap. Messages carry
// ``timestamp`` as UNIX seconds (server ``time.time()``; same convention as
// threadGrouping.ts). The transcript inserts a calendar-day separator before the
// first message of each new LOCAL day, and renders at most
// ``TRANSCRIPT_RENDER_CAP`` of the most recent messages so opening a long
// history is a bounded view, not a disorienting wall of text streamed from the
// top.

export const TRANSCRIPT_RENDER_CAP = 200;

export type TranscriptItem =
  | { kind: 'day'; id: string; label: string }
  | { kind: 'msg'; id: string; msg: AgentProfileMessage };

/** Local calendar-day key (YYYY-M-D) for a UNIX-seconds timestamp. Returns ''
 *  for a missing/invalid timestamp so such messages never force a separator. */
function dayKeyOfSeconds(timestampSec: number): string {
  if (!timestampSec || !Number.isFinite(timestampSec)) return '';
  const d = new Date(timestampSec * 1000);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

/** Human label for a day separator: Today / Yesterday / a locale date. ``nowMs``
 *  is injected so tests can pin a fixed reference instant. */
export function transcriptDayLabel(timestampSec: number, nowMs: number): string {
  const dayMs = 86_400_000;
  const startOfToday = new Date(nowMs).setHours(0, 0, 0, 0);
  const startOfYesterday = startOfToday - dayMs;
  const ms = timestampSec * 1000;
  if (ms >= startOfToday) return 'Today';
  if (ms >= startOfYesterday) return 'Yesterday';
  return new Date(ms).toLocaleDateString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
  });
}

/** Build the renderable transcript: cap to the most recent ``cap`` messages,
 *  then insert a day separator before the first message of each local day. A
 *  ``cap`` of 0 disables the cap. Pure — no DOM/store deps, so it is exercised
 *  by a focused vitest. */
export function buildTranscriptItems(
  messages: AgentProfileMessage[],
  opts: { nowMs?: number; cap?: number } = {},
): TranscriptItem[] {
  const cap = opts.cap ?? TRANSCRIPT_RENDER_CAP;
  const nowMs = opts.nowMs ?? Date.now();
  const capped = cap > 0 && messages.length > cap
    ? messages.slice(messages.length - cap)
    : messages;
  const items: TranscriptItem[] = [];
  let lastDayKey = '';
  for (const msg of capped) {
    const dayKey = dayKeyOfSeconds(msg.timestamp);
    if (dayKey && dayKey !== lastDayKey) {
      lastDayKey = dayKey;
      items.push({ kind: 'day', id: `day-${dayKey}`, label: transcriptDayLabel(msg.timestamp, nowMs) });
    }
    items.push({ kind: 'msg', id: msg.id, msg });
  }
  return items;
}

/** Load a thread's persisted transcript and publish it to the store.
 *  ``listMessages`` already Tier-2 degrades to ``[]``; the setter is injected so
 *  the caller can guard against a stale/unmounted write. */
export async function loadThreadMessages(
  threadId: string,
  agents: Map<string, Agent>,
  setThreadMessages: (threadId: string, msgs: AgentProfileMessage[]) => void,
): Promise<void> {
  const dtos = await listMessages(threadId);
  setThreadMessages(threadId, dtos.map((m) => threadDtoToMessage(m, agents)));
}
