// AD-923: tests for the GroupChatHeader End-of-meeting transcript writeback.
// SEPARATE file from GroupChatHeader.meeting.test.tsx (keeps the AD-920 count
// stable). Mocks the threadApi wrappers (incl. appendMessage) and seeds the
// REAL store (BF-287). Covers: End appends a deterministic role:'system'
// marker AND clears meeting_active; the append fires BEFORE the clear; Start
// does NOT append; and the HXI no-emoji guard on the composed marker body.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

vi.mock('../../sidebar/threadApi', () => ({
  patchThread: vi.fn(),
  addParticipant: vi.fn(),
  removeParticipant: vi.fn(),
  setMeetingActive: vi.fn(),
  appendMessage: vi.fn(),
}));

import { setMeetingActive, appendMessage } from '../../sidebar/threadApi';
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

describe('AD-923 GroupChatHeader transcript writeback', () => {
  it('End appends a role:"system" marker AND clears meeting_active', async () => {
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'], metadata: { meeting_active: true } }),
      [mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Bones' })],
    );
    vi.mocked(appendMessage).mockResolvedValue({});
    vi.mocked(setMeetingActive).mockResolvedValue(
      mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'], metadata: {} }),
    );
    render(<GroupChatHeader threadId="t1" />);

    fireEvent.click(screen.getByTestId('meeting-toggle'));

    await waitFor(() =>
      expect(appendMessage).toHaveBeenCalledWith(
        't1',
        expect.objectContaining({
          role: 'system',
          author_id: 'system',
          body: expect.stringContaining('Meeting ended'),
        }),
      ),
    );
    await waitFor(() => expect(setMeetingActive).toHaveBeenCalledWith('t1', false));
  });

  it('append fires BEFORE the meeting flag is cleared', async () => {
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1'], metadata: { meeting_active: true } }),
      [mkAgent({ id: 'a1', callsign: 'Vex' })],
    );
    vi.mocked(appendMessage).mockResolvedValue({});
    vi.mocked(setMeetingActive).mockResolvedValue(
      mkThread({ id: 't1', participants: ['captain', 'a1'], metadata: {} }),
    );
    render(<GroupChatHeader threadId="t1" />);

    fireEvent.click(screen.getByTestId('meeting-toggle'));

    await waitFor(() => expect(setMeetingActive).toHaveBeenCalled());
    expect(vi.mocked(appendMessage).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(setMeetingActive).mock.invocationCallOrder[0],
    );
  });

  it('Start does NOT append a marker', async () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'a1'] }), [mkAgent({ id: 'a1', callsign: 'Vex' })]);
    vi.mocked(setMeetingActive).mockResolvedValue(
      mkThread({ id: 't1', participants: ['captain', 'a1'], metadata: { meeting_active: true } }),
    );
    render(<GroupChatHeader threadId="t1" />);

    fireEvent.click(screen.getByTestId('meeting-toggle'));

    await waitFor(() => expect(setMeetingActive).toHaveBeenCalledWith('t1', true));
    expect(appendMessage).not.toHaveBeenCalled();
  });

  it('no-emoji guard: the composed marker body carries no emoji', async () => {
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'], metadata: { meeting_active: true } }),
      [mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Bones' })],
    );
    vi.mocked(appendMessage).mockResolvedValue({});
    vi.mocked(setMeetingActive).mockResolvedValue(
      mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'], metadata: {} }),
    );
    render(<GroupChatHeader threadId="t1" />);

    fireEvent.click(screen.getByTestId('meeting-toggle'));

    await waitFor(() => expect(appendMessage).toHaveBeenCalled());
    const body = String((vi.mocked(appendMessage).mock.calls[0][1] as { body: string }).body);
    expect(body).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
