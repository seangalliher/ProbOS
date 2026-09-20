import { useEffect, useState, type ReactElement } from 'react';
import { useStore } from '../../store/useStore';
import { useSettingsStore } from '../../store/useSettingsStore';
import { selectThreadToolProgress } from '../../store/liveToolProgress';

interface Props {
  threadId: string | null;
  participantIds: readonly string[] | null;
}

export function LiveToolProgress({ threadId, participantIds }: Props): ReactElement {
  const state = useStore(s => s.toolProgress);
  const connected = useStore(s => s.connected);
  const agents = useStore(s => s.agents);
  const enabled = useSettingsStore(s => s.snapshot?.config?.agentic_loop?.event_correlation_enabled);
  const loadSnapshot = useSettingsStore(s => s.loadSnapshot);
  const [, tick] = useState(0);
  const progress = selectThreadToolProgress(state, threadId, participantIds);
  const deadlines = progress.calls.filter(call => call.status === 'started' && call.startedAt !== null)
    .map(call => call.startedAt! + 30_000);
  const nextDeadline = deadlines.length ? Math.min(...deadlines) : null;

  useEffect(() => { void loadSnapshot(); }, [loadSnapshot]);
  useEffect(() => {
    if (nextDeadline === null) return;
    const timer = setTimeout(() => tick(value => value + 1), Math.max(1, nextDeadline - Date.now()));
    return () => clearTimeout(timer);
  }, [nextDeadline]);

  const labels = {
    started: 'Start observed',
    completed: 'Completed',
    error: 'Tool error',
    'completion-unconfirmed': 'Completion unconfirmed',
  };
  const active = progress.calls.filter(call => call.status === 'started').length;
  const completed = progress.calls.filter(call => call.status === 'completed').length;
  const errors = progress.calls.filter(call => call.status === 'error').length;
  const unconfirmed = progress.calls.filter(call => call.status === 'completion-unconfirmed').length;
  return (
    <section
      aria-label="Live tool progress"
      style={{
        padding: '6px 12px', fontSize: 12, color: '#c4c4d4', minHeight: 0,
        maxHeight: 'min(190px, 28%)', overflowY: 'auto', overflowWrap: 'anywhere',
        borderBottom: '1px solid rgba(255,255,255,0.08)', flexShrink: 1,
      }}
    >
      <div role="status" aria-live="polite">
        {!progress.associated
          ? 'Thread association unverified. Live tool progress is unknown.'
          : progress.calls.length === 0
            ? 'No tool activity observed for this conversation.'
            : `Tool observations: ${active} started, ${completed} completed, ${errors} errors, ${unconfirmed} completion unconfirmed.`}
      </div>
      {enabled === false && (
        <p>Live tool progress is off in saved settings. Enable event correlation and restart the runtime to receive new observations.</p>
      )}
      {enabled !== false && enabled !== true && (
        <p>Live tool progress availability is unknown. Configuration could not be verified.</p>
      )}
      {enabled === true && progress.calls.length === 0 && (
        <p>Saved configuration is not activity evidence. A runtime restart may be required.</p>
      )}
      {(!connected || progress.incomplete) && (
        <p>{!connected ? 'Event stream disconnected. ' : ''}Delivery is incomplete; absence of an update does not mean idle.</p>
      )}
      {(progress.omittedRuns > 0 || progress.omittedCalls > 0) && (
        <p>Retained history is limited: {progress.omittedRuns} run records and {progress.omittedCalls} call records omitted.</p>
      )}
      {progress.calls.length > 0 && (
        <details>
          <summary>Tool activity details ({progress.calls.length})</summary>
          <p>These are tool observations, not confirmation that the task succeeded or was delivered.</p>
          <ul aria-label="Observed tool calls" style={{ paddingLeft: 18 }}>
            {progress.calls.map(call => (
              <li key={call.key} style={{ margin: '6px 0', color: call.status === 'error' ? '#f4a1a1' : '#c4c4d4' }}>
                <span>{agents.get(call.participantId)?.callsign || agents.get(call.participantId)?.displayName || 'Participant'}</span>
                {' — '}<span>{call.toolId}</span>{': '}
                <strong>{labels[call.status]}</strong>
                {call.completionBeforeStart && <span>. Completion arrived without an observed start.</span>}
                {!call.fresh && <span>. Earlier observation; current delivery unverified.</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
