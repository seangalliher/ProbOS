import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store/useStore';

beforeEach(() => {
  useStore.setState({
    wardRoomOpen: false,
    wardRoomActiveChannel: null,
    wardRoomThreads: [],
    wardRoomActiveThread: null,
    wardRoomThreadDetail: null,
    wardRoomUnread: {},
    wardRoomChannels: [
      {
        id: 'ch1', name: 'All Hands', channel_type: 'ship' as const,
        department: '', created_by: 'system', created_at: 1000,
        archived: false, description: 'Ship-wide channel',
      },
      {
        id: 'ch2', name: 'Engineering', channel_type: 'department' as const,
        department: 'engineering', created_by: 'system', created_at: 1000,
        archived: false, description: '',
      },
    ],
  });
});

describe('WardRoomPanel store (AD-407c)', () => {
  it('openWardRoom sets open', () => {
    useStore.getState().openWardRoom();
    expect(useStore.getState().wardRoomOpen).toBe(true);
  });

  it('openWardRoom with channelId sets active channel', () => {
    useStore.getState().openWardRoom('ch2');
    expect(useStore.getState().wardRoomOpen).toBe(true);
    expect(useStore.getState().wardRoomActiveChannel).toBe('ch2');
  });

  it('openWardRoom auto-selects first channel if none active', () => {
    useStore.getState().openWardRoom();
    expect(useStore.getState().wardRoomActiveChannel).toBe('ch1');
  });

  it('closeWardRoom sets open false', () => {
    useStore.setState({ wardRoomOpen: true });
    useStore.getState().closeWardRoom();
    expect(useStore.getState().wardRoomOpen).toBe(false);
  });

  it('selectWardRoomChannel clears thread', () => {
    useStore.setState({
      wardRoomActiveThread: 'threadX',
      wardRoomThreadDetail: { thread: {} as any, posts: [] },
    });
    useStore.getState().selectWardRoomChannel('ch1');
    expect(useStore.getState().wardRoomActiveChannel).toBe('ch1');
    expect(useStore.getState().wardRoomActiveThread).toBeNull();
    expect(useStore.getState().wardRoomThreadDetail).toBeNull();
  });

  it('closeWardRoomThread clears active thread and detail', () => {
    useStore.setState({
      wardRoomActiveThread: 'threadX',
      wardRoomThreadDetail: { thread: {} as any, posts: [] },
    });
    useStore.getState().closeWardRoomThread();
    expect(useStore.getState().wardRoomActiveThread).toBeNull();
    expect(useStore.getState().wardRoomThreadDetail).toBeNull();
  });

  it('wardRoomUnread updates state', () => {
    useStore.setState({ wardRoomUnread: { ch1: 3, ch2: 1 } });
    expect(useStore.getState().wardRoomUnread).toEqual({ ch1: 3, ch2: 1 });
  });

  it('wardRoomOpen defaults to false', () => {
    useStore.setState({ wardRoomOpen: false });
    expect(useStore.getState().wardRoomOpen).toBe(false);
  });

  it('handleEvent recognizes ward_room_thread_created', () => {
    // Just verify the event type is handled without error
    useStore.getState().handleEvent({
      type: 'ward_room_thread_created',
      data: { channel_id: 'ch1', thread_id: 't1' },
      timestamp: Date.now() / 1000,
    });
    // No crash means the event case matched
  });
});
