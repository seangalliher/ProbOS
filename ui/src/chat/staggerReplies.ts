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

/** Tunable timing constants for the typing beat. Exported so the values are a
 *  single source of truth (and trivially adjustable) rather than scattered
 *  magic numbers. */
export const TYPING_BASE_MS = 480;       // floor: even one word reads as a beat
export const TYPING_PER_CHAR_MS = 14;    // ~ a brisk composing cadence
export const TYPING_MAX_MS = 2400;       // cap so a long reply never stalls the room
export const TYPING_MIN_MS = 360;        // hard minimum (very short replies)

export interface TypingDelayOptions {
  baseMs?: number;
  perCharMs?: number;
  maxMs?: number;
  minMs?: number;
}

/** Length-proportional typing delay (ms), clamped to ``[minMs, maxMs]``. Pure.
 *  A non-finite / empty text yields the minimum. */
export function computeTypingDelay(text: string, opts: TypingDelayOptions = {}): number {
  const base = opts.baseMs ?? TYPING_BASE_MS;
  const perChar = opts.perCharMs ?? TYPING_PER_CHAR_MS;
  const max = opts.maxMs ?? TYPING_MAX_MS;
  const min = opts.minMs ?? TYPING_MIN_MS;
  const len = typeof text === 'string' ? text.trim().length : 0;
  const raw = base + perChar * len;
  return Math.max(min, Math.min(max, raw));
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
  /** Override the per-reply delay (tests). Default: ``computeTypingDelay``. */
  delayFor?: (reply: StaggerReply) => number;
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
  const delayFor = deps.delayFor ?? ((r: StaggerReply) => computeTypingDelay(r.text));
  try {
    for (const reply of replies) {
      if (!cont()) return;
      const text = typeof reply?.text === 'string' ? reply.text : '';
      if (!text) continue;
      const callsign = typeof reply?.callsign === 'string' ? reply.callsign : '';
      try {
        deps.setTyping({ agentId: reply.agent_id, callsign });
        await deps.sleep(delayFor(reply));
      } catch {
        // Tier-2: a sleep/indicator failure must not drop the reply.
      }
      if (!cont()) return;
      try {
        deps.appendReply(reply);
      } catch {
        // Tier-2: one reply's render failure must not break the queue.
      }
    }
  } finally {
    // The indicator must never be left stuck on after the queue drains/aborts.
    try { deps.setTyping(null); } catch { /* swallow — teardown best-effort */ }
  }
}
