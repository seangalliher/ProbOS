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
  onspeechend?: (() => void) | null;
  start(): void;
  abort(): void;
  stop(): void;
}

export function isSpeechRecognitionSupported(): boolean {
  return typeof window !== 'undefined' &&
    ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);
}

let activeListening: ListeningInvocation | null = null;

export interface ListeningHandle {
  cancel(): void;
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
): ListeningHandle {
  const invocation = new ListeningInvocation(onResult, onEnd, onError, opts);
  if (!isSpeechRecognitionSupported()) {
    invocation.cancel();
    onError?.('Speech recognition not supported in this browser');
    return invocation;
  }
  const previous = activeListening;
  activeListening = invocation;
  previous?.stopAndFlush();
  if (activeListening === invocation) invocation.acquire();
  else invocation.cancel();
  return invocation;
}

class ListeningInvocation implements ListeningHandle {
  private live = true;
  private recognition: SpeechRecognitionInstance | null = null;
  private lease: Lease | null = null;
  private pendingText = '';
  private gapTimer: ReturnType<typeof setTimeout> | null = null;
  private gapGeneration = 0;
  private callbacks: {
    onResult: (text: string) => void;
    onEnd?: () => void;
    onError?: (error: string) => void;
    options?: ListenOptions;
  } | null;

  constructor(onResult: (text: string) => void, onEnd?: () => void,
    onError?: (error: string) => void, options?: ListenOptions) {
    this.callbacks = { onResult, onEnd, onError, options };
  }

  get listening(): boolean {
    return this.live && this.recognition !== null;
  }

  acquire(): void {
    const options = this.callbacks?.options;
    _arbiterAcquire({
      holder: options?.holder ?? 'press_to_talk',
      priority: options?.priority ?? PRIORITY_PRESS_TO_TALK,
      onAcquired: lease => {
        if (!this.live || activeListening !== this) {
          _arbiterRelease(lease);
          return;
        }
        this.lease = lease;
        this.spawn();
      },
      onPreempted: holder => {
        const callbacks = this.callbacks;
        this.cancel();
        callbacks?.options?.onPreempted?.(holder);
        callbacks?.onEnd?.();
      },
    });
  }

  cancel(): void {
    if (!this.live) return;
    this.live = false;
    this.clearGap();
    this.pendingText = '';
    this.callbacks = null;
    if (activeListening === this) activeListening = null;
    const recognition = this.recognition;
    this.recognition = null;
    const lease = this.lease;
    this.lease = null;
    if (recognition) {
      this.detach(recognition);
      try { recognition.abort(); } catch { /* already stopped */ }
    }
    if (lease) _arbiterRelease(lease);
  }

  stopAndFlush(): void {
    const callback = this.callbacks?.onResult;
    const text = this.pendingText.trim();
    this.cancel();
    if (text && callback) {
      try { callback(text); } catch { /* legacy gap delivery is best-effort */ }
    }
  }

  private clearGap(): void {
    if (this.gapTimer !== null) clearTimeout(this.gapTimer);
    this.gapTimer = null;
    this.gapGeneration += 1;
  }

  private detach(recognition: SpeechRecognitionInstance): void {
    recognition.onresult = null;
    recognition.onerror = null;
    recognition.onend = null;
    recognition.onspeechend = null;
  }

  private spawn(): void {
    if (!this.live || activeListening !== this) return;
    const options = this.callbacks?.options;
    const continuous = options?.continuous === true;
    const gapMs = options?.endOfSpeechGapMs;
    const gapEnabled = continuous && typeof gapMs === 'number' && gapMs > 0;
    let recognition: SpeechRecognitionInstance;
    try {
      const Constructor = window.SpeechRecognition || window.webkitSpeechRecognition!;
      recognition = new Constructor();
      this.recognition = recognition;
      recognition.continuous = continuous;
      recognition.interimResults = options?.interimResults === true;
      recognition.lang = 'en-US';
      const current = (): boolean => this.live && activeListening === this && this.recognition === recognition;
      recognition.onresult = event => {
        if (!current()) return;
        const results = event.results as unknown as ArrayLike<{ 0: { transcript: string }; isFinal?: boolean }>;
        let latest: string | null = null;
        for (let index = 0; index < results.length; index += 1) {
          const result = results[index];
          if (result.isFinal !== false) latest = result[0].transcript;
        }
        if (latest === null) return;
        if (!gapEnabled) {
          this.callbacks?.onResult(latest);
          return;
        }
        const piece = latest.trim();
        if (piece) this.pendingText = this.pendingText ? `${this.pendingText} ${piece}` : piece;
        this.clearGap();
        const generation = this.gapGeneration;
        this.gapTimer = setTimeout(() => {
          if (!this.live || activeListening !== this || this.gapGeneration !== generation) return;
          this.clearGap();
          const text = this.pendingText.trim();
          this.pendingText = '';
          if (text) this.callbacks?.onResult(text);
        }, gapMs);
      };
      recognition.onerror = event => {
        if (current() && event.error !== 'aborted') this.callbacks?.onError?.(event.error);
      };
      if (options?.onSpeechEnd) {
        recognition.onspeechend = () => {
          if (current()) this.callbacks?.options?.onSpeechEnd?.();
        };
      }
      recognition.onend = () => {
        if (!current()) return;
        this.detach(recognition);
        this.recognition = null;
        if (continuous) this.spawn();
        else {
          const onEnd = this.callbacks?.onEnd;
          this.cancel();
          onEnd?.();
        }
      };
      recognition.start();
    } catch (error) {
      const onError = this.callbacks?.onError;
      this.cancel();
      onError?.(error instanceof Error ? error.message : 'Speech recognition failed to start');
    }
  }
}

export function stopListening(): void {
  activeListening?.stopAndFlush();
}

export function isListening(): boolean {
  return activeListening?.listening ?? false;
}
