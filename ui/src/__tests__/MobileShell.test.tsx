// AD-708b: RTL tests for MobileShell — the device-routed full-screen PADD chat
// surface. Mirrors CompactApp.sidebar-integration.test.tsx: the heavy WS / audio
// subsystems are mocked, ProfileChatTab is stubbed so we assert on the agentId
// prop without dragging in TTS / VAD / attachments, and the REAL useStore is
// seeded with the crew roster (jsdom deletes WebSocket in setup.ts, so
// useWebSocket MUST be mocked).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { StrictMode } from 'react';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { useStore } from '../store/useStore';
import type { Agent } from '../store/types';

// Mock heavy subsystems MobileShell transitively imports.
vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: () => {} }));
vi.mock('../store/useSettingsStore', () => ({
  useSettingsStore: Object.assign(
    (sel: any) => sel({ snapshot: null, loadSnapshot: async () => {} }),
    { getState: () => ({ snapshot: null, loadSnapshot: async () => {} }) },
  ),
}));
// Stub ProfileChatTab so we can assert on the agentId prop without dragging in
// TTS / VAD / attachments.
vi.mock('../components/profile/ProfileChatTab', () => ({
  ProfileChatTab: ({ agentId, threadId }: { agentId: string; threadId?: string }) => (
    <div data-testid="profile-chat-stub" data-agent-id={agentId} data-thread-id={threadId ?? ''} />
  ),
}));

import MobileShell from '../MobileShell';

function resetMobileState(): void {
  useStore.setState({
    agents: new Map(),
    activeThreadId: null,
    activeProfileAgent: null,
    activeProfileThreadId: null,
    threadIdByAgent: new Map(),
    chatThreads: new Map(),
    threadMessages: new Map(),
    liveThreadRefresh: null,
    liveDrops: [],
    liveDropCount: 0,
  });
}

beforeEach(() => {
  localStorage.clear();
  resetMobileState();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  resetMobileState();
  localStorage.clear();
});

describe('AD-708b MobileShell', () => {
  it('renders the full-screen Yeo chat surface when Yeo is online', () => {
    useStore.setState({
      agents: new Map([['yeo-id', { id: 'yeo-id', callsign: 'Yeo', displayName: 'Yeo' } as any]]),
    });
    render(<MobileShell />);

    expect(screen.getByTestId('mobile-shell')).toBeInTheDocument();
    expect(screen.getByTestId('mobile-shell-chat')).toBeInTheDocument();
    expect(screen.getByText('FULL HXI')).toBeInTheDocument();
    const chat = screen.getByTestId('profile-chat-stub');
    expect(chat.getAttribute('data-agent-id')).toBe('yeo-id');
  });

  it('shows the connecting placeholder when no Yeo is present', () => {
    useStore.setState({ agents: new Map() });
    render(<MobileShell />);

    expect(screen.getByTestId('mobile-shell')).toBeInTheDocument();
    expect(screen.getByText(/Connecting to Yeo/i)).toBeInTheDocument();
    expect(screen.queryByTestId('profile-chat-stub')).not.toBeInTheDocument();
  });

  it('the FULL HXI button forces the #desktop escape hatch', () => {
    useStore.setState({
      agents: new Map([['yeo-id', { id: 'yeo-id', callsign: 'Yeo' } as any]]),
    });
    const replace = vi.fn();
    const originalLocation = window.location;
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { href: 'http://localhost/', hash: '', replace },
    });
    try {
      render(<MobileShell />);
      fireEvent.click(screen.getByText('FULL HXI'));
      expect(replace).toHaveBeenCalledTimes(1);
      expect(String(replace.mock.calls[0][0])).toContain('#desktop');
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: originalLocation });
    }
  });
});

describe('AD-708c-3 MobileShell chat<->mesh toggle', () => {
  it('AD-708c-3: defaults to the chat view with the toggle present and the mesh absent', () => {
    useStore.setState({
      agents: new Map([['yeo-id', { id: 'yeo-id', callsign: 'Yeo', displayName: 'Yeo' } as any]]),
    });
    render(<MobileShell />);
    expect(screen.getByTestId('mobile-view-toggle')).toBeInTheDocument();
    expect(screen.getByTestId('mobile-shell-chat')).toBeInTheDocument();
    expect(screen.queryByTestId('mobile-mesh')).not.toBeInTheDocument();
  });

  it('AD-708c-3: the MESH toggle swaps the body from chat to the 2D mesh', () => {
    useStore.setState({
      agents: new Map([['yeo-id', { id: 'yeo-id', callsign: 'Yeo', displayName: 'Yeo' } as any]]),
    });
    render(<MobileShell />);
    fireEvent.click(screen.getByTestId('mobile-toggle-mesh'));
    expect(screen.getByTestId('mobile-mesh')).toBeInTheDocument();
    expect(screen.queryByTestId('mobile-shell-chat')).not.toBeInTheDocument();
    expect(screen.queryByTestId('profile-chat-stub')).not.toBeInTheDocument();
  });

  it('AD-708c-3: toggling back to CHAT restores the chat surface and removes the mesh', () => {
    useStore.setState({
      agents: new Map([['yeo-id', { id: 'yeo-id', callsign: 'Yeo', displayName: 'Yeo' } as any]]),
    });
    render(<MobileShell />);
    fireEvent.click(screen.getByTestId('mobile-toggle-mesh'));
    expect(screen.getByTestId('mobile-mesh')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('mobile-toggle-chat'));
    expect(screen.getByTestId('mobile-shell-chat')).toBeInTheDocument();
    expect(screen.queryByTestId('mobile-mesh')).not.toBeInTheDocument();
  });
});

