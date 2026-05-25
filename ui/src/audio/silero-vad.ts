/**
 * AD-733c-7-5 — Browser-side Silero VAD wrapper.
 *
 * Dynamic-loads ``onnxruntime-web`` via the same indirect-string-variable
 * pattern as ``ui/src/audio/wakeWord.ts`` so first-paint never regresses
 * for Captains who never enable VAD. The runtime AND the ONNX model file
 * are both operator-pulled (``scripts/silero-vad-fetch.ps1``). When
 * either is absent the loader honest-degrades to ``null`` and the
 * voice-activity loop becomes a no-op (subsystem remains usable).
 *
 * Privacy invariant (AD-733c-7): no audio bytes leave the browser. This
 * module only consumes raw PCM frames and emits scores — it does not
 * persist, upload, or otherwise transmit the audio.
 */

/** Public shape returned by ``createVadSession``. */
export interface VadSession {
  /** Run inference on a single PCM frame; returns a 0..1 speech score. */
  score(buffer: Float32Array): Promise<number>;
  /** Release ONNX session resources. */
  destroy(): void;
}

/**
 * Internal seam — exported so vitest can stub the runtime import without
 * touching the public API.
 *
 * BF-307: previously used an indirect-string + ``@vite-ignore`` pattern
 * to keep ORT out of the bundle on the assumption that it was an
 * operator-pulled ``optionalDependency``. That assumption was wrong
 * (BF-306 promoted ``onnxruntime-web`` to a real dep) AND the indirection
 * made the dynamic import resolve to a bare specifier the browser
 * cannot resolve — ``_loadOnnxRuntime`` always returned ``null`` in
 * production. Use a regular dynamic import so Vite code-splits ORT into
 * its own chunk (lazy-loaded only when VAD is engaged, preserving
 * first-paint for Captains who never enable it).
 */
export async function _loadOnnxRuntime(): Promise<unknown | null> {
  try {
    const _mod = await import('onnxruntime-web');
    return _mod;
  } catch {
    return null;
  }
}

const MODEL_URL = '/data/silero-vad/silero_vad.onnx';

/**
 * Create a VAD inference session. Returns ``null`` when ``onnxruntime-web``
 * is absent OR the model file 404s — callers MUST treat ``null`` as honest
 * degrade (no VAD; the wake-word path remains the primary trigger).
 */
export async function createVadSession(): Promise<VadSession | null> {
  const ort = await _loadOnnxRuntime();
  if (!ort) return null;
  // The runtime is present; check the model file before committing to a
  // session. Avoid spamming the console on the (expected) 404 case when
  // the operator hasn't run ``silero-vad-fetch.ps1`` yet.
  let modelBytes: ArrayBuffer;
  try {
    const resp = await fetch(MODEL_URL);
    if (!resp.ok) return null;
    modelBytes = await resp.arrayBuffer();
  } catch {
    return null;
  }
  let session: any;
  try {
    const InferenceSession = (ort as any).InferenceSession;
    if (!InferenceSession || typeof InferenceSession.create !== 'function') return null;
    session = await InferenceSession.create(modelBytes);
  } catch {
    return null;
  }
  const Tensor = (ort as any).Tensor;
  return {
    async score(buffer: Float32Array): Promise<number> {
      try {
        const input = new Tensor('float32', buffer, [1, buffer.length]);
        // Silero exposes ``input`` / ``sr`` / ``state`` named tensors;
        // signature lives with the model. We only need the first output.
        const sr = new Tensor('int64', BigInt64Array.from([BigInt(16000)]), []);
        const stateData = new Float32Array(2 * 1 * 128);
        const state = new Tensor('float32', stateData, [2, 1, 128]);
        const feeds: Record<string, unknown> = { input, sr, state };
        const out = await session.run(feeds);
        // First key by convention — Silero returns ``output`` then
        // ``stateN``. Take the first scalar value as the speech score.
        const firstKey = Object.keys(out)[0];
        const data = out[firstKey]?.data;
        if (!data || typeof data[0] !== 'number') return 0;
        return Math.max(0, Math.min(1, data[0] as number));
      } catch {
        return 0;
      }
    },
    destroy(): void {
      try {
        session?.release?.();
      } catch {
        // Tier-2: release errors are non-actionable; swallow so unmount
        // does not throw during teardown.
      }
    },
  };
}
