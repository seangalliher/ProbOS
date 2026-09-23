/** Issue #1375: work-item state reconciliation, crossed on real wire texts.
 *
 * Frames are the texts a real WSEventStreamHub sent and REST bodies are the texts
 * the production app served, captured by tests/fixtures/issue1375_work_state_bridge.py
 * --write into ui/e2e/fixtures/issue1375_work_state.json through a one-to-one ID and
 * time map. Crossings seed nothing into the store: every record on screen arrives
 * through handleEvent and fetch.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import ChatsPanel from '../components/chats/ChatsPanel';
import CrewCollaborationPanel from '../components/crew/CrewCollaborationPanel';
import { BridgePanel } from '../components/BridgePanel';
import { BridgeKanban } from '../components/bridge/BridgeKanban';
import { NotificationCard } from '../components/bridge/BridgeNotifications';
import { ProfileWorkTab } from '../components/profile/ProfileWorkTab';
import {
  fetchCrewTaskDetail, fetchNotificationContext, repairRoomSummaries,
} from '../components/sidebar/threadApi';
import WorkBoard from '../components/work/WorkBoard';
import { startRoomWork } from '../components/workspace/todosApi';
import { WorkspaceFilesRail } from '../components/workspace/WorkspaceFilesRail';
import { liveReadFence } from '../store/liveReadFence';
import { useStore, workItemReconciler, type AD791aChatThreadView } from '../store/useStore';
import type {
  Agent, CrewSessionDetailProjection, CrewSessionProjectionEventData, CrewSessionRoomSummary,
  LegacyCrewTaskTree, LegacyCrewWorkItemView, MissionControlTask, NotificationView, RoomSummary, WSEvent,
  WorkItemView,
} from '../store/types';
import {
  loadIssue1375Capture, type Issue1375Capture, type Issue1375Checkpoint,
} from './helpers/issue1375Bridge';

// M3: the Board's refresh reads the nine status buckets; the private done fetch is gone.
const BUCKET_TEMPLATES = [
  ...['draft', 'open', 'scheduled', 'in_progress', 'review', 'blocked', 'failed']
    .map(status => `/api/work-items?status=${status}&limit=101`),
  ...['done', 'cancelled'].map(status => `/api/work-items?status=${status}&limit=21`),
];
const URL_TEMPLATES = [
  '/api/work-items/{X}',
  '/api/work-items/{X}/owned-steps',
  ...BUCKET_TEMPLATES,
];
const NATIVE_TEMPLATES = [
  '/api/work-items/{X}',
  '/api/work-items/{P}',
  '/api/work-items?parent_id={P}&limit=1001',
  '/api/crew-tasks/{P}',
  '/api/work-items/{X}/owned-steps',
  ...BUCKET_TEMPLATES,
];
const CAPTURED_API = /^\/api\/(work-items|crew-tasks)(?=[/?]|$)/;

interface RestReplay {
  readonly served: string[];
  readonly uncaptured: string[];
  // [checkpoint name, url] for every served request, in order.
  readonly log: Array<readonly [string, string]>;
  use(checkpoint: Issue1375Checkpoint): void;
  // Answers every held request with the body captured when it was issued.
  release(): void;
}

function replayRest(hold: (checkpoint: string, url: string) => boolean = () => false): RestReplay {
  let current: Issue1375Checkpoint = { name: 'none', frames: [], rest: {} };
  const served: string[] = [];
  const uncaptured: string[] = [];
  const log: Array<readonly [string, string]> = [];
  const held: Array<() => void> = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
    const url = typeof input === 'string' ? input
      : input instanceof URL ? `${input.pathname}${input.search}` : input.url;
    if (!CAPTURED_API.test(url)) throw new TypeError(`no backend for ${url}`);
    const entry = current.rest[url];
    if (entry === undefined) {
      uncaptured.push(url);
      throw new TypeError(`uncaptured work-item URL ${url}`);
    }
    served.push(url);
    log.push([current.name, url]);
    const response = (): Response => new Response(entry.body, {
      status: entry.status, headers: { 'Content-Type': 'application/json' },
    });
    if (!hold(current.name, url)) return response();
    return new Promise<Response>((resolve) => { held.push(() => resolve(response())); });
  }));
  return {
    served, uncaptured, log,
    use: (checkpoint) => { current = checkpoint; },
    release: () => { for (const answer of held.splice(0)) answer(); },
  };
}

function deliver(checkpoint: Issue1375Checkpoint): void {
  const drops = useStore.getState().liveDropCount;
  act(() => {
    for (const text of checkpoint.frames) useStore.getState().handleEvent(JSON.parse(text) as WSEvent);
  });
  // Premise: the live guard accepted every frame, so nothing below is a drop artefact.
  expect(useStore.getState().liveDropCount).toBe(drops);
}

function restRecord(checkpoint: Issue1375Checkpoint, url: string): WorkItemView {
  const read = checkpoint.rest[url];
  expect(read?.status).toBe(200);
  return (JSON.parse(read.body) as { work_item: WorkItemView }).work_item;
}

async function detailPanel(): Promise<HTMLElement> {
  // The modal's header row holds Close; its parent is the detail panel.
  const close = await screen.findByLabelText('Close');
  return close.parentElement!.parentElement as HTMLElement;
}

function projectionsFor(checkpoint: Issue1375Checkpoint, parentId: string): CrewSessionProjectionEventData[] {
  return checkpoint.frames.map(text => JSON.parse(text) as WSEvent)
    .filter(frame => frame.type === 'crew_session_projection')
    .map(frame => frame.data as unknown as CrewSessionProjectionEventData)
    .filter(data => data.parent_id === parentId);
}

let bridge: Issue1375Capture;

beforeAll(() => {
  bridge = loadIssue1375Capture('promoted_failed', URL_TEMPLATES);
});

beforeEach(() => {
  useStore.setState({
    workItems: null, workBookings: null, bookableResources: null, workTemplates: [],
    agents: new Map(), liveGeneration: null, liveSequence: 0, liveRepairEpoch: 0,
    crewSessionsByParent: new Map(), crewSessionSummariesByThread: new Map(),
    roomSummariesByThread: new Map(), liveCrewOwnerParentId: null, crewParentRefresh: null,
    activeProfileAgent: null, activeProfileThreadId: null, missionControlTasks: null,
  });
});

afterEach(async () => {
  await workItemReconciler.whenIdle();
  cleanup();
  vi.unstubAllGlobals();
});

describe('issue #1375 work-state reconciliation', () => {
  it('M1 promoted turn reaches failed on board and detail from the same REST record', async () => {
    const capture = bridge;
    expect(capture.checkpoints.map(checkpoint => checkpoint.name)).toEqual(['promoted', 'failed']);
    const [promoted, failed] = capture.checkpoints;
    const id = capture.ids.X;
    const byId = `/api/work-items/${id}`;
    const served = restRecord(failed, byId);
    expect(served.status).toBe('failed');
    const framesForX = capture.checkpoints.flatMap(checkpoint => checkpoint.frames)
      .map(text => JSON.parse(text) as WSEvent)
      .filter(frame => (frame.data.work_item as { id?: unknown } | undefined)?.id === id);
    // Premise (c): the stream's last word on X is status_changed, never an updated record.
    expect(framesForX[framesForX.length - 1]?.type).toBe('work_item_status_changed');

    const rest = replayRest();
    rest.use(promoted);
    const user = userEvent.setup();
    // M5: the Operations body shares the Board's cache.
    render(<><WorkBoard /><BridgeKanban /></>);
    // Premise (a): the store holds nothing about X before the first frame.
    expect(useStore.getState().workItems?.some(item => item.id === id) ?? false).toBe(false);
    deliver(promoted);

    // M5: a promoted turn's card says it is a conversation continuation.
    const card = (await screen.findByText(served.title)).closest('[role="button"]') as HTMLElement;
    expect(within(card).getByText('continuation')).toBeInTheDocument();
    await user.click(within(card).getByText(served.title));
    const openDetail = await detailPanel();
    rest.use(failed);
    deliver(failed);
    // A detail opened before the failure follows the cached record, not a copy.
    await waitFor(() => expect(openDetail).toHaveTextContent('failed'));
    expect(within(openDetail).getByText('failed')).toBeInTheDocument();
    await user.click(within(openDetail).getByLabelText('Close'));

    const row = screen.getByRole('button', { name: /Blocked\/Failed \(1\)/ });
    expect(row).toHaveTextContent('1 failed · 0 blocked · 0 cancelled');
    row.focus();
    await user.keyboard('{Enter}');
    const entry = screen.getByRole('button', { name: `${served.title}, failed, conversation continuation` });
    entry.focus();
    expect(entry).toHaveFocus();
    await user.keyboard('{Enter}');
    const detail = await detailPanel();
    expect(within(detail).getByText('failed')).toBeInTheDocument();

    const rendered = useStore.getState().workItems?.find(item => item.id === id);
    expect(rendered && { id: rendered.id, status: rendered.status, updated_at: rendered.updated_at })
      .toEqual({ id: served.id, status: served.status, updated_at: served.updated_at });
    // Premise (b): the record on screen is the one REST served.
    expect(rest.served).toContain(byId);
    expect(rest.uncaptured).toEqual([]);

    // M5: the Bridge counts X as failed and as a continuation, as many as the Board's failed count.
    const boardFailed = /(\d+) failed/.exec(row.textContent ?? '')?.[1];
    expect(boardFailed).toBe('1');
    expect(screen.getByTestId('bridge-work-failed').textContent).toBe(boardFailed);
    expect(screen.getByTestId('bridge-work-continuations-not-done').textContent).toBe('1');
    expect(screen.getByTestId('bridge-work-continuations-failed').textContent).toBe(boardFailed);
    // M5: X's detail names its origin, and its conversation link works from the keyboard.
    const origin = within(detail).getByTestId('work-board-origin');
    expect(origin).toHaveTextContent('Conversation continuation (DM promotion)');
    const link = within(origin).getByRole('button', { name: 'Open conversation' });
    link.focus();
    expect(link).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(useStore.getState().activeProfileThreadId).toBe(served.metadata.thread_id);
    expect(useStore.getState().activeProfileAgent).toBe(served.metadata.agent_id);
  });

  it('M1 statuses outside the known columns render in the Blocked/Failed row', async () => {
    // Component level (column classification, not a crossing), so this record is seeded.
    const item: WorkItemView = {
      id: 'issue1375-unknown', title: 'Quarantine drill', description: '', work_type: 'task',
      status: 'quarantined', priority: 3, parent_id: null, project_id: null, depends_on: [],
      assigned_to: null, created_by: 'captain', created_at: 1, updated_at: 1, due_at: null,
      estimated_tokens: 0, actual_tokens: 0, trust_requirement: 0, required_capabilities: [],
      tags: [], metadata: {}, steps: [], verification: null, schedule: null, ttl_seconds: null,
      template_id: null,
    };
    useStore.setState({ workItems: [item] });
    const rest = replayRest();
    // M3: the mount refresh reads the buckets, so serve a checkpoint whose failed bucket is empty.
    rest.use(bridge.checkpoints[0]);
    const user = userEvent.setup();
    render(<WorkBoard />);

    await user.click(screen.getByRole('button', { name: /Blocked\/Failed \(1\)/ }));

    expect(screen.getByRole('button', { name: 'Quarantine drill, quarantined' })).toBeInTheDocument();
    expect(rest.uncaptured).toEqual([]);
  });
});

describe('issue #1375 native crew child (M2)', () => {
  let native: Issue1375Capture;

  beforeAll(() => {
    native = loadIssue1375Capture('native_failed', NATIVE_TEMPLATES);
  });

  it('M2 native child failure agrees across board, detail, room and counts', async () => {
    const capture = native;
    expect(capture.checkpoints.map(checkpoint => checkpoint.name)).toEqual(['adopted', 'failed']);
    const [adopted, failed] = capture.checkpoints;
    const { P: parentId, X: childId, T: threadId } = capture.ids;
    const scopeUrl = `/api/work-items?parent_id=${parentId}&limit=1001`;
    const crewUrl = `/api/crew-tasks/${parentId}`;
    const child = restRecord(failed, `/api/work-items/${childId}`);
    expect([child.status, child.parent_id]).toEqual(['failed', parentId]);
    expect(restRecord(adopted, `/api/work-items/${childId}`).status).toBe('open');
    // Premise: the hub never sent the child as a record; only its parent's projection moved.
    const records = capture.checkpoints.flatMap(checkpoint => checkpoint.frames)
      .map(text => (JSON.parse(text) as WSEvent).data.work_item as { id?: unknown } | undefined);
    expect(records.filter(record => record?.id === childId)).toEqual([]);
    expect(projectionsFor(adopted, parentId).map(data => data.session.progress.failed)).not.toContain(1);
    const live = projectionsFor(failed, parentId);
    const final = live[live.length - 1];
    expect(final.session.progress).toMatchObject({ total: 1, failed: 1 });

    const rest = replayRest();
    rest.use(adopted);
    const user = userEvent.setup();
    // Both mount BEFORE the failure, so no mount-time read can carry the failed child.
    render(<><WorkBoard /><CrewCollaborationPanel threadId={threadId} parentId={parentId} /></>);
    // Premise: nothing about P or its child is seeded before the first frame.
    expect(useStore.getState().workItems).toBeNull();
    expect(useStore.getState().crewSessionsByParent.has(parentId)).toBe(false);
    deliver(adopted);
    // The room's mount read and its snapshot-epoch reload both settle on the pre-failure body.
    await waitFor(() => {
      expect(rest.log.filter(([, url]) => url === crewUrl)).toHaveLength(2);
      expect(screen.getByTestId('crew-collaboration-panel')).toHaveAttribute('aria-busy', 'false');
    });
    await act(() => workItemReconciler.whenIdle());

    rest.use(failed);
    deliver(failed);
    await act(() => workItemReconciler.whenIdle());

    // Board: the child sits in the Blocked/Failed row as failed, and its detail says failed.
    const blockedRow = await screen.findByRole('button', { name: /Blocked\/Failed \(1\)/ });
    await user.click(blockedRow);
    await user.click(screen.getByRole('button', { name: `${child.title}, failed` }));
    expect(within(await detailPanel()).getByText('failed')).toBeInTheDocument();
    // Room: 1 failed, from the hub's projection text rather than a REST reload.
    const { active, failed: failedCount, total } = final.session.progress;
    const room = screen.getByTestId('crew-collaboration-panel');
    // M5: the projection's failed count covers cancelled children too, and the room says so.
    expect(failedCount).toBe(1);
    expect(within(room).getByText(`${active} remaining · 1 failed/cancelled`)).toBeInTheDocument();
    // M5: the Board's failed and cancelled entries are the room's failed/cancelled count.
    expect(blockedRow).toHaveTextContent(`${failedCount} failed · 0 blocked · 0 cancelled`);
    expect(useStore.getState().crewSessionsByParent.get(parentId)).toEqual(final.session);
    expect(rest.log.filter(([name, url]) => name === 'failed' && url === crewUrl)).toEqual([]);
    // Counts: the Board's population for P agrees with the projection on the same IDs.
    const children = (useStore.getState().workItems ?? []).filter(item => item.parent_id === parentId);
    expect(children.map(item => item.id)).toEqual([childId]);
    expect(children.filter(item => item.status === 'failed' || item.status === 'cancelled'))
      .toHaveLength(failedCount);
    expect(children).toHaveLength(total);
    // Premise: the Board's child came from the parent-scope read, and nothing was uncaptured.
    expect(rest.log).toContainEqual(['failed', scopeUrl]);
    expect(rest.uncaptured).toEqual([]);
  });
});

describe('issue #1375 legacy crew room (M2)', () => {
  // Component level (the room's reload trigger, not a crossing), so the tree and frames are built here.
  const GENERATION = 'c'.repeat(32);
  const PARENT = 'issue1375-legacy-parent';
  const CHILD = 'issue1375-legacy-child';
  const THREAD = 'issue1375-legacy-thread';

  function legacyRecord(id: string, parentId: string | null, status: string): LegacyCrewWorkItemView {
    return {
      id, title: `Legacy ${id}`, description: '', work_type: 'task', status, priority: 3,
      parent_id: parentId, project_id: null, depends_on: [], assigned_to: 'worker-a',
      created_by: 'captain', created_at: 1, updated_at: 2, due_at: null, estimated_tokens: null,
      actual_tokens: 0, trust_requirement: 0.5, required_capabilities: [], tags: [], metadata: {},
      steps: [], verification: {}, schedule: {}, ttl_seconds: null, template_id: null,
    };
  }

  function legacyTree(childStatus: string): LegacyCrewTaskTree {
    return {
      parent: legacyRecord(PARENT, null, 'in_progress'),
      children: [{ ...legacyRecord(CHILD, PARENT, childStatus), verdict: null, rounds: null }],
      count: 1,
    };
  }

  function nativeSession(): CrewSessionDetailProjection {
    return {
      task_id: PARENT, thread_id: THREAD, goal: 'Native room', origin: 'captain',
      originator_id: 'captain', facilitator_id: 'facilitator-a', owner_ids: ['facilitator-a'],
      state: 'executing', revision: 1, success_criteria: ['Done'], expected_deliverable: 'Report',
      timestamps: {
        created_at: 1, transitioned_at: 1, started_at: 1, first_result_at: null,
        verified_at: null, completed_at: null,
      },
      progress: { total: 1, done: 0, failed: 0, active: 1, active_child: null },
      last_result_summary: '', blocker: null, result: null, verification: null,
      duplicate_resume_count: 0,
    };
  }

  function childFrame(parentId: string, status: string, sequence: number): WSEvent {
    return {
      type: 'work_item_status_changed',
      data: { work_item: legacyRecord(CHILD, parentId, status) },
      timestamp: 1,
      stream: { generation: GENERATION, sequence },
    };
  }

  function stubRoom(body: () => unknown): string[] {
    const crewReads: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      if (url === `/api/crew-tasks/${PARENT}`) {
        crewReads.push(url);
        return new Response(JSON.stringify(body()), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      // The Board reconciler also reads the child by ID; the room does not need it.
      if (url.startsWith('/api/work-items/')) return new Response('{}', { status: 503 });
      throw new TypeError(`no backend for ${url}`);
    }));
    return crewReads;
  }

  beforeEach(() => {
    useStore.setState({ liveGeneration: GENERATION, liveSequence: 0 });
  });

  it('M2 a legacy child frame reloads the legacy room and shows the REST status', async () => {
    let childStatus = 'in_progress';
    const crewReads = stubRoom(() => legacyTree(childStatus));
    render(<CrewCollaborationPanel threadId={THREAD} parentId={PARENT} />);
    // Premise: the room's current response is a legacy tree, not a native session.
    expect(await screen.findByTestId('crew-subtask-card')).toHaveAttribute('data-status', 'in_progress');
    expect(useStore.getState().crewSessionsByParent.has(PARENT)).toBe(false);
    expect(crewReads).toHaveLength(1);

    childStatus = 'failed';
    act(() => { useStore.getState().handleEvent(childFrame(PARENT, 'failed', 1)); });

    await waitFor(() => expect(screen.getByTestId('crew-subtask-card')).toHaveAttribute('data-status', 'failed'));
    expect(crewReads).toHaveLength(2);
  });

  it('M2 a native room does not reload on its child frame', async () => {
    const crewReads = stubRoom(() => ({ session: nativeSession() }));
    render(<CrewCollaborationPanel threadId={THREAD} parentId={PARENT} />);
    // Premise: the room's current response is a native session.
    await waitFor(() => expect(useStore.getState().crewSessionsByParent.get(PARENT)?.revision).toBe(1));

    act(() => { useStore.getState().handleEvent(childFrame(PARENT, 'failed', 1)); });
    await act(() => workItemReconciler.whenIdle());

    // Premise: the frame did reach the room's refresh trigger for this parent.
    expect(useStore.getState().crewParentRefresh?.parentId).toBe(PARENT);
    expect(crewReads).toHaveLength(1);
  });

  it('M2 a legacy room does not reload for another parent\'s child', async () => {
    const crewReads = stubRoom(() => legacyTree('in_progress'));
    render(<CrewCollaborationPanel threadId={THREAD} parentId={PARENT} />);
    await screen.findByTestId('crew-subtask-card');

    act(() => { useStore.getState().handleEvent(childFrame('issue1375-other-parent', 'failed', 1)); });
    await act(() => workItemReconciler.whenIdle());

    expect(useStore.getState().crewParentRefresh?.parentId).toBe('issue1375-other-parent');
    expect(crewReads).toHaveLength(1);
  });

  it('M4 a legacy child frame during the first load re-reads instead of showing the older tree', async () => {
    const answers: Array<(response: Response) => void> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      if (url === `/api/crew-tasks/${PARENT}`) return new Promise<Response>((resolve) => { answers.push(resolve); });
      if (url.startsWith('/api/work-items/')) return new Response('{}', { status: 503 });
      throw new TypeError(`no backend for ${url}`);
    }));
    const tree = (status: string): Response => new Response(JSON.stringify(legacyTree(status)), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    });
    render(<CrewCollaborationPanel threadId={THREAD} parentId={PARENT} />);
    await waitFor(() => expect(answers).toHaveLength(1));

    act(() => { useStore.getState().handleEvent(childFrame(PARENT, 'failed', 1)); });
    // Premise: the frame reached the room before it showed anything, so its refresh effect could not re-read.
    expect(useStore.getState().crewParentRefresh?.parentId).toBe(PARENT);
    expect(screen.getByTestId('crew-session-loading')).toBeInTheDocument();

    await act(async () => { answers[0](tree('in_progress')); });
    // The tree read before the frame is skipped, and the room reads again instead of showing it.
    await waitFor(() => expect(answers).toHaveLength(2));
    expect(screen.queryByTestId('crew-subtask-card')).toBeNull();
    expect(screen.getByTestId('crew-session-loading')).toBeInTheDocument();

    await act(async () => { answers[1](tree('failed')); });
    expect(await screen.findByTestId('crew-subtask-card')).toHaveAttribute('data-status', 'failed');
    expect(answers).toHaveLength(2);
  });
});

describe('issue #1375 restart (M3)', () => {
  let restart: Issue1375Capture;

  beforeAll(() => {
    restart = loadIssue1375Capture('restart', URL_TEMPLATES);
  });

  it('M3 a stale read issued before a restart cannot resurrect the older status', async () => {
    const capture = restart;
    expect(capture.checkpoints.map(checkpoint => checkpoint.name)).toEqual(['in_progress', 'restarted']);
    const [before, after] = capture.checkpoints;
    const id = capture.ids.X;
    const byId = `/api/work-items/${id}`;
    const held = restRecord(before, byId);
    const served = restRecord(after, byId);
    // Premise: the held body says in_progress; REST after the restart says failed.
    expect([held.status, served.status]).toEqual(['in_progress', 'failed']);
    // Premise: the two snapshot texts carry different generations.
    const snapshots = capture.checkpoints.map(checkpoint => JSON.parse(checkpoint.frames[0]) as WSEvent);
    expect(snapshots.map(snapshot => snapshot.type)).toEqual(['state_snapshot', 'state_snapshot']);
    expect(snapshots[0].stream?.generation).not.toBe(snapshots[1].stream?.generation);

    const order: string[] = [];
    // Holds only X's first by-ID read; any re-read is answered normally.
    const rest = replayRest((checkpoint, url) => {
      const holding = checkpoint === 'in_progress' && url === byId && !order.includes('issued');
      if (holding) order.push('issued');
      return holding;
    });
    try {
      rest.use(before);
      const user = userEvent.setup();
      render(<WorkBoard />);
      // Premise: nothing about X is seeded; the Board learns it from the stream and REST.
      expect(useStore.getState().workItems).toBeNull();
      deliver(before);
      // X reaches the Board from its status bucket while its own by-ID read is held.
      await user.click(await screen.findByText(held.title));
      const openDetail = await detailPanel();
      expect(within(openDetail).getByText('in_progress')).toBeInTheDocument();
      await waitFor(() => expect(order).toEqual(['issued']));

      rest.use(after);
      deliver(after);
      order.push('snapshot');
      const statuses: string[] = [];
      const unsubscribe = useStore.subscribe((state) => {
        const record = state.workItems?.find(item => item.id === id);
        if (record) statuses.push(record.status);
      });
      try {
        order.push('released');
        rest.release();
        await act(() => workItemReconciler.whenIdle());
      } finally {
        unsubscribe();
      }

      expect(order).toEqual(['issued', 'snapshot', 'released']);
      // The held in_progress body never reached the store once generation 2 had spoken.
      expect(statuses).not.toContain('in_progress');
      expect(openDetail).toHaveTextContent('failed');
      await user.click(within(openDetail).getByLabelText('Close'));
      await user.click(screen.getByRole('button', { name: /Blocked\/Failed \(1\)/ }));
      // M5: X is a promoted turn, so its entry also names its origin.
      expect(screen.getByRole('button', { name: `${served.title}, failed, conversation continuation` })).toBeInTheDocument();
      const rendered = useStore.getState().workItems?.find(item => item.id === id);
      expect(rendered && { status: rendered.status, updated_at: rendered.updated_at })
        .toEqual({ status: served.status, updated_at: served.updated_at });
      // Repair: generation 2's snapshot made the interested Board re-read every bucket.
      expect(rest.log.filter(([name, url]) => name === 'restarted' && url.startsWith('/api/work-items?status=')))
        .toHaveLength(BUCKET_TEMPLATES.length);
      expect(rest.uncaptured).toEqual([]);
    } finally {
      rest.release();
    }
  });
});

function record(id: string, status: string, overrides: Partial<WorkItemView> = {}): WorkItemView {
  return {
    id, title: `Work ${id}`, description: '', work_type: 'task', status, priority: 3,
    parent_id: null, project_id: null, depends_on: [], assigned_to: null, created_by: 'captain',
    created_at: 1, updated_at: 1, due_at: null, estimated_tokens: 0, actual_tokens: 0,
    trust_requirement: 0, required_capabilities: [], tags: [], metadata: {}, steps: [],
    verification: null, schedule: null, ttl_seconds: null, template_id: null, ...overrides,
  };
}

/** Component level: a fake of the two work-item GET routes; any other URL answers 404. */
function serveWorkItems(
  records: () => readonly WorkItemView[],
  status: (url: string) => number = () => 200,
  gate: Promise<void> = Promise.resolve(),
): string[] {
  const urls: string[] = [];
  const json = (code: number, body: unknown): Response => new Response(JSON.stringify(body), {
    status: code, headers: { 'Content-Type': 'application/json' },
  });
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
    const url = String(input);
    urls.push(url);
    await gate;
    const parsed = new URL(url, 'http://hxi.test');
    if (!parsed.pathname.startsWith('/api/work-items')) return json(404, { detail: 'no backend' });
    const code = status(url);
    if (code !== 200) return json(code, { detail: 'refused' });
    if (parsed.pathname === '/api/work-items') {
      // Like the store, list reads leave scaffold rows out; filters are exact matches.
      const rows = records().filter(row => row.metadata.ui_scaffold !== 1 && row.metadata.ui_scaffold !== true
        && [...parsed.searchParams].every(([key, value]) => key === 'limit'
          || String(row[key as keyof WorkItemView]) === value))
        .slice(0, Number(parsed.searchParams.get('limit')));
      return json(200, { work_items: rows, count: rows.length });
    }
    const id = /^\/api\/work-items\/([^/]+)$/.exec(parsed.pathname)?.[1];
    const row = id === undefined ? undefined : records().find(candidate => candidate.id === decodeURIComponent(id));
    return row ? json(200, { work_item: row }) : json(404, { detail: 'Work item not found' });
  }));
  return urls;
}

