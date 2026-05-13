/** AD-721b-2: Browser-side real-audio capture for server-side lip-sync.
 *
 *  Best-effort: most browsers today do NOT expose SpeechSynthesis output
 *  through Web Audio (see ``speechAmplitude.ts:1-7``), so this module is
 *  written to fail gracefully. Every entry point returns ``null`` / empty
 *  on any failure; the consumer (``useLipSyncCapture``) treats that as the
 *  signal to fall through to the AD-721b v1 heuristic path.
 *
 *  Wire shape: AD-731 invariant — captured bytes upload via the existing
 *  multipart attachment endpoint and produce a sha256 hash; the lipsync
 *  request body carries only the hash, never inline base64.
 *
 *  Transitional: this module becomes dead code if/when a server-streamed
 *  TTS path (forward marker AD-721b-2.3) lands — then the server is the
 *  source of audio bytes and no browser capture is needed.
 */

/** One viseme frame returned by ``POST /api/avatars/lipsync``.
 *  Mirrors the server's ``VisemeFrame`` dataclass shape. */
export interface LipSyncFrame {
  time: number;        // seconds since utterance start
  duration: number;    // seconds
  viseme: string;      // Oculus 15-set key
}

/** Server response shape for ``POST /api/avatars/lipsync``. */
export interface LipSyncResponse {
  backend: 'rhubarb' | 'heuristic' | 'disabled';
  frames: LipSyncFrame[];
}

/** Browser feature-detection result. ``ok: false`` means capture is
 *  impossible on this engine; the consumer falls through to heuristic. */
export interface CaptureCapability {
  ok: boolean;
  reason?: string;
}

/** Detect whether the browser exposes the APIs needed for capture.
 *  Pure synchronous check — safe to call on every render. */
export function detectCaptureCapability(): CaptureCapability {
  if (typeof window === 'undefined') {
    return { ok: false, reason: 'no-window' };
  }
  // AudioContext: required for MediaStreamDestination.
  const Ctor = (window as any).AudioContext || (window as any).webkitAudioContext;
  if (typeof Ctor !== 'function') {
    return { ok: false, reason: 'no-audiocontext' };
  }
  // MediaRecorder: required to encode the captured stream.
  if (typeof (window as any).MediaRecorder !== 'function') {
    return { ok: false, reason: 'no-mediarecorder' };
  }
  // SpeechSynthesis routability is not feature-detectable without an
  // utterance in flight. ``captureUtteranceAudio`` returns null when
  // the actual capture produces zero bytes — that is the runtime signal
  // for "this engine doesn't route SpeechSynthesis through Web Audio".
  return { ok: true };
}

/** Attempt to capture the audio of a SpeechSynthesisUtterance via Web Audio
 *  + MediaRecorder. Returns the captured Blob on success, ``null`` on any
 *  failure (capability missing, zero bytes captured, recorder error).
 *
 *  Caller is responsible for invoking this BEFORE ``speechSynthesis.speak``
 *  on engines that route SpeechSynthesis through Web Audio. The returned
 *  Promise resolves when the utterance ends.
 *
 *  Tier-2 log-and-degrade: NEVER throws. ``null`` is the only failure signal.
 */
export async function captureUtteranceAudio(
  utterance: SpeechSynthesisUtterance,
  opts?: { mimeType?: string; maxDurationMs?: number },
): Promise<Blob | null> {
  const cap = detectCaptureCapability();
  if (!cap.ok) {
    // eslint-disable-next-line no-console
    console.info(`[AD-721b-2] capture unavailable: ${cap.reason}`);
    return null;
  }
  const Ctor = (window as any).AudioContext || (window as any).webkitAudioContext;
  let ctx: AudioContext | null = null;
  let recorder: MediaRecorder | null = null;
  try {
    ctx = new Ctor();
    const dest = (ctx as AudioContext).createMediaStreamDestination();
    const mimeType = opts?.mimeType ?? 'audio/webm';
    recorder = new MediaRecorder(dest.stream, { mimeType });
    const chunks: BlobPart[] = [];
    recorder.ondataavailable = (e: BlobEvent) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };
    recorder.start();
    // Wait for utterance to end (or maxDurationMs safety bound).
    const maxMs = opts?.maxDurationMs ?? 30_000;
    const ended = new Promise<void>((resolve) => {
      const onEnd = () => { utterance.removeEventListener('end', onEnd); resolve(); };
      utterance.addEventListener('end', onEnd);
      // Safety bound — never wait more than maxMs even if onend never fires.
      setTimeout(() => { utterance.removeEventListener('end', onEnd); resolve(); }, maxMs);
    });
    await ended;
    // Stop recording and wait for the final ondataavailable.
    const stopped = new Promise<void>((resolve) => {
      const onStop = () => { recorder?.removeEventListener('stop', onStop); resolve(); };
      recorder?.addEventListener('stop', onStop);
      try { recorder?.stop(); } catch { resolve(); }
    });
    await stopped;
    if (chunks.length === 0) {
      // eslint-disable-next-line no-console
      console.info('[AD-721b-2] capture produced 0 bytes; SpeechSynthesis not routed');
      return null;
    }
    return new Blob(chunks, { type: mimeType });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn('[AD-721b-2] captureUtteranceAudio failed', err);
    return null;
  } finally {
    try { ctx?.close(); } catch { /* ignore */ }
  }
}

/** Upload the captured Blob and request a viseme schedule from the server.
 *  Returns the parsed response or ``null`` on any failure. NEVER throws.
 *
 *  Honors AD-731: bytes upload first via the existing multipart endpoint,
 *  the lipsync request body carries only the resulting sha256.
 */
export async function uploadAudioForLipSync(
  blob: Blob,
  opts?: { fetchImpl?: typeof fetch },
): Promise<LipSyncResponse | null> {
  const f = opts?.fetchImpl ?? fetch;
  try {
    // Step 1: multipart upload (AD-720a path; routers/chat.py:757).
    const form = new FormData();
    // Filename hint for server-side ext_to_mime resolver (AD-720a).
    const fname = blob.type === 'audio/webm' ? 'capture.webm' : 'capture.wav';
    form.append('file', blob, fname);
    const uploadResp = await f('/api/chat/attachments/multipart', {
      method: 'POST',
      body: form,
    });
    if (!uploadResp.ok) {
      // eslint-disable-next-line no-console
      console.warn(`[AD-721b-2] upload failed status=${uploadResp.status}`);
      return null;
    }
    const uploadJson = await uploadResp.json();
    const attachmentId = uploadJson?.attachment_id;
    if (typeof attachmentId !== 'string' || attachmentId.length !== 64) {
      // eslint-disable-next-line no-console
      console.warn('[AD-721b-2] upload returned invalid attachment_id');
      return null;
    }
    // Step 2: lipsync request — refs only, no inline bytes (AD-731 invariant).
    const lipsyncResp = await f('/api/avatars/lipsync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ attachment_id: attachmentId }),
    });
    if (!lipsyncResp.ok) {
      // eslint-disable-next-line no-console
      console.warn(`[AD-721b-2] lipsync failed status=${lipsyncResp.status}`);
      return null;
    }
    const data = (await lipsyncResp.json()) as LipSyncResponse;
    if (!data || !Array.isArray(data.frames)) return null;
    return data;
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn('[AD-721b-2] uploadAudioForLipSync failed', err);
    return null;
  }
}
