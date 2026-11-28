/* AD-733-2 — Screen capture + frame upload hook.
 *
 * Mirror of useCameraStream with two key differences:
 *   1. ``getDisplayMedia`` instead of ``getUserMedia`` — surfaces the OS-
 *      native monitor/window picker for free; no enumeration needed.
 *   2. ``track.onended`` auto-stops the stream when the operator clicks
 *      the browser's "Stop sharing" pill.
 *
 * Module-singleton state is separate from useCameraStream's _stream so
 * camera + screen run independently.
 *
 * AD-731 invariant: frames POSTed as multipart JPEG; server returns a
 * SHA — client never holds nor cares about the byte-level address.
 *
 * AD-733-2 wire field: ``source=screen`` discriminates the upload from
 * a camera frame so the server can apply the per-source rate bucket and
 * gate.
 *
 * BF-973: the loop carries useCameraStream's BF-933 guards. Overlapping starts share one pending start, so the
 * picker opens once; a stop cancels a pending start, and a capture picked after the stop has its tracks stopped as
 * soon as the picker returns it; a frame whose loop was stopped during its encode is not posted; a tick returns
 * while an upload is in flight (each upload is aborted after 10 s); a 429 pauses the uploads for its Retry-After,
 * else 1 s, 2 s, 4 s ... up to 30 s; a 413 drops the frame.
 */
import { useScreenStore } from '../store/useScreenStore';

const FRAME_ENDPOINT = '/api/perception/camera/frame';
// BF-973: the loop's guards. A start is one shared promise; every stop advances the epoch, which is how a start
// still waiting on the picker or on play(), and a frame still in its encode or its upload, learns that its loop was
// stopped; an upload in flight holds the next tick off; a 429 holds it off until _resumeAtMs.
const FRAME_UPLOAD_TIMEOUT_MS = 10_000;
const BACKOFF_BASE_MS = 1_000;
const RETRY_AFTER_MAX_MS = 30_000;
let _startInFlight: Promise<void> | null = null;
let _epoch = 0;
let _uploading = false;
let _resumeAtMs = 0;
let _rateLimited = 0;

let _screenStream: MediaStream | null = null;
let _intervalId: number | null = null;
let _video: HTMLVideoElement | null = null;
let _canvas: HTMLCanvasElement | null = null;
let _sessionId: string | null = null;
let _fps = 1;
let _jpegQuality = 0.6;
let _maxDim = 512;

/** Expose the live screen MediaStream so future preview surfaces can mirror. */
export function getScreenStream(): MediaStream | null {
  return _screenStream;
}

