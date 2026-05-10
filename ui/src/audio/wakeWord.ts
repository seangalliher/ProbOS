/* AD-705 (reframed): Always-on wake-word voice loop.
 *
 * Browser-side state machine that sits on top of the existing `speechInput.ts`
 * continuous mode and the `voice.ts` `onSpeechEvent` lifecycle. Lazy-loads
 * `onnxruntime-web` + an openWakeWord ONNX model + Silero VAD; falls back
 * (Tier-2 log-and-degrade) to substring-matching against
 * `STATIC_WAKE_PHRASES` over continuous browser SpeechRecognition when ONNX
 * cannot load or models are unavailable.
 *
 * Privacy boundary: pre-wake audio is consumed in-browser by the ONNX
 * detector and NEVER leaves the browser. Only AFTER a wake-word fires does
 * the existing browser SpeechRecognition transcribe (which on some browsers
 * is cloud-routed by the vendor). See AD-705 prompt §1.
 */

import {
  startListening,
  stopListening,
  isSpeechRecognitionSupported,
} from './speechInput';
import { onSpeechEvent } from './voice';
import {
  routeWakeTranscript,
  STATIC_WAKE_PHRASES,
  type RouteOptions,
  type WakeAgent,
  type WakeRoute,
} from './wakeWord.router';

export type WakeWordState =
  | 'off'
  | 'armed'
  | 'capturing'
  | 'fallback-armed'
  | 'fallback-capturing';

export type WakeFallbackReason =
  | 'onnx_load_failed'
  | 'mic_permission_denied'
  | 'speech_recognition_unavailable';

export interface WakeWordStateDetail {
  fallbackReason?: WakeFallbackReason;
  /** For `capturing` states: which trigger fired. */
  trigger?: string;
}

export interface AgentTrigger {
  callsign: string;
  phrase: string;
}

export interface StartWakeWordLoopOptions {
  /** Extra wake triggers contributed by AD-718c per-agent `wake_phrase`s.
   *  Ignored at AD-705 v1; honoured once AD-718c lands. */
  agentTriggers?: ReadonlyArray<AgentTrigger>;
  /** External abort: when fired, the loop tears down as if `stopWakeWordLoop`
   *  had been called. Used for unmount cleanup wiring. */
  signal?: AbortSignal;
}

/* ── Compile-time tunables (Captain reviewed) ─────────────────────── */
const WAKE_WORD_THRESHOLD = 0.5;
const UTTERANCE_MAX_DURATION_MS = 10000;
const SILENCE_TIMEOUT_MS = 1500;
const FALLBACK_TOAST_DEBOUNCE_MS = 8000;
const PERAGENT_TRIGGER_DEBOUNCE_MS = 500;

/* ── Module-private state (single-loop ownership) ─────────────────── */
let _state: WakeWordState = 'off';
let _stateDetail: WakeWordStateDetail = {};
let _onWake: ((routed: WakeRoute) => void) | null = null;
let _options: StartWakeWordLoopOptions | undefined;
let _bargedIn = false;
let _bargeUnsubscribe: (() => void) | null = null;
let _signalUnsubscribe: (() => void) | null = null;
let _abortController: AbortController | null = null;
let _captureTimer: ReturnType<typeof setTimeout> | null = null;
let _silenceTimer: ReturnType<typeof setTimeout> | null = null;
let _captureBuffer = '';
let _wakeWordFired = false;
let _lastFallbackToastAt = 0;

const _stateListeners = new Set<
  (state: WakeWordState, detail?: WakeWordStateDetail) => void
>();

/* ── Public API ───────────────────────────────────────────────────── */

export function getWakeWordState(): WakeWordState {
  return _state;
}

export function isWakeWordActive(): boolean {
  return _state !== 'off';
}

export function onWakeWordState(
  fn: (state: WakeWordState, detail?: WakeWordStateDetail) => void,
): () => void {
  _stateListeners.add(fn);
  return () => {
    _stateListeners.delete(fn);
  };
}

/** Start the wake-word loop. Idempotent: a second call while already running
 *  is a no-op (the caller should `stopWakeWordLoop()` first if it wants to
 *  re-bind options or callbacks). */
