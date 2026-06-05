/** BF-604: WorkBoard layout fixes.
 *
 * Two HXI regressions on the crew WORK board (AD-497):
 *  - The board header overlapped the fixed ViewSwitcher tab bar; the root now
 *    reserves top clearance so the toolbar sits below the floating tabs.
 *  - Columns were fixed-width equal-flex; each non-terminal column now exposes
 *    a drag handle on its right edge so the board is resizable.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('../store/useStore', () => {
  const state: any = {
    workItems: [],
    bookableResources: [],
    agents: new Map(),
    workTemplates: [],
    moveWorkItem: vi.fn(),
    createWorkItem: vi.fn(),
    assignWorkItem: vi.fn(),
    createFromTemplate: vi.fn(),
    fetchWorkTemplates: vi.fn(),
  };
  const useStore = (selector?: any) => (selector ? selector(state) : state);
  (useStore as any).getState = () => state;
  (useStore as any).__state = state;
  return { useStore };
});

import WorkBoard from '../components/work/WorkBoard';

beforeEach(() => {
  (global as any).fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({ work_items: [] }) }),
  );
});

describe('BF-604 WorkBoard layout', () => {
  it('reserves top clearance so the header does not overlap the tab bar', () => {
    const { container } = render(<WorkBoard />);
    const root = container.firstChild as HTMLElement;
    expect(root.style.paddingTop).toBe('40px');
    expect(root.style.boxSizing).toBe('border-box');
  });

  it('renders a resize handle on every non-terminal column', () => {
    render(<WorkBoard />);
    const handles = screen.getAllByRole('separator');
    // BACKLOG, READY, IN PROGRESS, REVIEW (DONE has no right-edge handle).
    expect(handles).toHaveLength(4);
    expect(screen.getByLabelText('Resize BACKLOG column')).toBeTruthy();
    expect(screen.getByLabelText('Resize REVIEW column')).toBeTruthy();
    expect(screen.queryByLabelText('Resize DONE column')).toBeNull();
  });

  it('gives resize handles the col-resize cursor affordance', () => {
    render(<WorkBoard />);
    const handle = screen.getByLabelText('Resize READY column') as HTMLElement;
    expect(handle.style.cursor).toBe('col-resize');
  });
});
