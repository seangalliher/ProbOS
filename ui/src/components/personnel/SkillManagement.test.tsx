/** AD-902 (Wave 257) vitest — Developmental (T3) skill management view.
 * Lists the agent's skill records, acquires from the registry catalog, re-levels
 * up (one click) and down (two-step confirm), soft-suspends (two-step confirm)
 * and reinstates — all over the AD-902 crew skill endpoints. HXI no-emoji guard. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import SkillManagement from './SkillManagement';

const RECORD = {
  skill_id: 'basic',
  name: 'Basic Skill',
  category: 'acquired',
  proficiency: 3,
  proficiency_label: 'apply',
  suspended: false,
};

const SUSPENDED_RECORD = {
  skill_id: 'basic',
  name: 'Basic Skill',
  category: 'acquired',
  proficiency: 3,
  proficiency_label: 'apply',
  suspended: true,
};

const CATALOG = [
  { skill_id: 'basic', name: 'Basic Skill', category: 'acquired' },
  { skill_id: 'advanced', name: 'Advanced Skill', category: 'acquired' },
];

/** Per-URL fetch stub. Records POST/PATCH/DELETE bodies for assertions. */
function stubFetch(
  records: unknown[],
  calls: Array<{ url: string; method: string; body?: unknown }>,
  opts: { acquireOk?: boolean; acquireDetail?: string } = {},
) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const method = (init?.method || 'GET').toUpperCase();
    calls.push({
      url,
      method,
      body: init?.body ? JSON.parse(init.body as string) : undefined,
    });
    if (method === 'GET' && url.includes('/skills/registry')) {
      return { ok: true, json: async () => ({ skills: CATALOG }) } as Response;
    }
    if (method === 'GET' && url.includes('/skills')) {
      return {
        ok: true,
        json: async () => ({ agent_id: 'a1', skills: records, count: records.length }),
      } as Response;
    }
    if (method === 'POST' && opts.acquireOk === false) {
      return { ok: false, json: async () => ({ detail: opts.acquireDetail || 'nope' }) } as Response;
    }
    // POST acquire, PATCH re-level/suspend/reinstate, DELETE suspend all succeed.
    return { ok: true, json: async () => ({}) } as Response;
  });
}

describe('SkillManagement (AD-902)', () => {
  let calls: Array<{ url: string; method: string; body?: unknown }>;

  beforeEach(() => {
    calls = [];
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('renders skill rows with name, category, and proficiency label', async () => {
    vi.stubGlobal('fetch', stubFetch([RECORD], calls));
    render(<SkillManagement agentId="a1" />);

    const row = await screen.findByTestId('skill-row-basic');
    expect(row).toBeTruthy();
    expect(screen.getByText(/Basic Skill/)).toBeTruthy();
    expect(screen.getByText(/acquired/)).toBeTruthy();
    expect(screen.getByText('APPLY')).toBeTruthy();
  });

  it('acquiring a skill POSTs skill_id at proficiency 1', async () => {
    vi.stubGlobal('fetch', stubFetch([], calls));
    render(<SkillManagement agentId="a1" />);

    await waitFor(() => expect(screen.getByTestId('skill-acquire-pick')).toBeTruthy());
    fireEvent.change(screen.getByTestId('skill-acquire-pick'), { target: { value: 'advanced' } });
    fireEvent.click(screen.getByTestId('skill-acquire-submit'));

    await waitFor(() => {
      const post = calls.find(c => c.method === 'POST' && c.url.endsWith('/a1/skills'));
      expect(post).toBeTruthy();
      expect(post!.body).toEqual({ skill_id: 'advanced', proficiency: 1 });
    });
  });

  it('surfaces the rejection detail when acquisition fails', async () => {
    vi.stubGlobal('fetch', stubFetch([], calls, { acquireOk: false, acquireDetail: 'Prerequisite missing.' }));
    render(<SkillManagement agentId="a1" />);

    await waitFor(() => expect(screen.getByTestId('skill-acquire-pick')).toBeTruthy());
    fireEvent.change(screen.getByTestId('skill-acquire-pick'), { target: { value: 'advanced' } });
    fireEvent.click(screen.getByTestId('skill-acquire-submit'));

    const err = await screen.findByTestId('skill-acquire-error');
    expect(err.textContent).toContain('Prerequisite missing.');
  });

  it('level up PATCHes the next proficiency in one click', async () => {
    vi.stubGlobal('fetch', stubFetch([RECORD], calls));
    render(<SkillManagement agentId="a1" />);

    const up = await screen.findByTestId('skill-up-basic');
    fireEvent.click(up);

    await waitFor(() => {
      const patch = calls.find(c => c.method === 'PATCH' && c.url.includes('/a1/skills/basic'));
      expect(patch).toBeTruthy();
      expect(patch!.body).toEqual({ proficiency: 4 });
    });
  });

  it('level down is a two-step confirm before PATCH', async () => {
    vi.stubGlobal('fetch', stubFetch([RECORD], calls));
    render(<SkillManagement agentId="a1" />);

    const down = await screen.findByTestId('skill-down-basic');
    fireEvent.click(down);
    // first click does not patch — it reveals the confirm affordance
    expect(calls.some(c => c.method === 'PATCH')).toBe(false);

    fireEvent.click(screen.getByTestId('skill-down-confirm-basic'));
    await waitFor(() => {
      const patch = calls.find(c => c.method === 'PATCH' && c.url.includes('/a1/skills/basic'));
      expect(patch).toBeTruthy();
      expect(patch!.body).toEqual({ proficiency: 2 });
    });
  });

  it('suspend is two-step DELETE; a suspended row reinstates via PATCH', async () => {
    // Suspend path.
    vi.stubGlobal('fetch', stubFetch([RECORD], calls));
    const { unmount } = render(<SkillManagement agentId="a1" />);
    const suspend = await screen.findByTestId('skill-suspend-basic');
    fireEvent.click(suspend);
    expect(calls.some(c => c.method === 'DELETE')).toBe(false);
    fireEvent.click(screen.getByTestId('skill-suspend-confirm-basic'));
    await waitFor(() => {
      const del = calls.find(c => c.method === 'DELETE' && c.url.includes('/a1/skills/basic'));
      expect(del).toBeTruthy();
    });
    unmount();
    cleanup();

    // Reinstate path — a suspended record exposes a reinstate affordance.
    calls.length = 0;
    vi.stubGlobal('fetch', stubFetch([SUSPENDED_RECORD], calls));
    render(<SkillManagement agentId="a1" />);
    const reinstate = await screen.findByTestId('skill-reinstate-basic');
    fireEvent.click(reinstate);
    await waitFor(() => {
      const patch = calls.find(c => c.method === 'PATCH' && c.url.includes('/a1/skills/basic'));
      expect(patch).toBeTruthy();
      expect(patch!.body).toEqual({ suspended: false });
    });
  });

  it('renders no emoji', async () => {
    vi.stubGlobal('fetch', stubFetch([RECORD], calls));
    const { container } = render(<SkillManagement agentId="a1" />);
    await screen.findByTestId('skill-row-basic');
    expect(/\p{Extended_Pictographic}/u.test(container.textContent || '')).toBe(false);
  });
});
