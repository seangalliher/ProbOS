// AD-984b: tests for the MeetingView speaking-pulse reduced-motion gate.
// SEPARATE file from MeetingView.speaking.test.tsx (keeps the AD-923 count
// stable). Mirrors that file's mocks: R3F (Canvas->div, useFrame->{}, useThree
// selector), the fleet telemetry hook, and a CrewVRM stub; seeds the REAL store
// via useStore.setState (BF-287). The speaking RING (state) must ALWAYS apply;
// the pulse ANIMATION is suppressed only when the OS requests reduced motion.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent } from '../../../store/types';

vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: any) => <div data-testid="canvas">{children}</div>,
  useFrame: () => {},
  // AD-947: FaceFraming calls useThree((s) => s.camera).lookAt(...).
  useThree: (sel: any) => sel({ camera: { lookAt: () => {}, updateProjectionMatrix: () => {} } }),
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

function innerOf(slotTestId: string): Element {
  const inner = screen.getByTestId(slotTestId).querySelector('[data-dim]');
  if (!inner) throw new Error(`no inner avatar box for ${slotTestId}`);
  return inner;
}

afterEach(() => {
  cleanup();
  useStore.setState({ agents: new Map(), chatThreads: new Map() });
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe('AD-984b MeetingView reduced-motion pulse gate', () => {
  it('default (no matchMedia): the speaking slot pulses (animation present)', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'] }), [
      mkAgent({ id: 'a1', callsign: 'Vex' }),
      mkAgent({ id: 'a2', callsign: 'Bones' }),
    ]);
    render(<MeetingView threadId="t1" speakingAgentId="a1" />);
    const inner = innerOf('avatar-slot-a1');
    expect(inner.getAttribute('style') || '').toContain('meetingSpeakingPulse');
  });

  it('reduced motion: the speaking slot keeps the ring but drops the pulse', () => {
    vi.stubGlobal('matchMedia', () => ({
      matches: true,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    }));
    seed(mkThread({ id: 't1', participants: ['captain', 'a1', 'a2'] }), [
      mkAgent({ id: 'a1', callsign: 'Vex' }),
      mkAgent({ id: 'a2', callsign: 'Bones' }),
    ]);
    render(<MeetingView threadId="t1" speakingAgentId="a1" />);
    // The slot is still the speaker (state preserved).
    expect(screen.getByTestId('avatar-slot-a1').getAttribute('data-speaking')).toBe('true');
    const style = innerOf('avatar-slot-a1').getAttribute('style') || '';
    // Pulse animation suppressed...
    expect(style).not.toContain('meetingSpeakingPulse');
    // ...but the amber ring box-shadow still applies (state still encoded).
    expect(style).toMatch(/box-shadow|f0b060|240, ?176, ?96/i);
  });
});
