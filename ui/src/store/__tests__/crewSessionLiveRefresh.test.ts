import { afterEach, describe, expect, it } from 'vitest';

import { useStore, type AD791aChatThreadView } from '../useStore';
import type {
  CrewSessionDetailProjection,
  CrewSessionProjectionEventData,
  CrewSessionSummaryProjection,
  WSEvent,
} from '../types';

const GENERATION = 'a'.repeat(32);

function detail(overrides: Partial<CrewSessionDetailProjection> = {}): CrewSessionDetailProjection {
  return {
    task_id: 'parent-1',
    thread_id: 'thread-1',
    goal: 'Prepare report',
    origin: 'captain',
    originator_id: 'captain',
    facilitator_id: 'facilitator-1',
    owner_ids: ['facilitator-1'],
    state: 'executing',
    revision: 2,
    success_criteria: ['Complete'],
    expected_deliverable: 'Report',
    timestamps: {
      created_at: 1, transitioned_at: 2, started_at: 2,
      first_result_at: null, verified_at: null, completed_at: null,
    },
    progress: {
      total: 2, done: 0, failed: 0, active: 2,
      active_child: { id: 'child-1', title: 'Research', status: 'in_progress', owner_id: 'agent-1' },
    },
    last_result_summary: '',
    blocker: null,
    result: null,
    verification: null,
    duplicate_resume_count: 0,
    ...overrides,
  };
}

function summary(source: CrewSessionDetailProjection): CrewSessionSummaryProjection {
  return {
    task_id: source.task_id,
    thread_id: source.thread_id,
    goal: source.goal,
    state: source.state,
    facilitator_id: source.facilitator_id,
    owner_ids: source.owner_ids,
    progress: {
      total: source.progress.total,
      done: source.progress.done,
      failed: source.progress.failed,
      active: source.progress.active,
    },
    last_result_summary: source.last_result_summary,
    blocker: source.blocker === null ? null : {
      reason: source.blocker.reason,
      since: source.blocker.since,
      duration_seconds: source.blocker.duration_seconds,
    },
    needs_attention: source.state === 'blocked_needs_captain',
    result_artifact_id: source.result?.artifact_id ?? null,
    verified_at: source.timestamps.verified_at,
  };
}

function projectionData(source = detail(), outputs = 1): CrewSessionProjectionEventData {
  return {
    parent_id: source.task_id,
    thread_id: source.thread_id,
    revision: source.revision,
    session: source,
    room_summary: {
      outputs,
      steps_total: 2,
      steps_done: 1,
      topic: source.goal,
      session: summary(source),
    },
  };
}

function frame(type: string, data: Record<string, unknown>, sequence: number, generation = GENERATION): WSEvent {
  return { type, data, timestamp: 1, stream: { generation, sequence } };
}

function installSnapshot(sequence = 0, generation = GENERATION): void {
  useStore.getState().handleEvent(frame('state_snapshot', {
    agents: [], connections: [], pools: [], system_mode: 'active',
    tc_n: 0, routing_entropy: 0,
  }, sequence, generation));
}

afterEach(() => {
  useStore.setState({
    liveGeneration: null,
    liveSequence: 0,
    liveRepairEpoch: 0,
    liveThreadRefresh: null,
    liveArtifactRefresh: null,
    liveTodoRefresh: null,
    liveCrewOwnerParentId: null,
    liveRailOwner: null,
    activeProfileAgent: null,
    activeProfileThreadId: null,
    threadIdByAgent: new Map(),
    chatThreads: new Map(),
    crewSessionsByParent: new Map(),
    crewSessionSummariesByThread: new Map(),
    roomSummariesByThread: new Map(),
  });
});

