/** BF-718 (#1157): the transcript is the single speech owner.
 *
 *  With voice on, the Captain heard every ordinary reply and SILENCE for
 *  anything the server pushed. Reported twice, most recently 2026-08-13:
 *
 *      Ezri  "I've started on that... task 0889db23c32b..."   -> SPOKEN
 *      Ezri  "Now I have a good picture of both products..."  -> SILENT
 *
 *  Speech was bound to the request/response path, so a promoted turn's report
 *  (AD-1165) — appended server-side, delivered as CHAT_THREAD_MESSAGE_APPENDED
 *  — reached the transcript and never reached the speaker.
 *
 *  The first attempt added a transcript watcher ALONGSIDE the send path, the
 *  AD-1062 greeting and the BF-290 conversation-mode callback, and was
 *  reverted: with several speakers every message is decided about twice, and no
 *  id-based marking wins the race against a WebSocket event the server emits
 *  BEFORE returning the HTTP body — the optimistic row and the canonical row
 *  carry different ids.
 *
 *  So all four speakers now share one CLAIM keyed on role + author + content.
 *  Whichever sees the message first speaks it; the rest fall silent without
 *  needing to know they raced. The transcript watcher is the one that closes
 *  BF-718, because it is the only one that sees a message nobody requested.
 *  The other three are kept because each sees something it cannot: a reply
 *  landing in a thread the Captain navigated away from (BF-671), and the
 *  conversation-mode turn-taking signal (BF-290). A GROUP room still defers to
 *  the AD-921 meeting sequencer, which drives the reveal clock; a 1:1 call does
 *  NOT, because the sequencer is only ever handed group fan-out replies.
 *
 *  Mounted against the real component and the real store, following the BF-671
 *  audioControl harness — the earlier attempt asserted this from ?raw source
 *  text on the false premise that ProfileChatTab cannot mount under jsdom.
 */
import {
  act, cleanup, fireEvent, render, screen, waitFor, type RenderResult,
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
vi.mock('../MeetingView', () => ({ MeetingView: () => <div data-testid="meeting-view-stub" /> }));
vi.mock('../../workspace/WorkspaceFilesRail', () => ({
  WorkspaceFilesRail: () => <aside data-testid="workspace-files-stub" />,
}));

import { ProfileChatTab } from '../ProfileChatTab';
import { sharedSpeechLedger } from '../speechLedgerStore';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

const AGENT_ID = 'bf718-host';
const PEER_ID = 'bf718-peer';
const THREAD_ID = 'bf718-thread';
const TTS_KEY = `hxi_chat_tts_${AGENT_ID}`;

/** Server-side transcript the GET /messages handler returns. Tests push onto
 *  this to simulate a message the server appended without being asked. */
let serverMessages: Array<Record<string, unknown>>;
let chatReply: Record<string, unknown>;
/** Set to hold the chat POST open so the server's WebSocket append can be made
 *  to land FIRST — the ordering the server actually produces. */
let releaseChat: (() => void) | null;
/** Set to hold the transcript GET open, so a push can be coalesced into a
 *  seeding load that is still in flight. */
let holdMessages: boolean;
let releaseMessages: (() => void) | null;

/** ``repairThreadMessages`` reads ``text()``, not ``json()``, and validates an
 *  EXACT DTO key set — so the mock has to be honest about both. */
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

function mkThread(id: string, participants: string[], meetingActive = false): AD791aChatThreadView {
  return {
    id, title: id, participants, created_at: 1, last_active_at: 1,
    metadata: {
      ...(participants.length === 2 ? { is_default: true } : {}),
      ...(meetingActive ? { meeting_active: true } : {}),
    },
  };
}

function serverMsg(
  id: string, body: string, authorId = AGENT_ID, role = 'agent',
  metadata: Record<string, unknown> = {},
) {
  return {
    id, thread_id: THREAD_ID, author_id: authorId, role, body,
    created_at: 1_700_000_000, metadata,
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
    if (url.endsWith('/chat/history')) return Promise.resolve(response({ memories: [] }));
    if (url.endsWith('/profile')) {
      return Promise.resolve(response({
        voiceProfile: { voice_name: 'test', pitch: 1, rate: 1, volume: 1 },
      }));
    }
    if (/\/api\/threads\/[^/?]+\/messages\?limit=200$/.test(url) && method === 'GET') {
      const body = () => response({ thread_id: THREAD_ID, messages: serverMessages });
      if (!holdMessages) return Promise.resolve(body());
      return new Promise<Response>((resolve) => {
        releaseMessages = () => resolve(body());
      });
    }
    if (url === `/api/agent/${AGENT_ID}/chat` && method === 'POST') {
      if (!releaseChat) return Promise.resolve(response(chatReply));
      return new Promise<Response>((resolve) => {
        releaseChat = () => resolve(response(chatReply));
      });
    }
    return Promise.resolve(response({}));
  }));
}

