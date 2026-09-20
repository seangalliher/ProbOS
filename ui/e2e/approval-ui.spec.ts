import { test, expect, type APIRequestContext, type Page, type Route } from '@playwright/test';
import { realpathSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const candidate = realpathSync(resolve(fileURLToPath(new URL('.', import.meta.url)), '../..'));
const base = `http://127.0.0.1:${process.env.APPROVAL_UI_PORT}`;
const bridge = `http://127.0.0.1:${process.env.APPROVAL_UI_BRIDGE_PORT}`;
const canonical = (path: string): string => path.replace(/\\/g, '/').toLowerCase();
type Scenario = { request_id: string; work_item_id: string; thread_id: string; agent_id: string; notice: string;
  message: { id: string; author_id: string; thread_id: string; body: string }; setup: Record<string, unknown>;
  numeric_boundary: {
    ordinary: { request_id: string; python_characters: number };
    repair: { request_id: string; python_characters: number; can_fulfil: boolean };
    unrelated_request_ids: string[];
  } | null };
type Controls = {
  failReads: boolean; settings: 'real' | 'failed' | 'disabled'; receipt: 'real' | 'null' | 'invalid';
  mutateRead?: (body: any) => void; mutateTranscript?: (body: any) => void;
  reads: number; decisions: number; transcripts: number; unexpected: string[];
};

async function json(request: APIRequestContext, path: string, body?: unknown): Promise<any> {
  const response = body === undefined ? await request.get(bridge + path) : await request.post(bridge + path, { data: body });
  expect(response.ok(), `${path}: ${await response.text()}`).toBe(true);
  return response.json();
}
async function state(request: APIRequestContext): Promise<any> { return json(request, '/__approval_ui__/state'); }

async function guard(page: Page): Promise<Controls> {
  const control: Controls = { failReads: false, settings: 'real', receipt: 'real',
    reads: 0, decisions: 0, transcripts: 0, unexpected: [] };
  page.on('pageerror', error => control.unexpected.push(`pageerror: ${error.message}`));
  await page.routeWebSocket(/.*/, socket => {
    const url = new URL(socket.url());
    // Vite's injected development client still attempts its own tokenized
    // socket with hmr:false. Close only that owned socket without connecting.
    if (url.origin !== base.replace('http:', 'ws:') || url.pathname !== '/' || !url.searchParams.has('token')) {
      control.unexpected.push(`websocket: ${url.origin}${url.pathname}`);
    }
    socket.close();
  });
  await page.route('**/*', async (route: Route) => {
    const incoming = route.request();
    const url = new URL(incoming.url());
    if (url.origin !== base) {
      control.unexpected.push(`${incoming.method()} ${url.origin}${url.pathname}`);
      await route.abort('blockedbyclient');
      return;
    }
    if (!url.pathname.startsWith('/api/')) { await route.continue(); return; }
    const capability = url.pathname === '/api/capability-requests/actionable';
    const deciding = /^\/api\/capability-requests\/[0-9a-f-]{36}\/decide$/.test(url.pathname);
    const transcript = /^\/api\/threads\/[0-9a-f]{32}\/messages$/.test(url.pathname);
    const settings = url.pathname === '/api/config';
    if (capability) {
      control.reads += 1;
      if (control.failReads) { await route.fulfill({ status: 503, json: { detail: 'isolated read failure' } }); return; }
    }
    if (settings && control.settings === 'failed') {
      await route.fulfill({ status: 503, json: { detail: 'isolated settings failure' } }); return;
    }
    if (deciding || capability || transcript || settings) {
      if (deciding) { expect(incoming.method()).toBe('POST'); control.decisions += 1; }
      else expect(incoming.method()).toBe('GET');
      if (transcript) control.transcripts += 1;
      // Forward the actual request to the owned real production route. Receipt
      // corruption occurs only AFTER that route has applied its real effects.
      const response = await route.fetch({ url: bridge + url.pathname + url.search, maxRedirects: 0, timeout: 10_000 });
      expect(response.status()).not.toBeGreaterThanOrEqual(300);
      const mutate = (capability && control.mutateRead) || (transcript && control.mutateTranscript)
        || (deciding && control.receipt !== 'real') || (settings && control.settings === 'disabled');
      if (!mutate) {
        // Preserve Python's numeric tokens; JSON reserialization would turn decoded overflow into null.
        await route.fulfill({ response });
        return;
      }
      const body = await response.json();
      if (capability) control.mutateRead?.(body);
      if (transcript) control.mutateTranscript?.(body);
      if (deciding && control.receipt !== 'real') body.standing_rule = control.receipt === 'null' ? null : { id: 'malformed' };
      if (settings && control.settings === 'disabled') body.config.approval_inbox.standing_rules_enabled = false;
      await route.fulfill({ response, json: body });
      return;
    }
    // Unrelated Bridge/IntentSurface reads have no authority in this fixture.
    // In particular no unknown POST may fall through to a provider or vessel.
    if (incoming.method() !== 'GET') {
      control.unexpected.push(`unexpected API mutation: ${incoming.method()} ${url.pathname}`);
      await route.abort('blockedbyclient');
      return;
    }
    await route.fulfill({ status: url.pathname.startsWith('/api/skill-requests') ? 200 : 503,
      json: url.pathname.startsWith('/api/skill-requests') ? { requests: [] }
        : { availability: { state: 'disabled', code: 'fixture.unrelated', message: 'Unrelated fixture service disabled', retryable: false } } });
  });
  return control;
}

async function open(page: Page, request: APIRequestContext, options: Record<string, unknown> = {}): Promise<Scenario> {
  const scenario: Scenario = await json(request, '/__approval_ui__/scenario', { kind: 'continue', ...options });
  const before = await state(request);
  expect(scenario.setup).toMatchObject({ request_status: 'pending', work_status: 'blocked', router_predispatchable: true, execution_count: 0 });
  expect(before.request.id).toBe(scenario.request_id);
  expect(before.request.work_item_id).toBe(scenario.work_item_id);
  expect(before.work_item.status).toBe('blocked');
  expect(before.work_item.metadata.capability_request_id).toBe(scenario.request_id);
  expect(before.router_predispatchable).toBe(true);
  expect(before.execution_calls).toEqual([]);
  expect(before.tool_calls).toEqual([]);
  expect(before.message.author_id).toBe(scenario.agent_id);
  expect(before.message.thread_id).toBe(scenario.thread_id);
  if (options.kind !== 'action') expect(scenario.notice).toContain(`(Request ${scenario.request_id}.)`);
  await page.goto(`${base}/approval-ui?thread=${scenario.thread_id}&agent=${scenario.agent_id}`);
  await expect(page.getByTestId('canonical-chat').getByText(scenario.notice, { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: `BRIDGE (${scenario.numeric_boundary ? 4 : 1})`, exact: true })).toBeVisible();
  return scenario;
}
async function center(page: Page, count = 1): Promise<void> {
  await page.getByRole('button', { name: `BRIDGE (${count})`, exact: true }).click();
  await expect(page.getByTestId('bridge-approval-row')).toHaveCount(count);
  await page.getByTestId('bridge-approval-row').first().click();
  await expect(page.getByRole('dialog', { name: /APPROVALS/ })).toBeVisible();
}
async function sink(request: APIRequestContext, scenario: Scenario): Promise<any> {
  await expect.poll(async () => (await state(request)).execution_calls.length).toBe(1);
  const evidence = await state(request);
  expect(evidence.request.status).toBe('fulfilled');
  expect(evidence.work_item.status).toBe('in_progress');
  expect(evidence.execution_calls[0]).toMatchObject({ agent_id: scenario.agent_id, work_status: 'in_progress',
    params: { work_item_id: scenario.work_item_id } });
  expect(evidence.event_counts.capability_request_decided).toBe(1);
  expect(evidence.event_counts.capability_request_fulfilled).toBe(1);
  expect(evidence.decision_post_count).toBe(1);
  return evidence;
}
async function reconciled(page: Page): Promise<void> {
  await expect(page.getByTestId('capability-request-card')).toHaveCount(0);
  await expect(page.getByTestId('bridge-approval-row')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'BRIDGE', exact: true })).toHaveText('BRIDGE');
}

