/**
 * AD-574b: WardRoomThreadDetail synchronous DM reply branch.
 *
 * Verifies the new submit path:
 * - DM view + resolved target_agent_id triggers /api/agent/{id}/chat call
 * - Thinking placeholder renders while in flight
 * - Dual-write posts Captain message + agent response back to thread
 * - Falls back to async post path when target_agent_id is null
 * - Falls back to async post path on chat-call failure
 * - Send button disables while thinking
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { WardRoomThreadDetail } from '../components/wardroom/WardRoomThreadDetail';
import { useStore } from '../store/useStore';

const FAKE_THREAD = {
  id: 't1', title: 'Test DM', body: '', author_callsign: 'Captain',
  created_at: Date.now() / 1000, net_score: 0,
};

beforeEach(() => {
  vi.restoreAllMocks();
  // Reset store to known state.
  useStore.setState({
    wardRoomView: 'dm-detail',
    wardRoomActiveChannel: 'ch-1',
    wardRoomActiveThread: 't1',
    wardRoomThreadDetail: { thread: FAKE_THREAD as any, posts: [] },
    wardRoomDmChannels: [
      { channel: { id: 'ch-1', name: 'dm-captain-agent-a', description: '', created_at: 0 },
        latest_thread: null, thread_count: 1, target_agent_id: 'agent-a-001-full' },
    ],
    wardRoomDmPending: null,
  });
});

describe('AD-574b WardRoomThreadDetail sync DM', () => {
  it('renders without thinking indicator when idle', () => {
    render(<WardRoomThreadDetail />);
    expect(screen.queryByTestId('dm-thinking-indicator')).toBeNull();
  });

  it('routes DM submit through /api/agent/{id}/chat then dual-writes posts', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(async (url: any) => {
      if (String(url).includes('/api/agent/')) {
        return new Response(JSON.stringify({ response: 'Hello Captain' }), { status: 200 });
      }
      return new Response('{}', { status: 200 });
    }) as any;

    render(<WardRoomThreadDetail />);
    const textarea = screen.getByPlaceholderText('Reply...') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'How are you?' } });
    const send = screen.getByText('Send');
    fireEvent.click(send);

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c: unknown[]) => String(c[0]));
      expect(calls).toContain('/api/agent/agent-a-001-full/chat');
      // Dual-write: at least one ward room post call after chat.
      expect(calls.filter((u: string) => u.includes('/api/wardroom/threads/t1/posts')).length).toBeGreaterThanOrEqual(2);
    });
  });

  it('shows thinking placeholder while chat is in flight', async () => {
    let resolveChat: (v: Response) => void = () => {};
    const chatPromise = new Promise<Response>(r => { resolveChat = r; });
    vi.spyOn(global, 'fetch').mockImplementation(async (url: any) => {
      if (String(url).includes('/api/agent/')) return chatPromise;
      return new Response('{}', { status: 200 });
    }) as any;

    render(<WardRoomThreadDetail />);
    fireEvent.change(screen.getByPlaceholderText('Reply...'), { target: { value: 'hi' } });
    fireEvent.click(screen.getByText('Send'));

    await waitFor(() => {
      expect(screen.queryByTestId('dm-thinking-indicator')).not.toBeNull();
    });
    resolveChat(new Response(JSON.stringify({ response: 'ok' }), { status: 200 }));
  });

  it('falls back to async post when target_agent_id is null', async () => {
    useStore.setState({
      wardRoomDmChannels: [
        { channel: { id: 'ch-1', name: 'dm-captain-x', description: '', created_at: 0 },
          latest_thread: null, thread_count: 1, target_agent_id: null },
      ],
    });
    const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValue(new Response('{}', { status: 200 })) as any;

    render(<WardRoomThreadDetail />);
    fireEvent.change(screen.getByPlaceholderText('Reply...'), { target: { value: 'fallback' } });
    fireEvent.click(screen.getByText('Send'));

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c: any) => String(c[0]));
      expect(calls.some((u: string) => u.includes('/api/agent/'))).toBe(false);
      expect(calls.some((u: string) => u.includes('/api/wardroom/threads/t1/posts'))).toBe(true);
    });
  });

  it('falls back to async post when chat call returns 500', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(async (url: any) => {
      if (String(url).includes('/api/agent/')) {
        return new Response('boom', { status: 500 });
      }
      return new Response('{}', { status: 200 });
    }) as any;

    render(<WardRoomThreadDetail />);
    fireEvent.change(screen.getByPlaceholderText('Reply...'), { target: { value: 'sad' } });
    fireEvent.click(screen.getByText('Send'));

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c: any) => String(c[0]));
      // Captain post still lands.
      expect(calls.some((u: string) => u.includes('/api/wardroom/threads/t1/posts'))).toBe(true);
      // Pending cleared.
      expect(useStore.getState().wardRoomDmPending).toBeNull();
    });
  });

  it('disables Send button while thinking', async () => {
    useStore.setState({
      wardRoomDmPending: { threadId: 't1', captainText: 'pending', startedAt: Date.now() },
    });
    render(<WardRoomThreadDetail />);
    const send = screen.getByText('Send') as HTMLButtonElement;
    expect(send.disabled).toBe(true);
  });
});

/**
 * BF-721: one DM channel holds many threads and may have several authors, so the
 * channel-level target_agent_id routes some replies to the wrong agent. The
 * backend now derives a per-thread target from that thread's own author_id; the
 * UI must prefer it and keep the channel-level value as the fallback.
 */
