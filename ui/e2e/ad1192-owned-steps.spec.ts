import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from '@playwright/test';

type SetupResult = {
  scenario: string;
  parent_id: string;
  child_id: string;
  child_ids?: string[];
  worker_ids?: string[];
  thread_id?: string;
  agent_id?: string;
  work_item: Record<string, unknown>;
  worker_calls: number;
};

type Counters = {
  worker: number;
  verifier_model: number;
  synthesis_model: number;
  planner: number;
  ingress_planner: number;
  episodes: number;
  completion_events: Array<Record<string, unknown>>;
};

async function installPreNavigationGuards(page: Page): Promise<string[]> {
  const violations: string[] = [];
  const { uiPort, backendPort } = test.info().config.metadata;
  const ownedOrigins = new Set([
    `http://127.0.0.1:${uiPort}`,
    `http://127.0.0.1:${backendPort}`,
  ]);
  const violation = (rawUrl: string, method: string): string | undefined => {
    const url = new URL(rawUrl);
    if (['data:', 'blob:'].includes(url.protocol)) return undefined;
    const origin = url.origin.replace(/^ws:/, 'http:').replace(/^wss:/, 'https:');
    if (!ownedOrigins.has(origin)) {
      return `external request ${method} ${url.origin}${url.pathname}`;
    }
    if (url.pathname.startsWith('/api/') && /provider|vessel|profile\/live/i.test(url.pathname)) {
      return `forbidden live surface ${method} ${url.pathname}`;
    }
    return undefined;
  };
  await page.context().route('**/*', async route => {
    const request = route.request();
    const reason = violation(request.url(), request.method());
    if (reason) {
      violations.push(reason);
      await route.abort('blockedbyclient');
      return;
    }
    await route.continue();
  });
  await page.context().routeWebSocket('**/*', socket => {
    const reason = violation(socket.url(), 'WEBSOCKET');
    if (reason) {
      violations.push(reason);
      socket.close({ code: 1008, reason: 'AD1192 unowned browser egress blocked' });
      return;
    }
    socket.connectToServer();
  });
  return violations;
}

async function mountWorkItem(page: Page, workItem: Record<string, unknown>): Promise<void> {
  await page.goto('/');
  await page.evaluate((item) => {
    const store = (window as unknown as {
      __store: {
        setState: (state: Record<string, unknown>) => void;
      };
    }).__store;
    store.setState({
      mainViewer: 'work',
      workItems: [item],
      workBookings: [],
      bookableResources: [],
      workTemplates: [],
    });
  }, workItem);
  await expect(page.getByText(String(workItem.title))).toBeVisible();
}

async function openWorkItem(page: Page, workItem: Record<string, unknown>): Promise<void> {
  await page.getByRole('button')
    .filter({ hasText: String(workItem.title) })
    .press('Enter');
}

async function mountProfileWorkItem(page: Page, workItem: Record<string, unknown>): Promise<void> {
  await page.goto('/');
  await page.getByRole('button', { name: 'Got it', exact: true }).click();
  await page.evaluate((item) => {
    const store = (window as unknown as {
      __store: { setState: (state: Record<string, unknown>) => void };
    }).__store;
    const agentId = String(item.assigned_to);
    store.setState({
      mainViewer: 'work',
      workItems: [item], workBookings: [], bookableResources: [], workTemplates: [],
      activeProfileAgent: agentId, activeProfileThreadId: null,
      profilePanelPos: { x: 180, y: 160 },
      agents: new Map([[agentId, {
        id: agentId, agentType: 'builder', callsign: 'Worker', pool: 'crew',
        state: 'active', confidence: 0.8, trust: 0.7, tier: 'domain', isCrew: true,
        position: [0, 0, 0],
      }]]),
    });
  }, workItem);
  await page.getByRole('button', { name: 'Work', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Reassign', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Reassign', exact: true }).click();
  await expect(page.getByTestId(`profile-owned-controls-${workItem.id}`)).toBeVisible();
}

async function setupScenario(
  request: APIRequestContext,
  scenario: string,
): Promise<SetupResult> {
  const response = await request.post(`/__ad1192__/setup/${scenario}`);
  expect(response.ok(), await response.text()).toBeTruthy();
  return await response.json() as SetupResult;
}

async function freshOwned(
  request: APIRequestContext,
  parentId: string,
): Promise<Record<string, any>> {
  const response = await request.get(`/api/work-items/${parentId}/owned-steps`);
  expect(response.ok(), await response.text()).toBeTruthy();
  return await response.json() as Record<string, any>;
}

async function adoptThroughMountedUi(page: Page): Promise<void> {
  await expect(page.getByText(/Managed steps · awaiting_adoption/)).toBeVisible();
  await page.getByTestId('owned-preview-adopt').click();
  await expect(page.getByTestId('owned-proposal')).toContainText('adopt_existing · ready');
  await page.getByTestId('owned-inspect-proposal').click();
  await expect(page.getByTestId('owned-proposal')).toContainText('adopt_existing · ready');
  await page.getByTestId('owned-apply-proposal').click();
  await expect(page.getByText(/Managed steps · active/)).toBeVisible();
}

async function bookingEvidence(
  request: APIRequestContext,
  scenario: string,
  action?: 'start' | 'advance' | 'finish',
): Promise<Record<string, any>> {
  const url = `/__ad1192__/booking/${scenario}`;
  const response = action
    ? await request.post(`${url}/${action}`)
    : await request.get(url);
  expect(response.ok(), await response.text()).toBeTruthy();
  return await response.json();
}

async function mountedOwnedCommand(
  page: Page,
  parentId: string,
  stepId: string,
  kind: string,
  status = 200,
): Promise<Record<string, any>> {
  const response = page.waitForResponse(incoming => (
    incoming.request().method() === 'POST'
    && new URL(incoming.url()).pathname === `/api/work-items/${parentId}/owned-steps/commands`
  ));
  await page.getByTestId(`owned-${kind}-${stepId}`).click();
  const received = await response;
  expect(received.status(), await received.text()).toBe(status);
  await expect(page.getByTestId('owned-refresh')).toBeEnabled();
  return received.request().postDataJSON();
}

function expectExactJournal(evidence: Record<string, any>, kinds: string[]): void {
  const { timestamps, journals } = evidence;
  expect(journals.map((entry: any) => entry.journal_type)).toEqual(kinds);
  expect(journals).toHaveLength(timestamps.length - 1);
  journals.forEach((entry: any, index: number) => {
    expect(entry.start_time).toBe(timestamps[index].timestamp);
    expect(entry.end_time).toBe(timestamps[index + 1].timestamp);
    expect(entry.duration_seconds).toBe(entry.end_time - entry.start_time);
    expect(entry.duration_seconds).toBeGreaterThanOrEqual(0);
    expect(entry.billable).toBe(kinds[index] === 'working');
    // Existing journals represent time; token totals live on booking/child.
    expect(entry.tokens_consumed).toBe(0);
  });
}

test.beforeEach(async ({ context }) => {
  await context.clearCookies();
  await context.clearPermissions();
});

test('pre-navigation guards abort unowned HTTP and WebSocket origins and live surfaces', async ({
  page,
}, testInfo) => {
  const violations = await installPreNavigationGuards(page);
  const failures: string[] = [];
  page.on('requestfailed', request => {
    failures.push(request.failure()?.errorText ?? '');
  });
  await page.goto('/');
  const blockedUrls = [
    'https://owned-steps-egress.invalid/probe',
    `http://localhost:${testInfo.config.metadata.uiPort}/probe`,
    `http://127.0.0.1:${testInfo.config.metadata.uiPort}/api/provider/guard-probe`,
  ];
  const blocked = await page.evaluate(async urls => Promise.all(urls.map(async url => {
    try {
      await fetch(url);
      return false;
    } catch {
      return true;
    }
  })), blockedUrls);
  expect(blocked).toEqual([true, true, true]);
  expect(
    failures.filter(reason => /^net::ERR_BLOCKED_BY_CLIENT(?:\.Inspector)?$/.test(reason)),
    JSON.stringify({ failures, violations }),
  ).toHaveLength(3);
  const closed = await page.evaluate(() => new Promise<number>(resolve => {
    const socket = new WebSocket('ws://owned-steps-egress.invalid/probe');
    socket.addEventListener('close', event => resolve(event.code), { once: true });
  }));
  expect(closed).toBe(1008);
  expect(violations).toEqual([
    'external request GET https://owned-steps-egress.invalid/probe',
    `external request GET http://localhost:${testInfo.config.metadata.uiPort}/probe`,
    'forbidden live surface GET /api/provider/guard-probe',
    'external request WEBSOCKET ws://owned-steps-egress.invalid/probe',
  ]);
});