test.beforeAll(async ({ request }) => {
  expect(canonical(process.env.APPROVAL_UI_CANDIDATE!)).toBe(canonical(candidate));
  const health = await json(request, '/__approval_ui__/health');
  expect(health).toMatchObject({ ok: true, service: 'approval-ui-test-bridge' });
  expect(health.pid).toBeGreaterThan(0);
  expect(health.server_id).toMatch(/^[0-9a-f]{32}$/);
  expect(canonical(health.candidate)).toBe(canonical(candidate));
  // The boundary fixture adds three real repair owners; keep exact provenance enumeration.
  expect(Object.keys(health.module_origins)).toHaveLength(20);
  for (const module of ['probos.cognitive.repair_issue', 'probos.fault_report', 'probos.fault_issue_filings']) {
    expect(Object.keys(health.module_origins)).toContain(module);
  }
  for (const path of Object.values(health.module_origins) as string[]) expect(canonical(path)).toContain(`${canonical(candidate)}/src/`);
  const response = await request.get(base + '/__approval_ui__/config');
  expect(response.ok()).toBe(true);
  const vite = await response.json();
  expect(vite).toMatchObject({ proxy: {}, host: '127.0.0.1', strictPort: true, port: Number(process.env.APPROVAL_UI_PORT) });
  expect(canonical(vite.candidate)).toBe(canonical(candidate));
  for (const path of Object.values(vite.sourceOrigins) as string[]) expect(canonical(path)).toContain(`${canonical(candidate)}/ui/src/`);
  console.log(`approval-ui provenance: ${JSON.stringify({ candidate, pythonOrigins: health.module_origins, uiOrigins: vite.sourceOrigins,
    proxy: vite.proxy, strictPort: vite.strictPort, serverId: health.server_id, bridgePid: health.pid, vitePid: vite.pid })}`);
});

