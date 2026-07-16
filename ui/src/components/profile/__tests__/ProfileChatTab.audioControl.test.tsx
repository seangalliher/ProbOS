/** BF-671: mounted output-audio ownership and live speech-boundary regressions.
 *
 * Mounts the real ProfileChatTab against the real Zustand store/localStorage.
 * Audio/controller/network edges are narrow mocks; scope selection, component
 * state, thread resolution, group reveal, and composer behavior remain the
 * production implementation.
 */
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  type RenderResult,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  speakResponse: vi.fn(),
  onSpeechEvent: vi.fn(() => () => {}),
  startListening: vi.fn(),
  stopListening: vi.fn(),
  armConversationMode: vi.fn(() => () => {}),
  disarmConversationMode: vi.fn(),
  markAgentReplyComplete: vi.fn(),
  speakMeetingReplies: vi.fn(),
  startCameraStream: vi.fn(async () => undefined),
  stopCameraStream: vi.fn(async () => undefined),
}));

vi.mock('../../../audio/voice', () => ({
  getServerPiperVoices: vi.fn(async () => null),
  speakResponse: mocks.speakResponse,
  stripMarkdownForSpeech: (text: string) => text,
  onSpeechEvent: mocks.onSpeechEvent,
  prewarmTts: vi.fn(),
}));

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
  useMeetingVoice: () => ({
    speakReplies: mocks.speakMeetingReplies,
    speakingAgentId: null,
  }),
}));

vi.mock('../../../hooks/useCameraStream', () => ({
  startCameraStream: mocks.startCameraStream,
  stopCameraStream: mocks.stopCameraStream,
}));

vi.mock('../MeetingView', () => ({
  MeetingView: () => <div data-testid="meeting-view-stub" />,
}));

vi.mock('../../workspace/WorkspaceFilesRail', () => ({
  WorkspaceFilesRail: () => <aside data-testid="workspace-files-stub" />,
}));

import { ProfileChatTab } from '../ProfileChatTab';
import profileChatSource from '../ProfileChatTab.tsx?raw';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

const AGENT_ID = 'audio-host';
const PEER_ID = 'audio-peer';
const OTHER_AGENT_ID = 'audio-other';
const TTS_KEY = `hxi_chat_tts_${AGENT_ID}`;
const OTHER_TTS_KEY = `hxi_chat_tts_${OTHER_AGENT_ID}`;
const MIC_KEY = `hxi_chat_mic_mode_${AGENT_ID}`;
const EMOJI_RE = /\p{Extended_Pictographic}/u;

type MockArmOptions = {
  agentId: string;
  onAgentReply?: (text: string) => void;
  submitTranscript?: (text: string) => Promise<void>;
};

type MockArmRecord = {
  index: number;
  opts: MockArmOptions;
  disposer: ReturnType<typeof vi.fn<() => void>>;
};

type JsonValue = Record<string, unknown>;
type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

type NetworkPlan = {
  greetingJson: Promise<JsonValue> | null;
  chatJson: Promise<JsonValue> | null;
  groupReplies: Array<{ agent_id: string; callsign: string; text: string }>;
};

let network: NetworkPlan;
let armRecords: MockArmRecord[];
let currentArmRecord: MockArmRecord | null;

function installOwnerRecordingArmMock(): void {
  armRecords = [];
  currentArmRecord = null;
  (mocks.armConversationMode as unknown as {
    mockImplementation: (implementation: (opts: MockArmOptions) => () => void) => void;
  }).mockImplementation((opts: MockArmOptions) => {
    let record!: MockArmRecord;
    const disposer = vi.fn<() => void>(() => {
      if (currentArmRecord === record) currentArmRecord = null;
    });
    record = { index: armRecords.length, opts, disposer };
    armRecords.push(record);
    currentArmRecord = record;
    return disposer;
  });
  mocks.disarmConversationMode.mockImplementation(() => {
    currentArmRecord = null;
  });
}

function requireCurrentArm(): MockArmRecord {
  if (currentArmRecord === null) throw new Error('expected a current conversation owner');
  return currentArmRecord;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

async function renderProfileChat(
  props: { agentId: string; threadId?: string },
): Promise<RenderResult> {
  let view!: RenderResult;
  await act(async () => {
    view = render(<ProfileChatTab {...props} />);
    await Promise.resolve();
  });
  return view;
}

async function rerenderProfileChat(
  view: RenderResult,
  props: { agentId: string; threadId?: string },
): Promise<void> {
  await act(async () => {
    view.rerender(<ProfileChatTab {...props} />);
    await Promise.resolve();
  });
}

function response(body: JsonValue | Promise<JsonValue>): Response {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as Response;
}

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
    position: [0, 0, 0],
    department: 'science',
  } as Agent;
}

function mkThread(
  id: string,
  participants: string[],
  meetingActive = false,
): AD791aChatThreadView {
  return {
    id,
    title: id,
    participants,
    created_at: 1,
    last_active_at: 1,
    metadata: {
      ...(participants.length === 2 ? { is_default: true } : {}),
      ...(meetingActive ? { meeting_active: true } : {}),
    },
  };
}

