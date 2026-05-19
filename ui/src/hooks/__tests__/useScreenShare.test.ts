/**
 * AD-744: useScreenShare hook tests.
 *
 * One-shot capture distinct from AD-733-2 useScreenStream. Verifies
 * getDisplayMedia is invoked, the track is stopped immediately, the
 * multipart POST carries source=screen + force=1 + agent_ids, and that
 * Tier-2 honest-degrade returns null without throwing on failures.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { captureScreenShareFrame } from '../useScreenShare';

class FakeTrack {
  stopped = false;
  kind = 'video';
  readyState = 'live';
  stop() {
    this.stopped = true;
  }
}

class FakeMediaStream {
  tracks: FakeTrack[] = [new FakeTrack()];
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

function _installCanvasShim() {
  // The hook uses <video> + <canvas>; jsdom provides the elements but
  // not toBlob/getContext implementations. Stub them so the JPEG path
  // resolves deterministically.
  const proto = HTMLCanvasElement.prototype as unknown as {
    getContext: (kind: string) => unknown;
    toBlob: (cb: (b: Blob | null) => void, type?: string, q?: number) => void;
  };
  proto.getContext = () => ({ drawImage: () => undefined });
  proto.toBlob = (cb) => cb(new Blob(['x'], { type: 'image/jpeg' }));

  // Force the videoWidth/videoHeight getters so the dimension-wait loop
  // exits immediately.
  Object.defineProperty(HTMLVideoElement.prototype, 'videoWidth', {
    configurable: true,
    get() { return 320; },
  });
  Object.defineProperty(HTMLVideoElement.prototype, 'videoHeight', {
    configurable: true,
    get() { return 200; },
  });
  // jsdom's <video>.play() rejects; mute the rejection so the hook
  // falls through to the canvas snapshot path.
  HTMLVideoElement.prototype.play = vi.fn(async () => undefined);
}

beforeEach(() => {
  _installCanvasShim();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('captureScreenShareFrame (AD-744)', () => {
  it('invokes getDisplayMedia exactly once', async () => {
    const stream = new FakeMediaStream();
    const md = _installGetDisplayMediaMock(stream);
    vi.spyOn(global, 'fetch').mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({ ok: true, attachment_ref: 'sha-abc' }),
    } as unknown as Response);

    await captureScreenShareFrame({ agentId: 'e1' });

    expect(md.getDisplayMedia).toHaveBeenCalledTimes(1);
  });

  it('stops the screen track immediately after grab (one-shot, not stream)', async () => {
    const stream = new FakeMediaStream();
    _installGetDisplayMediaMock(stream);
    vi.spyOn(global, 'fetch').mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({ ok: true, attachment_ref: 'sha-xyz' }),
    } as unknown as Response);

    await captureScreenShareFrame({ agentId: 'e1' });

    expect(stream.tracks.every((t) => t.stopped)).toBe(true);
  });

  it('multipart POST contains source=screen, force=1, agent_ids=<id>', async () => {
    const stream = new FakeMediaStream();
    _installGetDisplayMediaMock(stream);
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({ ok: true, attachment_ref: 'sha-1' }),
    } as unknown as Response);

    await captureScreenShareFrame({ agentId: 'counselor' });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const args = fetchSpy.mock.calls[0];
    expect(args[0]).toBe('/api/perception/camera/frame');
    const init = args[1] as RequestInit;
    expect(init?.method).toBe('POST');
    const form = init?.body as FormData;
    expect(form.get('source')).toBe('screen');
    expect(form.get('force')).toBe('1');
    expect(form.get('agent_ids')).toBe('counselor');
    expect(String(form.get('session_id'))).toMatch(/^share_counselor_/);
  });

  it('returns the attachment_id payload on success', async () => {
    const stream = new FakeMediaStream();
    _installGetDisplayMediaMock(stream);
    vi.spyOn(global, 'fetch').mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({ ok: true, attachment_ref: 'sha-OK' }),
    } as unknown as Response);

    const out = await captureScreenShareFrame({ agentId: 'e1' });
    expect(out).not.toBeNull();
    expect(out!.attachment_id).toBe('sha-OK');
    expect(out!.mime).toBe('image/jpeg');
  });

  it('returns null when getDisplayMedia rejects (honest-degrade)', async () => {
    _installGetDisplayMediaMock(new Error('user denied'));
    const out = await captureScreenShareFrame({ agentId: 'e1' });
    expect(out).toBeNull();
  });

  it('returns null when server returns non-200 (honest-degrade)', async () => {
    const stream = new FakeMediaStream();
    _installGetDisplayMediaMock(stream);
    vi.spyOn(global, 'fetch').mockResolvedValue({
      status: 503,
      ok: false,
      json: async () => ({ error: 'explicit_share_disabled' }),
    } as unknown as Response);
    const out = await captureScreenShareFrame({ agentId: 'e1' });
    expect(out).toBeNull();
    // Even on 5xx, the screen track must be released.
    expect(stream.tracks.every((t) => t.stopped)).toBe(true);
  });
});
