// AD-917: tests for the ProfileChatTab Captain send-routing branch. The full
// ProfileChatTab is too heavy to render (audio/screen deps) — same rationale
// as ProfileChatTab.bf294b.test.tsx — so the AD-917 group/solo decision is
// exercised through a faithful mirror of the branch in
// ProfileChatTab.sendText. If that production branch changes, update this
// mirror. Plain fetch-mock pattern (vi.stubGlobal('fetch', ...)).
import { describe, it, expect, vi, afterEach } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Agent } from '../../../store/types';
import { resolveFirstResponder } from '../../../chat/firstResponder';
import { ProfileChatTab } from '../ProfileChatTab';
import { useStore } from '../../../store/useStore';

vi.mock('../../../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => false, startListening: vi.fn(), stopListening: vi.fn(),
}));
vi.mock('../../../audio/conversationController', () => ({
  armConversationMode: vi.fn(() => () => {}), disarmConversationMode: vi.fn(), markAgentReplyComplete: vi.fn(),
}));
vi.mock('../../../audio/transformersStt', () => ({
  armTransformersStt: vi.fn(), disarmTransformersStt: vi.fn(),
  onTransformersTranscript: vi.fn(() => () => {}),
  onTransformersTranscribing: vi.fn(() => () => {}), onTransformersProgress: vi.fn(() => () => {}),
}));
vi.mock('../../../hooks/useCameraStream', () => ({
  startCameraStream: vi.fn(async () => undefined), stopCameraStream: vi.fn(async () => undefined),
}));
vi.mock('../MeetingView', () => ({ MeetingView: () => null }));
vi.mock('../../workspace/WorkspaceFilesRail', () => ({ WorkspaceFilesRail: () => null }));

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
  it.each([
    { filename: 'reviews.csv', expectedFilename: 'reviews.csv', status: 200 },
    { filename: 'why?.csv', expectedFilename: 'why.csv', status: 200 },
    { filename: '\u6587'.repeat(90) + '.csv', expectedFilename: '\u6587'.repeat(85), status: 200 },
    { filename: 'reviews.csv', expectedFilename: 'reviews.csv', status: 422 },
    { filename: 'accepted.csv', expectedFilename: 'accepted.csv', status: 200, invalidJson: true },
  ])('forwards a safe picked filename and preserves rejected sends: $filename / $status', async ({ filename, expectedFilename, status, invalidJson }) => {
    const initialState = useStore.getState();
    const scrollBefore = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView');
    const storageBefore = Object.fromEntries(Object.keys(localStorage).map(key => [key, localStorage.getItem(key)!]));
    const hash = 'a'.repeat(64);
    const thread = {
      id: 't1', title: 'Inputs', participants: ['captain', 'a1', 'a2'],
      created_at: 1, last_active_at: 1, task_id: null, metadata: {},
    };
    const response = (body: unknown): Response => new Response(JSON.stringify(body), {
      headers: { 'Content-Type': 'application/json' },
    });
    const upload = vi.fn((init: RequestInit) => {
      const file = (init.body as FormData).get('file') as File;
      expect(file.name).toBe(filename);
      expect(file.size).toBeGreaterThan(0);
      return response({ attachment_id: hash, sha256: hash, mime: 'text/csv', size_bytes: file.size, url: `/api/chat/attachments/${hash}` });
    });
    const groupPost = vi.fn((init: RequestInit) => {
      const request = JSON.parse(String(init.body));
      if (status !== 200) return new Response(JSON.stringify({ detail: 'invalid attachment label' }), { status });
      if (invalidJson) return new Response('invalid response', { status: 200 });
      return response({ id: 'persisted-captain', thread_id: 't1', author_id: 'captain', role: 'captain',
        body: request.body, created_at: 2, metadata: request.metadata, per_agent_replies: [] });
    });
    try {
      localStorage.clear();
      Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
      useStore.setState({
        activeProfileAgent: 'a1', activeProfileThreadId: 't1', activeThreadId: null,
        agents: new Map(['a1', 'a2'].map(id => [id, mkAgent({ id, callsign: id, isCrew: true })])),
        chatThreads: new Map([['t1', thread]]), threadIdByAgent: new Map(),
        threadMessages: new Map(), agentConversations: new Map(), chatDrafts: {},
        artifactsByThread: new Map(), selectedArtifactId: null, typingAgent: null,
        liveRepairEpoch: 0, liveThreadRefresh: null, voiceEnabled: false, callAudioEnabled: false,
      });
      vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === '/api/chat/attachments/multipart' && init?.method === 'POST') return upload(init);
        if (url === '/api/threads/t1/messages' && init?.method === 'POST') return groupPost(init);
        if (url === '/api/threads/t1/messages?limit=200') return response({ thread_id: 't1', messages: [] });
        if (url === '/api/threads/t1') return response(thread);
        if (url.endsWith('/chat/history')) return response({ memories: [] });
        if (url.endsWith('/profile')) return response({ voiceProfile: null });
        if (url.endsWith('/tts/status')) return response({ enabled: false, backend: 'browser' });
        if (url === '/api/voice/health') return response({ primary_stt: 'browser', engine: 'browser', backend_available: true, healthy: true });
        return response({});
      }));
      const view = render(<ProfileChatTab agentId="a1" threadId="t1" />);
      await act(async () => { await Promise.resolve(); });
      const picker = view.container.querySelector<HTMLInputElement>('input[type="file"]');
      expect(picker).not.toBeNull();
      fireEvent.change(picker!, { target: { files: [new File(['id,status\nT04,open'], filename, { type: 'text/csv' })] } });
      expect(await screen.findByText(filename)).toBeTruthy();
      expect(upload).toHaveBeenCalledTimes(1);
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: /^Send$/ })); });
      await waitFor(() => expect(groupPost).toHaveBeenCalledTimes(1));
      const request = JSON.parse(String(groupPost.mock.calls[0][0].body));
      expect(request.attachment_ids).toEqual([hash]);
      expect(request.attachment_filenames).toEqual({ [hash]: expectedFilename });
      expect(request.body).toBe('(attachment)');
      expect(request.metadata.client_message_id).toEqual(expect.any(String));
      if (status === 200) {
        expect(screen.queryByRole('button', { name: 'remove attachment' })).toBeNull();
        expect(useStore.getState().agentConversations.get('a1')?.messages.filter(message => message.role === 'user'))
          .toEqual([expect.objectContaining({ text: `(attachment)\n\n[attached: ${filename}]` })]);
      } else {
        expect(await screen.findByText('Message not sent. Attachments retained for retry.')).toBeVisible();
        expect(screen.getByRole('button', { name: 'remove attachment' })).toBeVisible();
        expect(useStore.getState().typingAgent).toBeNull();
        expect(useStore.getState().threadMessages.get('t1') ?? []).toEqual([]);
        expect(useStore.getState().agentConversations.get('a1')?.messages ?? []).toEqual([]);
        groupPost.mockImplementationOnce(init => {
          const retried = JSON.parse(String(init.body));
          return response({ id: 'retried-captain', thread_id: 't1', author_id: 'captain', role: 'captain',
            body: retried.body, created_at: 3, metadata: retried.metadata, per_agent_replies: [] });
        });
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /^Send$/ })); });
        await waitFor(() => expect(groupPost).toHaveBeenCalledTimes(2));
        expect(upload).toHaveBeenCalledTimes(1);
        expect(useStore.getState().agentConversations.get('a1')?.messages.filter(message => message.role === 'user'))
          .toEqual([expect.objectContaining({ text: `(attachment)\n\n[attached: ${filename}]` })]);
      }
    } finally {
      cleanup();
      useStore.setState(initialState, true);
      if (scrollBefore) Object.defineProperty(Element.prototype, 'scrollIntoView', scrollBefore);
      else Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
      localStorage.clear();
      for (const [key, value] of Object.entries(storageBefore)) localStorage.setItem(key, value);
    }
  });

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

