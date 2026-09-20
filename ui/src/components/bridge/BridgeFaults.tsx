import { ChevronDown, ChevronRight } from '../icons/Glyphs';
import { ApprovalRefreshGlyph } from '../skill/SkillRequestPanel';
import { resourceMessage } from '../../utils/resourceState';
import type { FaultDetail, FaultReports, FaultSummary } from '../../hooks/useFaultReports';

const BUTTON: React.CSSProperties = {
  appearance: 'none', background: 'none', border: '1px solid rgba(255,255,255,0.15)',
  borderRadius: 3, padding: '6px 8px', color: '#c8cee0', font: 'inherit',
  textAlign: 'left', cursor: 'pointer', overflowWrap: 'anywhere',
};
const EVIDENCE: React.CSSProperties = {
  whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', margin: '4px 0 10px',
  font: 'inherit', lineHeight: 1.5,
};

function IssueLink({ fault }: { fault: FaultSummary }): React.ReactNode {
  if (!fault.issue_lookup_available) return <span>Issue link lookup unavailable.</span>;
  if (!fault.issue) return <span>No confirmed issue link.</span>;
  return <a data-hxi-focus="" href={fault.issue.url} target="_blank" rel="noopener noreferrer"
    style={{ color: '#80b8e0', overflowWrap: 'anywhere' }}>
    Issue {fault.issue.repository}#{fault.issue.number}
  </a>;
}

function Detail({ fault }: { fault: FaultDetail }): React.ReactNode {
  return <>
    <dl style={{ margin: '8px 0', overflowWrap: 'anywhere' }}>
      <dt>Tool</dt><dd style={EVIDENCE}>{fault.tool_id || 'Not recorded'}</dd>
      <dt>Status</dt><dd style={EVIDENCE}>{fault.status}</dd>
      <dt>Recorded occurrences</dt><dd style={EVIDENCE}>{fault.occurrences}</dd>
      <dt>Recorded agent</dt><dd style={EVIDENCE}>{fault.recorded_agent_id || 'Not recorded'}</dd>
      <dt>Thread</dt><dd style={EVIDENCE}>{fault.thread_id || 'Not recorded'}</dd>
      <dt>Work item</dt><dd style={EVIDENCE}>{fault.work_item_id || 'Not recorded'}</dd>
      {fault.observed_as && <><dt>Observed as</dt><dd style={EVIDENCE}>{fault.observed_as}</dd></>}
      <dt>Fault ID</dt><dd style={EVIDENCE}>{fault.id}</dd>
      <dt>Signature</dt><dd style={EVIDENCE}>{fault.signature}</dd>
    </dl>
    <strong>Error evidence</strong><pre style={EVIDENCE}>{fault.error_text || 'Not recorded'}</pre>
    <strong>Attempted operation</strong><pre style={EVIDENCE}>{fault.attempted || 'Not recorded'}</pre>
    <strong>Stored trace sample</strong><pre style={EVIDENCE}>{fault.trace_summary}</pre>
    <p style={EVIDENCE}>
      The recorded agent and stored trace sample may describe different occurrences,
      not every occurrence. Stored evidence may already be bounded.
    </p>
    {fault.clipped_fields.length > 0 && <p style={EVIDENCE}>
      Additional display clipping: {fault.clipped_fields.join(', ')}.
    </p>}
  </>;
}

export function BridgeFaults({ reports }: { reports: FaultReports }): React.ReactNode {
  const { resource, detail, selectedId } = reports;
  const known = resource.status === 'ready' || resource.status === 'empty';
  const page = resource.data;
  const detailKnown = detail.status === 'ready';
  return <div data-testid="bridge-faults" style={{ fontSize: 11, color: '#c8cee0', minWidth: 0 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0' }}>
      <div role="status" aria-label="Fault reports status" style={{ flex: 1, overflowWrap: 'anywhere' }}>
        {known ? `${page?.total ?? 0} current fault records.` : `${resourceMessage(resource.status)} Current count unknown.`}
        {!known && page && ` Last-known record total: ${page.total}. Stale.`}
        {resource.refreshing && ' Refreshing.'}
        {reports.paused && ' Automatic refresh paused.'}
      </div>
      <button type="button" data-hxi-focus="" aria-label="Refresh fault reports"
        title="Refresh fault reports" onClick={reports.refresh} style={BUTTON}>
        <ApprovalRefreshGlyph />
      </button>
    </div>
    {page?.faults.map(row => {
      const expanded = row.id === selectedId;
      const evidence = expanded && detail.data?.fault.id === row.id ? detail.data.fault : null;
      // Expanded linkage follows its own refreshed receipt, not a stale list row.
      const linked = evidence ?? row;
      return <article key={row.id} data-fault-id={row.id}
        style={{ borderTop: '1px solid rgba(255,255,255,0.08)', padding: '8px 0', minWidth: 0 }}>
        <button type="button" data-hxi-focus="" aria-expanded={expanded}
          aria-controls={`fault-detail-${row.id}`} onClick={() => reports.select(row.id)}
          style={{ ...BUTTON, display: 'flex', gap: 6, alignItems: 'baseline', width: '100%' }}>
          <span aria-hidden="true">{expanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}</span>
          <span>{row.summary}</span>
        </button>
        <div style={{ padding: '6px 8px', overflowWrap: 'anywhere' }}>
          {expanded && evidence && !detailKnown && <span>Last-known link: </span>}
          <IssueLink fault={linked} />
        </div>
        {expanded && <div id={`fault-detail-${row.id}`} role="region" aria-label="Fault evidence"
          style={{ padding: '0 8px', minWidth: 0 }}>
          {!detailKnown && <p role="status" aria-label="Fault detail status">
            {resourceMessage(detail.status)} {evidence ? 'Last-known evidence. Stale.' : 'Evidence not loaded.'}
            {reports.detailPaused && ' Automatic refresh paused.'}
          </p>}
          {detail.refreshing && <p role="status">Refreshing stored evidence.</p>}
          {evidence && <Detail fault={evidence} />}
        </div>}
      </article>;
    })}
    {page && page.total > 0 && <nav aria-label="Fault pages"
      style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, padding: '8px 0' }}>
      <button type="button" data-hxi-focus="" onClick={reports.previousPage}
        disabled={!known || page.offset === 0} style={BUTTON}>Previous faults</button>
      <span>{page.faults.length > 0
        ? `${page.offset + 1}–${page.offset + page.faults.length} of ${page.total}`
        : `Page no longer populated; locating ${page.total} current records.`}</span>
      <button type="button" data-hxi-focus="" onClick={reports.nextPage}
        disabled={!known || page.offset + page.limit >= page.total} style={BUTTON}>Next faults</button>
    </nav>}
  </div>;
}
