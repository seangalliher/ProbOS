/* Shared capability queue presentation. Hosted panels reuse their shell/Bridge
 * lease; standalone panels acquire the same reference-counted polling owner. */
import { useCallback, useEffect, useRef } from 'react';
import { useStore, isCapabilityRequestView, type DecidedApproval } from '../../store/useStore';
import type { CapabilityApprovalView } from '../../store/types';
import { acquireApprovalPolling } from '../../store/approvalPolling';
import { resourceMessage } from '../../utils/resourceState';
import { ApprovalRefreshGlyph } from '../skill/SkillRequestPanel';
import { CapabilityRequestCard } from './CapabilityRequestCard';
import { HxiApprovalFocus } from '../approvals/HxiApprovalFocus';

export type CapabilityRequestView = CapabilityApprovalView;

export default function CapabilityRequestPanel(
  { onDecided, hosted = false }: { onDecided?: (decided: DecidedApproval) => void; hosted?: boolean } = {},
): React.JSX.Element {
  const resource = useStore(state => state.approvalResources.capability);
  const feedback = useStore(state => state.capabilityDecisionFeedback);
  const manualRead = useRef<AbortController | null>(null);
  const refreshButton = useRef<HTMLButtonElement | null>(null);
  useEffect(() => hosted ? undefined : acquireApprovalPolling(['capability']), [hosted]);
  useEffect(() => () => manualRead.current?.abort(), []);
  const load = useCallback(() => {
    manualRead.current?.abort();
    manualRead.current = new AbortController();
    return useStore.getState().refreshPendingApprovals({ queues: ['capability'], signal: manualRead.current.signal });
  }, []);
  const requests = resource.data?.requests.filter(isCapabilityRequestView) ?? [];
  const rows = new Map(requests.map(request => [request.id, request]));
  const ids = [...rows.keys(), ...[...feedback.keys()].filter(id => !rows.has(id))];
  return <div data-testid="capability-request-panel" style={{ padding: '8px 0' }}>
    <HxiApprovalFocus />
    <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, color: '#f0b060', fontWeight: 700, marginBottom: 6 }}>
      Capability Requests
      <button ref={refreshButton} type="button" aria-label="Refresh capability requests" title="Refresh capability requests"
        onClick={() => { void load(); }} data-hxi-focus=""
        style={{ background: 'none', border: 'none', color: '#f0b060', cursor: 'pointer', marginLeft: 8 }}>
        <ApprovalRefreshGlyph />
      </button>
    </div>
    <div role="status" aria-label="Capability requests status" style={{ fontSize: 11, color: '#666680', marginBottom: 6 }}>
      {resource.status === 'empty' ? 'No capability requests pending.' : resourceMessage(resource.status)}
      {(resource.stale || resource.refreshing) && ' Showing last-known capability requests; current count unknown.'}
      {resource.observedAt !== null && (resource.stale || resource.refreshing)
        && ` Last successful observation: ${new Date(resource.observedAt).toLocaleTimeString()}.`}
    </div>
    {ids.map(id => <CapabilityRequestCard key={id} requestId={id} request={rows.get(id)}
      onDecided={onDecided} onRetired={() => refreshButton.current?.focus()} />)}
  </div>;
}
