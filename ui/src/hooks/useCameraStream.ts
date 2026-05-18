/* AD-733 — Camera capture + frame upload hook.
 *
 * Owns the MediaStream + capture interval. Honors:
 *   - getUserMedia consent (browser-native).
 *   - visibilitychange → hidden: pause loop, keep stream alive.
 *   - beforeunload: stop unconditionally.
 *   - 503 from server: stop + surface error.
 *   - 429 from server: pass-through (token bucket throttles naturally).
 *   - 413 from server: log + continue (current frame dropped).
 *
 * AD-731: frames POSTed as multipart JPEG; server returns a SHA — client
 * never sees nor cares about the byte-level address.
 */
import { useCameraStore } from '../store/useCameraStore';

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
}

async function _captureAndUpload() {
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

  try {
    const resp = await fetch(FRAME_ENDPOINT, { method: 'POST', body: form });
    if (resp.status === 503) {
      const body = await resp.json().catch(() => ({}));
      useCameraStore.getState().setError(`camera disabled by server: ${body.error ?? 'unknown'}`);
      await stopCameraStream();
      return;
    }
    if (resp.status === 200) {
      useCameraStore.getState().incrementFramesSent();
    }
    // 429 / 413: drop the frame, the next interval tick tries again.
  } catch {
    // Network blip — keep the loop alive; the next frame will retry.
  }
}

export async function startCameraStream(opts?: {
  fps?: number;
  jpegQuality?: number;
  maxDimension?: number;
}): Promise<void> {
  if (_stream) return; // idempotent
  _fps = opts?.fps ?? 1;
  _jpegQuality = opts?.jpegQuality ?? 0.6;
  _maxDim = opts?.maxDimension ?? 512;
  useCameraStore.getState().setFps(_fps);
  useCameraStore.getState().setError(null);

  try {
    _stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    });
  } catch (err) {
    useCameraStore.getState().setError(`getUserMedia failed: ${String(err)}`);
    return;
  }

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
