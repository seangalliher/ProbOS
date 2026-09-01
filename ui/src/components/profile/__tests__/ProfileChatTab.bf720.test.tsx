/**
 * BF-720 reproduction: a delivered message whose transcript is fetched and then
 * thrown away.
 *
 * The measured defect: a promoted turn's report was written at 21:56:59,
 * persisted, emitted, and delivered over the websocket -- and did not appear
 * until the Captain sent a message at 22:14:33. 17.5 minutes invisible.
 *
 * BF-703 widened gate 4 (``isOpen``) for the same symptom and the symptom came
 * back, which means gate 4 was not the whole story. These tests walk past it:
 * the frame parses, the generation matches, the sequence advances, a shell owns
 * the thread, the mounted surface owns the thread, and the transcript endpoint
 * returns the message. It still never reaches the transcript, because the
 * refresh compared ``liveSequence`` before and after its own fetch and any
 * unrelated live frame in that window invalidated the result.
 *
 * That comparison is a liveness bug, not a safety property. ``liveGeneration``
 * is what identifies the authority a transcript was fetched under; a sequence
 * advance within the same generation means only "the ship is busy".
 */
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  speakResponseMock: vi.fn(),
  startListeningMock: vi.fn(),
  stopListeningMock: vi.fn(),
}));

vi.mock('../../../audio/voice', () => ({
  flushSpeechQueue: vi.fn(),
  getServerPiperVoices: vi.fn(async () => null),
  speakResponse: mocks.speakResponseMock,
  stripMarkdownForSpeech: (s: string) => s,
  onSpeechEvent: vi.fn(() => () => {}),
  prewarmTts: vi.fn(),
}));

vi.mock('../../../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => false,
  startListening: mocks.startListeningMock,
  stopListening: mocks.stopListeningMock,
}));

vi.mock('../MeetingView', () => ({
  MeetingView: () => <div data-testid="meeting-view-stub" />,
}));

import { ProfileChatTab } from '../ProfileChatTab';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent, WSEvent } from '../../../store/types';
import type { ThreadMessageDTO } from '../../sidebar/threadApi';

const AGENT_ID = 'counselor-ezri';
const THREAD_ID = 'thread-ezri';
const GENERATION = 'a'.repeat(32);
const REPORT_ID = 'msg-promoted-report';

type PendingThreadLoad = {
  readonly threadId: string;
  settled: boolean;
  readonly resolve: (response: Response) => void;
};

let pendingThreadLoads: PendingThreadLoad[] = [];

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify(body),
    json: async () => body,
  } as Response;
}

function mkAgent(): Agent {
  return {
    id: AGENT_ID,
    agentType: 'crew',
    callsign: 'Ezri',
    displayName: '',
    pool: 'bridge',
    state: 'active',
    confidence: 1,
    trust: 0.5,
    tier: 'domain',
    isCrew: true,
    position: [0, 0, 0] as [number, number, number],
  } as Agent;
}

function mkThread(): AD791aChatThreadView {
  return {
    id: THREAD_ID,
    title: 'Ezri',
    participants: ['captain', AGENT_ID],
    created_at: 1_700_000_000,
    last_active_at: 1_700_000_000,
    metadata: {},
  };
}

function dto(id: string, body: string): ThreadMessageDTO {
  return {
    id,
    thread_id: THREAD_ID,
    author_id: AGENT_ID,
    role: 'agent',
    body,
    created_at: 1_700_000_001,
    metadata: {},
  };
}

function frame(
  type: string,
  data: Record<string, unknown>,
  sequence: number,
): WSEvent {
  return { type, data, timestamp: 1, stream: { generation: GENERATION, sequence } };
}

function installSnapshot(): void {
  useStore.getState().handleEvent(frame('state_snapshot', {
    agents: [], connections: [], pools: [], system_mode: 'active',
    tc_n: 0, routing_entropy: 0,
  }, 0));
}

/** A perfectly ordinary background frame: an agent changed state. */
function unrelatedLiveFrame(sequence: number): WSEvent {
  return frame('agent_state', {
    agent_id: 'science-officer',
    state: 'idle',
    confidence: 0.9,
    trust: 0.6,
    pool: 'bridge',
  }, sequence);
}

