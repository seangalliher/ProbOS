import { afterEach, describe, expect, it } from 'vitest';
import { useStore } from '../useStore';
import type {
  CrewSessionDetailProjection,
  CrewSessionSummaryProjection,
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