function seed(opts: {
  tts: boolean;
  participants?: string[];
  meetingActive?: boolean;
  callAudio?: boolean;
  /** History for the no-thread 1:1 (AD-1062 legacy buffer). */
  conversation?: Array<{ role: string; text: string; authorId?: string }>;
  /** Omit the agent's thread entirely, so the transcript falls back to that
   *  buffer and no fetch ever hydrates the scope. */
  withoutThread?: boolean;
}): void {
  localStorage.setItem(TTS_KEY, opts.tts ? '1' : '0');
  const thread = mkThread(
    THREAD_ID, opts.participants ?? ['captain', AGENT_ID], opts.meetingActive ?? false,
  );
  useStore.setState({
    activeProfileAgent: AGENT_ID,
    activeProfileThreadId: null,
    agents: new Map([
      [AGENT_ID, mkAgent(AGENT_ID, 'Host')],
      [PEER_ID, mkAgent(PEER_ID, 'Peer')],
    ]),
    agentConversations: opts.conversation
      ? new Map([[AGENT_ID, {
          agentId: AGENT_ID,
          messages: opts.conversation.map((m, i) => ({
            id: `conv-${i}`, role: m.role, text: m.text,
            timestamp: 1_700_000_000 + i, authorId: m.authorId ?? AGENT_ID,
          })),
        }]]) as never
      : new Map(),
    threadIdByAgent: opts.withoutThread ? new Map() : new Map([[AGENT_ID, THREAD_ID]]),
    chatThreads: new Map([[THREAD_ID, thread]]),
    threadMessages: new Map(),
    callAudioEnabled: opts.callAudio ?? true,
    meetingChatVisible: true,
    typingAgent: null,
    // On by default, so a silence assertion is never satisfied by an off
    // toggle it did not mean to be testing.
    voiceEnabled: true,
  });
}

async function mount(): Promise<RenderResult> {
  let view!: RenderResult;
  await act(async () => {
    view = render(<ProfileChatTab agentId={AGENT_ID} />);
    await Promise.resolve();
  });
  // The speech owner treats everything before the transcript loads as history,
  // so a test must reach a hydrated surface before asserting about arrivals.
  await waitFor(() => {
    expect(useStore.getState().threadMessages.has(THREAD_ID)).toBe(true);
  });
  await act(async () => { await Promise.resolve(); });
  return view;
}

/** A message the SERVER appended — a promoted turn's report. It lands in the
 *  transcript over the socket, never through the send round trip. */
async function serverPushes(
  body: string, authorId = AGENT_ID,
  metadata: Record<string, unknown> = {},
): Promise<void> {
  const id = `pushed-${serverMessages.length}`;
  serverMessages.push(serverMsg(id, body, authorId, 'agent', metadata));
  await act(async () => {
    useStore.setState({ liveThreadRefresh: { threadId: THREAD_ID, requestId: id } });
    await Promise.resolve();
  });
  await waitFor(() => {
    const rendered = useStore.getState().threadMessages.get(THREAD_ID) ?? [];
    expect(rendered.some((m) => m.text === body)).toBe(true);
  });
  await act(async () => { await Promise.resolve(); });
}

function spokenTexts(): string[] {
  return mocks.speakResponse.mock.calls.map((call) => String(call[0]));
}

