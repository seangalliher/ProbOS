import { test, expect, type Page, type WebSocketRoute } from '@playwright/test';
import { readFileSync } from 'node:fs';
import type Wire from './fixtures/ad1207-faults.json';

const fixture: typeof Wire = JSON.parse(readFileSync(
  new URL('./fixtures/ad1207-faults.json', import.meta.url), 'utf8',
));
const ORIGIN = 'http://127.0.0.1:5197';
const headline = fixture.pending.list.faults[0].summary;

async function isolate(page: Page) {
  let stage: keyof typeof fixture = 'pending';
  let unavailable = false;
  const reads: { path: string; stage: string }[] = [];
  const blocked: string[] = [];
  const escaped: string[] = [];
  const fulfilled = new Set<string>();
  const sockets: WebSocketRoute[] = [];
  const navigations: string[] = [];
  await page.addInitScript(() => {
    localStorage.setItem('hxi_seen_intro', 'true');
    if (navigator.mediaDevices) {
      for (const method of ['getUserMedia', 'getDisplayMedia']) {
        Object.defineProperty(navigator.mediaDevices, method, {
          configurable: true,
          value: () => Promise.reject(new DOMException('Disabled in isolated fault test', 'NotAllowedError')),
        });
      }
      Object.defineProperty(navigator.mediaDevices, 'enumerateDevices', {
        configurable: true, value: async () => [],
      });
    }
    for (const name of ['Worker', 'SharedWorker', 'SpeechRecognition', 'webkitSpeechRecognition']) {
      Object.defineProperty(window, name, {
        configurable: true,
        value: class {
          constructor() { throw new DOMException('Disabled in isolated fault test', 'SecurityError'); }
        },
      });
    }
  });
  await page.context().route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== ORIGIN || request.method() !== 'GET') {
      blocked.push(request.url());
      await route.abort('blockedbyclient');
      return;
    }
    if (url.pathname.startsWith('/api/')) {
      let payload: unknown;
      let status = 200;
      if (url.pathname === '/api/faults') {
        expect(url.search).toBe('?limit=50&offset=0');
        reads.push({ path: url.pathname, stage });
        payload = unavailable ? { detail: 'controlled outage' } : fixture[stage].list;
        status = unavailable ? 503 : 200;
      } else if (/^\/api\/faults\/[0-9a-f]{12}$/.test(url.pathname)) {
        reads.push({ path: url.pathname, stage });
        const current = fixture[stage];
        payload = 'detail' in current ? current.detail : { detail: 'fault_not_found' };
        status = 'detail' in current ? 200 : 404;
      } else if (url.pathname === '/api/capability-requests/actionable') {
        payload = { view: 'actionable', requests: [] };
      } else if (url.pathname === '/api/skill-requests') {
        payload = { requests: [] };
      } else if (url.pathname === '/api/wardroom/dms') {
        payload = [];
      } else if (url.pathname === '/api/recreation/active') {
        payload = { game: null };
      } else if (url.pathname === '/api/config/avatars-enabled') {
        payload = { enabled: false };
      } else if (url.pathname === '/api/threads') {
        payload = { threads: [] };
      } else if (url.pathname === '/api/threads/summaries') {
        payload = { summaries: {} };
      } else {
        blocked.push(request.url());
        await route.abort('blockedbyclient');
        return;
      }
      fulfilled.add(request.url());
      await route.fulfill({ status, json: payload });
      return;
    }
    if (url.pathname === '/'
      || /^\/(?:src\/|node_modules\/|@vite\/|@id\/|@fs\/|@react-refresh$)/.test(url.pathname)) {
      await route.continue();
      return;
    }
    blocked.push(request.url());
    await route.abort('blockedbyclient');
  });
  await page.context().routeWebSocket(/.*/, socket => {
    const url = new URL(socket.url());
    if (url.origin === 'ws://127.0.0.1:5197' && url.pathname === '/ws/events' && !url.search) {
      sockets.push(socket);
    } else {
      blocked.push(socket.url());
      socket.close({ code: 1008, reason: 'Not part of the isolated fixture' });
    }
  });
  page.on('response', response => {
    const url = new URL(response.url());
    if (url.origin !== ORIGIN || (url.pathname.startsWith('/api/') && !fulfilled.has(response.url()))) {
      escaped.push(response.url());
    }
  });
  page.on('framenavigated', frame => {
    if (frame === page.mainFrame()) navigations.push(frame.url());
  });
  return {
    reads, blocked, escaped, navigations,
    setStage: (next: keyof typeof fixture): void => { stage = next; },
    setUnavailable: (value: boolean): void => { unavailable = value; },
    open: async (): Promise<void> => {
      // #desktop selects the actual desktop Bridge even at the narrow keyboard viewport.
      await page.goto('/#desktop');
      await expect.poll(() => sockets.length).toBeGreaterThan(0);
      sockets.at(-1)!.send(JSON.stringify({
        type: 'state_snapshot', timestamp: 1000,
        stream: { generation: '12070000000000000000000000000001', sequence: 1 },
        data: { agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0, fresh_boot: false },
      }));
      await page.getByRole('button', { name: /^BRIDGE/ }).click();
      await expect.poll(() => reads.length).toBeGreaterThan(0);
      expect(reads[0]).toEqual({ path: '/api/faults', stage: 'pending' });
    },
  };
}

