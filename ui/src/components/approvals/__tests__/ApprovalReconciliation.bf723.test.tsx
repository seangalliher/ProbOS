/**
 * BF-723: a decided request must not come back, and the badge must go with it.
 *
 * Two independent paths could resurrect a request the Captain had just decided,
 * because the decision only ever existed in `CapabilityRequestPanel`'s own
 * `useState` list. The shared slice was told nothing but "refresh":
 *
 *   1. `refreshPendingApprovals` fell back to `previous.filter(a => a.queue === q)`
 *      whenever a queue's GET failed. So a 503 on the queue just decided
 *      re-kept the very row the Captain had approved — the card was gone from
 *      the centre and the Bridge badge still counted it.
 *   2. An older in-flight GET, issued before the decision and landing after it,
 *      carried the request in its body and wrote it straight back.
 *
 * These tests drive the real panels, the real `ApprovalsCenterPanel` host and
 * the real store, so they cross the whole seam: click Approve -> `onDecided`
 * carries `(queue, id)` -> tombstone recorded -> every later refresh result is
 * reconciled against it. A test of either half alone passes against the defect.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent, within } from '@testing-library/react';

import { useStore } from '../../../store/useStore';
import { ApprovalsCenterPanel } from '../ApprovalsCenterPanel';

const NOW_S = Math.floor(Date.now() / 1000);

const CAPABILITY_ROW = {
  id: 'cap-1',
  agent_id: 'engineering-3',
  kind: 'continue',
  target: 'continue: summarise the incident log',
  rationale: 'cut off after 3 passes',
  work_item_id: null,
  status: 'pending',
  created_at: NOW_S,
  decided_at: null,
  decided_by: '',
  decision_reason: '',
};

const SKILL_ROW = {
  id: 'sk-1',
  agent_id: 'science-2',
  skill_id: 'summarization',
  skill_label: 'Summarization',
  source: 'self',
  justification: 'condense long reports',
  status: 'requested',
  linked_simulation_id: null,
  created_at: NOW_S - 60,
  decided_at: null,
  decided_by: '',
  decision_reason: '',
  pre_metric: null,
  post_metric: null,
};

function okJson(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response;
}

function errorResponse(status: number): Response {
  return { ok: false, status, json: async () => ({}) } as Response;
}

/** Reset every slice these assertions read, including the BF-723 additions. */
function resetApprovalState(): void {
  useStore.setState({
    pendingApprovals: [],
    decidedApprovals: new Set<string>(),
    approvalRequestSeq: 0,
    approvalAppliedSeq: { capability: 0, skill: 0 },
    approvalsCenterOpen: false,
  });
}

beforeEach(() => {
  resetApprovalState();
});

