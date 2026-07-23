import { expect, test, type WebSocketRoute } from '@playwright/test';

import {
  CREW,
  EZRI,
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

function snapshot(generation: string) {
  return frame('state_snapshot', {
    agents: CREW.map(agent => ({
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
  }, generation, 0);
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