function installNetwork(): void {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';

    if (url === '/api/voice/health') {
      return Promise.resolve(response({
        primary_stt: 'browser',
        engine: 'browser',
        backend_available: true,
        healthy: true,
      }));
    }
    if (url.endsWith('/chat/history')) return Promise.resolve(response({ memories: [] }));
    if (url.endsWith('/profile')) {
      return Promise.resolve(response({
        voiceProfile: { voice_name: 'test', pitch: 1, rate: 1, volume: 1 },
      }));
    }
    if (/\/api\/threads\/[^/?]+\/messages\?limit=200$/.test(url) && method === 'GET') {
      const threadId = decodeURIComponent(url.match(/\/api\/threads\/([^/?]+)/)?.[1] ?? '');
      return Promise.resolve(response({ thread_id: threadId, messages: [] }));
    }
    if (/\/api\/threads\/[^/?]+$/.test(url) && method === 'PATCH') {
      const threadId = decodeURIComponent(url.match(/\/api\/threads\/([^/?]+)$/)?.[1] ?? '');
      const body = JSON.parse(String(init?.body ?? '{}')) as { meeting_active?: boolean };
      const current = useStore.getState().chatThreads.get(threadId) ?? mkThread(threadId, []);
      return Promise.resolve(response({
        ...current,
        metadata: {
          ...(current.metadata ?? {}),
          meeting_active: body.meeting_active === true,
        },
      }));
    }
    if (/\/api\/threads\/[^/?]+\/messages$/.test(url) && method === 'POST') {
      const threadId = decodeURIComponent(url.match(/\/api\/threads\/([^/?]+)/)?.[1] ?? '');
      return Promise.resolve(response({
        id: 'group-response',
        thread_id: threadId,
        per_agent_replies: network.groupReplies,
      }));
    }
    if (url === `/api/agent/${AGENT_ID}/chat` && method === 'POST') {
      const body = JSON.parse(String(init?.body ?? '{}')) as { system_trigger?: boolean; thread_id?: string };
      if (body.system_trigger) {
        return Promise.resolve(response(
          network.greetingJson ?? Promise.resolve({ response: 'Greeting response.' }),
        ));
      }
      return Promise.resolve(response(
        network.chatJson ?? Promise.resolve({
          response: 'Typed response.',
          thread_id: body.thread_id,
        }),
      ));
    }
    return Promise.resolve(response({}));
  }));
}

function resetStore(): void {
  useStore.setState({
    activeProfileAgent: null,
    activeProfileThreadId: null,
    activeThreadId: null,
    agents: new Map(),
    agentConversations: new Map(),
    threadIdByAgent: new Map(),
    chatThreads: new Map(),
    threadMessages: new Map(),
    artifactsByThread: new Map(),
    selectedArtifactId: null,
    meetingChatVisible: true,
    callAudioEnabled: true,
    typingAgent: null,
    voiceEnabled: false,
    chatDrafts: {},
  });
}

function seed(
  thread: AD791aChatThreadView,
  opts: { tts: boolean; callAudio: boolean; conversation?: boolean },
): void {
  localStorage.setItem(TTS_KEY, opts.tts ? '1' : '0');
  if (opts.conversation) localStorage.setItem(MIC_KEY, 'conversation');
  useStore.setState({
    activeProfileAgent: AGENT_ID,
    activeProfileThreadId: null,
    agents: new Map([
      [AGENT_ID, mkAgent(AGENT_ID, 'Host')],
      [PEER_ID, mkAgent(PEER_ID, 'Peer')],
      [OTHER_AGENT_ID, mkAgent(OTHER_AGENT_ID, 'Other')],
    ]),
    agentConversations: new Map(),
    threadIdByAgent: new Map([[AGENT_ID, thread.id]]),
    chatThreads: new Map([[thread.id, thread]]),
    threadMessages: new Map([[thread.id, []]]),
    callAudioEnabled: opts.callAudio,
    meetingChatVisible: true,
    typingAgent: null,
    voiceEnabled: false,
  });
}

function setMeeting(threadId: string, active: boolean): void {
  const current = useStore.getState().chatThreads.get(threadId);
  if (!current) throw new Error(`missing thread ${threadId}`);
  useStore.getState().setChatThread({
    ...current,
    metadata: { ...(current.metadata ?? {}), meeting_active: active },
  });
}

function outputToggle(): HTMLButtonElement {
  return screen.getByTestId('output-audio-toggle') as HTMLButtonElement;
}

function visibleOutputAudioControls(): HTMLButtonElement[] {
  return screen.getAllByRole('button').filter((button) =>
    /call audio|agent voice/i.test(button.getAttribute('aria-label') ?? ''),
  ) as HTMLButtonElement[];
}

function expectSpeech(text: string, emotion?: string): void {
  expect(mocks.speakResponse.mock.calls.some((call) => (
    call[0] === text
    && call[2] === AGENT_ID
    && (emotion === undefined || call[3] === emotion)
  ))).toBe(true);
}

