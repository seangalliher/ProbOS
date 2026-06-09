// AD-932 / AD-937: tests for the EmptyChatAddPeople empty-state affordance.
// Seeds the REAL zustand store (BF-287 real-fixture style, no MagicMock) and
// mocks only threadApi.createThread. AD-937 made the flow NON-DESTRUCTIVE: the
// button now opens the AD-931 NewChatModal seeded with the host (the locked
// first participant) instead of materializing+mutating the 1:1. Covers the
// isCrew self-gate, the unknown-agent gate, the seeded-modal open (no mutation),
// the locked host chip, modal close, clickability, and the HXI no-emoji guard.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useStore } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

vi.mock('../../sidebar/threadApi', () => ({
  createThread: vi.fn(),
}));

import { createThread } from '../../sidebar/threadApi';
import { EmptyChatAddPeople } from '../EmptyChatAddPeople';

const mockedCreateThread = vi.mocked(createThread);

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

function seedAgents(list: Agent[]): void {
  const m = new Map<string, Agent>();
  for (const a of list) m.set(a.id, a);
  useStore.setState({ agents: m, chatThreads: new Map(), threadIdByAgent: new Map() });
}

afterEach(() => {
  cleanup();
  useStore.setState({ agents: new Map(), chatThreads: new Map(), threadIdByAgent: new Map() });
  vi.clearAllMocks();
});

describe('AD-932/AD-937 EmptyChatAddPeople', () => {
  it('renders the add-people affordance for a crew agent', () => {
    seedAgents([mkAgent({ id: 'a1', callsign: 'Vex' })]);
    render(<EmptyChatAddPeople agentId="a1" />);
    expect(screen.getByTestId('empty-chat-add-people')).toBeTruthy();
  });

  it('renders nothing for a non-crew agent', () => {
    seedAgents([mkAgent({ id: 'u1', callsign: 'Util', isCrew: false })]);
    const { container } = render(<EmptyChatAddPeople agentId="u1" />);
    expect(screen.queryByTestId('empty-chat-add-people')).toBeNull();
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing for an unknown agentId (no agent in store)', () => {
    seedAgents([mkAgent({ id: 'a1', callsign: 'Vex' })]);
    render(<EmptyChatAddPeople agentId="ghost" />);
    expect(screen.queryByTestId('empty-chat-add-people')).toBeNull();
  });

  it('AD-937: clicking opens the SEEDED NewChatModal (host locked), does NOT materialize/mutate', () => {
    seedAgents([mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Lume' })]);
    render(<EmptyChatAddPeople agentId="a1" />);
    expect(screen.queryByTestId('new-chat-modal')).toBeNull();

    fireEvent.click(screen.getByTestId('empty-chat-add-people'));

    // The AD-931 picker opens, pre-seeded with a1 as the locked host.
    expect(screen.getByTestId('new-chat-modal')).toBeTruthy();
    expect(screen.getByTestId('new-chat-seed-a1')).toBeTruthy();
    // Non-destructive: nothing is created or written on open (the old AD-932
    // materialize-then-mutate flow is gone).
    expect(mockedCreateThread).not.toHaveBeenCalled();
    expect(useStore.getState().chatThreads.size).toBe(0);
    expect(useStore.getState().threadIdByAgent.size).toBe(0);
  });

  it('AD-937: the seeded host chip is non-removable in the opened modal', () => {
    seedAgents([mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Lume' })]);
    render(<EmptyChatAddPeople agentId="a1" />);
    fireEvent.click(screen.getByTestId('empty-chat-add-people'));
    expect(screen.getByTestId('new-chat-seed-a1')).toBeTruthy();
    // The removable-chip variant is NOT used for the locked seed host.
    expect(screen.queryByTestId('new-chat-selected-a1')).toBeNull();
  });

  it('AD-937: the seeded modal closes via its cancel control (onClose)', () => {
    seedAgents([mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Lume' })]);
    render(<EmptyChatAddPeople agentId="a1" />);
    fireEvent.click(screen.getByTestId('empty-chat-add-people'));
    expect(screen.getByTestId('new-chat-modal')).toBeTruthy();
    fireEvent.click(screen.getByTestId('new-chat-cancel'));
    expect(screen.queryByTestId('new-chat-modal')).toBeNull();
  });

  it('the button is clickable (not disabled)', () => {
    seedAgents([mkAgent({ id: 'a1', callsign: 'Vex' })]);
    render(<EmptyChatAddPeople agentId="a1" />);
    const btn = screen.getByTestId('empty-chat-add-people') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it('contains no emoji (HXI #3)', () => {
    seedAgents([mkAgent({ id: 'a1', callsign: 'Vex' })]);
    const { container } = render(<EmptyChatAddPeople agentId="a1" />);
    expect(/\p{Extended_Pictographic}/u.test(container.innerHTML)).toBe(false);
  });
});
