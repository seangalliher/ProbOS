/**
 * AD-857: CapabilityRequestPanel tests.
 */
import { describe, it, expect, afterEach, vi, beforeEach } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent, act, within } from '@testing-library/react';
import CapabilityRequestPanel from '../components/capability/CapabilityRequestPanel';
import { ApprovalsCenterPanel } from '../components/approvals/ApprovalsCenterPanel';
import { BridgePanel } from '../components/BridgePanel';
import { useStore, isCapabilityRequestView, isApprovalPayload } from '../store/useStore';
import { RESOURCE_TIMEOUT_MS } from '../utils/resourceState';
import type { CapabilityApprovalView, CapabilityDecisionOutcome } from '../store/types';
import { applyCapabilityDecision, parseCapabilityDecision } from '../store/capabilityApprovals';
import { idleResource } from '../utils/resourceState';
import repairWire from '../../e2e/fixtures/ad1206-repair-approvals.json';

const PENDING: { view: 'actionable'; requests: CapabilityApprovalView[] } = {
  view: 'actionable',
  requests: [
    {
      id: 'req-1',
      agent_id: 'agent-1',
      kind: 'install',
      target: 'numpy',
      rationale: 'need arrays',
      work_item_id: 'wi-123456789012',
      status: 'pending',
      created_at: 1.0,
      decided_at: null,
      decided_by: '',
      decision_reason: '',
      payload: null,
      can_retry_fulfilment: false,
    },
  ],
};

describe('AD-1206 real repair approval wire consumer', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetApprovals();
  });
  afterEach(() => {
    cleanup();
    resetApprovals();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('consumes Python-verified pending -> approved Retry -> fulfilled through the actual component', async () => {
    let posts = 0;
    const transport = vi.fn<typeof fetch>().mockImplementation(async (input, options) => {
      if (options?.method === 'POST') {
        posts += 1;
        return response(posts === 1 ? repairWire.approved : repairWire.fulfilled);
      }
      return response(String(input).startsWith('/api/capability-requests')
        ? repairWire.pending : { requests: [] });
    });
    vi.stubGlobal('fetch', transport);
    await useStore.getState().refreshPendingApprovals();
    render(<CapabilityRequestPanel hosted />);
    expect(screen.getByTestId('capability-request-card')).toHaveTextContent('repair.dispatch');
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await tick();
    expect(posts).toBe(1);
    expect(screen.getByTestId('capability-request-card')).toHaveTextContent('Approved - awaiting fulfilment');
    expect(screen.getByRole('button', { name: 'Retry fulfilment' })).toBeEnabled();
    expect(useStore.getState().approvalResources.capability.data?.requests).toEqual([repairWire.approved.request]);
    expect(useStore.getState().pendingApprovals.map(row => row.id)).toEqual([repairWire.approved.request.id]);
    fireEvent.click(screen.getByRole('button', { name: 'Retry fulfilment' }));
    await tick();
    expect(posts).toBe(2);
    expect(screen.queryByTestId('capability-request-card')).toBeNull();
    expect(useStore.getState().pendingApprovals).toEqual([]);
    expect(useStore.getState().approvalResources.capability.data).toEqual(repairWire.empty);
    for (const [input, options] of transport.mock.calls.filter(([, options]) => options?.method === 'POST')) {
      expect(input).toBe(`/api/capability-requests/${repairWire.approved.request.id}/decide`);
      expect(JSON.parse(String(options?.body))).toEqual({ approve: true, reason: '' });
    }
  });

  it('keeps the Python-verified ordinary action non-replayed and non-retryable', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockImplementation(async (input, options) => response(
      options?.method === 'POST' ? repairWire.ordinary_approved
        : String(input).startsWith('/api/capability-requests') ? repairWire.ordinary_pending : { requests: [] },
    )));
    await useStore.getState().refreshPendingApprovals();
    render(<CapabilityRequestPanel hosted />);
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await tick();
    expect(screen.queryByTestId('capability-request-card')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Retry fulfilment' })).toBeNull();
    expect(useStore.getState().pendingApprovals).toEqual([]);
    const ordinary = repairWire.ordinary_pending.requests[0];
    if (!isCapabilityRequestView(ordinary)) throw new Error('Invalid Python ordinary fixture');
    expect(isCapabilityRequestView({
      ...repairWire.ordinary_approved.request, can_retry_fulfilment: true,
    })).toBe(false);
    expect(() => parseCapabilityDecision({
      ...repairWire.ordinary_approved, fulfilled: true,
      request: { ...repairWire.ordinary_approved.request, status: 'fulfilled' },
    }, ordinary, true)).toThrow();
    expect(() => parseCapabilityDecision({
      ...repairWire.ordinary_approved,
      request: { ...repairWire.ordinary_approved.request, payload: repairWire.approved.request.payload, can_retry_fulfilment: true },
    }, ordinary, true)).toThrow();
  });

  it('requires the exact reserved payload rather than repair-looking prose or parameters', () => {
    const row = repairWire.approved.request;
    for (const payload of [
      null, {}, { ...row.payload, tool_id: 'browser' },
      { ...row.payload, action: 'click' }, { ...row.payload, extra: true },
      { ...row.payload, params: {} }, { ...row.payload, session_id: 'old-session' },
      { ...row.payload, scope_key: '' }, { ...row.payload, thread_id: '\ud800' },
      { ...row.payload, params: { ...row.payload.params, signature: 'short' } },
      { ...row.payload, params: { ...row.payload.params, brief: 'x'.repeat(4000) } },
      { ...row.payload, params: { ...row.payload.params, brief: '\ud800' } },
      { ...row.payload, params: { ...row.payload.params, value: Infinity } },
    ]) {
      expect(isCapabilityRequestView({ ...row, payload })).toBe(false);
    }
    expect(isCapabilityRequestView({
      ...row, payload: { ...row.payload, thread_id: '😀'.repeat(64) },
    })).toBe(true);
  });
});

