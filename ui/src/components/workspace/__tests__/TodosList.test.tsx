/**
 * AD-1083: tests for the room Todo checklist (TodosList rows + the
 * WorkspaceFilesRail TODOS section count/visibility gate).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

import type { TaskInput } from '../../inputs/inputsApi';
import type { ArtifactView } from '../../../store/useStore';
import type { TodoStep } from '../todosApi';

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
  return { ...actual, fetchTaskSteps: vi.fn(), updateTaskStep: vi.fn(), ensureRoomTask: vi.fn() };
});

import { fetchThreadInputs } from '../../inputs/inputsApi';
import { fetchThreadArtifacts } from '../../artifacts/artifactApi';
import { fetchTaskSteps, updateTaskStep, ensureRoomTask } from '../todosApi';
import { WorkspaceFilesRail } from '../WorkspaceFilesRail';
import { TodosList } from '../TodosList';

const STEPS: TodoStep[] = [
  { label: 'Draft what-is-ai.docx', status: 'done' },
  { label: 'Yeo: AI Agent paragraph', status: 'submitted' },
  { label: 'Review + closing', status: 'pending' },
];

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('probos.workspaceFiles.collapsed', '0');
  vi.mocked(fetchThreadInputs).mockResolvedValue([] as TaskInput[]);
  vi.mocked(fetchThreadArtifacts).mockResolvedValue([] as ArtifactView[]);
  vi.mocked(fetchTaskSteps).mockResolvedValue(STEPS);
  vi.mocked(updateTaskStep).mockResolvedValue();
  vi.mocked(ensureRoomTask).mockResolvedValue('wi-bound');
});
afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks(); });

describe('WorkspaceFilesRail TODOS (AD-1083)', () => {
  it('shows the TODOS section with a done/total count when the room has a task', async () => {
    render(<WorkspaceFilesRail threadId="t1" taskId="wi-1" />);
    expect(await screen.findByText('TODOS (1/3)')).toBeTruthy();
  });

  it('hides TODOS when there is no bound task', async () => {
    vi.mocked(ensureRoomTask).mockRejectedValueOnce(new Error('no engine'));
    render(<WorkspaceFilesRail threadId="t1" />);
    await waitFor(() => expect(fetchThreadInputs).toHaveBeenCalled());
    expect(screen.queryByTestId('workspace-files-todos')).toBeNull();
  });

  it('AD-1084: a task-less workspace room self-binds a task and shows TODOS', async () => {
    render(<WorkspaceFilesRail threadId="t1" />);
    await waitFor(() => expect(ensureRoomTask).toHaveBeenCalledWith('t1', expect.any(String)));
    expect(await screen.findByTestId('workspace-files-todos')).toBeTruthy();
  });

  it('Captain confirm PATCHes the submitted step to done', async () => {
    render(<WorkspaceFilesRail threadId="t1" taskId="wi-1" />);
    fireEvent.click(await screen.findByTestId('todo-confirm-1'));
    await waitFor(() => expect(updateTaskStep).toHaveBeenCalledWith('wi-1', 1, { status: 'done', actor: 'captain' }));
  });

  it('BF-650: details panel toggles in the preview', async () => {
    vi.mocked(fetchThreadArtifacts).mockResolvedValue([
      { id: 'a1', thread_id: 't1', name: 'doc.docx', version: 1, content_hash: 'h', mime: 'm', size_bytes: 2048, created_by: 'ezri', created_at: 0, supersedes: null, _pinned_from_project: false },
    ] as ArtifactView[]);
    render(<WorkspaceFilesRail threadId="t1" taskId="wi-1" />);
    fireEvent.click(await screen.findByTestId('artifact-row-a1'));
    fireEvent.click(await screen.findByTestId('workspace-files-details-toggle'));
    expect(await screen.findByTestId('workspace-files-details')).toBeTruthy();
  });
});

describe('TodosList (AD-1083)', () => {
  it('shows confirm/reject only on submitted steps', () => {
    render(<TodosList steps={STEPS} onConfirm={() => {}} onReject={() => {}} />);
    expect(screen.getByTestId('todo-confirm-1')).toBeTruthy();
    expect(screen.queryByTestId('todo-confirm-0')).toBeNull();
  });

  it('renders empty state', () => {
    render(<TodosList steps={[]} onConfirm={() => {}} onReject={() => {}} />);
    expect(screen.getByTestId('todos-empty')).toBeTruthy();
  });
});
