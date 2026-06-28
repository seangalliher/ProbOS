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
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

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

import { fetchThreadInputs } from '../../inputs/inputsApi';
import { fetchThreadArtifacts } from '../../artifacts/artifactApi';
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
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
});

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
});
