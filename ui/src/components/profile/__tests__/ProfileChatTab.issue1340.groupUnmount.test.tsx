/** #1340 — the unmount flush has to be keyed on the SURFACE, not the speaker.
 *
 *  Retiring the BF-764 drain moved end-of-life onto the arbiter's
 *  `flushSpeechQueue`, and the first wiring scoped that flush by the mounted
 *  tab's `agentId`. Queued entries are not tagged with the mounted agent: the
 *  arrivals effect enqueues with `msg.authorId || agentId`, and in a room with
 *  more than one speaker the AD-936/AD-938 fan-out writes a PER-AGENT
 *  `authorId` into the host tab's transcript. So a peer-authored utterance sat
 *  in the queue under a key the flush never looked at, the Captain navigated
 *  away, and the backlog kept talking -- the exact regression the wiring exists
 *  to prevent.
 *
 *  Runs against the REAL `audio/voice`, because the queue whose end-of-life is
 *  under test IS that module. A mocked `speakResponse` would prove only that
 *  the mock was called; the assertion here is on `speechSynthesis.speak` --
 *  what actually reached the audio device.
 *
 *  The room is a live call whose roster has not fully loaded, which is what
 *  makes it a real production shape rather than a contrivance: the peer is a
 *  thread participant the store does not yet know as crew, so
 *  `defersToMeetingSequencer` (>= 2 KNOWN crew participants) is false and the
 *  arrivals effect narrates each reply in its author's voice.
 */
import {
  act, cleanup, render, waitFor, type RenderResult,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  startListening: vi.fn(),
  stopListening: vi.fn(),
  armConversationMode: vi.fn(() => () => {}),
  disarmConversationMode: vi.fn(),
  markAgentReplyComplete: vi.fn(),
  speakMeetingReplies: vi.fn(),
  startCameraStream: vi.fn(async () => undefined),
  stopCameraStream: vi.fn(async () => undefined),
}));

// `audio/voice` is deliberately NOT mocked -- see the header.
vi.mock('../../../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => true,
  startListening: mocks.startListening,
  stopListening: mocks.stopListening,
}));
vi.mock('../../../audio/conversationController', () => ({
  armConversationMode: mocks.armConversationMode,
  disarmConversationMode: mocks.disarmConversationMode,
  markAgentReplyComplete: mocks.markAgentReplyComplete,
}));
vi.mock('../../../audio/transformersStt', () => ({
  armTransformersStt: vi.fn(),
  disarmTransformersStt: vi.fn(),
  onTransformersTranscript: vi.fn(() => () => {}),
  onTransformersTranscribing: vi.fn(() => () => {}),
  onTransformersProgress: vi.fn(() => () => {}),
}));
vi.mock('../../../audio/useMeetingVoice', () => ({
  useMeetingVoice: () => ({ speakReplies: mocks.speakMeetingReplies, speakingAgentId: null }),
}));
vi.mock('../../../hooks/useCameraStream', () => ({
  startCameraStream: mocks.startCameraStream,
  stopCameraStream: mocks.stopCameraStream,
}));
vi.mock('../MeetingView', () => ({ MeetingView: () => <div data-testid="meeting-view-stub" /> }));
vi.mock('../../workspace/WorkspaceFilesRail', () => ({
  WorkspaceFilesRail: () => <aside data-testid="workspace-files-stub" />,
}));

import { ProfileChatTab } from '../ProfileChatTab';
import { useStore } from '../../../store/useStore';
import { speakResponse, _resetTtsStatusForTests } from '../../../audio/voice';
import type { Agent } from '../../../store/types';

const AGENT_ID = 'i1340-host';
/** A second speaker in the room. Its replies are written into the HOST tab's
 *  transcript carrying its own `authorId` -- the key the flush used to miss. */
const PEER_ID = 'i1340-peer';
const THREAD_ID = 'i1340-thread';
const TTS_KEY = `hxi_chat_tts_${AGENT_ID}`;

let speakCalls: FakeUtterance[] = [];

class FakeUtterance {
  text: string;
  rate = 1; pitch = 1; volume = 1;
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(text: string) { this.text = text; }
}

function installSpeechEngine(): void {
  speakCalls = [];
  (globalThis as any).SpeechSynthesisUtterance = FakeUtterance;
  (globalThis as any).speechSynthesis = {
    cancel: vi.fn(() => { for (const u of speakCalls) u.onerror?.(); }),
    speak: vi.fn((u: FakeUtterance) => { speakCalls.push(u); u.onstart?.(); }),
    getVoices: () => [],
    addEventListener: vi.fn(),
  };
}

