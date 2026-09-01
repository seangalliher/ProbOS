/** AD-1291 (BF-858) — the two end-to-end spans the arbiter has to satisfy.
 *
 *  These run against the REAL `audio/voice` module. Every other ProfileChatTab
 *  speech test mocks it, which is right for their subject but useless for this
 *  one: the serialisation under test IS that module, so a mocked
 *  `speakResponse` would prove only that the mock was called.
 *
 *  "The device" here means `speechSynthesis.speak` -- what actually reaches the
 *  audio output -- not what some producer asked for.
 *
 *  BOTH spans assert NON-OVERLAP, not order. That distinction is the whole
 *  point: the pre-fix cascade produced the SAME final order. `voice.ts` emitted
 *  the terminal 'end' carrying the SUPERSEDED utterance's id (BF-767), and the
 *  BF-764 drain correlates on exactly that id, so a foreign producer's cancel
 *  resolved the drain and ADVANCED it -- each utterance cancelling the last
 *  while the transcript still ended up in the right sequence. An acceptance
 *  test that checked only the final array would pass against the unfixed code.
 */
import {
  act, cleanup, fireEvent, render, screen, waitFor, type RenderResult,
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

// `audio/voice` is deliberately NOT mocked.
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
import { IntentSurface } from '../../IntentSurface';
import { useStore } from '../../../store/useStore';
import { _resetTtsStatusForTests } from '../../../audio/voice';
import type { Agent } from '../../../store/types';

const AGENT_ID = 'ad1291-host';
const THREAD_ID = 'ad1291-thread';
const TTS_KEY = `hxi_chat_tts_${AGENT_ID}`;

let createdUtterances: FakeUtterance[] = [];
let speakCalls: FakeUtterance[] = [];

class FakeUtterance {
  text: string;
  rate = 1; pitch = 1; volume = 1;
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(text: string) {
    this.text = text;
    createdUtterances.push(this);
  }
}

function installSpeechEngine(): void {
  createdUtterances = [];
  speakCalls = [];
  (globalThis as any).SpeechSynthesisUtterance = FakeUtterance;
  (globalThis as any).speechSynthesis = {
    cancel: vi.fn(),
    speak: vi.fn((u: FakeUtterance) => { speakCalls.push(u); u.onstart?.(); }),
    getVoices: () => [],
    addEventListener: vi.fn(),
  };
}

/** What reached the audio device, in dispatch order. */
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
let sendReply: string;
let intentReply: string;

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

function serverMsg(id: string, body: string) {
  return {
    id, thread_id: THREAD_ID, author_id: AGENT_ID, role: 'agent', body,
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
    if (url === `/api/agent/${AGENT_ID}/chat` && method === 'POST') {
      return Promise.resolve(response({ response: sendReply }));
    }
    if (url === '/api/chat' && method === 'POST') {
      return Promise.resolve(response({ response: intentReply }));
    }
    return Promise.resolve(response({}));
  }));
}

function seed(): void {
  localStorage.setItem(TTS_KEY, '1');
  useStore.setState({
    activeProfileAgent: AGENT_ID,
    activeProfileThreadId: null,
    agents: new Map([[AGENT_ID, mkAgent(AGENT_ID, 'Host')]]),
    agentConversations: new Map(),
    threadIdByAgent: new Map([[AGENT_ID, THREAD_ID]]),
    chatThreads: new Map([[THREAD_ID, {
      id: THREAD_ID, title: THREAD_ID, participants: ['captain', AGENT_ID],
      created_at: 1, last_active_at: 1, metadata: { is_default: true },
    }]]) as never,
    threadMessages: new Map(),
    chatHistory: [],
    activeDag: [],
    pendingRequests: 0,
    callAudioEnabled: true,
    meetingChatVisible: true,
    typingAgent: null,
    voiceEnabled: true,
  });
}

async function mount(node: React.ReactElement): Promise<RenderResult> {
  let view!: RenderResult;
  await act(async () => {
    view = render(node);
    await Promise.resolve();
  });
  await waitFor(() => {
    expect(useStore.getState().threadMessages.has(THREAD_ID)).toBe(true);
  });
  await act(async () => { await Promise.resolve(); });
  return view;
}

/** The defect's shape: SEVERAL arrivals admitted by ONE refresh. */
async function serverPushesBurst(...bodies: string[]): Promise<void> {
  let lastId = '';
  for (const body of bodies) {
    lastId = `pushed-${serverMessages.length}`;
    serverMessages.push(serverMsg(lastId, body));
  }
  await act(async () => {
    useStore.setState({ liveThreadRefresh: { threadId: THREAD_ID, requestId: lastId } });
    await Promise.resolve();
  });
  await waitFor(() => {
    const rendered = useStore.getState().threadMessages.get(THREAD_ID) ?? [];
    expect(rendered.some((m) => m.text === bodies[bodies.length - 1])).toBe(true);
  });
  await act(async () => { await Promise.resolve(); });
}

