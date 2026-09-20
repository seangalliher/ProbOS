import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';

vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: () => {} }));
vi.mock('../audio/voice', () => ({
  flushSpeechQueue: vi.fn(), getServerPiperVoices: vi.fn(async () => null),
  speakResponse: vi.fn(), stripMarkdownForSpeech: (text: string) => text,
  onSpeechEvent: vi.fn(() => () => {}), prewarmTts: vi.fn(),
}));
vi.mock('../audio/speechInput', () => ({ isSpeechRecognitionSupported: () => false, startListening: vi.fn() }));
vi.mock('../audio/voiceActivity', () => ({
  startVoiceActivity: vi.fn(), stopVoiceActivity: vi.fn(), subscribePcm: vi.fn(() => () => {}),
}));
vi.mock('../components/profile/MeetingView', () => ({ MeetingView: () => null }));

import CompactApp from '../CompactApp';
import MobileShell from '../MobileShell';
import { AgentProfilePanel } from '../components/profile/AgentProfilePanel';
import { ProfileChatTab } from '../components/profile/ProfileChatTab';
import { useStore, type AD791aChatThreadView } from '../store/useStore';
import { useSettingsStore, type ConfigSnapshot } from '../store/useSettingsStore';
import type { Agent } from '../store/types';

const generation = 'a'.repeat(32);
const crew = (id: string, callsign: string): Agent => ({
  id, callsign, displayName: callsign, agentType: 'crew', pool: 'bridge', state: 'active',
  confidence: 1, trust: 0.5, tier: 'domain', isCrew: true, position: [0, 0, 0],
});
const thread = (id: string, participants = ['yeo']): AD791aChatThreadView => ({
  id, title: id, participants, created_at: 1, last_active_at: 1, metadata: {},
});
const serverThreads = new Map<string, AD791aChatThreadView>();
const requests: { url: string; options?: RequestInit }[] = [];
let customFetch: ((url: string, options?: RequestInit) => Promise<Response> | undefined) | undefined;
const originalScroll = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView');
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
function emit(room: string, participant = 'yeo', end = false, run = 'b'.repeat(32)): void {
  useStore.getState().handleEvent({
    type: end ? 'agentic_tool_call_completed' : 'agentic_tool_call_started',
    data: {
      thread_id: room, agent_id: participant, run_id: run, iteration: 1,
      tool_call_index: 0, tool_call_id: 'duplicate', tool_id: `${participant}_probe`,
      ...(end ? { is_error: false, duration_ms: 1 } : {}),
    }, timestamp: 1, stream: { generation, sequence: useStore.getState().liveSequence + 1 },
  });
}
function send(): void {
  const input = screen.getByPlaceholderText('Message...');
  fireEvent.change(input, { target: { value: 'Please use the probe' } });
  fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
}
function chatRequests() { return requests.filter(request => /\/chat$/.test(request.url)); }
function associationRequests() { return requests.filter(request => /\/agent\/.*\/thread$/.test(request.url)); }

beforeEach(() => {
  localStorage.clear();
  serverThreads.clear();
  requests.length = 0;
  customFetch = undefined;
  useStore.setState(useStore.getInitialState(), true);
  useStore.getState().handleEvent({
    type: 'state_snapshot', data: {
      agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0,
    }, timestamp: 1, stream: { generation, sequence: 0 },
  });
  useStore.setState({ agents: new Map([['yeo', crew('yeo', 'Yeo')], ['other', crew('other', 'Other')]]), connected: true });
  useSettingsStore.setState({
    ...useSettingsStore.getInitialState(), loaded: true,
    snapshot: { config: { agentic_loop: { event_correlation_enabled: true } }, sections: [] } as unknown as ConfigSnapshot,
  }, true);
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
  vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request, options?: RequestInit) => {
    const url = String(input);
    requests.push({ url, options });
    const custom = customFetch?.(url, options);
    if (custom) return custom;
    if (/^\/api\/threads\/[^/]+$/.test(url) && !options?.method) {
      const found = serverThreads.get(decodeURIComponent(url.split('/').pop()!));
      return new Response(JSON.stringify(found ?? {}), { status: found ? 200 : 404 });
    }
    if (/\/messages/.test(url)) return new Response('{"messages":[]}');
    if (url.startsWith('/api/threads?')) return new Response(JSON.stringify({ threads: [...serverThreads.values()] }));
    if (url.startsWith('/api/threads/summaries')) return new Response('{"summaries":{}}');
    if (/\/chat$/.test(url)) return new Response('{"response":"Local reply"}');
    return new Response('{}', { status: 404 });
  }));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  if (originalScroll) Object.defineProperty(Element.prototype, 'scrollIntoView', originalScroll);
  else Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
  useStore.setState(useStore.getInitialState(), true);
  useSettingsStore.setState(useSettingsStore.getInitialState(), true);
});

