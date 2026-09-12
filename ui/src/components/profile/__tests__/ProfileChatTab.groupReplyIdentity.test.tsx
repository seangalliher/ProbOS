import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => false,
  startListening: vi.fn(),
  stopListening: vi.fn(),
}));
vi.mock('../../../audio/conversationController', () => ({
  armConversationMode: vi.fn(() => () => {}),
  disarmConversationMode: vi.fn(),
  markAgentReplyComplete: vi.fn(),
}));
vi.mock('../../../audio/transformersStt', () => ({
  armTransformersStt: vi.fn(),
  disarmTransformersStt: vi.fn(),
  onTransformersTranscript: vi.fn(() => () => {}),
  onTransformersTranscribing: vi.fn(() => () => {}),
  onTransformersProgress: vi.fn(() => () => {}),
}));
vi.mock('../../../hooks/useCameraStream', () => ({
  startCameraStream: vi.fn(async () => undefined),
  stopCameraStream: vi.fn(async () => undefined),
}));
vi.mock('../MeetingView', () => ({ MeetingView: () => null }));
vi.mock('../../workspace/WorkspaceFilesRail', () => ({ WorkspaceFilesRail: () => null }));

import fixture from '../../../../e2e/fixtures/group-reply-identity.json';
import { ProfileChatTab } from '../ProfileChatTab';
import { formatChatTime } from '../ChatMessageRow';
import { claimSpeech, sharedSpeechLedger, speechKeyFor, threadDtoToMessage, resetSharedSpeechLedger } from '../profileTranscript';
import { useStore } from '../../../store/useStore';
import type { Agent, AgentProfileMessage, WSEvent } from '../../../store/types';
import { _resetTtsStatusForTests } from '../../../audio/voice';
import * as voice from '../../../audio/voice';
import { applyEmotionalModulation, PITCH_BOUNDS, RATE_BOUNDS } from '../../../audio/voiceModulation';
import { deriveAgentSignals } from '../avatarSignals';
import { computeProcessingDelay, computeTypingDelay } from '../../../chat/staggerReplies';

const THREAD_ID = fixture.thread.id;
const HOST_ID = fixture.thread.participants[0];
const GENERATION = 'a'.repeat(32);
const initialState = useStore.getState();

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function crewAgent(id: string, callsign: string): Agent {
  return {
    id, callsign, agentType: 'crew', displayName: '', pool: 'bridge',
    state: 'active', confidence: 1, trust: 0.5, tier: 'domain',
    isCrew: true, position: [0, 0, 0],
  } as Agent;
}

function transcript(): AgentProfileMessage[] {
  return useStore.getState().threadMessages.get(THREAD_ID) ?? [];
}

let resolvePost: (value: Response) => void;
let postSettled: boolean;
let localStorageBefore: Record<string, string>;
let scrollIntoViewBefore: PropertyDescriptor | undefined;
let deviceCalls: BrowserUtterance[] = [];

class BrowserUtterance {
  text: string;
  rate = 1;
  pitch = 1;
  volume = 1;
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(text: string) { this.text = text; }
}

async function endDevice(index: number): Promise<void> {
  expect(deviceCalls[index]?.onend).toBeTypeOf('function');
  await act(async () => { deviceCalls[index].onend!(); });
}

beforeEach(() => {
  localStorageBefore = Object.fromEntries(
    Object.keys(localStorage).map((key) => [key, localStorage.getItem(key) ?? '']),
  );
  localStorage.clear();
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
  vi.setSystemTime(new Date('2026-09-11T22:06:07.487Z'));
  vi.spyOn(crypto, 'randomUUID').mockReturnValue(fixture.request.metadata.client_message_id as ReturnType<Crypto['randomUUID']>);
  resetSharedSpeechLedger();
  _resetTtsStatusForTests();
  scrollIntoViewBefore = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView');
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    configurable: true, value: vi.fn(),
  });
  deviceCalls = [];
  vi.stubGlobal('SpeechSynthesisUtterance', BrowserUtterance);
  vi.stubGlobal('speechSynthesis', {
    cancel: vi.fn(() => { deviceCalls[deviceCalls.length - 1]?.onerror?.(); }),
    speak: vi.fn((utterance: BrowserUtterance) => { deviceCalls.push(utterance); utterance.onstart?.(); }),
    getVoices: () => [],
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  });
  postSettled = false;
  useStore.setState({ ...initialState, liveGeneration: null, liveSequence: 0 });
  useStore.getState().handleEvent({
    type: 'state_snapshot',
    data: {
      agents: [], connections: [], pools: [], system_mode: 'active',
      tc_n: 0, routing_entropy: 0,
    },
    timestamp: 1,
    stream: { generation: GENERATION, sequence: 0 },
  });
  useStore.setState({
    activeProfileAgent: HOST_ID,
    activeProfileThreadId: THREAD_ID,
    activeThreadId: null,
    agents: new Map(fixture.response.per_agent_replies.map((reply) => [
      reply.agent_id, crewAgent(reply.agent_id, reply.callsign),
    ])),
    chatThreads: new Map([[THREAD_ID, fixture.thread]]),
    threadIdByAgent: new Map(),
    threadMessages: new Map(),
    agentConversations: new Map(),
    artifactsByThread: new Map(),
    selectedArtifactId: null,
    chatDrafts: {},
    typingAgent: null,
    liveRepairEpoch: 0,
    liveThreadRefresh: null,
    voiceEnabled: false,
    callAudioEnabled: false,
    meetingChatVisible: true,
  });
});

afterEach(async () => {
  cleanup();
  await act(async () => { deviceCalls[deviceCalls.length - 1]?.onend?.(); });
  if (!postSettled && resolvePost) {
    resolvePost(response({ per_agent_replies: [] }));
    await act(async () => { await Promise.resolve(); });
  }
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  if (scrollIntoViewBefore) {
    Object.defineProperty(Element.prototype, 'scrollIntoView', scrollIntoViewBefore);
  } else {
    Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
  }
  useStore.setState(initialState, true);
  resetSharedSpeechLedger();
  _resetTtsStatusForTests();
  localStorage.clear();
  for (const [key, value] of Object.entries(localStorageBefore)) localStorage.setItem(key, value);
});

