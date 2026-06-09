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
