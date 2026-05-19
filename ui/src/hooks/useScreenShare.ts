/* AD-744 — Interactive "Share screen to {agent}" one-shot capture.
 *
 * Distinct from AD-733-2 useScreenStream (ambient long-lived). This hook
 * captures ONE frame, stops the track immediately, and posts it with
 * ``source=screen``, ``force=true``, and ``agent_ids=<target>``. The
 * returned ``attachment_id`` is the SHA the caller appends to the next
 * DM turn's ``attachment_ids``.
 *
 * AD-731 invariant: the function never sees byte-level data after the
 * POST — only the SHA returned by the server.
 *
 * Tier-2 honest-degrade: returns ``null`` on any failure (browser
 * rejection, server 5xx, network blip). The caller surfaces a stroke
 * error banner; the composer text is preserved.
 */

const FRAME_ENDPOINT = '/api/perception/camera/frame';

export interface ShareFrameResult {
  attachment_id: string;
  mime: string;
  size_bytes: number;
}

function _generateSessionId(agentId: string): string {
  const ms = Date.now();
  return `share_${agentId}_${ms}`;
}

async function _grabFrameJpeg(stream: MediaStream): Promise<Blob | null> {
  // Use a hidden <video> + canvas — ImageCapture isn't supported on every
  // browser (Safari, Firefox subset). Canvas path is universal.
  const video = document.createElement('video');
  video.autoplay = true;
  video.playsInline = true;
  video.muted = true;
  video.srcObject = stream;
  try {
    await video.play();
  } catch {
    // Some browsers reject play() on hidden tabs — fall through and try
    // the canvas snapshot anyway; videoWidth check below catches failures.
  }

  // Tiny wait for the video element to populate dimensions.
  let attempts = 0;
  while ((video.videoWidth === 0 || video.videoHeight === 0) && attempts < 40) {
    await new Promise((r) => setTimeout(r, 25));
    attempts++;
  }
  if (video.videoWidth === 0 || video.videoHeight === 0) {
    return null;
  }

  const maxDim = 1024;
  const longest = Math.max(video.videoWidth, video.videoHeight);
  const scale = longest > maxDim ? maxDim / longest : 1;
  const w = Math.max(1, Math.round(video.videoWidth * scale));
  const h = Math.max(1, Math.round(video.videoHeight * scale));

  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0, w, h);

  return new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, 'image/jpeg', 0.7),
  );
}

export async function captureScreenShareFrame(opts: {
  agentId: string;
  agentCallsign?: string;
}): Promise<ShareFrameResult | null> {
  if (!opts || !opts.agentId) return null;

  let stream: MediaStream | null = null;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: 1 },
      audio: false,
    });
  } catch {
    // User dismissed the OS picker, or the API is gated.
    return null;
  }

  try {
    const blob = await _grabFrameJpeg(stream);
    if (!blob) return null;

    const form = new FormData();
    form.append('file', blob, 'share.jpg');
    form.append('session_id', _generateSessionId(opts.agentId));
    form.append('source', 'screen');
    form.append('force', '1');
    // AD-742c: comma-separated agent_ids. Single agent for v1; AD-744-1
    // forward marker covers share-to-many.
    form.append('agent_ids', opts.agentId);

    const resp = await fetch(FRAME_ENDPOINT, { method: 'POST', body: form });
    if (resp.status !== 200) {
      return null;
    }
    const data = await resp.json().catch(() => null);
    if (!data || !data.attachment_ref) return null;
    return {
      attachment_id: String(data.attachment_ref),
      mime: 'image/jpeg',
      size_bytes: blob.size,
    };
  } catch {
    return null;
  } finally {
    // One-shot — stop EVERY track immediately, no lingering capture loop.
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
    }
  }
}
