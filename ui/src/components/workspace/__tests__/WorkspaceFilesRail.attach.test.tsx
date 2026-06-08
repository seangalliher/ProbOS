/**
 * AD-926a: tests for the "+ Attach" affordance on the WorkspaceFilesRail.
 *
 * The rail self-fetches, so the inputs/artifact api modules are partially
 * mocked (``importOriginal`` keeps ``attachmentUrl`` real so the composed
 * ``InputsList`` rows still render; ``attachTaskInputs`` is a spy). Covers:
 * the attach button + multi-file input render only when ``taskId`` is set,
 * its absence when ``taskId`` is unset, the attach call wiring, the rail
 * refreshing its Inputs list from the returned array, and the HXI no-emoji
 * guard. localStorage is cleared between tests (the rail defaults collapsed
 * on first run, so each test forces it expanded via the '0' key).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

import type { TaskInput } from '../../inputs/inputsApi';
import type { ArtifactView } from '../../../store/useStore';

vi.mock('../../inputs/inputsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../inputs/inputsApi')>();
  return { ...actual, fetchThreadInputs: vi.fn(), attachTaskInputs: vi.fn() };
});
vi.mock('../../artifacts/artifactApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../artifacts/artifactApi')>();
  return { ...actual, fetchThreadArtifacts: vi.fn() };
});

import { fetchThreadInputs, attachTaskInputs } from '../../inputs/inputsApi';
import { fetchThreadArtifacts } from '../../artifacts/artifactApi';
import { WorkspaceFilesRail } from '../WorkspaceFilesRail';

const INITIAL: TaskInput[] = [
  { content_hash: 'in1', mime: 'text/plain', filename: 'notes.txt', size: 10, source: 'task' },
];
const REFRESHED: TaskInput[] = [
  { content_hash: 'in1', mime: 'text/plain', filename: 'notes.txt', size: 10, source: 'task' },
  { content_hash: 'new1', mime: 'text/plain', filename: 'attached.txt', size: 5, source: 'task' },
];

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('probos.workspaceFiles.collapsed', '0');
  vi.mocked(fetchThreadInputs).mockResolvedValue(INITIAL);
  vi.mocked(fetchThreadArtifacts).mockResolvedValue([] as ArtifactView[]);
  vi.mocked(attachTaskInputs).mockResolvedValue(REFRESHED);
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
});

describe('WorkspaceFilesRail "+ Attach" (AD-926a)', () => {
  it('renders the attach button + multi-file input when taskId is set', async () => {
    render(<WorkspaceFilesRail threadId="t1" taskId="wi-1" />);
    expect(await screen.findByTestId('workspace-files-attach')).toBeTruthy();
    const input = screen.getByTestId('workspace-files-attach-input') as HTMLInputElement;
    expect(input.type).toBe('file');
    expect(input.multiple).toBe(true);
  });

  it('hides the attach button when taskId is not set', async () => {
    render(<WorkspaceFilesRail threadId="t1" />);
    // Wait for the expanded INPUTS label to confirm the rail mounted expanded.
    expect(await screen.findByTestId('workspace-files-inputs-label')).toBeTruthy();
    expect(screen.queryByTestId('workspace-files-attach')).toBeNull();
  });

  it('selecting files calls attachTaskInputs with the taskId and picked files', async () => {
    render(<WorkspaceFilesRail threadId="t1" taskId="wi-1" />);
    const input = await screen.findByTestId('workspace-files-attach-input');
    const f1 = new File(['alpha'], 'a.txt', { type: 'text/plain' });
    const f2 = new File(['bravo'], 'b.txt', { type: 'text/plain' });
    fireEvent.change(input, { target: { files: [f1, f2] } });
    await waitFor(() => expect(attachTaskInputs).toHaveBeenCalledWith('wi-1', [f1, f2]));
  });

  it('refreshes the Inputs list from the returned array', async () => {
    render(<WorkspaceFilesRail threadId="t1" taskId="wi-1" />);
    const input = await screen.findByTestId('workspace-files-attach-input');
    // Initially only the fetched input is present.
    expect(await screen.findByTestId('input-row-in1')).toBeTruthy();
    fireEvent.change(input, { target: { files: [new File(['x'], 'attached.txt', { type: 'text/plain' })] } });
    // After the attach resolves, the rail shows the newly-returned ref.
    expect(await screen.findByTestId('input-row-new1')).toBeTruthy();
  });

  it('no-emoji guard: the attach affordance renders no emoji', async () => {
    const { container } = render(<WorkspaceFilesRail threadId="t1" taskId="wi-1" />);
    await screen.findByTestId('workspace-files-attach');
    expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
