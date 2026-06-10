// AD-938: hydrate-on-open. Opening a group from the unified CHATS list must
// hydrate the thread into chatThreads (so GroupChatHeader / MeetingView / the
// meetingActive selector + the thread-keyed transcript resolve) AND open it via
// the AD-937 override. Mirrors ChatsPanel.test.tsx: mock threadApi, seed the
// REAL store (BF-287 style), assert end-to-end store state after the click.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

vi.mock('../../sidebar/threadApi', () => ({
  listThreads: vi.fn(),
  addParticipant: vi.fn(),
  getThread: vi.fn(),
  createThread: vi.fn(),
}));

import { listThreads } from '../../sidebar/threadApi';
import ChatsPanel from '../ChatsPanel';

function mkAgent(p: { id: string; callsign: string }): Agent {
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
    isCrew: true,
    position: [0, 0, 0] as [number, number, number],
    department: '',
  } as Agent;
}

const G1: AD791aChatThreadView = {
  id: 'g1', title: 'Bridge Sync', participants: ['mccoy', 'scotty'], created_at: 0, last_active_at: 0,
};

function seed(): void {
  const am = new Map<string, Agent>();
  am.set('mccoy', mkAgent({ id: 'mccoy', callsign: 'Bones' }));
  am.set('scotty', mkAgent({ id: 'scotty', callsign: 'Scott' }));
  useStore.setState({
    agents: am,
    chatsOpen: true,
    threadIdByAgent: new Map(),
    chatThreads: new Map(),
    activeProfileAgent: null,
    activeProfileThreadId: null,
  });
}

afterEach(() => {
  cleanup();
  useStore.setState({
    agents: new Map(),
    chatsOpen: false,
    chatThreads: new Map(),
    threadIdByAgent: new Map(),
    activeProfileAgent: null,
    activeProfileThreadId: null,
  });
  vi.clearAllMocks();
});

describe('AD-938 ChatsPanel hydrate-on-open', () => {
  it('clicking a group row hydrates chatThreads AND opens it via the override', async () => {
    vi.mocked(listThreads).mockResolvedValue([G1]);
    seed();
    render(<ChatsPanel />);
    fireEvent.click(await screen.findByTestId('chat-row-g1'));

    // AD-938: the thread is now hydrated so GroupChatHeader/meetingActive resolve.
    // AD-971: handleOpen is async (re-fetches the thread) -> await the hydrate.
    await waitFor(() =>
      expect(useStore.getState().chatThreads.get('g1')).toMatchObject({ id: 'g1', title: 'Bridge Sync' }),
    );
    // AD-937: opened via the override (NOT the host's threadIdByAgent 1:1 slot).
    expect(useStore.getState().activeProfileThreadId).toBe('g1');
    expect(useStore.getState().activeProfileAgent).toBe('mccoy');
    expect(useStore.getState().threadIdByAgent.get('mccoy')).toBeUndefined();
  });
});
