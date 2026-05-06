/* Voice input — browser SpeechRecognition API (zero dependencies) */

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

/** Options for startListening. AD-474b adds continuous-listen + interim-results;
 *  AD-474c adds onSpeechEnd VAD callback. All fields optional; defaults preserve
 *  pre-AD-474 behavior verbatim (single-shot recognition, en-US, final results only). */
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

  _spawnRecognition(onResult, onEnd, onError, continuous, interimResults, opts);
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
      onResult(lastFinal);
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
  if (activeRecognition) {
    try { activeRecognition.abort(); } catch { /* already stopped */ }
    activeRecognition = null;
  }
}

export function isListening(): boolean {
  return activeRecognition !== null;
}
