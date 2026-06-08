// AD-917: tests for the ProfileChatTab Captain send-routing branch. The full
// ProfileChatTab is too heavy to render (audio/screen deps) — same rationale
// as ProfileChatTab.bf294b.test.tsx — so the AD-917 group/solo decision is
// exercised through a faithful mirror of the branch in
// ProfileChatTab.sendText. If that production branch changes, update this
// mirror. Plain fetch-mock pattern (vi.stubGlobal('fetch', ...)).
import { describe, it, expect, vi, afterEach } from 'vitest';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

type ThreadView = { id: string; participants: string[] };
type AgentLite = { id: string; isCrew: boolean };

// Mirror of the AD-917 send-routing branch (ProfileChatTab.tsx). Routes to the
// AD-914 group fan-out endpoint when the active thread has >=2 crew
// participants; otherwise the byte-identical 1:1 /api/agent/{id}/chat path.
async function routeSend(opts: {
  agentId: string;
  threadIdProp?: string;
  threadIdByAgent: Map<string, string>;
  chatThreads: Map<string, ThreadView>;
  agents: Map<string, AgentLite>;
  text: string;
  attachmentIds: string[];
}): Promise<'group' | 'solo'> {
  const { agentId, threadIdProp, threadIdByAgent, chatThreads, agents, text, attachmentIds } = opts;
  const groupThreadId = threadIdProp ?? threadIdByAgent.get(agentId);
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
          attachment_ids: attachmentIds,
        }),
      });
      return 'group';
    }
  }
  await fetch(`/api/agent/${agentId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text || '(attachment)', attachment_ids: attachmentIds }),
  });
  return 'solo';
}

function twoCrewThread(): { chatThreads: Map<string, ThreadView>; agents: Map<string, AgentLite> } {
  const chatThreads = new Map<string, ThreadView>([
    ['t1', { id: 't1', participants: ['captain', 'a1', 'a2'] }],
  ]);
  const agents = new Map<string, AgentLite>([
    ['a1', { id: 'a1', isCrew: true }],
    ['a2', { id: 'a2', isCrew: true }],
  ]);
  return { chatThreads, agents };
}

describe('AD-917 ProfileChatTab group send-routing', () => {
  it('routes a Captain send to POST /api/threads/{id}/messages when >=2 crew participants', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ per_agent_replies: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    const { chatThreads, agents } = twoCrewThread();

    const route = await routeSend({
      agentId: 'a1', threadIdProp: 't1', threadIdByAgent: new Map(), chatThreads, agents,
      text: 'status?', attachmentIds: [],
    });

    expect(route).toBe('group');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/threads/t1/messages');
    expect(fetchMock.mock.calls[0][0]).not.toBe('/api/agent/a1/chat');
  });

  it('includes attachment_ids in the group message POST body', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ per_agent_replies: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    const { chatThreads, agents } = twoCrewThread();

    await routeSend({
      agentId: 'a1', threadIdProp: 't1', threadIdByAgent: new Map(), chatThreads, agents,
      text: 'see this', attachmentIds: ['sha-1', 'sha-2'],
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.attachment_ids).toEqual(['sha-1', 'sha-2']);
    expect(body.author_id).toBe('captain');
    expect(body.role).toBe('captain');
    expect(body.body).toBe('see this');
  });

  it('attach-only group send uses the non-empty (attachment) body placeholder', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ per_agent_replies: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    const { chatThreads, agents } = twoCrewThread();

    await routeSend({
      agentId: 'a1', threadIdProp: 't1', threadIdByAgent: new Map(), chatThreads, agents,
      text: '', attachmentIds: ['sha-1'],
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.body).toBe('(attachment)');
    expect(body.body.length).toBeGreaterThanOrEqual(1);
  });

  it('a 1:1 thread (<=1 crew) still posts to /api/agent/{id}/chat', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ response: 'hi' }) });
    vi.stubGlobal('fetch', fetchMock);
    const chatThreads = new Map<string, ThreadView>([['t1', { id: 't1', participants: ['captain', 'a1'] }]]);
    const agents = new Map<string, AgentLite>([['a1', { id: 'a1', isCrew: true }]]);

    const route = await routeSend({
      agentId: 'a1', threadIdProp: 't1', threadIdByAgent: new Map(), chatThreads, agents,
      text: 'hello', attachmentIds: [],
    });

    expect(route).toBe('solo');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/agent/a1/chat');
  });

  it('group send body contains no emoji (HXI #3)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ per_agent_replies: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    const { chatThreads, agents } = twoCrewThread();

    await routeSend({
      agentId: 'a1', threadIdProp: 't1', threadIdByAgent: new Map(), chatThreads, agents,
      text: '', attachmentIds: ['sha-1'],
    });

    const raw = fetchMock.mock.calls[0][1].body as string;
    expect(raw).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
