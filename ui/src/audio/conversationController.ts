/**
 * AD-747 — ConversationController (always-on natural conversation mode).
 *
 * Wires together five subsystems shipped in prior waves to give the
 * Captain a hands-free duplex with the active DM agent:
 *
 *   - BF-318  speechRecognitionArbiter   (mic lease at PRIORITY_CONVERSATION)
 *   - AD-705a whisperStt                  (VAD-bounded local transcription)
 *   - AD-733c-7-5 voiceActivity           (Silero VAD speech_start/_end)
 *   - voice.ts stopSpeaking               (barge-in)
 *   - WardRoom DM /api/agent/{id}/chat    (transcript submission)
 *
 * State machine:
 *
 *   inactive
 *     → arm + arbiter grant ⇒ listening
 *   listening
 *     → VAD speech_start    ⇒ listening  (no state change; visual cue)
 *     → VAD speech_end +
 *       whisper transcript  ⇒ transcribing
 *   transcribing
 *     → fetch POST          ⇒ submitted
 *   submitted
 *     → agent reply + TTS   ⇒ agent_speaking
 *     → TTS onended         ⇒ silence_pending (30s timer)
 *   agent_speaking
 *     → VAD speech_start +
 *       barge_in_enabled    ⇒ listening   (voice.stopSpeaking() fires)
 *   silence_pending
 *     → 30s expiry          ⇒ inactive   (lease released; wake-word
 *                                          resumes via BF-318 onReleased)
 *     → user speech         ⇒ listening
 *
 * Press-to-talk preempts the conversation through the standard
 * BF-318 priority order. ``onPreempted`` triggers a clean disarm; the
 * caller may re-arm on the next active-agent signal.
 *
 * Privacy invariant (AD-733c-7): no audio bytes leave the browser.
 * The controller only sees transcript text; the only outgoing payload
 * is the text body of /api/agent/{id}/chat.
 */

import {
  acquire as _arbiterAcquire,
  release as _arbiterRelease,
  PRIORITY_CONVERSATION,
  type Lease,
} from './speechRecognitionArbiter';
import {
  armTransformersStt as armWhisperStt,
  disarmTransformersStt as disarmWhisperStt,
  onTransformersTranscript as _onWhisperTranscript,
} from './transformersStt';
import {
  subscribePcm as _subscribePcm,
  type PcmTapHandler,
} from './voiceActivity';
import { stopSpeaking as _stopSpeaking } from './voice';
import { attachBargeInDetector as _attachBargeInDetector } from './bargeInDetector';

export type ConversationState =
  | 'inactive'
  | 'listening'
  | 'transcribing'
  | 'submitted'
  | 'agent_speaking'
  | 'silence_pending';

export interface ArmOptions {
  agentId: string;
  /** Optional history payload to include with the chat POST.
   *  When omitted, history is the empty list. */
  historyProvider?: () => Array<{ role: string; content: string }>;
  /** Fires whenever the controller transitions state. */
  onStateChange?: (state: ConversationState) => void;
  /** Fires on every transcript before submission (HXI hook for the
   *  transcript-preview pill — forward marker AD-747-10). */
  onTranscript?: (text: string) => void;
  /** Fires when the controller posts a chat reply (HXI hook). */
  onAgentReply?: (text: string) => void;
  /** AD-985: group-meeting submission override. When provided, a completed
   *  utterance is handed to this callback INSTEAD of the built-in 1:1
   *  ``/api/agent/{id}/chat`` POST — the meeting path routes it to the group
   *  fan-out (``POST /api/threads/{id}/messages``). The crew's replies are
   *  spoken externally (``useMeetingVoice``), so the controller does NOT manage
   *  ``agent_speaking``/``onAgentReply`` in this mode: after the submit
   *  resolves it goes straight to ``silence_pending`` (mic stays live, gated by
   *  ``canListen``) to await the Captain's next turn. Fire-and-forget is fine —
   *  the controller only awaits the submit's own completion, not the replies. */
  submitTranscript?: (
    text: string,
    history: Array<{ role: string; content: string }>,
  ) => Promise<void>;
  /** AD-985: echo-gate predicate, checked before a transcript is accepted.
   *  Returns ``false`` when the mic must NOT listen right now — in a meeting
   *  that is ``speakingAgentId != null`` (any crew member mid-TTS), so the mic
   *  never transcribes the crew's own speech (the AD-922 meeting-wide echo
   *  gate). A dropped echo refreshes the silence timer (room activity keeps the
   *  session alive). When omitted, all transcripts are accepted (the 1:1 path,
   *  which has its own BF-300 host-filtered guard). */
  canListen?: () => boolean;
  /** Defaults; tests override. */
  silenceTimeoutMs?: number;
  bargeInEnabled?: boolean;
  /** AD-760: Schmitt-trigger barge-in detector tuning. All optional;
   *  defaults applied at the controller read site so existing callers
   *  remain source-compatible. See bargeInDetector.ts for semantics. */
  bargeInOnsetConfidence?: number;
  bargeInOffsetConfidence?: number;
  bargeInDebounceMs?: number;
  bargeInReleaseMs?: number;
  bargeInAmplitudeFloorDb?: number;
  bargeInCooldownMs?: number;
}

