import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { useStore } from '../useStore';
import type {
  CrewSessionDetailProjection,
  CrewSessionRoomSummary,
  CrewSessionSummaryProjection,
  RoomSummary,
} from '../types';

const detail: CrewSessionDetailProjection = {
  task_id: 'parent-1',
  thread_id: 'thread-1',
  goal: 'Prepare report',
  origin: 'captain',
  originator_id: 'captain',
  facilitator_id: 'facilitator-1',
  owner_ids: ['facilitator-1'],
  state: 'discussing',
  revision: 1,
  success_criteria: ['Complete'],
  expected_deliverable: 'Report',
  timestamps: {
    created_at: 1,
    transitioned_at: 1,
    started_at: null,
    first_result_at: null,
    verified_at: null,
    completed_at: null,
  },
  progress: { total: 0, done: 0, failed: 0, active: 0, active_child: null },
  last_result_summary: '',
  blocker: null,
  result: null,
  verification: null,
  duplicate_resume_count: 0,
};

const summary: CrewSessionSummaryProjection = {
  task_id: detail.task_id,
  thread_id: detail.thread_id,
  goal: detail.goal,
  state: detail.state,
  facilitator_id: detail.facilitator_id,
  owner_ids: detail.owner_ids,
  progress: { total: 0, done: 0, failed: 0, active: 0 },
  last_result_summary: '',
  blocker: null,
  needs_attention: false,
  result_artifact_id: null,
  verified_at: null,
};

afterEach(() => {
  useStore.setState({
    crewSessionsByParent: new Map(),
    crewSessionSummariesByThread: new Map(),
  });
});

describe('AD-1132 CrewSession one-shot hydration', () => {
  it('hydrateCrewSession clones the parent map and preserves prior entries', () => {
    const before = useStore.getState().crewSessionsByParent;
    useStore.getState().hydrateCrewSession('parent-1', detail);
    const first = useStore.getState().crewSessionsByParent;
    expect(first).not.toBe(before);
    expect(first.get('parent-1')).toBe(detail);

    const secondDetail = { ...detail, task_id: 'parent-2' };
    useStore.getState().hydrateCrewSession('parent-2', secondDetail);
    const second = useStore.getState().crewSessionsByParent;
    expect(second).not.toBe(first);
    expect(second.get('parent-1')).toBe(detail);
    expect(second.get('parent-2')).toBe(secondDetail);
  });

  it('hydrateCrewSession rejects a mismatched parent without re-keying it', () => {
    const before = useStore.getState().crewSessionsByParent;

    useStore.getState().hydrateCrewSession('outer-parent', detail);

    const after = useStore.getState().crewSessionsByParent;
    expect(after).toBe(before);
    expect(after.has('outer-parent')).toBe(false);
    expect(after.has(detail.task_id)).toBe(false);
  });

  it('hydrateCrewSession refuses a lower revision and accepts same-revision progress', () => {
    useStore.getState().hydrateCrewSession('parent-1', detail);
    useStore.getState().hydrateCrewSession('parent-1', {
      ...detail,
      revision: 0,
      state: 'discussing',
    });
    expect(useStore.getState().crewSessionsByParent.get('parent-1')).toBe(detail);

    const progressed = {
      ...detail,
      progress: { ...detail.progress, done: 1 },
    };
    useStore.getState().hydrateCrewSession('parent-1', progressed);
    expect(useStore.getState().crewSessionsByParent.get('parent-1')).toBe(progressed);
  });

  it('hydrateCrewSessionSummaries builds a new thread-keyed map per response', () => {
    const before = useStore.getState().crewSessionSummariesByThread;
    useStore.getState().hydrateCrewSessionSummaries({ 'thread-1': summary });
    const first = useStore.getState().crewSessionSummariesByThread;
    expect(first).not.toBe(before);
    expect(first.get('thread-1')).toBe(summary);

    const secondSummary = { ...summary, task_id: 'parent-2', thread_id: 'thread-2' };
    useStore.getState().hydrateCrewSessionSummaries({ 'thread-2': secondSummary });
    const second = useStore.getState().crewSessionSummariesByThread;
    expect(second).not.toBe(first);
    expect(second.has('thread-1')).toBe(false);
    expect(second.get('thread-2')).toBe(secondSummary);
  });

  it('hydrateCrewSessionSummaries drops mismatched members and keeps valid siblings', () => {
    const mismatched = { ...summary, thread_id: 'embedded-thread' };

    useStore.getState().hydrateCrewSessionSummaries({
      'outer-thread': mismatched,
      'thread-1': summary,
    });

    const hydrated = useStore.getState().crewSessionSummariesByThread;
    expect(hydrated.has('outer-thread')).toBe(false);
    expect(hydrated.has('embedded-thread')).toBe(false);
    expect(hydrated.get('thread-1')).toBe(summary);
  });

  it('unknown WebSocket events do not mutate either one-shot map', () => {
    useStore.getState().hydrateCrewSession('parent-1', detail);
    useStore.getState().hydrateCrewSessionSummaries({ 'thread-1': summary });
    const parentsBefore = useStore.getState().crewSessionsByParent;
    const summariesBefore = useStore.getState().crewSessionSummariesByThread;

    useStore.getState().handleEvent({
      type: 'crew_session_updated',
      data: { parent_id: 'parent-2', session: { task_id: 'parent-2' } },
      timestamp: 2,
    });

    expect(useStore.getState().crewSessionsByParent).toBe(parentsBefore);
    expect(useStore.getState().crewSessionSummariesByThread).toBe(summariesBefore);
  });
});

