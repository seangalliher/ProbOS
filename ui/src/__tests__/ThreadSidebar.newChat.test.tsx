/** AD-792 (Wave 195) vitest — "New chat" button POSTs to /api/threads
 * with Yeoman as participant, reads thread.to_dict() DIRECTLY (not
 * wrapped under {thread: ...}), and fires onThreadSelected + store
 * updates. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { useStore } from '../store/useStore';
import { ThreadSidebar } from '../components/sidebar/ThreadSidebar';

let postBody: any = null;

beforeEach(() => {
  localStorage.clear();
  postBody = null;
  useStore.setState({
    agents: new Map([['yeo-id', { id: 'yeo-id', callsign: 'Yeo', displayName: 'Yeo' } as any]]),
    chatThreads: new Map(),
    activeThreadId: null,
    threadIdByAgent: new Map(),
  });
  global.fetch = vi.fn((url: any, init?: any) => {
    const u = String(url);
    const method = (init?.method || 'GET').toUpperCase();
    if (u === '/api/threads' && method === 'POST') {
      postBody = JSON.parse(init.body);
      // POST returns thread.to_dict() DIRECTLY per routers/threads.py:117.
      return Promise.resolve({
        ok: true,
        json: async () => ({
          id: 'new-thread-id',
          title: 'Yeo',
          participants: ['yeo-id'],
          created_at: Date.now() / 1000,
          last_active_at: Date.now() / 1000,
          pinned: false,
          archived: false,
        }),
      }) as any;
    }
    return Promise.resolve({ ok: true, json: async () => ({ threads: [] }) }) as any;
  });
});

afterEach(() => {
  cleanup();
});

describe('ThreadSidebar new chat', () => {
  it('POSTs to /api/threads with Yeo as participant; updates store + fires callback', async () => {
    let selected: string | null = null;
    render(<ThreadSidebar onThreadSelected={(id) => { selected = id; }} activeThreadId={null} />);
    fireEvent.click(screen.getByTestId('sidebar-new-chat'));
    await waitFor(() => {
      expect(postBody).toMatchObject({ participants: ['yeo-id'] });
    });
    await waitFor(() => {
      expect(useStore.getState().chatThreads.get('new-thread-id')?.id).toBe('new-thread-id');
      expect(useStore.getState().activeThreadId).toBe('new-thread-id');
      expect(useStore.getState().threadIdByAgent.get('yeo-id')).toBe('new-thread-id');
      expect(selected).toBe('new-thread-id');
    });
  });

  it('disables the button when Yeo agent is not loaded', () => {
    useStore.setState({ agents: new Map() });
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    const btn = screen.getByTestId('sidebar-new-chat') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});
