/** BF-765: the shared speech ledger, in a deliberately IMPORTLESS module.
 *
 *  This exists separately from `profileTranscript` for one reason: the global
 *  vitest setup has to reset it between test cases, and `setupFiles` is
 *  evaluated BEFORE the test module. Importing `profileTranscript` there
 *  evaluated its own static imports ahead of a test file's `vi.mock`, which
 *  defeated the hoisting and broke an unrelated `loadThreadMessages` test.
 *
 *  So: no imports here, ever. Anything added to this file must stay
 *  dependency-free or the setup import becomes unsafe again.
 */

/** One scope's state. Claims and the seeded flag live in ONE record on
 *  purpose: they answer the same question and must be evicted together.
 *
 *  Review measured the alternative at the bound -- claims in an LRU `Map` and
 *  the seeded flag in a FIFO `Set` disagreed, so revisiting one scope read
 *  history aloud and revisiting another silently seeded a genuinely new
 *  message. Two structures cannot be kept in step by comment. */
export interface SpeechScope {
  keys: Set<string>;
  seen: boolean;
}

/** Per-scope memory of what has already been decided about. A scope is one
 *  thread, or the per-agent buffer for a 1:1 that has no thread yet. Keeping
 *  them separate matters: a late response from one thread must not wipe the
 *  state of the thread the Captain is now looking at. */
export interface SpeechLedger {
  scopes: Map<string, SpeechScope>;
}

export function createSpeechLedger(): SpeechLedger {
  return { scopes: new Map<string, SpeechScope>() };
}

/** ONE ledger for the app, not one per mounted component.
 *
 *  The claim exists so exactly one of the four 1:1 speakers says a given piece
 *  of content. A `useRef` scoped that guarantee to a single mount, so switching
 *  profile tabs while an in-flight `sendText` continuation still held the old
 *  ledger through its closure gave the new mount a blank one -- and both spoke.
 *  A claim that does not outlive the mount is not a claim. */
let sharedLedger: SpeechLedger | null = null;

export function sharedSpeechLedger(): SpeechLedger {
  if (sharedLedger === null) sharedLedger = createSpeechLedger();
  return sharedLedger;
}

/** Test seam. Module state would otherwise leak between test cases: a reply
 *  spoken in one case is already claimed in the next. Called from the global
 *  vitest setup, because ~40 test files reach this surface and resetting them
 *  one at a time missed one (found only under shuffled ordering). */
export function resetSharedSpeechLedger(): void {
  sharedLedger = null;
}
