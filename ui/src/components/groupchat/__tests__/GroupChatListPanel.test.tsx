// AD-919: tests for the Group Chats visibility panel. Mocks the threadApi
// list/participant wrappers and seeds the REAL store (agents + the
// groupChatListOpen flag) so the group-vs-1:1 filter, agent-created badge,
// avatars, Join (addParticipant 'captain'), and the per-host open-on-click
// (setThreadForAgent + openAgentProfile) are exercised end-to-end through the
// store — BF-287 real-fixture style, no MagicMock at the store boundary.
// Includes the HXI no-emoji guard.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, type RenderResult } from '@testing-library/react';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

vi.mock('../../sidebar/threadApi', () => ({
  listThreads: vi.fn(),
  addParticipant: vi.fn(),
}));

import { listThreads, addParticipant } from '../../sidebar/threadApi';
import GroupChatListPanel from '../GroupChatListPanel';

function mkAgent(p: { id: string; callsign: string; isCrew?: boolean; department?: string }): Agent {
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
    department: p.department ?? '',
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

const AGENTS: Agent[] = [
  mkAgent({ id: 'mccoy', callsign: 'Bones', department: 'science' }),
  mkAgent({ id: 'scotty', callsign: 'Scott', department: 'engineering' }),
];

// g1 — two crew, no created_by_agent -> group, Captain-built.
const G1 = mkThread({ id: 'g1', title: 'Bridge Sync', participants: ['mccoy', 'scotty'] });
// g2 — agent-created, Captain already joined.
const G2 = mkThread({
  id: 'g2',
  title: 'Diagnostics',
  participants: ['mccoy', 'scotty', 'captain'],
  metadata: { created_by_agent: 'mccoy' },
});
// g3 — single crew, no created_by_agent -> 1:1, excluded.
const G3 = mkThread({ id: 'g3', title: 'Sickbay 1:1', participants: ['mccoy'] });
// g4 — agent-created, NOT joined by the Captain.
const G4 = mkThread({
  id: 'g4',
  title: 'Warp Core',
  participants: ['scotty', 'mccoy'],
  metadata: { created_by_agent: 'scotty' },
});
const ALL = [G1, G2, G3, G4];

function seedAgents(list: Agent[]): Map<string, Agent> {
  const am = new Map<string, Agent>();
  for (const a of list) am.set(a.id, a);
  return am;
}

async function renderOpen(threads: AD791aChatThreadView[] = ALL, agents: Agent[] = AGENTS): Promise<RenderResult> {
  vi.mocked(listThreads).mockResolvedValue(threads);
  useStore.setState({
    agents: seedAgents(agents),
    groupChatListOpen: true,
    threadIdByAgent: new Map(),
    activeProfileAgent: null,
  });
  const r = render(<GroupChatListPanel />);
  // Wait for the on-open fetch to populate the list (g1 is always a group chat).
  await screen.findByTestId('group-chat-row-g1');
  return r;
}

afterEach(() => {
  cleanup();
  useStore.setState({
    agents: new Map(),
    groupChatListOpen: false,
    threadIdByAgent: new Map(),
    activeProfileAgent: null,
  });
  vi.clearAllMocks();
});

describe('AD-919 GroupChatListPanel', () => {
  it('renders only group chats (1:1 default thread excluded)', async () => {
    await renderOpen();
    expect(screen.getByTestId('group-chat-row-g1')).toBeTruthy();
    expect(screen.getByTestId('group-chat-row-g2')).toBeTruthy();
    expect(screen.getByTestId('group-chat-row-g4')).toBeTruthy();
    // g3 is a single-crew 1:1 thread -> not a group chat.
    expect(screen.queryByTestId('group-chat-row-g3')).toBeNull();
  });

  it('badges agent-created chats only', async () => {
    await renderOpen();
    const g1row = screen.getByTestId('group-chat-row-g1');
    const g2row = screen.getByTestId('group-chat-row-g2');
    const g4row = screen.getByTestId('group-chat-row-g4');
    expect(g1row.querySelector('[data-testid="group-chat-agent-badge"]')).toBeNull();
    expect(g2row.querySelector('[data-testid="group-chat-agent-badge"]')).not.toBeNull();
    expect(g4row.querySelector('[data-testid="group-chat-agent-badge"]')).not.toBeNull();
  });

  it('renders a participant avatar for each crew member', async () => {
    await renderOpen();
    const g1row = screen.getByTestId('group-chat-row-g1');
    expect(g1row.querySelectorAll('[data-testid="agent-avatar-badge"]')).toHaveLength(2);
  });

  it('Join calls addParticipant(threadId, "captain") once', async () => {
    vi.mocked(addParticipant).mockResolvedValue(null);
    await renderOpen();
    fireEvent.click(screen.getByTestId('group-chat-join-g4'));
    await waitFor(() => expect(addParticipant).toHaveBeenCalledWith('g4', 'captain'));
    expect(addParticipant).toHaveBeenCalledTimes(1);
  });

  it('Join flips the row from join control to a "Joined" marker', async () => {
    vi.mocked(addParticipant).mockResolvedValue(
      mkThread({
        id: 'g4',
        title: 'Warp Core',
        participants: ['scotty', 'mccoy', 'captain'],
        metadata: { created_by_agent: 'scotty' },
        last_active_at: 1,
      }),
    );
    await renderOpen();
    expect(screen.getByTestId('group-chat-join-g4')).toBeTruthy();
    fireEvent.click(screen.getByTestId('group-chat-join-g4'));
    await waitFor(() => expect(screen.queryByTestId('group-chat-joined-g4')).not.toBeNull());
    expect(screen.queryByTestId('group-chat-join-g4')).toBeNull();
  });

  it('clicking a row opens the group chat in the first crew host', async () => {
    await renderOpen();
    fireEvent.click(screen.getByTestId('group-chat-row-g1'));
    // Open-on-click routes via threadIdByAgent + activeProfileAgent (Decision D),
    // NOT the store top-level activeThreadId. Host = first crew participant.
    expect(useStore.getState().threadIdByAgent.get('mccoy')).toBe('g1');
    expect(useStore.getState().activeProfileAgent).toBe('mccoy');
  });

  it('Join also opens the chat in the host crew agent', async () => {
    vi.mocked(addParticipant).mockResolvedValue(
      mkThread({
        id: 'g4',
        title: 'Warp Core',
        participants: ['scotty', 'mccoy', 'captain'],
        metadata: { created_by_agent: 'scotty' },
      }),
    );
    await renderOpen();
    fireEvent.click(screen.getByTestId('group-chat-join-g4'));
    await waitFor(() => expect(useStore.getState().activeProfileAgent).not.toBeNull());
    const host = useStore.getState().activeProfileAgent;
    expect(['scotty', 'mccoy']).toContain(host);
    expect(useStore.getState().threadIdByAgent.get(host as string)).toBe('g4');
  });

  it('sorts un-joined agent-created chats to the top (HXI #9)', async () => {
    await renderOpen();
    const rows = screen.getAllByTestId(/^group-chat-row-/);
    const ids = rows.map((el) => el.getAttribute('data-testid'));
    const i4 = ids.indexOf('group-chat-row-g4');
    const i1 = ids.indexOf('group-chat-row-g1');
    const i2 = ids.indexOf('group-chat-row-g2');
    expect(i4).toBeGreaterThanOrEqual(0);
    expect(i4).toBeLessThan(i1);
    expect(i4).toBeLessThan(i2);
  });

  it('self-gates: renders nothing when closed', () => {
    useStore.setState({ agents: seedAgents(AGENTS), groupChatListOpen: false });
    const { container } = render(<GroupChatListPanel />);
    expect(screen.queryByTestId('group-chat-list-panel')).toBeNull();
    expect(container.innerHTML).toBe('');
  });

  it('contains no emoji (HXI #3 stroke-SVG only)', async () => {
    const { container } = await renderOpen();
    expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
