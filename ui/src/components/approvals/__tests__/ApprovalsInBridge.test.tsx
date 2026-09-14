/**
 * AD-1201: pending approvals live in the Bridge, and expand to a dedicated centre.
 *
 * BF-710 mounted the two approval panels in a fixed top-right stack at
 * `top: 12, right: 12` — the exact coordinates of the AD-325 BRIDGE toggle,
 * which it covered completely. These tests drive the real store and the real
 * `BridgePanel`, so they fail if the APPROVALS section stops rising with pending
 * work, stops receding without it, acquires a `stationId`, stops opening the
 * centre, stops feeding the BRIDGE badge, or leaks its poll timer.
 *
 * State is supplied through `fetch`, not by seeding the store: BridgePanel owns
 * the single approvals poll and refreshes on mount, so a seeded slice would be
 * overwritten before the first assertion. Driving the real endpoints keeps these
 * tests honest about the path production actually takes.
 *
 * The source-level reachability guard for the whole caller chain (App -> centre
 * -> panels) lives in `src/__tests__/App.bf710.test.tsx`.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent, act, within } from '@testing-library/react';
import { useStore } from '../../../store/useStore';
import { BridgePanel } from '../../BridgePanel';
import { IntentSurface } from '../../IntentSurface';
import { ApprovalsCenterPanel } from '../ApprovalsCenterPanel';
import { RESOURCE_TIMEOUT_MS } from '../../../utils/resourceState';

/** Must match APPROVALS_POLL_INTERVAL_MS in BridgePanel. */
const POLL_MS = 10000;

/** Recent enough that the row's relative time reads as "just now". */
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

function okJson(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

/** Routes each approvals endpoint to its own rows; everything else is empty. */
function approvalsFetch(capability: unknown[], skill: unknown[]) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith('/api/capability-requests')) return okJson({ requests: capability });
    if (url.startsWith('/api/skill-requests')) return okJson({ requests: skill });
    return okJson([]);
  });
}

function approvalCalls(mock: ReturnType<typeof vi.fn>): number {
  return mock.mock.calls.filter((args: unknown[]) => {
    const u = String(args[0]);
    return u.startsWith('/api/capability-requests') || u.startsWith('/api/skill-requests');
  }).length;
}

/** Reset every slice the Bridge reads so only approvals drive the assertions. */
function resetBridgeState() {
  useStore.getState().cancelPendingApprovals();
  const initial = useStore.getInitialState();
  useStore.setState({
    approvalResources: initial.approvalResources,
    approvalPoll: initial.approvalPoll,
    approvalControllers: { capability: null, skill: null },
    approvalIssuedSeq: { capability: 0, skill: 0 },
    approvalRequestSeq: 0,
    approvalAppliedSeq: { capability: 0, skill: 0 },
    decidedApprovals: new Set<string>(),
    pendingApprovals: [],
    agentTasks: [],
    notifications: [],
    missionControlTasks: [],
    wardRoomDmChannels: [],
    wardRoomUnread: {},
    approvalsCenterOpen: false,
  });
}

/** Stub the endpoints, mount the Bridge, and wait for the first poll to land. */
async function mountBridge(capability: unknown[], skill: unknown[]) {
  const fetchMock = approvalsFetch(capability, skill);
  vi.stubGlobal('fetch', fetchMock);
  resetBridgeState();
  const view = render(<BridgePanel open={true} onClose={() => {}} />);
  await waitFor(() =>
    expect(useStore.getState().pendingApprovals.length).toBe(capability.length + skill.length),
  );
  await waitFor(() => expect(Object.values(useStore.getState().approvalResources)
    .every(resource => ['ready', 'empty'].includes(resource.status))).toBe(true));
  return { ...view, fetchMock };
}

beforeEach(() => {
  resetBridgeState();
});