describe('AD-1133 live stream authority and reducer', () => {
  it('ignores deltas before snapshot and from another generation', () => {
    useStore.getState().handleEvent(frame('chat_thread_message_appended', {
      thread_id: 'thread-1', message_id: 'm1', author_id: 'agent-1', role: 'agent', created_at: 2,
    }, 1));
    expect(useStore.getState().liveSequence).toBe(0);
    installSnapshot();
    useStore.getState().handleEvent(frame('chat_thread_message_appended', {
      thread_id: 'thread-1', message_id: 'm1', author_id: 'agent-1', role: 'agent', created_at: 2,
    }, 1, 'b'.repeat(32)));
    expect(useStore.getState().liveSequence).toBe(0);
  });

  it('suppresses duplicate/out-of-order frames and raises one gap repair epoch', () => {
    installSnapshot(4);
    const epoch = useStore.getState().liveRepairEpoch;
    useStore.getState().handleEvent(frame('unknown', {}, 4));
    useStore.getState().handleEvent(frame('unknown', {}, 3));
    expect(useStore.getState().liveSequence).toBe(4);
    useStore.getState().handleEvent(frame('unknown', {}, 7));
    expect(useStore.getState().liveSequence).toBe(7);
    expect(useStore.getState().liveRepairEpoch).toBe(epoch + 1);
  });

  it('processes resync controls before duplicate suppression', () => {
    installSnapshot(5);
    const epoch = useStore.getState().liveRepairEpoch;
    useStore.getState().handleEvent(frame('resync_required', {}, 5));
    expect(useStore.getState().liveRepairEpoch).toBe(epoch + 1);
    expect(useStore.getState().liveSequence).toBe(5);
  });

  it('immutably applies same-revision progress/count changes without state regression', () => {
    useStore.setState({ liveCrewOwnerParentId: 'parent-1' });
    installSnapshot();
    const first = detail();
    useStore.getState().handleEvent(frame(
      'crew_session_projection', projectionData(first) as unknown as Record<string, unknown>, 1,
    ));
    const parentMap = useStore.getState().crewSessionsByParent;
    const roomMap = useStore.getState().roomSummariesByThread;
    const progressed = detail({
      progress: { total: 2, done: 1, failed: 0, active: 1, active_child: first.progress.active_child },
      last_result_summary: 'One child complete',
    });
    useStore.getState().handleEvent(frame(
      'crew_session_projection', projectionData(progressed, 2) as unknown as Record<string, unknown>, 2,
    ));
    expect(useStore.getState().crewSessionsByParent).not.toBe(parentMap);
    expect(useStore.getState().roomSummariesByThread).not.toBe(roomMap);
    expect(useStore.getState().crewSessionsByParent.get('parent-1')?.progress.done).toBe(1);
    expect(useStore.getState().roomSummariesByThread.get('thread-1')?.outputs).toBe(2);

    const sameRevisionRegression = detail({ revision: 2, state: 'discussing' });
    useStore.getState().handleEvent(frame(
      'crew_session_projection',
      projectionData(sameRevisionRegression) as unknown as Record<string, unknown>,
      3,
    ));
    expect(useStore.getState().crewSessionsByParent.get('parent-1')?.state).toBe('executing');

    const lower = detail({ revision: 1, state: 'discussing' });
    useStore.getState().handleEvent(frame(
      'crew_session_projection', projectionData(lower) as unknown as Record<string, unknown>, 4,
    ));
    expect(useStore.getState().crewSessionsByParent.get('parent-1')?.revision).toBe(2);
    expect(useStore.getState().crewSessionsByParent.get('parent-1')?.state).toBe('executing');
  });

  it('updates detail only for the mounted Crew owner while keeping summaries live', () => {
    useStore.setState({ liveCrewOwnerParentId: 'other-parent' });
    installSnapshot();
    useStore.getState().handleEvent(frame(
      'crew_session_projection', projectionData() as unknown as Record<string, unknown>, 1,
    ));
    expect(useStore.getState().crewSessionsByParent.has('parent-1')).toBe(false);
    expect(useStore.getState().crewSessionSummariesByThread.has('thread-1')).toBe(true);
    expect(useStore.getState().roomSummariesByThread.has('thread-1')).toBe(true);

    useStore.setState({ liveCrewOwnerParentId: 'parent-1' });
    useStore.getState().handleEvent(frame(
      'crew_session_projection', projectionData() as unknown as Record<string, unknown>, 2,
    ));
    expect(useStore.getState().crewSessionsByParent.has('parent-1')).toBe(true);
  });

  it('rejects repeated-id/state conflicts as a whole frame', () => {
    installSnapshot();
    const source = projectionData();
    const invalid = {
      ...source,
      room_summary: {
        ...source.room_summary,
        session: {
          ...source.room_summary.session,
          thread_id: 'other-thread',
        },
      },
    };
    useStore.getState().handleEvent(frame(
      'crew_session_projection', invalid as unknown as Record<string, unknown>, 1,
    ));
    expect(useStore.getState().liveSequence).toBe(0);
    expect(useStore.getState().crewSessionsByParent.size).toBe(0);
  });

  it('updates an existing thread and targets transcript refresh only for the active owner', () => {
    const thread: AD791aChatThreadView = {
      id: 'thread-1', title: 'Room', participants: ['agent-1'],
      created_at: 1, last_active_at: 1,
    };
    useStore.setState({
      activeProfileAgent: 'agent-1',
      threadIdByAgent: new Map([['agent-1', 'thread-1']]),
      chatThreads: new Map([['thread-1', thread]]),
    });
    installSnapshot();
    const before = useStore.getState().chatThreads;
    useStore.getState().handleEvent(frame('chat_thread_message_appended', {
      thread_id: 'thread-1', message_id: 'message-1', author_id: 'agent-1', role: 'agent', created_at: 9,
    }, 1));
    expect(useStore.getState().chatThreads).not.toBe(before);
    expect(useStore.getState().chatThreads.get('thread-1')?.last_active_at).toBe(9);
    expect(useStore.getState().liveThreadRefresh).toEqual({ threadId: 'thread-1', requestId: 'message-1' });

    useStore.setState({ activeProfileAgent: null, liveThreadRefresh: null });
    useStore.getState().handleEvent(frame('chat_thread_message_appended', {
      thread_id: 'thread-1', message_id: 'message-2', author_id: 'agent-1', role: 'agent', created_at: 10,
    }, 2));
    expect(useStore.getState().liveThreadRefresh).toBeNull();
  });

  it('targets artifact and Todo refresh only to the matching expanded rail owner', () => {
    useStore.setState({ liveRailOwner: { threadId: 'thread-1', parentId: 'parent-1' } });
    installSnapshot();
    useStore.getState().handleEvent(frame('artifact_version_added', {
      thread_id: 'thread-1', artifact_id: 'artifact-1', version: 1, created_at: 2,
    }, 1));
    expect(useStore.getState().liveArtifactRefresh).toEqual({
      threadId: 'thread-1', requestId: 'artifact-1',
    });
    useStore.getState().handleEvent(frame(
      'crew_session_projection', projectionData() as unknown as Record<string, unknown>, 2,
    ));
    expect(useStore.getState().liveTodoRefresh).toEqual({ parentId: 'parent-1', requestId: 2 });
  });

  it('does not let stale effect cleanup clear a newer identical owner claim', () => {
    const state = useStore.getState();
    const firstCrew = state.claimLiveCrewOwner('parent-1');
    const secondCrew = state.claimLiveCrewOwner('parent-1');
    state.releaseLiveCrewOwner('parent-1', firstCrew);
    expect(useStore.getState().liveCrewOwnerParentId).toBe('parent-1');
    state.releaseLiveCrewOwner('parent-1', secondCrew);
    expect(useStore.getState().liveCrewOwnerParentId).toBeNull();

    const owner = { threadId: 'thread-1', parentId: 'parent-1' };
    const firstRail = state.claimLiveRailOwner(owner);
    const secondRail = state.claimLiveRailOwner(owner);
    state.releaseLiveRailOwner(owner, firstRail);
    expect(useStore.getState().liveRailOwner).toEqual(owner);
    state.releaseLiveRailOwner(owner, secondRail);
    expect(useStore.getState().liveRailOwner).toBeNull();
  });
});