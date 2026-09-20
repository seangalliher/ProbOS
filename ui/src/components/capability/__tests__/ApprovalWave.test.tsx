import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { execFile } from 'node:child_process';
import { existsSync, realpathSync, statSync } from 'node:fs';
import { delimiter, dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  approvalKey, capabilityDecisionBody, capabilityFeedbackText, formatApprovalPayload,
  inspectActionPayload, isActionableCapabilityPayload, isCapabilityRequestView, parseCapabilityDecision,
  sameCapabilityRequest, standingApprovalPolicy,
} from '../../../store/capabilityApprovals';
import type { CapabilityApprovalView, CapabilityDecisionIntent } from '../../../store/types';
import { useStore } from '../../../store/useStore';
import { useSettingsStore } from '../../../store/useSettingsStore';
import CapabilityRequestPanel from '../CapabilityRequestPanel';
import { CapabilityRequestCard } from '../CapabilityRequestCard';

const ID = '9ab01eb5-4a9b-4df6-986d-b479191355d8';
const CONFIG = { approval_inbox: {
  standing_rules_enabled: true, standing_rule_max_ttl_hours: 12, standing_rule_default_ttl_hours: 24,
} };
function row(overrides: Partial<CapabilityApprovalView> = {}): CapabilityApprovalView {
  return {
    id: ID, agent_id: 'agent-a', kind: 'action', target: 'browser.click',
    rationale: 'Review this exact action', created_at: 10, work_item_id: null,
    status: 'pending', decided_at: null, decided_by: '', decision_reason: '',
    can_retry_fulfilment: false,
    payload: { tool_id: 'browser', action: 'click', params: { selector: '#send' },
      scope_key: 'example.test', session_id: null, thread_id: 'thread-a' },
    ...overrides,
  };
}
function decision(expected = row()): Record<string, unknown> {
  return { request: { ...expected, status: 'approved', decided_at: 20, decided_by: 'captain' }, fulfilled: false };
}
function receipt(): Record<string, unknown> {
  return { id: '05527d1d-d4c7-41da-8d28-1dbd75af4688', agent_id: 'agent-a',
    tool_id: 'browser', action: 'click', scope_key: 'example.test', issued_at: 20, expires_at: 3620 };
}
function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status });
}
function queue(requests: CapabilityApprovalView[] = [row()]): Response {
  return json({ view: 'actionable', requests });
}
async function load(transport = vi.fn<typeof fetch>(async () => queue())): Promise<typeof transport> {
  vi.stubGlobal('fetch', transport);
  await useStore.getState().refreshPendingApprovals({ queues: ['capability'] });
  expect(useStore.getState().approvalResources.capability.status).toBe('ready');
  expect(isCapabilityRequestView(useStore.getState().approvalResources.capability.data?.requests[0])).toBe(true);
  return transport;
}
function reset(): void {
  useStore.getState().cancelPendingApprovals();
  const initial = useStore.getInitialState();
  useStore.setState({
    approvalResources: initial.approvalResources, approvalPoll: initial.approvalPoll,
    approvalControllers: { capability: null, skill: null }, approvalIssuedSeq: { capability: 0, skill: 0 },
    approvalAppliedSeq: { capability: 0, skill: 0 }, approvalRequestSeq: 0,
    pendingApprovals: [], decidedApprovals: new Set(), capabilityDecidingIds: new Set(),
    capabilityDecisionFeedback: new Map(), capabilityDecisionRevision: 0, capabilityApprovalEpoch: 0, liveRepairEpoch: 0,
  });
  useSettingsStore.setState({ loaded: true, loading: false, snapshot: {
    config: CONFIG, secret_present: {}, sections: [], domain_counts: {}, domain_order: [],
    section_count: 0, config_path: '', uptime_seconds: 0, csrf_token: '',
  } });
}
beforeEach(reset);
afterEach(() => { cleanup(); reset(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('AD-1212 standing receipts and immutable review identity', () => {
  it('retains the complete real wire receipt without changing the compatible two-field result', () => {
    expect(isCapabilityRequestView(row())).toBe(true);
    expect(parseCapabilityDecision(decision(), row(), true)).toEqual(decision());
    expect(parseCapabilityDecision({ ...decision(), standing_rule: null }, row(), true)).toEqual(decision());
    expect(parseCapabilityDecision({ ...decision(), standing_rule: receipt() }, row(), true, 1))
      .toEqual({ ...decision(), standingRule: receipt() });
  });

  describe('AD-1212 shared inspectable standing card', () => {
    it('renders complete inert text, exact scope and an unchecked standing choice', async () => {
      const payload = { ...row().payload, params: { html: '<img src=x onerror="window.pwned=1">', bidi: '\u202e' } };
      const request = row({ payload });
      await load(vi.fn<typeof fetch>(async () => queue([request])));
      const view = render(<CapabilityRequestPanel hosted />);
      const inspected = screen.getByLabelText('Complete action payload');
      expect(inspected.textContent).toBe(formatApprovalPayload(payload));
      expect(inspected.textContent).toContain('\\u202e');
      expect(screen.getByText('Numbers show decoded JSON values; original numeric spelling is not preserved.')).toBeVisible();
      expect(view.container.querySelector('img, a, iframe, script')).toBeNull();
      expect(screen.getByRole('checkbox', { name: 'Grant standing approval' })).not.toBeChecked();
      expect(screen.queryByRole('spinbutton')).toBeNull();
      expect(screen.getByText(/Parameters, selectors, sessions and thread IDs/)).toBeTruthy();
      expect(screen.getByText(/does not replay the original action/)).toBeTruthy();
      expect(screen.getByText(/Exact match: agent agent-a/)).toHaveTextContent('scope "example.test"');
      expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();
    });
    it.each(['Approve', 'Deny'])('preserves the original round decision glyph strokes on %s', async name => {
      await load();
      render(<CapabilityRequestPanel hosted />);
      const glyph = screen.getByRole('button', { name }).querySelector('svg');
      expect(glyph).toHaveAttribute('stroke-linecap', 'round');
      expect(glyph).toHaveAttribute('stroke-linejoin', 'round');
    });
    it.each([
      { token: '0.5', value: 0.5, selected: false },
      { token: '0.5', value: 0.5, selected: true },
      { token: '-0', value: -0, selected: false },
      { token: '-0', value: -0, selected: true },
    ])('approves decoded numeric $token through the actual card with standing selected=$selected', async ({ token, value, selected }) => {
      const request = row({ payload: { ...row().payload, params: { x: value } } });
      const response = (body: unknown): Response => {
        // JSON.stringify normalizes -0; keep that decoded value in the raw wire fixture.
        const text = JSON.stringify(body);
        return new Response(Object.is(value, -0) ? text.replace('"x":0', '"x":-0') : text);
      };
      const transport = await load(vi.fn<typeof fetch>(async (_url, init) => init?.method === 'POST'
        ? response({ ...decision(request), standing_rule: selected ? receipt() : null })
        : response({ view: 'actionable', requests: [request] })));
      render(<CapabilityRequestPanel hosted />);
      expect(screen.getByLabelText('Complete action payload')).toHaveTextContent(`"params":{"x":${token}}`);
      expect(screen.getByText('Numbers show decoded JSON values; original numeric spelling is not preserved.')).toBeVisible();
      expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();
      expect(screen.getByRole('checkbox')).toBeEnabled();
      expect(screen.getByRole('checkbox')).not.toBeChecked();
      if (selected) {
        fireEvent.click(screen.getByRole('checkbox'));
        fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '1' } });
      }
      fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
      await waitFor(() => expect(screen.queryByTestId('capability-request-card')).toBeNull());
      expect(transport.mock.calls.map(([, init]) => init?.method ?? 'GET')).toEqual(['GET', 'GET', 'POST']);
      expect(transport.mock.calls[2][0]).toBe(`/api/capability-requests/${ID}/decide`);
      expect(JSON.parse(String(transport.mock.calls[2][1]?.body))).toEqual({ approve: true, reason: '',
        ...(selected ? { grant_standing: true, standing_ttl_hours: 1 } : {}) });
      const feedback = useStore.getState().capabilityDecisionFeedback.get(ID)!;
      const inspection = inspectActionPayload(feedback.outcome.request.payload);
      expect(inspection.ok).toBe(true);
      if (!inspection.ok) throw new Error(inspection.issue);
      expect(Object.is(inspection.payload.params.x, value)).toBe(true);
      expect(feedback.outcome.fulfilled).toBe(false);
      expect(feedback.outcome.request.can_retry_fulfilment).toBe(false);
      expect(useStore.getState().capabilityDecisionRevision).toBe(1);
      expect(useStore.getState().decidedApprovals.has(approvalKey('capability', ID))).toBe(true);
      expect(screen.getByTestId('capability-decision-feedback')).toHaveTextContent('the original action was not replayed');
      if (selected) expect(feedback.outcome.standingRule).toEqual(receipt());
      else expect(feedback.outcome.standingRule).toBeUndefined();
    });
    it('disables unsafe approval without disabling a reasoned denial', async () => {
      const request = row({ payload: { ...row().payload, params: {
        allowed: 0.5, nested: [{ value: Number.MAX_SAFE_INTEGER + 1 }],
      } } });
      const transport = await load(vi.fn<typeof fetch>(async (_url, init) => init?.method === 'POST'
        ? json({ request: { ...request, status: 'denied', decided_at: 20, decided_by: 'captain' }, fulfilled: false })
        : queue([request])));
      render(<CapabilityRequestPanel hosted />);
      expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled();
      expect(screen.getByRole('checkbox')).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Deny' })).toBeEnabled();
      // The old message pinned safe-integer-only inspection; decoded fractions are now valid.
      expect(screen.getByText(/Payload numbers must be finite; integers must be safe/)).toBeTruthy();
      expect(screen.queryByLabelText('Complete action payload')).toBeNull();
      fireEvent.change(screen.getByRole('textbox'), { target: { value: 'not inspectable' } });
      fireEvent.click(screen.getByRole('button', { name: 'Deny' }));
      await waitFor(() => expect(screen.queryByTestId('capability-request-card')).toBeNull());
      const posts = transport.mock.calls.filter(([, init]) => init?.method === 'POST');
      expect(posts).toHaveLength(1);
      expect(JSON.parse(String(posts[0][1]?.body))).toEqual({ approve: false, reason: 'not inspectable' });
      expect(screen.getByTestId('capability-decision-feedback')).toHaveTextContent('Denial recorded.');
    });
    it.each([true, false])('posts standing fields only for an explicit selected grant (%s)', async selected => {
      const transport = await load(vi.fn<typeof fetch>(async (_url, init) => init?.method === 'POST'
        ? json({ ...decision(), standing_rule: selected ? receipt() : null }) : queue()));
      render(<CapabilityRequestPanel hosted />);
      if (selected) {
        fireEvent.click(screen.getByRole('checkbox'));
        expect(screen.getByRole('spinbutton')).toHaveValue(12);
        fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '1' } });
      }
      fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
      await waitFor(() => expect(screen.queryByTestId('capability-request-card')).toBeNull());
      const posts = transport.mock.calls.filter(([, init]) => init?.method === 'POST');
      expect(posts).toHaveLength(1);
      expect(JSON.parse(String(posts[0][1]?.body))).toEqual({ approve: true, reason: '',
        ...(selected ? { grant_standing: true, standing_ttl_hours: 1 } : {}) });
      if (selected) expect(screen.getByTestId('capability-decision-feedback'))
        .toHaveTextContent('expires 1970-01-01T01:00:20.000Z');
    });
    it('does not silently change a dirty TTL when policy changes', async () => {
      await load();
      render(<CapabilityRequestPanel hosted />);
      fireEvent.click(screen.getByRole('checkbox'));
      fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '6' } });
      act(() => useSettingsStore.setState({ snapshot: {
        ...useSettingsStore.getState().snapshot!, config: { approval_inbox: {
          standing_rules_enabled: true, standing_rule_max_ttl_hours: 2, standing_rule_default_ttl_hours: 1,
        } },
      } }));
      expect(screen.getByRole('spinbutton')).toHaveValue(6);
      expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Deny' })).toBeEnabled();
      fireEvent.click(screen.getByRole('checkbox'));
      expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();
    });
    it.each(['failed', 'disabled', 'unknown'] as const)('keeps ordinary approval separate from %s standing policy', async state => {
      const transport = await load(vi.fn<typeof fetch>(async (url) => String(url) === '/api/config'
        ? json({}, 503) : queue([row(), row({ id: 'second' })])));
      useSettingsStore.setState(state === 'failed'
        ? { loaded: false, loading: false, snapshot: null }
        : { loaded: true, snapshot: { ...useSettingsStore.getState().snapshot!, config: state === 'disabled'
          ? { approval_inbox: { standing_rules_enabled: false } } : {} } });
      render(<CapabilityRequestPanel hosted />);
      await waitFor(() => expect(screen.getAllByRole('checkbox').every(control => control.hasAttribute('disabled'))).toBe(true));
      expect(screen.getAllByRole('button', { name: 'Approve' })).toHaveLength(2);
      for (const control of screen.getAllByRole('button', { name: 'Approve' })) expect(control).toBeEnabled();
      if (state === 'failed') expect(transport.mock.calls.filter(([url]) => url === '/api/config')).toHaveLength(1);
    });
    it('never includes a selected standing grant on Deny', async () => {
      const transport = await load(vi.fn<typeof fetch>(async (_url, init) => init?.method === 'POST'
        ? json({ request: { ...row(), status: 'denied', decided_at: 20, decided_by: 'captain' }, fulfilled: false }) : queue()));
      render(<CapabilityRequestPanel hosted />);
      fireEvent.click(screen.getByRole('checkbox'));
      fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '0' } });
      fireEvent.change(screen.getByRole('textbox'), { target: { value: 'declined' } });
      fireEvent.click(screen.getByRole('button', { name: 'Deny' }));
      await waitFor(() => expect(screen.queryByTestId('capability-request-card')).toBeNull());
      expect(JSON.parse(String(transport.mock.calls.find(([, init]) => init?.method === 'POST')?.[1]?.body)))
        .toEqual({ approve: false, reason: 'declined' });
    });
    it('preserves non-action approval and repair no-standing controls', async () => {
      const requests = [row({ kind: 'install', payload: null }),
        row({ id: 'repair', payload: { ...row().payload, tool_id: 'repair', action: 'dispatch' } })];
      await load(vi.fn<typeof fetch>(async () => queue(requests)));
      render(<CapabilityRequestPanel hosted />);
      expect(screen.queryByRole('checkbox')).toBeNull();
      for (const control of screen.getAllByRole('button', { name: 'Approve' })) expect(control).toBeEnabled();
      expect(screen.getByText(/Only this repair request/)).toBeTruthy();
    });
    it('moves retiring focused controls to their status, never stealing focus from another surface', async () => {
      const user = userEvent.setup();
      await load(vi.fn<typeof fetch>(async (_url, init) => init?.method === 'POST' ? json(decision()) : queue()));
      render(<><input aria-label="Elsewhere" /><CapabilityRequestPanel hosted /></>);
      await user.click(screen.getByRole('button', { name: 'Approve' }));
      await waitFor(() => expect(screen.getByLabelText(`Request ${ID} status`)).toHaveFocus());
      const outside = screen.getByLabelText('Elsewhere');
      await user.click(outside);
      act(() => useStore.getState().recordCapabilityDecision(parseCapabilityDecision(decision(), row(), true)));
      expect(outside).toHaveFocus();
    });
    it('falls back to capability Refresh when a focused card disappears without feedback', async () => {
      let absent = false;
      await load(vi.fn<typeof fetch>(async () => queue(absent ? [] : [row()])));
      render(<CapabilityRequestPanel hosted />);
      screen.getByRole('button', { name: 'Approve' }).focus();
      expect(screen.getByRole('button', { name: 'Approve' })).toHaveFocus();
      absent = true;
      await act(async () => useStore.getState().refreshPendingApprovals({ queues: ['capability'] }));
      expect(screen.getByRole('button', { name: 'Refresh capability requests' })).toHaveFocus();
    });
    it('renders absence as unknown until an authoritative empty read', async () => {
      render(<CapabilityRequestCard requestId={ID} inline />);
      expect(screen.getByRole('status')).toHaveTextContent('unknown');
      expect(screen.queryByRole('button')).toBeNull();
      vi.stubGlobal('fetch', vi.fn<typeof fetch>(async () => queue([])));
      await act(async () => useStore.getState().refreshPendingApprovals({ queues: ['capability'] }));
      expect(screen.getByRole('status')).toHaveTextContent('No longer actionable');
    });
  });
  it.each([
    { id: '' }, { agent_id: 'other' }, { tool_id: 'shell' }, { action: 'fill' }, { scope_key: '' },
    { issued_at: Infinity }, { expires_at: 9e20 }, { expires_at: 20 }, { expires_at: 3621 },
  ])('keeps a confirmed decision when the grant is malformed: %j', changed => {
    const outcome = parseCapabilityDecision({ ...decision(), standing_rule: { ...receipt(), ...changed } }, row(), true, 1);
    expect(outcome).toEqual({ ...decision(), standingRuleIssue: 'invalid' });
  });
  it('compares object keys structurally while preserving arrays, types and every displayed field', () => {
    const first = row();
    const equal = row({ payload: Object.fromEntries(Object.entries(first.payload!).reverse()) });
    expect(sameCapabilityRequest(first, equal)).toBe(true);
    for (const field of ['id', 'agent_id', 'kind', 'target', 'rationale', 'work_item_id',
      'status', 'decided_by', 'decision_reason', 'created_at', 'decided_at', 'can_retry_fulfilment'] as const) {
      expect(sameCapabilityRequest(first, { ...first, [field]: 'changed' } as CapabilityApprovalView)).toBe(false);
    }
    for (const params of [{ selector: ' #send' }, { selector: 2 }, { selector: ['a', 'b'] }]) {
      expect(sameCapabilityRequest(first, row({ payload: { ...first.payload, params } }))).toBe(false);
    }
    expect(sameCapabilityRequest(row({ payload: { x: ['a', 'b'] } }), row({ payload: { x: ['b', 'a'] } }))).toBe(false);
  });
  it('rejects a decision response that changes the inspected raw payload', () => {
    const response = decision(row({ payload: { ...row().payload, params: { selector: '#delete' } } }));
    expect(() => parseCapabilityDecision(response, row(), true)).toThrow('payload changed');
  });
});

