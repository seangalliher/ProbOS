/**
 * AD-705a — Offline STT consumer driven by the AD-721b-3 whisper.cpp
 * loader and the AD-733c-7-5 VAD PCM tap.
 *
 * **DEPRECATED in BF-301 (#775).** The whisper.cpp WASM artifact pipeline
 * this module depends on is abandoned upstream (HF tag deleted, CDN dead,
 * npm package incomplete). All active call sites have been migrated to
 * ``./transformersStt.ts``. This file is retained for one ProbOS release
 * cycle to ease revert; a follow-up hygiene PR will delete it.
 *
 * Subscribes to the existing ``voiceActivity`` PCM tap when armed
 * (``cognitive.offline_stt_enabled = true``); collects PCM frames
 * between Silero VAD speech_start / speech_end; runs the recognized
 * buffer through ``loadWhisperModel()``; emits the transcript through
 * the module-level ``onTranscript`` subscription.
 *
 * Privacy invariant (AD-733c-7 extended, AD-705a load-bearing): audio
 * bytes NEVER leave the browser. This module performs NO fetch calls
 * with any audio payload. The transcript STRING is the only datum that
 * crosses the wire — and it does so through ``IntentSurface``'s
 * existing keyboard ``handleSubmit`` path (NOT here).
 *
 * Honest-degrade paths:
 *   - ``loadWhisperModel()`` returns ``null`` (model not pulled) →
 *     no-op; no transcript emitted; browser-native ``SpeechRecognition``
 *     fallback in ``wakeWord.ts`` remains the primary path.
 *   - ``transcribeBuffer`` throws or returns empty → no transcript
 *     emitted.
 *   - Snapshot disabled OR absent → no subscription, zero overhead.
 */
import {
  subscribePcm,
  type PcmTapHandler,
} from './voiceActivity';
import { loadWhisperModel, type WhisperHandle } from './whisperLoader';

const SAMPLE_RATE = 16000;
// Hard ceiling on collected audio per utterance — guards against a
// missed speech_end signal eating unbounded memory. ~30 s of 16 kHz
// f32 mono = ~1.9 MB.
const MAX_UTTERANCE_SAMPLES = SAMPLE_RATE * 30;

type TranscriptListener = (text: string) => void;

interface SttState {
  unsubscribe: () => void;
  modelPromise: Promise<WhisperHandle | null> | null;
  ringBuffers: Float32Array[];
  ringSampleCount: number;
  transcribing: boolean;
}

let _state: SttState | null = null;
const _transcriptListeners: Set<TranscriptListener> = new Set();
const _transcribingListeners: Set<(active: boolean) => void> = new Set();
let _loaderOverride: (() => Promise<WhisperHandle | null>) | null = null;

/**
 * Internal seam — tests stub ``loadWhisperModel`` via this setter
 * without monkey-patching the module import.
 */
export function _setWhisperLoaderOverride(
  override: (() => Promise<WhisperHandle | null>) | null,
): void {
  _loaderOverride = override;
}

async function _loadModel(): Promise<WhisperHandle | null> {
  if (_loaderOverride) return _loaderOverride();
  return loadWhisperModel();
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

async function _runTranscription(buffers: Float32Array[]): Promise<void> {
  if (!_state) return;
  // Concatenate the ring into a single Float32Array.
  let total = 0;
  for (const b of buffers) total += b.length;
  if (total === 0) return;
  const merged = new Float32Array(total);
  let offset = 0;
  for (const b of buffers) {
    merged.set(b, offset);
    offset += b.length;
  }
  if (_state.modelPromise === null) {
    _state.modelPromise = _loadModel();
  }
  const handle = await _state.modelPromise;
  if (!handle) return;
  _state.transcribing = true;
  _emitTranscribing(true);
  let text = '';
  try {
    text = await handle.transcribeBuffer(merged, SAMPLE_RATE);
  } catch {
    text = '';
  } finally {
    _state.transcribing = false;
    _emitTranscribing(false);
  }
  if (!text) return;
  for (const cb of _transcriptListeners) {
    try {
      cb(text);
    } catch {
      // Tier-2.
    }
  }
}

function _buildTapHandler(): PcmTapHandler {
  return {
    onFrame(frame, _sr) {
      if (!_state) return;
      // Only retain frames once speech has started — otherwise we'd
      // accumulate silence between utterances unboundedly.
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
      // speech_start actually collects (the gate above checks length 0
      // AND count 0). We push an empty buffer to flip the gate.
      _state.ringBuffers = [new Float32Array(0)];
      _state.ringSampleCount = 0;
    },
    onSpeechEnd(_now) {
      if (!_state) return;
      const buffers = _state.ringBuffers;
      _state.ringBuffers = [];
      _state.ringSampleCount = 0;
      // Run transcription out-of-band so we don't block the VAD loop.
      void _runTranscription(buffers);
    },
  };
}

/**
 * Arm the STT consumer. Idempotent. Returns the unsubscribe handle so
 * callers can hot-toggle off the settings store.
 */
export function armWhisperStt(): () => void {
  if (_state) return disarmWhisperStt;
  const handler = _buildTapHandler();
  _state = {
    unsubscribe: subscribePcm(handler),
    modelPromise: null,
    ringBuffers: [],
    ringSampleCount: 0,
    transcribing: false,
  };
  return disarmWhisperStt;
}

/** Disarm the STT consumer. Idempotent. */
export function disarmWhisperStt(): void {
  if (!_state) return;
  try {
    _state.unsubscribe();
  } catch {
    // Tier-2.
  }
  _state = null;
}

/**
 * Subscribe to transcript events. Returns an unsubscribe handle.
 * Listeners receive the recognized text; they MUST NOT carry the audio
 * back over the wire — the privacy invariant is enforced at the call
 * site (IntentSurface only sends the text string).
 */
export function onTranscript(listener: TranscriptListener): () => void {
  _transcriptListeners.add(listener);
  return () => {
    _transcriptListeners.delete(listener);
  };
}

/** Subscribe to transcribing-state changes (HXI badge pulse). */
export function onTranscribing(listener: (active: boolean) => void): () => void {
  _transcribingListeners.add(listener);
  return () => {
    _transcribingListeners.delete(listener);
  };
}

/** Test seam — inspect armed state. */
export function _isArmed(): boolean {
  return _state !== null;
}

/** Test seam — clear all module state between tests. */
export function _resetWhisperStt(): void {
  disarmWhisperStt();
  _transcriptListeners.clear();
  _transcribingListeners.clear();
  _loaderOverride = null;
}