// AD-962a: full Agent fixture (resolveFirstResponder reads callsign + isCrew).
function mkAgent(p: { id: string; callsign: string; isCrew: boolean }): Agent {
  return {
    id: p.id,
    agentType: 'crew',
    callsign: p.callsign,
    displayName: '',
    pool: 'bridge',
    state: 'active',
    confidence: 1,
    trust: 0.5,
    tier: 'domain',
    isCrew: p.isCrew,
    position: [0, 0, 0] as [number, number, number],
  };
}

// Mirror of the AD-962 / AD-962a typing-beat block (ProfileChatTab.tsx): the
// beat is set ONLY inside the >=2-crew group branch; it names the resolved
// first responder when the Captain addresses a crew participant, else the
// generic "The crew" beat. The 1:1 path (<2 crew) never reaches setTypingAgent.
type TypingPayload = { threadId: string | null; agentId: string; callsign: string; verb: string };
function mirrorBeat(opts: {
  thread: ThreadView;
  agents: Map<string, Agent>;
  text: string;
  activeThreadId: string | null;
  setTypingAgent: (p: TypingPayload) => void;
}): void {
  const { thread, agents, text, activeThreadId, setTypingAgent } = opts;
  const crewParticipantCount = (thread.participants ?? []).filter(
    (id) => id !== 'captain' && agents.get(id)?.isCrew,
  ).length;
  if (crewParticipantCount >= 2) {
    const fr = resolveFirstResponder(text, thread.participants ?? [], agents);
    setTypingAgent(
      fr
        ? { threadId: activeThreadId ?? null, agentId: fr.agentId, callsign: fr.callsign, verb: 'thinking' }
        : { threadId: activeThreadId ?? null, agentId: '', callsign: 'The crew', verb: 'thinking' },
    );
  }
}

