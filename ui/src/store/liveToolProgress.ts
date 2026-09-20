/* AD-1174: bounded observations from the existing ordered event stream only. */

const MAX_RUNS = 32;
const MAX_CALLS = 64;
const UNCONFIRMED_MS = 30_000;
const GENERATION = /^[0-9a-f]{32}$/;
const STARTED = 'agentic_tool_call_started';
const COMPLETED = 'agentic_tool_call_completed';

export interface ToolObservation {
  threadId: string;
  participantId: string;
  runId: string;
  iteration: number;
  index: number;
  callId: string;
  toolId: string;
  terminal: 'completed' | 'error' | null;
}

interface ToolCall extends ToolObservation {
  startedAt: number | null;
  completionBeforeStart: boolean;
  epoch: number;
}

interface ToolRun {
  key: string;
  generation: string;
  threadId: string;
  participantId: string;
  runId: string;
  calls: readonly ToolCall[];
}

export interface ToolProgressState {
  generation: string | null;
  epoch: number;
  runs: readonly ToolRun[];
  incomplete: boolean;
  omittedRuns: number;
  omittedCalls: number;
  malformed: number;
}

export type ToolProgressAction =
  | { kind: 'snapshot'; generation: string }
  | { kind: 'loss'; malformed?: boolean }
  | { kind: 'observation'; generation: string; observation: ToolObservation; now: number };

export interface ThreadToolCall extends ToolObservation {
  key: string;
  startedAt: number | null;
  status: 'started' | 'completed' | 'error' | 'completion-unconfirmed';
  completionBeforeStart: boolean;
  fresh: boolean;
}

export interface ThreadToolProgress {
  associated: boolean;
  calls: readonly ThreadToolCall[];
  incomplete: boolean;
  omittedRuns: number;
  omittedCalls: number;
}

export function initialToolProgress(): ToolProgressState {
  return {
    generation: null, epoch: 0, runs: [], incomplete: false,
    omittedRuns: 0, omittedCalls: 0, malformed: 0,
  };
}

/** Match Python's exact nonblank, strict UTF-8 identity without normalizing it. */
export function isProgressIdentity(value: unknown): value is string {
  if (typeof value !== 'string' || value.length === 0 || value.length > 128
    || !/[^\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/u.test(value)) return false;
  let bytes = 0;
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(++i);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false;
      bytes += 4;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      return false;
    } else {
      bytes += code < 0x80 ? 1 : code < 0x800 ? 2 : 3;
    }
  }
  return bytes <= 128;
}

export function isToolProgressType(type: unknown): boolean {
  return type === STARTED || type === COMPLETED;
}

export function parseToolProgress(
  type: string, data: Record<string, unknown>,
): ToolObservation | 'unbound' | 'malformed' {
  if (!isToolProgressType(type)) return 'unbound';
  // Legacy/OFF and missing provenance do not acquire an agent-only association.
  if (!('run_id' in data) || !('thread_id' in data)) return 'unbound';
  if (!isProgressIdentity(data.thread_id) || !isProgressIdentity(data.agent_id)
    || !isProgressIdentity(data.run_id) || !GENERATION.test(data.run_id)
    || !isProgressIdentity(data.tool_call_id) || !isProgressIdentity(data.tool_id)
    || !Number.isSafeInteger(data.iteration) || (data.iteration as number) < 0
    || !Number.isSafeInteger(data.tool_call_index) || (data.tool_call_index as number) < 0
    || (type === COMPLETED && (typeof data.is_error !== 'boolean'
      || typeof data.duration_ms !== 'number' || !Number.isFinite(data.duration_ms)
      || data.duration_ms < 0))) return 'malformed';
  return {
    threadId: data.thread_id, participantId: data.agent_id, runId: data.run_id,
    iteration: data.iteration as number, index: data.tool_call_index as number,
    callId: data.tool_call_id, toolId: data.tool_id,
    terminal: type === STARTED ? null : data.is_error ? 'error' : 'completed',
  };
}

const increment = (n: number, by = 1): number => Math.min(Number.MAX_SAFE_INTEGER, n + by);

