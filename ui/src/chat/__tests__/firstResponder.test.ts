// AD-962a: unit tests for the pure first-responder resolver. No store, DOM, or
// fetch — the helper is deliberately pure so the cosmetic typing-beat guess is
// verified in isolation (mirrors the staggerReplies.test.ts convention).
import { describe, it, expect } from 'vitest';
import { extractDirectedCallsign, resolveFirstResponder } from '../firstResponder';
import type { Agent } from '../../store/types';

function mkAgent(p: { id: string; callsign: string; isCrew: boolean }): Agent {
  return {
    id: p.id,
    agentType: 'crew',
    callsign: p.callsign,
    displayName: '',
    pool: 'bridge',
    state: 'active',
    confidence: 1,
    trust: 0.5,
    tier: 'domain',
    isCrew: p.isCrew,
    position: [0, 0, 0] as [number, number, number],
  };
}

// Ezri (a1) + Yeo (a2) are crew; Probe (a3) is non-crew. 'captain' is a
// participant id but never in the agents map.
const PARTICIPANTS = ['captain', 'a1', 'a2', 'a3'] as const;
function fixture(): ReadonlyMap<string, Agent> {
  return new Map<string, Agent>([
    ['a1', mkAgent({ id: 'a1', callsign: 'Ezri', isCrew: true })],
    ['a2', mkAgent({ id: 'a2', callsign: 'Yeo', isCrew: true })],
    ['a3', mkAgent({ id: 'a3', callsign: 'Probe', isCrew: false })],
  ]);
}

describe('AD-962a resolveFirstResponder', () => {
  it('1. resolves a leading @-mention to the crew participant', () => {
    const r = resolveFirstResponder("@ezri what's the read?", PARTICIPANTS, fixture());
    expect(r).toEqual({ agentId: 'a1', callsign: 'Ezri' });
  });

  it('2. resolves a vocative comma and a vocative colon address', () => {
    expect(resolveFirstResponder('Ezri, your read?', PARTICIPANTS, fixture())).toEqual({
      agentId: 'a1',
      callsign: 'Ezri',
    });
    expect(resolveFirstResponder('Yeo: status', PARTICIPANTS, fixture())).toEqual({
      agentId: 'a2',
      callsign: 'Yeo',
    });
  });

  it('3. matches the callsign case-insensitively', () => {
    const r = resolveFirstResponder('@EZRI sitrep', PARTICIPANTS, fixture());
    expect(r).toEqual({ agentId: 'a1', callsign: 'Ezri' });
  });

  it('4. returns null for a bare leading word (no @/,/:)', () => {
    expect(resolveFirstResponder('Data shows steady state', PARTICIPANTS, fixture())).toBeNull();
  });

  it('5. returns null when the addressed callsign is not a participant', () => {
    expect(resolveFirstResponder('@nobody hello', PARTICIPANTS, fixture())).toBeNull();
  });

  it('6. excludes non-crew participants', () => {
    expect(resolveFirstResponder('Probe, look', PARTICIPANTS, fixture())).toBeNull();
  });

  it("7. excludes 'captain'", () => {
    expect(resolveFirstResponder('Captain, note this', PARTICIPANTS, fixture())).toBeNull();
  });
});

describe('AD-962a extractDirectedCallsign', () => {
  it('8. returns null for empty input and for a referential (non-leading) name', () => {
    expect(extractDirectedCallsign('')).toBeNull();
    expect(extractDirectedCallsign('I agree with Yeo.')).toBeNull();
  });
});
