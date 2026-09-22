import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../ownedStepsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../ownedStepsApi')>();
  return {
    ...actual,
    sendOwnedCommands: vi.fn(),
    previewOwnedProposal: vi.fn(),
    applyOwnedProposal: vi.fn(),
    fetchOwnedRepair: vi.fn(),
    fetchOwnedStepDetail: vi.fn(),
    finalizeOwnedSteps: vi.fn(),
    newOwnedOperationId: vi.fn((prefix: string) => `${prefix}-operation`),
  };
});

import { OwnedStepsPanel, OwnedStepsRecoveryPanel } from '../TodosList';
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
  type ProposalPage,
} from '../ownedStepsApi';

const digest = (character: string) => character.repeat(64);
const reference = {
  version: 1 as const,
  parent_id: 'parent-1',
  actor_id: 'captain',
  thread_id: '',
  turn_id: 'http-owner',
  view_id: 'view-1',
  content_hash: digest('a'),
};

function row(
  stepId: string,
  kind: 'manual' | 'child',
  actions: string[],
  status: 'pending' | 'in_progress' | 'submitted' | 'done' | 'rejected' = 'submitted',
) {
  return {
    step_id: stepId,
    ordinal: kind === 'manual' ? 1 : 2,
    kind,
    child_id: kind === 'child' ? 'child-1' : null,
    revision: 1,
    digest: digest(kind === 'manual' ? 'b' : 'c'),
    todo: {
      label: kind === 'manual' ? 'Captain review' : 'Crew execution',
      status,
      assigned_to: kind === 'child' ? 'worker-1' : null,
      submitted_by: kind === 'child' ? 'worker-1' : null,
      confirmed_by: null,
      note: null,
    },
    actions,
    evidence: {
      permit_state: kind === 'child' ? 'submitted' as const : 'unstarted' as const,
      assignment_epoch: 1,
      booking_id: kind === 'child' ? 'booking-1' : null,
      has_submission: kind === 'child',
      review_accepted: null,
    },
    token: null,
    detail_url: null,
  };
}

function view(overrides: Partial<ManagedOwnedStepsView> = {}): ManagedOwnedStepsView {
  return {
    version: 1,
    parent_id: 'parent-1',
    requested_item_id: 'parent-1',
    actor_id: 'captain',
    thread_id: '',
    turn_id: 'http-owner',
    view_id: 'view-1',
    mode: 'active',
    layout_revision: 1,
    plan_revision: 1,
    plan_digest: digest('d'),
    steps_digest: digest('e'),
    source_digest: digest('f'),
    plan_token: {},
    rows: [
      row('manual-1', 'manual', ['manual_confirm', 'manual_reject', 'edit_note']),
      row('child-step-1', 'child', ['manual_confirm', 'cancel_execution', 'pause_accounting']),
    ],
    previous_cursor: null,
    next_cursor: '20',
    omitted_step_ids: [],
    recovery: [],
    finalization: 'none',
    reference,
    ...overrides,
  };
}

function proposal(kind: ProposalPage['kind']): ProposalPage {
  return {
    version: 1,
    proposal: {
      version: 1,
      parent_id: 'parent-1',
      proposal_id: `${kind}-proposal`,
      manifest_digest: digest('1'),
    },
    reference: {
      ...reference,
      proposal_id: `${kind}-proposal`,
      manifest_digest: digest('1'),
    },
    kind,
    state: 'ready',
    before_digest: digest('2'),
    after_digest: digest('3'),
    gate_completion: true,
    manual_count: 1,
    child_count: 1,
    retired_count: kind === 'replan_unstarted' ? 1 : 0,
    rows: [],
    previous_cursor: null,
    next_cursor: null,
    coverage: {},
    omissions: [],
    actions: ['apply'],
    error_code: null,
    acknowledgement: null,
  };
}

const onRefresh = vi.fn(async () => {});
const onNavigate = vi.fn(async () => {});

