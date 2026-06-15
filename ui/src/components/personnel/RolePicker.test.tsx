/** AD-1010 vitest — Role Picker (Ship's Office role-template surface).
 * Browse roles (GET /api/crew/roles), pick a crew member, and apply a role's
 * skill+tool template (POST /api/crew/{id}/apply-role). Uses the `deps`
 * injection so no global fetch mock is needed. Upholds the HXI no-emoji guard. */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import RolePicker from './RolePicker';

afterEach(cleanup);

const EMOJI = /\p{Extended_Pictographic}/u;

function roles() {
  return [
    {
      role_id: 'post.counselor', agent_type: 'counselor', callsign: 'Ezri',
      title: "Ship's Counselor", department: 'counseling',
      skills: [{ id: 'active-listening', min_proficiency: 5 }],
      tools: ['read_file'],
      capabilities: ['counselor_wellness_report'],
    },
    {
      role_id: 'post.yeoman', agent_type: 'yeoman', callsign: 'Yeo',
      title: 'Yeoman', department: 'operations',
      skills: [], tools: [], capabilities: [],
    },
  ];
}

function roster() {
  return [
    { agent_id: 'ezri-1', callsign: 'Ezri', post: "Ship's Counselor", department: 'counseling' },
    { agent_id: 'yeo-1', callsign: 'Yeo', post: 'Yeoman', department: 'operations' },
  ];
}

function deps(overrides: any = {}) {
  return {
    fetchRoles: vi.fn(async () => roles()),
    fetchRoster: vi.fn(async () => roster()),
    applyRole: vi.fn(async () => ({
      applied_role: 'post.counselor', agent_type: 'counselor',
      skills_acquired: ['active-listening'], tools_granted: ['read_file'],
    })),
    ...overrides,
  };
}

describe('RolePicker (AD-1010)', () => {
  it('renders every role with its loadout summary', async () => {
    render(<RolePicker deps={deps()} />);
    await waitFor(() => expect(screen.getByTestId('role-post.counselor')).toBeTruthy());
    const card = screen.getByTestId('role-post.counselor');
    expect(card.textContent).toContain("Ship's Counselor");
    expect(card.textContent).toContain('COUNSELING');
    expect(card.textContent).toContain('1 skills · 1 tools · 1 caps');
    expect(screen.getByTestId('role-post.yeoman')).toBeTruthy();
  });

  it('expands a role to show skills, tools, and served capabilities', async () => {
    render(<RolePicker deps={deps()} />);
    await waitFor(() => screen.getByTestId('role-post.counselor'));
    fireEvent.click(screen.getByTestId('role-expand-post.counselor'));
    const detail = screen.getByTestId('role-detail-post.counselor');
    expect(detail.textContent).toContain('active-listening');
    expect(detail.textContent).toContain('read_file');
    expect(detail.textContent).toContain('counselor_wellness_report');
  });

  it('requires a crew member before applying', async () => {
    const d = deps();
    render(<RolePicker deps={d} />);
    await waitFor(() => screen.getByTestId('role-post.counselor'));
    fireEvent.click(screen.getByTestId('role-apply-post.counselor'));
    expect(screen.getByTestId('role-error').textContent).toContain('Select a crew member');
    expect(d.applyRole).not.toHaveBeenCalled();
  });

  it('applies a role to the selected agent and shows the result', async () => {
    const d = deps();
    render(<RolePicker deps={d} />);
    await waitFor(() => screen.getByTestId('role-post.counselor'));
    fireEvent.change(screen.getByTestId('role-agent-select'), { target: { value: 'yeo-1' } });
    fireEvent.click(screen.getByTestId('role-apply-post.counselor'));
    await waitFor(() => expect(d.applyRole).toHaveBeenCalledWith('yeo-1', 'post.counselor'));
    await waitFor(() =>
      expect(screen.getByTestId('role-result-post.counselor').textContent).toContain('1 skills, 1 tools'),
    );
  });

  it('surfaces an apply failure inline', async () => {
    const d = deps({ applyRole: vi.fn(async () => null) });
    render(<RolePicker deps={d} />);
    await waitFor(() => screen.getByTestId('role-post.counselor'));
    fireEvent.change(screen.getByTestId('role-agent-select'), { target: { value: 'yeo-1' } });
    fireEvent.click(screen.getByTestId('role-apply-post.counselor'));
    await waitFor(() => expect(screen.getByTestId('role-error').textContent).toContain('Apply failed'));
  });

  it('renders empty-state copy when no roles are available', async () => {
    render(<RolePicker deps={deps({ fetchRoles: vi.fn(async () => []) })} />);
    await waitFor(() => expect(screen.getByTestId('role-empty')).toBeTruthy());
  });

  it('uses NO emoji (HXI #3)', async () => {
    const { container } = render(<RolePicker deps={deps()} />);
    await waitFor(() => screen.getByTestId('role-post.counselor'));
    expect(EMOJI.test(container.textContent || '')).toBe(false);
    expect(EMOJI.test(container.innerHTML)).toBe(false);
  });
});
