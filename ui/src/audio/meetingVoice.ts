/** AD-921: Sequenced meeting voice. When a meeting is active, the per-agent
 *  replies returned by the AD-914 fan-out (already in AD-915 facilitator
 *  order) are SPOKEN one at a time -- each in its own per-agent voice (AD-718)
 *  -- with NO talk-over. The speaking agent_id is passed straight to
 *  ``speakResponse`` (AD-718/AD-738), whose ``onSpeechEvent`` stream the
 *  speaker's ``CrewVRM`` already consumes (filtered by agentId, CrewVRM.tsx)
 *  to drive viseme lip-sync (AD-721b). This module builds NO TTS and NO
 *  lip-sync engine -- it is purely a sequencer over existing primitives.
 *
 *  ``speakResponse`` dispatches without blocking and fires a matching
 *  ``'end'`` ``onSpeechEvent`` when the utterance finishes. We await that
 *  event per utterance (the BF-290 subscribe-before-speak one-shot pattern),
 *  correlated on the BF-767 ``utterance_id`` that ``speakResponse`` returns.
 *  When TTS is unavailable ``speakResponse`` no-ops and never fires ``'end'``;
 *  a per-utterance safety timeout resolves so the queue always drains (the
 *  meeting still shows avatars + transcript). */

import type { VoiceProfile, SpeechEvent } from './voice';

/** One entry of the AD-914 ``per_agent_replies`` array. */
export interface PerAgentReply {
  agent_id: string;
  callsign?: string;
  text: string;
}

/** Dependency-injected so the sequencer is unit-testable without WebAudio. */
export interface MeetingVoiceDeps {
  /** = ``speakResponse``: (text, profile, agent_id). Returns the BF-767
   *  ``utterance_id`` stamped on that call's own ``SpeechEvent``s, or
   *  ``undefined`` when no engine exists. ``void`` stays in the union so a
   *  stand-in that does not model ids degrades to agent attribution instead of
   *  failing to typecheck. */
  speak: (text: string, profile: VoiceProfile | undefined, agentId: string) => number | void;
  /** = ``onSpeechEvent``: subscribe to TTS lifecycle; returns an unsubscribe fn. */
  subscribe: (fn: (e: SpeechEvent) => void) => () => void;
  /** Resolve an agent's per-agent VoiceProfile (AD-718). ``undefined`` => the
   *  global default voice (still emotion-modulated by agent_id inside
   *  ``speakResponse``). */
  resolveProfile: (agentId: string) => Promise<VoiceProfile | undefined>;
  /** Called with the agent_id immediately before each utterance and ``null``
   *  after it ends. Drives the hook's ``speakingAgentId`` (AD-923 seam). */
  onSpeakingChange?: (agentId: string | null) => void;
  /** BF-621: called with the FULL reply right BEFORE its utterance begins, so
   *  the caller can show a "{callsign} is speaking…" label. Distinct from
   *  ``onSpeakingChange`` (which carries only the agent_id, for the avatar
   *  lip-sync indicator). */
  onUtteranceStart?: (reply: PerAgentReply) => void;
  /** BF-621: called with the FULL reply right AFTER its utterance completes
   *  (the ``'end'`` event or the safety timeout) and AFTER
   *  ``onSpeakingChange(null)`` — so the caller can reveal the reply text once
   *  it has been spoken ("hear, then see"). NOT called for a reply skipped by
   *  ``shouldContinue`` (a superseded batch). */
  onUtteranceEnd?: (reply: PerAgentReply) => void;
  /** Strip markdown for cleaner speech (= ``stripMarkdownForSpeech``). */
  strip?: (s: string) => string;
  /** Abort check evaluated before each utterance -- lets a newer batch
   *  supersede an in-flight one (no talk-over across Captain re-sends). */
  shouldContinue?: () => boolean;
  /** Safety cap (ms) for the case where ``'end'`` never fires (TTS
   *  unavailable). When omitted, a LENGTH-PROPORTIONAL cap is computed from
   *  the reply text (BF-615) so a long reply is never cut off mid-utterance.
   *  ``0`` disables the timeout (tests). */
  utteranceTimeoutMs?: number;
}