function sendTyped(text = 'Captain message'): void {
  const input = screen.getByPlaceholderText('Message...');
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key: 'Enter' });
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  serverMessages = [];
  releaseChat = null;
  holdMessages = false;
  releaseMessages = null;
  chatReply = { response: 'Typed response.', thread_id: THREAD_ID };
  installNetwork();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('BF-718 — a pushed message is spoken', () => {
  it('speaks a background report that arrived without a request', async () => {
    seed({ tts: true });
    await mount();

    await serverPushes('Now I have a good picture of both products.');

    await waitFor(() => {
      expect(spokenTexts()).toContain('Now I have a good picture of both products.');
    });
  });

  it('stays silent when the agent voice toggle is off', async () => {
    seed({ tts: false });
    await mount();

    await serverPushes('Now I have a good picture of both products.');
    await act(async () => { await Promise.resolve(); });

    expect(spokenTexts()).not.toContain('Now I have a good picture of both products.');  });
});

describe('BF-718 — an ordinary reply is spoken exactly once', () => {
  it('speaks the send-path reply, and speaks it only once', async () => {
    seed({ tts: true });
    await mount();

    await act(async () => {
      sendTyped();
      await Promise.resolve();
    });
    // The server's own append then arrives, carrying the same reply under the
    // canonical id. Speaking again here is the duplicate the first attempt hit.
    await serverPushes('Typed response.');

    await waitFor(() => {
      expect(spokenTexts().filter((t) => t === 'Typed response.')).toHaveLength(1);
    });
  });

  it('speaks it once when the server append LANDS FIRST, which is the real order', async () => {
    // The server emits CHAT_THREAD_MESSAGE_APPENDED before it returns the chat
    // response body, so the transcript usually sees the reply first. No
    // id-based marking survives this; the shared content claim does.
    seed({ tts: true });
    releaseChat = () => {};
    await mount();

    act(() => { sendTyped(); });
    await serverPushes('Typed response.');
    await act(async () => {
      releaseChat?.();
      await Promise.resolve();
    });
    await act(async () => { await Promise.resolve(); });

    expect(spokenTexts().filter((t) => t === 'Typed response.')).toHaveLength(1);
  });

  it('speaks it once in a 1:1 that has no thread, where rows carry no author', async () => {
    // `addAgentMessage` omits `authorId` on the per-agent buffer (AD-936 sets
    // it only for group replies), so a claim keyed on an explicit agent id
    // would not match the row it was made for and BOTH speakers would fire.
    seed({ tts: true, withoutThread: true });
    // The reply must NOT carry a thread_id, or `setThreadForAgent` promotes the
    // agent to a thread mid-test and the transcript reads threadMessages
    // instead of the buffer — quietly testing the wrong path.
    chatReply = { response: 'Typed response.' };
    await act(async () => {
      render(<ProfileChatTab agentId={AGENT_ID} />);
      await Promise.resolve();
    });
    await act(async () => { await Promise.resolve(); });

    await act(async () => {
      sendTyped();
      await Promise.resolve();
    });
    await act(async () => { await Promise.resolve(); });

    expect(useStore.getState().agentConversations.get(AGENT_ID)?.messages
      .some((m) => m.role === 'agent' && m.authorId === undefined)).toBe(true);
    expect(spokenTexts().filter((t) => t === 'Typed response.')).toHaveLength(1);
  });

  it('still forwards the AD-738e-1 emotion when the send path wins the claim', async () => {
    seed({ tts: true });
    chatReply = { response: 'Typed response.', thread_id: THREAD_ID, emotion: 'warm' };
    await mount();

    await act(async () => {
      sendTyped();
      await Promise.resolve();
    });

    await waitFor(() => {
      const call = mocks.speakResponse.mock.calls.find((c) => c[0] === 'Typed response.');
      expect(call).toBeDefined();
      expect(call?.[3]).toBe('warm');
    });
  });

  // BF-766: the WebSocket-first ordering is the USUAL one -- the server emits
  // CHAT_THREAD_MESSAGE_APPENDED before it returns the chat response body -- so
  // the transcript wins the claim most of the time. It used to speak flat,
  // because the emotion existed only on the response body it never saw.
  it('forwards the emotion when the TRANSCRIPT wins the claim', async () => {
    seed({ tts: true });
    await mount();

    await serverPushes('Pushed first.', AGENT_ID, { emotion: 'concerned' });

    const call = mocks.speakResponse.mock.calls.find((c) => c[0] === 'Pushed first.');
    expect(call).toBeDefined();
    expect(call?.[3]).toBe('concerned');
  });

  it('omits the emotion for a row that carries none, rather than defaulting it', async () => {
    seed({ tts: true });
    await mount();

    await serverPushes('No emotion here.');

    const call = mocks.speakResponse.mock.calls.find((c) => c[0] === 'No emotion here.');
    expect(call).toBeDefined();
    expect(call?.[3]).toBeUndefined();
  });

  it('waits for the winning utterance before signalling conversation-mode completion', async () => {
    // The controller's reply can reach onAgentReply after the server already
    // pushed the same text and the transcript spoke it. Staying silent is
    // right. Signalling completion IMMEDIATELY is not: it detaches the
    // barge-in guard and starts the silence timer while the agent is still
    // audibly talking. Completion must track the utterance that actually won.
    localStorage.setItem(`hxi_chat_mic_mode_${AGENT_ID}`, 'conversation');
    seed({ tts: true });
    await mount();

    await waitFor(() => expect(mocks.armConversationMode).toHaveBeenCalled());
    const [[opts]] = mocks.armConversationMode.mock.calls as unknown as
      Array<[{ onAgentReply: (text: string) => void }]>;

    await serverPushes('the controller and the socket agree');
    expect(spokenTexts().filter((t) => t === 'the controller and the socket agree'))
      .toHaveLength(1);

    mocks.markAgentReplyComplete.mockClear();
    const listenersBefore = mocks.onSpeechEvent.mock.calls.length;
    act(() => { opts.onAgentReply('the controller and the socket agree'); });

    // Silent, and NOT yet complete — it subscribed instead.
    expect(spokenTexts().filter((t) => t === 'the controller and the socket agree'))
      .toHaveLength(1);
    expect(mocks.markAgentReplyComplete).not.toHaveBeenCalled();
    expect(mocks.onSpeechEvent.mock.calls.length).toBe(listenersBefore + 1);

    // The transcript's utterance ends; NOW the controller may advance.
    const [listener] = (mocks.onSpeechEvent.mock.calls as unknown as
      Array<[(e: { type: string; agent_id?: string }) => void]>)[listenersBefore];
    act(() => { listener({ type: 'end', agent_id: AGENT_ID }); });
    expect(mocks.markAgentReplyComplete).toHaveBeenCalledTimes(1);
  });

  it('does not wait for an utterance that never existed', async () => {
    // Losing the claim is NOT proof that someone is speaking. Identical text
    // said earlier in the scope also loses, and then no 'end' ever fires —
    // waiting on one strands the controller in agent_speaking forever, which
    // is worse than the bug being fixed.
    localStorage.setItem(`hxi_chat_mic_mode_${AGENT_ID}`, 'conversation');
    seed({ tts: true });
    await mount();

    await waitFor(() => expect(mocks.armConversationMode).toHaveBeenCalled());
    const [[opts]] = mocks.armConversationMode.mock.calls as unknown as
      Array<[{ onAgentReply: (text: string) => void }]>;

    // Said once and finished long ago.
    await serverPushes('Acknowledged.');
    act(() => {
      const [[listener]] = (mocks.onSpeechEvent.mock.calls as unknown as
        Array<[(e: { type: string; agent_id?: string }) => void]>).slice(-1);
      listener({ type: 'end', agent_id: AGENT_ID });
    });

    mocks.markAgentReplyComplete.mockClear();
    act(() => { opts.onAgentReply('Acknowledged.'); });

    expect(mocks.markAgentReplyComplete).toHaveBeenCalledTimes(1);
  });

  it('signals conversation-mode completion at once when audio is off', async () => {
    // Nothing will ever emit an 'end', so waiting would strand the controller.
    localStorage.setItem(`hxi_chat_mic_mode_${AGENT_ID}`, 'conversation');
    seed({ tts: false });
    useStore.setState({ voiceEnabled: false });
    await mount();

    await waitFor(() => expect(mocks.armConversationMode).toHaveBeenCalled());
    const [[opts]] = mocks.armConversationMode.mock.calls as unknown as
      Array<[{ onAgentReply: (text: string) => void }]>;

    mocks.markAgentReplyComplete.mockClear();
    act(() => { opts.onAgentReply('nobody will hear this'); });

    expect(spokenTexts()).not.toContain('nobody will hear this');
    expect(mocks.markAgentReplyComplete).toHaveBeenCalledTimes(1);
  });
});