// Module state (single active controller per browser session).
let _state: ConversationState = 'inactive';
let _agentId: string | null = null;
let _lease: Lease | null = null;
let _whisperUnsubArmed: (() => void) | null = null;
let _transcriptUnsub: (() => void) | null = null;
let _vadUnsub: (() => void) | null = null;
let _silenceTimer: ReturnType<typeof setTimeout> | null = null;
let _opts: ArmOptions | null = null;
let _bargeInDisarm: (() => void) | null = null;
const _stateListeners: Set<(s: ConversationState) => void> = new Set();

// Approximate frame cadence used to translate ms tuning knobs into
// frame counts for the Schmitt detector. voiceActivity emits one
// frame per 30 ms (480 samples @ 16 kHz). Keep in sync with
// ``voiceActivity.FRAME_SAMPLES``.
const _FRAME_MS = 30;

function _attachBargeInForAgentSpeaking(): void {
  if (_bargeInDisarm !== null) return;
  if (_opts?.bargeInEnabled === false) return;
  const onset = _opts?.bargeInOnsetConfidence ?? 0.80;
  const offset = _opts?.bargeInOffsetConfidence ?? 0.40;
  const debounceMs = _opts?.bargeInDebounceMs ?? 250;
  const releaseMs = _opts?.bargeInReleaseMs ?? 100;
  const amplitudeFloorDb = _opts?.bargeInAmplitudeFloorDb ?? -45;
  const cooldownMs = _opts?.bargeInCooldownMs ?? 500;
  const debounceFrames = Math.max(1, Math.round(debounceMs / _FRAME_MS));
  const releaseFrames = Math.max(1, Math.round(releaseMs / _FRAME_MS));
  _bargeInDisarm = _attachBargeInDetector({
    onsetConfidence: onset,
    offsetConfidence: offset,
    debounceFrames,
    releaseFrames,
    amplitudeFloorDb,
    cooldownMs,
    onBargeIn: () => {
      // SRP: detector fires the user-spoke event; the controller's
      // existing _onVadSpeechStart branch handles state transition +
      // _stopSpeaking + silence-timer cancel.
      _onVadSpeechStart();
    },
  });
}

function _detachBargeIn(): void {
  if (_bargeInDisarm !== null) {
    try { _bargeInDisarm(); } catch { /* Tier-2 */ }
    _bargeInDisarm = null;
  }
}

function _setState(next: ConversationState): void {
  if (_state === next) return;
  const prev = _state;
  _state = next;
  // AD-760: attach/detach Schmitt-trigger barge-in detector on
  // agent_speaking entry/exit. Detector subscribes to the PCM tap and
  // delivers Silero score + RMS-derived dBFS via per-frame onFrame.
  if (next === 'agent_speaking') {
    _attachBargeInForAgentSpeaking();
  } else if (prev === 'agent_speaking') {
    _detachBargeIn();
  }
  _opts?.onStateChange?.(next);
  for (const l of _stateListeners) {
    try {
      l(next);
    } catch {
      // Tier-2.
    }
  }
}

export function getConversationState(): ConversationState {
  return _state;
}

