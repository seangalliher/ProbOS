/**
 * AD-721b-3 — Browser-side whisper.cpp WASM loader.
 *
 * Lazy-loads the whisper.cpp WASM glue + tiny.en GGML model. The runtime
 * AND the model are both operator-pulled (``scripts/whisper-tiny-en-fetch.ps1``).
 * When any artifact is absent the loader honest-degrades to ``null`` and
 * the offline STT path (AD-705a) falls through to the existing browser-
 * native ``SpeechRecognition`` (no regression for Captains who never run
 * the fetch script).
 *
 * Architectural notes:
 *   - whisper.cpp WASM ships as UMD-style glue (NOT ESM). The glue
 *     registers a global ``Module`` factory when its ``<script>`` tag
 *     evaluates — see upstream ``examples/whisper.wasm/main.js``. We
 *     inject a ``<script>`` element pointed at the operator-pulled
 *     ``/data/whisper/whisper.js`` rather than ``await import()``-ing it
 *     like the ESM silero-vad runtime.
 *   - First paint MUST never load this module. Consumers call
 *     ``loadWhisperModel()`` only when STT is armed (AD-705a).
 *   - AD-721b-3 is the foundation; the only consumer in this AD is the
 *     vitest harness. AD-705a wires it to the conversation surface.
 *
 * Privacy invariant (AD-733c-7 extended): no audio bytes leave the
 * browser. ``transcribeBuffer`` consumes a Float32Array PCM tap and
 * returns a transcript string; nothing is persisted, uploaded, or
 * transmitted from this module.
 */

/** Public handle returned by ``loadWhisperModel``. */
export interface WhisperHandle {
  /** Transcribe a Float32 PCM buffer; returns the recognized text. */
  transcribeBuffer(buffer: Float32Array, sampleRate: number): Promise<string>;
}

const GLUE_URL = '/data/whisper/whisper.js';
const WASM_URL = '/data/whisper/whisper.wasm';
const MODEL_URL = '/data/whisper/ggml-tiny.en.bin';

// Module-scoped factory cache: whisper.cpp's UMD glue registers a global
// ``Module`` factory on its first <script>-tag evaluation. Repeat calls
// reuse the already-injected script.
let _moduleFactoryPromise: Promise<unknown | null> | null = null;

/**
 * Internal seam — exported so vitest can stub the script-injection +
 * fetch boundary without touching the public API. Resolves to the
 * registered UMD factory, OR ``null`` if the glue script 404s / fails
 * to register a global ``Module``.
 *
 * Hard rule: NEVER replace this with a static ESM ``import`` of any
 * whisper symbol. The artifact set is operator-pulled and may not exist;
 * a static import breaks first paint when the file is absent.
 */
export async function _injectWhisperGlue(): Promise<unknown | null> {
  if (_moduleFactoryPromise) return _moduleFactoryPromise;
  _moduleFactoryPromise = (async () => {
    // Probe the glue file BEFORE injecting a <script> tag — a 404 on a
    // <script src> would surface in the console as a noisy error every
    // page load even when STT is intentionally disabled. The probe lets
    // us silently degrade.
    try {
      const resp = await fetch(GLUE_URL);
      if (!resp.ok) return null;
    } catch {
      return null;
    }
    return await new Promise<unknown | null>((resolve) => {
      try {
        const script = document.createElement('script');
        script.src = GLUE_URL;
        script.async = true;
        script.onload = () => {
          // UMD glue registers ``window.Module`` (or a similarly-named
          // factory). Read it indirectly to avoid bundler dead-code
          // elimination warnings.
          const w = window as unknown as Record<string, unknown>;
          const factory = w['Module'] ?? w['whisper_factory'] ?? null;
          resolve(factory);
        };
        script.onerror = () => resolve(null);
        document.head.appendChild(script);
      } catch {
        resolve(null);
      }
    });
  })();
  return _moduleFactoryPromise;
}

/**
 * Internal seam — exported so vitest can stub the fetch boundary.
 * Returns the bytes of an operator-pulled artifact, OR ``null`` on 404.
 */
export async function _fetchArtifact(url: string): Promise<ArrayBuffer | null> {
  try {
    const resp = await fetch(url);
    if (!resp.ok) return null;
    return await resp.arrayBuffer();
  } catch {
    return null;
  }
}

/**
 * Create a whisper.cpp inference handle. Returns ``null`` when any of
 * the three artifacts (glue / wasm / model bin) is absent — callers
 * MUST treat ``null`` as honest degrade (no STT; the existing
 * ``SpeechRecognition`` path remains the primary transcript source).
 */
export async function loadWhisperModel(): Promise<WhisperHandle | null> {
  const factory = await _injectWhisperGlue();
  if (!factory) return null;
  const wasmBytes = await _fetchArtifact(WASM_URL);
  if (!wasmBytes) return null;
  const modelBytes = await _fetchArtifact(MODEL_URL);
  if (!modelBytes) return null;
  // Instantiate the factory with the WASM binary + model bytes. The
  // exact factory contract varies by whisper.cpp build; we hand both
  // buffers to a single ``init`` call and read back a transcribe fn.
  // When the factory shape diverges, honest-degrade rather than throw.
  let runtime: Record<string, unknown> | null = null;
  try {
    if (typeof factory === 'function') {
      runtime = (await (factory as (...args: unknown[]) => Promise<unknown>)({
        wasmBinary: wasmBytes,
        modelBuffer: modelBytes,
      })) as Record<string, unknown> | null;
    }
  } catch {
    return null;
  }
  if (!runtime) return null;
  const transcribeFn = runtime['transcribeBuffer'] ?? runtime['transcribe'] ?? null;
  if (typeof transcribeFn !== 'function') return null;
  return {
    async transcribeBuffer(buffer: Float32Array, sampleRate: number): Promise<string> {
      try {
        const result = await (transcribeFn as (b: Float32Array, sr: number) => Promise<unknown>)(
          buffer,
          sampleRate,
        );
        if (typeof result === 'string') return result;
        if (result && typeof (result as Record<string, unknown>)['text'] === 'string') {
          return (result as Record<string, string>)['text'];
        }
        return '';
      } catch {
        return '';
      }
    },
  };
}

/**
 * Internal helper for vitest — clears the module-scoped factory cache
 * so each test starts from a clean script-injection state.
 */
export function _resetWhisperLoader(): void {
  _moduleFactoryPromise = null;
}