/** What actually reached the audio device, in dispatch order. */
function deviceTexts(): string[] {
  return speakCalls.map((u) => u.text);
}

/** End whatever the device is currently playing, releasing the arbiter. */
async function endDevice(index: number): Promise<void> {
  await act(async () => {
    speakCalls[index].onend?.();
    await Promise.resolve();
  });
  await act(async () => { await Promise.resolve(); });
}

let serverMessages: Array<Record<string, unknown>>;

function response(body: unknown): Response {
  const serialised = JSON.stringify(body);
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(JSON.parse(serialised)),
    text: () => Promise.resolve(serialised),
  } as Response;
}

function mkAgent(id: string, callsign: string): Agent {
  return {
    id, agentType: 'crew', callsign, displayName: '', pool: 'bridge', state: 'active',
    confidence: 1, trust: 0.5, tier: 'domain', isCrew: true, position: [0, 0, 0],
    department: 'science',
  } as Agent;
}

function serverMsg(id: string, body: string, authorId: string) {
  return {
    id, thread_id: THREAD_ID, author_id: authorId, role: 'agent', body,
    created_at: 1_700_000_000, metadata: {},
  };
}

function installNetwork(): void {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    if (url === '/api/voice/health') {
      return Promise.resolve(response({
        primary_stt: 'browser', engine: 'browser', backend_available: true, healthy: true,
      }));
    }
    // Keep voice.ts on the synchronous browser fallback: no Piper, no POST.
    if (url.endsWith('/api/avatars/tts/status')) {
      return Promise.resolve(response({ enabled: false, backend: 'browser' }));
    }
    if (url.endsWith('/chat/history')) return Promise.resolve(response({ memories: [] }));
    if (url.endsWith('/profile')) {
      return Promise.resolve(response({
        voiceProfile: { voice_name: 'test', pitch: 1, rate: 1, volume: 1 },
      }));
    }
    if (/\/api\/threads\/[^/?]+\/messages\?limit=200$/.test(url) && method === 'GET') {
      return Promise.resolve(response({ thread_id: THREAD_ID, messages: serverMessages }));
    }
    return Promise.resolve(response({}));
  }));
}

/** A live call in a room with a peer the roster has not resolved as crew.
 *  `callAudioEnabled` is what `isOutputAudioEnabledNow` consults for EVERY
 *  speaker once the call is live, which is why the peer's reply is audible at
 *  all. */
function seed(): void {
  localStorage.setItem(TTS_KEY, '1');
  useStore.setState({
    activeProfileAgent: AGENT_ID,
    activeProfileThreadId: null,
    agents: new Map([[AGENT_ID, mkAgent(AGENT_ID, 'Host')]]),
    agentConversations: new Map(),
    threadIdByAgent: new Map([[AGENT_ID, THREAD_ID]]),
    chatThreads: new Map([[THREAD_ID, {
      id: THREAD_ID,
      title: THREAD_ID,
      participants: ['captain', AGENT_ID, PEER_ID],
      created_at: 1,
      last_active_at: 1,
      metadata: { is_default: true, meeting_active: true },
    }]]) as never,
    threadMessages: new Map(),
    callAudioEnabled: true,
    meetingChatVisible: true,
    typingAgent: null,
    voiceEnabled: true,
  });
}

async function mount(): Promise<RenderResult> {
  let view!: RenderResult;
  await act(async () => {
    view = render(<ProfileChatTab agentId={AGENT_ID} />);
    await Promise.resolve();
  });
  await waitFor(() => {
    expect(useStore.getState().threadMessages.has(THREAD_ID)).toBe(true);
  });
  await act(async () => { await Promise.resolve(); });
  return view;
}

/** SEVERAL arrivals admitted by ONE refresh, so the second is still queued
 *  behind the first when the tab goes away. */
