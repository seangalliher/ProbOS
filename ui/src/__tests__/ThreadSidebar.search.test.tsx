/** AD-792 (Wave 195) vitest — search input debounces at 300ms and fires
 * GET /api/threads/search; results replace sections while query is
 * non-empty; clearing the query restores sections. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { useStore } from '../store/useStore';
import { ThreadSidebar } from '../components/sidebar/ThreadSidebar';

const calls: string[] = [];

beforeEach(() => {
  localStorage.clear();
  calls.length = 0;
  useStore.setState({
    agents: new Map(),
    chatThreads: new Map([
      ['t1', { id: 't1', title: 'Normal thread', participants: ['yeo-id'], created_at: 1, last_active_at: Date.now() / 1000, pinned: false, archived: false }],
    ]),
    activeThreadId: null,
    threadIdByAgent: new Map(),
  });
  global.fetch = vi.fn((url: any) => {
    const u = String(url);
    calls.push(u);
    if (u.includes('/api/threads/search')) {
      return Promise.resolve({
        ok: true,
        json: async () => ({
          query: 'sql',
          results: [
            { id: 'sr1', title: 'SQL primer', participants: ['yeo-id'], created_at: 1, last_active_at: Date.now() / 1000, pinned: false, archived: false },
          ],
        }),
      }) as any;
    }
    return Promise.resolve({ ok: true, json: async () => ({ threads: [] }) }) as any;
  });
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe('ThreadSidebar search', () => {
  it('debounces 300ms then fires /api/threads/search; reads data.results (not data.threads)', async () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    const input = screen.getByTestId('sidebar-search-input') as HTMLInputElement;

    fireEvent.change(input, { target: { value: 'sql' } });

    // Below the debounce window — no search call yet.
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    expect(calls.some((u) => u.includes('/api/threads/search'))).toBe(false);

    // Cross the 300ms boundary.
    await act(async () => { await vi.advanceTimersByTimeAsync(200); });
    expect(calls.some((u) => u.includes('/api/threads/search?q=sql'))).toBe(true);

    // Results render under the search-results testid.
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByTestId('sidebar-search-results')).toBeInTheDocument();
    expect(screen.getByText('SQL primer')).toBeInTheDocument();
  });

  it('clearing the query restores sections', async () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    const input = screen.getByTestId('sidebar-search-input') as HTMLInputElement;

    fireEvent.change(input, { target: { value: 'sql' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(400); });
    expect(screen.getByTestId('sidebar-search-results')).toBeInTheDocument();

    fireEvent.change(input, { target: { value: '' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(50); });
    expect(screen.queryByTestId('sidebar-search-results')).toBeNull();
    expect(screen.getByTestId('sidebar-section-pinned')).toBeInTheDocument();
  });
});
