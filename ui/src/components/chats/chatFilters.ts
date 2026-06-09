/**
 * AD-931: pure conversation-filter helpers for the unified CHATS surface.
 *
 * Moved verbatim from the AD-919 `GroupChatListPanel` (renamed to `ChatsPanel`
 * by AD-931) so the panel and its unit tests share one source of truth. The new
 * `isChat` widens `isGroupChat` to admit 1:1 conversations while EXCLUDING
 * AD-925 task-workspace rooms (which carry a `task_id`) — this reads like Teams'
 * *Chat* list, not its *Teams/Channels* list.
 *
 * Per HXI Design Principle #3: amber accent `#f0b060`, inactive `#666680`.
 */
import type { AD791aChatThreadView } from '../../store/useStore';
import type { Agent } from '../../store/types';

// The Captain participant is the literal "captain" sentinel. Verified consistent
// across the stack (AD-914 fan-out crew gate excludes it, AD-917 GroupChatHeader
// strips it, era-4/5 Captain posts use author_id="captain"). era-5 note: a future
// canonical captain DID / is_captain() helper makes this a one-line swap.
export const CAPTAIN_PARTICIPANT_ID = 'captain';

export const COLOR_ACTIVE = '#f0b060';
export const COLOR_INACTIVE = '#666680';

export type AgentMap = Map<string, Agent>;

/** Crew participant ids: not the Captain sentinel, resolves as a crew agent. */
export function crewParticipantIds(thread: AD791aChatThreadView, agents: AgentMap): string[] {
  return thread.participants.filter(
    (p) => p !== CAPTAIN_PARTICIPANT_ID && agents.get(p)?.isCrew === true,
  );
}

/** AD-918 agent-initiated tag. */
export function isAgentCreated(thread: AD791aChatThreadView): boolean {
  return !!thread.metadata?.created_by_agent;
}

/** A group chat = agent-initiated OR >=2 crew participants (AD-919 Decision C). */
export function isGroupChat(thread: AD791aChatThreadView, agents: AgentMap): boolean {
  return isAgentCreated(thread) || crewParticipantIds(thread, agents).length >= 2;
}

/**
 * AD-931: a "chat" = a 1:1 or group CONVERSATION, never a task-workspace room.
 *
 * Widens `isGroupChat` to also admit 1:1s (a single crew participant, e.g. the
 * per-agent default thread `metadata.is_default=true`) while EXCLUDING AD-925
 * task rooms — which always carry a `task_id`. The `!task_id` gate is the
 * exclusion key; everything else mirrors `isGroupChat` but at a >=1 crew floor.
 */
export function isChat(thread: AD791aChatThreadView, agents: AgentMap): boolean {
  if (thread.task_id) return false; // exclude AD-925 task rooms
  return isAgentCreated(thread) || crewParticipantIds(thread, agents).length >= 1;
}

/** Whether the Captain sentinel is already a participant. */
export function captainJoined(thread: AD791aChatThreadView): boolean {
  return thread.participants.includes(CAPTAIN_PARTICIPANT_ID);
}

/** Host = first crew participant (the AD-917 chat is rendered in its panel). */
export function hostAgentId(thread: AD791aChatThreadView, agents: AgentMap): string | null {
  return crewParticipantIds(thread, agents)[0] ?? null;
}

/**
 * AD-942: the canonical display name for a chat row / header.
 *
 * Teams/Slack convention: a DM or group chat is named by its PARTICIPANTS, not
 * by message content. Agent-initiated chats (AD-918/AD-924) can land a
 * conversational phrase in ``thread.title`` (e.g. "Hello Yeo", "Thanks, let me
 * know if anything changes"), which read as noise in the list. So the display
 * name is the crew callsigns joined by ", " — UNLESS the Captain explicitly
 * renamed the room (``metadata.title_locked`` via the AD-917 GroupChatHeader
 * rename / AD-794 set_title(lock=True)), in which case the deliberate title
 * wins. Honest-degrade: when no crew resolves (agents not hydrated) fall back
 * to the stored title, then a neutral "Chat".
 */
export function chatDisplayName(thread: AD791aChatThreadView, agents: AgentMap): string {
  const locked = !!(thread.metadata as { title_locked?: unknown } | undefined)?.title_locked;
  if (locked && thread.title.trim()) return thread.title;
  const names = crewParticipantIds(thread, agents)
    .map((id) => agents.get(id)?.callsign)
    .filter((c): c is string => !!c);
  if (names.length > 0) return names.join(', ');
  return thread.title.trim() || 'Chat';
}