function reportAppended(sequence: number): WSEvent {
  return frame('chat_thread_message_appended', {
    thread_id: THREAD_ID,
    message_id: REPORT_ID,
    author_id: AGENT_ID,
    role: 'agent',
    created_at: 1_700_000_001,
  }, sequence);
}

function resetStore(): void {
  useStore.setState({
    activeProfileAgent: AGENT_ID,
    activeProfileThreadId: THREAD_ID,
    activeThreadId: null,
    agents: new Map([[AGENT_ID, mkAgent()]]),
    agentConversations: new Map(),
    threadIdByAgent: new Map(),
    chatThreads: new Map([[THREAD_ID, mkThread()]]),
    threadMessages: new Map(),
    artifactsByThread: new Map(),
    selectedArtifactId: null,
    typingAgent: null,
    voiceEnabled: false,
    chatDrafts: {},
    liveGeneration: null,
    liveSequence: 0,
    liveRepairEpoch: 0,
    liveThreadRefresh: null,
    liveArtifactRefresh: null,
    liveTodoRefresh: null,
    liveCrewOwnerParentId: null,
    liveRailOwner: null,
    liveDropCount: 0,
    liveDrops: [],
  });
}

function installFetchMock(): void {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    const messageMatch = url.match(/^\/api\/threads\/([^/?]+)\/messages\?limit=200$/);
    if (messageMatch) {
      const threadId = decodeURIComponent(messageMatch[1]);
      return new Promise<Response>((resolve) => {
        pendingThreadLoads.push({ threadId, settled: false, resolve });
      });
    }
    if (url.endsWith('/chat/history')) return Promise.resolve(jsonResponse({ memories: [] }));
    if (url.endsWith('/profile')) return Promise.resolve(jsonResponse({ voiceProfile: null }));
    if (url === '/api/voice/health') {
      return Promise.resolve(jsonResponse({
        primary_stt: 'browser', engine: 'browser', backend_available: true, healthy: true,
      }));
    }
    const threadMatch = url.match(/^\/api\/threads\/([^/?]+)$/);
    if (threadMatch) return Promise.resolve(jsonResponse(mkThread()));
    return Promise.resolve(jsonResponse({}));
  }));
}

async function waitForThreadLoad(): Promise<PendingThreadLoad> {
  await waitFor(() => {
    expect(pendingThreadLoads.some((load) => !load.settled)).toBe(true);
  });
  const load = pendingThreadLoads.find((item) => !item.settled);
  if (!load) throw new Error('missing controlled transcript load');
  return load;
}