export function reduceToolProgress(
  state: ToolProgressState, action: ToolProgressAction,
): ToolProgressState {
  if (action.kind === 'loss') {
    return {
      ...state, epoch: state.epoch + 1, incomplete: true,
      malformed: increment(state.malformed, action.malformed ? 1 : 0),
    };
  }
  if (action.kind === 'snapshot') {
    if (action.generation === state.generation) return state;
    return {
      ...state, generation: action.generation, epoch: state.epoch + 1,
      incomplete: state.incomplete || state.runs.length > 0,
    };
  }
  if (action.generation !== state.generation) return state;
  const observation = action.observation;
  const key = JSON.stringify([
    action.generation, observation.threadId, observation.participantId, observation.runId,
  ]);
  const existing = state.runs.find(run => run.key === key);
  const call = existing?.calls.find(
    item => item.iteration === observation.iteration && item.index === observation.index,
  );
  if (call && (call.callId !== observation.callId || call.toolId !== observation.toolId
    || (call.terminal !== null && observation.terminal !== null
      && call.terminal !== observation.terminal))) {
    return reduceToolProgress(state, { kind: 'loss', malformed: true });
  }
  // Duplicate and late starts cannot refresh old evidence or undo terminal facts.
  if (call && (observation.terminal === null || call.terminal !== null)) return state;
  const next: ToolCall = {
    ...observation,
    startedAt: call?.startedAt ?? (observation.terminal === null ? action.now : null),
    completionBeforeStart: call?.completionBeforeStart ?? observation.terminal !== null,
    epoch: state.epoch,
  };
  let calls = call
    ? existing!.calls.map(item => item === call ? next : item)
    : [...(existing?.calls ?? []), next];
  let omittedCalls = state.omittedCalls;
  let omittedRuns = state.omittedRuns;
  if (calls.length > MAX_CALLS) {
    omittedCalls = increment(omittedCalls, calls.length - MAX_CALLS);
    calls = calls.slice(-MAX_CALLS);
  }
  const run: ToolRun = {
    key, generation: action.generation, threadId: observation.threadId,
    participantId: observation.participantId, runId: observation.runId, calls,
  };
  let runs = existing
    ? state.runs.map(item => item === existing ? run : item)
    : [...state.runs, run];
  if (runs.length > MAX_RUNS) {
    const removed = runs.slice(0, -MAX_RUNS);
    omittedRuns = increment(omittedRuns, removed.length);
    omittedCalls = increment(omittedCalls, removed.reduce((n, item) => n + item.calls.length, 0));
    runs = runs.slice(-MAX_RUNS);
  }
  const lost = omittedCalls !== state.omittedCalls || omittedRuns !== state.omittedRuns;
  if (lost) next.epoch = state.epoch + 1;
  return {
    ...state, runs, omittedCalls, omittedRuns,
    incomplete: state.incomplete || lost, epoch: state.epoch + (lost ? 1 : 0),
  };
}

export function selectThreadToolProgress(
  state: ToolProgressState,
  threadId: string | null,
  participantIds: readonly string[] | null,
  now: number = Date.now(),
): ThreadToolProgress {
  const associated = isProgressIdentity(threadId) && Array.isArray(participantIds)
    && participantIds.length > 0 && participantIds.every(isProgressIdentity);
  const participants = new Set(associated ? participantIds : []);
  return {
    associated,
    calls: associated ? state.runs.filter(run => run.threadId === threadId
      && participants.has(run.participantId)).flatMap(run => run.calls.map((call): ThreadToolCall => ({
        ...call, key: JSON.stringify([run.key, call.iteration, call.index]),
        fresh: call.epoch === state.epoch && run.generation === state.generation,
        status: call.terminal ?? (call.epoch !== state.epoch
          || call.startedAt === null || now - call.startedAt >= UNCONFIRMED_MS
          ? 'completion-unconfirmed' : 'started'),
      }))) : [],
    incomplete: state.incomplete,
    omittedRuns: state.omittedRuns,
    omittedCalls: state.omittedCalls,
  };
}
