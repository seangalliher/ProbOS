import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useStore } from '../store/useStore';
import { buildEventWebSocketUrl, useWebSocket } from './useWebSocket';

const GENERATION = 'a'.repeat(32);

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  readonly url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  open(): void { this.onopen?.(); }
  message(value: unknown): void {
    this.onmessage?.({ data: JSON.stringify(value) } as MessageEvent);
  }
  serverClose(): void { this.onclose?.(); }
  close(): void {
    this.closed = true;
  }
}

function snapshot(sequence = 0) {
  return {
    type: 'state_snapshot',
    data: {
      agents: [], connections: [], pools: [], system_mode: 'active',
      tc_n: 0, routing_entropy: 0,
    },
    timestamp: 1,
    stream: { generation: GENERATION, sequence },
  };
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeWebSocket);
  useStore.setState({
    connected: false,
    liveGeneration: null,
    liveSequence: 0,
    liveRepairEpoch: 0,
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('AD-1133 useWebSocket', () => {
  it('copies only a non-empty page token into the existing socket URL', () => {
    const withToken = {
      protocol: 'https:', host: 'ship.example', search: '?token=a%20b&other=x',
    } as Location;
    const withoutToken = {
      protocol: 'http:', host: 'localhost:5173', search: '?token=',
    } as Location;
    expect(buildEventWebSocketUrl(withToken)).toBe('wss://ship.example/ws/events?token=a%20b');
    expect(buildEventWebSocketUrl(withoutToken)).toBe('ws://localhost:5173/ws/events');
  });

  it('installs stream authority from the first valid snapshot', () => {
    renderHook(() => useWebSocket());
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.open();
      socket.message(snapshot(7));
    });
    expect(useStore.getState().connected).toBe(true);
    expect(useStore.getState().liveGeneration).toBe(GENERATION);
    expect(useStore.getState().liveSequence).toBe(7);
    expect(useStore.getState().liveRepairEpoch).toBe(1);
  });

  it('ignores stale callbacks from a replaced socket instance', () => {
    vi.useFakeTimers();
    renderHook(() => useWebSocket());
    const first = FakeWebSocket.instances[0];
    act(() => first.serverClose());
    act(() => vi.advanceTimersByTime(1000));
    const second = FakeWebSocket.instances[1];
    act(() => {
      second.open();
      second.message(snapshot(3));
      first.message(snapshot(99));
      first.serverClose();
    });
    expect(useStore.getState().liveSequence).toBe(3);
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it('quarantines replacement-socket deltas until its snapshot arrives', () => {
    vi.useFakeTimers();
    renderHook(() => useWebSocket());
    const first = FakeWebSocket.instances[0];
    act(() => {
      first.open();
      first.message(snapshot(3));
      first.serverClose();
    });
    expect(useStore.getState().liveGeneration).toBeNull();
    act(() => vi.advanceTimersByTime(1000));
    const second = FakeWebSocket.instances[1];
    act(() => {
      second.open();
      second.message({
        type: 'chat_thread_message_appended',
        data: {
          thread_id: 'thread-1', message_id: 'message-1', author_id: 'agent-1',
          role: 'agent', created_at: 2,
        },
        timestamp: 2,
        stream: { generation: GENERATION, sequence: 4 },
      });
    });
    expect(useStore.getState().liveSequence).toBe(3);
    expect(useStore.getState().liveGeneration).toBeNull();
    act(() => second.message(snapshot(4)));
    expect(useStore.getState().liveGeneration).toBe(GENERATION);
    expect(useStore.getState().liveSequence).toBe(4);
  });

  it('clears a pending reconnect timeout and closes the current socket on unmount', () => {
    vi.useFakeTimers();
    const view = renderHook(() => useWebSocket());
    const first = FakeWebSocket.instances[0];
    act(() => first.serverClose());
    view.unmount();
    act(() => vi.advanceTimersByTime(30_000));
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(first.closed).toBe(false);
  });

  it('ignores malformed JSON and ping frames', () => {
    renderHook(() => useWebSocket());
    const socket = FakeWebSocket.instances[0];
    act(() => {
      socket.onmessage?.({ data: '{' } as MessageEvent);
      socket.message({ type: 'ping', timestamp: 1 });
    });
    expect(useStore.getState().liveGeneration).toBeNull();
  });
});