describe('AD-1212 complete bounded inert inspection', () => {
  it('preserves markup and visibly escapes controls without indentation', () => {
    const value = { html: '<img src=x onerror=alert(1)>', c1: '\u0085', bidi: '\u202e', sep: '\u2028', nl: '\n' };
    const text = formatApprovalPayload(value);
    expect(text).toContain('<img src=x onerror=alert(1)>');
    expect(text).toContain('\\u0085');
    expect(text).toContain('\\u202e');
    expect(text).toContain('\\u2028');
    expect(text).not.toContain('\n');
    expect(text).not.toContain('  ');
    expect(formatApprovalPayload(null)).toBe('null');
    expect(formatApprovalPayload({})).toBe('{}');
  });
  // The old rejection table included -0 and 1.1; decoded-number inspection must accept both.
  it.each([
    ['0.5', 0.5], ['-0.5', -0.5], ['1.25', 1.25], ['0.1', 0.1], ['1.1', 1.1], ['1e-7', 1e-7],
    ['5e-324', Number.MIN_VALUE], ['9007199254740991', Number.MAX_SAFE_INTEGER],
    ['-9007199254740991', Number.MIN_SAFE_INTEGER], ['0', 0], ['-0', -0],
  ] as const)('displays decoded numeric %s with an Object.is round-trip and no value conversion', (token, value) => {
    const text = formatApprovalPayload(value);
    expect(text).toBe(token);
    expect(Object.is(JSON.parse(text), value)).toBe(true);
    const payload = { ...row().payload, params: { x: value } };
    const inspection = inspectActionPayload(payload);
    expect(inspection.ok).toBe(true);
    if (!inspection.ok) throw new Error(inspection.issue);
    expect(inspection.text).toContain(`"x":${token}`);
    expect(Object.is(JSON.parse(inspection.text).params.x, value)).toBe(true);
    expect(typeof inspection.payload.params.x).toBe('number');
    expect(Object.is(inspection.payload.params.x, value)).toBe(true);
    expect(Object.is(payload.params.x, value)).toBe(true);
  });
  it.each([
    { label: 'NaN', value: NaN }, { label: 'positive infinity', value: Infinity },
    { label: 'negative infinity', value: -Infinity },
    { label: 'integer above the safe maximum', value: Number.MAX_SAFE_INTEGER + 1 },
    { label: 'integer below the safe minimum', value: Number.MIN_SAFE_INTEGER - 1 },
    { label: 'parsed 9007199254740993', value: JSON.parse('9007199254740993') },
  ])('rejects the whole action for nested $label while retaining reasoned denial', ({ value }) => {
    const payload = { ...row().payload, params: { allowed: 0.5, nested: [{ value }] } };
    expect(() => formatApprovalPayload(payload)).toThrow('Payload numbers must be finite; integers must be safe.');
    expect(inspectActionPayload(payload)).toEqual({ ok: false, issue: 'Payload numbers must be finite; integers must be safe.' });
    const request = row({ payload });
    expect(() => capabilityDecisionBody(request, { action: 'approve', reason: '' }, CONFIG)).toThrow('Approval disabled');
    expect(() => capabilityDecisionBody(request, { action: 'approve', reason: '', standingTtlHours: 1 }, CONFIG))
      .toThrow('Approval disabled');
    expect(capabilityDecisionBody(request, { action: 'deny', reason: 'not inspectable' }, CONFIG))
      .toEqual({ approve: false, reason: 'not inspectable' });
  });
  it.each([null, 'session-a'])('constructs the validated six-field payload without changing scalar values (session %s)', session => {
    const params = Object.freeze({ number: 1, text: '1', flag: false, nothing: null,
      nested: Object.freeze([2, '2', true, null]) });
    const payload = Object.freeze({ tool_id: 'browser', action: 'click', params,
      scope_key: '', session_id: session, thread_id: '' });
    const inspection = inspectActionPayload(payload);
    expect(inspection.ok).toBe(true);
    if (!inspection.ok) throw new Error(inspection.issue);
    expect(inspection.payload).toStrictEqual(payload);
    expect(inspection.payload).not.toBe(payload);
    expect(inspection.payload.params).toBe(params);
  });
  it('preserves negative zero in detached review identity instead of normalizing it to zero', () => {
    const negative = row({ payload: { ...row().payload, params: { x: -0 } } });
    expect(sameCapabilityRequest(negative, structuredClone(negative))).toBe(true);
    expect(sameCapabilityRequest(negative, row({ payload: { ...negative.payload, params: { x: 0 } } }))).toBe(false);
  });
  it.each([NaN, Infinity, Number.MAX_SAFE_INTEGER + 1, undefined, () => 1, new Date(), 1n])(
    'rejects uninspectable value %s', value => expect(() => formatApprovalPayload({ value })).toThrow(),
  );
  it('rejects cycles, accessors and non-JSON array properties without invoking them', () => {
    const cycle: Record<string, unknown> = {}; cycle.self = cycle;
    const getter = vi.fn(() => 'hidden');
    expect(() => formatApprovalPayload(cycle)).toThrow();
    expect(() => formatApprovalPayload(Object.defineProperty({}, 'secret', { enumerable: true, get: getter }))).toThrow();
    expect(getter).not.toHaveBeenCalled();
    expect(() => formatApprovalPayload(new Array(1))).toThrow();
    expect(() => formatApprovalPayload(Object.assign([], { extra: true }))).toThrow();
    expect(inspectActionPayload(Object.defineProperty({ ...row().payload }, 'tool_id', { enumerable: true, get: getter })).ok).toBe(false);
    expect(getter).not.toHaveBeenCalled();
  });
  it('enforces exact byte, node and depth bounds without clipping', () => {
    expect(new TextEncoder().encode(formatApprovalPayload('x'.repeat(32766))).length).toBe(32768);
    expect(() => formatApprovalPayload('x'.repeat(32767))).toThrow('32,768');
    expect(formatApprovalPayload(Array(4095).fill(null))).toHaveLength(20476);
    expect(() => formatApprovalPayload(Array(4096).fill(null))).toThrow('4,096');
    let deep: unknown = null;
    for (let i = 0; i < 2048; i++) deep = [deep];
    expect(formatApprovalPayload(deep)).toHaveLength(4100);
    expect(() => formatApprovalPayload([deep])).toThrow('2,048');
    expect(() => formatApprovalPayload('\u202e'.repeat(5462))).toThrow('32,768');
  });
  it('uses code-point field limits and a necessary string-heavy size bound, not UTF-8 bytes', () => {
    const payload = { ...row().payload, scope_key: '😀'.repeat(253), session_id: '😀'.repeat(64), thread_id: '😀'.repeat(64) };
    expect(inspectActionPayload(payload).ok).toBe(true);
    expect(inspectActionPayload({ ...payload, scope_key: '😀'.repeat(254) }).ok).toBe(false);
    const exact = { ...row().payload, params: { text: '' } };
    // This used to claim JS reserialization enforced Python's exact canonical
    // limit. It only establishes the string-only bound; real Python numeric
    // boundaries cross the TS consumer and HTTP/browser paths in the bridge tests.
    const overhead = [...JSON.stringify(exact)].length;
    exact.params.text = '😀'.repeat(4000 - overhead);
    expect([...JSON.stringify(exact)]).toHaveLength(4000);
    expect(inspectActionPayload(exact).ok).toBe(true);
    exact.params.text += 'x';
    expect(inspectActionPayload(exact).ok).toBe(false);
  });
  it.each(['ordinary', 'repair'] as const)(
    'counts only numeric values as zero for the %s raw lower bound without mutating keys, strings or containers',
    kind => {
      const repair = kind === 'repair';
      const values = Object.freeze([1e-6, 0.5, -0, true, false, null]);
      const params = {
        ...(repair ? { fault_id: 'fault-1', signature: 'a'.repeat(64) } : {}),
        '123': '123', '1e-6': '1e-6', text: '😀\u0000\u007f\u0085\u202e\u2028\u2029',
        values, padding: '',
      };
      const payload = {
        tool_id: repair ? 'repair' : 'browser', action: repair ? 'dispatch' : 'click',
        params, scope_key: 'example.test', session_id: null, thread_id: 'thread-a',
      };
      const zeros = { ...payload, params: { ...params, values: [0, 0, 0, true, false, null] } };
      params.padding = '😀'.repeat(4000 - [...JSON.stringify(zeros)].length);
      Object.freeze(params);
      Object.freeze(payload);
      const inspection = inspectActionPayload(payload);
      expect(inspection.ok).toBe(true);
      if (!inspection.ok) throw new Error(inspection.issue);
      expect(inspection.payload).toStrictEqual(payload);
      expect(inspection.payload.params).toBe(params);
      expect(inspection.text).toContain('"1e-6":"1e-6"');
      expect(inspection.text).toContain('"123":"123"');
      expect(inspection.text).toContain('[0.000001,0.5,-0,true,false,null]');
      expect(inspection.text).toContain('\\u202e');
      expect(JSON.parse(inspection.text)).toStrictEqual(payload);
      expect(Object.is(params.values[2], -0)).toBe(true);
      const request = row({ payload, status: repair ? 'approved' : 'pending', can_retry_fulfilment: repair });
      expect(isActionableCapabilityPayload({ view: 'actionable', requests: [request, row({ id: 'unrelated' })] })).toBe(true);
      const over = { ...payload, params: { ...params, padding: params.padding + 'x' } };
      expect(inspectActionPayload(over).ok).toBe(false);
      if (repair) {
        // A genuinely impossible repair still rejects the whole response; do not filter it out.
        expect(isCapabilityRequestView({ ...request, payload: over })).toBe(false);
        expect(isActionableCapabilityPayload({
          view: 'actionable', requests: [{ ...request, payload: over }, row({ id: 'unrelated' })],
        })).toBe(false);
      }
    },
  );
  it.each([
    { value: Number.MAX_SAFE_INTEGER + 1, issue: 'integers must be safe' },
    { value: '\u{e0001}'.repeat(3700), issue: '32,768 UTF-8 bytes' },
  ])('keeps display-only restrictions out of repair retry eligibility ($issue)', ({ value, issue }) => {
    const request = row({
      status: 'approved', can_retry_fulfilment: true,
      payload: { tool_id: 'repair', action: 'dispatch', scope_key: 'browser',
        session_id: null, thread_id: '', params: { fault_id: 'fault-1', signature: 'a'.repeat(64), value } },
    });
    const inspection = inspectActionPayload(request.payload);
    expect(inspection.ok).toBe(false);
    if (inspection.ok) throw new Error('The display-only restriction did not discriminate');
    expect(inspection.issue).toContain(issue);
    expect(isCapabilityRequestView(request)).toBe(true);
    expect(capabilityDecisionBody(request, { action: 'retry' }, CONFIG)).toEqual({ approve: true, reason: '' });
  });
  it.each(['1e309', '-1e309'])('counts decoded JSON overflow %s as zero, not null, only for the repair lower bound', token => {
    const value: number = JSON.parse(token);
    expect(Object.is(value, token.startsWith('-') ? -Infinity : Infinity)).toBe(true);
    const params = { fault_id: 'fault-1', signature: 'a'.repeat(64), nested: Object.freeze([value]), padding: '' };
    const payload = { tool_id: 'repair', action: 'dispatch', scope_key: 'browser',
      session_id: null, thread_id: '', params };
    const zeros = { ...payload, params: { ...params, nested: [0] } };
    params.padding = 'x'.repeat(4000 - [...JSON.stringify(zeros)].length);
    Object.freeze(params);
    Object.freeze(payload);
    // JSON.stringify would emit four-character null; the necessary bound uses one-character zero.
    expect([...JSON.stringify(payload)]).toHaveLength(4003);
    const request = row({ payload, status: 'approved', can_retry_fulfilment: true });
    const queue = { view: 'actionable', requests: [request, row({ id: 'unrelated' })] };
    expect(isCapabilityRequestView(request)).toBe(true);
    expect(isActionableCapabilityPayload(queue)).toBe(true);
    expect(capabilityDecisionBody(request, { action: 'retry' }, CONFIG)).toEqual({ approve: true, reason: '' });
    expect(inspectActionPayload(payload)).toEqual({ ok: false, issue: 'Payload numbers must be finite; integers must be safe.' });
    expect(Object.is(params.nested[0], value)).toBe(true);
    expect(sameCapabilityRequest(request, structuredClone(request))).toBe(true);
    for (const changed of [-value, null]) {
      expect(sameCapabilityRequest(request, { ...request, payload: { ...payload,
        params: { ...params, nested: [changed] } } })).toBe(false);
    }
    expect(isActionableCapabilityPayload({ ...queue, requests: [
      { ...request, payload: { ...payload, params: { ...params, padding: params.padding + 'x' } } }, queue.requests[1],
    ] })).toBe(false);
  });
  it.each([NaN, undefined, () => 1, Symbol('not-json'), 1n])(
    'still rejects non-JSON-domain repair values (%s) instead of losing the invalid row', value => {
      const request = row({
        status: 'approved', can_retry_fulfilment: true,
        payload: { tool_id: 'repair', action: 'dispatch', scope_key: 'browser',
          session_id: null, thread_id: '', params: { fault_id: 'fault-1', signature: 'a'.repeat(64), value } },
      });
      expect(isCapabilityRequestView(request)).toBe(false);
      expect(isActionableCapabilityPayload({ view: 'actionable', requests: [request, row({ id: 'unrelated' })] })).toBe(false);
      expect(() => capabilityDecisionBody(request, { action: 'retry' }, CONFIG)).toThrow('Invalid capability decision intent');
    },
  );
  it.each([
    null, {}, { ...row().payload, extra: '' }, { ...row().payload, tool_id: 'Browser' },
    { ...row().payload, action: 'x'.repeat(65) }, { ...row().payload, params: [] },
    { ...row().payload, params: Object.fromEntries(Array.from({ length: 21 }, (_, i) => [`k${i}`, i])) },
    { ...row().payload, thread_id: '\ud800' }, { ...row().payload, session_id: 'x'.repeat(65) },
  ])('rejects action payload outside the existing six-field contract: %j', value => {
    expect(inspectActionPayload(value).ok).toBe(false);
    expect(capabilityDecisionBody(row({ payload: value as CapabilityApprovalView['payload'] }),
      { action: 'deny', reason: 'Unsafe to inspect' }, CONFIG)).toEqual({ approve: false, reason: 'Unsafe to inspect' });
  });
  it('uses known policy only and clamps the initial default, not submitted values', () => {
    expect(standingApprovalPolicy(CONFIG)).toEqual({ maxHours: 12, defaultHours: 12, issue: null });
    expect(standingApprovalPolicy(null).issue).toContain('unknown');
    expect(standingApprovalPolicy({ approval_inbox: { standing_rules_enabled: false } }).issue).toContain('disabled');
    expect(() => capabilityDecisionBody(row(), { action: 'approve', reason: '', standingTtlHours: 13 }, CONFIG)).toThrow('1 through 12');
    expect(() => capabilityDecisionBody(row(), { action: 'approve', reason: '', standingTtlHours: 1 }, null)).toThrow('unknown');
  });
});

