// AD-722b-4a: integration test for fleet hook wiring into CognitiveCanvas.

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';

const fleetHookMock = vi.hoisted(() => vi.fn());
vi.mock('../avatars/useFleetAvatarTelemetry', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../avatars/useFleetAvatarTelemetry')>();
  return {
    ...actual,
    useFleetAvatarTelemetry: (options: Parameters<typeof actual.useFleetAvatarTelemetry>[0]) => {
      fleetHookMock(options);
      actual.useFleetAvatarTelemetry(options);
    },
  };
});

// Stub heavy three.js / r3f modules so the canvas can render in jsdom.
vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: any) => null,
  useFrame: () => {},
}));
vi.mock('@react-three/drei', () => ({
  OrbitControls: () => null,
}));
vi.mock('three', async (importOriginal) => {
  const actual = (await importOriginal()) as any;
  return { ...actual };
});
// Stub canvas child modules that import three at top-level.
vi.mock('../canvas/agents', () => ({ AgentNodes: () => null }));
vi.mock('../canvas/connections', () => ({ Connections: () => null }));
vi.mock('../canvas/clusters', () => ({ TeamClusters: () => null }));
vi.mock('../canvas/effects', () => ({ Effects: () => null }));
vi.mock('../canvas/animations', () => ({
  HeartbeatPulse: () => null,
  ConsensusFlash: () => null,
  SelfModBloom: () => null,
  RoutingPulse: () => null,
  BackgroundParticles: () => null,
  FeedbackPulse: () => null,
}));
vi.mock('../canvas/scene', () => ({
  modeGrading: () => ({ tint: '#000', exposure: 1.0 }),
}));

import { CognitiveCanvas } from '../components/CognitiveCanvas';
import { useStore } from '../store/useStore';

class _FakeFleetSocket {
  static instances: _FakeFleetSocket[] = [];
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    _FakeFleetSocket.instances.push(this);
  }

  close = vi.fn(() => { this.closed = true; });

  emit(value: unknown): void {
    this.onmessage?.({ data: JSON.stringify(value) });
  }
}

describe('CognitiveCanvas fleet hook integration', () => {
  beforeEach(() => {
    _FakeFleetSocket.instances = [];
    vi.stubGlobal('WebSocket', _FakeFleetSocket);
    useStore.setState({ connected: true, avatarTelemetry: new Map() });
    fleetHookMock.mockClear();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  test('invokes useFleetAvatarTelemetry exactly once with onFrame callback', () => {
    fleetHookMock.mockClear();
    render(<CognitiveCanvas />);
    expect(fleetHookMock).toHaveBeenCalledTimes(1);
    const opts = fleetHookMock.mock.calls[0][0];
    expect(typeof opts.onFrame).toBe('function');
  });

  test('keeps the real fleet connection through store-driven rerenders and fences teardown delivery', () => {
    const view = render(<CognitiveCanvas />);
    expect(_FakeFleetSocket.instances).toHaveLength(1);
    const socket = _FakeFleetSocket.instances[0]!;
    const lateMessage = socket.onmessage!;
    act(() => socket.emit({ type: 'snapshot', agent_id: 'ezri', working_state: 'idle' }));
    expect(useStore.getState().avatarTelemetry.get('ezri')).toEqual({ working_state: 'idle' });
    const firstHandler = fleetHookMock.mock.calls[0][0].onFrame;
    for (let update = 0; update < 60; update += 1) {
      act(() => useStore.setState({ connected: update % 2 !== 0 }));
    }
    expect(fleetHookMock.mock.calls.length).toBeGreaterThan(1);
    expect(fleetHookMock.mock.calls[fleetHookMock.mock.calls.length - 1]![0].onFrame).not.toBe(firstHandler);
    expect(_FakeFleetSocket.instances).toHaveLength(1);
    expect(socket.close).not.toHaveBeenCalled();
    act(() => socket.emit({ type: 'diff', agent_id: 'ezri', working_state: 'thinking' }));
    expect(useStore.getState().avatarTelemetry.get('ezri')).toEqual({ working_state: 'thinking' });
    view.unmount();
    expect(socket.close).toHaveBeenCalledTimes(1);
    expect(socket.closed).toBe(true);
    act(() => lateMessage({ data: JSON.stringify({ type: 'diff', agent_id: 'ezri', working_state: 'stale' }) }));
    expect(useStore.getState().avatarTelemetry.get('ezri')).toEqual({ working_state: 'thinking' });
  });
});
