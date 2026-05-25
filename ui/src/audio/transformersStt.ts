/**
 * BF-301 (#775) — transformers.js Whisper STT consumer.
 *
 * Replaces the AD-705a whisper.cpp WASM path (abandoned upstream — HF tag
 * deleted, CDN dead, npm package incomplete). Uses ``@huggingface/transformers``
 * v3 ``pipeline('automatic-speech-recognition', 'Xenova/whisper-tiny.en')``
 * running inside a dedicated Web Worker for thread isolation. Browser
 * Cache API persists model shards on first use; subsequent loads hit cache.
 *
 * Public surface mirrors ``./whisperStt.ts`` so the three migrated call
 * sites (ProfileChatTab.tsx, IntentSurface.tsx, conversationController.ts)
 * use import-name swaps with local aliases — no logic changes required.
 *
 * New surface vs. AD-705a: ``onTransformersProgress(handler)`` exposes
 * the first-load download status so the UI can render a progress bar
 * during initial model fetch.
 *
 * Privacy invariant (AD-733c-7 extended, AD-705a load-bearing): audio
 * bytes NEVER leave the browser via this module. The model fetch
 * traffic is HF CDN ↔ browser for ONNX weights only — never operator
 * audio. The transcript STRING is the sole output crossing the wire.
 *
 * Honest-degrade paths:
 *   - Worker model fetch fails → ``{status: 'error'}`` progress event;
 *     no transcripts emitted; UI falls through to browser SR via the
 *     existing AD-826 empty-counter logic (see ProfileChatTab.tsx).
 *   - VAD subscription absent → arm() succeeds idempotently; no frames
 *     collected; no transcripts emitted.
 */
import {
  subscribePcm,
  type PcmTapHandler,
} from './voiceActivity';

const SAMPLE_RATE = 16000;
// Hard ceiling on collected audio per utterance — guards against a
// missed speech_end signal eating unbounded memory. ~30 s of 16 kHz
// f32 mono = ~1.9 MB. Matches whisperStt.ts.
const MAX_UTTERANCE_SAMPLES = SAMPLE_RATE * 30;
// BF-310: pre-roll buffer length. The VAD's minSpeechMs=400 ms means
// onSpeechStart fires ~400 ms AFTER speech actually began — without a
// pre-roll, whisper sees audio that starts mid-word and routinely
// hallucinates ("Testing" → "as retail"). Keep a 600 ms rolling
// pre-buffer at all times; prepend it to the utterance when
// speech_start fires so whisper gets the word onset.
const PREROLL_SAMPLES = Math.floor(SAMPLE_RATE * 0.6);

const DEFAULT_MODEL = 'Xenova/whisper-tiny.en';

export interface TransformersProgressEvent {
  status: 'initiate' | 'download' | 'progress' | 'done' | 'ready' | 'error';
  name?: string;
  file?: string;
  loaded?: number;
  total?: number;
  progress?: number;
}

type TranscriptListener = (text: string) => void;
type TranscribingListener = (active: boolean) => void;
type ProgressListener = (event: TransformersProgressEvent) => void;

interface Engaged {
  unsubscribe: () => void;
  ringBuffers: Float32Array[];
  ringSampleCount: number;
  // BF-310: rolling pre-speech buffer. Always accumulating; trimmed to
  // ``PREROLL_SAMPLES`` worth of audio. Dumped into ``ringBuffers`` at
  // speech_start so whisper receives the word onset.
  preroll: Float32Array[];
  prerollCount: number;
}

// BF-320: worker + whisper pipeline survive across arm/disarm cycles so
// PTT clicks don't pay the ~2-4s whisper-medium.en re-init cost.
// ``_engaged`` carries the PCM-tap subscription + per-utterance ring
// buffers and is allocated only while armed.
let _worker: Worker | null = null;
let _engaged: Engaged | null = null;
const _transcriptListeners: Set<TranscriptListener> = new Set();
const _transcribingListeners: Set<TranscribingListener> = new Set();
const _progressListeners: Set<ProgressListener> = new Set();
let _workerOverride: (() => Worker) | null = null;
let _model = DEFAULT_MODEL;

/**
 * Test seam — vitest stubs the Worker boundary with a MessageChannel-
 * backed fake. Production code MUST NOT import ``Worker`` from anywhere
 * mockable; this is the only injection point.
 */
export function _setTransformersWorkerOverride(
  factory: (() => Worker) | null,
): void {
  _workerOverride = factory;
}

