/** AD-954a: the group/call surface is keyed by the THREAD, not by
 *  activeProfileAgent. The room mounts from activeProfileThreadId and derives
 *  its anchor (the host id ProfileChatTab needs) from the thread's crew, so it
 *  survives an absent/stale activeProfileAgent. A 1:1 stays keyed by
 *  activeProfileAgent and is byte-identical. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
import { IntentSurface } from '../components/IntentSurface';
import { ApprovalsCenterPanel } from '../components/approvals/ApprovalsCenterPanel';
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
    if (u === '/api/wardroom/dms') {
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) }) as any;
    }
    if (u === '/api/config/avatars-enabled') {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ enabled: false }) }) as any;
    }
    if (u.endsWith('/profile')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          id: HOST, isCrew: true, department: 'medical', displayName: 'Ezri',
          specialization: [], hebbianConnections: [],
        }),
      }) as any;
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
  }) as any;
});

afterEach(cleanup);

describe('#1373 local profile viewport geometry', () => {
  let originalState: ReturnType<typeof useStore.getState>;
  let originalWidth: PropertyDescriptor | undefined;
  let originalHeight: PropertyDescriptor | undefined;
  let originalSize: string | null;

  function setViewport(width: number, height: number): void {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: height });
  }

  function mountPanel(size: { w: number; h: number }, position = { x: 100, y: 100 }): HTMLElement {
    localStorage.setItem('hxi_profile_panel_size', JSON.stringify(size));
    useStore.setState({ profilePanelPos: position });
    const { container } = render(<AgentProfilePanel />);
    expect(screen.getByTestId('profile-chat-tab')).toBeVisible();
    return container.firstElementChild as HTMLElement;
  }

  function expectGeometry(panel: HTMLElement, left: number, top: number, width: number, height: number): void {
    const style = getComputedStyle(panel);
    expect(style.boxSizing).toBe('border-box');
    expect(Number.parseFloat(style.left)).toBe(left);
    expect(Number.parseFloat(style.top)).toBe(top);
    expect(Number.parseFloat(style.width)).toBe(width);
    expect(Number.parseFloat(style.height)).toBe(height);
    expect(left).toBeGreaterThanOrEqual(0);
    expect(top).toBeGreaterThanOrEqual(0);
    expect(left + width).toBeLessThanOrEqual(window.innerWidth);
    expect(top + height).toBeLessThanOrEqual(window.innerHeight);
  }

  beforeEach(() => {
    originalState = useStore.getState();
    originalWidth = Object.getOwnPropertyDescriptor(window, 'innerWidth');
    originalHeight = Object.getOwnPropertyDescriptor(window, 'innerHeight');
    originalSize = localStorage.getItem('hxi_profile_panel_size');
    setViewport(900, 1000);
    useStore.setState({
      activeProfileAgent: HOST, activeProfileThreadId: 'g1',
      agents: _seedAgents(), chatThreads: _groupThread(),
      profilePanelPos: { x: 100, y: 100 }, poolToGroup: { medical: 'medical' },
      agentConversations: new Map(), liveGeneration: null,
      notificationNavigation: {
        requestId: Symbol('geometry'), generation: null,
        destination: { hostId: HOST, threadId: 'g1', parentId: 'parent', updated: false },
      },
    });
  });

  afterEach(() => {
    cleanup();
    useStore.setState(originalState, true);
    if (originalWidth) Object.defineProperty(window, 'innerWidth', originalWidth);
    if (originalHeight) Object.defineProperty(window, 'innerHeight', originalHeight);
    if (originalSize === null) localStorage.removeItem('hxi_profile_panel_size');
    else localStorage.setItem('hxi_profile_panel_size', originalSize);
    vi.restoreAllMocks();
  });

  it('keeps a fitting preferred rectangle unchanged', () => {
    const preferred = { w: 420, h: 580 };
    const panel = mountPanel(preferred);
    expectGeometry(panel, 100, 100, 420, 580);
    expect(localStorage.getItem('hxi_profile_panel_size')).toBe(JSON.stringify(preferred));
    expect(useStore.getState().profilePanelPos).toEqual({ x: 100, y: 100 });
  });

  it('keeps the actual profile above Bridge and below approvals without closing Bridge or mutating work', async () => {
    const user = userEvent.setup();
    const closeProfile = vi.fn(useStore.getState().closeAgentProfile);
    useStore.setState({
      bridgeOpen: false, approvalsCenterOpen: false, pendingApprovals: [],
      agentTasks: [], notifications: [], missionControlTasks: [],
      wardRoomDmChannels: [], wardRoomUnread: {}, closeAgentProfile: closeProfile,
    });
    render(<><IntentSurface /><AgentProfilePanel /><ApprovalsCenterPanel /></>);
    const toggle = await screen.findByRole('button', { name: /^BRIDGE/ });
    await user.click(toggle);
    expect(useStore.getState().bridgeOpen).toBe(true);
    expect(screen.getByTestId('profile-chat-tab')).toBeVisible();
    const fixedRoot = (element: HTMLElement): HTMLElement => {
      let current: HTMLElement | null = element;
      while (current && getComputedStyle(current).position !== 'fixed') current = current.parentElement;
      if (!current) throw new Error('Expected an actual fixed panel root');
      return current;
    };
    const bridge = fixedRoot(screen.getByRole('button', { name: 'Close Bridge' }));
    const profile = fixedRoot(screen.getByTitle('Close', { exact: true }));
    expect(Number(getComputedStyle(profile).zIndex)).toBeGreaterThan(Number(getComputedStyle(bridge).zIndex));
    expect(Number(getComputedStyle(bridge).zIndex)).toBeGreaterThan(Number(getComputedStyle(toggle).zIndex));
    act(() => useStore.setState({ approvalsCenterOpen: true }));
    const approvals = fixedRoot(await screen.findByRole('dialog'));
    expect(Number(getComputedStyle(approvals).zIndex)).toBeGreaterThan(Number(getComputedStyle(profile).zIndex));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    const beforeClose = useStore.getState();
    await user.click(screen.getByTitle('Close', { exact: true }));
    expect(closeProfile).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('profile-chat-tab')).toBeNull();
    expect(useStore.getState().activeProfileThreadId).toBeNull();
    expect(useStore.getState().bridgeOpen).toBe(true);
    expect(useStore.getState().notifications).toBe(beforeClose.notifications);
    expect(useStore.getState().composerDrafts).toBe(beforeClose.composerDrafts);
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([, options]) => options?.method === 'POST')).toEqual([]);
  });

  it('caps an oversized saved preference on the initial render without persisting the cap', () => {
    const preferred = { w: 1600, h: 1200 };
    const panel = mountPanel(preferred);
    expectGeometry(panel, 0, 0, 900, 1000);
    expect(localStorage.getItem('hxi_profile_panel_size')).toBe(JSON.stringify(preferred));
    expect(useStore.getState().profilePanelPos).toEqual({ x: 100, y: 100 });
  });

  it.each([
    { position: { x: -100, y: -100 }, left: 0, top: 0 },
    { position: { x: 5000, y: 5000 }, left: 80, top: 240 },
    { position: { x: Number.NaN, y: Number.POSITIVE_INFINITY }, left: 0, top: 0 },
  ])('bounds the stored position $position without rewriting it', ({ position, left, top }) => {
    const panel = mountPanel({ w: 820, h: 760 }, position);
    expectGeometry(panel, left, top, 820, 760);
    expect(useStore.getState().profilePanelPos).toEqual(position);
  });

  it.each([
    null, '', 'null', '{}', 'not-json', '{"w":-1,"h":580}',
    '{"w":420,"h":0}', '{"w":1e400,"h":580}', '{"w":420,"h":1e400}',
    '{"w":"420","h":580}',
  ])('uses finite default dimensions for an invalid or missing preference: %s', (stored) => {
    if (stored === null) localStorage.removeItem('hxi_profile_panel_size');
    else localStorage.setItem('hxi_profile_panel_size', stored);
    const { container } = render(<AgentProfilePanel />);
    expectGeometry(container.firstElementChild as HTMLElement, 100, 100, 420, 580);
  });

  it('restores preferred geometry after shrink and re-expansion without remounting or navigating', () => {
    setViewport(1440, 1000);
    const preferred = { w: 1060, h: 880 };
    const panel = mountPanel(preferred);
    const body = screen.getByTestId('profile-chat-tab');
    const before = useStore.getState();
    const requests = (fetch as ReturnType<typeof vi.fn>).mock.calls.length;
    expectGeometry(panel, 100, 100, 1060, 880);

    act(() => { setViewport(900, 700); window.dispatchEvent(new Event('resize')); });
    expectGeometry(panel, 0, 0, 900, 700);
    expect(localStorage.getItem('hxi_profile_panel_size')).toBe(JSON.stringify(preferred));
    act(() => { setViewport(1440, 1000); window.dispatchEvent(new Event('resize')); });
    expectGeometry(panel, 100, 100, 1060, 880);
    expect(screen.getByTestId('profile-chat-tab')).toBe(body);
    expect(useStore.getState().profilePanelPos).toBe(before.profilePanelPos);
    expect(useStore.getState().notificationNavigation).toBe(before.notificationNavigation);
    expect(useStore.getState().activeProfileThreadId).toBe('g1');
    expect(useStore.getState().composerDrafts).toBe(before.composerDrafts);
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(requests);
  });

  it('drags from effective coordinates and bounds both complete edges of a wide panel', () => {
    const panel = mountPanel({ w: 820, h: 760 });
    expectGeometry(panel, 80, 100, 820, 760);
    fireEvent.mouseDown(screen.getByTestId('group-surface-title'), { clientX: 120, clientY: 120 });
    fireEvent.mouseMove(window, { clientX: 120, clientY: 120 });
    expectGeometry(panel, 80, 100, 820, 760);
    fireEvent.mouseMove(window, { clientX: 5000, clientY: 5000 });
    expectGeometry(panel, 80, 240, 820, 760);
    expect(useStore.getState().profilePanelPos).toEqual({ x: 80, y: 240 });
    fireEvent.mouseMove(window, { clientX: -100, clientY: -100 });
    expectGeometry(panel, 0, 0, 820, 760);
    fireEvent.mouseUp(window);
    fireEvent.mouseMove(window, { clientX: 5000, clientY: 5000 });
    expectGeometry(panel, 0, 0, 820, 760);
  });

  it('resizes from effective dimensions and retains minimum sizes when they fit', () => {
    const panel = mountPanel({ w: 1600, h: 1200 });
    fireEvent.mouseDown(screen.getByLabelText('Resize panel'), { clientX: 900, clientY: 1000 });
    fireEvent.mouseMove(window, { clientX: 850, clientY: 950 });
    expectGeometry(panel, 0, 0, 850, 950);
    expect(localStorage.getItem('hxi_profile_panel_size')).toBe(JSON.stringify({ w: 850, h: 950 }));
    fireEvent.mouseMove(window, { clientX: 5000, clientY: 5000 });
    expectGeometry(panel, 0, 0, 900, 1000);
    fireEvent.mouseMove(window, { clientX: -5000, clientY: -5000 });
    expectGeometry(panel, 0, 0, 320, 360);
    fireEvent.mouseUp(window);
    fireEvent.mouseMove(window, { clientX: 5000, clientY: 5000 });
    expectGeometry(panel, 0, 0, 320, 360);
  });

  it('limits resizing to the space remaining after the effective position', () => {
    const panel = mountPanel({ w: 420, h: 580 });
    fireEvent.mouseDown(screen.getByLabelText('Resize panel'), { clientX: 520, clientY: 680 });
    fireEvent.mouseMove(window, { clientX: 5000, clientY: 5000 });
    expectGeometry(panel, 100, 100, 800, 900);
    expect(useStore.getState().profilePanelPos).toEqual({ x: 100, y: 100 });
    fireEvent.mouseUp(window);
  });

  it('does not let resize minimums exceed a small viewport', () => {
    setViewport(250, 300);
    const panel = mountPanel({ w: 420, h: 580 });
    expectGeometry(panel, 0, 0, 250, 300);
    fireEvent.mouseDown(screen.getByLabelText('Resize panel'), { clientX: 250, clientY: 300 });
    fireEvent.mouseMove(window, { clientX: -100, clientY: -100 });
    expectGeometry(panel, 0, 0, 250, 300);
    fireEvent.mouseUp(window);
  });

  it.each(['drag', 'resize'])('removes viewport and active %s listeners on unmount', (operation) => {
    const addListener = vi.spyOn(window, 'addEventListener');
    const removeListener = vi.spyOn(window, 'removeEventListener');
    mountPanel({ w: 820, h: 760 });
    fireEvent.mouseDown(operation === 'drag'
      ? screen.getByTestId('group-surface-title') : screen.getByLabelText('Resize panel'),
    { clientX: 200, clientY: 200 });
    const listeners = addListener.mock.calls.filter(([type]) => ['resize', 'mousemove', 'mouseup'].includes(type));
    expect(listeners.map(([type]) => type)).toEqual(expect.arrayContaining(['resize', 'mousemove', 'mouseup']));
    cleanup();
    for (const [type, handler] of listeners) {
      expect(removeListener).toHaveBeenCalledWith(type, handler);
    }
  });
});

describe('AD-954a thread-keyed group surface', () => {
  it('fits the complete notification-opened profile at 900px without rewriting its preference', () => {
    const originalState = useStore.getState();
    const originalWidth = Object.getOwnPropertyDescriptor(window, 'innerWidth');
    const originalHeight = Object.getOwnPropertyDescriptor(window, 'innerHeight');
    const originalSize = localStorage.getItem('hxi_profile_panel_size');
    const preferredSize = JSON.stringify({ w: 820, h: 760 });
    const navigation = {
      requestId: Symbol('viewport-regression'), generation: null,
      destination: { hostId: HOST, threadId: 'g1', parentId: 'parent', updated: false },
    };
    try {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: 900 });
      Object.defineProperty(window, 'innerHeight', { configurable: true, value: 1000 });
      localStorage.setItem('hxi_profile_panel_size', preferredSize);
      useStore.setState({
        activeProfileAgent: HOST, activeProfileThreadId: 'g1',
        agents: _seedAgents(), chatThreads: _groupThread(),
        profilePanelPos: { x: 100, y: 100 }, poolToGroup: { medical: 'medical' },
        agentConversations: new Map(), notificationNavigation: navigation, liveGeneration: null,
      });
      expect(useStore.getState().profilePanelPos.x + JSON.parse(preferredSize).w)
        .toBeGreaterThan(window.innerWidth);
      const { container } = render(<AgentProfilePanel />);
      expect(screen.getByTestId('profile-chat-tab')).toBeVisible();
      const panel = container.firstElementChild as HTMLElement;
      const style = getComputedStyle(panel);
      const left = Number.parseFloat(style.left);
      const top = Number.parseFloat(style.top);
      const outerWidth = Number.parseFloat(style.width) + (style.boxSizing === 'border-box' ? 0
        : Number.parseFloat(style.borderLeftWidth) + Number.parseFloat(style.borderRightWidth));
      const outerHeight = Number.parseFloat(style.height) + (style.boxSizing === 'border-box' ? 0
        : Number.parseFloat(style.borderTopWidth) + Number.parseFloat(style.borderBottomWidth));
      expect(left).toBeGreaterThanOrEqual(0);
      expect(top).toBeGreaterThanOrEqual(0);
      expect(outerWidth).toBeGreaterThan(0);
      expect(outerHeight).toBeGreaterThan(0);
      expect(left + outerWidth).toBeLessThanOrEqual(window.innerWidth);
      expect(top + outerHeight).toBeLessThanOrEqual(window.innerHeight);
      expect(localStorage.getItem('hxi_profile_panel_size')).toBe(preferredSize);
      expect(useStore.getState().profilePanelPos).toEqual({ x: 100, y: 100 });
      expect(useStore.getState().notificationNavigation).toBe(navigation);
      expect(useStore.getState().activeProfileThreadId).toBe('g1');
    } finally {
      cleanup();
      useStore.setState(originalState, true);
      if (originalWidth) Object.defineProperty(window, 'innerWidth', originalWidth);
      if (originalHeight) Object.defineProperty(window, 'innerHeight', originalHeight);
      if (originalSize === null) localStorage.removeItem('hxi_profile_panel_size');
      else localStorage.setItem('hxi_profile_panel_size', originalSize);
    }
  });

  it('selects Chat only for the current notification destination and cancels on manual tab navigation', async () => {
    const originalState = useStore.getState();
    try {
      useStore.setState({
        activeProfileAgent: HOST, activeProfileThreadId: 'solo-room',
        agents: _seedAgents(),
        chatThreads: new Map([['solo-room', {
          id: 'solo-room', title: 'Work room', participants: [HOST], task_id: 'parent',
          created_at: 1, last_active_at: 1, metadata: {},
        }]]),
        profilePanelPos: { x: 0, y: 0 }, poolToGroup: { medical: 'medical' },
        agentConversations: new Map(), notificationNavigation: null, liveGeneration: null,
      });
      render(<AgentProfilePanel />);
      expect(await screen.findByTestId('profile-chat-tab')).toBeVisible();
      fireEvent.click(screen.getByText('Profile'));
      expect(screen.queryByTestId('profile-chat-tab')).toBeNull();
      act(() => useStore.getState().setNotificationNavigation({
        requestId: Symbol('stale'), generation: 'old-generation',
        destination: { hostId: HOST, threadId: 'solo-room', parentId: 'parent', updated: false },
      }));
      expect(screen.queryByTestId('profile-chat-tab')).toBeNull();
      act(() => useStore.getState().setNotificationNavigation({
        requestId: Symbol('current'), generation: null,
        destination: { hostId: HOST, threadId: 'solo-room', parentId: 'parent', updated: true },
      }));
      expect(await screen.findByTestId('profile-chat-tab')).toBeVisible();
      fireEvent.click(screen.getByText('Profile'));
      expect(useStore.getState().notificationNavigation).toBeNull();
      expect(screen.queryByTestId('profile-chat-tab')).toBeNull();
    } finally {
      cleanup();
      useStore.setState(originalState, true);
    }
  });

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
