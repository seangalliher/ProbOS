import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  initialToolProgress, isProgressIdentity, parseToolProgress, reduceToolProgress,
  selectThreadToolProgress,
} from '../liveToolProgress';
import { useStore } from '../useStore';
import type { WSEvent } from '../types';

const generation = 'a'.repeat(32);
const started = 'agentic_tool_call_started';
const completed = 'agentic_tool_call_completed';
const payload = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
  thread_id: 'room-a', agent_id: 'agent-a', run_id: 'b'.repeat(32),
  iteration: 1, tool_call_index: 0, tool_call_id: ' provider/duplicate ', tool_id: 'read_file',
  ...overrides,
});

function frame(type: string, data: Record<string, unknown>, sequence: number, gen = generation): WSEvent {
  return { type, data, timestamp: 1, stream: { generation: gen, sequence } };
}

function snapshot(sequence = 0, gen = generation): void {
  useStore.getState().handleEvent(frame('state_snapshot', {
    agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0,
  }, sequence, gen));
}

function emit(type = started, overrides: Record<string, unknown> = {}, seq?: number): void {
  useStore.getState().handleEvent(frame(type, payload({
    ...(type === completed ? { is_error: false, duration_ms: 12 } : {}), ...overrides,
  }), seq ?? useStore.getState().liveSequence + 1));
}

function selected(thread: string | null = 'room-a', participants: string[] | null = ['agent-a']) {
  return selectThreadToolProgress(useStore.getState().toolProgress, thread, participants);
}

beforeEach(() => {
  useStore.setState(useStore.getInitialState(), true);
  snapshot();
});
afterEach(() => {
  vi.useRealTimers();
  useStore.setState(useStore.getInitialState(), true);
});

describe('exact identities', () => {
  it.each([
    undefined, null, '', ' \t\n', '\u001c\u0085', 2, {}, [], new String('thread'),
    'a'.repeat(129), '\u00e9'.repeat(65), '\ud800', '\udc00', '\ud800a',
  ])('rejects missing, blank, coerced, over-byte-bound or non-UTF8 input %s', value => {
    expect(isProgressIdentity(value)).toBe(false);
    expect(selectThreadToolProgress(
      useStore.getState().toolProgress, value as string, ['agent-a'],
    ).associated).toBe(false);
  });

  it.each([' room exact ', 'a'.repeat(128), '\u00e9'.repeat(64), '\ud83d\ude00'.repeat(32), '\ufeff'])(
    'retains the exact strict UTF8 identity %s', thread => {
      expect(isProgressIdentity(thread)).toBe(true);
      emit(started, { thread_id: thread });
      expect(selected(thread).calls[0].threadId).toBe(thread);
    },
  );

  it.each([
    { iteration: -1 }, { iteration: 1.5 }, { tool_call_index: true },
    { run_id: 'not-a-run' }, { tool_call_id: '' }, { tool_id: {} },
    { agent_id: '' }, { thread_id: 'x'.repeat(129) },
  ])('rejects malformed correlated shapes through frame_shape %s', bad => {
    emit(started, bad);
    expect(selected().calls).toEqual([]);
    expect(selected().incomplete).toBe(true);
    expect(useStore.getState().liveDrops.slice(-1)[0]).toMatchObject({
      gate: 'frame_shape', detail: 'tool_progress_shape',
    });
  });

  it.each([
    { is_error: 'false' }, { duration_ms: -1 }, { duration_ms: NaN }, { duration_ms: Infinity },
  ])('rejects malformed terminal facts %s', bad => {
    emit(completed, bad);
    expect(selected().calls).toEqual([]);
    expect(useStore.getState().liveDropCount).toBe(1);
  });

  it('leaves legacy OFF, unbound and unrelated events unprojected', () => {
    const before = useStore.getState().toolProgress;
    useStore.getState().handleEvent(frame(started, { agent_id: 'agent-a', tool_id: 'read_file', iteration: 1 }, 1));
    const unbound = payload();
    delete unbound.thread_id;
    useStore.getState().handleEvent(frame(started, unbound, 2));
    useStore.getState().handleEvent(frame('AGENTIC_TOOL_CALL_STARTED', payload(), 3));
    expect(useStore.getState().toolProgress).toBe(before);
    expect(parseToolProgress('other', {})).toBe('unbound');
    expect(useStore.getState().liveDropCount).toBe(0);
  });
});

