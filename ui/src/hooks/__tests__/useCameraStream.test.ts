/**
 * AD-733: useCameraStream hook tests.
 *
 * Mocks navigator.mediaDevices.getUserMedia, document.createElement, and
 * fetch — the production capture loop is exercised at the boundaries we
 * actually care about (getUserMedia, fetch, track.stop).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
  startCameraStream,
  stopCameraStream,
  _testReset,
} from '../useCameraStream';
import { useCameraStore } from '../../store/useCameraStore';

class FakeTrack {
  stopped = false;
  kind: string;
  constructor(kind: string) { this.kind = kind; }
  stop() { this.stopped = true; }
}

class FakeMediaStream {
  tracks: FakeTrack[] = [new FakeTrack('video')];
  getTracks() { return this.tracks; }
}

function _installGetUserMediaMock(stream: FakeMediaStream | Error) {
  const md = {
    getUserMedia: vi.fn(async () => {
      if (stream instanceof Error) throw stream;
      return stream as unknown as MediaStream;
    }),
  };
  Object.defineProperty(global.navigator, 'mediaDevices', {
    value: md,
    configurable: true,
    writable: true,
  });
  return md;
}

afterEach(() => {
  _testReset();
  vi.restoreAllMocks();
});

beforeEach(() => {
  useCameraStore.setState({ active: false, sessionId: null, error: null, framesSent: 0, fps: 1 });
});

describe('useCameraStream (AD-733)', () => {
  it('startCameraStream calls getUserMedia and marks store active', async () => {
    const stream = new FakeMediaStream();
    const md = _installGetUserMediaMock(stream);
    vi.spyOn(global, 'fetch').mockResolvedValue({
      status: 200, ok: true,
      json: async () => ({ ok: true, attachment_ref: 'abc' }),
    } as unknown as Response);

    await startCameraStream({ fps: 1 });

    expect(md.getUserMedia).toHaveBeenCalledTimes(1);
    expect(useCameraStore.getState().active).toBe(true);
    expect(useCameraStore.getState().sessionId).not.toBeNull();

    await stopCameraStream();
  });

  it('stopCameraStream stops every track returned by getUserMedia', async () => {
    const stream = new FakeMediaStream();
    _installGetUserMediaMock(stream);
    vi.spyOn(global, 'fetch').mockResolvedValue({
      status: 200, ok: true, json: async () => ({}),
    } as unknown as Response);

    await startCameraStream({ fps: 1 });
    await stopCameraStream();

    expect(stream.tracks.every((t) => t.stopped)).toBe(true);
    expect(useCameraStore.getState().active).toBe(false);
  });

  it('surfaces getUserMedia rejection without crashing', async () => {
    _installGetUserMediaMock(new Error('NotAllowedError'));
    await startCameraStream({ fps: 1 });
    expect(useCameraStore.getState().active).toBe(false);
    expect(useCameraStore.getState().error).toMatch(/getUserMedia failed/);
  });
});