async function resolveThreadLoad(
  load: PendingThreadLoad,
  messages: readonly ThreadMessageDTO[],
): Promise<void> {
  load.settled = true;
  await act(async () => {
    load.resolve(jsonResponse({ thread_id: load.threadId, messages }));
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function transcriptIds(): string[] {
  return (useStore.getState().threadMessages.get(THREAD_ID) ?? []).map((m) => m.id);
}

beforeEach(() => {
  pendingThreadLoads = [];
  localStorage.clear();
  resetStore();
  installFetchMock();
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    configurable: true,
    value: vi.fn(),
  });
});

afterEach(async () => {
  cleanup();
  for (const load of pendingThreadLoads) {
    if (load.settled) continue;
    load.settled = true;
    load.resolve(jsonResponse({ thread_id: load.threadId, messages: [] }));
  }
  await Promise.resolve();
  await Promise.resolve();
  resetStore();
  localStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** Mount, install authority, and settle the transcript load the mount kicks off. */
async function mountWithSeededTranscript(): Promise<void> {
  render(<ProfileChatTab agentId={AGENT_ID} threadId={THREAD_ID} />);
  const initial = await waitForThreadLoad();
  act(() => { installSnapshot(); });
  await resolveThreadLoad(initial, [dto('msg-existing', 'earlier turn')]);
  // The snapshot bumps liveRepairEpoch, which schedules its own repair.
  const repair = await waitForThreadLoad();
  await resolveThreadLoad(repair, [dto('msg-existing', 'earlier turn')]);
  await waitFor(() => { expect(transcriptIds()).toEqual(['msg-existing']); });
}

describe('BF-720 a delivered report reaches the transcript', () => {
  it('renders the report when nothing else happens during the fetch', async () => {
    await mountWithSeededTranscript();

    act(() => { useStore.getState().handleEvent(reportAppended(1)); });
    const refresh = await waitForThreadLoad();
    await resolveThreadLoad(refresh, [
      dto('msg-existing', 'earlier turn'),
      dto(REPORT_ID, 'work item complete'),
    ]);

    await waitFor(() => {
      expect(transcriptIds()).toEqual(['msg-existing', REPORT_ID]);
    });
  });

  // THE REPRODUCTION. Every gate the spec listed is passed. The ship simply
  // stayed busy while the transcript was in flight -- which is exactly what a
  // ship does at the moment a work item finishes and its report is promoted.
  it('renders the report even when an unrelated live frame lands during the fetch', async () => {
    await mountWithSeededTranscript();

    act(() => { useStore.getState().handleEvent(reportAppended(1)); });
    const refresh = await waitForThreadLoad();

    // An agent changed state while the transcript was being fetched.
    act(() => { useStore.getState().handleEvent(unrelatedLiveFrame(2)); });
    expect(useStore.getState().liveSequence).toBe(2);

    await resolveThreadLoad(refresh, [
      dto('msg-existing', 'earlier turn'),
      dto(REPORT_ID, 'work item complete'),
    ]);

    await waitFor(() => {
      expect(transcriptIds()).toEqual(['msg-existing', REPORT_ID]);
    });
  });

  it('leaves no stale_transcript drop when the ship is busy during the fetch', async () => {
    await mountWithSeededTranscript();
    useStore.setState({ liveDropCount: 0, liveDrops: [] });

    act(() => { useStore.getState().handleEvent(reportAppended(1)); });
    const refresh = await waitForThreadLoad();
    act(() => { useStore.getState().handleEvent(unrelatedLiveFrame(2)); });
    await resolveThreadLoad(refresh, [
      dto('msg-existing', 'earlier turn'),
      dto(REPORT_ID, 'work item complete'),
    ]);

    await waitFor(() => { expect(transcriptIds()).toContain(REPORT_ID); });
    expect(
      useStore.getState().liveDrops.filter((d) => d.gate === 'stale_transcript'),
    ).toEqual([]);
  });
});

describe('BF-720 safety: a transcript fetched under dead authority is still discarded', () => {
  it('discards the result when the generation changed during the fetch', async () => {
    await mountWithSeededTranscript();
    useStore.setState({ liveDropCount: 0, liveDrops: [] });

    act(() => { useStore.getState().handleEvent(reportAppended(1)); });
    const refresh = await waitForThreadLoad();

    // The socket dropped mid-fetch: authority is gone until a snapshot returns.
    act(() => { useStore.setState({ liveGeneration: null }); });

    await resolveThreadLoad(refresh, [
      dto('msg-existing', 'earlier turn'),
      dto(REPORT_ID, 'work item complete'),
    ]);

    expect(transcriptIds()).toEqual(['msg-existing']);
    expect(
      useStore.getState().liveDrops.some(
        (d) => d.gate === 'stale_transcript' && d.detail === 'generation_changed',
      ),
    ).toBe(true);
  });

  it('records a drop when the transcript fetch itself fails', async () => {
    await mountWithSeededTranscript();
    useStore.setState({ liveDropCount: 0, liveDrops: [] });

    act(() => { useStore.getState().handleEvent(reportAppended(1)); });
    const refresh = await waitForThreadLoad();
    refresh.settled = true;
    await act(async () => {
      refresh.resolve({ ok: false, status: 503 } as Response);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(transcriptIds()).toEqual(['msg-existing']);
    await waitFor(() => {
      expect(
        useStore.getState().liveDrops.some(
          (d) => d.gate === 'stale_transcript' && d.detail === 'fetch_failed',
        ),
      ).toBe(true);
    });
  });
});
