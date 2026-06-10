/** AD-952: human response dynamics — progressive group-reply reveal.
 *
 *  The AD-914 group fan-out returns ALL of a round's ``per_agent_replies``
 *  synchronously in one POST, and the UI used to dump them into the transcript
 *  in a single tight loop — every crew reply appearing at the same instant.
 *  That is the clearest "this is a bot" tell in a group chat: real people don't
 *  all answer in the same millisecond.
 *
 *  This module reveals the replies one at a time, each preceded by a brief
 *  "{callsign} is typing" beat whose length scales with the reply (a short
 *  "Aye." flashes by; a paragraph lingers). It is a PURE, dependency-injected
 *  sequencer over existing primitives — it builds no UI and reads no store
 *  directly, so it is unit-testable with a fake clock. Mirrors the AD-921
 *  ``speakRepliesSequentially`` sequencer shape.
 *
 *  Scope: the NON-meeting text-chat path only. In a live meeting the AD-921
 *  voice sequencer + AD-923 speaking-indicator already pace the crew one at a
 *  time, so the caller keeps the instant text render there (the spoken cadence
 *  is the "human dynamics"); this typing beat is the text-chat equivalent.
 */

/** One entry of the AD-914 ``per_agent_replies`` array (mirrors AD-921's
 *  ``PerAgentReply`` — kept local so this module has no audio dependency). */
export interface StaggerReply {
  agent_id: string;
  callsign?: string;
  text: string;
}

/** AD-960: natural-pacing timing model. Exported as the single source of truth
 *  so the cadence is trivially tunable. Each crew reply is revealed after a
 *  "{callsign} is typing" beat lasting ``PROCESSING + TYPING`` ms:
 *    PROCESSING = think-time (reading the message, deciding to respond)
 *    TYPING     = composing time at ~60 wpm, proportional to the reply length
 *  The indicator is shown for the WHOLE window (no dead air), then clears as the
 *  message lands. The FIRST reply uses the full processing beat (the crew
 *  reading the Captain's message); later cascade reactions use a shorter
 *  inter-turn beat (they were already engaged) so an active back-and-forth
 *  doesn't feel laggy. */
export const PROCESSING_FIRST_MS = 5000;    // first reply: think-time on the Captain's message (~5s)
export const PROCESSING_CASCADE_MS = 2500;  // later reactions in an active exchange
export const TYPING_MS_PER_WORD = 1000;     // 60 wpm = 1 word / 1000ms
export const TYPING_MIN_MS = 800;           // floor so even a one-word reply shows a brief compose beat
export const TYPING_MAX_MS = 9000;          // cap so a long paragraph never makes the room wait minutes

export interface TypingDelayOptions {
  msPerWord?: number;
  maxMs?: number;
  minMs?: number;
}

/** Word-count-proportional typing delay (ms) at ~60 wpm, clamped to
 *  ``[minMs, maxMs]``. Pure. Empty / non-string text yields the minimum. */
export function computeTypingDelay(text: string, opts: TypingDelayOptions = {}): number {
  const perWord = opts.msPerWord ?? TYPING_MS_PER_WORD;
  const max = opts.maxMs ?? TYPING_MAX_MS;
  const min = opts.minMs ?? TYPING_MIN_MS;
  const words = typeof text === 'string'
    ? text.trim().split(/\s+/).filter(Boolean).length
    : 0;
  const raw = words * perWord;
  return Math.max(min, Math.min(max, raw));
}

export interface ProcessingDelayOptions {
  firstMs?: number;
  cascadeMs?: number;
}

/** Think-time (ms) before a reply's typing beat. The first revealed reply
 *  (``index <= 0``) gets the full beat — the crew reading the Captain's
 *  message; later cascade replies get the shorter inter-turn beat. Pure. */
export function computeProcessingDelay(index: number, opts: ProcessingDelayOptions = {}): number {
  const first = opts.firstMs ?? PROCESSING_FIRST_MS;
  const cascade = opts.cascadeMs ?? PROCESSING_CASCADE_MS;
  return index <= 0 ? first : cascade;
}

/** Dependency-injected so the sequencer is unit-testable without React/timers. */
export interface RevealDeps {
  /** Show ("{callsign} is typing") or clear (null) the typing indicator. */
  setTyping: (t: { agentId: string; callsign: string } | null) => void;
  /** Commit one revealed reply to the transcript. */
  appendReply: (reply: StaggerReply) => void;
  /** Await ``ms`` — injectable so tests advance a fake clock. */
  sleep: (ms: number) => Promise<void>;
  /** Abort check evaluated before each reply — lets a thread switch / unmount
   *  stop an in-flight reveal (no replies leak into the wrong transcript). */
  shouldContinue?: () => boolean;
  /** Override the per-reply typing delay (tests). Default: ``computeTypingDelay``. */
  delayFor?: (reply: StaggerReply) => number;
  /** Override the per-reply processing (think-time) delay by revealed-index
   *  (tests). Default: ``computeProcessingDelay``. */
  processingFor?: (index: number) => number;
}

/** Reveal ``replies`` one at a time, in array order (AD-915 facilitator order),
 *  each after a ``setTyping`` beat. Resolves when the queue drains. Never
 *  throws; always clears the typing indicator on exit (even on abort/error).
 *  Empty-text replies are skipped (mirrors the AD-936 render guard). */
export async function revealRepliesProgressively(
  replies: StaggerReply[],
  deps: RevealDeps,
): Promise<void> {
  const cont = deps.shouldContinue ?? (() => true);
  const typingFor = deps.delayFor ?? ((r: StaggerReply) => computeTypingDelay(r.text));
  const processingFor = deps.processingFor ?? ((i: number) => computeProcessingDelay(i));
  // Index among the NON-empty replies actually revealed, so an empty leading
  // reply doesn't consume the (longer) first-reply processing beat.
  let shown = 0;
  try {
    for (const reply of replies) {
      if (!cont()) return;
      const text = typeof reply?.text === 'string' ? reply.text : '';
      if (!text) continue;
      const callsign = typeof reply?.callsign === 'string' ? reply.callsign : '';
      // The "{callsign} is typing" beat covers BOTH the think-time and the
      // composing time, so the indicator is visible for the whole wait (no
      // dead air) and clears the instant the message lands.
      const delay = processingFor(shown) + typingFor(reply);
      shown += 1;
      try {
        deps.setTyping({ agentId: reply.agent_id, callsign });
        await deps.sleep(delay);
      } catch {
        // Tier-2: a sleep/indicator failure must not drop the reply.
      }
      if (!cont()) return;
      // Clear the indicator the instant the message lands, then commit the
      // reply. Two independent guards so a throwing setTyping can't drop the
      // append.
      try { deps.setTyping(null); } catch { /* Tier-2 */ }
      try { deps.appendReply(reply); } catch { /* Tier-2: one render failure must not break the queue */ }
    }
  } finally {
    // The indicator must never be left stuck on after the queue drains/aborts.
    try { deps.setTyping(null); } catch { /* swallow — teardown best-effort */ }
  }
}