describe('validated existing stream -> bounded thread projection', () => {
  it('retains early observations without guessing a room or participant', () => {
    emit();
    expect(selected(null).calls).toEqual([]);
    expect(selected('room-a', null).associated).toBe(false);
    expect(selected('room-a', []).associated).toBe(false);
    expect(selected('room-a', ['other']).calls).toEqual([]);
    expect(selected('room-b').calls).toEqual([]);
    expect(selected().calls).toHaveLength(1);
    expect(selected().calls[0].status).toBe('started');
  });

  it('separates overlapping runs, participants, iterations and duplicate provider IDs', () => {
    emit();
    emit(started, { tool_call_index: 1 });
    emit(started, { iteration: 2 });
    emit(started, { run_id: 'c'.repeat(32) });
    emit(started, { agent_id: 'agent-b' });
    emit(started, { thread_id: 'room-b' });
    const own = selected();
    expect(own.calls).toHaveLength(4);
    expect(new Set(own.calls.map(call => call.key)).size).toBe(4);
    expect(new Set(own.calls.map(call => call.callId)).size).toBe(1);
    expect(selected('room-a', ['agent-a', 'agent-b']).calls).toHaveLength(5);
    expect(selected('room-b').calls).toHaveLength(1);
  });

  it.each([false, true])('preserves completed/error terminal facts across a late start, error=%s', error => {
    emit(completed, { is_error: error });
    emit();
    const call = selected().calls[0];
    expect(call.status).toBe(error ? 'error' : 'completed');
    expect(call.completionBeforeStart).toBe(true);
    expect(selected().calls).toHaveLength(1);
  });

  it('pairs ordinary completion without exposing arguments, results or error text', () => {
    emit(started, { arguments: 'private-marker' });
    emit(completed, { result: 'private-marker', error: 'private-marker' });
    expect(selected().calls[0]).toMatchObject({ status: 'completed', completionBeforeStart: false });
    expect(JSON.stringify(useStore.getState().toolProgress)).not.toContain('private-marker');
  });

  it.each([{ tool_call_id: 'different' }, { tool_id: 'write_file' }])(
    'records bounded identity-conflict detail and preserves the original call %s', bad => {
      emit();
      emit(completed, bad);
      expect(selected().calls[0]).toMatchObject({ toolId: 'read_file', status: 'completion-unconfirmed' });
      expect(useStore.getState().liveDrops.slice(-1)[0]).toMatchObject({
        gate: 'frame_shape', detail: 'tool_progress_identity',
      });
      expect(useStore.getState().toolProgress.malformed).toBe(1);
    },
  );

  it('does not overwrite conflicting terminal evidence', () => {
    emit(completed);
    emit(completed, { is_error: true });
    expect(selected().calls[0].status).toBe('completed');
    expect(selected().incomplete).toBe(true);
  });

  it('does not mistake a duplicate start or completion for fresh activity', () => {
    emit();
    const before = useStore.getState().toolProgress;
    emit();
    expect(useStore.getState().toolProgress).toBe(before);
    emit(completed);
    const terminal = useStore.getState().toolProgress;
    emit(completed);
    expect(useStore.getState().toolProgress).toBe(terminal);
  });

  it('reports completion unconfirmed at 30 seconds without inventing cancellation', () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    emit();
    vi.advanceTimersByTime(29_999);
    expect(selected().calls[0].status).toBe('started');
    vi.advanceTimersByTime(1);
    expect(selected().calls[0].status).toBe('completion-unconfirmed');
    emit(completed);
    expect(selected().calls[0].status).toBe('completed');
  });

  it.each(['disconnect', 'resync', 'gap', 'malformed'])('discloses %s without deleting terminal facts', loss => {
    useStore.getState().setConnected(true);
    emit();
    emit(completed);
    emit(started, { tool_call_index: 1 });
    if (loss === 'disconnect') useStore.getState().setConnected(false);
    if (loss === 'resync') useStore.getState().handleEvent(frame('resync_required', {}, 4));
    if (loss === 'gap') useStore.getState().handleEvent(frame('unrelated', {}, 5));
    if (loss === 'malformed') emit(completed, { duration_ms: -1 });
    expect(selected().incomplete).toBe(true);
    expect(selected().calls.map(call => call.status)).toEqual(['completed', 'completion-unconfirmed']);
    expect(selected().calls.every(call => !call.fresh)).toBe(true);
  });

  it('rejects stale sequences and generations; a new snapshot preserves but ages observed facts', () => {
    emit(completed);
    emit(started, { tool_call_index: 1 }, 1);
    useStore.getState().handleEvent(frame(started, payload({ tool_call_index: 2 }), 2, 'c'.repeat(32)));
    expect(selected().calls).toHaveLength(1);
    snapshot(0, 'c'.repeat(32));
    expect(selected().calls[0]).toMatchObject({ status: 'completed', fresh: false });
    useStore.getState().handleEvent(frame(started, payload(), 1, 'c'.repeat(32)));
    expect(selected().calls).toHaveLength(2);
    expect(selected().calls[1]).toMatchObject({ status: 'started', fresh: true });
  });

  it('bounds 32 runs by 64 calls and accounts for evicted records honestly', () => {
    for (let run = 1; run <= 33; run += 1) {
      for (let call = 0; call < 65; call += 1) {
        emit(started, { run_id: run.toString(16).padStart(32, '0'), tool_call_index: call });
      }
    }
    const state = useStore.getState().toolProgress;
    expect(state.runs).toHaveLength(32);
    expect(state.runs.every(run => run.calls.length === 64)).toBe(true);
    expect(selected().calls).toHaveLength(32 * 64);
    expect(selected()).toMatchObject({ incomplete: true, omittedRuns: 1, omittedCalls: 33 + 64 });
    expect(selected().calls.slice(-1)[0]).toMatchObject({ status: 'started', fresh: true });
    expect(selected().calls[0]).toMatchObject({ status: 'completion-unconfirmed', fresh: false });
  });

  it('has an empty/unknown initial projection and ignores observations without generation authority', () => {
    const empty = initialToolProgress();
    expect(selectThreadToolProgress(empty, null, null)).toMatchObject({ associated: false, calls: [] });
    const parsed = parseToolProgress(started, payload());
    if (typeof parsed === 'string') throw new Error('valid observation premise');
    expect(reduceToolProgress(empty, { kind: 'observation', generation, observation: parsed, now: 0 })).toBe(empty);
    const installed = reduceToolProgress(empty, { kind: 'snapshot', generation });
    expect(reduceToolProgress(installed, { kind: 'snapshot', generation })).toBe(installed);
  });
});
