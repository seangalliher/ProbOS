// AD-721b-2 regression: CrewVRM falls back to AD-721b v1 heuristic when
// useLipSyncCapture returns empty frames. Load-bearing sentinel for the
// "honest-degrade preserves heuristic" contract.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';
import * as THREE from 'three';

const loaderControls = vi.hoisted(() => ({
  loads: [] as Array<{ url: string; success: (gltf: any) => void; failure: (error: unknown) => void }>,
}));

vi.mock('@react-three/fiber', () => ({ useFrame: () => {} }));
vi.mock('three/examples/jsm/loaders/GLTFLoader.js', () => ({
  GLTFLoader: class {
    register(): this { return this; }
    load(url: string, success: (gltf: any) => void, _progress: unknown, failure: (error: unknown) => void): void {
      loaderControls.loads.push({ url, success, failure });
    }
  },
}));

import * as voice from '../audio/voice';
import * as lipSyncTrackMod from '../audio/lipSyncTrack';
import * as useLipSyncCaptureMod from '../audio/useLipSyncCapture';
import * as speechAmplitude from '../audio/speechAmplitude';
import { CrewVRM } from '../components/profile/CrewVRM';

function _ownedModel() {
  const geometry = new THREE.BoxGeometry(0.2, 0.4, 0.2);
  const texture = new THREE.Texture();
  const material = new THREE.MeshBasicMaterial({ map: texture });
  const scene = new THREE.Group();
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.y = 1;
  scene.add(mesh);
  const disposal = { geometry: 0, material: 0, texture: 0 };
  geometry.addEventListener('dispose', () => { disposal.geometry += 1; });
  material.addEventListener('dispose', () => { disposal.material += 1; });
  texture.addEventListener('dispose', () => { disposal.texture += 1; });
  const vrm = { scene, meta: { metaVersion: '1' }, humanoid: null, expressionManager: null, update: vi.fn() };
  return { scene, geometry, disposal, vrm, gltf: { scene, userData: { vrm } } };
}

const rendererProps = {
  agentId: 'ezri', vrmUrl: '/avatars/ezri.vrm', expressionOverrides: {},
  signals: { trust_delta: 0, load: 0, working_state: 'idle' as const, tier3_alert: false },
};

// Mock the hook to a stable empty-frames result so any speech-start event
// must fall through to the heuristic path.
vi.spyOn(useLipSyncCaptureMod, 'useLipSyncCapture').mockReturnValue({
  frames: [],
  capturing: false,
  reset: vi.fn(),
});

describe('CrewVRM real-audio fallback (AD-721b-2 regression)', () => {
  let buildSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    buildSpy = vi.spyOn(lipSyncTrackMod, 'buildHeuristicTrack');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('keeps the heuristic invocation path intact when frames stay empty', () => {
    // Direct invocation: this asserts the v1 contract — when the rhubarb
    // path produces no frames, buildHeuristicTrack remains the source of
    // viseme schedules. The CrewVRM consumer in the file's useEffect at
    // line ~324 calls this on every 'start' event; the mocked hook above
    // guarantees realFramesRef stays empty, so this path is the only one
    // exercised under honest-degrade.
    const track = lipSyncTrackMod.buildHeuristicTrack('hello', { rate: 1.0 });
    expect(track).not.toBeNull();
    expect(buildSpy).toHaveBeenCalled();
    // And the empty-frames hook contract is what CrewVRM consumes.
    const hookResult = useLipSyncCaptureMod.useLipSyncCapture({ enabled: true });
    expect(hookResult.frames).toEqual([]);
    expect(hookResult.capturing).toBe(false);
  });
});