test('real Bridge shows evidence and refreshes the confirmed link without competing actions', async ({ page }) => {
  const harness = await isolate(page);
  await harness.open();
  const faults = page.getByRole('button', { name: 'Faults (1)', exact: true });
  await expect(faults).toBeVisible();
  await expect(faults.locator('..')).not.toHaveAttribute('data-station');
  await expect(faults.locator('..')).not.toHaveAttribute('data-alerting');
  const row = page.getByRole('button', { name: headline, exact: true });
  await row.click();
  const evidence = page.getByRole('region', { name: 'Fault evidence' });
  await expect(evidence.getByText('Recorded agent', { exact: true })).toBeVisible();
  await expect(evidence.getByText('Stored trace sample', { exact: true })).toBeVisible();
  await expect(evidence.getByText('counselor-ezri', { exact: true })).toBeVisible();
  await expect(page.getByText('No confirmed issue link.', { exact: true })).toBeVisible();
  expect(harness.reads.some(read => read.path === '/api/faults/000000000001')).toBe(true);
  harness.setStage('filed');
  await page.getByRole('button', { name: 'Refresh fault reports' }).click();
  const link = page.getByRole('link', { name: 'Issue owner/repo#37' });
  await expect(link).toHaveAttribute('href', fixture.filed.detail.fault.issue.url);
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(page.getByRole('button', { name: 'Approve', exact: true })).toHaveCount(0);
  await expect(page.getByText('No activity', { exact: true })).toHaveCount(0);
  harness.setStage('empty');
  await page.getByRole('button', { name: 'Refresh fault reports' }).click();
  await expect(faults).toHaveCount(0);
  await expect(page.getByText('No activity', { exact: true })).toBeVisible();
  expect(harness.escaped).toEqual([]);
  expect(harness.navigations.every(url => url.startsWith(ORIGIN))).toBe(true);
});

test('narrow-safe keyboard disclosure, sibling link focus and stale count honesty', async ({ page }) => {
  const harness = await isolate(page);
  await harness.open();
  const row = page.getByRole('button', { name: headline, exact: true });
  await row.focus();
  await page.keyboard.press('Enter');
  await expect(row).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByRole('region', { name: 'Fault evidence' }).getByText('counselor-ezri', { exact: true })).toBeVisible();
  harness.setStage('filed');
  await page.getByRole('button', { name: 'Refresh fault reports' }).click();
  const link = page.getByRole('link', { name: 'Issue owner/repo#37' });
  await expect(link).toBeVisible();
  await row.focus();
  await page.keyboard.press('Tab');
  await expect(link).toBeFocused();
  await expect(link).toHaveCSS('outline-style', 'solid');
  const dimensions = await row.evaluate(element => {
    const box = element.getBoundingClientRect();
    return { left: box.left, right: box.right, width: innerWidth };
  });
  expect(dimensions.left).toBeGreaterThanOrEqual(0);
  expect(dimensions.right).toBeLessThanOrEqual(dimensions.width);
  harness.setUnavailable(true);
  await page.getByRole('button', { name: 'Refresh fault reports' }).click();
  await expect(page.getByRole('button', { name: 'Faults (1 last-known; current unknown)' })).toBeVisible();
  await expect(page.getByRole('status', { name: 'Fault reports status' })).toContainText('Unavailable');
  await expect(page.getByText('No activity', { exact: true })).toHaveCount(0);
  expect(harness.escaped).toEqual([]);
  expect(harness.navigations.every(url => url.startsWith(ORIGIN))).toBe(true);
});
