/** AD-792 (Wave 195) vitest — ThreadSidebar renders Pinned + Projects +
 * Recents sections, the New-chat button, and the search input on
 * cold-start with mocked chatThreads. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { useStore } from '../store/useStore';
import { ThreadSidebar } from '../components/sidebar/ThreadSidebar';

beforeEach(() => {
  localStorage.clear();
  useStore.setState({
    agents: new Map([['yeo-id', { id: 'yeo-id', callsign: 'Yeo', displayName: 'Yeo' } as any]]),
    chatThreads: new Map([
      ['t1', { id: 't1', title: 'Pinned chat', participants: ['yeo-id'], created_at: 1, last_active_at: Date.now() / 1000, pinned: true, archived: false }],
      ['t2', { id: 't2', title: 'Recent chat', participants: ['yeo-id'], created_at: 1, last_active_at: Date.now() / 1000, pinned: false, archived: false }],
    ]),
    activeThreadId: null,
    threadIdByAgent: new Map(),
  });
  global.fetch = vi.fn(() => Promise.resolve({ ok: true, json: async () => ({ threads: [] }) }) as any);
});

afterEach(() => {
  cleanup();
});

describe('ThreadSidebar render', () => {
  it('renders Pinned, Projects, Recents sections + New chat + Search', () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    expect(screen.getByTestId('sidebar-section-pinned')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-section-projects')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-section-recents')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-new-chat')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-search-input')).toBeInTheDocument();
    expect(screen.getByText('Pinned chat')).toBeInTheDocument();
    expect(screen.getByText('Recent chat')).toBeInTheDocument();
    expect(screen.getByText('Coming with AD-793.')).toBeInTheDocument();
  });

  it('renders empty-state messages when no threads', () => {
    useStore.setState({ chatThreads: new Map() });
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    expect(screen.getByText('No pinned threads yet')).toBeInTheDocument();
    expect(screen.getByText('No recent threads')).toBeInTheDocument();
  });
});
