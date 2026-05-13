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
    return () => {
      mounted = false;
      off();
      // The in-flight async task resolves on its own; mounted=false short-
      // circuits its setState calls. AudioContext cleanup happens in
      // captureUtteranceAudio's finally block.
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { frames, capturing, reset };
}
