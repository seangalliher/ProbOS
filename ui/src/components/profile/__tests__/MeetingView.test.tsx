// AD-920: tests for the MeetingView avatar gallery. Mocks R3F (Canvas->div,
// useFrame->{}), CrewVRM (stub div exposing onLoadError + recording agentId),
// and the fleet telemetry hook — the canonical CrewAvatarPopout.test.tsx
// pattern (no WebGL, no .vrm). Seeds the REAL store via useStore.setState
// (BF-287). Covers crew-only iteration (captain + non-crew excluded), VRM vs
// badge selection, the onLoadError fallback, the empty state, the caption, the
// missing-thread null path, and the HXI no-emoji guard.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, act, cleanup, fireEvent } from '@testing-library/react';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

const crewVrmMock = vi.hoisted(() => ({
  renderedAgentIds: [] as string[],
  lastOnLoadError: null as null | (() => void),
}));

// BF-613: the crew VRM is hydrated from GET /api/agent/{id}/profile (NOT the
// base store Agent, which never carries appearance). Drive it through a fetch
// stub keyed by agent id; an unkeyed agent returns no appearance -> badge.
const profileMock = vi.hoisted(() => ({ vrmByAgent: {} as Record<string, string> }));

vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: any) => <div data-testid="canvas">{children}</div>,
  useFrame: () => {},
  // AD-947/AD-964: FaceFraming calls useThree((s) => s.camera) then
  // camera.position.set(...) + camera.lookAt(...) + updateProjectionMatrix().
  useThree: (sel: any) => sel({ camera: { position: { set: () => {} }, lookAt: () => {}, updateProjectionMatrix: () => {} } }),
}));

vi.mock('../../../avatars/useFleetAvatarTelemetry', () => ({
  useFleetAvatarTelemetry: (_opts: any) => {},
}));

vi.mock('../CrewVRM', () => ({
  CrewVRM: (props: any) => {
    crewVrmMock.lastOnLoadError = props.onLoadError;
    crewVrmMock.renderedAgentIds.push(props.agentId);
    return <div data-testid={`crew-vrm-${props.agentId}`} />;
  },
}));

import { MeetingView } from '../MeetingView';

function mkAgent(p: { id: string; callsign: string; isCrew?: boolean }): Agent {
  const base: Record<string, unknown> = {
    id: p.id,
    agentType: 'crew',
    callsign: p.callsign,
    displayName: '',
    pool: 'bridge',
    state: 'active',
    confidence: 1,
    trust: 0.5,
    tier: 'domain',
    isCrew: p.isCrew ?? true,
    position: [0, 0, 0],
    department: 'science',
  };
  return base as unknown as Agent;
}

function mkThread(over: Partial<AD791aChatThreadView> & { id: string }): AD791aChatThreadView {
  return {
    id: over.id,
    title: over.title ?? 'Meeting',
    participants: over.participants ?? [],
    created_at: 0,
    last_active_at: 0,
    metadata: over.metadata,
  };
}

function seed(thread: AD791aChatThreadView, agentsList: Agent[]): void {
  const am = new Map<string, Agent>();
  for (const a of agentsList) am.set(a.id, a);
  const tm = new Map<string, AD791aChatThreadView>();
  tm.set(thread.id, thread);
  useStore.setState({ agents: am, chatThreads: tm });
}

afterEach(() => {
  cleanup();
  useStore.setState({ agents: new Map(), chatThreads: new Map() });
  crewVrmMock.renderedAgentIds = [];
  crewVrmMock.lastOnLoadError = null;
  profileMock.vrmByAgent = {};
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

beforeEach(() => {
  // BF-613: stub the per-agent profile fetch the AvatarSlot now uses to hydrate
  // the VRM. Returns appearance only for agents registered in profileMock.
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const m = /\/api\/agent\/([^/]+)\/profile/.exec(String(url));
    const vrm = m ? profileMock.vrmByAgent[m[1]] : undefined;
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(
        vrm
          ? { appearance: { vrm_url: vrm, expression_overrides: {}, color_palette_hint: '' } }
          : {},
      ),
    } as Response);
  }));
});