test('canonical no-work chat approval reaches the real router sink and all surfaces reconcile', async ({ page, request }) => {
  const control = await guard(page);
  const scenario = await open(page, request);
  expect(control.transcripts).toBe(1);
  const client = await page.evaluate(() => (window as any).__approvalUi.snapshot());
  expect(client.messages[0]).toMatchObject({ authorId: scenario.agent_id, threadId: scenario.thread_id, text: scenario.notice });
  await center(page);
  await expect(page.getByRole('dialog').getByTestId('capability-request-card')).toHaveCount(1);
  await page.getByRole('button', { name: 'Close Approvals' }).click();
  await page.getByRole('button', { name: 'Close Bridge' }).click();
  const reads = control.reads;
  await page.getByRole('button', { name: `Approve for request ${scenario.request_id}` }).click();
  const evidence = await sink(request, scenario);
  await reconciled(page);
  expect(control.reads).toBeGreaterThan(reads);
  expect(evidence.decision_posts[0].body).toEqual({ approve: true, reason: '' });
  await expect(page.getByTestId('canonical-chat').getByRole('status')).toHaveText(/fulfilment confirmed/i);
  expect(control.unexpected).toEqual([]);
  console.log(`chat-to-router: ${JSON.stringify({ request: scenario.request_id, work: scenario.work_item_id,
    executions: evidence.execution_calls, events: evidence.event_counts, decisionPosts: evidence.decision_post_count })}`);
});

test('real partial-work Bridge decision reconciles chat and admits a later empty-scope continuation', async ({ page, request }) => {
  const control = await guard(page);
  const scenario = await open(page, request, { partial: true });
  expect(scenario.notice).toContain('\n\n---\nThe first fixture step');
  await center(page);
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('checkbox', { name: 'Grant standing approval' }).check();
  await dialog.getByRole('spinbutton', { name: 'Standing lifetime in hours' }).fill('1');
  await dialog.getByRole('button', { name: 'Approve', exact: true }).click();
  const evidence = await sink(request, scenario);
  expect(evidence.decision_posts[0].body).toEqual({ approve: true, reason: '', grant_standing: true, standing_ttl_hours: 1 });
  expect(evidence.action.active_approvals).toHaveLength(1);
  await reconciled(page);
  await expect(dialog.getByTestId('capability-decision-feedback')).toHaveText(/Standing authority confirmed.*exact empty scope.*expires/);
  await page.getByRole('button', { name: 'Close Approvals' }).click();
  await expect(page.getByTestId('canonical-chat').getByRole('status')).toHaveText(/Standing authority confirmed/);
  const later = await json(request, '/__approval_ui__/future', {});
  expect(later.admitted).toBe(true);
  expect(later.thread_id).not.toBe(scenario.thread_id);
  expect(later.requests).toEqual([]);
  const expired = await json(request, '/__approval_ui__/future', { expired: true });
  expect(expired.admitted).toBe(false);
  expect(expired.requests).toHaveLength(1);
  expect(control.unexpected).toEqual([]);
});

test('explicit approved-fulfilment Retry reaches the sink without a second decision or standing fields', async ({ page, request }) => {
  const control = await guard(page);
  const scenario = await open(page, request, { approved_retry: true });
  const before = await state(request);
  expect(before.request.status).toBe('approved');
  expect(before.event_counts.capability_request_decided).toBe(1);
  const chat = page.getByTestId('canonical-chat');
  await expect(chat.getByRole('checkbox')).toHaveCount(0);
  await chat.getByRole('button', { name: `Retry fulfilment for request ${scenario.request_id}` }).click();
  const evidence = await sink(request, scenario);
  expect(evidence.trust_outcomes).toHaveLength(before.trust_outcomes.length);
  expect(evidence.decision_posts[0].body).toEqual({ approve: true, reason: '' });
  await reconciled(page);
  expect(control.unexpected).toEqual([]);
});