function _generateSessionId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return (crypto as { randomUUID: () => string }).randomUUID();
  }
  return `scr-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function _stopTracks() {
  if (_screenStream) {
    _screenStream.getTracks().forEach((t) => t.stop());
    _screenStream = null;
  }
  if (_intervalId !== null) {
    clearInterval(_intervalId);
    _intervalId = null;
  }
  _video = null;
  _canvas = null;
  _sessionId = null;
  // BF-973: every stop is also a cancel. A pending start sees a new epoch and releases any capture it is given; a
  // frame in its encode posts nothing, and an answer that arrives later is not acted on; the old loop's upload guard
  // and 429 pause do not outlive it. _testReset goes through here, so a test resets all of it.
  _epoch += 1;
  _startInFlight = null; // a call after a stop is not held to the cancelled start
  _uploading = false;
  _resumeAtMs = 0;
  _rateLimited = 0;
}

/** BF-973: RFC 9110 Retry-After is delta-seconds or an HTTP-date; anything else is no advice (as useCameraStream). */
function _parseRetryAfterMs(raw: string | null): number | null {
  if (raw === null) return null;
  const value = raw.trim();
  if (/^\d+$/.test(value)) return Number(value) * 1000;
  const at = Date.parse(value);
  return Number.isNaN(at) ? null : Math.max(0, at - Date.now());
}

/** BF-973: one capture-and-upload at a time. A tick that finds the previous upload still in flight, or the loop
 *  paused by a 429, returns at once. The flag belongs to the epoch that set it: an upload that settles after a stop
 *  (and perhaps a new start) does not release a newer loop's guard. */
async function _captureAndUpload() {
  if (_uploading || Date.now() < _resumeAtMs) return;
  const epoch = _epoch;
  _uploading = true;
  try {
    await _captureAndUploadFrame();
  } finally {
    if (epoch === _epoch) _uploading = false;
  }
}

async function _captureAndUploadFrame() {
  // BF-973: the epoch and the session id this frame belongs to, both read before the encode.
  const epoch = _epoch;
  const sessionId = _sessionId;
  if (!_video || !_canvas || !sessionId) return;
  if (_video.videoWidth === 0 || _video.videoHeight === 0) return;
  if (document.visibilityState === 'hidden') return;

  const srcW = _video.videoWidth;
  const srcH = _video.videoHeight;
  const longestEdge = Math.max(srcW, srcH);
  const scale = longestEdge > _maxDim ? _maxDim / longestEdge : 1;
  const w = Math.max(1, Math.round(srcW * scale));
  const h = Math.max(1, Math.round(srcH * scale));
  _canvas.width = w;
  _canvas.height = h;

  const ctx = _canvas.getContext('2d');
  if (!ctx) return;
  ctx.drawImage(_video, 0, 0, w, h);

  const blob: Blob | null = await new Promise((resolve) =>
    _canvas!.toBlob(resolve, 'image/jpeg', _jpegQuality),
  );
  if (!blob) return;
  if (epoch !== _epoch) return; // a stop came during the encode: post nothing

  const form = new FormData();
  form.append('file', blob, 'screen.jpg');
  form.append('session_id', sessionId);
  // AD-733-2: discriminator that routes to the screen subsystem on the
  // server side. AD-731 preserved — bytes still flow through SHA refs.
  form.append('source', 'screen');

  // BF-973: bound the upload, so a request that never answers cannot hold the in-flight guard for good.
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), FRAME_UPLOAD_TIMEOUT_MS);
  try {
    const resp = await fetch(FRAME_ENDPOINT, { method: 'POST', body: form, signal: controller.signal });
    if (epoch !== _epoch) return; // a stop came during the upload: its answer is not for the loop that runs now
    if (resp.status === 503) {
      const body = await resp.json().catch(() => ({}));
      if (epoch !== _epoch) return; // a stop came while the body was read: the same
      useScreenStore.getState().setError(
        `screen disabled by server: ${body.error ?? 'unknown'}`,
      );
      await stopScreenStream();
      return;
    }
    if (resp.status === 200) {
      useScreenStore.getState().incrementFramesSent();
      _rateLimited = 0; // a 200 ends the doubling
    }
    if (resp.status === 429) {
      // BF-973: the server's rate bucket said slow down. Honour Retry-After; without a usable one back off 1 s, 2 s,
      // 4 s ... The interval keeps its period; ticks inside the pause return without capturing.
      _rateLimited += 1;
      const advised = _parseRetryAfterMs(resp.headers.get('Retry-After'));
      const waitMs = advised ?? BACKOFF_BASE_MS * 2 ** (_rateLimited - 1);
      _resumeAtMs = Date.now() + Math.min(waitMs, RETRY_AFTER_MAX_MS);
    }
    // 413: drop the frame; the next interval tick tries again.
  } catch {
    // Network blip — keep the loop alive; the next frame will retry.
  } finally {
    window.clearTimeout(timeout); // the upload deadline, on every way out of the try
  }
}

export async function startScreenStream(opts?: {
  fps?: number;
  jpegQuality?: number;
  maxDimension?: number;
}): Promise<void> {
  // BF-973: concurrent callers share the one pending start, so the picker opens once (the guard below only sees a
  // capture already granted); a call after a stop starts afresh, because the stop dropped the pending start.
  if (_startInFlight) return _startInFlight;
  if (_screenStream) return; // idempotent
  const attempt: Promise<void> = _startScreen(opts).finally(() => {
    if (_startInFlight === attempt) _startInFlight = null;
  });
  _startInFlight = attempt;
  return attempt;
}

async function _startScreen(opts: Parameters<typeof startScreenStream>[0]): Promise<void> {
  const epoch = _epoch;
  _fps = opts?.fps ?? 1;
  _jpegQuality = opts?.jpegQuality ?? 0.6;
  _maxDim = opts?.maxDimension ?? 512;
  useScreenStore.getState().setError(null);

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: _fps },
      audio: false,
    });
  } catch (err) {
    // BF-973: a dismissed or failed picker reports its error, unless a stop cancelled this start while it was open.
    if (epoch === _epoch) useScreenStore.getState().setError(`getDisplayMedia failed: ${String(err)}`);
    return;
  }
  if (epoch !== _epoch) { // a stop came while the picker was open: release what was picked, start no loop
    stream.getTracks().forEach((t) => t.stop());
    return;
  }
  _screenStream = stream;

  // Auto-stop when the operator clicks the browser's "Stop sharing" pill.
  // Every track gets the handler — multi-track screens (e.g. cursor track)
  // all signal end-of-share via the video track.
  _screenStream.getTracks().forEach((track) => {
    track.onended = () => {
      void stopScreenStream();
    };
  });

  _sessionId = _generateSessionId();
  _video = document.createElement('video');
  _video.autoplay = true;
  _video.playsInline = true;
  _video.muted = true;
  _video.srcObject = _screenStream;
  try {
    await _video.play();
  } catch {
    /* play promise may reject on hidden tabs; capture loop skips until visible */
  }
  if (epoch !== _epoch) return; // a stop came during play(): the stream is already released, start no loop
  _canvas = document.createElement('canvas');

  useScreenStore.getState().setActive(true, _sessionId);

  const periodMs = Math.max(100, Math.round(1000 / Math.max(1, _fps)));
  _intervalId = window.setInterval(() => {
    void _captureAndUpload();
  }, periodMs);
}

export async function stopScreenStream(): Promise<void> {
  _stopTracks();
  useScreenStore.getState().reset();
}

export function _testReset(): void {
  _stopTracks();
  useScreenStore.getState().reset();
}