describe('CapabilityRequestPanel (AD-857)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    resetApprovals();
  });
  afterEach(() => {
    cleanup();
    useStore.setState({ decidedApprovals: new Set<string>() });
    vi.unstubAllGlobals();
  });

  it('renders_pending_card_with_rationale_and_buttons', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => PENDING,
    }));

    render(<CapabilityRequestPanel />);

    await waitFor(() => {
      expect(screen.getByTestId('capability-request-card')).toBeTruthy();
    });
    expect(screen.getByText('need arrays')).toBeTruthy();
    expect(screen.getByText('Approve')).toBeTruthy();
    expect(screen.getByText('Deny')).toBeTruthy();
    expect(screen.getByTestId('linked-work-item')).toBeTruthy();
  });

  it('approve_click_posts_to_decide_endpoint', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => PENDING })
      // The endpoint returns durable fulfilment evidence, not an empty request.
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => decision('fulfilled') });
    vi.stubGlobal('fetch', fetchMock);

    render(<CapabilityRequestPanel />);

    await waitFor(() => {
      expect(screen.getByText('Approve')).toBeTruthy();
    });
    fireEvent.click(screen.getByText('Approve'));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/capability-requests/req-1/decide',
        expect.objectContaining({ method: 'POST' }),
      );
    });
    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body.approve).toBe(true);
  });
});

function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status });
}

function decision(
  status: 'approved' | 'fulfilled' | 'denied', row = PENDING.requests[0],
): CapabilityDecisionOutcome {
  return {
    request: {
      ...row, status, decided_at: 2, decided_by: 'captain',
      can_retry_fulfilment: status === 'approved' && row.kind !== 'action',
    },
    fulfilled: status === 'fulfilled',
  };
}

function deferredResponse(): { promise: Promise<Response>; resolve: (value: Response) => void } {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>(complete => { resolve = complete; });
  return { promise, resolve };
}

function resetApprovals(): void {
  useStore.getState().cancelPendingApprovals();
  const initial = useStore.getInitialState();
  useStore.setState({
    approvalResources: initial.approvalResources,
    approvalPoll: initial.approvalPoll,
    approvalControllers: { capability: null, skill: null },
    approvalIssuedSeq: { capability: 0, skill: 0 },
    approvalAppliedSeq: { capability: 0, skill: 0 },
    approvalRequestSeq: 0,
    capabilityDecisionRevision: 0,
    capabilityApprovalEpoch: 0,
    liveRepairEpoch: 0,
    decidedApprovals: new Set<string>(),
    pendingApprovals: [],
    approvalsCenterOpen: false,
    agentTasks: [], notifications: [], missionControlTasks: [],
    wardRoomDmChannels: [], wardRoomUnread: {},
  });
}

async function tick(milliseconds = 0): Promise<void> {
  await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); });
}

