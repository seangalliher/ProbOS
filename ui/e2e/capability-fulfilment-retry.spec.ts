import { test, expect, type Locator, type Request, type WebSocketRoute } from '@playwright/test';
import { gotoApp } from './_helpers';

test.use({
  serviceWorkers: 'block',
  permissions: [],
  viewport: { width: 1440, height: 1000 },
});

for (const activation of ['pointer', 'keyboard'] as const) {
  test(`MCP approval survives failed fulfilment and reload, then explicitly retries (${activation})`, async ({
    page, context, baseURL,
  }, testInfo) => {
    test.setTimeout(60_000);
    if (!baseURL) throw new Error('The owned local Playwright server must supply baseURL');
    const origin = new URL(baseURL).origin;
    const location = new URL(origin);
    expect(['localhost', '127.0.0.1']).toContain(location.hostname);
    expect(location.port).not.toBe('');
    const generation = 'a'.repeat(32);
    let sequence = 0;
    let socket: WebSocketRoute | null = null;
    let socketCount = 0;
    let status: 'pending' | 'approved' | 'fulfilled' = 'pending';
    let unavailable = false;
    let posts = 0;
    let failedReads = 0;
    const observations: string[] = [];
    const mutations: unknown[] = [];
    const unexpectedMutations: string[] = [];
    const escaped: string[] = [];
    const permitted = new Set<Request>();
    const row = () => ({
      id: 'ordinary1205-approval',
      agent_id: 'ordinary1205-agent',
      kind: 'install',
      target: 'Local MCP echo',
      rationale: 'Use the local echo capability for the blocked work item.',
      work_item_id: 'ordinary1205-work',
      status,
      created_at: 1789680000,
      decided_at: status === 'pending' ? null : 1789680001,
      decided_by: status === 'pending' ? '' : 'captain',
      decision_reason: '',
      payload: { install_kind: 'mcp', mcp_server_id: 'ordinary1205-echo' },
      can_retry_fulfilment: status === 'approved',
    });
    const frame = (type: string, data: unknown) => JSON.stringify({
      type, data, timestamp: 1789680002,
      stream: { generation, sequence: ++sequence },
    });

    await context.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();
      if (url.origin !== origin) return route.abort('blockedbyclient');
      if (url.pathname === '/api/capability-requests/actionable' && method === 'GET') {
        permitted.add(request);
        if (unavailable) {
          failedReads += 1;
          return route.fulfill({ status: 503, json: { detail: 'controlled queue outage' } });
        }
        observations.push(status);
        return route.fulfill({ json: { view: 'actionable', requests: status === 'fulfilled' ? [] : [row()] } });
      }
      if (url.pathname === '/api/capability-requests/ordinary1205-approval/decide' && method === 'POST') {
        const body: unknown = request.postDataJSON();
        expect(body).toEqual({ approve: true, reason: '' });
        mutations.push(body);
        posts += 1;
        expect(status).toBe(posts === 1 ? 'pending' : 'approved');
        expect(posts).toBeLessThanOrEqual(2);
        status = posts === 1 ? 'approved' : 'fulfilled';
        permitted.add(request);
        if (!socket) throw new Error('The capability event fixture never connected');
        socket.send(frame(
          posts === 1 ? 'capability_request_decided' : 'capability_request_fulfilled',
          { id: row().id, agent_id: row().agent_id, kind: 'install', status },
        ));
        return route.fulfill({ json: { request: row(), fulfilled: status === 'fulfilled', standing_rule: null } });
      }
      if (url.pathname === '/api/skill-requests' && method === 'GET') {
        permitted.add(request);
        return route.fulfill({ json: { requests: [], status: 'pending' } });
      }
      if (url.pathname === '/api/wardroom/dms' && method === 'GET') {
        permitted.add(request);
        return route.fulfill({ json: [] });
      }
      if (method === 'GET' && !url.pathname.startsWith('/api/') && !url.pathname.startsWith('/ws/')) {
        permitted.add(request);
        return route.continue();
      }
      if (method !== 'GET') unexpectedMutations.push(`${method} ${url.pathname}`);
      return route.abort('blockedbyclient');
    });
    await context.routeWebSocket(/.*/, route => {
      const url = new URL(route.url());
      if (url.host !== location.host) {
        route.close();
        return;
      }
      route.onMessage(() => {});
      if (url.pathname === '/ws/events') {
        socket = route;
        socketCount += 1;
        route.send(frame('state_snapshot', {
          agents: [], connections: [], pools: [], system_mode: 'active',
          tc_n: 0, routing_entropy: 0, fresh_boot: false,
        }));
      } else {
        route.close();
      }
    });
    context.on('response', response => {
      if (!permitted.has(response.request())) escaped.push(response.url());
    });
    const activate = async (control: Locator): Promise<void> => {
      if (activation === 'pointer') await control.click();
      else {
        await control.focus();
        await expect(control).toBeFocused();
        await control.press('Enter');
      }
    };

    try {
      await gotoApp(page);
      await expect.poll(() => socketCount).toBe(1);
      await expect.poll(() => observations.length).toBeGreaterThan(0);
      expect(observations[0]).toBe('pending');
      const bridge = page.getByRole('button', { name: /^BRIDGE/ });
      await expect(bridge).toHaveText('BRIDGE (1)');
      await activate(bridge);
      await activate(page.getByTestId('bridge-approval-row'));
      const dialog = page.getByRole('dialog', { name: /APPROVALS/ });
      await expect(dialog).toBeVisible();
      await activate(dialog.getByRole('button', { name: 'Approve', exact: true }));
      const retry = dialog.getByRole('button', { name: 'Retry fulfilment', exact: true });
      await expect(retry).toBeEnabled();
      expect(posts).toBe(1);
      await expect(page.getByTestId('bridge-approval-row')).toContainText('Approved - awaiting fulfilment');
      await expect(dialog.getByRole('button', { name: 'Deny', exact: true })).toHaveCount(0);
      await expect(dialog.getByRole('textbox', { name: 'decision reason' })).toHaveCount(0);
      await expect(bridge).toHaveText('BRIDGE (1)');

      unavailable = true;
      await activate(dialog.getByRole('button', { name: 'Refresh capability requests', exact: true }));
      await expect.poll(() => failedReads).toBe(1);
      await expect(dialog.getByRole('status', { name: 'Capability requests status' })).toContainText('current count unknown');
      await expect(retry).toBeEnabled();
      expect(posts).toBe(1);
      await page.screenshot({ path: testInfo.outputPath('approved-awaiting-fulfilment.png') });

      unavailable = false;
      const beforeReload = observations.length;
      await page.reload();
      await expect.poll(() => socketCount).toBe(2);
      await expect.poll(() => observations.length).toBeGreaterThan(beforeReload);
      expect(observations.slice(beforeReload)).toContain('approved');
      await expect(bridge).toHaveText('BRIDGE (1)');
      expect(posts).toBe(1);
      await activate(bridge);
      await activate(page.getByTestId('bridge-approval-row'));
      await expect(retry).toBeEnabled();
      await activate(retry);
      await expect.poll(() => posts).toBe(2);
      await expect(page.getByTestId('capability-request-card')).toHaveCount(0);
      await expect(page.getByTestId('bridge-approval-row')).toHaveCount(0);
      await expect(bridge).toHaveText('BRIDGE');
      await expect(page.getByTestId('approvals-center-empty')).toBeVisible();
      expect(observations).toContain('fulfilled');
      expect(mutations).toEqual([{ approve: true, reason: '' }, { approve: true, reason: '' }]);
      expect(unexpectedMutations).toEqual([]);
      expect(escaped).toEqual([]);
    } finally {
      await testInfo.attach('fixture-evidence', {
        body: Buffer.from(JSON.stringify({ socketCount, observations, failedReads, mutations, unexpectedMutations, escaped })),
        contentType: 'application/json',
      });
    }
  });
}
