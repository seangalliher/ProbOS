/** AD-793 (Wave 196) vitest — ThreadSidebar renders the real Projects
 * section (replacing Wave 195's "Coming with AD-793." placeholder),
 * with expandable rows, thread counts, and localStorage persistence. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { useStore } from '../store/useStore';
import { ThreadSidebar } from '../components/sidebar/ThreadSidebar';

beforeEach(() => {
  localStorage.clear();
  useStore.setState({
    agents: new Map([['yeo-id', { id: 'yeo-id', callsign: 'Yeo', displayName: 'Yeo' } as any]]),
    chatThreads: new Map([
      ['t-loose', { id: 't-loose', title: 'Loose Chat', participants: ['yeo-id'], created_at: 1, last_active_at: Date.now() / 1000, pinned: false, archived: false, project_id: null }],
      ['t-in-p1-a', { id: 't-in-p1-a', title: 'P1 Chat A', participants: ['yeo-id'], created_at: 1, last_active_at: Date.now() / 1000, pinned: false, archived: false, project_id: 'p1' }],
      ['t-in-p1-b', { id: 't-in-p1-b', title: 'P1 Chat B', participants: ['yeo-id'], created_at: 1, last_active_at: Date.now() / 1000 - 100, pinned: false, archived: false, project_id: 'p1' }],
    ]),
    projects: new Map([
      ['p1', { id: 'p1', name: 'ProbOS Dev', description: 'OSS work', pinned_attachment_ids: [], archived: false, created_at: 1, last_active_at: Date.now() / 1000 }],
      ['p2', { id: 'p2', name: 'Newsletter', description: '', pinned_attachment_ids: [], archived: false, created_at: 1, last_active_at: Date.now() / 1000 - 200 }],
    ]),
    activeThreadId: null,
    threadIdByAgent: new Map(),
  });
  global.fetch = vi.fn((url: any) => {
    const u = String(url);
    if (u.startsWith('/api/projects')) {
      return Promise.resolve({ ok: true, json: async () => ({ projects: [] }) }) as any;
    }
    return Promise.resolve({ ok: true, json: async () => ({ threads: [] }) }) as any;
  });
});

afterEach(() => {
  cleanup();
});

describe('ThreadSidebar projects section', () => {
  it('renders projects with thread counts and excludes project-bound threads from Recents', () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    // Both projects rendered.
    expect(screen.getByTestId('project-row-p1')).toBeInTheDocument();
    expect(screen.getByTestId('project-row-p2')).toBeInTheDocument();
    expect(screen.getByText('ProbOS Dev')).toBeInTheDocument();
    expect(screen.getByText('Newsletter')).toBeInTheDocument();
    // Thread count "2" for p1 visible in the row.
    expect(screen.getByLabelText('Project ProbOS Dev (2 threads)')).toBeInTheDocument();
    expect(screen.getByLabelText('Project Newsletter (0 threads)')).toBeInTheDocument();
    // Recents: only loose thread (project-bound threads filtered out).
    expect(screen.getByText('Loose Chat')).toBeInTheDocument();
    expect(screen.queryByText('P1 Chat A')).not.toBeInTheDocument();
    expect(screen.queryByText('P1 Chat B')).not.toBeInTheDocument();
  });

  it('expands a project when chevron clicked and shows nested threads; persists to localStorage', () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    // Initially collapsed → nested threads not visible.
    expect(screen.queryByText('P1 Chat A')).not.toBeInTheDocument();
    // Click to expand.
    fireEvent.click(screen.getByTestId('project-row-p1'));
    // Now nested threads visible.
    expect(screen.getByText('P1 Chat A')).toBeInTheDocument();
    expect(screen.getByText('P1 Chat B')).toBeInTheDocument();
    // localStorage persisted.
    const raw = localStorage.getItem('probos.sidebar.projects.expanded');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed.p1).toBe(true);
    // Click again to collapse.
    fireEvent.click(screen.getByTestId('project-row-p1'));
    expect(screen.queryByText('P1 Chat A')).not.toBeInTheDocument();
  });

  it('shows "No threads yet" when an expanded project is empty', () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    fireEvent.click(screen.getByTestId('project-row-p2'));
    expect(screen.getByTestId('project-empty-p2')).toBeInTheDocument();
    expect(screen.getByText('No threads yet')).toBeInTheDocument();
  });
});