/** Drive the real composer, which is the send-path producer. */
async function captainSends(text: string): Promise<void> {
  const input = screen.getByPlaceholderText('Message...');
  fireEvent.change(input, { target: { value: text } });
  await act(async () => {
    fireEvent.keyDown(input, { key: 'Enter' });
    await Promise.resolve();
  });
  await act(async () => { await Promise.resolve(); });
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  serverMessages = [];
  sendReply = 'SEND PATH REPLY.';
  intentReply = 'SHIPS COMPUTER REPLY.';
  installSpeechEngine();
  installNetwork();
  _resetTtsStatusForTests();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('AD-1291 span 1 — arrivals and the send path share one device', () => {
  it('holds the send reply off the device until the arrival in flight ends', async () => {
    seed();
    await mount(<ProfileChatTab agentId={AGENT_ID} />);

    // PREMISE, asserted before anything else: the arbiter must actually be
    // parked mid-utterance. An arbiter that never parked would make every
    // assertion below pass vacuously.
    await serverPushesBurst('ARRIVAL ONE.', 'ARRIVAL TWO.');
    await waitFor(() => expect(deviceTexts()).toEqual(['ARRIVAL ONE.']));

    // A SECOND producer fires while ARRIVAL ONE is still in flight. Pre-fix
    // this reached the device immediately and cancelled it.
    await captainSends('captain speaks');
    expect(deviceTexts()).toEqual(['ARRIVAL ONE.']);

    // NON-OVERLAP: snapshot the device immediately before releasing each
    // utterance, so the next one is proven to start only afterwards.
    const beforeFirstEnd = speakCalls.length;
    await endDevice(0);
    expect(beforeFirstEnd).toBe(1);
    await waitFor(() => expect(deviceTexts()).toEqual(['ARRIVAL ONE.', 'ARRIVAL TWO.']));

    const beforeSecondEnd = speakCalls.length;
    await endDevice(1);
    expect(beforeSecondEnd).toBe(2);
    await waitFor(() => expect(deviceTexts()).toEqual([
      'ARRIVAL ONE.', 'ARRIVAL TWO.', 'SEND PATH REPLY.',
    ]));

    // #1340: this used to expect 'SEND PATH REPLY.' in the MIDDLE, and read
    // that position as proof the second producer was the send path rather than
    // the drain. It was really pinning an artefact OF the drain, which withheld
    // 'ARRIVAL TWO.' from the arbiter until 'ARRIVAL ONE.' ended -- so a
    // request the Captain made later overtook an arrival that had already
    // landed. With the drain retired the arbiter is FIFO by enqueue across all
    // producers, and both arrivals -- admitted by one refresh, before the
    // Captain typed -- correctly precede the reply. The text is the
    // discriminator now: only the send round trip says 'SEND PATH REPLY.'.
    expect(speechSynthesis.cancel).toHaveBeenCalled();
  });

  it('never lets two utterances hold the device at once', async () => {
    // The cascade's signature was that every utterance still arrived, in the
    // right order, each cancelling the last. So assert the property the order
    // cannot see: at most one utterance is unfinished at any moment.
    seed();
    await mount(<ProfileChatTab agentId={AGENT_ID} />);

    await serverPushesBurst('ARRIVAL ONE.', 'ARRIVAL TWO.');
    await waitFor(() => expect(deviceTexts()).toEqual(['ARRIVAL ONE.']));
    await captainSends('captain speaks');

    let ended = 0;
    for (let guard = 0; guard < 3; guard += 1) {
      // Every utterance the device has been handed so far must have been
      // released by us -- i.e. nothing started on top of a live one.
      expect(speakCalls.length).toBe(ended + 1);
      await endDevice(ended);
      ended += 1;
      if (speakCalls.length === ended) break;
    }
    // #1340: order updated with the sibling assertion above -- the drain used
    // to delay 'ARRIVAL TWO.' behind the send reply. The property this test
    // actually owns, one unfinished utterance at a time, is the loop above.
    expect(deviceTexts()).toEqual(['ARRIVAL ONE.', 'ARRIVAL TWO.', 'SEND PATH REPLY.']);
  });
});

describe('AD-1291 span 2 — a sibling component cannot cut in', () => {
  it("queues the Ship's Computer behind a crew utterance", async () => {
    // IntentSurface is mounted at App.tsx:113 for the WHOLE session, beside
    // ProfileChatTab, and its Ship's Computer reply carries no agent_id. This
    // is the span a component-level queue fails by construction: a queue
    // living inside the chat component cannot see a sibling's producer, and
    // both reach the same module-level device state in voice.ts.
    seed();
    await mount(
      <>
        <ProfileChatTab agentId={AGENT_ID} />
        <IntentSurface />
      </>,
    );

    await serverPushesBurst('CREW UTTERANCE.');
    await waitFor(() => expect(deviceTexts()).toEqual(['CREW UTTERANCE.']));

    // Ask the Ship's Computer while the crew member is still speaking.
    const pill = screen.queryByText(/Ask ProbOS/)?.closest('div');
    if (pill) fireEvent.click(pill);
    const intentInput = document.querySelector(
      'input[placeholder="Ask ProbOS..."]',
    ) as HTMLInputElement | null;
    if (intentInput === null) throw new Error('IntentSurface input not rendered');
    fireEvent.change(intentInput, { target: { value: 'status report' } });
    await act(async () => {
      fireEvent.submit(intentInput.closest('form')!);
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(useStore.getState().chatHistory.some((m) => m.text === intentReply)).toBe(true);
    });
    await act(async () => { await Promise.resolve(); });

    // Pre-fix this cancelled the crew utterance mid-sentence.
    const beforeEnd = speakCalls.length;
    expect(deviceTexts()).toEqual(['CREW UTTERANCE.']);
    expect(beforeEnd).toBe(1);

    await endDevice(0);
    await waitFor(() => expect(deviceTexts()).toEqual(['CREW UTTERANCE.', intentReply]));
  });
});
