/** BF-928 (#1666): the first transcript load of a scope in a browser session is history, whatever triggered it.
 *
 * `markScopeLoaded` is the shared ledger's record of that: it answers true once per scope (the first load that
 * lands) and false after. It is separate from `markScopeSeen`, which the speech effect uses up the first time it
 * SEES a scope, when the list is usually still empty because the transcript loads asynchronously.
 *
 * The function is read from the module namespace, through a cast, so that this file type-checks and loads before
 * it exists; the cases that need it are `built`, which is `it.fails` until BF-928 M2 sets it to `it`. With
 * BF928_RUNXFAIL=1 they run as ordinary cases and each stops at the call. Synthetic scope names only.
 */
import { describe, it, expect } from 'vitest';
import * as transcript from '../profileTranscript';
import {
  SPEECH_LEDGER_SCOPE_CAP, createSpeechLedger, markScopeSeen, type SpeechLedger,
} from '../profileTranscript';

const built = process.env.BF928_RUNXFAIL === '1' ? it : it.fails;

function markScopeLoaded(ledger: SpeechLedger, scopeKey: string): boolean {
  const fn = (transcript as unknown as {
    markScopeLoaded?: (ledger: SpeechLedger, scopeKey: string) => boolean;
  }).markScopeLoaded;
  if (fn === undefined) throw new Error('markScopeLoaded is not exported by profileTranscript yet');
  return fn(ledger, scopeKey);
}

describe('BF-928: the ledger records the first load that lands for a scope', () => {
  built('answers true for the first load of a scope and false after', () => {
    const ledger = createSpeechLedger();
    expect(markScopeLoaded(ledger, 'thread-a')).toBe(true);
    expect(markScopeLoaded(ledger, 'thread-a')).toBe(false);
    expect(markScopeLoaded(ledger, 'thread-a')).toBe(false);
  });

  built('keeps scopes apart', () => {
    const ledger = createSpeechLedger();
    expect(markScopeLoaded(ledger, 'thread-a')).toBe(true);
    expect(markScopeLoaded(ledger, 'thread-b')).toBe(true);
    expect(markScopeLoaded(ledger, 'thread-a')).toBe(false);
  });

  built('is independent of marking the scope seen, in either order', () => {
    const ledger = createSpeechLedger();
    expect(markScopeSeen(ledger, 'thread-a')).toBe(true);
    expect(markScopeLoaded(ledger, 'thread-a')).toBe(true);
    expect(markScopeLoaded(ledger, 'thread-b')).toBe(true);
    expect(markScopeSeen(ledger, 'thread-b')).toBe(true);
  });

  built('forgets a scope that is evicted at the bound, which then reads as first again', () => {
    const ledger = createSpeechLedger();
    expect(markScopeLoaded(ledger, 'old')).toBe(true);
    for (let i = 0; i < SPEECH_LEDGER_SCOPE_CAP; i += 1) markScopeLoaded(ledger, `filler-${i}`);
    expect(ledger.scopes.has('old')).toBe(false);
    expect(markScopeLoaded(ledger, 'old')).toBe(true);
  });

  it('leaves first sight as it was: true once, then false', () => {
    const ledger = createSpeechLedger();
    expect(markScopeSeen(ledger, 'thread-a')).toBe(true);
    expect(markScopeSeen(ledger, 'thread-a')).toBe(false);
  });
});
