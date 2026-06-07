/** AD-901 (Wave 256) vitest — Standing Orders & Directives management view.
 * Renders the read-only four tiers (passed as props) plus the AD-900 Directives
 * panel: issuing an order POSTs, a pending directive exposes an approve
 * affordance, revoke is two-step confirm, and the HXI no-emoji guard holds. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import StandingOrders from './StandingOrders';

const TIERS = [
  { tier: 'federation', source_file: 'federation.md', present: true, text: 'Prime directive applies.' },
  { tier: 'ship', source_file: 'ship.md', present: true, text: 'Maintain readiness.' },
  { tier: 'department', source_file: null, present: false, text: '' },
  { tier: 'agent', source_file: null, present: false, text: '' },
];

const ACTIVE_DIRECTIVE = {
  id: 'dir-active',
  directive_type: 'captain_order',
  content: 'Run a level-two diagnostic each watch.',
  status: 'active',
  priority: 3,
  issued_by: 'captain',
  target_department: 'science',
};

const PENDING_DIRECTIVE = {
  id: 'dir-pending',
  directive_type: 'learned_lesson',
  content: 'Recalibrate the sensor array before each sweep.',
  status: 'pending_approval',
  priority: 5,
  issued_by: 'agent-data',
  target_department: 'science',
};

/** Per-method/URL fetch stub. Records POST/DELETE bodies for assertions. */
function stubFetch(directives: unknown[], calls: Array<{ url: string; method: string; body?: unknown }>) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const method = (init?.method || 'GET').toUpperCase();
    calls.push({
      url,
      method,
      body: init?.body ? JSON.parse(init.body as string) : undefined,
    });
    if (method === 'GET' && url.includes('/directives')) {
      return {
        ok: true,
        json: async () => ({ agent_id: 'agent-data', directives, count: directives.length }),
      } as Response;
    }
    // POST issue, POST approve, DELETE revoke all succeed.
    return { ok: true, json: async () => ({}) } as Response;
  });
}

describe('StandingOrders (AD-901)', () => {
  let calls: Array<{ url: string; method: string; body?: unknown }>;

  beforeEach(() => {
    calls = [];
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('renders the read-only four tiers', async () => {
    vi.stubGlobal('fetch', stubFetch([], calls));
    render(<StandingOrders agentId="agent-data" tiers={TIERS} />);

    expect(screen.getByTestId('sr-order-tier-federation')).toBeTruthy();
    expect(screen.getByTestId('sr-order-tier-ship')).toBeTruthy();
    expect(screen.getByTestId('sr-order-tier-department')).toBeTruthy();
    expect(screen.getByText(/Prime directive applies\./)).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId('so-directives')).toBeTruthy());
  });

  it('issuing an order POSTs to the directives endpoint', async () => {
    vi.stubGlobal('fetch', stubFetch([], calls));
    render(<StandingOrders agentId="agent-data" tiers={TIERS} />);

    const textarea = screen.getByTestId('so-issue-content');
    fireEvent.change(textarea, { target: { value: 'Hold station at the nebula.' } });
    fireEvent.click(screen.getByTestId('so-issue-submit'));

    await waitFor(() => {
      const post = calls.find(c => c.method === 'POST' && c.url.endsWith('/agent-data/directives'));
      expect(post).toBeTruthy();
      expect((post!.body as { content: string }).content).toBe('Hold station at the nebula.');
    });
  });

  it('a pending directive shows an approve affordance that POSTs approve', async () => {
    vi.stubGlobal('fetch', stubFetch([PENDING_DIRECTIVE], calls));
    render(<StandingOrders agentId="agent-data" tiers={TIERS} />);

    const approve = await screen.findByTestId('so-approve-dir-pending');
    expect(screen.getByText('AWAITING APPROVAL')).toBeTruthy();
    fireEvent.click(approve);

    await waitFor(() => {
      const post = calls.find(c => c.method === 'POST' && c.url.includes('/directives/dir-pending/approve'));
      expect(post).toBeTruthy();
    });
  });

  it('revoke is a two-step confirm before DELETE', async () => {
    vi.stubGlobal('fetch', stubFetch([ACTIVE_DIRECTIVE], calls));
    render(<StandingOrders agentId="agent-data" tiers={TIERS} />);

    const revoke = await screen.findByTestId('so-revoke-dir-active');
    fireEvent.click(revoke);
    // first click does not delete — it reveals the confirm affordance
    expect(calls.some(c => c.method === 'DELETE')).toBe(false);

    const confirm = screen.getByTestId('so-revoke-confirm-dir-active');
    fireEvent.click(confirm);
    await waitFor(() => {
      const del = calls.find(c => c.method === 'DELETE' && c.url.includes('/directives/dir-active'));
      expect(del).toBeTruthy();
    });
  });

  it('renders no emoji', async () => {
    vi.stubGlobal('fetch', stubFetch([ACTIVE_DIRECTIVE, PENDING_DIRECTIVE], calls));
    const { container } = render(<StandingOrders agentId="agent-data" tiers={TIERS} />);
    await screen.findByTestId('so-directive-dir-active');
    expect(/\p{Extended_Pictographic}/u.test(container.textContent || '')).toBe(false);
  });
});
