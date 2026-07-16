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
let _ownershipGeneration = 0;

type ControllerOwner = Readonly<{
  generation: number;
  opts: ArmOptions;
  agentId: string;
}>;

type PendingAcquisition = Readonly<{
  generation: number;
  opts: ArmOptions;
  agentId: string;
  invalidatedGeneration: number;
}>;

type PendingInactiveNotification = Readonly<{
  epoch: number;
  invalidatedGeneration: number;
  opts: ArmOptions;
}>;

let _pendingAcquisition: PendingAcquisition | null = null;
let _inactiveNotificationEpoch = 0;
let _pendingInactiveNotification: PendingInactiveNotification | null = null;
const _stateListeners: Set<(s: ConversationState) => void> = new Set();

// Approximate frame cadence used to translate ms tuning knobs into
// frame counts for the Schmitt detector. voiceActivity emits one
// frame per 30 ms (480 samples @ 16 kHz). Keep in sync with
// ``voiceActivity.FRAME_SAMPLES``.
const _FRAME_MS = 30;

function _owns(owner: ControllerOwner): boolean {
  return (
    owner.generation === _ownershipGeneration
    && owner.opts === _opts
    && owner.agentId === _agentId
  );
}

function _attachBargeInForAgentSpeaking(owner: ControllerOwner): boolean {
  if (!_owns(owner)) return false;
  if (_bargeInDisarm !== null) return true;
  if (owner.opts.bargeInEnabled === false) return true;
  const onset = owner.opts.bargeInOnsetConfidence ?? 0.80;
  const offset = owner.opts.bargeInOffsetConfidence ?? 0.40;
  const debounceMs = owner.opts.bargeInDebounceMs ?? 250;
  const releaseMs = owner.opts.bargeInReleaseMs ?? 100;
  const amplitudeFloorDb = owner.opts.bargeInAmplitudeFloorDb ?? -45;
  const cooldownMs = owner.opts.bargeInCooldownMs ?? 500;
  const debounceFrames = Math.max(1, Math.round(debounceMs / _FRAME_MS));
  const releaseFrames = Math.max(1, Math.round(releaseMs / _FRAME_MS));
  if (!_owns(owner)) return false;
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
      _onVadSpeechStart(owner);
    },
  });
  if (_owns(owner)) return true;
  _detachBargeIn();
  return false;
}

function _detachBargeIn(): void {
  if (_bargeInDisarm !== null) {
    try { _bargeInDisarm(); } catch { /* Tier-2 */ }
    _bargeInDisarm = null;
  }
}