const shells: [string, () => ReactElement, (id: string) => void][] = [
  ['desktop profile', () => <AgentProfilePanel />, id => useStore.setState({ activeProfileAgent: 'yeo', activeProfileThreadId: id })],
  ['CompactApp', () => <CompactApp />, id => useStore.setState({ activeThreadId: id })],
  ['MobileShell', () => <MobileShell />, id => useStore.getState().setThreadForAgent('yeo', id)],
];

describe.each(shells)('%s actual shared consumer', (_name, shell, select) => {
  it('requires a SERVER roster, retains early observations, and follows room/participant changes', async () => {
    const waiting = deferred<Response>();
    serverThreads.set('room-a', thread('room-a', ['other']));
    serverThreads.set('room-b', thread('room-b', ['yeo']));
    useStore.setState({ chatThreads: new Map([['room-a', thread('room-a')], ['room-b', thread('room-b')]]) });
    select('room-a');
    customFetch = url => url === '/api/threads/room-a'
      ? waiting.promise.then(response => response.clone()) : undefined;
    emit('room-a', 'yeo');
    emit('room-a', 'other');
    emit('room-b', 'yeo');
    render(shell());
    const band = screen.getByRole('region', { name: 'Live tool progress' });
    expect(band).toHaveTextContent('association unverified');
    expect(band).not.toHaveTextContent('yeo_probe');
    await act(async () => waiting.resolve(new Response(JSON.stringify(serverThreads.get('room-a')))));
    await waitFor(() => expect(band).toHaveTextContent('other_probe'));
    expect(band).not.toHaveTextContent('yeo_probe');
    customFetch = undefined;
    act(() => select('room-b'));
    await waitFor(() => expect(band).toHaveTextContent('yeo_probe'));
    expect(band).not.toHaveTextContent('other_probe');
    act(() => emit('room-a', 'other', true));
    expect(band).not.toHaveTextContent('Completed');
    serverThreads.set('room-b', thread('room-b', ['other']));
    act(() => useStore.getState().setChatThread(thread('room-b', ['other'])));
    await waitFor(() => expect(band).toHaveTextContent('No tool activity observed'));
    expect(band).not.toHaveTextContent('yeo_probe');
    expect(associationRequests()).toHaveLength(0);
  });
});

