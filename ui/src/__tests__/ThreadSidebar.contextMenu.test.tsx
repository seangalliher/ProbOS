/** AD-792 (Wave 195) vitest — right-click on a ThreadRow opens the
 * context menu; each menu item (Rename / Pin / Archive / Delete) fires
 * the correct API + store update. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { useStore } from '../store/useStore';
import { ThreadSidebar } from '../components/sidebar/ThreadSidebar';

interface FetchCall {
  url: string;
  method: string;
  body: unknown;
}

let fetchCalls: FetchCall[] = [];

function makeThread(id: string, overrides: Partial<{ pinned: boolean; archived: boolean; title: string }> = {}) {
  return {
    id,
    title: overrides.title ?? `Thread ${id}`,
    participants: ['yeo-id'],
    created_at: 1,
    last_active_at: Date.now() / 1000,
    pinned: overrides.pinned ?? false,
    archived: overrides.archived ?? false,
  };
}

beforeEach(() => {
  localStorage.clear();
  fetchCalls = [];
  useStore.setState({
    agents: new Map(),
    chatThreads: new Map([['t1', makeThread('t1', { title: 'Original title' })]]),
    activeThreadId: null,
    threadIdByAgent: new Map(),
  });
  global.fetch = vi.fn((url: any, init?: any) => {
    const u = String(url);
    const method = (init?.method || 'GET').toUpperCase();
    const body = init?.body ? JSON.parse(init.body) : null;
    fetchCalls.push({ url: u, method, body });
    if (u.includes('/api/threads') && method === 'PATCH') {
      return Promise.resolve({
        ok: true,
        json: async () => ({ ...makeThread('t1'), ...body }),
      }) as any;
    }
    if (u.includes('/api/threads/t1') && method === 'DELETE') {
      return Promise.resolve({ ok: true, json: async () => ({ deleted: true, thread_id: 't1' }) }) as any;
    }
    return Promise.resolve({ ok: true, json: async () => ({ threads: [] }) }) as any;
  });
});

afterEach(() => {
  cleanup();
});

describe('ThreadSidebar context menu', () => {
  it('right-click opens the menu with all four items', () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    fireEvent.contextMenu(screen.getByTestId('thread-row-t1'));
    expect(screen.getByTestId('thread-context-menu')).toBeInTheDocument();
    expect(screen.getByTestId('ctx-rename')).toBeInTheDocument();
    expect(screen.getByTestId('ctx-pin')).toBeInTheDocument();
    expect(screen.getByTestId('ctx-archive')).toBeInTheDocument();
    expect(screen.getByTestId('ctx-delete')).toBeInTheDocument();
  });

  it('Rename submits PATCH with title + title_locked: true (Wave 194 contract)', async () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    fireEvent.contextMenu(screen.getByTestId('thread-row-t1'));
    fireEvent.click(screen.getByTestId('ctx-rename'));
    const input = screen.getByTestId('thread-rename-input-t1') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'Renamed thread' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => {
      const patch = fetchCalls.find((c) => c.method === 'PATCH');
      expect(patch).toBeDefined();
      expect(patch!.url).toContain('/api/threads/t1');
      expect(patch!.body).toMatchObject({ title: 'Renamed thread', title_locked: true });
    });
  });

  it('Pin toggles PATCH {pinned: true} and re-sorts', async () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    fireEvent.contextMenu(screen.getByTestId('thread-row-t1'));
    fireEvent.click(screen.getByTestId('ctx-pin'));
    await waitFor(() => {
      const patch = fetchCalls.find((c) => c.method === 'PATCH');
      expect(patch?.body).toMatchObject({ pinned: true });
    });
    // Optimistic update.
    expect(useStore.getState().chatThreads.get('t1')?.pinned).toBe(true);
  });

  it('Archive sends PATCH {archived: true} and removes the row from sections', async () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    fireEvent.contextMenu(screen.getByTestId('thread-row-t1'));
    fireEvent.click(screen.getByTestId('ctx-archive'));
    await waitFor(() => {
      const patch = fetchCalls.find((c) => c.method === 'PATCH');
      expect(patch?.body).toMatchObject({ archived: true });
    });
    expect(useStore.getState().chatThreads.get('t1')?.archived).toBe(true);
    // Filtered out of recents.
    expect(screen.queryByText('Original title')).toBeNull();
  });

  it('Delete shows confirm modal then sends DELETE on confirm', async () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    fireEvent.contextMenu(screen.getByTestId('thread-row-t1'));
    fireEvent.click(screen.getByTestId('ctx-delete'));
    expect(screen.getByTestId('thread-delete-confirm')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('thread-delete-confirm-btn'));
    await waitFor(() => {
      const del = fetchCalls.find((c) => c.method === 'DELETE');
      expect(del).toBeDefined();
      expect(del!.url).toContain('/api/threads/t1');
    });
    await waitFor(() => {
      expect(useStore.getState().chatThreads.has('t1')).toBe(false);
    });
  });
});