// BF-615: the per-utterance safety timeout is the fallback for when the TTS
// ``'end'`` event never fires (engine unavailable). It was a FIXED 20s, but a
// long crew reply takes well over 20s to speak — so the timer fired mid-speech,
// advanced the queue, and the NEXT ``speakResponse`` called
// ``speechSynthesis.cancel()``, truncating the still-speaking prior utterance
// (the Captain heard every reply cut off except the last, which had no
// successor to cancel it). The fix: scale the cap with the reply length at a
// conservative (slow) speech rate plus generous headroom, floored at the old
// 20s. Real speech still resolves early via the ``'end'`` event; the cap only
// ever fires when ``'end'`` genuinely never arrives.
export const UTTERANCE_TIMEOUT_FLOOR_MS = 20000; // floor (short replies / TTS-unavailable)
export const UTTERANCE_MS_PER_WORD = 460;        // ~130 wpm — conservative SLOW TTS rate
export const UTTERANCE_HEADROOM = 1.5;           // safety multiple over estimated speech time

export interface UtteranceTimeoutOptions {
  floorMs?: number;
  msPerWord?: number;
  headroom?: number;
}

/** BF-615: length-proportional per-utterance safety timeout (ms). Estimates
 *  speech duration from the word count at a conservative slow TTS rate, applies
 *  headroom, and floors at ``UTTERANCE_TIMEOUT_FLOOR_MS`` so short replies keep
 *  the original 20s net. Pure; empty / non-string text yields the floor. */
export function computeUtteranceTimeout(text: string, opts: UtteranceTimeoutOptions = {}): number {
  const floor = opts.floorMs ?? UTTERANCE_TIMEOUT_FLOOR_MS;
  const perWord = opts.msPerWord ?? UTTERANCE_MS_PER_WORD;
  const headroom = opts.headroom ?? UTTERANCE_HEADROOM;
  const words = typeof text === 'string'
    ? text.trim().split(/\s+/).filter(Boolean).length
    : 0;
  return Math.max(floor, Math.round(words * perWord * headroom));
}

/** Speak ONE reply and resolve when its matching ``'end'`` fires (or the
 *  safety timeout elapses). Subscribe BEFORE speaking so we never race the
 *  event (BF-290). Never throws. */
function _speakAndWait(
  reply: PerAgentReply,
  profile: VoiceProfile | undefined,
  deps: MeetingVoiceDeps,
): Promise<void> {
  return new Promise<void>((resolve) => {
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const finish = (): void => {
      if (settled) return;
      settled = true;
      try { off(); } catch { /* Tier-2: never let teardown break the queue */ }
      if (timer !== null) clearTimeout(timer);
      resolve();
    };
    // BF-862: filled in by the `deps.speak` below, which mints it synchronously.
    let utteranceId: number | undefined;
    const off = deps.subscribe((e: SpeechEvent) => {
      // AD-1291 'dropped' is terminal for THIS wait without being folded into
      // 'end': the utterance never reached the device, so no 'end' is coming.
      // Without it a barge-in that flushes a queued meeting utterance strands
      // the sequencer on its multi-second safety timeout.
      if (e.type !== 'end' && e.type !== 'dropped') return;
      // BF-862: a terminal event must be ATTRIBUTED to advance us. A bare 'end'
      // carrying no agent_id used to match as a wildcard, so the Ship's
      // Computer's unattributed utterance (IntentSurface) satisfied the wait
      // for a crew utterance and started the next speaker over the top of the
      // current one. `utterance_id` is the correct key: it is per-`speak`-call
      // unique, whereas a superseded utterance's terminal 'end' carries the
      // SAME agent_id as the reply that replaced it (BF-767). It is undefined
      // only for a terminal event fired synchronously inside `deps.speak`
      // (before it returned) or when no engine minted one; agent attribution
      // covers that, and is REQUIRED rather than assumed.
      if (utteranceId !== undefined
        ? e.utterance_id !== utteranceId
        : e.agent_id !== reply.agent_id) return;
      finish();
    });
    const timeoutMs = deps.utteranceTimeoutMs ?? computeUtteranceTimeout(reply.text);
    if (timeoutMs > 0) timer = setTimeout(finish, timeoutMs);
    const text = deps.strip ? deps.strip(reply.text) : reply.text;
    try {
      const spoken = deps.speak(text, profile, reply.agent_id);
      if (typeof spoken === 'number') utteranceId = spoken;
    } catch {
      // Tier-2: a throwing speak must not deadlock the queue.
      finish();
    }
  });
}

