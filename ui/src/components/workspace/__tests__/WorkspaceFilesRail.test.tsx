/**
 * AD-929: tests for the WorkspaceFilesRail.
 *
 * The rail is self-fetching, so the inputs/artifact api modules are
 * partially mocked (``importOriginal`` keeps ``attachmentUrl`` real so the
 * composed ``InputsList`` rows still render). Covers the Inputs/Outputs
 * sections, the self-fetch calls, the in-app preview Outputs action, the
 * collapse persistence, the default-collapsed-on-first-run behaviour, and
 * the HXI no-emoji guard. localStorage is cleared between tests.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { TaskInput } from '../../inputs/inputsApi';
import { useStore, type ArtifactView } from '../../../store/useStore';
import type {
  CrewSessionArtifactCommand,
  CrewSessionDetailProjection,
  CrewSessionRetryCommand,
  CrewSessionState,
  StartWorkResult,
} from '../../../store/types';

vi.mock('../../inputs/inputsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../inputs/inputsApi')>();
  return { ...actual, fetchThreadInputs: vi.fn() };
});
vi.mock('../../artifacts/artifactApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../artifacts/artifactApi')>();
  return { ...actual, fetchThreadArtifacts: vi.fn(), fetchArtifactMetadata: vi.fn() };
});
vi.mock('../todosApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../todosApi')>();
  return { ...actual, fetchTaskSteps: vi.fn(), updateTaskStep: vi.fn() };
});

import { fetchThreadInputs } from '../../inputs/inputsApi';
import { fetchArtifactMetadata, fetchThreadArtifacts } from '../../artifacts/artifactApi';
import * as todosApi from '../todosApi';
import { fetchTaskSteps, updateTaskStep } from '../todosApi';
import { WorkspaceFilesRail } from '../WorkspaceFilesRail';

const EMOJI_RE = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F600}-\u{1F64F}]/u;
const SHA_A = 'a'.repeat(64);
const SHA_B = 'b'.repeat(64);

const INPUTS: TaskInput[] = [
  {
    content_hash: 'in1',
    mime: 'text/plain',
    filename: 'notes.txt',
    size: 10,
    source: 'task',
  },
];

const ARTIFACTS: ArtifactView[] = [
  {
    id: 'art1',
    thread_id: 't1',
    name: 'report.md',
    version: 1,
    content_hash: 'h1',
    mime: 'text/markdown',
    size_bytes: 100,
    created_by: 'a1',
    created_at: 0,
    supersedes: null,
    _pinned_from_project: false,
  },
];

function sessionProjection(
  parentId: string,
  threadId: string,
  state: CrewSessionState = 'discussing',
): CrewSessionDetailProjection {
  const blocked = state === 'blocked_needs_captain';
  return {
    task_id: parentId,
    thread_id: threadId,
    goal: 'Prepare the readiness report',
    origin: 'captain',
    originator_id: 'captain',
    facilitator_id: 'facilitator-1',
    owner_ids: ['facilitator-1', 'owner-2'],
    state,
    revision: 1,
    success_criteria: ['Report is complete', 'Evidence is attached'],
    expected_deliverable: 'A verified readiness report',
    timestamps: {
      created_at: 1,
      transitioned_at: 2,
      started_at: state === 'executing' ? 2 : null,
      first_result_at: null,
      verified_at: null,
      completed_at: null,
    },
    progress: {
      total: 1, done: 0, failed: 0, active: 1,
      active_child: { id: 'child-1', title: 'Prepare evidence', status: 'in_progress', owner_id: 'owner-2' },
    },
    last_result_summary: '',
    blocker: blocked ? { reason: 'Captain approval required', since: 2, duration_seconds: 60, action: 'retry_start_work' } : null,
    result: null,
    verification: null,
    duplicate_resume_count: 0,
  };
}

function startWorkResult(
  parentId: string,
  threadId: string,
  state: CrewSessionState = 'discussing',
  disposition: StartWorkResult['disposition'] = 'created',
): StartWorkResult {
  const session = sessionProjection(parentId, threadId, state);
  return {
    disposition,
    parent_id: parentId,
    thread_id: threadId,
    state,
    facilitator_id: session.facilitator_id,
    owner_ids: session.owner_ids,
    duplicate_resume_count: session.duplicate_resume_count,
    scheduled: true,
    session,
  };
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(fetchThreadInputs).mockResolvedValue(INPUTS);
  vi.mocked(fetchThreadArtifacts).mockResolvedValue(ARTIFACTS);
  vi.mocked(fetchArtifactMetadata).mockResolvedValue(null);
  vi.mocked(fetchTaskSteps).mockResolvedValue([]);
  vi.mocked(updateTaskStep).mockResolvedValue();
  vi.stubGlobal('fetch', vi.fn());
  useStore.setState({
    crewSessionsByParent: new Map(),
    crewSessionSummariesByThread: new Map(),
  });
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  useStore.setState({
    crewSessionsByParent: new Map(),
    crewSessionSummariesByThread: new Map(),
  });
});

function openStartWorkDialog(): void {
  fireEvent.click(screen.getByTestId('workspace-start-work-open'));
}

function fillValidStartWorkForm(): void {
  fireEvent.change(screen.getByTestId('workspace-start-work-goal'), {
    target: { value: 'Prepare the readiness report' },
  });
  fireEvent.change(screen.getByTestId('workspace-start-work-criteria'), {
    target: { value: 'Report is complete\nEvidence is attached' },
  });
  fireEvent.change(screen.getByTestId('workspace-start-work-deliverable'), {
    target: { value: 'A verified readiness report' },
  });
}

describe('WorkspaceFilesRail (AD-929)', () => {
  it('renders the Inputs section for a workspace room (expanded)', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    expect(await screen.findByTestId('inputs-list')).toBeTruthy();
    expect(screen.getByTestId('workspace-files-inputs-label').textContent).toBe('INPUTS');
  });

  it('renders the Outputs section (artifact-list) when expanded', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    expect(await screen.findByTestId('artifact-list')).toBeTruthy();
    expect(screen.getByTestId('workspace-files-outputs-label').textContent).toBe('OUTPUTS');
  });

  it('calls fetchThreadInputs with the passed threadId', async () => {
    render(<WorkspaceFilesRail threadId="t1" />);
    await waitFor(() => expect(fetchThreadInputs).toHaveBeenCalledWith('t1'));
  });

  it('calls fetchThreadArtifacts with the passed threadId', async () => {
    render(<WorkspaceFilesRail threadId="t1" />);
    await waitFor(() => expect(fetchThreadArtifacts).toHaveBeenCalledWith('t1'));
  });

  it('opens an in-app preview overlay when an Outputs row is clicked (BF-642)', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    const row = await screen.findByTestId('artifact-row-art1');
    fireEvent.click(row);
    const preview = await screen.findByTestId('workspace-files-preview');
    expect(preview).toBeTruthy();
    expect(preview.textContent).toContain('report.md');
    fireEvent.click(screen.getByTestId('workspace-files-preview-close'));
    expect(screen.queryByTestId('workspace-files-preview')).toBeNull();
  });

  it('collapse toggle persists "1" to localStorage and renders data-collapsed="true"', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    const rail = await screen.findByTestId('workspace-files-rail');
    expect(rail.getAttribute('data-collapsed')).toBe('false');
    fireEvent.click(screen.getByTestId('workspace-files-collapse'));
    expect(localStorage.getItem('probos.workspaceFiles.collapsed')).toBe('1');
    expect(screen.getByTestId('workspace-files-rail').getAttribute('data-collapsed')).toBe('true');
  });

  it('mounts expanded when localStorage is "0" and collapsed by default on first run', () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    const { unmount } = render(<WorkspaceFilesRail threadId="t1" />);
    expect(screen.getByTestId('workspace-files-rail').getAttribute('data-collapsed')).toBe('false');
    unmount();
    cleanup();
    localStorage.clear();
    render(<WorkspaceFilesRail threadId="t1" />);
    expect(screen.getByTestId('workspace-files-rail').getAttribute('data-collapsed')).toBe('true');
  });

  it('renders no emoji (HXI Design Principle #3 — stroke-SVG icons only)', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    const { container } = render(<WorkspaceFilesRail threadId="t1" />);
    await screen.findByTestId('inputs-list');
    expect(container.textContent || '').not.toMatch(EMOJI_RE);
  });

  it('passive taskless and bound viewing issues no POST, PATCH, or DELETE', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    const { rerender } = render(<WorkspaceFilesRail threadId="t1" />);
    await waitFor(() => expect(fetchThreadInputs).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId('workspace-files-collapse'));
    fireEvent.click(screen.getByTestId('workspace-files-expand'));
    rerender(<WorkspaceFilesRail threadId="t1" taskId="task-1" />);
    await waitFor(() => expect(fetchTaskSteps).toHaveBeenCalledWith('task-1'));

    const mutationCalls = vi.mocked(fetch).mock.calls.filter(([, init]) =>
      ['POST', 'PATCH', 'DELETE'].includes(String(init?.method ?? 'GET')),
    );
    expect(mutationCalls).toEqual([]);
  });

  it('opening and cancelling Start Work performs no request', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    await screen.findByTestId('workspace-files-rail');

    openStartWorkDialog();
    expect(screen.getByRole('dialog')).toBeTruthy();
    fireEvent.click(screen.getByTestId('workspace-start-work-cancel'));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('opens Start Work with Goal focused', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);

    openStartWorkDialog();

    await waitFor(() => {
      expect(screen.getByTestId('workspace-start-work-goal')).toHaveFocus();
    });
  });

  it('wraps Tab forward and Shift+Tab backward across enabled dialog controls', async () => {
    const user = userEvent.setup();
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);

    await screen.findByTestId('input-row-in1');
    await screen.findByTestId('artifact-row-art1');
    await user.click(screen.getByTestId('workspace-start-work-open'));

    const goal = screen.getByTestId('workspace-start-work-goal');
    const criteria = screen.getByTestId('workspace-start-work-criteria');
    const deliverable = screen.getByTestId('workspace-start-work-deliverable');
    const retry = screen.getByTestId('workspace-start-work-retry');
    const cancel = screen.getByTestId('workspace-start-work-cancel');
    const confirm = screen.getByTestId('workspace-start-work-confirm');
    await waitFor(() => expect(goal).toHaveFocus());

    await user.type(goal, 'Prepare the readiness report');
    await user.type(criteria, 'Report is complete{Enter}Evidence is attached');
    await user.type(deliverable, 'A verified readiness report');
    await waitFor(() => expect(confirm).toBeEnabled());

    await user.click(goal);
    fireEvent.keyDown(goal, { key: 'Tab' });
    expect(criteria).toHaveFocus();
    fireEvent.keyDown(criteria, { key: 'Tab' });
    expect(deliverable).toHaveFocus();
    fireEvent.keyDown(deliverable, { key: 'Tab' });
    expect(retry).toHaveFocus();
    fireEvent.keyDown(retry, { key: 'Tab' });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(cancel, { key: 'Tab' });
    expect(confirm).toHaveFocus();

    fireEvent.keyDown(confirm, { key: 'Tab' });
    expect(goal).toHaveFocus();

    fireEvent.keyDown(goal, { key: 'Tab', shiftKey: true });
    expect(confirm).toHaveFocus();
  });

  it('non-pending Escape stops propagation, closes, and restores the opener', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    const parentKeyDown = vi.fn();
    render(
      <div onKeyDown={parentKeyDown}>
        <WorkspaceFilesRail threadId="t1" />
      </div>,
    );
    const opener = screen.getByTestId('workspace-start-work-open');
    opener.focus();
    fireEvent.click(opener);

    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(parentKeyDown).not.toHaveBeenCalled();
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('pending Escape is inert and keeps focus on the dialog container', async () => {
    const user = userEvent.setup();
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    let resolveRequest: ((value: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation(() => new Promise<Response>((resolve) => {
      resolveRequest = resolve;
    }));
    render(<WorkspaceFilesRail threadId="t1" />);

    await screen.findByTestId('input-row-in1');
    await screen.findByTestId('artifact-row-art1');
    await user.click(screen.getByTestId('workspace-start-work-open'));

    const goal = screen.getByTestId('workspace-start-work-goal');
    const criteria = screen.getByTestId('workspace-start-work-criteria');
    const deliverable = screen.getByTestId('workspace-start-work-deliverable');
    const confirm = screen.getByTestId('workspace-start-work-confirm');
    await user.type(goal, 'Prepare the readiness report');
    await user.type(criteria, 'Report is complete{Enter}Evidence is attached');
    await user.type(deliverable, 'A verified readiness report');
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const dialog = screen.getByRole('dialog');
    await waitFor(() => expect(dialog).toHaveFocus());

    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog')).toBe(dialog);
    expect(dialog).toHaveFocus();

    await user.tab();
    expect(dialog).toHaveFocus();
    await user.tab({ shift: true });
    expect(dialog).toHaveFocus();

    await act(async () => {
      resolveRequest?.({
        ok: true,
        json: async () => startWorkResult('pending-parent', 't1'),
      } as Response);
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('Cancel and successful Start Work restore the connected opener', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: async () => startWorkResult('focus-parent', 't1'),
    } as Response);
    render(<WorkspaceFilesRail threadId="t1" />);
    const opener = screen.getByTestId('workspace-start-work-open');

    fireEvent.click(opener);
    fireEvent.click(screen.getByTestId('workspace-start-work-cancel'));
    await waitFor(() => expect(opener).toHaveFocus());

    fireEvent.click(opener);
    fillValidStartWorkForm();
    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('invalid form disables confirm', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    render(<WorkspaceFilesRail threadId="t1" />);
    openStartWorkDialog();

    expect(screen.getByTestId('workspace-start-work-confirm')).toBeDisabled();
    fireEvent.change(screen.getByTestId('workspace-start-work-goal'), {
      target: { value: 'Goal only' },
    });
    expect(screen.getByTestId('workspace-start-work-confirm')).toBeDisabled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('one confirm performs exactly one correctly shaped POST and binds the parent locally', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    let resolveRequest: ((value: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation(() => new Promise<Response>((resolve) => {
      resolveRequest = resolve;
    }));
    const onSessionBound = vi.fn();
    render(<WorkspaceFilesRail threadId="room/1" onSessionBound={onSessionBound} />);
    openStartWorkDialog();
    fillValidStartWorkForm();
    fireEvent.click(screen.getByTestId('workspace-start-work-retry'));

    const confirm = screen.getByTestId('workspace-start-work-confirm');
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId('workspace-start-work-confirm')).toBeDisabled();
    expect(fetch).toHaveBeenCalledWith(
      '/api/threads/room%2F1/start-work',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          goal: 'Prepare the readiness report',
          success_criteria: ['Report is complete', 'Evidence is attached'],
          expected_deliverable: 'A verified readiness report',
          retry_blocked: true,
        }),
      },
    );

    await act(async () => {
      resolveRequest?.({
        ok: true,
        json: async () => startWorkResult('parent-1', 'room/1'),
      } as Response);
    });

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(fetchTaskSteps).toHaveBeenCalledWith('parent-1'));
    expect(screen.getByTestId('workspace-files-todos')).toBeTruthy();
    expect(useStore.getState().crewSessionsByParent.get('parent-1')).toEqual(
      sessionProjection('parent-1', 'room/1'),
    );
    expect(onSessionBound).toHaveBeenCalledTimes(1);
    expect(onSessionBound).toHaveBeenCalledWith(startWorkResult('parent-1', 'room/1'));
  });

  it('rejects a parent returned for a different authority room without hydration', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: async () => startWorkResult(
        'existing-parent',
        'existing-authority-room',
        'executing',
        'resumed',
      ),
    } as Response);
    const onSessionBound = vi.fn();
    render(<WorkspaceFilesRail threadId="requested-room" onSessionBound={onSessionBound} />);
    openStartWorkDialog();
    fillValidStartWorkForm();

    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));

    expect(await screen.findByTestId('workspace-start-work-error')).toHaveTextContent(
      'different room',
    );
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(fetchTaskSteps).not.toHaveBeenCalledWith('existing-parent');
    expect(useStore.getState().crewSessionsByParent.has('existing-parent')).toBe(false);
    expect(onSessionBound).not.toHaveBeenCalled();
  });

  it('server error stays visible with inputs preserved and is retryable', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    vi.mocked(fetch)
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({ detail: 'crew_session_terminal_not_reopenable' }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => startWorkResult('parent-2', 't1'),
      } as Response);
    render(<WorkspaceFilesRail threadId="t1" />);
    const opener = screen.getByTestId('workspace-start-work-open');
    openStartWorkDialog();
    fillValidStartWorkForm();

    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    expect(await screen.findByTestId('workspace-start-work-error')).toHaveTextContent(
      'crew_session_terminal_not_reopenable',
    );
    expect(screen.getByTestId('workspace-start-work-goal')).toHaveValue(
      'Prepare the readiness report',
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog.contains(document.activeElement)).toBe(true);

    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('ignores a Start Work response resolved in the same act as a room switch', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    let resolveRequest: ((value: Response) => void) | undefined;
    vi.mocked(fetch).mockImplementation(() => new Promise<Response>((resolve) => {
      resolveRequest = resolve;
    }));
    const { rerender } = render(<WorkspaceFilesRail threadId="room-1" />);
    openStartWorkDialog();
    fillValidStartWorkForm();
    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

    await act(async () => {
      resolveRequest?.({
        ok: true,
        json: async () => startWorkResult('stale-parent', 'room-1'),
      } as Response);
      rerender(<WorkspaceFilesRail threadId="room-2" />);
    });

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(fetchTaskSteps).not.toHaveBeenCalledWith('stale-parent');
    expect(useStore.getState().crewSessionsByParent.has('stale-parent')).toBe(false);
    expect(screen.queryByTestId('workspace-files-todos')).toBeNull();
  });

  it('drops an old polling refresh started during a room-switch render', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    const intervalCallbacks: Array<() => void> = [];
    vi.stubGlobal('setInterval', vi.fn((callback: TimerHandler) => {
      if (typeof callback === 'function') intervalCallbacks.push(callback as () => void);
      return 1;
    }));
    let staleResolve: ((value: ArtifactView[]) => void) | undefined;
    let roomOneCalls = 0;
    vi.mocked(fetchThreadArtifacts).mockImplementation((roomId) => {
      if (roomId === 'room-1') {
        roomOneCalls += 1;
        if (roomOneCalls === 1) return Promise.resolve([]);
        return new Promise<ArtifactView[]>((resolve) => { staleResolve = resolve; });
      }
      return Promise.resolve([]);
    });

    function FireOldInterval({ enabled }: { enabled: boolean }) {
      if (enabled) intervalCallbacks[0]?.();
      return null;
    }

    const view = render(
      <>
        <WorkspaceFilesRail threadId="room-1" />
        <FireOldInterval enabled={false} />
      </>,
    );
    await waitFor(() => expect(intervalCallbacks.length).toBeGreaterThan(0));

    view.rerender(
      <>
        <WorkspaceFilesRail threadId="room-2" />
        <FireOldInterval enabled />
      </>,
    );
    await waitFor(() => expect(staleResolve).toBeTypeOf('function'));
    await act(async () => {
      staleResolve?.([{
        ...ARTIFACTS[0],
        id: 'stale-artifact',
        thread_id: 'room-1',
        name: 'stale-room-one.md',
      }]);
    });

    expect(screen.queryByTestId('artifact-row-stale-artifact')).toBeNull();
    expect(fetchThreadArtifacts).toHaveBeenCalledWith('room-2');
  });

  it('owned retry command expands, pre-fills, checks retry, focuses Goal, and performs no write', async () => {
    const opener = document.createElement('button');
    opener.textContent = 'Retry blocked CrewSession work';
    document.body.appendChild(opener);
    const retryCommand: CrewSessionRetryCommand = {
      requestId: 1,
      parentId: 'blocked-parent',
      threadId: 't1',
      projection: sessionProjection('blocked-parent', 't1', 'blocked_needs_captain'),
      opener,
    };
    render(<WorkspaceFilesRail threadId="t1" retryCommand={retryCommand} />);

    expect(await screen.findByRole('dialog')).toBeTruthy();
    expect(screen.getByTestId('workspace-files-rail').getAttribute('data-collapsed')).toBe('false');
    expect(screen.getByTestId('workspace-start-work-goal')).toHaveValue(retryCommand.projection.goal);
    expect(screen.getByTestId('workspace-start-work-criteria')).toHaveValue(retryCommand.projection.success_criteria.join('\n'));
    expect(screen.getByTestId('workspace-start-work-deliverable')).toHaveValue(retryCommand.projection.expected_deliverable);
    expect(screen.getByTestId('workspace-start-work-retry')).toBeChecked();
    await waitFor(() => expect(screen.getByTestId('workspace-start-work-goal')).toHaveFocus());
    expect(fetch).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('workspace-start-work-cancel'));
    await waitFor(() => expect(opener).toHaveFocus());
    opener.remove();
  });

  it('owned artifact command prefers local metadata and opens the existing viewer', async () => {
    const command: CrewSessionArtifactCommand = {
      requestId: 1,
      parentId: 'parent-1',
      threadId: 't1',
      artifactId: 'art1',
    };
    render(<WorkspaceFilesRail threadId="t1" artifactCommand={command} />);

    expect(await screen.findByTestId('workspace-files-preview')).toBeTruthy();
    expect(screen.getAllByText('report.md').length).toBeGreaterThan(0);
    expect(fetchArtifactMetadata).not.toHaveBeenCalled();
  });

  it('rejects a matching preloaded artifact owned by another room', async () => {
    vi.mocked(fetchThreadArtifacts).mockResolvedValue([{ ...ARTIFACTS[0], thread_id: 'other-room' }]);
    const command: CrewSessionArtifactCommand = {
      requestId: 3,
      parentId: 'parent-1',
      threadId: 't1',
      artifactId: 'art1',
    };

    render(<WorkspaceFilesRail threadId="t1" artifactCommand={command} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('metadata could not be loaded');
    expect(screen.queryByTestId('workspace-files-preview')).toBeNull();
    expect(fetchArtifactMetadata).not.toHaveBeenCalled();
  });

  it('missing or mismatched artifact metadata alerts, then Retry opens the existing viewer', async () => {
    vi.mocked(fetchThreadArtifacts).mockResolvedValue([]);
    const loaded: ArtifactView = {
      ...ARTIFACTS[0],
      id: 'art2',
      thread_id: 't1',
      name: 'recovered.md',
    };
    vi.mocked(fetchArtifactMetadata)
      .mockResolvedValueOnce({ ...loaded, thread_id: 'other-room' })
      .mockResolvedValueOnce(loaded);
    const command: CrewSessionArtifactCommand = {
      requestId: 2,
      parentId: 'parent-1',
      threadId: 't1',
      artifactId: 'art2',
    };
    render(<WorkspaceFilesRail threadId="t1" artifactCommand={command} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('metadata could not be loaded');
    expect(screen.queryByTestId('workspace-files-preview')).toBeNull();
    fireEvent.click(screen.getByTestId('workspace-artifact-command-retry'));

    expect(await screen.findByTestId('workspace-files-preview')).toBeTruthy();
    expect(screen.getAllByText('recovered.md').length).toBeGreaterThan(0);
    expect(fetchArtifactMetadata).toHaveBeenCalledTimes(2);
    expect(fetchArtifactMetadata).toHaveBeenNthCalledWith(1, 'art2');
    expect(fetchArtifactMetadata).toHaveBeenNthCalledWith(2, 'art2');
  });

  it('todosApi no longer exports passive ensureRoomTask', () => {
    expect('ensureRoomTask' in todosApi).toBe(false);
  });
});