test('failed predecision reads send no POST; a reconnect snapshot and reload reconcile real canonical state', async ({ page, request }) => {
  const control = await guard(page);
  const scenario = await open(page, request);
  control.failReads = true;
  await page.getByRole('button', { name: `Approve for request ${scenario.request_id}` }).click();
  await expect(page.getByTestId('canonical-chat').getByRole('button', { name: `Approve for request ${scenario.request_id}` })).toBeDisabled();
  await expect(page.getByTestId('canonical-chat')).toContainText('Request state is unknown or stale');
  expect(control.decisions).toBe(0);
  expect((await state(request)).request.status).toBe('pending');
  const epoch = await page.evaluate(() => (window as any).__approvalUi.snapshot().liveRepairEpoch);
  control.failReads = false;
  await page.getByRole('button', { name: 'Reconnect snapshot', exact: true }).click();
  expect(await page.evaluate(() => (window as any).__approvalUi.snapshot().liveRepairEpoch)).toBe(epoch + 1);
  await expect(page.getByRole('button', { name: `Approve for request ${scenario.request_id}` })).toBeEnabled();
  await page.getByRole('button', { name: `Approve for request ${scenario.request_id}` }).click();
  await sink(request, scenario);
  await page.reload();
  await expect(page.getByTestId('canonical-chat')).toContainText(scenario.notice);
  await expect(page.getByTestId('canonical-chat').getByRole('status')).toHaveText('No longer actionable.');
  await reconciled(page);
  expect(control.transcripts).toBe(2);
  expect(control.decisions).toBe(1);
  expect(control.unexpected).toEqual([]);
});

test('a changed predecision row requires renewed review instead of silently approving its replacement', async ({ page, request }) => {
  const control = await guard(page);
  const scenario = await open(page, request);
  control.mutateRead = body => { body.requests[0].rationale = 'Changed after display'; };
  await page.getByRole('button', { name: `Approve for request ${scenario.request_id}` }).click();
  await expect(page.getByTestId('canonical-chat').getByRole('alert')).toHaveText(/changed; review/);
  expect(control.decisions).toBe(0);
  expect((await state(request)).execution_calls).toEqual([]);
  control.mutateRead = undefined;
  await page.getByRole('button', { name: 'Reconnect snapshot', exact: true }).click();
  await expect(page.getByTestId('canonical-chat')).not.toContainText('Changed after display');
  await page.getByRole('button', { name: `Approve for request ${scenario.request_id}` }).click();
  await sink(request, scenario);
  expect(control.unexpected).toEqual([]);
});

for (const receipt of ['null', 'invalid'] as const) test(`${receipt} standing receipt does not undo the real decision or invent grant confirmation`, async ({ page, request }) => {
  const control = await guard(page);
  control.receipt = receipt;
  const scenario = await open(page, request);
  const chat = page.getByTestId('canonical-chat');
  await chat.getByRole('checkbox').check();
  await chat.getByRole('spinbutton').fill('1');
  await chat.getByRole('button', { name: `Approve for request ${scenario.request_id}` }).click();
  const evidence = await sink(request, scenario);
  await reconciled(page);
  await expect(chat.getByRole('status')).toHaveText('Approval recorded; standing authority was not confirmed. Future runs may ask again.');
  expect(evidence.action.active_approvals).toHaveLength(1);
  expect((await json(request, '/__approval_ui__/future', {})).admitted).toBe(true);
  await page.getByRole('button', { name: 'Disconnect fixture views', exact: true }).click();
  const reads = control.reads;
  await page.getByRole('button', { name: 'Reconnect fixture views', exact: true }).click();
  await expect(chat.getByRole('status')).toHaveText('Approval recorded; standing authority was not confirmed. Future runs may ask again.');
  expect(control.reads).toBeGreaterThan(reads);
  expect(control.decisions).toBe(1);
  expect(control.unexpected).toEqual([]);
});

test('ordinary standing approval never replays, and later real admission ignores parameters but enforces scope and expiry', async ({ page, request }) => {
  const control = await guard(page);
  const scenario = await open(page, request, { kind: 'action' });
  await expect(page.getByTestId('canonical-chat').getByRole('button')).toHaveCount(0);
  await center(page);
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('Complete action payload')).toContainText('"compute_use_click"');
  await expect(dialog.getByRole('checkbox')).not.toBeChecked();
  await dialog.getByRole('checkbox').check();
  await dialog.getByRole('spinbutton').fill('1');
  await dialog.getByRole('button', { name: 'Approve', exact: true }).click();
  await reconciled(page);
  const evidence = await state(request);
  expect(evidence.request.status).toBe('approved');
  expect(evidence.work_item.status).toBe('blocked');
  expect(evidence.execution_calls).toEqual([]);
  expect(evidence.tool_calls).toEqual([]);
  expect(evidence.action.active_approvals).toHaveLength(1);
  await expect(dialog.getByTestId('capability-decision-feedback')).toHaveText(/original action was not replayed.*Standing authority confirmed.*expires/);
  const later = await json(request, '/__approval_ui__/future', { params: { x: 99, y: 123, selector: '#different' } });
  expect(later.admitted).toBe(true);
  expect(later.thread_id).not.toBe(scenario.thread_id);
  expect(later.requests).toEqual([]);
  const mismatch = await json(request, '/__approval_ui__/future', { scope_key: 'other.example' });
  expect(mismatch.admitted).toBe(false);
  expect(mismatch.requests).toHaveLength(1);
  const expired = await json(request, '/__approval_ui__/future', { expired: true });
  expect(expired.admitted).toBe(false);
  expect(expired.requests).toHaveLength(1);
  const final = await state(request);
  expect(final.tool_calls).toHaveLength(1);
  expect(final.execution_calls).toEqual([]);
  expect(control.unexpected).toEqual([]);
  console.log(`future-action-admission: ${JSON.stringify({ request: scenario.request_id, immediateExecutions: 0,
    admittedLater: later.admitted, changedThread: later.thread_id, scopeRejected: !mismatch.admitted,
    expiryRejected: !expired.admitted, toolCalls: final.tool_calls.length })}`);
});