function hasSpeech(text: string): boolean {
  return mocks.speakResponse.mock.calls.some((call) => (
    call[0] === text && call[2] === AGENT_ID
  ));
}

function sendTyped(text = 'Captain message'): void {
  const input = screen.getByPlaceholderText('Message...');
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key: 'Enter' });
}

async function startAudioCall(): Promise<void> {
  await act(async () => {
    fireEvent.click(screen.getByTestId('call-start'));
    await Promise.resolve();
  });
  await act(async () => {
    fireEvent.click(screen.getByTestId('call-audio'));
    await Promise.resolve();
  });
  await waitFor(() => {
    expect(
      (useStore.getState().chatThreads.get('one-to-one')?.metadata as Record<string, unknown>)
        ?.meeting_active,
    ).toBe(true);
  });
}

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.onSpeechEvent.mockReturnValue(() => {});
  installOwnerRecordingArmMock();
  mocks.startCameraStream.mockResolvedValue(undefined);
  mocks.stopCameraStream.mockResolvedValue(undefined);
  network = { greetingJson: null, chatJson: null, groupReplies: [] };
  localStorage.clear();
  resetStore();
  installNetwork();
  if (!(Element.prototype as unknown as { scrollIntoView?: unknown }).scrollIntoView) {
    Object.defineProperty(Element.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
  }
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.clear();
  resetStore();
});

describe('BF-671 composer scope matrix', () => {
  it.each([
    { name: 'ordinary false ignores call true', tts: false, callAudio: true, pressed: 'false', label: 'Unmute call audio' },
    { name: 'ordinary true ignores call false', tts: true, callAudio: false, pressed: 'true', label: 'Mute call audio' },
  ])('$name', async ({ tts, callAudio, pressed, label }) => {
    const thread = mkThread('one-to-one', ['captain', AGENT_ID]);
    seed(thread, { tts, callAudio });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    const toggle = outputToggle();
    expect(toggle.getAttribute('aria-pressed')).toBe(pressed);
    expect(toggle.getAttribute('aria-label')).toBe(label);
    expect(toggle.getAttribute('title')).toBe(label);
    expect(screen.getAllByTestId('output-audio-toggle')).toHaveLength(1);
    expect(visibleOutputAudioControls()).toHaveLength(1);
  });

  it.each([
    { name: 'active 1:1 uses call true over per-agent false', tts: false, callAudio: true, pressed: 'true' },
    { name: 'active 1:1 uses call false over per-agent true', tts: true, callAudio: false, pressed: 'false' },
  ])('$name', async ({ tts, callAudio, pressed }) => {
    const thread = mkThread('one-to-one', ['captain', AGENT_ID], true);
    seed(thread, { tts, callAudio });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    expect(outputToggle().getAttribute('aria-pressed')).toBe(pressed);
    expect(screen.getAllByTestId('output-audio-toggle')).toHaveLength(1);
    expect(visibleOutputAudioControls()).toHaveLength(1);
    expect(screen.queryByTestId('call-audio-toggle')).toBeNull();
  });

  it.each([
    { name: 'active group uses call true over host false', tts: false, callAudio: true, pressed: 'true' },
    { name: 'active group uses call false over host true', tts: true, callAudio: false, pressed: 'false' },
  ])('$name', async ({ tts, callAudio, pressed }) => {
    const thread = mkThread('group', ['captain', AGENT_ID, PEER_ID], true);
    seed(thread, { tts, callAudio });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    expect(outputToggle().getAttribute('aria-pressed')).toBe(pressed);
    expect(screen.getAllByTestId('output-audio-toggle')).toHaveLength(1);
    expect(visibleOutputAudioControls()).toHaveLength(1);
    expect(screen.queryByTestId('call-audio-toggle')).toBeNull();
  });

  it('ordinary clicks persist only per-agent state and leave call state untouched', async () => {
    const thread = mkThread('one-to-one', ['captain', AGENT_ID]);
    seed(thread, { tts: false, callAudio: true });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    act(() => fireEvent.click(outputToggle()));
    expect(outputToggle().getAttribute('aria-pressed')).toBe('true');
    expect(localStorage.getItem(TTS_KEY)).toBe('1');
    expect(useStore.getState().callAudioEnabled).toBe(true);

    act(() => fireEvent.click(outputToggle()));
    expect(outputToggle().getAttribute('aria-pressed')).toBe('false');
    expect(localStorage.getItem(TTS_KEY)).toBe('0');
    expect(useStore.getState().callAudioEnabled).toBe(true);
  });

  it('active-call clicks update only session call audio and call exit restores untouched per-agent state', async () => {
    const thread = mkThread('one-to-one', ['captain', AGENT_ID]);
    seed(thread, { tts: false, callAudio: true });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    act(() => setMeeting(thread.id, true));
    expect(outputToggle().getAttribute('aria-pressed')).toBe('true');
    act(() => fireEvent.click(outputToggle()));
    expect(useStore.getState().callAudioEnabled).toBe(false);
    expect(localStorage.getItem(TTS_KEY)).toBe('0');

    act(() => setMeeting(thread.id, false));
    expect(outputToggle().getAttribute('aria-pressed')).toBe('false');
    expect(localStorage.getItem(TTS_KEY)).toBe('0');
  });

  it('active-group click changes only call audio and leaves the host preference untouched', async () => {
    const thread = mkThread('group', ['captain', AGENT_ID, PEER_ID], true);
    seed(thread, { tts: true, callAudio: false });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    const storedBefore = localStorage.getItem(TTS_KEY);
    act(() => fireEvent.click(outputToggle()));

    expect(useStore.getState().callAudioEnabled).toBe(true);
    expect(localStorage.getItem(TTS_KEY)).toBe(storedBefore);
    expect(outputToggle().getAttribute('aria-pressed')).toBe('true');
  });

  it('agent switch hydrates the other persisted preference without copying either scope', async () => {
    const first = mkThread('one-to-one', ['captain', AGENT_ID]);
    const second = mkThread('other-one-to-one', ['captain', OTHER_AGENT_ID]);
    seed(first, { tts: false, callAudio: true });
    localStorage.setItem(OTHER_TTS_KEY, '1');
    act(() => useStore.getState().setChatThread(second));
    const view = await renderProfileChat({ agentId: AGENT_ID, threadId: first.id });
    expect(outputToggle().getAttribute('aria-pressed')).toBe('false');

    await rerenderProfileChat(view, { agentId: OTHER_AGENT_ID, threadId: second.id });

    await waitFor(() => expect(outputToggle().getAttribute('aria-pressed')).toBe('true'));
    expect(localStorage.getItem(TTS_KEY)).toBe('0');
    expect(localStorage.getItem(OTHER_TTS_KEY)).toBe('1');
    expect(useStore.getState().callAudioEnabled).toBe(true);
  });

  it('renders the exact accessible amber/dim inline speaker SVG contract with no emoji', async () => {
    const thread = mkThread('one-to-one', ['captain', AGENT_ID]);
    seed(thread, { tts: true, callAudio: false });
    const view = await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    let toggle = outputToggle();
    expect(toggle.getAttribute('aria-label')).toBe('Mute call audio');
    expect(toggle.getAttribute('title')).toBe('Mute call audio');
    expect(toggle.getAttribute('aria-pressed')).toBe('true');
    expect(toggle.style.color).toBe('rgb(240, 176, 96)');
    expect(toggle.style.background).toBe('rgba(240, 176, 96, 0.15)');
    expect(toggle.style.filter).toBe('drop-shadow(0 0 4px #f0b060)');
    const svg = toggle.querySelector('svg');
    expect(svg?.getAttribute('fill')).toBe('none');
    expect(svg?.getAttribute('stroke')).toBe('currentColor');
    expect(svg?.getAttribute('stroke-width')).toBe('1.5');
    expect(svg?.getAttribute('stroke-linecap')).toBe('round');
    expect(svg?.getAttribute('stroke-linejoin')).toBe('round');
    expect(svg?.getAttribute('aria-hidden')).toBe('true');

    act(() => fireEvent.click(toggle));
    toggle = outputToggle();
    expect(toggle.getAttribute('aria-label')).toBe('Unmute call audio');
    expect(toggle.style.color).toBe('rgb(102, 102, 128)');
    expect(toggle.style.background).toBe('transparent');
    expect(toggle.style.filter).toBe('drop-shadow(0 0 2px rgba(102, 102, 128, 0.3))');
    expect(EMOJI_RE.test(view.container.innerHTML)).toBe(false);
  });
});

