/**
 * AD-929: tests for the WorkspaceFilesRail.
 *
 * The rail is self-fetching, so the inputs/artifact api modules are
 * partially mocked (``importOriginal`` keeps ``attachmentUrl`` real so the
 * composed ``InputsList`` rows still render). Covers the Inputs/Outputs
 * sections, the self-fetch calls, the in-app preview Outputs action, the
 * collapse persistence, the default-collapsed-on-first-run behaviour, and
 * the HXI no-emoji guard. localStorage is cleared between tests.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { TaskInput } from '../../inputs/inputsApi';
import { useStore, type ArtifactView } from '../../../store/useStore';
import type {
  CrewSessionArtifactCommand,
  CrewSessionDetailProjection,
  CrewSessionRetryCommand,
  CrewSessionState,
  StartWorkResult,
} from '../../../store/types';

vi.mock('../../inputs/inputsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../inputs/inputsApi')>();
  return { ...actual, fetchThreadInputs: vi.fn() };
});
vi.mock('../../artifacts/artifactApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../artifacts/artifactApi')>();
  return { ...actual, fetchThreadArtifacts: vi.fn(), fetchArtifactMetadata: vi.fn() };
});
vi.mock('../todosApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../todosApi')>();
  return { ...actual, fetchTaskSteps: vi.fn(), updateTaskStep: vi.fn() };
});

import { fetchThreadInputs } from '../../inputs/inputsApi';
import { fetchArtifactMetadata, fetchThreadArtifacts } from '../../artifacts/artifactApi';
import * as todosApi from '../todosApi';
import { fetchTaskSteps, updateTaskStep } from '../todosApi';
import { WorkspaceFilesRail } from '../WorkspaceFilesRail';
import railSource from '../WorkspaceFilesRail.tsx?raw';

const EMOJI_RE = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F600}-\u{1F64F}]/u;
const SHA_A = 'a'.repeat(64);
const SHA_B = 'b'.repeat(64);

const INPUTS: TaskInput[] = [
  {
    content_hash: 'in1',
    mime: 'text/plain',
    filename: 'notes.txt',
    size: 10,
    source: 'task',
    available: true,
  },
];

const ARTIFACTS: ArtifactView[] = [
  {
    id: 'art1',
    thread_id: 't1',
    name: 'report.md',
    version: 1,
    content_hash: 'h1',
    mime: 'text/markdown',
    size_bytes: 100,
    created_by: 'a1',
    created_at: 0,
    supersedes: null,
    _pinned_from_project: false,
  },
];

function sessionProjection(
  parentId: string,
  threadId: string,
  state: CrewSessionState = 'discussing',
): CrewSessionDetailProjection {
  const blocked = state === 'blocked_needs_captain';
  return {
    task_id: parentId,
    thread_id: threadId,
    goal: 'Prepare the readiness report',
    origin: 'captain',
    originator_id: 'captain',
    facilitator_id: 'facilitator-1',
    owner_ids: ['facilitator-1', 'owner-2'],
    state,
    revision: 1,
    success_criteria: ['Report is complete', 'Evidence is attached'],
    expected_deliverable: 'A verified readiness report',
    timestamps: {
      created_at: 1,
      transitioned_at: 2,
      started_at: state === 'executing' ? 2 : null,
      first_result_at: null,
      verified_at: null,
      completed_at: null,
    },
    progress: {
      total: 1, done: 0, failed: 0, active: 1,
      active_child: { id: 'child-1', title: 'Prepare evidence', status: 'in_progress', owner_id: 'owner-2' },
    },
    last_result_summary: '',
    blocker: blocked ? { reason: 'crew_worker_unavailable', since: 2, duration_seconds: 60, action: 'retry_start_work' } : null,
    result: null,
    verification: null,
    duplicate_resume_count: 0,
  };
}

function startWorkResult(
  parentId: string,
  threadId: string,
  state: CrewSessionState = 'discussing',
  disposition: StartWorkResult['disposition'] = 'created',
): StartWorkResult {
  const session = sessionProjection(parentId, threadId, state);
  return {
    disposition,
    parent_id: parentId,
    thread_id: threadId,
    state,
    facilitator_id: session.facilitator_id,
    owner_ids: session.owner_ids,
    duplicate_resume_count: session.duplicate_resume_count,
    scheduled: true,
    session,
  };
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(fetchThreadInputs).mockResolvedValue(INPUTS);
  vi.mocked(fetchThreadArtifacts).mockResolvedValue(ARTIFACTS);
  vi.mocked(fetchArtifactMetadata).mockResolvedValue(null);
  vi.mocked(fetchTaskSteps).mockResolvedValue([]);
  vi.mocked(updateTaskStep).mockResolvedValue();
  vi.stubGlobal('fetch', vi.fn());
  useStore.setState({
    crewSessionsByParent: new Map(),
    crewSessionSummariesByThread: new Map(),
    liveArtifactRefresh: null,
    liveTodoRefresh: null,
    liveRepairEpoch: 0,
    liveThreadRefresh: null,
    liveGeneration: null,
    threadMessages: new Map(),
    liveRailOwner: null,
  });
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  useStore.setState({
    crewSessionsByParent: new Map(),
    crewSessionSummariesByThread: new Map(),
    liveArtifactRefresh: null,
    liveTodoRefresh: null,
    liveRepairEpoch: 0,
    liveThreadRefresh: null,
    liveGeneration: null,
    threadMessages: new Map(),
    liveRailOwner: null,
  });
});

function openStartWorkDialog(): void {
  fireEvent.click(screen.getByTestId('workspace-start-work-open'));
}

function fillValidStartWorkForm(): void {
  fireEvent.change(screen.getByTestId('workspace-start-work-goal'), {
    target: { value: 'Prepare the readiness report' },
  });
  fireEvent.change(screen.getByTestId('workspace-start-work-criteria'), {
    target: { value: 'Report is complete\nEvidence is attached' },
  });
  fireEvent.change(screen.getByTestId('workspace-start-work-deliverable'), {
    target: { value: 'A verified readiness report' },
  });
}

describe('WorkspaceFilesRail (AD-929)', () => {
  it('performs one initial Inputs request per expanded room', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    const view = render(<WorkspaceFilesRail threadId="t1" />);
    await screen.findByText('notes.txt');
    expect(fetchThreadInputs).toHaveBeenCalledTimes(1);
    vi.mocked(fetchThreadInputs).mockClear();
    view.rerender(<WorkspaceFilesRail threadId="t2" />);
    await screen.findByText('notes.txt');
    expect(fetchThreadInputs).toHaveBeenCalledTimes(1);
    expect(fetchThreadInputs).toHaveBeenCalledWith('t2');
  });

  it('distinguishes initial input failure from a successfully empty room and recovers', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    vi.mocked(fetchThreadInputs).mockRejectedValue(new Error('503'));
    render(<WorkspaceFilesRail threadId="t1" />);
    expect(screen.queryByTestId('inputs-list-empty')).toBeNull();
    expect(await screen.findByRole('alert')).toHaveTextContent('Inputs unavailable.');
    expect(screen.queryByTestId('inputs-list-empty')).toBeNull();
    vi.mocked(fetchThreadInputs).mockResolvedValue([]);
    fireEvent.click(screen.getByTestId('workspace-files-refresh'));
    expect(await screen.findByTestId('inputs-list-empty')).toHaveTextContent('No inputs yet.');
  });

  it('retains known refs without download access after failure and restores Ready on recovery', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    await waitFor(() => expect(screen.getByTestId('input-row-in1')).toHaveTextContent('Ready'));
    vi.mocked(fetchThreadInputs).mockRejectedValue(new Error('503'));
    fireEvent.click(screen.getByTestId('workspace-files-refresh'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Showing last known inputs');
    expect(screen.getByTestId('input-row-in1')).toHaveTextContent('notes.txt');
    expect(screen.getByTestId('input-row-in1')).not.toHaveAttribute('href');
    vi.mocked(fetchThreadInputs).mockResolvedValue(INPUTS);
    act(() => useStore.setState({ liveRepairEpoch: 1 }));
    await waitFor(() => expect(screen.getByTestId('input-row-in1')).toHaveTextContent('Ready'));
  });

  it('coalesces persisted attachment refreshes and ignores text-only and optimistic changes', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    await waitFor(() => expect(screen.getByTestId('input-row-in1')).toHaveTextContent('Ready'));
    vi.mocked(fetchThreadInputs).mockClear();
    const message = {
      id: 'upload-1', threadId: 't1', role: 'user' as const, text: 'attached', timestamp: 1,
      metadata: { attachments: [{ content_hash: SHA_A, mime: 'text/csv' }] },
    };
    act(() => useStore.setState({ threadMessages: new Map([['t1', [{ ...message, optimistic: true }]]]) }));
    expect(fetchThreadInputs).not.toHaveBeenCalled();
    let resolveOld!: (rows: TaskInput[]) => void;
    vi.mocked(fetchThreadInputs).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    act(() => useStore.setState({ threadMessages: new Map([['t1', [message]]]) }));
    expect(fetchThreadInputs).toHaveBeenCalledTimes(1);
    expect(resolveOld).toBeTypeOf('function');
    act(() => useStore.setState({ threadMessages: new Map([['t1', [{ ...message, text: 'new text' }]]]) }));
    expect(fetchThreadInputs).toHaveBeenCalledTimes(1);
    act(() => useStore.setState({ threadMessages: new Map([['t1', [{
      ...message, metadata: { attachments: [{ content_hash: SHA_B, mime: 'text/csv' }] },
    }]]]) }));
    act(() => useStore.setState({ liveThreadRefresh: { threadId: 't1', requestId: 'upload-1' } }));
    expect(fetchThreadInputs).toHaveBeenCalledTimes(1);
    vi.mocked(fetchThreadInputs).mockResolvedValue([{ ...INPUTS[0], content_hash: SHA_B, filename: 'latest.csv' }]);
    await act(async () => resolveOld([{ ...INPUTS[0], filename: 'obsolete.csv' }]));
    expect(fetchThreadInputs).toHaveBeenCalledTimes(2);
    expect(await screen.findByText('latest.csv')).toBeTruthy();
    expect(screen.queryByText('obsolete.csv')).toBeNull();
  });

  it('rejects late inputs across room generations including navigation back', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    let resolveOld!: (rows: TaskInput[]) => void;
    vi.mocked(fetchThreadInputs).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const view = render(<WorkspaceFilesRail threadId="t1" />);
    expect(resolveOld).toBeTypeOf('function');
    vi.mocked(fetchThreadInputs).mockResolvedValue([]);
    view.rerender(<WorkspaceFilesRail threadId="t2" />);
    expect(await screen.findByTestId('inputs-list-empty')).toBeTruthy();
    view.rerender(<WorkspaceFilesRail threadId="t1" />);
    expect(await screen.findByTestId('inputs-list-empty')).toBeTruthy();
    await act(async () => resolveOld(INPUTS));
    expect(screen.queryByText('notes.txt')).toBeNull();
    expect(screen.getByTestId('inputs-list-empty')).toBeTruthy();
  });

  it('refreshes binding and reopen while doing no input work for collapsed live signals', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    const view = render(<WorkspaceFilesRail threadId="t1" />);
    await waitFor(() => expect(screen.getByTestId('input-row-in1')).toHaveTextContent('Ready'));
    vi.mocked(fetchThreadInputs).mockClear();
    view.rerender(<WorkspaceFilesRail threadId="t1" taskId="parent-1" />);
    await waitFor(() => expect(screen.getByTestId('input-row-in1')).toHaveTextContent('Ready'));
    expect(fetchThreadInputs).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId('workspace-files-collapse'));
    vi.mocked(fetchThreadInputs).mockClear();
    act(() => useStore.setState({ liveRepairEpoch: 1, liveThreadRefresh: { threadId: 't1', requestId: 'persisted' } }));
    expect(fetchThreadInputs).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('workspace-files-expand'));
    await waitFor(() => expect(screen.getByTestId('input-row-in1')).toHaveTextContent('Ready'));
    expect(fetchThreadInputs).toHaveBeenCalledWith('t1');
  });

  it('discards old stream results and accepts a repair response', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    let resolveOld!: (rows: TaskInput[]) => void;
    vi.mocked(fetchThreadInputs).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    render(<WorkspaceFilesRail threadId="t1" />);
    expect(resolveOld).toBeTypeOf('function');
    vi.mocked(fetchThreadInputs).mockResolvedValue([]);
    act(() => useStore.setState({ liveGeneration: 'b'.repeat(32), liveRepairEpoch: 1 }));
    await act(async () => resolveOld(INPUTS));
    expect(await screen.findByTestId('inputs-list-empty')).toBeTruthy();
    expect(screen.queryByText('notes.txt')).toBeNull();
  });

  it('overlays a narrow room without shrinking the conversation and disconnects observation', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    vi.stubGlobal('innerWidth', 390);
    let onResize!: ResizeObserverCallback;
    let observed!: Element;
    const disconnect = vi.fn();
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: ResizeObserverCallback) { onResize = callback; }
      observe(target: Element) { observed = target; }
      disconnect = disconnect;
    });
    const view = render(<WorkspaceFilesRail threadId="t1" />);
    await screen.findByTestId('inputs-list');
    act(() => onResize([{ target: observed, contentRect: { width: 390 } } as ResizeObserverEntry], {} as ResizeObserver));
    const rail = screen.getByTestId('workspace-files-rail');
    expect(rail).toHaveAttribute('data-compact', 'true');
    expect(rail.style.position).toBe('absolute');
    expect(rail.style.width).toBe('100%');
    vi.stubGlobal('innerWidth', 1440);
    act(() => onResize([{ target: observed, contentRect: { width: 420 } } as ResizeObserverEntry], {} as ResizeObserver));
    expect(rail).toHaveAttribute('data-compact', 'false');
    expect(rail.style.position).toBe('relative');
    view.unmount();
    expect(disconnect).toHaveBeenCalledOnce();
  });

  it('refreshes legacy task upload results into verified Ready inputs', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" taskId="parent-1" />);
    await screen.findByText('notes.txt');
    await waitFor(() => expect(fetchThreadInputs).toHaveBeenCalled());
    vi.mocked(fetchThreadInputs).mockClear();
    const uploaded: TaskInput = { content_hash: SHA_A, filename: 'uploaded.csv', mime: 'text/csv', size: 7, source: 'task' };
    vi.mocked(fetchThreadInputs).mockResolvedValue([{ ...uploaded, available: true }]);
    const post = vi.fn().mockResolvedValue(new Response(JSON.stringify({ inputs: [uploaded] })));
    vi.stubGlobal('fetch', post);
    fireEvent.change(screen.getByTestId('workspace-files-attach-input'), { target: { files: [new File(['a,b\n1,2'], 'uploaded.csv', { type: 'text/csv' })] } });
    await waitFor(() => expect(post).toHaveBeenCalledOnce());
    await waitFor(() => expect(fetchThreadInputs).toHaveBeenCalledWith('t1'));
    expect(screen.getByTestId(`input-row-${SHA_A}`)).toHaveTextContent('Ready');
    expect(screen.getByTestId(`input-row-${SHA_A}`)).toHaveAttribute('href');
  });

  it('retains an acknowledged task upload when the first authoritative GET is stale', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" taskId="parent-1" />);
    await screen.findByText('notes.txt');
    const uploaded: TaskInput = { content_hash: SHA_A, filename: 'new.csv', mime: 'text/csv', size: 7, source: 'task' };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ inputs: [uploaded] }))));
    fireEvent.change(screen.getByTestId('workspace-files-attach-input'), { target: { files: [new File(['a,b\n1,2'], 'new.csv', { type: 'text/csv' })] } });
    expect(await screen.findByRole('alert')).toHaveTextContent('Inputs unavailable.');
    expect(screen.getByTestId(`input-row-${SHA_A}`)).toHaveTextContent('new.csv');
    expect(screen.getByTestId(`input-row-${SHA_A}`)).not.toHaveAttribute('href');
    vi.mocked(fetchThreadInputs).mockResolvedValue([{ ...uploaded, available: true }]);
    fireEvent.click(screen.getByTestId('workspace-files-refresh'));
    await waitFor(() => expect(screen.getByTestId(`input-row-${SHA_A}`)).toHaveTextContent('Ready'));
  });

  it('surfaces task upload failure without deleting existing input rows', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" taskId="parent-1" />);
    await screen.findByText('notes.txt');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('unavailable', { status: 503 })));
    fireEvent.change(screen.getByTestId('workspace-files-attach-input'), { target: { files: [new File(['a,b'], 'failed.csv', { type: 'text/csv' })] } });
    expect(await screen.findByRole('alert')).toHaveTextContent('Input upload failed.');
    expect(screen.getByText('notes.txt')).toBeInTheDocument();
  });

  it('registers only an expanded bound room and releases it on unmount', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    const view = render(<WorkspaceFilesRail threadId="t1" taskId="parent-1" />);
    await waitFor(() => expect(useStore.getState().liveRailOwner).toEqual({
      threadId: 't1', parentId: 'parent-1',
    }));
    view.unmount();
    expect(useStore.getState().liveRailOwner).toBeNull();
  });

  it('does zero GET work while collapsed and contains no BF-644 interval', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '1');
    render(<WorkspaceFilesRail threadId="t1" taskId="parent-1" />);
    await Promise.resolve();
    expect(fetchThreadInputs).not.toHaveBeenCalled();
    expect(fetchThreadArtifacts).not.toHaveBeenCalled();
    expect(fetchTaskSteps).not.toHaveBeenCalled();
    expect(railSource).not.toContain('setInterval(');
    expect(railSource).not.toContain('5000');
  });

  it('refreshes matching live artifact and Todo commands while expanded', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" taskId="parent-1" />);
    await waitFor(() => expect(fetchThreadArtifacts).toHaveBeenCalled());
    vi.mocked(fetchThreadArtifacts).mockResolvedValue([
      ...ARTIFACTS,
      { ...ARTIFACTS[0], id: 'art2', name: 'live.md' },
    ]);
    vi.mocked(fetchTaskSteps).mockResolvedValue([
      { label: 'Live Todo', status: 'submitted' },
    ]);
    act(() => useStore.setState({
      liveArtifactRefresh: { threadId: 't1', requestId: 'art2' },
      liveTodoRefresh: { parentId: 'parent-1', requestId: 2 },
    }));
    expect(await screen.findByText('live.md')).toBeTruthy();
    expect(await screen.findByText(/Live Todo/)).toBeTruthy();
  });

  it('runs one non-overlapping manual artifact/Todo refresh pair', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" taskId="parent-1" />);
    await waitFor(() => expect(fetchTaskSteps).toHaveBeenCalled());
    vi.mocked(fetchThreadArtifacts).mockClear();
    vi.mocked(fetchTaskSteps).mockClear();
    fireEvent.click(screen.getByTestId('workspace-files-refresh'));
    fireEvent.click(screen.getByTestId('workspace-files-refresh'));
    await waitFor(() => expect(fetchThreadArtifacts).toHaveBeenCalledTimes(1));
    expect(fetchTaskSteps).toHaveBeenCalledTimes(1);
  });

  it('renders the Inputs section for a workspace room (expanded)', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    expect(await screen.findByTestId('inputs-list')).toBeTruthy();
    expect(screen.getByTestId('workspace-files-inputs-label').textContent).toBe('INPUTS');
  });

  it('renders the Outputs section (artifact-list) when expanded', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    expect(await screen.findByTestId('artifact-list')).toBeTruthy();
    expect(screen.getByTestId('workspace-files-outputs-label').textContent).toBe('OUTPUTS');
  });

  it('calls fetchThreadInputs with the passed threadId', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    await waitFor(() => expect(fetchThreadInputs).toHaveBeenCalledWith('t1'));
  });

  it('calls fetchThreadArtifacts with the passed threadId', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    await waitFor(() => expect(fetchThreadArtifacts).toHaveBeenCalledWith('t1'));
  });

  it('opens an in-app preview overlay when an Outputs row is clicked (BF-642)', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    const row = await screen.findByTestId('artifact-row-art1');
    fireEvent.click(row);
    const preview = await screen.findByTestId('workspace-files-preview');
    expect(preview).toBeTruthy();
    expect(preview.textContent).toContain('report.md');
    fireEvent.click(screen.getByTestId('workspace-files-preview-close'));
    expect(screen.queryByTestId('workspace-files-preview')).toBeNull();
  });

  it('collapse toggle persists "1" to localStorage and renders data-collapsed="true"', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    const rail = await screen.findByTestId('workspace-files-rail');
    expect(rail.getAttribute('data-collapsed')).toBe('false');
    fireEvent.click(screen.getByTestId('workspace-files-collapse'));
    expect(localStorage.getItem('probos.workspaceFiles.collapsed')).toBe('1');
    expect(screen.getByTestId('workspace-files-rail').getAttribute('data-collapsed')).toBe('true');
  });

  it('mounts expanded when localStorage is "0" and collapsed by default on first run', () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    const { unmount } = render(<WorkspaceFilesRail threadId="t1" />);
    expect(screen.getByTestId('workspace-files-rail').getAttribute('data-collapsed')).toBe('false');
    unmount();
    cleanup();
    localStorage.clear();
    render(<WorkspaceFilesRail threadId="t1" />);
    expect(screen.getByTestId('workspace-files-rail').getAttribute('data-collapsed')).toBe('true');
  });

  it('renders no emoji (HXI Design Principle #3 — stroke-SVG icons only)', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    const { container } = render(<WorkspaceFilesRail threadId="t1" />);
    await screen.findByTestId('inputs-list');
    expect(container.textContent || '').not.toMatch(EMOJI_RE);
  });

  it('passive taskless and bound viewing issues no POST, PATCH, or DELETE', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    const { rerender } = render(<WorkspaceFilesRail threadId="t1" />);
    await waitFor(() => expect(fetchThreadInputs).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId('workspace-files-collapse'));
    fireEvent.click(screen.getByTestId('workspace-files-expand'));
    rerender(<WorkspaceFilesRail threadId="t1" taskId="task-1" />);
    await waitFor(() => expect(fetchTaskSteps).toHaveBeenCalledWith('task-1'));

    const mutationCalls = vi.mocked(fetch).mock.calls.filter(([, init]) =>
      ['POST', 'PATCH', 'DELETE'].includes(String(init?.method ?? 'GET')),
    );
    expect(mutationCalls).toEqual([]);
  });

  it('opening and cancelling Start Work performs no request', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    await screen.findByTestId('workspace-files-rail');

    openStartWorkDialog();
    expect(screen.getByRole('dialog')).toBeTruthy();
    fireEvent.click(screen.getByTestId('workspace-start-work-cancel'));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('opens Start Work with Goal focused', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);

    openStartWorkDialog();

    await waitFor(() => {
      expect(screen.getByTestId('workspace-start-work-goal')).toHaveFocus();
    });
  });

  it('wraps Tab forward and Shift+Tab backward across enabled dialog controls', async () => {
    const user = userEvent.setup();
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);

    await screen.findByTestId('input-row-in1');
    await screen.findByTestId('artifact-row-art1');
    await user.click(screen.getByTestId('workspace-start-work-open'));

    const goal = screen.getByTestId('workspace-start-work-goal');
    const criteria = screen.getByTestId('workspace-start-work-criteria');
    const deliverable = screen.getByTestId('workspace-start-work-deliverable');
    const retry = screen.getByTestId('workspace-start-work-retry');
    const cancel = screen.getByTestId('workspace-start-work-cancel');
    const confirm = screen.getByTestId('workspace-start-work-confirm');
    await waitFor(() => expect(goal).toHaveFocus());

    await user.type(goal, 'Prepare the readiness report');
    await user.type(criteria, 'Report is complete{Enter}Evidence is attached');
    await user.type(deliverable, 'A verified readiness report');
    await waitFor(() => expect(confirm).toBeEnabled());

    await user.click(goal);
    fireEvent.keyDown(goal, { key: 'Tab' });
    expect(criteria).toHaveFocus();
    fireEvent.keyDown(criteria, { key: 'Tab' });
    expect(deliverable).toHaveFocus();
    fireEvent.keyDown(deliverable, { key: 'Tab' });
    expect(retry).toHaveFocus();
    fireEvent.keyDown(retry, { key: 'Tab' });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(cancel, { key: 'Tab' });
    expect(confirm).toHaveFocus();

    fireEvent.keyDown(confirm, { key: 'Tab' });
    expect(goal).toHaveFocus();

    fireEvent.keyDown(goal, { key: 'Tab', shiftKey: true });
    expect(confirm).toHaveFocus();
  });

  it('non-pending Escape stops propagation, closes, and restores the opener', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    const parentKeyDown = vi.fn();
    render(
      <div onKeyDown={parentKeyDown}>
        <WorkspaceFilesRail threadId="t1" />
      </div>,
    );
    const opener = screen.getByTestId('workspace-start-work-open');
    opener.focus();
    fireEvent.click(opener);

    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(parentKeyDown).not.toHaveBeenCalled();
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('pending Escape is inert and keeps focus on the dialog container', async () => {
    const user = userEvent.setup();
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    let resolveRequest: ((value: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation(() => new Promise<Response>((resolve) => {
      resolveRequest = resolve;
    }));
    render(<WorkspaceFilesRail threadId="t1" />);

    await screen.findByTestId('input-row-in1');
    await screen.findByTestId('artifact-row-art1');
    await user.click(screen.getByTestId('workspace-start-work-open'));

    const goal = screen.getByTestId('workspace-start-work-goal');
    const criteria = screen.getByTestId('workspace-start-work-criteria');
    const deliverable = screen.getByTestId('workspace-start-work-deliverable');
    const confirm = screen.getByTestId('workspace-start-work-confirm');
    await user.type(goal, 'Prepare the readiness report');
    await user.type(criteria, 'Report is complete{Enter}Evidence is attached');
    await user.type(deliverable, 'A verified readiness report');
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const dialog = screen.getByRole('dialog');
    await waitFor(() => expect(dialog).toHaveFocus());

    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog')).toBe(dialog);
    expect(dialog).toHaveFocus();

    await user.tab();
    expect(dialog).toHaveFocus();
    await user.tab({ shift: true });
    expect(dialog).toHaveFocus();

    await act(async () => {
      resolveRequest?.({
        ok: true,
        json: async () => startWorkResult('pending-parent', 't1'),
      } as Response);
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('Cancel and successful Start Work restore the connected opener', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: async () => startWorkResult('focus-parent', 't1'),
    } as Response);
    render(<WorkspaceFilesRail threadId="t1" />);
    const opener = screen.getByTestId('workspace-start-work-open');

    fireEvent.click(opener);
    fireEvent.click(screen.getByTestId('workspace-start-work-cancel'));
    await waitFor(() => expect(opener).toHaveFocus());

    fireEvent.click(opener);
    fillValidStartWorkForm();
    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('invalid form disables confirm', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    openStartWorkDialog();

    expect(screen.getByTestId('workspace-start-work-confirm')).toBeDisabled();
    fireEvent.change(screen.getByTestId('workspace-start-work-goal'), {
      target: { value: 'Goal only' },
    });
    expect(screen.getByTestId('workspace-start-work-confirm')).toBeDisabled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('one confirm performs exactly one correctly shaped POST and binds the parent locally', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    let resolveRequest: ((value: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation(() => new Promise<Response>((resolve) => {
      resolveRequest = resolve;
    }));
    const onSessionBound = vi.fn();
    render(<WorkspaceFilesRail threadId="room/1" onSessionBound={onSessionBound} />);
    openStartWorkDialog();
    fillValidStartWorkForm();
    fireEvent.click(screen.getByTestId('workspace-start-work-retry'));

    const confirm = screen.getByTestId('workspace-start-work-confirm');
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId('workspace-start-work-confirm')).toBeDisabled();
    expect(fetch).toHaveBeenCalledWith(
      '/api/threads/room%2F1/start-work',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          goal: 'Prepare the readiness report',
          success_criteria: ['Report is complete', 'Evidence is attached'],
          expected_deliverable: 'A verified readiness report',
          retry_blocked: true,
        }),
      },
    );

    await act(async () => {
      resolveRequest?.({
        ok: true,
        json: async () => startWorkResult('parent-1', 'room/1'),
      } as Response);
    });

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(fetchTaskSteps).toHaveBeenCalledWith('parent-1'));
    expect(screen.getByTestId('workspace-files-todos')).toBeTruthy();
    expect(useStore.getState().crewSessionsByParent.get('parent-1')).toEqual(
      sessionProjection('parent-1', 'room/1'),
    );
    expect(onSessionBound).toHaveBeenCalledTimes(1);
    expect(onSessionBound).toHaveBeenCalledWith(startWorkResult('parent-1', 'room/1'));
  });

  it('rejects a parent returned for a different authority room without hydration', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: async () => startWorkResult(
        'existing-parent',
        'existing-authority-room',
        'executing',
        'resumed',
      ),
    } as Response);
    const onSessionBound = vi.fn();
    render(<WorkspaceFilesRail threadId="requested-room" onSessionBound={onSessionBound} />);
    openStartWorkDialog();
    fillValidStartWorkForm();

    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));

    expect(await screen.findByTestId('workspace-start-work-error')).toHaveTextContent(
      'different room',
    );
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(fetchTaskSteps).not.toHaveBeenCalledWith('existing-parent');
    expect(useStore.getState().crewSessionsByParent.has('existing-parent')).toBe(false);
    expect(onSessionBound).not.toHaveBeenCalled();
  });

  it('server error stays visible with inputs preserved and is retryable', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    vi.mocked(fetch)
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({ detail: 'crew_session_terminal_not_reopenable' }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => startWorkResult('parent-2', 't1'),
      } as Response);
    render(<WorkspaceFilesRail threadId="t1" />);
    const opener = screen.getByTestId('workspace-start-work-open');
    openStartWorkDialog();
    fillValidStartWorkForm();

    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    expect(await screen.findByTestId('workspace-start-work-error')).toHaveTextContent(
      'crew_session_terminal_not_reopenable',
    );
    expect(screen.getByTestId('workspace-start-work-goal')).toHaveValue(
      'Prepare the readiness report',
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog.contains(document.activeElement)).toBe(true);

    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it.each([
    ['crew_session_worker_unavailable', 'No eligible worker is available.'],
    ['crew_session_worker_eligibility_unwired', 'Worker eligibility checks are unavailable.'],
    ['crew_session_agent_identity_changed', 'The selected worker identity has changed.'],
    ['crew_session_owner_identity_changed', 'The selected worker identity has changed.'],
    ['crew_session_retry_not_authorized', 'Retry is not authorized for the current session.'],
    ['crew_worker_identity_lost', 'Execution evidence must be reviewed'],
    ...[
      'crew_recovery_plan_runtime_invalid', 'crew_recovery_plan_integrity_invalid',
      'crew_recovery_plan_semantic_invalid', 'crew_recovery_plan_missing',
      'crew_recovery_plan_children_invalid', 'crew_recovery_plan_child_id_conflict',
      'crew_recovery_plan_version_invalid', 'crew_recovery_plan_phase_invalid',
      'crew_recovery_phase_ref_invalid', 'crew_recovery_version_invalid',
      'crew_recovery_error_code_invalid', 'crew_recovery_attempt_count_invalid',
      'crew_recovery_retry_count_invalid', 'crew_recovery_interrupted_children_invalid',
      'crew_recovery_backoff_invalid', 'crew_recovery_too_large',
    ].map(code => [code, 'Execution evidence must be reviewed']),
  ])('maps exact API detail %s to bounded guidance', async (code, expected) => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    vi.mocked(fetch).mockResolvedValue({
      ok: false, status: 422, json: async () => ({ detail: code }),
    } as Response);
    const onSessionBound = vi.fn();
    render(<WorkspaceFilesRail threadId="t1" onSessionBound={onSessionBound} />);
    openStartWorkDialog();
    fillValidStartWorkForm();
    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));

    const error = await screen.findByTestId('workspace-start-work-error');
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith('/api/threads/t1/start-work', expect.objectContaining({ method: 'POST' }));
    expect(error).toHaveTextContent(expected);
    expect(error.textContent).not.toContain(code);
    expect(error.textContent!.length).toBeLessThanOrEqual(256);
    expect(screen.getByTestId('workspace-start-work-goal')).toHaveValue('Prepare the readiness report');
    expect(onSessionBound).not.toHaveBeenCalled();
    expect(useStore.getState().crewSessionsByParent.size).toBe(0);
  });

  it.each([
    'unrecognized_error',
    'prefix crew_session_worker_unavailable',
    'crew_session_worker_unavailable_extra',
    'crew_session_worker_unavailable: detail',
    'crew_recovery_unrecognized_integrity',
    'x'.repeat(300),
  ])('preserves the bounded fallback for non-exact detail %s', async (detail) => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    vi.mocked(fetch).mockResolvedValue({
      ok: false, status: 409, json: async () => ({ detail }),
    } as Response);
    render(<WorkspaceFilesRail threadId="t1" />);
    openStartWorkDialog();
    fillValidStartWorkForm();
    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    expect((await screen.findByTestId('workspace-start-work-error')).textContent).toBe(detail.slice(0, 256));
  });

  it('retains the API status fallback when detail is not a string', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    vi.mocked(fetch).mockResolvedValue({
      ok: false, status: 422, json: async () => ({ detail: { code: 'crew_session_worker_unavailable' } }),
    } as Response);
    render(<WorkspaceFilesRail threadId="t1" />);
    openStartWorkDialog();
    fillValidStartWorkForm();
    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    expect(await screen.findByTestId('workspace-start-work-error')).toHaveTextContent('Start Work failed (422)');
  });

  it('retains the generic fallback for a non-Error rejection', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    vi.mocked(fetch).mockRejectedValue(null);
    render(<WorkspaceFilesRail threadId="t1" />);
    openStartWorkDialog();
    fillValidStartWorkForm();
    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    expect(await screen.findByTestId('workspace-start-work-error')).toHaveTextContent('Start Work failed');
  });

  it('does not let a previous room error overwrite the current room error', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    let resolveOld!: (response: Response) => void;
    vi.mocked(fetch)
      .mockImplementationOnce(() => new Promise<Response>(resolve => { resolveOld = resolve; }))
      .mockResolvedValueOnce({
        ok: false, status: 409, json: async () => ({ detail: 'crew_session_retry_not_authorized' }),
      } as Response);
    const view = render(<WorkspaceFilesRail threadId="room-1" />);
    openStartWorkDialog();
    fillValidStartWorkForm();
    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(resolveOld).toBeTypeOf('function');

    view.rerender(<WorkspaceFilesRail threadId="room-2" />);
    openStartWorkDialog();
    fillValidStartWorkForm();
    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    expect(await screen.findByTestId('workspace-start-work-error')).toHaveTextContent('Retry is not authorized for the current session.');
    expect(fetch).toHaveBeenCalledTimes(2);
    await act(async () => resolveOld({
      ok: false, status: 422, json: async () => ({ detail: 'crew_worker_identity_lost' }),
    } as Response));
    expect(screen.getByTestId('workspace-start-work-error')).toHaveTextContent('Retry is not authorized for the current session.');
    expect(screen.queryByText(/Worker identity was lost/)).toBeNull();
    expect(screen.getByTestId('workspace-start-work-confirm')).toBeEnabled();
  });

  it('ignores a Start Work response resolved in the same act as a room switch', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    let resolveRequest: ((value: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation(() => new Promise<Response>((resolve) => {
      resolveRequest = resolve;
    }));
    const { rerender } = render(<WorkspaceFilesRail threadId="room-1" />);
    openStartWorkDialog();
    fillValidStartWorkForm();
    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

    await act(async () => {
      resolveRequest?.({
        ok: true,
        json: async () => startWorkResult('stale-parent', 'room-1'),
      } as Response);
      rerender(<WorkspaceFilesRail threadId="room-2" />);
    });

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(fetchTaskSteps).not.toHaveBeenCalledWith('stale-parent');
    expect(useStore.getState().crewSessionsByParent.has('stale-parent')).toBe(false);
    expect(screen.queryByTestId('workspace-files-todos')).toBeNull();
  });

  it('drops an old live refresh started before a room switch', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    let staleResolve: ((value: ArtifactView[]) => void) | undefined;
    let roomOneCalls = 0;
    vi.mocked(fetchThreadArtifacts).mockImplementation((roomId) => {
      if (roomId === 'room-1') {
        roomOneCalls += 1;
        if (roomOneCalls === 1) return Promise.resolve([]);
        return new Promise<ArtifactView[]>((resolve) => { staleResolve = resolve; });
      }
      return Promise.resolve([]);
    });

    const view = render(<WorkspaceFilesRail threadId="room-1" />);
    await waitFor(() => expect(fetchThreadArtifacts).toHaveBeenCalledWith('room-1'));
    act(() => useStore.setState({
      liveArtifactRefresh: { threadId: 'room-1', requestId: 'artifact-live' },
    }));
    await waitFor(() => expect(staleResolve).toBeTypeOf('function'));
    view.rerender(<WorkspaceFilesRail threadId="room-2" />);
    await act(async () => {
      staleResolve?.([{
        ...ARTIFACTS[0],
        id: 'stale-artifact',
        thread_id: 'room-1',
        name: 'stale-room-one.md',
      }]);
    });

    expect(screen.queryByTestId('artifact-row-stale-artifact')).toBeNull();
    expect(fetchThreadArtifacts).toHaveBeenCalledWith('room-2');
  });

  it('owned retry command expands, pre-fills, checks retry, focuses Goal, and performs no write', async () => {
    const opener = document.createElement('button');
    opener.textContent = 'Retry blocked CrewSession work';
    document.body.appendChild(opener);
    const retryCommand: CrewSessionRetryCommand = {
      requestId: 1,
      parentId: 'blocked-parent',
      threadId: 't1',
      projection: sessionProjection('blocked-parent', 't1', 'blocked_needs_captain'),
      opener,
    };
    render(<WorkspaceFilesRail threadId="t1" retryCommand={retryCommand} />);

    expect(await screen.findByRole('dialog')).toBeTruthy();
    expect(screen.getByTestId('workspace-files-rail').getAttribute('data-collapsed')).toBe('false');
    expect(screen.getByTestId('workspace-start-work-goal')).toHaveValue(retryCommand.projection.goal);
    expect(screen.getByTestId('workspace-start-work-criteria')).toHaveValue(retryCommand.projection.success_criteria.join('\n'));
    expect(screen.getByTestId('workspace-start-work-deliverable')).toHaveValue(retryCommand.projection.expected_deliverable);
    expect(screen.getByTestId('workspace-start-work-retry')).toBeChecked();
    await waitFor(() => expect(screen.getByTestId('workspace-start-work-goal')).toHaveFocus());
    expect(fetch).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('workspace-start-work-cancel'));
    await waitFor(() => expect(opener).toHaveFocus());
    opener.remove();
  });

  it.each([
    { name: 'command room', commandThread: 'other-room', projectionThread: 't1', projectionParent: 'blocked-parent', taskId: 'blocked-parent' },
    { name: 'projection room', commandThread: 't1', projectionThread: 'other-room', projectionParent: 'blocked-parent', taskId: 'blocked-parent' },
    { name: 'projection task', commandThread: 't1', projectionThread: 't1', projectionParent: 'other-parent', taskId: 'blocked-parent' },
    { name: 'bound task', commandThread: 't1', projectionThread: 't1', projectionParent: 'blocked-parent', taskId: 'other-parent' },
  ])('ignores a retry command with a mismatched $name', async ({ commandThread, projectionThread, projectionParent, taskId }) => {
    const opener = document.createElement('button');
    document.body.appendChild(opener);
    try {
      const retryCommand: CrewSessionRetryCommand = {
        requestId: 1,
        parentId: 'blocked-parent',
        threadId: commandThread,
        projection: sessionProjection(projectionParent, projectionThread, 'blocked_needs_captain'),
        opener,
      };
      render(<WorkspaceFilesRail threadId="t1" taskId={taskId} retryCommand={retryCommand} />);
      await act(async () => {});
      expect(opener.isConnected).toBe(true);
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(screen.getByTestId('workspace-files-rail')).toHaveAttribute('data-collapsed', 'true');
      expect(fetch).not.toHaveBeenCalled();
      expect(useStore.getState().crewSessionsByParent.size).toBe(0);
    } finally {
      opener.remove();
    }
  });

  it('submits an owned unavailable-worker retry only once while pending', async () => {
    const opener = document.createElement('button');
    document.body.appendChild(opener);
    try {
      let resolveRequest!: (response: Response) => void;
      vi.mocked(fetch).mockImplementation(() => new Promise<Response>(resolve => { resolveRequest = resolve; }));
      const retryCommand: CrewSessionRetryCommand = {
        requestId: 1,
        parentId: 'blocked-parent',
        threadId: 't1',
        projection: sessionProjection('blocked-parent', 't1', 'blocked_needs_captain'),
        opener,
      };
      const onSessionBound = vi.fn();
      const view = render(<WorkspaceFilesRail threadId="t1" taskId="blocked-parent" retryCommand={retryCommand} onSessionBound={onSessionBound} />);
      const confirm = await screen.findByTestId('workspace-start-work-confirm');
      expect(confirm).toBeEnabled();
      expect(fetch).not.toHaveBeenCalled();
      const form = confirm.closest('form');
      expect(form).not.toBeNull();
      act(() => {
        fireEvent.click(confirm);
        fireEvent.click(confirm);
        fireEvent.submit(form!);
      });
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(confirm).toBeDisabled();
      expect(fetch).toHaveBeenCalledWith('/api/threads/t1/start-work', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          goal: retryCommand.projection.goal,
          success_criteria: retryCommand.projection.success_criteria,
          expected_deliverable: retryCommand.projection.expected_deliverable,
          retry_blocked: true,
        }),
      });
      const result = startWorkResult('blocked-parent', 't1', 'executing', 'resumed');
      await act(async () => resolveRequest({ ok: true, json: async () => result } as Response));
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
      expect(onSessionBound).toHaveBeenCalledExactlyOnceWith(result);
      expect(useStore.getState().crewSessionsByParent.get('blocked-parent')).toEqual(result.session);
      view.rerender(<WorkspaceFilesRail threadId="t1" taskId="blocked-parent" retryCommand={{ ...retryCommand }} onSessionBound={onSessionBound} />);
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(screen.queryByText('Verified result')).toBeNull();
    } finally {
      opener.remove();
    }
  });

  it('keeps missing result artifact metadata unavailable without opening a preview', async () => {
    vi.mocked(fetchThreadArtifacts).mockResolvedValue([]);
    vi.mocked(fetchArtifactMetadata).mockResolvedValue(null);
    const command: CrewSessionArtifactCommand = {
      requestId: 1, parentId: 'parent-1', threadId: 't1', artifactId: 'missing-result',
    };
    render(<WorkspaceFilesRail threadId="t1" taskId="parent-1" artifactCommand={command} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('metadata could not be loaded');
    expect(fetchArtifactMetadata).toHaveBeenCalledExactlyOnceWith('missing-result');
    expect(screen.queryByTestId('workspace-files-preview')).toBeNull();
    expect(screen.queryByText('Verified result')).toBeNull();
  });

  it('owned artifact command prefers local metadata and opens the existing viewer', async () => {
    const command: CrewSessionArtifactCommand = {
      requestId: 1,
      parentId: 'parent-1',
      threadId: 't1',
      artifactId: 'art1',
    };
    render(<WorkspaceFilesRail threadId="t1" artifactCommand={command} />);

    expect(await screen.findByTestId('workspace-files-preview')).toBeTruthy();
    expect(screen.getAllByText('report.md').length).toBeGreaterThan(0);
    expect(fetchArtifactMetadata).not.toHaveBeenCalled();
  });

  it('rejects a matching preloaded artifact owned by another room', async () => {
    vi.mocked(fetchThreadArtifacts).mockResolvedValue([{ ...ARTIFACTS[0], thread_id: 'other-room' }]);
    const command: CrewSessionArtifactCommand = {
      requestId: 3,
      parentId: 'parent-1',
      threadId: 't1',
      artifactId: 'art1',
    };

    render(<WorkspaceFilesRail threadId="t1" artifactCommand={command} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('metadata could not be loaded');
    expect(screen.queryByTestId('workspace-files-preview')).toBeNull();
    expect(fetchArtifactMetadata).not.toHaveBeenCalled();
  });

  it('missing or mismatched artifact metadata alerts, then Retry opens the existing viewer', async () => {
    vi.mocked(fetchThreadArtifacts).mockResolvedValue([]);
    const loaded: ArtifactView = {
      ...ARTIFACTS[0],
      id: 'art2',
      thread_id: 't1',
      name: 'recovered.md',
    };
    vi.mocked(fetchArtifactMetadata)
      .mockResolvedValueOnce({ ...loaded, thread_id: 'other-room' })
      .mockResolvedValueOnce(loaded);
    const command: CrewSessionArtifactCommand = {
      requestId: 2,
      parentId: 'parent-1',
      threadId: 't1',
      artifactId: 'art2',
    };
    render(<WorkspaceFilesRail threadId="t1" artifactCommand={command} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('metadata could not be loaded');
    expect(screen.queryByTestId('workspace-files-preview')).toBeNull();
    fireEvent.click(screen.getByTestId('workspace-artifact-command-retry'));

    expect(await screen.findByTestId('workspace-files-preview')).toBeTruthy();
    expect(screen.getAllByText('recovered.md').length).toBeGreaterThan(0);
    expect(fetchArtifactMetadata).toHaveBeenCalledTimes(2);
    expect(fetchArtifactMetadata).toHaveBeenNthCalledWith(1, 'art2');
    expect(fetchArtifactMetadata).toHaveBeenNthCalledWith(2, 'art2');
  });

  it('todosApi no longer exports passive ensureRoomTask', () => {
    expect('ensureRoomTask' in todosApi).toBe(false);
  });
});