test('canonical service plan crosses real run restart resume correction finalizer raw API parser and mounted UI', async ({
  page,
  request,
}, testInfo) => {
  console.log(
    `AD1192 owned ports ui=${testInfo.config.metadata.uiPort} backend=${testInfo.config.metadata.backendPort}`,
  );
  const violations = await installPreNavigationGuards(page);
  const setup = await setupScenario(request, 'canonical');
  expect(setup.worker_calls).toBe(0);

  const initialOwnedResponse = page.waitForResponse(response => (
    response.request().method() === 'GET'
    && new URL(response.url()).pathname === `/api/work-items/${setup.parent_id}/owned-steps`
  ));
  await mountWorkItem(page, setup.work_item);
  await openWorkItem(page, setup.work_item);
  const initialRaw = await (await initialOwnedResponse).text();
  const initialOwned = JSON.parse(initialRaw);
  expect(initialOwned.mode).toBe('awaiting_adoption');
  expect(initialOwned.rows.map((row: any) => row.kind)).toEqual(['manual']);
  expect(initialOwned.reference.content_hash).toMatch(/^[a-f0-9]{64}$/);
  await expect(page.getByTestId('work-board-owned-controls')).toBeVisible();

  await adoptThroughMountedUi(page);
  const adopted = await freshOwned(request, setup.parent_id);
  const adoptedChild = adopted.rows.find((row: any) => row.kind === 'child');
  await expect(page.getByTestId(`owned-child-verdict-${adoptedChild.step_id}`))
    .toContainText('Independent verdict');
  const execution = await request.post('/__ad1192__/execute/canonical');
  expect(execution.ok(), await execution.text()).toBeTruthy();
  const executed = await execution.json();
  expect(executed.initial_output).toBe('initial-canonical-result');
  expect(executed.corrected_output).toBe('corrected-canonical-result');
  expect(executed.final_output).toBe('actual-canonical-corrected-result');
  expect(executed.corrected_output).not.toBe(executed.initial_output);
  expect(executed.completed).toBe(false);
  expect(executed.state).toBe('verifying');
  expect(executed.resume_count).toBe(1);
  expect(executed.child_tokens).toBe(14);
  expect(executed.worker_calls_after - executed.worker_calls_before).toBe(2);

  await page.getByTestId('owned-refresh').click();
  await expect(page.getByText(/Managed steps · waiting_manual_gate/)).toBeVisible();
  const waiting = await freshOwned(request, setup.parent_id);
  const manual = waiting.rows.find((row: any) => row.kind === 'manual');
  const child = waiting.rows.find((row: any) => row.kind === 'child');
  expect(child.todo.status).toBe('done');
  expect(child.evidence.review_accepted).toBe(true);
  await page.getByTestId(`owned-detail-${child.step_id}`).click();
  await expect(page.getByTestId('owned-step-detail')).toContainText('"read_only": true');

  expect((await request.post('/__ad1192__/dm/block')).ok()).toBeTruthy();
  const dmPromise = request.post(`/api/agent/${setup.agent_id}/chat`, {
    data: {
      message: 'captain raw canonical stale command',
      thread_id: setup.thread_id,
    },
  });
  expect((await request.get('/__ad1192__/dm/wait-entered')).ok()).toBeTruthy();
  const captured = await (await request.get('/__ad1192__/state')).json();
  expect(captured.dm.descriptor.actor_id).toBe(setup.agent_id);
  expect(captured.dm.descriptor.parent_id).toBe(setup.parent_id);
  expect(captured.dm.last_prompt).toMatch(/"token"\s*:\s*\{/);
  expect(captured.dm.last_prompt).toContain('manual_submit');
  await page.getByTestId(`owned-manual_submit-${manual.step_id}`).click();
  await expect(page.getByTestId(`owned-manual_confirm-${manual.step_id}`)).toBeVisible();
  expect((await request.post('/__ad1192__/dm/release')).ok()).toBeTruthy();
  const dm = await dmPromise;
  expect(dm.ok(), await dm.text()).toBeTruthy();
  const returned = (await dm.json()).response as string;
  expect(returned).toContain('owned_steps_row_conflict');
  expect(returned).toContain('not saved');
  const staleEvidence = await (await request.get('/__ad1192__/state')).json();
  expect(staleEvidence.dm.persisted).toBe(returned);
  expect(staleEvidence.dm.captain_message).toBe('captain raw canonical stale command');
  expect(staleEvidence.dm.descriptor).toEqual(captured.dm.descriptor);
  expect(staleEvidence.dm.requests).toBe(captured.dm.requests);
  expect(staleEvidence.counters).toMatchObject({
    worker: captured.counters.worker,
    verifier_model: captured.counters.verifier_model,
    synthesis_model: captured.counters.synthesis_model,
    planner: captured.counters.planner,
  });
  const beforeClose = staleEvidence.counters as Counters;
  const canonicalConfirm = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname
      === `/api/work-items/${setup.parent_id}/owned-steps/commands`
  ));
  await page.getByTestId(`owned-manual_confirm-${manual.step_id}`).click();
  expect((await canonicalConfirm).ok()).toBeTruthy();
  const closedResponse = await request.get('/__ad1192__/await/canonical');
  expect(closedResponse.ok(), await closedResponse.text()).toBeTruthy();
  const closed = await closedResponse.json();
  expect(closed.completed).toBe(true);
  expect(closed.final_output).toBe('actual-canonical-corrected-result');
  expect(closed.work_item.metadata.crew_session.result_artifact_id).toMatch(
    /^[A-Za-z0-9_.:-]+$/,
  );
  expect(closed.work_item.metadata.crew_session.revision).toBeGreaterThan(1);
  // The former subset omitted planner and completion-event attempts.
  expect(closed.counters).toEqual(beforeClose);
  await page.getByTestId('owned-refresh').click();
  await expect(page.getByText(/Managed steps · completed/)).toBeVisible();

  const evidence = await (await request.get('/__ad1192__/state')).json();
  const candidateRoot = String(testInfo.config.metadata.candidateRoot).replaceAll('\\', '/');
  for (const origin of Object.values(evidence.origins) as string[]) {
    expect(origin.replaceAll('\\', '/').startsWith(`${candidateRoot}/`)).toBeTruthy();
  }
  expect(evidence.python.replaceAll('\\', '/').toLowerCase())
    .toBe('d:/probos/.venv/scripts/python.exe');
  expect(evidence.cwd.replaceAll('\\', '/')).toBe(`${candidateRoot}/ui`);
  console.log(
    `AD1192 fixture pid=${evidence.pid} python=${evidence.python} candidate=${candidateRoot}`,
  );
  expect(evidence.canonical).toEqual({
    initial: 'initial-canonical-result',
    corrected: 'corrected-canonical-result',
    final: 'actual-canonical-corrected-result',
    resume_count: 1,
  });
  expect(evidence.trust['worker-a']).toEqual({ alpha: 2.5, beta: 2 });
  // Trust delivery is gated by canonical publication. The former equality
  // incorrectly prohibited its first delivery instead of detecting a replay.
  expect(staleEvidence.trust).toEqual({});
  expect(evidence.trust['verifier-a']).toEqual({ alpha: 3, beta: 2 });
  expect(evidence.episode_ids).toEqual(staleEvidence.episode_ids);
  // This formerly asserted zero with no DM. The two normal DM memory writes
  // are allowed; receipt-only gate release must not add a third write.
  expect(evidence.counters.episodes).toBe(2);
  const artifact = evidence.artifacts.canonical;
  expect(artifact.count).toBe(1);
  expect(artifact.latest).toHaveLength(1);
  expect(artifact.versions).toEqual(artifact.latest);
  expect(artifact.versions[0]).toMatchObject({
    id: closed.work_item.metadata.crew_session.result_artifact_id,
    thread_id: setup.thread_id,
    version: 1,
    supersedes: null,
  });
  expect(artifact.versions[0].content_hash).toMatch(/^[a-f0-9]{64}$/);
  const completedView = await freshOwned(request, setup.parent_id);
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const finalized = await request.post(
      `/api/work-items/${setup.parent_id}/owned-steps/finalize`,
      { data: { version: 1, reference: completedView.reference } },
    );
    expect(finalized.ok(), await finalized.text()).toBeTruthy();
    expect(await finalized.json()).toEqual({ disposition: 'completed' });
  }
  const retried = await (await request.get('/__ad1192__/state')).json();
  expect(retried.counters).toEqual(evidence.counters);
  expect(retried.trust).toEqual(evidence.trust);
  expect(retried.episode_ids).toEqual(evidence.episode_ids);
  expect(retried.artifacts).toEqual(evidence.artifacts);
  expect(retried.events).toEqual(evidence.events);
  const afterRetry = await (await request.get('/__ad1192__/await/canonical')).json();
  expect(afterRetry.work_item).toEqual(closed.work_item);
  expect(evidence.process_owner).toBe(testInfo.config.metadata.processOwner);
  expect(violations).toEqual([]);
});