afterEach(() => {
  cleanup();
  resetApprovalState();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('BF-723 a decided request is reconciled centrally, not just locally', () => {
  it('drops the card AND the badge count when that queue 503s right after the decision', async () => {
    /* The reproduction. `capabilityDown` flips the moment the decide POST
     * lands, which is exactly the reference-vessel sequence: the write
     * succeeded, the immediately following read did not. */
    let capabilityDown = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/decide')) {
        capabilityDown = true;
        return okJson({ ok: true });
      }
      if (url.startsWith('/api/capability-requests')) {
        return capabilityDown ? errorResponse(503) : okJson({ requests: [CAPABILITY_ROW] });
      }
      if (url.startsWith('/api/skill-requests')) return okJson({ requests: [SKILL_ROW] });
      return okJson([]);
    });
    vi.stubGlobal('fetch', fetchMock);
    useStore.setState({ approvalsCenterOpen: true });
    await useStore.getState().refreshPendingApprovals();
    expect(useStore.getState().pendingApprovals.map(a => a.id).sort()).toEqual(['cap-1', 'sk-1']);

    render(<ApprovalsCenterPanel />);
    const card = await screen.findByTestId('capability-request-card');

    // Both queues render a card here, so scope the click to the capability one.
    fireEvent.click(within(card).getByText('Approve'));

    // Half one: the card is gone from the centre.
    await waitFor(() => expect(screen.queryByTestId('capability-request-card')).toBeNull());
    // Half two: the shared slice went with it. BOTH, not either — before the
    // fix the failed GET re-kept `cap-1` and the Bridge badge still read 2.
    await waitFor(() =>
      expect(useStore.getState().pendingApprovals.map(a => a.id)).toEqual(['sk-1']),
    );
  });

  it('a delayed older GET still carrying the decided request does not restore it', async () => {
    /* The GET is issued while the request is still pending, the Captain decides
     * during its flight, and it lands afterwards with a body the server had
     * already composed. Nothing about the response is wrong; it is simply
     * describing a world that no longer exists. */
    let releaseCapability: (() => void) | null = null;
    const held = new Promise<void>(resolve => { releaseCapability = resolve; });
    let capabilityCalls = 0;

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/capability-requests') && !url.includes('/decide')) {
        capabilityCalls += 1;
        if (capabilityCalls === 2) await held;
        return okJson({ requests: [CAPABILITY_ROW] });
      }
      if (url.includes('/decide')) return okJson({ ok: true });
      if (url.startsWith('/api/skill-requests')) return okJson({ requests: [] });
      return okJson([]);
    });
    vi.stubGlobal('fetch', fetchMock);

    await useStore.getState().refreshPendingApprovals();
    expect(useStore.getState().pendingApprovals.map(a => a.id)).toEqual(['cap-1']);

    const delayed = useStore.getState().refreshPendingApprovals() as unknown as Promise<void>;
    await waitFor(() => expect(capabilityCalls).toBe(2));

    useStore.getState().recordApprovalDecision('capability', 'cap-1');
    expect(useStore.getState().pendingApprovals).toEqual([]);

    releaseCapability!();
    await delayed;

    expect(useStore.getState().pendingApprovals).toEqual([]);
  });

  it('an out-of-order response for one queue does not clobber a newer one', async () => {
    /* Two refreshes overlap. The first one's capability read is slow; the
     * second returns the current, shorter list. When the first finally lands it
     * is describing an older state of the same queue and must be discarded —
     * the skill queue's newer answer must survive untouched too. */
    let releaseFirst: (() => void) | null = null;
    const held = new Promise<void>(resolve => { releaseFirst = resolve; });
    let capabilityCalls = 0;

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/capability-requests')) {
        capabilityCalls += 1;
        if (capabilityCalls === 1) {
          await held;
          return okJson({ requests: [CAPABILITY_ROW] });
        }
        return okJson({ requests: [] });
      }
      if (url.startsWith('/api/skill-requests')) return okJson({ requests: [SKILL_ROW] });
      return okJson([]);
    });
    vi.stubGlobal('fetch', fetchMock);

    const first = useStore.getState().refreshPendingApprovals() as unknown as Promise<void>;
    await waitFor(() => expect(capabilityCalls).toBe(1));
    await (useStore.getState().refreshPendingApprovals() as unknown as Promise<void>);
    expect(useStore.getState().pendingApprovals.map(a => a.id)).toEqual(['sk-1']);

    releaseFirst!();
    await first;

    expect(useStore.getState().pendingApprovals.map(a => a.id)).toEqual(['sk-1']);
  });

  it('releases a tombstone once the server stops reporting that id', async () => {
    /* A tombstone is a correction to a server that has not caught up yet, not a
     * permanent record. Once the server agrees the request is gone the entry
     * has no work left to do, and keeping it would let the set grow for the
     * lifetime of the session. */
    let pending: unknown[] = [CAPABILITY_ROW];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/capability-requests')) return okJson({ requests: pending });
      if (url.startsWith('/api/skill-requests')) return okJson({ requests: [] });
      return okJson([]);
    });
    vi.stubGlobal('fetch', fetchMock);

    await useStore.getState().refreshPendingApprovals();
    useStore.getState().recordApprovalDecision('capability', 'cap-1');
    expect(useStore.getState().decidedApprovals.size).toBe(1);

    // The server has not caught up: the row is still reported, so the tombstone
    // is still doing work and must be retained.
    await useStore.getState().refreshPendingApprovals();
    expect(useStore.getState().pendingApprovals).toEqual([]);
    expect(useStore.getState().decidedApprovals.size).toBe(1);

    // The server agrees. The tombstone is spent.
    pending = [];
    await useStore.getState().refreshPendingApprovals();
    expect(useStore.getState().decidedApprovals.size).toBe(0);
    expect(useStore.getState().pendingApprovals).toEqual([]);
  });

  it('does not grow the tombstone set without bound across many decisions', async () => {
    /* The unbounded-growth guard. Each decision adds one entry; each refresh in
     * which the server no longer reports it takes that entry away again, so the
     * set tracks outstanding disagreements rather than session history. */
    let pending: Record<string, unknown>[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/capability-requests')) return okJson({ requests: pending });
      if (url.startsWith('/api/skill-requests')) return okJson({ requests: [] });
      return okJson([]);
    });
    vi.stubGlobal('fetch', fetchMock);

    for (let i = 0; i < 25; i += 1) {
      pending = [{ ...CAPABILITY_ROW, id: `cap-${i}` }];
      await useStore.getState().refreshPendingApprovals();
      useStore.getState().recordApprovalDecision('capability', `cap-${i}`);
      pending = [];
      await useStore.getState().refreshPendingApprovals();
    }

    expect(useStore.getState().decidedApprovals.size).toBe(0);
    expect(useStore.getState().pendingApprovals).toEqual([]);
  });

  it('a tombstone is scoped to its queue — the same id in the other queue survives', async () => {
    /* The two queues mint ids independently, so a bare id is not a safe key.
     * Deciding a capability request must not silently swallow a skill request
     * that happens to share its identifier. */
    const SHARED = 'req-1';
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/capability-requests')) {
        return okJson({ requests: [{ ...CAPABILITY_ROW, id: SHARED }] });
      }
      if (url.startsWith('/api/skill-requests')) {
        return okJson({ requests: [{ ...SKILL_ROW, id: SHARED }] });
      }
      return okJson([]);
    });
    vi.stubGlobal('fetch', fetchMock);

    await useStore.getState().refreshPendingApprovals();
    expect(useStore.getState().pendingApprovals).toHaveLength(2);

    useStore.getState().recordApprovalDecision('capability', SHARED);
    await useStore.getState().refreshPendingApprovals();

    const survivors = useStore.getState().pendingApprovals;
    expect(survivors.map(a => a.queue)).toEqual(['skill']);
    expect(survivors[0].id).toBe(SHARED);
  });
});