test('Python numeric boundaries remain approvable and retryable without poisoning unrelated rows or badges', async ({ page, request }) => {
  const control = await guard(page);
  const scenario = await open(page, request, { kind: 'action', numeric_boundary: true });
  const boundary = scenario.numeric_boundary;
  expect(boundary).not.toBeNull();
  if (!boundary) throw new Error('Real Python boundary scenario was not created');
  expect(boundary.ordinary).toEqual({ request_id: scenario.request_id, python_characters: 3998 });
  expect(boundary.repair.python_characters).toBe(4000);
  expect(boundary.repair.can_fulfil).toBe(true);
  expect(boundary.unrelated_request_ids).toHaveLength(2);
  const initialQueue = await json(request, '/api/capability-requests/actionable');
  expect(initialQueue.requests).toHaveLength(4);
  const ordinaryRow = initialQueue.requests.find((row: any) => row.id === scenario.request_id);
  const repairRow = initialQueue.requests.find((row: any) => row.id === boundary.repair.request_id);
  const unrelatedRows = initialQueue.requests.filter((row: any) => boundary.unrelated_request_ids.includes(row.id));
  expect(ordinaryRow).toMatchObject({ status: 'pending', can_retry_fulfilment: false, payload: { params: { x: 1e-6 } } });
  expect(repairRow).toMatchObject({ status: 'approved', can_retry_fulfilment: true, payload: { params: { x: 1e-6 } } });
  expect([...JSON.stringify(ordinaryRow.payload)]).toHaveLength(4001);
  expect([...JSON.stringify(repairRow.payload)]).toHaveLength(4003);
  const before = await state(request);
  expect(before.repair.filing).toMatchObject({ disposition: 'retryable_failure', failure_code: 'pre_send_failure' });
  expect(before.repair.issue_calls).toHaveLength(1);
  expect(before.event_counts.capability_request_decided).toBe(1);
  await center(page, 4);
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByTestId('capability-request-card')).toHaveCount(4);
  const ordinary = dialog.getByRole('group', { name: `Capability request ${scenario.request_id}`, exact: true });
  const repair = dialog.getByRole('group', { name: `Capability request ${boundary.repair.request_id}`, exact: true });
  const assertQueue = async (ids: string[]): Promise<void> => {
    await expect(page.getByRole('button', { name: `BRIDGE (${ids.length})`, exact: true })).toBeVisible();
    await expect(page.getByTestId('bridge-approval-row')).toHaveCount(ids.length);
    await expect(dialog.getByTestId('capability-request-card')).toHaveCount(ids.length);
    await expect.poll(async () => {
      const client = await page.evaluate(() => (window as any).__approvalUi.snapshot());
      return {
        status: client.resource.status, stale: client.resource.stale, refreshing: client.resource.refreshing,
        ids: client.resource.data.requests.map((row: any) => row.id).sort(),
      };
    }).toEqual({ status: 'ready', stale: false, refreshing: false, ids: [...ids].sort() });
    for (const id of boundary.unrelated_request_ids) {
      await expect(dialog.getByRole('group', { name: `Capability request ${id}`, exact: true })
        .getByRole('button', { name: 'Approve', exact: true })).toBeEnabled();
    }
  };
  await assertQueue([scenario.request_id, boundary.repair.request_id, ...boundary.unrelated_request_ids]);
  expect(JSON.parse(await ordinary.getByLabel('Complete action payload', { exact: true }).innerText())).toEqual(ordinaryRow.payload);
  await expect(ordinary.getByLabel('Complete action payload', { exact: true })).toContainText('"x":0.000001');
  await expect(ordinary.getByRole('checkbox')).toBeEnabled();
  await expect(ordinary.getByRole('checkbox')).not.toBeChecked();
  await expect(ordinary.getByRole('button', { name: 'Approve', exact: true })).toBeEnabled();
  await expect(repair.getByRole('checkbox')).toHaveCount(0);
  await expect(repair.getByRole('button', { name: 'Retry fulfilment', exact: true })).toBeEnabled();
  await ordinary.getByRole('button', { name: 'Approve', exact: true }).click();
  await assertQueue([boundary.repair.request_id, ...boundary.unrelated_request_ids]);
  const middle = await state(request);
  expect(middle.request.status).toBe('approved');
  expect(middle.work_item.status).toBe('blocked');
  expect(middle.execution_calls).toEqual([]);
  expect(middle.tool_calls).toEqual([]);
  expect(middle.action.approvals).toEqual([]);
  expect(middle.event_counts.capability_request_decided).toBe(2);
  await repair.getByRole('button', { name: 'Retry fulfilment', exact: true }).click();
  await assertQueue(boundary.unrelated_request_ids);
  const after = await state(request);
  expect(after.repair.request.status).toBe('fulfilled');
  expect(after.repair.request.decided_at).toBe(before.repair.request.decided_at);
  expect(after.repair.filing).toMatchObject({ disposition: 'filed', issue_number: 17 });
  expect(after.repair.issue_calls).toHaveLength(2);
  expect(after.event_counts.capability_request_decided).toBe(2);
  expect(after.event_counts.capability_request_fulfilled).toBe(1);
  expect(after.trust_outcomes).toEqual(middle.trust_outcomes);
  expect(after.trust_outcomes).toHaveLength(2);
  expect(after.action.approvals).toEqual([]);
  expect(after.execution_calls).toEqual([]);
  expect(after.tool_calls).toEqual([]);
  expect(after.decision_post_count).toBe(2);
  expect(after.decision_posts.map((post: any) => post.body)).toEqual([
    { approve: true, reason: '' }, { approve: true, reason: '' },
  ]);
  expect((await json(request, '/api/capability-requests/actionable')).requests).toEqual(unrelatedRows);
  await dialog.getByRole('button', { name: 'Refresh capability requests' }).click();
  await assertQueue(boundary.unrelated_request_ids);
  expect(control.decisions).toBe(2);
  expect(control.unexpected).toEqual([]);
  console.log(`python-numeric-boundary: ${JSON.stringify({
    ordinary: { python: boundary.ordinary.python_characters, js: [...JSON.stringify(ordinaryRow.payload)].length, approved: true },
    repair: { python: boundary.repair.python_characters, js: [...JSON.stringify(repairRow.payload)].length,
      retryEligible: boundary.repair.can_fulfil, status: after.repair.request.status, issueCalls: after.repair.issue_calls.length },
    queueAndBadges: [4, 3, 2], unrelatedIds: boundary.unrelated_request_ids,
    decisionPosts: after.decision_post_count, decisionsBeforeRetry: middle.event_counts.capability_request_decided,
    decisionsAfterRetry: after.event_counts.capability_request_decided, standingRules: after.action.approvals.length,
  })}`);
});

