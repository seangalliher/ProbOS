/**
 * BF-301 (#775) — transformers.js Whisper ASR worker.
 *
 * Self-contained Web Worker that owns the @huggingface/transformers v3
 * ``automatic-speech-recognition`` pipeline. The main thread (transformersStt.ts)
 * communicates with this worker via three message types:
 *
 *   - ``{ type: 'init', model: string }``     — load the ASR pipeline.
 *     Worker emits ``{ type: 'progress', event }`` during fetch and a
 *     ``{ status: 'ready' }`` event when the pipeline is constructed.
 *   - ``{ type: 'transcribe', captureId, jobId, samples, sampleRate }``
 *     — run inference. Processing, partial/final transcript and completion
 *     events echo the invocation's immutable IDs and increasing sequence.
 *   - ``{ type: 'shutdown' }`` — release the pipeline and self.close().
 *
 * Privacy invariant: this worker never makes audio-bearing network
 * requests. The transformers.js model fetch is HF-CDN ↔ browser for
 * ONNX weight shards only. Audio bytes are received via postMessage
 * from the main thread and consumed in-process.
 */
import {
  pipeline,
  type AutomaticSpeechRecognitionPipeline,
} from '@huggingface/transformers';
import type { TransformersJobEvent, TransformersJobIdentity } from './transformersStt';

// transformers.js v3 `pipeline()` has heavily overloaded signatures that
// blow the TS union-type budget when narrowed by string-literal task id.
// Cast through `unknown` to a narrow function type; the runtime contract
// is enforced by the discriminated-status messages we emit back.
type _AsrPipelineFactory = (
  task: 'automatic-speech-recognition',
  model: string,
  options: {
    progress_callback?: (event: unknown) => void;
  },
) => Promise<AutomaticSpeechRecognitionPipeline>;
const _pipeline = pipeline as unknown as _AsrPipelineFactory;

let _asr: AutomaticSpeechRecognitionPipeline | null = null;
let _model = 'Xenova/whisper-tiny.en';
let _initializing: Promise<AutomaticSpeechRecognitionPipeline> | null = null;
let _closed = false;
const _scope = self;
const _running = new Map<string, () => void>();

function _post(message: unknown): void {
  (_scope as unknown as Worker).postMessage(message);
}

/**
 * BF-309 + BF-315: whisper emits special tokens like ``[BLANK_AUDIO]``,
 * ``[INAUDIBLE]``, ``[MUSIC]``, ``(silence)`` for non-speech VAD windows,
 * and occasionally hallucinates symbol-only output like ``">>"`` or
 * ``"--"`` on near-silent audio. Filter at the worker boundary so no
 * consumer sees these markers. The strict rule: a meaningful transcript
 * MUST contain at least one letter or digit. Anything that doesn't is
 * non-speech and gets dropped.
 */
function _isMeaningfulTranscript(text: string): boolean {
  const trimmed = (text || '').trim();
  if (trimmed.length === 0) return false;
  // Whisper special-token markers: bracketed [TAG] or parenthetical (tag).
  if (/^[\[\(][^\]\)]*[\]\)]$/.test(trimmed)) return false;
  // BF-315: must contain at least one letter (any script) or digit. This
  // is strictly stronger than the prior pure-punctuation check, which
  // missed Unicode math/symbol categories (">>" is \p{Sm}, not \p{P}).
  if (!/[\p{L}\p{N}]/u.test(trimmed)) return false;
  return true;
}

function _initialize(): Promise<AutomaticSpeechRecognitionPipeline> {
  if (_initializing) return _initializing;
  _initializing = Promise.resolve().then(() => _pipeline(
    'automatic-speech-recognition', _model,
    { progress_callback: (event: unknown) => {
      if (!_closed) _post({ type: 'progress', event });
    } },
  )).then(async asr => {
    if (_closed) {
      await asr.dispose();
      throw new Error('Local STT worker closed during initialization.');
    }
    _asr = asr;
    _post({ type: 'progress', event: { status: 'ready', name: _model } });
    return asr;
  });
  return _initializing;
}

function _validIdentity(message: Record<string, unknown>): message is Record<string, unknown> & TransformersJobIdentity {
  return typeof message.captureId === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(message.captureId) &&
    typeof message.jobId === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(message.jobId);
}

_scope.addEventListener('message', async (e: MessageEvent) => {
  const msg = e.data;
  if (_closed || !msg || typeof msg !== 'object') return;

  if (msg.type === 'init') {
    if (!_initializing) _model = typeof msg.model === 'string' && msg.model.length > 0 ? msg.model : _model;
    try {
      await _initialize();
    } catch {
      if (!_closed) _post({
        type: 'progress',
        event: { status: 'error', name: _model, file: 'Local model initialization failed; jobs return explicit failure.' },
      });
    }
    return;
  }

  if (msg.type === 'transcribe') {
    if (!_validIdentity(msg) || _running.has(msg.jobId)) return;
    const identity: TransformersJobIdentity = Object.freeze({ captureId: msg.captureId, jobId: msg.jobId });
    let sequence = 0;
    let finished = false;
    const send = (event: Omit<Extract<TransformersJobEvent, { type: 'transcript' }>, keyof TransformersJobIdentity | 'sequence'> |
      Omit<Extract<TransformersJobEvent, { type: 'transcribing' }>, keyof TransformersJobIdentity | 'sequence'> |
      Omit<Extract<TransformersJobEvent, { type: 'complete' }>, keyof TransformersJobIdentity | 'sequence'>): void => {
      if (!finished) _post({ ...identity, ...event, sequence: ++sequence });
    };
    const finish = (outcome: 'success' | 'error'): void => {
      if (finished) return;
      send({ type: 'transcribing', active: false });
      send({ type: 'complete', outcome });
      finished = true;
      _running.delete(identity.jobId);
    };
    _running.set(identity.jobId, () => finish('error'));
    let outcome: 'success' | 'error' = 'error';
    try {
      send({ type: 'transcribing', active: true });
      if (!(msg.samples instanceof Float32Array) || !msg.samples.length ||
          msg.samples.length > 16000 * 30 || msg.sampleRate !== 16000) return;
      const asr = _asr ?? await (_initializing ?? Promise.reject(new Error('Local model not initialized.')));
      if (finished || _closed) return;
      if (!asr) throw new Error('Local model initialization returned no pipeline.');
      const out = await asr(msg.samples, {
        sampling_rate: 16000,
        chunk_length_s: 30,
        stride_length_s: 5,
        return_timestamps: false,
        chunk_callback: (chunk: { text?: string }) => {
          if (chunk && typeof chunk.text === 'string' && _isMeaningfulTranscript(chunk.text)) {
            send({ type: 'transcript', text: chunk.text, isPartial: true });
          }
        },
      } as Parameters<AutomaticSpeechRecognitionPipeline>[1]);
      const candidate = (out as { text?: unknown })?.text;
      const text = typeof candidate === 'string' && _isMeaningfulTranscript(candidate) ? candidate : '';
      send({ type: 'transcript', text, isPartial: false });
      outcome = 'success';
    } catch {
      console.warn('Local STT inference or initialization failed; completing the job without recognized text.');
    } finally {
      finish(outcome);
    }
    return;
  }

  if (msg.type === 'shutdown') {
    _closed = true;
    for (const finish of [..._running.values()]) finish();
    const asr = _asr;
    _asr = null;
    try { await asr?.dispose(); } catch {
      console.warn('Local STT model disposal failed; closing the worker releases its remaining resources.');
    } finally { _scope.close(); }
    return;
  }
});