describe('BF-718 — history is never read aloud', () => {
  it('speaks nothing for a transcript that already existed on open', async () => {
    serverMessages = [
      serverMsg('h1', 'first historical reply'),
      serverMsg('h2', 'second historical reply'),
    ];
    seed({ tts: true });
    await mount();
    await act(async () => { await Promise.resolve(); });

    expect(spokenTexts()).toEqual([]);
  });

  it('speaks nothing when a single historical message hydrates late', async () => {
    // The defect the first attempt shipped: the effect's first run sees an
    // EMPTY list because the transcript loads asynchronously, so the real
    // history that follows reads as live traffic.
    serverMessages = [serverMsg('h1', 'the only historical reply')];
    seed({ tts: true });
    await mount();
    await act(async () => { await Promise.resolve(); });

    expect(spokenTexts()).not.toContain('the only historical reply');
  });

  it('speaks nothing when the transcript has no thread and never hydrates', async () => {
    // A 1:1 with no server thread reads the AD-1062 conversation buffer, which
    // is already populated at mount — no fetch, so nothing marks it as loaded.
    seed({
      tts: true,
      withoutThread: true,
      conversation: [
        { role: 'captain', text: 'what did you find?' },
        { role: 'agent', text: 'buffered history nobody asked to hear' },
      ],
    });
    await act(async () => {
      render(<ProfileChatTab agentId={AGENT_ID} />);
      await Promise.resolve();
    });
    await act(async () => { await Promise.resolve(); });

    expect(spokenTexts()).not.toContain('buffered history nobody asked to hear');
  });

  it('speaks a push whose row was already inside a seeding load', async () => {
    // A reconnect repair is a SEEDING load. A push that lands while it is in
    // flight gets coalesced behind it, and the repair's own response can
    // already contain the pushed row. Seeding the whole array then claims that
    // row silently and the coalesced refresh finds nothing left to say —
    // BF-718 all over again, for exactly the message this AD exists to speak.
    seed({ tts: true });
    await mount();

    serverMessages.push(serverMsg('late', 'the report the repair swallowed'));
    holdMessages = true;

    // 1. The repair starts a no-trigger (seeding) load. It hangs.
    await act(async () => {
      useStore.setState({ liveRepairEpoch: useStore.getState().liveRepairEpoch + 1 });
      await Promise.resolve();
    });
    expect(releaseMessages).not.toBeNull();

    // 2. The push arrives while that load is in flight, so it is coalesced.
    await act(async () => {
      useStore.setState({ liveThreadRefresh: { threadId: THREAD_ID, requestId: 'late' } });
      await Promise.resolve();
    });

    // 3. The seeding load resolves — carrying the pushed row.
    holdMessages = false;
    await act(async () => {
      releaseMessages?.();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(spokenTexts()).toContain('the report the repair swallowed');
    });
  });

  it('speaks nothing on a reconnect repair, however few messages it carries', async () => {
    seed({ tts: true });
    await mount();

    serverMessages.push(serverMsg('missed', 'arrived while the socket was down'));
    await act(async () => {
      useStore.setState({ liveRepairEpoch: useStore.getState().liveRepairEpoch + 1 });
      await Promise.resolve();
    });
    await act(async () => { await Promise.resolve(); });

    expect(spokenTexts()).not.toContain('arrived while the socket was down');
  });
});