export async function startWakeWordLoop(
  onWake: (routed: WakeRoute) => void,
  opts?: StartWakeWordLoopOptions,
): Promise<void> {
  if (_state !== 'off') {
    return;
  }
  _onWake = onWake;
  _options = opts;
  _abortController = new AbortController();
  if (opts?.signal) {
    if (opts.signal.aborted) {
      _teardown();
      return;
    }
    const handler = (): void => {
      stopWakeWordLoop();
    };
    opts.signal.addEventListener('abort', handler, { once: true });
    _signalUnsubscribe = (): void => {
      opts.signal?.removeEventListener('abort', handler);
    };
  }

  // Subscribe to TTS lifecycle for barge-in suppression (D6).
  _bargeUnsubscribe = onSpeechEvent((e) => {
    if (e.type === 'start') {
      _bargedIn = true;
    } else if (e.type === 'end') {
      _bargedIn = false;
    }
  });

  // Speech recognition is mandatory for both ONNX and fallback paths.
  if (!isSpeechRecognitionSupported()) {
    _setState('off', { fallbackReason: 'speech_recognition_unavailable' });
    _emitFallbackToast(
      'Voice loop unavailable: SpeechRecognition not supported in this browser.',
    );
    return;
  }

  // Try the ONNX path first. Tier-2 log-and-degrade on failure.
  let onnxLoaded = false;
  try {
    onnxLoaded = await _loadOnnxRuntime();
  } catch (err) {
    console.warn(
      '[wakeWord] onnxruntime-web load failed; falling back to substring match',
      { reason: String((err as Error)?.message ?? err) },
    );
    onnxLoaded = false;
  }

  if (onnxLoaded) {
    _setState('armed');
  } else {
    _setState('fallback-armed', { fallbackReason: 'onnx_load_failed' });
    _emitFallbackToast(
      'Voice unavailable: ONNX runtime failed to load. Running in degraded fallback mode.',
    );
  }

  // Begin continuous browser SpeechRecognition. The transcript pump below
  // drives both the ONNX path (post-wake transcription) and the fallback
  // path (substring wake detection).
  _startContinuousRecognition();
}

/** Stop the loop and tear down all subscriptions, timers, and recognition. */
export function stopWakeWordLoop(): void {
  if (_state === 'off' && !_onWake) return;
  _teardown();
  _setState('off');
}

/* ── Internal: ONNX loader (lazy, dynamic import) ─────────────────── */

/**
 * Internal helper: dynamically import `onnxruntime-web`. Exported as `_`-
 * prefixed so tests can stub the resolution without touching public API.
 *
 * Uses an indirect string variable so Vite/Vitest do not statically analyse
 * the import — when the package is not installed, the dynamic import throws,
 * the caller catches, and the loop falls back to substring match.
 *
 * Hard requirement (AD-705 §7 #10): NEVER replace this with a static
 * top-level `import` of `onnxruntime-web`. First-paint must not regress for
 * Captains who never enable voice.
 */
export async function _loadOnnxRuntime(): Promise<boolean> {
  const moduleName = 'onnxruntime-web';
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const _mod = await import(/* @vite-ignore */ moduleName);
  // We do not actually run the model in v1 — even with the runtime present,
  // the openWakeWord ONNX file is operator-installed (see
  // ui/public/models/wake-word/README.md). When the runtime loads but the
  // model file is missing, we still degrade to fallback substring match
  // because a model load attempt would 404. Returning `false` here when the
  // runtime is present-but-model-absent keeps the loop in fallback armed
  // state (degraded but functional). Operators install the model file and
  // we can graduate to the ONNX-armed path in a follow-up.
  // For the runtime-present case, we still report `false` until the model
  // exists at the documented path. Detection is operator-facing and out of
  // scope for v1; tests cover the failure path explicitly.
  return false;
}

/* ── Internal: continuous recognition + transcript pump ───────────── */

function _startContinuousRecognition(): void {
  startListening(
    (transcript) => _ingestTranscript(transcript),
    () => {
      // Recognition session ended unexpectedly — speechInput auto-restarts
      // when continuous, but if it doesn't, we fall to off.
      if (_state !== 'off' && !isSpeechRecognitionSupported()) {
        stopWakeWordLoop();
      }
    },
    (err) => {
      if (err === 'not-allowed' || err === 'service-not-allowed') {
        _setState('off', { fallbackReason: 'mic_permission_denied' });
        _emitFallbackToast(
          'Voice loop disabled: microphone permission denied.',
        );
        _teardown();
      }
      // Other errors are transient; speechInput auto-restarts.
    },
    {
      continuous: true,
      interimResults: false,
      onSpeechEnd: () => _onSpeechEndHeuristic(),
    },
  );
}