afterEach(() => {
  cleanup();
  resetBridgeState();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('AD-1201 Bridge APPROVALS section', () => {
  it('renders the section with a count when requests are pending', async () => {
    await mountBridge([CAPABILITY_ROW], [SKILL_ROW]);

    expect(await screen.findByText(/Approvals \(2\)/i)).toBeTruthy();
    expect(screen.getAllByTestId('bridge-approval-row').length).toBe(2);
  });

  it('recedes to nothing when no requests are pending', async () => {
    await mountBridge([], []);
    await screen.findByText(/SHUTDOWN/i);

    expect(screen.queryByText(/Approvals \(/i)).toBeNull();
    expect(screen.queryByTestId('bridge-approval-row')).toBeNull();
    // ...and the feed's empty state is still correct.
    expect(screen.getByText(/No activity/i)).toBeTruthy();
  });

  it('suppresses the "No activity" empty state when only approvals are pending', async () => {
    await mountBridge([CAPABILITY_ROW], []);
    await screen.findByText(/Approvals \(1\)/i);

    expect(screen.queryByText(/No activity/i)).toBeNull();
  });

  it('carries no data-station attribute — activity feed, not a command station', async () => {
    const { container } = await mountBridge([CAPABILITY_ROW], []);
    await screen.findByText(/Approvals \(1\)/i);

    /* Every command station renders `data-station`; the feed sections do not.
     * The presence of a station elsewhere proves the attribute is reachable, so
     * its absence on the approvals header is a real signal, not a false pass. */
    expect(container.querySelector('[data-station="communications"]')).toBeTruthy();
    const header = screen.getByText(/Approvals \(1\)/i).closest('[data-station]');
    expect(header).toBeNull();
  });

  it('shows a compact summary per row — the ask, what kind, how long ago', async () => {
    await mountBridge([CAPABILITY_ROW], []);
    await screen.findByText(/Approvals \(1\)/i);

    const row = screen.getByTestId('bridge-approval-row');
    // BF-716: the ASK leads. This assertion used to require the agent id
    // ('engineering-3') in the row, which is what shipped — and the Captain
    // reported the result as unreadable: "CONTINUE counselor_counselor_0_67c601cb".
    // The identifier is not what makes a card actionable, so it is no longer
    // the headline; `target` (BF-709's readable request) is.
    expect(screen.getByTestId('bridge-approval-ask').textContent).toContain(
      'summarise the incident log',
    );
    expect(screen.getByTestId('bridge-approval-kind').textContent).toBe('continue');
    expect(row.textContent).toMatch(/just now|m ago|h ago|d ago/);
    // The approve/deny controls belong in the centre, not the feed.
    expect(row.querySelector('button')).toBeNull();
    expect(row.querySelector('input')).toBeNull();
  });

  it('represents both queues in the section', async () => {
    const { container } = await mountBridge([CAPABILITY_ROW], [SKILL_ROW]);
    await screen.findByText(/Approvals \(2\)/i);

    expect(container.querySelector('[data-queue="capability"]')).toBeTruthy();
    expect(container.querySelector('[data-queue="skill"]')).toBeTruthy();
  });
});

describe('AD-1201 expand opens the approvals centre', () => {
  it('the section expand affordance flips approvalsCenterOpen', async () => {
    await mountBridge([CAPABILITY_ROW], []);
    const header = await screen.findByText(/Approvals \(1\)/i);

    /* BF-724: the header row is now a flex container holding two SIBLING
     * buttons — the disclosure (chevron + title, carrying `aria-expanded`) and
     * the expand affordance. Nesting the expand control inside the disclosure
     * would be interactive content inside a button, which is the same class of
     * defect BF-724 exists to remove. The title's parent is therefore the
     * disclosure button rather than the row, so this walks one level further
     * out. The property asserted below is unchanged, and the mouse path it
     * covers is deliberately kept: `ApprovalsKeyboard.bf724.test.tsx` proves
     * the keyboard path, this one proves the pointer path still works. */
    const expand = header.parentElement?.parentElement
      ?.querySelector('[title="Expand to full view"]');
    expect(expand).toBeTruthy();
    expect(useStore.getState().approvalsCenterOpen).toBe(false);

    fireEvent.click(expand as Element);

    expect(useStore.getState().approvalsCenterOpen).toBe(true);
  });

  it('clicking a summary row opens the centre too', async () => {
    await mountBridge([CAPABILITY_ROW], []);
    await screen.findByText(/Approvals \(1\)/i);

    fireEvent.click(screen.getByTestId('bridge-approval-row'));

    expect(useStore.getState().approvalsCenterOpen).toBe(true);
  });

  it('the centre renders nothing while the flag is false', () => {
    vi.stubGlobal('fetch', approvalsFetch([], []));
    render(<ApprovalsCenterPanel />);

    expect(screen.queryByTestId('approvals-center-panel')).toBeNull();
  });

  it('the centre hosts both request panels and can be closed', async () => {
    vi.stubGlobal('fetch', approvalsFetch([CAPABILITY_ROW], [SKILL_ROW]));
    useStore.setState({ approvalsCenterOpen: true });
    await useStore.getState().refreshPendingApprovals();

    render(<ApprovalsCenterPanel />);

    expect(await screen.findByTestId('capability-request-card')).toBeTruthy();
    expect(await screen.findByTestId('skill-request-card')).toBeTruthy();
    expect(screen.getByText(/APPROVALS \(2\)/i)).toBeTruthy();

    fireEvent.click(screen.getByTestId('approvals-center-close'));
    expect(useStore.getState().approvalsCenterOpen).toBe(false);
  });

  it('shows an empty state in the centre when nothing is pending', async () => {
    vi.stubGlobal('fetch', approvalsFetch([], []));
    useStore.setState({ approvalsCenterOpen: true });

    render(<ApprovalsCenterPanel />);

    expect(await screen.findByTestId('approvals-center-empty')).toBeTruthy();
  });

  it('approving in the centre posts to the decide endpoint and drops the card', async () => {
    let pending: unknown[] = [CAPABILITY_ROW];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/decide')) { pending = []; return okJson({ ok: true }); }
      if (url.startsWith('/api/capability-requests')) return okJson({ requests: pending });
      if (url.startsWith('/api/skill-requests')) return okJson({ requests: [] });
      return okJson([]);
    });
    vi.stubGlobal('fetch', fetchMock);
    useStore.setState({ approvalsCenterOpen: true });
    await useStore.getState().refreshPendingApprovals();

    render(<ApprovalsCenterPanel />);
    await screen.findByTestId('capability-request-card');

    fireEvent.click(screen.getByText('Approve'));

    await waitFor(() => expect(screen.queryByTestId('capability-request-card')).toBeNull());
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url) === '/api/capability-requests/cap-1/decide',
      ),
    ).toBe(true);
    /* `onDecided` re-reads the shared slice, so the Bridge count does not lag
     * behind what the Captain just did. */
    await waitFor(() => expect(useStore.getState().pendingApprovals.length).toBe(0));
  });
});

