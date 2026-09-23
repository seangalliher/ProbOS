/**
 * AD-1083: room Todo checklist rows — the AD-1080 senior-validation loop made
 * visible in the workspace sidecar. Each row: status glyph + label + (for a
 * submitted step) Confirm / Reject affordances for the Captain. Done = green
 * check, rejected = red x, submitted = amber dot (awaiting validation),
 * in_progress = amber ring, pending = dim ring.
 *
 * HXI Design Principle #3 — inline stroke-SVG glyphs only, no emoji.
 */
import { useState } from 'react';
import type { TodoStep } from './todosApi';
import {
  OwnedStepsApiError,
  applyOwnedProposal,
  fetchOwnedRepair,
  fetchOwnedStepDetail,
  finalizeOwnedSteps,
  newOwnedOperationId,
  previewOwnedProposal,
  sendOwnedCommands,
  type ManagedOwnedStepsView,
  type OwnedRowCommand,
  type ProposalPage,
} from './ownedStepsApi';

const AMBER = '#f0b060';
const DIM = '#666680';
const GREEN = '#60c070';
const RED = '#d05050';

const COMMON = {
  width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none',
  stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
};

function statusGlyph(status: TodoStep['status']) {
  if (status === 'done') {
    return <svg {...COMMON} style={{ color: GREEN }} aria-label="done"><path d="M20 6L9 17l-5-5" /></svg>;
  }
  if (status === 'rejected') {
    return <svg {...COMMON} style={{ color: RED }} aria-label="rejected"><path d="M6 6l12 12M18 6L6 18" /></svg>;
  }
  if (status === 'submitted') {
    return <svg {...COMMON} style={{ color: AMBER }} aria-label="awaiting review"><circle cx="12" cy="12" r="9" /><path d="M12 8v4l3 2" /></svg>;
  }
  if (status === 'in_progress') {
    return <svg {...COMMON} style={{ color: AMBER }} aria-label="in progress"><circle cx="12" cy="12" r="9" /></svg>;
  }
  return <svg {...COMMON} style={{ color: DIM }} aria-label="pending"><circle cx="12" cy="12" r="9" /></svg>;
}

export interface TodosListProps {
  steps: TodoStep[];
  onConfirm: (index: number) => void;
  onReject: (index: number) => void;
}

