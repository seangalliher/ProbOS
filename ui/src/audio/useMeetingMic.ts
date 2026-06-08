/** AD-922: meeting-scoped push-to-talk capture lifecycle. A pure-DI React hook
 *  that arms the existing offline STT (``transformersStt`` -- the whisperStt
 *  module is deprecated, BF-301) for ONE VAD-bounded utterance and hands the
 *  finished transcript to ``submit``. ProfileChatTab passes ``sendText``, which
 *  already self-routes to the AD-914 group fan-out when the thread has >=2 crew
 *  (AD-917) -- so the meeting mic needs NO new dispatch branch.
 *
 *  Opens NO new mic: the app already opened the stream app-wide via
 *  ``startVoiceActivity`` (App.tsx); ``armTransformersStt`` only taps it. The
 *  capture is meeting-gated and echo-gated (refuses to arm while an agent is
 *  speaking, so the Captain's mic never transcribes the agents' TTS) and
 *  honest-degrades to typing when STT/mic is unavailable or permission is
 *  denied. The transcript listener is one-shot + torn down on every exit path
 *  (BF-319: the per-agent mic and this mic share the global
 *  ``onTransformersTranscript`` set, so a straggler must not fan two submits),
 *  and the gate inputs are read live via refs (BF-292) so the hook stays
 *  reference-stable when mounted from ProfileChatTab's send callback. */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  armTransformersStt,
  disarmTransformersStt,
  onTransformersTranscript,
} from './transformersStt';
import { isSpeechRecognitionSupported } from './speechInput';
import { getMicPermissionState, onMicPermissionState } from './wakeWord';

export interface UseMeetingMicOptions {
  /** True when the active thread's ``metadata.meeting_active`` is set. */
  meetingActive: boolean;
  /** True while ANY meeting agent is mid-utterance
   *  (``useMeetingVoice.speakingAgentId != null``). Echo gate: the mic refuses
   *  to arm while agents speak (BF-300, meeting-wide). */
  speaking: boolean;
  /** Where a finished transcript goes. ProfileChatTab passes ``sendText``,
   *  which self-routes to the AD-914 group fan-out when the thread has >=2
   *  crew (AD-917). */
  submit: (text: string) => void | Promise<void>;
  /** Test seams -- default to the real audio modules. */
  deps?: {
    arm?: () => () => void;
    disarm?: () => void;
    onTranscript?: (l: (t: string) => void) => () => void;
    isSupported?: () => boolean;
    micState?: () => string;
  };
}

export interface UseMeetingMicResult {
  /** True while a capture is armed and waiting for the VAD-bounded transcript. */
  capturing: boolean;
  /** True when voice input is possible at all (STT/SR available). When false
   *  the consumer hides the button -- the Captain types (no regression). */
  supported: boolean;
  /** True when the mic is unusable right now (permission denied/unavailable) --
   *  drives the muted visual. */
  blocked: boolean;
  /** Click handler: arm if idle, cancel if capturing. No-ops (honest-degrade)
   *  when gated off (not in a meeting, an agent is speaking, STT unavailable,
   *  or permission denied). */
  toggleCapture: () => void;
}

function _isBlocked(state: string): boolean {
  return state === 'denied' || state === 'unavailable';
}

export function useMeetingMic(opts: UseMeetingMicOptions): UseMeetingMicResult {
  const arm = opts.deps?.arm ?? armTransformersStt;
  const disarm = opts.deps?.disarm ?? disarmTransformersStt;
  const onTranscript = opts.deps?.onTranscript ?? onTransformersTranscript;
  const readMicState = opts.deps?.micState ?? getMicPermissionState;
  const isSupported = opts.deps?.isSupported ?? isSpeechRecognitionSupported;

  // SR availability is a sufficient proxy for "the browser can do voice input
  // at all". Read once per render; when false the consumer hides the button.
  const supported = isSupported();

  const [capturing, setCapturing] = useState(false);
  const [blocked, setBlocked] = useState<boolean>(() => _isBlocked(readMicState()));

  // BF-292: read every gate input live via a ref so ``toggleCapture`` stays a
  // reference-stable callback (it is mounted imperatively from ProfileChatTab's
  // send path and must not churn that callback's dependency array).
  const meetingActiveRef = useRef(opts.meetingActive);
  const speakingRef = useRef(opts.speaking);
  const submitRef = useRef(opts.submit);
  const supportedRef = useRef(supported);
  const blockedRef = useRef(blocked);
  const capturingRef = useRef(capturing);
  // BF-319: one-shot transcript teardown handle. The per-agent mic and this
  // mic both subscribe the global ``onTransformersTranscript`` set, so a
  // straggler transcript fanning to two live listeners would call submit twice.
  const transcriptUnsubRef = useRef<(() => void) | null>(null);

  useEffect(() => { meetingActiveRef.current = opts.meetingActive; }, [opts.meetingActive]);
  useEffect(() => { speakingRef.current = opts.speaking; }, [opts.speaking]);
  useEffect(() => { submitRef.current = opts.submit; }, [opts.submit]);
  useEffect(() => { supportedRef.current = supported; }, [supported]);
  useEffect(() => { blockedRef.current = blocked; }, [blocked]);
  useEffect(() => { capturingRef.current = capturing; }, [capturing]);

  // Keep ``blocked`` live: a late grant/deny updates the muted visual.
  // ``onMicPermissionState`` fires the current state synchronously on subscribe.
  useEffect(() => {
    const unsub = onMicPermissionState((s) => { setBlocked(_isBlocked(s)); });
    return unsub;
  }, []);

  const toggleCapture = useCallback((): void => {
    // Second click while armed -> cancel: one-shot teardown, no submit.
    if (capturingRef.current) {
      if (transcriptUnsubRef.current) {
        try { transcriptUnsubRef.current(); } catch { /* Tier-2 */ }
        transcriptUnsubRef.current = null;
      }
      try { disarm(); } catch { /* Tier-2 */ }
      setCapturing(false);
      return;
    }
    // Gate (honest-degrade -- all no-op): not in a meeting, an agent is
    // speaking (echo gate), STT unavailable, or mic permission denied.
    if (
      !meetingActiveRef.current ||
      speakingRef.current ||
      !supportedRef.current ||
      blockedRef.current
    ) {
      return;
    }
    // Arm: subscribe a one-shot transcript listener stored on a ref. On the
    // FIRST event tear the listener down BEFORE submitting (BF-319) so a
    // straggler can neither re-enter nor reach a sibling listener, then submit
    // the trimmed text if non-empty.
    const unsub = onTranscript((text: string) => {
      try { unsub(); } catch { /* Tier-2 */ }
      transcriptUnsubRef.current = null;
      try { disarm(); } catch { /* Tier-2 */ }
      setCapturing(false);
      const trimmed = (text ?? '').trim();
      if (trimmed) { void submitRef.current(trimmed); }
    });
    transcriptUnsubRef.current = unsub;
    try { arm(); } catch { /* Tier-2 */ }
    setCapturing(true);
  }, [arm, disarm, onTranscript]);

  // Unmount cleanup: if still armed, unsub + disarm (no setState on teardown).
  useEffect(() => {
    return () => {
      if (transcriptUnsubRef.current) {
        try { transcriptUnsubRef.current(); } catch { /* Tier-2 */ }
        transcriptUnsubRef.current = null;
      }
      try { disarm(); } catch { /* Tier-2 */ }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { capturing, supported, blocked, toggleCapture };
}
