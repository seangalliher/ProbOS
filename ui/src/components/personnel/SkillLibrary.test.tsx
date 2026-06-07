/** AD-898 (Wave 257) vitest — Skill Library management view.
 * Thin admin surface over the AD-895 governed endpoints: browse/filter the
 * definition list, create with inline validation, retire behind a two-step
 * confirm, surface the server's in-use/built-in protection errors, and uphold
 * the HXI no-emoji guard. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import SkillLibrary from './SkillLibrary';

interface Call {
  url: string;
  method: string;
  body: any;
}

const DEFS = [
  {
    skill_id: 'skill-diag',
    name: 'Diagnostics',
    category: 'role',
    description: 'Run system diagnostics.',
    domain: 'engineering',
    prerequisites: [],
    decay_rate_days: 14,
    origin: 'designed',
  },
  {
    skill_id: 'skill-core',
    name: 'Core Reasoning',
    category: 'pcc',
    description: 'Built-in core skill.',
    domain: '*',
    prerequisites: [],
    decay_rate_days: 30,
    origin: 'builtin',
  },
];

function stubFetch(calls: Call[], opts?: { deleteStatus?: number; deleteDetail?: string }) {
  global.fetch = vi.fn((url: string, init?: any) => {
    const method = (init?.method || 'GET').toUpperCase();
    const body = init?.body ? JSON.parse(init.body) : null;
    calls.push({ url, method, body });
    if (method === 'GET') {
      return Promise.resolve({
        ok: true,
        json: async () => ({ definitions: DEFS, count: DEFS.length }),
      }) as any;
    }
    if (method === 'DELETE' && opts?.deleteStatus && opts.deleteStatus >= 400) {
      return Promise.resolve({
        ok: false,
        status: opts.deleteStatus,
        json: async () => ({ detail: opts.deleteDetail || 'rejected' }),
      }) as any;
    }
    return Promise.resolve({ ok: true, json: async () => ({}) }) as any;
  }) as any;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('SkillLibrary (AD-898)', () => {
  let calls: Call[];
  beforeEach(() => {
    calls = [];
  });

  it('1. renders the definition list from GET /api/skills/definitions', async () => {
    stubFetch(calls);
    render(<SkillLibrary />);
    expect(await screen.findByTestId('skill-row-skill-diag')).toBeTruthy();
    expect(screen.getByTestId('skill-row-skill-core')).toBeTruthy();
    expect(screen.getByText('Diagnostics')).toBeTruthy();
    expect(calls.some(c => c.method === 'GET' && c.url.startsWith('/api/skills/definitions'))).toBe(true);
  });

  it('2. create form validates a missing name before POSTing', async () => {
    stubFetch(calls);
    render(<SkillLibrary />);
    await screen.findByTestId('skill-row-skill-diag');
    fireEvent.click(screen.getByTestId('skill-new'));
    // Submit with empty form → inline validation, no POST.
    fireEvent.click(screen.getByTestId('skill-form-submit'));
    expect(screen.getByTestId('skill-form-error').textContent).toContain('Name is required');
    expect(calls.some(c => c.method === 'POST')).toBe(false);
    // Fill required fields → POST fires.
    fireEvent.change(screen.getByTestId('skill-form-id'), { target: { value: 'skill-new1' } });
    fireEvent.change(screen.getByTestId('skill-form-name'), { target: { value: 'New Skill' } });
    fireEvent.click(screen.getByTestId('skill-form-submit'));
    await waitFor(() => {
      const post = calls.find(c => c.method === 'POST');
      expect(post).toBeTruthy();
      expect(post!.url).toBe('/api/skills/definitions');
      expect(post!.body.skill_id).toBe('skill-new1');
      expect(post!.body.name).toBe('New Skill');
    });
  });

  it('3. retire requires a two-step confirm before DELETE', async () => {
    stubFetch(calls);
    render(<SkillLibrary />);
    await screen.findByTestId('skill-row-skill-diag');
    fireEvent.click(screen.getByTestId('skill-delete-skill-diag'));
    // No DELETE yet — only the confirm button appears.
    expect(calls.some(c => c.method === 'DELETE')).toBe(false);
    fireEvent.click(screen.getByTestId('skill-delete-confirm-skill-diag'));
    await waitFor(() => {
      const del = calls.find(c => c.method === 'DELETE');
      expect(del).toBeTruthy();
      expect(del!.url).toBe('/api/skills/definitions/skill-diag');
    });
  });

  it('4. an in-use retire surfaces the server protection error inline', async () => {
    stubFetch(calls, { deleteStatus: 400, deleteDetail: 'Skill is in active use by 3 agents.' });
    render(<SkillLibrary />);
    await screen.findByTestId('skill-row-skill-diag');
    fireEvent.click(screen.getByTestId('skill-delete-skill-diag'));
    fireEvent.click(screen.getByTestId('skill-delete-confirm-skill-diag'));
    await waitFor(() => {
      expect(screen.getByTestId('skill-row-error').textContent).toContain('in active use');
    });
  });

  it('5. renders no emoji (HXI Principle #3)', async () => {
    stubFetch(calls);
    const { container } = render(<SkillLibrary />);
    await screen.findByTestId('skill-row-skill-diag');
    expect(/\p{Extended_Pictographic}/u.test(container.textContent || '')).toBe(false);
  });
});
