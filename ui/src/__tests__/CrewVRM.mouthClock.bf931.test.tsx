/** BF-931 (#1669): with deferred visemes the avatar's mouth must not start before the voice is heard.
 *
 * The real `voice.ts` runs with a fake <audio> that fires 'play' as soon as `play()` is called, as a real element
 * does, and fires 'playing' only when the test says so, with `currentTime` at 0 until then. A mounted `CrewVRM`
 * hears the speech 'start' event from the real `voice.ts`. The VRM loader and the render loop are replaced: the
 * loader hands back a model whose face mesh carries the five mouth morphs, and the frame callback is captured and
 * stepped by hand with a controlled clock (the global `performance` is replaced for the case, as the BF-918 voice
 * suite does for its timing case; React's scheduler keeps the real one). The deferred visemes never arrive on their
 * own here (the lipsync request never answers), so the avatar runs on its heuristic track: the window the defect
 * lived in.
 *
 * The cases the unfixed tree fails are `built`, which is `it.fails` until BF-931 M2 sets it to `it`; with
 * BF931_RUNXFAIL=1 they run as ordinary cases. The third case is a control: frames that arrive after playback
 * started were already sampled on the audio time (BF-283). The text is synthetic.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';
import * as THREE from 'three';

const frameLoop = vi.hoisted(() => ({
  callbacks: [] as Array<(state: unknown, delta: number) => void>,
}));
const loaderControls = vi.hoisted(() => ({
  loads: [] as Array<{ url: string; success: (gltf: unknown) => void }>,
}));

vi.mock('@react-three/fiber', () => ({
  useFrame: (callback: (state: unknown, delta: number) => void) => { frameLoop.callbacks.push(callback); },
}));
vi.mock('three/examples/jsm/loaders/GLTFLoader.js', () => ({
  GLTFLoader: class {
    register(): this { return this; }
    load(url: string, success: (gltf: unknown) => void): void {
      loaderControls.loads.push({ url, success });
    }
  },
}));

import * as voice from '../audio/voice';
import { injectLipSyncFrames } from '../audio/useLipSyncCapture';
import { CrewVRM } from '../components/profile/CrewVRM';

const built = process.env.BF931_RUNXFAIL === '1' ? it : it.fails;
const AGENT_ID = 'bf931-agent';
const TEXT = 'Okay, ready when you are.';
const MOUTH_MORPHS = ['Fcl_MTH_A', 'Fcl_MTH_I', 'Fcl_MTH_U', 'Fcl_MTH_E', 'Fcl_MTH_O'];

let audios: FakeAudio[] = [];
let clock = 0;

class FakeUtterance {
  text: string;
  rate = 1;
  pitch = 1;
  volume = 1;
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(text: string) { this.text = text; }
}

/** An <audio> whose `play()` fires 'play' at once, as a real element's does, and whose 'playing' (and a
 *  `currentTime` above 0) comes later, when the test says so. */
class FakeAudio {
  src: string;
  volume = 1;
  playbackRate = 1;
  preservesPitch = true;
  currentTime = 0;
  private listeners: Record<string, Array<() => void>> = {};
  pause = vi.fn(() => { this.emit('pause'); });
  play = vi.fn((): Promise<void> => { this.emit('play'); return Promise.resolve(); });
  removeAttribute = vi.fn();
  load = vi.fn();
  constructor(src: string) {
    this.src = src;
    audios.push(this);
  }
  addEventListener(event: string, listener: () => void): void {
    (this.listeners[event] ||= []).push(listener);
  }
  emit(event: string): void {
    for (const listener of this.listeners[event] ?? []) listener();
  }
}

function installNetwork(): void {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith('/api/avatars/tts/status')) {
      return { ok: true, json: async () => ({ enabled: true, backend: 'piper', sentence_pipelining_enabled: false }) };
    }
    if (url === '/api/avatars/tts') {
      return {
        ok: true,
        json: async () => ({
          backend: 'piper', audio_attachment_id: 'a'.repeat(64), mime: 'audio/wav',
          visemes: [], visemes_deferred: true, duration_ms: 0,
        }),
      };
    }
    if (url === '/api/avatars/lipsync') return new Promise<never>(() => {});
    return Response.json({ clips: [] });
  }));
}

