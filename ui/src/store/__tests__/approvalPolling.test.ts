import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';
import { createElement } from 'react';
import { acquireApprovalPolling } from '../approvalPolling';
import { useStore } from '../useStore';
import type { ApprovalQueue, CapabilityApprovalView } from '../types';
import { RESOURCE_TIMEOUT_MS } from '../../utils/resourceState';

vi.mock('../../CompactApp', () => ({ default: () => null }));
vi.mock('../../pwa/register', () => ({ registerServiceWorker: vi.fn(async () => {}) }));
vi.mock('react-dom/client', async importOriginal => {
  const original = await importOriginal<typeof import('react-dom/client')>();
  return { ...original, createRoot: (container: Element | DocumentFragment) =>
    container === null ? { render: () => {}, unmount: () => {} } : original.createRoot(container) };
});

const releases: Array<() => void> = [];
function acquire(queues: readonly ApprovalQueue[]): () => void {
  const release = acquireApprovalPolling(queues);
  releases.push(release);
  return release;
}
function response(input: RequestInfo | URL): Response {
  return new Response(JSON.stringify(String(input).includes('capability')
    ? { view: 'actionable', requests: [] } : { requests: [] }), { status: 200 });
}
async function settle(): Promise<void> { await act(async () => { await vi.advanceTimersByTimeAsync(0); }); }
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
  cleanup();
  for (const release of releases.splice(0)) release();
  await settle();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('AD-1216 reference-counted approval polling owner', () => {
  it('has one subscription and schedule across desktop, compact, mobile, Bridge and standalone leases', async () => {
    const transport = vi.fn<typeof fetch>(async input => response(input));
    vi.stubGlobal('fetch', transport);
    const subscribe = vi.spyOn(useStore, 'subscribe');
    const desktop = acquire(['capability', 'skill']);
    const compact = acquire(['capability']);
    const mobile = acquire(['capability']);
    const bridge = acquire(['capability', 'skill']);
    const standalone = acquire(['capability']);
    await settle();
    expect(transport).toHaveBeenCalledTimes(2);
    expect(subscribe).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(transport).toHaveBeenCalledTimes(4);
    desktop(); desktop(); compact(); mobile(); bridge();
    await settle();
    expect(vi.getTimerCount()).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(transport).toHaveBeenCalledTimes(5);
    expect(String(transport.mock.calls[4][0])).toContain('capability');
    standalone();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('aborts only the last released queue GET, and releases are idempotent', async () => {
    const transport = vi.fn<typeof fetch>(() => new Promise(() => {}));
    vi.stubGlobal('fetch', transport);
    const capability = acquire(['capability']);
    const skill = acquire(['skill']);
    expect(transport).toHaveBeenCalledTimes(2);
    capability(); capability();
    expect(transport.mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(transport.mock.calls[1][1]?.signal?.aborted).toBe(false);
    await settle();
    skill();
    expect(transport.mock.calls[1][1]?.signal?.aborted).toBe(true);
    await settle();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('cancels selected shared reads while the compatible no-argument form cancels both', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>(() => new Promise(() => {})));
    acquire(['capability', 'skill']);
    const { capability, skill } = useStore.getState().approvalControllers;
    useStore.getState().cancelPendingApprovals(['capability']);
    expect(capability?.signal.aborted).toBe(true);
    expect(skill?.signal.aborted).toBe(false);
    useStore.getState().cancelPendingApprovals();
    expect(skill?.signal.aborted).toBe(true);
  });
  it('invalidates capability reads on capability and repair epochs, not skill', async () => {
    const transport = vi.fn<typeof fetch>(async input => response(input));
    vi.stubGlobal('fetch', transport);
    acquire(['capability', 'skill']);
    await settle();
    useStore.setState({ capabilityApprovalEpoch: 1 });
    await settle();
    useStore.setState({ liveRepairEpoch: 1 });
    await settle();
    expect(transport.mock.calls.filter(([input]) => String(input).includes('capability'))).toHaveLength(3);
    expect(transport.mock.calls.filter(([input]) => String(input).includes('skill'))).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(1);
  });
  it('cannot rearm after teardown or let a previous lifecycle replace a newer read', async () => {
    let old!: (value: Response) => void;
    const transport = vi.fn<typeof fetch>().mockImplementationOnce(() => new Promise(resolve => { old = resolve; }))
      .mockImplementation(async input => response(input));
    vi.stubGlobal('fetch', transport);
    const release = acquire(['capability']);
    release();
    expect(transport.mock.calls[0][1]?.signal?.aborted).toBe(true);
    const nextRelease = acquire(['capability']);
    await settle();
    const generation = useStore.getState().approvalAppliedSeq.capability;
    old(new Response('{}', { status: 503 }));
    await settle();
    expect(useStore.getState().approvalAppliedSeq.capability).toBe(generation);
    expect(useStore.getState().approvalResources.capability.status).toBe('empty');
    expect(vi.getTimerCount()).toBe(1);
    nextRelease();
    await settle();
    useStore.setState({ capabilityApprovalEpoch: 100, liveRepairEpoch: 100 });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(transport).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
  });
  it('retains the 15-second GET timeout and existing bounded retry schedule', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const transport = vi.fn<typeof fetch>(() => new Promise(() => {}));
    vi.stubGlobal('fetch', transport);
    acquire(['capability']);
    await vi.advanceTimersByTimeAsync(RESOURCE_TIMEOUT_MS - 1);
    expect(transport).toHaveBeenCalledTimes(1);
    expect(useStore.getState().approvalResources.capability.status).toBe('loading');
    await vi.advanceTimersByTimeAsync(RESOURCE_TIMEOUT_MS * 3);
    expect(transport).toHaveBeenCalledTimes(3);
    expect(useStore.getState().approvalResources.capability.status).toBe('unavailable');
    expect(useStore.getState().approvalPoll.capability.failures).toBe(3);
    expect(vi.getTimerCount()).toBe(0);
    expect(warn).toHaveBeenCalledTimes(3);
  });
  it('does not poll an unauthorized queue and reacquisition explicitly refreshes it', async () => {
    const transport = vi.fn<typeof fetch>(async () => new Response('{}', { status: 403 }));
    vi.stubGlobal('fetch', transport);
    const release = acquire(['capability']);
    await settle();
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(transport).toHaveBeenCalledTimes(1);
    release();
    acquire(['capability']);
    await settle();
    expect(transport).toHaveBeenCalledTimes(2);
  });
  it('does not abort an already submitted POST or discard tombstones and feedback', async () => {
    const request: CapabilityApprovalView = {
      id: 'req-poll', agent_id: 'agent-a', kind: 'install', target: 'numpy', rationale: 'arrays',
      work_item_id: null, status: 'pending', created_at: 10, decided_at: null, decided_by: '',
      decision_reason: '', payload: null, can_retry_fulfilment: false,
    };
    let complete!: (value: Response) => void;
    const transport = vi.fn<typeof fetch>(async (_input, init) => init?.method === 'POST'
      ? new Promise(resolve => { complete = resolve; })
      : new Response(JSON.stringify({ view: 'actionable', requests: [request] }), { status: 200 }));
    vi.stubGlobal('fetch', transport);
    const release = acquire(['capability']);
    await settle();
    const pending = useStore.getState().decideCapabilityRequest(structuredClone(request), { action: 'approve', reason: '' });
    await settle();
    expect(transport.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
    release();
    expect(transport.mock.calls[2][1]?.signal).toBeUndefined();
    complete(new Response(JSON.stringify({
      request: { ...request, status: 'fulfilled', decided_at: 20, decided_by: 'captain' }, fulfilled: true,
    }), { status: 200 }));
    await pending;
    expect(useStore.getState().capabilityDecisionFeedback.has(request.id)).toBe(true);
    expect(useStore.getState().decidedApprovals.size).toBe(1);
    expect(useStore.getState().capabilityDecidingIds.size).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });
  it('deduplicates queue arguments and leaves an empty lease inert', async () => {
    const transport = vi.fn<typeof fetch>(async input => response(input));
    vi.stubGlobal('fetch', transport);
    acquire([])();
    expect(transport).not.toHaveBeenCalled();
    acquire(['capability', 'capability']);
    await settle();
    expect(transport).toHaveBeenCalledTimes(1);
    expect(() => acquire(['other' as ApprovalQueue])).toThrow('Unknown');
  });
  it.each(['desktop', 'compact', 'mobile'] as const)('mounts the actual %s entry lifecycle with the specified queue set', async target => {
    const { ApprovalPollingBoundary } = await import('../../main');
    const transport = vi.fn<typeof fetch>(async input => response(input));
    vi.stubGlobal('fetch', transport);
    const view = render(createElement(ApprovalPollingBoundary, { target, children: null }));
    await settle();
    expect(transport.mock.calls.map(([input]) => String(input))).toEqual(target === 'desktop'
      ? ['/api/capability-requests/actionable', '/api/skill-requests?status=pending']
      : ['/api/capability-requests/actionable']);
    expect(vi.getTimerCount()).toBe(1);
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
