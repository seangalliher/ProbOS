// AD-984b: a11y tests for the GroupChatHeader room-title rename affordance.
// SEPARATE file from GroupChatHeader.meeting.test.tsx / GroupChatHeader.test.tsx
// (keeps the AD-917/AD-920 counts stable). Mirrors the meeting file's real-store
// seed (BF-287). Asserts the non-editing title is a keyboard-operable button
// (role="button" + tabIndex=0 + aria-label) and that Enter / Space open the
// inline editor (the same path the click handler uses).
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

vi.mock('../../sidebar/threadApi', () => ({
  patchThread: vi.fn(),
  addParticipant: vi.fn(),
  removeParticipant: vi.fn(),
  setMeetingActive: vi.fn(),
  appendMessage: vi.fn(),
}));

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
  useStore.setState({ agents: new Map(), chatThreads: new Map(), callAudioEnabled: true, meetingChatVisible: true });
  vi.clearAllMocks();
});

describe('AD-984b GroupChatHeader title a11y', () => {
  it('the non-editing title is a keyboard-operable button (role/tabIndex/aria-label)', () => {
    seed(mkThread({ id: 't1', title: 'Bridge', participants: ['captain', 'a1'] }), [
      mkAgent({ id: 'a1', callsign: 'Vex' }),
    ]);
    render(<GroupChatHeader threadId="t1" />);
    const title = screen.getByTestId('group-chat-title');
    expect(title.getAttribute('role')).toBe('button');
    expect(title.getAttribute('tabindex')).toBe('0');
    expect(title.getAttribute('aria-label')).toBe('Rename room');
  });

  it('Enter on the title opens the inline editor', () => {
    seed(mkThread({ id: 't1', title: 'Bridge', participants: ['captain', 'a1'] }), [
      mkAgent({ id: 'a1', callsign: 'Vex' }),
    ]);
    render(<GroupChatHeader threadId="t1" />);
    expect(screen.queryByTestId('group-chat-title-input')).toBeNull();
    fireEvent.keyDown(screen.getByTestId('group-chat-title'), { key: 'Enter' });
    expect(screen.getByTestId('group-chat-title-input')).toBeTruthy();
  });

  it('Space on the title opens the inline editor', () => {
    seed(mkThread({ id: 't1', title: 'Bridge', participants: ['captain', 'a1'] }), [
      mkAgent({ id: 'a1', callsign: 'Vex' }),
    ]);
    render(<GroupChatHeader threadId="t1" />);
    expect(screen.queryByTestId('group-chat-title-input')).toBeNull();
    fireEvent.keyDown(screen.getByTestId('group-chat-title'), { key: ' ' });
    expect(screen.getByTestId('group-chat-title-input')).toBeTruthy();
  });
});
