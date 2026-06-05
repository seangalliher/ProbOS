/** BF-604: ViewSwitcher auto-hides the KANBAN (Mission Control) tab.
 *
 * The KANBAN board only surfaces the build/design pipeline. When there are no
 * active builds it is an empty board sitting next to the crew WORK board, which
 * confused the Captain. The tab now appears only when builds exist, and the
 * viewer falls back to WORK if the tab is hidden out from under it.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('../store/useStore', () => {
  const state: any = { mainViewer: 'work', missionControlTasks: null };
  const useStore: any = (selector?: any) => (selector ? selector(state) : state);
  useStore.getState = () => state;
  useStore.setState = vi.fn((patch: any) =>
    Object.assign(state, typeof patch === 'function' ? patch(state) : patch),
  );
  useStore.__state = state;
  return { useStore };
});

import { ViewSwitcher } from '../components/ViewSwitcher';
import { useStore as _useStore } from '../store/useStore';

const store = _useStore as any;
const state = store.__state;

beforeEach(() => {
  state.mainViewer = 'work';
  state.missionControlTasks = null;
  store.setState.mockClear();
});

describe('BF-604 ViewSwitcher KANBAN visibility', () => {
  it('hides the KANBAN tab when there are no active builds', () => {
    state.missionControlTasks = null;
    render(<ViewSwitcher />);
    expect(screen.queryByText('KANBAN')).toBeNull();
    // The other tabs still render.
    expect(screen.getByText('WORK')).toBeTruthy();
    expect(screen.getByText('SYSTEM')).toBeTruthy();
  });

  it('shows the KANBAN tab when builds are active', () => {
    state.missionControlTasks = [{ id: 'b1', status: 'working' }];
    render(<ViewSwitcher />);
    expect(screen.getByText('KANBAN')).toBeTruthy();
  });

  it('redirects to WORK when the KANBAN view is hidden out from under it', () => {
    state.mainViewer = 'kanban';
    state.missionControlTasks = null;
    render(<ViewSwitcher />);
    expect(store.setState).toHaveBeenCalledWith({ mainViewer: 'work' });
  });

  it('stays on KANBAN while builds are still active', () => {
    state.mainViewer = 'kanban';
    state.missionControlTasks = [{ id: 'b1', status: 'queued' }];
    render(<ViewSwitcher />);
    expect(store.setState).not.toHaveBeenCalledWith({ mainViewer: 'work' });
  });
});
