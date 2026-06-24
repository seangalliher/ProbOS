// AD-708b: RTL tests for MobileShell — the device-routed full-screen PADD chat
// surface. Mirrors CompactApp.sidebar-integration.test.tsx: the heavy WS / audio
// subsystems are mocked, ProfileChatTab is stubbed so we assert on the agentId
// prop without dragging in TTS / VAD / attachments, and the REAL useStore is
// seeded with the crew roster (jsdom deletes WebSocket in setup.ts, so
// useWebSocket MUST be mocked).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useStore } from '../store/useStore';

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

beforeEach(() => {
  localStorage.clear();
  useStore.setState({ agents: new Map() });
});

afterEach(() => {
  cleanup();
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