export function TodosList(props: TodosListProps) {
  const { steps, onConfirm, onReject } = props;
  if (steps.length === 0) {
    return (
      <div data-testid="todos-empty" style={{ fontSize: 11, color: DIM, padding: '6px 10px' }}>
        No todos yet.
      </div>
    );
  }
  return (
    <ul data-testid="todos-list" style={{ listStyle: 'none', margin: 0, padding: '2px 0' }}>
      {steps.map((s, i) => (
        <li key={i} data-testid={`todo-row-${i}`}
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px' }}>
          <span style={{ flex: '0 0 auto', display: 'inline-flex' }}>{statusGlyph(s.status)}</span>
          <span style={{
            flex: '1 1 auto', fontSize: 11,
            color: s.status === 'done' ? DIM : '#cfcfe0',
            textDecoration: s.status === 'done' ? 'line-through' : 'none',
          }}>
            {i + 1}. {s.label}
          </span>
          {s.status === 'submitted' && (
            <span style={{ flex: '0 0 auto', display: 'inline-flex', gap: 4 }}>
              <button type="button" data-testid={`todo-confirm-${i}`} title="Confirm"
                onClick={() => onConfirm(i)}
                style={{ background: 'transparent', border: 'none', color: GREEN, cursor: 'pointer', padding: 2 }}>
                <svg {...COMMON} aria-label="confirm"><path d="M20 6L9 17l-5-5" /></svg>
              </button>
              <button type="button" data-testid={`todo-reject-${i}`} title="Send back"
                onClick={() => onReject(i)}
                style={{ background: 'transparent', border: 'none', color: RED, cursor: 'pointer', padding: 2 }}>
                <svg {...COMMON} aria-label="reject"><path d="M6 6l12 12M18 6L6 18" /></svg>
              </button>
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

export interface OwnedStepsPanelProps {
    taskId: string;
    view: ManagedOwnedStepsView;
    onRefresh: () => Promise<void>;
    onNavigate: (cursor: string | null) => Promise<void>;
  }

  function ownedErrorFeedback(error: unknown): string {
    if (error instanceof OwnedStepsApiError) return error.feedback;
    return error instanceof Error ? error.message : 'Owned steps request failed.';
  }

  function rowCommandLabel(kind: OwnedRowCommand['kind']): string {
    switch (kind) {
      case 'manual_submit': return 'Submit';
      case 'manual_confirm': return 'Confirm';
      case 'manual_reject': return 'Reject';
      case 'edit_note': return 'Edit note';
      case 'reassign_unstarted': return 'Reassign';
      case 'cancel_execution': return 'Cancel execution';
      case 'pause_accounting': return 'Pause BOOKING CLOCK ONLY; worker continues';
      case 'resume_accounting': return 'Resume BOOKING CLOCK ONLY; worker continues';
      case 'abandon': return 'Abandon';
    }
  }

export function OwnedStepsPanel({
    taskId,
    view,
    onRefresh,
    onNavigate,
  }: OwnedStepsPanelProps) {
    const [busy, setBusy] = useState(false);
    const [feedback, setFeedback] = useState('');
    const [proposal, setProposal] = useState<ProposalPage | null>(null);
    const [repairOpen, setRepairOpen] = useState(false);
    const [repairPrefix, setRepairPrefix] = useState('');
    const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
    const [proposalOperationId, setProposalOperationId] = useState('');

    const run = async (operation: () => Promise<void>, refreshAfter = false): Promise<void> => {
      if (busy) return;
      setBusy(true);
      setFeedback('');
      try {
        await operation();
        if (refreshAfter) await onRefresh();
      } catch (error) {
        setFeedback(ownedErrorFeedback(error));
      } finally {
        setBusy(false);
      }
    };

    const runCommand = async (
      row: ManagedOwnedStepsView['rows'][number],
      kind: OwnedRowCommand['kind'],
    ): Promise<void> => {
      let command: OwnedRowCommand;
      const identity = {
        operation_id: newOwnedOperationId(kind),
        step_id: row.step_id,
      };
      if (kind === 'manual_reject' || kind === 'edit_note') {
        const note = window.prompt(kind === 'manual_reject' ? 'Rejection reason' : 'Step note');
        if (note === null || (kind === 'manual_reject' && !note.trim())) return;
        command = { ...identity, kind, note };
      } else if (kind === 'reassign_unstarted') {
        const assignee_id = window.prompt('New assignee ID');
        if (!assignee_id?.trim()) return;
        command = { ...identity, kind, assignee_id: assignee_id.trim() };
      } else if (kind === 'pause_accounting' || kind === 'resume_accounting') {
        const booking_id = row.evidence.booking_id;
        const resource_id = row.todo.assigned_to;
        if (!booking_id || !resource_id) {
          setFeedback('Booking clock control is unavailable because its exact booking or resource binding is missing.');
          return;
        }
        command = { ...identity, kind, booking_id, resource_id };
      } else {
        command = { ...identity, kind };
      }
      await run(async () => {
        await sendOwnedCommands(taskId, view.reference, [command]);
      }, true);
    };

    const prepare = async (
      kind: 'adopt_existing' | 'replan_unstarted',
    ): Promise<void> => {
      await run(async () => {
        const next = await previewOwnedProposal(taskId, {
          version: 1,
          kind,
          preparation_id: newOwnedOperationId(`prepare-${kind}`),
          reference: view.reference,
        });
        setProposal(next);
        setProposalOperationId(newOwnedOperationId(`apply-${kind}`));
      });
    };

    const inspectProposal = async (cursor?: string): Promise<void> => {
      if (!proposal) return;
      await run(async () => {
        setProposal(await previewOwnedProposal(taskId, {
          version: 1,
          kind: 'inspect_proposal',
          proposal: proposal.proposal,
          ...(cursor === undefined ? {} : { cursor }),
        }));
      });
    };

    const applyProposal = async (): Promise<void> => {
      if (!proposal?.reference) return;
      await run(async () => {
        await applyOwnedProposal(taskId, {
          version: 1,
          operation_id: proposalOperationId,
          reference: proposal.reference!,
        }, proposal.kind);
        setProposal(null);
        setProposalOperationId('');
        setRepairOpen(false);
      }, true);
    };

    const openRepair = async (): Promise<void> => {
      await run(async () => {
        const repair = await fetchOwnedRepair(taskId);
        setRepairPrefix(repair.raw_steps ?? '');
        setRepairOpen(true);
        setProposal(null);
        setProposalOperationId('');
        if (repair.omissions.length) {
          setFeedback(`Readonly evidence omitted: ${repair.omissions.join(', ')}.`);
        }
      });
    };

    const previewRepair = async (): Promise<void> => {
      await run(async () => {
        const repair = await fetchOwnedRepair(taskId);
        setProposal(await previewOwnedProposal(taskId, {
          version: 1,
          kind: 'replace_manual_prefix',
          preparation_id: newOwnedOperationId('prepare-prefix'),
          reference: repair.reference,
          prefix_json: repairPrefix,
        }));
        setProposalOperationId(newOwnedOperationId('apply-replace_manual_prefix'));
      });
    };

    const allowedRowActions = (
      row: ManagedOwnedStepsView['rows'][number],
    ): OwnedRowCommand['kind'][] => {
      const known: OwnedRowCommand['kind'][] = [
        'manual_submit', 'manual_confirm', 'manual_reject', 'edit_note',
        'reassign_unstarted', 'cancel_execution', 'pause_accounting',
        'resume_accounting', 'abandon',
      ];
      return known.filter(kind => row.actions.includes(kind))
        .filter(kind => row.kind === 'manual'
          || !['manual_submit', 'manual_confirm', 'manual_reject', 'edit_note'].includes(kind));
    };

    return (
      <div data-testid="owned-steps-panel" style={{ fontSize: 11, color: '#cfcfe0' }}>
        <div style={{ padding: '4px 10px', color: AMBER }}>
          Managed steps · {view.mode} · page {view.rows.length}
        </div>
        {feedback && (
          <div role="alert" data-testid="owned-steps-feedback"
            style={{ margin: '4px 10px', padding: 6, color: '#f08b8b', border: '1px solid rgba(208,80,80,.35)' }}>
            {feedback}
          </div>
        )}
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {view.rows.map(row => (
            <li key={row.step_id} data-testid={`owned-step-${row.step_id}`}
              style={{ padding: '5px 10px', borderTop: '1px solid rgba(255,255,255,.05)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span>{statusGlyph(row.todo.status)}</span>
                <span style={{ flex: 1 }}>{row.ordinal}. {row.todo.label}</span>
                <span style={{ color: DIM }}>{row.kind}</span>
              </div>
              {row.todo.note && <div style={{ color: DIM, marginLeft: 20 }}>{row.todo.note}</div>}
              {row.kind === 'child' && row.evidence.review_accepted !== true && (
                <div data-testid={`owned-child-verdict-${row.step_id}`} style={{ color: DIM, marginLeft: 20 }}>
                  Independent verdict controls this row.
                </div>
              )}
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
                {allowedRowActions(row).map(kind => (
                  <button type="button" key={kind} disabled={busy}
                    data-testid={`owned-${kind}-${row.step_id}`}
                    onClick={() => { void runCommand(row, kind); }}>
                    {rowCommandLabel(kind)}
                  </button>
                ))}
                <button type="button" disabled={busy}
                  data-testid={`owned-detail-${row.step_id}`}
                  onClick={() => {
                    void run(async () => {
                      setDetail(await fetchOwnedStepDetail(taskId, row.step_id));
                    });
                  }}>
                  Detail
                </button>
              </div>
            </li>
          ))}
        </ul>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', padding: '6px 10px' }}>
          {view.previous_cursor !== null && (
            <button type="button" disabled={busy} data-testid="owned-page-previous"
              onClick={() => { void run(() => onNavigate(view.previous_cursor)); }}>Previous</button>
          )}
          {view.next_cursor !== null && (
            <button type="button" disabled={busy} data-testid="owned-page-next"
              onClick={() => { void run(() => onNavigate(view.next_cursor)); }}>Next</button>
          )}
          {view.mode === 'awaiting_adoption' && (
            <button type="button" disabled={busy} data-testid="owned-preview-adopt"
              onClick={() => { void prepare('adopt_existing'); }}>Preview adoption</button>
          )}
          {view.recovery.includes('replan_unstarted') && (
            <button type="button" disabled={busy} data-testid="owned-preview-replan"
              onClick={() => { void prepare('replan_unstarted'); }}>Preview unstarted replan</button>
          )}
          {(view.recovery.includes('replace_manual_prefix') || view.recovery.includes('inspect_source')) && (
            <button type="button" disabled={busy} data-testid="owned-open-repair"
              onClick={() => { void openRepair(); }}>Readonly repair evidence</button>
          )}
          {(view.finalization === 'pending' || view.mode === 'waiting_manual_gate') && (
            <button type="button" disabled={busy} data-testid="owned-finalize"
              onClick={() => {
                void run(async () => {
                  const disposition = await finalizeOwnedSteps(taskId, view.reference);
                  setFeedback(`Finalize-only result: ${disposition}.`);
                }, true);
              }}>
              Retry finalize only
            </button>
          )}
          <button type="button" disabled={busy} data-testid="owned-refresh"
            onClick={() => { void run(onRefresh); }}>Refresh view</button>
        </div>
        {detail && (
          <pre data-testid="owned-step-detail"
            style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', padding: 8, color: DIM }}>
            {JSON.stringify(detail, null, 2)}
          </pre>
        )}
        {repairOpen && (
          <div data-testid="owned-repair-editor" style={{ padding: 8 }}>
            <div style={{ color: AMBER }}>Readonly source evidence; correction is a separate proposal.</div>
            <textarea aria-label="Exact replacement prefix JSON" value={repairPrefix}
              onChange={event => setRepairPrefix(event.target.value)}
              style={{ width: '100%', minHeight: 90, boxSizing: 'border-box' }} />
            <button type="button" disabled={busy} data-testid="owned-preview-repair"
              onClick={() => { void previewRepair(); }}>Preview exact prefix correction</button>
          </div>
        )}
        {proposal && (
          <div data-testid="owned-proposal" style={{ padding: 8, borderTop: '1px solid rgba(240,176,96,.2)' }}>
            <div>{proposal.kind} · {proposal.state}</div>
            <div>
              {proposal.manual_count} manual · {proposal.child_count} active children · {proposal.retired_count} retired
            </div>
            {proposal.omissions.length > 0 && <div>Omissions: {proposal.omissions.join(', ')}</div>}
            <button type="button" disabled={busy} data-testid="owned-inspect-proposal"
              onClick={() => { void inspectProposal(); }}>Inspect persisted proposal</button>
            {proposal.previous_cursor !== null && (
              <button type="button" disabled={busy}
                onClick={() => { void inspectProposal(proposal.previous_cursor!); }}>Previous proposal page</button>
            )}
            {proposal.next_cursor !== null && (
              <button type="button" disabled={busy}
                onClick={() => { void inspectProposal(proposal.next_cursor!); }}>Next proposal page</button>
            )}
            {proposal.reference && proposal.state === 'ready' && (
              <button type="button" disabled={busy} data-testid="owned-apply-proposal"
                onClick={() => { void applyProposal(); }}>Apply exact proposal</button>
            )}
          </div>
        )}
      </div>
    );
}

export function OwnedStepsRecoveryPanel({
    taskId,
    actions,
    onRefresh,
}: {
    taskId: string;
    actions: string[];
    onRefresh: () => Promise<void>;
}) {
    const [busy, setBusy] = useState(false);
    const [feedback, setFeedback] = useState('');
    const [prefix, setPrefix] = useState('');
    const [repairReference, setRepairReference] = useState<Awaited<ReturnType<typeof fetchOwnedRepair>>['reference'] | null>(null);
    const [proposal, setProposal] = useState<ProposalPage | null>(null);
    const [proposalOperationId, setProposalOperationId] = useState('');

    const run = async (operation: () => Promise<void>): Promise<void> => {
      if (busy) return;
      setBusy(true);
      setFeedback('');
      try {
        await operation();
      } catch (error) {
        setFeedback(ownedErrorFeedback(error));
      } finally {
        setBusy(false);
      }
    };

    const loadEvidence = async (): Promise<void> => {
      await run(async () => {
        const repair = await fetchOwnedRepair(taskId);
        setRepairReference(repair.reference);
        setPrefix(repair.raw_steps ?? '');
        if (repair.omissions.length) {
          setFeedback(`Readonly evidence omitted: ${repair.omissions.join(', ')}.`);
        }
      });
    };

    const preview = async (
      kind: 'replace_manual_prefix' | 'replan_unstarted',
    ): Promise<void> => {
      if (!repairReference) return;
      await run(async () => {
        const next = await previewOwnedProposal(
          taskId,
          kind === 'replace_manual_prefix'
            ? {
              version: 1,
              kind,
              preparation_id: newOwnedOperationId(`prepare-${kind}`),
              reference: repairReference,
              prefix_json: prefix,
            }
            : {
              version: 1,
              kind,
              preparation_id: newOwnedOperationId(`prepare-${kind}`),
              reference: repairReference,
            },
        );
        setProposal(next);
        setProposalOperationId(newOwnedOperationId(`apply-${kind}`));
      });
    };

    const apply = async (): Promise<void> => {
      if (!proposal?.reference) return;
      await run(async () => {
        await applyOwnedProposal(taskId, {
          version: 1,
          operation_id: proposalOperationId,
          reference: proposal.reference!,
        }, proposal.kind);
        setProposal(null);
        setProposalOperationId('');
        await onRefresh();
      });
    };

    return (
      <div data-testid="owned-steps-recovery" style={{ padding: '6px 10px', fontSize: 11 }}>
        {feedback && <div role="alert" style={{ color: '#f08b8b' }}>{feedback}</div>}
        {!repairReference ? (
          <button type="button" disabled={busy} data-testid="owned-load-repair"
            onClick={() => { void loadEvidence(); }}>
            Load readonly repair evidence
          </button>
        ) : (
          <>
            <textarea aria-label="Exact recovery prefix JSON" value={prefix}
              onChange={event => setPrefix(event.target.value)}
              style={{ width: '100%', minHeight: 90, boxSizing: 'border-box' }} />
            {actions.includes('replace_manual_prefix') && (
              <button type="button" disabled={busy} data-testid="owned-recovery-preview-prefix"
                onClick={() => { void preview('replace_manual_prefix'); }}>
                Preview exact prefix correction
              </button>
            )}
            {actions.includes('replan_unstarted') && (
              <button type="button" disabled={busy} data-testid="owned-recovery-preview-replan"
                onClick={() => { void preview('replan_unstarted'); }}>
                Preview unstarted replan
              </button>
            )}
          </>
        )}
        {proposal && (
          <div data-testid="owned-recovery-proposal">
            <div>{proposal.kind} · {proposal.state}</div>
            <button type="button" disabled={busy} data-testid="owned-recovery-inspect"
              onClick={() => {
                void run(async () => {
                  setProposal(await previewOwnedProposal(taskId, {
                    version: 1,
                    kind: 'inspect_proposal',
                    proposal: proposal.proposal,
                  }));
                });
              }}>
              Inspect persisted proposal
            </button>
            {proposal.reference && proposal.state === 'ready' && (
              <button type="button" disabled={busy} data-testid="owned-recovery-apply"
                onClick={() => { void apply(); }}>
                Apply exact proposal
              </button>
            )}
          </div>
        )}
      </div>
    );
}