describe('issue #1375 work surfaces (M3)', () => {
  // Component level (population, labels and states, not a crossing): a fake of the two GET routes.
  const GENERATION = 'd'.repeat(32);

  function column(label: string): HTMLElement {
    return screen.getByText(label).parentElement!.parentElement as HTMLElement;
  }

  function columnTitles(label: string): string[] {
    return within(column(label)).queryAllByRole('button').map(card => card.textContent ?? '');
  }

  function columnCount(label: string): string {
    return screen.getByText(label).nextElementSibling?.textContent ?? '';
  }

  function resync(sequence: number): WSEvent {
    return { type: 'resync_required', data: {}, timestamp: 1, stream: { generation: GENERATION, sequence } };
  }

  it('M3 the board loads its population from the status buckets, with no private done fetch', async () => {
    const urls = serveWorkItems(() => [record('a', 'open'), record('b', 'done')]);
    render(<WorkBoard />);
    await act(() => workItemReconciler.whenIdle());

    expect(urls).toEqual(BUCKET_TEMPLATES);
    expect(columnTitles('BACKLOG')).toEqual([expect.stringMatching(/^Work a/)]);
    expect(columnTitles('DONE')).toEqual([expect.stringMatching(/^Work b/)]);
  });

  it('M3 columns sort by priority, newest created, then id; Done shows the latest 20 by update under an honest header', async () => {
    const running = [
      record('ip-c', 'in_progress', { priority: 2, created_at: 5 }),
      record('ip-a', 'in_progress', { priority: 1, created_at: 1 }),
      record('ip-b2', 'in_progress', { priority: 2, created_at: 9 }),
      record('ip-b1', 'in_progress', { priority: 2, created_at: 9 }),
    ];
    const done = Array.from({ length: 25 }, (_, index) => record(
      `d${String(index).padStart(2, '0')}`, 'done', { updated_at: 100 + ((index * 7) % 25) },
    ));
    serveWorkItems(() => [...running, ...done]);
    render(<WorkBoard />);
    await act(() => workItemReconciler.whenIdle());

    expect(columnTitles('IN PROGRESS').map(text => text.split('task')[0]))
      .toEqual(['Work ip-a', 'Work ip-b1', 'Work ip-b2', 'Work ip-c']);
    // The done bucket served 21 of the 25; the column shows the 20 of those updated last.
    const latest = [...done.slice(0, 21)].sort((a, b) => b.updated_at - a.updated_at).slice(0, 20);
    expect(columnTitles('DONE').map(text => text.split('task')[0])).toEqual(latest.map(item => item.title));
    expect(columnCount('DONE')).toBe('latest 20 of 21+');
    expect(columnCount('IN PROGRESS')).toBe('4/10');
  });

  it('M3 the board says it is loading until its first read answers, then that it is empty', async () => {
    let answer!: () => void;
    serveWorkItems(() => [], () => 200, new Promise<void>((resolve) => { answer = resolve; }));
    render(<WorkBoard />);
    expect(screen.getByTestId('work-board-state')).toHaveAttribute('data-state', 'loading');
    expect(screen.getByTestId('work-board-state')).toHaveTextContent('Loading work items');

    answer();
    await act(() => workItemReconciler.whenIdle());

    expect(screen.getByTestId('work-board-state')).toHaveAttribute('data-state', 'empty');
    expect(screen.getByTestId('work-board-state')).toHaveTextContent('No work items.');
  });

  it.each([
    [503, 'unavailable', 'Work items are unavailable.'],
    [401, 'unauthorized', 'Access to work items was denied.'],
  ])('M3 a first read answered %s shows the %s state', async (code, state, text) => {
    serveWorkItems(() => [record('a', 'open')], () => code);
    render(<WorkBoard />);
    await act(() => workItemReconciler.whenIdle());

    expect(screen.getByTestId('work-board-state')).toHaveAttribute('data-state', state);
    expect(screen.getByTestId('work-board-state')).toHaveTextContent(text);
    expect(screen.queryByText('Work a')).toBeNull();
  });

  it.each([
    [503, 'stale', 'Showing last known work items', true],
    [401, 'unauthorized', 'Access to work items was denied.', false],
  ])('M3 a refresh answered %s after a load shows the %s state', async (code, state, text, kept) => {
    let status = 200;
    serveWorkItems(() => [record('a', 'open')], () => status);
    useStore.setState({ liveGeneration: GENERATION, liveSequence: 0 });
    render(<WorkBoard />);
    await act(() => workItemReconciler.whenIdle());
    expect(screen.getByText('Work a')).toBeInTheDocument();

    status = code;
    act(() => { useStore.getState().handleEvent(resync(1)); });
    await act(() => workItemReconciler.whenIdle());

    expect(screen.getByTestId('work-board-state')).toHaveAttribute('data-state', state);
    expect(screen.getByTestId('work-board-state')).toHaveTextContent(text);
    // 503 keeps the last-known record; 401/403 drops the content (I5).
    expect(screen.queryByText('Work a') !== null).toBe(kept);
  });

  it('M3 an unknown status renders in the Blocked/Failed row, and scaffold rows are never shown or counted', async () => {
    const rows = [
      record('open-1', 'open'),
      record('odd', 'quarantined'),
      record('bind-open', 'open', { metadata: { ui_scaffold: 1 } }),
      record('bind-failed', 'failed', { metadata: { ui_scaffold: true } }),
    ];
    // Component level: scaffold rows reach the cache only by ID (S29), so they are seeded here.
    useStore.setState({ workItems: rows });
    serveWorkItems(() => rows);
    const user = userEvent.setup();
    render(<WorkBoard />);
    await act(() => workItemReconciler.whenIdle());

    expect(columnCount('BACKLOG')).toBe('1');
    await user.click(screen.getByRole('button', { name: /Blocked\/Failed \(1\)/ }));
    expect(screen.getByRole('button', { name: 'Work odd, quarantined' })).toBeInTheDocument();
    expect(screen.queryByText('Work bind-open')).toBeNull();
    expect(screen.queryByText('Work bind-failed')).toBeNull();
  });

  it('M3 the Operations body registers interest in the work-item population', async () => {
    const urls = serveWorkItems(() => []);
    render(<BridgeKanban />);
    await act(() => workItemReconciler.whenIdle());

    expect(urls).toEqual(BUCKET_TEMPLATES);
  });

  it('M3 the profile reads its agent scopes, labels Blocked / Failed, and shows 10+ for a truncated done scope', async () => {
    const mine = { assigned_to: 'res-a' };
    const rows = [
      record('p-run', 'in_progress', mine),
      record('p-failed', 'failed', mine),
      record('p-blocked', 'blocked', mine),
      ...Array.from({ length: 12 }, (_, index) => record(`p-done-${index}`, 'done', { ...mine, updated_at: 10 + index })),
      record('other', 'open', { assigned_to: 'res-b' }),
      // Reassigned since the profile last saw it; no bucket returns its status.
      record('moved', 'quarantined', { assigned_to: 'res-c' }),
    ];
    useStore.setState({ workItems: [record('moved', 'in_progress', mine)] });
    const urls = serveWorkItems(() => rows);
    const user = userEvent.setup();
    render(<ProfileWorkTab agentId="res-a" />);
    await act(() => workItemReconciler.whenIdle());

    expect(urls).toContain('/api/work-items?assigned_to=res-a&limit=101');
    expect(urls).toContain('/api/work-items?assigned_to=res-a&status=done&limit=11');
    expect(urls.filter(url => /[?&]limit=10(&|$)/.test(url))).toEqual([]);
    // The omission was confirmed by ID before the profile stopped showing it.
    expect(urls).toContain('/api/work-items/moved');
    expect(screen.queryByText('Work moved')).toBeNull();
    expect(screen.getByText('Active Work (1)')).toBeInTheDocument();
    expect(screen.getByText('Blocked / Failed (2)')).toBeInTheDocument();
    await user.click(screen.getByText('Completed (10+)'));
    const shown = Array.from({ length: 10 }, (_, index) => `Work p-done-${11 - index}`);
    for (const title of shown) expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.queryByText('Work p-done-1')).toBeNull();
  });

  it('M3 rendering BridgePanel makes zero /api/work-items fetches, even as work-item frames arrive', async () => {
    const urls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      urls.push(String(input));
      throw new TypeError('no backend');
    }));
    render(<BridgePanel open onClose={() => {}} />);
    for (const checkpoint of bridge.checkpoints) deliver(checkpoint);
    await act(() => workItemReconciler.whenIdle());

    // Premise: the frames reached the store; the Bridge still read no work item (I7).
    expect(useStore.getState().liveSequence).toBeGreaterThan(0);
    expect(urls.filter(url => url.startsWith('/api/work-items'))).toEqual([]);
  });
});

