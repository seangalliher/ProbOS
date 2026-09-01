/** BF-764 (#1222): a burst of transcript arrivals talks over itself.
 *
 *  One refresh can admit several arrivals at once — a promoted turn's report
 *  landing beside an ordinary reply, or a backlog delivered after a
 *  reconnect. The speaker walked them in a single synchronous pass and called
 *  `speakResponse` for each, but `speakResponse` CANCELLED whatever was
 *  playing before it started. So every utterance but the last began and was
 *  immediately truncated.
 *
 *  Nothing is lost from the transcript — each arrival's claim is consumed and
 *  the text renders — so this is an audio-quality defect, and the fix must not
 *  turn it into a silence defect. That is what the two guards below are for,
 *  and both are still asserted here: an arrival that produces no utterance at
 *  all must not wedge the queue, and neither must an utterance whose terminal
 *  'end' never arrives.
 *
 *  ## Re-pointed at the arbiter (#1340)
 *
 *  BF-764 answered this with a queue INSIDE this component. AD-1291 moved that
 *  ownership into `audio/voice`'s arbiter, where it covers all seven producers
 *  instead of this component's arrivals alone, and #1340 retired the local
 *  drain. These tests therefore run against the REAL `audio/voice` module and
 *  assert on what reached `speechSynthesis.speak` — the audio device — rather
 *  than on what some producer asked for.
 *
 *  That distinction is the whole point of the re-point. The obvious migration
 *  was to keep mocking `audio/voice` and hand the mock a fake queue, but then
 *  every assertion below would describe the FAKE's guards while production
 *  never ran them. The serialisation under test IS that module.
 *
 *  The fake engine models `cancel()` faithfully: cancelling a live utterance
 *  fires its terminal callback, and `voice.ts` routes `onend`/`onerror`
 *  through one settle guard, so the cancel emits exactly one 'end' carrying
 *  the SUPERSEDED utterance's id (BF-767). That is the real BF-858 mechanism,
 *  not a simulation of it.
 *
 *  Mounted against the real component and the real store, following the
 *  BF-718 harness.
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

// `audio/voice` is deliberately NOT mocked — see the header.
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
import {
  SPEECH_JOIN_TIMEOUT_MS, speakResponse, _resetTtsStatusForTests,
} from '../../../audio/voice';
import type { Agent } from '../../../store/types';

const AGENT_ID = 'bf764-host';
const THREAD_ID = 'bf764-thread';
const TTS_KEY = `hxi_chat_tts_${AGENT_ID}`;

let speakCalls: FakeUtterance[] = [];
/** When true the device finishes an utterance the instant it receives it, so a
 *  terminal 'end' lands INSIDE the dispatch, before it has returned. */
