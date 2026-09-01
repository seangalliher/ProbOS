/** AD-965: neutral, nameable group surface. When the AgentProfilePanel hosts a
 *  GROUP thread (>=2 crew), its identity is the group title (not the host agent)
 *  and the agent-scoped tabs collapse to Chat-only. A 1:1 is byte-identical. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, cleanup, act } from '@testing-library/react';
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


describe('AD-965 group surface', () => {
  it('shows the GROUP title as the panel identity (not the host agent)', async () => {
    useStore.setState({
      activeProfileAgent: HOST,
      activeProfileThreadId: 'g1',
      agents: _seedAgents(),
      chatThreads: new Map([[
        'g1',
        {
          id: 'g1', title: '', participants: ['captain', HOST, PEER],
          metadata: {}, created_at: 0, last_active_at: 0,
        } as any,
      ]]),
      profilePanelPos: { x: 0, y: 0 },
      poolToGroup: { medical: 'medical' },
      agentConversations: new Map(),
    });
    render(<AgentProfilePanel />);
    // The neutral room identity = participant callsigns (Teams-style), NOT
    // "Ezri" alone with its department framing.
    const title = await waitFor(() => screen.getByTestId('group-surface-title'));
    expect(title.textContent).toBe('Ezri, Yeo');
  });

  it('honors a Captain-locked custom room title', async () => {
    useStore.setState({
      activeProfileAgent: HOST,
      activeProfileThreadId: 'g1',
      agents: _seedAgents(),
      chatThreads: new Map([[
        'g1',
        {
          id: 'g1', title: 'Bridge Sync', participants: ['captain', HOST, PEER],
          metadata: { title_locked: true }, created_at: 0, last_active_at: 0,
        } as any,
      ]]),
      profilePanelPos: { x: 0, y: 0 },
      poolToGroup: {},
      agentConversations: new Map(),
    });
    render(<AgentProfilePanel />);
    const title = await waitFor(() => screen.getByTestId('group-surface-title'));
    expect(title.textContent).toBe('Bridge Sync');
  });

  it('collapses the agent-scoped tabs to Chat-only on a group surface', async () => {
    useStore.setState({
      activeProfileAgent: HOST,
      activeProfileThreadId: 'g1',
      agents: _seedAgents(),
      chatThreads: new Map([[
        'g1',
        {
          id: 'g1', title: '', participants: ['captain', HOST, PEER],
          metadata: {}, created_at: 0, last_active_at: 0,
        } as any,
      ]]),
      profilePanelPos: { x: 0, y: 0 },
      poolToGroup: { medical: 'medical' },
      agentConversations: new Map(),
    });
    render(<AgentProfilePanel />);
    await waitFor(() => screen.getByTestId('group-surface-title'));
    // Chat is present; the agent-scoped tabs are gone.
    expect(screen.getByText('Chat')).toBeTruthy();
    expect(screen.queryByText('Work')).toBeNull();
    expect(screen.queryByText('Profile')).toBeNull();
    expect(screen.queryByText('Health')).toBeNull();
    expect(screen.queryByText('Memory')).toBeNull();
    expect(screen.queryByText('Self-image')).toBeNull();
  });

  it('a 1:1 (no group thread) keeps the agent identity and full tab set', async () => {
    useStore.setState({
      activeProfileAgent: HOST,
      activeProfileThreadId: null,
      agents: _seedAgents(),
      chatThreads: new Map(),
      profilePanelPos: { x: 0, y: 0 },
      poolToGroup: { medical: 'medical' },
      agentConversations: new Map(),
    });
    render(<AgentProfilePanel />);
    // No group-surface title; the agent tabs are all present.
    await waitFor(() => screen.getByText('Chat'));
    expect(screen.queryByTestId('group-surface-title')).toBeNull();
    expect(screen.getByText('Work')).toBeTruthy();
    expect(screen.getByText('Health')).toBeTruthy();
  });

  it('closing an agent-created group surface unmounts the panel', async () => {
    useStore.setState({
      activeProfileAgent: HOST,
      activeProfileThreadId: 'g1',
      agents: _seedAgents(),
      chatThreads: new Map([[
        'g1',
        {
          id: 'g1', title: '', participants: ['captain', HOST, PEER],
          metadata: { created_by_agent: HOST }, created_at: 0, last_active_at: 0,
        } as any,
      ]]),
      profilePanelPos: { x: 0, y: 0 },
      poolToGroup: { medical: 'medical' },
      agentConversations: new Map(),
    });
    render(<AgentProfilePanel />);
    await waitFor(() => screen.getByTestId('group-surface-title'));

    // The close handler must dismiss the panel even though activeProfileAgent is
    // the host re-derived from the thread (the group close bug).
    act(() => { useStore.getState().closeAgentProfile(); });

    await waitFor(() => expect(screen.queryByTestId('group-surface-title')).toBeNull());
    expect(useStore.getState().activeProfileThreadId).toBeNull();
  });
});
