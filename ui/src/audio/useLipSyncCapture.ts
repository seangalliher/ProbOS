/** AD-721b-2: React hook to capture utterance audio and resolve a real
 *  viseme schedule from the server-side rhubarb backend (AD-721b-1).
 *
 *  Honest-degrade: when capture is unavailable, the upload fails, or the
 *  server returns ``backend == "heuristic"`` / empty frames, the hook
 *  exposes ``frames: []`` — the consumer (``CrewVRM``) MUST fall through
 *  to ``buildHeuristicTrack`` on an empty schedule. This invariant
 *  preserves the AD-721b v1 contract: speech never stops animating.
 *
 *  The ``enabled`` parameter is preserved on the public API for future
 *  use (e.g. an HXI Captain-facing toggle); production callers today
 *  hardcode ``true`` and rely on the server-side honest-degrade chain.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { onSpeechEvent } from './voice';
import {
  captureUtteranceAudio,
  uploadAudioForLipSync,
  type LipSyncFrame,
  type LipSyncResponse,
} from './lipSyncCapture';

export interface UseLipSyncCaptureOptions {
  /** True when the operator has set ``lipsync.backend = "rhubarb"`` AND the
   *  server endpoint is reachable. Production today hardcodes ``true``;
   *  reserved for a future HXI Captain-facing toggle. */
  enabled: boolean;
  /** Filter to a single agent's utterances. ``undefined`` = capture for all. */
  agentId?: string;
}

export interface UseLipSyncCaptureResult {
  /** Most recent viseme schedule from the server. Empty when:
   *   - capture not yet attempted,
   *   - capture in progress,
   *   - capture failed (use heuristic),
   *   - server returned ``backend == "heuristic"`` (use heuristic),
   *   - server returned ``backend == "disabled"`` (use heuristic). */
  frames: LipSyncFrame[];
  /** True while a capture is in progress. */
  capturing: boolean;
  /** Reset frames to []. CrewVRM should call this on utterance end. */
  reset: () => void;
}

export function useLipSyncCapture(
  opts: UseLipSyncCaptureOptions,
): UseLipSyncCaptureResult {
  const [frames, setFrames] = useState<LipSyncFrame[]>([]);
  const [capturing, setCapturing] = useState(false);
  // Hold the latest enable flag in a ref so the subscription doesn't churn.
  const enabledRef = useRef(opts.enabled);
  const agentIdRef = useRef(opts.agentId);
  useEffect(() => { enabledRef.current = opts.enabled; }, [opts.enabled]);
  useEffect(() => { agentIdRef.current = opts.agentId; }, [opts.agentId]);

  const reset = useCallback(() => setFrames([]), []);

  useEffect(() => {
    let mounted = true;
    const off = onSpeechEvent((e) => {
      if (!enabledRef.current) return;
      if (agentIdRef.current && e.agent_id !== agentIdRef.current) return;
      if (e.type !== 'start') return;
      // BF-293: server-streamed Piper path already injects visemes via
      // injectLipSyncFrames. Capturing the same audio from the browser's
      // WebAudio destination and re-uploading it would (a) duplicate work,
      // (b) produce a webm blob that rhubarb can't process (BF-292), and
      // (c) overwrite the high-quality server visemes with empty/heuristic
      // ones. Only capture when this event came from the BROWSER
      // SpeechSynthesisUtterance fallback path.
      if (e.source !== 'browser') return;
      // Spawn the capture. Do NOT await inside the listener — listeners are
      // synchronous and per voice.ts:42 a thrown exception would be caught
      // and other listeners would still fire.
      setCapturing(true);
      void (async () => {
        try {
          const blob = await captureUtteranceAudio(e.utterance);
          if (!mounted) return;
          if (!blob) {
            return;
          }
          const resp: LipSyncResponse | null = await uploadAudioForLipSync(blob);
          if (!mounted) return;
          if (!resp || resp.backend !== 'rhubarb' || resp.frames.length === 0) {
            return;
          }
          setFrames(resp.frames);
        } finally {
          if (mounted) setCapturing(false);
        }
      })();
    });
    // AD-738: server-streamed TTS path injects frames directly via
    // injectLipSyncFrames; mirror the agentId filter the start-listener uses.
    const offInject = _subscribeInjection((frames, agentId) => {
      if (!enabledRef.current) return;
      if (agentIdRef.current && agentId !== agentIdRef.current) return;
      if (mounted) setFrames(frames);
    });
    return () => {
      mounted = false;
      off();
      offInject();
      // The in-flight async task resolves on its own; mounted=false short-
      // circuits its setState calls. AudioContext cleanup happens in
      // captureUtteranceAudio's finally block.
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { frames, capturing, reset };
}

/** AD-738 — Module-level injection registry. ``voice.ts`` calls
 *  ``injectLipSyncFrames`` after the server returns viseme data; every
 *  mounted ``useLipSyncCapture`` hook with matching (or unset) ``agentId``
 *  receives the frames. Mirrors the ``onSpeechEvent`` listener pattern. */

type FrameInjector = (frames: LipSyncFrame[], agentId?: string) => void;
const _injectListeners = new Set<FrameInjector>();

/** Imperative entry point called from ``voice.ts`` after a successful
 *  ``/api/avatars/tts`` round-trip. NEVER throws. */
export function injectLipSyncFrames(frames: LipSyncFrame[], agentId?: string): void {
  for (const fn of _injectListeners) {
    try { fn(frames, agentId); } catch { /* ignore */ }
  }
}

function _subscribeInjection(fn: FrameInjector): () => void {
  _injectListeners.add(fn);
  return () => { _injectListeners.delete(fn); };
}
