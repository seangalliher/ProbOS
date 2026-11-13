/** BF-933 (#1671): the camera capture loop under overlapping starts, a stop during a start, a 429 and a slow upload.
 *
 * The defect: `startCameraStream` returned early only when `_stream` was set, and `_stream` is assigned after the
 * `getUserMedia` await, so two overlapping calls both passed, each opened a camera and each created a
 * `setInterval`; the second overwrote the module's one interval id, so the first loop could never be stopped.
 * A stop that arrived while the camera was opening found nothing to stop, and the start then ran. A 429 was dropped
 * and retried on the next tick (its `Retry-After` was never read), and nothing kept a tick from starting a capture
 * while the previous upload was still in flight.
 *
 * The fixtures are synthetic: a fake camera whose `getUserMedia` the test settles by hand, a fake `<video>` and
 * `<canvas>`, a stubbed `fetch` that answers with the statuses the server uses, and a `Retry-After` of a few
 * seconds. They carry no console output, count or timing from the live call that found the defect: this repository
 * is public and its tests hold no vessel data.
 *
 * The cases the unfixed hook fails are `built`, which is `it.fails` until BF-933 S1 M2 sets it to `it`; with
 * BF933_RUNXFAIL=1 they run as ordinary cases, so each can be seen to stop at its own assertion. Time is vitest's
 * fake clock with the system time fixed: the hook reads `Date.now()` and `window.setInterval`/`window.setTimeout`.
 * Every case restores the module (`_testReset`), the timers, the spies and `navigator.mediaDevices`.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
  getCameraStream,
  startCameraStream,
  stopCameraStream,
  _testReset,
} from '../useCameraStream';
import { useCameraStore } from '../../store/useCameraStore';

const built = process.env.BF933_RUNXFAIL === '1' ? it : it.fails;

class FakeTrack {
  stopped = false;
  stop() { this.stopped = true; }
}

class FakeMediaStream {
  tracks: FakeTrack[] = [new FakeTrack()];
  getTracks() { return this.tracks; }
  get released() { return this.tracks.every((t) => t.stopped); }
}

/** A camera the test opens by hand: each getUserMedia call stays pending until the test settles it. */
function installCamera() {
  const streams: FakeMediaStream[] = [];
  const open: Array<() => void> = [];
  const fail: Array<(error: Error) => void> = [];
  const getUserMedia = vi.fn(
    () =>
      new Promise<MediaStream>((resolve, reject) => {
        const stream = new FakeMediaStream();
        streams.push(stream);
        open.push(() => resolve(stream as unknown as MediaStream));
        fail.push(reject);
      }),
  );
  Object.defineProperty(global.navigator, 'mediaDevices', {
    value: { getUserMedia },
    configurable: true,
    writable: true,
  });
  return { getUserMedia, streams, open, fail };
}

/** A fake <video> that is ready (non-zero size) and a fake <canvas> whose encoder answers at once. */
function installElements(options: { play?: () => Promise<void> } = {}) {
  const real = document.createElement.bind(document);
  vi.spyOn(document, 'createElement').mockImplementation(((tag: string, init?: ElementCreationOptions) => {
    if (tag === 'video') {
      return {
        videoWidth: 640,
        videoHeight: 480,
        autoplay: false,
        playsInline: false,
        muted: false,
        srcObject: null,
        play: options.play ?? (async () => undefined),
      } as unknown as HTMLVideoElement;
    }
    if (tag === 'canvas') {
      return {
        width: 0,
        height: 0,
        getContext: () => ({ drawImage: () => undefined }),
        toBlob: (done: BlobCallback) => done(new Blob(['frame'], { type: 'image/jpeg' })),
      } as unknown as HTMLCanvasElement;
    }
    return real(tag, init);
  }) as typeof document.createElement);
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
}

const ok = (): Response => new Response('{}', { status: 200 });
const limited = (retryAfter?: string): Response =>
  new Response('{"error":"rate_limited"}', {
    status: 429,
    headers: retryAfter === undefined ? {} : { 'Retry-After': retryAfter },
  });

/** A fetch whose n-th call answers script[n] (the last entry repeats). */
function installFetch(script: Array<() => Response>) {
  let calls = 0;
  return vi.spyOn(globalThis, 'fetch').mockImplementation(
    async () => script[Math.min(calls++, script.length - 1)](),
  );
}

