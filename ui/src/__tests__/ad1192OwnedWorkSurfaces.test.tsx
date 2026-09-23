import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../components/inputs/inputsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../components/inputs/inputsApi')>();
  return { ...actual, fetchThreadInputs: vi.fn().mockResolvedValue([]) };
});
vi.mock('../components/artifacts/artifactApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../components/artifacts/artifactApi')>();
  return {
    ...actual,
    fetchThreadArtifacts: vi.fn().mockResolvedValue([]),
    fetchArtifactMetadata: vi.fn().mockResolvedValue(null),
  };
});
vi.mock('../components/workspace/todosApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../components/workspace/todosApi')>();
  return {
    ...actual,
    fetchTaskSteps: vi.fn(),
    updateTaskStep: vi.fn(),
  };
});
vi.mock('../components/workspace/ownedStepsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../components/workspace/ownedStepsApi')>();
  return {
    ...actual,
    fetchOwnedSteps: vi.fn(),
    sendOwnedCommands: vi.fn().mockResolvedValue([]),
  };
});

import WorkBoard from '../components/work/WorkBoard';
import { ProfileWorkTab } from '../components/profile/ProfileWorkTab';
import { WorkspaceFilesRail } from '../components/workspace/WorkspaceFilesRail';
import {
  OwnedStepsApiError,
  fetchOwnedSteps,
  type ManagedOwnedStepsView,
} from '../components/workspace/ownedStepsApi';
import { fetchTaskSteps } from '../components/workspace/todosApi';
import { useStore } from '../store/useStore';
import type { WorkItemView } from '../store/types';

const digest = (character: string) => character.repeat(64);

function item(overrides: Partial<WorkItemView> = {}): WorkItemView {
  return {
    id: 'parent-1',
    title: 'Owned crew task',
    description: 'Verify the owned workflow.',
    work_type: 'task',
    status: 'failed',
    priority: 2,
    parent_id: null,
    project_id: null,
    depends_on: [],
    assigned_to: 'worker-1',
    created_by: 'captain',
    created_at: 1,
    updated_at: 2,
    due_at: null,
    estimated_tokens: 100,
    actual_tokens: 20,
    trust_requirement: 0,
    required_capabilities: [],
    tags: [],
    metadata: {},
    steps: [
      { label: 'Legacy complete', status: 'completed' },
      { label: 'Owned complete', status: 'done' },
    ],
    verification: null,
    schedule: null,
    ttl_seconds: null,
    template_id: null,
    ...overrides,
  };
}

function managedView(): ManagedOwnedStepsView {
  const reference = {
    version: 1 as const,
    parent_id: 'parent-1',
    actor_id: 'captain',
    thread_id: '',
    turn_id: 'http-owner',
    view_id: 'view-1',
    content_hash: digest('a'),
  };
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
    plan_digest: digest('b'),
    steps_digest: digest('c'),
    source_digest: digest('d'),
    plan_token: {},
    rows: [{
      step_id: 'manual-1',
      ordinal: 1,
      kind: 'manual',
      child_id: null,
      revision: 1,
      digest: digest('e'),
      todo: {
        label: 'Captain gate',
        status: 'submitted',
        assigned_to: null,
        submitted_by: 'worker-1',
        confirmed_by: null,
        note: null,
      },
      actions: ['manual_confirm'],
      evidence: {
        permit_state: 'unstarted',
        assignment_epoch: 1,
        booking_id: null,
        has_submission: false,
        review_accepted: null,
      },
      token: null,
      detail_url: null,
    }],
    previous_cursor: null,
    next_cursor: null,
    omitted_step_ids: [],
    recovery: [],
    finalization: 'none',
    reference,
  };
}

const unmanaged = {
  version: 1 as const,
  mode: 'unmanaged' as const,
  parent_id: 'parent-1',
  requested_item_id: 'parent-1',
  reference: null,
  rows: [],
  previous_cursor: null,
  next_cursor: null,
  recovery: [] as string[],
  finalization: 'none' as const,
};