/** Speak ``replies`` strictly one at a time, in array order (AD-915
 *  facilitator order). Resolves when the queue drains. Never throws. */
export async function speakRepliesSequentially(
  replies: PerAgentReply[],
  deps: MeetingVoiceDeps,
): Promise<void> {
  for (const reply of replies) {
    if (deps.shouldContinue && !deps.shouldContinue()) break;
    const text = (reply?.text ?? '').trim();
    if (!text) continue;
    let profile: VoiceProfile | undefined;
    try {
      profile = await deps.resolveProfile(reply.agent_id);
    } catch {
      profile = undefined; // Tier-2: distinct-voice -> same-voice degrade.
    }
    if (deps.shouldContinue && !deps.shouldContinue()) break;
    deps.onSpeakingChange?.(reply.agent_id);
    deps.onUtteranceStart?.(reply);
    let _spoken = false;
    try {
      await _speakAndWait(reply, profile, deps);
      _spoken = true;
    } finally {
      deps.onSpeakingChange?.(null);
    }
    // BF-621: reveal the text AFTER the utterance completes (and after the
    // "speaking" label is cleared) — "hear, then see." Only when the utterance
    // actually ran; a superseded batch breaks at the top of the next iteration
    // so its later replies are neither spoken nor revealed (correct — stale).
    if (_spoken) deps.onUtteranceEnd?.(reply);
  }
}

/** AD-921: per-agent ``VoiceProfile`` resolver backed by the existing AD-718
 *  ``GET /api/agent/{id}/profile`` endpoint (the same source ProfileChatTab
 *  uses for the host). Caches per agent_id; Tier-2 -- any failure resolves to
 *  ``undefined`` (the agent speaks in the global default voice). ``fetchImpl``
 *  is injectable for tests. */
export function createVoiceProfileResolver(
  fetchImpl: typeof fetch = (typeof fetch === 'function' ? fetch : (async () => { throw new Error('no fetch'); }) as unknown as typeof fetch),
): (agentId: string) => Promise<VoiceProfile | undefined> {
  // AD-972: cache the in-flight PROMISE (not just the resolved value) so a
  // prewarm at meeting-open and the per-utterance resolve dedupe to ONE fetch
  // even when they race. A resolved entry stays cached (no re-fetch); a failed
  // fetch resolves to ``undefined`` and is cached as the default-voice degrade.
  const cache = new Map<string, Promise<VoiceProfile | undefined>>();
  return (agentId: string): Promise<VoiceProfile | undefined> => {
    const cached = cache.get(agentId);
    if (cached) return cached;
    const pending = (async (): Promise<VoiceProfile | undefined> => {
      try {
        const resp = await fetchImpl(`/api/agent/${agentId}/profile`, { method: 'GET' });
        if (resp.ok) {
          const data = await resp.json();
          if (data && data.voiceProfile) return data.voiceProfile as VoiceProfile;
        }
      } catch {
        // Tier-2: any failure -> default voice.
      }
      return undefined;
    })();
    cache.set(agentId, pending);
    return pending;
  };
}
