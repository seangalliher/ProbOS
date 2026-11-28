/** BF-933 (#1671): a skill-request queue whose store is disabled is read once and then left alone, quietly.
 *
 * The issue behind this file reported a skill-requests endpoint that answers 503 by design when its store is
 * disabled, read again and again with a console line each time. The tree already stops on a typed-disabled answer
 * (`nextResourcePoll`, `refreshPendingApprovals`) and the existing suites pin the request count
 * (SkillRequestPanel.test.tsx, ApprovalsInBridge.test.tsx). What no case pinned was the console (a typed-disabled
 * read logs nothing), that a plain 503 is bounded and names the queue that failed, and that a re-acquired lease
 * asks once more. These cases are characterization: they pass on the base, and a change that warned for a disabled
 * queue, kept reading it, or stopped reading an enabled one would fail them.
 *
 * The 503 body has the shape the route sends for a disabled store (detail plus availability with state, code,
 * message and retryable); the one request row is invented. No console line, count or timing from the vessel that
 * found the issue is here: this repository is public and its tests hold no vessel data.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { acquireApprovalPolling } from '../approvalPolling';
import { useStore } from '../useStore';
import type { ApprovalQueue } from '../types';

const DISABLED_BODY = {
  detail: 'skill request store not available',
  availability: {
    state: 'disabled',
    code: 'skill_requests.disabled',
    message: 'Disabled. Review configuration with the operator.',
    retryable: false,
  },
};
const PLAIN_503_BODY = { detail: 'skill request store not available' };
const ONE_REQUEST = {
  requests: [
    {
      id: 'sr-1',
      agent_id: 'agent-1',
      skill_id: 'summarization',
      skill_label: 'Summarization',
      source: 'self',
      justification: 'condense long reports',
      status: 'requested',
      linked_simulation_id: null,
      created_at: 1.0,
      decided_at: null,
      decided_by: '',
      decision_reason: '',
      pre_metric: null,
      post_metric: null,
    },
  ],
};

const releases: Array<() => void> = [];
function acquire(queues: readonly ApprovalQueue[]): () => void {
  const release = acquireApprovalPolling(queues);
  releases.push(release);
  return release;
}
function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), { status });
}
/** A fetch that answers the skill queue with `skill()` and the capability queue with an empty actionable list. */
function transport(skill: () => Response): { skill: number; capability: number } {
  const calls = { skill: 0, capability: 0 };
  vi.stubGlobal('fetch', vi.fn<typeof fetch>(async input => {
    if (String(input).startsWith('/api/skill-requests')) {
      calls.skill += 1;
      return skill();
    }
    calls.capability += 1;
    return json({ view: 'actionable', requests: [] }, 200);
  }));
  return calls;
}

beforeEach(() => {
  vi.useFakeTimers();
  useStore.getState().cancelPendingApprovals();
  const initial = useStore.getInitialState();
  useStore.setState({
    approvalResources: initial.approvalResources, approvalPoll: initial.approvalPoll,
    approvalControllers: { capability: null, skill: null }, approvalIssuedSeq: { capability: 0, skill: 0 },
    approvalAppliedSeq: { capability: 0, skill: 0 }, approvalRequestSeq: 0,
    pendingApprovals: [], decidedApprovals: new Set(), capabilityDecidingIds: new Set(),
    capabilityDecisionFeedback: new Map(), capabilityDecisionRevision: 0, capabilityApprovalEpoch: 0, liveRepairEpoch: 0,
  });
});
afterEach(async () => {
  for (const release of releases.splice(0)) release();
  await vi.advanceTimersByTimeAsync(0);
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('BF-933: the skill-request queue under a disabled store', () => {
  it('reads a typed-disabled skill queue once, logs nothing, and leaves the capability cadence alone', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const calls = transport(() => json(DISABLED_BODY, 503));
    acquire(['capability', 'skill']);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(calls.skill).toBe(1);
    expect(calls.capability).toBeGreaterThan(1);
    expect(useStore.getState().approvalResources.skill.status).toBe('disabled');
    expect(useStore.getState().approvalPoll.skill.nextAt).toBeNull();
    expect(warn).not.toHaveBeenCalled();
  });

  it('bounds a plain 503 to three reads, and each warning names the skill queue', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const calls = transport(() => json(PLAIN_503_BODY, 503));
    acquire(['skill']);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(calls.skill).toBe(3);
    expect(useStore.getState().approvalResources.skill.status).toBe('unavailable');
    expect(useStore.getState().approvalPoll.skill.failures).toBe(3);
    expect(warn).toHaveBeenCalledTimes(3);
    expect(String(warn.mock.calls[0][0])).toContain('Approval skill queue read failed');
  });

  it('reads an enabled skill queue every ten seconds and logs nothing', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const calls = transport(() => json(ONE_REQUEST, 200));
    acquire(['skill']);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(calls.skill).toBe(4);
    expect(useStore.getState().approvalResources.skill.status).toBe('ready');
    expect(warn).not.toHaveBeenCalled();
  });

  it('asks a typed-disabled queue once more when a lease is re-acquired, and still logs nothing', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const calls = transport(() => json(DISABLED_BODY, 503));
    const release = acquire(['skill']);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(calls.skill).toBe(1);
    release();
    acquire(['skill']);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(calls.skill).toBe(2);
    expect(warn).not.toHaveBeenCalled();
  });
});
