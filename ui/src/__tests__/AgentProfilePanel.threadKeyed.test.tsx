/** AD-954a: the group/call surface is keyed by the THREAD, not by
 *  activeProfileAgent. The room mounts from activeProfileThreadId and derives
 *  its anchor (the host id ProfileChatTab needs) from the thread's crew, so it
 *  survives an absent/stale activeProfileAgent. A 1:1 stays keyed by
 *  activeProfileAgent and is byte-identical. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import React from 'react';

vi.mock('@react-three/fiber', () => ({
  useFrame: () => {},
  Canvas: ({ children }: any) => <div data-testid="canvas">{children}</div>,
}));
vi.mock('@react-three/drei', () => ({ OrbitControls: () => null }));
vi.mock('../components/profile/CrewVRM', () => ({
  CrewVRM: () => <div data-testid="crew-vrm" />,
  applyRestingExpressionMultiMesh: () => 0,
}));
vi.mock('../components/profile/ParametricAvatar', () => ({
  ParametricAvatar: () => <div data-testid="parametric-avatar" />,
}));
vi.mock('../audio/voice', () => ({
  flushSpeechQueue: vi.fn(),
  getServerPiperVoices: vi.fn(async () => null),
  onSpeechEvent: () => () => {},
  speakResponse: vi.fn(),
  stripMarkdownForSpeech: (s: string) => s,
}));
vi.mock('../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => false,
  startListening: vi.fn(),
  stopListening: vi.fn(),
}));
// AD-954a: ProfileChatTab makes its OWN unconditional `/api/agent/{id}/profile`
// fetch (AD-718 voice-profile load) and renders in group mode (the chat tab).
// Mock it so case 3 ("no host /profile fetch in group mode") isolates the
// PANEL's own suppressed fetch — without this, the child's identical-URL fetch
// pollutes the assertion. The panel-level title + tab labels live in
// AgentProfilePanel and are unaffected by mocking the chat tab body.
vi.mock('../components/profile/ProfileChatTab', () => ({
  ProfileChatTab: () => <div data-testid="profile-chat-tab" />,
}));

import { AgentProfilePanel } from '../components/profile/AgentProfilePanel';
import { useStore } from '../store/useStore';

const HOST = 'agent-counselor';
const PEER = 'agent-yeoman';

function _agent(id: string, agent_type: string, callsign: string, pool: string) {
  return {
    id, agent_type, callsign, displayName: callsign, pool,
    state: 'idle', tier: 'domain', capabilities: [], confidence: 0.7, trust: 0.7,
    isCrew: true,
  } as any;
}

function _seedAgents() {
  return new Map<string, any>([
    [HOST, _agent(HOST, 'counselor', 'Ezri', 'medical')],
    [PEER, _agent(PEER, 'yeoman', 'Yeo', 'bridge')],
  ]);
}

function _groupThread() {
  return new Map<string, any>([[
    'g1',
    {
      id: 'g1', title: '', participants: ['captain', HOST, PEER],
      metadata: {}, created_at: 0, last_active_at: 0,
    } as any,
  ]]);
}

function _profileFetchCalls(): string[] {
  return ((global.fetch as any).mock.calls as any[][])
    .map((c) => String(c[0]))
    .filter((u) => u.endsWith('/profile'));
}

beforeEach(() => {
  if (!(Element.prototype as any).scrollIntoView) {
    (Element.prototype as any).scrollIntoView = vi.fn();
  }
  global.fetch = vi.fn((url: any) => {
    const u = String(url);
    if (u === '/api/config/avatars-enabled') {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ enabled: false }) }) as any;
    }
    if (u.endsWith('/profile')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ id: HOST, isCrew: true, department: 'medical', displayName: 'Ezri' }),
      }) as any;
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
  }) as any;
});

afterEach(cleanup);


describe('AD-954a thread-keyed group surface', () => {
  it('mounts the group surface from the THREAD with no activeProfileAgent', async () => {
    // The decoupling forcing function: activeProfileAgent is null but the active
    // thread is a group. Pre-edit, agentId = activeProfileAgent = null → the
    // `if (!agentId || !agent) return null` gate returns null and nothing
    // renders. Post-edit, agentId is DERIVED from the thread's host, so the room
    // renders its neutral (AD-965) title from thread.id alone.
    useStore.setState({
      activeProfileAgent: null,
      activeProfileThreadId: 'g1',
      agents: _seedAgents(),
      chatThreads: _groupThread(),
      profilePanelPos: { x: 0, y: 0 },
      poolToGroup: { medical: 'medical' },
      agentConversations: new Map(),
    });
    render(<AgentProfilePanel />);
    const title = await waitFor(() => screen.getByTestId('group-surface-title'));
    expect(title.textContent).toBe('Ezri, Yeo');
  });

  it('suppresses markAgentRead on a group surface, but marks read on a 1:1', async () => {
    const markAgentRead = vi.fn();
    // Group surface (no activeProfileAgent): a room, not the host's DM.
    useStore.setState({
      activeProfileAgent: null,
      activeProfileThreadId: 'g1',
      agents: _seedAgents(),
      chatThreads: _groupThread(),
      profilePanelPos: { x: 0, y: 0 },
      poolToGroup: { medical: 'medical' },
      agentConversations: new Map(),
      markAgentRead,
    });
    render(<AgentProfilePanel />);
    await waitFor(() => screen.getByTestId('group-surface-title'));
    expect(markAgentRead).not.toHaveBeenCalled();

    cleanup();
    // A 1:1: keyed by activeProfileAgent, no group thread → marks read.
    useStore.setState({
      activeProfileAgent: HOST,
      activeProfileThreadId: null,
      chatThreads: new Map(),
      markAgentRead,
    });
    render(<AgentProfilePanel />);
    await waitFor(() => screen.getByText('Chat'));
    expect(markAgentRead).toHaveBeenCalledWith(HOST);
  });

  it('suppresses the host /profile fetch in group mode but fetches it on a 1:1', async () => {
    // Group mode: the panel skips its host-scoped /profile fetch (its data is
    // never shown). ProfileChatTab is mocked, so NOTHING fetches /profile here.
    useStore.setState({
      activeProfileAgent: null,
      activeProfileThreadId: 'g1',
      agents: _seedAgents(),
      chatThreads: _groupThread(),
      profilePanelPos: { x: 0, y: 0 },
      poolToGroup: { medical: 'medical' },
      agentConversations: new Map(),
    });
    render(<AgentProfilePanel />);
    await waitFor(() => screen.getByTestId('group-surface-title'));
    expect(_profileFetchCalls()).toHaveLength(0);

    cleanup();
    (global.fetch as any).mockClear();
    // A 1:1: the panel fetches the host profile.
    useStore.setState({
      activeProfileAgent: HOST,
      activeProfileThreadId: null,
      chatThreads: new Map(),
    });
    render(<AgentProfilePanel />);
    await waitFor(() => screen.getByText('Chat'));
    await waitFor(() => expect(_profileFetchCalls().length).toBeGreaterThan(0));
  });

  it('a 1:1 is byte-identical: agent identity, full tab set, profile fetched, marks read', async () => {
    const markAgentRead = vi.fn();
    useStore.setState({
      activeProfileAgent: HOST,
      activeProfileThreadId: null,
      agents: _seedAgents(),
      chatThreads: new Map(),
      profilePanelPos: { x: 0, y: 0 },
      poolToGroup: { medical: 'medical' },
      agentConversations: new Map(),
      markAgentRead,
    });
    render(<AgentProfilePanel />);
    await waitFor(() => screen.getByText('Chat'));
    // No group surface; the agent identity + full agent-scoped tab set present.
    expect(screen.queryByTestId('group-surface-title')).toBeNull();
    expect(screen.getByText('Work')).toBeTruthy();
    expect(screen.getByText('Profile')).toBeTruthy();
    expect(screen.getByText('Health')).toBeTruthy();
    expect(screen.getByText('Memory')).toBeTruthy();
    expect(screen.getByText('Self-image')).toBeTruthy();
    // The panel fetched the host profile and marked the 1:1 read.
    await waitFor(() => expect(_profileFetchCalls().length).toBeGreaterThan(0));
    expect(markAgentRead).toHaveBeenCalledWith(HOST);
  });
});
