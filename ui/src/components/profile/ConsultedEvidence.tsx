import { useState } from 'react';
import type { AgentProfileMessage } from '../../store/types';
import { CONSULTED_TRACE_REF_PATTERN, useConsultedTrace } from '../../hooks/useConsultedTrace';
import { HxiApprovalFocus } from '../approvals/HxiApprovalFocus';

const AMBER = '#f0b060';
const DIM = '#666680';
const MUTED_VIOLET = '#6a5a8a';
const WARN = '#c07050';

type RefCandidate =
  | { kind: 'absent' }
  | { kind: 'malformed' }
  | { kind: 'valid'; ref: string };

function candidateRefOf(msg: AgentProfileMessage): RefCandidate {
  const value = msg.metadata?.tool_trace_ref;
  if (value === undefined || value === null) return { kind: 'absent' };
  if (typeof value !== 'string' || !CONSULTED_TRACE_REF_PATTERN.test(value)) {
    return { kind: 'malformed' };
  }
  return { kind: 'valid', ref: value };
}

function hasExplicitBinding(
  msg: AgentProfileMessage,
  activeThreadId: string | undefined,
): boolean {
  return msg.role === 'agent'
    && typeof msg.id === 'string'
    && msg.id.trim().length > 0
    && typeof msg.authorId === 'string'
    && msg.authorId.trim().length > 0
    && typeof msg.threadId === 'string'
    && msg.threadId.trim().length > 0
    && typeof activeThreadId === 'string'
    && activeThreadId.length > 0
    && msg.threadId === activeThreadId;
}

export function ConsultedEvidence({ msg, activeThreadId }: {
  msg: AgentProfileMessage;
  activeThreadId?: string;
}): React.JSX.Element | null {
  const bound = hasExplicitBinding(msg, activeThreadId);
  const candidate = bound ? candidateRefOf(msg) : { kind: 'absent' } as const;
  const candidateIdentity = candidate.kind === 'valid' ? candidate.ref : candidate.kind;
  const ownerKey = candidate.kind !== 'absent'
    ? JSON.stringify([msg.id, msg.threadId, msg.authorId, candidateIdentity])
    : '';
  const [owner, setOwner] = useState(ownerKey);
  const [expanded, setExpanded] = useState(false);
  const ownerChanged = owner !== ownerKey;
  if (ownerChanged) {
    setOwner(ownerKey);
    setExpanded(false);
  }

  const disclosed = ownerChanged ? false : expanded;
  const ref = candidate.kind === 'valid' ? candidate.ref : null;
  const { state, retry } = useConsultedTrace(ref, disclosed, ownerKey);

  if (candidate.kind === 'absent') return null;
  if (candidate.kind === 'malformed') {
    return (
      <div style={{ marginTop: 4, fontSize: 10, color: WARN }}>
        Receipt unavailable. The receipt reference on this message is unreadable.
      </div>
    );
  }

  const bodyId = `consulted-evidence-${msg.id}`;
  return (
    <div style={{ marginTop: 4 }}>
      <HxiApprovalFocus />
      <button
        type="button"
        data-hxi-focus
        aria-expanded={disclosed}
        aria-controls={bodyId}
        onClick={() => setExpanded((was) => !was)}
        style={{
          fontFamily: 'inherit',
          fontSize: 10,
          borderRadius: 4,
          padding: '3px 6px',
          background: 'rgba(0,0,0,0.2)',
          color: disclosed ? AMBER : DIM,
          border: `1px solid ${disclosed ? 'rgba(240,176,96,0.35)' : 'rgba(255,255,255,0.1)'}`,
          cursor: 'pointer',
        }}
      >
        {disclosed ? 'Hide consulted evidence' : 'Show consulted evidence'}
      </button>
      {disclosed && (
        <div id={bodyId} style={{ marginTop: 4, fontSize: 10, color: DIM }}>
          <ConsultedEvidenceBody state={state} retry={retry} />
        </div>
      )}
    </div>
  );
}

function ConsultedEvidenceBody({ state, retry }: {
  state: ReturnType<typeof useConsultedTrace>['state'];
  retry: () => Promise<void>;
}): React.JSX.Element {
  if (state.status === 'idle' || state.status === 'loading') {
    return <span>{'Loading consulted evidence\u2026'}</span>;
  }
  if (state.status === 'ready' || state.status === 'empty') {
    const data = state.data;
    if (!data) return <span>Receipt unavailable.</span>;
    return (
      <div>
        {data.requests.length > 0 ? (
          <ul style={{ margin: '2px 0', paddingLeft: 16 }}>
            {data.requests.map((entry, index) => (
              <li key={index} style={{ wordBreak: 'break-word' }}>{entry}</li>
            ))}
          </ul>
        ) : (
          <span>No requests recorded.</span>
        )}
        <div style={{ marginTop: 2, color: MUTED_VIOLET }}>{data.notice}</div>
      </div>
    );
  }
  return (
    <div>
      <span>Receipt unavailable.</span>
      {state.retryable && (
        <button
          type="button"
          data-hxi-focus
          onClick={() => { void retry(); }}
          style={{
            fontFamily: 'inherit',
            fontSize: 10,
            borderRadius: 4,
            padding: '2px 5px',
            marginLeft: 6,
            background: 'rgba(0,0,0,0.2)',
            color: AMBER,
            border: '1px solid rgba(240,176,96,0.35)',
            cursor: 'pointer',
          }}
        >
          Retry
        </button>
      )}
    </div>
  );
}
