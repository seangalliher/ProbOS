import { expect, test, type Locator, type WebSocketRoute } from '@playwright/test';

import notificationFixture from './fixtures/notification-navigation.json' with { type: 'json' };

import {
  CREW,
  EZRI,
  mkAgent,
  mkMessage,
  mkThread,
  mockChatApi,
  gotoApp,
  openGroupChat,
  seedAgents,
  type MockChatApiOptions,
} from './_helpers';

const GENERATION_A = 'a'.repeat(32);
const GENERATION_B = 'b'.repeat(32);
const SHA_A = 'a'.repeat(64);
const SHA_B = 'b'.repeat(64);

type SessionState =
  | 'discussing'
  | 'executing'
  | 'verifying'
  | 'blocked_needs_captain'
  | 'done'
  | 'failed';

function session(state: SessionState, revision: number, done: number) {
  const terminal = state === 'done';
  return {
    task_id: 'parent-1',
    thread_id: 'thread-1',
    goal: 'Prepare the live navigation report',
    origin: 'captain',
    originator_id: 'captain',
    facilitator_id: 'ezri',
    owner_ids: ['ezri', 'yeo'],
    state,
    revision,
    success_criteria: ['Complete', 'Verified'],
    expected_deliverable: 'A verified report',
    timestamps: {
      created_at: 1,
      transitioned_at: revision,
      started_at: state === 'discussing' ? null : 2,
      first_result_at: state === 'verifying' || terminal ? 3 : null,
      verified_at: terminal ? 5 : null,
      completed_at: terminal ? 5 : null,
    },
    progress: {
      total: 2,
      done,
      failed: 0,
      active: 2 - done,
      active_child: done === 2 ? null : {
        id: `child-${done + 1}`,
        title: done === 0 ? 'Research evidence' : 'Verify report',
        status: state === 'verifying' ? 'review' : 'in_progress',
        owner_id: done === 0 ? 'yeo' : 'ezri',
      },
    },
    last_result_summary: done > 0 ? 'Draft report is ready.' : '',
    blocker: null,
    result: terminal ? {
      artifact_id: 'artifact-1',
      content_hash: SHA_B,
      result_ref: SHA_A,
      evidence_refs: [SHA_A],
    } : null,
    verification: terminal ? {
      verifier_agent_id: 'ezri',
      confidence: 0.94,
      critique: 'All criteria are satisfied.',
      accepted_count: 2,
      total_count: 2,
      convergence_rounds: 1,
    } : null,
    duplicate_resume_count: 0,
  };
}

function summary(detail: ReturnType<typeof session>) {
  return {
    task_id: detail.task_id,
    thread_id: detail.thread_id,
    goal: detail.goal,
    state: detail.state,
    facilitator_id: detail.facilitator_id,
    owner_ids: detail.owner_ids,
    progress: {
      total: detail.progress.total,
      done: detail.progress.done,
      failed: detail.progress.failed,
      active: detail.progress.active,
    },
    last_result_summary: detail.last_result_summary,
    blocker: null,
    needs_attention: false,
    result_artifact_id: detail.result?.artifact_id ?? null,
    verified_at: detail.timestamps.verified_at,
  };
}

function projection(detail: ReturnType<typeof session>, outputs: number, stepsDone: number) {
  return {
    parent_id: detail.task_id,
    thread_id: detail.thread_id,
    revision: detail.revision,
    session: detail,
    room_summary: {
      outputs,
      steps_total: 2,
      steps_done: stepsDone,
      topic: detail.goal,
      session: summary(detail),
    },
  };
}

function frame(
  type: string,
  data: Record<string, unknown>,
  generation: string,
  sequence: number,
) {
  return JSON.stringify({
    type,
    data,
    timestamp: sequence + 1,
    stream: { generation, sequence },
  });
}

function snapshot(generation: string, agents = CREW, notifications: Record<string, unknown>[] = []) {
  return frame('state_snapshot', {
    agents: agents.map(agent => ({
      id: agent.id,
      agent_type: agent.agentType,
      callsign: agent.callsign,
      display_name: agent.displayName,
      pool: agent.pool,
      state: agent.state,
      confidence: agent.confidence,
      trust: agent.trust,
      tier: agent.tier,
      isCrew: true,
    })),
    connections: [],
    pools: [],
    system_mode: 'active',
    tc_n: 0,
    routing_entropy: 0,
    notifications,
  }, generation, 0);
}

