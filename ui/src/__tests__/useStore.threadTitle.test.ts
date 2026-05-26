/**
 * AD-794 vitest — chat response with a new ``title`` field hydrates
 * the local chatThreads map.
 *
 * Per AD-794, first-turn auto-naming runs on the server and returns
 * the updated title alongside thread_id. The UI must update its
 * chatThreads map so the AD-792 sidebar (and any other consumer)
 * sees the rename without a /api/threads round-trip.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { useStore } from '../store/useStore';

async function sendChatTurn(agentId: string, message: string): Promise<void> {
  const body: Record<string, unknown> = { message, history: [], attachment_ids: [] };
  const res = await fetch(`/api/agent/${agentId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (typeof data?.thread_id === 'string' && data.thread_id.length > 0) {
    useStore.getState().setThreadForAgent(agentId, data.thread_id);
    if (typeof data?.title === 'string' && data.title.length > 0) {
      const _view = useStore.getState().chatThreads.get(data.thread_id);
      const _next = _view
        ? { ..._view, title: data.title, last_active_at: Date.now() / 1000 }
        : {
            id: data.thread_id,
            title: data.title,
            participants: [agentId],
            created_at: Date.now() / 1000,
            last_active_at: Date.now() / 1000,
          };
      useStore.getState().setChatThread(_next);
    }
  }
}

beforeEach(() => {
  useStore.setState({
    threadIdByAgent: new Map(),
    chatThreads: new Map(),
    activeThreadId: null,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('AD-794 chat-response title hydration', () => {
  it('inserts a new thread view when response carries a fresh title', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async () =>
      new Response(
        JSON.stringify({
          response: 'Working on it.',
          thread_id: 'thread-warp-coil',
          title: 'Investigate warp coil',
        }),
        { status: 200 },
      ),
    );

    await sendChatTurn('agent-ezri', 'Help me investigate the warp coil.');

    const view = useStore.getState().chatThreads.get('thread-warp-coil');
    expect(view).toBeDefined();
    expect(view!.title).toBe('Investigate warp coil');
    expect(view!.id).toBe('thread-warp-coil');
  });

  it('updates an existing thread view when the title changes', async () => {
    // Seed an existing view.
    useStore.getState().setChatThread({
      id: 'thread-1',
      title: 'Ezri',
      participants: ['agent-ezri'],
      created_at: 1000,
      last_active_at: 1000,
    });

    vi.spyOn(global, 'fetch').mockImplementation(async () =>
      new Response(
        JSON.stringify({
          response: 'Sure.',
          thread_id: 'thread-1',
          title: 'Renamed by auto-name',
        }),
        { status: 200 },
      ),
    );

    await sendChatTurn('agent-ezri', 'A long message body.');

    const view = useStore.getState().chatThreads.get('thread-1');
    expect(view!.title).toBe('Renamed by auto-name');
    expect(view!.participants).toEqual(['agent-ezri']);
  });

  it('leaves the chatThreads map untouched when no title is returned', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async () =>
      new Response(
        JSON.stringify({ response: 'Ack', thread_id: 'thread-2' }),
        { status: 200 },
      ),
    );

    await sendChatTurn('agent-ezri', 'hi');

    // thread_id was cached, but no thread view exists (no title).
    expect(useStore.getState().threadIdByAgent.get('agent-ezri')).toBe('thread-2');
    expect(useStore.getState().chatThreads.has('thread-2')).toBe(false);
  });
});
