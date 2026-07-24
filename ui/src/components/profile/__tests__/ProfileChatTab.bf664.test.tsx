/** BF-664: mounted capped-transcript auto-scroll regressions.
 *
 * Mounts the real ProfileChatTab against the real Zustand store. Voice/speech
 * and MeetingView use the proven AD-984b isolation header; transcript updates,
 * caps, effects, and DOM scroll behavior remain production code.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  speakResponseMock: vi.fn(),
  startListeningMock: vi.fn(),
  stopListeningMock: vi.fn(),
  supportedRef: { v: true },
}));

vi.mock('../../../audio/voice', () => ({
  getServerPiperVoices: vi.fn(async () => null),
  speakResponse: mocks.speakResponseMock,
  stripMarkdownForSpeech: (s: string) => s,
  onSpeechEvent: vi.fn(() => () => {}),
  prewarmTts: vi.fn(),
}));

vi.mock('../../../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => mocks.supportedRef.v,
  startListening: mocks.startListeningMock,
  stopListening: mocks.stopListeningMock,
}));

vi.mock('../MeetingView', () => ({
  MeetingView: () => <div data-testid="meeting-view-stub" />,
}));

import { ProfileChatTab } from '../ProfileChatTab';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent, AgentProfileMessage } from '../../../store/types';
import type { ThreadMessageDTO } from '../../sidebar/threadApi';

const AGENT_ID = 'agent-bf664';

type PendingThreadLoad = {
  threadId: string;
  settled: boolean;
  resolve: (response: Response) => void;
};

let pendingThreadLoads: PendingThreadLoad[] = [];
let nextFrameId = 1;
let queuedFrames = new Map<number, FrameRequestCallback>();
let cancelledFrames = new Set<number>();
let requestFrameMock: ReturnType<typeof vi.fn>;
let cancelFrameMock: ReturnType<typeof vi.fn>;
let metricScrollHeight = 2_000;
let metricClientHeight = 500;
let scrollPositions = new WeakMap<HTMLElement, number>();
let scrollTopWrites: Array<{ element: HTMLElement; value: number }> = [];
let originalScrollHeight: PropertyDescriptor | undefined;
let originalClientHeight: PropertyDescriptor | undefined;
let originalScrollTop: PropertyDescriptor | undefined;
let originalScrollIntoView: PropertyDescriptor | undefined;

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify(body),
    json: async () => body,
  } as Response;
}

function mkAgent(id: string = AGENT_ID): Agent {
  return {
    id,
    agentType: 'crew',
    callsign: 'Vex',
    displayName: '',
    pool: 'bridge',
    state: 'active',
    confidence: 1,
    trust: 0.5,
    tier: 'domain',
    isCrew: true,
    position: [0, 0, 0] as [number, number, number],
    department: 'science',
  } as Agent;
}

function mkThread(id: string, meetingActive = false): AD791aChatThreadView {
  return {
    id,
    title: `Thread ${id}`,
    participants: ['captain', AGENT_ID],
    created_at: 1_700_000_000,
    last_active_at: 1_700_000_000,
    metadata: meetingActive ? { meeting_active: true } : {},
  };
}

function mkMessage(
  id: string,
  role: AgentProfileMessage['role'] = 'agent',
): AgentProfileMessage {
  return {
    id,
    role,
    text: `message ${id}`,
    timestamp: 1_700_000_000,
    ...(role === 'agent' ? { authorId: AGENT_ID, callsign: 'Vex' } : {}),
  };
}

function mkMessages(count: number, prefix: string): AgentProfileMessage[] {
  return Array.from({ length: count }, (_, index) => mkMessage(`${prefix}-${index}`));
}

function toDto(threadId: string, message: AgentProfileMessage): ThreadMessageDTO {
  return {
    id: message.id,
    thread_id: threadId,
    author_id: message.role === 'agent' ? AGENT_ID : message.role === 'user' ? 'captain' : 'system',
    role: message.role === 'user' ? 'captain' : message.role,
    body: message.text,
    created_at: message.timestamp,
    metadata: {},
  };
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
    liveGeneration: null,
    liveSequence: 0,
    liveRepairEpoch: 0,
    liveThreadRefresh: null,
    liveArtifactRefresh: null,
    liveTodoRefresh: null,
    liveCrewOwnerParentId: null,
    liveRailOwner: null,
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
    if (url.endsWith('/chat/history')) {
      return Promise.resolve(jsonResponse({ memories: [] }));
    }
    if (url.endsWith('/profile')) {
      return Promise.resolve(jsonResponse({ voiceProfile: null }));
    }
    if (url === '/api/voice/health') {
      return Promise.resolve(jsonResponse({
        primary_stt: 'browser',
        engine: 'browser',
        backend_available: true,
        healthy: true,
      }));
    }
    const threadMatch = url.match(/^\/api\/threads\/([^/?]+)$/);
    if (threadMatch) {
      const threadId = decodeURIComponent(threadMatch[1]);
      return Promise.resolve(jsonResponse(useStore.getState().chatThreads.get(threadId) ?? {}));
    }
    return Promise.resolve(jsonResponse({}));
  }));
}

function installScrollMetrics(): void {
  originalScrollHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollHeight');
  originalClientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
  originalScrollTop = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollTop');
  Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
    configurable: true,
    get: () => metricScrollHeight,
  });
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    get: () => metricClientHeight,
  });
  Object.defineProperty(HTMLElement.prototype, 'scrollTop', {
    configurable: true,
    get(this: HTMLElement) {
      return scrollPositions.get(this) ?? 0;
    },
    set(this: HTMLElement, value: number) {
      const numericValue = Number(value);
      scrollPositions.set(this, numericValue);
      scrollTopWrites.push({ element: this, value: numericValue });
    },
  });
}

function restorePrototypeProperty(
  name: 'scrollHeight' | 'clientHeight' | 'scrollTop',
  descriptor: PropertyDescriptor | undefined,
): void {
  if (descriptor) Object.defineProperty(HTMLElement.prototype, name, descriptor);
  else delete (HTMLElement.prototype as unknown as Record<string, unknown>)[name];
}

function installFrameHarness(): void {
  requestFrameMock = vi.fn((callback: FrameRequestCallback): number => {
    const id = nextFrameId++;
    queuedFrames.set(id, callback);
    return id;
  });
  cancelFrameMock = vi.fn((id: number): void => {
    cancelledFrames.add(id);
  });
  vi.stubGlobal('requestAnimationFrame', requestFrameMock);
  vi.stubGlobal('cancelAnimationFrame', cancelFrameMock);
}

function activeFrameIds(): number[] {
  return [...queuedFrames.keys()].filter((id) => !cancelledFrames.has(id));
}

function flushFrames(): void {
  const frames = [...queuedFrames.entries()];
  queuedFrames.clear();
  for (const [id, callback] of frames) {
    if (!cancelledFrames.has(id)) callback(16);
  }
}

function setScrollPosition(element: HTMLElement, top: number): void {
  scrollPositions.set(element, top);
  fireEvent.scroll(element);
}

function installScrollTo(element: HTMLElement): ReturnType<typeof vi.fn> {
  const scrollToMock = vi.fn();
  Object.defineProperty(element, 'scrollTo', {
    configurable: true,
    value: scrollToMock,
  });
  return scrollToMock;
}

function disableScrollTo(element: HTMLElement): void {
  Object.defineProperty(element, 'scrollTo', {
    configurable: true,
    value: undefined,
  });
}

function seedActiveThread(
  threadId: string,
  messages: AgentProfileMessage[],
  meetingActive = false,
): void {
  useStore.setState({
    activeProfileAgent: AGENT_ID,
    agents: new Map([[AGENT_ID, mkAgent()]]),
    chatThreads: new Map([[threadId, mkThread(threadId, meetingActive)]]),
  });
  useStore.getState().setThreadMessages(threadId, messages);
}

function seedColdMessages(count: number): AgentProfileMessage[] {
  useStore.setState({
    activeProfileAgent: AGENT_ID,
    activeProfileThreadId: null,
    threadIdByAgent: new Map(),
    agents: new Map([[AGENT_ID, mkAgent()]]),
  });
  for (let index = 0; index < count; index += 1) {
    useStore.getState().addAgentMessage(AGENT_ID, 'agent', `cold ${index}`);
  }
  return useStore.getState().agentConversations.get(AGENT_ID)?.messages ?? [];
}

async function waitForThreadLoad(threadId: string): Promise<PendingThreadLoad> {
  await waitFor(() => {
    expect(pendingThreadLoads.some((load) => load.threadId === threadId && !load.settled)).toBe(true);
  });
  const load = pendingThreadLoads.find((item) => item.threadId === threadId && !item.settled);
  if (!load) throw new Error(`missing controlled load for ${threadId}`);
  return load;
}

async function resolveThreadLoad(
  load: PendingThreadLoad,
  messages: AgentProfileMessage[],
): Promise<void> {
  load.settled = true;
  await act(async () => {
    load.resolve(jsonResponse({
      thread_id: load.threadId,
      messages: messages.map((message) => toDto(load.threadId, message)),
    }));
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  mocks.speakResponseMock.mockReset();
  mocks.startListeningMock.mockReset();
  mocks.stopListeningMock.mockReset();
  mocks.supportedRef.v = true;
  localStorage.clear();
  resetStore();

  let now = 1_700_000_000_000;
  vi.spyOn(Date, 'now').mockImplementation(() => {
    now += 1;
    return now;
  });
  let random = 0;
  vi.spyOn(Math, 'random').mockImplementation(() => {
    random += 0.001;
    return random;
  });

  pendingThreadLoads = [];
  nextFrameId = 1;
  queuedFrames = new Map();
  cancelledFrames = new Set();
  metricScrollHeight = 2_000;
  metricClientHeight = 500;
  scrollPositions = new WeakMap();
  scrollTopWrites = [];
  installScrollMetrics();
  installFrameHarness();
  installFetchMock();
  originalScrollIntoView = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView');
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
  queuedFrames.clear();
  cancelledFrames.clear();
  restorePrototypeProperty('scrollHeight', originalScrollHeight);
  restorePrototypeProperty('clientHeight', originalClientHeight);
  restorePrototypeProperty('scrollTop', originalScrollTop);
  if (originalScrollIntoView) {
    Object.defineProperty(Element.prototype, 'scrollIntoView', originalScrollIntoView);
  } else {
    delete (Element.prototype as unknown as Record<string, unknown>).scrollIntoView;
  }
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('BF-664 mounted active-thread cap', () => {
  it('follows a pinned agent append at 200 and reads final post-layout height', async () => {
    const initial = mkMessages(200, 'active-pinned');
    seedActiveThread('thread-pinned', initial);
    render(<ProfileChatTab agentId={AGENT_ID} threadId="thread-pinned" />);
    const transcript = await screen.findByTestId('chat-transcript') as HTMLElement;
    const scrollToMock = installScrollTo(transcript);
    setScrollPosition(transcript, 1_500);
    scrollTopWrites = [];

    const oldTailId = initial[199].id;
    act(() => {
      useStore.getState().appendThreadMessage(
        'thread-pinned',
        mkMessage('active-pinned-200'),
      );
    });

    const stored = useStore.getState().threadMessages.get('thread-pinned') ?? [];
    expect(stored).toHaveLength(200);
    expect(stored[198].id).toBe(oldTailId);
    expect(stored[199].id).toBe('active-pinned-200');
    expect(activeFrameIds()).toHaveLength(1);
    expect(scrollToMock).not.toHaveBeenCalled();

    metricScrollHeight = 2_600;
    act(() => flushFrames());
    expect(scrollToMock).toHaveBeenCalledTimes(1);
    expect(scrollToMock).toHaveBeenCalledWith({ top: 2_600, behavior: 'smooth' });
  });

  it('does not yank an unpinned agent append at 200', async () => {
    const initial = mkMessages(200, 'active-unpinned');
    seedActiveThread('thread-unpinned', initial);
    render(<ProfileChatTab agentId={AGENT_ID} threadId="thread-unpinned" />);
    const transcript = await screen.findByTestId('chat-transcript') as HTMLElement;
    const scrollToMock = installScrollTo(transcript);
    setScrollPosition(transcript, 100);
    scrollTopWrites = [];

    act(() => {
      useStore.getState().appendThreadMessage(
        'thread-unpinned',
        mkMessage('active-unpinned-200'),
      );
    });

    const stored = useStore.getState().threadMessages.get('thread-unpinned') ?? [];
    expect(stored).toHaveLength(200);
    expect(stored[198].id).toBe(initial[199].id);
    expect(activeFrameIds()).toHaveLength(0);
    expect(scrollToMock).not.toHaveBeenCalled();
    expect(scrollTopWrites).toHaveLength(0);
  });

  it('always follows an unpinned Captain append at 200', async () => {
    const initial = mkMessages(200, 'active-captain');
    seedActiveThread('thread-captain', initial);
    render(<ProfileChatTab agentId={AGENT_ID} threadId="thread-captain" />);
    const transcript = await screen.findByTestId('chat-transcript') as HTMLElement;
    const scrollToMock = installScrollTo(transcript);
    setScrollPosition(transcript, 100);

    act(() => {
      useStore.getState().appendThreadMessage(
        'thread-captain',
        mkMessage('active-captain-200', 'user'),
      );
    });

    const stored = useStore.getState().threadMessages.get('thread-captain') ?? [];
    expect(stored).toHaveLength(200);
    expect(stored[198].id).toBe(initial[199].id);
    expect(activeFrameIds()).toHaveLength(1);
    metricScrollHeight = 2_700;
    act(() => flushFrames());
    expect(scrollToMock).toHaveBeenCalledWith({ top: 2_700, behavior: 'smooth' });
  });
});

describe('BF-664 mounted cold-buffer cap', () => {
  it('follows a pinned agent append at 100 through the scrollTop fallback', async () => {
    const initial = seedColdMessages(100);
    expect(initial).toHaveLength(100);
    expect(new Set(initial.map((message) => message.id))).toHaveLength(100);
    render(<ProfileChatTab agentId={AGENT_ID} />);
    const transcript = await screen.findByTestId('chat-transcript') as HTMLElement;
    disableScrollTo(transcript);
    setScrollPosition(transcript, 1_500);
    scrollTopWrites = [];
    const oldTailId = initial[99].id;

    act(() => {
      useStore.getState().addAgentMessage(AGENT_ID, 'agent', 'cold capped agent');
    });

    const stored = useStore.getState().agentConversations.get(AGENT_ID)?.messages ?? [];
    expect(stored).toHaveLength(100);
    expect(stored[98].id).toBe(oldTailId);
    expect(stored[99].id).not.toBe(oldTailId);
    expect(activeFrameIds()).toHaveLength(1);
    metricScrollHeight = 2_800;
    act(() => flushFrames());
    expect(transcript.scrollTop).toBe(2_800);
    expect(scrollTopWrites[scrollTopWrites.length - 1]).toEqual({ element: transcript, value: 2_800 });
  });

  it('does not yank an unpinned agent append at 100', async () => {
    const initial = seedColdMessages(100);
    render(<ProfileChatTab agentId={AGENT_ID} />);
    const transcript = await screen.findByTestId('chat-transcript') as HTMLElement;
    const scrollToMock = installScrollTo(transcript);
    setScrollPosition(transcript, 100);
    scrollTopWrites = [];

    act(() => {
      useStore.getState().addAgentMessage(AGENT_ID, 'agent', 'cold unpinned agent');
    });

    const stored = useStore.getState().agentConversations.get(AGENT_ID)?.messages ?? [];
    expect(stored).toHaveLength(100);
    expect(stored[98].id).toBe(initial[99].id);
    expect(activeFrameIds()).toHaveLength(0);
    expect(scrollToMock).not.toHaveBeenCalled();
    expect(scrollTopWrites).toHaveLength(0);
  });

  it('always follows an unpinned Captain append at 100', async () => {
    const initial = seedColdMessages(100);
    render(<ProfileChatTab agentId={AGENT_ID} />);
    const transcript = await screen.findByTestId('chat-transcript') as HTMLElement;
    const scrollToMock = installScrollTo(transcript);
    setScrollPosition(transcript, 100);

    act(() => {
      useStore.getState().addAgentMessage(AGENT_ID, 'user', 'cold capped Captain');
    });

    const stored = useStore.getState().agentConversations.get(AGENT_ID)?.messages ?? [];
    expect(stored).toHaveLength(100);
    expect(stored[98].id).toBe(initial[99].id);
    expect(activeFrameIds()).toHaveLength(1);
    metricScrollHeight = 2_900;
    act(() => flushFrames());
    expect(scrollToMock).toHaveBeenCalledWith({ top: 2_900, behavior: 'smooth' });
  });
});

describe('BF-664 mounted load, context, visibility, and cleanup', () => {
  it('jumps directly when an initial active-thread load resolves with 200 messages', async () => {
    seedActiveThread('thread-load', []);
    render(<ProfileChatTab agentId={AGENT_ID} threadId="thread-load" />);
    const transcript = await screen.findByTestId('chat-transcript') as HTMLElement;
    const scrollToMock = installScrollTo(transcript);
    scrollTopWrites = [];
    const load = await waitForThreadLoad('thread-load');
    metricScrollHeight = 3_200;

    await resolveThreadLoad(load, mkMessages(200, 'loaded'));
    await waitFor(() => {
      expect(useStore.getState().threadMessages.get('thread-load')).toHaveLength(200);
    });

    expect(transcript.scrollTop).toBe(3_200);
  expect(scrollTopWrites[scrollTopWrites.length - 1]).toEqual({ element: transcript, value: 3_200 });
    expect(activeFrameIds()).toHaveLength(0);
    expect(scrollToMock).not.toHaveBeenCalled();
  });

  it('context switch jumps directly and cancels an old pending smooth frame', async () => {
    const first = mkMessages(200, 'context-first');
    const second = mkMessages(80, 'context-second');
    useStore.setState({
      activeProfileAgent: AGENT_ID,
      agents: new Map([[AGENT_ID, mkAgent()]]),
      chatThreads: new Map([
        ['thread-first', mkThread('thread-first')],
        ['thread-second', mkThread('thread-second')],
      ]),
    });
    useStore.getState().setThreadMessages('thread-first', first);
    useStore.getState().setThreadMessages('thread-second', second);
    const view = render(<ProfileChatTab agentId={AGENT_ID} threadId="thread-first" />);
    const firstTranscript = await screen.findByTestId('chat-transcript') as HTMLElement;
    const scrollToMock = installScrollTo(firstTranscript);
    setScrollPosition(firstTranscript, 1_500);

    act(() => {
      useStore.getState().appendThreadMessage(
        'thread-first',
        mkMessage('context-first-200'),
      );
    });
    const [oldFrameId] = activeFrameIds();
    expect(oldFrameId).toBeDefined();

    metricScrollHeight = 4_100;
    view.rerender(<ProfileChatTab agentId={AGENT_ID} threadId="thread-second" />);
    const secondTranscript = screen.getByTestId('chat-transcript') as HTMLElement;
    expect(cancelFrameMock).toHaveBeenCalledWith(oldFrameId);
    expect(activeFrameIds()).toHaveLength(0);
    expect(secondTranscript.scrollTop).toBe(4_100);

    act(() => flushFrames());
    expect(scrollToMock).not.toHaveBeenCalled();
    expect(secondTranscript.scrollTop).toBe(4_100);
  });

  it('observes hidden capped appends without scrolling, then remounts at latest and pinned', async () => {
    const initial = mkMessages(200, 'meeting');
    seedActiveThread('thread-meeting', initial, true);
    render(<ProfileChatTab agentId={AGENT_ID} threadId="thread-meeting" />);
    const firstTranscript = await screen.findByTestId('chat-transcript') as HTMLElement;
    const firstScrollTo = installScrollTo(firstTranscript);
    scrollTopWrites = [];

    act(() => {
      useStore.getState().appendThreadMessage(
        'thread-meeting',
        mkMessage('meeting-before-hide-200'),
      );
    });
    const [preHideFrameId] = activeFrameIds();
    expect(preHideFrameId).toBeDefined();

    act(() => {
      useStore.setState({ meetingChatVisible: false });
    });
    expect(screen.queryByTestId('chat-transcript')).toBeNull();
    expect(cancelFrameMock).toHaveBeenCalledWith(preHideFrameId);
    expect(activeFrameIds()).toHaveLength(0);
    act(() => flushFrames());
    expect(firstScrollTo).not.toHaveBeenCalled();

    act(() => {
      useStore.getState().appendThreadMessage(
        'thread-meeting',
        mkMessage('meeting-hidden-200'),
      );
    });
    const hiddenStored = useStore.getState().threadMessages.get('thread-meeting') ?? [];
    expect(hiddenStored).toHaveLength(200);
    expect(hiddenStored[198].id).toBe('meeting-before-hide-200');
    expect(activeFrameIds()).toHaveLength(0);
    expect(firstScrollTo).not.toHaveBeenCalled();
    expect(scrollTopWrites).toHaveLength(0);

    metricScrollHeight = 4_300;
    act(() => {
      useStore.setState({ meetingChatVisible: true });
    });
    const remountedTranscript = screen.getByTestId('chat-transcript') as HTMLElement;
    expect(remountedTranscript).not.toBe(firstTranscript);
    expect(remountedTranscript.scrollTop).toBe(4_300);
    expect(activeFrameIds()).toHaveLength(0);

    const remountedScrollTo = installScrollTo(remountedTranscript);
    act(() => {
      useStore.getState().appendThreadMessage(
        'thread-meeting',
        mkMessage('meeting-visible-201'),
      );
    });
    expect(activeFrameIds()).toHaveLength(1);
    metricScrollHeight = 4_500;
    act(() => flushFrames());
    expect(remountedScrollTo).toHaveBeenCalledWith({ top: 4_500, behavior: 'smooth' });
  });

  it('takes the instant bulk path for an unrelated same-count replacement', async () => {
    const initial = mkMessages(200, 'replace-old');
    seedActiveThread('thread-replace', initial);
    render(<ProfileChatTab agentId={AGENT_ID} threadId="thread-replace" />);
    const transcript = await screen.findByTestId('chat-transcript') as HTMLElement;
    const scrollToMock = installScrollTo(transcript);
    setScrollPosition(transcript, 1_500);
    scrollTopWrites = [];

    act(() => {
      useStore.getState().appendThreadMessage(
        'thread-replace',
        mkMessage('replace-old-200'),
      );
    });
    const [staleFrameId] = activeFrameIds();
    expect(staleFrameId).toBeDefined();
    metricScrollHeight = 3_600;

    act(() => {
      useStore.getState().setThreadMessages(
        'thread-replace',
        mkMessages(200, 'replace-new'),
      );
    });

    expect(useStore.getState().threadMessages.get('thread-replace')).toHaveLength(200);
  expect(cancelFrameMock).toHaveBeenCalledWith(staleFrameId);
    expect(transcript.scrollTop).toBe(3_600);
  expect(scrollTopWrites[scrollTopWrites.length - 1]).toEqual({ element: transcript, value: 3_600 });
    expect(activeFrameIds()).toHaveLength(0);
  act(() => flushFrames());
    expect(scrollToMock).not.toHaveBeenCalled();
  });

  it('cancels a pending smooth frame on unmount', async () => {
    const initial = mkMessages(200, 'unmount');
    seedActiveThread('thread-unmount', initial);
    const view = render(<ProfileChatTab agentId={AGENT_ID} threadId="thread-unmount" />);
    const transcript = await screen.findByTestId('chat-transcript') as HTMLElement;
    const scrollToMock = installScrollTo(transcript);
    setScrollPosition(transcript, 1_500);

    act(() => {
      useStore.getState().appendThreadMessage(
        'thread-unmount',
        mkMessage('unmount-200'),
      );
    });
    const [frameId] = activeFrameIds();
    expect(frameId).toBeDefined();

    view.unmount();
    expect(cancelFrameMock).toHaveBeenCalledWith(frameId);
    expect(activeFrameIds()).toHaveLength(0);
    act(() => flushFrames());
    expect(scrollToMock).not.toHaveBeenCalled();
  });
});