describe('BF-723 onDecided carries what was decided', () => {
  it('the capability panel reports its queue and the decided id', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/decide')) return okJson({ ok: true });
      if (url.startsWith('/api/capability-requests')) return okJson({ requests: [CAPABILITY_ROW] });
      if (url.startsWith('/api/skill-requests')) return okJson({ requests: [] });
      return okJson([]);
    });
    vi.stubGlobal('fetch', fetchMock);
    useStore.setState({ approvalsCenterOpen: true });
    await useStore.getState().refreshPendingApprovals();

    render(<ApprovalsCenterPanel />);
    await screen.findByTestId('capability-request-card');
    fireEvent.click(screen.getByText('Approve'));

    /* The host records the tombstone from what `onDecided` handed it. Before
     * BF-723 the callback took no arguments at all, so no tombstone was
     * reachable from any decision. */
    await waitFor(() =>
      expect(useStore.getState().decidedApprovals.has('capability\u0000cap-1')).toBe(true),
    );
  });

  it('the skill panel reports its own queue, not the capability one', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/decide')) return okJson({ ok: true });
      if (url.startsWith('/api/capability-requests')) return okJson({ requests: [] });
      if (url.startsWith('/api/skill-requests')) return okJson({ requests: [SKILL_ROW] });
      return okJson([]);
    });
    vi.stubGlobal('fetch', fetchMock);
    useStore.setState({ approvalsCenterOpen: true });
    await useStore.getState().refreshPendingApprovals();

    render(<ApprovalsCenterPanel />);
    await screen.findByTestId('skill-request-card');
    fireEvent.click(screen.getByText('Approve'));

    await waitFor(() =>
      expect(useStore.getState().decidedApprovals.has('skill\u0000sk-1')).toBe(true),
    );
    expect(useStore.getState().decidedApprovals.has('capability\u0000sk-1')).toBe(false);
  });
});
