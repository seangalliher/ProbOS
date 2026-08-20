/**
 * BF-765 / BF-768: the speech claim must outlive the mount, and must be bounded.
 *
 * BF-718 gave the four 1:1 speakers a shared claim so exactly one of them says
 * a given piece of content. The ledger holding it was a `useRef`, so the
 * guarantee lasted exactly as long as one mounted `ProfileChatTab` -- switching
 * profile tabs while an in-flight `sendText` continuation still held the old
 * ledger through its closure handed the new mount a blank one, and both spoke.
 *
 * Making it outlive the mount turns an unbounded map into a real leak, so the
 * two are fixed together: one entry per thread or per-agent buffer ever seen,
 * for the life of the tab.
 */

import { beforeEach, describe, expect, it } from 'vitest';

import {
  SPEECH_LEDGER_SCOPE_CAP,
  SPEECH_SCOPE_CAP,
  claimSpeech,
  createSpeechLedger,
  markScopeSeen,
  resetSharedSpeechLedger,
  sharedSpeechLedger,
} from '../profileTranscript';
import type { AgentProfileMessage } from '../../../store/types';

function agentMsg(text: string, id = text): AgentProfileMessage {
  return { id, role: 'agent', text, timestamp: 0 } as AgentProfileMessage;
}

beforeEach(() => {
  resetSharedSpeechLedger();
});

describe('BF-765: the claim outlives the mount', () => {
  it('returns the same ledger to every caller', () => {
    expect(sharedSpeechLedger()).toBe(sharedSpeechLedger());
  });

  it('a second mount cannot re-claim what the first already spoke', () => {
    // The first mount speaks it.
    expect(claimSpeech(sharedSpeechLedger(), 'thread-1', agentMsg('all clear'))).toBe(true);

    // Remount: the component builds its ledger reference again from scratch.
    const afterRemount = sharedSpeechLedger();

    expect(claimSpeech(afterRemount, 'thread-1', agentMsg('all clear'))).toBe(false);
  });

  it('a fresh per-mount ledger WOULD have spoken twice', () => {
    // The counterfactual, so the test above cannot pass for the wrong reason.
    const first = createSpeechLedger();
    const second = createSpeechLedger();
    expect(claimSpeech(first, 'thread-1', agentMsg('all clear'))).toBe(true);
    expect(claimSpeech(second, 'thread-1', agentMsg('all clear'))).toBe(true);
  });

  it('seenScopes travels with the claims it belongs to', () => {
    const ledger = sharedSpeechLedger();
    expect(markScopeSeen(ledger, 'thread-1')).toBe(true);
    // Remount must NOT report the scope as first-sight again, or the whole
    // transcript re-seeds and a genuine arrival in that window is swallowed.
    expect(markScopeSeen(sharedSpeechLedger(), 'thread-1')).toBe(false);
  });

  it('keeps scopes independent', () => {
    const ledger = sharedSpeechLedger();
    expect(claimSpeech(ledger, 'thread-1', agentMsg('hello'))).toBe(true);
    expect(claimSpeech(ledger, 'thread-2', agentMsg('hello'))).toBe(true);
  });
});

describe('BF-768: the ledger is bounded in both dimensions', () => {
  it('bounds the number of scopes', () => {
    const ledger = createSpeechLedger();
    for (let i = 0; i < SPEECH_LEDGER_SCOPE_CAP + 25; i += 1) {
      claimSpeech(ledger, `thread-${i}`, agentMsg('x'));
    }
    expect(ledger.scopes.size).toBe(SPEECH_LEDGER_SCOPE_CAP);
  });

  it('marking a scope seen also counts against the scope bound', () => {
    const ledger = createSpeechLedger();
    for (let i = 0; i < SPEECH_LEDGER_SCOPE_CAP + 25; i += 1) {
      markScopeSeen(ledger, `thread-${i}`);
    }
    expect(ledger.scopes.size).toBe(SPEECH_LEDGER_SCOPE_CAP);
  });

  it('evicts the seeded flag and the claims TOGETHER', () => {
    // The blocker review found: `scopes` evicted LRU while `seenScopes`
    // evicted FIFO, so at the bound one scope reported seen=false/claims=true
    // and another the reverse. Revisiting the first read history aloud;
    // revisiting the second silently seeded a genuinely new message. One
    // record per scope makes disagreement unrepresentable.
    const ledger = createSpeechLedger();
    for (let i = 0; i < SPEECH_LEDGER_SCOPE_CAP + 1; i += 1) {
      const scope = `scope-${i}`;
      markScopeSeen(ledger, scope);
      claimSpeech(ledger, scope, agentMsg(`msg-${i}`));
    }
    for (const [key, scope] of ledger.scopes) {
      // A retained scope remembers BOTH, an evicted one is simply absent.
      expect(scope.seen, `${key} was retained but forgot it was seeded`).toBe(true);
      expect(scope.keys.size, `${key} was retained but forgot its claims`).toBeGreaterThan(0);
    }
  });
  it('evicts least-recently-USED, not least-recently-created', () => {
    const ledger = createSpeechLedger();
    claimSpeech(ledger, 'old-but-active', agentMsg('first'));

    // Keep touching it while the cap is exceeded by newer scopes.
    for (let i = 0; i < SPEECH_LEDGER_SCOPE_CAP; i += 1) {
      claimSpeech(ledger, `filler-${i}`, agentMsg('x'));
      claimSpeech(ledger, 'old-but-active', agentMsg(`keepalive-${i}`));
    }

    // The scope the Captain keeps returning to must still remember what it
    // spoke; evicting it would make the next arrival speak twice.
    expect(ledger.scopes.has('old-but-active')).toBe(true);
    expect(claimSpeech(ledger, 'old-but-active', agentMsg('first'))).toBe(false);
  });

  it('still bounds keys within one scope', () => {
    const ledger = createSpeechLedger();
    for (let i = 0; i < SPEECH_SCOPE_CAP + 10; i += 1) {
      claimSpeech(ledger, 'thread-1', agentMsg(`msg-${i}`));
    }
    expect(ledger.scopes.get('thread-1')!.keys.size).toBe(SPEECH_SCOPE_CAP);
  });

  it('an evicted scope forgets, which is the accepted cost of the bound', () => {
    const ledger = createSpeechLedger();
    claimSpeech(ledger, 'evicted', agentMsg('hello'));
    for (let i = 0; i < SPEECH_LEDGER_SCOPE_CAP + 5; i += 1) {
      claimSpeech(ledger, `filler-${i}`, agentMsg('x'));
    }
    expect(ledger.scopes.has('evicted')).toBe(false);
    // Stated rather than hidden: past the bound the claim is gone and the
    // content could be spoken again. The bound is the decision.
    expect(claimSpeech(ledger, 'evicted', agentMsg('hello'))).toBe(true);
  });
});