for (const sign of ['positive', 'negative'] as const) test(`Python ${sign} integer overflow retains the real queue and approved repair Retry`, async ({ page, request }) => {
  const control = await guard(page);
  const scenario = await open(page, request, { kind: 'action', numeric_boundary: true, numeric_overflow: sign });
  const boundary = scenario.numeric_boundary;
  if (!boundary) throw new Error('Real Python overflow scenario was not created');
  expect(boundary.ordinary.python_characters).toBe(3998);
  expect(boundary.repair.python_characters).toBe(4000);
  expect(boundary.repair.can_fulfil).toBe(true);
  expect(boundary.unrelated_request_ids).toHaveLength(2);
  const expectedValue = sign === 'positive' ? Infinity : -Infinity;
  const wire = await request.get(bridge + '/api/capability-requests/actionable');
  expect(wire.ok()).toBe(true);
  const text = await wire.text();
  expect(text.split(`"value":${sign === 'negative' ? '-' : ''}1${'0'.repeat(309)}`)).toHaveLength(3);
  expect(text).not.toContain('Infinity');
  expect(text).not.toContain('"value":null');
  const initialQueue = JSON.parse(text);
  const ordinaryRow = initialQueue.requests.find((row: any) => row.id === scenario.request_id);
  const repairRow = initialQueue.requests.find((row: any) => row.id === boundary.repair.request_id);
  expect(ordinaryRow.payload.params.value).toBe(expectedValue);
  expect(repairRow).toMatchObject({ status: 'approved', can_retry_fulfilment: true });
  expect(repairRow.payload.params.value).toBe(expectedValue);
  const before = await state(request);
  expect(before.repair.filing).toMatchObject({ disposition: 'retryable_failure', failure_code: 'pre_send_failure' });
  expect(before.repair.issue_calls).toHaveLength(1);
  expect(before.event_counts.capability_request_decided).toBe(1);
  expect(before.decision_post_count).toBe(0);
  await center(page, 4);
  const dialog = page.getByRole('dialog');
  const ordinary = dialog.getByRole('group', { name: `Capability request ${scenario.request_id}`, exact: true });
  const repair = dialog.getByRole('group', { name: `Capability request ${boundary.repair.request_id}`, exact: true });
  const assertQueue = async (ids: string[]): Promise<void> => {
    await expect(page.getByRole('button', { name: `BRIDGE (${ids.length})`, exact: true })).toBeVisible();
    await expect(page.getByTestId('bridge-approval-row')).toHaveCount(ids.length);
    await expect(dialog.getByTestId('capability-request-card')).toHaveCount(ids.length);
    const overflowIds = [scenario.request_id, boundary.repair.request_id].filter(id => ids.includes(id));
    await expect.poll(() => page.evaluate(({ overflowIds, sign }) => {
      const client = (window as any).__approvalUi.snapshot();
      const rows = client.resource.data.requests;
      return {
        status: client.resource.status, stale: client.resource.stale, refreshing: client.resource.refreshing,
        ids: rows.map((row: any) => row.id).sort(),
        // Assert inside the browser before any test-side JSON serialization can hide Infinity as null.
        decoded: overflowIds.map(id => {
          const value = rows.find((row: any) => row.id === id)?.payload.params.value;
          return { id, type: typeof value, value: String(value), exact: Object.is(value, sign === 'positive' ? Infinity : -Infinity) };
        }),
      };
    }, { overflowIds, sign })).toEqual({
      status: 'ready', stale: false, refreshing: false, ids: [...ids].sort(),
      decoded: overflowIds.map(id => ({ id, type: 'number', value: String(expectedValue), exact: true })),
    });
    for (const id of boundary.unrelated_request_ids) {
      await expect(dialog.getByRole('group', { name: `Capability request ${id}`, exact: true })
        .getByRole('button', { name: 'Approve', exact: true })).toBeEnabled();
    }
  };
  await assertQueue([scenario.request_id, boundary.repair.request_id, ...boundary.unrelated_request_ids]);
  await expect(ordinary.getByText(/Payload numbers must be finite; integers must be safe/)).toBeVisible();
  await expect(ordinary.getByRole('button', { name: 'Approve', exact: true })).toBeDisabled();
  await expect(ordinary.getByRole('checkbox')).toBeDisabled();
  await expect(ordinary.getByRole('checkbox')).not.toBeChecked();
  await expect(ordinary.getByRole('button', { name: 'Deny', exact: true })).toBeEnabled();
  await expect(repair.getByRole('checkbox')).toHaveCount(0);
  await expect(repair.getByRole('button', { name: 'Retry fulfilment', exact: true })).toBeEnabled();
  const readsBeforeRetry = control.reads;
  await repair.getByRole('button', { name: 'Retry fulfilment', exact: true }).click();
  const remaining = initialQueue.requests.filter((row: any) => row.id !== boundary.repair.request_id);
  await assertQueue(remaining.map((row: any) => row.id));
  const confirmation = await page.evaluate(({ repairId, sign }) => {
    const feedback = (window as any).__approvalUi.snapshot().feedback.find(([id]: [string]) => id === repairId)?.[1];
    return {
      fulfilled: feedback?.outcome.fulfilled, status: feedback?.outcome.request.status,
      exact: Object.is(feedback?.outcome.request.payload.params.value, sign === 'positive' ? Infinity : -Infinity),
      standingRequested: feedback?.standingRequested, standingRule: Boolean(feedback?.outcome.standingRule),
    };
  }, { repairId: boundary.repair.request_id, sign });
  expect(confirmation).toEqual({ fulfilled: true, status: 'fulfilled', exact: true, standingRequested: false, standingRule: false });
  const after = await state(request);
  expect(after.repair.request.status).toBe('fulfilled');
  for (const field of ['decided_at', 'decided_by', 'decision_reason', 'payload']) {
    expect(after.repair.request[field]).toEqual(before.repair.request[field]);
  }
  expect(after.repair.filing).toMatchObject({ disposition: 'filed', issue_number: 17 });
  expect(after.repair.issue_calls).toHaveLength(2);
  expect(after.event_counts.capability_request_decided).toBe(1);
  expect(after.event_counts.capability_request_fulfilled).toBe(1);
  expect(after.trust_outcomes).toEqual(before.trust_outcomes);
  expect(after.trust_outcomes).toHaveLength(1);
  expect(after.action.approvals).toEqual([]);
  expect(after.execution_calls).toEqual([]);
  expect(after.tool_calls).toEqual([]);
  expect(after.request.status).toBe('pending');
  expect(after.work_item.status).toBe('blocked');
  expect(after.decision_post_count).toBe(1);
  expect(after.decision_posts[0].body).toEqual({ approve: true, reason: '' });
  expect((await json(request, '/api/capability-requests/actionable')).requests).toEqual(remaining);
  await dialog.getByRole('button', { name: 'Refresh capability requests' }).click();
  await assertQueue(remaining.map((row: any) => row.id));
  expect(control.reads).toBeGreaterThan(readsBeforeRetry);
  expect(control.decisions).toBe(1);
  expect(control.unexpected).toEqual([]);
  console.log(`python-numeric-overflow: ${JSON.stringify({
    sign, browserDecoded: String(expectedValue), ordinaryApprovalDisabled: true,
    queueAndBadges: [4, 3], repairStatus: after.repair.request.status, issueCalls: after.repair.issue_calls.length,
    decisionPosts: after.decision_post_count, decisionsBeforeRetry: before.event_counts.capability_request_decided,
    decisionsAfterRetry: after.event_counts.capability_request_decided, standingRules: after.action.approvals.length,
  })}`);
});