describe('first actual send association ownership', () => {
  it('associates before normal dispatch, using real server participants and preserving loaded settings drafts', async () => {
    const association = deferred<Response>();
    const reply = deferred<Response>();
    serverThreads.set('first', thread('first', ['yeo', 'other']));
    customFetch = url => url === '/api/agent/yeo/thread' ? association.promise
      : url === '/api/agent/yeo/chat' ? reply.promise : undefined;
    useSettingsStore.setState({ draft: { 'system.name': 'Unsaved' }, draftCount: 1 });
    render(<ProfileChatTab agentId="yeo" />);
    expect(associationRequests()).toHaveLength(0);
    send();
    expect(chatRequests()).toHaveLength(0);
    await act(async () => association.resolve(new Response(JSON.stringify(serverThreads.get('first')))));
    expect(associationRequests()).toHaveLength(1);
    expect(chatRequests()).toHaveLength(1);
    expect(JSON.parse(String(chatRequests()[0].options?.body)).thread_id).toBe('first');
    act(() => emit('first', 'other'));
    await waitFor(() => expect(screen.getByRole('region', { name: 'Live tool progress' })).toHaveTextContent('other_probe'));
    expect(useSettingsStore.getState()).toMatchObject({ draft: { 'system.name': 'Unsaved' }, draftCount: 1 });
    await act(async () => reply.resolve(new Response('{"response":"Reply","thread_id":"first"}')));
    expect(chatRequests()).toHaveLength(1);
  });

  it.each(['resolve', 'reject'])('races ignored abort at 1500ms and consumes a late %s without rebinding or resending', async ending => {
    vi.useFakeTimers();
    const association = deferred<Response>();
    customFetch = url => url === '/api/agent/yeo/thread' ? association.promise : undefined;
    render(<ProfileChatTab agentId="yeo" />);
    send();
    expect(associationRequests()).toHaveLength(1);
    await act(async () => vi.advanceTimersByTimeAsync(1499));
    expect(chatRequests()).toHaveLength(0);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(chatRequests()).toHaveLength(1);
    expect(JSON.parse(String(chatRequests()[0].options?.body))).not.toHaveProperty('thread_id');
    expect(associationRequests()[0].options?.signal?.aborted).toBe(true);
    fireEvent.change(screen.getByPlaceholderText('Message...'), { target: { value: 'Keep this next draft' } });
    await act(async () => {
      if (ending === 'resolve') association.resolve(new Response(JSON.stringify(thread('late'))));
      else association.reject(new Error('late local rejection'));
    });
    expect(useStore.getState().threadIdByAgent.has('yeo')).toBe(false);
    expect(screen.getByPlaceholderText('Message...')).toHaveValue('Keep this next draft');
    expect(screen.getByRole('region', { name: 'Live tool progress' })).toHaveTextContent('unknown');
    expect(chatRequests()).toHaveLength(1);
    expect(associationRequests()).toHaveLength(1);
  });

  it.each(['agent', 'room'])('a context switch (%s) aborts lookup but still dispatches once to the captured original destination', async change => {
    const association = deferred<Response>();
    const reply = deferred<Response>();
    customFetch = url => url === '/api/agent/yeo/thread' ? association.promise
      : url === '/api/agent/yeo/chat' ? reply.promise : undefined;
    const mounted = render(<ProfileChatTab agentId="yeo" />);
    send();
    if (change === 'agent') mounted.rerender(<ProfileChatTab agentId="other" />);
    else {
      serverThreads.set('elsewhere', thread('elsewhere'));
      act(() => useStore.setState({ activeProfileThreadId: 'elsewhere' }));
    }
    await act(async () => { await Promise.resolve(); });
    expect(chatRequests()).toHaveLength(1);
    expect(chatRequests()[0].url).toBe('/api/agent/yeo/chat');
    expect(JSON.parse(String(chatRequests()[0].options?.body))).not.toHaveProperty('thread_id');
    expect(associationRequests()[0].options?.signal?.aborted).toBe(true);
    const owner = change === 'agent' ? 'agent:other' : 'thread:elsewhere';
    act(() => useStore.getState().updateComposerDraft(owner, draft => ({ ...draft, text: 'New destination draft' })));
    await act(async () => association.resolve(new Response(JSON.stringify(thread('late')))));
    await act(async () => reply.resolve(new Response('{"response":"Old reply","thread_id":"old-return"}')));
    expect(useStore.getState().threadIdByAgent.has('yeo')).toBe(false);
    expect(screen.getByPlaceholderText('Message...')).toHaveValue('New destination draft');
    expect(chatRequests()).toHaveLength(1);
  });

  it.each(['refused', 'malformed', 'foreign', 'throw'])('degrades association %s to one unchanged normal send', async failure => {
    customFetch = url => url === '/api/agent/yeo/thread'
      ? failure === 'throw' ? Promise.reject(new Error('local failure'))
        : Promise.resolve(new Response(JSON.stringify(
          failure === 'malformed' ? { id: 'room', participants: [2] }
            : failure === 'foreign' ? thread('room', ['other']) : {},
        ), { status: failure === 'refused' ? 503 : 200 }))
      : undefined;
    render(<ProfileChatTab agentId="yeo" />);
    send();
    await waitFor(() => expect(chatRequests()).toHaveLength(1));
    expect(JSON.parse(String(chatRequests()[0].options?.body))).not.toHaveProperty('thread_id');
    expect(useStore.getState().threadIdByAgent.has('yeo')).toBe(false);
    expect(associationRequests()).toHaveLength(1);
  });

  it.each([false, undefined])('does not associate from viewing or sending when correlation readiness is %s', async enabled => {
    useSettingsStore.setState({ snapshot: {
      config: { agentic_loop: { event_correlation_enabled: enabled } }, sections: [],
    } as unknown as ConfigSnapshot });
    render(<ProfileChatTab agentId="yeo" />);
    expect(associationRequests()).toHaveLength(0);
    send();
    await waitFor(() => expect(chatRequests()).toHaveLength(1));
    expect(associationRequests()).toHaveLength(0);
  });

  it('bounds existing-thread hydration and ignores a late roster after unmount', async () => {
    vi.useFakeTimers();
    const hydration = deferred<Response>();
    customFetch = url => url === '/api/threads/room' ? hydration.promise : undefined;
    const mounted = render(<ProfileChatTab agentId="yeo" threadId="room" />);
    await act(async () => vi.advanceTimersByTimeAsync(15_000));
    const request = requests.find(item => item.url === '/api/threads/room');
    expect(request?.options?.signal?.aborted).toBe(true);
    expect(screen.getByRole('region', { name: 'Live tool progress' })).toHaveTextContent('unverified');
    mounted.unmount();
    await act(async () => hydration.resolve(new Response(JSON.stringify(thread('room')))));
    expect(useStore.getState().threadIdByAgent.size).toBe(0);
    expect(associationRequests()).toHaveLength(0);
  });

  it('does not accept a response for another thread or a superseded roster request', async () => {
    const hydration = deferred<Response>();
    customFetch = url => url === '/api/threads/room' ? hydration.promise : undefined;
    useStore.getState().setChatThread(thread('room'));
    render(<ProfileChatTab agentId="yeo" threadId="room" />);
    act(() => {
      emit('room');
      useStore.getState().setChatThread(thread('room', ['other']));
    });
    await act(async () => hydration.resolve(new Response(JSON.stringify(thread('wrong')))));
    const band = screen.getByRole('region', { name: 'Live tool progress' });
    expect(within(band).getByRole('status')).toHaveTextContent('unverified');
    expect(band).not.toHaveTextContent('yeo_probe');
  });

  it('makes roster authority unknown when reconnect repair fails without deleting observed terminal facts', async () => {
    serverThreads.set('room', thread('room'));
    useStore.getState().setChatThread(thread('room'));
    emit('room', 'yeo', true);
    render(<ProfileChatTab agentId="yeo" threadId="room" />);
    const band = screen.getByRole('region', { name: 'Live tool progress' });
    await waitFor(() => expect(band).toHaveTextContent('Completed'));
    customFetch = url => url === '/api/threads/room'
      ? Promise.resolve(new Response('{}', { status: 503 })) : undefined;
    act(() => useStore.getState().handleEvent({
      type: 'resync_required', data: {}, timestamp: 1,
      stream: { generation, sequence: useStore.getState().liveSequence + 1 },
    }));
    await waitFor(() => expect(band).toHaveTextContent('association unverified'));
    expect(useStore.getState().toolProgress.runs[0].calls[0].terminal).toBe('completed');
    expect(associationRequests()).toHaveLength(0);
  });
});