/** A fetch that never answers on its own: each call waits for the test to release it. */
function installHeldFetch() {
  const release: Array<() => void> = [];
  const send = vi.spyOn(globalThis, 'fetch').mockImplementation(
    () => new Promise<Response>((resolve) => { release.push(() => resolve(ok())); }),
  );
  return { send, release };
}

async function startRunning(camera: ReturnType<typeof installCamera>, index = 0): Promise<void> {
  const started = startCameraStream({ fps: 1 });
  camera.open[index]();
  await started;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2030-01-01T00:00:00.000Z'));
  useCameraStore.setState({ active: false, sessionId: null, error: null, framesSent: 0, fps: 1 });
});

afterEach(() => {
  _testReset();
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete (navigator as { mediaDevices?: unknown }).mediaDevices;
});

describe('BF-933: overlapping starts leak no capture loop', () => {
  built('two overlapping starts share one camera and one capture interval, and one stop leaves none', async () => {
    const camera = installCamera();
    installElements();
    const intervals = vi.spyOn(window, 'setInterval');
    const first = startCameraStream({ fps: 1 });
    const second = startCameraStream({ fps: 1 });
    expect(camera.getUserMedia).toHaveBeenCalledTimes(1);
    camera.open[0]();
    await Promise.all([first, second]);
    expect(intervals).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);
    expect(useCameraStore.getState().active).toBe(true);
    await stopCameraStream();
    expect(vi.getTimerCount()).toBe(0);
    expect(camera.streams.every((s) => s.released)).toBe(true);
    expect(getCameraStream()).toBeNull();
  });

  built('a stop while the camera is opening releases the camera and starts no loop', async () => {
    const camera = installCamera();
    installElements();
    const pending = startCameraStream({ fps: 1 });
    await stopCameraStream();
    camera.open[0]();
    await pending;
    expect(camera.streams[0].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    expect(useCameraStore.getState().active).toBe(false);
    expect(getCameraStream()).toBeNull();
  });

  built('a stop while the video is starting leaves no loop', async () => {
    const camera = installCamera();
    let finishPlay!: () => void;
    installElements({ play: () => new Promise<void>((resolve) => { finishPlay = resolve; }) });
    const pending = startCameraStream({ fps: 1 });
    camera.open[0]();
    await vi.advanceTimersByTimeAsync(0);
    await stopCameraStream();
    finishPlay();
    await pending;
    expect(vi.getTimerCount()).toBe(0);
    expect(useCameraStore.getState().active).toBe(false);
    expect(camera.streams[0].released).toBe(true);
  });

  built('a start after a stop, while the first start is pending, runs one loop and the first stream is released', async () => {
    const camera = installCamera();
    installElements();
    const first = startCameraStream({ fps: 1 });
    await stopCameraStream();
    const second = startCameraStream({ fps: 1 });
    expect(camera.getUserMedia).toHaveBeenCalledTimes(2);
    camera.open[0]();
    camera.open[1]();
    await Promise.all([first, second]);
    expect(camera.streams[0].released).toBe(true);
    expect(camera.streams[1].released).toBe(false);
    expect(vi.getTimerCount()).toBe(1);
    expect(useCameraStore.getState().active).toBe(true);
    await stopCameraStream();
    expect(camera.streams[1].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  built('a cancelled start that then fails reports nothing and leaves the newer start alone', async () => {
    const camera = installCamera();
    installElements();
    const first = startCameraStream({ fps: 1 });
    await stopCameraStream();
    const second = startCameraStream({ fps: 1 });
    camera.open[1]();
    await second;
    camera.fail[0](new Error('NotAllowedError'));
    await first;
    expect(useCameraStore.getState().error).toBeNull();
    expect(useCameraStore.getState().active).toBe(true);
  });
});

describe('BF-933: a tick does not start a capture while the previous upload is in flight', () => {
  built('ticks during a pending upload send nothing, and the first tick after it settles sends again', async () => {
    const camera = installCamera();
    installElements();
    const { send, release } = installHeldFetch();
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3000);
    expect(send).toHaveBeenCalledTimes(1);
    release[0]();
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  built('an upload that settles after a stop and a restart does not release the new loop\'s guard', async () => {
    const camera = installCamera();
    installElements();
    const { send, release } = installHeldFetch();
    await startRunning(camera, 0);
    await vi.advanceTimersByTimeAsync(1000);
    await stopCameraStream();
    await startRunning(camera, 1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
    release[0]();
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  built('an upload that never answers is aborted, and the loop sends again', async () => {
    const camera = installCamera();
    installElements();
    const send = vi.spyOn(globalThis, 'fetch').mockImplementation(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        }),
    );
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10_000);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });
});

describe('BF-933: a 429 is honoured', () => {
  built('a 429 with Retry-After: 3 pauses the uploads for that long, then they resume', async () => {
    const camera = installCamera();
    installElements();
    const send = installFetch([() => limited('3'), ok]);
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  built('without a usable Retry-After the pause doubles from one second, and a 200 starts it over', async () => {
    const camera = installCamera();
    installElements();
    const send = installFetch([() => limited(), () => limited('soon'), ok, () => limited(), ok]);
    await startRunning(camera);
    const calls: number[] = [];
    for (let second = 1; second <= 6; second += 1) {
      await vi.advanceTimersByTimeAsync(1000);
      calls.push(send.mock.calls.length);
    }
    expect(calls).toEqual([1, 2, 2, 3, 4, 5]);
  });

  built('a long Retry-After is capped at thirty seconds', async () => {
    const camera = installCamera();
    installElements();
    const send = installFetch([() => limited('3600'), ok]);
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(29_000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  built('an HTTP-date Retry-After is honoured', async () => {
    const camera = installCamera();
    installElements();
    const send = installFetch([() => limited(new Date('2030-01-01T00:00:05.000Z').toUTCString()), ok]);
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });
});

describe('BF-933: what must not change', () => {
  it('a single start opens one camera and one capture loop, and a stop releases both', async () => {
    const camera = installCamera();
    installElements();
    await startRunning(camera);
    expect(camera.getUserMedia).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);
    expect(useCameraStore.getState().active).toBe(true);
    await stopCameraStream();
    expect(camera.streams[0].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    expect(useCameraStore.getState().active).toBe(false);
  });

  it('a start after the camera is running changes nothing', async () => {
    const camera = installCamera();
    installElements();
    await startRunning(camera);
    await startCameraStream({ fps: 1 });
    expect(camera.getUserMedia).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);
  });

  it('a 200 counts a frame, the form carries the session id, and a stop leaves no timer behind', async () => {
    const camera = installCamera();
    installElements();
    const send = installFetch([ok]);
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    expect(useCameraStore.getState().framesSent).toBe(1);
    const form = send.mock.calls[0][1]?.body as FormData;
    expect(form.get('session_id')).toBe(useCameraStore.getState().sessionId);
    await stopCameraStream();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('a 503 from the server stops the camera, as before', async () => {
    const camera = installCamera();
    installElements();
    installFetch([() => new Response('{"error":"camera_disabled"}', { status: 503 })]);
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(1000);
    expect(useCameraStore.getState().active).toBe(false);
    expect(camera.streams[0].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('a 413 and a network error drop one frame each and keep the loop alive', async () => {
    const camera = installCamera();
    installElements();
    const send = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(async () => new Response('{}', { status: 413 }))
      .mockImplementationOnce(async () => { throw new TypeError('network'); })
      .mockImplementation(async () => ok());
    await startRunning(camera);
    await vi.advanceTimersByTimeAsync(3000);
    expect(send).toHaveBeenCalledTimes(3);
    expect(useCameraStore.getState().framesSent).toBe(1);
    expect(useCameraStore.getState().active).toBe(true);
    expect(vi.getTimerCount()).toBe(1);
  });

  it('a failed camera open reports the error, and a later start can succeed', async () => {
    const camera = installCamera();
    installElements();
    const first = startCameraStream({ fps: 1 });
    camera.fail[0](new Error('NotAllowedError'));
    await first;
    expect(useCameraStore.getState().error).toMatch(/getUserMedia failed/);
    expect(useCameraStore.getState().active).toBe(false);
    await startRunning(camera, 1);
    expect(useCameraStore.getState().active).toBe(true);
    expect(vi.getTimerCount()).toBe(1);
  });

  it('a stop clears the pause and the doubling, so the next call starts clean', async () => {
    const camera = installCamera();
    installElements();
    const send = installFetch([() => limited(), () => limited(), () => limited(), ok]);
    await startRunning(camera, 0);
    await vi.advanceTimersByTimeAsync(2000);
    expect(send).toHaveBeenCalledTimes(2);
    await stopCameraStream();
    await startRunning(camera, 1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(4);
  });
});
