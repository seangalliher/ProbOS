// AD-722b-4a: integration test for fleet hook wiring into CognitiveCanvas.

import { describe, expect, test, vi } from 'vitest';
import { render } from '@testing-library/react';

const fleetHookMock = vi.fn();
vi.mock('../avatars/useFleetAvatarTelemetry', () => ({
  useFleetAvatarTelemetry: (opts: any) => {
    fleetHookMock(opts);
  },
}));

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

describe('CognitiveCanvas fleet hook integration', () => {
  test('invokes useFleetAvatarTelemetry exactly once with onFrame callback', () => {
    fleetHookMock.mockClear();
    render(<CognitiveCanvas />);
    expect(fleetHookMock).toHaveBeenCalledTimes(1);
    const opts = fleetHookMock.mock.calls[0][0];
    expect(typeof opts.onFrame).toBe('function');
  });
});
