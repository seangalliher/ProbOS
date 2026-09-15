/** AD-792 (Wave 195) vitest — collapse chevron toggles sidebar width
 * 240 ↔ 56 and persists to localStorage under `probos.sidebar.collapsed`. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, render, screen, fireEvent, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('ThreadSidebar collapse', () => {
  it.each([false, true])('preserves preference %s across narrow overlays and width recovery', async (preference) => {
    localStorage.setItem('probos.sidebar.collapsed', preference ? '1' : '0');
    const width = vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(390);
    const onThreadSelected = vi.fn();
    useStore.setState({ chatThreads: new Map([['saved', {
      id: 'saved', title: 'Saved conversation', participants: ['yeo'], created_at: 1, last_active_at: 1,
    }]]) });
    const user = userEvent.setup();
    render(<ThreadSidebar onThreadSelected={onThreadSelected} activeThreadId={null} />);
    expect(screen.getByTestId('thread-sidebar')).toHaveAttribute('data-collapsed', 'true');
    screen.getByRole('button', { name: 'Expand sidebar' }).focus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('dialog', { name: 'Thread navigation' })).toHaveStyle({ position: 'absolute', maxWidth: '100%' });
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toHaveFocus();
    await user.click(screen.getByRole('button', { name: 'Expand sidebar' }));
    await user.click(screen.getByRole('button', { name: 'Open thread Saved conversation' }));
    expect(onThreadSelected).toHaveBeenCalledWith('saved');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(localStorage.getItem('probos.sidebar.collapsed')).toBe(preference ? '1' : '0');
    width.mockReturnValue(900);
    act(() => window.dispatchEvent(new Event('resize')));
    expect(screen.getByTestId('thread-sidebar')).toHaveAttribute('data-collapsed', String(preference));
    expect(localStorage.getItem('probos.sidebar.collapsed')).toBe(preference ? '1' : '0');
  });

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
