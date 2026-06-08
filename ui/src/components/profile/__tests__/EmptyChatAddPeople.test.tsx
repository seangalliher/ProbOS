// AD-932: tests for the EmptyChatAddPeople empty-state affordance. Seeds the
// REAL zustand store (BF-287 real-fixture style, no MagicMock) and mocks only
// threadApi.createThread, so the materialize-then-handoff flow (createThread ->
// setChatThread + setThreadForAgent) is driven end-to-end through the real
// store. Covers the isCrew self-gate, the unknown-agent gate, the create+wire
// success path, honest-degrade on null, clickability, and the HXI no-emoji guard.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
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

function mkThread(over: Partial<AD791aChatThreadView> & { id: string }): AD791aChatThreadView {
  return {
    id: over.id,
    title: over.title ?? 'Room',
    participants: over.participants ?? [],
    created_at: over.created_at ?? 0,
    last_active_at: over.last_active_at ?? 0,
  };
}

afterEach(() => {
  cleanup();
  useStore.setState({ agents: new Map(), chatThreads: new Map(), threadIdByAgent: new Map() });
  vi.clearAllMocks();
});

describe('AD-932 EmptyChatAddPeople', () => {
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

  it('click materializes the thread: createThread called once with {title: callsign, participants: [agentId]}', async () => {
    seedAgents([mkAgent({ id: 'a1', callsign: 'Vex' })]);
    mockedCreateThread.mockResolvedValue(mkThread({ id: 't1', title: 'Vex', participants: ['a1'] }));
    render(<EmptyChatAddPeople agentId="a1" />);

    fireEvent.click(screen.getByTestId('empty-chat-add-people'));

    await waitFor(() => expect(mockedCreateThread).toHaveBeenCalledTimes(1));
    expect(mockedCreateThread).toHaveBeenCalledWith({ title: 'Vex', participants: ['a1'] });
  });

  it('on success writes setChatThread (chatThreads) and setThreadForAgent (threadIdByAgent)', async () => {
    seedAgents([mkAgent({ id: 'a1', callsign: 'Vex' })]);
    mockedCreateThread.mockResolvedValue(mkThread({ id: 't1', title: 'Vex', participants: ['a1'] }));
    render(<EmptyChatAddPeople agentId="a1" />);

    fireEvent.click(screen.getByTestId('empty-chat-add-people'));

    await waitFor(() => {
      expect(useStore.getState().chatThreads.get('t1')).toBeTruthy();
      expect(useStore.getState().threadIdByAgent.get('a1')).toBe('t1');
    });
  });

  it('honest-degrade: createThread resolves null -> no store write, button stays', async () => {
    seedAgents([mkAgent({ id: 'a1', callsign: 'Vex' })]);
    mockedCreateThread.mockResolvedValue(null);
    render(<EmptyChatAddPeople agentId="a1" />);

    fireEvent.click(screen.getByTestId('empty-chat-add-people'));

    await waitFor(() => expect(mockedCreateThread).toHaveBeenCalledTimes(1));
    expect(useStore.getState().threadIdByAgent.size).toBe(0);
    expect(useStore.getState().chatThreads.size).toBe(0);
    expect(screen.getByTestId('empty-chat-add-people')).toBeTruthy();
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
