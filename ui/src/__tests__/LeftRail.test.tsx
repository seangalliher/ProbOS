/** AD-719b: Copilot-style left rail tests. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { LeftRail, type LeftRailAgent, type LeftRailThread } from '../components/leftrail/LeftRail';

const agents: LeftRailAgent[] = [
  { agent_id: 'a1', callsign: 'Maya', department: 'engineering', status: 'online' },
  { agent_id: 'a2', callsign: 'Ezri', department: 'counselor', status: 'online' },
  { agent_id: 'a3', callsign: 'Bones', department: 'medical', status: 'offline' },
];

const threads: LeftRailThread[] = [
  { thread_id: 't1', title: 'system check' },
  { thread_id: 't2', title: 'avatar revision' },
];

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* ignore */
  }
});

describe('AD-719b LeftRail', () => {
  it('returns null when hxi_left_rail_enabled is not set (default OFF)', () => {
    const { container } = render(
      <LeftRail agents={agents} recentThreads={threads} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders agents + recent sections when enabled', () => {
    window.localStorage.setItem('hxi_left_rail_enabled', 'true');
    render(<LeftRail agents={agents} recentThreads={threads} />);
    expect(screen.getByTestId('hxi-left-rail')).toBeTruthy();
    expect(screen.getByTestId('hxi-left-rail-agents-section')).toBeTruthy();
    expect(screen.getByTestId('hxi-left-rail-recent-section')).toBeTruthy();
    // Online agents only.
    expect(screen.getByTestId('hxi-left-rail-agent-a1')).toBeTruthy();
    expect(screen.getByTestId('hxi-left-rail-agent-a2')).toBeTruthy();
    expect(screen.queryByTestId('hxi-left-rail-agent-a3')).toBeNull();
  });

  it('clicking an agent fires onSelectAgent with agentId', () => {
    window.localStorage.setItem('hxi_left_rail_enabled', 'true');
    const onSelectAgent = vi.fn();
    render(
      <LeftRail
        agents={agents}
        recentThreads={threads}
        onSelectAgent={onSelectAgent}
      />,
    );
    fireEvent.click(screen.getByTestId('hxi-left-rail-agent-a1'));
    expect(onSelectAgent).toHaveBeenCalledWith('a1');
  });

  it('clicking a thread fires onSelectThread with threadId', () => {
    window.localStorage.setItem('hxi_left_rail_enabled', 'true');
    const onSelectThread = vi.fn();
    render(
      <LeftRail
        agents={agents}
        recentThreads={threads}
        onSelectThread={onSelectThread}
      />,
    );
    fireEvent.click(screen.getByTestId('hxi-left-rail-thread-t1'));
    expect(onSelectThread).toHaveBeenCalledWith('t1');
  });

  it('collapse toggle persists hxi_left_rail_collapsed and updates width', () => {
    window.localStorage.setItem('hxi_left_rail_enabled', 'true');
    render(<LeftRail agents={agents} recentThreads={threads} />);
    const rail = screen.getByTestId('hxi-left-rail');
    expect((rail as HTMLElement).style.width).toBe('240px');
    fireEvent.click(screen.getByTestId('hxi-left-rail-collapse-toggle'));
    expect((rail as HTMLElement).style.width).toBe('56px');
    expect(window.localStorage.getItem('hxi_left_rail_collapsed')).toBe('true');
  });
});