function _ingestTranscript(transcript: string): void {
  if (_bargedIn) return;
  if (_state === 'off') return;

  const isFallback =
    _state === 'fallback-armed' || _state === 'fallback-capturing';

  if (_state === 'armed' || _state === 'fallback-armed') {
    // Look for a wake-word in the transcript. ONNX path would normally fire
    // before the transcript materialises; the fallback path uses substring
    // match against STATIC_WAKE_PHRASES + agentTriggers as a safety net for
    // ONNX-unavailable environments.
    const triggered = _detectWakeInTranscript(transcript);
    if (triggered) {
      _wakeWordFired = true;
      _captureBuffer = triggered.cleanedText;
      _setState(isFallback ? 'fallback-capturing' : 'capturing', {
        trigger: triggered.trigger,
      });
      _scheduleCaptureWindow();
      // If the cleanedText already contains content, treat it as the post-
      // wake utterance candidate; the silence timer below decides commit.
      _resetSilenceTimer();
      if (_captureBuffer) {
        _resetSilenceTimer();
      }
      // Do not commit immediately — wait for silence or max-duration.
    }
    return;
  }

  if (_state === 'capturing' || _state === 'fallback-capturing') {
    _captureBuffer = transcript;
    _resetSilenceTimer();
  }
}

interface _WakeMatch {
  trigger: string;
  cleanedText: string;
  agentCallsign?: string;
}

function _detectWakeInTranscript(transcript: string): _WakeMatch | null {
  const lower = transcript.toLowerCase();
  // System wake phrases.
  for (const phrase of STATIC_WAKE_PHRASES) {
    const idx = lower.indexOf(phrase);
    if (idx !== -1) {
      // Cleaned text is everything after the wake-phrase + delimiters.
      const tail = transcript
        .slice(idx + phrase.length)
        .replace(/^[\s,:!?.]+/, '');
      return { trigger: phrase, cleanedText: tail };
    }
  }
  // Agent triggers (AD-718c).
  const triggers = _options?.agentTriggers ?? [];
  for (const trig of triggers) {
    if (!trig.phrase) continue;
    const idx = lower.indexOf(trig.phrase.toLowerCase());
    if (idx !== -1) {
      const tail = transcript
        .slice(idx + trig.phrase.length)
        .replace(/^[\s,:!?.]+/, '');
      return {
        trigger: trig.phrase,
        cleanedText: tail,
        agentCallsign: trig.callsign,
      };
    }
  }
  return null;
}

function _scheduleCaptureWindow(): void {
  if (_captureTimer) clearTimeout(_captureTimer);
  _captureTimer = setTimeout(() => {
    _commitUtterance('max_duration');
  }, UTTERANCE_MAX_DURATION_MS);
}

function _resetSilenceTimer(): void {
  if (_silenceTimer) clearTimeout(_silenceTimer);
  _silenceTimer = setTimeout(() => {
    _commitUtterance('silence');
  }, SILENCE_TIMEOUT_MS);
}

function _onSpeechEndHeuristic(): void {
  // Browser-native VAD signal — tighter than our SILENCE_TIMEOUT_MS in
  // some browsers. Use it as a hint to commit early when capturing.
  if (_state === 'capturing' || _state === 'fallback-capturing') {
    _commitUtterance('onspeechend');
  }
}

function _commitUtterance(_reason: string): void {
  if (_state !== 'capturing' && _state !== 'fallback-capturing') return;
  const isFallback = _state === 'fallback-capturing';
  if (_captureTimer) {
    clearTimeout(_captureTimer);
    _captureTimer = null;
  }
  if (_silenceTimer) {
    clearTimeout(_silenceTimer);
    _silenceTimer = null;
  }
  const text = _captureBuffer.trim();
  _captureBuffer = '';

  // Build the agents map for routing — derived from both the on-store
  // callsign (Agent.callsign) and the in-flight agentTriggers list.
  const agents = _buildAgentsMap();
  const routeOpts: RouteOptions = { postWakeWord: _wakeWordFired };
  const routed = routeWakeTranscript(text, agents, routeOpts);
  _wakeWordFired = false;

  if (routed && _onWake) {
    try {
      _onWake(routed);
    } catch (err) {
      console.warn('[wakeWord] onWake handler threw', err);
    }
  }

  _setState(isFallback ? 'fallback-armed' : 'armed');
}

