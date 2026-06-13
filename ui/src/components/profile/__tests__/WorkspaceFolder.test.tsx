// AD-999: WorkspaceFolder render tests. Read-only view of an agent's
// code-execution working folder (AD-997/998), shown in the profile Work tab.
// Uses the `deps` injection so no global fetch mock is needed. HXI #3 (no
// emoji) is asserted.
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { WorkspaceFolder, formatBytes, type WorkspaceInfo } from '../WorkspaceFolder';

afterEach(cleanup);

const EMOJI = /\p{Extended_Pictographic}/u;

function info(over: Partial<WorkspaceInfo> = {}): WorkspaceInfo {
  return {
    enabled: true,
    persistent: true,
    root: '/data/ws',
    path: '/data/ws/ezri',
    owner: 'ezri',
    exists: true,
    files: [],
    total_bytes: 0,
    ...over,
  };
}

describe('AD-999 WorkspaceFolder', () => {
  it('shows the loading placeholder before the fetch resolves', () => {
    const fetchWorkspace = vi.fn(() => new Promise<never>(() => {}));
    render(<WorkspaceFolder agentId="ezri" deps={{ fetchWorkspace }} />);
    expect(screen.getByTestId('workspace-loading')).toBeTruthy();
  });

  it('reports disabled when code execution is off', async () => {
    const fetchWorkspace = vi.fn(async () => info({ enabled: false, path: null }));
    render(<WorkspaceFolder agentId="ezri" deps={{ fetchWorkspace }} />);
    await waitFor(() => screen.getByTestId('workspace-folder'));
    expect(screen.getByTestId('workspace-folder').textContent).toContain('disabled');
  });

  it('reports nothing-persisted when ephemeral', async () => {
    const fetchWorkspace = vi.fn(async () => info({ persistent: false, path: null }));
    render(<WorkspaceFolder agentId="ezri" deps={{ fetchWorkspace }} />);
    await waitFor(() => screen.getByTestId('workspace-folder'));
    expect(screen.getByTestId('workspace-folder').textContent).toContain('Ephemeral');
  });

  it('shows the path and "no files yet" when enabled but empty', async () => {
    const fetchWorkspace = vi.fn(async () => info({ files: [] }));
    render(<WorkspaceFolder agentId="ezri" deps={{ fetchWorkspace }} />);
    await waitFor(() => screen.getByTestId('workspace-path'));
    expect(screen.getByTestId('workspace-path').textContent).toBe('/data/ws/ezri');
    expect(screen.getByTestId('workspace-folder').textContent).toContain('No files yet');
  });

  it('lists files with sizes and a total', async () => {
    const fetchWorkspace = vi.fn(async () => info({
      files: [
        { name: 'result.txt', is_dir: false, size_bytes: 2048, modified: 1 },
        { name: '.venv', is_dir: true, size_bytes: 5_000_000, modified: 1 },
      ],
      total_bytes: 5_002_048,
    }));
    render(<WorkspaceFolder agentId="ezri" deps={{ fetchWorkspace }} />);
    await waitFor(() => screen.getByTestId('workspace-file-result.txt'));
    expect(screen.getByTestId('workspace-file-result.txt').textContent).toContain('2.0 KB');
    // Directory entry shown with a trailing slash.
    expect(screen.getByTestId('workspace-file-.venv').textContent).toContain('.venv/');
    expect(screen.getByTestId('workspace-folder').textContent).toContain('2 items');
  });

  it('shows an error state when the fetch fails', async () => {
    const fetchWorkspace = vi.fn(async () => { throw new Error('boom'); });
    render(<WorkspaceFolder agentId="ezri" deps={{ fetchWorkspace }} />);
    await waitFor(() => expect(screen.getByTestId('workspace-folder').textContent).toContain('Could not load'));
  });

  it('refetches when agentId changes', async () => {
    const fetchWorkspace = vi.fn(async () => info());
    const { rerender } = render(<WorkspaceFolder agentId="ezri" deps={{ fetchWorkspace }} />);
    await waitFor(() => screen.getByTestId('workspace-path'));
    rerender(<WorkspaceFolder agentId="yeo" deps={{ fetchWorkspace }} />);
    await waitFor(() => expect(fetchWorkspace.mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(fetchWorkspace).toHaveBeenLastCalledWith('yeo');
  });

  it('formatBytes renders B / KB / MB', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(5_000_000)).toBe('4.8 MB');
  });

  it('contains no emoji (HXI #3)', async () => {
    const fetchWorkspace = vi.fn(async () => info({
      files: [{ name: 'a.txt', is_dir: false, size_bytes: 1, modified: 1 }],
    }));
    const { container } = render(<WorkspaceFolder agentId="ezri" deps={{ fetchWorkspace }} />);
    await waitFor(() => screen.getByTestId('workspace-path'));
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
  });
});
