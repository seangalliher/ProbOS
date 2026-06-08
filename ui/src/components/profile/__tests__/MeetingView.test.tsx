// AD-920: tests for the MeetingView avatar gallery. Mocks R3F (Canvas->div,
// useFrame->{}), CrewVRM (stub div exposing onLoadError + recording agentId),
// and the fleet telemetry hook — the canonical CrewAvatarPopout.test.tsx
// pattern (no WebGL, no .vrm). Seeds the REAL store via useStore.setState
// (BF-287). Covers crew-only iteration (captain + non-crew excluded), VRM vs
// badge selection, the onLoadError fallback, the empty state, the caption, the
// missing-thread null path, and the HXI no-emoji guard.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within, act, cleanup } from '@testing-library/react';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

const crewVrmMock = vi.hoisted(() => ({
  renderedAgentIds: [] as string[],
  lastOnLoadError: null as null | (() => void),
}));

vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: any) => <div data-testid="canvas">{children}</div>,
  useFrame: () => {},
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

function mkAgent(p: { id: string; callsign: string; isCrew?: boolean; vrmUrl?: string }): Agent {
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
  if (p.vrmUrl) {
    base.appearance = { vrm_url: p.vrmUrl, expression_overrides: {}, color_palette_hint: '' };
  }
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
  vi.clearAllMocks();
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

  it('renders CrewVRM when the agent has appearance.vrm_url', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'echo'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo', vrmUrl: '/avatars/echo.vrm' }),
    ]);
    render(<MeetingView threadId="t1" />);
    expect(screen.getByTestId('crew-vrm-echo')).toBeTruthy();
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

  it('falls back to badge when CrewVRM onLoadError fires', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'echo'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo', vrmUrl: '/avatars/echo.vrm' }),
    ]);
    render(<MeetingView threadId="t1" />);
    expect(screen.getByTestId('crew-vrm-echo')).toBeTruthy();

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

  it('no-emoji guard', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'echo', 'bones'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo', vrmUrl: '/avatars/echo.vrm' }),
      mkAgent({ id: 'bones', callsign: 'Bones' }),
    ]);
    const { container } = render(<MeetingView threadId="t1" />);
    expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
