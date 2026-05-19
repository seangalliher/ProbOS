/**
 * AD-733c-7-5 — browser-side voice-activity loop tests.
 *
 * BF-287: real ``usePerceptionModeStore``; fetch + getUserMedia mocked
 * at the global boundary. ONNX runtime stubbed via the exported
 * ``_loadOnnxRuntime`` seam.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import * as silero from '../silero-vad';
import {
  startVoiceActivity,
  stopVoiceActivity,
  _processFrame,
  _peekState,
} from '../voiceActivity';
import { usePerceptionModeStore } from '../../store/usePerceptionModeStore';

interface FakeTrack {
  stop: ReturnType<typeof vi.fn>;
}

function installFakeMic(): { stream: MediaStream; stop: ReturnType<typeof vi.fn> } {
  const stop = vi.fn();
  const track: FakeTrack = { stop };
  const stream = {
    getTracks: () => [track as unknown as MediaStreamTrack],
  } as unknown as MediaStream;
  (globalThis as any).navigator = {
    mediaDevices: {
      getUserMedia: vi.fn().mockResolvedValue(stream),
    },
  };
  return { stream, stop };
}

function stubVadSession(scores: number[]) {
  const calls = { i: 0 };
  vi.spyOn(silero, 'createVadSession').mockResolvedValue({
    score: async (_buf: Float32Array) => {
      const s = scores[Math.min(calls.i, scores.length - 1)];
      calls.i += 1;
      return s;
    },
    destroy: vi.fn(),
  });
}

function reset() {
  stopVoiceActivity();
  usePerceptionModeStore.setState({
    mode: null,
    since: null,
    lastDmActivity: null,
    presets: null,
    transitions: [],
    available: false,
    perAgent: {},
    lastSpeechAt: null,
  });
}

describe('voiceActivity (AD-733c-7-5)', () => {
  beforeEach(reset);
  afterEach(() => { reset(); vi.restoreAllMocks(); });

  it('POSTs to /api/perception/voice-activity on sustained speech event', async () => {
    stubVadSession([0.9, 0.9, 0.9]);
    installFakeMic();
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({ ok: true, transitioned: true }),
    });
    (globalThis as any).fetch = fetchMock;

    const armed = await startVoiceActivity({ minSpeechMs: 100 });
    expect(armed).toBe(true);

    const buf = new Float32Array(480);
    // First frame opens the speech window at t=0.
    await _processFrame(buf, 0);
    // Second frame at t=200ms — window exceeds 100ms floor → fires once.
    await _processFrame(buf, 200);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/perception/voice-activity');
    expect(init.method).toBe('POST');
    // Privacy invariant: body MUST contain only metadata.
    const body = init.body as string;
    expect(body).toMatch(/"source":"vad"/);
    expect(body).not.toMatch(/audio|buffer|pcm|base64/i);
  });

  it('debounces sub-threshold events within the speech duration floor', async () => {
    stubVadSession([0.9, 0.2, 0.9, 0.9]);
    installFakeMic();
    const fetchMock = vi.fn().mockResolvedValue({ status: 200, ok: true, json: async () => ({}) });
    (globalThis as any).fetch = fetchMock;

    await startVoiceActivity({ minSpeechMs: 400 });
    const buf = new Float32Array(480);
    await _processFrame(buf, 0);    // window opens
    await _processFrame(buf, 100);  // sub-threshold → resets window
    await _processFrame(buf, 200);  // window reopens
    await _processFrame(buf, 350);  // 150ms held — still below 400ms floor

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('honest-degrades and stops firing on 503 from the endpoint', async () => {
    stubVadSession([0.9, 0.9, 0.9, 0.9, 0.9]);
    installFakeMic();
    const fetchMock = vi.fn().mockResolvedValue({ status: 503, ok: false, json: async () => ({}) });
    (globalThis as any).fetch = fetchMock;

    await startVoiceActivity({ minSpeechMs: 100 });
    const buf = new Float32Array(480);
    await _processFrame(buf, 0);
    await _processFrame(buf, 200);   // first fire → endpoint says 503
    await _processFrame(buf, 400);
    await _processFrame(buf, 600);   // would have fired again — latched off

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(_peekState()?.endpointOff).toBe(true);
  });

  it('releases the mic on stopVoiceActivity()', async () => {
    stubVadSession([0.1]);
    const { stop } = installFakeMic();
    (globalThis as any).fetch = vi.fn();

    await startVoiceActivity();
    stopVoiceActivity();

    expect(stop).toHaveBeenCalledTimes(1);
    expect(_peekState()).toBeNull();
  });
});