test('legacy persisted adoption stale blocked DM refusal and manual-gate finalize-only cross returned and stored egress', async ({
  page,
  request,
}) => {
  const violations = await installPreNavigationGuards(page);
  const baseline = await (await request.get('/__ad1192__/state')).json();
  const setup = await setupScenario(request, 'legacy');
  await mountWorkItem(page, setup.work_item);
  await openWorkItem(page, setup.work_item);
  await adoptThroughMountedUi(page);

  const prime = await request.post('/__ad1192__/prime/legacy');
  expect(prime.ok(), await prime.text()).toBeTruthy();
  const primed = await prime.json();
  expect(primed.completed).toBe(false);
  expect(primed.disposition).toBe('pending');
  expect(primed.after.completion_events).toHaveLength(1);
  expect(primed.after.completion_events[0].completed).toBe(false);
  await page.getByTestId('owned-refresh').click();
  await expect(page.getByText(/Managed steps · waiting_manual_gate/)).toBeVisible();

  expect((await request.post('/__ad1192__/dm/block')).ok()).toBeTruthy();
  const dmPromise = request.post(`/api/agent/${setup.agent_id}/chat`, {
    data: {
      message: 'captain raw stale command',
      thread_id: setup.thread_id,
    },
  });
  const entered = await request.get('/__ad1192__/dm/wait-entered');
  expect(entered.ok()).toBeTruthy();

  const viewed = await freshOwned(request, setup.parent_id);
  const manual = viewed.rows.find((row: any) => row.kind === 'manual');
  await page.getByTestId(`owned-manual_submit-${manual.step_id}`).click();
  await expect(page.getByTestId(`owned-manual_confirm-${manual.step_id}`)).toBeVisible();
  expect((await request.post('/__ad1192__/dm/release')).ok()).toBeTruthy();
  const dm = await dmPromise;
  expect(dm.ok(), await dm.text()).toBeTruthy();
  const returned = (await dm.json()).response as string;
  expect(returned).toContain('Owned steps refused');
  // This formerly pinned a leaked reader write token reaching row/store
  // authority. Readonly projection now withholds it before mutation dispatch.
  expect(returned).toContain('owned_steps_hidden_or_unpresented');
  expect(returned).toContain('not saved');

  const beforeCloseEvidence = await (await request.get('/__ad1192__/state')).json();
  const beforeClose = beforeCloseEvidence.counters as Counters;
  const legacyConfirm = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname
      === `/api/work-items/${setup.parent_id}/owned-steps/commands`
  ));
  await page.getByTestId(`owned-manual_confirm-${manual.step_id}`).click();
  expect((await legacyConfirm).ok()).toBeTruthy();
  const closedResponse = await request.get('/__ad1192__/await/legacy');
  expect(closedResponse.ok(), await closedResponse.text()).toBeTruthy();
  const closed = await closedResponse.json();
  expect(closed.completed).toBe(true);
  // Include the frozen completed=false event, not just cognition counters.
  expect(closed.counters).toEqual(beforeClose);
  const evidence = await (await request.get('/__ad1192__/state')).json();
  expect(evidence.trust).toEqual(beforeCloseEvidence.trust);
  expect(evidence.episode_ids).toEqual(beforeCloseEvidence.episode_ids);
  expect(evidence.dm.persisted).toBe(returned);
  expect(evidence.dm.captain_message).toBe('captain raw stale command');
  expect(evidence.dm.descriptor.rows).toBeUndefined();
  expect(JSON.stringify(evidence.dm.descriptor).length).toBeLessThanOrEqual(4096);
  expect(evidence.dm.last_prompt).toContain('"rows":');
  // These formerly pinned server-global totals, which hid test-order coupling.
  // Assert this scenario's one DM and three new episodes independently.
  expect(evidence.dm.requests - baseline.dm.requests).toBe(1);
  expect(evidence.counters.episodes - baseline.counters.episodes).toBe(3);
  expect(evidence.episode_ids).toHaveLength(baseline.episode_ids.length + 3);
  expect(new Set(evidence.episode_ids).size).toBe(evidence.episode_ids.length);
  for (const episodeId of evidence.episode_ids) {
    expect(episodeId).toMatch(/^[a-f0-9]{32,64}$/);
  }
  const completedView = await freshOwned(request, setup.parent_id);
  const finalized = await request.post(
    `/api/work-items/${setup.parent_id}/owned-steps/finalize`,
    { data: { version: 1, reference: completedView.reference } },
  );
  expect(finalized.ok(), await finalized.text()).toBeTruthy();
  expect(await finalized.json()).toEqual({ disposition: 'completed' });
  const retried = await (await request.get('/__ad1192__/state')).json();
  expect(retried.counters).toEqual(evidence.counters);
  expect(retried.trust).toEqual(evidence.trust);
  expect(retried.episode_ids).toEqual(evidence.episode_ids);
  const afterRetry = await (await request.get('/__ad1192__/await/legacy')).json();
  expect(afterRetry.work_item).toEqual(closed.work_item);
  expect(violations).toEqual([]);
});