export function onConversationState(
  listener: (state: ConversationState) => void,
): () => void {
  _stateListeners.add(listener);
  return () => {
    _stateListeners.delete(listener);
  };
}

/** Arm the controller. Idempotent on the same agentId. */
export function armConversationMode(opts: ArmOptions): () => void {
  if (!opts.agentId) {
    // No active agent — no-op. Caller is expected to invoke arm only
    // when a DM thread is active.
    return () => undefined;
  }
  if (_agentId === opts.agentId && _state !== 'inactive') {
    // Already armed for this agent.
    return disarmConversationMode;
  }
  // If armed for a different agent, disarm first.
  if (_state !== 'inactive') {
    disarmConversationMode();
  }
  _opts = opts;
  _agentId = opts.agentId;
  const lease = _arbiterAcquire({
    holder: 'conversation',
    priority: PRIORITY_CONVERSATION,
    onAcquired: () => {
      _wireSubscriptionsAndListen();
    },
    onPreempted: () => {
      // A higher-priority holder (press-to-talk) grabbed the mic.
      // Clean teardown; caller's onStateChange sees inactive.
      _teardownInternal();
    },
  });
  if (lease !== null) {
    _lease = lease;
    // _grantSync already fired onAcquired which wired things.
  } else {
    // Queued — the arbiter has a higher-priority holder. Wait.
    // (For Wave 180, we treat queueing as a synonym for failure to arm:
    // the controller stays inactive and the caller can retry.)
    _opts = null;
    _agentId = null;
  }
  return disarmConversationMode;
}

function _wireSubscriptionsAndListen(): void {
  // STT.
  _whisperUnsubArmed = armWhisperStt();
  _transcriptUnsub = _onWhisperTranscript((text: string) => {
    void _onTranscript(text);
  });
  // VAD speech_start / speech_end.
  const vadHandler: PcmTapHandler = {
    // The controller doesn't need the raw PCM stream — whisperStt
    // already taps it. We only care about VAD events.
    onFrame: () => undefined,
    onSpeechStart: () => _onVadSpeechStart(),
    // onSpeechEnd not required — whisperStt's transcription pipeline
    // fires onTranscript when the utterance closes.
  };
  _vadUnsub = _subscribePcm(vadHandler);
  _setState('listening');
}

function _onVadSpeechStart(): void {
  if (_state === 'agent_speaking') {
    // Barge-in: user spoke over the agent's TTS reply.
    const bargeOn = _opts?.bargeInEnabled !== false;
    if (bargeOn) {
      try {
        _stopSpeaking();
      } catch {
        // Tier-2.
      }
      _cancelSilenceTimer();
      _setState('listening');
    }
  }
  // In other states VAD speech_start is informational only.
}

