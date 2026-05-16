/** AD-719a: WardRoomThreadList multi-agent badge tests. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../store/useStore', () => {
  const state: any = {
    wardRoomThreads: [],
    wardRoomActiveChannel: 'ch1',
    wardRoomChannels: [{ id: 'ch1', name: 'ship' }],
    selectWardRoomThread: vi.fn(),
    refreshWardRoomThreads: vi.fn(),
  };
  const useStore = (selector?: any) =>
    selector ? selector(state) : state;
  // Expose getState for the submit path used elsewhere.
  (useStore as any).getState = () => state;
  (useStore as any).__state = state;
  return { useStore };
});

import { WardRoomThreadList } from '../components/wardroom/WardRoomThreadList';
import { useStore as _useStore } from '../store/useStore';

const state = (_useStore as any).__state;

function makeThread(overrides: any = {}) {
  return {
    id: 't1',
    channel_id: 'ch1',
    author_id: 'captain',
    title: 'Plan',
    body: 'body',
    created_at: 0, last_activity: 0,
    pinned: false, locked: false,
    thread_mode: 'discuss',
    max_responders: 0,
    reply_count: 0, net_score: 0,
    author_callsign: 'Captain',
    channel_name: 'ship',
    ...overrides,
  };
}

beforeEach(() => {
  state.wardRoomThreads = [];
});

describe('AD-719a WardRoomThreadList multi-agent badge', () => {
  it('renders multi-agent badge for multi_agent threads', () => {
    state.wardRoomThreads = [makeThread({ id: 't1', thread_mode: 'multi_agent' })];
    render(<WardRoomThreadList />);
    expect(screen.getByTestId('multi-agent-badge-t1')).toBeTruthy();
  });

  it('does NOT render multi-agent badge for discuss threads', () => {
    state.wardRoomThreads = [makeThread({ id: 't2', thread_mode: 'discuss' })];
    render(<WardRoomThreadList />);
    expect(screen.queryByTestId('multi-agent-badge-t2')).toBeNull();
  });

  it('renders multiple threads and only marks the multi_agent one', () => {
    state.wardRoomThreads = [
      makeThread({ id: 't1', thread_mode: 'discuss', title: 'Discuss thread' }),
      makeThread({ id: 't2', thread_mode: 'multi_agent', title: 'MA thread' }),
    ];
    render(<WardRoomThreadList />);
    expect(screen.queryByTestId('multi-agent-badge-t1')).toBeNull();
    expect(screen.getByTestId('multi-agent-badge-t2')).toBeTruthy();
  });

  it('clicking a multi-agent thread fires selectWardRoomThread with the id', () => {
    state.wardRoomThreads = [makeThread({ id: 't9', thread_mode: 'multi_agent' })];
    render(<WardRoomThreadList />);
    // Click the rendered thread row (the title element).
    fireEvent.click(screen.getByText('Plan'));
    expect(state.selectWardRoomThread).toHaveBeenCalledWith('t9');
  });
});