describe('issue #1368 capability resource lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetApprovals();
    vi.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    resetApprovals();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it.each([
    [503, { detail: 'capability request store not available' }, 'Unavailable.'],
    [503, { availability: { state: 'disabled', code: 'capability.disabled', message: 'Disabled', retryable: false } }, 'Disabled.'],
    [401, { detail: 'private diagnostic' }, 'Access denied.'],
    [403, { detail: 'private diagnostic' }, 'Access denied.'],
    [500, { error: 'private diagnostic' }, 'Request failed.'],
    [200, { requests: null }, 'Request failed.'],
    [200, { requests: [{ ...PENDING.requests[0], created_at: '1' }] }, 'Request failed.'],
  ])('renders HTTP %s as explicit resource status', async (status, payload, message) => {
    const transport = vi.fn<typeof fetch>().mockResolvedValue(response(payload, status));
    vi.stubGlobal('fetch', transport);
    render(<CapabilityRequestPanel />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading.');
    await tick();
    expect(transport).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('status')).toHaveTextContent(message);
    expect(screen.queryByText('No capability requests pending.')).toBeNull();
    expect(screen.queryByText(/private diagnostic/)).toBeNull();
    if (message === 'Disabled.' || message === 'Access denied.') {
      await tick(90_000);
      expect(transport).toHaveBeenCalledTimes(1);
    }
  });

  it('shows genuine empty and retains healthy ten-second polling', async () => {
    const transport = vi.fn<typeof fetch>().mockImplementation(async () => response({ view: 'actionable', requests: [] }));
    vi.stubGlobal('fetch', transport);
    render(<CapabilityRequestPanel />);
    await tick();
    expect(screen.getByRole('status')).toHaveTextContent('No capability requests pending.');
    await tick(9_999);
    expect(transport).toHaveBeenCalledTimes(1);
    await tick(1);
    expect(transport).toHaveBeenCalledTimes(2);
  });

  it('retries only at ten and thirty seconds, then recovers on manual refresh', async () => {
    let down = true;
    const transport = vi.fn<typeof fetch>().mockImplementation(async () => down
      ? response({ detail: 'unavailable' }, 503) : response(PENDING));
    vi.stubGlobal('fetch', transport);
    render(<CapabilityRequestPanel />);
    await tick();
    await tick(9_999);
    expect(transport).toHaveBeenCalledTimes(1);
    await tick(1);
    expect(transport).toHaveBeenCalledTimes(2);
    await tick(19_999);
    expect(transport).toHaveBeenCalledTimes(2);
    await tick(1);
    expect(transport).toHaveBeenCalledTimes(3);
    await tick(90_000);
    expect(transport).toHaveBeenCalledTimes(3);
    down = false;
    fireEvent.click(screen.getByRole('button', { name: 'Refresh capability requests' }));
    await tick();
    expect(screen.getByTestId('capability-request-card')).toHaveTextContent('numpy');
    expect(screen.getByRole('status')).toHaveTextContent('Available.');
    await tick(10_000);
    expect(transport).toHaveBeenCalledTimes(5);
  });

  it.each([401, 403, 404, 410])('clears cached requests after HTTP %s', async status => {
    const transport = vi.fn<typeof fetch>().mockResolvedValueOnce(response(PENDING))
      .mockImplementation(async () => response({}, status));
    vi.stubGlobal('fetch', transport);
    render(<CapabilityRequestPanel />);
    await tick();
    expect(screen.getByTestId('capability-request-card')).toBeTruthy();
    await tick(10_000);
    expect(screen.queryByTestId('capability-request-card')).toBeNull();
    expect(screen.getByRole('status')).not.toHaveTextContent('last-known');
  });

  it('labels retained cards stale when a subsequent read fails', async () => {
    const transport = vi.fn<typeof fetch>().mockResolvedValueOnce(response(PENDING))
      .mockImplementation(async () => response({}, 503));
    vi.stubGlobal('fetch', transport);
    render(<CapabilityRequestPanel />);
    await tick();
    expect(screen.getByTestId('capability-request-card')).toBeTruthy();
    await tick(10_000);
    expect(screen.getByTestId('capability-request-card')).toBeTruthy();
    expect(screen.getByRole('status')).toHaveTextContent('Unavailable.');
    expect(screen.getByRole('status')).toHaveTextContent('last-known');
    expect(screen.getByRole('status')).toHaveTextContent('Last successful observation:');
  });

  it('times out hung reads without overlapping, and cancels retry work on unmount', async () => {
    const transport = vi.fn<typeof fetch>().mockImplementation(() => new Promise<Response>(() => {}));
    vi.stubGlobal('fetch', transport);
    const view = render(<CapabilityRequestPanel />);
    await tick(RESOURCE_TIMEOUT_MS - 1);
    expect(transport).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('status')).toHaveTextContent('Loading.');
    await tick(1);
    expect(screen.getByRole('status')).toHaveTextContent('Unavailable.');
    expect((transport.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(true);
    view.unmount();
    const calls = transport.mock.calls.length;
    await tick(90_000);
    expect(transport).toHaveBeenCalledTimes(calls);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('aborts on unmount and ignores late completion', async () => {
    const late = deferredResponse();
    const transport = vi.fn<typeof fetch>().mockReturnValue(late.promise);
    vi.stubGlobal('fetch', transport);
    const view = render(<CapabilityRequestPanel />);
    expect(transport).toHaveBeenCalledTimes(1);
    view.unmount();
    expect((transport.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(true);
    await act(async () => { late.resolve(response(PENDING)); });
    await tick(90_000);
    expect(transport).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('ignores an older read after a newer manual refresh', async () => {
    const late = deferredResponse();
    const transport = vi.fn<typeof fetch>().mockReturnValueOnce(late.promise)
      .mockResolvedValueOnce(response({ view: 'actionable', requests: [] }));
    vi.stubGlobal('fetch', transport);
    render(<CapabilityRequestPanel />);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh capability requests' }));
    await tick();
    expect(transport).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('status')).toHaveTextContent('No capability requests pending.');
    await act(async () => { late.resolve(response(PENDING)); });
    expect(screen.queryByTestId('capability-request-card')).toBeNull();
  });

  it('mounts hosted panels without GETs after the real Bridge retry budget is paused', async () => {
    const transport = vi.fn<typeof fetch>().mockImplementation(async input => String(input).includes('-requests')
      ? response({ detail: 'unavailable' }, 503) : response([]));
    vi.stubGlobal('fetch', transport);
    render(<BridgePanel open={false} onClose={() => {}} />);
    await tick();
    await tick(30_000);
    const capabilityCalls = () => transport.mock.calls.filter(([url]) => String(url).startsWith('/api/capability-requests')).length;
    expect(capabilityCalls()).toBe(3);
    expect(useStore.getState().approvalPoll.capability.nextAt).toBeNull();
    act(() => { useStore.setState({ approvalsCenterOpen: true }); });
    const view = render(<ApprovalsCenterPanel />);
    await tick(60_000);
    expect(capabilityCalls()).toBe(3);
    expect(within(screen.getByTestId('capability-request-panel')).getByRole('status')).toHaveTextContent('Unavailable.');
    expect(screen.queryByTestId('approvals-center-empty')).toBeNull();
    view.rerender(<ApprovalsCenterPanel />);
    await tick();
    expect(capabilityCalls()).toBe(3);
    transport.mockImplementation(async input => String(input).startsWith('/api/capability-requests')
      ? response(PENDING) : response([]));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh capability requests' }));
    await tick();
    expect(capabilityCalls()).toBe(4);
    expect(useStore.getState().pendingApprovals.map(row => row.id)).toEqual(['req-1']);
    expect(screen.getByTestId('capability-request-card')).toHaveTextContent('numpy');
    await tick(10_000);
    expect(capabilityCalls()).toBe(5);
  });

  it.each([false, true])('retains approved unfulfilled central and panel rows with both queues failing (hosted=%s)', async hosted => {
    let down = false;
    const transport = vi.fn<typeof fetch>().mockImplementation(async (input, options) => {
      // This previously pinned removal on fulfilled=false, hiding the only retry.
      if (options?.method === 'POST') { down = true; return response(decision('approved')); }
      if (down) return response({ detail: 'unavailable' }, 503);
      return response(String(input).startsWith('/api/capability-requests') ? PENDING : { requests: [] });
    });
    vi.stubGlobal('fetch', transport);
    await useStore.getState().refreshPendingApprovals();
    expect(useStore.getState().pendingApprovals).toHaveLength(1);
    const decided = vi.fn(() => { void useStore.getState().refreshPendingApprovals(); });
    render(<CapabilityRequestPanel hosted={hosted} onDecided={decided} />);
    await tick();
    expect(screen.getByTestId('capability-request-card')).toBeTruthy();
    fireEvent.change(screen.getByRole('textbox', { name: 'decision reason' }), { target: { value: '  approved scope  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await tick();
    expect(decided).toHaveBeenCalledExactlyOnceWith({ queue: 'capability', id: 'req-1', outcome: decision('approved') });
    expect(useStore.getState().pendingApprovals.map(row => row.id)).toEqual(['req-1']);
    expect(useStore.getState().approvalResources.capability.status).toBe('unavailable');
    expect(useStore.getState().approvalResources.skill.status).toBe('unavailable');
    expect(screen.getByTestId('capability-request-card')).toHaveTextContent('Approved - awaiting fulfilment');
    expect(screen.getByRole('button', { name: 'Retry fulfilment' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Deny' })).toBeNull();
    expect(screen.queryByRole('textbox', { name: 'decision reason' })).toBeNull();
    expect(useStore.getState().decidedApprovals.size).toBe(0);
    const mutations = transport.mock.calls.filter(([, options]) => options?.method === 'POST');
    expect(mutations).toHaveLength(1);
    expect(JSON.parse(String(mutations[0][1]?.body))).toEqual({ approve: true, reason: 'approved scope' });
  });

  it('decides through the actual approvals center even when both subsequent queue reads fail', async () => {
    let down = false;
    const transport = vi.fn<typeof fetch>().mockImplementation(async (input, options) => {
      // HTTP 200 with unfulfilled work must retain the centre's actionable row.
      if (options?.method === 'POST') { down = true; return response(decision('approved')); }
      if (down) return response({ detail: 'unavailable' }, 503);
      return response(String(input).startsWith('/api/capability-requests') ? PENDING : { requests: [] });
    });
    vi.stubGlobal('fetch', transport);
    useStore.setState({ approvalsCenterOpen: true });
    render(<ApprovalsCenterPanel />);
    await tick();
    expect(useStore.getState().pendingApprovals).toHaveLength(1);
    fireEvent.click(within(screen.getByTestId('capability-request-card')).getByRole('button', { name: 'Approve' }));
    await tick();
    expect(useStore.getState().pendingApprovals.map(row => row.id)).toEqual(['req-1']);
    expect(useStore.getState().approvalResources.capability.status).toBe('unavailable');
    expect(useStore.getState().approvalResources.skill.status).toBe('unavailable');
    expect(screen.getByTestId('capability-request-card')).toHaveTextContent('Approved - awaiting fulfilment');
    expect(screen.queryByTestId('approvals-center-empty')).toBeNull();
    expect(transport.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1);
  });

  it('cancels a hosted manual read on unmount without creating a polling loop', async () => {
    const late = deferredResponse();
    const transport = vi.fn<typeof fetch>().mockReturnValue(late.promise);
    vi.stubGlobal('fetch', transport);
    const view = render(<CapabilityRequestPanel hosted />);
    expect(transport).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh capability requests' }));
    expect(transport).toHaveBeenCalledTimes(1);
    expect(useStore.getState().approvalResources.capability.status).toBe('loading');
    view.unmount();
    expect((transport.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(true);
    await act(async () => { late.resolve(response(PENDING)); });
    await tick(60_000);
    expect(transport).toHaveBeenCalledTimes(1);
    expect(useStore.getState().pendingApprovals).toEqual([]);
    expect(useStore.getState().approvalResources.capability.status).toBe('idle');
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([false, true])('blocks a pre-decision pending response from downgrading an approval (hosted=%s)', async hosted => {
    const late = deferredResponse();
    let defer = false;
    const transport = vi.fn<typeof fetch>().mockImplementation(async (input, options) => {
      // The former removal assertion encoded the unfulfilled-as-terminal defect.
      if (options?.method === 'POST') return response(decision('approved'));
      if (!String(input).startsWith('/api/capability-requests')) return response({ requests: [] });
      return defer ? late.promise : response(PENDING);
    });
    vi.stubGlobal('fetch', transport);
    await useStore.getState().refreshPendingApprovals();
    render(<CapabilityRequestPanel hosted={hosted} />);
    await tick();
    expect(screen.getByTestId('capability-request-card')).toBeTruthy();
    defer = true;
    const before = transport.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: 'Refresh capability requests' }));
    await tick();
    expect(transport.mock.calls.length).toBe(before + 1);
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await tick();
    expect(useStore.getState().pendingApprovals.map(row => row.id)).toEqual(['req-1']);
    expect(screen.getByRole('button', { name: 'Retry fulfilment' })).toBeEnabled();
    await act(async () => { late.resolve(response(PENDING)); });
    await tick();
    expect(screen.getByRole('button', { name: 'Retry fulfilment' })).toBeEnabled();
    expect(useStore.getState().pendingApprovals.map(row => row.id)).toEqual(['req-1']);
    expect(useStore.getState().decidedApprovals.size).toBe(0);
  });

  it('requires a denial reason and never automatically retries a failed POST', async () => {
    const transport = vi.fn<typeof fetch>().mockImplementation(async (_input, options) =>
      options?.method === 'POST' ? response({}, 503) : response(PENDING));
    vi.stubGlobal('fetch', transport);
    render(<CapabilityRequestPanel />);
    await tick();
    fireEvent.click(screen.getByRole('button', { name: 'Deny' }));
    expect(screen.getByRole('alert')).toHaveTextContent('A reason is required to deny.');
    expect(transport.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0);
    fireEvent.change(screen.getByRole('textbox', { name: 'decision reason' }), { target: { value: '  out of scope  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Deny' }));
    await tick();
    expect(screen.getByRole('alert')).toHaveTextContent('decision failed (503)');
    await tick(60_000);
    const mutations = transport.mock.calls.filter(([, options]) => options?.method === 'POST');
    expect(mutations).toHaveLength(1);
    expect(JSON.parse(String(mutations[0][1]?.body))).toEqual({ approve: false, reason: 'out of scope' });
    expect(useStore.getState().decidedApprovals.size).toBe(0);
  });

  it('accepts numeric serializer fields and preserves an action payload unchanged', async () => {
    const row = { ...PENDING.requests[0], kind: 'action', payload: { tool: 'browser', arguments: { url: 'https://example.org' } } };
    const payload = { view: 'actionable', requests: [row] };
    expect(isCapabilityRequestView(row)).toBe(true);
    expect(isApprovalPayload('capability', payload)).toBe(true);
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockImplementation(async input => response(
      String(input).startsWith('/api/capability-requests') ? payload : { requests: [] })));
    await useStore.getState().refreshPendingApprovals();
    expect(useStore.getState().approvalResources.capability.data?.requests).toEqual(payload.requests);
    render(<CapabilityRequestPanel hosted />);
    expect(screen.getByTestId('capability-request-card')).toHaveTextContent('action');
  });

  it.each([null, [], {}, { ...PENDING.requests[0], created_at: '1' },
    { ...PENDING.requests[0], work_item_id: 42 }, { ...PENDING.requests[0], payload: [] },
    { ...PENDING.requests[0], decided_at: 'yesterday' }, { ...PENDING.requests[0], rationale: {} },
  ])('rejects malformed capability detail %j', value => {
    expect(isCapabilityRequestView(value)).toBe(false);
  });

  it('requires actionable decision evidence and accepts nullable serializer fields', () => {
    // Pending-only minimal rows cannot establish whether fulfilment is retryable.
    expect(isCapabilityRequestView({ id: 'minimal', agent_id: 'agent', kind: 'install', target: 'numpy', created_at: 1 })).toBe(false);
    expect(isCapabilityRequestView(PENDING.requests[0])).toBe(true);
    expect(isApprovalPayload('capability', { requests: [] })).toBe(false);
    expect(isApprovalPayload('capability', { view: 'actionable', requests: [] })).toBe(true);
  });

  it.each([false, true])('reloads approved work after remount and explicitly retries once (hosted=%s)', async hosted => {
    let row = PENDING.requests[0];
    let fulfilled = false;
    const transport = vi.fn<typeof fetch>().mockImplementation(async (input, options) => {
      if (options?.method === 'POST') {
        const status = row.status === 'pending' ? 'approved' : 'fulfilled';
        const result = decision(status, row);
        row = result.request;
        fulfilled = result.fulfilled;
        return response(result);
      }
      return response(String(input).startsWith('/api/capability-requests')
        ? { view: 'actionable', requests: fulfilled ? [] : [row] } : { requests: [] });
    });
    vi.stubGlobal('fetch', transport);
    await useStore.getState().refreshPendingApprovals();
    let view = render(<CapabilityRequestPanel hosted={hosted} />);
    await tick();
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await tick();
    expect(screen.getByRole('button', { name: 'Retry fulfilment' })).toBeEnabled();
    view.unmount();
    resetApprovals();
    await useStore.getState().refreshPendingApprovals();
    view = render(<CapabilityRequestPanel hosted={hosted} />);
    await tick();
    expect(screen.getByTestId('capability-request-card')).toHaveTextContent('Approved - awaiting fulfilment');
    expect(transport.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Retry fulfilment' }));
    await tick();
    expect(screen.queryByTestId('capability-request-card')).toBeNull();
    expect(useStore.getState().pendingApprovals).toEqual([]);
    expect(useStore.getState().decidedApprovals.has('capability\u0000req-1')).toBe(true);
    const posts = transport.mock.calls.filter(([, options]) => options?.method === 'POST');
    expect(posts).toHaveLength(2);
    expect(JSON.parse(String(posts[1][1]?.body))).toEqual({ approve: true, reason: '' });
    view.unmount();
  });

  it.each([false, true])('removes terminal outcomes even when the next reads fail (hosted=%s)', async hosted => {
    for (const status of ['fulfilled', 'denied', 'action'] as const) {
      resetApprovals();
      const row = status === 'action' ? { ...PENDING.requests[0], kind: 'action' } : PENDING.requests[0];
      let down = false;
      const transport = vi.fn<typeof fetch>().mockImplementation(async (input, options) => {
        if (options?.method === 'POST') {
          down = true;
          return response(decision(status === 'action' ? 'approved' : status, row));
        }
        if (down) return response({}, 503);
        return response(String(input).startsWith('/api/capability-requests')
          ? { view: 'actionable', requests: [row] } : { requests: [] });
      });
      vi.stubGlobal('fetch', transport);
      await useStore.getState().refreshPendingApprovals();
      const view = render(<CapabilityRequestPanel hosted={hosted} onDecided={() => {
        void useStore.getState().refreshPendingApprovals();
      }} />);
      await tick();
      fireEvent.change(screen.getByRole('textbox'), { target: { value: 'not authorized' } });
      fireEvent.click(screen.getByRole('button', { name: status === 'denied' ? 'Deny' : 'Approve' }));
      await tick();
      expect(screen.queryByTestId('capability-request-card')).toBeNull();
      expect(screen.queryByRole('button', { name: 'Retry fulfilment' })).toBeNull();
      expect(useStore.getState().pendingApprovals).toEqual([]);
      expect(useStore.getState().decidedApprovals.has('capability\u0000req-1')).toBe(true);
      expect(useStore.getState().approvalResources.capability.status).toBe('unavailable');
      view.unmount();
    }
  });

  it.each([false, true])('rejects malformed or mismatched decisions without hiding work (hosted=%s)', async hosted => {
    const valid = decision('approved');
    const badBodies: unknown[] = [
      null, {}, { ok: true }, { request: {} }, { fulfilled: false },
      { ...valid, fulfilled: undefined }, { ...valid, fulfilled: 'false' },
      { ...valid, request: { ...valid.request, id: 'other' } },
      { ...valid, request: { ...valid.request, kind: 'build' } },
      { ...valid, request: { ...valid.request, agent_id: 'other' } },
      { ...valid, request: { ...valid.request, target: 'other' } },
      { ...valid, request: { ...valid.request, work_item_id: null } },
      { ...valid, request: { ...valid.request, created_at: 99 } },
      { ...valid, request: { ...valid.request, can_retry_fulfilment: false } },
      { ...valid, request: { ...valid.request, decided_at: null } },
      { ...valid, request: { ...valid.request, decided_by: '' } },
      { ...valid, request: PENDING.requests[0] }, { ...valid, fulfilled: true },
      decision('denied'), { ...decision('fulfilled'), fulfilled: false },
    ];
    const transport = vi.fn<typeof fetch>().mockImplementation(async input => response(
      String(input).startsWith('/api/capability-requests') ? PENDING : { requests: [] }));
    vi.stubGlobal('fetch', transport);
    await useStore.getState().refreshPendingApprovals();
    render(<CapabilityRequestPanel hosted={hosted} />);
    await tick();
    for (const payload of badBodies) {
      transport.mockImplementation(async (_input, options) => response(options?.method === 'POST' ? payload : PENDING));
      fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
      await tick();
      expect(screen.getByRole('alert')).toHaveTextContent(/capability decision response/);
      expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();
      expect(useStore.getState().pendingApprovals.map(row => row.id)).toEqual(['req-1']);
      expect(useStore.getState().decidedApprovals.size).toBe(0);
    }
    transport.mockImplementation(async () => new Response('{', { status: 200 }));
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await tick();
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();
  });

  it.each([false, true])('preserves an approval across a pre-decision empty read, then accepts a fresh empty read (hosted=%s)', async hosted => {
    const late = deferredResponse();
    let defer = false;
    const transport = vi.fn<typeof fetch>().mockImplementation(async (input, options) => {
      if (options?.method === 'POST') return response(decision('approved'));
      if (!String(input).startsWith('/api/capability-requests')) return response({ requests: [] });
      return defer ? late.promise : response(PENDING);
    });
    vi.stubGlobal('fetch', transport);
    await useStore.getState().refreshPendingApprovals();
    render(<CapabilityRequestPanel hosted={hosted} />);
    await tick();
    defer = true;
    fireEvent.click(screen.getByRole('button', { name: 'Refresh capability requests' }));
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await tick();
    await act(async () => { late.resolve(response({ view: 'actionable', requests: [] })); });
    await tick();
    expect(screen.getByRole('button', { name: 'Retry fulfilment' })).toBeEnabled();
    transport.mockImplementation(async () => response({ view: 'actionable', requests: [] }));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh capability requests' }));
    await tick();
    expect(screen.queryByTestId('capability-request-card')).toBeNull();
  });

  it.each([false, true])('does not resurrect completed work from a delayed approval response (hosted=%s)', async hosted => {
    const late = deferredResponse();
    let completed = false;
    const transport = vi.fn<typeof fetch>().mockImplementation(async (input, options) => {
      if (options?.method === 'POST') return late.promise;
      return response(String(input).startsWith('/api/capability-requests')
        ? { view: 'actionable', requests: completed ? [] : PENDING.requests } : { requests: [] });
    });
    vi.stubGlobal('fetch', transport);
    await useStore.getState().refreshPendingApprovals();
    render(<CapabilityRequestPanel hosted={hosted} />);
    await tick();
    const button = screen.getByRole('button', { name: 'Approve' });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(transport.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1);
    completed = true;
    fireEvent.click(screen.getByRole('button', { name: 'Refresh capability requests' }));
    await tick();
    expect(screen.queryByTestId('capability-request-card')).toBeNull();
    await act(async () => { late.resolve(response(decision('approved'))); });
    await tick();
    expect(screen.queryByTestId('capability-request-card')).toBeNull();
    if (hosted) expect(useStore.getState().pendingApprovals).toEqual([]);
  });

  it.each([false, true])('prevents another POST across remount while a decision is in flight (hosted=%s)', async hosted => {
    const late = deferredResponse();
    const transport = vi.fn<typeof fetch>().mockImplementation(async (input, options) => {
      if (options?.method === 'POST') return late.promise;
      return response(String(input).startsWith('/api/capability-requests') ? PENDING : { requests: [] });
    });
    vi.stubGlobal('fetch', transport);
    await useStore.getState().refreshPendingApprovals();
    const first = render(<CapabilityRequestPanel hosted={hosted} />);
    await tick();
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(useStore.getState().capabilityDecidingIds.has('req-1')).toBe(true);
    first.unmount();
    render(<CapabilityRequestPanel hosted={hosted} />);
    await tick();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(transport.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1);
    await act(async () => { late.resolve(response({}, 503)); });
    await tick();
    expect(useStore.getState().capabilityDecidingIds.size).toBe(0);
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();
  });

  it.each([false, true])('replaces an in-flight read after accepted capability events and repairs (hosted=%s)', async hosted => {
    const late = deferredResponse();
    let reads = 0;
    const transport = vi.fn<typeof fetch>().mockImplementation(async input => {
      if (!String(input).startsWith('/api/capability-requests')) return response({ requests: [] });
      reads += 1;
      return reads === 1 ? late.promise : response({
        view: 'actionable', requests: [decision('approved').request],
      });
    });
    vi.stubGlobal('fetch', transport);
    useStore.setState({ liveGeneration: 'a'.repeat(32), liveSequence: 0 });
    if (hosted) render(<BridgePanel open={false} onClose={() => {}} />);
    render(<CapabilityRequestPanel hosted={hosted} />);
    await tick();
    expect(reads).toBe(1);
    act(() => useStore.getState().handleEvent({
      type: 'capability_request_decided', data: { id: 'req-1', status: 'approved' }, timestamp: 2,
      stream: { generation: 'a'.repeat(32), sequence: 1 },
    }));
    await tick();
    expect(reads).toBe(2);
    expect(transport.mock.calls.find(([url]) => String(url).startsWith('/api/capability-requests'))?.[1]?.signal?.aborted).toBe(true);
    expect(screen.getByRole('button', { name: 'Retry fulfilment' })).toBeEnabled();
    await act(async () => { late.resolve(response(PENDING)); });
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    act(() => { useStore.setState({ liveRepairEpoch: 1 }); });
    await tick();
    expect(reads).toBe(3);
    expect(transport.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(0);
  });

  it('rejects non-actionable rows, inconsistent retry flags and duplicate identities', () => {
    for (const row of [
      decision('fulfilled').request, decision('denied').request,
      decision('approved', { ...PENDING.requests[0], kind: 'action' }).request,
      { ...PENDING.requests[0], can_retry_fulfilment: true },
      { ...PENDING.requests[0], status: { toString: () => 'pending' } },
    ]) expect(isApprovalPayload('capability', { view: 'actionable', requests: [row] })).toBe(false);
    expect(isApprovalPayload('capability', { view: 'actionable', requests: [PENDING.requests[0], PENDING.requests[0]] })).toBe(false);
    expect(isApprovalPayload('capability', { view: 'pending', requests: [] })).toBe(false);
    expect(() => parseCapabilityDecision(decision('approved'), PENDING.requests[0], false)).toThrow();
    const action = { ...PENDING.requests[0], kind: 'action' };
    expect(() => parseCapabilityDecision(decision('fulfilled', action), action, true)).toThrow();
    const empty = idleResource<import('../store/types').ApprovalPayload>('capability');
    const terminal = applyCapabilityDecision(empty, new Set(), decision('fulfilled'));
    expect(terminal.resource.data).toBeNull();
    expect(terminal.tombstones.has('capability\u0000req-1')).toBe(true);
    const stale = applyCapabilityDecision(empty, terminal.tombstones, decision('approved'));
    expect(stale.resource.data).toBeNull();
    expect(stale.tombstones).toEqual(terminal.tombstones);
  });
});
