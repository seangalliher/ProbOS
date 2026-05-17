/** AD-718e: ProfileInfoTab language-filter dropdown tests. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, fireEvent, cleanup, screen } from '@testing-library/react';
import type { Agent, AgentProfileData } from '../store/types';

vi.mock('../audio/voice', () => ({
  getAvailableVoices: vi.fn(() => []),
  speakResponse: vi.fn(),
  // AD-718e: ProfileInfoTab calls getServerPiperVoices to load the catalog;
  // return a mixed-language list so the filter has something to do.
  getServerPiperVoices: vi.fn(async () => [
    { name: 'en_US-amy', voice: 'amy', region: 'en_US', lang: 'en', quality: 'medium' },
    { name: 'en_GB-alan', voice: 'alan', region: 'en_GB', lang: 'en', quality: 'medium' },
    { name: 'es_ES-mls', voice: 'mls', region: 'es_ES', lang: 'es', quality: 'medium' },
    { name: 'fr_FR-siwis', voice: 'siwis', region: 'fr_FR', lang: 'fr', quality: 'medium' },
  ]),
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

const _profileData = (): AgentProfileData =>
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
    },
  }) as unknown as AgentProfileData;

async function _flush(): Promise<void> {
  // Allow the getServerPiperVoices() promise to resolve before assertion.
  await new Promise(r => setTimeout(r, 0));
  await new Promise(r => setTimeout(r, 0));
}

describe('AD-718e ProfileInfoTab language filter', () => {
  beforeEach(() => {
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(
      async () => new Response('{}', { status: 200 }),
    ) as unknown as typeof fetch;
  });
  afterEach(() => cleanup());

  it('lang_filter_dropdown_renders_distinct_lang_codes_from_voices', async () => {
    render(<ProfileInfoTab profileData={_profileData()} agent={_agent} />);
    await _flush();
    const filter = screen.getByTestId('ad718e-lang-filter') as HTMLSelectElement;
    expect(filter).toBeTruthy();
    const codes = Array.from(filter.options).map(o => o.value);
    // 'All' (empty) + distinct codes sorted.
    expect(codes).toContain('');
    expect(codes).toContain('en');
    expect(codes).toContain('es');
    expect(codes).toContain('fr');
    // Distinct - 'en' must appear exactly once even though two voices share it.
    expect(codes.filter(c => c === 'en').length).toBe(1);
  });

  it('lang_filter_selection_filters_voice_list', async () => {
    const { container } = render(
      <ProfileInfoTab profileData={_profileData()} agent={_agent} />,
    );
    await _flush();
    const filter = screen.getByTestId('ad718e-lang-filter') as HTMLSelectElement;
    fireEvent.change(filter, { target: { value: 'es' } });
    const voiceSelect = container.querySelector(
      'select[aria-label="Voice selector"]',
    ) as HTMLSelectElement;
    expect(voiceSelect).toBeTruthy();
    const names = Array.from(voiceSelect.options).map(o => o.value);
    expect(names).toContain('');  // default option
    expect(names).toContain('es_ES-mls');
    expect(names).not.toContain('en_US-amy');
    expect(names).not.toContain('fr_FR-siwis');
  });
});