test('restart lost acknowledgement exact retry stale second-store conflict and two fresh replans cross actual UI controls', async ({
  page,
  request,
}) => {
  const violations = await installPreNavigationGuards(page);
  const setup = await setupScenario(request, 'replan');
  const applyBodies: any[] = [];
  page.on('request', outgoing => {
    const url = new URL(outgoing.url());
    if (
      outgoing.method() === 'POST'
      && url.pathname === `/api/work-items/${setup.parent_id}/owned-steps/commands`
    ) {
      const value = outgoing.postDataJSON();
      if (value && 'operation_id' in value) applyBodies.push(value);
    }
  });
  await mountWorkItem(page, setup.work_item);
  await openWorkItem(page, setup.work_item);
  await expect(page.getByText(/Managed steps · active/)).toBeVisible();

  const original = await request.get(`/__ad1192__/membership/replan`);
  const originalIds = (await original.json()).active as string[];
  const requiredView = await freshOwned(request, setup.parent_id);
  expect(
    requiredView.recovery,
    'Active unstarted owned work must expose replan_unstarted to mounted UI.',
  ).toContain('replan_unstarted');
  await page.getByTestId('owned-preview-replan').click();
  await expect(page.getByTestId('owned-proposal')).toContainText('replan_unstarted · ready');
  expect((await request.post('/__ad1192__/restart')).ok()).toBeTruthy();
  expect((await request.post('/__ad1192__/fault/lost-ack')).ok()).toBeTruthy();
  await page.getByTestId('owned-apply-proposal').click();
  await expect(page.getByTestId('owned-steps-feedback'))
    .toContainText('Inspect and retry the exact proposal.');
  await page.getByTestId('owned-apply-proposal').click();
  await expect(page.getByTestId('owned-proposal')).toHaveCount(0);
  await expect(page.getByTestId('owned-preview-replan')).toBeEnabled();
  await expect(page.getByText(/Managed steps · active/)).toBeVisible();
  expect(applyBodies).toHaveLength(2);
  expect(applyBodies[1].operation_id).toBe(applyBodies[0].operation_id);

  const firstMembership = await (await request.get('/__ad1192__/membership/replan')).json();
  expect(new Set(firstMembership.active).isDisjointFrom(new Set(originalIds))).toBe(true);
  expect(firstMembership.retired).toEqual(expect.arrayContaining(originalIds));
  await page.getByTestId('owned-preview-replan').click();
  await expect(page.getByTestId('owned-proposal')).toContainText('replan_unstarted · ready');
  await page.getByTestId('owned-apply-proposal').click();
  await expect(page.getByTestId('owned-proposal')).toHaveCount(0);
  await expect(page.getByTestId('owned-preview-replan')).toBeEnabled();
  await expect(page.getByText(/Managed steps · active/)).toBeVisible();
  const secondMembership = await (await request.get('/__ad1192__/membership/replan')).json();
  expect(new Set(secondMembership.active).isDisjointFrom(new Set(firstMembership.active))).toBe(true);
  expect(secondMembership.retired).toEqual(expect.arrayContaining([
    ...originalIds,
    ...firstMembership.active,
  ]));
  expect(secondMembership.planner_calls).toBe(2);

  await page.getByTestId('owned-preview-replan').click();
  await expect(page.getByTestId('owned-proposal')).toContainText('replan_unstarted · ready');
  const secondWrite = await request.post('/__ad1192__/second-store-start/replan');
  expect(secondWrite.ok(), await secondWrite.text()).toBeTruthy();
  await page.getByTestId('owned-apply-proposal').click();
  await expect(page.getByTestId('owned-steps-feedback')).toContainText(/stale|conflict|admission/i);
  const afterConflict = await (await request.get('/__ad1192__/membership/replan')).json();
  expect(afterConflict.active).toEqual(secondMembership.active);
  expect(afterConflict.retired).toEqual(secondMembership.retired);
  expect(violations).toEqual([]);
});

test('retired history exceeds 1000 while active stays bounded through repeated actual proposal UI', async ({
  page,
  request,
}) => {
  const violations = await installPreNavigationGuards(page);
  const setup = await setupScenario(request, 'replan');
  expect((await request.post('/__ad1192__/history', { data: { count: 200 } })).ok())
    .toBeTruthy();
  await mountWorkItem(page, setup.work_item);
  await openWorkItem(page, setup.work_item);

  let priorActive = (await (await request.get('/__ad1192__/membership/replan')).json()).active as string[];
  const requiredView = await freshOwned(request, setup.parent_id);
  expect(
    requiredView.recovery,
    'Active unstarted owned work must expose replan_unstarted to mounted UI.',
  ).toContain('replan_unstarted');
  for (let index = 0; index < 6; index += 1) {
    await page.getByTestId('owned-preview-replan').click();
    await expect(page.getByTestId('owned-proposal')).toContainText('replan_unstarted · ready');
    await page.getByTestId('owned-apply-proposal').click();
    await expect(page.getByTestId('owned-proposal')).toHaveCount(0);
    await expect(page.getByTestId('owned-preview-replan')).toBeEnabled();
    await expect(page.getByText(/Managed steps · active/)).toBeVisible();
    const membership = await (await request.get('/__ad1192__/membership/replan')).json();
    expect(membership.active).toHaveLength(200);
    expect(new Set(membership.active).isDisjointFrom(new Set(priorActive))).toBe(true);
    priorActive = membership.active;
  }
  const finalMembership = await (await request.get('/__ad1192__/membership/replan')).json();
  expect(finalMembership.active).toHaveLength(200);
  expect(finalMembership.retired).toHaveLength(1002);
  expect(finalMembership.planner_calls).toBe(6);
  expect(violations).toEqual([]);
});

test('mounted ownership error preserves raw malformed and oversized evidence through explicit replacement then separate adoption', async ({
  page,
  request,
}) => {
  const violations = await installPreNavigationGuards(page);
  for (const scenario of ['malformed', 'oversized']) {
    const setup = await setupScenario(request, scenario);
    const applyBodies: any[] = [];
    page.on('request', outgoing => {
      const url = new URL(outgoing.url());
      if (
        outgoing.method() === 'POST'
        && url.pathname === `/api/work-items/${setup.parent_id}/owned-steps/commands`
      ) {
        const value = outgoing.postDataJSON();
        if (value && 'operation_id' in value) applyBodies.push(value);
      }
    });
    await mountWorkItem(page, setup.work_item);
    await openWorkItem(page, setup.work_item);
    await expect(page.getByTestId('work-board-ownership-error')).toContainText(/repair/i);
    await page.getByTestId('owned-load-repair').click();
    const editor = page.getByLabel('Exact recovery prefix JSON');
    if (scenario === 'malformed') {
      await expect(editor).toHaveValue('[{"label": "Historical", "status": "completed"}]');
    } else {
      await expect(editor).toHaveValue('');
      await expect(page.getByText('Readonly evidence omitted: raw_steps.'))
        .toBeVisible();
    }
    await editor.fill('[{"label":"Corrected","status":"pending"}]');
    await page.getByTestId('owned-recovery-preview-prefix').click();
    await expect(page.getByTestId('owned-recovery-proposal'))
      .toContainText('replace_manual_prefix · ready');
    if (scenario === 'malformed') {
      expect((await request.post('/__ad1192__/fault/lost-ack')).ok()).toBeTruthy();
      await page.getByTestId('owned-recovery-apply').click();
      await expect(page.getByText('Inspect and retry the exact proposal.'))
        .toContainText('Inspect and retry the exact proposal.');
    }
    await page.getByTestId('owned-recovery-apply').click();
    await expect(page.getByText(/Managed steps · awaiting_adoption/)).toBeVisible();
    if (scenario === 'malformed') {
      expect(applyBodies).toHaveLength(2);
      expect(applyBodies[1].operation_id).toBe(applyBodies[0].operation_id);
    }
    await adoptThroughMountedUi(page);
  }
  expect(violations).toEqual([]);
});

test('mounted production paging reaches outside-page rows and readonly detail without polling', async ({
  page,
  request,
}) => {
  const violations = await installPreNavigationGuards(page);
  const setup = await setupScenario(request, 'paging');
  const initial = await freshOwned(request, setup.parent_id);
  expect(initial.rows.length).toBeGreaterThan(0);
  expect(initial.next_cursor).not.toBeNull();
  await mountWorkItem(page, setup.work_item);
  await openWorkItem(page, setup.work_item);
  await expect(page.getByText(
    `Managed steps · awaiting_adoption · page ${initial.rows.length}`,
  ))
    .toBeVisible();
  const firstIds = await page.locator('li[data-testid^="owned-step-"]')
    .evaluateAll(nodes => nodes.map(node => node.getAttribute('data-testid')));
  expect(firstIds).toHaveLength(initial.rows.length);
  const nextPage = page.waitForResponse(response => (
    response.request().method() === 'GET'
    && new URL(response.url()).pathname
      === `/api/work-items/${setup.parent_id}/owned-steps`
    && new URL(response.url()).searchParams.has('cursor')
  ));
  await page.getByTestId('owned-page-next').click();
  expect((await nextPage).ok()).toBeTruthy();
  await expect(page.locator(`li[data-testid="${firstIds[0]}"]`)).toHaveCount(0);
  await expect(page.getByText(/Managed steps · awaiting_adoption · page /))
    .toBeVisible();
  const secondRows = page.locator('li[data-testid^="owned-step-"]');
  const secondIds = await secondRows.evaluateAll(
    nodes => nodes.map(node => node.getAttribute('data-testid')),
  );
  expect(secondIds.length).toBeGreaterThan(0);
  expect(new Set(secondIds).isDisjointFrom(new Set(firstIds))).toBe(true);
  const outsideStepId = String(secondIds[0]).replace('owned-step-', '');
  await page.getByTestId(`owned-detail-${outsideStepId}`).click();
  await expect(page.getByTestId('owned-step-detail'))
    .toContainText('"read_only": true');
  expect(violations).toEqual([]);
});

