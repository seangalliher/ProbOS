/* AD-705 (reframed): Wake-word-aware router (pure function).
 *
 * Splits a recognised post-wake transcript into either a system surface
 * (Ship's Computer) or a per-agent surface (`@callsign` path). Pure: no DOM,
 * no fetch, no module state. Fully testable in isolation.
 */

/** Compile-time list of static system wake phrases. Extend cautiously: each
 *  entry is matched as a leading prefix and is also used by the Tier-2
 *  fallback substring matcher in `wakeWord.ts`. Lowercase only. */
export const STATIC_WAKE_PHRASES = ['computer'] as const;

/** Optional filler words permitted before the wake phrase. */
const _LEADING_FILLER_RE = /^\s*(hey|ok|okay)?\s*/i;

export interface WakeRoute {
  surface: 'system' | 'agent';
  /** Present iff `surface === 'agent'`. */
  agentCallsign?: string;
  /** Transcript with the wake-prefix stripped and trimmed. */
  cleanedText: string;
}

/** Minimal structural shape consumed by the router. The store's full Agent
 *  type satisfies this via TypeScript's structural subtyping. */
export interface WakeAgent {
  callsign?: string;
  voice_profile?: { wake_phrase?: string };
}

export interface RouteOptions {
  /** True iff a wake-word ONNX detector already fired for this utterance.
   *  When true, an unaddressed transcript still routes to the system surface
   *  because the wake-word IS the addressing. Defaults to false. */
  postWakeWord?: boolean;
}

function _stripPrefix(transcript: string, phrase: string): string {
  // Match: optional leading filler, the phrase, optional trailing punctuation
  // / whitespace; case-insensitive. Returns the remainder, trimmed.
  const escaped = phrase.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&');
  const re = new RegExp(`^\\s*(?:hey|ok|okay)?\\s*${escaped}[,:!?\\s]+`, 'i');
  return transcript.replace(re, '').trim();
}

function _matchesLeading(transcript: string, phrase: string): boolean {
  if (!phrase) return false;
  const stripped = transcript.replace(_LEADING_FILLER_RE, '').toLowerCase();
  const phraseLower = phrase.toLowerCase();
  if (!stripped.startsWith(phraseLower)) return false;
  // Require a word boundary after the phrase so "computerise" does not match
  // "computer". The boundary is either end-of-string or a non-letter char.
  const next = stripped.charAt(phraseLower.length);
  return next === '' || /[^a-z0-9]/i.test(next);
}

/**
 * Route a recognised transcript to either the system or a specific agent.
 *
 * Routing rules (rule order is significant — system wins ambiguity):
 *   1. Leading filler ("hey", "ok", "okay") permitted before the wake.
 *   2. System wake: transcript starts with any `STATIC_WAKE_PHRASES` entry.
 *   3. Per-agent wake: transcript starts with an agent's `callsign` OR
 *      `voice_profile.wake_phrase` (AD-718c provides the latter).
 *   4. Bare transcript with no recognised prefix:
 *        - if `opts.postWakeWord === true` → system surface (wake-word was
 *          the addressing).
 *        - otherwise → null (discard; not addressed to anyone).
 *   5. Ambiguous (matches both system and an agent prefix): system wins.
 *
 * @returns A `WakeRoute` describing which surface to dispatch to, or `null`
 *   when the transcript is unaddressed and there was no preceding wake fire.
 */
export function routeWakeTranscript(
  transcript: string,
  agents: ReadonlyMap<string, WakeAgent>,
  opts: RouteOptions = {},
): WakeRoute | null {
  const text = (transcript ?? '').trim();
  if (!text) {
    return opts.postWakeWord ? { surface: 'system', cleanedText: '' } : null;
  }

  // Rule 2: system wake takes priority.
  for (const phrase of STATIC_WAKE_PHRASES) {
    if (_matchesLeading(text, phrase)) {
      return { surface: 'system', cleanedText: _stripPrefix(text, phrase) };
    }
  }

  // Rule 3: per-agent wake (callsign or wake_phrase).
  for (const agent of agents.values()) {
    const callsign = agent.callsign ?? '';
    const wakePhrase = agent.voice_profile?.wake_phrase ?? '';
    // Try wake_phrase first (more specific than callsign).
    if (wakePhrase && _matchesLeading(text, wakePhrase)) {
      return {
        surface: 'agent',
        agentCallsign: callsign || wakePhrase,
        cleanedText: _stripPrefix(text, wakePhrase),
      };
    }
    if (callsign && _matchesLeading(text, callsign)) {
      return {
        surface: 'agent',
        agentCallsign: callsign,
        cleanedText: _stripPrefix(text, callsign),
      };
    }
  }

  // Rule 4: bare transcript with no recognised prefix.
  if (opts.postWakeWord) {
    return { surface: 'system', cleanedText: text };
  }
  return null;
}