let autoEndOnSpeak = false;

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
  autoEndOnSpeak = false;
  (globalThis as any).SpeechSynthesisUtterance = FakeUtterance;
  (globalThis as any).speechSynthesis = {
    // A real browser fires the live utterance's terminal callback when it is
    // cancelled, and `voice.ts` turns that into an 'end' carrying the
    // SUPERSEDED utterance's id. Modelling it is what makes the cascade test
    // below exercise the genuine BF-858 mechanism. Already-ended utterances
    // are inert: `voice.ts` holds a per-utterance settle guard.
    cancel: vi.fn(() => { for (const u of speakCalls) u.onerror?.(); }),
    speak: vi.fn((u: FakeUtterance) => {
      speakCalls.push(u);
      u.onstart?.();
      if (autoEndOnSpeak) u.onend?.();
    }),
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

/** The defect's shape: SEVERAL arrivals admitted by ONE refresh. */
async function serverPushesBurst(...bodies: string[]): Promise<void> {
  let lastId = '';
  for (const body of bodies) {
    lastId = `pushed-${serverMessages.length}`;
    serverMessages.push(serverMsg(lastId, body));
  }
  await act(async () => {
    // The trigger id has to name a message the fetch will actually return, or
    // the refresh is dropped as a stale transcript repair.
    useStore.setState({ liveThreadRefresh: { threadId: THREAD_ID, requestId: lastId } });
    await Promise.resolve();
  });
  await waitFor(() => {
    const rendered = useStore.getState().threadMessages.get(THREAD_ID) ?? [];
    expect(rendered.some((m) => m.text === bodies[bodies.length - 1])).toBe(true);
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

describe('BF-764 — a burst of arrivals is spoken one at a time', () => {
  it('does not start the second utterance until the first one ends', async () => {
    seed();
    await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');

    // Before the fix BOTH reached the device in one synchronous pass, and the
    // second cancelled the first mid-sentence.
    await waitFor(() => expect(deviceTexts()).toContain('First thing said.'));
    expect(deviceTexts()).not.toContain('Second thing said.');

    await endDevice(0);

    await waitFor(() => expect(deviceTexts()).toContain('Second thing said.'));
    expect(deviceTexts()).toEqual(['First thing said.', 'Second thing said.']);
  });

  it('speaks a burst in arrival order', async () => {
    seed();
    await mount();

    await serverPushesBurst('One.', 'Two.', 'Three.');

    await waitFor(() => expect(deviceTexts()).toEqual(['One.']));
    await endDevice(0);
    await waitFor(() => expect(deviceTexts()).toEqual(['One.', 'Two.']));
    await endDevice(1);
    await waitFor(() => expect(deviceTexts()).toEqual(['One.', 'Two.', 'Three.']));
  });

  it('holds a sibling surface behind the arrival in flight', async () => {
    // Re-pointed (#1340). This used to fire a hand-built 'end' carrying a
    // foreign id straight at the component's own listener, to pin that the
    // drain correlated on the utterance id rather than on `agent_id`. That
    // listener no longer exists, and the id-correlation it was pinning is now
    // asserted for real against the arbiter in the superseded-'end' test below.
    //
    // What it becomes is the property the drain could never provide: a
    // producer OUTSIDE this component (IntentSurface is mounted for the whole
    // session beside it) shares the one device, and must neither cut in nor
    // advance our queue. A component-local queue could not see it at all.
    seed();
    await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');
    await waitFor(() => expect(deviceTexts()).toEqual(['First thing said.']));

    act(() => {
      speakResponse("Ship's Computer here.", undefined, undefined, undefined, 'narration');
    });
    await act(async () => { await Promise.resolve(); });
    expect(deviceTexts()).toEqual(['First thing said.']);

    await endDevice(0);
    await waitFor(() => expect(deviceTexts()).toEqual([
      'First thing said.', 'Second thing said.',
    ]));
    await endDevice(1);
    await waitFor(() => expect(deviceTexts()).toEqual([
      'First thing said.', 'Second thing said.', "Ship's Computer here.",
    ]));
  });

  it('does not advance on a non-terminal speech event', async () => {
    seed();
    await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');
    await waitFor(() => expect(deviceTexts()).toEqual(['First thing said.']));

    // A 'start' is not a terminal event. Re-firing it must change nothing.
    await act(async () => {
      speakCalls[0].onstart?.();
      await Promise.resolve();
    });
    expect(deviceTexts()).toEqual(['First thing said.']);
  });

  // GUARD 1 — an arrival that can never produce an utterance must not wedge.
  it('keeps going when there is no TTS engine to speak an arrival', async () => {
    // Nothing will EVER emit an 'end' for an entry the device cannot take, so
    // waiting on one would silence every later message — strictly worse than
    // the clipped audio being fixed.
    seed();
    await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');
    await waitFor(() => expect(deviceTexts()).toEqual(['First thing said.']));

    // The engine disappears between enqueue and dispatch.
    const savedSynthesis = (globalThis as any).speechSynthesis;
    const savedAudio = (globalThis as any).Audio;
    const live = speakCalls[0];
    delete (globalThis as any).speechSynthesis;
    delete (globalThis as any).Audio;
    await act(async () => {
      live.onend?.();
      await Promise.resolve();
    });

    // Drained rather than wedged: with the engine back, the next arrival is
    // spoken immediately and no timer had to rescue it.
    (globalThis as any).speechSynthesis = savedSynthesis;
    (globalThis as any).Audio = savedAudio;
    _resetTtsStatusForTests();
    await serverPushesBurst('Third thing said.');
    await waitFor(() => expect(deviceTexts()).toEqual([
      'First thing said.', 'Third thing said.',
    ]));
  });

  // GUARD 2 — a lost 'end' must not strand the rest of the queue.
  it('moves on when an utterance never reports that it ended', async () => {
    // `shouldAdvanceTime` keeps the clock moving so `waitFor` and the mount's
    // network round trips still progress; without it the harness starves.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    seed();
    await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');
    await waitFor(() => expect(deviceTexts()).toEqual(['First thing said.']));

    // Nothing ever ends the first utterance.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SPEECH_JOIN_TIMEOUT_MS + 1000);
    });

    expect(deviceTexts()).toEqual(['First thing said.', 'Second thing said.']);
  });

  it('does not fire the join timeout on an utterance that ended normally', async () => {
    // The timeout is a safety net. If it were short enough to fire on a real
    // utterance it would reintroduce the overlap it exists to prevent.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    seed();
    await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');
    await waitFor(() => expect(deviceTexts()).toEqual(['First thing said.']));

    await act(async () => { await vi.advanceTimersByTimeAsync(SPEECH_JOIN_TIMEOUT_MS - 1000); });
    expect(deviceTexts()).toEqual(['First thing said.']);
  });

  it('leaves a single arrival unchanged', async () => {
    // The queue must not add a round trip to the ordinary one-message case.
    seed();
    await mount();

    await serverPushesBurst('Only thing said.');

    await waitFor(() => expect(deviceTexts()).toEqual(['Only thing said.']));
  });

  it('survives the superseded utterance ending while the next one starts', async () => {
    // THE BF-858 CASCADE, against real production code. Dispatching an entry
    // calls `speechSynthesis.cancel()` first, and a real browser answers that
    // by firing the live utterance's terminal callback — so an 'end' carrying
    // the SUPERSEDED id lands synchronously, inside the dispatch, while the
    // arbiter's listener for the NEW entry is already armed.
    //
    // Correlating on anything less precise than the utterance id resolves that
    // listener on somebody else's completion and launches the entry after it
    // on top of the one just started. Each utterance cancels the last while
    // the transcript still ends up in the right order, which is why a test
    // that checked only the final array would pass against the unfixed code.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    seed();
    await mount();

    // THREE messages, deliberately. With two, a wrongly-resolved listener
    // would still leave the same final transcript, so the mistake would be
    // invisible. The third makes it observable.
    await serverPushesBurst('One.', 'Two.', 'Three.');
    await waitFor(() => expect(deviceTexts()).toEqual(['One.']));

    // Let the join timeout release 'One.' WITHOUT ending it, so it is still
    // live when 'Two.' dispatches and the cancel has something to supersede.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SPEECH_JOIN_TIMEOUT_MS + 1000);
    });
    expect(deviceTexts()).toEqual(['One.', 'Two.']);
    // PREMISE: the cancel really did emit 'One.'s terminal 'end' during
    // 'Two.'s dispatch. Without this the assertion below passes vacuously.
    expect((globalThis as any).speechSynthesis.cancel).toHaveBeenCalled();

    // That superseded 'end' must NOT be mistaken for 'Two.' finishing.
    await act(async () => { await Promise.resolve(); });
    expect(deviceTexts()).toEqual(['One.', 'Two.']);

    await endDevice(1);
    await waitFor(() => expect(deviceTexts()).toEqual(['One.', 'Two.', 'Three.']));
  });

  it('resolves when the utterance ends before speakResponse returns', async () => {
    // The mirror case: an 'end' carrying OUR OWN id, fired synchronously from
    // inside the dispatch. It must resolve the entry rather than be discarded
    // — discarding it would strand the queue until the join timeout.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    autoEndOnSpeak = true;
    seed();
    await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');

    await waitFor(() => {
      expect(deviceTexts()).toEqual(['First thing said.', 'Second thing said.']);
    });
    // Reached WITHOUT the join timeout having to rescue either one.
    expect(vi.getTimerCount()).toBe(0);
  });

  it('does not start a second drain when an arrival lands mid-utterance', async () => {
    // Arrivals do not wait for the queue to be idle. A refresh landing while
    // an utterance is in flight must join the existing queue, not start a
    // second drain — two drains would each dispatch, which is the very
    // cancellation this fix exists to stop.
    seed();
    await mount();

    await serverPushesBurst('One.', 'Two.');
    await waitFor(() => expect(deviceTexts()).toEqual(['One.']));

    // A NEW refresh while 'One.' is still speaking.
    await serverPushesBurst('Three.');
    await act(async () => { await Promise.resolve(); });
    expect(deviceTexts()).toEqual(['One.']);

    await endDevice(0);
    await waitFor(() => expect(deviceTexts()).toEqual(['One.', 'Two.']));
    await endDevice(1);
    await waitFor(() => expect(deviceTexts()).toEqual(['One.', 'Two.', 'Three.']));
  });

  it('stops speaking a backlog once the tab unmounts', async () => {
    // Serialising means the queue outlives the render that filled it, so it
    // needs an explicit end-of-life: a Captain who has navigated away must not
    // still be read the rest of the backlog.
    seed();
    const view = await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');
    await waitFor(() => expect(deviceTexts()).toEqual(['First thing said.']));

    view.unmount();
    await endDevice(0);

    expect(deviceTexts()).toEqual(['First thing said.']);
  });
});