for (const settings of ['real', 'failed', 'disabled'] as const) test(`unselected ordinary approval remains non-replaying with ${settings} standing settings`, async ({ page, request }) => {
  const control = await guard(page);
  control.settings = settings;
  await open(page, request, { kind: 'action' });
  await center(page);
  const dialog = page.getByRole('dialog');
  if (settings !== 'real') await expect(dialog.getByRole('checkbox')).toBeDisabled();
  await dialog.getByRole('button', { name: 'Approve', exact: true }).click();
  await reconciled(page);
  const evidence = await state(request);
  expect(evidence.decision_posts[0].body).toEqual({ approve: true, reason: '' });
  expect(evidence.action.approvals).toEqual([]);
  expect(evidence.execution_calls).toEqual([]);
  expect(evidence.tool_calls).toEqual([]);
  const future = await json(request, '/__approval_ui__/future', {});
  expect(future.admitted).toBe(false);
  expect(future.requests).toHaveLength(1);
  expect(control.unexpected).toEqual([]);
});

test('canonical messages with absent legacy metadata stay text-only even when the visual host matches', async ({ page, request }) => {
  const control = await guard(page);
  control.mutateTranscript = body => { delete body.messages[0].author_id; delete body.messages[0].thread_id; };
  await open(page, request);
  await expect(page.getByTestId('canonical-chat').getByTestId('capability-request-card')).toHaveCount(0);
  await expect(page.getByTestId('canonical-chat').getByRole('button')).toHaveCount(0);
  expect(control.decisions).toBe(0);
  expect((await state(request)).execution_calls).toEqual([]);
  expect(control.unexpected).toEqual([]);
});

