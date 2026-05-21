/* Voice input — browser SpeechRecognition API (zero dependencies)
 *
 * BF-318: all acquisition now flows through speechRecognitionArbiter.
 * The arbiter is the single source of mic ownership; the module-level
 * activeRecognition below is an implementation detail behind it.
 */

import {
  acquire as _arbiterAcquire,
  release as _arbiterRelease,
  PRIORITY_PRESS_TO_TALK,
  type Lease,
} from './speechRecognitionArbiter';

// Extend Window for vendor-prefixed API
declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognitionInstance;
    webkitSpeechRecognition?: new () => SpeechRecognitionInstance;
  }
}

interface SpeechRecognitionInstance {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { results: { [index: number]: { [index: number]: { transcript: string } } } }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  abort(): void;
  stop(): void;
}

export function isSpeechRecognitionSupported(): boolean {
  return typeof window !== 'undefined' &&
    ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);
}

let activeRecognition: SpeechRecognitionInstance | null = null;
let stopRequested = false;
let activeContinuous = false;
let activeLease: Lease | null = null;
// AD-760: accumulator + silence-gap timer state for ``endOfSpeechGapMs``.
let gapAccumulator = '';
let gapTimer: ReturnType<typeof setTimeout> | null = null;
let gapForwardOnResult: ((text: string) => void) | null = null;

function _flushGapAccumulator(): void {
  if (gapTimer !== null) {
    clearTimeout(gapTimer);
    gapTimer = null;
  }
  const text = gapAccumulator.trim();
  gapAccumulator = '';
  const forward = gapForwardOnResult;
  gapForwardOnResult = null;
  if (text && forward) {
    try { forward(text); } catch { /* Tier-2 */ }
  }
}

/** Options for startListening. AD-474b adds continuous-listen + interim-results;
 *  AD-474c adds onSpeechEnd VAD callback. BF-318 adds priority +
 *  onPreempted. All fields optional; defaults preserve pre-BF-318
 *  behavior (press-to-talk priority, single-shot recognition, en-US,
 *  final results only). */
export interface ListenOptions {
  /** When true, recognition keeps listening across utterances and auto-restarts on session end
   *  until stopListening() is called. Defaults to false (single-shot — matches v0 behavior). */
  continuous?: boolean;
  /** When true, recognition reports interim (non-final) results in addition to finals.
   *  onResult still only fires for final results — interim filtering happens in the
   *  onresult handler. Set this if you wire a separate interim-display path. */
  interimResults?: boolean;
  /** Fires when the browser detects end-of-utterance (recognition.onspeechend), BEFORE
   *  recognition.onend fires for the session. Useful for flipping a mic icon to a
   *  "processing…" state without polling. AD-474c. */
  onSpeechEnd?: () => void;
  /** BF-318: priority for the arbiter lease. Defaults to
   *  PRIORITY_PRESS_TO_TALK (the historical caller is the press-to-talk
   *  mic button). Callers like wakeWord use PRIORITY_WAKE_WORD. */
  priority?: number;
  /** BF-318: fires when a higher-priority acquire preempts this
   *  session. The caller's recognition will already be aborted by the
   *  time this fires; this is a hook for state cleanup (icon reset,
   *  toast, etc.). */
  onPreempted?: (byHolder: string) => void;
  /** BF-318: optional holder tag for logs / observer (defaults to
   *  ``press_to_talk``). */
  holder?: string;
  /** AD-760: when set together with ``continuous: true``, the recognizer
   *  accumulates final transcripts and only fires ``onResult`` after
   *  the configured silence gap elapses without a new final (or on
   *  ``stopListening``). Unset/undefined preserves v0 behavior (single
   *  ``onResult`` per final). Recommended value for press-to-talk:
   *  ``1500`` ms. Only meaningful when ``continuous=true``. */
  endOfSpeechGapMs?: number;
}