for (const surface of ['WorkBoard', 'Profile'] as const) {
  test(`${surface} mounted child URLs edit preview adopt replan and repair the authoritative parent`, async ({
    page, request,
  }) => {
    const violations = await installPreNavigationGuards(page);
    const setup = await setupScenario(request, surface === 'Profile' ? 'legacy-profile' : 'legacy-child');
    const childResponse = await request.get(`/api/work-items/${setup.child_id}`);
    expect(childResponse.ok()).toBeTruthy();
    const child = (await childResponse.json()).work_item as Record<string, unknown>;
    expect(child.parent_id).toBe(setup.parent_id);
    expect(child.status).toBe(surface === 'Profile' ? 'blocked' : 'open');
    const ownerPaths: string[] = [];
    page.on('request', outgoing => {
      const pathname = new URL(outgoing.url()).pathname;
      if (pathname.includes('/owned-steps')) ownerPaths.push(pathname);
    });
    if (surface === 'WorkBoard') {
      await mountWorkItem(page, child);
      await openWorkItem(page, child);
    } else {
      await mountProfileWorkItem(page, child);
    }
    await expect(page.getByText(/Managed steps · awaiting_adoption/)).toBeVisible();
    const initial = await freshOwned(request, setup.child_id);
    page.once('dialog', dialog => dialog.accept('Current note from mounted child'));
    await page.getByTestId(`owned-edit_note-${initial.rows[0].step_id}`).click();
    await expect(page.getByText('Current note from mounted child', { exact: true })).toBeVisible();
    await adoptThroughMountedUi(page);
    if (surface === 'WorkBoard') {
      await page.getByTestId('owned-preview-replan').click();
      await expect(page.getByTestId('owned-proposal')).toContainText('replan_unstarted · ready');
      await page.getByTestId('owned-apply-proposal').click();
      await expect(page.getByTestId('owned-preview-replan')).toBeEnabled();
    } else {
      // Profile's existing actions belong to blocked work. Its interrupted
      // child must not gain an unstarted-replan permission through parent resolution.
      await expect(page.getByTestId('owned-preview-replan')).toHaveCount(0);
      const interrupted = await freshOwned(request, setup.child_id);
      const refused = await request.post(`/api/work-items/${setup.child_id}/owned-steps/preview`, {
        data: {
          version: 1, kind: 'replan_unstarted', preparation_id: 'profile-interrupted-replan',
          reference: interrupted.reference,
        },
      });
      expect(refused.status()).toBe(409);
      expect((await refused.json()).detail.parent_id).toBe(setup.parent_id);
    }
    const replanned = await freshOwned(request, setup.child_id);
    expect(replanned.rows[0].todo.note).toBe('Current note from mounted child');
    expect(replanned.parent_id).toBe(setup.parent_id);
    expect(replanned.requested_item_id).toBe(setup.child_id);
    await page.getByTestId('owned-open-repair').click();
    const prefix = '[ { "label" : "Child-controlled exact repair", "status" : "pending" } ]';
    await page.getByLabel('Exact replacement prefix JSON').fill(prefix);
    await page.getByTestId('owned-preview-repair').click();
    await expect(page.getByTestId('owned-proposal')).toContainText('replace_manual_prefix · ready');
    const repaired = page.waitForResponse(response => (
      response.request().method() === 'POST'
      && new URL(response.url()).pathname === `/api/work-items/${setup.child_id}/owned-steps/commands`
    ));
    await page.getByTestId('owned-apply-proposal').click();
    expect((await repaired).ok()).toBeTruthy();
    await expect(page.getByTestId('owned-steps-panel')).toContainText('Child-controlled exact repair');
    expect(ownerPaths.length).toBeGreaterThan(10);
    expect(ownerPaths.every(value => value.startsWith(`/api/work-items/${setup.child_id}/owned-steps`))).toBe(true);
    expect(ownerPaths).toContain(`/api/work-items/${setup.child_id}/owned-steps/adopt`);
    expect(ownerPaths).toContain(`/api/work-items/${setup.child_id}/owned-steps/repair`);
    expect(ownerPaths).toContain(`/api/work-items/${setup.child_id}/owned-steps/commands`);
    const parent = (await (await request.get(`/api/work-items/${setup.parent_id}`)).json()).work_item;
    expect(parent.steps[0].label).toBe('Child-controlled exact repair');
    expect(violations).toEqual([]);
  });
}

test('actual 5000-character owned label crosses backend wire page detail and mounted controls intact', async ({
  page, request,
}) => {
  const violations = await installPreNavigationGuards(page);
  const setup = await setupScenario(request, 'long-row');
  const response = await request.get(`/api/work-items/${setup.parent_id}/owned-steps`);
  expect(response.ok()).toBeTruthy();
  const wire = await response.text();
  const observed = JSON.parse(wire);
  expect(observed.rows[0].todo.label).toBe('x'.repeat(5000));
  expect(Buffer.byteLength(wire)).toBeGreaterThan(7000);
  expect(Buffer.byteLength(wire)).toBeLessThan(16_384);
  await mountWorkItem(page, setup.work_item);
  await openWorkItem(page, setup.work_item);
  await expect(page.getByTestId(`owned-step-${observed.rows[0].step_id}`)).toContainText('x'.repeat(5000));
  await page.getByTestId(`owned-detail-${observed.rows[0].step_id}`).click();
  await expect(page.getByTestId('owned-step-detail')).toContainText('x'.repeat(5000));
  await expect(page.getByTestId('owned-step-detail')).toContainText('"read_only": true');
  const legacy = await request.get(`/api/work-items/${setup.parent_id}/steps`);
  expect((await legacy.json()).steps[0].label).toBe('x'.repeat(5000));
  expect(violations).toEqual([]);
});

