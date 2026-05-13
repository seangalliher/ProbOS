// AD-721b-2: lipSyncCapture pure-module tests.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
  detectCaptureCapability,
  uploadAudioForLipSync,
} from '../lipSyncCapture';

describe('detectCaptureCapability', () => {
  let originalAudioContext: unknown;
  let originalWebkitAudioContext: unknown;
  let originalMediaRecorder: unknown;

  beforeEach(() => {
    originalAudioContext = (window as any).AudioContext;
    originalWebkitAudioContext = (window as any).webkitAudioContext;
    originalMediaRecorder = (window as any).MediaRecorder;
  });

  afterEach(() => {
    (window as any).AudioContext = originalAudioContext;
    (window as any).webkitAudioContext = originalWebkitAudioContext;
    (window as any).MediaRecorder = originalMediaRecorder;
  });

  it('returns ok=false when AudioContext is missing', () => {
    (window as any).AudioContext = undefined;
    (window as any).webkitAudioContext = undefined;
    (window as any).MediaRecorder = function () {};
    const result = detectCaptureCapability();
    expect(result.ok).toBe(false);
    expect(result.reason).toBe('no-audiocontext');
  });

  it('returns ok=false when MediaRecorder is missing', () => {
    (window as any).AudioContext = function () {};
    (window as any).MediaRecorder = undefined;
    const result = detectCaptureCapability();
    expect(result.ok).toBe(false);
    expect(result.reason).toBe('no-mediarecorder');
  });
});

describe('uploadAudioForLipSync', () => {
  it('uploads via multipart then POSTs lipsync ref (AD-731 invariant)', async () => {
    const sha = 'a'.repeat(64);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ attachment_id: sha }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          backend: 'rhubarb',
          frames: [{ time: 0, duration: 0.1, viseme: 'aa' }],
        }),
      });

    const blob = new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/webm' });
    const result = await uploadAudioForLipSync(blob, { fetchImpl: fetchMock as any });

    expect(result).not.toBeNull();
    expect(result!.backend).toBe('rhubarb');
    expect(result!.frames).toHaveLength(1);

    // Two fetch calls in order: multipart upload, then JSON lipsync request.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [firstUrl, firstInit] = fetchMock.mock.calls[0];
    expect(firstUrl).toBe('/api/chat/attachments/multipart');
    expect(firstInit.method).toBe('POST');
    // FormData body — bytes via multipart, not inline JSON.
    expect(firstInit.body).toBeInstanceOf(FormData);

    const [secondUrl, secondInit] = fetchMock.mock.calls[1];
    expect(secondUrl).toBe('/api/avatars/lipsync');
    expect(secondInit.method).toBe('POST');
    // CRITICAL: AD-731 invariant — body is JSON with the ref, NOT a base64 blob.
    const parsed = JSON.parse(secondInit.body as string);
    expect(parsed).toEqual({ attachment_id: sha });
    expect(parsed).not.toHaveProperty('audio_bytes');
    expect(parsed).not.toHaveProperty('blob');
    expect(parsed).not.toHaveProperty('base64');
  });

  it('returns null on upload failure and never POSTs to lipsync', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({}),
    });

    const blob = new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/webm' });
    const result = await uploadAudioForLipSync(blob, { fetchImpl: fetchMock as any });

    expect(result).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    // The lipsync endpoint MUST NOT have been called.
    expect(fetchMock.mock.calls[0][0]).toBe('/api/chat/attachments/multipart');
  });
});
