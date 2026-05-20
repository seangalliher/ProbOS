import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, fireEvent, cleanup, screen } from '@testing-library/react';
import type { Agent, AgentProfileData } from '../../../store/types';

// AD-735: per-agent volume slider in ProfileInfoTab.

vi.mock('../../../audio/voice', () => ({
  getServerPiperVoices: vi.fn(async () => null),
  getAvailableVoices: vi.fn(() => []),
  speakResponse: vi.fn(),
}));

vi.mock('../../../store/useStore', () => {
  const _state = {
    wardRoomDmChannels: [],
    refreshWardRoomDmChannels: vi.fn(),
    activeGame: null,
    challengeAgent: vi.fn(),
  };
  const useStore = ((selector: (s: typeof _state) => unknown) =>
    selector(_state)) as unknown as { getState: () => typeof _state };
  useStore.getState = () => _state;
  return { useStore };
});

import { ProfileInfoTab } from '../ProfileInfoTab';

const _agent: Agent = {
  id: 'a1',
  agentType: 'CognitiveAgent',
  callsign: 'Ezri',
  displayName: 'Counselor',
  pool: 'crew',
  state: 'active',
  confidence: 0.8,
  trust: 0.7,
  tier: 'domain',
  isCrew: true,
  position: [0, 0, 0],
};

const _profileData = (
  override: Partial<AgentProfileData['voiceProfile']> = {},
): AgentProfileData =>
  ({
    rank: 'lieutenant',
    agencyLevel: 'autonomous',
    department: 'medical',
    callsign: 'Ezri',
    displayName: 'Counselor',
    specialization: ['counseling'],
    personality: {},
    proactiveCooldown: null,
    isCrew: true,
    tier: 'domain',
    pool: 'crew',
    hebbianConnections: [],
    memoryCount: 0,
    uptime: 0,
    voiceProfile: {
      voice_name: '',
      pitch: 0.9,
      rate: 0.95,
      volume: 0.8,
      wake_phrase: '',
      ...override,
    },
  }) as unknown as AgentProfileData;

describe('ProfileInfoTab volume slider (AD-735)', () => {
  beforeEach(() => {
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(
      async () => new Response('{}', { status: 200 }),
    ) as unknown as typeof fetch;
  });
  afterEach(() => {
    cleanup();
  });

  it('renders with default value 0.8 and displays 80%', () => {
    const { container } = render(
      <ProfileInfoTab profileData={_profileData()} agent={_agent} />,
    );
    const slider = container.querySelector(
      '[data-testid="volume-slider"]',
    ) as HTMLInputElement;
    expect(slider).not.toBeNull();
    expect(slider.value).toBe('0.8');
    expect(container.textContent).toContain('80%');
  });

  it('renders an existing persisted value (0.35 → "35%")', () => {
    const { container } = render(
      <ProfileInfoTab
        profileData={_profileData({ volume: 0.35 })}
        agent={_agent}
      />,
    );
    const slider = container.querySelector(
      '[data-testid="volume-slider"]',
    ) as HTMLInputElement;
    expect(slider.value).toBe('0.35');
    expect(container.textContent).toContain('35%');
  });

  it('persists volume via PUT on mouse-up', () => {
    const fetchSpy = vi.fn(
      async () => new Response('{}', { status: 200 }),
    ) as unknown as typeof fetch;
    (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchSpy;
    const { container } = render(
      <ProfileInfoTab profileData={_profileData()} agent={_agent} />,
    );
    const slider = container.querySelector(
      '[data-testid="volume-slider"]',
    ) as HTMLInputElement;
    fireEvent.change(slider, { target: { value: '0.5' } });
    fireEvent.mouseUp(slider);
    expect(fetchSpy).toHaveBeenCalled();
    const calls = (fetchSpy as unknown as { mock: { calls: unknown[][] } })
      .mock.calls;
    const putCall = calls.find(
      (c) => (c[1] as { method?: string } | undefined)?.method === 'PUT',
    );
    expect(putCall).toBeDefined();
    const body = JSON.parse((putCall![1] as { body: string }).body);
    expect(body.volume).toBe(0.5);
  });

  it('round-trips in-range boundary values (0 and 1) via change+mouseUp', () => {
    const fetchSpy = vi.fn(
      async () => new Response('{}', { status: 200 }),
    ) as unknown as typeof fetch;
    (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchSpy;
    const { container } = render(
      <ProfileInfoTab profileData={_profileData()} agent={_agent} />,
    );
    const slider = container.querySelector(
      '[data-testid="volume-slider"]',
    ) as HTMLInputElement;

    fireEvent.change(slider, { target: { value: '0' } });
    fireEvent.mouseUp(slider);
    fireEvent.change(slider, { target: { value: '1' } });
    fireEvent.mouseUp(slider);

    const calls = (fetchSpy as unknown as { mock: { calls: unknown[][] } })
      .mock.calls;
    const putBodies = calls
      .filter((c) => (c[1] as { method?: string } | undefined)?.method === 'PUT')
      .map((c) => JSON.parse((c[1] as { body: string }).body).volume);
    expect(putBodies).toContain(0);
    expect(putBodies).toContain(1);
  });

  it('has an accessible label "Volume"', () => {
    render(<ProfileInfoTab profileData={_profileData()} agent={_agent} />);
    const slider = screen.getByRole('slider', { name: 'Volume' });
    expect(slider).toBeDefined();
  });
});
