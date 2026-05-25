/**
 * AD-733c-7-5 — Browser-side voice-activity detection loop.
 *
 * Opens a dedicated ``getUserMedia({audio: true})`` stream (no shared
 * mic-tap exists in the codebase: ``wakeWord.ts`` uses the
 * ``SpeechRecognition`` transcript API; ``useCameraStream`` requests
 * ``audio: false`` explicitly). Chunks PCM frames at 16 kHz / 30 ms,
 * feeds each frame to a ``VadSession`` (created via
 * ``createVadSession`` from ``silero-vad.ts``), and POSTs to
 * ``/api/perception/voice-activity`` when sustained speech is detected
 * above the configured ``vad_min_speech_duration_ms`` floor.
 *
 * **Privacy invariant (AD-733c-7).** Audio bytes NEVER leave the
 * browser. The POST body carries ONLY ``{agent?, source}`` metadata.
 * Tests assert by string-matching on the captured request body — see
 * ``__tests__/voiceActivity.test.ts``.
 *
 * Honest-degrade paths:
 *
 * - ``createVadSession()`` returns ``null`` (runtime or model absent) →
 *   no-op; ``startVoiceActivity()`` resolves cleanly without armed state.
 * - ``getUserMedia`` rejects → no-op; permission denial is a Captain
 *   choice, not an error.
 * - Endpoint returns 503 (``vad_engagement_enabled=false``) → loop
 *   stops firing further POSTs for the lifetime of this session.
 */
import { createVadSession, type VadSession } from './silero-vad';
import { usePerceptionModeStore } from '../store/usePerceptionModeStore';

interface VadOptions {
  /** Agent ID to engage; omit for runtime-wide engagement. */
  agent?: string;
  /** Sustained speech duration floor (ms) — backend default is 400. */
  minSpeechMs?: number;
  /** Score threshold; default 0.5 mirrors common Silero examples. */
  scoreThreshold?: number;
}

/**
 * AD-705a — PCM tap handler. Subscribers receive raw 16 kHz PCM frames
 * from the existing VAD loop (zero overhead when no subscribers exist).
 * ``onSpeechStart`` / ``onSpeechEnd`` fire on VAD score crossings so a
 * downstream STT consumer can window utterances without opening a
 * second mic stream (DRY per the AD-705a Architect decision).
 *
 * Privacy invariant (AD-733c-7, extended by AD-705a): PCM tap consumers
 * MUST process frames in-browser only. Audio bytes NEVER leave the
 * browser — the tap is internal-only.
 */
export interface PcmTapHandler {
  /** AD-760: ``score`` is the Silero VAD probability for this frame
   *  (0..1), or ``undefined`` when the score isn't available (e.g.
   *  fan-out happened before scoring). Existing subscribers may ignore
   *  the new arg — the signature is backward-compatible. */
  onFrame(frame: Float32Array, sampleRate: number, score?: number): void;
  onSpeechStart?(now: number): void;
  onSpeechEnd?(now: number): void;
}

const SAMPLE_RATE = 16000;
const FRAME_SAMPLES = 480; // 30 ms @ 16 kHz

// Module-scoped subscribers — populated only when the AD-705a STT path
// (or any other consumer) is armed. Empty set = zero overhead.
const _pcmSubscribers: Set<PcmTapHandler> = new Set();
let _speechActiveForTap = false;

interface LoopState {
  stream: MediaStream | null;
  audioCtx: AudioContext | null;
  session: VadSession | null;
  active: boolean;
  // 503 latch: once the endpoint says "off", stop firing for this session.
  endpointOff: boolean;
  // Pending speech window: how long we've been above threshold.
  speechStartedAt: number | null;
  options: {
    agent: string | undefined;
    minSpeechMs: number;
    scoreThreshold: number;
  };
  // Bookkeeping for the next-tick scheduler when we are not using an
  // AudioWorklet (jsdom path).
  pendingTimer: ReturnType<typeof setTimeout> | null;
  // BF-308: production capture chain — null in jsdom / test pumps.
  source: MediaStreamAudioSourceNode | null;
  workletNode: AudioWorkletNode | null;
}

let _state: LoopState | null = null;

/**
 * Internal: drive a single frame through the pipeline. Exported as a
 * test seam so vitest can pump frames deterministically without an
 * actual ``MediaStream``.
 */
