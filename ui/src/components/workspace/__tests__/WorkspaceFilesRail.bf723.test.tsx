/**
 * BF-723 (absorbing #1161): the rail's artifact and Todo lists survive a live
 * frame arriving mid-fetch.
 *
 * `refreshArtifacts` and `refreshSteps` each captured `authority.liveSequence`
 * before their GET and discarded the result if the sequence had moved by the
 * time it resolved. Both are triggered by live artifact/Todo commands, which
 * arrive as frames — and more frames follow them. The rail therefore fetched
 * the right data at the right moment and then threw it away, leaving the
 * Outputs and Todo lists showing the state before the work landed.
 *
 * These are two independent call sites in one component and get one
 * reproduction each: the artifact path additionally gates on
 * `triggerArtifactId` being present in the response, and the steps path
 * additionally gates on `effectiveTaskIdRef`, so a single shared test would
 * not prove either. `liveGeneration` remains the authority check and is
 * asserted intact for both.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';

import { useStore, type ArtifactView } from '../../../store/useStore';
import type { TaskInput } from '../../inputs/inputsApi';
import type { WSEvent } from '../../../store/types';

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
import { fetchTaskSteps, updateTaskStep } from '../todosApi';
import { WorkspaceFilesRail } from '../WorkspaceFilesRail';

const GENERATION = 'a'.repeat(32);
const OTHER_GENERATION = 'b'.repeat(32);

const INPUTS: TaskInput[] = [
  { content_hash: 'in1', mime: 'text/plain', filename: 'notes.txt', size: 10, source: 'task' },
];

const BASE_ARTIFACT: ArtifactView = {
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
};

/** A live frame on the CURRENT stream — the burst that follows a promotion. */
function liveFrame(sequence: number): WSEvent {
  return {
    type: 'chat_thread_message_appended',
    data: {
      thread_id: 't1',
      message_id: `m${sequence}`,
      author_id: 'a1',
      role: 'agent',
      created_at: 2,
    },
    timestamp: 1,
    stream: { generation: GENERATION, sequence },
  } as WSEvent;
}

/** Hold a mocked resolver so the test owns when the GET lands. */
function deferred<T>(): { promise: Promise<T>; release: (v: T) => void } {
  let release!: (v: T) => void;
  const promise = new Promise<T>((resolve) => { release = resolve; });
  return { promise, release };
}

function seedStream(): void {
  useStore.setState({
    crewSessionsByParent: new Map(),
    crewSessionSummariesByThread: new Map(),
    liveArtifactRefresh: null,
    liveTodoRefresh: null,
    liveRepairEpoch: 0,
    liveRailOwner: null,
    liveGeneration: GENERATION,
    liveSequence: 0,
  });
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('probos.workspaceFiles.collapsed', '0');
  vi.mocked(fetchThreadInputs).mockResolvedValue(INPUTS);
  vi.mocked(fetchThreadArtifacts).mockResolvedValue([BASE_ARTIFACT]);
  vi.mocked(fetchArtifactMetadata).mockResolvedValue(null);
  vi.mocked(fetchTaskSteps).mockResolvedValue([]);
  vi.mocked(updateTaskStep).mockResolvedValue();
  vi.stubGlobal('fetch', vi.fn());
  seedStream();
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
    liveRailOwner: null,
    liveGeneration: null,
    liveSequence: 0,
  });
});

