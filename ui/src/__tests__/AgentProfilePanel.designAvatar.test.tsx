/** AD-721d D11: AgentProfilePanel "Design avatar" + approval-flow integration tests. */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, fireEvent, waitFor, screen } from '@testing-library/react';
import React from 'react';

// Mock @react-three/fiber + drei before importing the component (popout
// pulls in R3F which trips up jsdom).
vi.mock('@react-three/fiber', () => ({
  useFrame: () => {},
  Canvas: ({ children }: any) => <div data-testid="canvas">{children}</div>,
}));
vi.mock('@react-three/drei', () => ({
  OrbitControls: () => null,
}));
// Mock heavy CrewVRM/ParametricAvatar to keep the test focused on UX flow.
vi.mock('../components/profile/CrewVRM', () => ({
  CrewVRM: () => <div data-testid="crew-vrm" />,
  applyRestingExpressionMultiMesh: () => 0,
}));
vi.mock('../components/profile/ParametricAvatar', () => ({
  ParametricAvatar: () => <div data-testid="parametric-avatar" />,
}));
// Mock voice/audio so render doesn't try to wire SpeechSynthesis.
vi.mock('../audio/voice', () => ({
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

const AGENT_ID = 'agent-counselor';

function seedStore(): void {
  useStore.setState({
    activeProfileAgent: AGENT_ID,
    agents: new Map([
      [
        AGENT_ID,
        {
          id: AGENT_ID,
          agent_type: 'counselor',
          displayName: 'Echo',
          pool: 'medical',
          state: 'idle',
          tier: 'domain',
          capabilities: [],
          confidence: 0.7,
          trust: 0.7,
        } as any,
      ],
    ]),
    profilePanelPos: { x: 0, y: 0 },
    poolToGroup: { medical: 'medical' },
    agentConversations: new Map(),
  });
}

beforeEach(() => {
  seedStore();
  if (!(Element.prototype as any).scrollIntoView) {
    (Element.prototype as any).scrollIntoView = vi.fn();
  }
});

describe('AgentProfilePanel — AD-721d Design avatar flow', () => {
  it('clicks Design avatar → POSTs /appearance/propose and surfaces approval bar', async () => {
    const proposeBody = vi.fn();
    global.fetch = vi.fn((url: any, init?: any) => {
      const u = String(url);
      if (u === '/api/config/avatars-enabled') {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ enabled: true }) }) as any;
      }
      if (u.endsWith('/profile')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            id: AGENT_ID,
            isCrew: true,
            department: 'medical',
            displayName: 'Echo',
            appearance: {
              vrm_url: '',
              expression_overrides: {},
              color_palette_hint: '',
              dsl: null,
            },
          }),
        }) as any;
      }
      if (u.endsWith('/appearance/propose') && init?.method === 'POST') {
        proposeBody(JSON.parse(init.body));
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            agent_id: AGENT_ID,
            dsl: {
              body: { type: 'slim', height_cm: 165 },
              hair: { style: 'medium', color_hsl: [25, 30, 40] },
              face: { warmth: 0.7, jaw: 'soft', eyes: 'almond' },
              outfit: { style: 'robe', primary_color: '#4a3a6a', accents: [] },
              expression_resting: 'gentle_smile',
              notes: 'gentle counselor',
            },
          }),
        }) as any;
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
    }) as any;

    render(<AgentProfilePanel />);

    // Wait for avatars-enabled feature flag fetch to populate the design button.
    const designBtn = await waitFor(() =>
      screen.getByTestId('design-avatar-btn'),
    );
    fireEvent.click(designBtn);

    await waitFor(() => {
      expect(proposeBody).toHaveBeenCalledWith({ captain_note: '' });
    });

    // Approval bar surfaces with the proposed DSL.
    await waitFor(() => {
      expect(screen.getByTestId('approval-bar')).toBeInTheDocument();
      expect(screen.getByTestId('approve-dsl-btn')).toBeInTheDocument();
      expect(screen.getByTestId('reject-dsl-btn')).toBeInTheDocument();
    });
  });

  it('Approve in popout → PUT /appearance with the proposed DSL body', async () => {
    let lastPut: any = null;
    global.fetch = vi.fn((url: any, init?: any) => {
      const u = String(url);
      if (u === '/api/config/avatars-enabled') {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ enabled: true }) }) as any;
      }
      if (u.endsWith('/profile')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            id: AGENT_ID,
            isCrew: true,
            department: 'medical',
            displayName: 'Echo',
            appearance: {
              vrm_url: '',
              expression_overrides: {},
              color_palette_hint: '',
              dsl: null,
            },
          }),
        }) as any;
      }
      if (u.endsWith('/appearance/propose') && init?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            agent_id: AGENT_ID,
            dsl: {
              body: { type: 'average', height_cm: 170 },
              hair: { style: 'medium', color_hsl: [30, 40, 30] },
              face: { warmth: 0.5, jaw: 'neutral', eyes: 'almond' },
              outfit: { style: 'uniform', primary_color: '#2a4a6a', accents: [] },
              expression_resting: 'neutral',
              notes: '',
            },
          }),
        }) as any;
      }
      if (u.endsWith(`/agent/${AGENT_ID}/appearance`) && init?.method === 'PUT') {
        lastPut = JSON.parse(init.body);
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ agentId: AGENT_ID, dsl: lastPut.dsl }),
        }) as any;
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
    }) as any;

    render(<AgentProfilePanel />);

    const designBtn = await waitFor(() => screen.getByTestId('design-avatar-btn'));
    fireEvent.click(designBtn);

    const approveBtn = await waitFor(() => screen.getByTestId('approve-dsl-btn'));
    fireEvent.click(approveBtn);

    await waitFor(() => {
      expect(lastPut).not.toBeNull();
      expect(lastPut.dsl.body.type).toBe('average');
      expect(lastPut.dsl.expression_resting).toBe('neutral');
    });
  });
});