export async function _processFrame(buffer: Float32Array, now: number = Date.now()): Promise<void> {
  if (!_state || !_state.active || !_state.session) return;
  if (_state.endpointOff) return;
  const score = await _state.session.score(buffer);
  // AD-705a PCM tap — fan out the raw frame to any subscribers after
  // scoring so AD-760's barge-in detector receives the per-frame
  // Silero score without re-running the model. Subscribers cannot
  // influence the VAD scoring path; the score arg is optional so
  // pre-AD-760 subscribers (e.g. whisperStt) continue to ignore it.
  if (_pcmSubscribers.size > 0) {
    for (const handler of _pcmSubscribers) {
      try {
        handler.onFrame(buffer, SAMPLE_RATE, score);
      } catch {
        // Tier-2: subscriber errors are non-actionable; the VAD path
        // continues regardless.
      }
    }
  }
  // AD-705a speech-boundary fan-out: track threshold crossings
  // independently of the main loop's sustained-speech window so STT
  // consumers can window utterances at the same cadence Silero hears
  // them.
  if (_pcmSubscribers.size > 0) {
    const aboveThreshold = score >= _state.options.scoreThreshold;
    if (aboveThreshold && !_speechActiveForTap) {
      _speechActiveForTap = true;
      for (const handler of _pcmSubscribers) {
        try {
          handler.onSpeechStart?.(now);
        } catch {
          // Tier-2.
        }
      }
    } else if (!aboveThreshold && _speechActiveForTap) {
      _speechActiveForTap = false;
      for (const handler of _pcmSubscribers) {
        try {
          handler.onSpeechEnd?.(now);
        } catch {
          // Tier-2.
        }
      }
    }
  }
  if (score >= _state.options.scoreThreshold) {
    if (_state.speechStartedAt === null) {
      _state.speechStartedAt = now;
      return;
    }
    const heldFor = now - _state.speechStartedAt;
    if (heldFor >= _state.options.minSpeechMs) {
      // Fire once; reset the window so the next event needs to re-arm.
      _state.speechStartedAt = null;
      await _emitSpeechEvent();
    }
  } else {
    _state.speechStartedAt = null;
  }
}

