/**
 * AD-815b: Chat-with-agent helper.
 *
 * Resolves to the AD-791 chat thread the desktop should focus when the
 * Captain picks an agent from the tray submenu (or the in-window
 * "New chat" picker). Reuses the most recently active non-archived 1:1
 * thread when one exists; creates a fresh one otherwise.
 *
 * Pure adapter around the runtime REST surface — accepts the fetch
 * implementation so tests can inject a stub.
 */

export interface AgentSummary {
  id: string;
  name: string;
}

export interface Thread {
  id: string;
  title: string;
  participants: string[];
  archived: boolean;
  last_active_at: number;
}

export interface ChatWithAgentClient {
  /** Returns the existing thread list ordered by recent activity. */
  listThreads: () => Promise<Thread[]>;
  /** Creates a new thread with the supplied options. */
  createThread: (opts: {
    title: string;
    participants: string[];
  }) => Promise<Thread>;
}

/**
 * Resolve to the thread id the desktop should focus.
 *
 * Strategy:
 *   1. Pick the most-recently-active non-archived thread whose
 *      participants list is exactly `[agent.id]`.
 *   2. Otherwise, create a new "Chat with <name>" thread and return its id.
 */
export async function startChatWithAgent(
  agent: AgentSummary,
  client: ChatWithAgentClient,
): Promise<string> {
  const existing = await client.listThreads();
  const reusable = existing
    .filter(
      (t) =>
        !t.archived &&
        t.participants.length === 1 &&
        t.participants[0] === agent.id,
    )
    .sort((a, b) => b.last_active_at - a.last_active_at);
  if (reusable.length > 0) {
    return reusable[0].id;
  }
  const fresh = await client.createThread({
    title: `Chat with ${agent.name}`,
    participants: [agent.id],
  });
  return fresh.id;
}
