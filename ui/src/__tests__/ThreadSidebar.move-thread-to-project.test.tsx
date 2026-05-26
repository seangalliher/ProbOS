/** AD-793 (Wave 196) vitest — right-click ThreadRow → "Move to
 * project…" → submenu lists projects → picking PATCHes thread.project_id
 * and re-groups the thread under that project's section. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { useStore } from '../store/useStore';
import { ThreadSidebar } from '../components/sidebar/ThreadSidebar';

beforeEach(() => {
  localStorage.clear();
  useStore.setState({
    agents: new Map([['yeo-id', { id: 'yeo-id', callsign: 'Yeo', displayName: 'Yeo' } as any]]),
    chatThreads: new Map([
      ['t-loose', { id: 't-loose', title: 'Loose Chat', participants: ['yeo-id'], created_at: 1, last_active_at: Date.now() / 1000, pinned: false, archived: false, project_id: null }],
    ]),
    projects: new Map([
      ['p1', { id: 'p1', name: 'Target Project', description: '', pinned_attachment_ids: [], archived: false, created_at: 1, last_active_at: Date.now() / 1000 }],
    ]),
    activeThreadId: null,
    threadIdByAgent: new Map(),
  });
  global.fetch = vi.fn((url: any, init: any) => {
    const u = String(url);
    if (u.startsWith('/api/threads/') && init?.method === 'PATCH') {
      const body = JSON.parse(init.body);
      return Promise.resolve({
        ok: true,
        json: async () => ({
          id: 't-loose',
          title: 'Loose Chat',
          participants: ['yeo-id'],
          created_at: 1,
          last_active_at: Date.now() / 1000,
          pinned: false,
          archived: false,
          project_id: body.project_id ?? null,
        }),
      }) as any;
    }
    if (u.startsWith('/api/projects')) {
      return Promise.resolve({ ok: true, json: async () => ({ projects: [] }) }) as any;
    }
    return Promise.resolve({ ok: true, json: async () => ({ threads: [] }) }) as any;
  });
});

afterEach(() => {
  cleanup();
});

describe('ThreadSidebar move thread to project', () => {
  it('right-click → Move to project… → submenu lists target projects + None option', () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    // Right-click the loose thread.
    fireEvent.contextMenu(screen.getByTestId('thread-row-t-loose'));
    // Context menu shown with "Move to project…" item.
    expect(screen.getByTestId('ctx-move-to-project')).toBeInTheDocument();
    // Click it → submenu opens.
    fireEvent.click(screen.getByTestId('ctx-move-to-project'));
    expect(screen.getByTestId('move-to-project-menu-t-loose')).toBeInTheDocument();
    // None option present.
    expect(screen.getByTestId('move-to-project-none-t-loose')).toBeInTheDocument();
    // Target project visible.
    expect(screen.getByTestId('move-to-project-p1')).toBeInTheDocument();
  });

  it('picking a project PATCHes thread and re-groups under that project', async () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    fireEvent.contextMenu(screen.getByTestId('thread-row-t-loose'));
    fireEvent.click(screen.getByTestId('ctx-move-to-project'));
    fireEvent.click(screen.getByTestId('move-to-project-p1'));
    await waitFor(() => {
      const t = useStore.getState().chatThreads.get('t-loose');
      expect(t?.project_id).toBe('p1');
    });
    // PATCH was called with project_id.
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    const patchCall = fetchMock.mock.calls.find(
      (c) => String(c[0]).includes('/api/threads/t-loose') && c[1]?.method === 'PATCH',
    );
    expect(patchCall).toBeTruthy();
    const body = JSON.parse(patchCall![1]!.body);
    expect(body.project_id).toBe('p1');
  });
});
