// AD-917: tests for the GroupChatHeader in-chat group controls. Mocks the
// threadApi participant/rename wrappers and seeds the REAL store (agents +
// chatThreads) so the strip/rename/add/remove flows are driven end-to-end
// through the store hydrate, BF-287 real-fixture style. Covers the avatar
// strip, rename->PATCH, empty-title no-op, add-participant, remove-participant,
// the undefined-thread render-nothing path, and the HXI no-emoji guard.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

vi.mock('../../sidebar/threadApi', () => ({
  patchThread: vi.fn(),
  addParticipant: vi.fn(),
  removeParticipant: vi.fn(),
  // AD-937: NewChatModal (opened by the 1:1 add control) imports createThread.
  createThread: vi.fn(),
}));

import { patchThread, addParticipant, removeParticipant } from '../../sidebar/threadApi';
import { GroupChatHeader } from '../GroupChatHeader';

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

function seed(thread: AD791aChatThreadView, agentsList: Agent[]): void {
  const am = new Map<string, Agent>();
  for (const a of agentsList) am.set(a.id, a);
  const tm = new Map<string, AD791aChatThreadView>();
  tm.set(thread.id, thread);
  useStore.setState({ agents: am, chatThreads: tm });
}

function mkThread(over: Partial<AD791aChatThreadView> & { id: string }): AD791aChatThreadView {
  return {
    id: over.id,
    title: over.title ?? 'Room',
    participants: over.participants ?? [],
    created_at: over.created_at ?? 0,
    last_active_at: over.last_active_at ?? 0,
    metadata: over.metadata,
  };
}

afterEach(() => {
  cleanup();
  useStore.setState({ agents: new Map(), chatThreads: new Map() });
  vi.clearAllMocks();
});