// Issue #1375 M4: a crew or room read applies only if it was issued after the key's last live write (I2).
describe('issue #1375 crew hydration fence', () => {
  const GENERATION = 'e'.repeat(32);
  let sequence = 0;

  function session(
    done: number,
    overrides: Partial<CrewSessionDetailProjection> = {},
  ): CrewSessionDetailProjection {
    return {
      ...detail,
      state: 'executing',
      revision: 2,
      timestamps: { ...detail.timestamps, transitioned_at: 2, started_at: 2 },
      progress: {
        total: 2, done, failed: 0, active: 2 - done,
        active_child: { id: 'child-1', title: 'Research', status: 'in_progress', owner_id: 'agent-1' },
      },
      last_result_summary: done > 0 ? 'One child complete' : '',
      ...overrides,
    };
  }

  function roomOf(source: CrewSessionDetailProjection): CrewSessionRoomSummary {
    const { total, done, failed, active } = source.progress;
    return {
      outputs: done,
      steps_total: total,
      steps_done: done,
      topic: source.goal,
      session: {
        ...summary,
        task_id: source.task_id,
        thread_id: source.thread_id,
        state: source.state,
        progress: { total, done, failed, active },
        last_result_summary: source.last_result_summary,
      },
    };
  }

  /** Delivers `source` as a live projection frame and returns the room summary the reducer stored. */
  function writeLive(source: CrewSessionDetailProjection): CrewSessionRoomSummary {
    const room = roomOf(source);
    sequence += 1;
    useStore.getState().handleEvent({
      type: 'crew_session_projection',
      data: {
        parent_id: source.task_id, thread_id: source.thread_id, revision: source.revision,
        session: source, room_summary: room,
      },
      timestamp: 1,
      stream: { generation: GENERATION, sequence },
    });
    // Premise: the production parser accepted the frame, because the reducer stored exactly what it parsed.
    expect(useStore.getState().roomSummariesByThread.get(source.thread_id)).toBe(room);
    return room;
  }

  function clearMaps(): void {
    useStore.setState({
      crewSessionsByParent: new Map(),
      crewSessionSummariesByThread: new Map(),
      roomSummariesByThread: new Map(),
    });
  }

  /** Premise: `stale` parses, shares `live`'s revision, and the two-argument form takes it even over `live`. */
  function expectOnlyTheFenceCanReject(
    stale: CrewSessionDetailProjection,
    live: CrewSessionDetailProjection,
  ): void {
    for (const source of [stale, live]) {
      writeLive(source);
      expect(useStore.getState().crewSessionsByParent.get('parent-1')).toBe(source);
      clearMaps();
    }
    expect(stale.revision).toBe(live.revision);
    useStore.getState().hydrateCrewSession('parent-1', stale);
    expect(useStore.getState().crewSessionsByParent.get('parent-1')).toBe(stale);
    useStore.getState().hydrateCrewSession('parent-1', live);
    useStore.getState().hydrateCrewSession('parent-1', stale);
    expect(useStore.getState().crewSessionsByParent.get('parent-1')).toBe(stale);
    clearMaps();
  }

  beforeEach(() => {
    sequence = 0;
    clearMaps();
    useStore.setState({ liveGeneration: GENERATION, liveSequence: 0, liveCrewOwnerParentId: 'parent-1' });
  });

  afterEach(() => {
    useStore.setState({
      liveGeneration: null,
      liveSequence: 0,
      liveCrewOwnerParentId: null,
      roomSummariesByThread: new Map(),
    });
  });

  it('rejects a same-revision response issued before a newer live projection was written', () => {
    const stale = session(0);
    const live = session(1);
    expectOnlyTheFenceCanReject(stale, live);

    const issuedAt = useStore.getState().beginLiveRead();
    writeLive(live);
    const applied = useStore.getState().hydrateCrewSession('parent-1', stale, issuedAt);

    expect(useStore.getState().crewSessionsByParent.get('parent-1')).toBe(live);
    expect(applied).toBe(false);
  });

  it('accepts same-revision progress from a read issued after the live write', () => {
    const live = session(0);
    const progressed = session(1);
    expectOnlyTheFenceCanReject(live, progressed);

    writeLive(live);
    const issuedAt = useStore.getState().beginLiveRead();
    const applied = useStore.getState().hydrateCrewSession('parent-1', progressed, issuedAt);

    expect(useStore.getState().crewSessionsByParent.get('parent-1')).toBe(progressed);
    expect(applied).toBe(true);
  });

  it('rejects an older-issued concurrent response that resolves last', () => {
    const older = session(0);
    const newer = session(1);
    expectOnlyTheFenceCanReject(older, newer);

    const olderIssuedAt = useStore.getState().beginLiveRead();
    const newerIssuedAt = useStore.getState().beginLiveRead();
    const newerApplied = useStore.getState().hydrateCrewSession('parent-1', newer, newerIssuedAt);
    const olderApplied = useStore.getState().hydrateCrewSession('parent-1', older, olderIssuedAt);

    expect(useStore.getState().crewSessionsByParent.get('parent-1')).toBe(newer);
    expect([newerApplied, olderApplied]).toEqual([true, false]);
  });

  it('room summaries keep a thread written live after the read was issued', () => {
    const secondRoom = (done: number) => session(done, { task_id: 'parent-2', thread_id: 'thread-2' });
    const staleRoom = roomOf(session(0));
    const legacyRoom: RoomSummary = { outputs: 0, steps_total: 3, steps_done: 1, topic: 'Legacy room' };
    const response = { 'thread-1': staleRoom, 'thread-3': legacyRoom };
    // Premise: the two-argument form replaces the whole map, so it would lose both live rooms.
    writeLive(session(1));
    writeLive(secondRoom(1));
    useStore.getState().hydrateRoomSummaries(response);
    expect(useStore.getState().roomSummariesByThread.get('thread-1')).toBe(staleRoom);
    expect(useStore.getState().roomSummariesByThread.has('thread-2')).toBe(false);
    clearMaps();

    // A room written live BEFORE the read was issued is still governed by the read.
    writeLive(session(0, { task_id: 'parent-4', thread_id: 'thread-4' }));
    const issuedAt = useStore.getState().beginLiveRead();
    const liveRoom = writeLive(session(1));
    const newRoom = writeLive(secondRoom(1));
    useStore.getState().hydrateRoomSummaries(response, issuedAt);

    const state = useStore.getState();
    expect(state.roomSummariesByThread.get('thread-1')).toBe(liveRoom);
    expect(state.crewSessionSummariesByThread.get('thread-1')).toBe(liveRoom.session);
    expect(state.roomSummariesByThread.get('thread-2')).toBe(newRoom);
    expect(state.crewSessionSummariesByThread.get('thread-2')).toBe(newRoom.session);
    expect(state.roomSummariesByThread.get('thread-3')).toBe(legacyRoom);
    expect(state.roomSummariesByThread.has('thread-4')).toBe(false);
    expect(state.crewSessionSummariesByThread.has('thread-4')).toBe(false);
  });

  it('an older-issued rooms read that resolves last cannot undo a newer read', () => {
    const staleRoom = roomOf(session(0));
    const staleLegacy: RoomSummary = { outputs: 0, steps_total: 3, steps_done: 1, topic: 'Legacy room' };
    const freshLegacy: RoomSummary = { outputs: 1, steps_total: 3, steps_done: 3, topic: 'Legacy room' };
    const newer = { 'thread-3': freshLegacy };
    const older = { 'thread-1': staleRoom, 'thread-3': staleLegacy };
    // Premise: the two-argument form lets the older response undo the newer one.
    writeLive(session(0));
    useStore.getState().hydrateRoomSummaries(newer);
    useStore.getState().hydrateRoomSummaries(older);
    expect(useStore.getState().roomSummariesByThread.get('thread-1')).toBe(staleRoom);
    expect(useStore.getState().roomSummariesByThread.get('thread-3')).toBe(staleLegacy);
    clearMaps();

    writeLive(session(0));
    const olderIssuedAt = useStore.getState().beginLiveRead();
    const newerIssuedAt = useStore.getState().beginLiveRead();
    useStore.getState().hydrateRoomSummaries(newer, newerIssuedAt);
    useStore.getState().hydrateRoomSummaries(older, olderIssuedAt);

    const state = useStore.getState();
    expect(state.roomSummariesByThread.has('thread-1')).toBe(false);
    expect(state.crewSessionSummariesByThread.has('thread-1')).toBe(false);
    expect(state.roomSummariesByThread.get('thread-3')).toBe(freshLegacy);
  });

  it('a fenced read keeps the thread and revision guards', () => {
    const current = session(1, { revision: 3 });
    writeLive(current);
    const issuedAt = useStore.getState().beginLiveRead();

    const applied = [
      session(1, { revision: 2 }),
      session(1, { revision: 4, thread_id: 'thread-9' }),
      session(1, { revision: 4, task_id: 'parent-9' }),
    ].map(source => useStore.getState().hydrateCrewSession('parent-1', source, issuedAt));

    expect(useStore.getState().crewSessionsByParent.get('parent-1')).toBe(current);
    expect(applied).toEqual([false, false, false]);
  });
});