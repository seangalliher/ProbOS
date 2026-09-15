/** AD-982b: vision-capability toggle in the AgentProfilePanel header.
 *
 * The Captain can grant/revoke an agent's permanent ambient vision from the
 * profile card. The toggle reflects /profile visionCapable and POSTs to
 * /api/agent/{id}/vision-capability/set.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, fireEvent, waitFor, screen, cleanup, act } from '@testing-library/react';
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
import { validProfile } from '../hooks/useProfileResource';

const AGENT_ID = 'agent-yeoman';
const INITIAL = useStore.getState();
const originalFetch = global.fetch;

function seedStore(): void {
  useStore.setState({
    ...INITIAL, connected: true, liveGeneration: 'vision-fixture', liveRepairEpoch: 0,
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

function profileResp(visionCapable: boolean | undefined): Response {
  const payload = {
    id: AGENT_ID, isCrew: true, department: 'ops', displayName: 'Yeo', callsign: 'Yeo', agentType: 'yeoman',
    rank: 'lieutenant', agencyLevel: 'autonomous', personality: {}, specialization: [], trust: 0.7,
    trustHistory: [], confidence: 0.7, state: 'idle', tier: 'domain', pool: 'ops', hebbianConnections: [],
    memoryCount: 0, uptime: 120, proactiveCooldown: null,
    ...(visionCapable === undefined ? {} : { visionCapable }),
    appearance: { vrm_url: '', expression_overrides: {}, color_palette_hint: '', dsl: null },
  };
  expect(validProfile(payload, AGENT_ID)).toBe(true);
  return Response.json(payload);
}

interface ControlledRead {
  resolve: (response: Response) => void;
  signal: AbortSignal | null | undefined;
}

interface ControlledWrite extends ControlledRead {
  body: { enabled: boolean; reason: string };
  reject: (error: Error) => void;
}

function controlledRequests(): { profiles: ControlledRead[]; writes: ControlledWrite[] } {
  const profiles: ControlledRead[] = [];
  const writes: ControlledWrite[] = [];
  global.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    if (url.endsWith('/profile') && !init?.signal) return Promise.resolve(profileResp(undefined));
    if (url.endsWith('/profile')) return new Promise(resolve => profiles.push({ resolve, signal: init?.signal }));
    if (url.endsWith('/vision-capability/set')) {
      expect(init?.method).toBe('POST');
      return new Promise((resolve, reject) => {
        writes.push({ resolve, reject, signal: init?.signal, body: JSON.parse(String(init?.body)) });
        init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
      });
    }
    return Promise.resolve(Response.json(url === '/api/config/avatars-enabled' ? { enabled: false } : {}));
  });
  return { profiles, writes };
}

async function settleRead(read: ControlledRead, value: boolean | undefined, status = 200): Promise<void> {
  await act(async () => read.resolve(status === 200 ? profileResp(value) : Response.json({}, { status })));
}

beforeEach(() => {
  seedStore();
  if (!(Element.prototype as any).scrollIntoView) {
    (Element.prototype as any).scrollIntoView = vi.fn();
  }
});

afterEach(() => {
  cleanup();
  useStore.setState(INITIAL, true);
  global.fetch = originalFetch;
  vi.useRealTimers();
});

describe('AgentProfilePanel — AD-982b vision toggle', () => {
  it.each([false, true])('renders a distinct unknown glyph when the retained vision value is %s', async value => {
    const requests = controlledRequests();
    render(<AgentProfilePanel />);
    const toggle = screen.getByTestId('vision-toggle');
    const unknownGeometry = toggle.querySelector('svg')!.innerHTML;
    expect(toggle.querySelector('circle')?.getAttribute('r')).toBe('5.5');
    expect(toggle.querySelector('path')?.getAttribute('d')).toContain('M6.5 6.2');
    await settleRead(requests.profiles[0], value);
    const knownGeometry = toggle.querySelector('svg')!.innerHTML;
    expect(knownGeometry).not.toBe(unknownGeometry);
    fireEvent.click(toggle);
    expect(toggle).toBeDisabled();
    expect(toggle.querySelector('svg')!.innerHTML).toBe(unknownGeometry);
    await act(async () => requests.writes[0].resolve(Response.json({})));
    await settleRead(requests.profiles[requests.profiles.length - 1], undefined, 503);
    expect(toggle.querySelector('svg')!.innerHTML).toBe(unknownGeometry);
  });

  it('keeps missing and rejected vision state indeterminate and permits read-only recovery', async () => {
    const requests = controlledRequests();
    render(<AgentProfilePanel />);
    expect(requests.profiles.length).toBeGreaterThan(0);
    expect(screen.getByLabelText('Ambient vision state unknown')).toBeDisabled();
    await settleRead(requests.profiles[0], undefined);
    fireEvent.click(screen.getByTestId('vision-toggle'));
    expect(requests.writes).toHaveLength(0);
    fireEvent.click(screen.getByLabelText('Refresh ambient vision state'));
    await settleRead(requests.profiles[requests.profiles.length - 1], undefined, 503);
    expect(screen.getByLabelText('Ambient vision state unknown')).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('could not be verified');
    fireEvent.click(screen.getByLabelText('Refresh ambient vision state'));
    await settleRead(requests.profiles[requests.profiles.length - 1], true);
    expect(screen.getByLabelText('Disable ambient vision')).toBeEnabled();
    expect(requests.writes).toHaveLength(0);
  });

  it.each([false, true])('fences duplicate writes and follows the authoritative result for initial %s', async initial => {
    const requests = controlledRequests();
    render(<AgentProfilePanel />);
    await settleRead(requests.profiles[0], initial);
    const toggle = screen.getByTestId('vision-toggle');
    fireEvent.click(toggle);
    fireEvent.click(toggle);
    expect(requests.writes).toHaveLength(1);
    expect(requests.writes[0].body).toEqual({ enabled: !initial,
      reason: initial ? 'Captain revoked ambient vision' : 'Captain granted ambient vision' });
    expect(toggle).toBeDisabled();
    const readsBefore = requests.profiles.length;
    await act(async () => requests.writes[0].resolve(Response.json({ vision_capable: !initial })));
    expect(requests.profiles).toHaveLength(readsBefore + 1);
    fireEvent.click(toggle);
    expect(requests.writes).toHaveLength(1);
    await settleRead(requests.profiles[requests.profiles.length - 1], initial);
    expect(screen.getByLabelText(initial ? 'Disable ambient vision' : 'Enable ambient vision')).toBeEnabled();
  });

  it.each(['http', 'rejected', 'timeout'] as const)('reconciles a %s write failure without retrying the write', async failure => {
    const requests = controlledRequests();
    render(<AgentProfilePanel />);
    await settleRead(requests.profiles[0], true);
    if (failure === 'timeout') vi.useFakeTimers();
    fireEvent.click(screen.getByLabelText('Disable ambient vision'));
    expect(requests.writes).toHaveLength(1);
    if (failure === 'http') await act(async () => requests.writes[0].resolve(Response.json({}, { status: 403 })));
    else if (failure === 'rejected') await act(async () => requests.writes[0].reject(new Error('Synthetic transport failure')));
    else await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(screen.getByTestId('vision-toggle')).toBeDisabled();
    await settleRead(requests.profiles[requests.profiles.length - 1], false);
    expect(screen.getByLabelText('Enable ambient vision')).toBeEnabled();
    expect(screen.getByRole('alert')).toHaveTextContent(/failed|uncertain/);
    expect(requests.writes).toHaveLength(1);
  });

  it.each(['failed', 'missing'] as const)('keeps a %s reconciliation locked until a verified read-only recovery', async failure => {
    const requests = controlledRequests();
    render(<AgentProfilePanel />);
    await settleRead(requests.profiles[0], false);
    fireEvent.click(screen.getByLabelText('Enable ambient vision'));
    await act(async () => requests.writes[0].resolve(Response.json({})));
    const reconciliation = requests.profiles[requests.profiles.length - 1];
    await settleRead(reconciliation, undefined, failure === 'failed' ? 503 : 200);
    expect(screen.getByTestId('vision-toggle')).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Refresh ambient vision state'));
    await settleRead(requests.profiles[requests.profiles.length - 1], true);
    expect(screen.getByLabelText('Disable ambient vision')).toBeEnabled();
    expect(requests.writes).toHaveLength(1);
  });

  it.each([false, true])('accepts a newer same-owner reconciliation result of %s without using the superseded value', async value => {
    const requests = controlledRequests();
    render(<AgentProfilePanel />);
    await settleRead(requests.profiles[0], !value);
    fireEvent.click(screen.getByTestId('vision-toggle'));
    await act(async () => requests.writes[0].resolve(Response.json({})));
    const reconciliation = requests.profiles[requests.profiles.length - 1];
    const before = requests.profiles.length;
    act(() => window.dispatchEvent(new CustomEvent('voice-profile-updated', { detail: { agentId: AGENT_ID } })));
    expect(requests.profiles).toHaveLength(before + 1);
    expect(reconciliation.signal?.aborted).toBe(true);
    await settleRead(reconciliation, !value);
    expect(screen.getByTestId('vision-toggle')).toBeDisabled();
    await settleRead(requests.profiles[requests.profiles.length - 1], value);
    expect(screen.getByLabelText(value ? 'Disable ambient vision' : 'Enable ambient vision')).toBeEnabled();
    expect(requests.writes).toHaveLength(1);
  });

  it('keeps failed replacement reads unknown and does not extend reconciliation deadlines on repeated supersession', async () => {
    vi.useFakeTimers();
    const requests = controlledRequests();
    render(<AgentProfilePanel />);
    await settleRead(requests.profiles[0], false);
    fireEvent.click(screen.getByTestId('vision-toggle'));
    await act(async () => requests.writes[0].resolve(Response.json({})));
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    act(() => window.dispatchEvent(new CustomEvent('voice-profile-updated', { detail: { agentId: AGENT_ID } })));
    await act(async () => { await vi.advanceTimersByTimeAsync(4_000); });
    act(() => window.dispatchEvent(new CustomEvent('voice-profile-updated', { detail: { agentId: AGENT_ID } })));
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(screen.getByRole('alert')).toHaveTextContent('could not be verified');
    await settleRead(requests.profiles[requests.profiles.length - 1], true);
    expect(screen.getByTestId('vision-toggle')).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Refresh ambient vision state'));
    const recovery = requests.profiles[requests.profiles.length - 1];
    act(() => window.dispatchEvent(new CustomEvent('voice-profile-updated', { detail: { agentId: AGENT_ID } })));
    expect(recovery.signal?.aborted).toBe(true);
    await settleRead(requests.profiles[requests.profiles.length - 1], undefined, 503);
    expect(screen.getByTestId('vision-toggle')).toBeDisabled();
    expect(requests.writes).toHaveLength(1);
  });

  it.each(['disconnect', 'generation', 'repair', 'visibility', 'participant', 'unmount'] as const)(
    'retires a superseded reconciliation on %s and ignores its late data', async transition => {
      const requests = controlledRequests();
      const view = render(<AgentProfilePanel />);
      await settleRead(requests.profiles[0], false);
      fireEvent.click(screen.getByTestId('vision-toggle'));
      await act(async () => requests.writes[0].resolve(Response.json({})));
      const original = requests.profiles[requests.profiles.length - 1];
      act(() => window.dispatchEvent(new CustomEvent('voice-profile-updated', { detail: { agentId: AGENT_ID } })));
      const replacement = requests.profiles[requests.profiles.length - 1];
      expect(original.signal?.aborted).toBe(true);
      const visibility = Object.getOwnPropertyDescriptor(document, 'visibilityState');
      try {
        act(() => {
          if (transition === 'disconnect') useStore.setState({ connected: false });
          else if (transition === 'generation') useStore.setState({ liveGeneration: 'new-vision-generation' });
          else if (transition === 'repair') useStore.setState({ liveRepairEpoch: 1 });
          else if (transition === 'visibility') {
            Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
            document.dispatchEvent(new Event('visibilitychange'));
          } else if (transition === 'participant') useStore.setState({ activeProfileAgent: null });
          else view.unmount();
        });
        expect(replacement.signal?.aborted).toBe(true);
        const after = requests.profiles.length;
        await settleRead(original, true);
        await settleRead(replacement, true);
        expect(requests.profiles).toHaveLength(after);
        expect(requests.writes).toHaveLength(1);
        const toggle = screen.queryByTestId('vision-toggle');
        if (toggle) expect(toggle).toBeDisabled();
      } finally {
        if (visibility) Object.defineProperty(document, 'visibilityState', visibility);
        else Reflect.deleteProperty(document, 'visibilityState');
      }
    },
  );

  it.each(['disconnect', 'generation', 'participant', 'unmount'] as const)('retires pending vision work on %s without refreshing the next owner', async transition => {
    const requests = controlledRequests();
    const view = render(<AgentProfilePanel />);
    await settleRead(requests.profiles[0], true);
    fireEvent.click(screen.getByLabelText('Disable ambient vision'));
    expect(requests.writes).toHaveLength(1);
    act(() => {
      if (transition === 'disconnect') useStore.setState({ connected: false });
      else if (transition === 'generation') useStore.setState({ liveGeneration: 'new-vision-generation' });
      else if (transition === 'participant') useStore.setState({ activeProfileAgent: null });
      else view.unmount();
    });
    expect(requests.writes[0].signal?.aborted).toBe(true);
    const readsAfterTransition = requests.profiles.length;
    await act(async () => requests.writes[0].resolve(Response.json({})));
    expect(requests.profiles).toHaveLength(readsAfterTransition);
    if (transition === 'disconnect') expect(screen.getByTestId('vision-toggle')).toBeDisabled();
  });

  it('renders the vision toggle for a crew agent with the correct aria-label when OFF', async () => {
    global.fetch = vi.fn((url: any) => {
      const u = String(url);
      if (u === '/api/config/avatars-enabled') return Promise.resolve({ ok: true, json: () => Promise.resolve({ enabled: true }) }) as any;
      if (u.endsWith('/profile')) return Promise.resolve(profileResp(false)) as any;
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
    }) as any;
    render(<AgentProfilePanel />);
    const btn = await screen.findByRole('button', { name: 'Enable ambient vision' });
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
    const btn = await screen.findByRole('button', { name: 'Disable ambient vision' });
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
    const btn = await screen.findByRole('button', { name: 'Enable ambient vision' });
    fireEvent.click(btn);
    await waitFor(() => expect(sets.length).toBe(1));
    expect(sets[0].enabled).toBe(true);
  });
});
