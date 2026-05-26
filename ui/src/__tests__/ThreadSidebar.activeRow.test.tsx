/** AD-792 (Wave 195) vitest — active thread row receives the amber
 * border-left treatment (HXI #4 motion communicates state); other rows
 * do not. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { useStore } from '../store/useStore';
import { ThreadSidebar } from '../components/sidebar/ThreadSidebar';

beforeEach(() => {
  localStorage.clear();
  useStore.setState({
    agents: new Map(),
    chatThreads: new Map([
      ['tA', { id: 'tA', title: 'Alpha', participants: ['yeo-id'], created_at: 1, last_active_at: Date.now() / 1000, pinned: false, archived: false }],
      ['tB', { id: 'tB', title: 'Beta', participants: ['yeo-id'], created_at: 1, last_active_at: Date.now() / 1000, pinned: false, archived: false }],
    ]),
    activeThreadId: null,
    threadIdByAgent: new Map(),
  });
  global.fetch = vi.fn(() => Promise.resolve({ ok: true, json: async () => ({ threads: [] }) }) as any);
});

afterEach(() => {
  cleanup();
});

describe('ThreadSidebar active row', () => {
  it('amber-border applies only to the active thread', () => {
    render(<ThreadSidebar onThreadSelected={() => {}} activeThreadId="tA" />);
    const rowA = screen.getByTestId('thread-row-tA');
    const rowB = screen.getByTestId('thread-row-tB');
    // Active row carries a 3px amber border-left; inactive row carries transparent.
    // jsdom normalizes hex colors to rgb in style.borderLeft.
    expect(rowA.style.borderLeft).toMatch(/rgb\(240,\s*176,\s*96\)/);
    expect(rowB.style.borderLeft).toContain('transparent');
  });

  it('clicking a non-active row invokes onThreadSelected with its id', () => {
    let selected: string | null = null;
    render(<ThreadSidebar onThreadSelected={(id) => { selected = id; }} activeThreadId="tA" />);
    fireEvent.click(screen.getByTestId('thread-row-tB'));
    expect(selected).toBe('tB');
  });
});
