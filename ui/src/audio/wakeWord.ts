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
import {
  PRIORITY_WAKE_WORD,
  currentHolder as _arbiterCurrentHolder,
} from './speechRecognitionArbiter';
import { onSpeechEvent } from './voice';
import {
  routeWakeTranscript,
  STATIC_WAKE_PHRASES,
  type RouteOptions,
  type WakeAgent,
  type WakeRoute,
} from './wakeWord.router';
import { useSettingsStore } from '../store/useSettingsStore';

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

/** AD-736: explicit mic-permission state machine. Separate from
 *  ``WakeWordState`` — the wake loop can be ``off`` for multiple
 *  reasons (mic denied, ONNX missing, SR unavailable); this enum
 *  captures the *mic-permission* subset for Captain-visible UX. */
export type MicPermissionState =
  | 'pending'
  | 'granted'
  | 'denied'
  | 'unavailable';

const _micPermissionListeners = new Set<(s: MicPermissionState) => void>();
let _micPermissionState: MicPermissionState = 'pending';

/** AD-736: subscribe to mic-permission state changes. Fires the current
 *  state synchronously so subscribers don't need a separate getter. */
export function onMicPermissionState(
  fn: (s: MicPermissionState) => void,
): () => void {
  _micPermissionListeners.add(fn);
  try {
    fn(_micPermissionState);
  } catch (err) {
    console.warn('[wakeWord] mic listener error', err);
  }
  return () => {
    _micPermissionListeners.delete(fn);
  };
}

/** AD-736: read the current mic-permission state. Synchronous; no Promise. */
export function getMicPermissionState(): MicPermissionState {
  return _micPermissionState;
}

function _setMicPermission(next: MicPermissionState): void {
  if (next === _micPermissionState) return;
  _micPermissionState = next;
  for (const fn of _micPermissionListeners) {
    try {
      fn(next);
    } catch (err) {
      console.warn('[wakeWord] mic listener error', err);
    }
  }
}

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
let _activeAgentCallsign: string | null = null;
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

  // AD-736: feature-detect SR support, then hardware presence. The two
  // failure modes carry different Captain-facing guidance, so distinguish
  // them at the boundary.
  if (!isSpeechRecognitionSupported()) {
    _setMicPermission('unavailable');
    _setState('off', { fallbackReason: 'speech_recognition_unavailable' });
    _emitFallbackToast(
      'Voice loop unavailable: SpeechRecognition not supported in this browser.',
    );
    return;
  }

  // AD-736 Tier-2: hardware probe. If enumerateDevices is unavailable or
  // rejects, fall through optimistically — the SR onerror path will still
  // catch denial. Optimism preserves backward compat with browsers (Safari
  // < 14) that gate mediaDevices behind getUserMedia. Note: enumerateDevices
  // requires a secure context (HTTPS or localhost); over plain HTTP the
  // mediaDevices object is undefined and the guard short-circuits.
  try {
    const mediaDevices = navigator.mediaDevices;
    if (mediaDevices && typeof mediaDevices.enumerateDevices === 'function') {
      const devices = await mediaDevices.enumerateDevices();
      const hasAudioInput = devices.some((d) => d.kind === 'audioinput');
      if (!hasAudioInput) {
        _setMicPermission('unavailable');
        _setState('off', { fallbackReason: 'speech_recognition_unavailable' });
        console.info('[wakeWord] no audio input device detected; voice loop disabled');
        return;
      }
    }
  } catch (err) {
    console.warn('[wakeWord] enumerateDevices probe failed; continuing', err);
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
 * BF-307: previously used an indirect string + ``@vite-ignore`` to keep
 * ORT out of the bundle. With ``onnxruntime-web`` now a real dep
 * (BF-306), the indirection actively broke production — the browser
 * cannot resolve a bare specifier from a dynamic ``import()`` so this
 * function always threw. Use a regular dynamic import so Vite
 * code-splits ORT into its own chunk (lazy-loaded on first arm; the
 * function is only called when the wake-word loop engages, so
 * first-paint posture remains intact).
 */
export async function _loadOnnxRuntime(): Promise<boolean> {
  const _mod = await import('onnxruntime-web');
  // AD-705c (Wave 179): prefer the Captain-trained ``captain.onnx``
  // (or the operator-configured ``cognitive.custom_model_filename``)
  // over the stock community model. The fetch order ensures the
  // custom model takes priority; if neither responds 200, we honest-
  // degrade to substring-match (return false; existing AD-705 v1
  // behavior). Reading the snapshot via a dynamic import keeps the
  // first-paint posture intact (this function is only called when the
  // wake-word loop arms).
  let customFilename = 'captain.onnx';
  try {
    const snapshot = useSettingsStore.getState().snapshot;
    const cognitiveCfg = (snapshot?.config as Record<string, unknown> | undefined)
      ?.['cognitive'] as Record<string, unknown> | undefined;
    const cfgValue = cognitiveCfg?.['custom_model_filename'];
    if (typeof cfgValue === 'string' && cfgValue.length > 0) {
      customFilename = cfgValue;
    }
  } catch {
    // Tier-2: snapshot may not be hydrated yet; default filename is
    // safe.
  }
  const candidates = [
    `/models/wake-word/${customFilename}`,
    '/models/wake-word/hey_jarvis_v0.1.onnx',
  ];
  for (const url of candidates) {
    try {
      const resp = await fetch(url, { method: 'HEAD' });
      if (resp.ok) {
        // Model file is present; the runtime is loaded. v1 still
        // returns false because we do not actually run inference here
        // — graduating to true requires the inference path, tracked
        // separately. Returning false keeps the loop in the
        // fallback-armed state (BF-308 behavior preserved).
        return false;
      }
    } catch {
      // Tier-2: HEAD probe may fail in jsdom; ignore and try next.
    }
  }
  return false;
}

/* ── Internal: continuous recognition + transcript pump ───────────── */

function _startContinuousRecognition(): void {
  // BF-318: if a higher-priority holder owns the mic (press-to-talk
  // or ConversationController), park rather than trying to acquire.
  // ``onReleased`` (registered via the arbiter lease below) will
  // re-arm us when the higher holder finishes.
  const holder = _arbiterCurrentHolder();
  if (holder && holder.priority > PRIORITY_WAKE_WORD) {
    return;
  }
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
        _setMicPermission('denied');
        _setState('off', { fallbackReason: 'mic_permission_denied' });
        _emitFallbackToast(
          'Voice loop disabled: microphone permission denied.',
        );
        _teardown();
      } else if (err === 'audio-capture') {
        // AD-736: SpeechRecognition.error 'audio-capture' = mic hardware
        // problem (disconnected, in use by another app). Distinct from
        // permission denial; surfaces as 'unavailable'.
        _setMicPermission('unavailable');
        _setState('off', { fallbackReason: 'speech_recognition_unavailable' });
        console.info('[wakeWord] audio-capture error; voice loop disabled');
        _teardown();
      }
      // Other errors are transient; speechInput auto-restarts.
    },
    {
      continuous: true,
      interimResults: false,
      onSpeechEnd: () => _onSpeechEndHeuristic(),
      // BF-318 — wake-word yields to press-to-talk + conversation.
      priority: PRIORITY_WAKE_WORD,
      holder: 'wake_word',
      onPreempted: () => {
        // A higher-priority holder grabbed the mic. Park; we'll be
        // notified to re-arm when they release. The arbiter notifies
        // queued waiters' ``onReleased`` on release; we don't enqueue
        // ourselves (which would block press-to-talk's re-acquire) —
        // instead we poll via _maybeRearmAfterRelease below.
        _scheduleRearmAfterRelease();
      },
    },
  );
}

