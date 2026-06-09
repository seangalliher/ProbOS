// AD-938: the NewChatModal 2+ create-group branch must hydrate the created
// thread into chatThreads (so the new group's header/participants/meeting
// toggle + transcript resolve immediately) before opening it via the AD-937
// override. Mirrors NewChatModal.test.tsx (mock threadApi, real store, BF-287).
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

vi.mock('../../sidebar/threadApi', () => ({
  listThreads: vi.fn(),
  addParticipant: vi.fn(),
  createThread: vi.fn(),
}));

import { createThread } from '../../sidebar/threadApi';
import { NewChatModal } from '../NewChatModal';

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

function mkThread(over: Partial<AD791aChatThreadView> & { id: string }): AD791aChatThreadView {
  return { title: 'Room', participants: [], created_at: 0, last_active_at: 0, ...over };
}

function seedStore(): void {
  const am = new Map<string, Agent>();
  am.set('mccoy', mkAgent({ id: 'mccoy', callsign: 'Bones' }));
  am.set('scotty', mkAgent({ id: 'scotty', callsign: 'Scott' }));
  useStore.setState({
    agents: am,
    chatsOpen: true,
    chatThreads: new Map(),
    threadIdByAgent: new Map(),
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

describe('AD-938 NewChatModal hydrate-on-create', () => {
  it('2 selected -> hydrates the created group into chatThreads AND opens via the override', async () => {
    const created = mkThread({ id: 'new-1', title: 'Bones, Scott', participants: ['mccoy', 'scotty'] });
    vi.mocked(createThread).mockResolvedValue(created);
    seedStore();
    render(<NewChatModal onClose={vi.fn()} />);
    fireEvent.click(screen.getAllByTestId('add-participant-row')[0]); // Bones (mccoy)
    fireEvent.click(screen.getAllByTestId('add-participant-row')[0]); // Scott (scotty)
    fireEvent.click(screen.getByTestId('new-chat-start'));

    // AD-938: the created group is hydrated so its header + transcript resolve.
    await vi.waitFor(() =>
      expect(useStore.getState().chatThreads.get('new-1')).toMatchObject({ id: 'new-1', title: 'Bones, Scott' }),
    );
    // AD-937: opened via the override (NOT the host's threadIdByAgent 1:1 slot).
    expect(useStore.getState().activeProfileThreadId).toBe('new-1');
    expect(useStore.getState().activeProfileAgent).toBe('mccoy');
    expect(useStore.getState().threadIdByAgent.get('mccoy')).toBeUndefined();
  });

  it('does not hydrate when createThread honest-degrades to null', async () => {
    vi.mocked(createThread).mockResolvedValue(null);
    seedStore();
    render(<NewChatModal onClose={vi.fn()} />);
    fireEvent.click(screen.getAllByTestId('add-participant-row')[0]);
    fireEvent.click(screen.getAllByTestId('add-participant-row')[0]);
    fireEvent.click(screen.getByTestId('new-chat-start'));

    await vi.waitFor(() => expect(createThread).toHaveBeenCalled());
    expect(useStore.getState().chatThreads.size).toBe(0);
    expect(useStore.getState().activeProfileThreadId).toBeNull();
  });
});
