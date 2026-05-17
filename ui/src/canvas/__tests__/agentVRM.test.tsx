// AD-721f: Cognitive-Canvas VRM avatar replacement -- unit tests for the
// pure helper and the AgentVRM mount path.
//
// Heavy three.js / r3f modules are mocked so the suite runs under jsdom.
// The pure ``_pickCloseAgents`` helper is the canonical place where
// LOD-cull + concurrency-cap logic lives and is testable without WebGL.

import { describe, expect, test, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import { _pickCloseAgents } from '../agentVRM';

// Capture the constructed loaders so each test can drive the success/error
// callback paths through the same fake.
type LoaderCallbacks = {
  url: string;
  onLoad: (gltf: any) => void;
  onProgress: ((ev: any) => void) | undefined;
  onError: (err: any) => void;
};
const _loaderInvocations: LoaderCallbacks[] = [];

vi.mock('three/examples/jsm/loaders/GLTFLoader.js', () => ({
  GLTFLoader: class {
    register(_plugin: any) { /* no-op */ }
    load(url: string, onLoad: any, onProgress: any, onError: any) {
      _loaderInvocations.push({ url, onLoad, onProgress, onError });
    }
  },
}));

vi.mock('@pixiv/three-vrm', () => ({
  VRMLoaderPlugin: class { constructor(_p: any) { /* no-op */ } },
  VRMUtils: { rotateVRM0: () => { /* no-op */ } },
}));

// Stub the r3f primitives used by AgentVRM so the JSX renders under jsdom.
// ``<group>`` / ``<primitive>`` map to plain divs to keep the tree inspectable.
vi.mock('@react-three/fiber', async () => {
  // No actual r3f runtime in this suite; AgentVRM is the only consumer here
  // and it uses <group> + <primitive> which are r3f-only intrinsics.
  return {
    // useFrame / useThree are only used by AgentNodes tests below.
    useFrame: (_cb: any) => { /* no-op */ },
    useThree: () => ({ camera: { position: { x: 0, y: 0, z: 0 } } }),
  };
});

beforeEach(() => {
  _loaderInvocations.length = 0;
});

describe('AD-721f _pickCloseAgents', () => {
  const mkAgent = (id: string, x: number, y: number, z: number) => ({
    id,
    position: [x, y, z] as [number, number, number],
  });

  test('returns empty when maxCount is 0', () => {
    const agents = [mkAgent('a', 0, 0, 0)];
    expect(_pickCloseAgents(agents, [0, 0, 0], 10, 0)).toEqual([]);
  });

  test('filters by lodDistance and orders closest-first', () => {
    const agents = [
      mkAgent('far', 20, 0, 0),
      mkAgent('mid', 5, 0, 0),
      mkAgent('near', 1, 0, 0),
    ];
    const out = _pickCloseAgents(agents, [0, 0, 0], 10, 5);
    expect(out.map((a) => a.id)).toEqual(['near', 'mid']);
  });

  test('respects maxCount cap (concurrency limit)', () => {
    const agents = Array.from({ length: 20 }, (_, i) =>
      mkAgent(`a${i}`, i * 0.5, 0, 0),
    );
    const out = _pickCloseAgents(agents, [0, 0, 0], 100, 5);
    expect(out.length).toBe(5);
    // Closest-first ordering preserved (a0..a4)
    expect(out.map((a) => a.id)).toEqual(['a0', 'a1', 'a2', 'a3', 'a4']);
  });

  test('excludes load-failed agents (orb fallback)', () => {
    const agents = [
      mkAgent('a', 1, 0, 0),
      mkAgent('b', 2, 0, 0),
      mkAgent('c', 3, 0, 0),
    ];
    const failed = new Set<string>(['b']);
    const out = _pickCloseAgents(agents, [0, 0, 0], 10, 5, failed);
    expect(out.map((a) => a.id)).toEqual(['a', 'c']);
  });
});

describe('AD-721f AgentVRM load + error paths', () => {
  test('calls onLoadError when the loader rejects', async () => {
    const { AgentVRM } = await import('../agentVRM');
    const onLoadError = vi.fn();
    render(
      <AgentVRM
        agentId="agent-1"
        position={[0, 0, 0]}
        vrmUrl="missing.vrm"
        onLoadError={onLoadError}
      />,
    );
    expect(_loaderInvocations.length).toBe(1);
    // Simulate a loader error -- the success path returns a VRM; the error
    // path must invoke onLoadError exactly once with the agentId.
    _loaderInvocations[0].onError(new Error('404'));
    expect(onLoadError).toHaveBeenCalledTimes(1);
    expect(onLoadError).toHaveBeenCalledWith('agent-1');
  });

  test('calls onLoadError when the GLTF has no userData.vrm', async () => {
    const { AgentVRM } = await import('../agentVRM');
    const onLoadError = vi.fn();
    render(
      <AgentVRM
        agentId="agent-2"
        position={[0, 0, 0]}
        vrmUrl="not-a-vrm.glb"
        onLoadError={onLoadError}
      />,
    );
    _loaderInvocations[0].onLoad({ userData: {} });
    expect(onLoadError).toHaveBeenCalledTimes(1);
    expect(onLoadError).toHaveBeenCalledWith('agent-2');
  });

  test('renders nothing while VRM is still loading (orb path stays)', async () => {
    const { AgentVRM } = await import('../agentVRM');
    const { container } = render(
      <AgentVRM
        agentId="agent-3"
        position={[1, 2, 3]}
        vrmUrl="slow.vrm"
        onLoadError={() => { /* no-op */ }}
      />,
    );
    // Loader was invoked but no callback fired yet -> component renders null.
    expect(_loaderInvocations.length).toBe(1);
    expect(container.children.length).toBe(0);
  });

  test('empty vrmUrl is a soft-skip (no loader invocation, no error)', async () => {
    const { AgentVRM } = await import('../agentVRM');
    const onLoadError = vi.fn();
    render(
      <AgentVRM
        agentId="agent-4"
        position={[0, 0, 0]}
        vrmUrl=""
        onLoadError={onLoadError}
      />,
    );
    expect(_loaderInvocations.length).toBe(0);
    expect(onLoadError).not.toHaveBeenCalled();
  });
});

// AD-721f-1 forward marker: per-frame budget instrumentation.
// vitest under jsdom has no WebGL renderer, so a synthetic cost measurement
// is not stable. Filed as AD-721f-1 for follow-up; see DECISIONS.md AD-721f.
test.skip('AD-721f-1: per-frame useFrame cost stays under 8 ms at N=12 VRMs', () => {
  // Intentionally deferred.
});
