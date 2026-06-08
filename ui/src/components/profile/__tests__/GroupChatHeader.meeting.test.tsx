// AD-920: tests for the GroupChatHeader Start/End Meeting toggle. SEPARATE
// file from GroupChatHeader.test.tsx (keeps the AD-917 count stable). Mocks
// the threadApi wrappers and seeds the REAL store (agents + chatThreads),
// BF-287 real-fixture style. Covers start/end toggling, aria-pressed
// reflection, the no-crew hidden path, and the HXI no-emoji guard.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

vi.mock('../../sidebar/threadApi', () => ({
  patchThread: vi.fn(),
  addParticipant: vi.fn(),
  removeParticipant: vi.fn(),
  setMeetingActive: vi.fn(),
  // AD-923: the End path now also calls appendMessage (transcript marker);
  // stub it so the module mock resolves it on the End-branch click.
  appendMessage: vi.fn(),
}));

import { setMeetingActive } from '../../sidebar/threadApi';
import { GroupChatHeader } from '../GroupChatHeader';

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
    id: over.id,
    title: over.title ?? 'Room',
    participants: over.participants ?? [],
    created_at: over.created_at ?? 0,
    last_active_at: over.last_active_at ?? 0,
    metadata: over.metadata,
  };
}

function seed(thread: AD791aChatThreadView, agentsList: Agent[]): void {
  const am = new Map<string, Agent>();
  for (const a of agentsList) am.set(a.id, a);
  const tm = new Map<string, AD791aChatThreadView>();
  tm.set(thread.id, thread);
  useStore.setState({ agents: am, chatThreads: tm });
}

afterEach(() => {
  cleanup();
  useStore.setState({ agents: new Map(), chatThreads: new Map() });
  vi.clearAllMocks();
});

describe('AD-920 GroupChatHeader meeting toggle', () => {
  it('start meeting: click calls setMeetingActive(threadId, true) and hydrates the store', async () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'a1'] }), [mkAgent({ id: 'a1', callsign: 'Vex' })]);
    const updated = mkThread({ id: 't1', participants: ['captain', 'a1'], metadata: { meeting_active: true } });
    vi.mocked(setMeetingActive).mockResolvedValue(updated);
    render(<GroupChatHeader threadId="t1" />);

    fireEvent.click(screen.getByTestId('meeting-toggle'));

    await waitFor(() => expect(setMeetingActive).toHaveBeenCalledWith('t1', true));
    await waitFor(() =>
      expect(
        (useStore.getState().chatThreads.get('t1')?.metadata as Record<string, unknown> | undefined)
          ?.meeting_active,
      ).toBe(true),
    );
  });

  it('end meeting: click on an active meeting calls setMeetingActive(threadId, false)', async () => {
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1'], metadata: { meeting_active: true } }),
      [mkAgent({ id: 'a1', callsign: 'Vex' })],
    );
    vi.mocked(setMeetingActive).mockResolvedValue(
      mkThread({ id: 't1', participants: ['captain', 'a1'], metadata: {} }),
    );
    render(<GroupChatHeader threadId="t1" />);

    fireEvent.click(screen.getByTestId('meeting-toggle'));

    await waitFor(() => expect(setMeetingActive).toHaveBeenCalledWith('t1', false));
  });

  it('aria-pressed reflects metadata.meeting_active (true when active, false when inactive)', () => {
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1'], metadata: { meeting_active: true } }),
      [mkAgent({ id: 'a1', callsign: 'Vex' })],
    );
    render(<GroupChatHeader threadId="t1" />);
    expect(screen.getByTestId('meeting-toggle').getAttribute('aria-pressed')).toBe('true');

    cleanup();
    seed(mkThread({ id: 't2', participants: ['captain', 'a1'] }), [mkAgent({ id: 'a1', callsign: 'Vex' })]);
    render(<GroupChatHeader threadId="t2" />);
    expect(screen.getByTestId('meeting-toggle').getAttribute('aria-pressed')).toBe('false');
  });

  it('toggle hidden when there are no crew participants', () => {
    seed(mkThread({ id: 't1', participants: ['captain'] }), [
      mkAgent({ id: 'captain', callsign: 'Cap', isCrew: false }),
    ]);
    render(<GroupChatHeader threadId="t1" />);
    expect(screen.queryByTestId('meeting-toggle')).toBeNull();
  });

  it('no-emoji guard', () => {
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1'], metadata: { meeting_active: true } }),
      [mkAgent({ id: 'a1', callsign: 'Vex' })],
    );
    const { container } = render(<GroupChatHeader threadId="t1" />);
    expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
