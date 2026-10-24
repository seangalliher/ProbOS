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

/** BF-918 (#1626) — Drive an ordered queue that prepares ahead of what plays.
 *
 *  AD-1071's queue (`runSentenceQueue`, which this replaces) prepared item N+1 only
 *  after item N had finished PLAYING, so every sentence boundary cost a whole
 *  synthesis. Here:
 *   - `prepare` runs one item at a time, in order: item k starts once k-1 is
 *     prepared, and never more than `lookahead` items ahead of the one playing;
 *   - `play(k)` starts only after `play(k-1)` and `prepare(k)` resolved, so playback
 *     order is item order;
 *   - `shouldContinue` is checked before each play and before each prepare starts;
 *     once it is false nothing more plays, nothing more is prepared, and every
 *     prepared-but-unplayed result goes to `discard` (when it arrives, if it is
 *     still in flight);
 *   - a `prepare` that rejects counts as `null`; a `play` that throws is swallowed
 *     and the queue moves on (AD-1071's honest-degrade).
 *  Lookahead 0 is AD-1071's sequential queue. Returns the number of items played.
 *  Pure control flow: the Audio/fetch side-effects live in the injected callbacks. */
export async function runPrefetchQueue<P>(
  items: string[],
  prepare: (item: string, index: number) => Promise<P | null>,
  play: (prepared: P | null, item: string, index: number) => Promise<void>,
  shouldContinue: () => boolean,
  lookahead = 1,
  discard: (prepared: P | null) => void = () => {},
): Promise<number> {
  const pending: Array<Promise<P | null>> = [];
  const ensure = (k: number): void => {
    if (k >= items.length || pending[k] !== undefined) return;
    const previous: Promise<unknown> = k === 0 ? Promise.resolve(null) : pending[k - 1];
    pending[k] = previous
      .then(() => (shouldContinue() ? prepare(items[k], k) : null))
      .then((prepared) => prepared, () => null);
  };
  let consumed = 0;
  let played = 0;
  try {
    for (let i = 0; i < items.length; i += 1) {
      if (!shouldContinue()) break;
      ensure(i);
      const prepared = await pending[i];
      consumed = i + 1;
      if (!shouldContinue()) { discard(prepared); break; }
      for (let k = i + 1; k <= i + lookahead; k += 1) ensure(k);
      try {
        await play(prepared, items[i], i);
      } catch {
        // Honest-degrade: keep speaking the rest of the reply.
      }
      played += 1;
    }
  } finally {
    for (let k = consumed; k < pending.length; k += 1) {
      const p = pending[k];
      if (p !== undefined) void p.then(discard);
    }
  }
  return played;
}