function _setState(owner: ControllerOwner, next: ConversationState): boolean {
  if (!_owns(owner)) return false;
  if (_state === next) return true;
  const prev = _state;
  _state = next;
  // AD-760: attach/detach Schmitt-trigger barge-in detector on
  // agent_speaking entry/exit. Detector subscribes to the PCM tap and
  // delivers Silero score + RMS-derived dBFS via per-frame onFrame.
  if (next === 'agent_speaking') {
    if (!_attachBargeInForAgentSpeaking(owner)) return false;
  } else if (prev === 'agent_speaking') {
    _detachBargeIn();
  }
  if (!_owns(owner)) return false;
  owner.opts.onStateChange?.(next);
  if (!_owns(owner)) return false;
  for (const l of [..._stateListeners]) {
    if (!_owns(owner)) return false;
    try {
      l(next);
    } catch {
      // Tier-2.
    }
    if (!_owns(owner)) return false;
  }
  return true;
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

/** Arm the controller. Every accepted non-empty arm replaces prior ownership. */
export function armConversationMode(opts: ArmOptions): () => void {
  if (!opts.agentId) {
    // No active agent — no-op. Caller is expected to invoke arm only
    // when a DM thread is active.
    return () => undefined;
  }

  _ownershipGeneration += 1;
  const generation = _ownershipGeneration;
  _pendingAcquisition = null;
  _teardownInvalidatedOwner({
    releaseLease: true,
    notifyInactive: _state !== 'inactive',
    expectedGeneration: generation,
  });
  if (_ownershipGeneration !== generation) return () => undefined;
  _opts = opts;
  _agentId = opts.agentId;
  const owner: ControllerOwner = {
    generation,
    opts,
    agentId: opts.agentId,
  };
  const lease = _arbiterAcquire({
    holder: 'conversation',
    priority: PRIORITY_CONVERSATION,
    onAcquired: (grantedLease) => {
      if (!_owns(owner)) {
        if (
          _pendingAcquisition?.generation === owner.generation
          && _pendingAcquisition.opts === owner.opts
          && _pendingAcquisition.agentId === owner.agentId
          && _pendingAcquisition.invalidatedGeneration === _ownershipGeneration
        ) {
          _pendingAcquisition = null;
        }
        _arbiterRelease(grantedLease);
        return;
      }
      _lease = grantedLease;
      _wireSubscriptionsAndListen(owner);
    },
    onPreempted: () => {
      if (!_owns(owner)) return;
      // A higher-priority holder (press-to-talk) grabbed the mic.
      // The arbiter already invalidated this lease, so do not release it.
      _ownershipGeneration += 1;
      const invalidatedGeneration = _ownershipGeneration;
      _pendingAcquisition = null;
      _teardownInvalidatedOwner({
        releaseLease: false,
        notifyInactive: false,
        expectedGeneration: invalidatedGeneration,
      });
      _enqueuePreemptedInactiveNotification(owner.opts, invalidatedGeneration);
    },
  });
  if (lease === null && _owns(owner)) {
    // Queued: invalidate the controller activation while preserving only the
    // exact callback bookkeeping needed to release a later stale grant.
    _ownershipGeneration += 1;
    _pendingAcquisition = {
      generation: owner.generation,
      opts: owner.opts,
      agentId: owner.agentId,
      invalidatedGeneration: _ownershipGeneration,
    };
    _opts = null;
    _agentId = null;
    _lease = null;
    _state = 'inactive';
  }
  return () => {
    if (_owns(owner)) _disarmOwned(owner);
  };
}

function _wireSubscriptionsAndListen(owner: ControllerOwner): void {
  if (!_owns(owner)) return;
  // STT.
  _whisperUnsubArmed = armWhisperStt();
  if (!_owns(owner)) return;
  _transcriptUnsub = _onWhisperTranscript((text: string) => {
    if (!_owns(owner)) return;
    void _onTranscript(owner, text);
  });
  if (!_owns(owner)) return;
  // VAD speech_start / speech_end.
  const vadHandler: PcmTapHandler = {
    // The controller doesn't need the raw PCM stream — whisperStt
    // already taps it. We only care about VAD events.
    onFrame: () => undefined,
    onSpeechStart: () => _onVadSpeechStart(owner),
    // onSpeechEnd not required — whisperStt's transcription pipeline
    // fires onTranscript when the utterance closes.
  };
  _vadUnsub = _subscribePcm(vadHandler);
  if (!_owns(owner)) return;
  _setState(owner, 'listening');
}

function _onVadSpeechStart(owner: ControllerOwner): void {
  if (!_owns(owner)) return;
  if (_state === 'agent_speaking') {
    // Barge-in: user spoke over the agent's TTS reply.
    const bargeOn = owner.opts.bargeInEnabled !== false;
    if (bargeOn) {
      if (!_owns(owner)) return;
      try {
        _stopSpeaking();
      } catch {
        // Tier-2.
      }
      if (!_owns(owner)) return;
      _cancelSilenceTimer(owner);
      if (!_owns(owner)) return;
      _setState(owner, 'listening');
    }
  }
  // In other states VAD speech_start is informational only.
}

async function _onTranscript(owner: ControllerOwner, text: string): Promise<void> {
  if (!_owns(owner)) return;
  const trimmed = (text || '').trim();
  if (!trimmed) return;
  if (!_owns(owner) || _state === 'inactive') return;
  // AD-985: meeting-wide echo gate. When a crew member is mid-TTS the mic must
  // not transcribe their speech, so drop the transcript. A dropped echo is
  // ROOM ACTIVITY, so refresh the silence timer to keep the session alive
  // through a long crew turn (otherwise a >30s crew discussion would release
  // the mic mid-meeting). The 1:1 path passes no canListen and is unaffected.
  if (owner.opts.canListen) {
    if (!_owns(owner)) return;
    const canListen = owner.opts.canListen();
    if (!_owns(owner)) return;
    if (!canListen) {
      _refreshSilenceTimer(owner);
      return;
    }
  }
  if (!_owns(owner)) return;
  _cancelSilenceTimer(owner);
  if (!_owns(owner)) return;
  owner.opts.onTranscript?.(trimmed);
  if (!_owns(owner)) return;
  if (!_setState(owner, 'transcribing')) return;
  if (!_owns(owner)) return;
  const history = owner.opts.historyProvider?.() ?? [];
  if (!_owns(owner)) return;
  if (!_setState(owner, 'submitted')) return;
  if (!_owns(owner)) return;
  if (owner.opts.submitTranscript) {
    try {
      await owner.opts.submitTranscript(trimmed, history);
      if (!_owns(owner)) return;
    } catch {
      if (!_owns(owner)) return;
      _setState(owner, 'listening');
      return;
    }
    if (!_owns(owner)) return;
    _enterSilencePending(owner);
    return;
  }
  try {
    const resp = await fetch(`/api/agent/${owner.agentId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: trimmed, history }),
    });
    if (!_owns(owner)) return;
    if (!resp.ok) {
      _setState(owner, 'listening');
      return;
    }
    const json = await resp.json();
    if (!_owns(owner)) return;
    const replyText = String(json?.response ?? json?.reply ?? json?.message ?? '');
    if (!replyText) {
      _setState(owner, 'listening');
      return;
    }
    // Hand off to agent_speaking BEFORE the callback so the caller's muted
    // path may synchronously invoke markAgentReplyComplete(). That completed
    // silence_pending state is authoritative and must survive callback return.
    if (!_setState(owner, 'agent_speaking')) return;
    if (!_owns(owner)) return;
    owner.opts.onAgentReply?.(replyText);
    // The caller's audible TTS path is expected
    // to invoke ``markAgentReplyComplete()`` when the speech finishes
    // (or immediately when TTS is disabled, in which case the
    // controller proceeds straight to silence_pending).
  } catch {
    if (!_owns(owner)) return;
    // Network error — fall back to listening so the operator can
    // try again. Honest-degrade per Tier-2.
    _setState(owner, 'listening');
  }
}

/** Signal that the agent's TTS reply has finished. Starts the
 *  silence-pending timer; expiry disarms the controller. */
export function markAgentReplyComplete(): void {
  const owner = _currentOwner();
  if (owner === null || _state !== 'agent_speaking') return;
  _enterSilencePending(owner);
}

/** Enter ``silence_pending`` and start the 30s release timer. Shared by the
 *  1:1 reply-complete path (markAgentReplyComplete) and the AD-985 group path
 *  (after a fan-out submit). On expiry the controller disarms; the BF-318
 *  ``onReleased`` then lets wake-word resume. */
function _enterSilencePending(owner: ControllerOwner): void {
  if (!_owns(owner)) return;
  if (!_setState(owner, 'silence_pending')) return;
  if (!_owns(owner)) return;
  _cancelSilenceTimer(owner);
  if (!_owns(owner)) return;
  const timeoutMs = owner.opts.silenceTimeoutMs ?? 30000;
  _silenceTimer = setTimeout(() => {
    if (!_owns(owner)) return;
    _silenceTimer = null;
    if (_state === 'silence_pending') _disarmOwned(owner);
  }, timeoutMs);
}

/** AD-985: restart the silence timer if (and only if) one is pending, so room
 *  activity (a dropped crew-TTS echo) keeps an open meeting mic alive. No-op
 *  when not in ``silence_pending`` (e.g. mid-listen) — there is no timer to
 *  refresh and the controller is already live. */
function _refreshSilenceTimer(owner: ControllerOwner): void {
  if (!_owns(owner) || _state !== 'silence_pending' || _silenceTimer === null) return;
  _enterSilencePending(owner);
}

function _cancelSilenceTimer(owner?: ControllerOwner): void {
  if (owner && !_owns(owner)) return;
  if (_silenceTimer !== null) {
    clearTimeout(_silenceTimer);
    _silenceTimer = null;
  }
}

export function disarmConversationMode(): void {
  const owner = _currentOwner();
  if (owner === null) {
    if (_pendingAcquisition !== null) _ownershipGeneration += 1;
    _pendingAcquisition = null;
    return;
  }
  _disarmOwned(owner);
}

function _currentOwner(): ControllerOwner | null {
  if (_opts === null || _agentId === null) return null;
  return { generation: _ownershipGeneration, opts: _opts, agentId: _agentId };
}

function _disarmOwned(owner: ControllerOwner): void {
  if (!_owns(owner)) return;
  _ownershipGeneration += 1;
  const invalidatedGeneration = _ownershipGeneration;
  _pendingAcquisition = null;
  _teardownInvalidatedOwner({
    releaseLease: true,
    notifyInactive: true,
    expectedGeneration: invalidatedGeneration,
  });
}

function _notifyInactive(opts: ArmOptions | null, expectedGeneration: number): void {
  if (_ownershipGeneration !== expectedGeneration) return;
  opts?.onStateChange?.('inactive');
  if (_ownershipGeneration !== expectedGeneration) return;
  for (const listener of [..._stateListeners]) {
    if (_ownershipGeneration !== expectedGeneration) return;
    try { listener('inactive'); } catch { /* Tier-2 */ }
    if (_ownershipGeneration !== expectedGeneration) return;
  }
}

function _enqueuePreemptedInactiveNotification(
  opts: ArmOptions,
  invalidatedGeneration: number,
): void {
  _inactiveNotificationEpoch += 1;
  const job: PendingInactiveNotification = {
    epoch: _inactiveNotificationEpoch,
    invalidatedGeneration,
    opts,
  };
  _pendingInactiveNotification = job;
  queueMicrotask(() => {
    if (
      _pendingInactiveNotification !== job
      || job.epoch !== _inactiveNotificationEpoch
    ) return;
    _pendingInactiveNotification = null;
    if (job.opts.onStateChange) {
      job.opts.onStateChange('inactive');
      if (
        job.epoch !== _inactiveNotificationEpoch
        || _ownershipGeneration !== job.invalidatedGeneration
      ) return;
    }
    for (const listener of [..._stateListeners]) {
      if (
        job.epoch !== _inactiveNotificationEpoch
      ) return;
      try { listener('inactive'); } catch { /* Tier-2 */ }
      if (_ownershipGeneration !== job.invalidatedGeneration) return;
    }
  });
}

function _teardownInvalidatedOwner(options: {
  releaseLease: boolean;
  notifyInactive: boolean;
  expectedGeneration: number;
}): void {
  const oldOpts = _opts;
  const oldLease = _lease;
  const shouldNotifyInactive = options.notifyInactive && _state !== 'inactive';
  const hadControllerResources = (
    oldOpts !== null
    || oldLease !== null
    || _whisperUnsubArmed !== null
    || _transcriptUnsub !== null
    || _vadUnsub !== null
    || _bargeInDisarm !== null
    || _silenceTimer !== null
    || _state !== 'inactive'
  );
  _cancelSilenceTimer();
  _detachBargeIn();
  if (_whisperUnsubArmed) {
    try { _whisperUnsubArmed(); } catch { /* Tier-2 */ }
    _whisperUnsubArmed = null;
  } else if (hadControllerResources) {
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
  _state = 'inactive';
  if (options.releaseLease && oldLease !== null) {
    _arbiterRelease(oldLease);
  }
  if (shouldNotifyInactive) {
    _notifyInactive(oldOpts, options.expectedGeneration);
  }
}

/** Test seam — full module reset. */
export function _resetConversationControllerForTests(): void {
  _ownershipGeneration += 1;
  _inactiveNotificationEpoch += 1;
  _pendingInactiveNotification = null;
  const invalidatedGeneration = _ownershipGeneration;
  _pendingAcquisition = null;
  _teardownInvalidatedOwner({
    releaseLease: true,
    notifyInactive: false,
    expectedGeneration: invalidatedGeneration,
  });
  _stateListeners.clear();
}
