// AD-939: tests for the Captain gallery slot in MeetingView. SEPARATE file
// from MeetingView.test.tsx / MeetingView.speaking.test.tsx (keeps those
// counts stable). Mirrors their mocks — R3F (Canvas->div, useFrame->{}), the
// fleet telemetry hook, a CrewVRM stub — and ALSO mocks the camera/screen
// stream getters so the live-video path is deterministic; the camera/screen
// stores are the REAL zustand stores toggled via setState (BF-287). Covers:
// the slot always renders, camera>screen>icon selection, the play()/srcObject
// attach attempt, crew slots rendering alongside, and the HXI no-emoji guard.
import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import { useCameraStore } from '../../../store/useCameraStore';
import { useScreenStore } from '../../../store/useScreenStore';
import type { Agent } from '../../../store/types';

const camMock = vi.hoisted(() => ({ stream: null as MediaStream | null }));
const scrMock = vi.hoisted(() => ({ stream: null as MediaStream | null }));

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

vi.mock('../../../hooks/useCameraStream', () => ({
  getCameraStream: () => camMock.stream,
}));

vi.mock('../../../hooks/useScreenStream', () => ({
  getScreenStream: () => scrMock.stream,
}));

import { MeetingView } from '../MeetingView';

// jsdom implements neither HTMLMediaElement.play nor a srcObject accessor;
// stub both so the attach effect runs without throwing and can be asserted.
const playMock = vi.fn().mockResolvedValue(undefined);
beforeAll(() => {
  Object.defineProperty(HTMLMediaElement.prototype, 'play', {
    configurable: true,
    writable: true,
    value: playMock,
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'srcObject', {
    configurable: true,
    get(this: { _srcObject?: MediaStream | null }) {
      return this._srcObject ?? null;
    },
    set(this: { _srcObject?: MediaStream | null }, v: MediaStream | null) {
      this._srcObject = v;
    },
  });
});

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
  useCameraStore.setState({ active: false });
  useScreenStore.setState({ active: false });
  camMock.stream = null;
  scrMock.stream = null;
  playMock.mockClear();
});

describe('AD-939 MeetingView Captain slot', () => {
  it('renders the Captain slot first in the gallery', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'echo'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo' }),
    ]);
    const { container } = render(<MeetingView threadId="t1" />);
    expect(screen.getByTestId('captain-slot')).toBeTruthy();
    // Captain slot precedes the crew slot in document order (rendered first).
    const slots = container.querySelectorAll(
      '[data-testid="captain-slot"], [data-testid^="avatar-slot-"]',
    );
    expect(slots[0].getAttribute('data-testid')).toBe('captain-slot');
  });

  it('camera active -> shows captain-video (camera preferred), attaches the stream', () => {
    const fakeStream = {} as unknown as MediaStream;
    camMock.stream = fakeStream;
    useCameraStore.setState({ active: true });
    seed(mkThread({ id: 't1', participants: ['captain', 'echo'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo' }),
    ]);
    render(<MeetingView threadId="t1" />);
    const video = screen.getByTestId('captain-video') as HTMLVideoElement;
    expect(video).toBeTruthy();
    expect(screen.queryByTestId('captain-icon')).toBeNull();
    // The effect attempted to attach + play the live stream.
    expect(video.srcObject).toBe(fakeStream);
    expect(playMock).toHaveBeenCalled();
  });

  it('screen active (camera off) -> shows captain-video from the screen stream', () => {
    const fakeStream = {} as unknown as MediaStream;
    scrMock.stream = fakeStream;
    useScreenStore.setState({ active: true });
    seed(mkThread({ id: 't1', participants: ['captain', 'echo'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo' }),
    ]);
    render(<MeetingView threadId="t1" />);
    const video = screen.getByTestId('captain-video') as HTMLVideoElement;
    expect(video).toBeTruthy();
    expect(video.srcObject).toBe(fakeStream);
  });

  it('neither active -> shows the captain-icon, no video', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'echo'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo' }),
    ]);
    render(<MeetingView threadId="t1" />);
    expect(screen.getByTestId('captain-icon')).toBeTruthy();
    expect(screen.queryByTestId('captain-video')).toBeNull();
  });

  it('crew slots still render alongside the Captain slot', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'echo', 'bones'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo' }),
      mkAgent({ id: 'bones', callsign: 'Bones' }),
    ]);
    render(<MeetingView threadId="t1" />);
    expect(screen.getByTestId('captain-slot')).toBeTruthy();
    expect(screen.getByTestId('avatar-slot-echo')).toBeTruthy();
    expect(screen.getByTestId('avatar-slot-bones')).toBeTruthy();
  });

  it('no-emoji guard (icon fallback path)', () => {
    seed(mkThread({ id: 't1', participants: ['captain', 'echo'] }), [
      mkAgent({ id: 'echo', callsign: 'Echo' }),
    ]);
    const { container } = render(<MeetingView threadId="t1" />);
    expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
