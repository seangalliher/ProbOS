/** AD-1011 vitest — Skill Coverage (ship-wide skill registry view, #815 view 1).
 * Read-only coverage lens: per-skill holder count + a coverage bar + gap flag,
 * expandable holders. Uses `deps` injection so no global fetch mock is needed.
 * Upholds the HXI no-emoji guard. */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import SkillCoverage from './SkillCoverage';

afterEach(cleanup);

const EMOJI = /\p{Extended_Pictographic}/u;

function coverage() {
  return {
    crew_count: 2,
    gap_count: 1,
    skills: [
      {
        skill_id: 'active-listening', name: 'Active Listening', category: 'role',
        holder_count: 2, gap: false,
        holders: [
          { agent_id: 'ezri-1', callsign: 'Ezri', proficiency: 4, proficiency_label: 'apply' },
          { agent_id: 'yeo-1', callsign: 'Yeo', proficiency: 2, proficiency_label: 'follow' },
        ],
      },
      {
        skill_id: 'warp-theory', name: 'Warp Theory', category: 'role',
        holder_count: 0, gap: true, holders: [],
      },
    ],
  };
}

function deps(overrides: any = {}) {
  return { fetchCoverage: vi.fn(async () => coverage()), ...overrides };
}

describe('SkillCoverage (AD-1011)', () => {
  it('renders the coverage summary line', async () => {
    render(<SkillCoverage deps={deps()} />);
    await waitFor(() => expect(screen.getByTestId('skill-coverage')).toBeTruthy());
    expect(screen.getByTestId('skill-coverage-summary').textContent).toContain('2 skills · 2 crew · 1 gaps');
  });

  it('renders a row per skill with holder count and gap flag', async () => {
    render(<SkillCoverage deps={deps()} />);
    await waitFor(() => screen.getByTestId('skill-coverage'));
    expect(screen.getByTestId('coverage-active-listening').textContent).toContain('2 crew');
    expect(screen.getByTestId('coverage-warp-theory').textContent).toContain('GAP');
  });

  it('expands a held skill to show its holders + proficiency', async () => {
    render(<SkillCoverage deps={deps()} />);
    await waitFor(() => screen.getByTestId('skill-coverage'));
    fireEvent.click(screen.getByTestId('coverage-row-active-listening'));
    const holders = screen.getByTestId('coverage-holders-active-listening');
    expect(holders.textContent).toContain('Ezri');
    expect(holders.textContent).toContain('apply');
    expect(holders.textContent).toContain('Yeo');
  });

  it('shows empty-state copy when the registry is empty', async () => {
    render(<SkillCoverage deps={deps({ fetchCoverage: vi.fn(async () => ({ skills: [], crew_count: 0, gap_count: 0 })) })} />);
    await waitFor(() => expect(screen.getByTestId('skill-coverage-empty')).toBeTruthy());
  });

  it('uses NO emoji (HXI #3)', async () => {
    const { container } = render(<SkillCoverage deps={deps()} />);
    await waitFor(() => screen.getByTestId('skill-coverage'));
    expect(EMOJI.test(container.textContent || '')).toBe(false);
    expect(EMOJI.test(container.innerHTML)).toBe(false);
  });
});
