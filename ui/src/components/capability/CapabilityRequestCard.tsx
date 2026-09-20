import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useStore, type DecidedApproval } from '../../store/useStore';
import { useSettingsStore } from '../../store/useSettingsStore';
import type { CapabilityApprovalView, CapabilityDecisionIntent } from '../../store/types';
import {
  approvalDisplayText, capabilityFeedbackText, formatApprovalPayload, inspectActionPayload,
  standingApprovalEligible, standingApprovalPolicy,
} from '../../store/capabilityApprovals';
import { HxiApprovalFocus } from '../approvals/HxiApprovalFocus';

const AMBER = '#f0b060';
const DIM = '#666680';
const RED = '#d05050';
const CONTROL: React.CSSProperties = {
  fontFamily: 'inherit', fontSize: 11, borderRadius: 4, padding: '5px 7px',
  background: 'rgba(0,0,0,0.25)', color: '#c8d0e0', border: '1px solid rgba(255,255,255,0.1)',
};

export function CapabilityRequestCard({ requestId, request, inline = false, onDecided, onRetired }: {
  requestId: string;
  request?: CapabilityApprovalView;
  inline?: boolean;
  onDecided?: (decided: DecidedApproval) => void;
  onRetired?: () => void;
}): React.JSX.Element {
  const resource = useStore(state => state.approvalResources.capability);
  const sharedBusy = useStore(state => state.capabilityDecidingIds.has(requestId));
  const feedback = useStore(state => state.capabilityDecisionFeedback.get(requestId));
  const snapshot = useSettingsStore(state => state.snapshot);
  const loaded = useSettingsStore(state => state.loaded);
  const loading = useSettingsStore(state => state.loading);
  const loadSettings = useSettingsStore(state => state.loadSnapshot);
  // The closure submits the detached row that produced this render, never a
  // lookup of a newer row made just before the POST.
  const expected = useMemo(() => request ? structuredClone(request) : undefined, [request]);
  const [reason, setReason] = useState('');
  const [selected, setSelected] = useState(false);
  const [ttl, setTtl] = useState('');
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const deciding = useRef(false);
  const root = useRef<HTMLDivElement | null>(null);
  const status = useRef<HTMLDivElement | null>(null);
  const focused = useRef(false);
  const retired = useRef(onRetired);
  retired.current = onRetired;
  const known = (resource.status === 'ready' || resource.status === 'empty') && !resource.stale && !resource.refreshing;
  const eligible = expected !== undefined && standingApprovalEligible(expected);
  const policy = standingApprovalPolicy(loaded && !loading ? snapshot?.config : null);
  const inspection = inspectActionPayload(expected?.payload);
  const ordinary = expected?.kind === 'action' && expected.payload?.tool_id !== 'repair';
  const standingDisabled = !known || busy || sharedBusy || policy.issue !== null || !inspection.ok;
  const ttlValid = /^\d+$/.test(ttl) && Number.isSafeInteger(Number(ttl))
    && policy.maxHours !== null && Number(ttl) >= 1 && Number(ttl) <= policy.maxHours;
  const waiting = busy || sharedBusy || !known;
  const inspectText = useMemo(() => {
    if (!expected?.payload) return null;
    try { return formatApprovalPayload(expected.payload); } catch { return null; }
  }, [expected]);

  useEffect(() => { if (eligible) void loadSettings(); }, [eligible, loadSettings]);
  useEffect(() => {
    if (!dirty && policy.defaultHours !== null) setTtl(String(policy.defaultHours));
  }, [dirty, policy.defaultHours]);
  useLayoutEffect(() => {
    if (!request && focused.current) {
      status.current?.focus();
      focused.current = false;
    }
  }, [request]);
  useLayoutEffect(() => () => {
    if (root.current?.contains(document.activeElement)) retired.current?.();
  }, []);

  async function decide(action: 'approve' | 'deny' | 'retry'): Promise<void> {
    if (!expected || deciding.current) return;
    if (action === 'deny' && !reason.trim()) { setError('A reason is required to deny.'); return; }
    const intent: CapabilityDecisionIntent = action === 'retry' ? { action }
      : action === 'deny' ? { action, reason }
        : { action, reason, ...(selected ? { standingTtlHours: Number(ttl) } : {}) };
    deciding.current = true;
    setBusy(true);
    setError(null);
    try {
      const outcome = await useStore.getState().decideCapabilityRequest(expected, intent);
      onDecided?.({ queue: 'capability', id: expected.id, outcome });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Decision failed; refresh the request state before retrying.');
    } finally {
      deciding.current = false;
      setBusy(false);
    }
  }

  const name = (label: string): string => inline ? `${label} for request ${requestId}` : label;
  const accent = ['grant', 'install', 'build'].includes(expected?.kind ?? '') ? '#e08040' : DIM;
  return <div ref={root}
    onFocusCapture={() => { focused.current = true; }}
    onBlurCapture={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) focused.current = false; }}
    style={{ marginBottom: 8, color: '#c8d0e0', fontSize: 11 }}
  >
    <HxiApprovalFocus />
    {!expected ? <div ref={status} role="status" tabIndex={-1} data-hxi-focus=""
      aria-label={`Request ${requestId} status`} data-testid="capability-decision-feedback">
      {feedback ? capabilityFeedbackText(feedback) : known ? 'No longer actionable.' : 'Request state unknown; refresh approvals.'}
    </div> : <div data-testid="capability-request-card" role="group" aria-label={`Capability request ${requestId}`}
      style={{ borderRadius: 6, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
        borderLeft: `3px solid ${accent}`, padding: '9px 11px' }}>
      <div style={{ color: accent, textTransform: 'uppercase', fontWeight: 700 }}>{approvalDisplayText(expected.kind)}</div>
      <div style={{ fontSize: 12, fontWeight: 600, overflowWrap: 'anywhere' }}>{approvalDisplayText(expected.target)}</div>
      <div style={{ color: '#9098b0', margin: '4px 0', overflowWrap: 'anywhere' }}>
        {approvalDisplayText(expected.rationale) || <em>no rationale provided</em>}
      </div>
      <div style={{ color: DIM, overflowWrap: 'anywhere' }}>Request {requestId} · Agent {approvalDisplayText(expected.agent_id)}</div>
      <div style={{ color: DIM, marginBottom: 6 }}>
        {expected.work_item_id
          ? <span data-testid="linked-work-item">work item {approvalDisplayText(expected.work_item_id)}</span>
          : 'unlinked'}
      </div>
      {inspectText !== null && <>
        <pre tabIndex={0} data-hxi-focus="" aria-label={name('Complete action payload')}
          style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 240, overflow: 'auto', fontSize: 11 }}>
          {inspectText}
        </pre>
        <p>Numbers show decoded JSON values; original numeric spelling is not preserved.</p>
      </>}
      {ordinary && !inspection.ok && <p>{inspection.issue} Approval and standing authority are disabled; Deny remains available.</p>}
      {ordinary && <p>Approval records this decision only; it does not replay the original action.</p>}
      {expected.kind === 'continue' && <p>Approval uses the existing linked-work continuation. Fulfilment alone does not confirm resumed execution.</p>}
      {expected.payload?.tool_id === 'repair' && <p>Only this repair request is authorized. Standing authority is not available.</p>}
      {!known && <p>Request state is unknown or stale; refresh before deciding.</p>}
      {expected.can_retry_fulfilment && <div role="status" style={{ color: AMBER, marginBottom: 7 }}>Approved - awaiting fulfilment</div>}
      {!expected.can_retry_fulfilment && <input type="text" value={reason} disabled={waiting} data-hxi-focus=""
        onChange={event => setReason(event.target.value)} placeholder="Reason (required to deny)"
        aria-label={name('decision reason')} style={{ ...CONTROL, width: '100%', boxSizing: 'border-box', marginBottom: 7 }} />}
      {eligible && <fieldset style={{ border: '1px solid #66668055', padding: 8, margin: '4px 0 8px' }}>
        <legend>Future matching runs</legend>
        <label>
          <input type="checkbox" checked={selected} disabled={standingDisabled} data-hxi-focus=""
            aria-label={name('Grant standing approval')}
            onChange={event => { setSelected(event.target.checked); setDirty(true); }} />
          {' '}Grant a scoped, expiring standing approval
        </label>
        {policy.issue && <p>{policy.issue}</p>}
        {!inspection.ok && <p>Standing approval requires a complete, inspectable action payload.</p>}
        {inspection.ok && <>
          <p>Exact match: agent {approvalDisplayText(expected.agent_id)}, tool {approvalDisplayText(inspection.payload.tool_id)},
            {' '}action {approvalDisplayText(inspection.payload.action)}, scope {inspection.payload.scope_key === ''
              ? 'exact empty scope (not a wildcard or thread-specific grant)'
              : approvalDisplayText(JSON.stringify(inspection.payload.scope_key))}.</p>
          <p>Parameters, selectors, sessions and thread IDs are not additional standing match fields.</p>
        </>}
        {selected && <>
          <label>Lifetime (hours){' '}
            <input type="number" min={1} max={policy.maxHours ?? undefined} step={1} value={ttl}
              disabled={standingDisabled} data-hxi-focus="" aria-label={name('Standing lifetime in hours')}
              onChange={event => { setTtl(event.target.value); setDirty(true); }} style={{ ...CONTROL, width: 70 }} />
          </label>
          {!ttlValid && <p>Choose an integer lifetime from 1 through {policy.maxHours ?? 'the configured maximum'} hours.</p>}
          <p>Lifetime starts at issuance; confirmed issuance and expiry are shown after the decision.</p>
        </>}
      </fieldset>}
      {error && <div role="alert" style={{ color: RED, marginBottom: 6 }}>{error}</div>}
      {feedback && <div role="status" aria-label={`Request ${requestId} decision`}>{capabilityFeedbackText(feedback)}</div>}
      <div style={{ display: 'flex', gap: 6 }}>
        <button type="button" data-hxi-focus="" aria-label={name(expected.can_retry_fulfilment ? 'Retry fulfilment' : 'Approve')}
          disabled={waiting || (ordinary && !inspection.ok) || (eligible && selected && (standingDisabled || !ttlValid))}
          onClick={() => { void decide(expected.can_retry_fulfilment ? 'retry' : 'approve'); }}
          style={{ ...CONTROL, color: AMBER, borderColor: `${AMBER}55`, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={AMBER} strokeWidth={1.5}
            strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 13l4 4L19 7" /></svg>
          {expected.can_retry_fulfilment ? 'Retry fulfilment' : 'Approve'}
        </button>
        {!expected.can_retry_fulfilment && <button type="button" data-hxi-focus="" aria-label={name('Deny')}
          disabled={waiting} onClick={() => { void decide('deny'); }}
          style={{ ...CONTROL, color: RED, borderColor: `${RED}55`, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={RED} strokeWidth={1.5}
            strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          Deny
        </button>}
      </div>
    </div>}
  </div>;
}