test('mounted booking CLOCK ONLY pause resume preserves a running permit and closes on break exactly once', async ({
  page,
  request,
  context,
}) => {
  const violations = await installPreNavigationGuards(page);
  const setup = await setupScenario(request, 'booking-clock');
  const before = await bookingEvidence(request, setup.scenario);
  await mountWorkItem(page, setup.work_item);
  await openWorkItem(page, setup.work_item);
  const started = await bookingEvidence(request, setup.scenario, 'start');
  expect(started.child.bookings[0].status).toBe('active');
  expect(started.child.work_item.actual_tokens).toBe(0);
  expect(started.permit.booking_id).toBe(started.child.bookings[0].id);
  expect(started.row.permit_state).toBe('started');
  await page.getByTestId('owned-refresh').click();
  const stepId = started.row.step_id;
  await expect(page.getByTestId(`owned-pause_accounting-${stepId}`))
    .toHaveText('Pause BOOKING CLOCK ONLY; worker continues');
  await expect(page.getByTestId(`owned-resume_accounting-${stepId}`))
    .toHaveText('Resume BOOKING CLOCK ONLY; worker continues');

  const stale = await context.newPage();
  const staleViolations = await installPreNavigationGuards(stale);
  await mountWorkItem(stale, setup.work_item);
  await openWorkItem(stale, setup.work_item);
  await expect(stale.getByTestId(`owned-pause_accounting-${stepId}`)).toBeVisible();
  await mountedOwnedCommand(page, setup.parent_id, stepId, 'pause_accounting');
  const paused = await bookingEvidence(request, setup.scenario);
  expect(paused.permit).toEqual(started.permit);
  expect(paused.row.permit).toBe(started.row.permit);
  expect(paused.row.permit_state).toBe('started');
  expect(paused.child.work_item).toEqual(started.child.work_item);
  expect(paused.child.bookings).toEqual([
    { ...started.child.bookings[0], status: 'on_break' },
  ]);
  expect(paused.child.timestamps.slice(0, -1)).toEqual(started.child.timestamps);
  expect(paused.child.timestamps.at(-1)).toMatchObject({
    status: 'on_break', source: 'owned_accounting',
  });
  expect(paused.child.journals).toEqual([]);
  const progressed = await bookingEvidence(request, setup.scenario, 'advance');
  expect(progressed.progress).toEqual([{
    iteration: 1, permit: started.permit, thread_id: '',
  }]);
  expect(progressed.child).toEqual(paused.child);
  expect(progressed.counters).toEqual(started.counters);
  expect(progressed.worker_calls).toHaveLength(1);

  const resumeBody = await mountedOwnedCommand(
    page, setup.parent_id, stepId, 'resume_accounting',
  );
  const resumed = await bookingEvidence(request, setup.scenario);
  expect(resumed.permit).toEqual(started.permit);
  expect(resumed.child.work_item).toEqual(started.child.work_item);
  expect(resumed.child.bookings).toEqual(started.child.bookings);
  expect(resumed.child.timestamps.map((stamp: any) => stamp.status))
    .toEqual(['scheduled', 'active', 'on_break', 'active']);
  const duplicate = await request.post(
    `/api/work-items/${setup.parent_id}/owned-steps/commands`,
    { data: resumeBody },
  );
  expect(duplicate.ok(), await duplicate.text()).toBeTruthy();
  expect(await bookingEvidence(request, setup.scenario)).toEqual(resumed);
  await mountedOwnedCommand(stale, setup.parent_id, stepId, 'pause_accounting', 409);
  await expect(stale.getByTestId('owned-steps-feedback'))
    .toContainText('owned_steps_row_conflict');
  expect(await bookingEvidence(request, setup.scenario)).toEqual(resumed);

  await mountedOwnedCommand(page, setup.parent_id, stepId, 'pause_accounting');
  const stillRunning = await bookingEvidence(request, setup.scenario, 'advance');
  expect(stillRunning.progress).toHaveLength(2);
  expect(stillRunning.progress[1].permit).toEqual(started.permit);
  expect(stillRunning.child.bookings[0].status).toBe('on_break');
  const finished = await bookingEvidence(request, setup.scenario, 'finish');
  expect(finished.execution.results).toHaveLength(1);
  expect(finished.execution.results[0]).toMatchObject({
    status: 'done', actual_tokens: 7, agent_id: 'worker-a',
  });
  expect(finished.child.work_item.actual_tokens).toBe(7);
  expect(finished.child.work_item.verification).toEqual({});
  expect(finished.row.permit_state).toBe('submitted');
  expect(JSON.parse(finished.row.todo_json).status).toBe('submitted');
  expect(finished.row.reviewed_result).toBeNull();
  expect(finished.child.bookings[0]).toMatchObject({
    status: 'completed', total_tokens_consumed: 7,
    actual_start: started.child.bookings[0].actual_start,
  });
  expect(finished.child.bookings[0].actual_end)
    .toBe(finished.child.work_item.updated_at);
  // Booking end and its append-only timestamp are separately sampled by the
  // existing store; only the journal boundaries must equal timestamp pairs.
  expect(finished.child.timestamps.at(-1).timestamp)
    .toBeGreaterThanOrEqual(finished.child.bookings[0].actual_end);
  expect(finished.child.timestamps.map((stamp: any) => stamp.status))
    .toEqual(['scheduled', 'active', 'on_break', 'active', 'on_break', 'completed']);
  expectExactJournal(finished.child, ['idle', 'working', 'break', 'working', 'break']);
  expect(finished.events.filter((event: any) => event.type === 'booking_completed'))
    .toHaveLength(1);
  expect(finished.worker_calls).toHaveLength(1);
  expect(finished.counters).toEqual(started.counters);
  for (const observed of [started, paused, progressed, resumed, stillRunning, finished]) {
    expect(observed.unrelated).toEqual(before.unrelated);
  }
  expect(before.unrelated[0].work_item.actual_tokens).toBe(11);
  expectExactJournal(before.unrelated[0], ['idle', 'working']);
  await page.getByTestId('owned-refresh').click();
  await expect(page.getByTestId(`owned-pause_accounting-${stepId}`)).toHaveCount(0);
  await expect(page.getByTestId(`owned-manual_confirm-${stepId}`)).toHaveCount(0);
  expect(violations).toEqual([]);
  expect(staleViolations).toEqual([]);
  await stale.close();
});

test('mounted real unstarted reassignment replaces only its scheduled booking and rejects stale controls', async ({
  page,
  request,
  context,
}) => {
  const violations = await installPreNavigationGuards(page);
  const setup = await setupScenario(request, 'booking-reassign');
  const initial = await bookingEvidence(request, setup.scenario);
  const stepId = initial.row.step_id;
  expect(initial.row.permit_state).toBe('unstarted');
  expect(initial.permit).toBeNull();
  await mountWorkItem(page, setup.work_item);
  await openWorkItem(page, setup.work_item);
  const stale = await context.newPage();
  const staleViolations = await installPreNavigationGuards(stale);
  await mountWorkItem(stale, setup.work_item);
  await openWorkItem(stale, setup.work_item);
  await expect(stale.getByTestId(`owned-reassign_unstarted-${stepId}`)).toBeVisible();

  page.once('dialog', dialog => dialog.accept('unregistered-worker'));
  await mountedOwnedCommand(page, setup.parent_id, stepId, 'reassign_unstarted', 409);
  await expect(page.getByTestId('owned-steps-feedback'))
    .toContainText('owned_steps_assignment_ineligible');
  expect(await bookingEvidence(request, setup.scenario)).toEqual(initial);
  page.once('dialog', dialog => dialog.accept('worker-b'));
  await mountedOwnedCommand(page, setup.parent_id, stepId, 'reassign_unstarted');
  const reassigned = await bookingEvidence(request, setup.scenario);
  expect(reassigned.row.assignment_epoch).toBe(initial.row.assignment_epoch + 1);
  expect(reassigned.row.assignee_id).toBe('worker-b');
  expect(reassigned.child.work_item.assigned_to).toBe('worker-b');
  expect(reassigned.child.work_item.actual_tokens).toBe(0);
  expect(reassigned.permit).toBeNull();
  expect(reassigned.child.bookings).toHaveLength(2);
  const [cancelled, replacement] = reassigned.child.bookings;
  expect(cancelled).toEqual({ ...initial.child.bookings[0], status: 'cancelled' });
  expect(replacement.id).not.toBe(cancelled.id);
  expect(replacement).toMatchObject({
    resource_id: 'worker-b', status: 'scheduled',
    work_item_id: setup.child_id, requirement_id: cancelled.requirement_id,
    actual_start: null, actual_end: null, total_tokens_consumed: 0,
  });
  expect(reassigned.child.timestamps.map((stamp: any) => stamp.status))
    .toEqual(['scheduled', 'cancelled', 'scheduled']);
  expect(reassigned.child.journals).toEqual([]);
  expect(reassigned.counters).toEqual(initial.counters);
  stale.once('dialog', dialog => dialog.accept('worker-b'));
  await mountedOwnedCommand(stale, setup.parent_id, stepId, 'reassign_unstarted', 409);
  await expect(stale.getByTestId('owned-steps-feedback'))
    .toContainText('owned_steps_row_conflict');
  expect(await bookingEvidence(request, setup.scenario)).toEqual(reassigned);

  const started = await bookingEvidence(request, setup.scenario, 'start');
  expect(started.permit).toMatchObject({
    assignee_id: 'worker-b', booking_id: replacement.id,
    assignment_epoch: reassigned.row.assignment_epoch,
  });
  expect(started.worker_calls[0].thread_id).toBe('');
  const finished = await bookingEvidence(request, setup.scenario, 'finish');
  expect(finished.worker_calls).toHaveLength(1);
  expect(finished.worker_calls[0].agent_id).toBe('worker-b');
  expect(finished.child.work_item.actual_tokens).toBe(7);
  expect(finished.child.work_item.metadata.crew_execution.thread_id).toBe('');
  expect(finished.child.bookings[0]).toEqual(cancelled);
  expect(finished.child.bookings[1]).toMatchObject({
    id: replacement.id, status: 'completed', total_tokens_consumed: 7,
  });
  expect(finished.child.journals.every((entry: any) => entry.booking_id === replacement.id))
    .toBe(true);
  expectExactJournal({
    timestamps: finished.child.timestamps.filter((stamp: any) => stamp.booking_id === replacement.id),
    journals: finished.child.journals,
  }, ['idle', 'working']);
  expect(finished.unrelated).toEqual(initial.unrelated);
  expect(reassigned.unrelated).toEqual(initial.unrelated);
  expect(violations).toEqual([]);
  expect(staleViolations).toEqual([]);
  await stale.close();
});