async function serverPushesBurst(...rows: Array<[string, string]>): Promise<void> {
  let lastId = '';
  for (const [body, authorId] of rows) {
    lastId = `pushed-${serverMessages.length}`;
    serverMessages.push(serverMsg(lastId, body, authorId));
  }
  await act(async () => {
    useStore.setState({ liveThreadRefresh: { threadId: THREAD_ID, requestId: lastId } });
    await Promise.resolve();
  });
  await waitFor(() => {
    const rendered = useStore.getState().threadMessages.get(THREAD_ID) ?? [];
    expect(rendered.some((m) => m.text === rows[rows.length - 1][0])).toBe(true);
  });
  await act(async () => { await Promise.resolve(); });
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  serverMessages = [];
  installSpeechEngine();
  installNetwork();
  _resetTtsStatusForTests();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('#1340 — an unmounting tab drops the backlog it queued, whoever spoke it', () => {
  it('queues the peer-authored reply behind the host reply while mounted', async () => {
    // THE PREMISE, asserted on its own so the unmount test below cannot pass
    // vacuously. If the peer's reply never reached the queue -- wrong audio
    // gate, wrong deferral predicate, claim collision -- then "nothing further
    // reached the device after unmount" would be true for reasons that have
    // nothing to do with the flush.
    seed();
    await mount();

    await serverPushesBurst(
      ['HOST SPEAKS.', AGENT_ID],
      ['PEER SPEAKS.', PEER_ID],
    );

    // The peer's row is in the transcript under ITS OWN author id, which is the
    // id the arrivals effect hands to `speakResponse`.
    const rendered = useStore.getState().threadMessages.get(THREAD_ID) ?? [];
    expect(rendered.find((m) => m.text === 'PEER SPEAKS.')?.authorId).toBe(PEER_ID);

    // One at a time: the peer's utterance is QUEUED, not dispatched.
    await waitFor(() => expect(deviceTexts()).toEqual(['HOST SPEAKS.']));

    // Released, it speaks -- so there was a real backlog to leak.
    await endDevice(0);
    await waitFor(() => expect(deviceTexts()).toEqual(['HOST SPEAKS.', 'PEER SPEAKS.']));
  });

  it('speaks nothing more once the tab unmounts, even for a peer-authored entry', async () => {
    seed();
    const view = await mount();

    await serverPushesBurst(
      ['HOST SPEAKS.', AGENT_ID],
      ['PEER SPEAKS.', PEER_ID],
    );
    await waitFor(() => expect(deviceTexts()).toEqual(['HOST SPEAKS.']));

    view.unmount();
    // Releasing the in-flight utterance is what lets the backlog through. The
    // flush had to have dropped it BEFORE this point; nothing after unmount can.
    await endDevice(0);
    await act(async () => { await Promise.resolve(); });

    expect(deviceTexts()).toEqual(['HOST SPEAKS.']);
  });

  it('leaves a sibling surface\'s queued utterance alone on the way out', async () => {
    // The other half of the same contract, and the reason the flush cannot
    // simply be widened to "drop everything": there is ONE device and several
    // producers on it. `IntentSurface` is mounted for the whole session and
    // passes no owner at all, so an unscoped flush from this tab's unmount
    // would silence the Ship's Computer mid-backlog.
    seed();
    const view = await mount();

    await serverPushesBurst(
      ['HOST SPEAKS.', AGENT_ID],
      ['PEER SPEAKS.', PEER_ID],
    );
    await waitFor(() => expect(deviceTexts()).toEqual(['HOST SPEAKS.']));

    // A producer that is not this surface, queued behind the same utterance.
    await act(async () => {
      speakResponse('SHIPS COMPUTER.');
      await Promise.resolve();
    });
    expect(deviceTexts()).toEqual(['HOST SPEAKS.']);

    view.unmount();
    await endDevice(0);

    // Mine dropped, theirs spoken.
    await waitFor(() => expect(deviceTexts()).toEqual(['HOST SPEAKS.', 'SHIPS COMPUTER.']));
  });

  it('does not drop a second surface showing the SAME agent', async () => {
    // Why the owner key is minted per MOUNT rather than taken from `agentId`.
    // Three call sites render this tab (AgentProfilePanel, CompactApp,
    // MobileShell) and a single mount can be re-pointed at another agent
    // without remounting, so an agent id is neither unique to a surface nor
    // stable across its life. Two surfaces on the same agent must still be two
    // owners, or one leaving silences the other.
    seed();
    let staying!: RenderResult;
    let leaving!: RenderResult;
    await act(async () => {
      staying = render(<ProfileChatTab agentId={AGENT_ID} />);
      leaving = render(<ProfileChatTab agentId={AGENT_ID} />);
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(useStore.getState().threadMessages.has(THREAD_ID)).toBe(true);
    });
    await act(async () => { await Promise.resolve(); });

    // Whichever surface wins the BF-718 claim queues BOTH arrivals; the point
    // is only that the backlog belongs to a surface that is not unmounting.
    await serverPushesBurst(
      ['HOST SPEAKS.', AGENT_ID],
      ['PEER SPEAKS.', PEER_ID],
    );
    await waitFor(() => expect(deviceTexts()).toEqual(['HOST SPEAKS.']));

    leaving.unmount();
    await endDevice(0);

    await waitFor(() => expect(deviceTexts()).toEqual(['HOST SPEAKS.', 'PEER SPEAKS.']));
    staying.unmount();
  });
});