/** BF-318: while a higher-priority holder owns the mic, wake-word
 *  polls the arbiter's currentHolder() and re-arms when it goes
 *  null. Polling (vs. enqueuing) keeps wake-word from blocking
 *  press-to-talk re-acquires. */
let _rearmPoll: ReturnType<typeof setTimeout> | null = null;

function _scheduleRearmAfterRelease(): void {
  if (_rearmPoll !== null) return;
  _rearmPoll = setTimeout(() => {
    _rearmPoll = null;
    if (_state === 'off') return;
    const holder = _arbiterCurrentHolder();
    if (holder === null) {
      _startContinuousRecognition();
    } else {
      _scheduleRearmAfterRelease();
    }
  }, 250);
}

function _ingestTranscript(transcript: string): void {
  // AD-736: receiving any transcript means SR ran successfully, which
  // means the browser honoured the mic-permission grant. Promote state
  // once — subsequent calls short-circuit because _setMicPermission is
  // idempotent.
  if (_micPermissionState !== 'granted') {
    _setMicPermission('granted');
  }
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
      _activeAgentCallsign = triggered.agentCallsign ?? null;
      _captureBuffer = triggered.cleanedText;
      _setState(isFallback ? 'fallback-capturing' : 'capturing', {
        trigger: triggered.trigger,
      });
      _scheduleCaptureWindow();
      _resetSilenceTimer();
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

  // If a per-agent trigger fired, the surface is locked to that agent;
  // routeWakeTranscript still runs to strip any residual prefix tokens.
  let routed: WakeRoute | null;
  if (_activeAgentCallsign) {
    routed = {
      surface: 'agent',
      agentCallsign: _activeAgentCallsign,
      cleanedText: text,
    };
  } else {
    const agents = _buildAgentsMap();
    const routeOpts: RouteOptions = { postWakeWord: _wakeWordFired };
    routed = routeWakeTranscript(text, agents, routeOpts);
  }
  _wakeWordFired = false;
  _activeAgentCallsign = null;

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
  _activeAgentCallsign = null;
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
  _activeAgentCallsign = null;
  _bargedIn = false;
  _onWake = null;
  _options = undefined;
  try {
    stopListening();
  } catch {
    // Tier-1 swallow: stopListening is best-effort during teardown.
  }
  // AD-736: when the loop tears down, mic-permission state reverts to
  // pending UNLESS we know the browser refused permission. Permanent
  // denial sticks until page reload (the browser does not re-prompt).
  if (_micPermissionState !== 'denied' && _micPermissionState !== 'unavailable') {
    _setMicPermission('pending');
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
  agentCallsign?: string;
}): void {
  if (_state !== 'armed' && _state !== 'fallback-armed') return;
  const isFallback = _state === 'fallback-armed';
  _wakeWordFired = true;
  _activeAgentCallsign = opts.agentCallsign ?? null;
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
  // AD-736: reset mic permission state + listeners for test isolation.
  _micPermissionState = 'pending';
  _micPermissionListeners.clear();
}

export {
  WAKE_WORD_THRESHOLD,
  UTTERANCE_MAX_DURATION_MS,
  SILENCE_TIMEOUT_MS,
  PERAGENT_TRIGGER_DEBOUNCE_MS,
};
