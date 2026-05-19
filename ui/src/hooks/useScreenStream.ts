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
 */
import { useScreenStore } from '../store/useScreenStore';

const FRAME_ENDPOINT = '/api/perception/camera/frame';

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
}

async function _captureAndUpload() {
  if (!_video || !_canvas || !_sessionId) return;
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

  const form = new FormData();
  form.append('file', blob, 'screen.jpg');
  form.append('session_id', _sessionId);
  // AD-733-2: discriminator that routes to the screen subsystem on the
  // server side. AD-731 preserved — bytes still flow through SHA refs.
  form.append('source', 'screen');

  try {
    const resp = await fetch(FRAME_ENDPOINT, { method: 'POST', body: form });
    if (resp.status === 503) {
      const body = await resp.json().catch(() => ({}));
      useScreenStore.getState().setError(
        `screen disabled by server: ${body.error ?? 'unknown'}`,
      );
      await stopScreenStream();
      return;
    }
    if (resp.status === 200) {
      useScreenStore.getState().incrementFramesSent();
    }
    // 429 / 413: drop the frame; the next interval tick retries.
  } catch {
    // Network blip — keep the loop alive; the next frame will retry.
  }
}

export async function startScreenStream(opts?: {
  fps?: number;
  jpegQuality?: number;
  maxDimension?: number;
}): Promise<void> {
  if (_screenStream) return; // idempotent
  _fps = opts?.fps ?? 1;
  _jpegQuality = opts?.jpegQuality ?? 0.6;
  _maxDim = opts?.maxDimension ?? 512;
  useScreenStore.getState().setError(null);

  try {
    _screenStream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: _fps },
      audio: false,
    });
  } catch (err) {
    useScreenStore.getState().setError(`getDisplayMedia failed: ${String(err)}`);
    return;
  }

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
