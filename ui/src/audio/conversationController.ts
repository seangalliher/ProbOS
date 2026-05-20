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
  armWhisperStt,
  disarmWhisperStt,
  onTranscript as _onWhisperTranscript,
} from './whisperStt';
import {
  subscribePcm as _subscribePcm,
  type PcmTapHandler,
} from './voiceActivity';
import { stopSpeaking as _stopSpeaking } from './voice';

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
  /** Defaults; tests override. */
  silenceTimeoutMs?: number;
  bargeInEnabled?: boolean;
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
const _stateListeners: Set<(s: ConversationState) => void> = new Set();

function _setState(next: ConversationState): void {
  if (_state === next) return;
  _state = next;
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
  _setState('silence_pending');
  const timeoutMs = _opts?.silenceTimeoutMs ?? 30000;
  _silenceTimer = setTimeout(() => {
    _silenceTimer = null;
    if (_state === 'silence_pending') {
      disarmConversationMode();
    }
  }, timeoutMs);
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
