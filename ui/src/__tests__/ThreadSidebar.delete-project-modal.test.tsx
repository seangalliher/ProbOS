/** AD-793 (Wave 196) vitest — DELETE confirmation modal with cascade
 * radio. Default unparent; cascade requires a second confirmation
 * click before firing. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { useStore } from '../store/useStore';
import { ThreadSidebar } from '../components/sidebar/ThreadSidebar';

let lastDeleteCall: { url: string } | null = null;

beforeEach(() => {
  localStorage.clear();
  lastDeleteCall = null;
  useStore.setState({
    agents: new Map([['yeo-id', { id: 'yeo-id', callsign: 'Yeo', displayName: 'Yeo' } as any]]),
    chatThreads: new Map([
      ['t-in-p1', { id: 't-in-p1', title: 'Inside P1', participants: ['yeo-id'], created_at: 1, last_active_at: Date.now() / 1000, pinned: false, archived: false, project_id: 'p1' }],
    ]),
    projects: new Map([
      ['p1', { id: 'p1', name: 'DeleteMe', description: '', pinned_attachment_ids: [], archived: false, created_at: 1, last_active_at: Date.now() / 1000 }],
    ]),
    activeThreadId: null,
    threadIdByAgent: new Map(),
  });
  global.fetch = vi.fn((url: any, init: any) => {
    const u = String(url);
    if (u.startsWith('/api/projects/p1') && init?.method === 'DELETE') {
      lastDeleteCall = { url: u };
      const cascade = u.includes('cascade=true');
      return Promise.resolve({
        ok: true,
        json: async () => ({ deleted: true, affected_threads: 1, cascade }),
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

describe('ThreadSidebar delete project modal', () => {
  it('shows delete confirmation with unparent as default', () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    fireEvent.contextMenu(screen.getByTestId('project-row-p1'));
    fireEvent.click(screen.getByTestId('project-ctx-delete'));
    const modal = screen.getByTestId('project-delete-confirm');
    expect(modal).toBeInTheDocument();
    const unparent = screen.getByTestId('project-delete-mode-unparent') as HTMLInputElement;
    const cascade = screen.getByTestId('project-delete-mode-cascade') as HTMLInputElement;
    expect(unparent.checked).toBe(true);
    expect(cascade.checked).toBe(false);
  });

  it('unparent confirmation fires DELETE with cascade=false', async () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    fireEvent.contextMenu(screen.getByTestId('project-row-p1'));
    fireEvent.click(screen.getByTestId('project-ctx-delete'));
    fireEvent.click(screen.getByTestId('project-delete-confirm-btn'));
    await waitFor(() => expect(lastDeleteCall).not.toBeNull());
    expect(lastDeleteCall!.url).toContain('cascade=false');
    // Project removed from store; contained thread unparented.
    await waitFor(() => {
      expect(useStore.getState().projects.has('p1')).toBe(false);
      expect(useStore.getState().chatThreads.get('t-in-p1')?.project_id).toBeNull();
    });
  });

  it('cascade requires a second confirmation click before firing', async () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    fireEvent.contextMenu(screen.getByTestId('project-row-p1'));
    fireEvent.click(screen.getByTestId('project-ctx-delete'));
    // Switch to cascade mode.
    fireEvent.click(screen.getByTestId('project-delete-mode-cascade'));
    // First click → no DELETE yet; warning shown.
    fireEvent.click(screen.getByTestId('project-delete-confirm-btn'));
    expect(lastDeleteCall).toBeNull();
    expect(screen.getByTestId('project-delete-cascade-warning')).toBeInTheDocument();
    // Second click → DELETE fires with cascade=true.
    fireEvent.click(screen.getByTestId('project-delete-confirm-btn'));
    await waitFor(() => expect(lastDeleteCall).not.toBeNull());
    expect(lastDeleteCall!.url).toContain('cascade=true');
    // Project + cascaded thread removed from store.
    await waitFor(() => {
      expect(useStore.getState().projects.has('p1')).toBe(false);
      expect(useStore.getState().chatThreads.has('t-in-p1')).toBe(false);
    });
  });
});