describe('BF-721 WardRoomThreadDetail per-thread DM target', () => {
  const CHANNEL_TARGET = 'counselor_counselor_0_67c601cb';
  const THREAD_TARGET = 'counselor_counselor_1_aa11bb22';

  function setThreadTarget(target: string | null | undefined) {
    useStore.setState({
      wardRoomThreadDetail: {
        thread: { ...FAKE_THREAD, target_agent_id: target } as any,
        posts: [],
      },
      wardRoomDmChannels: [
        { channel: { id: 'ch-1', name: 'dm-captain-counselo', description: '', created_at: 0 },
          latest_thread: null, thread_count: 2, target_agent_id: CHANNEL_TARGET },
      ],
    });
  }

  async function sendAndCollectUrls() {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(async (url: any) => {
      if (String(url).includes('/api/agent/')) {
        return new Response(JSON.stringify({ response: 'ack' }), { status: 200 });
      }
      return new Response('{}', { status: 200 });
    }) as any;

    render(<WardRoomThreadDetail />);
    fireEvent.change(screen.getByPlaceholderText('Reply...'), { target: { value: 'ping' } });
    fireEvent.click(screen.getByText('Send'));

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c: unknown[]) => String(c[0]));
      expect(calls.some((u: string) => u.includes('/api/agent/'))).toBe(true);
    });
    return fetchMock.mock.calls.map((c: unknown[]) => String(c[0]));
  }

  it('replies to the thread target, not the channel target', async () => {
    setThreadTarget(THREAD_TARGET);
    const calls = await sendAndCollectUrls();
    expect(calls).toContain(`/api/agent/${THREAD_TARGET}/chat`);
    expect(calls).not.toContain(`/api/agent/${CHANNEL_TARGET}/chat`);
  });

  it('posts the agent response under the thread target author_id', async () => {
    setThreadTarget(THREAD_TARGET);
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(async (url: any) => {
      if (String(url).includes('/api/agent/')) {
        return new Response(JSON.stringify({ response: 'ack' }), { status: 200 });
      }
      return new Response('{}', { status: 200 });
    }) as any;

    render(<WardRoomThreadDetail />);
    fireEvent.change(screen.getByPlaceholderText('Reply...'), { target: { value: 'ping' } });
    fireEvent.click(screen.getByText('Send'));

    await waitFor(() => {
      const bodies = fetchMock.mock.calls
        .filter((c: any[]) => String(c[0]).includes('/posts'))
        .map((c: any[]) => JSON.parse(String(c[1]?.body ?? '{}')));
      expect(bodies.some((b: any) => b.author_id === THREAD_TARGET)).toBe(true);
      expect(bodies.some((b: any) => b.author_id === CHANNEL_TARGET)).toBe(false);
    });
  });

  it('falls back to the channel target when the thread has none', async () => {
    setThreadTarget(null);
    const calls = await sendAndCollectUrls();
    expect(calls).toContain(`/api/agent/${CHANNEL_TARGET}/chat`);
  });

  it('falls back to the channel target when the field is absent entirely', async () => {
    setThreadTarget(undefined);
    const calls = await sendAndCollectUrls();
    expect(calls).toContain(`/api/agent/${CHANNEL_TARGET}/chat`);
  });

  it('stays on the async post-only path outside a DM view', async () => {
    setThreadTarget(THREAD_TARGET);
    useStore.setState({ wardRoomView: 'channels' });
    const fetchMock = vi.spyOn(global, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 200 })) as any;

    render(<WardRoomThreadDetail />);
    fireEvent.change(screen.getByPlaceholderText('Reply...'), { target: { value: 'ping' } });
    fireEvent.click(screen.getByText('Send'));

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c: unknown[]) => String(c[0]));
      expect(calls.some((u: string) => u.includes('/api/wardroom/threads/t1/posts'))).toBe(true);
      expect(calls.some((u: string) => u.includes('/api/agent/'))).toBe(false);
    });
  });
});