describe('AD-1201 BRIDGE badge includes pending approvals', () => {
  it('counts approvals alongside attention tasks and unread notifications', async () => {
    vi.stubGlobal('fetch', approvalsFetch([CAPABILITY_ROW], [SKILL_ROW]));
    resetBridgeState();

    render(<IntentSurface />);

    expect(await screen.findByText('BRIDGE (2)')).toBeTruthy();
  });

  it('reads BRIDGE with no count when nothing is pending', async () => {
    vi.stubGlobal('fetch', approvalsFetch([], []));
    resetBridgeState();

    render(<IntentSurface />);

    expect(await screen.findByText('BRIDGE')).toBeTruthy();
  });
});

describe('AD-1201 the approvals poll', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  async function tick(ms: number): Promise<void> {
    await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
  }

  it('fills the shared slice from both queues in one pass', async () => {
    await mountBridge([CAPABILITY_ROW], [SKILL_ROW]);

    const approvals = useStore.getState().pendingApprovals;
    expect(approvals.map(a => a.queue).sort()).toEqual(['capability', 'skill']);
    // Newest first, and the skill row is projected onto the shared shape.
    expect(approvals[0].queue).toBe('capability');
    const skill = approvals.find(a => a.queue === 'skill');
    expect(skill?.target).toBe('Summarization');
    expect(skill?.kind).toBe('self');
    expect(skill?.agent_id).toBe('science-2');
  });

  it('polls once per interval — two endpoint reads per pass, not per render', async () => {
    const { fetchMock } = await mountBridge([CAPABILITY_ROW], []);
    await waitFor(() => expect(approvalCalls(fetchMock)).toBe(2));

    await tick(POLL_MS * 3);

    // mount pass + 3 intervals, 2 endpoints each.
    expect(approvalCalls(fetchMock)).toBe(8);
  });

  it('clears its interval on unmount — no leaked timer', async () => {
    const { unmount, fetchMock } = await mountBridge([], []);
    await waitFor(() => expect(approvalCalls(fetchMock)).toBe(2));

    unmount();
    await tick(POLL_MS * 5);

    expect(approvalCalls(fetchMock)).toBe(2);
  });

  it('keeps the last known list when both queues are unreachable', async () => {
    const { fetchMock } = await mountBridge([CAPABILITY_ROW], []);
    const known = useStore.getState().pendingApprovals;
    expect(known.length).toBe(1);

    vi.spyOn(console, 'warn').mockImplementation(() => {});
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/capability-requests') || url.startsWith('/api/skill-requests')) {
        throw new Error('network down');
      }
      return okJson([]);
    });

    await tick(POLL_MS);

    /* Degrading to zero would silently clear the badge and tell the Captain
     * nothing needs a decision — the opposite of the truth. */
    expect(useStore.getState().pendingApprovals).toEqual(known);
    expect(console.warn).toHaveBeenCalled();
  });

  it('keeps one queue when only the other is unreachable', async () => {
    const { fetchMock } = await mountBridge([], [SKILL_ROW]);
    expect(useStore.getState().pendingApprovals.map(a => a.id)).toEqual(['sk-1']);

    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/skill-requests')) throw new Error('skills down');
      if (url.startsWith('/api/capability-requests')) return okJson({ requests: [CAPABILITY_ROW] });
      return okJson([]);
    });

    await tick(POLL_MS);

    await waitFor(() => {
      const ids = useStore.getState().pendingApprovals.map(a => a.id).sort();
      expect(ids).toEqual(['cap-1', 'sk-1']);
    });
  });
});