describe('AD-962a ProfileChatTab typing-beat first-responder naming', () => {
  it('9. names the first responder when the Captain @-mentions a crew participant', () => {
    const setTypingAgent = vi.fn();
    const thread: ThreadView = { id: 't1', participants: ['captain', 'a1', 'a2'] };
    const agents = new Map<string, Agent>([
      ['a1', mkAgent({ id: 'a1', callsign: 'Ezri', isCrew: true })],
      ['a2', mkAgent({ id: 'a2', callsign: 'Yeo', isCrew: true })],
    ]);

    mirrorBeat({ thread, agents, text: '@Ezri what is the read?', activeThreadId: 't1', setTypingAgent });

    expect(setTypingAgent).toHaveBeenCalledTimes(1);
    expect(setTypingAgent).toHaveBeenCalledWith({
      threadId: 't1', agentId: 'a1', callsign: 'Ezri', verb: 'thinking',
    });
  });

  it('10. falls back to the generic crew beat with no mention, and never sets the beat on a 1:1', () => {
    const setTypingAgent = vi.fn();
    const thread: ThreadView = { id: 't1', participants: ['captain', 'a1', 'a2'] };
    const agents = new Map<string, Agent>([
      ['a1', mkAgent({ id: 'a1', callsign: 'Ezri', isCrew: true })],
      ['a2', mkAgent({ id: 'a2', callsign: 'Yeo', isCrew: true })],
    ]);

    mirrorBeat({ thread, agents, text: 'status?', activeThreadId: 't1', setTypingAgent });

    expect(setTypingAgent).toHaveBeenCalledTimes(1);
    expect(setTypingAgent).toHaveBeenCalledWith({
      threadId: 't1', agentId: '', callsign: 'The crew', verb: 'thinking',
    });

    // A 1:1 thread (<2 crew) never sets the beat, even with a leading mention.
    const setTypingAgent1on1 = vi.fn();
    const solo: ThreadView = { id: 't2', participants: ['captain', 'a1'] };
    mirrorBeat({ thread: solo, agents, text: '@Ezri hi', activeThreadId: 't2', setTypingAgent: setTypingAgent1on1 });
    expect(setTypingAgent1on1).not.toHaveBeenCalled();
  });
});