describe('BF-671 live call greeting boundary', () => {
  it('active 1:1 speaks greeting when call audio is on despite per-agent off', async () => {
    const thread = mkThread('one-to-one', ['captain', AGENT_ID]);
    seed(thread, { tts: false, callAudio: true });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    await startAudioCall();

    await waitFor(() => expectSpeech('Greeting response.'));
  });

  it('active 1:1 appends but does not speak greeting when call audio is off despite per-agent on', async () => {
    const thread = mkThread('one-to-one', ['captain', AGENT_ID]);
    seed(thread, { tts: true, callAudio: false });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    await startAudioCall();

    await waitFor(() => {
      const messages = useStore.getState().agentConversations.get(AGENT_ID)?.messages ?? [];
      expect(messages.some((message) => message.text === 'Greeting response.')).toBe(true);
    });
    expect(mocks.speakResponse).not.toHaveBeenCalled();
  });

  it('reads the latest call state after a deferred greeting response', async () => {
    const pending = deferred<JsonValue>();
    network.greetingJson = pending.promise;
    const thread = mkThread('one-to-one', ['captain', AGENT_ID]);
    seed(thread, { tts: false, callAudio: false });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    await startAudioCall();
    await act(async () => {
      useStore.getState().setCallAudioEnabled(true);
      pending.resolve({ response: 'Deferred greeting.' });
      await Promise.resolve();
    });

    await waitFor(() => expectSpeech('Deferred greeting.'));
  });

  it('falls back to current per-agent state when the call ends before greeting resolves', async () => {
    const pending = deferred<JsonValue>();
    network.greetingJson = pending.promise;
    const thread = mkThread('one-to-one', ['captain', AGENT_ID]);
    seed(thread, { tts: false, callAudio: true });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    await startAudioCall();
    await act(async () => {
      fireEvent.click(screen.getByTestId('call-end'));
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(
        (useStore.getState().chatThreads.get(thread.id)?.metadata as Record<string, unknown>)
          ?.meeting_active,
      ).toBe(false);
    });
    await act(async () => {
      pending.resolve({ response: 'Late greeting.' });
      await Promise.resolve();
    });

    await waitFor(() => {
      const messages = useStore.getState().agentConversations.get(AGENT_ID)?.messages ?? [];
      expect(messages.some((message) => message.text === 'Late greeting.')).toBe(true);
    });
    expect(mocks.speakResponse).not.toHaveBeenCalled();
  });

  it.each([
    { name: 'A off and B on stays silent', aTts: false, bTts: true, speaks: false },
    { name: 'A on and B off speaks', aTts: true, bTts: false, speaks: true },
  ])('deferred greeting after A call ends: $name', async ({ aTts, bTts, speaks }) => {
    const pending = deferred<JsonValue>();
    network.greetingJson = pending.promise;
    const first = mkThread('one-to-one', ['captain', AGENT_ID]);
    const second = mkThread('other-one-to-one', ['captain', OTHER_AGENT_ID]);
    seed(first, { tts: aTts, callAudio: true });
    localStorage.setItem(OTHER_TTS_KEY, bTts ? '1' : '0');
    act(() => {
      useStore.getState().setChatThread(second);
      useStore.getState().setThreadForAgent(OTHER_AGENT_ID, second.id);
    });
    const view = await renderProfileChat({ agentId: AGENT_ID, threadId: first.id });

    await startAudioCall();
    await act(async () => {
      fireEvent.click(screen.getByTestId('call-end'));
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(
        (useStore.getState().chatThreads.get(first.id)?.metadata as Record<string, unknown>)
          ?.meeting_active,
      ).toBe(false);
    });
    await rerenderProfileChat(view, { agentId: OTHER_AGENT_ID, threadId: second.id });
    await act(async () => {
      pending.resolve({ response: 'Late A greeting.' });
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      const messages = useStore.getState().agentConversations.get(AGENT_ID)?.messages ?? [];
      expect(messages.some((message) => message.text === 'Late A greeting.')).toBe(true);
    });
    expect(hasSpeech('Late A greeting.')).toBe(speaks);
    expect(localStorage.getItem(TTS_KEY)).toBe(aTts ? '1' : '0');
    expect(localStorage.getItem(OTHER_TTS_KEY)).toBe(bTts ? '1' : '0');
    expect(useStore.getState().callAudioEnabled).toBe(true);
  });
});

