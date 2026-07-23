import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const audio = vi.hoisted(() => ({
  speakResponse: vi.fn(),
  startListening: vi.fn(),
  stopListening: vi.fn(),
}));

vi.mock('../../../audio/voice', () => ({
  getServerPiperVoices: vi.fn(async () => null),
  speakResponse: audio.speakResponse,
  stripMarkdownForSpeech: (text: string) => text,
  onSpeechEvent: vi.fn(() => () => {}),
  prewarmTts: vi.fn(),
}));

vi.mock('../../../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => true,
  startListening: audio.startListening,
  stopListening: audio.stopListening,
}));

vi.mock('../MeetingView', () => ({
  MeetingView: () => <div data-testid="meeting-view-stub" />,
}));

import { ProfileChatTab } from '../ProfileChatTab';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type {
  Agent,
  CrewSessionDetailProjection,
  CrewSessionState,
  StartWorkResult,
} from '../../../store/types';

const SHA_A = 'a'.repeat(64);
const SHA_B = 'b'.repeat(64);

function agent(id: string): Agent {
  return {
    id,
    agentType: 'crew',
    callsign: id,
    displayName: id,
    pool: 'bridge',
    state: 'active',
    confidence: 1,
    trust: 0.5,
    tier: 'domain',
    isCrew: true,
    position: [0, 0, 0],
  };
}

function thread(id: string, taskId: string | null): AD791aChatThreadView {
  return {
    id,
    title: id,
    participants: ['host', 'peer'],
    task_id: taskId,
    created_at: 1,
    last_active_at: 1,
    metadata: {},
  };
}

function projection(
  parentId: string,
  threadId: string,
  state: CrewSessionState,
): CrewSessionDetailProjection {
  const done = state === 'done';
  const blocked = state === 'blocked_needs_captain';
  return {
    task_id: parentId,
    thread_id: threadId,
    goal: `Goal for ${threadId}`,
    origin: 'captain',
    originator_id: 'captain',
    facilitator_id: 'host',
    owner_ids: ['host', 'peer'],
    state,
    revision: 1,
    success_criteria: ['Complete', 'Verified'],
    expected_deliverable: 'A report',
    timestamps: {
      created_at: 1,
      transitioned_at: 3,
      started_at: done ? 2 : null,
      first_result_at: done ? 2.5 : null,
      verified_at: done ? 3 : null,
      completed_at: done ? 3 : null,
    },
    progress: { total: 1, done: done ? 1 : 0, failed: 0, active: done ? 0 : 1, active_child: done ? null : { id: 'child', title: 'Active child', status: 'in_progress', owner_id: 'peer' } },
    last_result_summary: done ? 'Verified' : '',
    blocker: blocked ? { reason: 'Captain approval required', since: 3, duration_seconds: 60, action: 'retry_start_work' } : null,
    result: done ? { artifact_id: 'artifact-1', content_hash: SHA_B, result_ref: SHA_A, evidence_refs: [SHA_A] } : null,
    verification: done ? { verifier_agent_id: 'peer', confidence: 0.9, critique: 'Accepted', accepted_count: 1, total_count: 1, convergence_rounds: 1 } : null,
    duplicate_resume_count: 0,
  };
}

function json(body: unknown, status = 200): Response {
  const serialized = JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => serialized,
    headers: new Headers({ 'content-type': 'text/markdown' }),
    blob: async () => new Blob(['artifact body'], { type: 'text/markdown' }),
  } as Response;
}

type NetworkOptions = {
  details: Record<string, CrewSessionDetailProjection>;
  startResult?: StartWorkResult;
  messagesByThread?: Record<string, Array<{
    id: string;
    thread_id: string;
    author_id: string;
    role: string;
    body: string;
    created_at: number;
    metadata: Record<string, unknown>;
  }>>;
};

