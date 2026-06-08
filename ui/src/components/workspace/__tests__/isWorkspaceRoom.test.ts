/**
 * AD-929: tests for the isWorkspaceRoom gate.
 *
 * Pure predicate — exercised with real ``AD791aChatThreadView`` +
 * ``Map<string, Agent>`` fixtures (BF-287: real fixtures, not MagicMock).
 * Covers task_id rooms, ≥2-crew group rooms, the 1:1 DM / captain-only /
 * non-crew negatives, and the undefined-thread guard.
 */
import { describe, it, expect } from 'vitest';
import { isWorkspaceRoom } from '../isWorkspaceRoom';
import type { AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

function mkAgent(p: { id: string; isCrew?: boolean }): Agent {
  return {
    id: p.id,
    agentType: 'crew',
    callsign: p.id,
    displayName: '',
    pool: 'bridge',
    state: 'active',
    confidence: 1,
    trust: 0.5,
    tier: 'domain',
    isCrew: p.isCrew ?? true,
    position: [0, 0, 0] as [number, number, number],
  };
}

function mkThread(
  over: Partial<AD791aChatThreadView> & { id: string },
): AD791aChatThreadView {
  return {
    id: over.id,
    title: over.title ?? 'Room',
    participants: over.participants ?? [],
    created_at: over.created_at ?? 0,
    last_active_at: over.last_active_at ?? 0,
    task_id: over.task_id ?? null,
    metadata: over.metadata,
  };
}

function mkAgentsMap(agents: Agent[]): Map<string, Agent> {
  const m = new Map<string, Agent>();
  for (const a of agents) m.set(a.id, a);
  return m;
}

describe('isWorkspaceRoom (AD-929)', () => {
  it('returns true when task_id is set even with 0 crew participants', () => {
    const thread = mkThread({ id: 't1', task_id: 'task-9', participants: ['captain'] });
    expect(isWorkspaceRoom(thread, mkAgentsMap([]))).toBe(true);
  });

  it('returns true for a group room with 2 crew participants and no task_id', () => {
    const thread = mkThread({
      id: 't2',
      participants: ['captain', 'a1', 'a2'],
    });
    const agents = mkAgentsMap([mkAgent({ id: 'a1' }), mkAgent({ id: 'a2' })]);
    expect(isWorkspaceRoom(thread, agents)).toBe(true);
  });

  it('returns false for a 1:1 DM (one crew participant, no task_id)', () => {
    const thread = mkThread({ id: 't3', participants: ['captain', 'a1'] });
    const agents = mkAgentsMap([mkAgent({ id: 'a1' })]);
    expect(isWorkspaceRoom(thread, agents)).toBe(false);
  });

  it('excludes the captain from the crew count (captain + 1 crew → false)', () => {
    const thread = mkThread({ id: 't4', participants: ['captain', 'a1'] });
    const agents = mkAgentsMap([
      mkAgent({ id: 'captain', isCrew: true }),
      mkAgent({ id: 'a1' }),
    ]);
    expect(isWorkspaceRoom(thread, agents)).toBe(false);
  });

  it('returns false when 2 participants are non-crew (isCrew: false)', () => {
    const thread = mkThread({ id: 't5', participants: ['captain', 'u1', 'u2'] });
    const agents = mkAgentsMap([
      mkAgent({ id: 'u1', isCrew: false }),
      mkAgent({ id: 'u2', isCrew: false }),
    ]);
    expect(isWorkspaceRoom(thread, agents)).toBe(false);
  });

  it('returns false when the thread is undefined', () => {
    expect(isWorkspaceRoom(undefined, mkAgentsMap([]))).toBe(false);
  });
});