describe('BF-671 live 1:1 send and PTT boundaries', () => {
  it('active 1:1 typed reply speaks when call audio is on despite per-agent off', async () => {
    const thread = mkThread('one-to-one', ['captain', AGENT_ID], true);
    seed(thread, { tts: false, callAudio: true });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    sendTyped();

    await waitFor(() => expectSpeech('Typed response.'));
  });

  it('active 1:1 typed reply appends silently when call audio is off despite per-agent on', async () => {
    const thread = mkThread('one-to-one', ['captain', AGENT_ID], true);
    seed(thread, { tts: true, callAudio: false });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    sendTyped();

    await waitFor(() => {
      const messages = useStore.getState().agentConversations.get(AGENT_ID)?.messages ?? [];
      expect(messages.some((message) => message.text === 'Typed response.')).toBe(true);
    });
    expect(mocks.speakResponse).not.toHaveBeenCalled();
  });

  it('uses response-time call state and the authoritative response thread while a request is pending', async () => {
    const pending = deferred<JsonValue>();
    network.chatJson = pending.promise;
    const requestThread = mkThread('one-to-one', ['captain', AGENT_ID], true);
    const unrelated = mkThread('unrelated-group', ['captain', AGENT_ID, PEER_ID], false);
    seed(requestThread, { tts: false, callAudio: false });
    act(() => useStore.getState().setChatThread(unrelated));
    await renderProfileChat({ agentId: AGENT_ID });

    sendTyped();
    act(() => {
      useStore.getState().setCallAudioEnabled(true);
      useStore.getState().openGroupChatThread(AGENT_ID, unrelated.id);
    });
    await act(async () => {
      pending.resolve({ response: 'Authoritative reply.', thread_id: requestThread.id });
      await Promise.resolve();
    });

    await waitFor(() => expectSpeech('Authoritative reply.'));
  });

  it('PTT submits through the same sendText speech policy', async () => {
    const thread = mkThread('one-to-one', ['captain', AGENT_ID], true);
    seed(thread, { tts: false, callAudio: true });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/voice/health'));

    vi.useFakeTimers();
    act(() => fireEvent.click(screen.getByLabelText('Voice input')));
    const onTranscript = mocks.startListening.mock.calls[0]?.[0] as ((text: string) => void) | undefined;
    expect(onTranscript).toBeTypeOf('function');
    await act(async () => {
      onTranscript?.('PTT message');
      await vi.runAllTimersAsync();
      await Promise.resolve();
    });

    expectSpeech('Typed response.');
  });

  it.each([
    { name: 'A off and B on stays silent', aTts: false, bTts: true, speaks: false },
    { name: 'A on and B off speaks', aTts: true, bTts: false, speaks: true },
  ])('deferred A send after switching to B: $name', async ({ aTts, bTts, speaks }) => {
    const pending = deferred<JsonValue>();
    network.chatJson = pending.promise;
    const first = mkThread('one-to-one', ['captain', AGENT_ID]);
    const second = mkThread('other-one-to-one', ['captain', OTHER_AGENT_ID]);
    seed(first, { tts: aTts, callAudio: true });
    localStorage.setItem(OTHER_TTS_KEY, bTts ? '1' : '0');
    act(() => {
      useStore.getState().setChatThread(second);
      useStore.getState().setThreadForAgent(OTHER_AGENT_ID, second.id);
    });
    const view = await renderProfileChat({ agentId: AGENT_ID, threadId: first.id });

    sendTyped('Deferred A request');
    await rerenderProfileChat(view, { agentId: OTHER_AGENT_ID, threadId: second.id });
    await act(async () => {
      pending.resolve({ response: 'Deferred A reply.', thread_id: first.id });
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      const messages = useStore.getState().agentConversations.get(AGENT_ID)?.messages ?? [];
      expect(messages.some((message) => message.text === 'Deferred A reply.')).toBe(true);
    });
    expect(hasSpeech('Deferred A reply.')).toBe(speaks);
    expect(localStorage.getItem(TTS_KEY)).toBe(aTts ? '1' : '0');
    expect(localStorage.getItem(OTHER_TTS_KEY)).toBe(bTts ? '1' : '0');
    expect(useStore.getState().callAudioEnabled).toBe(true);
  });

  it.each([
    { name: 'live global on speaks', globalVoice: true, bTts: false, speaks: true },
    { name: 'live global off stays silent', globalVoice: false, bTts: true, speaks: false },
  ])('deferred A send with missing A key: $name', async ({ globalVoice, bTts, speaks }) => {
    const pending = deferred<JsonValue>();
    network.chatJson = pending.promise;
    const first = mkThread('one-to-one', ['captain', AGENT_ID]);
    const second = mkThread('other-one-to-one', ['captain', OTHER_AGENT_ID]);
    seed(first, { tts: false, callAudio: true });
    localStorage.setItem(OTHER_TTS_KEY, bTts ? '1' : '0');
    act(() => {
      useStore.getState().setChatThread(second);
      useStore.getState().setThreadForAgent(OTHER_AGENT_ID, second.id);
    });
    const view = await renderProfileChat({ agentId: AGENT_ID, threadId: first.id });

    sendTyped('Missing-key A request');
    localStorage.removeItem(TTS_KEY);
    act(() => useStore.setState({ voiceEnabled: globalVoice }));
    await rerenderProfileChat(view, { agentId: OTHER_AGENT_ID, threadId: second.id });
    await act(async () => {
      pending.resolve({ response: 'Missing-key A reply.', thread_id: first.id });
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      const messages = useStore.getState().agentConversations.get(AGENT_ID)?.messages ?? [];
      expect(messages.some((message) => message.text === 'Missing-key A reply.')).toBe(true);
    });
    expect(hasSpeech('Missing-key A reply.')).toBe(speaks);
    expect(localStorage.getItem(TTS_KEY)).toBeNull();
    expect(localStorage.getItem(OTHER_TTS_KEY)).toBe(bTts ? '1' : '0');
    expect(useStore.getState().callAudioEnabled).toBe(true);
  });
});

