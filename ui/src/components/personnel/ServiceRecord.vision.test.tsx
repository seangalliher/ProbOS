/** AD-982b: vision-capability toggle in the personnel ServiceRecord.
 *
 * The Captain can grant/revoke an agent's PERMANENT ambient vision from the
 * personnel record. The toggle seeds from the record's vision_capable, POSTs to
 * /api/agent/{id}/vision-capability/set, and updates optimistically.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import ServiceRecord from './ServiceRecord';

const ORDERS = { agent_id: 'yeo-1', agent_type: 'yeoman', tiers: [] };
const TOOLS = { agent_id: 'yeo-1', certifications: [], count: 0 };

const SUMMARY = {
  agent_id: 'yeo-1', agent_type: 'yeoman', callsign: 'Yeo',
  post: 'Yeoman', department: 'ops', rank: 'ensign',
};

function stubFetch(map: Record<string, any>, onSet?: (body: any) => void) {
  global.fetch = vi.fn((url: string, opts?: any) => {
    if (String(url).includes('/vision-capability/set')) {
      if (onSet && opts?.body) onSet(JSON.parse(opts.body));
      return Promise.resolve({ ok: true, json: async () => ({ vision_capable: true }) }) as any;
    }
    for (const key of Object.keys(map)) {
      if (String(url).includes(key)) {
        return Promise.resolve({ ok: true, json: async () => map[key] }) as any;
      }
    }
    return Promise.resolve({ ok: false, status: 404, json: async () => ({}) }) as any;
  }) as any;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('ServiceRecord — AD-982b vision toggle', () => {
  it('renders "Off" when the record reports vision_capable false', async () => {
    stubFetch({ '/record': { agent_id: 'yeo-1', vision_capable: false }, '/standing-orders': ORDERS, '/tools': TOOLS });
    render(<ServiceRecord agentId="yeo-1" summary={SUMMARY} />);
    const btn = await screen.findByTestId('sr-vision-toggle');
    expect(btn.textContent).toBe('Off');
  });

  it('renders "Granted" when the record reports vision_capable true', async () => {
    stubFetch({ '/record': { agent_id: 'yeo-1', vision_capable: true }, '/standing-orders': ORDERS, '/tools': TOOLS });
    render(<ServiceRecord agentId="yeo-1" summary={SUMMARY} />);
    const btn = await screen.findByTestId('sr-vision-toggle');
    expect(btn.textContent).toBe('Granted');
  });

  it('clicking Off POSTs enabled:true and flips to Granted optimistically', async () => {
    const sets: any[] = [];
    stubFetch(
      { '/record': { agent_id: 'yeo-1', vision_capable: false }, '/standing-orders': ORDERS, '/tools': TOOLS },
      (body) => sets.push(body),
    );
    render(<ServiceRecord agentId="yeo-1" summary={SUMMARY} />);
    const btn = await screen.findByTestId('sr-vision-toggle');
    fireEvent.click(btn);
    await waitFor(() => expect(sets.length).toBe(1));
    expect(sets[0].enabled).toBe(true);
    await waitFor(() => expect(screen.getByTestId('sr-vision-toggle').textContent).toBe('Granted'));
  });

  it('clicking Granted POSTs enabled:false (revoke)', async () => {
    const sets: any[] = [];
    stubFetch(
      { '/record': { agent_id: 'yeo-1', vision_capable: true }, '/standing-orders': ORDERS, '/tools': TOOLS },
      (body) => sets.push(body),
    );
    render(<ServiceRecord agentId="yeo-1" summary={SUMMARY} />);
    const btn = await screen.findByTestId('sr-vision-toggle');
    fireEvent.click(btn);
    await waitFor(() => expect(sets.length).toBe(1));
    expect(sets[0].enabled).toBe(false);
  });

  it('falls back to the roster summary when the record omits vision_capable', async () => {
    stubFetch({ '/record': { agent_id: 'yeo-1' }, '/standing-orders': ORDERS, '/tools': TOOLS });
    render(
      <ServiceRecord agentId="yeo-1" summary={{ ...SUMMARY, vision_capable: true }} />,
    );
    const btn = await screen.findByTestId('sr-vision-toggle');
    expect(btn.textContent).toBe('Granted');
  });

  it('reverts the optimistic state when the POST fails', async () => {
    // record says false; set endpoint returns !ok -> stays Off after revert.
    global.fetch = vi.fn((url: string) => {
      if (String(url).includes('/vision-capability/set')) {
        return Promise.resolve({ ok: false, status: 500, json: async () => ({}) }) as any;
      }
      if (String(url).includes('/record')) {
        return Promise.resolve({ ok: true, json: async () => ({ agent_id: 'yeo-1', vision_capable: false }) }) as any;
      }
      return Promise.resolve({ ok: true, json: async () => ({ tiers: [], certifications: [] }) }) as any;
    }) as any;
    render(<ServiceRecord agentId="yeo-1" summary={SUMMARY} />);
    const btn = await screen.findByTestId('sr-vision-toggle');
    fireEvent.click(btn);
    // optimistic flip to Granted, then revert to Off on the failed response.
    await waitFor(() => expect(screen.getByTestId('sr-vision-toggle').textContent).toBe('Off'));
  });
});