test('mounted cancel revokes the real running permit and abandon preserves interrupted legacy evidence', async ({
  page,
  request,
}) => {
  const violations = await installPreNavigationGuards(page);
  for (const scenario of ['booking-cancel', 'booking-abandon']) {
    const setup = await setupScenario(request, scenario);
    await mountWorkItem(page, setup.work_item);
    await openWorkItem(page, setup.work_item);
    const initial = await bookingEvidence(request, scenario);
    const stepId = initial.row.step_id;
    if (scenario === 'booking-cancel') {
      await bookingEvidence(request, scenario, 'start');
      await page.getByTestId('owned-refresh').click();
      await mountedOwnedCommand(page, setup.parent_id, stepId, 'pause_accounting');
    } else {
      expect(initial.row.permit_state).toBe('interrupted');
      expect(initial.child.work_item.status).toBe('in_progress');
      expect(initial.child.bookings[0].status).toBe('active');
      await expect(page.getByText(/Managed steps · interrupted/)).toBeVisible();
    }
    const beforeCancel = await bookingEvidence(request, scenario);
    const viewed = await freshOwned(request, setup.parent_id);
    const forgedConfirm = await request.post(
      `/api/work-items/${setup.parent_id}/owned-steps/commands`,
      {
        data: {
          version: 1, reference: viewed.reference,
          commands: [{
            operation_id: `${scenario}-forged-confirm`, step_id: stepId,
            kind: 'manual_confirm',
          }],
        },
      },
    );
    expect(forgedConfirm.status()).toBe(409);
    expect(await forgedConfirm.text()).toContain('owned_steps_hidden_or_unpresented');
    expect(await bookingEvidence(request, scenario)).toEqual(beforeCancel);
    await expect(page.getByTestId(`owned-manual_confirm-${stepId}`)).toHaveCount(0);
    const body = await mountedOwnedCommand(
      page, setup.parent_id, stepId,
      scenario === 'booking-cancel' ? 'cancel_execution' : 'abandon',
    );
    const cancelled = await bookingEvidence(request, scenario);
    expect(cancelled.row.permit_state).toBe('revoked');
    expect(cancelled.row.assignment_epoch).toBe(beforeCancel.row.assignment_epoch + 1);
    expect(cancelled.row.reviewed_result).toBeNull();
    expect(cancelled.child.work_item).toMatchObject({
      status: 'cancelled', actual_tokens: 0, verification: {},
    });
    expect(cancelled.child.bookings).toEqual([
      { ...beforeCancel.child.bookings[0], status: 'cancelled' },
    ]);
    expect(cancelled.child.timestamps.slice(0, -1)).toEqual(beforeCancel.child.timestamps);
    expect(cancelled.child.timestamps.at(-1)).toMatchObject({
      status: 'cancelled', source: 'system',
    });
    expect(cancelled.child.journals).toEqual([]);
    expect(cancelled.permit).toEqual(beforeCancel.permit);
    expect(cancelled.unrelated).toEqual(initial.unrelated);
    expect(cancelled.counters).toEqual(beforeCancel.counters);
    const duplicate = await request.post(
      `/api/work-items/${setup.parent_id}/owned-steps/commands`, { data: body },
    );
    expect(duplicate.ok(), await duplicate.text()).toBeTruthy();
    expect(await bookingEvidence(request, scenario)).toEqual(cancelled);
    if (scenario === 'booking-cancel') {
      const late = await bookingEvidence(request, scenario, 'finish');
      expect(late.execution).toEqual({ error: 'owned_steps_execution_revoked' });
      expect(late.child).toEqual(cancelled.child);
      expect(late.row).toEqual(cancelled.row);
      expect(late.events).toEqual(cancelled.events);
      expect(late.counters).toEqual(cancelled.counters);
      expect(late.unrelated).toEqual(initial.unrelated);
    } else {
      expect(cancelled.worker_calls).toEqual([]);
      expect(cancelled.permit).toBeNull();
    }
  }
  expect(violations).toEqual([]);
});

