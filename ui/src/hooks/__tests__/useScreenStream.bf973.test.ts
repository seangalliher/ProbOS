/** BF-973 (#1804): the screen capture loop under overlapping starts, a stop while the picker is open, a stop during
 * the encode, a slow upload and a 429.
 *
 * The defect: `startScreenStream` returned early only when `_screenStream` was set, and `_screenStream` is assigned
 * after the `getDisplayMedia` await, so two overlapping calls both passed, each opened the picker and each created a
 * `setInterval`. A stop that arrived while the picker was open found nothing to stop, and the start then ran. A 429
 * was dropped with no pause, nothing kept a tick from starting a capture while the previous upload was in flight,
 * and the session id was read after the encode.
 *
 * The fixtures are synthetic, as in useCameraStream.bf933.test.ts: a fake picker whose `getDisplayMedia` the test
 * settles by hand, a fake `<video>` and `<canvas>`, and a stubbed `fetch`. The cases the unbuilt hook fails are
 * `built`, which is `it.fails` until BF-973 M2 sets it to `it`; with BF973_RUNXFAIL=1 they run as ordinary cases,
 * so each can be seen to stop at its own assertion. Time is vitest's fake clock with the system time fixed; no case
 * waits on the wall clock. Every case restores the module (`_testReset`), the timers, the spies and
 * `navigator.mediaDevices`. Each title names its case and the contract's mutation rows (W) that it kills.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
  getScreenStream,
  startScreenStream,
  stopScreenStream,
  _testReset,
} from '../useScreenStream';
import { useScreenStore } from '../../store/useScreenStore';

const built = process.env.BF973_RUNXFAIL === '1' ? it : it.fails;

class FakeTrack {
  stopped = false;
  onended: (() => void) | null = null;
  stop() { this.stopped = true; }
}

class FakeMediaStream {
  tracks: FakeTrack[] = [new FakeTrack()];
  getTracks() { return this.tracks; }
  get released() { return this.tracks.every((t) => t.stopped); }
}

/** A picker the test settles by hand: each getDisplayMedia call stays pending until the test picks or dismisses. */
function installPicker() {
  const streams: FakeMediaStream[] = [];
  const pick: Array<() => void> = [];
  const dismiss: Array<(error: Error) => void> = [];
  const getDisplayMedia = vi.fn(
    () =>
      new Promise<MediaStream>((resolve, reject) => {
        const stream = new FakeMediaStream();
        streams.push(stream);
        pick.push(() => resolve(stream as unknown as MediaStream));
        dismiss.push(reject);
      }),
  );
  Object.defineProperty(global.navigator, 'mediaDevices', {
    value: { getDisplayMedia },
    configurable: true,
    writable: true,
  });
  return { getDisplayMedia, streams, pick, dismiss };
}

