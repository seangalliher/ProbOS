/** AD-921: Sequenced meeting voice. When a meeting is active, the per-agent
 *  replies returned by the AD-914 fan-out (already in AD-915 facilitator
 *  order) are SPOKEN one at a time -- each in its own per-agent voice (AD-718)
 *  -- with NO talk-over. The speaking agent_id is passed straight to
 *  ``speakResponse`` (AD-718/AD-738), whose ``onSpeechEvent`` stream the
 *  speaker's ``CrewVRM`` already consumes (filtered by agentId, CrewVRM.tsx)
 *  to drive viseme lip-sync (AD-721b). This module builds NO TTS and NO
 *  lip-sync engine -- it is purely a sequencer over existing primitives.
 *
 *  ``speakResponse`` is fire-and-forget (returns void) and fires a matching
 *  ``'end'`` ``onSpeechEvent`` when the utterance finishes. We await that
 *  event per utterance (the BF-290 subscribe-before-speak one-shot pattern).
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
  /** = ``speakResponse``: (text, profile, agent_id). Fire-and-forget. */
  speak: (text: string, profile: VoiceProfile | undefined, agentId: string) => void;
  /** = ``onSpeechEvent``: subscribe to TTS lifecycle; returns an unsubscribe fn. */
  subscribe: (fn: (e: SpeechEvent) => void) => () => void;
  /** Resolve an agent's per-agent VoiceProfile (AD-718). ``undefined`` => the
   *  global default voice (still emotion-modulated by agent_id inside
   *  ``speakResponse``). */
  resolveProfile: (agentId: string) => Promise<VoiceProfile | undefined>;
  /** Called with the agent_id immediately before each utterance and ``null``
   *  after it ends. Drives the hook's ``speakingAgentId`` (AD-923 seam). */
  onSpeakingChange?: (agentId: string | null) => void;
  /** Strip markdown for cleaner speech (= ``stripMarkdownForSpeech``). */
  strip?: (s: string) => string;
  /** Abort check evaluated before each utterance -- lets a newer batch
   *  supersede an in-flight one (no talk-over across Captain re-sends). */
  shouldContinue?: () => boolean;
  /** Safety cap (ms) for the case where ``'end'`` never fires (TTS
   *  unavailable). Default 20000. ``0`` disables the timeout (tests). */
  utteranceTimeoutMs?: number;
}

const _DEFAULT_UTTERANCE_TIMEOUT_MS = 20000;

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
    const off = deps.subscribe((e: SpeechEvent) => {
      if (e.type !== 'end') return;
      // A bare 'end' with no agent_id (legacy) matches; an 'end' for a
      // DIFFERENT agent_id must NOT advance this utterance.
      if (e.agent_id && e.agent_id !== reply.agent_id) return;
      finish();
    });
    const timeoutMs = deps.utteranceTimeoutMs ?? _DEFAULT_UTTERANCE_TIMEOUT_MS;
    if (timeoutMs > 0) timer = setTimeout(finish, timeoutMs);
    const text = deps.strip ? deps.strip(reply.text) : reply.text;
    try {
      deps.speak(text, profile, reply.agent_id);
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
    try {
      await _speakAndWait(reply, profile, deps);
    } finally {
      deps.onSpeakingChange?.(null);
    }
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
  const cache = new Map<string, VoiceProfile | undefined>();
  return async (agentId: string): Promise<VoiceProfile | undefined> => {
    if (cache.has(agentId)) return cache.get(agentId);
    let profile: VoiceProfile | undefined;
    try {
      const resp = await fetchImpl(`/api/agent/${agentId}/profile`, { method: 'GET' });
      if (resp.ok) {
        const data = await resp.json();
        if (data && data.voiceProfile) profile = data.voiceProfile as VoiceProfile;
      }
    } catch {
      profile = undefined;
    }
    cache.set(agentId, profile);
    return profile;
  };
}
