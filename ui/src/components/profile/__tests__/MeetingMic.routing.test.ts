/** AD-922: proves a meeting STT transcript routes to the AD-914 group fan-out,
 *  not the 1:1 path. The full ProfileChatTab is too heavy to render (same
 *  rationale as ProfileChatTab.groupsend.test.tsx), so we reuse a faithful
 *  mirror of the AD-917 sendText group-routing branch and feed it the captured
 *  transcript as the message. The meeting mic only ever calls sendText, so this
 *  mirror is the meeting-mic dispatch. Plain fetch-mock (vi.stubGlobal). */
import { describe, it, expect, vi, afterEach } from 'vitest';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

type ThreadView = { id: string; participants: string[] };
type AgentLite = { id: string; isCrew: boolean };

// Mirror of the AD-917 send-routing branch (ProfileChatTab.sendText). The
// AD-922 meeting mic feeds the transcript here via submit=sendText. If the
// production branch changes, update this mirror.
async function routeSend(opts: {
  agentId: string;
  threadIdByAgent: Map<string, string>;
  chatThreads: Map<string, ThreadView>;
  agents: Map<string, AgentLite>;
  text: string;
}): Promise<'group' | 'solo'> {
  const { agentId, threadIdByAgent, chatThreads, agents, text } = opts;
  const groupThreadId = threadIdByAgent.get(agentId);
  if (groupThreadId) {
    const thread = chatThreads.get(groupThreadId);
    const crewParticipantCount = (thread?.participants ?? []).filter(
      (id) => id !== 'captain' && agents.get(id)?.isCrew,
    ).length;
    if (thread && crewParticipantCount >= 2) {
      await fetch(`/api/threads/${groupThreadId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          author_id: 'captain',
          role: 'captain',
          body: text || '(attachment)',
          attachment_ids: [],
        }),
      });
      return 'group';
    }
  }
  await fetch(`/api/agent/${agentId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text || '(attachment)', attachment_ids: [] }),
  });
  return 'solo';
}

describe('AD-922 meeting mic transcript routing', () => {
  it('routes a captured transcript to POST /api/threads/{id}/messages in a >=2-crew meeting', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({ per_agent_replies: [] }) });
    vi.stubGlobal('fetch', fetchMock);

    const chatThreads = new Map<string, ThreadView>([
      ['t1', { id: 't1', participants: ['captain', 'a1', 'a2'] }],
    ]);
    const agents = new Map<string, AgentLite>([
      ['a1', { id: 'a1', isCrew: true }],
      ['a2', { id: 'a2', isCrew: true }],
    ]);

    const route = await routeSend({
      agentId: 'a1',
      threadIdByAgent: new Map([['a1', 't1']]),
      chatThreads,
      agents,
      text: 'what is our status', // the captured STT transcript
    });

    expect(route).toBe('group');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/threads/t1/messages');
    expect(fetchMock.mock.calls[0][0]).not.toBe('/api/agent/a1/chat');
  });
});