describe('AD-920 MeetingView gallery', () => {
  it('renders one slot per crew participant; excludes captain and non-crew', () => {
    seed(
      mkThread({ id: 't1', participants: ['captain', 'echo', 'bones', 'ext'] }),
      [
        mkAgent({ id: 'echo', callsign: 'Echo' }),
        mkAgent({ id: 'bones', callsign: 'Bones' }),
        mkAgent({ id: 'ext', callsign: 'Ext', isCrew: false }),
        mkAgent({ id: 'captain', callsign: 'Cap', isCrew: false }),
      ],
    );
    const { container } = render(<MeetingView threadId="t1" />);
    const slots = container.querySelectorAll('[data-testid^="avatar-slot-"]');
    expect(slots).toHaveLength(2);
    expect(screen.getByTestId('avatar-slot-echo')).toBeTruthy();
    expect(screen.getByTestId('avatar-slot-bones')).toBeTruthy();
    expect(screen.queryByTestId('avatar-slot-captain')).toBeNull();
    expect(screen.queryByTestId('avatar-slot-ext')).toBeNull();
  });

  it('renders CrewVRM when the agent profile has appearance.vrm_url (BF-613: hydrated via /profile)', async () => {
    profileMock.vrmByAgent.echo = '/avatars/echo.vrm';
    seed(mkThread({ id: 't1', participants: ['captain', 'echo'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo' }),
    ]);
    render(<MeetingView threadId="t1" />);
    expect(await screen.findByTestId('crew-vrm-echo')).toBeTruthy();
  });

  it('renders AgentAvatarBadge when appearance is absent', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'bones'] }), [
      mkAgent({ id: 'bones', callsign: 'Bones' }),
    ]);
    render(<MeetingView threadId="t1" />);
    const slot = screen.getByTestId('avatar-slot-bones');
    expect(within(slot).getByTestId('agent-avatar-badge')).toBeTruthy();
    expect(screen.queryByTestId('crew-vrm-bones')).toBeNull();
  });

  it('falls back to badge when CrewVRM onLoadError fires', async () => {
    profileMock.vrmByAgent.echo = '/avatars/echo.vrm';
    seed(mkThread({ id: 't1', participants: ['captain', 'echo'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo' }),
    ]);
    render(<MeetingView threadId="t1" />);
    expect(await screen.findByTestId('crew-vrm-echo')).toBeTruthy();

    act(() => {
      crewVrmMock.lastOnLoadError?.();
    });

    expect(screen.queryByTestId('crew-vrm-echo')).toBeNull();
    const slot = screen.getByTestId('avatar-slot-echo');
    expect(within(slot).getByTestId('agent-avatar-badge')).toBeTruthy();
  });

  it('renders the empty-state when there are no crew participants', () => {
    seed(mkThread({ id: 't1', participants: ['captain'] }), [
      mkAgent({ id: 'captain', callsign: 'Cap', isCrew: false }),
    ]);
    render(<MeetingView threadId="t1" />);
    expect(screen.getByTestId('meeting-view')).toBeTruthy();
    expect(screen.getByText('No crew in this meeting yet.')).toBeTruthy();
  });

  it('caption shows the callsign', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'echo'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo' }),
    ]);
    render(<MeetingView threadId="t1" />);
    expect(screen.getByTestId('avatar-caption-echo').textContent).toBe('Echo');
  });

  it('returns null when the thread is missing', () => {
    render(<MeetingView threadId="missing" />);
    expect(screen.queryByTestId('meeting-view')).toBeNull();
  });

  it('no-emoji guard', async () => {
    profileMock.vrmByAgent.echo = '/avatars/echo.vrm';
    seed(mkThread({ id: 't1', participants: ['captain', 'echo', 'bones'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo' }),
      mkAgent({ id: 'bones', callsign: 'Bones' }),
    ]);
    const { container } = render(<MeetingView threadId="t1" />);
    await screen.findByTestId('crew-vrm-echo');
    expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});

describe('AD-974 MeetingView drag-to-resize', () => {
  function slotWidth(id: string): number {
    const el = screen.getByTestId(`avatar-slot-${id}`) as HTMLElement;
    return parseInt(el.style.width, 10);
  }

  it('renders the resize handle', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'echo'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo' }),
    ]);
    render(<MeetingView threadId="t1" />);
    expect(screen.getByTestId('meeting-resize-handle')).toBeTruthy();
  });

  it('dragging the handle DOWN enlarges the slots and persists the scale', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'echo'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo' }),
    ]);
    render(<MeetingView threadId="t1" />);
    expect(slotWidth('echo')).toBe(120); // scale 1 (default)
    const handle = screen.getByTestId('meeting-resize-handle');
    // Drag down 220px == +1.0 scale -> width 240.
    fireEvent.mouseDown(handle, { clientY: 100 });
    act(() => { window.dispatchEvent(new MouseEvent('mousemove', { clientY: 320 })); });
    expect(slotWidth('echo')).toBe(240);
    act(() => { window.dispatchEvent(new MouseEvent('mouseup')); });
    // Persisted for reopen.
    expect(localStorage.getItem('hxi_meeting_gallery_scale')).toBe('2');
  });

  it('clamps the scale to the [1,3] range', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'echo'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo' }),
    ]);
    render(<MeetingView threadId="t1" />);
    const handle = screen.getByTestId('meeting-resize-handle');
    // Drag down far past the max (220px/unit, so 1000px -> +4.5, clamped to 3).
    fireEvent.mouseDown(handle, { clientY: 0 });
    act(() => { window.dispatchEvent(new MouseEvent('mousemove', { clientY: 1000 })); });
    expect(slotWidth('echo')).toBe(360); // 120 * 3 (clamped max)
    // Drag up below the min -> clamped to 1 (width 120).
    act(() => { window.dispatchEvent(new MouseEvent('mousemove', { clientY: -1000 })); });
    expect(slotWidth('echo')).toBe(120);
    act(() => { window.dispatchEvent(new MouseEvent('mouseup')); });
  });

  it('restores the persisted scale on mount', () => {
    localStorage.setItem('hxi_meeting_gallery_scale', '2');
    seed(mkThread({ id: 't1', participants: ['captain', 'echo'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo' }),
    ]);
    render(<MeetingView threadId="t1" />);
    expect(slotWidth('echo')).toBe(240); // 120 * 2 restored
    localStorage.removeItem('hxi_meeting_gallery_scale');
  });
});
