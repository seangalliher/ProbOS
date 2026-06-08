// AD-931: tests for the "+ New chat" picker modal. Mocks the threadApi
// wrappers and seeds the REAL store (BF-287 style). Verifies the AD-917
// AddParticipantPopover reuse (accumulate onAdd -> selected[]), the Start gate
// (>=1), and the AD-931 Decision-C branch on selection count: 1 agent ->
// openAgentProfile (NO createThread); 2+ -> createThread + open host. Includes
// the HXI no-emoji guard.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

vi.mock('../../sidebar/threadApi', () => ({
  listThreads: vi.fn(),
  addParticipant: vi.fn(),
  createThread: vi.fn(),
}));

import { listThreads, createThread } from '../../sidebar/threadApi';
import ChatsPanel from '../ChatsPanel';
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
  return {
    title: 'Room',
    participants: [],
    created_at: 0,
    last_active_at: 0,
    ...over,
  };
}

function seedStore(): void {
  const am = new Map<string, Agent>();
  // Insertion order drives the popover row order: [Bones(mccoy), Scott(scotty)].
  am.set('mccoy', mkAgent({ id: 'mccoy', callsign: 'Bones' }));
  am.set('scotty', mkAgent({ id: 'scotty', callsign: 'Scott' }));
  useStore.setState({
    agents: am,
    chatsOpen: true,
    threadIdByAgent: new Map(),
    activeProfileAgent: null,
  });
}

afterEach(() => {
  cleanup();
  useStore.setState({
    agents: new Map(),
    chatsOpen: false,
    threadIdByAgent: new Map(),
    activeProfileAgent: null,
  });
  vi.clearAllMocks();
});

describe('AD-931 NewChatModal', () => {
  it('the panel "+ New chat" button opens the modal with the picker', async () => {
    vi.mocked(listThreads).mockResolvedValue([]);
    seedStore();
    render(<ChatsPanel />);
    await screen.findByTestId('chats-empty'); // flush the on-open fetch effect
    expect(screen.queryByTestId('new-chat-modal')).toBeNull();
    fireEvent.click(screen.getByTestId('new-chat-button'));
    expect(await screen.findByTestId('new-chat-modal')).toBeTruthy();
    expect(screen.getByTestId('add-participant-popover')).toBeTruthy();
  });

  it('Start is disabled with 0 selected, enabled after one pick', () => {
    seedStore();
    render(<NewChatModal onClose={vi.fn()} />);
    expect((screen.getByTestId('new-chat-start') as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getAllByTestId('add-participant-row')[0]); // Bones
    expect((screen.getByTestId('new-chat-start') as HTMLButtonElement).disabled).toBe(false);
  });

  it('1 selected -> openAgentProfile, NO createThread, panel closed', () => {
    seedStore();
    const onClose = vi.fn();
    render(<NewChatModal onClose={onClose} />);
    fireEvent.click(screen.getAllByTestId('add-participant-row')[0]); // Bones (mccoy)
    fireEvent.click(screen.getByTestId('new-chat-start'));
    expect(useStore.getState().activeProfileAgent).toBe('mccoy');
    expect(createThread).not.toHaveBeenCalled();
    expect(useStore.getState().chatsOpen).toBe(false);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('2 selected -> createThread(participants,title) then setThreadForAgent + openAgentProfile host', async () => {
    vi.mocked(createThread).mockResolvedValue(
      mkThread({ id: 'new-1', title: 'Bones, Scott', participants: ['mccoy', 'scotty'] }),
    );
    seedStore();
    render(<NewChatModal onClose={vi.fn()} />);
    fireEvent.click(screen.getAllByTestId('add-participant-row')[0]); // Bones (mccoy)
    fireEvent.click(screen.getAllByTestId('add-participant-row')[0]); // Scott (scotty) — mccoy dropped out
    fireEvent.click(screen.getByTestId('new-chat-start'));
    await vi.waitFor(() =>
      expect(createThread).toHaveBeenCalledWith(
        expect.objectContaining({ participants: ['mccoy', 'scotty'], title: 'Bones, Scott' }),
      ),
    );
    await vi.waitFor(() => expect(useStore.getState().threadIdByAgent.get('mccoy')).toBe('new-1'));
    expect(useStore.getState().activeProfileAgent).toBe('mccoy');
  });

  it('a picked agent is removable via its chip and drops back into the picker', () => {
    seedStore();
    render(<NewChatModal onClose={vi.fn()} />);
    fireEvent.click(screen.getAllByTestId('add-participant-row')[0]); // Bones (mccoy)
    expect(screen.getByTestId('new-chat-selected-mccoy')).toBeTruthy();
    // mccoy dropped out of the popover -> only Scott remains.
    expect(screen.getAllByTestId('add-participant-row')).toHaveLength(1);
    fireEvent.click(screen.getByTestId('new-chat-selected-mccoy')); // remove the chip
    expect(screen.queryByTestId('new-chat-selected-mccoy')).toBeNull();
    expect(screen.getAllByTestId('add-participant-row')).toHaveLength(2);
    expect((screen.getByTestId('new-chat-start') as HTMLButtonElement).disabled).toBe(true);
  });

  it('contains no emoji (HXI #3 stroke-SVG only)', () => {
    seedStore();
    const { container } = render(<NewChatModal onClose={vi.fn()} />);
    expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
