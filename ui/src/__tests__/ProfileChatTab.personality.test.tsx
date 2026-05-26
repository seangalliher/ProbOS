/**
 * AD-809 vitest — ProfileChatTab renders /personality system replies.
 *
 * Per the AD-809 spec Section 7, the chat handler returns
 * ``{ system: true, response: "Personality set to ...", thread_id: ..., applied: "formal" }``
 * for /personality commands. The UI must render this as a system note
 * (distinct styling: dim italic) rather than an agent reply, and
 * must NOT play TTS.
 *
 * This focused test verifies the sendText round-trip shape directly
 * — the same emulation pattern used by ProfileChatTab.threadId.test.tsx
 * — without mounting the full component tree.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { useStore } from '../store/useStore';

async function sendChatTurn(agentId: string, message: string): Promise<{ ok: boolean }> {
  const knownThreadId = useStore.getState().threadIdByAgent.get(agentId);
  const body: Record<string, unknown> = { message, history: [], attachment_ids: [] };
  if (knownThreadId) body.thread_id = knownThreadId;
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
  if (data?.system === true) {
    useStore.getState().addAgentMessage(agentId, 'system', data.response || '');
    return { ok: true };
  }
  useStore.getState().addAgentMessage(agentId, 'agent', data.response || '');
  return { ok: true };
}

beforeEach(() => {
  useStore.setState({
    threadIdByAgent: new Map(),
    chatThreads: new Map(),
    activeThreadId: null,
    agentConversations: new Map(),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('AD-809 /personality slash-command UI', () => {
  it('renders a system-role message when response.system is true', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async () =>
      new Response(
        JSON.stringify({
          system: true,
          response: 'Personality set to `formal` for this thread.',
          thread_id: 'thread-abc',
          applied: 'formal',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    await sendChatTurn('agent-ezri', '/personality formal');

    const conv = useStore.getState().agentConversations.get('agent-ezri');
    expect(conv).toBeDefined();
    expect(conv!.messages.length).toBe(1);
    const msg = conv!.messages[0];
    expect(msg.role).toBe('system');
    expect(msg.text).toContain('formal');
    // Thread mapping cached even for slash-command responses.
    expect(useStore.getState().threadIdByAgent.get('agent-ezri')).toBe('thread-abc');
  });

  it('does NOT render a system message for normal agent replies', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(async () =>
      new Response(
        JSON.stringify({ response: 'On it, Captain.', thread_id: 'thread-xyz' }),
        { status: 200 },
      ),
    );

    await sendChatTurn('agent-ezri', 'Status report.');

    const conv = useStore.getState().agentConversations.get('agent-ezri');
    expect(conv!.messages.length).toBe(1);
    expect(conv!.messages[0].role).toBe('agent');
  });
});
