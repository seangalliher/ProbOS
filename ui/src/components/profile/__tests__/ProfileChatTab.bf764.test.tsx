/** BF-764 (#1222): a burst of transcript arrivals talks over itself.
 *
 *  One refresh can admit several arrivals at once — a promoted turn's report
 *  landing beside an ordinary reply, or a backlog delivered after a
 *  reconnect. The speaker walked them in a single synchronous pass and called
 *  `speakResponse` for each, but `speakResponse` CANCELS whatever is playing
 *  before it starts (voice.ts ~L246). So every utterance but the last began
 *  and was immediately truncated.
 *
 *  The failure is backend-dependent, which is why it survived so long: browser
 *  TTS produced a clipped burst, while Piper could run two at once, because
 *  `_speakGeneration` gates sentence pipelining WITHIN a reply rather than
 *  whole utterances. Either way the Captain did not hear what was said.
 *
 *  Nothing is lost from the transcript — each arrival's claim is consumed and
 *  the text renders — so this is an audio-quality defect, and the fix must not
 *  turn it into a silence defect. That is what the two guards below are for,
 *  and both are asserted here: an arrival that produces no utterance at all
 *  must not wedge the queue, and neither must an utterance whose terminal
 *  'end' never arrives.
 *
 *  Mounted against the real component and the real store, following the
 *  BF-718 harness.
 */
