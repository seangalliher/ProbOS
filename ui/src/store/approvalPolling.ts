import type { ApprovalQueue } from './types';
import { useStore } from './useStore';

const references: Record<ApprovalQueue, number> = { capability: 0, skill: 0 };
let owner: AbortController | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let unsubscribe: (() => void) | null = null;
let generation = 0;

function activeQueues(): ApprovalQueue[] {
  return (['capability', 'skill'] as const).filter(queue => references[queue] > 0);
}

function arm(): void {
  clearTimeout(timer);
  timer = undefined;
  const lifecycle = owner;
  const ticket = generation;
  if (!lifecycle || lifecycle.signal.aborted) return;
  const state = useStore.getState();
  const due = activeQueues()
    .filter(queue => !state.approvalControllers[queue])
    .map(queue => state.approvalPoll[queue].nextAt)
    .filter((time): time is number => time !== null);
  if (!due.length) return;
  timer = setTimeout(() => {
    timer = undefined;
    if (owner !== lifecycle || ticket !== generation || lifecycle.signal.aborted) return;
    void useStore.getState().refreshPendingApprovals({
      queues: activeQueues(), automatic: true, signal: lifecycle.signal,
    });
  }, Math.max(0, Math.min(...due) - Date.now()));
}

/** One lifecycle and schedule, shared by shells, Bridge and standalone panels. */
export function acquireApprovalPolling(queues: readonly ApprovalQueue[]): () => void {
  const unique = [...new Set(queues)];
  if (unique.some(queue => queue !== 'capability' && queue !== 'skill')) throw new Error('Unknown approval queue.');
  if (unique.length === 0) return () => {};
  const first = unique.filter(queue => references[queue] === 0);
  for (const queue of unique) references[queue] += 1;
  if (!owner) {
    owner = new AbortController();
    generation += 1;
    let capabilityEpoch = useStore.getState().capabilityApprovalEpoch;
    let repairEpoch = useStore.getState().liveRepairEpoch;
    const lifecycle = owner;
    unsubscribe = useStore.subscribe(state => {
      const invalidated = capabilityEpoch !== state.capabilityApprovalEpoch || repairEpoch !== state.liveRepairEpoch;
      capabilityEpoch = state.capabilityApprovalEpoch;
      repairEpoch = state.liveRepairEpoch;
      if (invalidated && references.capability > 0 && owner === lifecycle && !lifecycle.signal.aborted) {
        void state.refreshPendingApprovals({ queues: ['capability'], signal: lifecycle.signal });
      }
      arm();
    });
  }
  if (first.length) void useStore.getState().refreshPendingApprovals({ queues: first, signal: owner.signal });
  arm();
  let released = false;
  return () => {
    if (released) return;
    released = true;
    const last = unique.filter(queue => --references[queue] === 0);
    if (activeQueues().length === 0) {
      clearTimeout(timer);
      timer = undefined;
      unsubscribe?.();
      unsubscribe = null;
      const previous = owner;
      owner = null;
      generation += 1;
      previous?.abort();
      useStore.getState().cancelPendingApprovals();
    } else {
      useStore.getState().cancelPendingApprovals(last);
      arm();
    }
  };
}
