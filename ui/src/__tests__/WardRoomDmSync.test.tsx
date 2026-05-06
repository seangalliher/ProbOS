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
      const calls = fetchMock.mock.calls.map(c => String(c[0]));
      expect(calls).toContain('/api/agent/agent-a-001-full/chat');
      // Dual-write: at least one ward room post call after chat.
      expect(calls.filter(u => u.includes('/api/wardroom/threads/t1/posts')).length).toBeGreaterThanOrEqual(2);
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
