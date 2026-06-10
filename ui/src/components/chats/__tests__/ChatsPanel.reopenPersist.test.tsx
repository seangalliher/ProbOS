// AD-971: added participants must survive close + reopen, and the CHATS list
// row must reflect a live add.
//
// Captain-reported bug: added Lyra + Sentinel to a chat, closed it, reopened —
// they were gone, and the chats list row never updated. Root cause: opening a
// row called setChatThread(staleListObject), CLOBBERING the freshly-added
// participants the backend had persisted; and the ChatsPanel kept its own
// listThreads() snapshot that never saw the header add.
//
// Fix: handleOpen re-fetches the thread from the backend (authoritative) before
// hydrating, and the row prefers whichever thread version is fresher by
// last_active_at. BF-287: mock threadApi, seed the REAL store, assert store
// state after the interaction.
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

import { listThreads, getThread } from '../../sidebar/threadApi';
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

// The stale list snapshot: only Atlas + Wesley, last_active_at=0.
const STALE: AD791aChatThreadView = {
  id: 'g1', title: 'Atlas, Wesley', participants: ['atlas', 'wesley'],
  created_at: 0, last_active_at: 0,
};
// The backend's CURRENT truth: Lyra + Sentinel were added, last_active_at bumped.
const FRESH: AD791aChatThreadView = {
  id: 'g1', title: 'Atlas, Wesley', participants: ['atlas', 'wesley', 'lyra', 'sentinel'],
  created_at: 0, last_active_at: 5,
};

function seed(): void {
  const am = new Map<string, Agent>();
  am.set('atlas', mkAgent({ id: 'atlas', callsign: 'Atlas' }));
  am.set('wesley', mkAgent({ id: 'wesley', callsign: 'Wesley' }));
  am.set('lyra', mkAgent({ id: 'lyra', callsign: 'Lyra' }));
  am.set('sentinel', mkAgent({ id: 'sentinel', callsign: 'Sentinel' }));
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

describe('AD-971 added participants survive reopen', () => {
  it('opening a row hydrates from the BACKEND, not the stale list object', async () => {
    vi.mocked(listThreads).mockResolvedValue([STALE]);
    vi.mocked(getThread).mockResolvedValue(FRESH);
    seed();
    render(<ChatsPanel />);
    fireEvent.click(await screen.findByTestId('chat-row-g1'));

    // The store is hydrated with the FRESH thread (Lyra + Sentinel present),
    // never the stale 2-participant list object -> no clobber on reopen.
    await waitFor(() =>
      expect(useStore.getState().chatThreads.get('g1')?.participants).toEqual(
        ['atlas', 'wesley', 'lyra', 'sentinel'],
      ),
    );
    expect(getThread).toHaveBeenCalledWith('g1');
  });

  it('falls back to the list object when the backend fetch fails (Tier-2)', async () => {
    vi.mocked(listThreads).mockResolvedValue([STALE]);
    vi.mocked(getThread).mockResolvedValue(null); // network/!ok
    seed();
    render(<ChatsPanel />);
    fireEvent.click(await screen.findByTestId('chat-row-g1'));

    await waitFor(() =>
      expect(useStore.getState().chatThreads.get('g1')).toMatchObject({ id: 'g1' }),
    );
  });

  it('the row prefers the fresher chatThreads version (live header add reflects)', async () => {
    // The list snapshot is stale; the store has the freshly-added version (a
    // header add wrote it via setChatThread + bumped last_active_at). The row
    // must render the fresher title from the store.
    vi.mocked(listThreads).mockResolvedValue([STALE]);
    seed();
    useStore.getState().setChatThread({
      ...FRESH, title: 'Atlas, Wesley, Lyra, Sentinel',
    });
    render(<ChatsPanel />);
    // The row shows the fresher display (4 participants) from the store, not the
    // stale 2-participant list snapshot.
    expect(await screen.findByText('Atlas, Wesley, Lyra, Sentinel')).toBeTruthy();
  });
});
