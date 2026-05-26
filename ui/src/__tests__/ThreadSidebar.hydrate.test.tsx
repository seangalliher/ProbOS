/** AD-792 (Wave 195) vitest — ThreadSidebar fires GET /api/threads on
 * mount and pipes the result through hydrateChatThreads. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, waitFor, cleanup } from '@testing-library/react';
import { useStore } from '../store/useStore';
import { ThreadSidebar } from '../components/sidebar/ThreadSidebar';

let lastUrl: string = '';
const seenUrls: string[] = [];

beforeEach(() => {
  localStorage.clear();
  useStore.setState({
    agents: new Map(),
    chatThreads: new Map(),
    activeThreadId: null,
    threadIdByAgent: new Map(),
  });
  lastUrl = '';
  seenUrls.length = 0;
  global.fetch = vi.fn((url: any) => {
    const u = String(url);
    lastUrl = u;
    seenUrls.push(u);
    // AD-793: ThreadSidebar now hydrates threads + projects in
    // parallel. Distinguish by URL so each receives a valid body.
    if (u.startsWith('/api/projects')) {
      return Promise.resolve({
        ok: true,
        json: async () => ({ projects: [] }),
      }) as any;
    }
    return Promise.resolve({
      ok: true,
      json: async () => ({
        threads: [
          { id: 'h1', title: 'Hydrated', participants: ['yeo-id'], created_at: 1, last_active_at: Date.now() / 1000, pinned: false, archived: false },
        ],
      }),
    }) as any;
  });
});

afterEach(() => {
  cleanup();
});

describe('ThreadSidebar hydration', () => {
  it('fires GET /api/threads with include_archived=false and seeds chatThreads', async () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    await waitFor(() => {
      const threadsUrl = seenUrls.find((u) => u.startsWith('/api/threads?'));
      expect(threadsUrl).toBeDefined();
      expect(threadsUrl).toContain('include_archived=false');
      expect(threadsUrl).toContain('limit=100');
    });
    await waitFor(() => {
      expect(useStore.getState().chatThreads.get('h1')?.title).toBe('Hydrated');
    });
  });

  it('honest-degrades silently when /api/threads returns non-ok', async () => {
    global.fetch = vi.fn(() => Promise.resolve({ ok: false, json: async () => ({}) }) as any);
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    // Should not throw; chatThreads stays empty.
    await waitFor(() => {
      expect(useStore.getState().chatThreads.size).toBe(0);
    });
  });
});
