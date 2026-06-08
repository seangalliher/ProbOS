// AD-931: unit tests for the pure conversation-filter helpers backing the
// unified CHATS surface. `isChat` widens `isGroupChat` to admit 1:1s while
// excluding AD-925 task rooms (task_id). Verifies helper parity with the
// migrated AD-919 cases (isGroupChat / hostAgentId / captainJoined).
import { describe, it, expect } from 'vitest';
import type { AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';
import { isChat, isGroupChat, hostAgentId, captainJoined } from '../chatFilters';

function mkAgent(p: { id: string; callsign: string; isCrew?: boolean }): Agent {
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
    isCrew: p.isCrew ?? true,
    position: [0, 0, 0] as [number, number, number],
    department: '',
  } as Agent;
}

function mkThread(over: Partial<AD791aChatThreadView> & { id: string }): AD791aChatThreadView {
  return {
    title: 'Room',
    participants: [],
    created_at: 0,
    last_active_at: 0,
    ...over,
  };
}

function agentMap(list: Agent[]): Map<string, Agent> {
  const m = new Map<string, Agent>();
  for (const a of list) m.set(a.id, a);
  return m;
}

const AGENTS = agentMap([
  mkAgent({ id: 'mccoy', callsign: 'Bones' }),
  mkAgent({ id: 'scotty', callsign: 'Scott' }),
]);

describe('AD-931 chatFilters.isChat', () => {
  it('admits a 1:1 (single crew, no task_id)', () => {
    const t = mkThread({ id: '1on1', participants: ['mccoy'] });
    expect(isChat(t, AGENTS)).toBe(true);
  });

  it('admits a group (>=2 crew)', () => {
    const t = mkThread({ id: 'grp', participants: ['mccoy', 'scotty'] });
    expect(isChat(t, AGENTS)).toBe(true);
  });

  it('admits an agent-created thread', () => {
    const t = mkThread({ id: 'ac', participants: ['mccoy'], metadata: { created_by_agent: 'mccoy' } });
    expect(isChat(t, AGENTS)).toBe(true);
  });

  it('excludes an AD-925 task room (task_id set, 2 crew)', () => {
    const t = mkThread({ id: 'task', participants: ['mccoy', 'scotty'], task_id: 'task-1' });
    expect(isChat(t, AGENTS)).toBe(false);
  });

  it('excludes a captain-only / 0-crew non-agent-created thread', () => {
    const captainOnly = mkThread({ id: 'cap', participants: ['captain'] });
    const empty = mkThread({ id: 'empty', participants: [] });
    expect(isChat(captainOnly, AGENTS)).toBe(false);
    expect(isChat(empty, AGENTS)).toBe(false);
  });
});

describe('AD-931 chatFilters parity helpers', () => {
  it('isGroupChat: true for >=2 crew, false for a single crew', () => {
    const group = mkThread({ id: 'g', participants: ['mccoy', 'scotty'] });
    const solo = mkThread({ id: 's', participants: ['mccoy'] });
    expect(isGroupChat(group, AGENTS)).toBe(true);
    expect(isGroupChat(solo, AGENTS)).toBe(false);
  });

  it('hostAgentId: first crew participant', () => {
    const t = mkThread({ id: 'h', participants: ['mccoy', 'scotty'] });
    expect(hostAgentId(t, AGENTS)).toBe('mccoy');
    const none = mkThread({ id: 'n', participants: ['captain'] });
    expect(hostAgentId(none, AGENTS)).toBeNull();
  });

  it('captainJoined: reflects the captain sentinel presence', () => {
    const joined = mkThread({ id: 'j', participants: ['mccoy', 'captain'] });
    const notJoined = mkThread({ id: 'nj', participants: ['mccoy'] });
    expect(captainJoined(joined)).toBe(true);
    expect(captainJoined(notJoined)).toBe(false);
  });
});