describe('AD-917 GroupChatHeader', () => {
  it('renders an avatar badge for each crew participant, excluding captain', () => {
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'] }),
      [mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Lume' }), mkAgent({ id: 'captain', callsign: 'Cap' })],
    );
    render(<GroupChatHeader threadId="t1" />);

    const badges = screen
      .getByTestId('participant-strip')
      .querySelectorAll('[data-testid="agent-avatar-badge"]');
    expect(badges).toHaveLength(2);
  });

  it('rename: editing the title submits PATCH {title, title_locked:true} and hydrates the store', async () => {
    seed(
      mkThread({ id: 't1', title: 'Old', participants: ['captain', 'a1', 'a2'] }),
      [mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Lume' })],
    );
    const updated = mkThread({ id: 't1', title: 'New', participants: ['captain', 'a1', 'a2'], last_active_at: 1 });
    vi.mocked(patchThread).mockResolvedValue(updated);
    render(<GroupChatHeader threadId="t1" />);

    fireEvent.click(screen.getByTestId('group-chat-title'));
    const input = screen.getByTestId('group-chat-title-input');
    fireEvent.change(input, { target: { value: 'New' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() =>
      expect(patchThread).toHaveBeenCalledWith('t1', { title: 'New', title_locked: true }),
    );
    await waitFor(() => expect(useStore.getState().chatThreads.get('t1')?.title).toBe('New'));
  });

  it('rename: empty title submit is a no-op (no PATCH)', () => {
    seed(mkThread({ id: 't1', title: 'Old', participants: ['captain', 'a1', 'a2'] }), [
      mkAgent({ id: 'a1', callsign: 'Vex' }),
      mkAgent({ id: 'a2', callsign: 'Lume' }),
    ]);
    render(<GroupChatHeader threadId="t1" />);

    fireEvent.click(screen.getByTestId('group-chat-title'));
    const input = screen.getByTestId('group-chat-title-input');
    fireEvent.change(input, { target: { value: '   ' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(patchThread).not.toHaveBeenCalled();
  });

  it('add-participant on a GROUP (>=2 crew): popover -> addParticipant + updates the strip', async () => {
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'] }),
      [mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Lume' }), mkAgent({ id: 'a3', callsign: 'Rix' })],
    );
    const updated = mkThread({ id: 't1', participants: ['captain', 'a1', 'a2', 'a3'], last_active_at: 1 });
    vi.mocked(addParticipant).mockResolvedValue(updated);
    render(<GroupChatHeader threadId="t1" />);

    expect(
      screen.getByTestId('participant-strip').querySelectorAll('[data-testid="agent-avatar-badge"]'),
    ).toHaveLength(2);

    fireEvent.click(screen.getByTestId('add-participant-button'));
    const rows = screen.getAllByTestId('add-participant-row');
    expect(rows).toHaveLength(1); // a1,a2 already participants -> only a3 offered
    fireEvent.click(rows[0]);

    await waitFor(() => expect(addParticipant).toHaveBeenCalledWith('t1', 'a3'));
    await waitFor(() =>
      expect(
        screen.getByTestId('participant-strip').querySelectorAll('[data-testid="agent-avatar-badge"]'),
      ).toHaveLength(3),
    );
  });

  it('AD-937/AD-969: add-participant on the Captain 1:1 HOME DM (is_default) opens the SEEDED picker, does NOT mutate', () => {
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1'], metadata: { is_default: true } }),
      [mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Lume' })],
    );
    render(<GroupChatHeader threadId="t1" />);
    // is_default 1:1 -> the add control opens the NewChatModal seeded with the
    // host, NOT the inline add-participant @-popover (which would mutate the
    // pristine 1:1 home DM).
    expect(screen.queryByTestId('new-chat-modal')).toBeNull();
    fireEvent.click(screen.getByTestId('add-participant-button'));
    // The seeded NewChatModal opens (it contains its own multi-select picker);
    // the inline mutate path (addParticipant) is never taken.
    expect(screen.getByTestId('new-chat-modal')).toBeTruthy();
    expect(screen.getByTestId('new-chat-seed-a1')).toBeTruthy();
    expect(addParticipant).not.toHaveBeenCalled();
  });

  it('AD-969: add-participant on an AGENT-CREATED room (1 crew, not is_default) adds IN PLACE, no new chat', async () => {
    seed(
      mkThread({ id: 't1', participants: ['a1'], metadata: { created_by_agent: 'a1' } }),
      [mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Lume' })],
    );
    const updated = mkThread({
      id: 't1', participants: ['a1', 'a2'], metadata: { created_by_agent: 'a1' }, last_active_at: 1,
    });
    vi.mocked(addParticipant).mockResolvedValue(updated);
    render(<GroupChatHeader threadId="t1" />);

    // The add control opens the inline @-popover (NOT the new-chat modal) — the
    // Captain-reported bug was that this minted a brand-new chat instead.
    fireEvent.click(screen.getByTestId('add-participant-button'));
    expect(screen.queryByTestId('new-chat-modal')).toBeNull();
    const rows = screen.getAllByTestId('add-participant-row');
    expect(rows).toHaveLength(1); // a1 already in -> only a2 offered
    fireEvent.click(rows[0]);

    await waitFor(() => expect(addParticipant).toHaveBeenCalledWith('t1', 'a2'));
    await waitFor(() =>
      expect(
        screen.getByTestId('participant-strip').querySelectorAll('[data-testid="agent-avatar-badge"]'),
      ).toHaveLength(2),
    );
  });

  it('remove-participant: hovering reveals the remove control and clicking it DELETEs + updates the strip', async () => {
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'] }),
      [mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Lume' })],
    );
    const updated = mkThread({ id: 't1', participants: ['captain', 'a2'], last_active_at: 1 });
    vi.mocked(removeParticipant).mockResolvedValue(updated);
    render(<GroupChatHeader threadId="t1" />);

    const badges = screen
      .getByTestId('participant-strip')
      .querySelectorAll('[data-testid="agent-avatar-badge"]');
    expect(badges).toHaveLength(2);

    fireEvent.mouseEnter(badges[0].parentElement!);
    fireEvent.click(screen.getByTestId('remove-participant-a1'));

    await waitFor(() => expect(removeParticipant).toHaveBeenCalledWith('t1', 'a1'));
    await waitFor(() =>
      expect(
        screen.getByTestId('participant-strip').querySelectorAll('[data-testid="agent-avatar-badge"]'),
      ).toHaveLength(1),
    );
  });

  it('renders nothing when the thread is undefined', () => {
    useStore.setState({ agents: new Map(), chatThreads: new Map() });
    const { container } = render(<GroupChatHeader threadId="missing" />);
    expect(container.querySelector('[data-testid="group-chat-header"]')).toBeNull();
  });

  it('renders no emoji (HXI #3)', () => {
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'] }),
      [mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Lume' })],
    );
    const { container } = render(<GroupChatHeader threadId="t1" />);
    expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