describe('BF-718 — the inherited rules still hold', () => {
  it.each(['(no response)', '(communication error)', '(error: timeout)'])(
    'never speaks the %s placeholder', async (placeholder) => {
      seed({ tts: true });
      await mount();

      await serverPushes(placeholder);
      await act(async () => { await Promise.resolve(); });

      expect(spokenTexts()).not.toContain(placeholder);
    },
  );

  it('leaves a live GROUP call to the meeting sequencer', async () => {
    // useMeetingVoice speaks the group fan-out AND drives the reveal clock. A
    // second speaker there both duplicates and cancels in-flight audio.
    seed({
      tts: true, meetingActive: true, callAudio: true,
      participants: ['captain', AGENT_ID, PEER_ID],
    });
    await mount();

    await serverPushes('spoken by the meeting sequencer, not here');
    await act(async () => { await Promise.resolve(); });

    expect(spokenTexts()).not.toContain('spoken by the meeting sequencer, not here');
  });

  it('SPEAKS a pushed message during a 1:1 call, which no sequencer covers', async () => {
    // useMeetingVoice is only ever handed the GROUP fan-out replies. Deferring
    // a 1:1 call to it hands the message to nobody: the transcript claims and
    // stays quiet, then the send path loses the claim and stays quiet too.
    seed({ tts: false, meetingActive: true, callAudio: true });
    await mount();

    await serverPushes('the report that landed mid-call');

    await waitFor(() => {
      expect(spokenTexts()).toContain('the report that landed mid-call');
    });
  });

  it('speaks a 1:1 call reply exactly once when the append LANDS FIRST', async () => {
    seed({ tts: false, meetingActive: true, callAudio: true });
    releaseChat = () => {};
    await mount();

    act(() => { sendTyped(); });
    await serverPushes('Typed response.');
    await act(async () => {
      releaseChat?.();
      await Promise.resolve();
    });
    await act(async () => { await Promise.resolve(); });

    expect(spokenTexts().filter((t) => t === 'Typed response.')).toHaveLength(1);
  });

  it('does not read a group backlog aloud when the room stops being a group', async () => {
    // The group bail-out still CLAIMS before returning. Without that, every
    // message that scrolled past while the room was a group becomes a fresh
    // arrival the moment it is not, and gets read out in a burst.
    seed({ tts: true, participants: ['captain', AGENT_ID, PEER_ID] });
    await mount();
    await serverPushes('said while it was a crew room');
    expect(spokenTexts()).not.toContain('said while it was a crew room');

    await act(async () => {
      useStore.getState().setChatThread(
        mkThread(THREAD_ID, ['captain', AGENT_ID], false) as never,
      );
      await Promise.resolve();
    });
    await act(async () => { await Promise.resolve(); });

    expect(spokenTexts()).not.toContain('said while it was a crew room');
  });

  it('leaves a group room alone, even for the agent whose voice is on', async () => {
    // The host's own toggle is ON here, so the only thing keeping this quiet is
    // the 1:1 restriction — not an off switch elsewhere.
    seed({ tts: true, participants: ['captain', AGENT_ID, PEER_ID] });
    await mount();

    await serverPushes('a host reply in a crew room');
    await act(async () => { await Promise.resolve(); });

    expect(spokenTexts()).not.toContain('a host reply in a crew room');
  });

  it('leaves a group room alone for a peer whose voice is also on', async () => {
    seed({ tts: true, participants: ['captain', AGENT_ID, PEER_ID] });
    await mount();

    await serverPushes('a peer reply in a crew room', PEER_ID);
    await act(async () => { await Promise.resolve(); });

    expect(spokenTexts()).not.toContain('a peer reply in a crew room');
  });
});

describe('BF-765 — the claim outlives the mount', () => {
  it('the mounted component claims into the SHARED ledger, not a private one', async () => {
    // The consumer crossing. The lifetime unit tests never mount the
    // component, so reverting `useRef(sharedSpeechLedger())` back to
    // `useRef(createSpeechLedger())` would leave every one of them green --
    // the claim would work perfectly inside a ledger nothing else can see.
    seed({ tts: true });
    await mount();

    await serverPushes('The scan is complete.');
    await waitFor(() => {
      expect(spokenTexts()).toContain('The scan is complete.');
    });

    const scope = sharedSpeechLedger().scopes.get(THREAD_ID);
    expect(
      scope, 'the component spoke but the shared ledger never saw the claim',
    ).toBeDefined();
    expect(scope!.keys.size).toBeGreaterThan(0);
  });
});
