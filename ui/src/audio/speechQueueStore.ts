/** AD-1291 (BF-858): the speech arbiter's queue state, in a deliberately
 *  IMPORTLESS module.
 *
 *  Same reasoning as `speechLedgerStore` (BF-765): the global vitest setup has
 *  to reset this between test cases, `setupFiles` is evaluated BEFORE the test
 *  module, and importing `voice.ts` there would evaluate its static imports
 *  ahead of a test file's `vi.mock('.../audio/voice')` -- defeating the
 *  hoisting in every file that mocks it. Without a reset the leak is worse
 *  than the ledger's was: a test whose fake `speechSynthesis.speak` never
 *  fires `onend` leaves an entry in flight forever, and the NEXT test file's
 *  first utterance queues behind it and is never spoken.
 *
 *  The `VoiceProfile` import below is `import type`, which the compiler erases
 *  entirely, so this module still emits no runtime import. Keep it that way.
 */
import type { VoiceProfile } from './voice';

/** Declared by the CALLER, never computed here.
 *
 *  `interactive` is a live conversational turn; `narration` reads out text that
 *  is already rendered in a visible transcript. The distinction is the
 *  producer's ("what kind of thing am I saying"), which is why it is a
 *  parameter rather than something the arbiter infers -- an arbiter that
 *  classified utterances by inspecting them would be deciding what is worth
 *  saying, which belongs to the BF-718 claim ledger (AD-1231). */
export type SpeechClass = 'narration' | 'interactive';

export interface SpeechQueueEntry {
  id: number;
  text: string;
  profile?: VoiceProfile;
  agent_id?: string;
  emotion?: string;
  speechClass: SpeechClass;
  /** True once the entry has been handed to the device. A started entry is
   *  never dropped -- only queued-but-unstarted ones are, because dropping a
   *  started one would cut audio the Captain is already hearing. */
  started: boolean;
}

export interface SpeechQueueState {
  entries: SpeechQueueEntry[];
  draining: boolean;
  /** Set by the test reset. The drain loop re-reads it every iteration so a
   *  queue abandoned mid-utterance cannot speak into the next test case. */
  abandoned: boolean;
  /** Settles the in-flight wait, so an abandoned drain unwinds immediately
   *  instead of holding its join timer for the full timeout. */
  settleActive: (() => void) | null;
}

/** ONE queue for the document, because there is one audio output device for
 *  the document. A per-component queue cannot see a sibling component's
 *  producers -- `IntentSurface` is mounted for the whole session alongside
 *  `ProfileChatTab`, and both reach this module. */
let _state: SpeechQueueState | null = null;

export function speechQueueState(): SpeechQueueState {
  if (_state === null) {
    _state = { entries: [], draining: false, abandoned: false, settleActive: null };
  }
  return _state;
}

/** Test seam, called from the global vitest setup. Abandons the previous
 *  state rather than merely dropping the reference: a drain loop already
 *  parked on an `'end'` holds its own reference, and would otherwise wake on
 *  its join timer and speak an entry belonging to a finished test. */
export function resetSpeechArbiterForTests(): void {
  const previous = _state;
  _state = null;
  if (previous === null) return;
  previous.abandoned = true;
  previous.entries.length = 0;
  const settle = previous.settleActive;
  previous.settleActive = null;
  if (settle !== null) {
    try { settle(); } catch { /* Tier-2 -- teardown must not throw */ }
  }
}
