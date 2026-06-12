import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, fireEvent, cleanup } from '@testing-library/react';
import type { Agent, AgentProfileData } from '../store/types';

// AD-718c E8 (UI): wake-phrase row in ProfileInfoTab.

vi.mock('../audio/voice', () => ({
  getServerPiperVoices: vi.fn(async () => null),
  getAvailableVoices: vi.fn(() => []),
  speakResponse: vi.fn(),
  // VoiceProfile type is structural — re-exported as an empty stub.
}));

vi.mock('../store/useStore', () => {
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

import { ProfileInfoTab } from '../components/profile/ProfileInfoTab';

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

describe('ProfileInfoTab wake-phrase row (AD-718c E5)', () => {
  beforeEach(() => {
    // Reset fetch mock per test.
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(
      async () => new Response('{}', { status: 200 }),
    ) as unknown as typeof fetch;
  });
  afterEach(() => {
    cleanup();
  });

  it('renders the wake-phrase input with maxLength=50', () => {
    const { container } = render(
      <ProfileInfoTab profileData={_profileData()} agent={_agent} />,
    );
    const input = container.querySelector(
      '[data-testid="wake-phrase-input"]',
    ) as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(input.maxLength).toBe(50);
  });

  it('populates the input from profileData.voiceProfile.wake_phrase', () => {
    const { container } = render(
      <ProfileInfoTab
        profileData={_profileData({ wake_phrase: 'Ezri' })}
        agent={_agent}
      />,
    );
    const input = container.querySelector(
      '[data-testid="wake-phrase-input"]',
    ) as HTMLInputElement;
    expect(input.value).toBe('Ezri');
  });

  it('persists the wake phrase via PUT on blur', () => {
    const fetchSpy = vi.fn(
      async () => new Response('{}', { status: 200 }),
    ) as unknown as typeof fetch;
    (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchSpy;
    const { container } = render(
      <ProfileInfoTab profileData={_profileData()} agent={_agent} />,
    );
    const input = container.querySelector(
      '[data-testid="wake-phrase-input"]',
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'Ezri' } });
    fireEvent.blur(input);
    expect(fetchSpy).toHaveBeenCalled();
    // AD-983c: ProfileInfoTab now also mounts CapabilityPanel, which fires a
    // GET /api/agent/{id}/capabilities on mount. Find the voice-profile PUT by
    // URL rather than assuming it is the first fetch call.
    const calls = (fetchSpy as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    const putCall = calls.find(
      (c) => typeof c[0] === 'string' && (c[0] as string).includes('/voice-profile'),
    );
    expect(putCall).toBeDefined();
    const body = JSON.parse(
      ((putCall as unknown[])[1] as { body: string }).body,
    );
    expect(body.wake_phrase).toBe('Ezri');
  });
});
