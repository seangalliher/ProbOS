/** AD-718a: ProfileInfoTab voice-proposal Vitest coverage. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';

vi.mock('../audio/voice', () => ({
  speakResponse: vi.fn(),
  getAvailableVoices: () => [],
}));

import { ProfileInfoTab } from '../components/profile/ProfileInfoTab';
import { useStore } from '../store/useStore';
import type { Agent, AgentProfileData } from '../store/types';

const AGENT: Agent = {
  id: 'agent-007',
  name: 'Counselor',
  agent_type: 'counselor',
  state: 'active',
  isCrew: true,
} as unknown as Agent;

const PROFILE_DATA: AgentProfileData = {
  id: 'agent-007',
  rank: 'lieutenant',
  agencyLevel: 'autonomous',
  department: 'bridge',
  callsign: 'Troi',
  displayName: 'Counselor',
  personality: {},
  specialization: [],
  trust: 0.55,
  trustHistory: [],
  hebbianConnections: [],
  voiceProfile: { voice_name: '', pitch: 0.9, rate: 0.95, volume: 0.8 },
} as unknown as AgentProfileData;

const PROPOSAL_BODY = {
  agent_id: 'agent-007',
  voice_profile: { voice_name: 'Aria', pitch: 1.05, rate: 0.92, volume: 0.85 },
  rationale: 'warm cadence',
};

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({
    wardRoomDmChannels: [],
    refreshWardRoomDmChannels: () => {},
    activeGame: null,
    challengeAgent: () => {},
  } as any);
});

function setupFetch(handlers: Record<string, (init?: RequestInit) => Promise<unknown>>): void {
  global.fetch = vi.fn(async (url: any, init?: any) => {
    const u = String(url);
    for (const [key, handler] of Object.entries(handlers)) {
      if (u.endsWith(key)) {
        const data = await handler(init);
        return { ok: true, status: 200, json: () => Promise.resolve(data) } as any;
      }
    }
    return { ok: true, status: 200, json: () => Promise.resolve({}) } as any;
  }) as any;
}

describe('AD-718a ProfileInfoTab voice proposal', () => {
  it('renders the Propose voice button', () => {
    setupFetch({});
    render(<ProfileInfoTab profileData={PROFILE_DATA} agent={AGENT} />);
    expect(screen.getByLabelText('Propose voice')).toBeTruthy();
  });

  it('Propose voice button calls the propose endpoint and shows preview', async () => {
    setupFetch({
      '/voice-profile/propose': async () => PROPOSAL_BODY,
    });
    render(<ProfileInfoTab profileData={PROFILE_DATA} agent={AGENT} />);
    fireEvent.click(screen.getByLabelText('Propose voice'));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalled();
    });
    const calls = (global.fetch as any).mock.calls;
    const proposeCall = calls.find((c: any[]) => String(c[0]).endsWith('/voice-profile/propose'));
    expect(proposeCall).toBeTruthy();
    const body = JSON.parse(proposeCall[1].body);
    expect(body).toEqual({ captain_note: '' });

    // Preview region renders.
    await screen.findByRole('region', { name: /voice proposal preview/i });
    expect(screen.getByText(/warm cadence/)).toBeTruthy();
  });

  it('Approve calls PUT with proposal_rationale', async () => {
    setupFetch({
      '/voice-profile/propose': async () => PROPOSAL_BODY,
    });
    render(<ProfileInfoTab profileData={PROFILE_DATA} agent={AGENT} />);
    fireEvent.click(screen.getByLabelText('Propose voice'));
    await screen.findByRole('region', { name: /voice proposal preview/i });

    fireEvent.click(screen.getByLabelText('Approve voice proposal'));

    await waitFor(() => {
      const calls = (global.fetch as any).mock.calls;
      const putCall = calls.find(
        (c: any[]) => String(c[0]).endsWith('/voice-profile')
                       && c[1]?.method === 'PUT',
      );
      expect(putCall).toBeTruthy();
      const body = JSON.parse(putCall[1].body);
      expect(body.proposal_rationale).toBe('warm cadence');
      expect(body.pitch).toBe(1.05);
      expect(body.voice_name).toBe('Aria');
    });
  });

  it('Reject clears preview without calling PUT', async () => {
    setupFetch({
      '/voice-profile/propose': async () => PROPOSAL_BODY,
    });
    render(<ProfileInfoTab profileData={PROFILE_DATA} agent={AGENT} />);
    fireEvent.click(screen.getByLabelText('Propose voice'));
    await screen.findByRole('region', { name: /voice proposal preview/i });

    fireEvent.click(screen.getByLabelText('Reject voice proposal'));

    await waitFor(() => {
      expect(screen.queryByRole('region', { name: /voice proposal preview/i })).toBeNull();
    });
    const putCalls = (global.fetch as any).mock.calls.filter(
      (c: any[]) => String(c[0]).endsWith('/voice-profile') && c[1]?.method === 'PUT',
    );
    expect(putCalls.length).toBe(0);
  });

  it('Request revisions resubmits propose with the captain note', async () => {
    setupFetch({
      '/voice-profile/propose': async () => PROPOSAL_BODY,
    });
    render(<ProfileInfoTab profileData={PROFILE_DATA} agent={AGENT} />);
    fireEvent.click(screen.getByLabelText('Propose voice'));
    await screen.findByRole('region', { name: /voice proposal preview/i });

    fireEvent.click(screen.getByLabelText('Request voice revisions'));
    const noteInput = await screen.findByLabelText('Captain revision note');
    fireEvent.change(noteInput, { target: { value: 'lower pitch' } });
    fireEvent.click(screen.getByLabelText('Submit revision note'));

    await waitFor(() => {
      const proposeCalls = (global.fetch as any).mock.calls.filter(
        (c: any[]) => String(c[0]).endsWith('/voice-profile/propose'),
      );
      expect(proposeCalls.length).toBe(2);
      const last = JSON.parse(proposeCalls[1][1].body);
      expect(last.captain_note).toBe('lower pitch');
    });
  });
});