describe('BF-671 live conversation-controller callback', () => {
  async function captureOrdinaryReply(
    tts: boolean,
    callAudio: boolean,
  ): Promise<(text: string) => void> {
    const thread = mkThread('one-to-one', ['captain', AGENT_ID]);
    seed(thread, { tts, callAudio, conversation: true });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });
    await waitFor(() => expect(currentArmRecord?.opts.onAgentReply).toBeTypeOf('function'));
    const current = requireCurrentArm();
    expect(current.index).toBe(armRecords.length - 1);
    return current.opts.onAgentReply!;
  }

  it('ordinary enabled reply subscribes before speech and completes on matching end', async () => {
    const onAgentReply = await captureOrdinaryReply(true, false);
    const subscriptionsBefore = mocks.onSpeechEvent.mock.calls.length;
    const unsubscribe = vi.fn();
    mocks.onSpeechEvent.mockReturnValueOnce(unsubscribe);

    act(() => onAgentReply('Ordinary audible.'));

    expectSpeech('Ordinary audible.');
    expect(mocks.onSpeechEvent.mock.invocationCallOrder[subscriptionsBefore])
      .toBeLessThan(mocks.speakResponse.mock.invocationCallOrder[0]);
    expect(mocks.markAgentReplyComplete).not.toHaveBeenCalled();
    const speechCalls = mocks.onSpeechEvent.mock.calls as unknown[][];
    const listener = speechCalls[subscriptionsBefore][0] as
      ((event: { type: string; agent_id?: string }) => void);
    act(() => {
      listener({ type: 'start', agent_id: AGENT_ID });
      listener({ type: 'end', agent_id: OTHER_AGENT_ID });
      listener({ type: 'end', agent_id: AGENT_ID });
    });
    expect(mocks.markAgentReplyComplete).toHaveBeenCalledTimes(1);
    expect(unsubscribe).toHaveBeenCalledTimes(1);
  });

  it('ordinary disabled reply appends and completes immediately without speech subscription', async () => {
    const onAgentReply = await captureOrdinaryReply(false, true);
    const subscriptionsBefore = mocks.onSpeechEvent.mock.calls.length;

    act(() => onAgentReply('Ordinary silent.'));

    expect(mocks.speakResponse).not.toHaveBeenCalled();
    expect(mocks.onSpeechEvent.mock.calls).toHaveLength(subscriptionsBefore);
    expect(mocks.markAgentReplyComplete).toHaveBeenCalledTimes(1);
  });

  it('active-call audible policy invokes the latest current meeting-arm callback', async () => {
    const thread = mkThread('one-to-one', ['captain', AGENT_ID]);
    seed(thread, { tts: false, callAudio: true, conversation: true });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });
    await waitFor(() => expect(currentArmRecord?.opts.onAgentReply).toBeTypeOf('function'));
    const ordinaryOwner = requireCurrentArm();

    act(() => setMeeting(thread.id, true));
    await waitFor(() => expect(currentArmRecord?.opts.submitTranscript).toBeTypeOf('function'));
    const current = requireCurrentArm();
    expect(current).not.toBe(ordinaryOwner);
    expect(current.index).toBe(armRecords.length - 1);
    expect(current.opts.onAgentReply).toBeUndefined();

    await act(async () => {
      await current.opts.submitTranscript?.('Current call turn');
      await Promise.resolve();
    });

    await waitFor(() => expectSpeech('Typed response.'));
  });

  it('active-call muted policy starts from the latest arm callback and reads the live toggle', async () => {
    const pending = deferred<JsonValue>();
    network.chatJson = pending.promise;
    const thread = mkThread('one-to-one', ['captain', AGENT_ID]);
    seed(thread, { tts: true, callAudio: true, conversation: true });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });
    await waitFor(() => expect(currentArmRecord?.opts.onAgentReply).toBeTypeOf('function'));
    const ordinaryOwner = requireCurrentArm();

    act(() => setMeeting(thread.id, true));
    await waitFor(() => expect(currentArmRecord?.opts.submitTranscript).toBeTypeOf('function'));
    const current = requireCurrentArm();
    expect(current).not.toBe(ordinaryOwner);
    expect(current.index).toBe(armRecords.length - 1);

    await act(async () => {
      await current.opts.submitTranscript?.('Current call turn');
      await Promise.resolve();
    });
    act(() => useStore.getState().setCallAudioEnabled(false));
    await act(async () => {
      pending.resolve({ response: 'Current call muted.', thread_id: thread.id });
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      const messages = useStore.getState().agentConversations.get(AGENT_ID)?.messages ?? [];
      expect(messages.some((message) => message.text === 'Current call muted.')).toBe(true);
    });
    expect(mocks.speakResponse).not.toHaveBeenCalled();
  });

  it('React cleanup keeps accepted arm ownership bound from ordinary A through meeting B', async () => {
    const thread = mkThread('one-to-one', ['captain', AGENT_ID]);
    seed(thread, { tts: true, callAudio: true, conversation: true });
    const view = await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });
    await waitFor(() => expect(currentArmRecord?.opts.onAgentReply).toBeTypeOf('function'));
    const ownerA = requireCurrentArm();
    const globalDisarmsBefore = mocks.disarmConversationMode.mock.calls.length;

    act(() => setMeeting(thread.id, true));
    await waitFor(() => {
      expect(currentArmRecord).not.toBe(ownerA);
      expect(currentArmRecord?.opts.submitTranscript).toBeTypeOf('function');
    });
    const ownerB = requireCurrentArm();
    expect(ownerB.index).toBe(armRecords.length - 1);
    expect(ownerA.disposer).toHaveBeenCalledTimes(1);
    expect(mocks.disarmConversationMode).toHaveBeenCalledTimes(globalDisarmsBefore);

    act(() => ownerA.disposer());
    expect(ownerA.disposer).toHaveBeenCalledTimes(2);
    expect(currentArmRecord).toBe(ownerB);

    await act(async () => {
      view.unmount();
      await Promise.resolve();
    });
    expect(ownerB.disposer).toHaveBeenCalledTimes(1);
    expect(currentArmRecord).toBeNull();
    expect(mocks.disarmConversationMode).toHaveBeenCalledTimes(globalDisarmsBefore);
  });
});

