/** AD-792 (Wave 195) vitest — collapse chevron toggles sidebar width
 * 240 ↔ 56 and persists to localStorage under `probos.sidebar.collapsed`. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useStore } from '../store/useStore';
import { ThreadSidebar, loadSidebarCollapsed } from '../components/sidebar/ThreadSidebar';

beforeEach(() => {
  localStorage.clear();
  useStore.setState({
    agents: new Map(),
    chatThreads: new Map(),
    activeThreadId: null,
    threadIdByAgent: new Map(),
  });
  global.fetch = vi.fn(() => Promise.resolve({ ok: true, json: async () => ({ threads: [] }) }) as any);
});

afterEach(() => {
  cleanup();
});

describe('ThreadSidebar collapse', () => {
  it('starts expanded by default; chevron click collapses + persists', () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId={null} />);
    const sidebar = screen.getByTestId('thread-sidebar');
    expect(sidebar.getAttribute('data-collapsed')).toBe('false');

    fireEvent.click(screen.getByTestId('sidebar-collapse-toggle'));
    expect(screen.getByTestId('thread-sidebar').getAttribute('data-collapsed')).toBe('true');
    expect(localStorage.getItem('probos.sidebar.collapsed')).toBe('1');
  });

  it('honors initialCollapsed prop and loadSidebarCollapsed helper', () => {
    localStorage.setItem('probos.sidebar.collapsed', '1');
    expect(loadSidebarCollapsed()).toBe(true);
    render(<ThreadSidebar initialCollapsed onThreadSelected={() => {}} activeThreadId={null} />);
    expect(screen.getByTestId('thread-sidebar').getAttribute('data-collapsed')).toBe('true');
  });

  it('collapsed view renders the new-chat button and avatar column', () => {
    useStore.setState({
      chatThreads: new Map([
        ['pinA', { id: 'pinA', title: 'Alpha pinned', participants: ['yeo-id'], created_at: 1, last_active_at: Date.now() / 1000, pinned: true, archived: false }],
      ]),
    });
    render(<ThreadSidebar initialCollapsed onThreadSelected={() => {}} activeThreadId={null} />);
    expect(screen.getByTestId('sidebar-new-chat')).toBeInTheDocument();
    // First-letter avatar of the pinned thread.
    expect(screen.getByTestId('thread-row-pinA')).toHaveTextContent('A');
  });
});