async function _onTranscript(text: string): Promise<void> {
  const trimmed = (text || '').trim();
  if (!trimmed) return;
  if (_state === 'inactive') return;
  // AD-985: meeting-wide echo gate. When a crew member is mid-TTS the mic must
  // not transcribe their speech, so drop the transcript. A dropped echo is
  // ROOM ACTIVITY, so refresh the silence timer to keep the session alive
  // through a long crew turn (otherwise a >30s crew discussion would release
  // the mic mid-meeting). The 1:1 path passes no canListen and is unaffected.
  if (_opts?.canListen && !_opts.canListen()) {
    _refreshSilenceTimer();
    return;
  }
  // Cancel any pending silence timer the moment new user speech
  // arrives — keeps the conversation alive while there's activity.
  _cancelSilenceTimer();
  _opts?.onTranscript?.(trimmed);
  _setState('transcribing');
  const agentId = _agentId;
  if (!agentId) {
    _setState('listening');
    return;
  }
  const history = _opts?.historyProvider?.() ?? [];
  _setState('submitted');
  // AD-985: group-meeting path — hand the utterance to the injected submit
  // (the AD-914 group fan-out via sendText) instead of the 1:1 chat POST. The
  // crew's replies are spoken by useMeetingVoice, so the controller does not
  // enter agent_speaking; it goes to silence_pending so the mic stays live
  // (echo-gated) for the Captain's next turn, with the 30s release.
  if (_opts?.submitTranscript) {
    try {
      await _opts.submitTranscript(trimmed, history);
    } catch {
      // Honest-degrade: network/submit error -> back to listening.
      _setState('listening');
      return;
    }
    _enterSilencePending();
    return;
  }
  try {
    const resp = await fetch(`/api/agent/${agentId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: trimmed, history }),
    });
    if (!resp.ok) {
      _setState('listening');
      return;
    }
    const json = await resp.json().catch(() => ({}));
    const replyText = String(json?.reply ?? json?.message ?? '');
    if (replyText) {
      _opts?.onAgentReply?.(replyText);
    }
    // Hand off to agent_speaking; the caller's TTS path is expected
    // to invoke ``markAgentReplyComplete()`` when the speech finishes
    // (or immediately when TTS is disabled, in which case the
    // controller proceeds straight to silence_pending).
    _setState('agent_speaking');
  } catch {
    // Network error — fall back to listening so the operator can
    // try again. Honest-degrade per Tier-2.
    _setState('listening');
  }
}

/** Signal that the agent's TTS reply has finished. Starts the
 *  silence-pending timer; expiry disarms the controller. */
export function markAgentReplyComplete(): void {
  if (_state !== 'agent_speaking') return;
  _enterSilencePending();
}

/** Enter ``silence_pending`` and start the 30s release timer. Shared by the
 *  1:1 reply-complete path (markAgentReplyComplete) and the AD-985 group path
 *  (after a fan-out submit). On expiry the controller disarms; the BF-318
 *  ``onReleased`` then lets wake-word resume. */
function _enterSilencePending(): void {
  _setState('silence_pending');
  _cancelSilenceTimer();
  const timeoutMs = _opts?.silenceTimeoutMs ?? 30000;
  _silenceTimer = setTimeout(() => {
    _silenceTimer = null;
    if (_state === 'silence_pending') {
      disarmConversationMode();
    }
  }, timeoutMs);
}

/** AD-985: restart the silence timer if (and only if) one is pending, so room
 *  activity (a dropped crew-TTS echo) keeps an open meeting mic alive. No-op
 *  when not in ``silence_pending`` (e.g. mid-listen) — there is no timer to
 *  refresh and the controller is already live. */
function _refreshSilenceTimer(): void {
  if (_state !== 'silence_pending' || _silenceTimer === null) return;
  _enterSilencePending();
}

function _cancelSilenceTimer(): void {
  if (_silenceTimer !== null) {
    clearTimeout(_silenceTimer);
    _silenceTimer = null;
  }
}

export function disarmConversationMode(): void {
  if (_state === 'inactive') return;
  if (_lease !== null) {
    const lease = _lease;
    _lease = null;
    _arbiterRelease(lease);
  }
  _teardownInternal();
}

function _teardownInternal(): void {
  _cancelSilenceTimer();
  _detachBargeIn();
  if (_whisperUnsubArmed) {
    try { _whisperUnsubArmed(); } catch { /* Tier-2 */ }
    _whisperUnsubArmed = null;
  } else {
    // Defensive: disarm whisper module-level state in case armWhisperStt
    // was idempotent and returned a no-op disarm.
    try { disarmWhisperStt(); } catch { /* Tier-2 */ }
  }
  if (_transcriptUnsub) {
    try { _transcriptUnsub(); } catch { /* Tier-2 */ }
    _transcriptUnsub = null;
  }
  if (_vadUnsub) {
    try { _vadUnsub(); } catch { /* Tier-2 */ }
    _vadUnsub = null;
  }
  _opts = null;
  _agentId = null;
  _lease = null;
  _setState('inactive');
}

/** Test seam — full module reset. */
export function _resetConversationControllerForTests(): void {
  _cancelSilenceTimer();
  _detachBargeIn();
  if (_lease !== null) {
    try { _arbiterRelease(_lease); } catch { /* Tier-2 */ }
  }
  _whisperUnsubArmed = null;
  _transcriptUnsub = null;
  _vadUnsub = null;
  _opts = null;
  _agentId = null;
  _lease = null;
  _state = 'inactive';
  _stateListeners.clear();
}