/** A fake <video> that is ready and a fake <canvas> whose encoder answers at once unless the case holds it. */
function installElements(options: { play?: () => Promise<void>; toBlob?: (done: BlobCallback) => void } = {}) {
  const real = document.createElement.bind(document);
  vi.spyOn(document, 'createElement').mockImplementation(((tag: string, init?: ElementCreationOptions) => {
    if (tag === 'video') {
      return {
        videoWidth: 1280,
        videoHeight: 720,
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
        toBlob: options.toBlob ?? ((done: BlobCallback) => done(new Blob(['frame'], { type: 'image/jpeg' }))),
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

async function startRunning(picker: ReturnType<typeof installPicker>, index = 0): Promise<void> {
  const started = startScreenStream({ fps: 1 });
  picker.pick[index]();
  await started;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2030-01-01T00:00:00.000Z'));
  useScreenStore.setState({ active: false, sessionId: null, error: null, framesSent: 0 });
});

afterEach(() => {
  _testReset();
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete (navigator as { mediaDevices?: unknown }).mediaDevices;
});

describe('BF-973: overlapping starts and a stop during a start', () => {
  built('S1 [W1] two overlapping starts open one picker and one capture interval, and one stop releases every track', async () => {
    const picker = installPicker();
    installElements();
    const intervals = vi.spyOn(window, 'setInterval');
    const first = startScreenStream({ fps: 1 });
    const second = startScreenStream({ fps: 1 });
    expect(picker.getDisplayMedia).toHaveBeenCalledTimes(1);
    picker.pick[0]();
    await Promise.all([first, second]);
    expect(intervals).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);
    expect(useScreenStore.getState().active).toBe(true);
    await stopScreenStream();
    expect(vi.getTimerCount()).toBe(0);
    expect(picker.streams.every((s) => s.released)).toBe(true);
    expect(getScreenStream()).toBeNull();
  });

  built('S2 [W2] a stop while the picker is open releases the picked capture, starts no loop and posts nothing', async () => {
    const picker = installPicker();
    installElements();
    const send = installFetch([ok]);
    const pending = startScreenStream({ fps: 1 });
    await stopScreenStream();
    picker.pick[0]();
    await pending;
    expect(picker.streams[0].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    expect(useScreenStore.getState().active).toBe(false);
    expect(getScreenStream()).toBeNull();
    await vi.advanceTimersByTimeAsync(3000);
    expect(send).not.toHaveBeenCalled();
  });

  built('S3 [W3] a stop while the video is starting releases the capture and starts no loop', async () => {
    const picker = installPicker();
    let finishPlay!: () => void;
    installElements({ play: () => new Promise<void>((resolve) => { finishPlay = resolve; }) });
    const pending = startScreenStream({ fps: 1 });
    picker.pick[0]();
    await vi.advanceTimersByTimeAsync(0);
    await stopScreenStream();
    finishPlay();
    await pending;
    expect(vi.getTimerCount()).toBe(0);
    expect(useScreenStore.getState().active).toBe(false);
    expect(picker.streams[0].released).toBe(true);
  });

  built('S4 [W2, W4] a start after a stop, while the first picker is open, runs one loop and releases the first capture', async () => {
    const picker = installPicker();
    installElements();
    const first = startScreenStream({ fps: 1 });
    await stopScreenStream();
    const second = startScreenStream({ fps: 1 });
    expect(picker.getDisplayMedia).toHaveBeenCalledTimes(2);
    picker.pick[0]();
    picker.pick[1]();
    await Promise.all([first, second]);
    expect(picker.streams[0].released).toBe(true);
    expect(picker.streams[1].released).toBe(false);
    expect(vi.getTimerCount()).toBe(1);
    expect(useScreenStore.getState().active).toBe(true);
    await stopScreenStream();
    expect(picker.streams[1].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  built('S5 [W5] a cancelled start whose picker is then dismissed reports nothing and leaves the newer start alone', async () => {
    const picker = installPicker();
    installElements();
    const first = startScreenStream({ fps: 1 });
    await stopScreenStream();
    const second = startScreenStream({ fps: 1 });
    picker.pick[1]();
    await second;
    picker.dismiss[0](new Error('NotAllowedError'));
    await first;
    expect(useScreenStore.getState().error).toBeNull();
    expect(useScreenStore.getState().active).toBe(true);
  });
});

describe('BF-973: the frame loop', () => {
  built('S6 [W6] ticks during a pending upload send nothing, and the first tick after it settles sends again', async () => {
    const picker = installPicker();
    installElements();
    const { send, release } = installHeldFetch();
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3000);
    expect(send).toHaveBeenCalledTimes(1);
    release[0]();
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  built('S7 [W8] a stop during the encode posts nothing', async () => {
    const picker = installPicker();
    const encodes: BlobCallback[] = [];
    installElements({ toBlob: (done) => { encodes.push(done); } });
    const send = installFetch([ok]);
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(1000);
    expect(encodes).toHaveLength(1);
    await stopScreenStream();
    encodes[0](new Blob(['frame'], { type: 'image/jpeg' }));
    await vi.advanceTimersByTimeAsync(0);
    expect(send).not.toHaveBeenCalled();
  });

  built('S8 [W7] an upload that settles after a stop and a restart does not release the new loop\'s guard', async () => {
    const picker = installPicker();
    installElements();
    const { send, release } = installHeldFetch();
    await startRunning(picker, 0);
    await vi.advanceTimersByTimeAsync(1000);
    await stopScreenStream();
    await startRunning(picker, 1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
    release[0]();
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  built('S12 [W13] an upload that never answers is aborted after ten seconds, and the loop sends again', async () => {
    const picker = installPicker();
    installElements();
    const send = vi.spyOn(globalThis, 'fetch').mockImplementation(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        }),
    );
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10_000);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  it('S13 [W14] a 429 that answers after a stop and a restart does not pause the new loop', async () => {
    const picker = installPicker();
    installElements();
    let answerFirst!: (response: Response) => void;
    let calls = 0;
    const send = vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
      calls += 1;
      if (calls === 1) return new Promise<Response>((resolve) => { answerFirst = resolve; });
      return Promise.resolve(ok());
    });
    await startRunning(picker, 0);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await stopScreenStream();
    await startRunning(picker, 1);
    answerFirst(limited('30'));
    await vi.advanceTimersByTimeAsync(2000);
    expect(send).toHaveBeenCalledTimes(3);
    expect(useScreenStore.getState().active).toBe(true);
  });
});

describe('BF-973: a 429 is honoured', () => {
  built('S9 [W9, W10] a 429 with Retry-After: 3 posts nothing for three seconds, then the uploads resume', async () => {
    const picker = installPicker();
    installElements();
    const send = installFetch([() => limited('3'), ok]);
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });

  built('S10 [W9, W12] without a usable Retry-After the pause doubles from one second, and a 200 starts it over', async () => {
    const picker = installPicker();
    installElements();
    const send = installFetch([() => limited(), () => limited('soon'), ok, () => limited(), ok]);
    await startRunning(picker);
    const calls: number[] = [];
    for (let second = 1; second <= 6; second += 1) {
      await vi.advanceTimersByTimeAsync(1000);
      calls.push(send.mock.calls.length);
    }
    expect(calls).toEqual([1, 2, 2, 3, 4, 5]);
  });

  built('S11 [W9, W10, W11] a long Retry-After is capped at thirty seconds', async () => {
    const picker = installPicker();
    installElements();
    const send = installFetch([() => limited('3600'), ok]);
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(29_000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(2);
  });
});

describe('BF-973: what must not change', () => {
  it('C1 a single start opens one picker and one capture loop, and a stop releases both', async () => {
    const picker = installPicker();
    installElements();
    await startRunning(picker);
    expect(picker.getDisplayMedia).toHaveBeenCalledTimes(1);
    expect(getScreenStream()).toBe(picker.streams[0] as unknown as MediaStream);
    expect(vi.getTimerCount()).toBe(1);
    expect(useScreenStore.getState().active).toBe(true);
    await stopScreenStream();
    expect(picker.streams[0].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    expect(useScreenStore.getState().active).toBe(false);
  });

  it('C2 a start while the capture runs changes nothing', async () => {
    const picker = installPicker();
    installElements();
    await startRunning(picker);
    await startScreenStream({ fps: 1 });
    expect(picker.getDisplayMedia).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);
  });

  it('C3 a 200 counts a frame, the form carries the session id and source=screen, and a stop leaves no timer', async () => {
    const picker = installPicker();
    installElements();
    const send = installFetch([ok]);
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(1000);
    expect(send).toHaveBeenCalledTimes(1);
    expect(useScreenStore.getState().framesSent).toBe(1);
    const form = send.mock.calls[0][1]?.body as FormData;
    expect(form.get('session_id')).toBe(useScreenStore.getState().sessionId);
    expect(form.get('source')).toBe('screen');
    await stopScreenStream();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('C4 a 503 from the server stops the capture, as before', async () => {
    const picker = installPicker();
    installElements();
    installFetch([() => new Response('{"error":"screen_disabled"}', { status: 503 })]);
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(1000);
    expect(useScreenStore.getState().active).toBe(false);
    expect(picker.streams[0].released).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('C5 a 413 and a network error drop one frame each and keep the loop alive', async () => {
    const picker = installPicker();
    installElements();
    const send = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(async () => new Response('{}', { status: 413 }))
      .mockImplementationOnce(async () => { throw new TypeError('network'); })
      .mockImplementation(async () => ok());
    await startRunning(picker);
    await vi.advanceTimersByTimeAsync(3000);
    expect(send).toHaveBeenCalledTimes(3);
    expect(useScreenStore.getState().framesSent).toBe(1);
    expect(useScreenStore.getState().active).toBe(true);
    expect(vi.getTimerCount()).toBe(1);
  });
});