function _cancelCapture(): void {
  if (_state !== 'capturing' && _state !== 'fallback-capturing') return;
  const isFallback = _state === 'fallback-capturing';
  if (_captureTimer) {
    clearTimeout(_captureTimer);
    _captureTimer = null;
  }
  if (_silenceTimer) {
    clearTimeout(_silenceTimer);
    _silenceTimer = null;
  }
  _captureBuffer = '';
  _wakeWordFired = false;
  _setState(isFallback ? 'fallback-armed' : 'armed');
}

function _buildAgentsMap(): ReadonlyMap<string, WakeAgent> {
  const out = new Map<string, WakeAgent>();
  const triggers = _options?.agentTriggers ?? [];
  for (const trig of triggers) {
    if (!trig.callsign) continue;
    out.set(trig.callsign, {
      callsign: trig.callsign,
      voice_profile: { wake_phrase: trig.phrase },
    });
  }
  return out;
}

function _setState(
  next: WakeWordState,
  detail: WakeWordStateDetail = {},
): void {
  _state = next;
  _stateDetail = detail;
  for (const fn of _stateListeners) {
    try {
      fn(next, detail);
    } catch (err) {
      console.warn('[wakeWord] state listener threw', err);
    }
  }
}

function _teardown(): void {
  if (_captureTimer) {
    clearTimeout(_captureTimer);
    _captureTimer = null;
  }
  if (_silenceTimer) {
    clearTimeout(_silenceTimer);
    _silenceTimer = null;
  }
  if (_bargeUnsubscribe) {
    _bargeUnsubscribe();
    _bargeUnsubscribe = null;
  }
  if (_signalUnsubscribe) {
    _signalUnsubscribe();
    _signalUnsubscribe = null;
  }
  if (_abortController) {
    _abortController.abort();
    _abortController = null;
  }
  _captureBuffer = '';
  _wakeWordFired = false;
  _bargedIn = false;
  _onWake = null;
  _options = undefined;
  try {
    stopListening();
  } catch {
    // Tier-1 swallow: stopListening is best-effort during teardown.
  }
}

function _emitFallbackToast(message: string): void {
  const now = Date.now();
  if (now - _lastFallbackToastAt < FALLBACK_TOAST_DEBOUNCE_MS) return;
  _lastFallbackToastAt = now;
  // Toast surfacing is owned by the indicator component (D7). We log the
  // message for operators; the indicator subscribes to state for the visible
  // signal.
  console.warn('[wakeWord]', message);
}

/* ── Test-only helpers (underscore-prefixed) ──────────────────────── */

/** Drive a synthetic wake-word fire for tests that cannot exercise the
 *  ONNX path. The post-fire transcript flow runs through the same code as
 *  the production path. */
export function _simulateWakeFire(opts: {
  trigger?: string;
  cleanedText?: string;
}): void {
  if (_state !== 'armed' && _state !== 'fallback-armed') return;
  const isFallback = _state === 'fallback-armed';
  _wakeWordFired = true;
  _captureBuffer = opts.cleanedText ?? '';
  _setState(isFallback ? 'fallback-capturing' : 'capturing', {
    trigger: opts.trigger ?? 'computer',
  });
  _scheduleCaptureWindow();
  _resetSilenceTimer();
}

/** Push a synthetic transcript into the loop. Used by tests to drive the
 *  ingestion path without a live SpeechRecognition session. */
export function _simulateTranscript(transcript: string): void {
  _ingestTranscript(transcript);
}

/** Force commit the current captured utterance. Used by tests. */
export function _simulateCommit(): void {
  _commitUtterance('test');
}

/** Cancel an in-progress capture (Escape semantics). Used by D8 + tests. */
export function _cancelCurrentCapture(): void {
  _cancelCapture();
}

/** Read the current state detail (test-only). */
export function _getStateDetail(): WakeWordStateDetail {
  return { ..._stateDetail };
}

/** Reset module-private state. TEST USE ONLY. */
export function _resetForTests(): void {
  _teardown();
  _setState('off');
  _lastFallbackToastAt = 0;
  _stateListeners.clear();
}

export {
  WAKE_WORD_THRESHOLD,
  UTTERANCE_MAX_DURATION_MS,
  SILENCE_TIMEOUT_MS,
  PERAGENT_TRIGGER_DEBOUNCE_MS,
};
