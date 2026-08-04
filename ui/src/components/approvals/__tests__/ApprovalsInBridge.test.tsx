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
import { render, screen, cleanup, waitFor, fireEvent, act } from '@testing-library/react';
import { useStore } from '../../../store/useStore';
import { BridgePanel } from '../../BridgePanel';
import { IntentSurface } from '../../IntentSurface';
import { ApprovalsCenterPanel } from '../ApprovalsCenterPanel';

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

function okJson(body: unknown) {
  return { ok: true, json: async () => body } as Response;
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
  useStore.setState({
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
  return { ...view, fetchMock };
}

beforeEach(() => {
  resetBridgeState();
});

afterEach(() => {
  cleanup();
  resetBridgeState();
  vi.restoreAllMocks();
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

  it('shows a compact summary per row — who asked, what kind, how long ago', async () => {
    await mountBridge([CAPABILITY_ROW], []);
    await screen.findByText(/Approvals \(1\)/i);

    const row = screen.getByTestId('bridge-approval-row');
    expect(row.textContent).toContain('continue');
    expect(row.textContent).toContain('engineering-3');
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

    const expand = header.parentElement?.querySelector('[title="Expand to full view"]');
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