export function startListening(
  onResult: (text: string) => void,
  onEnd?: () => void,
  onError?: (error: string) => void,
  opts?: ListenOptions,
): void {
  if (!isSpeechRecognitionSupported()) {
    onError?.('Speech recognition not supported in this browser');
    return;
  }

  // Stop any active session
  stopListening();
  stopRequested = false;

  const continuous = opts?.continuous === true;
  const interimResults = opts?.interimResults === true;
  activeContinuous = continuous;

  // BF-318 — acquire the arbiter lease before spawning. If the arbiter
  // denies (a higher-priority holder is active), the request queues
  // and ``onAcquired`` fires later; meanwhile no SR instance is
  // created. Callers that don't pass priority get press-to-talk.
  const priority = opts?.priority ?? PRIORITY_PRESS_TO_TALK;
  const holder = opts?.holder ?? 'press_to_talk';
  const lease = _arbiterAcquire({
    holder,
    priority,
    onAcquired: (grantedLease) => {
      activeLease = grantedLease;
      _spawnRecognition(onResult, onEnd, onError, continuous, interimResults, opts);
    },
    onPreempted: (by) => {
      // A higher-priority holder grabbed the device. Abort our SR
      // instance (the lease is already invalidated by the arbiter)
      // and notify the caller.
      _abortActiveRecognition();
      activeLease = null;
      opts?.onPreempted?.(by);
      onEnd?.();
    },
  });
  if (lease !== null) {
    activeLease = lease;
    // _grantSync already invoked onAcquired which spawned recognition.
  } else {
    // Queued — wait for onAcquired to fire. activeLease stays null
    // until promotion; isListening() returns false until SR spawns.
  }
}

function _spawnRecognition(
  onResult: (text: string) => void,
  onEnd: (() => void) | undefined,
  onError: ((error: string) => void) | undefined,
  continuous: boolean,
  interimResults: boolean,
  opts: ListenOptions | undefined,
): void {
  const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition!;
  const recognition = new Ctor();
  recognition.continuous = continuous;
  recognition.interimResults = interimResults;
  recognition.lang = 'en-US';

  // AD-760: end-of-speech gap mode. Accumulate finals across utterances
  // and only forward after ``endOfSpeechGapMs`` of silence (or on
  // stopListening). Default off — IntentSurface / wake-word / other
  // callers are unaffected.
  const gapMs = opts?.endOfSpeechGapMs;
  const gapEnabled = continuous && typeof gapMs === 'number' && gapMs > 0;
  if (gapEnabled) {
    gapAccumulator = '';
    gapForwardOnResult = onResult;
  }

  recognition.onresult = (event) => {
    // Pick the most recent final result. In single-shot mode this is always index 0.
    // In continuous mode results accumulate; we report the latest final transcript.
    // event.results[i].isFinal exists at runtime; types here keep the v0 shape.
    const results = event.results as unknown as ArrayLike<{ 0: { transcript: string }; isFinal?: boolean }>;
    let lastFinal: string | null = null;
    for (let i = 0; i < (results as { length: number }).length; i++) {
      const r = results[i];
      if (r.isFinal !== false) {
        lastFinal = r[0].transcript;
      }
    }
    if (lastFinal !== null) {
      if (gapEnabled) {
        // Append (with a leading space if needed) and (re)start the
        // silence-gap timer. onResult fires only when the timer elapses
        // or stopListening is called.
        const piece = lastFinal.trim();
        if (piece) {
          gapAccumulator = gapAccumulator
            ? `${gapAccumulator} ${piece}`
            : piece;
        }
        if (gapTimer !== null) clearTimeout(gapTimer);
        gapTimer = setTimeout(() => {
          gapTimer = null;
          _flushGapAccumulator();
        }, gapMs as number);
      } else {
        onResult(lastFinal);
      }
    }
  };

  recognition.onerror = (event) => {
    if (event.error !== 'aborted') {
      onError?.(event.error);
    }
  };

  // AD-474c — VAD end-of-utterance hook.
  if (opts?.onSpeechEnd) {
    (recognition as unknown as { onspeechend: (() => void) | null }).onspeechend = () => {
      opts.onSpeechEnd?.();
    };
  }

  recognition.onend = () => {
    const wasContinuous = activeContinuous;
    activeRecognition = null;
    if (wasContinuous && !stopRequested) {
      // Auto-restart for hands-free continuous mode (AD-474b).
      _spawnRecognition(onResult, onEnd, onError, continuous, interimResults, opts);
      return;
    }
    onEnd?.();
  };

  activeRecognition = recognition;
  recognition.start();
}

export function stopListening(): void {
  stopRequested = true;
  activeContinuous = false;
  // AD-760: flush any pending accumulator BEFORE aborting so the
  // caller sees the partial transcript.
  if (gapForwardOnResult !== null || gapAccumulator) {
    _flushGapAccumulator();
  }
  _abortActiveRecognition();
  // BF-318: release the arbiter lease so queued waiters (wake-word)
  // can resume.
  if (activeLease !== null) {
    const lease = activeLease;
    activeLease = null;
    _arbiterRelease(lease);
  }
}

/** Internal: abort the current SR instance without touching the
 *  arbiter lease. Used for both stopListening and preemption. */
function _abortActiveRecognition(): void {
  if (activeRecognition) {
    try { activeRecognition.abort(); } catch { /* already stopped */ }
    activeRecognition = null;
  }
}

export function isListening(): boolean {
  return activeRecognition !== null;
}