async function _emitSpeechEvent(): Promise<void> {
  if (!_state) return;
  // Update the local Zustand slice immediately so the SPEECH badge
  // flashes regardless of the network round-trip outcome (honest UX —
  // the browser heard the speech even if the backend is offline).
  try {
    usePerceptionModeStore.getState().noteSpeechEvent();
  } catch {
    // Tier-2: missing setter (unit-test seam without the store) is
    // never fatal — the network POST is the load-bearing side effect.
  }
  const body: Record<string, string> = { source: 'vad' };
  if (_state.options.agent) body.agent = _state.options.agent;
  try {
    const resp = await fetch('/api/perception/voice-activity', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (resp.status === 503) {
      _state.endpointOff = true;
    }
  } catch {
    // Tier-2: transient network failure — keep the loop armed. The
    // next sustained speech event will retry.
  }
}

function _scheduleNextTick(): void {
  if (!_state || !_state.active) return;
  if (!_state.audioCtx || !_state.stream) return;
  // AudioWorklet path is the production runtime; jsdom does not
  // implement it. We allow the loop to remain in the armed state with
  // no automatic frame production — tests pump frames via
  // ``_processFrame``. Production wires the worklet at first
  // ``startVoiceActivity`` call (out-of-scope for this AD's tests; the
  // worklet shim is a follow-up — see AD-733c-7-5-1).
  _state.pendingTimer = setTimeout(_scheduleNextTick, 1000);
}

/**
 * Start the voice-activity loop. Idempotent: a second call without a
 * matching ``stopVoiceActivity()`` is a no-op.
 *
 * Returns ``false`` when honest-degraded (runtime absent, mic denied,
 * etc.); returns ``true`` when armed.
 */
export async function startVoiceActivity(opts: VadOptions = {}): Promise<boolean> {
  if (_state && _state.active) return true;
  const options = {
    agent: opts.agent,
    minSpeechMs: opts.minSpeechMs ?? 400,
    scoreThreshold: opts.scoreThreshold ?? 0.5,
  };
  const session = await createVadSession();
  if (!session) {
    return false;
  }
  let stream: MediaStream | null = null;
  try {
    const md = (globalThis as any).navigator?.mediaDevices;
    if (!md || typeof md.getUserMedia !== 'function') {
      session.destroy();
      return false;
    }
    // AD-760: enable echo cancellation, noise suppression, and AGC on
    // the conversation pipeline's single getUserMedia call. First-line
    // defense against TTS bleed driving false barge-ins.
    stream = await md.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
  } catch {
    session.destroy();
    return false;
  }
  // AudioContext is best-effort in jsdom; absent context still leaves the
  // loop in the "armed for ``_processFrame`` test driver" state.
  let audioCtx: AudioContext | null = null;
  try {
    const Ctor = (globalThis as any).AudioContext
      ?? (globalThis as any).webkitAudioContext;
    if (Ctor) audioCtx = new Ctor({ sampleRate: SAMPLE_RATE });
  } catch {
    audioCtx = null;
  }
  // BF-308: wire the production PCM capture chain. The previous code
  // opened the mic + AudioContext but never connected anything, so no
  // PCM ever reached ``_processFrame`` — Silero never scored, no
  // speech_start ever fired, every downstream consumer sat forever
  // waiting for events that never came. The "follow-up shim" comment
  // from AD-733c-7-5-1 referred to this missing wiring; BF-308 ships
  // it. jsdom does not implement AudioWorklet, so addModule throws —
  // we honest-degrade to the test-pump path (``_processFrame`` direct
  // invocation) without disabling the loop.
  let source: MediaStreamAudioSourceNode | null = null;
  let workletNode: AudioWorkletNode | null = null;
  if (audioCtx && stream && typeof (audioCtx as any).audioWorklet?.addModule === 'function') {
    try {
      const workletUrl = (await import('./pcmCaptureWorklet.js?url')).default;
      await (audioCtx as any).audioWorklet.addModule(workletUrl);
      source = audioCtx.createMediaStreamSource(stream);
      workletNode = new AudioWorkletNode(audioCtx, 'pcm-capture');
      workletNode.port.onmessage = (e: MessageEvent) => {
        const frame = e.data as Float32Array;
        if (frame && frame.length > 0) {
          void _processFrame(frame);
        }
      };
      source.connect(workletNode);
      // Worklet must connect to destination for ``process()`` to be
      // pumped reliably across browsers — route through a zero-gain
      // node so no audio is actually played back. Chrome/Edge will
      // pump the worklet without this; Safari/Firefox edge-cases
      // require it. Cheap insurance.
      const muteGain = audioCtx.createGain();
      muteGain.gain.value = 0;
      workletNode.connect(muteGain);
      muteGain.connect(audioCtx.destination);
    } catch (err) {
      // Tier-2: worklet wiring failure leaves the mic stream open + the
      // loop "armed" so test pumps still work, but production capture is
      // dead. Logged so operators can diagnose (BF-307 retro: silent
      // null is operator-hostile).
      // eslint-disable-next-line no-console
      console.warn('[voiceActivity] BF-308: failed to install PCM capture worklet — VAD will not score live audio', err);
      source = null;
      workletNode = null;
    }
  }
  _state = {
    stream,
    audioCtx,
    session,
    active: true,
    endpointOff: false,
    speechStartedAt: null,
    options,
    pendingTimer: null,
    source,
    workletNode,
  };
  _scheduleNextTick();
  return true;
}

/**
 * Stop the loop and release the mic. Idempotent.
 */
export function stopVoiceActivity(): void {
  if (!_state) return;
  _state.active = false;
  if (_state.pendingTimer) {
    clearTimeout(_state.pendingTimer);
    _state.pendingTimer = null;
  }
  // BF-308: tear down the capture chain before closing the context.
  try {
    _state.source?.disconnect();
  } catch {
    // Tier-2.
  }
  try {
    if (_state.workletNode) {
      _state.workletNode.port.onmessage = null;
      _state.workletNode.disconnect();
    }
  } catch {
    // Tier-2.
  }
  try {
    _state.stream?.getTracks().forEach((t) => t.stop());
  } catch {
    // Tier-2: track.stop() throwing during teardown is non-actionable;
    // swallow so unmount does not crash.
  }
  try {
    void _state.audioCtx?.close();
  } catch {
    // Tier-2: same — closing an already-closed context throws.
  }
  try {
    _state.session?.destroy();
  } catch {
    // Tier-2.
  }
  _state = null;
}

/** Test seam — vitest can inspect / reset internal state. */
export function _peekState(): LoopState | null {
  return _state;
}

/** Test seam — exposed so ``vad_min_speech_duration_ms`` defaults align. */
export const _FRAME_SAMPLES = FRAME_SAMPLES;

/**
 * AD-705a — subscribe to the PCM tap. Returns an unsubscribe handle.
 * Frames flow at 16 kHz / 30 ms cadence (the existing VAD loop's
 * native rate). Speech-boundary callbacks fire on Silero threshold
 * crossings. The tap is zero-overhead when no subscribers exist.
 */
export function subscribePcm(handler: PcmTapHandler): () => void {
  _pcmSubscribers.add(handler);
  return () => {
    _pcmSubscribers.delete(handler);
    if (_pcmSubscribers.size === 0) {
      _speechActiveForTap = false;
    }
  };
}

/** Test seam — expose subscriber count for vitest. */
export function _peekPcmSubscriberCount(): number {
  return _pcmSubscribers.size;
}

/** Test seam — clear PCM subscribers between tests. */
export function _resetPcmSubscribers(): void {
  _pcmSubscribers.clear();
  _speechActiveForTap = false;
}