describe('AD-708d MobileShell swipe gestures', () => {
  it('AD-708d: a left-swipe on the body switches from chat to the mesh', () => {
    useStore.setState({
      agents: new Map([['yeo-id', { id: 'yeo-id', callsign: 'Yeo', displayName: 'Yeo' } as any]]),
    });
    render(<MobileShell />);
    const body = screen.getByTestId('mobile-shell-body');
    fireEvent.pointerDown(body, { clientX: 300, clientY: 200 });
    fireEvent.pointerUp(body, { clientX: 80, clientY: 205 });
    expect(screen.getByTestId('mobile-mesh')).toBeInTheDocument();
    expect(screen.queryByTestId('mobile-shell-chat')).not.toBeInTheDocument();
  });

  it('AD-708d: a right-swipe on the body switches from the mesh back to chat', () => {
    useStore.setState({
      agents: new Map([['yeo-id', { id: 'yeo-id', callsign: 'Yeo', displayName: 'Yeo' } as any]]),
    });
    render(<MobileShell />);
    fireEvent.click(screen.getByTestId('mobile-toggle-mesh'));
    expect(screen.getByTestId('mobile-mesh')).toBeInTheDocument();
    const body = screen.getByTestId('mobile-shell-body');
    fireEvent.pointerDown(body, { clientX: 80, clientY: 200 });
    fireEvent.pointerUp(body, { clientX: 300, clientY: 205 });
    expect(screen.getByTestId('mobile-shell-chat')).toBeInTheDocument();
    expect(screen.queryByTestId('mobile-mesh')).not.toBeInTheDocument();
  });

  it('AD-708d: the header tap toggle still switches views without any swipe', () => {
    useStore.setState({
      agents: new Map([['yeo-id', { id: 'yeo-id', callsign: 'Yeo', displayName: 'Yeo' } as any]]),
    });
    render(<MobileShell />);
    fireEvent.click(screen.getByTestId('mobile-toggle-mesh'));
    expect(screen.getByTestId('mobile-mesh')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('mobile-toggle-chat'));
    expect(screen.getByTestId('mobile-shell-chat')).toBeInTheDocument();
    expect(screen.queryByTestId('mobile-mesh')).not.toBeInTheDocument();
  });
});

function yeoAgent(id = 'yeo-id'): Agent {
  return {
    id, callsign: 'Yeo', displayName: 'Yeo', agentType: 'yeoman', pool: 'yeoman',
    state: 'active', confidence: 1, trust: 0.5, tier: 'domain', isCrew: true,
    position: [0, 0, 0],
  };
}

function seedMobileChat(threadId = 'yeo-thread', agentId = 'yeo-id'): void {
  useStore.setState({
    agents: new Map([[agentId, yeoAgent(agentId)]]),
    threadIdByAgent: new Map([[agentId, threadId]]),
  });
}

