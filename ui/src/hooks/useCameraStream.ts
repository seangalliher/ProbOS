/* AD-733 — Camera capture + frame upload hook.
 *
 * Owns the MediaStream + capture interval. Honors:
 *   - getUserMedia consent (browser-native).
 *   - visibilitychange → hidden: pause loop, keep stream alive.
 *   - beforeunload: stop unconditionally.
 *   - 503 from server: stop + surface error.
 *   - 429 from server: honour Retry-After, else back off 1 s, 2 s, 4 s ... up to 30 s;
 *     ticks inside the pause return without capturing (BF-933).
 *   - a start that overlaps a pending start shares it; a stop cancels a pending start (BF-933).
 *   - 413 from server: log + continue (current frame dropped).
 *
 * AD-731: frames POSTed as multipart JPEG; server returns a SHA — client
 * never sees nor cares about the byte-level address.
 */
import { useCameraStore } from '../store/useCameraStore';
import { useCameraMultiplexerStore } from '../store/useCameraMultiplexerStore';

const FRAME_ENDPOINT = '/api/perception/camera/frame';

let _stream: MediaStream | null = null;
let _intervalId: number | null = null;
let _video: HTMLVideoElement | null = null;
let _canvas: HTMLCanvasElement | null = null;
let _sessionId: string | null = null;
let _fps = 1;
let _jpegQuality = 0.6;
let _maxDim = 512;
// BF-302: when set, the next capture is sent with force=1 so the consumer
// bypasses the supervisor's throttle + novelty gate. One-shot flag.
let _forceNext = false;
// AD-742c-6: optional device_id this stream is bound to. When set, the
// capture loop derives agent_ids from the multiplexer bindings that match
// this device. ``null`` = legacy single-stream behavior (zero-arg call).
let _activeDeviceId: string | null = null;
// BF-933: the loop's guards. A start is one shared promise; every stop bumps the epoch, which is how a start that
// is still waiting on the camera or the video learns it was cancelled; an upload in flight holds the next tick
// off; a 429 holds it off until _resumeAtMs.
const FRAME_UPLOAD_TIMEOUT_MS = 10_000;
const BACKOFF_BASE_MS = 1_000;
const RETRY_AFTER_MAX_MS = 30_000;
let _startInFlight: Promise<void> | null = null;
let _epoch = 0;
let _uploading = false;
let _resumeAtMs = 0;
let _rateLimited = 0;
// AD-742c-6: future-proofing for true multi-stream capture. v1 keeps the
// single-video / single-canvas loop; the map currently holds at most one
// stream keyed by deviceId (or "default" when no deviceId is bound).
const _streams: Map<string, MediaStream> = new Map();

/** BF-302: expose the live MediaStream so the preview panel can mirror it. */
export function getCameraStream(): MediaStream | null {
  return _stream;
}

/** BF-302: arm the next capture to bypass supervisor (operator preview). */
export function forceNextFrame(): void {
  _forceNext = true;
}