/** Test seam — reset module-scoped state between tests. */
export function _resetTransformersStt(): void {
  if (_engaged) {
    try { _engaged.unsubscribe(); } catch { /* Tier-2 */ }
  }
  _engaged = null;
  if (_worker) {
    try { _worker.postMessage({ type: 'shutdown' }); } catch { /* Tier-2 */ }
    try { _worker.terminate(); } catch { /* Tier-2 */ }
  }
  _worker = null;
  _transcriptListeners.clear();
  _transcribingListeners.clear();
  _progressListeners.clear();
  _workerOverride = null;
  _model = DEFAULT_MODEL;
}

/** Test seam — inspect armed state. */
export function _isArmed(): boolean {
  return _engaged !== null;
}

/**
 * Override the model id used on next ``armTransformersStt``. Call sites
 * may read ``voiceHealth.model`` and call this before arming to honor
 * operator-configured ``cognitive.transformers_model``.
 */
export function _setTransformersModel(model: string): void {
  if (typeof model === 'string' && model.length > 0) {
    _model = model;
  }
}

function _emitTranscribing(active: boolean): void {
  for (const cb of _transcribingListeners) {
    try {
      cb(active);
    } catch {
      // Tier-2.
    }
  }
}

function _emitTranscript(text: string): void {
  if (!text) return;
  for (const cb of _transcriptListeners) {
    try {
      cb(text);
    } catch {
      // Tier-2.
    }
  }
}

function _emitProgress(event: TransformersProgressEvent): void {
  for (const cb of _progressListeners) {
    try {
      cb(event);
    } catch {
      // Tier-2.
    }
  }
}

function _defaultWorkerFactory(): Worker {
  // Vite-native: `new Worker(new URL(..., import.meta.url), { type: 'module' })`.
  // Vite 6 emits an ES-module worker chunk; rollupOptions in vite.config.ts
  // colocates this with the @huggingface/transformers bundle as `stt-vendor`.
  return new Worker(
    new URL('./transformersWorker.ts', import.meta.url),
    { type: 'module' },
  );
}

function _buildTapHandler(): PcmTapHandler {
  return {
    onFrame(frame, _sr) {
      if (!_engaged) return;
      // BF-310: while pre-speech, accumulate into the rolling preroll
      // buffer (FIFO trim to PREROLL_SAMPLES). Once speech_start has
      // fired (ringBuffers non-empty), append to the utterance ring.
      if (_engaged.ringBuffers.length === 0 && _engaged.ringSampleCount === 0) {
        // Pre-speech: append to preroll, trim oldest frames.
        _engaged.preroll.push(new Float32Array(frame));
        _engaged.prerollCount += frame.length;
        while (_engaged.prerollCount > PREROLL_SAMPLES && _engaged.preroll.length > 1) {
          const dropped = _engaged.preroll.shift();
          if (dropped) _engaged.prerollCount -= dropped.length;
        }
        return;
      }
      if (_engaged.ringSampleCount + frame.length > MAX_UTTERANCE_SAMPLES) {
        return;
      }
      // Defensive copy — the VAD loop may reuse the buffer.
      _engaged.ringBuffers.push(new Float32Array(frame));
      _engaged.ringSampleCount += frame.length;
    },
    onSpeechStart(_now) {
      if (!_engaged) return;
      // BF-310: seed the utterance ring with the rolling pre-roll so
      // whisper sees the word onset (otherwise the first 400 ms is
      // lost). Clear the preroll buffer after the dump — the next
      // utterance gathers fresh pre-roll while the current one is
      // being collected (we keep filling preroll between utterances).
      const seed: Float32Array[] = [];
      let seedCount = 0;
      for (const b of _engaged.preroll) {
        seed.push(b);
        seedCount += b.length;
      }
      _engaged.ringBuffers = seed.length > 0 ? seed : [new Float32Array(0)];
      _engaged.ringSampleCount = seedCount;
      _engaged.preroll = [];
      _engaged.prerollCount = 0;
    },
    onSpeechEnd(_now) {
      if (!_engaged || !_worker) return;
      const buffers = _engaged.ringBuffers;
      _engaged.ringBuffers = [];
      _engaged.ringSampleCount = 0;
      // Concatenate and ship to the worker.
      let total = 0;
      for (const b of buffers) total += b.length;
      if (total === 0) return;
      const merged = new Float32Array(total);
      let offset = 0;
      for (const b of buffers) {
        merged.set(b, offset);
        offset += b.length;
      }
      try {
        _worker.postMessage(
          { type: 'transcribe', samples: merged, sampleRate: SAMPLE_RATE },
          [merged.buffer],
        );
      } catch {
        // Tier-2 — worker may have been terminated between the speech
        // event and dispatch.
      }
    },
  };
}

