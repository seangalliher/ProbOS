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

interface SttState {
  worker: Worker;
  unsubscribe: () => void;
  ringBuffers: Float32Array[];
  ringSampleCount: number;
}

let _state: SttState | null = null;
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
  if (_state) {
    try { _state.unsubscribe(); } catch { /* Tier-2 */ }
    try { _state.worker.terminate(); } catch { /* Tier-2 */ }
  }
  _state = null;
  _transcriptListeners.clear();
  _transcribingListeners.clear();
  _progressListeners.clear();
  _workerOverride = null;
  _model = DEFAULT_MODEL;
}

/** Test seam — inspect armed state. */
export function _isArmed(): boolean {
  return _state !== null;
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
      if (!_state) return;
      // Only retain frames once speech has started — otherwise we'd
      // accumulate silence between utterances unboundedly. Matches
      // whisperStt.ts gating.
      if (_state.ringBuffers.length === 0 && _state.ringSampleCount === 0) {
        return;
      }
      if (_state.ringSampleCount + frame.length > MAX_UTTERANCE_SAMPLES) {
        return;
      }
      // Defensive copy — the VAD loop may reuse the buffer.
      _state.ringBuffers.push(new Float32Array(frame));
      _state.ringSampleCount += frame.length;
    },
    onSpeechStart(_now) {
      if (!_state) return;
      // Seed the ring with a marker so the first onFrame past
      // speech_start actually collects (gate above checks length 0 AND
      // count 0). An empty buffer flips the gate.
      _state.ringBuffers = [new Float32Array(0)];
      _state.ringSampleCount = 0;
    },
    onSpeechEnd(_now) {
      if (!_state) return;
      const buffers = _state.ringBuffers;
      _state.ringBuffers = [];
      _state.ringSampleCount = 0;
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
        _state.worker.postMessage(
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
 */
export function armTransformersStt(): () => void {
  if (_state) return disarmTransformersStt;
  const factory = _workerOverride ?? _defaultWorkerFactory;
  const worker = factory();
  _wireWorker(worker);
  // Init the pipeline; the worker emits progress events back through the
  // message channel.
  try {
    worker.postMessage({ type: 'init', model: _model });
  } catch {
    // Tier-2 — surface a synthetic error progress event so subscribers
    // can fall through.
    _emitProgress({ status: 'error', name: _model, file: 'postMessage init failed' });
  }
  _state = {
    worker,
    unsubscribe: subscribePcm(_buildTapHandler()),
    ringBuffers: [],
    ringSampleCount: 0,
  };
  return disarmTransformersStt;
}

/** Disarm the STT consumer. Idempotent. */
export function disarmTransformersStt(): void {
  if (!_state) return;
  const worker = _state.worker;
  try {
    _state.unsubscribe();
  } catch {
    // Tier-2.
  }
  try {
    worker.postMessage({ type: 'shutdown' });
  } catch {
    // Tier-2.
  }
  _state = null;
  // 250 ms grace before terminate; covers in-flight transcribe responses
  // that the operator still wants to receive on the next arm cycle.
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
