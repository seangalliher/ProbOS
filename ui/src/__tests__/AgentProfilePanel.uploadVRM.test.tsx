/** AD-721h: VRM upload UI integration tests. */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, fireEvent, waitFor, screen } from '@testing-library/react';
import React from 'react';

vi.mock('@react-three/fiber', () => ({
  useFrame: () => {},
  Canvas: ({ children }: any) => <div data-testid="canvas">{children}</div>,
}));
vi.mock('@react-three/drei', () => ({
  OrbitControls: () => null,
}));
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

const AGENT_ID = 'agent-engineer';

function seedStore(): void {
  useStore.setState({
    activeProfileAgent: AGENT_ID,
    agents: new Map([
      [
        AGENT_ID,
        {
          id: AGENT_ID,
          agent_type: 'engineer',
          displayName: 'Echo',
          pool: 'engineering',
          state: 'idle',
          tier: 'domain',
          capabilities: [],
          confidence: 0.7,
          trust: 0.7,
        } as any,
      ],
    ]),
    profilePanelPos: { x: 0, y: 0 },
    poolToGroup: { engineering: 'engineering' },
    agentConversations: new Map(),
  });
}

function _profileFetchResponse() {
  return {
    ok: true,
    json: () => Promise.resolve({
      id: AGENT_ID,
      isCrew: true,
      department: 'engineering',
      displayName: 'Echo',
      appearance: { vrm_url: '', expression_overrides: {}, color_palette_hint: '', dsl: null },
    }),
  };
}

function _avatarsEnabledResponse() {
  return { ok: true, json: () => Promise.resolve({ enabled: true }) };
}

beforeEach(() => {
  seedStore();
  if (!(Element.prototype as any).scrollIntoView) {
    (Element.prototype as any).scrollIntoView = vi.fn();
  }
});

describe('AgentProfilePanel — AD-721h Upload VRM flow', () => {
  it('Upload VRM button click opens file picker (input.click invoked)', async () => {
    global.fetch = vi.fn((url: any) => {
      const u = String(url);
      if (u === '/api/config/avatars-enabled') return Promise.resolve(_avatarsEnabledResponse()) as any;
      if (u.endsWith('/profile')) return Promise.resolve(_profileFetchResponse()) as any;
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
    }) as any;

    render(<AgentProfilePanel />);
    const btn = await waitFor(() => screen.getByTestId('upload-vrm-btn')) as HTMLButtonElement;
    const input = screen.getByTestId('upload-vrm-input') as HTMLInputElement;
    const clickSpy = vi.spyOn(input, 'click');
    fireEvent.click(btn);
    expect(clickSpy).toHaveBeenCalled();
  });

  it('happy path: file selection POSTs multipart to /appearance/vrm with file field', async () => {
    let lastPost: { url: string; body: FormData | null } | null = null;
    global.fetch = vi.fn((url: any, init?: any) => {
      const u = String(url);
      if (u === '/api/config/avatars-enabled') return Promise.resolve(_avatarsEnabledResponse()) as any;
      if (u.endsWith('/profile')) return Promise.resolve(_profileFetchResponse()) as any;
      if (u.endsWith('/appearance/vrm') && init?.method === 'POST') {
        lastPost = { url: u, body: init.body as FormData };
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            agent_id: AGENT_ID,
            attachment_id: 'deadbeef',
            vrm_url: `${AGENT_ID}.vrm`,
            bytes: 256,
          }),
        }) as any;
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
    }) as any;

    render(<AgentProfilePanel />);
    const input = await waitFor(() => screen.getByTestId('upload-vrm-input')) as HTMLInputElement;
    const file = new File([new Uint8Array([0x67, 0x6c, 0x54, 0x46, 1, 2, 3, 4, 5, 6, 7, 8])], 'test.vrm', { type: 'application/octet-stream' });
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    fireEvent.change(input);

    await waitFor(() => {
      expect(lastPost).not.toBeNull();
      expect(lastPost!.url.endsWith('/appearance/vrm')).toBe(true);
      const fd = lastPost!.body as FormData;
      expect(fd.get('file')).toBeInstanceOf(File);
    });
  });

  it('413 response surfaces inline error reason', async () => {
    global.fetch = vi.fn((url: any, init?: any) => {
      const u = String(url);
      if (u === '/api/config/avatars-enabled') return Promise.resolve(_avatarsEnabledResponse()) as any;
      if (u.endsWith('/profile')) return Promise.resolve(_profileFetchResponse()) as any;
      if (u.endsWith('/appearance/vrm') && init?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          status: 413,
          json: () => Promise.resolve({ detail: { reason: 'too_large' } }),
        }) as any;
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
    }) as any;

    render(<AgentProfilePanel />);
    const input = await waitFor(() => screen.getByTestId('upload-vrm-input')) as HTMLInputElement;
    const file = new File([new Uint8Array([0x67, 0x6c, 0x54, 0x46, 1, 2, 3])], 'big.vrm', { type: 'application/octet-stream' });
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    fireEvent.change(input);

    const btn = await waitFor(() => screen.getByTestId('upload-vrm-btn')) as HTMLButtonElement;
    await waitFor(() => {
      expect(btn.getAttribute('title') || '').toContain('too_large');
    });
  });

  it('415 response surfaces inline error reason', async () => {
    global.fetch = vi.fn((url: any, init?: any) => {
      const u = String(url);
      if (u === '/api/config/avatars-enabled') return Promise.resolve(_avatarsEnabledResponse()) as any;
      if (u.endsWith('/profile')) return Promise.resolve(_profileFetchResponse()) as any;
      if (u.endsWith('/appearance/vrm') && init?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          status: 415,
          json: () => Promise.resolve({ detail: { reason: 'not_a_vrm' } }),
        }) as any;
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
    }) as any;

    render(<AgentProfilePanel />);
    const input = await waitFor(() => screen.getByTestId('upload-vrm-input')) as HTMLInputElement;
    const file = new File([new Uint8Array([0x50, 0x4e, 0x47, 0x00])], 'fake.png', { type: 'image/png' });
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    fireEvent.change(input);

    const btn = await waitFor(() => screen.getByTestId('upload-vrm-btn')) as HTMLButtonElement;
    await waitFor(() => {
      expect(btn.getAttribute('title') || '').toContain('not_a_vrm');
    });
  });
});
