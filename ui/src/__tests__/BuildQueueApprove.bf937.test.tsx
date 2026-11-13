/** BF-937 (#1678): approving a build in review says what it is: not merged, and where its candidate branch is kept.
 *
 * The vessel's answer is `ui/e2e/fixtures/bf937-queue-approve-unavailable.json`, the file the backend test compares the
 * real route's answer with. The cases the unfixed tree fails are `built`, which is `it.fails` until BF-937 S1 M2 sets it to
 * `it`; with BF937_RUNXFAIL=1 they run as ordinary cases, so each can be seen to stop at its own assertion. No BF-937 name
 * is imported at the top: the helper is imported inside its own cases, by a variable path, so that this file type-checks
 * and loads before the helper exists. `globalThis.fetch` is replaced per case and restored.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { IntentSurface } from '../components/IntentSurface';
import { FullKanban } from '../components/bridge/FullKanban';
import { useStore } from '../store/useStore';
import type { BuildQueueItem, MissionControlTask, WSEvent } from '../store/types';
import unavailable from '../../e2e/fixtures/bf937-queue-approve-unavailable.json';

const built = process.env.BF937_RUNXFAIL === '1' ? it : it.fails;
const APPROVE = '/api/build/queue/approve';
const HELPER = '../store/buildQueueApprove';
const realFetch = globalThis.fetch;

type Call = { url: string; body: unknown };

/** Every request is recorded; the approve route answers `body`, everything else answers `{}`. */
function answerWith(body: unknown): Call[] {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn().mockImplementation((url: unknown, init?: { body?: string }) => {
    calls.push({ url: String(url), body: init?.body ? JSON.parse(init.body) : null });
    return Promise.resolve({ ok: true, json: () => Promise.resolve(String(url) === APPROVE ? body : {}) });
  }) as unknown as typeof fetch;
  return calls;
}

/** The approve route is unreachable (the request fails); everything else answers `{}`. */
function noAnswer(): Call[] {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn().mockImplementation((url: unknown, init?: { body?: string }) => {
    calls.push({ url: String(url), body: init?.body ? JSON.parse(init.body) : null });
    return String(url) === APPROVE
      ? Promise.reject(new TypeError('network down'))
      : Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  }) as unknown as typeof fetch;
  return calls;
}

async function flush(): Promise<void> {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  globalThis.fetch = realFetch;
});

function reviewTask(): MissionControlTask {
  return {
    id: unavailable.build_id, type: 'build', title: 'Candidate build', department: 'engineering', status: 'review',
    agent_type: 'builder', agent_id: '', started_at: 0, completed_at: 0, priority: 5, ad_number: 0, error: '',
    metadata: {},
  };
}

function queueItem(status: BuildQueueItem['status']): BuildQueueItem {
  return {
    id: unavailable.build_id, title: 'Candidate build', ad_number: 0, status, priority: 5,
    worktree_path: unavailable.worktree_path, builder_id: '', error: '', file_footprint: [],
    commit_hash: unavailable.commit,
  };
}

describe('BF-937: the Mission Control card', () => {
  beforeEach(() => {
    useStore.setState({ missionControlTasks: [reviewTask()] });
  });
  afterEach(() => {
    useStore.setState({ missionControlTasks: null });
  });

  it('posts the build id to the approve route, as before', async () => {
    const calls = answerWith(unavailable);
    render(<FullKanban />);
    fireEvent.click(screen.getByText('Approve'));
    await flush();
    expect(calls).toEqual([{ url: APPROVE, body: { build_id: unavailable.build_id } }]);
  });

  it('rejects as before', async () => {
    const calls = answerWith({ status: 'ok', message: 'Build rejected' });
    render(<FullKanban />);
    fireEvent.click(screen.getByText('Reject'));
    await flush();
    expect(calls).toEqual([{ url: '/api/build/queue/reject', body: { build_id: unavailable.build_id } }]);
  });

  built('shows the answer the vessel gave, under the card', async () => {
    answerWith(unavailable);
    render(<FullKanban />);
    fireEvent.click(screen.getByText('Approve'));
    expect(await screen.findByRole('status')).toHaveTextContent(unavailable.message);
  });

  built('says so when the vessel gives no answer', async () => {
    noAnswer();
    render(<FullKanban />);
    fireEvent.click(screen.getByText('Approve'));
    expect(await screen.findByRole('status')).toHaveTextContent(/no answer from the vessel/i);
  });
});