function installNetwork(options: NetworkOptions): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    if (url === '/api/voice/health') {
      return Promise.resolve(json({ primary_stt: 'browser', engine: 'browser', backend_available: true, healthy: true }));
    }
    if (url.endsWith('/chat/history')) return Promise.resolve(json({ memories: [] }));
    if (url.endsWith('/profile')) return Promise.resolve(json({ voiceProfile: null }));
    const messageMatch = url.match(/^\/api\/threads\/([^/]+)\/messages\?limit=200$/);
    if (messageMatch) {
      return Promise.resolve(json({
        thread_id: decodeURIComponent(messageMatch[1]),
        messages: options.messagesByThread?.[decodeURIComponent(messageMatch[1])] ?? [],
      }));
    }
    if (/\/api\/threads\/[^/]+\/inputs$/.test(url)) {
      return Promise.resolve(json({ inputs: [] }));
    }
    const artifactMatch = url.match(/^\/api\/artifacts\/thread\/([^?]+)\?limit=1001$/);
    if (artifactMatch) {
      return Promise.resolve(json({
        thread_id: decodeURIComponent(artifactMatch[1]), artifacts: [],
      }));
    }
    if (/\/api\/work-items\/[^/]+\/steps\?limit=1001$/.test(url)) {
      return Promise.resolve(json({ steps: [], gate_completion: false }));
    }
    const detailMatch = url.match(/^\/api\/crew-tasks\/(.+)$/);
    if (detailMatch) {
      const parentId = decodeURIComponent(detailMatch[1]);
      const detail = options.details[parentId];
      return Promise.resolve(detail ? json({ session: detail }) : json({}, 404));
    }
    if (url === '/api/artifacts/artifact-1') {
      return Promise.resolve(json({
        id: 'artifact-1', thread_id: 't1', name: 'report.md', version: 1,
        content_hash: SHA_B, mime: 'text/markdown', size_bytes: 100,
        created_by: 'peer', created_at: 3, supersedes: null,
      }));
    }
    if (url === '/api/artifacts/artifact-1/content') {
      return Promise.resolve(json({}));
    }
    if (method === 'POST' && /\/api\/threads\/[^/]+\/start-work$/.test(url)) {
      return Promise.resolve(options.startResult ? json(options.startResult) : json({}, 500));
    }
    return Promise.resolve(json({}));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function seed(threadRows: AD791aChatThreadView[]): void {
  useStore.setState({
    activeProfileAgent: null,
    activeProfileThreadId: null,
    activeThreadId: null,
    agents: new Map([['host', agent('host')], ['peer', agent('peer')]]),
    agentConversations: new Map(),
    threadIdByAgent: new Map(),
    chatThreads: new Map(threadRows.map(row => [row.id, row])),
    threadMessages: new Map(),
    crewSessionsByParent: new Map(),
    crewSessionSummariesByThread: new Map(),
    artifactsByThread: new Map(),
    selectedArtifactId: null,
    voiceEnabled: false,
    meetingChatVisible: true,
    callAudioEnabled: true,
    typingAgent: null,
    chatDrafts: {},
    liveGeneration: null,
    liveSequence: 0,
    liveRepairEpoch: 0,
    liveThreadRefresh: null,
  });
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('probos.workspaceFiles.collapsed', '0');
  if (!(Element.prototype as unknown as { scrollIntoView?: unknown }).scrollIntoView) {
    (Element.prototype as unknown as { scrollIntoView: () => void }).scrollIntoView = vi.fn();
  }
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  localStorage.clear();
  seed([]);
});