test('legacy NO-ROOM two-worker run resumes exact submissions then restarts manual-gate finalize-only without effects', async ({
  page,
  request,
}) => {
  const violations = await installPreNavigationGuards(page);
  const setup = await setupScenario(request, 'legacy-no-room');
  expect(setup.thread_id).toBe('');
  expect(setup.child_ids).toHaveLength(2);
  expect(setup.worker_ids).toHaveLength(2);
  const originalPrefix = setup.work_item.steps;
  const before = await (await request.get('/__ad1192__/no-room')).json();
  expect(before.control).toMatchObject({
    owner_kind: 'legacy', thread_id: '', facilitator_id: null,
    mode: 'awaiting_adoption', manual_prefix_length: 1,
  });
  expect(before.work_item.assigned_to).toBe('crew_orchestrator');
  expect(before.rooms).toEqual([]);
  expect(before.worker_calls).toEqual([]);
  expect(before.canonical_session).toBeNull();
  const oldWire = await (await request.get(
    `/api/work-items/${setup.parent_id}/steps`,
  )).json();
  expect(oldWire).toEqual({ steps: originalPrefix, gate_completion: true });
  expect(Object.keys(oldWire.steps[0]).sort()).toEqual([
    'label', 'status', 'assigned_to', 'submitted_by', 'confirmed_by', 'note',
  ].sort());
  const workItemKeys = [
    'id', 'title', 'description', 'work_type', 'status', 'priority', 'parent_id',
    'project_id', 'depends_on', 'assigned_to', 'created_by', 'created_at',
    'updated_at', 'due_at', 'estimated_tokens', 'actual_tokens', 'trust_requirement',
    'required_capabilities', 'tags', 'metadata', 'steps', 'verification',
    'schedule', 'ttl_seconds', 'template_id',
  ].sort();
  expect(Object.keys(setup.work_item).sort()).toEqual(workItemKeys);

  await mountWorkItem(page, setup.work_item);
  await openWorkItem(page, setup.work_item);
  await adoptThroughMountedUi(page);
  const adopted = await freshOwned(request, setup.parent_id);
  const manual = adopted.rows.find((row: any) => row.kind === 'manual');
  expect(manual.todo).toEqual(oldWire.steps[0]);
  for (const child of adopted.rows.filter((row: any) => row.kind === 'child')) {
    await expect(page.getByTestId(`owned-child-verdict-${child.step_id}`))
      .toContainText('Independent verdict');
    await expect(page.getByTestId(`owned-manual_confirm-${child.step_id}`)).toHaveCount(0);
  }
  const runResponse = await request.post('/__ad1192__/no-room/run');
  expect(runResponse.ok(), await runResponse.text()).toBeTruthy();
  const run = await runResponse.json();
  const executed = run.evidence;
  expect(executed.restarts).toBe(1);
  expect(executed.results).toHaveLength(2);
  expect(executed.resumed).toEqual(executed.results);
  expect(executed.worker_calls.map((call: any) => call.agent_id)).toEqual(setup.worker_ids);
  expect(executed.worker_calls.map((call: any) => call.thread_id)).toEqual(['', '']);
  expect(executed.counters.worker - run.before.worker).toBe(2);
  for (const kind of ['verifier_model', 'synthesis_model', 'planner', 'ingress_planner', 'episodes']) {
    expect(executed.counters[kind]).toBe(run.before[kind]);
  }
  expect(executed.work_item.steps.slice(0, 1)).toEqual(originalPrefix);
  expect(executed.submissions).toHaveLength(2);
  expect(executed.reviews).toEqual([]);
  const resultKeys = [
    'work_item_id', 'spec_id', 'agent_id', 'output', 'status', 'tool_trace_ref',
    'started_at', 'finished_at', 'stopped_reason', 'actual_tokens',
    'artifact_refs', 'blocked_dependency_ids',
  ].sort();
  const executionKeys = [
    'version', 'parent_id', 'work_item_id', 'thread_id', 'assigned_to', 'status',
    'stopped_reason', 'output_summary', 'tool_trace_ref', 'artifact_refs',
    'tokens_used', 'started_at', 'finished_at', 'blocked_dependency_ids',
  ].sort();
  for (let index = 0; index < 2; index += 1) {
    const result = executed.results[index];
    const child = executed.children[index].work_item;
    expect(Object.keys(result).sort()).toEqual(resultKeys);
    expect(Object.keys(child).sort()).toEqual(workItemKeys);
    expect(result).toMatchObject({
      agent_id: setup.worker_ids![index], work_item_id: setup.child_ids![index],
      output: `legacy-result-${setup.worker_ids![index]}`,
      status: 'done', actual_tokens: 7, artifact_refs: [],
    });
    const execution = child.metadata.crew_execution;
    expect(Object.keys(execution).sort()).toEqual(executionKeys);
    expect(execution.thread_id).toBe('');
    expect(execution.tokens_used).toBe(7);
    expect(child.actual_tokens).toBe(7);
    expect(child.verification).toEqual({});
    expect(JSON.parse(executed.submissions[index].execution_json)).toEqual(execution);
  }

  const primeResponse = await request.post('/__ad1192__/no-room/prime');
  expect(primeResponse.ok(), await primeResponse.text()).toBeTruthy();
  const primed = await primeResponse.json();
  const waiting = primed.evidence;
  expect(primed.result).toMatchObject({
    completed: false, disposition: 'pending', accepted_count: 2, total_count: 2,
    final_output: 'actual-legacy-final-result',
  });
  expect(waiting.counters.worker).toBe(executed.counters.worker);
  expect(waiting.counters.verifier_model - executed.counters.verifier_model).toBe(2);
  expect(waiting.counters.synthesis_model - executed.counters.synthesis_model).toBe(1);
  expect(waiting.counters.episodes - executed.counters.episodes).toBe(1);
  expect(waiting.counters.completion_events.slice(-1)).toEqual([
    expect.objectContaining({
      parent_id: setup.parent_id, completed: false, accepted_count: 2, total_count: 2,
    }),
  ]);
  expect(waiting.control.mode).toBe('waiting_manual_gate');
  expect(waiting.control.finalization.thread_id).toBe('');
  expect(waiting.manifest.thread_id).toBe('');
  expect(waiting.manifest.producer_ids).toEqual(setup.worker_ids);
  expect(waiting.output).toBe('actual-legacy-final-result');
  expect(waiting.reviews).toHaveLength(2);
  expect(waiting.reviews.every((review: any) => review.accepted)).toBe(true);
  expect(waiting.effects.map((effect: any) => effect.kind).sort()).toEqual([
    'producer_trust', 'producer_trust', 'collaboration_episode', 'crew_task_completed',
  ].sort());
  expect(waiting.effects.every((effect: any) => effect.disposition === 'attempted_unknown'))
    .toBe(true);
  expect(waiting.recovery_guard).toEqual({
    enabled: true, forbidden_attempts: [],
    worker: true, verifier: true, synthesis: true, planners: true,
  });
  const beforeRecovery = await (await request.get('/__ad1192__/state')).json();
  for (const producer of setup.worker_ids!) {
    expect(beforeRecovery.trust[producer]).toEqual({ alpha: 3, beta: 2 });
  }
  const restartResponse = await request.post('/__ad1192__/no-room/recover');
  expect(restartResponse.ok(), await restartResponse.text()).toBeTruthy();
  const recovered = await restartResponse.json();
  expect(recovered.result).toEqual(primed.result);
  expect(recovered.evidence).toEqual({ ...waiting, restarts: 2 });
  await page.getByTestId('owned-refresh').click();
  await expect(page.getByText(/Managed steps · waiting_manual_gate/)).toBeVisible();
  await page.getByTestId('owned-finalize').click();
  await expect(page.getByTestId('owned-steps-feedback')).toContainText('Finalize-only result: pending.');
  expect(await (await request.get('/__ad1192__/no-room')).json()).toEqual(recovered.evidence);

  await mountedOwnedCommand(page, setup.parent_id, manual.step_id, 'manual_submit');
  await mountedOwnedCommand(page, setup.parent_id, manual.step_id, 'manual_confirm');
  const closedResponse = await request.get('/__ad1192__/await/legacy-no-room');
  expect(closedResponse.ok(), await closedResponse.text()).toBeTruthy();
  const closed = await closedResponse.json();
  expect(closed.completed).toBe(true);
  expect(closed.final_output).toBe('actual-legacy-final-result');
  expect(closed.counters).toEqual(waiting.counters);
  const final = await (await request.get('/__ad1192__/no-room')).json();
  expect(final.control.mode).toBe('completed');
  expect(final.control.finalization).toEqual(waiting.control.finalization);
  expect(final.children).toEqual(waiting.children);
  expect(final.effects).toEqual(waiting.effects);
  expect(final.manifest).toEqual(waiting.manifest);
  expect(final.recovery_guard).toEqual(waiting.recovery_guard);
  for (const state of [before, executed, waiting, recovered.evidence, final]) {
    expect(state.rooms).toEqual([]);
    expect(state.control.thread_id).toBe('');
    expect(state.control.facilitator_id).toBeNull();
    expect(state.canonical_session).toBeNull();
    expect(state.work_item.assigned_to).toBe('crew_orchestrator');
    expect(state.work_item.metadata.crew_session).toBeUndefined();
    expect(state.artifacts).toEqual({ count: 0, latest: [], versions: [] });
  }
  const afterClose = await (await request.get('/__ad1192__/state')).json();
  expect(afterClose.trust).toEqual(beforeRecovery.trust);
  expect(afterClose.episode_ids).toEqual(beforeRecovery.episode_ids);
  await page.getByTestId('owned-refresh').click();
  await expect(page.getByText(/Managed steps · completed/)).toBeVisible();
  const completedView = await freshOwned(request, setup.parent_id);
  for (let retry = 0; retry < 2; retry += 1) {
    const response = await request.post(
      `/api/work-items/${setup.parent_id}/owned-steps/finalize`,
      { data: { version: 1, reference: completedView.reference } },
    );
    expect(response.ok(), await response.text()).toBeTruthy();
    expect(await response.json()).toEqual({ disposition: 'completed' });
  }
  expect(await (await request.get('/__ad1192__/no-room')).json()).toEqual(final);
  const afterRetry = await (await request.get('/__ad1192__/state')).json();
  for (const key of ['counters', 'trust', 'episode_ids', 'events', 'artifacts']) {
    expect(afterRetry[key]).toEqual(afterClose[key]);
  }
  expect(violations).toEqual([]);
});

test('all six owned endpoints authenticate before bodies and reject spoof authority fields', async ({
  request,
}) => {
  const setup = await setupScenario(request, 'legacy');
  expect((await request.post('/__ad1192__/auth', {
    data: { token: 'ad1192-isolated-token' },
  })).ok()).toBeTruthy();
  for (const path of [
    `/api/work-items/${setup.parent_id}/owned-steps`,
    `/api/work-items/${setup.parent_id}/owned-steps/repair`,
  ]) {
    const denied = await request.get(path);
    expect(denied.status()).toBe(401);
    expect(await denied.text()).toContain('missing_or_malformed_authorization');
  }
  for (const suffix of ['preview', 'adopt', 'commands', 'finalize']) {
    const denied = await request.post(
      `/api/work-items/${setup.parent_id}/owned-steps/${suffix}`,
      {
        data: '{malformed',
        headers: { 'Content-Type': 'application/json' },
      },
    );
    expect(denied.status()).toBe(401);
    const body = await denied.text();
    expect(body).toContain('missing_or_malformed_authorization');
    expect(body).not.toContain('ad1192-isolated-token');
  }
  const spoofed = await request.post(
    `/api/work-items/${setup.parent_id}/owned-steps/commands`,
    {
      headers: {
        Authorization: 'Bearer ad1192-isolated-token',
        'Content-Type': 'application/json',
      },
      data: {
        version: 1,
        actor: 'captain',
        role: 'captain',
        reference: {},
        commands: [],
      },
    },
  );
  expect(spoofed.status()).toBe(422);
});