describe('issue #1368 shared approval availability', () => {
  const unavailable = () => okJson({
    detail: 'skill request store not available', availability: {
      state: 'unavailable', code: 'skill_requests.unavailable', message: 'Skill requests unavailable', retryable: true,
    },
  }, 503);

  it('shows partial unknown instead of empty, then recovers through the hosted skill refresh', async () => {
    let down = true;
    const transport = vi.fn<typeof fetch>().mockImplementation(async input => {
      const url = String(input);
      if (url.startsWith('/api/skill-requests')) return down ? unavailable() : okJson({ requests: [SKILL_ROW], status: 'pending' });
      if (url.startsWith('/api/capability-requests')) return okJson({ requests: [] });
      return okJson([]);
    });
    vi.stubGlobal('fetch', transport);
    useStore.setState({ approvalsCenterOpen: true });
    render(<><BridgePanel open onClose={() => {}} /><ApprovalsCenterPanel /></>);
    const panel = await screen.findByTestId('skill-request-panel');
    await waitFor(() => expect(within(panel).getByRole('status')).toHaveTextContent('Unavailable.'));
    expect(transport.mock.calls.some(([url]) => String(url).startsWith('/api/skill-requests'))).toBe(true);
    expect(useStore.getState().approvalResources.capability.status).toBe('empty');
    expect(screen.queryByTestId('approvals-center-empty')).toBeNull();
    expect(screen.queryByText('No activity')).toBeNull();
    expect(screen.getAllByRole('status', { name: 'Approval queue freshness' })[0]).toHaveTextContent('Current count unknown.');
    down = false;
    fireEvent.click(within(panel).getByRole('button', { name: 'Refresh skill requests' }));
    expect(await within(panel).findByText('Summarization')).toBeTruthy();
    expect(useStore.getState().pendingApprovals.map(row => row.id)).toEqual(['sk-1']);
    expect(screen.getByTestId('bridge-approval-row')).toHaveTextContent('Summarization');
  });

  it('retains the actual BRIDGE badge count and labels its stale skill queue', async () => {
    let down = false;
    const transport = vi.fn<typeof fetch>().mockImplementation(async input => {
      if (String(input).startsWith('/api/skill-requests')) return down ? unavailable() : okJson({ requests: [SKILL_ROW] });
      if (String(input).startsWith('/api/capability-requests')) return okJson({ requests: [] });
      return okJson([]);
    });
    vi.stubGlobal('fetch', transport);
    render(<IntentSurface />);
    expect(await screen.findByText('BRIDGE (1)')).toBeTruthy();
    down = true;
    await act(async () => { await useStore.getState().refreshPendingApprovals(); });
    expect(screen.getByText('BRIDGE (1)')).toBeTruthy();
    expect(screen.getByRole('status', { name: 'Approval queue freshness' })).toHaveTextContent('Skill: Unavailable.');
    expect(screen.getByRole('status', { name: 'Approval queue freshness' })).toHaveTextContent('Last-known pending: 1. Stale.');
    expect(useStore.getState().approvalResources.skill.stale).toBe(true);
  });

  it.each([401, 403])('clears hosted skill details and the shared count on HTTP %s', async httpStatus => {
    let denied = false;
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockImplementation(async input => {
      if (String(input).startsWith('/api/skill-requests')) return denied
        ? okJson({ detail: 'denied' }, httpStatus) : okJson({ requests: [SKILL_ROW] });
      if (String(input).startsWith('/api/capability-requests')) return okJson({ requests: [] });
      return okJson([]);
    }));
    useStore.setState({ approvalsCenterOpen: true });
    render(<ApprovalsCenterPanel />);
    await screen.findByTestId('skill-request-card');
    denied = true;
    fireEvent.click(screen.getByRole('button', { name: 'Refresh skill requests' }));
    await waitFor(() => expect(screen.getByRole('status', { name: 'Skill requests status' })).toHaveTextContent('Access denied.'));
    expect(screen.queryByTestId('skill-request-card')).toBeNull();
    expect(useStore.getState().pendingApprovals).toEqual([]);
    expect(useStore.getState().approvalResources.skill).toMatchObject({ data: null, observedAt: null, stale: false });
    expect(screen.queryByTestId('approvals-center-empty')).toBeNull();
  });

  it('does not publish a hosted refresh after the center closes, and reentry recovers', async () => {
    let release!: (response: Response) => void;
    const skillSignals: AbortSignal[] = [];
    let held = true;
    const transport = vi.fn<typeof fetch>().mockImplementation((input, init) => {
      if (String(input).startsWith('/api/skill-requests') && held) {
        skillSignals.push(init!.signal!);
        return new Promise<Response>(resolve => { release = resolve; });
      }
      if (String(input).startsWith('/api/skill-requests')) return Promise.resolve(okJson({ requests: [SKILL_ROW] }));
      if (String(input).startsWith('/api/capability-requests')) return Promise.resolve(okJson({ requests: [] }));
      return Promise.resolve(okJson([]));
    });
    vi.stubGlobal('fetch', transport);
    useStore.setState({ approvalsCenterOpen: true });
    render(<ApprovalsCenterPanel />);
    await waitFor(() => expect(skillSignals).toHaveLength(1));
    fireEvent.click(screen.getByRole('button', { name: 'Close Approvals' }));
    expect(skillSignals[0].aborted).toBe(true);
    await act(async () => { release(okJson({ requests: [SKILL_ROW] })); });
    expect(useStore.getState().pendingApprovals).toEqual([]);
    held = false;
    act(() => { useStore.setState({ approvalsCenterOpen: true }); });
    expect(await screen.findByTestId('skill-request-card')).toBeTruthy();
  });

  it.each([401, 403])('removes cached capability cards when the shared queue denies HTTP %s', async httpStatus => {
    let denied = false;
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockImplementation(async input => {
      if (String(input).startsWith('/api/capability-requests')) return denied
        ? okJson({ detail: 'denied' }, httpStatus) : okJson({ requests: [CAPABILITY_ROW] });
      return okJson({ requests: [] });
    }));
    useStore.setState({ approvalsCenterOpen: true });
    render(<ApprovalsCenterPanel />);
    await screen.findByTestId('capability-request-card');
    denied = true;
    fireEvent.click(screen.getByRole('button', { name: 'Refresh approval queues' }));
    await waitFor(() => expect(useStore.getState().approvalResources.capability.status).toBe('unauthorized'));
    expect(screen.queryByTestId('capability-request-card')).toBeNull();
    expect(useStore.getState().pendingApprovals).toEqual([]);
    expect(screen.queryByTestId('approvals-center-empty')).toBeNull();
  });
});

