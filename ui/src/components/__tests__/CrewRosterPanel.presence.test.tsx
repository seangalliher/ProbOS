/**
 * AD-930: CrewRosterPanel presence dots.
 *
 * Mirrors the CrewRoster.bridge real-store seeding (useStore.setState) — each
 * crew row renders a PresenceDot driven by the ambient `presence` slice. The
 * roster polls `fetchPresence` while open; we replace it with a spy so the real
 * /api/crew/presence fetch never fires and the poll can be asserted. Includes
 * the HXI no-emoji guard.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

import CrewRosterPanel from '../CrewRosterPanel';
import { useStore } from '../../store/useStore';
import type { CrewManifestEntry } from '../../store/types';

const EMOJI_RE = /\p{Extended_Pictographic}/u;

function entry(agentId: string, callsign: string): CrewManifestEntry {
  return {
    agentId,
    agentType: callsign.toLowerCase(),
    callsign,
    department: 'engineering',
    post: 'engineer',
    rank: 'commander',
    trustScore: 0.7,
  };
}

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* ignore */
  }
});

afterEach(() => {
  cleanup();
  useStore.setState({ crewManifestOpen: false, crewManifest: null, presence: {} });
});

describe('CrewRosterPanel presence (AD-930)', () => {
  it('renders a presence dot per row from the presence slice and polls while open', () => {
    const spy = vi.fn(async () => {});
    useStore.setState({
      crewManifestOpen: true,
      crewManifest: [entry('forge-1', 'Forge')],
      presence: { 'forge-1': 'working' },
      fetchPresence: spy,
    });

    render(<CrewRosterPanel />);

    const dots = screen.getAllByTestId('presence-dot');
    expect(dots.some((d) => d.getAttribute('data-presence') === 'working')).toBe(true);
    // The open effect fires the initial poll.
    expect(spy).toHaveBeenCalled();
  });

  it('renders offline for an agent absent from the presence map', () => {
    useStore.setState({
      crewManifestOpen: true,
      crewManifest: [entry('ghost-1', 'Ghost')],
      presence: {},
      fetchPresence: vi.fn(async () => {}),
    });

    render(<CrewRosterPanel />);

    const dots = screen.getAllByTestId('presence-dot');
    expect(dots.some((d) => d.getAttribute('data-presence') === 'offline')).toBe(true);
  });

  it('renders no emoji (HXI Design Principle #3)', () => {
    useStore.setState({
      crewManifestOpen: true,
      crewManifest: [entry('forge-1', 'Forge')],
      presence: { 'forge-1': 'in_meeting' },
      fetchPresence: vi.fn(async () => {}),
    });

    const { container } = render(<CrewRosterPanel />);
    expect(container.textContent || '').not.toMatch(EMOJI_RE);
  });
});