describe('issue #1375 named counters (M5)', () => {
  // Component level (counter labels and origin display, not a crossing): the fake GET routes above.
  const EMOJI = /\p{Extended_Pictographic}/u;

  // turn_promotion.py _create_promoted_work_item: the shape of a promoted DM turn.
  function continuationRecord(id: string, status: string): WorkItemView {
    return record(id, status, {
      assigned_to: 'agent-a', tags: ['conversational-turn'],
      metadata: { source: 'dm_agentic_promotion', thread_id: 'dm-thread', agent_id: 'agent-a' },
    });
  }

  function buildTask(id: string, status: MissionControlTask['status']): MissionControlTask {
    return {
      id, type: 'build', title: `Build ${id}`, department: 'engineering', status, agent_type: 'builder',
      agent_id: 'builder-1', started_at: 1, completed_at: 0, priority: 3, ad_number: 0, error: '', metadata: {},
    };
  }

  function workUrls(urls: readonly string[]): string[] {
    return urls.filter(url => url.startsWith('/api/work-items'));
  }

  it('M5 the Operations header counts work items not done from the cache alone, and says unknown until they load', async () => {
    const rows = [
      record('open-1', 'open'), continuationRecord('turn-failed', 'failed'), record('blocked-1', 'blocked'),
      record('done-1', 'done'), record('cancelled-1', 'cancelled'),
    ];
    const urls = serveWorkItems(() => rows);
    render(<BridgePanel open onClose={() => {}} />);
    await screen.findByText(/SHUTDOWN/i);
    const header = (): HTMLElement => screen.getByRole('button', { name: /^Operations \(/ });

    // H8: nothing has loaded the population, so the header does not guess.
    expect(header()).toHaveTextContent('Operations (unknown)');
    expect(workUrls(urls)).toEqual([]);

    render(<WorkBoard />);
    await act(() => workItemReconciler.whenIdle());

    // H7: the count is what Expand opens, every item not done or cancelled; failed and blocked count.
    await waitFor(() => expect(header()).toHaveTextContent('Operations (3)'));
    // Premise: only the Board read the population; the Bridge read nothing (I7).
    expect(workUrls(urls)).toEqual(BUCKET_TEMPLATES);
  });

  it('M5 the Operations body sums work items and keeps the build pipeline apart, with done and failed split', async () => {
    useStore.setState({
      missionControlTasks: [
        buildTask('q', 'queued'), buildTask('w', 'working'), buildTask('r', 'review'),
        buildTask('d', 'done'), buildTask('f1', 'failed'), buildTask('f2', 'failed'),
      ],
    });
    serveWorkItems(() => [
      record('open-1', 'open'), record('blocked-1', 'blocked'), record('failed-1', 'failed'),
      continuationRecord('turn-failed', 'failed'), continuationRecord('turn-running', 'in_progress'),
      continuationRecord('turn-done', 'done'), record('cancelled-1', 'cancelled'),
    ]);
    render(<BridgeKanban />);
    await act(() => workItemReconciler.whenIdle());

    const summary = screen.getByRole('group', { name: 'Work items' });
    const count = (testId: string): string | null => within(summary).getByTestId(testId).textContent;
    expect(count('bridge-work-not-done')).toBe('5');
    expect(count('bridge-work-failed')).toBe('2');
    expect(count('bridge-work-blocked')).toBe('1');
    expect(count('bridge-work-continuations-not-done')).toBe('2');
    expect(count('bridge-work-continuations-failed')).toBe('1');
    // The pipeline keeps its population; done and failed builds now sit in separate columns.
    const pipeline = screen.getByRole('group', { name: 'Build pipeline' });
    expect(['queued', 'working', 'review', 'done', 'failed']
      .map(key => within(pipeline).getByTestId(`build-pipeline-${key}-count`).textContent))
      .toEqual(['1', '1', '1', '1', '2']);
    expect(document.body.textContent ?? '').not.toMatch(EMOJI);
  });

  it('M5 the Blocked/Failed row breaks down its statuses, opens every entry by keyboard, and shows continuation origins', async () => {
    const rows = [
      record('failed-1', 'failed'), continuationRecord('turn-failed', 'failed'), record('blocked-1', 'blocked'),
      record('cancelled-1', 'cancelled'), record('odd-1', 'quarantined'),
      continuationRecord('turn-open', 'open'), record('open-1', 'open'),
    ];
    // Component level: no bucket serves the quarantined row, so the cache is seeded with the rows.
    useStore.setState({ workItems: rows });
    serveWorkItems(() => rows);
    const user = userEvent.setup();
    render(<WorkBoard />);
    await act(() => workItemReconciler.whenIdle());

    const row = screen.getByRole('button', { name: /Blocked\/Failed \(5\)/ });
    expect(row).toHaveTextContent('2 failed · 1 blocked · 1 cancelled · 1 other');
    const card = (title: string): HTMLElement => screen.getByText(title).closest('[role="button"]') as HTMLElement;
    expect(within(card('Work turn-open')).getByText('continuation')).toBeInTheDocument();
    expect(within(card('Work open-1')).queryByText('continuation')).toBeNull();

    row.focus();
    await user.keyboard('{Enter}');
    const reached: string[] = [];
    for (let step = 0; step < 5; step += 1) {
      await user.tab();
      reached.push(document.activeElement?.getAttribute('aria-label') ?? '');
    }
    expect(reached.sort()).toEqual([
      'Work blocked-1, blocked', 'Work cancelled-1, cancelled', 'Work failed-1, failed',
      'Work odd-1, quarantined', 'Work turn-failed, failed, conversation continuation',
    ]);
    const turnEntry = screen.getByRole('button', { name: 'Work turn-failed, failed, conversation continuation' });
    expect(within(turnEntry).getByText('continuation')).toBeInTheDocument();

    turnEntry.focus();
    await user.keyboard('{Enter}');
    const detail = await detailPanel();
    const origin = within(detail).getByTestId('work-board-origin');
    expect(origin).toHaveTextContent('Conversation continuation (DM promotion)');
    within(detail).getByLabelText('Close').focus();
    await user.tab();
    const link = within(origin).getByRole('button', { name: 'Open conversation' });
    expect(link).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(useStore.getState()).toMatchObject({ activeProfileAgent: 'agent-a', activeProfileThreadId: 'dm-thread' });
    // The detail closes so the conversation it opened is not hidden behind it.
    expect(screen.queryByLabelText('Close')).toBeNull();

    screen.getByRole('button', { name: 'Work failed-1, failed' }).focus();
    await user.keyboard('{Enter}');
    const delegated = within(await detailPanel()).getByTestId('work-board-origin');
    expect(delegated).toHaveTextContent('Delegated');
    expect(within(delegated).queryByRole('button')).toBeNull();
    expect(document.body.textContent ?? '').not.toMatch(EMOJI);
  });
});

describe('issue #1375 by-ID read failures and displayed freshness (RV1)', () => {
  // Component level: the fake GET routes above, with the by-ID route of `x` answering a chosen status.
  const GENERATION = 'e'.repeat(32);
  const ROWS = [record('a', 'open'), record('x', 'in_progress'), record('f', 'failed')];

  function changed(id: string, sequence: number): WSEvent {
    return {
      type: 'work_item_updated', data: { work_item: record(id, 'in_progress') }, timestamp: 1,
      stream: { generation: GENERATION, sequence },
    };
  }

  function frameX(sequence: number): void {
    act(() => { useStore.getState().handleEvent(changed('x', sequence)); });
  }

  const operationsHeader = (): HTMLElement => screen.getByRole('button', { name: /^Operations \(/ });

  // BridgePanel reads other routes too; only work-item reads matter here.
  const workUrls = (urls: readonly string[]): string[] => urls.filter(url => url.startsWith('/api/work-items'));

  // Mounts the Board and the Operations header and body over nine fresh bucket reads, then frames `x` once.
  async function loadThenFrameX(code: () => number): Promise<string[]> {
    const urls = serveWorkItems(() => ROWS, url => (url === '/api/work-items/x' ? code() : 200));
    useStore.setState({ liveGeneration: GENERATION, liveSequence: 0 });
    render(<BridgePanel open onClose={() => {}} />);
    await screen.findByText(/SHUTDOWN/i);
    render(<WorkBoard />);
    render(<BridgeKanban />);
    await act(() => workItemReconciler.whenIdle());
    // Premise: every bucket read fresh, so the population alone says ready and the counts are exact.
    expect(workUrls(urls)).toEqual(BUCKET_TEMPLATES);
    expect(screen.queryByTestId('work-board-state')).toBeNull();
    expect(operationsHeader()).toHaveTextContent('Operations (3)');

    frameX(1);
    await act(() => workItemReconciler.whenIdle());
    // Premise: the frame caused exactly one by-ID read.
    expect(workUrls(urls).slice(BUCKET_TEMPLATES.length)).toEqual(['/api/work-items/x']);
    return urls;
  }

  it('RV1 a by-ID 503 after nine fresh bucket reads shows the Board and every Operations count as last known', async () => {
    await loadThenFrameX(() => 503);

    // 503 keeps the record (I5), and nothing on screen may claim it is current.
    expect(screen.getByText('Work x')).toBeInTheDocument();
    expect(screen.getByTestId('work-board-state')).toHaveAttribute('data-state', 'stale');
    expect(screen.getByTestId('work-board-state')).toHaveTextContent('Showing last known work items');
    expect(operationsHeader()).toHaveTextContent('Operations (3 (last known))');
    expect(screen.getByTestId('bridge-work-not-done').textContent).toBe('3 (last known)');
    expect(screen.getByTestId('bridge-work-failed').textContent).toBe('1 (last known)');
  });

  it('RV1 a later successful by-ID read of the item clears last known', async () => {
    let code = 503;
    await loadThenFrameX(() => code);
    // Premise: the failure showed.
    expect(screen.getByTestId('work-board-state')).toHaveAttribute('data-state', 'stale');

    code = 200;
    frameX(2);
    await act(() => workItemReconciler.whenIdle());

    expect(screen.queryByTestId('work-board-state')).toBeNull();
    expect(operationsHeader()).toHaveTextContent('Operations (3)');
    expect(screen.getByTestId('bridge-work-not-done').textContent).toBe('3');
  });

  it('RV1 a single item refused by ID drops that item but never hides the Board', async () => {
    await loadThenFrameX(() => 401);

    expect(screen.queryByText('Work x')).toBeNull();
    expect(screen.getByText('Work a')).toBeInTheDocument();
    expect(screen.getByTestId('work-board-state')).toHaveAttribute('data-state', 'stale');
    expect(operationsHeader()).toHaveTextContent('Operations (2 (last known))');
  });

  it('RV1 the profile marks its counts last known while a by-ID read failure is outstanding', async () => {
    const mine = { assigned_to: 'res-a' };
    const rows = [record('p-run', 'in_progress', mine), record('x', 'open', mine), record('p-done', 'done', mine)];
    let code = 503;
    serveWorkItems(() => rows, url => (url === '/api/work-items/x' ? code : 200));
    useStore.setState({ liveGeneration: GENERATION, liveSequence: 0 });
    render(<ProfileWorkTab agentId="res-a" />);
    await act(() => workItemReconciler.whenIdle());
    // Premise: the agent's scopes read fresh.
    expect(screen.getByText('Active Work (2)')).toBeInTheDocument();
    expect(screen.getByText('Completed (1)')).toBeInTheDocument();

    frameX(1);
    await act(() => workItemReconciler.whenIdle());
    expect(screen.getByText('Active Work (2 (last known))')).toBeInTheDocument();
    expect(screen.getByText('Completed (1 (last known))')).toBeInTheDocument();

    code = 200;
    frameX(2);
    await act(() => workItemReconciler.whenIdle());
    expect(screen.getByText('Active Work (2)')).toBeInTheDocument();
    expect(screen.getByText('Completed (1)')).toBeInTheDocument();
  });
});

describe('issue #1375 crew hydration fence (M4)', () => {
  // Component level (each caller's issue stamp, not a crossing): shape-valid bodies and frames are built here.
  const GENERATION = 'f'.repeat(32);
  const PARENT = 'issue1375-fence-parent';
  const THREAD = 'issue1375-fence-thread';
  const HOST = 'issue1375-fence-host';
  let sequence = 0;

  function session(done: number): CrewSessionDetailProjection {
    return {
      task_id: PARENT, thread_id: THREAD, goal: 'Fenced room', origin: 'captain',
      originator_id: 'captain', facilitator_id: HOST, owner_ids: [HOST],
      state: 'executing', revision: 2, success_criteria: ['Done'], expected_deliverable: 'Report',
      timestamps: {
        created_at: 1, transitioned_at: 2, started_at: 2, first_result_at: null,
        verified_at: null, completed_at: null,
      },
      progress: {
        total: 2, done, failed: 0, active: 2 - done,
        active_child: { id: 'issue1375-fence-child', title: 'Research', status: 'in_progress', owner_id: HOST },
      },
      last_result_summary: done > 0 ? 'One child complete' : '', blocker: null, result: null,
      verification: null, duplicate_resume_count: 0,
    };
  }

  function roomOf(source: CrewSessionDetailProjection): CrewSessionRoomSummary {
    const { total, done, failed, active } = source.progress;
    return {
      outputs: done, steps_total: total, steps_done: done, topic: source.goal,
      session: {
        task_id: source.task_id, thread_id: source.thread_id, goal: source.goal, state: source.state,
        facilitator_id: source.facilitator_id, owner_ids: source.owner_ids,
        progress: { total, done, failed, active }, last_result_summary: source.last_result_summary,
        blocker: null, needs_attention: false, result_artifact_id: null, verified_at: null,
      },
    };
  }

  /** Delivers `source` as a live projection; the room map holding the exact object proves the parser accepted it. */
  function deliverLive(source: CrewSessionDetailProjection): CrewSessionRoomSummary {
    const room = roomOf(source);
    sequence += 1;
    act(() => {
      useStore.getState().handleEvent({
        type: 'crew_session_projection',
        data: {
          parent_id: source.task_id, thread_id: source.thread_id, revision: source.revision,
          session: source, room_summary: room,
        },
        timestamp: 1,
        stream: { generation: GENERATION, sequence },
      });
    });
    expect(useStore.getState().roomSummariesByThread.get(source.thread_id)).toBe(room);
    return room;
  }

  function json(body: unknown): Response {
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
  }

  /** Premise helper: what the caller's own REST validator makes of `body`. */
  async function servedOnce<T>(body: unknown, read: () => Promise<T>): Promise<T> {
    vi.stubGlobal('fetch', vi.fn(async (): Promise<Response> => json(body)));
    return read();
  }

  /** Holds the request to `held` until `answer`; serves `routes` at once; any other URL has no backend. */
  function holdRequest(held: string, routes: Readonly<Record<string, unknown>> = {}) {
    let settle: ((response: Response) => void) | null = null;
    let issued = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      if (url === held) {
        issued += 1;
        return new Promise<Response>((resolve) => { settle = resolve; });
      }
      if (url in routes) return json(routes[url]);
      throw new TypeError(`no backend for ${url}`);
    }));
    return {
      issued: () => issued,
      answer: (body: unknown) => { settle?.(json(body)); },
    };
  }

  function hostAgent(): Agent {
    return {
      id: HOST, agentType: 'crew', callsign: 'Host', displayName: 'Host', pool: 'bridge',
      state: 'active', confidence: 1, trust: 0.5, tier: 'domain', isCrew: true, position: [0, 0, 0],
    };
  }

  /** Holds only the first request to `held`; later ones get `later()` at once; `routes` answer at once. */
  function holdFirstRequest(held: string, later: () => unknown, routes: Readonly<Record<string, unknown>> = {}) {
    let settle: ((response: Response) => void) | null = null;
    let issued = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      if (url === held) {
        issued += 1;
        if (issued > 1) return json(later());
        return new Promise<Response>((resolve) => { settle = resolve; });
      }
      if (url in routes) return json(routes[url]);
      throw new TypeError(`no backend for ${url}`);
    }));
    return {
      issued: () => issued,
      answerFirst: (body: unknown) => { settle?.(json(body)); },
    };
  }

  /** S6: an owned-step reassign publishes the native child raw, as its full record, not as a projection. */
  function rawAssignedChildFrame(): WSEvent {
    sequence += 1;
    const child: WorkItemView = {
      id: 'issue1375-fence-child', title: 'Research', description: '', work_type: 'task',
      status: 'open', priority: 3, parent_id: PARENT, project_id: null, depends_on: [],
      assigned_to: 'issue1375-fence-other', created_by: HOST, created_at: 1, updated_at: 3,
      due_at: null, estimated_tokens: 0, actual_tokens: 0, trust_requirement: 0,
      required_capabilities: [], tags: [], metadata: {}, steps: [], verification: null,
      schedule: null, ttl_seconds: null, template_id: null,
    };
    return {
      type: 'work_item_assigned',
      data: { work_item: child, source: 'reassign_unstarted' },
      timestamp: 1,
      stream: { generation: GENERATION, sequence },
    };
  }

  beforeEach(() => {
    sequence = 0;
    useStore.setState({ liveGeneration: GENERATION, liveSequence: 0 });
  });

  afterEach(() => {
    useStore.setState({
      chatsOpen: false, chatThreads: new Map(), threadIdByAgent: new Map(),
      activeProfileAgent: null, activeProfileThreadId: null, activeThreadId: null,
      notificationNavigation: null, liveRailOwner: null, liveTodoRefresh: null,
    });
    localStorage.clear();
  });

  it('M4 the room keeps a live projection written while its older-issued read was in flight', async () => {
    const stale = session(0);
    const live = session(1);
    // Premise: the REST validator accepts the stale body, at the live projection's revision.
    expect(stale.revision).toBe(live.revision);
    expect(await servedOnce({ session: stale }, () => fetchCrewTaskDetail(PARENT)))
      .toEqual({ kind: 'success', response: { session: stale } });
    const read = holdRequest(`/api/crew-tasks/${PARENT}`);
    render(<CrewCollaborationPanel threadId={THREAD} parentId={PARENT} />);
    await waitFor(() => expect(read.issued()).toBe(1));

    // The panel owns P, so the reducer keeps the live detail while the read is in flight.
    deliverLive(live);
    expect(useStore.getState().crewSessionsByParent.get(PARENT)).toBe(live);
    await act(async () => { read.answer({ session: stale }); });
    const room = screen.getByTestId('crew-collaboration-panel');
    await waitFor(() => expect(room).toHaveAttribute('aria-busy', 'false'));

    expect(useStore.getState().crewSessionsByParent.get(PARENT)).toBe(live);
    expect(within(room).getByText('1/2')).toBeInTheDocument();
    expect(read.issued()).toBe(1);
  });

  it('M4 the rooms list keeps a room written live while its older-issued summaries read was in flight', async () => {
    const legacy: RoomSummary = { outputs: 0, steps_total: 3, steps_done: 1, topic: 'Legacy room' };
    const body = { summaries: { [THREAD]: roomOf(session(0)), 'issue1375-fence-legacy': legacy } };
    // Premise: the REST validator accepts the stale summaries.
    expect(await servedOnce(body, () => repairRoomSummaries()))
      .toEqual({ kind: 'success', summaries: body.summaries });
    const thread: AD791aChatThreadView = {
      id: THREAD, title: 'Fenced room', participants: [HOST], created_at: 0, last_active_at: 0,
    };
    useStore.setState({ agents: new Map([[HOST, hostAgent()]]), chatsOpen: true });
    const read = holdRequest('/api/threads/summaries', {
      '/api/threads?include_archived=false&limit=100': { threads: [thread] },
    });
    render(<ChatsPanel />);
    await screen.findByTestId(`chat-row-${THREAD}`);
    await waitFor(() => expect(read.issued()).toBe(1));

    const live = deliverLive(session(1));
    await act(async () => { read.answer(body); });
    // The read applied: it still governs the room the stream did not write after it was issued.
    await waitFor(() => expect(useStore.getState().roomSummariesByThread.get('issue1375-fence-legacy')).toEqual(legacy));

    expect(useStore.getState().roomSummariesByThread.get(THREAD)).toBe(live);
    expect(useStore.getState().crewSessionSummariesByThread.get(THREAD)).toBe(live.session);
    // Only the live summary carries a result line; the stale one has none.
    expect(screen.getByTestId(`room-session-${THREAD}`)).toHaveTextContent('One child complete');
    // R1: a refused room the store still holds is kept, not read again.
    expect(read.issued()).toBe(1);
  });

  it('M4 an opened notification keeps a live projection written while its older-issued context read was in flight', async () => {
    const id = 'e'.repeat(64);
    const context = {
      kind: 'crew_session', notification_id: id, delivery_revision: 1,
      thread: {
        id: THREAD, task_id: PARENT, title: 'Fenced room', participants: [HOST], project_id: null,
        pinned: false, archived: false, personality_override: null, workspace_root: null,
        created_at: 1, last_active_at: 3, preprompt: null, model: null, metadata: {},
      },
      session: session(0),
    };
    const live = session(1);
    // Premise: the REST validator accepts the stale context, at the live projection's revision.
    expect(context.session.revision).toBe(live.revision);
    expect(await servedOnce(context, () => fetchNotificationContext(id))).toEqual({ kind: 'success', context });
    // An open room panel owns P, so the reducer keeps the live detail it parses.
    useStore.setState({ agents: new Map([[HOST, hostAgent()]]), liveCrewOwnerParentId: PARENT });
    const notification: NotificationView = {
      id, agent_id: HOST, agent_type: 'crew_session', department: 'ops',
      notification_type: 'action_required', title: 'Fenced room update', detail: 'd',
      action_url: '', created_at: 0, acknowledged: false,
    };
    const read = holdRequest(`/api/notifications/${id}/context`);
    render(<NotificationCard notification={notification} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open room context: Fenced room update' }));
    await waitFor(() => expect(read.issued()).toBe(1));

    deliverLive(live);
    expect(useStore.getState().crewSessionsByParent.get(PARENT)).toBe(live);
    await act(async () => { read.answer(context); });
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Room context opened.'));

    expect(useStore.getState().crewSessionsByParent.get(PARENT)).toBe(live);
    expect(useStore.getState().activeProfileThreadId).toBe(THREAD);
  });

  it('M4 Start Work keeps a live projection written while its older-issued start request was in flight', async () => {
    const result = {
      disposition: 'resumed', parent_id: PARENT, thread_id: THREAD, state: 'executing',
      facilitator_id: HOST, owner_ids: [HOST], duplicate_resume_count: 0, scheduled: true,
      session: session(0),
    };
    const live = session(1);
    const request = {
      goal: 'Fenced room', success_criteria: ['Done'], expected_deliverable: 'Report', retry_blocked: false,
    };
    // Premise: the start-work validator accepts the stale result, at the live projection's revision.
    expect(result.session.revision).toBe(live.revision);
    expect(await servedOnce(result, () => startRoomWork(THREAD, request))).toEqual(result);
    // An open room panel owns P, so the reducer keeps the live detail it parses.
    useStore.setState({ liveCrewOwnerParentId: PARENT });
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    const start = holdRequest(`/api/threads/${THREAD}/start-work`);
    render(<WorkspaceFilesRail threadId={THREAD} />);
    fireEvent.click(screen.getByTestId('workspace-start-work-open'));
    fireEvent.change(screen.getByTestId('workspace-start-work-goal'), { target: { value: request.goal } });
    fireEvent.change(screen.getByTestId('workspace-start-work-criteria'), { target: { value: 'Done' } });
    fireEvent.change(screen.getByTestId('workspace-start-work-deliverable'), {
      target: { value: request.expected_deliverable },
    });
    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    await waitFor(() => expect(start.issued()).toBe(1));

    deliverLive(live);
    expect(useStore.getState().crewSessionsByParent.get(PARENT)).toBe(live);
    await act(async () => { start.answer(result); });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());

    expect(useStore.getState().crewSessionsByParent.get(PARENT)).toBe(live);
  });

  it('R1 a native room whose first read a raw child assignment fenced reads again instead of going blank', async () => {
    const body = { session: session(1) };
    // Premise: the REST validator accepts the session body.
    expect(await servedOnce(body, () => fetchCrewTaskDetail(PARENT))).toEqual({ kind: 'success', response: body });
    const begin = vi.spyOn(liveReadFence, 'begin');
    try {
      const read = holdFirstRequest(`/api/crew-tasks/${PARENT}`, () => body);
      render(<CrewCollaborationPanel threadId={THREAD} parentId={PARENT} />);
      await waitFor(() => expect(read.issued()).toBe(1));
      expect(begin).toHaveBeenCalledTimes(1);
      const firstRead = begin.mock.results[0].value as number;

      const drops = useStore.getState().liveDropCount;
      act(() => { useStore.getState().handleEvent(rawAssignedChildFrame()); });
      const refresh = useStore.getState().crewParentRefresh;
      // Premise: the frame stamped P after the read was issued, so the fence refuses that read,
      // and, being no projection, it left nothing for P that the room could show instead.
      expect(useStore.getState().liveDropCount).toBe(drops);
      expect(refresh?.parentId).toBe(PARENT);
      expect(refresh!.stamp).toBeGreaterThan(firstRead);
      expect(liveReadFence.accepts(`crew:${PARENT}`, firstRead)).toBe(false);
      expect(useStore.getState().crewSessionsByParent.has(PARENT)).toBe(false);

      await act(async () => { read.answerFirst(body); });

      const room = await screen.findByTestId('crew-collaboration-panel');
      await waitFor(() => expect(room).toHaveAttribute('aria-busy', 'false'));
      expect(within(room).getByText('1/2')).toBeInTheDocument();
      expect(useStore.getState().crewSessionsByParent.get(PARENT)).toEqual(body.session);
      // Exactly one re-read, and it was issued after the frame's stamp.
      expect(read.issued()).toBe(2);
      expect(begin).toHaveBeenCalledTimes(2);
      expect(begin.mock.results[1].value as number).toBeGreaterThan(refresh!.stamp);
    } finally {
      begin.mockRestore();
    }
  });

  it('R1 the rooms list reads again for a room the fence refused after the bounded live map evicted it', async () => {
    const stale = { summaries: { [THREAD]: roomOf(session(0)) } };
    const fresh = { summaries: { [THREAD]: roomOf(session(1)) } };
    // Premise: the REST validator accepts both bodies.
    expect(await servedOnce(stale, () => repairRoomSummaries())).toEqual({ kind: 'success', summaries: stale.summaries });
    expect(await servedOnce(fresh, () => repairRoomSummaries())).toEqual({ kind: 'success', summaries: fresh.summaries });
    const thread: AD791aChatThreadView = {
      id: THREAD, title: 'Fenced room', participants: [HOST], created_at: 0, last_active_at: 0,
    };
    // The live map is at its 256-entry bound, with THREAD as its oldest entry.
    const full = new Map<string, RoomSummary>([[THREAD, roomOf(session(0))]]);
    for (let index = 1; full.size < 256; index += 1) {
      full.set(`issue1375-fence-filler-${index}`, { outputs: 0, steps_total: 0, steps_done: 0, topic: 'Filler' });
    }
    useStore.setState({ agents: new Map([[HOST, hostAgent()]]), chatsOpen: true, roomSummariesByThread: full });
    const begin = vi.spyOn(liveReadFence, 'begin');
    try {
      const read = holdFirstRequest('/api/threads/summaries', () => fresh, {
        '/api/threads?include_archived=false&limit=100': { threads: [thread] },
      });
      render(<ChatsPanel />);
      await screen.findByTestId(`chat-row-${THREAD}`);
      await waitFor(() => expect(read.issued()).toBe(1));
      expect(begin).toHaveBeenCalledTimes(1);
      const firstRead = begin.mock.results[0].value as number;

      // THREAD is rewritten in place, so it stays oldest; a new room's write then evicts it.
      deliverLive(session(1));
      deliverLive({ ...session(0), task_id: 'issue1375-fence-parent-new', thread_id: 'issue1375-fence-thread-new' });
      // Premise: the fence refuses the read for THREAD, and the store no longer holds anything for it.
      expect(liveReadFence.accepts(`room:${THREAD}`, firstRead)).toBe(false);
      expect(useStore.getState().roomSummariesByThread.has(THREAD)).toBe(false);
      expect(useStore.getState().roomSummariesByThread.size).toBe(256);

      await act(async () => { read.answerFirst(stale); });

      // Only the fresh summary carries a result line; the stale one has none.
      expect(await screen.findByTestId(`room-session-${THREAD}`)).toHaveTextContent('One child complete');
      expect(read.issued()).toBe(2);
      expect(begin).toHaveBeenCalledTimes(2);
      expect(begin.mock.results[1].value as number).toBeGreaterThan(firstRead);
    } finally {
      begin.mockRestore();
    }
  });
});