describe('issue #1368 independent Bridge retry ownership', () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });
  const tick = async (milliseconds: number): Promise<void> => {
    await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); });
  };

  it.each(['skill', 'capability'] as const)('pauses failed %s after two retries while its peer keeps polling behind a closed Bridge', async failedQueue => {
    const calls = { capability: 0, skill: 0 };
    let down = true;
    const transport = vi.fn<typeof fetch>().mockImplementation(async input => {
      const queue = String(input).startsWith('/api/skill-requests') ? 'skill'
        : String(input).startsWith('/api/capability-requests') ? 'capability' : null;
      if (!queue) return okJson([]);
      calls[queue] += 1;
      return down && queue === failedQueue ? okJson({ detail: 'queue unavailable' }, 503) : okJson({ requests: [] });
    });
    vi.stubGlobal('fetch', transport);
    const view = render(<BridgePanel open={false} onClose={() => {}} />);
    await tick(0);
    expect(calls).toEqual({ capability: 1, skill: 1 });
    const healthyQueue = failedQueue === 'skill' ? 'capability' : 'skill';
    await tick(9_999);
    expect(calls[failedQueue]).toBe(1);
    await tick(1);
    expect(calls[failedQueue]).toBe(2);
    await tick(19_999);
    expect(calls[failedQueue]).toBe(2);
    await tick(1);
    expect(calls[failedQueue]).toBe(3);
    expect(calls[healthyQueue]).toBe(4);
    await tick(30_000);
    expect(calls[failedQueue]).toBe(3);
    expect(calls[healthyQueue]).toBe(7);
    down = false;
    view.rerender(<BridgePanel open onClose={() => {}} />);
    await tick(0);
    expect(calls[failedQueue]).toBe(4);
    expect(useStore.getState().approvalResources[failedQueue].status).toBe('empty');
    await tick(10_000);
    expect(calls[failedQueue]).toBe(5);
    expect(calls[healthyQueue]).toBe(8);
  });

  it.each([401, 403, 503])('stops denied or typed-disabled skills at HTTP %s while capabilities remain healthy', async httpStatus => {
    const calls = { capability: 0, skill: 0 };
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockImplementation(async input => {
      if (String(input).startsWith('/api/skill-requests')) {
        calls.skill += 1;
        return okJson({ detail: 'skill request store not available', availability: {
          state: 'disabled', code: 'skill_requests.disabled', message: 'Skill requests disabled', retryable: false,
        } }, httpStatus);
      }
      if (String(input).startsWith('/api/capability-requests')) {
        calls.capability += 1;
        return okJson({ requests: [] });
      }
      return okJson([]);
    }));
    render(<BridgePanel open onClose={() => {}} />);
    await tick(60_000);
    expect(calls).toEqual({ capability: 7, skill: 1 });
    expect(useStore.getState().approvalResources.skill.status).toBe(httpStatus === 503 ? 'disabled' : 'unauthorized');
    expect(screen.getByRole('status', { name: 'Approval queue freshness' })).toHaveTextContent('Current count unknown.');
  });

  it('bounds hung skill reads without overlap and does not block capability publication or cadence', async () => {
    const signals: AbortSignal[] = [];
    let capabilityCalls = 0;
    const transport = vi.fn<typeof fetch>().mockImplementation((input, init) => {
      if (String(input).startsWith('/api/skill-requests')) {
        expect(signals.every(signal => signal.aborted)).toBe(true);
        signals.push(init!.signal!);
        return new Promise<Response>(() => {});
      }
      if (String(input).startsWith('/api/capability-requests')) {
        capabilityCalls += 1;
        return Promise.resolve(okJson({ requests: [CAPABILITY_ROW] }));
      }
      return Promise.resolve(okJson([]));
    });
    vi.stubGlobal('fetch', transport);
    const view = render(<BridgePanel open={false} onClose={() => {}} />);
    await tick(0);
    expect(useStore.getState().pendingApprovals.map(row => row.id)).toEqual(['cap-1']);
    await tick(RESOURCE_TIMEOUT_MS - 1);
    expect(signals).toHaveLength(1);
    expect(capabilityCalls).toBe(2);
    await tick(2);
    expect(signals).toHaveLength(2);
    expect(signals[0].aborted).toBe(true);
    view.unmount();
    const countAtUnmount = transport.mock.calls.length;
    await tick(120_000);
    expect(signals.every(signal => signal.aborted)).toBe(true);
    expect(transport).toHaveBeenCalledTimes(countAtUnmount);
    expect(useStore.getState().approvalControllers).toEqual({ capability: null, skill: null });
  });

  it('does not start an extra shared skill poll when the approvals center is hosted', async () => {
    const transport = approvalsFetch([], [SKILL_ROW]);
    vi.stubGlobal('fetch', transport);
    useStore.setState({ approvalsCenterOpen: true });
    render(<><BridgePanel open onClose={() => {}} /><ApprovalsCenterPanel /></>);
    await tick(0);
    const skillReads = () => transport.mock.calls.filter(([input]) => String(input).startsWith('/api/skill-requests')).length;
    const initialReads = skillReads();
    expect(initialReads).toBeGreaterThan(0);
    expect(screen.getByTestId('skill-request-card')).toBeTruthy();
    await tick(30_000);
    expect(skillReads() - initialReads).toBe(3);
  });

  it('continues the shared healthy schedule after a hosted refresh is canceled by closing the center', async () => {
    let hold = false;
    let skillReads = 0;
    const signals: AbortSignal[] = [];
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockImplementation((input, init) => {
      if (String(input).startsWith('/api/skill-requests')) {
        skillReads += 1;
        if (hold) {
          signals.push(init!.signal!);
          return new Promise<Response>(() => {});
        }
        return Promise.resolve(okJson({ requests: skillReads > 2 ? [SKILL_ROW] : [] }));
      }
      if (String(input).startsWith('/api/capability-requests')) return Promise.resolve(okJson({ requests: [] }));
      return Promise.resolve(okJson([]));
    }));
    render(<><BridgePanel open={false} onClose={() => {}} /><ApprovalsCenterPanel /></>);
    await tick(0);
    expect(skillReads).toBe(1);
    expect(useStore.getState().approvalPoll.skill.nextAt).not.toBeNull();
    hold = true;
    act(() => { useStore.setState({ approvalsCenterOpen: true }); });
    await tick(0);
    expect(skillReads).toBe(1);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Refresh approval queues' }));
    await tick(0);
    expect(skillReads).toBe(2);
    expect(signals).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Close Approvals' }));
    hold = false;
    await tick(0);
    expect(signals[0].aborted).toBe(true);
    await tick(10_000);
    expect(skillReads).toBe(3);
    expect(useStore.getState().pendingApprovals.map(row => row.id)).toEqual(['sk-1']);
    expect(screen.getByTestId('bridge-approval-row')).toHaveTextContent('Summarization');
  });
});