function faceModel(): { mesh: THREE.Mesh; gltf: unknown } {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.2, 0.2), new THREE.MeshBasicMaterial());
  mesh.morphTargetDictionary = Object.fromEntries(MOUTH_MORPHS.map((name, index) => [name, index]));
  mesh.morphTargetInfluences = MOUTH_MORPHS.map(() => 0);
  const scene = new THREE.Group();
  scene.add(mesh);
  const vrm = { scene, meta: { metaVersion: '1' }, humanoid: null, expressionManager: null, update: vi.fn() };
  return { mesh, gltf: { scene, userData: { vrm } } };
}

const mouth = (mesh: THREE.Mesh): number => (mesh.morphTargetInfluences ?? []).reduce((sum, weight) => sum + weight, 0);

async function mountAvatar(): Promise<{ mesh: THREE.Mesh }> {
  const model = faceModel();
  render(
    <CrewVRM
      agentId={AGENT_ID}
      vrmUrl="/avatars/test.vrm"
      expressionOverrides={{}}
      signals={{ trust_delta: 0, load: 0, working_state: 'idle', tier3_alert: false }}
      onLoadError={vi.fn()}
    />,
  );
  expect(loaderControls.loads).toHaveLength(1);
  await act(async () => { loaderControls.loads[0]!.success(model.gltf); });
  return model;
}

/** The real voice.ts speaks TEXT for the avatar's agent: its 'start' event fires from the fake audio's 'play'. */
async function speak(): Promise<FakeAudio> {
  voice._resetTtsStatusForTests();
  voice.speakResponse(TEXT, undefined, AGENT_ID);
  await act(async () => { for (let i = 0; i < 60; i += 1) await Promise.resolve(); });
  expect(audios, 'premise: the reply was synthesized and its audio made').toHaveLength(1);
  expect(audios[0]!.play, 'premise: play() was requested').toHaveBeenCalledTimes(1);
  return audios[0]!;
}

function stepFrame(): void {
  const callback = frameLoop.callbacks[frameLoop.callbacks.length - 1];
  expect(callback, 'CrewVRM registered no frame callback').toBeDefined();
  callback!({}, 1 / 60);
}

beforeEach(() => {
  audios = [];
  frameLoop.callbacks = [];
  loaderControls.loads = [];
  clock = 1000;
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance);
  vi.stubGlobal('Audio', FakeAudio);
  vi.stubGlobal('speechSynthesis', {
    cancel: vi.fn(), speak: vi.fn(), getVoices: () => [], addEventListener: vi.fn(),
  });
  vi.stubGlobal('performance', { now: () => clock, measure: vi.fn(), getEntriesByName: () => [], clearMeasures: vi.fn() });
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  vi.spyOn(console, 'log').mockImplementation(() => {});
  installNetwork();
});

afterEach(() => {
  try { voice.stopSpeaking(); } catch { /* the module's audio state must not leak into the next case */ }
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('BF-931: the avatar mouth follows the voice, not the request to play', () => {
  built('stays closed from the speech start until the audio is playing (its playing fires 300 ms after play)', async () => {
    const model = await mountAvatar();
    await speak();
    for (const elapsed of [100, 200, 299]) {
      clock = 1000 + elapsed; // wall time since play() was requested; playing is due at +300 ms: currentTime stays 0
      stepFrame();
      expect(mouth(model.mesh), `the mouth moved ${elapsed} ms after play() and before playing`).toBe(0);
    }
  });

  built('follows the audio time once it plays, not the wall clock', async () => {
    const model = await mountAvatar();
    const audio = await speak();
    clock += 400; // the wall clock reads a closed instant of this text's heuristic track (measured)
    audio.currentTime = 0.04; // the audio plays and has reached 40 ms, an open instant
    audio.emit('playing');
    stepFrame();
    expect(mouth(model.mesh)).toBeGreaterThan(0);
  });

  it('samples late deferred visemes on the audio time', async () => {
    const model = await mountAvatar();
    const audio = await speak();
    clock += 5000; // far past the frame's window on a wall clock
    audio.currentTime = 0.1;
    audio.emit('playing');
    act(() => injectLipSyncFrames([{ time: 0.04, duration: 0.2, viseme: 'aa' }], AGENT_ID));
    stepFrame();
    expect(mouth(model.mesh)).toBeGreaterThan(0);
  });
});
