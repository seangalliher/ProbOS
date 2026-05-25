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
 *   - ``{ type: 'transcribe', samples: Float32Array, sampleRate: number }``
 *     — run inference. Worker emits ``{ type: 'transcribing', active: true }``
 *     then partial ``{ type: 'transcript', text, isPartial: true }`` events
 *     during chunked decoding, a final ``{ type: 'transcript', text,
 *     isPartial: false }``, and ``{ type: 'transcribing', active: false }``.
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

function _post(message: unknown): void {
  (self as unknown as Worker).postMessage(message);
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

self.addEventListener('message', async (e: MessageEvent) => {
  const msg = e.data;
  if (!msg || typeof msg !== 'object') return;

  if (msg.type === 'init') {
    _model = typeof msg.model === 'string' && msg.model.length > 0 ? msg.model : _model;
    try {
      _asr = await _pipeline(
        'automatic-speech-recognition',
        _model,
        {
          progress_callback: (event: unknown) => {
            // Forward HF progress shape verbatim; the main thread normalizes.
            _post({ type: 'progress', event });
          },
        },
      );
      _post({ type: 'progress', event: { status: 'ready', name: _model } });
    } catch (err) {
      _post({
        type: 'progress',
        event: { status: 'error', name: _model, file: String(err) },
      });
    }
    return;
  }

  if (msg.type === 'transcribe') {
    if (!_asr) return;
    _post({ type: 'transcribing', active: true });
    try {
      const samples = msg.samples as Float32Array;
      const out = await _asr(samples, {
        sampling_rate: msg.sampleRate ?? 16000,
        chunk_length_s: 30,
        stride_length_s: 5,
        return_timestamps: false,
        // chunk_callback fires per chunk during transcription, enabling
        // progressive partial transcripts (xenova/whisper-web pattern).
        chunk_callback: (chunk: { text?: string }) => {
          if (chunk && typeof chunk.text === 'string' && _isMeaningfulTranscript(chunk.text)) {
            _post({ type: 'transcript', text: chunk.text, isPartial: true });
          }
        },
      } as Parameters<AutomaticSpeechRecognitionPipeline>[1]);
      const text = (out as { text?: string })?.text ?? '';
      if (_isMeaningfulTranscript(text)) {
        _post({ type: 'transcript', text, isPartial: false });
      }
    } catch (err) {
      // Tier-2 log; no transcript emitted on failure.
      console.warn('[BF-301] transcribe error', err);
    } finally {
      _post({ type: 'transcribing', active: false });
    }
    return;
  }

  if (msg.type === 'shutdown') {
    _asr = null;
    self.close();
    return;
  }
});