describe('AD-1132 ProfileChatTab CrewSession integration', () => {
  it('repairs an active transcript only after the triggering message is authoritative', async () => {
    const room = thread('t1', null);
    const options: NetworkOptions = { details: {}, messagesByThread: { t1: [] } };
    seed([room]);
    useStore.getState().openGroupChatThread('host', 't1');
    installNetwork(options);
    render(<ProfileChatTab agentId="host" threadId="t1" />);
    await waitFor(() => expect(useStore.getState().threadMessages.get('t1')).toEqual([]));
    act(() => {
      useStore.getState().handleEvent({
        type: 'state_snapshot',
        data: { agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0 },
        timestamp: 1,
        stream: { generation: 'a'.repeat(32), sequence: 0 },
      });
    });
    options.messagesByThread!.t1 = [{
      id: 'message-1', thread_id: 't1', author_id: 'peer', role: 'agent',
      body: 'Live result arrived.', created_at: 5, metadata: {},
    }];
    act(() => {
      useStore.getState().handleEvent({
        type: 'chat_thread_message_appended',
        data: { thread_id: 't1', message_id: 'message-1', author_id: 'peer', role: 'agent', created_at: 5 },
        timestamp: 5,
        stream: { generation: 'a'.repeat(32), sequence: 1 },
      });
    });
    expect(await screen.findByText('Live result arrived.')).toBeTruthy();
    expect(useStore.getState().threadMessages.get('t1')).toHaveLength(1);
    act(() => {
      useStore.getState().handleEvent({
        type: 'chat_thread_message_appended',
        data: { thread_id: 't1', message_id: 'message-1', author_id: 'peer', role: 'agent', created_at: 5 },
        timestamp: 5,
        stream: { generation: 'a'.repeat(32), sequence: 1 },
      });
    });
    expect(useStore.getState().threadMessages.get('t1')).toHaveLength(1);
  });

  it('loads a newly owned room while the prior transcript request is pending', async () => {
    const first = thread('t1', null);
    const second = thread('t2', null);
    seed([first, second]);
    useStore.getState().openGroupChatThread('host', 't1');
    let resolveFirst: ((value: Response) => void) | undefined;
    const baseFetch = installNetwork({ details: {}, messagesByThread: {} });
    const fallbackFetch = baseFetch as unknown as (
      input: RequestInfo | URL,
      init?: RequestInit,
    ) => Promise<Response>;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/threads/t1/messages?limit=200') {
        return new Promise<Response>((resolve) => { resolveFirst = resolve; });
      }
      if (url === '/api/threads/t2/messages?limit=200') {
        return Promise.resolve(json({
          thread_id: 't2',
          messages: [{
            id: 'message-2', thread_id: 't2', author_id: 'peer', role: 'agent',
            body: 'Second room is current.', created_at: 2, metadata: {},
          }],
        }));
      }
      return fallbackFetch(input, init);
    });
    vi.stubGlobal('fetch', fetchMock);
    const view = render(<ProfileChatTab agentId="host" threadId="t1" />);
    await waitFor(() => expect(resolveFirst).toBeTypeOf('function'));

    act(() => useStore.getState().openGroupChatThread('host', 't2'));
    view.rerender(<ProfileChatTab agentId="host" threadId="t2" />);
    expect(await screen.findByText('Second room is current.')).toBeTruthy();

    await act(async () => {
      resolveFirst?.(json({
        thread_id: 't1',
        messages: [{
          id: 'message-1', thread_id: 't1', author_id: 'peer', role: 'agent',
          body: 'First room is stale.', created_at: 1, metadata: {},
        }],
      }));
    });
    expect(screen.queryByText('First room is stale.')).toBeNull();
    expect(useStore.getState().threadMessages.get('t2')).toHaveLength(1);
  });

  it('mounts the panel in the chat column and forwards owned retry with zero passive writes', async () => {
    const room = thread('t1', 'p1');
    const blocked = projection('p1', 't1', 'blocked_needs_captain');
    seed([room]);
    const fetchMock = installNetwork({ details: { p1: blocked } });

    render(<ProfileChatTab agentId="host" threadId="t1" />);

    const panel = await screen.findByTestId('crew-collaboration-panel');
    const rail = await screen.findByTestId('workspace-files-rail');
    const chatColumn = panel.parentElement?.parentElement;
    expect(chatColumn?.parentElement).toBe(rail.parentElement);
    expect(chatColumn?.style.flex).toContain('1');
    expect(chatColumn?.style.minWidth).toBe('0px');
    expect(chatColumn?.style.minHeight).toBe('0px');
    expect(chatColumn?.parentElement?.style.flexDirection).toBe('row');
    expect(fetchMock.mock.calls.filter(([, init]) => ['POST', 'PATCH', 'DELETE'].includes(String(init?.method ?? 'GET')))).toEqual([]);

    fireEvent.click(screen.getByRole('button', { name: 'Retry blocked CrewSession work' }));
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeTruthy();
    expect(screen.getByTestId('workspace-start-work-goal')).toHaveValue(blocked.goal);
    expect(screen.getByTestId('workspace-start-work-criteria')).toHaveValue(blocked.success_criteria.join('\n'));
    expect(screen.getByTestId('workspace-start-work-deliverable')).toHaveValue(blocked.expected_deliverable);
    expect(screen.getByTestId('workspace-start-work-retry')).toBeChecked();
    await waitFor(() => expect(screen.getByTestId('workspace-start-work-goal')).toHaveFocus());
    expect(fetchMock.mock.calls.filter(([, init]) => ['POST', 'PATCH', 'DELETE'].includes(String(init?.method ?? 'GET')))).toEqual([]);
  });

  it('focuses the owned session band after a successful blocked retry removes its trigger', async () => {
    const room = thread('t1', 'p1');
    const blocked = projection('p1', 't1', 'blocked_needs_captain');
    const resumed = {
      ...projection('p1', 't1', 'executing'),
      goal: blocked.goal,
      success_criteria: blocked.success_criteria,
      expected_deliverable: blocked.expected_deliverable,
    };
    const result: StartWorkResult = {
      disposition: 'resumed', parent_id: 'p1', thread_id: 't1', state: 'executing',
      facilitator_id: 'host', owner_ids: ['host', 'peer'], duplicate_resume_count: 0,
      scheduled: true, session: resumed,
    };
    seed([room]);
    installNetwork({ details: { p1: blocked }, startResult: result });
    render(<ProfileChatTab agentId="host" threadId="t1" />);

    const blockedTrigger = await screen.findByRole('button', { name: 'Retry blocked CrewSession work' });
    blockedTrigger.focus();
    fireEvent.click(blockedTrigger);
    await waitFor(() => expect(screen.getByTestId('workspace-start-work-goal')).toHaveFocus());
    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));

    const sessionBand = await screen.findByTestId('crew-collaboration-panel');
    await waitFor(() => expect(sessionBand).toHaveFocus());
    expect(sessionBand.getAttribute('data-state')).toBe('executing');
    expect(screen.queryByRole('button', { name: 'Retry blocked CrewSession work' })).toBeNull();
  });

  it('binds a taskless room from one Start Work response and renders the hydrated session immediately', async () => {
    const room = thread('t2', null);
    const created = projection('p2', 't2', 'discussing');
    const result: StartWorkResult = {
      disposition: 'created', parent_id: 'p2', thread_id: 't2', state: 'discussing',
      facilitator_id: 'host', owner_ids: ['host', 'peer'], duplicate_resume_count: 0,
      scheduled: true, session: created,
    };
    seed([room]);
    const fetchMock = installNetwork({ details: { p2: created }, startResult: result });
    render(<ProfileChatTab agentId="host" threadId="t2" />);
    await screen.findByTestId('workspace-files-rail');
    expect(screen.queryByTestId('crew-collaboration-panel')).toBeNull();

    fireEvent.click(screen.getByTestId('workspace-start-work-open'));
    fireEvent.change(screen.getByTestId('workspace-start-work-goal'), { target: { value: created.goal } });
    fireEvent.change(screen.getByTestId('workspace-start-work-criteria'), { target: { value: created.success_criteria.join('\n') } });
    fireEvent.change(screen.getByTestId('workspace-start-work-deliverable'), { target: { value: created.expected_deliverable } });
    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));

    expect(await screen.findByText(created.goal)).toBeTruthy();
    expect(useStore.getState().crewSessionsByParent.get('p2')).toEqual(created);
    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST');
    expect(posts).toHaveLength(1);
    expect(String(posts[0][0])).toBe('/api/threads/t2/start-work');
  });

  it('drops a taskless binding resolved in the same act as a room switch', async () => {
    const roomOne = thread('t1', null);
    const roomTwo = thread('t2', null);
    const stale = projection('stale-parent', 't1', 'discussing');
    const staleResult: StartWorkResult = {
      disposition: 'created', parent_id: 'stale-parent', thread_id: 't1', state: 'discussing',
      facilitator_id: 'host', owner_ids: ['host', 'peer'], duplicate_resume_count: 0,
      scheduled: true, session: stale,
    };
    let resolveStart: ((value: Response) => void) | undefined;
    seed([roomOne, roomTwo]);
    const fetchMock = installNetwork({ details: {} });
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'POST' && url === '/api/threads/t1/start-work') {
        return new Promise<Response>(resolve => { resolveStart = resolve; });
      }
      if (url === '/api/voice/health') {
        return Promise.resolve(json({ primary_stt: 'browser', engine: 'browser', backend_available: true, healthy: true }));
      }
      if (url.endsWith('/chat/history')) return Promise.resolve(json({ memories: [] }));
      if (url.endsWith('/profile')) return Promise.resolve(json({ voiceProfile: null }));
      if (/\/api\/threads\/[^/]+\/messages\?limit=200$/.test(url)) return Promise.resolve(json({ messages: [] }));
      if (/\/api\/threads\/[^/]+\/inputs$/.test(url)) return Promise.resolve(json({ inputs: [] }));
      if (/\/api\/artifacts\/thread\//.test(url)) return Promise.resolve(json({ artifacts: [] }));
      return Promise.resolve(json({}));
    });
    const view = render(<ProfileChatTab agentId="host" threadId="t1" />);
    await screen.findByTestId('workspace-files-rail');
    fireEvent.click(screen.getByTestId('workspace-start-work-open'));
    fireEvent.change(screen.getByTestId('workspace-start-work-goal'), { target: { value: stale.goal } });
    fireEvent.change(screen.getByTestId('workspace-start-work-criteria'), { target: { value: stale.success_criteria.join('\n') } });
    fireEvent.change(screen.getByTestId('workspace-start-work-deliverable'), { target: { value: stale.expected_deliverable } });
    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    await waitFor(() => expect(resolveStart).toBeTypeOf('function'));

    await act(async () => {
      resolveStart?.(json(staleResult));
      view.rerender(<ProfileChatTab agentId="host" threadId="t2" />);
    });

    expect(useStore.getState().crewSessionsByParent.has('stale-parent')).toBe(false);
    expect(screen.queryByText(stale.goal)).toBeNull();
    expect(screen.queryByTestId('crew-collaboration-panel')).toBeNull();
  });

  it('forwards an owned result command to metadata GET and the existing rail viewer', async () => {
    const room = thread('t1', 'p1');
    const done = projection('p1', 't1', 'done');
    seed([room]);
    const fetchMock = installNetwork({ details: { p1: done } });
    render(<ProfileChatTab agentId="host" threadId="t1" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Open CrewSession result artifact' }));

    expect(await screen.findByTestId('workspace-files-preview')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/artifacts/artifact-1')).toBe(true);
    expect(fetchMock.mock.calls.filter(([, init]) => ['POST', 'PATCH', 'DELETE'].includes(String(init?.method ?? 'GET')))).toEqual([]);
  });
});