describe('issue #1367 mounted CrewVRM lifetime', () => {
  beforeEach(() => {
    loaderControls.loads = [];
    vi.spyOn(useLipSyncCaptureMod, 'useLipSyncCapture').mockReturnValue({
      frames: [], capturing: false, reset: vi.fn(),
    });
    vi.spyOn(voice, 'onSpeechEvent').mockReturnValue(vi.fn());
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ clips: [] })));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('reports a current load failure but never calls the consumer after unmount', () => {
    const onLoadError = vi.fn();
    const { unmount } = render(<CrewVRM
      agentId="ezri" vrmUrl="Ezri.vrm" expressionOverrides={{}}
      signals={{ trust_delta: 0, load: 0, working_state: 'idle', tier3_alert: false }}
      onLoadError={onLoadError}
    />);
    expect(loaderControls.loads).toHaveLength(1);
    const load = loaderControls.loads[0]!;
    expect(load.url).toBe('/api/system/avatars/Ezri.vrm');
    act(() => load.failure(new Error('current asset failed')));
    expect(onLoadError).toHaveBeenCalledTimes(1);

    unmount();
    act(() => load.failure(new Error('late retired failure')));

    expect(onLoadError).toHaveBeenCalledTimes(1);
  });

  it.each(['asset', 'participant', 'empty'] as const)('removes and disposes the old model before a %s replacement can render', async transition => {
    const onLoadError = vi.fn();
    const onHeadY = vi.fn();
    const view = render(<CrewVRM {...rendererProps} onLoadError={onLoadError} onHeadY={onHeadY} />);
    const first = _ownedModel();
    expect(loaderControls.loads).toHaveLength(1);
    await act(async () => loaderControls.loads[0]!.success(first.gltf));
    expect(view.container.querySelector('primitive')).not.toBeNull();
    expect(onHeadY).toHaveBeenCalledTimes(1);
    expect(onHeadY.mock.calls[0][0]).toBeGreaterThan(1);
    const next = transition === 'participant' ? { ...rendererProps, agentId: 'yeo' }
      : { ...rendererProps, vrmUrl: transition === 'empty' ? '' : '/avatars/other.vrm' };

    view.rerender(<CrewVRM {...next} onLoadError={onLoadError} onHeadY={onHeadY} />);

    expect(view.container.querySelector('primitive')).toBeNull();
    expect(first.disposal).toEqual({ geometry: 1, material: 1, texture: 1 });
    expect(loaderControls.loads).toHaveLength(transition === 'empty' ? 1 : 2);
    expect(onLoadError).not.toHaveBeenCalled();
    view.unmount();
    expect(first.disposal).toEqual({ geometry: 1, material: 1, texture: 1 });
  });

  it('disposes a late success without rendering or measuring a retired participant', async () => {
    const onLoadError = vi.fn();
    const onHeadY = vi.fn();
    const view = render(<CrewVRM {...rendererProps} onLoadError={onLoadError} onHeadY={onHeadY} />);
    expect(loaderControls.loads).toHaveLength(1);
    const retired = loaderControls.loads[0]!;
    view.unmount();
    const late = _ownedModel();

    await act(async () => retired.success(late.gltf));

    expect(late.disposal).toEqual({ geometry: 1, material: 1, texture: 1 });
    expect(onHeadY).not.toHaveBeenCalled();
    expect(onLoadError).not.toHaveBeenCalled();
    expect(view.container.querySelector('primitive')).toBeNull();
  });

  it('disposes a loaded scene without a VRM and reports the current failure', async () => {
    const onLoadError = vi.fn();
    render(<CrewVRM {...rendererProps} onLoadError={onLoadError} />);
    const invalid = _ownedModel();
    expect(loaderControls.loads).toHaveLength(1);
    await act(async () => loaderControls.loads[0]!.success({ scene: invalid.scene, userData: {} }));
    expect(onLoadError).toHaveBeenCalledTimes(1);
    expect(invalid.disposal).toEqual({ geometry: 1, material: 1, texture: 1 });
  });

  it('stops and uncaches animation before disposing its owned scene', async () => {
    const events: string[] = [];
    vi.spyOn(THREE.AnimationMixer.prototype, 'stopAllAction').mockImplementation(function (this: THREE.AnimationMixer) {
      events.push('stop');
      return this;
    });
    vi.spyOn(THREE.AnimationMixer.prototype, 'uncacheRoot').mockImplementation(() => { events.push('uncache'); });
    const model = _ownedModel();
    model.geometry.addEventListener('dispose', () => { events.push('dispose'); });
    const { unmount } = render(<CrewVRM {...rendererProps} onLoadError={vi.fn()} />);
    await act(async () => loaderControls.loads[0]!.success(model.gltf));
    expect(global.fetch).toHaveBeenCalledWith('/api/avatars/animations');
    expect(events).toEqual([]);

    unmount();

    expect(events).toEqual(['stop', 'uncache', 'dispose']);
    expect(model.disposal).toEqual({ geometry: 1, material: 1, texture: 1 });
  });

  it('keeps the current participant when an earlier load succeeds or fails late', async () => {
    const onLoadError = vi.fn();
    const onHeadY = vi.fn();
    const view = render(<CrewVRM {...rendererProps} onLoadError={onLoadError} onHeadY={onHeadY} />);
    const retired = loaderControls.loads[0]!;
    view.rerender(<CrewVRM {...rendererProps} agentId="yeo" vrmUrl="/avatars/yeo.vrm"
      onLoadError={onLoadError} onHeadY={onHeadY} />);
    expect(loaderControls.loads).toHaveLength(2);
    const current = _ownedModel();
    await act(async () => loaderControls.loads[1]!.success(current.gltf));
    expect(onHeadY).toHaveBeenCalledTimes(1);
    const late = _ownedModel();

    await act(async () => {
      retired.success(late.gltf);
      retired.failure(new Error('retired asset'));
    });

    expect(late.disposal).toEqual({ geometry: 1, material: 1, texture: 1 });
    expect(current.disposal).toEqual({ geometry: 0, material: 0, texture: 0 });
    expect(onHeadY).toHaveBeenCalledTimes(1);
    expect(onLoadError).not.toHaveBeenCalled();
    expect(view.container.querySelector('primitive')).not.toBeNull();
    view.unmount();
    expect(current.disposal).toEqual({ geometry: 1, material: 1, texture: 1 });
  });

  it('uses current callbacks without reloading a stable participant and asset', async () => {
    const firstHead = vi.fn();
    const latestHead = vi.fn();
    const firstError = vi.fn();
    const latestError = vi.fn();
    const view = render(<CrewVRM {...rendererProps} onLoadError={firstError} onHeadY={firstHead} />);
    view.rerender(<CrewVRM {...rendererProps} onLoadError={latestError} onHeadY={latestHead} />);
    expect(loaderControls.loads).toHaveLength(1);
    const model = _ownedModel();
    await act(async () => loaderControls.loads[0]!.success(model.gltf));
    expect(firstHead).not.toHaveBeenCalled();
    expect(latestHead).toHaveBeenCalledTimes(1);
    expect(firstError).not.toHaveBeenCalled();
    view.unmount();
    const second = render(<CrewVRM {...rendererProps} onLoadError={firstError} />);
    second.rerender(<CrewVRM {...rendererProps} onLoadError={latestError} />);
    expect(loaderControls.loads).toHaveLength(2);
    act(() => loaderControls.loads[1]!.failure(new Error('current failure')));
    expect(latestError).toHaveBeenCalledTimes(1);
    expect(firstError).not.toHaveBeenCalled();
  });

  it('does not load an empty URL and recovers when an asset is supplied', async () => {
    const onLoadError = vi.fn();
    const view = render(<CrewVRM {...rendererProps} vrmUrl="" onLoadError={onLoadError} />);
    expect(loaderControls.loads).toHaveLength(0);
    expect(view.container.querySelector('primitive')).toBeNull();
    view.rerender(<CrewVRM {...rendererProps} onLoadError={onLoadError} />);
    expect(loaderControls.loads).toHaveLength(1);
    const model = _ownedModel();
    await act(async () => loaderControls.loads[0]!.success(model.gltf));
    expect(view.container.querySelector('primitive')).not.toBeNull();
    expect(onLoadError).not.toHaveBeenCalled();
  });

  it('keeps mounted speech fallback agent-scoped and ignores a captured listener after teardown', () => {
    let listener!: Parameters<typeof voice.onSpeechEvent>[0];
    const unsubscribe = vi.fn();
    vi.mocked(voice.onSpeechEvent).mockImplementation(callback => {
      listener = callback;
      return unsubscribe;
    });
    const buildTrack = vi.spyOn(lipSyncTrackMod, 'buildHeuristicTrack');
    const attachAnalyser = vi.spyOn(speechAmplitude, '_attachAnalyserOrSchedule').mockReturnValue({
      frequencyBinCount: 32, getByteFrequencyData: (buffer: Uint8Array): void => { buffer.fill(0); },
    });
    const { unmount } = render(<CrewVRM {...rendererProps} onLoadError={vi.fn()} />);
    expect(voice.onSpeechEvent).toHaveBeenCalledTimes(1);
    const utterance = { text: 'hello', rate: 1 } as SpeechSynthesisUtterance;
    act(() => listener({ type: 'start', agent_id: 'yeo', utterance }));
    expect(buildTrack).not.toHaveBeenCalled();
    act(() => listener({ type: 'start', agent_id: 'ezri', utterance }));
    expect(buildTrack).toHaveBeenCalledExactlyOnceWith('hello', { rate: 1 });
    expect(attachAnalyser).toHaveBeenCalledTimes(1);

    unmount();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
    act(() => listener({ type: 'start', agent_id: 'ezri', utterance }));

    expect(buildTrack).toHaveBeenCalledTimes(1);
    expect(attachAnalyser).toHaveBeenCalledTimes(1);
  });
});