beforeEach(() => {
  vi.mocked(sendOwnedCommands).mockResolvedValue([{ operation_id: 'op', disposition: 'applied' }]);
  vi.mocked(applyOwnedProposal).mockResolvedValue('applied');
  vi.mocked(fetchOwnedStepDetail).mockResolvedValue({ read_only: true });
  vi.mocked(finalizeOwnedSteps).mockResolvedValue('completed');
  onRefresh.mockClear();
  onNavigate.mockClear();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('OwnedStepsPanel', () => {
  it('uses stable row IDs and actual actions while child verdict actions remain readonly', async () => {
    render(<OwnedStepsPanel taskId="parent-1" view={view()} onRefresh={onRefresh} onNavigate={onNavigate} />);

    expect(screen.getByTestId('owned-step-manual-1')).toBeTruthy();
    expect(screen.getByTestId('owned-manual_confirm-manual-1')).toBeTruthy();
    expect(screen.queryByTestId('owned-manual_confirm-child-step-1')).toBeNull();
    expect(screen.getByTestId('owned-child-verdict-child-step-1')).toBeTruthy();
    expect(screen.getByText('Pause BOOKING CLOCK ONLY; worker continues')).toBeTruthy();

    fireEvent.click(screen.getByTestId('owned-manual_confirm-manual-1'));
    await waitFor(() => expect(sendOwnedCommands).toHaveBeenCalledWith(
      'parent-1',
      reference,
      [{
        operation_id: 'manual_confirm-operation',
        step_id: 'manual-1',
        kind: 'manual_confirm',
      }],
    ));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('shows stale feedback and never refreshes or resubmits the rejected write', async () => {
    vi.mocked(sendOwnedCommands).mockRejectedValue(new OwnedStepsApiError(
      409,
      'owned_steps_view_stale',
      'Viewed row is stale.',
      'parent-1',
      'view-1',
      ['refresh'],
      'Owned steps refused: refresh explicitly.',
    ));
    render(<OwnedStepsPanel taskId="parent-1" view={view()} onRefresh={onRefresh} onNavigate={onNavigate} />);

    fireEvent.click(screen.getByTestId('owned-manual_confirm-manual-1'));

    expect(await screen.findByText('Owned steps refused: refresh explicitly.')).toBeTruthy();
    expect(sendOwnedCommands).toHaveBeenCalledTimes(1);
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it('previews inspects and explicitly applies adoption without automatic application', async () => {
    vi.mocked(previewOwnedProposal).mockResolvedValue(proposal('adopt_existing'));
    render(<OwnedStepsPanel
      taskId="parent-1"
      view={view({ mode: 'awaiting_adoption' })}
      onRefresh={onRefresh}
      onNavigate={onNavigate}
    />);

    fireEvent.click(screen.getByTestId('owned-preview-adopt'));
    expect(await screen.findByTestId('owned-proposal')).toHaveTextContent('adopt_existing · ready');
    expect(applyOwnedProposal).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('owned-inspect-proposal'));
    await waitFor(() => expect(previewOwnedProposal).toHaveBeenLastCalledWith(
      'parent-1',
      expect.objectContaining({ kind: 'inspect_proposal' }),
    ));
    fireEvent.click(screen.getByTestId('owned-apply-proposal'));
    // The proposal kind now selects the contract-prescribed endpoint; the old
    // two-argument call incorrectly routed replacement/replan through /adopt.
    await waitFor(() => expect(applyOwnedProposal).toHaveBeenCalledWith(
      'parent-1',
      expect.objectContaining({ operation_id: 'apply-adopt_existing-operation' }),
      'adopt_existing',
    ));
  });

  it('reuses the exact proposal operation identity after a lost acknowledgement', async () => {
    let operationSequence = 0;
    vi.mocked(newOwnedOperationId).mockImplementation(
      (prefix: string) => `${prefix}-${++operationSequence}`,
    );
    vi.mocked(previewOwnedProposal).mockResolvedValue(proposal('replan_unstarted'));
    vi.mocked(applyOwnedProposal)
      .mockRejectedValueOnce(new OwnedStepsApiError(
        503,
        'owned_steps_acknowledgement_lost',
        'The committed acknowledgement was lost.',
        'parent-1',
        'view-1',
        ['inspect_proposal'],
        'Inspect and retry the exact proposal.',
      ))
      .mockResolvedValueOnce('duplicate');
    render(<OwnedStepsPanel
      taskId="parent-1"
      view={view({ recovery: ['replan_unstarted'] })}
      onRefresh={onRefresh}
      onNavigate={onNavigate}
    />);

    fireEvent.click(screen.getByTestId('owned-preview-replan'));
    expect(await screen.findByText('replan_unstarted · ready')).toBeTruthy();
    fireEvent.click(screen.getByTestId('owned-apply-proposal'));
    expect(await screen.findByText('Inspect and retry the exact proposal.')).toBeTruthy();
    fireEvent.click(screen.getByTestId('owned-apply-proposal'));

    await waitFor(() => expect(applyOwnedProposal).toHaveBeenCalledTimes(2));
    const first = vi.mocked(applyOwnedProposal).mock.calls[0][1].operation_id;
    const retry = vi.mocked(applyOwnedProposal).mock.calls[1][1].operation_id;
    expect(retry).toBe(first);
  });

  it('keeps malformed repair evidence readonly then performs exact correction as a separate proposal', async () => {
    vi.mocked(fetchOwnedRepair).mockResolvedValue({
      version: 1,
      parent_id: 'parent-1',
      reference: { ...reference, observation_id: 'observation-1' },
      steps_digest: digest('4'),
      control_digest: null,
      raw_steps: '[{"label":"Historical","status":"completed"}]',
      raw_control: null,
      omissions: [],
      actions: ['replace_manual_prefix'],
    });
    vi.mocked(previewOwnedProposal).mockResolvedValue(proposal('replace_manual_prefix'));
    render(<OwnedStepsPanel
      taskId="parent-1"
      view={view({ recovery: ['inspect_source', 'replace_manual_prefix'] })}
      onRefresh={onRefresh}
      onNavigate={onNavigate}
    />);

    fireEvent.click(screen.getByTestId('owned-open-repair'));
    const editor = await screen.findByLabelText('Exact replacement prefix JSON');
    expect(editor).toHaveValue('[{"label":"Historical","status":"completed"}]');
    fireEvent.change(editor, {
      target: { value: '[{"label":"Corrected","status":"pending"}]' },
    });
    fireEvent.click(screen.getByTestId('owned-preview-repair'));
    await waitFor(() => expect(previewOwnedProposal).toHaveBeenCalledWith(
      'parent-1',
      expect.objectContaining({
        kind: 'replace_manual_prefix',
        prefix_json: '[{"label":"Corrected","status":"pending"}]',
      }),
    ));
    expect(applyOwnedProposal).not.toHaveBeenCalled();
  });

  it('provides persisted replan paging detail abandon and finalize-only controls', async () => {
    vi.mocked(previewOwnedProposal).mockResolvedValue(proposal('replan_unstarted'));
    render(<OwnedStepsPanel
      taskId="parent-1"
      view={view({
        mode: 'waiting_manual_gate',
        recovery: ['replan_unstarted'],
        finalization: 'pending',
        rows: [row('child-step-1', 'child', ['abandon'])],
      })}
      onRefresh={onRefresh}
      onNavigate={onNavigate}
    />);

    fireEvent.click(screen.getByTestId('owned-page-next'));
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith('20'));
    fireEvent.click(screen.getByTestId('owned-detail-child-step-1'));
    expect(await screen.findByTestId('owned-step-detail')).toHaveTextContent('"read_only": true');
    fireEvent.click(screen.getByTestId('owned-abandon-child-step-1'));
    await waitFor(() => expect(sendOwnedCommands).toHaveBeenCalledWith(
      'parent-1',
      reference,
      [expect.objectContaining({ kind: 'abandon', step_id: 'child-step-1' })],
    ));
    fireEvent.click(screen.getByTestId('owned-preview-replan'));
    expect(await screen.findByText('replan_unstarted · ready')).toBeTruthy();
    fireEvent.click(screen.getByTestId('owned-finalize'));
    await waitFor(() => expect(finalizeOwnedSteps).toHaveBeenCalledWith('parent-1', reference));
  });

  it('starts malformed-prefix recovery from readonly evidence without requiring a valid owned view', async () => {
    vi.mocked(fetchOwnedRepair).mockResolvedValue({
      version: 1,
      parent_id: 'parent-1',
      reference: { ...reference, observation_id: 'observation-1' },
      steps_digest: digest('4'),
      control_digest: null,
      raw_steps: '[{"label":"Historical","status":"completed"}]',
      raw_control: null,
      omissions: [],
      actions: ['replace_manual_prefix', 'replan_unstarted'],
    });
    vi.mocked(previewOwnedProposal).mockResolvedValue(proposal('replace_manual_prefix'));
    render(<OwnedStepsRecoveryPanel
      taskId="parent-1"
      actions={['inspect_source', 'replace_manual_prefix', 'replan_unstarted']}
      onRefresh={onRefresh}
    />);

    fireEvent.click(screen.getByTestId('owned-load-repair'));
    const editor = await screen.findByLabelText('Exact recovery prefix JSON');
    expect(editor).toHaveValue('[{"label":"Historical","status":"completed"}]');
    fireEvent.change(editor, {
      target: { value: '[{"label":"Corrected","status":"pending"}]' },
    });
    fireEvent.click(screen.getByTestId('owned-recovery-preview-prefix'));
    expect(await screen.findByTestId('owned-recovery-proposal')).toBeTruthy();
    expect(applyOwnedProposal).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('owned-recovery-apply'));
    await waitFor(() => expect(applyOwnedProposal).toHaveBeenCalled());
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});