describe('BF-723 WorkspaceFilesRail artifacts survive a live frame mid-fetch', () => {
  it('renders artifacts that resolved after a frame advanced liveSequence', async () => {
    render(<WorkspaceFilesRail threadId="t1" taskId="parent-1" />);
    await waitFor(() => expect(fetchThreadArtifacts).toHaveBeenCalled());
    await screen.findByText('report.md');

    // The promoted artifact's own command triggers the refresh...
    const held = deferred<ArtifactView[]>();
    vi.mocked(fetchThreadArtifacts).mockReturnValue(held.promise);
    act(() => useStore.setState({
      liveArtifactRefresh: { threadId: 't1', requestId: 'art2' },
    }));
    await waitFor(() => expect(fetchThreadArtifacts).toHaveBeenCalledTimes(2));

    // ...and the frames that follow the promotion arrive while it is in flight.
    act(() => { useStore.getState().handleEvent(liveFrame(1)); });
    expect(useStore.getState().liveSequence).toBe(1);
    expect(useStore.getState().liveGeneration).toBe(GENERATION);

    await act(async () => {
      held.release([BASE_ARTIFACT, { ...BASE_ARTIFACT, id: 'art2', name: 'live.md' }]);
      await Promise.resolve();
    });

    expect(await screen.findByText('live.md')).toBeTruthy();
  });

  it('still discards artifacts when liveGeneration changes mid-fetch', async () => {
    render(<WorkspaceFilesRail threadId="t1" taskId="parent-1" />);
    await waitFor(() => expect(fetchThreadArtifacts).toHaveBeenCalled());
    await screen.findByText('report.md');

    const held = deferred<ArtifactView[]>();
    vi.mocked(fetchThreadArtifacts).mockReturnValue(held.promise);
    act(() => useStore.setState({
      liveArtifactRefresh: { threadId: 't1', requestId: 'art2' },
    }));
    await waitFor(() => expect(fetchThreadArtifacts).toHaveBeenCalledTimes(2));

    act(() => { useStore.setState({ liveGeneration: OTHER_GENERATION }); });

    await act(async () => {
      held.release([BASE_ARTIFACT, { ...BASE_ARTIFACT, id: 'art2', name: 'live.md' }]);
      await Promise.resolve();
    });

    expect(screen.queryByText('live.md')).toBeNull();
  });
});

describe('BF-723 WorkspaceFilesRail Todo steps survive a live frame mid-fetch', () => {
  it('renders steps that resolved after a frame advanced liveSequence', async () => {
    render(<WorkspaceFilesRail threadId="t1" taskId="parent-1" />);
    await waitFor(() => expect(fetchTaskSteps).toHaveBeenCalled());

    const held = deferred<{ label: string; status: string }[]>();
    vi.mocked(fetchTaskSteps).mockReturnValue(
      held.promise as ReturnType<typeof fetchTaskSteps>,
    );
    act(() => useStore.setState({
      liveTodoRefresh: { parentId: 'parent-1', requestId: 2 },
    }));
    await waitFor(() => expect(fetchTaskSteps).toHaveBeenCalledTimes(2));

    act(() => { useStore.getState().handleEvent(liveFrame(1)); });
    expect(useStore.getState().liveSequence).toBe(1);
    expect(useStore.getState().liveGeneration).toBe(GENERATION);

    await act(async () => {
      held.release([{ label: 'Live Todo', status: 'submitted' }]);
      await Promise.resolve();
    });

    expect(await screen.findByText(/Live Todo/)).toBeTruthy();
  });

  it('still discards steps when liveGeneration changes mid-fetch', async () => {
    render(<WorkspaceFilesRail threadId="t1" taskId="parent-1" />);
    await waitFor(() => expect(fetchTaskSteps).toHaveBeenCalled());

    const held = deferred<{ label: string; status: string }[]>();
    vi.mocked(fetchTaskSteps).mockReturnValue(
      held.promise as ReturnType<typeof fetchTaskSteps>,
    );
    act(() => useStore.setState({
      liveTodoRefresh: { parentId: 'parent-1', requestId: 2 },
    }));
    await waitFor(() => expect(fetchTaskSteps).toHaveBeenCalledTimes(2));

    act(() => { useStore.setState({ liveGeneration: OTHER_GENERATION }); });

    await act(async () => {
      held.release([{ label: 'Live Todo', status: 'submitted' }]);
      await Promise.resolve();
    });

    expect(screen.queryByText(/Live Todo/)).toBeNull();
  });
});
