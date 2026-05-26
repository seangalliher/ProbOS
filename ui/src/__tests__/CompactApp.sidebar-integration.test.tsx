/** AD-792 (Wave 195) vitest — CompactApp mounts ThreadSidebar
 * alongside the ProfileChatTab and propagates active-thread switches
 * through the store. Heavy ProfileChatTab + audio / VAD / WS
 * subsystems are mocked so this test focuses on the sidebar-host
 * contract. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react';
import { useStore } from '../store/useStore';

// Mock heavy subsystems CompactApp transitively imports.
vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: () => {} }));
vi.mock('../hooks/useCameraStream', () => ({ stopCameraStream: vi.fn() }));
vi.mock('../audio/voiceActivity', () => ({
  startVoiceActivity: vi.fn(),
  stopVoiceActivity: vi.fn(),
}));
vi.mock('../store/useSettingsStore', () => ({
  useSettingsStore: Object.assign(
    (sel: any) => sel({ snapshot: null, loadSnapshot: async () => {} }),
    { getState: () => ({ snapshot: null, loadSnapshot: async () => {} }) },
  ),
}));
// Stub ProfileChatTab + chips so we can assert on the agentId prop without
// dragging in TTS / VAD / attachments.
vi.mock('../components/profile/ProfileChatTab', () => ({
  ProfileChatTab: ({ agentId, threadId }: { agentId: string; threadId?: string }) => (
    <div data-testid="profile-chat-stub" data-agent-id={agentId} data-thread-id={threadId ?? ''} />
  ),
}));
vi.mock('../components/YeoStarterChips', () => ({ YeoStarterChips: () => null }));
vi.mock('../components/YeoEmptyGreeting', () => ({ YeoEmptyGreeting: () => null }));

import CompactApp from '../CompactApp';

beforeEach(() => {
  localStorage.clear();
  useStore.setState({
    agents: new Map([
      ['yeo-id', { id: 'yeo-id', callsign: 'Yeo', displayName: 'Yeo' } as any],
      ['agent-2', { id: 'agent-2', callsign: 'Bones', displayName: 'Bones' } as any],
    ]),
    chatThreads: new Map([
      [
        't1',
        {
          id: 't1',
          title: 'Yeo thread',
          participants: ['yeo-id'],
          created_at: 1,
          last_active_at: Date.now() / 1000,
          pinned: false,
          archived: false,
        },
      ],
      [
        't2',
        {
          id: 't2',
          title: 'Bones thread',
          participants: ['agent-2'],
          created_at: 1,
          last_active_at: Date.now() / 1000,
          pinned: false,
          archived: false,
        },
      ],
    ]),
    activeThreadId: null,
    threadIdByAgent: new Map(),
    agentConversations: new Map(),
  });
  global.fetch = vi.fn(() => Promise.resolve({ ok: true, json: async () => ({ threads: [] }) }) as any);
});

afterEach(() => {
  cleanup();
});

describe('CompactApp sidebar integration', () => {
  it('mounts ThreadSidebar alongside ProfileChatTab on cold-start (Yeo)', async () => {
    render(<CompactApp />);
    await waitFor(() => {
      expect(screen.getByTestId('thread-sidebar')).toBeInTheDocument();
      expect(screen.getByTestId('profile-chat-stub')).toBeInTheDocument();
    });
    const chat = screen.getByTestId('profile-chat-stub');
    expect(chat.getAttribute('data-agent-id')).toBe('yeo-id');
  });

  it('selecting a different thread re-mounts the chat against participants[0]', async () => {
    render(<CompactApp />);
    await screen.findByTestId('thread-sidebar');
    // Switch active thread via the sidebar row.
    await act(async () => {
      fireEvent.click(screen.getByTestId('thread-row-t2'));
    });
    await waitFor(() => {
      const chat = screen.getByTestId('profile-chat-stub');
      expect(chat.getAttribute('data-agent-id')).toBe('agent-2');
      expect(chat.getAttribute('data-thread-id')).toBe('t2');
    });
  });
});