test('uninspectable complete payload disables approval, while literal markup remains inert', async ({ page, request }) => {
  const control = await guard(page);
  control.mutateRead = body => {
    body.requests[0].payload.params = { markup: '<img src=x onerror="window.approvalUiPwned=1">', bidi: '\u202e', text: 'x'.repeat(4000) };
  };
  await open(page, request, { kind: 'action' });
  await center(page);
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('button', { name: 'Approve', exact: true })).toBeDisabled();
  await expect(dialog.getByRole('button', { name: 'Deny', exact: true })).toBeEnabled();
  await expect(dialog.getByRole('checkbox')).toBeDisabled();
  await expect(dialog.getByText(/exceeds 4,000 canonical characters/)).toBeVisible();
  await expect(dialog.locator('img, iframe, a')).toHaveCount(0);
  await expect(dialog.getByLabel('Complete action payload')).toContainText('\\u202e');
  expect(await page.evaluate(() => (window as any).approvalUiPwned)).toBeUndefined();
  expect(control.decisions).toBe(0);
  expect(control.unexpected).toEqual([]);
});

test('keyboard dialog focus restores its opener and a retired inline control focuses its request status', async ({ page, request }) => {
  const control = await guard(page);
  const scenario = await open(page, request);
  await page.getByRole('button', { name: 'BRIDGE (1)', exact: true }).focus();
  await page.keyboard.press('Enter');
  const opener = page.getByTestId('bridge-approval-row');
  await opener.focus();
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeFocused();
  await page.keyboard.press('Tab');
  const close = page.getByRole('button', { name: 'Close Approvals' });
  await expect(close).toBeFocused();
  expect(await close.evaluate(element => getComputedStyle(element).outlineColor)).toBe('rgb(240, 176, 96)');
  await page.keyboard.press('Shift+Tab');
  // The real modal also hosts the skill queue; its Refresh is the last tab stop.
  await expect(dialog.getByRole('button', { name: 'Refresh skill requests' })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(close).toBeFocused();
  await dialog.getByRole('button', { name: 'Approve', exact: true }).focus();
  await page.keyboard.press('Tab');
  await expect(dialog.getByRole('button', { name: 'Deny', exact: true })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(opener).toBeFocused();
  await page.getByRole('button', { name: 'Close Bridge' }).click();
  const approve = page.getByRole('button', { name: `Approve for request ${scenario.request_id}` });
  await approve.focus();
  await page.keyboard.press('Enter');
  await sink(request, scenario);
  await expect(page.getByTestId('canonical-chat').getByRole('status')).toBeFocused();
  expect(control.unexpected).toEqual([]);
});