import {
  act, cleanup, render, waitFor, type RenderResult,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type SpeechEventShape = { type: string; agent_id?: string; utterance_id?: number };

const mocks = vi.hoisted(() => {
  const speechListeners = new Set<(e: SpeechEventShape) => void>();
  return {
    speechListeners,
    /** Mirrors `voice.ts::_fire`: every live listener sees every event. */
    fireSpeech: (e: SpeechEventShape): void => {
      for (const fn of [...speechListeners]) fn(e);
    },
    speakResponse: vi.fn(),
    onSpeechEvent: vi.fn((fn: (e: SpeechEventShape) => void) => {
      speechListeners.add(fn);
      return () => { speechListeners.delete(fn); };
    }),
    startListening: vi.fn(),
    stopListening: vi.fn(),
    armConversationMode: vi.fn(() => () => {}),
    disarmConversationMode: vi.fn(),
    markAgentReplyComplete: vi.fn(),
    speakMeetingReplies: vi.fn(),
    startCameraStream: vi.fn(async () => undefined),
    stopCameraStream: vi.fn(async () => undefined),
  };
});

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
import type { Agent } from '../../../store/types';

const AGENT_ID = 'bf764-host';
const THREAD_ID = 'bf764-thread';
const TTS_KEY = `hxi_chat_tts_${AGENT_ID}`;

/** The join timeout the component uses, mirrored so a test can outrun it. */
const SPEECH_JOIN_TIMEOUT_MS = 45000;

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

function spokenTexts(): string[] {
  return mocks.speakResponse.mock.calls.map((call) => String(call[0]));
}

/** Every utterance gets a distinct id, so the queue has something to correlate
 *  on and GUARD 1 (the undefined-id path) is not silently under test. */
function speakReturnsIds(): void {
  let next = 0;
  mocks.speakResponse.mockImplementation(() => { next += 1; return next; });
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.speechListeners.clear();
  localStorage.clear();
  serverMessages = [];
  installNetwork();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('BF-764 — a burst of arrivals is spoken one at a time', () => {
  it('does not start the second utterance until the first one ends', async () => {
    speakReturnsIds();
    seed();
    await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');

    // Before the fix BOTH were called in one synchronous pass, and the second
    // call cancelled the first mid-sentence.
    await waitFor(() => expect(spokenTexts()).toContain('First thing said.'));
    expect(spokenTexts()).not.toContain('Second thing said.');

    act(() => { mocks.fireSpeech({ type: 'end', agent_id: AGENT_ID, utterance_id: 1 }); });

    await waitFor(() => expect(spokenTexts()).toContain('Second thing said.'));
    expect(spokenTexts()).toEqual(['First thing said.', 'Second thing said.']);
  });

  it('speaks a burst in arrival order', async () => {
    speakReturnsIds();
    seed();
    await mount();

    await serverPushesBurst('One.', 'Two.', 'Three.');

    await waitFor(() => expect(spokenTexts()).toEqual(['One.']));
    act(() => { mocks.fireSpeech({ type: 'end', agent_id: AGENT_ID, utterance_id: 1 }); });
    await waitFor(() => expect(spokenTexts()).toEqual(['One.', 'Two.']));
    act(() => { mocks.fireSpeech({ type: 'end', agent_id: AGENT_ID, utterance_id: 2 }); });
    await waitFor(() => expect(spokenTexts()).toEqual(['One.', 'Two.', 'Three.']));
  });

  it('ignores an end that belongs to a different utterance', async () => {
    // Superseding an utterance emits a terminal 'end' carrying the SAME
    // agent_id (BF-767), so correlating on agent_id alone would advance the
    // queue on somebody else's completion and reintroduce the overlap.
    speakReturnsIds();
    seed();
    await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');
    await waitFor(() => expect(spokenTexts()).toEqual(['First thing said.']));

    act(() => { mocks.fireSpeech({ type: 'end', agent_id: AGENT_ID, utterance_id: 9999 }); });
    await act(async () => { await Promise.resolve(); });
    expect(spokenTexts()).toEqual(['First thing said.']);

    act(() => { mocks.fireSpeech({ type: 'end', agent_id: AGENT_ID, utterance_id: 1 }); });
    await waitFor(() => expect(spokenTexts()).toEqual(['First thing said.', 'Second thing said.']));
  });

  it('does not advance on a non-terminal speech event', async () => {
    speakReturnsIds();
    seed();
    await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');
    await waitFor(() => expect(spokenTexts()).toEqual(['First thing said.']));

    act(() => { mocks.fireSpeech({ type: 'start', agent_id: AGENT_ID, utterance_id: 1 }); });
    await act(async () => { await Promise.resolve(); });
    expect(spokenTexts()).toEqual(['First thing said.']);
  });

  // GUARD 1 — an arrival that produced no utterance must not wedge the queue.
  it('keeps going when there is no TTS engine to return an utterance id', async () => {
    // `speakResponse` returns undefined when nothing can speak (BF-290). No
    // 'end' will EVER arrive for it, so waiting on one would silence every
    // later message — strictly worse than the clipped audio being fixed.
    mocks.speakResponse.mockReturnValue(undefined);
    seed();
    await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');

    await waitFor(() => {
      expect(spokenTexts()).toEqual(['First thing said.', 'Second thing said.']);
    });
  });

  // GUARD 2 — a lost 'end' must not strand the rest of the queue.
  it('moves on when an utterance never reports that it ended', async () => {
    // `shouldAdvanceTime` keeps the clock moving so `waitFor` and the mount's
    // network round trips still progress; without it the harness starves.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    speakReturnsIds();
    seed();
    await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');
    await waitFor(() => expect(spokenTexts()).toEqual(['First thing said.']));

    // Nothing ever fires 'end' for utterance 1.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SPEECH_JOIN_TIMEOUT_MS + 1000);
    });

    expect(spokenTexts()).toEqual(['First thing said.', 'Second thing said.']);
  });

  it('does not fire the join timeout on an utterance that ended normally', async () => {
    // The timeout is a safety net. If it were short enough to fire on a real
    // utterance it would reintroduce the overlap it exists to prevent.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    speakReturnsIds();
    seed();
    await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');
    await waitFor(() => expect(spokenTexts()).toEqual(['First thing said.']));

    await act(async () => { await vi.advanceTimersByTimeAsync(SPEECH_JOIN_TIMEOUT_MS - 1000); });
    expect(spokenTexts()).toEqual(['First thing said.']);
  });

  it('leaves a single arrival unchanged', async () => {
    // The queue must not add a round trip to the ordinary one-message case.
    speakReturnsIds();
    seed();
    await mount();

    await serverPushesBurst('Only thing said.');

    await waitFor(() => expect(spokenTexts()).toEqual(['Only thing said.']));
  });

  it('survives the superseded utterance ending while the next one starts', async () => {
    // `speakResponse` calls `speechSynthesis.cancel()` on its first lines, and
    // the terminal 'end' that emits is delivered SYNCHRONOUSLY -- carrying the
    // SUPERSEDED utterance's older id, before this call has returned its own.
    // The listener is already armed at that instant, so a `const` bound to the
    // return value would be read in its temporal dead zone. voice.ts::_fire
    // swallows listener exceptions, so the throw would be invisible and the
    // queue would stall for the full join timeout instead of advancing.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let next = 0;
    mocks.speakResponse.mockImplementation(() => {
      // Exactly what cancel() does: emit the PREVIOUS utterance's terminal
      // 'end' synchronously, from inside this call.
      if (next > 0) mocks.fireSpeech({ type: 'end', agent_id: AGENT_ID, utterance_id: next });
      next += 1;
      return next;
    });
    seed();
    await mount();

    // THREE messages, deliberately. With two, an early 'end' that wrongly
    // resolved the next utterance would still leave the same final transcript,
    // so the mistake would be invisible. The third makes it observable.
    await serverPushesBurst('One.', 'Two.', 'Three.');
    await waitFor(() => expect(spokenTexts()).toEqual(['One.']));

    act(() => { mocks.fireSpeech({ type: 'end', agent_id: AGENT_ID, utterance_id: 1 }); });
    await waitFor(() => expect(spokenTexts()).toEqual(['One.', 'Two.']));

    // 'Two.' started, and starting it re-emitted 'One.'s terminal end. That
    // must NOT be mistaken for 'Two.' finishing.
    await act(async () => { await Promise.resolve(); });
    expect(spokenTexts()).toEqual(['One.', 'Two.']);

    act(() => { mocks.fireSpeech({ type: 'end', agent_id: AGENT_ID, utterance_id: 2 }); });

    // Reached WITHOUT the join timeout having to rescue it.
    await waitFor(() => expect(spokenTexts()).toEqual(['One.', 'Two.', 'Three.']));
    expect(vi.getTimerCount()).toBeLessThanOrEqual(1);
  });

  it('resolves when the utterance ends before speakResponse returns', async () => {
    // The mirror case: an 'end' carrying OUR OWN id, fired synchronously from
    // inside the call. Held and reconciled, not discarded -- discarding it
    // would strand this utterance until the join timeout.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let next = 0;
    mocks.speakResponse.mockImplementation(() => {
      next += 1;
      const mine = next;
      mocks.fireSpeech({ type: 'end', agent_id: AGENT_ID, utterance_id: mine });
      return mine;
    });
    seed();
    await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');

    await waitFor(() => {
      expect(spokenTexts()).toEqual(['First thing said.', 'Second thing said.']);
    });
  });

  it('does not start a second drain when an arrival lands mid-utterance', async () => {
    // Arrivals do not wait for the queue to be idle. A refresh landing while
    // an utterance is in flight must join the existing queue, not start a
    // second drain -- two drains would each call `speakResponse`, which is the
    // very cancellation this fix exists to stop.
    speakReturnsIds();
    seed();
    await mount();

    await serverPushesBurst('One.', 'Two.');
    await waitFor(() => expect(spokenTexts()).toEqual(['One.']));

    // A NEW refresh while 'One.' is still speaking.
    await serverPushesBurst('Three.');
    await act(async () => { await Promise.resolve(); });
    expect(spokenTexts()).toEqual(['One.']);

    act(() => { mocks.fireSpeech({ type: 'end', agent_id: AGENT_ID, utterance_id: 1 }); });
    await waitFor(() => expect(spokenTexts()).toEqual(['One.', 'Two.']));
    act(() => { mocks.fireSpeech({ type: 'end', agent_id: AGENT_ID, utterance_id: 2 }); });
    await waitFor(() => expect(spokenTexts()).toEqual(['One.', 'Two.', 'Three.']));
  });

  it('stops speaking a backlog once the tab unmounts', async () => {
    // Serialising means the queue outlives the render that filled it. The old
    // synchronous loop finished before unmount and could not do this.
    speakReturnsIds();
    seed();
    const view = await mount();

    await serverPushesBurst('First thing said.', 'Second thing said.');
    await waitFor(() => expect(spokenTexts()).toEqual(['First thing said.']));

    view.unmount();
    act(() => { mocks.fireSpeech({ type: 'end', agent_id: AGENT_ID, utterance_id: 1 }); });
    await act(async () => { await Promise.resolve(); });

    expect(spokenTexts()).toEqual(['First thing said.']);
  });
});
