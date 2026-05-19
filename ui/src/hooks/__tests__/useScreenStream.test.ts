/**
 * AD-733-2: useScreenStream hook tests.
 *
 * Mirrors useCameraStream.test.ts shape: mocks getDisplayMedia, fetch,
 * and the track lifecycle. The capture loop is exercised at the
 * boundaries that matter (getDisplayMedia, track.stop, onended auto-stop).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
  startScreenStream,
  stopScreenStream,
  _testReset,
} from '../useScreenStream';
import { useScreenStore } from '../../store/useScreenStore';

class FakeTrack {
  stopped = false;
  kind: string;
  onended: (() => void) | null = null;
  constructor(kind: string) {
    this.kind = kind;
  }
  stop() {
    this.stopped = true;
  }
}

class FakeMediaStream {
  tracks: FakeTrack[] = [new FakeTrack('video')];
  getTracks() {
    return this.tracks;
  }
}

function _installGetDisplayMediaMock(stream: FakeMediaStream | Error) {
  const md = {
    getDisplayMedia: vi.fn(async () => {
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
  useScreenStore.setState({
    active: false,
    sessionId: null,
    error: null,
    framesSent: 0,
  });
});

describe('useScreenStream (AD-733-2)', () => {
  it('startScreenStream calls getDisplayMedia and marks store active', async () => {
    const stream = new FakeMediaStream();
    const md = _installGetDisplayMediaMock(stream);
    vi.spyOn(global, 'fetch').mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({ ok: true, attachment_ref: 'scr' }),
    } as unknown as Response);

    await startScreenStream({ fps: 1 });

    expect(md.getDisplayMedia).toHaveBeenCalledTimes(1);
    expect(useScreenStore.getState().active).toBe(true);
    expect(useScreenStore.getState().sessionId).not.toBeNull();

    await stopScreenStream();
  });

  it('track.onended auto-stops the stream', async () => {
    const stream = new FakeMediaStream();
    _installGetDisplayMediaMock(stream);
    vi.spyOn(global, 'fetch').mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({}),
    } as unknown as Response);

    await startScreenStream({ fps: 1 });
    expect(useScreenStore.getState().active).toBe(true);

    // Simulate the operator clicking the browser's "Stop sharing" pill.
    const track = stream.tracks[0];
    expect(typeof track.onended).toBe('function');
    track.onended!();

    // The onended callback schedules stopScreenStream(); flush microtasks.
    await new Promise((r) => setTimeout(r, 0));
    expect(stream.tracks.every((t) => t.stopped)).toBe(true);
    expect(useScreenStore.getState().active).toBe(false);
  });

  it('stopScreenStream stops every track returned by getDisplayMedia', async () => {
    const stream = new FakeMediaStream();
    _installGetDisplayMediaMock(stream);
    vi.spyOn(global, 'fetch').mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({}),
    } as unknown as Response);

    await startScreenStream({ fps: 1 });
    await stopScreenStream();

    expect(stream.tracks.every((t) => t.stopped)).toBe(true);
    expect(useScreenStore.getState().active).toBe(false);
  });

  it('surfaces getDisplayMedia rejection without crashing', async () => {
    _installGetDisplayMediaMock(new Error('NotAllowedError'));
    await startScreenStream({ fps: 1 });
    expect(useScreenStore.getState().active).toBe(false);
    expect(useScreenStore.getState().error).toMatch(/getDisplayMedia failed/);
  });

  it('startScreenStream is idempotent — second call is a no-op', async () => {
    const stream = new FakeMediaStream();
    const md = _installGetDisplayMediaMock(stream);
    vi.spyOn(global, 'fetch').mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({}),
    } as unknown as Response);

    await startScreenStream({ fps: 1 });
    await startScreenStream({ fps: 1 });

    expect(md.getDisplayMedia).toHaveBeenCalledTimes(1);
    await stopScreenStream();
  });
});