describe('AD-1212 one predecision command', () => {
  it('performs a fresh shared GET, one exact POST, one reconciliation and releases its guard', async () => {
    const transport = await load(vi.fn<typeof fetch>(async (_url, init) => init?.method === 'POST' ? json(decision()) : queue()));
    const applied = useStore.getState().approvalAppliedSeq.capability;
    const expected = structuredClone(row());
    const pending = useStore.getState().decideCapabilityRequest(expected, { action: 'approve', reason: '  checked  ' });
    expect(useStore.getState().capabilityDecidingIds.has(ID)).toBe(true);
    const outcome = await pending;
    expect(outcome.request.status).toBe('approved');
    expect(useStore.getState().approvalAppliedSeq.capability).toBeGreaterThan(applied);
    expect(transport.mock.calls.map(([, init]) => init?.method ?? 'GET')).toEqual(['GET', 'GET', 'POST']);
    expect(JSON.parse(String(transport.mock.calls[2][1]?.body))).toEqual({ approve: true, reason: 'checked' });
    expect(transport.mock.calls[2][1]?.signal).toBeUndefined();
    expect(useStore.getState().capabilityDecisionRevision).toBe(1);
    expect(useStore.getState().decidedApprovals.has(approvalKey('capability', ID))).toBe(true);
    expect(useStore.getState().pendingApprovals).toEqual([]);
    expect(useStore.getState().capabilityDecidingIds.size).toBe(0);
  });
  it('does not accept duplicate submissions or mutate the inspected snapshot during the read', async () => {
    let release!: (response: Response) => void;
    await load();
    const transport = vi.fn<typeof fetch>(() => new Promise(resolve => { release = resolve; }));
    vi.stubGlobal('fetch', transport);
    const expected = row();
    const pending = useStore.getState().decideCapabilityRequest(expected, { action: 'approve', reason: '' });
    await expect(useStore.getState().decideCapabilityRequest(expected, { action: 'approve', reason: '' })).rejects.toThrow('already in progress');
    expected.rationale = 'changed in place';
    release(queue([row({ rationale: 'changed in place' })]));
    await expect(pending).rejects.toThrow('review the current request');
    expect(transport).toHaveBeenCalledTimes(1);
    expect(useStore.getState().capabilityDecidingIds.size).toBe(0);
  });
  it('rejects a changed fresh row before any POST rather than approving the replacement', async () => {
    await load();
    const expected = structuredClone(row());
    const transport = vi.fn<typeof fetch>(async (_url, init) => init?.method === 'POST'
      ? json(decision()) : queue([row({ rationale: 'Changed after display' })]));
    vi.stubGlobal('fetch', transport);
    await expect(useStore.getState().decideCapabilityRequest(expected, { action: 'approve', reason: '' }))
      .rejects.toThrow('changed; review the current request');
    expect(transport.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
    expect(useStore.getState().capabilityDecisionRevision).toBe(0);
    expect(useStore.getState().capabilityDecidingIds.size).toBe(0);
  });
  it.each(['stale', 'refreshing', 'failed', 'unauthorized', 'idle'] as const)('refuses %s resource before issuing a read or POST', async state => {
    const transport = await load();
    const resource = useStore.getState().approvalResources.capability;
    useStore.setState({ approvalResources: { ...useStore.getState().approvalResources, capability: {
      ...resource, ...(state === 'stale' || state === 'refreshing' ? { [state]: true } : { status: state }),
    } } });
    await expect(useStore.getState().decideCapabilityRequest(row(), { action: 'approve', reason: '' })).rejects.toThrow('unknown or stale');
    expect(transport).toHaveBeenCalledTimes(1);
  });
  it('requires a newly applied generation rather than treating a no-op refresh as proof', async () => {
    const transport = await load();
    const refresh = useStore.getState().refreshPendingApprovals;
    useStore.setState({ refreshPendingApprovals: async () => {} });
    try {
      await expect(useStore.getState().decideCapabilityRequest(row(), { action: 'approve', reason: '' })).rejects.toThrow('fresh read');
      expect(transport).toHaveBeenCalledTimes(1);
    } finally { useStore.setState({ refreshPendingApprovals: refresh }); }
  });
  it.each([400, 404])('reads after concurrent HTTP %s but never repeats the POST', async status => {
    const transport = await load(vi.fn<typeof fetch>(async (_url, init) => init?.method === 'POST' ? json({}, status) : queue()));
    await expect(useStore.getState().decideCapabilityRequest(row(), { action: 'approve', reason: '' })).rejects.toThrow('no longer actionable');
    expect(transport.mock.calls.map(([, init]) => init?.method ?? 'GET')).toEqual(['GET', 'GET', 'POST', 'GET']);
    expect(useStore.getState().capabilityDecisionRevision).toBe(0);
  });
  it('refreshes an invalid overall response without a tombstone or confirmed feedback', async () => {
    await load(vi.fn<typeof fetch>(async (_url, init) => init?.method === 'POST' ? json({ request: {}, fulfilled: true }) : queue()));
    await expect(useStore.getState().decideCapabilityRequest(row(), { action: 'approve', reason: '' })).rejects.toThrow('not confirmed');
    expect(useStore.getState().decidedApprovals.size).toBe(0);
    expect(useStore.getState().capabilityDecisionFeedback.size).toBe(0);
    expect(useStore.getState().pendingApprovals).toHaveLength(1);
  });
  it.each([null, { invalid: true }, receipt()])('reconciles the valid decision independently of standing receipt %j', async standing => {
    const transport = await load(vi.fn<typeof fetch>(async (_url, init) => init?.method === 'POST'
      ? json({ ...decision(), standing_rule: standing }) : queue()));
    await useStore.getState().decideCapabilityRequest(row(), { action: 'approve', reason: '', standingTtlHours: 1 });
    expect(JSON.parse(String(transport.mock.calls[2][1]?.body)))
      .toEqual({ approve: true, reason: '', grant_standing: true, standing_ttl_hours: 1 });
    expect(useStore.getState().pendingApprovals).toHaveLength(0);
    const feedback = useStore.getState().capabilityDecisionFeedback.get(ID)!;
    expect(capabilityFeedbackText(feedback)).toContain(standing && 'id' in standing
      ? 'Standing authority confirmed' : 'standing authority was not confirmed');
    expect(useStore.getState().capabilityDecisionRevision).toBe(1);
  });
  it('bounds shared feedback to the most recent 32 IDs without changing tombstones', () => {
    for (let i = 0; i < 40; i++) useStore.getState().recordCapabilityDecision({
      request: row({ id: `id-${i}`, status: 'denied', decided_at: 20, decided_by: 'captain' }), fulfilled: false,
    });
    expect(useStore.getState().capabilityDecisionFeedback.size).toBe(32);
    expect(useStore.getState().capabilityDecisionFeedback.has('id-0')).toBe(false);
    expect(useStore.getState().capabilityDecisionFeedback.has('id-39')).toBe(true);
    expect(useStore.getState().decidedApprovals.size).toBe(40);
  });
  it('preserves deny and approved retry bodies and never adds standing fields to repair', () => {
    expect(capabilityDecisionBody(row(), { action: 'deny', reason: '  no  ' }, CONFIG)).toEqual({ approve: false, reason: 'no' });
    expect(() => capabilityDecisionBody(row(), { action: 'deny', reason: '  ' }, CONFIG)).toThrow('reason');
    const retry = row({ kind: 'continue', status: 'approved', can_retry_fulfilment: true });
    expect(capabilityDecisionBody(retry, { action: 'retry' }, CONFIG)).toEqual({ approve: true, reason: '' });
    expect(() => capabilityDecisionBody(row(), { action: 'retry' }, CONFIG)).toThrow('retry');
    expect(() => capabilityDecisionBody(row({ payload: { ...row().payload, tool_id: 'repair' } }),
      { action: 'approve', reason: '', standingTtlHours: 1 }, CONFIG)).toThrow('eligible');
    expect(() => capabilityDecisionBody(row(), { action: 'invalid' } as unknown as CapabilityDecisionIntent, CONFIG)).toThrow('intent');
  });
});

interface NumericBoundaryWire {
  python: string;
  fixture: string;
  health: {
    ok: boolean;
    service: string;
    candidate: string;
    module_origins: Record<string, string>;
  };
  boundary: {
    ordinary: { request_id: string; python_characters: number };
    repair: { request_id: string; python_characters: number; can_fulfil: boolean };
    unrelated_request_ids: string[];
  };
  wire: string;
}

function requiredPython(root: string, override = process.env.PROBOS_TEST_PYTHON): string {
  const executable = override ?? (process.platform === 'win32'
    ? 'D:\\ProbOS\\.venv\\Scripts\\python.exe' : join(root, '.venv/bin/python'));
  if (!executable || !existsSync(executable) || !statSync(executable).isFile()) {
    throw new Error('Approved backend interpreter missing; set PROBOS_TEST_PYTHON. This crossing must not skip.');
  }
  return executable;
}

async function numericBoundaryWire(overflow: 'positive' | 'negative' | null = null): Promise<NumericBoundaryWire> {
  const root = realpathSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../../../..'));
  const executable = requiredPython(root);
  // The UI job owns Python and Node. Carry response.text as a string, never a
  // JS-reserialized queue: JSON.stringify would turn decoded overflow into null.
  const stdout = await new Promise<string>((accept, reject) => {
    execFile(executable, ['-u', '-c', `
import asyncio
import json
import sys
import httpx
from tests.fixtures import approval_ui_bridge as bridge

async def collect() -> dict[str, object]:
    app = bridge.create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1",
        ) as client:
            scenario = await client.post("/__approval_ui__/scenario", json={
                "kind": "action", "numeric_boundary": True,
                "numeric_overflow": json.loads(sys.argv[1]),
            })
            assert scenario.status_code == 200, scenario.text
            health = await client.get("/__approval_ui__/health")
            response = await client.get("/api/capability-requests/actionable")
            assert health.status_code == response.status_code == 200
            result = {
                "python": sys.executable, "fixture": bridge.__file__,
                "health": health.json(), "boundary": scenario.json()["numeric_boundary"],
                "wire": response.text,
            }
    assert app.state.runtime.closed
    return result

sys.stdout.write(json.dumps(asyncio.run(collect()), ensure_ascii=False, allow_nan=False))
`, JSON.stringify(overflow)], {
      cwd: root, shell: false, windowsHide: true, timeout: 25_000, maxBuffer: 1_000_000, encoding: 'utf8',
      env: {
        ...process.env, PYTHONPATH: [join(root, 'src'), root].join(delimiter),
        PYTHONDONTWRITEBYTECODE: '1', PYTHONIOENCODING: 'utf-8',
        PROBOS_NATS_ENABLED: 'false', HF_HUB_OFFLINE: '1',
      },
    }, (error, output, stderr) => error
      ? reject(new Error(`Approval wire bridge failed; crossing is unverified: ${error.message}\n${stderr}`))
      : accept(output));
  });
  const result = JSON.parse(stdout) as NumericBoundaryWire;
  expect(realpathSync(result.python)).toBe(realpathSync(executable));
  expect(realpathSync(result.fixture)).toBe(join(root, 'tests/fixtures/approval_ui_bridge.py'));
  expect(result.health.ok).toBe(true);
  expect(result.health.service).toBe('approval-ui-test-bridge');
  expect(realpathSync(result.health.candidate)).toBe(root);
  expect(Object.keys(result.health.module_origins).length).toBeGreaterThanOrEqual(15);
  for (const origin of Object.values(result.health.module_origins)) {
    expect(realpathSync(origin).startsWith(join(root, 'src') + sep)).toBe(true);
  }
  expect(realpathSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../../store/capabilityApprovals.ts')))
    .toBe(join(root, 'ui/src/store/capabilityApprovals.ts'));
  expect(result.boundary.ordinary.python_characters).toBe(3998);
  expect(result.boundary.repair.python_characters).toBe(4000);
  expect(result.boundary.repair.can_fulfil).toBe(true);
  expect(typeof result.wire).toBe('string');
  return result;
}

describe('AD-1212 real Python-wire numeric boundary consumers', () => {
  it('fails rather than skips when the approved Python interpreter is missing', () => {
    expect(() => requiredPython('.', '')).toThrow('must not skip');
  });

  it('accepts finite Python boundaries despite longer JavaScript serialization', async () => {
    const { boundary, wire } = await numericBoundaryWire();
    const queue = JSON.parse(wire) as { requests: CapabilityApprovalView[] };
    expect(queue.requests).toHaveLength(4);
    const actual = new Map(queue.requests.map(request => [request.id, request]));
    expect([...JSON.stringify(actual.get(boundary.ordinary.request_id)!.payload)]).toHaveLength(4001);
    expect([...JSON.stringify(actual.get(boundary.repair.request_id)!.payload)]).toHaveLength(4003);
    expect(isActionableCapabilityPayload(queue)).toBe(true);
    for (const request of queue.requests) {
      expect(isCapabilityRequestView(request)).toBe(true);
      expect(inspectActionPayload(request.payload).ok).toBe(true);
    }
  }, 30_000);

  it.each(['positive', 'negative'] as const)(
    'preserves raw %s overflow rows and Retry while blocking ordinary approval', async sign => {
      const { boundary, wire } = await numericBoundaryWire(sign);
      const token = `${sign === 'negative' ? '-' : ''}1${'0'.repeat(309)}`;
      expect(wire.split(`"value":${token}`)).toHaveLength(3);
      expect(wire).not.toContain('Infinity');
      expect(wire).not.toContain('"value":null');
      const queue = JSON.parse(wire) as { requests: CapabilityApprovalView[] };
      expect(queue.requests).toHaveLength(4);
      const ordinary = queue.requests.find(request => request.id === boundary.ordinary.request_id)!;
      const repair = queue.requests.find(request => request.id === boundary.repair.request_id)!;
      expect([ordinary, repair].map(request => {
        expect(request.payload).not.toBeNull();
        const value = (request.payload!.params as Record<string, number>).value;
        return { type: typeof value, value: String(value), infinite: Object.is(Math.abs(value), Infinity) };
      })).toEqual(Array(2).fill({
        type: 'number', value: sign === 'positive' ? 'Infinity' : '-Infinity', infinite: true,
      }));
      expect(isActionableCapabilityPayload(queue)).toBe(true);
      for (const request of queue.requests) expect(isCapabilityRequestView(request)).toBe(true);
      expect(Object.fromEntries(queue.requests.map(request => [request.id, inspectActionPayload(request.payload).ok])))
        .toEqual({
          [ordinary.id]: false, [repair.id]: false,
          ...Object.fromEntries(boundary.unrelated_request_ids.map(id => [id, true])),
        });
      expect(() => capabilityDecisionBody(ordinary, { action: 'approve', reason: '' }, {})).toThrow();
      expect(capabilityDecisionBody(repair, { action: 'retry' }, {})).toEqual({ approve: true, reason: '' });
    }, 30_000,
  );
});
