/**
 * BF-723 (absorbing #1161): a crew session detail that arrived is not stale
 * because a frame arrived.
 *
 * `load` captured `authority.liveSequence` before `fetchCrewTaskDetail` and
 * discarded the response if the sequence had moved at all by the time it
 * resolved. This surface is the worst place for that rule: the panel refreshes
 * BECAUSE a child finished, and a child finishing is itself a frame. The
 * condition it tested for was the condition that made the fetch worth doing.
 *
 * BF-720 removed the identical comparison from `ProfileChatTab`. Ordering here
 * was already enforced by `requestIdRef` plus `inFlightRef` (which coalesce)
 * and by the `owns(...)` ownership check, so the sequence test only ever
 * subtracted.
 *
 * `liveGeneration` is the genuine authority check and is asserted intact.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';

import { useStore } from '../../store/useStore';
import type {
  CrewSessionDetailProjection,
  CrewSessionState,
  WSEvent,
} from '../../store/types';

vi.mock('../sidebar/threadApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../sidebar/threadApi')>();
  return { ...actual, fetchCrewTaskDetail: vi.fn() };
});

import { fetchCrewTaskDetail } from '../sidebar/threadApi';
import CrewCollaborationPanel from './CrewCollaborationPanel';

const GENERATION = 'a'.repeat(32);
const OTHER_GENERATION = 'b'.repeat(32);

function projection(state: CrewSessionState = 'executing'): CrewSessionDetailProjection {
  return {
    task_id: 'p1',
    thread_id: 't1',
    goal: 'Prepare the readiness report',
    origin: 'captain',
    originator_id: 'captain',
    facilitator_id: 'facilitator-1',
    owner_ids: ['facilitator-1'],
    state,
    revision: 2,
    success_criteria: ['Report is complete'],
    expected_deliverable: 'A verified readiness report',
    timestamps: {
      created_at: 1,
      transitioned_at: 3,
      started_at: 2,
      first_result_at: null,
      verified_at: null,
      completed_at: null,
    },
    progress: {
      total: 4,
      done: 3,
      failed: 0,
      active: 1,
      active_child: {
        id: 'child-1',
        title: 'Analyze the evidence',
        status: 'in_progress',
        owner_id: 'owner-2',
      },
    },
    last_result_summary: 'Draft analysis is available.',
    blocker: null,
    result: null,
    verification: null,
    duplicate_resume_count: 0,
  };
}

/** A live frame on the CURRENT stream — a child finishing produces one. */
function liveFrame(sequence: number): WSEvent {
  return {
    type: 'chat_thread_message_appended',
    data: {
      thread_id: 't1',
      message_id: `m${sequence}`,
      author_id: 'facilitator-1',
      role: 'agent',
      created_at: 2,
    },
    timestamp: 1,
    stream: { generation: GENERATION, sequence },
  } as WSEvent;
}

function seedStream(): void {
  useStore.setState({
    crewSessionsByParent: new Map(),
    liveCrewOwnerParentId: null,
    liveGeneration: GENERATION,
    liveSequence: 0,
    liveRepairEpoch: 0,
  });
}

afterEach(() => {
  cleanup();
  useStore.setState({
    crewSessionsByParent: new Map(),
    liveCrewOwnerParentId: null,
    liveGeneration: null,
    liveSequence: 0,
    liveRepairEpoch: 0,
  });
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe('BF-723 CrewCollaborationPanel detail survives a live frame mid-fetch', () => {
  it('hydrates a session that resolved after a frame advanced liveSequence', async () => {
    let release: ((v: { kind: 'success'; response: { session: CrewSessionDetailProjection } }) => void) | null = null;
    vi.mocked(fetchCrewTaskDetail).mockImplementation(
      () => new Promise((resolve) => { release = resolve; }) as ReturnType<typeof fetchCrewTaskDetail>,
    );

    seedStream();
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);
    await waitFor(() => expect(fetchCrewTaskDetail).toHaveBeenCalledWith('p1'));
    expect(release).not.toBeNull();

    /* The child that this refresh is about finishing IS the frame. */
    act(() => { useStore.getState().handleEvent(liveFrame(1)); });
    expect(useStore.getState().liveSequence).toBe(1);
    expect(useStore.getState().liveGeneration).toBe(GENERATION);

    await act(async () => {
      release!({ kind: 'success', response: { session: projection() } });
      await Promise.resolve();
    });

    await waitFor(() =>
      expect(useStore.getState().crewSessionsByParent.get('p1')).toMatchObject({
        task_id: 'p1', thread_id: 't1', revision: 2,
      }),
    );
    expect(await screen.findByText('3/4')).toBeTruthy();
  });

  it('still discards the session when liveGeneration changes mid-fetch', async () => {
    let release: ((v: { kind: 'success'; response: { session: CrewSessionDetailProjection } }) => void) | null = null;
    vi.mocked(fetchCrewTaskDetail).mockImplementation(
      () => new Promise((resolve) => { release = resolve; }) as ReturnType<typeof fetchCrewTaskDetail>,
    );

    seedStream();
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);
    await waitFor(() => expect(fetchCrewTaskDetail).toHaveBeenCalledWith('p1'));

    act(() => { useStore.setState({ liveGeneration: OTHER_GENERATION }); });

    await act(async () => {
      release!({ kind: 'success', response: { session: projection() } });
      await Promise.resolve();
    });

    expect(useStore.getState().crewSessionsByParent.get('p1')).toBeUndefined();
  });
});