describe('AD-1243 Mobile displayed-thread ownership', () => {
  it('registers the exact displayed thread without setting Desktop profile ownership', () => {
    seedMobileChat();
    render(<MobileShell />);

    expect(screen.getByTestId('profile-chat-stub')).toHaveAttribute('data-thread-id', 'yeo-thread');
    expect(useStore.getState().activeThreadId).toBe('yeo-thread');
    expect(useStore.getState().activeProfileAgent).toBeNull();
    expect(useStore.getState().activeProfileThreadId).toBeNull();
  });

  it('registers synchronous agent and thread arrival after a cold start', () => {
    render(<MobileShell />);
    expect(screen.getByText(/Connecting to Yeo/i)).toBeInTheDocument();
    expect(useStore.getState().activeThreadId).toBeNull();

    act(() => {
      seedMobileChat();
      // The next live frame can arrive before React renders this store update.
      expect(useStore.getState().activeThreadId).toBe('yeo-thread');
    });

    expect(screen.getByTestId('profile-chat-stub')).toHaveAttribute('data-thread-id', 'yeo-thread');
  });

  it('registers a newly associated thread before the store update returns', () => {
    useStore.setState({ agents: new Map([['yeo-id', yeoAgent()]]) });
    render(<MobileShell />);
    expect(useStore.getState().activeThreadId).toBeNull();

    act(() => {
      useStore.getState().setThreadForAgent('yeo-id', 'arrived-thread');
      expect(useStore.getState().activeThreadId).toBe('arrived-thread');
    });

    expect(screen.getByTestId('profile-chat-stub')).toHaveAttribute('data-thread-id', 'arrived-thread');
  });

  it('releases on mesh and claims only the current displayed thread on returning to chat', () => {
    seedMobileChat();
    useStore.getState().setActiveThread('older-selection');
    render(<MobileShell />);
    expect(useStore.getState().activeThreadId).toBe('yeo-thread');

    fireEvent.click(screen.getByTestId('mobile-toggle-mesh'));
    expect(useStore.getState().activeThreadId).toBeNull();
    act(() => useStore.getState().setThreadForAgent('yeo-id', 'next-thread'));
    expect(useStore.getState().activeThreadId).toBeNull();

    fireEvent.click(screen.getByTestId('mobile-toggle-chat'));
    expect(useStore.getState().activeThreadId).toBe('next-thread');
    expect(screen.getByTestId('profile-chat-stub')).toHaveAttribute('data-thread-id', 'next-thread');
  });

  it.each(['removed', 'renamed'] as const)('releases when the displayed Yeo agent is %s', (change) => {
    seedMobileChat();
    render(<MobileShell />);

    act(() => {
      useStore.setState({
        agents: change === 'removed'
          ? new Map()
          : new Map([['yeo-id', { ...yeoAgent(), callsign: 'Other' }]]),
      });
      expect(useStore.getState().activeThreadId).toBeNull();
    });

    expect(screen.queryByTestId('profile-chat-stub')).not.toBeInTheDocument();
    act(() => useStore.getState().setThreadForAgent('yeo-id', 'not-visible'));
    expect(useStore.getState().activeThreadId).toBeNull();
  });

  it('rebinds agent switches to the new Yeo thread, never the old selection', () => {
    seedMobileChat();
    render(<MobileShell />);

    act(() => {
      seedMobileChat('replacement-thread', 'replacement-yeo');
      expect(useStore.getState().activeThreadId).toBe('replacement-thread');
    });

    expect(screen.getByTestId('profile-chat-stub')).toHaveAttribute('data-agent-id', 'replacement-yeo');
    expect(screen.getByTestId('profile-chat-stub')).toHaveAttribute('data-thread-id', 'replacement-thread');
  });

  it.each([undefined, ''])('releases when the resolved thread becomes %s', (thread) => {
    seedMobileChat();
    render(<MobileShell />);

    act(() => {
      useStore.setState({ threadIdByAgent: thread === undefined ? new Map() : new Map([['yeo-id', thread]]) });
      expect(useStore.getState().activeThreadId).toBeNull();
    });

    expect(screen.getByTestId('profile-chat-stub')).toHaveAttribute('data-thread-id', '');
    act(() => useStore.getState().setThreadForAgent('yeo-id', 'returned-thread'));
    expect(useStore.getState().activeThreadId).toBe('returned-thread');
    expect(screen.getByTestId('profile-chat-stub')).toHaveAttribute('data-thread-id', 'returned-thread');
  });

  it('switches displayed threads without feeding its active selection back into resolution', () => {
    seedMobileChat();
    render(<MobileShell />);

    act(() => useStore.getState().setThreadForAgent('yeo-id', 'switched-thread'));

    expect(useStore.getState().activeThreadId).toBe('switched-thread');
    expect(screen.getByTestId('profile-chat-stub')).toHaveAttribute('data-thread-id', 'switched-thread');
  });

  it('clears its still-current claim on unmount instead of restoring an older selection', () => {
    seedMobileChat();
    useStore.getState().setActiveThread('older-selection');
    const mounted = render(<MobileShell />);
    expect(useStore.getState().activeThreadId).toBe('yeo-thread');

    mounted.unmount();

    expect(useStore.getState().activeThreadId).toBeNull();
  });

  it('does not claim or clear a pre-existing equal selection on mesh or unmount', () => {
    seedMobileChat();
    useStore.getState().setActiveThread('yeo-thread');
    const mounted = render(<MobileShell />);

    fireEvent.click(screen.getByTestId('mobile-toggle-mesh'));
    expect(useStore.getState().activeThreadId).toBe('yeo-thread');
    fireEvent.click(screen.getByTestId('mobile-toggle-chat'));
    mounted.unmount();

    expect(useStore.getState().activeThreadId).toBe('yeo-thread');
  });

  it.each(['foreign-thread', null])('yields to a newer %s selection across unrelated updates and cleanup', (selection) => {
    seedMobileChat();
    const mounted = render(<MobileShell />);

    act(() => useStore.getState().setActiveThread(selection));
    act(() => {
      useStore.getState().setThreadForAgent('unrelated-agent', 'unrelated-thread');
      useStore.setState({ agents: new Map(useStore.getState().agents) });
    });

    expect(useStore.getState().activeThreadId).toBe(selection);
    expect(screen.getByTestId('profile-chat-stub')).toHaveAttribute('data-thread-id', 'yeo-thread');
    mounted.unmount();
    expect(useStore.getState().activeThreadId).toBe(selection);
  });

  it.each(['thread', 'agent'] as const)('keeps a foreign selection arriving in the same update as %s disappearance', (missing) => {
    seedMobileChat();
    const mounted = render(<MobileShell />);

    act(() => {
      useStore.setState({
        activeThreadId: 'foreign-thread',
        ...(missing === 'thread' ? { threadIdByAgent: new Map() } : { agents: new Map() }),
      });
      expect(useStore.getState().activeThreadId).toBe('foreign-thread');
    });
    mounted.unmount();

    expect(useStore.getState().activeThreadId).toBe('foreign-thread');
  });

  it('does not resume a relinquished claim when a foreign selector later returns to the same ID', () => {
    seedMobileChat();
    const mounted = render(<MobileShell />);
    act(() => useStore.getState().setActiveThread('foreign-thread'));
    act(() => useStore.getState().setActiveThread('yeo-thread'));

    mounted.unmount();

    expect(useStore.getState().activeThreadId).toBe('yeo-thread');
  });

  it('reacquires after yielding only when a new thread binding becomes visible', () => {
    seedMobileChat();
    render(<MobileShell />);
    act(() => useStore.getState().setActiveThread('foreign-thread'));

    act(() => useStore.getState().setThreadForAgent('yeo-id', 'new-visible-thread'));

    expect(useStore.getState().activeThreadId).toBe('new-visible-thread');
    expect(screen.getByTestId('profile-chat-stub')).toHaveAttribute('data-thread-id', 'new-visible-thread');
  });

  it('reacquires the same thread for a new visible agent binding after yielding', () => {
    seedMobileChat();
    render(<MobileShell />);
    act(() => useStore.getState().setActiveThread('foreign-thread'));

    act(() => seedMobileChat('yeo-thread', 'replacement-yeo'));

    expect(useStore.getState().activeThreadId).toBe('yeo-thread');
    expect(screen.getByTestId('profile-chat-stub')).toHaveAttribute('data-agent-id', 'replacement-yeo');
  });

  it('preserves a foreign selection on mesh and treats returning to chat as a new visible binding', () => {
    seedMobileChat();
    const mounted = render(<MobileShell />);
    act(() => useStore.getState().setActiveThread('foreign-thread'));

    fireEvent.click(screen.getByTestId('mobile-toggle-mesh'));
    expect(useStore.getState().activeThreadId).toBe('foreign-thread');
    fireEvent.click(screen.getByTestId('mobile-toggle-chat'));
    expect(useStore.getState().activeThreadId).toBe('yeo-thread');
    mounted.unmount();
    expect(useStore.getState().activeThreadId).toBeNull();
  });

  it('owns one layout subscription per chat mount and removes it on mesh and unmount', () => {
    const originalSubscribe = useStore.subscribe;
    const unsubscribers: ReturnType<typeof vi.fn>[] = [];
    const subscribe = vi.spyOn(useStore, 'subscribe').mockImplementation((listener) => {
      const unsubscribe = vi.fn(originalSubscribe(listener));
      unsubscribers.push(unsubscribe);
      return unsubscribe;
    });
    seedMobileChat();
    const mounted = render(<MobileShell />);
    expect(subscribe).toHaveBeenCalledTimes(1);
    act(() => useStore.getState().setThreadForAgent('yeo-id', 'changed-thread'));
    expect(subscribe).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId('mobile-toggle-mesh'));
    expect(unsubscribers[0]).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId('mobile-toggle-chat'));
    expect(subscribe).toHaveBeenCalledTimes(2);
    mounted.unmount();
    expect(unsubscribers[1]).toHaveBeenCalledTimes(1);
    act(() => useStore.getState().setThreadForAgent('yeo-id', 'after-unmount'));
    expect(useStore.getState().activeThreadId).toBeNull();
  });

  it('registers and releases correctly through StrictMode layout cleanup', () => {
    seedMobileChat();
    const mounted = render(<StrictMode><MobileShell /></StrictMode>);
    expect(useStore.getState().activeThreadId).toBe('yeo-thread');

    mounted.unmount();

    expect(useStore.getState().activeThreadId).toBeNull();
  });
});