function _wireWorker(worker: Worker): void {
  worker.addEventListener('message', (e: MessageEvent) => {
    const msg = e.data;
    if (!msg || typeof msg !== 'object') return;
    if (msg.type === 'progress') {
      const event = msg.event as TransformersProgressEvent | undefined;
      if (event && typeof event.status === 'string') {
        _emitProgress(event);
      }
      return;
    }
    if (msg.type === 'transcript') {
      const text = typeof msg.text === 'string' ? msg.text : '';
      _emitTranscript(text);
      return;
    }
    if (msg.type === 'transcribing') {
      _emitTranscribing(Boolean(msg.active));
      return;
    }
  });
}

/**
 * Arm the STT consumer. Idempotent. Returns the disarm handle so callers
 * can hot-toggle off the settings store.
 *
 * BF-320: the Worker + whisper pipeline is created ONCE per page
 * lifetime and reused across arm/disarm cycles. Subsequent arm calls
 * only re-subscribe the PCM tap; the model stays resident.
 */
export function armTransformersStt(): () => void {
  if (_engaged) return disarmTransformersStt;
  if (_worker === null) {
    const factory = _workerOverride ?? _defaultWorkerFactory;
    const worker = factory();
    _wireWorker(worker);
    // Init the pipeline; the worker emits progress events back through
    // the message channel.
    try {
      worker.postMessage({ type: 'init', model: _model });
    } catch {
      // Tier-2 — surface a synthetic error progress event so subscribers
      // can fall through.
      _emitProgress({ status: 'error', name: _model, file: 'postMessage init failed' });
    }
    _worker = worker;
  }
  _engaged = {
    unsubscribe: subscribePcm(_buildTapHandler()),
    ringBuffers: [],
    ringSampleCount: 0,
    preroll: [],
    prerollCount: 0,
  };
  return disarmTransformersStt;
}

/**
 * Disarm the STT consumer. Idempotent. Detaches the PCM tap only — the
 * worker + whisper pipeline remain resident for the next arm cycle.
 * Use ``terminateTransformersStt`` to fully tear down (e.g. on page
 * unload).
 */
export function disarmTransformersStt(): void {
  if (!_engaged) return;
  try {
    _engaged.unsubscribe();
  } catch {
    // Tier-2.
  }
  _engaged = null;
}

/**
 * Fully shut down the worker + whisper pipeline. Disarms first if armed.
 * Wired to ``beforeunload`` in production; callable directly from tests.
 */
export function terminateTransformersStt(): void {
  if (_engaged) {
    try { _engaged.unsubscribe(); } catch { /* Tier-2 */ }
    _engaged = null;
  }
  if (_worker === null) return;
  const worker = _worker;
  _worker = null;
  try {
    worker.postMessage({ type: 'shutdown' });
  } catch {
    // Tier-2.
  }
  // 250 ms grace before terminate; covers in-flight transcribe responses
  // still being delivered.
  setTimeout(() => {
    try {
      worker.terminate();
    } catch {
      // Tier-2.
    }
  }, 250);
}

/**
 * Subscribe to transcript events. Returns an unsubscribe handle.
 * Listeners receive the recognized text; they MUST NOT carry the audio
 * back over the wire — the privacy invariant is enforced at the call
 * site (only the text string is sent in subsequent API calls).
 */
export function onTransformersTranscript(listener: TranscriptListener): () => void {
  _transcriptListeners.add(listener);
  return () => {
    _transcriptListeners.delete(listener);
  };
}

/** Subscribe to transcribing-state changes (HXI mic pulse). */
export function onTransformersTranscribing(listener: TranscribingListener): () => void {
  _transcribingListeners.add(listener);
  return () => {
    _transcribingListeners.delete(listener);
  };
}

/**
 * Subscribe to first-load model download progress. Listeners receive
 * the transformers.js progress event shape verbatim — see the type for
 * the discriminated status field.
 */
export function onTransformersProgress(listener: ProgressListener): () => void {
  _progressListeners.add(listener);
  return () => {
    _progressListeners.delete(listener);
  };
}

// BF-320: tear down the resident worker on page unload so the model
// doesn't keep its WebGPU/wasm allocations alive past the page lifetime.
// Guarded for SSR / non-browser test environments without a real window.
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener('beforeunload', () => {
    try { terminateTransformersStt(); } catch { /* Tier-2 */ }
  });
}
