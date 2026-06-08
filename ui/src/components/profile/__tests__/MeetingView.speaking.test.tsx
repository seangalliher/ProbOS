// AD-923: tests for the MeetingView who's-speaking highlight + presence
// header. SEPARATE file from MeetingView.test.tsx (keeps the AD-920 count
// stable). Mirrors that file's mocks: R3F (Canvas->div, useFrame->{}), the
// fleet telemetry hook, and a CrewVRM stub; seeds the REAL store via
// useStore.setState (BF-287). Covers the lit speaker (data-speaking="true"),
// dimmed non-speakers (data-dim="true"), the neutral idle state, the presence
// count, the Captain-present chip, and the HXI no-emoji guard.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: any) => <div data-testid="canvas">{children}</div>,
  useFrame: () => {},
}));

vi.mock('../../../avatars/useFleetAvatarTelemetry', () => ({
  useFleetAvatarTelemetry: (_opts: any) => {},
}));

vi.mock('../CrewVRM', () => ({
  CrewVRM: (props: any) => <div data-testid={`crew-vrm-${props.agentId}`} />,
}));

import { MeetingView } from '../MeetingView';

function mkAgent(p: { id: string; callsign: string; isCrew?: boolean }): Agent {
  return {
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
    position: [0, 0, 0] as [number, number, number],
    department: 'science',
  } as unknown as Agent;
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
  vi.clearAllMocks();
});

describe('AD-923 MeetingView speaking highlight + presence', () => {
  it('lights the speaking slot (data-speaking="true")', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'] }), [
      mkAgent({ id: 'a1', callsign: 'Vex' }),
      mkAgent({ id: 'a2', callsign: 'Bones' }),
    ]);
    render(<MeetingView threadId="t1" speakingAgentId="a1" />);
    expect(screen.getByTestId('avatar-slot-a1').getAttribute('data-speaking')).toBe('true');
  });

  it('dims the non-speaking slots while someone is speaking', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'] }), [
      mkAgent({ id: 'a1', callsign: 'Vex' }),
      mkAgent({ id: 'a2', callsign: 'Bones' }),
    ]);
    render(<MeetingView threadId="t1" speakingAgentId="a1" />);
    const other = screen.getByTestId('avatar-slot-a2');
    expect(other.getAttribute('data-speaking')).toBe('false');
    const inner = other.querySelector('[data-dim]');
    expect(inner?.getAttribute('data-dim')).toBe('true');
  });

  it('idle (speakingAgentId=null): nobody lit, nobody dimmed', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'] }), [
      mkAgent({ id: 'a1', callsign: 'Vex' }),
      mkAgent({ id: 'a2', callsign: 'Bones' }),
    ]);
    render(<MeetingView threadId="t1" speakingAgentId={null} />);
    for (const id of ['a1', 'a2']) {
      const slot = screen.getByTestId(`avatar-slot-${id}`);
      expect(slot.getAttribute('data-speaking')).toBe('false');
      expect(slot.querySelector('[data-dim]')?.getAttribute('data-dim')).toBe('false');
    }
  });

  it('presence header renders the crew count (captain + non-crew excluded)', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'a1', 'a2', 'ext'] }), [
      mkAgent({ id: 'a1', callsign: 'Vex' }),
      mkAgent({ id: 'a2', callsign: 'Bones' }),
      mkAgent({ id: 'ext', callsign: 'Ext', isCrew: false }),
    ]);
    render(<MeetingView threadId="t1" />);
    const slots = screen.getByTestId('meeting-view').querySelectorAll('[data-testid^="avatar-slot-"]');
    expect(slots).toHaveLength(2);
    expect(screen.getByTestId('meeting-presence').textContent).toContain('2 in meeting');
  });

  it('renders the Captain-present chip', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'a1'] }), [
      mkAgent({ id: 'a1', callsign: 'Vex' }),
    ]);
    render(<MeetingView threadId="t1" />);
    expect(screen.getByTestId('captain-present')).toBeTruthy();
  });

  it('no-emoji guard (incl. the injected <style>)', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'] }), [
      mkAgent({ id: 'a1', callsign: 'Vex' }),
      mkAgent({ id: 'a2', callsign: 'Bones' }),
    ]);
    const { container } = render(<MeetingView threadId="t1" speakingAgentId="a1" />);
    expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
