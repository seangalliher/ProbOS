/** AD-797 (Wave 197) vitest — ArtifactDrawer list-render with pinned badge. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { useStore, type ArtifactView } from '../store/useStore';
import { ArtifactDrawer } from '../components/artifacts/ArtifactDrawer';

function art(over: Partial<ArtifactView>): ArtifactView {
  return {
    id: 'a1', thread_id: 't1', name: 'x.md', version: 1,
    content_hash: 'h1', mime: 'text/markdown', size_bytes: 10,
    created_by: 'agent', created_at: 1, supersedes: null,
    _pinned_from_project: false, ...over,
  };
}

beforeEach(() => {
  localStorage.clear();
  useStore.setState({
    activeThreadId: 't1',
    chatThreads: new Map([
      ['t1', { id: 't1', title: 'T1', participants: ['a'], created_at: 1, last_active_at: 1 }],
    ]),
    artifactsByThread: new Map([
      ['t1', [
        art({ id: 'a1', name: 'native.md' }),
        art({ id: 'a2', name: 'pinned.md', _pinned_from_project: true }),
      ]],
    ]),
    selectedArtifactId: null,
    artifactDrawerCollapsed: false,
  });
  // Block real fetches.
  global.fetch = vi.fn((url: any) => {
    const u = String(url);
    if (u.endsWith('/content')) {
      return Promise.resolve({
        ok: true,
        headers: { get: (k: string) => k.toLowerCase() === 'content-type' ? 'text/markdown' : null },
        blob: async () => new Blob(['# x'], { type: 'text/markdown' }),
      }) as any;
    }
    return Promise.resolve({
      ok: true, json: async () => ({ thread_id: 't1', artifacts: [
      { ...art({ id: 'a1', name: 'native.md' }) },
      { ...art({ id: 'a2', name: 'pinned.md', _pinned_from_project: true }) },
    ]}),
    }) as any;
  });
});

afterEach(() => { cleanup(); });

describe('ArtifactDrawer list-render', () => {
  it('renders names + version chips + pinned badge for project-pinned rows', async () => {
    render(<ArtifactDrawer />);
    await waitFor(() => {
      expect(screen.getByTestId('artifact-list')).toBeInTheDocument();
    });
    // Scope assertions to the list (the viewer also renders the active
    // artifact's name in its toolbar, which would otherwise collide).
    expect(screen.getByTestId('artifact-row-a1')).toHaveTextContent('native.md');
    expect(screen.getByTestId('artifact-row-a2')).toHaveTextContent('pinned.md');
    expect(screen.getByTestId('artifact-pinned-badge-a2')).toBeInTheDocument();
    expect(screen.queryByTestId('artifact-pinned-badge-a1')).not.toBeInTheDocument();
  });
});
