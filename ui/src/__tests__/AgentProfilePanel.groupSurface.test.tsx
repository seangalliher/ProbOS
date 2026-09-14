/** AD-965: neutral, nameable group surface. When the AgentProfilePanel hosts a
 *  GROUP thread (>=2 crew), its identity is the group title (not the host agent)
 *  and the agent-scoped tabs collapse to Chat-only. A 1:1 is byte-identical. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, cleanup, act, fireEvent } from '@testing-library/react';
import React from 'react';

vi.mock('@react-three/fiber', () => ({
  useFrame: () => {},
  Canvas: ({ children }: any) => <div data-testid="canvas">{children}</div>,
}));
vi.mock('@react-three/drei', () => ({ OrbitControls: () => null }));
vi.mock('../components/profile/CrewVRM', () => ({
  CrewVRM: ({ agentId, vrmUrl }: { agentId: string; vrmUrl: string }) =>
    <div data-testid="crew-vrm" data-agent-id={agentId} data-vrm-url={vrmUrl} />,
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

  it('keeps the same participant VRM selected when an open DM popout enters a group', async () => {
    const vrmUrl = '/api/avatars/ezri.vrm';
    let profileRequests = 0;
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/config/avatars-enabled') return Response.json({ enabled: true });
      if (url === `/api/agent/${HOST}/profile`) {
        profileRequests += 1;
        return Response.json({
          id: HOST, isCrew: true, callsign: 'Ezri', department: 'medical',
          appearance: { vrm_url: vrmUrl, dsl: null, expression_overrides: {} },
        });
      }
      return Response.json({});
    });
    useStore.setState({
      activeProfileAgent: HOST,
      activeProfileThreadId: null,
      agents: _seedAgents(),
      chatThreads: new Map([['g1', {
        id: 'g1', title: '', participants: ['captain', HOST, PEER],
        metadata: {}, created_at: 0, last_active_at: 0,
      } as any]]),
      profilePanelPos: { x: 0, y: 0 },
      poolToGroup: { medical: 'medical' },
      agentConversations: new Map(),
    });
    render(<AgentProfilePanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Show avatar' }));
    await waitFor(() => expect(screen.getByTestId('crew-vrm').getAttribute('data-vrm-url')).toBe(vrmUrl));
    expect(profileRequests).toBeGreaterThan(0);
    expect(screen.getByTestId('crew-vrm').getAttribute('data-agent-id')).toBe(HOST);
    expect(screen.queryByTestId('parametric-avatar')).toBeNull();

    act(() => useStore.setState({ activeProfileThreadId: 'g1' }));

    await waitFor(() => expect(screen.getByTestId('group-surface-title').textContent).toBe('Ezri, Yeo'));
    expect(useStore.getState().activeProfileThreadId).toBe('g1');
    expect(screen.queryByTestId('crew-vrm')?.getAttribute('data-vrm-url')).toBe(vrmUrl);
    expect(screen.queryByTestId('crew-vrm')?.getAttribute('data-agent-id')).toBe(HOST);
    expect(screen.queryByTestId('parametric-avatar')).toBeNull();
  });

  it.each(['success', 'missing', 'failed'] as const)('does not bind the previous avatar to a new participant during a %s profile read', async outcome => {
    let resolvePeer!: (response: Response) => void;
    const peerResponse = new Promise<Response>(resolve => { resolvePeer = resolve; });
    let peerRequests = 0;
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/config/avatars-enabled') return Response.json({ enabled: true });
      if (url === `/api/agent/${HOST}/profile`) return Response.json({
        id: HOST, isCrew: true, callsign: 'Ezri', department: 'medical',
        appearance: { vrm_url: '/api/avatars/ezri.vrm', dsl: null, expression_overrides: {} },
      });
      if (url === `/api/agent/${PEER}/profile`) {
        peerRequests += 1;
        return (await peerResponse).clone();
      }
      return Response.json({});
    });
    useStore.setState({
      activeProfileAgent: HOST, activeProfileThreadId: null, agents: _seedAgents(),
      chatThreads: new Map(), profilePanelPos: { x: 0, y: 0 }, poolToGroup: {},
      agentConversations: new Map(),
    });
    const view = render(<AgentProfilePanel />);
    try {
      fireEvent.click(await screen.findByRole('button', { name: 'Show avatar' }));
      await waitFor(() => expect(screen.getByTestId('crew-vrm').getAttribute('data-vrm-url'))
        .toBe('/api/avatars/ezri.vrm'));
      expect(screen.getByTestId('crew-vrm').getAttribute('data-agent-id')).toBe(HOST);

      act(() => useStore.setState({ activeProfileAgent: PEER }));

      await waitFor(() => expect(peerRequests).toBeGreaterThan(0));
      expect(useStore.getState().activeProfileAgent).toBe(PEER);
      expect(screen.queryByTestId('crew-vrm')).toBeNull();
      await act(async () => resolvePeer(outcome === 'success'
        ? Response.json({
          id: PEER, isCrew: true, callsign: 'Yeo', department: 'bridge',
          appearance: { vrm_url: '/api/avatars/yeo.vrm', dsl: null, expression_overrides: {} },
        })
        : Response.json({ error: 'Profile unavailable' }, { status: outcome === 'missing' ? 404 : 503 })));
      if (outcome === 'success') {
        await waitFor(() => expect(screen.getByTestId('crew-vrm').getAttribute('data-vrm-url'))
          .toBe('/api/avatars/yeo.vrm'));
        expect(screen.getByTestId('crew-vrm').getAttribute('data-agent-id')).toBe(PEER);
      } else {
        expect(screen.queryByTestId('crew-vrm')).toBeNull();
      }
    } finally {
      view.unmount();
      resolvePeer(Response.json({ error: 'Test cleanup' }, { status: 503 }));
    }
  });

  it('does not present a retired participant proposal in the newly selected avatar', async () => {
    let resolveProposal!: (response: Response) => void;
    const proposalResponse = new Promise<Response>(resolve => { resolveProposal = resolve; });
    let proposalRequests = 0;
    global.fetch = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = String(input);
      if (url === '/api/config/avatars-enabled') return Response.json({ enabled: true });
      if (url === `/api/agent/${HOST}/appearance/propose`) {
        expect(options?.method).toBe('POST');
        proposalRequests += 1;
        return proposalResponse;
      }
      if (url.endsWith('/profile')) {
        const participant = url.includes(HOST) ? HOST : PEER;
        return Response.json({
          id: participant, isCrew: true, callsign: participant === HOST ? 'Ezri' : 'Yeo',
          appearance: { vrm_url: `/avatars/${participant}.vrm`, expression_overrides: {}, color_palette_hint: '' },
        });
      }
      return Response.json({});
    });
    useStore.setState({
      activeProfileAgent: HOST, activeProfileThreadId: null, agents: _seedAgents(),
      chatThreads: new Map(), profilePanelPos: { x: 0, y: 0 }, poolToGroup: {},
      agentConversations: new Map(),
    });
    const view = render(<AgentProfilePanel />);
    try {
      fireEvent.click(await screen.findByRole('button', { name: 'Design avatar' }));
      await waitFor(() => expect(proposalRequests).toBe(1));
      act(() => useStore.setState({ activeProfileAgent: PEER }));
      expect(useStore.getState().activeProfileAgent).toBe(PEER);

      await act(async () => resolveProposal(Response.json({ dsl: { version: 1 }, proposal_iteration: 1, max_iterations: 3 })));

      expect(screen.queryByTestId('approval-bar')).toBeNull();
      expect(screen.queryByRole('dialog', { name: `Avatar — ${PEER}` })).toBeNull();
      expect(screen.getByRole('button', { name: 'Design avatar' })).not.toBeDisabled();
    } finally {
      view.unmount();
      resolveProposal(Response.json({ error: 'Test cleanup' }, { status: 503 }));
    }
  });
});
