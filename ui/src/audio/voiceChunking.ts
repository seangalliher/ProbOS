/* AD-1071 — Pure sentence-chunking + sequential-queue helpers for TTS
 * pipelining (voice edge). Extracted from voice.ts so the queue/index logic
 * is unit-testable under jsdom WITHOUT mocking Audio/fetch. DEFAULT-OFF:
 * voice.ts only uses these when tts.sentence_pipelining_enabled is true. */

/** Common abbreviations whose trailing period must NOT trigger a sentence
 *  split. v1 keeps this list minimal — the most frequent English titles and
 *  month shorthands. Matched case-insensitively at a word boundary. This is
 *  the "trivially avoidable" abbreviation guard called for in the AD-1071
 *  scope; anything fancier (Latin ``e.g.``/``i.e.`` with internal periods)
 *  is out of scope for v1. */
const _ABBREVIATIONS = [
  'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 'vs', 'etc',
  'inc', 'ltd', 'co', 'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug',
  'sep', 'sept', 'oct', 'nov', 'dec',
];

// Control-char sentinels used only during the split. Reply text never
// contains these, so round-tripping them is safe.
const _SPLIT = '\u0000';
const _ABBR = '\u0001';

/** AD-1071 — Split a finished reply into ordered sentence chunks for
 *  sequential TTS playback.
 *
 *  Heuristic (basic-regex v1):
 *   - split on sentence-final punctuation ``[.!?]`` followed by whitespace,
 *   - preserve order, trim each chunk, drop empties,
 *   - keep a trailing fragment that has no terminal punctuation,
 *   - do NOT split on a small set of common abbreviations (``Dr.``, ``Mr.`` …),
 *   - cap the result at ``maxChunks`` (default 40) by merging the overflow
 *     into the final chunk,
 *   - fall back to ``[text]`` when there is 0-1 sentence, and to ``[]`` for
 *     empty / whitespace-only input.
 *
 *  Pure — no side effects, safe to unit-test under jsdom. */
export function splitIntoSentences(text: string, maxChunks = 40): string[] {
  if (typeof text !== 'string') return [];
  const trimmed = text.trim();
  if (trimmed.length === 0) return [];

  // Protect abbreviation periods so they don't look like sentence ends.
  let guarded = trimmed;
  for (const abbr of _ABBREVIATIONS) {
    // Abbreviations are hardcoded literals — no user input in the pattern.
    const re = new RegExp(`\\b(${abbr})\\.`, 'gi');
    guarded = guarded.replace(re, `$1${_ABBR}`);
  }

  const chunks = guarded
    // Insert a split sentinel after terminal punctuation + whitespace.
    .replace(/([.!?]+)\s+/g, `$1${_SPLIT}`)
    .split(_SPLIT)
    // Restore protected abbreviation periods, then trim.
    .map((s) => s.split(_ABBR).join('.').trim())
    .filter((s) => s.length > 0);

  if (chunks.length <= 1) return [trimmed];
  if (chunks.length > maxChunks) {
    const head = chunks.slice(0, maxChunks - 1);
    const tail = chunks.slice(maxChunks - 1).join(' ');
    return [...head, tail];
  }
  return chunks;
}

/** AD-1071 — Drive a strictly-ordered queue of async side-effects.
 *
 *  Given ``items`` and a ``processOne`` that returns a Promise resolving when
 *  that item's work is DONE (e.g. its audio fired ``ended``), each item is
 *  processed only after the previous one resolves — the sequencing guarantee
 *  behind "next sentence starts after the previous one ends".
 *
 *  Honest-degrade: a ``processOne`` that throws is swallowed here (the
 *  side-effect owner logs) and the queue advances to the next item so one
 *  failed sentence never aborts the whole reply.
 *
 *  ``shouldContinue`` (optional) is checked before each item; returning false
 *  stops the queue early (used by voice.ts to cancel an in-flight reply when
 *  a newer one starts). Returns the number of items processed.
 *
 *  Pure control flow — the Audio/fetch side-effects live entirely inside the
 *  injected ``processOne``, so this is unit-testable with a stub. */
export async function runSentenceQueue(
  items: string[],
  processOne: (item: string, index: number) => Promise<void>,
  shouldContinue?: () => boolean,
): Promise<number> {
  let processed = 0;
  for (let i = 0; i < items.length; i++) {
    if (shouldContinue && !shouldContinue()) break;
    try {
      await processOne(items[i], i);
    } catch {
      // Honest-degrade: keep speaking the rest of the reply.
    }
    processed += 1;
  }
  return processed;
}