for (const viewport of [{ width: 1440, height: 1000 }, { width: 900, height: 1000 }]) {
  for (const activation of ['pointer', 'Enter', 'Space'] as const) {
    test(`checked failure notification navigation ${activation} at ${viewport.width}px`, async ({ page }, testInfo) => {
      test.setTimeout(90000);
      await page.setViewportSize(viewport);
      const { context, event, rooms, summaries, messages } = notificationFixture;
      const sourceRoom = mkThread('synthetic-draft-source', 'Unsent draft room', ['ezri', 'yeo']);
      const agents = [...CREW, ...context.thread.participants.map(id => mkAgent(id, id, 'operations'))];
      const sockets: WebSocketRoute[] = [];
      const mutations: string[] = [];
      const contextRequests: string[] = [];
      let sequence = 0;
      const acknowledged = { ...event.data.notification, acknowledged: true };
      const syntheticHistory = Array.from({ length: 51 }, (_, index) => ({
        ...event.data.notification, id: `synthetic-history-${index}`, title: `Synthetic history ${index}`,
      }));
      const retained = syntheticHistory.slice(-50).map(item => ({ ...item, acknowledged: true }));
      await page.addInitScript(({ width, height }) => {
        localStorage.setItem('hxi_profile_panel_size', JSON.stringify({ w: Math.min(1060, width - 80), h: height - 120 }));
        localStorage.setItem('probos.workspaceFiles.collapsed', width < 1000 ? '1' : '0');
      }, viewport);
      page.on('request', request => {
        const path = new URL(request.url()).pathname;
        if (path.startsWith('/api/') && !['GET', 'HEAD'].includes(request.method())) {
          mutations.push(`${request.method()} ${path}`);
        }
      });
      await mockChatApi(page, {
        threads: [...rooms.threads, sourceRoom],
        messagesByThread: { [messages.thread_id]: messages.messages, [sourceRoom.id]: [] },
        roomSummaries: summaries.summaries,
        crewDetailsByParent: { [context.session.task_id]: context.session },
      });
      await page.route(`**/api/threads/${context.thread.id}`, route => route.fulfill({ json: context.thread }));
      await page.route(`**/api/threads/${sourceRoom.id}`, route => route.fulfill({ json: sourceRoom }));
      await page.route('**/api/chat/attachments/multipart', route => route.fulfill({ json: {
        attachment_id: SHA_A, url: '/attachment', sha256: SHA_A, mime: 'text/plain', size_bytes: 5,
      } }));
      await page.route('**/api/notifications/**', async route => {
        const request = route.request();
        const path = new URL(request.url()).pathname;
        if (request.method() === 'GET' && path === `/api/notifications/${context.notification_id}/context`) {
          contextRequests.push(path);
          return route.fulfill({ json: context, headers: { 'Cache-Control': 'no-store' } });
        }
        if (request.method() === 'POST' && path === `/api/notifications/${context.notification_id}/ack`) {
          sockets[0].send(frame('notification_ack', { notifications: [acknowledged], unread_count: 0 }, GENERATION_A, ++sequence));
          return route.fulfill({ json: { ok: true } });
        }
        if (request.method() === 'POST' && path === '/api/notifications/ack-all') {
          sockets[0].send(frame('notification_ack', { notifications: retained, unread_count: 0 }, GENERATION_A, ++sequence));
          return route.fulfill({ json: { ok: true } });
        }
        return route.abort();
      });
      await page.routeWebSocket('**/ws/events*', socket => { sockets.push(socket); });
      await gotoApp(page);
      await expect.poll(() => sockets.length).toBe(1);
      sockets[0].send(snapshot(GENERATION_A, agents));
      await expect.poll(() => page.evaluate(() => (window as unknown as {
        __store: { getState: () => { liveGeneration: string | null } };
      }).__store.getState().liveGeneration)).toBe(GENERATION_A);
      await seedAgents(page, agents);

      await openGroupChat(page, EZRI.id, sourceRoom);
      const composer = page.getByPlaceholder('Message...', { exact: true });
      await composer.fill('Unsent source-room text');
      await composer.locator('..').locator('input[type="file"]').setInputFiles({
        name: 'draft.txt', mimeType: 'text/plain', buffer: Buffer.from('draft'),
      });
      await expect(page.getByText('draft.txt', { exact: true })).toBeVisible();
      await page.getByTitle('Close', { exact: true }).click();
      await expect(composer).toHaveCount(0);

      const failureFrame = frame(event.type, event.data, GENERATION_A, ++sequence);
      sockets[0].send(failureFrame);
      const bridge = page.getByRole('button', { name: /^BRIDGE(?: \(\d+\))?$/ });
      await expect(bridge).toHaveText('BRIDGE (1)');
      await expect(bridge).toBeVisible();
      sockets[0].send(failureFrame);
      sockets[0].send(frame(event.type, event.data, GENERATION_A, ++sequence));
      await expect(bridge).toHaveText('BRIDGE (1)');
      await page.screenshot({ path: testInfo.outputPath('unread-badge.png') });
      await bridge.click();
      const openContext = page.getByRole('button', { name: `Open room context: ${event.data.notification.title}`, exact: true });
      await expect(openContext).toHaveCount(1);
      await expect(openContext).toBeVisible();
      const activate = async (button: Locator): Promise<void> => {
        if (activation === 'pointer') await button.click();
        else {
          await button.focus();
          await expect(button).toBeFocused();
          await button.press(activation);
        }
      };
      const closeBridge = async (): Promise<void> => {
        const beforeMutations = [...mutations];
        const beforeRequests = [...contextRequests];
        const profileThread = await page.evaluate(() => (window as unknown as {
          __store: { getState: () => { activeProfileThreadId: string | null } };
        }).__store.getState().activeProfileThreadId);
        await page.getByRole('button', { name: 'Close Bridge', exact: true }).click();
        await expect.poll(() => page.evaluate(() => (window as unknown as {
          __store: { getState: () => { bridgeOpen: boolean } };
        }).__store.getState().bridgeOpen)).toBe(false);
        await expect(bridge).toHaveCSS('opacity', '1');
        expect(mutations).toEqual(beforeMutations);
        expect(contextRequests).toEqual(beforeRequests);
        expect(await page.evaluate(() => (window as unknown as {
          __store: { getState: () => { activeProfileThreadId: string | null } };
        }).__store.getState().activeProfileThreadId)).toBe(profileThread);
      };
      const expectProfileBounds = async (): Promise<void> => {
        const geometry = await page.getByTitle('Close', { exact: true }).evaluate(button => {
          let panel = button.parentElement;
          while (panel && getComputedStyle(panel).position !== 'fixed') panel = panel.parentElement;
          if (!panel) throw new Error('Profile close control has no fixed outer panel');
          const closeBounds = button.getBoundingClientRect();
          return {
            panel: panel.getBoundingClientRect().toJSON(),
            close: closeBounds.toJSON(),
            unobstructed: [
              [closeBounds.left + 1, closeBounds.top + 1],
              [closeBounds.right - 1, closeBounds.top + 1],
              [closeBounds.left + 1, closeBounds.bottom - 1],
              [closeBounds.right - 1, closeBounds.bottom - 1],
              [closeBounds.left + closeBounds.width / 2, closeBounds.top + closeBounds.height / 2],
            ].every(([horizontal, vertical]) => button.contains(document.elementFromPoint(horizontal, vertical))),
          };
        });
        expect(geometry.unobstructed, 'Profile close must remain reachable while Bridge is open').toBe(true);
        for (const bounds of [geometry.panel, geometry.close]) {
          expect(bounds.width).toBeGreaterThan(0);
          expect(bounds.height).toBeGreaterThan(0);
          expect(bounds.left).toBeGreaterThanOrEqual(0);
          expect(bounds.top).toBeGreaterThanOrEqual(0);
          expect(bounds.right).toBeLessThanOrEqual(viewport.width);
          expect(bounds.bottom).toBeLessThanOrEqual(viewport.height);
        }
      };
      await activate(openContext);
      const band = page.getByTestId('crew-collaboration-panel');
      await expect(band).toHaveAttribute('data-state', 'failed');
      await expect(band).toBeFocused();
      await expect(band.getByRole('heading', { name: context.session.goal, exact: true })).toBeVisible();
      await expect(band.getByText(context.session.last_result_summary, { exact: true })).toBeVisible();
      await expect(page.getByRole('status').filter({ hasText: 'Notification room context opened. Showing current session state.' })).toBeVisible();
      const destination = await page.evaluate(() => {
        const state = (window as unknown as { __store: { getState: () => {
          activeProfileThreadId: string | null; activeProfileAgent: string | null;
          threadIdByAgent: Map<string, string>;
          crewSessionsByParent: Map<string, { task_id: string; thread_id: string; state: string }>;
        } } }).__store.getState();
        return {
          thread: state.activeProfileThreadId, host: state.activeProfileAgent,
          defaults: [...state.threadIdByAgent], sessions: [...state.crewSessionsByParent.values()],
        };
      });
      expect(destination.thread).toBe(context.thread.id);
      expect(context.thread.participants).toContain(destination.host);
      expect(destination.defaults).toEqual([]);
      expect(destination.sessions).toContainEqual(context.session);
      expect(contextRequests).toHaveLength(1);
      expect(mutations).toEqual(['POST /api/chat/attachments/multipart']);
      await expect(composer).toHaveValue('');
      await expect(page.getByText('draft.txt', { exact: true })).toHaveCount(0);
      await expect(page.getByTestId('chat-transcript')).not.toContainText(context.session.last_result_summary);
      await expectProfileBounds();
      expect(await page.evaluate(() => (window as unknown as {
        __store: { getState: () => { bridgeOpen: boolean } };
      }).__store.getState().bridgeOpen)).toBe(true);
      await composer.fill('Unsent destination-room text');
      await page.screenshot({ path: testInfo.outputPath('bridge-and-failure-context.png') });
      await page.getByTitle('Close', { exact: true }).click();
      await expect(band).toHaveCount(0);
      await expect(composer).toHaveCount(0);
      expect(await page.evaluate(() => {
        const state = (window as unknown as { __store: { getState: () => {
          bridgeOpen: boolean; activeProfileThreadId: string | null;
        } } }).__store.getState();
        return { bridge: state.bridgeOpen, thread: state.activeProfileThreadId };
      })).toEqual({ bridge: true, thread: null });
      await expect(page.getByRole('button', { name: 'Close Bridge', exact: true })).toBeVisible();
      expect(contextRequests).toHaveLength(1);
      expect(mutations).toEqual(['POST /api/chat/attachments/multipart']);
      await openGroupChat(page, EZRI.id, sourceRoom);
      await expect(composer).toHaveValue('Unsent source-room text');
      await expect(page.getByText('draft.txt', { exact: true })).toBeVisible();
      await page.getByTitle('Close', { exact: true }).click();
      await activate(openContext);
      await expect(band).toBeFocused();
      await expect(band).toHaveAttribute('data-state', 'failed');
      await expect(composer).toHaveValue('Unsent destination-room text');
      await expect(page.getByText('draft.txt', { exact: true })).toHaveCount(0);
      expect(contextRequests).toHaveLength(2);
      expect(mutations).toEqual(['POST /api/chat/attachments/multipart']);
      const profileTop = await page.getByTitle('Close', { exact: true }).evaluate(button => {
        let panel = button.parentElement;
        while (panel && getComputedStyle(panel).position !== 'fixed') panel = panel.parentElement;
        if (!panel) throw new Error('Profile close control has no fixed outer panel');
        return panel.getBoundingClientRect().top;
      });
      const bridgeCloseBounds = await page.getByRole('button', { name: 'Close Bridge', exact: true }).boundingBox();
      expect(bridgeCloseBounds).not.toBeNull();
      expect(bridgeCloseBounds!.y + bridgeCloseBounds!.height).toBeLessThanOrEqual(profileTop);
      await closeBridge();
      await expectProfileBounds();
      await expect.poll(() => page.getByTitle('Close', { exact: true }).evaluate(button => {
        const bounds = button.getBoundingClientRect();
        return [
          [bounds.left + 1, bounds.top + 1],
          [bounds.right - 1, bounds.top + 1],
          [bounds.left + 1, bounds.bottom - 1],
          [bounds.right - 1, bounds.bottom - 1],
          [bounds.left + bounds.width / 2, bounds.top + bounds.height / 2],
        ].every(([horizontal, vertical]) => button.contains(document.elementFromPoint(horizontal, vertical)));
      })).toBe(true);

      const fit = await band.evaluate(element => {
        const bounds = element.getBoundingClientRect();
        const grid = element.querySelector('.crew-session-grid')!;
        const sections = [...grid.children].map(child => child.getBoundingClientRect());
        return {
          left: bounds.left, right: bounds.right, top: bounds.top, bottom: bounds.bottom,
          fits: [...element.querySelectorAll<HTMLElement>('h3, .crew-session-section')]
            .every(child => child.scrollWidth <= child.clientWidth + 1),
          separate: sections[0].right <= sections[1].left + 1 || sections[0].bottom <= sections[1].top + 1,
        };
      });
      expect(fit.left).toBeGreaterThanOrEqual(0);
      expect(fit.right).toBeLessThanOrEqual(viewport.width);
      expect(fit.top).toBeGreaterThanOrEqual(0);
      expect(fit.bottom).toBeLessThanOrEqual(viewport.height);
      expect(fit.fits).toBe(true);
      expect(fit.separate).toBe(true);
      const bandBox = await band.boundingBox();
      const composerBox = await composer.boundingBox();
      expect(bandBox).not.toBeNull();
      expect(composerBox).not.toBeNull();
      expect(bandBox!.y + bandBox!.height).toBeLessThanOrEqual(composerBox!.y + 1);
      await page.screenshot({ path: testInfo.outputPath('failure-context.png') });

      await composer.fill('Unsent destination-room text');
      await page.getByTitle('Close', { exact: true }).click();
      await expect(band).toHaveCount(0);
      await expect(composer).toHaveCount(0);
      await openGroupChat(page, EZRI.id, sourceRoom);
      await expect(composer).toHaveValue('Unsent source-room text');
      await expect(page.getByText('draft.txt', { exact: true })).toBeVisible();
      await page.getByTitle('Close', { exact: true }).click();
      await bridge.click();
      await page.getByRole('button', { name: 'Mark read', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Mark read', exact: true })).toHaveCount(0);
      await expect(bridge).toHaveText('BRIDGE');
      await expect(openContext).toBeEnabled();
      await activate(openContext);
      await expect(band).toBeFocused();
      await expect(band).toHaveAttribute('data-state', 'failed');
      await expect(composer).toHaveValue('Unsent destination-room text');
      expect(contextRequests).toHaveLength(3);
      await closeBridge();
      await page.getByTitle('Close', { exact: true }).click();

      await test.step('synthetic acknowledgement history prunes the checked card, not its failed room', async () => {
        sockets[0].send(frame('notification_snapshot', {
          notifications: [acknowledged, ...syntheticHistory], unread_count: syntheticHistory.length,
        }, GENERATION_A, ++sequence));
        await expect(bridge).toHaveText('BRIDGE (51)');
        await bridge.click();
        await closeBridge();
        await expect(bridge).toHaveText('BRIDGE (51)');
        await bridge.click();
        await activate(openContext);
        await expect(band).toBeFocused();
        await expect(composer).toHaveValue('Unsent destination-room text');
        await expectProfileBounds();
        expect(contextRequests).toHaveLength(4);
        const markAllBounds = await page.getByRole('button', { name: 'Mark all read', exact: true }).boundingBox();
        expect(markAllBounds).not.toBeNull();
        expect(markAllBounds!.y + markAllBounds!.height).toBeLessThanOrEqual(profileTop);
        await page.getByRole('button', { name: 'Mark all read', exact: true }).click();
        await expect.poll(() => mutations.filter(path => path === 'POST /api/notifications/ack-all').length).toBe(1);
        await expect(openContext).toHaveCount(0);
        await expect(bridge).toHaveText('BRIDGE');
        await expect(band).toHaveAttribute('data-state', 'failed');
        await expect(composer).toHaveValue('Unsent destination-room text');
        expect(await page.evaluate(() => (window as unknown as {
          __store: { getState: () => { activeProfileThreadId: string | null } };
        }).__store.getState().activeProfileThreadId)).toBe(context.thread.id);
        await closeBridge();
        await page.getByTitle('Close', { exact: true }).click();
        await bridge.click();
        sockets[0].send(failureFrame);
        await expect(openContext).toHaveCount(0);
        await sockets[0].close({ code: 1012, reason: 'notification reconnect test' });
        await expect.poll(() => sockets.length, { timeout: 5000 }).toBe(2);
        sockets[1].send(snapshot(GENERATION_B, agents, retained));
        await expect.poll(() => page.evaluate(() => (window as unknown as {
          __store: { getState: () => { liveGeneration: string | null } };
        }).__store.getState().liveGeneration)).toBe(GENERATION_B);
        sockets[1].send(frame(event.type, event.data, GENERATION_A, sequence + 1));
        sockets[1].send(frame('notification_snapshot', { notifications: retained, unread_count: 0 }, GENERATION_B, 1));
        await expect.poll(() => page.evaluate(() => (window as unknown as {
          __store: { getState: () => { liveSequence: number } };
        }).__store.getState().liveSequence)).toBe(1);
        await expect(openContext).toHaveCount(0);
        await expect(page.getByRole('button', { name: /^Open room context: Synthetic history / })).toHaveCount(50);
        await closeBridge();
        await page.getByTestId('crew-collab-pill').click();
        const row = page.getByTestId(`chat-row-${context.thread.id}`);
        await expect(row).toBeVisible();
        await expect(row).toContainText(context.session.goal);
        await expect(row).toContainText('failed');
        await expect(row).toContainText(context.session.last_result_summary);
        await page.screenshot({ path: testInfo.outputPath('pruned-failed-room.png') });
        await row.click();
        await expect(band).toHaveAttribute('data-state', 'failed');
        await expect(band.getByRole('heading')).toHaveText(context.session.goal);
      });
      expect(mutations).toEqual([
        'POST /api/chat/attachments/multipart',
        `POST /api/notifications/${context.notification_id}/ack`,
        'POST /api/notifications/ack-all',
      ]);
    });
  }
}

test('live CrewSession room refreshes and repairs through the sole stream', async ({ page }) => {
  const room = mkThread('thread-1', 'Navigation room', ['ezri', 'yeo'], {
    task_id: 'parent-1',
  });
  const executing = session('executing', 2, 0);
  const options: MockChatApiOptions = {
    threads: [room],
    messagesByThread: {
      'thread-1': [mkMessage('captain-1', 'thread-1', 'captain', 'captain', 'Begin work.', 1)],
    },
    crewDetailsByParent: { 'parent-1': executing },
    roomSummaries: {
      'thread-1': {
        outputs: 0, steps_total: 2, steps_done: 0,
        topic: executing.goal, session: summary(executing),
      },
    },
    stepsByParent: {
      'parent-1': [
        { label: 'Research evidence', status: 'in_progress' },
        { label: 'Verify report', status: 'pending' },
      ],
    },
    artifactsByThread: { 'thread-1': [] },
  };
  const sockets: WebSocketRoute[] = [];
  const apiRequests: string[] = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) apiRequests.push(url.pathname);
  });
  await page.addInitScript(() => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
  });
  await mockChatApi(page, options);
  await page.routeWebSocket('**/ws/events*', socket => {
    sockets.push(socket);
  });
  await gotoApp(page);
  await expect.poll(() => sockets.length).toBe(1);
  sockets[0].send(snapshot(GENERATION_A));
  await seedAgents(page, CREW);
  await openGroupChat(page, EZRI.id, room);

  const panel = page.getByTestId('crew-collaboration-panel');
  const rail = page.getByTestId('workspace-files-rail');
  await expect(panel).toBeVisible();
  await expect(rail).toHaveAttribute('data-collapsed', 'false');
  await expect(page.getByTestId('chats-panel')).toHaveCount(0);
  const panelBox = await panel.boundingBox();
  const railBox = await rail.boundingBox();
  expect(panelBox).not.toBeNull();
  expect(railBox).not.toBeNull();
  expect((panelBox?.x ?? 0) + (panelBox?.width ?? 0)).toBeLessThanOrEqual((railBox?.x ?? 0) + 1);

  sockets[0].send(frame(
    'crew_session_projection',
    projection(executing, 0, 0),
    GENERATION_A,
    1,
  ));
  await expect(panel).toHaveAttribute('data-state', 'executing');

  options.messagesByThread!['thread-1'].push(
    mkMessage('message-1', 'thread-1', 'yeo', 'agent', 'Live research result.', 3),
  );
  sockets[0].send(frame('chat_thread_message_appended', {
    thread_id: 'thread-1', message_id: 'message-1', author_id: 'yeo',
    role: 'agent', created_at: 3,
  }, GENERATION_A, 2));
  await expect(page.getByText('Live research result.')).toBeVisible();

  const artifactOne = {
    id: 'artifact-1', thread_id: 'thread-1', name: 'navigation-report.md',
    version: 1, content_hash: SHA_B, mime: 'text/markdown', size_bytes: 120,
    created_by: 'yeo', created_at: 4, supersedes: null,
    _pinned_from_project: false,
  };
  options.artifactsByThread!['thread-1'] = [artifactOne];
  sockets[0].send(frame('artifact_version_added', {
    thread_id: 'thread-1', artifact_id: 'artifact-1', version: 1, created_at: 4,
  }, GENERATION_A, 3));
  await expect(page.getByText('navigation-report.md')).toBeVisible();

  const verifying = session('verifying', 3, 1);
  options.crewDetailsByParent!['parent-1'] = verifying;
  options.stepsByParent!['parent-1'] = [
    { label: 'Research evidence', status: 'done' },
    { label: 'Verify report', status: 'submitted', submitted_by: 'ezri' },
  ];
  sockets[0].send(frame(
    'crew_session_projection',
    projection(verifying, 1, 1),
    GENERATION_A,
    4,
  ));
  await expect(panel).toHaveAttribute('data-state', 'verifying');
  await expect(page.getByTestId('todo-row-1')).toContainText('Verify report');

  const done = session('done', 4, 2);
  options.crewDetailsByParent!['parent-1'] = done;
  options.stepsByParent!['parent-1'] = [
    { label: 'Research evidence', status: 'done' },
    { label: 'Verify report', status: 'done' },
  ];
  sockets[0].send(frame(
    'crew_session_projection',
    projection(done, 1, 2),
    GENERATION_A,
    5,
  ));
  await expect(panel).toHaveAttribute('data-state', 'done');
  await expect(page.getByTestId('crew-session-verification')).toContainText('94%');

  sockets[0].send(frame(
    'crew_session_projection',
    projection(executing, 0, 0),
    GENERATION_A,
    5,
  ));
  await expect(panel).toHaveAttribute('data-state', 'done');
  expect(await page.getByText('Live research result.').count()).toBe(1);

  options.messagesByThread!['thread-1'].push(
    mkMessage('message-gap', 'thread-1', 'ezri', 'agent', 'Gap repair message.', 6),
  );
  const artifactTwo = { ...artifactOne, id: 'artifact-2', name: 'evidence.md', created_at: 6 };
  options.artifactsByThread!['thread-1'] = [artifactOne, artifactTwo];
  sockets[0].send(frame(
    'crew_session_projection',
    projection(done, 2, 2),
    GENERATION_A,
    7,
  ));
  await expect(page.getByText('Gap repair message.')).toBeVisible();
  await expect(page.getByText('evidence.md')).toBeVisible();

  await sockets[0].close({ code: 1012, reason: 'restart' });
  await expect.poll(() => sockets.length, { timeout: 5000 }).toBe(2);
  options.messagesByThread!['thread-1'].push(
    mkMessage('message-reconnect', 'thread-1', 'yeo', 'agent', 'Reconnect repair message.', 8),
  );
  sockets[1].send(snapshot(GENERATION_B));
  await expect(page.getByText('Reconnect repair message.')).toBeVisible();

  await page.evaluate(() => {
    const store = (window as unknown as {
      __store: { getState: () => { closeAgentProfile: () => void } };
    }).__store;
    store.getState().closeAgentProfile();
  });
  await expect(panel).toHaveCount(0);
  const beforeCleanupEvent = apiRequests.filter(path => (
    path.includes('/messages') || path.includes('/artifacts/thread') || path.includes('/steps')
  )).length;
  sockets[1].send(frame('chat_thread_message_appended', {
    thread_id: 'thread-1', message_id: 'after-close', author_id: 'yeo',
    role: 'agent', created_at: 9,
  }, GENERATION_B, 1));
  await page.waitForTimeout(100);
  const afterCleanupEvent = apiRequests.filter(path => (
    path.includes('/messages') || path.includes('/artifacts/thread') || path.includes('/steps')
  )).length;
  expect(afterCleanupEvent).toBe(beforeCleanupEvent);
  const owners = await page.evaluate(() => {
    const state = (window as unknown as {
      __store: { getState: () => { liveCrewOwnerParentId: string | null; liveRailOwner: unknown } };
    }).__store.getState();
    return {
      crew: state.liveCrewOwnerParentId,
      rail: state.liveRailOwner,
    };
  });
  expect(owners).toEqual({ crew: null, rail: null });
});