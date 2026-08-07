/**
 * BF-723 (absorbing #1161): a summary that arrived is not stale because a
 * frame arrived.
 *
 * `refreshSummaries` captured `authority.liveSequence` before calling
 * `repairRoomSummaries()` and threw the result away if the sequence had moved
 * at all by the time it resolved. BF-720 removed exactly this comparison from
 * `ProfileChatTab` and the reasoning transfers unchanged: within one
 * `liveGeneration` a sequence advance means only that ANOTHER FRAME ARRIVED,
 * and one always does at the moment a work item finishes — which is the moment
 * a room's outputs/steps counters change and this refresh is worth doing.
 *
 * Ordering between two refreshes of the same panel was already enforced by
 * `summaryRequestRef` and `summaryInFlightRef`, which coalesce rather than
 * race, so the sequence check contributed nothing except the discard.
 *
 * `liveGeneration` is the real authority check and is asserted here too: a
 * stream identity change genuinely voids the fetch, and removing that guard
 * would be a different bug.
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, waitFor, act } from '@testing-library/react';

import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent, RoomSummary, WSEvent } from '../../../store/types';

vi.mock('../../sidebar/threadApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../sidebar/threadApi')>();
  return { ...actual, listThreads: vi.fn(), repairRoomSummaries: vi.fn() };
});

import { listThreads, repairRoomSummaries } from '../../sidebar/threadApi';
import ChatsPanel from '../ChatsPanel';

const GENERATION = 'a'.repeat(32);
const OTHER_GENERATION = 'b'.repeat(32);

const G1: AD791aChatThreadView = {
  id: 'g1',
  title: 'Bridge Sync',
  participants: ['mccoy', 'scotty'],
  created_at: 0,
  last_active_at: 0,
};

const SUMMARY: RoomSummary = {
  outputs: 2,
  steps_total: 4,
  steps_done: 3,
  topic: 'Live navigation report',
};

function mkAgent(id: string, callsign: string): Agent {
  return {
    id,
    agentType: 'crew',
    callsign,
    displayName: '',
    pool: 'bridge',
    state: 'active',
    confidence: 1,
    trust: 0.5,
    tier: 'domain',
    isCrew: true,
    position: [0, 0, 0] as [number, number, number],
    department: '',
  } as Agent;
}

/** A live frame on the CURRENT stream — the burst this panel used to fear. */
function liveFrame(sequence: number, generation = GENERATION): WSEvent {
  return {
    type: 'chat_thread_message_appended',
    data: {
      thread_id: 'g1',
      message_id: `m${sequence}`,
      author_id: 'mccoy',
      role: 'agent',
      created_at: 2,
    },
    timestamp: 1,
    stream: { generation, sequence },
  } as WSEvent;
}

function seedOpenPanel(): void {
  const agents = new Map<string, Agent>();
  agents.set('mccoy', mkAgent('mccoy', 'Bones'));
  agents.set('scotty', mkAgent('scotty', 'Scott'));
  useStore.setState({
    agents,
    chatsOpen: true,
    threadIdByAgent: new Map(),
    chatThreads: new Map(),
    roomSummariesByThread: new Map(),
    liveGeneration: GENERATION,
    liveSequence: 0,
    liveRepairEpoch: 0,
  });
}

beforeEach(() => {
  vi.mocked(listThreads).mockResolvedValue([G1]);
});

afterEach(() => {
  cleanup();
  useStore.setState({
    agents: new Map(),
    chatsOpen: false,
    chatThreads: new Map(),
    threadIdByAgent: new Map(),
    roomSummariesByThread: new Map(),
    liveGeneration: null,
    liveSequence: 0,
    liveRepairEpoch: 0,
  });
  vi.clearAllMocks();
});

describe('BF-723 ChatsPanel room summaries survive a live frame mid-fetch', () => {
  it('hydrates a summary that resolved after a frame advanced liveSequence', async () => {
    let release: ((v: { kind: 'success'; summaries: Record<string, RoomSummary> }) => void) | null = null;
    vi.mocked(repairRoomSummaries).mockImplementation(
      () => new Promise((resolve) => { release = resolve; }),
    );

    seedOpenPanel();
    render(<ChatsPanel />);
    await screen.findByTestId('chat-row-g1');
    await waitFor(() => expect(repairRoomSummaries).toHaveBeenCalled());
    expect(release).not.toBeNull();

    /* The burst. One frame on the SAME stream, arriving while the summary GET
     * is in flight — the ordinary case, not a pathological one. */
    act(() => { useStore.getState().handleEvent(liveFrame(1)); });
    expect(useStore.getState().liveSequence).toBe(1);
    expect(useStore.getState().liveGeneration).toBe(GENERATION);

    await act(async () => {
      release!({ kind: 'success', summaries: { g1: SUMMARY } });
      await Promise.resolve();
    });

    // The result was correct when it was fetched and is still correct now.
    await waitFor(() =>
      expect(useStore.getState().roomSummariesByThread.get('g1')).toMatchObject({
        outputs: 2, steps_total: 4, steps_done: 3,
      }),
    );
    expect(await screen.findByTestId('room-badge-g1')).toHaveTextContent('3/4');
  });

  it('still discards the summary when liveGeneration changes mid-fetch', async () => {
    /* The authority check that IS real. A new stream identity means the server
     * re-established state under a different generation, and a snapshot will
     * bump liveRepairEpoch to refetch. Removing this would be its own bug. */
    let release: ((v: { kind: 'success'; summaries: Record<string, RoomSummary> }) => void) | null = null;
    vi.mocked(repairRoomSummaries).mockImplementation(
      () => new Promise((resolve) => { release = resolve; }),
    );

    seedOpenPanel();
    render(<ChatsPanel />);
    await screen.findByTestId('chat-row-g1');
    await waitFor(() => expect(repairRoomSummaries).toHaveBeenCalled());

    act(() => { useStore.setState({ liveGeneration: OTHER_GENERATION }); });

    await act(async () => {
      release!({ kind: 'success', summaries: { g1: SUMMARY } });
      await Promise.resolve();
    });

    expect(useStore.getState().roomSummariesByThread.get('g1')).toBeUndefined();
  });
});
