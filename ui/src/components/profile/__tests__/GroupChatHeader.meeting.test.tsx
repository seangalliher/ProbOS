// AD-920: tests for the GroupChatHeader Start/End Meeting toggle. SEPARATE
// file from GroupChatHeader.test.tsx (keeps the AD-917 count stable). Mocks
// the threadApi wrappers and seeds the REAL store (agents + chatThreads),
// BF-287 real-fixture style. Covers start/end toggling, aria-pressed
// reflection, the no-crew hidden path, and the HXI no-emoji guard.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { act, render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
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
import groupChatHeaderSource from '../GroupChatHeader.tsx?raw';

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
  useStore.setState({ agents: new Map(), chatThreads: new Map(), callAudioEnabled: true, meetingChatVisible: true });
  vi.clearAllMocks();
});

describe('AD-920 GroupChatHeader meeting toggle', () => {
  it('start meeting: click calls setMeetingActive(threadId, true) and hydrates the store', async () => {
    // AD-1058: the GroupChatHeader call toggle is GROUP-only now (a 1:1 uses the
    // Teams-style CallMenu); exercise it on a 2-crew group.
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'] }),
      [mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Bones' })],
    );
    const updated = mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'], metadata: { meeting_active: true } });
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
    // AD-1058: group context (the toggle is group-only now).
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'], metadata: { meeting_active: true } }),
      [mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Bones' })],
    );
    vi.mocked(setMeetingActive).mockResolvedValue(
      mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'], metadata: {} }),
    );
    render(<GroupChatHeader threadId="t1" />);

    fireEvent.click(screen.getByTestId('meeting-toggle'));

    await waitFor(() => expect(setMeetingActive).toHaveBeenCalledWith('t1', false));
  });

  it('AD-954: the toggle is framed as "Start call" / "End call" (Teams mental model)', () => {
    // AD-1058: group context (the toggle is group-only now).
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'] }),
      [mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Bones' })],
    );
    const { rerender } = render(<GroupChatHeader threadId="t1" />);
    // Inactive -> "Start call".
    expect(screen.getByTestId('meeting-toggle').getAttribute('aria-label')).toBe('Start call');
    expect(screen.getByTestId('meeting-toggle').getAttribute('title')).toBe('Start call');
    // Active -> "End call".
    act(() => {
      useStore.getState().setChatThread(
        mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'], metadata: { meeting_active: true } }),
      );
      rerender(<GroupChatHeader threadId="t1" />);
    });
    expect(screen.getByTestId('meeting-toggle').getAttribute('aria-label')).toBe('End call');
  });

  it('aria-pressed reflects metadata.meeting_active (true when active, false when inactive)', () => {
    // AD-1058: group context (the toggle is group-only now).
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'], metadata: { meeting_active: true } }),
      [mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Bones' })],
    );
    render(<GroupChatHeader threadId="t1" />);
    expect(screen.getByTestId('meeting-toggle').getAttribute('aria-pressed')).toBe('true');

    cleanup();
    seed(
      mkThread({ id: 't2', participants: ['captain', 'a1', 'a2'] }),
      [mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Bones' })],
    );
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

describe('BF-671 GroupChatHeader has no output-audio ownership', () => {
  it('active call retains its header controls but renders no audio control or label', () => {
    seed(
      mkThread({
        id: 't1',
        title: 'Bridge room',
        participants: ['captain', 'a1', 'a2'],
        metadata: { meeting_active: true },
      }),
      [mkAgent({ id: 'a1', callsign: 'Vex' }), mkAgent({ id: 'a2', callsign: 'Bones' })],
    );
    render(<GroupChatHeader threadId="t1" />);

    expect(screen.getByTestId('group-chat-title').textContent).toBe('Vex, Bones');
    expect(screen.getByTestId('participant-strip').children).toHaveLength(2);
    expect(screen.getByTestId('meeting-toggle').getAttribute('aria-label')).toBe('End call');
    expect(screen.getByTestId('chat-visibility-toggle')).toBeTruthy();
    expect(screen.getByTestId('add-participant-button')).toBeTruthy();
    expect(screen.queryByTestId('call-audio-toggle')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Mute call audio' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Unmute call audio' })).toBeNull();
  });

  it('source contains no call-audio selector, setter, testid, label, or speaker path', () => {
    expect(groupChatHeaderSource).not.toMatch(/callAudioEnabled|setCallAudioEnabled|call-audio-toggle/);
    expect(groupChatHeaderSource).not.toMatch(/Mute call audio|Unmute call audio/);
    expect(groupChatHeaderSource).not.toContain('M2.5 6 H5 L8.5 3.5 V12.5 L5 10 H2.5 Z');
  });
});

describe('AD-984a GroupChatHeader chat-visibility toggle', () => {
  it('chat-visibility toggle hidden when no meeting is active', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'a1'] }), [mkAgent({ id: 'a1', callsign: 'Vex' })]);
    render(<GroupChatHeader threadId="t1" />);
    expect(screen.queryByTestId('chat-visibility-toggle')).toBeNull();
  });

  it('chat-visibility toggle shown and visible (aria-pressed=true) by default in a meeting', () => {
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1'], metadata: { meeting_active: true } }),
      [mkAgent({ id: 'a1', callsign: 'Vex' })],
    );
    useStore.setState({ meetingChatVisible: true });
    render(<GroupChatHeader threadId="t1" />);
    const btn = screen.getByTestId('chat-visibility-toggle');
    expect(btn).toBeTruthy();
    expect(btn.getAttribute('aria-pressed')).toBe('true');
    expect(btn.getAttribute('aria-label')).toBe('Hide chat');
  });

  it('clicking the chat-visibility toggle hides the chat (meetingChatVisible -> false, aria-pressed -> false)', () => {
    seed(
      mkThread({ id: 't1', participants: ['captain', 'a1'], metadata: { meeting_active: true } }),
      [mkAgent({ id: 'a1', callsign: 'Vex' })],
    );
    useStore.setState({ meetingChatVisible: true });
    render(<GroupChatHeader threadId="t1" />);
    const btn = screen.getByTestId('chat-visibility-toggle');
    fireEvent.click(btn);
    expect(useStore.getState().meetingChatVisible).toBe(false);
    expect(btn.getAttribute('aria-pressed')).toBe('false');
    expect(btn.getAttribute('aria-label')).toBe('Show chat');
  });
});