function openShell() {
  const pillText = screen.queryByText(/Ask ProbOS/);
  if (pillText) {
    const clickable = pillText.closest('div');
    if (clickable) fireEvent.click(clickable);
  }
}

describe('BF-937: the Build Queue panel', () => {
  beforeEach(() => {
    useStore.setState({
      chatHistory: [], activeDag: [], pendingRequests: 0, agents: new Map(), buildQueue: [queueItem('reviewing')],
    });
  });
  afterEach(() => {
    useStore.setState({ buildQueue: null, chatHistory: [] });
  });

  function openTheShell(): void {
    render(<IntentSurface />);
    openShell();
  }

  it('posts the build id to the approve route, as before', async () => {
    const calls = answerWith(unavailable);
    openTheShell();
    fireEvent.click(await screen.findByText('Approve'));
    await flush();
    expect(calls.filter((call) => call.url === APPROVE)).toEqual([{ url: APPROVE, body: { build_id: unavailable.build_id } }]);
  });

  built('adds the answer the vessel gave to the chat', async () => {
    answerWith(unavailable);
    openTheShell();
    fireEvent.click(await screen.findByText('Approve'));
    expect(await screen.findByText(unavailable.message)).toBeInTheDocument();
  });

  built('says so in the chat when the vessel gives no answer', async () => {
    noAnswer();
    openTheShell();
    fireEvent.click(await screen.findByText('Approve'));
    expect(await screen.findByText(/no answer from the vessel/i)).toBeInTheDocument();
  });
});

const GENERATION = 'b'.repeat(32);
let nextSequence = 0;

function frame(type: string, data: Record<string, unknown>): WSEvent {
  return { type, data, timestamp: Date.now() / 1000, stream: { generation: GENERATION, sequence: nextSequence++ } };
}

function lastChatText(): string {
  const history = useStore.getState().chatHistory;
  return history.length > 0 ? history[history.length - 1].text : '';
}

describe('BF-937: the announcement of a build in the queue', () => {
  beforeEach(() => {
    nextSequence = 0;
    useStore.setState({ chatHistory: [], liveGeneration: null, liveSequence: 0, liveRepairEpoch: 0, buildQueue: null });
    useStore.getState().handleEvent(frame('state_snapshot', {
      agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0,
    }));
  });

  it('announces a build that starts building as before', () => {
    useStore.getState().handleEvent(frame('build_queue_item', { item: queueItem('building') }));
    expect(lastChatText()).toBe('Builder started: Candidate build');
  });

  built('announces a build that reaches review as a candidate that is not merged, with its place', () => {
    useStore.getState().handleEvent(frame('build_queue_item', { item: queueItem('reviewing') }));
    const text = lastChatText();
    expect(text).toContain('Build ready for review: Candidate build');
    expect(text).toContain(`Candidate branch kept in ${unavailable.worktree_path}`);
    expect(text).toMatch(/not merged/i);
    expect(text).toContain('AD-1336');
  });
});

describe('BF-937: the helper', () => {
  built('returns the vessel message, or a fixed line when it sent none', async () => {
    const { queueApproveMessage } = await import(/* @vite-ignore */ HELPER);
    expect(queueApproveMessage(unavailable)).toBe(unavailable.message);
    expect(queueApproveMessage({ status: 'error', message: 'Build x not in reviewing status' })).toBe(
      'Build x not in reviewing status',
    );
    for (const body of [null, undefined, 'text', 7, {}, { message: '' }, { message: '   ' }, { message: 3 }]) {
      expect(queueApproveMessage(body)).toBe('Approve request failed: no answer from the vessel. Nothing was merged.');
    }
  });

  built('never rejects: a network failure and an unreadable body read as no answer', async () => {
    const { approveQueuedBuild } = await import(/* @vite-ignore */ HELPER);
    noAnswer();
    await expect(approveQueuedBuild('x')).resolves.toMatch(/no answer from the vessel/);
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: false, json: () => Promise.reject(new SyntaxError('not json')) }) as unknown as typeof fetch;
    await expect(approveQueuedBuild('x')).resolves.toMatch(/no answer from the vessel/);
  });
});
