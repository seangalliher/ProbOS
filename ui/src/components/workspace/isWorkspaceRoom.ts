/**
 * AD-929: workspace-room gate for the unified "Files" rail.
 *
 * A pure predicate over client-side store data — no fetch, no side
 * effects. Returns true when the active thread is a task workspace:
 *   - ``task_id`` is set  ⇒ an AD-925 auto task room (authoritative), OR
 *   - it has ≥ 2 crew participants ⇒ a group room (AD-917 turns a 1:1
 *     into a group at the 2nd crew participant).
 * A 1:1 DM (one crew participant, no ``task_id``) is NOT a workspace
 * room, so ``ProfileChatTab`` renders no Files rail beside it.
 *
 * The crew-count idiom is the verbatim ``GroupChatHeader`` filter
 * (exclude the Captain, resolve each id to its agent, keep only crew).
 */
import type { AD791aChatThreadView } from '../../store/useStore';
import type { Agent } from '../../store/types';

export function isWorkspaceRoom(
  thread: AD791aChatThreadView | undefined,
  agents: Map<string, Agent>,
): boolean {
  if (!thread) return false;
  // A set task_id is the authoritative "this is a workspace" marker.
  if (thread.task_id) return true;
  // Otherwise it is a workspace only once it holds ≥ 2 crew participants
  // (a group room). Reuse the GroupChatHeader crew filter verbatim.
  const crewCount = (thread.participants ?? [])
    .filter((id) => id !== 'captain')
    .map((id) => ({ id, agent: agents.get(id) }))
    .filter((p): p is { id: string; agent: Agent } => !!p.agent && p.agent.isCrew)
    .length;
  return crewCount >= 2;
}
