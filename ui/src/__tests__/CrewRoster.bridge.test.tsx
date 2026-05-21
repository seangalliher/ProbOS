/**
 * AD-766: HXI surface for Yeoman on the Bridge.
 *
 * Two behaviors covered:
 *   1. CrewRosterPanel renders a Bridge section when a yeoman entry exists,
 *      with the existing bridge department color token.
 *   2. LeftRail pins Yeo to the top of the 1:1 DM list (default-pinned
 *      per spec §6).
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

import CrewRosterPanel from '../components/CrewRosterPanel';
import { LeftRail, sortYeomanFirst, type LeftRailAgent } from '../components/leftrail/LeftRail';
import { useStore } from '../store/useStore';

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* ignore */
  }
});

describe('AD-766 CrewRoster Bridge section', () => {
  it('renders bridge department containing the yeoman entry', () => {
    // Hydrate the store with a manifest that includes a bridge yeoman.
    useStore.setState({
      crewManifestOpen: true,
      crewManifest: [
        {
          agentId: 'yeo-001',
          agentType: 'yeoman',
          callsign: 'Yeo',
          department: 'bridge',
          post: 'yeoman',
          rank: 'commander',
          trustScore: 0.7,
        },
        {
          agentId: 'counselor-001',
          agentType: 'counselor',
          callsign: 'Troi',
          department: 'bridge',
          post: 'counselor',
          rank: 'lieutenant',
          trustScore: 0.6,
        },
      ],
    });

    render(<CrewRosterPanel />);

    // Bridge section header rendered.
    expect(screen.getByText(/bridge/i)).toBeTruthy();
    // Both bridge crew entries visible by callsign.
    expect(screen.getByText('Yeo')).toBeTruthy();
    expect(screen.getByText('Troi')).toBeTruthy();
  });
});

describe('AD-766 LeftRail Yeo pinning', () => {
  it('sortYeomanFirst moves the Yeo callsign to the top', () => {
    const input: LeftRailAgent[] = [
      { agent_id: 'a1', callsign: 'Maya', department: 'engineering', status: 'online' },
      { agent_id: 'a2', callsign: 'Ezri', department: 'counselor', status: 'online' },
      { agent_id: 'yeo-001', callsign: 'Yeo', department: 'bridge', status: 'online' },
    ];
    const sorted = sortYeomanFirst(input);
    expect(sorted[0].callsign).toBe('Yeo');
    // Stable order preserved for the rest.
    expect(sorted[1].callsign).toBe('Maya');
    expect(sorted[2].callsign).toBe('Ezri');
  });

  it('sortYeomanFirst no-ops when Yeo is absent', () => {
    const input: LeftRailAgent[] = [
      { agent_id: 'a1', callsign: 'Maya', department: 'engineering', status: 'online' },
      { agent_id: 'a2', callsign: 'Ezri', department: 'counselor', status: 'online' },
    ];
    const sorted = sortYeomanFirst(input);
    expect(sorted.map((a) => a.callsign)).toEqual(['Maya', 'Ezri']);
  });

  it('renders Yeo first in the rail when enabled and online', () => {
    window.localStorage.setItem('hxi_left_rail_enabled', 'true');
    const agents: LeftRailAgent[] = [
      { agent_id: 'a1', callsign: 'Maya', department: 'engineering', status: 'online' },
      { agent_id: 'yeo-001', callsign: 'Yeo', department: 'bridge', status: 'online' },
      { agent_id: 'a2', callsign: 'Ezri', department: 'counselor', status: 'online' },
    ];
    render(<LeftRail agents={agents} recentThreads={[]} />);
    const section = screen.getByTestId('hxi-left-rail-agents-section');
    const buttons = section.querySelectorAll('[data-testid^="hxi-left-rail-agent-"]');
    expect(buttons.length).toBe(3);
    expect(buttons[0].getAttribute('data-testid')).toBe('hxi-left-rail-agent-yeo-001');
  });
});
