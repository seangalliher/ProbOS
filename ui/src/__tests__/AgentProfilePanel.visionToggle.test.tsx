/** AD-982b: vision-capability toggle in the AgentProfilePanel header.
 *
 * The Captain can grant/revoke an agent's permanent ambient vision from the
 * profile card. The toggle reflects /profile visionCapable and POSTs to
 * /api/agent/{id}/vision-capability/set.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, fireEvent, waitFor, screen } from '@testing-library/react';
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

const AGENT_ID = 'agent-yeoman';

function seedStore(): void {
  useStore.setState({
    activeProfileAgent: AGENT_ID,
    agents: new Map([
      [AGENT_ID, {
        id: AGENT_ID, agent_type: 'yeoman', displayName: 'Yeo', pool: 'ops',
        state: 'idle', tier: 'domain', capabilities: [], confidence: 0.7, trust: 0.7,
      } as any],
    ]),
    profilePanelPos: { x: 0, y: 0 },
    poolToGroup: { ops: 'ops' },
    agentConversations: new Map(),
  });
}

function profileResp(visionCapable: boolean) {
  return {
    ok: true,
    json: () => Promise.resolve({
      id: AGENT_ID, isCrew: true, department: 'ops', displayName: 'Yeo',
      visionCapable,
      appearance: { vrm_url: '', expression_overrides: {}, color_palette_hint: '', dsl: null },
    }),
  };
}

beforeEach(() => {
  seedStore();
  if (!(Element.prototype as any).scrollIntoView) {
    (Element.prototype as any).scrollIntoView = vi.fn();
  }
});

describe('AgentProfilePanel — AD-982b vision toggle', () => {
  it('renders the vision toggle for a crew agent with the correct aria-label when OFF', async () => {
    global.fetch = vi.fn((url: any) => {
      const u = String(url);
      if (u === '/api/config/avatars-enabled') return Promise.resolve({ ok: true, json: () => Promise.resolve({ enabled: true }) }) as any;
      if (u.endsWith('/profile')) return Promise.resolve(profileResp(false)) as any;
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
    }) as any;
    render(<AgentProfilePanel />);
    const btn = await waitFor(() => screen.getByTestId('vision-toggle'));
    expect(btn.getAttribute('aria-label')).toBe('Enable ambient vision');
  });

  it('renders the ON aria-label when visionCapable is true', async () => {
    global.fetch = vi.fn((url: any) => {
      const u = String(url);
      if (u === '/api/config/avatars-enabled') return Promise.resolve({ ok: true, json: () => Promise.resolve({ enabled: true }) }) as any;
      if (u.endsWith('/profile')) return Promise.resolve(profileResp(true)) as any;
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
    }) as any;
    render(<AgentProfilePanel />);
    const btn = await waitFor(() => screen.getByTestId('vision-toggle'));
    expect(btn.getAttribute('aria-label')).toBe('Disable ambient vision');
  });

  it('clicking the toggle POSTs enabled:true to the set endpoint', async () => {
    const sets: any[] = [];
    global.fetch = vi.fn((url: any, init?: any) => {
      const u = String(url);
      if (u === '/api/config/avatars-enabled') return Promise.resolve({ ok: true, json: () => Promise.resolve({ enabled: true }) }) as any;
      if (u.includes('/vision-capability/set') && init?.method === 'POST') {
        sets.push(JSON.parse(init.body));
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ vision_capable: true }) }) as any;
      }
      if (u.endsWith('/profile')) return Promise.resolve(profileResp(false)) as any;
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
    }) as any;
    render(<AgentProfilePanel />);
    const btn = await waitFor(() => screen.getByTestId('vision-toggle'));
    fireEvent.click(btn);
    await waitFor(() => expect(sets.length).toBe(1));
    expect(sets[0].enabled).toBe(true);
  });
});