describe('#1372 group reply identity', () => {
  it('sends a group turn when secure-context randomUUID is unavailable', async () => {
    vi.stubGlobal('crypto', { randomUUID: undefined });
    const groupPost = vi.fn((init: RequestInit) => {
      const request = JSON.parse(String(init.body));
      return response({ ...fixture.response, metadata: request.metadata, per_agent_replies: [] });
    });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = String(input);
      if (url === `/api/threads/${THREAD_ID}/messages` && init?.method === 'POST') return groupPost(init);
      if (url === `/api/threads/${THREAD_ID}/messages?limit=200`) return response({ thread_id: THREAD_ID, messages: [] });
      if (url === `/api/threads/${THREAD_ID}`) return response(fixture.thread);
      if (url.endsWith('/chat/history')) return response({ memories: [] });
      if (url.endsWith('/profile')) return response({ voiceProfile: null });
      if (url.endsWith('/api/avatars/tts/status')) return response({ enabled: false, backend: 'browser' });
      if (url === '/api/voice/health') return response({ primary_stt: 'browser', engine: 'browser', backend_available: true, healthy: true });
      return response({});
    }));
    render(<ProfileChatTab agentId={HOST_ID} threadId={THREAD_ID} />);
    await act(async () => { await Promise.resolve(); });
    const composer = screen.getByPlaceholderText('Message...');
    fireEvent.change(composer, { target: { value: fixture.request.body } });
    await act(async () => { fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' }); });
    expect(groupPost).toHaveBeenCalledTimes(1);
    const request = JSON.parse(String(groupPost.mock.calls[0][0].body));
    expect(request.metadata.client_message_id).toEqual(expect.any(String));
    expect(request.metadata.client_message_id.length).toBeGreaterThan(0);
    expect(transcript()).toHaveLength(1);
    expect(transcript()[0].id).toBe(fixture.response.id);
    expect(transcript()[0].metadata?.client_message_id).toBe(request.metadata.client_message_id);
    expect(screen.getByRole('button', { name: /^Send$/ })).toBeDisabled();
    postSettled = true;
  });

  it('replaces transient legacy group replies with authoritative rows after an in-flight refresh', async () => {
    let holdHistory = false;
    let resolveHistory: ((value: Response) => void) | undefined;
    const pendingPost = new Promise<Response>((resolve) => { resolvePost = resolve; });
    const groupPost = vi.fn(() => pendingPost);
    const historyGet = vi.fn(() => holdHistory
      ? new Promise<Response>(resolve => { resolveHistory = resolve; })
      : Promise.resolve(response({ thread_id: THREAD_ID, messages: [] })));
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = String(input);
      if (url === `/api/threads/${THREAD_ID}/messages` && init?.method === 'POST') return groupPost();
      if (url === `/api/threads/${THREAD_ID}/messages?limit=200`) return historyGet();
      if (url === `/api/threads/${THREAD_ID}`) return response(fixture.thread);
      if (url.endsWith('/chat/history')) return response({ memories: [] });
      if (url.endsWith('/profile')) return response({ voiceProfile: null });
      if (url.endsWith('/api/avatars/tts/status')) return response({ enabled: false, backend: 'browser' });
      if (url === '/api/voice/health') return response({ primary_stt: 'browser', engine: 'browser', backend_available: true, healthy: true });
      return response({});
    }));
    render(<ProfileChatTab agentId={HOST_ID} threadId={THREAD_ID} />);
    await act(async () => { await Promise.resolve(); });
    expect(historyGet).toHaveBeenCalledTimes(1);
    const composer = screen.getByPlaceholderText('Message...');
    fireEvent.change(composer, { target: { value: fixture.request.body } });
    await act(async () => { fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' }); });
    expect(groupPost).toHaveBeenCalledTimes(1);
    holdHistory = true;
    await act(async () => {
      useStore.getState().handleEvent({ ...fixture.events[1], stream: { generation: GENERATION, sequence: 1 } } as WSEvent);
    });
    expect(historyGet).toHaveBeenCalledTimes(2);
    expect(resolveHistory).toBeTypeOf('function');
    await act(async () => {
      postSettled = true;
      resolvePost(response({ ...fixture.response, per_agent_replies: fixture.response.per_agent_replies.map(({ agent_id, callsign, text }) => ({ agent_id, callsign, text })) }));
    });
    for (const [index, reply] of fixture.response.per_agent_replies.entries()) {
      await act(async () => { await vi.advanceTimersByTimeAsync(computeProcessingDelay(index) + computeTypingDelay(reply.text)); });
    }
    expect(transcript().filter(message => message.id.startsWith('transient:'))).toHaveLength(2);
    expect(transcript()).toHaveLength(3);
    await act(async () => { resolveHistory!(response(fixture.history)); });
    expect(transcript().map(message => message.id)).toEqual(fixture.history.messages.map(message => message.id));
    const rendered = within(screen.getByTestId('chat-transcript'));
    expect(rendered.getAllByTestId('chat-msg-time')).toHaveLength(3);
    for (const reply of fixture.response.per_agent_replies) expect(rendered.getAllByText(reply.message.body, { exact: true })).toHaveLength(1);
  });

  it('preserves warm solo replacement when its HTTP mirror lands during a live history GET', async () => {
    const soloThread = { ...fixture.thread, participants: [HOST_ID] };
    const canonicalRows = fixture.history.messages.slice(0, 2);
    const pendingPost = new Promise<Response>((resolve) => { resolvePost = resolve; });
    let resolveHistory: ((value: Response) => void) | undefined;
    let holdHistory = false;
    const soloPost = vi.fn(() => pendingPost);
    const historyGet = vi.fn(() => holdHistory
      ? new Promise<Response>(resolve => { resolveHistory = resolve; })
      : Promise.resolve(response({ thread_id: THREAD_ID, messages: [] })));
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = String(input);
      if (url === `/api/agent/${HOST_ID}/chat` && init?.method === 'POST') return soloPost();
      if (url === `/api/threads/${THREAD_ID}/messages?limit=200`) return historyGet();
      if (url === `/api/threads/${THREAD_ID}`) return response(soloThread);
      if (url.endsWith('/chat/history')) return response({ memories: [] });
      if (url.endsWith('/profile')) return response({ voiceProfile: null });
      if (url.endsWith('/api/avatars/tts/status')) return response({ enabled: false, backend: 'browser' });
      if (url === '/api/voice/health') return response({ primary_stt: 'browser', engine: 'browser', backend_available: true, healthy: true });
      return response({});
    }));
    useStore.setState({ chatThreads: new Map([[THREAD_ID, soloThread]]) });
    render(<ProfileChatTab agentId={HOST_ID} threadId={THREAD_ID} />);
    await act(async () => { await Promise.resolve(); });
    expect(historyGet).toHaveBeenCalledTimes(1);
    expect(transcript()).toEqual([]);
    const composer = screen.getByPlaceholderText('Message...');
    fireEvent.change(composer, { target: { value: canonicalRows[0].body } });
    await act(async () => { fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' }); });
    expect(soloPost).toHaveBeenCalledTimes(1);
    holdHistory = true;
    await act(async () => {
      useStore.getState().handleEvent({ ...fixture.events[1], stream: { generation: GENERATION, sequence: 1 } } as WSEvent);
    });
    expect(historyGet).toHaveBeenCalledTimes(2);
    expect(resolveHistory).toBeTypeOf('function');
    await act(async () => {
      postSettled = true;
      resolvePost(response({ response: canonicalRows[1].body, thread_id: THREAD_ID }));
    });
    const localReply = transcript().find(message => message.role === 'agent');
    expect(localReply?.text).toBe(canonicalRows[1].body);
    expect(localReply?.id).not.toBe(canonicalRows[1].id);
    expect(localReply?.threadId).toBeUndefined();
    await act(async () => { resolveHistory!(response({ thread_id: THREAD_ID, messages: canonicalRows })); });
    expect(transcript().map(message => message.id)).toEqual(canonicalRows.map(message => message.id));
    const rendered = within(screen.getByTestId('chat-transcript'));
    expect(rendered.getAllByText(canonicalRows[1].body, { exact: true })).toHaveLength(1);
    expect(rendered.getAllByTestId('chat-msg-time')).toHaveLength(2);
  });

  it.each([
    'event-first', 'http-first', 'replayed-receipt', 'same-text-distinct-id',
    'history-seed', 'losing-claim', 'unmount', 'mute', 'room-shift', 'superseding-batch',
    'meeting-toggle', 'pending-profile-mute', 'room-before-http',
  ] as const)('uses real meeting audio and shared identity for %s', async (scenario) => {
    const receipt = structuredClone(fixture.response);
    if (scenario === 'same-text-distinct-id') {
      const first = receipt.per_agent_replies[0];
      receipt.per_agent_replies[1] = {
        ...first,
        message: { ...first.message, id: 'synthetic-negative-same-author-prose-distinct-id', created_at: 6 },
      };
    }
    const replies = receipt.per_agent_replies;
    for (const reply of replies) expect(reply.message.metadata.fanout).toBe('ad914');
    const meetingThread = { ...fixture.thread, metadata: { ...fixture.thread.metadata, meeting_active: true } };
    const canonicalRows = [fixture.history.messages[0], ...replies.map(reply => reply.message)];
    let history = scenario === 'history-seed' ? canonicalRows : [];
    const pendingPost = new Promise<Response>((resolve) => { resolvePost = resolve; });
    const groupPost = vi.fn((_init: RequestInit): Promise<Response> => pendingPost);
    const historyGet = vi.fn(() => response({ ...fixture.history, messages: history }));
    const profiles = new Map(fixture.response.per_agent_replies.map((reply, index) => [
      reply.agent_id, {
        voice_name: `identity-voice-${index}`,
        pitch: PITCH_BOUNDS[0] + (PITCH_BOUNDS[1] - PITCH_BOUNDS[0]) * (index + 1) / 3,
        rate: RATE_BOUNDS[0] + (RATE_BOUNDS[1] - RATE_BOUNDS[0]) * (index + 1) / 3,
        volume: 0.8,
      },
    ]));
    let releaseProfiles!: () => void;
    const pendingProfiles = new Promise<void>((resolve) => { releaseProfiles = resolve; });
    const profileGet = vi.fn((id: string): Response | Promise<Response> => scenario === 'pending-profile-mute'
      ? pendingProfiles.then(() => response({ voiceProfile: profiles.get(id) }))
      : response({ voiceProfile: profiles.get(id) }));
    const speechCalls = vi.spyOn(voice, 'speakResponse');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = String(input);
      if (url === `/api/threads/${THREAD_ID}/messages` && init?.method === 'POST') return groupPost(init);
      if (url === `/api/threads/${THREAD_ID}/messages?limit=200`) return historyGet();
      if (url === `/api/threads/${THREAD_ID}`) return response(meetingThread);
      if (url.endsWith('/messages?limit=200')) return response({ messages: [], thread_id: 'synthetic-negative-other-room' });
      if (url.endsWith('/chat/history')) return response({ memories: [] });
      const profileAgent = fixture.thread.participants.find(id => url === `/api/agent/${id}/profile`);
      if (profileAgent) return profileGet(profileAgent);
      if (url.endsWith('/api/avatars/tts/status')) return response({ enabled: false, backend: 'browser' });
      if (url === '/api/voice/health') return response({ primary_stt: 'browser', engine: 'browser', backend_available: true, healthy: true });
      return response({});
    }));
    useStore.setState({ chatThreads: new Map([[THREAD_ID, meetingThread]]), callAudioEnabled: true });
    for (const participant of fixture.thread.participants) expect(useStore.getState().agents.get(participant)?.isCrew).toBe(true);
    const view = render(<ProfileChatTab agentId={HOST_ID} threadId={THREAD_ID} />);
    await act(async () => { await Promise.resolve(); });
    expect(historyGet).toHaveBeenCalledTimes(1);
    expect(transcript().map(row => row.id)).toEqual(history.map(row => row.id));
    expect(deviceCalls).toHaveLength(0);
    expect(fixture.thread.participants).toHaveLength(2);
    for (const participant of fixture.thread.participants) expect(profileGet).toHaveBeenCalledWith(participant);
    const assertSpeaker = (deviceIndex: number, replyIndex: number): void => {
      const reply = replies[replyIndex];
      const profile = profiles.get(reply.agent_id)!;
      const effective = applyEmotionalModulation(profile, deriveAgentSignals(
        reply.agent_id,
        useStore.getState() as unknown as Parameters<typeof deriveAgentSignals>[1],
      ));
      expect(deviceCalls[deviceIndex].pitch).toBeCloseTo(effective.pitch!);
      expect(deviceCalls[deviceIndex].rate).toBeCloseTo(effective.rate!);
      expect(speechCalls.mock.calls[deviceIndex][1]).toEqual(profile);
      expect(speechCalls.mock.calls[deviceIndex][2]).toBe(reply.agent_id);
      expect(speechCalls.mock.calls[deviceIndex][5]).toMatch(/^profile-chat-/);
      expect(useStore.getState().typingAgent).toMatchObject({
        threadId: THREAD_ID, agentId: reply.agent_id, verb: 'speaking',
      });
    };
    const send = async (): Promise<void> => {
      const composer = screen.getByPlaceholderText('Message...');
      fireEvent.change(composer, { target: { value: fixture.request.body } });
      await act(async () => { fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' }); });
    };
    await send();
    expect(groupPost).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(groupPost.mock.calls[0][0].body)).metadata).toEqual(fixture.request.metadata);
    const push = async (): Promise<void> => {
      history = canonicalRows;
      for (const [index, event] of fixture.events.entries()) {
        const readsBefore = historyGet.mock.calls.length;
        await act(async () => {
          useStore.getState().handleEvent({
            ...event,
            data: {
              ...event.data, message_id: canonicalRows[index].id,
              author_id: canonicalRows[index].author_id, created_at: canonicalRows[index].created_at,
            },
            stream: { generation: GENERATION, sequence: useStore.getState().liveSequence + 1 },
          } as WSEvent);
        });
        expect(historyGet.mock.calls.length).toBeGreaterThan(readsBefore);
        expect(transcript().map(row => row.id)).toEqual(canonicalRows.map(row => row.id));
      }
    };
    if (scenario === 'event-first') {
      await push();
      expect(postSettled).toBe(false);
      expect(transcript().filter(row => row.role === 'agent').map(row => row.authorId))
        .toEqual(replies.map(reply => reply.agent_id));
      expect(deviceCalls, 'Live group hydration leaves speaking to the meeting sequencer').toHaveLength(0);
      expect(speechCalls).not.toHaveBeenCalled();
    }
    if (scenario === 'losing-claim') {
      expect(claimSpeech(sharedSpeechLedger(), THREAD_ID,
        threadDtoToMessage(replies[0].message, useStore.getState().agents))).toBe(true);
    }
    const otherTyping = { threadId: 'synthetic-negative-other-room', agentId: HOST_ID, callsign: 'Other crew' };
    const moveToOtherRoom = async (): Promise<void> => {
      const other = { ...meetingThread, id: otherTyping.threadId };
      await act(async () => {
        useStore.getState().setChatThread(other);
        useStore.setState({ activeProfileThreadId: other.id });
        view.rerender(<ProfileChatTab agentId={HOST_ID} threadId={other.id} />);
      });
      await act(async () => { useStore.getState().setTypingAgent(otherTyping); });
    };
    const assertAcceptedRows = (): void => {
      expect(transcript().map(row => row.id)).toEqual(canonicalRows.map(row => row.id));
      expect(transcript().map(row => row.timestamp)).toEqual(canonicalRows.map(row => row.created_at));
      expect(transcript().map(row => row.text)).toEqual(canonicalRows.map(row => row.body));
      expect(useStore.getState().agentConversations.get(HOST_ID)?.messages.filter(row => row.role === 'agent'))
        .toEqual(replies.map(reply => threadDtoToMessage(reply.message, useStore.getState().agents)));
      expect(useStore.getState().threadMessages.get(otherTyping.threadId) ?? []).toEqual([]);
    };
    if (scenario === 'room-before-http') await moveToOtherRoom();
    await act(async () => { postSettled = true; resolvePost(response(receipt)); });
    if (scenario === 'room-before-http') {
      assertAcceptedRows();
      expect(deviceCalls).toHaveLength(0);
      expect(speechCalls).not.toHaveBeenCalled();
      expect(useStore.getState().typingAgent).toEqual(otherTyping);
      return;
    }
    if (scenario === 'pending-profile-mute') {
      expect(deviceCalls).toHaveLength(0);
      expect(transcript().map(row => row.id)).toEqual([canonicalRows[0].id]);
      expect(historyGet).toHaveBeenCalledTimes(1);
      await act(async () => { useStore.getState().setCallAudioEnabled(false); });
      assertAcceptedRows();
      const settledRows = transcript();
      await act(async () => { releaseProfiles(); });
      expect(transcript()).toBe(settledRows);
      expect(deviceCalls).toHaveLength(0);
      expect(speechCalls).not.toHaveBeenCalled();
      expect(useStore.getState().typingAgent).toBeNull();
      return;
    }
    if (scenario === 'history-seed') {
      expect(deviceCalls).toHaveLength(0);
      expect(useStore.getState().typingAgent).toBeNull();
      expect(transcript().map(row => row.id)).toEqual(canonicalRows.map(row => row.id));
      return;
    }
    expect(deviceCalls.map(utterance => utterance.text)).toEqual([
      replies[scenario === 'losing-claim' ? 1 : 0].message.body,
    ]);
    assertSpeaker(0, scenario === 'losing-claim' ? 1 : 0);
    if (scenario === 'losing-claim') {
      expect(transcript().some(row => row.id === replies[0].message.id)).toBe(true);
      await endDevice(0);
      expect(useStore.getState().typingAgent).toBeNull();
      expect(transcript().map(row => row.id)).toEqual(canonicalRows.map(row => row.id));
      return;
    }
    if (scenario === 'superseding-batch') {
      expect(historyGet).toHaveBeenCalledTimes(1);
      expect(transcript().map(row => row.id)).toEqual([canonicalRows[0].id]);
      const nextReceipt = {
        ...receipt,
        per_agent_replies: replies.map(reply => ({
          ...reply,
          message: { ...reply.message, id: `next-batch-${reply.message.id}`, created_at: reply.message.created_at + 10 },
        })),
      };
      groupPost.mockImplementationOnce(async () => response(nextReceipt));
      await send();
      expect(groupPost).toHaveBeenCalledTimes(2);
      expect(transcript().map(row => row.id)).toEqual(canonicalRows.map(row => row.id));
      await endDevice(0);
      expect(deviceCalls).toHaveLength(2);
      assertSpeaker(1, 0);
      expect(transcript().map(row => row.id)).toEqual(canonicalRows.map(row => row.id));
      await endDevice(1);
      expect(deviceCalls).toHaveLength(3);
      assertSpeaker(2, 1);
      expect(transcript().map(row => row.id)).toEqual([
        ...canonicalRows.map(row => row.id), nextReceipt.per_agent_replies[0].message.id,
      ]);
      await endDevice(2);
      expect(transcript().map(row => row.id)).toEqual([
        ...canonicalRows.map(row => row.id), ...nextReceipt.per_agent_replies.map(reply => reply.message.id),
      ]);
      expect(useStore.getState().threadMessages.get(otherTyping.threadId) ?? []).toEqual([]);
      expect(useStore.getState().typingAgent).toBeNull();
      expect(deviceCalls).toHaveLength(3);
      return;
    }
    if (scenario === 'unmount' || scenario === 'mute' || scenario === 'room-shift' || scenario === 'meeting-toggle') {
      expect(historyGet).toHaveBeenCalledTimes(1);
      expect(transcript().map(row => row.id)).toEqual([canonicalRows[0].id]);
      if (scenario === 'unmount') view.unmount();
      if (scenario === 'mute') await act(async () => { useStore.getState().setCallAudioEnabled(false); });
      if (scenario === 'room-shift') await moveToOtherRoom();
      if (scenario === 'meeting-toggle') {
        await act(async () => {
          useStore.getState().setChatThread({
            ...meetingThread, metadata: { ...meetingThread.metadata, meeting_active: false },
          });
        });
      }
      assertAcceptedRows();
      await endDevice(0);
      assertAcceptedRows();
      expect(deviceCalls).toHaveLength(1);
      expect(useStore.getState().typingAgent).toEqual(scenario === 'room-shift' ? otherTyping : null);
      if (scenario === 'mute') {
        expect(transcript().map(row => row.id), 'Muting audio does not discard accepted HTTP replies')
          .toEqual(canonicalRows.map(row => row.id));
      }
      return;
    }
    if (scenario !== 'event-first') {
      expect(transcript().some(row => row.id === replies[0].message.id)).toBe(false);
      expect(transcript().some(row => row.id === replies[1].message.id)).toBe(false);
    }
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(deviceCalls).toHaveLength(1);
    assertSpeaker(0, 0);
    await endDevice(0);
    expect(deviceCalls.map(utterance => utterance.text)).toEqual(replies.map(reply => reply.message.body));
    assertSpeaker(1, 1);
    expect(speechCalls.mock.calls[1][5]).toBe(speechCalls.mock.calls[0][5]);
    if (scenario !== 'same-text-distinct-id') {
      expect(deviceCalls[0].pitch).not.toBe(deviceCalls[1].pitch);
      expect(deviceCalls[0].rate).not.toBe(deviceCalls[1].rate);
    }
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(deviceCalls).toHaveLength(2);
    assertSpeaker(1, 1);
    if (scenario !== 'event-first') {
      expect(transcript().some(row => row.id === replies[0].message.id)).toBe(true);
      expect(transcript().some(row => row.id === replies[1].message.id)).toBe(false);
    }
    await endDevice(1);
    expect(useStore.getState().typingAgent).toBeNull();
    expect(transcript().map(row => row.id)).toEqual(canonicalRows.map(row => row.id));
    expect(transcript().map(row => row.timestamp)).toEqual(canonicalRows.map(row => row.created_at));
    const memoryBeforeReplay = useStore.getState().agentConversations.get(HOST_ID)!.messages;
    const replyMemory = memoryBeforeReplay.filter(message => message.role === 'agent');
    expect(replyMemory).toEqual(replies.map(reply => threadDtoToMessage(reply.message, useStore.getState().agents)));
    await push();
    expect(useStore.getState().agentConversations.get(HOST_ID)!.messages).toBe(memoryBeforeReplay);
    if (scenario === 'replayed-receipt') {
      groupPost.mockImplementationOnce(async () => response(receipt));
      await send();
      expect(groupPost).toHaveBeenCalledTimes(2);
      expect(useStore.getState().typingAgent).toBeNull();
      const replayedMemory = useStore.getState().agentConversations.get(HOST_ID)!.messages;
      expect(replayedMemory.filter(message => message.role === 'agent')).toEqual(replyMemory);
      expect(replayedMemory.filter(message => message.role === 'user'))
        .toHaveLength(memoryBeforeReplay.filter(message => message.role === 'user').length + 1);
    }
    expect(deviceCalls).toHaveLength(2);
    expect(within(screen.getByTestId('chat-transcript')).getAllByTestId('chat-msg-time')).toHaveLength(3);
  });

  it.each(['text-room', 'legacy-text-room', 'roster-transition', 'meeting-transition'] as const)(
    'keeps observed group rows silent through %s but admits new solo arrivals', async (scenario) => {
      const delayedReceipt = structuredClone(fixture.response);
      const startedInMeeting = scenario === 'roster-transition' || scenario === 'meeting-transition';
      let currentThread = {
        ...fixture.thread, metadata: { ...fixture.thread.metadata, meeting_active: startedInMeeting },
      };
      let history: typeof fixture.history.messages = [];
      const pendingPost = new Promise<Response>((resolve) => { resolvePost = resolve; });
      const groupPost = vi.fn((_init: RequestInit): Promise<Response> => pendingPost);
      const historyGet = vi.fn(() => response({ ...fixture.history, messages: history }));
      vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === `/api/threads/${THREAD_ID}/messages` && init?.method === 'POST') return groupPost(init);
        if (url === `/api/threads/${THREAD_ID}/messages?limit=200`) return historyGet();
        if (url === `/api/threads/${THREAD_ID}`) return response(currentThread);
        if (url.endsWith('/chat/history')) return response({ memories: [] });
        if (url.endsWith('/profile')) return response({ voiceProfile: { pitch: 1, rate: 1, volume: 0.8 } });
        if (url.endsWith('/api/avatars/tts/status')) return response({ enabled: false, backend: 'browser' });
        if (url === '/api/voice/health') return response({ primary_stt: 'browser', engine: 'browser', backend_available: true, healthy: true });
        return response({});
      }));
      useStore.setState({
        chatThreads: new Map([[THREAD_ID, currentThread]]), voiceEnabled: true, callAudioEnabled: true,
      });
      expect(currentThread.participants).toHaveLength(2);
      for (const id of currentThread.participants) expect(useStore.getState().agents.get(id)?.isCrew).toBe(true);
      render(<ProfileChatTab agentId={HOST_ID} threadId={THREAD_ID} />);
      await act(async () => { await Promise.resolve(); });
      expect(historyGet).toHaveBeenCalledTimes(1);
      expect(transcript()).toEqual([]);
      const composer = screen.getByPlaceholderText('Message...');
      fireEvent.change(composer, { target: { value: fixture.request.body } });
      await act(async () => { fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' }); });
      expect(groupPost).toHaveBeenCalledTimes(1);
      history = structuredClone(fixture.history.messages);
      if (scenario === 'legacy-text-room') {
        for (const row of history) {
          if (row.role === 'agent') Reflect.deleteProperty(row.metadata, 'fanout');
        }
        for (const reply of delayedReceipt.per_agent_replies) Reflect.deleteProperty(reply.message.metadata, 'fanout');
      }
      for (const event of fixture.events) {
        const readsBefore = historyGet.mock.calls.length;
        await act(async () => {
          useStore.getState().handleEvent({
            ...event, stream: { generation: GENERATION, sequence: useStore.getState().liveSequence + 1 },
          } as WSEvent);
        });
        expect(historyGet.mock.calls.length).toBeGreaterThan(readsBefore);
        expect(transcript().map(row => row.id)).toEqual(history.map(row => row.id));
      }
      expect(postSettled).toBe(false);
      expect(transcript().filter(row => row.role === 'agent').map(row => row.authorId))
        .toEqual(fixture.thread.participants);
      expect(deviceCalls).toHaveLength(0);
      const observedReplies = transcript().filter(row => row.role === 'agent');
      expect(observedReplies).toHaveLength(2);
      for (const row of observedReplies) {
        expect(sharedSpeechLedger().scopes.get(THREAD_ID)?.keys.has(speechKeyFor(row, HOST_ID)))
          .toBe(!startedInMeeting);
      }
      if (scenario === 'meeting-transition') {
        currentThread = { ...currentThread, metadata: { ...currentThread.metadata, meeting_active: false } };
        await act(async () => { useStore.getState().setChatThread(currentThread); });
        expect(deviceCalls).toHaveLength(0);
        for (const row of observedReplies) {
          expect(sharedSpeechLedger().scopes.get(THREAD_ID)?.keys.has(speechKeyFor(row, HOST_ID))).toBe(true);
        }
        currentThread = { ...currentThread, metadata: { ...currentThread.metadata, meeting_active: true } };
        await act(async () => { useStore.getState().setChatThread(currentThread); });
        expect(deviceCalls).toHaveLength(0);
      }
      currentThread = { ...currentThread, participants: [HOST_ID] };
      await act(async () => { useStore.getState().setChatThread(currentThread); });
      expect(currentThread.participants.filter(id => useStore.getState().agents.get(id)?.isCrew)).toHaveLength(1);
      expect(deviceCalls).toHaveLength(0);
      for (const row of observedReplies) {
        expect(sharedSpeechLedger().scopes.get(THREAD_ID)?.keys.has(speechKeyFor(row, HOST_ID))).toBe(true);
      }
      const newRow = {
        ...fixture.response.per_agent_replies[0].message,
        id: 'identity-post-transition', body: 'A genuinely new solo arrival.', created_at: 10,
      };
      history = [...history, newRow];
      const readsBefore = historyGet.mock.calls.length;
      await act(async () => {
        useStore.getState().handleEvent({
          ...fixture.events[1],
          data: { ...fixture.events[1].data, message_id: newRow.id, author_id: newRow.author_id, created_at: newRow.created_at },
          stream: { generation: GENERATION, sequence: useStore.getState().liveSequence + 1 },
        } as WSEvent);
      });
      expect(historyGet.mock.calls.length).toBeGreaterThan(readsBefore);
      expect(transcript().map(row => row.id)).toEqual(history.map(row => row.id));
      expect(deviceCalls.map(utterance => utterance.text)).toEqual([newRow.body]);
      await endDevice(0);
      expect(deviceCalls).toHaveLength(1);
      await act(async () => { postSettled = true; resolvePost(response(delayedReceipt)); });
      expect(deviceCalls).toHaveLength(1);
      expect(transcript().filter(row => row.role === 'agent')).toHaveLength(3);
    },
  );

  it('keeps three canonical rendered rows when live events precede HTTP and delayed reveal', async () => {
    vi.setSystemTime(new Date((fixture.response.created_at - 1) * 1000));
    let history = { ...fixture.history, messages: [] as typeof fixture.history.messages };
    const pendingPost = new Promise<Response>((resolve) => { resolvePost = resolve; });
    const groupPost = vi.fn((_init: RequestInit): Promise<Response> => pendingPost);
    const soloPost = vi.fn((_init: RequestInit): Response => response({ response: 'History received.' }));
    const historyGet = vi.fn((): Response => response(history));
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === `/api/agent/${HOST_ID}/chat` && method === 'POST') return soloPost(init!);
      if (url === `/api/threads/${THREAD_ID}/messages` && method === 'POST') {
        return groupPost(init!);
      }
      if (url === `/api/threads/${THREAD_ID}/messages?limit=200` && method === 'GET') {
        return historyGet();
      }
      if (url === `/api/threads/${THREAD_ID}`) return response(fixture.thread);
      if (url.endsWith('/chat/history')) return response({ memories: [] });
      if (url.endsWith('/profile')) return response({ voiceProfile: null });
      if (url.endsWith('/api/avatars/tts/status')) return response({ enabled: false, backend: 'browser' });
      if (url === '/api/voice/health') {
        return response({ primary_stt: 'browser', engine: 'browser', backend_available: true, healthy: true });
      }
      return response({});
    }));

    expect(fixture.thread.participants).toHaveLength(2);
    for (const participant of fixture.thread.participants) {
      expect(useStore.getState().agents.get(participant)?.isCrew).toBe(true);
    }
    const view = render(<ProfileChatTab agentId={HOST_ID} threadId={THREAD_ID} />);
    await act(async () => { await Promise.resolve(); });
    expect(historyGet).toHaveBeenCalled();
    expect(useStore.getState().threadMessages.get(THREAD_ID)).toEqual([]);
    expect(useStore.getState().liveGeneration).toBe(GENERATION);

    const composer = screen.getByPlaceholderText('Message...');
    fireEvent.change(composer, { target: { value: fixture.request.body } });
    await act(async () => { fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' }); });
    expect(groupPost).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(groupPost.mock.calls[0][0].body))).toEqual({ ...fixture.request, attachment_ids: [] });
    expect(transcript()).toHaveLength(1);
    expect(transcript()[0].text).toBe(fixture.request.body);
    expect(transcript()[0]).toMatchObject({
      threadId: THREAD_ID, role: 'user', authorId: 'captain', optimistic: true,
      metadata: fixture.request.metadata,
    });

    history = fixture.history;
    for (const [index, event] of fixture.events.entries()) {
      const readsBefore = historyGet.mock.calls.length;
      const frame: WSEvent = {
        ...event, stream: { generation: GENERATION, sequence: index + 1 },
      };
      await act(async () => { useStore.getState().handleEvent(frame); });
      expect(useStore.getState().liveSequence).toBe(index + 1);
      expect(useStore.getState().liveThreadRefresh).toEqual({
        threadId: THREAD_ID, requestId: event.data.message_id,
      });
      expect(historyGet.mock.calls.length).toBeGreaterThan(readsBefore);
    }

    const rendered = within(screen.getByTestId('chat-transcript'));
    const canonicalIds = fixture.history.messages.map((message) => message.id);
    expect(postSettled).toBe(false);
    expect(transcript().map((message) => message.id)).toEqual(canonicalIds);
    expect(transcript().filter((message) => message.role === 'user')).toHaveLength(1);
    expect(transcript().filter((message) => message.role === 'agent').map((message) => message.authorId))
      .toEqual(fixture.thread.participants);
    expect(transcript().map((message) => message.timestamp))
      .toEqual(fixture.history.messages.map((message) => message.created_at));
    expect(rendered.getAllByTestId('chat-msg-time').map((element) => element.textContent))
      .toEqual(fixture.history.messages.map((message) => formatChatTime(message.created_at)));
    for (const message of fixture.history.messages) {
      expect(rendered.getAllByText(message.body, { exact: true })).toHaveLength(1);
    }

    await act(async () => {
      postSettled = true;
      resolvePost(response(fixture.response));
    });
    expect(rendered.getAllByTestId('chat-msg-time')).toHaveLength(3);
    for (const [index, reply] of fixture.response.per_agent_replies.entries()) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(computeProcessingDelay(index) + computeTypingDelay(reply.text));
      });
    }

    expect(groupPost).toHaveBeenCalledTimes(1);
    expect(useStore.getState().typingAgent).toBeNull();
    expect.soft(rendered.getAllByTestId('chat-msg-time'), 'delayed HTTP reveal must not turn three rows into five')
      .toHaveLength(3);
    for (const message of fixture.history.messages) {
      expect.soft(rendered.getAllByText(message.body, { exact: true })).toHaveLength(1);
      expect.soft(transcript().filter((row) => row.id === message.id)).toHaveLength(1);
      expect.soft(transcript().find((row) => row.id === message.id)?.timestamp).toBe(message.created_at);
    }
    expect.soft(transcript().map((message) => message.id)).toEqual(canonicalIds);
    expect(useStore.getState().agentConversations.get(HOST_ID)?.messages
      .filter(message => message.role === 'agent').map(message => message.text))
      .toEqual(fixture.response.per_agent_replies.map(reply => reply.message.body));
    const memoryBeforeReplay = useStore.getState().agentConversations.get(HOST_ID)!.messages;
    expect(memoryBeforeReplay.filter(message => message.role === 'agent')).toEqual(
      fixture.response.per_agent_replies.map(reply => threadDtoToMessage(reply.message, useStore.getState().agents)),
    );
    await act(async () => {
      for (const [index, event] of fixture.events.entries()) {
        useStore.getState().handleEvent({
          ...event, stream: { generation: GENERATION, sequence: index + 1 },
        } as WSEvent);
      }
    });
    expect(useStore.getState().agentConversations.get(HOST_ID)!.messages).toBe(memoryBeforeReplay);
    await act(async () => {
      useStore.setState({ activeProfileThreadId: null, activeThreadId: null, threadIdByAgent: new Map() });
      view.rerender(<ProfileChatTab agentId={HOST_ID} />);
    });
    const soloComposer = screen.getByPlaceholderText('Message...');
    fireEvent.change(soloComposer, { target: { value: 'Continue with the group replies.' } });
    await act(async () => { fireEvent.keyDown(soloComposer, { key: 'Enter', code: 'Enter' }); });
    expect(soloPost).toHaveBeenCalledTimes(1);
    expect(groupPost).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(soloPost.mock.calls[0][0].body))).toMatchObject({
      message: 'Continue with the group replies.',
      history: [
        { role: 'user', text: fixture.request.body },
        ...fixture.response.per_agent_replies.map(reply => ({ role: 'agent', text: reply.message.body })),
      ],
    });
  });

  it.each(['http-first', 'stale-get', 'room-switch', 'identical-sends'] as const)(
    'keeps canonical identities and captured ownership for %s', async (scenario) => {
      let history = { ...fixture.history, messages: [] as typeof fixture.history.messages };
      let holdHistory = false;
      let resolveHistory: ((value: Response) => void) | undefined;
      const pendingPost = new Promise<Response>((resolve) => { resolvePost = resolve; });
      const groupPost = vi.fn((_init: RequestInit): Promise<Response> => pendingPost);
      const historyGet = vi.fn((): Response | Promise<Response> => {
        if (holdHistory) return new Promise<Response>((resolve) => { resolveHistory = resolve; });
        return response(history);
      });
      const otherThread = { ...fixture.thread, id: 'other-room', title: 'Other room' };
      vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = String(input);
        if (url === `/api/threads/${THREAD_ID}/messages` && init?.method === 'POST') return groupPost(init);
        if (url === `/api/threads/${THREAD_ID}/messages?limit=200`) return historyGet();
        if (url === `/api/threads/${THREAD_ID}`) return response(fixture.thread);
        if (url === '/api/threads/other-room/messages?limit=200') return response({ messages: [], thread_id: 'other-room' });
        if (url === '/api/threads/other-room') return response(otherThread);
        if (url.endsWith('/chat/history')) return response({ memories: [] });
        if (url.endsWith('/profile')) return response({ voiceProfile: null });
        if (url.endsWith('/api/avatars/tts/status')) return response({ enabled: false, backend: 'browser' });
        if (url === '/api/voice/health') return response({ primary_stt: 'browser', engine: 'browser', backend_available: true, healthy: true });
        return response({});
      }));

      const view = render(<ProfileChatTab agentId={HOST_ID} threadId={THREAD_ID} />);
      await act(async () => { await Promise.resolve(); });
      expect(historyGet).toHaveBeenCalledTimes(1);
      expect(transcript()).toEqual([]);
      const send = async (): Promise<void> => {
        const composer = screen.getByPlaceholderText('Message...');
        fireEvent.change(composer, { target: { value: fixture.request.body } });
        await act(async () => { fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' }); });
      };
      await send();
      expect(groupPost).toHaveBeenCalledTimes(1);
      expect(JSON.parse(String(groupPost.mock.calls[0][0].body))).toEqual({ ...fixture.request, attachment_ids: [] });
      expect(transcript()).toHaveLength(1);
      expect(transcript()[0].metadata).toEqual(fixture.request.metadata);

      if (scenario === 'stale-get') {
        holdHistory = true;
        await act(async () => { useStore.setState({ liveRepairEpoch: useStore.getState().liveRepairEpoch + 1 }); });
        expect(historyGet).toHaveBeenCalledTimes(2);
        expect(resolveHistory).toBeTypeOf('function');
      }

      await act(async () => {
        postSettled = true;
        resolvePost(response(fixture.response));
      });
      expect(transcript().filter(message => message.role === 'user')).toEqual([
        expect.objectContaining({ id: fixture.response.id, timestamp: fixture.response.created_at, metadata: fixture.response.metadata }),
      ]);
      expect(transcript().some(message => message.optimistic)).toBe(false);

      const otherTyping = { threadId: 'other-room', agentId: HOST_ID, callsign: 'Other crew' };
      if (scenario === 'room-switch') {
        await act(async () => {
          useStore.getState().setChatThread(otherThread);
          useStore.setState({ activeProfileThreadId: 'other-room' });
          view.rerender(<ProfileChatTab agentId={HOST_ID} threadId="other-room" />);
        });
        expect(useStore.getState().typingAgent).toBeNull();
        await act(async () => { useStore.getState().setTypingAgent(otherTyping); });
      }
      for (const [index, reply] of fixture.response.per_agent_replies.entries()) {
        await act(async () => {
          await vi.advanceTimersByTimeAsync(computeProcessingDelay(index) + computeTypingDelay(reply.text));
        });
      }
      const canonicalIds = fixture.history.messages.map(message => message.id);
      expect(transcript().map(message => message.id)).toEqual(canonicalIds);
      expect(transcript().map(message => message.timestamp)).toEqual(fixture.history.messages.map(message => message.created_at));

      if (scenario === 'stale-get') {
        await act(async () => { resolveHistory!(response(history)); });
        holdHistory = false;
        expect(transcript().map(message => message.id)).toEqual(canonicalIds);
      }
      if (scenario === 'room-switch') {
        expect(useStore.getState().typingAgent).toEqual(otherTyping);
        expect(useStore.getState().threadMessages.get('other-room')).toEqual([]);
        const rendered = within(screen.getByTestId('chat-transcript'));
        for (const message of fixture.history.messages) expect(rendered.queryByText(message.body, { exact: true })).toBeNull();
        expect(groupPost).toHaveBeenCalledTimes(1);
        return;
      }

      history = fixture.history;
      for (const [index, event] of fixture.events.entries()) {
        const readsBefore = historyGet.mock.calls.length;
        await act(async () => {
          useStore.getState().handleEvent({ ...event, stream: { generation: GENERATION, sequence: index + 1 } } as WSEvent);
        });
        expect(historyGet.mock.calls.length).toBeGreaterThan(readsBefore);
      }
      expect(transcript().map(message => message.id)).toEqual(canonicalIds);
      const rendered = within(screen.getByTestId('chat-transcript'));
      expect(rendered.getAllByTestId('chat-msg-time')).toHaveLength(3);
      for (const message of fixture.history.messages) expect(rendered.getAllByText(message.body, { exact: true })).toHaveLength(1);

      if (scenario === 'identical-sends') {
        const secondToken = 'identity-send-2';
        vi.mocked(crypto.randomUUID).mockReturnValue(secondToken as ReturnType<Crypto['randomUUID']>);
        let resolveSecond!: (value: Response) => void;
        groupPost.mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveSecond = resolve; }));
        await send();
        expect(groupPost).toHaveBeenCalledTimes(2);
        expect(JSON.parse(String(groupPost.mock.calls[1][0].body))).toEqual({
          ...fixture.request, attachment_ids: [], metadata: { client_message_id: secondToken },
        });
        expect(transcript().filter(message => message.role === 'user')).toHaveLength(2);
        expect(transcript().filter(message => message.role === 'user').map(message => message.metadata?.client_message_id))
          .toEqual([fixture.request.metadata.client_message_id, secondToken]);
        await act(async () => {
          resolveSecond(response({
            ...fixture.response, id: 'identity-captain-2', created_at: 6,
            metadata: { client_message_id: secondToken }, per_agent_replies: [],
          }));
        });
        expect(transcript().filter(message => message.role === 'user').map(message => message.id))
          .toEqual([fixture.response.id, 'identity-captain-2']);
        expect(rendered.getAllByText(fixture.request.body, { exact: true })).toHaveLength(2);
      } else {
        expect(groupPost).toHaveBeenCalledTimes(1);
      }
    },
  );
});