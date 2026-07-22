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
import type { ArtifactView } from '../../../store/useStore';

vi.mock('../../inputs/inputsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../inputs/inputsApi')>();
  return { ...actual, fetchThreadInputs: vi.fn() };
});
vi.mock('../../artifacts/artifactApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../artifacts/artifactApi')>();
  return { ...actual, fetchThreadArtifacts: vi.fn() };
});
vi.mock('../todosApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../todosApi')>();
  return { ...actual, fetchTaskSteps: vi.fn(), updateTaskStep: vi.fn() };
});

import { fetchThreadInputs } from '../../inputs/inputsApi';
import { fetchThreadArtifacts } from '../../artifacts/artifactApi';
import * as todosApi from '../todosApi';
import { fetchTaskSteps, updateTaskStep } from '../todosApi';
import { WorkspaceFilesRail } from '../WorkspaceFilesRail';

const EMOJI_RE = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F600}-\u{1F64F}]/u;

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

beforeEach(() => {
  localStorage.clear();
  vi.mocked(fetchThreadInputs).mockResolvedValue(INPUTS);
  vi.mocked(fetchThreadArtifacts).mockResolvedValue(ARTIFACTS);
  vi.mocked(fetchTaskSteps).mockResolvedValue([]);
  vi.mocked(updateTaskStep).mockResolvedValue();
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
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
        json: async () => ({
          disposition: 'created',
          parent_id: 'pending-parent',
          thread_id: 't1',
          state: 'discussing',
          scheduled: true,
        }),
      } as Response);
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('Cancel and successful Start Work restore the connected opener', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: async () => ({
        disposition: 'created',
        parent_id: 'focus-parent',
        thread_id: 't1',
        state: 'discussing',
        scheduled: true,
      }),
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
    render(<WorkspaceFilesRail threadId="room/1" />);
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
        json: async () => ({
          disposition: 'created',
          parent_id: 'parent-1',
          thread_id: 'room/1',
          state: 'discussing',
          scheduled: true,
        }),
      } as Response);
    });

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(fetchTaskSteps).toHaveBeenCalledWith('parent-1'));
    expect(screen.getByTestId('workspace-files-todos')).toBeTruthy();
  });

  it('binds a deduplicated parent returned from an existing authority room', async () => {
    localStorage.setItem('probos.workspaceFiles.collapsed', '0');
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: async () => ({
        disposition: 'resumed',
        parent_id: 'existing-parent',
        thread_id: 'existing-authority-room',
        state: 'executing',
        scheduled: true,
      }),
    } as Response);
    render(<WorkspaceFilesRail threadId="requested-room" />);
    openStartWorkDialog();
    fillValidStartWorkForm();

    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(fetchTaskSteps).toHaveBeenCalledWith('existing-parent'));
    expect(screen.getByTestId('workspace-files-todos')).toBeTruthy();
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
        json: async () => ({
          disposition: 'created',
          parent_id: 'parent-2',
          thread_id: 't1',
          state: 'discussing',
          scheduled: true,
        }),
      } as Response);
    render(<WorkspaceFilesRail threadId="t1" />);
    openStartWorkDialog();
    fillValidStartWorkForm();

    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    expect(await screen.findByTestId('workspace-start-work-error')).toHaveTextContent(
      'crew_session_terminal_not_reopenable',
    );
    expect(screen.getByTestId('workspace-start-work-goal')).toHaveValue(
      'Prepare the readiness report',
    );

    fireEvent.click(screen.getByTestId('workspace-start-work-confirm'));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('ignores a Start Work response owned by the previous room', async () => {
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

    rerender(<WorkspaceFilesRail threadId="room-2" />);
    await act(async () => {
      resolveRequest?.({
        ok: true,
        json: async () => ({
          disposition: 'created',
          parent_id: 'stale-parent',
          thread_id: 'room-1',
          state: 'discussing',
          scheduled: true,
        }),
      } as Response);
    });

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(fetchTaskSteps).not.toHaveBeenCalledWith('stale-parent');
    expect(screen.queryByTestId('workspace-files-todos')).toBeNull();
  });

  it('todosApi no longer exports passive ensureRoomTask', () => {
    expect('ensureRoomTask' in todosApi).toBe(false);
  });
});