function _generateSessionId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return (crypto as any).randomUUID();
  }
  return `cam-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function _stopTracks() {
  if (_stream) {
    _stream.getTracks().forEach((t) => t.stop());
    _stream = null;
  }
  if (_intervalId !== null) {
    clearInterval(_intervalId);
    _intervalId = null;
  }
  _video = null;
  _canvas = null;
  _sessionId = null;
  _activeDeviceId = null;
  _streams.clear();
  // BF-933: every stop is also a cancel. A start still waiting on the camera sees a new epoch and releases what it
  // was given; a call after a stop is not held to the cancelled start; the old call's upload guard and 429 pause
  // do not outlive it. _testReset goes through here, so a test resets all of it.
  _epoch += 1;
  _startInFlight = null;
  _uploading = false;
  _resumeAtMs = 0;
  _rateLimited = 0;
}

/**
 * AD-742c-6: compute the ``agent_ids`` form-field value for the current
 * stream from the multiplexer bindings. When ``_activeDeviceId`` is set,
 * only agents bound to THAT device are included; when null (legacy
 * single-stream call), all currently-bound agents pile onto the stream.
 * Returns an empty string when no bindings apply — the legacy fan-out
 * path on the backend is preserved.
 */
function _computeAgentIds(): string {
  let bindings: Record<string, string> = {};
  try {
    bindings = useCameraMultiplexerStore.getState().bindings ?? {};
  } catch {
    // Tier-2: store unavailable in some test envs — degrade to no field.
    return '';
  }
  const agentIds: string[] = [];
  for (const [agentId, deviceId] of Object.entries(bindings)) {
    if (!deviceId) continue;
    if (_activeDeviceId === null || deviceId === _activeDeviceId) {
      agentIds.push(agentId);
    }
  }
  return agentIds.join(',');
}

/** BF-933: RFC 9110 Retry-After is delta-seconds or an HTTP-date; anything else is no advice. */
function _parseRetryAfterMs(raw: string | null): number | null {
  if (raw === null) return null;
  const value = raw.trim();
  if (/^\d+$/.test(value)) return Number(value) * 1000;
  const at = Date.parse(value);
  return Number.isNaN(at) ? null : Math.max(0, at - Date.now());
}

/** BF-933: one capture-and-upload at a time. A tick that finds the previous upload still in flight, or the loop
 *  paused by a 429, returns at once. The flag belongs to the epoch that set it: an upload that settles after a
 *  stop (and perhaps a new start) does not release a newer loop's guard. */
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
  // BF-933: the epoch this upload belongs to. Its answer is acted on only while that epoch is the current one.
  const epoch = _epoch;
  if (!_video || !_canvas || !_sessionId) return;
  if (_video.videoWidth === 0 || _video.videoHeight === 0) return; // not ready yet
  if (document.visibilityState === 'hidden') return; // paused while tab is hidden

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

  const form = new FormData();
  form.append('file', blob, 'frame.jpg');
  form.append('session_id', _sessionId);
  if (_forceNext) {
    form.append('force', '1');
    _forceNext = false;
  }
  // AD-742c-6: thread agent_ids from the multiplexer bindings. AD-731
  // invariant preserved — agent_ids is a STRING list, never bytes.
  const agentIds = _computeAgentIds();
  if (agentIds) {
    form.append('agent_ids', agentIds);
  }

  // BF-933: bound the upload, so a request that never answers cannot hold the in-flight guard for good.
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), FRAME_UPLOAD_TIMEOUT_MS);
  try {
    const resp = await fetch(FRAME_ENDPOINT, { method: 'POST', body: form, signal: controller.signal });
    if (epoch !== _epoch) return; // a stop came during the upload: the answer is not for the loop that runs now
    if (resp.status === 503) {
      const body = await resp.json().catch(() => ({}));
      if (epoch !== _epoch) return; // a stop came while the body was read: the same
      useCameraStore.getState().setError(`camera disabled by server: ${body.error ?? 'unknown'}`);
      await stopCameraStream();
      return;
    }
    if (resp.status === 200) {
      useCameraStore.getState().incrementFramesSent();
      _rateLimited = 0; // a 200 ends the doubling
    }
    if (resp.status === 429) {
      // BF-933: the server's token bucket said slow down. Honour Retry-After; without a usable one back off
      // 1 s, 2 s, 4 s ... The interval keeps its period; ticks inside the pause return without capturing.
      _rateLimited += 1;
      const advised = _parseRetryAfterMs(resp.headers.get('Retry-After'));
      const waitMs = advised ?? BACKOFF_BASE_MS * 2 ** (_rateLimited - 1);
      _resumeAtMs = Date.now() + Math.min(waitMs, RETRY_AFTER_MAX_MS);
    }
    // 413: drop the frame, the next interval tick tries again.
  } catch {
    // Network blip — keep the loop alive; the next frame will retry.
  } finally {
    // BF-933: the deadline covers the answer's body too (a 503 whose body never arrives is cut by it).
    window.clearTimeout(timeout);
  }
}

export async function startCameraStream(opts?: {
  fps?: number;
  jpegQuality?: number;
  maxDimension?: number;
  // AD-742c-6: optional device constraint. Zero-arg (or omitted) preserves
  // legacy single-stream behavior bit-for-bit; supplying a deviceId routes
  // the agent_ids form field per binding (see ``_computeAgentIds``).
  deviceId?: string;
}): Promise<void> {
  // BF-933: concurrent callers share the one pending start (the guard below only sees a camera that has already
  // been granted); a call after a stop starts afresh, because the stop dropped the pending start.
  if (_startInFlight) return _startInFlight;
  if (_stream) return; // idempotent
  const attempt: Promise<void> = _startCamera(opts).finally(() => {
    if (_startInFlight === attempt) _startInFlight = null;
  });
  _startInFlight = attempt;
  return attempt;
}

async function _startCamera(opts: Parameters<typeof startCameraStream>[0]): Promise<void> {
  const epoch = _epoch;
  _fps = opts?.fps ?? 1;
  _jpegQuality = opts?.jpegQuality ?? 0.6;
  _maxDim = opts?.maxDimension ?? 512;
  _activeDeviceId = opts?.deviceId ?? null;
  useCameraStore.getState().setFps(_fps);
  useCameraStore.getState().setError(null);

  let stream: MediaStream;
  try {
    const videoConstraints: MediaTrackConstraints = {
      width: { ideal: 640 },
      height: { ideal: 480 },
    };
    if (_activeDeviceId) {
      videoConstraints.deviceId = { exact: _activeDeviceId } as ConstrainDOMString;
    }
    stream = await navigator.mediaDevices.getUserMedia({
      video: videoConstraints,
      audio: false,
    });
  } catch (err) {
    // BF-933: a start that a stop has cancelled reports nothing and touches nothing of a newer start.
    if (epoch === _epoch) {
      useCameraStore.getState().setError(`getUserMedia failed: ${String(err)}`);
      _activeDeviceId = null;
    }
    return;
  }
  if (epoch !== _epoch) {
    // BF-933: a stop arrived while the camera was being opened; release what was granted and start no loop.
    stream.getTracks().forEach((t) => t.stop());
    return;
  }
  _stream = stream;
  // AD-742c-6: register in the multiplex map alongside the legacy _stream
  // singleton. v1 only ever has one entry; the map is plumbing for the
  // forward-marker true-multi-stream variant.
  _streams.set(_activeDeviceId ?? 'default', _stream);

  _sessionId = _generateSessionId();
  _video = document.createElement('video');
  _video.autoplay = true;
  _video.playsInline = true;
  _video.muted = true;
  _video.srcObject = _stream;
  try {
    await _video.play();
  } catch {
    /* play promise sometimes rejects on hidden tabs; the capture loop will skip until visible */
  }
  // BF-933: a stop that arrived during play() has already released the stream; do not start a loop.
  if (epoch !== _epoch) return;
  _canvas = document.createElement('canvas');

  useCameraStore.getState().setActive(true, _sessionId);

  const periodMs = Math.max(100, Math.round(1000 / Math.max(1, _fps)));
  _intervalId = window.setInterval(() => {
    void _captureAndUpload();
  }, periodMs);
}

export async function stopCameraStream(): Promise<void> {
  _stopTracks();
  useCameraStore.getState().reset();
}

export function _testReset(): void {
  _stopTracks();
  useCameraStore.getState().reset();
}