describe('BF-671 group voice/reveal and meeting mic contracts', () => {
  const replies = [
    { agent_id: AGENT_ID, callsign: 'Host', text: 'First reply.' },
    { agent_id: PEER_ID, callsign: 'Peer', text: 'Second reply.' },
  ];

  it('active group with call audio on selects meeting voice and reveals in sequencer order', async () => {
    network.groupReplies = replies;
    const thread = mkThread('group', ['captain', AGENT_ID, PEER_ID], true);
    seed(thread, { tts: false, callAudio: true });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    sendTyped('Crew report');
    await waitFor(() => expect(mocks.speakMeetingReplies).toHaveBeenCalledTimes(1));
    const [spoken, hooks] = mocks.speakMeetingReplies.mock.calls[0] as [
      typeof replies,
      { onUtteranceStart: (reply: typeof replies[number]) => void; onUtteranceEnd: (reply: typeof replies[number]) => void },
    ];
    expect(spoken).toEqual(replies);
    act(() => {
      for (const reply of spoken) {
        hooks.onUtteranceStart(reply);
        hooks.onUtteranceEnd(reply);
      }
    });

    const messages = useStore.getState().agentConversations.get(AGENT_ID)?.messages ?? [];
    expect(messages.filter((message) => message.role === 'agent').map((message) => message.text))
      .toEqual(['First reply.', 'Second reply.']);
  });

  it('muted active group progressively reveals every non-empty reply with zero voice', async () => {
    vi.useFakeTimers();
    network.groupReplies = [replies[0], { agent_id: 'empty', callsign: 'Empty', text: '' }, replies[1]];
    const thread = mkThread('group', ['captain', AGENT_ID, PEER_ID], true);
    seed(thread, { tts: true, callAudio: false });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    sendTyped('Crew report');
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await vi.runAllTimersAsync();
    });

    expect(mocks.speakMeetingReplies).not.toHaveBeenCalled();
    const messages = useStore.getState().agentConversations.get(AGENT_ID)?.messages ?? [];
    expect(messages.filter((message) => message.role === 'agent').map((message) => message.text))
      .toEqual(['First reply.', 'Second reply.']);
  });

  it('non-meeting group remains progressively revealed text only even when call audio is on', async () => {
    vi.useFakeTimers();
    network.groupReplies = replies;
    const thread = mkThread('group', ['captain', AGENT_ID, PEER_ID], false);
    seed(thread, { tts: true, callAudio: true });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    sendTyped('Crew report');
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await vi.runAllTimersAsync();
    });

    expect(mocks.speakMeetingReplies).not.toHaveBeenCalled();
    const messages = useStore.getState().agentConversations.get(AGENT_ID)?.messages ?? [];
    expect(messages.filter((message) => message.role === 'agent').map((message) => message.text))
      .toEqual(['First reply.', 'Second reply.']);
  });

  it('meeting conversation mode routes through sendText and muting call audio disarms it', async () => {
    const thread = mkThread('group', ['captain', AGENT_ID, PEER_ID], true);
    seed(thread, { tts: false, callAudio: true, conversation: true });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    await waitFor(() => expect(mocks.armConversationMode).toHaveBeenCalled());
    const armCalls = mocks.armConversationMode.mock.calls as unknown[][];
    const meetingOpts = armCalls[armCalls.length - 1][0] as {
      submitTranscript?: (text: string) => Promise<void>;
      onAgentReply?: (text: string) => void;
    };
    expect(meetingOpts.submitTranscript).toBeTypeOf('function');
    expect(meetingOpts.onAgentReply).toBeUndefined();
    await act(async () => { await meetingOpts.submitTranscript?.('Meeting transcript'); });
    await waitFor(() => {
      const calls = vi.mocked(global.fetch).mock.calls;
      expect(calls.some(([url, init]) =>
        String(url) === `/api/threads/${thread.id}/messages` && init?.method === 'POST',
      )).toBe(true);
    });

    const disarmsBefore = mocks.disarmConversationMode.mock.calls.length;
    act(() => useStore.getState().setCallAudioEnabled(false));
    await waitFor(() => expect(mocks.disarmConversationMode.mock.calls.length).toBeGreaterThan(disarmsBefore));
  });

  it('call-audio false prevents meeting open-mic arming', async () => {
    const thread = mkThread('group', ['captain', AGENT_ID, PEER_ID], true);
    seed(thread, { tts: true, callAudio: false, conversation: true });
    await renderProfileChat({ agentId: AGENT_ID, threadId: thread.id });

    await waitFor(() => expect(mocks.disarmConversationMode).toHaveBeenCalled());
    expect(mocks.armConversationMode).not.toHaveBeenCalled();
  });

  it('contains no active-speech cancellation or new microphone state/control', () => {
    expect(profileChatSource).not.toMatch(/speechSynthesis\.cancel|_activeAudio\.pause|callMicEnabled/);
    expect(profileChatSource).not.toMatch(/toggleOutputAudio[\s\S]{0,500}stopSpeaking/);
  });
});