const moveWorkItem = vi.fn(async () => {});
const assignWorkItem = vi.fn(async () => {});

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('probos.workspaceFiles.collapsed', '0');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ work_items: [], count: 0 }),
  }));
  vi.mocked(fetchTaskSteps).mockResolvedValue([{ label: 'Legacy', status: 'submitted' }]);
  useStore.setState({
    workItems: [item()],
    workBookings: [],
    bookableResources: [{
      resource_id: 'worker-1',
      resource_type: 'crew',
      agent_type: 'worker',
      callsign: 'Worker',
      capacity: 1,
      calendar_id: null,
      department: 'ops',
      characteristics: [],
      display_on_board: true,
      active: true,
    }],
    agents: new Map([['worker-1', {
      id: 'worker-1',
      agentType: 'worker',
      callsign: 'Worker',
    } as never]]),
    workTemplates: [],
    scheduledTasks: [],
    moveWorkItem,
    assignWorkItem,
    liveArtifactRefresh: null,
    liveTodoRefresh: null,
    liveRepairEpoch: 0,
    liveThreadRefresh: null,
    liveGeneration: null,
    threadMessages: new Map(),
    liveRailOwner: null,
  });
  moveWorkItem.mockClear();
  assignWorkItem.mockClear();
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe('AD-1192 owned work surfaces', () => {
  it('rail classifies managed ownership before legacy fetch and mounts owned controls', async () => {
    vi.mocked(fetchOwnedSteps).mockResolvedValue(managedView());
    render(<WorkspaceFilesRail threadId="thread-1" taskId="parent-1" />);

    expect(await screen.findByTestId('owned-steps-panel')).toBeTruthy();
    expect(screen.getByText('TODOS (0/1)')).toBeTruthy();
    expect(fetchTaskSteps).not.toHaveBeenCalled();
    expect(screen.getByTestId('owned-manual_confirm-manual-1')).toBeTruthy();
  });

  it('rail treats ownership errors as blocking rather than unmanaged fallback', async () => {
    vi.mocked(fetchOwnedSteps).mockRejectedValue(new OwnedStepsApiError(
      503,
      'owned_steps_unavailable',
      'Owner unavailable.',
      'parent-1',
      null,
      ['refresh'],
      'Ownership is unavailable; refresh explicitly.',
    ));
    render(<WorkspaceFilesRail threadId="thread-1" taskId="parent-1" />);

    expect(await screen.findByTestId('owned-steps-classification-error'))
      .toHaveTextContent('Ownership is unavailable');
    expect(fetchTaskSteps).not.toHaveBeenCalled();
    expect(screen.queryByTestId('todo-confirm-0')).toBeNull();
  });

  it('WorkBoard mounted detail meter accepts done and historical completed', async () => {
    vi.mocked(fetchOwnedSteps).mockResolvedValue(unmanaged);
    useStore.setState({ workItems: [item({ status: 'in_progress' })] });
    render(<WorkBoard />);

    fireEvent.click(screen.getByText('Owned crew task'));
    expect(await screen.findByText('Steps (2/2)')).toBeTruthy();
  });

  it('WorkBoard drag routes managed work to owned controls without generic transition', async () => {
    vi.mocked(fetchOwnedSteps).mockResolvedValue(managedView());
    useStore.setState({ workItems: [item({ status: 'in_progress' })] });
    render(<WorkBoard />);
    const card = screen.getByText('Owned crew task').closest('[draggable="true"]') as HTMLElement;
    const dataTransfer = {
      setData: vi.fn(),
      getData: vi.fn().mockReturnValue('parent-1'),
    };
    fireEvent.dragStart(card, { dataTransfer });
    const doneHeader = screen.getByText('DONE');
    fireEvent.drop(doneHeader.parentElement as HTMLElement, { dataTransfer });

    expect(await screen.findByTestId('work-board-owned-controls')).toBeTruthy();
    expect(moveWorkItem).not.toHaveBeenCalled();
  });

  it('Profile blocks generic Cancel for managed and unknown ownership', async () => {
    vi.mocked(fetchOwnedSteps).mockResolvedValueOnce(managedView());
    render(<ProfileWorkTab agentId="worker-1" />);
    fireEvent.click(screen.getByText('Cancel'));
    expect(await screen.findByTestId('profile-owned-controls-parent-1')).toBeTruthy();
    expect(moveWorkItem).not.toHaveBeenCalled();

    cleanup();
    vi.mocked(fetchOwnedSteps).mockRejectedValue(new OwnedStepsApiError(
      503,
      'owned_steps_unavailable',
      'Owner unavailable.',
      'parent-1',
      null,
      ['refresh'],
      'Ownership could not be verified.',
    ));
    render(<ProfileWorkTab agentId="worker-1" />);
    fireEvent.click(screen.getByText('Cancel'));
    await waitFor(() => expect(screen.getByTestId('profile-work-ownership-error'))
      .toHaveTextContent('Ownership could not be verified'));
    expect(moveWorkItem).not.toHaveBeenCalled();
  });
});
